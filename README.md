# ElectroBoy

ElectroBoy is an AI agent pipeline for disciplined AI-assisted software
development. It turns an informal agent workflow into an ordered, auditable
pipeline:

1. Define requirements with the human operator and design author agent.
2. Create and review the detailed design.
3. Approve an implementation plan with small phases.
4. Implement one phase at a time.
5. Run code review, validation test review, validation, and documentation
   review.
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

Bash completion can be enabled from a checkout:

```bash
source <(./electroboy completion bash)
```

## Workflow

Create a pipeline project and enter its project environment:

```bash
./electroboy new path/to/project
source path/to/project/.electroboy/bin/activate
electroboy status
```

`new` creates or enters the target directory. If the directory is not already
inside a Git worktree, it initializes a GitHub-ready repository. Existing
repositories are reused instead of nesting a new repository. The command also
creates the standard pipeline artifacts, creates `.electroboy/`, and
installs `path/to/project/.electroboy/bin/activate`.

Use a meta-project when several related repositories need shared agent
context. Run commands from the top-level workspace, register repositories, and
switch the active target with `start`:

```bash
electroboy meta init ~/ORNL/Quantum/openQSE
source ~/ORNL/Quantum/openQSE/.electroboy/bin/activate
electroboy add QFw qhw-characterization
electroboy start QFw
electroboy requirements
electroboy start qhw-characterization
electroboy design
```

`meta init <path>` creates the meta-project registry explicitly and installs
`<path>/.electroboy/bin/activate`. Source that activation script once from the
workspace root, then use `add <repo> [repo...]` to register one or more
repositories and `start <repo>` to switch the active target. `add` and `start`
require that registry, so running either command from the wrong root fails
instead of creating unexpected state. There is no separate `end` command. If
the repository is not already registered, `start` registers it, initializes its
ElectroBoy project state when needed, and makes it active. Stage artifacts and
approval commits belong to the active target repository. Agent sessions run from
the meta-project root and receive the active repo plus the registered repo list
in their prompts.

When the ElectroBoy source checkout has changed, refresh the meta-project
runtime from that checkout before rerunning stages. Running the refresh from
the checkout avoids reinstalling an older activated `electroboy` runtime over
itself:

```bash
cd ~/ORNL/Quantum/openQSE/electroboy
./electroboy meta init ~/ORNL/Quantum/openQSE
source ~/ORNL/Quantum/openQSE/.electroboy/bin/activate
electroboy design-review --force --reason "Rerun with coordinated design review updates"
electroboy design-review
```

After the runtime has been refreshed, normal meta-project work can continue
from the meta-project root.

Start feature work when you want the same from-scratch pipeline with feature
metadata attached. ElectroBoy prompts for a feature artifact name in an
interactive shell, or derives one from the title when input is not interactive.
Pass `--name <feature>` to choose it explicitly. Feature runs write
feature-tagged artifacts such as `docs/requirements-<feature>.md`,
`docs/detailed-design-<feature>.md`, `docs/implementation-plan-<feature>.md`,
and `docs/test-plan-<feature>.md`; later review and report artifacts use the
same suffix. If those files already exist, ElectroBoy warns before amending
them, or accepts the reuse directly with `--amend`.

Use `--branch` when ElectroBoy should create or switch to a focused feature
branch before the normal stages begin. Omit the branch name to derive
`feature/<slug>` from the title, or pass an explicit branch name:

```bash
electroboy feature start "Add dashboard export" --branch
electroboy feature start "Add admission and scheduling to the QFw" --name adm-sched-v01 --branch adm-sched-v01
electroboy requirements
electroboy requirements-approve
electroboy design
electroboy test-plan
electroboy design-review
electroboy design-approve
electroboy implementation-plan
electroboy plan-approve
electroboy code
electroboy test-plan
electroboy test-plan-approve
electroboy validate
electroboy validation-approve
electroboy document
electroboy code-approve
```

During feature runs with a branch, mutating agents are instructed to verify the
branch before editing each git repository they touch. If they need to edit a
nested repository and the feature branch is missing there, they create it with
`git switch -c <branch>` rather than editing on the wrong branch.

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

