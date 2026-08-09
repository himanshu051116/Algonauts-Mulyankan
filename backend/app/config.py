from pathlib import Path
from urllib.parse import urlparse

import arq
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    environment: str = "development"
    database_url: str = (
        "postgresql+asyncpg://mulyankan:mulyankan_secret@localhost:5432/mulyankan"
    )
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_jwks_url: str = ""
    supabase_jwt_issuer: str = ""
    supabase_jwt_audience: str = "authenticated"
    supabase_jwt_algorithms: str = "RS256,ES256"
    supabase_jwks_cache_seconds: int = 300
    jwt_clock_skew_seconds: int = 60
    auth_allow_local_jwt: bool = False
    local_jwt_issuer: str = "mulyankan-local-dev"
    local_jwt_audience: str = "mulyankan-dev"
    jwt_secret: str = "change-this-to-a-long-random-secret"
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24
    storage_endpoint: str = "http://localhost:9000"
    storage_public_endpoint: str = ""
    storage_access_key: str = "minioadmin"
    storage_secret_key: str = "minioadmin"
    storage_bucket: str = "mulyankan-proposals"
    storage_region: str = "us-east-1"
    redis_url: str = "redis://localhost:6379/0"
    ocr_language: str = "eng+hin"
    max_file_size_mb: int = 50
    allowed_extensions: str = ".pdf,.docx,.txt"
    malware_scan_enabled: bool = False
    malware_scan_command: str = "clamscan"
    malware_scan_timeout_seconds: int = 60
    rate_limit_per_minute: int = 30
    readiness_timeout_seconds: float = 3.0
    signed_download_ttl_seconds: int = 900
    worker_heartbeat_key: str = "mulyankan:worker:heartbeat"
    worker_heartbeat_ttl_seconds: int = 120
    allowed_hosts: str = "localhost,127.0.0.1"
    trust_proxy_headers: bool = False
    metrics_enabled: bool = True
    metrics_token: str = ""
    log_level: str = "INFO"
    sentry_dsn: str = ""
    otel_service_name: str = "mulyankan-backend"
    cors_origins: str = "http://localhost:4174,http://localhost:5173"
    bootstrap_admin_uid: str = ""
    bootstrap_admin_email: str = ""
    audit_export_signing_key: str = ""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def backend_dir(self) -> Path:
        return BACKEND_DIR

    @property
    def migrations_dir(self) -> Path:
        return PROJECT_ROOT / "migrations"

    @property
    def alembic_ini_path(self) -> Path:
        return self.migrations_dir / "alembic.ini"

    @property
    def data_dir(self) -> Path:
        return PROJECT_ROOT / "data"

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"prod", "production"}

    @property
    def resolved_supabase_jwt_issuer(self) -> str:
        if self.supabase_jwt_issuer:
            return self.supabase_jwt_issuer.rstrip("/")
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def resolved_supabase_jwks_url(self) -> str:
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def supabase_jwt_algorithm_list(self) -> list[str]:
        return [
            alg.strip()
            for alg in self.supabase_jwt_algorithms.split(",")
            if alg.strip()
        ]

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]
        return list(dict.fromkeys(origins)) or ["*"]

    @property
    def allowed_host_list(self) -> list[str]:
        hosts = [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]
        return list(dict.fromkeys(hosts)) or ["localhost", "127.0.0.1"]

    @property
    def allowed_extension_set(self) -> set[str]:
        return {
            extension.strip().lower()
            for extension in self.allowed_extensions.split(",")
            if extension.strip()
        }

    @property
    def arq_redis_settings(self) -> arq.connections.RedisSettings:
        parsed = urlparse(self.redis_url)
        return arq.connections.RedisSettings(
            host=parsed.hostname or "localhost",
            port=parsed.port or 6379,
            password=parsed.password,
            database=int(parsed.path.lstrip("/")) if parsed.path else 0,
        )

    @model_validator(mode="after")
    def validate_auth_safety(self) -> "Settings":
        if self.is_production and self.auth_allow_local_jwt:
            raise ValueError("AUTH_ALLOW_LOCAL_JWT cannot be enabled in production")
        if self.max_file_size_mb <= 0:
            raise ValueError("MAX_FILE_SIZE_MB must be greater than zero")
        if self.rate_limit_per_minute < 0:
            raise ValueError("RATE_LIMIT_PER_MINUTE cannot be negative")
        if self.readiness_timeout_seconds <= 0:
            raise ValueError("READINESS_TIMEOUT_SECONDS must be greater than zero")
        if self.signed_download_ttl_seconds < 60 or self.signed_download_ttl_seconds > 86400:
            raise ValueError("SIGNED_DOWNLOAD_TTL_SECONDS must be between 60 and 86400")
        if self.worker_heartbeat_ttl_seconds < 30:
            raise ValueError("WORKER_HEARTBEAT_TTL_SECONDS must be at least 30")
        unsupported = self.allowed_extension_set - {".pdf", ".docx", ".txt"}
        if unsupported:
            raise ValueError(
                f"Unsupported ALLOWED_EXTENSIONS values: {sorted(unsupported)}"
            )
        return self


settings = Settings()
