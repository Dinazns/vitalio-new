"""Tests for clinical weekly narrative generation."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.helpers.weekly_analysis import (
    build_clinical_weekly_narrative,
    _collect_clinical_findings,
    weekly_summary_max_severity,
)


def _vital_stats(feat, mn, mx, mean, unit):
    return {
        "status": "ok",
        "unit": unit,
        "statistics": {"min": mn, "max": mx, "mean": mean, "median": mean, "std": 1.0},
        "trend": {"label": "stable", "strength": "negligible", "significant": False},
        "series": [{"value": mx}],
        "clinical_alerts": [],
        "n_anomalies": 0,
    }


class TestClinicalWeeklyNarrative(unittest.TestCase):
    def test_stable_profile_is_concise(self):
        analysis = {
            "status": "ok",
            "n_measurements": 30,
            "time_span_hours": 168,
            "vitals": {
                "heart_rate": _vital_stats("heart_rate", 62, 88, 74, "bpm"),
                "spo2": _vital_stats("spo2", 95, 99, 97, "%"),
                "temperature": _vital_stats("temperature", 36.2, 37.1, 36.7, "°C"),
            },
            "timeline": [],
            "correlations": {},
        }
        max_sev = weekly_summary_max_severity(analysis)
        result = build_clinical_weekly_narrative(analysis, max_sev)
        self.assertIn("stable", result["text"].lower())
        self.assertLess(len(result["text"]), 400)
        self.assertEqual(result["risk_level"], "minimal")

    def test_detects_hypoxemia_and_urgent_recommendation(self):
        analysis = {
            "status": "ok",
            "n_measurements": 20,
            "time_span_hours": 72,
            "vitals": {
                "heart_rate": _vital_stats("heart_rate", 70, 95, 80, "bpm"),
                "spo2": _vital_stats("spo2", 84, 91, 88, "%"),
                "temperature": _vital_stats("temperature", 36.5, 37.0, 36.8, "°C"),
            },
            "timeline": [],
            "correlations": {},
        }
        findings = _collect_clinical_findings(analysis)
        self.assertTrue(any("hypox" in f["headline"].lower() for f in findings))
        max_sev = weekly_summary_max_severity(analysis)
        result = build_clinical_weekly_narrative(analysis, max_sev)
        self.assertIn("urgence", result["text"].lower())
        self.assertIn("15", result["recommended_action"])

    def test_detects_tachycardia(self):
        analysis = {
            "status": "ok",
            "n_measurements": 15,
            "time_span_hours": 48,
            "vitals": {
                "heart_rate": _vital_stats("heart_rate", 80, 155, 110, "bpm"),
                "spo2": _vital_stats("spo2", 96, 99, 97, "%"),
                "temperature": _vital_stats("temperature", 36.5, 37.2, 36.9, "°C"),
            },
            "timeline": [],
            "correlations": {},
        }
        result = build_clinical_weekly_narrative(analysis, 2)
        self.assertIn("tachycardie", result["text"].lower())
        self.assertIn("cardiaque", result["recommended_action"].lower())


if __name__ == "__main__":
    unittest.main()
