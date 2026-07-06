# ElectroBoy

ElectroBoy is an AI agent pipeline for disciplined AI-assisted software
development. It turns an informal agent workflow into an ordered, auditable
pipeline:

1. Define requirements with the human operator and design author agent.
2. Create and review the detailed design.
3. Approve an implementation plan with small phases.
4. Implement one phase at a time.
5. Run code review, test review, validation, and documentation review.
6. Preserve all review comments, decisions, commands, and artifacts.

The tool is intentionally not a replacement for human design judgment. It keeps
the creative requirements and design work interactive, then enforces the
engineering discipline around when implementation can start and how review
loops are recorded.

## Installation

Python 3.10 or newer is required. The package declares Rich for automatic
pipeline progress output.

Standard installation:

```bash
python -m pip install .
electroboy --help
```

Editable installation:

```bash
python -m pip install -e .
electroboy --help
```

Run directly from a checkout:

```bash
./electroboy --help
./electroboy new /tmp/example-pipeline-project
```

## Workflow

Create a pipeline project and enter its project environment:

```bash
./electroboy new path/to/project
source path/to/project/bin/activate
electroboy status
```

`new` creates or enters the target directory. If the directory is not already
inside a Git worktree, it initializes a GitHub-ready repository. Existing
repositories are reused instead of nesting a new repository. The command also
creates the standard pipeline artifacts, creates `.electroboy/`, and
installs `path/to/project/bin/activate`.

Define and approve requirements:

```bash
electroboy requirements
electroboy requirements-approve
```

Create, review, and approve the design:

```bash
electroboy design
electroboy design-review
electroboy design-approve
```

Create and approve the implementation plan:

```bash
electroboy implementation-plan
electroboy plan-approve
```

Commit the approved pre-implementation baseline:

```bash
git status --short
git add .
git commit -m "project: approve implementation baseline"
```

Run the automated implementation pipeline, finesse documentation, and record
final approval:

```bash
electroboy code
electroboy validate
electroboy document
electroboy code-approve
```

The automated code loop expects a clean git worktree before it creates phase
commits. Commit the approved requirements, design, implementation plan,
generated project files, and any hand-authored baseline files before running
`code`.

`code` starts or resumes the fully automated implementation loop. It selects
the active or next planned phase, invokes the configured coding agent, invokes
code review, invokes test review, creates and records the phase commit, and
continues until every planned phase is complete. The command stops only when an
agent fails, an unresolved review issue blocks progress, phase scope changes,
git cannot create a valid commit, or the agents need human input.

After `code` completes, run `validate`. Validation always runs the full test
suite plus artifact-declared validation commands. If validation fails, the
pipeline opens a validation-fix phase and returns to `code`. `document` runs
the documentation refinement and review phase. If a review or validation issue
needs human input, the command records the escalation and stops at a resumable
checkpoint.

Use phased mode only when a human wants to inspect and record each phase commit
manually:

```bash
electroboy code --phased
electroboy phase commit <phase> --sha <commit-sha>
```

`code --phased` preserves the one-phase checkpoint workflow. It runs the active
phase agents and leaves commit creation or commit recording to the operator.

Expert users can force the active stage when adopting or repairing an existing
project:

```bash
electroboy stage implementation --force --reason "Adopting existing project"
```

This records a decision and activity event, but it does not mark skipped gates
as complete.

Resume an interrupted run from the same project:

```bash
source path/to/project/bin/activate
electroboy status
electroboy code
```

Move backward when later work exposes a missing requirement, design issue, or
phase-plan problem:

```bash
electroboy requirements --reason "New setup workflow discovered"
electroboy design --reason "Architecture needs queued run support"
electroboy implementation-plan --reason "Phase split needs to change"
electroboy document --reason "Improve API examples"
```

The pipeline allows controlled backward movement and blocks forward skips. An
earlier stage command records a change-control event and invalidates affected
downstream gates. A later stage command fails until its predecessor gates pass.

Leave the project environment:

```bash
electroboy deactivate
```

The activation script prefixes the shell prompt with the project directory
name, and can also enter a configured Python environment. The pipeline uses
`electroboy deactivate` instead of bare `deactivate` so it can restore the
prompt and does not conflict with Python virtual environment behavior.

After activation, use `electroboy` without `./` so the project environment
selects the active project.

The `./ai-pipeline` command is an alias.

## Why This Exists

AI coding agents are useful, but they can drift when the project lacks a clear
process. This tool provides the process layer around those agents.

It helps by:

- Enforcing requirements before design, and design before implementation.
- Preventing an operator or agent from jumping into the middle of the pipeline.
- Breaking implementation into small reviewed phases instead of one large code
  dump.
- Keeping code review and test review as separate responsibilities.
- Recording an append-only history of agent actions and review comments.
- Supporting controlled iteration when later work exposes a requirement or
  design issue.
- Avoiding waterfall development by making requirement and design refinement a
  first-class change-control path.
- Allowing different agent CLIs to be used behind the same orchestration model.

## Current Status

The repository contains a local runnable orchestrator prototype with the
operator-facing workflow described above.

Implemented capabilities:

- Python package and CLI entry point.
- ElectroBoy command entrypoint with the `ai-pipeline` alias.
- `./electroboy new <path>` project creation.
- Generated project activation scripts under `<project>/bin/activate`.
- `electroboy deactivate` shell-safe deactivation.
- JSON-backed shared state under `.electroboy/shared/`.
- Local runtime state under `.electroboy/local/`.
- Ordered stage gates for requirements, design, planning, implementation,
  validation, and documentation review.
