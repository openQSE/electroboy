# Implementation Artifact

This artifact records what changed in each implementation phase. It gives
review agents a stable phase-by-phase baseline for implementation review.

## Phase 0. Repository Foundation

Commit: `363a278 pipeline: add initial CLI foundation`
Follow-up commit: `8d21012 phase 0: add project environment entrypoints`

Implemented:

- Added Python project metadata and package skeleton.
- Added `ai-pipeline` CLI entry point.
- Added basic run initialization, status, stage, gate, resume, and change
  commands.
- Added early JSON state handling and ordered-flow tests.
- Added README usage guidance and Python ignore rules.
- Added `./ai-pipeline` and `./electroboy` source checkout wrappers.
- Added the `electroboy` console-script alias.
- Added `ai-pipeline new <path>` for project creation.
- Added generated project activation scripts under `<project>/bin/activate`.
- Added `ai-pipeline deactivate` shell-safe project deactivation.
- Added Rich as the terminal progress dependency for the target workflow.
- Added project environment tests for creation, activation files, and
  deactivation records.
- Generated project wrappers set `PYTHONPATH` to the pipeline source so
  `ai-pipeline` and `electroboy` work outside the source checkout.
- Generated wrappers now use project-local runtime code instead of embedding
  the creator's absolute checkout path.
- `ai-pipeline new <path>` now reuses an existing Git worktree and initializes
  a repository only when the target is not already inside one.
- Runtime config loading now prefers `.agent-pipeline/project.toml` and keeps
  root-level `agent-pipeline.toml` as a compatibility fallback.
- Project config parsing accepts the documented `[environment]` section.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 1. Artifact Templates

Implemented:

- Added artifact templates for requirements, design, implementation plan, and
  API documentation.
- Added `ArtifactManager` helpers for creating missing artifacts without
  overwriting existing files.
- Added artifact snapshot support with SHA-256 checksums.
- Added `ai-pipeline artifacts init` and `ai-pipeline artifacts snapshot`.
- Added artifact snapshot records under the active run.
- Added activity-log events for manual artifact snapshots.
- Added artifact tests for template safety and snapshot creation.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 2. State Store

Follow-up commit: `070c8bd phase 2: split shared and local state`

Implemented:

- Added structured models for review issues, decisions, and phase status.
- Added structured models for approvals, stage state, change requests, and
  baseline invalidations.
- Added JSONL helpers for review issue files and decision records.
- Made review issue reads collapse append-only lifecycle records to the latest
  issue state.
- Added phase status persistence in `.agent-pipeline/phase-status.json`.
- Added message and raw runtime stream writers.
- Added recursive redaction for JSON-compatible state records.
- Added tests for review issue, phase status, decision, and raw-event state.
- Moved committed run state under `.agent-pipeline/shared/`.
- Moved local raw runtime streams under `.agent-pipeline/local/`.
- Preserved legacy read paths while writing new state to the shared layout.
- Updated artifact snapshots to use the shared run directory.
- Updated tests for the shared and local state split.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 3. Gate Engine

Implemented:

- Added gate constants for stage order, change control, plan currency, code
  review, phase test review, and commit readiness.
- Added approval and snapshot checks to predecessor gates.
- Added gate evaluation activity events.
- Added change-control gate checks that block stage transitions while change
  requests remain open.
- Added implementation-plan currency checks for active phase drift.
- Added code review and phase test review gates based on phase status and
  blocking review issues.
- Required code review and test review gates to have runtime-backed agent
  invocation evidence before a phase commit can pass.
- Added commit gate composition across implementation, plan currency, code
  review, and phase test review gates.
- Added gate tests for open change requests, plan drift, blocking review
  issues, and commit readiness.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 4. Runtime Adapter Interface

Implemented:

- Added `PipelineConfig` loading for `agent-pipeline.toml`.
- Added runtime selection by role with a default Codex runtime.
- Expanded `AgentInvocation` and `AgentResult` to carry schema, event,
  command, changed-file, and error data.
- Added explicit runtime environment allowlists.
- Added runtime factory functions for manual, generic CLI, Codex exec, and
  Codex SDK adapters.
- Implemented manual runtime completion from a configured response file.
- Normalized subprocess runtime failures as failed `AgentResult` values.
- Added tests for config parsing, role selection, and manual runtime results.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 5. CLI Runtime Adapters

Implemented:

