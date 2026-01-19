import time
import random
import datetime
import sys
import json
import paho.mqtt.client as mqtt

# =========================
# Configuration MQTT
# =========================
BROKER_ADDRESS = "localhost"
PORT = 1883

U_ID = "SIM-ESP32-001"
TOPIC = f"vitalio/dev/{U_ID}/measurements"

# =========================
# Simulation
# =========================
def demarrer_simulation():
    print("--- Simulateur IoT : Capteurs vers MQTT ---")
    print(f"u_id utilisé : {U_ID}")

    # Configuration du client MQTT
    print(f"\nConnexion au broker {BROKER_ADDRESS}...")
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=U_ID
    )

    try:
        client.connect(BROKER_ADDRESS, PORT, 60)
        print("Connexion réussie !")
        client.loop_start()
    except Exception as e:
        print(f"Erreur de connexion au broker : {e}")
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
