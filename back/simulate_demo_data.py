# back/scripts/seed_measurements_history.py
import os
import random
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from pymongo import MongoClient, InsertOne

load_dotenv(".env")
from app import config  # noqa: F401 — résolution DNS MongoDB si configurée

DEVICE_ID = "VITALIO-D8D096C4"
WEEKS = 3
MEASURES_PER_DAY = 4   # ~84 points sur 21 jours (ajustez si besoin)

uri = os.environ["MONGODB_URI"]
medical_db = os.getenv("MONGODB_MEDICAL_DB", "Vitalio_Medical")
coll_name = os.getenv("MONGODB_MEASUREMENTS_COLLECTION", "measurements")

client = MongoClient(uri, serverSelectionTimeoutMS=10000)
client.admin.command("ping")
col = client[medical_db][coll_name]

now = datetime.now(timezone.utc)
start = now - timedelta(weeks=WEEKS)
step = timedelta(days=1) / MEASURES_PER_DAY

ops = []
t = start
while t <= now:
    hr = random.randint(62, 92)
    spo2 = random.randint(94, 99)
    temp = round(random.uniform(36.4, 37.6), 1)
    sq = random.randint(70, 98)

    ops.append(InsertOne({
        "device_id": DEVICE_ID,
        "measured_at": t,
        "heart_rate": hr,
        "spo2": spo2,
        "temperature": temp,
        "signal_quality": sq,
        "source": "simulation",
        "status": "VALID",
        "validation_reasons": [],
    }))
    t += step

if ops:
    result = col.bulk_write(ops, ordered=False)
    print(f"Inséré: {result.inserted_count} mesures pour {DEVICE_ID}")
else:
    print("Aucune mesure à insérer.")