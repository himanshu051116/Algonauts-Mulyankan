from __future__ import annotations

import shlex
from pathlib import Path

import yaml

REQUIRED_SERVICES = {
    "postgres",
    "redis",
    "minio",
    "minio-init",
    "migration",
    "backend",
    "worker",
    "frontend",
}

REQUIRED_PYTHON_ENV = {
    "SUPABASE_JWKS_URL",
    "SUPABASE_JWT_ISSUER",
    "SUPABASE_JWT_AUDIENCE",
    "SUPABASE_JWT_ALGORITHMS",
    "SUPABASE_JWKS_CACHE_SECONDS",
    "JWT_CLOCK_SKEW_SECONDS",
    "JWT_EXPIRY_HOURS",
    "MAX_FILE_SIZE_MB",
    "OCR_LANGUAGE",
    "MALWARE_SCAN_ENABLED",
    "MALWARE_SCAN_COMMAND",
    "AUDIT_EXPORT_SIGNING_KEY",
    "LOG_LEVEL",
    "SENTRY_DSN",
    "OTEL_SERVICE_NAME",
}


def main() -> None:
    project_root = Path.cwd()
    compose_path = project_root / "docker-compose.yml"
    data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("docker-compose.yml must contain a YAML mapping")

    services = data.get("services")
    if not isinstance(services, dict):
        raise SystemExit("docker-compose.yml must define services")

    missing = REQUIRED_SERVICES.difference(services)
    if missing:
        raise SystemExit(
            f"docker-compose.yml is missing required services: {sorted(missing)}"
        )

    for service_name in ("postgres", "redis", "minio", "backend", "worker", "frontend"):
        service = _service(services, service_name)
        if not service.get("healthcheck"):
            raise SystemExit(f"Service {service_name!r} must define a healthcheck")

    backend = _service(services, "backend")
    worker = _service(services, "worker")
    migration = _service(services, "migration")
    if "migration" not in _dependency_names(backend):
        raise SystemExit("Backend must depend on the migration service")
    if "migration" not in _dependency_names(worker):
        raise SystemExit("Worker must depend on the migration service")
    for dependency in ("postgres", "redis", "minio", "minio-init"):
        if dependency not in _dependency_names(migration):
            raise SystemExit(f"Migration service must depend on {dependency}")

    migration_command = str(migration.get("command", ""))
    if "python -m backend.scripts.init_storage" in migration_command:
        raise SystemExit(
            "Migration service must not use unsupported bucket-level PutBucketCors; "
            "MinIO initialization belongs to minio-init and server-level CORS."
        )
    minio = _service(services, "minio")
    minio_environment = _environment(minio, "minio")
    if "MINIO_API_CORS_ALLOW_ORIGIN" not in minio_environment:
        raise SystemExit("MinIO must configure server-level CORS explicitly")
    minio_init = _service(services, "minio-init")
    minio_init_command = str(minio_init.get("entrypoint", ""))
    for required_fragment in ("mc alias set", "mc mb --ignore-existing", "STORAGE_BUCKET"):
        if required_fragment not in minio_init_command:
            raise SystemExit(
                f"minio-init is missing required initialization fragment: {required_fragment}"
            )
    if "cd /app/backend" in migration_command:
        raise SystemExit(
            "Migration service must not change to /app/backend before importing backend.*"
        )

    for service_name in ("migration", "backend", "worker"):
        environment = _environment(_service(services, service_name), service_name)
        missing_environment = REQUIRED_PYTHON_ENV.difference(environment)
        if missing_environment:
            raise SystemExit(
                f"Service {service_name!r} does not propagate runtime settings: "
                f"{sorted(missing_environment)}"
            )

    frontend = _service(services, "frontend")
    frontend_environment = _environment(frontend, "frontend")
    for required in ("STORAGE_PUBLIC_ENDPOINT", "NGINX_ENVSUBST_FILTER"):
        if required not in frontend_environment:
            raise SystemExit(
                f"Frontend must propagate runtime CSP setting: {required}"
            )
    nginx_template = project_root / "frontend" / "nginx.conf.template"
    if not nginx_template.is_file():
        raise SystemExit("Frontend Nginx runtime template is missing")
    template_text = nginx_template.read_text(encoding="utf-8")
    if "connect-src 'self' https: wss: ${STORAGE_PUBLIC_ENDPOINT};" not in template_text:
        raise SystemExit(
            "Frontend CSP must allow the configured browser-facing storage endpoint"
        )

    for service_name in ("migration", "backend", "worker", "frontend"):
        service = _service(services, service_name)
        build = service.get("build")
        if not isinstance(build, dict):
            raise SystemExit(f"Service {service_name!r} must define a build mapping")
        dockerfile = build.get("dockerfile")
        if not isinstance(dockerfile, str) or not dockerfile.strip():
            raise SystemExit(f"Service {service_name!r} must define a Dockerfile")
        _validate_dockerfile_sources(project_root, project_root / dockerfile)

    expected_port_tokens = {
        "postgres": "${POSTGRES_HOST_PORT:-5432}",
        "redis": "${REDIS_HOST_PORT:-6379}",
        "minio": "${MINIO_API_HOST_PORT:-9000}",
        "backend": "${BACKEND_HOST_PORT:-8000}",
        "frontend": "${FRONTEND_HOST_PORT:-3000}",
    }
    for service_name, token in expected_port_tokens.items():
        ports = _service(services, service_name).get("ports", [])
        if not isinstance(ports, list):
            raise SystemExit(f"Service {service_name!r} ports must be a list")
        rendered = " ".join(str(item) for item in ports)
        if token not in rendered:
            raise SystemExit(
                f"Service {service_name!r} must use configurable loopback host ports"
            )


    _validate_frontend_dependency_sources(project_root)

    print("docker-compose.yml and Docker build contexts are valid")


