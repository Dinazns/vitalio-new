"""
Alert threshold and breach evaluation logic.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from pymongo.errors import PyMongoError

from config import ALERT_DEFAULT_THRESHOLDS, ALERT_DEFAULT_CONSECUTIVE_BREACHES
from database import get_medical_db
from exceptions import DatabaseError


def merge_thresholds(raw_thresholds: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Return complete threshold dictionary with defaults."""
    thresholds = dict(ALERT_DEFAULT_THRESHOLDS)
    if not isinstance(raw_thresholds, dict):
        return thresholds
    for key in ALERT_DEFAULT_THRESHOLDS.keys():
        value = raw_thresholds.get(key)
        if value is None:
            continue
        try:
            thresholds[key] = float(value)
        except (TypeError, ValueError):
            continue
    return thresholds


def get_alert_threshold_config(device_id: str, pathology: Optional[str] = None) -> Dict[str, Any]:
    """Resolve alert thresholds with priority: patient -> pathology -> default -> builtin."""
    collection = get_medical_db().alert_thresholds
    config = None
    scope = "builtin_default"

    try:
        config = collection.find_one({"scope": "patient", "device_id": device_id, "enabled": True})
        if config:
            scope = "patient"
        elif pathology:
            config = collection.find_one({"scope": "pathology", "pathology": pathology, "enabled": True})
            if config:
                scope = "pathology"
        if not config:
            config = collection.find_one({"scope": "default", "enabled": True})
            if config:
                scope = "default"
    except PyMongoError:
        config = None
        scope = "builtin_default"

    thresholds = merge_thresholds((config or {}).get("thresholds"))
    consecutive = (config or {}).get("consecutive_breaches", ALERT_DEFAULT_CONSECUTIVE_BREACHES)
    try:
        consecutive = max(1, int(consecutive))
    except (TypeError, ValueError):
        consecutive = ALERT_DEFAULT_CONSECUTIVE_BREACHES

    return {
        "scope": scope,
        "thresholds": thresholds,
        "consecutive_breaches": consecutive,
        "pathology": (config or {}).get("pathology"),
    }


def compute_metric_breaches(measurement: Dict[str, Any], thresholds: Dict[str, float]) -> List[Dict[str, Any]]:
    """Return the list of metric breaches found on the measurement."""
    breaches = []

    hr = measurement.get("heart_rate")
    if isinstance(hr, (int, float)):
        if hr < thresholds["heart_rate_min"]:
            breaches.append({"metric": "heart_rate", "operator": "lt", "threshold": thresholds["heart_rate_min"], "value": hr})
        elif hr > thresholds["heart_rate_max"]:
            breaches.append({"metric": "heart_rate", "operator": "gt", "threshold": thresholds["heart_rate_max"], "value": hr})

    spo2 = measurement.get("spo2")
    if isinstance(spo2, (int, float)) and spo2 < thresholds["spo2_min"]:
        breaches.append({"metric": "spo2", "operator": "lt", "threshold": thresholds["spo2_min"], "value": spo2})

    temp = measurement.get("temperature")
    if isinstance(temp, (int, float)):
        if temp < thresholds["temperature_min"]:
            breaches.append({"metric": "temperature", "operator": "lt", "threshold": thresholds["temperature_min"], "value": temp})
        elif temp > thresholds["temperature_max"]:
            breaches.append({"metric": "temperature", "operator": "gt", "threshold": thresholds["temperature_max"], "value": temp})

    return breaches


def has_consecutive_breach(device_id: str, breach: Dict[str, Any], consecutive_required: int) -> bool:
    """Check if the same breach condition appears on N consecutive valid measurements."""
    metric = breach["metric"]
    operator = breach["operator"]
    threshold = breach["threshold"]
    cursor = get_medical_db().measurements.find(
        {"device_id": device_id, "status": {"$ne": "INVALID"}},
        projection={"_id": 0, metric: 1, "measured_at": 1}
    ).sort("measured_at", -1).limit(consecutive_required)

    rows = list(cursor)
    if len(rows) < consecutive_required:
        return False

    for row in rows:
        value = row.get(metric)
        if not isinstance(value, (int, float)):
            return False
        if operator == "lt" and value >= threshold:
            return False
        if operator == "gt" and value <= threshold:
            return False
    return True


