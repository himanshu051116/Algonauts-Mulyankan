"""Import and mapper smoke tests for the authoritative backend."""

import importlib


def test_app_main_imports():
    module = importlib.import_module("app.main")

    assert module.app.title == "Mulyankan Backend API"


def test_app_worker_imports():
    module = importlib.import_module("app.worker")

    assert module.WorkerSettings.functions


def test_sqlalchemy_mappers_configure():
    from sqlalchemy.orm import configure_mappers

    importlib.import_module("app.models.proposal")
    importlib.import_module("app.models.user")

    configure_mappers()


def test_user_role_enum_persists_values():
    from app.models.user import User, UserRole

    assert User.__table__.c.role.type.enums == [role.value for role in UserRole]