`design-review` coordinates the design-review agent with an automatic
design-author update pass when blocker or major findings require changes to
the detailed design. The review agent is instructed not to modify files except
for its run progress file. The orchestrator records design updates in
`docs/design-review-updates.md`, or `docs/design-review-updates-<feature>.md`
for feature runs, then reruns design review until it passes or still blocks.

Create and approve the implementation plan:

```bash
electroboy implementation-plan
electroboy plan-approve
```

Draft the system test plan whenever useful during design or planning:

```bash
electroboy test-plan
```

`test-plan` updates `docs/test-plan.md`, or the feature-specific test plan in a
feature run. It can be run while the active stage is still design,
implementation planning, or implementation so system test ideas are captured
when they arise. After implementation completes, run `test-plan` again to
review the final validation surface, then approve it:

```bash
electroboy test-plan
electroboy test-plan-approve
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
electroboy test-plan
electroboy test-plan-approve
electroboy validate
electroboy validation-approve
electroboy document
electroboy code-approve
```

The automated code loop expects approved baseline artifacts to already be
committed. Commit the approved requirements, design, implementation plan,
generated project files, and any hand-authored baseline files before running
`code`.

`code` starts or resumes the fully automated implementation loop. It selects
the active or next planned phase, invokes the configured coding agent, runs up
to five code-review/fix passes, asks the coding agent to commit the reviewed
phase changes, records the resulting commit, and continues until every planned
phase is complete. Blocker and major findings stop the phase after the retry
limit. Minor findings are recorded for follow-up and do not block progress.

Pass `--msg "<instruction>"` to append an operator instruction to the coding
agent's implementation, fix, and commit prompts for that `code` run. The
message cannot broaden the active phase scope. Coding and fix passes leave
changes in the working tree; only the dedicated commit pass may create git
commits.

Pass `--review-msg "<instruction>"` to append an operator instruction only to
the code-review agent prompts for that `code` run. The instruction is reused
on every code-review attempt and is not passed to coding, commit, or test
review agents.

Use `code --list-phases` to inspect planned implementation phases and the
recorded state for each phase. Expert recovery can move the active phase with
`code --set-phase <n> --reason "<why>"`. Earlier uncommitted phases are
recorded as `operator-skipped` for sequencing, not as committed. The command
records the operator override, then the next `electroboy code` starts from
that phase and tells the agents to check earlier phases for required
dependencies before editing. If a required dependency is missing, the agent
must stop and report the gap instead of silently filling skipped phases.

Use `code --interactive` to open an interactive coding-agent shell for the
active or next planned phase. This is for operator-guided fine tuning. The
interactive session does not run review agents, create phase commits, or
advance the implementation loop; after exiting, run `electroboy code` to
continue automated review and commit handling.

Automated `code` stage review attempts are written to `docs/reviews/`, for
example `docs/reviews/code-review-phase-2-attempt-1.md`. Feature runs include
the feature tag in those filenames. The top-level `docs/code-review.md` file
remains a latest-summary index that points to the per-attempt reports.
Generated review reports are human-readable pipeline output and should not be
included in phase implementation commits.

Use `code-review` to audit the current codebase, a single commit, or an
already-written commit range without advancing the pipeline:

```bash
electroboy code-review
electroboy code-review <sha>
electroboy code-review <sha1>..<sha2>
```

When no target is provided, the review agent inspects the current codebase. A
single SHA reviews that commit. A range is inclusive, so both endpoint commits
are reviewed. For ranges, the review agent first inspects the final tree at
`<sha2>`, then reviews each commit in order against the approved requirements,
detailed design, implementation plan, and test plan. Findings are recorded in
an explicit review report such as `docs/code-review-CR-0001.md` and in the
active run's internal review issue file. Feature runs use reports such as
`docs/code-review-<feature>-CR-0001.md`. The default mode is review-only and
does not modify files.

Each explicit review gets a stable `CR-####` id. Use `list` to discover prior
reviews, and `--verbose` to print the recorded findings:

```bash
electroboy code-review list
electroboy code-review list CR-0001 --verbose
```

Use `--fix-followup` when you want ElectroBoy to preserve the reviewed commits
and launch a fix agent that appends follow-up commits at `HEAD`:

