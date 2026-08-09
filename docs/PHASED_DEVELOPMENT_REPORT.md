# Mulyankan phased development report

## Phase 1 — Security and compatibility stabilization

Completed:

- centralized least-privilege proposal/evaluation access policy
- pending-user status endpoint that does not bypass active-user protection
- production configuration fail-fast checks
- current backend evaluation mapped into the frontend report
- safe role and administrator transition validation
- removal of the vulnerable unused PDF-generation dependency
- clean Python type and lint gates

## Phase 2 — Extraction, scoring and data integrity

Completed:

- immutable numbered proposal versions and stored executive summaries
- version-bound uploads and evaluations
- page-aware PDF extraction and Hindi/English OCR fallback
- safer DOCX package validation
- duration extraction separated from milestone ranges
- financial percentage extraction
- executable conditional and duplicate checks
- contextual evidence scoring and keyword-stuffing protection
- prior-project similarity records
- database uniqueness, range and integrity constraints
- exact model/rubric/guideline/extraction/checksum metadata per run

## Phase 3 — Institutional review workflow

Completed:

- review assignments bound to exact proposal versions
- separate technical and financial reviewer roles
- criterion completeness, bounds and total validation
- conflict declaration and authorized resolution
- adjudication after independent reviews
- committee decision with controlled status transitions
- version-specific governance history in the frontend

## Phase 4 — Operations and release hardening

Completed:

- request IDs and security response headers
- Redis-backed rate limiting with bounded local degraded mode
- ClamAV fail-closed integration when enabled
- short-lived, authorized private document-download URLs
- database, migration, reference-data, Redis, storage and worker readiness checks
- worker heartbeat
- secured Prometheus metrics
- tamper-evident audit hash chain and PostgreSQL append-only triggers
- true audit pagination totals and chain-verification endpoint
- production Docker and Vercel security configuration
- CI quality gates and local release-validation scripts
- release ignore rules that exclude secrets, caches, dependencies, logs and databases
- secret-scanned source packaging with per-file manifest and archive checksum
- clean-extraction regression validation
- current Vite 8 frontend build with dependency audit free of known npm vulnerabilities
- native dashboard/report charts replacing the deprecated Recharts 2 dependency

## External items not solvable from source code alone

- rotate credentials in Supabase, PostgreSQL, MinIO/S3 and Vercel
- configure real production domains and secrets
- obtain lawful historical proposal data and expert labels
- perform independent institutional validation and user-acceptance testing
- establish backup retention, incident response and operating ownership

## Product classification after the rebuild

The repository is a production-engineered **pilot decision-support platform**. It is suitable for controlled workflow pilots and expert data collection. It must not be represented as an autonomous or scientifically validated proposal-selection model until the validation gates are completed.
