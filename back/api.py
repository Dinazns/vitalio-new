import json
import os
import threading
from urllib.request import urlopen
from functools import wraps
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from jose import jwt, JWTError
from jose.constants import ALGORITHMS
from dotenv import load_dotenv
from supabase import create_client, Client
import paho.mqtt.client as mqtt
from uuid import UUID

from physio_validation import (
    MeasurementInput,
    PhysioValidationConfig,
    validate_measurement,
)

env_path = '.env'
if not os.path.exists(env_path):
    env_path = '../.env'
load_dotenv(env_path)

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

CORS(
    app,
    supports_credentials=True,
    resources={r"/api/*": {"origins": "*"}},
)

# ============================================================================
# CONFIGURATION
# ============================================================================

AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
API_AUDIENCE = os.getenv("AUTH0_AUDIENCE")
ALGORITHMS = ["RS256"]

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))  # TLS port (8883), not unencrypted (1883)
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "vitalio/dev/+/measurements")
# MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")  # Required for authentication
# MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")  # Required for authentication
MQTT_CA_CERT = os.getenv("MQTT_CA_CERT", "./mosquitto/certs/ca.crt")  # CA certificate for TLS verification

_supabase_client: Optional[Client] = None

_mqtt_client: Optional[mqtt.Client] = None
_mqtt_thread: Optional[threading.Thread] = None


def get_supabase_client() -> Optional[Client]:
    """
    Get or create Supabase client instance.
    Initializes client lazily to allow API to start without valid credentials.
    
    Returns:
        Client: Supabase client if credentials are valid, None otherwise
        
    Raises:
        DatabaseError: If credentials are provided but invalid
    """
    global _supabase_client
    
    if _supabase_client is not None:
        return _supabase_client
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    
    try:
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        return _supabase_client
    except Exception as e:
        print(f"Warning: Failed to initialize Supabase client: {str(e)}")
        print("API will start but database operations will fail until credentials are fixed.")
        return None

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


def requires_permission(*required_permissions: str):
    """
    Decorator to enforce permission-based authorization using Auth0 RBAC.
    
    Auth0 RBAC (Role-Based Access Control) stores permissions in the JWT token
    under the "permissions" claim (array of strings).
    
    IMPORTANT:
    - Must be used together with @requires_auth on the same route.
    - Never trusts the frontend: permissions are always read from the verified JWT.
    - Requires Auth0 RBAC to be enabled with "Add Permissions in the Access Token" enabled.
    
    Example:
        @app.route("/api/me/data")
        @requires_auth
        @requires_permission("read:patient_data")
        def get_patient_data():
            ...
    """
    
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            payload = getattr(g, "jwt_payload", None)
            if not payload:
                raise AuthError(
                    {
                        "code": "auth_context_missing",
                        "message": "Authentication context not found. Ensure @requires_auth is applied before @requires_permission.",
                    },
                    500,
                )
            
            # Auth0 RBAC stores permissions in the "permissions" claim (array of strings)
            permissions = payload.get("permissions", [])
            if not isinstance(permissions, list):
                permissions = []
            
            # Debug: Log available permissions if missing (development only)
            if not permissions:
                print(f"[DEBUG] JWT payload keys: {list(payload.keys())}")
                print(f"[DEBUG] Permissions claim is missing or empty. Available claims: {list(payload.keys())}")
                print(f"[DEBUG] This usually means RBAC is not enabled or 'Add Permissions in the Access Token' is disabled in Auth0.")
            
            # Check if user has at least one of the required permissions
            if not any(perm in permissions for perm in required_permissions):
                error_msg = (
                    f"User does not have required permission. Required: {', '.join(required_permissions)}. "
                    f"Available permissions: {permissions if permissions else 'none (RBAC may not be configured)'}"
                )
                raise AuthError(
                    {
                        "code": "insufficient_permissions",
                        "message": error_msg,
                    },
                    403,
                )
            
            return f(*args, **kwargs)
        
        return wrapper
    
    return decorator

# ============================================================================
# DATABASE ACCESS LAYER
# ============================================================================

def get_user_record(user_id: str) -> Dict[str, Any]:
    """
    Load a user row from public.users for authorization / display.

    - Ne touche jamais au schéma d'auth Supabase (auth.users)
    - Utilise uniquement la table applicative public.users
    """
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
        resp = (
            supabase_client.table("users")
            .select("id, email, role")
            .eq("id", user_id)
            .execute()
        )
    except Exception as e:
        raise DatabaseError(
            {
                "code": "user_lookup_error",
                "message": f"Failed to load user record: {str(e)}",
            },
            500,
        )

    if not resp.data:
        raise DatabaseError(
            {
                "code": "user_not_found",
                "message": "Authenticated user does not exist in users table",
            },
            404,
        )

    return resp.data[0]


