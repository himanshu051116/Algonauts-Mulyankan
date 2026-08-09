# Mulyankan 0.7.0.3 Registry-Consistency and Failure-State Hotfix

## Confirmed live defect

A fresh governed-package evaluation could fail with `model_version_missing` even while `/health/ready` had previously returned ready. The active MOC-ST model row existed and was eligible, but its stored artifact hash no longer matched the packaged evaluator files. The worker also collapsed artifact-integrity failures into `model_version_missing`, and a preflight failure created no `model_runs` row, causing the report adapter to fall back to `Legacy Unverified`.

## Corrections

- Backend readiness and the worker now call the same `select_active_model_version` function.
- The installer explicitly builds migration, backend, worker and frontend images.
- The installer compares the packaged evaluator hash across migration, backend and worker images before touching the registry.
- The authoritative migration/seed command runs after the images are built.
- Registry integrity is verified from one-off backend and worker images before startup and from live containers after startup.
- Worker audit details now retain the exact preflight exception message and classify artifact-integrity failures as `model_registry_invalid`.
- A proposal in error state with no model run is returned as `status=error`, so fresh failures render as `Evaluation failed`, never `Legacy Unverified`.

## Compatibility

- No database migration.
- No scoring threshold change.
- No evidence-contract weakening.
- No deletion or rewriting of historical proposals, uploads or evaluations.
- Existing 0.7.0 package manifests remain valid.
