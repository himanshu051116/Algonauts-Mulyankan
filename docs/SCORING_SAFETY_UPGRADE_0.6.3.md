# Mulyankan 0.6.3 — Evidence-Gated Scoring Safety Upgrade

## Release scope

Mulyankan 0.6.3 is the first phase of the accuracy architecture upgrade. It does **not** claim expert-validated prediction accuracy and does not replace institutional review. It fixes the highest-risk behaviour in 0.6.1: a criterion could receive a capped positive score even when no acceptable criterion evidence existed, and an abstained evaluation could still expose an official-looking numeric total.

The statistical artifact remains the packaged brochure-derived model version `2.0`. The registered inference policy is now `2.1` because evidence selection, release rules and fail-closed behaviour changed. Existing model artifacts are not silently overwritten.

## Non-negotiable safety invariants

1. A document that fails the main-document or scheme gate is not scored.
2. A supporting document cannot initiate proposal scoring.
3. A criterion without accepted evidence has `awarded_score = null`.
4. An unreleased criterion cannot contribute to an official total.
5. An abstained evaluation has `total_score = null`.
6. A model or artifact failure produces rules-only human-review output, not a substitute official score.
7. Historical runs created under the older evidence policy are marked `legacy_unverified`; they are not silently certified as evidence-grounded.

## New evaluation stages

### 1. Document gate

The worker evaluates the authoritative main document before rule or ML scoring. The transparent gate combines:

- declared document role;
- proposal structure coverage;
- Coal S&T scheme relevance;
- résumé/CV indicators;
- brochure/reference indicators;
- extraction sufficiency.

It returns one of:

- `accepted`;
- `invalid_document`;
- `wrong_scheme`;
- `insufficient_extraction`;
- `role_disallowed`;
- `manual_review`.

This is a conservative deterministic gate for the pilot. Thresholds must later be calibrated on expert-labelled proposal packages.

### 2. Criterion evidence contracts

`data/evidence-contracts/moc-st-evidence-contracts-v1.yaml` defines the document roles, sections and evidence expectations permitted for all 23 MOC-ST criteria. The same contract drives retrieval filtering, scoring and regression tests.

Examples:

- PI/team CVs can support team-track-record criteria.
- Budget annexures can support financial criteria.
- CVs and reference brochures cannot support project novelty, work plan, safety impact or strategic fit.

### 3. Evidence-gated inference

The trained model is invoked only for criteria that have contract-accepted evidence. The previous fallback to full-document text for evidence-empty criteria has been removed.

Criterion states include:

- `supported`;
- `partially_supported`;
- `contradicted`;
- `unresolved`;
- `not_applicable`;
- `extraction_uncertain`;
- `role_disallowed`;
- `legacy_unverified`.

Only released, evidence-backed criteria can contribute to the official total.

### 4. Fail-closed fallback

The deterministic contextual engine is registered as `contextual-rule-heuristic-v3`. It preserves rule findings and evidence organisation when the trained artifact is unavailable, but it returns:

- `scoring_status = rules_only`;
- `total_score = null`;
- mandatory human review.

It is not presented as an equivalent replacement ML score.

## Database migration

Revision: `20260708_scoring_safety`

The migration adds:

- document role and role-classification metadata;
- model-run diagnostic score, scoring status and gate result;
- criterion status, release flag and evidence count;
- evidence document role and verification status;
- supporting constraints and indexes.

Historical policy:

- older completed runs become `legacy_unverified`;
- their previous total is retained as `diagnostic_score`;
- their official `total_score` is cleared while 0.6.3 is active;
- historical criterion values remain preserved in the database for audit and rollback, but are marked unreleased and are sanitised by the public evaluation API;
- older criterion predictions are never promoted to verified evidence.

This is deliberately conservative: old keyword evidence cannot be retroactively certified by a new policy, while non-destructive history is retained for traceability.

## Frontend changes

The evaluation report now:

- displays `NOT SCORED` instead of coercing null to zero;
- shows document-gate findings;
- distinguishes released and unresolved criteria;
- does not display an official total for abstained evaluations;
- keeps diagnostic values away from ordinary applicant presentation.

The existing administrator user-management frontend and MinIO CSP correction are preserved.

## What this release does not solve

0.6.3 does not yet provide:

- multi-file submission packages with applicant-confirmed document roles;
- layout-aware table/form extraction;
- semantic cross-encoder reranking;
- independent NLI support/contradiction verification;
- expert-labelled ordinal criterion models;
- institution/time-held-out accuracy estimates;
- calibrated confidence or autonomous decision authority.

Those belong to the 0.7–0.9 roadmap. This release intentionally prioritises fail-closed scoring safety before model expansion.
