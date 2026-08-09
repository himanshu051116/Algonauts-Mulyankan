import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import JSON, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.proposal import FundingScheme, Proposal, ProposalVersion
from app.models.user import User, UserRole
from app.routers.proposals import create_proposal_version
from app.schemas.proposal import ProposalCreate, ProposalVersionCreate


class FakeRequest:
    client = type("Client", (), {"host": "127.0.0.1"})()
    headers = {"user-agent": "pytest"}


@pytest_asyncio.fixture
async def version_session():
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session
    await engine.dispose()


def test_proposal_create_normalises_text():
    payload = ProposalCreate(
        title="  Methane monitoring for underground mines  ",
        scheme_code=" MOC-ST ",
        executive_summary="  Safe, evidence-led deployment.  ",
    )
    assert payload.title == "Methane monitoring for underground mines"
    assert payload.scheme_code == "MOC-ST"
    assert payload.executive_summary == "Safe, evidence-led deployment."


@pytest.mark.asyncio
async def test_new_proposal_version_is_immutable_and_inherits_summary(version_session):
    session = version_session
    user = User(
        id="owner-1",
        email="owner@example.gov.in",
        role=UserRole.APPLICANT,
        is_active=True,
        is_verified=True,
    )
    scheme = FundingScheme(
        id="scheme-1",
        code="MOC-ST",
        name="Ministry of Coal S&T",
        is_active=True,
    )
    proposal = Proposal(
        id="proposal-1",
        owner_id=user.id,
        scheme_id=scheme.id,
        title="Coal mine methane monitoring",
        status="revision_required",
        current_version=1,
    )
    first = ProposalVersion(
        id="version-1",
        proposal_id=proposal.id,
        version_number=1,
        title=proposal.title,
        executive_summary="Original summary",
        structured_data={"locked": True},
    )
    session.add_all([user, scheme, proposal, first])
    await session.commit()

    response = await create_proposal_version(
        proposal_id=proposal.id,
        body=ProposalVersionCreate(),
        request=FakeRequest(),
        current_user=user,
        db=session,
    )

    assert response.version_number == 2
    assert response.previous_version_id == first.id
    assert response.title == proposal.title
    assert response.executive_summary == "Original summary"
    assert response.document_hash == ""
    assert response.content_hash == ""

    await session.refresh(proposal)
    assert proposal.current_version == 2
    first_row = await session.get(ProposalVersion, first.id)
    assert first_row is not None
    assert first_row.structured_data == {"locked": True}


@pytest.mark.asyncio
async def test_duplicate_version_number_is_rejected_by_database(version_session):
    session = version_session
    user = User(
        id="owner-2",
        email="owner2@example.gov.in",
        role=UserRole.APPLICANT,
        is_active=True,
        is_verified=True,
    )
    scheme = FundingScheme(
        id="scheme-2",
        code="MOC-ST-2",
        name="Test scheme",
        is_active=True,
    )
    proposal = Proposal(
        id="proposal-2",
        owner_id=user.id,
        scheme_id=scheme.id,
        title="Duplicate protection proposal",
        status="draft",
        current_version=1,
    )
    proposal_id = proposal.id
    session.add_all(
        [
            user,
            scheme,
            proposal,
            ProposalVersion(proposal_id=proposal_id, version_number=1),
        ]
    )
    await session.commit()

    session.add(ProposalVersion(proposal_id=proposal_id, version_number=1))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    rows = await session.execute(
        select(ProposalVersion).where(ProposalVersion.proposal_id == proposal_id)
    )
    assert len(rows.scalars().all()) == 1


@pytest.mark.asyncio
async def test_evaluated_revision_must_branch_before_editing():
    from app.routers.proposals import _editable_current_version

    proposal = Proposal(
        id="proposal-revision",
        owner_id="owner-1",
        scheme_id="scheme-1",
        title="Original title",
        status="revision_required",
        current_version=1,
    )
    version = ProposalVersion(
        id="version-evaluated",
        proposal_id=proposal.id,
        version_number=1,
        title=proposal.title,
    )

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class Db:
        def __init__(self):
            self.results = [version, "model-run-1"]

        async def execute(self, _statement):
            return Result(self.results.pop(0))

    with pytest.raises(HTTPException) as exc:
        await _editable_current_version(Db(), proposal)

    assert exc.value.status_code == 409
    assert "Create a new proposal version" in exc.value.detail


@pytest.mark.asyncio
async def test_new_revision_version_is_editable():
    from app.routers.proposals import _editable_current_version

    proposal = Proposal(
        id="proposal-revision-2",
        owner_id="owner-1",
        scheme_id="scheme-1",
        title="Revised title",
        status="revision_required",
        current_version=2,
    )
    version = ProposalVersion(
        id="version-new",
        proposal_id=proposal.id,
        version_number=2,
        previous_version_id="version-old",
        title=proposal.title,
    )

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class Db:
        def __init__(self):
            self.results = [version, None]

        async def execute(self, _statement):
            return Result(self.results.pop(0))

    assert await _editable_current_version(Db(), proposal) is version
