from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.planning import (  # noqa: E402
    ensure_implementation_plan_jsonl,
    implementation_units_from_markdown,
    planned_phases,
    read_implementation_units,
)


class PlanTests(unittest.TestCase):
    def test_planned_phases_parse_clean_heading_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_file(
                root / "docs" / "implementation-plan.md",
                "# Plan\n\n"
                "## Phase 1. First Work\n\n"
                "Requirements: REQ-1\n"
                "Paths: src/electroboy\n"
                "Paths: tests\n",
            )

            phases = planned_phases(root)

        self.assertEqual(phases[0].heading, "Phase 1. First Work")
        self.assertEqual(phases[0].paths, ["src/electroboy", "tests"])

    def test_implementation_units_parse_commit_breakdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_file(
                root / "docs" / "implementation-plan.md",
                "# Plan\n\n"
                "## Detailed Design Traceability\n\n"
                "| Phase | Primary detailed-design body sections | Notes |\n"
                "| --- | --- | --- |\n"
                "| Phase 9. Completion Queues | "
                "[Execution APIs](detailed-design.md#execution-apis); "
                "[Integration Sequence](detailed-design.md#integration-sequence) | "
                "[CAT-002](detailed-design.md#cat-002) |\n\n"
                "## Commit Breakdown\n\n"
                "### Phase 9 Commit Sequence\n\n"
                "| Commit ID | Primary repo | Plan tasks | Scope and exit criteria |\n"
                "| --- | --- | --- | --- |\n"
                "| PH9-C01 | QFw | PH9.1 | Add controller-owned queues. |\n"
                "| PH9-C02 | QFw, DEFw | PH9.2, PH9.3 | Publish and read completions. |\n\n"
                "## Phase 9. Completion Queues\n\n"
                "1. PH9.1 Add reservation-scoped completion queue state.\n"
                "   - Reqs: `CAT-002`, `API-001`, `STATE-001`.\n\n"
                "2. PH9.2 Publish terminal completions in managed order.\n"
                "   - Reqs: `ADM-021`, `SCHED-005`.\n\n"
                "3. PH9.3 Implement scoped read_cq and peek_cq.\n"
                "   - Reqs: `API-001`, `API-004`.\n",
            )

            units = implementation_units_from_markdown(root)

        self.assertEqual([unit.unit_id for unit in units], ["PH9-C01", "PH9-C02"])
        self.assertEqual(units[0].phase, 9)
        self.assertEqual(units[0].sequence, 1)
        self.assertEqual(units[0].title, "Add reservation-scoped completion queue state.")
        self.assertEqual(units[0].requirements, ["CAT-002", "API-001", "STATE-001"])
        self.assertEqual(units[1].primary_repos, ["QFw", "DEFw"])
        self.assertEqual(units[1].plan_tasks, ["PH9.2", "PH9.3"])
        self.assertEqual(units[1].dependencies, ["PH9-C01"])
        self.assertEqual(
            units[1].design_sections,
            ["Execution APIs", "Integration Sequence"],
        )

    def test_ensure_implementation_plan_jsonl_writes_structured_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_file(
                root / "docs" / "implementation-plan.md",
                "# Plan\n\n"
                "## Phase 1. First Work\n\n"
                "Requirements: REQ-1\n"
                "Paths: src/electroboy\n",
            )

            units, created = ensure_implementation_plan_jsonl(root)
            reread = read_implementation_units(root)

        self.assertTrue(created)
        self.assertEqual([unit.unit_id for unit in units], ["PH1-C01"])
        self.assertEqual([unit.unit_id for unit in reread], ["PH1-C01"])
        self.assertEqual(reread[0].source_type, "markdown-phase-fallback")


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
