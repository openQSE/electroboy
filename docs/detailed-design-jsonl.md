# Structured Artifact Design

ElectroBoy uses workflow artifacts as durable context between humans,
interactive agents, non-interactive agents, and deterministic orchestration
code. The structured artifact model makes every major artifact available in a
machine-readable JSONL form while keeping Markdown available for human review.

The JSONL artifact is the source of truth. The Markdown artifact is the
readable companion. During interactive authoring, agents update the JSONL file
and call the deterministic renderer so the operator can keep reading Markdown
in the GUI. During non-interactive stages, ElectroBoy reads the JSONL file
where stable records are needed, starting with implementation units and
expanding to other stage decisions as those workflows are structured.

Feature workflows use the same naming rule for both files. A feature named
`munge` uses `docs/requirements-munge.jsonl` and
`docs/requirements-munge.md`, `docs/detailed-design-munge.jsonl` and
`docs/detailed-design-munge.md`, and so on.

## Goals

- Keep human-readable Markdown in `docs/`.
- Give ElectroBoy deterministic records for stage logic.
- Preserve stable identifiers across edits.
- Avoid parsing arbitrary Markdown for orchestration decisions.
- Allow old Markdown-only projects to continue through bootstrap conversion.
- Let agents update structured and rendered artifacts without waiting for a
  separate render pass after the interactive session ends.

## Artifact Pairing

Each major document has a JSONL source and a Markdown companion.

| Artifact | JSONL source | Markdown companion |
| --- | --- | --- |
| Requirements | `docs/requirements.jsonl` | `docs/requirements.md` |
| Detailed design | `docs/detailed-design.jsonl` | `docs/detailed-design.md` |
| Implementation plan | `docs/implementation-plan.jsonl` | `docs/implementation-plan.md` |
| Test plan | `docs/test-plan.jsonl` | `docs/test-plan.md` |
| Implementation log | `docs/implementation-log.jsonl` | `docs/implementation-log.md` |
| Implementation report | `docs/implementation-report.jsonl` | `docs/implementation-report.md` |
| Validation report | `docs/validation-report.jsonl` | `docs/validation-report.md` |

Review issues remain run records under `.electroboy/shared/runs/<run-id>/`.
Readable review summaries remain under `docs/reviews/` or the feature-tagged
review report path.

## JSONL Record Envelope

Every line in an artifact JSONL file is one JSON object. Records share a
small common envelope so tools can sort, validate, and render mixed content.

```json
{
  "schema_version": 1,
  "artifact_type": "requirements",
  "record_type": "requirement",
  "id": "REQ-001",
  "order": 10,
  "title": "Reserve QPU capacity",
  "status": "draft",
  "links": [],
  "tags": [],
  "updated_at": "2026-08-10T20:34:46+00:00"
}
```

Common fields:

- `schema_version` identifies the record schema.
- `artifact_type` names the owning artifact.
- `record_type` selects the artifact-specific payload shape.
- `id` is stable and human-readable.
- `order` controls rendered order without relying on file position.
- `title` is the rendered heading or item label.
- `status` is `draft`, `approved`, `changed`, `deprecated`, or `deferred`.
- `links` records traceability to other artifact ids.
- `tags` records loose grouping labels.
- `updated_at` records the last material edit time.

JSONL files are append-friendly, but artifact files are canonical snapshots.
Agents may rewrite a JSONL artifact to keep ordering and deleted records clear.
Run logs, review issues, decisions, and approvals remain append-only.

## Requirements Schema

Requirements files describe expected behavior and constraints. They provide
the primary traceability anchor for design, planning, test planning, coding,
validation, and documentation review.

Document metadata:

```json
{
  "schema_version": 1,
  "artifact_type": "requirements",
  "record_type": "document",
  "id": "REQ-DOC",
  "order": 0,
  "title": "Requirements",
  "summary": "Admission and scheduling requirements for QFw.",
  "scope": ["in scope item"],
  "out_of_scope": ["deferred item"],
  "personas": ["operator", "developer"],
  "status": "draft"
}
```

Requirement record:

```json
{
  "schema_version": 1,
  "artifact_type": "requirements",
  "record_type": "requirement",
  "id": "REQ-001",
  "order": 10,
  "title": "Submit admission request",
  "statement": "The system accepts an admission request for a target backend.",
  "body": "Detailed Markdown for the requirement.",
  "rationale": "Operators need a stable entry point for scheduling requests.",
  "priority": "must",
  "acceptance_criteria": [
    "A request can be submitted through the documented API.",
    "Invalid backend names produce a clear error."
  ],
  "verification": ["TEST-001"],
  "dependencies": [],
  "status": "draft"
}
```