def _service(services: dict[object, object], name: str) -> dict[str, object]:
    value = services.get(name)
    if not isinstance(value, dict):
        raise SystemExit(f"Service {name!r} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _environment(service: dict[str, object], service_name: str) -> set[str]:
    value = service.get("environment", {})
    if isinstance(value, dict):
        return {str(key) for key in value}
    if isinstance(value, list):
        return {str(item).split("=", 1)[0] for item in value}
    raise SystemExit(f"Service {service_name!r} environment must be a mapping or list")


def _dependency_names(service: dict[str, object]) -> set[str]:
    depends_on = service.get("depends_on", {})
    if isinstance(depends_on, dict):
        return {str(key) for key in depends_on}
    if isinstance(depends_on, list):
        return {str(item) for item in depends_on}
    return set()


def _validate_dockerfile_sources(project_root: Path, dockerfile: Path) -> None:
    if not dockerfile.is_file():
        raise SystemExit(f"Dockerfile not found: {dockerfile.relative_to(project_root)}")

    for line_number, raw_line in enumerate(
        dockerfile.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line.upper().startswith("COPY "):
            continue
        tokens = shlex.split(line)
        if any(token.startswith("--from=") for token in tokens[1:]):
            continue
        arguments = [token for token in tokens[1:] if not token.startswith("--")]
        if len(arguments) < 2:
            raise SystemExit(
                f"Invalid COPY instruction in {dockerfile.name}:{line_number}"
            )
        for source in arguments[:-1]:
            if any(character in source for character in "*$?["):
                continue
            source_path = project_root / source.rstrip("/")
            if not source_path.exists():
                relative_dockerfile = dockerfile.relative_to(project_root)
                raise SystemExit(
                    f"Missing Docker COPY source {source!r} referenced by "
                    f"{relative_dockerfile}:{line_number}"
                )



def _validate_frontend_dependency_sources(project_root: Path) -> None:
    lock_path = project_root / "package-lock.json"
    lock_text = lock_path.read_text(encoding="utf-8")
    forbidden = ("internal.api.openai.org", "applied-caas-gateway")
    if any(token in lock_text for token in forbidden):
        raise SystemExit("package-lock.json contains a non-public package registry URL")

    npmrc = (project_root / ".npmrc").read_text(encoding="utf-8")
    if "registry=https://registry.npmjs.org/" not in npmrc:
        raise SystemExit(".npmrc must explicitly use the public npm registry")

    dockerfile = (project_root / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    if "node:22.16.0-alpine AS builder" in dockerfile:
        raise SystemExit("Frontend builder must use the Debian Node image, not Alpine")
    if "node:22.16.0-bookworm-slim AS builder" not in dockerfile:
        raise SystemExit("Frontend Docker builder version is not pinned as expected")

if __name__ == "__main__":
    main()
