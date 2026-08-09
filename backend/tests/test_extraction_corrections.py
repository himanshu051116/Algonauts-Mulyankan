"""Reviewer correction workflow for authoritative extracted proposal fields."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.models.proposal import ExtractedField, Proposal, ProposalDocument, ProposalVersion
from app.models.user import User, UserRole


class Result:
    def __init__(self, *, row=None, scalar=None):
        self._row = row
        self._scalar = scalar

    def one_or_none(self):
        return self._row

    def scalar_one_or_none(self):
        return self._scalar


class FakeDb:
    def __init__(self, results):
        self.results = list(results)
        self.commits = 0
        self.refreshed = []

    async def execute(self, _statement):
        return self.results.pop(0)

    async def commit(self):
        self.commits += 1

    async def refresh(self, item):
        self.refreshed.append(item)


class FakeRequest:
    client = type("Client", (), {"host": "127.0.0.1"})()
    headers = {"user-agent": "pytest"}


@pytest.fixture
def correction_objects():
    officer = User(
        id="officer-1",
        email="officer@coal.gov.in",
        role=UserRole.SCRUTINY_OFFICER,
        is_active=True,
        is_verified=True,
    )
    proposal = Proposal(
        id="proposal-1",
        owner_id="owner-1",
        scheme_id="scheme-1",
        title="Coal safety pilot",
        status="human_review",
        current_version=1,
    )
    version = ProposalVersion(
        id="version-1",
        proposal_id=proposal.id,
        version_number=1,
        title=proposal.title,
        document_hash="a" * 64,
        content_hash="b" * 64,
        structured_data={
            "fields": {
                "project_duration_months": {
                    "normalized_value": 18,
                    "status": "extracted",
                }
            }
        },
    )
    document = ProposalDocument(
        id="document-1",
        proposal_version_id=version.id,
        file_name="proposal.pdf",
        storage_path="proposals/proposal-1/v1/proposal.pdf",
        file_type="pdf",
        file_size=1024,
        sha256_hash="a" * 64,
        is_primary=True,
    )
    field = ExtractedField(
        id="field-1",
        document_id=document.id,
        field_name="project_duration_months",
        field_value="18 months",
        normalized_value="18",
        original_text="The project duration shall be 18 months.",
        source_page=4,
        source_section="Work plan",
        char_start=100,
        char_end=145,
        evidence_coverage=0.92,
        validation_warnings=[],
        conflict_status="none",
    )
    return officer, proposal, version, document, field


@pytest.mark.asyncio
async def test_correction_updates_effective_value_snapshot_and_hash(
    monkeypatch, correction_objects
):
    from app.routers import storage as storage_router

    officer, proposal, version, document, field = correction_objects
    db = FakeDb(
        [
            Result(row=(document, version, proposal)),
            Result(scalar=field),
        ]
    )
    audit_details = {}

    async def create_audit_event(_db, **kwargs):
        audit_details.update(kwargs)

    monkeypatch.setattr(storage_router, "create_audit_event", create_audit_event)

    response = await storage_router.correct_extracted_field(
        document_id=document.id,
        field_name=field.field_name,
        body=storage_router.ExtractedFieldCorrectionRequest(
            value="24",
            reason="Verified against the signed work-plan table on page 4.",
        ),
        request=FakeRequest(),
        current_user=officer,
        db=db,
    )

    assert response.effective_value == "24"
    assert response.corrected_by == officer.id
    assert response.corrected_at is not None
    assert field.conflict_status == "corrected"
    entry = version.structured_data["fields"][field.field_name]
    assert entry["normalized_value"] == "24"
    assert entry["manually_corrected"] is True
    assert entry["correction_reason"].startswith("Verified")
    assert version.content_hash not in {"a" * 64, "b" * 64}
    assert len(version.content_hash or "") == 64
    assert audit_details["event_type"] == "extraction.field_corrected"
    assert audit_details["details"]["previous_value"] == "18"
    assert audit_details["details"]["corrected_value"] == "24"
    assert db.commits == 1
    assert db.refreshed == [field]


@pytest.mark.asyncio
async def test_correction_rejects_superseded_document(correction_objects):
    from app.routers import storage as storage_router

    officer, proposal, version, document, _field = correction_objects
    document.is_primary = False
    document.superseded_at = datetime.now(timezone.utc)
    db = FakeDb([Result(row=(document, version, proposal))])

    with pytest.raises(HTTPException) as exc:
        await storage_router.correct_extracted_field(
            document_id=document.id,
            field_name="project_duration_months",
            body=storage_router.ExtractedFieldCorrectionRequest(
                value="24",
                reason="Verified against the signed work-plan table.",
            ),
            request=FakeRequest(),
            current_user=officer,
            db=db,
        )

    assert exc.value.status_code == 409
    assert "active primary document" in exc.value.detail


@pytest.mark.asyncio
async def test_correction_rejects_finalised_proposal(correction_objects):
    from app.routers import storage as storage_router

    officer, proposal, version, document, _field = correction_objects
    proposal.status = "approved"
    db = FakeDb([Result(row=(document, version, proposal))])

    with pytest.raises(HTTPException) as exc:
        await storage_router.correct_extracted_field(
            document_id=document.id,
            field_name="project_duration_months",
            body=storage_router.ExtractedFieldCorrectionRequest(
                value="24",
                reason="Verified against the signed work-plan table.",
            ),
            request=FakeRequest(),
            current_user=officer,
            db=db,
        )

    assert exc.value.status_code == 409
    assert "Finalised" in exc.value.detail
