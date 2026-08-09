# ElectroBoy GUI Detailed Design

## Table of Contents

- [Purpose](#purpose)
- [Design Principles](#design-principles)
- [Goals](#goals)
- [Non-Goals](#non-goals)
- [User Experience](#user-experience)
- [Architecture](#architecture)
- [Service Model](#service-model)
- [Workflow Graph](#workflow-graph)
- [Interactive Agent Sessions](#interactive-agent-sessions)
- [Progress And Monitoring](#progress-and-monitoring)
- [Project And Meta-Project Support](#project-and-meta-project-support)
- [State And Persistence](#state-and-persistence)
- [API Shape](#api-shape)
- [Security And Process Boundaries](#security-and-process-boundaries)
- [Failure Handling](#failure-handling)
- [Implementation Plan](#implementation-plan)
- [Open Questions](#open-questions)

## Purpose

The ElectroBoy GUI provides a browser-based interface over the existing
orchestrator. It makes the workflow easier to see and operate without replacing
the CLI. The GUI should let an operator initialize a project, see the current
pipeline state, launch interactive or non-interactive stages, monitor progress,
interrupt running agents, and review generated artifacts from one place.

The main problem it solves is interaction quality. The Codex CLI is useful, but
it is not ideal for multi-line editing, links, attachments, progress summaries,
or workflow navigation. The GUI should provide a friendlier operator surface
while preserving the current ElectroBoy state model, command semantics, and
agent contracts.

## Design Principles

- The CLI remains supported and authoritative. Every GUI action maps to the
  same workflow concepts exposed by ElectroBoy commands.
- The GUI does not bypass gates. It calls orchestrator APIs that enforce the
  same stage, approval, force, and project-activation rules as the CLI.
- The first screen is the workflow, not a landing page. The operator should see
  the project state and next useful action immediately.
- The workflow graph drives navigation. Operators click a stage to see valid
  actions, artifacts, progress, review issues, and reset options.
- Interactive agent sessions should feel like a structured chat editor, not a
  raw terminal. Raw provider output remains available as diagnostics.
- Progress must be visible from another browser tab or shell while a long
  non-interactive phase is running.
- The GUI should be useful for both single-repository projects and meta-projects
  with multiple active repositories.

## Goals

- Run ElectroBoy as a local service with a browser UI.
- Initialize a new project or meta-project from the browser.
- Display the pipeline as an interactive top-level workflow graph.
- Show the active stage, stage command, next stage, active phase, active unit,
  gates, open issues, and registered repositories.
- Start public workflow commands from the graph, including forced resets through
  `<command> --force` semantics.
- Launch interactive agents from the browser with a multi-line input editor,
  attachment references, link insertion, and an interrupt button.
- Stream concise progress from non-interactive agents.
- Show generated Markdown artifacts and review reports in readable panes.
- Preserve the existing CLI workflow so operators can move between browser and
  terminal without losing state.

## Non-Goals

- Do not remove or replace the CLI.
- Do not create a separate workflow engine.
- Do not make the browser directly manipulate `.electroboy` state files.
- Do not require a hosted cloud service for the first implementation.
- Do not implement a full IDE. Source editing should remain in the user's
  editor, while the GUI coordinates workflow, prompts, progress, and artifacts.
- Do not expose raw Codex terminal control as the primary interaction model.

## User Experience

### Initial Screen

When the GUI opens without an active project, it shows a compact setup view:

- New project path input.
- Meta-project init path input.
- Existing project path input.
- Recent project list when available.
- Runtime health summary showing whether the configured agent runtime is found.

Creating or opening a project immediately transitions to the workflow screen.

### Workflow Screen

The primary screen has three persistent regions:

1. Workflow graph at the top.
2. Main work area below the graph.
3. Progress/activity side pane.

The workflow graph shows the command-aligned stages:

- `requirements`
- `requirements-approve`
- `design`
- `design-review`
- `design-approve`
- `implementation-plan`
- `plan-approve`
- `code`
- `test-plan`
- `test-plan-approve`
- `validate`
- `validation-approve`
- `document`
- `code-approve`

Each node shows its state:

- active
- blocked
- complete
- invalidated
- available by force
- running
- failed

Clicking a node opens a stage panel with:

- Current status and blocking reasons.
- Primary action, such as `Run requirements` or `Approve design`.
- Secondary actions, such as `Run interactive`, `Run with --force`, or
  `Open artifact`.
- Relevant artifacts.
- Related review reports.
- Gate and approval status.

### Interactive Agent Layout

When the operator launches an interactive stage, the bottom work area becomes an
agent session:

- Multi-line prompt editor with normal `Shift+Enter` behavior.
- Send button.
- Interrupt button.
- Attachment button.
- Link insertion control.
- Context chips showing which artifacts will be passed to the agent.
- Agent response pane with Markdown rendering.
- Optional raw output tab for diagnostics.

The primary response pane should be readable and structured. It should not be a
raw terminal transcript by default. Raw provider output remains accessible for
debugging agent runtime problems.

### Progress Pane

The progress pane mirrors `electroboy progress`:

- Current running role.
- Progress message from the role-specific progress file.
- Prominent issue announcements, for example:
  `ISSUE FOUND - MAJOR - <summary>`.
- Last activity event.
- Links to generated review/report files.
- Current command and process state.

The progress pane can follow a long-running command started from the GUI or
from another shell.

## Architecture

The GUI has three layers:

```text
Browser UI
  |
  | HTTP + WebSocket/SSE
  v
ElectroBoy Service
  |
  | Python API calls into orchestrator modules
  v
Existing ElectroBoy State, Runtime, And Agent Adapters
```

The service should import ElectroBoy modules directly instead of shelling out
for every command. A thin CLI-compatible command runner can still be useful for
early implementation and regression testing, but the long-term service boundary
should call the same internal functions used by the CLI.

The browser should be a local web app served by the ElectroBoy service. The
first implementation should prefer a small stack:

- Python service using FastAPI or Starlette.
- Server-sent events or WebSocket for progress and agent streams.
- React or a similarly small component-based frontend.
- Plain Markdown rendering for artifacts.

The service owns process management. The browser sends user intent; it does not
spawn agents directly.

## Service Model

The service runs in a project or meta-project context:

```bash
electroboy serve
```

Optional parameters:

```bash
electroboy serve --root /path/to/project
electroboy serve --host 127.0.0.1 --port 8765
```

The service should:

- Resolve the active project the same way the CLI does.
- Load the manifest, phase status, activity log, review issues, and repository
  registry.
- Expose read APIs for status, graph state, artifacts, issues, and progress.
- Expose mutating APIs for workflow actions.
- Manage interactive and non-interactive agent child processes.
- Record interrupts, failures, and completed sessions in existing activity
  logs.

The service must not keep the only copy of state in memory. Durable state stays
in `.electroboy/shared` and `.electroboy/local` so CLI and GUI can interoperate.

## Workflow Graph

The workflow graph is derived from the current manifest and known public
workflow commands. It should not hard-code stale state. The service computes a
graph response that includes:

- Nodes.
- Edges.
- Active stage.
- Current command for the active stage.
- Next stage.
- Gate state.
- Invalidated gates.
- Blocking messages.
- Force availability.

The graph should represent approval commands as first-class nodes because they
are operator actions. For example, after `implementation-plan`, the expected
next stage is `plan-approve`, not `code`.

Click behavior:

- Clicking the active stage shows the normal run/resume action.
- Clicking an earlier stage shows change-control actions and optional force.
- Clicking a later blocked stage shows blocking predecessor gates.
- Clicking any stage shows artifacts and history for that stage.

Forced movement uses command-level force only:

```text
requirements --force
design --force
design-review --force
implementation-plan --force
code --force
test-plan --force
validate --force
document --force
```

There is no GUI action corresponding to a low-level `stage` command.

## Interactive Agent Sessions

Interactive sessions are browser-mediated agent processes.

The service creates a session record with:

- Session id.
- Project root.
- Run id.
- Stage.
- Role.
- Artifact context.
- Started timestamp.
- Provider runtime.
- Process id when applicable.
- Status.

Input flow:

1. Operator types a message in the browser editor.
2. Browser sends the message and attachment references to the service.
3. Service writes the message to the agent process or starts a new provider
   session.
4. Service streams agent output back as structured chunks.
5. Browser renders agent output in the response pane.
6. Service records session summaries and provider session ids using existing
   ElectroBoy session files.

Attachments should be copied into a run-local ignored directory:

```text
.electroboy/local/uploads/<run-id>/<session-id>/
```

The prompt should reference attachments by path. Attachments are not promoted
to official docs unless the operator or agent explicitly updates project
artifacts.

The interrupt button sends an interrupt signal to the active provider process.
For Codex CLI runtimes this should first send `SIGINT`. If the process does not
exit after a grace period, the service can offer a stronger termination action.
Every interrupt is recorded as an activity event.

### Follow-Up Coding

When all planned implementation phases are committed, the GUI should still let
the operator open interactive coding:

```text
code --interactive --force
```

The session is labeled as follow-up implementation. It should not create a fake
phase. The prompt tells the coding agent that all planned phases are already
recorded as committed and that the work is operator-directed follow-up.

## Progress And Monitoring

The GUI progress stream should combine:

- The current role progress file.
- Activity log tail.
- Review issue records.
- Running process state.
- Generated artifact paths.

The service should expose one progress stream per active project:

```text
GET /api/projects/{project_id}/progress
```

For browser streaming, use WebSocket or server-sent events:

```text
GET /api/projects/{project_id}/events
```

Event types:

- `status.updated`
- `progress.updated`
- `activity.appended`
- `issue.found`
- `artifact.updated`
- `process.started`
- `process.interrupted`
- `process.completed`
- `process.failed`

Issue events should be prominent and should carry severity:

```json
{
  "type": "issue.found",
  "severity": "major",
  "summary": "Completion polling loses terminal reservation state.",
  "source": "docs/reviews/code-review-phase-9-attempt-2.md"
}
```

The same event model should support a future `electroboy progress` view and the
GUI without duplicating progress parsing logic.

## Project And Meta-Project Support

For a normal project, the service root is the project root.

For a meta-project, the service root is the meta-project root and the active
repository is selected from the registered repository list. The GUI should show:

- Meta-project root.
- Active repository.
- Registered repositories.
- Per-repository status summary.
- A repository switcher.

Switching repositories should follow existing `electroboy start <repo>`
semantics. It should context switch to the selected repository and initialize
ElectroBoy state for that repository if needed. No separate end command is
needed.

Artifacts shown in the GUI should always be resolved against the active target
repository. Meta-project-level state is shown separately.

## State And Persistence

The GUI reads the same state as the CLI:

```text
.electroboy/shared/runs/<run-id>/manifest.json
.electroboy/shared/phase-status.json
.electroboy/shared/runs/<run-id>/activity-log.jsonl
.electroboy/shared/runs/<run-id>/approvals.jsonl
.electroboy/shared/runs/<run-id>/change-requests.jsonl
.electroboy/shared/runs/<run-id>/code-reviews.jsonl
.electroboy/shared/runs/<run-id>/progress/
.electroboy/local/sessions/<run-id>/<stage>/<role>.json
```

The service should use existing `StateStore` and artifact helpers. It should
avoid writing state directly except through ElectroBoy APIs.

Generated user-facing Markdown remains under `docs/`, including:

- Requirements.
- Detailed design.
- Implementation plan.
- Test plan.
- Review summaries.
- Implementation reports.
- Validation reports.

Hidden JSONL ledgers and provider transcripts remain under `.electroboy`.

## API Shape

The exact API can evolve, but the first version should expose these concepts.

Read APIs:

```text
GET /api/status
GET /api/workflow
GET /api/artifacts
GET /api/artifacts/{artifact_id}
GET /api/issues
GET /api/reviews
GET /api/progress
GET /api/activity
GET /api/meta/repositories
```

Mutating APIs:

```text
POST /api/projects/new
POST /api/meta/init
POST /api/meta/add
POST /api/meta/start
POST /api/workflow/{command}/run
POST /api/workflow/{command}/approve
POST /api/workflow/{command}/force
POST /api/agents/interactive/start
POST /api/agents/interactive/{session_id}/message
POST /api/agents/interactive/{session_id}/interrupt
POST /api/agents/noninteractive/start
POST /api/uploads
```

The workflow command API should accept:

```json
{
  "force": false,
  "reason": "",
  "interactive": false,
  "message": "",
  "review_message": "",
  "blockers_only": false
}
```

The service translates these into the same internal call paths as the CLI.

## Security And Process Boundaries

The first implementation is local-only by default:

- Bind to `127.0.0.1`.
- Do not expose the service on a public interface unless explicitly requested.
- Do not trust browser input as shell text.
- Do not run arbitrary shell commands from the browser.
- Route all workflow operations through ElectroBoy command APIs.
- Store uploaded files under `.electroboy/local/uploads`.
- Avoid serving files outside the active project or meta-project roots.

If remote access is added later, it must include authentication and a clear
workspace allowlist.

## Failure Handling

The GUI should make failure states explicit:

- Agent failed.
- Agent interrupted.
- Command blocked by gate.
- Project not active.
- Runtime not configured.
- Artifact missing.
- Review output contract failed.
- Repository dirty state blocks the requested action.

For each failure, show:

- What failed.
- The blocking reason.
- The next useful action.
- Links to raw output or logs when available.

The GUI should not hide orchestrator errors. It should translate them into
readable messages while preserving the underlying detail.

## Implementation Plan

### Phase 1. Service Skeleton

- Add `electroboy serve`.
- Start a local HTTP service bound to `127.0.0.1`.
- Expose status, workflow graph, artifacts, progress, and activity read APIs.
- Serve a minimal browser UI.
- Reuse existing `StateStore`, manifest, phase-status, and report helpers.

Exit criteria:

- Browser can open an existing project and show the same state as
  `electroboy status`.
- CLI and GUI can both read the same active project state.

### Phase 2. Workflow Graph

- Render the command-aligned workflow graph.
- Highlight active, complete, blocked, invalidated, and forced-available
  states.
- Open a stage panel when a node is clicked.
- Show stage artifacts and blocking gates.

Exit criteria:

- The graph correctly distinguishes `implementation-plan`, `plan-approve`,
  `code`, `test-plan`, and `test-plan-approve`.
- There is no low-level stage-reset action in the UI.

### Phase 3. Command Execution

- Add service endpoints for public workflow commands.
- Support `--force`, `--reason`, and command-specific options.
- Stream command progress to the browser.
- Record activity through existing orchestrator paths.

Exit criteria:

- The GUI can run requirements, design, implementation-plan, code, test-plan,
  validate, and document commands.
- Forced command resets behave the same as the CLI.

### Phase 4. Interactive Agent Sessions

- Add browser-mediated interactive sessions.
- Provide a multi-line editor, send button, interrupt button, and response pane.
- Preserve provider session ids and summaries.
- Add attachment upload and prompt references.
- Provide optional raw output diagnostics.

Exit criteria:

- The operator can click `requirements`, launch an interactive agent, type a
  multi-line prompt, and see rendered agent output.
- The operator can interrupt a running interactive agent and see the activity
  event.

### Phase 5. Progress And Review Visibility

- Stream progress files and activity events.
- Highlight issue findings by severity.
- Show review summaries under `docs/reviews`.
- Link generated reports directly from the workflow graph.

Exit criteria:

- A browser opened in a second shell/session can monitor a non-interactive
  `code` or `design-review` run started elsewhere.
- New blocker and major issues appear prominently.

### Phase 6. Meta-Project Support

- Add repository selector.
- Show registered repositories.
- Support `meta init`, `add`, and `start` from the GUI.
- Scope artifacts and commands to the active target repository.

Exit criteria:

- The operator can open a meta-project, switch active repositories, and run the
  workflow against the selected repository.

## Open Questions

- Should the first UI be bundled as static assets served by Python, or should it
  use a separate frontend dev server during development?
- Should interactive agent output be stored as rendered Markdown chunks in
  addition to raw provider transcripts?
- How much raw terminal behavior should the diagnostics tab expose?
- Should uploads be included in future commit artifacts, or always remain
  local-only unless copied into project docs?
- Should the service support multiple simultaneous browser clients with one
  active interactive session, or allow multiple named sessions per role?
- Should remote access be supported later, or should the service remain
  intentionally local-only?
