"""
Invitation, email, and linkage helpers.
"""
import hashlib
import io
import logging
import re
import secrets
import smtplib
import threading
from datetime import datetime, timedelta, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Any, Optional

import qrcode
from pymongo.errors import PyMongoError

from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM,
    FRONTEND_URL, INVITE_TTL_HOURS,
)
from database import get_identity_db
from exceptions import AuthError
from services.user_service import get_user_profile

logger = logging.getLogger(__name__)


def hash_secret_token(token: str) -> str:
    """Hash token/code with SHA-256 before persistence."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_qr_png(url: str, size: int = 256) -> bytes:
    """Generate QR code PNG image for given URL."""
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size, size))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def send_invitation_email(
    patient_email: str,
    invite_token: str,
    web_invite_url: str,
    expires_at: datetime,
    doctor_display_name: str = "Votre médecin",
    password_setup_url: Optional[str] = None,
) -> None:
    """Send invitation email with QR code to patient.
    If password_setup_url is provided, invite the user to set their password first.
    """
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        raise ValueError("SMTP non configuré: SMTP_HOST, SMTP_USER et SMTP_PASSWORD sont requis dans .env")

    logger.info("Envoi email invitation vers %s (SMTP: %s:%s)", patient_email, SMTP_HOST, SMTP_PORT)

    qr_bytes = generate_qr_png(web_invite_url)
    expires_str = expires_at.strftime("%d/%m/%Y à %H:%M") if isinstance(expires_at, datetime) else str(expires_at)

    msg = MIMEMultipart("related")
    msg["Subject"] = "Invitation VitalIO - Associez-vous à votre médecin"
    msg["From"] = EMAIL_FROM
    msg["To"] = patient_email

    password_block = ""
    if password_setup_url:
        password_block = f"""
  <p style="margin: 16px 0;">
    <strong>Première connexion :</strong> votre compte a été créé. 
    <a href="{password_setup_url}" style="color: #2563eb; font-weight: bold;">Définissez votre mot de passe</a> 
    pour accéder à VitalIO.
  </p>
  <p>Ensuite, cliquez sur le lien ci-dessous pour accepter l'invitation.</p>
"""
    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 500px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #2563eb;">Invitation VitalIO</h2>
  <p>Bonjour,</p>
  <p>{doctor_display_name} vous invite à associer votre compte VitalIO pour le suivi de vos constantes vitales.</p>
  {password_block}
  <p>Cliquez sur ce lien : <a href="{web_invite_url}">{web_invite_url}</a></p>
  <p style="color: #666; font-size: 14px;">Cette invitation expire le <strong>{expires_str}</strong>.</p>
  <p>Cordialement,<br/>L'équipe VitalIO</p>
</body>
</html>
"""
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    img = MIMEImage(qr_bytes)
    img.add_header("Content-ID", "<qrcode>")
    img.add_header("Content-Disposition", "inline", filename="invitation-qr.png")
    msg.attach(img)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(EMAIL_FROM, patient_email, msg.as_string())
        logger.info("Email envoyé avec succès vers %s", patient_email)
    except smtplib.SMTPException as e:
        logger.exception("Erreur SMTP: %s", e)
        raise ValueError(f"Erreur SMTP: {e}") from e
    except OSError as e:
        logger.exception("Erreur connexion SMTP: %s", e)
        raise ValueError(f"Impossible de se connecter à {SMTP_HOST}:{SMTP_PORT}") from e


def send_caregiver_invitation_email(
    caregiver_email: str,
    invite_token: str,
    web_invite_url: str,
    expires_at: datetime,
    patient_display_name: str = "Un patient VitalIO",
) -> None:
    """Send invitation email to emergency contact inviting them as caregiver."""
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        raise ValueError("SMTP non configuré")

    expires_str = expires_at.strftime("%d/%m/%Y à %H:%M") if isinstance(expires_at, datetime) else str(expires_at)

    msg = MIMEMultipart("related")
    msg["Subject"] = "VitalIO - Vous êtes désigné(e) comme contact d'urgence"
    msg["From"] = EMAIL_FROM
    msg["To"] = caregiver_email

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 500px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #2563eb;">VitalIO - Invitation Aidant</h2>
  <p>Bonjour,</p>
  <p><strong>{patient_display_name}</strong> vous a désigné(e) comme contact d'urgence sur VitalIO.</p>
  <p style="text-align: center; margin: 24px 0;">
    <a href="{web_invite_url}" style="display: inline-block; padding: 14px 32px; background: #2563eb; color: #fff !important; text-decoration: none; border-radius: 8px; font-weight: bold;">Créer mon compte aidant</a>
  </p>
  <p>Si le bouton ne fonctionne pas, copiez ce lien dans votre navigateur :</p>
  <p><a href="{web_invite_url}" style="color: #2563eb; word-break: break-all;">{web_invite_url}</a></p>
  <p style="color: #666; font-size: 14px;">Cette invitation expire le <strong>{expires_str}</strong>.</p>
