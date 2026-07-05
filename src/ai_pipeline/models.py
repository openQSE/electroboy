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
    event_id: str | None = None
    stage: str | None = None
    phase: int | None = None
    gate: str | None = None
    status: str | None = None
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    linked_issue_ids: list[str] = field(default_factory=list)
    artifact_changes: list[str] = field(default_factory=list)
    artifact_snapshot_refs: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    message_ref: str | None = None
    commit: str | None = None
    schema_version: int = SCHEMA_VERSION
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.event_id,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "stage": self.stage,
            "phase": self.phase,
            "gate": self.gate,
            "status": self.status,
            "action": self.action,
            "summary": self.summary,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "linked_issue_ids": list(self.linked_issue_ids),
            "artifact_changes": list(self.artifact_changes),
            "artifact_snapshot_refs": list(self.artifact_snapshot_refs),
            "commands": list(self.commands),
            "message_ref": self.message_ref,
            "commit": self.commit,
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


@dataclass
class ReviewIssue:
    """Structured issue emitted by a review agent."""

    issue_id: str
    source: str
    severity: str
    status: str
    summary: str
    stage: str | None = None
    phase: int | None = None
    owner: str | None = None
    artifact: str | None = None
    location: str | None = None
    rationale: str | None = None
    requested_change: str | None = None
    response: str | None = None
    verification: str | None = None
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now)
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "issue_id": self.issue_id,
            "source": self.source,
            "severity": self.severity,
            "status": self.status,
            "summary": self.summary,
            "stage": self.stage,
            "phase": self.phase,
            "owner": self.owner,
            "artifact": self.artifact,
            "location": self.location,
            "rationale": self.rationale,
            "requested_change": self.requested_change,
            "response": self.response,
            "verification": self.verification,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewIssue":
        return cls(
            issue_id=str(data["issue_id"]),
            source=str(data.get("source", "agent")),
            severity=str(data.get("severity", "major")),
            status=str(data.get("status", "open")),
            summary=str(data.get("summary", "")),
            stage=data.get("stage"),
            phase=data.get("phase"),
            owner=data.get("owner"),
            artifact=data.get("artifact"),
            location=data.get("location"),
            rationale=data.get("rationale"),
            requested_change=data.get("requested_change"),
            response=data.get("response"),
            verification=data.get("verification"),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            created_at=data.get("created_at", utc_now()),
            updated_at=data.get("updated_at"),
        )


@dataclass
class ApprovalRecord:
    """Approval or confirmation required by a stage gate."""

    approval_id: str
    stage: str
    actor: str
    approval_type: str
    summary: str
    artifact_path: str | None = None
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "approval_id": self.approval_id,
            "stage": self.stage,
            "actor": self.actor,
            "approval_type": self.approval_type,
            "summary": self.summary,
            "artifact_path": self.artifact_path,
            "created_at": self.created_at,
        }


@dataclass
class StageState:
    """Typed view of stage progress."""

    stage: str
    status: str
    gate: str | None = None
    artifact_path: str | None = None
    snapshot_ref: str | None = None
    schema_version: int = SCHEMA_VERSION
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "stage": self.stage,
            "status": self.status,
            "gate": self.gate,
            "artifact_path": self.artifact_path,
            "snapshot_ref": self.snapshot_ref,
            "updated_at": self.updated_at,
        }


@dataclass
class ChangeRequest:
    """Append-only change-control request event."""

    request_id: str
    run_id: str
    baseline: str
    reason: str
    status: str
    event: str
    human_approved: bool = False
    reopened_stage: str | None = None
    invalidated_gates: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now)
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.request_id,
            "run_id": self.run_id,
            "baseline": self.baseline,
            "reason": self.reason,
            "status": self.status,
            "event": self.event,
            "human_approved": self.human_approved,
            "reopened_stage": self.reopened_stage,
            "invalidated_gates": list(self.invalidated_gates),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class BaselineInvalidation:
    """Record of downstream gates and snapshots invalidated by change control."""

    invalidation_id: str
    change_request_id: str
    baseline: str
    invalidated_gates: list[str]
    invalidated_snapshot_refs: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "invalidation_id": self.invalidation_id,
            "change_request_id": self.change_request_id,
            "baseline": self.baseline,
            "invalidated_gates": list(self.invalidated_gates),
            "invalidated_snapshot_refs": list(self.invalidated_snapshot_refs),
            "created_at": self.created_at,
        }


@dataclass
class DecisionRecord:
    """Human or orchestrator decision that affects future stages."""

    decision_id: str
    summary: str
    rationale: str
    stage: str
    phase: int | None = None
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "summary": self.summary,
            "rationale": self.rationale,
            "stage": self.stage,
            "phase": self.phase,
            "created_at": self.created_at,
        }


@dataclass
class PhaseStatus:
    """Status record for implementation phases."""

    active_phase: int | None = None
    phases: dict[str, dict[str, Any]] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PhaseStatus":
        return cls(
            active_phase=data.get("active_phase"),
            phases=dict(data.get("phases", {})),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            updated_at=data.get("updated_at", utc_now()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "active_phase": self.active_phase,
            "phases": self.phases,
            "updated_at": self.updated_at,
        }
