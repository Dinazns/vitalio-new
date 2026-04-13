"""
inject_test_measurements.py
----------------------------
Génère et injecte des mesures de test réalistes sur 90 jours dans MongoDB.
Couvre : heart_rate, spo2, temperature, signal_quality, ml_level, scoring ML.

Usage :
    python inject_test_measurements.py [--device SIM-ESP32-001] [--days 90] [--dry-run]
"""

import argparse
import math
import random
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient, ASCENDING
from pymongo.errors import BulkWriteError

# ─────────────────────────────────────────────
# CONFIG  (aligné sur config.py / Vitalio)
# ─────────────────────────────────────────────
MONGO_URI = "mongodb://localhost:27017"
DB_MEDICAL = "Vitalio_Medical"    # base des measurements (api, mqtt_handler)
DB_IDENTITY = "Vitalio_Identity"  # base des users_devices
COLLECTION_MEASUREMENTS = "measurements"
COLLECTION_USERS_DEVICES = "users_devices"

DEFAULT_DEVICE_ID = "SIM-ESP32-001"
DEFAULT_DAYS      = 90


# ─────────────────────────────────────────────
# CONNEXION  (même logique que data.py)
# ─────────────────────────────────────────────
def get_client() -> MongoClient:
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=5_000)


def get_measurements_collection(client: MongoClient):
    return client[DB_MEDICAL][COLLECTION_MEASUREMENTS]


def resolve_device_id(client: MongoClient, device_id: str | None) -> str:
    """Retourne device_id explicite ou le premier trouvé dans users_devices (Vitalio_Identity)."""
    if device_id:
        return device_id
    col = client[DB_IDENTITY][COLLECTION_USERS_DEVICES]
    doc = col.find_one({}, {"device_id": 1})
    if doc and "device_id" in doc:
        return doc["device_id"]
    return DEFAULT_DEVICE_ID


# ─────────────────────────────────────────────
# GÉNÉRATEUR DE TIMESTAMPS
# ─────────────────────────────────────────────
def generate_timestamps(days: int):
    """
    Génère 4-8 mesures/jour réparties principalement entre 6h-12h et 18h-22h.
    Quelques mesures diurnes/nocturnes ponctuelles pour la diversité heatmap.
    """
    now   = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    ts = start
    while ts <= now:
        hour = ts.hour
        in_morning = 6  <= hour < 12
        in_evening = 18 <= hour < 22

        # Probabilité d'émettre un point selon l'heure
        if in_morning or in_evening:
            emit_prob = 0.92
        elif 12 <= hour < 18:
            emit_prob = 0.55   # après-midi : moderé
        else:
            emit_prob = 0.20   # nuit : rare mais présent

        if random.random() < emit_prob:
            # petite variation aléatoire en minutes pour éviter les timestamps réguliers
            jitter = timedelta(minutes=random.randint(-25, 25))
            yield ts + jitter

        # Intervalle entre tentatives : 2h-6h
        ts += timedelta(minutes=random.randint(120, 360))


# ─────────────────────────────────────────────
# GÉNÉRATEURS DE VALEURS PHYSIOLOGIQUES
# ─────────────────────────────────────────────
def sinusoidal_walk(
    t: float,
    base: float,
    amplitude: float,
    period_hours: float = 24.0,
    noise_sigma: float = 1.0,
) -> float:
    """
    Valeur = base + amplitude * sin(2π t / period) + bruit gaussien.
    t : heure fractionnaire dans la journée (0-24).
    """
    angle = 2 * math.pi * t / period_hours
    return base + amplitude * math.sin(angle) + random.gauss(0, noise_sigma)


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def gen_heart_rate(ts: datetime, prev: float | None) -> float:
    """60-100 bpm avec marche aléatoire légère + sinusoïde circadienne."""
    hour = ts.hour + ts.minute / 60.0
    base = sinusoidal_walk(hour, base=72, amplitude=8, noise_sigma=2.5)
    if prev is not None:
        base = 0.7 * prev + 0.3 * base   # lissage marche aléatoire
    return clamp(round(base, 1), 50, 110)


def gen_spo2(ts: datetime, prev: float | None) -> float:
    """95-100 % (quelques valeurs basses pour déclencher des alertes)."""
    hour = ts.hour + ts.minute / 60.0
    base = sinusoidal_walk(hour, base=97.5, amplitude=1.0, noise_sigma=0.4)
    if prev is not None:
        base = 0.75 * prev + 0.25 * base
    # 3 % de chances d'une valeur basse (alerte)
    if random.random() < 0.03:
        base = random.uniform(90, 94)
    return clamp(round(base, 1), 88, 100)


def gen_temperature(ts: datetime, prev: float | None) -> float:
    """36.0-37.5 °C (quelques pics fébriles pour alertes)."""
    hour = ts.hour + ts.minute / 60.0
    base = sinusoidal_walk(hour, base=36.8, amplitude=0.4, noise_sigma=0.15)
    if prev is not None:
        base = 0.8 * prev + 0.2 * base
    # 2 % de chances d'un épisode fébrile
    if random.random() < 0.02:
        base = random.uniform(37.8, 39.2)
    return clamp(round(base, 2), 35.0, 40.5)


def gen_signal_quality() -> int:
    """85-100, légèrement biaisé vers les hautes valeurs."""
    return int(clamp(random.gauss(94, 4), 85, 100))