</body>
</html>
"""
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(EMAIL_FROM, caregiver_email, msg.as_string())
    logger.info("Email invitation aidant envoyé vers %s", caregiver_email)


def invite_emergency_contact_if_needed(
    patient_user_id_auth: str,
    emergency_email: str,
    patient_display_name: str = "Un patient VitalIO",
) -> Optional[str]:
    """
    If emergency contact email does not belong to existing user, create caregiver invite and send email.
    Returns invite_token if email sent, None otherwise.
    """
    if not emergency_email or not emergency_email.strip():
        return None
    emergency_email = emergency_email.strip().lower()

    existing_user = get_identity_db().users.find_one(
        {"email": {"$regex": f"^{re.escape(emergency_email)}$", "$options": "i"}},
        projection={"user_id_auth": 1, "role": 1},
    )

    if existing_user:
        caregiver_uid = existing_user["user_id_auth"]
        if caregiver_uid == patient_user_id_auth:
            return None
        try:
            get_identity_db().caregiver_patients.update_one(
                {"caregiver_user_id_auth": caregiver_uid, "patient_user_id_auth": patient_user_id_auth},
                {"$setOnInsert": {
                    "caregiver_user_id_auth": caregiver_uid,
                    "patient_user_id_auth": patient_user_id_auth,
                    "created_at": datetime.now(timezone.utc),
                }},
                upsert=True,
            )
            if existing_user.get("role") not in ("caregiver", "aidant"):
                get_identity_db().users.update_one(
                    {"user_id_auth": caregiver_uid},
                    {"$set": {"role": "caregiver"}},
                )
            logger.info("Auto-linked existing user %s as caregiver for %s", caregiver_uid, patient_user_id_auth)
        except PyMongoError as e:
            logger.warning("Failed to auto-link caregiver %s: %s", caregiver_uid, e)
        return None

    already_invited = get_identity_db().caregiver_invites.find_one({
        "patient_user_id_auth": patient_user_id_auth,
        "caregiver_email": emergency_email,
        "used_at": None,
        "expires_at": {"$gt": datetime.now(timezone.utc)},
    })
    if already_invited:
        return None

    invite_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=max(INVITE_TTL_HOURS, 1) * 7)

    try:
        get_identity_db().caregiver_invites.insert_one({
            "token_hash": hash_secret_token(invite_token),
            "patient_user_id_auth": patient_user_id_auth,
            "caregiver_email": emergency_email,
            "created_by_user_id_auth": patient_user_id_auth,
            "expires_at": expires_at,
            "used_at": None,
            "created_at": now,
        })
        log_caregiver_audit_event(
            "caregiver_invite_created",
            actor_user_id_auth=patient_user_id_auth,
            patient_user_id_auth=patient_user_id_auth,
            caregiver_email=emergency_email,
            details={"expires_at": expires_at.isoformat()},
        )
    except PyMongoError as e:
        logger.warning("Failed to create caregiver invite for %s: %s", emergency_email, e)
        return None

    web_invite_url = f"{FRONTEND_URL.rstrip('/')}/invite-caregiver?token={invite_token}"

    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
        def _send_async():
            try:
                send_caregiver_invitation_email(
                    caregiver_email=emergency_email,
                    invite_token=invite_token,
                    web_invite_url=web_invite_url,
                    expires_at=expires_at,
                    patient_display_name=patient_display_name,
                )
            except Exception as e:
                logger.exception("Envoi email invitation aidant échoué: %s", e)

        threading.Thread(target=_send_async, daemon=True).start()
    else:
        logger.warning("SMTP not configured - caregiver invite created but email NOT sent for %s", emergency_email)

    return invite_token


def generate_invite_token() -> str:
    """Generate non-predictable invitation token."""
    return secrets.token_urlsafe(32)


def generate_cabinet_code() -> str:
    """Generate short non-predictable cabinet code."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


