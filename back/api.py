import io
import json
import logging
import os
import re
import hashlib
import secrets
import smtplib
import threading
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.request import urlopen
from functools import wraps
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from jose import jwt, JWTError
from jose.constants import ALGORITHMS
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
import qrcode
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from bson import ObjectId
import ml_module

env_path = '.env'
if not os.path.exists(env_path):
    env_path = '../.env'
load_dotenv(env_path)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

logger = logging.getLogger(__name__)

CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:5173", "http://localhost:5174", "http://localhost:3000", "http://127.0.0.1:5173", "http://127.0.0.1:5174"],
        "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True,
    }
})

# ============================================================================
# CONFIGURATION
# ============================================================================

AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
API_AUDIENCE = os.getenv("AUTH0_AUDIENCE")
ALGORITHMS = ["RS256"]
AUTH0_ROLE_CLAIM = os.getenv("AUTH0_ROLE_CLAIM", "https://vitalio.app/role")

# MongoDB (Vitalio_Identity + Vitalio_Medical)
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_IDENTITY_DB = os.getenv("MONGODB_IDENTITY_DB", "Vitalio_Identity")
MONGODB_MEDICAL_DB = os.getenv("MONGODB_MEDICAL_DB", "Vitalio_Medical")

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))  # TLS port (8883), not unencrypted (1883)
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "vitalio/dev/+/measurements")
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")  # Required for authentication
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")  # Required for authentication
MQTT_CA_CERT = os.getenv("MQTT_CA_CERT", "./mosquitto/certs/ca.crt")  # CA certificate for TLS verification
MQTT_ENABLED = os.getenv("MQTT_ENABLED", "true").lower() == "true"

# Alerting engine defaults (can be overridden per patient/pathology in DB).
ALERT_DEFAULT_THRESHOLDS = {
    "spo2_min": 92.0,
    "heart_rate_min": 50.0,
    "heart_rate_max": 120.0,
    "temperature_min": 35.5,
    "temperature_max": 38.0,
}
ALERT_DEFAULT_CONSECUTIVE_BREACHES = 3
INVITE_TTL_HOURS = int(os.getenv("INVITE_TTL_HOURS", "24"))
CABINET_CODE_TTL_MINUTES_DEFAULT = int(os.getenv("CABINET_CODE_TTL_MINUTES", "15"))

# Email (SMTP) for invitation QR
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "charldevlin@gmail.com")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

_mqtt_client: Optional[mqtt.Client] = None
_mqtt_thread: Optional[threading.Thread] = None
_mongo_client: Optional[MongoClient] = None


def get_mongo_client() -> MongoClient:
    """Return MongoDB client (singleton)."""
    global _mongo_client
    if _mongo_client is None:
        try:
            _mongo_client = MongoClient(
                MONGODB_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
            )
            # Force a ping to verify connection
            _mongo_client.admin.command("ping")
        except PyMongoError as e:
            raise DatabaseError({
                "code": "database_connection_error",
                "message": f"Failed to connect to MongoDB: {str(e)}"
            }, 500)
    return _mongo_client


def get_identity_db():
    """Return Vitalio_Identity database (users, users_devices)."""
    return get_mongo_client()[MONGODB_IDENTITY_DB]


def get_medical_db():
    """Return Vitalio_Medical database (measurements)."""
    return get_mongo_client()[MONGODB_MEDICAL_DB]


def init_database():
    """
    Ensure MongoDB collections and indexes exist.
    Vitalio_Identity: users, users_devices, doctor_patients, caregiver_patients.
    Vitalio_Medical: measurements, doctor_feedback, alert collections.
    """
    try:
        identity_db = get_identity_db()
        medical_db = get_medical_db()

        # users_devices: unique index on user_id_auth
        identity_db.users_devices.create_index("user_id_auth", unique=True)
        identity_db.users.create_index("user_id_auth", unique=True)
        identity_db.users.create_index("role")
        identity_db.doctor_patients.create_index(
            [("doctor_user_id_auth", 1), ("patient_user_id_auth", 1)],
            unique=True
        )
        identity_db.doctor_patients.create_index("doctor_user_id_auth")
        identity_db.caregiver_patients.create_index(
            [("caregiver_user_id_auth", 1), ("patient_user_id_auth", 1)],
            unique=True
        )
        identity_db.caregiver_patients.create_index("caregiver_user_id_auth")
        identity_db.users_devices.create_index("device_id")
        identity_db.doctor_invites.create_index("token_hash", unique=True)
        identity_db.doctor_invites.create_index("expires_at", expireAfterSeconds=0)
        identity_db.doctor_invites.create_index([("doctor_user_id_auth", 1), ("mode", 1), ("created_at", -1)])
        identity_db.caregiver_invites.create_index("token_hash", unique=True)
        identity_db.caregiver_invites.create_index("expires_at", expireAfterSeconds=0)
        identity_db.caregiver_invites.create_index("patient_user_id_auth")
        identity_db.audit_links.create_index([("event_type", 1), ("created_at", -1)])
        identity_db.audit_links.create_index([("doctor_user_id_auth", 1), ("patient_user_id_auth", 1), ("created_at", -1)])

        # measurements: index for queries by device_id and measured_at
        medical_db.measurements.create_index([("device_id", 1), ("measured_at", -1)])
        medical_db.doctor_feedback.create_index([("patient_user_id_auth", 1), ("created_at", -1)])
        medical_db.doctor_feedback.create_index([("doctor_user_id_auth", 1), ("created_at", -1)])
        medical_db.alert_thresholds.create_index(
            [("scope", 1), ("device_id", 1), ("pathology", 1)],
            unique=True
        )
        medical_db.alert_thresholds.create_index("enabled")
        medical_db.alerts.create_index([("device_id", 1), ("status", 1), ("created_at", -1)])
        medical_db.alerts.create_index([("device_id", 1), ("metric", 1), ("status", 1)])

        # ML anomaly detection collections
        medical_db.ml_anomalies.create_index([("device_id", 1), ("status", 1), ("created_at", -1)])
        medical_db.ml_anomalies.create_index([("user_id_auth", 1), ("status", 1)])
        medical_db.ml_anomalies.create_index([("user_id_auth", 1), ("created_at", -1)])
        medical_db.ml_anomalies.create_index("measurement_id")
        medical_db.ml_anomalies.create_index("status")
        medical_db.ml_decisions.create_index([("device_id", 1), ("processed_at", -1)])
        medical_db.ml_decisions.create_index("measurement_id", unique=True)
        medical_db.ml_model_versions.create_index("version", unique=True)

        # ML flags on measurements for filtering
        medical_db.measurements.create_index("ml_is_anomaly", sparse=True)
        medical_db.measurements.create_index("ml_anomaly_status", sparse=True)
        medical_db.measurements.create_index("ml_anomaly_id", sparse=True)
    except DatabaseError:
        raise
    except PyMongoError as e:
        raise DatabaseError({
            "code": "database_init_error",
            "message": f"Failed to initialize MongoDB: {str(e)}"
        }, 500)

# ============================================================================
# ERROR HANDLING
# ============================================================================

class AuthError(Exception):
    """Custom exception for authentication/authorization errors."""
    def __init__(self, error: Dict[str, str], status_code: int):
        self.error = error
        self.status_code = status_code


class DatabaseError(Exception):
    """Custom exception for database operation errors."""
    def __init__(self, error: Dict[str, str], status_code: int):
        self.error = error
        self.status_code = status_code


@app.errorhandler(AuthError)
def handle_auth_error(ex: AuthError):
    """Handle authentication errors."""
    return jsonify(ex.error), ex.status_code


@app.errorhandler(DatabaseError)
def handle_database_error(ex: DatabaseError):
    """Handle database errors."""
    return jsonify(ex.error), ex.status_code


@app.errorhandler(500)
def handle_internal_error(e):
    """Handle internal server errors."""
    return jsonify({
        "code": "internal_server_error",
        "message": "An internal server error occurred"
    }), 500

# ============================================================================
# JWT AUTHENTICATION (Sequence Steps 3-5)
# ============================================================================

def get_token_auth_header() -> str:
    """
    Extract JWT token from Authorization header.
    
    Sequence Step 3: Frontend calls GET /api/me/data with Authorization: Bearer <JWT>
    
    Returns:
        str: JWT token string
        
    Raises:
        AuthError: If Authorization header is missing or malformed
    """
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
    Fetch Auth0 JWKS (JSON Web Key Set) for JWT signature verification.
    
    Returns:
        dict: JWKS containing public keys for JWT verification
    """
    print("JWKS URL =", f"https://{AUTH0_DOMAIN}/.well-known/jwks.json")
    try:
        jwks_url = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"
        jwks_response = urlopen(jwks_url)
        jwks = json.loads(jwks_response.read())
        return jwks
    except Exception as e:
        raise AuthError({
            "code": "jwks_fetch_error",
            "message": f"Failed to fetch JWKS: {str(e)}"
        }, 500)


def get_rsa_key(token: str, jwks: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Extract RSA public key from JWKS matching the token's key ID.
    
    Args:
        token: JWT token string
        jwks: JWKS dictionary from Auth0
        
    Returns:
        dict: RSA key dictionary with kty, kid, use, n, e fields, or None if not found
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        
        if not kid:
            return None
        
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"],
                }
        
        return None
    except Exception as e:
        raise AuthError({
            "code": "key_extraction_error",
            "message": f"Failed to extract RSA key: {str(e)}"
        }, 401)


def verify_jwt(token: str) -> Dict[str, Any]:
    """
    Verify JWT token signature, issuer, audience, and expiration.
    
    Sequence Step 4: Flask API verifies:
    - JWT signature (RS256)
    - issuer
    - audience
    - expiration
    - extracts user_id from the 'sub' claim
    
    Args:
        token: JWT token string
        
    Returns:
        dict: Decoded JWT payload containing user information
        
    Raises:
        AuthError: If JWT verification fails
    """
    if not AUTH0_DOMAIN:
        raise AuthError({
            "code": "configuration_error",
            "message": "AUTH0_DOMAIN not configured"
        }, 500)
    
    if not API_AUDIENCE:
        raise AuthError({
            "code": "configuration_error",
            "message": "AUTH0_AUDIENCE not configured"
        }, 500)
    
    # Fetch JWKS
    jwks = get_jwks()
    
    # Extract RSA key
    rsa_key = get_rsa_key(token, jwks)
    
    if not rsa_key:
        raise AuthError({
            "code": "invalid_header",
            "message": "Unable to find appropriate key for JWT"
        }, 401)
    
    # Verify and decode JWT
    try:
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=ALGORITHMS,
            audience=API_AUDIENCE,
            issuer=f"https://{AUTH0_DOMAIN}/"
        )
        
        # Ensure 'sub' claim exists (user_id)
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
    except Exception as e:
        raise AuthError({
            "code": "token_processing_error",
            "message": f"Error processing token: {str(e)}"
        }, 401)


def get_or_create_user(auth0_sub: str, email: Optional[str]) -> str:
    """
    Behaviour:
        - Look up user by auth0_sub in public.users
        - If found, return its internal UUID (id)
        - If not found, create a new row and return the new UUID

    Constraints:
        - Never touches auth.users or Supabase Auth
        - Only relies on the Auth0 subject (auth0_sub) and optional email
    """
    if not auth0_sub:
        raise AuthError(
            {
                "code": "invalid_token",
                "message": "Missing Auth0 subject (sub) in JWT payload",
            },
            401,
        )

    supabase_client = get_supabase_client()
    if not supabase_client:
        raise DatabaseError(
            {
                "code": "database_not_configured",
                "message": "Database client not initialized. Please check SUPABASE_URL and SUPABASE_KEY in .env file",
            },
            500,
        )

    try:
        # 1) Try to find an existing user by auth0_sub
        select_response = (
            supabase_client.table("users")
            .select("id")
            .eq("auth0_sub", auth0_sub)
            .execute()
        )

        if select_response.data:
            user_id = select_response.data[0].get("id")
            if user_id:
                return user_id

        # 2) Not found: attempt to create the user
        insert_payload: Dict[str, Any] = {"auth0_sub": auth0_sub}
        # email can be None; assume column allows NULL
        insert_payload["email"] = email

        try:
            insert_response = (
                supabase_client.table("users")
                .insert(insert_payload)
                .execute()
            )

            if insert_response.data:
                created_id = insert_response.data[0].get("id")
                if created_id:
                    return created_id
        except Exception as insert_error:
            # Handle potential race condition: another request may have created the row
            error_str = str(insert_error)
            if "duplicate key value" not in error_str and "unique constraint" not in error_str:
                raise

        # 3) If insert failed due to unique constraint, re-select
        retry_response = (
            supabase_client.table("users")
            .select("id")
            .eq("auth0_sub", auth0_sub)
            .execute()
        )
        if retry_response.data and retry_response.data[0].get("id"):
            return retry_response.data[0]["id"]

        # If we still don't have an id, something unexpected happened
        raise DatabaseError(
            {
                "code": "user_resolution_failed",
                "message": "Unable to resolve or create application user for given Auth0 subject",
            },
            500,
        )

    except AuthError:
        # Let AuthError bubble up unmodified
        raise
    except DatabaseError:
        # Let DatabaseError bubble up unmodified
        raise
    except Exception as e:
        raise DatabaseError(
            {
                "code": "user_resolution_error",
                "message": f"Error while resolving or creating application user: {str(e)}",
            },
            500,
        )


def requires_auth(f):
    """
    Decorator to protect routes requiring JWT authentication.
    
    Sequence Steps 3-5:
    - Extracts JWT from Authorization header
    - Verifies JWT (signature, issuer, audience, expiration)
    - Extracts user_id from 'sub' claim
    - Stores authenticated user info in Flask request context (g)
    
    Args:
        f: Route function to protect
        
    Returns:
        Decorated function that requires valid JWT
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Let CORS preflight requests pass without JWT validation.
        if request.method == "OPTIONS":
            return ("", 200)

        # Extract JWT token from Authorization header
        token = get_token_auth_header()
        
        # Verify JWT (signature, issuer, audience, expiration)
        payload = verify_jwt(token)
        
        # Extract user_id from 'sub' claim and store in request context
        auth0_sub = payload.get("sub")
        user_email = payload.get("email")
        
        if not auth0_sub:
            raise AuthError({
                "code": "invalid_token",
                "message": "JWT missing user identifier in 'sub' claim"
            }, 401)
        
        # Resolve or create internal application user (public.users)
        user_id = get_or_create_user(auth0_sub, user_email)
        
        # Store authenticated user information in Flask request context
        g.user_id_auth = auth0_sub          # Raw Auth0 subject (for logging/traces)
        g.user_id = user_id                 # Internal UUID from public.users.id
        g.user_email = user_email
        g.jwt_payload = payload
        
        return f(*args, **kwargs)
    
    return decorated


