# API Documentation

## Public CLI

The public interface is the `electroboy` command. `ai-pipeline` is an alias
for the same CLI. Source checkouts include `./electroboy` and `./ai-pipeline`
wrappers.

Operator workflow commands:

- `new <path>` creates a GitHub-ready project, initializes artifacts, creates
  `.electroboy/`, and installs `<path>/.electroboy/bin/activate`.
- `meta init <path>` initializes an explicit meta-project registry and installs
  `<path>/.electroboy/bin/activate`.
- `add <path> [path...]` registers one or more repositories in the current
  meta-project.
- `start <repository>` switches the active target repository for meta-project
  work, registering and initializing it when needed.
- `feature start <title-or-issue-url> [--name <feature>] [--amend]
  [--branch [name]]` starts feature work through the standard pipeline,
  chooses feature-scoped artifact paths, and optionally creates or switches to
  a feature branch.
- `status` prints the active stage, the command for the active stage, next
  stage, active phase, completed gates, invalidated gates, open requests, open
  issues, and blocked gates. In meta-project mode it also prints the meta root,
  active repo, and registered repos.
- `progress [--once|--follow] [--interval <seconds>]` prints or follows hidden
  progress files for the active run. `monitor` is an alias.
- `requirements [--reason <text>] [--session-id <id>]` starts or resumes
  requirements authoring.
- `requirements-approve` records human and Design Author approval.
- `design [--reason <text>] [--session-id <id>]` starts or resumes design
  authoring.
- `design-review` runs the design-review stage gate and may coordinate
  design-author updates to the detailed-design artifact.
- `design-approve` records human design acceptance.
- `implementation-plan [--reason <text>] [--session-id <id>]` starts or
  resumes planning.
- `plan-approve` records human and Design Author plan approval.
- `test-plan [--reason <text>] [--session-id <id>]` starts or resumes system
  test-plan authoring.
- `test-plan-approve` records human test-plan approval.
- `code [--reason <text>] [--msg <text>] [--phased]` starts or resumes
  implementation work.
- `code-review <sha1>..<sha2> [--fix-followup|--fix-in-place] [--msg <text>]`
  reviews an inclusive commit range without advancing the pipeline.
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
- `stage <stage> --force [--reason <text>]` resets directly to a named stage
  for expert recovery and existing-project adoption.
- `completion bash` prints the Bash completion script.

Workflow commands also accept `--force` for expert recovery. A forced command
resets the state machine to that command's stage, records a decision, marks all
predecessor gates satisfied, records predecessor snapshots, and then runs the
command normally. `--reason <text>` can be supplied when the command exposes it
and is stored with the decision record.

Project-scoped stage commands require an active ElectroBoy project. For normal
projects, run `electroboy new <path>` or `electroboy feature start ...` and
source `<project>/.electroboy/bin/activate`. For meta-projects, source the
meta-project activation script and run `electroboy start <repo>` before
authoring, review, implementation, validation, or approval commands. Changing
into the project directory without sourcing the activation script does not
activate the project; stage commands block unless automation passes an
explicit `--root`.

Earlier operator workflow commands reopen baselines when `--reason` is
provided and the requested stage is behind the active stage. The orchestrator
records change-control and baseline-invalidation records before resuming from
the reopened stage.

Authoring commands use scoped prompts. `requirements` targets the run's
requirements artifact, `design` targets the run's detailed-design artifact,
`implementation-plan` targets the run's implementation-plan artifact, and
`test-plan` targets the run's test-plan artifact. Normal runs use the canonical
paths under `docs/`; feature runs use `docs/*-<feature>.md` paths recorded in
the run's `feature.json`. `test-plan` may run before it is the active stage so
operators can capture system test cases during design, planning, or
implementation. If the operator asks the authoring agent to update an upstream
authoring artifact, the orchestrator detects the changed artifact after the
session, reopens the earliest affected stage, invalidates downstream gates,
and prints the next approval command.

Authoring commands also maintain local provider session records under
`.electroboy/local/sessions/<run-id>/<stage>/<role>.json`. When a record
contains a provider session id and the configured runtime supports resume,
ElectroBoy passes that id back to the runtime. Codex interactive sessions use
`codex resume <session-id>`. When no provider session id is available,
ElectroBoy starts a new session with recovery context from the local session
record, shared session summary when present, and the current stage artifact.
Passing `--session-id <id>` writes that id to the stage's local session record
before the agent starts. If a record already exists for the same run, stage,
and role, the explicit id replaces it and becomes the id used by later
authoring resumes.

`feature start` records feature metadata in the current run's `feature.json`.
When `--name` is omitted in an interactive shell, ElectroBoy prompts for the
feature artifact name. In non-interactive use, it derives a slug from the title
or issue URL. The slug controls paths such as `docs/requirements-<slug>.md`,
`docs/detailed-design-<slug>.md`, `docs/implementation-plan-<slug>.md`, and
`docs/test-plan-<slug>.md`. Review and report artifacts, including
`docs/code-review-<slug>.md` and `docs/test-review-<slug>.md`, use the same
suffix. If any feature artifact already exists, ElectroBoy warns before
amending it; use `--amend` to accept reuse without an interactive prompt.

When `--branch` is provided, the command blocks tracked uncommitted changes
before creating or switching branches. Untracked files do not block feature
branch setup. `--branch` without a value derives `feature/<slug>` from the
title or issue URL. `--branch <name>` uses the exact branch name provided.
During that feature run, mutating agent prompts tell the agent to verify that
each git repository it edits, including nested repositories, is on the feature
branch. If the branch does not exist in a repository it must edit, the agent is
instructed to create it with `git switch -c <branch>`.
After intake, the normal workflow begins at `electroboy requirements` unless
an existing run is already active at another stage.

