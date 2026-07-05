"""Deterministic gate checks for ordered pipeline flow."""

from __future__ import annotations

from pathlib import Path

from .models import (
    GATE_CHANGE_CONTROL,
    GATE_CODE_REVIEW,
    GATE_COMMIT,
    GATE_DESIGN,
    GATE_DOCUMENTATION,
    GATE_HUMAN_DESIGN_ACCEPTANCE,
    GATE_IMPLEMENTATION,
    GATE_PHASE_TEST_REVIEW,
    GATE_PLAN_CURRENCY,
    GATE_REQUIREMENTS,
    GATE_STAGE_ORDER,
    GATE_VALIDATION_TESTING,
    GateResult,
    RunManifest,
    STAGE_DESIGN,
    STAGE_DESIGN_ACCEPTANCE,
    STAGE_DESIGN_REVIEW,
    STAGE_DOCS_REVIEW,
    STAGE_IMPLEMENTATION,
    STAGE_PLAN,
    STAGE_REQUIREMENTS,
    STAGE_VALIDATION,
)
from .planning import has_traceability
from .state_store import StateStore


REQUIRED_FILES = {
    GATE_REQUIREMENTS: "docs/requirements.md",
    GATE_DESIGN: "docs/detailed-design.md",
    GATE_IMPLEMENTATION: "docs/implementation-plan.md",
    GATE_DOCUMENTATION: "docs/api.md",
}

GATE_SNAPSHOT_ARTIFACTS = {
    GATE_REQUIREMENTS: "docs/requirements.md",
    GATE_DESIGN: "docs/detailed-design.md",
    GATE_HUMAN_DESIGN_ACCEPTANCE: "docs/detailed-design.md",
    GATE_IMPLEMENTATION: "docs/implementation-plan.md",
}

GATE_APPROVALS = {
    GATE_REQUIREMENTS: [
        (STAGE_REQUIREMENTS, "human-approval"),
        (STAGE_REQUIREMENTS, "author-confirmation"),
    ],
    GATE_DESIGN: [
        (STAGE_DESIGN, "human-approval"),
    ],
    GATE_HUMAN_DESIGN_ACCEPTANCE: [
        (STAGE_DESIGN_ACCEPTANCE, "human-approval"),
    ],
    GATE_IMPLEMENTATION: [
        (STAGE_PLAN, "human-approval"),
        (STAGE_PLAN, "author-confirmation"),
    ],
}

BLOCKING_ISSUE_STATUSES = {"open", "accepted", "fixed", "escalated"}

PHASE_REVIEW_EVENT_KEYS = {
    "code_review": "code_review_event",
    "test_review": "test_review_event",
}

PREDECESSOR_GATES = {
    STAGE_REQUIREMENTS: [],
    STAGE_DESIGN: [GATE_REQUIREMENTS],
    STAGE_DESIGN_REVIEW: [GATE_REQUIREMENTS],
    STAGE_DESIGN_ACCEPTANCE: [GATE_REQUIREMENTS, GATE_DESIGN],
    STAGE_PLAN: [
        GATE_REQUIREMENTS,
        GATE_DESIGN,
        GATE_HUMAN_DESIGN_ACCEPTANCE,
    ],
    STAGE_IMPLEMENTATION: [GATE_IMPLEMENTATION],
    STAGE_VALIDATION: [GATE_IMPLEMENTATION],
    STAGE_DOCS_REVIEW: [GATE_VALIDATION_TESTING],
}