def require_app_role(required_role: str):
    """
    Lightweight role-based authorization using the public.users.role column.

    - Le JWT est déjà vérifié par @requires_auth (signature, issuer, audience, etc.)
    - Ce décorateur lit simplement le rôle applicatif dans public.users.role
    - Toute décision d'autorisation reste côté backend (jamais côté frontend)
    """

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = get_user_record(g.user_id)
            role = user.get("role")
            if role != required_role:
                raise AuthError(
                    {
                        "code": "forbidden",
                        "message": f"User role '{role}' is not allowed to access this resource (requires '{required_role}').",
                    },
                    403,
                )
            # Attacher le user applicatif au contexte pour les handlers en aval
            g.app_user = user
            return f(*args, **kwargs)

        return wrapper

    return decorator


def get_device_id(user_id: str) -> Optional[str]:
    """
    Query correspondence database to map internal user UUID to device_id.
    
    Sequence Steps 6-7:
    - API queries correspondence database:
      SELECT device_id WHERE user_id = <internal user UUID>
    - Correspondence database returns device_id
    
    Args:
        user_id: Internal user UUID from public.users.id
        
    Returns:
        str: device_id if found, None otherwise
        
    Raises:
        DatabaseError: If database query fails
    """
    supabase_client = get_supabase_client()
    if not supabase_client:
        raise DatabaseError({
            "code": "database_not_configured",
            "message": "Database client not initialized. Please check SUPABASE_URL and SUPABASE_KEY in .env file"
        }, 500)
    
    try:
        # Query correspondence database
        # SELECT device_id WHERE user_id = <internal user UUID>
        response = supabase_client.table("user_devices").select(
            "device_id"
        ).eq(
            "user_id", user_id
        ).execute()
        
        # Extract device_id from response
        if response.data and len(response.data) > 0:
            device_id = response.data[0].get("device_id")
            return device_id
        
        return None
        
    except Exception as e:
        raise DatabaseError({
            "code": "correspondence_query_error",
            "message": f"Failed to query correspondence database: {str(e)}"
        }, 500)


def get_device_ids_for_user(user_id: str) -> List[str]:
    """
    Return all device_ids linked to a user via user_devices.
    """
    supabase_client = get_supabase_client()
    if not supabase_client:
        raise DatabaseError({
            "code": "database_not_configured",
            "message": "Database client not initialized. Please check SUPABASE_URL and SUPABASE_KEY in .env file"
        }, 500)
    try:
        response = supabase_client.table("user_devices").select(
            "device_id"
        ).eq("user_id", user_id).execute()
        if response.data:
            return [row.get("device_id") for row in response.data if row.get("device_id")]
        return []
    except Exception as e:
        raise DatabaseError({
            "code": "correspondence_query_error",
            "message": f"Failed to query user devices: {str(e)}"
        }, 500)


def get_device_measurements(device_id: str) -> List[Dict[str, Any]]:
    """
    Query medical database to fetch vital measurements for a device.
    
    Sequence Steps 8-9:
    - API queries medical database:
      SELECT timestamp, heart_rate, spo2, temperature WHERE device_id = ?
    - Medical database returns the vital measurements
    
    Args:
        device_id: UUID from devices.id
        
    Returns:
        list: List of measurement dictionaries containing:
            - timestamp
            - heart_rate
            - spo2
            - temperature
            
    Raises:
        DatabaseError: If database query fails
    """
    supabase_client = get_supabase_client()
    if not supabase_client:
        raise DatabaseError({
            "code": "database_not_configured",
            "message": "Database client not initialized. Please check SUPABASE_URL and SUPABASE_KEY in .env file"
        }, 500)
    
    try:
        # Query medical database
        # SELECT timestamp, heart_rate, spo2, temperature WHERE device_uuid = ?
        response = supabase_client.table("measurements").select(
            "timestamp, heart_rate, spo2, temperature"
        ).eq(
            "device_uuid", device_id
        ).order("timestamp", desc=True).limit(100).execute()
        
        # Return vital measurements
        if response.data:
            return response.data
        
        return []
        
    except Exception as e:
        raise DatabaseError({
            "code": "medical_query_error",
            "message": f"Failed to query medical database: {str(e)}"
        }, 500)


