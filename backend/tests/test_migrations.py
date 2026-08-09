from pathlib import Path
import re

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def test_initial_migration_reuses_user_role_enum_type():
    migration = (MIGRATIONS / "609a290ee409_initial_schema.py").read_text()
    assert "checkfirst=True" in migration
    assert "user_role_enum = postgresql.ENUM" in migration
    assert 'sa.Column("role", user_role_enum' in migration
    assert 'sa.Column("role", sa.Enum(name="user_role")' not in migration


def test_migration_revision_ids_fit_alembic_version_table():
    for path in MIGRATIONS.glob("*.py"):
        text = path.read_text()
        match = re.search(r'^revision(?:\s*:\s*[^=]+)?\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        assert match, f"{path.name} has no revision id"
        assert len(match.group(1)) <= 32, f"{path.name} revision id exceeds Alembic's default 32-character limit"


def test_scoring_safety_migration_preserves_legacy_prediction_values():
    migration = (MIGRATIONS / "20260708_scoring_safety.py").read_text()
    assert "SET awarded_score = NULL" not in migration
    assert "criterion_status = 'legacy_unverified'" in migration
    assert "awarded_score IS NULL OR evidence_count > 0 OR criterion_status = 'legacy_unverified'" in migration
    assert "awarded_score IS NULL OR released OR criterion_status = 'legacy_unverified'" in migration
    assert "SET total_score = diagnostic_score" in migration


def test_readiness_migration_constant_matches_latest_head():
    project_root = Path(__file__).resolve().parents[2]
    health_text = (project_root / "backend" / "app" / "routers" / "health.py").read_text()
    revisions: dict[str, str | None] = {}
    for path in MIGRATIONS.glob("*.py"):
        text = path.read_text()
        revision_match = re.search(r'^revision(?:\s*:\s*[^=]+)?\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        down_match = re.search(r'^down_revision(?:\s*:\s*[^=]+)?\s*=\s*(?:["\']([^"\']+)["\']|None)', text, re.MULTILINE)
        if revision_match:
            revisions[revision_match.group(1)] = down_match.group(1) if down_match and down_match.group(1) else None
    referenced = {down for down in revisions.values() if down}
    heads = set(revisions) - referenced
    assert len(heads) == 1
    latest_head = heads.pop()
    assignments = re.findall(
        r'^LATEST_MIGRATION\s*=\s*["\']([^"\']+)["\']',
        health_text,
        re.MULTILINE,
    )
    assert assignments == [latest_head]
