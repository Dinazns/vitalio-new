"""
JWT authentication, role resolution, and decorators for the VitalIO API.
"""
import logging
import re
import threading
import time
from functools import wraps
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from urllib.request import urlopen
import json

from flask import request, g
from jose import jwt, JWTError

from config import AUTH0_DOMAIN, API_AUDIENCE, AUTH0_ALGORITHMS, AUTH0_ROLE_CLAIM
from database import get_identity_db, get_medical_db
from exceptions import AuthError, DatabaseError

logger = logging.getLogger(__name__)

# JWKS in-memory cache, avoids a network round-trip on every request and
# makes the server resilient to brief Auth0 / DNS outages.
_JWKS_CACHE: Optional[Dict[str, Any]] = None
_JWKS_CACHE_TS: float = 0.0
_JWKS_CACHE_TTL: float = 3600.0          # refresh every hour
_JWKS_FETCH_TIMEOUT: float = 5.0         # abort slow DNS/network after 5 s
_jwks_lock = threading.Lock()


def get_token_auth_header() -> str:
    """Extract JWT token from Authorization header."""
    auth = request.headers.get("Authorization", None)
    if not auth:
        raise AuthError({
            "code": "authorization_header_missing",
            "message": "Authorization header is required"
        }, 401)
    parts = auth.split()
    if parts[0].lower() != "bearer":
        raise AuthError({
            "code": "invalid_header",
            "message": "Authorization header must start with 'Bearer'"
        }, 401)
    if len(parts) != 2:
        raise AuthError({
            "code": "invalid_header",
            "message": "Authorization header must be 'Bearer <token>'"
        }, 401)
    return parts[1]


def get_jwks() -> Dict[str, Any]:
    """
    Return Auth0 JWKS, using an in-memory cache (TTL = 1 h).
    On network failure the stale cache is returned so a brief DNS outage
    does not take down the entire API.  Only raises AuthError when there
    is no usable cache at all.
    """
    global _JWKS_CACHE, _JWKS_CACHE_TS

    now = time.monotonic()

    # Fast path: cache is fresh, no lock needed
    if _JWKS_CACHE is not None and (now - _JWKS_CACHE_TS) < _JWKS_CACHE_TTL:
        return _JWKS_CACHE

    with _jwks_lock:
        now = time.monotonic()
        if _JWKS_CACHE is not None and (now - _JWKS_CACHE_TS) < _JWKS_CACHE_TTL:
            return _JWKS_CACHE

        try:
            jwks_url = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"
            jwks_response = urlopen(jwks_url, timeout=_JWKS_FETCH_TIMEOUT)
            fresh = json.loads(jwks_response.read())
            _JWKS_CACHE = fresh
            _JWKS_CACHE_TS = time.monotonic()
            return _JWKS_CACHE
        except Exception as exc:
            if _JWKS_CACHE is not None:
                logger.warning(
                    "JWKS refresh failed (%s); using stale cache (age=%.0fs)",
                    exc, now - _JWKS_CACHE_TS,
                )
                return _JWKS_CACHE
            raise AuthError({
                "code": "jwks_fetch_error",
                "message": f"Failed to fetch JWKS: {str(exc)}"
            }, 500)


