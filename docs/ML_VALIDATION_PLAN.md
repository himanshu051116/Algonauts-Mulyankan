# ML validation plan for Mulyankan

## Current 0.6.0 status

Mulyankan now contains a reproducibly trained bootstrap model and a complete model-registry/inference path. Its current labels are brochure-derived weak supervision, so the artifact is suitable for integration testing, evidence-control development and shadow-pilot preparation only. It has not passed the institutional gates below.

The next training dataset must follow `data/training/expert-labelled-record.schema.json` and should be exported only under an approved legal, privacy and information-security process.

## Non-negotiable rule

Do not train or claim an accurate proposal-scoring model from synthetic proposals alone. Synthetic data is useful for software tests, not for proving selection accuracy.

## Dataset unit

Each record must bind:

- immutable proposal version and document checksum
- scheme, guideline and rubric versions
- page/section evidence spans
- eligibility outcomes and clarification states
- criterion scores from at least two qualified experts
- adjudicated score and rationale
- final institutional decision and decision date
- reviewer role, confidence and conflict declaration
- proposal institution and year for leakage-safe splitting

Personally identifiable and commercially sensitive content must be minimized, access-controlled and governed by a documented lawful basis.

## Splits

Use time-based and institution-held-out test sets. Keep all versions of the same proposal in one split. Never use a simple random paragraph split.

## Required metrics

- criterion MAE and quadratic weighted kappa
- rank correlation and calibration error
- eligibility precision/recall by rule
- evidence retrieval recall and reviewer-supported precision
- abstention coverage versus error
- false-approval and false-rejection rates
- performance by proposal type, institution size, language and OCR status
- inter-reviewer and model-reviewer agreement

## Gates

1. Annotation rulebook approved by domain experts.
2. Double-label agreement reaches the approved threshold.
3. Baseline and retrieval models are reproducible from versioned data.
4. Calibration and held-out error targets are met.
5. Bias and failure-mode review is passed.
6. Shadow pilot shows no unacceptable harm or workflow degradation.
7. Independent technical and institutional sign-off is obtained.
8. Model remains advisory with an abstention route and human override.

## Model registry requirements

Every released model must record the dataset version, code commit, artifact hash, training configuration, metrics, rubric compatibility, effective date, owner, approval record and rollback target.
