"""
Mailjet transactional email via REST API (HTTPS).
Used instead of SMTP because Render blocks outbound ports 25/587/465.

Reuses existing env vars:
  SMTP_USER     -> Mailjet API Key (public)
  SMTP_PASSWORD -> Mailjet Secret Key
  EMAIL_FROM    -> verified sender address
"""
from __future__ import annotations

import base64
import html as html_module
import logging
import re
from typing import Any, Dict, List, Optional

import requests

from app.config import SMTP_USER, SMTP_PASSWORD, EMAIL_FROM

logger = logging.getLogger(__name__)

MAILJET_SEND_URL = "https://api.mailjet.com/v3.1/send"
MAILJET_TIMEOUT = 30


def escape_href(url: str) -> str:
    """Encode & and other characters for safe use in HTML href attributes."""
    return html_module.escape(url or "", quote=True)


def email_cta_button(url: str, label: str, *, bg_color: str = "#2563eb") -> str:
    """Bulletproof CTA button (table layout) — clickable in Gmail, Outlook, mobile."""
    safe_url = escape_href(url)
    safe_label = html_module.escape(label)
    return f"""<table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" style="margin:24px auto;">
<tr>
<td align="center" bgcolor="{bg_color}" style="border-radius:8px;background-color:{bg_color};">
<a href="{safe_url}" target="_blank" rel="noopener noreferrer" style="display:inline-block;padding:14px 32px;font-family:Arial,Helvetica,sans-serif;font-size:16px;font-weight:bold;color:#ffffff;text-decoration:none;border-radius:8px;line-height:1.25;mso-padding-alt:0;">
{safe_label}
</a>
</td>
</tr>
</table>"""


def email_text_link(url: str, link_text: Optional[str] = None) -> str:
    safe_url = escape_href(url)
    display = html_module.escape(link_text or url)
    return (
        f'<p style="word-break:break-all;font-size:14px;margin:12px 0;">'
        f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" '
        f'style="color:#2563eb;text-decoration:underline;">{display}</a></p>'
    )


def is_mailjet_configured() -> bool:
    return bool(SMTP_USER and SMTP_PASSWORD and EMAIL_FROM)


def make_inline_png_attachment(png_bytes: bytes, content_id: str, filename: str) -> Dict[str, Any]:
    return {
        "ContentType": "image/png",
        "Filename": filename,
        "ContentID": content_id,
        "Base64Content": base64.b64encode(png_bytes).decode("ascii"),
    }


def _html_to_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text or "Message VitalIO"


def _format_mailjet_error(resp: requests.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return (resp.text or resp.content.decode("utf-8", errors="replace") or "(réponse vide)")[:1000]

    parts: List[str] = []
    messages = data.get("Messages") if isinstance(data, dict) else None
    if isinstance(messages, list):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if str(msg.get("Status", "")).lower() == "error":
                for err in msg.get("Errors") or []:
                    if isinstance(err, dict):
                        code = err.get("ErrorCode") or err.get("ErrorIdentifier") or ""
                        message = err.get("ErrorMessage") or err.get("Message") or str(err)
                        parts.append(f"{code}: {message}".strip(": "))
    if parts:
        return "; ".join(parts)
    return str(data)[:1000]


def _raise_if_message_errors(data: Dict[str, Any]) -> None:
    messages = data.get("Messages")
    if not isinstance(messages, list):
        return
    errors: List[str] = []
    for msg in messages:
        if not isinstance(msg, dict) or str(msg.get("Status", "")).lower() != "error":
            continue
        for err in msg.get("Errors") or []:
            if isinstance(err, dict):
                code = err.get("ErrorCode") or err.get("ErrorIdentifier") or ""
                message = err.get("ErrorMessage") or err.get("Message") or str(err)
                errors.append(f"{code}: {message}".strip(": "))
    if errors:
        raise ValueError(f"Erreur Mailjet: {'; '.join(errors)}")


def send_html_email(
    to_email: str,
    subject: str,
    html_body: str,
    *,
    from_email: Optional[str] = None,
    from_name: str = "VitalIO",
    text_part: Optional[str] = None,
    inline_attachments: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Send a transactional HTML email through Mailjet Send API v3.1."""
    if not is_mailjet_configured():
        raise ValueError(
            "Mailjet non configuré: SMTP_USER (API Key), SMTP_PASSWORD (Secret Key) "
            "et EMAIL_FROM sont requis"
        )

    sender = (from_email or EMAIL_FROM or "").strip()
    recipient = (to_email or "").strip()
    if not sender or not recipient:
        raise ValueError("Expéditeur ou destinataire email manquant")

    message: Dict[str, Any] = {
        "From": {"Email": sender, "Name": from_name},
        "To": [{"Email": recipient}],
        "Subject": subject,
        "TextPart": text_part if text_part is not None else _html_to_text(html_body),
        "HTMLPart": html_body,
    }
    if inline_attachments:
        message["InlinedAttachments"] = inline_attachments

    logger.info("Envoi email Mailjet API v3.1 vers %s", recipient)
    try:
        resp = requests.post(
            MAILJET_SEND_URL,
            json={"Messages": [message]},
            auth=(SMTP_USER, SMTP_PASSWORD),
            timeout=MAILJET_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.exception("Erreur requête Mailjet API: %s", exc)
        raise ValueError(f"Impossible de contacter Mailjet: {exc}") from exc

    if resp.status_code >= 400:
        detail = _format_mailjet_error(resp)
        logger.error("Mailjet API error %s: %s", resp.status_code, detail)
        raise ValueError(f"Erreur Mailjet API ({resp.status_code}): {detail}")

    try:
        data = resp.json()
        if isinstance(data, dict):
            _raise_if_message_errors(data)
    except ValueError:
        raise
    except Exception as exc:
        logger.warning("Réponse Mailjet non analysée: %s", exc)

    logger.info("Email envoyé avec succès vers %s via Mailjet API v3.1", recipient)
