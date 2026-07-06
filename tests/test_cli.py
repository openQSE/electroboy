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
            write_manual_runtime(root)
            self.assertEqual(self.run_cli(["--root", str(root), "requirements"])[0], 0)

            code, stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "stage",
                    "requirements",
                    "--human-approved",
                    "--author-confirmed",
                ]
            )
            gate_code, gate_stdout, _gate_stderr = self.run_cli(
                ["--root", str(root), "gate", "requirements"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("active stage: design", stdout)
        self.assertEqual(gate_code, 0)
        self.assertIn("requirements: pass", gate_stdout)

    def test_public_requirements_command_records_authoring(self) -> None:
        with temp_project() as root:
            self.assertEqual(self.run_cli(["--root", str(root), "init"])[0], 0)
            write_manual_runtime(root)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "requirements"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("authoring stage: requirements", stdout)
        self.assertIn("artifact: docs/requirements.md", stdout)

    def test_requirements_approval_requires_design_author_event(self) -> None:
        with temp_project() as root:
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            self.assertEqual(self.run_cli(["--root", str(root), "init"])[0], 0)

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "requirements-approve"]
            )

        self.assertEqual(code, 1)
        self.assertIn("agent confirmation is missing", stderr)

    def test_public_design_review_advances_to_design_acceptance(self) -> None:
        with temp_project() as root:
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            self.assertEqual(self.run_cli(["--root", str(root), "init"])[0], 0)
            write_manual_runtime(root)
            self.assertEqual(self.run_cli(["--root", str(root), "requirements"])[0], 0)
            self.assertEqual(
                self.run_cli(
                    [
                        "--root",
                        str(root),
                        "requirements-approve",
                    ]
                )[0],
                0,
            )

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "design-review"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("completed stage: design-review", stdout)
        self.assertIn("active stage: design-acceptance", stdout)

    def test_rejects_plan_before_design_acceptance(self) -> None:
        with temp_project() as root:
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            self.assertEqual(self.run_cli(["--root", str(root), "init"])[0], 0)
            write_manual_runtime(root)
            self.assertEqual(self.run_cli(["--root", str(root), "requirements"])[0], 0)
            self.assertEqual(
                self.run_cli(
                    [
                        "--root",
                        str(root),
                        "stage",
                        "requirements",
                        "--human-approved",
                        "--author-confirmed",
                    ]
                )[0],
                0,
            )

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "stage", "plan"]
            )

        self.assertEqual(code, 1)
        self.assertIn("active stage is design", stderr)

    def test_public_plan_approval_uses_traceability_gate(self) -> None:
        with temp_project() as root:
            write_file(root / "docs" / "requirements.md", "# Requirements\n\nREQ-1\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(
                root / "docs" / "implementation-plan.md",
                "# Plan\n\n## Phase 1\n\nRequirements: REQ-1\n",
            )
            self.assertEqual(self.run_cli(["--root", str(root), "init"])[0], 0)
            write_manual_runtime(root)
            self.assertEqual(self.run_cli(["--root", str(root), "requirements"])[0], 0)
            self.assertEqual(
                self.run_cli(["--root", str(root), "requirements-approve"])[0],
                0,
            )
            self.assertEqual(
                self.run_cli(["--root", str(root), "design-review"])[0],
                0,
            )
            self.assertEqual(
                self.run_cli(["--root", str(root), "design-approve"])[0],
                0,
            )
            self.assertEqual(
                self.run_cli(["--root", str(root), "implementation-plan"])[0],
                0,
            )

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "plan-approve"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("active stage: implementation", stdout)


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
