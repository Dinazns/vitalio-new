"""HTTP routes — patient_routes."""
import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone, date
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, request, jsonify, g, Response
from pymongo.errors import PyMongoError
from bson import ObjectId

from app.ml import engine as ml_module
from app.config import (
    FRONTEND_URL, INVITE_TTL_HOURS, CABINET_CODE_TTL_MINUTES_DEFAULT,
    SMTP_HOST, SMTP_USER, SMTP_PASSWORD,
    ALERT_DEFAULT_CONSECUTIVE_BREACHES,
)
from app.database import get_identity_db, get_medical_db
from app.exceptions import AuthError, DatabaseError
from app.auth import (
    requires_auth, requires_role, get_current_user_role, get_user_role,
    _extract_profile_from_jwt, _sanitize_person_name,
)
from app.services.user_service import (
    get_device_ids, get_device_id, get_device_measurements,
    get_device_status,
    get_assigned_patient_ids_for_doctor, get_assigned_patient_ids_for_caregiver,
    get_assigned_doctor_ids_for_patient, get_assigned_caregiver_ids_for_patient,
    ensure_patient_access_or_403, resolve_patient_id_to_user_id_auth, get_user_db_id,
    parse_iso_datetime, normalize_user_id_auth, get_user_profile, _split_display_name,
    datetime_to_iso_utc, get_address_dict_from_profile,
)
from app.services.invitation_service import (
    hash_secret_token, generate_invite_token, generate_cabinet_code,
    log_link_audit_event, create_doctor_patient_link, get_invite_document_or_404,
    send_invitation_email, invite_emergency_contact_if_needed, log_caregiver_audit_event,
)
from app.services.auth0_service import create_auth0_user_if_not_exists
from app.services.terms_service import CURRENT_TERMS_VERSION, get_terms_status, accept_terms
from app.services.measurement_service import (
    query_patient_measurements, query_patient_measurements_for_devices,
    count_patient_measurements_total,
    query_patient_measurements_range, list_latest_doctor_feedback,
    build_assigned_patients_payload, build_trend_window,
    normalize_patient_measurement_payload,
)
from app.services.alert_service import (
    evaluate_measurement_alerts, merge_thresholds, get_alert_threshold_config,
    create_manual_alert, write_alert_event,
)
from app.services.ml_retrain_runner import do_ml_retrain
from app.services.alert_messages import format_alert_for_doctor, format_alert_for_caregiver
from app.services.severity_level import SEVERITY_URGENCY, resolve_alert_severity_level
from app.services.ml_service import run_ml_scoring
from app.services.ml_retrain_scheduler import schedule_retrain_after_new_measurement
from app.services.alert_ml_audit import create_or_merge_alert_for_validated_ml
from app.services.ml_thresholds_store import save_ml_thresholds_to_db
from app.services.patient_data_portability import build_patient_export, erase_patient_all_data
from app.services.audit_service import log_audit_event, query_audit_log
from app.services.field_encryption import encrypt_profile_fields
from app.services.patient_pseudo_service import ensure_patient_pseudo_id, attach_patient_pseudo_to_doc
from app.api.helpers.audit_helpers import audit_actor_role
from app.api.helpers.alert_helpers import sanitize_alert_dict, finalize_alert_api_payload
from app.api.helpers.weekly_analysis import (
    weekly_summary_max_severity,
    build_lay_patient_weekly_summary,
)
from app.api.helpers.doctor_helpers import (
    normalize_email,
    resolve_patient_id,
    apply_patient_device_assignment,
    admin_user_summary,
    build_combined_anomaly_summary_for_analysis,
)

logger = logging.getLogger(__name__)

patient_bp = Blueprint("patient", __name__)

