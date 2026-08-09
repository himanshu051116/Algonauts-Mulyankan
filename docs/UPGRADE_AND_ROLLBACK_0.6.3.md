# Upgrade and rollback guide — Mulyankan 0.6.1 to 0.6.3

## Safety rule

Install 0.6.3 in a **new source folder**. Keep the working 0.6.1 folder unchanged until all checks pass. Copy only the existing `.env` into the new folder. Never copy database volume files manually.

The `.env` must retain the same `COMPOSE_PROJECT_NAME` if the upgraded source is intended to use the existing PostgreSQL, Redis and MinIO volumes.

## Before upgrade

1. Confirm 0.6.1 is healthy.
2. Record `docker compose ps -a`.
3. Back up PostgreSQL using a custom-format dump.
4. Preserve the existing source folder.
5. Preserve `.env` separately and securely.
6. Do not delete Docker volumes.

The included `scripts/windows/upgrade-scoring-safety-0.6.3.ps1` performs the backup, build, migration-twice check, startup and safety queries. The frontend Nginx CSP is rendered at container start from `STORAGE_PUBLIC_ENDPOINT`, so existing 9100 deployments and fresh 9000 deployments remain compatible.

## Upgrade sequence

From the new 0.6.3 source folder:

```powershell
& ".\scripts\windows\upgrade-scoring-safety-0.6.3.ps1"
```

The script:

1. validates Docker and Compose;
2. creates a PostgreSQL custom-format backup;
3. copies `.env` and Compose configuration into a protected local backup folder;
4. validates Compose configuration;
5. builds migration, backend, worker and frontend images;
6. runs migrations and seed once;
7. runs migrations and seed a second time to prove idempotency;
8. starts the complete stack;
9. waits for backend readiness and frontend health;
10. verifies migration head and scoring-safety invariants.

## Required post-upgrade checks

- `/health` reports version `0.6.3`.
- `/health/ready` reports all critical checks as `ok`.
- migration container exits with code 0.
- backend, worker and frontend are healthy.
- a standalone résumé produces no official total or criterion score.
- a strong Coal S&T proposal can produce released evidence-backed criteria.
- an artifact failure results in rules-only mode.
- the live CSP still allows the configured public MinIO endpoint.

## Rollback

The 0.6.3 downgrade restores legacy model-run totals from `diagnostic_score` before removing the new safety columns. Historical criterion values are preserved non-destructively throughout the upgrade. Even so, a complete PostgreSQL backup remains mandatory because restoring the pre-upgrade dump is the safest rollback path for a real deployment.

For the safest complete rollback:

1. stop the upgraded stack;
2. restore the pre-upgrade PostgreSQL custom-format dump;
3. return to the untouched 0.6.1 source folder;
4. start 0.6.1 with the same `.env` and Compose project name;
5. verify health and historical evaluations.

Example database restoration (replace the path):

```powershell
docker compose stop backend worker frontend migration
docker compose cp ".\backups\upgrade-0.6.3-<timestamp>\postgres-pre-0.6.3.dump" postgres:/tmp/postgres-pre-0.6.3.dump
docker compose exec -T postgres sh -lc 'dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB" && pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner /tmp/postgres-pre-0.6.3.dump'
```

Review the target database and backup path before executing any destructive restoration command.
