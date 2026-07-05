# AI Agent Pipeline

AI Agent Pipeline is a local orchestration tool for disciplined AI-assisted
software development. It turns an informal agent workflow into an ordered,
auditable pipeline:

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

## Workflow

Create a pipeline project and enter its project environment:

```bash
./ai-pipeline new path/to/project
source path/to/project/bin/activate
ai-pipeline status
```

`new` creates or enters the target directory. If the directory is not already
inside a Git worktree, it initializes a GitHub-ready repository. Existing
repositories are reused instead of nesting a new repository. The command also
creates the standard pipeline artifacts, creates `.agent-pipeline/`, and
installs `path/to/project/bin/activate`.

Define and approve requirements with ElectroBoy:

```bash
ai-pipeline requirements
ai-pipeline requirements-approve
```

Create, review, and approve the design:

```bash
ai-pipeline design
ai-pipeline design-review
ai-pipeline design-approve
```

Create and approve the implementation plan:

```bash
ai-pipeline implementation-plan
ai-pipeline plan-approve
```

Run the automated implementation pipeline, finesse documentation, and record
final approval:

```bash
ai-pipeline code
ai-pipeline phase commit <phase> --sha <commit-sha>
ai-pipeline code
ai-pipeline validate
ai-pipeline document
ai-pipeline code-approve
```

`code` starts or resumes one implementation phase, invokes the configured
coding agent, invokes code review, invokes test review, and records the agent
evidence required by the phase commit gate. After reviewing the resulting git
commit, record it with `phase commit`. Repeat `code` and `phase commit` until
all phases are complete, then run validation. Validation always runs the full
test suite plus artifact-declared validation commands. If validation fails, the
pipeline opens a validation-fix phase and returns to `code`. `document` runs
the documentation refinement and review phase. If a review or validation issue
needs human input, the command records the escalation and stops at a resumable
checkpoint.

Resume an interrupted run from the same project:

```bash
source path/to/project/bin/activate
ai-pipeline status
ai-pipeline code
```

Move backward when later work exposes a missing requirement, design issue, or
phase-plan problem:

```bash
ai-pipeline requirements --reason "New setup workflow discovered"
ai-pipeline design --reason "Architecture needs queued run support"
ai-pipeline implementation-plan --reason "Phase split needs to change"
ai-pipeline document --reason "Improve API examples"
```

The pipeline allows controlled backward movement and blocks forward skips. An
earlier stage command records a change-control event and invalidates affected
downstream gates. A later stage command fails until its predecessor gates pass.

Leave the project environment:

```bash
ai-pipeline deactivate
```

The activation script can also enter a configured Python environment. The
pipeline uses `ai-pipeline deactivate` instead of bare `deactivate` so it does
not conflict with Python virtual environment behavior.

The repository entrypoint can be run as either `./ai-pipeline` or
`./electroboy`. Installed command environments expose the same CLI as
`ai-pipeline` and `electroboy`.

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
- `ai-pipeline` and `electroboy` command entrypoints.
- `ai-pipeline new <path>` project creation.
- Generated project activation scripts under `<project>/bin/activate`.
- `ai-pipeline deactivate` shell-safe deactivation.
- JSON-backed shared state under `.agent-pipeline/shared/`.
- Local runtime state under `.agent-pipeline/local/`.
- Ordered stage gates for requirements, design, planning, implementation,
  validation, and documentation review.
- Primary stage commands for requirements, design, implementation planning,
  code, documentation, and final approval.
- Explicit human approvals and Design Author confirmations for required
  baseline gates.
- Artifact snapshots, approval records, decisions, review issues, change
  requests, baseline invalidations, and activity events.
- Append-only issue lifecycle transitions.
- Phase start, review, test review, drift, and commit commands.
- Final validation and documentation review gates.
- Change-control classify, approve, and reopen behavior.
- Public stage commands that reopen earlier baselines with `--reason`.
- Summary and trace reports.
- Rich-compatible progress output for automatic implementation commands, with
  plain text fallback when Rich is unavailable.
- Runtime adapter scaffolding for manual, generic CLI, Codex exec, and Codex
  SDK runtimes.
- Unit tests for pipeline state, gates, runtime adapters, phase flow,
  validation, documentation review, change control, and reporting.

Extension points:

- The Codex exec and generic CLI adapters can invoke configured agent CLIs.
- `CodexSdkRuntime` remains a documented extension point.
- Documentation review has deterministic checks and can also consume
  documentation-agent issue records.

## Install For Development

Python 3.10 or newer is required. The prototype has no third-party runtime
dependencies. The target workflow adds Rich for automatic pipeline progress
output.

