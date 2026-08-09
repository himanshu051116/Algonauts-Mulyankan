"""Liveness, readiness, and secured Prometheus metrics endpoints."""

from __future__ import annotations

import asyncio
import hmac
import shutil
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.services.model_registry import select_active_model_version
from app.services.storage import check_storage_ready

router = APIRouter(tags=["health"])
LATEST_MIGRATION = "20260712_model_lifecycle"
ACTIVE_SCHEME_CODE = "MOC-ST"


async def _with_timeout(check: Callable[[], Awaitable[Any]]) -> Any:
    return await asyncio.wait_for(check(), timeout=settings.readiness_timeout_seconds)


async def _check_database(db: AsyncSession) -> bool:
    await db.execute(text("SELECT 1"))
    return True


async def _check_migration(db: AsyncSession) -> bool:
    result = await db.execute(text("SELECT version_num FROM alembic_version"))
    return result.scalar_one_or_none() == LATEST_MIGRATION


async def _check_reference_data(db: AsyncSession) -> bool:
    await select_active_model_version(db, ACTIVE_SCHEME_CODE)
    return True


async def _check_redis() -> bool:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        return bool(await redis.ping())
    finally:
        await redis.aclose()


async def _check_worker_heartbeat() -> bool:
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        return bool(await redis.get(settings.worker_heartbeat_key))
    finally:
        await redis.aclose()


async def _check_ocr_runtime() -> bool:
    def _probe() -> bool:
        try:
            import pytesseract

            languages = set(pytesseract.get_languages(config=""))
            required = {value.strip() for value in settings.ocr_language.split("+") if value.strip()}
            return bool(required) and required.issubset(languages)
        except Exception:
            return False

    return await asyncio.to_thread(_probe)


async def _check_malware_scanner() -> bool:
    if not settings.malware_scan_enabled:
        return not settings.is_production
    return shutil.which(settings.malware_scan_command) is not None


async def _execute_check(
    name: str,
    check: Callable[[], Awaitable[bool]],
    *,
    critical: bool,
) -> tuple[str, dict[str, Any]]:
    try:
        ok = bool(await _with_timeout(check))
    except Exception:
        ok = False
    return name, {
        "status": "ok" if ok else "unavailable",
        "critical": critical,
    }


@router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "version": "0.8.0",
        "environment": settings.environment,
    }


@router.get("/health/ready")
async def readiness(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    database_checks = [
        await _execute_check("database", lambda: _check_database(db), critical=True),
        await _execute_check("migration", lambda: _check_migration(db), critical=True),
        await _execute_check(
            "reference_data", lambda: _check_reference_data(db), critical=True
        ),
    ]
    external_checks = await asyncio.gather(
        _execute_check("redis", _check_redis, critical=True),
        _execute_check("storage", check_storage_ready, critical=True),
        _execute_check(
            "worker",
            _check_worker_heartbeat,
            critical=settings.is_production,
        ),
        _execute_check(
            "ocr_runtime",
            _check_ocr_runtime,
            critical=settings.is_production,
        ),
        _execute_check(
            "malware_scanner",
            _check_malware_scanner,
            critical=settings.is_production,
        ),
    )
    checks = dict(database_checks + list(external_checks))
    critical_ok = all(
        check["status"] == "ok"
        for check in checks.values()
        if check["critical"]
    )
    return JSONResponse(
        status_code=200 if critical_ok else 503,
        content={
            "status": "ready" if critical_ok else "not_ready",
            "environment": settings.environment,
            "checks": checks,
        },
    )


@router.get("/metrics", include_in_schema=False)
async def metrics(
    authorization: str | None = Header(default=None),
) -> Response:
    if not settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    if settings.metrics_token:
        expected = f"Bearer {settings.metrics_token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Invalid metrics token")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