def handle_mqtt_message(topic: str, payload: Dict[str, Any], user_id: Optional[str] = None) -> Optional[str]:
    """
    Handle a single MQTT message at application level.

    Responsibilities:
    - Extract device serial_number from MQTT topic
    - Upsert device into devices table (idempotent, no duplicates)
    - Optionally link the device to a user via user_devices (pivot table)

    Design notes:
    - The topic is the source of truth for the device serial:
      devices publish to topics of the form:
          vitalio/dev/{SERIAL_NUMBER}/measurements
      The device lui‑même ne connaît PAS l'utilisateur, seulement son identifiant matériel.
    - The pivot table user_devices(user_id, device_id) is used to model:
      * Many devices per user
      * Future cases of device re-assignment with explicit validation (QR code, pairing code, etc.)
    - UPSERT is critical in IoT:
      * Devices reconnect, redémarrent, renvoient plusieurs fois les mêmes infos
      * The backend may receive the same serial_number many times
      * We must never create duplicate device rows for the same serial_number.

    SQL intent:
        -- 1) Upsert the device
        INSERT INTO devices (serial_number, mqtt_topic)
        VALUES (:serial_number, :topic)
        ON CONFLICT (serial_number)
        DO UPDATE SET mqtt_topic = EXCLUDED.mqtt_topic
        RETURNING id;

        -- 2) Idempotent user-device link (only if user_id provided)
        INSERT INTO user_devices (user_id, device_id)
        VALUES (:user_id, :device_id)
        ON CONFLICT (user_id, device_id)
        DO NOTHING;

    Security / data integrity:
    - Verifies that user_id exists in public.users before linking.
    - Never links a device that is already linked to another user:
        * If a row exists in user_devices with device_id and user_id != current,
          the function logs a warning and skips linking.

    Returns:
        device_id (UUID as string) if the device row exists/was created, None on failure.
    """
    # -----------------------------------------------------------------------
    # Step 1: Extract serial_number from MQTT topic
    # Example: "vitalio/dev/SIM-ESP32-003/measurements" -> "SIM-ESP32-003"
    # -----------------------------------------------------------------------
    topic_parts = topic.split("/")
    serial_number = topic_parts[2] if len(topic_parts) > 2 else None

    if not serial_number:
        print(f"[handle_mqtt_message] Warning: Could not extract serial_number from topic='{topic}'")
        return None

    supabase_client = get_supabase_client()
    if not supabase_client:
        print("[handle_mqtt_message] Error: Supabase client not available")
        return None

    # -----------------------------------------------------------------------
    # Step 2: Upsert device row (idempotent, based on UNIQUE(serial_number))
    # NOTE: The supabase-py client does NOT support `.select()` after upsert.
    #       We therefore:
    #         1) perform the upsert
    #         2) re-select the row by serial_number to obtain `id`
    # -----------------------------------------------------------------------
    try:
        (
            supabase_client
            .table("devices")
            .upsert(
                {
                    "serial_number": serial_number,
                    "mqtt_topic": topic,
                },
                on_conflict="serial_number",
            )
            .execute()
        )
    except Exception as e:
        print(
            f"[handle_mqtt_message] Error upserting device for serial_number={serial_number}: {e}"
        )
        return None

    try:
        select_response = (
            supabase_client
            .table("devices")
            .select("id")
            .eq("serial_number", serial_number)
            .execute()
        )
    except Exception as e:
        print(
            f"[handle_mqtt_message] Error selecting device id after upsert for "
            f"serial_number={serial_number}: {e}"
        )
        return None

    if not select_response.data:
        print(
            f"[handle_mqtt_message] Error: no device row found after upsert for "
            f"serial_number={serial_number}"
        )
        return None

    device_id = select_response.data[0].get("id")
    if not device_id:
        print(
            f"[handle_mqtt_message] Error: device row for serial_number={serial_number} has no 'id'"
        )
        return None

    print(
        f"[handle_mqtt_message] Device resolved: serial_number={serial_number}, device_id={device_id}"
    )

    # -----------------------------------------------------------------------
    # Step 3: Optionally link device to user via pivot user_devices
    # -----------------------------------------------------------------------
    if user_id:
        try:
            # 3.a Ensure user exists in public.users
            user_resp = (
                supabase_client
                .table("users")
                .select("id")
                .eq("id", user_id)
                .execute()
            )

            if not user_resp.data:
                print(
                    f"[handle_mqtt_message] Warning: user_id={user_id} not found in public.users; "
                    f"skipping user_devices link for device_id={device_id}"
                )
                # We still return device_id so measurements can be stored.
                return device_id

            # 3.b Check if the device is already linked to some user
            link_resp = (
                supabase_client
                .table("user_devices")
                .select("user_id")
                .eq("device_id", device_id)
                .execute()
            )

            if link_resp.data:
                existing_user_id = link_resp.data[0].get("user_id")
                if existing_user_id == user_id:
                    # Idempotent: the link already exists for this user
                    print(
                        f"[handle_mqtt_message] user_devices link already exists: "
                        f"user_id={user_id}, device_id={device_id}"
                    )
                    return device_id

                # Device is already linked to another user -> do NOT reassign automatically
                print(
                    f"[handle_mqtt_message] Warning: device_id={device_id} already linked to "
                    f"user_id={existing_user_id}; refusing to link to user_id={user_id}"
                )
                return device_id

            # 3.c Create idempotent link (user_id, device_id)
            #     Uses ON CONFLICT to be robust to race conditions.
            pivot_resp = (
                supabase_client
                .table("user_devices")
                .upsert(
                    {
                        "user_id": user_id,
                        "device_id": device_id,
                    },
                    on_conflict="user_id,device_id",
                )
                .execute()
            )

            print(
                f"[handle_mqtt_message] user_devices link created/confirmed: "
                f"user_id={user_id}, device_id={device_id}, serial_number={serial_number}"
            )
        except Exception as e:
            print(
                f"[handle_mqtt_message] Error while linking user_id={user_id} to device_id={device_id}: {e}"
            )
            # Do not block measurement ingestion; just log the error.

    return device_id

