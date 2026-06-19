"""
Invitation, email, and linkage helpers.
"""
import hashlib
import io
import logging
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

import qrcode
from pymongo.errors import PyMongoError

from app.config import (
    FRONTEND_URL, INVITE_TTL_HOURS,
)
from app.database import get_identity_db
from app.exceptions import AuthError
from app.services.mailjet_service import (
    is_mailjet_configured,
    make_inline_png_attachment,
    send_html_email,
    email_cta_button,
    email_text_link,
    escape_href,
)
from app.services.user_service import get_user_profile

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
    """Send invitation email with link to patient.
    If password_setup_url is provided, invite the user to set their password first.
    """
    if not is_mailjet_configured():
        raise ValueError("Mailjet non configuré: SMTP_USER, SMTP_PASSWORD et EMAIL_FROM sont requis")

    if not str(web_invite_url).startswith(("http://", "https://")):
        raise ValueError(
            "Lien d'invitation invalide (URL absolue requise). "
            "Vérifiez la variable d'environnement FRONTEND_URL sur le serveur."
        )

    expires_str = expires_at.strftime("%d/%m/%Y à %H:%M") if isinstance(expires_at, datetime) else str(expires_at)

    password_block = ""
    if password_setup_url:
        password_block = f"""
  <p style="margin: 16px 0;">
    <strong>Première connexion :</strong> votre compte a été créé.
    <a href="{escape_href(password_setup_url)}" target="_blank" rel="noopener noreferrer" style="color: #2563eb; font-weight: bold; text-decoration: underline;">Définissez votre mot de passe</a>
    pour accéder à VitalIO.
  </p>
  <p>Ensuite, cliquez sur le bouton ci-dessous pour accepter l'invitation.</p>
"""
    cta_button = email_cta_button(web_invite_url, "Accepter l'invitation")
    fallback_link = email_text_link(web_invite_url)
    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 500px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #2563eb;">Invitation VitalIO</h2>
  <p>Bonjour,</p>
  <p>{doctor_display_name} vous invite à associer votre compte VitalIO pour le suivi de vos constantes vitales.</p>
  {password_block}
  {cta_button}
  <p>Si le bouton ne fonctionne pas, copiez ce lien dans votre navigateur :</p>
  {fallback_link}
  <p style="color: #666; font-size: 14px;">Cette invitation expire le <strong>{expires_str}</strong>.</p>
  <p>Cordialement,<br/>L'équipe VitalIO</p>
</body>
</html>
"""
    text_part = (
        f"Invitation VitalIO\n\n"
        f"{doctor_display_name} vous invite à associer votre compte VitalIO.\n\n"
        f"Acceptez l'invitation en ouvrant ce lien :\n{web_invite_url}\n\n"
        f"Cette invitation expire le {expires_str}.\n"
    )
    send_html_email(
        patient_email,
        "Invitation VitalIO - Associez-vous à votre médecin",
        html_body,
        text_part=text_part,
    )


def send_device_enrollment_code_email(
    patient_email: str,
    patient_display_name: str,
    device_id: str,
    enrollment_code: str,
    expires_at: datetime,
) -> None:
    """Envoie le code à 6 chiffres d'enregistrement du boîtier (généré par l'ESP32)."""
    if not is_mailjet_configured():
        raise ValueError("Mailjet non configuré: SMTP_USER, SMTP_PASSWORD et EMAIL_FROM sont requis")
    if not patient_email:
        raise ValueError("Adresse email patient manquante")

    expires_str = expires_at.strftime("%d/%m/%Y à %H:%M") if isinstance(expires_at, datetime) else str(expires_at)
    enroll_url = f"{FRONTEND_URL.rstrip('/')}/patient/enroll-device"
    display_name = patient_display_name or "Bonjour"

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 500px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #2563eb;">Code d'enregistrement VitalIO</h2>
  <p>Bonjour {display_name},</p>
  <p>Votre boîtier <strong>{device_id}</strong> est prêt à être associé à votre compte.</p>
  <p style="text-align: center; margin: 28px 0;">
    <span style="display: inline-block; font-size: 2rem; font-weight: bold; letter-spacing: 0.35em; padding: 16px 24px; background: #eff6ff; border-radius: 12px; color: #1e40af;">{enrollment_code}</span>
  </p>
  <p>Ce code est également affiché sur l&apos;écran de votre boîtier. Ouvrez VitalIO, allez dans <strong>Mon boîtier</strong> et saisissez-le.</p>
  {email_cta_button(enroll_url, "Enregistrer mon boîtier")}
  <p style="color: #666; font-size: 14px;">Ce code expire le <strong>{expires_str}</strong> (environ 10 minutes).</p>
  <p>Cordialement,<br/>L'équipe VitalIO</p>
</body>
</html>
"""
    send_html_email(
        patient_email,
        f"VitalIO - Code d'enregistrement du boîtier {device_id}",
        html_body,
    )
    logger.info("Email code enrollment envoyé vers %s (device %s)", patient_email, device_id)


