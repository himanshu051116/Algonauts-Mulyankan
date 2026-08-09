# Mulyankan Backend

## Administrator Bootstrap

The first administrator is created with an explicit local command. It is not exposed through a public API and does not run automatically.

Set at least one of these environment values before running the command:

```powershell
$env:BOOTSTRAP_ADMIN_UID = "<supabase-user-id>"
$env:BOOTSTRAP_ADMIN_EMAIL = "administrator@organisation.gov.in"
python -m backend.scripts.bootstrap_admin
```

For Supabase Authentication, prefer setting both values so the local `users.id` matches the Supabase JWT `sub` claim. The command is idempotent, refuses unsafe placeholder values, activates and verifies the selected user, assigns the `administrator` role, and writes an audit event.

## Common Commands

```powershell
# Apply database migrations
alembic -c migrations/alembic.ini upgrade head

# Seed schemes, rules, rubrics, and model versions
python -m backend.scripts.seed_data

# Bootstrap the initial administrator
python -m backend.scripts.bootstrap_admin

# Start the API locally
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Start the background worker locally
arq app.worker.WorkerSettings

# Run backend tests
python -m pytest backend/tests -vv -rs
```
