# Brochure-aligned advisory ML model — Mulyankan 0.6.0

## Scope

Mulyankan packages a reproducibly trainable NLP model for preliminary scoring of Ministry of Coal R&D proposals. The source brochure defines the rubric and eligibility policy, but it is not a labelled historical proposal dataset. The included model is therefore a **weak-supervision bootstrap model**, suitable for integration, evidence-control and shadow-pilot work—not for autonomous selection or claims of official accuracy.

## Artifact

- Model name: `moc-brochure-hybrid-ml-v2`
- Version: `2.0`
- Format: `portable-hashed-linear-v1`
- Artifact: `data/models/moc-brochure-hybrid-ml-v2/model.npz`
- Model card: `data/models/moc-brochure-hybrid-ml-v2/model_card.json`
- Metrics: `data/models/moc-brochure-hybrid-ml-v2/metrics.json`
- Compatible rubric: `data/rules/moc-st-100-mark-rubric-v2.yaml`

The artifact contains only numeric coefficient, intercept and class arrays. It is loaded using `allow_pickle=False`. This removes the arbitrary-code-execution risk associated with joblib/pickle model deserialization and improves portability across supported scikit-learn environments.

## Features and targets

The model creates a fixed 8,192-dimensional representation for each criterion:

- 4,096 stateless word-hash features;
- 4,096 stateless character-hash features.

Each of the 23 rubric criteria has a separate averaged SGD logistic classifier with four ordinal evidence levels. The predicted level distribution is converted to a criterion score, then constrained by retrieved evidence, evidence coverage, vocabulary coverage and information sufficiency.

## Safety controls

- deterministic hard-screening rules remain separate;
- criterion marks cannot exceed official maxima;
- evidence strength caps predicted levels;
- sparse and out-of-coverage documents cause abstention;
- keyword-stuffed text is regression-tested and must not receive a competitive score;
- missing, corrupt or hash-mismatched artifacts are rejected;
- the transparent contextual engine is retained only as a flagged fallback;
- all proposals proceed to authorized human review.

The exposed value is an **uncalibrated reliability indicator**, not statistical confidence or approval probability.

## Training data

The packaged bootstrap contains 1,200 proposal groups and 27,600 criterion examples generated from the brochure-derived weak-label specification. Grouped splits prevent variants of a synthetic proposal from appearing in both train and holdout sets.

These records do not represent real applicant behaviour, reviewer disagreement, institutional priorities or eventual project outcomes. Bootstrap metrics only test pipeline consistency.

## Expert retraining contract

`data/training/expert-labelled-record.schema.json` supports:

- immutable proposal/document identifiers and checksums;
- guideline and rubric versions;
- double-review and adjudicated criterion scores;
- evidence passages and page references;
- reviewer agreement metadata;
- final recommendation and decision outcome;
- time and organisation grouping for leakage-safe validation.

Expert datasets are supplied with repeated `--expert-dataset` arguments. Production promotion should require temporal/institutional holdout evaluation, calibration, subgroup testing, false-approval review, security approval and formal model-card sign-off.

## Monitoring after review

The application records model-versus-expert score deltas, absolute errors, recommendation disagreement, reviews after abstention and committee disagreement. These records create the operational foundation for calibration and drift analysis after genuine proposal volume is available.
