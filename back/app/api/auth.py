"""HTTP routes — auth_routes."""
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

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/api/push/vapid-public-key", methods=["GET"])
def get_vapid_public_key():
    """Return VAPID public key for push subscription (public, no auth required)."""
    from app.config import VAPID_PUBLIC_KEY
    return jsonify({"vapid_public_key": VAPID_PUBLIC_KEY or ""}), 200


@auth_bp.route("/api/me/role", methods=["GET"])
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


@auth_bp.route("/api/terms/current-version", methods=["GET"])
def get_current_terms_version():
    return jsonify({"current_version": CURRENT_TERMS_VERSION}), 200


@auth_bp.route("/api/me/terms", methods=["GET"])
@requires_auth
@requires_role("patient", "doctor", "caregiver", "admin", "superuser", "medecin", "aidant")
def get_my_terms_status():
    return jsonify(get_terms_status(g.user_id_auth)), 200


@auth_bp.route("/api/me/terms", methods=["POST"])
@requires_auth
@requires_role("patient", "doctor", "caregiver", "admin", "superuser", "medecin", "aidant")
def post_my_terms_acceptance():
    return jsonify(accept_terms(g.user_id_auth)), 200


@auth_bp.route("/api/me/profile", methods=["GET"])
@requires_auth
@requires_role("patient")
def get_my_profile():
    user_id_auth = g.user_id_auth
    profile = get_user_profile(user_id_auth)
    payload = getattr(g, "jwt_payload", {}) or {}
    profile_email = profile.get("email") or payload.get("email") or ""
    raw_display_name = profile.get("display_name") or ""
    safe_display_name = (
        _sanitize_person_name(raw_display_name, profile_email)
        or _sanitize_person_name(payload.get("name"), profile_email)
        or ""
    )
    profile_data = {
        "display_name": safe_display_name,
        "email": profile_email,
        "first_name": profile.get("first_name") or _sanitize_person_name(payload.get("given_name"), profile_email) or "",
        "last_name": profile.get("last_name") or _sanitize_person_name(payload.get("family_name"), profile_email) or "",
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
        safe_name = safe_display_name
        if safe_name:
            profile_data["first_name"], profile_data["last_name"] = _split_display_name(safe_name)
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


@auth_bp.route("/api/me/profile", methods=["PATCH"])
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

    profile = get_user_profile(g.user_id_auth) or {}
    payload_jwt = getattr(g, "jwt_payload", {}) or {}
    known_email = (
        updates.get("email")
        or profile.get("email")
        or payload_jwt.get("email")
        or payload_jwt.get("https://vitalio.app/email")
    )
    for name_field in ("first_name", "last_name", "display_name"):
        if name_field not in updates:
            continue
        sanitized = _sanitize_person_name(updates[name_field], known_email)
        updates[name_field] = sanitized if sanitized else None

    set_doc = encrypt_profile_fields({**updates, "updated_at": datetime.now(timezone.utc)})
    ns = "https://vitalio.app/"
    jwt_role = (payload_jwt.get(f"{ns}role") or payload_jwt.get("role") or "").strip().lower()
    role_map = {"doctor": "medecin", "medecin": "medecin", "superuser": "medecin", "patient": "patient",
                "caregiver": "aidant", "aidant": "aidant", "admin": "admin"}
    default_role = role_map.get(jwt_role, jwt_role or "patient")
    set_on_insert = {
        "user_id_auth": g.user_id_auth, "role": default_role, "created_at": datetime.now(timezone.utc),
    }

    # À la première connexion (ou mise à jour profil), display_name = first_name + last_name
    first_name_val = str(updates.get("first_name") or profile.get("first_name") or "").strip()
    last_name_val = str(updates.get("last_name") or profile.get("last_name") or "").strip()
    if first_name_val or last_name_val:
        computed_display = f"{first_name_val} {last_name_val}".strip()
        if computed_display:
            set_doc["display_name"] = computed_display[:128]
    if "display_name" not in set_doc:
        set_on_insert["display_name"] = updates.get("display_name") or g.user_id_auth

    try:
        get_identity_db().users.update_one(
            {"user_id_auth": g.user_id_auth},
            {"$set": set_doc, "$setOnInsert": set_on_insert},
            upsert=True,
        )
        if get_user_role(g.user_id_auth) == "patient":
            ensure_patient_pseudo_id(g.user_id_auth)
    except PyMongoError as e:
        raise DatabaseError({"code": "update_error", "message": str(e)}, 500)

    if new_emergency_email:
        patient_profile = get_user_profile(g.user_id_auth)
        patient_name = patient_profile.get("display_name") or patient_profile.get("email") or "Un patient VitalIO"
        invite_emergency_contact_if_needed(g.user_id_auth, new_emergency_email, patient_name)

    return jsonify({"message": "Profile updated"}), 200


@auth_bp.route("/api/me/onboarding", methods=["POST"])
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
    set_doc = encrypt_profile_fields({
        "first_name": first_name, "last_name": last_name, "display_name": display_name,
        "age": age, "sex": sex_val, "phone": phone, "birthdate": birthdate,
        "emergency_contact": emergency,
        "medical_history": medical_history, "onboarding_completed": True,
        "role": "patient",
        "email": email,
        "updated_at": datetime.now(timezone.utc),
    })
    set_on_insert = {
        "user_id_auth": g.user_id_auth, "created_at": datetime.now(timezone.utc),
    }

    try:
        get_identity_db().users.update_one(
            {"user_id_auth": g.user_id_auth},
            {"$set": set_doc, "$setOnInsert": set_on_insert},
            upsert=True,
        )
        ensure_patient_pseudo_id(g.user_id_auth)
    except PyMongoError as e:
        raise DatabaseError({"code": "update_error", "message": str(e)}, 500)

    patient_profile = get_user_profile(g.user_id_auth)
    patient_name = patient_profile.get("display_name") or patient_profile.get("email") or "Un patient VitalIO"
    invite_emergency_contact_if_needed(g.user_id_auth, ec_email, patient_name)

    return jsonify({"message": "Onboarding médical complété", "onboarding_completed": True}), 200


