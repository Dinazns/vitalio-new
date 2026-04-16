"""
Measurement queries and validation.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from pymongo.errors import PyMongoError

from database import get_medical_db, get_identity_db
from exceptions import DatabaseError
from services.user_service import get_device_id, get_user_profile, get_user_db_id, datetime_to_iso_utc
from services.alert_service import device_has_actionable_open_alert


def get_latest_device_measurement(device_id: str) -> Optional[Dict[str, Any]]:
    """Return latest measurement document for one device."""
    try:
        doc = get_medical_db().measurements.find_one(
            {"device_id": device_id},
            sort=[("measured_at", -1)],
            projection={"_id": 0}
        )
        return doc
    except PyMongoError as e:
        raise DatabaseError({
            "code": "latest_measurement_query_error",
            "message": f"Failed to query latest measurement: {str(e)}"
        }, 500)


def compute_alert_indicator(measurement: Optional[Dict[str, Any]]) -> bool:
    """Compute whether measurement should raise alert indicator on doctor dashboard."""
    if not measurement:
        return False
    if measurement.get("status") == "INVALID":
        return True
    hr = measurement.get("heart_rate")
    spo2 = measurement.get("spo2")
    temp = measurement.get("temperature")
    if hr is not None and (hr < 50 or hr > 120):
        return True
    if spo2 is not None and spo2 < 92:
        return True
    if temp is not None and (temp < 35.5 or temp > 38.0):
        return True
    return False


def query_patient_measurements(device_id: str, days: int, limit: int = 500) -> List[Dict[str, Any]]:
    """Query patient measurements constrained by lookback days and limit."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    try:
        cursor = get_medical_db().measurements.find(
            {"device_id": device_id, "measured_at": {"$gte": cutoff}},
            projection={"_id": 0}
        ).sort("measured_at", -1).limit(max(limit, 1))

        rows = []
        for doc in cursor:
            measured_at = doc.get("measured_at")
            timestamp = datetime_to_iso_utc(measured_at) if isinstance(measured_at, datetime) else str(measured_at)
            rows.append({
                "timestamp": timestamp,
                "heart_rate": doc.get("heart_rate"),
                "spo2": doc.get("spo2"),
                "temperature": doc.get("temperature"),
                "signal_quality": doc.get("signal_quality"),
                "status": doc.get("status"),
                "source": doc.get("source", "device"),
            })
        return rows
    except PyMongoError as e:
        raise DatabaseError({
            "code": "patient_measurements_query_error",
            "message": f"Failed to query patient measurements: {str(e)}"
        }, 500)


def count_patient_measurements_total(device_ids: List[str]) -> int:
    """Count all measurements for the given devices (no time or limit filter)."""
    if not device_ids:
        return 0
    try:
        return get_medical_db().measurements.count_documents({"device_id": {"$in": device_ids}})
    except PyMongoError:
        return 0


def query_patient_measurements_for_devices(
    device_ids: List[str],
    days: int,
    limit: int = 2000,
) -> List[Dict[str, Any]]:
    """Query measurements for multiple patient devices."""
    if not device_ids:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    try:
        cursor = get_medical_db().measurements.find(
            {"device_id": {"$in": device_ids}, "measured_at": {"$gte": cutoff}},
            projection={"_id": 0}
        ).sort("measured_at", -1).limit(max(limit, 1))

        rows = []
        for doc in cursor:
            measured_at = doc.get("measured_at")
            timestamp = datetime_to_iso_utc(measured_at) if isinstance(measured_at, datetime) else str(measured_at)
            rows.append({
                "timestamp": timestamp,
                "measured_at": timestamp,
                "device_id": doc.get("device_id"),
                "heart_rate": doc.get("heart_rate"),
                "spo2": doc.get("spo2"),
                "temperature": doc.get("temperature"),
                "signal_quality": doc.get("signal_quality"),
                "status": doc.get("status"),
                "source": doc.get("source", "device"),
                "ml_score": doc.get("ml_score"),
                "ml_level": doc.get("ml_level"),
            })
        return rows
    except PyMongoError as e:
        raise DatabaseError({
            "code": "patient_measurements_query_error",
            "message": f"Failed to query patient measurements: {str(e)}"
        }, 500)


