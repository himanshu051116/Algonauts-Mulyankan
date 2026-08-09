# Mulyankan 0.6.0 Critical Hardening and Residual-Risk Audit

## Executive conclusion

Mulyankan 0.6.0 consolidates the code-fixable root causes identified across the original source audit, the 0.4.0 rebuild, the 0.4.1 frontend reassessment, the 0.5.0 ML integration and the Windows/Docker run. The work does **not** claim that every listed symptom has been independently eliminated in production. Closely related symptoms were reduced to their underlying architectural causes and addressed at the authoritative boundary: database constraints, immutable proposal versions, server-controlled documents, queue state transitions, evidence-aware scoring, portable model loading, audit integrity and deterministic deployment configuration.

The result is a production-engineered **pilot decision-support system**, not an autonomous or institutionally validated proposal-selection system. The packaged ML model is genuinely trained, versioned and executable, but its current labels are brochure-derived weak supervision. Official accuracy, calibration, fairness and approval-risk claims require a real expert-adjudicated Coal S&T dataset and independent institutional validation.

## Root-cause disposition

| Root cause | 0.6.0 treatment | Residual status |
|---|---|---|
| Heuristic-only evaluation and unsafe artifact loading | Added 23 criterion-specific trained classifiers, evidence caps, abstention, artifact hash verification and a pickle-free compressed NumPy format loaded with `allow_pickle=False` | **Mitigated, not institutionally validated** |
| Keyword stuffing and unsupported scores | Criterion evidence levels cap predicted marks; weak or contradictory documents abstain; deterministic hard screening remains separate | **Fixed in code; real-world adversarial validation remains** |
| Unreliable model selection | Registry selection enforces scheme/rubric linkage, active status, effective time and artifact identity; deterministic fallback is explicit | **Fixed in code** |
| Mutable submitted content | Proposal versions carry title/content snapshots; evaluated revisions cannot be edited in place; new uploads create/supersede authoritative document state | **Fixed in code** |
| Ambiguous document authority | One active primary document per proposal version is enforced by database index and API logic; submission/evaluation require successful extraction | **Fixed in code** |
| Weak DOCX validation | Added package-structure, member-count, expanded-size, compression-ratio, macro/embedding/encryption and path checks; bounded table/image inventory is produced | **Materially hardened; external AV remains required** |
| Extraction corrections lacked governance | Added reviewer/admin correction APIs preserving original value, corrected value, reason, actor, timestamp and new content hash | **Fixed in code** |
| Queue failures corrupted proposal state | Enqueue failures roll back safely, preserve prior status, expose stable API errors and support controlled retry | **Fixed in code** |
| Processing failure presented as rejection | Worker now separates extraction/model failure, abstention, revision required and human-review states | **Fixed in code** |
| Reviewer/model disagreement was invisible | Added per-review and committee monitoring for score delta, absolute error, recommendation/decision disagreement and abstention review | **Fixed in code; drift thresholds need real data** |
| Database allowed invalid or duplicate records | Added proposal-version, primary-document, score/range/status and workflow constraints plus the existing reviewer/criterion uniqueness protections | **Fixed in code** |
| Mutable audit records and unsigned exports | PostgreSQL audit rows are append-only; audit and committee-decision exports use deterministic HMAC-SHA256 integrity envelopes | **Tamper-evident in deployment; not a legal digital signature** |
| Unsafe production defaults | Production startup now rejects weak JWT/audit keys, disabled malware scanning, HTTP public endpoints, wildcard/HTTP origins and unsafe credentials | **Fixed in code; deployment values still operator-owned** |
| Fragile Docker/Windows build | Pinned Node 22.16.0, deterministic `npm ci`, configurable host ports, corrected service paths, readiness dependencies and environment propagation | **Statically validated; live daemon validation pending** |
| Missing operational readiness | Readiness covers database, migrations/reference data, Redis, object storage, worker heartbeat, OCR, malware runtime and model artifact | **Fixed in code; live service proof pending** |
| Frontend/backend contract drift | Frontend consumes authoritative backend evaluation states, evidence and workflow status; browser fallback scoring is not authoritative | **Fixed in current release** |

## Evaluation and ML controls

The active model is `moc-brochure-hybrid-ml-v2` version `2.0`. It uses stateless word and character hashing with criterion-specific averaged SGD logistic classifiers. The serialized artifact contains numeric arrays and JSON metadata only. The loader rejects hash mismatch, malformed dimensions, unknown criterion layout and any artifact requiring pickle deserialization.

The model predicts 23 brochure-aligned criterion evidence levels. The scoring layer then applies rubric maxima, evidence sufficiency, negation and support checks. It exposes a reliability indicator and vocabulary/evidence diagnostics rather than claiming calibrated statistical confidence. Insufficient or incoherent text causes abstention and mandatory human review instead of a confident numeric decision.

Deterministic hard screening remains outside the ML model for duration, thrust-area fit, prohibited expenses, industry relevance and regulatory/safety compliance. This prevents a probabilistic text model from overriding explicit eligibility rules.

### Current model limitation

The included 1,200 bootstrap proposal groups and 27,600 criterion examples are synthetic weak-supervision records derived from the brochure. Holdout metrics confirm pipeline reproducibility against those generated labels only. They do not measure agreement with MoC/CMPDI experts, future outcomes, approval quality, subgroup fairness or calibration.

