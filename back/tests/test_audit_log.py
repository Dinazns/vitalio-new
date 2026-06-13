"""Tests for global security audit_log trail."""
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.audit_service import log_audit_event, query_audit_log, AUDIT_ACTIONS


class TestAuditService(unittest.TestCase):
    def test_log_audit_event_inserts_document(self):
        coll = MagicMock()
        db = MagicMock()
        db.audit_log = coll
        with patch("services.audit_service.get_identity_db", return_value=db):
            log_audit_event(
                event_type="patient_profile_read",
                actor_user_id_auth="auth0|doc1",
                actor_role="doctor",
                resource_type="patient",
                resource_id="auth0|pat1",
                action="read",
                details={"endpoint": "/api/patients/x/profile"},
            )
        coll.insert_one.assert_called_once()
        doc = coll.insert_one.call_args[0][0]
        self.assertEqual(doc["event_type"], "patient_profile_read")
        self.assertEqual(doc["action"], "read")
        self.assertEqual(doc["resource_id"], "auth0|pat1")

    def test_invalid_action_skipped(self):
        coll = MagicMock()
        db = MagicMock()
        db.audit_log = coll
        with patch("services.audit_service.get_identity_db", return_value=db):
            log_audit_event(
                event_type="x",
                actor_user_id_auth="a",
                actor_role="admin",
                resource_type="patient",
                resource_id="b",
                action="invalid_action",
            )
        coll.insert_one.assert_not_called()

    def test_query_audit_log_pagination(self):
        coll = MagicMock()
        coll.count_documents.return_value = 2
        now = datetime.now(timezone.utc)
        coll.find.return_value.sort.return_value.skip.return_value.limit.return_value = [
            {"_id": "1", "event_type": "patient_data_export", "created_at": now},
            {"_id": "2", "event_type": "device_status_changed", "created_at": now},
        ]
        db = MagicMock()
        db.audit_log = coll
        with patch("services.audit_service.get_identity_db", return_value=db):
            total, events = query_audit_log(page=1, page_size=10, event_type="patient_data_export")
        self.assertEqual(total, 2)
        self.assertEqual(len(events), 2)
        self.assertIn("id", events[0])

    def test_audit_actions_set(self):
        self.assertIn("read", AUDIT_ACTIONS)
        self.assertIn("export", AUDIT_ACTIONS)
        self.assertIn("delete", AUDIT_ACTIONS)


if __name__ == "__main__":
    unittest.main()
