#!/usr/bin/env python3
"""Validate local Markdown links and image references in tracked project docs."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
INLINE_CODE = re.compile(r"`([^`\n]+)`")
REPO_PATH_PREFIXES = ("backend/", "src/", "data/", "migrations/", "scripts/", "frontend/", "docs/", ".github/")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "#", "data:")


def markdown_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "EVALUATION_SYSTEM.md", ROOT / "CHANGELOG_MULYANKAN_REBUILD.md", ROOT / "BUGFIX_REPORT.md"]
    files.extend(sorted((ROOT / "docs").rglob("*.md")))
    return [path for path in files if path.exists()]


def resolve_target(source: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().split("#", 1)[0].strip()
    if not target or target.startswith(SKIP_PREFIXES):
        return None
    # Markdown permits optional titles after a path; project docs do not use spaces in
    # local paths, so split those conservatively if present.
    if " \"" in target:
        target = target.split(" \"", 1)[0]
    target = unquote(target.strip("<>"))
    return (source.parent / target).resolve()


def main() -> int:
    missing: list[tuple[Path, str, Path]] = []
    checked = 0
    checked_code_paths = 0
    for source in markdown_files():
        text = source.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            resolved = resolve_target(source, raw_target)
            if resolved is None:
                continue
            checked += 1
            if not resolved.exists():
                missing.append((source.relative_to(ROOT), raw_target, resolved))

        # Project docs also use inline code for implementation paths. Validate only
        # conservative, root-relative repository prefixes so commands, URLs, env vars,
        # and illustrative filesystem paths are not mistaken for files.
        for raw_code in INLINE_CODE.findall(text):
            candidate = raw_code.strip()
            if not candidate.startswith(REPO_PATH_PREFIXES):
                continue
            if any(char in candidate for char in ("*", "{", "}", "<", ">", "|")):
                continue
            resolved = (ROOT / candidate.rstrip("/")).resolve()
            checked_code_paths += 1
            if not resolved.exists():
                missing.append((source.relative_to(ROOT), candidate, resolved))

    if missing:
        print("Documentation validation failed; missing local targets:")
        for source, raw_target, resolved in missing:
            print(f"  {source}: {raw_target} -> {resolved.relative_to(ROOT) if resolved.is_relative_to(ROOT) else resolved}")
        return 1

    print(
        "Documentation validation passed: "
        f"{checked} local links/images + {checked_code_paths} inline repository paths "
        f"checked across {len(markdown_files())} Markdown files."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
