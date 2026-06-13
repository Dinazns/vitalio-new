"""
Alert threshold and breach evaluation logic.
"""
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from bson import ObjectId
from pymongo.errors import PyMongoError

from app.config import ALERT_DEFAULT_THRESHOLDS, ALERT_DEFAULT_CONSECUTIVE_BREACHES
from app.database import get_medical_db
from app.exceptions import DatabaseError
from app.services.patient_pseudo_service import get_patient_pseudo_id_for_device
from app.services.severity_level import (
    SEVERITY_CRITICAL,
    SEVERITY_URGENCY,
    SEVERITY_WARNING,
    severity_for_manual_alert,
    severity_for_near_threshold,
    severity_for_ml_anomaly_level,
    severity_for_threshold_breach,
)
from app.services.user_service import get_patient_id_from_device

# Margins for "near threshold" WARNING alerts (values still in range, close to limit).
_NEAR_THRESHOLD_MARGINS = {
    "spo2": 3.0,
    "heart_rate": 5.0,
    "temperature": 0.4,
}

logger = logging.getLogger(__name__)

# Cooldown in seconds between manual alerts from the same patient
MANUAL_ALERT_COOLDOWN_SECONDS = 0
MANUAL_ALERT_MAX_PER_HOUR = 9999


def write_alert_event(
    medical_alert_id: str,
    event_type: str,
    actor_user_id_auth: str,
    actor_role: str,
    payload: Dict[str, Any],
) -> None:
    """
    Append an immutable audit event to medical.alert_events.
    event_type values:
      alert_created, alert_resolved,
      doctor_validated, doctor_rejected, doctor_escalation, doctor_note,
      caregiver_seen_patient, caregiver_comment,
      patient_manual_trigger,
      ml_audit_merged.
    """
    try:
        doc: Dict[str, Any] = {
            "medical_alert_id": medical_alert_id,
            "event_type": event_type,
            "actor_user_id_auth": actor_user_id_auth,
            "actor_role": actor_role,
            "payload": payload,
            "created_at": datetime.now(timezone.utc),
        }
        get_medical_db().alert_events.insert_one(doc)
    except Exception as exc:
        logger.warning("alert_events insert failed (event_type=%s): %s", event_type, exc)


def _rule_enabled(doc: Optional[Dict[str, Any]]) -> bool:
    """Missing 'enabled' counts as True (legacy documents)."""
    if not doc:
        return False
    return doc.get("enabled") is not False


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
        patient_doc = collection.find_one({"scope": "patient", "device_id": device_id})
        if patient_doc and _rule_enabled(patient_doc):
            config = patient_doc
            scope = "patient"
        elif pathology:
            path_doc = collection.find_one({"scope": "pathology", "pathology": pathology})
            if path_doc and _rule_enabled(path_doc):
                config = path_doc
                scope = "pathology"
        if config is None:
            default_doc = collection.find_one({"scope": "default"})
            if default_doc and _rule_enabled(default_doc):
                config = default_doc
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
        "rule_id": (config or {}).get("_id"),
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


