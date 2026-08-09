# Mulyankan 0.6.3 verification report

## Scope

This report covers the Phase 1 evidence-gated scoring upgrade applied to the 0.6.1 portable source.

## Final source-level verification

The final working tree passed:

- Python bytecode compilation.
- Ruff static analysis.
- Mypy type analysis across 56 application, migration and quality-script modules.
- Backend test suite: **180 passed, 3 skipped**.
- Coverage run: **81% total**, above the enforced 70% minimum.
- Frontend dependency installation from the public npm registry.
- Frontend ESLint with zero warnings.
- Frontend TypeScript/Vite production build: 1,655 modules transformed successfully.
- npm security audit: zero known vulnerabilities at all reported severities.
- Docker Compose static validation, Dockerfile COPY-source validation and runtime CSP-template validation.
- Alembic graph: one linear head, `20260708_scoring_safety`.
- Offline Alembic upgrade SQL rendering: 858 lines.
- Offline Alembic downgrade SQL rendering: 380 lines.
- Release packaging and secret-exclusion tests.

## Accuracy and safety regression coverage

The tests cover:

- valid Coal S&T proposal gate acceptance;
- standalone résumé rejection;
- supporting-document role rejection as primary input;
- reference brochure rejection;
- conservative manual review for ambiguous and low-structure cases;
- no-evidence-no-score behaviour;
- suffix and prefix negation handling;
- generic single-keyword non-release;
- keyword-stuffing non-release;
- evidence-contract section and document-role restrictions;
- legacy evaluation payload sanitisation;
- preservation of historical criterion values for audit and rollback;
- worker persistence, cancellation and failure recovery;
- trained-model registry policy versioning;
- fail-closed rules-only fallback behaviour;
- release archive exclusion of `.env`, backups, caches and generated dependencies;
- runtime frontend CSP substitution from `STORAGE_PUBLIC_ENDPOINT`.

## Triple-verification definition

### Pass 1 — upgraded working tree

Compile, Ruff, Mypy, full backend tests, coverage, frontend lint/build/audit, Compose validation and offline Alembic upgrade/downgrade checks are executed against the modified source tree.

### Pass 2 — packaged clean extraction

The secret-free ZIP is extracted into a new directory. Manifest hashes, archive hygiene, dependency installation, backend tests, frontend checks, Compose validation and Alembic checks are rerun without relying on the working tree.

### Pass 3 — target Docker deployment

The included Windows upgrade script performs PostgreSQL backup, image build, migration and seed twice, complete startup, readiness checks, database safety queries and live CSP verification on a machine with Docker Desktop, PostgreSQL, Redis and MinIO containers.

The release-building environment does not provide a Docker daemon. Therefore live container migration, real PostgreSQL upgrade, MinIO upload, Supabase authentication and browser end-to-end checks must still pass on the target Windows machine before 0.6.3 replaces the working 0.6.1 deployment.

## Residual model limitation

The statistical artifact remains trained on brochure-derived weak supervision. Its near-perfect bootstrap metrics are pipeline sanity metrics, not real-world expert agreement. The system must remain advisory and human-controlled until an expert-adjudicated dataset supports calibration, false-decision analysis and shadow-mode validation.

## Release boundary

Mulyankan 0.6.3 is a fail-closed scoring-safety release. It does not yet include multi-file submission packages, layout-aware extraction, semantic cross-encoder reranking, independent entailment verification, expert-trained ordinal scoring or institutionally calibrated release thresholds. Those remain later roadmap phases.
