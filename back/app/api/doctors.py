"""HTTP routes — doctor_routes."""
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
    ALERT_DEFAULT_CONSECUTIVE_BREACHES,
)
from app.services.mailjet_service import is_mailjet_configured
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
    relationship_exists,
    parse_iso_datetime, normalize_user_id_auth, get_user_profile, _split_display_name,
    datetime_to_iso_utc, get_address_dict_from_profile, resolve_patient_display_name,
    is_auth_provider_id,
)
from app.services.invitation_service import (
    hash_secret_token, generate_invite_token, generate_cabinet_code,
    log_link_audit_event, create_doctor_patient_link, remove_doctor_patient_link,
    get_invite_document_or_404,
    send_invitation_email, send_doctor_patient_unlink_email,
    invite_emergency_contact_if_needed, log_caregiver_audit_event,
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

doctor_bp = Blueprint("doctor", __name__)

@doctor_bp.route("/api/me/push-subscribe", methods=["POST"])
@requires_auth
@requires_role("doctor", "medecin", "caregiver", "aidant", "Superuser")
def push_subscribe():
    """Register a push subscription for alert notifications (doctors/caregivers)."""
    from app.config import VAPID_PUBLIC_KEY
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


@doctor_bp.route("/api/doctor/invitations", methods=["POST"])
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
        patient_email = normalize_email(patient_email_raw)
        if not patient_email and patient_user_id_auth:
            profile = get_user_profile(patient_user_id_auth)
            patient_email = normalize_email(profile.get("email") or "")
        if not patient_email:
            return jsonify({"code": "invalid_payload", "message": "patient_email is required when send_email is true"}), 400
        if not is_mailjet_configured():
            return jsonify({"code": "email_config_error", "message": "Mailjet non configuré"}), 503

    invite_device_id = str(payload.get("device_id") or "").strip() or None
    if invite_device_id:
        existing_dev = get_identity_db().users_devices.find_one({"device_id": invite_device_id})
        if existing_dev:
            return jsonify({
                "code": "device_already_assigned",
                "message": "Ce device est déjà associé à un compte patient",
            }), 409

    invite_token = generate_invite_token()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=max(INVITE_TTL_HOURS, 1))
    invite_metadata: Dict[str, Any] = {"targeted": bool(patient_user_id_auth)}
    if invite_device_id:
        invite_metadata["device_id"] = invite_device_id
    invite_doc = {
        "token_hash": hash_secret_token(invite_token),
        "doctor_user_id_auth": g.user_id_auth, "patient_user_id_auth": patient_user_id_auth,
        "expires_at": expires_at, "used_at": None, "created_at": now,
        "created_by_user_id_auth": g.user_id_auth, "mode": "invite_link",
        "metadata": invite_metadata,
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

    email_queued = False
    if send_email and patient_email:
        email_queued = True

        def _send_invitation_email_background() -> None:
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
            try:
                send_invitation_email(
                    patient_email, invite_token, web_invite_url, expires_at,
                    doctor_display_name,
                    password_setup_url=password_setup_url,
                )
            except Exception as e:
                logger.exception("Envoi email invitation échoué: %s", e)

        # Réponse HTTP immédiate : Auth0 + SMTP peuvent dépasser le timeout Render (~30 s).
        threading.Thread(target=_send_invitation_email_background, daemon=True).start()

    return jsonify({
        "invite_token": invite_token, "expires_at": datetime_to_iso_utc(expires_at),
        "deep_link": f"vitalio://invite?token={invite_token}", "web_invite_url": web_invite_url,
        "qr_payload": web_invite_url, "mode": "invite_link",
        "target_patient_user_id_auth": patient_user_id_auth,
        "email_sent": False,
        "email_queued": email_queued,
        "pending_device_id": invite_device_id,
    }), 201


@doctor_bp.route("/api/doctor/cabinet-codes", methods=["POST"])
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


@doctor_bp.route("/api/doctor/patients", methods=["GET"])
@requires_auth
@requires_role("doctor")
def get_doctor_patients():
    patient_ids = get_assigned_patient_ids_for_doctor(g.user_id_auth)
    patients = build_assigned_patients_payload(patient_ids, doctor_queue_alert_badge=True)
    return jsonify({"doctor_id": g.user_id_auth, "count": len(patients), "patients": patients}), 200


@doctor_bp.route("/api/doctor/patients/<patient_id>", methods=["DELETE"])
@requires_auth
@requires_role("doctor", "medecin")
def remove_assigned_patient(patient_id: str):
    """Remove the authenticated doctor's link to a patient and notify the patient by email."""
    patient_id = resolve_patient_id(patient_id)
    doctor_id = g.user_id_auth
    if not relationship_exists("doctor", doctor_id, patient_id):
        return jsonify({
            "code": "patient_not_assigned",
            "message": "Ce patient n'est pas associé à votre compte médecin",
        }), 404

    patient_profile = get_user_profile(patient_id)
    patient_email = normalize_email(patient_profile.get("email") or "")
    patient_display_name = resolve_patient_display_name(patient_profile) or "Patient"
    doctor_profile = get_user_profile(doctor_id)
    doctor_display_name = doctor_profile.get("display_name") or doctor_profile.get("email") or "Votre médecin"

    try:
        removed = remove_doctor_patient_link(doctor_id, patient_id)
    except PyMongoError as e:
        raise DatabaseError({
            "code": "doctor_patient_unlink_error",
            "message": f"Failed to remove doctor-patient link: {str(e)}",
        }, 500)

    if not removed:
        return jsonify({
            "code": "patient_not_assigned",
            "message": "Ce patient n'est pas associé à votre compte médecin",
        }), 404

    log_link_audit_event(
        "doctor_patient_unlinked",
        doctor_id,
        doctor_id,
        patient_id,
        "doctor",
        {"endpoint": request.path},
    )
    log_audit_event(
        event_type="doctor_patient_unlinked",
        actor_user_id_auth=doctor_id,
        actor_role=audit_actor_role(),
        resource_type="association",
        resource_id=f"{doctor_id}:{patient_id}",
        action="delete",
        details={
            "doctor_user_id_auth": doctor_id,
            "patient_user_id_auth": patient_id,
            "endpoint": request.path,
        },
        request=request,
    )

    email_queued = False
    if patient_email:
        email_queued = True

        def _send_unlink_email_background() -> None:
            try:
                send_doctor_patient_unlink_email(
                    patient_email,
                    patient_display_name,
                    doctor_display_name,
                )
            except Exception as e:
                logger.exception("Envoi email retrait patient échoué: %s", e)

        threading.Thread(target=_send_unlink_email_background, daemon=True).start()

    return jsonify({
        "message": "Patient retiré de votre liste de suivi",
        "patient_id": patient_id,
        "email_queued": email_queued,
    }), 200


@doctor_bp.route("/api/caregiver/patients", methods=["GET"])
@requires_auth
@requires_role("caregiver", "aidant")
def get_caregiver_patients():
    patient_ids = get_assigned_patient_ids_for_caregiver(g.user_id_auth)
    patients = build_assigned_patients_payload(patient_ids)
    return jsonify({"caregiver_id": g.user_id_auth, "count": len(patients), "patients": patients}), 200


@doctor_bp.route("/api/caregiver/invitations/accept", methods=["POST"])
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

def resolve_patient_id(patient_id: str) -> str:
    """Resolve URL patient_id (db id or auth id) to user_id_auth. Raises 404 if not found."""
    resolved = resolve_patient_id_to_user_id_auth(patient_id)
    if not resolved:
        raise DatabaseError({"code": "patient_not_found", "message": "Patient not found"}, 404)
    return resolved


@doctor_bp.route("/api/patients/<patient_id>/measurements", methods=["GET"])
@requires_auth
def get_authorized_patient_measurements(patient_id: str):
    patient_id = resolve_patient_id(patient_id)
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


@doctor_bp.route("/api/doctor/patients/<patient_id>/measurements", methods=["GET"])
@requires_auth
@requires_role("doctor")
def get_doctor_patient_measurements(patient_id: str):
    patient_id = resolve_patient_id(patient_id)
    ensure_patient_access_or_403(patient_id)
    device_id = get_device_id(patient_id)
    if not device_id:
        raise DatabaseError({"code": "device_not_found", "message": "No device record found for patient"}, 404)
    days = request.args.get("days", default=30, type=int)
    limit = request.args.get("limit", default=500, type=int)
    measurements = query_patient_measurements(device_id=device_id, days=days, limit=limit)
    log_audit_event(
        event_type="patient_measurements_read",
        actor_user_id_auth=g.user_id_auth,
        actor_role=audit_actor_role(),
        resource_type="patient",
        resource_id=patient_id,
        action="read",
        details={"device_id": device_id, "count": len(measurements), "endpoint": request.path},
        request=request,
    )
    return jsonify({"patient_id": patient_id, "device_id": device_id, "days": days,
                    "count": len(measurements), "measurements": measurements}), 200


@doctor_bp.route("/api/doctor/patients/<patient_id>/trends", methods=["GET"])
@requires_auth
@requires_role("doctor")
def get_doctor_patient_trends(patient_id: str):
    patient_id = resolve_patient_id(patient_id)
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


@doctor_bp.route("/api/doctor/patients/<patient_id>/device", methods=["POST"])
@requires_auth
@requires_role("doctor", "superuser", "medecin")
def assign_device_to_patient(patient_id: str):
    """Associe un device_id à un patient - appelé par le médecin."""
    patient_id = resolve_patient_id(patient_id)
    ensure_patient_access_or_403(patient_id)

    payload = request.get_json(silent=True) or {}
    device_id = str(payload.get("device_id") or "").strip()

    if not device_id:
        return jsonify({"code": "missing_device_id", "message": "device_id requis"}), 400

    res = apply_patient_device_assignment(patient_id, device_id, g.user_id_auth)
    if not res[0]:
        return jsonify(res[1]), res[2]
    _, now = res
    return jsonify({
        "message": "Device assigné au patient",
        "patient_id": patient_id,
        "device_id": device_id,
        "assigned_at": datetime_to_iso_utc(now),
    }), 200


@doctor_bp.route("/api/doctor/patients/<patient_id>/device", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser", "medecin")
def get_patient_device(patient_id: str):
    """Retourne le device_id associé à un patient."""
    patient_id = resolve_patient_id(patient_id)
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


@doctor_bp.route("/api/doctor/patients/<patient_id>/alert-thresholds", methods=["GET", "PUT"])
@requires_auth
@requires_role("doctor")
def doctor_patient_alert_thresholds(patient_id: str):
    patient_id = resolve_patient_id(patient_id)
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


@doctor_bp.route("/api/doctor/patients/<patient_id>/feedback", methods=["POST"])
@requires_auth
@requires_role("doctor")
def create_doctor_feedback(patient_id: str):
    patient_id = resolve_patient_id(patient_id)
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


@doctor_bp.route("/api/patients/<patient_id>/feedback/latest", methods=["GET"])
@requires_auth
def get_latest_feedback_for_patient(patient_id: str):
    patient_id = resolve_patient_id(patient_id)
    ensure_patient_access_or_403(patient_id)
    limit = request.args.get("limit", default=5, type=int)
    feedbacks = list_latest_doctor_feedback(patient_user_id_auth=patient_id, limit=limit)
    return jsonify({"patient_id": patient_id, "count": len(feedbacks), "feedback": feedbacks}), 200


@doctor_bp.route("/api/patients/<patient_id>/doctor-info", methods=["GET"])
@requires_auth
@requires_role("patient", "doctor", "caregiver", "aidant", "admin", "superuser", "medecin")
def get_patient_doctor_info(patient_id: str):
    """Return the patient's doctor(s) info for display to patient or caregiver."""
    patient_id = resolve_patient_id(patient_id)
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


@doctor_bp.route("/api/patients/<patient_id>/profile", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser", "caregiver", "aidant", "admin", "medecin")
def get_patient_profile_for_doctor(patient_id: str):
    """Return the patient's profile for display to doctor (name, age, contact, medical history)."""
    patient_id = resolve_patient_id(patient_id)
    ensure_patient_access_or_403(patient_id)
    profile = get_user_profile(patient_id)
    display_name = resolve_patient_display_name(profile)
    if not display_name:
        return jsonify({
            "code": "patient_profile_incomplete",
            "message": "Profil patient incomplet (email requis)",
        }), 404
    first_name = str(profile.get("first_name") or "").strip()
    last_name = str(profile.get("last_name") or "").strip()
    if is_auth_provider_id(first_name):
        first_name = ""
    if is_auth_provider_id(last_name):
        last_name = ""
    if not first_name and not last_name and display_name and "@" not in display_name:
        fn, ln = _split_display_name(display_name)
        if not is_auth_provider_id(fn):
            first_name = fn
        if not is_auth_provider_id(ln):
            last_name = ln
    log_audit_event(
        event_type="patient_profile_read",
        actor_user_id_auth=g.user_id_auth,
        actor_role=audit_actor_role(),
        resource_type="patient",
        resource_id=patient_id,
        action="read",
        details={"endpoint": request.path},
        request=request,
    )
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


@doctor_bp.route("/api/patients/<patient_id>/caregiver-info", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser", "caregiver", "aidant", "admin", "medecin")
def get_patient_caregiver_info(patient_id: str):
    """Return the patient's caregiver(s) info for display to doctor or caregiver.
    Includes linked caregivers (caregiver_patients) and fallback to emergency_contact from profile."""
    patient_id = resolve_patient_id(patient_id)
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


@doctor_bp.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "healthcare-api"}), 200


# ============================================================================
# ROUTES - ML
# ============================================================================

