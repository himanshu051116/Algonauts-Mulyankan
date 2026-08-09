"""Verify the additive Mulyankan 0.8 validation-pilot schema and assets."""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.config import settings
from app.database import engine

EXPECTED_TABLES = {
    "validation_studies",
    "validation_cases",
    "validation_consensus",
    "shadow_comparisons",
    "validation_metric_snapshots",
}
EXPECTED_ASSIGNMENT_COLUMNS = {"validation_case_id"}
EXPECTED_REVIEW_COLUMNS = {
    "annotation_protocol_version",
    "annotation_rulebook_version",
    "model_output_visible_at_submission",
}
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def _expected_revision() -> str:
    config = Config(str(MIGRATIONS_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected one Alembic head, found {heads}")
    return heads[0]


def _schema_snapshot(connection):
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    assignment_columns = {
        column["name"] for column in inspector.get_columns("reviewer_assignments")
    }
    review_columns = {
        column["name"] for column in inspector.get_columns("expert_reviews")
    }
    return tables, assignment_columns, review_columns


async def verify() -> None:
    async with engine.connect() as connection:
        revision = (
            await connection.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one()
        tables, assignment_columns, review_columns = await connection.run_sync(
            _schema_snapshot
        )

    missing_tables = EXPECTED_TABLES - tables
    missing_assignment_columns = EXPECTED_ASSIGNMENT_COLUMNS - assignment_columns
    missing_review_columns = EXPECTED_REVIEW_COLUMNS - review_columns
    expected_revision = _expected_revision()
    if revision != expected_revision:
        raise RuntimeError(
            f"Expected Alembic revision {expected_revision}, found {revision}"
        )
    if missing_tables:
        raise RuntimeError(f"Missing validation tables: {sorted(missing_tables)}")
    if missing_assignment_columns:
        raise RuntimeError(
            "Missing reviewer-assignment columns: "
            f"{sorted(missing_assignment_columns)}"
        )
    if missing_review_columns:
        raise RuntimeError(
            f"Missing expert-review columns: {sorted(missing_review_columns)}"
        )

    protocol = settings.data_dir / "validation" / "expert-grounded-validation-protocol-v1.yaml"
    rulebook = settings.data_dir / "validation" / "expert-annotation-rulebook-v1.yaml"
    for path in (protocol, rulebook):
        if not Path(path).is_file():
            raise RuntimeError(f"Validation governance asset is missing: {path}")

    print(f"alembic_revision={revision}")
    print(f"validation_tables={','.join(sorted(EXPECTED_TABLES))}")
    print(f"protocol_asset={protocol.name}")
    print(f"rulebook_asset={rulebook.name}")
    print("validation_pilot_verification=ok")


if __name__ == "__main__":
    asyncio.run(verify())
