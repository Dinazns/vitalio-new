"""
Unified alert severity taxonomy (evaluation grid):
  INFO | WARNING | CRITICAL | URGENCY

Maps VitalIO sources (thresholds, ML, manual, SAMU escalation) to one field.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_URGENCY = "URGENCY"

SEVERITY_LEVELS = (SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL, SEVERITY_URGENCY)

_SEVERITY_RANK = {
    SEVERITY_INFO: 0,
    SEVERITY_WARNING: 1,
    SEVERITY_CRITICAL: 2,
    SEVERITY_URGENCY: 3,
}


def highest_severity(*levels: Optional[str]) -> str:
    """Return the most severe level among the given values."""
    best = SEVERITY_INFO
    for level in levels:
        if not level:
            continue
        normalized = str(level).strip().upper()
        if normalized not in _SEVERITY_RANK:
            continue
        if _SEVERITY_RANK[normalized] > _SEVERITY_RANK[best]:
            best = normalized
    return best


def _has_emergency_escalation(alert: Dict[str, Any]) -> bool:
    esc = alert.get("emergency_escalations") or []
    return isinstance(esc, list) and len(esc) > 0


def resolve_alert_severity_level(alert: Dict[str, Any]) -> str:
    """
    Compute severity_level for a medical.alerts document.
    Priority: URGENCY > CRITICAL > WARNING > INFO.
    """
    if not alert:
        return SEVERITY_CRITICAL

    if str(alert.get("alert_source") or "") == "manual" or alert.get("metric") == "manual":
        return SEVERITY_URGENCY

    if _has_emergency_escalation(alert):
        return SEVERITY_URGENCY

    if str(alert.get("ml_urgency") or "").lower() == "immediate":
        return SEVERITY_URGENCY

    stored = str(alert.get("severity_level") or "").strip().upper()
    if stored in SEVERITY_LEVELS and stored == SEVERITY_URGENCY:
        return SEVERITY_URGENCY

    source = str(alert.get("alert_source") or "")
    if source == "near_threshold":
        return SEVERITY_WARNING

    ml_sev = str(alert.get("ml_severity") or alert.get("anomaly_level") or "").lower()
    if ml_sev == "warning":
        return SEVERITY_WARNING
    if ml_sev in ("critical", "threshold"):
        return SEVERITY_CRITICAL

    if source == "threshold" or (source == "both" and alert.get("metric") not in ("ml_anomaly", "manual")):
        return SEVERITY_CRITICAL

    if source == "ml":
        return SEVERITY_WARNING if ml_sev == "warning" else SEVERITY_CRITICAL

    if stored in SEVERITY_LEVELS:
        return stored

    operator = str(alert.get("operator") or "")
    if operator.startswith("near_"):
        return SEVERITY_WARNING

    return SEVERITY_CRITICAL


def severity_for_threshold_breach() -> str:
    return SEVERITY_CRITICAL


def severity_for_manual_alert() -> str:
    return SEVERITY_URGENCY


def severity_for_near_threshold() -> str:
    return SEVERITY_WARNING


def severity_for_ml_level(ml_level: Optional[str]) -> Optional[str]:
    """Map ML score level to severity. Returns None if no alert should be created."""
    level = str(ml_level or "").lower()
    if level == "critical":
        return SEVERITY_CRITICAL
    if level == "warning":
        return SEVERITY_WARNING
    return None


def severity_for_ml_anomaly_level(anomaly_level: Optional[str]) -> str:
    level = str(anomaly_level or "").lower()
    if level == "warning":
        return SEVERITY_WARNING
    if level == "threshold":
        return SEVERITY_CRITICAL
    return SEVERITY_CRITICAL


def resolve_measurement_display_level(
    ml_level: Optional[str],
    *,
    near_threshold: bool = False,
    drift_warning: bool = False,
) -> str:
    """Display severity for patient timeline (no DB alert required for INFO)."""
    if near_threshold or drift_warning:
        return highest_severity(SEVERITY_WARNING, severity_for_ml_level(ml_level))
    mapped = severity_for_ml_level(ml_level)
    if mapped:
        return mapped
    return SEVERITY_INFO


def enrich_alert_with_severity(alert: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure alert dict exposes canonical severity_level."""
    out = dict(alert)
    out["severity_level"] = resolve_alert_severity_level(out)
    return out


def map_analysis_severity_to_grid(severity: Optional[str]) -> str:
    """Map ml_module analysis point severity (normal/warning/critical) to grid levels."""
    s = str(severity or "normal").lower()
    if s == "critical":
        return SEVERITY_CRITICAL
    if s == "warning":
        return SEVERITY_WARNING
    return SEVERITY_INFO
