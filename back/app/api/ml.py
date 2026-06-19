"""HTTP routes - ml_routes."""
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
    datetime_to_iso_utc, get_address_dict_from_profile, resolve_patient_display_name,
    is_auth_provider_id,
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
    get_patient_measurement_date_span, suggest_analysis_days_for_measurement_span,
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
    build_lay_caregiver_weekly_summary,
    build_clinical_weekly_narrative,
)
from app.api.helpers.patient_clinical_context import (
    load_patient_clinical_context,
    enrich_narrative_summary,
)
from app.api.helpers.doctor_helpers import (
    normalize_email,
    resolve_patient_id,
    apply_patient_device_assignment,
    admin_user_summary,
    build_combined_anomaly_summary_for_analysis,
)

logger = logging.getLogger(__name__)

ml_bp = Blueprint("ml", __name__)

@ml_bp.route("/api/ml/info", methods=["GET"])
def ml_model_info():
    return jsonify(ml_module.get_model_info()), 200


@ml_bp.route("/api/admin/ml/model-info", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser")
def admin_ml_model_info():
    """Alias explicite : même charge utile que GET /api/ml/info (+ auth admin)."""
    return jsonify(ml_module.get_model_info()), 200


@ml_bp.route("/api/doctor/ml-anomalies", methods=["GET"])
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
    if severity in ("critical", "warning", "threshold"):
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
            level = doc.get("anomaly_level")
            urgency = str(doc.get("urgency") or "routine")
            from app.services.severity_level import highest_severity, severity_for_ml_anomaly_level, SEVERITY_URGENCY
            doc["severity_level"] = severity_for_ml_anomaly_level(level)
            if urgency == "immediate":
                doc["severity_level"] = highest_severity(doc["severity_level"], SEVERITY_URGENCY)
            anomalies.append(doc)
        return jsonify({"anomalies": anomalies, "count": len(anomalies)}), 200
    except PyMongoError as e:
        raise DatabaseError({"code": "ml_anomalies_query_error", "message": str(e)}, 500)


@ml_bp.route("/api/doctor/ml-anomalies/<anomaly_id>", methods=["PATCH"])
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
    # Alerte seuil ouverte liée : clôturer la même ligne que PATCH /api/doctor/alerts
    if (
        anomaly_doc.get("anomaly_source") == "threshold"
        or anomaly_doc.get("anomaly_level") == "threshold"
    ):
        try:
            ds_alert = "VALIDATED" if new_status == "validated" else "REJECTED"
            alert_upd: Dict[str, Any] = {
                "doctor_status": ds_alert,
                "status": "RESOLVED",
                "resolved_at": now,
                "updated_at": now,
            }
            if new_status == "validated":
                alert_upd["validated_by"] = g.user_id_auth
                alert_upd["validated_at"] = now
            else:
                alert_upd["rejected_by"] = g.user_id_auth
                alert_upd["rejected_at"] = now
            get_medical_db().alerts.update_one(
                {"ml_anomaly_id": oid, "alert_source": "threshold", "status": "OPEN"},
                {"$set": alert_upd},
            )
        except PyMongoError as e:
            logger.warning("sync threshold alert from ML validation failed: %s", e)
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


@ml_bp.route("/api/admin/ml/retrain", methods=["POST"])
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


@ml_bp.route("/api/admin/ml/batch-score", methods=["POST"])
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


@ml_bp.route("/api/admin/ml/bootstrap", methods=["POST"])
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


@ml_bp.route("/api/admin/ml/test", methods=["POST"])
@requires_auth
@requires_role("doctor", "superuser")
def run_ml_test():
    from tests import ml_test
    payload = request.get_json(silent=True) or {}
    custom = payload.get("measurements")
    results = ml_test.run_custom_test(custom) if custom and isinstance(custom, list) else ml_test.run_all_tests()
    return jsonify(results), 200


@ml_bp.route("/api/admin/ml/thresholds", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser")
def get_ml_thresholds():
    return jsonify(ml_module.get_model_info()), 200


@ml_bp.route("/api/admin/ml/thresholds", methods=["PUT"])
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


_PATIENT_IDENTITY_PROJECTION = {"display_name": 1, "email": 1, "first_name": 1, "last_name": 1}


def _apply_patient_identity_to_ml_payload(payload: Dict[str, Any], user_doc: Optional[Dict[str, Any]]) -> None:
    """Remplit patient_display, patient_first_name, patient_last_name pour les réponses ML."""
    if not user_doc:
        return
    payload["patient_display"] = resolve_patient_display_name(user_doc)
    fn = (user_doc.get("first_name") or "").strip()
    ln = (user_doc.get("last_name") or "").strip()
    if is_auth_provider_id(fn):
        fn = ""
    if is_auth_provider_id(ln):
        ln = ""
    if not fn and not ln:
        disp = (user_doc.get("display_name") or "").strip()
        if disp and not is_auth_provider_id(disp):
            a, b = _split_display_name(disp)
            fn, ln = (a or "").strip(), (b or "").strip()
            if is_auth_provider_id(fn):
                fn = ""
            if is_auth_provider_id(ln):
                ln = ""
    payload["patient_first_name"] = fn or None
    payload["patient_last_name"] = ln or None


def _load_clinical_context_safe(patient_id: str) -> Optional[Dict[str, Any]]:
    try:
        return load_patient_clinical_context(patient_id)
    except Exception as exc:
        logger.warning("Clinical context load failed for %s: %s", patient_id, exc)
        return None


def _attach_contextual_summaries(
    payload: Dict[str, Any],
    analysis: Dict[str, Any],
    max_severity: int,
    clinical_context: Optional[Dict[str, Any]],
) -> None:
    payload["clinical_narrative_summary"] = build_clinical_weekly_narrative(
        analysis, max_severity, clinical_context=clinical_context,
    )
    payload["lay_narrative_summary"] = build_lay_caregiver_weekly_summary(
        analysis, max_severity, clinical_context=clinical_context,
    )
    if clinical_context:
        payload["patient_clinical_context"] = {
            "condition_labels": clinical_context.get("condition_labels") or [],
            "pathology": clinical_context.get("pathology"),
            "has_medical_history": bool(clinical_context.get("medical_history_excerpt")),
            "doctor_feedback_count": len(clinical_context.get("recent_doctor_feedback") or []),
            "context_recently_updated": bool(
                clinical_context.get("profile_recently_updated")
                or clinical_context.get("has_recent_doctor_feedback")
                or clinical_context.get("doctor_only_labels")
            ),
        }


@ml_bp.route("/api/ml/decisions", methods=["GET"])
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


@ml_bp.route("/api/doctor/ml/forecast/<patient_id>", methods=["GET", "OPTIONS"])
@requires_auth
@requires_role("doctor", "superuser", "caregiver", "aidant")
def get_ml_forecast(patient_id: str):
    patient_id = resolve_patient_id(patient_id)
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
        user_doc = get_identity_db().users.find_one({"user_id_auth": patient_id}, _PATIENT_IDENTITY_PROJECTION)
        if user_doc:
            _apply_patient_identity_to_ml_payload(result, user_doc)
    except Exception:
        pass
    return jsonify(result), 200


@ml_bp.route("/api/doctor/ml/patient-analysis/<patient_id>", methods=["GET", "OPTIONS"])
@requires_auth
@requires_role("doctor", "superuser", "caregiver", "aidant")
def get_patient_ml_analysis(patient_id: str):
    patient_id = resolve_patient_id(patient_id)
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
    measurement_span = get_patient_measurement_date_span(device_ids)
    suggested_days = suggest_analysis_days_for_measurement_span(measurement_span)
    if len(measurements) < 3:
        # Pas une « mauvaise requête » : le client doit pouvoir afficher un message sans erreur HTTP 400.
        clinical_context = _load_clinical_context_safe(patient_id)
        insuff_analysis = {"status": "insufficient_data"}
        narrative = build_clinical_weekly_narrative(
            insuff_analysis, 0, clinical_context=clinical_context,
        )
        lay_narrative = build_lay_caregiver_weekly_summary(
            insuff_analysis, 0, clinical_context=clinical_context,
        )
        message = (
            f"Moins de 3 mesures sur les {days} derniers jours ({len(measurements)} reçue(s)). "
            "L'analyse détaillée nécessite au moins 3 points."
        )
        if measurement_span and suggested_days and suggested_days > days:
            message += (
                f" Les dernières mesures datent d'environ {measurement_span['latest_age_days']} jour(s) ; "
                f"essayez la période {suggested_days} jours."
            )
        insuff_body: Dict[str, Any] = {
            "code": "insufficient_data",
            "message": message,
            "patient_id": get_user_db_id(patient_id) or patient_id,
            "patient_user_id_auth": patient_id,
            "device_ids": device_ids,
            "days": days,
            "measurement_count": len(measurements),
            "n_total_measurements": count_patient_measurements_total(device_ids),
            "status": "insufficient_data",
            "clinical_narrative_summary": narrative,
            "lay_narrative_summary": lay_narrative,
            "anomaly_summary": {"total": 0, "by_status": {}, "recent": []},
            "vitals": {},
            "timeline": [],
            "correlations": {},
            "ml_score_timeline": [],
        }
        if measurement_span:
            insuff_body["measurement_span"] = measurement_span
        if suggested_days:
            insuff_body["suggested_days"] = suggested_days
        if clinical_context:
            insuff_body["patient_clinical_context"] = {
                "condition_labels": clinical_context.get("condition_labels") or [],
                "pathology": clinical_context.get("pathology"),
                "has_medical_history": bool(clinical_context.get("medical_history_excerpt")),
                "doctor_feedback_count": len(clinical_context.get("recent_doctor_feedback") or []),
                "context_recently_updated": bool(
                    clinical_context.get("profile_recently_updated")
                    or clinical_context.get("has_recent_doctor_feedback")
                    or clinical_context.get("doctor_only_labels")
                ),
            }
        try:
            user_doc = get_identity_db().users.find_one({"user_id_auth": patient_id}, _PATIENT_IDENTITY_PROJECTION)
            if user_doc:
                _apply_patient_identity_to_ml_payload(insuff_body, user_doc)
        except Exception:
            pass
        return jsonify(insuff_body), 200
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
    try:
        clinical_context = _load_clinical_context_safe(patient_id)
        result = ml_module.analyze_patient_vitals(measurements, ml_scores=ml_decisions_list, anomaly_records=anomaly_records)
        _max_sev = weekly_summary_max_severity(result)
        _attach_contextual_summaries(result, result, _max_sev, clinical_context)
        result["anomaly_summary"] = build_combined_anomaly_summary_for_analysis(
            anomaly_records, threshold_alert_docs
        )
        if include_forecast and len(measurements) >= 3:
            try:
                result["forecast"] = ml_module.forecast_vitals(
                    measurements,
                    horizon=forecast_horizon,
                    history_window_hours=48,
                )
                if isinstance(result.get("forecast"), dict) and isinstance(result["forecast"].get("summary"), dict):
                    result["forecast"]["summary"] = enrich_narrative_summary(
                        result["forecast"]["summary"], result, clinical_context, audience="clinical",
                    )
            except Exception as e:
                logger.warning("Forecast skipped for patient %s (days=%s): %s", patient_id, days, e)
                result["forecast"] = {"error": str(e)}
        result["patient_id"] = get_user_db_id(patient_id) or patient_id
        result["device_ids"] = device_ids
        result["days"] = days
        result["n_total_measurements"] = count_patient_measurements_total(device_ids)
        try:
            user_doc = get_identity_db().users.find_one({"user_id_auth": patient_id}, _PATIENT_IDENTITY_PROJECTION)
            if user_doc:
                _apply_patient_identity_to_ml_payload(result, user_doc)
        except Exception:
            pass
        return jsonify(result), 200
    except (AuthError, DatabaseError):
        raise
    except Exception as e:
        logger.exception("get_patient_ml_analysis failed: %s", e)
        return jsonify({
            "code": "analysis_error",
            "message": "L'analyse n'a pas pu être calculée. Réessayez plus tard.",
        }), 500

