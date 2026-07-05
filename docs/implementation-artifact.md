# Implementation Artifact

This artifact records what changed in each implementation phase. It gives
review agents a stable phase-by-phase baseline for implementation review.

## Phase 0. Repository Foundation

Commit: `363a278 pipeline: add initial CLI foundation`

Implemented:

- Added Python project metadata and package skeleton.
- Added `ai-pipeline` CLI entry point.
- Added basic run initialization, status, stage, gate, resume, and change
  commands.
- Added early JSON state handling and ordered-flow tests.
- Added README usage guidance and Python ignore rules.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 1. Artifact Templates

Implemented:

- Added artifact templates for requirements, design, implementation plan, and
  API documentation.
- Added `ArtifactManager` helpers for creating missing artifacts without
  overwriting existing files.
- Added artifact snapshot support with SHA-256 checksums.
- Added `ai-pipeline artifacts init` and `ai-pipeline artifacts snapshot`.
- Added artifact snapshot records under the active run.
- Added artifact tests for template safety and snapshot creation.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 2. State Store

Implemented:

- Added structured models for review issues, decisions, and phase status.
- Added JSONL helpers for review issue files and decision records.
- Added phase status persistence in `.agent-pipeline/phase-status.json`.
- Added message and raw runtime stream writers.
- Added recursive redaction for JSON-compatible state records.
- Added tests for review issue, phase status, decision, and raw-event state.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 3. Gate Engine

Implemented:

- Added gate constants for stage order, change control, plan currency, code
  review, phase test review, and commit readiness.
- Added change-control gate checks that block stage transitions while change
  requests remain open.
- Added implementation-plan currency checks for active phase drift.
- Added code review and phase test review gates based on phase status and
  blocking review issues.
- Added commit gate composition across implementation, plan currency, code
  review, and phase test review gates.
- Added gate tests for open change requests, plan drift, blocking review
  issues, and commit readiness.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 4. Runtime Adapter Interface

Implemented:

- Added `PipelineConfig` loading for `agent-pipeline.toml`.
- Added runtime selection by role with a default Codex runtime.
- Expanded `AgentInvocation` and `AgentResult` to carry schema, event,
  command, changed-file, and error data.
- Added runtime factory functions for manual, generic CLI, Codex exec, and
  Codex SDK adapters.
- Implemented manual runtime completion from a configured response file.
- Added tests for config parsing, role selection, and manual runtime results.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 5. CLI Runtime Adapters

Implemented:

- Implemented subprocess-backed generic CLI runtime invocation.
- Added prompt construction with role context paths.
- Added stdout parsing for plain text and JSON agent results.
- Implemented Codex JSONL parsing for final messages and raw events.
- Added `ai-pipeline agent run` for configured role invocation.
- Stored agent prompts, responses, raw runtime events, and activity events.
- Added runtime adapter tests for generic JSON output and Codex JSONL output.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```

## Phase 6. Requirements And Design Loops

Implemented:

- Added artifact snapshots when requirements, design review, design
  acceptance, or implementation planning stages complete.
- Added `ai-pipeline issues add`, `issues list`, and `issues resolve`.
- Blocked design-review completion while open blocker or major design issues
  remain.
- Preserved design review issue records in run JSONL files.
- Added tests for requirements snapshots and design review issue iteration.

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m ai_pipeline --help
```
