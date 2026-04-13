"""
Simulateur d'alerte VitalIO - injection directe en base.
Lance ce script depuis le dossier back/ avec le venv activé :

    python simulate_alert.py                          # SpO2 critique (85%)
    python simulate_alert.py --metric heart_rate_low  # Bradycardie (38 bpm)
    python simulate_alert.py --metric heart_rate_high # Tachycardie (135 bpm)
    python simulate_alert.py --metric temperature     # Hyperthermie (39.5°C)
    python simulate_alert.py --metric manual          # Alerte bouton patient
    python simulate_alert.py --device SIM-ESP32-002   # Autre device
    python simulate_alert.py --list-devices           # Voir les devices disponibles
"""
import argparse
import sys
import os
from datetime import datetime, timezone

# Assure que le répertoire courant est bien 'back/'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(".env" if os.path.exists(".env") else "../.env")

from database import get_identity_db, get_medical_db, init_database
from services.alert_service import evaluate_measurement_alerts, create_manual_alert

PRESETS = {
    "spo2": {
        "heart_rate": 78.0,
        "spo2": 85.0,        # seuil min = 92 %
        "temperature": 36.8,
        "label": "Hypoxémie (SpO2 = 85 %)",
    },
    "heart_rate_low": {
        "heart_rate": 38.0,  # seuil min = 50 bpm
        "spo2": 97.0,
        "temperature": 36.5,
        "label": "Bradycardie (FC = 38 bpm)",
    },
    "heart_rate_high": {
        "heart_rate": 135.0, # seuil max = 120 bpm
        "spo2": 96.0,
        "temperature": 37.2,
        "label": "Tachycardie (FC = 135 bpm)",
    },
    "temperature": {
        "heart_rate": 82.0,
        "spo2": 96.0,
        "temperature": 39.5, # seuil max = 38.0 °C
        "label": "Hyperthermie (Temp = 39.5 °C)",
    },
    "manual": {
        "label": "Alerte manuelle patient (bouton)",
    },
}


def list_devices():
    devices = list(get_identity_db().users_devices.find({}, {"_id": 0, "device_id": 1, "user_id_auth": 1}))
    if not devices:
        print("Aucun device enregistré.")
        return
    print(f"{'Device ID':<25} {'user_id_auth'}")
    print("-" * 70)
    for d in devices:
        print(f"{d.get('device_id','?'):<25} {d.get('user_id_auth','?')}")


def get_default_device():
    doc = get_identity_db().users_devices.find_one({}, sort=[("_id", 1)])
    if doc:
        return doc["device_id"]
    return None


def simulate(device_id: str, metric: str):
    preset = PRESETS[metric]
    print(f"\n{'='*60}")
    print(f"  Simulation : {preset['label']}")
    print(f"  Device     : {device_id}")
    print(f"{'='*60}")

    if metric == "manual":
        patient_doc = get_identity_db().users_devices.find_one({"device_id": device_id})
        patient_id = patient_doc.get("user_id_auth", "sim-patient") if patient_doc else "sim-patient"
        result = create_manual_alert(
            device_id=device_id,
            patient_user_id_auth=patient_id,
            message="[simulation] Je me sens mal, besoin d'aide.",
        )
        if result["created"]:
            print(f"  [OK] Alerte manuelle creee  -> alert_id = {result['alert_id']}")
        else:
            print(f"  [X]  Anti-spam actif : {result['reason']} (wait {result.get('wait_seconds','?')} s)")
        return

    now = datetime.now(timezone.utc)
    measurement_doc = {
        "device_id": device_id,
        "measured_at": now,
        "heart_rate": preset["heart_rate"],
        "spo2": preset["spo2"],
        "temperature": preset["temperature"],
        "signal_quality": 90,
        "source": "simulation",
        "status": "VALID",
        "validation_reasons": [],
    }

    ins = get_medical_db().measurements.insert_one(measurement_doc)
    measurement_doc["_id"] = ins.inserted_id
    print(f"  [OK] Mesure inseree -> _id = {ins.inserted_id}")
    print(f"       FC={preset['heart_rate']} bpm | SpO2={preset['spo2']}% | T={preset['temperature']} C")

    triggered = evaluate_measurement_alerts(
        device_id=device_id,
        measurement=measurement_doc,
    )

    if triggered:
        for t in triggered:
            new_flag = "NOUVELLE" if t.get("is_new") else "mise a jour"
            print(f"  [OK] Alerte {new_flag} -> {t['metric']} {t['operator']} seuil={t['threshold']} valeur={t['value']}")
    else:
        print("  [i]  Aucune alerte declenchee (valeurs OK ou consecutivite non atteinte)")

    print(f"\n  Consultez /doctor/alertes dans l'UI pour voir l'alerte.")


def main():
    parser = argparse.ArgumentParser(description="Simulateur d'alerte VitalIO")
    parser.add_argument("--metric", choices=list(PRESETS.keys()), default="spo2",
                        help="Type d'alerte à simuler (défaut: spo2)")
    parser.add_argument("--device", default=None, help="device_id cible (défaut: premier device en base)")
    parser.add_argument("--list-devices", action="store_true", help="Lister les devices disponibles et quitter")
    args = parser.parse_args()

    try:
        init_database()
    except Exception as e:
        print(f"Erreur connexion MongoDB : {e}")
        sys.exit(1)

    if args.list_devices:
        list_devices()
        return

    device_id = args.device or get_default_device()
    if not device_id:
        print("Aucun device trouvé. Ajoutez d'abord un patient ou précisez --device SIM-ESP32-XXX")
        sys.exit(1)

    simulate(device_id, args.metric)


if __name__ == "__main__":
    main()
