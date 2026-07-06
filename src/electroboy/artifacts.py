"""Pipeline artifact templates and snapshots."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from .models import ArtifactSnapshot


ARTIFACT_TEMPLATES = {
    "docs/requirements.md": """# Requirements

## Purpose

Describe the system behavior to build.

## Target Users

- TBD

## Workflows

- TBD

## Required Behavior

- TBD

## Constraints

- TBD

## Non-Goals

- TBD

## Acceptance Criteria

- TBD
""",
    "docs/detailed-design.md": """# Detailed Design

## Purpose

Describe how the system satisfies `docs/requirements.md`.

## Architecture

- TBD

## Data Flow

- TBD

## Operational Model

- TBD

## Open Decisions

- TBD
""",
    "docs/implementation-plan.md": """# Implementation Plan

## Phase 0. Repository Foundation

Scope:

- TBD

Acceptance criteria:

- TBD
""",
    "docs/api.md": """# API Documentation

## Public API

- TBD

## Commands

- TBD

## Configuration

- TBD
""",
}


class ArtifactError(RuntimeError):
    """Raised when artifact handling fails."""


class ArtifactManager:
    """Create artifact templates and approved run snapshots."""

    def __init__(self, root: Path | str = ".") -> None:
        self.root = Path(root).resolve()

    def init_templates(self, overwrite: bool = False) -> list[str]:
        written: list[str] = []
        for relative_path, template in ARTIFACT_TEMPLATES.items():
            path = self.root / relative_path
            if path.exists() and not overwrite:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(template, encoding="utf-8")
            written.append(relative_path)
        return written

    def snapshot(
        self,
        run_id: str,
        relative_path: str,
        event_id: str,
    ) -> ArtifactSnapshot:
        source = self.root / relative_path
        if not source.exists():
            raise ArtifactError(f"artifact does not exist: {relative_path}")

        snapshot_path = self.root / ".electroboy" / "shared" / "runs" / run_id
        snapshot_path = snapshot_path / "artifacts" / relative_path
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, snapshot_path)

        return ArtifactSnapshot(
            artifact_path=relative_path,
            snapshot_path=str(snapshot_path.relative_to(self.root)),
            checksum=self.checksum(source),
            event_id=event_id,
        )

    def snapshot_all(self, run_id: str, event_id: str) -> list[ArtifactSnapshot]:
        snapshots: list[ArtifactSnapshot] = []
        for relative_path in ARTIFACT_TEMPLATES:
            path = self.root / relative_path
            if path.exists():
                snapshots.append(self.snapshot(run_id, relative_path, event_id))
        return snapshots

    def checksum(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
