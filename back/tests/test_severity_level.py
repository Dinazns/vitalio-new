"""Tests for unified alert severity_level mapping."""
import unittest

from app.services.severity_level import (
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_URGENCY,
    SEVERITY_WARNING,
    enrich_alert_with_severity,
    highest_severity,
    resolve_alert_severity_level,
    resolve_measurement_display_level,
    severity_for_ml_level,
)


class TestSeverityLevel(unittest.TestCase):
    def test_manual_alert_is_urgency(self):
        self.assertEqual(
            resolve_alert_severity_level({"alert_source": "manual", "metric": "manual"}),
            SEVERITY_URGENCY,
        )

    def test_threshold_breach_is_critical(self):
        self.assertEqual(
            resolve_alert_severity_level({"alert_source": "threshold", "metric": "spo2"}),
            SEVERITY_CRITICAL,
        )

    def test_near_threshold_is_warning(self):
        self.assertEqual(
            resolve_alert_severity_level({"alert_source": "near_threshold", "metric": "spo2"}),
            SEVERITY_WARNING,
        )

    def test_samu_escalation_is_urgency(self):
        self.assertEqual(
            resolve_alert_severity_level({
                "alert_source": "threshold",
                "metric": "spo2",
                "emergency_escalations": [{"type": "samu"}],
            }),
            SEVERITY_URGENCY,
        )

    def test_ml_warning_is_warning(self):
        self.assertEqual(
            resolve_alert_severity_level({"alert_source": "ml", "ml_severity": "warning"}),
            SEVERITY_WARNING,
        )

    def test_ml_immediate_urgency(self):
        self.assertEqual(
            resolve_alert_severity_level({"alert_source": "ml", "ml_urgency": "immediate"}),
            SEVERITY_URGENCY,
        )

    def test_highest_severity(self):
        self.assertEqual(highest_severity(SEVERITY_INFO, SEVERITY_CRITICAL), SEVERITY_CRITICAL)
        self.assertEqual(highest_severity(SEVERITY_WARNING, SEVERITY_URGENCY), SEVERITY_URGENCY)

    def test_measurement_display_normal_is_info(self):
        self.assertEqual(resolve_measurement_display_level("normal"), SEVERITY_INFO)

    def test_measurement_display_warning(self):
        self.assertEqual(resolve_measurement_display_level("warning"), SEVERITY_WARNING)

    def test_measurement_display_near_threshold(self):
        self.assertEqual(
            resolve_measurement_display_level("normal", near_threshold=True),
            SEVERITY_WARNING,
        )

    def test_ml_level_mapping(self):
        self.assertEqual(severity_for_ml_level("critical"), SEVERITY_CRITICAL)
        self.assertEqual(severity_for_ml_level("warning"), SEVERITY_WARNING)
        self.assertIsNone(severity_for_ml_level("normal"))

    def test_enrich_alert(self):
        doc = enrich_alert_with_severity({"alert_source": "manual", "metric": "manual"})
        self.assertEqual(doc["severity_level"], SEVERITY_URGENCY)


if __name__ == "__main__":
    unittest.main()
