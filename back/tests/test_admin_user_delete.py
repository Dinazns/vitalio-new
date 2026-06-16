"""Tests for admin user deletion."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.exceptions import DatabaseError
from app.services.patient_data_portability import erase_user_all_data


class TestEraseUserAllData(unittest.TestCase):
    def test_patient_delegates_to_patient_erase(self):
        with patch(
            "app.services.patient_data_portability.erase_patient_all_data",
            return_value={"users_deleted": 1},
        ) as patient_erase:
            with patch("app.services.patient_data_portability.get_identity_db") as get_identity:
                db = MagicMock()
                get_identity.return_value = db
                db.users.find_one.return_value = {"role": "patient"}
                result = erase_user_all_data("auth0|patient-1")

        patient_erase.assert_called_once_with("auth0|patient-1")
        self.assertEqual(result["users_deleted"], 1)

    def test_doctor_deletes_links_and_profile(self):
        identity = MagicMock()
        medical = MagicMock()
        identity.users.find_one.return_value = {"role": "doctor"}
        identity.doctor_patients.delete_many.return_value.deleted_count = 2
        identity.doctor_invites.delete_many.return_value.deleted_count = 1
        medical.doctor_feedback.delete_many.return_value.deleted_count = 3
        identity.audit_links.delete_many.return_value.deleted_count = 0
        identity.push_subscriptions.delete_many.return_value.deleted_count = 1
        identity.users.delete_one.return_value.deleted_count = 1

        with patch("app.services.patient_data_portability.get_identity_db", return_value=identity):
            with patch("app.services.patient_data_portability.get_medical_db", return_value=medical):
                counts = erase_user_all_data("auth0|doctor-1")

        self.assertEqual(counts["doctor_patients"], 2)
        self.assertEqual(counts["doctor_feedback"], 3)
        self.assertEqual(counts["users_deleted"], 1)
        identity.users.delete_one.assert_called_once_with({"user_id_auth": "auth0|doctor-1"})

    def test_unknown_user_raises(self):
        identity = MagicMock()
        identity.users.find_one.return_value = None
        with patch("app.services.patient_data_portability.get_identity_db", return_value=identity):
            with self.assertRaises(DatabaseError) as ctx:
                erase_user_all_data("auth0|missing")
        self.assertEqual(ctx.exception.error["code"], "user_not_found")


if __name__ == "__main__":
    unittest.main()