def provision_user_if_new(user_id_auth: str, jwt_payload: Dict[str, Any]) -> Optional[str]:
    """
    JIT provisioning: create user in identity.users and users_devices if absent.
    Used when a new Auth0 user connects via invite link (signup then first login).
    Returns the provisioned role ("patient") or None if user already existed.
    Reads namespaced custom claims (https://vitalio.app/*) with fallback to standard claims.
    All additionalSignUpFields from Auth0 Lock are stored in user_metadata and injected
    into the JWT by the Post-Login Action (auth0_action_post_login.js).
    """
    if get_identity_db().users.find_one({"user_id_auth": user_id_auth}):
        return None

    ns = "https://vitalio.app/"

    def claim(key):
        return jwt_payload.get(f"{ns}{key}") or jwt_payload.get(key) or ""

    display_name = (
        claim("name")
        or claim("email")
        or jwt_payload.get("nickname")
        or user_id_auth
    )
    first_name = claim("given_name")[:64]
    last_name = claim("family_name")[:64]
    email = claim("email")[:256]
    picture = claim("picture")[:512]

    # Fields from Auth0 Lock additionalSignUpFields (via Post-Login Action)
    phone     = claim("phone_number")[:32] or None
    birthdate = claim("birthdate")[:16] or None
    pathology = claim("pathology")[:64] or None
    emergency = {
        "last_name":  claim("emergency_lastname")[:64]  or None,
        "first_name": claim("emergency_firstname")[:64] or None,
        "phone":      claim("emergency_phone")[:32]     or None,
        "email":      claim("emergency_email")[:256]    or None,
    }
    has_emergency = any(v for v in emergency.values())

    try:
        get_identity_db().users.update_one(
            {"user_id_auth": user_id_auth},
            {
                "$set": {
                    "user_id_auth": user_id_auth,
                    "role": "patient",
                    "display_name": str(display_name)[:128],
                    "email": email,
                    "first_name": first_name or None,
                    "last_name": last_name or None,
                    "picture": picture or None,
                    "phone": phone,
                    "birthdate": birthdate,
                    "pathology": pathology,
                    "emergency_contact": emergency if has_emergency else None,
                    "created_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        device_id = f"SIM-PAT-{hashlib.sha256(user_id_auth.encode()).hexdigest()[:12].upper()}"
        get_identity_db().users_devices.update_one(
            {"user_id_auth": user_id_auth},
            {"$set": {"user_id_auth": user_id_auth, "device_id": device_id}},
            upsert=True,
        )
        logger.info("JIT provisioned patient: %s -> %s", user_id_auth, device_id)

        if has_emergency and emergency.get("email"):
            patient_name = display_name if display_name != user_id_auth else "Un patient VitalIO"
            invite_emergency_contact_if_needed(user_id_auth, emergency["email"], patient_name)

        return "patient"
    except PyMongoError as e:
        logger.warning("JIT provisioning failed for %s: %s", user_id_auth, e)
        return None


def get_current_user_role() -> str:
    """
    Extract normalized user role. Database is the source of truth for existing users.
    JWT is only used when user is not yet in DB. JIT-provisions new users as patient.
    """
    payload = getattr(g, "jwt_payload", {}) or {}
    current_user_id_auth = getattr(g, "user_id_auth", None)

    # 1. Database first (source of truth) - existing users may have JWT with wrong role (e.g. "user")
    if current_user_id_auth:
        db_role = get_user_role(current_user_id_auth)
        if db_role:
            return db_role
        # New user: JIT provision as patient when no role in JWT
        provisioned = provision_user_if_new(current_user_id_auth, payload)
        if provisioned:
            return provisioned

    # 2. JWT fallback (new users not yet in DB, or edge cases)
    role_raw = payload.get(AUTH0_ROLE_CLAIM) or payload.get("role") or payload.get("roles") or payload.get("https://vitalio.app/roles")
    if isinstance(role_raw, list):
        role_raw = role_raw[0] if role_raw else ""
    role = str(role_raw or "").strip().lower()
    if role == "medecin" or role == "médecin" or role == "superuser":
        return "doctor"
    if role == "aidant" or role == "family":
        return "caregiver"
    if role == "user":
        return "patient"
    return role or "patient"


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
                    "message": f"Role '{role or 'unknown'}' does not have access to this resource"
                }, 403)
            g.current_role = role
            return f(*args, **kwargs)
        return wrapped
    return decorator

# ============================================================================
# DATABASE ACCESS LAYER
# ============================================================================

def get_device_ids(user_id_auth: str) -> List[str]:
    """
    Query Vitalio_Identity.users_devices to map Auth0 user_id to one or many
    device IDs.
    """
    try:
        cursor = get_identity_db().users_devices.find(
            {"user_id_auth": user_id_auth},
            projection={"device_id": 1, "_id": 0}
        )
        ids = []
        for doc in cursor:
            device_id = doc.get("device_id")
            if device_id:
                ids.append(str(device_id))
        # Stable order + deduplication while preserving first occurrence
        seen = set()
        ordered = []
        for device_id in ids:
            if device_id in seen:
                continue
            seen.add(device_id)
            ordered.append(device_id)
        return ordered
    except PyMongoError as e:
        raise DatabaseError({
            "code": "correspondence_query_error",
            "message": f"Failed to query identity database: {str(e)}"
        }, 500)


def get_device_id(user_id_auth: str) -> Optional[str]:
    """
    Backward-compatible helper: return the first mapped device ID.
    """
    ids = get_device_ids(user_id_auth)
    return ids[0] if ids else None


def get_device_measurements(device_id: str) -> List[Dict[str, Any]]:
    """
    Query Vitalio_Medical.measurements for vital measurements of a device.
    """
    try:
        cursor = get_medical_db().measurements.find(
            {"device_id": device_id}
        ).sort("measured_at", -1).limit(100)

        rows = []
        for doc in cursor:
            doc.pop("_id", None)
            ts = doc.get("measured_at")
            if isinstance(ts, datetime):
                doc["timestamp"] = ts.isoformat()
            else:
                doc["timestamp"] = doc.get("measured_at")
            rows.append({
                "timestamp": doc["timestamp"],
                "heart_rate": doc.get("heart_rate"),
                "spo2": doc.get("spo2"),
                "temperature": doc.get("temperature"),
            })
        return rows
    except PyMongoError as e:
        raise DatabaseError({
            "code": "medical_query_error",
            "message": f"Failed to query medical database: {str(e)}"
        }, 500)


def get_assigned_patient_ids_for_doctor(doctor_user_id_auth: str) -> List[str]:
    """Return patient Auth0 IDs assigned to a given doctor Auth0 ID."""
    try:
        cursor = get_identity_db().doctor_patients.find(
            {"doctor_user_id_auth": doctor_user_id_auth},
            projection={"_id": 0, "patient_user_id_auth": 1}
        )
        return [doc.get("patient_user_id_auth") for doc in cursor if doc.get("patient_user_id_auth")]
    except PyMongoError as e:
        raise DatabaseError({
            "code": "doctor_assignments_query_error",
            "message": f"Failed to query doctor assignments: {str(e)}"
        }, 500)


def get_assigned_patient_ids_for_caregiver(caregiver_user_id_auth: str) -> List[str]:
    """Return patient Auth0 IDs assigned to a given caregiver Auth0 ID."""
    try:
        cursor = get_identity_db().caregiver_patients.find(
            {"caregiver_user_id_auth": caregiver_user_id_auth},
            projection={"_id": 0, "patient_user_id_auth": 1}
        )
        return [doc.get("patient_user_id_auth") for doc in cursor if doc.get("patient_user_id_auth")]
    except PyMongoError as e:
        raise DatabaseError({
            "code": "caregiver_assignments_query_error",
            "message": f"Failed to query caregiver assignments: {str(e)}"
        }, 500)


def get_assigned_doctor_ids_for_patient(patient_user_id_auth: str) -> List[str]:
    """Return doctor Auth0 IDs assigned to a given patient Auth0 ID."""
    try:
        cursor = get_identity_db().doctor_patients.find(
            {"patient_user_id_auth": patient_user_id_auth},
            projection={"_id": 0, "doctor_user_id_auth": 1}
        )
        return [doc.get("doctor_user_id_auth") for doc in cursor if doc.get("doctor_user_id_auth")]
    except PyMongoError as e:
        raise DatabaseError({
            "code": "doctor_assignments_query_error",
            "message": f"Failed to query doctor assignments for patient: {str(e)}"
        }, 500)


def get_user_role(user_id_auth: str) -> Optional[str]:
    """Return normalized role stored in identity.users."""
    try:
        doc = get_identity_db().users.find_one(
            {"user_id_auth": user_id_auth},
            projection={"_id": 0, "role": 1}
        )
    except PyMongoError as e:
        raise DatabaseError({
            "code": "user_role_query_error",
            "message": f"Failed to query user role: {str(e)}"
        }, 500)

    if not doc:
        return None
    role = str(doc.get("role") or "").strip().lower()
    if role in ("medecin", "superuser"):
        return "doctor"
    if role == "aidant":
        return "caregiver"
    return role


def relationship_exists(relationship_type: str, user_id_auth: str, patient_user_id_auth: str) -> bool:
    """Check if relationship exists between doctor/caregiver and patient."""
    identity_db = get_identity_db()
    if relationship_type == "doctor":
        query = {
            "doctor_user_id_auth": user_id_auth,
            "patient_user_id_auth": patient_user_id_auth
        }
        return identity_db.doctor_patients.find_one(query, projection={"_id": 1}) is not None
    if relationship_type == "caregiver":
        query = {
            "caregiver_user_id_auth": user_id_auth,
            "patient_user_id_auth": patient_user_id_auth
        }
        return identity_db.caregiver_patients.find_one(query, projection={"_id": 1}) is not None
    return False


def ensure_patient_access_or_403(patient_user_id_auth: str):
    """
    Enforce patient data access by role + relationship:
    - patient: self only
    - doctor/caregiver: must be assigned
    - admin: always allowed
    """
    current_user_id_auth = g.user_id_auth
    role = get_current_user_role()
    if not role or role == "unknown":
        role = get_user_role(current_user_id_auth) or role

    # Always allow self access for authenticated user.
    # This prevents false 403 when role claim is missing in JWT.
    if current_user_id_auth == patient_user_id_auth:
        return

    if role == "admin":
        return

    if role == "patient":
        if current_user_id_auth != patient_user_id_auth:
            raise AuthError({
                "code": "forbidden",
                "message": "Patient users can only access their own data"
            }, 403)
        return

    if role == "doctor":
        if not relationship_exists("doctor", current_user_id_auth, patient_user_id_auth):
            raise AuthError({
                "code": "patient_not_assigned",
                "message": "This patient is not assigned to the authenticated doctor"
            }, 403)
        return

    if role == "caregiver":
        if not relationship_exists("caregiver", current_user_id_auth, patient_user_id_auth):
            raise AuthError({
                "code": "patient_not_assigned",
                "message": "This patient is not assigned to the authenticated caregiver"
            }, 403)
        return

    raise AuthError({
        "code": "forbidden",
        "message": f"Role '{role or 'unknown'}' cannot access patient resources"
    }, 403)


def parse_iso_datetime(value: Optional[str], field_name: str) -> Optional[datetime]:
    """Parse ISO date/time query parameter into datetime (UTC-naive)."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.replace(tzinfo=None)
        return parsed
    except Exception:
        raise ValueError(f"Invalid datetime format for '{field_name}', expected ISO-8601")


def normalize_user_id_auth(value: Any, field_name: str) -> str:
    """Normalize Auth0 subject identifier used across identity relations."""
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def hash_secret_token(token: str) -> str:
    """Hash token/code with SHA-256 before persistence."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_qr_png(url: str, size: int = 256) -> bytes:
    """Generate QR code PNG image for given URL."""
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size, size))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def send_invitation_email(
    patient_email: str,
    invite_token: str,
    web_invite_url: str,
    expires_at: datetime,
    doctor_display_name: str = "Votre médecin",
) -> None:
    """Send invitation email with QR code to patient."""
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        raise ValueError("SMTP non configuré: SMTP_HOST, SMTP_USER et SMTP_PASSWORD sont requis dans .env")

    logger.info("Envoi email invitation vers %s (SMTP: %s:%s)", patient_email, SMTP_HOST, SMTP_PORT)

    qr_bytes = generate_qr_png(web_invite_url)
    expires_str = expires_at.strftime("%d/%m/%Y à %H:%M") if isinstance(expires_at, datetime) else str(expires_at)

    msg = MIMEMultipart("related")
    msg["Subject"] = "Invitation VitalIO - Associez-vous à votre médecin"
    msg["From"] = EMAIL_FROM
    msg["To"] = patient_email

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 500px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #2563eb;">Invitation VitalIO</h2>
  <p>Bonjour,</p>
  <p>{doctor_display_name} vous invite à associer votre compte VitalIO pour le suivi de vos constantes vitales.</p>
  <p><strong>Scannez le QR code ci-dessous</strong> avec votre téléphone pour accepter l'invitation et lier votre compte au cabinet médical :</p>
  <p style="text-align: center; margin: 24px 0;">
    <img src="cid:qrcode" alt="QR code invitation" width="256" height="256" style="border: 1px solid #ddd; border-radius: 8px;" />
  </p>
  <p>Ou cliquez sur ce lien : <a href="{web_invite_url}">{web_invite_url}</a></p>
  <p style="color: #666; font-size: 14px;">Cette invitation expire le <strong>{expires_str}</strong>.</p>
  <p>Cordialement,<br/>L'équipe VitalIO</p>
</body>
</html>
"""
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    img = MIMEImage(qr_bytes)
    img.add_header("Content-ID", "<qrcode>")
    img.add_header("Content-Disposition", "inline", filename="invitation-qr.png")
    msg.attach(img)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(EMAIL_FROM, patient_email, msg.as_string())
        logger.info("Email envoyé avec succès vers %s", patient_email)
    except smtplib.SMTPAuthenticationError as e:
        logger.exception("Erreur authentification SMTP: %s", e)
        raise ValueError(
            "Erreur d'authentification SMTP (Mailjet). Vérifiez que SMTP_USER (API Key) et SMTP_PASSWORD (Secret Key) "
            "sont corrects dans .env. Voir https://app.mailjet.com/account/api_keys"
        ) from e
    except smtplib.SMTPRecipientsRefused as e:
        logger.exception("Destinataire refusé: %s", e)
        raise ValueError(
            f"L'adresse email {patient_email} est refusée par le serveur SMTP. Vérifiez qu'elle est valide."
        ) from e
    except smtplib.SMTPException as e:
        logger.exception("Erreur SMTP: %s", e)
        raise ValueError(f"Erreur SMTP: {e}") from e
    except OSError as e:
        logger.exception("Erreur connexion SMTP: %s", e)
        raise ValueError(
            f"Impossible de se connecter à {SMTP_HOST}:{SMTP_PORT}. Vérifiez votre connexion internet et le pare-feu."
        ) from e


def send_caregiver_invitation_email(
    caregiver_email: str,
    invite_token: str,
    web_invite_url: str,
    expires_at: datetime,
    patient_display_name: str = "Un patient VitalIO",
) -> None:
    """Send invitation email to an emergency contact inviting them to join as caregiver."""
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        raise ValueError("SMTP non configuré: SMTP_HOST, SMTP_USER et SMTP_PASSWORD sont requis dans .env")

    logger.info("Envoi email invitation aidant vers %s (SMTP: %s:%s)", caregiver_email, SMTP_HOST, SMTP_PORT)

    expires_str = expires_at.strftime("%d/%m/%Y à %H:%M") if isinstance(expires_at, datetime) else str(expires_at)

    msg = MIMEMultipart("related")
    msg["Subject"] = "VitalIO — Vous êtes désigné(e) comme contact d'urgence"
    msg["From"] = EMAIL_FROM
    msg["To"] = caregiver_email

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 500px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #2563eb;">VitalIO — Invitation Aidant</h2>
  <p>Bonjour,</p>
  <p><strong>{patient_display_name}</strong> vous a désigné(e) comme contact d'urgence
  sur la plateforme de télésurveillance médicale VitalIO.</p>
  <p>En créant votre compte aidant, vous pourrez :</p>
  <ul>
    <li>Consulter les constantes vitales de votre proche en temps réel</li>
    <li>Recevoir des alertes en cas d'anomalie détectée</li>
  </ul>
  <p style="text-align: center; margin: 24px 0;">
    <a href="{web_invite_url}"
       style="display: inline-block; padding: 14px 32px; background: #2563eb;
              color: #fff; text-decoration: none; border-radius: 8px;
              font-weight: bold;">
      Créer mon compte aidant
    </a>
  </p>
  <p style="font-size: 14px; color: #666;">
    Ou copiez ce lien : <a href="{web_invite_url}">{web_invite_url}</a>
  </p>
  <p style="color: #666; font-size: 14px;">Cette invitation expire le <strong>{expires_str}</strong>.</p>
  <p>Cordialement,<br/>L'équipe VitalIO</p>
</body>
</html>
"""
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(EMAIL_FROM, caregiver_email, msg.as_string())
        logger.info("Email invitation aidant envoyé vers %s", caregiver_email)
    except smtplib.SMTPException as e:
        logger.exception("Erreur SMTP (invitation aidant): %s", e)
        raise ValueError(f"Erreur SMTP: {e}") from e
    except OSError as e:
        logger.exception("Erreur connexion SMTP (invitation aidant): %s", e)
        raise ValueError(f"Impossible de se connecter à {SMTP_HOST}:{SMTP_PORT}") from e