@patient_bp.route("/api/me/export-data", methods=["GET"])
@requires_auth
@requires_role("patient")
def export_my_patient_data():
    """Export JSON de toutes les données VitalIO liées au patient authentifié."""
    uid = g.user_id_auth
    try:
        payload = build_patient_export(uid)
    except DatabaseError:
        raise
    log_audit_event(
        event_type="patient_data_export",
        actor_user_id_auth=uid,
        actor_role=audit_actor_role(),
        resource_type="patient",
        resource_id=uid,
        action="export",
        details={"endpoint": "/api/me/export-data"},
        request=request,
    )
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"vitalio-export-{ts}.json"
    return Response(
        raw,
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@patient_bp.route("/api/me/account-data", methods=["DELETE"])
@requires_auth
@requires_role("patient")
def delete_my_patient_account_data():
    """
    Supprime profil, appareils, mesures, alertes, liens médecin/aidant côté VitalIO.
    Le compte Auth0 reste : le client doit déconnecter après succès.
    """
    body = request.get_json(silent=True) or {}
    if body.get("confirm") != "SUPPRIMER_MES_DONNEES":
        return jsonify({
            "code": "confirmation_required",
            "message": 'Confirmation requise : envoyer {"confirm":"SUPPRIMER_MES_DONNEES"} dans le corps JSON.',
        }), 400
    uid = g.user_id_auth
    log_audit_event(
        event_type="patient_data_erasure",
        actor_user_id_auth=uid,
        actor_role=audit_actor_role(),
        resource_type="patient",
        resource_id=uid,
        action="delete",
        details={"endpoint": "/api/me/account-data"},
        request=request,
    )
    try:
        counts = erase_patient_all_data(uid)
    except DatabaseError:
        raise
    return jsonify({
        "message": "Toutes vos données VitalIO ont été supprimées. Vous pouvez vous déconnecter.",
        "deleted": counts,
    }), 200


@patient_bp.route("/api/me/device", methods=["GET"])
@requires_auth
@requires_role("patient")
def get_patient_me_device():
    """Identifiant(s) du boîtier ; attribution médecin et confirmation email (device_enrollments)."""
    device_ids = get_device_ids(g.user_id_auth)
    ud = None
    try:
        ud = get_identity_db().users_devices.find_one({"user_id_auth": g.user_id_auth})
    except PyMongoError as e:
        logger.warning("users_devices lookup failed in get_patient_me_device: %s", e)

    doctor_assigned = bool(ud and ud.get("assigned_by"))
    primary_id = device_ids[0] if device_ids else None
    device_enrolled = False
    if primary_id:
        try:
            enr = get_identity_db().device_enrollments.find_one(
                {"device_id": primary_id, "enrolled": True},
                projection={"_id": 1},
            )
            device_enrolled = enr is not None
        except PyMongoError as e:
            logger.warning("device_enrollments lookup failed: %s", e)

    if not device_ids:
        return jsonify({
            "device_id": None,
            "device_ids": [],
            "doctor_assigned_device": False,
            "device_enrolled": False,
        }), 200
    return jsonify({
        "device_id": device_ids[0],
        "device_ids": device_ids,
        "doctor_assigned_device": doctor_assigned,
        "device_enrolled": device_enrolled,
    }), 200


@patient_bp.route("/api/me/data", methods=["GET"])
@requires_auth
@requires_role("patient")
def get_patient_data():
    device_id = get_device_id(g.user_id_auth)
    if not device_id:
        raise DatabaseError({"code": "device_not_found", "message": "No device record found for authenticated user"}, 404)
    measurements = get_device_measurements(device_id)
    return jsonify({"device_id": device_id, "measurements": measurements, "measurement_count": len(measurements)}), 200


def weekly_summary_max_severity(analysis: Dict[str, Any]) -> int:
    """Highest severity from point anomalies, drift alerts, and per-measurement ML levels."""
    rank = {"critical": 3, "warning": 2, "mild": 1, "moderate": 2, "negligible": 0, "normal": 0, "strong": 3}
    max_s = 0
    for feat in ("heart_rate", "spo2", "temperature"):
        info = (analysis.get("vitals") or {}).get(feat) or {}
        if info.get("status") != "ok":
            continue
        for ap in info.get("anomalous_points") or []:
            max_s = max(max_s, rank.get(str(ap.get("severity", "")), 0))
        for alert in info.get("clinical_alerts") or []:
            max_s = max(max_s, rank.get(str(alert.get("severity", "")), 0))
    for p in analysis.get("timeline") or []:
        if p.get("ml_level") == "critical":
            max_s = max(max_s, 3)
        elif p.get("ml_level") == "warning":
            max_s = max(max_s, 2)
    return max_s


def _weekly_risk_bundle(max_severity: int) -> Tuple[str, str, str]:
    """risk_level, recommended_action (clinical), recommended_action (plain language for patients)."""
    if max_severity >= 3:
        return (
            "high",
            "Consultez votre médecin ou un professionnel de santé pour interpréter ces variations.",
            "Si vous ne vous sentez pas bien (douleur, essoufflement, malaise), appelez vite votre médecin ou le 15.",
        )
    if max_severity >= 2:
        return (
            "moderate",
            "Restez vigilant aux prochaines mesures ; en cas de symptômes ou persistance des alertes, demandez un avis médical.",
            "Poursuivez le suivi à domicile. Si l'inquiétude ou des symptômes durent plus de quelques jours, contactez votre médecin ou votre infirmier.",
        )
    if max_severity >= 1:
        return (
            "low",
            "Poursuivez la surveillance habituelle et signalez tout changement notable à votre soignant.",
            "Continuez vos mesures comme d'habitude. Prévenez la personne qui s'occupe de vous en cas de changement net.",
        )
    return (
        "minimal",
        "Pas d'action particulière nécessaire ; continuez vos mesures régulières.",
        "Rien de particulier à changer si vous vous sentez bien. Continuez simplement à enregistrer vos relevés.",
    )


def _period_intro_phrase(analysis: Dict[str, Any]) -> Optional[Tuple[int, str]]:
    n_meas = analysis.get("n_measurements", 0)
    span_h = analysis.get("time_span_hours")
    if not n_meas or span_h is None:
        return None
    if span_h < 24:
        period_txt = f"environ {max(1, int(round(span_h)) or 1)} heure(s)"
    else:
        period_txt = f"environ {max(span_h / 24.0, 0.1):.1f} jour(s)"
    return (n_meas, period_txt)


def _build_clinical_weekly_narrative(analysis: Dict[str, Any], max_severity: int) -> Dict[str, Any]:
    """Detailed, statistical narrative for clinicians (médecin / équipe soignante)."""
    if analysis.get("status") == "insufficient_data":
        return {
            "text": "Pas assez de données pour générer un résumé. Continuez à enregistrer vos mesures.",
            "risk_level": "unknown",
            "recommended_action": "Enregistrer plus de mesures cette semaine.",
        }
    vitals = analysis.get("vitals", {})
    labels_fr = {"heart_rate": "Fréquence cardiaque", "spo2": "Oxygène dans le sang", "temperature": "Température"}
    feat_order = ("heart_rate", "spo2", "temperature")
    paragraphs: List[str] = []
    vital_paragraph_count = 0

    intro = _period_intro_phrase(analysis)
    if intro:
        n_meas, period_txt = intro
        paragraphs.append(
            f"Analyse basée sur {n_meas} mesure(s) sur {period_txt}. "
            "Le détail ci-dessous complète les moyennes par la dispersion, la tendance globale et les points atypiques."
        )

    for feat in feat_order:
        info = vitals.get(feat)
        if not info or info.get("status") != "ok":
            continue
        stats = info.get("statistics") or {}
        trend = info.get("trend") or {}
        unit = info.get("unit", "")
        label = labels_fr.get(feat, feat)
        mean_val = stats.get("mean")
        if mean_val is None:
            continue

        mn = stats.get("min")
        mx = stats.get("max")
        med = stats.get("median")
        std = stats.get("std")
        cv = stats.get("cv")

        parts: List[str] = []
        if unit in ("bpm", "%"):
            parts.append(
                f"{label} : valeurs observées entre {mn:.0f} et {mx:.0f} {unit}, "
                f"médiane {med:.0f} {unit}, moyenne {mean_val:.0f} {unit}."
            )
        else:
            parts.append(
                f"{label} : valeurs entre {mn:.1f} et {mx:.1f} {unit}, "
                f"médiane {med:.1f} {unit}, moyenne {mean_val:.1f} {unit}."
            )

        if cv is not None and feat == "heart_rate" and cv >= 12:
            parts.append(
                "La variabilité est marquée : l'écart entre les mesures est important, "
                "donc la moyenne seule ne résume pas bien l'activité récente (pics et creux possibles)."
            )
        elif cv is not None and feat == "spo2" and cv >= 5:
            parts.append(
                "Des écarts notables autour de la moyenne sont visibles ; la série n'est pas strictement plate, "
                "ce qui mérite d'être regardé avec les mesures les plus récentes."
            )

        series = info.get("series") or []
        if len(series) >= 3:
            last_vals = [float(series[i]["value"]) for i in range(-3, 0)]
            recent_mean = sum(last_vals) / len(last_vals)
            if med is not None and std is not None and float(std) > 1e-6:
                if recent_mean > float(med) + 0.8 * float(std):
                    parts.append(
                        "Les toutes dernières mesures sont nettement plus hautes que le niveau médian de la semaine."
                    )
                elif recent_mean < float(med) - 0.8 * float(std):
                    parts.append(
                        "Les toutes dernières mesures sont nettement plus basses que le niveau médian de la semaine."
                    )

        t_label = trend.get("label", "stable")
        t_strength = trend.get("strength", "negligible")
        t_sig = bool(trend.get("significant"))
        spd = abs(float(trend.get("slope_per_day", 0) or 0))
        if t_label == "stable" or t_strength in ("negligible", "normal") or not t_sig:
            parts.append(
                "Tendance sur la période : globalement stable (pas de pente nette et statistiquement fiable sur l'ensemble des jours)."
            )
        else:
            direction_fr = "à la hausse" if t_label == "increasing" else "à la baisse"
            strength_fr = {"mild": "légère", "moderate": "modérée", "strong": "marquée"}.get(t_strength, t_strength)
            unit_day = unit if unit else "unité"
            parts.append(
                f"Tendance sur la période : évolution {direction_fr}, d'intensité {strength_fr} "
                f"(ordre de grandeur ~{spd:.1f} {unit_day} par jour)."
            )

        n_anom = int(info.get("n_anomalies") or 0)
        if n_anom > 0:
            parts.append(
                f"{n_anom} mesure(s) ressortent comme atypiques (hors plage attendue ou outlier statistique) sur cette série."
            )

        for alert in info.get("clinical_alerts") or []:
            msg = alert.get("message")
            if msg:
                parts.append(msg)

        paragraphs.append(" ".join(parts))
        vital_paragraph_count += 1

    correlations = analysis.get("correlations") or {}
    hr_spo2 = (correlations.get("heart_rate") or {}).get("spo2")
    if hr_spo2 is not None and abs(float(hr_spo2)) >= 0.45:
        sense = "varient souvent dans le même sens" if float(hr_spo2) > 0 else "varient souvent en sens opposé"
        paragraphs.append(
            f"Lien entre fréquence cardiaque et oxygénation : corrélation notable ({float(hr_spo2):.2f}) — les deux courbes {sense} "
            "sur la semaine, ce qui peut correspondre à des épisodes conjoints à interpréter avec un professionnel de santé si cela vous concerne."
        )

    timeline = analysis.get("timeline") or []
    ml_warn = sum(1 for p in timeline if p.get("ml_level") == "warning")
    ml_crit = sum(1 for p in timeline if p.get("ml_level") == "critical")
    if ml_crit or ml_warn:
        paragraphs.append(
            f"Modèle d'aide à l'analyse : {ml_crit + ml_warn} mesure(s) classées en vigilance ou alerte sur la période "
            f"({ml_crit} critique(s), {ml_warn} vigilance(s)) — à rapprocher des valeurs brutes et de votre ressenti."
        )

    if vital_paragraph_count == 0:
        if len(paragraphs) == 0:
            return {
                "text": "Vos constantes vitales de la semaine sont dans les plages habituelles.",
                "risk_level": "minimal",
                "recommended_action": "Continuez à surveiller vos mesures.",
            }
        risk, action_clin, _ = _weekly_risk_bundle(max_severity)
        return {"text": "\n\n".join(paragraphs), "risk_level": risk, "recommended_action": action_clin}

    risk, action_clin, _ = _weekly_risk_bundle(max_severity)
    return {"text": "\n\n".join(paragraphs), "risk_level": risk, "recommended_action": action_clin}


def build_lay_patient_weekly_summary(analysis: Dict[str, Any], max_severity: int) -> Dict[str, Any]:
    """Short, accessible French summary for patients and non-specialists."""
    if analysis.get("status") == "insufficient_data":
        return {
            "text": "Il nous manque encore des mesures pour parler de votre semaine avec précision. "
            "Continuez à enregistrer vos constantes comme d'habitude.",
            "risk_level": "unknown",
            "recommended_action": "Enregistrer un peu plus de mesures sur les prochains jours.",
        }
    vitals = analysis.get("vitals", {})
    labels_lay = {
        "heart_rate": "Votre pouls",
        "spo2": "L'oxygène dans votre sang",
        "temperature": "Votre température",
    }
    feat_order = ("heart_rate", "spo2", "temperature")
    paragraphs: List[str] = []
    vital_paragraph_count = 0

    intro = _period_intro_phrase(analysis)
    if intro:
        n_meas, period_txt = intro
        paragraphs.append(
            f"Vous avez enregistré {n_meas} mesure(s) sur {period_txt}. "
            "Voici ce que l'on peut en dire, avec des mots simples. "
            "Ce résumé ne remplace pas l'avis d'un médecin ou d'une infirmière."
        )

    for feat in feat_order:
        info = vitals.get(feat)
        if not info or info.get("status") != "ok":
            continue
        stats = info.get("statistics") or {}
        trend = info.get("trend") or {}
        unit = info.get("unit", "")
        label = labels_lay.get(feat, feat)
        mean_val = stats.get("mean")
        if mean_val is None:
            continue

        mn = stats.get("min")
        mx = stats.get("max")
        med = stats.get("median")
        std = stats.get("std")
        cv = stats.get("cv")
        if mn is None or mx is None or med is None:
            continue

        parts: List[str] = []
        if feat == "heart_rate":
            parts.append(
                f"{label} : les relevés vont de {mn:.0f} à {mx:.0f} battements par minute. "
                f"La moyenne sur la période est d'environ {mean_val:.0f}, et en pratique vos mesures se situent souvent vers {med:.0f}."
            )
        elif feat == "spo2":
            parts.append(
                f"{label} : les taux vont de {mn:.0f} à {mx:.0f} pour cent. "
                f"La moyenne est d'environ {mean_val:.0f} pour cent, et le plus souvent autour de {med:.0f} pour cent."
            )
        else:
            parts.append(
                f"{label} : entre {mn:.1f} et {mx:.1f} °C, avec une moyenne d'environ {mean_val:.1f} °C."
            )

        if cv is not None and feat == "heart_rate" and cv >= 12:
            parts.append(
                "Les chiffres du pouls montent et descendent beaucoup d'une mesure à l'autre : "
                "une moyenne seule ne dit pas tout sur ce que vous avez vécu sur la période."
            )
        elif cv is not None and feat == "spo2" and cv >= 5:
            parts.append(
                "L'oxygène n'est pas resté strictement au même niveau tout le temps ; "
                "il est utile de regarder aussi vos dernières mesures."
            )

        series = info.get("series") or []
        if len(series) >= 3:
            last_vals = [float(series[i]["value"]) for i in range(-3, 0)]
            recent_mean = sum(last_vals) / len(last_vals)
            if med is not None and std is not None and float(std) > 1e-6:
                if recent_mean > float(med) + 0.8 * float(std):
                    parts.append("Vos toutes dernières mesures sont plutôt plus hautes que d'habitude pour vous sur cette période.")
                elif recent_mean < float(med) - 0.8 * float(std):
                    parts.append("Vos toutes dernières mesures sont plutôt plus basses que d'habitude pour vous sur cette période.")

        t_label = trend.get("label", "stable")
        t_strength = trend.get("strength", "negligible")
        t_sig = bool(trend.get("significant"))
        if t_label == "stable" or t_strength in ("negligible", "normal") or not t_sig:
            parts.append("Sur l'ensemble des jours, la tendance reste plutôt stable.")
        else:
            direction = "augmenter" if t_label == "increasing" else "diminuer"
            intens = {"mild": "un peu", "moderate": "modérément", "strong": "nettement"}.get(t_strength, "")
            phrase = f"Sur la période, les valeurs ont plutôt tendance à {direction}"
            if intens:
                phrase += f" {intens}"
            phrase += "."
            parts.append(phrase)

        n_anom = int(info.get("n_anomalies") or 0)
        if n_anom > 0:
            parts.append(
                f"{n_anom} mesure(s) ont été signalées comme inhabituelles par le système ; "
                "votre équipe soignante peut vous aider à comprendre si c'est normal dans votre situation."
            )

        if info.get("clinical_alerts"):
            parts.append(
                "Une alerte de suivi automatique signale une évolution à garder à l'œil ; "
                "parlez-en à votre médecin si vous ne savez pas quoi en penser."
            )

        paragraphs.append(" ".join(parts))
        vital_paragraph_count += 1

    correlations = analysis.get("correlations") or {}
    hr_spo2 = (correlations.get("heart_rate") or {}).get("spo2")
    if hr_spo2 is not None and abs(float(hr_spo2)) >= 0.45:
        together = "souvent monté ou baissé en même temps" if float(hr_spo2) > 0 else "souvent évolué en sens inverse"
        paragraphs.append(
            f"Votre pouls et votre taux d'oxygène ont {together} sur la période. "
            "En cas de doute, demandez l'avis d'un professionnel de santé."
        )

    timeline = analysis.get("timeline") or []
    ml_warn = sum(1 for p in timeline if p.get("ml_level") == "warning")
    ml_crit = sum(1 for p in timeline if p.get("ml_level") == "critical")
    if ml_crit or ml_warn:
        paragraphs.append(
            f"L'outil d'analyse a classé {ml_crit + ml_warn} de vos mesures comme devant être surveillées de plus près "
            f"({ml_crit} en niveau critique, {ml_warn} en niveau vigilance). "
            "Comparez cela avec ce que vous avez réellement ressenti."
        )

    if vital_paragraph_count == 0:
        if len(paragraphs) == 0:
            return {
                "text": "Vos constantes semblent dans des fourchettes habituelles sur la période.",
                "risk_level": "minimal",
                "recommended_action": "Continuez à prendre vos mesures comme prévu.",
            }
        risk, _, action_patient = _weekly_risk_bundle(max_severity)
        return {"text": "\n\n".join(paragraphs), "risk_level": risk, "recommended_action": action_patient}

    risk, _, action_patient = _weekly_risk_bundle(max_severity)
    return {"text": "\n\n".join(paragraphs), "risk_level": risk, "recommended_action": action_patient}


@patient_bp.route("/api/me/weekly-analysis", methods=["GET"])
@requires_auth
@requires_role("patient")
def get_patient_weekly_analysis():
    """Return last 7 days of measurements + AI summary for patient view."""
    device_id = get_device_id(g.user_id_auth)
    if not device_id:
        raise DatabaseError({"code": "device_not_found", "message": "No device record found for authenticated user"}, 404)
    measurements = query_patient_measurements_for_devices(device_ids=[device_id], days=7, limit=500)
    if not measurements:
        return jsonify({
            "device_id": device_id,
            "measurements": [],
            "measurement_count": 0,
            "summary": {
                "text": "Aucune mesure enregistrée cette semaine. Enregistrez vos constantes vitales pour obtenir une analyse.",
                "risk_level": "unknown",
                "recommended_action": "Enregistrer des mesures.",
            },
        }), 200
    try:
        analysis = ml_module.analyze_patient_vitals(measurements)
        max_sev = weekly_summary_max_severity(analysis)
        try:
            summary = build_lay_patient_weekly_summary(analysis, max_sev)
        except Exception as build_err:
            logger.warning("Weekly lay summary build failed: %s", build_err, exc_info=True)
            summary = {
                "text": "Vos mesures de la semaine sont bien prises en compte, mais le texte de synthèse n'a pas pu être généré pour le moment.",
                "risk_level": "unknown",
                "recommended_action": "Réessayez plus tard. En cas de symptômes inquiétants, contactez un professionnel de santé.",
            }
    except Exception as e:
        logger.warning("Weekly analysis failed for patient: %s", e, exc_info=True)
        summary = {
            "text": "Analyse indisponible pour le moment (erreur technique). Vos mesures restent enregistrées.",
            "risk_level": "unknown",
            "recommended_action": "Réessayez dans quelques instants.",
        }
    return jsonify({
        "device_id": device_id,
        "measurements": measurements,
        "measurement_count": len(measurements),
        "summary": summary,
    }), 200


@patient_bp.route("/api/me/measurements", methods=["POST"])
@requires_auth
@requires_role("patient")
def submit_patient_measurement():
    """Enregistre une mesure pour le boîtier associé au compte (users_devices), jamais un device_id fourni par le client."""
    device_id = get_device_id(g.user_id_auth)
    if not device_id:
        raise DatabaseError({"code": "device_not_found", "message": "No device record found for authenticated user"}, 404)
    if get_device_status(device_id) == "suspended":
        return jsonify({"code": "device_suspended", "message": "Dispositif suspendu par un administrateur"}), 403
    payload = request.get_json(silent=True) or {}
    # Ne jamais faire confiance au corps de la requête pour l’identifiant matériel : même logique que les mesures boîtier.
    if isinstance(payload, dict):
        payload = {k: v for k, v in payload.items() if k != "device_id"}
    try:
        normalized = normalize_patient_measurement_payload(payload)
    except ValueError as validation_error:
        return jsonify({"code": "invalid_payload", "message": str(validation_error)}), 400

    measurement_doc = {
        "device_id": device_id, "measured_at": normalized["measured_at"],
        "heart_rate": normalized["heart_rate"], "spo2": normalized["spo2"],
        "temperature": normalized["temperature"], "signal_quality": normalized["signal_quality"],
        "source": normalized["source"], "status": normalized["status"],
        "validation_reasons": normalized["reasons"],
    }
    attach_patient_pseudo_to_doc(measurement_doc, user_id_auth=g.user_id_auth)
    try:
        ins = get_medical_db().measurements.insert_one(measurement_doc)
        measurement_doc["_id"] = ins.inserted_id
    except PyMongoError as e:
        raise DatabaseError({"code": "measurement_insert_error", "message": f"Failed to insert measurement: {str(e)}"}, 500)

    triggered_alerts = []
    try:
        prof = get_user_profile(g.user_id_auth)
        pathology_ctx = (prof.get("pathology") or "").strip() or None
        triggered_alerts = evaluate_measurement_alerts(
            device_id=device_id, measurement=measurement_doc, pathology=pathology_ctx
        )
    except PyMongoError as e:
        logger.warning("Alert evaluation failed for device %s: %s", device_id, e)

    ml_result: Dict[str, Any] = {}
    try:
        ml_result = run_ml_scoring(device_id=device_id, measurement_doc=measurement_doc)
    except Exception as e:
        logger.warning("ML scoring failed for device %s: %s", device_id, e)

    if normalized["status"] == "VALID":
        try:
            schedule_retrain_after_new_measurement(device_id)
        except Exception as e:
            logger.warning("Schedule ML retrain after patient measurement failed: %s", e)

    return jsonify({
        "message": "Measurement stored successfully",
        "device_id": device_id,
        "measurement": {
            "timestamp": datetime_to_iso_utc(normalized["measured_at"]),
            "heart_rate": normalized["heart_rate"], "spo2": normalized["spo2"],
            "temperature": normalized["temperature"], "signal_quality": normalized["signal_quality"],
            "status": normalized["status"], "validation_reasons": normalized["reasons"],
            "source": normalized["source"],
        },
        "alerts_triggered": triggered_alerts,
        "ml": {
            "score": ml_result.get("ml_score"), "level": ml_result.get("ml_level"),
            "model_version": ml_result.get("ml_model_version"),
            "contributing_variables": ml_result.get("ml_contributing_variables", []),
            "skipped": ml_result.get("ml_skipped", False),
        } if ml_result else None,
    }), 201


@patient_bp.route("/api/patient/invitations/accept", methods=["POST"])
@requires_auth
@requires_role("patient")
def accept_doctor_invitation():
    payload = request.get_json(silent=True) or {}
    invite_token = str(payload.get("invite_token") or "").strip()
    if not invite_token:
        return jsonify({"code": "invalid_payload", "message": "invite_token is required"}), 400
    invite = get_invite_document_or_404(invite_token, mode="invite_link")
    if invite.get("patient_user_id_auth") and invite["patient_user_id_auth"] != g.user_id_auth:
        raise AuthError({"code": "forbidden_invitation", "message": "This invitation is targeted to another patient"}, 403)
    doctor_user_id_auth = invite.get("doctor_user_id_auth")
    created = create_doctor_patient_link(doctor_user_id_auth, g.user_id_auth, "patient_accept_invite", g.user_id_auth)
    if not created:
        raise AuthError({"code": "association_exists", "message": "Doctor-patient association already exists"}, 409)

    meta = invite.get("metadata") or {}
    pending_device = str(meta.get("device_id") or "").strip()
    device_assigned = False
    device_assignment_error = None
    if pending_device:
        res = apply_patient_device_assignment(g.user_id_auth, pending_device, doctor_user_id_auth)
        if res[0]:
            device_assigned = True
        else:
            device_assignment_error = res[1].get("message")
            logger.warning(
                "Invite accept: device %s not assigned to %s: %s",
                pending_device,
                g.user_id_auth,
                device_assignment_error,
            )

    now = datetime.now(timezone.utc)
    get_identity_db().doctor_invites.update_one(
        {"_id": invite["_id"], "used_at": None},
        {"$set": {"used_at": now, "used_by_user_id_auth": g.user_id_auth}}
    )
    log_link_audit_event("invite_accepted", g.user_id_auth, doctor_user_id_auth, g.user_id_auth, "invite_link",
                         {"invite_created_at": str(invite.get("created_at"))})
    body: Dict[str, Any] = {
        "message": "Invitation accepted",
        "doctor_user_id_auth": doctor_user_id_auth,
        "patient_user_id_auth": g.user_id_auth,
        "device_assigned": device_assigned,
    }
    if pending_device:
        body["pending_device_id"] = pending_device
    if device_assignment_error:
        body["device_assignment_error"] = device_assignment_error
    return jsonify(body), 201


@patient_bp.route("/api/patient/cabinet-codes/redeem", methods=["POST"])
@requires_auth
@requires_role("patient")
def redeem_cabinet_code():
    payload = request.get_json(silent=True) or {}
    code = str(payload.get("code") or "").strip().upper()
    if not code:
        return jsonify({"code": "invalid_payload", "message": "code is required"}), 400
    invite = get_invite_document_or_404(code, mode="cabinet_code")
    doctor_user_id_auth = invite.get("doctor_user_id_auth")
    created = create_doctor_patient_link(doctor_user_id_auth, g.user_id_auth, "cabinet_code", g.user_id_auth)
    if not created:
        raise AuthError({"code": "association_exists", "message": "Doctor-patient association already exists"}, 409)
    now = datetime.now(timezone.utc)
    get_identity_db().doctor_invites.update_one(
        {"_id": invite["_id"], "used_at": None},
        {"$set": {"used_at": now, "used_by_user_id_auth": g.user_id_auth}}
    )
    log_link_audit_event("cabinet_code_redeemed", g.user_id_auth, doctor_user_id_auth, g.user_id_auth, "cabinet_code",
                         {"invite_created_at": str(invite.get("created_at"))})
    return jsonify({"message": "Cabinet code redeemed", "doctor_user_id_auth": doctor_user_id_auth,
                    "patient_user_id_auth": g.user_id_auth}), 201