`design-review` writes the run's design-review summary and design-review update
log. The update log is `docs/design-review-updates.md` for normal runs and
`docs/design-review-updates-<feature>.md` for feature runs. If the review
agent reports blocker or major findings, ElectroBoy invokes a non-interactive
design-author update turn to modify the run's detailed-design artifact, logs
the resulting diff, and reruns review within a bounded loop.

`meta init`, `add`, and `start` enable meta-project mode. The registry is
stored in `.electroboy/shared/repositories.json` under the meta-project root.
`meta init` also installs the meta activation environment under
`.electroboy/bin/`. `add` registers one or more repositories in one command.
`add` and `start` require an initialized registry. `start` sets the active
target repository; later stage commands operate on that target repo's
`.electroboy` state and `docs/` artifacts. Agent runtimes execute from the
meta-project root and receive prompt context that names the active target repo
and every registered repo. Running `start <other-repo>` context-switches
directly; no `end` command is required.

## Stage Commands

The normal workflow advances through stage-specific commands such as
`requirements-approve`, `design-review`, `design-approve`, `plan-approve`,
`code`, `validate`, and `document`.

`--force` is the expert escape hatch for resetting the state machine to a
specific workflow point:

```bash
electroboy implementation-plan --force
electroboy code --force
electroboy validate --force
```

The low-level `stage <stage> --force [--reason <text>]` command uses the same
reset behavior when a named stage is more convenient. Approval commands can
also be forced; they reset to their target stage, satisfy predecessor gates,
and then approve that stage.

## Project Environment Commands

```bash
./electroboy new path/to/project
source path/to/project/.electroboy/bin/activate
electroboy status
electroboy deactivate
```

`new` creates the target directory when needed. If the target is not already
inside a Git worktree, it initializes a repository. Existing repositories are
reused. Activation exports `ELECTROBOY_PROJECT_ROOT`, prepends
`<project>/.electroboy/bin` to `PATH`, prefixes the shell prompt with the
project name, defines an `electroboy` shell function, and registers Bash
completion when Bash is available. The generated wrappers pass
`--root <project>` to the Python module and use project-local runtime code
when available, including the `ai-pipeline` wrapper.

If `.electroboy/project.toml` enables Python activation, the activation
script sources the configured Python environment. It only deactivates that
Python environment when the pipeline owns that activation.

## Phase Commands

`electroboy code` is the normal implementation command. By default, it runs
each remaining planned phase, invokes coding, code review, and test review
agents, asks the coding agent to commit reviewed phase changes, records that
commit, and continues until the implementation stage is complete. Use
`--msg "<instruction>"` to append operator guidance to coding-agent
implementation, fix, and commit prompts for that run.

For each phase, code review and test review are bounded automatic loops. The
orchestrator gives the coding agent up to five attempts to resolve blocker and
major review findings. Minor findings are kept as follow-up notes and do not
block the phase. Code review summaries are written to `docs/code-review.md`;
test review summaries are written to `docs/test-review.md`. Feature runs use
the corresponding `docs/code-review-<feature>.md` and
`docs/test-review-<feature>.md` files.

`electroboy code-review <sha1>..<sha2>` audits an already-written commit range.
The range is inclusive, so both endpoint commits are reviewed. The review
agent first inspects the final tree at `<sha2>`, then reviews each commit in
order against the approved requirements, detailed design, implementation plan,
and test plan. Findings are written to `docs/code-review.md` and the run's
range review issue file. The default mode is review-only and does not modify
files.

`electroboy code-review <sha1>..<sha2> --fix-followup` launches a fix agent
when blocker or major findings remain and asks it to append follow-up commits
at `HEAD`. `electroboy code-review <sha1>..<sha2> --fix-in-place` instead asks
the fix agent to rewrite the offending commits. Both fix modes require the
range end to be current `HEAD`. New fix attempts require a clean tracked
working tree. If a previous fix pass was interrupted after writing blocker or
major findings and left tracked edits behind, rerunning the same command
resumes with the fix agent first, passes the dirty path list into the prompt,
and then reruns review. ElectroBoy reruns range review, up to five attempts.
Minor findings remain recorded but do not force a fix commit or rewrite.

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

Validation requires the run's approved test-plan artifact. It writes the run's
validation report, stores a copy under the run artifact directory, and stores
failures in `validation-review.jsonl`. In feature runs the validation report is
`docs/validation-report-<feature>.md`.

`validation-approve` commits the run's implementation log, implementation
report, and validation report, then advances the active stage to documentation
review.

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
design_author_update = "codex"
code_review = "codex"
```

The design-author role opens the interactive Codex CLI. Long-running
non-interactive roles receive a progress file under
`.electroboy/shared/runs/<run-id>/progress/`. `electroboy progress` follows
those files from another activated shell. Progress files are informational;
ElectroBoy lets agent runtimes continue until they exit or the operator
interrupts them. Review prompts prohibit modifying project files other than the
progress file, and explicit runtime sandbox options still override the default
sandbox choice. Automated review roles must return a final JSON object with
`ok`, `final_message`, and `issues`; malformed or free-form review output
blocks the stage instead of being interpreted.

## Public Python Modules

- `electroboy.cli` contains the CLI parser and command handlers.
- `electroboy.models` contains versioned state models.
- `electroboy.state_store` reads and writes `.electroboy` state.
- `electroboy.gates` evaluates deterministic gates.
- `electroboy.artifacts` creates templates and snapshots artifacts.
- `electroboy.planning` parses implementation phases and optional
  traceability hints.
- `electroboy.runtime` selects configured agent runtimes.
- `electroboy.adapters.*` implements runtime adapter contracts.
