# Mulyankan 0.8.0 — Expert-Grounded Validation and Shadow Pilot

## Purpose

Version 0.8.0 adds a controlled framework for comparing Mulyankan's advisory output with independent expert reviews. It does **not** claim that the current model is scientifically validated or approved for official decision-making.

## Core safeguards

- Each validation study freezes a scheme, rubric and registered model version.
- Each proposal group can appear only once in a study, preventing revised versions from crossing partitions.
- A shadow case requires at least two completed independent expert reviews.
- Reviewers remain blind to model results, peer reviews, machine-extracted fields, adjudications and committee outcomes until their immutable submission is complete.
- Shadow-pilot records do not change proposal workflow state or competent-authority decisions.
- Metrics are partitioned and labelled observational; material expert disagreement is flagged for institutional adjudication before training-label approval.
- Exports are allowed only after a study is frozen, completed or archived.

## Workflow

1. An authorised validation manager creates a study.
2. The active scheme, rubric and model are frozen into the study record.
3. Completed historical or shadow proposal runs are assigned to controlled partitions.
4. Qualified reviewers receive blind assignments and score every frozen rubric criterion.
5. Mulyankan computes expert consensus and reviewer-agreement measurements.
6. Model-versus-expert comparisons are stored without modifying the proposal decision.
7. Observational metrics are computed for all, development, internal-test, external-test and shadow partitions.
8. Material reviewer disagreement is flagged and preserved in the consensus record.
9. A versioned JSONL dataset can be exported for approved analysis after the study is frozen.

## Metrics included

- total-score MAE, RMSE and bias;
- Pearson and Spearman score correlation;
- within-5 and within-10 point rates;
- model release and abstention/withhold rates;
- recommendation agreement when an explicit study policy is configured;
- expert pairwise MAE, score dispersion and material-disagreement rate;
- criterion-level MAE;
- a confidence-calibration proxy, explicitly labelled non-certifying.

## Scientific limitations

The framework provides traceable data collection and analysis. A credible model-validation claim still requires an approved annotation protocol, qualified domain experts, adequate sample sizes, a leakage-safe external test set, adjudication rules, calibration analysis, failure-mode review and independent institutional sign-off.

## Roles

- Administrators, ML engineers and scrutiny officers manage studies and cases.
- Auditors, adjudicators and committee-secretariat users can inspect study summaries.
- Technical and financial reviewers complete blind annotation assignments.
- Only authorised export roles can download frozen study records.

## Compatibility

The database change is additive. Existing proposals, documents, model runs, scores, reviews and audit records are preserved. Existing review and evaluation APIs remain available. The shadow-pilot functionality is isolated under `/api/v1/validation` and dedicated frontend views.


## Blindness boundary

While a reviewer has a pending blind shadow assignment, the normal evaluation report, peer-review results, machine-extracted fields, adjudications, committee outcomes and proposal outcome status are hidden. Source proposal documents remain available because experts must cite the original pages used for each criterion.

## Case exclusion

A validation manager may exclude a case only while the study is draft or active, must provide an auditable protocol reason, and cannot exclude a case after comparison. Freezing the study prevents further case inclusion or exclusion.