def query_patient_measurements_range(
    device_id: str,
    limit: int = 200,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """Query patient measurements by optional date range and limit."""
    query: Dict[str, Any] = {"device_id": device_id}
    if from_dt or to_dt:
        measured_at_query: Dict[str, Any] = {}
        if from_dt:
            measured_at_query["$gte"] = from_dt
        if to_dt:
            measured_at_query["$lte"] = to_dt
        query["measured_at"] = measured_at_query

    try:
        cursor = get_medical_db().measurements.find(
            query,
            projection={"_id": 0}
        ).sort("measured_at", -1).limit(min(max(limit, 1), 1000))

        rows = []
        for doc in cursor:
            measured_at = doc.get("measured_at")
            timestamp = datetime_to_iso_utc(measured_at) if isinstance(measured_at, datetime) else str(measured_at)
            rows.append({
                "timestamp": timestamp,
                "heart_rate": doc.get("heart_rate"),
                "spo2": doc.get("spo2"),
                "temperature": doc.get("temperature"),
                "signal_quality": doc.get("signal_quality"),
                "status": doc.get("status"),
                "source": doc.get("source", "device"),
            })
        return rows
    except PyMongoError as e:
        raise DatabaseError({
            "code": "patient_measurements_query_error",
            "message": f"Failed to query patient measurements: {str(e)}"
        }, 500)


def list_latest_doctor_feedback(patient_user_id_auth: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Return latest doctor feedback entries for one patient."""
    try:
        cursor = get_medical_db().doctor_feedback.find(
            {"patient_user_id_auth": patient_user_id_auth},
            projection={"_id": 0}
        ).sort("created_at", -1).limit(min(max(limit, 1), 50))

        feedbacks = []
        for doc in cursor:
            created_at = doc.get("created_at")
            doctor_id = doc.get("doctor_user_id_auth")
            doctor_profile = get_user_profile(doctor_id) if doctor_id else {}
            doctor_display_name = (
                doctor_profile.get("display_name") or doctor_profile.get("email") or doctor_id or ""
            )
            feedbacks.append({
                "patient_user_id_auth": doc.get("patient_user_id_auth"),
                "doctor_user_id_auth": doctor_id,
                "doctor_display_name": doctor_display_name,
                "message": doc.get("message"),
                "severity": doc.get("severity"),
                "status": doc.get("status"),
                "recommendation": doc.get("recommendation"),
                "created_at": datetime_to_iso_utc(created_at) if isinstance(created_at, datetime) else created_at,
            })
        return feedbacks
    except PyMongoError as e:
        raise DatabaseError({
            "code": "doctor_feedback_query_error",
            "message": f"Failed to query doctor feedback: {str(e)}"
        }, 500)


def build_assigned_patients_payload(
    patient_ids: List[str],
    *,
    doctor_queue_alert_badge: bool = False,
) -> List[Dict[str, Any]]:
    """Build patient cards (profile + latest measurements) for doctor/caregiver views."""
    patients = []
    for patient_user_id_auth in patient_ids:
        device_id = get_device_id(patient_user_id_auth)
        profile = get_user_profile(patient_user_id_auth)
        db_id = get_user_db_id(patient_user_id_auth)
        latest_measurement = get_latest_device_measurement(device_id) if device_id else None
        measured_at = latest_measurement.get("measured_at") if latest_measurement else None
        measured_at_iso = datetime_to_iso_utc(measured_at) if isinstance(measured_at, datetime) else None

        if doctor_queue_alert_badge:
            alert_flag = bool(device_id) and device_has_actionable_open_alert(device_id)
        else:
            alert_flag = compute_alert_indicator(latest_measurement)

        patients.append({
            "id": db_id or patient_user_id_auth,
            "patient_id": patient_user_id_auth,
            "display_name": profile.get("display_name") or profile.get("email") or patient_user_id_auth,
            "device_id": device_id,
            "last_measurement": {
                "timestamp": measured_at_iso,
                "spo2": latest_measurement.get("spo2") if latest_measurement else None,
                "heart_rate": latest_measurement.get("heart_rate") if latest_measurement else None,
                "temperature": latest_measurement.get("temperature") if latest_measurement else None,
                "status": latest_measurement.get("status") if latest_measurement else None,
            } if latest_measurement else None,
            "alert": alert_flag,
        })
    return patients


def build_trend_window(measurements: List[Dict[str, Any]], days: int) -> Dict[str, Any]:
    """Compute trend summary for one lookback window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    filtered = []
    for row in measurements:
        try:
            ts = datetime.fromisoformat(str(row.get("timestamp")).replace("Z", "+00:00"))
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
            if ts >= cutoff:
                filtered.append(row)
        except Exception:
            continue

    filtered_sorted = sorted(filtered, key=lambda row: row.get("timestamp", ""))
    if not filtered_sorted:
        return {
            "days": days,
            "count": 0,
            "averages": {"spo2": None, "heart_rate": None, "temperature": None},
            "delta": {"spo2": None, "heart_rate": None, "temperature": None},
            "series": []
        }

    def avg(key: str) -> Optional[float]:
        values = [row.get(key) for row in filtered_sorted if isinstance(row.get(key), (int, float))]
        if not values:
            return None
        return round(sum(values) / len(values), 2)

    first = filtered_sorted[0]
    last = filtered_sorted[-1]

    def compute_delta(key: str) -> Optional[float]:
        first_value = first.get(key)
        last_value = last.get(key)
        if not isinstance(first_value, (int, float)) or not isinstance(last_value, (int, float)):
            return None
        return round(last_value - first_value, 2)

    series = filtered_sorted[-120:]
    return {
        "days": days,
        "count": len(filtered_sorted),
        "averages": {"spo2": avg("spo2"), "heart_rate": avg("heart_rate"), "temperature": avg("temperature")},
        "delta": {"spo2": compute_delta("spo2"), "heart_rate": compute_delta("heart_rate"), "temperature": compute_delta("temperature")},
        "series": series
    }


def parse_measurement_timestamp(timestamp_value: Optional[str]) -> datetime:
    """Parse measurement timestamp with ISO fallback to current UTC time."""
    if not timestamp_value:
        return datetime.now(timezone.utc)
    try:
        normalized = timestamp_value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except Exception:
        return datetime.now(timezone.utc)


def validate_measurement_values(
    heart_rate: Any,
    spo2: Any,
    temperature: Any,
    signal_quality: Any = None,
    require_signal_quality: bool = False
) -> List[str]:
    """Validate measurement values and return reason codes for invalid fields."""
    reasons = []
    if heart_rate is None or heart_rate < 30 or heart_rate > 220:
        reasons.append("heart_rate_out_of_range")
    if spo2 is None or spo2 < 70 or spo2 > 100:
        reasons.append("spo2_out_of_range")
    if temperature is None or temperature < 34 or temperature > 42:
        reasons.append("temperature_out_of_range")
    if require_signal_quality or signal_quality is not None:
        if signal_quality is None or signal_quality < 50:
            reasons.append("low_signal_quality")
    return reasons


def normalize_patient_measurement_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize and validate payload sent by patient app."""
    required_fields = ["heart_rate", "spo2", "temperature"]
    missing = [field for field in required_fields if field not in payload]
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}")

    try:
        heart_rate = float(payload["heart_rate"])
        spo2 = float(payload["spo2"])
        temperature = float(payload["temperature"])
        signal_quality_raw = payload.get("signal_quality")
        signal_quality = float(signal_quality_raw) if signal_quality_raw is not None else None
    except (TypeError, ValueError):
        raise ValueError("heart_rate, spo2, temperature and signal_quality must be numeric")

    source = payload.get("source", "simulation")
    if source not in ("simulation", "device"):
        raise ValueError("source must be 'simulation' or 'device'")

    measured_at = parse_measurement_timestamp(payload.get("measured_at"))
    reasons = validate_measurement_values(
        heart_rate=heart_rate, spo2=spo2, temperature=temperature,
        signal_quality=signal_quality, require_signal_quality=False
    )

    return {
        "measured_at": measured_at,
        "heart_rate": heart_rate,
        "spo2": spo2,
        "temperature": temperature,
        "signal_quality": signal_quality,
        "source": source,
        "reasons": reasons,
        "status": "VALID" if not reasons else "INVALID"
    }


def validate_measurement_payload_mqtt(payload: dict) -> dict:
    """Validate IoT sensor payload for MQTT messages."""
    sensors = payload.get("sensors", {})
    max30102 = sensors.get("MAX30102", {})
    mlx90614 = sensors.get("MLX90614", {})
    hr = max30102.get("heart_rate")
    spo2 = max30102.get("spo2")
    temp = mlx90614.get("object_temp")
    signal_quality = payload.get("signal_quality")

    reasons = validate_measurement_values(
        heart_rate=hr, spo2=spo2, temperature=temp,
        signal_quality=signal_quality, require_signal_quality=True
    )
    status = "VALID" if not reasons else "INVALID"

    return {
        "status": status,
        "reasons": reasons,
        "validated_at": datetime.now(timezone.utc).isoformat()
    }
