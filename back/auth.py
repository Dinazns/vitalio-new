import json
import os
from urllib.request import urlopen
from functools import wraps
from flask import Flask, request, jsonify, g
from jose import jwt
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# --- AUTH0 CONFIG ---
AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
API_AUDIENCE = os.getenv("AUTH0_AUDIENCE")
ALGORITHMS = ["RS256"]

# --- ERROR HANDLING ---
class AuthError(Exception):
    def __init__(self, error, status_code):
        self.error = error
        self.status_code = status_code

@app.errorhandler(AuthError)
def handle_auth_error(ex):
    return jsonify(ex.error), ex.status_code

# --- AUTH HELPERS ---
def get_token_auth_header():
    auth = request.headers.get("Authorization", None)
    if not auth:
        raise AuthError({"code": "authorization_header_missing"}, 401)

    parts = auth.split()
    if parts[0].lower() != "bearer":
        raise AuthError({"code": "invalid_header"}, 401)
    if len(parts) != 2:
        raise AuthError({"code": "invalid_header"}, 401)

    return parts[1]

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_auth_header()

        jwks = json.loads(
            urlopen(f"https://{AUTH0_DOMAIN}/.well-known/jwks.json").read()
        )

        unverified_header = jwt.get_unverified_header(token)
        rsa_key = next(
            (
                {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"],
                }
                for key in jwks["keys"]
                if key["kid"] == unverified_header["kid"]
            ),
            None,
        )

        if not rsa_key:
            raise AuthError({"code": "invalid_header"}, 401)

        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=ALGORITHMS,
            audience=auth,
            issuer=f"https://{AUTH0_DOMAIN}/"
        )

        g.current_user = payload
        return f(*args, **kwargs)

    return decorated

# --- ROUTES ---
@app.route("/api/public")
def public():
    return jsonify(message="Public endpoint")

@app.route("/api/private")
@requires_auth
def private():
    return jsonify(
        message="Protected endpoint",
        user=g.current_user["sub"]
    )

if __name__ == "__main__":
    app.run(debug=True, port=5000)