def upsert_open_alert(device_id: str, breach: Dict[str, Any], threshold_config: Dict[str, Any], measured_at: datetime) -> bool:
    """
    Create or update an open alert for a durable breach.
    Returns True if a NEW alert was created (insert), False if existing was updated.
    """
    metric = breach["metric"]
    operator = breach["operator"]
    query = {"device_id": device_id, "metric": metric, "operator": operator, "status": "OPEN"}
    now = datetime.now(timezone.utc)
    set_fields = {
        "threshold": breach["threshold"],
        "latest_value": breach["value"],
        "consecutive_required": threshold_config["consecutive_breaches"],
        "last_breach_at": measured_at,
        "rule_scope": threshold_config["scope"],
        "updated_at": now,
    }
    set_on_insert = {
        "device_id": device_id,
        "metric": metric,
        "operator": operator,
        "status": "OPEN",
        "created_at": now,
        "first_breach_at": measured_at,
        "doctor_status": "PENDING",
    }
    result = get_medical_db().alerts.update_one(
        query,
        {"$set": set_fields, "$setOnInsert": set_on_insert},
        upsert=True
    )
    return result.upserted_id is not None


def resolve_metric_alert(device_id: str, metric: str):
    """Resolve open alerts for a metric once value is back in-range."""
    get_medical_db().alerts.update_many(
        {"device_id": device_id, "metric": metric, "status": "OPEN"},
        {"$set": {"status": "RESOLVED", "resolved_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}}
    )


def evaluate_measurement_alerts(device_id: str, measurement: Dict[str, Any], pathology: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Evaluate one ingested measurement and create alerts only for durable breaches.
    Returns durable breaches that triggered/updated OPEN alerts.
    """
    if measurement.get("status") == "INVALID":
        return []

    threshold_config = get_alert_threshold_config(device_id=device_id, pathology=pathology)
    thresholds = threshold_config["thresholds"]
    breaches = compute_metric_breaches(measurement, thresholds)
    durable = []
    measured_at = measurement.get("measured_at")
    if not isinstance(measured_at, datetime):
        measured_at = datetime.now(timezone.utc)

    breached_metrics = {breach["metric"] for breach in breaches}
    for metric in ("heart_rate", "spo2", "temperature"):
        if metric not in breached_metrics:
            resolve_metric_alert(device_id, metric)

    for breach in breaches:
        if has_consecutive_breach(device_id, breach, threshold_config["consecutive_breaches"]):
            is_new = upsert_open_alert(device_id, breach, threshold_config, measured_at)
            durable.append({
                "metric": breach["metric"],
                "operator": breach["operator"],
                "value": breach["value"],
                "threshold": breach["threshold"],
                "scope": threshold_config["scope"],
                "is_new": is_new,
            })
            if is_new:
                try:
                    from services.invitation_service import send_alert_emails_for_new_alert
                    from services.user_service import get_patient_id_from_device, get_user_profile
                    patient_id = get_patient_id_from_device(device_id)
                    patient_name = "Un patient"
                    if patient_id:
                        profile = get_user_profile(patient_id)
                        patient_name = profile.get("display_name") or profile.get("email") or "Un patient"
                    send_alert_emails_for_new_alert(
                        device_id=device_id,
                        metric=breach["metric"],
                        operator=breach["operator"],
                        value=breach["value"],
                        threshold=breach["threshold"],
                        patient_name=patient_name,
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("Failed to send alert emails for device %s: %s", device_id, e)

    return durable
