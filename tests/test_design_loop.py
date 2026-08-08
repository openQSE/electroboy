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

            snapshots = StateStore(root).read_artifact_snapshots()
            requirements_snapshots = [
                snapshot
                for snapshot in snapshots
                if snapshot.get("artifact_path") == "docs/requirements.md"
            ]
            self.assertEqual(code, 0, stderr)
            self.assertTrue(requirements_snapshots)
            self.assertTrue(
                (root / str(requirements_snapshots[-1]["snapshot_path"])).exists()
            )

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

    def test_design_review_interactive_records_session(self) -> None:
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

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "design-review", "--interactive"]
            )

            session = store.read_session_record(
                "design-review",
                "design_review_interactive",
            )
            prompt = sorted(
                (store.run_dir("run-1") / "messages").glob("*-prompt.md")
            )[-1].read_text(encoding="utf-8")

        self.assertEqual(code, 0, stderr)
        self.assertIn("interactive design-review session completed", stdout)
        self.assertIsNotNone(session)
        session = session or {}
        self.assertEqual(session["role"], "design_review_interactive")
        self.assertIn("Interactive mode:", prompt)
        self.assertIn("Review docs/detailed-design.md", prompt)

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
            store = StateStore(root)
            prompt_files = sorted(
                (store.run_dir("run-1") / "messages").glob("*-prompt.md")
            )
            prompt = prompt_files[-1].read_text(encoding="utf-8")
            summary = (root / "docs" / "design-review.md").read_text(
                encoding="utf-8"
            )
            committed_files = git_show_names(root)
            progress_exists = (
                root
                / ".electroboy"
                / "shared"
                / "runs"
                / "run-1"
                / "progress"
                / "design-review-progress.md"
            ).exists()

        self.assertEqual(code, 0, stderr)
        self.assertIn("design-review: running design review agent", stdout)
        self.assertIn("summary: docs/design-review.md", stdout)
        self.assertIn("next: run `electroboy design-approve`", stdout)
        self.assertIn("Run ID: run-1", summary)
        self.assertIn("Stage result: passed", summary)
        self.assertIn("docs/detailed-design.md", summary)
        self.assertNotIn("docs/design-review.md", committed_files)
        self.assertIn("Inspect source code as needed", prompt)
        self.assertIn("Do not modify files.", prompt)
        self.assertNotIn("Do not inspect source code", prompt)
        self.assertIn(
            "progress: .electroboy/shared/runs/run-1/progress/"
            "design-review-progress.md",
            stdout,
        )
        self.assertTrue(progress_exists)
        self.assertIn("Progress file:", prompt)
        self.assertIn("Structured output contract:", prompt)

    def test_design_review_coordinates_design_author_updates(self) -> None:
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
            write_review_update_runtime(root)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "design-review"]
            )
            design = (root / "docs" / "detailed-design.md").read_text(
                encoding="utf-8"
            )
            updates = (root / "docs" / "design-review-updates.md").read_text(
                encoding="utf-8"
            )
            issues = store.read_review_issues("design-review.jsonl")
            manifest = store.load_current_manifest()

        self.assertEqual(code, 0, stderr)
        self.assertIn("running design review agent pass 1", stdout)
        self.assertIn("running design author update after pass 1", stdout)
        self.assertIn("design author updated docs/detailed-design.md", stdout)
        self.assertIn("completed stage: design-review", stdout)
        self.assertIn("Reviewed update: aligned with code.", design)
        self.assertIn("### Update After Review Pass 1", updates)
        self.assertIn("DES-1: major open - Design lacks reviewed update.", updates)
        self.assertIn("+Reviewed update: aligned with code.", updates)
        self.assertEqual(issues[0]["status"], "verified")
        self.assertEqual(manifest.active_stage, "design-acceptance")

    def test_design_review_blocks_malformed_automated_review_output(self) -> None:
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
            write_narrative_review_update_runtime(root)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "design-review"]
            )
            design = (root / "docs" / "detailed-design.md").read_text(
                encoding="utf-8"
            )
            issues = store.read_review_issues("design-review.jsonl")

        self.assertEqual(code, 1, stderr)
        self.assertIn("Agent output contract failed for design_review", stdout)
        self.assertNotIn("Narrative update: aligned with review.", design)
        self.assertEqual(issues, [])


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


