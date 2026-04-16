"""
Full ML model retrain (Isolation Forest) from measurements + doctor feedback on ml_anomalies.

- rejected (FP) : sur-échantillonnés comme inliers IF uniquement.
- validated (TP) : banque d’exemplaires pour l’inférence (pas dans fit IF).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from pymongo.errors import PyMongoError

import ml_module
from database import get_medical_db

logger = logging.getLogger(__name__)


def do_ml_retrain(
    days: int = 30,
    contamination: float = 0.05,
    n_estimators: int = 150,
    *,
    trigger: str = "manual",
    trigger_device_id: Optional[str] = None,
    trigger_metric: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Retrain ML model. Persists version to ml_model_versions with optional trigger metadata.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    try:
        measurements = list(get_medical_db().measurements.find(
            {"status": "VALID", "measured_at": {"$gte": cutoff}},
            projection={"_id": 0, "heart_rate": 1, "spo2": 1, "temperature": 1, "signal_quality": 1, "status": 1}
        ).limit(50000))
    except PyMongoError:
        raise
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
    meta = ml_module.train_model(
        measurements=measurements,
        validated_anomalies=validated_anomalies,
        contamination=contamination,
        n_estimators=n_estimators,
    )
    version_doc: Dict[str, Any] = {
        "version": meta["version"],
        "trained_at": meta["trained_at"],
        "n_samples": meta["n_samples"],
        "contamination": meta["contamination"],
        "n_estimators": meta["n_estimators"],
        "created_at": datetime.now(timezone.utc),
        "trigger": trigger,
    }
    if trigger_device_id:
        version_doc["trigger_device_id"] = trigger_device_id
    if trigger_metric:
        version_doc["trigger_metric"] = trigger_metric
    try:
        get_medical_db().ml_model_versions.insert_one(version_doc)
    except PyMongoError as e:
        logger.warning("ml_model_versions insert failed: %s", e)
    return meta
