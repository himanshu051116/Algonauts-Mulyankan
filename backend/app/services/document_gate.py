"""Fail-closed document and scheme gate for preliminary proposal scoring.

This module intentionally uses transparent structural and domain signals. It is
not presented as a calibrated classifier. The gate prevents unsupported files
from entering criterion scoring while preserving a clear manual-review state.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

GATE_VERSION = "document-gate-v1"
MAIN_PROPOSAL_ROLE = "main_proposal"


@dataclass(frozen=True)
class GateResult:
    status: str
    accepted: bool
    scoring_allowed: bool
    document_type: str
    declared_role: str
    classified_role: str
    role_status: str
    classification_reliability: float
    word_count: int
    structure_coverage: float
    scheme_relevance: float
    structure_signals: list[str]
    domain_signals: list[str]
    reasons: list[str]
    gate_version: str = GATE_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_STRUCTURE_SIGNALS: dict[str, tuple[str, ...]] = {
    "objectives": (r"\bobjectives?\b", r"\baims?\b", r"\bproject goals?\b"),
    "methodology": (r"\bmethodolog(?:y|ies)\b", r"\btechnical approach\b", r"\bexperimental design\b"),
    "work_plan": (r"\bwork\s*plan\b", r"\bwork packages?\b", r"\bimplementation plan\b"),
    "timeline": (r"\bmilestones?\b", r"\bgantt\b", r"\bproject schedule\b", r"\bphase\s+\d+\b"),
    "budget": (r"\bbudget\b", r"\bcost estimate\b", r"\bfinancial(?:s| plan)?\b"),
    "duration": (r"\bproject duration\b", r"\bduration\s*[:\-]?\s*\d+\s*(?:months?|years?)\b"),
    "team": (r"\bprincipal investigator\b", r"\bproject team\b", r"\bco-?pi\b"),
    "trl": (r"\btrl\s*\d+\b", r"\btechnology readiness level\b"),
    "impact": (r"\bexpected outcomes?\b", r"\bproject impact\b", r"\bcommerciali[sz]ation\b", r"\beconomic benefit\b"),
    "risk_compliance": (r"\brisk(?:s| management)?\b", r"\bmitigation\b", r"\bcompliance\b", r"\bdgms\b"),
}

_DOMAIN_SIGNALS: dict[str, tuple[str, ...]] = {
    "coal_material": (r"\bcoal\b", r"\blignite\b", r"\bwashery\b", r"\bbeneficiation\b"),
    "mining_context": (r"\bmine(?:s| site| safety)?\b", r"\bopencast\b", r"\bunderground mining\b", r"\bcoal seam\b"),
    "sector_entities": (r"\bcoal india\b", r"\bcmpdi\b", r"\bdgms\b", r"\bcoal psu\b"),
    "coal_technology": (r"\bclean coal\b", r"\bcoal gasification\b", r"\bcoal handling\b", r"\bmine mechanisation\b", r"\bmine mechanization\b"),
    "coal_environment": (r"\bmine environment\b", r"\bcoal waste\b", r"\bmine water\b", r"\bmine fire\b"),
}

_RESUME_MARKERS = (
    r"\bcurriculum vitae\b",
    r"\bresume\b",
    r"\beducation\b",
    r"\btechnical skills\b",
    r"\bwork experience\b",
    r"\binternships?\b",
    r"\bcgpa\b",
    r"\bb\.?\s*tech\b",
    r"\blinkedin\b",
    r"\bgithub\b",
    r"\bleetcode\b",
)

_REFERENCE_MARKERS = (
    r"\bpurpose of this brochure\b",
    r"\bwho can apply\b",
    r"\bwhat applicants should do\b",
    r"\bapplicant guidance\b",
    r"\bmarking summary table\b",
    r"\bdo['’]?s and don['’]?ts\b",
)


def _matched_groups(text: str, groups: dict[str, tuple[str, ...]]) -> list[str]:
    return [
        name
        for name, patterns in groups.items()
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)
    ]


def _marker_count(text: str, patterns: tuple[str, ...]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, text, re.IGNORECASE))


def _result(
    *,
    status: str,
    accepted: bool,
    document_type: str,
    declared_role: str,
    classified_role: str,
    role_status: str,
    word_count: int,
    structure_signals: list[str],
    domain_signals: list[str],
    reasons: list[str],
    classification_reliability: float,
) -> GateResult:
    structure_coverage = round(len(structure_signals) / len(_STRUCTURE_SIGNALS), 3)
    scheme_relevance = round(len(domain_signals) / len(_DOMAIN_SIGNALS), 3)
    return GateResult(
        status=status,
        accepted=accepted,
        scoring_allowed=accepted,
        document_type=document_type,
        declared_role=declared_role,
        classified_role=classified_role,
        role_status=role_status,
        classification_reliability=round(max(0.0, min(1.0, classification_reliability)), 3),
        word_count=word_count,
        structure_coverage=structure_coverage,
        scheme_relevance=scheme_relevance,
        structure_signals=structure_signals,
        domain_signals=domain_signals,
        reasons=reasons,
    )


def assess_document(
    text: str,
    scheme_code: str,
    *,
    declared_role: str = MAIN_PROPOSAL_ROLE,
    file_name: str | None = None,
) -> GateResult:
    """Assess whether a document may enter MOC-ST criterion scoring.

    The gate is deliberately conservative. Borderline inputs are sent to manual
    review without a numeric score rather than forced through the ML model.
    """

    normalised = re.sub(r"\s+", " ", text or " ").strip()
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9&/'-]*", normalised)
    word_count = len(words)
    structure_signals = _matched_groups(normalised, _STRUCTURE_SIGNALS)
    domain_signals = _matched_groups(normalised, _DOMAIN_SIGNALS)
    resume_markers = _marker_count(normalised, _RESUME_MARKERS)
    reference_markers = _marker_count(normalised, _REFERENCE_MARKERS)
    filename = (file_name or "").lower()

    if declared_role != MAIN_PROPOSAL_ROLE:
        return _result(
            status="role_disallowed",
            accepted=False,
            document_type="supporting_document",
            declared_role=declared_role,
            classified_role=declared_role,
            role_status="confirmed",
            word_count=word_count,
            structure_signals=structure_signals,
            domain_signals=domain_signals,
            reasons=["Only a declared main proposal may initiate criterion scoring."],
            classification_reliability=1.0,
        )

    if reference_markers >= 2:
        return _result(
            status="invalid_document",
            accepted=False,
            document_type="reference_guideline",
            declared_role=declared_role,
            classified_role="reference_guideline",
            role_status="mismatch",
            word_count=word_count,
            structure_signals=structure_signals,
            domain_signals=domain_signals,
            reasons=["Applicant guidance or reference material cannot be scored as a submitted proposal."],
            classification_reliability=0.95,
        )

    filename_resume = any(token in filename for token in ("resume", "cv", "curriculum-vitae"))
    if filename_resume or (resume_markers >= 4 and len(structure_signals) < 7):
        return _result(
            status="invalid_document",
            accepted=False,
            document_type="resume",
            declared_role=declared_role,
            classified_role="pi_cv",
            role_status="mismatch",
            word_count=word_count,
            structure_signals=structure_signals,
            domain_signals=domain_signals,
            reasons=["The file appears to be a résumé/CV rather than the main proposal."],
            classification_reliability=0.95,
        )

    if word_count < 80:
        return _result(
            status="insufficient_extraction",
            accepted=False,
            document_type="unknown",
            declared_role=declared_role,
            classified_role="unknown",
            role_status="uncertain",
            word_count=word_count,
            structure_signals=structure_signals,
            domain_signals=domain_signals,
            reasons=["The extracted document is too short for reliable proposal classification."],
            classification_reliability=0.0,
        )

    if len(structure_signals) < 3:
        return _result(
            status="manual_review",
            accepted=False,
            document_type="possible_proposal",
            declared_role=declared_role,
            classified_role="unknown",
            role_status="uncertain",
            word_count=word_count,
            structure_signals=structure_signals,
            domain_signals=domain_signals,
            reasons=[
                "Too few proposal-specific sections were detected for automated scoring; "
                "a reviewer must classify the document."
            ],
            classification_reliability=0.35,
        )

    if scheme_code.upper() == "MOC-ST" and len(domain_signals) < 2:
        return _result(
            status="manual_review",
            accepted=False,
            document_type="proposal_scheme_unconfirmed",
            declared_role=declared_role,
            classified_role="main_proposal",
            role_status="uncertain",
            word_count=word_count,
            structure_signals=structure_signals,
            domain_signals=domain_signals,
            reasons=[
                "Coal S&T relevance was not established with enough contextual evidence; "
                "the scheme must be confirmed by a reviewer."
            ],
            classification_reliability=0.40,
        )

    if len(structure_signals) < 5 or len(domain_signals) < 3:
        return _result(
            status="manual_review",
            accepted=False,
            document_type="possible_moc_st_proposal",
            declared_role=declared_role,
            classified_role="main_proposal",
            role_status="uncertain",
            word_count=word_count,
            structure_signals=structure_signals,
            domain_signals=domain_signals,
            reasons=["The document may be a Coal S&T proposal, but its structure or domain evidence is incomplete."],
            classification_reliability=0.50,
        )

    return _result(
        status="accepted",
        accepted=True,
        document_type="moc_st_proposal",
        declared_role=declared_role,
        classified_role="main_proposal",
        role_status="confirmed",
        word_count=word_count,
        structure_signals=structure_signals,
        domain_signals=domain_signals,
        reasons=[],
        classification_reliability=min(
            len(structure_signals) / len(_STRUCTURE_SIGNALS),
            len(domain_signals) / len(_DOMAIN_SIGNALS),
        ),
    )


def gate_only_scoring_result(gate: GateResult, *, maximum_score: float = 100.0) -> dict[str, Any]:
    """Build a stable no-score result for a rejected or review-only document."""

    return {
        "total_score": None,
        "diagnostic_score": None,
        "maximum_score": maximum_score,
        "evidence_coverage": 0.0,
        "information_sufficiency": 0.0,
        "confidence": None,
        "category_scores": [],
        "model_source": GATE_VERSION,
        "model_invoked": False,
        "advisory_only": True,
        "official_decision_validated": False,
        "scoring_status": "gate_rejected" if gate.status != "manual_review" else "manual_review",
        "abstention": True,
        "abstention_reasons": list(gate.reasons),
        "decision_recommendation": None,
        "document_gate": gate.as_dict(),
    }
