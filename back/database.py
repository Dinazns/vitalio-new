"""
MongoDB client and database initialization.
"""
from typing import Optional
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from config import MONGODB_URI, MONGODB_IDENTITY_DB, MONGODB_MEDICAL_DB
from exceptions import DatabaseError

_mongo_client: Optional[MongoClient] = None


def get_mongo_client() -> MongoClient:
    """Return MongoDB client (singleton)."""
    global _mongo_client
    if _mongo_client is None:
        try:
            _mongo_client = MongoClient(
                MONGODB_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
            )
            _mongo_client.admin.command("ping")
        except PyMongoError as e:
            raise DatabaseError({
                "code": "database_connection_error",
                "message": f"Failed to connect to MongoDB: {str(e)}"
            }, 500)
    return _mongo_client


def get_identity_db():
    """Return Vitalio_Identity database (users, users_devices)."""
    return get_mongo_client()[MONGODB_IDENTITY_DB]


def get_medical_db():
    """Return Vitalio_Medical database (measurements)."""
    return get_mongo_client()[MONGODB_MEDICAL_DB]


def init_database():
    """
    Ensure MongoDB collections and indexes exist.
    Vitalio_Identity: users, users_devices, device_enrollments, doctor_patients, caregiver_patients.
    Vitalio_Medical: measurements, doctor_feedback, alert collections.
    """
    try:
        identity_db = get_identity_db()
        medical_db = get_medical_db()

        identity_db.users_devices.create_index("user_id_auth", unique=True)
        identity_db.users.create_index("user_id_auth", unique=True)
        identity_db.users.create_index("role")
        identity_db.doctor_patients.create_index(
            [("doctor_user_id_auth", 1), ("patient_user_id_auth", 1)],
            unique=True
        )
        identity_db.doctor_patients.create_index("doctor_user_id_auth")
        identity_db.caregiver_patients.create_index(
            [("caregiver_user_id_auth", 1), ("patient_user_id_auth", 1)],
            unique=True
        )
        identity_db.caregiver_patients.create_index("caregiver_user_id_auth")
        identity_db.users_devices.create_index("device_id")
        identity_db.doctor_invites.create_index("token_hash", unique=True)
        identity_db.doctor_invites.create_index("expires_at", expireAfterSeconds=0)
        identity_db.doctor_invites.create_index([("doctor_user_id_auth", 1), ("mode", 1), ("created_at", -1)])
        identity_db.caregiver_invites.create_index("token_hash", unique=True)
        identity_db.caregiver_invites.create_index("expires_at", expireAfterSeconds=0)
        identity_db.caregiver_invites.create_index("patient_user_id_auth")
        identity_db.audit_links.create_index([("event_type", 1), ("created_at", -1)])
        identity_db.audit_links.create_index([("doctor_user_id_auth", 1), ("patient_user_id_auth", 1), ("created_at", -1)])
        identity_db.alerts.create_index("medical_alert_id", unique=True)
        identity_db.alerts.create_index([("author", 1), ("createdAt", -1)])
        identity_db.push_subscriptions.create_index([("user_id_auth", 1), ("endpoint", 1)], unique=True)
        identity_db.push_subscriptions.create_index("user_id_auth")
        identity_db.device_enrollments.create_index("device_id", unique=True)
        identity_db.device_enrollments.create_index([("enrollment_code", 1), ("enrolled", 1)])

        medical_db.measurements.create_index([("device_id", 1), ("measured_at", -1)])
        medical_db.doctor_feedback.create_index([("patient_user_id_auth", 1), ("created_at", -1)])
        medical_db.doctor_feedback.create_index([("doctor_user_id_auth", 1), ("created_at", -1)])
        medical_db.alert_thresholds.create_index(
            [("scope", 1), ("device_id", 1), ("pathology", 1)],
            unique=True
        )
        try:
            medical_db.alert_thresholds.create_index(
                [("device_id", 1)],
                unique=True,
                name="uniq_alert_thresholds_patient_device",
                partialFilterExpression={"scope": "patient", "device_id": {"$exists": True, "$type": "string"}},
            )
        except PyMongoError:
            pass
        medical_db.alert_thresholds.create_index("enabled")
        medical_db.threshold_breach_events.create_index([("device_id", 1), ("created_at", -1)])
        medical_db.threshold_breach_events.create_index([("measurement_id", 1)], sparse=True)
        medical_db.alerts.create_index([("device_id", 1), ("status", 1), ("created_at", -1)])
        medical_db.alerts.create_index([("device_id", 1), ("metric", 1), ("status", 1)])

        medical_db.ml_anomalies.create_index([("device_id", 1), ("status", 1), ("created_at", -1)])
        medical_db.ml_anomalies.create_index([("user_id_auth", 1), ("status", 1)])
        medical_db.ml_anomalies.create_index([("user_id_auth", 1), ("created_at", -1)])
        medical_db.ml_anomalies.create_index("measurement_id")
        medical_db.ml_anomalies.create_index("status")
        medical_db.ml_decisions.create_index([("device_id", 1), ("processed_at", -1)])
        medical_db.ml_decisions.create_index("measurement_id", unique=True)
        medical_db.ml_model_versions.create_index("version", unique=True)
        medical_db.ml_thresholds.create_index("_id")

        medical_db.alerts.create_index("ml_anomaly_id", unique=True, sparse=True)
        medical_db.alerts.create_index("measurement_id", sparse=True)
        medical_db.alerts.create_index("alert_source")
        medical_db.alerts.create_index([("device_id", 1), ("alert_source", 1), ("status", 1)])

        medical_db.measurements.create_index("ml_is_anomaly", sparse=True)
        medical_db.measurements.create_index("ml_anomaly_status", sparse=True)
        medical_db.measurements.create_index("ml_anomaly_id", sparse=True)

        # Append-only audit journal for alert lifecycle events
        medical_db.alert_events.create_index([("medical_alert_id", 1), ("created_at", -1)])
        medical_db.alert_events.create_index([("medical_alert_id", 1), ("event_type", 1)])
        medical_db.alert_events.create_index([("actor_user_id_auth", 1), ("created_at", -1)])
        medical_db.alert_events.create_index("created_at")
        try:
            from services.ml_thresholds_store import load_ml_thresholds_from_db
            load_ml_thresholds_from_db()
        except Exception:
            pass
    except DatabaseError:
        raise
    except PyMongoError as e:
        raise DatabaseError({
            "code": "database_init_error",
            "message": f"Failed to initialize MongoDB: {str(e)}"
        }, 500)
