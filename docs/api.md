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
  The next stage is the next operator command stage, so approval commands such
  as `plan-approve` are shown when approval is the next step.
- `progress [--once|--follow] [--interval <seconds>]` prints or follows hidden
  progress files for the active run. `monitor` is an alias.
- `serve [--root <path>] [--host <host>] [--port <port>]` starts the local
  browser service. The web interface fetches `/api/health`, shows a workflow
  stage graphic beginning with `project`, lets the operator open or create and
  activate a project for the service through a service-backed directory browser,
  exposes `Start` on the requirements stage after activation, and opens a bottom
  requirements-agent pane with
  streamed output and a multi-line input.
- `requirements [--reason <text>] [--session-id <id>]` starts or resumes
  requirements authoring.
- `requirements-approve` records human and Design Author approval.
- `design [--reason <text>] [--session-id <id>]` starts or resumes design
  authoring.
- `design-review [--interactive]` runs the design-review stage gate and may
  coordinate design-author updates to the detailed-design artifact.
- `design-approve` records human design acceptance.
- `implementation-plan [--reason <text>] [--session-id <id>]` starts or
  resumes planning.
- `plan-approve` records human and Design Author plan approval.
- `test-plan [--reason <text>] [--session-id <id>]` starts or resumes system
  test-plan authoring.
- `test-plan-approve` records human test-plan approval.
- `bug start <issue-reference> [--provider <name>] [--branch [name]]` starts
  a bug-fix run from an upstream issue provider.
- `bug investigate|reproduce|fix|validate [--interactive]` advances the active
  bug-fix run through evidence gathering, repair, validation, and handoff.
- `code [--reason <text>] [--msg <text>] [--review-msg <text>]
  [--blockers-only]
  [--list-phases|--set-phase <n>] [--phased|--interactive|--commit]` starts or
  resumes implementation work.
- `code-review [list [<cr-id>] | <cr-id> | <sha> | <sha1>..<sha2>]
  [--fix-followup|--fix-in-place] [--msg <text>] [--verbose]
  [--interactive]` reviews the current codebase, lists recorded reviews,
  fixes a recorded review, or reviews a commit/range without advancing the
  pipeline.
- `phase commit <n> --sha <commit-sha>` records a reviewed phase commit after
  `code --phased`.
- `validate [--blockers-only] [--interactive]` runs validation test review,
  final validation commands, and writes a validation report.
- `validation-approve` approves validation and commits implementation handoff
  reports.
- `document [--reason <text>] [--interactive]` runs documentation review and
  refinement.
- `code-approve` records final human completion approval.
- `deactivate` leaves an activated project shell environment.
- `report summary` writes or prints a run summary.
- `report trace` writes or prints the activity trace.
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

The local browser service exposes the first GUI slice through stdlib HTTP
handlers. `GET /` serves the workflow page. `GET /api/health` returns
`status: connected`. Each loaded browser page creates an isolated service
context with `POST /api/contexts`; project activation and running agents are
scoped to that returned `context_id`. `GET /api/project?context_id=<id>`
returns the service root, the context's active project root, and terminal
activation command. `POST /api/project/open?context_id=<id>` activates an
existing ElectroBoy project for that browser context, and
`POST /api/project/new?context_id=<id>` initializes a new project with the same
setup helpers used by `electroboy new` before activating it for that context.
`POST /api/project/deactivate?context_id=<id>` clears only that context's
active project. `GET /api/files/browse?path=<path>` returns child directories
for the service-backed browser. The browser opens this directory browser inside
the web UI because ordinary browser file pickers do not reliably expose
absolute local directory paths to JavaScript. GUI activation means the service
records an active project root for the browser context; each requirements
process sources that project's activation script when one exists. `GET
/api/workflow?context_id=<id>` returns the stage list, exposes `Open` and
`Create` for `project`, adds `Deactivate` once a project is active, and exposes
`Start` for `requirements` once a project is active. Other stages remain
inactive until later GUI work wires them up. The requirements agent uses
`POST /api/agents/requirements/start?context_id=<id>`,
`POST /api/agents/requirements/message?context_id=<id>`, and
`GET /api/agents/requirements/events?context_id=<id>`. The event stream is
Server-Sent Events and carries normal child-process output from the same
`electroboy requirements` command path used by the CLI.

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

Approval commands can also be forced; they reset to their target stage,
satisfy predecessor gates, and then approve that stage. There is no separate
low-level stage-reset command; use the workflow command for the stage you want.

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

## Bug Commands

`electroboy bug start <issue-reference>` starts a focused bug-fix workflow
without entering the full requirements/design pipeline. It creates durable
state in `bug.json`, writes `docs/bugs/<bug-id>/issue.md`, and optionally
creates or switches to a focused branch when `--branch` is provided. Omit the
branch name to derive `fix/<number-and-title-slug>`.

Bug issue intake is provider-based. The built-in `generic` provider records
the reference without fetching metadata. The built-in `local` provider reads a
markdown or JSON file. Configured command providers can adapt GitHub, Gerrit,
GitLab, or another tracker by printing normalized JSON.

```toml
[upstream]
default = "tracker"

