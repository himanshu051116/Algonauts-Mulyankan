# Mulyankan 0.7.0.1 Evaluation Persistence Hotfix

## Defect corrected

A newly confirmed governed submission package could complete extraction and scoring in memory but fail while persisting the evaluation payload. The payload included `package_confirmed_at` as a Python `datetime`, while PostgreSQL JSONB requires a JSON-serializable value. The worker therefore marked the run failed and the report could incorrectly fall back to a legacy-unverified document-gate label.

## Corrections

- Serialize package confirmation timestamps as ISO 8601 strings before JSONB persistence.
- Log unexpected worker exceptions with proposal and scheme context.
- Persist the bounded exception message in internal failure details.
- Represent failed current evaluations as `evaluation_failed`, not `legacy_unverified`.
- Add regression coverage for a confirmed package with a timezone-aware confirmation timestamp.

## Compatibility

- No database migration.
- No schema or API contract removal.
- Existing 0.7.0 package manifests and uploaded documents remain valid.
- The failed evaluation can be rerun after deploying the hotfix; no re-upload is required.
