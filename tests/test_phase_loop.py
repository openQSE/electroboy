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
from ai_pipeline.models import GATE_IMPLEMENTATION, STAGE_IMPLEMENTATION  # noqa: E402
from ai_pipeline.state_store import StateStore  # noqa: E402


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

    def test_phase_commit_requires_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare_implementation_run(root)
            self.assertEqual(
                self.run_cli(["--root", str(root), "phase", "start", "1"])[0],
                0,
            )

            blocked, _stdout, stderr = self.run_cli(
                ["--root", str(root), "phase", "commit", "1"]
            )
            self.assertEqual(
                self.run_cli(
                    ["--root", str(root), "phase", "review", "1", "--pass"]
                )[0],
                0,
            )
            self.assertEqual(
                self.run_cli(["--root", str(root), "phase", "test", "1", "--pass"])[0],
                0,
            )
            passed, stdout, _stderr = self.run_cli(
                ["--root", str(root), "phase", "commit", "1", "--sha", "abc"]
            )

        self.assertEqual(blocked, 1)
        self.assertIn("code review has not passed", stderr)
        self.assertEqual(passed, 0)
        self.assertIn("committed phase: 1", stdout)

    def test_phase_drift_blocks_commit_until_plan_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_file(
                root / "docs" / "implementation-plan.md",
                "# Plan\n\n## Phase 1\n\nRequirements: REQ-1\n",
            )
            self.prepare_implementation_run(root)
            self.assertEqual(self.run_cli(["--root", str(root), "phase", "start", "1"])[0], 0)
            self.assertEqual(
                self.run_cli(
                    ["--root", str(root), "phase", "review", "1", "--pass"]
                )[0],
                0,
            )
            self.assertEqual(
                self.run_cli(["--root", str(root), "phase", "test", "1", "--pass"])[0],
                0,
            )
            self.assertEqual(
                self.run_cli(
                    [
                        "--root",
                        str(root),
                        "phase",
                        "drift",
                        "1",
                        "--reason",
                        "Scope changed.",
                    ]
                )[0],
                0,
            )

            blocked, _stdout, stderr = self.run_cli(
                ["--root", str(root), "phase", "commit", "1"]
            )
            self.assertEqual(
                self.run_cli(
                    ["--root", str(root), "plan", "update", "--reason", "Updated."]
                )[0],
                0,
            )
            passed, _stdout, _stderr = self.run_cli(
                ["--root", str(root), "phase", "commit", "1"]
            )

        self.assertEqual(blocked, 1)
        self.assertIn("active phase has plan drift", stderr)
        self.assertEqual(passed, 0)


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
