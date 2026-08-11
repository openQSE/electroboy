from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.state_store import StateStore  # noqa: E402
from electroboy.planning import ImplementationUnit  # noqa: E402
from electroboy.structured_artifacts import (  # noqa: E402
    artifact_jsonl_path,
    import_artifact,
    markdown_to_artifact_records,
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

    def test_import_artifact_preserves_rich_requirement_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            StateStore(root).init_run(run_id="run-1")
            markdown = """# Requirements

## REQ-001. Submit request

**Statement:** The system accepts a request.

| Input | Expected |
| --- | --- |
| valid | accepted |

```mermaid
flowchart LR
A-->B
```

**Acceptance Criteria:**
- Valid requests are accepted.
- Invalid requests are rejected.
"""
            path = root / "docs" / "requirements.md"
            path.parent.mkdir()
            path.write_text(markdown, encoding="utf-8")

            result = import_artifact(root, "requirements")
            records = [
                json.loads(line)
                for line in (root / "docs" / "requirements.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]

        self.assertEqual(result.record_count, 2)
        requirement = records[1]
        self.assertEqual(requirement["id"], "REQ-001")
        self.assertEqual(requirement["statement"], "The system accepts a request.")
        self.assertIn("| Input | Expected |", requirement["body"])
        self.assertIn("```mermaid", requirement["body"])
        self.assertEqual(
            requirement["acceptance_criteria"],
            ["Valid requests are accepted.", "Invalid requests are rejected."],
        )

    def test_import_artifact_splits_requirement_table_rows(self) -> None:
        records = markdown_to_artifact_records(
            "requirements",
            """# Requirements

## Behavior Requirements

| Requirement ID | Description |
| --- | --- |
| BEH-001 | The system shall create a shared family plan. |
| BEH-002 | The system shall detect schedule conflicts. |

## Similar Tools

| Tool | Capability |
| --- | --- |
| Cozi | Shared calendar |
""",
        )

        by_id = {str(record.get("id")): record for record in records}
        self.assertEqual(by_id["BEH-001"]["record_type"], "requirement")
        self.assertEqual(
            by_id["BEH-001"]["statement"],
            "The system shall create a shared family plan.",
        )
        self.assertEqual(by_id["BEH-001"]["tags"], ["behavior-requirements"])
        self.assertEqual(by_id["BEH-002"]["record_type"], "requirement")
        behavior = next(
            record
            for record in records
            if record.get("title") == "Behavior Requirements"
        )
        similar_tools = next(
            record
            for record in records
            if record.get("title") == "Similar Tools"
        )
        self.assertNotIn("BEH-001", str(behavior.get("body", "")))
        self.assertIn("| Tool | Capability |", similar_tools["body"])

    def test_markdown_import_commit_tasks_drive_plan_tasks(self) -> None:
        records = markdown_to_artifact_records(
            "implementation-plan",
            """# Implementation Plan

## Phase 1

### PH1-C1. Add model

Implement this as one commit.

**Commit Tasks:**
- Add model.
- Add tests.
""",
        )
        unit = ImplementationUnit.from_dict(records[1])

        self.assertEqual(unit.commit_tasks, ["Add model.", "Add tests."])
        self.assertEqual(unit.plan_tasks, ["Add model.", "Add tests."])
        self.assertEqual(unit.body, "Implement this as one commit.")

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
