"""Versioned, fail-closed rule engine for eligibility and compliance rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypeAlias

import yaml

from app.services.field_schema import get_field_entry


JsonObject: TypeAlias = dict[str, Any]
RuleResult: TypeAlias = dict[str, Any]

RULES_DIR = Path(__file__).resolve().parents[3] / "data" / "rules"
SCHEMES_DIR = Path(__file__).resolve().parents[3] / "data" / "schemes"

PASS_STATUSES: set[str] = {
    "pass",
    "not_applicable",
}

BLOCKING_STATUSES: set[str] = {
    "fail",
    "unresolved",
    "clarification_required",
    "exception_review",
    "not_implemented",
}

VALID_RULE_STATUSES: set[str] = PASS_STATUSES | BLOCKING_STATUSES


def _as_mapping(value: object, *, context: str) -> JsonObject:
    """Validate and normalise an externally loaded mapping."""

    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping")

    return {
        str(key): item
        for key, item in value.items()
    }


def _as_mapping_list(
    value: object,
    *,
    context: str,
) -> list[JsonObject]:
    """Validate a list containing mappings."""

    if value is None:
        return []

    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")

    mappings: list[JsonObject] = []

    for index, item in enumerate(value):
        mappings.append(
            _as_mapping(
                item,
                context=f"{context}[{index}]",
            )
        )

    return mappings


def _require_string(
    mapping: JsonObject,
    key: str,
    *,
    context: str,
) -> str:
    """Read a required non-empty string from a mapping."""

    value = mapping.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{context}.{key} must be a non-empty string"
        )

    return value.strip()


def _optional_string(
    mapping: JsonObject,
    key: str,
    *,
    default: str = "",
) -> str:
    """Read an optional string with a deterministic default."""

    value = mapping.get(key)

    if isinstance(value, str):
        return value.strip()

    return default


def _string_list(value: object) -> list[str]:
    """Convert an external list value into a list of strings."""

    if value is None:
        return []

    if not isinstance(value, list):
        return [str(value)]

    return [
        str(item)
        for item in value
        if item is not None
    ]


def _load_yaml_mapping(path: Path) -> JsonObject:
    """Load a YAML file whose root must be a mapping."""

    with path.open("r", encoding="utf-8") as file:
        raw_data: object = yaml.safe_load(file)

    if raw_data is None:
        raise ValueError(f"YAML file is empty: {path}")

    return _as_mapping(
        raw_data,
        context=f"YAML file {path}",
    )


def _version_file_candidates(
    version: str | None,
) -> list[str]:
    """Return compatible filename representations for a version."""

    effective_version = version or "1"
    candidates = [effective_version]

    if effective_version.endswith(".0"):
        shortened = effective_version[:-2]

        if shortened and shortened not in candidates:
            candidates.append(shortened)

    return candidates


def _load_scheme_thrust_areas(
    scheme_code: str,
) -> list[str]:
    """Load and normalise approved thrust-area identifiers."""

    path = (
        SCHEMES_DIR
        / f"{scheme_code.lower()}-scheme.yaml"
    )

    if not path.exists():
        return []

    scheme = _load_yaml_mapping(path)

    thrust_area_entries = _as_mapping_list(
        scheme.get("thrust_areas"),
        context=f"{path}.thrust_areas",
    )

    thrust_areas: list[str] = []

    for index, entry in enumerate(thrust_area_entries):
        thrust_area_id = _require_string(
            entry,
            "id",
            context=f"{path}.thrust_areas[{index}]",
        ).lower()

        thrust_areas.append(thrust_area_id)

    return thrust_areas


def _load_rule_file(
    scheme_code: str,
    version: str | None = None,
) -> list[JsonObject]:
    """Load and validate one version of a scheme rule file."""

    for candidate in _version_file_candidates(version):
        filename = (
            f"{scheme_code.lower()}"
            f"-eligibility-rules-v{candidate}.yaml"
        )

        path = RULES_DIR / filename

        if not path.exists():
            continue

        rule_document = _load_yaml_mapping(path)

        return _as_mapping_list(
            rule_document.get("rules"),
            context=f"{path}.rules",
        )

    return []


def _parse_range(value: str) -> tuple[float, float]:
    """Parse an inclusive numeric range such as '12-36'."""

    parts = value.split("-", maxsplit=1)

    if len(parts) != 2:
        raise ValueError(
            f"Range must contain lower and upper values: {value!r}"
        )

    lower = float(parts[0].strip())
    upper = float(parts[1].strip())

    if lower > upper:
        raise ValueError(
            f"Range lower bound exceeds upper bound: {value!r}"
        )

    return lower, upper


def _normalize(value: object) -> str:
    """Normalise a value for case-insensitive comparisons."""

    if value is None:
        return ""

    return str(value).strip().lower()


def _effective_value(field_entry: JsonObject) -> Any:
    """Prefer a manually corrected value over extracted data."""

    manual_value = field_entry.get(
        "manually_corrected_value"
    )

    if manual_value not in (None, ""):
        return manual_value

    return field_entry.get("normalized_value")


def _preflight_field_status(
    field_entry: JsonObject,
) -> tuple[str, float, str] | None:
    """Stop rule execution when extraction already identified a blocker."""

    status = field_entry.get("status")

    warning_items = _string_list(
        field_entry.get("validation_warnings")
    )
    warnings = "; ".join(warning_items)

    raw_coverage = field_entry.get("evidence_coverage")

    try:
        evidence_coverage = float(raw_coverage or 0.0)
    except (TypeError, ValueError):
        evidence_coverage = 0.0

    if status == "clarification_required":
        return (
            "clarification_required",
            evidence_coverage,
            warnings or "Field requires clarification",
        )

    if status == "not_implemented":
        return (
            "not_implemented",
            0.0,
            (
                warnings
                or (
                    "Required extraction or reference data "
                    "is not implemented"
                )
            ),
        )

    if status == "unresolved":
        return (
            "unresolved",
            evidence_coverage,
            warnings or "Field could not be resolved",
        )

    return None


def progression_policy(
    results: list[RuleResult],
) -> JsonObject:
    """Determine whether rule results permit automatic progression."""

    blocking = [
        result
        for result in results
        if result.get("result") in BLOCKING_STATUSES
    ]

    unknown = [
        result
        for result in results
        if result.get("result") not in VALID_RULE_STATUSES
    ]

    blocked_results = blocking + unknown
    automatic_progression = not blocked_results

    blocking_statuses = sorted(
        {
            str(result.get("result", "unknown"))
            for result in blocked_results
        }
    )

    blocking_rule_ids = [
        str(result.get("rule_id", "unknown"))
        for result in blocked_results
    ]

    return {
        "automatic_progression": automatic_progression,
        "eligible": automatic_progression,
        "blocking_statuses": blocking_statuses,
        "blocking_rule_ids": blocking_rule_ids,
        "requires_human_review": bool(blocked_results),
    }


def _evaluate_operator(
    operator: str,
    field_value: Any,
    limit_value: Any,
    extracted_fields: JsonObject,
    scheme_thrust_areas: list[str] | None = None,
) -> tuple[str, float, str]:
    """Evaluate one configured rule operator."""

    # Reserved for operators that need access to multiple fields.
    _ = extracted_fields

    normalized_value = _normalize(field_value)

    match operator:
        case "in_list" if limit_value is not None:
            if isinstance(limit_value, list):
                expected = [
                    str(item).strip()
                    for item in limit_value
                ]
            else:
                expected = [
                    item.strip()
                    for item in str(limit_value).split(",")
                ]

            expected_lower = [
                item.lower()
                for item in expected
            ]

            if not normalized_value:
                return (
                    "unresolved",
                    0.0,
                    "Field value is empty or missing",
                )

            if normalized_value in expected_lower:
                return ("pass", 1.0, "")

            return (
                "fail",
                1.0,
                (
                    f"Value {field_value!r} is not in the "
                    f"allowed list: {expected}"
                ),
            )

        case "range" if limit_value is not None:
            try:
                lower, upper = _parse_range(
                    str(limit_value)
                )
            except (TypeError, ValueError) as exc:
                return (
                    "not_implemented",
                    0.0,
                    f"Invalid configured range: {exc}",
                )

            try:
                numeric_value = float(field_value)
            except (TypeError, ValueError):
                return (
                    "unresolved",
                    0.0,
                    (
                        "Cannot parse numeric value from "
                        f"{field_value!r}"
                    ),
                )

            if lower <= numeric_value <= upper:
                return ("pass", 1.0, "")

            return (
                "fail",
                1.0,
                (
                    f"Value {numeric_value} is outside the "
                    f"allowed range [{lower}-{upper}]"
                ),
            )

        case "max_percentage" if limit_value is not None:
            try:
                percentage = (
                    float(field_value)
                    if field_value is not None
                    else None
                )
            except (TypeError, ValueError):
                return (
                    "unresolved",
                    0.0,
                    (
                        "Cannot parse percentage from "
                        f"{field_value!r}"
                    ),
                )

            if percentage is None:
                return (
                    "unresolved",
                    0.0,
                    "Field value is missing",
                )

            try:
                maximum_percentage = float(limit_value)
            except (TypeError, ValueError):
                return (
                    "not_implemented",
                    0.0,
                    (
                        "Configured maximum percentage is "
                        f"invalid: {limit_value!r}"
                    ),
                )

            if percentage <= maximum_percentage:
                return ("pass", 1.0, "")

            return (
                "exception_review",
                1.0,
                (
                    f"Value {percentage}% exceeds maximum "
                    f"{maximum_percentage}%"
                ),
            )

        case "max_value" if limit_value is not None:
            if field_value is None:
                return (
                    "unresolved",
                    0.0,
                    "Field value is missing",
                )

            try:
                field_numeric_value = float(field_value)
            except (TypeError, ValueError):
                return (
                    "unresolved",
                    0.0,
                    (
                        "Cannot parse numeric value from "
                        f"{field_value!r}"
                    ),
                )

            try:
                configured_maximum_value = float(limit_value)
            except (TypeError, ValueError):
                return (
                    "not_implemented",
                    0.0,
                    (
                        "Configured maximum value is invalid: "
                        f"{limit_value!r}"
                    ),
                )

            if field_numeric_value <= configured_maximum_value:
                return ("pass", 1.0, "")

            return (
                "fail",
                1.0,
                (
                    f"Value {field_numeric_value} exceeds maximum "
                    f"{configured_maximum_value}"
                ),
            )

        case "prohibited":
            absence_values = {
                "",
                "false",
                "no",
                "none",
                "nil",
                "n/a",
                "not applicable",
                "absent",
                "0",
            }

            if normalized_value in absence_values:
                return ("pass", 1.0, "")

            return (
                "fail",
                1.0,
                f"Prohibited item present: {field_value}",
            )

        case "required_field":
            if normalized_value:
                return ("pass", 1.0, "")

            return (
                "unresolved",
                0.0,
                "Required field is missing or empty",
            )

        case "conditional_requirement":
            absence_values = {
                "none",
                "nil",
                "n/a",
                "not applicable",
                "not_required",
                "false",
                "no",
            }

            if normalized_value in absence_values:
                return ("not_applicable", 1.0, "Requirement is not applicable")
            if normalized_value:
                return ("pass", 1.0, "")
            return (
                "clarification_required",
                0.0,
                "Conditional requirement may apply and requires human review",
            )

        case "conditional_approval":
            absence_values = {
                "",
                "none",
                "nil",
                "n/a",
                "not applicable",
                "false",
                "no",
                "0",
            }
            if normalized_value in absence_values:
                return ("pass", 1.0, "No conditional approval is required")
            return (
                "exception_review",
                1.0,
                "The requested item requires documented prior approval and limit verification",
            )

        case "conditional_justification":
            if normalized_value in {"not_required", "not applicable", "n/a"}:
                return ("not_applicable", 1.0, "No duration exception is required")
            if normalized_value in {"justification_present", "yes", "provided"}:
                return (
                    "exception_review",
                    1.0,
                    "Duration exception justification is present and requires human approval",
                )
            if normalized_value:
                return (
                    "exception_review",
                    0.75,
                    "A possible duration justification was detected and requires human approval",
                )
            return (
                "clarification_required",
                0.0,
                "Duration exceeds the normal limit and justification is missing",
            )

        case "duplicate_check":
            if normalized_value in {
                "none",
                "no",
                "not applicable",
                "not_submitted_elsewhere",
                "no_prior_funding",
            }:
                return ("pass", 1.0, "No duplication was declared in the proposal")
            if normalized_value in {"possible_duplicate", "yes", "duplicate"}:
                return (
                    "clarification_required",
                    0.6,
                    "Potential duplication was identified and must be checked against the proposal repository",
                )
            return (
                "clarification_required",
                0.0,
                "A non-duplication declaration or repository comparison is required",
            )

        case "thrust_area_match":
            approved_areas = scheme_thrust_areas or []

            if (
                approved_areas
                and normalized_value in approved_areas
            ):
                return ("pass", 1.0, "")

            if normalized_value and len(normalized_value) > 3:
                return (
                    "clarification_required",
                    0.5,
                    (
                        f"Thrust area {field_value!r} was not "
                        "found in the scheme's approved list: "
                        f"{approved_areas}"
                    ),
                )

            return (
                "unresolved",
                0.0,
                (
                    "Unable to determine thrust-area alignment "
                    "from extracted text"
                ),
            )

        case "minimum_qualification" if limit_value is not None:
            required_qualification = _normalize(limit_value)

            if (
                required_qualification
                and required_qualification in normalized_value
            ):
                return ("pass", 1.0, "")

            return (
                "clarification_required",
                0.5,
                (
                    "Cannot confirm minimum qualification "
                    f"({limit_value}) from the extracted text"
                ),
            )

        case "entity_type" if limit_value is not None:
            required_entity_type = _normalize(limit_value)

            if (
                required_entity_type
                and required_entity_type in normalized_value
            ):
                return ("pass", 1.0, "")

            if not normalized_value:
                return (
                    "unresolved",
                    0.0,
                    "Entity type is missing",
                )

            return (
                "fail",
                1.0,
                (
                    f"Entity type {field_value!r} does not match "
                    f"required type {limit_value!r}"
                ),
            )

        case _:
            return (
                "not_implemented",
                0.0,
                (
                    f"Unknown operator {operator!r} or required "
                    "configuration is missing"
                ),
            )


async def evaluate_rules(
    scheme_code: str,
    extracted_fields: JsonObject,
    rule_version: str | None = None,
) -> JsonObject:
    """Evaluate all configured rules for one proposal."""

    rules = _load_rule_file(
        scheme_code,
        rule_version,
    )

    effective_rule_version = rule_version or "1"

    if not rules:
        return {
            "scheme_code": scheme_code,
            "rule_version": effective_rule_version,
            "summary": {
                "eligible": False,
                "automatic_progression": False,
                "has_errors": True,
                "has_exceptions": False,
                "requires_human_review": True,
                "blocking_statuses": ["not_implemented"],
                "blocking_rule_ids": [],
            },
            "results": [],
            "error": (
                "No rule definitions were found for scheme "
                f"{scheme_code}"
            ),
        }

    thrust_areas = _load_scheme_thrust_areas(
        scheme_code
    )

    results: list[RuleResult] = []
    has_errors = False
    has_exceptions = False

    for rule_index, rule in enumerate(rules):
        rule_context = f"rules[{rule_index}]"

        rule_id = _require_string(
            rule,
            "rule_id",
            context=rule_context,
        )
        category = _require_string(
            rule,
            "category",
            context=rule_context,
        )
        field_name = _require_string(
            rule,
            "field",
            context=rule_context,
        )
        operator = _require_string(
            rule,
            "operator",
            context=rule_context,
        )

        field_entry_raw: object = get_field_entry(
            extracted_fields,
            field_name,
        )

        field_entry = _as_mapping(
            field_entry_raw,
            context=f"field_entry[{field_name}]",
        )

        field_value = _effective_value(
            field_entry
        )
        limit_value = rule.get("limit_value")

        preflight = _preflight_field_status(
            field_entry
        )

        if preflight is not None:
            result, evidence_coverage, detail = preflight
        else:
            result, evidence_coverage, detail = (
                _evaluate_operator(
                    operator,
                    field_value,
                    limit_value,
                    extracted_fields,
                    thrust_areas,
                )
            )

        severity = _optional_string(
            rule,
            "severity",
            default="error",
        )
        uncertainty_action = _optional_string(
            rule,
            "uncertainty_action",
            default="review",
        )

        source_reference_value = rule.get(
            "source_reference"
        )
        source_reference = (
            str(source_reference_value)
            if source_reference_value is not None
            else None
        )

        rule_result: RuleResult = {
            "rule_id": rule_id,
            "category": category,
            "field": field_name,
            "result": result,
            "evidence_coverage": evidence_coverage,
            "detail": detail,
            "severity": severity,
            "uncertainty_action": uncertainty_action,
            "source_reference": source_reference,
            "field_status": field_entry.get("status"),
        }

        results.append(rule_result)

        if (
            result in BLOCKING_STATUSES
            and severity == "error"
        ):
            has_errors = True

        if result in {
            "exception_review",
            "not_implemented",
            "clarification_required",
        }:
            has_exceptions = True

    summary: JsonObject = {
        **progression_policy(results),
        "has_errors": has_errors,
        "has_exceptions": has_exceptions,
    }

    return {
        "scheme_code": scheme_code,
        "rule_version": effective_rule_version,
        "summary": summary,
        "results": results,
    }
