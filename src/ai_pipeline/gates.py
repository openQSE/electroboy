"""Deterministic gate checks for ordered pipeline flow."""

from __future__ import annotations

from pathlib import Path

from .models import (
    GATE_DESIGN,
    GATE_DOCUMENTATION,
    GATE_HUMAN_DESIGN_ACCEPTANCE,
    GATE_IMPLEMENTATION,
    GATE_REQUIREMENTS,
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


REQUIRED_FILES = {
    GATE_REQUIREMENTS: "docs/requirements.md",
    GATE_DESIGN: "docs/detailed-design.md",
    GATE_IMPLEMENTATION: "docs/implementation-plan.md",
    GATE_DOCUMENTATION: "docs/api.md",
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

    def evaluate(self, name: str, manifest: RunManifest) -> GateResult:
        if name == "stage-order":
            return self.stage_order(manifest.active_stage, manifest)
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
            return self._completed_gate(
                manifest,
                name,
                "human design acceptance has not been recorded",
            )
        if name == GATE_IMPLEMENTATION:
            return self._completed_file_gate(
                manifest,
                name,
                "docs/implementation-plan.md",
                "implementation-plan approval has not been recorded",
            )
        if name == GATE_VALIDATION_TESTING:
            return self._completed_gate(
                manifest,
                name,
                "validation testing has not been recorded",
            )
        if name == GATE_DOCUMENTATION:
            return self._completed_gate(
                manifest,
                name,
                "documentation review has not been recorded",
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

        if messages:
            return GateResult(name="stage-order", status="blocked", messages=messages)
        return GateResult(name="stage-order", status="pass")

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

    def _completed_file_gate(
        self,
        manifest: RunManifest,
        gate: str,
        relative_path: str,
        missing_message: str,
    ) -> GateResult:
        file_result = self.require_file(relative_path)
        if not file_result.passed:
            return GateResult(name=gate, status="blocked", messages=file_result.messages)
        return self._completed_gate(manifest, gate, missing_message)
