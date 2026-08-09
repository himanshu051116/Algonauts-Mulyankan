"""Safe public projection of persisted evaluation payloads.

Stored payloads are immutable provenance records.  Public API responses are
projected from current database release-state fields so legacy or abstained
runs cannot expose an official-looking score after a safety migration.
"""

from __future__ import annotations

import copy
from typing import Any

LEGACY_REASON = (
    "This evaluation predates evidence-contract verification and is retained "
    "for audit only. Re-run the current proposal version before using advisory scores."
)


def _mapping(value: object) -> dict[str, Any]:
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def public_scoring_payload(
    stored_scoring: object,
    *,
    scoring_status: str,
    total_score: float | None,
    diagnostic_score: float | None,
    abstention_reason: str | None,
) -> dict[str, Any]:
    """Return a fail-closed API representation without mutating provenance."""

    scoring = _mapping(stored_scoring)
    released = scoring_status == "released"
    scoring["scoring_status"] = scoring_status
    scoring["total_score"] = total_score if released else None
    scoring["diagnostic_score"] = diagnostic_score

    if not released:
        scoring["abstention"] = True
        scoring["decision_recommendation"] = None
        reasons = [
            str(item)
            for item in scoring.get("abstention_reasons", [])
            if str(item).strip()
        ] if isinstance(scoring.get("abstention_reasons"), list) else []
        if abstention_reason and abstention_reason not in reasons:
            reasons.append(abstention_reason)
        if scoring_status == "legacy_unverified" and LEGACY_REASON not in reasons:
            reasons.append(LEGACY_REASON)
        if scoring_status == "failed" and not reasons:
            reasons.append("Evaluation failed before advisory scoring could be completed.")
        scoring["abstention_reasons"] = reasons

    if scoring_status == "legacy_unverified":
        for category in scoring.get("category_scores", []):
            if not isinstance(category, dict):
                continue
            category["awarded"] = None
            category["released"] = False
            for criterion in category.get("criteria", []):
                if not isinstance(criterion, dict):
                    continue
                criterion["awarded_score"] = None
                criterion["ordinal_grade"] = None
                criterion["confidence"] = None
                criterion["ml_prediction"] = None
                criterion["contextual_baseline_score"] = None
                criterion["released"] = False
                criterion["criterion_status"] = "legacy_unverified"
                warnings = criterion.get("warnings")
                warning_list = [str(item) for item in warnings] if isinstance(warnings, list) else []
                if LEGACY_REASON not in warning_list:
                    warning_list.append(LEGACY_REASON)
                criterion["warnings"] = warning_list

    return scoring


def public_gate_payload(
    stored_gate: object,
    *,
    persisted_gate: object,
    scoring_status: str,
) -> dict[str, Any]:
    """Return gate provenance, synthesising a safe state for legacy runs."""

    gate = _mapping(stored_gate)
    if not gate:
        gate = _mapping(persisted_gate)
    if scoring_status == "legacy_unverified" and not gate.get("status"):
        gate.update(
            {
                "status": "legacy_unverified",
                "accepted": False,
                "scoring_allowed": False,
                "document_type": "unknown",
                "declared_role": "main_proposal",
                "classified_role": "unknown",
                "role_status": "legacy_unverified",
                "structure_coverage": 0.0,
                "scheme_relevance": 0.0,
                "reasons": [LEGACY_REASON],
            }
        )
    elif scoring_status == "failed" and not gate.get("status"):
        gate.update(
            {
                "status": "evaluation_failed",
                "accepted": False,
                "scoring_allowed": False,
                "document_type": "unknown",
                "declared_role": "main_proposal",
                "classified_role": "unknown",
                "role_status": "uncertain",
                "structure_coverage": 0.0,
                "scheme_relevance": 0.0,
                "reasons": [
                    "Evaluation failed before document-gate results were persisted."
                ],
            }
        )
    return gate
