"""
Configuration: environment variables and application constants.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

_BASE_DIR = Path(__file__).resolve().parent
# Priorité : back/.env (à côté de ce fichier), puis cwd, puis racine du repo.
# Évite de charger ../.env (souvent localhost) quand on lance l'API depuis un autre dossier.
for _env_path in (_BASE_DIR / ".env", Path.cwd() / ".env", _BASE_DIR.parent / ".env"):
    if _env_path.is_file():
        load_dotenv(_env_path)
        break

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
# Optionnel : serveurs DNS pour les requêtes SRV/TXT (mongodb+srv). Utile sous Windows si d'autres
# cartes (WSL, Hyper-V) pointent vers des DNS 192.168.* qui timeout. Ex. : 8.8.8.8,1.1.1.1
MONGODB_DNS_SERVERS = os.getenv("MONGODB_DNS_SERVERS", "").strip()


def apply_mongodb_dns_resolver() -> None:
    """Force dnspython à utiliser des résolveurs explicites pour mongodb+srv (évite DNS LAN cassés)."""
    if not MONGODB_DNS_SERVERS:
        return
    servers = [s.strip() for s in MONGODB_DNS_SERVERS.split(",") if s.strip()]
    if not servers:
        return
    try:
        import dns.resolver

        res = dns.resolver.Resolver(configure=False)
        res.nameservers = servers
        dns.resolver.default_resolver = res
    except ImportError:
        pass


apply_mongodb_dns_resolver()

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

# CORS: comma-separated extra origins (e.g. Vercel preview URLs). Merged in api.py with base list.
def _parse_cors_origins_env(raw: str) -> list:
    if not raw or not raw.strip():
        return []
    return [o.strip() for o in raw.split(",") if o.strip()]


CORS_EXTRA_ORIGINS = _parse_cors_origins_env(os.getenv("CORS_ORIGINS", ""))

# Web Push (VAPID keys - generate with: py -m vapid --gen)
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
