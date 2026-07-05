"""Core data models for pipeline state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = 1

STAGE_REQUIREMENTS = "requirements"
STAGE_DESIGN = "design"
STAGE_DESIGN_REVIEW = "design-review"
STAGE_DESIGN_ACCEPTANCE = "design-acceptance"
STAGE_PLAN = "plan"
STAGE_IMPLEMENTATION = "implementation"
STAGE_VALIDATION = "validation"
STAGE_DOCS_REVIEW = "docs-review"
STAGE_COMPLETE = "complete"

STAGES = [
    STAGE_REQUIREMENTS,
    STAGE_DESIGN,
    STAGE_DESIGN_REVIEW,
    STAGE_DESIGN_ACCEPTANCE,
    STAGE_PLAN,
    STAGE_IMPLEMENTATION,
    STAGE_VALIDATION,
    STAGE_DOCS_REVIEW,
    STAGE_COMPLETE,
]

GATE_REQUIREMENTS = "requirements"
GATE_DESIGN = "design"
GATE_HUMAN_DESIGN_ACCEPTANCE = "human-design-acceptance"
GATE_IMPLEMENTATION = "implementation"
GATE_VALIDATION_TESTING = "validation-testing"
GATE_DOCUMENTATION = "documentation"

GATES = [
    GATE_REQUIREMENTS,
    GATE_DESIGN,
    GATE_HUMAN_DESIGN_ACCEPTANCE,
    GATE_IMPLEMENTATION,
    GATE_VALIDATION_TESTING,
    GATE_DOCUMENTATION,
]

NEXT_STAGE = {
    STAGE_REQUIREMENTS: STAGE_DESIGN,
    STAGE_DESIGN: STAGE_DESIGN_REVIEW,
    STAGE_DESIGN_REVIEW: STAGE_DESIGN_ACCEPTANCE,
    STAGE_DESIGN_ACCEPTANCE: STAGE_PLAN,
    STAGE_PLAN: STAGE_IMPLEMENTATION,
    STAGE_IMPLEMENTATION: STAGE_VALIDATION,
    STAGE_VALIDATION: STAGE_DOCS_REVIEW,
    STAGE_DOCS_REVIEW: STAGE_COMPLETE,
}


def utc_now() -> str:
    """Return a stable UTC timestamp for state files."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class RunManifest:
    """Durable state for the active pipeline run."""

    run_id: str
    active_stage: str = STAGE_REQUIREMENTS
    completed_gates: list[str] = field(default_factory=list)
    invalidated_gates: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunManifest":
        return cls(
            run_id=data["run_id"],
            active_stage=data.get("active_stage", STAGE_REQUIREMENTS),
            completed_gates=list(data.get("completed_gates", [])),
            invalidated_gates=list(data.get("invalidated_gates", [])),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            created_at=data.get("created_at", utc_now()),
            updated_at=data.get("updated_at", utc_now()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "active_stage": self.active_stage,
            "completed_gates": list(self.completed_gates),
            "invalidated_gates": list(self.invalidated_gates),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def has_gate(self, gate: str) -> bool:
        return gate in self.completed_gates and gate not in self.invalidated_gates

    def complete_gate(self, gate: str) -> None:
        if gate not in self.completed_gates:
            self.completed_gates.append(gate)
        if gate in self.invalidated_gates:
            self.invalidated_gates.remove(gate)
        self.updated_at = utc_now()

    def set_active_stage(self, stage: str) -> None:
        if stage not in STAGES:
            raise ValueError(f"unknown pipeline stage: {stage}")
        self.active_stage = stage
        self.updated_at = utc_now()


@dataclass
class GateResult:
    """Result of a deterministic gate check."""

    name: str
    status: str
    messages: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "pass"


@dataclass
class ActivityEvent:
    """Append-only activity-log event."""

    actor: str
    action: str
    summary: str
    stage: str | None = None
    gate: str | None = None
    schema_version: int = SCHEMA_VERSION
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "stage": self.stage,
            "gate": self.gate,
            "action": self.action,
            "summary": self.summary,
        }


@dataclass
class ArtifactSnapshot:
    """Snapshot metadata for an approved pipeline artifact."""

    artifact_path: str
    snapshot_path: str
    checksum: str
    event_id: str
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_path": self.artifact_path,
            "snapshot_path": self.snapshot_path,
            "checksum": self.checksum,
            "event_id": self.event_id,
            "created_at": self.created_at,
        }
