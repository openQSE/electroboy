# API Documentation

## Public CLI

The public interface is the `electroboy` command. `ai-pipeline` is an alias
for the same CLI. Source checkouts include `./electroboy` and `./ai-pipeline`
wrappers.

Operator workflow commands:

- `new <path>` creates a GitHub-ready project, initializes artifacts, creates
  `.electroboy/`, and installs `<path>/bin/activate`.
- `status` prints active stage, next stage, active phase, completed gates,
  invalidated gates, open requests, open issues, and blocked gates.
- `requirements [--reason <text>]` starts or resumes requirements authoring.
- `requirements-approve` records human and Design Author approval.
- `design [--reason <text>]` starts or resumes design authoring.
- `design-review` runs the design-review stage gate.
- `design-approve` records human design acceptance.
- `implementation-plan [--reason <text>]` starts or resumes planning.
- `plan-approve` records human and Design Author plan approval.
- `code [--reason <text>] [--phased]` starts or resumes implementation work.
- `phase commit <n> --sha <commit-sha>` records a reviewed phase commit after
  `code --phased`.
- `validate` runs final validation commands and writes a validation report.
- `validation-approve` approves validation and commits implementation handoff
  reports.
- `document [--reason <text>]` runs documentation review and refinement.
- `code-approve` records final human completion approval.
- `deactivate` leaves an activated project shell environment.
- `report summary` writes or prints a run summary.
- `report trace` writes or prints the activity trace.
- `stage <stage> --force --reason <text>` forces the active stage for expert
  recovery and existing-project adoption.
- `completion bash` prints the Bash completion script.

Earlier operator workflow commands reopen baselines when `--reason` is
provided and the requested stage is behind the active stage. The orchestrator
records change-control and baseline-invalidation records before resuming from
the reopened stage.

Authoring commands use scoped prompts. `requirements` targets
`docs/requirements.md`, `design` targets `docs/detailed-design.md`, and
`implementation-plan` targets `docs/implementation-plan.md`. If the operator
asks the authoring agent to update an upstream authoring artifact, the
orchestrator detects the changed artifact after the session, reopens the
earliest affected stage, invalidates downstream gates, and prints the next
approval command.

Authoring commands also maintain local provider session records under
`.electroboy/local/sessions/<run-id>/<stage>/<role>.json`. When a record
contains a provider session id and the configured runtime supports resume,
ElectroBoy passes that id back to the runtime. Codex interactive sessions use
`codex resume <session-id>`. When no provider session id is available,
ElectroBoy starts a new session with recovery context from the local session
record, shared session summary when present, and the current stage artifact.

## Stage Commands

The normal workflow advances through stage-specific commands such as
`requirements-approve`, `design-review`, `design-approve`, `plan-approve`,
`code`, `validate`, and `document`.

`stage` is an expert escape hatch for setting the active stage directly:

```bash
electroboy stage implementation --force --reason "Adopting existing project"
```

The command records a decision and activity event, but it does not mark
skipped gates as complete.

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
`<project>/bin` to `PATH`, prefixes the shell prompt with the project name,
defines an `electroboy` shell function, and registers Bash completion when Bash
is available. The generated wrappers pass `--root <project>` to the Python
module and use project-local runtime code when available, including the
`ai-pipeline` wrapper.

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
electroboy phase commit <n> --sha <commit-sha>
```

`phase commit` verifies that code review and test review have runtime-backed
agent events, verifies that the supplied SHA is an existing commit reachable
from `HEAD`, verifies that the commit message identifies the phase and
objective, checks changed paths against any `Paths:` metadata for the active
phase, and stores it in phase status.

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

Validation writes `docs/validation-report.md`, stores a copy under the run
artifact directory, and stores failures in `validation-review.jsonl`.

`validation-approve` commits `docs/implementation-log.md`,
`docs/implementation-report.md`, and `docs/validation-report.md`, then advances
the active stage to documentation review.

## Documentation Commands

```bash
electroboy document
electroboy document --reason "Improve API examples"
electroboy code-approve
```

`document` wraps the final documentation review gate. It requires validation
testing to pass before it can complete. `code-approve` requires the
documentation gate to pass before it records final human completion approval.

## Runtime Configuration

`electroboy.toml` selects agent runtimes.

```toml
[runtime]
default = "codex"

[runtimes.codex]
adapter = "codex_exec"
command = "codex"
args = ["exec", "--json"]

[runtimes.codex-interactive]
adapter = "codex_interactive"
command = "codex"

[roles]
design_author = "codex-interactive"
code_review = "codex"
```

The design-author role opens the interactive Codex CLI. Codex review roles run
in `read-only` sandbox mode by default. Coding and documentation-writing roles
run in `workspace-write` mode unless the runtime sets an explicit sandbox
option.

## Public Python Modules

- `electroboy.cli` contains the CLI parser and command handlers.
- `electroboy.models` contains versioned state models.
- `electroboy.state_store` reads and writes `.electroboy` state.
- `electroboy.gates` evaluates deterministic gates.
- `electroboy.artifacts` creates templates and snapshots artifacts.
- `electroboy.planning` parses requirement and phase traceability.
- `electroboy.runtime` selects configured agent runtimes.
- `electroboy.adapters.*` implements runtime adapter contracts.
