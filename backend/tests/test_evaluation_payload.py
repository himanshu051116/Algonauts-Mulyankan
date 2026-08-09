"""Public evaluation payload safety regression tests."""

from app.services.evaluation_payload import (
    LEGACY_REASON,
    public_gate_payload,
    public_scoring_payload,
)


def _stored_scoring() -> dict:
    return {
        "total_score": 72.5,
        "decision_recommendation": "expert_review_required",
        "abstention": False,
        "category_scores": [
            {
                "category": "Novelty",
                "awarded": 7.0,
                "released": True,
                "criteria": [
                    {
                        "criterion_id": "novelty",
                        "awarded_score": 7.0,
                        "ordinal_grade": 3,
                        "confidence": 0.8,
                        "ml_prediction": 7.2,
                        "contextual_baseline_score": 6.8,
                        "released": True,
                        "criterion_status": "supported",
                        "warnings": [],
                    }
                ],
            }
        ],
    }


def test_legacy_payload_is_fail_closed_without_mutating_provenance():
    stored = _stored_scoring()
    public = public_scoring_payload(
        stored,
        scoring_status="legacy_unverified",
        total_score=None,
        diagnostic_score=72.5,
        abstention_reason=None,
    )

    assert stored["total_score"] == 72.5
    assert stored["category_scores"][0]["criteria"][0]["awarded_score"] == 7.0
    assert public["total_score"] is None
    assert public["diagnostic_score"] == 72.5
    assert public["scoring_status"] == "legacy_unverified"
    assert public["abstention"] is True
    assert public["decision_recommendation"] is None
    assert LEGACY_REASON in public["abstention_reasons"]
    category = public["category_scores"][0]
    criterion = category["criteria"][0]
    assert category["awarded"] is None
    assert category["released"] is False
    assert criterion["awarded_score"] is None
    assert criterion["ordinal_grade"] is None
    assert criterion["released"] is False
    assert criterion["criterion_status"] == "legacy_unverified"


def test_released_payload_uses_authoritative_database_score():
    public = public_scoring_payload(
        _stored_scoring(),
        scoring_status="released",
        total_score=68.0,
        diagnostic_score=68.0,
        abstention_reason=None,
    )
    assert public["total_score"] == 68.0
    assert public["scoring_status"] == "released"
    assert public["category_scores"][0]["criteria"][0]["awarded_score"] == 7.0


def test_legacy_gate_defaults_to_not_accepted():
    gate = public_gate_payload(
        {},
        persisted_gate={},
        scoring_status="legacy_unverified",
    )
    assert gate["status"] == "legacy_unverified"
    assert gate["accepted"] is False
    assert gate["scoring_allowed"] is False
    assert LEGACY_REASON in gate["reasons"]


def test_failed_run_does_not_masquerade_as_legacy_evaluation() -> None:
    scoring = public_scoring_payload(
        {},
        scoring_status="failed",
        total_score=None,
        diagnostic_score=None,
        abstention_reason=None,
    )
    gate = public_gate_payload({}, persisted_gate={}, scoring_status="failed")

    assert scoring["scoring_status"] == "failed"
    assert scoring["abstention_reasons"] == [
        "Evaluation failed before advisory scoring could be completed."
    ]
    assert gate["status"] == "evaluation_failed"
    assert gate["role_status"] == "uncertain"
    assert gate["reasons"] == [
        "Evaluation failed before document-gate results were persisted."
    ]