Supported `priority` values are `must`, `should`, `could`, and `deferred`.
The `verification` list links requirements to test-plan records. The
`dependencies` list names prerequisite requirement ids. The `statement` field
is the concise requirement summary. The `body` field carries the full
requirement text and supports Markdown content, including lists, tables, code
blocks, links, and Mermaid diagrams.

Section records may be used for narrative grouping:

```json
{
  "schema_version": 1,
  "artifact_type": "requirements",
  "record_type": "section",
  "id": "REQSEC-001",
  "order": 5,
  "title": "User Workflows",
  "body": "The operator workflow starts with admission and ends with status.",
  "status": "draft"
}
```

## Design Schema

Design files explain how the system satisfies the requirements. They link
design sections and decisions back to requirement ids.

Design section:

```json
{
  "schema_version": 1,
  "artifact_type": "design",
  "record_type": "section",
  "id": "DES-001",
  "order": 10,
  "title": "Admission service boundary",
  "body": "The admission service validates requests before scheduling.",
  "requirements": ["REQ-001", "REQ-002"],
  "interfaces": ["IFACE-001"],
  "status": "draft"
}
```

Design decision:

```json
{
  "schema_version": 1,
  "artifact_type": "design",
  "record_type": "decision",
  "id": "DEC-001",
  "order": 20,
  "title": "Keep scheduling policy outside admission validation",
  "body": "Detailed Markdown explaining the decision and alternatives.",
  "context": "Admission validates request shape and backend availability.",
  "decision": "Scheduling policy remains in the scheduler service.",
  "consequences": [
    "Admission stays simple.",
    "Scheduler tests cover policy behavior."
  ],
  "requirements": ["REQ-001"],
  "status": "draft"
}
```

Interface records capture APIs, messages, file formats, and integration
contracts:

```json
{
  "schema_version": 1,
  "artifact_type": "design",
  "record_type": "interface",
  "id": "IFACE-001",
  "order": 30,
  "title": "Admission request",
  "body": "Detailed Markdown for request examples and edge cases.",
  "kind": "api",
  "producer": "client",
  "consumer": "admission-service",
  "schema": {
    "backend": "string",
    "requested_time": "datetime"
  },
  "requirements": ["REQ-001"],
  "status": "draft"
}
```

Design `body` fields support Markdown content, including tables, code blocks,
links, and Mermaid diagrams. Short fields such as `context`, `decision`, and
`consequences` remain available for deterministic summaries and reports.

## Implementation Plan Schema

The implementation plan schema already exists in the codebase. The planned
workflow keeps it as the automation source for `electroboy code`.

Implementation unit:

```json
{
  "schema_version": 1,
  "unit_id": "PH1-C1",
  "phase": 1,
  "sequence": 1,
  "title": "Create admission request model",
  "body": "Detailed Markdown describing the intended implementation unit.",
  "primary_repos": ["QFw"],
  "commit_tasks": ["Add request dataclass", "Add parser tests"],
  "requirements": ["REQ-001"],
  "design_sections": ["DES-001", "IFACE-001"],
  "scope": "Introduce request model and validation errors.",
  "exit_criteria": ["Unit tests pass for valid and invalid requests."],
  "paths": ["qfw/admission/request.py", "tests/test_admission_request.py"],
  "dependencies": [],
  "source_plan": "docs/implementation-plan.md",
  "source_type": "jsonl"
}
```

Each implementation unit is a commit pass. The `commit_tasks` list defines the
set of changes expected to land in the same git commit. The coding agent
implements one unit, self-reviews it, sends it through code review, fixes
blocker and major issues, and commits that unit only after no blocker or major
review issues remain. Minor issues are recorded as follow-up items unless the
operator chooses a stricter mode.

The code loop for one unit is:

1. Load the next implementation unit from JSONL.
2. Implement only that unit's `commit_tasks`.
3. Run one coding-agent self-review pass.
4. Run the code-review agent against the unit changes.
5. Fix blocker and major issues.
6. Repeat review and fix until the unit passes or the retry limit is reached.
7. Commit the unit and record the commit SHA against the unit.

