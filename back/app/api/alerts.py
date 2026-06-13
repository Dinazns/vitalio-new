"""HTTP routes — alert_routes."""
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

alert_bp = Blueprint("alerts", __name__)

@alert_bp.route("/api/patient/alerts", methods=["POST"])
@requires_auth
@requires_role("patient")
def patient_trigger_manual_alert():
    """Patient manually triggers a critical alert via the app button."""
    device_id = get_device_id(g.user_id_auth)
    if not device_id:
        raise DatabaseError({"code": "device_not_found", "message": "No device record found"}, 404)
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message") or "").strip()[:500] or None

    result = create_manual_alert(
        device_id=device_id,
        patient_user_id_auth=g.user_id_auth,
        message=message,
    )
    if not result["created"]:
        reason = result["reason"]
        if reason == "cooldown":
            wait = result.get("wait_seconds") or 0
            return jsonify({
                "code": "rate_limited",
                "message": f"Veuillez patienter {wait} secondes avant de déclencher une nouvelle alerte.",
                "wait_seconds": wait,
            }), 429
        return jsonify({
            "code": "rate_limited",
            "message": "Limite horaire d'alertes manuelles atteinte. Appelez le 15 en cas d'urgence réelle.",
        }), 429

    alert_id = result["alert_id"]
    profile = get_user_profile(g.user_id_auth)
    patient_name = profile.get("display_name") or profile.get("email") or "Un patient"

    try:
        from app.services.invitation_service import send_alert_emails_for_new_alert
        send_alert_emails_for_new_alert(
            device_id=device_id, metric="manual", operator="manual",
            value=0, threshold=0, patient_name=patient_name,
        )
    except Exception as exc:
        logger.warning("Manual alert email send failed: %s", exc)

    try:
        from app.services.webpush_service import send_manual_alert_push_notifications
        send_manual_alert_push_notifications(
            device_id=device_id, patient_name=patient_name, patient_message=message,
        )
    except Exception as exc:
        logger.warning("Manual alert push send failed: %s", exc)

    log_audit_event(
        event_type="alert_manual_trigger",
        actor_user_id_auth=g.user_id_auth,
        actor_role=audit_actor_role(),
        resource_type="alert",
        resource_id=alert_id,
        action="create",
        details={"device_id": device_id, "endpoint": "/api/patient/alerts"},
        request=request,
    )

    return jsonify({
        "message": "Alerte envoyée. Votre médecin et votre aidant ont été notifiés.",
        "alert_id": alert_id,
    }), 201


def normalize_email(email_raw: str):
    if not email_raw or not isinstance(email_raw, str):
        return None
    s = str(email_raw).strip().lower()
    return s if "@" in s and "." in s and len(s) > 5 else None


# ============================================================================
# ROUTES - Doctor / Caregiver / Admin
# ============================================================================

