"""
Resolve MQTT TLS CA bundle for local Mosquitto vs public brokers (HiveMQ, etc.).
"""
import os
from typing import Tuple

# Aliases accepted in MQTT_CA_CERT for the system/public CA bundle (Let's Encrypt, etc.).
_CERTIFI_ALIASES = frozenset({"certifi", "system", "default"})


def resolve_mqtt_ca_cert(ca_cert_config: str) -> Tuple[str, str]:
    """
    Return (path_to_ca_bundle, label_for_logs).

    MQTT_CA_CERT may be:
    - certifi | system | default → Mozilla CA bundle via certifi (HiveMQ, public TLS)
    - path to a PEM file → local Mosquitto or custom CA
    """
    normalized = (ca_cert_config or "").strip()
    if normalized.lower() in _CERTIFI_ALIASES:
        import certifi

        path = certifi.where()
        return path, "certifi (public CA bundle)"

    if not os.path.isfile(normalized):
        raise FileNotFoundError(
            f"CA certificate not found: {normalized}\n"
            "Local Mosquitto: run mosquitto/generate_certificates.ps1\n"
            "HiveMQ / public broker: set MQTT_CA_CERT=certifi"
        )

    return normalized, normalized
