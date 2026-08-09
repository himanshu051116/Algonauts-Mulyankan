# Mulyankan 0.7.0.2 Evidence-Mapping and Prohibition-Parser Hotfix

## Defects corrected

A current governed package completed extraction and evaluation, but the deterministic rule layer could misread prose such as `no foreign travel, and ...` as a positive foreign-travel declaration. The generic labelled-value extractor consumed punctuation or following prose as the field value, producing malformed output such as `Prohibited item present: , and`.

The evidence-contract layer also failed to recognise several valid, commonly used proposal headings such as `Novelty and Technical Contribution`, `Technical Methodology`, `Work Packages and Deliverables`, `Risk Management`, and `Safety, Environmental and Ethical Compliance`. Valid evidence was therefore assigned to the previous section or rejected as unclassified, causing avoidable abstention.

## Corrections

- Evaluate local negative statements before any label-style parsing for prohibited items.
- Treat a prohibited phrase as a labelled declaration only when an explicit separator or declaration verb is present.
- Preserve fail-closed handling for explicit positive declarations such as `Foreign Travel: included`.
- Recognise governed-proposal heading variants without using fuzzy body-text matching.
- Collect every exact heading occurrence rather than only the first occurrence for each alias.
- Add precise semantic equivalents for novelty, technical clarity, work packages, adoption, strategic fit, phased funding, dependencies, compliance, collaboration and indigenisation evidence.
- Resolve industry relevance from multiple concrete partner, deployment, field-demonstration or technology-transfer signals when table extraction reverses label/value order.
- Remove `co-pi` as a women-researcher evidence term; gender participation is not inferred from a role title.
- Keep all evidence-contract minimum-hit requirements, score-release thresholds and reliability thresholds unchanged.

## Compatibility

- No database migration.
- No database schema change.
- No API request or response removal.
- Existing governed-package manifests and uploaded documents remain valid.
- Historical failed and abstained runs remain unchanged for audit.
- A new evaluation must be created after deploying the hotfix to apply corrected extraction and evidence mapping.
