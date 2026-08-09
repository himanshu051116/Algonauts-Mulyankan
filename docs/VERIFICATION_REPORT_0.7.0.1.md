# Mulyankan 0.7.0.1 Source Verification Report

**Release:** 0.7.0.1 — Governed Package Evaluation Persistence Hotfix  
**Database migration:** None

## Verified defect

A confirmed governed package includes a timezone-aware `package_confirmed_at` value. Release 0.7.0 placed that Python `datetime` directly inside a JSONB evaluation payload. The checksum helper tolerated it through `default=str`, but PostgreSQL JSON serialization did not. The worker consequently failed after document extraction and in-memory evaluation, before result persistence.

## Corrections verified

- Package confirmation timestamps are converted to ISO 8601 strings before JSONB persistence.
- Failed current runs synthesize `evaluation_failed`, not `legacy_unverified`.
- Unexpected worker exceptions are logged and retain bounded internal failure details.
- A regression test now executes worker persistence with a confirmed package timestamp.

## Automated results

- Backend: 189 passed, 3 skipped.
- Ruff: passed.
- Mypy: no issues in 51 source files.
- Frontend ESLint: passed with zero warnings.
- TypeScript and Vite production build: passed.

## Compatibility

The hotfix changes no database schema, package manifest format, evidence thresholds, document policy, scoring rubric, authentication contract, object-storage layout, or API route. Existing 0.7.0 uploads remain valid and the failed proposal can be rerun after deployment.