def compute_near_threshold_conditions(
    measurement: Dict[str, Any],
    thresholds: Dict[str, float],
) -> List[Dict[str, Any]]:
    """Return near-threshold conditions (WARNING) without full breach."""
    near = []
    hr = measurement.get("heart_rate")
    if isinstance(hr, (int, float)):
        margin = _NEAR_THRESHOLD_MARGINS["heart_rate"]
        if thresholds["heart_rate_min"] <= hr < thresholds["heart_rate_min"] + margin:
            near.append({
                "metric": "heart_rate",
                "operator": "near_lt",
                "threshold": thresholds["heart_rate_min"],
                "value": hr,
            })
        elif thresholds["heart_rate_max"] - margin < hr <= thresholds["heart_rate_max"]:
            near.append({
                "metric": "heart_rate",
                "operator": "near_gt",
                "threshold": thresholds["heart_rate_max"],
                "value": hr,
            })

    spo2 = measurement.get("spo2")
    if isinstance(spo2, (int, float)):
        margin = _NEAR_THRESHOLD_MARGINS["spo2"]
        lo = thresholds["spo2_min"]
        if lo <= spo2 < lo + margin:
            near.append({
                "metric": "spo2",
                "operator": "near_lt",
                "threshold": lo,
                "value": spo2,
            })

    temp = measurement.get("temperature")
    if isinstance(temp, (int, float)):
        margin = _NEAR_THRESHOLD_MARGINS["temperature"]
        if thresholds["temperature_min"] <= temp < thresholds["temperature_min"] + margin:
            near.append({
                "metric": "temperature",
                "operator": "near_lt",
                "threshold": thresholds["temperature_min"],
                "value": temp,
            })
        elif thresholds["temperature_max"] - margin < temp <= thresholds["temperature_max"]:
            near.append({
                "metric": "temperature",
                "operator": "near_gt",
                "threshold": thresholds["temperature_max"],
                "value": temp,
            })

    return near


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


