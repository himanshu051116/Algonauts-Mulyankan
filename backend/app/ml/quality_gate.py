"""Versioned no-private-dataset robustness gate for the advisory ML scorer.

The gate protects behavioural promises that can be tested without CMPDI or
historical proposal data. Passing it does not promote a model beyond bootstrap
status and does not validate official scoring quality.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.ml.constants import (
    DATA_DIR,
    MODEL_ARTIFACT_PATH,
    MODEL_EVIDENCE_CONTRACT_PATH,
    MODEL_NAME,
    MODEL_REGISTRY_VERSION,
    MODEL_RUBRIC_PATH,
    MODEL_VERSION,
)
from app.ml.inference import score_proposal_with_ml

DEFAULT_BENCHMARK_PATH = (
    DATA_DIR / "benchmarks" / "no-private-data-advisory-ml-v1.json"
)
EVIDENCE_CONTRACT_PATH = MODEL_EVIDENCE_CONTRACT_PATH


@dataclass(frozen=True)
class QualityCase:
    case_id: str
    group: str
    description: str
    text: str
    expect_abstention: bool
    min_diagnostic_score: float | None = None
    max_diagnostic_score: float | None = None
    min_released_criteria: int | None = None


@dataclass(frozen=True)
class QualityBenchmark:
    benchmark_id: str
    benchmark_version: str
    dataset_requirement: str
    official_decision_validated: bool
    strong_case_id: str
    minimum_margin: float
    cases: tuple[QualityCase, ...]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _optional_float(value: object, *, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"Benchmark field {field} must be numeric")
    return float(value)


def _optional_int(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"Benchmark field {field} must be an integer")
    return value


def _case_text(raw: dict[str, Any], *, case_id: str) -> str:
    value = raw.get("text")
    if isinstance(value, str):
        text = value
    elif isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        text = "\n\n".join(value)
    else:
        raise RuntimeError(f"Benchmark case {case_id} must contain text")
    repeat = raw.get("repeat", 1)
    if isinstance(repeat, bool) or not isinstance(repeat, int) or not 1 <= repeat <= 100:
        raise RuntimeError(f"Benchmark case {case_id} repeat must be between 1 and 100")
    return text * repeat


def load_benchmark(path: Path = DEFAULT_BENCHMARK_PATH) -> QualityBenchmark:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load ML quality benchmark: {path}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("ML quality benchmark root must be an object")
    if raw.get("schema_version") != "1.0":
        raise RuntimeError("Unsupported ML quality benchmark schema")
    if raw.get("official_decision_validated") is not False:
        raise RuntimeError("No-private-data benchmark cannot validate official decisions")

    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise RuntimeError("ML quality benchmark must contain cases")
    cases: list[QualityCase] = []
    seen: set[str] = set()
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise RuntimeError("ML quality benchmark contains a non-object case")
        case_id = str(raw_case.get("id") or "").strip()
        if not case_id or case_id in seen:
            raise RuntimeError(f"ML quality benchmark has an invalid case id: {case_id!r}")
        seen.add(case_id)
        expectation = raw_case.get("expectation")
        if not isinstance(expectation, dict) or not isinstance(
            expectation.get("abstention"), bool
        ):
            raise RuntimeError(f"Benchmark case {case_id} has no abstention expectation")
        cases.append(
            QualityCase(
                case_id=case_id,
                group=str(raw_case.get("group") or "unclassified"),
                description=str(raw_case.get("description") or ""),
                text=_case_text(raw_case, case_id=case_id),
                expect_abstention=expectation["abstention"],
                min_diagnostic_score=_optional_float(
                    expectation.get("minimum_diagnostic_score"),
                    field=f"{case_id}.minimum_diagnostic_score",
                ),
                max_diagnostic_score=_optional_float(
                    expectation.get("maximum_diagnostic_score"),
                    field=f"{case_id}.maximum_diagnostic_score",
                ),
                min_released_criteria=_optional_int(
                    expectation.get("minimum_released_criteria"),
                    field=f"{case_id}.minimum_released_criteria",
                ),
            )
        )

    strong_case_id = str(raw.get("strong_case_id") or "")
    if strong_case_id not in seen:
        raise RuntimeError("ML quality benchmark strong case id is missing")
    minimum_margin = _optional_float(
        raw.get("minimum_strong_to_weak_margin"),
        field="minimum_strong_to_weak_margin",
    )
    if minimum_margin is None or minimum_margin < 0:
        raise RuntimeError("ML quality benchmark margin must be non-negative")

    return QualityBenchmark(
        benchmark_id=str(raw.get("benchmark_id") or ""),
        benchmark_version=str(raw.get("benchmark_version") or ""),
        dataset_requirement=str(raw.get("dataset_requirement") or ""),
        official_decision_validated=False,
        strong_case_id=strong_case_id,
        minimum_margin=minimum_margin,
        cases=tuple(cases),
    )


def _yaml_version(path: Path, field: str) -> str:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get(field) is None:
        raise RuntimeError(f"{path.name} does not declare {field}")
    return str(raw[field])


def _criterion_summaries(result: dict[str, Any]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for category in result.get("category_scores", []):
        if not isinstance(category, dict):
            continue
        for criterion in category.get("criteria", []):
            if not isinstance(criterion, dict):
                continue
            evidence = criterion.get("evidence")
            summaries.append(
                {
                    "criterion_id": criterion.get("criterion_id"),
                    "released": bool(criterion.get("released")),
                    "awarded_score": criterion.get("awarded_score"),
                    "maximum_score": criterion.get("maximum_score"),
                    "criterion_status": criterion.get("criterion_status"),
                    "evidence_count": len(evidence) if isinstance(evidence, list) else 0,
                    "model_confidence_signal": criterion.get("confidence"),
                }
            )
    return summaries


def _case_summary(case: QualityCase, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "case": case.case_id,
        "group": case.group,
        "description": case.description,
        "passed": True,
        "expectation": {
            "abstention": case.expect_abstention,
            "minimum_diagnostic_score": case.min_diagnostic_score,
            "maximum_diagnostic_score": case.max_diagnostic_score,
            "minimum_released_criteria": case.min_released_criteria,
        },
        "expect_abstention": case.expect_abstention,
        "abstention": bool(result.get("abstention")),
        "diagnostic_score": result.get("diagnostic_score"),
        "total_score_released": result.get("total_score") is not None,
        "confidence": result.get("confidence"),
        "model_confidence_signal": result.get("confidence"),
        "evidence_coverage": result.get("evidence_coverage"),
        "released_criterion_count": result.get("released_criterion_count"),
        "abstention_reasons": result.get("abstention_reasons", []),
        "criteria": _criterion_summaries(result),
    }


def _check_case(case: QualityCase, result: dict[str, Any]) -> dict[str, Any]:
    summary = _case_summary(case, result)
    failures: list[str] = []
    diagnostic = float(result.get("diagnostic_score") or 0.0)
    released = int(result.get("released_criterion_count") or 0)

    if bool(result.get("abstention")) is not case.expect_abstention:
        failures.append(
            f"expected abstention={case.expect_abstention}, got {result.get('abstention')}"
        )
    if case.min_diagnostic_score is not None and diagnostic < case.min_diagnostic_score:
        failures.append(
            f"diagnostic score {diagnostic:.1f} is below {case.min_diagnostic_score:.1f}"
        )
    if case.max_diagnostic_score is not None and diagnostic > case.max_diagnostic_score:
        failures.append(
            f"diagnostic score {diagnostic:.1f} is above {case.max_diagnostic_score:.1f}"
        )
    if case.min_released_criteria is not None and released < case.min_released_criteria:
        failures.append(
            f"released criteria {released} is below {case.min_released_criteria}"
        )

    if failures:
        summary["passed"] = False
        summary["failures"] = failures
    return summary


async def run_quality_gate(
    benchmark_path: Path | None = None,
) -> dict[str, Any]:
    """Run deterministic behavioural checks that do not need private data."""

    path = (benchmark_path or DEFAULT_BENCHMARK_PATH).resolve()
    benchmark = load_benchmark(path)
    case_results: list[dict[str, Any]] = []
    for case in benchmark.cases:
        result = await score_proposal_with_ml("MOC-ST", case.text, "2.0")
        case_results.append(_check_case(case, result))

    strong = next(
        item for item in case_results if item["case"] == benchmark.strong_case_id
    )
    weak_cases = [
        item for item in case_results if item["case"] != benchmark.strong_case_id
    ]
    weak_scores = [float(item.get("diagnostic_score") or 0.0) for item in weak_cases]
    margin = float(strong.get("diagnostic_score") or 0.0) - max(weak_scores or [0.0])
    margin_passed = margin >= benchmark.minimum_margin

    if not margin_passed:
        case_results.append(
            {
                "case": "strong_vs_weak_margin",
                "group": "cross_case_invariant",
                "passed": False,
                "failures": [
                    f"strong diagnostic margin {margin:.1f} is below "
                    f"{benchmark.minimum_margin:.1f}"
                ],
            }
        )

    passed = all(bool(item.get("passed")) for item in case_results)
    rubric_version = _yaml_version(MODEL_RUBRIC_PATH, "rubric_version")
    contract_version = _yaml_version(EVIDENCE_CONTRACT_PATH, "contract_version")
    report: dict[str, Any] = {
        "report_schema_version": "1.0",
        "deterministic_report": True,
        "passed": passed,
        "quality_gate": benchmark.benchmark_id,
        "dataset_requirement": benchmark.dataset_requirement,
        "official_decision_validated": False,
        "model": {
            "name": MODEL_NAME,
            "artifact_version": MODEL_VERSION,
            "inference_policy_version": MODEL_REGISTRY_VERSION,
            "artifact_path": str(MODEL_ARTIFACT_PATH.relative_to(DATA_DIR.parent)).replace(
                "\\", "/"
            ),
            "artifact_sha256": _file_sha256(MODEL_ARTIFACT_PATH),
        },
        "benchmark": {
            "id": benchmark.benchmark_id,
            "version": benchmark.benchmark_version,
            "path": str(path.relative_to(DATA_DIR.parent)).replace("\\", "/")
            if path.is_relative_to(DATA_DIR.parent)
            else str(path),
            "sha256": _file_sha256(path),
            "case_count": len(benchmark.cases),
            "minimum_strong_to_weak_margin": benchmark.minimum_margin,
        },
        "rubric": {
            "version": rubric_version,
            "sha256": _file_sha256(MODEL_RUBRIC_PATH),
        },
        "evidence_contract": {
            "version": contract_version,
            "sha256": _file_sha256(EVIDENCE_CONTRACT_PATH),
        },
        "margin_strong_minus_max_weak": round(margin, 3),
        "cases": case_results,
        "promotion": {
            "current_state": "bootstrap",
            "recommended_state": "bootstrap",
            "decision": (
                "retain_bootstrap_advisory"
                if passed
                else "reject_candidate_due_to_quality_gate_failure"
            ),
            "eligible_for_official_decision_use": False,
            "reason": (
                "Behavioural robustness passed, but no expert-labelled institutional "
                "outcomes were used."
                if passed
                else "One or more required behavioural checks failed."
            ),
        },
    }
    report["report_sha256"] = _canonical_sha256(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print full JSON output")
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=DEFAULT_BENCHMARK_PATH,
        help="versioned benchmark JSON path",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write the deterministic model-quality report to this path",
    )
    args = parser.parse_args()

    result = asyncio.run(run_quality_gate(args.benchmark))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        status = "PASSED" if result["passed"] else "FAILED"
        print(f"{status}: {result['quality_gate']}")
        print(f"report SHA-256: {result['report_sha256']}")
        print(f"strong-minus-weak margin: {result['margin_strong_minus_max_weak']}")
        for case in result["cases"]:
            print(
                f"- {case['case']}: {'PASS' if case['passed'] else 'FAIL'} "
                f"score={case.get('diagnostic_score')} abstention={case.get('abstention')}"
            )
            for failure in case.get("failures", []):
                print(f"  reason: {failure}")
        if args.output:
            print(f"report written to: {args.output}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