Run directly from a checkout:

```bash
./ai-pipeline --help
./electroboy --help
./ai-pipeline new /tmp/example-pipeline-project
```

Or install in editable mode:

```bash
python -m pip install -e .
ai-pipeline --help
electroboy --help
```

## Basic Usage

Create or enter a project:

```bash
./ai-pipeline new path/to/project
source path/to/project/bin/activate
```

Show the current stage, blocked gate, and next command:

```bash
ai-pipeline status
```

Interactive authoring commands:

```bash
ai-pipeline requirements
ai-pipeline design
ai-pipeline implementation-plan
```

Approval commands:

```bash
ai-pipeline requirements-approve
ai-pipeline design-approve
ai-pipeline plan-approve
ai-pipeline code-approve
```

Automated commands:

```bash
ai-pipeline design-review
ai-pipeline code
ai-pipeline document
```

`requirements`, `design`, and `implementation-plan` start the configured
Design Author Agent with the right artifact context. The session can end and
be restarted. The next invocation rebuilds context from repository artifacts,
shared pipeline state, decisions, review issues, and activity events.

`code` resumes from the last durable checkpoint. It implements one phase at a
time and runs code review and test review. `phase commit` records the reviewed
git commit for that phase. After all phase commits are recorded, validation
testing runs before the documentation finesse pass.
`document` completes documentation review before `code-approve` can pass.

## Flow Enforcement

The CLI records one active stage in
`.agent-pipeline/shared/runs/<run-id>/manifest.json`. Mutating commands must
match that active stage, move backward through change control, or pass
predecessor gates.

For example, this fails immediately after `new`:

```bash
ai-pipeline code
```

The command is blocked because the run is still at `requirements`. This is the
core software engineering rule enforced by the orchestrator: no implementation
before requirements, design, and implementation planning are approved.

Useful inspection commands:

```bash
ai-pipeline status
ai-pipeline report summary
ai-pipeline report trace
```

## Change Control

Later pipeline stages may reveal a missing requirement, design drift, or an
implementation-plan gap. Those cases must reopen the earliest affected
baseline instead of jumping directly into an arbitrary stage.

Run the earliest affected stage command with a reason:

```bash
ai-pipeline requirements --reason "Validation found a missing setup workflow"
ai-pipeline design --reason "The architecture needs queued run support"
ai-pipeline implementation-plan --reason "The phase split is wrong"
ai-pipeline document --reason "Improve API examples"
```

The orchestrator records a change-control event, asks for approval when
downstream gates would be invalidated, and resumes from the reopened stage.

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

[runtimes.claude]
adapter = "generic_cli"
command = "claude"
args = ["--print"]
structured_output = "prompt_contract"

[roles]
design_author = "codex"
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

Codex review roles run with `--sandbox read-only` by default. Coding and
documentation-writing roles run with `--sandbox workspace-write` unless the
runtime configuration supplies an explicit sandbox option.

If `activate_python` is true, `source path/to/project/bin/activate` also
enters the configured Python environment. `ai-pipeline deactivate` restores the
pipeline context and only deactivates the Python environment when the pipeline
owns that activation.

## State Files

Pipeline state is stored under `.agent-pipeline/`.

Shared files are committed to git:

- `.agent-pipeline/project.toml` stores project configuration.
- `.agent-pipeline/shared/current-run` stores the active run id.
- `.agent-pipeline/shared/runs/<run-id>/manifest.json` stores active stage and
  completed gates.
- `.agent-pipeline/shared/runs/<run-id>/activity-log.jsonl` stores run events.
- `.agent-pipeline/shared/runs/<run-id>/change-requests.jsonl` stores
  change-control requests.
- `.agent-pipeline/shared/runs/<run-id>/approvals.jsonl` stores human and
  agent approvals.
- `.agent-pipeline/shared/runs/<run-id>/*-review.jsonl` stores append-only
  issue lifecycle records.
- `.agent-pipeline/shared/runs/<run-id>/artifact-snapshots.jsonl` stores
  approved artifact snapshots.

Local files are ignored by git:

- `.agent-pipeline/local/activation.json` stores shell activation state.
- `.agent-pipeline/local/sessions/` stores provider session references.
- `.agent-pipeline/local/raw/` stores redacted raw runtime streams.
- `.agent-pipeline/local/logs/` stores local diagnostic logs.

Secrets are never written to shared or local state.

## Development

Run tests:

```bash
python -m unittest discover -s tests
```

Run the CLI smoke check:

```bash
ai-pipeline --help
```

Run a full smoke check:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
ai-pipeline --help
```
