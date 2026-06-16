"""Device lifecycle constants and users_devices field builders (no DB/auth imports)."""
from datetime import datetime
from typing import Any, Dict, Optional

DEVICE_STATUS_ACTIVE = "active"
DEVICE_STATUS_SUSPENDED = "suspended"


def active_device_assignment_fields(
    user_id_auth: str,
    device_id: str,
    *,
    assigned_by: Optional[str] = None,
    assigned_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Fields persisted on users_devices when linking a device to a patient."""
    fields: Dict[str, Any] = {
        "user_id_auth": user_id_auth,
        "device_id": device_id,
        "status": DEVICE_STATUS_ACTIVE,
    }
    if assigned_by is not None:
        fields["assigned_by"] = assigned_by
    if assigned_at is not None:
        fields["assigned_at"] = assigned_at
    return fields
