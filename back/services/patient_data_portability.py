"""
Export et effacement des données patient (RGPD / droit à l'oubli côté VitalIO).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pymongo.errors import PyMongoError

from database import get_identity_db, get_medical_db
from exceptions import DatabaseError
from services.user_service import (
    datetime_to_iso_utc,
    get_assigned_caregiver_ids_for_patient,
    get_assigned_doctor_ids_for_patient,
    get_device_ids,
    get_user_profile,
)

logger = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return datetime_to_iso_utc(value) if value.tzinfo else value.replace(tzinfo=timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _serialize_user_doc(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not doc:
        return {}
    out = dict(doc)
    out.pop("_id", None)
    return _json_safe(out)


def build_patient_export(user_id_auth: str) -> Dict[str, Any]:
    """Assemble toutes les données VitalIO liées au patient."""
    identity = get_identity_db()
    medical = get_medical_db()
    profile = get_user_profile(user_id_auth)
    device_ids = get_device_ids(user_id_auth)

    doctor_ids = get_assigned_doctor_ids_for_patient(user_id_auth)
    caregiver_ids = get_assigned_caregiver_ids_for_patient(user_id_auth)

    doctors = []
    for did in doctor_ids:
        doctors.append(_serialize_user_doc(identity.users.find_one({"user_id_auth": did})))

    caregivers = []
    for cid in caregiver_ids:
        caregivers.append(_serialize_user_doc(identity.users.find_one({"user_id_auth": cid})))

    users_devices = list(identity.users_devices.find({"user_id_auth": user_id_auth}, {"_id": 0}))
    device_enrollments = []
    for did in device_ids:
        de = identity.device_enrollments.find_one({"device_id": did}, {"_id": 0})
        if de:
            device_enrollments.append(_serialize_user_doc(de))

    measurements: List[Dict[str, Any]] = []
    if device_ids:
        try:
            cur = medical.measurements.find({"device_id": {"$in": device_ids}}).sort("measured_at", -1).limit(100_000)
            for doc in cur:
                measurements.append(_serialize_user_doc(doc))
        except PyMongoError as e:
            raise DatabaseError({"code": "export_measurements_error", "message": str(e)}, 500)

    alerts: List[Dict[str, Any]] = []
    alert_events: List[Dict[str, Any]] = []
    med_alert_ids: List[str] = []
    alert_or: List[Dict[str, Any]] = [{"patient_user_id_auth": user_id_auth}]
    if device_ids:
        alert_or.insert(0, {"device_id": {"$in": device_ids}})
    try:
        for doc in medical.alerts.find({"$or": alert_or}).sort("created_at", -1).limit(50_000):
            if doc.get("_id"):
                med_alert_ids.append(str(doc["_id"]))
            alerts.append(_serialize_user_doc(doc))
        if med_alert_ids:
            for ev in medical.alert_events.find({"medical_alert_id": {"$in": med_alert_ids}}).sort("created_at", 1).limit(200_000):
                alert_events.append(_serialize_user_doc(ev))
    except PyMongoError as e:
        raise DatabaseError({"code": "export_alerts_error", "message": str(e)}, 500)

    identity_alerts_list: List[Dict[str, Any]] = []
    if med_alert_ids:
        for row in identity.alerts.find({"medical_alert_id": {"$in": med_alert_ids}}, {"_id": 0}).limit(50_000):
            identity_alerts_list.append(_serialize_user_doc(row))

    ml_anomalies: List[Dict[str, Any]] = []
    ml_decisions: List[Dict[str, Any]] = []
    ml_or: List[Dict[str, Any]] = [{"user_id_auth": user_id_auth}]
    if device_ids:
        ml_or.insert(0, {"device_id": {"$in": device_ids}})
    try:
        for doc in medical.ml_anomalies.find({"$or": ml_or}).sort("created_at", -1).limit(50_000):
            ml_anomalies.append(_serialize_user_doc(doc))
        if device_ids:
            for doc in medical.ml_decisions.find({"device_id": {"$in": device_ids}}).sort("processed_at", -1).limit(100_000):
                ml_decisions.append(_serialize_user_doc(doc))
    except PyMongoError as e:
        raise DatabaseError({"code": "export_ml_error", "message": str(e)}, 500)

    doctor_feedback: List[Dict[str, Any]] = []
    try:
        for doc in medical.doctor_feedback.find({"patient_user_id_auth": user_id_auth}).sort("created_at", -1).limit(10_000):
            doctor_feedback.append(_serialize_user_doc(doc))
    except PyMongoError as e:
        raise DatabaseError({"code": "export_feedback_error", "message": str(e)}, 500)

    alert_thresholds: List[Dict[str, Any]] = []
    threshold_breach_events: List[Dict[str, Any]] = []
    if device_ids:
        try:
            for doc in medical.alert_thresholds.find({"device_id": {"$in": device_ids}}):
                alert_thresholds.append(_serialize_user_doc(doc))
            for doc in medical.threshold_breach_events.find({"device_id": {"$in": device_ids}}).sort("created_at", -1).limit(50_000):
                threshold_breach_events.append(_serialize_user_doc(doc))
        except PyMongoError as e:
            logger.warning("export thresholds/breaches: %s", e)

    caregiver_invites = list(
        identity.caregiver_invites.find({"patient_user_id_auth": user_id_auth}, {"token_hash": 0, "_id": 0}).limit(500)
    )
    caregiver_invites = [_serialize_user_doc(x) for x in caregiver_invites]

    doctor_patients = list(identity.doctor_patients.find({"patient_user_id_auth": user_id_auth}, {"_id": 0}))
    caregiver_patients = list(identity.caregiver_patients.find({"patient_user_id_auth": user_id_auth}, {"_id": 0}))

    push_subscriptions = list(identity.push_subscriptions.find({"user_id_auth": user_id_auth}, {"_id": 0}))

    audit_links = list(identity.audit_links.find({"patient_user_id_auth": user_id_auth}, {"_id": 0}).limit(5000))
    audit_links = [_serialize_user_doc(x) for x in audit_links]

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user_id_auth": user_id_auth,
        "profile": _json_safe(profile),
        "device_ids": device_ids,
        "users_devices": [_serialize_user_doc(x) for x in users_devices],
        "device_enrollments": device_enrollments,
        "doctor_patients": [_serialize_user_doc(x) for x in doctor_patients],
        "caregiver_patients": [_serialize_user_doc(x) for x in caregiver_patients],
        "caregiver_invites": caregiver_invites,
        "push_subscriptions": [_serialize_user_doc(x) for x in push_subscriptions],
        "audit_links": audit_links,
        "linked_doctors_profiles": doctors,
        "linked_caregivers_profiles": caregivers,
        "measurements": measurements,
        "medical_alerts": alerts,
        "alert_events": alert_events,
        "identity_alert_mirrors": identity_alerts_list,
        "ml_anomalies": ml_anomalies,
        "ml_decisions": ml_decisions,
        "doctor_feedback": doctor_feedback,
        "alert_thresholds": alert_thresholds,
        "threshold_breach_events": threshold_breach_events,
    }


def erase_patient_all_data(user_id_auth: str) -> Dict[str, int]:
    """
    Supprime les enregistrements VitalIO pour ce patient (profil inclus).
    N'efface pas le compte Auth0 (déconnexion côté client).
    """
    identity = get_identity_db()
    medical = get_medical_db()
    device_ids = get_device_ids(user_id_auth)
    counts: Dict[str, int] = {}

    med_alert_ids: List[str] = []
    if device_ids or user_id_auth:
        q_or: List[Dict[str, Any]] = []
        if device_ids:
            q_or.append({"device_id": {"$in": device_ids}})
        q_or.append({"patient_user_id_auth": user_id_auth})
        try:
            for doc in medical.alerts.find({"$or": q_or}, {"_id": 1}):
                if doc.get("_id"):
                    med_alert_ids.append(str(doc["_id"]))
        except PyMongoError as e:
            raise DatabaseError({"code": "erase_alerts_list_error", "message": str(e)}, 500)

    try:
        if med_alert_ids:
            r = medical.alert_events.delete_many({"medical_alert_id": {"$in": med_alert_ids}})
            counts["alert_events"] = r.deleted_count
            oids = []
            for s in med_alert_ids:
                try:
                    oids.append(ObjectId(s))
                except Exception:
                    pass
            if oids:
                r = medical.alerts.delete_many({"_id": {"$in": oids}})
                counts["medical_alerts"] = r.deleted_count
            r = identity.alerts.delete_many({"medical_alert_id": {"$in": med_alert_ids}})
            counts["identity_alerts"] = r.deleted_count
    except PyMongoError as e:
        raise DatabaseError({"code": "erase_alerts_error", "message": str(e)}, 500)

    try:
        if device_ids:
            r = medical.ml_decisions.delete_many({"device_id": {"$in": device_ids}})
            counts["ml_decisions"] = r.deleted_count
            r = medical.measurements.delete_many({"device_id": {"$in": device_ids}})
            counts["measurements"] = r.deleted_count
            r = medical.threshold_breach_events.delete_many({"device_id": {"$in": device_ids}})
            counts["threshold_breach_events"] = r.deleted_count
            r = medical.alert_thresholds.delete_many({"device_id": {"$in": device_ids}})
            counts["alert_thresholds"] = r.deleted_count
        ano_or: List[Dict[str, Any]] = [{"user_id_auth": user_id_auth}]
        if device_ids:
            ano_or.insert(0, {"device_id": {"$in": device_ids}})
        r = medical.ml_anomalies.delete_many({"$or": ano_or})
        counts["ml_anomalies"] = r.deleted_count
        r = medical.doctor_feedback.delete_many({"patient_user_id_auth": user_id_auth})
        counts["doctor_feedback"] = r.deleted_count
    except PyMongoError as e:
        raise DatabaseError({"code": "erase_medical_error", "message": str(e)}, 500)

    try:
        r = identity.caregiver_invites.delete_many({"patient_user_id_auth": user_id_auth})
        counts["caregiver_invites"] = r.deleted_count
        r = identity.doctor_patients.delete_many({"patient_user_id_auth": user_id_auth})
        counts["doctor_patients"] = r.deleted_count
        r = identity.caregiver_patients.delete_many({"patient_user_id_auth": user_id_auth})
        counts["caregiver_patients"] = r.deleted_count
        r = identity.audit_links.delete_many({"patient_user_id_auth": user_id_auth})
        counts["audit_links"] = r.deleted_count
        r = identity.push_subscriptions.delete_many({"user_id_auth": user_id_auth})
        counts["push_subscriptions"] = r.deleted_count
        if device_ids:
            r = identity.device_enrollments.delete_many({"device_id": {"$in": device_ids}})
            counts["device_enrollments"] = r.deleted_count
        r = identity.users_devices.delete_many({"user_id_auth": user_id_auth})
        counts["users_devices"] = r.deleted_count
        r = identity.users.delete_one({"user_id_auth": user_id_auth})
        counts["users_deleted"] = r.deleted_count
    except PyMongoError as e:
        raise DatabaseError({"code": "erase_identity_error", "message": str(e)}, 500)

    return counts