def log_link_audit_event(
    event_type: str,
    actor_user_id_auth: str,
    doctor_user_id_auth: str,
    patient_user_id_auth: str,
    mode: str,
    details: Optional[Dict[str, Any]] = None
):
    """Write immutable audit event for linkage operations."""
    get_identity_db().audit_links.insert_one({
        "event_type": event_type,
        "actor_user_id_auth": actor_user_id_auth,
        "doctor_user_id_auth": doctor_user_id_auth,
        "patient_user_id_auth": patient_user_id_auth,
        "mode": mode,
        "created_at": datetime.now(timezone.utc),
        "details": details or {},
    })


def _get_metric_label(metric: str, operator: str = "") -> str:
    """Return human-readable metric label for alert emails."""
    labels = {
        "heart_rate": "Fréquence cardiaque",
        "spo2": "SpO2 (oxygénation)",
        "temperature": "Température",
    }
    base = labels.get(metric, metric)
    if operator == "lt":
        return f"{base} (trop bas)"
    if operator == "gt":
        return f"{base} (trop élevé)"
    return base


def send_alert_email(
    recipient_email: str,
    recipient_name: str,
    patient_name: str,
    metric: str,
    operator: str,
    value: float,
    threshold: float,
    is_doctor: bool = True,
) -> None:
    """
    Send health alert email to doctor or caregiver.
    """
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("SMTP non configuré - email alerte non envoyé vers %s", recipient_email)
        return

    metric_label = _get_metric_label(metric, operator)
    value_str = f"{value:.1f}" if isinstance(value, (int, float)) else str(value)
    threshold_str = f"{threshold:.1f}" if isinstance(threshold, (int, float)) else str(threshold)

    if is_doctor:
        subject = f"VitalIO - Alerte santé : {patient_name} - {metric_label}"
        intro = f"Une alerte a été déclenchée pour le patient <strong>{patient_name}</strong>."
        detail = f"Type de défaillance : <strong>{metric_label}</strong>. Valeur mesurée : {value_str} (seuil : {threshold_str})."
    else:
        subject = f"VitalIO - Alerte : état de santé de {patient_name}"
        intro = f"L'état de santé de <strong>{patient_name}</strong> nécessite votre attention."
        detail = f"Type de défaillance : <strong>{metric_label}</strong>. Valeur mesurée : {value_str} (seuil : {threshold_str})."

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 500px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #b91c1c;">VitalIO - Alerte santé</h2>
  <p>Bonjour {recipient_name or 'Madame, Monsieur'},</p>
  <p>{intro}</p>
  <p>{detail}</p>
  <p style="margin-top: 24px;">
    <a href="{FRONTEND_URL.rstrip('/')}" style="display: inline-block; padding: 12px 24px; background: #2563eb; color: #fff !important; text-decoration: none; border-radius: 8px; font-weight: bold;">
      Voir les détails sur VitalIO
    </a>
  </p>
  <p style="color: #666; font-size: 14px;">Cordialement,<br/>L'équipe VitalIO</p>
