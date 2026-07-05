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
