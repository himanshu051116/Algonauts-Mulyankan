"""Canonical structured proposal fields for the active MOC-ST workflow."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeAlias

import yaml


JsonObject: TypeAlias = dict[str, Any]

FIELD_SCHEMA_VERSION = "moc-st-fields-v1"
ACTIVE_SCHEME_CODE = "MOC-ST"
RULES_DIR = Path(__file__).resolve().parents[3] / "data" / "rules"

CANONICAL_FIELD_SCHEMA: dict[str, JsonObject] = {
    "institution_eligibility": {
        "extraction_method": "keyword_section_heuristic",
        "missing_value_policy": "unresolved",
    },
    "pi_qualification": {
        "extraction_method": "credential_keyword_heuristic",
        "missing_value_policy": "unresolved",
    },
    "project_duration": {
        "extraction_method": "duration_normalizer",
        "missing_value_policy": "unresolved",
        "unit": "months",
    },
    "duration_exception_above_24": {
        "extraction_method": "duration_justification_heuristic",
        "missing_value_policy": "clarification_required",
    },
    "thrust_area_alignment": {
        "extraction_method": "approved_thrust_area_keyword_match",
        "missing_value_policy": "unresolved",
    },
    "contingency_percentage": {
        "extraction_method": "percentage_pattern",
        "missing_value_policy": "unresolved",
        "unit": "percent",
    },
    "overhead_percentage": {
        "extraction_method": "percentage_pattern",
        "missing_value_policy": "unresolved",
        "unit": "percent",
    },
    "land_purchase": {
        "extraction_method": "prohibited_budget_item_heuristic",
        "missing_value_policy": "not_applicable",
    },
    "foreign_travel": {
        "extraction_method": "budget_line_keyword_heuristic",
        "missing_value_policy": "clarification_required",
    },
    "staff_vehicles": {
        "extraction_method": "prohibited_item_keyword_heuristic",
        "missing_value_policy": "not_applicable",
    },
    "permanent_salary": {
        "extraction_method": "prohibited_item_keyword_heuristic",
        "missing_value_policy": "not_applicable",
    },
    "routine_academic_study": {
        "extraction_method": "prohibited_scope_heuristic",
        "missing_value_policy": "not_applicable",
    },
    "industry_relevance": {
        "extraction_method": "industry_benefit_evidence_heuristic",
        "missing_value_policy": "unresolved",
    },
    "environmental_safety_compliance": {
        "extraction_method": "regulatory_compliance_evidence_heuristic",
        "missing_value_policy": "unresolved",
    },
    "equipment_duplication": {
        "extraction_method": "duplication_declaration_heuristic_v2",
        "missing_value_policy": "clarification_required",
    },
    "dgms_approval": {
        "extraction_method": "statutory_approval_keyword_heuristic",
        "missing_value_policy": "clarification_required",
    },
}


def _has_value(value: object) -> bool:
    """Return True when a field contains a meaningful value."""

    return value not in (None, "")


def _normalise_mapping(value: object, *, context: str) -> JsonObject:
    """Validate and normalise an externally loaded mapping."""

    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping")

    return {str(key): item for key, item in value.items()}


def _normalise_mapping_list(
    value: object,
    *,
    context: str,
) -> list[JsonObject]:
    """Validate a list containing mapping entries."""

    if value is None:
        return []

    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")

    result: list[JsonObject] = []

    for index, item in enumerate(value):
        result.append(
            _normalise_mapping(
                item,
                context=f"{context}[{index}]",
            )
        )

    return result


def _load_yaml_mapping(path: Path) -> JsonObject:
    """Load a YAML document whose root must be a mapping."""

    with path.open("r", encoding="utf-8") as file:
        raw_data: object = yaml.safe_load(file)

    if raw_data is None:
        raise ValueError(f"YAML file is empty: {path}")

    return _normalise_mapping(
        raw_data,
        context=f"YAML file {path}",
    )


def empty_field(field_name: str) -> JsonObject:
    """Create an empty canonical field using its configured policy."""

    spec = CANONICAL_FIELD_SCHEMA[field_name]

    return {
        "field_name": field_name,
        "schema_version": FIELD_SCHEMA_VERSION,
        "normalized_value": None,
        "unit": spec.get("unit"),
        "original_text": None,
        "page": None,
        "section": None,
        "extraction_method": spec["extraction_method"],
        "evidence_coverage": 0.0,
        "validation_warnings": [],
        "manually_corrected_value": None,
        "corrected_by": None,
        "corrected_at": None,
        "status": spec["missing_value_policy"],
    }


def canonicalize_extracted_fields(
    fields: list[JsonObject],
) -> JsonObject:
    """Convert extracted fields into the canonical MOC-ST structure."""

    canonical_fields: dict[str, JsonObject] = {
        field_name: empty_field(field_name)
        for field_name in CANONICAL_FIELD_SCHEMA
    }

    for field in fields:
        raw_field_name = field.get("field_name")

        if not isinstance(raw_field_name, str):
            continue

        field_name = raw_field_name.strip()

        if field_name not in CANONICAL_FIELD_SCHEMA:
            continue

        current = deepcopy(canonical_fields[field_name])

        normalized_value = field.get(
            "normalized_value",
            field.get("field_value"),
        )
        has_value = _has_value(normalized_value)

        incoming_status = field.get("status")
        if isinstance(incoming_status, str) and incoming_status.strip():
            status = incoming_status.strip()
        else:
            status = (
                "resolved"
                if has_value
                else str(current["status"])
            )

        incoming_coverage = field.get("evidence_coverage")
        if incoming_coverage is None:
            evidence_coverage = 1.0 if has_value else 0.0
        else:
            try:
                evidence_coverage = float(incoming_coverage)
            except (TypeError, ValueError):
                evidence_coverage = 1.0 if has_value else 0.0

        original_text = field.get("original_text")
        if original_text is None and normalized_value is not None:
            original_text = str(normalized_value)

        validation_warnings = field.get("validation_warnings", [])
        if not isinstance(validation_warnings, list):
            validation_warnings = [str(validation_warnings)]

        current.update(
            {
                "normalized_value": normalized_value,
                "unit": field.get(
                    "unit",
                    field.get("field_unit", current.get("unit")),
                ),
                "original_text": original_text,
                "page": field.get("page", field.get("source_page")),
                "section": field.get(
                    "section",
                    field.get("source_section"),
                ),
                "extraction_method": field.get(
                    "extraction_method",
                    current["extraction_method"],
                ),
                "evidence_coverage": evidence_coverage,
                "validation_warnings": validation_warnings,
                "status": status,
            }
        )

        canonical_fields[field_name] = current

    return {
        "schema_version": FIELD_SCHEMA_VERSION,
        "scheme_code": ACTIVE_SCHEME_CODE,
        "generated_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "fields": canonical_fields,
    }


def get_field_entry(
    structured_data: JsonObject,
    field_name: str,
) -> JsonObject:
    """Return one field from canonical or legacy structured data."""

    if structured_data.get("schema_version") == FIELD_SCHEMA_VERSION:
        fields_value = structured_data.get("fields")

        if isinstance(fields_value, dict):
            entry_value = fields_value.get(field_name)

            if isinstance(entry_value, dict):
                return {
                    str(key): item
                    for key, item in entry_value.items()
                }

    if field_name in structured_data:
        value = structured_data.get(field_name)

        entry: JsonObject = (
            empty_field(field_name)
            if field_name in CANONICAL_FIELD_SCHEMA
            else {
                "field_name": field_name,
                "normalized_value": None,
                "status": "not_implemented",
            }
        )

        has_value = _has_value(value)

        entry.update(
            {
                "normalized_value": value,
                "original_text": (
                    str(value)
                    if value is not None
                    else None
                ),
                "evidence_coverage": 1.0 if has_value else 0.0,
                "status": (
                    "resolved"
                    if has_value
                    else entry.get("status", "unresolved")
                ),
            }
        )

        return entry

    if field_name in CANONICAL_FIELD_SCHEMA:
        return empty_field(field_name)

    return {
        "field_name": field_name,
        "normalized_value": None,
        "status": "not_implemented",
    }


def rule_field_mapping(
    scheme_code: str = ACTIVE_SCHEME_CODE,
) -> list[JsonObject]:
    """Return the canonical-field dependency of each configured rule."""

    candidates = sorted(
        RULES_DIR.glob(f"{scheme_code.lower()}-eligibility-rules-v*.yaml"),
        key=lambda candidate: tuple(
            int(part) if part.isdigit() else 0
            for part in candidate.stem.rsplit("-v", maxsplit=1)[-1].split(".")
        ),
        reverse=True,
    )
    if not candidates:
        expected = RULES_DIR / f"{scheme_code.lower()}-eligibility-rules-v1.yaml"
        raise FileNotFoundError(
            f"Rule definition file does not exist: {expected}"
        )
    path = candidates[0]

    data = _load_yaml_mapping(path)
    rules = _normalise_mapping_list(
        data.get("rules"),
        context=f"{path}.rules",
    )

    mapping: list[JsonObject] = []

    for index, rule in enumerate(rules):
        raw_field = rule.get("field")
        raw_rule_id = rule.get("rule_id")

        if not isinstance(raw_field, str) or not raw_field.strip():
            raise ValueError(
                f"{path}.rules[{index}].field must be a non-empty string"
            )

        if not isinstance(raw_rule_id, str) or not raw_rule_id.strip():
            raise ValueError(
                f"{path}.rules[{index}].rule_id must be a non-empty string"
            )

        field_name = raw_field.strip()
        spec = CANONICAL_FIELD_SCHEMA.get(field_name)

        mapping.append(
            {
                "rule_id": raw_rule_id.strip(),
                "required_fields": [field_name],
                "extraction_method": (
                    spec["extraction_method"]
                    if spec is not None
                    else None
                ),
                "missing_value_policy": (
                    spec["missing_value_policy"]
                    if spec is not None
                    else "not_implemented"
                ),
            }
        )

    return mapping


def validate_active_rule_fields() -> None:
    """Ensure every active rule references a canonical field."""

    missing = [
        str(row["required_fields"][0])
        for row in rule_field_mapping(ACTIVE_SCHEME_CODE)
        if row["required_fields"][0]
        not in CANONICAL_FIELD_SCHEMA
    ]

    if missing:
        raise ValueError(
            "Active rules reference fields absent from canonical schema: "
            f"{sorted(set(missing))}"
        )
