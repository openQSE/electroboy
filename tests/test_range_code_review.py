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
from electroboy.state_store import StateStore  # noqa: E402


class RangeCodeReviewTests(unittest.TestCase):
    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_code_review_range_records_commit_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_range_review_runtime(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
            initialize_git_repo(root)
            sha1 = create_commit(root, "src/one.py", "one = 1\n", "code: one")
            sha2 = create_commit(root, "src/two.py", "two = 2\n", "code: two")
            StateStore(root).init_run(run_id="run-1")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "code-review", f"{sha1}..{sha2}"]
            )

            summary = (root / "docs" / "code-review.md").read_text(
                encoding="utf-8"
            )
            messages_dir = (
                root
                / ".electroboy"
                / "shared"
                / "runs"
                / "run-1"
                / "messages"
            )
            prompts = "\n".join(
                path.read_text(encoding="utf-8")
                for path in messages_dir.glob("*-prompt.md")
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("commits reviewed: 2", stdout)
        self.assertIn("blocker/major findings: 1", stdout)
        self.assertIn("Mode: commit range review", summary)
        self.assertIn("Fix in place: no", summary)
        self.assertIn(f"Commit: {sha1}", summary)
        self.assertIn("RCR-", summary)
        self.assertIn("First inspect the final tree", prompts)
        self.assertIn("Then review each commit", prompts)

    def test_code_review_fix_in_place_amends_range_and_reruns_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fix_in_place_runtime(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
            initialize_git_repo(root)
            sha = create_commit(root, "src/work.py", "work = False\n", "code: work")
            StateStore(root).init_run(run_id="run-1")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "code-review", f"{sha}..{sha}", "--fix-in-place"]
            )

            new_head = git_head(root)
            summary = (root / "docs" / "code-review.md").read_text(
                encoding="utf-8"
            )

        self.assertEqual(code, 0, stderr)
        self.assertNotEqual(new_head, sha)
        self.assertIn("blocker/major findings: 1", stdout)
        self.assertIn("blocker/major findings: 0", stdout)
        self.assertIn("Fix in place: yes", summary)
        self.assertIn("Status: verified", summary)


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def initialize_git_repo(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Test User"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "baseline"],
        check=True,
        capture_output=True,
    )


def create_commit(root: Path, relative_path: str, text: str, message: str) -> str:
    write_file(root / relative_path, text)
    subprocess.run(["git", "-C", str(root), "add", relative_path], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", message],
        check=True,
        capture_output=True,
    )
    return git_head(root)


def git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def write_range_review_runtime(root: Path) -> None:
    write_file(
        root / "agent.py",
        """
from __future__ import annotations

import json
import re
import sys

prompt = sys.stdin.read()
commits = re.findall(r"- ([0-9a-f]{12}) ([0-9a-f]{40}) ", prompt)
commit = commits[0][1] if commits else ""
issue = {
    "issue_id": f"RCR-{commit[:8]}-001",
    "severity": "major",
    "status": "open",
    "summary": "Commit does not match the approved plan.",
    "commit": commit,
    "artifact": "src/one.py",
    "location": "src/one.py:1",
    "rationale": "The range reviewer should tie findings to commits.",
    "requested_change": "Align the commit with the implementation plan.",
}
print(json.dumps({"ok": True, "final_message": "reviewed", "issues": [issue]}))
""".lstrip(),
    )
    write_runtime_config(root)


def write_fix_in_place_runtime(root: Path) -> None:
    write_file(
        root / "agent.py",
        """
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

prompt = sys.stdin.read()
if "Fix code-review findings in place" in prompt:
    path = pathlib.Path("src/fixed.py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixed = True\\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/fixed.py"], check=True)
    subprocess.run(
        ["git", "commit", "--amend", "--no-edit"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print(json.dumps({"ok": True, "final_message": "fixed"}))
else:
    commits = re.findall(r"- ([0-9a-f]{12}) ([0-9a-f]{40}) ", prompt)
    commit = commits[-1][1] if commits else ""
    fixed = pathlib.Path("src/fixed.py").exists()
    issue = {
        "issue_id": "RCR-FIX-001",
        "severity": "major",
        "status": "verified" if fixed else "open",
        "summary": "Commit needs an in-place fix.",
        "commit": commit,
        "artifact": "src/work.py",
        "location": "src/work.py:1",
        "rationale": "The commit must be corrected before the range passes.",
        "requested_change": "Amend the offending commit.",
    }
    print(json.dumps({"ok": True, "final_message": "reviewed", "issues": [issue]}))
""".lstrip(),
    )
    write_runtime_config(root)


def write_runtime_config(root: Path) -> None:
    write_file(
        root / "electroboy.toml",
        f"""
[runtime]
default = "agent"

[runtimes.agent]
adapter = "generic_cli"
command = "{sys.executable}"
args = ["agent.py"]
env = ["PATH"]
structured_output = "json_schema"
""".lstrip(),
    )


if __name__ == "__main__":
    unittest.main()
