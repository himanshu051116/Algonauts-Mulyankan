"""Regression tests for the 0.6.0 integrity hardening."""

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import JSON, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.proposal import FundingScheme, Proposal, ProposalDocument, ProposalVersion
from app.models.user import User, UserRole


@pytest_asyncio.fixture
async def hardening_session():
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


async def _seed_version(session):
    owner = User(
        id="owner-hardening",
        email="hardening@example.gov.in",
        role=UserRole.APPLICANT,
        is_active=True,
        is_verified=True,
    )
    scheme = FundingScheme(
        id="scheme-hardening",
        code="MOC-ST-HARDENING",
        name="Hardening scheme",
        is_active=True,
    )
    proposal = Proposal(
        id="proposal-hardening",
        owner_id=owner.id,
        scheme_id=scheme.id,
        title="Immutable submitted title",
        status="draft",
        current_version=1,
    )
    version = ProposalVersion(
        id="version-hardening",
        proposal_id=proposal.id,
        version_number=1,
        title=proposal.title,
    )
    session.add_all([owner, scheme, proposal, version])
    await session.commit()
    return proposal, version


def _document(version_id: str, document_id: str, *, primary: bool = True):
    return ProposalDocument(
        id=document_id,
        proposal_version_id=version_id,
        file_name=f"{document_id}.pdf",
        file_type="pdf",
        file_size=1024,
        storage_path=f"proposals/{document_id}.pdf",
        sha256_hash=("a" if document_id.endswith("1") else "b") * 64,
        extracted_text="Coal proposal evidence",
        upload_completed_at=datetime.now(timezone.utc),
        is_primary=primary,
    )


@pytest.mark.asyncio
async def test_exactly_one_active_primary_document_per_version(hardening_session):
    session = hardening_session
    _, version = await _seed_version(session)
    version_id = version.id
    first = _document(version_id, "document-1")
    first_id = first.id
    session.add(first)
    await session.commit()

    session.add(_document(version_id, "document-2"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    await session.execute(
        update(ProposalDocument)
        .where(ProposalDocument.id == first_id)
        .values(is_primary=False, superseded_at=datetime.now(timezone.utc))
    )
    session.add(_document(version_id, "document-2"))
    await session.commit()

    result = await session.execute(
        select(ProposalDocument).where(
            ProposalDocument.proposal_version_id == version_id,
            ProposalDocument.is_primary.is_(True),
            ProposalDocument.superseded_at.is_(None),
        )
    )
    assert [document.id for document in result.scalars().all()] == ["document-2"]


@pytest.mark.asyncio
async def test_invalid_proposal_status_is_rejected_by_database(hardening_session):
    session = hardening_session
    proposal, _ = await _seed_version(session)
    proposal.status = "pending"
    with pytest.raises(IntegrityError):
        await session.commit()
