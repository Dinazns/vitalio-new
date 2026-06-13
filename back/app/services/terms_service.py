"""
Terms of use acceptance tracking for VitalIO users.
Update CURRENT_TERMS_VERSION when conditions d'utilisation change.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pymongo.errors import PyMongoError

from app.database import get_identity_db
from app.exceptions import DatabaseError
from app.services.user_service import datetime_to_iso_utc

# Bump this date when /conditions-utilisation content changes materially.
CURRENT_TERMS_VERSION = "2026-06-08"


def _serialize_accepted_at(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return datetime_to_iso_utc(value)
    return str(value)


def needs_terms_acceptance(
    terms_accepted_at: Any,
    terms_version: Optional[str],
) -> bool:
    if not terms_accepted_at:
        return True
    return str(terms_version or "").strip() != CURRENT_TERMS_VERSION


def get_terms_status(user_id_auth: str) -> Dict[str, Any]:
    try:
        doc = get_identity_db().users.find_one(
            {"user_id_auth": user_id_auth},
            projection={"terms_accepted_at": 1, "terms_version": 1, "_id": 0},
        ) or {}
    except PyMongoError as e:
        raise DatabaseError({
            "code": "terms_query_error",
            "message": f"Failed to query terms status: {str(e)}",
        }, 500)

    accepted_at = doc.get("terms_accepted_at")
    accepted_version = doc.get("terms_version")
    return {
        "current_version": CURRENT_TERMS_VERSION,
        "terms_accepted_at": _serialize_accepted_at(accepted_at),
        "terms_version": accepted_version,
        "needs_acceptance": needs_terms_acceptance(accepted_at, accepted_version),
    }


def accept_terms(user_id_auth: str) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    try:
        get_identity_db().users.update_one(
            {"user_id_auth": user_id_auth},
            {
                "$set": {
                    "terms_accepted_at": now,
                    "terms_version": CURRENT_TERMS_VERSION,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "user_id_auth": user_id_auth,
                    "created_at": now,
                },
            },
            upsert=True,
        )
    except PyMongoError as e:
        raise DatabaseError({
            "code": "terms_accept_error",
            "message": f"Failed to record terms acceptance: {str(e)}",
        }, 500)

    return {
        "current_version": CURRENT_TERMS_VERSION,
        "terms_accepted_at": datetime_to_iso_utc(now),
        "terms_version": CURRENT_TERMS_VERSION,
        "needs_acceptance": False,
    }
