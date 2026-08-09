"""Deterministic weak-supervision dataset generation from the MoC brochure rubric.

The generated records are for software/bootstrap validation only. They are not
historical MoC decisions and must never be represented as institutional labels.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class CriterionDefinition:
    criterion_id: str
    category: str
    maximum: float
    positive: tuple[str, ...]
    weak: tuple[str, ...]


_COMMON_INTROS = (
    "This research proposal addresses a coal-sector operational problem through a staged technology-development programme.",
    "The project is submitted for preliminary consideration under the Ministry of Coal research and development scheme.",
    "The consortium proposes an applied R&D programme for safer, cleaner, and more productive coal operations.",
    "The proposed work combines laboratory development, field validation, and an industry-facing deployment plan.",
)

_COAL_CONTEXT = (
    "The operating context includes opencast and underground coal mines, washeries, coal handling plants, and mine-support systems.",
    "The intended users include coal PSUs, CMPDI technical groups, mine operators, safety teams, and technology partners.",
    "The baseline problem affects productivity, safety, environmental performance, cost, or domestic technology capability.",
    "The proposal uses measurable technical, economic, and operational indicators rather than relying only on narrative claims.",
)

_SECTION_LEADS = (
    "Evidence supplied by the applicant:",
    "The proposal records the following:",
    "The project team states:",
    "Supporting information includes:",
)


_HIGH_CONFIDENCE_SENTENCES = (
    "The claim is supported by a named owner, a measurable baseline, a target, and a verification milestone.",
    "Supporting annexures identify documentary evidence, responsible personnel, dates, and acceptance criteria.",
    "The evidence is quantified, traceable to a work package, and scheduled for independent verification.",
    "A responsible organisation, measurable indicator, decision gate, and fallback action are explicitly recorded.",
    "The proposal links this claim to baseline data, a numerical target, a verification method, and an accountable lead.",
    "Commitment evidence and implementation details are supplied rather than relying on a general statement.",
    "The section provides specific quantities, named partners, ownership, and a testable completion condition.",
    "Evidence quality is strengthened by dates, roles, supporting documents, and a measurable success threshold.",
)

_OMISSION_SENTENCES = (
    "No verifiable evidence is supplied for this requirement.",
    "The document does not contain enough information to evaluate this point.",
    "This aspect is omitted and would require clarification during expert review.",
)


def _mapping(value: object, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _mapping_list(value: object, *, context: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")
    return [_mapping(item, context=f"{context}[{index}]") for index, item in enumerate(value)]


def load_definitions(rubric_path: Path, spec_path: Path) -> tuple[dict[str, Any], list[CriterionDefinition]]:
    rubric = _mapping(yaml.safe_load(rubric_path.read_text(encoding="utf-8")), context="rubric")
    spec = _mapping(yaml.safe_load(spec_path.read_text(encoding="utf-8")), context="spec")
    spec_criteria = _mapping(spec.get("criteria"), context="spec.criteria")

    definitions: list[CriterionDefinition] = []
    for category in _mapping_list(rubric.get("categories"), context="rubric.categories"):
        category_name = str(category.get("name", "Uncategorised"))
        for criterion in _mapping_list(category.get("criteria"), context=f"{category_name}.criteria"):
            criterion_id = str(criterion["id"])
            phrase_spec = _mapping(spec_criteria.get(criterion_id), context=f"spec.criteria.{criterion_id}")
            positive = tuple(str(item) for item in phrase_spec.get("positive", []) if str(item).strip())
            weak = tuple(str(item) for item in phrase_spec.get("weak", []) if str(item).strip())
            if not positive or not weak:
                raise ValueError(f"Criterion {criterion_id} needs positive and weak phrases")
            definitions.append(
                CriterionDefinition(
                    criterion_id=criterion_id,
                    category=category_name,
                    maximum=float(criterion["maximum"]),
                    positive=positive,
                    weak=weak,
                )
            )

    if round(sum(item.maximum for item in definitions), 6) != float(rubric.get("total_marks", 100)):
        raise ValueError("Rubric criteria do not sum to the declared total")

    return spec, definitions


def _level(rng: random.Random) -> int:
    value = rng.random()
    if value < 0.22:
        return 0
    if value < 0.48:
        return 1
    if value < 0.78:
        return 2
    return 3


def _score_ratio(level: int, rng: random.Random) -> float:
    centres = {0: 0.03, 1: 0.28, 2: 0.63, 3: 0.91}
    spread = {0: 0.025, 1: 0.06, 2: 0.07, 3: 0.045}
    return max(0.0, min(1.0, centres[level] + rng.uniform(-spread[level], spread[level])))


def _criterion_text(definition: CriterionDefinition, level: int, rng: random.Random) -> list[str]:
    if level == 0:
        return [rng.choice(_OMISSION_SENTENCES)] if rng.random() < 0.28 else []
    if level == 1:
        return [rng.choice(definition.weak)]
    if level == 2:
        return [rng.choice(definition.positive)]
    choices = list(definition.positive)
    rng.shuffle(choices)
    selected = choices[: min(2, len(choices))]
    selected.append(rng.choice(_HIGH_CONFIDENCE_SENTENCES))
    return selected


def generate_records(
    rubric_path: Path,
    spec_path: Path,
    output_path: Path,
    *,
    rows: int | None = None,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    spec, definitions = load_definitions(rubric_path, spec_path)
    record_count = int(rows if rows is not None else spec.get("rows", 1200))
    random_seed = int(seed if seed is not None else spec.get("seed", 20260706))
    # Reproducible synthetic sampling; no security-sensitive randomness.
    rng = random.Random(random_seed)  # nosec B311
    by_category: dict[str, list[CriterionDefinition]] = {}
    for definition in definitions:
        by_category.setdefault(definition.category, []).append(definition)

    records: list[dict[str, Any]] = []
    for row_index in range(record_count):
        family = row_index % 12
        paragraphs = [rng.choice(_COMMON_INTROS), rng.choice(_COAL_CONTEXT)]
        scores: dict[str, float] = {}
        levels: dict[str, int] = {}
        criterion_evidence: dict[str, str] = {}

        for category_index, (category, category_definitions) in enumerate(by_category.items(), start=1):
            category_lines: list[str] = []
            for definition in category_definitions:
                level = _level(rng)
                levels[definition.criterion_id] = level
                scores[definition.criterion_id] = round(
                    _score_ratio(level, rng) * definition.maximum,
                    3,
                )
                evidence_lines = _criterion_text(definition, level, rng)
                criterion_context = [rng.choice(_COMMON_INTROS), rng.choice(_COAL_CONTEXT)]
                criterion_evidence[definition.criterion_id] = " ".join(
                    [*criterion_context, *evidence_lines]
                )
                category_lines.extend(evidence_lines)
            if category_lines:
                rng.shuffle(category_lines)
                paragraphs.append(
                    f"Section {category_index}: {category}. {rng.choice(_SECTION_LEADS)}\n"
                    + " ".join(category_lines)
                )

        if rng.random() < 0.45:
            paragraphs.append(rng.choice(_COAL_CONTEXT))
        if rng.random() < 0.20:
            paragraphs.append(
                "The document contains supporting tables and annexures, but only evidence stated in the proposal body is used for this bootstrap record."
            )

        records.append(
            {
                "record_id": f"bootstrap-{row_index + 1:05d}",
                "scheme_code": "MOC-ST",
                "rubric_version": "2.0",
                "proposal_group": f"template-family-{family:02d}",
                "label_origin": "brochure-derived weak supervision",
                "text": "\n\n".join(paragraphs),
                "criterion_scores": scores,
                "generation_levels": levels,
                "criterion_evidence": criterion_evidence,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return records
