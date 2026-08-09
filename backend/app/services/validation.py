"""Expert-grounded validation and shadow-pilot metrics.

This module measures model-versus-expert behaviour without changing proposal
workflow state or committee decisions. Metrics remain observational until an
institution approves the protocol, dataset, thresholds, and acceptance gates.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import delete, false, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.proposal import (
    CriterionPrediction,
    ExpertCriterionScore,
    ExpertReview,
    FundingScheme,
    ModelRun,
    ModelVersion,
    Proposal,
    ProposalVersion,
    ReviewerAssignment,
    RubricCriterion,
    RubricVersion,
    ShadowComparison,
    ValidationCase,
    ValidationConsensus,
    ValidationMetricSnapshot,
    ValidationStudy,
)


@dataclass(frozen=True)
class ReviewObservation:
    review_id: str
    assignment_id: str
    total_score: float
    recommendation: str | None
    criterion_scores: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class CaseObservation:
    case: ValidationCase
    model_run: ModelRun
    reviews: list[ReviewObservation]
    consensus_total: float
    consensus_recommendation: str | None
    consensus_criteria: dict[str, dict[str, Any]]
    agreement_metrics: dict[str, Any]
    model_released: bool
    model_total: float | None
    score_error: float | None
    model_recommendation: str | None
    recommendation_agreement: bool | None
    criterion_errors: dict[str, float]


async def rubric_definition_hash(db: AsyncSession, rubric_version_id: str) -> str:
    rubric_result = await db.execute(
        select(RubricVersion).where(RubricVersion.id == rubric_version_id)
    )
    rubric = rubric_result.scalar_one()
    criteria_result = await db.execute(
        select(RubricCriterion)
        .where(RubricCriterion.rubric_version_id == rubric_version_id)
        .order_by(RubricCriterion.order.asc(), RubricCriterion.id.asc())
    )
    criteria = list(criteria_result.scalars().all())
    payload = {
        "rubric_id": rubric.id,
        "scheme_id": rubric.scheme_id,
        "version": rubric.version,
        "total_marks": rubric.total_marks,
        "criteria": [
            {
                "id": criterion.id,
                "criterion_key": criterion.criterion_key,
                "category": criterion.category,
                "criterion": criterion.criterion,
                "maximum": criterion.maximum,
                "weight": criterion.weight,
                "description": criterion.description,
                "order": criterion.order,
            }
            for criterion in criteria
        ],
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


async def validate_study_frozen_identity(
    db: AsyncSession, study: ValidationStudy
) -> None:
    model_result = await db.execute(
        select(ModelVersion).where(ModelVersion.id == study.model_version_id)
    )
    model = model_result.scalar_one_or_none()
    if model is None or model.artifact_hash != study.model_artifact_hash:
        raise RuntimeError(
            "The validation study model artifact no longer matches its frozen identity"
        )
    current_rubric_hash = await rubric_definition_hash(db, study.rubric_version_id)
    if current_rubric_hash != study.rubric_definition_hash:
        raise RuntimeError(
            "The validation study rubric definition no longer matches its frozen identity"
        )


def _mean(values: Iterable[float]) -> float | None:
    cleaned = [float(value) for value in values]
    return statistics.fmean(cleaned) if cleaned else None


def _rmse(values: Iterable[float]) -> float | None:
    cleaned = [float(value) for value in values]
    return math.sqrt(statistics.fmean(value * value for value in cleaned)) if cleaned else None


def _pairwise_absolute_difference(values: list[float]) -> float | None:
    differences = [
        abs(values[left] - values[right])
        for left in range(len(values))
        for right in range(left + 1, len(values))
    ]
    return _mean(differences)


def _ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][1] == ordered[cursor][1]:
            end += 1
        average_rank = (cursor + 1 + end) / 2.0
        for index in range(cursor, end):
            ranks[ordered[index][0]] = average_rank
        cursor = end
    return ranks


def pearson_correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    )
    left_variance = sum((value - left_mean) ** 2 for value in left)
    right_variance = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_variance * right_variance)
    if denominator == 0:
        return None
    return numerator / denominator


def spearman_correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    return pearson_correlation(_ranks(left), _ranks(right))


def recommendation_from_score(
    score: float | None, policy: dict[str, Any]
) -> str | None:
    if score is None:
        return None
    approved_min = policy.get("approved_min")
    revision_min = policy.get("revision_min")
    if not isinstance(approved_min, (int, float)) or not isinstance(
        revision_min, (int, float)
    ):
        return None
    if approved_min <= revision_min or revision_min < 0 or approved_min > 100:
        return None
    if score >= float(approved_min):
        return "approved"
    if score >= float(revision_min):
        return "revision"
    return "rejected"


def _mode_or_none(values: list[str]) -> tuple[str | None, float | None]:
    if not values:
        return None, None
    counts = Counter(values)
    most_common = counts.most_common()
    if len(most_common) > 1 and most_common[0][1] == most_common[1][1]:
        return None, most_common[0][1] / len(values)
    return most_common[0][0], most_common[0][1] / len(values)


def consensus_from_reviews(
    reviews: list[ReviewObservation],
) -> tuple[float, str | None, dict[str, dict[str, Any]], dict[str, Any]]:
    if len(reviews) < 2:
        raise ValueError("At least two submitted blind reviews are required")

    totals = [review.total_score for review in reviews]
    recommendation_values = [
        review.recommendation for review in reviews if review.recommendation
    ]
    recommendation, recommendation_agreement = _mode_or_none(recommendation_values)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for review in reviews:
        for criterion_id, value in review.criterion_scores.items():
            grouped[criterion_id].append(value)

    criterion_consensus: dict[str, dict[str, Any]] = {}
    for criterion_id, values in grouped.items():
        scores = [float(value["score"]) for value in values]
        first = values[0]
        criterion_consensus[criterion_id] = {
            "criterion_id": criterion_id,
            "criterion_key": first.get("criterion_key"),
            "criterion": first.get("criterion"),
            "category": first.get("category"),
            "maximum": first.get("maximum"),
            "score": round(statistics.fmean(scores), 4),
            "reviewer_count": len(scores),
            "score_std": round(statistics.pstdev(scores), 4)
            if len(scores) > 1
            else 0.0,
        }

    total_score_range = max(totals) - min(totals)
    recommendation_disagreement = len(set(recommendation_values)) > 1
    material_disagreement = (
        total_score_range >= 15.0 or recommendation_disagreement
    )
    agreement = {
        "pairwise_total_mae": _pairwise_absolute_difference(totals),
        "total_score_std": statistics.pstdev(totals) if len(totals) > 1 else 0.0,
        "total_score_range": total_score_range,
        "recommendation_agreement": recommendation_agreement,
        "recommendation_consensus": recommendation,
        "recommendation_disagreement": recommendation_disagreement,
        "material_disagreement": material_disagreement,
        "adjudication_recommended": material_disagreement,
        "reviewer_count": len(reviews),
    }
    return (
        round(statistics.fmean(totals), 4),
        recommendation,
        criterion_consensus,
        agreement,
    )


def _calibration_ece(observations: list[CaseObservation], bins: int = 5) -> tuple[float | None, list[dict[str, Any]]]:
    usable = [
        observation
        for observation in observations
        if observation.model_released
        and observation.score_error is not None
        and observation.model_run.confidence is not None
    ]
    if not usable:
        return None, []

    buckets: list[list[tuple[float, float]]] = [[] for _ in range(bins)]
    for observation in usable:
        confidence = min(1.0, max(0.0, float(observation.model_run.confidence or 0.0)))
        score_error = observation.score_error
        if score_error is None:
            raise RuntimeError("Calibration observation is missing its score error")
        accuracy = max(0.0, 1.0 - abs(float(score_error)) / 100.0)
        index = min(bins - 1, int(confidence * bins))
        buckets[index].append((confidence, accuracy))

    details: list[dict[str, Any]] = []
    weighted_gap = 0.0
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        mean_confidence = statistics.fmean(item[0] for item in bucket)
        mean_accuracy = statistics.fmean(item[1] for item in bucket)
        weight = len(bucket) / len(usable)
        weighted_gap += abs(mean_confidence - mean_accuracy) * weight
        details.append(
            {
                "bin": index,
                "count": len(bucket),
                "mean_confidence": round(mean_confidence, 4),
                "mean_normalized_accuracy": round(mean_accuracy, 4),
            }
        )
    return weighted_gap, details


async def load_case_reviews(
    db: AsyncSession, validation_case: ValidationCase
) -> list[ReviewObservation]:
    review_result = await db.execute(
        select(ReviewerAssignment, ExpertReview)
        .join(ExpertReview, ExpertReview.assignment_id == ReviewerAssignment.id)
        .where(
            ReviewerAssignment.validation_case_id == validation_case.id,
            ReviewerAssignment.status == "completed",
            ExpertReview.is_submitted.is_(True),
        )
        .order_by(ExpertReview.submitted_at.asc())
    )
    pairs = review_result.all()
    observations: list[ReviewObservation] = []
    for assignment, review in pairs:
        score_result = await db.execute(
            select(ExpertCriterionScore, RubricCriterion)
            .join(
                RubricCriterion,
                RubricCriterion.id == ExpertCriterionScore.rubric_criterion_id,
            )
            .where(ExpertCriterionScore.review_id == review.id)
            .order_by(RubricCriterion.order.asc())
        )
        criterion_scores = {
            criterion.id: {
                "score": float(score.score),
                "criterion_key": criterion.criterion_key,
                "criterion": criterion.criterion,
                "category": criterion.category,
                "maximum": float(criterion.maximum),
                "confidence": score.confidence,
                "evidence_coverage": score.evidence_coverage,
                "page_references": score.page_references or [],
            }
            for score, criterion in score_result.all()
        }
        if review.total_score is None:
            continue
        observations.append(
            ReviewObservation(
                review_id=review.id,
                assignment_id=assignment.id,
                total_score=float(review.total_score),
                recommendation=review.recommendation,
                criterion_scores=criterion_scores,
            )
        )
    return observations


async def _model_criterion_scores(
    db: AsyncSession, model_run_id: str
) -> dict[str, dict[str, Any]]:
    result = await db.execute(
        select(CriterionPrediction, RubricCriterion)
        .join(
            RubricCriterion,
            RubricCriterion.id == CriterionPrediction.rubric_criterion_id,
        )
        .where(CriterionPrediction.model_run_id == model_run_id)
    )
    return {
        criterion.id: {
            "criterion_key": criterion.criterion_key,
            "criterion": criterion.criterion,
            "category": criterion.category,
            "maximum": float(prediction.maximum_score),
            "score": float(prediction.awarded_score)
            if prediction.awarded_score is not None
            else None,
            "released": bool(prediction.released),
            "status": prediction.criterion_status,
        }
        for prediction, criterion in result.all()
    }


async def build_case_observation(
    db: AsyncSession, study: ValidationStudy, validation_case: ValidationCase
) -> CaseObservation | None:
    reviews = await load_case_reviews(db, validation_case)
    if len(reviews) < study.minimum_reviews_per_case:
        validation_case.status = "under_review" if reviews else "queued"
        return None

    consensus_total, consensus_recommendation, consensus_criteria, agreement = (
        consensus_from_reviews(reviews)
    )
    model_run_result = await db.execute(
        select(ModelRun).where(ModelRun.id == validation_case.model_run_id)
    )
    model_run = model_run_result.scalar_one()
    model_released = (
        model_run.status == "completed"
        and model_run.scoring_status == "released"
        and model_run.total_score is not None
    )
    model_total = (
        float(model_run.total_score)
        if model_released and model_run.total_score is not None
        else None
    )
    score_error = model_total - consensus_total if model_total is not None else None
    model_recommendation = recommendation_from_score(
        model_total, study.recommendation_policy or {}
    )
    expert_recommendation = consensus_recommendation or recommendation_from_score(
        consensus_total, study.recommendation_policy or {}
    )
    recommendation_agreement = (
        model_recommendation == expert_recommendation
        if model_recommendation and expert_recommendation
        else None
    )

    model_criteria = await _model_criterion_scores(db, model_run.id)
    criterion_errors: dict[str, float] = {}
    for criterion_id, consensus in consensus_criteria.items():
        prediction = model_criteria.get(criterion_id)
        if not prediction or prediction["score"] is None or not prediction["released"]:
            continue
        criterion_errors[criterion_id] = float(prediction["score"]) - float(
            consensus["score"]
        )

    return CaseObservation(
        case=validation_case,
        model_run=model_run,
        reviews=reviews,
        consensus_total=consensus_total,
        consensus_recommendation=expert_recommendation,
        consensus_criteria=consensus_criteria,
        agreement_metrics=agreement,
        model_released=model_released,
        model_total=model_total,
        score_error=score_error,
        model_recommendation=model_recommendation,
        recommendation_agreement=recommendation_agreement,
        criterion_errors=criterion_errors,
    )


async def persist_case_observation(
    db: AsyncSession, observation: CaseObservation
) -> None:
    consensus_result = await db.execute(
        select(ValidationConsensus).where(
            ValidationConsensus.validation_case_id == observation.case.id
        )
    )
    consensus = consensus_result.scalar_one_or_none()
    if consensus is None:
        consensus = ValidationConsensus(validation_case_id=observation.case.id)
        db.add(consensus)
    consensus.expert_total_score = observation.consensus_total
    consensus.expert_recommendation = observation.consensus_recommendation
    consensus.reviewer_count = len(observation.reviews)
    consensus.consensus_method = "mean_of_blind_reviews"
    consensus.criterion_scores = observation.consensus_criteria
    consensus.agreement_metrics = observation.agreement_metrics
    consensus.computed_at = datetime.now(timezone.utc)

    comparison_result = await db.execute(
        select(ShadowComparison).where(
            ShadowComparison.validation_case_id == observation.case.id
        )
    )
    comparison = comparison_result.scalar_one_or_none()
    if comparison is None:
        comparison = ShadowComparison(validation_case_id=observation.case.id)
        db.add(comparison)
    comparison.model_total_score = observation.model_total
    comparison.expert_total_score = observation.consensus_total
    comparison.score_error = observation.score_error
    comparison.absolute_error = (
        abs(observation.score_error) if observation.score_error is not None else None
    )
    comparison.squared_error = (
        observation.score_error**2 if observation.score_error is not None else None
    )
    comparison.model_scoring_status = observation.model_run.scoring_status
    comparison.model_released = observation.model_released
    comparison.model_recommendation = observation.model_recommendation
    comparison.expert_recommendation = observation.consensus_recommendation
    comparison.recommendation_agreement = observation.recommendation_agreement
    comparison.model_confidence = observation.model_run.confidence
    comparison.model_information_sufficiency = (
        observation.model_run.information_sufficiency
    )
    comparison.details = {
        "criterion_errors": observation.criterion_errors,
        "review_ids": [review.review_id for review in observation.reviews],
        "model_run_id": observation.model_run.id,
    }
    comparison.computed_at = datetime.now(timezone.utc)

    observation.case.status = "compared"
    observation.case.comparison_ready_at = datetime.now(timezone.utc)


def _metrics_for_partition(
    observations: list[CaseObservation], total_cases: int
) -> list[tuple[str, float | None, int, dict[str, Any]]]:
    compared = len(observations)
    released = [observation for observation in observations if observation.model_released]
    errors = [
        float(observation.score_error)
        for observation in released
        if observation.score_error is not None
    ]
    model_scores = [
        float(observation.model_total)
        for observation in released
        if observation.model_total is not None
    ]
    expert_scores = [
        float(observation.consensus_total)
        for observation in released
        if observation.model_total is not None
    ]
    pairwise_mae = [
        float(observation.agreement_metrics["pairwise_total_mae"])
        for observation in observations
        if observation.agreement_metrics.get("pairwise_total_mae") is not None
    ]
    recommendation_values = [
        1.0 if observation.recommendation_agreement else 0.0
        for observation in observations
        if observation.recommendation_agreement is not None
    ]
    ece, ece_details = _calibration_ece(observations)

    metrics: list[tuple[str, float | None, int, dict[str, Any]]] = [
        ("cases_total", float(total_cases), total_cases, {}),
        ("cases_compared", float(compared), compared, {}),
        (
            "comparison_completion_rate",
            compared / total_cases if total_cases else None,
            total_cases,
            {},
        ),
        (
            "model_release_rate",
            len(released) / compared if compared else None,
            compared,
            {},
        ),
        (
            "model_abstention_or_withhold_rate",
            (compared - len(released)) / compared if compared else None,
            compared,
            {},
        ),
        ("total_score_mae", _mean(abs(error) for error in errors), len(errors), {}),
        ("total_score_rmse", _rmse(errors), len(errors), {}),
        ("total_score_bias_model_minus_expert", _mean(errors), len(errors), {}),
        (
            "score_within_5_points_rate",
            _mean(1.0 if abs(error) <= 5 else 0.0 for error in errors),
            len(errors),
            {},
        ),
        (
            "score_within_10_points_rate",
            _mean(1.0 if abs(error) <= 10 else 0.0 for error in errors),
            len(errors),
            {},
        ),
        ("pearson_score_correlation", pearson_correlation(model_scores, expert_scores), len(model_scores), {}),
        ("spearman_rank_correlation", spearman_correlation(model_scores, expert_scores), len(model_scores), {}),
        ("expert_pairwise_mae", _mean(pairwise_mae), len(pairwise_mae), {}),
        (
            "material_disagreement_rate",
            _mean(
                1.0
                if observation.agreement_metrics.get("material_disagreement")
                else 0.0
                for observation in observations
            ),
            len(observations),
            {
                "threshold": "total-score range >= 15 or recommendation disagreement",
                "interpretation": "flag for institutional adjudication before training-label approval",
            },
        ),
        (
            "recommendation_agreement_rate",
            _mean(recommendation_values),
            len(recommendation_values),
            {"requires_explicit_study_recommendation_policy": True},
        ),
        (
            "confidence_calibration_ece_proxy",
            ece,
            len([o for o in observations if o.model_run.confidence is not None]),
            {"bins": ece_details, "interpretation": "observational proxy, not certification"},
        ),
    ]

    criterion_errors: dict[str, list[float]] = defaultdict(list)
    criterion_labels: dict[str, str] = {}
    for observation in observations:
        for criterion_id, error in observation.criterion_errors.items():
            criterion_errors[criterion_id].append(error)
            consensus = observation.consensus_criteria.get(criterion_id, {})
            criterion_labels[criterion_id] = (
                consensus.get("criterion_key")
                or consensus.get("criterion")
                or criterion_id
            )
    for criterion_id, values in sorted(criterion_errors.items()):
        metrics.append(
            (
                f"criterion_mae:{criterion_labels[criterion_id]}",
                _mean(abs(value) for value in values),
                len(values),
                {"criterion_id": criterion_id},
            )
        )
    return metrics


async def compute_study_metrics(
    db: AsyncSession, study: ValidationStudy
) -> tuple[str, list[CaseObservation], list[str], int]:
    case_result = await db.execute(
        select(ValidationCase)
        .where(
            ValidationCase.study_id == study.id,
            ValidationCase.status != "excluded",
        )
        .order_by(ValidationCase.included_at.asc())
    )
    cases = list(case_result.scalars().all())
    observations: list[CaseObservation] = []
    warnings: list[str] = []
    for validation_case in cases:
        observation = await build_case_observation(db, study, validation_case)
        if observation is None:
            continue
        await persist_case_observation(db, observation)
        observations.append(observation)

    if len(cases) < 30:
        warnings.append(
            "Fewer than 30 cases are included; metrics are pilot observations, not model validation."
        )
    partition_counts = Counter(case.partition for case in cases)
    if partition_counts.get("external_test", 0) == 0:
        warnings.append("No external-test cases are present.")
    if partition_counts.get("shadow", 0) == 0:
        warnings.append("No shadow-pilot cases are present.")
    if len(observations) < len(cases):
        warnings.append(
            "Some cases do not yet have the required number of completed blind expert reviews."
        )
    disagreement_count = sum(
        bool(observation.agreement_metrics.get("material_disagreement"))
        for observation in observations
    )
    if disagreement_count:
        warnings.append(
            f"{disagreement_count} compared case(s) have material expert disagreement; "
            "institutional adjudication is recommended before using those labels for training."
        )
    if not study.recommendation_policy:
        warnings.append(
            "No study-specific recommendation bands are configured; recommendation agreement is not computed."
        )

    snapshot_group_id = uuid.uuid4().hex
    await db.execute(
        delete(ValidationMetricSnapshot).where(
            ValidationMetricSnapshot.study_id == study.id,
            ValidationMetricSnapshot.snapshot_group_id == snapshot_group_id,
        )
    )

    metrics_written = 0
    partitions = ["all", "development", "internal_test", "external_test", "shadow"]
    for partition in partitions:
        partition_cases = cases if partition == "all" else [case for case in cases if case.partition == partition]
        partition_observations = (
            observations
            if partition == "all"
            else [observation for observation in observations if observation.case.partition == partition]
        )
        if not partition_cases and partition != "all":
            continue
        for name, value, sample_size, details in _metrics_for_partition(
            partition_observations, len(partition_cases)
        ):
            db.add(
                ValidationMetricSnapshot(
                    study_id=study.id,
                    snapshot_group_id=snapshot_group_id,
                    partition=partition,
                    metric_name=name,
                    metric_value=value,
                    sample_size=sample_size,
                    details=details,
                )
            )
            metrics_written += 1

    await db.flush()
    return snapshot_group_id, observations, warnings, metrics_written


async def latest_study_metrics(
    db: AsyncSession, study_id: str
) -> tuple[str | None, datetime | None, list[ValidationMetricSnapshot]]:
    group_result = await db.execute(
        select(
            ValidationMetricSnapshot.snapshot_group_id,
            ValidationMetricSnapshot.computed_at,
        )
        .where(ValidationMetricSnapshot.study_id == study_id)
        .order_by(ValidationMetricSnapshot.computed_at.desc())
        .limit(1)
    )
    row = group_result.first()
    if row is None:
        return None, None, []
    snapshot_group_id, computed_at = row
    metric_result = await db.execute(
        select(ValidationMetricSnapshot)
        .where(
            ValidationMetricSnapshot.study_id == study_id,
            ValidationMetricSnapshot.snapshot_group_id == snapshot_group_id,
        )
        .order_by(
            ValidationMetricSnapshot.partition.asc(),
            ValidationMetricSnapshot.metric_name.asc(),
        )
    )
    return snapshot_group_id, computed_at, list(metric_result.scalars().all())


async def validation_readiness(
    db: AsyncSession, study: ValidationStudy
) -> dict[str, Any]:
    case_result = await db.execute(
        select(ValidationCase).where(
            ValidationCase.study_id == study.id,
            ValidationCase.status != "excluded",
        )
    )
    cases = list(case_result.scalars().all())
    assignment_result = await db.execute(
        select(ReviewerAssignment).where(
            ReviewerAssignment.validation_case_id.in_([case.id for case in cases])
        )
        if cases
        else select(ReviewerAssignment).where(false())
    )
    assignments = list(assignment_result.scalars().all()) if cases else []
    completed_reviews = sum(1 for assignment in assignments if assignment.status == "completed")
    compared_cases = sum(1 for case in cases if case.status == "compared")
    consensus_result = await db.execute(
        select(ValidationConsensus).where(
            ValidationConsensus.validation_case_id.in_([case.id for case in cases])
        )
        if cases
        else select(ValidationConsensus).where(false())
    )
    consensus_records = list(consensus_result.scalars().all()) if cases else []
    material_disagreements = sum(
        bool((record.agreement_metrics or {}).get("material_disagreement"))
        for record in consensus_records
    )
    partition_counts = Counter(case.partition for case in cases)
    warnings: list[str] = []
    if len(cases) < 30:
        warnings.append("Pilot sample is below the minimum size for a credible internal validation claim.")
    if partition_counts.get("external_test", 0) == 0:
        warnings.append("External test partition is empty.")
    if compared_cases < len(cases):
        warnings.append("Not all cases have completed the required blind-review comparison.")
    if material_disagreements:
        warnings.append(
            f"{material_disagreements} case(s) have material expert disagreement and "
            "should be adjudicated before training-label approval."
        )
    if study.status not in {"frozen", "completed"}:
        warnings.append("Study is not frozen; cases or labels may still change.")
    return {
        "scientifically_validated": False,
        "status": "pilot_observational" if cases else "not_started",
        "warnings": warnings,
        "total_cases": len(cases),
        "compared_cases": compared_cases,
        "completed_reviews": completed_reviews,
        "minimum_reviews_per_case": study.minimum_reviews_per_case,
        "partitions": dict(partition_counts),
    }


async def export_study_jsonl(
    db: AsyncSession,
    study: ValidationStudy,
    *,
    include_evidence: bool = False,
) -> str:
    case_result = await db.execute(
        select(ValidationCase, Proposal, ProposalVersion, ModelRun)
        .join(Proposal, Proposal.id == ValidationCase.proposal_id)
        .join(ProposalVersion, ProposalVersion.id == ValidationCase.proposal_version_id)
        .join(ModelRun, ModelRun.id == ValidationCase.model_run_id)
        .where(ValidationCase.study_id == study.id)
        .order_by(ValidationCase.included_at.asc())
    )
    lines: list[str] = []
    for validation_case, proposal, version, model_run in case_result.all():
        reviews = await load_case_reviews(db, validation_case)
        consensus_result = await db.execute(
            select(ValidationConsensus).where(
                ValidationConsensus.validation_case_id == validation_case.id
            )
        )
        consensus = consensus_result.scalar_one_or_none()
        comparison_result = await db.execute(
            select(ShadowComparison).where(
                ShadowComparison.validation_case_id == validation_case.id
            )
        )
        comparison = comparison_result.scalar_one_or_none()
        payload: dict[str, Any] = {
            "schema_version": "mulyankan-expert-grounded-record-v1",
            "study": {
                "id": study.id,
                "name": study.name,
                "protocol_version": study.protocol_version,
                "annotation_rulebook_version": study.annotation_rulebook_version,
                "model_version_id": study.model_version_id,
                "model_artifact_hash": study.model_artifact_hash,
                "rubric_version_id": study.rubric_version_id,
                "rubric_definition_hash": study.rubric_definition_hash,
                "shadow_mode": study.shadow_mode,
            },
            "case": {
                "id": validation_case.id,
                "partition": validation_case.partition,
                "status": validation_case.status,
            },
            "proposal": {
                "id": proposal.id,
                "version_id": version.id,
                "version_number": version.version_number,
                "title": version.title,
                "package_hash": version.package_hash,
                "content_hash": version.content_hash,
                "structured_data": version.structured_data if include_evidence else None,
            },
            "model_run": {
                "id": model_run.id,
                "model_version_id": model_run.model_version_id,
                "status": model_run.status,
                "scoring_status": model_run.scoring_status,
                "total_score": model_run.total_score,
                "diagnostic_score": model_run.diagnostic_score,
                "confidence": model_run.confidence,
                "information_sufficiency": model_run.information_sufficiency,
                "input_checksum": model_run.input_checksum,
                "output_checksum": model_run.output_checksum,
            },
            "expert_reviews": [
                {
                    "review_id": review.review_id,
                    "assignment_id": review.assignment_id,
                    "total_score": review.total_score,
                    "recommendation": review.recommendation,
                    "criterion_scores": review.criterion_scores,
                }
                for review in reviews
            ],
            "consensus": {
                "total_score": consensus.expert_total_score,
                "recommendation": consensus.expert_recommendation,
                "reviewer_count": consensus.reviewer_count,
                "criterion_scores": consensus.criterion_scores,
                "agreement_metrics": consensus.agreement_metrics,
            }
            if consensus
            else None,
            "comparison": {
                "model_total_score": comparison.model_total_score,
                "expert_total_score": comparison.expert_total_score,
                "absolute_error": comparison.absolute_error,
                "recommendation_agreement": comparison.recommendation_agreement,
                "model_released": comparison.model_released,
            }
            if comparison
            else None,
        }
        lines.append(json.dumps(payload, sort_keys=True, default=str))
    return "\n".join(lines) + ("\n" if lines else "")


async def study_response_data(
    db: AsyncSession, study: ValidationStudy
) -> dict[str, Any]:
    scheme_result = await db.execute(
        select(FundingScheme).where(FundingScheme.id == study.scheme_id)
    )
    scheme = scheme_result.scalar_one()
    rubric_result = await db.execute(
        select(RubricVersion).where(RubricVersion.id == study.rubric_version_id)
    )
    rubric = rubric_result.scalar_one()
    model_result = await db.execute(
        select(ModelVersion).where(ModelVersion.id == study.model_version_id)
    )
    model = model_result.scalar_one()
    case_result = await db.execute(
        select(ValidationCase).where(ValidationCase.study_id == study.id)
    )
    cases = list(case_result.scalars().all())
    return {
        "id": study.id,
        "name": study.name,
        "description": study.description,
        "scheme_id": study.scheme_id,
        "scheme_code": scheme.code,
        "rubric_version_id": study.rubric_version_id,
        "rubric_version": rubric.version,
        "model_version_id": study.model_version_id,
        "model_name": model.model_name,
        "model_version": model.version,
        "model_artifact_hash": study.model_artifact_hash,
        "rubric_definition_hash": study.rubric_definition_hash,
        "protocol_version": study.protocol_version,
        "annotation_rulebook_version": study.annotation_rulebook_version,
        "status": study.status,
        "shadow_mode": study.shadow_mode,
        "minimum_reviews_per_case": study.minimum_reviews_per_case,
        "recommendation_policy": study.recommendation_policy or {},
        "created_by": study.created_by,
        "created_at": study.created_at,
        "activated_at": study.activated_at,
        "frozen_at": study.frozen_at,
        "completed_at": study.completed_at,
        "case_count": len(cases),
        "compared_case_count": sum(case.status == "compared" for case in cases),
    }
