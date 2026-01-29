import time
import random
import datetime
import sys
import json
import paho.mqtt.client as mqtt

# ============================================================================
# Healthcare-Grade MQTT Publisher Configuration
# Security: TLS-encrypted connections with certificate validation
# ============================================================================

import os
import ssl
from dotenv import load_dotenv

# Load environment variables
# Try current directory first, then parent directory (for .env in root)
env_path = '.env'
if not os.path.exists(env_path):
    env_path = '../.env'
load_dotenv(env_path)

# MQTT Broker Configuration (TLS)
BROKER_ADDRESS = os.getenv("MQTT_BROKER", "localhost")
PORT = int(os.getenv("MQTT_PORT", "8883"))  # TLS port (8883), not unencrypted (1883)

# Authentication
# In production, you should enforce username/password authentication.
# For local development, our Mosquitto broker is configured with
# `allow_anonymous true`, so we do NOT require credentials here.
# MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
# MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")

# TLS Certificate (CA certificate for broker verification)
CA_CERT_PATH = os.getenv("MQTT_CA_CERT", "./mosquitto/certs/ca.crt")

# Device Configuration
# The DEVICE_ID (serial_number) MUST be provided by the environment and must
# match the value stored in the database (devices.serial_number). This keeps
# MQTT fully agnostic of the user while still allowing user ↔ device linkage
# through the user_devices pivot table.
DEVICE_ID = "SIM-ESP32-003"
if not DEVICE_ID:
    print("ERROR: DEVICE_ID is not set.")
    print("  Please set the environment variable DEVICE_ID to the serial number")
    print("  entered by the patient (e.g. SIM-ESP32-001) before starting data.py:")
    print("     On Windows PowerShell:")
    print("         $env:DEVICE_ID = 'SIM-ESP32-001'")
    print("         python .\\data.py")
    sys.exit(1)

TOPIC = f"vitalio/dev/{DEVICE_ID}/measurements"

# =========================
# Simulation
# =========================
def demarrer_simulation():
    print("--- Simulateur IoT : Capteurs vers MQTT ---")
    print(f"Numéro de capteur utilisé (DEVICE_ID) : {DEVICE_ID}")

    # ========================================================================
    # Healthcare-Grade MQTT Client Configuration (TLS)
    # ========================================================================
    
    print(f"\n{'='*60}")
    print("Healthcare-Grade MQTT Publisher (TLS-Encrypted)")
    print(f"{'='*60}")
    print(f"Broker: {BROKER_ADDRESS}:{PORT} (TLS)")
    print(f"Device serial_number (DEVICE_ID): {DEVICE_ID}")
    print(f"Topic: {TOPIC}")
    print(f"{'='*60}\n")
    
    # Verify CA certificate exists
    if not os.path.exists(CA_CERT_PATH):
        print(f"ERROR: CA certificate not found: {CA_CERT_PATH}")
        print("   Please generate certificates using: mosquitto/generate_certificates.ps1")
        sys.exit(1)
    
    # NOTE:
    # The test broker allows anonymous connections (see mosquitto.conf),
    # so we intentionally do not enforce MQTT_USERNAME / MQTT_PASSWORD here.
    
    # Create MQTT client
    print(f"Creating secure MQTT client...")
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=DEVICE_ID
    )
    
    # ========================================================================
    # TLS CONFIGURATION (Healthcare-Grade Security)
    # ========================================================================
    
    try:
        # Configure TLS
        # cafile: CA certificate to verify broker identity
        # tls_version: Enforce TLS 1.2 or higher (healthcare requirement)
        client.tls_set(
            ca_certs=CA_CERT_PATH,
            certfile=None,  # Client certificate not required (using username/password)
            keyfile=None,   # Client key not required (using username/password)
            tls_version=ssl.PROTOCOL_TLSv1_2,  # TLS 1.2 minimum
            cert_reqs=ssl.CERT_REQUIRED,  # Require broker certificate validation
            ciphers=None  # Use default secure cipher suites
        )
        print(f"TLS configured (CA: {CA_CERT_PATH})")
        
        # Username/password authentication
        # client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        # print(f"Authentication configured (Username: {MQTT_USERNAME})")
        
        # Connect to broker
        print(f"\nConnecting to broker {BROKER_ADDRESS}:{PORT} via TLS...")
        client.connect(BROKER_ADDRESS, PORT, 60)
        print("Connection successful! (TLS-encrypted)")
        client.loop_start()
        
    except FileNotFoundError as e:
        print(f"Error: Certificate file not found: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"Error: Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error connecting to broker: {e}")
        print("   Please verify:")
        print("   1. Broker is running (docker-compose up -d)")
        print("   2. Certificates are generated (mosquitto/generate_certificates.ps1)")
        print("   3. Username/password are correct")
        print("   4. CA certificate path is correct")
        sys.exit(1)

    print(f"Publication des données sur le topic : {TOPIC}")
    print("Ctrl+C pour arrêter.\n")

    try:
        while True:
            # =========================
            # Simulation des capteurs
            # =========================

            # MAX30102
            bpm = random.randint(60, 100)
            spo2 = random.randint(95, 100)

            # MLX90614
            temp_objet = round(random.uniform(36.5, 37.5), 2)
            temp_ambiante = round(random.uniform(20.0, 25.0), 2)

            timestamp = datetime.datetime.utcnow().isoformat()

            # =========================
            # Payload JSON
            # =========================
            payload = {
                "timestamp": timestamp,
                "simulated": True,
                "signal_quality": random.randint(80, 100),
                "sensors": {
                    "MAX30102": {
                        "heart_rate": bpm,
                        "spo2": spo2
                    },
                    "MLX90614": {
                        "object_temp": temp_objet,
                        "ambient_temp": temp_ambiante
                    }
                }
            }

            payload_json = json.dumps(payload)

            # =========================
            # Envoi MQTT
            # =========================
            info = client.publish(TOPIC, payload_json, qos=1)
            info.wait_for_publish()

            # =========================
            # Feedback console
            # =========================
            print("-" * 50)
            print(f"Données envoyées ({DEVICE_ID}) à {timestamp}")
            print(payload_json)
            print("-" * 50)

            time.sleep(30)

    except KeyboardInterrupt:
        print("\nArrêt du simulateur.")
        client.loop_stop()
        client.disconnect()
        sys.exit()

if __name__ == "__main__":
    demarrer_simulation()
