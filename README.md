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

The current implementation is the first runnable slice of the orchestrator.

Implemented:

- Python package and CLI entry point.
- JSON-backed run state under `.agent-pipeline/`.
- `init`, `status`, `resume`, `stage`, `gate`, and basic `change` commands.
- Early ordered-flow enforcement.
- Gate checks for requirements, design, design acceptance, and planning.
- Runtime adapter scaffolding for manual, generic CLI, Codex exec, and Codex
  SDK runtimes.
- Unit tests for CLI initialization and blocked mid-pipeline jumps.

Not implemented yet:

- Real agent invocation.
- Runtime configuration loading.
- Codex or Claude execution.
- Artifact snapshots.
- Full phase implementation loop.
- Validation testing and documentation review automation.
- Change request classify/reopen behavior.

The repository is being built phase by phase. The runtime adapter structure is
present, but the CLI does not yet call Codex, Claude, or another agent CLI.

## Install For Development

The project currently has no third-party runtime dependencies. Python 3.10 or
newer is required.

Run directly from a checkout:

```bash
PYTHONPATH=src python -m ai_pipeline --help
```

Or install in editable mode:

```bash
python -m pip install -e .
ai-pipeline --help
```

## Basic Usage

Initialize a pipeline run:

```bash
PYTHONPATH=src python -m ai_pipeline init
```

Show the current run state:

```bash
PYTHONPATH=src python -m ai_pipeline status
```

The initial active stage is `requirements`. The pipeline will reject later
stage commands until the required predecessor gates pass.

Create `docs/requirements.md`, then complete the requirements stage:

```bash
mkdir -p docs
printf '# Requirements\n' > docs/requirements.md
PYTHONPATH=src python -m ai_pipeline stage requirements
```

The active stage becomes `design`.

Create `docs/detailed-design.md`, then move through design and design review:

```bash
printf '# Detailed Design\n' > docs/detailed-design.md
PYTHONPATH=src python -m ai_pipeline stage design
PYTHONPATH=src python -m ai_pipeline stage design-review
PYTHONPATH=src python -m ai_pipeline stage design-acceptance
```

Create `docs/implementation-plan.md`, then approve the plan stage:

```bash
printf '# Implementation Plan\n' > docs/implementation-plan.md
PYTHONPATH=src python -m ai_pipeline stage plan
```

At this point the current slice advances to the `implementation` stage. The
full phase implementation loop will be added in later phases.

## Flow Enforcement

The CLI records one active stage in
`.agent-pipeline/runs/<run-id>/manifest.json`. Mutating commands must match
that active stage and pass predecessor gates.

For example, this fails immediately after `init`:

```bash
PYTHONPATH=src python -m ai_pipeline stage plan
```

The command is blocked because the run is still at `requirements`. This is the
core software engineering rule enforced by the orchestrator: no implementation
planning before requirements and design are approved.

Useful inspection commands:

```bash
PYTHONPATH=src python -m ai_pipeline status
PYTHONPATH=src python -m ai_pipeline resume
PYTHONPATH=src python -m ai_pipeline gate requirements
PYTHONPATH=src python -m ai_pipeline gate implementation
```

## Change Control

Later pipeline stages may reveal a missing requirement, design drift, or an
implementation-plan gap. Those cases must reopen the earliest affected
baseline instead of jumping directly into an arbitrary stage.

Open a change-control request:

```bash
PYTHONPATH=src python -m ai_pipeline change open \
  --baseline requirements \
  --reason "Validation found an undocumented setup workflow."
```

Show open requests:

```bash
PYTHONPATH=src python -m ai_pipeline change status
```

The `change classify` and `change reopen` command shapes exist, but their
behavior is not implemented yet.

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

The planned runtime configuration shape is:

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
design_review = "codex"
coding = "codex"
code_review = "claude"
test_review = "codex"
documentation = "codex"
```

The first implementation slice includes the `RuntimeConfig` model and adapter
placeholders. Runtime config loading and actual agent invocation are the next
implementation steps before Codex, Claude, or another CLI can run inside the
pipeline.

## State Files

Pipeline state is stored under `.agent-pipeline/`.

Important files:

- `current-run` stores the active run id.
- `runs/<run-id>/manifest.json` stores active stage and completed gates.
- `runs/<run-id>/activity-log.jsonl` stores run events.
- `runs/<run-id>/change-requests.jsonl` stores change-control requests.

The `.agent-pipeline/` directory is ignored by git because it contains local
run history.

## Development

Run tests:

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

Run the CLI smoke check:

```bash
PYTHONPATH=src python -m ai_pipeline --help
```

The next build steps are runtime configuration loading, artifact snapshots, and
real adapter invocation for configured agent CLIs.