def write_review_update_runtime(root: Path) -> None:
    write_file(
        root / "agent.py",
        r'''
import json
from pathlib import Path
import sys


prompt = sys.stdin.read()
design_path = Path("docs/detailed-design.md")
design = design_path.read_text(encoding="utf-8")
for line in prompt.splitlines():
    if line.startswith("Progress file: "):
        progress = Path(line.split(":", 1)[1].strip())
        progress.parent.mkdir(parents=True, exist_ok=True)
        with progress.open("a", encoding="utf-8") as stream:
            stream.write("fake agent started\\n")
        break

if "Update docs/detailed-design.md" in prompt:
    design_path.write_text(
        design.rstrip() + "\n\nReviewed update: aligned with code.\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "ok": True,
        "final_message": "Updated the detailed design from review findings.",
        "changed_files": ["docs/detailed-design.md"],
    }))
elif "Reviewed update: aligned with code." in design:
    print(json.dumps({
        "ok": True,
        "final_message": "Design review findings are resolved.",
        "issues": [{
            "issue_id": "DES-1",
            "severity": "major",
            "status": "verified",
            "summary": "Design now includes the reviewed update.",
        }],
    }))
else:
    print(json.dumps({
        "ok": True,
        "final_message": "Design needs an update.",
        "issues": [{
            "issue_id": "DES-1",
            "severity": "major",
            "status": "open",
            "summary": "Design lacks reviewed update.",
        }],
    }))
'''.lstrip(),
    )
    config = """
[runtime]
default = "agent"

[runtimes.agent]
adapter = "generic_cli"
command = "python3"
args = ["agent.py"]

[roles]
design_review = "agent"
design_author_update = "agent"
""".lstrip()
    write_file(root / "electroboy.toml", config)
    if (root / ".electroboy").exists():
        write_file(root / ".electroboy" / "project.toml", config)


def write_narrative_review_update_runtime(root: Path) -> None:
    write_file(
        root / "agent.py",
        r'''
from pathlib import Path
import sys


prompt = sys.stdin.read()
design_path = Path("docs/detailed-design.md")
design = design_path.read_text(encoding="utf-8")
for line in prompt.splitlines():
    if line.startswith("Progress file: "):
        progress = Path(line.split(":", 1)[1].strip())
        progress.parent.mkdir(parents=True, exist_ok=True)
        with progress.open("a", encoding="utf-8") as stream:
            stream.write("fake agent started\\n")
        break

if "Update docs/detailed-design.md" in prompt:
    design_path.write_text(
        design.rstrip() + "\n\nNarrative update: aligned with review.\n",
        encoding="utf-8",
    )
    print("Updated the detailed design from narrative review findings.")
elif "Narrative update: aligned with review." in design:
    print("""**Blockers**

No blockers found.

**Major Findings**

No major findings.
""")
else:
    print("""**Blockers**

No blockers found.

**Major Findings**

1. **Major: Design lacks a narrative-reviewed flow.**
   The design does not describe the flow requested by the review.
   Requested change: add the missing design flow.
""")
'''.lstrip(),
    )
    config = """
[runtime]
default = "agent"

[runtimes.agent]
adapter = "generic_cli"
command = "python3"
args = ["agent.py"]

[roles]
design_review = "agent"
design_author_update = "agent"
""".lstrip()
    write_file(root / "electroboy.toml", config)
    if (root / ".electroboy").exists():
        write_file(root / ".electroboy" / "project.toml", config)


if __name__ == "__main__":
    unittest.main()
