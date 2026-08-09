# Mulyankan 0.4.0 final release validation

## Validation scope

The release candidate was generated from the rebuilt repository using `scripts/quality/create-release.py`, extracted into a new empty directory, and validated without copying local dependencies, caches, databases, environment files or build output.

## Passed gates

- Python bytecode compilation for the API, worker, scripts and release utilities
- Ruff linting for application code, migrations, tests and quality utilities
- Mypy checking for the backend application
- 136 backend tests passed; 3 live-service tests were skipped because Redis/object-storage services were not running in the validation container
- backend coverage: 72.19%, above the enforced 70% threshold
- complete Alembic PostgreSQL migration chain rendered successfully in offline SQL mode
- Docker Compose YAML, runtime environment propagation, migration command, and Docker build-context sources validated
- clean `npm ci` installation from `package-lock.json`
- TypeScript compilation and ESLint passed
- Vite 8 production build passed
- release-manifest regeneration, output-directory exclusion and `.env.example` secret scanning regression tests passed
- complete npm dependency audit reported zero known vulnerabilities
- release ZIP checksum verified
- packaged source contains no `.env`, Git metadata, local databases, logs, dependency directories, caches, Vercel metadata or generated frontend output
- staged source passed common private-key, JWT, Supabase secret-key, OpenAI-key and Vercel-token pattern scans

## Release classification

Mulyankan 0.4.0 is a production-engineered pilot decision-support platform. Its workflow, security controls, deterministic evidence-grounded baseline, reviewer governance and release process are suitable for controlled institutional pilots and expert-labelled dataset collection.

It is not an independently validated autonomous proposal-selection model. Official decisions must remain with authorized human reviewers and committees until the validation plan is completed with real historical proposals, expert labels, held-out evaluation, calibration, bias/error analysis and institutional acceptance testing.

## External checks still required

The following cannot be proven inside the source-only validation environment:

- live PostgreSQL, Redis, S3/MinIO and Supabase integration under production credentials
- ClamAV signature updates and EICAR acceptance testing in the deployed runtime
- backup restoration and disaster-recovery drills
- production-domain CORS, host and TLS configuration
- Vercel-to-backend connectivity
- real multi-user acceptance testing with applicant, reviewer, adjudicator and committee roles
- independent security review and institutional evaluation-policy approval

## Corrective audit note

The bug-fix audit additionally corrected the frontend Docker copy context, Vite environment directory, migration package invocation, MinIO initialization ordering, missing container environment propagation, account-status failure handling, and release-manifest integrity. See `BUGFIX_REPORT.md`.
