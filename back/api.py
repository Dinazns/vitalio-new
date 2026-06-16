"""
VitalIO API - Main application entry point.

Run locally:  python api.py
Production:   gunicorn -c gunicorn.conf.py api:app
"""
import logging
import os

from app.ml import engine as ml_module
from app.main import create_app
from app.mqtt_handler import start_mqtt_subscriber

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _bootstrap_background_services() -> None:
    """ML + MQTT subscriber (runs under Gunicorn and python api.py)."""
    try:
        ml_module.init_ml()
    except Exception as e:
        logger.warning("ML init at startup failed: %s", e)
    start_mqtt_subscriber()


app = create_app()
_bootstrap_background_services()

if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("FLASK_PORT", 5000)),
        debug=os.getenv("FLASK_DEBUG", "False").lower() == "true",
    )