- Primary stage commands for requirements, design, implementation planning,
  code, documentation, and final approval.
- Explicit human approvals and Design Author confirmations for required
  baseline gates.
- Artifact snapshots, approval records, decisions, review issues, change
  requests, baseline invalidations, and activity events.
- Append-only issue lifecycle transitions.
- Automated phase start, review, test review, drift, and commit recording, plus
  manual `phase commit` for phased mode.
- Final validation and documentation review gates.
- Public workflow commands that reopen earlier baselines with `--reason`.
- Expert forced stage movement with `electroboy stage <stage> --force`.
- Summary and trace reports.
- Rich-compatible progress output for automatic implementation commands, with
  plain text fallback when Rich is unavailable.
- Default automated implementation that commits each reviewed phase and
  advances to validation when the implementation plan is complete.
- Runtime adapter scaffolding for manual, generic CLI, Codex exec, and Codex
  SDK runtimes.
- Unit tests for pipeline state, gates, runtime adapters, phase flow,
  validation, documentation review, change control, and reporting.

Extension points:

- The Codex exec and generic CLI adapters can invoke configured agent CLIs.
- `CodexSdkRuntime` remains a documented extension point.
- Documentation review has deterministic checks and can also consume
  documentation-agent issue records.

## Flow Enforcement

The CLI records one active stage in
`.electroboy/shared/runs/<run-id>/manifest.json`. Mutating commands must
match that active stage, move backward through change control, or pass
predecessor gates, unless an expert operator uses the explicit forced stage
override.

For example, this fails immediately after `new`:

```bash
electroboy code
```

The command is blocked because the run is still at `requirements`. This is the
core software engineering rule enforced by the orchestrator: no implementation
before requirements, design, and implementation planning are approved.

Useful inspection commands:

```bash
electroboy status
electroboy report summary
electroboy report trace
```

## Change Control

Later pipeline stages may reveal a missing requirement, design drift, or an
implementation-plan gap. Those cases must reopen the earliest affected
baseline instead of jumping directly into an arbitrary stage.

Run the earliest affected stage command with a reason:

```bash
electroboy requirements --reason "Validation found a missing setup workflow"
electroboy design --reason "The architecture needs queued run support"
electroboy implementation-plan --reason "The phase split is wrong"
electroboy document --reason "Improve API examples"
```

The orchestrator records a change-control event, asks for approval when
downstream gates would be invalidated, and resumes from the reopened stage.
Use `electroboy stage <stage> --force --reason <text>` only when an expert
operator needs to override the active stage directly.

## Agent Runtime Configuration

The design supports configurable agent runtimes. Codex is the default target,
but the pipeline is intended to support any CLI that can satisfy the adapter
contract, including Claude or a local agent command.

A compatible agent CLI must be able to:

- Run non-interactively.
- Receive a role prompt and context bundle.
- Return output that can be parsed into the pipeline's `AgentResult`.
- Make filesystem write behavior clear to the orchestrator.
- Keep credentials outside repository files and durable run state.

Runtime configuration shape:

```toml
[runtime]
default = "codex"

[runtimes.codex]
adapter = "codex_exec"
command = "codex"
args = ["exec", "--json"]
structured_output = "json_schema"

[runtimes.codex-interactive]
adapter = "codex_interactive"
command = "codex"

[runtimes.claude]
adapter = "generic_cli"
command = "claude"
args = ["--print"]
structured_output = "prompt_contract"

[roles]
design_author = "codex-interactive"
design_review = "codex"
coding = "codex"
code_review = "claude"
test_review = "codex"
documentation = "codex"

[environment]
activate_python = true
python_activate = ".venv/bin/activate"
python_managed_by_pipeline = false
```

The design-author role opens the interactive Codex CLI for requirements,
design, and implementation-plan authoring. Codex review roles run with
`--sandbox read-only` by default. Coding and documentation-writing roles run
with `--sandbox workspace-write` unless the runtime configuration supplies an
explicit sandbox option.

If `activate_python` is true, `source path/to/project/bin/activate` also
enters the configured Python environment. `electroboy deactivate` restores the
pipeline context and only deactivates the Python environment when the pipeline
owns that activation.

## State Files

Pipeline state is stored under `.electroboy/`.

Shared files are committed to git:

- `.electroboy/project.toml` stores project configuration.
- `.electroboy/shared/current-run` stores the active run id.
- `.electroboy/shared/runs/<run-id>/manifest.json` stores active stage and
  completed gates.
- `.electroboy/shared/runs/<run-id>/activity-log.jsonl` stores run events.
- `.electroboy/shared/runs/<run-id>/change-requests.jsonl` stores
  change-control requests.
- `.electroboy/shared/runs/<run-id>/approvals.jsonl` stores human and
  agent approvals.
- `.electroboy/shared/runs/<run-id>/*-review.jsonl` stores append-only
  issue lifecycle records.
- `.electroboy/shared/runs/<run-id>/artifact-snapshots.jsonl` stores
  approved artifact snapshots.

Local files are ignored by git:

- `.electroboy/local/activation.json` stores shell activation state.
- `.electroboy/local/sessions/` stores provider session references.
- `.electroboy/local/raw/` stores redacted raw runtime streams.
- `.electroboy/local/logs/` stores local diagnostic logs.

Secrets are never written to shared or local state.

## Development

Run tests:

```bash
python -m unittest discover -s tests
```

Run the CLI smoke check:

```bash
./electroboy --help
```

Run a full smoke check:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
./electroboy --help
```
