# AI Agent Pipeline Implementation Plan

## Table of Contents

- [Purpose](#purpose)
- [Recommendation](#recommendation)
- [Implementation Choice](#implementation-choice)
- [Codex And API Keys](#codex-and-api-keys)
- [Runtime Strategy](#runtime-strategy)
  - [Manual Adapter](#manual-adapter)
  - [Codex Exec Adapter](#codex-exec-adapter)
  - [Codex SDK Adapter](#codex-sdk-adapter)
- [Non-Goals](#non-goals)
- [Repository Layout](#repository-layout)
- [State And Artifact Storage](#state-and-artifact-storage)
- [Data Models](#data-models)
- [CLI Shape](#cli-shape)
- [Agent Prompt Contracts](#agent-prompt-contracts)
- [Stage Implementation Phases](#stage-implementation-phases)
- [Recommended Initial Milestone](#recommended-initial-milestone)
- [Raw API Alternative](#raw-api-alternative)
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
adapters. The automated adapter uses Codex through `codex exec --json`. This
keeps the orchestrator small while relying on Codex for coding, repository
inspection, review, command execution, sandboxing, and final
responses.

## Recommendation

Use a Python CLI to define the loops, gates, state files, and artifact
snapshots. Use Codex as the agent runtime through `codex exec --json`.

This approach keeps process control deterministic while using Codex for the
work that benefits from an agent: reading the repository, editing files,
running commands, reviewing diffs, and explaining results.

Direct OpenAI API usage is an extension path, not the starting point. A direct
API implementation would have to recreate shell execution, filesystem policy,
git integration, sandboxing, streaming events, and structured review handling.
Codex already provides those primitives for local software work.

## Implementation Choice

The pipeline needs two separate capabilities.

The orchestrator controls process state. It knows which stage is active, which
artifact is approved, which issues remain open, which gate is blocked, and what
event must be written to the activity log. This behavior belongs in ordinary
deterministic code.

The agents perform reasoning and code work. They review prose, inspect diffs,
write code, propose tests, run commands, and summarize results. This behavior
belongs in Codex or another agent runtime.

The selected implementation uses Python for orchestration and Codex for agent
execution.

## Codex And API Keys

Using Codex is enough for the baseline implementation when the pipeline runs on
a developer workstation or trusted private runner. Codex already provides a
coding-oriented agent surface, workspace access, shell execution, sandbox
settings, and non-interactive execution through `codex exec`.

An API key is needed only when the selected Codex authentication path requires
one. Codex can authenticate through ChatGPT sign-in or through an API key.
For local interactive use, saved Codex authentication is enough after
`codex login`. For non-interactive automation, the safer default is to pass a
scoped key only to the Codex invocation that needs it.

Codex supports `CODEX_API_KEY` for `codex exec`. The orchestrator treats that
variable as an invocation-time credential, not as repository configuration.

The implementation must never store API keys in repository files,
`.agent-pipeline/`, prompts, logs, activity events, review issues, or generated
reports. Environment snapshots written by the orchestrator must redact known
secret variables.

Recommended authentication model:

- Developer workstation: use `codex login` and saved local Codex credentials.
- Local scripted automation: use saved Codex auth or pass `CODEX_API_KEY` only
  to the single `codex exec` process.
- CI or shared runners: use a dedicated secret store and pass credentials only
  to the isolated Codex step.
- Public or untrusted repositories: do not expose API keys to jobs that execute
  repository-controlled code.

A local prototype only needs Codex installed and authenticated. No repository
file should contain a secret value.

## Runtime Strategy

The orchestrator supports three runtime adapters.

### Manual Adapter

The manual adapter writes role prompts and expected response schemas into the
run directory. A human runs the desired agent manually and stores the response
file where the orchestrator expects it.

This adapter is useful for bootstrap work and for debugging prompt design.
It requires no programmatic model calls from the orchestrator.

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
the manual and Codex exec adapters.

## Non-Goals

- The baseline does not call the raw OpenAI API directly.
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
stage logic, state persistence, prompt construction, and runtime adapters
separate.

## State And Artifact Storage

The orchestrator stores run state under `.agent-pipeline/`.

```text
.agent-pipeline/
  runs/
    <run-id>/
      manifest.json
      activity-log.jsonl
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
ai-pipeline resume
```

The CLI is intentionally explicit. Each command performs one stage transition,
agent invocation, or gate check. This makes failures easier to inspect and
resume.

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
- Write `phase-status.json`.
- Append `decisions.jsonl`.
- Store message files and raw runtime streams.

Acceptance criteria:

- Appends are atomic enough for local use.
- JSONL files remain valid after repeated writes.
- State can be loaded after process restart.
- Secret values are redacted before state is written.

### Phase 3. Gate Engine

Implement deterministic gate checks.

Scope:

- Requirements gate.
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

### Phase 4. Runtime Adapter Interface

Implement the adapter boundary that lets the orchestrator call agents without
knowing whether the agent is manual, Codex CLI, or SDK-backed.

Scope:

- Define `AgentRuntime`.
- Define `AgentInvocation`.
- Define `AgentResult`.
- Add manual adapter.
- Add Codex exec adapter stub.
- Add redaction before durable storage.

Acceptance criteria:

- Manual adapter can complete a stage from a response file.
- Runtime errors are represented as activity events.
- The orchestrator can swap adapters through configuration.

### Phase 5. Codex Exec Adapter

Implement automated agent invocation with `codex exec --json`.

Scope:

- Build prompts from role, stage, and context bundle.
- Invoke Codex in read-only or workspace-write sandbox mode.
- Capture JSONL events.
- Extract final response.
- Use `--output-schema` for structured review and gate outputs when practical.
- Store prompt, response, and redacted raw events.
- Parse structured output into review issues or stage results.

Acceptance criteria:

- Design review can run through Codex and produce issue JSONL.
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

### Phase 11. Resume And Reporting

Implement restart-safe resume behavior and human-readable reporting.

Scope:

- Resume from run manifest and phase status.
- Report blocked gates.
- Report open issues by severity.
- Generate a run summary.
- Generate a trace report from the activity log.

Acceptance criteria:

- The pipeline can resume after interruption.
- Reports explain what happened and why the current state is blocked or ready.
- Run history can reconstruct agent steps and decisions.

## Recommended Initial Milestone

The initial useful milestone is a local, single-repo prototype:

1. Initialize state.
2. Run manual requirements and design stages.
3. Run automated design review through `codex exec`.
4. Record issues and activity events.
5. Approve design and implementation plan manually.
6. Run one small implementation phase through the coding, review, and test
   loop.

This milestone proves the hard parts of the process without requiring a full
dashboard, cloud execution, or raw API integration.

## Raw API Alternative

The pipeline can be implemented directly against the OpenAI API, but that is a
larger project. A raw API implementation must provide its own tool execution,
filesystem access control, shell command policy, git integration, streaming
event capture, and review-output validation.

That path is useful only after the Codex-based prototype proves the process and
the project needs tighter control than `codex exec` or the Codex SDK provides.

## Security Requirements

- Never write API keys or access tokens to logs, prompts, state files, review
  issues, or reports.
- Redact known secret environment variables before storing command context.
- Use read-only sandbox mode for review agents.
- Use workspace-write only for coding and documentation fix turns.
- Keep full-access execution outside the baseline design.
- Treat `~/.codex/auth.json` as a secret if saved Codex auth is used.
- Store CI credentials in the CI secret store.
- Pass `CODEX_API_KEY` only to the process that needs it.
- Do not set `OPENAI_API_KEY` or `CODEX_API_KEY` as a job-level environment
  variable in jobs that run repository-controlled code.

## Verification Commands

Baseline verification commands:

```bash
python -m pytest
python -m ai_pipeline --help
python -m ai_pipeline status
python -m ai_pipeline gate requirements
python -m ai_pipeline gate implementation
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
- Whether the Codex SDK adapter is implemented before or after the initial
  end-to-end run.