def upsert_open_alert(
    device_id: str,
    breach: Dict[str, Any],
    threshold_config: Dict[str, Any],
    measured_at: datetime,
    measurement_id: Any = None,
) -> Tuple[bool, Optional[ObjectId]]:
    """
    Create or update an open alert for a durable breach.
    Returns (is_new, alert_object_id). On creation also writes an alert_created event to alert_events.
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
        "applied_thresholds": threshold_config.get("thresholds"),
        "updated_at": now,
    }
    rid = threshold_config.get("rule_id")
    if rid is not None:
        set_fields["alert_thresholds_rule_id"] = rid
    if measurement_id is not None:
        set_fields["measurement_id"] = measurement_id
    set_on_insert = {
        "device_id": device_id,
        "metric": metric,
        "operator": operator,
        "status": "OPEN",
        "created_at": now,
        "first_breach_at": measured_at,
        "doctor_status": "PENDING",
        "alert_source": "threshold",
        "severity_level": severity_for_threshold_breach(),
        # first_measurement_id is set once at creation and never overwritten
        **({"first_measurement_id": measurement_id} if measurement_id is not None else {}),
    }
    pseudo = get_patient_pseudo_id_for_device(device_id)
    if pseudo:
        set_fields["patient_pseudo_id"] = pseudo
        set_on_insert["patient_pseudo_id"] = pseudo
    # measurement_id is NOT duplicated in $setOnInsert - it lives only in $set above
    result = get_medical_db().alerts.update_one(
        query,
        {"$set": set_fields, "$setOnInsert": set_on_insert},
        upsert=True
    )
    is_new = result.upserted_id is not None
    if is_new:
        alert_oid: Optional[ObjectId] = result.upserted_id
        write_alert_event(
            medical_alert_id=str(result.upserted_id),
            event_type="alert_created",
            actor_user_id_auth=device_id,
            actor_role="system",
            payload={
                "alert_source": "threshold",
                "metric": metric,
                "operator": operator,
                "value": breach["value"],
                "threshold": breach["threshold"],
                "rule_scope": threshold_config["scope"],
                "measurement_id": str(measurement_id) if measurement_id else None,
            },
        )
    else:
        doc = get_medical_db().alerts.find_one(query, projection={"_id": 1})
        alert_oid = doc["_id"] if doc else None
    return is_new, alert_oid


def upsert_near_threshold_alert(
    device_id: str,
    condition: Dict[str, Any],
    threshold_config: Dict[str, Any],
    measured_at: datetime,
    measurement_id: Any = None,
) -> Tuple[bool, Optional[ObjectId]]:
    """Create or refresh a WARNING alert when a value is close to a clinical threshold."""
    metric = condition["metric"]
    operator = condition["operator"]
    query = {
        "device_id": device_id,
        "metric": metric,
        "operator": operator,
        "alert_source": "near_threshold",
        "status": "OPEN",
    }
    now = datetime.now(timezone.utc)
    set_fields = {
        "threshold": condition["threshold"],
        "latest_value": condition["value"],
        "last_breach_at": measured_at,
        "rule_scope": threshold_config["scope"],
        "applied_thresholds": threshold_config.get("thresholds"),
        "updated_at": now,
        "severity_level": severity_for_near_threshold(),
    }
    if measurement_id is not None:
        set_fields["measurement_id"] = measurement_id
    set_on_insert = {
        "device_id": device_id,
        "metric": metric,
        "operator": operator,
        "status": "OPEN",
        "alert_source": "near_threshold",
        "doctor_status": "PENDING",
        "severity_level": severity_for_near_threshold(),
        "created_at": now,
        "first_breach_at": measured_at,
        **({"first_measurement_id": measurement_id} if measurement_id is not None else {}),
    }
    pseudo = get_patient_pseudo_id_for_device(device_id)
    if pseudo:
        set_fields["patient_pseudo_id"] = pseudo
        set_on_insert["patient_pseudo_id"] = pseudo
    result = get_medical_db().alerts.update_one(
        query,
        {"$set": set_fields, "$setOnInsert": set_on_insert},
        upsert=True,
    )
    is_new = result.upserted_id is not None
    alert_oid: Optional[ObjectId] = result.upserted_id
    if not is_new:
        doc = get_medical_db().alerts.find_one(query, projection={"_id": 1})
        alert_oid = doc["_id"] if doc else None
    if is_new and alert_oid:
        write_alert_event(
            medical_alert_id=str(alert_oid),
            event_type="alert_created",
            actor_user_id_auth=device_id,
            actor_role="system",
            payload={
                "alert_source": "near_threshold",
                "severity_level": SEVERITY_WARNING,
                "metric": metric,
                "operator": operator,
                "value": condition["value"],
                "threshold": condition["threshold"],
            },
        )
    return is_new, alert_oid


def resolve_near_threshold_alert(device_id: str, metric: str) -> None:
    """Resolve near-threshold WARNING when value returns to a comfortable range."""
    get_medical_db().alerts.update_many(
        {
            "device_id": device_id,
            "metric": metric,
            "alert_source": "near_threshold",
            "status": "OPEN",
        },
        {"$set": {
            "status": "RESOLVED",
            "resolved_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }},
    )


def upsert_ml_warning_alert(
    device_id: str,
    measurement: Dict[str, Any],
    ml_result: Dict[str, Any],
) -> Tuple[bool, Optional[ObjectId]]:
    """Persist an OPEN WARNING alert for ML warning level (non-critical anomaly)."""
    now = datetime.now(timezone.utc)
    measured_at = measurement.get("measured_at")
    if not isinstance(measured_at, datetime):
        measured_at = now
    measurement_id = measurement.get("_id")
    query = {
        "device_id": device_id,
        "alert_source": "ml",
        "metric": "ml_anomaly",
        "operator": "model",
        "severity_level": SEVERITY_WARNING,
        "status": "OPEN",
    }
    set_fields = {
        "latest_value": ml_result.get("ml_score"),
        "last_breach_at": measured_at,
        "updated_at": now,
        "ml_severity": "warning",
        "ml_urgency": ml_result.get("ml_urgency", "routine"),
        "dossier_summary": ml_result.get("ml_recommended_action") or "Anomalie ML — surveillance recommandée",
        "doctor_status": "PENDING",
    }
    if measurement_id is not None:
        set_fields["measurement_id"] = measurement_id
    set_on_insert = {
        "device_id": device_id,
        "metric": "ml_anomaly",
        "operator": "model",
        "status": "OPEN",
        "alert_source": "ml",
        "severity_level": SEVERITY_WARNING,
        "doctor_status": "PENDING",
        "created_at": now,
        "first_breach_at": measured_at,
        "ml_severity": "warning",
        **({"first_measurement_id": measurement_id} if measurement_id is not None else {}),
    }
    pseudo = get_patient_pseudo_id_for_device(device_id)
    if pseudo:
        set_fields["patient_pseudo_id"] = pseudo
        set_on_insert["patient_pseudo_id"] = pseudo
    result = get_medical_db().alerts.update_one(
        query,
        {"$set": set_fields, "$setOnInsert": set_on_insert},
        upsert=True,
    )
    is_new = result.upserted_id is not None
    alert_oid: Optional[ObjectId] = result.upserted_id
    if not is_new:
        doc = get_medical_db().alerts.find_one(query, projection={"_id": 1})
        alert_oid = doc["_id"] if doc else None
    return is_new, alert_oid


def upsert_open_alert_from_ml_critical(
    device_id: str,
    measurement: Dict[str, Any],
    ml_result: Dict[str, Any],
    ml_anomaly_id: Any,
) -> Tuple[bool, Optional[ObjectId]]:
    """Create OPEN CRITICAL alert when ML detects critical anomaly."""
    now = datetime.now(timezone.utc)
    measured_at = measurement.get("measured_at")
    if not isinstance(measured_at, datetime):
        measured_at = now
    measurement_id = measurement.get("_id")
    ml_urgency = str(ml_result.get("ml_urgency") or "routine")
    severity_level = SEVERITY_URGENCY if ml_urgency == "immediate" else SEVERITY_CRITICAL
    query = {
        "device_id": device_id,
        "alert_source": "ml",
        "ml_anomaly_id": ml_anomaly_id,
        "status": "OPEN",
    }
    set_fields = {
        "metric": "ml_anomaly",
        "operator": "model",
        "latest_value": ml_result.get("ml_score"),
        "last_breach_at": measured_at,
        "updated_at": now,
        "ml_severity": "critical",
        "ml_urgency": ml_urgency,
        "severity_level": severity_level,
        "dossier_summary": ml_result.get("ml_recommended_action") or "Anomalie ML critique",
        "doctor_status": "PENDING",
    }
    if measurement_id is not None:
        set_fields["measurement_id"] = measurement_id
    set_on_insert = {
        "device_id": device_id,
        "metric": "ml_anomaly",
        "operator": "model",
        "status": "OPEN",
        "alert_source": "ml",
        "ml_anomaly_id": ml_anomaly_id,
        "severity_level": severity_level,
        "doctor_status": "PENDING",
        "created_at": now,
        "first_breach_at": measured_at,
        "ml_severity": "critical",
        **({"first_measurement_id": measurement_id} if measurement_id is not None else {}),
    }
    pseudo = get_patient_pseudo_id_for_device(device_id)
    if pseudo:
        set_fields["patient_pseudo_id"] = pseudo
        set_on_insert["patient_pseudo_id"] = pseudo
    result = get_medical_db().alerts.update_one(
        query,
        {"$set": set_fields, "$setOnInsert": set_on_insert},
        upsert=True,
    )
    is_new = result.upserted_id is not None
    alert_oid: Optional[ObjectId] = result.upserted_id
    if not is_new:
        doc = get_medical_db().alerts.find_one(query, projection={"_id": 1})
        alert_oid = doc["_id"] if doc else None
    return is_new, alert_oid


def ensure_threshold_ml_anomaly_for_alert(
    *,
    device_id: str,
    measurement: Dict[str, Any],
    breach: Dict[str, Any],
    threshold_config: Dict[str, Any],
    alert_oid: Optional[ObjectId],
) -> None:
    """
    Insère une ligne ml_anomalies (feedback médecin + réentraînement) et lie l'alerte seuil.
    Idempotent si l'alerte a déjà ml_anomaly_id.
    """
    if alert_oid is None:
        return
    db = get_medical_db()
    try:
        existing = db.alerts.find_one({"_id": alert_oid}, projection={"ml_anomaly_id": 1})
        if existing and existing.get("ml_anomaly_id"):
            return
    except PyMongoError:
        return

    from app.ml import engine as ml_module

    patient_id = get_patient_id_from_device(device_id)
    meas_id = measurement.get("_id")
    event_doc = ml_module.build_threshold_anomaly_document(
        device_id=device_id,
        user_id_auth=patient_id,
        measurement_id=meas_id,
        measurement=measurement,
        breach=breach,
        rule_scope=str(threshold_config.get("scope") or "builtin_default"),
    )
    try:
        ins = db.ml_anomalies.insert_one(event_doc)
        anomaly_oid = ins.inserted_id
        db.alerts.update_one(
            {"_id": alert_oid},
            {"$set": {"ml_anomaly_id": anomaly_oid, "updated_at": datetime.now(timezone.utc)}},
        )
        if meas_id is not None:
            db.measurements.update_one(
                {"_id": meas_id},
                {"$set": {
                    "ml_anomaly_id": anomaly_oid,
                    "ml_anomaly_status": "pending",
                }},
            )
    except PyMongoError as e:
        logger.warning("ensure_threshold_ml_anomaly_for_alert failed: %s", e)


def create_manual_alert(
    device_id: str,
    patient_user_id_auth: str,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a manual alert triggered by the patient via the alert button.
    Returns {"created": bool, "reason": str, "alert_id": str|None}.
    Anti-spam: cooldown of MANUAL_ALERT_COOLDOWN_SECONDS and max MANUAL_ALERT_MAX_PER_HOUR per hour.
    """
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    medical_db = get_medical_db()

    # Rate-limit check: last manual alert from this device
    cutoff_cooldown = now - timedelta(seconds=MANUAL_ALERT_COOLDOWN_SECONDS)
    recent = medical_db.alerts.find_one(
        {"device_id": device_id, "alert_source": "manual", "created_at": {"$gte": cutoff_cooldown}},
        sort=[("created_at", -1)],
    )
    if recent:
        wait_s = int((recent["created_at"].replace(tzinfo=timezone.utc) - cutoff_cooldown).total_seconds())
        return {"created": False, "reason": f"cooldown", "wait_seconds": max(0, wait_s), "alert_id": None}

    # Hourly cap
    cutoff_hour = now - timedelta(hours=1)
    count_hour = medical_db.alerts.count_documents(
        {"device_id": device_id, "alert_source": "manual", "created_at": {"$gte": cutoff_hour}}
    )
    if count_hour >= MANUAL_ALERT_MAX_PER_HOUR:
        return {"created": False, "reason": "hourly_limit", "wait_seconds": None, "alert_id": None}

    doc: Dict[str, Any] = {
        "device_id": device_id,
        "metric": "manual",
        "operator": "manual",
        "status": "OPEN",
        "alert_source": "manual",
        "severity_level": severity_for_manual_alert(),
        "doctor_status": "PENDING",
        "created_at": now,
        "updated_at": now,
        "triggered_at": now,
        "patient_user_id_auth": patient_user_id_auth,
    }
    if message:
        doc["patient_message"] = message[:500]

    pseudo = get_patient_pseudo_id_for_device(device_id)
    if pseudo:
        doc["patient_pseudo_id"] = pseudo

    result = medical_db.alerts.insert_one(doc)
    alert_id = str(result.inserted_id)
    write_alert_event(
        medical_alert_id=alert_id,
        event_type="patient_manual_trigger",
        actor_user_id_auth=patient_user_id_auth,
        actor_role="patient",
        payload={"device_id": device_id, "message": message or ""},
    )
    return {"created": True, "reason": "ok", "wait_seconds": None, "alert_id": alert_id}


