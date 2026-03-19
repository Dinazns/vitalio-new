import time
import random
import datetime
import sys
import json
import paho.mqtt.client as mqtt

import os
import ssl
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

env_path = '.env'
if not os.path.exists(env_path):
    env_path='../.env'
load_dotenv(env_path)

BROKER_ADDRESS=os.getenv("MQTT_BROKER","localhost")
PORT=int(os.getenv("MQTT_PORT","8883"))

MQTT_USERNAME=os.getenv("MQTT_USERNAME","")
MQTT_PASSWORD=os.getenv("MQTT_PASSWORD","")

CA_CERT_PATH=os.getenv("MQTT_CA_CERT","./mosquitto/certs/ca.crt")

U_ID=os.getenv("DEVICE_ID","SIM-ESP32-002")
TOPIC=f"vitalio/dev/{U_ID}/measurements"

MONGODB_URI=os.getenv("MONGODB_URI")
MONGODB_MEDICAL_DB=os.getenv("MONGODB_MEDICAL_DB","Vitalio_Medical")
MONGODB_MEASUREMENTS_COLLECTION=os.getenv("MONGODB_MEASUREMENTS_COLLECTION","measurements")
MONGODB_DIRECT_WRITE_ENABLED=os.getenv("MONGODB_DIRECT_WRITE_ENABLED","true").lower()=="true"

_mongo_client=None

def get_measurements_collection():
    """Create/reuse MongoDB client and return measurements collection."""
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )
        _mongo_client.admin.command("ping")
    return _mongo_client[MONGODB_MEDICAL_DB][MONGODB_MEASUREMENTS_COLLECTION]

def demarrer_simulation():
    print("--- Simulateur IoT : Capteurs vers MQTT ---")
    print(f"u_id utilisé : {U_ID}")

    print(f"\n{'='*60}")
    print("Healthcare-Grade MQTT Publisher (TLS-Encrypted)")
    print(f"{'='*60}")
    print(f"Broker: {BROKER_ADDRESS}:{PORT} (TLS)")
    print(f"Device ID: {U_ID}")
    print(f"Topic: {TOPIC}")
    print(f"{'='*60}\n")

    mongo_collection = None
    if MONGODB_DIRECT_WRITE_ENABLED:
        try:
            mongo_collection = get_measurements_collection()
            print(
                "MongoDB direct write enabled: "
                f"{MONGODB_MEDICAL_DB}.{MONGODB_MEASUREMENTS_COLLECTION}"
            )
        except PyMongoError as e:
            print(f"WARNING: MongoDB connection failed, direct write disabled: {e}")
        except Exception as e:
            print(f"WARNING: Unexpected MongoDB initialization error: {e}")

    if not os.path.exists(CA_CERT_PATH):
        print(f"ERROR: CA certificate not found: {CA_CERT_PATH}")
        print("   Please generate certificates using: mosquitto/generate_certificates.ps1")
        sys.exit(1)

    if not MQTT_USERNAME or not MQTT_PASSWORD:
        print("ERROR: MQTT_USERNAME and MQTT_PASSWORD must be set")
        print("   Anonymous connections are disabled for security.")
        sys.exit(1)

    print(f"Creating secure MQTT client...")
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=U_ID
    )

    try:
        client.tls_set(
            ca_certs=CA_CERT_PATH,
            certfile=None,
            keyfile=None,
            tls_version=ssl.PROTOCOL_TLSv1_2,
            cert_reqs=ssl.CERT_REQUIRED,
            ciphers=None
        )
        print(f"TLS configured (CA: {CA_CERT_PATH})")

        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        print(f"Authentication configured (Username: {MQTT_USERNAME})")

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
            bpm = random.randint(60, 100)
            spo2 = random.randint(95, 100)
            temp_objet = round(random.uniform(36.5, 37.5), 2)
            temp_ambiante = round(random.uniform(20.0, 25.0), 2)
            signal_quality = random.randint(80, 100)

            measured_at = datetime.datetime.now(datetime.timezone.utc)
            timestamp = measured_at.isoformat()

            payload = {
                "timestamp": timestamp,
                "simulated": True,
                "signal_quality": signal_quality,
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

            info = client.publish(TOPIC, payload_json, qos=1)
            info.wait_for_publish()

            if mongo_collection is not None:
                try:
                    mongo_collection.insert_one({
                        "device_id": U_ID,
                        "measured_at": measured_at,
                        "heart_rate": bpm,
                        "spo2": spo2,
                        "temperature": temp_objet,
                        "signal_quality": signal_quality,
                        "source": "simulation",
                        "status": "VALID",
                        "validation_reasons": [],
                    })
                except PyMongoError as e:
                    print(f"WARNING: MongoDB insert failed: {e}")

            print("-" * 50)
            print(f"Données envoyées ({U_ID}) à {timestamp}")
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
