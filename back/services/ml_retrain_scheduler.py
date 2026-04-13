"""
Debounce ML retrain jobs after threshold alerts (many measurements can arrive in bursts).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_pending_timer: Optional[threading.Timer] = None
_last_retrain_epoch = 0.0

# Minimum wall time between retrains triggered by thresholds (seconds)
MIN_INTERVAL_S = 180
# Delay before running retrain after last breach notification (coalesce burst)
DEBOUNCE_DELAY_S = 90


def schedule_retrain_after_threshold_breach(device_id: str, metric: str) -> None:
    """Schedule a background retrain; coalesces rapid calls and enforces MIN_INTERVAL_S."""

    def _run() -> None:
        global _last_retrain_epoch, _pending_timer
        with _lock:
            _pending_timer = None
            now = time.time()
            if now - _last_retrain_epoch < MIN_INTERVAL_S:
                logger.info("ML retrain skipped (min interval): device=%s metric=%s", device_id, metric)
                return
            _last_retrain_epoch = now
        try:
            from services.ml_retrain_runner import do_ml_retrain
            meta = do_ml_retrain(
                days=30,
                contamination=0.05,
                n_estimators=150,
                trigger="threshold_breach",
                trigger_device_id=device_id,
                trigger_metric=metric,
            )
            logger.info(
                "ML retrain after threshold breach OK: version=%s n_samples=%s device=%s",
                meta.get("version"),
                meta.get("n_samples"),
                device_id,
            )
        except Exception as e:
            logger.warning("ML retrain after threshold breach failed: %s", e)

    global _pending_timer
    with _lock:
        if _pending_timer is not None:
            _pending_timer.cancel()
        _pending_timer = threading.Timer(DEBOUNCE_DELAY_S, _run)
        _pending_timer.daemon = True
        _pending_timer.start()