def invite_emergency_contact_if_needed(
    patient_user_id_auth: str,
    emergency_email: str,
    patient_display_name: str = "Un patient VitalIO",
) -> Optional[str]:
    """
    If the emergency contact email does not belong to an existing user,
    create a caregiver invite token and send an invitation email (async).
    If the contact is already registered, auto-create the caregiver_patients link.
    Returns the invite_token if an email was sent, None otherwise.
    """
    if not emergency_email or not emergency_email.strip():
        return None
    emergency_email = emergency_email.strip().lower()

    existing_user = get_identity_db().users.find_one(
        {"email": {"$regex": f"^{re.escape(emergency_email)}$", "$options": "i"}},
        projection={"user_id_auth": 1, "role": 1},
    )

    if existing_user:
        caregiver_uid = existing_user["user_id_auth"]
        if caregiver_uid == patient_user_id_auth:
            return None
        try:
            get_identity_db().caregiver_patients.update_one(
                {"caregiver_user_id_auth": caregiver_uid, "patient_user_id_auth": patient_user_id_auth},
                {"$setOnInsert": {
                    "caregiver_user_id_auth": caregiver_uid,
                    "patient_user_id_auth": patient_user_id_auth,
                    "created_at": datetime.now(timezone.utc),
                }},
                upsert=True,
            )
            if existing_user.get("role") not in ("caregiver", "aidant"):
                get_identity_db().users.update_one(
                    {"user_id_auth": caregiver_uid},
                    {"$set": {"role": "caregiver"}},
                )
            logger.info("Auto-linked existing user %s as caregiver for %s", caregiver_uid, patient_user_id_auth)
        except PyMongoError as e:
            logger.warning("Failed to auto-link caregiver %s: %s", caregiver_uid, e)
        return None

    already_invited = get_identity_db().caregiver_invites.find_one({
        "patient_user_id_auth": patient_user_id_auth,
        "caregiver_email": emergency_email,
        "used_at": None,
        "expires_at": {"$gt": datetime.now(timezone.utc)},
    })
    if already_invited:
        logger.info("Caregiver invite already pending for %s → %s", patient_user_id_auth, emergency_email)
        return None

    invite_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=max(INVITE_TTL_HOURS, 1) * 7)  # 7 days for caregiver invites

    try:
        get_identity_db().caregiver_invites.insert_one({
            "token_hash": hash_secret_token(invite_token),
            "patient_user_id_auth": patient_user_id_auth,
            "caregiver_email": emergency_email,
            "expires_at": expires_at,
            "used_at": None,
            "created_at": now,
        })
    except PyMongoError as e:
        logger.warning("Failed to create caregiver invite for %s: %s", emergency_email, e)
        return None

    web_invite_url = f"{FRONTEND_URL.rstrip('/')}/invite-caregiver?token={invite_token}"

    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
        def _send_async():
            try:
                send_caregiver_invitation_email(
                    caregiver_email=emergency_email,
                    invite_token=invite_token,
                    web_invite_url=web_invite_url,
                    expires_at=expires_at,
                    patient_display_name=patient_display_name,
                )
            except Exception as e:
                logger.exception("Envoi email invitation aidant échoué: %s", e)

        threading.Thread(target=_send_async, daemon=True).start()
    else:
        logger.warning("SMTP not configured — caregiver invite created but email NOT sent for %s", emergency_email)

    return invite_token


def generate_invite_token() -> str:
    """Generate non-predictable invitation token."""
    return secrets.token_urlsafe(32)


def generate_cabinet_code() -> str:
    """Generate short non-predictable cabinet code."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


def log_link_audit_event(
    event_type: str,
    actor_user_id_auth: str,
    doctor_user_id_auth: str,
    patient_user_id_auth: str,
    mode: str,
    details: Optional[Dict[str, Any]] = None
):
    """Write immutable audit event for linkage operations."""
    get_identity_db().audit_links.insert_one({
        "event_type": event_type,
        "actor_user_id_auth": actor_user_id_auth,
        "doctor_user_id_auth": doctor_user_id_auth,
        "patient_user_id_auth": patient_user_id_auth,
        "mode": mode,
        "created_at": datetime.now(timezone.utc),
        "details": details or {},
    })


def create_doctor_patient_link(
    doctor_user_id_auth: str,
    patient_user_id_auth: str,
    linked_by: str,
    linked_by_user_id_auth: str
) -> bool:
    """
    Create doctor-patient link if absent.
    Returns True when created, False when already exists.
    """
    link_doc = {
        "doctor_user_id_auth": doctor_user_id_auth,
        "patient_user_id_auth": patient_user_id_auth,
        "linked_by": linked_by,
        "linked_by_user_id_auth": linked_by_user_id_auth,
        "created_at": datetime.now(timezone.utc),
    }
    result = get_identity_db().doctor_patients.update_one(
        {
            "doctor_user_id_auth": doctor_user_id_auth,
            "patient_user_id_auth": patient_user_id_auth,
        },
        {"$setOnInsert": link_doc},
        upsert=True
    )
    return result.upserted_id is not None


def get_invite_document_or_404(token_or_code: str, mode: str) -> Dict[str, Any]:
    """Fetch invite/code by hashed token and raise HTTP-oriented errors."""
    token_hash = hash_secret_token(token_or_code)
    invite = get_identity_db().doctor_invites.find_one({
        "token_hash": token_hash,
        "mode": mode,
    })
    if not invite:
        raise AuthError({
            "code": "invite_not_found",
            "message": "Invitation/code not found"
        }, 404)

    if invite.get("used_at"):
        raise AuthError({
            "code": "invite_already_used",
            "message": "Invitation/code already used"
        }, 409)

    expires_at = invite.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at < datetime.now(timezone.utc):
        raise AuthError({
            "code": "invite_expired",
            "message": "Invitation/code expired"
        }, 410)

    return invite


def get_user_profile(user_id_auth: str) -> Dict[str, Any]:
    """Get profile display data for one user from identity.users collection."""
    try:
        profile = get_identity_db().users.find_one(
            {"user_id_auth": user_id_auth},
            projection={
                "_id": 0, "display_name": 1, "email": 1,
                "first_name": 1, "last_name": 1, "age": 1, "sex": 1,
                "contact": 1, "picture": 1, "emergency_contact": 1,
            }
        )
        return profile or {}
    except PyMongoError as e:
        raise DatabaseError({
            "code": "user_profile_query_error",
            "message": f"Failed to query user profile: {str(e)}"
        }, 500)


def get_latest_device_measurement(device_id: str) -> Optional[Dict[str, Any]]:
    """Return latest measurement document for one device."""
    try:
        doc = get_medical_db().measurements.find_one(
            {"device_id": device_id},
            sort=[("measured_at", -1)],
            projection={"_id": 0}
        )
        return doc
    except PyMongoError as e:
        raise DatabaseError({
            "code": "latest_measurement_query_error",
            "message": f"Failed to query latest measurement: {str(e)}"
        }, 500)


def compute_alert_indicator(measurement: Optional[Dict[str, Any]]) -> bool:
    """Compute whether measurement should raise alert indicator on doctor dashboard."""
    if not measurement:
        return False
    if measurement.get("status") == "INVALID":
        return True

    hr = measurement.get("heart_rate")
    spo2 = measurement.get("spo2")
    temp = measurement.get("temperature")

    if hr is not None and (hr < 50 or hr > 120):
        return True
    if spo2 is not None and spo2 < 92:
        return True
    if temp is not None and (temp < 35.5 or temp > 38.0):
        return True
    return False


def query_patient_measurements(device_id: str, days: int, limit: int = 500) -> List[Dict[str, Any]]:
    """Query patient measurements constrained by lookback days and limit."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    try:
        cursor = get_medical_db().measurements.find(
            {"device_id": device_id, "measured_at": {"$gte": cutoff}},
            projection={"_id": 0}
        ).sort("measured_at", -1).limit(max(limit, 1))

        rows = []
        for doc in cursor:
            measured_at = doc.get("measured_at")
            timestamp = measured_at.isoformat() if isinstance(measured_at, datetime) else str(measured_at)
            rows.append({
                "timestamp": timestamp,
                "heart_rate": doc.get("heart_rate"),
                "spo2": doc.get("spo2"),
                "temperature": doc.get("temperature"),
                "signal_quality": doc.get("signal_quality"),
                "status": doc.get("status"),
                "source": doc.get("source", "device"),
            })
        return rows
    except PyMongoError as e:
        raise DatabaseError({
            "code": "patient_measurements_query_error",
            "message": f"Failed to query patient measurements: {str(e)}"
        }, 500)


def query_patient_measurements_for_devices(
    device_ids: List[str],
    days: int,
    limit: int = 2000,
) -> List[Dict[str, Any]]:
    """
    Query measurements for multiple patient devices in one request.
    """
    if not device_ids:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    try:
        cursor = get_medical_db().measurements.find(
            {"device_id": {"$in": device_ids}, "measured_at": {"$gte": cutoff}},
            projection={"_id": 0}
        ).sort("measured_at", -1).limit(max(limit, 1))

        rows = []
        for doc in cursor:
            measured_at = doc.get("measured_at")
            timestamp = measured_at.isoformat() if isinstance(measured_at, datetime) else str(measured_at)
            rows.append({
                "timestamp": timestamp,
                "measured_at": timestamp,
                "device_id": doc.get("device_id"),
                "heart_rate": doc.get("heart_rate"),
                "spo2": doc.get("spo2"),
                "temperature": doc.get("temperature"),
                "signal_quality": doc.get("signal_quality"),
                "status": doc.get("status"),
                "source": doc.get("source", "device"),
                "ml_score": doc.get("ml_score"),
                "ml_level": doc.get("ml_level"),
            })
        return rows
    except PyMongoError as e:
        raise DatabaseError({
            "code": "patient_measurements_query_error",
            "message": f"Failed to query patient measurements: {str(e)}"
        }, 500)