- Implemented subprocess-backed generic CLI runtime invocation.
- Added prompt construction with role context paths.
- Added stdout parsing for plain text and JSON agent results.
- Implemented Codex JSONL parsing for final messages and raw events.
- Added `ai-pipeline agent run` for configured role invocation.
- Stored agent prompts, responses, raw runtime events, and activity events.
- Added runtime adapter tests for generic JSON output and Codex JSONL output.
- Added explicit Codex sandbox selection for read-only review roles and
  workspace-write coding roles.
- Stored structured agent issues in the mapped review issue files.
- Normalized structured Codex `ok: false` final messages as failed agent
  results.
- Runtime subprocesses now receive only the configured environment allowlist.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 6. Requirements And Design Loops

Follow-up commit: `b297058 phase 6: add authoring stage commands`

Implemented:

- Added artifact snapshots when requirements, design review, design
  acceptance, or implementation planning stages complete.
- Added `ai-pipeline issues add`, `issues list`, and `issues resolve`.
- Added explicit stage approval records for requirements, design, design
  acceptance, and planning.
- Made issue resolution append a verified lifecycle transition instead of
  rewriting review history.
- Blocked design-review completion while open blocker or major design issues
  remain.
- Preserved design review issue records in run JSONL files.
- Added tests for requirements snapshots and design review issue iteration.
- Added public `requirements` and `requirements-approve` commands.
- Added public `design`, `design-review`, and `design-approve` commands.
- Added resumable authoring activity records for requirements and design.
- Routed public requirements, design, and implementation-plan commands through
  the configured Design Author Agent runtime before recording authoring state.
- Routed public design review through the configured Design Review Agent
  runtime before completing the design-review gate.
- Required Design Author Agent confirmation to come from a successful
  runtime-backed authoring event before requirements or plan approval.
- Reused existing approval and design-review gates from the public commands.
- Added tests for public requirements authoring and design review flow.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 7. Implementation Planning

Implemented:

- Added `ai-pipeline plan check` for phase-to-requirement traceability.
- Added `ai-pipeline plan update` to record implementation-plan changes.
- Replaced substring traceability checks with phase parsing and REQ-id
  validation against `docs/requirements.md`.
- Blocked plan-stage approval when structured traceability is missing.
- Snapshotted the implementation plan when plan updates are recorded.
- Added activity-log records for implementation-plan update decisions and
  plan snapshots.
- Added implementation-plan command entries to `docs/implementation-plan.md`.
- Added plan tests for traceability checks and update recording.
- Added public `implementation-plan` and `plan-approve` commands.
- Reused the existing plan traceability and approval gates from the public
  commands.
- Added tests for public plan approval through the traceability gate.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 8. Phase Implementation Loop

Follow-up commit: `14ad0a6 phase 8: add implementation workflow commands`

Implemented:

- Added `ai-pipeline phase start` to activate an implementation phase.
- Added `ai-pipeline phase review --pass` for code review completion.
- Added `ai-pipeline phase test --pass` for phase test review completion.
- Added `ai-pipeline phase drift` for active-phase plan drift.
- Added `ai-pipeline phase commit` with commit-gate enforcement.
- Blocked a second active phase from overwriting an uncommitted phase.
- Required review and test review commands to target the active phase.
- Required phase commits to reference an existing git commit SHA.
- Made plan updates restore active-phase plan currency.
- Added tests for review-gated phase commits and plan-drift blocking.
- Added public `ai-pipeline code` for starting or resuming implementation.
- Made `code` start the next uncommitted planned phase.
- Made `code` resume an already active phase from durable phase status.
- Made `code` invoke the configured coding, code review, and test review
  agent runtimes for the active phase.
- Persisted coding, code review, and test review event ids in phase status.
- Required phase commit gates to use runtime-backed review evidence instead of
  manual pass flags alone.
- Attributed manual phase review and test markers to the human operator.
- Cleared active-phase review evidence when phase-plan drift is recorded.
- Required phase commit SHAs to be reachable from `HEAD`.
- Required phase commit messages to identify the active phase and objective.
- Checked phase commit changed paths against implementation-plan `Paths:`
  metadata when a planned phase declares scope paths.
- Added Rich-compatible progress output with a plain text fallback.
- Added tests for public `code` phase startup.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 9. Validation Testing

Implemented:

