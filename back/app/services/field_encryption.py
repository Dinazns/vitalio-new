"""
Application-level encryption for sensitive profile fields (Fernet).
Backward compatible: plaintext values without enc:v1: prefix are returned as-is.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app import config

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:v1:"

PROFILE_SCALAR_FIELDS = (
    "phone",
    "contact",
    "address_line1",
    "address_line2",
    "postal_code",
    "city",
    "country",
    "medical_history",
)

EMERGENCY_ENCRYPT_FIELDS = ("phone", "email")

_fernet = None
_warned_missing_key = False


def encryption_enabled() -> bool:
    key = getattr(config, "FIELD_ENCRYPTION_KEY", "") or ""
    return bool(str(key).strip())


def _get_fernet():
    global _fernet, _warned_missing_key
    if _fernet is not None:
        return _fernet
    if not encryption_enabled():
        if not _warned_missing_key:
            logger.warning("FIELD_ENCRYPTION_KEY not set; sensitive fields stored in plaintext")
            _warned_missing_key = True
        return None
    try:
        from cryptography.fernet import Fernet

        key = str(getattr(config, "FIELD_ENCRYPTION_KEY", "") or "").strip().encode("utf-8")
        _fernet = Fernet(key)
        return _fernet
    except Exception as exc:
        logger.error("Invalid FIELD_ENCRYPTION_KEY: %s", exc)
        return None


def encrypt_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    if text.startswith(ENC_PREFIX):
        return text
    f = _get_fernet()
    if f is None:
        return text
    token = f.encrypt(text.encode("utf-8")).decode("ascii")
    return f"{ENC_PREFIX}{token}"


def decrypt_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if not text.startswith(ENC_PREFIX):
        return text
    f = _get_fernet()
    if f is None:
        return text
    try:
        token = text[len(ENC_PREFIX) :].encode("ascii")
        return f.decrypt(token).decode("utf-8")
    except Exception as exc:
        logger.warning("Failed to decrypt field value: %s", exc)
        return None


def _encrypt_emergency_contact(ec: Any) -> Any:
    if not isinstance(ec, dict):
        return ec
    out = dict(ec)
    for field in EMERGENCY_ENCRYPT_FIELDS:
        if field in out and out[field]:
            out[field] = encrypt_value(str(out[field]))
    return out


def _decrypt_emergency_contact(ec: Any) -> Any:
    if not isinstance(ec, dict):
        return ec
    out = dict(ec)
    for field in EMERGENCY_ENCRYPT_FIELDS:
        if field in out and out[field]:
            out[field] = decrypt_value(str(out[field]))
    return out


def encrypt_profile_fields(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy with sensitive scalar fields encrypted for MongoDB storage."""
    if not doc:
        return doc
    out = dict(doc)
    for field in PROFILE_SCALAR_FIELDS:
        if field in out and out[field]:
            out[field] = encrypt_value(str(out[field]))
    if "emergency_contact" in out:
        out["emergency_contact"] = _encrypt_emergency_contact(out["emergency_contact"])
    return out


def decrypt_profile_fields(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a copy with sensitive fields decrypted for API responses."""
    if not doc:
        return {}
    out = dict(doc)
    for field in PROFILE_SCALAR_FIELDS:
        if field in out and out[field]:
            out[field] = decrypt_value(str(out[field]))
    if "emergency_contact" in out:
        out["emergency_contact"] = _decrypt_emergency_contact(out["emergency_contact"])
    return out
