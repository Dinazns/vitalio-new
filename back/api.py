"""
VitalIO API - Main application entry point.
Refactored: configuration, database, auth, and business logic are in separate modules.
"""
import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone, date
from typing import Dict, Any, List, Optional, Tuple

from flask import Flask, request, jsonify, g, Response
from flask_cors import CORS
from pymongo.errors import PyMongoError
from bson import ObjectId

import ml_module

# Config & core
from config import (
    FRONTEND_URL, INVITE_TTL_HOURS, CABINET_CODE_TTL_MINUTES_DEFAULT,
    SMTP_HOST, SMTP_USER, SMTP_PASSWORD,
    MONGODB_IDENTITY_DB, MONGODB_MEDICAL_DB,
    ALERT_DEFAULT_CONSECUTIVE_BREACHES,
)
from database import get_identity_db, get_medical_db, init_database
from exceptions import AuthError, DatabaseError
from api_auth import requires_auth, requires_role, get_current_user_role, get_user_role, _extract_profile_from_jwt

# Services
from services.user_service import (
    get_device_ids, get_device_id, get_device_measurements,
    get_assigned_patient_ids_for_doctor, get_assigned_patient_ids_for_caregiver,
    get_assigned_doctor_ids_for_patient, get_assigned_caregiver_ids_for_patient,
    ensure_patient_access_or_403, resolve_patient_id_to_user_id_auth, get_user_db_id,
    parse_iso_datetime, normalize_user_id_auth, get_user_profile, _split_display_name,
    datetime_to_iso_utc, get_address_dict_from_profile,
)
from services.invitation_service import (
    hash_secret_token, generate_invite_token, generate_cabinet_code,
    log_link_audit_event, create_doctor_patient_link, get_invite_document_or_404,
    send_invitation_email, invite_emergency_contact_if_needed, log_caregiver_audit_event,
)
from services.auth0_service import create_auth0_user_if_not_exists
from services.measurement_service import (
    get_latest_device_measurement, compute_alert_indicator,
    query_patient_measurements, query_patient_measurements_for_devices,
    count_patient_measurements_total,
    query_patient_measurements_range, list_latest_doctor_feedback,
    build_assigned_patients_payload, build_trend_window,
    normalize_patient_measurement_payload, validate_measurement_values,
)
from services.alert_service import (
    evaluate_measurement_alerts, merge_thresholds, get_alert_threshold_config,
    create_manual_alert, write_alert_event,
)
from services.ml_retrain_runner import do_ml_retrain
from services.alert_messages import format_alert_for_doctor, format_alert_for_caregiver
from services.ml_service import run_ml_scoring
from services.ml_retrain_scheduler import schedule_retrain_after_new_measurement
from services.alert_ml_audit import create_or_merge_alert_for_validated_ml
from services.ml_thresholds_store import save_ml_thresholds_to_db
from services.patient_data_portability import build_patient_export, erase_patient_all_data
from mqtt_handler import start_mqtt_subscriber

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _sanitize_alert_dict(d: Dict[str, Any]) -> None:
    """Convert any remaining ObjectId / non-serialisable values to strings in-place."""
    for key, val in list(d.items()):
        if isinstance(val, ObjectId):
            d[key] = str(val)


def _finalize_alert_api_payload(
    raw_alert: Dict[str, Any],
    out: Dict[str, Any],
    patient_user_id_auth: Optional[str],
    *,
    include_patient_address: bool,
) -> None:
    if include_patient_address and patient_user_id_auth:
        addr = get_address_dict_from_profile(get_user_profile(patient_user_id_auth))
        if addr:
            out["patient_address"] = addr
    out["caregiver_intervened"] = bool(
        raw_alert.get("caregiver_resolution_at") or raw_alert.get("caregiver_resolution_comment")
    )
    esc = raw_alert.get("emergency_escalations") or []
    serialized = []
    if isinstance(esc, list):
        for e in esc:
            if not isinstance(e, dict):
                continue
            item = dict(e)
            at = item.get("at")
            if isinstance(at, datetime):
                item["at"] = datetime_to_iso_utc(at)
            serialized.append(item)
    out["emergency_escalations"] = serialized


