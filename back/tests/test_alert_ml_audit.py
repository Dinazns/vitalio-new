"""Tests for ML validation → medical alerts audit trail."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from bson import ObjectId

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.alert_ml_audit import create_or_merge_alert_for_validated_ml, ML_METRIC, ML_OPERATOR


class TestAlertMlAudit(unittest.TestCase):
    def test_insert_new_ml_audit_alert(self):
        db = MagicMock()
        alerts = MagicMock()
        db.alerts = alerts
        alerts.find_one.side_effect = [None, None]
        new_id = ObjectId()
        ins = MagicMock(inserted_id=new_id)
        alerts.insert_one.return_value = ins

        oid = ObjectId()
        mid = ObjectId()
        doc = {
            "device_id": "dev-1",
            "user_id_auth": "auth0|p1",
            "measurement_id": mid,
            "anomaly_score": 0.91,
            "recommended_action": "Surveillance",
            "anomaly_level": "critical",
            "measured_at": None,
        }
        with patch("services.alert_ml_audit.get_medical_db", return_value=db):
            aid, mode = create_or_merge_alert_for_validated_ml(doc, oid, "auth0|doc1")

        self.assertEqual(mode, "inserted")
        self.assertEqual(aid, new_id)
        alerts.insert_one.assert_called_once()
        call_kw = alerts.insert_one.call_args[0][0]
        self.assertEqual(call_kw["metric"], ML_METRIC)
        self.assertEqual(call_kw["operator"], ML_OPERATOR)
        self.assertEqual(call_kw["alert_source"], "ml")
        self.assertEqual(call_kw["ml_anomaly_id"], oid)
        self.assertEqual(call_kw["measurement_id"], mid)
        self.assertEqual(call_kw["doctor_status"], "VALIDATED")

    def test_idempotent_existing_ml_alert(self):
        db = MagicMock()
        existing_id = ObjectId()
        db.alerts.find_one.return_value = {"_id": existing_id, "ml_anomaly_id": ObjectId()}

        oid = ObjectId()
        doc = {"device_id": "d", "user_id_auth": "u", "measurement_id": ObjectId()}
        with patch("services.alert_ml_audit.get_medical_db", return_value=db):
            aid, mode = create_or_merge_alert_for_validated_ml(doc, oid, "doc")

        self.assertEqual(mode, "existing")
        self.assertEqual(aid, existing_id)
        db.alerts.insert_one.assert_not_called()

    def test_merge_into_open_threshold_alert(self):
        db = MagicMock()
        alerts = MagicMock()
        db.alerts = alerts
        merge_id = ObjectId()
        alerts.find_one.side_effect = [
            None,
            {"_id": merge_id, "metric": "heart_rate", "device_id": "dev-1"},
        ]
        oid = ObjectId()
        mid = ObjectId()
        doc = {
            "device_id": "dev-1",
            "user_id_auth": "auth0|p1",
            "measurement_id": mid,
            "anomaly_score": 0.88,
            "recommended_action": "Test merge",
            "anomaly_level": "critical",
        }
        with patch("services.alert_ml_audit.get_medical_db", return_value=db):
            aid, mode = create_or_merge_alert_for_validated_ml(doc, oid, "auth0|doc1")

        self.assertEqual(mode, "merged")
        self.assertEqual(aid, merge_id)
        alerts.update_one.assert_called_once()
        upd = alerts.update_one.call_args[0][1]["$set"]
        self.assertEqual(upd["alert_source"], "both")
        self.assertEqual(upd["ml_anomaly_id"], oid)
        self.assertEqual(upd["doctor_status"], "VALIDATED")
        alerts.insert_one.assert_not_called()


if __name__ == "__main__":
    unittest.main()
