# Mulyankan rebuild changelog

## 0.8.0 maintenance rectification — password recovery and release integrity

- added a complete Supabase forgot-password request and password-update flow at `/auth/reset-password`
- prevents account enumeration in reset-request success messages and forces fresh sign-in after a password change
- removed the duplicate stale readiness migration assignment and strengthened the single-head regression test
- made validation-pilot schema verification derive the current Alembic head
- changed the example Compose namespace from `mulyankan-061` to `mulyankan-080`
- removed and permanently excludes obsolete `original-broken` source copies from controlled releases
- normalized Python source encoding and updated deployment, verification and rollback documentation
- passed 238 backend tests, 70.53% coverage, frontend lint/build, npm audit, migration rendering, Compose validation and controlled release verification

## 0.8.0 — expert-grounded validation and shadow pilot

- added additive validation-study, case, consensus, comparison and metric-snapshot tables
- froze scheme, rubric, model, protocol and annotation-rulebook identity per study
- added proposal-group leakage protection and development/internal/external/shadow partitions
- added double-blind reviewer assignments with model-output, peer-review, machine-extraction, adjudication and committee-outcome suppression until submission
- added criterion-complete expert annotation using the existing frozen rubric
- added auditable pre-freeze case exclusion and cancellation of pending assignments
- added material expert-disagreement flags and adjudication recommendations before training-label approval
- added expert consensus, reviewer-agreement, total/criterion error, correlation, release/withhold and calibration-proxy metrics
- added observational readiness warnings that never claim scientific validation
- added frozen JSONL export for approved analysis and future training workflows
- added validation-lab and blind-review frontend workspaces
- added a compatibility-safe Windows upgrade script with pre-migration backup, core-record count preservation and live schema/model verification
- preserved all existing proposal, document, evaluation, review and committee workflows

### Scientific limitation

This release implements the infrastructure for expert-grounded validation. It does not convert the bootstrap-trained advisory model into an institutionally validated model. Real qualified reviewers, approved labels, adequate samples, external testing, adjudication and institutional sign-off remain required.

## 0.7.0.3 — Registry consistency and fresh-failure reporting

- Unified active model/rubric selection between readiness and workers.
- Added cross-image evaluator hash verification.
- Refreshes model registry after hotfix image builds.
- Preserves exact model-registry failure details in audit events.
- Fresh preflight failures no longer appear as legacy-unverified reports.
- Added target-host installer and registry verification module.

# Mulyankan Changelog

## 0.7.0.2 — Evidence Mapping and Prohibition Parser Hotfix

- Evaluate negated prohibited-item statements before label-style parsing, preventing “no foreign travel” prose from becoming a false deterministic failure.
- Require an explicit separator or declaration verb before treating a prohibited phrase as a labelled positive value.
- Recognise common governed-proposal headings for novelty, methodology, work packages, schedule, infrastructure, team, budget, risk, compliance, impact, TRL and deployment sections.
- Add precise evidence synonyms for the brochure-aligned rubric while preserving all evidence-contract thresholds and abstention thresholds.
- Remove the generic `co-pi` token from women-researcher evidence so gender participation is never inferred from role title alone.
- No database migration or API contract change.

## 0.7.0 — governed submission packages

- Replaced the implicit single-file submission flow with policy-defined multi-document package slots.
- Added server-bound requirement IDs, role/type/size validation and one-active-document-per-slot enforcement.
- Added applicant role confirmation, canonical package manifests and deterministic SHA-256 package identities.
- Kept the main proposal authoritative while allowing contract-permitted supporting evidence with document-level provenance.
- Prevented supporting files from superseding the proposal body or satisfying unrelated criteria.
- Invalidated package confirmation whenever the active file set changes.
- Added a forward-only Alembic migration while preserving historical runs as `legacy_single_document`.
- Added a governed package frontend, package readiness diagnostics, compatibility-safe TXT main-proposal API support and direct regression tests.
- Preserved all 0.6.3 scoring-safety thresholds, model artifacts and human decision controls.

## 0.6.3 — evidence-gated scoring safety

- Added transparent main-document and Coal S&T scheme gates.
- Added versioned criterion evidence contracts covering all 23 MOC-ST criteria.
- Removed full-document ML fallback for criteria without acceptable evidence.
- Enforced null criterion scores when evidence is unresolved and null official totals on abstention.
- Added explicit criterion/scoring statuses, gate persistence, document-role metadata and evidence-verification metadata.
- Added fail-closed rules-only fallback and a new inference registry policy version without mutating the statistical artifact.
- Added forward-only scoring-safety migration with conservative `legacy_unverified` treatment for historical outputs.
- Updated frontend reporting for `NOT SCORED`, gate failures and unresolved criteria.
- Added adversarial résumé, brochure, role and keyword-stuffing regression tests.

## 0.6.0 — critical hardening and consolidated release

