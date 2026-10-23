# Mulyankan Resolve — Pending Operation Gate v8

**Staged source patch; not installed into the default branch or deployed.**

This directory preserves the v8 source-level upgrade to the Razorpay dispute RiskOps prototype. It must **not** be installed directly over the repository's current public \`main\`, which has not yet incorporated the preceding Resolve releases.

## The change

- Enforces one unresolved provider operation per dispute using a PostgreSQL partial unique index on \`riskops_provider_operations(case_id)\` for \`reserved\`, \`observed\`, and \`ambiguous\`.
- Allows different later actions only after previous operations are explicitly completed.
- Retains immutable per-attempt idempotency keys; repeat bytes / draft attempts remain blocked.
- Stops migration if the old journal already contains more than one unresolved operation for any case.
- Does **not** auto-retry, contest, accept, submit, or claim exactly-once provider effects.

## Exact prerequisite chain

\`Integration v4 → Frontend v5 → Security v6 → Recovery v7 → Pending Gate v8\`.

Apply these in a **separate fully integrated clone**, draining v7 workers before applying the PostgreSQL migration; never run mixed v7/v8 workers. Verify the frozen v24 manifest (20 source hashes) before and after applying. The v8 source files here belong at repository-relative paths under \`payload/\` only **after** all previous upgrades have passed their pinned installer checks.

The source-package installer, release manifest, and regression suite are staged here alongside this payload. See the included \`apply_pending_gate_v8.py\`; it refuses changed baselines.

## Verification status

- Previously verified locally: 11 network-free v8 regression/SQL contract checks, compile audit, and installer dry-run checks.
- **Not** verified in GitHub CI: actual PostgreSQL migration/concurrent workers, full historical backend tests, production Vite build, authenticated provider flow.
- No real Razorpay Test Mode calls and no production merchant outcome metrics.

**Safety:** do not put Razorpay API credentials into the repo. Provider host and keys must remain server-side and Test Mode restricted until authorized integration testing is complete.

The corresponding complete multi-version offline handoff is preserved separately; this PR stages the v8 reviewable patch and does not imply the public repository is immediately v8 deployable.
