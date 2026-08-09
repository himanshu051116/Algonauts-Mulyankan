# Upgrade and rollback — Mulyankan 0.8.0

## Upgrade characteristics

- Source baseline: 0.7.0.3
- Database migrations: additive (`20260709_validation_pilot` followed by `20260712_model_lifecycle`)
- Existing proposal and evaluation data: preserved
- Existing object-storage and Redis volumes: preserved
- Model scoring behaviour: unchanged
- New features: expert-grounded validation studies, shadow-pilot comparison, and evidence-backed model lifecycle metadata

## Before upgrading

1. Keep the 0.7.0.3 source directory.
2. Copy its working `.env` into the 0.8.0 source directory.
3. Keep Docker Desktop running.
4. Do not delete the generated upgrade backup until validation and rollback checks pass.

## Upgrade

Run:

```powershell
.\scripts\windows\upgrade-expert-validation-0.8.0.ps1
```

The script validates Compose, starts infrastructure, creates a PostgreSQL backup, builds all application images, runs migrations and reference-data seeding, verifies the model registry, recreates application services, checks version/readiness and verifies the new validation tables.

## Rollback application code

The additive tables and columns do not interfere with 0.7.0.3 code. To roll back the application while retaining the 0.8.0 schema:

1. Stop the 0.8.0 application services.
2. Return to the preserved 0.7.0.3 source directory containing the same `.env` and Compose project name.
3. Rebuild/recreate backend, worker and frontend from 0.7.0.3.
4. Verify `/health` and `/health/ready`.

This is the preferred operational rollback because it preserves pilot records.

## Full database rollback

A full schema downgrade removes validation-study records and the new review metadata columns. Use it only after exporting any required pilot records and only with an approved backup/restore plan. The safest full rollback is restoration of the timestamped PostgreSQL backup created before migration.