```bash
electroboy code-review --fix-followup
electroboy code-review <sha> --fix-followup
electroboy code-review <sha1>..<sha2> --fix-followup
electroboy code-review CR-0001 --fix-followup
```

Use `--fix-in-place` only when you want ElectroBoy to launch a fix agent that
rewrites the current branch range:

```bash
electroboy code-review <sha> --fix-in-place
electroboy code-review <sha1>..<sha2> --fix-in-place
electroboy code-review CR-0001 --fix-in-place
```

Both fix modes require the reviewed commit target to end at the current `HEAD`.
`--fix-in-place` requires an explicit commit, range, or compatible review id
target. When a `CR-####` id is provided, ElectroBoy uses the recorded findings
from that review and starts with the fix agent instead of rerunning review from
scratch. New fix attempts require a clean tracked working tree. If an earlier
fix pass was interrupted after writing blocker or major findings, rerun the
same command; ElectroBoy resumes with the fix agent first when tracked edits
or an in-progress rebase
remain. The fix prompt tells the agent which paths are already dirty, tells it
to resolve rebase conflicts, and tells it to continue the rewrite until it
succeeds. `--fix-followup` must preserve the reviewed commits and add new fix
commits after the range. `--fix-in-place` must fold blocker and major fixes
into the offending commits rather than creating follow-up commits. ElectroBoy
then reruns the range review, up to five attempts. Minor findings remain
recorded but do not require a fix commit or rewrite.

Long-running non-interactive passes write hidden progress files under the
active run. From another activated shell, use `progress` to watch concise agent
heartbeats without manually tailing files:

```bash
electroboy progress
```

`electroboy monitor` is an alias. In an interactive terminal the command
follows live updates by default; use `--once` to print the current snapshot and
exit.

When a review agent reports structured issues, ElectroBoy appends prominent
lines such as `ISSUE FOUND - PH2-CODE-001 - MAJOR - <summary>` and
`ISSUE VERIFIED - PH2-CODE-001 - MAJOR - <summary>` to the relevant progress
file.

Progress files are informational only. ElectroBoy does not stop an agent just
because progress output pauses; the agent runs until it exits or the operator
interrupts it.

After `code` completes, revisit and approve the run's test-plan artifact.
Validation requires that approved system test plan, runs a validation
test-review pass first, then runs the full test suite plus artifact-declared
validation commands, and writes the run's validation report. Each validation
test-review rerun writes the next report under `docs/reviews/`, such as
`docs/reviews/test-review-validation-attempt-2.md`. If validation test-review
or validation commands fail with blocker findings, the pipeline opens a
validation-fix phase and returns to `code`. After validation passes, run
`validation-approve` to commit the implementation log, implementation report,
and validation report before documentation review. `document` runs the
documentation refinement and review phase. If a review or validation issue
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
`code --interactive` opens an interactive coding-agent shell for the active or
next planned phase and leaves the implementation loop paused when the shell
exits.

Expert users can force a workflow command when adopting or repairing an
existing project. `--force` resets the state machine to that command's stage
and marks all previous gates satisfied so the command can run:

```bash
electroboy implementation-plan --force
electroboy code --force
electroboy validate --force
```

The low-level `stage <stage> --force` command remains available as an alias
for resetting directly to a named stage. A `--reason` can be provided on any
forced command and is recorded in the decision log.

Resume an interrupted run from the same project:

