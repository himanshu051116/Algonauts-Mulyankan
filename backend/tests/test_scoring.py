"""Unit tests for fail-closed evidence scoring."""

import pytest

from app.services.evidence_contracts import detect_section_spans, has_local_negation
from app.services.scoring import score_proposal


@pytest.mark.asyncio
async def test_scoring_empty_text_is_not_scored():
    result = await score_proposal("MOC-ST", "")
    assert result["total_score"] is None
    assert result["diagnostic_score"] == 0
    assert result["maximum_score"] > 0
    assert result["information_sufficiency"] == 0
    assert result["abstention"] is True
    assert result["released_criterion_count"] == 0


@pytest.mark.asyncio
async def test_scoring_releases_only_contract_accepted_evidence():
    text = """
    Introduction
    This project addresses a critical coal mining safety problem in opencast mines.
    Methodology
    A novel research methodology and technical approach will improve mine productivity.
    Work Plan
    The work plan includes measurable milestones, deliverables and a 24 month timeline.
    Team
    The principal investigator has coal-sector expertise and laboratory facilities.
    Budget
    The itemised budget includes quotations, quantities, rates and cost justification.
    Compliance
    DGMS approval and environmental clearance will be obtained before field trials.
    """
    result = await score_proposal("MOC-ST", text)
    assert result["diagnostic_score"] > 0
    assert result["maximum_score"] == 100
    assert result["released_criterion_count"] > 0
    assert result["model_source"] == "contextual-rule-heuristic-v3"
    for category in result["category_scores"]:
        for criterion in category["criteria"]:
            if criterion["awarded_score"] is not None:
                assert criterion["released"] is True
                assert criterion["evidence_count"] > 0
                assert criterion["evidence"]


@pytest.mark.asyncio
async def test_scoring_accepts_seeded_semantic_rubric_version():
    result = await score_proposal(
        "MOC-ST",
        "Introduction\nCoal mine safety research.\nMethodology\nThe pilot methodology includes mine testing and validation.",
        "1.0",
    )
    assert "error" not in result
    assert result["maximum_score"] == 100
    assert len(result["category_scores"]) > 0


@pytest.mark.asyncio
async def test_scoring_unknown_scheme_is_not_scored():
    result = await score_proposal("UNKNOWN", "Some text")
    assert "error" in result
    assert result["total_score"] is None
    assert result["scoring_status"] == "configuration_error"


@pytest.mark.asyncio
async def test_keyword_stuffing_cannot_release_score():
    text = (
        "coal mine research novel methodology objective validation budget risk "
        "pilot prototype scale up impact safety productivity quotation " * 40
    )
    result = await score_proposal("MOC-ST", text)
    assert result["total_score"] is None
    assert result["abstention"] is True
    assert result["document_quality"]["repetition_penalty"] < 0.5


@pytest.mark.asyncio
async def test_no_evidence_means_no_score():
    result = await score_proposal(
        "MOC-ST",
        "Introduction\nThe applicant enjoys software interfaces and relationship milestones. "
        "The document describes education, coding projects and general machine learning experience.",
        "2.0",
    )
    assert result["total_score"] is None
    for category in result["category_scores"]:
        for criterion in category["criteria"]:
            if criterion["evidence_count"] == 0:
                assert criterion["awarded_score"] is None
                assert criterion["ordinal_grade"] is None
                assert criterion["released"] is False


def test_suffix_negation_is_not_supporting_evidence():
    assert has_local_negation("Foreign travel is not requested for this project.", ["foreign travel"])
    assert has_local_negation("Environmental benefit will never be claimed without measurements.", ["environmental benefit"])
    assert not has_local_negation("Environmental benefit will be measured through emission reduction.", ["environmental benefit"])


@pytest.mark.asyncio
async def test_single_generic_keyword_does_not_release_criterion_score():
    result = await score_proposal(
        "MOC-ST",
        "Infrastructure\nThe team has access to a machine. "
        "Administrative reporting arrangements, meeting records, communication "
        "procedures, document retention and general coordination are described "
        "without identifying any additional laboratory, equipment or test-site evidence.",
        "2.0",
    )
    infrastructure = next(
        criterion
        for category in result["category_scores"]
        for criterion in category["criteria"]
        if criterion["criterion_id"] == "infrastructure-readiness"
    )
    assert infrastructure["released"] is False
    assert infrastructure["awarded_score"] is None


def test_section_detection_recognises_governed_proposal_heading_variants():
    text = """
5. Novelty and Technical Contribution
Joint optimisation uses a hybrid model and first-principles constraints.

6. Technical Methodology
A sampling plan, data acquisition layer and cross-validation protocol are defined.

7. Work Packages and Deliverables
Work package WP1 has milestones and deliverables.

12. Risk Management
Feed variability and sensor drift have mitigation owners.

13. Safety, Environmental and Ethical Compliance
Safety procedures and statutory approvals are defined.
"""
    spans = detect_section_spans(text)
    detected = {item["section_type"] for item in spans}

    assert {"novelty", "methodology", "work_plan", "risk", "safety_environment"} <= detected