def get_rsa_key(token: str, jwks: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Extract RSA public key from JWKS matching the token's key ID."""
    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            return None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return {
                    "kty": key["kty"], "kid": key["kid"], "use": key["use"],
                    "n": key["n"], "e": key["e"],
                }
        return None
    except Exception as e:
        raise AuthError({
            "code": "key_extraction_error",
            "message": f"Failed to extract RSA key: {str(e)}"
        }, 401)


def verify_jwt(token: str) -> Dict[str, Any]:
    """Verify JWT token and return decoded payload."""
    if not AUTH0_DOMAIN or not API_AUDIENCE:
        raise AuthError({
            "code": "configuration_error",
            "message": "AUTH0_DOMAIN and AUTH0_AUDIENCE must be configured"
        }, 500)
    jwks = get_jwks()
    rsa_key = get_rsa_key(token, jwks)
    if not rsa_key:
        raise AuthError({
            "code": "invalid_header",
            "message": "Unable to find appropriate key for JWT"
        }, 401)
    try:
        payload = jwt.decode(
            token, rsa_key,
            algorithms=AUTH0_ALGORITHMS,
            audience=API_AUDIENCE,
            issuer=f"https://{AUTH0_DOMAIN}/"
        )
        if "sub" not in payload:
            raise AuthError({
                "code": "invalid_token",
                "message": "JWT missing 'sub' claim"
            }, 401)
        return payload
    except JWTError as e:
        raise AuthError({
            "code": "invalid_token",
            "message": f"JWT verification failed: {str(e)}"
        }, 401)


def _extract_profile_from_jwt(jwt_payload: Dict[str, Any], user_id_auth: str) -> Dict[str, Any]:
    """Extract user profile fields from JWT payload (Auth0 claims)."""
    ns = "https://vitalio.app/"

    def claim(key):
        val = jwt_payload.get(f"{ns}{key}") or jwt_payload.get(key) or ""
        return str(val) if val is not None else ""

    first_name = (claim("given_name") or "")[:64] or None
    last_name = (claim("family_name") or "")[:64] or None
    email = (claim("email") or "").strip()[:256] or None
    picture = (claim("picture") or "")[:512] or None
    display_name = (
        f"{first_name or ''} {last_name or ''}".strip()
        or claim("name")
        or claim("email")
        or (jwt_payload.get("nickname") or "")
        or user_id_auth
    )[:128]
    return {
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "display_name": display_name,
        "picture": picture,
    }


def _extract_role_from_jwt(jwt_payload: Optional[Dict[str, Any]]) -> str:
    """Extract and normalize role from JWT claims. Returns canonical role for DB storage."""
    if not jwt_payload:
        return "patient"
    ns = "https://vitalio.app/"
    role_raw = (
        jwt_payload.get(AUTH0_ROLE_CLAIM)
        or jwt_payload.get(f"{ns}role")
        or jwt_payload.get("role")
        or jwt_payload.get("roles")
        or jwt_payload.get(f"{ns}roles")
    )
    if isinstance(role_raw, list):
        role_raw = role_raw[0] if role_raw else ""
    role = str(role_raw or "").strip().lower()
    if role in ("medecin", "médecin", "superuser"):
        return "doctor"
    if role in ("aidant", "family"):
        return "caregiver"
    if role == "user":
        return "patient"
    if role in ("patient", "doctor", "caregiver", "admin"):
        return role
    return "patient"


def get_or_create_user(auth0_sub: str, jwt_payload: Optional[Dict[str, Any]] = None) -> str:
    """Resolve or create user in Vitalio_Identity.users. Returns user_id_auth."""
    if not auth0_sub:
        raise AuthError({"code": "invalid_token", "message": "Missing Auth0 subject"}, 401)
    try:
        identity_db = get_identity_db()
        if identity_db.users.find_one({"user_id_auth": auth0_sub}):
            return auth0_sub
        profile = {}
        if jwt_payload:
            profile = _extract_profile_from_jwt(jwt_payload, auth0_sub)
        email = profile.get("email") or (jwt_payload.get("email") if jwt_payload else None)
        role = _extract_role_from_jwt(jwt_payload)
        doc = {
            "user_id_auth": auth0_sub,
            "email": email,
            "role": role,
            "display_name": profile.get("display_name") or auth0_sub,
            "first_name": profile.get("first_name"),
            "last_name": profile.get("last_name"),
            "picture": profile.get("picture"),
            "created_at": datetime.now(timezone.utc),
        }
        try:
            identity_db.users.insert_one(doc)
        except Exception as e:
            if "duplicate key" not in str(e).lower() and "E11000" not in str(e):
                raise
        return auth0_sub
    except (AuthError, DatabaseError):
        raise
    except Exception as e:
        raise DatabaseError({
            "code": "user_resolution_error",
            "message": f"Error resolving user: {str(e)}",
        }, 500)


def get_user_role(user_id_auth: str) -> Optional[str]:
    """Return normalized role from identity.users."""
    try:
        doc = get_identity_db().users.find_one(
            {"user_id_auth": user_id_auth},
            projection={"_id": 0, "role": 1}
        )
    except Exception:
        raise DatabaseError({
            "code": "user_role_query_error",
            "message": "Failed to query user role"
        }, 500)
    if not doc:
        return None
    role = str(doc.get("role") or "").strip().lower()
    if role in ("medecin", "superuser"):
        return "doctor"
    if role == "aidant":
        return "caregiver"
    return role


def _get_next_sim_esp32_device_id() -> str:
    """Return next available SIM-ESP32-XXX device ID (e.g. SIM-ESP32-003).
    Scans users_devices and measurements to avoid reusing existing IDs.
    """
    pattern = re.compile(r"^SIM-ESP32-(\d+)$", re.IGNORECASE)
    numbers = [0]

    try:
        for device_id in get_identity_db().users_devices.distinct("device_id"):
            if device_id:
                m = pattern.match(str(device_id))
                if m:
                    numbers.append(int(m.group(1)))
        for device_id in get_medical_db().measurements.distinct("device_id"):
            if device_id:
                m = pattern.match(str(device_id))
                if m:
                    numbers.append(int(m.group(1)))
    except Exception as e:
        logger.warning("Error scanning existing device IDs: %s", e)

    next_num = max(numbers) + 1
    return f"SIM-ESP32-{next_num:03d}"


def _ensure_patient_device(user_id_auth: str) -> None:
    """Ensure a patient has a device in users_devices. Creates one if missing."""
    identity_db = get_identity_db()
    if identity_db.users_devices.find_one({"user_id_auth": user_id_auth}):
        return
    device_id = _get_next_sim_esp32_device_id()
    identity_db.users_devices.update_one(
        {"user_id_auth": user_id_auth},
        {"$set": {"user_id_auth": user_id_auth, "device_id": device_id}},
        upsert=True,
    )
    logger.info("Auto-assigned device for patient: %s -> %s", user_id_auth, device_id)


def _provision_user_if_new(user_id_auth: str, jwt_payload: Dict[str, Any]) -> Optional[str]:
    """JIT provision new patient. Returns provisioned role or None. Called lazily by get_current_user_role."""
    if get_identity_db().users.find_one({"user_id_auth": user_id_auth}):
        return None

    ns = "https://vitalio.app/"
    def claim(key):
        return jwt_payload.get(f"{ns}{key}") or jwt_payload.get(key) or ""

    first_name = claim("given_name")[:64]
    last_name = claim("family_name")[:64]
    display_name = f"{first_name} {last_name}".strip() or claim("name") or claim("email") or jwt_payload.get("nickname") or user_id_auth
    email = claim("email")[:256]
    picture = claim("picture")[:512]
    phone = claim("phone_number")[:32] or None
    birthdate = claim("birthdate")[:16] or None
    pathology = claim("pathology")[:64] or None
    emergency = {
        "last_name": claim("emergency_lastname")[:64] or None,
        "first_name": claim("emergency_firstname")[:64] or None,
        "phone": claim("emergency_phone")[:32] or None,
        "email": claim("emergency_email")[:256] or None,
    }
    has_emergency = any(v for v in emergency.values())

    try:
        get_identity_db().users.update_one(
            {"user_id_auth": user_id_auth},
            {"$set": {
                "user_id_auth": user_id_auth, "role": "patient",
                "display_name": str(display_name)[:128],
                "email": email, "first_name": first_name or None,
                "last_name": last_name or None, "picture": picture or None,
                "phone": phone, "birthdate": birthdate, "pathology": pathology,
                "emergency_contact": emergency if has_emergency else None,
                "created_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        device_id = _get_next_sim_esp32_device_id()
        get_identity_db().users_devices.update_one(
            {"user_id_auth": user_id_auth},
            {"$set": {"user_id_auth": user_id_auth, "device_id": device_id}},
            upsert=True,
        )
        logger.info("JIT provisioned patient: %s -> %s", user_id_auth, device_id)

        if has_emergency and emergency.get("email"):
            from services.invitation_service import invite_emergency_contact_if_needed
            patient_name = display_name if display_name != user_id_auth else "Un patient VitalIO"
            invite_emergency_contact_if_needed(user_id_auth, emergency["email"], patient_name)

        return "patient"
    except Exception as e:
        logger.warning("JIT provisioning failed for %s: %s", user_id_auth, e)
        return None


def get_current_user_role() -> str:
    """Extract normalized user role. DB is source of truth; JIT-provisions new users."""
    payload = getattr(g, "jwt_payload", {}) or {}
    current_user_id_auth = getattr(g, "user_id_auth", None)

    if current_user_id_auth:
        db_role = get_user_role(current_user_id_auth)
        if db_role:
            if db_role == "patient":
                _ensure_patient_device(current_user_id_auth)
            return db_role
        provisioned = _provision_user_if_new(current_user_id_auth, payload)
        if provisioned:
            if provisioned == "patient":
                _ensure_patient_device(current_user_id_auth)
            return provisioned

    role_raw = payload.get(AUTH0_ROLE_CLAIM) or payload.get("role") or payload.get("roles") or payload.get("https://vitalio.app/roles")
    if isinstance(role_raw, list):
        role_raw = role_raw[0] if role_raw else ""
    role = str(role_raw or "").strip().lower()
    if role in ("medecin", "médecin", "superuser"):
        return "doctor"
    if role in ("aidant", "family"):
        return "caregiver"
    if role == "user":
        role = "patient"
    role = role or "patient"
    if role == "patient" and current_user_id_auth:
        _ensure_patient_device(current_user_id_auth)
    return role


def requires_auth(f):
    """Decorator to protect routes requiring JWT authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == "OPTIONS":
            return ("", 200)
        token = get_token_auth_header()
        payload = verify_jwt(token)
        auth0_sub = payload.get("sub")
        user_email = payload.get("email")
        if not auth0_sub:
            raise AuthError({
                "code": "invalid_token",
                "message": "JWT missing user identifier in 'sub' claim"
            }, 401)
        user_id = get_or_create_user(auth0_sub, payload)
        g.user_id_auth = auth0_sub
        g.user_id = user_id
        g.user_email = user_email
        g.jwt_payload = payload
        return f(*args, **kwargs)
    return decorated


def requires_role(*allowed_roles):
    """Decorator that enforces user role from validated JWT claims."""
    normalized_allowed = {str(role).strip().lower() for role in allowed_roles}

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            role = get_current_user_role()
            if role not in normalized_allowed:
                raise AuthError({
                    "code": "forbidden",
                    "message": f"Role '{role or 'unknown'}' does not have access"
                }, 403)
            g.current_role = role
            return f(*args, **kwargs)
        return wrapped
    return decorator
