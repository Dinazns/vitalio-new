"""
MQTT subscriber for IoT device measurements.
"""
import json
import os
import threading
from datetime import datetime, timezone
from typing import Optional

import paho.mqtt.client as mqtt
from pymongo.errors import PyMongoError

from config import (
    MQTT_BROKER, MQTT_PORT, MQTT_TOPIC, MQTT_USERNAME, MQTT_PASSWORD,
    MQTT_CA_CERT, MQTT_ENABLED,
)
from database import get_medical_db
from services.measurement_service import validate_measurement_payload_mqtt
from services.alert_service import evaluate_measurement_alerts
from services.ml_service import run_ml_scoring
from services.ml_retrain_scheduler import schedule_retrain_after_new_measurement
from services.user_service import get_patient_id_from_device, get_user_profile

_mqtt_client: Optional[mqtt.Client] = None
_mqtt_thread: Optional[threading.Thread] = None


def on_mqtt_message(client, userdata, msg):
    """Handle incoming MQTT messages from IoT devices."""
    try:
        payload = json.loads(msg.payload.decode())
        topic_parts = msg.topic.split('/')
        device_id = topic_parts[2] if len(topic_parts) > 2 else None

        if not device_id:
            print(f"Warning: Could not extract device_id from topic: {msg.topic}")
            return

        validation = validate_measurement_payload_mqtt(payload)

        payload_timestamp = payload.get("timestamp")
        try:
            parsed_timestamp = datetime.fromisoformat(payload_timestamp.replace("Z", "+00:00"))
        except Exception:
            parsed_timestamp = datetime.now(timezone.utc)

        sensors = payload.get("sensors", {})
        max30102 = sensors.get("MAX30102", {})
        mlx90614 = sensors.get("MLX90614", {})

        measurement_doc = {
            "device_id": device_id,
            "measured_at": parsed_timestamp,
            "heart_rate": max30102.get("heart_rate"),
            "spo2": max30102.get("spo2"),
            "temperature": mlx90614.get("object_temp"),
            "signal_quality": payload.get("signal_quality"),
            "status": validation["status"],
            "validation_reasons": validation["reasons"],
            "source": "device",
        }

        try:
            ins = get_medical_db().measurements.insert_one(measurement_doc)
            measurement_doc["_id"] = ins.inserted_id
            print(f"Measurement inserted for device {device_id} (status: {validation['status']})")
            pathology_ctx = None
            pid = get_patient_id_from_device(device_id)
            if pid:
                try:
                    prof = get_user_profile(pid)
                    pathology_ctx = (prof.get("pathology") or "").strip() or None
                except Exception:
                    pathology_ctx = None
            durable_alerts = evaluate_measurement_alerts(
                device_id=device_id, measurement=measurement_doc, pathology=pathology_ctx
            )
            if durable_alerts:
                print(
                    f"Durable alert(s) for {device_id}: "
                    + ", ".join([f"{a['metric']} {a['operator']} {a['threshold']}" for a in durable_alerts])
                )
            try:
                ml_res = run_ml_scoring(device_id=device_id, measurement_doc=measurement_doc)
                if ml_res.get("ml_level") in ("warning", "critical"):
                    print(f"ML {ml_res['ml_level']} for {device_id}: score={ml_res['ml_score']}")
            except Exception as ml_err:
                print(f"Warning: ML scoring failed for device {device_id}: {ml_err}")
            if measurement_doc.get("status") == "VALID":
                try:
                    schedule_retrain_after_new_measurement(device_id)
                except Exception as sched_err:
                    print(f"Warning: schedule ML retrain after MQTT measurement failed: {sched_err}")
        except PyMongoError as db_error:
            print(f"Error inserting measurement for device {device_id}: {str(db_error)}")

    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON payload in MQTT message - {str(e)}")
    except KeyError as e:
        print(f"Error: Missing key in payload - {str(e)}")
    except Exception as e:
        print(f"Error processing MQTT message: {str(e)}")


def _on_mqtt_connect(client, userdata, flags, rc, properties=None):
    """Callback for MQTT connection."""
    if rc == 0:
        print(f"MQTT subscriber connected to {MQTT_BROKER}:{MQTT_PORT}")
        print(f"Subscribed to topic: {MQTT_TOPIC}")
        client.subscribe(MQTT_TOPIC, qos=1)
    else:
        print(f"MQTT connection failed with code: {rc}")


def _on_mqtt_subscribe(client, userdata, mid, granted_qos, properties=None):
    """Callback for MQTT subscription confirmation."""
    print(f"MQTT subscription confirmed (QoS: {granted_qos[0]})")


def start_mqtt_subscriber():
    """Start MQTT subscriber in a background thread."""
    global _mqtt_client, _mqtt_thread

    if not MQTT_ENABLED:
        print("MQTT subscriber disabled (MQTT_ENABLED=false)")
        return
    if not MQTT_BROKER:
        print("MQTT_BROKER not configured, skipping MQTT subscriber")
        return

    def mqtt_thread_function():
        global _mqtt_client
        try:
            _mqtt_client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id="VitalIO_API_Subscriber"
            )
            _mqtt_client.on_connect = _on_mqtt_connect
            _mqtt_client.on_subscribe = _on_mqtt_subscribe
            _mqtt_client.on_message = on_mqtt_message

            if not os.path.exists(MQTT_CA_CERT):
                raise FileNotFoundError(
                    f"CA certificate not found: {MQTT_CA_CERT}\n"
                    "Please generate certificates using: mosquitto/generate_certificates.ps1"
                )

            _mqtt_client.tls_set(
                ca_certs=MQTT_CA_CERT,
                certfile=None,
                keyfile=None,
                tls_version=mqtt.ssl.PROTOCOL_TLSv1_2,
                cert_reqs=mqtt.ssl.CERT_REQUIRED,
                ciphers=None
            )

            if not MQTT_USERNAME or not MQTT_PASSWORD:
                raise ValueError(
                    "MQTT_USERNAME and MQTT_PASSWORD must be set in environment variables."
                )

            _mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

            print(f"Connecting to MQTT broker via TLS {MQTT_BROKER}:{MQTT_PORT}...")
            _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            _mqtt_client.loop_forever()

        except (FileNotFoundError, ValueError, ConnectionRefusedError) as e:
            print(f"Error: {str(e)}")
        except Exception as e:
            print(f"Error in MQTT subscriber thread: {str(e)}")

    _mqtt_thread = threading.Thread(target=mqtt_thread_function, daemon=True)
    _mqtt_thread.start()
    print("MQTT subscriber started in background thread")
