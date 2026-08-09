from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


@pytest.mark.asyncio
async def test_active_model_selector_validates_selected_artifact(monkeypatch):
    from app.services import model_registry

    model = SimpleNamespace(id="model-1")
    session = SimpleNamespace(execute=AsyncMock(return_value=_ScalarResult(model)))
    validated = []
    monkeypatch.setattr(
        model_registry,
        "validate_model_artifact",
        lambda selected: validated.append(selected),
    )

    selected = await model_registry.select_active_model_version(session, "MOC-ST")

    assert selected is model
    assert validated == [model]
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_active_model_selector_fails_closed_when_registry_is_missing():
    from app.services.model_registry import select_active_model_version

    session = SimpleNamespace(execute=AsyncMock(return_value=_ScalarResult(None)))

    with pytest.raises(RuntimeError, match="No active model/rubric"):
        await select_active_model_version(session, "MOC-ST")


@pytest.mark.asyncio
async def test_failed_preflight_without_model_run_is_not_reported_as_pending(monkeypatch):
    from app.routers import evaluations

    proposal = SimpleNamespace(status="error")
    monkeypatch.setattr(
        evaluations,
        "get_proposal_for_user",
        AsyncMock(return_value=proposal),
    )
    monkeypatch.setattr(
        evaluations,
        "ensure_proposal_active_scheme",
        AsyncMock(return_value=SimpleNamespace(code="MOC-ST")),
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _ScalarResult("version-1"),
                _ScalarResult(None),
            ]
        )
    )

    response = await evaluations.get_evaluation(
        "proposal-1",
        current_user=SimpleNamespace(id="user-1"),
        db=db,
    )

    assert response.status == "error"
    assert response.error_message
    assert "preflight" in response.error_message.lower()


def test_0703_installer_refreshes_and_verifies_registry():
    root = Path(__file__).resolve().parents[2]
    script = (
        root
        / "scripts"
        / "windows"
        / "apply-registry-consistency-hotfix-0.7.0.3.ps1"
    ).read_text(encoding="utf-8")

    assert "docker compose build migration backend worker frontend" in script
    assert "Run migrations and refresh reference/model registry" in script
    assert "backendHash" in script and "workerHash" in script and "migrationHash" in script
    assert "backend.scripts.verify_model_registry" in script
    assert 'health.version -eq "0.7.0.3"' in script


def test_readiness_and_worker_share_registry_selection_path():
    root = Path(__file__).resolve().parents[2]
    health = (root / "backend" / "app" / "routers" / "health.py").read_text(
        encoding="utf-8"
    )
    worker = (root / "backend" / "app" / "worker.py").read_text(
        encoding="utf-8"
    )

    assert "select_active_model_version" in health
    assert "select_active_model_version" in worker
    assert "validate_model_artifact(model_version)" not in worker
