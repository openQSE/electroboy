# Requirements

## Purpose

ElectroBoy provides a local orchestration layer for disciplined AI-assisted
software development. It preserves iterative human design work while
enforcing ordered implementation, review, validation, documentation, and change
control.

## Functional Requirements

- `REQ-1`: The pipeline starts with requirements and prevents later stages from
  running before predecessor gates pass.
- `REQ-2`: Requirements, design, design acceptance, and implementation planning
  record explicit human or Design Author approvals before gates pass.
- `REQ-3`: Approved artifacts are snapshotted and linked from run state.
- `REQ-4`: Review issues are stored as append-only lifecycle records.
- `REQ-5`: Activity events record gate checks, snapshots, approvals, agent
  invocations, phase actions, validation, documentation review, and change
  control.
- `REQ-6`: Agent runtimes are configurable by role and normalize their results
  into a shared response shape.
- `REQ-7`: Review agents use read-only sandbox policy when Codex is selected.
- `REQ-8`: Implementation runs one active phase at a time and commits each
  completed phase with a verified git SHA.
- `REQ-9`: Implementation plans trace every phase to requirement ids.
- `REQ-10`: Validation runs only after all planned phases are committed.
- `REQ-11`: Validation failures create blocking review issues and must be
  resolved before the validation gate passes.
- `REQ-12`: Documentation review verifies required docs and checks that public
  CLI behavior is documented.
- `REQ-13`: Change control classifies the earliest affected baseline, records
  human approval, invalidates downstream gates and snapshots, and resumes from
  the reopened stage.
- `REQ-14`: Status, resume, summary, and trace reports explain the current run
  state and preserve enough history for later review.

## Non-Goals

- The baseline does not implement a cloud scheduler or hosted dashboard.
- The baseline does not require provider API integration.
- The baseline does not replace human requirements and design judgment.

## Acceptance Criteria

- `python -m unittest discover -s tests` passes.
- `PYTHONPATH=src python -m electroboy --help` loads from a checkout.
- A run cannot skip requirements, design, implementation planning, validation,
  or documentation review.
- A later finding can reopen an earlier baseline only through change control.