The next unit starts only after the current unit has a reviewed commit.

## Test Plan Schema

The test plan defines human-facing system tests and automation targets. It is
not limited to unit tests generated by the coding agent.

Test suite:

```json
{
  "schema_version": 1,
  "artifact_type": "test-plan",
  "record_type": "suite",
  "id": "TS-001",
  "order": 10,
  "title": "Admission scheduling smoke tests",
  "body": "Detailed Markdown describing suite setup and constraints.",
  "scope": "End-to-end admission and scheduling behavior.",
  "requirements": ["REQ-001", "REQ-002"],
  "status": "draft"
}
```

Test case:

```json
{
  "schema_version": 1,
  "artifact_type": "test-plan",
  "record_type": "test",
  "id": "TEST-001",
  "order": 20,
  "title": "Submit valid admission request",
  "body": "Detailed Markdown for manual notes, tables, or diagrams.",
  "level": "system",
  "suite": "TS-001",
  "requirements": ["REQ-001"],
  "design_sections": ["DES-001", "IFACE-001"],
  "implementation_units": ["PH1-C1"],
  "preconditions": ["QFw service is running."],
  "steps": ["Submit a valid request.", "Poll request status."],
  "expected_results": ["The request is accepted.", "Status becomes queued."],
  "automation": {
    "command": "pytest tests/system/test_admission.py::test_valid_request",
    "manual": false
  },
  "status": "draft"
}
```

`level` values are `unit`, `integration`, `system`, `smoke`, and `manual`.
The validation stage reads these records when deciding which tests to run and
how to summarize results. Test-plan `body` fields support Markdown content,
including tables, code blocks, links, and Mermaid diagrams.

## Report Schemas

Report JSONL files summarize what happened after execution stages. They are
structured so the GUI can filter, group, and link results back to artifacts.

Implementation log event:

```json
{
  "schema_version": 1,
  "artifact_type": "implementation-log",
  "record_type": "unit-event",
  "id": "IMPL-EVT-001",
  "order": 10,
  "unit_id": "PH1-C1",
  "event": "implemented",
  "summary": "Added admission request model and parser tests.",
  "files": ["qfw/admission/request.py", "tests/test_admission_request.py"],
  "commit": "abc1234",
  "status": "complete"
}
```

Implementation report record:

```json
{
  "schema_version": 1,
  "artifact_type": "implementation-report",
  "record_type": "summary",
  "id": "IMPL-SUMMARY",
  "order": 0,
  "implemented_units": ["PH1-C1"],
  "deferred_issues": ["CR-001"],
  "design_changes": ["DEC-002"],
  "current_state": "Admission request model is implemented and tested.",
  "status": "complete"
}
```

Validation result:

```json
{
  "schema_version": 1,
  "artifact_type": "validation-report",
  "record_type": "test-result",
  "id": "VAL-001",
  "order": 10,
  "test_id": "TEST-001",
  "command": "pytest tests/system/test_admission.py::test_valid_request",
  "result": "passed",
  "duration_seconds": 4.2,
  "stdout_summary": "1 passed",
  "stderr_summary": "",
  "status": "complete"
}
```

## Review Issue Schema

Review issue JSONL remains separate from the user-facing artifacts. Each issue
is a run record because reviews are event history, not artifact source text.

```json
{
  "id": "DESIGN-001",
  "stage": "design-review",
  "phase": null,
  "severity": "major",
  "status": "open",
  "owner": "design-author",
  "artifact": "docs/detailed-design.md",
  "location": "Admission service boundary",
  "summary": "The design omits scheduler error handling.",
  "rationale": "The requirements include invalid backend handling.",
  "requested_change": "Define the scheduler error path.",
  "response": null,
  "verification": null
}
```

Severity values are `blocker`, `major`, and `minor`. Blocker issues prevent
progress. Major issues prevent progress unless waived. Minor issues are
recorded and may become follow-up work.

## Rendering Rules

The Markdown companion is rendered from JSONL records in `order` sequence.
Renderers keep stable headings so humans can link to sections and compare
diffs.

Agents update the JSONL file during interactive sessions, then call the
deterministic renderer before yielding control. The renderer rewrites the
Markdown companion from the JSONL source. This keeps Markdown available in the
GUI without making Markdown a second editable source of truth.

The command shape is:

```text
electroboy render-artifact requirements
electroboy render-artifact design
electroboy render-artifact implementation-plan
electroboy render-artifact test-plan
```

