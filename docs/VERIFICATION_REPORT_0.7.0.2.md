# Mulyankan 0.7.0.2 Source Verification Report

**Release:** 0.7.0.2 — Evidence-Mapping and Prohibition-Parser Hotfix  
**Date:** 8 July 2026

## Live defect evidence

The 0.7.0.1 worker log showed that all governed-package documents were extracted and `evaluate_proposal` finished with status `completed`. The remaining defects were therefore interpretation defects rather than queue, extraction, persistence or migration failures.

The reproduced governed demo package exposed two issues:

1. `no foreign travel, and ...` was parsed as a positive prohibited item because generic label parsing ran before local-negation handling.
2. valid evidence under headings such as `Novelty and Technical Contribution`, `Technical Methodology`, `Work Packages and Deliverables`, `Risk Management`, and `Safety, Environmental and Ethical Compliance` was assigned to the wrong section or rejected as unclassified.

## Corrections verified

- Negated prohibited-item statements resolve to `none` before label parsing.
- Explicit positive declarations such as `Foreign Travel: included` still resolve to `yes` and fail closed.
- Governed proposal heading variants map to their intended evidence-contract sections.
- Keyword matching uses both left and right word boundaries, preventing substring inflation.
- Precise semantic equivalents improve evidence retrieval without changing evidence thresholds.
- `co-pi` alone no longer counts as women-researcher evidence.
- Industry relevance resolves from multiple concrete partner/deployment/technology-transfer signals when PDF table extraction reverses label/value order.

## Automated verification

- Backend tests: **193 passed**.
- Environment-dependent tests: **3 skipped**.
- Ruff: passed.
- Mypy: passed with no issues in 51 source files.
- Frontend ESLint: passed with zero warnings.
- TypeScript and Vite production build: passed.
- npm audit: 0 vulnerabilities.
- PostgreSQL Alembic offline rendering: passed through head `20260708_packages`.
- Compose and Docker build-context validation: passed.
- No new database migration.

Coverage instrumentation was not re-reported in this verification container because the coverage-enabled full suite exceeded the execution window. The complete non-instrumented suite passed in three deterministic batches, including all new regressions.

## Controlled demo replay

Using the six mandatory synthetic demo PDFs:

- deterministic hard-screening: eligible, no blocking rules;
- foreign travel: resolved as absent;
- industry relevance: resolved as demonstrated;
- advisory scoring status: released;
- advisory total: 33.5/100;
- evidence coverage: 0.295;
- released criteria: 14;
- uncalibrated reliability indicator: 0.334;
- abstention reasons: none.

The low advisory score is not upgraded or forced by this hotfix. Missing evidence for inclusivity, quantified ROI/economic ratio and other unsupported criteria remains unresolved and receives no marks.

## Compatibility

- Existing PostgreSQL, Redis and MinIO volumes remain unchanged.
- Existing 0.7.0 and 0.7.0.1 governed package manifests remain valid.
- Historical evaluations remain immutable for audit.
- A fresh evaluation is required to apply corrected extraction and evidence mapping.