- replaced the pickle/joblib ML artifact with a portable compressed NumPy linear model loaded with `allow_pickle=False`;
- added immutable title snapshots, authoritative primary-document rules and mandatory revision branching after evaluation;
- added scrutiny-officer correction of extracted fields with attribution, reasons, content re-hashing and audit events;
- strengthened DOCX package validation and added table/image inventories;
- added model-versus-expert and committee disagreement monitoring;
- added append-only PostgreSQL audit protection and HMAC-signed controlled exports;
- strengthened production HTTPS, secret, malware and metrics validation;
- added configurable loopback Docker host ports and deterministic Node 22.16 frontend builds;
- added rerun preflight checks, safe queue-state recovery and stable external error messages;
- expanded release regression tests and residual-risk documentation.

# Mulyankan rebuild changelog

## 0.5.0 — brochure-aligned trained ML model

- normalised the uploaded MoC R&D guidance brochure into a versioned six-category, 23-criterion, 100-mark rubric
- added versioned hard-screening rules for duration, thrust area, prohibited budget items, industry relevance and compliance readiness
- implemented 23 criterion-specific word/character TF-IDF ordinal classifiers with reproducible SGD training
- generated a 1,200-record brochure-derived weak-supervision bootstrap dataset and packaged a serialised model artifact, model card and metrics
- added evidence-controlled blending, document-quality checks, vocabulary coverage, confidence, top features and abstention
- registered and integrity-hashed the trained model with a deterministic fallback
- integrated trained inference into the ARQ worker, persisted criterion confidence and warnings, and exposed model provenance in the frontend report
- added expert-labelled JSON Schema and retraining support for one or more adjudicated JSONL datasets
- aligned preliminary result bands to the brochure while preserving mandatory human review and committee authority
- added regression tests for artifact integrity, trained-model dispatch, score separation and hard-screening behavior

### Scientific limitation

The packaged artifact is a real trained model, but its current labels are brochure-derived weak supervision. Its hold-out metrics measure recovery of those generated labels, not accuracy against MoC/CMPDI decisions. Institutional use requires expert-adjudicated historical proposals, leakage-safe held-out evaluation, calibration, bias/error analysis and a shadow pilot.

## 0.4.1 — frontend reassessment and usability hardening

- corrected workflow-status presentation so processing errors are not shown as proposal rejections
- added distinct pending, automated evaluation, human review, adjudication, committee review, withdrawal and error states
- fixed portfolio distribution math for proposals without final decisions
- redesigned proposal submission with extension and size validation, drag-and-drop, file removal, counters and live readiness guidance
- prevented incompatible files from surviving PDF/DOCX source changes
- added visible refresh state, last-updated context and visibility-aware polling without overlapping requests
- added search clearing, status filtering and date/score sorting to submission history
- improved mobile history rows so status and score remain visible
- added keyboard-accessible mobile navigation, skip link, focus styles and reduced-motion support
- added Escape handling, focus restoration and scroll locking for report dialogs
- added a runtime error boundary and a clear configuration screen instead of blank-page failures when Supabase variables are missing
- removed runtime Google Fonts dependency and strengthened typography, spacing, contrast and responsive layout

## 0.4.0 — deployment and release-integrity bug fixes

- fixed the frontend Docker build referencing a missing `public/` directory
- corrected Vite environment loading so the repository `.env` is used locally
- fixed the migration container module path and startup ordering
- propagated documented Supabase, JWT, file-size, logging and telemetry settings into Python containers
- deferred MinIO init credentials to container runtime variables instead of embedding them in the rendered command
- blocked the workspace when server-side account verification fails
- prevented stale manifests and previous release output from contaminating generated source archives
- strengthened Compose validation and added a Docker builder-stage CI gate

## 0.4.0 — phased reliability rebuild

### Security

- fixed cross-proposal evaluation authorization
- centralized proposal access checks
- protected private document downloads with short-lived signed URLs
- production fail-fast configuration checks
- security headers, host validation and rate limiting
- optional fail-closed ClamAV scanning
- tamper-evident, append-only audit records

### Evaluation and evidence

- upgraded extraction with OCR/page metadata and safer DOCX handling
- corrected duration and percentage extraction
- replaced permanently unimplemented blockers with executable review logic
- added contextual evidence scoring and keyword-stuffing resistance
- added prior-proposal similarity records
- stored reproducibility versions and checksums

### Workflow

- immutable proposal revisions
- version-bound technical and financial reviews
- conflict management, adjudication and committee decisions
- controlled proposal status transitions
- frontend now renders the authoritative backend evaluation and governance data

### Operations

- readiness checks and worker heartbeat
- Prometheus metrics
- CI and local quality gates
- safer Docker/Vercel configuration
- comprehensive secret and artifact exclusion rules
- secret-scanned release packaging with manifest and SHA-256 checksum
- clean-extraction validation so tests do not depend on local cache directories
- upgraded the frontend toolchain to Vite 8 and removed the deprecated charting dependency in favour of lightweight native charts

### Scientific limitation

The active scoring engine remains an advisory deterministic baseline. A validated ML model requires real expert-labelled Coal S&T proposal data and institutional validation.

## 0.6.3 readiness hotfix

- Updated the readiness migration check to require `20260708_scoring_safety`, matching the actual Alembic head.
- Added a regression test that derives the Alembic head and verifies the readiness constant.
- Updated the Windows upgrade script to print backend logs and container state when startup fails.
