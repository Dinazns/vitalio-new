"""HTTP routes — admin_routes."""
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
from app.services.patient_data_portability import build_patient_export, erase_patient_all_data, erase_user_all_data
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

admin_bp = Blueprint("admin", __name__)

@admin_bp.route("/api/admin/associations/doctor-patient", methods=["POST"])
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
    log_audit_event(
        event_type="admin_association_created",
        actor_user_id_auth=g.user_id_auth,
        actor_role=audit_actor_role(),
        resource_type="association",
        resource_id=f"{doctor_user_id_auth}:{patient_user_id_auth}",
        action="create",
        details={
            "doctor_user_id_auth": doctor_user_id_auth,
            "patient_user_id_auth": patient_user_id_auth,
            "endpoint": "/api/admin/associations/doctor-patient",
        },
        request=request,
    )
    return jsonify({"message": "Doctor-patient association saved", "doctor_user_id_auth": doctor_user_id_auth,
                    "patient_user_id_auth": patient_user_id_auth}), 201


@admin_bp.route("/api/admin/associations/caregiver-patient", methods=["POST"])
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
    log_audit_event(
        event_type="admin_caregiver_association_created",
        actor_user_id_auth=g.user_id_auth,
        actor_role=audit_actor_role(),
        resource_type="association",
        resource_id=f"{caregiver_user_id_auth}:{patient_user_id_auth}",
        action="create",
        details={
            "caregiver_user_id_auth": caregiver_user_id_auth,
            "patient_user_id_auth": patient_user_id_auth,
            "endpoint": "/api/admin/associations/caregiver-patient",
        },
        request=request,
    )
    return jsonify({"message": "Caregiver-patient association saved", "caregiver_user_id_auth": caregiver_user_id_auth,
                    "patient_user_id_auth": patient_user_id_auth}), 201