def query_patient_measurements_range(
    device_id: str,
    limit: int = 200,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """Query patient measurements by optional date range and limit."""
    query: Dict[str, Any] = {"device_id": device_id}
    if from_dt or to_dt:
        measured_at_query: Dict[str, Any] = {}
        if from_dt:
            measured_at_query["$gte"] = from_dt
        if to_dt:
            measured_at_query["$lte"] = to_dt
        query["measured_at"] = measured_at_query

    try:
        cursor = get_medical_db().measurements.find(
            query,
            projection={"_id": 0}
        ).sort("measured_at", -1).limit(min(max(limit, 1), 1000))

        rows = []
        for doc in cursor:
            measured_at = doc.get("measured_at")
            timestamp = measured_at.isoformat() if isinstance(measured_at, datetime) else str(measured_at)
            rows.append({
                "timestamp": timestamp,
                "heart_rate": doc.get("heart_rate"),
                "spo2": doc.get("spo2"),
                "temperature": doc.get("temperature"),
                "signal_quality": doc.get("signal_quality"),
                "status": doc.get("status"),
                "source": doc.get("source", "device"),
            })
        return rows
    except PyMongoError as e:
        raise DatabaseError({
            "code": "patient_measurements_query_error",
            "message": f"Failed to query patient measurements: {str(e)}"
        }, 500)


def list_latest_doctor_feedback(patient_user_id_auth: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Return latest doctor feedback entries for one patient."""
    try:
        cursor = get_medical_db().doctor_feedback.find(
            {"patient_user_id_auth": patient_user_id_auth},
            projection={"_id": 0}
        ).sort("created_at", -1).limit(min(max(limit, 1), 50))

        feedbacks = []
        for doc in cursor:
            created_at = doc.get("created_at")
            feedbacks.append({
                "patient_user_id_auth": doc.get("patient_user_id_auth"),
                "doctor_user_id_auth": doc.get("doctor_user_id_auth"),
                "message": doc.get("message"),
                "severity": doc.get("severity"),
                "status": doc.get("status"),
                "recommendation": doc.get("recommendation"),
                "created_at": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
            })
        return feedbacks
    except PyMongoError as e:
        raise DatabaseError({
            "code": "doctor_feedback_query_error",
            "message": f"Failed to query doctor feedback: {str(e)}"
        }, 500)


def build_assigned_patients_payload(patient_ids: List[str]) -> List[Dict[str, Any]]:
    """Build patient cards (profile + latest measurements) for doctor/caregiver views."""
    patients = []
    for patient_user_id_auth in patient_ids:
        device_id = get_device_id(patient_user_id_auth)
        profile = get_user_profile(patient_user_id_auth)
        latest_measurement = get_latest_device_measurement(device_id) if device_id else None
        measured_at = latest_measurement.get("measured_at") if latest_measurement else None
        measured_at_iso = measured_at.isoformat() if isinstance(measured_at, datetime) else None

        patients.append({
            "patient_id": patient_user_id_auth,
            "display_name": profile.get("display_name") or profile.get("email") or patient_user_id_auth,
            "device_id": device_id,
            "last_measurement": {
                "timestamp": measured_at_iso,
                "spo2": latest_measurement.get("spo2") if latest_measurement else None,
                "heart_rate": latest_measurement.get("heart_rate") if latest_measurement else None,
                "temperature": latest_measurement.get("temperature") if latest_measurement else None,
                "status": latest_measurement.get("status") if latest_measurement else None,
            } if latest_measurement else None,
            "alert": compute_alert_indicator(latest_measurement)
        })
    return patients


def build_trend_window(measurements: List[Dict[str, Any]], days: int) -> Dict[str, Any]:
    """Compute trend summary for one lookback window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    filtered = []
    for row in measurements:
        try:
            ts = datetime.fromisoformat(str(row.get("timestamp")).replace("Z", "+00:00"))
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
            if ts >= cutoff:
                filtered.append(row)
        except Exception:
            continue

    filtered_sorted = sorted(filtered, key=lambda row: row.get("timestamp", ""))
    if not filtered_sorted:
        return {
            "days": days,
            "count": 0,
            "averages": {"spo2": None, "heart_rate": None, "temperature": None},
            "delta": {"spo2": None, "heart_rate": None, "temperature": None},
            "series": []
        }

    def avg(key: str) -> Optional[float]:
        values = [row.get(key) for row in filtered_sorted if isinstance(row.get(key), (int, float))]
        if not values:
            return None
        return round(sum(values) / len(values), 2)

    first = filtered_sorted[0]
    last = filtered_sorted[-1]

    def compute_delta(key: str) -> Optional[float]:
        first_value = first.get(key)
        last_value = last.get(key)
        if not isinstance(first_value, (int, float)) or not isinstance(last_value, (int, float)):
            return None
        return round(last_value - first_value, 2)

    series = filtered_sorted[-120:]
    return {
        "days": days,
        "count": len(filtered_sorted),
        "averages": {
            "spo2": avg("spo2"),
            "heart_rate": avg("heart_rate"),
            "temperature": avg("temperature"),
        },
        "delta": {
            "spo2": compute_delta("spo2"),
            "heart_rate": compute_delta("heart_rate"),
            "temperature": compute_delta("temperature"),
        },
        "series": series
    }


def parse_measurement_timestamp(timestamp_value: Optional[str]) -> datetime:
    """Parse measurement timestamp with ISO fallback to current UTC time."""
    if not timestamp_value:
        return datetime.now(timezone.utc)
    try:
        normalized = timestamp_value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except Exception:
        return datetime.now(timezone.utc)


def validate_measurement_values(
    heart_rate: Any,
    spo2: Any,
    temperature: Any,
    signal_quality: Any = None,
    require_signal_quality: bool = False
) -> List[str]:
    """Validate measurement values and return reason codes for invalid fields."""
    reasons = []

    if heart_rate is None or heart_rate < 30 or heart_rate > 220:
        reasons.append("heart_rate_out_of_range")

    if spo2 is None or spo2 < 70 or spo2 > 100:
        reasons.append("spo2_out_of_range")

    if temperature is None or temperature < 34 or temperature > 42:
        reasons.append("temperature_out_of_range")

    if require_signal_quality or signal_quality is not None:
        if signal_quality is None or signal_quality < 50:
            reasons.append("low_signal_quality")

    return reasons


def normalize_patient_measurement_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize and validate payload sent by patient app."""
    required_fields = ["heart_rate", "spo2", "temperature"]
    missing = [field for field in required_fields if field not in payload]
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}")

    try:
        heart_rate = float(payload["heart_rate"])
        spo2 = float(payload["spo2"])
        temperature = float(payload["temperature"])
        signal_quality_raw = payload.get("signal_quality")
        signal_quality = float(signal_quality_raw) if signal_quality_raw is not None else None
    except (TypeError, ValueError):
        raise ValueError("heart_rate, spo2, temperature and signal_quality must be numeric")

    source = payload.get("source", "simulation")
    if source not in ("simulation", "device"):
        raise ValueError("source must be 'simulation' or 'device'")

    measured_at = parse_measurement_timestamp(payload.get("measured_at"))
    reasons = validate_measurement_values(
        heart_rate=heart_rate,
        spo2=spo2,
        temperature=temperature,
        signal_quality=signal_quality,
        require_signal_quality=False
    )

    return {
        "measured_at": measured_at,
        "heart_rate": heart_rate,
        "spo2": spo2,
        "temperature": temperature,
        "signal_quality": signal_quality,
        "source": source,
        "reasons": reasons,
        "status": "VALID" if not reasons else "INVALID"
    }


def merge_thresholds(raw_thresholds: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Return complete threshold dictionary with defaults."""
    thresholds = dict(ALERT_DEFAULT_THRESHOLDS)
    if not isinstance(raw_thresholds, dict):
        return thresholds

    for key in ALERT_DEFAULT_THRESHOLDS.keys():
        value = raw_thresholds.get(key)
        if value is None:
            continue
        try:
            thresholds[key] = float(value)
        except (TypeError, ValueError):
            continue
    return thresholds


def get_alert_threshold_config(device_id: str, pathology: Optional[str] = None) -> Dict[str, Any]:
    """
    Resolve alert thresholds with priority:
    1) patient/device scope
    2) pathology scope (if provided)
    3) default scope in DB
    4) hardcoded defaults
    """
    collection = get_medical_db().alert_thresholds
    config = None
    scope = "builtin_default"

    try:
        config = collection.find_one({"scope": "patient", "device_id": device_id, "enabled": True})
        if config:
            scope = "patient"
        elif pathology:
            config = collection.find_one({"scope": "pathology", "pathology": pathology, "enabled": True})
            if config:
                scope = "pathology"
        if not config:
            config = collection.find_one({"scope": "default", "enabled": True})
            if config:
                scope = "default"
    except PyMongoError:
        # Non-blocking fallback to hardcoded defaults.
        config = None
        scope = "builtin_default"

    thresholds = merge_thresholds((config or {}).get("thresholds"))
    consecutive = (config or {}).get("consecutive_breaches", ALERT_DEFAULT_CONSECUTIVE_BREACHES)
    try:
        consecutive = max(1, int(consecutive))
    except (TypeError, ValueError):
        consecutive = ALERT_DEFAULT_CONSECUTIVE_BREACHES

    return {
        "scope": scope,
        "thresholds": thresholds,
        "consecutive_breaches": consecutive,
        "pathology": (config or {}).get("pathology"),
    }


def compute_metric_breaches(measurement: Dict[str, Any], thresholds: Dict[str, float]) -> List[Dict[str, Any]]:
    """Return the list of metric breaches found on the measurement."""
    breaches = []

    hr = measurement.get("heart_rate")
    if isinstance(hr, (int, float)):
        if hr < thresholds["heart_rate_min"]:
            breaches.append({"metric": "heart_rate", "operator": "lt", "threshold": thresholds["heart_rate_min"], "value": hr})
        elif hr > thresholds["heart_rate_max"]:
            breaches.append({"metric": "heart_rate", "operator": "gt", "threshold": thresholds["heart_rate_max"], "value": hr})

    spo2 = measurement.get("spo2")
    if isinstance(spo2, (int, float)) and spo2 < thresholds["spo2_min"]:
        breaches.append({"metric": "spo2", "operator": "lt", "threshold": thresholds["spo2_min"], "value": spo2})

    temp = measurement.get("temperature")
    if isinstance(temp, (int, float)):
        if temp < thresholds["temperature_min"]:
            breaches.append({"metric": "temperature", "operator": "lt", "threshold": thresholds["temperature_min"], "value": temp})
        elif temp > thresholds["temperature_max"]:
            breaches.append({"metric": "temperature", "operator": "gt", "threshold": thresholds["temperature_max"], "value": temp})

    return breaches


def has_consecutive_breach(device_id: str, breach: Dict[str, Any], consecutive_required: int) -> bool:
    """Check if the same breach condition appears on N consecutive valid measurements."""
    metric = breach["metric"]
    operator = breach["operator"]
    threshold = breach["threshold"]
    cursor = get_medical_db().measurements.find(
        {
            "device_id": device_id,
            "status": {"$ne": "INVALID"},
        },
        projection={"_id": 0, metric: 1, "measured_at": 1}
    ).sort("measured_at", -1).limit(consecutive_required)

    rows = list(cursor)
    if len(rows) < consecutive_required:
        return False

    for row in rows:
        value = row.get(metric)
        if not isinstance(value, (int, float)):
            return False
        if operator == "lt" and value >= threshold:
            return False
        if operator == "gt" and value <= threshold:
            return False
    return True


def upsert_open_alert(device_id: str, breach: Dict[str, Any], threshold_config: Dict[str, Any], measured_at: datetime):
    """Create or update an open alert for a durable breach."""
    metric = breach["metric"]
    operator = breach["operator"]
    query = {"device_id": device_id, "metric": metric, "operator": operator, "status": "OPEN"}
    now = datetime.now(timezone.utc)
    set_fields = {
        "threshold": breach["threshold"],
        "latest_value": breach["value"],
        "consecutive_required": threshold_config["consecutive_breaches"],
        "last_breach_at": measured_at,
        "rule_scope": threshold_config["scope"],
        "updated_at": now,
    }
    set_on_insert = {
        "device_id": device_id,
        "metric": metric,
        "operator": operator,
        "status": "OPEN",
        "created_at": now,
        "first_breach_at": measured_at,
    }
    get_medical_db().alerts.update_one(
        query,
        {"$set": set_fields, "$setOnInsert": set_on_insert},
        upsert=True
    )


def resolve_metric_alert(device_id: str, metric: str):
    """Resolve open alerts for a metric once value is back in-range."""
    get_medical_db().alerts.update_many(
        {"device_id": device_id, "metric": metric, "status": "OPEN"},
        {"$set": {"status": "RESOLVED", "resolved_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}}
    )


def evaluate_measurement_alerts(device_id: str, measurement: Dict[str, Any], pathology: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Evaluate one ingested measurement and create alerts only for durable breaches.
    Returns durable breaches that triggered/updated OPEN alerts.
    """
    if measurement.get("status") == "INVALID":
        return []

    threshold_config = get_alert_threshold_config(device_id=device_id, pathology=pathology)
    thresholds = threshold_config["thresholds"]
    breaches = compute_metric_breaches(measurement, thresholds)
    durable = []
    measured_at = measurement.get("measured_at")
    if not isinstance(measured_at, datetime):
        measured_at = datetime.now(timezone.utc)

    breached_metrics = {breach["metric"] for breach in breaches}
    for metric in ("heart_rate", "spo2", "temperature"):
        if metric not in breached_metrics:
            resolve_metric_alert(device_id, metric)

    for breach in breaches:
        if has_consecutive_breach(device_id, breach, threshold_config["consecutive_breaches"]):
            upsert_open_alert(device_id, breach, threshold_config, measured_at)
            durable.append({
                "metric": breach["metric"],
                "operator": breach["operator"],
                "value": breach["value"],
                "threshold": breach["threshold"],
                "scope": threshold_config["scope"],
            })

    return durable


# ============================================================================
# ML SCORING PIPELINE  (features #1-#3, #6, #8-#10)
# ============================================================================

def run_ml_scoring(device_id: str, measurement_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score one measurement through the ML module, persist the audit decision,
    create an anomaly event if critical, and enrich the measurement document
    with all ML flags.
    Returns the ml_result dict.
    """
    ml_result = ml_module.score_measurement(measurement_doc)

    is_anomaly = ml_result.get("ml_is_anomaly", False)
    ml_level = ml_result.get("ml_level")

    measurement_update = {
        "ml_score": ml_result["ml_score"],
        "ml_level": ml_level,
        "ml_model_version": ml_result["ml_model_version"],
        "ml_contributing_variables": ml_result.get("ml_contributing_variables", []),
        "ml_is_anomaly": is_anomaly,
        "ml_criticality": ml_result.get("ml_criticality", "normal"),
        "ml_recommended_action": ml_result.get("ml_recommended_action"),
        "ml_anomaly_status": "pending" if is_anomaly and ml_level == "critical" else "none",
    }

    suggestion = None
    if not ml_result.get("ml_skipped"):
        suggestion = {
            "recommended_action": ml_result.get("ml_recommended_action"),
            "clinical_reasoning": ml_result.get("ml_clinical_reasoning", []),
            "urgency": ml_result.get("ml_urgency", "routine"),
        }

        decision_doc = {
            "measurement_id": measurement_doc.get("_id"),
            "device_id": device_id,
            "measured_at": measurement_doc.get("measured_at"),
            "anomaly_score": ml_result["ml_score"],
            "anomaly_level": ml_level,
            "model_version": ml_result["ml_model_version"],
            "contributing_variables": ml_result["ml_contributing_variables"],
            "recommended_action": suggestion["recommended_action"],
            "clinical_reasoning": suggestion["clinical_reasoning"],
            "urgency": suggestion["urgency"],
            "processed_at": datetime.now(timezone.utc),
        }
        try:
            get_medical_db().ml_decisions.insert_one(decision_doc)
        except PyMongoError:
            logger.warning("Failed to insert ml_decision for device %s", device_id)

    user_id_auth = None
    try:
        mapping = get_identity_db().users_devices.find_one({"device_id": device_id})
        if mapping:
            user_id_auth = mapping.get("user_id_auth")
    except PyMongoError:
        pass

    anomaly_event = ml_module.build_anomaly_event(
        device_id=device_id,
        user_id_auth=user_id_auth,
        measurement_id=measurement_doc.get("_id"),
        measurement=measurement_doc,
        ml_result=ml_result,
        suggestion=suggestion,
    )
    if anomaly_event:
        try:
            insert_result = get_medical_db().ml_anomalies.insert_one(anomaly_event)
            anomaly_oid = insert_result.inserted_id
            measurement_update["ml_anomaly_id"] = anomaly_oid
            measurement_update["ml_anomaly_status"] = "pending"
            logger.info("ML anomaly event created for device %s (score=%.3f)", device_id, ml_result["ml_score"])
        except PyMongoError:
            logger.warning("Failed to insert ml_anomaly for device %s", device_id)

    try:
        get_medical_db().measurements.update_one(
            {"_id": measurement_doc.get("_id")},
            {"$set": measurement_update}
        )
    except PyMongoError:
        logger.warning("Failed to update measurement with ML fields for device %s", device_id)

    return ml_result


# ============================================================================
# API ROUTES
# ============================================================================

def _split_display_name(display_name: str) -> tuple:
    """Split 'Dr. Jean Dupont' or 'Jean Dupont' into (first_name, last_name)."""
    if not display_name or not isinstance(display_name, str):
        return ("", "")
    parts = str(display_name).strip().split(None, 2)  # max 3 parts: Dr., Jean, Dupont
    if len(parts) >= 3:
        return (parts[1], parts[2])  # Jean, Dupont
    if len(parts) == 2:
        return (parts[0], parts[1])
    if len(parts) == 1:
        return (parts[0], "")
    return ("", "")


@app.route("/api/me/role", methods=["GET"])
@requires_auth
def get_my_role():
    """
    Return the authenticated user's role from the database.
    Works for all roles (patient, doctor, caregiver, admin).
    Returns display-friendly role: Superuser, Médecin, Patient, Aidant, Admin.
    Used by the frontend at login time for routing and UI display.
    """
    user_id_auth = g.user_id_auth
    payload = getattr(g, "jwt_payload", {}) or {}
    ns = "https://vitalio.app/"

    db_role = get_user_role(user_id_auth)
    jwt_role = (payload.get(f"{ns}role") or payload.get("role") or "").strip()
    role_raw = (db_role or jwt_role or "").strip().lower()

    role_display_map = {
        "superuser": "Superuser",
        "doctor": "Médecin",
        "medecin": "Médecin",
        "médecin": "Médecin",
        "patient": "Patient",
        "caregiver": "Aidant",
        "aidant": "Aidant",
        "admin": "Admin",
    }
    display_role = role_display_map.get(role_raw, "Patient")
    return jsonify({"role": display_role, "user_id_auth": user_id_auth}), 200


@app.route("/api/me/profile", methods=["GET"])
@requires_auth
@requires_role("patient")
def get_my_profile():
    """
    Return current patient profile and assigned doctors.
    Patient: email, first_name, last_name, age, sex.
    Doctors: first_name, last_name, contact (no auth IDs in display data).
    """
    user_id_auth = g.user_id_auth
    profile = get_user_profile(user_id_auth)
    payload = getattr(g, "jwt_payload", {}) or {}
    profile_data = {
        "email": profile.get("email") or payload.get("email") or "",
        "first_name": profile.get("first_name") or payload.get("given_name") or "",
        "last_name": profile.get("last_name") or payload.get("family_name") or "",
        "age": profile.get("age"),
        "sex": profile.get("sex"),
        "picture": profile.get("picture") or payload.get("picture") or "",
        "emergency_contact": profile.get("emergency_contact") or None,
    }
    if not profile_data["first_name"] and not profile_data["last_name"]:
        name = profile.get("display_name") or payload.get("name") or ""
        if name:
            profile_data["first_name"], profile_data["last_name"] = _split_display_name(name)
    doctor_ids = get_assigned_doctor_ids_for_patient(user_id_auth)
    doctors = []
    for idx, did in enumerate(doctor_ids):
        doc_profile = get_user_profile(did)
        disp = doc_profile.get("display_name") or doc_profile.get("email") or ""
        fname, lname = _split_display_name(disp) if disp else ("", "")
        if not fname and not lname:
            fname = disp
        contact = doc_profile.get("contact") or doc_profile.get("email") or ""
        doctors.append({
            "id": idx,
            "first_name": fname,
            "last_name": lname,
            "contact": contact,
        })
    return jsonify({
        "profile": profile_data,
        "doctors": doctors,
    }), 200


@app.route("/api/me/profile", methods=["PATCH"])
@requires_auth
@requires_role("patient", "doctor", "caregiver", "admin", "superuser", "medecin", "aidant")
def patch_my_profile():
    """Update user profile fields (all roles). Supports emergency_contact sub-object for patients."""
    _EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    ALLOWED_PROFILE_FIELDS = {
        "first_name":   (str, 64),
        "last_name":    (str, 64),
        "age":          (int, None),
        "sex":          (str, 16),
        "display_name": (str, 128),
        "email":        (str, 256),
        "picture":      (str, 512),
    }

    payload = request.get_json(silent=True) or {}
    updates = {}

    for field, (ftype, max_len) in ALLOWED_PROFILE_FIELDS.items():
        if field not in payload:
            continue
        raw = payload[field]
        if ftype is int:
            try:
                val = int(raw)
                updates[field] = val if 0 <= val <= 150 else None
            except (TypeError, ValueError):
                updates[field] = None
        elif field == "sex":
            val = str(raw or "").strip().lower()
            updates[field] = val if val in ("m", "f", "homme", "femme", "autre") else None
        elif field == "email":
            val = str(raw or "").strip()[:max_len]
            if val and not _EMAIL_RE.match(val):
                return jsonify({"code": "invalid_email", "message": "Invalid email format"}), 422
            updates[field] = val or None
        elif field == "picture":
            val = str(raw or "").strip()[:max_len]
            if val and not val.startswith(("https://", "http://")):
                return jsonify({"code": "invalid_picture", "message": "Picture must be a URL"}), 422
            updates[field] = val or None
        else:
            updates[field] = str(raw or "")[:max_len] or None

    # Handle emergency_contact sub-object
    new_emergency_email = None
    if "emergency_contact" in payload and isinstance(payload["emergency_contact"], dict):
        ec = payload["emergency_contact"]
        emergency = {
            "last_name":  str(ec.get("last_name") or "").strip()[:64] or None,
            "first_name": str(ec.get("first_name") or "").strip()[:64] or None,
            "phone":      str(ec.get("phone") or "").strip()[:32] or None,
            "email":      None,
        }
        ec_email = str(ec.get("email") or "").strip()[:256]
        if ec_email:
            if not _EMAIL_RE.match(ec_email):
                return jsonify({"code": "invalid_emergency_email", "message": "Invalid emergency contact email"}), 422
            emergency["email"] = ec_email
            new_emergency_email = ec_email

        has_any = any(v for v in emergency.values())
        updates["emergency_contact"] = emergency if has_any else None

    if not updates:
        return jsonify({"message": "No fields to update"}), 400

    set_doc = {**updates, "updated_at": datetime.now(timezone.utc)}
    payload = getattr(g, "jwt_payload", {}) or {}
    ns = "https://vitalio.app/"
    jwt_role = (payload.get(f"{ns}role") or payload.get("role") or "").strip().lower()
    role_map = {"doctor": "medecin", "medecin": "medecin", "superuser": "medecin", "patient": "patient", "caregiver": "aidant", "aidant": "aidant", "admin": "admin"}
    default_role = role_map.get(jwt_role, jwt_role or "patient")

    set_on_insert = {
        "user_id_auth": g.user_id_auth,
        "role": default_role,
        "created_at": datetime.now(timezone.utc),
    }
    if "display_name" not in set_doc:
        set_on_insert["display_name"] = updates.get("display_name") or updates.get("email") or g.user_id_auth

    try:
        get_identity_db().users.update_one(
            {"user_id_auth": g.user_id_auth},
            {
                "$set": set_doc,
                "$setOnInsert": set_on_insert,
            },
            upsert=True,
        )
    except PyMongoError as e:
        raise DatabaseError({"code": "update_error", "message": str(e)}, 500)

    if new_emergency_email:
        patient_profile = get_user_profile(g.user_id_auth)
        patient_name = patient_profile.get("display_name") or patient_profile.get("email") or "Un patient VitalIO"
        invite_emergency_contact_if_needed(g.user_id_auth, new_emergency_email, patient_name)

    return jsonify({"message": "Profile updated"}), 200


@app.route("/api/me/data", methods=["GET"])
@requires_auth
@requires_role("patient")
def get_patient_data():
    """
    Protected route to fetch patient medical data.
    
    Implements complete sequence (Steps 1-10):
    1. Frontend authenticates via Auth0 (handled by frontend)
    2. Auth0 returns signed JWT (handled by Auth0)
    3. Frontend calls GET /api/me/data with Authorization: Bearer <JWT> (this route)
    4. Flask API verifies JWT (handled by @requires_auth decorator)
    5. API authorizes request and identifies user as patient (handled by @requires_auth)
    6. API resolves/creates internal user (public.users) from Auth0 subject
    7. API queries correspondence database (get_device_id) using internal user UUID
    8. Correspondence database returns device_id (UUID -> devices.id)
    9. API queries medical database (get_device_measurements)
    10. Medical database returns vital measurements
    11. API returns minimal device identity + medical measurements
    
    Returns:
        JSON response containing:
        - device_id: Minimal device identity (pivot ID only, UUID -> devices.id)
        - measurements: List of vital measurements
        
    Raises:
        AuthError: If authentication fails
        DatabaseError: If database queries fail
    """
    # g.user_id contains the internal UUID from public.users.id
    
    device_id = get_device_id(g.user_id)
    
    if not device_id:
        raise DatabaseError({
            "code": "device_not_found",
            "message": "No device record found for authenticated user"
        }, 404)
    
    # Query medical database to get vital measurements
    measurements = get_device_measurements(device_id)
    
    # Return minimal device identity (device_id only) + medical measurements
    return jsonify({
        "device_id": device_id,
        "measurements": measurements,
        "measurement_count": len(measurements)
    }), 200


@app.route("/api/me/measurements", methods=["POST"])
@requires_auth
@requires_role("patient")
def submit_patient_measurement():
    """
    Protected route to submit one measurement from patient interface.
    Uses authenticated user_id -> device_id mapping before insert.
    """
    device_id = get_device_id(g.user_id_auth)
    if not device_id:
        raise DatabaseError({
            "code": "device_not_found",
            "message": "No device record found for authenticated user"
        }, 404)

    payload = request.get_json(silent=True) or {}
    try:
        normalized = normalize_patient_measurement_payload(payload)
    except ValueError as validation_error:
        return jsonify({
            "code": "invalid_payload",
            "message": str(validation_error)
        }), 400

    measurement_doc = {
        "device_id": device_id,
        "measured_at": normalized["measured_at"],
        "heart_rate": normalized["heart_rate"],
        "spo2": normalized["spo2"],
        "temperature": normalized["temperature"],
        "signal_quality": normalized["signal_quality"],
        "source": normalized["source"],
        "status": normalized["status"],
        "validation_reasons": normalized["reasons"],
    }

    try:
        get_medical_db().measurements.insert_one(measurement_doc)
    except PyMongoError as e:
        raise DatabaseError({
            "code": "measurement_insert_error",
            "message": f"Failed to insert measurement: {str(e)}"
        }, 500)

    triggered_alerts = []
    try:
        triggered_alerts = evaluate_measurement_alerts(device_id=device_id, measurement=measurement_doc)
    except PyMongoError as e:
        print(f"Warning: alert evaluation failed for device {device_id}: {str(e)}")

    ml_result: Dict[str, Any] = {}
    try:
        ml_result = run_ml_scoring(device_id=device_id, measurement_doc=measurement_doc)
    except Exception as e:
        logger.warning("ML scoring failed for device %s: %s", device_id, e)

    return jsonify({
        "message": "Measurement stored successfully",
        "device_id": device_id,
        "measurement": {
            "timestamp": normalized["measured_at"].isoformat(),
            "heart_rate": normalized["heart_rate"],
            "spo2": normalized["spo2"],
            "temperature": normalized["temperature"],
            "signal_quality": normalized["signal_quality"],
            "status": normalized["status"],
            "validation_reasons": normalized["reasons"],
            "source": normalized["source"],
        },
        "alerts_triggered": triggered_alerts,
        "ml": {
            "score": ml_result.get("ml_score"),
            "level": ml_result.get("ml_level"),
            "model_version": ml_result.get("ml_model_version"),
            "contributing_variables": ml_result.get("ml_contributing_variables", []),
            "skipped": ml_result.get("ml_skipped", False),
        } if ml_result else None,
    }), 201


def _normalize_email(email_raw: str) -> Optional[str]:
    """Validate and normalize email address."""
    if not email_raw or not isinstance(email_raw, str):
        return None
    s = str(email_raw).strip().lower()
    if "@" in s and "." in s and len(s) > 5:
        return s
    return None


@app.route("/api/doctor/invitations", methods=["POST"])
@requires_auth
@requires_role("doctor", "superuser")
def create_doctor_invitation():
    """Doctor creates invitation token (24h TTL by default). Optionally sends QR by email to patient."""
    payload = request.get_json(silent=True) or {}
    patient_user_id_auth_raw = payload.get("patient_user_id_auth")
    patient_email_raw = payload.get("patient_email")
    send_email = payload.get("send_email", False) is True

    logger.debug("create_doctor_invitation payload: send_email=%s, patient_email=%s", send_email, patient_email_raw)

    patient_user_id_auth = None
    if patient_user_id_auth_raw is not None and str(patient_user_id_auth_raw).strip():
        try:
            patient_user_id_auth = normalize_user_id_auth(patient_user_id_auth_raw, "patient_user_id_auth")
        except ValueError as e:
            return jsonify({"code": "invalid_payload", "message": str(e)}), 400
        patient_role = get_user_role(patient_user_id_auth)
        if patient_role != "patient":
            return jsonify({
                "code": "invalid_patient",
                "message": "patient_user_id_auth must reference a user with role 'patient'"
            }), 400

    patient_email = None
    if send_email:
        patient_email = _normalize_email(patient_email_raw)
        if not patient_email and patient_user_id_auth:
            profile = get_user_profile(patient_user_id_auth)
            patient_email = _normalize_email(profile.get("email") or "")
        if not patient_email:
            return jsonify({
                "code": "invalid_payload",
                "message": "patient_email is required when send_email is true (or patient must have email in profile)"
            }), 400

    invite_token = generate_invite_token()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=max(INVITE_TTL_HOURS, 1))
    invite_doc = {
        "token_hash": hash_secret_token(invite_token),
        "doctor_user_id_auth": g.user_id_auth,
        "patient_user_id_auth": patient_user_id_auth,
        "expires_at": expires_at,
        "used_at": None,
        "created_at": now,
        "created_by_user_id_auth": g.user_id_auth,
        "mode": "invite_link",
        "metadata": {"targeted": bool(patient_user_id_auth)},
    }

    try:
        get_identity_db().doctor_invites.insert_one(invite_doc)
        log_link_audit_event(
            event_type="invite_created",
            actor_user_id_auth=g.user_id_auth,
            doctor_user_id_auth=g.user_id_auth,
            patient_user_id_auth=patient_user_id_auth or "",
            mode="invite_link",
            details={"targeted": bool(patient_user_id_auth), "expires_at": expires_at.isoformat()},
        )
    except PyMongoError as e:
        raise DatabaseError({
            "code": "invite_insert_error",
            "message": f"Failed to create invitation: {str(e)}"
        }, 500)

    web_invite_url = f"{FRONTEND_URL.rstrip('/')}/invite?token={invite_token}"
    doctor_profile = get_user_profile(g.user_id_auth)
    doctor_display_name = doctor_profile.get("display_name") or doctor_profile.get("email") or "Votre médecin"

    if send_email and patient_email:
        if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
            return jsonify({"code": "email_config_error", "message": "SMTP non configuré"}), 503
        # Envoi en arrière-plan pour ne pas bloquer la réponse
        def _send_async():
            try:
                send_invitation_email(
                    patient_email=patient_email,
                    invite_token=invite_token,
                    web_invite_url=web_invite_url,
                    expires_at=expires_at,
                    doctor_display_name=doctor_display_name,
                )
            except Exception as e:
                logger.exception("Envoi email invitation échoué (background): %s", e)

        threading.Thread(target=_send_async, daemon=True).start()

    return jsonify({
        "invite_token": invite_token,
        "expires_at": expires_at.isoformat(),
        "deep_link": f"vitalio://invite?token={invite_token}",
        "web_invite_url": web_invite_url,
        "qr_payload": web_invite_url,
        "mode": "invite_link",
        "target_patient_user_id_auth": patient_user_id_auth,
        "email_sent": bool(send_email and patient_email),
    }), 201


@app.route("/api/patient/invitations/accept", methods=["POST"])
@requires_auth
@requires_role("patient")
def accept_doctor_invitation():
    """Patient accepts one invitation token and creates doctor-patient relation."""
    payload = request.get_json(silent=True) or {}
    invite_token = str(payload.get("invite_token") or "").strip()
    if not invite_token:
        return jsonify({"code": "invalid_payload", "message": "invite_token is required"}), 400

    invite = get_invite_document_or_404(invite_token, mode="invite_link")
    patient_target = invite.get("patient_user_id_auth")
    if patient_target and patient_target != g.user_id_auth:
        raise AuthError({
            "code": "forbidden_invitation",
            "message": "This invitation is targeted to another patient"
        }, 403)

    doctor_user_id_auth = invite.get("doctor_user_id_auth")
    created = create_doctor_patient_link(
        doctor_user_id_auth=doctor_user_id_auth,
        patient_user_id_auth=g.user_id_auth,
        linked_by="patient_accept_invite",
        linked_by_user_id_auth=g.user_id_auth
    )
    if not created:
        raise AuthError({
            "code": "association_exists",
            "message": "Doctor-patient association already exists"
        }, 409)

    now = datetime.now(timezone.utc)
    get_identity_db().doctor_invites.update_one(
        {"_id": invite["_id"], "used_at": None},
        {"$set": {"used_at": now, "used_by_user_id_auth": g.user_id_auth}}
    )
    log_link_audit_event(
        event_type="invite_accepted",
        actor_user_id_auth=g.user_id_auth,
        doctor_user_id_auth=doctor_user_id_auth,
        patient_user_id_auth=g.user_id_auth,
        mode="invite_link",
        details={"invite_created_at": str(invite.get("created_at"))},
    )

    return jsonify({
        "message": "Invitation accepted",
        "doctor_user_id_auth": doctor_user_id_auth,
        "patient_user_id_auth": g.user_id_auth
    }), 201


@app.route("/api/doctor/cabinet-codes", methods=["POST"])
@requires_auth
@requires_role("doctor")
def create_doctor_cabinet_code():
    """Doctor generates one short-lived single-use cabinet code."""
    payload = request.get_json(silent=True) or {}
    ttl_minutes = payload.get("ttl_minutes", CABINET_CODE_TTL_MINUTES_DEFAULT)
    try:
        ttl_minutes = int(ttl_minutes)
    except (TypeError, ValueError):
        return jsonify({"code": "invalid_payload", "message": "ttl_minutes must be an integer"}), 400
    ttl_minutes = min(max(ttl_minutes, 10), 30)

    code = generate_cabinet_code()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ttl_minutes)
    invite_doc = {
        "token_hash": hash_secret_token(code),
        "doctor_user_id_auth": g.user_id_auth,
        "patient_user_id_auth": None,
        "expires_at": expires_at,
        "used_at": None,
        "created_at": now,
        "created_by_user_id_auth": g.user_id_auth,
        "mode": "cabinet_code",
        "metadata": {"ttl_minutes": ttl_minutes},
    }

    try:
        get_identity_db().doctor_invites.insert_one(invite_doc)
        log_link_audit_event(
            event_type="cabinet_code_created",
            actor_user_id_auth=g.user_id_auth,
            doctor_user_id_auth=g.user_id_auth,
            patient_user_id_auth="",
            mode="cabinet_code",
            details={"expires_at": expires_at.isoformat(), "ttl_minutes": ttl_minutes},
        )
    except PyMongoError as e:
        raise DatabaseError({
            "code": "cabinet_code_insert_error",
            "message": f"Failed to create cabinet code: {str(e)}"
        }, 500)

    return jsonify({
        "code": code,
        "expires_at": expires_at.isoformat(),
        "qr_payload": f"vitalio://cabinet-code?code={code}",
        "mode": "cabinet_code",
    }), 201


@app.route("/api/patient/cabinet-codes/redeem", methods=["POST"])
@requires_auth
@requires_role("patient")
def redeem_cabinet_code():
    """Patient redeems one cabinet code to create doctor-patient relation."""
    payload = request.get_json(silent=True) or {}
    code = str(payload.get("code") or "").strip().upper()
    if not code:
        return jsonify({"code": "invalid_payload", "message": "code is required"}), 400

    invite = get_invite_document_or_404(code, mode="cabinet_code")
    doctor_user_id_auth = invite.get("doctor_user_id_auth")

    created = create_doctor_patient_link(
        doctor_user_id_auth=doctor_user_id_auth,
        patient_user_id_auth=g.user_id_auth,
        linked_by="cabinet_code",
        linked_by_user_id_auth=g.user_id_auth
    )
    if not created:
        raise AuthError({
            "code": "association_exists",
            "message": "Doctor-patient association already exists"
        }, 409)

    now = datetime.now(timezone.utc)
    get_identity_db().doctor_invites.update_one(
        {"_id": invite["_id"], "used_at": None},
        {"$set": {"used_at": now, "used_by_user_id_auth": g.user_id_auth}}
    )
    log_link_audit_event(
        event_type="cabinet_code_redeemed",
        actor_user_id_auth=g.user_id_auth,
        doctor_user_id_auth=doctor_user_id_auth,
        patient_user_id_auth=g.user_id_auth,
        mode="cabinet_code",
        details={"invite_created_at": str(invite.get("created_at"))},
    )

    return jsonify({
        "message": "Cabinet code redeemed",
        "doctor_user_id_auth": doctor_user_id_auth,
        "patient_user_id_auth": g.user_id_auth
    }), 201


@app.route("/api/admin/associations/doctor-patient", methods=["POST"])
@requires_auth
@requires_role("admin")
def create_doctor_patient_association():
    """Create doctor-patient relationship (admin only)."""
    payload = request.get_json(silent=True) or {}
    try:
        doctor_user_id_auth = normalize_user_id_auth(payload.get("doctor_user_id_auth"), "doctor_user_id_auth")
        patient_user_id_auth = normalize_user_id_auth(payload.get("patient_user_id_auth"), "patient_user_id_auth")
    except ValueError as e:
        return jsonify({
            "code": "invalid_payload",
            "message": str(e)
        }), 400

    doctor_role = get_user_role(doctor_user_id_auth)
    patient_role = get_user_role(patient_user_id_auth)
    if doctor_role != "doctor":
        return jsonify({
            "code": "invalid_doctor",
            "message": "doctor_user_id_auth must reference a user with role 'doctor'"
        }), 400
    if patient_role != "patient":
        return jsonify({
            "code": "invalid_patient",
            "message": "patient_user_id_auth must reference a user with role 'patient'"
        }), 400

    try:
        created = create_doctor_patient_link(
            doctor_user_id_auth=doctor_user_id_auth,
            patient_user_id_auth=patient_user_id_auth,
            linked_by="admin",
            linked_by_user_id_auth=g.user_id_auth
        )
    except PyMongoError as e:
        raise DatabaseError({
            "code": "doctor_association_insert_error",
            "message": f"Failed to store doctor-patient association: {str(e)}"
        }, 500)
    if not created:
        return jsonify({
            "code": "association_exists",
            "message": "Doctor-patient association already exists"
        }), 409

    log_link_audit_event(
        event_type="admin_association_created",
        actor_user_id_auth=g.user_id_auth,
        doctor_user_id_auth=doctor_user_id_auth,
        patient_user_id_auth=patient_user_id_auth,
        mode="admin",
        details={},
    )

    return jsonify({
        "message": "Doctor-patient association saved",
        "doctor_user_id_auth": doctor_user_id_auth,
        "patient_user_id_auth": patient_user_id_auth
    }), 201


@app.route("/api/admin/associations/caregiver-patient", methods=["POST"])
@requires_auth
@requires_role("admin")
def create_caregiver_patient_association():
    """Create caregiver-patient relationship (admin only)."""
    payload = request.get_json(silent=True) or {}
    caregiver_user_id_auth = str(payload.get("caregiver_user_id_auth") or "").strip()
    patient_user_id_auth = str(payload.get("patient_user_id_auth") or "").strip()

    if not caregiver_user_id_auth or not patient_user_id_auth:
        return jsonify({
            "code": "invalid_payload",
            "message": "caregiver_user_id_auth and patient_user_id_auth are required"
        }), 400

    caregiver_role = get_user_role(caregiver_user_id_auth)
    patient_role = get_user_role(patient_user_id_auth)
    if caregiver_role != "caregiver":
        return jsonify({
            "code": "invalid_caregiver",
            "message": "caregiver_user_id_auth must reference a user with role 'caregiver'"
        }), 400
    if patient_role != "patient":
        return jsonify({
            "code": "invalid_patient",
            "message": "patient_user_id_auth must reference a user with role 'patient'"
        }), 400

    try:
        get_identity_db().caregiver_patients.update_one(
            {
                "caregiver_user_id_auth": caregiver_user_id_auth,
                "patient_user_id_auth": patient_user_id_auth
            },
            {
                "$set": {
                    "caregiver_user_id_auth": caregiver_user_id_auth,
                    "patient_user_id_auth": patient_user_id_auth,
                },
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
            },
            upsert=True
        )
    except PyMongoError as e:
        raise DatabaseError({
            "code": "caregiver_association_insert_error",
            "message": f"Failed to store caregiver-patient association: {str(e)}"
        }, 500)

    return jsonify({
        "message": "Caregiver-patient association saved",
        "caregiver_user_id_auth": caregiver_user_id_auth,
        "patient_user_id_auth": patient_user_id_auth
    }), 201


@app.route("/api/doctor/patients", methods=["GET"])
@requires_auth
@requires_role("doctor")
def get_doctor_patients():
    """List patients assigned to authenticated doctor with latest measurement and alert indicator."""
    doctor_user_id_auth = g.user_id_auth
    patient_ids = get_assigned_patient_ids_for_doctor(doctor_user_id_auth)
    patients = build_assigned_patients_payload(patient_ids)

    return jsonify({
        "doctor_id": doctor_user_id_auth,
        "count": len(patients),
        "patients": patients
    }), 200


@app.route("/api/caregiver/patients", methods=["GET"])
@requires_auth
@requires_role("caregiver")
def get_caregiver_patients():
    """List patients assigned to authenticated caregiver with latest measurement."""
    caregiver_user_id_auth = g.user_id_auth
    patient_ids = get_assigned_patient_ids_for_caregiver(caregiver_user_id_auth)
    patients = build_assigned_patients_payload(patient_ids)

    return jsonify({
        "caregiver_id": caregiver_user_id_auth,
        "count": len(patients),
        "patients": patients
    }), 200


@app.route("/api/caregiver/invitations/accept", methods=["POST"])
@requires_auth
def accept_caregiver_invitation():
    """
    Emergency contact accepts a caregiver invitation token.
    Creates caregiver_patients link and sets user role to 'caregiver' if needed.
    """
    payload = request.get_json(silent=True) or {}
    invite_token = str(payload.get("invite_token") or "").strip()
    if not invite_token:
        return jsonify({"code": "invalid_payload", "message": "invite_token is required"}), 400

    token_hash = hash_secret_token(invite_token)
    invite = get_identity_db().caregiver_invites.find_one({"token_hash": token_hash})
    if not invite:
        return jsonify({"code": "invite_not_found", "message": "Invitation introuvable ou expirée"}), 404
    if invite.get("used_at"):
        return jsonify({"code": "invite_used", "message": "Cette invitation a déjà été utilisée"}), 409
    if invite.get("expires_at") and invite["expires_at"] < datetime.now(timezone.utc):
        return jsonify({"code": "invite_expired", "message": "Cette invitation a expiré"}), 410

    patient_user_id_auth = invite["patient_user_id_auth"]
    caregiver_user_id_auth = g.user_id_auth

    if caregiver_user_id_auth == patient_user_id_auth:
        return jsonify({"code": "self_link", "message": "Vous ne pouvez pas être votre propre aidant"}), 400

    try:
        get_identity_db().caregiver_patients.update_one(
            {"caregiver_user_id_auth": caregiver_user_id_auth, "patient_user_id_auth": patient_user_id_auth},
            {"$setOnInsert": {
                "caregiver_user_id_auth": caregiver_user_id_auth,
                "patient_user_id_auth": patient_user_id_auth,
                "created_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )

        current_role = get_user_role(caregiver_user_id_auth)
        if current_role not in ("caregiver", "aidant", "doctor", "admin"):
            get_identity_db().users.update_one(
                {"user_id_auth": caregiver_user_id_auth},
                {"$set": {"role": "caregiver"}},
            )

        get_identity_db().caregiver_invites.update_one(
            {"_id": invite["_id"]},
            {"$set": {"used_at": datetime.now(timezone.utc), "accepted_by": caregiver_user_id_auth}},
        )
        logger.info("Caregiver invite accepted: %s linked to patient %s", caregiver_user_id_auth, patient_user_id_auth)
    except PyMongoError as e:
        raise DatabaseError({"code": "accept_error", "message": f"Failed to accept caregiver invitation: {str(e)}"}, 500)

    return jsonify({
        "message": "Invitation acceptée — vous êtes maintenant aidant de ce patient",
        "patient_user_id_auth": patient_user_id_auth,
        "role": "caregiver",
    }), 200


@app.route("/api/patients/<patient_id>/measurements", methods=["GET"])
@requires_auth
def get_authorized_patient_measurements(patient_id: str):
    """Return measurements for authorized roles (patient self, assigned doctor/caregiver, admin)."""
    ensure_patient_access_or_403(patient_id)

    device_id = get_device_id(patient_id)
    if not device_id:
        raise DatabaseError({
            "code": "device_not_found",
            "message": "No device record found for patient"
        }, 404)

    limit = request.args.get("limit", default=200, type=int)
    from_raw = request.args.get("from", default=None, type=str)
    to_raw = request.args.get("to", default=None, type=str)
    try:
        from_dt = parse_iso_datetime(from_raw, "from")
        to_dt = parse_iso_datetime(to_raw, "to")
        if from_dt and to_dt and from_dt > to_dt:
            return jsonify({
                "code": "invalid_payload",
                "message": "'from' must be <= 'to'"
            }), 400
    except ValueError as e:
        return jsonify({"code": "invalid_payload", "message": str(e)}), 400

    measurements = query_patient_measurements_range(
        device_id=device_id,
        limit=limit,
        from_dt=from_dt,
        to_dt=to_dt
    )

    return jsonify({
        "patient_id": patient_id,
        "device_id": device_id,
        "count": len(measurements),
        "filters": {"limit": min(max(limit, 1), 1000), "from": from_raw, "to": to_raw},
        "latest_measurement": measurements[0] if measurements else None,
        "measurements": measurements
    }), 200


@app.route("/api/doctor/patients/<patient_id>/measurements", methods=["GET"])
@requires_auth
@requires_role("doctor")
def get_doctor_patient_measurements(patient_id: str):
    """Get assigned patient's measurements for doctor view."""
    ensure_patient_access_or_403(patient_id)
    device_id = get_device_id(patient_id)
    if not device_id:
        raise DatabaseError({
            "code": "device_not_found",
            "message": "No device record found for patient"
        }, 404)

    days = request.args.get("days", default=30, type=int)
    limit = request.args.get("limit", default=500, type=int)
    measurements = query_patient_measurements(device_id=device_id, days=days, limit=limit)

    return jsonify({
        "patient_id": patient_id,
        "device_id": device_id,
        "days": days,
        "count": len(measurements),
        "measurements": measurements
    }), 200


@app.route("/api/doctor/patients/<patient_id>/trends", methods=["GET"])
@requires_auth
@requires_role("doctor")
def get_doctor_patient_trends(patient_id: str):
    """Get 7-day and 30-day trend summaries for an assigned patient."""
    doctor_user_id_auth = g.user_id_auth
    patient_ids = set(get_assigned_patient_ids_for_doctor(doctor_user_id_auth))
    if patient_id not in patient_ids:
        return jsonify({
            "code": "patient_not_assigned",
            "message": "This patient is not assigned to the authenticated doctor"
        }), 403

    device_id = get_device_id(patient_id)
    if not device_id:
        raise DatabaseError({
            "code": "device_not_found",
            "message": "No device record found for patient"
        }, 404)

    measurements = query_patient_measurements(device_id=device_id, days=30, limit=1500)
    trend_7 = build_trend_window(measurements, 7)
    trend_30 = build_trend_window(measurements, 30)

    return jsonify({
        "patient_id": patient_id,
        "device_id": device_id,
        "trends": {
            "7d": trend_7,
            "30d": trend_30
        }
    }), 200


@app.route("/api/doctor/alerts", methods=["GET"])
@requires_auth
@requires_role("doctor")
def get_doctor_alerts():
    """List alerts for patients assigned to the authenticated doctor."""
    doctor_user_id_auth = g.user_id_auth
    status = (request.args.get("status", default="OPEN", type=str) or "OPEN").strip().upper()
    limit = min(max(request.args.get("limit", default=100, type=int), 1), 500)

    patient_ids = get_assigned_patient_ids_for_doctor(doctor_user_id_auth)
    if not patient_ids:
        return jsonify({"doctor_id": doctor_user_id_auth, "count": 0, "alerts": []}), 200

    device_by_patient = {}
    for patient_id in patient_ids:
        device_id = get_device_id(patient_id)
        if device_id:
            device_by_patient[patient_id] = device_id

    device_ids = list(device_by_patient.values())
    if not device_ids:
        return jsonify({"doctor_id": doctor_user_id_auth, "count": 0, "alerts": []}), 200

    patient_by_device = {device_id: patient_id for patient_id, device_id in device_by_patient.items()}
    query: Dict[str, Any] = {"device_id": {"$in": device_ids}}
    if status != "ALL":
        query["status"] = status

    cursor = get_medical_db().alerts.find(query, projection={"_id": 0}).sort("created_at", -1).limit(limit)

    alerts = []
    for alert in cursor:
        created_at = alert.get("created_at")
        updated_at = alert.get("updated_at")
        resolved_at = alert.get("resolved_at")
        first_breach_at = alert.get("first_breach_at")
        last_breach_at = alert.get("last_breach_at")
        device_id = alert.get("device_id")
        alerts.append({
            **alert,
            "patient_id": patient_by_device.get(device_id),
            "created_at": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
            "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else updated_at,
            "resolved_at": resolved_at.isoformat() if isinstance(resolved_at, datetime) else resolved_at,
            "first_breach_at": first_breach_at.isoformat() if isinstance(first_breach_at, datetime) else first_breach_at,
            "last_breach_at": last_breach_at.isoformat() if isinstance(last_breach_at, datetime) else last_breach_at,
        })

    return jsonify({
        "doctor_id": doctor_user_id_auth,
        "status_filter": status,
        "count": len(alerts),
        "alerts": alerts
    }), 200


@app.route("/api/doctor/patients/<patient_id>/alert-thresholds", methods=["GET", "PUT"])
@requires_auth
@requires_role("doctor")
def doctor_patient_alert_thresholds(patient_id: str):
    """Read or upsert patient-scoped alert thresholds for assigned patient."""
    doctor_user_id_auth = g.user_id_auth
    patient_ids = set(get_assigned_patient_ids_for_doctor(doctor_user_id_auth))
    if patient_id not in patient_ids:
        return jsonify({
            "code": "patient_not_assigned",
            "message": "This patient is not assigned to the authenticated doctor"
        }), 403

    device_id = get_device_id(patient_id)
    if not device_id:
        raise DatabaseError({
            "code": "device_not_found",
            "message": "No device record found for patient"
        }, 404)

    collection = get_medical_db().alert_thresholds

    if request.method == "GET":
        patient_rule = collection.find_one(
            {"scope": "patient", "device_id": device_id},
            projection={"_id": 0}
        ) or {}
        effective = get_alert_threshold_config(device_id=device_id, pathology=patient_rule.get("pathology"))
        return jsonify({
            "patient_id": patient_id,
            "device_id": device_id,
            "patient_rule": patient_rule,
            "effective_rule": effective,
        }), 200

    payload = request.get_json(silent=True) or {}
    thresholds = merge_thresholds(payload.get("thresholds"))
    consecutive = payload.get("consecutive_breaches", ALERT_DEFAULT_CONSECUTIVE_BREACHES)
    try:
        consecutive = max(1, int(consecutive))
    except (TypeError, ValueError):
        return jsonify({
            "code": "invalid_payload",
            "message": "consecutive_breaches must be an integer >= 1"
        }), 400

    pathology = payload.get("pathology")
    enabled = bool(payload.get("enabled", True))
    now = datetime.now(timezone.utc)

    collection.update_one(
        {"scope": "patient", "device_id": device_id},
        {
            "$set": {
                "scope": "patient",
                "patient_user_id_auth": patient_id,
                "device_id": device_id,
                "pathology": pathology,
                "thresholds": thresholds,
                "consecutive_breaches": consecutive,
                "enabled": enabled,
                "updated_by": doctor_user_id_auth,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True
    )

    updated_rule = collection.find_one(
        {"scope": "patient", "device_id": device_id},
        projection={"_id": 0}
    ) or {}
    return jsonify({
        "message": "Patient alert thresholds saved",
        "patient_id": patient_id,
        "device_id": device_id,
        "rule": updated_rule
    }), 200


@app.route("/api/doctor/patients/<patient_id>/feedback", methods=["POST"])
@requires_auth
@requires_role("doctor")
def create_doctor_feedback(patient_id: str):
    """Create doctor feedback for one assigned patient."""
    ensure_patient_access_or_403(patient_id)
    payload = request.get_json(silent=True) or {}

    message = str(payload.get("message") or "").strip()
    if not message:
        return jsonify({
            "code": "invalid_payload",
            "message": "message is required"
        }), 400
    if len(message) > 2000:
        return jsonify({
            "code": "invalid_payload",
            "message": "message exceeds 2000 characters"
        }), 400

    severity = payload.get("severity")
    if severity is not None:
        severity = str(severity).strip().lower()
        if severity not in ("low", "medium", "high"):
            return jsonify({
                "code": "invalid_payload",
                "message": "severity must be one of: low, medium, high"
            }), 400

    status = payload.get("status")
    if status is not None:
        status = str(status).strip().lower()
        if status not in ("new", "follow_up", "resolved"):
            return jsonify({
                "code": "invalid_payload",
                "message": "status must be one of: new, follow_up, resolved"
            }), 400

    recommendation = payload.get("recommendation")
    if recommendation is not None:
        recommendation = str(recommendation).strip()
        if len(recommendation) > 2000:
            return jsonify({
                "code": "invalid_payload",
                "message": "recommendation exceeds 2000 characters"
            }), 400

    now = datetime.now(timezone.utc)
    feedback_doc = {
        "patient_user_id_auth": patient_id,
        "doctor_user_id_auth": g.user_id_auth,
        "message": message,
        "severity": severity,
        "status": status or "new",
        "recommendation": recommendation,
        "created_at": now,
    }

    try:
        get_medical_db().doctor_feedback.insert_one(feedback_doc)
    except PyMongoError as e:
        raise DatabaseError({
            "code": "doctor_feedback_insert_error",
            "message": f"Failed to store doctor feedback: {str(e)}"
        }, 500)

    return jsonify({
        "message": "Doctor feedback created",
        "feedback": {
            **{k: v for k, v in feedback_doc.items() if k != "_id"},
            "created_at": now.isoformat(),
        }
    }), 201


@app.route("/api/patients/<patient_id>/feedback/latest", methods=["GET"])
@requires_auth
def get_latest_feedback_for_patient(patient_id: str):
    """Read latest doctor feedback for authorized viewer."""
    ensure_patient_access_or_403(patient_id)
    limit = request.args.get("limit", default=5, type=int)
    feedbacks = list_latest_doctor_feedback(patient_user_id_auth=patient_id, limit=limit)

    return jsonify({
        "patient_id": patient_id,
        "count": len(feedbacks),
        "feedback": feedbacks
    }), 200


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint for monitoring."""
    return jsonify({
        "status": "healthy",
        "service": "healthcare-api"
    }), 200


# ============================================================================
# ML ENDPOINTS  (features #2-#7, #10)
# ============================================================================

@app.route("/api/ml/info", methods=["GET"])
def ml_model_info():
    """Public endpoint returning current ML model metadata."""
    return jsonify(ml_module.get_model_info()), 200


@app.route("/api/doctor/ml-anomalies", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser")
def list_ml_anomalies():
    """
    List ML anomalies for the doctor's assigned patients only.
    Query params: status (pending|validated|rejected), limit, device_id,
                  severity (critical), from_date, to_date
    """
    doctor_user_id_auth = g.user_id_auth
    role = get_current_user_role()

    patient_ids = None
    if role != "superuser":
        patient_ids = get_assigned_patient_ids_for_doctor(doctor_user_id_auth)
        if not patient_ids:
            return jsonify({"anomalies": [], "count": 0}), 200

    status_filter = request.args.get("status")
    device_id = request.args.get("device_id")
    severity = request.args.get("severity")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    limit = min(int(request.args.get("limit", "50")), 200)

    query: Dict[str, Any] = {}
    if patient_ids is not None:
        query["user_id_auth"] = {"$in": patient_ids}
    if status_filter in ("pending", "validated", "rejected"):
        query["status"] = status_filter
    if severity in ("critical", "warning"):
        query["anomaly_level"] = severity
    if device_id:
        query["device_id"] = device_id
    if from_date or to_date:
        date_q: Dict[str, Any] = {}
        if from_date:
            try:
                date_q["$gte"] = datetime.fromisoformat(from_date)
            except ValueError:
                pass
        if to_date:
            try:
                date_q["$lte"] = datetime.fromisoformat(to_date)
            except ValueError:
                pass
        if date_q:
            query["created_at"] = date_q

    try:
        cursor = get_medical_db().ml_anomalies.find(query).sort("created_at", -1).limit(limit)
        anomalies = []
        for doc in cursor:
            doc["anomaly_id"] = str(doc.pop("_id"))
            if doc.get("measurement_id"):
                doc["measurement_id"] = str(doc["measurement_id"])
            for dt_field in ("measured_at", "created_at", "validated_at"):
                if isinstance(doc.get(dt_field), datetime):
                    doc[dt_field] = doc[dt_field].isoformat()
            anomalies.append(doc)
        return jsonify({"anomalies": anomalies, "count": len(anomalies)}), 200
    except PyMongoError as e:
        raise DatabaseError({"code": "ml_anomalies_query_error", "message": str(e)}, 500)


@app.route("/api/doctor/ml-anomalies/<anomaly_id>", methods=["PATCH"])
@requires_auth
@requires_role("doctor", "superuser")
def validate_ml_anomaly(anomaly_id: str):
    """
    Validate or reject an ML anomaly. Propagates status to the source measurement.
    Body: { "status": "validated" | "rejected" }
    """
    payload = request.get_json(silent=True) or {}
    new_status = payload.get("status")
    if new_status not in ("validated", "rejected"):
        return jsonify({"code": "invalid_payload", "message": "status must be 'validated' or 'rejected'"}), 400

    try:
        oid = ObjectId(anomaly_id)
    except Exception:
        return jsonify({"code": "invalid_id", "message": "anomaly_id is not a valid ObjectId"}), 400

    anomaly_doc = get_medical_db().ml_anomalies.find_one({"_id": oid})
    if not anomaly_doc:
        return jsonify({"code": "not_found", "message": "Anomaly not found"}), 404

    role = get_current_user_role()
    if role != "superuser":
        anomaly_patient = anomaly_doc.get("user_id_auth")
        if anomaly_patient:
            patient_ids = get_assigned_patient_ids_for_doctor(g.user_id_auth)
            if anomaly_patient not in patient_ids:
                return jsonify({"code": "forbidden", "message": "This anomaly belongs to a patient not assigned to you"}), 403

    now = datetime.now(timezone.utc)
    get_medical_db().ml_anomalies.update_one(
        {"_id": oid},
        {"$set": {
            "status": new_status,
            "validated_by": g.user_id_auth,
            "validated_at": now,
        }}
    )

    measurement_id = anomaly_doc.get("measurement_id")
    if measurement_id:
        try:
            get_medical_db().measurements.update_one(
                {"_id": measurement_id},
                {"$set": {
                    "ml_anomaly_status": new_status,
                    "ml_validated_by": g.user_id_auth,
                    "ml_validated_at": now,
                }}
            )
        except PyMongoError:
            logger.warning("Failed to propagate validation to measurement %s", measurement_id)

    return jsonify({
        "message": f"Anomaly {new_status}",
        "anomaly_id": anomaly_id,
        "status": new_status,
        "validated_by": g.user_id_auth,
        "validated_at": now.isoformat(),
    }), 200


@app.route("/api/admin/ml/retrain", methods=["POST"])
@requires_auth
@requires_role("doctor", "superuser")
def retrain_ml_model():
    """
    Retrain the Isolation Forest model (feature #5).
    Body (optional): { "days": 30, "contamination": 0.05, "n_estimators": 150 }
    """
    payload = request.get_json(silent=True) or {}
    days = int(payload.get("days", 30))
    contamination = float(payload.get("contamination", 0.05))
    n_estimators = int(payload.get("n_estimators", 150))

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    try:
        measurements = list(
            get_medical_db().measurements.find(
                {"status": "VALID", "measured_at": {"$gte": cutoff}},
                projection={"_id": 0, "heart_rate": 1, "spo2": 1, "temperature": 1, "signal_quality": 1, "status": 1}
            ).limit(50000)
        )
    except PyMongoError as e:
        raise DatabaseError({"code": "training_data_error", "message": str(e)}, 500)

    validated_anomalies: List[Dict[str, Any]] = []
    try:
        validated_anomalies = list(
            get_medical_db().ml_anomalies.find(
                {"status": {"$in": ["validated", "rejected"]}},
                projection={"_id": 0}
            ).limit(10000)
        )
    except PyMongoError:
        logger.warning("Could not load validated anomalies for retraining")

    try:
        meta = ml_module.train_model(
            measurements=measurements,
            validated_anomalies=validated_anomalies,
            contamination=contamination,
            n_estimators=n_estimators,
        )
    except ValueError as e:
        return jsonify({"code": "training_error", "message": str(e)}), 400

    try:
        get_medical_db().ml_model_versions.insert_one({
            "version": meta["version"],
            "trained_at": meta["trained_at"],
            "n_samples": meta["n_samples"],
            "contamination": meta["contamination"],
            "n_estimators": meta["n_estimators"],
            "created_at": datetime.now(timezone.utc),
        })
    except PyMongoError:
        logger.warning("Failed to persist model version metadata")

    return jsonify({"message": "Model retrained successfully", **meta}), 200


@app.route("/api/admin/ml/batch-score", methods=["POST"])
@requires_auth
@requires_role("doctor", "superuser")
def batch_score_measurements():
    """
    Retroactively score all measurements that have no ml_score.
    Populates ml_decisions and ml_anomalies for historical data.
    Body (optional): { "limit": 5000, "days": 30 }
    """
    payload = request.get_json(silent=True) or {}
    limit = int(payload.get("limit", 5000))
    days = int(payload.get("days", 30))

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    try:
        cursor = get_medical_db().measurements.find(
            {
                "measured_at": {"$gte": cutoff},
                "$or": [
                    {"ml_score": None},
                    {"ml_score": {"$exists": False}},
                ],
            }
        ).sort("measured_at", -1).limit(limit)

        scored = 0
        skipped = 0
        errors = 0
        for doc in cursor:
            try:
                ml_result = run_ml_scoring(
                    device_id=doc.get("device_id", "unknown"),
                    measurement_doc=doc,
                )
                if ml_result.get("ml_skipped"):
                    skipped += 1
                else:
                    scored += 1
            except Exception:
                errors += 1

        return jsonify({
            "message": "Batch scoring complete",
            "scored": scored,
            "skipped": skipped,
            "errors": errors,
        }), 200
    except PyMongoError as e:
        raise DatabaseError({"code": "batch_score_error", "message": str(e)}, 500)


@app.route("/api/admin/ml/bootstrap", methods=["POST"])
@requires_auth
@requires_role("doctor", "superuser")
def ml_bootstrap():
    """
    Idempotent bootstrap: train model on historical data, then batch-score
    all unscored measurements. Returns a summary.
    Body (optional): { "train_days": 365, "score_days": 365, "score_limit": 10000 }
    """
    payload = request.get_json(silent=True) or {}
    train_days = int(payload.get("train_days", 365))
    score_days = int(payload.get("score_days", 365))
    score_limit = int(payload.get("score_limit", 10000))
    contamination = float(payload.get("contamination", 0.05))
    n_estimators = int(payload.get("n_estimators", 150))

    train_cutoff = datetime.now(timezone.utc) - timedelta(days=max(train_days, 1))
    try:
        train_measurements = list(
            get_medical_db().measurements.find(
                {"status": "VALID", "measured_at": {"$gte": train_cutoff}},
                projection={"_id": 0, "heart_rate": 1, "spo2": 1, "temperature": 1, "signal_quality": 1, "status": 1}
            ).limit(50000)
        )
    except PyMongoError as e:
        raise DatabaseError({"code": "bootstrap_training_data_error", "message": str(e)}, 500)

    n_train = len(train_measurements)

    validated_anomalies: List[Dict[str, Any]] = []
    try:
        validated_anomalies = list(
            get_medical_db().ml_anomalies.find(
                {"status": {"$in": ["validated", "rejected"]}},
                projection={"_id": 0}
            ).limit(10000)
        )
    except PyMongoError:
        pass

    try:
        meta = ml_module.train_model(
            measurements=train_measurements,
            validated_anomalies=validated_anomalies,
            contamination=contamination,
            n_estimators=n_estimators,
        )
    except ValueError as e:
        return jsonify({"code": "bootstrap_training_error", "message": str(e)}), 400

    try:
        get_medical_db().ml_model_versions.insert_one({
            "version": meta["version"],
            "trained_at": meta["trained_at"],
            "n_samples": meta["n_samples"],
            "contamination": meta["contamination"],
            "n_estimators": meta["n_estimators"],
            "created_at": datetime.now(timezone.utc),
        })
    except PyMongoError:
        pass

    score_cutoff = datetime.now(timezone.utc) - timedelta(days=max(score_days, 1))
    scored = 0
    skipped = 0
    errors = 0
    n_critical = 0
    n_warning = 0
    try:
        cursor = get_medical_db().measurements.find(
            {
                "measured_at": {"$gte": score_cutoff},
                "$or": [
                    {"ml_score": None},
                    {"ml_score": {"$exists": False}},
                ],
            }
        ).sort("measured_at", -1).limit(score_limit)

        for doc in cursor:
            try:
                ml_result = run_ml_scoring(
                    device_id=doc.get("device_id", "unknown"),
                    measurement_doc=doc,
                )
                if ml_result.get("ml_skipped"):
                    skipped += 1
                else:
                    scored += 1
                    level = ml_result.get("ml_level")
                    if level == "critical":
                        n_critical += 1
                    elif level == "warning":
                        n_warning += 1
            except Exception:
                errors += 1
    except PyMongoError as e:
        raise DatabaseError({"code": "bootstrap_score_error", "message": str(e)}, 500)

    n_pending = 0
    try:
        n_pending = get_medical_db().ml_anomalies.count_documents({"status": "pending"})
    except PyMongoError:
        pass

    return jsonify({
        "message": "Bootstrap complete",
        "model": meta,
        "n_train": n_train,
        "n_scored": scored,
        "n_skipped": skipped,
        "n_errors": errors,
        "n_warning": n_warning,
        "n_critical": n_critical,
        "n_pending": n_pending,
    }), 200


@app.route("/api/admin/ml/test", methods=["POST"])
@requires_auth
@requires_role("doctor", "superuser")
def run_ml_test():
    """
    Inject simulated measurements and return ML scores (feature #7).
    Body (optional): { "measurements": [...] }
    If no measurements provided, runs the built-in test suites.
    """
    import ml_test

    payload = request.get_json(silent=True) or {}
    custom = payload.get("measurements")

    if custom and isinstance(custom, list):
        results = ml_test.run_custom_test(custom)
    else:
        results = ml_test.run_all_tests()

    return jsonify(results), 200


@app.route("/api/admin/ml/thresholds", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser")
def get_ml_thresholds():
    """Return current ML anomaly score thresholds."""
    return jsonify(ml_module.get_model_info()), 200


@app.route("/api/admin/ml/thresholds", methods=["PUT"])
@requires_auth
@requires_role("doctor", "superuser")
def update_ml_thresholds():
    """
    Update ML score → level thresholds.
    Body: { "normal_max": 0.3, "warning_max": 0.7 }
    """
    payload = request.get_json(silent=True) or {}
    normal_max = payload.get("normal_max")
    warning_max = payload.get("warning_max")
    if normal_max is None and warning_max is None:
        return jsonify({"code": "invalid_payload", "message": "Provide normal_max and/or warning_max"}), 400
    ml_module.configure_thresholds(normal_max=normal_max, warning_max=warning_max)
    return jsonify({"message": "Thresholds updated", **ml_module.get_model_info()}), 200


@app.route("/api/ml/decisions", methods=["GET"])
@requires_auth
@requires_role("doctor", "superuser")
def list_ml_decisions():
    """
    Audit trail: list recent ML decisions (feature #10).
    Query params: device_id, limit
    """
    device_id = request.args.get("device_id")
    limit = min(int(request.args.get("limit", "50")), 500)

    query: Dict[str, Any] = {}
    if device_id:
        query["device_id"] = device_id

    try:
        cursor = get_medical_db().ml_decisions.find(
            query, projection={"_id": 0, "measurement_id": 0}
        ).sort("processed_at", -1).limit(limit)
        decisions = []
        for doc in cursor:
            for dt_field in ("measured_at", "processed_at"):
                if isinstance(doc.get(dt_field), datetime):
                    doc[dt_field] = doc[dt_field].isoformat()
            decisions.append(doc)
        return jsonify({"decisions": decisions, "count": len(decisions)}), 200
    except PyMongoError as e:
        raise DatabaseError({"code": "ml_decisions_query_error", "message": str(e)}, 500)


# ============================================================================
# ML FORECAST
# ============================================================================

@app.route("/api/doctor/ml/forecast/<patient_id>", methods=["GET", "OPTIONS"])
@requires_auth
@requires_role("doctor", "superuser")
def get_ml_forecast(patient_id: str):
    """
    Generate short-term forecast of vital signs for a specific patient
    assigned to the authenticated doctor. Uses weighted linear regression
    on the patient's historical measurements.

    Query params:
      - train_days (int, default 30): lookback window used to fit trend model
      - history_hours (int, default 48): recent window returned for state chart
      - horizon (int, default 6): how many future points to predict
    """
    ensure_patient_access_or_403(patient_id)

    device_ids = get_device_ids(patient_id)
    if not device_ids:
        raise DatabaseError({
            "code": "device_not_found",
            "message": "No device record found for patient"
        }, 404)

    train_days = request.args.get("train_days", type=int)
    if train_days is None:
        train_days = request.args.get("days", default=30, type=int)
    history_hours = request.args.get("history_hours", default=48, type=int)
    horizon = request.args.get("horizon", default=6, type=int)
    horizon = max(1, min(horizon, 24))
    train_days = max(7, min(train_days, 365))
    history_hours = max(12, min(history_hours, 7 * 24))

    measurements = query_patient_measurements_for_devices(
        device_ids=device_ids,
        days=train_days,
        limit=5000,
    )
    if len(measurements) < 3:
        return jsonify({
            "code": "insufficient_data",
            "message": f"Not enough measurements ({len(measurements)} < 3)",
            "patient_id": patient_id,
        }), 400

    try:
        result = ml_module.forecast_vitals(
            measurements,
            horizon=horizon,
            history_window_hours=history_hours,
        )
    except ValueError as e:
        return jsonify({"code": "forecast_error", "message": str(e)}), 400

    result["patient_id"] = patient_id
    result["device_ids"] = device_ids
    result["train_days"] = train_days
    result["history_hours"] = history_hours

    patient_display = None
    try:
        user_doc = get_identity_db().users.find_one(
            {"user_id_auth": patient_id},
            {"display_name": 1, "email": 1},
        )
        if user_doc:
            patient_display = user_doc.get("display_name") or user_doc.get("email")
    except Exception:
        pass
    if patient_display:
        result["patient_display"] = patient_display

    return jsonify(result), 200


@app.route("/api/doctor/ml/patient-analysis/<patient_id>", methods=["GET", "OPTIONS"])
@requires_auth
@requires_role("doctor", "superuser")
def get_patient_ml_analysis(patient_id: str):
    """
    Comprehensive ML analysis for a specific patient: trend charts with moving
    averages, anomaly detection timeline, statistical summaries, correlations,
    daily patterns, and forecast.

    Query params:
      - days (int, default 30): lookback window
      - include_forecast (bool, default true): also run forecast
      - forecast_horizon (int, default 6): prediction points
    """
    ensure_patient_access_or_403(patient_id)

    device_ids = get_device_ids(patient_id)
    if not device_ids:
        raise DatabaseError({
            "code": "device_not_found",
            "message": "No device record found for patient"
        }, 404)

    days = request.args.get("days", default=30, type=int)
    days = max(7, min(days, 365))
    include_forecast = request.args.get("include_forecast", "true").lower() != "false"
    forecast_horizon = request.args.get("forecast_horizon", default=6, type=int)
    forecast_horizon = max(1, min(forecast_horizon, 24))

    measurements = query_patient_measurements_for_devices(
        device_ids=device_ids,
        days=days,
        limit=10000,
    )

    if len(measurements) < 3:
        return jsonify({
            "code": "insufficient_data",
            "message": f"Not enough measurements ({len(measurements)} < 3)",
            "patient_id": patient_id,
        }), 400

    ml_decisions_list = []
    anomaly_records = []
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        ml_decisions_list = list(
            get_medical_db().ml_decisions.find(
                {"device_id": {"$in": device_ids}, "measured_at": {"$gte": cutoff}},
                projection={"_id": 0}
            ).sort("measured_at", -1).limit(5000)
        )
        anomaly_records = list(
            get_medical_db().ml_anomalies.find(
                {"device_id": {"$in": device_ids}, "created_at": {"$gte": cutoff}},
                projection={"_id": 0}
            ).sort("created_at", -1).limit(200)
        )
    except Exception:
        logger.warning("Could not fetch ML decisions/anomalies for patient analysis")

    for doc in ml_decisions_list:
        for key, val in doc.items():
            if isinstance(val, datetime):
                doc[key] = val.isoformat()
    for doc in anomaly_records:
        for key, val in doc.items():
            if isinstance(val, datetime):
                doc[key] = val.isoformat()

    result = ml_module.analyze_patient_vitals(
        measurements,
        ml_scores=ml_decisions_list,
        anomaly_records=anomaly_records,
    )

    if include_forecast and len(measurements) >= 3:
        try:
            forecast = ml_module.forecast_vitals(
                measurements,
                horizon=forecast_horizon,
                history_window_hours=48,
            )
            result["forecast"] = forecast
        except Exception as e:
            result["forecast"] = {"error": str(e)}

    result["patient_id"] = patient_id
    result["device_ids"] = device_ids
    result["days"] = days

    patient_display = None
    try:
        user_doc = get_identity_db().users.find_one(
            {"user_id_auth": patient_id},
            {"display_name": 1, "email": 1},
        )
        if user_doc:
            patient_display = user_doc.get("display_name") or user_doc.get("email")
    except Exception:
        pass
    if patient_display:
        result["patient_display"] = patient_display

    return jsonify(result), 200


# ============================================================================
# MQTT SUBSCRIBER
# ============================================================================

def validate_measurement_payload(payload: dict) -> dict:
    """
    Validate IoT sensor payload and return validation status.
    
    Args:
        payload: Dictionary containing sensor data
        
    Returns:
        dict: Validation result with status and reasons
    """
    sensors = payload.get("sensors", {})
    max30102 = sensors.get("MAX30102", {})
    mlx90614 = sensors.get("MLX90614", {})
    
    hr = max30102.get("heart_rate")
    spo2 = max30102.get("spo2")
    temp = mlx90614.get("object_temp")
    signal_quality = payload.get("signal_quality")

    reasons = validate_measurement_values(
        heart_rate=hr,
        spo2=spo2,
        temperature=temp,
        signal_quality=signal_quality,
        require_signal_quality=True
    )
    
    status = "VALID" if not reasons else "INVALID"
    
    return {
        "status": status,
        "reasons": reasons,
        "validated_at": datetime.now(timezone.utc).isoformat()
    }


def on_mqtt_message(client, userdata, msg):
    """
    Handle incoming MQTT messages from IoT devices.
    Extracts device ID from topic and inserts measurements into SQL Server.
    """
    try:
        payload = json.loads(msg.payload.decode())
        
        # Extract serial_number from topic (e.g., "SIM-ESP32-001" from "vitalio/dev/SIM-ESP32-001/measurements")
        topic_parts = msg.topic.split('/')
        serial_number = topic_parts[2] if len(topic_parts) > 2 else None
        
        if not serial_number:
            print(f"Warning: Could not extract device serial_number from topic: {msg.topic}")
            return
        
        validation = validate_measurement_payload(payload)
        
        payload_timestamp = payload.get("timestamp")
        try:
            parsed_timestamp = datetime.fromisoformat(payload_timestamp)
        except Exception:
            parsed_timestamp = datetime.now(timezone.utc)

        measurement_doc = {
                "device_id": device_id,
                "measured_at": parsed_timestamp,
                "heart_rate": payload["sensors"]["MAX30102"]["heart_rate"],
                "spo2": payload["sensors"]["MAX30102"]["spo2"],
                "temperature": payload["sensors"]["MLX90614"]["object_temp"],
                "signal_quality": payload["signal_quality"],
                "status": validation["status"],
                "validation_reasons": validation["reasons"],
                "source": "device",
            }

        try:
            get_medical_db().measurements.insert_one(measurement_doc)
            print(f"Measurement inserted for device {device_id} (status: {validation['status']})")
            durable_alerts = evaluate_measurement_alerts(device_id=device_id, measurement=measurement_doc)
            if durable_alerts:
                print(
                    f"Durable alert(s) for {device_id}: "
                    + ", ".join([f"{a['metric']} {a['operator']} {a['threshold']}" for a in durable_alerts])
                )
            try:
                ml_res = run_ml_scoring(device_id=device_id, measurement_doc=measurement_doc)
                if ml_res.get("ml_level") in ("warning", "critical"):
                    print(f"ML {ml_res['ml_level']} for {device_id}: score={ml_res['ml_score']}")
            except Exception as ml_err:
                print(f"Warning: ML scoring failed for device {device_id}: {ml_err}")
        except PyMongoError as db_error:
            print(f"Error inserting measurement for device {device_id}: {str(db_error)}")
    
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON payload in MQTT message - {str(e)}")
    except KeyError as e:
        print(f"Error: Missing key in payload - {str(e)}")
    except Exception as e:
        print(f"Error processing MQTT message: {str(e)}")


def on_mqtt_connect(client, userdata, flags, rc, properties=None):
    """Callback for MQTT connection."""
    if rc == 0:
        print(f"MQTT subscriber connected to {MQTT_BROKER}:{MQTT_PORT}")
        print(f"Subscribed to topic: {MQTT_TOPIC}")
        client.subscribe(MQTT_TOPIC, qos=1)
    else:
        print(f"MQTT connection failed with code: {rc}")


def on_mqtt_subscribe(client, userdata, mid, granted_qos, properties=None):
    """Callback for MQTT subscription confirmation."""
    print(f"MQTT subscription confirmed (QoS: {granted_qos[0]})")


def start_mqtt_subscriber():
    """
    Start MQTT subscriber in a background thread.
    This allows the Flask app to run while MQTT messages are processed.
    """
    global _mqtt_client, _mqtt_thread
    
    # Allow disabling MQTT subscriber for local API/frontend development.
    if not MQTT_ENABLED:
        print("MQTT subscriber disabled (MQTT_ENABLED=false)")
        return

    # Check if MQTT is configured
    if not MQTT_BROKER:
        print("MQTT_BROKER not configured, skipping MQTT subscriber")
        return
    
    def mqtt_thread_function():
        """
        Thread function to run MQTT client loop with TLS encryption.
        
        Healthcare Security Requirements:
        - TLS 1.2+ encryption for all MQTT traffic
        - CA certificate validation (broker authentication)
        - Username/password authentication (client authentication)
        - No fallback to insecure connections
        """
        global _mqtt_client
        
        try:
            # Create MQTT client
            _mqtt_client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id="VitalIO_API_Subscriber"
            )
            
            # Set callbacks
            _mqtt_client.on_connect = on_mqtt_connect
            _mqtt_client.on_subscribe = on_mqtt_subscribe
            _mqtt_client.on_message = on_mqtt_message
            
            # ====================================================================
            # TLS CONFIGURATION
            # ====================================================================
            
            # Verify CA certificate path exists
            if not os.path.exists(MQTT_CA_CERT):
                raise FileNotFoundError(
                    f"CA certificate not found: {MQTT_CA_CERT}\n"
                    "Please generate certificates using: mosquitto/generate_certificates.ps1"
                )
            
            # Configure TLS
            # cafile: CA certificate to verify broker identity
            # tls_version: Enforce TLS 1.2 or higher (healthcare requirement)
            _mqtt_client.tls_set(
                ca_certs=MQTT_CA_CERT,
                certfile=None,  # Client certificate not required (using username/password)
                keyfile=None,   # Client key not required (using username/password)
                tls_version=mqtt.ssl.PROTOCOL_TLSv1_2,  # TLS 1.2 minimum
                cert_reqs=mqtt.ssl.CERT_REQUIRED,  # Require broker certificate validation
                ciphers=None  # Use default secure cipher suites
            )
            
            # Username/password authentication (required - anonymous access disabled)
            if not MQTT_USERNAME or not MQTT_PASSWORD:
                raise ValueError(
                    "MQTT_USERNAME and MQTT_PASSWORD must be set in environment variables.\n"
                    "Anonymous connections are disabled for security."
                )
            
            _mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
            
            # ====================================================================
            # CONNECT TO BROKER
            # ====================================================================
            
            print(f"Connecting to MQTT broker via TLS {MQTT_BROKER}:{MQTT_PORT}...")
            print(f"   CA Certificate: {MQTT_CA_CERT}")
            print(f"   Username: {MQTT_USERNAME}")
            print(f"   TLS Version: 1.2+ (enforced)")
            
            _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            _mqtt_client.loop_forever()
            
        except FileNotFoundError as e:
            print(f"Error: {str(e)}")
        except ValueError as e:
            print(f"Error: {str(e)}")
        except ConnectionRefusedError as e:
            print(
                f"MQTT connection refused ({MQTT_BROKER}:{MQTT_PORT}). "
                f"Start broker or set MQTT_ENABLED=false. Details: {str(e)}"
            )
        except Exception as e:
            print(f"Error in MQTT subscriber thread: {str(e)}")
    
    # Start MQTT subscriber in background thread
    _mqtt_thread = threading.Thread(target=mqtt_thread_function, daemon=True)
    _mqtt_thread.start()
    print("MQTT subscriber started in background thread")

if __name__ == "__main__":
    # Ensure MongoDB collections/indexes are ready
    try:
        init_database()
        print(f"MongoDB initialized ({MONGODB_IDENTITY_DB}, {MONGODB_MEDICAL_DB})")
    except DatabaseError as e:
        print(f"Warning: Database initialization failed: {e.error.get('message')}")

    # Load ML model (if previously trained)
    ml_module.init_ml()

    # Start MQTT subscriber in background before starting Flask
    start_mqtt_subscriber()
    
    # Production settings
    app.run(
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("FLASK_PORT", 5000)),
        debug=os.getenv("FLASK_DEBUG", "False").lower() == "true"
    )