Before operational decision use, the model must be retrained and validated on double-reviewed, adjudicated historical proposals with proposal-level group splits, institution/time holdouts, calibration curves, false-approval analysis, subgroup analysis, reviewer agreement and drift baselines.

## Document and evidence controls

- Upload confirmation is bound server-side to the authenticated owner, upload session, proposal version, object key, filename, media type and measured object size.
- A proposal version has at most one active primary document.
- Submission and evaluation require an extracted primary document; late worker failure is no longer the normal validation path.
- Re-extraction replaces page/section/field state transactionally rather than duplicating records.
- PDF/DOCX/TXT processing is bounded by file size, page/member limits and decompression safety checks.
- OCR/page confidence and extraction metadata are persisted where the configured OCR runtime returns them.
- Reviewer field correction preserves original evidence and creates an audit record.
- Criterion results retain evidence passages and extraction context where available; exact OCR bounding-box quality still depends on the production OCR engine.

## Workflow and authorization controls

- Proposal, evaluation and document access use shared proposal-access checks rather than divergent router policies.
- Inactive/pending users can reach the account-state response needed by the frontend without receiving an applicant workspace.
- Roles, statuses, recommendations, criterion ranges and active-rubric membership are constrained in schemas and/or the database.
- Submitted/evaluated proposal versions are immutable. Revision creates a new version and preserves the prior snapshot.
- Evaluation re-run is blocked for withdrawn/finalized proposals and requires an authoritative extracted document.
- Abstention, revision required, human review, adjudication, committee review, approved and rejected are distinct states.
- Committee-decision export contains the proposal/version snapshot, model run, completed expert reviews and final decision in a signed integrity envelope.

## Deployment and release controls

- Node is pinned to 22.16.0 in the frontend image; the image uses `npm ci` from the lockfile and does not continue after a partial install.
- Host ports for PostgreSQL, Redis, MinIO API/console and frontend are configurable to avoid conflicts with old local containers.
- Compose uses Docker service names internally and validates required environment propagation.
- Production startup rejects unsafe authentication, audit, malware, CORS, storage and Supabase configuration.
- The release packager excludes `.env`, caches, virtual environments, `node_modules`, local databases, logs, prior releases and build output; it scans staged text for likely secrets and creates a per-file SHA-256 manifest plus archive checksum.

## Validation completed for this source state

- Backend: **162 passed, 3 skipped**.
- Backend statement coverage: **72.43%**, above the 70% release gate.
- Ruff: passed.
- Mypy: passed.
- Python bytecode compilation: passed.
- Frontend clean install, ESLint and production TypeScript/Vite build: passed.
- Frontend dependency audit: zero reported vulnerabilities at validation time.
- Alembic full offline migration-chain rendering: passed through `20260706_hardening`.
- Docker Compose/build-context static validation: passed.
- Packaged model training, hash verification, inference, weak-document abstention and corrupt-artifact rejection: passed.

## Items that remain external or partially validated

The following cannot be truthfully closed by source-code changes alone:

1. Live PostgreSQL, Redis, MinIO, Supabase, OCR, ClamAV and worker integration under the final deployment credentials.
2. Docker image build and full multi-container smoke test on a running Docker daemon.
3. ClamAV EICAR acceptance testing and signature-update monitoring in the target environment.
4. Browser E2E testing for real upload, extraction, correction, signed download, reviewer assignment, adjudication and committee sign-off.
5. Backup restoration, disaster-recovery and queue-recovery drills.
6. Production TLS, DNS, reverse-proxy, CORS, allowed-host and Vercel-to-backend verification.
7. Independent penetration testing and multi-role institutional UAT.
8. A real expert-labelled Coal S&T dataset and institution/time held-out validation.
9. Statistical calibration, bias/subgroup analysis, false-approval/false-rejection cost analysis, outcome validation and model-drift thresholds.
10. Institutional approval of the rubric, thresholds, eligibility rules, retention policy, reviewer policy and legal status of exports.
11. A legally recognized digital-signature workflow. HMAC envelopes prove integrity to holders of the secret key but are not public-key signatures or statutory sign-off.

## Recommended institutional acceptance sequence

1. Deploy to an isolated pilot environment with rotated credentials and private object storage.
2. Complete live Docker/service, EICAR, backup/restore and browser E2E acceptance tests.
3. Import a de-identified historical proposal corpus with two independent expert reviews and adjudication.
4. Freeze a time/institution holdout before model training.
5. Measure criterion MAE, rank correlation, calibration, abstention coverage, disagreement, false approvals and subgroup behavior.
6. Run the model in shadow mode; do not expose its recommendation to reviewers during the first blinded comparison phase.
7. Establish change control, drift thresholds, incident response and signed model/rubric approval records.
8. Permit advisory production use only after the competent authority approves the evidence.

## Final classification

Mulyankan 0.6.0 is a materially hardened, testable and traceable pilot platform with an actual trained advisory model. It is suitable for controlled demonstrations, shadow evaluation and expert-data collection. It is **not** yet scientifically or institutionally validated for autonomous approval or rejection, and the software deliberately keeps final authority with human reviewers and committees.