def send_device_confirmation_email(
    patient_email: str,
    patient_display_name: str,
    confirmation_url: str,
    device_id: str,
    expires_at: datetime,
) -> None:
    """Email de confirmation d'enregistrement du boîtier (lien valable 24h)."""
    if not is_mailjet_configured():
        raise ValueError("Mailjet non configuré: SMTP_USER, SMTP_PASSWORD et EMAIL_FROM sont requis")
    if not patient_email:
        raise ValueError("Adresse email patient manquante")

    expires_str = expires_at.strftime("%d/%m/%Y à %H:%M") if isinstance(expires_at, datetime) else str(expires_at)
    qr_bytes = generate_qr_png(confirmation_url)

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 500px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #2563eb;">Confirmation du boîtier VitalIO</h2>
  <p>Bonjour {patient_display_name},</p>
  <p>Vous avez demandé l'enregistrement du dispositif <strong>{device_id}</strong>.</p>
  <p style="text-align: center; margin: 20px 0;">
    <img src="cid:qrcode" alt="QR code confirmation" width="200" height="200" />
  </p>
  {email_cta_button(confirmation_url, "Confirmer l'enregistrement")}
  <p>Si le bouton ne fonctionne pas, copiez ce lien :</p>
  {email_text_link(confirmation_url)}
  <p style="color: #666; font-size: 14px;">Ce lien expire le <strong>{expires_str}</strong>.</p>
  <p>Cordialement,<br/>L'équipe VitalIO</p>
</body>
</html>
"""
    send_html_email(
        patient_email,
        "Confirmation d'enregistrement du dispositif VitalIO",
        html_body,
        inline_attachments=[make_inline_png_attachment(qr_bytes, "qrcode", "device-confirm-qr.png")],
    )
    logger.info("Email confirmation device envoyé vers %s (device %s)", patient_email, device_id)


def send_caregiver_invitation_email(
    caregiver_email: str,
    invite_token: str,
    web_invite_url: str,
    expires_at: datetime,
    patient_display_name: str = "Un patient VitalIO",
) -> None:
    """Send invitation email to emergency contact inviting them as caregiver."""
    if not is_mailjet_configured():
        raise ValueError("Mailjet non configuré")

    expires_str = expires_at.strftime("%d/%m/%Y à %H:%M") if isinstance(expires_at, datetime) else str(expires_at)

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 500px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #2563eb;">VitalIO - Invitation Aidant</h2>
  <p>Bonjour,</p>
  <p><strong>{patient_display_name}</strong> vous a désigné(e) comme contact d'urgence sur VitalIO.</p>
  {email_cta_button(web_invite_url, "Créer mon compte aidant")}
  <p>Si le bouton ne fonctionne pas, copiez ce lien dans votre navigateur :</p>
  {email_text_link(web_invite_url)}
  <p style="color: #666; font-size: 14px;">Cette invitation expire le <strong>{expires_str}</strong>.</p>
</body>
</html>
"""
    send_html_email(
        caregiver_email,
        "VitalIO - Vous êtes désigné(e) comme contact d'urgence",
        html_body,
    )
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

    if is_mailjet_configured():
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
    else:
        logger.warning("Mailjet not configured - caregiver invite created but email NOT sent for %s", emergency_email)

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
    if not is_mailjet_configured():
        logger.warning("Mailjet non configuré - email alerte non envoyé vers %s", recipient_email)
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

    def _send_async():
        try:
            send_html_email(recipient_email, subject, html_body)
            logger.info(
                "Email alerte envoyé vers %s (patient: %s, métrique: %s)",
                recipient_email, patient_name, metric,
            )
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
    from app.services.user_service import (
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


def send_doctor_patient_unlink_email(
    patient_email: str,
    patient_display_name: str,
    doctor_display_name: str,
) -> None:
    """Notify patient that their doctor removed the medical follow-up link."""
    if not is_mailjet_configured():
        logger.warning("Mailjet non configuré - email retrait médecin non envoyé vers %s", patient_email)
        return
    if not str(patient_email or "").strip():
        raise ValueError("Adresse email patient manquante")

    greeting_name = (patient_display_name or "").strip() or "Bonjour"
    doctor_label = (doctor_display_name or "").strip() or "Votre médecin"
    subject = "VitalIO - Fin de suivi médical"
    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 500px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #2563eb;">Fin de suivi médical</h2>
  <p>Bonjour {greeting_name},</p>
  <p><strong>{doctor_label}</strong> a retiré le lien de suivi médical entre votre compte VitalIO et son cabinet.</p>
  <p>Votre compte VitalIO et vos données personnelles restent accessibles. Vous pouvez continuer à utiliser votre boîtier et, si besoin, vous associer à un autre professionnel de santé.</p>
  <p>Cordialement,<br/>L'équipe VitalIO</p>
</body>
</html>
"""
    text_part = (
        f"Fin de suivi médical VitalIO\n\n"
        f"Bonjour {greeting_name},\n\n"
        f"{doctor_label} a retiré le lien de suivi médical entre votre compte VitalIO et son cabinet.\n\n"
        f"Votre compte VitalIO et vos données personnelles restent accessibles.\n"
    )
    send_html_email(patient_email, subject, html_body, text_part=text_part)
    logger.info("Email retrait médecin envoyé vers %s (médecin: %s)", patient_email, doctor_label)


def remove_doctor_patient_link(
    doctor_user_id_auth: str,
    patient_user_id_auth: str,
) -> bool:
    """Remove doctor-patient link. Returns True when a link existed and was deleted."""
    result = get_identity_db().doctor_patients.delete_one({
        "doctor_user_id_auth": doctor_user_id_auth,
        "patient_user_id_auth": patient_user_id_auth,
    })
    return result.deleted_count > 0


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
