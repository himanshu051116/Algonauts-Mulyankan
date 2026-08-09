"""Unit tests for the rule engine service."""

import pytest

from app.services.rules import evaluate_rules


@pytest.mark.asyncio
async def test_rules_in_list_pass():
    result = await evaluate_rules(
        "MOC-ST",
        {"institution_eligibility": "academic"},
    )
    results = result["results"]
    in_list_rules = [r for r in results if r["rule_id"] == "MOC-ST-ELIG-001"]
    assert len(in_list_rules) == 1
    assert in_list_rules[0]["result"] == "pass"


@pytest.mark.asyncio
async def test_rules_in_list_fail():
    result = await evaluate_rules(
        "MOC-ST",
        {"institution_eligibility": "unknown_org"},
    )
    results = result["results"]
    in_list_rules = [r for r in results if r["rule_id"] == "MOC-ST-ELIG-001"]
    assert len(in_list_rules) == 1
    assert in_list_rules[0]["result"] == "fail"


@pytest.mark.asyncio
async def test_rules_range_pass():
    result = await evaluate_rules(
        "MOC-ST",
        {"project_duration": "24"},
    )
    results = result["results"]
    range_rules = [r for r in results if r["rule_id"] == "MOC-ST-ELIG-003"]
    assert len(range_rules) == 1
    assert range_rules[0]["result"] == "pass"


@pytest.mark.asyncio
async def test_rules_range_fail_below():
    result = await evaluate_rules(
        "MOC-ST",
        {"project_duration": "6"},
    )
    results = result["results"]
    range_rules = [r for r in results if r["rule_id"] == "MOC-ST-ELIG-003"]
    assert len(range_rules) == 1
    assert range_rules[0]["result"] == "fail"


@pytest.mark.asyncio
async def test_rules_max_percentage_pass():
    result = await evaluate_rules(
        "MOC-ST",
        {"contingency_percentage": "4"},
    )
    results = result["results"]
    fin_rules = [r for r in results if r["rule_id"] == "MOC-ST-FIN-001"]
    assert len(fin_rules) == 1
    assert fin_rules[0]["result"] == "pass"


@pytest.mark.asyncio
async def test_rules_max_percentage_exception():
    result = await evaluate_rules(
        "MOC-ST",
        {"contingency_percentage": "8"},
    )
    results = result["results"]
    fin_rules = [r for r in results if r["rule_id"] == "MOC-ST-FIN-001"]
    assert len(fin_rules) == 1
    assert fin_rules[0]["result"] == "exception_review"


@pytest.mark.asyncio
async def test_rules_prohibited_fail():
    result = await evaluate_rules(
        "MOC-ST",
        {"staff_vehicles": "Purchase of one SUV for field staff"},
    )
    results = result["results"]
    prohib_rules = [r for r in results if r["rule_id"] == "MOC-ST-FIN-004"]
    assert len(prohib_rules) == 1
    assert prohib_rules[0]["result"] == "fail"


@pytest.mark.asyncio
async def test_rules_prohibited_pass():
    result = await evaluate_rules(
        "MOC-ST",
        {"staff_vehicles": ""},
    )
    results = result["results"]
    prohib_rules = [r for r in results if r["rule_id"] == "MOC-ST-FIN-004"]
    assert len(prohib_rules) == 1
    assert prohib_rules[0]["result"] == "pass"


@pytest.mark.asyncio
async def test_rules_thrust_area_match_known():
    result = await evaluate_rules(
        "MOC-ST",
        {"thrust_area_alignment": "safety-health-environment"},
    )
    results = result["results"]
    thrust_rules = [r for r in results if r["rule_id"] == "MOC-ST-ELIG-005"]
    assert len(thrust_rules) == 1
    # safety-health-environment IS in the MOC-ST thrust areas
    assert thrust_rules[0]["result"] == "pass"


@pytest.mark.asyncio
async def test_rules_thrust_area_match_unknown():
    result = await evaluate_rules(
        "MOC-ST",
        {"thrust_area_alignment": "nuclear-fusion"},
    )
    results = result["results"]
    thrust_rules = [r for r in results if r["rule_id"] == "MOC-ST-ELIG-005"]
    assert len(thrust_rules) == 1
    # Not in MOC-ST thrust areas, but is non-empty string > 3 chars
    assert thrust_rules[0]["result"] == "clarification_required"


@pytest.mark.asyncio
async def test_rules_multiple_fields():
    """Test that all rules are evaluated and summary is correct."""
    result = await evaluate_rules(
        "MOC-ST",
        {
            "institution_eligibility": "academic",
            "pi_qualification": "phd",
            "project_duration": "24",
            "thrust_area_alignment": "safety-health-environment",
            "contingency_percentage": "3",
            "overhead_percentage": "8",
            "staff_vehicles": "None",
            "permanent_salary": "Not applicable",
            "dgms_approval": "DGMS approval will be obtained before mine trials",
        },
    )
    # Missing explicit declarations require clarification rather than a fake
    # not-implemented rejection.
    assert result["summary"]["eligible"] is False
    assert result["summary"]["has_errors"] is False
    assert result["summary"]["has_exceptions"] is True
    assert result["summary"]["requires_human_review"] is True
    assert "clarification_required" in result["summary"]["blocking_statuses"]
    assert "not_implemented" not in result["summary"]["blocking_statuses"]
    assert len(result["results"]) > 0


@pytest.mark.asyncio
async def test_rules_scheme_not_found():
    """Unrecognised scheme code should return an error."""
    result = await evaluate_rules("UNKNOWN", {})
    assert "error" in result
    assert result["summary"]["eligible"] is False


@pytest.mark.asyncio
async def test_rules_missing_fields_fail_closed():
    result = await evaluate_rules("MOC-ST", {})
    assert result["summary"]["automatic_progression"] is False
    assert "unresolved" in result["summary"]["blocking_statuses"]
    assert result["summary"]["eligible"] is False


@pytest.mark.asyncio
async def test_rules_null_field_is_unresolved():
    result = await evaluate_rules("MOC-ST", {"project_duration": None})
    duration_rule = next(r for r in result["results"] if r["rule_id"] == "MOC-ST-ELIG-003")
    assert duration_rule["result"] == "unresolved"


@pytest.mark.asyncio
async def test_rules_contradictory_duration_requires_clarification():
    result = await evaluate_rules(
        "MOC-ST",
        {
            "schema_version": "moc-st-fields-v1",
            "fields": {
                "project_duration": {
                    "normalized_value": None,
                    "status": "clarification_required",
                    "evidence_coverage": 1.0,
                    "validation_warnings": ["Contradictory project durations found"],
                }
            },
        },
    )
    duration_rule = next(r for r in result["results"] if r["rule_id"] == "MOC-ST-ELIG-003")
    assert duration_rule["result"] == "clarification_required"
    assert result["summary"]["automatic_progression"] is False


@pytest.mark.asyncio
async def test_rules_duplicate_declaration_is_evaluated():
    result = await evaluate_rules("MOC-ST", {"equipment_duplication": "none"})
    duplicate_rule = next(r for r in result["results"] if r["rule_id"] == "MOC-ST-FIN-006")
    assert duplicate_rule["result"] == "pass"
