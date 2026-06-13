"""HTTP routes — device_routes."""
import io
import json
import logging
import os
import qrcode
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone, date
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, request, jsonify, g, Response, send_file
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
    send_invitation_email, send_device_confirmation_email,
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

device_bp = Blueprint("device", __name__)

# Portail captif ESP32 (QR collé sur le boîtier)
DEVICE_WIFI_PORTAL_URL = "http://192.168.4.1/"


def _qr_png_response(payload: str, download_name: str = "qrcode.png"):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img_io = io.BytesIO()
    img.save(img_io, "PNG")
    img_io.seek(0)
    return send_file(img_io, mimetype="image/png", as_attachment=False, download_name=download_name)

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
def register_device_enrollment_pending():
    """ESP32 connecté : signale que le boîtier attend la confirmation patient (sans code 6 chiffres)."""
    payload = request.get_json(silent=True) or {}
    device_id = str(payload.get("device_id") or "").strip()

    if not device_id:
        return jsonify({"code": "missing_device_id", "message": "device_id requis"}), 400

    device_doc = get_identity_db().users_devices.find_one({"device_id": device_id})
    if not device_doc:
        return jsonify({"code": "unknown_device", "message": "Device inconnu"}), 403

    now = datetime.now(timezone.utc)
    try:
        get_identity_db().device_enrollments.update_one(
            {"device_id": device_id},
            {
                "$set": {"device_id": device_id, "enrolled": False, "updated_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
    except PyMongoError as e:
        logger.warning("device_enrollments upsert failed: %s", e)
        return jsonify({"code": "enrollment_store_error", "message": str(e)}), 500

    logger.info("Device %s en attente de confirmation email", device_id)
    return jsonify({"message": "Device en attente de confirmation", "device_id": device_id}), 201


@device_bp.route("/api/device/enrollment/status", methods=["GET"])
def check_enrollment_status():
    """ESP32 vérifie si le patient a confirmé l'enrollment via email."""
    device_id = request.args.get("device_id", "").strip()
    if not device_id:
        return jsonify({"code": "missing_device_id"}), 400

    doc = get_identity_db().device_enrollments.find_one({"device_id": device_id})
    if not doc:
        return jsonify({"enrolled": False}), 200

    if doc.get("enrolled"):
        return jsonify({"enrolled": True}), 200

    expires_at = doc.get("confirmation_expires_at")
    if isinstance(expires_at, datetime):
        exp = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
        if exp < datetime.now(timezone.utc):
            return jsonify({"enrolled": False, "reason": "confirmation_expired"}), 200

    return jsonify({"enrolled": False}), 200


@device_bp.route("/api/device/validate", methods=["POST"])
@requires_auth
@requires_role("patient")
def validate_device_enrollment():
    """Patient confirme son boîtier (device_id) — envoi email de confirmation 24h."""
    payload = request.get_json(silent=True) or {}
    device_id = str(payload.get("device_id") or "").strip()

    if not device_id:
        return jsonify({"code": "missing_device_id", "message": "device_id requis"}), 400

    device_doc = get_identity_db().users_devices.find_one({"device_id": device_id})
    if not device_doc:
        return jsonify({"code": "device_not_found", "message": "Device introuvable"}), 404

    if device_doc.get("user_id_auth") != g.user_id_auth:
        return jsonify({"code": "device_not_yours", "message": "Ce device n'est pas assigne a votre compte"}), 403

    enrollment_doc = get_identity_db().device_enrollments.find_one({"device_id": device_id})
    if enrollment_doc and enrollment_doc.get("enrolled"):
        return jsonify({"code": "already_enrolled", "message": "Device deja enregistre"}), 400

    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_secret_token(raw_token)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=24)

    try:
        get_identity_db().device_enrollments.update_one(
            {"device_id": device_id},
            {"$set": {
                "device_id": device_id,
                "user_id_auth": g.user_id_auth,
                "enrolled": False,
                "confirmation_token": token_hash,
                "confirmation_expires_at": expires_at,
                "created_at": now,
            }},
            upsert=True,
        )
    except PyMongoError as e:
        logger.warning("device_enrollments upsert failed: %s", e)
        return jsonify({"code": "enrollment_store_error", "message": str(e)}), 500

    try:
        user_profile = get_user_profile(g.user_id_auth)
        patient_email = (user_profile.get("email") or "").strip()
        first = (user_profile.get("first_name") or "").strip()
        last = (user_profile.get("last_name") or "").strip()
        patient_name = f"{first} {last}".strip() or (user_profile.get("display_name") or "Patient")
    except Exception as e:
        logger.warning("Failed to get patient profile: %s", e)
        return jsonify({"code": "profile_error", "message": "Profil patient introuvable"}), 500

    if not patient_email:
        return jsonify({"code": "missing_email", "message": "Aucune adresse email sur votre compte"}), 400

    confirmation_url = f"{FRONTEND_URL}/device/confirm?token={raw_token}&device_id={device_id}"

    try:
        send_device_confirmation_email(
            patient_email=patient_email,
            patient_display_name=patient_name,
            confirmation_url=confirmation_url,
            device_id=device_id,
            expires_at=expires_at,
        )
    except ValueError as e:
        logger.warning("Failed to send confirmation email: %s", e)
        return jsonify({"code": "email_error", "message": str(e)}), 500

    logger.info("Confirmation email sent for device %s", device_id)
    return jsonify({
        "message": "Email de confirmation envoyé",
        "device_id": device_id,
        "expires_in_hours": 24,
    }), 201


@device_bp.route("/api/device/confirm", methods=["POST"])
def confirm_device_enrollment():
    """Confirme l'enrollment via le lien reçu par email (sans authentification)."""
    payload = request.get_json(silent=True) or {}
    token = str(payload.get("token") or "").strip()
    device_id = str(payload.get("device_id") or "").strip()

    if not token or not device_id:
        return jsonify({"code": "missing_params", "message": "token et device_id requis"}), 400

    now = datetime.now(timezone.utc)
    token_hash = hash_secret_token(token)
    enrollment_doc = get_identity_db().device_enrollments.find_one({
        "device_id": device_id,
        "confirmation_token": token_hash,
    })

    if not enrollment_doc:
        return jsonify({"code": "invalid_token", "message": "Token invalide"}), 404

    expires_at = enrollment_doc.get("confirmation_expires_at")
    if isinstance(expires_at, datetime):
        exp = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
        if exp < now:
            return jsonify({"code": "expired_token", "message": "Token expire"}), 410

    try:
        get_identity_db().device_enrollments.update_one(
            {"_id": enrollment_doc["_id"]},
            {"$set": {
                "enrolled": True,
                "enrolled_at": now,
                "enrolled_by": enrollment_doc.get("user_id_auth"),
                "confirmation_token": None,
            }},
        )
    except PyMongoError as e:
        logger.warning("device_enrollments finalize failed: %s", e)
        return jsonify({"code": "enrollment_error", "message": str(e)}), 500

    logger.info("Device %s enrolled via email confirmation", device_id)
    return jsonify({"message": "Device enregistre avec succes", "device_id": device_id}), 200


@device_bp.route("/api/device/qrcode", methods=["GET"])
@requires_auth
@requires_role("patient")
def get_device_qrcode():
    """
    Génère un QR code PNG.
    - type=wifi (défaut) : portail ESP32 http://192.168.4.1/ (config Wi-Fi)
    - type=device : QR avec device_id (étiquette boîtier), device_id requis
    """
    qr_type = (request.args.get("type") or "wifi").strip().lower()
    device_id = request.args.get("device_id", "").strip()

    if qr_type == "wifi":
        return _qr_png_response(DEVICE_WIFI_PORTAL_URL, "vitalio-wifi-portal.png")

    if qr_type == "device":
        if not device_id:
            return jsonify({"code": "missing_device_id", "message": "device_id requis pour type=device"}), 400
        device_doc = get_identity_db().users_devices.find_one({
            "device_id": device_id,
            "user_id_auth": g.user_id_auth,
        })
        if not device_doc:
            return jsonify({"code": "device_not_found", "message": "Device non trouve"}), 404
        return _qr_png_response(device_id, f"{device_id}-qr.png")

    return jsonify({"code": "invalid_type", "message": "type doit etre wifi ou device"}), 400


# ============================================================================
# MAIN
# ============================================================================

