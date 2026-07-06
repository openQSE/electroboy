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
from electroboy.planning import planned_phases  # noqa: E402
from electroboy.state_store import StateStore  # noqa: E402


class PlanTests(unittest.TestCase):
    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_plan_check_requires_phase_and_requirement_traceability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            self.assertEqual(self.run_cli(["--root", str(root), "init"])[0], 0)

            blocked, _stdout, _stderr = self.run_cli(
                ["--root", str(root), "plan", "check"]
            )
            write_file(
                root / "docs" / "requirements.md",
                "# Requirements\n\n- REQ-1: Build the pipeline.\n",
            )
            write_file(
                root / "docs" / "implementation-plan.md",
                "# Plan\n\n## Phase 1\n\nRequirements: REQ-1\n",
            )
            passed, stdout, _stderr = self.run_cli(
                ["--root", str(root), "plan", "check"]
            )

        self.assertEqual(blocked, 1)
        self.assertEqual(passed, 0)
        self.assertIn("traceability: pass", stdout)

    def test_plan_update_records_decision_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_file(
                root / "docs" / "requirements.md",
                "# Requirements\n\n- REQ-1: Build the pipeline.\n",
            )
            write_file(
                root / "docs" / "implementation-plan.md",
                "# Plan\n\n## Phase 1\n\nRequirements: REQ-1\n",
            )
            self.assertEqual(self.run_cli(["--root", str(root), "init"])[0], 0)

            code, stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "plan",
                    "update",
                    "--reason",
                    "Split phase for review.",
                ]
            )
            activity = StateStore(root).read_activity()

        self.assertEqual(code, 0, stderr)
        self.assertIn("recorded implementation plan update", stdout)
        self.assertEqual(activity[-1]["action"], "plan-updated")
        self.assertIn("PLAN-0001", activity[-1]["summary"])
        self.assertTrue(activity[-1]["artifact_snapshot_refs"])

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


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
