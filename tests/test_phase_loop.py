from __future__ import annotations

import io
import subprocess
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
    GATE_IMPLEMENTATION,
    STAGE_IMPLEMENTATION,
    STAGE_VALIDATION,
)
from electroboy.state_store import StateStore  # noqa: E402


class PhaseLoopTests(unittest.TestCase):
    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def prepare_implementation_run(self, root: Path) -> None:
        store = StateStore(root)
        manifest = store.init_run(run_id="run-1")
        manifest.complete_gate(GATE_IMPLEMENTATION)
        manifest.set_active_stage(STAGE_IMPLEMENTATION)
        store.save_manifest(manifest)
        if (root / "docs" / "implementation-plan.md").exists():
            snapshot = ArtifactManager(root).snapshot(
                manifest.run_id,
                "docs/implementation-plan.md",
                "plan-approved",
            )
            store.append_artifact_snapshot(snapshot)

    def test_phase_commit_requires_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manual_runtime(root)
            self.prepare_implementation_run(root)
            start_phase(root, 1)

            blocked, _stdout, stderr = self.run_cli(
                ["--root", str(root), "phase", "commit", "1"]
            )
            mark_phase_reviews(root, 1)
            manual_blocked, _manual_stdout, manual_stderr = self.run_cli(
                ["--root", str(root), "phase", "commit", "1"]
            )
            self.assertEqual(
                self.run_cli(["--root", str(root), "code", "--phased"])[0],
                0,
            )
            sha = create_git_commit(root, "phase 1: reviewed work")
            passed, stdout, _stderr = self.run_cli(
                ["--root", str(root), "phase", "commit", "1", "--sha", sha]
            )

        self.assertEqual(blocked, 1)
        self.assertIn("code review has not passed", stderr)
        self.assertEqual(manual_blocked, 1)
        self.assertIn("code review agent evidence is missing", manual_stderr)
        self.assertEqual(passed, 0)
        self.assertIn("committed phase: 1", stdout)

    def test_code_command_starts_next_planned_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manual_runtime(root)
            write_file(
                root / "docs" / "implementation-plan.md",
                "# Plan\n\n## Phase 1. First Work\n\nRequirements: REQ-1\n",
            )
            self.prepare_implementation_run(root)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "code", "--phased"]
            )

            status = StateStore(root).load_phase_status()

        self.assertEqual(code, 0, stderr)
        self.assertEqual(status.active_phase, 1)
        self.assertIn("active phase: 1", stdout)

    def test_code_command_automates_all_planned_phases_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_generic_agent_runtime(root)
            write_file(
                root / "docs" / "implementation-plan.md",
                "# Plan\n\n"
                "## Phase 1. First Work\n\n"
                "Requirements: REQ-1\n"
                "Paths: src/phase1\n\n"
                "## Phase 2. Second Work\n\n"
                "Requirements: REQ-1\n"
                "Paths: src/phase2\n",
            )
            initialize_git_repo(root)
            self.prepare_implementation_run(root)

            code, stdout, stderr = self.run_cli(["--root", str(root), "code"])

            store = StateStore(root)
            manifest = store.load_current_manifest()
            status = store.load_phase_status()
            phase1_exists = (root / "src" / "phase1" / "output.txt").exists()
            phase2_exists = (root / "src" / "phase2" / "output.txt").exists()
            implementation_log = root / "docs" / "implementation-log.md"
            implementation_report = root / "docs" / "implementation-report.md"
            implementation_log_text = implementation_log.read_text(encoding="utf-8")
            implementation_report_text = implementation_report.read_text(
                encoding="utf-8"
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("committed phase: 1", stdout)
        self.assertIn("committed phase: 2", stdout)
        self.assertIn("artifact: docs/implementation-log.md", stdout)
        self.assertIn("artifact: docs/implementation-report.md", stdout)
        self.assertEqual(manifest.active_stage, STAGE_VALIDATION)
        self.assertIsNone(status.active_phase)
        self.assertEqual(status.phases["1"]["status"], "committed")
        self.assertEqual(status.phases["2"]["status"], "committed")
        self.assertTrue(status.phases["1"]["commit"])
        self.assertTrue(status.phases["2"]["commit"])
        self.assertTrue(phase1_exists)
        self.assertTrue(phase2_exists)
        self.assertIn("Phase 1", implementation_log_text)
        self.assertIn("ready for validation", implementation_report_text)

    def test_phase_commit_requires_phase_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manual_runtime(root)
            self.prepare_implementation_run(root)
            start_phase(root, 1)
            self.assertEqual(
                self.run_cli(["--root", str(root), "code", "--phased"])[0],
                0,
            )
            sha = create_git_commit(root, "unrelated work")

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "phase", "commit", "1", "--sha", sha]
            )

        self.assertEqual(code, 1)
        self.assertIn("commit message must identify phase 1", stderr)

    def test_phase_commit_requires_scope_paths_when_plan_declares_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manual_runtime(root)
            write_file(
                root / "docs" / "implementation-plan.md",
                "# Plan\n\n"
                "## Phase 1. First Work\n\n"
                "Requirements: REQ-1\n"
                "Paths: src/allowed\n",
            )
            self.prepare_implementation_run(root)
            self.assertEqual(
                self.run_cli(["--root", str(root), "code", "--phased"])[0],
                0,
            )
            sha = create_git_commit(
                root,
                "phase 1: first work",
                "out of scope\n",
                relative_path="docs/out-of-scope.md",
            )

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "phase", "commit", "1", "--sha", sha]
            )

        self.assertEqual(code, 1)
        self.assertIn("outside phase 1 scope", stderr)


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def start_phase(root: Path, phase_number: int) -> None:
    store = StateStore(root)
    status = store.load_phase_status()
    status.active_phase = phase_number
    status.phases[str(phase_number)] = {
        "status": "active",
        "objective": "",
        "plan_current": True,
    }
    store.save_phase_status(status)


def mark_phase_reviews(root: Path, phase_number: int) -> None:
    store = StateStore(root)
    status = store.load_phase_status()
    phase = status.phases.setdefault(str(phase_number), {})
    phase["code_review"] = "passed"
    phase["test_review"] = "passed"
    store.save_phase_status(status)


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


def write_generic_agent_runtime(root: Path) -> None:
    write_file(
        root / "agent.py",
        """
from __future__ import annotations

import json
import pathlib
import sys

prompt = sys.stdin.read().lower()
if "phase 1" in prompt:
    path = pathlib.Path("src/phase1/output.txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("phase 1\\n", encoding="utf-8")
elif "phase 2" in prompt:
    path = pathlib.Path("src/phase2/output.txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("phase 2\\n", encoding="utf-8")
print(json.dumps({"ok": True, "final_message": "accepted"}))
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
coding = "agent"
code_review = "agent"
test_review = "agent"
""".lstrip(),
    )


def initialize_git_repo(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Test User"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "baseline"],
        check=True,
        capture_output=True,
    )


def create_git_commit(
    root: Path,
    message: str,
    content: str = "phase\n",
    relative_path: str = "phase.txt",
) -> str:
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Test User"],
        check=True,
        capture_output=True,
    )
    write_file(root / relative_path, content)
    subprocess.run(["git", "-C", str(root), "add", relative_path], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", message],
        check=True,
        capture_output=True,
    )
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    unittest.main()
