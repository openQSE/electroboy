# Feature Requests

This document records proposed ElectroBoy features before they are promoted to
requirements or implementation plans. Each feature request is kept in its own
collapsible section so proposals can grow without making the document hard to
scan.

<details>
<summary>Bug Fixing Workflow</summary>

## Purpose

Bug fixing should be a first-class workflow separate from the larger
requirements, design, implementation, validation, and documentation pipeline.
Bug work usually starts from a GitHub issue and begins with uncertainty. The
first deliverable is evidence: what failed, whether the failure can be
reproduced, where the likely cause lives, and what proof is needed before a
fix is accepted.

The workflow should help a developer use AI for investigation and repair while
preserving the discipline expected from ordinary bug work. A complete bug fix
should link back to the issue, explain the root cause, include a regression
test when practical, validate the fix, and land through a focused branch and
commit.

## Proposed CLI

```bash
electroboy bug start <issue-url> --branch
electroboy bug investigate
electroboy bug reproduce
electroboy bug fix
electroboy bug validate
electroboy bug summary
```

## Command Behavior

### `electroboy bug start <issue-url> --branch`

Starts a bug-fix run from a GitHub issue URL.

The command should capture issue metadata such as title, URL, issue number,
labels, reported behavior, expected behavior, and any linked stack traces or
logs. It should create durable bug-run state under `.electroboy/` so the
investigation can be resumed later.

When `--branch` is provided, ElectroBoy should create or switch to a focused
branch for the fix. A reasonable branch name is derived from the issue number
and title, such as `fix/123-short-issue-slug`. The command should refuse to
hide unrelated local changes. If the worktree is dirty, it should either record
that state clearly or ask the operator to resolve it before branch creation.

Expected output should include the active issue, branch name, current bug-run
id, and the next command to run.

### `electroboy bug investigate`

Investigates the issue before attempting a fix.

An agent can inspect the issue text, repository code, recent changes, failing
logs, related tests, and nearby documentation. The goal is not to patch code
yet. The goal is to produce an investigation note that records what is known,
what is still unknown, and which hypotheses are plausible.

The investigation artifact should include suspected files or components,
commands already tried, relevant observations, and a ranked list of likely root
causes. It should also state whether the issue appears reproducible from the
available information.

This step is valuable because it prevents the workflow from jumping directly to
a plausible-looking patch without evidence.

### `electroboy bug reproduce`

Attempts to reproduce the reported failure.

The preferred outcome is a failing regression test, a minimal failing command,
or a small reproduction script that fails before the fix. The reproduction
artifact should record the exact command, environment assumptions, observed
failure, and expected behavior.

If the bug cannot be reproduced, the command should record why. Examples
include missing external services, nondeterministic timing, unavailable
customer data, or a report that lacks enough detail. In that case, the workflow
can continue only with an explicit note that the fix will rely on code review,
reasoned analysis, and targeted validation instead of a known failing test.

The key gate is that a bug fix is not considered ready unless it has either a
regression test or a documented reason why a regression test is not practical.

### `electroboy bug fix`

Creates the fix and updates or adds regression coverage.

This command should use the investigation and reproduction artifacts as input.
The agent should keep the change scoped to the issue, avoid unrelated
refactors, and preserve the existing project style. If a failing test or
reproduction command exists, the fix should make that test pass.

The command should record a fix note with the root cause, changed files,
behavioral impact, and test coverage added. If the implementation discovers
that the earlier investigation was wrong, it should update the bug-run state
instead of silently changing direction.

The fix should remain on the bug branch created by `bug start --branch`, unless
the operator explicitly chooses a different branch strategy.

### `electroboy bug validate`

Validates the fix before upstream handoff.

Validation should run the regression test first, then any relevant broader
test commands. The command should record exactly what was run, the exit status,
and important output. For small fixes this may be one focused test module. For
shared behavior or high-risk changes, it may include the full unit suite or
additional integration checks.

If validation fails, ElectroBoy should keep the bug run active and record the
failure as a blocking issue. The next action is another investigation or fix
pass, not a summary that claims completion.

### `electroboy bug summary`

Prepares the upstream handoff.

The summary should collect the issue link, branch name, reproduction result,
root cause, fix summary, regression coverage, validation commands, and commit
or pull request status. It should be suitable for a pull request body or a
final issue comment.