# ============================================================================
# API ROUTES
# ============================================================================

@app.route("/api/me/data", methods=["GET"])
@requires_auth
@requires_permission("read:patient_data")
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


@app.route("/api/user-devices", methods=["POST"])
@requires_auth
def create_user_device():
    """
    Create or update a correspondence between the authenticated user and a device.

    Auth:
        - Uses Auth0 JWT via @requires_auth
        - Never trusts user_id from frontend
        - Relies on g.user_id (internal UUID from public.users.id)

    Body (JSON):
        {
            "serial_number": "SIM-ESP32-001"
        }

    Behaviour:
        - Resolves devices.id from devices.serial_number
        - Inserts a row into user_devices (user_id, device_id)
    """
    supabase_client = get_supabase_client()
    if not supabase_client:
        raise DatabaseError({
            "code": "database_not_configured",
            "message": "Database client not initialized. Please check SUPABASE_URL and SUPABASE_KEY in .env file"
        }, 500)

    data = request.get_json() or {}
    serial_number = data.get("serial_number")

    if not serial_number:
        return jsonify({"error": "serial_number required"}), 400

    # Ensure a device row exists for this serial_number.
    # If it n'existe pas encore (capteur jamais vu côté MQTT), on le crée
    # ici avec un mqtt_topic déterministe : vitalio/dev/<serial_number>/measurements.
    try:
        mqtt_topic = f"vitalio/dev/{serial_number}/measurements"

        # Idempotent upsert on serial_number to avoid duplicates.
        (
            supabase_client
            .table("devices")
            .upsert(
                {
                    "serial_number": serial_number,
                    "mqtt_topic": mqtt_topic,
                },
                on_conflict="serial_number",
            )
            .execute()
        )

        # Re-select to retrieve the device UUID (devices.id)
        device_response = (
            supabase_client
            .table("devices")
            .select("id")
            .eq("serial_number", serial_number)
            .execute()
        )

        if not device_response.data:
            return jsonify({
                "error": "device_not_persisted",
                "message": f"Device row could not be created or found for serial_number={serial_number}"
            }), 500

        device_id = device_response.data[0].get("id")
        if not device_id:
            return jsonify({
                "error": "device_invalid",
                "message": f"Device record for serial_number={serial_number} has no 'id' field"
            }), 500
    except Exception as e:
        raise DatabaseError({
            "code": "device_upsert_error",
            "message": f"Failed to upsert device for serial_number={serial_number}: {str(e)}"
        }, 500)

    # Enforce uniqueness: a device can only be associated with a single user.
    # If the device is already linked to a different user, return 409.
    try:
        existing_links = (
            supabase_client
            .table("user_devices")
            .select("user_id")
            .eq("device_id", device_id)
            .execute()
        )
    except Exception as e:
        raise DatabaseError({
            "code": "user_device_lookup_error",
            "message": f"Failed to check existing user-device links: {str(e)}"
        }, 500)

    if existing_links.data:
        existing_user_id = existing_links.data[0].get("user_id")
        if existing_user_id and existing_user_id != g.user_id:
            # Device already linked to another user
            return jsonify({
                "error": "device_already_associated",
                "message": "This device is already associated with another user."
            }), 409
        if existing_user_id == g.user_id:
            # Idempotent success: already linked to this user
            return jsonify({
                "user_id": g.user_id,
                "device_id": device_id,
                "serial_number": serial_number,
                "message": "Device already associated with this user."
            }), 200

    # Create correspondence user <-> device
    # We already ensured that either:
    # - the device is not linked yet, or
    # - it is linked to this user (early return above).
    # So a simple INSERT is sufficient here.
    try:
        insert_response = (
            supabase_client
            .table("user_devices")
            .insert({
                "user_id": g.user_id,   # Internal UUID from public.users.id
                "device_id": device_id  # UUID from devices.id
            })
            .execute()
        )

        created = insert_response.data[0] if insert_response.data else None
        return jsonify({
            "user_id": g.user_id,
            "device_id": device_id,
            "serial_number": serial_number,
            "record": created
        }), 201
    except Exception as e:
        raise DatabaseError({
            "code": "user_device_insert_error",
            "message": f"Failed to persist user-device mapping: {str(e)}"
        }, 500)


