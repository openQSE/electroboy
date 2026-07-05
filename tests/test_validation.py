from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_pipeline.cli import main  # noqa: E402
from ai_pipeline.models import (  # noqa: E402
    GATE_IMPLEMENTATION,
    GATE_VALIDATION_TESTING,
    STAGE_DOCS_REVIEW,
    STAGE_VALIDATION,
)
from ai_pipeline.state_store import StateStore  # noqa: E402


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
        manifest.complete_gate(GATE_IMPLEMENTATION)
        manifest.set_active_stage(STAGE_VALIDATION)
        store.save_manifest(manifest)
        return store

    def test_validation_passes_and_advances_to_documentation_review(self) -> None:
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
            report = (
                store.run_dir(manifest.run_id)
                / "artifacts"
                / "validation-report.md"
            )
            report_text = report.read_text(encoding="utf-8")

            self.assertEqual(code, 0, stderr)
            self.assertIn("validation: passed", stdout)
            self.assertEqual(manifest.active_stage, STAGE_DOCS_REVIEW)
            self.assertTrue(manifest.has_gate(GATE_VALIDATION_TESTING))
            self.assertIn("validation ok", report_text)
            self.assertIn("artifact validation commands", report_text)
            self.assertIn("configured full test-suite command", report_text)

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
            self.assertIn("blocking validation review issues remain", stderr)

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
            command = "definitely-missing-ai-pipeline-command"
            write_file(root / "docs" / "requirements.md", f"Validation: {command}\n")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "validate"]
            )
            issues = store.read_review_issues("validation-review.jsonl")

        self.assertEqual(code, 1, stderr)
        self.assertIn("validation: failed", stdout)
        self.assertEqual(issues[0]["severity"], "blocker")
        self.assertIn(command, issues[0]["summary"])


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
