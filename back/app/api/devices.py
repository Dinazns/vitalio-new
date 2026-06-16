"""HTTP routes — device_routes."""
import json
import logging
import os
import re
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
    send_device_enrollment_code_email,
)
from app.services.mailjet_service import is_mailjet_configured
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

device_bp = Blueprint("device", __name__)


def _active_enrollment_for_device(device_id: str) -> Optional[Dict[str, Any]]:
    """Retourne l'enrollment en attente non expiré pour un device, ou None."""
    doc = get_identity_db().device_enrollments.find_one({
        "device_id": device_id,
        "enrolled": False,
    })
    if not doc:
        return None
    expires_at = doc.get("expires_at")
    if isinstance(expires_at, datetime):
        exp = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
        if exp < datetime.now(timezone.utc):
            return None
    return doc


def _send_enrollment_code_email_for_patient(
    patient_user_id_auth: str,
    device_id: str,
    enrollment_code: str,
    expires_at: datetime,
) -> None:
    if not is_mailjet_configured():
        raise ValueError("Mailjet non configuré: envoi e-mail impossible")
    profile = get_user_profile(patient_user_id_auth) or {}
    patient_email = normalize_email(profile.get("email"))
    if not patient_email:
        raise ValueError("Aucune adresse e-mail associée à votre compte")
    display_name = (
        profile.get("display_name")
        or profile.get("first_name")
        or patient_email
    )
    send_device_enrollment_code_email(
        patient_email,
        display_name,
        device_id,
        enrollment_code,
        expires_at,
    )


@device_bp.route("/api/device/measurements", methods=["POST"])
def submit_device_measurement():
    payload = request.get_json(silent=True) or {}
    device_id = str(payload.get("device_id") or "").strip()
    if not device_id:
        return jsonify({"code": "missing_device_id", "message": "device_id requis"}), 400

    # Vérifier dans users_devices - c'est là que sont les vrais devices
    device_doc = get_identity_db().users_devices.find_one({"device_id": device_id})
    if not device_doc:
        return jsonify({"code": "unknown_device", "message": "device_id inconnu"}), 403
    if (device_doc.get("status") or "active") == "suspended":
        return jsonify({"code": "device_suspended", "message": "Dispositif suspendu par un administrateur"}), 403

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


@device_bp.route("/api/device/enrollment", methods=["POST"])
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


@device_bp.route("/api/device/enrollment/status", methods=["GET"])
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


@device_bp.route("/api/patient/enrollment/send-code-email", methods=["POST"])
@requires_auth
@requires_role("patient")
def patient_request_enrollment_code_email():
    """Patient demande l'envoi du code à 6 chiffres par e-mail (boîtier déjà connecté)."""
    device_doc = get_identity_db().users_devices.find_one({"user_id_auth": g.user_id_auth})
    if not device_doc or not device_doc.get("device_id"):
        return jsonify({
            "code": "no_device_assigned",
            "message": "Aucun boîtier assigné à votre compte",
        }), 404

    device_id = str(device_doc["device_id"])
    enrollment = _active_enrollment_for_device(device_id)
    if not enrollment:
        return jsonify({
            "code": "no_active_code",
            "message": "Aucun code actif. Vérifiez que le boîtier est connecté au Wi-Fi.",
        }), 404

    expires_at = enrollment.get("expires_at")
    if not isinstance(expires_at, datetime):
        return jsonify({"code": "invalid_enrollment", "message": "Enrollment invalide"}), 500

    try:
        _send_enrollment_code_email_for_patient(
            g.user_id_auth,
            device_id,
            str(enrollment.get("enrollment_code") or ""),
            expires_at,
        )
    except ValueError as e:
        return jsonify({"code": "email_send_failed", "message": str(e)}), 400
    except Exception as e:
        logger.exception("Envoi email code enrollment demandé par patient échoué: %s", e)
        return jsonify({"code": "email_send_failed", "message": "Envoi e-mail impossible"}), 500

    logger.info("Code enrollment envoyé par e-mail (demande patient, device %s)", device_id)
    return jsonify({
        "message": "Code envoyé par e-mail",
        "device_id": device_id,
        "expires_at": datetime_to_iso_utc(expires_at),
    }), 200


@device_bp.route("/api/patient/enroll-device", methods=["POST"])
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

