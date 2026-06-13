"""
Backfill patient_pseudo_id for existing patients in Vitalio_Identity.users.
Run once after deploying pseudonymisation: python scripts/backfill_patient_pseudo.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import config  # noqa: F401
from app.database import get_identity_db, init_database
from app.services.patient_pseudo_service import ensure_patient_pseudo_id


def main():
    init_database()
    identity = get_identity_db()
    cursor = identity.users.find({"role": "patient"}, {"user_id_auth": 1, "patient_pseudo_id": 1})
    count = 0
    for doc in cursor:
        uid = doc.get("user_id_auth")
        if not uid or doc.get("patient_pseudo_id"):
            continue
        pseudo = ensure_patient_pseudo_id(uid)
        if pseudo:
            count += 1
            print(f"  {uid} -> {pseudo}")
    print(f"Backfill complete: {count} patient(s) updated.")


if __name__ == "__main__":
    main()
