"""
Web Push notification service.
Sends push notifications to doctors and caregivers when a patient triggers an alert.
"""
import json
import logging
from typing import Dict, Any, List, Optional

from config import VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, FRONTEND_URL
from database import get_identity_db

logger = logging.getLogger(__name__)


def _get_push_subscriptions_for_users(user_ids: List[str]) -> List[Dict[str, Any]]:
    """Return push subscriptions for the given user IDs (doctors/caregivers)."""
    if not user_ids:
        return []
    try:
        coll = get_identity_db().push_subscriptions
        cursor = coll.find({"user_id_auth": {"$in": user_ids}, "enabled": True})
        return list(cursor)
    except Exception as e:
        logger.warning("Failed to fetch push subscriptions: %s", e)
        return []


def _send_push(subscription: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    """Send a single web push. Returns True if sent successfully."""
    if not VAPID_PRIVATE_KEY:
        logger.debug("VAPID_PRIVATE_KEY not set, skipping web push")
        return False
    try:
        from pywebpush import webpush, WebPushException
        sub_info = subscription.get("subscription") or subscription
        if isinstance(sub_info, str):
            sub_info = json.loads(sub_info)
        endpoint = sub_info.get("endpoint", "?") if isinstance(sub_info, dict) else "?"
        logger.info("[PUSH] Sending to endpoint: %s", endpoint[:60])
        webpush(
            subscription_info=sub_info,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": "mailto:support@vitalio.app"},
        )
        logger.info("[PUSH] Sent successfully to %s", endpoint[:60])
        return True
    except Exception as e:
        logger.warning("[PUSH] Failed for subscription: %s", e)
        return False


def send_alert_push_notifications(
    device_id: str,
    metric: str,
    operator: str,
    value: float,
    threshold: float,
    patient_name: str = "Un patient",
) -> None:
    """
    Send web push notifications to all doctors and caregivers of the patient.
    Called when a new threshold alert is created (same audience as alert emails).
    """
    from services.user_service import (
        get_patient_id_from_device,
        get_assigned_doctor_ids_for_patient,
        get_assigned_caregiver_ids_for_patient,
    )

    logger.info("[PUSH] send_alert_push_notifications called for device=%s metric=%s", device_id, metric)

    if not VAPID_PRIVATE_KEY:
        logger.warning("[PUSH] VAPID_PRIVATE_KEY not set, aborting")
        return

    patient_id = get_patient_id_from_device(device_id)
    logger.info("[PUSH] patient_id resolved: %s", patient_id)
    if not patient_id:
        logger.warning("[PUSH] No patient found for device %s", device_id)
        return

    doctor_ids = get_assigned_doctor_ids_for_patient(patient_id)
    caregiver_ids = get_assigned_caregiver_ids_for_patient(patient_id)
    recipient_ids = list(dict.fromkeys(doctor_ids + caregiver_ids))
    logger.info("[PUSH] recipients: doctors=%s caregivers=%s", doctor_ids, caregiver_ids)
    if not recipient_ids:
        logger.warning("[PUSH] No recipients found for patient %s", patient_id)
        return

    subscriptions = _get_push_subscriptions_for_users(recipient_ids)
    logger.info("[PUSH] subscriptions found: %d for recipients %s", len(subscriptions), recipient_ids)
    if not subscriptions:
        logger.warning("[PUSH] No push subscriptions in DB for recipients %s", recipient_ids)
        return

    # Build human-readable metric label
    metric_labels = {
        "heart_rate": "Fréquence cardiaque",
        "spo2": "SpO2",
        "temperature": "Température",
    }
    metric_label = metric_labels.get(metric, metric)
    op_label = "inférieur à" if operator == "lt" else "supérieur à"

    base_url = (FRONTEND_URL or "").rstrip("/")
    body = f"{patient_name}: {metric_label} {op_label} {threshold} (valeur: {value})"
    tag = f"alert-{device_id}-{metric}"

    from services.user_service import get_user_role
    sent = 0
    for sub in subscriptions:
        role = (get_user_role(sub.get("user_id_auth") or "") or "").lower()
        url = f"{base_url}/caregiver" if role in ("caregiver", "aidant") else f"{base_url}/doctor/alertes"
        payload = {"title": "VitalIO - Nouvelle alerte", "body": body, "url": url, "tag": tag}
        if _send_push(sub, payload):
            sent += 1
    if sent:
        logger.info("Web push sent to %d/%d recipients for patient %s alert", sent, len(subscriptions), patient_name)


def send_manual_alert_push_notifications(
    device_id: str,
    patient_name: str = "Un patient",
    patient_message: Optional[str] = None,
) -> None:
    """
    Send web push notifications to all doctors and caregivers when the patient
    manually triggers an alert via the alert button.
    """
    from services.user_service import (
        get_patient_id_from_device,
        get_assigned_doctor_ids_for_patient,
        get_assigned_caregiver_ids_for_patient,
    )

    logger.info("[PUSH] send_manual_alert_push_notifications called for device=%s", device_id)

    if not VAPID_PRIVATE_KEY:
        logger.warning("[PUSH] VAPID_PRIVATE_KEY not set, aborting")
        return

    patient_id = get_patient_id_from_device(device_id)
    logger.info("[PUSH] patient_id resolved: %s", patient_id)
    if not patient_id:
        logger.warning("[PUSH] No patient found for device %s", device_id)
        return

    doctor_ids = get_assigned_doctor_ids_for_patient(patient_id)
    caregiver_ids = get_assigned_caregiver_ids_for_patient(patient_id)
    recipient_ids = list(dict.fromkeys(doctor_ids + caregiver_ids))
    logger.info("[PUSH] recipients: doctors=%s caregivers=%s", doctor_ids, caregiver_ids)
    if not recipient_ids:
        logger.warning("[PUSH] No recipients found for patient %s", patient_id)
        return

    subscriptions = _get_push_subscriptions_for_users(recipient_ids)
    logger.info("[PUSH] subscriptions found: %d for recipients %s", len(subscriptions), recipient_ids)
    if not subscriptions:
        logger.warning("[PUSH] No push subscriptions in DB for recipients %s", recipient_ids)
        return

    base_url = (FRONTEND_URL or "").rstrip("/")
    body = f"{patient_name} a déclenché une alerte manuelle"
    if patient_message:
        body = f"{body} : {patient_message[:120]}{'…' if len(patient_message) > 120 else ''}"
    tag = f"manual-alert-{device_id}"

    from services.user_service import get_user_role
    sent = 0
    for sub in subscriptions:
        role = (get_user_role(sub.get("user_id_auth") or "") or "").lower()
        url = f"{base_url}/caregiver" if role in ("caregiver", "aidant") else f"{base_url}/doctor/alertes"
        payload = {"title": "VitalIO - Alerte patient", "body": body, "url": url, "tag": tag}
        if _send_push(sub, payload):
            sent += 1
    if sent:
        logger.info("Manual alert push sent to %d/%d recipients for patient %s", sent, len(subscriptions), patient_name)


def send_ml_anomaly_push_notifications(
    device_id: str,
    patient_name: str = "Un patient",
    anomaly_score: float = 0.0,
    recommended_action: Optional[str] = None,
) -> None:
    """
    Send web push notifications to all doctors and caregivers when an ML anomaly (critical) is created.
    """
    from services.user_service import (
        get_patient_id_from_device,
        get_assigned_doctor_ids_for_patient,
        get_assigned_caregiver_ids_for_patient,
    )

    if not VAPID_PRIVATE_KEY:
        return

    patient_id = get_patient_id_from_device(device_id)
    if not patient_id:
        return

    doctor_ids = get_assigned_doctor_ids_for_patient(patient_id)
    caregiver_ids = get_assigned_caregiver_ids_for_patient(patient_id)
    recipient_ids = list(dict.fromkeys(doctor_ids + caregiver_ids))
    if not recipient_ids:
        return

    subscriptions = _get_push_subscriptions_for_users(recipient_ids)
    if not subscriptions:
        return

    base_url = (FRONTEND_URL or "").rstrip("/")
    score_pct = f"{(anomaly_score * 100):.0f}%"
    body = f"{patient_name}: Alerte IA détectée (risque {score_pct})"
    if recommended_action:
        body = f"{body} - {recommended_action[:80]}{'…' if len(recommended_action or '') > 80 else ''}"
    tag = f"ml-alert-{device_id}"

    from services.user_service import get_user_role
    sent = 0
    for sub in subscriptions:
        role = (get_user_role(sub.get("user_id_auth") or "") or "").lower()
        url = f"{base_url}/caregiver" if role in ("caregiver", "aidant") else f"{base_url}/doctor/alertes"
        payload = {"title": "VitalIO - Alerte IA", "body": body, "url": url, "tag": tag}
        if _send_push(sub, payload):
            sent += 1
    if sent:
        logger.info("ML web push sent to %d/%d recipients for patient %s", sent, len(subscriptions), patient_name)
