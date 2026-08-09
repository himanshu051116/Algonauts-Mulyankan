"""Inference for the trained brochure-aligned Mulyankan scorer."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeAlias

import numpy as np
from app.ml.constants import (
    MODEL_ARTIFACT_PATH,
    MODEL_CARD_PATH,
    MODEL_FORMAT_VERSION,
    MODEL_NAME,
    MODEL_VERSION,
    MODEL_REGISTRY_VERSION,
)
from app.ml.training import build_feature_transformer
from app.services.scoring import _grade_ordinal, score_proposal

JsonObject: TypeAlias = dict[str, Any]


def _bounded(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _safe_criterion_key(criterion_id: str) -> str:
    return criterion_id.replace("-", "_")


@lru_cache(maxsize=2)
def load_model_bundle(path: str | None = None) -> dict[str, Any]:
    """Load a non-executable numeric model artifact.

    ``allow_pickle=False`` is mandatory.  This closes the joblib/pickle code
    execution surface and avoids the private scikit-learn class incompatibility
    that affected the previous release artifact.
    """

    artifact_path = Path(path) if path is not None else MODEL_ARTIFACT_PATH
    card_path = (
        artifact_path.with_name("model_card.json")
        if path is not None
        else MODEL_CARD_PATH
    )
    if not artifact_path.is_file():
        raise RuntimeError(f"ML model artifact is missing: {artifact_path}")
    if not card_path.is_file():
        raise RuntimeError(f"ML model card is missing: {card_path}")
    metadata = json.loads(card_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise RuntimeError("ML model card root is invalid")
    if metadata.get("model_name") != MODEL_NAME or metadata.get("model_version") != MODEL_VERSION:
        raise RuntimeError("ML model artifact identity does not match the registered model")
    if metadata.get("format_version") != MODEL_FORMAT_VERSION:
        raise RuntimeError("ML model artifact format is unsupported")

    required = {
        "criterion_ids",
        "criterion_maxima",
        "level_ratios",
        "metrics",
        "training_rows",
        "feature_stats",
    }
    missing = sorted(required - set(metadata))
    if missing:
        raise RuntimeError(f"ML model card is missing keys: {missing}")

    criterion_ids = [str(item) for item in metadata["criterion_ids"]]
    models: dict[str, dict[str, np.ndarray]] = {}
    try:
        with np.load(artifact_path, allow_pickle=False) as arrays:
            for criterion_id in criterion_ids:
                safe_id = _safe_criterion_key(criterion_id)
                keys = {
                    "coef": f"coef__{safe_id}",
                    "intercept": f"intercept__{safe_id}",
                    "classes": f"classes__{safe_id}",
                }
                if any(value not in arrays.files for value in keys.values()):
                    raise RuntimeError(
                        f"ML model is missing numeric arrays for criterion {criterion_id}"
                    )
                coef = np.asarray(arrays[keys["coef"]], dtype=np.float64)
                intercept = np.asarray(arrays[keys["intercept"]], dtype=np.float64)
                classes = np.asarray(arrays[keys["classes"]], dtype=np.int64)
                if coef.ndim != 2 or intercept.ndim != 1 or classes.ndim != 1:
                    raise RuntimeError(f"ML model arrays have invalid dimensions for {criterion_id}")
                if coef.shape[0] != intercept.shape[0] or coef.shape[0] != classes.shape[0]:
                    raise RuntimeError(f"ML model class dimensions disagree for {criterion_id}")
                expected_features = int(metadata.get("feature_config", {}).get("total_features", 0))
                if expected_features <= 0 or coef.shape[1] != expected_features:
                    raise RuntimeError(f"ML model feature dimensions disagree for {criterion_id}")
                if sorted(classes.tolist()) != [0, 1, 2, 3]:
                    raise RuntimeError(f"ML model classes are invalid for {criterion_id}")
                if not np.isfinite(coef).all() or not np.isfinite(intercept).all():
                    raise RuntimeError(f"ML model contains non-finite values for {criterion_id}")
                models[criterion_id] = {
                    "coef": coef,
                    "intercept": intercept,
                    "classes": classes,
                }
    except ValueError as exc:
        raise RuntimeError("ML model artifact is not a valid pickle-free NumPy archive") from exc

    return {**metadata, "models": models}


def clear_model_cache() -> None:
    load_model_bundle.cache_clear()


def _baseline_lookup(baseline: JsonObject) -> dict[str, JsonObject]:
    result: dict[str, JsonObject] = {}
    for category_value in baseline.get("category_scores", []):
        if not isinstance(category_value, dict):
            continue
        for criterion_value in category_value.get("criteria", []):
            if not isinstance(criterion_value, dict):
                continue
            criterion_id = str(criterion_value.get("criterion_id", ""))
            if criterion_id:
                result[criterion_id] = criterion_value
    return result


def _criterion_input(criterion: JsonObject, full_text: str) -> str:
    evidence_value = criterion.get("evidence", [])
    evidence = evidence_value if isinstance(evidence_value, list) else []
    passages = [
        str(item.get("text", "")).strip()
        for item in evidence
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    ]
    if passages:
        return " ".join(passages[:5])
    return full_text


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits)
    exp = np.exp(shifted)
    denominator = float(np.sum(exp))
    if denominator <= 0 or not np.isfinite(denominator):
        return np.full_like(exp, 1.0 / max(len(exp), 1), dtype=float)
    probabilities = exp / denominator
    return np.asarray(probabilities, dtype=np.float64)


def _evidence_signal_terms(criterion: JsonObject, *, limit: int = 6) -> list[dict[str, Any]]:
    """Return transparent evidence terms, not fake model feature names.

    Hashing vectorizers intentionally do not retain a vocabulary.  Presenting
    hashed buckets as words would be misleading, so the API surfaces frequent
    non-trivial terms from the retrieved evidence and explicitly labels them as
    evidence signals rather than causal feature attributions.
    """

    evidence = criterion.get("evidence", [])
    passages = " ".join(
        str(item.get("text", ""))
        for item in evidence
        if isinstance(item, dict)
    )
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9/-]{2,}", passages.lower())
    stop = {
        "the", "and", "for", "with", "from", "that", "this", "will", "are",
        "was", "were", "into", "through", "project", "proposal", "using",
    }
    counts: dict[str, int] = {}
    for token in tokens:
        if token in stop:
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return [{"term": term, "count": count, "source": "retrieved_evidence"} for term, count in ranked]


def _validation_factor(metrics: dict[str, Any]) -> float:
    """Discount synthetic hold-out metrics instead of treating them as calibration."""

    mae = float(metrics.get("criterion_mean_mae_ratio", 0.35))
    accuracy = float(metrics.get("criterion_mean_level_accuracy", 0.0))
    mathematical = _bounded((1.0 - (1.6 * mae)) * (0.75 + (0.25 * accuracy)), 0.35, 0.96)
    if not bool(metrics.get("calibrated_on_expert_outcomes", False)):
        mathematical *= 0.78
    return _bounded(mathematical, 0.30, 0.86)


async def score_proposal_with_ml(
    scheme_code: str,
    extracted_text: str,
    rubric_version: str = "2.0",
    *,
    artifact_path: Path | None = None,
    document_role: str = "main_proposal",
    evidence_contract_version: str = "1",
    documents: list[dict[str, Any]] | None = None,
) -> JsonObject:
    """Predict rubric levels only for criteria with accepted evidence."""

    baseline = await score_proposal(
        scheme_code,
        extracted_text,
        rubric_version,
        document_role=document_role,
        evidence_contract_version=evidence_contract_version,
        documents=documents,
    )
    if "error" in baseline:
        return baseline
    if not extracted_text.strip():
        baseline.update(
            {
                "model_source": MODEL_NAME,
                "model_version": MODEL_REGISTRY_VERSION,
                "artifact_model_version": MODEL_VERSION,
                "training_data_type": "brochure-derived weak supervision",
                "confidence": 0.0,
                "confidence_type": "uncalibrated_reliability_indicator",
                "official_decision_validated": False,
                "scoring_status": "abstained",
                "abstention": True,
                "abstention_reasons": ["proposal text is empty"],
                "decision_recommendation": None,
                "total_score": None,
            }
        )
        return baseline

    bundle = load_model_bundle(str(artifact_path) if artifact_path else None)
    if str(bundle.get("rubric_version")) != rubric_version:
        raise RuntimeError(
            f"Model rubric {bundle.get('rubric_version')} is incompatible with requested rubric {rubric_version}"
        )

    model_map = bundle.get("models")
    if not isinstance(model_map, dict):
        raise RuntimeError("ML model artifact contains no criterion model mapping")
    level_ratios = np.asarray(bundle.get("level_ratios"), dtype=float)
    criterion_ids = [str(item) for item in bundle["criterion_ids"]]
    criterion_maxima = [float(item) for item in bundle["criterion_maxima"]]
    maxima_by_id = dict(zip(criterion_ids, criterion_maxima, strict=True))
    baseline_by_id = _baseline_lookup(baseline)
    transformer = build_feature_transformer()

    quality = baseline.get("document_quality", {})
    quality_factor = float(quality.get("factor", 0.0)) if isinstance(quality, dict) else 0.0
    word_count = int(quality.get("word_count", 0)) if isinstance(quality, dict) else 0
    length_coverage = _bounded(word_count / 450.0)
    metrics = bundle.get("metrics", {}) if isinstance(bundle.get("metrics"), dict) else {}
    validation_factor = _validation_factor(metrics)
    feature_stats = bundle.get("feature_stats", {}) if isinstance(bundle.get("feature_stats"), dict) else {}

    raw_predictions: dict[str, dict[str, Any]] = {}
    vocabulary_coverages: list[float] = []
    for criterion_id in criterion_ids:
        criterion = baseline_by_id.get(criterion_id, {})
        evidence = criterion.get("evidence", []) if isinstance(criterion, dict) else []
        if not isinstance(evidence, list):
            evidence = []
        if not criterion.get("released") or not evidence:
            raw_predictions[criterion_id] = {
                "released": False,
                "vocabulary_coverage": 0.0,
                "evidence_signals": [],
            }
            continue

        model = model_map.get(criterion_id)
        if not isinstance(model, dict):
            raise RuntimeError(f"ML model is missing criterion arrays for {criterion_id}")
        model_text = _criterion_input(criterion, extracted_text)
        if not model_text.strip():
            raw_predictions[criterion_id] = {
                "released": False,
                "vocabulary_coverage": 0.0,
                "evidence_signals": [],
            }
            continue
        transformed = transformer.transform([model_text]).tocsr()
        coef = np.asarray(model["coef"], dtype=float)
        intercept = np.asarray(model["intercept"], dtype=float)
        classes = np.asarray(model["classes"], dtype=int)
        if transformed.shape[1] != coef.shape[1]:
            raise RuntimeError(
                f"ML feature dimension mismatch for {criterion_id}: {transformed.shape[1]} != {coef.shape[1]}"
            )
        logits = np.asarray(transformed @ coef.T).reshape(-1) + intercept
        probabilities = _softmax(logits)
        ml_ratio = float(probabilities @ level_ratios[classes])
        stats = feature_stats.get(criterion_id, {}) if isinstance(feature_stats.get(criterion_id), dict) else {}
        expected_nonzero = max(float(stats.get("median_nonzero", 1.0)), 1.0)
        vocabulary_coverage = _bounded(
            float(transformed.getnnz()) / max(expected_nonzero * 0.70, 1.0)
        )
        vocabulary_coverages.append(vocabulary_coverage)
        raw_predictions[criterion_id] = {
            "released": True,
            "ratio": ml_ratio,
            "probabilities": probabilities,
            "classes": classes,
            "vocabulary_coverage": vocabulary_coverage,
            "evidence_signals": _evidence_signal_terms(criterion),
        }

    mean_vocabulary_coverage = (
        float(np.mean(vocabulary_coverages)) if vocabulary_coverages else 0.0
    )
    global_reliability = _bounded(
        (
            (0.34 * quality_factor)
            + (0.38 * mean_vocabulary_coverage)
            + (0.28 * length_coverage)
        ) * validation_factor,
        0.0,
        0.86,
    )

    category_scores: list[JsonObject] = []
    total_awarded = 0.0
    total_maximum = 0.0
    weighted_sufficiency = 0.0
    weighted_reliability = 0.0
    released_criteria = 0

    for category_value in baseline.get("category_scores", []):
        if not isinstance(category_value, dict):
            continue
        category_name = str(category_value.get("category", "Uncategorised"))
        criteria_output: list[JsonObject] = []
        category_awarded = 0.0
        category_maximum = float(category_value.get("maximum", 0.0))

        for criterion_value in category_value.get("criteria", []):
            if not isinstance(criterion_value, dict):
                continue
            criterion_id = str(criterion_value.get("criterion_id", ""))
            maximum = float(
                criterion_value.get("maximum_score", maxima_by_id.get(criterion_id, 0.0))
            )
            total_maximum += maximum
            prediction = raw_predictions.get(criterion_id, {"released": False})
            evidence = criterion_value.get("evidence", [])
            if not isinstance(evidence, list):
                evidence = []

            if not prediction.get("released") or not evidence:
                criteria_output.append(
                    {
                        **criterion_value,
                        "awarded_score": None,
                        "ordinal_grade": None,
                        "criterion_status": "unresolved",
                        "released": False,
                        "confidence": None,
                        "ml_prediction": None,
                        "contextual_baseline_score": None,
                        "ml_weight": None,
                        "vocabulary_coverage": 0.0,
                        "top_model_features": [],
                        "evidence_signal_terms": [],
                        "warnings": [
                            "No contract-accepted evidence was available; no ML score was produced."
                        ],
                        "rationale": "No verified evidence means no criterion score.",
                    }
                )
                continue

            contextual_score = float(criterion_value.get("awarded_score") or 0.0)
            contextual_ratio = contextual_score / maximum if maximum else 0.0
            evidence_coverage = _bounded(
                float(criterion_value.get("evidence_coverage", 0.0))
            )
            information_sufficiency = _bounded(
                float(criterion_value.get("information_sufficiency", 0.0))
            )
            vocabulary_coverage = float(prediction["vocabulary_coverage"])
            controlled_ml_ratio = float(prediction["ratio"])
            warnings: list[str] = []

            if evidence_coverage < 0.15 and controlled_ml_ratio > 0.50:
                controlled_ml_ratio = 0.50
                warnings.append("ML estimate was capped because evidence coverage is weak.")

            criterion_reliability = _bounded(
                global_reliability
                * (
                    0.35
                    + (0.30 * evidence_coverage)
                    + (0.20 * information_sufficiency)
                    + (0.15 * vocabulary_coverage)
                )
            )
            ml_weight = _bounded(
                0.58 + (0.20 * criterion_reliability),
                0.58,
                0.76,
            )
            final_ratio = (
                (ml_weight * controlled_ml_ratio)
                + ((1.0 - ml_weight) * contextual_ratio)
            )
            final_ratio *= 0.78 + (0.22 * _bounded(quality_factor))
            awarded = round(_bounded(final_ratio) * maximum, 1)
            if criterion_reliability < 0.34:
                warnings.append("Low reliability indicator; expert confirmation is required.")

            rationale = (
                f"Criterion-specific trained NLP estimate {controlled_ml_ratio * maximum:.1f}/{maximum:.1f} "
                f"was computed only from contract-accepted evidence and blended with contextual score "
                f"{contextual_score:.1f}/{maximum:.1f}; uncalibrated reliability indicator "
                f"{criterion_reliability:.2f}."
            )
            criteria_output.append(
                {
                    **criterion_value,
                    "awarded_score": awarded,
                    "maximum_score": maximum,
                    "ordinal_grade": _grade_ordinal(awarded, maximum),
                    "criterion_status": criterion_value.get("criterion_status", "supported"),
                    "released": True,
                    "confidence": round(criterion_reliability, 3),
                    "confidence_type": "uncalibrated_reliability_indicator",
                    "ml_prediction": round(controlled_ml_ratio * maximum, 3),
                    "contextual_baseline_score": round(contextual_score, 3),
                    "ml_weight": round(ml_weight, 3),
                    "vocabulary_coverage": round(vocabulary_coverage, 3),
                    "top_model_features": [],
                    "evidence_signal_terms": prediction["evidence_signals"],
                    "warnings": warnings,
                    "rationale": rationale,
                }
            )
            category_awarded += awarded
            total_awarded += awarded
            released_criteria += 1
            weighted_sufficiency += information_sufficiency * maximum
            weighted_reliability += criterion_reliability * maximum

        category_scores.append(
            {
                "category": category_name,
                "maximum": category_maximum,
                "awarded": round(category_awarded, 1),
                "released": any(item.get("released") for item in criteria_output),
                "criteria": criteria_output,
            }
        )

    information_sufficiency = round(
        weighted_sufficiency / max(total_maximum, 1.0),
        3,
    )
    model_reliability = round(
        weighted_reliability / max(total_maximum, 1.0),
        3,
    )
    diagnostic_score = round(total_awarded, 1)
    abstention_reasons: list[str] = []
    if word_count < 150:
        abstention_reasons.append("document is too short for reliable brochure-rubric scoring")
    if quality_factor < 0.30:
        abstention_reasons.append("document quality or repetition controls failed")
    if mean_vocabulary_coverage < 0.30:
        abstention_reasons.append("proposal vocabulary is outside the bootstrap model's learned coverage")
    if information_sufficiency < 0.25:
        abstention_reasons.append("supporting evidence coverage is insufficient")
    if model_reliability < 0.32:
        abstention_reasons.append("uncalibrated reliability indicator is below the advisory threshold")
    if released_criteria < 6:
        abstention_reasons.append("too few criteria have contract-accepted evidence")
    abstention = bool(abstention_reasons)

    return {
        "scheme_code": scheme_code,
        "rubric_version": rubric_version,
        "total_score": None if abstention else diagnostic_score,
        "diagnostic_score": diagnostic_score,
        "maximum_score": total_maximum,
        "evidence_coverage": information_sufficiency,
        "information_sufficiency": information_sufficiency,
        "confidence": model_reliability,
        "confidence_type": "uncalibrated_reliability_indicator",
        "released_criterion_count": released_criteria,
        "category_scores": category_scores,
        "model_source": MODEL_NAME,
        "model_version": MODEL_REGISTRY_VERSION,
        "artifact_model_version": MODEL_VERSION,
        "engine_version": f"{MODEL_NAME}@{MODEL_REGISTRY_VERSION}",
        "model_format": MODEL_FORMAT_VERSION,
        "model_invoked": released_criteria > 0,
        "training_rows": int(bundle.get("training_rows", 0)),
        "criterion_training_examples": int(bundle.get("criterion_training_examples", 0)),
        "training_data_type": "brochure-derived weak supervision",
        "document_quality": quality,
        "document_role": document_role,
        "submission_package_document_count": len(documents) if documents else 1,
        "evidence_contract_version": evidence_contract_version,
        "vocabulary_coverage": round(mean_vocabulary_coverage, 3),
        "validation": {
            "evaluation_scope": metrics.get("evaluation_scope"),
            "metric_interpretation": metrics.get("metric_interpretation"),
            "bootstrap_holdout_evaluated": True,
            "official_decision_validated": False,
            "calibrated_on_expert_outcomes": False,
            "criterion_mean_mae_ratio": metrics.get("criterion_mean_mae_ratio"),
            "criterion_mean_level_accuracy": metrics.get("criterion_mean_level_accuracy"),
            "total_score_mae": metrics.get("total_score_mae"),
            "total_score_spearman": metrics.get("total_score_spearman"),
            "test_rows": metrics.get("test_rows"),
        },
        "blend_policy": {
            "ai_preliminary_score_weight": 0.45,
            "recommended_expert_weight": 0.55,
            "within_ai_score": "trained criterion NLP over contract-accepted evidence plus contextual evidence baseline",
        },
        "advisory_only": True,
        "official_decision_validated": False,
        "scoring_status": "abstained" if abstention else "released",
        "abstention": abstention,
        "abstention_reasons": abstention_reasons,
        "decision_recommendation": None if abstention else "expert_review_required",
    }
