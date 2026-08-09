"""Transparent near-duplicate screening for previously submitted proposals.

This is deliberately a deterministic text-similarity screen, not a plagiarism
verdict.  High overlap creates a reviewer clarification flag and stores the
matched proposal/version for audit.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.proposal import Proposal, ProposalDocument, ProposalVersion


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2
    ]


def _shingles(tokens: list[str], size: int = 5) -> set[tuple[str, ...]]:
    if len(tokens) < size:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def proposal_text_similarity(left: str, right: str) -> float:
    """Return a 0..1 overlap score resistant to isolated shared keywords."""

    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0

    left_shingles = _shingles(left_tokens)
    right_shingles = _shingles(right_tokens)
    shingle_union = left_shingles | right_shingles
    shingle_score = (
        len(left_shingles & right_shingles) / len(shingle_union)
        if shingle_union
        else 0.0
    )
    left_set = set(left_tokens)
    right_set = set(right_tokens)
    token_union = left_set | right_set
    token_score = len(left_set & right_set) / len(token_union) if token_union else 0.0
    length_ratio = min(len(left_tokens), len(right_tokens)) / max(len(left_tokens), len(right_tokens))
    return round(min(1.0, ((0.75 * shingle_score) + (0.25 * token_score)) * length_ratio), 4)


def _matching_passages(left: str, right: str, limit: int = 3) -> list[str]:
    right_normalized = re.sub(r"\s+", " ", right.lower())
    matches: list[str] = []
    for passage in re.split(r"(?:\n{2,}|(?<=[.!?])\s+)", left):
        cleaned = re.sub(r"\s+", " ", passage).strip()
        if len(cleaned.split()) < 8:
            continue
        probe = cleaned.lower()[:240]
        if probe and probe in right_normalized:
            matches.append(cleaned[:500])
        if len(matches) >= limit:
            break
    return matches


async def check_prior_projects(
    db: AsyncSession,
    document: ProposalDocument,
    proposal_id: str,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    """Compare a document with prior extracted proposals in the same database."""

    if not document.extracted_text:
        return {"checked_projects": 0, "highest_similarity": 0.0, "level": "not_run", "matches": []}

    result = await db.execute(
        select(ProposalDocument, ProposalVersion, Proposal)
        .join(ProposalVersion, ProposalVersion.id == ProposalDocument.proposal_version_id)
        .join(Proposal, Proposal.id == ProposalVersion.proposal_id)
        .where(
            Proposal.id != proposal_id,
            ProposalDocument.extracted_text.isnot(None),
            ProposalDocument.upload_completed_at.isnot(None),
        )
        .order_by(ProposalDocument.created_at.desc())
        .limit(limit)
    )
    rows = result.all()
    matches: list[dict[str, Any]] = []
    for candidate, version, proposal in rows:
        score = proposal_text_similarity(document.extracted_text, candidate.extracted_text or "")
        if score < 0.15:
            continue
        matches.append(
            {
                "proposal_id": proposal.id,
                "proposal_version_id": version.id,
                "title": proposal.title,
                "similarity": score,
                "matched_passages": _matching_passages(document.extracted_text, candidate.extracted_text or ""),
            }
        )
    matches.sort(key=lambda item: float(item["similarity"]), reverse=True)
    highest = float(matches[0]["similarity"]) if matches else 0.0
    level = "high" if highest >= 0.75 else "medium" if highest >= 0.45 else "low"
    return {
        "checked_projects": len(rows),
        "highest_similarity": highest,
        "level": level,
        "matches": matches[:5],
        "method": "word-5gram-jaccard-v1",
        "review_threshold": 0.75,
    }
