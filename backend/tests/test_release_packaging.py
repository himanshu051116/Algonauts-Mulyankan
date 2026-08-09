from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path


RELEASE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "quality" / "create-release.py"
VERIFY_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "quality" / "verify-release.py"


def _write_minimal_source(root: Path) -> None:
    (root / "package.json").write_text(
        json.dumps({"name": "mulyankan-test", "version": "9.9.9"}),
        encoding="utf-8",
    )
    (root / "README.md").write_text("test release\n", encoding="utf-8")


def test_release_regenerates_manifest_and_excludes_previous_output(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = source / "release"
    source.mkdir()
    output.mkdir()
    _write_minimal_source(source)
    (source / "RELEASE_MANIFEST.json").write_text(
        '{"stale": true}\n', encoding="utf-8"
    )
    (output / "old-source.zip").write_bytes(b"old archive")

    subprocess.run(
        [
            sys.executable,
            str(RELEASE_SCRIPT),
            "--source",
            str(source),
            "--output-dir",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    archive_path = output / "mulyankan-9.9.9-source.zip"
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(
            archive.read("mulyankan-9.9.9/RELEASE_MANIFEST.json")
        )

    manifest_paths = {item["path"] for item in manifest["files"]}
    assert manifest["file_count"] == len(manifest["files"])
    assert "README.md" in manifest_paths
    assert "SBOM.cyclonedx.json" in manifest_paths
    assert "RELEASE_MANIFEST.json" not in manifest_paths
    assert manifest["release_policy"]["name"] == "allowlisted-source-release"
    assert manifest["official_decision_validated"] is False
    assert manifest["sbom"]["format"] == "CycloneDX"
    assert not any("old-source.zip" in name for name in names)


def test_release_secret_scan_includes_env_example(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    _write_minimal_source(source)
    (source / ".env.example").write_text(
        "OPENAI_API_KEY=sk-" + "A" * 32 + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(RELEASE_SCRIPT),
            "--source",
            str(source),
            "--output-dir",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert ".env.example: OpenAI-style key" in result.stderr + result.stdout


def test_release_rejects_non_placeholder_secret_assignments(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    _write_minimal_source(source)
    (source / ".env.example").write_text(
        "JWT_SECRET=actual-secret-material-that-must-not-ship\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(RELEASE_SCRIPT),
            "--source",
            str(source),
            "--output-dir",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "non-placeholder value for JWT_SECRET" in result.stderr + result.stdout
    assert "actual-secret-material" not in result.stderr + result.stdout


def test_release_uses_top_level_allowlist(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    _write_minimal_source(source)
    (source / "unreviewed-export.pdf").write_bytes(b"must not ship")

    subprocess.run(
        [
            sys.executable,
            str(RELEASE_SCRIPT),
            "--source",
            str(source),
            "--output-dir",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    with zipfile.ZipFile(output / "mulyankan-9.9.9-source.zip") as archive:
        names = set(archive.namelist())
    assert not any(name.endswith("unreviewed-export.pdf") for name in names)


def test_release_verifier_checks_manifest_sbom_and_checksum(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    _write_minimal_source(source)

    subprocess.run(
        [
            sys.executable,
            str(RELEASE_SCRIPT),
            "--source",
            str(source),
            "--output-dir",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [
            sys.executable,
            str(VERIFY_SCRIPT),
            "--release-dir",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)

    assert report["verified"] is True
    assert report["version"] == "9.9.9"
    assert report["file_count"] >= 3
    assert report["official_decision_validated"] is False

    checksum_path = output / "mulyankan-9.9.9-source.zip.sha256"
    checksum_path.write_text(
        f"{'0' * 64}  mulyankan-9.9.9-source.zip\n",
        encoding="utf-8",
    )
    failed = subprocess.run(
        [
            sys.executable,
            str(VERIFY_SCRIPT),
            "--release-dir",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert failed.returncode != 0
    assert "SHA-256 does not match" in failed.stdout


def test_release_has_only_public_npm_registry_urls() -> None:
    project_root = Path(__file__).resolve().parents[2]
    lock_text = (project_root / "package-lock.json").read_text(encoding="utf-8")
    assert "internal.api.openai.org" not in lock_text
    assert "applied-caas-gateway" not in lock_text
    assert "https://registry.npmjs.org/" in lock_text


def test_frontend_docker_builder_is_reproducible() -> None:
    project_root = Path(__file__).resolve().parents[2]
    dockerfile = (project_root / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM node:22.16.0-bookworm-slim AS builder" in dockerfile
    assert "node:22.16.0-alpine AS builder" not in dockerfile
    assert "npm config set registry https://registry.npmjs.org/" in dockerfile
    assert "COPY tsconfig.json vite.config.ts eslint.config.js index.html ./" in dockerfile
    assert "frontend/nginx.conf.template" in dockerfile
    assert "/etc/nginx/templates/mulyankan.conf.template" in dockerfile


def test_backend_host_port_is_configurable() -> None:
    project_root = Path(__file__).resolve().parents[2]
    compose = (project_root / "docker-compose.yml").read_text(encoding="utf-8")
    assert '${BACKEND_HOST_PORT:-8000}:8000' in compose


def test_release_excludes_manual_backup_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    _write_minimal_source(source)
    (source / "nginx.conf.csp-backup").write_text("old config", encoding="utf-8")
    (source / "settings.backup-20260708").write_text("old config", encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(RELEASE_SCRIPT),
            "--source",
            str(source),
            "--output-dir",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    with zipfile.ZipFile(output / "mulyankan-9.9.9-source.zip") as archive:
        names = set(archive.namelist())
    assert not any(name.endswith("csp-backup") for name in names)
    assert not any(".backup" in name for name in names)


def test_frontend_csp_uses_runtime_storage_origin() -> None:
    project_root = Path(__file__).resolve().parents[2]
    template = (project_root / "frontend" / "nginx.conf.template").read_text(encoding="utf-8")
    compose = (project_root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "connect-src 'self' https: wss: ${STORAGE_PUBLIC_ENDPOINT};" in template
    assert "NGINX_ENVSUBST_FILTER: STORAGE_PUBLIC_ENDPOINT" in compose
    assert "STORAGE_PUBLIC_ENDPOINT: ${STORAGE_PUBLIC_ENDPOINT:-http://127.0.0.1:9000}" in compose


def test_upgrade_script_surfaces_backend_logs_when_start_fails() -> None:
    project_root = Path(__file__).resolve().parents[2]
    script = (project_root / "scripts" / "windows" / "upgrade-scoring-safety-0.6.3.ps1").read_text(encoding="utf-8")
    assert 'docker compose logs backend --tail 200' in script
    assert 'Failed stack status' in script


def test_upgrade_script_uses_shell_safe_invariant_separator() -> None:
    project_root = Path(__file__).resolve().parents[2]
    script = (project_root / "scripts" / "windows" / "upgrade-scoring-safety-0.6.3.ps1").read_text(encoding="utf-8")
    assert '-F "," -P pager=off' in script
    assert '-F "|" -P pager=off' not in script
    assert "^([^,]+),(.+)$" in script

def test_report_separates_document_gate_from_deterministic_rule_result() -> None:
    project_root = Path(__file__).resolve().parents[2]
    report = (project_root / "src" / "features" / "reviews" / "ReportModal.tsx").read_text(encoding="utf-8")
    styles = (project_root / "src" / "styles.css").read_text(encoding="utf-8")

    assert 'const documentGateAccepted = structured?.documentGate.accepted === true;' in report
    assert '"No deterministic rule failure detected"' in report
    assert 'This does not establish document' in report
    assert '"Deterministic eligibility checks passed"' in report
    assert '.hard-screen-banner.review' in styles


def test_release_excludes_obsolete_broken_source_copies(tmp_path: Path) -> None:
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    (source / "scripts" / "windows").mkdir(parents=True)
    _write_minimal_source(source)
    obsolete = source / "scripts" / "windows" / "upgrade.ps1.original-broken"
    obsolete.write_text("must not ship", encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(RELEASE_SCRIPT),
            "--source",
            str(source),
            "--output-dir",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    with zipfile.ZipFile(output / "mulyankan-9.9.9-source.zip") as archive:
        names = set(archive.namelist())
    assert not any("original-broken" in name for name in names)
