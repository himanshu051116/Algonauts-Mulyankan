# Mulyankan 0.8.0 rectification and password-recovery audit

## Scope

This maintenance pass rechecked the uploaded 0.8.0 working source, corrected confirmed defects, added a complete Supabase password-recovery user journey, and regenerated a controlled source release. It does not claim that software can be proven free of every possible defect. The evidence below establishes that no known blocking defect remained in the exercised source, test, build, migration-render and release-integrity paths at the end of this pass.

## Pass 1 — source and workflow correctness

The source was inspected for duplicate module-level constants, stale migration-head references, unsafe release artifacts, authentication route handling, environment drift and obsolete source copies.

Confirmed defects corrected:

1. `backend/app/routers/health.py` defined `LATEST_MIGRATION` twice. The later stale value overrode the current Alembic head and caused readiness to report `migration: unavailable`. Exactly one assignment now remains and the regression test derives the sole Alembic head before comparing it.
2. `backend/scripts/verify_validation_pilot.py` required the previous migration revision even after the model-lifecycle migration was added. It now derives the single current Alembic head from `migrations/alembic.ini` rather than maintaining another stale constant.
3. `.env.example` used the older `mulyankan-061` Compose namespace. It now uses `mulyankan-080`, preventing new 0.8.0 deployments from joining old 0.6.1 containers and volumes by default.
4. An obsolete `upgrade-expert-validation-0.8.0.ps1.original-broken` copy was present under the allowlisted `scripts` directory. The copy was removed, and both the packager and independent verifier now reject obsolete or broken source copies.
5. UTF-8 byte-order marks were removed from Python sources where they could interfere with source-level parsing and quality tooling.

Password recovery added:

- The sign-in screen now exposes an accessible **Forgot password?** action.
- Reset requests call Supabase `resetPasswordForEmail` with a dedicated `/auth/reset-password` redirect.
- The response is neutral and does not reveal whether the email address is registered.
- Recovery sessions are recognized through the URL and `PASSWORD_RECOVERY` auth event.
- The dedicated reset page validates matching passwords, calls `updateUser`, removes the recovery URL from history, signs out the recovery session and requires a fresh sign-in.
- Invalid or expired recovery links fail closed to a recovery-error screen rather than opening the workspace.
- Deployment documentation now requires both `/auth/callback` and `/auth/reset-password` in the Supabase redirect allowlist.

## Pass 2 — automated quality verification

Executed against the rectified source:

| Gate | Result |
|---|---|
| Python compilation | Passed |
| Ruff | Passed |
| Mypy | Passed — 55 source files |
| Backend tests | Passed — 238 passed, 3 skipped |
| Backend coverage | 70.53% — threshold 70% |
| Frontend ESLint | Passed with zero warnings |
| TypeScript + Vite production build | Passed |
| npm audit | Passed — 0 known vulnerabilities at the configured threshold |
| Alembic full offline render | Passed through `20260712_model_lifecycle` |
| Compose/build-context validation | Passed |
| No-private-data ML quality gate | Passed; promotion remains bootstrap advisory |

One Starlette test-framework deprecation warning remains. It concerns the test client's future HTTP transport package and is not a runtime application failure. It should be addressed when the project's Starlette/FastAPI test stack formally migrates to the successor transport.

## Pass 3 — release and security verification

The controlled source packager was run after the code checks. It uses a top-level allowlist and excludes runtime `.env` files, backups, SQL/database files, caches, dependencies, build output and prior archives. The independent verifier checked the archive checksum, manifest, member paths, per-file hashes, secret patterns, SBOM and forbidden file rules.

Final release evidence is supplied next to the archive in its checksum and verification files. The working source folder remains unsuitable for distribution because it contains deployment credentials and runtime data; only the controlled source ZIP should be shared.

## Required Supabase deployment setting

For each frontend origin, configure these exact Auth redirect URLs in Supabase:

- `<frontend-origin>/auth/callback`
- `<frontend-origin>/auth/reset-password`

`VITE_PUBLIC_APP_URL` must equal the frontend origin. Email delivery and redirect allowlisting are external Supabase configuration and must still be exercised with the actual deployment account.

## Conclusion

The audited source passes the available static, unit, build, migration-render, ML-governance and controlled-release gates. The remaining acceptance work is environment-dependent: live Supabase email delivery, an actual recovery-link click, Docker end-to-end startup, role-based browser acceptance and production credential rotation.
