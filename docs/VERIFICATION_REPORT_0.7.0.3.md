# Mulyankan 0.7.0.3 Source Verification Report

**Release:** 0.7.0.3 — Registry-Consistency and Failure-State Hotfix  
**Migration head:** unchanged (`20260708_packages`)

## Verified regression

The live probe showed an active, effective MOC-ST model (`moc-brochure-hybrid-ml-v2-evidence-v1`) whose registered artifact hash did not match the packaged evaluator. The worker therefore returned `model_registry_invalid`/the earlier generic `model_version_missing` before creating a model run.

## Automated checks

- Backend tests: 198 passed, 3 skipped.
- Ruff: passed.
- Mypy: passed across 56 source files.
- Frontend ESLint: passed with zero warnings.
- TypeScript/Vite production build: passed.
- npm audit: zero vulnerabilities.
- Python compileall: passed.
- Release manifest and clean archive checks are performed during packaging.

## Operational verification added

The Windows installer fails closed unless migration, backend and worker images compute the same packaged evaluator hash. It then runs the idempotent migration/seed path and validates the active registry row from both worker and backend images before and after service startup.

## Runtime boundary

Docker is not available in the source-verification container, so live Docker execution must be performed on the target Docker Desktop host. The installer contains the exact target-host registry and readiness checks that were absent from 0.7.0.2.
