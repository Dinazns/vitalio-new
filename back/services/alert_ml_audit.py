"""
When a doctor validates an ML anomaly, ensure an audit row exists in medical_db.alerts.

Threshold alerts keep using upsert on (device_id, metric, operator, status=OPEN) with clinical metrics.
ML audit rows use metric='ml_anomaly', operator='model' (no collision). Optional fields:

- alert_source: "threshold" | "ml" | "both"
- measurement_id, ml_anomaly_id, user_id_auth, device_id
- ml_severity, dossier_summary (short clinical text)
- emergency_escalations: [{ at, by, type }] (via PATCH médecin)
- caregiver_resolution_*, doctor_status, validated_* - shared with aidant workflow
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from bson import ObjectId
from pymongo.errors import PyMongoError

from database import get_medical_db

logger = logging.getLogger(__name__)

ML_METRIC = "ml_anomaly"
ML_OPERATOR = "model"


def _summary_from_anomaly(anomaly_doc: Dict[str, Any]) -> str:
    parts = []
    action = anomaly_doc.get("recommended_action")
    if action:
        parts.append(str(action).strip()[:400])
    score = anomaly_doc.get("anomaly_score")
    if isinstance(score, (int, float)):
        parts.append(f"Score ML {float(score):.3f}")
    if not parts:
        return "Anomalie ML validée par le médecin"
    return " - ".join(parts)[:500]


def create_or_merge_alert_for_validated_ml(
    anomaly_doc: Dict[str, Any],
    ml_anomaly_oid: ObjectId,
    doctor_user_id_auth: str,
) -> Tuple[Optional[ObjectId], str]:
    """
    Create or merge a medical alerts document for a validated ML anomaly.

    Returns (alert_object_id_or_none, mode) where mode is 'merged', 'inserted', or 'existing'.
    """
    db = get_medical_db()
    now = datetime.now(timezone.utc)
    device_id = anomaly_doc.get("device_id")
    user_id_auth = anomaly_doc.get("user_id_auth")
    measurement_id = anomaly_doc.get("measurement_id")

    existing_ml = db.alerts.find_one({"ml_anomaly_id": ml_anomaly_oid})
    if existing_ml and existing_ml.get("_id"):
        return existing_ml["_id"], "existing"

    summary = _summary_from_anomaly(anomaly_doc)
    severity = str(anomaly_doc.get("anomaly_level") or "critical")

    merged_id: Optional[ObjectId] = None
    if measurement_id:
        try:
            merged = db.alerts.find_one({
                "device_id": device_id,
                "status": "OPEN",
                "measurement_id": measurement_id,
                "metric": {"$ne": ML_METRIC},
            })
            if merged and merged.get("_id"):
                merged_id = merged["_id"]
        except PyMongoError:
            pass

    if merged_id:
        try:
            db.alerts.update_one(
                {"_id": merged_id},
                {"$set": {
                    "alert_source": "both",
                    "ml_anomaly_id": ml_anomaly_oid,
                    "ml_severity": severity,
                    "dossier_summary": summary,
                    "doctor_status": "VALIDATED",
                    "validated_by": doctor_user_id_auth,
                    "validated_at": now,
                    "updated_at": now,
                }},
            )
            return merged_id, "merged"
        except PyMongoError as e:
            logger.warning("Failed to merge ML into threshold alert: %s", e)

    measured_at = anomaly_doc.get("measured_at") or now
    doc: Dict[str, Any] = {
        "device_id": device_id,
        "metric": ML_METRIC,
        "operator": ML_OPERATOR,
        "status": "OPEN",
        "alert_source": "ml",
        "ml_anomaly_id": ml_anomaly_oid,
        "measurement_id": measurement_id,
        "user_id_auth": user_id_auth,
        "ml_severity": severity,
        "dossier_summary": summary,
        "latest_value": anomaly_doc.get("anomaly_score"),
        "threshold": None,
        "doctor_status": "VALIDATED",
        "validated_by": doctor_user_id_auth,
        "validated_at": now,
        "created_at": now,
        "first_breach_at": measured_at,
        "last_breach_at": measured_at,
        "updated_at": now,
        "consecutive_required": None,
        "rule_scope": "ml_model",
    }
    try:
        ins = db.alerts.insert_one(doc)
        return ins.inserted_id, "inserted"
    except PyMongoError as e:
        logger.warning("Failed to insert ML audit alert: %s", e)
        return None, "error"
