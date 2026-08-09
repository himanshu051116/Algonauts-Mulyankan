"""Dispatch proposal scoring to the registered and integrity-checked engine."""

from __future__ import annotations

from typing import Any

from app.ml.constants import MODEL_NAME, MODEL_REGISTRY_VERSION
from app.ml.inference import score_proposal_with_ml
from app.models.proposal import ModelVersion
from app.services.model_registry import CONTEXTUAL_BASELINE_NAME
from app.services.scoring import score_proposal


async def score_with_registered_model(
    model: ModelVersion,
    scheme_code: str,
    extracted_text: str,
    rubric_version: str,
    *,
    document_role: str = "main_proposal",
    evidence_contract_version: str = "1",
    documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the selected engine without silently promoting fallback output.

    The contextual baseline is retained for transparent diagnostics and evidence
    organisation.  It must never substitute an official-looking numeric result
    when the trained artifact is unavailable.
    """

    if model.model_name == MODEL_NAME:
        result = await score_proposal_with_ml(
            scheme_code,
            extracted_text,
            rubric_version,
            document_role=document_role,
            evidence_contract_version=evidence_contract_version,
            documents=documents,
        )
        result.setdefault("engine_version", f"{MODEL_NAME}@{MODEL_REGISTRY_VERSION}")
        return result

    if model.model_name == CONTEXTUAL_BASELINE_NAME:
        result = await score_proposal(
            scheme_code,
            extracted_text,
            rubric_version,
            document_role=document_role,
            evidence_contract_version=evidence_contract_version,
            documents=documents,
        )
        result.update(
            {
                "total_score": None,
                "scoring_status": "rules_only",
                "abstention": True,
                "decision_recommendation": None,
                "model_source": CONTEXTUAL_BASELINE_NAME,
                "engine_version": f"{CONTEXTUAL_BASELINE_NAME}@{model.version}",
                "model_invoked": False,
                "fallback_notice": (
                    "The trained model was unavailable. Deterministic rules and "
                    "evidence diagnostics were produced, but no automated score was released."
                ),
                "abstention_reasons": list(result.get("abstention_reasons", []))
                + ["trained model unavailable; rules-only fail-closed mode"],
            }
        )
        return result

    raise RuntimeError(f"No scoring adapter is registered for model {model.model_name}")
