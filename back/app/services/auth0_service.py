"""
Auth0 Management API - create users when sending invitations.
Requires AUTH0_M2M_CLIENT_ID and AUTH0_M2M_CLIENT_SECRET (Machine-to-Machine app)
with scopes: create:users read:users create:user_tickets
"""
import logging
import secrets
from typing import Optional, Tuple

import requests

from app.config import (
    AUTH0_DOMAIN, AUTH0_M2M_CLIENT_ID, AUTH0_M2M_CLIENT_SECRET,
    FRONTEND_URL,
)

logger = logging.getLogger(__name__)

AUTH0_CONNECTION = "Username-Password-Authentication"


def _get_management_token() -> Optional[str]:
    """Get access token for Auth0 Management API via client credentials."""
    if not AUTH0_DOMAIN or not AUTH0_M2M_CLIENT_ID or not AUTH0_M2M_CLIENT_SECRET:
        return None
    url = f"https://{AUTH0_DOMAIN}/oauth/token"
    payload = {
        "client_id": AUTH0_M2M_CLIENT_ID,
        "client_secret": AUTH0_M2M_CLIENT_SECRET,
        "audience": f"https://{AUTH0_DOMAIN}/api/v2/",
        "grant_type": "client_credentials",
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception as e:
        logger.warning("Auth0 Management token fetch failed: %s", e)
        return None


def _user_exists_by_email(email: str, token: str) -> Optional[str]:
    """Check if user exists in Auth0 by email. Returns user_id if found."""
    url = f"https://{AUTH0_DOMAIN}/api/v2/users-by-email"
    try:
        resp = requests.get(url, params={"email": email}, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if resp.status_code != 200:
            return None
        users = resp.json()
        if users and len(users) > 0:
            return users[0].get("user_id")
    except Exception as e:
        logger.warning("Auth0 user lookup by email failed: %s", e)
    return None


def create_auth0_user_if_not_exists(
    email: str,
    name: Optional[str] = None,
    invite_return_url: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Create user in Auth0 if they don't exist.
    Returns (created, user_id_or_ticket_url).
    If user was created, optionally create password change ticket and return that URL.
    """
    token = _get_management_token()
    if not token:
        logger.info("Auth0 Management API not configured - skip user creation")
        return (False, None)

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Check if user exists
    existing_id = _user_exists_by_email(email, token)
    if existing_id:
        logger.info("Auth0 user already exists for %s", email)
        return (False, existing_id)

    # Create user with random password (they'll use password reset)
    temp_password = secrets.token_urlsafe(24)
    create_url = f"https://{AUTH0_DOMAIN}/api/v2/users"
    create_payload = {
        "connection": AUTH0_CONNECTION,
        "email": email.lower().strip(),
        "email_verified": True,
        "password": temp_password,
        "name": (name or email).strip()[:128],
    }
    try:
        resp = requests.post(create_url, json=create_payload, headers=headers, timeout=10)
        resp.raise_for_status()
        user_data = resp.json()
        user_id = user_data.get("user_id")
        logger.info("Auth0 user created for %s (user_id=%s)", email, user_id)

        # Create password change ticket so they can set their password
        if invite_return_url:
            ticket_url = _create_password_change_ticket(token, user_id, invite_return_url)
            if ticket_url:
                return (True, ticket_url)
        return (True, None)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 409:
            logger.info("Auth0 user already exists (409) for %s", email)
            return (False, None)
        logger.warning("Auth0 create user failed for %s: %s", email, e)
    except Exception as e:
        logger.warning("Auth0 create user failed for %s: %s", email, e)
    return (False, None)


def _create_password_change_ticket(token: str, user_id: str, result_url: str) -> Optional[str]:
    """Create Auth0 password change ticket, return the ticket URL."""
    url = f"https://{AUTH0_DOMAIN}/api/v2/tickets/password-change"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"user_id": user_id, "result_url": result_url}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json().get("ticket")
    except Exception as e:
        logger.warning("Auth0 password change ticket failed: %s", e)
    return None
