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
            activity = store.read_activity()
            snapshots = store.read_artifact_snapshots()
            readme_snapshots = [
                snapshot
                for snapshot in snapshots
                if snapshot.get("artifact_path") == "README.md"
            ]
            api_snapshots = [
                snapshot
                for snapshot in snapshots
                if snapshot.get("artifact_path") == "docs/api.md"
            ]

            self.assertEqual(code, 0, stderr)
            self.assertIn("documentation review: passed", stdout)
            self.assertEqual(manifest.active_stage, STAGE_COMPLETE)
            self.assertTrue(manifest.has_gate(GATE_DOCUMENTATION))
            self.assertTrue(api_snapshots)
            self.assertTrue(readme_snapshots)
            self.assertTrue((root / str(api_snapshots[-1]["snapshot_path"])).exists())
            self.assertTrue(
                (root / str(readme_snapshots[-1]["snapshot_path"])).exists()
            )
            self.assertIn(
                readme_snapshots[-1]["snapshot_path"],
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

    def test_document_interactive_records_session_without_completing_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.prepare_docs_review_run(root)
            write_docs(root, include_api=True)
            write_manual_runtime(root)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "document", "--interactive"]
            )

            manifest = store.load_current_manifest()
            session = store.read_session_record(
                STAGE_DOCS_REVIEW,
                "documentation_interactive",
            )
            prompt = sorted(
                (store.run_dir("run-1") / "messages").glob("*-prompt.md")
            )[-1].read_text(encoding="utf-8")

        self.assertEqual(code, 0, stderr)
        self.assertIn("interactive documentation session completed", stdout)
        self.assertEqual(manifest.active_stage, STAGE_DOCS_REVIEW)
        self.assertFalse(manifest.has_gate(GATE_DOCUMENTATION))
        self.assertIsNotNone(session)
        session = session or {}
        self.assertEqual(session["role"], "documentation_interactive")
        self.assertIn("Interactive mode:", prompt)
        self.assertIn("Review final documentation", prompt)

    def test_document_sidecar_interactive_waits_for_operator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.prepare_docs_review_run(root)
            write_docs(root, include_api=True)
            write_manual_runtime(root)

            code, stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "document",
                    "--sidecar",
                    "--interactive",
                    "--target",
                    "docs/guide.md",
                ]
            )

            prompt = sorted(
                (store.run_dir("run-1") / "messages").glob("*-prompt.md")
            )[-1].read_text(encoding="utf-8")

        self.assertEqual(code, 0, stderr)
        self.assertIn("documentation sidecar completed", stdout)
        self.assertIn("Read the project documentation under docs/", prompt)
        self.assertIn("wait for operator instructions", prompt)
        self.assertIn("Selected documentation target: docs/guide.md.", prompt)
        self.assertIn("Do not proactively create, rewrite, or update documentation.", prompt)
        self.assertNotIn("Review final documentation against the completed codebase.", prompt)
        self.assertNotIn("Report files changed and a concise commit_message", prompt)

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
            "Commands: new meta add start status deactivate requirements "
            "requirements-approve design design-review design-approve "
            "implementation-plan plan-approve test-plan test-plan-approve "
            "bug code code-review corkboard document render-artifact import-artifact "
            "code-approve progress monitor report phase refresh-runtime service "
            "serve validate validation-approve completion feature.\n",
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
