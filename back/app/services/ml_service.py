"""
ML scoring pipeline integration.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any

from pymongo.errors import PyMongoError

from app.ml import engine as ml_module
from app.database import get_medical_db
from app.services.user_service import get_patient_id_from_device, get_user_profile

logger = logging.getLogger(__name__)


def run_ml_scoring(device_id: str, measurement_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score one measurement through the ML module, persist the audit decision,
    create an anomaly event if critical, and enrich the measurement document.
    Returns the ml_result dict.
    """
    to_score = dict(measurement_doc)
    patient_id = get_patient_id_from_device(device_id)
    if patient_id:
        to_score["user_id_auth"] = patient_id
    ml_result = ml_module.score_measurement(to_score)

    is_anomaly = ml_result.get("ml_is_anomaly", False)
    ml_level = ml_result.get("ml_level")

    measurement_update = {
        "ml_score": ml_result["ml_score"],
        "ml_level": ml_level,
        "ml_model_version": ml_result["ml_model_version"],
        "ml_contributing_variables": ml_result.get("ml_contributing_variables", []),
        "ml_is_anomaly": is_anomaly,
        "ml_criticality": ml_result.get("ml_criticality", "normal"),
        "ml_recommended_action": ml_result.get("ml_recommended_action"),
        "ml_anomaly_status": "pending" if is_anomaly and ml_level == "critical" else "none",
    }
    if ml_result.get("ml_if_base_score") is not None:
        measurement_update["ml_if_base_score"] = ml_result["ml_if_base_score"]
    if ml_result.get("ml_tp_exemplar_boost") is not None:
        measurement_update["ml_tp_exemplar_boost"] = ml_result["ml_tp_exemplar_boost"]

    suggestion = None
    if not ml_result.get("ml_skipped"):
        suggestion = {
            "recommended_action": ml_result.get("ml_recommended_action"),
            "clinical_reasoning": ml_result.get("ml_clinical_reasoning", []),
            "urgency": ml_result.get("ml_urgency", "routine"),
        }

        decision_doc = {
            "measurement_id": measurement_doc.get("_id"),
            "device_id": device_id,
            "measured_at": measurement_doc.get("measured_at"),
            "anomaly_score": ml_result["ml_score"],
            "anomaly_level": ml_level,
            "model_version": ml_result["ml_model_version"],
            "contributing_variables": ml_result["ml_contributing_variables"],
            "recommended_action": suggestion["recommended_action"],
            "clinical_reasoning": suggestion["clinical_reasoning"],
            "urgency": suggestion["urgency"],
            "processed_at": datetime.now(timezone.utc),
        }
        if ml_result.get("ml_if_base_score") is not None:
            decision_doc["if_base_score"] = ml_result["ml_if_base_score"]
        if ml_result.get("ml_tp_exemplar_boost") is not None:
            decision_doc["tp_exemplar_boost"] = ml_result["ml_tp_exemplar_boost"]
        try:
            get_medical_db().ml_decisions.insert_one(decision_doc)
        except PyMongoError:
            logger.warning("Failed to insert ml_decision for device %s", device_id)

    user_id_auth = get_patient_id_from_device(device_id)

    anomaly_event = ml_module.build_anomaly_event(
        device_id=device_id,
        user_id_auth=user_id_auth,
        measurement_id=measurement_doc.get("_id"),
        measurement=measurement_doc,
        ml_result=ml_result,
        suggestion=suggestion,
    )
    if anomaly_event:
        try:
            insert_result = get_medical_db().ml_anomalies.insert_one(anomaly_event)
            anomaly_oid = insert_result.inserted_id
            measurement_update["ml_anomaly_id"] = anomaly_oid
            measurement_update["ml_anomaly_status"] = "pending"
            logger.info("ML anomaly event created for device %s (score=%.3f)", device_id, ml_result["ml_score"])
            try:
                from app.services.alert_service import upsert_open_alert_from_ml_critical
                upsert_open_alert_from_ml_critical(
                    device_id=device_id,
                    measurement=measurement_doc,
                    ml_result=ml_result,
                    ml_anomaly_id=anomaly_oid,
                )
            except Exception as e:
                logger.warning("Failed to create CRITICAL ML alert for device %s: %s", device_id, e)
            try:
                from app.services.webpush_service import send_ml_anomaly_push_notifications
                patient_id = get_patient_id_from_device(device_id)
                patient_name = "Un patient"
                if patient_id:
                    profile = get_user_profile(patient_id)
                    patient_name = profile.get("display_name") or profile.get("email") or "Un patient"
                send_ml_anomaly_push_notifications(
                    device_id=device_id,
                    patient_name=patient_name,
                    anomaly_score=ml_result.get("ml_score", 0),
                    recommended_action=ml_result.get("ml_recommended_action"),
                )
            except Exception as e:
                logger.warning("Failed to send ML alert push notifications for device %s: %s", device_id, e)
        except PyMongoError:
            logger.warning("Failed to insert ml_anomaly for device %s", device_id)
    elif ml_level == "warning" and not ml_result.get("ml_skipped"):
        try:
            from app.services.alert_service import upsert_ml_warning_alert
            upsert_ml_warning_alert(device_id, measurement_doc, ml_result)
        except Exception as e:
            logger.warning("Failed to create WARNING ML alert for device %s: %s", device_id, e)

    try:
        get_medical_db().measurements.update_one(
            {"_id": measurement_doc.get("_id")},
            {"$set": measurement_update}
        )
    except PyMongoError:
        logger.warning("Failed to update measurement with ML fields for device %s", device_id)

    return ml_result
