from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO

FORBIDDEN_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".pytest-tmp",
    ".ruff_cache",
    ".tmp",
    ".venv",
    "__pycache__",
    "backups",
    "dist",
    "htmlcov",
    "logs",
    "node_modules",
    "uploads",
    "venv",
}
FORBIDDEN_SUFFIXES = {
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
MAX_MEMBER_BYTES = 250 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_MEMBER_COUNT = 100_000
MAX_COMPRESSION_RATIO = 2000


class VerificationError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Independently verify a Mulyankan source release and checksum"
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--archive", type=Path)
    target.add_argument("--release-dir", type=Path)
    return parser.parse_args()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stream_sha256(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _resolve_archive(args: argparse.Namespace) -> Path:
    if args.archive is not None:
        archive = args.archive.resolve()
    else:
        release_dir = args.release_dir.resolve()
        archives = sorted(release_dir.glob("mulyankan-*-source.zip"))
        if len(archives) != 1:
            raise VerificationError(
                f"Expected exactly one source archive in {release_dir}, found {len(archives)}"
            )
        archive = archives[0]
    if not archive.is_file():
        raise VerificationError(f"Release archive does not exist: {archive}")
    return archive


def _verify_checksum(archive: Path) -> str:
    checksum_path = archive.with_suffix(archive.suffix + ".sha256")
    if not checksum_path.is_file():
        raise VerificationError(f"Checksum sidecar is missing: {checksum_path}")
    fields = checksum_path.read_text(encoding="utf-8").strip().split()
    if len(fields) != 2 or fields[1] != archive.name:
        raise VerificationError("Checksum sidecar has an invalid format or filename")
    expected = fields[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise VerificationError("Checksum sidecar does not contain a SHA-256 digest")
    actual = _file_sha256(archive)
    if actual != expected:
        raise VerificationError("Release archive SHA-256 does not match its sidecar")
    return actual


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().strip("'\"").strip()
    if not normalized or normalized.startswith("${"):
        return True
    lowered = normalized.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _scan_text(relative: PurePosixPath, text: str) -> list[str]:
    findings: list[str] = []
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            findings.append(f"{relative}: {label}")
    if relative.name.startswith(".env"):
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
            if not match:
                continue
            name, value = match.groups()
            if SENSITIVE_ENV_KEY.search(name) and not _is_placeholder(value):
                findings.append(
                    f"{relative}:{line_number}: non-placeholder value for {name}"
                )
    return findings


def _validate_member(relative: PurePosixPath) -> None:
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise VerificationError(f"Unsafe archive member path: {relative}")
    if any(part in FORBIDDEN_DIR_NAMES for part in relative.parts[:-1]):
        raise VerificationError(f"Forbidden directory in release: {relative}")
    if relative.name == ".env" or (
        relative.name.startswith(".env.") and relative.name != ".env.example"
    ):
        raise VerificationError(f"Runtime environment file in release: {relative}")
    lowered_name = relative.name.lower()
    if ".original" in lowered_name or "broken" in lowered_name:
        raise VerificationError(f"Obsolete or broken source file in release: {relative}")
    if relative.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise VerificationError(f"Forbidden file type in release: {relative}")


def _manifest_entries(manifest: dict[str, object]) -> dict[str, dict[str, object]]:
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        raise VerificationError("Release manifest files must be an array")
    entries: dict[str, dict[str, object]] = {}
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise VerificationError("Release manifest contains a non-object file entry")
        path = raw.get("path")
        digest = raw.get("sha256")
        size = raw.get("size_bytes")
        if (
            not isinstance(path, str)
            or not re.fullmatch(r"[0-9a-f]{64}", str(digest))
            or not isinstance(size, int)
            or size < 0
        ):
            raise VerificationError("Release manifest contains an invalid file entry")
        if path in entries:
            raise VerificationError(f"Duplicate path in release manifest: {path}")
        entries[path] = raw
    if manifest.get("file_count") != len(entries):
        raise VerificationError("Release manifest file count does not match its entries")
    return entries


def verify_release(archive: Path) -> dict[str, object]:
    archive_sha256 = _verify_checksum(archive)
    secret_findings: list[str] = []

    try:
        package = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise VerificationError("Release archive is not a valid ZIP package") from exc

    with package:
        infos = [info for info in package.infolist() if not info.is_dir()]
        if not infos or len(infos) > MAX_MEMBER_COUNT:
            raise VerificationError("Release archive has an invalid member count")
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise VerificationError("Release archive contains duplicate member names")
        if any("\\" in name for name in names):
            raise VerificationError("Release archive contains non-portable member paths")

        roots = {PurePosixPath(name).parts[0] for name in names}
        if len(roots) != 1:
            raise VerificationError("Release archive must contain one top-level directory")
        root = next(iter(roots))

        total_size = 0
        relative_infos: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            member = PurePosixPath(info.filename)
            if len(member.parts) < 2 or member.parts[0] != root:
                raise VerificationError(f"Archive member is outside the release root: {member}")
            relative = PurePosixPath(*member.parts[1:])
            _validate_member(relative)
            if info.flag_bits & 0x1:
                raise VerificationError(f"Encrypted member is not allowed: {relative}")
            if info.file_size > MAX_MEMBER_BYTES:
                raise VerificationError(f"Release member exceeds the size limit: {relative}")
            total_size += info.file_size
            if total_size > MAX_TOTAL_BYTES:
                raise VerificationError("Release archive exceeds the total size limit")
            if (
                info.compress_size > 0
                and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
            ):
                raise VerificationError(
                    f"Release member has a suspicious compression ratio: {relative}"
                )
            relative_infos[str(relative)] = info

        manifest_name = f"{root}/RELEASE_MANIFEST.json"
        if manifest_name not in names:
            raise VerificationError("Release manifest is missing")
        manifest = json.loads(package.read(manifest_name))
        if not isinstance(manifest, dict):
            raise VerificationError("Release manifest root must be an object")
        entries = _manifest_entries(manifest)

        payload_paths = set(relative_infos) - {"RELEASE_MANIFEST.json"}
        if set(entries) != payload_paths:
            missing = sorted(payload_paths - set(entries))
            extra = sorted(set(entries) - payload_paths)
            raise VerificationError(
                f"Release manifest payload mismatch; missing={missing}, extra={extra}"
            )

        for path, expected in entries.items():
            info = relative_infos[path]
            if info.file_size != expected["size_bytes"]:
                raise VerificationError(f"Release member size mismatch: {path}")
            with package.open(info) as handle:
                actual_hash = _stream_sha256(handle)
            if actual_hash != expected["sha256"]:
                raise VerificationError(f"Release member SHA-256 mismatch: {path}")

            relative = PurePosixPath(path)
            if relative.suffix.lower() in TEXT_SUFFIXES or relative.name.startswith(".env"):
                text = package.read(info).decode("utf-8", errors="strict")
                secret_findings.extend(_scan_text(relative, text))

        if secret_findings:
            joined = "\n".join(f"- {item}" for item in secret_findings)
            raise VerificationError(f"Potential secrets detected in release:\n{joined}")

        sbom_meta = manifest.get("sbom")
        if not isinstance(sbom_meta, dict) or sbom_meta.get("path") != "SBOM.cyclonedx.json":
            raise VerificationError("Release manifest does not identify the required SBOM")
        sbom_info = relative_infos.get("SBOM.cyclonedx.json")
        if sbom_info is None:
            raise VerificationError("CycloneDX SBOM is missing")
        sbom = json.loads(package.read(sbom_info))
        if (
            not isinstance(sbom, dict)
            or sbom.get("bomFormat") != "CycloneDX"
            or sbom.get("specVersion") != "1.5"
            or not isinstance(sbom.get("components"), list)
        ):
            raise VerificationError("CycloneDX SBOM has an invalid structure")

        return {
            "verified": True,
            "archive": archive.name,
            "archive_sha256": archive_sha256,
            "release_root": root,
            "version": manifest.get("version"),
            "source_revision": manifest.get("source_revision"),
            "file_count": len(entries),
            "sbom_component_count": len(sbom["components"]),
            "official_decision_validated": manifest.get("official_decision_validated"),
        }


def main() -> int:
    try:
        archive = _resolve_archive(parse_args())
        result = verify_release(archive)
    except (OSError, ValueError, VerificationError, zipfile.BadZipFile) as exc:
        print(f"Release verification failed: {exc}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
