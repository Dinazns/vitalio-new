"""
Debounce ML retrain jobs (threshold alerts, new measurements). Bursts coalesce into one run.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_pending_timer: Optional[threading.Timer] = None
_last_retrain_epoch = 0.0
# (trigger, trigger_device_id, trigger_metric) - snapshot at timer fire
_pending_ctx: Optional[Tuple[str, Optional[str], Optional[str]]] = None

# Minimum wall time between retrains (seconds)
MIN_INTERVAL_S = 180
# Delay before running retrain after last schedule call (coalesce burst)
DEBOUNCE_DELAY_S = 90


def _timer_fire() -> None:
    global _last_retrain_epoch, _pending_timer, _pending_ctx
    with _lock:
        _pending_timer = None
        ctx = _pending_ctx
        _pending_ctx = None
    if not ctx:
        return
    trigger, dev_id, metric = ctx
    with _lock:
        now = time.time()
        if now - _last_retrain_epoch < MIN_INTERVAL_S:
            logger.info(
                "ML retrain skipped (min interval): trigger=%s device=%s metric=%s",
                trigger,
                dev_id,
                metric,
            )
            return
        _last_retrain_epoch = now
    try:
        from services.ml_retrain_runner import do_ml_retrain

        meta = do_ml_retrain(
            days=30,
            contamination=0.05,
            n_estimators=150,
            trigger=trigger,
            trigger_device_id=dev_id,
            trigger_metric=metric,
        )
        logger.info(
            "ML retrain OK: version=%s n_samples=%s trigger=%s device=%s",
            meta.get("version"),
            meta.get("n_samples"),
            trigger,
            dev_id,
        )
    except Exception as e:
        logger.warning("ML retrain failed (trigger=%s): %s", trigger, e)


def _schedule_debounced(
    trigger: str,
    device_id: Optional[str] = None,
    metric: Optional[str] = None,
) -> None:
    global _pending_timer, _pending_ctx
    with _lock:
        _pending_ctx = (trigger, device_id, metric)
        if _pending_timer is not None:
            _pending_timer.cancel()
        _pending_timer = threading.Timer(DEBOUNCE_DELAY_S, _timer_fire)
        _pending_timer.daemon = True
        _pending_timer.start()


def schedule_retrain_after_threshold_breach(device_id: str, metric: str) -> None:
    """Schedule a background retrain after a threshold breach; coalesces with other triggers."""
    _schedule_debounced("threshold_breach", device_id, metric)


def schedule_retrain_after_new_measurement(device_id: str) -> None:
    """Schedule a background retrain after a new VALID measurement (API or MQTT)."""
    _schedule_debounced("new_measurement", device_id, None)
