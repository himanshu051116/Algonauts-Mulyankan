import os
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import settings
from app.database import init_db
from app.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.routers import (
    admin,
    audit,
    evaluations,
    governance,
    health,
    proposals,
    reviews,
    storage,
    validation,
)


def _validate_production_config() -> None:
    """Fail fast when production-unsafe defaults are active."""
    is_test = os.environ.get("TESTING", "").lower() in ("true", "1", "yes")
    if is_test or not settings.is_production:
        return

    errors: list[str] = []
    if settings.cors_origin_list == ["*"]:
        errors.append("CORS_ORIGINS must contain explicit origins")
    if "*" in settings.allowed_host_list:
        errors.append("ALLOWED_HOSTS cannot contain '*' in production")
    if not settings.allowed_host_list:
        errors.append("ALLOWED_HOSTS must be configured")
    if settings.auth_allow_local_jwt:
        errors.append("AUTH_ALLOW_LOCAL_JWT cannot be enabled")
    if not settings.supabase_url and not (
        settings.supabase_jwks_url and settings.supabase_jwt_issuer
    ):
        errors.append("Supabase URL or explicit JWKS URL and issuer are required")
    if (
        settings.jwt_secret == "change-this-to-a-long-random-secret"  # nosec B105
        or len(settings.jwt_secret) < 32
    ):
        errors.append("JWT_SECRET must contain at least 32 non-default characters")
    if settings.storage_access_key == "minioadmin":
        errors.append("STORAGE_ACCESS_KEY still uses the MinIO default")
    if settings.storage_secret_key == "minioadmin":  # nosec B105
        errors.append("STORAGE_SECRET_KEY still uses the MinIO default")
    if not settings.storage_bucket.strip():
        errors.append("STORAGE_BUCKET is required")
    parsed_database = urlparse(settings.database_url)
    if parsed_database.scheme.startswith("sqlite"):
        errors.append("SQLite is not supported for production")
    if parsed_database.password in {None, "", "mulyankan_secret", "password"}:
        errors.append("DATABASE_URL must use a non-default password")
    if settings.metrics_enabled and not settings.metrics_token.strip():
        errors.append("METRICS_TOKEN is required when metrics are enabled")
    if not settings.malware_scan_enabled:
        errors.append("MALWARE_SCAN_ENABLED must be true in production")
    if len(settings.audit_export_signing_key) < 32:
        errors.append("AUDIT_EXPORT_SIGNING_KEY must contain at least 32 characters")
    for origin in settings.cors_origin_list:
        parsed_origin = urlparse(origin)
        if parsed_origin.scheme != "https":
            errors.append("Production CORS origins must use HTTPS")
            break
    if settings.supabase_url and urlparse(settings.supabase_url).scheme != "https":
        errors.append("SUPABASE_URL must use HTTPS in production")
    if (
        settings.storage_public_endpoint
        and urlparse(settings.storage_public_endpoint).scheme != "https"
    ):
        errors.append("STORAGE_PUBLIC_ENDPOINT must use HTTPS in production")

    if errors:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_production_config()
    await init_db()
    yield


app = FastAPI(
    title="Mulyankan Backend API",
    description="Coal proposal preliminary scrutiny and human decision-support platform",
    version="0.8.0",
    lifespan=lifespan,
)

if settings.is_production:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_host_list,
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=settings.cors_origin_list != ["*"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=settings.rate_limit_per_minute,
)
app.add_middleware(RequestContextMiddleware)

app.include_router(health.router)
app.include_router(proposals.router, prefix="/api/v1/proposals", tags=["proposals"])
app.include_router(
    evaluations.router, prefix="/api/v1/evaluations", tags=["evaluations"]
)
app.include_router(reviews.router, prefix="/api/v1/reviews", tags=["reviews"])
app.include_router(governance.router, prefix="/api/v1/governance", tags=["governance"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(storage.router, prefix="/api/v1/storage", tags=["storage"])
app.include_router(audit.router, prefix="/api/v1")
app.include_router(
    validation.router, prefix="/api/v1/validation", tags=["validation"]
)
