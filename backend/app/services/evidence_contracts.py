"""Versioned criterion evidence contracts and section-aware passage controls."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONTRACT_DIR = Path(__file__).resolve().parents[3] / "data" / "evidence-contracts"

_SECTION_PATTERNS: dict[str, tuple[str, ...]] = {
    "abstract": ("abstract", "executive summary", "summary"),
    "introduction": (
        "introduction", "background", "problem statement", "problem statement and need",
    ),
    "objectives": (
        "objectives", "aims and objectives", "project objectives",
        "objectives and measurable success criteria",
    ),
    "literature_review": (
        "literature review", "review of literature", "prior work", "state of the art",
        "references and technical basis",
    ),
    "novelty": (
        "novelty", "innovation", "research gap", "originality",
        "novelty and technical contribution", "novelty and innovation",
    ),
    "methodology": (
        "methodology", "research methodology", "methods", "technical methodology",
    ),
    "technical_approach": (
        "technical approach", "system architecture", "process flow", "technical details",
    ),
    "validation": ("validation", "testing protocol", "acceptance criteria"),
    "trl": (
        "technology readiness", "trl", "readiness level", "trl progression and exit criteria",
    ),
    "infrastructure": (
        "infrastructure", "facilities", "laboratory", "equipment available",
        "infrastructure and facilities",
    ),
    "work_plan": (
        "work plan", "workplan", "implementation plan", "work packages",
        "work packages and deliverables",
    ),
    "timeline": (
        "timeline", "milestones", "gantt chart", "project schedule",
        "month-wise implementation schedule", "month wise implementation schedule",
    ),
    "team": (
        "project team", "principal investigator", "investigators", "team details",
        "project team and responsibilities",
    ),
    "experience": ("experience", "track record", "previous projects", "publications"),
    "partner": ("industry partner", "collaboration", "support letter", "mou"),
    "collaboration": ("collaboration", "consortium", "partner institutions"),
    "commercialisation": (
        "commercialisation", "commercialization", "technology transfer", "deployment plan",
        "commercialisation and deployment pathway", "commercialization and deployment pathway",
    ),
    "impact": (
        "impact", "expected outcomes", "benefits", "adoption", "expected outputs and impact",
    ),
    "economics": ("economic benefit", "cost benefit", "payback", "return on investment", "roi"),
    "strategic_alignment": (
        "strategic fit", "atmanirbhar", "net zero", "national priority",
        "alignment with scheme and national priorities",
    ),
    "safety_environment": (
        "safety", "environment", "emissions", "waste", "water",
        "safety, environmental and ethical compliance",
        "safety environmental and ethical compliance",
    ),
    "inclusivity": ("inclusivity", "women researchers", "sc/st", "rural innovators"),
    "budget": (
        "budget", "cost estimate", "financial prudence", "budget summary and justification",
    ),
    "financial": ("financial", "fund utilisation", "fund utilization", "expenditure"),
    "risk": ("risk", "dependencies", "mitigation", "contingency", "risk management"),
    "compliance": (
        "compliance", "statutory approvals", "dgms", "regulatory", "proposal certification",
    ),
    "declarations": ("declaration", "undertaking", "certification"),
    "annexures": ("annexure", "appendix", "enclosure"),
}


def _heading_pattern(label: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?im)^\s*(?:#{1,6}\s*)?(?:\d+(?:\.\d+)*[.)-]?\s*)?{re.escape(label)}\s*(?:[:\-–—]\s*)?$"
    )


@lru_cache(maxsize=8)
def load_evidence_contracts(scheme_code: str, version: str = "1") -> dict[str, Any]:
    path = CONTRACT_DIR / f"{scheme_code.lower()}-evidence-contracts-v{version}.yaml"
    if not path.is_file():
        return {"contract_version": version, "scheme_code": scheme_code, "defaults": {}, "criteria": {}}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Evidence contract file {path} must contain a mapping")
    return raw


def criterion_contract(scheme_code: str, criterion_id: str, version: str = "1") -> dict[str, Any]:
    contracts = load_evidence_contracts(scheme_code, version)
    defaults = contracts.get("defaults", {}) if isinstance(contracts.get("defaults"), dict) else {}
    criteria = contracts.get("criteria", {}) if isinstance(contracts.get("criteria"), dict) else {}
    specific = criteria.get(criterion_id, {}) if isinstance(criteria.get(criterion_id), dict) else {}
    return {**defaults, **specific, "contract_version": str(contracts.get("contract_version", version))}


def detect_section_spans(text: str) -> list[dict[str, Any]]:
    matches: list[tuple[int, str, str]] = []
    for section_type, labels in _SECTION_PATTERNS.items():
        for label in labels:
            for match in _heading_pattern(label).finditer(text):
                matches.append((match.start(), section_type, match.group(0).strip()))
    matches.sort(key=lambda item: item[0])
    deduplicated: list[tuple[int, str, str]] = []
    for item in matches:
        if deduplicated and abs(item[0] - deduplicated[-1][0]) < 3:
            continue
        deduplicated.append(item)
    spans: list[dict[str, Any]] = []
    for index, (start, section_type, heading) in enumerate(deduplicated):
        end = deduplicated[index + 1][0] if index + 1 < len(deduplicated) else len(text)
        spans.append({"section_type": section_type, "heading": heading, "char_start": start, "char_end": end})
    return spans


def section_for_offset(spans: list[dict[str, Any]], offset: int) -> str:
    for span in spans:
        if int(span["char_start"]) <= offset < int(span["char_end"]):
            return str(span["section_type"])
    return "unclassified"


def passage_allowed(
    contract: dict[str, Any],
    *,
    document_role: str,
    section_type: str,
    keyword_hits: int,
) -> bool:
    allowed_roles = [str(item) for item in contract.get("allowed_document_roles", ["main_proposal"])]
    if document_role not in allowed_roles:
        return False
    allowed_sections = [str(item) for item in contract.get("allowed_sections", [])]
    minimum_hits = int(contract.get("minimum_keyword_hits", 1))
    if keyword_hits < minimum_hits:
        return False
    if not allowed_sections or section_type in allowed_sections:
        return True
    if section_type == "unclassified" and bool(contract.get("allow_unclassified_section", True)):
        return keyword_hits >= int(contract.get("unclassified_min_keyword_hits", max(2, minimum_hits)))
    return False


def has_local_negation(text: str, keywords: list[str]) -> bool:
    """Detect explicit denial close to a matched evidence phrase.

    Both prefix and suffix contexts are checked so statements such as
    ``foreign travel is not requested`` cannot be mistaken for support.
    """

    lower = text.lower()
    marker = r"\b(?:no|not|none|without|lacks?|lacking|absent|never|neither|not\s+planned|not\s+available|not\s+requested)\b"
    for keyword in keywords:
        start = 0
        needle = keyword.lower()
        while True:
            index = lower.find(needle, start)
            if index < 0:
                break
            prefix = lower[max(0, index - 55):index]
            suffix = lower[index + len(needle): index + len(needle) + 55]
            if re.search(marker + r"[^.!?]{0,45}$", prefix):
                return True
            if re.search(r"^[^.!?]{0,25}" + marker, suffix):
                return True
            start = index + max(len(needle), 1)
    return False