@alert_bp.route("/api/caregiver/alerts", methods=["GET"])
@requires_auth
@requires_role("caregiver", "aidant")
def get_caregiver_alerts():
    caregiver_user_id_auth = g.user_id_auth
    status = (request.args.get("status", default="OPEN", type=str) or "OPEN").strip().upper()
    severity_level = (request.args.get("severity_level") or "").strip().upper()
    limit = min(max(request.args.get("limit", default=100, type=int), 1), 500)
    patient_ids = get_assigned_patient_ids_for_caregiver(caregiver_user_id_auth)
    if not patient_ids:
        return jsonify({"caregiver_id": caregiver_user_id_auth, "count": 0, "alerts": []}), 200
    device_by_patient = {pid: get_device_id(pid) for pid in patient_ids if get_device_id(pid)}
    device_ids = list(device_by_patient.values())
    if not device_ids:
        return jsonify({"caregiver_id": caregiver_user_id_auth, "count": 0, "alerts": []}), 200
    patient_by_device = {did: pid for pid, did in device_by_patient.items()}
    id_by_auth = {pid: str(get_user_db_id(pid) or pid) for pid in patient_ids}
    query: Dict[str, Any] = {"device_id": {"$in": device_ids}}
    if status != "ALL":
        query["status"] = status
        if status == "OPEN":
            from app.services.alert_service import open_alert_query_requires_doctor_triage

            query.update(open_alert_query_requires_doctor_triage())
    if severity_level in ("INFO", "WARNING", "CRITICAL", "URGENCY"):
        query["severity_level"] = severity_level
    cursor = get_medical_db().alerts.find(query).sort("created_at", -1).limit(limit)
    alerts = []
    for alert in cursor:
        out = format_alert_for_caregiver(dict(alert))
        out.pop("_id", None)
        sanitize_alert_dict(out)
        oid = alert.get("_id")
        out["alert_id"] = str(oid) if oid is not None else None
        for k, v in list(out.items()):
            if isinstance(v, datetime):
                out[k] = datetime_to_iso_utc(v)
        auth_id = patient_by_device.get(alert.get("device_id"))
        out["patient_id"] = id_by_auth.get(auth_id, auth_id) if auth_id else None
        out["doctor_status"] = alert.get("doctor_status", "PENDING")
        out["caregiver_resolution_comment"] = alert.get("caregiver_resolution_comment")
        out["caregiver_seen_patient"] = alert.get("caregiver_seen_patient")
        out["alert_source"] = alert.get("alert_source", "threshold")
        out["patient_message"] = alert.get("patient_message")
        finalize_alert_api_payload(dict(alert), out, auth_id, include_patient_address=False)
        alerts.append(out)
    return jsonify({"caregiver_id": caregiver_user_id_auth, "status_filter": status, "count": len(alerts), "alerts": alerts}), 200


