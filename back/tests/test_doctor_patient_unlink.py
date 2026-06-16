"""Tests for doctor-patient unlink service."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.invitation_service import remove_doctor_patient_link


class TestDoctorPatientUnlink(unittest.TestCase):
    def test_remove_doctor_patient_link_success(self):
        coll = MagicMock()
        coll.delete_one.return_value = MagicMock(deleted_count=1)
        db = MagicMock()
        db.doctor_patients = coll
        with patch("app.services.invitation_service.get_identity_db", return_value=db):
            removed = remove_doctor_patient_link("auth0|doctor", "auth0|patient")
        self.assertTrue(removed)
        coll.delete_one.assert_called_once_with({
            "doctor_user_id_auth": "auth0|doctor",
            "patient_user_id_auth": "auth0|patient",
        })

    def test_remove_doctor_patient_link_not_found(self):
        coll = MagicMock()
        coll.delete_one.return_value = MagicMock(deleted_count=0)
        db = MagicMock()
        db.doctor_patients = coll
        with patch("app.services.invitation_service.get_identity_db", return_value=db):
            removed = remove_doctor_patient_link("auth0|doctor", "auth0|patient")
        self.assertFalse(removed)


if __name__ == "__main__":
    unittest.main()
