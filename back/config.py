"""
Configuration: environment variables and application constants.
"""
import os
from dotenv import load_dotenv

env_path = '.env'
if not os.path.exists(env_path):
    env_path = '../.env'
load_dotenv(env_path)

# Auth0
AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
API_AUDIENCE = os.getenv("AUTH0_AUDIENCE")
AUTH0_ALGORITHMS = ["RS256"]
AUTH0_ROLE_CLAIM = os.getenv("AUTH0_ROLE_CLAIM", "https://vitalio.app/role")
# Auth0 Management API (Machine-to-Machine app for creating users)
AUTH0_M2M_CLIENT_ID = os.getenv("AUTH0_M2M_CLIENT_ID")
AUTH0_M2M_CLIENT_SECRET = os.getenv("AUTH0_M2M_CLIENT_SECRET")

# MongoDB
MONGODB_URI = os.getenv("MONGODB_URI", "") 
MONGODB_IDENTITY_DB = os.getenv("MONGODB_IDENTITY_DB", "Vitalio_Identity")
MONGODB_MEDICAL_DB = os.getenv("MONGODB_MEDICAL_DB", "Vitalio_Medical")

# MQTT
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "vitalio/dev/+/measurements")
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_CA_CERT = os.getenv("MQTT_CA_CERT", "./mosquitto/certs/ca.crt")
MQTT_ENABLED = os.getenv("MQTT_ENABLED", "true").lower() == "true"

# Alert engine defaults
# Une seule mesure hors seuil suffit pour déclencher une alerte (prises de mesure peu fréquentes).
ALERT_DEFAULT_THRESHOLDS = {
    "spo2_min": 92.0,
    "heart_rate_min": 50.0,
    "heart_rate_max": 120.0,
    "temperature_min": 35.5,
    "temperature_max": 38.0,
}
ALERT_DEFAULT_CONSECUTIVE_BREACHES = 1

# Invitations
INVITE_TTL_HOURS = int(os.getenv("INVITE_TTL_HOURS", "24"))
CABINET_CODE_TTL_MINUTES_DEFAULT = int(os.getenv("CABINET_CODE_TTL_MINUTES", "15"))

# Email (SMTP)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "charldevlin@gmail.com")
FRONTEND_URL = os.getenv("FRONTEND_URL", "")