When the fix is ready, the workflow should support a focused commit that
references the issue. A future extension could open a pull request, link it to
the issue, and include the generated summary in the PR body.

## Suggested Artifacts

- Issue intake record with URL, title, labels, and reported behavior.
- Investigation note with hypotheses, inspected files, and suspected cause.
- Reproduction record with a failing test, command, or documented exception.
- Fix note with root cause, changed files, and regression coverage.
- Validation record with commands, results, and remaining risk.
- Summary suitable for a pull request or final issue update.

## Completion Criteria

- The bug run is linked to a GitHub issue.
- The work is isolated on a focused branch when branch creation was requested.
- The reported failure is reproduced, or the lack of reproduction is explained.
- The fix is scoped to the issue.
- A regression test is added when practical.
- Validation commands pass and are recorded.
- The final summary explains the root cause, fix, tests, and upstream status.

</details>

<details>
<summary>Feature Development Intake</summary>

## Purpose

New feature work should continue to use the standard ElectroBoy pipeline:
requirements, design, implementation planning, coding, validation, and
documentation. Feature development starts with intent and scope rather than an
unknown failure, so the existing ordered gates are a good fit.

The workflow should help a developer start feature work from a short title or a
GitHub issue without creating a second process that duplicates the main
pipeline. A feature-intake command can capture metadata and prepare a branch,
then hand control to the normal stage commands.

## Proposed CLI

```bash
electroboy feature start <title-or-issue-url> --branch
electroboy requirements
electroboy design
electroboy implementation-plan
electroboy code
electroboy validate
electroboy document
electroboy code-approve
```

## Command Behavior

### `electroboy feature start <title-or-issue-url> --branch`

Starts a standard pipeline run for feature development. Feature intake should
behave like a from-scratch implementation run with feature metadata attached,
plus optional branch setup when requested.

The command should capture feature metadata such as title, source issue URL,
issue number, labels, requested behavior, initial scope notes, and any known
constraints. If the input is a GitHub issue URL, ElectroBoy can import the
issue title and description as seed context for requirements authoring.

When `--branch` is provided, ElectroBoy should create or switch to a focused
feature branch. A reasonable branch name is derived from the issue number or
title, such as `feature/456-short-feature-slug`. As with bug-fix work, the
command should avoid hiding unrelated local changes and should make the active
branch explicit in the output.

After intake, the command should set up or resume the normal pipeline state and
print the next command, usually `electroboy requirements`. It should not create
a parallel feature-specific stage sequence.

### Standard Pipeline Commands

Feature work should proceed through the existing stage commands instead of a
parallel feature-specific workflow.

`electroboy requirements` should define the problem, user-visible behavior,
scope, non-goals, constraints, and acceptance criteria.

`electroboy design` should record the architecture, data model, interfaces,
state transitions, compatibility concerns, and important tradeoffs.

`electroboy implementation-plan` should split the work into reviewable phases
that trace back to requirements.

`electroboy code` should implement the approved plan in those phases.

`electroboy validate` should run the tests and checks needed to prove the
feature meets its requirements.

`electroboy document` should update user-facing and developer-facing
documentation before final approval.

`electroboy code-approve` should record final human completion approval after
documentation review has passed.

## Why This Differs From Bug Fixing

Bug fixes need an investigation and reproduction workflow because the root
cause is often unknown. A bug workflow should first establish evidence: what
failed, whether it can be reproduced, and what regression coverage proves the
fix.

Feature work is different. The main risk is unclear scope, weak design, or
unvalidated acceptance criteria. The existing ElectroBoy pipeline already
addresses those risks by forcing requirements and design before implementation.

## Suggested Artifacts

- Feature intake record with title, issue URL, labels, and initial scope.
- Requirements artifact describing behavior, non-goals, and acceptance
  criteria.
- Design artifact describing architecture, interfaces, and tradeoffs.
- Implementation plan with traceable phases.
- Validation record with commands and results.
- Documentation updates covering the new behavior.

## Completion Criteria

- The feature run is linked to a title or source issue.
- The work is isolated on a focused branch when branch creation was requested.
- Requirements are approved before design.
- Design is approved before implementation planning.
- Implementation phases trace back to requirements.
- Validation passes and is recorded.
- Documentation is updated before final completion.

</details>
