"""Regression tests for the brochure-aligned trained Mulyankan model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from app.ml.constants import (
    MODEL_ARTIFACT_PATH,
    MODEL_CARD_PATH,
    MODEL_NAME,
    MODEL_QUALITY_REPORT_PATH,
    MODEL_REGISTRY_VERSION,
    MODEL_VERSION,
)
from app.ml.inference import load_model_bundle, score_proposal_with_ml
from app.models.proposal import ModelVersion
from app.services.document import extract_structured_fields
from app.services.evaluation_engine import score_with_registered_model
from app.services.field_schema import canonicalize_extracted_fields
from app.services.model_registry import (
    brochure_ml_artifact_hash,
    brochure_ml_metadata,
    brochure_ml_quality_report,
    validate_model_artifact,
)
from app.services.rules import evaluate_rules


STRONG_PROPOSAL = """
Institution Type: startup innovator
Project Duration: 24 months
Thrust Area: alternative-use-clean-coal
Land Purchase: none
Vehicle Purchase: none
Permanent Salary: none
Routine Academic Study: none
Foreign Travel: none
Industry Relevance: A named Coal India subsidiary will host a mine-site pilot and adopt the system after acceptance testing, reducing operating cost and emissions.
Compliance: The project will obtain DGMS approval and environmental permits before field trials and comply with mine-safety regulations.

The technology is distinct from prior Ministry of Coal projects based on a documented patent landscape, prior-art search, literature comparison and research gap. A provisional patent will cover an indigenous sensor-fusion algorithm and replace imported equipment under Make in India. The architecture, process flow, block diagrams, algorithms and validation protocol are specified.

The current technology readiness level is TRL 4 and the target is TRL 6 through laboratory validation, prototype testing and a mine pilot. Existing laboratories, calibrated test rigs, machines, software and computing infrastructure are available. The principal investigator has delivered three coal-industry pilots and the multidisciplinary team has publications, deployments and relevant expertise. Quarterly work-plan milestones, responsibilities, deliverables, acceptance criteria, dependencies and backup paths are defined in a Gantt schedule.

A signed MoU and support letter from a named Coal India subsidiary confirm the deployment site, data access, operators, acceptance authority, technology transfer and post-project adoption. A quantified cost-benefit analysis estimates INR 5 crore annual savings against INR 1 crore deployment cost, 20 percent productivity improvement, reduced downtime and a 14-month payback. Sensitivity analysis covers downside scenarios. The project targets a measured 20 percent emission reduction, 15 percent incident reduction, improved mine safety, waste reduction and water savings. It aligns with Atmanirbhar Bharat, Net Zero, sustainability, circular economy and coal-sector priorities.

The project includes substantive SC/ST researchers, 40 percent women researchers including a woman co-PI, a rural startup, an MSME, a university, CMPDI and a coal PSU in a multi-agency consortium with joint governance and complementary work packages.

The itemised head-wise budget includes quantities, rates, taxes, quotations and cost justification linked to work packages. Phased funding and quarterly fund releases are milestone-linked. Manpower cost is 25 percent of the total budget. ROI assumptions, payback, sensitivity analysis and scaled-deployment economics are provided.

