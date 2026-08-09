import pytest
from fastapi import HTTPException

from app.services.field_schema import CANONICAL_FIELD_SCHEMA, rule_field_mapping, validate_active_rule_fields
from app.services.schemes import ACTIVE_SCHEME_CODES, ensure_active_scheme_code


def test_only_moc_st_is_active():
    assert ACTIVE_SCHEME_CODES == ("MOC-ST",)


@pytest.mark.parametrize("scheme_code", ["CIL-RD", "ST-FIRST"])
def test_inactive_schemes_raise_structured_422(scheme_code):
    with pytest.raises(HTTPException) as exc:
        ensure_active_scheme_code(scheme_code)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "unsupported_scheme"
    assert exc.value.detail["supported_schemes"] == ["MOC-ST"]


def test_active_rule_fields_are_present_in_canonical_schema():
    validate_active_rule_fields()
    mapping = rule_field_mapping("MOC-ST")
    assert mapping
    for row in mapping:
        field = row["required_fields"][0]
        assert field in CANONICAL_FIELD_SCHEMA
        assert row["extraction_method"]
        assert row["missing_value_policy"] in {
            "unresolved",
            "clarification_required",
            "not_applicable",
            "not_implemented",
        }