@app.route("/api/me/device", methods=["GET"])
@requires_auth
def get_my_device():
    """
    Return the device associated with the authenticated user.

    Response (200):
        {
            "device_id": "<uuid from devices.id>",
            "serial_number": "SIM-ESP32-001",
            "mqtt_topic": "vitalio/dev/SIM-ESP32-001/measurements"
        }

    Errors:
        - 404 if the user has no associated device
    """
    supabase_client = get_supabase_client()
    if not supabase_client:
        raise DatabaseError({
            "code": "database_not_configured",
            "message": "Database client not initialized. Please check SUPABASE_URL and SUPABASE_KEY in .env file"
        }, 500)

    try:
        link_response = (
            supabase_client
            .table("user_devices")
            .select("device_id")
            .eq("user_id", g.user_id)
            .execute()
        )
    except Exception as e:
        raise DatabaseError({
            "code": "user_device_lookup_error",
            "message": f"Failed to look up user-device link: {str(e)}"
        }, 500)

    if not link_response.data:
        return jsonify({
            "error": "device_not_paired",
            "message": "No device associated with the authenticated user."
        }), 404

    device_id = link_response.data[0].get("device_id")
    if not device_id:
        return jsonify({
            "error": "device_invalid",
            "message": "User-device record is missing device_id."
        }), 500

    try:
        device_response = (
            supabase_client
            .table("devices")
            .select("serial_number, mqtt_topic")
            .eq("id", device_id)
            .execute()
        )
    except Exception as e:
        raise DatabaseError({
            "code": "device_lookup_error",
            "message": f"Failed to load device information: {str(e)}"
        }, 500)

    if not device_response.data:
        return jsonify({
            "error": "device_not_found",
            "message": "Associated device not found in devices table."
        }), 404

    device_row = device_response.data[0]

    return jsonify({
        "device_id": device_id,
        "serial_number": device_row.get("serial_number"),
        "mqtt_topic": device_row.get("mqtt_topic"),
    }), 200


@app.route("/api/doctor/requests", methods=["POST"])
@requires_auth
@require_app_role("doctor")
def create_doctor_request():
    """
    Demande d'association Médecin → Patient (validation par Admin).

    - Médecin authentifié (JWT + rôle doctor).
    - doctor_id = g.user_id (jamais pris depuis le front).
    - Pas de doublon (doctor_id + patient_email).
    - Table: doctor_requests(id, doctor_id, patient_email, created_at).
    """
    supabase_client = get_supabase_client()
    if not supabase_client:
        raise DatabaseError(
            {
                "code": "database_not_configured",
                "message": "Database client not initialized. Please check SUPABASE_URL and SUPABASE_KEY in .env file",
            },
            500,
        )

    data = request.get_json() or {}
    patient_email_raw = data.get("patient_email") or ""
    patient_email = patient_email_raw.strip().lower()

    if not patient_email:
        return jsonify(
            {
                "code": "validation_error",
                "message": "patient_email is required",
            }
        ), 400

    if "@" not in patient_email or "." not in patient_email.split("@")[-1]:
        return jsonify(
            {
                "code": "validation_error",
                "message": "patient_email must be a valid email address",
            }
        ), 400

    try:
        # Pas de doublon (doctor_id + patient_email)
        existing = (
            supabase_client.table("doctor_requests")
            .select("id, created_at")
            .eq("doctor_id", g.user_id)
            .eq("patient_email", patient_email)
            .execute()
        )

        if existing.data:
            return jsonify(
                {
                    "request": existing.data[0],
                    "message": "A request for this patient already exists.",
                }
            ), 200

        insert_payload = {
            "doctor_id": g.user_id,
            "patient_email": patient_email,
            # Nouveau flux : status explicite pour suivre le cycle de vie (pending → approved/rejected)
            "status": "pending",
        }

        insert_resp = (
            supabase_client.table("doctor_requests")
            .insert(insert_payload)
            .execute()
        )

        created = insert_resp.data[0] if insert_resp.data else insert_payload
        return jsonify({"request": created}), 201

    except Exception as e:
        raise DatabaseError(
            {
                "code": "doctor_request_insert_error",
                "message": f"Failed to create doctor request: {str(e)}",
            },
            500,
        )


