"""Flask application factory."""
from __future__ import annotations

import logging

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

from app.config import CORS_EXTRA_ORIGINS, FRONTEND_URL, MONGODB_IDENTITY_DB, MONGODB_MEDICAL_DB
from app.database import init_database
from app.exceptions import AuthError, DatabaseError
from app.api import register_blueprints

logger = logging.getLogger(__name__)


def create_app(*, init_db: bool = True) -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    _cors_base = ["https://vitalio-new.vercel.app", "http://localhost:5173"]
    if FRONTEND_URL and str(FRONTEND_URL).strip():
        _cors_base.append(str(FRONTEND_URL).strip())
    cors_origins = list(dict.fromkeys(_cors_base + CORS_EXTRA_ORIGINS))

    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": cors_origins,
                "methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
                "allow_headers": ["Content-Type", "Authorization"],
                "supports_credentials": True,
            }
        },
    )

    if init_db:
        try:
            init_database()
        except DatabaseError as e:
            logger.warning("Database init at startup: %s", e.error.get("message"))

    register_blueprints(app)

    @app.after_request
    def _ensure_cors_on_all_responses(response: Response):
        """
        Garantir Access-Control-Allow-Origin sur les réponses d'erreur (ex. 500) : sans cela,
        le navigateur affiche une erreur CORS au lieu du corps JSON (même si l'origine est autorisée).
        Avec credentials, l'origine doit être échoée explicitement (pas '*').
        """
        try:
            origin = request.headers.get("Origin")
            if origin and origin in cors_origins:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers.setdefault("Vary", "Origin")
                response.headers.setdefault(
                    "Access-Control-Allow-Headers",
                    request.headers.get("Access-Control-Request-Headers", "Content-Type, Authorization"),
                )
                response.headers.setdefault(
                    "Access-Control-Allow-Methods",
                    "GET, POST, PUT, DELETE, PATCH, OPTIONS",
                )
        except Exception:
            pass
        return response

    @app.errorhandler(AuthError)
    def handle_auth_error(ex: AuthError):
        return jsonify(ex.error), ex.status_code

    @app.errorhandler(DatabaseError)
    def handle_database_error(ex: DatabaseError):
        return jsonify(ex.error), ex.status_code

    @app.errorhandler(500)
    def handle_internal_error(e):
        return jsonify({
            "code": "internal_server_error",
            "message": "An internal server error occurred",
        }), 500

    return app
