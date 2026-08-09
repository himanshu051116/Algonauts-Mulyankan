"""Optional ARQ/Redis integration checks.

These tests are skipped unless a real Redis endpoint accepts a short TCP probe.
The probe deliberately avoids creating an ARQ pool when Redis is unavailable,
so the offline release suite cannot retain connection/retry background tasks.
"""

from __future__ import annotations

import asyncio

import pytest

try:
    import arq
    from app.config import settings
except ImportError:
    pytest.skip("arq or pydantic_settings not installed", allow_module_level=True)


async def _redis_reachable() -> bool:
    host = settings.arq_redis_settings.host
    port = settings.arq_redis_settings.port
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=0.5
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, TimeoutError):
        return False


async def _close_pool(pool) -> None:
    close_pool = getattr(pool, "aclose", None)
    if close_pool is None:
        close_pool = pool.close
    await close_pool()


@pytest.mark.asyncio
async def test_arq_create_and_close_pool():
    if not await _redis_reachable():
        pytest.skip("Redis not available on the configured endpoint")
    pool = await arq.create_pool(settings.arq_redis_settings)
    assert pool is not None
    await _close_pool(pool)


@pytest.mark.asyncio
async def test_arq_pool_enqueue_and_close():
    if not await _redis_reachable():
        pytest.skip("Redis not available on the configured endpoint")
    pool = await arq.create_pool(settings.arq_redis_settings)
    try:
        result = await pool.enqueue_job(
            "evaluate_proposal", "test-id", scheme_code="MOC-ST"
        )
        assert result is not None
    finally:
        await _close_pool(pool)


@pytest.mark.asyncio
async def test_arq_pool_close_idempotent():
    if not await _redis_reachable():
        pytest.skip("Redis not available on the configured endpoint")
    pool = await arq.create_pool(settings.arq_redis_settings)
    await _close_pool(pool)
    await _close_pool(pool)
