"""Gunicorn configuration for VitalIO API (Render / Docker).

Use one worker by default: a single MQTT subscriber (fixed client_id) must not
be duplicated across processes. Override with WEB_CONCURRENCY only if you run
MQTT ingestion elsewhere.
"""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
preload_app = False
