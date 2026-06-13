"""
VitalIO API - Main application entry point.

Run locally:  python api.py
Production:   gunicorn api:app --bind 0.0.0.0:$PORT
"""
import logging
import os

from app.ml import engine as ml_module
from app.config import MONGODB_IDENTITY_DB, MONGODB_MEDICAL_DB
from app.database import init_database
from app.exceptions import DatabaseError
from app.main import create_app
from app.mqtt_handler import start_mqtt_subscriber

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = create_app()

if __name__ == "__main__":
    try:
        init_database()
        print(f"MongoDB initialized ({MONGODB_IDENTITY_DB}, {MONGODB_MEDICAL_DB})")
    except DatabaseError as e:
        print(f"Warning: Database initialization failed: {e.error.get('message')}")

    ml_module.init_ml()
    start_mqtt_subscriber()

    app.run(
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("FLASK_PORT", 5000)),
        debug=os.getenv("FLASK_DEBUG", "False").lower() == "true",
    )
