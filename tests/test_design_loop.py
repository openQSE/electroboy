from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.cli import main  # noqa: E402
from electroboy.models import ReviewIssue  # noqa: E402
from electroboy.state_store import StateStore  # noqa: E402


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
            configure_git_identity(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            StateStore(root).init_run(run_id="run-1")
            write_manual_runtime(root)
            self.assertEqual(self.run_cli(["--root", str(root), "requirements"])[0], 0)

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "requirements-approve"]
            )

            run_dir = next(
                (root / ".electroboy" / "shared" / "runs").iterdir()
            )
            snapshot = run_dir / "artifacts" / "docs" / "requirements.md"
            self.assertEqual(code, 0, stderr)
            self.assertTrue(snapshot.exists())

    def test_design_review_blocks_until_issue_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configure_git_identity(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            store = StateStore(root)
            store.init_run(run_id="run-1")
            write_manual_runtime(root)
            self.assertEqual(self.run_cli(["--root", str(root), "requirements"])[0], 0)
            self.assertEqual(
                self.run_cli(["--root", str(root), "requirements-approve"])[0],
                0,
            )
            store.append_review_issue(
                "design-review.jsonl",
                ReviewIssue(
                    issue_id="DES-1",
                    source="design-review-agent",
                    severity="major",
                    status="open",
                    summary="Missing workflow.",
                ),
            )

            blocked, _stdout, stderr = self.run_cli(
                ["--root", str(root), "design-review"]
            )
            store.append_review_issue(
                "design-review.jsonl",
                ReviewIssue(
                    issue_id="DES-1",
                    source="design-review-agent",
                    severity="major",
                    status="verified",
                    summary="Missing workflow.",
                ),
            )
            passed, _stdout, _stderr = self.run_cli(
                ["--root", str(root), "design-review"]
            )

        self.assertEqual(blocked, 1)
        self.assertIn("blocking design review issues remain", stderr)
        self.assertEqual(passed, 0)

    def test_design_review_writes_summary_and_commits_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            self.assertEqual(self.run_cli(["new", str(root), "--run-id", "run-1"])[0], 0)
            configure_git_identity(root)
            write_manual_runtime(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            self.assertEqual(self.run_cli(["--root", str(root), "requirements"])[0], 0)
            self.assertEqual(
                self.run_cli(["--root", str(root), "requirements-approve"])[0],
                0,
            )

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "design-review"]
            )
            summary = (root / "docs" / "design-review.md").read_text(
                encoding="utf-8"
            )
            committed_files = git_show_names(root)

        self.assertEqual(code, 0, stderr)
        self.assertIn("design-review: running design review agent", stdout)
        self.assertIn("summary: docs/design-review.md", stdout)
        self.assertIn("next: run `electroboy design-approve`", stdout)
        self.assertIn("Run ID: run-1", summary)
        self.assertIn("Stage result: passed", summary)
        self.assertIn("docs/detailed-design.md", summary)
        self.assertNotIn("docs/design-review.md", committed_files)


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def configure_git_identity(root: Path) -> None:
    subprocess.run(
        ["git", "-C", str(root), "init"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.com"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Test User"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def git_show_names(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "show", "--name-only", "--format=", "HEAD"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def write_manual_runtime(root: Path) -> None:
    write_file(root / "agent-response.md", "accepted\n")
    config = """
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
""".lstrip()
    write_file(root / "electroboy.toml", config)
    if (root / ".electroboy").exists():
        write_file(root / ".electroboy" / "project.toml", config)


if __name__ == "__main__":
    unittest.main()