@alert_bp.route("/api/doctor/alerts/<alert_id>", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser", "medecin")
def get_doctor_alert(alert_id: str):
    """Return a single alert with measurement context snapshot."""
    try:
        oid = ObjectId(alert_id)
    except Exception:
        return jsonify({"code": "invalid_id", "message": "alert_id is not a valid ObjectId"}), 400
    alert_doc = get_medical_db().alerts.find_one({"_id": oid})
    if not alert_doc:
        return jsonify({"code": "not_found", "message": "Alerte introuvable"}), 404
    device_id = alert_doc.get("device_id")
    patient_ids = get_assigned_patient_ids_for_doctor(g.user_id_auth)
    device_by_patient = {pid: get_device_id(pid) for pid in patient_ids if get_device_id(pid)}
    if device_id not in device_by_patient.values():
        return jsonify({"code": "forbidden", "message": "Cette alerte ne concerne pas un de vos patients"}), 403
    patient_by_device = {did: pid for pid, did in device_by_patient.items()}
    auth_id = patient_by_device.get(device_id)

    out = format_alert_for_doctor(dict(alert_doc))
    out["alert_id"] = alert_id
    out.pop("_id", None)
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = datetime_to_iso_utc(v)
    out["patient_id"] = str(get_user_db_id(auth_id) or auth_id) if auth_id else None
    out["doctor_status"] = alert_doc.get("doctor_status", "PENDING")
    out["caregiver_resolution_comment"] = alert_doc.get("caregiver_resolution_comment")
    finalize_alert_api_payload(alert_doc, out, auth_id, include_patient_address=True)

    # Triggering measurement context
    measurement_context = None
    measurement_id = alert_doc.get("measurement_id")
    if measurement_id:
        try:
            m_doc = get_medical_db().measurements.find_one({"_id": measurement_id})
            if m_doc:
                measurement_context = {
                    "measurement_id": str(measurement_id),
                    "measured_at": datetime_to_iso_utc(m_doc["measured_at"]) if isinstance(m_doc.get("measured_at"), datetime) else None,
                    "heart_rate": m_doc.get("heart_rate"),
                    "spo2": m_doc.get("spo2"),
                    "temperature": m_doc.get("temperature"),
                    "signal_quality": m_doc.get("signal_quality"),
                    "status": m_doc.get("status"),
                }
        except Exception as exc:
            logger.warning("Failed to fetch measurement context for alert %s: %s", alert_id, exc)
    if not measurement_context and device_id:
        # Fallback: last 5 measurements around alert creation
        try:
            cutoff = alert_doc.get("created_at") or datetime.now(timezone.utc)
            recent = list(get_medical_db().measurements.find(
                {"device_id": device_id, "measured_at": {"$lte": cutoff}},
                sort=[("measured_at", -1)], limit=5,
                projection={"_id": 1, "measured_at": 1, "heart_rate": 1, "spo2": 1,
                            "temperature": 1, "signal_quality": 1, "status": 1},
            ))
            measurement_context = [
                {
                    "measurement_id": str(r["_id"]),
                    "measured_at": datetime_to_iso_utc(r["measured_at"]) if isinstance(r.get("measured_at"), datetime) else None,
                    "heart_rate": r.get("heart_rate"), "spo2": r.get("spo2"),
                    "temperature": r.get("temperature"), "signal_quality": r.get("signal_quality"),
                    "status": r.get("status"),
                }
                for r in recent
            ]
        except Exception as exc:
            logger.warning("Failed to fetch recent measurements for alert %s: %s", alert_id, exc)
    out["measurement_context"] = measurement_context

    # Alert events (audit trail)
    try:
        events = list(get_medical_db().alert_events.find(
            {"medical_alert_id": alert_id},
            sort=[("created_at", 1)],
            projection={"_id": 0},
        ))
        for ev in events:
            if isinstance(ev.get("created_at"), datetime):
                ev["created_at"] = datetime_to_iso_utc(ev["created_at"])
        out["alert_events"] = events
    except Exception as exc:
        logger.warning("Failed to fetch alert_events for %s: %s", alert_id, exc)
        out["alert_events"] = []

    return jsonify(out), 200


@alert_bp.route("/api/doctor/alerts/<alert_id>", methods=["PATCH"])
@requires_auth
@requires_role("doctor", "superuser", "medecin")
def patch_doctor_alert(alert_id: str):
    """Validate or reject an alert, log emergency escalation, and/or add a clinical note."""
    payload = request.get_json(silent=True) or {}
    doctor_status = str(payload.get("doctor_status") or "").strip().upper()
    esc_raw = payload.get("emergency_escalation")
    has_escalation = isinstance(esc_raw, dict) and str(esc_raw.get("type") or "").strip() != ""
    doctor_note = str(payload.get("note") or "").strip()[:2000] or None
    if doctor_status and doctor_status not in ("VALIDATED", "REJECTED"):
        return jsonify({"code": "invalid_payload", "message": "doctor_status must be 'VALIDATED' or 'REJECTED'"}), 400
    if not doctor_status and not has_escalation and not doctor_note:
        return jsonify({
            "code": "invalid_payload",
            "message": "Provide doctor_status (VALIDATED/REJECTED), emergency_escalation { type }, and/or note",
        }), 400
    try:
        oid = ObjectId(alert_id)
    except Exception:
        return jsonify({"code": "invalid_id", "message": "alert_id is not a valid ObjectId"}), 400
    alert_doc = get_medical_db().alerts.find_one({"_id": oid})
    if not alert_doc:
        return jsonify({"code": "not_found", "message": "Alerte introuvable"}), 404
    device_id = alert_doc.get("device_id")
    patient_ids = get_assigned_patient_ids_for_doctor(g.user_id_auth)
    device_by_patient = {pid: get_device_id(pid) for pid in patient_ids if get_device_id(pid)}
    if device_id not in device_by_patient.values():
        return jsonify({"code": "forbidden", "message": "Cette alerte ne concerne pas un de vos patients"}), 403
    now = datetime.now(timezone.utc)
    response: Dict[str, Any] = {"message": "Alerte mise à jour", "alert_id": alert_id}
    if doctor_status:
        # Clôturer la file « ouvertes » : sans changement de status, l'alerte restait OPEN
        # (badges, GET ?status=OPEN, notifications « à traiter »).
        update = {
            "doctor_status": doctor_status,
            "updated_at": now,
            "status": "RESOLVED",
            "resolved_at": now,
        }
        if doctor_status == "VALIDATED":
            update["validated_by"] = g.user_id_auth
            update["validated_at"] = now
        else:
            update["rejected_by"] = g.user_id_auth
            update["rejected_at"] = now
        if doctor_note:
            update["doctor_note"] = doctor_note
            update["doctor_note_at"] = now
        get_medical_db().alerts.update_one({"_id": oid}, {"$set": update})
        event_type = "doctor_validated" if doctor_status == "VALIDATED" else "doctor_rejected"
        write_alert_event(
            medical_alert_id=alert_id,
            event_type=event_type,
            actor_user_id_auth=g.user_id_auth,
            actor_role="doctor",
            payload={"doctor_status": doctor_status, "note": doctor_note},
        )
        response["doctor_status"] = doctor_status
        response["status"] = "RESOLVED"
        response["resolved_at"] = datetime_to_iso_utc(now)
        response["validated_at" if doctor_status == "VALIDATED" else "rejected_at"] = datetime_to_iso_utc(now)
        # Aligne le feedback sur l’anomalie ML (réentraînement FP/TP comme /api/doctor/ml-anomalies)
        ml_anomaly_oid = alert_doc.get("ml_anomaly_id")
        if ml_anomaly_oid:
            st_ml = "validated" if doctor_status == "VALIDATED" else "rejected"
            prev_ml_status = None
            try:
                aml = get_medical_db().ml_anomalies.find_one({"_id": ml_anomaly_oid}, {"status": 1})
                prev_ml_status = (aml or {}).get("status")
                get_medical_db().ml_anomalies.update_one(
                    {"_id": ml_anomaly_oid},
                    {"$set": {"status": st_ml, "validated_by": g.user_id_auth, "validated_at": now}},
                )
                meas_id = alert_doc.get("measurement_id")
                if meas_id:
                    get_medical_db().measurements.update_one(
                        {"_id": meas_id},
                        {"$set": {
                            "ml_anomaly_status": st_ml,
                            "ml_validated_by": g.user_id_auth,
                            "ml_validated_at": now,
                        }},
                    )
            except PyMongoError as e:
                logger.warning("sync ml_anomaly from doctor alert failed: %s", e)

            if prev_ml_status != st_ml:
                def _retrain_from_alert():
                    try:
                        do_ml_retrain(days=30, trigger="doctor_alert_ml_feedback")
                    except Exception as e:
                        logger.warning("Background ML retrain after doctor alert failed: %s", e)

                threading.Thread(target=_retrain_from_alert, daemon=True).start()
        elif str(alert_doc.get("alert_source") or "") == "threshold" and not alert_doc.get("ml_anomaly_id"):
            # Données créées avant liaison ml_anomalies : feedback médecin déclenche quand même un réentraînement
            def _retrain_threshold_legacy():
                try:
                    do_ml_retrain(days=30, trigger="doctor_threshold_feedback")
                except Exception as e:
                    logger.warning("Background ML retrain after threshold alert (legacy) failed: %s", e)

            threading.Thread(target=_retrain_threshold_legacy, daemon=True).start()
    elif doctor_note:
        get_medical_db().alerts.update_one(
            {"_id": oid},
            {"$set": {"doctor_note": doctor_note, "doctor_note_at": now, "updated_at": now}},
        )
        write_alert_event(
            medical_alert_id=alert_id,
            event_type="doctor_note",
            actor_user_id_auth=g.user_id_auth,
            actor_role="doctor",
            payload={"note": doctor_note},
        )
    if has_escalation:
        etype = str(esc_raw.get("type") or "samu").strip().lower()[:64]
        entry = {"at": now, "by": g.user_id_auth, "type": etype}
        get_medical_db().alerts.update_one(
            {"_id": oid},
            {"$push": {"emergency_escalations": entry}, "$set": {"updated_at": now, "severity_level": SEVERITY_URGENCY}},
        )
        write_alert_event(
            medical_alert_id=alert_id,
            event_type="doctor_escalation",
            actor_user_id_auth=g.user_id_auth,
            actor_role="doctor",
            payload={"escalation_type": etype},
        )
        response["emergency_escalation_logged"] = {"type": etype, "at": datetime_to_iso_utc(now)}
        response["severity_level"] = SEVERITY_URGENCY
    if doctor_status:
        log_audit_event(
            event_type="alert_doctor_triage",
            actor_user_id_auth=g.user_id_auth,
            actor_role=audit_actor_role(),
            resource_type="alert",
            resource_id=alert_id,
            action="update",
            details={
                "doctor_status": doctor_status,
                "device_id": device_id,
                "endpoint": request.path,
            },
            request=request,
        )
    return jsonify(response), 200


@alert_bp.route("/api/caregiver/alerts/<alert_id>", methods=["PATCH"])
@requires_auth
@requires_role("caregiver", "aidant")
def patch_caregiver_alert(alert_id: str):
    """
    Record caregiver intervention on an alert.
    New fields (retrocompat - old clients sending only resolution_comment still work):
      seen_patient_since_alert: bool - caregiver physically saw the patient since the alert
      resolution_comment: str (optional when seen_patient_since_alert is provided)
    """
    payload = request.get_json(silent=True) or {}
    comment = str(payload.get("resolution_comment") or "").strip()
    seen_raw = payload.get("seen_patient_since_alert")

    # Retrocompat: old clients send only resolution_comment
    has_seen = seen_raw is not None
    seen_bool: Optional[bool] = bool(seen_raw) if has_seen else None

    if not comment and not has_seen:
        return jsonify({"code": "invalid_payload",
                        "message": "Fournir resolution_comment et/ou seen_patient_since_alert"}), 400
    if comment and len(comment) > 1000:
        return jsonify({"code": "invalid_payload",
                        "message": "Le commentaire ne doit pas dépasser 1000 caractères"}), 400
    try:
        oid = ObjectId(alert_id)
    except Exception:
        return jsonify({"code": "invalid_id", "message": "alert_id is not a valid ObjectId"}), 400
    alert_doc = get_medical_db().alerts.find_one({"_id": oid})
    if not alert_doc:
        return jsonify({"code": "not_found", "message": "Alerte introuvable"}), 404
    device_id = alert_doc.get("device_id")
    patient_ids = get_assigned_patient_ids_for_caregiver(g.user_id_auth)
    device_by_patient = {pid: get_device_id(pid) for pid in patient_ids if get_device_id(pid)}
    if device_id not in device_by_patient.values():
        return jsonify({"code": "forbidden", "message": "Cette alerte ne concerne pas un de vos proches"}), 403
    patient_by_device = {did: pid for pid, did in device_by_patient.items()}
    patient_id = patient_by_device.get(device_id)
    patient_profile = get_user_profile(patient_id) if patient_id else {}
    patient_name = patient_profile.get("display_name") or patient_profile.get("email") or "le patient"
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%d/%m/%Y")
    time_str = now.strftime("%H:%M")

    update_fields: Dict[str, Any] = {"updated_at": now}
    if comment:
        resolution_text = f"Urgence résolue, l'aidant de {patient_name} est intervenu le {date_str} à {time_str} : {comment}"
        update_fields["caregiver_resolution_comment"] = resolution_text
        update_fields["caregiver_resolution_at"] = now
        update_fields["caregiver_resolution_by"] = g.user_id_auth
    else:
        resolution_text = None

    if has_seen:
        update_fields["caregiver_seen_patient"] = seen_bool
        update_fields["caregiver_seen_at"] = now
        if not update_fields.get("caregiver_resolution_at"):
            update_fields["caregiver_resolution_at"] = now
            update_fields["caregiver_resolution_by"] = g.user_id_auth

    get_medical_db().alerts.update_one({"_id": oid}, {"$set": update_fields})

    # Mirror last caregiver action in Vitalio_Identity.alerts (unique index on medical_alert_id)
    identity_update: Dict[str, Any] = {
        "medical_alert_id": str(oid),
        "author": "caregiver",
        "createdAt": now,
        "caregiver_user_id_auth": g.user_id_auth,
    }
    if resolution_text:
        identity_update["caregiverComment"] = resolution_text
    if has_seen:
        identity_update["caregiver_seen_patient"] = seen_bool
        identity_update["caregiver_seen_at"] = now
    get_identity_db().alerts.update_one(
        {"medical_alert_id": str(oid)},
        {"$set": identity_update},
        upsert=True,
    )

    # Audit event
    event_type = "caregiver_seen_patient" if has_seen else "caregiver_comment"
    write_alert_event(
        medical_alert_id=alert_id,
        event_type=event_type,
        actor_user_id_auth=g.user_id_auth,
        actor_role="caregiver",
        payload={
            "seen_patient_since_alert": seen_bool,
            "comment": comment or None,
        },
    )

    resp: Dict[str, Any] = {
        "message": "Action enregistrée",
        "alert_id": alert_id,
        "caregiver_resolution_at": datetime_to_iso_utc(now),
    }
    if resolution_text:
        resp["caregiver_resolution_comment"] = resolution_text
    if has_seen:
        resp["caregiver_seen_patient"] = seen_bool
        resp["caregiver_seen_at"] = datetime_to_iso_utc(now)
    return jsonify(resp), 200


@alert_bp.route("/api/doctor/alerts", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser", "medecin")
def get_doctor_alerts():
    doctor_user_id_auth = g.user_id_auth
    status = (request.args.get("status", default="OPEN", type=str) or "OPEN").strip().upper()
    severity_level = (request.args.get("severity_level") or "").strip().upper()
    limit = min(max(request.args.get("limit", default=100, type=int), 1), 500)
    patient_ids = get_assigned_patient_ids_for_doctor(doctor_user_id_auth)
    if not patient_ids:
        return jsonify({"doctor_id": doctor_user_id_auth, "count": 0, "alerts": []}), 200
    device_by_patient = {pid: get_device_id(pid) for pid in patient_ids if get_device_id(pid)}
    device_ids = list(device_by_patient.values())
    if not device_ids:
        return jsonify({"doctor_id": doctor_user_id_auth, "count": 0, "alerts": []}), 200
    patient_by_device = {did: pid for pid, did in device_by_patient.items()}
    id_by_auth = {pid: str(get_user_db_id(pid) or pid) for pid in patient_ids}
    query: Dict[str, Any] = {"device_id": {"$in": device_ids}}
    if status != "ALL":
        query["status"] = status
        if status == "OPEN":
            from app.services.alert_service import open_alert_query_requires_doctor_triage

            query.update(open_alert_query_requires_doctor_triage())
    if severity_level in ("INFO", "WARNING", "CRITICAL", "URGENCY"):
        query["severity_level"] = severity_level
    cursor = get_medical_db().alerts.find(query).sort("created_at", -1).limit(limit)
    alerts = []
    for alert in cursor:
        out = format_alert_for_doctor(dict(alert))
        out.pop("_id", None)
        sanitize_alert_dict(out)
        out["alert_id"] = str(alert["_id"]) if alert.get("_id") else None
        for k, v in list(out.items()):
            if isinstance(v, datetime):
                out[k] = datetime_to_iso_utc(v)
        auth_id = patient_by_device.get(alert.get("device_id"))
        out["patient_id"] = id_by_auth.get(auth_id, auth_id) if auth_id else None
        out["doctor_status"] = alert.get("doctor_status", "PENDING")
        out["caregiver_resolution_comment"] = alert.get("caregiver_resolution_comment")
        out["caregiver_seen_patient"] = alert.get("caregiver_seen_patient")
        out["alert_source"] = alert.get("alert_source", "threshold")
        out["patient_message"] = alert.get("patient_message")
        out["doctor_note"] = alert.get("doctor_note")
        # Inline measurement snapshot for threshold alerts (avoids extra round-trip)
        measurement_snapshot = None
        m_id = alert.get("measurement_id")
        if m_id:
            try:
                m_doc = get_medical_db().measurements.find_one(
                    {"_id": m_id},
                    projection={"_id": 1, "measured_at": 1, "heart_rate": 1, "spo2": 1,
                                "temperature": 1, "signal_quality": 1, "status": 1},
                )
                if m_doc:
                    measurement_snapshot = {
                        "measurement_id": str(m_id),
                        "measured_at": datetime_to_iso_utc(m_doc["measured_at"]) if isinstance(m_doc.get("measured_at"), datetime) else None,
                        "heart_rate": m_doc.get("heart_rate"),
                        "spo2": m_doc.get("spo2"),
                        "temperature": m_doc.get("temperature"),
                        "signal_quality": m_doc.get("signal_quality"),
                        "status": m_doc.get("status"),
                    }
            except Exception:
                pass
        out["measurement_snapshot"] = measurement_snapshot
        finalize_alert_api_payload(dict(alert), out, auth_id, include_patient_address=True)
        alerts.append(out)
    return jsonify({"doctor_id": doctor_user_id_auth, "status_filter": status, "count": len(alerts), "alerts": alerts}), 200


