"""Doctor route shared helpers."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo.errors import PyMongoError

from app.database import get_identity_db
from app.exceptions import DatabaseError
from app.services.user_service import resolve_patient_id_to_user_id_auth
from app.services.device_constants import active_device_assignment_fields


def normalize_email(email_raw: str):
    if not email_raw or not isinstance(email_raw, str):
        return None
    s = str(email_raw).strip().lower()
    return s if "@" in s and "." in s and len(s) > 5 else None


def admin_user_summary(profile: Dict[str, Any], user_id_auth: Optional[str]) -> Optional[Dict[str, Any]]:
    """Compact user descriptor for admin listings."""
    if not user_id_auth:
        return None
    first_name = (profile.get("first_name") or "").strip()
    last_name = (profile.get("last_name") or "").strip()
    full_name = f"{first_name} {last_name}".strip()
    display_name = (profile.get("display_name") or "").strip() or full_name or None
    return {
        "user_id_auth": user_id_auth,
        "display_name": display_name,
        "email": profile.get("email"),
        "first_name": profile.get("first_name"),
        "last_name": profile.get("last_name"),
    }


def resolve_patient_id(patient_id: str) -> str:
    """Resolve URL patient_id (db id or auth id) to user_id_auth. Raises 404 if not found."""
    resolved = resolve_patient_id_to_user_id_auth(patient_id)
    if not resolved:
        raise DatabaseError({"code": "patient_not_found", "message": "Patient not found"}, 404)
    return resolved


def apply_patient_device_assignment(
    patient_user_id_auth: str,
    device_id: str,
    assigned_by_user_id_auth: str,
):
    """Associe un boîtier à un patient. Retourne (True, now) ou (False, body_dict, http_status)."""
    existing = get_identity_db().users_devices.find_one({"device_id": device_id})
    if existing and existing.get("user_id_auth") != patient_user_id_auth:
        return (
            False,
            {
                "code": "device_already_assigned",
                "message": "Ce device est déjà assigné à un autre patient",
            },
            409,
        )
    now = datetime.now(timezone.utc)
    try:
        get_identity_db().users_devices.update_one(
            {"user_id_auth": patient_user_id_auth},
            {
                "$set": active_device_assignment_fields(
                    patient_user_id_auth,
                    device_id,
                    assigned_by=assigned_by_user_id_auth,
                    assigned_at=now,
                ),
                "$unset": {
                    "suspension_reason": "",
                    "status_updated_at": "",
                    "status_updated_by": "",
                },
            },
            upsert=True,
        )
    except PyMongoError as e:
        raise DatabaseError({"code": "device_assign_error", "message": str(e)}, 500)
    return (True, now)


def build_combined_anomaly_summary_for_analysis(
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
