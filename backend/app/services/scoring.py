"""Evidence-based scoring service applying the 100-mark rubric.

Scores each rubric criterion using keyword evidence extracted from proposal
documents. Returns scores with evidence coverage, supporting passages, and
abstention markers.

This is a transparent, rule-based heuristic scorer, not a trained ML model.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, TypeAlias, TypedDict

import yaml

from app.services.evidence_contracts import (
    criterion_contract,
    detect_section_spans,
    has_local_negation,
    passage_allowed,
    section_for_offset,
)


JsonObject: TypeAlias = dict[str, Any]


class KeywordMatch(TypedDict):
    """A keyword match found in the proposal text."""

    keyword: str
    count: int
    positions: list[int]


class CriterionScore(TypedDict):
    """Structured result for one rubric criterion."""

    awarded_score: float | None
    maximum_score: float
    ordinal_grade: int | None
    criterion_status: str
    released: bool
    evidence_coverage: float
    information_sufficiency: float
    evidence_count: int
    evidence: list[dict[str, Any]]
    rejected_evidence: list[dict[str, Any]]
    missing_evidence: list[str]
    rationale: str


RUBRIC_DIR = Path(__file__).resolve().parents[3] / "data" / "rules"


def _rubric_version_file_candidates(version: str) -> list[str]:
    """Return compatible rubric-version filename candidates."""

    candidates = [version]

    if version.endswith(".0"):
        candidates.append(version[:-2])

    return candidates


def _as_mapping(value: object, *, context: str) -> JsonObject:
    """Validate and normalise an externally loaded mapping."""

    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping")

    return {str(key): item for key, item in value.items()}


def _as_mapping_list(value: object, *, context: str) -> list[JsonObject]:
    """Validate a list whose members must all be mappings."""

    if value is None:
        return []

    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")

    result: list[JsonObject] = []

    for index, item in enumerate(value):
        result.append(
            _as_mapping(
                item,
                context=f"{context}[{index}]",
            )
        )

    return result


def _as_string(value: object, *, default: str = "") -> str:
    """Return a string value or a safe default."""

    if isinstance(value, str):
        return value

    return default


def _as_float(value: object, *, default: float = 0.0) -> float:
    """Convert a numeric configuration value to float safely."""

    if isinstance(value, bool):
        return default

    if isinstance(value, int | float):
        return float(value)

    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default

    return default


def _load_rubric(
    scheme_code: str,
    version: str = "1",
) -> JsonObject | None:
    """Load and validate a rubric YAML document."""

    for candidate in _rubric_version_file_candidates(version):
        path = (
            RUBRIC_DIR
            / f"{scheme_code.lower()}-100-mark-rubric-v{candidate}.yaml"
        )

        if not path.exists():
            continue

        with path.open("r", encoding="utf-8") as file:
            raw_data: object = yaml.safe_load(file)

        if raw_data is None:
            return None

        rubric = _as_mapping(
            raw_data,
            context=f"Rubric file {path}",
        )

        categories = rubric.get("categories")

        if categories is not None and not isinstance(categories, list):
            raise ValueError(
                f"Rubric file {path} contains an invalid 'categories' value"
            )

        return rubric

    return None


def _grade_ordinal(match_score: float, max_score: float) -> int:
    """Convert the weighted criterion score into an ordinal grade."""

    if max_score <= 0:
        return 0

    ratio = match_score / max_score

    if ratio >= 0.9:
        return 5
    if ratio >= 0.7:
        return 4
    if ratio >= 0.5:
        return 3
    if ratio >= 0.3:
        return 2
    if ratio >= 0.1:
        return 1

    return 0


_CRITERION_KEYWORDS: dict[str, list[str]] = {
    "coal-specific-problem": [
        "coal",
        "lignite",
        "mine",
        "opencast",
        "underground",
        "coal india",
        "cmpdi",
        "block",
        "seam",
        "grade",
        "ash content",
        "washing",
    ],
    "thrust-area-justification": [
        "thrust area",
        "alignment",
        "relevance",
        "priority area",
    ],
    "r&d-content": [
        "research",
        "develop",
        "investigat",
        "novel",
        "innovative",
        "proof of concept",
        "pilot",
        "prototype",
    ],
    "significance": [
        "significant",
        "critical",
        "important",
        "benefit",
        "impact",
        "safety",
        "productivity",
        "cost reduction",
        "emission",
    ],
    "prior-work-review": [
        "literature",
        "prior work",
        "existing",
        "previous study",
        "state of the art",
        "review",
    ],
    "research-gap": [
        "research gap",
        "gap",
        "limitation",
        "not addressed",
        "lacking",
        "not been studied",
        "no study",
    ],
    "scientific-contribution": [
        "novel",
        "new approach",
        "innovative method",
        "first time",
        "breakthrough",
        "indigenous",
        "indigenisation",
    ],
    "indigenisation": [
        "make in india",
        "atmanirbhar",
        "indigenous",
        "import substitution",
        "self-reliant",
        "local manufacturing",
    ],
    "ipr-potential": [
        "patent",
        "copyright",
        "ipr",
        "intellectual property",
        "design registration",
        "utility model",
    ],
    "duplication-risk": [
        "duplication",
        "overlap",
        "existing project",
        "similar work",
        "already done",
    ],
    "objective-clarity": [
        "objective",
        "aim",
        "goal",
        "purpose",
        "specific",
        "measurable",
        "quantifiable",
    ],
    "objective-output-mapping": [
        "output",
        "deliverable",
        "outcome",
        "expected result",
        "target",
        "success criterion",
    ],
    "scientific-validity": [
        "methodology",
        "approach",
        "method",
        "technique",
        "scientific",
        "validity",
        "rigorous",
    ],
    "experimental-design": [
        "experiment",
        "trial",
        "field study",
        "lab study",
        "baseline",
        "control",
        "comparison",
        "sampling",
    ],
    "data-plan": [
        "data collection",
        "data analysis",
        "statistical",
        "monitoring",
        "sensor",
        "measurement",
    ],
    "validation-protocol": [
        "validation",
        "testing",
        "verification",
        "acceptance criteria",
        "success criteria",
        "failure criteria",
        "milestone",
    ],
    "pi-expertise": [
        "phd",
        "professor",
        "scientist",
        "head",
        "expertise",
        "experienced",
        "specialist",
    ],
    "past-performance": [
        "completed project",
        "sanctioned",
        "earlier",
        "previous",
        "track record",
        "publication",
    ],
    "institutional-facilities": [
        "laboratory",
        "facility",
        "equipment",
        "infrastructure",
        "centre",
        "center",
        "institute",
    ],
    "collaborator-strength": [
        "collaboration",
        "partner",
        "joint",
        "consortium",
        "collaborating",
        "co-investigator",
    ],
    "conflict-check": [
        "conflict",
        "vendor",
        "supplier",
        "proprietary",
    ],
    "work-package-structure": [
        "work package",
        "wp",
        "task",
        "activity",
        "responsibility",
        "team",
        "division",
    ],
    "milestones": [
        "milestone",
        "timeline",
        "gantt",
        "schedule",
        "phase",
        "month",
        "quarter",
        "year",
    ],
    "schedule-realism": [
        "pert",
        "bar chart",
        "critical path",
        "realistic",
        "feasible timeline",
    ],
    "procurement-recruitment": [
        "procurement",
        "recruitment",
        "hiring",
        "purchase",
        "manpower",
        "staff",
    ],
    "backup-paths": [
        "alternative",
        "backup",
        "contingency",
        "fallback",
        "risk mitigation",
        "plan b",
    ],
    "industry-benefit": [
        "benefit",
        "productivity",
        "safety improvement",
        "cost saving",
        "revenue",
        "efficiency",
    ],
    "end-user": [
        "end user",
        "beneficiary",
        "mine",
        "colliery",
        "area",
        "deployment site",
        "field trial",
    ],
    "commitment-evidence": [
        "mou",
        "letter of support",
        "commitment",
        "undertaking",
        "endorsement",
        "agreement",
    ],
    "scale-up-plan": [
        "scale up",
        "replication",
        "commercialisation",
        "technology transfer",
        "deployment",
    ],
    "post-project-ownership": [
        "maintenance",
        "ownership",
        "sustenance",
        "after project",
        "post-project",
        "handover",
    ],
    "budget-consistency": [
        "budget",
        "cost",
        "expenditure",
        "head",
        "summary",
    ],
    "quotations": [
        "quotation",
        "cost estimate",
        "rate",
        "price",
        "proforma",
    ],
    "equipment-justification": [
        "justification",
        "equipment",
        "instrument",
        "procure",
    ],
    "milestone-linking": [
        "phasing",
        "installment",
        "release",
        "tranche",
        "milestone-based",
        "linked",
    ],
    "value-for-money": [
        "cost effective",
        "value for money",
        "economical",
        "optimal",
        "efficient use",
    ],
    "statutory-requirements": [
        "dgms",
        "statutory",
        "legal",
        "compliance",
        "clearance",
        "permission",
        "approval required",
    ],
    "environmental-permissions": [
        "environmental clearance",
        "moef",
        "consent",
        "pollution",
        "environmental impact",
    ],
    "risk-register": [
        "risk",
        "mitigation",
        "risk register",
        "risk assessment",
        "risk owner",
    ],
    "operational-risks": [
        "operational risk",
        "technical risk",
        "failure",
        "delay",
        "challenge",
        "bottleneck",
    ],
    "contingency-exit": [
        "contingency plan",
        "exit strategy",
        "termination",
        "discontinuation",
        "alternative plan",
    ],
}

# Brochure-aligned v2 criteria. These terms are used only for evidence retrieval
# and the transparent contextual fallback; the trained ML model supplies the
# primary statistical prediction.
_CRITERION_KEYWORDS.update({
    "uniqueness-vs-past-work": [
        "prior work", "earlier project", "previous project", "literature",
        "state of the art", "comparison", "research gap", "differentiate",
        "novel", "unique", "not been addressed", "joint optimisation",
        "joint optimization", "hybrid model", "first-principles",
        "first principles", "confidence-bounded",
    ],
    "patent-ip-potential": [
        "patent", "patentability", "ipr", "intellectual property", "license",
        "licensing", "trade secret", "know-how", "design right", "copyright",
    ],
    "indigenisation-potential": [
        "indigenous", "indigenisation", "indigenization", "import substitution",
        "make in india", "atmanirbhar", "domestic manufacturing", "local supplier",
        "domestic equipment", "local skill development", "domestic coal",
    ],
    "technical-clarity": [
        "architecture", "flowchart", "block diagram", "drawing", "algorithm",
        "process flow", "technical approach", "interface", "assumption", "methodology",
        "sampling plan", "data acquisition", "cross-validation",
        "cross validation", "engineering constraint",
    ],
    "trl-advancement": [
        "trl", "technology readiness", "proof of concept", "prototype",
        "pilot", "demonstration", "relevant environment", "validation gate",
    ],
    "infrastructure-readiness": [
        "laboratory", "infrastructure", "test rig", "machine", "instrument",
        "software licence", "workshop", "test site", "facility", "calibration",
    ],
    "team-track-record": [
        "principal investigator", "pi", "experience", "track record",
        "completed project", "publication", "deployment", "phd", "expertise",
    ],
    "workplan-milestones": [
        "work plan", "workplan", "work package", "work packages", "milestone",
        "timeline", "phase", "responsibility", "deliverable", "pert", "gantt",
        "backup path",
    ],
    "adoption-likelihood": [
        "industry partner", "coal psu", "mou", "support letter", "deployment site",
        "end user", "technology transfer", "adoption", "pilot host", "acceptance authority",
        "demonstration partner", "joint design review", "deployment pathway",
    ],
    "economic-benefit-ratio": [
        "benefit-cost", "cost benefit", "economic benefit", "annual saving",
        "payback", "productivity", "downtime", "cost reduction", "financial benefit",
    ],
    "safety-environment-impact": [
        "safety", "incident reduction", "emission", "particulate", "waste",
        "water", "environmental", "reclamation", "exposure", "monitoring indicator",
    ],
    "strategic-fit": [
        "atmanirbhar bharat", "net zero", "sustainability", "energy security",
        "national priority", "coal sector priority", "circular economy", "make in india",
        "domestic coal", "coal utilisation", "coal utilization", "local skill development",
    ],
    "sc-st-participation": [
        "sc/st", "sc and st", "scheduled caste", "scheduled tribe",
        "inclusive participation", "reserved category",
    ],
    "women-researchers": [
        "women researcher", "woman pi", "female researcher", "women participation",
        "women constitute", "women researchers", "woman co-pi",
        "female co-pi", "gender participation",
    ],
    "startup-rural-innovators": [
        "startup", "msme", "rural innovator", "field innovator",
        "local fabricator", "innovation partner",
    ],
    "multi-agency-collaboration": [
        "collaboration", "consortium", "university", "coal psu", "cmpdi",
        "industry partner", "demonstration partner", "joint design review",
        "joint governance", "work package", "multi-agency",
    ],
    "budget-realism": [
        "budget", "quotation", "cost estimate", "quantity", "rate", "tax",
        "head-wise", "arithmetic", "cost justification", "consumables",
    ],
    "phased-funding": [
        "phased funding", "fund release", "installment", "tranche", "cash flow",
        "milestone-linked", "utilisation", "quarterly", "year-wise",
        "year 1", "year 2",
    ],
    "roi-realism": [
        "roi", "return on investment", "payback", "sensitivity analysis",
        "downside scenario", "financial assumption", "scaled deployment",
    ],
    "manpower-cost-ratio": [
        "manpower cost", "manpower ratio", "personnel cost", "staff cost",
        "30 percent", "30%", "role duration rate",
    ],
    "dependencies-listed": [
        "dependency", "equipment supply", "site access", "data access",
        "permission", "power supply", "network connectivity", "partner availability",
        "feed variability", "fabrication delay", "sensor drift", "missing data",
    ],
    "mitigation-plans": [
        "mitigation", "risk owner", "alternate supplier", "backup site",
        "trigger", "contingency", "recovery action", "alternative path",
    ],
    "compliance-readiness": [
        "dgms", "environmental clearance", "safety approval", "regulatory",
        "permission", "procurement compliance", "ethics", "data security",
        "statutory approval", "safety procedures", "authorised channels",
        "authorized channels", "pre-run permits",
    ],
})



def _page_for_offset(text: str, offset: int) -> int | None:
    page = None
    for match in re.finditer(r"\[PAGE\s+(\d+)\]", text[: max(0, offset) + 1], re.IGNORECASE):
        page = int(match.group(1))
    return page


def _passages(
    text: str,
    *,
    document_role: str = "main_proposal",
    document_id: str | None = None,
    file_name: str | None = None,
) -> list[dict[str, Any]]:
    """Split one package document into auditable passages with provenance."""

    boundary = re.compile(r"(?:\n{2,}|(?<=[.!?])\s+)")
    section_spans = detect_section_spans(text)
    passages: list[dict[str, Any]] = []
    cursor = 0
    for chunk in boundary.split(text):
        stripped = chunk.strip()
        if not stripped:
            cursor += len(chunk) + 1
            continue
        start = text.find(stripped, cursor)
        if start < 0:
            start = cursor
        end = start + len(stripped)
        cursor = end
        cleaned = re.sub(r"\[PAGE\s+\d+\]", "", stripped, flags=re.IGNORECASE).strip()
        section_type = section_for_offset(section_spans, start)
        # Section headings establish provenance but are not themselves evidence.
        # Removing the heading prevents a heading keyword plus one generic term
        # from satisfying a multi-term criterion contract.
        for span in section_spans:
            if int(span["char_start"]) != start:
                continue
            heading = str(span.get("heading", "")).strip()
            if heading and cleaned.lower().startswith(heading.lower()):
                cleaned = cleaned[len(heading):].lstrip(" \t\r\n:-–—")
            break
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9&/'-]*", cleaned)
        if len(words) < 5:
            continue
        passages.append(
            {
                "text": cleaned[:900],
                "lower": cleaned.lower(),
                "char_start": start,
                "char_end": end,
                "word_count": len(words),
                "page": _page_for_offset(text, start),
                "section_type": section_type,
                "document_role": document_role,
                "document_id": document_id,
                "file_name": file_name,
            }
        )
    return passages


def _document_quality(text: str, passages: list[dict[str, Any]]) -> dict[str, Any]:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9&/'-]*", text.lower())
    if not words:
        return {"factor": 0.0, "word_count": 0, "passage_count": 0, "repetition_penalty": 1.0}

    unique_ratio = len(set(words)) / len(words)
    counts: dict[str, int] = {}
    for word in words:
        if len(word) > 2:
            counts[word] = counts.get(word, 0) + 1
    dominant_ratio = max(counts.values(), default=0) / max(len(words), 1)
    token_penalty = max(0.35, 1.0 - max(0.0, dominant_ratio - 0.04) * 5.0)
    shingles = [tuple(words[index : index + 5]) for index in range(max(0, len(words) - 4))]
    shingle_unique_ratio = (len(set(shingles)) / len(shingles)) if shingles else 1.0
    sequence_penalty = max(0.20, min(1.0, shingle_unique_ratio / 0.35))
    repetition_penalty = min(token_penalty, sequence_penalty)
    length_factor = min(1.0, len(words) / 300.0)
    passage_factor = min(1.0, len(passages) / 10.0)
    lexical_factor = min(1.0, unique_ratio / 0.45)
    # A bag of every keyword in one line must never receive a near-perfect score.
    factor = min(1.0, (0.35 * length_factor) + (0.45 * passage_factor) + (0.20 * lexical_factor))
    factor *= repetition_penalty
    return {
        "factor": round(factor, 3),
        "word_count": len(words),
        "passage_count": len(passages),
        "unique_word_ratio": round(unique_ratio, 3),
        "shingle_unique_ratio": round(shingle_unique_ratio, 3),
        "repetition_penalty": round(repetition_penalty, 3),
    }


def _unresolved_criterion(
    max_score: float,
    reason: str,
    *,
    rejected: list[dict[str, Any]] | None = None,
) -> CriterionScore:
    return {
        "awarded_score": None,
        "maximum_score": max_score,
        "ordinal_grade": None,
        "criterion_status": "unresolved",
        "released": False,
        "evidence_coverage": 0.0,
        "information_sufficiency": 0.0,
        "evidence_count": 0,
        "evidence": [],
        "rejected_evidence": rejected or [],
        "missing_evidence": [reason],
        "rationale": reason,
    }


def _score_criterion(
    criterion_id: str,
    max_score: float,
    text: str,
    passages: list[dict[str, Any]] | None = None,
    quality_factor: float = 1.0,
    *,
    scheme_code: str = "MOC-ST",
    document_role: str = "main_proposal",
    contract_version: str = "1",
) -> CriterionScore:
    """Score only contract-accepted evidence; missing evidence never earns marks."""

    keywords = _CRITERION_KEYWORDS.get(criterion_id, [])
    if not keywords or not text.strip():
        return _unresolved_criterion(
            max_score,
            "No configured evidence terms or proposal text is empty",
        )

    contract = criterion_contract(scheme_code, criterion_id, contract_version)
    evidence_passages = passages if passages is not None else _passages(text)
    matched_keywords: set[str] = set()
    matched_passage_indexes: set[int] = set()
    evidence: list[dict[str, Any]] = []
    rejected_evidence: list[dict[str, Any]] = []

    for passage_index, passage in enumerate(evidence_passages):
        lower = str(passage["lower"])
        found = [
            keyword
            for keyword in keywords
            if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", lower)
        ]
        if not found:
            continue
        section_type = str(passage.get("section_type", "unclassified"))
        rejection_reason: str | None = None
        density = len(found) / max(int(passage["word_count"]), 1)
        if density > 0.30 and int(passage["word_count"]) < 30:
            rejection_reason = "keyword_density"
        elif has_local_negation(str(passage["text"]), found):
            rejection_reason = "negated_or_contradictory"
        passage_document_role = str(
            passage.get("document_role") or document_role
        )
        elif_not_allowed = not passage_allowed(
            contract,
            document_role=passage_document_role,
            section_type=section_type,
            keyword_hits=len(found),
        )
        if rejection_reason is None and elif_not_allowed:
            rejection_reason = "evidence_contract_rejected"

        evidence_item = {
            "keyword": found[0],
            "keywords": found[:6],
            "count": len(found),
            "text": passage["text"],
            "source_page": passage.get("page"),
            "source_section": section_type,
            "document_role": passage_document_role,
            "document_id": passage.get("document_id"),
            "file_name": passage.get("file_name"),
            "char_start": passage["char_start"],
            "char_end": passage["char_end"],
            "contract_version": contract.get("contract_version", contract_version),
        }
        if rejection_reason:
            rejected_evidence.append(
                {**evidence_item, "verification_status": rejection_reason}
            )
            continue

        matched_keywords.update(found)
        matched_passage_indexes.add(passage_index)
        evidence.append(
            {
                **evidence_item,
                "relevance_score": round(
                    min(1.0, 0.35 + 0.15 * len(found)),
                    2,
                ),
                "verification_status": "contract_accepted",
            }
        )

    if not evidence:
        return _unresolved_criterion(
            max_score,
            "No evidence passage satisfied the criterion evidence contract",
            rejected=rejected_evidence[:5],
        )

    keyword_coverage = min(
        1.0,
        len(matched_keywords) / max(2.0, len(keywords) * 0.5),
    )
    passage_diversity = min(1.0, len(matched_passage_indexes) / 3.0)
    context_depth = min(
        1.0,
        sum(
            min(int(item["word_count"]), 40)
            for index, item in enumerate(evidence_passages)
            if index in matched_passage_indexes
        ) / 70.0,
    )
    evidence_strength = (
        (0.50 * keyword_coverage)
        + (0.30 * passage_diversity)
        + (0.20 * context_depth)
    )
    score_ratio = evidence_strength * max(0.0, min(1.0, quality_factor))
    awarded_score = round(min(max_score, score_ratio * max_score), 1)
    information_sufficiency = round(
        min(
            1.0,
            (0.55 * passage_diversity) + (0.45 * keyword_coverage),
        ) * quality_factor,
        2,
    )
    criterion_status = (
        "supported" if evidence_strength >= 0.50 else "partially_supported"
    )

    return {
        "awarded_score": awarded_score,
        "maximum_score": max_score,
        "ordinal_grade": _grade_ordinal(awarded_score, max_score),
        "criterion_status": criterion_status,
        "released": True,
        "evidence_coverage": round(evidence_strength, 2),
        "information_sufficiency": information_sufficiency,
        "evidence_count": len(evidence),
        "evidence": evidence[:5],
        "rejected_evidence": rejected_evidence[:5],
        "missing_evidence": [],
        "rationale": (
            f"Accepted {len(evidence)} evidence passage(s) under contract "
            f"{contract.get('contract_version', contract_version)} with "
            f"{len(matched_keywords)}/{len(keywords)} distinct evidence terms."
        ),
    }


async def score_proposal(
    scheme_code: str,
    extracted_text: str,
    rubric_version: str = "1",
    *,
    document_role: str = "main_proposal",
    evidence_contract_version: str = "1",
    documents: list[dict[str, Any]] | None = None,
) -> JsonObject:
    """Score a proposal against the selected rubric with fail-closed evidence rules."""

    rubric = _load_rubric(scheme_code, rubric_version)
    if rubric is None:
        return {
            "error": f"No rubric found for scheme {scheme_code} version {rubric_version}",
            "total_score": None,
            "diagnostic_score": None,
            "maximum_score": 0.0,
            "evidence_coverage": 0.0,
            "information_sufficiency": 0.0,
            "category_scores": [],
            "model_source": "contextual-rule-heuristic-v3",
            "scoring_status": "configuration_error",
            "abstention": True,
            "abstention_reasons": ["rubric configuration is unavailable"],
            "decision_recommendation": None,
        }

    categories = _as_mapping_list(
        rubric.get("categories"),
        context="rubric.categories",
    )
    main_passages = _passages(
        extracted_text,
        document_role=document_role,
    )
    evidence_passages = main_passages
    package_documents = documents or []
    if package_documents:
        evidence_passages = []
        for package_document in package_documents:
            document_text = str(package_document.get("text") or "")
            if not document_text.strip():
                continue
            evidence_passages.extend(
                _passages(
                    document_text,
                    document_role=str(
                        package_document.get("document_role") or "unknown"
                    ),
                    document_id=(
                        str(package_document.get("document_id"))
                        if package_document.get("document_id")
                        else None
                    ),
                    file_name=(
                        str(package_document.get("file_name"))
                        if package_document.get("file_name")
                        else None
                    ),
                )
            )
    quality = _document_quality(extracted_text, main_passages)

    category_scores: list[JsonObject] = []
    total_awarded = 0.0
    total_maximum = 0.0
    weighted_sufficiency_sum = 0.0
    total_weight = 0.0
    released_criteria = 0

    for category_index, category in enumerate(categories):
        category_name = _as_string(category.get("name"))
        category_maximum = _as_float(category.get("maximum"))
        criteria = _as_mapping_list(
            category.get("criteria"),
            context=f"rubric.categories[{category_index}].criteria",
        )
        category_awarded = 0.0
        criterion_scores: list[JsonObject] = []

        for criterion in criteria:
            criterion_id = _as_string(criterion.get("id"))
            criterion_label = _as_string(criterion.get("label"))
            criterion_maximum = _as_float(criterion.get("maximum"))
            result = _score_criterion(
                criterion_id,
                criterion_maximum,
                extracted_text,
                evidence_passages,
                float(quality["factor"]),
                scheme_code=scheme_code,
                document_role=document_role,
                contract_version=evidence_contract_version,
            )
            criterion_scores.append(
                {
                    "criterion_id": criterion_id,
                    "label": criterion_label,
                    **result,
                }
            )
            awarded_score = result["awarded_score"]
            if awarded_score is not None:
                category_awarded += awarded_score
                total_awarded += awarded_score
                released_criteria += 1
            total_maximum += criterion_maximum
            weighted_sufficiency_sum += (
                result["information_sufficiency"] * criterion_maximum
            )
            total_weight += criterion_maximum

        category_scores.append(
            {
                "category": category_name,
                "maximum": category_maximum,
                "awarded": round(category_awarded, 1),
                "released": any(item.get("released") for item in criterion_scores),
                "criteria": criterion_scores,
            }
        )

    information_sufficiency = round(
        weighted_sufficiency_sum / max(total_weight, 1.0),
        3,
    )
    diagnostic_score = round(total_awarded, 1)
    abstention_reasons: list[str] = []
    if information_sufficiency < 0.25:
        abstention_reasons.append("supporting evidence coverage is insufficient")
    if float(quality["factor"]) < 0.30:
        abstention_reasons.append("document quality or repetition controls failed")
    if released_criteria < 6:
        abstention_reasons.append("too few criteria have contract-accepted evidence")
    abstention = bool(abstention_reasons)

    return {
        "scheme_code": scheme_code,
        "rubric_version": rubric_version,
        "total_score": None if abstention else diagnostic_score,
        "diagnostic_score": diagnostic_score,
        "maximum_score": total_maximum,
        "evidence_coverage": information_sufficiency,
        "information_sufficiency": information_sufficiency,
        "released_criterion_count": released_criteria,
        "category_scores": category_scores,
        "model_source": "contextual-rule-heuristic-v3",
        "document_quality": quality,
        "document_role": document_role,
        "submission_package_document_count": len(package_documents) if package_documents else 1,
        "evidence_contract_version": evidence_contract_version,
        "advisory_only": True,
        "scoring_status": "abstained" if abstention else "released",
        "abstention": abstention,
        "abstention_reasons": abstention_reasons,
        "decision_recommendation": None if abstention else "expert_review_required",
    }
