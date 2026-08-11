from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.artifacts import ArtifactManager  # noqa: E402
from electroboy.cli import main  # noqa: E402
from electroboy.models import (  # noqa: E402
    GATE_DESIGN,
    GATE_DOCUMENTATION,
    GATE_HUMAN_DESIGN_ACCEPTANCE,
    GATE_IMPLEMENTATION,
    GATE_REQUIREMENTS,
    GATE_VALIDATION_TESTING,
    STAGE_COMPLETE,
    STAGE_DESIGN,
    STAGE_PLAN,
)
from electroboy.state_store import StateStore  # noqa: E402


class ChangeControlTests(unittest.TestCase):
    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_public_stage_command_reopens_earlier_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = StateStore(root)
            manifest = store.init_run(run_id="run-1")
            for gate in [
                GATE_REQUIREMENTS,
                GATE_DESIGN,
                GATE_HUMAN_DESIGN_ACCEPTANCE,
                GATE_IMPLEMENTATION,
                GATE_VALIDATION_TESTING,
                GATE_DOCUMENTATION,
            ]:
                manifest.complete_gate(gate)
            manifest.set_active_stage(STAGE_COMPLETE)
            store.save_manifest(manifest)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_manual_runtime(root)

            code, stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "requirements",
                    "--reason",
                    "New workflow discovered.",
                ]
            )
            manifest = store.load_current_manifest()
            requests = store.read_change_requests()

            self.assertEqual(code, 0, stderr)
            self.assertIn("reopened baseline: requirements", stdout)
            self.assertEqual(manifest.active_stage, "requirements")
            self.assertIn(GATE_REQUIREMENTS, manifest.invalidated_gates)
            self.assertEqual(requests[0]["status"], "reopened")

    def test_public_stage_reopen_requires_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = StateStore(root)
            manifest = store.init_run(run_id="run-1")
            manifest.complete_gate(GATE_REQUIREMENTS)
            manifest.set_active_stage(STAGE_PLAN)
            store.save_manifest(manifest)

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "requirements"]
            )

        self.assertEqual(code, 2)
        self.assertIn("reopen reason is required", stderr)

    def test_design_authoring_reopens_requirements_when_requirements_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = StateStore(root)
            manifest = store.init_run(run_id="run-1")
            manifest.complete_gate(GATE_REQUIREMENTS)
            manifest.set_active_stage(STAGE_DESIGN)
            store.save_manifest(manifest)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            append_snapshot(store, "docs/requirements.md", "requirements")
            write_authoring_agent_runtime(
                root,
                {
                    "docs/requirements.md": "# Requirements\n\nChanged in design.\n",
                    "docs/detailed-design.md": "# Design\n\nChanged.\n",
                },
            )

            code, stdout, stderr = self.run_cli(["--root", str(root), "design"])
            manifest = store.load_current_manifest()
            requests = store.read_change_requests()
            activity = store.read_activity()

        self.assertEqual(code, 0, stderr)
        self.assertIn("reopened baseline: requirements", stdout)
        self.assertIn("upstream artifact changes", stdout)
        self.assertIn("docs/requirements.md", stdout)
        self.assertIn("active stage: requirements", stdout)
        self.assertEqual(manifest.active_stage, "requirements")
        self.assertIn(GATE_REQUIREMENTS, manifest.invalidated_gates)
        self.assertEqual(requests[-1]["baseline"], "requirements")
        self.assertEqual(
            activity[-2]["artifact_changes"],
            [
                "docs/detailed-design.jsonl",
                "docs/detailed-design.md",
                "docs/requirements.jsonl",
                "docs/requirements.md",
            ],
        )

    def test_plan_authoring_reopens_earliest_upstream_artifact_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = StateStore(root)
            manifest = store.init_run(run_id="run-1")
            for gate in [
                GATE_REQUIREMENTS,
                GATE_DESIGN,
                GATE_HUMAN_DESIGN_ACCEPTANCE,
            ]:
                manifest.complete_gate(gate)
            manifest.set_active_stage(STAGE_PLAN)
            store.save_manifest(manifest)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            append_snapshot(store, "docs/requirements.md", "requirements")
            append_snapshot(store, "docs/detailed-design.md", "design")
            append_snapshot(store, "docs/detailed-design.md", "design-acceptance")
            write_authoring_agent_runtime(
                root,
                {
                    "docs/requirements.md": "# Requirements\n\nChanged in plan.\n",
                    "docs/detailed-design.md": "# Design\n\nChanged in plan.\n",
                    "docs/implementation-plan.md": "# Plan\n\nChanged.\n",
                },
            )

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "implementation-plan"]
            )
            manifest = store.load_current_manifest()
            requests = store.read_change_requests()

        self.assertEqual(code, 0, stderr)
        self.assertIn("reopened baseline: requirements", stdout)
        self.assertIn("docs/requirements.md", stdout)
        self.assertIn("docs/detailed-design.md", stdout)
        self.assertIn("active stage: requirements", stdout)
        self.assertEqual(manifest.active_stage, "requirements")
        self.assertIn(GATE_REQUIREMENTS, manifest.invalidated_gates)
        self.assertEqual(requests[-1]["baseline"], "requirements")


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_snapshot(store: StateStore, relative_path: str, event_id: str) -> None:
    snapshot = ArtifactManager(store.root).snapshot(
        store.load_current_manifest().run_id,
        relative_path,
        event_id,
    )
    store.append_artifact_snapshot(snapshot)


def write_manual_runtime(root: Path) -> None:
    write_file(root / "agent-response.md", "accepted\n")
    write_file(
        root / "electroboy.toml",
        """
[runtime]
default = "manual"

[runtimes.manual]
adapter = "manual"
command = "manual"
response_file = "agent-response.md"

[roles]
design_author = "manual"
design_review = "manual"
coding = "manual"
code_review = "manual"
test_review = "manual"
documentation = "manual"
""".lstrip(),
    )


def write_authoring_agent_runtime(root: Path, updates: dict[str, str]) -> None:
    update_lines = "\n".join(
        f"pathlib.Path({path!r}).write_text({text!r}, encoding='utf-8')"
        for path, text in updates.items()
    )
    write_file(
        root / "agent.py",
        f"""
from __future__ import annotations

import json
import pathlib
import sys

sys.stdin.read()
{update_lines}
print(json.dumps({{"ok": True, "final_message": "accepted"}}))
""".lstrip(),
    )
    write_file(
        root / "electroboy.toml",
        f"""
[runtime]
default = "agent"

[runtimes.agent]
adapter = "generic_cli"
command = "{sys.executable}"
args = ["agent.py"]
env = ["PATH"]

[roles]
design_author = "agent"
""".lstrip(),
    )


if __name__ == "__main__":
    unittest.main()
