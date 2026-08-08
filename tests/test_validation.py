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
    GATE_TEST_PLAN,
    GATE_VALIDATION_TESTING,
    STAGE_DOCS_REVIEW,
    STAGE_VALIDATION,
)
from electroboy.state_store import StateStore  # noqa: E402


class ValidationTests(unittest.TestCase):
    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def prepare_validation_run(self, root: Path) -> StateStore:
        store = StateStore(root)
        manifest = store.init_run(run_id="run-1")
        write_validation_manual_runtime(root)
        write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
        write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
        manifest.complete_gate(GATE_IMPLEMENTATION)
        manifest.complete_gate(GATE_TEST_PLAN)
        manifest.set_active_stage(STAGE_VALIDATION)
        store.save_manifest(manifest)
        manager = ArtifactManager(root)
        store.append_artifact_snapshot(
            manager.snapshot(
                manifest.run_id,
                "docs/implementation-plan.md",
                "plan-approved",
            )
        )
        store.append_artifact_snapshot(
            manager.snapshot(
                manifest.run_id,
                "docs/test-plan.md",
                "test-plan-approved",
            )
        )
        return store

    def test_validation_passes_and_stays_ready_for_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.prepare_validation_run(root)
            write_test_suite(root)
            command = f"{sys.executable} -c \"print('validation ok')\""
            write_file(root / "docs" / "requirements.md", f"Validation: {command}\n")
            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "validate", "--command", command]
            )

            manifest = store.load_current_manifest()
            report = root / "docs" / "validation-report.md"
            report_text = report.read_text(encoding="utf-8")

            self.assertEqual(code, 0, stderr)
            self.assertIn("validation: passed", stdout)
            self.assertIn("next: run `electroboy validation-approve`", stdout)
            self.assertEqual(manifest.active_stage, STAGE_VALIDATION)
            self.assertTrue(manifest.has_gate(GATE_VALIDATION_TESTING))
            self.assertIn("validation ok", report_text)
            self.assertIn("artifact validation commands", report_text)
            self.assertIn("configured full test-suite command", report_text)
            self.assertTrue((root / "docs" / "test-review.md").exists())

    def test_validate_interactive_records_test_review_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.prepare_validation_run(root)
            command = f"{sys.executable} -c \"print('validation ok')\""
            write_file(root / "docs" / "requirements.md", f"Validation: {command}\n")

            code, stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "validate",
                    "--interactive",
                    "--command",
                    command,
                ]
            )

            manifest = store.load_current_manifest()
            session = store.read_session_record(
                STAGE_VALIDATION,
                "test_review_interactive",
            )
            prompt = sorted(
                (store.run_dir("run-1") / "messages").glob("*-prompt.md")
            )[-1].read_text(encoding="utf-8")
            report_exists = (root / "docs" / "validation-report.md").exists()

        self.assertEqual(code, 0, stderr)
        self.assertIn("interactive validation test-review session completed", stdout)
        self.assertFalse(manifest.has_gate(GATE_VALIDATION_TESTING))
        self.assertFalse(report_exists)
        self.assertIsNotNone(session)
        session = session or {}
        self.assertEqual(session["role"], "test_review_interactive")
        self.assertIn("Interactive mode:", prompt)
        self.assertIn("Review the approved system test plan", prompt)

    def test_validation_test_review_attempts_increment_on_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare_validation_run(root)
            write_test_suite(root)
            command = f"{sys.executable} -c \"print('validation ok')\""
            write_file(root / "docs" / "requirements.md", f"Validation: {command}\n")

            first_code, _first_stdout, first_stderr = self.run_cli(
                ["--root", str(root), "validate", "--command", command]
            )
            second_code, _second_stdout, second_stderr = self.run_cli(
                ["--root", str(root), "validate", "--command", command]
            )

            test_review = (root / "docs" / "test-review.md").read_text(
                encoding="utf-8"
            )
            attempt_1_exists = (
                root
                / "docs"
                / "reviews"
                / "test-review-validation-attempt-1.md"
            ).exists()
            attempt_2_exists = (
                root
                / "docs"
                / "reviews"
                / "test-review-validation-attempt-2.md"
            ).exists()

        self.assertEqual(first_code, 0, first_stderr)
        self.assertEqual(second_code, 0, second_stderr)
        self.assertTrue(attempt_1_exists)
        self.assertTrue(attempt_2_exists)
        self.assertIn("Latest review attempt: 2", test_review)
        self.assertIn("docs/reviews/test-review-validation-attempt-1.md", test_review)
        self.assertIn("docs/reviews/test-review-validation-attempt-2.md", test_review)

    def test_validation_approve_commits_reports_and_advances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configure_git_identity(root)
            store = self.prepare_validation_run(root)
            write_file(root / "docs" / "implementation-log.md", "# Log\n")
            write_file(root / "docs" / "implementation-report.md", "# Report\n")
            write_test_suite(root)
            command = f"{sys.executable} -c \"print('validation ok')\""
            write_file(root / "docs" / "requirements.md", f"Validation: {command}\n")
            self.assertEqual(
                self.run_cli(["--root", str(root), "validate", "--command", command])[0],
                0,
            )

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "validation-approve"]
            )
            manifest = store.load_current_manifest()
            committed_files = git_show_names(root)

        self.assertEqual(code, 0, stderr)
        self.assertIn("validation approved", stdout)
        self.assertEqual(manifest.active_stage, STAGE_DOCS_REVIEW)
        self.assertIn("docs/implementation-log.md", committed_files)
        self.assertIn("docs/implementation-report.md", committed_files)
        self.assertIn("docs/validation-report.md", committed_files)

    def test_validation_failure_records_blocking_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.prepare_validation_run(root)
            command = (
                f"{sys.executable} -c \"import sys; print('bad'); sys.exit(3)\""
            )
            write_file(root / "docs" / "requirements.md", f"Validation: {command}\n")
            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "validate", "--command", command]
            )

            manifest = store.load_current_manifest()
            issues = store.read_review_issues("validation-review.jsonl")
            phase_status = store.load_phase_status()

            self.assertEqual(code, 1, stderr)
            self.assertIn("validation: failed", stdout)
            self.assertEqual(manifest.active_stage, "implementation")
            self.assertFalse(manifest.has_gate(GATE_VALIDATION_TESTING))
        self.assertEqual(issues[0]["severity"], "blocker")
        self.assertEqual(issues[0]["status"], "open")
        self.assertIsNotNone(phase_status.active_phase)

    def test_validation_requires_approved_test_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = StateStore(root)
            manifest = store.init_run(run_id="run-1")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            manifest.complete_gate(GATE_IMPLEMENTATION)
            manifest.set_active_stage(STAGE_VALIDATION)
            store.save_manifest(manifest)
            snapshot = ArtifactManager(root).snapshot(
                manifest.run_id,
                "docs/implementation-plan.md",
                "plan-approved",
            )
            store.append_artifact_snapshot(snapshot)
            command = f"{sys.executable} -c \"print('validation ok')\""
            write_file(root / "docs" / "requirements.md", f"Validation: {command}\n")

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "validate", "--command", command]
            )

        self.assertEqual(code, 1)
        self.assertIn("predecessor gate is not complete: test-plan", stderr)

    def test_validation_pass_blocks_on_unresolved_validation_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare_validation_run(root)
            failing = (
                f"{sys.executable} -c \"import sys; print('bad'); sys.exit(3)\""
            )
            passing = f"{sys.executable} -c \"print('validation ok')\""
            write_test_suite(root)
            write_file(root / "docs" / "requirements.md", f"Validation: {failing}\n")
            self.assertEqual(
                self.run_cli(["--root", str(root), "validate", "--command", failing])[0],
                1,
            )
            store = StateStore(root)
            manifest = store.load_current_manifest()
            manifest.set_active_stage(STAGE_VALIDATION)
            store.save_manifest(manifest)
            write_file(root / "docs" / "requirements.md", f"Validation: {passing}\n")

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "validate", "--command", passing]
            )

            self.assertEqual(code, 1)
            self.assertIn("blocking validation or test-review issues remain", stderr)

    def test_validation_requires_full_test_suite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare_validation_run(root)
            command = f"{sys.executable} -c \"print('validation ok')\""
            write_file(root / "docs" / "requirements.md", f"Validation: {command}\n")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "validate", "--command", command]
            )

        self.assertEqual(code, 1, stderr)
        self.assertIn("validation: failed", stdout)

    def test_validation_missing_executable_records_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.prepare_validation_run(root)
            command = "definitely-missing-electroboy-command"
            write_file(root / "docs" / "requirements.md", f"Validation: {command}\n")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "validate"]
            )
            issues = store.read_review_issues("validation-review.jsonl")

        self.assertEqual(code, 1, stderr)
        self.assertIn("validation: failed", stdout)
        self.assertEqual(issues[0]["severity"], "blocker")
        self.assertIn(command, issues[0]["summary"])

    def test_validation_test_review_blocks_before_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.prepare_validation_run(root)
            write_validation_review_runtime(root, severity="blocker")
            write_test_suite(root)
            command = f"{sys.executable} -c \"print('validation ok')\""
            write_file(root / "docs" / "requirements.md", f"Validation: {command}\n")

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "validate", "--command", command]
            )

            manifest = store.load_current_manifest()
            issues = store.read_review_issues("validation-test-review.jsonl")

        self.assertEqual(code, 1)
        self.assertIn("test-review issue(s) remain", stderr)
        self.assertEqual(manifest.active_stage, "implementation")
        self.assertEqual(issues[0]["severity"], "blocker")
        self.assertEqual(issues[0]["status"], "open")

    def test_validation_blockers_only_defers_major_review_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.prepare_validation_run(root)
            write_validation_review_runtime(root, severity="major")
            write_test_suite(root)
            command = f"{sys.executable} -c \"print('validation ok')\""
            write_file(root / "docs" / "requirements.md", f"Validation: {command}\n")

            code, stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "validate",
                    "--blockers-only",
                    "--command",
                    command,
                ]
            )

            manifest = store.load_current_manifest()
            issues = store.read_review_issues("validation-test-review.jsonl")
            test_review = (root / "docs" / "test-review.md").read_text(
                encoding="utf-8"
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("validation: passed", stdout)
        self.assertTrue(manifest.has_gate(GATE_VALIDATION_TESTING))
        self.assertEqual(issues[0]["severity"], "major")
        self.assertEqual(issues[0]["status"], "deferred")
        self.assertIn("Status: deferred", test_review)


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_validation_manual_runtime(root: Path) -> None:
    write_file(root / "agent-response.md", "test review ok\n")
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
test_review = "manual"
""".lstrip(),
    )


def write_validation_review_runtime(root: Path, severity: str) -> None:
    script = root / "fake-agent.py"
    write_file(
        script,
        f"""
import json
import pathlib
import sys

raw_prompt = sys.stdin.read()
for line in raw_prompt.splitlines():
    if line.startswith("Progress file: "):
        progress = pathlib.Path(line.split(":", 1)[1].strip())
        progress.parent.mkdir(parents=True, exist_ok=True)
        progress.write_text("fake validation test review\\n", encoding="utf-8")
        break

issues = [{{
    "issue_id": "VTR-001",
    "severity": "{severity}",
    "status": "open",
    "summary": "Validation coverage needs review.",
    "artifact": "docs/test-plan.md",
    "location": "docs/test-plan.md:1",
    "rationale": "The system test plan lacks one required scenario.",
    "requested_change": "Add the missing validation scenario.",
}}]
print(json.dumps({{
    "ok": True,
    "final_message": "validation test review complete",
    "issues": issues,
}}))
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
args = ["{script}"]
env = ["PATH"]
structured_output = "json_schema"

[roles]
test_review = "agent"
""".lstrip(),
    )


def configure_git_identity(root: Path) -> None:
    subprocess.run(
        ["git", "-C", str(root), "init"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.com"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Test User"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def git_show_names(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "show", "--name-only", "--format=", "HEAD"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def write_test_suite(root: Path) -> None:
    write_file(
        root / "tests" / "test_smoke.py",
        "import unittest\n\n"
        "class SmokeTests(unittest.TestCase):\n"
        "    def test_smoke(self):\n"
        "        self.assertTrue(True)\n",
    )


if __name__ == "__main__":
    unittest.main()
