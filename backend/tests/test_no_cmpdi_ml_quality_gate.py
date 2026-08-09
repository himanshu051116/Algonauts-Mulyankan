"""No-CMPDI ML quality gate tests.

These tests do not claim institutional validation. They protect the advisory
model against obvious regressions when only brochure/bootstrap data is
available.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

from app.ml.quality_gate import (
    DEFAULT_BENCHMARK_PATH,
    load_benchmark,
    run_quality_gate,
)


def _run_gate():
    return asyncio.run(run_quality_gate())


def test_no_private_dataset_quality_gate_passes():
    result = _run_gate()

    assert result["passed"] is True
    assert result["dataset_requirement"].startswith("none")
    assert result["official_decision_validated"] is False
    assert result["margin_strong_minus_max_weak"] >= 15.0


def test_no_private_dataset_gate_keeps_weak_cases_abstained():
    result = _run_gate()
    cases = {item["case"]: item for item in result["cases"]}

    assert cases["evidence_rich_public_synthetic"]["abstention"] is False
    for case_name in [
        "weak_public_synthetic",
        "generic_non_coal",
        "contradictory_claims",
        "keyword_stuffing",
    ]:
        assert cases[case_name]["passed"] is True
        assert cases[case_name]["abstention"] is True
        assert cases[case_name]["total_score_released"] is False


def test_quality_gate_uses_a_versioned_external_benchmark():
    benchmark = load_benchmark()

    assert DEFAULT_BENCHMARK_PATH.is_file()
    assert benchmark.benchmark_id == "no-private-dataset-advisory-ml-v1"
    assert benchmark.benchmark_version == "1.0.0"
    assert len(benchmark.cases) == 5
    assert benchmark.official_decision_validated is False


def test_quality_report_has_reproducible_provenance_and_stays_bootstrap():
    result = _run_gate()

    assert len(result["model"]["artifact_sha256"]) == 64
    assert len(result["benchmark"]["sha256"]) == 64
    assert len(result["rubric"]["sha256"]) == 64
    assert len(result["evidence_contract"]["sha256"]) == 64
    assert result["benchmark"]["case_count"] == 5
    assert result["promotion"]["recommended_state"] == "bootstrap"
    assert result["promotion"]["eligible_for_official_decision_use"] is False

    strong = next(
        case
        for case in result["cases"]
        if case["case"] == "evidence_rich_public_synthetic"
    )
    assert len(strong["criteria"]) == 23
    assert all("evidence_count" in criterion for criterion in strong["criteria"])

    report_hash = result["report_sha256"]
    payload = dict(result)
    del payload["report_sha256"]
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert report_hash == hashlib.sha256(canonical).hexdigest()
