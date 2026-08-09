"""
Arq worker for async proposal evaluation.

Runs rule evaluation and rubric scoring as background tasks so the API can
respond immediately and the caller can poll for results.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import re
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select

from app.config import settings
from app.database import async_session_factory
from app.models.proposal import (
    CriterionEvidence,
    CriterionPrediction,
    FundingScheme,
    GuidelineVersion,
    ModelRun,
    ModelVersion,
    Proposal,
    ProposalDocument,
    ProposalVersion,
    RubricCriterion,
    RubricVersion,
    RuleDefinition,
    RuleResult,
    SimilarityMatch,
)
from app.services.audit import create_audit_event
from app.services.document import detect_sections, extract_structured_fields
from app.services.document_gate import assess_document, gate_only_scoring_result
from app.services.model_registry import select_active_model_version
from app.services.evaluation_engine import score_with_registered_model as score_proposal
from app.services.rules import evaluate_rules
from app.services.schemes import ACTIVE_SCHEME_CODES, ensure_active_scheme_code
from app.services.similarity import check_prior_projects


logger = logging.getLogger(__name__)


def _json_checksum(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _normalize_rule_result(value: str) -> str:
    return value.replace("-", "_")


def _criterion_lookup_keys(criterion: RubricCriterion) -> list[str]:
    keys = []
    if criterion.criterion_key:
        keys.append(criterion.criterion_key.lower())
    keys.append(criterion.criterion.lower())
    keys.append(_slugify(criterion.criterion))
    return [key for key in keys if key]


async def _mark_failure(
    proposal_id: str,
    model_run_id: str | None,
    failure_code: str,
    failure_details: dict[str, Any],
    proposal_status: str = "error",
) -> None:
    async with async_session_factory() as session:
        proposal_result = await session.execute(select(Proposal).where(Proposal.id == proposal_id))
        proposal = proposal_result.scalar_one_or_none()
        if proposal:
            old_status = proposal.status
            proposal.status = proposal_status
        else:
            old_status = None

        if model_run_id:
            run_result = await session.execute(select(ModelRun).where(ModelRun.id == model_run_id))
            model_run = run_result.scalar_one_or_none()
            if model_run:
                model_run.status = "failed"
                model_run.scoring_status = "failed"
                model_run.completed_at = datetime.now(timezone.utc)
                model_run.failure_code = failure_code
                model_run.failure_details = failure_details
                model_run.error_message = "Evaluation failed"
                model_run.evaluation_payload = {
                    "status": "failed",
                    "failure_code": failure_code,
                    "failure_details": failure_details,
                }

        await create_audit_event(
            session,
            event_type="evaluation.failed",
            resource_type="proposal",
            resource_id=proposal_id,
            details={
                "failure_code": failure_code,
                "failure_details": failure_details,
                "model_run_id": model_run_id,
            },
        )
        if old_status is not None:
            await create_audit_event(
                session,
                event_type="proposal.status_transition",
                resource_type="proposal",
                resource_id=proposal_id,
                details={"from": old_status, "to": proposal_status, "reason": failure_code},
            )
        await session.commit()


async def _create_or_reuse_run(
    session,
    proposal_id: str,
    scheme_code: str,
    trigger_user_id: str | None,
    rerun_reason: str | None,
) -> tuple[
    Proposal,
    ProposalVersion,
    ModelVersion,
    ModelRun | None,
    ProposalDocument | None,
    str | None,
    str | None,
    bool,
]:
    proposal_result = await session.execute(select(Proposal).where(Proposal.id == proposal_id))
    proposal = proposal_result.scalar_one_or_none()
    if not proposal:
        raise LookupError("Proposal not found")

    version_result = await session.execute(
        select(ProposalVersion)
        .where(ProposalVersion.proposal_id == proposal_id)
        .order_by(ProposalVersion.version_number.desc())
        .limit(1)
    )
    version = version_result.scalar_one_or_none()
    if not version:
        raise LookupError("No proposal version found")

    model_version = await select_active_model_version(session, scheme_code)

    document_result = await session.execute(
        select(ProposalDocument)
        .where(
            ProposalDocument.proposal_version_id == version.id,
            ProposalDocument.is_primary.is_(True),
            ProposalDocument.document_role == "main_proposal",
            ProposalDocument.superseded_at.is_(None),
            ProposalDocument.extracted_text.isnot(None),
        )
        .order_by(ProposalDocument.created_at.desc())
        .limit(1)
    )
    document = document_result.scalar_one_or_none()

    rule_version = None
    guideline = None
    if version.guideline_version_id:
        guideline_result = await session.execute(
            select(GuidelineVersion).where(GuidelineVersion.id == version.guideline_version_id).limit(1)
        )
        guideline = guideline_result.scalar_one_or_none()
    if guideline is None:
        guideline_result = await session.execute(
            select(GuidelineVersion)
            .join(FundingScheme, FundingScheme.id == GuidelineVersion.scheme_id)
            .where(
                FundingScheme.code == scheme_code,
                GuidelineVersion.effective_date <= datetime.now(timezone.utc),
            )
            .order_by(GuidelineVersion.effective_date.desc(), GuidelineVersion.published_at.desc())
            .limit(1)
        )
        guideline = guideline_result.scalar_one_or_none()
        if guideline is not None:
            version.guideline_version_id = guideline.id
    if guideline is not None:
        rule_version = guideline.version

    version.rubric_version_id = model_version.rubric_version_id
    rubric_version = None
    rubric_version_row = await session.execute(
        select(RubricVersion).where(RubricVersion.id == model_version.rubric_version_id).limit(1)
    )
    rubric = rubric_version_row.scalar_one_or_none()
    if rubric:
        rubric_version = rubric.version

    existing_result = await session.execute(
        select(ModelRun)
        .where(
            ModelRun.proposal_version_id == version.id,
            ModelRun.model_version_id == model_version.id,
            ModelRun.status.in_(("queued", "running", "completed")),
        )
        .order_by(ModelRun.created_at.desc())
        .limit(1)
    )
    existing_run = existing_result.scalar_one_or_none()
    if existing_run and rerun_reason is None:
        return proposal, version, model_version, existing_run, document, rule_version, rubric_version, True

    proposal.status = "evaluating"

    raw_random_seed = (
        model_version.test_metrics.get("random_seed")
        if isinstance(model_version.test_metrics, dict)
        else None
    )
    registered_random_seed = (
        int(raw_random_seed) if isinstance(raw_random_seed, (int, float, str)) else None
    )

    model_run = ModelRun(
        proposal_version_id=version.id,
        model_version_id=model_version.id,
        status="running",
        scoring_status="pending",
        started_at=datetime.now(timezone.utc),
        engine_version=model_version.model_name,
        extraction_version=document.extraction_version if document else None,
        rule_version=rule_version,
        trigger_user_id=trigger_user_id,
        rerun_reason=rerun_reason,
        input_checksum=(
            version.package_hash
            or (version.content_hash or document.sha256_hash if document else version.content_hash)
        ),
        evaluation_payload={},
        failure_details={},
        random_seed=registered_random_seed,
    )
    session.add(model_run)
    await session.flush()
    await create_audit_event(
        session,
        event_type="evaluation.started",
        resource_type="proposal",
        resource_id=proposal_id,
        details={
            "scheme_code": scheme_code,
            "model_run_id": model_run.id,
            "trigger_user_id": trigger_user_id,
            "rerun_reason": rerun_reason,
        },
    )
    await session.commit()
    return proposal, version, model_version, model_run, document, rule_version, rubric_version, False


async def evaluate_proposal(
    ctx: dict,
    proposal_id: str,
    scheme_code: str,
    trigger_user_id: str | None = None,
    rerun_reason: str | None = None,
) -> dict:
    try:
        if scheme_code not in ACTIVE_SCHEME_CODES:
            await _mark_failure(
                proposal_id,
                None,
                failure_code="unsupported_scheme",
                failure_details={"scheme_code": scheme_code, "supported_schemes": list(ACTIVE_SCHEME_CODES)},
            )
            return {"error": "unsupported_scheme", "proposal_id": proposal_id}
        ensure_active_scheme_code(scheme_code)
        async with async_session_factory() as session:
            try:
                (
                    proposal,
                    version,
                    model_version,
                    model_run,
                    document,
                    rule_version,
                    rubric_version,
                    reused_existing,
                ) = await _create_or_reuse_run(
                    session,
                    proposal_id,
                    scheme_code,
                    trigger_user_id,
                    rerun_reason,
                )
            except LookupError as exc:
                failure_code = "proposal_not_found" if "Proposal not found" in str(exc) else "proposal_version_missing"
                await _mark_failure(
                    proposal_id,
                    None,
                    failure_code=failure_code,
                    failure_details={"stage": "preflight", "exception_type": type(exc).__name__},
                )
                return {"error": failure_code, "proposal_id": proposal_id}
            except RuntimeError as exc:
                failure_code = (
                    "model_version_missing"
                    if str(exc).startswith("No active model/rubric")
                    else "model_registry_invalid"
                )
                await _mark_failure(
                    proposal_id,
                    None,
                    failure_code=failure_code,
                    failure_details={
                        "stage": "preflight",
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    },
                )
                logger.error(
                    "Evaluation preflight failed for proposal %s: %s",
                    proposal_id,
                    exc,
                )
                return {"error": failure_code, "proposal_id": proposal_id}

            if reused_existing and model_run and rerun_reason is None and model_run.status in ("queued", "running", "completed"):
                return {
                    "proposal_id": proposal_id,
                    "status": model_run.status,
                    "model_run_id": model_run.id,
                    "duplicate": True,
                    "evaluation_payload": model_run.evaluation_payload,
                }
            if model_run is None:
                raise RuntimeError("Evaluation run was not created")

            if not document:
                await _mark_failure(
                    proposal_id,
                    model_run.id if model_run else None,
                    failure_code="document_missing",
                    failure_details={"stage": "preflight"},
                )
                return {"error": "document_missing", "proposal_id": proposal_id, "model_run_id": model_run.id if model_run else None}

            extracted_text = document.extracted_text or ""
            if not extracted_text.strip():
                await _mark_failure(
                    proposal_id,
                    model_run.id,
                    failure_code="empty_extracted_text",
                    failure_details={"stage": "evaluation", "document_id": document.id},
                )
                return {"error": "empty_extracted_text", "proposal_id": proposal_id, "model_run_id": model_run.id}

            package_documents: list[dict[str, Any]] = []
            if version.package_status == "confirmed" and version.package_hash:
                package_result = await session.execute(
                    select(ProposalDocument)
                    .where(
                        ProposalDocument.proposal_version_id == version.id,
                        ProposalDocument.superseded_at.is_(None),
                        ProposalDocument.upload_completed_at.isnot(None),
                        ProposalDocument.extracted_text.isnot(None),
                    )
                    .order_by(ProposalDocument.created_at.asc())
                )
                for package_document in package_result.scalars().all():
                    package_documents.append(
                        {
                            "document_id": package_document.id,
                            "requirement_id": package_document.requirement_id,
                            "document_role": package_document.document_role,
                            "file_name": package_document.file_name,
                            "sha256_hash": package_document.sha256_hash,
                            "text": package_document.extracted_text or "",
                        }
                    )
            if not package_documents:
                package_documents = [
                    {
                        "document_id": document.id,
                        "requirement_id": document.requirement_id,
                        "document_role": document.document_role,
                        "file_name": document.file_name,
                        "sha256_hash": document.sha256_hash,
                        "text": extracted_text,
                    }
                ]

            document_gate = assess_document(
                extracted_text,
                scheme_code,
                declared_role=document.document_role,
                file_name=document.file_name,
            )
            structured_data = copy.deepcopy(version.structured_data or {})
            if document_gate.accepted:
                similarity_result = await check_prior_projects(session, document, proposal_id)
                if float(similarity_result.get("highest_similarity", 0.0)) >= float(
                    similarity_result.get("review_threshold", 0.75)
                ):
                    fields = structured_data.setdefault("fields", {})
                    fields["equipment_duplication"] = {
                        "field_name": "equipment_duplication",
                        "normalized_value": "possible_duplicate",
                        "status": "clarification_required",
                        "evidence_coverage": 1.0,
                        "original_text": "High textual overlap with a previously submitted proposal",
                        "validation_warnings": ["Prior-project similarity threshold exceeded"],
                        "extraction_method": "prior_project_similarity_v1",
                    }
                rule_result = await evaluate_rules(scheme_code, structured_data, rule_version)
                scoring_result = await score_proposal(
                    model_version,
                    scheme_code,
                    extracted_text,
                    rubric_version or "1",
                    document_role=document.document_role,
                    evidence_contract_version="1",
                    documents=package_documents,
                )
            else:
                similarity_result = {
                    "status": "not_run",
                    "method": None,
                    "checked_projects": 0,
                    "highest_similarity": 0.0,
                    "matches": [],
                    "reason": "document gate did not permit scoring",
                }
                rule_result = {
                    "scheme_code": scheme_code,
                    "rule_version": rule_version,
                    "summary": {
                        "eligible": False,
                        "has_errors": False,
                        "has_exceptions": False,
                        "requires_human_review": True,
                        "automatic_progression": False,
                        "blocking_statuses": [document_gate.status],
                    },
                    "results": [],
                }
                scoring_result = gate_only_scoring_result(document_gate)

            rule_summary = rule_result.get("summary", {})
            actual_engine_version = str(
                scoring_result.get("engine_version")
                or scoring_result.get("model_source")
                or model_version.model_name
            )
            evaluation_payload = {
                "proposal_id": proposal_id,
                "proposal_version_id": version.id,
                "scheme_code": scheme_code,
                "model_run_id": model_run.id,
                "engine_version": actual_engine_version,
                "trigger_user_id": trigger_user_id,
                "rerun_reason": rerun_reason,
                "document_gate": document_gate.as_dict(),
                "rule_evaluation": rule_result,
                "scoring": scoring_result,
                "prior_project_check": similarity_result,
                "submission_package": {
                    "status": version.package_status,
                    "package_hash": version.package_hash,
                    "policy_version": version.package_policy_version,
                    "confirmed_at": (
                        version.package_confirmed_at.isoformat()
                        if version.package_confirmed_at
                        else None
                    ),
                    "confirmed_by": version.package_confirmed_by,
                    "document_count": len(package_documents),
                    "documents": [
                        {
                            "document_id": item["document_id"],
                            "requirement_id": item.get("requirement_id"),
                            "document_role": item["document_role"],
                            "file_name": item["file_name"],
                            "sha256_hash": item["sha256_hash"],
                        }
                        for item in package_documents
                    ],
                },
                "document_audit": {
                    "document_id": document.id,
                    "file_name": document.file_name,
                    "file_type": document.file_type,
                    "document_role": document.document_role,
                    "classified_role": document_gate.classified_role,
                    "role_status": document_gate.role_status,
                    "word_count": len(extracted_text.split()),
                    "page_count": len(re.findall(r"\[PAGE\s+\d+\]", extracted_text, re.IGNORECASE)) or 1,
                    "ocr_used": document.ocr_used,
                    "ocr_pages": document.ocr_pages or [],
                    "extraction_version": document.extraction_version,
                    "content_hash": document.sha256_hash,
                },
                "input_checksum": model_run.input_checksum,
                "output_checksum": None,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }
            output_checksum = _json_checksum(evaluation_payload)
            evaluation_payload["output_checksum"] = output_checksum

            async with async_session_factory() as persist_session:
                run_result = await persist_session.execute(
                    select(ModelRun).where(ModelRun.id == model_run.id).limit(1)
                )
                persisted_run = run_result.scalar_one_or_none()
                if not persisted_run:
                    raise RuntimeError("Model run disappeared before persistence")

                persisted_run.status = "completed"
                persisted_run.engine_version = actual_engine_version
                persisted_run.total_score = scoring_result.get("total_score")
                persisted_run.diagnostic_score = scoring_result.get("diagnostic_score")
                persisted_run.scoring_status = str(scoring_result.get("scoring_status", "abstained"))
                persisted_run.gate_result = document_gate.as_dict()
                persisted_run.information_sufficiency = scoring_result.get("information_sufficiency", 0)
                persisted_run.confidence = scoring_result.get("confidence")
                persisted_run.completed_at = datetime.now(timezone.utc)
                persisted_run.evaluation_payload = evaluation_payload
                persisted_run.output_checksum = output_checksum
                persisted_run.failure_code = None
                persisted_run.failure_details = {}
                persisted_run.error_message = None

                document_result = await persist_session.execute(
                    select(ProposalDocument).where(ProposalDocument.id == document.id).limit(1)
                )
                persisted_document = document_result.scalar_one_or_none()
                if persisted_document:
                    persisted_document.classified_role = document_gate.classified_role
                    persisted_document.role_status = document_gate.role_status
                    persisted_document.role_confidence = document_gate.classification_reliability
                    persisted_document.role_reason = "; ".join(document_gate.reasons) or "Document gate accepted the declared role."

                abstention_reasons = scoring_result.get("abstention_reasons", [])
                if not isinstance(abstention_reasons, list):
                    abstention_reasons = []
                persisted_run.abstention_reason = (
                    "; ".join(str(reason) for reason in abstention_reasons if str(reason).strip())
                    or "model abstained because reliability thresholds were not met"
                ) if scoring_result.get("abstention") else None

                rule_defs_result = await persist_session.execute(
                    select(RuleDefinition).where(
                        RuleDefinition.rule_id.in_(
                            [entry["rule_id"] for entry in rule_result.get("results", [])]
                        )
                    )
                )
                rule_defs = {rule.rule_id: rule for rule in rule_defs_result.scalars().all()}

                rubric_result = await persist_session.execute(
                    select(RubricCriterion)
                    .where(RubricCriterion.rubric_version_id == model_version.rubric_version_id)
                    .order_by(RubricCriterion.order.asc())
                )
                rubric_criteria = rubric_result.scalars().all()
                rubric_lookup: dict[str, RubricCriterion] = {}
                for criterion in rubric_criteria:
                    for key in _criterion_lookup_keys(criterion):
                        if key not in rubric_lookup:
                            rubric_lookup[key] = criterion

                for entry in rule_result.get("results", []):
                    rule_def = rule_defs.get(entry["rule_id"])
                    if not rule_def:
                        continue
                    result_value = _normalize_rule_result(entry.get("result", "unresolved"))
                    field_name = str(entry.get("field") or "")
                    canonical_fields = structured_data.get("fields", {}) if isinstance(structured_data, dict) else {}
                    field_entry = canonical_fields.get(field_name, {}) if isinstance(canonical_fields, dict) else {}
                    if not isinstance(field_entry, dict):
                        field_entry = {}
                    evidence_payload = {
                        "scheme_code": scheme_code,
                        "rule_version": rule_version,
                        "source_reference": entry.get("source_reference"),
                        "detail": entry.get("detail"),
                        "field": field_name,
                        "field_entry": field_entry,
                    }
                    persist_session.add(
                        RuleResult(
                            model_run_id=persisted_run.id,
                            rule_definition_id=rule_def.id,
                            rule_identifier=entry.get("rule_id"),
                            rule_version=rule_version,
                            result=result_value,
                            evidence_coverage=entry.get("evidence_coverage"),
                            detail=entry.get("detail"),
                            evidence={
                                "input_value": field_entry.get("normalized_value"),
                                "summary": rule_summary,
                                "metadata": evidence_payload,
                            },
                            input_payload=structured_data,
                            explanation=entry.get("detail"),
                            evidence_excerpt=field_entry.get("original_text") or entry.get("detail"),
                            page_reference=str(field_entry.get("page")) if field_entry.get("page") is not None else None,
                            section_reference=field_entry.get("section"),
                            warnings=[],
                        )
                    )

                for category in scoring_result.get("category_scores", []):
                    for entry in category.get("criteria", []):
                        matched_criterion = rubric_lookup.get(entry.get("criterion_id", "").lower())
                        if matched_criterion is None:
                            continue
                        criterion_prediction = CriterionPrediction(
                            model_run_id=persisted_run.id,
                            rubric_criterion_id=matched_criterion.id,
                            ordinal_grade=entry.get("ordinal_grade"),
                            awarded_score=entry.get("awarded_score"),
                            maximum_score=entry.get("maximum_score", matched_criterion.maximum),
                            category_score=category.get("awarded"),
                            confidence=entry.get("confidence"),
                            evidence_coverage=entry.get("evidence_coverage"),
                            information_sufficiency=entry.get("information_sufficiency"),
                            missing_evidence=entry.get("missing_evidence", []),
                            criterion_status=entry.get("criterion_status", "unresolved"),
                            released=bool(entry.get("released", False)),
                            evidence_count=int(entry.get("evidence_count", len(entry.get("evidence", [])))),
                            abstention=bool(scoring_result.get("abstention")),
                            model_source=scoring_result.get("model_source", model_version.model_name),
                            rationale=entry.get("rationale"),
                            warnings=entry.get("warnings", []),
                        )
                        persist_session.add(criterion_prediction)
                        await persist_session.flush()
                        for ev in entry.get("evidence", []):
                            persist_session.add(
                                CriterionEvidence(
                                    criterion_prediction_id=criterion_prediction.id,
                                    passage_text=ev.get("text") or ev.get("keyword", ""),
                                    source_page=ev.get("source_page"),
                                    source_section=ev.get("source_section"),
                                    char_start=ev.get("char_start"),
                                    char_end=ev.get("char_end"),
                                    relevance_score=float(ev.get("relevance_score", ev.get("count", 0))),
                                    assertion_state="contract_accepted",
                                    document_role=ev.get("document_role", document.document_role),
                                    verification_status=ev.get("verification_status", "contract_accepted"),
                                    verification_reason=ev.get("verification_reason"),
                                    retrieval_rank=entry.get("evidence", []).index(ev) + 1,
                                )
                            )

                for match in similarity_result.get("matches", []):
                    persist_session.add(
                        SimilarityMatch(
                            model_run_id=persisted_run.id,
                            matched_proposal_version_id=match["proposal_version_id"],
                            similarity_score=float(match["similarity"]),
                            method=str(similarity_result.get("method", "word-5gram-jaccard-v1")),
                            matched_passages=match.get("matched_passages", []),
                            review_flag="review" if float(match["similarity"]) >= 0.75 else "none",
                        )
                    )

                proposal_result = await persist_session.execute(
                    select(Proposal).where(Proposal.id == proposal_id)
                )
                persisted_proposal = proposal_result.scalar_one_or_none()
                automatic_progression = rule_summary.get("automatic_progression")
                if automatic_progression is None:
                    automatic_progression = not bool(rule_summary.get("has_errors")) and not bool(
                        rule_summary.get("blocking_statuses")
                    )
                scorer_abstained = bool(scoring_result.get("abstention"))
                if document_gate.status in {
                    "invalid_document",
                    "wrong_scheme",
                    "insufficient_extraction",
                    "role_disallowed",
                }:
                    next_status = "revision_required"
                    transition_reason = f"document_gate_{document_gate.status}"
                elif document_gate.status == "manual_review":
                    next_status = "human_review"
                    transition_reason = "document_gate_manual_review"
                else:
                    next_status = (
                        "revision_required"
                        if not bool(automatic_progression)
                        else "human_review"
                    )
                    transition_reason = (
                        "automated_scorer_abstained_human_review_required"
                        if scorer_abstained and next_status == "human_review"
                        else "evaluation_completed"
                    )
                if persisted_proposal:
                    old_status = persisted_proposal.status
                    persisted_proposal.status = next_status

                await create_audit_event(
                    persist_session,
                    event_type="evaluation.completed",
                    resource_type="proposal",
                    resource_id=proposal_id,
                    details={
                        "total_score": scoring_result.get("total_score"),
                        "diagnostic_score": scoring_result.get("diagnostic_score"),
                        "scoring_status": scoring_result.get("scoring_status"),
                        "document_gate_status": document_gate.status,
                        "information_sufficiency": scoring_result.get("information_sufficiency"),
                        "rule_summary": rule_summary,
                        "model_run_id": persisted_run.id,
                        "status": next_status,
                        "scorer_abstained": scorer_abstained,
                        "decision_authority": "human_only",
                    },
                )
                if persisted_proposal:
                    await create_audit_event(
                        persist_session,
                        event_type="proposal.status_transition",
                        resource_type="proposal",
                        resource_id=proposal_id,
                        details={"from": old_status, "to": next_status, "reason": transition_reason},
                    )
                await persist_session.commit()

            return {
                "proposal_id": proposal_id,
                "status": "completed",
                "model_run_id": model_run.id,
                "total_score": scoring_result.get("total_score"),
                "diagnostic_score": scoring_result.get("diagnostic_score"),
                "scoring_status": scoring_result.get("scoring_status"),
                "document_gate": document_gate.as_dict(),
                "information_sufficiency": scoring_result.get("information_sufficiency"),
                "rule_summary": rule_summary,
                "evaluation_payload": evaluation_payload,
            }

    except asyncio.CancelledError:
        failed_model_run = locals().get("model_run")
        failed_model_run_id = (
            failed_model_run.id if isinstance(failed_model_run, ModelRun) else None
        )
        await asyncio.shield(
            _mark_failure(
                proposal_id,
                failed_model_run_id,
                failure_code="evaluation_cancelled",
                failure_details={"stage": "evaluation"},
            )
        )
        raise
    except Exception as exc:
        logger.exception(
            "Proposal evaluation failed",
            extra={"proposal_id": proposal_id, "scheme_code": scheme_code},
        )
        failed_model_run = locals().get("model_run")
        failed_model_run_id = failed_model_run.id if isinstance(failed_model_run, ModelRun) else None
        await _mark_failure(
            proposal_id,
            failed_model_run_id,
            failure_code="evaluation_exception",
            failure_details={
                "stage": "evaluation",
                "exception_type": type(exc).__name__,
                "exception_message": str(exc)[:500],
            },
        )
        return {"error": "evaluation_failed", "proposal_id": proposal_id}


async def extract_document(ctx: dict, document_id: str) -> dict:
    """Background document extraction and field detection."""
    from app.models.proposal import ExtractedField, ProposalDocument, ProposalSection

    async with async_session_factory() as session:
        result = await session.execute(
            select(ProposalDocument).where(ProposalDocument.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if not doc or not doc.extracted_text:
            return {"error": "Document not found or no text", "document_id": document_id}

        text = doc.extracted_text
        await session.execute(delete(ProposalSection).where(ProposalSection.document_id == document_id))
        await session.execute(delete(ExtractedField).where(ExtractedField.document_id == document_id))
        sections = await detect_sections(text)
        for sec in sections:
            section_obj = ProposalSection(
                document_id=document_id,
                section_type=sec["section_type"],
                heading=sec.get("heading"),
                text=sec.get("text"),
                start_page=sec.get("start_page"),
                end_page=sec.get("end_page"),
                char_start=sec.get("char_start"),
                char_end=sec.get("char_end"),
                confidence=sec.get("confidence"),
            )
            session.add(section_obj)

        fields = await extract_structured_fields(text)
        for f in fields:
            field_obj = ExtractedField(
                document_id=document_id,
                field_name=f["field_name"],
                field_value=f.get("field_value"),
                normalized_value=str(f.get("normalized_value")) if f.get("normalized_value") is not None else None,
                field_unit=f.get("unit"),
                original_text=f.get("original_text"),
                source_page=f.get("source_page"),
                char_start=f.get("char_start"),
                char_end=f.get("char_end"),
                evidence_coverage=f.get("evidence_coverage"),
                validation_warnings=f.get("validation_warnings", []),
            )
            session.add(field_obj)

        await session.commit()
        return {"document_id": document_id, "sections": len(sections), "fields": len(fields)}


async def _heartbeat_loop(redis: Any) -> None:
    interval = max(settings.worker_heartbeat_ttl_seconds // 3, 10)
    while True:
        await redis.set(
            settings.worker_heartbeat_key,
            datetime.now(timezone.utc).isoformat(),
            ex=settings.worker_heartbeat_ttl_seconds,
        )
        await asyncio.sleep(interval)


async def worker_startup(ctx: dict[str, Any]) -> None:
    redis = ctx.get("redis")
    if redis is None:
        raise RuntimeError("ARQ Redis connection is unavailable during startup")
    await redis.set(
        settings.worker_heartbeat_key,
        datetime.now(timezone.utc).isoformat(),
        ex=settings.worker_heartbeat_ttl_seconds,
    )
    ctx["heartbeat_task"] = asyncio.create_task(
        _heartbeat_loop(redis), name="mulyankan-worker-heartbeat"
    )


async def worker_shutdown(ctx: dict[str, Any]) -> None:
    task = ctx.get("heartbeat_task")
    if isinstance(task, asyncio.Task):
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    redis = ctx.get("redis")
    if redis is not None:
        await redis.delete(settings.worker_heartbeat_key)


class WorkerSettings:
    redis_settings = settings.arq_redis_settings
    on_startup = worker_startup
    on_shutdown = worker_shutdown
    functions = [evaluate_proposal, extract_document]
    poll_delay = 0.5
    max_jobs = 10
