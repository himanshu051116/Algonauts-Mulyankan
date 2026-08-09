"""Governed multi-document submission packages for proposal versions.

The package policy is configuration-driven. A package becomes confirmable only
when every mandatory requirement is represented by one active, integrity-
confirmed document with the configured role and file type. The canonical
manifest is hashed so the exact applicant-confirmed package can be reproduced
for evaluation and audit.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import yaml

POLICY_DIR = Path(__file__).resolve().parents[3] / "data" / "schemes"


class SubmissionPackagePolicyError(ValueError):
    """Raised when a submission-package policy is missing or malformed."""


def load_submission_policy(scheme_code: str) -> dict[str, Any]:
    path = POLICY_DIR / f"{scheme_code.lower()}-required-documents-v1.yaml"
    if not path.exists():
        raise SubmissionPackagePolicyError(
            f"No governed submission-package policy is configured for {scheme_code}"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SubmissionPackagePolicyError(f"Invalid submission-package policy: {path}")
    requirements = raw.get("required_documents")
    if not isinstance(requirements, list) or not requirements:
        raise SubmissionPackagePolicyError(
            f"Submission-package policy contains no requirements: {path}"
        )
    seen: set[str] = set()
    normalised: list[dict[str, Any]] = []
    for index, item in enumerate(requirements):
        if not isinstance(item, dict):
            raise SubmissionPackagePolicyError(
                f"required_documents[{index}] must be a mapping"
            )
        requirement_id = str(item.get("id", "")).strip()
        document_role = str(item.get("document_role", "")).strip()
        allowed_types = item.get("allowed_types")
        if not requirement_id or requirement_id in seen:
            raise SubmissionPackagePolicyError(
                f"Duplicate or blank requirement id at index {index}"
            )
        if not document_role:
            raise SubmissionPackagePolicyError(
                f"Requirement {requirement_id} has no document_role"
            )
        if not isinstance(allowed_types, list) or not allowed_types:
            raise SubmissionPackagePolicyError(
                f"Requirement {requirement_id} has no allowed_types"
            )
        seen.add(requirement_id)
        normalised.append(
            {
                "id": requirement_id,
                "label": str(item.get("label", requirement_id)),
                "description": str(item.get("description", "")),
                "document_role": document_role,
                "allowed_types": [str(value).lower().lstrip(".") for value in allowed_types],
                "mandatory": bool(item.get("mandatory", False)),
                "max_size_mb": int(item.get("max_size_mb", 50)),
            }
        )
    return {
        "scheme_code": str(raw.get("scheme_code", scheme_code)),
        "version": str(raw.get("version", "v1")),
        "requirements": normalised,
    }


def requirement_for(
    scheme_code: str, requirement_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    policy = load_submission_policy(scheme_code)
    for requirement in policy["requirements"]:
        if requirement["id"] == requirement_id:
            return policy, requirement
    raise SubmissionPackagePolicyError(
        f"Unknown submission requirement '{requirement_id}' for {scheme_code}"
    )


def _document_record(document: Any) -> dict[str, Any]:
    return {
        "id": str(document.id),
        "requirement_id": getattr(document, "requirement_id", None),
        "document_role": str(document.document_role),
        "file_name": str(document.file_name),
        "file_type": str(document.file_type).lower().lstrip("."),
        "file_size": int(document.file_size),
        "sha256_hash": str(document.sha256_hash),
        "is_primary": bool(document.is_primary),
        "role_status": str(document.role_status),
        "has_extractable_text": bool((document.extracted_text or "").strip()),
        "upload_completed": document.upload_completed_at is not None,
        "created_at": (
            document.created_at.isoformat() if getattr(document, "created_at", None) else None
        ),
    }


def build_submission_package_summary(
    *,
    scheme_code: str,
    proposal_id: str,
    version: Any,
    documents: Iterable[Any],
) -> dict[str, Any]:
    policy = load_submission_policy(scheme_code)
    active = [
        document
        for document in documents
        if getattr(document, "superseded_at", None) is None
        and getattr(document, "upload_completed_at", None) is not None
    ]
    records = [_document_record(document) for document in active]
    by_requirement: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        requirement_id = record.get("requirement_id")
        if requirement_id:
            by_requirement.setdefault(str(requirement_id), []).append(record)

    checks: list[dict[str, Any]] = []
    missing_mandatory: list[str] = []
    invalid_requirements: list[str] = []
    for requirement in policy["requirements"]:
        matches = by_requirement.get(requirement["id"], [])
        status = "missing"
        document_id: str | None = None
        reason: str | None = None
        if len(matches) > 1:
            status = "invalid"
            reason = "More than one active document is assigned to this requirement."
        elif len(matches) == 1:
            document = matches[0]
            document_id = str(document["id"])
            if document["document_role"] != requirement["document_role"]:
                status = "invalid"
                reason = "Declared document role does not match the governed requirement."
            elif document["file_type"] not in requirement["allowed_types"]:
                status = "invalid"
                reason = "File type is not permitted for this requirement."
            elif document["file_size"] > requirement["max_size_mb"] * 1024 * 1024:
                status = "invalid"
                reason = "File exceeds the requirement-specific size limit."
            elif not document["sha256_hash"] or not document["upload_completed"]:
                status = "invalid"
                reason = "Upload integrity confirmation is incomplete."
            elif requirement["document_role"] == "main_proposal" and not document[
                "has_extractable_text"
            ]:
                status = "invalid"
                reason = "The main proposal has no extractable text."
            else:
                status = "complete"
        if requirement["mandatory"] and status != "complete":
            missing_mandatory.append(requirement["id"])
        if status == "invalid":
            invalid_requirements.append(requirement["id"])
        checks.append(
            {
                **requirement,
                "status": status,
                "document_id": document_id,
                "reason": reason,
            }
        )

    primary_documents = [
        record
        for record in records
        if record["is_primary"] and record["document_role"] == "main_proposal"
    ]
    unassigned_document_ids = [
        str(record["id"]) for record in records if not record.get("requirement_id")
    ]
    ready = (
        not missing_mandatory
        and not invalid_requirements
        and len(primary_documents) == 1
        and not unassigned_document_ids
    )

    manifest_documents = [
        {
            "document_id": record["id"],
            "requirement_id": record["requirement_id"],
            "document_role": record["document_role"],
            "file_name": record["file_name"],
            "file_type": record["file_type"],
            "file_size": record["file_size"],
            "sha256_hash": record["sha256_hash"],
            "is_primary": record["is_primary"],
        }
        for record in sorted(
            records,
            key=lambda value: (
                str(value.get("requirement_id") or "~"),
                str(value["document_id"] if "document_id" in value else value["id"]),
            ),
        )
    ]
    manifest = {
        "manifest_version": "1.0",
        "policy_version": policy["version"],
        "scheme_code": scheme_code,
        "proposal_id": proposal_id,
        "proposal_version_id": str(version.id),
        "proposal_version_number": int(version.version_number),
        "documents": manifest_documents,
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    package_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    stored_status = str(getattr(version, "package_status", "draft"))
    if stored_status in {"confirmed", "legacy_single_document"}:
        effective_status = stored_status
    elif ready:
        effective_status = "ready"
    elif records:
        effective_status = "incomplete"
    else:
        effective_status = "draft"

    return {
        "proposal_id": proposal_id,
        "proposal_version_id": str(version.id),
        "proposal_version_number": int(version.version_number),
        "scheme_code": scheme_code,
        "policy_version": policy["version"],
        "package_status": effective_status,
        "package_hash": getattr(version, "package_hash", None),
        "package_confirmed_at": getattr(version, "package_confirmed_at", None),
        "package_confirmed_by": getattr(version, "package_confirmed_by", None),
        "ready_to_confirm": ready,
        "missing_mandatory_requirements": missing_mandatory,
        "invalid_requirements": invalid_requirements,
        "unassigned_document_ids": unassigned_document_ids,
        "requirements": checks,
        "documents": records,
        "canonical_manifest": manifest,
        "computed_package_hash": package_hash,
    }
