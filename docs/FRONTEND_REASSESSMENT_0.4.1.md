# Mulyankan 0.4.1 frontend reassessment

## Scope

The frontend was reassessed against five criteria: correctness of decision-support information, workflow usability, accessibility, responsive behaviour, and operational resilience. The work intentionally preserves the existing coal R&D evaluation architecture and authoritative backend workflow.

## Confirmed defects corrected

1. **Misleading portfolio chart:** proposals in pending or review states could leave an unallocated conic-gradient segment that appeared red, visually implying rejection. Every workflow state now receives an explicit segment.
2. **Processing errors shown as rejection:** the frontend converted backend `error` status to `rejected`. Errors now remain operational errors and are labelled separately.
3. **Human-review stages collapsed into “completed”:** `human_review`, `adjudication`, and `committee_review` now remain distinct workflow states.
4. **Incompatible upload retained:** switching from PDF to Word, or vice versa, retained the previous file in React state. The file is now cleared whenever the document type changes.
5. **Insufficient upload validation:** the browser now rejects empty files, wrong extensions, and files larger than 50 MB before creating an upload request.
6. **Blank screen on missing Supabase variables:** import-time configuration failure was replaced with an explicit deployment-configuration screen.
7. **Overlapping background refreshes:** workspace refreshes now use an in-flight guard and pause while the tab is hidden.
8. **Mobile history information loss:** status and score were hidden on narrow screens. Both are now displayed in a compact metadata row.
9. **Dialog keyboard gaps:** the report dialog now closes with Escape, restores focus, and locks background scrolling.
10. **Weak failure containment:** a top-level React error boundary now provides a recovery screen for unexpected rendering failures.

## UX and visual improvements

- submission flow reorganised into numbered document, scheme, and proposal-detail sections
- accessible drag-and-drop file area with selected-file metadata and removal control
- title and summary character counters
- live readiness score with evidence-specific checklist
- clearer advisory/human-decision language throughout the workspace
- distinct colours and labels for automated evaluation and institutional review stages
- refresh control and retry action for workspace data failures
- search clearing, comprehensive status filters, and date/score sorting
- correct user role shown in the sidebar instead of a hard-coded generic label
- improved touch targets, focus visibility, typography, spacing, contrast, and responsive behaviour
- reduced-motion support and a keyboard skip link
- remote font dependency removed to improve privacy, offline rendering, and startup reliability

## Validation

- TypeScript production build: passed
- ESLint with zero warnings: passed
- npm high-severity dependency audit: passed
- backend test suite and coverage gate: passed
- Python compilation, Ruff, Mypy, Alembic offline migration rendering, and Compose validation: passed

A live browser screenshot could not be captured in the execution container because its installed Chromium process did not terminate correctly in headless mode. Responsive states were reviewed through the component structure, CSS breakpoints, TypeScript build, and static interaction audit. This limitation does not affect the generated source or normal browser operation.
