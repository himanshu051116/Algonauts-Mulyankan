"""Operational middleware for request identity, security headers, metrics, and throttling."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from prometheus_client import Counter, Gauge, Histogram
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings

HTTP_REQUESTS_TOTAL = Counter(
    "mulyankan_http_requests_total",
    "HTTP requests handled by the API",
    ("method", "route", "status"),
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "mulyankan_http_request_duration_seconds",
    "HTTP request latency",
    ("method", "route"),
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "mulyankan_http_requests_in_progress",
    "HTTP requests currently being processed",
    ("method",),
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id", "").strip() or str(
            uuid.uuid4()
        )
        request.state.request_id = request_id
        started = time.perf_counter()
        method = request.method
        HTTP_REQUESTS_IN_PROGRESS.labels(method=method).inc()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            route = request.scope.get("route")
            route_path = getattr(route, "path", request.url.path)
            status = str(response.status_code if response is not None else 500)
            HTTP_REQUESTS_TOTAL.labels(
                method=method, route=route_path, status=status
            ).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(
                method=method, route=route_path
            ).observe(time.perf_counter() - started)
            HTTP_REQUESTS_IN_PROGRESS.labels(method=method).dec()
            if response is not None:
                response.headers["X-Request-ID"] = request_id
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["X-Frame-Options"] = "DENY"
                response.headers["Referrer-Policy"] = "no-referrer"
                response.headers["Permissions-Policy"] = (
                    "camera=(), microphone=(), geolocation=()"
                )
                response.headers["Cross-Origin-Resource-Policy"] = "same-site"
                if request.url.path.startswith("/api/"):
                    response.headers["Cache-Control"] = "no-store"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Redis-backed fixed-window limit with a local degraded-mode fallback."""

    def __init__(self, app, requests_per_minute: int) -> None:
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True)
        self.local_windows: dict[str, deque[float]] = defaultdict(deque)
        self.local_lock = asyncio.Lock()

    @staticmethod
    def _client_key(request: Request) -> str:
        client = request.client.host if request.client else "unknown"
        if settings.trust_proxy_headers:
            forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
            if forwarded:
                client = forwarded
        return f"{client}:{request.method}:{request.url.path}"

    async def _redis_count(self, key: str) -> int:
        minute = int(time.time() // 60)
        redis_key = f"mulyankan:rate:{minute}:{key}"
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.incr(redis_key)
            pipe.expire(redis_key, 120)
            count, _ = await pipe.execute()
        return int(count)

    async def _local_count(self, key: str) -> int:
        now = time.monotonic()
        cutoff = now - 60
        async with self.local_lock:
            window = self.local_windows[key]
            while window and window[0] < cutoff:
                window.popleft()
            window.append(now)
            return len(window)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if (
            self.requests_per_minute <= 0
            or request.method == "OPTIONS"
            or request.url.path.startswith("/health")
            or request.url.path == "/metrics"
        ):
            return await call_next(request)

        key = self._client_key(request)
        try:
            count = await asyncio.wait_for(
                self._redis_count(key), timeout=settings.readiness_timeout_seconds
            )
        except Exception:
            count = await self._local_count(key)

        if count > self.requests_per_minute:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Request rate limit exceeded. Retry after the current minute.",
                    "code": "rate_limit_exceeded",
                },
                headers={"Retry-After": "60"},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(
            max(self.requests_per_minute - count, 0)
        )
        return response