When a user edits the Markdown companion manually, the inverse command brings
the JSONL source back into sync:

```text
electroboy import-artifact requirements
electroboy import-artifact design
electroboy import-artifact implementation-plan
electroboy import-artifact test-plan
```

The importer preserves rich Markdown bodies and recovers generated scalar and
list fields where possible. Arbitrary Markdown headings without stable ids are
converted into deterministic section or implementation-unit records. This
manual import is an explicit recovery operation because it replaces the JSONL
source from the Markdown companion.

The renderer performs a full-file render. Full renders are simple, reliable,
and fast for expected artifact sizes. The design leaves room for a later
incremental renderer by keeping stable record ids, deterministic ordering, and
record-local content hashes, but the initial implementation prioritizes
correctness over partial updates.

ElectroBoy validates that JSONL parses before rendering. Approval ensures the
structured source exists when a stage uses one, creates it from Markdown for
older projects when needed, and includes both the JSONL source and Markdown
companion in approval commits and snapshots.

Approval records snapshot both files. If only Markdown exists, compatibility
conversion runs before the stage needs structured data.

## Compatibility Conversion

Markdown-only projects remain valid inputs. When a structured artifact is
missing, ElectroBoy creates one from the Markdown companion where practical.

Conversion rules:

- Requirements headings and requirement-like bullets become section and
  requirement records.
- Design headings become design section records.
- Implementation-plan commit rows become implementation units.
- Test-plan headings and numbered test cases become suite and test records.

Generated records use stable ids when the Markdown already contains ids. If no
id exists, ElectroBoy creates deterministic ids from document order. The
Markdown remains unchanged during compatibility conversion unless the operator
or agent explicitly asks for a synchronized rewrite.

## Agent Prompt Contract

Authoring agents receive the JSONL source path and Markdown companion path.
The prompt names the JSONL file as the structured source and the Markdown file
as the rendered companion.

For requirements authoring, the prompt should say:

```text
Work with the operator on the requirements artifact.

Structured source: docs/requirements-<feature>.jsonl.
Readable companion: docs/requirements-<feature>.md.
Read only these two files unless the operator explicitly asks otherwise.
Update both files together so the Markdown reflects the JSONL source.
Do not inspect source code unless the operator explicitly asks you to.
If the operator asks you to update another artifact, report that file and why.
```

Design, implementation-plan, and test-plan prompts follow the same pattern.
Later-stage prompts read JSONL records for deterministic context and may read
Markdown companions for human-readable narrative.

## Orchestrator Responsibilities

ElectroBoy owns file resolution, validation, snapshots, and stage decisions.
Agents own content edits during authoring sessions.

The orchestrator performs these checks:

- Resolve feature-tagged artifact pairs for the active run.
- Create missing JSONL files from Markdown companions when possible.
- Validate that JSONL files parse and contain object records.
- Snapshot JSONL and Markdown companions on approval.
- Reopen the earliest affected stage when an approved earlier artifact changes.
- Use JSONL records where implemented, including implementation units.

The orchestrator does not rewrite approved content as a side effect of normal
status or display commands.

## Implementation Status

Requirements, detailed design, implementation plan, and test plan now use
paired JSONL and Markdown artifacts during authoring. Stage prompts name the
JSONL file as the source of truth and the Markdown file as the readable
companion. Agents are instructed to edit JSONL, then run `electroboy
render-artifact <artifact>` so Markdown remains readable during the session.

Older Markdown-only projects are bootstrapped automatically when an authoring
stage or approval stage needs a structured artifact. ElectroBoy imports the
existing Markdown companion into the matching JSONL path. Feature runs use the
feature-tagged JSONL path derived from the feature-tagged Markdown path.

Approvals and forced snapshots include both the JSONL source and Markdown
companion for structured authoring artifacts. Change invalidation also records
snapshot references for both files where they exist.

Design review receives both requirements and design artifact pairs as context,
plus the review summary and update log. The implementation loop already uses
the structured implementation-plan JSONL before running phase or unit work.

Review issues, approvals, activity logs, change requests, decisions, and
snapshots remain JSONL run records under `.electroboy/shared/runs/<run-id>/`.

Implementation log, implementation report, and validation report JSONL sources
are documented here but are not yet the primary implementation path. Strict
cross-artifact link validation is also deferred; the current implementation
validates parseability and object shape, while artifact-specific validation is
incremental.
