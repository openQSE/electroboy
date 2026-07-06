# ElectroBoy Implementation Plan

## Table of Contents

- [Purpose](#purpose)
- [Recommendation](#recommendation)
- [Implementation Choice](#implementation-choice)
- [CLI Configuration And Credentials](#cli-configuration-and-credentials)
- [Runtime Strategy](#runtime-strategy)
  - [Manual Adapter](#manual-adapter)
  - [Generic CLI Adapter](#generic-cli-adapter)
  - [Codex Exec Adapter](#codex-exec-adapter)
  - [Codex SDK Adapter](#codex-sdk-adapter)
- [Non-Goals](#non-goals)
- [Repository Layout](#repository-layout)
- [State And Artifact Storage](#state-and-artifact-storage)
- [Project Environment Activation](#project-environment-activation)
- [Data Models](#data-models)
- [CLI Shape](#cli-shape)
- [Flow Enforcement](#flow-enforcement)
- [Implementation Plan Maintenance](#implementation-plan-maintenance)
- [Agent Prompt Contracts](#agent-prompt-contracts)
- [Stage Implementation Phases](#stage-implementation-phases)
- [Recommended Initial Milestone](#recommended-initial-milestone)
- [Provider API Alternative](#provider-api-alternative)
- [Security Requirements](#security-requirements)
- [Verification Commands](#verification-commands)
- [Open Implementation Decisions](#open-implementation-decisions)

## Purpose

This document defines the implementation strategy for the AI agent pipeline
described in `docs/detailed-design.md`. It explains how the pipeline is built,
which automation surface drives agent work, where API keys fit, and how the
work is broken into reviewable phases.

The recommended implementation is a local Python CLI orchestrator that manages
state, artifacts, gates, and loop control. Agent work is delegated to role
adapters. Codex is the default agent CLI, but the orchestrator can use another
configured CLI when it satisfies the same invocation and response contract.
The orchestrator enforces the ordered requirements, design, planning,
implementation, validation, and documentation flow.

## Recommendation

Use a Python CLI to define the loops, gates, state files, and artifact
snapshots. Use a configured agent CLI for review, coding, validation, and
documentation work. The default runtime is Codex through `codex exec --json`.
Mutating CLI commands must pass stage-order checks before they invoke agents or
edit pipeline state.

This approach keeps process control deterministic while using an agent CLI for
the work that benefits from a repository-aware assistant: reading files,
editing code, running commands, reviewing diffs, and explaining results.

Direct provider API usage is an extension path, not the starting point. A
direct API implementation would have to recreate shell execution, filesystem
policy, git integration, sandboxing, streaming events, and structured review
handling. A CLI runtime already provides many of those primitives for local
software work.

## Implementation Choice

The pipeline needs two separate capabilities.

The orchestrator controls process state. It knows which stage is active, which
artifact is approved, which issues remain open, which gate is blocked, and what
event must be written to the activity log. This behavior belongs in ordinary
deterministic code.

The agents perform reasoning and code work. They review prose, inspect diffs,
write code, propose tests, run commands, and summarize results. This behavior
belongs in a configured agent runtime.

The selected implementation uses Python for orchestration and an adapter-backed
agent CLI for execution.

The CLI is exposed through two equivalent command names. `electroboy` is the
primary tool name, and `ai-pipeline` is the plain compatibility alias.
Repository checkouts provide `./electroboy` and `./ai-pipeline`; installed
environments provide `electroboy` and `ai-pipeline`.

## CLI Configuration And Credentials

The orchestrator selects an agent runtime from configuration. Codex is the
default runtime because it provides a coding-oriented CLI, workspace access,
shell execution, sandbox settings, and non-interactive execution through
`codex exec`. A project can configure another CLI, such as Claude or a local
agent tool, when that CLI can satisfy the pipeline contract.

Each runtime configuration defines the command, arguments, working directory,
environment allowlist, sandbox policy, output mode, and parser. The
orchestrator can also assign different runtimes by role. For example, design
review can use Codex while code review uses another CLI, as long as both
adapters return the same `AgentResult` shape.

Example configuration:

```toml
[runtime]
default = "codex"

[runtimes.codex]
adapter = "codex_exec"
command = "codex"
args = ["exec", "--json"]
structured_output = "json_schema"

[runtimes.claude]
adapter = "generic_cli"
command = "claude"
args = ["<non-interactive-args>"]
structured_output = "prompt_contract"

[roles]
design_author = "codex"
design_review = "codex"
coding = "codex"
code_review = "claude"
test_review = "codex"
documentation = "codex"

[environment]
python_activate = ".venv/bin/activate"
python_managed_by_pipeline = false
activate_python = true
```

A CLI runtime is compatible when it can:

- Run non-interactively from a command.
- Receive a role prompt and context bundle.
- Restrict or document filesystem write behavior.
- Return a final response that can be parsed into `AgentResult`.
- Keep credentials outside repository files and durable run state.

Credentials depend on the selected runtime. An API key is needed only when the
selected CLI authentication path requires one. Codex can authenticate through
ChatGPT sign-in or through an API key. Other CLIs may use their own login
files, environment variables, local services, or provider keys.

Codex supports `CODEX_API_KEY` for `codex exec`. The orchestrator treats that
variable as an invocation-time credential, not as repository configuration.
The same rule applies to credentials for any other CLI.

The implementation must never store API keys in repository files,
`.electroboy/`, prompts, logs, activity events, review issues, or generated
reports. Environment snapshots written by the orchestrator must redact known
secret variables.

Recommended authentication model:

- Developer workstation: use the selected CLI's normal login flow.
- Local scripted automation: use saved CLI auth or pass a scoped credential
  only to the single agent process.
- CI or shared runners: use a dedicated secret store and pass credentials only
  to the isolated agent step.
- Public or untrusted repositories: do not expose API keys to jobs that execute
  repository-controlled code.

A local prototype only needs at least one configured agent CLI installed and
authenticated. No repository file should contain a secret value.

## Runtime Strategy

The orchestrator supports multiple runtime adapters behind the same interface.

### Manual Adapter

The manual adapter writes role prompts and expected response schemas into the
run directory. A human runs the desired agent manually and stores the response
file where the orchestrator expects it.

This adapter is useful for bootstrap work and for debugging prompt design.
It requires no programmatic model calls from the orchestrator.

### Generic CLI Adapter

The generic CLI adapter invokes any configured command that can run
non-interactively. It passes the role prompt and context bundle through stdin,
a temporary prompt file, or command arguments, depending on the runtime
configuration.

This adapter is responsible for process execution, timeout handling, stdout
and stderr capture, exit-code interpretation, and response parsing. When the
CLI cannot emit structured JSON directly, the prompt contract requires the
final response to include the structured fields that the parser needs.

The generic adapter supports CLIs such as Claude or local agent tools without
changing orchestrator logic. Runtime-specific behavior stays in configuration
or in small parser modules.

### Codex Exec Adapter

The Codex exec adapter invokes `codex exec --json` with a role-specific prompt
and a curated context bundle. The adapter captures JSONL events, final output,
file changes, commands, and errors. It then converts the result into activity
events and structured issue records.

Default sandbox policy:

- Read-only for design review, code review, test review, validation testing,
  and documentation review.
- Workspace-write for coding-agent turns and documentation-agent fix turns.
- No full-access mode in the baseline implementation.

The adapter must pass explicit prompts, capture stdout and stderr separately,
and store the raw Codex JSONL stream under the run directory when useful for
debugging. Stored streams must be scrubbed for secrets before they become
durable artifacts.

### Codex SDK Adapter

The SDK adapter is an extension point. It provides finer thread control than
shelling out to `codex exec`, but it adds dependency and integration
complexity. The implementation keeps this adapter behind the same interface as
the manual, generic CLI, and Codex exec adapters.

## Non-Goals

- The baseline does not call provider APIs directly.
- The baseline does not implement its own shell tool runner for agents.
- The baseline does not create a web dashboard.
- The baseline does not run multiple coding agents concurrently.
- The baseline does not rely on hidden agent conversation memory.

## Repository Layout

The implementation uses this layout:

```text
src/electroboy/
  __init__.py
  cli.py
  config.py
  models.py
  state_store.py
  artifacts.py
  gates.py
  orchestrator.py
  redaction.py
  prompts/
    __init__.py
    requirements.py
    design.py
    implementation_plan.py
    code.py
    review.py
    validation.py
    documentation.py
  adapters/
    __init__.py
    base.py
    manual.py
    generic_cli.py
    codex_exec.py
    codex_sdk.py
tests/
  test_state_store.py
  test_gates.py
  test_redaction.py
  test_orchestrator.py
docs/
  requirements.md
  detailed-design.md
  implementation-plan.md
  api.md
README.md
```

The package name can be adjusted before implementation begins. The layout keeps
configuration, stage logic, state persistence, prompt construction, and runtime
adapters separate.

## State And Artifact Storage

The orchestrator stores run state under `.electroboy/`. The directory is
split into committed shared state and ignored local state.

```text
.electroboy/
  project.toml
  shared/
    current-run
    phase-status.json
    decisions.jsonl
    runs/
      <run-id>/
        manifest.json
        approvals.jsonl
        activity-log.jsonl
        change-requests.jsonl
        baseline-invalidations.jsonl
        artifact-snapshots.jsonl
        design-review.jsonl
        phase-<n>-code-review.jsonl
        phase-<n>-test-review.jsonl
        validation-review.jsonl
        documentation-review.jsonl
        artifacts/
          requirements.md
          detailed-design.md
          implementation-plan.md
          validation-report.md
          README.md
          api.md
        messages/
          <event-id>.md
  local/
    activation.json
    sessions/
    raw/
    logs/
```

Working artifacts remain in their normal repository paths. Approved snapshots
are copied into `artifacts/` at gate boundaries. Review comments and findings
are written as JSONL issue records. Agent prompts and full textual responses
are stored in `messages/`.

Shared records are committed to git by default. They include approvals,
review issues, change requests, baseline invalidations, artifact snapshots,
decisions, phase status, and activity events. This lets multiple developers
collaborate on the same requirements, design, plan, and review history.

Local records are ignored by git. They include provider session ids, raw
runtime streams, local logs, activation state, machine-specific paths, and
temporary checkpoints. Optional raw runtime streams are stored under
`local/raw/` after redaction. Credentials are never written to shared or local
state.

Change-control requests are stored in `change-requests.jsonl`. Each request
records the reason for reopening earlier work, the earliest affected baseline,
the downstream gates that were invalidated, and the stage where the pipeline
resumes.

## Project Environment Activation

`electroboy new <path>` creates or enters the project environment. It creates
the target directory when needed. If the target is not already inside a Git
worktree, it initializes a GitHub-ready repository. Existing repositories are
reused instead of nesting a new repository. The command writes standard
artifact templates, creates `.electroboy/`, installs
`<path>/bin/activate`, and writes project-local runtime code under ignored
local state.

The activation script sets project-specific environment variables and wraps the
`electroboy` command so the current shell has a project context. It also
prints the active stage, blocked gate when applicable, and next useful command.

The activation script can enter a configured Python environment:

```toml
[environment]
activate_python = true
python_activate = ".venv/bin/activate"
python_managed_by_pipeline = false
```

When `python_managed_by_pipeline` is true, `electroboy deactivate` deactivates
that Python environment while restoring pipeline variables. When the Python
environment was active before project activation, the pipeline leaves it in
place. The activation script does not define or override bare `deactivate`.

`electroboy deactivate` is implemented as an activated-shell wrapper around
the CLI. The wrapper can restore environment variables in the current shell,
while the Python process records the deactivation event in local state.

Activation is restart-safe. If the shell closes during a code run, the operator
can run `source <project>/bin/activate` and then `electroboy code`. The
orchestrator resumes from shared run state, phase status, issue records,
artifact snapshots, and any safe local checkpoint data.

## Data Models

The baseline implementation uses typed Python models and JSON serialization.
Pydantic is useful but not required. If the project avoids third-party
dependencies during bootstrap, dataclasses plus JSON Schema validation are
sufficient.

Required models:

- `RunManifest`
- `ActivityEvent`
- `ReviewIssue`
- `DecisionRecord`
- `PhaseStatus`
- `ArtifactSnapshot`
- `GateResult`
- `StageState`
- `ChangeRequest`
- `BaselineInvalidation`
- `RuntimeConfig`
- `AgentInvocation`
- `AgentResult`

Each model includes a schema version. Schema versions let the pipeline migrate
state files safely as the design evolves.

## CLI Shape

The primary CLI exposes commands that match the operator workflow.

```text
electroboy new <path>
source <path>/bin/activate
electroboy status
electroboy requirements [--reason <text>]
electroboy requirements-approve
electroboy design [--reason <text>]
electroboy design-review
electroboy design-approve
electroboy implementation-plan [--reason <text>]
electroboy plan-approve
electroboy code [--reason <text>] [--phased]
electroboy validate
electroboy document [--reason <text>]
electroboy code-approve
electroboy deactivate
electroboy report summary
electroboy report trace
```

`requirements`, `design`, and `implementation-plan` invoke the configured
Design Author Agent in an interactive authoring context. The orchestrator
passes the active artifact, predecessor baselines, open review issues,
decisions, and current stage state. The command records a draft event when the
session exits. Approval remains separate so the human operator can review the
artifact before the pipeline advances.

`design-review` starts the automated design review loop. `code` starts or
resumes the fully automated implementation loop. By default, it runs every
remaining planned phase, invokes coding, code review, and test review agents,
creates and records each valid phase commit, and advances to validation when
the implementation plan is complete. `code --phased` runs one phase and leaves
commit creation or commit recording to the operator before the next phase can
start. During `code`, the orchestrator uses Rich progress indicators for the
active phase, code review, test review, escalations, and resumable checkpoints.

`validate` runs final validation testing after the implementation stage is
complete. It runs the full test suite and the validation commands declared by
the artifacts. If validation finds blocker or major issues, the orchestrator
opens a validation-fix implementation phase and returns the run to `code`.

`document` starts or resumes the documentation finesse pass. It gives the
Documentation Agent the final codebase, requirements, design, implementation
plan, validation report, and review history. The command must pass before
`code-approve` can record final completion.

Earlier stage commands are the primary iteration mechanism. When the active run
is beyond the requested stage, the command opens a change-control record,
stores the supplied reason, invalidates downstream gates after approval, and
re-enters the ordered pipeline at that stage. Later stage commands are blocked
until all predecessor gates pass.

The implementation can still expose lower-level commands for debugging,
testing, and CI automation:

```text
electroboy debug gate <name>
electroboy debug phase start <n>
electroboy debug phase review <n> --pass
electroboy debug phase test <n> --pass
electroboy debug phase commit <n> --sha <commit-sha>
electroboy debug validate [--command <argv>...]
electroboy debug change status
```

Those commands use the same gate engine and activity log as the primary CLI.

## Flow Enforcement

The CLI enforces the pipeline as an ordered state machine. A mutating command
loads the run manifest, checks the active stage, evaluates predecessor gates,
and refuses to run when the requested action would skip required requirements,
design, planning, validation, or documentation work.

Read-only commands can inspect any run state. Mutating stage commands follow
the user-facing transition rules:

- The active stage command resumes the active stage.
- An earlier stage command starts a controlled iteration from that stage.
- A later stage command is blocked until every predecessor gate passes.
- A completed run can be re-entered from any earlier stage.
- `code` resumes from the last durable checkpoint when implementation was
  interrupted.
- `document` resumes the documentation stage after validation testing passes.

The orchestrator records every accepted transition in `activity-log.jsonl`.

The gate engine owns these decisions:

- Starting a run is valid only at requirements definition.
- Design work requires an approved requirements baseline.
- Implementation planning requires human acceptance of reviewed design.
- Phase implementation requires an approved implementation plan.
- Validation testing requires all planned phases to be committed.
- Final documentation review requires validation testing to pass.
- Moving backward creates or resumes a change-control request.

When an earlier stage command is used, the orchestrator records the reason,
classifies the earliest affected baseline, and invalidates downstream gates
that depended on the old baseline. Classification remains a blocking state
until the human operator approves reopening. The pipeline then resumes from the
reopened stage and advances through the normal gate sequence.

## Implementation Plan Maintenance

`docs/implementation-plan.md` is the review baseline for implementation work.
The coding agent, code review agent, and test review agent evaluate active
phase work against that document. When development changes the agreed phase
scope, sequence, acceptance criteria, required tests, dependency order, or
documentation impact, the plan is updated before review continues.

This rule supports iterative development without falling back into waterfall.
Requirements and design can evolve, and implementation discoveries can refine
the phase plan. The pipeline keeps those refinements explicit so reviewers
evaluate code against a current artifact instead of an outdated discussion.

The orchestrator distinguishes plan drift from ordinary implementation detail.
Small choices that stay inside the active phase scope are recorded in review
comments or commits. Changes that alter what the phase means require a
`docs/implementation-plan.md` update, approval, and a new plan snapshot.

Implementation-plan maintenance adds these checks:

- Code review blocks when the active phase is not described by the current
  implementation plan.
- Test review blocks when required tests or acceptance criteria have changed
  but the implementation plan has not.
- Commit blocks when accepted phase-scope changes are not reflected in the
  implementation plan.
- Change control reopens Stage 5 for plan-only changes.

## Agent Prompt Contracts

Every agent invocation receives a role prompt, a context bundle, and a response
contract.

Review agents return structured issue records. Coding agents return a summary
of changed files, tests run, and unresolved blockers. Validation testing returns
a validation report plus validation review issues. Documentation review returns
documentation issues and any edited documentation files.

The orchestrator rejects malformed agent output. The failing response is stored
as an activity event, and the stage remains blocked until the response is fixed
or manually waived.

## Stage Implementation Phases

### Phase 0. Repository Foundation

Requirements: REQ-1, REQ-14
Paths: README.md, electroboy, ai-pipeline, pyproject.toml
Paths: src/electroboy
Paths: tests

Create the package skeleton, test harness, formatter configuration, CLI entry
point, project-environment commands, and terminal presentation dependency.

Scope:

- Add `pyproject.toml`.
- Add the `rich` dependency for stage indicators and progress output.
- Add `src/electroboy/`.
- Add `tests/`.
- Add basic CLI command parsing.
- Add `electroboy new <path>`.
- Add GitHub-ready repository initialization for new projects.
- Add `ai-pipeline` as an alias for the same CLI entrypoint.
- Add activation-script template generation.
- Add `electroboy deactivate` shell-wrapper contract.
- Add README setup placeholders if needed.

Acceptance criteria:

- `PYTHONPATH=src python -m electroboy --help` or the configured console
  script runs.
- `electroboy new <path>` creates a project directory and git repository.
- New repositories include GitHub-oriented defaults for collaboration.
- `./electroboy --help` and `./ai-pipeline --help` expose the same command set.
- `<path>/bin/activate` sets project context for the active shell.
- The activation script does not define bare `deactivate`.
- `electroboy deactivate` restores pipeline-owned shell state.
- Unit tests run locally.
- The package imports without side effects.

### Phase 1. Artifact Templates

Requirements: REQ-3, REQ-5
Paths: src/electroboy/artifacts.py
Paths: tests/test_artifacts.py

Create templates for the core pipeline artifacts.

Scope:

- Add template generation for `docs/requirements.md`.
- Add template generation for `docs/detailed-design.md`.
- Add template generation for `docs/implementation-plan.md`.
- Add template generation for `docs/api.md`.
- Add artifact snapshot helpers.

Acceptance criteria:

- Missing artifact files can be initialized without overwriting existing files.
- Approved artifacts can be copied into a run artifact directory.
- Snapshot events include artifact path, snapshot path, checksum, and event id.

### Phase 2. State Store

Requirements: REQ-4, REQ-5, REQ-13, REQ-14
Paths: src/electroboy/state_store.py
Paths: src/electroboy/models.py
Paths: tests/test_state_store.py

Implement durable JSON and JSONL state handling.

Scope:

- Create run directories.
- Write `manifest.json`.
- Append `activity-log.jsonl`.
- Append review issue files.
- Append `change-requests.jsonl`.
- Append approval and baseline invalidation records.
- Write `phase-status.json`.
- Append `decisions.jsonl`.
- Store message files and raw runtime streams.
- Enforce shared state and local state separation.
- Generate `.gitignore` entries for `.electroboy/local/`.

Acceptance criteria:

- Appends are atomic enough for local use.
- JSONL files remain valid after repeated writes.
- Review issue lifecycle transitions are append-only.
- State can be loaded after process restart.
- Secret values are redacted before state is written.
- Change-control records can be loaded and linked to activity events.
- Shared state can be committed to git without local session data.
- Local state is ignored and can be rebuilt when safe.

### Phase 3. Gate Engine

Requirements: REQ-1, REQ-2, REQ-3, REQ-5, REQ-9
Paths: src/electroboy/gates.py
Paths: src/electroboy/models.py
Paths: tests/test_gates.py

Implement deterministic gate checks.

Scope:

- Requirements gate.
- Stage order gate.
- Change-control gate.
- Implementation-plan currency gate.
- Earlier-stage iteration gate.
- Design gate.
- Human design acceptance gate.
- Implementation gate.
- Code review gate.
- Phase test review gate.
- Commit gate.
- Validation testing gate.
- Documentation gate.

Acceptance criteria:

- Each gate returns pass, fail, or blocked.
- Gate failures include concrete missing conditions.
- Gate results are written to the activity log.
- Gates verify approvals, current snapshots, and structured traceability.
- Unit tests cover pass and fail cases.
- Tests prove that later stages cannot start before predecessor gates pass.
- Tests prove that active-stage commands resume the current stage.
- Tests prove that earlier-stage commands create change-control iterations.
- Tests prove that reopened baselines invalidate downstream gates.
- Tests prove that phase-scope changes block review until the plan is updated.

### Phase 4. Runtime Adapter Interface

Requirements: REQ-6, REQ-7
Paths: src/electroboy/runtime.py, src/electroboy/config.py
Paths: src/electroboy/adapters
Paths: tests/test_runtime_config.py

Implement the adapter boundary that lets the orchestrator call agents without
knowing whether the agent is manual, Codex-backed, Claude-backed, SDK-backed,
or implemented by another CLI runtime.

Scope:

- Define `AgentRuntime`.
- Define `AgentInvocation`.
- Define `AgentResult`.
- Define `RuntimeConfig`.
- Add manual adapter.
- Add generic CLI adapter.
- Add Codex exec adapter stub.
- Add runtime selection by role.
- Add redaction before durable storage.

Acceptance criteria:

- Manual adapter can complete a stage from a response file.
- Generic CLI adapter can invoke a configured command.
- Runtime errors are represented as activity events.
- Runtime invocation failures return normalized `AgentResult` values.
- The orchestrator can swap adapters through configuration.

### Phase 5. CLI Runtime Adapters

Requirements: REQ-5, REQ-6, REQ-7
Paths: src/electroboy/adapters
Paths: src/electroboy/cli.py
Paths: tests/test_runtime_adapters.py

Implement automated agent invocation through the generic CLI adapter and the
default Codex exec adapter.

Scope:

- Build prompts from role, stage, and context bundle.
- Invoke the configured CLI for each role.
- Invoke Codex in read-only or workspace-write sandbox mode when Codex is
  selected.
- Capture stdout, stderr, exit status, and structured runtime events when
  available.
- Extract final response.
- Use runtime-specific structured output support when practical.
- Store prompt, response, and redacted raw events.
- Parse structured output into review issues or stage results.

Acceptance criteria:

- Design review can run through the configured default runtime.
- Codex can run through `codex exec --json` and produce issue JSONL.
- Codex sandbox mode is explicit for review and write roles.
- A second CLI runtime can be configured through the generic adapter.
- Structured outputs conform to the expected response schema.
- Coding-agent turns can run with workspace-write permission.
- Review-agent turns run read-only.
- Failures leave the stage resumable.

### Phase 6. Requirements And Design Loops

Requirements: REQ-1, REQ-2, REQ-3, REQ-4, REQ-5
Paths: src/electroboy/cli.py
Paths: tests/test_cli.py, tests/test_design_loop.py

Implement the human and Design Author Agent requirements and design stages.

Scope:

- Add `electroboy requirements`.
- Add `electroboy requirements-approve`.
- Add `electroboy design`.
- Add `electroboy design-review`.
- Add `electroboy design-approve`.
- Invoke the configured Design Author Agent for interactive authoring.
- Rebuild authoring context from artifacts and shared run state.
- Requirements definition stage.
- Human-led design exploration stage.
- Automated design review stage.
- Human design acceptance stage.
- Artifact snapshots for requirements and design.
- Review issue iteration.

Acceptance criteria:

- Requirements and design commands can resume without a provider session id.
- Requirements approval is recorded before formal design review.
- Required approvals are explicit state records, not inferred from files.
- Design commands fail before the requirements gate passes.
- Design review checks against approved requirements.
- Human design acceptance blocks implementation planning.
- Approved requirements and design snapshots are stored.

### Phase 7. Implementation Planning

Requirements: REQ-2, REQ-3, REQ-5, REQ-9
Paths: src/electroboy/planning.py
Paths: src/electroboy/cli.py
Paths: tests/test_plan.py

Implement collaborative implementation-plan generation and approval.

Scope:

- Add `electroboy implementation-plan`.
- Add `electroboy plan-approve`.
- Invoke the configured Design Author Agent with the approved requirements and
  reviewed design context.
- Generate or update `docs/implementation-plan.md`.
- Track human approval.
- Track Design Author Agent confirmation.
- Verify phase-to-requirement traceability.
- Support plan updates discovered during implementation.
- Snapshot the approved plan.

Acceptance criteria:

- Implementation-plan authoring can resume from artifacts and shared state.
- Coding cannot start until the implementation gate passes.
- Planning cannot start until human design acceptance passes.
- Every phase references relevant requirements.
- Traceability is parsed from phase `Requirements:` lines and checked against
  requirement ids from `docs/requirements.md`.
- Phase scope is parsed from one or more `Paths:` lines under each phase.
- The human operator sees and approves the phase plan.
- Plan changes discovered during development are recorded before review
  continues.
- The activity log records plan approval and snapshot events.

### Phase 8. Phase Implementation Loop

Requirements: REQ-4, REQ-5, REQ-8, REQ-9
Paths: src/electroboy/cli.py
Paths: src/electroboy/gates.py
Paths: tests/test_phase_loop.py

Implement one-phase-at-a-time coding, review, test review, and commit flow.

Scope:

- Add `electroboy code`.
- Add `electroboy code --phased` for explicit one-phase checkpoint mode.
- Start active phase.
- Invoke coding agent.
- Invoke code review agent.
- Iterate until code review passes.
- Invoke phase test review agent.
- Iterate until phase test review passes.
- Detect active-phase drift from `docs/implementation-plan.md`.
- Create and record the verified phase commit by default.
- Preserve manual commit recording through phased mode.
- Update `phase-status.json`.
- Persist checkpoints before and after each agent turn.
- Render stage, phase, review, test, and escalation progress with Rich.

Acceptance criteria:

- `electroboy code` resumes after interruption from the last durable
  checkpoint.
- `electroboy code` automates every remaining planned phase by default.
- `electroboy code --phased` runs only the active phase and waits for manual
  commit recording.
- Each phase records an independent git commit before the next phase starts.
- A new phase cannot start while another phase is active.
- Phase review and test review can update only the active phase.
- Phase commits require an existing git commit SHA reachable from `HEAD`.
- Phase commit messages identify the active phase and objective.
- Phase commit changed paths must match the planned phase `Paths:` metadata.
- Phase commits require code review and test review agent evidence.
- Manual review and test flags do not replace agent invocation evidence.
- Code review and phase test review issues block commits.
- Phase-scope drift clears review evidence and blocks commit until the plan is
  updated and review agents run again.
- Test commands and outputs are stored in the activity log.
- Phase changes are limited to the active phase scope.
- Rich output clearly identifies the active stage, active phase, blocking
  issue, next agent, and resume checkpoint.

### Phase 9. Validation Testing

Requirements: REQ-5, REQ-10, REQ-11
Paths: src/electroboy/cli.py
Paths: tests/test_validation.py

Implement final validation of the completed codebase.

Scope:

- Run the full test suite.
- Run validation commands defined by the requirements and design.
- Check end-to-end workflows.
- Check integrated behavior against `docs/requirements.md`.
- Check architecture and behavior against `docs/detailed-design.md`.
- Write `validation-review.jsonl`.
- Write `validation-report.md`.

Acceptance criteria:

- Final documentation review cannot start until validation passes.
- Validation does not pass while blocker or major validation issues remain.
- Validation commands run as argument vectors unless explicit shell mode is
  requested.
- Validation issues return work to the coding agent.
- Validation fixes go through code review and phase test review.
- Validation failures open a validation-fix phase and return the active stage
  to implementation.
- The configured full test-suite command always runs and fails closed when the
  suite cannot be run.
- Validation report is stored as a run artifact.

### Phase 10. Documentation Review

Requirements: REQ-5, REQ-12
Paths: src/electroboy/cli.py
Paths: tests/test_documentation_review.py
Paths: README.md, docs/api.md

Implement final documentation verification.

Scope:

- Add `electroboy document`.
- Add `electroboy code-approve`.
- Verify `docs/requirements.md`.
- Verify `docs/detailed-design.md`.
- Verify `README.md`.
- Verify `docs/api.md`.
- Store documentation review issues.
- Snapshot final documentation artifacts.

Acceptance criteria:

- Documentation gate passes only after validation passes.
- `document` can be run repeatedly while the documentation gate is active.
- `code-approve` passes only after documentation review passes.
- Final human completion approval is recorded in `approvals.jsonl`.
- Public API documentation matches code.
- Generated missing-file issues are verified automatically after the file is
  restored.
- Requirements documentation matches implemented behavior.
- README can be followed by a new contributor.

### Phase 11. Change Control And Iteration

Requirements: REQ-5, REQ-13
Paths: src/electroboy/cli.py
Paths: tests/test_change_control.py

Implement controlled reopening of requirements, design, planning, or
implementation work.

Scope:

- Open change-control requests from earlier-stage commands.
- Classify the earliest affected baseline.
- Record human approval for reopening earlier stages.
- Invalidate downstream gates and artifact snapshots.
- Reopen the affected stage.
- Resume the ordered pipeline from the reopened stage.

Acceptance criteria:

- `requirements --reason`, `design --reason`, `implementation-plan --reason`,
  `code --reason`, and `document --reason` can reopen completed or later-stage
  work.
- Completed runs can reopen requirements or design through change control.
- Later-stage findings can reopen the earliest affected baseline.
- Reopen requires classification and human approval.
- Invalidated gates no longer authorize later stages.
- Invalidated artifact snapshots are recorded explicitly.
- The activity log explains why the pipeline moved backward.
- The run history remains append-only.

### Phase 12. Resume And Reporting

Requirements: REQ-5, REQ-14
Paths: src/electroboy/cli.py
Paths: tests/test_reporting.py

Implement restart-safe resume behavior and human-readable reporting.

Scope:

- Print activation status and next command from `<project>/bin/activate`.
- Resume from run manifest and phase status.
- Report blocked gates.
- Report open change-control requests.
- Report open issues by severity.
- Generate a run summary.
- Generate a trace report from the activity log.

Acceptance criteria:

- The pipeline can resume after interruption.
- Reactivating a project reports the active stage and next useful command.
- Reports explain what happened and why the current state is blocked or ready.
- Reports show invalidated gates and the active reopened stage.
- Reports include decisions, phase commits, snapshots, and baseline
  invalidations.
- Run history can reconstruct agent steps and decisions.

## Recommended Initial Milestone

The initial useful milestone is a local, single-repo prototype:

1. Create a project with `electroboy new <path>`.
2. Activate it with `source <path>/bin/activate`.
3. Run interactive requirements and design stages through the configured
   Design Author Agent.
4. Verify that implementation commands fail before requirements and design
   gates pass.
5. Run automated design review through the configured default runtime.
6. Record issues and activity events in shared state.
7. Approve design and implementation plan manually.
8. Run one small implementation phase through the coding, review, and test
   loop.
9. Interrupt `electroboy code` and verify that it resumes after activation.
10. Run `electroboy document` after validation testing passes.
11. Reopen requirements with `electroboy requirements --reason <text>`.
12. Verify downstream gate invalidation.

This milestone proves the hard parts of the process without requiring a full
dashboard, cloud execution, or direct provider API integration.

## Provider API Alternative

The pipeline can be implemented directly against provider APIs, but that is a
larger project. A direct API implementation must provide its own tool
execution, filesystem access control, shell command policy, git integration,
streaming event capture, and review-output validation.

That path is useful after the CLI-based prototype proves the process and the
project needs tighter control than configured CLI adapters provide.

## Security Requirements

- Never write API keys or access tokens to logs, prompts, state files, review
  issues, or reports.
- Redact known secret environment variables before storing command context.
- Use read-only sandbox mode for review agents.
- Use workspace-write only for coding and documentation fix turns.
- Keep full-access execution outside the baseline design.
- Treat saved CLI authentication files as secrets.
- Store CI credentials in the CI secret store.
- Pass runtime credentials only to the process that needs them.
- Runtime subprocesses receive only the configured environment allowlist.
- Do not set provider API keys as job-level environment variables in jobs that
  run repository-controlled code.

## Verification Commands

Baseline verification commands:

```bash
python -m unittest discover -s tests
PYTHONPATH=src python -m electroboy --help
electroboy new /tmp/example-pipeline-project
source /tmp/example-pipeline-project/bin/activate
electroboy status
electroboy requirements
electroboy requirements-approve
electroboy design
electroboy code
electroboy document
electroboy deactivate
```

Provider-specific invocation details can change as adapters mature. The
workflow requirements remain stable: unit tests must pass, the CLI must load,
state must round-trip, stage gates must report clear pass or fail results, and
blocked forward movement must produce actionable errors.

## Open Implementation Decisions

- Whether the package is named `electroboy`, `agent_pipeline`, or something
  project-specific.
- Whether to use Pydantic or standard-library dataclasses for state models.
- Whether `validation-report.md` is written by the Test Review Agent or by the
  orchestrator from validation events.
- How detailed downstream invalidation reporting should be.
- Which agent CLI runtimes are supported by the initial generic adapter.
- Whether runtime selection is global, per stage, per role, or per invocation.
- Whether the Codex SDK adapter is implemented before or after the initial
  end-to-end run.