# ─────────────────────────────────────────────
# SCORING ML / ALERTES
# ─────────────────────────────────────────────
def compute_ml_level(hr: float, spo2: float, temp: float) -> str:
    """Règle simple simulant une inférence ML."""
    score = 0
    if hr < 55 or hr > 100:  score += 2
    if spo2 < 93:            score += 3
    elif spo2 < 95:          score += 1
    if temp > 38.5:          score += 3
    elif temp > 37.5:        score += 1

    if score >= 4:
        return "critical"
    elif score >= 2:
        return "warning"
    return "normal"


def build_validation_reasons(hr: float, spo2: float, temp: float) -> list[str]:
    reasons = []
    if hr > 100:  reasons.append("tachycardie détectée")
    if hr < 55:   reasons.append("bradycardie détectée")
    if spo2 < 95: reasons.append("SpO2 basse")
    if temp > 37.5: reasons.append("température élevée")
    return reasons


def build_ml_scores(hr: float, spo2: float, temp: float) -> dict:
    """Scores factices simulant une sortie de modèle ML."""
    anomaly   = clamp(random.gauss(0.1, 0.08) + (0.4 if hr > 100 else 0), 0, 1)
    risk      = clamp(random.gauss(0.12, 0.06) + (0.3 if spo2 < 95 else 0), 0, 1)
    stability = clamp(1 - anomaly * 0.6 - risk * 0.4 + random.gauss(0, 0.05), 0, 1)
    return {
        "anomaly_score": round(anomaly, 4),
        "risk_score":    round(risk, 4),
        "stability":     round(stability, 4),
    }


# ─────────────────────────────────────────────
# CONSTRUCTION D'UN DOCUMENT
# ─────────────────────────────────────────────
def build_document(
    device_id: str,
    ts: datetime,
    prev_hr: float | None,
    prev_spo2: float | None,
    prev_temp: float | None,
) -> dict:
    hr   = gen_heart_rate(ts, prev_hr)
    spo2 = gen_spo2(ts, prev_spo2)
    temp = gen_temperature(ts, prev_temp)
    ml_level = compute_ml_level(hr, spo2, temp)
    reasons  = build_validation_reasons(hr, spo2, temp)
    scores   = build_ml_scores(hr, spo2, temp)

    return {
        "device_id":          device_id,
        "measured_at":        ts,
        "heart_rate":         hr,
        "spo2":               spo2,
        "temperature":        temp,
        "signal_quality":     gen_signal_quality(),
        "source":             "simulated",
        "status":             "validated",
        "ml_level":           ml_level,
        "validation_reasons": reasons,
        "ml_scores":          scores,
        "created_at":         datetime.now(timezone.utc),
    }


# ─────────────────────────────────────────────
# INJECTION PRINCIPALE
# ─────────────────────────────────────────────
def inject(device_id: str, days: int, dry_run: bool = False):
    client = get_client()
    col    = get_measurements_collection(client)

    device_id = resolve_device_id(client, device_id)
    print(f"🎯 Device cible : {device_id}")
    print(f"📅 Période       : {days} jours")
    print(f"🔧 Mode          : {'DRY-RUN (aucune écriture)' if dry_run else 'INSERTION RÉELLE'}")
    print()

    timestamps = list(generate_timestamps(days))
    total = len(timestamps)
    print(f"⏱  Timestamps générés : {total}")

    # Vérifier les doublons éventuels
    existing = col.count_documents({"device_id": device_id})
    print(f"📦 Documents existants pour ce device : {existing}")

    documents  = []
    prev_hr    = None
    prev_spo2  = None
    prev_temp  = None

    for ts in sorted(timestamps):
        doc = build_document(device_id, ts, prev_hr, prev_spo2, prev_temp)
        prev_hr   = doc["heart_rate"]
        prev_spo2 = doc["spo2"]
        prev_temp = doc["temperature"]
        documents.append(doc)

    # Statistiques rapides
    ml_counts = {}
    for d in documents:
        ml_counts[d["ml_level"]] = ml_counts.get(d["ml_level"], 0) + 1
    print(f"📊 Répartition ml_level : {ml_counts}")

    if dry_run:
        print(f"\n✅ [DRY-RUN] {total} documents prêts - aucun envoyé à MongoDB.")
        return

    # Insertion par lots de 500
    batch_size = 500
    inserted   = 0
    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        try:
            result = col.insert_many(batch, ordered=False)
            inserted += len(result.inserted_ids)
            print(f"  ✔ Lot {i // batch_size + 1} : {len(result.inserted_ids)} insérés")
        except BulkWriteError as bwe:
            ok = bwe.details.get("nInserted", 0)
            inserted += ok
            print(f"  ⚠ Lot {i // batch_size + 1} : {ok} insérés, "
                  f"{len(bwe.details.get('writeErrors', []))} erreurs")

    print(f"\n✅ Injection terminée : {inserted} / {total} documents insérés.")

    # Création d'index utiles
    print("🔍 Vérification des index…")
    col.create_index([("device_id", ASCENDING), ("measured_at", ASCENDING)], background=True)
    col.create_index([("ml_level", ASCENDING)], background=True)
    print("   Index OK.")

    client.close()


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject test measurements into MongoDB")
    parser.add_argument("--device",  default=DEFAULT_DEVICE_ID, help="device_id cible")
    parser.add_argument("--days",    type=int, default=DEFAULT_DAYS, help="Nombre de jours en arrière")
    parser.add_argument("--dry-run", action="store_true", help="Simule sans écrire dans MongoDB")
    args = parser.parse_args()

    inject(device_id=args.device, days=args.days, dry_run=args.dry_run)