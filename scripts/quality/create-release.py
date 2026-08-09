from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

ALLOWED_TOP_LEVEL_DIR_NAMES = {
    ".github",
    "backend",
    "data",
    "docs",
    "frontend",
    "migrations",
    "scripts",
    "src",
}
ALLOWED_TOP_LEVEL_FILE_NAMES = {
    ".dockerignore",
    ".env.example",
    ".gitignore",
    ".npmrc",
    "BUGFIX_REPORT.md",
    "CHANGELOG_MULYANKAN_REBUILD.md",
    "EVALUATION_SYSTEM.md",
    "README.md",
    "compose.dev.yml",
    "docker-compose.yml",
    "eslint.config.js",
    "index.html",
    "package-lock.json",
    "package.json",
    "postcss.config.js",
    "pyproject.toml",
    "tsconfig.json",
    "vercel.json",
    "vite.config.ts",
}
EXCLUDED_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".pytest-tmp",
    ".ruff_cache",
    ".tmp",
    ".venv",
    ".vercel",
    "__pycache__",
    "backups",
    "dist",
    "htmlcov",
    "logs",
    "node_modules",
    "uploads",
    "venv",
}
EXCLUDED_FILE_NAMES = {
    ".coverage",
    "coverage.xml",
    "RELEASE_MANIFEST.json",
    "SBOM.cyclonedx.json",
    "tsconfig.tsbuildinfo",
}
EXCLUDED_SUFFIXES = {
    ".db",
    ".dump",
    ".log",
    ".pyc",
    ".pyo",
    ".sql",
    ".sqlite",
    ".sqlite3",
    ".tar",
    ".tgz",
    ".zip",
}
TEXT_SUFFIXES = {
    ".css",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "OpenAI-style key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b"),
    "Supabase secret key": re.compile(r"\bsb_secret_[A-Za-z0-9_-]{20,}\b"),
    "Vercel token": re.compile(r"\b(?:vercel_|vcp_)[A-Za-z0-9_-]{20,}\b", re.IGNORECASE),
    "long JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{40,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b"),
}
SENSITIVE_ENV_KEY = re.compile(
    r"(?:^|_)(?:PASSWORD|SECRET|TOKEN|PRIVATE_KEY|SIGNING_KEY|SERVICE_ROLE_KEY|API_KEY)$",
    re.IGNORECASE,
)
PLACEHOLDER_MARKERS = (
    "change-me",
    "changeme",
    "development-only",
    "example",
    "generate-",
    "local-only",
    "placeholder",
    "replace-",
    "test-only",
    "your-",
)
SBOM_FILE_NAME = "SBOM.cyclonedx.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an allowlisted, secret-scanned Mulyankan source release ZIP"
    )
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "release")
    parser.add_argument("--version", default=None)
    return parser.parse_args()


def is_allowlisted(relative: Path) -> bool:
    if not relative.parts:
        return False
    if len(relative.parts) == 1:
        return relative.name in ALLOWED_TOP_LEVEL_FILE_NAMES
    return relative.parts[0] in ALLOWED_TOP_LEVEL_DIR_NAMES


def should_exclude(relative: Path) -> bool:
    if any(
        part in EXCLUDED_DIR_NAMES or part.startswith("backup-")
        for part in relative.parts[:-1]
    ):
        return True
    name = relative.name
    if name in EXCLUDED_FILE_NAMES:
        return True
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    lowered_name = name.lower()
    if name.endswith("~") or name.startswith(".~"):
        return True
    if ".backup" in name or name.endswith(".bak") or name.endswith("-backup"):
        return True
    if ".original" in lowered_name or "broken" in lowered_name:
        return True
    return relative.suffix.lower() in EXCLUDED_SUFFIXES


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().strip("'\"").strip()
    if not normalized or normalized.startswith("${"):
        return True
    lowered = normalized.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _scan_env_assignments(path: Path, text: str, root: Path) -> list[str]:
    findings: list[str] = []
    if not path.name.startswith(".env"):
        return findings
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not match:
            continue
        name, value = match.groups()
        if SENSITIVE_ENV_KEY.search(name) and not _is_placeholder(value):
            findings.append(
                f"{path.relative_to(root)}:{line_number}: non-placeholder value for {name}"
            )
    return findings


def scan_secrets(root: Path) -> list[str]:
    findings: list[str] = []
    for path in root.rglob("*"):
        is_text_candidate = (
            path.suffix.lower() in TEXT_SUFFIXES or path.name.startswith(".env")
        )
        if not path.is_file() or not is_text_candidate:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(root)}: {label}")
        findings.extend(_scan_env_assignments(path, text, root))
    return findings


def _npm_components(root: Path) -> list[dict[str, object]]:
    lock_path = root / "package-lock.json"
    if not lock_path.is_file():
        return []
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    packages = lock.get("packages", {})
    if not isinstance(packages, dict):
        return []

    components: list[dict[str, object]] = []
    for package_path, raw in packages.items():
        if not package_path or "node_modules/" not in package_path or not isinstance(raw, dict):
            continue
        name = str(package_path).rsplit("node_modules/", 1)[-1]
        version = str(raw.get("version") or "unresolved")
        scope = "development" if raw.get("dev") else "runtime"
        encoded_name = quote(name, safe="/")
        encoded_version = quote(version, safe=".-_")
        purl = f"pkg:npm/{encoded_name}@{encoded_version}"
        components.append(
            {
                "type": "library",
                "bom-ref": f"{purl}?scope={scope}",
                "name": name,
                "version": version,
                "purl": purl,
                "properties": [
                    {"name": "mulyankan:ecosystem", "value": "npm"},
                    {"name": "mulyankan:scope", "value": scope},
                ],
            }
        )
    return components


