"""Regression tests for governed multi-document submission packages."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.services.scoring import score_proposal
from app.services.submission_packages import build_submission_package_summary


def _version(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": "version-1",
        "version_number": 1,
        "package_status": "draft",
        "package_hash": None,
        "package_confirmed_at": None,
        "package_confirmed_by": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _document(
    requirement_id: str,
    document_role: str,
    *,
    identifier: str | None = None,
    file_type: str = "pdf",
    is_primary: bool = False,
    extracted_text: str = "Supporting evidence is available in this governed document.",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=identifier or f"doc-{requirement_id}",
        requirement_id=requirement_id,
        document_role=document_role,
        file_name=f"{requirement_id}.{file_type}",
        file_type=file_type,
        file_size=1024,
        storage_path=f"proposals/version-1/{requirement_id}.{file_type}",
        sha256_hash=(requirement_id.encode("utf-8").hex() + "0" * 64)[:64],
        extracted_text=extracted_text,
        is_primary=is_primary,
        role_status="confirmed",
        upload_completed_at=datetime.now(UTC),
        superseded_at=None,
        created_at=datetime.now(UTC),
    )


def _complete_documents() -> list[SimpleNamespace]:
    return [
        _document(
            "proposal_body",
            "main_proposal",
            is_primary=True,
            extracted_text=(
                "Introduction\nThis coal research proposal addresses mine safety. "
                "Methodology\nThe technical approach includes pilot validation."
            ),
        ),
        _document("budget_sheet", "budget_annexure"),
        _document("pi_cv", "pi_cv"),
        _document("endorsement_letter", "institution_profile"),
        _document("declaration_form", "compliance_document"),
        _document("prior_funding_declaration", "compliance_document"),
    ]


def test_submission_package_reports_missing_mandatory_requirements() -> None:
    summary = build_submission_package_summary(
        scheme_code="MOC-ST",
        proposal_id="proposal-1",
        version=_version(),
        documents=[
            _document(
                "proposal_body",
                "main_proposal",
                is_primary=True,
                extracted_text="A complete extractable coal research proposal body.",
            )
        ],
    )

    assert summary["package_status"] == "incomplete"
    assert summary["ready_to_confirm"] is False
    assert set(summary["missing_mandatory_requirements"]) == {
        "budget_sheet",
        "pi_cv",
        "endorsement_letter",
        "declaration_form",
        "prior_funding_declaration",
    }


def test_complete_submission_package_has_stable_manifest_hash() -> None:
    documents = _complete_documents()
    first = build_submission_package_summary(
        scheme_code="MOC-ST",
        proposal_id="proposal-1",
        version=_version(),
        documents=documents,
    )
    second = build_submission_package_summary(
        scheme_code="MOC-ST",
        proposal_id="proposal-1",
        version=_version(),
        documents=list(reversed(documents)),
    )

    assert first["package_status"] == "ready"
    assert first["ready_to_confirm"] is True
    assert first["missing_mandatory_requirements"] == []
    assert first["invalid_requirements"] == []
    assert len(first["computed_package_hash"]) == 64
    assert first["computed_package_hash"] == second["computed_package_hash"]
    assert first["canonical_manifest"] == second["canonical_manifest"]
    assert len(first["canonical_manifest"]["documents"]) == 6


@pytest.mark.asyncio
async def test_supporting_evidence_retains_document_provenance_and_role_contract() -> None:
    main_text = """
    Introduction
    This coal research project addresses a mine safety problem using a pilot methodology.
    Work Plan
    The work plan defines milestones, deliverables and a 24 month validation timeline.
    """
    package_documents = [
        {
            "document_id": "main-1",
            "document_role": "main_proposal",
            "file_name": "proposal.pdf",
            "text": main_text,
        },
        {
            "document_id": "budget-1",
            "document_role": "budget_annexure",
            "file_name": "budget.pdf",
            "text": (
                "Budget\nThe itemised budget includes equipment quantities, supplier "
                "quotations, unit rates, taxes and cost justification for each budget head."
            ),
        },
    ]

    result = await score_proposal(
        "MOC-ST",
        main_text,
        "2.0",
        documents=package_documents,
    )
    budget = next(
        criterion
        for category in result["category_scores"]
        for criterion in category["criteria"]
        if criterion["criterion_id"] == "budget-realism"
    )

    assert budget["released"] is True
    assert any(
        evidence.get("document_id") == "budget-1"
        and evidence.get("document_role") == "budget_annexure"
        and evidence.get("file_name") == "budget.pdf"
        for evidence in budget["evidence"]
    )


@pytest.mark.asyncio
async def test_disallowed_supporting_role_cannot_release_budget_evidence() -> None:
    main_text = """
    Introduction
    This coal research project addresses mine safety using a pilot methodology.
    Work Plan
    The work plan defines milestones and a validation timeline.
    """
    result = await score_proposal(
        "MOC-ST",
        main_text,
        "2.0",
        documents=[
            {
                "document_id": "cv-1",
                "document_role": "pi_cv",
                "file_name": "pi-cv.pdf",
                "text": (
                    "Budget\nThe itemised budget includes quotations, quantities, rates, "
                    "taxes and detailed cost justification for equipment."
                ),
            }
        ],
    )
    budget = next(
        criterion
        for category in result["category_scores"]
        for criterion in category["criteria"]
        if criterion["criterion_id"] == "budget-realism"
    )

    assert budget["released"] is False
    assert budget["awarded_score"] is None
