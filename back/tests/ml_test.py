"""
VitalIO - Module de test du moteur ML.

Permet d'injecter des mesures simulées et de vérifier :
  - la détection correcte des anomalies
  - la classification des niveaux (normal / warning / critical)
  - la stabilité du score du modèle

Utilisé par POST /api/admin/ml/test (api.py).
"""

from typing import Any, Dict, List

from app.ml.engine import get_model_info, score_measurement

NORMAL_SAMPLES: List[Dict[str, Any]] = [
    {"heart_rate": 72, "spo2": 98, "temperature": 36.6, "signal_quality": 90, "status": "VALID"},
    {"heart_rate": 80, "spo2": 97, "temperature": 37.0, "signal_quality": 85, "status": "VALID"},
    {"heart_rate": 65, "spo2": 99, "temperature": 36.8, "signal_quality": 95, "status": "VALID"},
    {"heart_rate": 75, "spo2": 96, "temperature": 36.5, "signal_quality": 88, "status": "VALID"},
]

WARNING_SAMPLES: List[Dict[str, Any]] = [
    {"heart_rate": 125, "spo2": 93, "temperature": 37.8, "signal_quality": 75, "status": "VALID"},
    {"heart_rate": 48, "spo2": 91, "temperature": 38.2, "signal_quality": 70, "status": "VALID"},
    {"heart_rate": 110, "spo2": 90, "temperature": 35.3, "signal_quality": 65, "status": "VALID"},
]

CRITICAL_SAMPLES: List[Dict[str, Any]] = [
    {"heart_rate": 180, "spo2": 82, "temperature": 40.0, "signal_quality": 60, "status": "VALID"},
    {"heart_rate": 35, "spo2": 75, "temperature": 34.5, "signal_quality": 45, "status": "VALID"},
    {"heart_rate": 200, "spo2": 78, "temperature": 41.0, "signal_quality": 40, "status": "VALID"},
]

EDGE_CASE_SAMPLES: List[Dict[str, Any]] = [
    {"heart_rate": None, "spo2": 98, "temperature": 36.6, "signal_quality": 90, "status": "VALID"},
    {"heart_rate": 72, "spo2": None, "temperature": None, "signal_quality": 90, "status": "VALID"},
    {"heart_rate": 72, "spo2": 98, "temperature": 36.6, "signal_quality": 90, "status": "INVALID"},
    {"heart_rate": 999, "spo2": -5, "temperature": 100, "signal_quality": 200, "status": "VALID"},
]


def _run_suite(samples: List[Dict[str, Any]], suite_name: str) -> List[Dict[str, Any]]:
    results = []
    for idx, sample in enumerate(samples):
        ml = score_measurement(sample)
        results.append({
            "suite": suite_name,
            "index": idx,
            "input": sample,
            "ml_score": ml["ml_score"],
            "ml_level": ml["ml_level"],
            "ml_skipped": ml["ml_skipped"],
            "ml_skip_reasons": ml["ml_skip_reasons"],
            "ml_contributing_variables": ml["ml_contributing_variables"],
        })
    return results


def run_all_tests() -> Dict[str, Any]:
    """Execute all test suites and return structured results."""
    model_info = get_model_info()
    suites = {
        "normal": NORMAL_SAMPLES,
        "warning": WARNING_SAMPLES,
        "critical": CRITICAL_SAMPLES,
        "edge_cases": EDGE_CASE_SAMPLES,
    }
    all_results: List[Dict[str, Any]] = []
    summary: Dict[str, Dict[str, int]] = {}

    for name, samples in suites.items():
        suite_results = _run_suite(samples, name)
        all_results.extend(suite_results)

        counts: Dict[str, int] = {"normal": 0, "warning": 0, "critical": 0, "skipped": 0}
        for r in suite_results:
            if r["ml_skipped"]:
                counts["skipped"] += 1
            elif r["ml_level"]:
                counts[r["ml_level"]] = counts.get(r["ml_level"], 0) + 1
        summary[name] = counts

    return {
        "model_info": model_info,
        "summary": summary,
        "results": all_results,
    }


def run_custom_test(measurements: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Score an arbitrary list of measurements provided via API."""
    model_info = get_model_info()
    results = _run_suite(measurements, "custom")
    return {
        "model_info": model_info,
        "results": results,
    }
