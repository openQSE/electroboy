from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.state_store import StateStore  # noqa: E402
from electroboy.structured_artifacts import (  # noqa: E402
    artifact_jsonl_path,
    render_artifact,
    render_artifact_markdown,
)


class StructuredArtifactTests(unittest.TestCase):
    def test_render_design_preserves_markdown_body(self) -> None:
        markdown = render_artifact_markdown(
            "design",
            [
                {
                    "record_type": "document",
                    "title": "Design",
                },
                {
                    "record_type": "section",
                    "id": "DES-001",
                    "order": 10,
                    "title": "Flow",
                    "body": "```mermaid\nflowchart LR\nA-->B\n```",
                    "requirements": ["REQ-001"],
                },
            ],
        )

        self.assertIn("## DES-001. Flow", markdown)
        self.assertIn("```mermaid\nflowchart LR\nA-->B\n```", markdown)
        self.assertIn("- REQ-001", markdown)

    def test_render_test_plan_preserves_markdown_body(self) -> None:
        markdown = render_artifact_markdown(
            "test-plan",
            [
                {
                    "record_type": "test",
                    "id": "TEST-001",
                    "order": 10,
                    "title": "Manual table",
                    "body": "| Input | Expected |\n| --- | --- |\n| A | B |",
                    "steps": ["Run the command."],
                    "expected_results": ["It succeeds."],
                },
            ],
        )

        self.assertIn("| Input | Expected |", markdown)
        self.assertIn("**Steps:**", markdown)
        self.assertIn("- It succeeds.", markdown)

    def test_render_implementation_unit_uses_commit_tasks(self) -> None:
        markdown = render_artifact_markdown(
            "implementation-plan",
            [
                {
                    "unit_id": "PH1-C1",
                    "phase": 1,
                    "sequence": 1,
                    "title": "Add model",
                    "body": "Commit this as one reviewed unit.",
                    "commit_tasks": ["Add model.", "Add tests."],
                },
            ],
        )

        self.assertIn("## Phase 1", markdown)
        self.assertIn("### PH1-C1. Add model", markdown)
        self.assertIn("Commit this as one reviewed unit.", markdown)
        self.assertIn("**Commit Tasks:**", markdown)
        self.assertIn("- Add tests.", markdown)

    def test_render_artifact_writes_markdown_from_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            StateStore(root).init_run(run_id="run-1")
            jsonl = root / "docs" / "requirements.jsonl"
            jsonl.parent.mkdir()
            jsonl.write_text(
                json.dumps(
                    {
                        "record_type": "requirement",
                        "id": "REQ-001",
                        "order": 10,
                        "title": "Submit request",
                        "body": "Detailed body.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = render_artifact(root, "requirements")
            rendered = (root / "docs" / "requirements.md").read_text(
                encoding="utf-8",
            )

        self.assertEqual(result.jsonl_path, "docs/requirements.jsonl")
        self.assertEqual(result.markdown_path, "docs/requirements.md")
        self.assertEqual(result.record_count, 1)
        self.assertIn("Detailed body.", rendered)

    def test_feature_jsonl_path_follows_feature_markdown_path(self) -> None:
        self.assertEqual(
            artifact_jsonl_path(
                Path("/tmp/project"),
                "requirements",
                "docs/requirements-munge.md",
            ),
            "docs/requirements-munge.jsonl",
        )


if __name__ == "__main__":
    unittest.main()
