"""Model registry integrity helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.ml.constants import (
    MODEL_ARTIFACT_PATH,
    MODEL_BENCHMARK_PATH,
    MODEL_CARD_PATH,
    MODEL_EVIDENCE_CONTRACT_PATH,
    MODEL_METRICS_PATH,
    MODEL_NAME,
    MODEL_QUALITY_REPORT_PATH,
    MODEL_RUBRIC_PATH,
    MODEL_VERSION,
    MODEL_REGISTRY_VERSION,
)
from app.models.proposal import FundingScheme, ModelVersion, RubricVersion

CONTEXTUAL_BASELINE_NAME = "contextual-rule-heuristic-v3"
CONTEXTUAL_BASELINE_VERSION = "3.0"
MODEL_LIFECYCLE_STATES = frozenset(
    {
        "bootstrap",
        "candidate",
        "shadow",
        "externally_tested",
        "institutionally_accepted",
        "retired",
    }
)
PROMOTION_EVIDENCE_STATES = MODEL_LIFECYCLE_STATES - {"bootstrap", "retired"}


def _hash_files(files: list[Path]) -> str:
    root = settings.project_root
    digest = hashlib.sha256()
    for path in files:
        if not path.is_file():
            raise RuntimeError(f"Model artifact component is missing: {path}")
        try:
            display_path = path.relative_to(root)
        except ValueError:
            display_path = path
        digest.update(str(display_path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    if not path.is_file():
        raise RuntimeError(f"Model artifact component is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_report_hash(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("report_sha256", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _report_section(value: dict[str, Any], key: str) -> dict[str, Any]:
    section = value.get(key)
    if not isinstance(section, dict):
        raise RuntimeError("Model quality gate report metadata is incomplete")
    return section


def contextual_baseline_artifact_hash() -> str:
    """Hash the executable baseline and active MOC-ST configuration."""
    root = settings.project_root
    data_dir = settings.data_dir
    files: list[Path] = [
        root / "backend/app/services/scoring.py",
        root / "backend/app/services/evidence_contracts.py",
        root / "data/evidence-contracts/moc-st-evidence-contracts-v1.yaml",
        root / "backend/app/services/rules.py",
        root / "backend/app/services/field_schema.py",
        data_dir / "canonical-fields/moc-st-fields-v1.yaml",
        *sorted((data_dir / "rules").glob("moc-st-*.yaml")),
    ]
    return _hash_files(files)


def brochure_ml_artifact_hash() -> str:
    """Hash the trained artifact, model card, rubric, and executable inference path."""
    root = settings.project_root
    return _hash_files(
        [
            MODEL_ARTIFACT_PATH,
            MODEL_CARD_PATH,
            MODEL_METRICS_PATH,
            MODEL_QUALITY_REPORT_PATH,
            MODEL_BENCHMARK_PATH,
            MODEL_RUBRIC_PATH,
            root / "backend/app/ml/constants.py",
            root / "backend/app/ml/bootstrap.py",
            root / "backend/app/ml/training.py",
            root / "backend/app/ml/inference.py",
            root / "backend/app/ml/quality_gate.py",
            root / "backend/app/services/evaluation_engine.py",
            root / "backend/app/services/scoring.py",
            root / "backend/app/services/evidence_contracts.py",
            root / "backend/app/services/document_gate.py",
            root / "data/evidence-contracts/moc-st-evidence-contracts-v1.yaml",
            root / "data/training/moc-brochure-weak-label-spec-v1.yaml",
        ]
    )


def brochure_ml_metadata() -> dict[str, Any]:
    """Load trusted packaged model metadata for database registration."""
    if not MODEL_CARD_PATH.is_file():
        raise RuntimeError(f"Model card is missing: {MODEL_CARD_PATH}")
    value = json.loads(MODEL_CARD_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("Model card root must be an object")
    if value.get("model_name") != MODEL_NAME or value.get("model_version") != MODEL_VERSION:
        raise RuntimeError("Model card identity does not match the registered ML model")
    return value


def brochure_ml_quality_report() -> dict[str, Any]:
    """Load and verify the deterministic no-private-data gate report."""

    if not MODEL_QUALITY_REPORT_PATH.is_file():
        raise RuntimeError(
            f"Model quality gate report is missing: {MODEL_QUALITY_REPORT_PATH}"
        )
    value = json.loads(MODEL_QUALITY_REPORT_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("Model quality gate report root must be an object")
    claimed_hash = value.get("report_sha256")
    if (
        not isinstance(claimed_hash, str)
        or len(claimed_hash) != 64
        or _canonical_report_hash(value) != claimed_hash
    ):
        raise RuntimeError("Model quality gate report hash is invalid")
    if value.get("passed") is not True or value.get("official_decision_validated") is not False:
        raise RuntimeError("Model quality gate report has an unsafe promotion outcome")

    model = _report_section(value, "model")
    benchmark = _report_section(value, "benchmark")
    rubric = _report_section(value, "rubric")
    evidence_contract = _report_section(value, "evidence_contract")
    promotion = _report_section(value, "promotion")
    if (
        model.get("name") != MODEL_NAME
        or model.get("artifact_version") != MODEL_VERSION
        or model.get("inference_policy_version") != MODEL_REGISTRY_VERSION
        or model.get("artifact_sha256") != _file_sha256(MODEL_ARTIFACT_PATH)
    ):
        raise RuntimeError("Model quality gate report identity does not match the artifact")
    if benchmark.get("sha256") != _file_sha256(MODEL_BENCHMARK_PATH):
        raise RuntimeError("Model quality gate report benchmark hash is stale")
    if rubric.get("sha256") != _file_sha256(MODEL_RUBRIC_PATH):
        raise RuntimeError("Model quality gate report rubric hash is stale")
    if evidence_contract.get("sha256") != _file_sha256(
        MODEL_EVIDENCE_CONTRACT_PATH
    ):
        raise RuntimeError("Model quality gate report evidence-contract hash is stale")
    if promotion.get("recommended_state") not in MODEL_LIFECYCLE_STATES:
        raise RuntimeError("Model quality gate report has an invalid lifecycle recommendation")
    if promotion.get("eligible_for_official_decision_use") is not False:
        raise RuntimeError("Bootstrap model cannot be approved for official decision use")
    return value


def validate_model_artifact(model: ModelVersion) -> None:
    """Reject model metadata that cannot reproduce the selected engine."""
    lifecycle_state = getattr(model, "lifecycle_state", None) or "bootstrap"
    quality_report_hash = getattr(model, "quality_gate_report_hash", None)
    if lifecycle_state not in MODEL_LIFECYCLE_STATES:
        raise RuntimeError("Selected model has an invalid lifecycle state")
    if lifecycle_state in PROMOTION_EVIDENCE_STATES and not quality_report_hash:
        raise RuntimeError("Selected promoted model has no quality gate report hash")
    if len(model.artifact_hash or "") != 64 or model.artifact_hash == "0" * 64:
        raise RuntimeError("Selected model has an invalid artifact hash")
    if model.model_name == CONTEXTUAL_BASELINE_NAME:
        expected = contextual_baseline_artifact_hash()
        if model.version != CONTEXTUAL_BASELINE_VERSION:
            raise RuntimeError("Selected contextual baseline version is unsupported")
        if model.artifact_hash != expected:
            raise RuntimeError("Selected contextual baseline artifact hash does not match code")
        return
    if model.model_name == MODEL_NAME:
        if model.version != MODEL_REGISTRY_VERSION:
            raise RuntimeError("Selected brochure ML inference-policy version is unsupported")
        expected = brochure_ml_artifact_hash()
        if model.artifact_hash != expected:
            raise RuntimeError("Selected brochure ML artifact hash does not match packaged files")
        metadata = brochure_ml_metadata()
        quality_report = brochure_ml_quality_report()
        if quality_report_hash != quality_report["report_sha256"]:
            raise RuntimeError(
                "Selected brochure ML quality report hash does not match packaged evidence"
            )
        recommendation = quality_report["promotion"]["recommended_state"]
        if lifecycle_state != recommendation:
            raise RuntimeError(
                "Selected brochure ML lifecycle state exceeds its quality evidence"
            )
        if model.training_rows != int(metadata.get("training_rows", 0)):
            raise RuntimeError("Selected brochure ML training row count does not match its model card")
        metrics = metadata.get("metrics")
        if not isinstance(metrics, dict) or not metrics.get("trained_model"):
            raise RuntimeError("Selected brochure ML model has invalid validation metadata")
        if not model.test_metrics or not model.test_metrics.get("trained_model"):
            raise RuntimeError("Selected brochure ML registry entry has no training metrics")
        return
    if model.training_rows <= 0:
        raise RuntimeError("Selected trained model has no registered training rows")
    if not model.test_metrics:
        raise RuntimeError("Selected trained model has no registered validation metrics")


async def select_active_model_version(
    session: AsyncSession,
    scheme_code: str,
    *,
    at: datetime | None = None,
    validate: bool = True,
) -> ModelVersion:
    """Select the exact model/rubric pair used by evaluation workers.

    Readiness checks and workers must share this path so a deployment cannot
    report ready while the evaluator would reject the active registry row.
    """
    effective_at = at or datetime.now(timezone.utc)
    result = await session.execute(
        select(ModelVersion)
        .join(RubricVersion, RubricVersion.id == ModelVersion.rubric_version_id)
        .join(FundingScheme, FundingScheme.id == RubricVersion.scheme_id)
        .where(
            ModelVersion.is_active.is_(True),
            RubricVersion.is_active.is_(True),
            RubricVersion.effective_date <= effective_at,
            FundingScheme.is_active.is_(True),
            FundingScheme.code == scheme_code,
        )
        .order_by(ModelVersion.created_at.desc())
        .limit(1)
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise RuntimeError(
            f"No active model/rubric is registered for scheme {scheme_code}"
        )
    if validate:
        validate_model_artifact(model)
    return model
