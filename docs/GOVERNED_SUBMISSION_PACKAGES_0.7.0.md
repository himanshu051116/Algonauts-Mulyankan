# Governed Submission Packages — Mulyankan 0.7.0

## Purpose

Mulyankan 0.7.0 replaces the implicit single-file submission assumption with a governed, version-bound proposal package. The upgrade does not relax the 0.6.3 evidence gate and does not convert supporting documents into unrestricted scoring input. It makes the document set, declared role, policy requirement and package identity explicit before a proposal can enter evaluation.

Mulyankan remains a preliminary scrutiny and human decision-support platform. Package confirmation proves only which files and roles the applicant submitted; it is not an eligibility certificate, scientific validation or approval recommendation.

## Package policy

The active Coal S&T package policy is stored in `data/schemes/moc-st-required-documents-v1.yaml`. Every slot defines:

- a stable requirement identifier;
- a user-facing label and description;
- an expected governed document role;
- permitted file types and a requirement-specific size ceiling;
- whether the slot is mandatory.

The mandatory 0.7.0 slots are the proposal body, budget estimate, PI CV, institutional endorsement, declaration/undertaking and prior-funding declaration. Co-PI CVs, DGMS approval and industry support are optional policy slots. Conditional policy interpretation remains a human/governance responsibility; the application does not infer that an optional document is legally unnecessary.

## Submission lifecycle

1. The applicant creates or opens an editable proposal version.
2. Each upload session is bound server-side to the proposal version, requirement ID, declared role, file name, size limit and permitted MIME type.
3. Upload confirmation performs object integrity, signature, malware and bounded extraction checks.
4. Replacing a main proposal supersedes only the former main proposal. Replacing a supporting slot supersedes only the active document assigned to the same requirement.
5. Any package mutation invalidates a previous confirmation, manifest and package hash.
6. The applicant explicitly confirms the declared roles.
7. The backend verifies mandatory slots, role/type constraints, upload integrity, exactly one active authoritative main proposal and no unassigned active documents.
8. The backend stores a canonical manifest and SHA-256 package hash on the proposal version.
9. Submission is accepted only while the current active document set reproduces the confirmed hash.

## Evidence isolation

The main proposal remains authoritative for document-quality gating, scheme suitability and canonical field extraction. Supporting documents may contribute evidence only where the versioned evidence contract permits their role. Examples include:

- PI/team CVs for team track record;
- budget annexures or quotations for budget criteria;
- industry support letters for adoption/collaboration;
- safety, environment or compliance documents for corresponding readiness criteria.

A supporting document cannot start scoring by itself, replace the authoritative proposal body, or satisfy a criterion whose contract does not permit its role. Evidence records retain document ID, file name and role provenance.

## Immutable identity and auditability

The canonical manifest contains stable proposal/version identity and a sorted list of active documents with requirement ID, role, file metadata, primary status and SHA-256 hash. The package hash is the SHA-256 of deterministic canonical JSON. Evaluation model-run input identity prefers this package hash when a package is confirmed.

Audit events record upload-session creation, document confirmation, package confirmation and proposal submission. Historical evaluated versions are marked `legacy_single_document`; the migration does not falsely claim that those versions were applicant-confirmed packages.

## Compatibility boundaries

- Existing non-draft 0.6.3 proposal versions remain readable and reproducible as legacy single-document snapshots.
- Existing scoring, rubric, statistical model artifact, evidence-contract version and score-release thresholds are unchanged.
- The main-proposal API retains PDF, DOCX and TXT extraction compatibility. The governed browser workflow presents the policy-preferred file types.
- New or revised submissions must satisfy and confirm the governed package policy before evaluation.
- No historical model run, criterion prediction or committee decision is rewritten.

## Database changes

Alembic revision `20260708_packages` adds package status, manifest, hash, policy version and confirmation attribution to `proposal_versions`, plus requirement IDs on upload sessions and proposal documents. It also enforces one active document per governed requirement and indexes package hashes.

## Verification focus

Release verification must prove:

- deterministic manifest hashes independent of upload ordering;
- missing mandatory slots prevent confirmation;
- package changes invalidate confirmation;
- one supporting slot does not supersede unrelated files;
- role-disallowed evidence cannot release a criterion;
- role-permitted evidence retains source-document provenance;
- the 0.6.3 no-evidence-no-score and abstention rules still pass unchanged.
