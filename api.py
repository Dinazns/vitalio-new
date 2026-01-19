import paho.mqtt.client as mqtt
import json
from datetime import datetime
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

BROKER_ADDRESS = os.getenv("MQTT_BROKER")
PORT = int(os.getenv("MQTT_PORT"))
TOPIC = os.getenv("MQTT_TOPIC")

def validate_payload(payload: dict) -> dict:
    reasons = []

    sensors = payload.get("sensors", {})
    max30102 = sensors.get("MAX30102", {})
    mlx90614 = sensors.get("MLX90614", {})

    hr = max30102.get("heart_rate")
    spo2 = max30102.get("spo2")
    temp = mlx90614.get("object_temp")
    signal_quality = payload.get("signal_quality")

    # ---- Heart Rate ----
    if hr is None or hr < 30 or hr >220:
        reasons.append("heart_rate_out_of_range")

    # ---- SpO2 ----
    if spo2 is None or spo2 < 70 or spo2 > 100:
        reasons.append("spo2_out_of_range")

    # ---- Temperature ----
    if temp is None or temp < 34 or temp > 42:
        reasons.append("temperature_out_of_range")

    # ---- Signal Quality ----
    if signal_quality is None or signal_quality < 50:
        reasons.append("low_signal_quality")

    status = "VALID" if not reasons else "INVALID"

    return {
        "status": status,
        "reasons": reasons,
        "validated_at": datetime.utcnow().isoformat()
    }

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())

        # Extract u_id from topic
        topic_parts = msg.topic.split('/')
        u_id = topic_parts[2] if len(topic_parts) > 2 else None

        validation = validate_payload(payload)

        enriched_payload = {
            **payload,
            "validation": validation
        }

        print("\nDonnée reçue")
        print(json.dumps(enriched_payload, indent=2))

        data_to_insert = {
            "u_id": u_id,
            "timestamp": payload["timestamp"],
            "heart_rate": payload["sensors"]["MAX30102"]["heart_rate"],
            "spo2": payload["sensors"]["MAX30102"]["spo2"],
            "temperature": payload["sensors"]["MLX90614"]["object_temp"],
            "signal_quality": payload["signal_quality"],
            "status": validation["status"],
            "reasons": validation["reasons"]
        }

        print("Data to insert:", json.dumps(data_to_insert, indent=2))

        supabase.table("measurements").insert(data_to_insert).execute()

    except Exception as e:
        print(" Erreur de traitement :", e)

client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id="VitalIO_Validator"
)

client.connect(BROKER_ADDRESS, PORT, 60)
client.subscribe(TOPIC, qos=1)
client.on_message = on_message

print("Subscriber VitalIO – validation active")
client.loop_forever()
