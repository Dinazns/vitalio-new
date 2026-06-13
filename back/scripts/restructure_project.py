#!/usr/bin/env python3
"""One-shot restructure: back/ -> back/app/ package layout."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

BACK = Path(__file__).resolve().parent.parent
ROOT = BACK.parent

ROUTE_RENAMES = {
    "auth_routes.py": "auth.py",
    "patient_routes.py": "patients.py",
    "doctor_routes.py": "doctors.py",
    "alert_routes.py": "alerts.py",
    "ml_routes.py": "ml.py",
    "admin_routes.py": "admin.py",
    "device_routes.py": "devices.py",
}

SCRIPT_MOVES = {
    "data.py": "simulate_sensor.py",
    "simulate_alert.py": "simulate_alert.py",
    "seed_db.py": "seed_db.py",
    "seed_relations_feedback.py": "seed_relations_feedback.py",
    "migrate_profiles.py": "migrate_profiles.py",
}

DOC_MOVES = [
    (BACK / "ASSOCIATION_E2E_TEST_PLAN.md", ROOT / "docs" / "association-e2e-test-plan.md"),
    (BACK / "ASSOCIATION_MIGRATION_NOTES.md", ROOT / "docs" / "association-migration-notes.md"),
    (BACK / "RELATIONS_ACCESS_TEST_PLAN.md", ROOT / "docs" / "relations-access-test-plan.md"),
    (ROOT / "front" / "vitalio" / "AUTH0_SETUP.md", ROOT / "docs" / "auth0.md"),
    (BACK / "mosquitto" / "QUICK_START.md", ROOT / "docs" / "mqtt-quick-start.md"),
    (BACK / "mosquitto" / "CONFIGURATION_TLS_RESUME.md", ROOT / "docs" / "mqtt-tls.md"),
    (BACK / "mosquitto" / "VERIFICATION_TLS.md", ROOT / "docs" / "mqtt-verification-tls.md"),
]


def ensure_dirs() -> None:
    for rel in (
        "app/api/helpers",
        "app/services",
        "app/ml",
        "app/models",
        "auth0",
        "scripts",
    ):
        (BACK / rel).mkdir(parents=True, exist_ok=True)
    (ROOT / "docs").mkdir(parents=True, exist_ok=True)


def move_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    shutil.move(str(src), str(dst))
    print(f"  moved {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")


def move_core_modules() -> None:
    mapping = {
        "config.py": "app/config.py",
        "database.py": "app/database.py",
        "api_auth.py": "app/auth.py",
        "exceptions.py": "app/exceptions.py",
        "mqtt_handler.py": "app/mqtt_handler.py",
        "ml_module.py": "app/ml/engine.py",
    }
    for src_name, dst_rel in mapping.items():
        move_if_exists(BACK / src_name, BACK / dst_rel)


def move_services() -> None:
    src_dir = BACK / "services"
    if not src_dir.exists():
        return
    for f in src_dir.iterdir():
        if f.is_file():
            move_if_exists(f, BACK / "app" / "services" / f.name)
    if src_dir.exists() and not any(src_dir.iterdir()):
        src_dir.rmdir()


def move_routes() -> None:
    routes_dir = BACK / "routes"
    if not routes_dir.exists():
        return
    helpers = routes_dir / "helpers"
    if helpers.exists():
        for f in helpers.iterdir():
            if f.is_file():
                move_if_exists(f, BACK / "app" / "api" / "helpers" / f.name)
        if helpers.exists() and not any(helpers.iterdir()):
            helpers.rmdir()
    init = routes_dir / "__init__.py"
    if init.exists():
        move_if_exists(init, BACK / "app" / "api" / "__init__.py")
    for old_name, new_name in ROUTE_RENAMES.items():
        move_if_exists(routes_dir / old_name, BACK / "app" / "api" / new_name)
    if routes_dir.exists():
        shutil.rmtree(routes_dir, ignore_errors=True)


def move_scripts() -> None:
    scripts = BACK / "scripts"
    for src_name, dst_name in SCRIPT_MOVES.items():
        move_if_exists(BACK / src_name, scripts / dst_name)


def move_docs_and_auth0() -> None:
    move_if_exists(BACK / "auth0_action_post_login.js", BACK / "auth0" / "post_login_action.js")
    for src, dst in DOC_MOVES:
        move_if_exists(src, dst)


def write_package_inits() -> None:
    (BACK / "app" / "__init__.py").write_text(
        '"""VitalIO backend application package."""\n',
        encoding="utf-8",
    )
    (BACK / "app" / "ml" / "__init__.py").write_text(
        '"""ML engine (anomaly detection, forecasting)."""\n'
        "from app.ml.engine import *  # noqa: F403\n",
        encoding="utf-8",
    )
    (BACK / "app" / "models" / "__init__.py").write_text(
        '"""Domain constants and document shapes (MongoDB collections)."""\n'
        "from app.models.collections import IDENTITY_DB, MEDICAL_DB\n",
        encoding="utf-8",
    )
    collections = BACK / "app" / "models" / "collections.py"
    if not collections.exists():
        collections.write_text(
            '"""MongoDB database and collection names."""\n'
            "from app.config import MONGODB_IDENTITY_DB, MONGODB_MEDICAL_DB\n\n"
            "IDENTITY_DB = MONGODB_IDENTITY_DB\n"
            "MEDICAL_DB = MONGODB_MEDICAL_DB\n",
            encoding="utf-8",
        )


def fix_api_init() -> None:
    init_path = BACK / "app" / "api" / "__init__.py"
    if not init_path.exists():
        return
    text = init_path.read_text(encoding="utf-8")
    replacements = {
        "from routes.auth_routes import auth_bp": "from app.api.auth import auth_bp",
        "from routes.patient_routes import patient_bp": "from app.api.patients import patient_bp",
        "from routes.doctor_routes import doctor_bp": "from app.api.doctors import doctor_bp",
        "from routes.alert_routes import alert_bp": "from app.api.alerts import alert_bp",
        "from routes.ml_routes import ml_bp": "from app.api.ml import ml_bp",
        "from routes.admin_routes import admin_bp": "from app.api.admin import admin_bp",
        "from routes.device_routes import device_bp": "from app.api.devices import device_bp",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    init_path.write_text(text, encoding="utf-8")


def rewrite_imports_in_file(path: Path) -> bool:
    if ".venv" in path.parts or "mosquitto" in path.parts and "scripts" not in path.parts:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    original = text

    # Order matters: longer prefixes first
    subs = [
        (r"\bfrom routes\.helpers\.", "from app.api.helpers."),
        (r"\bfrom routes\.", "from app.api."),
        (r"\bfrom routes import", "from app.api import"),
        (r"\bfrom services\.", "from app.services."),
        (r"\bfrom api_auth import", "from app.auth import"),
        (r"\bimport api_auth\b", "from app import auth as api_auth"),
        (r"\bfrom config import", "from app.config import"),
        (r"\bimport config\b", "from app import config"),
        (r"\bfrom database import", "from app.database import"),
        (r"\bfrom exceptions import", "from app.exceptions import"),
        (r"\bfrom mqtt_handler import", "from app.mqtt_handler import"),
        (r"\bimport mqtt_handler\b", "from app import mqtt_handler"),
        (r"\bimport ml_module\b", "from app.ml import engine as ml_module"),
        (r"\bfrom ml_module import", "from app.ml.engine import"),
        (r"\bfrom tests import ml_test\b", "from tests import ml_test"),
    ]
    for pattern, repl in subs:
        text = re.sub(pattern, repl, text)

    # Route module header blocks still say routes.helpers
    text = text.replace("from app.api.helpers.", "from app.api.helpers.")

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def rewrite_all_imports() -> int:
    count = 0
    for base in (BACK / "app", BACK / "tests", BACK / "scripts", BACK):
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if ".venv" in path.parts:
                continue
            if path.name == "restructure_project.py":
                continue
            if rewrite_imports_in_file(path):
                count += 1
    return count


def main() -> None:
    print("Creating directories...")
    ensure_dirs()
    print("Moving core modules...")
    move_core_modules()
    print("Moving services...")
    move_services()
    print("Moving routes -> app/api...")
    move_routes()
    print("Moving scripts...")
    move_scripts()
    print("Moving docs and auth0...")
    move_docs_and_auth0()
    print("Writing package inits...")
    write_package_inits()
    fix_api_init()
    print("Rewriting imports...")
    n = rewrite_all_imports()
    print(f"Updated imports in {n} files.")
    print("Done. Next: create app/main.py and update api.py manually if needed.")


if __name__ == "__main__":
    main()