def _build_combined_anomaly_summary_for_analysis(
    anomaly_records: List[Dict[str, Any]],
    threshold_alert_docs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Merge ml_anomalies with threshold-based alerts (medical.alerts, excluding metric=ml_anomaly).
    Dedup: if a threshold alert references the same measurement_id as an ML anomaly, count the alert only.
    """
    thr_m_ids = {a.get("measurement_id") for a in threshold_alert_docs if a.get("measurement_id")}
    ml_filtered = [a for a in anomaly_records if a.get("measurement_id") not in thr_m_ids]
    by_status: Dict[str, int] = {}
    for a in ml_filtered:
        st = str(a.get("status") or "pending").lower()
        by_status[st] = by_status.get(st, 0) + 1
    for a in threshold_alert_docs:
        ds = (a.get("doctor_status") or "PENDING").upper()
        sk = "validated" if ds == "VALIDATED" else "rejected" if ds == "REJECTED" else "pending"
        by_status[sk] = by_status.get(sk, 0) + 1
    recent_ml = [
        {
            "timestamp": str(a.get("measured_at", "")),
            "score": float(a.get("anomaly_score") or 0),
            "level": a.get("anomaly_level", "critical"),
            "status": a.get("status", "pending"),
            "contributing_variables": a.get("contributing_variables", []),
        }
        for a in ml_filtered[:15]
    ]
    recent_thr: List[Dict[str, Any]] = []
    for a in threshold_alert_docs[:12]:
        ts = a.get("last_breach_at") or a.get("created_at")
        metric = str(a.get("metric") or "seuil")
        recent_thr.append({
            "timestamp": str(ts) if ts else "",
            "score": 0.0,
            "level": "threshold",
            "status": str(a.get("doctor_status") or "PENDING").lower(),
            "contributing_variables": [{"variable": metric, "contribution_weight": 1.0}],
            # expose IDs so the UI can send PATCH requests directly from this panel
            "alert_id": str(a["_id"]) if a.get("_id") else None,
            "alert_source": a.get("alert_source", "threshold"),
            "metric": metric,
            "operator": a.get("operator"),
            "value": a.get("latest_value") or a.get("value"),
            "threshold": a.get("threshold"),
            "status_raw": str(a.get("doctor_status") or "PENDING"),
        })
    combined_recent = recent_ml + recent_thr
    combined_recent.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)
    return {
        "total": len(ml_filtered) + len(threshold_alert_docs),
        "by_status": by_status,
        "recent": combined_recent[:25],
    }


app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

CORS(app, resources={
    r"/api/*": {
        "origins": [
            "https://vitalio-new.vercel.app",
            "http://localhost:5173",
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True,
    }
})


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(AuthError)
def handle_auth_error(ex: AuthError):
    return jsonify(ex.error), ex.status_code


@app.errorhandler(DatabaseError)
def handle_database_error(ex: DatabaseError):
    return jsonify(ex.error), ex.status_code


@app.errorhandler(500)
def handle_internal_error(e):
    return jsonify({
        "code": "internal_server_error",
        "message": "An internal server error occurred"
    }), 500


# ============================================================================
# ROUTES - ME / Patient
# ============================================================================

@app.route("/api/push/vapid-public-key", methods=["GET"])
def get_vapid_public_key():
    """Return VAPID public key for push subscription (public, no auth required)."""
    from config import VAPID_PUBLIC_KEY
    return jsonify({"vapid_public_key": VAPID_PUBLIC_KEY or ""}), 200


@app.route("/api/me/push-subscribe", methods=["POST"])
@requires_auth
@requires_role("doctor", "medecin", "caregiver", "aidant", "Superuser")
def push_subscribe():
    """Register a push subscription for alert notifications (doctors/caregivers)."""
    from config import VAPID_PUBLIC_KEY
    from datetime import datetime, timezone
    payload = request.get_json(silent=True) or {}
    subscription = payload.get("subscription")
    if not subscription or not isinstance(subscription, dict):
        return jsonify({"code": "invalid_subscription", "message": "subscription object required"}), 400
    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        return jsonify({"code": "invalid_subscription", "message": "endpoint and keys (p256dh, auth) required"}), 400
    user_id_auth = g.user_id_auth
    now = datetime.now(timezone.utc)
    doc = {
        "user_id_auth": user_id_auth,
        "endpoint": endpoint,
        "subscription": subscription,
        "enabled": True,
        "updated_at": now,
    }
    try:
        coll = get_identity_db().push_subscriptions
        coll.update_one(
            {"user_id_auth": user_id_auth, "endpoint": endpoint},
            {"$set": doc, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        return jsonify({
            "message": "Push subscription enregistrée",
            "vapid_public_key": VAPID_PUBLIC_KEY or None,
        }), 200
    except PyMongoError as e:
        logger.warning("Push subscription save failed: %s", e)
        return jsonify({"code": "database_error", "message": "Failed to save subscription"}), 500


@app.route("/api/me/role", methods=["GET"])
@requires_auth
def get_my_role():
    user_id_auth = g.user_id_auth
    payload = getattr(g, "jwt_payload", {}) or {}
    ns = "https://vitalio.app/"
    db_role = get_user_role(user_id_auth)
    jwt_role = (payload.get(f"{ns}role") or payload.get("role") or "").strip()
    role_raw = (db_role or jwt_role or "").strip().lower()
    role_display_map = {
        "superuser": "doctor", 
        "doctor": "doctor", 
        "medecin": "doctor", 
        "médecin": "doctor",
        "patient": "patient", 
        "caregiver": "caregiver", 
        "aidant": "caregiver", 
        "admin": "admin",
    }
    display_role = role_display_map.get(role_raw, "Patient")
    return jsonify({"role": display_role, "user_id_auth": user_id_auth}), 200


@app.route("/api/me/profile", methods=["GET"])
@requires_auth
@requires_role("patient")
def get_my_profile():
    user_id_auth = g.user_id_auth
    profile = get_user_profile(user_id_auth)
    payload = getattr(g, "jwt_payload", {}) or {}
    profile_data = {
        "display_name": profile.get("display_name") or payload.get("name") or "",
        "email": profile.get("email") or payload.get("email") or "",
        "first_name": profile.get("first_name") or payload.get("given_name") or "",
        "last_name": profile.get("last_name") or payload.get("family_name") or "",
        "age": profile.get("age"), "sex": profile.get("sex"),
        "phone": profile.get("phone"), "birthdate": profile.get("birthdate"),
        "picture": profile.get("picture") or payload.get("picture") or "",
        "emergency_contact": profile.get("emergency_contact") or None,
        "medical_history": profile.get("medical_history") or None,
        "onboarding_completed": profile.get("onboarding_completed", False),
        "address_line1": profile.get("address_line1") or "",
        "address_line2": profile.get("address_line2") or "",
        "postal_code": profile.get("postal_code") or "",
        "city": profile.get("city") or "",
        "country": profile.get("country") or "",
    }
    if not profile_data["first_name"] and not profile_data["last_name"]:
        name = profile.get("display_name") or payload.get("name") or ""
        if name:
            profile_data["first_name"], profile_data["last_name"] = _split_display_name(name)
    doctor_ids = get_assigned_doctor_ids_for_patient(user_id_auth)
    device_ids = get_device_ids(user_id_auth)
    measurements_count = count_patient_measurements_total(device_ids)
    profile_data["has_measurements"] = measurements_count > 0
    profile_data["has_doctor"] = len(doctor_ids) > 0
    doctors = []
    for idx, did in enumerate(doctor_ids):
        doc_profile = get_user_profile(did)
        disp = doc_profile.get("display_name") or doc_profile.get("email") or ""
        fname, lname = _split_display_name(disp) if disp else ("", "")
        if not fname and not lname:
            fname = disp
        contact = doc_profile.get("contact") or doc_profile.get("email") or ""
        doctors.append({"id": idx, "first_name": fname, "last_name": lname, "contact": contact})
    caregiver_ids = get_assigned_caregiver_ids_for_patient(user_id_auth)
    caregivers = []
    for idx, cid in enumerate(caregiver_ids):
        cg_profile = get_user_profile(cid)
        disp = cg_profile.get("display_name") or cg_profile.get("email") or ""
        fname, lname = _split_display_name(disp) if disp else ("", "")
        if not fname and not lname:
            fname = disp
        contact = cg_profile.get("contact") or cg_profile.get("email") or ""
        caregivers.append({
            "id": idx,
            "first_name": fname,
            "last_name": lname,
            "contact": contact,
            "email": cg_profile.get("email") or "",
            "phone": cg_profile.get("phone") or "",
        })
    return jsonify({"profile": profile_data, "doctors": doctors, "caregivers": caregivers}), 200


@app.route("/api/me/profile", methods=["PATCH"])
@requires_auth
@requires_role("patient", "doctor", "caregiver", "admin", "superuser", "medecin", "aidant")
def patch_my_profile():
    _EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    ALLOWED_PROFILE_FIELDS = {
        "first_name": (str, 64), "last_name": (str, 64), "age": (int, None), "sex": (str, 16),
        "phone": (str, 32), "birthdate": (str, 16),
        "display_name": (str, 128), "email": (str, 256), "picture": (str, 512),
        "medical_history": (str, 2000),
    }
    payload = request.get_json(silent=True) or {}
    updates = {}
    for field, (ftype, max_len) in ALLOWED_PROFILE_FIELDS.items():
        if field not in payload:
            continue
        raw = payload[field]
        if ftype is int:
            try:
                val = int(raw)
                updates[field] = val if 0 <= val <= 150 else None
            except (TypeError, ValueError):
                updates[field] = None
        elif field == "sex":
            val = str(raw or "").strip().lower()
            u = (str(raw or "").strip().upper())
            if val in ("f", "m", "o") or u in ("F", "M", "O"):
                updates[field] = val if val in ("f", "m", "o") else u.lower()
            elif val in ("homme", "masculin"):
                updates[field] = "m"
            elif val in ("femme", "féminin", "feminin"):
                updates[field] = "f"
            elif val == "autre":
                updates[field] = "o"
            else:
                updates[field] = None
        elif field == "email":
            val = str(raw or "").strip()[:max_len]
            if val and not _EMAIL_RE.match(val):
                return jsonify({"code": "invalid_email", "message": "Invalid email format"}), 422
            updates[field] = val or None
        elif field == "picture":
            val = str(raw or "").strip()[:max_len]
            if val and not val.startswith(("https://", "http://")):
                return jsonify({"code": "invalid_picture", "message": "Picture must be a URL"}), 422
            updates[field] = val or None
        elif field == "medical_history":
            updates[field] = str(raw or "").strip()[:max_len] or None
        else:
            updates[field] = str(raw or "")[:max_len] or None

    new_emergency_email = None
    if "emergency_contact" in payload and isinstance(payload["emergency_contact"], dict):
        ec = payload["emergency_contact"]
        emergency = {
            "last_name": str(ec.get("last_name") or "").strip()[:64] or None,
            "first_name": str(ec.get("first_name") or "").strip()[:64] or None,
            "phone": str(ec.get("phone") or "").strip()[:32] or None,
            "email": None,
        }
        ec_email = str(ec.get("email") or "").strip()[:256]
        if ec_email:
            if not _EMAIL_RE.match(ec_email):
                return jsonify({"code": "invalid_emergency_email", "message": "Invalid emergency contact email"}), 422
            emergency["email"] = ec_email
            new_emergency_email = ec_email
        has_any = any(v for v in emergency.values())
        updates["emergency_contact"] = emergency if has_any else None

    if get_user_role(g.user_id_auth) == "patient":
        ADDRESS_FIELDS = {
            "address_line1": 128, "address_line2": 128, "postal_code": 16,
            "city": 64, "country": 64,
        }
        for field, max_len in ADDRESS_FIELDS.items():
            if field not in payload:
                continue
            updates[field] = str(payload[field] or "").strip()[:max_len] or None

    if not updates:
        return jsonify({"message": "No fields to update"}), 400

    set_doc = {**updates, "updated_at": datetime.now(timezone.utc)}
    payload_jwt = getattr(g, "jwt_payload", {}) or {}
    ns = "https://vitalio.app/"
    jwt_role = (payload_jwt.get(f"{ns}role") or payload_jwt.get("role") or "").strip().lower()
    role_map = {"doctor": "medecin", "medecin": "medecin", "superuser": "medecin", "patient": "patient",
                "caregiver": "aidant", "aidant": "aidant", "admin": "admin"}
    default_role = role_map.get(jwt_role, jwt_role or "patient")
    set_on_insert = {
        "user_id_auth": g.user_id_auth, "role": default_role, "created_at": datetime.now(timezone.utc),
    }

    # À la première connexion (ou mise à jour profil), display_name = first_name + last_name
    profile = get_user_profile(g.user_id_auth) or {}
    first_name_val = str(updates.get("first_name") or profile.get("first_name") or "").strip()
    last_name_val = str(updates.get("last_name") or profile.get("last_name") or "").strip()
    if first_name_val or last_name_val:
        computed_display = f"{first_name_val} {last_name_val}".strip()
        if computed_display:
            set_doc["display_name"] = computed_display[:128]
    if "display_name" not in set_doc:
        set_on_insert["display_name"] = updates.get("display_name") or updates.get("email") or g.user_id_auth

    try:
        get_identity_db().users.update_one(
            {"user_id_auth": g.user_id_auth},
            {"$set": set_doc, "$setOnInsert": set_on_insert},
            upsert=True,
        )
    except PyMongoError as e:
        raise DatabaseError({"code": "update_error", "message": str(e)}, 500)

    if new_emergency_email:
        patient_profile = get_user_profile(g.user_id_auth)
        patient_name = patient_profile.get("display_name") or patient_profile.get("email") or "Un patient VitalIO"
        invite_emergency_contact_if_needed(g.user_id_auth, new_emergency_email, patient_name)

    return jsonify({"message": "Profile updated"}), 200


@app.route("/api/me/onboarding", methods=["POST"])
@requires_auth
@requires_role("patient")
def complete_onboarding():
    """
    Complete medical onboarding for new patients.
    Required: first_name, last_name, sex, emergency_contact (aidant), medical_history.
    Optional: phone, birthdate, age (computed from birthdate if not provided).
    """
    _EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    payload = request.get_json(silent=True) or {}

    first_name = str(payload.get("first_name") or payload.get("given_name") or "").strip()[:64] or None
    last_name = str(payload.get("last_name") or payload.get("family_name") or "").strip()[:64] or None
    if not first_name or not last_name:
        return jsonify({"code": "invalid_name", "message": "Le prénom et le nom sont requis"}), 400

    phone = str(payload.get("phone") or payload.get("phone_number") or "").strip()[:32] or None
    birthdate = str(payload.get("birthdate") or "").strip()[:16] or None

    email = str(payload.get("email") or "").strip()[:256]
    if not email or not _EMAIL_RE.match(email):
        return jsonify({"code": "invalid_email", "message": "L'email du patient est requis et doit être valide"}), 400

    age = None
    age_raw = payload.get("age")
    if age_raw is not None:
        try:
            age = int(age_raw) if 0 <= int(age_raw) <= 150 else None
        except (TypeError, ValueError):
            pass
    if age is None and birthdate:
        try:
            bd = datetime.strptime(birthdate[:10], "%Y-%m-%d").date()
            age = (date.today() - bd).days // 365
            if age < 0 or age > 150:
                age = None
        except (ValueError, TypeError):
            pass
    if age is None:
        return jsonify({"code": "invalid_age", "message": "L'âge ou la date de naissance est requis"}), 400

    sex_raw = str(payload.get("sex") or "").strip().upper()
    if sex_raw in ("F", "M", "O"):
        sex_val = sex_raw.lower()
    elif str(payload.get("sex") or "").strip().lower() in ("m", "f", "homme", "femme", "autre"):
        v = str(payload.get("sex")).lower()
        sex_val = "m" if v in ("m", "homme") else "f" if v in ("f", "femme") else "o"
    else:
        return jsonify({"code": "invalid_sex", "message": "Le sexe est requis (F, M, O)"}), 400

    ec = payload.get("emergency_contact")
    if not isinstance(ec, dict):
        return jsonify({"code": "invalid_aidant", "message": "Les informations de l'aidant sont requises"}), 400
    ec_email = str(ec.get("email") or "").strip()[:256]
    if not ec_email or not _EMAIL_RE.match(ec_email):
        return jsonify({"code": "invalid_aidant_email", "message": "L'email de l'aidant est requis et doit être valide"}), 400
    emergency = {
        "last_name": str(ec.get("last_name") or "").strip()[:64] or None,
        "first_name": str(ec.get("first_name") or "").strip()[:64] or None,
        "phone": str(ec.get("phone") or "").strip()[:32] or None,
        "email": ec_email,
    }

    medical_history = str(payload.get("medical_history") or "").strip()[:2000]
    if not medical_history:
        return jsonify({"code": "invalid_medical_history", "message": "L'historique médical est requis"}), 400

    display_name = f"{first_name} {last_name}".strip()
    set_doc = {
        "first_name": first_name, "last_name": last_name, "display_name": display_name,
        "age": age, "sex": sex_val, "phone": phone, "birthdate": birthdate,
        "emergency_contact": emergency,
        "medical_history": medical_history, "onboarding_completed": True,
        "role": "patient",
        "email": email,
        "updated_at": datetime.now(timezone.utc),
    }
    set_on_insert = {
        "user_id_auth": g.user_id_auth, "created_at": datetime.now(timezone.utc),
    }

    try:
        get_identity_db().users.update_one(
            {"user_id_auth": g.user_id_auth},
            {"$set": set_doc, "$setOnInsert": set_on_insert},
            upsert=True,
        )
    except PyMongoError as e:
        raise DatabaseError({"code": "update_error", "message": str(e)}, 500)

    patient_profile = get_user_profile(g.user_id_auth)
    patient_name = patient_profile.get("display_name") or patient_profile.get("email") or "Un patient VitalIO"
    invite_emergency_contact_if_needed(g.user_id_auth, ec_email, patient_name)

    return jsonify({"message": "Onboarding médical complété", "onboarding_completed": True}), 200


@app.route("/api/me/export-data", methods=["GET"])
@requires_auth
@requires_role("patient")
def export_my_patient_data():
    """Export JSON de toutes les données VitalIO liées au patient authentifié."""
    uid = g.user_id_auth
    try:
        payload = build_patient_export(uid)
    except DatabaseError:
        raise
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"vitalio-export-{ts}.json"
    return Response(
        raw,
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/api/me/account-data", methods=["DELETE"])
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
    try:
        counts = erase_patient_all_data(uid)
    except DatabaseError:
        raise
    return jsonify({
        "message": "Toutes vos données VitalIO ont été supprimées. Vous pouvez vous déconnecter.",
        "deleted": counts,
    }), 200


@app.route("/api/me/device", methods=["GET"])
@requires_auth
@requires_role("patient")
def get_patient_me_device():
    """Identifiant(s) du ou des boîtiers liés au compte (attribution médecin ou appairage terminé)."""
    device_ids = get_device_ids(g.user_id_auth)
    if not device_ids:
        return jsonify({"device_id": None, "device_ids": []}), 200
    return jsonify({"device_id": device_ids[0], "device_ids": device_ids}), 200


@app.route("/api/me/data", methods=["GET"])
@requires_auth
@requires_role("patient")
def get_patient_data():
    device_id = get_device_id(g.user_id_auth)
    if not device_id:
        raise DatabaseError({"code": "device_not_found", "message": "No device record found for authenticated user"}, 404)
    measurements = get_device_measurements(device_id)
    return jsonify({"device_id": device_id, "measurements": measurements, "measurement_count": len(measurements)}), 200


def _weekly_summary_max_severity(analysis: Dict[str, Any]) -> int:
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


def _build_lay_patient_weekly_summary(analysis: Dict[str, Any], max_severity: int) -> Dict[str, Any]:
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


@app.route("/api/me/weekly-analysis", methods=["GET"])
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
        max_sev = _weekly_summary_max_severity(analysis)
        summary = _build_lay_patient_weekly_summary(analysis, max_sev)
    except Exception as e:
        logger.warning("Weekly analysis failed for patient: %s", e)
        summary = {
            "text": "Analyse en cours de chargement. Réessayez dans quelques instants.",
            "risk_level": "unknown",
            "recommended_action": "",
        }
    return jsonify({
        "device_id": device_id,
        "measurements": measurements,
        "measurement_count": len(measurements),
        "summary": summary,
    }), 200


@app.route("/api/me/measurements", methods=["POST"])
@requires_auth
@requires_role("patient")
def submit_patient_measurement():
    device_id = get_device_id(g.user_id_auth)
    if not device_id:
        raise DatabaseError({"code": "device_not_found", "message": "No device record found for authenticated user"}, 404)
    payload = request.get_json(silent=True) or {}
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


@app.route("/api/patient/alerts", methods=["POST"])
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
        from services.invitation_service import send_alert_emails_for_new_alert
        send_alert_emails_for_new_alert(
            device_id=device_id, metric="manual", operator="manual",
            value=0, threshold=0, patient_name=patient_name,
        )
    except Exception as exc:
        logger.warning("Manual alert email send failed: %s", exc)

    try:
        from services.webpush_service import send_manual_alert_push_notifications
        send_manual_alert_push_notifications(
            device_id=device_id, patient_name=patient_name, patient_message=message,
        )
    except Exception as exc:
        logger.warning("Manual alert push send failed: %s", exc)

    return jsonify({
        "message": "Alerte envoyée. Votre médecin et votre aidant ont été notifiés.",
        "alert_id": alert_id,
    }), 201


def _normalize_email(email_raw: str):
    if not email_raw or not isinstance(email_raw, str):
        return None
    s = str(email_raw).strip().lower()
    return s if "@" in s and "." in s and len(s) > 5 else None


# ============================================================================
# ROUTES - Doctor / Caregiver / Admin
# ============================================================================

@app.route("/api/doctor/invitations", methods=["POST"])
@requires_auth
@requires_role("doctor", "superuser")
def create_doctor_invitation():
    payload = request.get_json(silent=True) or {}
    patient_user_id_auth_raw = payload.get("patient_user_id_auth")
    patient_email_raw = payload.get("patient_email")
    send_email = payload.get("send_email", False) is True

    patient_user_id_auth = None
    if patient_user_id_auth_raw is not None and str(patient_user_id_auth_raw).strip():
        try:
            patient_user_id_auth = normalize_user_id_auth(patient_user_id_auth_raw, "patient_user_id_auth")
        except ValueError as e:
            return jsonify({"code": "invalid_payload", "message": str(e)}), 400
        if get_user_role(patient_user_id_auth) != "patient":
            return jsonify({"code": "invalid_patient", "message": "patient_user_id_auth must reference a user with role 'patient'"}), 400

    patient_email = None
    if send_email:
        patient_email = _normalize_email(patient_email_raw)
        if not patient_email and patient_user_id_auth:
            profile = get_user_profile(patient_user_id_auth)
            patient_email = _normalize_email(profile.get("email") or "")
        if not patient_email:
            return jsonify({"code": "invalid_payload", "message": "patient_email is required when send_email is true"}), 400

    invite_token = generate_invite_token()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=max(INVITE_TTL_HOURS, 1))
    invite_doc = {
        "token_hash": hash_secret_token(invite_token),
        "doctor_user_id_auth": g.user_id_auth, "patient_user_id_auth": patient_user_id_auth,
        "expires_at": expires_at, "used_at": None, "created_at": now,
        "created_by_user_id_auth": g.user_id_auth, "mode": "invite_link",
        "metadata": {"targeted": bool(patient_user_id_auth)},
    }
    try:
        get_identity_db().doctor_invites.insert_one(invite_doc)
        log_link_audit_event("invite_created", g.user_id_auth, g.user_id_auth, patient_user_id_auth or "", "invite_link",
                             {"targeted": bool(patient_user_id_auth), "expires_at": datetime_to_iso_utc(expires_at)})
    except PyMongoError as e:
        raise DatabaseError({"code": "invite_insert_error", "message": f"Failed to create invitation: {str(e)}"}, 500)

    web_invite_url = f"{FRONTEND_URL.rstrip('/')}/invite?token={invite_token}"
    doctor_profile = get_user_profile(g.user_id_auth)
    doctor_display_name = doctor_profile.get("display_name") or doctor_profile.get("email") or "Votre médecin"

    if send_email and patient_email:
        if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
            return jsonify({"code": "email_config_error", "message": "SMTP non configuré"}), 503
        password_setup_url = None
        try:
            created, ticket_or_id = create_auth0_user_if_not_exists(
                patient_email,
                name=doctor_display_name,
                invite_return_url=web_invite_url,
            )
            if created and ticket_or_id and ticket_or_id.startswith("http"):
                password_setup_url = ticket_or_id
        except Exception as e:
            logger.warning("Auth0 user creation skipped: %s", e)
        import threading as _th
        def _send_async():
            try:
                send_invitation_email(
                    patient_email, invite_token, web_invite_url, expires_at,
                    doctor_display_name,
                    password_setup_url=password_setup_url,
                )
            except Exception as e:
                logger.exception("Envoi email invitation échoué (background): %s", e)
        _th.Thread(target=_send_async, daemon=True).start()

    return jsonify({
        "invite_token": invite_token, "expires_at": datetime_to_iso_utc(expires_at),
        "deep_link": f"vitalio://invite?token={invite_token}", "web_invite_url": web_invite_url,
        "qr_payload": web_invite_url, "mode": "invite_link",
        "target_patient_user_id_auth": patient_user_id_auth, "email_sent": bool(send_email and patient_email),
    }), 201


@app.route("/api/patient/invitations/accept", methods=["POST"])
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
    now = datetime.now(timezone.utc)
    get_identity_db().doctor_invites.update_one(
        {"_id": invite["_id"], "used_at": None},
        {"$set": {"used_at": now, "used_by_user_id_auth": g.user_id_auth}}
    )
    log_link_audit_event("invite_accepted", g.user_id_auth, doctor_user_id_auth, g.user_id_auth, "invite_link",
                         {"invite_created_at": str(invite.get("created_at"))})
    return jsonify({"message": "Invitation accepted", "doctor_user_id_auth": doctor_user_id_auth,
                    "patient_user_id_auth": g.user_id_auth}), 201


@app.route("/api/doctor/cabinet-codes", methods=["POST"])
@requires_auth
@requires_role("doctor")
def create_doctor_cabinet_code():
    payload = request.get_json(silent=True) or {}
    ttl_minutes = payload.get("ttl_minutes", CABINET_CODE_TTL_MINUTES_DEFAULT)
    try:
        ttl_minutes = int(ttl_minutes)
    except (TypeError, ValueError):
        return jsonify({"code": "invalid_payload", "message": "ttl_minutes must be an integer"}), 400
    ttl_minutes = min(max(ttl_minutes, 10), 30)
    code = generate_cabinet_code()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ttl_minutes)
    invite_doc = {
        "token_hash": hash_secret_token(code), "doctor_user_id_auth": g.user_id_auth,
        "patient_user_id_auth": None, "expires_at": expires_at, "used_at": None,
        "created_at": now, "created_by_user_id_auth": g.user_id_auth,
        "mode": "cabinet_code", "metadata": {"ttl_minutes": ttl_minutes},
    }
    try:
        get_identity_db().doctor_invites.insert_one(invite_doc)
        log_link_audit_event("cabinet_code_created", g.user_id_auth, g.user_id_auth, "", "cabinet_code",
                             {"expires_at": datetime_to_iso_utc(expires_at), "ttl_minutes": ttl_minutes})
    except PyMongoError as e:
        raise DatabaseError({"code": "cabinet_code_insert_error", "message": f"Failed to create cabinet code: {str(e)}"}, 500)
    return jsonify({"code": code, "expires_at": datetime_to_iso_utc(expires_at), "qr_payload": f"vitalio://cabinet-code?code={code}",
                    "mode": "cabinet_code"}), 201


@app.route("/api/patient/cabinet-codes/redeem", methods=["POST"])
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


@app.route("/api/admin/associations/doctor-patient", methods=["POST"])
@requires_auth
@requires_role("admin")
def create_doctor_patient_association():
    payload = request.get_json(silent=True) or {}
    try:
        doctor_user_id_auth = normalize_user_id_auth(payload.get("doctor_user_id_auth"), "doctor_user_id_auth")
        patient_user_id_auth = normalize_user_id_auth(payload.get("patient_user_id_auth"), "patient_user_id_auth")
    except ValueError as e:
        return jsonify({"code": "invalid_payload", "message": str(e)}), 400
    if get_user_role(doctor_user_id_auth) != "doctor":
        return jsonify({"code": "invalid_doctor", "message": "doctor_user_id_auth must reference a user with role 'doctor'"}), 400
    if get_user_role(patient_user_id_auth) != "patient":
        return jsonify({"code": "invalid_patient", "message": "patient_user_id_auth must reference a user with role 'patient'"}), 400
    try:
        created = create_doctor_patient_link(doctor_user_id_auth, patient_user_id_auth, "admin", g.user_id_auth)
    except PyMongoError as e:
        raise DatabaseError({"code": "doctor_association_insert_error", "message": f"Failed to store doctor-patient association: {str(e)}"}, 500)
    if not created:
        return jsonify({"code": "association_exists", "message": "Doctor-patient association already exists"}), 409
    log_link_audit_event("admin_association_created", g.user_id_auth, doctor_user_id_auth, patient_user_id_auth, "admin", {})
    return jsonify({"message": "Doctor-patient association saved", "doctor_user_id_auth": doctor_user_id_auth,
                    "patient_user_id_auth": patient_user_id_auth}), 201


@app.route("/api/admin/associations/caregiver-patient", methods=["POST"])
@requires_auth
@requires_role("admin")
def create_caregiver_patient_association():
    payload = request.get_json(silent=True) or {}
    caregiver_user_id_auth = str(payload.get("caregiver_user_id_auth") or "").strip()
    patient_user_id_auth = str(payload.get("patient_user_id_auth") or "").strip()
    if not caregiver_user_id_auth or not patient_user_id_auth:
        return jsonify({"code": "invalid_payload", "message": "caregiver_user_id_auth and patient_user_id_auth are required"}), 400
    if get_user_role(caregiver_user_id_auth) != "caregiver":
        return jsonify({"code": "invalid_caregiver", "message": "caregiver_user_id_auth must reference a user with role 'caregiver'"}), 400
    if get_user_role(patient_user_id_auth) != "patient":
        return jsonify({"code": "invalid_patient", "message": "patient_user_id_auth must reference a user with role 'patient'"}), 400
    try:
        get_identity_db().caregiver_patients.update_one(
            {"caregiver_user_id_auth": caregiver_user_id_auth, "patient_user_id_auth": patient_user_id_auth},
            {"$set": {"caregiver_user_id_auth": caregiver_user_id_auth, "patient_user_id_auth": patient_user_id_auth},
             "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
            upsert=True
        )
    except PyMongoError as e:
        raise DatabaseError({"code": "caregiver_association_insert_error", "message": f"Failed to store caregiver-patient association: {str(e)}"}, 500)
    return jsonify({"message": "Caregiver-patient association saved", "caregiver_user_id_auth": caregiver_user_id_auth,
                    "patient_user_id_auth": patient_user_id_auth}), 201


@app.route("/api/doctor/patients", methods=["GET"])
@requires_auth
@requires_role("doctor")
def get_doctor_patients():
    patient_ids = get_assigned_patient_ids_for_doctor(g.user_id_auth)
    patients = build_assigned_patients_payload(patient_ids, doctor_queue_alert_badge=True)
    return jsonify({"doctor_id": g.user_id_auth, "count": len(patients), "patients": patients}), 200


@app.route("/api/caregiver/patients", methods=["GET"])
@requires_auth
@requires_role("caregiver", "aidant")
def get_caregiver_patients():
    patient_ids = get_assigned_patient_ids_for_caregiver(g.user_id_auth)
    patients = build_assigned_patients_payload(patient_ids)
    return jsonify({"caregiver_id": g.user_id_auth, "count": len(patients), "patients": patients}), 200


@app.route("/api/caregiver/alerts", methods=["GET"])
@requires_auth
@requires_role("caregiver", "aidant")
def get_caregiver_alerts():
    caregiver_user_id_auth = g.user_id_auth
    status = (request.args.get("status", default="OPEN", type=str) or "OPEN").strip().upper()
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
            from services.alert_service import open_alert_query_requires_doctor_triage

            query.update(open_alert_query_requires_doctor_triage())
    cursor = get_medical_db().alerts.find(query).sort("created_at", -1).limit(limit)
    alerts = []
    for alert in cursor:
        out = format_alert_for_caregiver(dict(alert))
        out.pop("_id", None)
        _sanitize_alert_dict(out)
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
        _finalize_alert_api_payload(dict(alert), out, auth_id, include_patient_address=False)
        alerts.append(out)
    return jsonify({"caregiver_id": caregiver_user_id_auth, "status_filter": status, "count": len(alerts), "alerts": alerts}), 200


@app.route("/api/doctor/alerts/<alert_id>", methods=["GET"])
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
    _finalize_alert_api_payload(alert_doc, out, auth_id, include_patient_address=True)

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


@app.route("/api/doctor/alerts/<alert_id>", methods=["PATCH"])
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
            {"$push": {"emergency_escalations": entry}, "$set": {"updated_at": now}},
        )
        write_alert_event(
            medical_alert_id=alert_id,
            event_type="doctor_escalation",
            actor_user_id_auth=g.user_id_auth,
            actor_role="doctor",
            payload={"escalation_type": etype},
        )
        response["emergency_escalation_logged"] = {"type": etype, "at": datetime_to_iso_utc(now)}
    return jsonify(response), 200


@app.route("/api/caregiver/alerts/<alert_id>", methods=["PATCH"])
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


@app.route("/api/caregiver/invitations/accept", methods=["POST"])
@requires_auth
def accept_caregiver_invitation():
    payload = request.get_json(silent=True) or {}
    invite_token = str(payload.get("invite_token") or "").strip()
    if not invite_token:
        return jsonify({"code": "invalid_payload", "message": "invite_token is required"}), 400
    token_hash = hash_secret_token(invite_token)
    invite = get_identity_db().caregiver_invites.find_one({"token_hash": token_hash})
    if not invite:
        return jsonify({"code": "invite_not_found", "message": "Invitation introuvable ou expirée"}), 404
    if invite.get("used_at"):
        return jsonify({"code": "invite_used", "message": "Cette invitation a déjà été utilisée"}), 409
    expires_at = invite.get("expires_at")
    if isinstance(expires_at, datetime):
        exp = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
        if exp < datetime.now(timezone.utc):
            return jsonify({"code": "invite_expired", "message": "Cette invitation a expiré"}), 410
    patient_user_id_auth = invite["patient_user_id_auth"]
    caregiver_user_id_auth = g.user_id_auth
    if caregiver_user_id_auth == patient_user_id_auth:
        return jsonify({"code": "self_link", "message": "Vous ne pouvez pas être votre propre aidant"}), 400
    try:
        get_identity_db().caregiver_patients.update_one(
            {"caregiver_user_id_auth": caregiver_user_id_auth, "patient_user_id_auth": patient_user_id_auth},
            {"$setOnInsert": {"caregiver_user_id_auth": caregiver_user_id_auth, "patient_user_id_auth": patient_user_id_auth,
                             "created_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        # Update role to caregiver if needed, and enrich profile when email/name are missing
        current = get_identity_db().users.find_one({"user_id_auth": caregiver_user_id_auth}) or {}
        role_update = {}
        if get_user_role(caregiver_user_id_auth) not in ("caregiver", "aidant", "doctor", "admin"):
            role_update["role"] = "caregiver"
        # Enrich profile if email/name missing (Auth0 JWT may lack claims; invite has caregiver_email)
        if not (current.get("email") and current.get("display_name")):
            profile = _extract_profile_from_jwt(getattr(g, "jwt_payload", {}) or {}, caregiver_user_id_auth)
            if not current.get("email") and invite.get("caregiver_email"):
                role_update["email"] = invite["caregiver_email"].strip()[:256]
            elif not current.get("email") and profile.get("email"):
                role_update["email"] = profile["email"]
            if not current.get("display_name") and profile.get("display_name"):
                role_update["display_name"] = profile["display_name"][:128]
            if not current.get("first_name") and profile.get("first_name"):
                role_update["first_name"] = profile["first_name"]
            if not current.get("last_name") and profile.get("last_name"):
                role_update["last_name"] = profile["last_name"]
            if not current.get("picture") and profile.get("picture"):
                role_update["picture"] = profile["picture"]
        if role_update:
            get_identity_db().users.update_one({"user_id_auth": caregiver_user_id_auth}, {"$set": role_update})
        get_identity_db().caregiver_invites.update_one(
            {"_id": invite["_id"]},
            {"$set": {"used_at": datetime.now(timezone.utc), "accepted_by": caregiver_user_id_auth}},
        )
        log_caregiver_audit_event(
            "caregiver_invite_accepted",
            actor_user_id_auth=caregiver_user_id_auth,
            patient_user_id_auth=patient_user_id_auth,
            caregiver_user_id_auth=caregiver_user_id_auth,
            caregiver_email=invite.get("caregiver_email"),
            details={"invite_created_at": str(invite.get("created_at"))},
        )
        logger.info("Caregiver invite accepted: %s linked to patient %s", caregiver_user_id_auth, patient_user_id_auth)
    except PyMongoError as e:
        raise DatabaseError({"code": "accept_error", "message": f"Failed to accept caregiver invitation: {str(e)}"}, 500)
    return jsonify({"message": "Invitation acceptée - vous êtes maintenant aidant de ce patient",
                    "patient_user_id_auth": patient_user_id_auth, "role": "caregiver"}), 200


# ============================================================================
# ROUTES - Measurements, Trends, Alerts, Feedback
# ============================================================================

def _resolve_patient_id(patient_id: str) -> str:
    """Resolve URL patient_id (db id or auth id) to user_id_auth. Raises 404 if not found."""
    resolved = resolve_patient_id_to_user_id_auth(patient_id)
    if not resolved:
        raise DatabaseError({"code": "patient_not_found", "message": "Patient not found"}, 404)
    return resolved


@app.route("/api/patients/<patient_id>/measurements", methods=["GET"])
@requires_auth
def get_authorized_patient_measurements(patient_id: str):
    patient_id = _resolve_patient_id(patient_id)
    ensure_patient_access_or_403(patient_id)
    device_id = get_device_id(patient_id)
    if not device_id:
        raise DatabaseError({"code": "device_not_found", "message": "No device record found for patient"}, 404)
    limit = request.args.get("limit", default=200, type=int)
    from_raw = request.args.get("from", default=None, type=str)
    to_raw = request.args.get("to", default=None, type=str)
    try:
        from_dt = parse_iso_datetime(from_raw, "from")
        to_dt = parse_iso_datetime(to_raw, "to")
        if from_dt and to_dt and from_dt > to_dt:
            return jsonify({"code": "invalid_payload", "message": "'from' must be <= 'to'"}), 400
    except ValueError as e:
        return jsonify({"code": "invalid_payload", "message": str(e)}), 400
    measurements = query_patient_measurements_range(device_id=device_id, limit=limit, from_dt=from_dt, to_dt=to_dt)
    return jsonify({"patient_id": patient_id, "device_id": device_id, "count": len(measurements),
                    "filters": {"limit": min(max(limit, 1), 1000), "from": from_raw, "to": to_raw},
                    "latest_measurement": measurements[0] if measurements else None, "measurements": measurements}), 200


@app.route("/api/doctor/patients/<patient_id>/measurements", methods=["GET"])
@requires_auth
@requires_role("doctor")
def get_doctor_patient_measurements(patient_id: str):
    patient_id = _resolve_patient_id(patient_id)
    ensure_patient_access_or_403(patient_id)
    device_id = get_device_id(patient_id)
    if not device_id:
        raise DatabaseError({"code": "device_not_found", "message": "No device record found for patient"}, 404)
    days = request.args.get("days", default=30, type=int)
    limit = request.args.get("limit", default=500, type=int)
    measurements = query_patient_measurements(device_id=device_id, days=days, limit=limit)
    return jsonify({"patient_id": patient_id, "device_id": device_id, "days": days,
                    "count": len(measurements), "measurements": measurements}), 200


@app.route("/api/doctor/patients/<patient_id>/trends", methods=["GET"])
@requires_auth
@requires_role("doctor")
def get_doctor_patient_trends(patient_id: str):
    patient_id = _resolve_patient_id(patient_id)
    patient_ids = set(get_assigned_patient_ids_for_doctor(g.user_id_auth))
    if patient_id not in patient_ids:
        return jsonify({"code": "patient_not_assigned", "message": "This patient is not assigned to the authenticated doctor"}), 403
    device_id = get_device_id(patient_id)
    if not device_id:
        raise DatabaseError({"code": "device_not_found", "message": "No device record found for patient"}, 404)
    measurements = query_patient_measurements(device_id=device_id, days=30, limit=1500)
    trend_7 = build_trend_window(measurements, 7)
    trend_30 = build_trend_window(measurements, 30)
    return jsonify({"patient_id": patient_id, "device_id": device_id, "trends": {"7d": trend_7, "30d": trend_30}}), 200


@app.route("/api/doctor/patients/<patient_id>/device", methods=["POST"])
@requires_auth
@requires_role("doctor", "superuser", "medecin")
def assign_device_to_patient(patient_id: str):
    """Associe un device_id à un patient - appelé par le médecin."""
    patient_id = _resolve_patient_id(patient_id)
    ensure_patient_access_or_403(patient_id)

    payload = request.get_json(silent=True) or {}
    device_id = str(payload.get("device_id") or "").strip()

    if not device_id:
        return jsonify({"code": "missing_device_id", "message": "device_id requis"}), 400

    existing = get_identity_db().users_devices.find_one({"device_id": device_id})
    if existing and existing.get("user_id_auth") != patient_id:
        return jsonify({
            "code": "device_already_assigned",
            "message": "Ce device est déjà assigné à un autre patient",
        }), 409

    now = datetime.now(timezone.utc)
    try:
        get_identity_db().users_devices.update_one(
            {"user_id_auth": patient_id},
            {
                "$set": {
                    "user_id_auth": patient_id,
                    "device_id": device_id,
                    "assigned_by": g.user_id_auth,
                    "assigned_at": now,
                }
            },
            upsert=True,
        )
    except PyMongoError as e:
        raise DatabaseError({"code": "device_assign_error", "message": str(e)}, 500)

    return jsonify({
        "message": "Device assigné au patient",
        "patient_id": patient_id,
        "device_id": device_id,
        "assigned_at": datetime_to_iso_utc(now),
    }), 200


@app.route("/api/doctor/patients/<patient_id>/device", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser", "medecin")
def get_patient_device(patient_id: str):
    """Retourne le device_id associé à un patient."""
    patient_id = _resolve_patient_id(patient_id)
    ensure_patient_access_or_403(patient_id)

    doc = get_identity_db().users_devices.find_one(
        {"user_id_auth": patient_id},
        {"_id": 0},
    )
    if not doc or not doc.get("device_id"):
        return jsonify({"code": "no_device", "message": "Aucun device assigné"}), 404

    assigned_at = doc.get("assigned_at")
    return jsonify({
        "patient_id": patient_id,
        "device_id": doc.get("device_id"),
        "assigned_at": datetime_to_iso_utc(assigned_at) if assigned_at else None,
    }), 200


@app.route("/api/doctor/alerts", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser", "medecin")
def get_doctor_alerts():
    doctor_user_id_auth = g.user_id_auth
    status = (request.args.get("status", default="OPEN", type=str) or "OPEN").strip().upper()
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
            from services.alert_service import open_alert_query_requires_doctor_triage

            query.update(open_alert_query_requires_doctor_triage())
    cursor = get_medical_db().alerts.find(query).sort("created_at", -1).limit(limit)
    alerts = []
    for alert in cursor:
        out = format_alert_for_doctor(dict(alert))
        out.pop("_id", None)
        _sanitize_alert_dict(out)
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
        _finalize_alert_api_payload(dict(alert), out, auth_id, include_patient_address=True)
        alerts.append(out)
    return jsonify({"doctor_id": doctor_user_id_auth, "status_filter": status, "count": len(alerts), "alerts": alerts}), 200


@app.route("/api/doctor/patients/<patient_id>/alert-thresholds", methods=["GET", "PUT"])
@requires_auth
@requires_role("doctor")
def doctor_patient_alert_thresholds(patient_id: str):
    patient_id = _resolve_patient_id(patient_id)
    patient_ids = set(get_assigned_patient_ids_for_doctor(g.user_id_auth))
    if patient_id not in patient_ids:
        return jsonify({"code": "patient_not_assigned", "message": "This patient is not assigned to the authenticated doctor"}), 403
    device_id = get_device_id(patient_id)
    if not device_id:
        raise DatabaseError({"code": "device_not_found", "message": "No device record found for patient"}, 404)
    collection = get_medical_db().alert_thresholds
    if request.method == "GET":
        patient_rule = collection.find_one({"scope": "patient", "device_id": device_id}, projection={"_id": 0}) or {}
        effective = get_alert_threshold_config(device_id=device_id, pathology=patient_rule.get("pathology"))
        return jsonify({"patient_id": patient_id, "device_id": device_id, "patient_rule": patient_rule, "effective_rule": effective}), 200
    payload = request.get_json(silent=True) or {}
    thresholds = merge_thresholds(payload.get("thresholds"))
    consecutive = payload.get("consecutive_breaches", ALERT_DEFAULT_CONSECUTIVE_BREACHES)
    try:
        consecutive = max(1, int(consecutive))
    except (TypeError, ValueError):
        return jsonify({"code": "invalid_payload", "message": "consecutive_breaches must be an integer >= 1"}), 400
    pathology = payload.get("pathology")
    if pathology is not None and isinstance(pathology, str):
        pathology = pathology.strip() or None
    enabled = bool(payload.get("enabled", True))
    now = datetime.now(timezone.utc)
    try:
        collection.delete_many({"scope": "patient", "device_id": device_id})
        collection.insert_one({
            "scope": "patient",
            "patient_user_id_auth": patient_id,
            "device_id": device_id,
            "pathology": pathology,
            "thresholds": thresholds,
            "consecutive_breaches": consecutive,
            "enabled": enabled,
            "updated_by": g.user_id_auth,
            "updated_at": now,
            "created_at": now,
        })
    except PyMongoError as e:
        raise DatabaseError({"code": "alert_thresholds_save_error", "message": str(e)}, 500)
    updated_rule = collection.find_one({"scope": "patient", "device_id": device_id}, projection={"_id": 0}) or {}
    return jsonify({"message": "Patient alert thresholds saved", "patient_id": patient_id, "device_id": device_id, "rule": updated_rule}), 200


@app.route("/api/doctor/patients/<patient_id>/feedback", methods=["POST"])
@requires_auth
@requires_role("doctor")
def create_doctor_feedback(patient_id: str):
    patient_id = _resolve_patient_id(patient_id)
    ensure_patient_access_or_403(patient_id)
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message") or "").strip()
    if not message:
        return jsonify({"code": "invalid_payload", "message": "message is required"}), 400
    if len(message) > 2000:
        return jsonify({"code": "invalid_payload", "message": "message exceeds 2000 characters"}), 400
    severity = payload.get("severity")
    if severity is not None and str(severity).strip().lower() not in ("low", "medium", "high"):
        return jsonify({"code": "invalid_payload", "message": "severity must be one of: low, medium, high"}), 400
    status = payload.get("status")
    if status is not None and str(status).strip().lower() not in ("new", "follow_up", "resolved"):
        return jsonify({"code": "invalid_payload", "message": "status must be one of: new, follow_up, resolved"}), 400
    recommendation = payload.get("recommendation")
    if recommendation is not None and len(str(recommendation).strip()) > 2000:
        return jsonify({"code": "invalid_payload", "message": "recommendation exceeds 2000 characters"}), 400
    now = datetime.now(timezone.utc)
    feedback_doc = {
        "patient_user_id_auth": patient_id, "doctor_user_id_auth": g.user_id_auth,
        "message": message, "severity": severity, "status": status or "new", "recommendation": recommendation,
        "created_at": now,
    }
    try:
        get_medical_db().doctor_feedback.insert_one(feedback_doc)
    except PyMongoError as e:
        raise DatabaseError({"code": "doctor_feedback_insert_error", "message": f"Failed to store doctor feedback: {str(e)}"}, 500)
    return jsonify({"message": "Doctor feedback created", "feedback": {**{k: v for k, v in feedback_doc.items() if k != "_id"}, "created_at": datetime_to_iso_utc(now)}}), 201


@app.route("/api/patients/<patient_id>/feedback/latest", methods=["GET"])
@requires_auth
def get_latest_feedback_for_patient(patient_id: str):
    patient_id = _resolve_patient_id(patient_id)
    ensure_patient_access_or_403(patient_id)
    limit = request.args.get("limit", default=5, type=int)
    feedbacks = list_latest_doctor_feedback(patient_user_id_auth=patient_id, limit=limit)
    return jsonify({"patient_id": patient_id, "count": len(feedbacks), "feedback": feedbacks}), 200


@app.route("/api/patients/<patient_id>/doctor-info", methods=["GET"])
@requires_auth
@requires_role("patient", "doctor", "caregiver", "aidant", "admin", "superuser", "medecin")
def get_patient_doctor_info(patient_id: str):
    """Return the patient's doctor(s) info for display to patient or caregiver."""
    patient_id = _resolve_patient_id(patient_id)
    ensure_patient_access_or_403(patient_id)
    doctor_ids = get_assigned_doctor_ids_for_patient(patient_id)
    doctors = []
    for idx, did in enumerate(doctor_ids):
        doc_profile = get_user_profile(did)
        disp = doc_profile.get("display_name") or doc_profile.get("email") or ""
        fname, lname = _split_display_name(disp) if disp else ("", "")
        if not fname and not lname:
            fname = disp
        contact = doc_profile.get("contact") or doc_profile.get("email") or ""
        phone = doc_profile.get("phone") or ""
        doctors.append({
            "id": idx,
            "user_id_auth": did,
            "first_name": fname,
            "last_name": lname,
            "display_name": disp or f"{fname} {lname}".strip() or did,
            "contact": contact,
            "phone": phone,
            "email": doc_profile.get("email") or "",
        })
    return jsonify({"patient_id": patient_id, "doctors": doctors}), 200


@app.route("/api/patients/<patient_id>/profile", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser", "caregiver", "aidant", "admin", "medecin")
def get_patient_profile_for_doctor(patient_id: str):
    """Return the patient's profile for display to doctor (name, age, contact, medical history)."""
    patient_id = _resolve_patient_id(patient_id)
    ensure_patient_access_or_403(patient_id)
    profile = get_user_profile(patient_id)
    display_name = profile.get("display_name") or profile.get("email") or patient_id
    first_name = profile.get("first_name") or ""
    last_name = profile.get("last_name") or ""
    if not first_name and not last_name:
        first_name, last_name = _split_display_name(display_name) if display_name else ("", "")
    return jsonify({
        "patient_id": patient_id,
        "profile": {
            "display_name": display_name,
            "first_name": first_name,
            "last_name": last_name,
            "email": profile.get("email") or "",
            "phone": profile.get("phone") or "",
            "contact": profile.get("contact") or "",
            "birthdate": profile.get("birthdate"),
            "age": profile.get("age"),
            "sex": profile.get("sex"),
            "medical_history": profile.get("medical_history"),
            "onboarding_completed": profile.get("onboarding_completed", False),
            "address_line1": profile.get("address_line1") or "",
            "address_line2": profile.get("address_line2") or "",
            "postal_code": profile.get("postal_code") or "",
            "city": profile.get("city") or "",
            "country": profile.get("country") or "",
        }
    }), 200


@app.route("/api/patients/<patient_id>/caregiver-info", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser", "caregiver", "aidant", "admin", "medecin")
def get_patient_caregiver_info(patient_id: str):
    """Return the patient's caregiver(s) info for display to doctor or caregiver.
    Includes linked caregivers (caregiver_patients) and fallback to emergency_contact from profile."""
    patient_id = _resolve_patient_id(patient_id)
    ensure_patient_access_or_403(patient_id)
    caregiver_ids = get_assigned_caregiver_ids_for_patient(patient_id)
    caregivers = []
    for idx, cid in enumerate(caregiver_ids):
        cg_profile = get_user_profile(cid)
        disp = cg_profile.get("display_name") or cg_profile.get("email") or ""
        fname, lname = _split_display_name(disp) if disp else ("", "")
        if not fname and not lname:
            fname = disp
        contact = cg_profile.get("contact") or cg_profile.get("email") or ""
        phone = cg_profile.get("phone") or ""
        caregivers.append({
            "id": idx,
            "user_id_auth": cid,
            "first_name": fname,
            "last_name": lname,
            "display_name": disp or f"{fname} {lname}".strip() or cid,
            "contact": contact,
            "phone": phone,
            "email": cg_profile.get("email") or "",
        })
    # Fallback: if no linked caregivers, include emergency_contact from patient profile
    if not caregivers:
        patient_profile = get_user_profile(patient_id)
        ec = patient_profile.get("emergency_contact") or {}
        if isinstance(ec, dict) and (ec.get("first_name") or ec.get("last_name") or ec.get("email") or ec.get("phone")):
            fname = str(ec.get("first_name") or "").strip() or ""
            lname = str(ec.get("last_name") or "").strip() or ""
            disp = f"{fname} {lname}".strip() or ec.get("email") or ec.get("phone") or "Aidant"
            caregivers.append({
                "id": 0,
                "user_id_auth": None,
                "first_name": fname or None,
                "last_name": lname or None,
                "display_name": disp,
                "contact": ec.get("email") or ec.get("phone") or "",
                "phone": str(ec.get("phone") or "").strip() or None,
                "email": str(ec.get("email") or "").strip() or "",
            })
    return jsonify({"patient_id": patient_id, "caregivers": caregivers}), 200


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "healthcare-api"}), 200


# ============================================================================
# ROUTES - ML
# ============================================================================

@app.route("/api/ml/info", methods=["GET"])
def ml_model_info():
    return jsonify(ml_module.get_model_info()), 200


@app.route("/api/admin/ml/model-info", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser")
def admin_ml_model_info():
    """Alias explicite : même charge utile que GET /api/ml/info (+ auth admin)."""
    return jsonify(ml_module.get_model_info()), 200


@app.route("/api/doctor/ml-anomalies", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser")
def list_ml_anomalies():
    doctor_user_id_auth = g.user_id_auth
    role = get_current_user_role()
    allowed_devices: Optional[List[str]] = None
    if role != "superuser":
        patient_ids = get_assigned_patient_ids_for_doctor(doctor_user_id_auth)
        if not patient_ids:
            return jsonify({"anomalies": [], "count": 0}), 200
        allowed_devices = [d for d in (get_device_id(p) for p in patient_ids) if d]
        if not allowed_devices:
            return jsonify({"anomalies": [], "count": 0}), 200
    status_filter = request.args.get("status")
    device_id = request.args.get("device_id")
    severity = request.args.get("severity")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    limit = min(int(request.args.get("limit", "50")), 200)
    query: Dict[str, Any] = {}
    if device_id:
        if allowed_devices is not None and device_id not in allowed_devices:
            return jsonify({"anomalies": [], "count": 0}), 200
        query["device_id"] = device_id
    elif allowed_devices is not None:
        # device_id filtre les anomalies même si user_id_auth manque sur le document (bug fréquent)
        query["device_id"] = {"$in": allowed_devices}
    if status_filter in ("pending", "validated", "rejected"):
        query["status"] = status_filter
    if severity in ("critical", "warning"):
        query["anomaly_level"] = severity
    if from_date or to_date:
        date_q: Dict[str, Any] = {}
        if from_date:
            try:
                date_q["$gte"] = datetime.fromisoformat(from_date)
            except ValueError:
                pass
        if to_date:
            try:
                date_q["$lte"] = datetime.fromisoformat(to_date)
            except ValueError:
                pass
        if date_q:
            query["created_at"] = date_q
    try:
        cursor = get_medical_db().ml_anomalies.find(query).sort("created_at", -1).limit(limit)
        anomalies = []
        for doc in cursor:
            doc["anomaly_id"] = str(doc.pop("_id"))
            if doc.get("measurement_id"):
                doc["measurement_id"] = str(doc["measurement_id"])
            for dt_field in ("measured_at", "created_at", "validated_at"):
                if isinstance(doc.get(dt_field), datetime):
                    doc[dt_field] = datetime_to_iso_utc(doc[dt_field])
            anomalies.append(doc)
        return jsonify({"anomalies": anomalies, "count": len(anomalies)}), 200
    except PyMongoError as e:
        raise DatabaseError({"code": "ml_anomalies_query_error", "message": str(e)}, 500)


@app.route("/api/doctor/ml-anomalies/<anomaly_id>", methods=["PATCH"])
@requires_auth
@requires_role("doctor", "superuser")
def validate_ml_anomaly(anomaly_id: str):
    payload = request.get_json(silent=True) or {}
    new_status = payload.get("status")
    if new_status not in ("validated", "rejected"):
        return jsonify({"code": "invalid_payload", "message": "status must be 'validated' or 'rejected'"}), 400
    try:
        oid = ObjectId(anomaly_id)
    except Exception:
        return jsonify({"code": "invalid_id", "message": "anomaly_id is not a valid ObjectId"}), 400
    anomaly_doc = get_medical_db().ml_anomalies.find_one({"_id": oid})
    if not anomaly_doc:
        return jsonify({"code": "not_found", "message": "Anomaly not found"}), 404
    role = get_current_user_role()
    if role != "superuser":
        patient_ids = get_assigned_patient_ids_for_doctor(g.user_id_auth)
        allowed_devices = {d for p in patient_ids if (d := get_device_id(p))}
        uid = anomaly_doc.get("user_id_auth")
        dev = anomaly_doc.get("device_id")
        if uid and uid not in patient_ids:
            return jsonify({"code": "forbidden", "message": "This anomaly belongs to a patient not assigned to you"}), 403
        if not uid and dev not in allowed_devices:
            return jsonify({"code": "forbidden", "message": "This anomaly belongs to a patient not assigned to you"}), 403
    if anomaly_doc.get("status") == new_status:
        return jsonify({
            "message": f"Anomaly already {new_status}",
            "anomaly_id": anomaly_id,
            "status": new_status,
            "validated_by": anomaly_doc.get("validated_by"),
            "validated_at": datetime_to_iso_utc(anomaly_doc["validated_at"]) if anomaly_doc.get("validated_at") else None,
        }), 200
    now = datetime.now(timezone.utc)
    get_medical_db().ml_anomalies.update_one(
        {"_id": oid},
        {"$set": {"status": new_status, "validated_by": g.user_id_auth, "validated_at": now}}
    )
    measurement_id = anomaly_doc.get("measurement_id")
    if measurement_id:
        try:
            get_medical_db().measurements.update_one(
                {"_id": measurement_id},
                {"$set": {"ml_anomaly_status": new_status, "ml_validated_by": g.user_id_auth, "ml_validated_at": now}}
            )
        except PyMongoError:
            logger.warning("Failed to propagate validation to measurement %s", measurement_id)
    audit_alert_id = None
    audit_mode = None
    if new_status == "validated":
        try:
            aid, audit_mode = create_or_merge_alert_for_validated_ml(
                dict(anomaly_doc), oid, g.user_id_auth
            )
            if aid is not None:
                audit_alert_id = str(aid)
        except Exception as e:
            logger.warning("ML validated → alerts audit failed: %s", e)
    # Déclencher le réentraînement ML en arrière-plan (validated/rejected servent au feedback)
    def _retrain_in_background():
        try:
            do_ml_retrain(days=30, trigger="ml_validation_feedback")
        except Exception as e:
            logger.warning("Background ML retrain after validation failed: %s", e)
    threading.Thread(target=_retrain_in_background, daemon=True).start()
    body: Dict[str, Any] = {
        "message": f"Anomaly {new_status}",
        "anomaly_id": anomaly_id,
        "status": new_status,
        "validated_by": g.user_id_auth,
        "validated_at": datetime_to_iso_utc(now),
    }
    if audit_alert_id:
        body["audit_alert_id"] = audit_alert_id
    if audit_mode:
        body["audit_alert_mode"] = audit_mode
    return jsonify(body), 200


@app.route("/api/admin/ml/retrain", methods=["POST"])
@requires_auth
@requires_role("doctor", "superuser")
def retrain_ml_model():
    payload = request.get_json(silent=True) or {}
    days, contamination = int(payload.get("days", 30)), float(payload.get("contamination", 0.05))
    n_estimators = int(payload.get("n_estimators", 150))
    try:
        meta = do_ml_retrain(
            days=days, contamination=contamination, n_estimators=n_estimators, trigger="manual"
        )
    except PyMongoError as e:
        raise DatabaseError({"code": "training_data_error", "message": str(e)}, 500)
    except ValueError as e:
        return jsonify({"code": "training_error", "message": str(e)}), 400
    return jsonify({"message": "Model retrained successfully", **meta}), 200


@app.route("/api/admin/ml/batch-score", methods=["POST"])
@requires_auth
@requires_role("doctor", "superuser")
def batch_score_measurements():
    payload = request.get_json(silent=True) or {}
    limit, days = int(payload.get("limit", 5000)), int(payload.get("days", 30))
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    try:
        cursor = get_medical_db().measurements.find(
            {"measured_at": {"$gte": cutoff}, "$or": [{"ml_score": None}, {"ml_score": {"$exists": False}}]}
        ).sort("measured_at", -1).limit(limit)
        scored = skipped = errors = 0
        for doc in cursor:
            try:
                ml_result = run_ml_scoring(device_id=doc.get("device_id", "unknown"), measurement_doc=doc)
                skipped += 1 if ml_result.get("ml_skipped") else 0
                scored += 0 if ml_result.get("ml_skipped") else 1
            except Exception:
                errors += 1
        return jsonify({"message": "Batch scoring complete", "scored": scored, "skipped": skipped, "errors": errors}), 200
    except PyMongoError as e:
        raise DatabaseError({"code": "batch_score_error", "message": str(e)}, 500)


@app.route("/api/admin/ml/bootstrap", methods=["POST"])
@requires_auth
@requires_role("doctor", "superuser")
def ml_bootstrap():
    payload = request.get_json(silent=True) or {}
    train_days = int(payload.get("train_days", 365))
    score_days = int(payload.get("score_days", 365))
    score_limit = int(payload.get("score_limit", 10000))
    contamination = float(payload.get("contamination", 0.05))
    n_estimators = int(payload.get("n_estimators", 150))
    train_cutoff = datetime.now(timezone.utc) - timedelta(days=max(train_days, 1))
    try:
        train_measurements = list(get_medical_db().measurements.find(
            {"status": "VALID", "measured_at": {"$gte": train_cutoff}},
            projection={"_id": 0, "heart_rate": 1, "spo2": 1, "temperature": 1, "signal_quality": 1, "status": 1}
        ).limit(50000))
    except PyMongoError as e:
        raise DatabaseError({"code": "bootstrap_training_data_error", "message": str(e)}, 500)
    validated_anomalies = []
    try:
        raw_anomalies = list(get_medical_db().ml_anomalies.find(
            {"status": {"$in": ["validated", "rejected"]}},
            projection={
                "_id": 0, "measurement_id": 1, "status": 1, "user_id_auth": 1,
                "heart_rate": 1, "spo2": 1, "temperature": 1, "signal_quality": 1, "measurement": 1,
            },
        ).sort("validated_at", -1).limit(10000))
        for a in raw_anomalies:
            if a.get("measurement"):
                validated_anomalies.append(a)
            elif a.get("measurement_id"):
                m = get_medical_db().measurements.find_one(
                    {"_id": a["measurement_id"]},
                    projection={"heart_rate": 1, "spo2": 1, "temperature": 1, "signal_quality": 1, "status": 1}
                )
                if m:
                    a["measurement"] = m
                    validated_anomalies.append(a)
    except PyMongoError:
        pass
    try:
        meta = ml_module.train_model(measurements=train_measurements, validated_anomalies=validated_anomalies,
                                     contamination=contamination, n_estimators=n_estimators)
    except ValueError as e:
        return jsonify({"code": "bootstrap_training_error", "message": str(e)}), 400
    try:
        get_medical_db().ml_model_versions.insert_one({
            "version": meta["version"], "trained_at": meta["trained_at"], "n_samples": meta["n_samples"],
            "contamination": meta["contamination"], "n_estimators": meta["n_estimators"],
            "created_at": datetime.now(timezone.utc),
        })
    except PyMongoError:
        pass
    score_cutoff = datetime.now(timezone.utc) - timedelta(days=max(score_days, 1))
    scored = skipped = errors = n_critical = n_warning = 0
    try:
        cursor = get_medical_db().measurements.find(
            {"measured_at": {"$gte": score_cutoff}, "$or": [{"ml_score": None}, {"ml_score": {"$exists": False}}]}
        ).sort("measured_at", -1).limit(score_limit)
        for doc in cursor:
            try:
                ml_result = run_ml_scoring(device_id=doc.get("device_id", "unknown"), measurement_doc=doc)
                if ml_result.get("ml_skipped"):
                    skipped += 1
                else:
                    scored += 1
                    if ml_result.get("ml_level") == "critical":
                        n_critical += 1
                    elif ml_result.get("ml_level") == "warning":
                        n_warning += 1
            except Exception:
                errors += 1
    except PyMongoError as e:
        raise DatabaseError({"code": "bootstrap_score_error", "message": str(e)}, 500)
    n_pending = 0
    try:
        n_pending = get_medical_db().ml_anomalies.count_documents({"status": "pending"})
    except PyMongoError:
        pass
    return jsonify({"message": "Bootstrap complete", "model": meta, "n_train": len(train_measurements),
                    "n_scored": scored, "n_skipped": skipped, "n_errors": errors,
                    "n_warning": n_warning, "n_critical": n_critical, "n_pending": n_pending}), 200


@app.route("/api/admin/ml/test", methods=["POST"])
@requires_auth
@requires_role("doctor", "superuser")
def run_ml_test():
    import ml_test
    payload = request.get_json(silent=True) or {}
    custom = payload.get("measurements")
    results = ml_test.run_custom_test(custom) if custom and isinstance(custom, list) else ml_test.run_all_tests()
    return jsonify(results), 200


@app.route("/api/admin/ml/thresholds", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser")
def get_ml_thresholds():
    return jsonify(ml_module.get_model_info()), 200


@app.route("/api/admin/ml/thresholds", methods=["PUT"])
@requires_auth
@requires_role("doctor", "superuser")
def update_ml_thresholds():
    payload = request.get_json(silent=True) or {}
    normal_max, warning_max = payload.get("normal_max"), payload.get("warning_max")
    if normal_max is None and warning_max is None:
        return jsonify({"code": "invalid_payload", "message": "Provide normal_max and/or warning_max"}), 400
    ml_module.configure_thresholds(normal_max=normal_max, warning_max=warning_max)
    try:
        save_ml_thresholds_to_db()
    except PyMongoError as e:
        logger.warning("Could not persist ml_thresholds: %s", e)
    return jsonify({"message": "Thresholds updated", **ml_module.get_model_info()}), 200


@app.route("/api/ml/decisions", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser")
def list_ml_decisions():
    device_id = request.args.get("device_id")
    limit = min(int(request.args.get("limit", "50")), 500)
    query: Dict[str, Any] = {}
    if device_id:
        query["device_id"] = device_id
    try:
        cursor = get_medical_db().ml_decisions.find(
            query, projection={"_id": 0, "measurement_id": 0}
        ).sort("processed_at", -1).limit(limit)
        decisions = []
        for doc in cursor:
            for dt_field in ("measured_at", "processed_at"):
                if isinstance(doc.get(dt_field), datetime):
                    doc[dt_field] = datetime_to_iso_utc(doc[dt_field])
            decisions.append(doc)
        return jsonify({"decisions": decisions, "count": len(decisions)}), 200
    except PyMongoError as e:
        raise DatabaseError({"code": "ml_decisions_query_error", "message": str(e)}, 500)


@app.route("/api/doctor/ml/forecast/<patient_id>", methods=["GET", "OPTIONS"])
@requires_auth
@requires_role("doctor", "superuser", "caregiver", "aidant")
def get_ml_forecast(patient_id: str):
    patient_id = _resolve_patient_id(patient_id)
    ensure_patient_access_or_403(patient_id)
    device_ids = get_device_ids(patient_id)
    if not device_ids:
        raise DatabaseError({"code": "device_not_found", "message": "No device record found for patient"}, 404)
    train_days = request.args.get("train_days", type=int) or request.args.get("days", type=int) or 30
    history_hours = request.args.get("history_hours", 48, type=int) or 48
    horizon = request.args.get("horizon", 24, type=int) or 24
    train_days = max(7, min(train_days, 365))
    history_hours = max(12, min(history_hours, 7 * 24))
    horizon = max(1, min(horizon, 72))  # horizon in hours (24 = full day)
    measurements = query_patient_measurements_for_devices(device_ids=device_ids, days=train_days, limit=5000)
    if len(measurements) < 3:
        return jsonify({"code": "insufficient_data", "message": f"Attendre plus de mesures ({len(measurements)} < 3)", "patient_id": patient_id}), 400
    try:
        result = ml_module.forecast_vitals(measurements, horizon=horizon, history_window_hours=history_hours)
    except ValueError as e:
        return jsonify({"code": "forecast_error", "message": str(e)}), 400
    result["patient_id"] = get_user_db_id(patient_id) or patient_id
    result["device_ids"] = device_ids
    result["train_days"] = train_days
    result["history_hours"] = history_hours
    try:
        user_doc = get_identity_db().users.find_one({"user_id_auth": patient_id}, {"display_name": 1, "email": 1})
        if user_doc:
            result["patient_display"] = user_doc.get("display_name") or user_doc.get("email")
    except Exception:
        pass
    return jsonify(result), 200


@app.route("/api/doctor/ml/patient-analysis/<patient_id>", methods=["GET", "OPTIONS"])
@requires_auth
@requires_role("doctor", "superuser", "caregiver", "aidant")
def get_patient_ml_analysis(patient_id: str):
    patient_id = _resolve_patient_id(patient_id)
    ensure_patient_access_or_403(patient_id)
    device_ids = get_device_ids(patient_id)
    if not device_ids:
        raise DatabaseError({"code": "device_not_found", "message": "No device record found for patient"}, 404)
    days = request.args.get("days", 30, type=int) or 30
    days = max(7, min(days, 365))
    include_forecast = request.args.get("include_forecast", "true").lower() != "false"
    forecast_horizon = request.args.get("forecast_horizon", 24, type=int) or 24
    forecast_horizon = max(1, min(forecast_horizon, 72))  # horizon in hours (24 = full day)
    measurements = query_patient_measurements_for_devices(device_ids=device_ids, days=days, limit=50000)
    if len(measurements) < 3:
        return jsonify({"code": "insufficient_data", "message": f"Attendre plus de mesures ({len(measurements)} < 3)", "patient_id": patient_id}), 400
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    ml_decisions_list, anomaly_records = [], []
    try:
        ml_decisions_list = list(get_medical_db().ml_decisions.find(
            {"device_id": {"$in": device_ids}, "measured_at": {"$gte": cutoff}}, projection={"_id": 0}
        ).sort("measured_at", -1).limit(5000))
        anomaly_records = list(get_medical_db().ml_anomalies.find(
            {"device_id": {"$in": device_ids}, "created_at": {"$gte": cutoff}}, projection={"_id": 0}
        ).sort("created_at", -1).limit(200))
    except Exception:
        pass
    for doc in ml_decisions_list + anomaly_records:
        for key, val in doc.items():
            if isinstance(val, datetime):
                doc[key] = datetime_to_iso_utc(val)
    threshold_alert_docs: List[Dict[str, Any]] = []
    try:
        threshold_alert_docs = list(get_medical_db().alerts.find(
            {"device_id": {"$in": device_ids}, "created_at": {"$gte": cutoff}, "metric": {"$ne": "ml_anomaly"}},
        ).sort("created_at", -1).limit(400))
    except Exception:
        threshold_alert_docs = []
    for doc in threshold_alert_docs:
        for key, val in doc.items():
            if isinstance(val, datetime):
                doc[key] = datetime_to_iso_utc(val)
    result = ml_module.analyze_patient_vitals(measurements, ml_scores=ml_decisions_list, anomaly_records=anomaly_records)
    _max_sev = _weekly_summary_max_severity(result)
    result["clinical_narrative_summary"] = _build_clinical_weekly_narrative(result, _max_sev)
    result["anomaly_summary"] = _build_combined_anomaly_summary_for_analysis(
        anomaly_records, threshold_alert_docs
    )
    if include_forecast and len(measurements) >= 3:
        try:
            result["forecast"] = ml_module.forecast_vitals(measurements, horizon=forecast_horizon, history_window_hours=48)
        except Exception as e:
            result["forecast"] = {"error": str(e)}
    result["patient_id"] = get_user_db_id(patient_id) or patient_id
    result["device_ids"] = device_ids
    result["days"] = days
    result["n_total_measurements"] = count_patient_measurements_total(device_ids)
    try:
        user_doc = get_identity_db().users.find_one({"user_id_auth": patient_id}, {"display_name": 1, "email": 1})
        if user_doc:
            result["patient_display"] = user_doc.get("display_name") or user_doc.get("email")
    except Exception:
        pass
    return jsonify(result), 200

@app.route("/api/device/measurements", methods=["POST"])
def submit_device_measurement():
    payload = request.get_json(silent=True) or {}
    device_id = str(payload.get("device_id") or "").strip()
    if not device_id:
        return jsonify({"code": "missing_device_id", "message": "device_id requis"}), 400

    # Vérifier dans users_devices - c'est là que sont les vrais devices
    device_doc = get_identity_db().users_devices.find_one({"device_id": device_id})
    if not device_doc:
        return jsonify({"code": "unknown_device", "message": "device_id inconnu"}), 403

    try:
        normalized = normalize_patient_measurement_payload(payload)
    except ValueError as e:
        return jsonify({"code": "invalid_payload", "message": str(e)}), 400

    measurement_doc = {
        "device_id":         device_id,
        "measured_at":       normalized["measured_at"],
        "heart_rate":        normalized["heart_rate"],
        "spo2":              normalized["spo2"],
        "temperature":       normalized["temperature"],
        "signal_quality":    normalized["signal_quality"],
        "source":            normalized["source"],
        "status":            normalized["status"],
        "validation_reasons": normalized["reasons"],
    }

    try:
        ins = get_medical_db().measurements.insert_one(measurement_doc)
        measurement_doc["_id"] = ins.inserted_id
    except PyMongoError as e:
        return jsonify({"code": "insert_error", "message": str(e)}), 500

    try:
        run_ml_scoring(device_id=device_id, measurement_doc=measurement_doc)
    except Exception as e:
        logger.warning("ML scoring failed: %s", e)

    if normalized["status"] == "VALID":
        try:
            schedule_retrain_after_new_measurement(device_id)
        except Exception as e:
            logger.warning("Schedule ML retrain after device measurement failed: %s", e)

    return jsonify({
        "message":        "Mesure enregistree",
        "device_id":      device_id,
        "measurement_id": str(ins.inserted_id),
    }), 201


# ============================================================================
# ROUTES - Device Enrollment
# ============================================================================


@app.route("/api/device/enrollment", methods=["POST"])
def create_enrollment_code():
    """ESP32 soumet un code d'enrollment - stocké 10 minutes en base."""
    payload = request.get_json(silent=True) or {}
    device_id = str(payload.get("device_id") or "").strip()
    enrollment_code = str(payload.get("enrollment_code") or "").strip()

    if not device_id or not enrollment_code:
        return jsonify({"code": "missing_fields", "message": "device_id et enrollment_code requis"}), 400

    device_doc = get_identity_db().users_devices.find_one({"device_id": device_id})
    if not device_doc:
        return jsonify({"code": "unknown_device", "message": "Device inconnu"}), 403

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=10)

    try:
        get_identity_db().device_enrollments.update_one(
            {"device_id": device_id},
            {"$set": {
                "device_id": device_id,
                "enrollment_code": enrollment_code,
                "enrolled": False,
                "created_at": now,
                "expires_at": expires_at,
            }},
            upsert=True,
        )
    except PyMongoError as e:
        logger.warning("device_enrollments upsert failed: %s", e)
        return jsonify({"code": "enrollment_store_error", "message": str(e)}), 500

    logger.info("Enrollment code created for device %s", device_id)
    return jsonify({
        "message": "Code enrollment enregistre",
        "device_id": device_id,
        "expires_at": datetime_to_iso_utc(expires_at),
    }), 201


@app.route("/api/device/enrollment/status", methods=["GET"])
def check_enrollment_status():
    """ESP32 vérifie si le patient a validé le code."""
    device_id = request.args.get("device_id", "").strip()
    if not device_id:
        return jsonify({"code": "missing_device_id"}), 400

    doc = get_identity_db().device_enrollments.find_one({"device_id": device_id})
    if not doc:
        return jsonify({"enrolled": False}), 200

    expires_at = doc.get("expires_at")
    if isinstance(expires_at, datetime):
        exp = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
        if exp < datetime.now(timezone.utc):
            return jsonify({"enrolled": False, "reason": "expired"}), 200

    return jsonify({"enrolled": doc.get("enrolled", False)}), 200


@app.route("/api/patient/enroll-device", methods=["POST"])
@requires_auth
@requires_role("patient")
def patient_enroll_device():
    """Patient entre le code à 6 chiffres pour lier le device à son compte."""
    payload = request.get_json(silent=True) or {}
    enrollment_code = str(payload.get("enrollment_code") or "").strip()

    if not enrollment_code:
        return jsonify({"code": "missing_code", "message": "enrollment_code requis"}), 400
    if len(enrollment_code) != 6 or not enrollment_code.isdigit():
        return jsonify({"code": "invalid_format", "message": "Le code doit contenir exactement 6 chiffres"}), 400

    now = datetime.now(timezone.utc)
    doc = get_identity_db().device_enrollments.find_one({
        "enrollment_code": enrollment_code,
        "enrolled": False,
    })

    if not doc:
        return jsonify({"code": "invalid_code", "message": "Code invalide ou deja utilise"}), 404

    expires_at = doc.get("expires_at")
    if isinstance(expires_at, datetime):
        exp = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
        if exp < now:
            return jsonify({"code": "expired_code", "message": "Code expire, redemandez-en un"}), 410

    device_id = doc["device_id"]

    device_doc = get_identity_db().users_devices.find_one({
        "device_id": device_id,
        "user_id_auth": g.user_id_auth,
    })
    if not device_doc:
        return jsonify({
            "code": "device_not_yours",
            "message": "Ce device n'est pas assigne a votre compte",
        }), 403

    try:
        get_identity_db().device_enrollments.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "enrolled": True,
                "enrolled_at": now,
                "enrolled_by": g.user_id_auth,
            }},
        )
    except PyMongoError as e:
        logger.warning("device_enrollments finalize failed: %s", e)
        return jsonify({"code": "enrollment_update_error", "message": str(e)}), 500

    logger.info("Device %s enrolled by patient %s", device_id, g.user_id_auth)
    return jsonify({
        "message": "Device enregistre avec succes",
        "device_id": device_id,
    }), 200


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    try:
        init_database()
        print(f"MongoDB initialized ({MONGODB_IDENTITY_DB}, {MONGODB_MEDICAL_DB})")
    except DatabaseError as e:
        print(f"Warning: Database initialization failed: {e.error.get('message')}")

    ml_module.init_ml()
    start_mqtt_subscriber()

    app.run(
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("FLASK_PORT", 5000)),
        debug=os.getenv("FLASK_DEBUG", "False").lower() == "true"
    )