class GateEngine:
    """Evaluate gates against the current repository and manifest."""

    def __init__(self, root: Path | str = ".") -> None:
        self.root = Path(root).resolve()
        self.store = StateStore(self.root)

    def evaluate(self, name: str, manifest: RunManifest) -> GateResult:
        if name == GATE_STAGE_ORDER:
            return self.stage_order(manifest.active_stage, manifest)
        if name == GATE_CHANGE_CONTROL:
            return self.change_control()
        if name == GATE_PLAN_CURRENCY:
            return self.implementation_plan_currency()
        if name == GATE_REQUIREMENTS:
            return self._completed_file_gate(
                manifest,
                name,
                "docs/requirements.md",
                "requirements approval has not been recorded",
            )
        if name == GATE_DESIGN:
            return self._completed_file_gate(
                manifest,
                name,
                "docs/detailed-design.md",
                "design review has not been recorded",
            )
        if name == GATE_HUMAN_DESIGN_ACCEPTANCE:
            return self._completed_gate_with_requirements(
                manifest,
                name,
                "human design acceptance has not been recorded",
            )
        if name == GATE_IMPLEMENTATION:
            result = self._completed_file_gate(
                manifest,
                name,
                "docs/implementation-plan.md",
                "implementation-plan approval has not been recorded",
            )
            if result.passed and not has_traceability(self.root):
                return GateResult(
                    name=name,
                    status="blocked",
                    messages=["implementation plan lacks requirements traceability"],
                )
            return result
        if name == GATE_CODE_REVIEW:
            return self.phase_review_gate(
                gate=GATE_CODE_REVIEW,
                issue_file_template="phase-{phase}-code-review.jsonl",
                status_key="code_review",
            )
        if name == GATE_PHASE_TEST_REVIEW:
            return self.phase_review_gate(
                gate=GATE_PHASE_TEST_REVIEW,
                issue_file_template="phase-{phase}-test-review.jsonl",
                status_key="test_review",
            )
        if name == GATE_COMMIT:
            return self.commit_gate(manifest)
        if name == GATE_VALIDATION_TESTING:
            return self.validation_gate(
                manifest,
            )
        if name == GATE_DOCUMENTATION:
            return self.documentation_gate(
                manifest,
            )
        return GateResult(name=name, status="fail", messages=[f"unknown gate: {name}"])

    def stage_order(self, requested_stage: str, manifest: RunManifest) -> GateResult:
        messages: list[str] = []
        if manifest.active_stage != requested_stage:
            messages.append(
                f"active stage is {manifest.active_stage}, not {requested_stage}"
            )

        for gate in PREDECESSOR_GATES.get(requested_stage, []):
            if not manifest.has_gate(gate):
                messages.append(f"predecessor gate is not complete: {gate}")
            elif not self._has_required_snapshot(gate):
                messages.append(f"predecessor snapshot is missing: {gate}")

        open_changes = self._open_change_requests()
        if open_changes:
            messages.append("open change-control request blocks stage transition")

        if messages:
            return GateResult(
                name=GATE_STAGE_ORDER,
                status="blocked",
                messages=messages,
            )
        return GateResult(name=GATE_STAGE_ORDER, status="pass")

    def change_control(self) -> GateResult:
        open_changes = self._open_change_requests()
        if open_changes:
            ids = ", ".join(str(change.get("id")) for change in open_changes)
            return GateResult(
                name=GATE_CHANGE_CONTROL,
                status="blocked",
                messages=[f"open change-control requests: {ids}"],
            )
        return GateResult(name=GATE_CHANGE_CONTROL, status="pass")

    def implementation_plan_currency(self) -> GateResult:
        status = self.store.load_phase_status()
        if status.active_phase is None:
            return GateResult(name=GATE_PLAN_CURRENCY, status="pass")
        phase = status.phases.get(str(status.active_phase), {})
        if phase.get("plan_current", True):
            return GateResult(name=GATE_PLAN_CURRENCY, status="pass")
        return GateResult(
            name=GATE_PLAN_CURRENCY,
            status="blocked",
            messages=["active phase has plan drift"],
        )

    def phase_review_gate(
        self,
        gate: str,
        issue_file_template: str,
        status_key: str,
    ) -> GateResult:
        status = self.store.load_phase_status()
        if status.active_phase is None:
            return GateResult(
                name=gate,
                status="blocked",
                messages=["no active phase"],
            )
        phase_key = str(status.active_phase)
        phase = status.phases.get(phase_key, {})
        if phase.get(status_key) != "passed":
            return GateResult(
                name=gate,
                status="blocked",
                messages=[f"{status_key.replace('_', ' ')} has not passed"],
            )
        event_key = PHASE_REVIEW_EVENT_KEYS.get(status_key)
        if event_key and not phase.get(event_key):
            return GateResult(
                name=gate,
                status="blocked",
                messages=[
                    f"{status_key.replace('_', ' ')} agent evidence is missing"
                ],
            )
        issue_file = issue_file_template.format(phase=phase_key)
        open_issues = self._blocking_issues(issue_file)
        if open_issues:
            return GateResult(
                name=gate,
                status="blocked",
                messages=[f"blocking review issues remain in {issue_file}"],
            )
        return GateResult(name=gate, status="pass")

    def commit_gate(self, manifest: RunManifest) -> GateResult:
        messages: list[str] = []
        if not manifest.has_gate(GATE_IMPLEMENTATION):
            messages.append("implementation gate is not complete")
        for result in [
            self.implementation_plan_currency(),
            self.phase_review_gate(
                GATE_CODE_REVIEW,
                "phase-{phase}-code-review.jsonl",
                "code_review",
            ),
            self.phase_review_gate(
                GATE_PHASE_TEST_REVIEW,
                "phase-{phase}-test-review.jsonl",
                "test_review",
            ),
        ]:
            messages.extend(result.messages)
        if messages:
            return GateResult(name=GATE_COMMIT, status="blocked", messages=messages)
        return GateResult(name=GATE_COMMIT, status="pass")

    def validation_gate(self, manifest: RunManifest) -> GateResult:
        messages: list[str] = []
        if not manifest.has_gate(GATE_VALIDATION_TESTING):
            messages.append("validation testing has not been recorded")
        if self._blocking_issues("validation-review.jsonl"):
            messages.append("blocking validation review issues remain")
        report = self.store.run_dir(manifest.run_id) / "artifacts" / "validation-report.md"
        if manifest.has_gate(GATE_VALIDATION_TESTING) and not report.exists():
            messages.append("validation report is missing")
        if messages:
            return GateResult(
                name=GATE_VALIDATION_TESTING,
                status="blocked",
                messages=messages,
            )
        return GateResult(name=GATE_VALIDATION_TESTING, status="pass")

    def documentation_gate(self, manifest: RunManifest) -> GateResult:
        messages: list[str] = []
        if not manifest.has_gate(GATE_DOCUMENTATION):
            messages.append("documentation review has not been recorded")
        for relative_path in [
            "docs/requirements.md",
            "docs/detailed-design.md",
            "README.md",
            "docs/api.md",
        ]:
            file_result = self.require_file(relative_path)
            messages.extend(file_result.messages)
        if self._blocking_issues("documentation-review.jsonl"):
            messages.append("blocking documentation review issues remain")
        if messages:
            return GateResult(
                name=GATE_DOCUMENTATION,
                status="blocked",
                messages=messages,
            )
        return GateResult(name=GATE_DOCUMENTATION, status="pass")

    def require_file(self, relative_path: str) -> GateResult:
        path = self.root / relative_path
        if path.exists():
            return GateResult(name=relative_path, status="pass")
        return GateResult(
            name=relative_path,
            status="blocked",
            messages=[f"required file is missing: {relative_path}"],
        )

    def _completed_gate(
        self,
        manifest: RunManifest,
        gate: str,
        missing_message: str,
    ) -> GateResult:
        if manifest.has_gate(gate):
            return GateResult(name=gate, status="pass")
        return GateResult(name=gate, status="blocked", messages=[missing_message])

    def _completed_gate_with_requirements(
        self,
        manifest: RunManifest,
        gate: str,
        missing_message: str,
    ) -> GateResult:
        messages: list[str] = []
        if not manifest.has_gate(gate):
            messages.append(missing_message)
        for stage, approval_type in GATE_APPROVALS.get(gate, []):
            if not self._has_approval(stage, approval_type):
                messages.append(
                    f"approval is missing: {stage} {approval_type}"
                )
        if manifest.has_gate(gate) and not self._has_required_snapshot(gate):
            messages.append(f"required snapshot is missing: {gate}")
        if messages:
            return GateResult(name=gate, status="blocked", messages=messages)
        return GateResult(name=gate, status="pass")

    def _completed_file_gate(
        self,
        manifest: RunManifest,
        gate: str,
        relative_path: str,
        missing_message: str,
    ) -> GateResult:
        messages: list[str] = []
        file_result = self.require_file(relative_path)
        messages.extend(file_result.messages)
        if not manifest.has_gate(gate):
            messages.append(missing_message)
        for stage, approval_type in GATE_APPROVALS.get(gate, []):
            if not self._has_approval(stage, approval_type):
                messages.append(
                    f"approval is missing: {stage} {approval_type}"
                )
        if manifest.has_gate(gate) and not self._has_required_snapshot(gate):
            messages.append(f"required snapshot is missing: {gate}")
        if gate == GATE_DESIGN and self._blocking_issues("design-review.jsonl"):
            messages.append("blocking design review issues remain")
        if messages:
            return GateResult(name=gate, status="blocked", messages=messages)
        return GateResult(name=gate, status="pass")

    def _has_required_snapshot(self, gate: str) -> bool:
        artifact_path = GATE_SNAPSHOT_ARTIFACTS.get(gate)
        if artifact_path is None:
            return True
        invalidated = {
            str(snapshot_ref)
            for invalidation in self.store.read_baseline_invalidations()
            for snapshot_ref in invalidation.get("invalidated_snapshot_refs", [])
        }
        for snapshot in self.store.read_artifact_snapshots():
            if snapshot.get("artifact_path") != artifact_path:
                continue
            if str(snapshot.get("snapshot_path")) in invalidated:
                continue
            return True
        return False

    def _has_approval(self, stage: str, approval_type: str) -> bool:
        return any(
            approval.get("stage") == stage
            and approval.get("approval_type") == approval_type
            for approval in self.store.read_approvals()
        )

    def _open_change_requests(self) -> list[dict[str, object]]:
        return [
            request
            for request in self.store.read_change_requests()
            if request.get("status") == "open"
        ]

    def _blocking_issues(self, issue_file: str) -> list[dict[str, object]]:
        return [
            issue
            for issue in self.store.read_review_issues(issue_file)
            if issue.get("status") in BLOCKING_ISSUE_STATUSES
            and issue.get("severity") in {"blocker", "major"}
        ]