</body>
</html>
"""
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = recipient_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    def _send_async():
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(EMAIL_FROM, recipient_email, msg.as_string())
            logger.info("Email alerte envoyé vers %s (patient: %s, métrique: %s)", recipient_email, patient_name, metric)
        except Exception as e:
            logger.exception("Envoi email alerte échoué vers %s: %s", recipient_email, e)

    threading.Thread(target=_send_async, daemon=True).start()


def send_alert_emails_for_new_alert(
    device_id: str,
    metric: str,
    operator: str,
    value: float,
    threshold: float,
    patient_name: str = "Un patient",
) -> None:
    """
    Send alert emails to all doctors and caregivers of the patient.
    Called when a new threshold alert is created.
    """
    from services.user_service import (
        get_patient_id_from_device,
        get_assigned_doctor_ids_for_patient,
        get_assigned_caregiver_ids_for_patient,
        get_user_profile,
    )

    patient_id = get_patient_id_from_device(device_id)
    if not patient_id:
        logger.warning("Impossible d'envoyer les emails d'alerte: patient inconnu pour device %s", device_id)
        return

    display_name = patient_name
    if patient_name == "Un patient":
        profile = get_user_profile(patient_id)
        display_name = profile.get("display_name") or profile.get("email") or "Un patient"

    doctor_ids = get_assigned_doctor_ids_for_patient(patient_id)
    caregiver_ids = get_assigned_caregiver_ids_for_patient(patient_id)

    for did in doctor_ids:
        doc_profile = get_user_profile(did)
        email = _normalize_email(doc_profile.get("email"))
        if email:
            name = doc_profile.get("display_name") or doc_profile.get("first_name") or ""
            send_alert_email(
                recipient_email=email,
                recipient_name=name,
                patient_name=display_name,
                metric=metric,
                operator=operator,
                value=value,
                threshold=threshold,
                is_doctor=True,
            )

    for cid in caregiver_ids:
        cg_profile = get_user_profile(cid)
        email = _normalize_email(cg_profile.get("email"))
        if email:
            name = cg_profile.get("display_name") or cg_profile.get("first_name") or ""
            send_alert_email(
                recipient_email=email,
                recipient_name=name,
                patient_name=display_name,
                metric=metric,
                operator=operator,
                value=value,
                threshold=threshold,
                is_doctor=False,
            )


def _normalize_email(email_raw) -> Optional[str]:
    """Normalize and validate email for sending."""
    if not email_raw or not isinstance(email_raw, str):
        return None
    s = str(email_raw).strip().lower()
    return s if "@" in s and "." in s and len(s) > 5 else None


def log_caregiver_audit_event(
    event_type: str,
    actor_user_id_auth: str,
    patient_user_id_auth: str,
    caregiver_email: Optional[str] = None,
    caregiver_user_id_auth: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
):
    """Write immutable audit event for caregiver invite operations."""
    d = dict(details or {})
    if caregiver_email is not None:
        d["caregiver_email"] = caregiver_email
    if caregiver_user_id_auth is not None:
        d["caregiver_user_id_auth"] = caregiver_user_id_auth
    get_identity_db().audit_links.insert_one({
        "event_type": event_type,
        "actor_user_id_auth": actor_user_id_auth,
        "doctor_user_id_auth": "",
        "patient_user_id_auth": patient_user_id_auth,
        "mode": "caregiver_invite",
        "created_at": datetime.now(timezone.utc),
        "details": d,
    })


def create_doctor_patient_link(
    doctor_user_id_auth: str,
    patient_user_id_auth: str,
    linked_by: str,
    linked_by_user_id_auth: str
) -> bool:
    """Create doctor-patient link if absent. Returns True when created, False when already exists."""
    link_doc = {
        "doctor_user_id_auth": doctor_user_id_auth,
        "patient_user_id_auth": patient_user_id_auth,
        "linked_by": linked_by,
        "linked_by_user_id_auth": linked_by_user_id_auth,
        "created_at": datetime.now(timezone.utc),
    }
    result = get_identity_db().doctor_patients.update_one(
        {
            "doctor_user_id_auth": doctor_user_id_auth,
            "patient_user_id_auth": patient_user_id_auth,
        },
        {"$setOnInsert": link_doc},
        upsert=True
    )
    return result.upserted_id is not None


def get_invite_document_or_404(token_or_code: str, mode: str) -> Dict[str, Any]:
    """Fetch invite/code by hashed token and raise HTTP-oriented errors."""
    token_hash = hash_secret_token(token_or_code)
    invite = get_identity_db().doctor_invites.find_one({
        "token_hash": token_hash,
        "mode": mode,
    })
    if not invite:
        raise AuthError({
            "code": "invite_not_found",
            "message": "Invitation/code not found"
        }, 404)
    if invite.get("used_at"):
        raise AuthError({
            "code": "invite_already_used",
            "message": "Invitation/code already used"
        }, 409)
    expires_at = invite.get("expires_at")
    if isinstance(expires_at, datetime):
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise AuthError({
                "code": "invite_expired",
                "message": "Invitation/code expired"
            }, 410)
    return invite
