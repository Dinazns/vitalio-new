"""Alert API payload helpers."""
from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId

from app.services.severity_level import resolve_alert_severity_level
from app.services.user_service import get_address_dict_from_profile, get_user_profile, datetime_to_iso_utc

def sanitize_alert_dict(d: Dict[str, Any]) -> None:
    """Convert any remaining ObjectId / non-serialisable values to strings in-place."""
    for key, val in list(d.items()):
        if isinstance(val, ObjectId):
            d[key] = str(val)


def finalize_alert_api_payload(
    raw_alert: Dict[str, Any],
    out: Dict[str, Any],
    patient_user_id_auth: Optional[str],
    *,
    include_patient_address: bool,
) -> None:
    if include_patient_address and patient_user_id_auth:
        addr = get_address_dict_from_profile(get_user_profile(patient_user_id_auth))
        if addr:
            out["patient_address"] = addr
    out["caregiver_intervened"] = bool(
        raw_alert.get("caregiver_resolution_at") or raw_alert.get("caregiver_resolution_comment")
    )
    esc = raw_alert.get("emergency_escalations") or []
    serialized = []
    if isinstance(esc, list):
        for e in esc:
            if not isinstance(e, dict):
                continue
            item = dict(e)
            at = item.get("at")
            if isinstance(at, datetime):
                item["at"] = datetime_to_iso_utc(at)
            serialized.append(item)
    out["emergency_escalations"] = serialized
    out["severity_level"] = resolve_alert_severity_level(raw_alert)
