"""
Tests for FP/TP separation: rejected → IF inliers only; validated → TP exemplar bank + inference boost.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ml_module


class TestMLFeedbackSplit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = [
            {
                "heart_rate": 72 + i,
                "spo2": 97 + (i % 3),
                "temperature": 36.5 + i * 0.05,
                "signal_quality": 85 + i,
                "status": "VALID",
            }
            for i in range(25)
        ]
        feedback = [
            {
                "status": "rejected",
                "user_id_auth": "pat-a",
                "measurement": base[0],
            },
            {
                "status": "validated",
                "user_id_auth": "pat-a",
                "measurement": {
                    "heart_rate": 200,
                    "spo2": 75,
                    "temperature": 40.0,
                    "signal_quality": 40,
                    "status": "VALID",
                },
            },
        ]
        ml_module.train_model(
            base,
            validated_anomalies=feedback,
            contamination=0.05,
            n_estimators=50,
        )

    def test_score_includes_if_base_and_tp_fields(self):
        m = {
            "heart_rate": 72,
            "spo2": 98,
            "temperature": 36.6,
            "signal_quality": 90,
            "status": "VALID",
            "user_id_auth": "pat-a",
        }
        r = ml_module.score_measurement(m)
        self.assertFalse(r.get("ml_skipped"))
        self.assertIn("ml_if_base_score", r)
        self.assertIn("ml_tp_exemplar_boost", r)
        self.assertIsNotNone(r.get("ml_score"))

    def test_near_validated_tp_gets_higher_boost(self):
        near = {
            "heart_rate": 199,
            "spo2": 76,
            "temperature": 39.9,
            "signal_quality": 41,
            "status": "VALID",
            "user_id_auth": "pat-a",
        }
        r_near = ml_module.score_measurement(near)
        normal = {
            "heart_rate": 72,
            "spo2": 98,
            "temperature": 36.6,
            "signal_quality": 90,
            "status": "VALID",
            "user_id_auth": "pat-a",
        }
        r_norm = ml_module.score_measurement(normal)
        self.assertGreater(r_near.get("ml_tp_exemplar_boost", 0), r_norm.get("ml_tp_exemplar_boost", 0))


if __name__ == "__main__":
    unittest.main()