def resolve_metric_alert(device_id: str, metric: str):
    """Resolve open alerts for a metric once value is back in-range."""
    get_medical_db().alerts.update_many(
        {"device_id": device_id, "metric": metric, "status": "OPEN"},
        {"$set": {"status": "RESOLVED", "resolved_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}}
    )


# Statuts médecin qui retirent l'alerte de la file « ouvertes » (rétrocompat : status encore OPEN en base).
_DOCTOR_TRIAGE_DONE = frozenset(
    {"VALIDATED", "REJECTED", "validated", "rejected"}
)


def open_alert_query_requires_doctor_triage() -> Dict[str, Any]:
    """Fragment MongoDB : alerte OPEN encore à traiter côté médecin."""
    return {"doctor_status": {"$nin": list(_DOCTOR_TRIAGE_DONE)}}


def device_has_actionable_open_alert(device_id: Optional[str]) -> bool:
    """True si une alerte OPEN nécessite encore une action médecin (file d'attente)."""
    if not device_id:
        return False
    try:
        doc = get_medical_db().alerts.find_one(
            {"device_id": device_id, "status": "OPEN", **open_alert_query_requires_doctor_triage()},
            projection={"_id": 1},
        )
        return doc is not None
    except PyMongoError:
        return False


def _record_threshold_breach_event(
    device_id: str,
    measurement_id: Any,
    breach: Dict[str, Any],
    threshold_config: Dict[str, Any],
    *,
    new_alert: bool,
) -> None:
    """Audit row when a durable threshold breach opens a new OPEN alert."""
    doc: Dict[str, Any] = {
        "device_id": device_id,
        "metric": breach["metric"],
        "operator": breach["operator"],
        "value": breach["value"],
        "threshold": breach["threshold"],
        "rule_scope": threshold_config.get("scope"),
        "pathology_context": threshold_config.get("pathology"),
        "applied_thresholds": threshold_config.get("thresholds"),
        "new_alert_opened": new_alert,
        "created_at": datetime.now(timezone.utc),
    }
    rid = threshold_config.get("rule_id")
    if rid is not None:
        doc["alert_thresholds_rule_id"] = rid
    if measurement_id is not None:
        doc["measurement_id"] = measurement_id
    get_medical_db().threshold_breach_events.insert_one(doc)


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
    near_conditions = compute_near_threshold_conditions(measurement, thresholds)
    near_metrics = {c["metric"] for c in near_conditions}

    for metric in ("heart_rate", "spo2", "temperature"):
        if metric not in breached_metrics:
            resolve_metric_alert(device_id, metric)
        if metric not in near_metrics:
            resolve_near_threshold_alert(device_id, metric)

    for condition in near_conditions:
        if condition["metric"] not in breached_metrics:
            upsert_near_threshold_alert(
                device_id, condition, threshold_config, measured_at,
                measurement_id=measurement.get("_id"),
            )

    for breach in breaches:
        if has_consecutive_breach(device_id, breach, threshold_config["consecutive_breaches"]):
            is_new, alert_oid = upsert_open_alert(
                device_id, breach, threshold_config, measured_at,
                measurement_id=measurement.get("_id"),
            )
            ensure_threshold_ml_anomaly_for_alert(
                device_id=device_id,
                measurement=measurement,
                breach=breach,
                threshold_config=threshold_config,
                alert_oid=alert_oid,
            )
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
                    _record_threshold_breach_event(
                        device_id=device_id,
                        measurement_id=measurement.get("_id"),
                        breach=breach,
                        threshold_config=threshold_config,
                        new_alert=True,
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("threshold_breach_events insert failed: %s", e)
                try:
                    from app.services.ml_retrain_scheduler import schedule_retrain_after_threshold_breach
                    schedule_retrain_after_threshold_breach(device_id, breach["metric"])
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("schedule ML retrain after threshold failed: %s", e)
                try:
                    from app.services.invitation_service import send_alert_emails_for_new_alert
                    from app.services.webpush_service import send_alert_push_notifications
                    from app.services.user_service import get_patient_id_from_device, get_user_profile
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
                    send_alert_push_notifications(
                        device_id=device_id,
                        metric=breach["metric"],
                        operator=breach["operator"],
                        value=breach["value"],
                        threshold=breach["threshold"],
                        patient_name=patient_name,
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("Failed to send alert notifications for device %s: %s", device_id, e)

    return durable
