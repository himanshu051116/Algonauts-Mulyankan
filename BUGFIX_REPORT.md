# Mulyankan 0.4.0 bug-fix audit

## Scope

The uploaded source archive was extracted into a clean directory and checked across the frontend build, backend tests, static analysis, database migration rendering, Docker/Compose definitions, environment propagation, authentication failure states, and release packaging.

## Confirmed defects fixed

### 1. Frontend Docker build referenced a missing directory

`frontend/Dockerfile` attempted to copy `public/`, but the release archive contains no `public` directory. A clean Docker build therefore failed during the copy stage even though a normal local Vite build succeeded.

**Fix:** removed the unused `COPY public/ public/` instruction and added Dockerfile source validation plus a CI builder-stage Docker build.

### 2. Vite loaded environment files from the wrong directory

The Vite configuration used `envDir: ".."` even though `vite.config.ts`, `package.json`, and `.env` are all in the repository root. Local runs could therefore miss `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, `VITE_API_URL`, and `VITE_PUBLIC_APP_URL`, causing startup or connectivity failures.

**Fix:** changed `envDir` to the repository root.

### 3. Migration container used an invalid Python module path

The migration command changed into `/app/backend` and then invoked `python -m backend.scripts.init_storage`. From that working directory, the `backend` package parent is not on `sys.path`, producing `ModuleNotFoundError: No module named 'backend'`.

**Fix:** the command now remains in `/app` and invokes `python -m backend.scripts.init_storage` from the correct package root.

### 4. Storage initialization could race MinIO startup and bucket creation

The migration service previously waited only for the MinIO container to start, while `minio-init` and the migration process could both attempt bucket initialization concurrently.

**Fix:** migration now waits for healthy PostgreSQL, Redis, and MinIO services and for `minio-init` to finish successfully before applying storage CORS configuration.

### 5. Docker silently ignored documented runtime settings

The Python containers did not receive several settings supported by `Settings`, including Supabase JWKS overrides, JWT audience/algorithms/cache/skew, JWT expiry, maximum file size, logging, Sentry, and OpenTelemetry values. Changing these in `.env` had no effect inside the containers.

**Fix:** propagated the missing settings into migration, backend, and worker services; made JWT algorithm and storage region configurable; updated environment templates; and added validation that fails when required settings disappear from Compose.

### 6. MinIO init credentials were interpolated into the rendered command

Compose substituted storage credentials directly into the `minio-init` shell command.

**Fix:** changed command references to escaped container variables so credentials are resolved inside the init container rather than embedded by Compose in the rendered command.

### 7. Frontend could render the workspace after account-status verification failed

When `/admin/users/me` failed, the frontend stored `null` but still rendered the workspace with an applicant fallback role. Backend authorization remained authoritative, but the UI showed an unlocked shell and repeatedly issued failing API requests.

**Fix:** added a locked account-verification error state with retry/sign-out actions and prevented proposal polling until an active server-side account is confirmed.

### 8. Release manifests could contain a stale self-hash

The release generator copied an existing `RELEASE_MANIFEST.json`, hashed it, then overwrote it with a new manifest. The generated manifest could therefore list an invalid hash for itself.

**Fix:** old manifests are excluded from staging and a new manifest is generated once without self-referencing.

### 9. Previous release output could be repackaged into later releases

When the default `release/` directory already contained archives, a subsequent release run could include those files in the next source archive.

**Fix:** the selected output directory is excluded from source traversal, and using the source directory itself as output is rejected.

### 10. `.env.example` was skipped by secret scanning

The scanner selected files by suffix, but `.env.example` has the suffix `.example`; credentials accidentally placed there were not scanned.

**Fix:** all `.env*` text files are now scanned. Regression tests verify detection.

## Validation results

- Frontend clean dependency installation: passed
- TypeScript production build: passed
- ESLint with zero warnings: passed
- npm high-severity dependency audit: zero vulnerabilities
- Ruff: passed
- Mypy: passed
- Backend tests: 136 passed, 3 skipped live-service tests
- Backend coverage: 72.19%, above the enforced 70% threshold
- Alembic PostgreSQL migration chain offline render: passed
- Compose and Docker build-context validation: passed
- Migration package imports from container-equivalent paths: passed
- Release packaging regression tests: passed

## Remaining external validation

A Docker daemon is not available in the analysis environment, so the full multi-container stack was not booted here. CI now builds the actual frontend Docker builder stage, and the corrected archive should still be validated on the target Windows/Docker Desktop machine with live PostgreSQL, Redis, MinIO, Supabase credentials, worker heartbeat, direct browser uploads, and role-based acceptance tests.

## 0.8.0 maintenance rectification and password recovery

A three-pass audit of the uploaded 0.8.0 working source corrected five additional defects: duplicate readiness migration constants, a stale validation verifier revision, an old Compose namespace in `.env.example`, an obsolete broken upgrade-script copy, and Python BOM artifacts. A complete Supabase forgot-password and password-update frontend flow was added with neutral account-discovery messaging, dedicated recovery routing, invalid-link handling and forced reauthentication after the password change.

Final local verification for this maintenance pass: Python compilation, Ruff, Mypy, 238 backend tests with 3 environment-dependent skips, 70.53% backend coverage, frontend ESLint, TypeScript/Vite production build, npm audit, offline Alembic head rendering, Compose validation, ML quality gate and controlled-release verification all passed. See `docs/RECTIFICATION_PASSWORD_RECOVERY_AUDIT_0.8.0.md` for scope and limitations.

## 0.8.0 clean-restart audit (2026-07-14)

The source archive was extracted into a new directory and its internal release manifest was verified before any edits. This pass corrected the following confirmed defects:

- Replaced `python-jose` and its vulnerable `ecdsa` dependency with `PyJWT[crypto]`, while preserving JWKS validation, algorithm restrictions, issuer/audience checks and clock-skew handling.
- Hardened DOCX processing by parsing every XML and relationship part with `defusedxml` before content extraction.
- Extended the ML evidence gate so a quality report is rejected when its rubric or evidence-contract hash is stale, not only when the model or benchmark hash changes.
- Made proposal submission retryable after a queue outage without creating a duplicate sealed proposal package, and added a matching retry state to the submission UI.
- Corrected asynchronous Redis pool shutdown compatibility for clients exposing `aclose()` instead of `close()`.
- Included the ESLint configuration in the frontend Docker builder so container linting works consistently.
- Replaced runtime-sensitive assertions in validation metrics with explicit error handling.

Verified results for this restart: Python compilation passed; Ruff passed; Mypy passed for 55 source files; 242 backend tests passed with 3 environment-dependent skips; coverage was 70.74%, above the enforced 70% threshold; all Alembic migrations rendered through `20260712_model_lifecycle`; frontend TypeScript/Vite production build passed; ESLint passed with zero warnings; npm reported zero vulnerabilities; `pip-audit` reported no known vulnerabilities; Bandit reported no findings; the Compose configuration validator passed; and every service in the isolated runtime became healthy. The registered ML artifact, packaged artifact, validation pilot and database migration head were also verified successfully.

The corrected stack is isolated under Compose project `mulyankan-restart-0714` and uses frontend port 23000 and API port 28000, leaving earlier instances untouched. Because no CMPDI-labelled institutional dataset is available, the bundled ML model remains an advisory bootstrap model and is not presented as externally validated decision evidence.
