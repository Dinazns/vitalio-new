"""
Backfill severity_level on existing medical.alerts documents.
Run once after deploying multi-level alert taxonomy:
  python scripts/backfill_alert_severity.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import config  # noqa: F401
from app.database import get_medical_db, init_database
from app.services.severity_level import resolve_alert_severity_level


def main():
    init_database()
    medical = get_medical_db()
    updated = 0
    cursor = medical.alerts.find({}, {"_id": 1})
    for doc in cursor:
        full = medical.alerts.find_one({"_id": doc["_id"]})
        if not full:
            continue
        level = resolve_alert_severity_level(full)
        if full.get("severity_level") != level:
            medical.alerts.update_one({"_id": doc["_id"]}, {"$set": {"severity_level": level}})
            updated += 1
    print(f"Backfill complete: {updated} alert(s) updated.")


if __name__ == "__main__":
    main()
