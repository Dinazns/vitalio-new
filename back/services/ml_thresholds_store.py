"""
Persist ML score thresholds (normal_max, warning_max) in Vitalio_Medical.ml_thresholds.

Singleton document _id == "current". Loaded after DB init; API PUT updates DB + in-memory module.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from pymongo.errors import PyMongoError

import ml_module
from ml_module import DEFAULT_ML_THRESHOLDS
from database import get_medical_db

logger = logging.getLogger(__name__)

ML_THRESHOLDS_DOC_ID = "current"


def load_ml_thresholds_from_db() -> bool:
    """Apply stored thresholds to ml_module. Returns True if a document was found."""
    try:
        doc = get_medical_db().ml_thresholds.find_one({"_id": ML_THRESHOLDS_DOC_ID})
    except PyMongoError as e:
        logger.warning("ml_thresholds read failed: %s", e)
        return False
    if not doc:
        return False
    nm, wm = doc.get("normal_max"), doc.get("warning_max")
    try:
        ml_module.configure_thresholds(
            normal_max=float(nm) if nm is not None else None,
            warning_max=float(wm) if wm is not None else None,
        )
    except (TypeError, ValueError):
        return False
    logger.info("ML thresholds loaded from MongoDB (normal_max=%s warning_max=%s)", nm, wm)
    return True


def save_ml_thresholds_to_db() -> Dict[str, Any]:
    """Persist current ml_module thresholds (call after configure_thresholds)."""
    info = ml_module.get_model_info()
    thresholds = info.get("thresholds") or {}
    now = datetime.now(timezone.utc)
    doc = {
        "_id": ML_THRESHOLDS_DOC_ID,
        "normal_max": float(thresholds.get("normal_max", DEFAULT_ML_THRESHOLDS["normal_max"])),
        "warning_max": float(thresholds.get("warning_max", DEFAULT_ML_THRESHOLDS["warning_max"])),
        "updated_at": now,
    }
    try:
        get_medical_db().ml_thresholds.replace_one({"_id": ML_THRESHOLDS_DOC_ID}, doc, upsert=True)
    except PyMongoError as e:
        logger.warning("ml_thresholds write failed: %s", e)
        raise
    return doc
