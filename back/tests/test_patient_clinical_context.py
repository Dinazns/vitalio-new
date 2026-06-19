"""Tests for patient clinical context enrichment in ML narratives."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.helpers.patient_clinical_context import (
    build_patient_clinical_context,
    enrich_narrative_summary,
    extract_conditions_from_history,
)
from app.api.helpers.weekly_analysis import (
    build_clinical_weekly_narrative,
    build_lay_patient_weekly_summary,
    build_lay_caregiver_weekly_summary,
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


def _bpco_analysis():
    return {
        "status": "ok",
        "n_measurements": 20,
        "time_span_hours": 72,
        "vitals": {
            "heart_rate": _vital_stats("heart_rate", 70, 95, 80, "bpm"),
            "spo2": _vital_stats("spo2", 88, 91, 89, "%"),
            "temperature": _vital_stats("temperature", 36.5, 37.0, 36.8, "°C"),
        },
        "timeline": [],
        "correlations": {},
    }


class TestPatientClinicalContext(unittest.TestCase):
    def test_extract_conditions_from_history(self):
        conditions = extract_conditions_from_history(
            "Hypertension traitée, BPCO modérée, anticoagulant Eliquis",
            pathology="Insuffisance cardiaque",
        )
        keys = {c["key"] for c in conditions}
        self.assertIn("hypertension", keys)
        self.assertIn("bpco", keys)
        self.assertIn("anticoagulation", keys)
        self.assertIn("icc", keys)

    def test_clinical_narrative_includes_context_and_cross_insights(self):
        analysis = _bpco_analysis()
        ctx = build_patient_clinical_context(
            {"medical_history": "BPCO modérée sous bronchodilatateurs"},
            [{"message": "Surveiller l'essoufflement", "status": "follow_up"}],
        )
        max_sev = weekly_summary_max_severity(analysis)
        result = build_clinical_weekly_narrative(analysis, max_sev, clinical_context=ctx)
        self.assertTrue(result.get("context_enriched"))
        self.assertIn("BPCO", result["text"])
        self.assertIn("Contexte patient", result["text"])
        self.assertIn("SpO", result["text"])

    def test_patient_summary_uses_accessible_tone(self):
        analysis = _bpco_analysis()
        ctx = build_patient_clinical_context(
            {"medical_history": "BPCO"},
            [{"message": "Continuez vos inhalateurs matin et soir", "recommendation": "Appeler si essoufflement"}],
        )
        max_sev = weekly_summary_max_severity(analysis)
        result = build_lay_patient_weekly_summary(analysis, max_sev, clinical_context=ctx)
        self.assertIn("Votre médecin", result["text"])
        self.assertIn("dossier", result["text"].lower())
        self.assertIn("Rappel du suivi médical", result.get("recommended_action", ""))

    def test_caregiver_summary_uses_third_person(self):
        analysis = _bpco_analysis()
        ctx = build_patient_clinical_context({"medical_history": "BPCO"}, [])
        max_sev = weekly_summary_max_severity(analysis)
        result = build_lay_caregiver_weekly_summary(analysis, max_sev, clinical_context=ctx)
        self.assertIn("proche", result["text"].lower())
        self.assertNotIn("Votre pouls", result["text"])

    def test_enrich_without_context_is_noop(self):
        base = {"text": "Mesures stables.", "risk_level": "minimal", "recommended_action": "RAS"}
        out = enrich_narrative_summary(base, _bpco_analysis(), None, audience="clinical")
        self.assertEqual(out["text"], base["text"])

    def test_doctor_comment_adds_new_pathology(self):
        analysis = _bpco_analysis()
        ctx = build_patient_clinical_context(
            {"medical_history": "Hypertension"},
            [{
                "message": "Diagnostic récent d'insuffisance cardiaque, surveiller la prise de poids",
                "created_at": "2026-06-17T10:00:00+00:00",
                "status": "follow_up",
            }],
        )
        self.assertIn("icc", {c["key"] for c in ctx["conditions"]})
        self.assertIn("insuffisance cardiaque", ctx["doctor_only_labels"])
        max_sev = weekly_summary_max_severity(analysis)
        result = build_clinical_weekly_narrative(analysis, max_sev, clinical_context=ctx)
        self.assertTrue(result.get("context_recently_updated"))
        self.assertIn("insuffisance cardiaque", result["text"].lower())
        self.assertIn("médecin", result["text"].lower())

    def test_patient_profile_update_reflected_in_summary(self):
        analysis = {
            "status": "ok",
            "n_measurements": 15,
            "time_span_hours": 120,
            "vitals": {
                "heart_rate": _vital_stats("heart_rate", 62, 88, 74, "bpm"),
                "spo2": _vital_stats("spo2", 95, 99, 97, "%"),
                "temperature": _vital_stats("temperature", 36.2, 37.1, 36.7, "°C"),
            },
            "timeline": [],
            "correlations": {},
        }
        ctx = build_patient_clinical_context(
            {
                "medical_history": "Diabète type 2, metformine",
                "updated_at": "2026-06-17T08:00:00+00:00",
            },
            [],
        )
        self.assertTrue(ctx["profile_recently_updated"])
        self.assertIn("diabete", {c["key"] for c in ctx["conditions"]})
        result = build_lay_patient_weekly_summary(
            analysis, weekly_summary_max_severity(analysis), clinical_context=ctx,
        )
        self.assertIn("mis à jour", result["text"].lower())
        self.assertIn("diabète", result["text"].lower())


if __name__ == "__main__":
    unittest.main()