def _python_components(root: Path) -> list[dict[str, object]]:
    components: list[dict[str, object]] = []
    for relative, scope in (
        (Path("backend/requirements.txt"), "runtime"),
        (Path("backend/requirements-dev.txt"), "development"),
    ):
        path = root / relative
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            requirement = line.strip()
            if not requirement or requirement.startswith(("#", "-r ", "--requirement ")):
                continue
            match = re.match(
                r"^([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[^\]]+\])?\s*(.*)$",
                requirement,
            )
            if not match:
                continue
            name, constraint = match.groups()
            constraint = constraint.strip() or "*"
            exact = re.fullmatch(r"==\s*([^;\s]+)", constraint)
            version = exact.group(1) if exact else "declared"
            purl = f"pkg:pypi/{quote(name.lower(), safe='.-_')}"
            if exact:
                purl += f"@{quote(version, safe='.-_')}"
            components.append(
                {
                    "type": "library",
                    "bom-ref": f"python:{name.lower()}:{scope}:{constraint}",
                    "name": name,
                    "version": version,
                    "purl": purl,
                    "properties": [
                        {"name": "mulyankan:ecosystem", "value": "pypi"},
                        {"name": "mulyankan:scope", "value": scope},
                        {
                            "name": "mulyankan:declared_version_constraint",
                            "value": constraint,
                        },
                    ],
                }
            )
    return components


def build_sbom(root: Path, version: str, created_at: str) -> dict[str, object]:
    components = _npm_components(root) + _python_components(root)
    unique = {
        str(component["bom-ref"]): component
        for component in components
    }
    ordered = [unique[key] for key in sorted(unique)]
    serial_seed = f"Mulyankan:{version}:" + "|".join(sorted(unique))
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, serial_seed)}",
        "version": 1,
        "metadata": {
            "timestamp": created_at,
            "component": {
                "type": "application",
                "name": "Mulyankan",
                "version": version,
            },
            "properties": [
                {
                    "name": "mulyankan:inventory_type",
                    "value": "declared source dependencies; verify deployed versions separately",
                }
            ],
        },
        "components": ordered,
    }


def git_revision(source: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and re.fullmatch(r"[0-9a-fA-F]{40}", revision) else None


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    output_dir = args.output_dir.resolve()
    package_json = json.loads((source / "package.json").read_text(encoding="utf-8"))
    version = args.version or str(package_json["version"])
    archive_root = f"mulyankan-{version}"
    if output_dir == source:
        raise SystemExit("Output directory must not be the source directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"{archive_root}-source.zip"
    output_is_inside_source = output_dir.is_relative_to(source)
    created_at = datetime.now(UTC).isoformat()

    with tempfile.TemporaryDirectory(prefix="mulyankan-release-") as temp_dir:
        staging_root = Path(temp_dir) / archive_root
        files: list[Path] = []
        excluded_by_allowlist = 0
        for source_path in source.rglob("*"):
            if output_is_inside_source and source_path.is_relative_to(output_dir):
                continue
            relative = source_path.relative_to(source)
            if source_path.is_dir():
                continue
            if not is_allowlisted(relative):
                excluded_by_allowlist += 1
                continue
            if source_path.is_symlink():
                raise SystemExit(f"Release source contains a symbolic link: {relative}")
            if should_exclude(relative):
                continue
            destination = staging_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
            files.append(destination)

        sbom_path = staging_root / SBOM_FILE_NAME
        sbom_path.write_text(
            json.dumps(build_sbom(staging_root, version, created_at), indent=2) + "\n",
            encoding="utf-8",
        )
        files.append(sbom_path)

        findings = scan_secrets(staging_root)
        if findings:
            joined = "\n".join(f"- {finding}" for finding in findings)
            raise SystemExit(f"Potential secrets detected in release staging:\n{joined}")

        manifest_files = []
        for path in sorted(files):
            manifest_files.append(
                {
                    "path": str(path.relative_to(staging_root)).replace("\\", "/"),
                    "sha256": file_sha256(path),
                    "size_bytes": path.stat().st_size,
                }
            )
        manifest = {
            "product": "Mulyankan",
            "version": version,
            "classification": "controlled technical demonstration and shadow-pilot candidate",
            "official_decision_validated": False,
            "created_at_utc": created_at,
            "source_revision": git_revision(source),
            "release_policy": {
                "name": "allowlisted-source-release",
                "version": "1.0",
                "excluded_by_allowlist_count": excluded_by_allowlist,
            },
            "sbom": {
                "path": SBOM_FILE_NAME,
                "format": "CycloneDX",
                "spec_version": "1.5",
                "sha256": file_sha256(sbom_path),
            },
            "file_count": len(manifest_files),
            "files": manifest_files,
        }
        manifest_path = staging_root / "RELEASE_MANIFEST.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        with zipfile.ZipFile(
            archive_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path in sorted(staging_root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging_root.parent))

    checksum = file_sha256(archive_path)
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    checksum_path.write_text(f"{checksum}  {archive_path.name}\n", encoding="utf-8")
    print(archive_path)
    print(checksum_path)


if __name__ == "__main__":
    main()
