# Upgrade and Rollback — Mulyankan 0.7.0

## Before upgrading

1. Keep the verified 0.6.3 source folder unchanged.
2. Copy the working `.env` into the new 0.7.0 source folder; never place it in a release archive.
3. Confirm Docker Desktop is running and `docker compose config --quiet` succeeds.
4. Create and verify a PostgreSQL custom-format backup before running the new migration.
5. Record the current Alembic revision and container image state.

Windows users may run:

```powershell
.\scripts\windows\upgrade-governed-packages-0.7.0.ps1
```

The script performs a pre-migration backup, builds the application, runs migration/seeding twice to verify idempotence, starts the stack and checks the 0.7.0 migration and package invariants.

## Expected migration

The database head after upgrade is `20260708_packages`. Existing non-draft versions are marked `legacy_single_document`. Draft and revision-required versions remain editable but must be completed and confirmed under the 0.7.0 package policy before submission.

The migration does not alter rubric versions, model artifacts, criterion predictions, evaluation totals, human reviews or final decisions.

## Post-upgrade checks

- `/health` reports version `0.7.0`.
- `/health/ready` reports the expected migration head and healthy critical dependencies.
- Exactly one active main proposal exists per governed version.
- No active version has more than one document for the same non-null requirement ID.
- A package cannot submit until it is complete, explicitly confirmed and hash-consistent.
- Replacing any package document clears confirmation.
- Existing 0.6.3 evaluations and reports remain readable.
- An incomplete demo remains not scored under the 0.6.3 safety gate.

## Application rollback before new 0.7.0 data is accepted

If the migration completed but no package has been confirmed and no new 0.7.0 submission has been accepted, stop the stack, restore the pre-upgrade database backup and restart the verified 0.6.3 source. Restoring the backup is safer than attempting to mix a downgraded schema with newer application state.

## Rollback after 0.7.0 package activity

Do not run an in-place downgrade after applicants have uploaded or confirmed package documents. Preserve the 0.7.0 database and object storage, take an additional backup and investigate the failure. A schema downgrade would discard requirement assignments, package manifests, confirmation attribution and hashes. Restore the pre-upgrade backup only when the loss of all post-upgrade activity is explicitly accepted by the responsible authority.

## Operational limitation

A source-only verification environment cannot prove Docker runtime health, external Redis/MinIO connectivity or production authentication. Those checks must be completed on the target host using the supplied upgrade script and the institution's actual configuration.
