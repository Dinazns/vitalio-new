"""
Pseudonymisation: patient_pseudo_id in Identity, referenced from Medical collections.
Medical data never stores Auth0 user_id_auth; linkage is via Identity only.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from pymongo.errors import PyMongoError

from app.database import get_identity_db

logger = logging.getLogger(__name__)


def ensure_patient_pseudo_id(user_id_auth: str) -> Optional[str]:
    """Create or return stable UUID pseudo-id for a patient. Returns None if user_id_auth empty."""
    uid = str(user_id_auth or "").strip()
    if not uid:
        return None
    try:
        identity = get_identity_db()
        doc = identity.users.find_one(
            {"user_id_auth": uid},
            projection={"patient_pseudo_id": 1},
        )
        if doc and doc.get("patient_pseudo_id"):
            return str(doc["patient_pseudo_id"])
        pseudo = str(uuid.uuid4())
        identity.users.update_one(
            {"user_id_auth": uid},
            {"$set": {"patient_pseudo_id": pseudo}},
            upsert=False,
        )
        return pseudo
    except PyMongoError as exc:
        logger.warning("ensure_patient_pseudo_id failed for %s: %s", uid, exc)
        return None


def get_patient_pseudo_id(user_id_auth: str) -> Optional[str]:
    """Return existing pseudo-id without creating one."""
    uid = str(user_id_auth or "").strip()
    if not uid:
        return None
    try:
        doc = get_identity_db().users.find_one(
            {"user_id_auth": uid},
            projection={"patient_pseudo_id": 1},
        )
        if doc and doc.get("patient_pseudo_id"):
            return str(doc["patient_pseudo_id"])
    except PyMongoError as exc:
        logger.warning("get_patient_pseudo_id failed for %s: %s", uid, exc)
    return None


def get_patient_pseudo_id_for_device(device_id: str) -> Optional[str]:
    """Resolve pseudo-id from device_id via Identity.users_devices."""
    from app.services.user_service import get_patient_id_from_device

    patient_uid = get_patient_id_from_device(device_id)
    if not patient_uid:
        return None
    existing = get_patient_pseudo_id(patient_uid)
    if existing:
        return existing
    return ensure_patient_pseudo_id(patient_uid)


def attach_patient_pseudo_to_doc(doc: Dict[str, Any], *, device_id: Optional[str] = None, user_id_auth: Optional[str] = None) -> Dict[str, Any]:
    """Add patient_pseudo_id to a medical document when resolvable."""
    pseudo = None
    if user_id_auth:
        pseudo = get_patient_pseudo_id(user_id_auth) or ensure_patient_pseudo_id(user_id_auth)
    elif device_id:
        pseudo = get_patient_pseudo_id_for_device(device_id)
    if pseudo:
        doc["patient_pseudo_id"] = pseudo
    return doc
