"""Shared audit helpers for route handlers."""
from app.auth import get_current_user_role
from flask import g


def audit_actor_role() -> str:
    return str(getattr(g, "current_role", None) or get_current_user_role() or "unknown")
