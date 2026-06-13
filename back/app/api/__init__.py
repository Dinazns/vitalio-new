"""Register Flask blueprints."""
from app.api.auth import auth_bp
from app.api.patients import patient_bp
from app.api.doctors import doctor_bp
from app.api.alerts import alert_bp
from app.api.ml import ml_bp
from app.api.admin import admin_bp
from app.api.devices import device_bp

ALL_BLUEPRINTS = (
    auth_bp,
    patient_bp,
    doctor_bp,
    alert_bp,
    ml_bp,
    admin_bp,
    device_bp,
)


def register_blueprints(app):
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)