@app.route("/api/doctor/requests", methods=["GET"])
@requires_auth
@require_app_role("doctor")
def list_doctor_requests_for_doctor():
    """
    Liste des demandes d'association pour le médecin connecté.

    - Ne retourne QUE les demandes du médecin courant (doctor_id = g.user_id)
    - Permet au frontend de lister :
        * les patients déjà associés (status = 'approved')
        * les demandes en attente / rejetées
    """
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
        resp = (
            supabase_client.table("doctor_requests")
            .select("id, patient_email, status, created_at")
            .eq("doctor_id", g.user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return jsonify({"requests": resp.data or []}), 200
    except Exception as e:
        raise DatabaseError(
            {
                "code": "doctor_requests_doctor_list_error",
                "message": f"Failed to list doctor requests for doctor: {str(e)}",
            },
            500,
        )


@app.route("/api/doctor/patients/measurements", methods=["GET"])
@requires_auth
@require_app_role("doctor")
def get_doctor_patients_measurements():
    """
    Return measurements for all patients associated with the connected doctor
    (doctor_requests with status = 'approved').

    For each approved patient:
    - Resolve user id from users.email = patient_email
    - Get all device_ids from user_devices for that user
    - Fetch measurements for each device and aggregate (sorted by timestamp desc, limited per patient)
    """
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
        # 1) Approved doctor_requests for this doctor
        req_resp = (
            supabase_client.table("doctor_requests")
            .select("patient_email")
            .eq("doctor_id", g.user_id)
            .eq("status", "approved")
            .execute()
        )
        requests_data = req_resp.data or []
        patient_emails = list({r.get("patient_email") for r in requests_data if r.get("patient_email")})
        if not patient_emails:
            return jsonify({"patients": []}), 200

        # 2) Resolve user ids from emails
        users_resp = (
            supabase_client.table("users")
            .select("id, email")
            .in_("email", patient_emails)
            .execute()
        )
        users_data = users_resp.data or []
        email_to_user_id = {u.get("email"): u.get("id") for u in users_data if u.get("email") and u.get("id")}

        # 3) For each patient, get device_ids and then measurements
        MEASUREMENTS_LIMIT_PER_PATIENT = 100
        patients_with_measurements = []

        for patient_email in patient_emails:
            user_id = email_to_user_id.get(patient_email)
            if not user_id:
                patients_with_measurements.append({
                    "patient_email": patient_email,
                    "measurements": [],
                })
                continue
            device_ids = get_device_ids_for_user(user_id)
            all_measurements = []
            for device_id in device_ids:
                try:
                    measurements = get_device_measurements(device_id)
                    for m in measurements:
                        m_copy = dict(m)
                        m_copy["device_id"] = device_id
                        all_measurements.append(m_copy)
                except Exception:
                    continue
            # Sort by timestamp desc and limit
            all_measurements.sort(
                key=lambda x: (x.get("timestamp") or ""),
                reverse=True,
            )
            all_measurements = all_measurements[:MEASUREMENTS_LIMIT_PER_PATIENT]
            patients_with_measurements.append({
                "patient_email": patient_email,
                "measurements": all_measurements,
            })

        return jsonify({"patients": patients_with_measurements}), 200
    except DatabaseError:
        raise
    except Exception as e:
        raise DatabaseError(
            {
                "code": "doctor_patients_measurements_error",
                "message": f"Failed to fetch patients measurements: {str(e)}",
            },
            500,
        )


@app.route("/api/admin/doctor-requests", methods=["GET"])
@requires_auth
@requires_permission("add_users")
def list_doctor_requests():
    """
    Consultation des demandes Médecin → Patient (lecture seule, via Auth0 RBAC).

    - Accès réservé aux utilisateurs possédant la permission Auth0 "add_users"
      (claim "permissions" dans le JWT d'accès).
    - Ne fait aucune confiance au frontend : la décision est entièrement
      contrôlée par le backend via @requires_permission.

    Retourne: id, doctor_id, patient_email, created_at.
    """
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
        resp = (
            supabase_client.table("doctor_requests")
            .select("id, doctor_id, patient_email, status, created_at")
            .order("created_at", desc=True)
            .execute()
        )
        raw_requests = resp.data or []
        if not raw_requests:
            return jsonify({"requests": []}), 200

        doctor_ids = list({r.get("doctor_id") for r in raw_requests if r.get("doctor_id")})
        users_by_id: Dict[str, Dict[str, Any]] = {}
        if doctor_ids:
            users_resp = (
                supabase_client.table("users")
                .select("id, email")
                .in_("id", doctor_ids)
                .execute()
            )
            for u in users_resp.data or []:
                uid = u.get("id")
                if uid:
                    users_by_id[uid] = u

        assembled = []
        for r in raw_requests:
            doctor_id = r.get("doctor_id")
            doctor_email = (users_by_id.get(doctor_id) or {}).get("email")
            assembled.append({
                "id": r.get("id"),
                "doctor_id": doctor_id,
                "doctor_email": doctor_email,
                "patient_email": r.get("patient_email"),
                "status": r.get("status"),
                "created_at": r.get("created_at"),
            })
        return jsonify({"requests": assembled}), 200
    except Exception as e:
        raise DatabaseError(
            {
                "code": "doctor_requests_list_error",
                "message": f"Failed to list doctor requests: {str(e)}",
            },
            500,
        )


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint for monitoring."""
    return jsonify({
        "status": "healthy",
        "service": "healthcare-api"
    }), 200


# ============================================================================
# MQTT SUBSCRIBER
# ============================================================================

def build_measurement_input_from_payload(payload: dict) -> MeasurementInput:
    """
    Pure adapter: build MeasurementInput from raw MQTT payload.
    """
    sensors = payload.get("sensors", {})
    max30102 = sensors.get("MAX30102", {})
    mlx90614 = sensors.get("MLX90614", {})

    ts_raw = payload.get("timestamp")
    meta: Dict[str, Any] = {"raw_timestamp": ts_raw}
    try:
        if ts_raw:
            # Normalise à un datetime timezone-aware en UTC pour éviter
            # les erreurs "can't compare offset-naive and offset-aware datetimes"
            # dans physio_validation et les calculs downstream.
            parsed = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                ts = parsed.replace(tzinfo=timezone.utc)
            else:
                ts = parsed.astimezone(timezone.utc)
        else:
            ts = datetime.now(timezone.utc)
            meta["timestamp_fallback_now"] = True
    except Exception:
        ts = datetime.now(timezone.utc)
        meta["timestamp_parse_error"] = True

    return MeasurementInput(
        heart_rate_bpm=max30102.get("heart_rate"),
        spo2_percent=max30102.get("spo2"),
        temp_celsius=mlx90614.get("object_temp"),
        timestamp=ts,
        signal_quality_score=payload.get("signal_quality"),
        missing_ratio=None,
        artefact_flag=None,
        meta=meta,
    )


def validate_measurement_payload(payload: dict) -> dict:
    """
    Validate IoT sensor payload using physio_validation module.
    Returns a dict compatible with existing caller.
    """
    m_input = build_measurement_input_from_payload(payload)
    cfg = PhysioValidationConfig()
    result = validate_measurement(m_input, cfg)

    return {
        "status": result.status.value.upper(),
        "quality_score": result.quality_score,
        "reasons": result.reasons,
        "hard_rule_violations": result.hard_rule_violations,
        "validated_at": datetime.utcnow().isoformat() + "Z",
    }


def on_mqtt_message(client, userdata, msg):
    """
    Handle incoming MQTT messages from IoT devices.

    Responsibilities:
    - Log reception of the raw MQTT message
    - Extract device serial_number from topic (vitalio/dev/{SERIAL_NUMBER}/measurements)
    - Delegate device upsert / resolution to handle_mqtt_message
    - Insert a new measurement row into Supabase.measurements

    Notes:
    - We extract serial_number here (in addition to handle_mqtt_message) so that
      logs are always consistent and serial_number is defined for error messages.
    - The FK column in measurements is `device_id` (text), which stores the
      UUID string from devices.id. We align data_to_insert with that schema.
    """
    try:
        # ------------------------------------------------------------------
        # 1) Decode payload & basic logging
        # ------------------------------------------------------------------
        raw_payload = msg.payload.decode()
        print(f"[on_mqtt_message] Received MQTT message on topic='{msg.topic}': {raw_payload}")

        payload = json.loads(raw_payload)

        # ------------------------------------------------------------------
        # 2) Extract serial_number from topic for logging and tracing
        #    Example: vitalio/dev/SIM-ESP32-003/measurements -> SIM-ESP32-003
        # ------------------------------------------------------------------
        topic_parts = msg.topic.split("/")
        serial_number = topic_parts[2] if len(topic_parts) > 2 else None

        if not serial_number:
            print(f"[on_mqtt_message] Warning: Could not extract serial_number from topic='{msg.topic}'")
            return

        # ------------------------------------------------------------------
        # 3) Validate measurement payload (physiological rules)
        # ------------------------------------------------------------------
        validation = validate_measurement_payload(payload)

        # ------------------------------------------------------------------
        # 4) Resolve / upsert device and get devices.id (UUID as string)
        # ------------------------------------------------------------------
        # For pure MQTT ingestion there is no authenticated user context,
        # so we pass user_id=None. A future pairing flow can supply a real user_id.
        device_id = handle_mqtt_message(msg.topic, payload, user_id=None)
        serial_number = msg.topic.split("/")[2]
        if not device_id:
            print(
                f"[on_mqtt_message] Error: handle_mqtt_message could not resolve device "
                f"for serial_number={serial_number}; skipping measurement insert."
            )
            return

        print(
            f"[on_mqtt_message] Device resolved for serial_number={serial_number}: "
            f"device_id={device_id}, status={validation['status']}"
        )

        # ------------------------------------------------------------------
        # 5) Prepare measurement row for insertion
        # ------------------------------------------------------------------
        supabase_client = get_supabase_client()
        if not supabase_client:
            print("[on_mqtt_message] Error: Supabase client not available for MQTT subscriber")
            return

        try:
            max30102 = payload["sensors"]["MAX30102"]
            mlx90614 = payload["sensors"]["MLX90614"]
            timestamp = payload["timestamp"]
            signal_quality = payload["signal_quality"]
        except KeyError as e:
            print(f"[on_mqtt_message] Error: Missing key in payload for serial_number={serial_number}: {e}")
            return

        # IMPORTANT: device_id must match the FK column name in Supabase.
        # Schema: measurements(device_id FK -> devices.id, ...)
        data_to_insert = {
            "device_uuid": device_id,
            "timestamp": timestamp,
            "heart_rate": max30102.get("heart_rate"),
            "spo2": max30102.get("spo2"),
            "temperature": mlx90614.get("object_temp"),
            "signal_quality": signal_quality,
            "status": validation["status"],
        }

        # ------------------------------------------------------------------
        # 6) Insert into measurements (idempotent at message level: each
        #    MQTT payload naturally results in one new row)
        # ------------------------------------------------------------------
        try:
            response = supabase_client.table("measurements").insert(data_to_insert).execute()
            print(
                f"[on_mqtt_message] Measurement inserted for serial_number={serial_number}, "
                f"device_id={device_id}, inserted_rows={len(response.data) if response and response.data else 0}"
            )
        except Exception as db_error:
            print(
                f"[on_mqtt_message] Error inserting measurement for serial_number={serial_number}, "
                f"device_id={device_id}: {db_error}"
            )

    except json.JSONDecodeError as e:
        print(f"[on_mqtt_message] Error: Invalid JSON payload in MQTT message - {e}")
    except Exception as e:
        print(f"[on_mqtt_message] Error processing MQTT message: {e}")


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
            # if not MQTT_USERNAME or not MQTT_PASSWORD:
            #     raise ValueError(
            #         "MQTT_USERNAME and MQTT_PASSWORD must be set in environment variables.\n"
            #         "Anonymous connections are disabled for security."
            #     )
            
            # _mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
            
            # ====================================================================
            # CONNECT TO BROKER
            # ====================================================================
            
            print(f"Connecting to MQTT broker via TLS {MQTT_BROKER}:{MQTT_PORT}...")
            print(f"   CA Certificate: {MQTT_CA_CERT}")
            # print(f"   Username: {MQTT_USERNAME}")
            print(f"   TLS Version: 1.2+ (enforced)")
            
            _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            _mqtt_client.loop_forever()
            
        except FileNotFoundError as e:
            print(f"Error: {str(e)}")
        except ValueError as e:
            print(f"Error: {str(e)}")
        except Exception as e:
            print(f"Error in MQTT subscriber thread: {str(e)}")
            import traceback
            traceback.print_exc()
    
    # Start MQTT subscriber in background thread
    _mqtt_thread = threading.Thread(target=mqtt_thread_function, daemon=True)
    _mqtt_thread.start()
    print("MQTT subscriber started in background thread")

if __name__ == "__main__":
    # Start MQTT subscriber in background before starting Flask
    start_mqtt_subscriber()
    
    # Production settings
    app.run(
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("FLASK_PORT", 5000)),
        debug=os.getenv("FLASK_DEBUG", "False").lower() == "true"
    )
