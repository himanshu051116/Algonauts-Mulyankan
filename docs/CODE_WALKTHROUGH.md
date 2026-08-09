# Mulyankan code walkthrough

This is a short map of the code paths that define Mulyankan's behaviour. It is meant for someone who wants to inspect the implementation without reading every file in the repository.

## 1. Proposal intake

The proposal workflow starts in the frontend under:

- `src/features/proposals/SubmissionStudio.tsx`
- `src/features/proposals/SubmissionHistory.tsx`

On the backend, submission/version handling is mainly implemented in:

- `backend/app/routers/proposals.py`
- `backend/app/services/submission_packages.py`
- `backend/app/services/document.py`
- `backend/app/services/document_gate.py`

The important design choice is that evaluation is tied to a proposal version rather than an unversioned mutable upload.

## 2. Evidence before score

The central evaluation path is:

- `backend/app/services/evaluation_engine.py`
- `backend/app/services/evidence_contracts.py`
- `backend/app/services/rules.py`
- `backend/app/services/scoring.py`
- `backend/app/ml/inference.py`

Supporting definitions are versioned under:

- `data/evidence-contracts/`
- `data/rules/` (versioned rubric and eligibility definitions)
- `data/schemes/`

A criterion is not simply handed to the model. The document gate and evidence contract determine whether the criterion has enough accepted evidence to be evaluated. This is also why an evaluation can abstain instead of producing a normal total.

## 3. Human review

Reviewer-facing state and expert scoring are handled through:

- `backend/app/routers/reviews.py`
- `backend/app/routers/governance.py`
- `src/features/reviews/`

The model output is advisory. Reviewer notes, criterion scores and recommendations remain separate records.

## 4. Validation and shadow review

The validation workflow is one of the more project-specific parts of release 0.8.0:

- `backend/app/services/validation.py`
- `backend/app/routers/validation.py`
- `src/features/validation/ValidationLab.tsx`
- `src/features/validation/ShadowReviewDesk.tsx`

It supports expert/model comparison without silently turning validation results into proposal decisions.

## 5. Audit and security

Useful files to inspect:

- `backend/app/auth.py`
- `backend/app/services/access.py`
- `backend/app/services/audit.py`
- `backend/app/services/signing.py`
- `backend/app/services/malware.py`
- `backend/app/routers/audit.py`

These cover access policy, audit events, integrity envelopes and upload-security controls.

## 6. Model and training provenance

The model pipeline is under `backend/app/ml/`. Reproducibility inputs and model documentation are under:

- `data/training/moc-brochure-weak-label-spec-v1.yaml`
- `data/training/expert-labelled-record.schema.json`
- `data/models/moc-brochure-hybrid-ml-v2/`

The generated weak-supervision JSONL is not stored in Git. It can be regenerated from the versioned specification with the training CLI.

## 7. Tests worth sampling

These tests cover behaviour that is important to the actual product rather than only endpoint happy paths:

- `backend/tests/test_access_policy.py`
- `backend/tests/test_document_gate.py`
- `backend/tests/test_scoring.py`
- `backend/tests/test_submission_packages.py`
- `backend/tests/test_upload_integrity.py`
- `backend/tests/test_validation_pilot.py`
- `backend/tests/test_registry_consistency_hotfix.py`
- `backend/tests/test_release_packaging.py`

## 8. Build and release checks

- `.github/workflows/quality.yml`
- `scripts/quality/validate-release.sh`
- `scripts/quality/create-release.py`
- `scripts/quality/verify-release.py`
- `scripts/quality/validate_compose.py`

These are useful for reproducing the checks used on the cleaned submission snapshot.
