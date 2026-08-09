"""Validate that every YAML configuration file resolves correctly."""

from pathlib import Path

import pytest
import yaml

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
SCHEMES_DIR = DATA_DIR / "schemes"
RULES_DIR = DATA_DIR / "rules"


def _load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def test_all_scheme_files_exist():
    paths = list(SCHEMES_DIR.glob("*-scheme.yaml"))
    assert len(paths) >= 3, f"Expected at least 3 scheme files, found {len(paths)}"
    codes = set()
    for p in paths:
        data = _load_yaml(p)
        code = data.get("scheme_code", "")
        assert code, f"{p.name} has no scheme_code"
        expected_prefix = p.name.split("-scheme.yaml")[0]
        assert code.lower() == expected_prefix, \
            f"{p.name}: scheme_code '{code}' does not match filename prefix '{expected_prefix}'"
        assert code not in codes, f"Duplicate scheme_code '{code}' in {p.name}"
        codes.add(code)
        ta = data.get("thrust_areas", [])
        assert len(ta) > 0, f"{p.name} has no thrust areas"
        ta_ids = {t["id"] for t in ta if "id" in t}
        assert len(ta_ids) == len(ta), f"{p.name} has duplicate thrust area IDs"


def test_all_rule_files_exist():
    paths = list(RULES_DIR.glob("*-eligibility-rules-*.yaml"))
    assert len(paths) >= 3, f"Expected at least 3 rule files, found {len(paths)}"
    versions = {}
    for p in paths:
        data = _load_yaml(p)
        code = data.get("scheme_code", "")
        rv = data.get("rule_version", "")
        assert code, f"{p.name} has no scheme_code"
        assert rv, f"{p.name} has no rule_version"
        key = (code, rv)
        assert key not in versions, \
            f"Duplicate rule version {rv} for scheme {code} in {p.name} and {versions[key]}"
        versions[key] = p.name
        rules = data.get("rules", [])
        assert len(rules) > 0, f"{p.name} has no rules"
        rule_ids = {r["rule_id"] for r in rules if "rule_id" in r}
        assert len(rule_ids) == len(rules), f"{p.name} has duplicate rule_ids"
        for r in rules:
            assert "field" in r, f"Rule {r.get('rule_id', '?')} in {p.name} has no 'field'"
            assert "operator" in r, f"Rule {r.get('rule_id', '?')} in {p.name} has no 'operator'"
            assert "category" in r, f"Rule {r.get('rule_id', '?')} in {p.name} has no 'category'"


def test_rubric_files_validate():
    paths = list(RULES_DIR.glob("*-100-mark-rubric-*.yaml"))
    assert len(paths) >= 1, "Expected at least 1 rubric file"
    for p in paths:
        data = _load_yaml(p)
        assert data.get("total_marks") == 100, f"{p.name}: total_marks != 100"
        cats = data.get("categories", [])
        assert len(cats) > 0, f"{p.name} has no categories"
        seen_ids = []
        for cat in cats:
            criteria = cat.get("criteria", [])
            assert len(criteria) > 0, f"{p.name} category '{cat.get('name')}' has no criteria"
            cat_criteria_sum = sum(cr.get("maximum", 0) for cr in criteria)
            assert cat.get("maximum", 0) == cat_criteria_sum, \
                f"{p.name} category '{cat.get('name')}': max {cat['maximum']} != sum of criteria {cat_criteria_sum}"
            for cr in criteria:
                cid = cr.get("id", "")
                assert cid, f"{p.name}: criterion without id"
                assert cid not in seen_ids, f"{p.name}: duplicate criterion id '{cid}'"
                seen_ids.append(cid)
        assert data.get("scheme_code", ""), f"{p.name} has no scheme_code"
        assert data.get("rubric_version", ""), f"{p.name} has no rubric_version"


@pytest.mark.asyncio
async def test_rules_load_via_service():
    from app.services.rules import evaluate_rules

    paths = list(RULES_DIR.glob("*-eligibility-rules-*.yaml"))
    assert len(paths) >= 3
    for p in paths:
        data = _load_yaml(p)
        code = data["scheme_code"]
        result = await evaluate_rules(code, {})
        assert "error" not in result, f"Scheme {code}: {result.get('error')}"
        assert len(result["results"]) > 0, f"Scheme {code}: no rules evaluated"
        for r in result["results"]:
            assert r["result"] in (
                "pass", "fail", "exception_review", "clarification_required",
                "unresolved", "not_implemented", "not_applicable",
            ), f"Unexpected result '{r['result']}' for rule {r['rule_id']} in scheme {code}"
            assert 0 <= r["evidence_coverage"] <= 1, \
                f"Evidence coverage out of range for rule {r['rule_id']} in scheme {code}"