Critical dependencies include equipment supply, site access, data access, permissions, power and partner availability. Each dependency has a risk owner, trigger, alternate supplier, backup site, contingency and recovery action. DGMS approval, environmental clearance, safety approval, procurement compliance and data-security requirements are scheduled before field deployment.
"""

WEAK_PROPOSAL = """
Institution Type: startup
Project Duration: 24 months
Thrust Area: clean coal
The project studies coal using AI. Industry relevance may exist. Rules will be followed.
No technical, economic, team, budget, risk, adoption, or validation evidence is provided.
"""


def test_brochure_rubric_has_six_categories_and_twenty_three_targets():
    rubric = yaml.safe_load(
        Path("data/rules/moc-st-100-mark-rubric-v2.yaml").read_text(encoding="utf-8")
    )
    categories = rubric["categories"]
    criteria = [criterion for category in categories for criterion in category["criteria"]]
    assert len(categories) == 6
    assert len(criteria) == 23
    assert sum(float(criterion["maximum"]) for criterion in criteria) == 100.0


def test_packaged_model_is_trained_and_integrity_checked():
    bundle = load_model_bundle()
    metadata = brochure_ml_metadata()
    quality_report = brochure_ml_quality_report()
    assert bundle["model_name"] == MODEL_NAME
    assert bundle["model_version"] == MODEL_VERSION
    assert bundle["training_rows"] > 0
    assert len(bundle["models"]) == 23
    assert metadata["governance"]["advisory_only"] is True
    assert metadata["metrics"]["official_decision_validated"] is False
    assert MODEL_QUALITY_REPORT_PATH.is_file()
    assert quality_report["passed"] is True
    assert quality_report["promotion"]["recommended_state"] == "bootstrap"
    assert quality_report["promotion"]["eligible_for_official_decision_use"] is False

    model = ModelVersion(
        id="test-brochure-model",
        model_name=MODEL_NAME,
        version=MODEL_REGISTRY_VERSION,
        artifact_hash=brochure_ml_artifact_hash(),
        rubric_version_id="rubric-v2",
        training_rows=int(metadata["training_rows"]),
        test_metrics={"trained_model": True},
        lifecycle_state="bootstrap",
        quality_gate_report_hash=quality_report["report_sha256"],
        is_active=True,
    )
    validate_model_artifact(model)

    model.quality_gate_report_hash = "0" * 64
    with pytest.raises(RuntimeError, match="quality report hash"):
        validate_model_artifact(model)


@pytest.mark.parametrize(
    ("section", "message"),
    [
        ("rubric", "rubric hash is stale"),
        ("evidence_contract", "evidence-contract hash is stale"),
    ],
)
def test_quality_report_rejects_stale_scoring_evidence(
    tmp_path: Path,
    monkeypatch,
    section: str,
    message: str,
):
    from app.services import model_registry

    report = json.loads(MODEL_QUALITY_REPORT_PATH.read_text(encoding="utf-8"))
    report[section]["sha256"] = "0" * 64
    report["report_sha256"] = model_registry._canonical_report_hash(report)
    report_path = tmp_path / "model_quality_gate_report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(model_registry, "MODEL_QUALITY_REPORT_PATH", report_path)

    with pytest.raises(RuntimeError, match=message):
        model_registry.brochure_ml_quality_report()


@pytest.mark.asyncio
async def test_trained_model_separates_evidence_rich_and_weak_proposals():
    strong = await score_proposal_with_ml("MOC-ST", STRONG_PROPOSAL, "2.0")
    weak = await score_proposal_with_ml("MOC-ST", WEAK_PROPOSAL, "2.0")

    assert strong["model_source"] == MODEL_NAME
    assert strong["maximum_score"] == 100.0
    assert len([item for category in strong["category_scores"] for item in category["criteria"]]) == 23
    assert strong["total_score"] is not None
    assert weak["total_score"] is None
    assert strong["diagnostic_score"] > weak["diagnostic_score"] + 20
    assert strong["confidence"] > weak["confidence"]
    assert strong["abstention"] is False
    assert weak["abstention"] is True
    assert strong["official_decision_validated"] is False
    assert strong["advisory_only"] is True


@pytest.mark.asyncio
async def test_registered_dispatch_uses_the_trained_model():
    metadata = brochure_ml_metadata()
    quality_report = brochure_ml_quality_report()
    model = ModelVersion(
        id="dispatch-brochure-model",
        model_name=MODEL_NAME,
        version=MODEL_REGISTRY_VERSION,
        artifact_hash=brochure_ml_artifact_hash(),
        rubric_version_id="rubric-v2",
        training_rows=int(metadata["training_rows"]),
        test_metrics={"trained_model": True},
        lifecycle_state="bootstrap",
        quality_gate_report_hash=quality_report["report_sha256"],
        is_active=True,
    )
    result = await score_with_registered_model(model, "MOC-ST", STRONG_PROPOSAL, "2.0")
    assert result["model_source"] == MODEL_NAME
    assert result["training_rows"] == metadata["training_rows"]


@pytest.mark.asyncio
async def test_brochure_v2_hard_screening_passes_complete_declarations():
    extracted = await extract_structured_fields(STRONG_PROPOSAL)
    canonical = canonicalize_extracted_fields(extracted)
    result = await evaluate_rules("MOC-ST", canonical, "2.0")

    assert result["summary"]["automatic_progression"] is True
    assert result["summary"]["blocking_statuses"] == []
    assert canonical["fields"]["institution_eligibility"]["normalized_value"] == "startup"
    assert canonical["fields"]["thrust_area_alignment"]["normalized_value"] == "alternative-use-clean-coal"
    assert canonical["fields"]["industry_relevance"]["normalized_value"] == "demonstrated"
    assert canonical["fields"]["environmental_safety_compliance"]["normalized_value"] == "addressed"


@pytest.mark.asyncio
async def test_brochure_v2_prohibited_foreign_travel_fails_closed():
    proposal = STRONG_PROPOSAL.replace("Foreign Travel: none", "Foreign Travel: yes, INR 8 lakh budgeted")
    canonical = canonicalize_extracted_fields(await extract_structured_fields(proposal))
    result = await evaluate_rules("MOC-ST", canonical, "2.0")
    foreign_travel = next(
        item for item in result["results"] if item["rule_id"] == "MOC-ST-V2-FIN-005"
    )
    assert foreign_travel["result"] == "fail"
    assert result["summary"]["automatic_progression"] is False


def test_bootstrap_generator_is_deterministic_and_complete(tmp_path: Path):
    from app.ml.bootstrap import generate_records

    rubric = Path("data/rules/moc-st-100-mark-rubric-v2.yaml")
    spec = Path("data/training/moc-brochure-weak-label-spec-v1.yaml")
    first_path = tmp_path / "first.jsonl"
    second_path = tmp_path / "second.jsonl"

    first = generate_records(rubric, spec, first_path, rows=24, seed=91)
    second = generate_records(rubric, spec, second_path, rows=24, seed=91)

    assert first == second
    assert first_path.read_bytes() == second_path.read_bytes()
    assert len(first) == 24
    assert {record["label_origin"] for record in first} == {
        "brochure-derived weak supervision"
    }
    assert all(len(record["criterion_scores"]) == 23 for record in first)
    assert all(len(record["criterion_evidence"]) == 23 for record in first)
    assert all(record["text"].strip() for record in first)


def test_packaged_model_is_pickle_free_and_corruption_is_rejected(tmp_path: Path):
    import shutil

    assert MODEL_ARTIFACT_PATH.suffix == ".npz"
    assert not list(MODEL_ARTIFACT_PATH.parent.glob("*.joblib"))
    artifact = tmp_path / "model.npz"
    card = tmp_path / "model_card.json"
    shutil.copy2(MODEL_ARTIFACT_PATH, artifact)
    shutil.copy2(MODEL_CARD_PATH, card)
    artifact.write_bytes(b"not-a-numpy-archive")

    load_model_bundle.cache_clear()
    with pytest.raises(RuntimeError, match="pickle-free NumPy archive"):
        load_model_bundle(str(artifact))
    load_model_bundle.cache_clear()


@pytest.mark.asyncio
async def test_keyword_stuffing_cannot_obtain_a_decision_grade_score():
    stuffing = (
        "novel patent indigenous make in india trl laboratory infrastructure team "
        "milestones mou partner adoption roi safety environment net zero sc st women "
        "startup collaboration budget quotations phased funding payback manpower "
        "dependencies mitigation compliance dgms "
    ) * 30
    strong = await score_proposal_with_ml("MOC-ST", STRONG_PROPOSAL, "2.0")
    stuffed = await score_proposal_with_ml("MOC-ST", stuffing, "2.0")

    assert stuffed["abstention"] is True
    assert stuffed["decision_recommendation"] is None
    assert stuffed["total_score"] is None
    assert stuffed["diagnostic_score"] < 40
    assert strong["total_score"] is not None
    assert stuffed["diagnostic_score"] < strong["diagnostic_score"] - 20
    assert stuffed["confidence_type"] == "uncalibrated_reliability_indicator"