- Added `ai-pipeline validate` for final validation testing.
- Added support for one or more validation commands through `--command`.
- Added artifact-backed validation commands parsed from `Validation:` lines in
  `docs/requirements.md` and `docs/detailed-design.md`.
- Failed validation when required artifact-backed validation commands are
  missing.
- Added a required validation command that runs the full unit test suite.
- Returned validation failures to a validation-fix implementation phase.
- Ran validation commands as argument vectors unless explicit shell mode is
  requested.
- Normalized missing validation executables into failed validation results
  instead of uncaught subprocess errors.
- Wrote validation output to the run artifact
  `artifacts/validation-report.md`.
- Recorded validation command sources in the validation report.
- Stored raw validation command results in the run raw-event log.
- Added blocking `validation-review.jsonl` issues when validation fails.
- Blocked validation success while open blocker or major validation issues
  remain.
- Required every planned phase to be committed before validation can pass.
- Advanced the run from validation to documentation review when validation
  passes.
- Allowed the implementation stage to transition into validation after all
  active phase work is committed.
- Added validation tests for pass and fail outcomes.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 10. Documentation Review

Follow-up commit: `14ad0a6 phase 8: add implementation workflow commands`

Implemented:

- Added `ai-pipeline docs-review` for final documentation verification.
- Required `docs/requirements.md`, `docs/detailed-design.md`, `README.md`,
  and `docs/api.md` before the documentation gate can pass.
- Added blocking `documentation-review.jsonl` issues for missing required
  documentation files.
- Verified generated missing-file issues automatically when the file is
  restored.
- Added deterministic content checks for README usage, tests, and public CLI
  documentation.
- Checked `docs/api.md` against the actual top-level CLI parser commands.
- Blocked documentation review while open blocker or major documentation
  review issues remain.
- Snapshotted final documentation artifacts when documentation review passes.
- Stored documentation review activity with artifact snapshot refs instead of
  only source artifact paths.
- Completed the documentation gate and advanced the run to `complete`.
- Added documentation review tests for missing-file and passing-doc paths.
- Added public `ai-pipeline document` for documentation refinement and review.
- Routed public `document` through the configured Documentation Agent runtime
  before deterministic documentation checks.
- Added public `ai-pipeline code-approve` for final human completion approval.
- Blocked final approval until documentation review passes.
- Stored final human completion approval in `approvals.jsonl`.
- Added tests for `document` and `code-approve`.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 11. Change Control And Iteration

Follow-up commit: `3847e8d phase 11: reopen stages from public commands`

Implemented:

- Added latest-state reads for append-only `change-requests.jsonl` events.
- Kept classified change requests blocking until they are reopened.
- Added baseline validation for change-control commands.
- Implemented `ai-pipeline change classify <id> [--baseline <baseline>]`.
- Implemented `ai-pipeline change approve <id> --human-approved`.
- Implemented `ai-pipeline change reopen <id>`.
- Required classification and human approval before reopening.
- Invalidated downstream gates when a baseline is reopened.
- Recorded invalidated artifact snapshot refs in baseline invalidation records.
- Moved the active stage back to the reopened baseline stage.
- Recorded reopen decisions and change-control activity events.
- Updated `docs/implementation-plan.md` to document classify and reopen
  behavior.
- Added change-control tests for classified blockers and downstream gate
  invalidation.
- Added public `--reason` reopen behavior for earlier stage commands.
- Recorded public reopen commands as change requests, decisions, activity
  events, and baseline invalidations.
- Invalidated downstream gates when public commands reopen a baseline.
- Required `--reason` when an earlier public stage command moves backward.
- Added tests for public stage reopening and missing-reason blockers.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 12. Resume And Reporting

Implemented:

- Added StateStore readers for activity events and artifact snapshots.
- Expanded `ai-pipeline status` to show active phase, invalidated gates, open
  change requests, open review issues, and blocked gates.
- Expanded `ai-pipeline resume` to show the resumed stage, active phase, open
  blockers, and blocked gates.
- Added `ai-pipeline report summary` for human-readable run summaries.
- Added `ai-pipeline report trace` for activity-log trace reports.
- Expanded reports with decisions, phase commits, snapshots, and baseline
  invalidations.
- Added `--output` support for writing generated reports to files.
- Updated `docs/implementation-plan.md` to list the report commands.
- Added reporting tests for resume blockers and written summary and trace
  reports.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```
