# Mulyankan 0.8.0 Verification Report

## Release purpose

Mulyankan 0.8.0 adds the infrastructure required to collect expert-grounded labels and operate a controlled shadow pilot. It does not claim that the current bootstrap-trained scoring model is scientifically validated, calibrated for official decisions, or approved for autonomous selection.

## Baseline and compatibility scope

- Source baseline: Mulyankan 0.7.0.3.
- Database changes: two forward additive Alembic revisions, `20260709_validation_pilot` and `20260712_model_lifecycle`.
- Existing proposal, document, upload, evaluation, model-run, review, adjudication, committee and audit records are preserved.
- Existing API operations are retained. Version 0.8.0 adds isolated `/api/v1/validation/*` operations.
- Existing evaluator artifact and scoring thresholds are unchanged.
- The preferred rollback is application-code rollback to the preserved 0.7.0.3 source while retaining the additive 0.8.0 tables.

## Implemented validation controls

- Study-level freezing of scheme, rubric version, rubric-definition hash, model version, model-artifact hash, protocol version and annotation-rulebook version.
- Proposal-group uniqueness within a study so different versions of one proposal cannot cross partitions.
- Development, internal-test, external-test and shadow partitions.
- At least two independent reviews per included case.
- Blindness of model results, peer reviews, machine-extracted fields, adjudications, committee outcomes and proposal outcome status until the reviewer submits an immutable review.
- Criterion-level score, rationale and source-page provenance requirements.
- Auditable reviewer conflict declaration.
- Auditable case exclusion before study freeze; compared cases cannot be excluded.
- Material expert-disagreement detection using a 15-point total-score range or recommendation disagreement, with adjudication recommended before training-label approval.
- Observational score error, correlation, selective-release, reviewer-agreement, criterion-error and calibration-proxy metrics.
- Partitioned metric snapshots and versioned JSONL export after study freeze.
- Explicit isolation from proposal status, advisory score and committee-decision workflows.

## Source-tree verification

The complete source tree was rechecked after the final 0.8.0 changes.

| Gate | Result |
|---|---|
| Python compilation | Passed |
| Ruff | Passed |
| Mypy | Passed — 60 source files |
| Backend tests | Passed — 225 passed, 3 environment-dependent skipped |
| Backend coverage | 70.11% — required threshold 70% |
| Frontend ESLint | Passed, zero warnings |
| TypeScript + Vite production build | Passed |
| npm audit | Passed — 0 vulnerabilities |
| Compose/build-context static validation | Passed |
| Alembic full offline render | Passed |
| 0.7.0.3 → 0.8.0 offline upgrade render | Passed |
| Destructive SQL scan of forward migration | Passed — no DROP TABLE, DROP COLUMN, TRUNCATE or DELETE FROM |
| OpenAPI compatibility | Passed — 40 existing operations retained; 11 operations added; none removed |
| Shared schema compatibility | Passed — no old property removed and no new required field added to shared schemas |
| Source-file compatibility | Passed — no baseline source file removed |

## Validation-specific regression coverage

Dedicated tests cover:

- two-review minimum and reviewer consensus;
- material-disagreement flags;
- score correlations and explicit recommendation bands;
- blind model-output and sensitive-outcome access blocking;
- criterion rationale and page-provenance requirements;
- frozen model/rubric identity;
- irreversible frozen-study transitions;
- additive migration structure;
- auditable pre-freeze case exclusion;
- Windows backup, record-preservation, schema and registry verification logic;
- release-package exclusion of runtime backups and secrets.

## Target-host verification

The release includes `scripts/windows/upgrade-expert-validation-0.8.0.ps1`. On the target Windows Docker environment it:

1. validates Docker and Compose;
2. starts and checks PostgreSQL, Redis and MinIO;
3. records pre-upgrade core table counts;
4. creates a timestamped PostgreSQL and configuration backup;
5. rebuilds migration, backend, worker and frontend images;
6. verifies identical evaluator hashes across evaluator-bearing images;
7. runs the additive migration and reference/model-registry refresh;
8. verifies the active model registry and 0.8 schema;
9. confirms core record counts are unchanged;
10. recreates services and verifies version `0.8.0` and readiness;
11. repeats live registry/schema checks inside the running containers.

Docker is not available in the release-construction environment, so a live PostgreSQL migration and container startup were not falsely claimed here. Those checks are deliberately fail-closed in the target-host installer and must pass before a pilot study is created.

## Scientific limitation

This release validates the software workflow and data-governance controls, not the predictive validity of the scoring model. A credible institutional model claim still requires qualified domain experts, an approved annotation protocol, adequate sample sizes, an institution/time-held-out external test set, adjudication of disputed labels, calibration and failure analysis, fairness review, shadow-pilot results and competent-authority sign-off.

## Maintenance rectification

The maintained source removes a duplicate stale readiness revision, derives validation-script expectations from the single Alembic head, adds the frontend password-recovery flow, isolates the example Compose namespace as `mulyankan-080`, and excludes obsolete broken script copies from controlled releases.

## Release conclusion

Mulyankan 0.8.0 is suitable for controlled expert-label collection and shadow-mode observational validation. It must remain advisory and must not be represented as an officially validated or autonomous funding-decision model.