[upstreams.tracker]
adapter = "command"
command = "tracker-cli"
args = ["issue", "show", "{reference}", "--json"]
domains = ["tracker.example.com"]
env = ["PATH", "TRACKER_TOKEN"]
```

Command providers may return fields such as `title`, `number`, `url`,
`labels`, `body`, `state`, and `author`. ElectroBoy stores the normalized
metadata in the bug record and writes the issue artifact for the agents.

`bug investigate`, `bug reproduce`, `bug fix`, and `bug validate` invoke the
configured agent runtime with the active bug artifacts as context. The
investigation step records known facts and likely root causes. The reproduction
step records a failing test, command, script, or the reason reproduction is not
practical. The fix step keeps code changes scoped to the bug and records root
cause, changed files, behavioral impact, and regression coverage.

`bug validate` can also run explicit operator commands:

```bash
electroboy bug validate --command "python -m pytest tests/test_bug.py"
electroboy bug validate --shell-command "make test && make lint"
```

When validation commands are provided, ElectroBoy runs them directly and writes
`docs/bugs/<bug-id>/validation.md`. Without commands, it invokes the
`bug_validate` agent role and asks the agent to run and record relevant checks.

`bug summary` writes `docs/bugs/<bug-id>/summary.md` with the issue reference,
branch, artifact status, and upstream handoff notes.

Pass `--interactive` to any bug agent step to open a live operator session for
that step. The session is recorded for resume, then control returns to the
operator.

## Phase Commands

`electroboy code` is the normal implementation command. By default, it runs
each remaining planned phase, invokes coding and code review agents, asks the
coding agent to commit reviewed phase changes, records that commit, and
continues until the implementation stage is complete. Use
`--msg "<instruction>"` to append operator guidance to coding-agent
implementation, fix, and commit prompts for that run. Use
`--review-msg "<instruction>"` to append operator guidance only to the
code-review agent prompts for that run; the instruction is reused on every
code-review attempt. Use `--blockers-only` to make only blocker findings
trigger another automatic coding pass; major findings are recorded as deferred
follow-up items.

Before it lists, selects, or runs phases, `electroboy code` ensures the
structured implementation plan exists. If the run's
`docs/implementation-plan.jsonl`, or feature-tagged equivalent, is missing,
ElectroBoy creates it from the Markdown plan's commit breakdown. If no commit
breakdown table is present, it creates one fallback unit per Markdown phase.

`electroboy code --commit` is an expert recovery command for an active
implementation phase. It skips coding and code review, runs the dedicated
coding-agent commit pass immediately, records the commit as operator-forced,
and leaves any open review findings in the ledger. It does not mark code review
as passed.

`electroboy code --interactive` starts or resumes the active implementation
phase, opens the configured interactive coding runtime, records the session,
and then returns control without running code review or phase commit handling.
Use it for operator-guided fine tuning, then run
`electroboy code` to continue the automated implementation loop. If every
planned phase is already committed, `electroboy code --interactive --force`
re-enters the code stage and opens a follow-up implementation session instead
of completing the stage again.

`electroboy design-review --interactive`,
`electroboy code-review --interactive`, `electroboy validate --interactive`,
and `electroboy document --interactive` use the same live-session pattern for
review, validation test-review, and documentation work. They record the
session and return without completing gates or running the automated follow-up
loop.

`electroboy code --list-phases` prints every planned phase plus the recorded
status, review state, and commit for each phase. `electroboy code --set-phase
<n> --reason "<why>"` is an expert recovery command. It records the selected
active phase, records earlier uncommitted phases as `operator-skipped` for
sequencing, and returns without running agents. The next `electroboy code`
starts from that phase and instructs the agents to check earlier phases for
required dependencies before editing. If a required dependency is missing,
the agent must stop and report the gap instead of silently implementing
skipped phases.

For each phase, code review is a bounded automatic loop. The orchestrator gives
the coding agent up to five attempts to resolve blocker and major review
findings. Minor findings are kept as follow-up notes and do not block the
phase. Automated `code` stage review attempts are written under
`docs/reviews/`, for example
`docs/reviews/code-review-phase-2-attempt-1.md`. Feature runs include the
feature tag in those filenames. `docs/code-review.md`, or the feature-tagged
equivalent, remains a latest summary index that points to the per-attempt
reports. Generated review
reports are human-readable pipeline output and should stay out of phase
implementation commits.

`electroboy code-review` audits the current codebase. `electroboy code-review
<sha>` audits one commit. `electroboy code-review <sha1>..<sha2>` audits an
already-written commit range. The range is inclusive, so both endpoint commits
are reviewed. For ranges, the review agent first inspects the final tree at
`<sha2>`, then reviews each commit in order against the approved requirements,
detailed design, implementation plan, and test plan. Findings are written to
an explicit review report such as `docs/code-review-CR-0001.md` and the run's
review issue file. Feature runs use reports such as
`docs/code-review-<feature>-CR-0001.md`. The default mode is review-only and
does not modify files.

Each explicit review gets a stable `CR-####` id. `electroboy code-review list`
prints recorded review ids, targets, finding counts, and report paths.
`electroboy code-review list CR-0001 --verbose` prints the recorded findings
for one review.