@admin_bp.route("/api/admin/devices", methods=["GET"])
@requires_auth
@requires_role("admin")
def admin_list_devices():
    """Paginated registry of patient devices with status and relationships."""
    identity_db = get_identity_db()
    q = (request.args.get("q") or "").strip()
    status_filter = (request.args.get("status") or "").strip().lower()
    page = max(request.args.get("page", default=1, type=int) or 1, 1)
    page_size = min(max(request.args.get("page_size", default=50, type=int) or 50, 1), 200)

    conditions: List[Dict[str, Any]] = []
    if status_filter == "suspended":
        conditions.append({"status": "suspended"})
    elif status_filter == "active":
        conditions.append({"$or": [{"status": "active"}, {"status": {"$exists": False}}]})

    try:
        if q:
            regex = {"$regex": re.escape(q), "$options": "i"}
            matched_patient_ids = [
                u.get("user_id_auth")
                for u in identity_db.users.find(
                    {"$or": [
                        {"email": regex}, {"display_name": regex},
                        {"first_name": regex}, {"last_name": regex},
                        {"user_id_auth": regex},
                    ]},
                    projection={"user_id_auth": 1, "_id": 0},
                ) if u.get("user_id_auth")
            ]
            search_or: List[Dict[str, Any]] = [{"device_id": regex}]
            if matched_patient_ids:
                search_or.append({"user_id_auth": {"$in": matched_patient_ids}})
            conditions.append({"$or": search_or})

        mongo_filter = {"$and": conditions} if conditions else {}
        total = identity_db.users_devices.count_documents(mongo_filter)
        rows = list(
            identity_db.users_devices
            .find(mongo_filter, {"_id": 0})
            .sort("device_id", 1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )

        patient_ids = [r.get("user_id_auth") for r in rows if r.get("user_id_auth")]
        device_ids = [r.get("device_id") for r in rows if r.get("device_id")]

        profiles: Dict[str, Any] = {}
        doctors_by_patient: Dict[str, List[str]] = {}
        doctor_ids: set = set()
        if patient_ids:
            for u in identity_db.users.find(
                {"user_id_auth": {"$in": patient_ids}},
                {"_id": 0, "user_id_auth": 1, "display_name": 1, "email": 1, "first_name": 1, "last_name": 1},
            ):
                profiles[u["user_id_auth"]] = u
            for link in identity_db.doctor_patients.find(
                {"patient_user_id_auth": {"$in": patient_ids}},
                {"_id": 0, "doctor_user_id_auth": 1, "patient_user_id_auth": 1},
            ):
                doctors_by_patient.setdefault(link["patient_user_id_auth"], []).append(link["doctor_user_id_auth"])
                doctor_ids.add(link["doctor_user_id_auth"])

        doctor_profiles: Dict[str, Any] = {}
        if doctor_ids:
            for u in identity_db.users.find(
                {"user_id_auth": {"$in": list(doctor_ids)}},
                {"_id": 0, "user_id_auth": 1, "display_name": 1, "email": 1, "first_name": 1, "last_name": 1},
            ):
                doctor_profiles[u["user_id_auth"]] = u

        enrolled_ids: set = set()
        if device_ids:
            for e in identity_db.device_enrollments.find(
                {"device_id": {"$in": device_ids}, "enrolled": True},
                {"_id": 0, "device_id": 1},
            ):
                enrolled_ids.add(e["device_id"])
    except PyMongoError as e:
        raise DatabaseError({"code": "admin_devices_query_error", "message": str(e)}, 500)

    devices = []
    for r in rows:
        pid = r.get("user_id_auth")
        prof = profiles.get(pid, {})
        devices.append({
            "device_id": r.get("device_id"),
            "status": r.get("status") or "active",
            "status_updated_at": datetime_to_iso_utc(r.get("status_updated_at")) if r.get("status_updated_at") else None,
            "status_updated_by": r.get("status_updated_by"),
            "suspension_reason": r.get("suspension_reason"),
            "assigned_at": datetime_to_iso_utc(r.get("assigned_at")) if r.get("assigned_at") else None,
            "assigned_by": r.get("assigned_by"),
            "enrolled": r.get("device_id") in enrolled_ids,
            "patient": admin_user_summary(prof, pid),
            "doctors": [
                admin_user_summary(doctor_profiles.get(d, {}), d)
                for d in doctors_by_patient.get(pid, [])
            ],
        })

    return jsonify({"count": total, "page": page, "page_size": page_size, "devices": devices}), 200


@admin_bp.route("/api/admin/devices/<device_id>/status", methods=["PATCH"])
@requires_auth
@requires_role("admin")
def admin_update_device_status(device_id):
    """Activate or suspend a device. Suspension blocks measurement ingestion."""
    device_id = str(device_id or "").strip()
    if not device_id:
        return jsonify({"code": "missing_device_id", "message": "device_id requis"}), 400
    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status") or "").strip().lower()
    if status not in ("active", "suspended"):
        return jsonify({"code": "invalid_status", "message": "status doit être 'active' ou 'suspended'"}), 400
    reason = str(payload.get("reason") or "").strip()

    identity_db = get_identity_db()
    device_doc = identity_db.users_devices.find_one({"device_id": device_id})
    if not device_doc:
        return jsonify({"code": "unknown_device", "message": "device_id inconnu"}), 404

    current = device_doc.get("status") or "active"
    now = datetime.now(timezone.utc)
    set_ops: Dict[str, Any] = {
        "$set": {"status": status, "status_updated_at": now, "status_updated_by": g.user_id_auth}
    }
    if status == "suspended":
        set_ops["$set"]["suspension_reason"] = reason or None
    else:
        set_ops["$unset"] = {"suspension_reason": ""}

    try:
        identity_db.users_devices.update_one({"device_id": device_id}, set_ops)
    except PyMongoError as e:
        raise DatabaseError({"code": "device_status_update_error", "message": str(e)}, 500)

    # Audit only real transitions to keep the journal meaningful (idempotent calls are silent).
    if current != status:
        try:
            identity_db.audit_links.insert_one({
                "event_type": "device_status_changed",
                "actor_user_id_auth": g.user_id_auth,
                "patient_user_id_auth": device_doc.get("user_id_auth"),
                "device_id": device_id,
                "from_status": current,
                "to_status": status,
                "reason": reason or None,
                "created_at": now,
            })
        except PyMongoError as e:
            logger.warning("Failed to write device status audit for %s: %s", device_id, e)
        log_audit_event(
            event_type="device_status_changed",
            actor_user_id_auth=g.user_id_auth,
            actor_role=audit_actor_role(),
            resource_type="device",
            resource_id=device_id,
            action="update",
            details={
                "from_status": current,
                "to_status": status,
                "patient_user_id_auth": device_doc.get("user_id_auth"),
                "reason": reason or None,
                "endpoint": f"/api/admin/devices/{device_id}/status",
            },
            request=request,
        )

    return jsonify({
        "message": "Device status updated",
        "device_id": device_id,
        "status": status,
        "suspension_reason": (reason or None) if status == "suspended" else None,
        "status_updated_at": datetime_to_iso_utc(now),
    }), 200


@admin_bp.route("/api/admin/associations/doctor-patients", methods=["GET"])
@requires_auth
@requires_role("admin")
def admin_list_doctor_patient_links():
    """Paginated list of doctor-patient links enriched with user info."""
    identity_db = get_identity_db()
    page = max(request.args.get("page", default=1, type=int) or 1, 1)
    page_size = min(max(request.args.get("page_size", default=100, type=int) or 100, 1), 500)
    try:
        total = identity_db.doctor_patients.count_documents({})
        links = list(
            identity_db.doctor_patients
            .find({}, {"_id": 0})
            .sort("created_at", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        user_ids: set = set()
        for link in links:
            for key in ("doctor_user_id_auth", "patient_user_id_auth"):
                if link.get(key):
                    user_ids.add(link[key])
        profiles: Dict[str, Any] = {}
        if user_ids:
            for u in identity_db.users.find(
                {"user_id_auth": {"$in": list(user_ids)}},
                {"_id": 0, "user_id_auth": 1, "display_name": 1, "email": 1, "first_name": 1, "last_name": 1},
            ):
                profiles[u["user_id_auth"]] = u
    except PyMongoError as e:
        raise DatabaseError({"code": "doctor_patient_links_query_error", "message": str(e)}, 500)

    items = [
        {
            "doctor": admin_user_summary(profiles.get(link.get("doctor_user_id_auth"), {}), link.get("doctor_user_id_auth")),
            "patient": admin_user_summary(profiles.get(link.get("patient_user_id_auth"), {}), link.get("patient_user_id_auth")),
            "linked_by": link.get("linked_by"),
            "created_at": datetime_to_iso_utc(link.get("created_at")) if link.get("created_at") else None,
        }
        for link in links
    ]
    return jsonify({"count": total, "page": page, "page_size": page_size, "links": items}), 200


@admin_bp.route("/api/admin/audit-log", methods=["GET"])
@requires_auth
@requires_role("admin")
def admin_list_audit_log():
    """Paginated global security audit trail (append-only audit_log collection)."""
    from_raw = request.args.get("from")
    to_raw = request.args.get("to")
    event_type = (request.args.get("event_type") or "").strip() or None
    actor_user_id_auth = (request.args.get("actor_user_id_auth") or "").strip() or None
    resource_id = (request.args.get("resource_id") or "").strip() or None
    page = max(request.args.get("page", default=1, type=int) or 1, 1)
    page_size = min(max(request.args.get("page_size", default=50, type=int) or 50, 1), 100)

    from_dt = to_dt = None
    try:
        if from_raw:
            from_dt = parse_iso_datetime(from_raw)
        if to_raw:
            to_dt = parse_iso_datetime(to_raw)
        if from_dt and from_dt.tzinfo is None:
            from_dt = from_dt.replace(tzinfo=timezone.utc)
        if to_dt and to_dt.tzinfo is None:
            to_dt = to_dt.replace(tzinfo=timezone.utc)
        if from_dt and to_dt and from_dt > to_dt:
            return jsonify({"code": "invalid_payload", "message": "'from' must be <= 'to'"}), 400
    except ValueError as e:
        return jsonify({"code": "invalid_payload", "message": str(e)}), 400

    total, events = query_audit_log(
        from_dt=from_dt,
        to_dt=to_dt,
        event_type=event_type,
        actor_user_id_auth=actor_user_id_auth,
        resource_id=resource_id,
        page=page,
        page_size=page_size,
    )
    return jsonify({
        "total": total,
        "page": page,
        "page_size": page_size,
        "events": events,
    }), 200


def _admin_user_role_filter(role_filter: str) -> Optional[Dict[str, Any]]:
    role_filter = (role_filter or "").strip().lower()
    if not role_filter:
        return None
    if role_filter == "doctor":
        return {"role": {"$in": ["doctor", "medecin", "superuser"]}}
    if role_filter == "caregiver":
        return {"role": {"$in": ["caregiver", "aidant"]}}
    return {"role": role_filter}


@admin_bp.route("/api/admin/users", methods=["GET"])
@requires_auth
@requires_role("admin")
def admin_list_users():
    """Paginated registry of VitalIO users."""
    identity_db = get_identity_db()
    q = (request.args.get("q") or "").strip()
    role_filter = (request.args.get("role") or "").strip().lower()
    page = max(request.args.get("page", default=1, type=int) or 1, 1)
    page_size = min(max(request.args.get("page_size", default=50, type=int) or 50, 1), 200)

    conditions: List[Dict[str, Any]] = []
    role_cond = _admin_user_role_filter(role_filter)
    if role_cond:
        conditions.append(role_cond)
    if q:
        regex = {"$regex": re.escape(q), "$options": "i"}
        conditions.append({"$or": [
            {"email": regex},
            {"display_name": regex},
            {"first_name": regex},
            {"last_name": regex},
            {"user_id_auth": regex},
        ]})

    mongo_filter = {"$and": conditions} if conditions else {}
    projection = {
        "_id": 0,
        "user_id_auth": 1,
        "role": 1,
        "display_name": 1,
        "email": 1,
        "first_name": 1,
        "last_name": 1,
        "created_at": 1,
    }

    try:
        total = identity_db.users.count_documents(mongo_filter)
        rows = list(
            identity_db.users
            .find(mongo_filter, projection)
            .sort("created_at", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
    except PyMongoError as e:
        raise DatabaseError({"code": "admin_users_query_error", "message": str(e)}, 500)

    users = []
    for row in rows:
        uid = row.get("user_id_auth")
        summary = admin_user_summary(row, uid) or {"user_id_auth": uid}
        summary["role"] = row.get("role")
        summary["created_at"] = datetime_to_iso_utc(row.get("created_at")) if row.get("created_at") else None
        users.append(summary)

    return jsonify({"count": total, "page": page, "page_size": page_size, "users": users}), 200


@admin_bp.route("/api/admin/users/<path:user_id_auth>", methods=["DELETE"])
@requires_auth
@requires_role("admin")
def admin_delete_user(user_id_auth: str):
    """Delete a VitalIO user and role-specific linked data (not Auth0)."""
    user_id_auth = str(user_id_auth or "").strip()
    if not user_id_auth:
        return jsonify({"code": "missing_user_id", "message": "user_id_auth requis"}), 400

    body = request.get_json(silent=True) or {}
    if body.get("confirm") != "SUPPRIMER_UTILISATEUR":
        return jsonify({
            "code": "confirmation_required",
            "message": 'Confirmation requise : envoyer {"confirm":"SUPPRIMER_UTILISATEUR"} dans le corps JSON.',
        }), 400

    if user_id_auth == g.user_id_auth:
        return jsonify({"code": "self_delete_forbidden", "message": "Vous ne pouvez pas supprimer votre propre compte admin."}), 403

    try:
        target = get_identity_db().users.find_one({"user_id_auth": user_id_auth}, {"_id": 0, "role": 1, "email": 1})
    except PyMongoError as e:
        raise DatabaseError({"code": "user_lookup_error", "message": str(e)}, 500)

    if not target:
        return jsonify({"code": "user_not_found", "message": "Utilisateur introuvable"}), 404

    target_role = str(target.get("role") or "").strip().lower()
    if target_role == "admin":
        return jsonify({"code": "admin_delete_forbidden", "message": "La suppression d'un compte administrateur n'est pas autorisée."}), 403

    log_audit_event(
        event_type="admin_user_deleted",
        actor_user_id_auth=g.user_id_auth,
        actor_role=audit_actor_role(),
        resource_type="user",
        resource_id=user_id_auth,
        action="delete",
        details={
            "deleted_role": target.get("role"),
            "deleted_email": target.get("email"),
            "endpoint": f"/api/admin/users/{user_id_auth}",
        },
        request=request,
    )

    try:
        counts = erase_user_all_data(user_id_auth)
    except DatabaseError:
        raise

    return jsonify({
        "message": "Utilisateur supprimé de VitalIO.",
        "user_id_auth": user_id_auth,
        "deleted": counts,
    }), 200

