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


class CliTests(unittest.TestCase):
    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_init_and_status(self) -> None:
        with temp_project() as root:
            self.assertEqual(self.run_cli(["--root", str(root), "init"])[0], 0)

            code, stdout, stderr = self.run_cli(["--root", str(root), "status"])

        self.assertEqual(code, 0, stderr)
        self.assertIn("active stage: requirements", stdout)
        self.assertIn("completed gates:", stdout)

    def test_rejects_design_before_requirements(self) -> None:
        with temp_project() as root:
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            self.assertEqual(self.run_cli(["--root", str(root), "init"])[0], 0)

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "stage", "design"]
            )

        self.assertEqual(code, 1)
        self.assertIn("active stage is requirements", stderr)

    def test_requirements_stage_advances_to_design(self) -> None:
        with temp_project() as root:
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            self.assertEqual(self.run_cli(["--root", str(root), "init"])[0], 0)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "stage", "requirements"]
            )
            gate_code, gate_stdout, _gate_stderr = self.run_cli(
                ["--root", str(root), "gate", "requirements"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("active stage: design", stdout)
        self.assertEqual(gate_code, 0)
        self.assertIn("requirements: pass", gate_stdout)

    def test_rejects_plan_before_design_acceptance(self) -> None:
        with temp_project() as root:
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            self.assertEqual(self.run_cli(["--root", str(root), "init"])[0], 0)
            self.assertEqual(
                self.run_cli(["--root", str(root), "stage", "requirements"])[0],
                0,
            )

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "stage", "plan"]
            )

        self.assertEqual(code, 1)
        self.assertIn("active stage is design", stderr)


class temp_project:
    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        return self.root

    def __exit__(self, *args: object) -> None:
        self._tmp.cleanup()


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