`electroboy code-review --fix-followup` and `electroboy code-review <target>
--fix-followup` launch a fix agent when blocker or major findings remain and
ask it to append follow-up commits at `HEAD`. `electroboy code-review <target>
--fix-in-place` instead asks the fix agent to rewrite the offending commit or
range, so it requires an explicit commit, range, or compatible review id
target. `electroboy code-review CR-0001 --fix-followup` uses the recorded
findings from that review id and starts with the fix agent instead of rerunning
review from scratch. Both fix modes require the reviewed commit target to end
at current `HEAD`. New fix attempts require a clean tracked working tree. If a
previous fix pass was interrupted after writing blocker or major findings,
rerunning the same command resumes with the fix agent first
when tracked edits or an in-progress rebase remain. The prompt passes the dirty
path list and rebase state to the agent, tells it to resolve conflicts, and
tells it to continue the rewrite until it succeeds. ElectroBoy reruns range
review, up to five attempts. Minor findings remain recorded but do not force a
fix commit or rewrite.

`electroboy code --phased` is the explicit manual checkpoint mode. It runs one
phase and leaves commit creation or commit recording to the operator.

```bash
electroboy phase commit <n> --sha <commit-sha>
```

`phase commit` verifies that code review has a runtime-backed agent event,
verifies that the supplied SHA is an existing commit reachable from `HEAD`,
checks changed paths against any `Paths:` metadata for the active phase, and
stores it in phase status.

## Validation Commands

`validate` first runs a validation test-review pass against the approved
system test plan. It then runs the configured full test-suite command,
artifact validation commands declared with `Validation:` lines, and any quoted
operator commands passed with `--command`.

```bash
electroboy validate --command "python -m unittest discover -s tests"
```

Use `--shell-command` only when shell behavior is required.

```bash
electroboy validate --shell-command "python -m unittest discover -s tests"
```

Validation requires the run's approved test-plan artifact. It writes the run's
test-review summary to `docs/test-review.md` and detailed validation
test-review attempts under `docs/reviews/`. Each validation rerun uses the next
attempt number, for example `docs/reviews/test-review-validation-attempt-2.md`.
Use `--blockers-only` to let major test-review findings continue as deferred
follow-up items. Failed validation commands remain blockers. Validation writes
the validation report, stores a copy under the run artifact directory, and
stores command failures in `validation-review.jsonl`. In feature runs the
validation report is `docs/validation-report-<feature>.md`.

`validate --interactive` opens only the validation test-review agent. It does
not run validation commands or complete the validation gate.

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
`document --interactive` opens a documentation agent session and returns
without running the documentation review gate.

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
design_review_interactive = "codex-interactive"
coding_interactive = "codex-interactive"
code_review = "codex"
code_review_interactive = "codex-interactive"
range_code_fix_interactive = "codex-interactive"
test_review_interactive = "codex-interactive"
documentation_interactive = "codex-interactive"
bug_investigate_interactive = "codex-interactive"
bug_reproduce_interactive = "codex-interactive"
bug_fix_interactive = "codex-interactive"
bug_validate_interactive = "codex-interactive"
```

The design-author role opens the interactive Codex CLI for requirements,
design, implementation-plan, and test-plan authoring. Roles ending in
`_interactive` open live operator sessions for the corresponding command.
Long-running non-interactive roles receive a progress file under
`.electroboy/shared/runs/<run-id>/progress/`. `electroboy progress` follows
those files from another activated shell. When review agents report structured
issues, ElectroBoy appends prominent progress lines such as
`ISSUE FOUND - PH2-CODE-001 - MAJOR - <summary>` or
`ISSUE VERIFIED - PH2-CODE-001 - MAJOR - <summary>`. Progress files are
informational; ElectroBoy lets agent runtimes continue until they exit or the
operator interrupts them. Review prompts prohibit modifying project files other
than the progress file, and explicit runtime sandbox options still override the
default sandbox choice. Automated review roles must return a final JSON object
with `ok`, `final_message`, and `issues`; malformed or free-form review output
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
- `electroboy.service` runs the local browser service, workflow page, health
  endpoint, and requirements-agent process bridge.
- `electroboy.adapters.*` implements runtime adapter contracts.
