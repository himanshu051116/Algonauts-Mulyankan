# Mulyankan 0.7.0 Verification Report

**Release:** 0.7.0 — Governed Submission Packages  
**Verification date:** 8 July 2026  
**Source baseline:** `Mulyankan_0.6.3_FINAL_UI_Eligibility_Clarified(1).zip`

## Scope verified

The upgrade was applied directly to the supplied 0.6.3 source. Verification covered the new package policy, requirement-bound uploads, package confirmation, manifest hashing, database migration, supporting-document evidence isolation, frontend package workflow and regression of the existing evidence-gated evaluation stack.

## Automated results

| Gate | Result |
|---|---|
| Python compilation | Passed |
| Ruff | Passed |
| Mypy | Passed; no issues in 51 source files |
| Backend tests | 188 passed, 3 skipped |
| Backend coverage | 73.32%; required threshold 70% |
| Alembic offline PostgreSQL rendering | Passed through `20260708_packages` |
| Frontend ESLint | Passed with zero warnings |
| TypeScript/Vite production build | Passed |
| npm audit | Passed; 0 vulnerabilities |
| Compose/build-context fallback validator | Passed |
| Governed-package direct tests | 4 passed |

The skipped tests are pre-existing environment-dependent cases. One pre-existing Starlette/httpx deprecation warning remains and does not represent a 0.7.0 failure.

## Package-governance assertions

The direct tests demonstrate that:

- a proposal body alone remains incomplete and reports all missing mandatory requirements;
- a complete package produces a stable manifest and identical SHA-256 package hash independent of document order;
- a permitted budget annexure can contribute criterion evidence with document ID, file name and role provenance;
- budget-like text in a PI CV cannot release the budget criterion because the role is disallowed by the evidence contract.

The complete regression suite also confirms that the 0.6.3 document gate, no-evidence-no-score behavior, abstention, upload integrity, proposal versioning, worker execution and queue-failure handling remain intact.

## Migration verification

Alembic rendered the full PostgreSQL chain successfully and advanced the expected head from `20260708_scoring_safety` to `20260708_packages`. The migration:

- adds package metadata and confirmation attribution to proposal versions;
- adds governed requirement IDs to upload sessions and proposal documents;
- enforces one active document per requirement;
- marks historical non-draft versions `legacy_single_document` without fabricating a manifest or confirmation.

No rubric, model artifact, criterion prediction, model-run score, review or committee-decision data is rewritten by this migration.

## Compatibility review

- The main proposal remains the only authoritative source for canonical structured fields and document-quality gating.
- Supporting uploads supersede only the same requirement slot and cannot replace the main proposal.
- Package mutation clears confirmation and package identity.
- PDF and DOCX are presented in the governed browser workflow; TXT main-proposal upload remains accepted at the API layer for 0.6.3 compatibility.
- Historical evaluated versions remain readable as legacy snapshots.
- New or revised proposals must complete and confirm the 0.7.0 package before submission.

## Runtime limitation

Docker is not installed in the verification environment, so live container startup, PostgreSQL migration execution, Redis/ARQ connectivity, MinIO object operations, Supabase authentication and browser-based end-to-end evaluation were not executed here. Compose YAML and Docker build contexts passed the repository fallback validator. The supplied Windows upgrade script performs backup, live migration, idempotence, health and database invariant checks on the target machine.

## Release conclusion

The source is eligible for packaging as Mulyankan 0.7.0. Deployment should follow `UPGRADE_AND_ROLLBACK_0.7.0.md`, retain the 0.6.3 source and pre-upgrade database backup, and complete the target-host Docker verification before institutional use.