```bash
source path/to/project/.electroboy/bin/activate
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

Authoring agents start with narrow prompts: each stage reads only its approved
context documents and updates its stage artifact by default. In feature runs
those prompts name the feature-specific artifacts. If the operator asks the
agent to update an upstream artifact anyway, ElectroBoy compares the known
authoring artifacts after the session, reopens the earliest affected stage,
and asks for the required reapproval.

Leave the project environment:

```bash
electroboy deactivate
```

The activation script prefixes the shell prompt with the project directory
name, and can also enter a configured Python environment. The pipeline uses
`electroboy deactivate` instead of bare `deactivate` so it can restore the
prompt and does not conflict with Python virtual environment behavior.

After activation, use `electroboy` without `./` so the project environment
selects the active project. In Bash, activation also registers command and
option tab completion for `electroboy` and `ai-pipeline`.

The `./ai-pipeline` command is an alias.

## Why This Exists

AI coding agents are useful, but they can drift when the project lacks a clear
process. This tool provides the process layer around those agents.

It helps by:

- Enforcing requirements before design, and design before implementation.
- Preventing an operator or agent from jumping into the middle of the pipeline.
- Breaking implementation into small reviewed phases instead of one large code
  dump.
- Keeping code review and validation test review as separate responsibilities.
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
- Generated project activation scripts under `<project>/.electroboy/bin/activate`.
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
- Automated phase start, code review, drift, and commit recording, plus
  manual `phase commit` for phased mode.
- Explicit `code-review` audits for the current codebase, a single commit, or
  already-written commit ranges, with `CR-####` ids, list/verbose output, and
  optional follow-up or in-place fix/review loops.
- Final validation and documentation review gates.
- Public workflow commands that reopen earlier baselines with `--reason`.
- Expert command-level stage resets with `electroboy <command> --force`.
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
predecessor gates, unless an expert operator uses the explicit command-level
`--force` override.

Project-scoped stage commands require an active ElectroBoy project before they
run. If you are using a normal project, create or enter it with
`electroboy new` or `electroboy feature start`, then source
`<project>/.electroboy/bin/activate`. If you are using a meta-project, source
the meta activation script and run `electroboy start <repo>` before authoring,
review, implementation, validation, or approval commands. Merely changing into
the project or meta-project directory is not enough; unactivated stage commands
are blocked unless an explicit `--root` is provided by automation.

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
electroboy test-plan --reason "Validation needs a new system scenario"
electroboy document --reason "Improve API examples"
```

The orchestrator records a change-control event, asks for approval when
downstream gates would be invalidated, and resumes from the reopened stage.

Use `<command> --force` only when an expert operator intentionally wants to
reset the state machine to that command's stage. For example,
`electroboy implementation-plan --force` resets the active stage to `plan`,
records a forced reset decision, marks all predecessor gates satisfied, records
predecessor snapshots, and starts implementation-plan authoring. Approval
commands work the same way, then approve their target stage.

## Agent Runtime Configuration

The design supports configurable agent runtimes. Codex is the default target,
but the pipeline is intended to support any CLI that can satisfy the adapter
contract, including Claude or a local agent command.

A compatible agent CLI must be able to:

- Run non-interactively.
- Receive a role prompt and context bundle.
- Return output that can be parsed into the pipeline's `AgentResult`.
- For automated review roles, return a final JSON object with `ok`,
  `final_message`, and `issues`; use `issues: []` when there are no findings.
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
design_author_update = "codex"
design_review = "codex"
coding = "codex"
coding_interactive = "codex-interactive"
code_review = "claude"
test_review = "codex"
documentation = "codex"

[environment]
activate_python = true
python_activate = ".venv/bin/activate"
python_managed_by_pipeline = false
```

The design-author role opens the interactive Codex CLI for requirements,
design, implementation-plan, and test-plan authoring. The coding-interactive
role opens the interactive Codex CLI for `code --interactive`. Long-running
non-interactive roles receive a progress file and run with enough filesystem
access to update that file unless the runtime configuration supplies an
explicit sandbox option. Review prompts still prohibit modifying project files
other than the progress file.
Automated review roles also receive a structured output contract. If their
final response is not valid JSON in that shape, ElectroBoy blocks the stage and
stores the raw response for debugging instead of trying to infer findings from
free-form prose.

If `activate_python` is true,
`source path/to/project/.electroboy/bin/activate` also enters the configured
Python environment. `electroboy deactivate` restores the pipeline context and
only deactivates the Python environment when the pipeline owns that activation.

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

Ignored files are not committed to git:

- `.electroboy/local/activation.json` stores shell activation state.
- `.electroboy/local/sessions/` stores provider session references.
- `.electroboy/local/raw/` stores redacted raw runtime streams.
- `.electroboy/local/logs/` stores local diagnostic logs.
- `.electroboy/shared/runs/<run-id>/progress/` stores live agent progress
  heartbeats consumed by `electroboy progress`.

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
