from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.cli import main  # noqa: E402
from electroboy.models import (  # noqa: E402
    GATE_DOCUMENTATION,
    GATE_VALIDATION_TESTING,
    STAGE_COMPLETE,
    STAGE_DOCS_REVIEW,
)
from electroboy.state_store import StateStore  # noqa: E402


class DocumentationReviewTests(unittest.TestCase):
    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def prepare_docs_review_run(self, root: Path) -> StateStore:
        store = StateStore(root)
        manifest = store.init_run(run_id="run-1")
        manifest.complete_gate(GATE_VALIDATION_TESTING)
        manifest.set_active_stage(STAGE_DOCS_REVIEW)
        store.save_manifest(manifest)
        return store

    def test_docs_review_records_missing_file_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.prepare_docs_review_run(root)
            write_docs(root, include_api=False)
            write_manual_runtime(root)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "document"]
            )
            issues = store.read_review_issues("documentation-review.jsonl")

            self.assertEqual(code, 1, stderr)
            self.assertIn("documentation review: failed", stdout)
            self.assertEqual(issues[0]["severity"], "blocker")
            self.assertIn("docs/api.md", issues[0]["summary"])

    def test_docs_review_reconciles_restored_missing_file_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.prepare_docs_review_run(root)
            write_docs(root, include_api=False)
            write_manual_runtime(root)
            self.assertEqual(self.run_cli(["--root", str(root), "document"])[0], 1)
            write_docs(root, include_api=True)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "document"]
            )
            issues = store.read_review_issues("documentation-review.jsonl")

            self.assertEqual(code, 0, stderr)
            self.assertIn("documentation review: passed", stdout)
            self.assertEqual(issues[0]["status"], "verified")

    def test_docs_review_passes_and_snapshots_documentation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.prepare_docs_review_run(root)
            write_docs(root, include_api=True)
            write_manual_runtime(root)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "document"]
            )
            manifest = store.load_current_manifest()
            api_snapshot = (
                store.run_dir(manifest.run_id)
                / "artifacts"
                / "docs"
                / "api.md"
            )
            readme_snapshot = (
                store.run_dir(manifest.run_id) / "artifacts" / "README.md"
            )
            activity = store.read_activity()

            self.assertEqual(code, 0, stderr)
            self.assertIn("documentation review: passed", stdout)
            self.assertEqual(manifest.active_stage, STAGE_COMPLETE)
            self.assertTrue(manifest.has_gate(GATE_DOCUMENTATION))
            self.assertTrue(api_snapshot.exists())
            self.assertTrue(readme_snapshot.exists())
            self.assertIn(
                ".electroboy/shared/runs/run-1/artifacts/README.md",
                activity[-1]["artifact_snapshot_refs"],
            )

    def test_document_command_runs_documentation_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.prepare_docs_review_run(root)
            write_docs(root, include_api=True)
            write_manual_runtime(root)

            code, stdout, stderr = self.run_cli(["--root", str(root), "document"])

            manifest = store.load_current_manifest()

        self.assertEqual(code, 0, stderr)
        self.assertIn("documentation review: passed", stdout)
        self.assertEqual(manifest.active_stage, STAGE_COMPLETE)

    def test_code_approve_requires_documentation_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare_docs_review_run(root)
            write_docs(root, include_api=True)
            write_manual_runtime(root)

            blocked, _stdout, stderr = self.run_cli(
                ["--root", str(root), "code-approve"]
            )
            self.assertEqual(self.run_cli(["--root", str(root), "document"])[0], 0)
            passed, stdout, _stderr = self.run_cli(
                ["--root", str(root), "code-approve"]
            )

        self.assertEqual(blocked, 1)
        self.assertIn("documentation review has not been recorded", stderr)
        self.assertEqual(passed, 0)
        self.assertIn("completion approval: recorded", stdout)


def write_docs(root: Path, include_api: bool) -> None:
    write_file(root / "docs" / "requirements.md", "# Requirements\n")
    write_file(root / "docs" / "detailed-design.md", "# Detailed Design\n")
    write_file(
        root / "README.md",
        "# Project\n\nRun with `PYTHONPATH=src python -m electroboy --help`.\n"
        "Run tests with `python -m unittest discover -s tests`.\n",
    )
    if include_api:
        write_file(
            root / "docs" / "api.md",
            "# API\n\n"
            "Commands: new status deactivate requirements "
            "requirements-approve design design-review design-approve "
            "implementation-plan plan-approve code document code-approve "
            "report stage phase validate validation-approve.\n",
        )


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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


if __name__ == "__main__":
    unittest.main()
