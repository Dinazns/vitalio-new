"""
Global security audit trail (append-only) in Vitalio_Identity.audit_log.
Complements alert_events (medical alerts) and audit_links (linkage operations).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo.errors import PyMongoError

from app.database import get_identity_db
from app.services.user_service import datetime_to_iso_utc

logger = logging.getLogger(__name__)

# Allowed actions for validation / documentation
AUDIT_ACTIONS = frozenset({"read", "create", "update", "delete", "export"})


def _client_ip(req) -> Optional[str]:
    if req is None:
        return None
    forwarded = (req.headers.get("X-Forwarded-For") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()[:128]
    remote = getattr(req, "remote_addr", None)
    return str(remote)[:128] if remote else None


def _user_agent(req) -> Optional[str]:
    if req is None:
        return None
    ua = (req.headers.get("User-Agent") or "").strip()
    return ua[:512] if ua else None


def _sanitize_details(details: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(details, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, value in details.items():
        if value is None:
            continue
        k = str(key)[:64]
        if isinstance(value, (str, int, float, bool)):
            out[k] = value if not isinstance(value, str) else value[:2000]
        elif isinstance(value, dict):
            out[k] = {str(sk)[:64]: sv for sk, sv in value.items() if isinstance(sv, (str, int, float, bool))}
    return out


def log_audit_event(
    event_type: str,
    actor_user_id_auth: str,
    actor_role: str,
    resource_type: str,
    resource_id: str,
    action: str,
    details: Optional[Dict[str, Any]] = None,
    request=None,
) -> None:
    """Append one immutable row to audit_log. Never raises to callers."""
    if action not in AUDIT_ACTIONS:
        logger.warning("audit_log skipped: invalid action %r", action)
        return
    try:
        doc: Dict[str, Any] = {
            "event_type": str(event_type or "")[:128],
            "actor_user_id_auth": str(actor_user_id_auth or "")[:256],
            "actor_role": str(actor_role or "unknown")[:64],
            "resource_type": str(resource_type or "")[:64],
            "resource_id": str(resource_id or "")[:256],
            "action": action,
            "details": _sanitize_details(details),
            "created_at": datetime.now(timezone.utc),
        }
        ip = _client_ip(request)
        ua = _user_agent(request)
        if ip:
            doc["ip_address"] = ip
        if ua:
            doc["user_agent"] = ua
        get_identity_db().audit_log.insert_one(doc)
    except Exception as exc:
        logger.warning("audit_log insert failed (event_type=%s): %s", event_type, exc)


def _serialize_audit_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    oid = out.pop("_id", None)
    if oid is not None:
        out["id"] = str(oid)
    created = out.get("created_at")
    if isinstance(created, datetime):
        out["created_at"] = datetime_to_iso_utc(created)
    return out


def query_audit_log(
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    event_type: Optional[str] = None,
    actor_user_id_auth: Optional[str] = None,
    resource_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> Tuple[int, List[Dict[str, Any]]]:
    """Paginated read of audit_log (newest first)."""
    page = max(1, int(page or 1))
    page_size = min(max(1, int(page_size or 50)), 100)
    query: Dict[str, Any] = {}
    if from_dt or to_dt:
        created: Dict[str, Any] = {}
        if from_dt:
            created["$gte"] = from_dt
        if to_dt:
            created["$lte"] = to_dt
        query["created_at"] = created
    if event_type:
        query["event_type"] = str(event_type).strip()
    if actor_user_id_auth:
        query["actor_user_id_auth"] = str(actor_user_id_auth).strip()
    if resource_id:
        query["resource_id"] = str(resource_id).strip()

    coll = get_identity_db().audit_log
    try:
        total = coll.count_documents(query)
        cursor = (
            coll.find(query)
            .sort("created_at", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        events = [_serialize_audit_doc(d) for d in cursor]
        return total, events
    except PyMongoError as exc:
        logger.warning("audit_log query failed: %s", exc)
        return 0, []
