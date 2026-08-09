# Production deployment guide

## Recommended topology

- Frontend: Vercel or the included Nginx container
- FastAPI backend and ARQ worker: a persistent container platform
- PostgreSQL: managed PostgreSQL with backups and point-in-time recovery
- Redis: managed Redis with authentication and persistence
- Documents: private S3-compatible bucket
- Authentication: Supabase Auth

Vercel hosts only the React frontend. Set `VITE_API_URL` to the separately deployed FastAPI base URL.

## Mandatory secret handling

Do not paste account passwords, service-role keys, database passwords or Vercel tokens into chat or commit them to Git. Rotate any value previously included in a ZIP. Configure secrets through the hosting provider's encrypted environment settings.

## Production environment requirements

- `ENVIRONMENT=production`
- `AUTH_ALLOW_LOCAL_JWT=false`
- explicit HTTPS `CORS_ORIGINS`
- explicit API `ALLOWED_HOSTS`
- non-default PostgreSQL and storage credentials
- Supabase URL, issuer and JWKS configuration
- `METRICS_TOKEN` when metrics are enabled
- private storage bucket
- Redis reachable by both API and worker
- current Alembic migration applied
- seeded active MOC-ST rubric and model metadata

Production startup intentionally fails if unsafe defaults remain.

## Supabase

1. Create or select the Supabase project.
2. Enable the required authentication provider(s).
3. Add the exact frontend callback URLs to Auth redirect URLs: `https://your-frontend.example/auth/callback` and `https://your-frontend.example/auth/reset-password`.
4. Set the Supabase Site URL to the frontend origin. Password-recovery emails must redirect to `/auth/reset-password`.
5. Put only the public project URL and publishable/anon key in Vercel.
6. Put backend-only secrets in the backend host, never in Vercel frontend variables.
7. Create the first user, copy its user UUID, and run the bootstrap administrator procedure.
8. Test sign-up confirmation and password recovery from the deployed origin before admitting pilot users.

## Vercel

Set:

- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_PUBLISHABLE_KEY`
- `VITE_PUBLIC_APP_URL`
- `VITE_API_URL`

The included `vercel.json` adds SPA routing and security headers.

## Backend rollout order

1. Provision PostgreSQL, Redis and private object storage.
2. Set production environment variables.
3. Run `alembic upgrade head`.
4. Run `python -m backend.scripts.seed_data`.
5. Initialize the private storage bucket.
6. Start the ARQ worker and confirm its Redis heartbeat.
7. Start FastAPI.
8. Verify `/health/ready` returns HTTP 200.
9. Configure the monitoring system to scrape `/metrics` with its bearer token.
10. Deploy the frontend and run an end-to-end pilot submission.

## Malware scanning

The backend image includes ClamAV. Update its signature database as part of image/runtime operations. First verify clean and EICAR test files in a non-production environment, then set `MALWARE_SCAN_ENABLED=true`. Enabled scanning is fail closed.

## Migration preflight

The integrity migration refuses to silently delete duplicate or orphaned records. Back up the database and resolve any reported duplicates before retrying. PostgreSQL append-only triggers prevent updates and deletion of audit/security events after the migration.

## Acceptance checks

- applicant cannot read another applicant's proposal
- unassigned reviewer cannot access documents or evaluations
- reviewer sees only assigned versions
- pending user cannot access active workflows
- uploaded PDF/DOCX checksum and extraction evidence are recorded
- two independent review paths complete
- conflict and adjudication paths work
- committee decision changes status only through allowed transitions
- audit-chain verification reports valid
- backup restore has been tested

## Release packaging

Run the full quality gate before packaging. Then use:

```bash
python scripts/quality/create-release.py --output-dir release
```

Distribute the generated `mulyankan-<version>-source.zip` together with its `.sha256` file. The packaging command excludes local `.env` files, credentials, Git metadata, dependency folders, caches, logs, local databases and generated frontend output. It also scans staged text files for common private-key and token formats.
