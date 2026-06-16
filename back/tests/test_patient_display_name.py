"""Tests for patient display name resolution (no Auth0 ids in UI)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.user_service import resolve_patient_display_name, normalize_patient_email


class TestPatientDisplayName(unittest.TestCase):
    def test_prefers_full_name(self):
        profile = {
            "first_name": "Jean",
            "last_name": "Dupont",
            "email": "jean@example.com",
            "display_name": "auth0|abc123",
        }
        self.assertEqual(resolve_patient_display_name(profile), "Jean Dupont")

    def test_falls_back_to_email_when_name_missing(self):
        profile = {"email": "patient@example.com", "display_name": "auth0|abc123"}
        self.assertEqual(resolve_patient_display_name(profile), "patient@example.com")

    def test_uses_safe_display_name(self):
        profile = {"email": "patient@example.com", "display_name": "Marie Martin"}
        self.assertEqual(resolve_patient_display_name(profile), "Marie Martin")

    def test_ignores_auth_id_in_first_name(self):
        profile = {
            "first_name": "auth0|abc123",
            "last_name": "",
            "email": "patient@example.com",
        }
        self.assertEqual(resolve_patient_display_name(profile), "patient@example.com")

        self.assertIsNone(resolve_patient_display_name({"display_name": "auth0|abc123"}))
        self.assertIsNone(resolve_patient_display_name(None))
        self.assertIsNone(normalize_patient_email({"email": ""}))


if __name__ == "__main__":
    unittest.main()
