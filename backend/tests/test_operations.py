"""Operational hardening tests for scanning, readiness, throttling, and workers."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.config import settings
from app.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.services.malware import MalwareScanError, scan_file
from app.worker import worker_shutdown, worker_startup


class FakeProcess:
    def __init__(self, returncode: int, output: bytes = b"") -> None:
        self.returncode = returncode
        self.output = output
        self.killed = False

    async def communicate(self):
        return self.output, b""

    def kill(self) -> None:
        self.killed = True


@pytest.mark.asyncio
async def test_malware_scan_disabled(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "malware_scan_enabled", False)
    path = tmp_path / "proposal.pdf"
    path.write_bytes(b"%PDF-1.4")
    assert await scan_file(path) == "disabled"


@pytest.mark.asyncio
async def test_malware_scan_clean_and_infected(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "malware_scan_enabled", True)
    path = tmp_path / "proposal.pdf"
    path.write_bytes(b"%PDF-1.4")

    async def clean_process(*_args, **_kwargs):
        return FakeProcess(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", clean_process)
    assert await scan_file(path) == "clean"

    async def infected_process(*_args, **_kwargs):
        return FakeProcess(1, b"proposal.pdf: Test-Signature FOUND")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", infected_process)
    with pytest.raises(MalwareScanError, match="Malware was detected"):
        await scan_file(path)


@pytest.mark.asyncio
async def test_worker_heartbeat_lifecycle(monkeypatch):
    monkeypatch.setattr(settings, "worker_heartbeat_ttl_seconds", 30)

    class FakeRedis:
        def __init__(self) -> None:
            self.values = {}
            self.deleted = []

        async def set(self, key, value, ex=None):
            self.values[key] = (value, ex)

        async def delete(self, key):
            self.deleted.append(key)

    redis = FakeRedis()
    ctx = {"redis": redis}
    await worker_startup(ctx)
    assert settings.worker_heartbeat_key in redis.values
    assert isinstance(ctx["heartbeat_task"], asyncio.Task)
    await worker_shutdown(ctx)
    assert settings.worker_heartbeat_key in redis.deleted


def test_request_headers_and_local_rate_limit(monkeypatch):
    app = FastAPI()

    @app.get("/api/test")
    async def endpoint():
        return {"ok": True}

    async def redis_unavailable(self, _key):
        raise ConnectionError("Redis unavailable")

    monkeypatch.setattr(RateLimitMiddleware, "_redis_count", redis_unavailable)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RateLimitMiddleware, requests_per_minute=1)

    with TestClient(app) as client:
        first = client.get("/api/test")
        second = client.get("/api/test")

    assert first.status_code == 200
    assert first.headers["x-content-type-options"] == "nosniff"
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["x-request-id"]
    assert second.status_code == 429
    assert second.json()["code"] == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_readiness_status_reflects_critical_checks(monkeypatch):
    from app.routers import health

    async def ok(*_args, **_kwargs):
        return True

    async def failed(*_args, **_kwargs):
        return False

    monkeypatch.setattr(health, "_check_database", ok)
    monkeypatch.setattr(health, "_check_migration", ok)
    monkeypatch.setattr(health, "_check_reference_data", ok)
    monkeypatch.setattr(health, "_check_redis", ok)
    monkeypatch.setattr(health, "check_storage_ready", failed)
    monkeypatch.setattr(health, "_check_worker_heartbeat", failed)
    monkeypatch.setattr(settings, "environment", "development")

    response = await health.readiness(SimpleNamespace())
    body = json.loads(response.body)
    assert response.status_code == 503
    assert body["status"] == "not_ready"
    assert body["checks"]["storage"]["critical"] is True
    assert body["checks"]["worker"]["critical"] is False


def test_audit_hash_chain_detects_tampering():
    from datetime import datetime, timedelta, timezone

    from app.models.proposal import AuditEvent
    from app.services.audit import GENESIS_HASH, _event_digest, verify_audit_chain

    created_1 = datetime(2026, 7, 5, 10, 0, tzinfo=timezone.utc)
    hash_1 = _event_digest(
        event_id="event-1",
        user_id="user-1",
        event_type="proposal.created",
        resource_type="proposal",
        resource_id="proposal-1",
        details={"status": "draft"},
        ip_address="127.0.0.1",
        user_agent="pytest",
        created_at=created_1,
        previous_hash=GENESIS_HASH,
    )
    event_1 = AuditEvent(
        id="event-1",
        user_id="user-1",
        event_type="proposal.created",
        resource_type="proposal",
        resource_id="proposal-1",
        details={"status": "draft"},
        ip_address="127.0.0.1",
        user_agent="pytest",
        previous_hash=GENESIS_HASH,
        event_hash=hash_1,
        created_at=created_1,
    )
    created_2 = created_1 + timedelta(seconds=1)
    hash_2 = _event_digest(
        event_id="event-2",
        user_id="user-1",
        event_type="proposal.submitted",
        resource_type="proposal",
        resource_id="proposal-1",
        details={"status": "submitted"},
        ip_address="127.0.0.1",
        user_agent="pytest",
        created_at=created_2,
        previous_hash=hash_1,
    )
    event_2 = AuditEvent(
        id="event-2",
        user_id="user-1",
        event_type="proposal.submitted",
        resource_type="proposal",
        resource_id="proposal-1",
        details={"status": "submitted"},
        ip_address="127.0.0.1",
        user_agent="pytest",
        previous_hash=hash_1,
        event_hash=hash_2,
        created_at=created_2,
    )

    assert verify_audit_chain([event_1, event_2])["valid"] is True
    event_1.details = {"status": "approved"}
    result = verify_audit_chain([event_1, event_2])
    assert result["valid"] is False
    assert result["invalid_event_id"] == "event-1"


def test_settings_normalize_origins_hosts_and_extensions():
    from app.config import Settings

    configured = Settings(
        _env_file=None,
        cors_origins=" https://one.example ,https://two.example,https://one.example ",
        allowed_hosts=" api.example,api.example , internal.example ",
        allowed_extensions=".PDF,.docx,.txt",
        metrics_enabled=False,
    )
    assert configured.cors_origin_list == [
        "https://one.example",
        "https://two.example",
    ]
    assert configured.allowed_host_list == ["api.example", "internal.example"]
    assert configured.allowed_extension_set == {".pdf", ".docx", ".txt"}


def test_production_validation_rejects_unsafe_defaults(monkeypatch):
    import app.main as main

    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setattr(main.settings, "environment", "production")
    monkeypatch.setattr(main.settings, "cors_origins", "*")
    monkeypatch.setattr(main.settings, "allowed_hosts", "*")
    monkeypatch.setattr(main.settings, "supabase_url", "")
    monkeypatch.setattr(main.settings, "supabase_jwks_url", "")
    monkeypatch.setattr(main.settings, "supabase_jwt_issuer", "")
    monkeypatch.setattr(
        main.settings, "database_url", "postgresql+asyncpg://user:password@db/mulyankan"
    )
    monkeypatch.setattr(main.settings, "storage_access_key", "minioadmin")
    monkeypatch.setattr(main.settings, "storage_secret_key", "minioadmin")
    monkeypatch.setattr(main.settings, "metrics_enabled", True)
    monkeypatch.setattr(main.settings, "metrics_token", "")

    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        main._validate_production_config()


def test_contextual_model_registry_detects_artifact_tampering():
    from app.models.proposal import ModelVersion
    from app.services.model_registry import (
        CONTEXTUAL_BASELINE_NAME,
        CONTEXTUAL_BASELINE_VERSION,
        validate_model_artifact,
    )

    model = ModelVersion(
        model_name=CONTEXTUAL_BASELINE_NAME,
        version=CONTEXTUAL_BASELINE_VERSION,
        artifact_hash="f" * 64,
        rubric_version_id="rubric-1",
        training_rows=0,
        test_metrics={"trained_model": False},
        is_active=True,
    )
    with pytest.raises(RuntimeError, match="does not match code"):
        validate_model_artifact(model)


def test_production_validation_requires_https_public_endpoints(monkeypatch):
    import app.main as main

    monkeypatch.delenv("TESTING", raising=False)
    safe_values = {
        "environment": "production",
        "cors_origins": "http://app.example",
        "allowed_hosts": "api.example",
        "auth_allow_local_jwt": False,
        "supabase_url": "http://auth.example",
        "supabase_jwks_url": "",
        "supabase_jwt_issuer": "",
        "jwt_secret": "x" * 48,
        "storage_endpoint": "http://minio:9000",
        "storage_public_endpoint": "http://files.example",
        "storage_access_key": "non-default-user",
        "storage_secret_key": "y" * 48,
        "storage_bucket": "mulyankan-proposals",
        "database_url": "postgresql+asyncpg://user:strong-secret@db/mulyankan",
        "metrics_enabled": True,
        "metrics_token": "z" * 32,
        "malware_scan_enabled": True,
        "audit_export_signing_key": "a" * 48,
    }
    for name, value in safe_values.items():
        monkeypatch.setattr(main.settings, name, value)

    with pytest.raises(RuntimeError) as exc:
        main._validate_production_config()

    message = str(exc.value)
    assert "CORS origins must use HTTPS" in message
    assert "SUPABASE_URL must use HTTPS" in message
    assert "STORAGE_PUBLIC_ENDPOINT must use HTTPS" in message
