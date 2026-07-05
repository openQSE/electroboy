# API Documentation

## Public CLI

The public interface is the `ai-pipeline` command. `electroboy` is an alias for
the same CLI. Source checkouts include `./ai-pipeline` and `./electroboy`
wrappers.

Operator workflow commands:

- `new <path>` creates a GitHub-ready project, initializes artifacts, creates
  `.agent-pipeline/`, and installs `<path>/bin/activate`.
- `status` prints active stage, active phase, completed gates, invalidated
  gates, open requests, open issues, and blocked gates.
- `requirements [--reason <text>]` starts or resumes requirements authoring.
- `requirements-approve` records human and Design Author approval.
- `design [--reason <text>]` starts or resumes design authoring.
- `design-review` runs the design-review stage gate.
- `design-approve` records human design acceptance.
- `implementation-plan [--reason <text>]` starts or resumes planning.
- `plan-approve` records human and Design Author plan approval.
- `code [--reason <text>]` starts or resumes implementation phase work.
- `document [--reason <text>]` runs documentation review and refinement.
- `code-approve` records final human completion approval.
- `deactivate` leaves an activated project shell environment.
- `report summary` writes or prints a run summary.
- `report trace` writes or prints the activity trace.

Lower-level commands:

- `init` creates a run under `.agent-pipeline/shared/`.
- `resume` prints the state needed to continue an interrupted run.
- `stage` completes the active pipeline stage when approvals and gates pass.
- `gate` evaluates a deterministic gate and records the result.
- `phase` manages phase start, review, test review, drift, and commit state.
- `validate` runs final validation commands and writes a validation report.
- `docs-review` verifies final documentation and snapshots passing docs.
- `plan` checks or records implementation-plan updates.
- `issues` records append-only review issue lifecycle events.
- `agent` invokes the configured runtime for an agent role.
- `artifacts` creates artifact templates and snapshots artifacts.
- `change` manages change-control requests, approvals, and reopening.

Earlier operator workflow commands reopen baselines when `--reason` is
provided and the requested stage is behind the active stage. The orchestrator
records change-control and baseline-invalidation records before resuming from
the reopened stage.

## Stage Commands

Stage commands enforce the ordered pipeline.

```bash
ai-pipeline stage requirements --human-approved --author-confirmed
ai-pipeline stage design --human-approved
ai-pipeline stage design-review
ai-pipeline stage design-acceptance --human-approved
ai-pipeline stage plan --human-approved --author-confirmed
ai-pipeline stage implementation
```

`requirements`, `design`, `design-acceptance`, and `plan` require explicit
approval flags unless the approval records already exist for the run.

## Project Environment Commands

```bash
./ai-pipeline new path/to/project
source path/to/project/bin/activate
ai-pipeline status
ai-pipeline deactivate
```

`new` creates the target directory when needed. If the target is not already
inside a Git worktree, it initializes a repository. Existing repositories are
reused. Activation exports `AI_PIPELINE_PROJECT_ROOT`, prepends
`<project>/bin` to `PATH`, and defines shell functions for `ai-pipeline` and
`electroboy`. The generated wrappers pass `--root <project>` to the Python
module and use project-local runtime code when available.

If `.agent-pipeline/project.toml` enables Python activation, the activation
script sources the configured Python environment. It only deactivates that
Python environment when the pipeline owns that activation.

## Phase Commands

```bash
ai-pipeline phase start <n>
ai-pipeline phase review <n> --pass
ai-pipeline phase test <n> --pass
ai-pipeline phase drift <n> --reason <text>
ai-pipeline phase commit <n> --sha <commit-sha>
```

Only one implementation phase can be active. Review and test review commands
must target the active phase. They record operator state and issue files, but
they do not replace configured agent runtime evidence. `phase commit` verifies
that code review and test review have runtime-backed agent events, verifies
that the supplied SHA is an existing commit reachable from `HEAD`, verifies
that the commit message identifies the phase and objective, checks changed
paths against any `Paths:` metadata for the active phase, and stores it in
phase status.

## Validation Commands

`validate` always runs the configured full test-suite command. It also runs
artifact validation commands declared with `Validation:` lines and any quoted
operator commands passed with `--command`.

```bash
ai-pipeline validate --command "python -m unittest discover -s tests"
```

Use `--shell-command` only when shell behavior is required.

```bash
ai-pipeline validate --shell-command "python -m unittest discover -s tests"
```

Validation writes `validation-report.md` under the run artifact directory and
stores failures in `validation-review.jsonl`.

## Documentation Commands

```bash
ai-pipeline document
ai-pipeline document --reason "Improve API examples"
ai-pipeline code-approve
```

`document` wraps the final documentation review gate. It requires validation
testing to pass before it can complete. `code-approve` requires the
documentation gate to pass before it records final human completion approval.

## Change Control Commands

```bash
ai-pipeline change open --baseline requirements --reason <text>
ai-pipeline change classify CR-0001 --baseline requirements
ai-pipeline change approve CR-0001 --human-approved
ai-pipeline change reopen CR-0001
ai-pipeline change status
```

`reopen` requires a classified and human-approved request. It invalidates
downstream gates and records affected artifact snapshot refs.

## Issue Commands

```bash
ai-pipeline issues add <file> --id <id> --source <agent> \
  --severity major --summary <text>
ai-pipeline issues transition <file> <id> --status fixed
ai-pipeline issues resolve <file> <id>
ai-pipeline issues list <file>
```

Review issue files are append-only JSONL logs. Reads collapse lifecycle events
to the latest state for each issue id.

## Runtime Configuration

`agent-pipeline.toml` selects agent runtimes.

```toml
[runtime]
default = "codex"

[runtimes.codex]
adapter = "codex_exec"
command = "codex"
args = ["exec", "--json"]

[roles]
code_review = "codex"
```

Codex review roles run in `read-only` sandbox mode by default. Coding and
documentation-writing roles run in `workspace-write` mode unless the runtime
sets an explicit sandbox option.

## Public Python Modules

- `ai_pipeline.cli` contains the CLI parser and command handlers.
- `ai_pipeline.models` contains versioned state models.
- `ai_pipeline.state_store` reads and writes `.agent-pipeline` state.
- `ai_pipeline.gates` evaluates deterministic gates.
- `ai_pipeline.artifacts` creates templates and snapshots artifacts.
- `ai_pipeline.planning` parses requirement and phase traceability.
- `ai_pipeline.runtime` selects configured agent runtimes.
- `ai_pipeline.adapters.*` implements runtime adapter contracts.
