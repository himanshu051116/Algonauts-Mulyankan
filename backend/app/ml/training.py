"""Training utilities for the brochure-aligned Mulyankan NLP scorer.

The release artifact is intentionally stored as numeric ``.npz`` arrays plus
JSON metadata.  It does not use pickle/joblib, so loading the packaged model
cannot execute arbitrary Python code and does not depend on scikit-learn's
private pickle layout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import scipy
import sklearn
import yaml
from scipy.stats import spearmanr
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import FeatureUnion

from app.ml.bootstrap import generate_records
from app.ml.constants import MODEL_FORMAT_VERSION, MODEL_NAME, MODEL_VERSION

RANDOM_SEED = 20260706
PROJECT_ROOT = Path(__file__).resolve().parents[3]
LEVEL_RATIOS = np.asarray([0.03, 0.28, 0.63, 0.91], dtype=np.float64)
WORD_FEATURES = 4096
CHAR_FEATURES = 4096


def build_feature_transformer() -> FeatureUnion:
    """Create the stateless, version-tolerant feature transformer."""

    return FeatureUnion(
        [
            (
                "word",
                HashingVectorizer(
                    lowercase=True,
                    strip_accents="unicode",
                    stop_words="english",
                    ngram_range=(1, 2),
                    n_features=WORD_FEATURES,
                    alternate_sign=False,
                    norm="l2",
                ),
            ),
            (
                "char",
                HashingVectorizer(
                    analyzer="char_wb",
                    lowercase=True,
                    ngram_range=(3, 5),
                    n_features=CHAR_FEATURES,
                    alternate_sign=False,
                    norm="l2",
                ),
            ),
        ]
    )


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Dataset line {line_number} is not an object")
            records.append(value)
    if not records:
        raise ValueError("Training dataset is empty")
    return records


def _rubric_targets(rubric_path: Path) -> tuple[str, list[str], list[float]]:
    data = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Rubric root must be a mapping")
    criterion_ids: list[str] = []
    maxima: list[float] = []
    categories = data.get("categories", [])
    if not isinstance(categories, list):
        raise ValueError("Rubric categories must be a list")
    for category in categories:
        if not isinstance(category, dict):
            raise ValueError("Rubric category must be a mapping")
        criteria = category.get("criteria", [])
        if not isinstance(criteria, list):
            raise ValueError("Rubric criteria must be a list")
        for criterion in criteria:
            if not isinstance(criterion, dict):
                raise ValueError("Rubric criterion must be a mapping")
            criterion_ids.append(str(criterion["id"]))
            maxima.append(float(criterion["maximum"]))
    if round(sum(maxima), 6) != float(data.get("total_marks", 100)):
        raise ValueError("Criterion maxima do not sum to rubric total")
    return str(data.get("rubric_version", "")), criterion_ids, maxima


def _dataset_fingerprint(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _criterion_level(record: dict[str, Any], criterion_id: str, maximum: float) -> int:
    level_map = record.get("generation_levels")
    if isinstance(level_map, dict) and criterion_id in level_map:
        level = int(level_map[criterion_id])
        if 0 <= level <= 3:
            return level
        raise ValueError(f"Criterion {criterion_id} has invalid ordinal level {level}")

    score_map = record.get("criterion_scores")
    if not isinstance(score_map, dict) or criterion_id not in score_map:
        raise ValueError(
            f"Training record {record.get('record_id', '<unknown>')} lacks a label for {criterion_id}"
        )
    score = float(score_map[criterion_id])
    if not 0.0 <= score <= maximum:
        raise ValueError(f"Criterion {criterion_id} score {score} is outside [0, {maximum}]")
    ratio = score / maximum if maximum else 0.0
    if ratio < 0.10:
        return 0
    if ratio < 0.45:
        return 1
    if ratio < 0.78:
        return 2
    return 3


def _new_classifier() -> SGDClassifier:
    return SGDClassifier(
        loss="log_loss",
        alpha=0.0002,
        max_iter=1500,
        tol=1e-4,
        class_weight="balanced",
        random_state=RANDOM_SEED,
        average=True,
    )


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exp = np.exp(shifted)
    probabilities = exp / np.sum(exp, axis=1, keepdims=True)
    return np.asarray(probabilities, dtype=np.float64)


def train_model(
    dataset_path: Path,
    rubric_path: Path,
    output_dir: Path,
    *,
    additional_dataset_paths: list[Path] | None = None,
) -> dict[str, Any]:
    rubric_version, criterion_ids, maxima = _rubric_targets(rubric_path)
    dataset_paths = [dataset_path, *(additional_dataset_paths or [])]
    records: list[dict[str, Any]] = []
    for path in dataset_paths:
        records.extend(_load_jsonl(path))

    groups = [
        str(record.get("proposal_group", f"record-{index}"))
        for index, record in enumerate(records)
    ]
    origins = {str(record.get("label_origin", "unknown")) for record in records}
    indices = np.arange(len(records))
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.20, random_state=RANDOM_SEED)
    train_idx, test_idx = next(splitter.split(indices, groups=groups))

    transformer = build_feature_transformer()
    feature_stats: dict[str, dict[str, float | int]] = {}
    per_criterion_mae: dict[str, float] = {}
    per_criterion_accuracy: dict[str, float] = {}
    all_true_scores: list[np.ndarray] = []
    all_predicted_scores: list[np.ndarray] = []
    arrays: dict[str, np.ndarray] = {}

    for criterion_id, maximum in zip(criterion_ids, maxima, strict=True):
        snippets: list[str] = []
        levels: list[int] = []
        for record_index, record in enumerate(records):
            evidence_map = record.get("criterion_evidence")
            snippet = (
                str(evidence_map.get(criterion_id, "")).strip()
                if isinstance(evidence_map, dict)
                else ""
            )
            if not snippet:
                snippet = str(record.get("text", "")).strip()
            snippets.append(snippet or "No supporting evidence was supplied for this criterion.")
            try:
                levels.append(_criterion_level(record, criterion_id, maximum))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid training record {record_index}: {exc}") from exc

        train_texts = [snippets[int(index)] for index in train_idx]
        test_texts = [snippets[int(index)] for index in test_idx]
        x_train = transformer.transform(train_texts)
        x_test = transformer.transform(test_texts)
        y = np.asarray(levels, dtype=np.int64)
        classifier = _new_classifier()
        classifier.fit(x_train, y[train_idx])

        logits = np.asarray(x_test @ classifier.coef_.T) + classifier.intercept_
        probabilities = _softmax(logits)
        classes = np.asarray(classifier.classes_, dtype=np.int64)
        predicted_levels = classes[np.argmax(probabilities, axis=1)]
        expected_ratios = probabilities @ LEVEL_RATIOS[classes]
        true_ratios = LEVEL_RATIOS[y[test_idx]]
        per_criterion_mae[criterion_id] = round(
            float(mean_absolute_error(true_ratios, expected_ratios)), 6
        )
        per_criterion_accuracy[criterion_id] = round(
            float(accuracy_score(y[test_idx], predicted_levels)), 6
        )
        all_true_scores.append(true_ratios * maximum)
        all_predicted_scores.append(expected_ratios * maximum)

        nonzero_counts = np.asarray(x_train.getnnz(axis=1), dtype=float)
        feature_stats[criterion_id] = {
            "median_nonzero": round(float(np.median(nonzero_counts)), 3),
            "p10_nonzero": round(float(np.percentile(nonzero_counts, 10)), 3),
            "feature_count": int(x_train.shape[1]),
        }
        safe_id = criterion_id.replace("-", "_")
        arrays[f"coef__{safe_id}"] = np.asarray(classifier.coef_, dtype=np.float32)
        arrays[f"intercept__{safe_id}"] = np.asarray(classifier.intercept_, dtype=np.float32)
        arrays[f"classes__{safe_id}"] = classes.astype(np.int16)

    true_matrix = np.stack(all_true_scores, axis=1)
    predicted_matrix = np.stack(all_predicted_scores, axis=1)
    total_true = true_matrix.sum(axis=1)
    total_predicted = predicted_matrix.sum(axis=1)
    total_spearman = spearmanr(total_true, total_predicted).statistic
    total_spearman_value = (
        float(total_spearman)
        if total_spearman is not None and np.isfinite(total_spearman)
        else 0.0
    )
    weak_only = all(origin == "brochure-derived weak supervision" for origin in origins)
    metrics: dict[str, Any] = {
        "evaluation_scope": (
            "group-held-out brochure-derived weak supervision"
            if weak_only
            else "group-held-out mixed expert and weak-supervision data"
        ),
        "metric_interpretation": (
            "pipeline regression/sanity metrics only; not real-world selection accuracy"
            if weak_only
            else "development metrics; institutional temporal validation still required"
        ),
        "official_decision_validated": False,
        "calibrated_on_expert_outcomes": False,
        "trained_model": True,
        "train_rows": int(len(train_idx)),
        "test_rows": int(len(test_idx)),
        "criterion_mean_mae_ratio": round(float(np.mean(list(per_criterion_mae.values()))), 6),
        "criterion_mean_level_accuracy": round(
            float(np.mean(list(per_criterion_accuracy.values()))), 6
        ),
        "total_score_mae": round(float(mean_absolute_error(total_true, total_predicted)), 4),
        "total_score_rmse": round(float(mean_squared_error(total_true, total_predicted) ** 0.5), 4),
        "total_score_r2": round(float(r2_score(total_true, total_predicted)), 6),
        "total_score_spearman": round(total_spearman_value, 6),
        "per_criterion_mae_ratio": per_criterion_mae,
        "per_criterion_level_accuracy": per_criterion_accuracy,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    # NumPy's type stubs do not model named array payloads accurately.
    np.savez_compressed(output_dir / "model.npz", **arrays)  # type: ignore[arg-type]
    metadata: dict[str, Any] = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "format_version": MODEL_FORMAT_VERSION,
        "rubric_version": rubric_version,
        "criterion_ids": criterion_ids,
        "criterion_maxima": maxima,
        "level_ratios": LEVEL_RATIOS.tolist(),
        "training_rows": len(records),
        "criterion_training_examples": len(records) * len(criterion_ids),
        "training_origins": sorted(origins),
        "dataset_sha256": _dataset_fingerprint(dataset_paths),
        "dataset_files": [path.name for path in dataset_paths],
        "random_seed": RANDOM_SEED,
        "feature_stats": feature_stats,
        "feature_config": {
            "word_features": WORD_FEATURES,
            "char_features": CHAR_FEATURES,
            "total_features": WORD_FEATURES + CHAR_FEATURES,
            "alternate_sign": False,
        },
        "training_runtime": {
            "python_implementation": "CPython",
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "metrics": metrics,
    }
    model_card = {
        **metadata,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "architecture": (
            "23 criterion-specific stateless word/character hashing vectorizers and "
            "averaged SGD logistic classifiers, exported as non-pickle numeric arrays"
        ),
        "artifact_security": {
            "pickle_free": True,
            "numpy_allow_pickle_required": False,
            "reason": "prevents executable model deserialisation and private sklearn pickle incompatibility",
        },
        "intended_use": (
            "Advisory preliminary scoring and ML workflow validation under mandatory human review."
        ),
        "limitations": [
            "The packaged model is trained on brochure-derived weak-supervision records, not historical institutional decisions.",
            "Hold-out metrics are pipeline regression checks and do not establish real-world proposal-selection accuracy.",
            "Reliability values are evidence and coverage indicators, not statistically calibrated probabilities.",
            "Hard eligibility checks remain deterministic and the scorer abstains when evidence or coverage is weak.",
            "Production use requires expert-labelled historical proposals, temporal/institution-held-out validation, calibration, bias review, and shadow deployment.",
        ],
        "governance": {
            "advisory_only": True,
            "official_decision_validated": False,
            "confidence_type": "uncalibrated_reliability_indicator",
            "recommended_ai_weight": 0.45,
            "recommended_expert_weight": 0.55,
        },
    }
    (output_dir / "model_card.json").write_text(
        json.dumps(model_card, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return model_card


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the Mulyankan brochure-aligned ML scorer")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "data/training/moc-brochure-bootstrap-v1.jsonl",
    )
    parser.add_argument(
        "--rubric",
        type=Path,
        default=PROJECT_ROOT / "data/rules/moc-st-100-mark-rubric-v2.yaml",
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=PROJECT_ROOT / "data/training/moc-brochure-weak-label-spec-v1.yaml",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data/models" / MODEL_NAME,
    )
    parser.add_argument(
        "--expert-dataset",
        type=Path,
        action="append",
        default=[],
        help="Optional expert/adjudicated JSONL dataset; may be supplied more than once",
    )
    parser.add_argument("--regenerate-bootstrap", action="store_true")
    args = parser.parse_args()
    if args.regenerate_bootstrap or not args.dataset.exists():
        generate_records(args.rubric, args.spec, args.dataset)
    card = train_model(
        args.dataset,
        args.rubric,
        args.output_dir,
        additional_dataset_paths=args.expert_dataset,
    )
    print(json.dumps(card, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
