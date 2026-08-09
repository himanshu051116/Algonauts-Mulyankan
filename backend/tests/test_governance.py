import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.proposal import (
    ExpertReview,
    FundingScheme,
    Proposal,
    ProposalVersion,
    ReviewerAssignment,
)
from app.models.user import User, UserRole
from app.routers.governance import create_adjudication, create_committee_decision
from app.schemas.governance import AdjudicationCreate, CommitteeDecisionCreate


class FakeRequest:
    client = type("Client", (), {"host": "127.0.0.1"})()
    headers = {"user-agent": "pytest"}


@pytest_asyncio.fixture
async def governance_graph():
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with factory() as session:
        owner = User(
            id="owner-governance",
            email="owner-governance@example.gov.in",
            role=UserRole.APPLICANT,
            is_active=True,
            is_verified=True,
        )
        adjudicator = User(
            id="adjudicator-1",
            email="adjudicator@example.gov.in",
            role=UserRole.SENIOR_ADJUDICATOR,
            is_active=True,
            is_verified=True,
        )
        secretariat = User(
            id="secretariat-1",
            email="secretariat@example.gov.in",
            role=UserRole.COMMITTEE_SECRETARIAT,
            is_active=True,
            is_verified=True,
        )
        technical = User(
            id="reviewer-technical",
            email="technical@example.gov.in",
            role=UserRole.TECHNICAL_REVIEWER,
            is_active=True,
            is_verified=True,
        )
        financial = User(
            id="reviewer-financial",
            email="financial@example.gov.in",
            role=UserRole.FINANCIAL_REVIEWER,
            is_active=True,
            is_verified=True,
        )
        scheme = FundingScheme(
            id="scheme-governance",
            code="MOC-ST",
            name="Ministry of Coal S&T",
            is_active=True,
        )
        proposal = Proposal(
            id="proposal-governance",
            owner_id=owner.id,
            scheme_id=scheme.id,
            title="Governance workflow proposal",
            status="human_review",
            current_version=1,
        )
        version = ProposalVersion(
            id="version-governance",
            proposal_id=proposal.id,
            version_number=1,
        )
        technical_assignment = ReviewerAssignment(
            id="assignment-technical",
            proposal_id=proposal.id,
            proposal_version_id=version.id,
            reviewer_id=technical.id,
            assigned_by=secretariat.id,
            role="technical",
            status="completed",
        )
        financial_assignment = ReviewerAssignment(
            id="assignment-financial",
            proposal_id=proposal.id,
            proposal_version_id=version.id,
            reviewer_id=financial.id,
            assigned_by=secretariat.id,
            role="financial",
            status="completed",
        )
        session.add_all(
            [
                owner,
                adjudicator,
                secretariat,
                technical,
                financial,
                scheme,
                proposal,
                version,
                technical_assignment,
                financial_assignment,
                ExpertReview(
                    assignment_id=technical_assignment.id,
                    total_score=78,
                    recommendation="approved",
                    is_submitted=True,
                ),
                ExpertReview(
                    assignment_id=financial_assignment.id,
                    total_score=72,
                    recommendation="revision",
                    is_submitted=True,
                ),
            ]
        )
        await session.commit()
        yield session, proposal, version, adjudicator, secretariat

    await engine.dispose()


@pytest.mark.asyncio
async def test_adjudication_and_committee_decision_are_version_bound(governance_graph):
    session, proposal, version, adjudicator, secretariat = governance_graph

    adjudication = await create_adjudication(
        proposal_id=proposal.id,
        body=AdjudicationCreate(
            reason="The two expert recommendations differ and require resolution.",
            resolved_score=75,
        ),
        request=FakeRequest(),
        current_user=adjudicator,
        db=session,
    )
    assert adjudication.proposal_version_id == version.id
    assert proposal.status == "adjudication"

    decision = await create_committee_decision(
        proposal_id=proposal.id,
        body=CommitteeDecisionCreate(
            decision="approved",
            decision_notes="Approved after considering both expert reviews and adjudication.",
        ),
        request=FakeRequest(),
        current_user=secretariat,
        db=session,
    )
    assert decision.proposal_version_id == version.id
    assert decision.expert_score_at_decision == 75
    assert proposal.status == "approved"


@pytest.mark.asyncio
async def test_duplicate_committee_decision_is_rejected(governance_graph):
    session, proposal, _version, _adjudicator, secretariat = governance_graph

    await create_committee_decision(
        proposal_id=proposal.id,
        body=CommitteeDecisionCreate(
            decision="revision_required",
            decision_notes="The proposal requires a revised implementation and budget plan.",
        ),
        request=FakeRequest(),
        current_user=secretariat,
        db=session,
    )

    # Re-open only to exercise the immutable decision guard for this version.
    proposal.status = "committee_review"
    await session.commit()
    with pytest.raises(HTTPException) as exc:
        await create_committee_decision(
            proposal_id=proposal.id,
            body=CommitteeDecisionCreate(
                decision="approved",
                decision_notes="A second decision must not overwrite the recorded decision.",
            ),
            request=FakeRequest(),
            current_user=secretariat,
            db=session,
        )
    assert exc.value.status_code == 409
    assert "already exists" in exc.value.detail
