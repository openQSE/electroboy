# AI Agent Pipeline Implementation Plan

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
- [Data Models](#data-models)
- [CLI Shape](#cli-shape)
- [Flow Enforcement](#flow-enforcement)
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
design_review = "codex"
coding = "codex"
code_review = "claude"
test_review = "codex"
documentation = "codex"
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
`.agent-pipeline/`, prompts, logs, activity events, review issues, or generated
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
src/ai_pipeline/
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

The orchestrator stores run state under `.agent-pipeline/`.

```text
.agent-pipeline/
  runs/
    <run-id>/
      manifest.json
      activity-log.jsonl
      change-requests.jsonl
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
      raw/
        <event-id>.jsonl
  phase-status.json
  decisions.jsonl
```

Working artifacts remain in their normal repository paths. Approved snapshots
are copied into `artifacts/` at gate boundaries. Review comments and findings
are written as JSONL issue records. Agent prompts and full textual responses
are stored in `messages/`. Optional raw runtime streams are stored in `raw/`
after redaction.

Change-control requests are stored in `change-requests.jsonl`. Each request
records the reason for reopening earlier work, the earliest affected baseline,
the downstream gates that were invalidated, and the stage where the pipeline
resumes.

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

The baseline CLI exposes commands that match the pipeline stages.

```text
ai-pipeline init
ai-pipeline status
ai-pipeline stage requirements
ai-pipeline stage design
ai-pipeline stage design-review
ai-pipeline stage design-acceptance
ai-pipeline stage plan
ai-pipeline phase start <n>
ai-pipeline phase review <n>
ai-pipeline phase test <n>
ai-pipeline phase commit <n>
ai-pipeline validate
ai-pipeline docs-review
ai-pipeline gate <name>
ai-pipeline change open
ai-pipeline change classify <id>
ai-pipeline change reopen <id>
ai-pipeline change status
ai-pipeline resume
```

The CLI is intentionally explicit. Each command performs one stage transition,
agent invocation, or gate check. This makes failures easier to inspect and
resume.

## Flow Enforcement

The CLI enforces the pipeline as an ordered state machine. A mutating command
loads the run manifest, checks the active stage, evaluates predecessor gates,
and refuses to run when the requested action would skip required requirements,
design, planning, validation, or documentation work.

Read-only commands can inspect any run state. Mutating commands are accepted
only when they match the active stage or a valid change-control transition.
The orchestrator records every accepted transition in `activity-log.jsonl`.

The gate engine owns these decisions:

- Starting a run is valid only at requirements definition.
- Design work requires an approved requirements baseline.
- Implementation planning requires human acceptance of reviewed design.
- Phase implementation requires an approved implementation plan.
- Validation testing requires all planned phases to be committed.
- Final documentation review requires validation testing to pass.
- Reopening an earlier baseline requires a change-control request.

Change-control commands classify the earliest affected baseline and invalidate
downstream gates that depended on the old baseline. The pipeline then resumes
from the reopened stage and advances through the normal gate sequence.

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

Create the package skeleton, test harness, formatter configuration, and CLI
entry point.

Scope:

- Add `pyproject.toml`.
- Add `src/ai_pipeline/`.
- Add `tests/`.
- Add basic CLI command parsing.
- Add README setup placeholders if needed.

Acceptance criteria:

- `python -m ai_pipeline --help` or the configured console script runs.
- Unit tests run locally.
- The package imports without side effects.

### Phase 1. Artifact Templates

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

Implement durable JSON and JSONL state handling.

Scope:

- Create run directories.
- Write `manifest.json`.
- Append `activity-log.jsonl`.
- Append review issue files.
- Append `change-requests.jsonl`.
- Write `phase-status.json`.
- Append `decisions.jsonl`.
- Store message files and raw runtime streams.

Acceptance criteria:

- Appends are atomic enough for local use.
- JSONL files remain valid after repeated writes.
- State can be loaded after process restart.
- Secret values are redacted before state is written.
- Change-control records can be loaded and linked to activity events.

### Phase 3. Gate Engine

Implement deterministic gate checks.

Scope:

- Requirements gate.
- Stage order gate.
- Change-control gate.
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
- Unit tests cover pass and fail cases.
- Tests prove that later stages cannot start before predecessor gates pass.
- Tests prove that reopened baselines invalidate downstream gates.

### Phase 4. Runtime Adapter Interface

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
- The orchestrator can swap adapters through configuration.

### Phase 5. CLI Runtime Adapters

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
- A second CLI runtime can be configured through the generic adapter.
- Structured outputs conform to the expected response schema.
- Coding-agent turns can run with workspace-write permission.
- Review-agent turns run read-only.
- Failures leave the stage resumable.

### Phase 6. Requirements And Design Loops

Implement the human/ElectroBoy requirements and design stages.

Scope:

- Requirements definition stage.
- Human-led design exploration stage.
- Automated design review stage.
- Human design acceptance stage.
- Artifact snapshots for requirements and design.
- Review issue iteration.

Acceptance criteria:

- Requirements approval is recorded before formal design review.
- Design commands fail before the requirements gate passes.
- Design review checks against approved requirements.
- Human design acceptance blocks implementation planning.
- Approved requirements and design snapshots are stored.

### Phase 7. Implementation Planning

Implement collaborative implementation-plan generation and approval.

Scope:

- Generate or update `docs/implementation-plan.md`.
- Track human approval.
- Track Design Author Agent confirmation.
- Verify phase-to-requirement traceability.
- Snapshot the approved plan.

Acceptance criteria:

- Coding cannot start until the implementation gate passes.
- Planning cannot start until human design acceptance passes.
- Every phase references relevant requirements.
- The human operator sees and approves the phase plan.
- The activity log records plan approval and snapshot events.

### Phase 8. Phase Implementation Loop

Implement one-phase-at-a-time coding, review, test review, and commit flow.

Scope:

- Start active phase.
- Invoke coding agent.
- Invoke code review agent.
- Iterate until code review passes.
- Invoke phase test review agent.
- Iterate until phase test review passes.
- Commit verified phase.
- Update `phase-status.json`.

Acceptance criteria:

- Each phase is committed independently.
- Code review and phase test review issues block commits.
- Test commands and outputs are stored in the activity log.
- Phase changes are limited to the active phase scope.

### Phase 9. Validation Testing

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
- Validation issues return work to the coding agent.
- Validation fixes go through code review and phase test review.
- Validation report is stored as a run artifact.

### Phase 10. Documentation Review

Implement final documentation verification.

Scope:

- Verify `docs/requirements.md`.
- Verify `docs/detailed-design.md`.
- Verify `README.md`.
- Verify `docs/api.md`.
- Store documentation review issues.
- Snapshot final documentation artifacts.

Acceptance criteria:

- Documentation gate passes only after validation passes.
- Public API documentation matches code.
- Requirements documentation matches implemented behavior.
- README can be followed by a new contributor.

### Phase 11. Change Control And Iteration

Implement controlled reopening of requirements, design, planning, or
implementation work.

Scope:

- Open change-control requests.
- Classify the earliest affected baseline.
- Record human approval for reopening earlier stages.
- Invalidate downstream gates and artifact snapshots.
- Reopen the affected stage.
- Resume the ordered pipeline from the reopened stage.

Acceptance criteria:

- Completed runs can reopen requirements or design through change control.
- Later-stage findings can reopen the earliest affected baseline.
- Invalidated gates no longer authorize later stages.
- The activity log explains why the pipeline moved backward.
- The run history remains append-only.

### Phase 12. Resume And Reporting

Implement restart-safe resume behavior and human-readable reporting.

Scope:

- Resume from run manifest and phase status.
- Report blocked gates.
- Report open change-control requests.
- Report open issues by severity.
- Generate a run summary.
- Generate a trace report from the activity log.

Acceptance criteria:

- The pipeline can resume after interruption.
- Reports explain what happened and why the current state is blocked or ready.
- Reports show invalidated gates and the active reopened stage.
- Run history can reconstruct agent steps and decisions.

## Recommended Initial Milestone

The initial useful milestone is a local, single-repo prototype:

1. Initialize state.
2. Run manual requirements and design stages.
3. Verify that implementation commands fail before requirements and design
   gates pass.
4. Run automated design review through the configured default runtime.
5. Record issues and activity events.
6. Approve design and implementation plan manually.
7. Run one small implementation phase through the coding, review, and test
   loop.
8. Open a sample change-control request and verify downstream gate
   invalidation.

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
- Do not set provider API keys as job-level environment variables in jobs that
  run repository-controlled code.

## Verification Commands

Baseline verification commands:

```bash
python -m pytest
python -m ai_pipeline --help
python -m ai_pipeline status
python -m ai_pipeline gate requirements
python -m ai_pipeline gate implementation
python -m ai_pipeline change status
```

The exact command names can change when the CLI implementation starts. The
requirements remain stable: unit tests must pass, the CLI must load, state must
round-trip, and gates must report clear pass or fail results.

## Open Implementation Decisions

- Whether the package is named `ai_pipeline`, `agent_pipeline`, or something
  project-specific.
- Whether to use Pydantic or standard-library dataclasses for state models.
- Whether `validation-report.md` is written by the Test Review Agent or by the
  orchestrator from validation events.
- Whether run artifact snapshots are committed to git or kept as local run
  output.
- How detailed downstream invalidation reporting should be.
- Which agent CLI runtimes are supported by the initial generic adapter.
- Whether runtime selection is global, per stage, per role, or per invocation.
- Whether the Codex SDK adapter is implemented before or after the initial
  end-to-end run.
