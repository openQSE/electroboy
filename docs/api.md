# API Documentation

## Public CLI

The public interface is the `electroboy` command. `ai-pipeline` is an alias
for the same CLI. Source checkouts include `./electroboy` and `./ai-pipeline`
wrappers.

Operator workflow commands:

- `new <path>` creates a GitHub-ready project, initializes artifacts, creates
  `.electroboy/`, and installs `<path>/bin/activate`.
- `status` prints active stage, active phase, completed gates, invalidated
  gates, open requests, open issues, and blocked gates.
- `requirements [--reason <text>]` starts or resumes requirements authoring.
- `requirements-approve` records human and Design Author approval.
- `design [--reason <text>]` starts or resumes design authoring.
- `design-review` runs the design-review stage gate.
- `design-approve` records human design acceptance.
- `implementation-plan [--reason <text>]` starts or resumes planning.
- `plan-approve` records human and Design Author plan approval.
- `code [--reason <text>] [--phased]` starts or resumes implementation work.
- `document [--reason <text>]` runs documentation review and refinement.
- `code-approve` records final human completion approval.
- `deactivate` leaves an activated project shell environment.
- `report summary` writes or prints a run summary.
- `report trace` writes or prints the activity trace.

Lower-level commands:

- `init` creates a run under `.electroboy/shared/`.
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
electroboy stage requirements --human-approved --author-confirmed
electroboy stage design --human-approved
electroboy stage design-review
electroboy stage design-acceptance --human-approved
electroboy stage plan --human-approved --author-confirmed
electroboy stage implementation
```

`requirements`, `design`, `design-acceptance`, and `plan` require explicit
approval flags unless the approval records already exist for the run.

## Project Environment Commands

```bash
./electroboy new path/to/project
source path/to/project/bin/activate
electroboy status
electroboy deactivate
```

`new` creates the target directory when needed. If the target is not already
inside a Git worktree, it initializes a repository. Existing repositories are
reused. Activation exports `ELECTROBOY_PROJECT_ROOT`, prepends
`<project>/bin` to `PATH`, and defines shell functions for `electroboy` and
`ai-pipeline`. The generated wrappers pass `--root <project>` to the Python
module and use project-local runtime code when available.

If `.electroboy/project.toml` enables Python activation, the activation
script sources the configured Python environment. It only deactivates that
Python environment when the pipeline owns that activation.

## Phase Commands

`electroboy code` is the normal implementation command. By default, it runs
each remaining planned phase, invokes coding, code review, and test review
agents, creates a valid phase commit, records that commit, and continues until
the implementation stage is complete.

`electroboy code --phased` is the explicit manual checkpoint mode. It runs one
phase and leaves commit creation or commit recording to the operator.

```bash
electroboy phase start <n>
electroboy phase review <n> --pass
electroboy phase test <n> --pass
electroboy phase drift <n> --reason <text>
electroboy phase commit <n> --sha <commit-sha>
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
electroboy validate --command "python -m unittest discover -s tests"
```

Use `--shell-command` only when shell behavior is required.

```bash
electroboy validate --shell-command "python -m unittest discover -s tests"
```

Validation writes `validation-report.md` under the run artifact directory and
stores failures in `validation-review.jsonl`.

## Documentation Commands

```bash
electroboy document
electroboy document --reason "Improve API examples"
electroboy code-approve
```

`document` wraps the final documentation review gate. It requires validation
testing to pass before it can complete. `code-approve` requires the
documentation gate to pass before it records final human completion approval.

## Change Control Commands

```bash
electroboy change open --baseline requirements --reason <text>
electroboy change classify CR-0001 --baseline requirements
electroboy change approve CR-0001 --human-approved
electroboy change reopen CR-0001
electroboy change status
```

`reopen` requires a classified and human-approved request. It invalidates
downstream gates and records affected artifact snapshot refs.

## Issue Commands

```bash
electroboy issues add <file> --id <id> --source <agent> \
  --severity major --summary <text>
electroboy issues transition <file> <id> --status fixed
electroboy issues resolve <file> <id>
electroboy issues list <file>
```

Review issue files are append-only JSONL logs. Reads collapse lifecycle events
to the latest state for each issue id.

## Runtime Configuration

`electroboy.toml` selects agent runtimes.

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

- `electroboy.cli` contains the CLI parser and command handlers.
- `electroboy.models` contains versioned state models.
- `electroboy.state_store` reads and writes `.electroboy` state.
- `electroboy.gates` evaluates deterministic gates.
- `electroboy.artifacts` creates templates and snapshots artifacts.
- `electroboy.planning` parses requirement and phase traceability.
- `electroboy.runtime` selects configured agent runtimes.
- `electroboy.adapters.*` implements runtime adapter contracts.
