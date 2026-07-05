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


class DesignLoopTests(unittest.TestCase):
    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_requirements_stage_snapshots_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            self.assertEqual(self.run_cli(["--root", str(root), "init"])[0], 0)
            write_manual_runtime(root)
            self.assertEqual(self.run_cli(["--root", str(root), "requirements"])[0], 0)

            code, _stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "stage",
                    "requirements",
                    "--human-approved",
                    "--author-confirmed",
                ]
            )

            run_dir = next(
                (root / ".agent-pipeline" / "shared" / "runs").iterdir()
            )
            snapshot = run_dir / "artifacts" / "docs" / "requirements.md"
            self.assertEqual(code, 0, stderr)
            self.assertTrue(snapshot.exists())

    def test_design_review_blocks_until_issue_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
                        "stage",
                        "requirements",
                        "--human-approved",
                        "--author-confirmed",
                    ]
                )[0],
                0,
            )
            self.assertEqual(
                self.run_cli(
                    [
                        "--root",
                        str(root),
                        "stage",
                        "design",
                        "--human-approved",
                    ]
                )[0],
                0,
            )
            self.assertEqual(
                self.run_cli(
                    [
                        "--root",
                        str(root),
                        "issues",
                        "add",
                        "design-review.jsonl",
                        "--id",
                        "DES-1",
                        "--source",
                        "design-review-agent",
                        "--severity",
                        "major",
                        "--summary",
                        "Missing workflow.",
                    ]
                )[0],
                0,
            )

            blocked, _stdout, stderr = self.run_cli(
                ["--root", str(root), "stage", "design-review"]
            )
            self.assertEqual(
                self.run_cli(
                    [
                        "--root",
                        str(root),
                        "issues",
                        "resolve",
                        "design-review.jsonl",
                        "DES-1",
                    ]
                )[0],
                0,
            )
            passed, _stdout, _stderr = self.run_cli(
                ["--root", str(root), "stage", "design-review"]
            )

        self.assertEqual(blocked, 1)
        self.assertIn("blocking design review issues remain", stderr)
        self.assertEqual(passed, 0)


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_manual_runtime(root: Path) -> None:
    write_file(root / "agent-response.md", "accepted\n")
    write_file(
        root / "agent-pipeline.toml",
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
