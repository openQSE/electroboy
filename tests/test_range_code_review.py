from __future__ import annotations

import io
import json
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

            summary = read_code_review_summary(root)
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
        self.assertIn("code review id: CR-0001", stdout)
        self.assertIn("commits reviewed: 2", stdout)
        self.assertIn("blocker/major findings: 1", stdout)
        self.assertIn("Mode: commit range review", summary)
        self.assertIn("Fix in place: no", summary)
        self.assertIn(f"Commit: {sha1}", summary)
        self.assertIn("RCR-", summary)
        self.assertIn("First inspect the final tree", prompts)
        self.assertIn("Then review each commit", prompts)

    def test_code_review_single_commit_records_commit_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_range_review_runtime(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
            initialize_git_repo(root)
            sha = create_commit(root, "src/one.py", "one = 1\n", "code: one")
            StateStore(root).init_run(run_id="run-1")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "code-review", sha]
            )

            summary = read_code_review_summary(root)
            prompts = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (
                    root
                    / ".electroboy"
                    / "shared"
                    / "runs"
                    / "run-1"
                    / "messages"
                ).glob("*-prompt.md")
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("code review id: CR-0001", stdout)
        self.assertIn("commits reviewed: 1", stdout)
        self.assertIn("Mode: single commit review", summary)
        self.assertIn(f"Range: {sha}", summary)
        self.assertIn(f"Commit: {sha}", summary)
        self.assertIn(f"Review commit {sha}", prompts)

    def test_code_review_without_target_reviews_current_codebase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_range_review_runtime(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
            initialize_git_repo(root)
            head = create_commit(root, "src/one.py", "one = 1\n", "code: one")
            StateStore(root).init_run(run_id="run-1")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "code-review"]
            )

            summary = read_code_review_summary(root)
            prompts = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (
                    root
                    / ".electroboy"
                    / "shared"
                    / "runs"
                    / "run-1"
                    / "messages"
                ).glob("*-prompt.md")
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("code review id: CR-0001", stdout)
        self.assertIn("reviewed target: codebase", stdout)
        self.assertIn("blocker/major findings: 1", stdout)
        self.assertIn("issue file: code-review-CR-0001.jsonl", stdout)
        self.assertIn("Mode: full codebase review", summary)
        self.assertIn("Range: none", summary)
        self.assertIn(f"Reviewed tree: {head}", summary)
        self.assertIn("Review the current codebase.", prompts)

    def test_code_review_interactive_records_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manual_runtime(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
            StateStore(root).init_run(run_id="run-1")

            code, stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "code-review",
                    "--interactive",
                    "--msg",
                    "focus on admission edge cases",
                ]
            )

            store = StateStore(root)
            session = store.read_session_record(
                "code-review",
                "code_review_interactive",
            )
            prompt = sorted(
                (store.run_dir("run-1") / "messages").glob("*-prompt.md")
            )[-1].read_text(encoding="utf-8")

        self.assertEqual(code, 0, stderr)
        self.assertIn("interactive code-review session completed", stdout)
        self.assertIsNotNone(session)
        session = session or {}
        self.assertEqual(session["role"], "code_review_interactive")
        self.assertIn("Interactive mode:", prompt)
        self.assertIn("Review the current codebase", prompt)
        self.assertIn("focus on admission edge cases", prompt)

    def test_code_review_contract_failure_does_not_report_zero_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_invalid_review_runtime(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
            initialize_git_repo(root)
            create_commit(root, "src/one.py", "one = 1\n", "code: one")
            StateStore(root).init_run(run_id="run-1")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "code-review"]
            )
            list_code, list_stdout, list_stderr = self.run_cli(
                ["--root", str(root), "code-review", "list"]
            )

        self.assertEqual(code, 1, stderr)
        self.assertIn("code review id: CR-0001", stdout)
        self.assertIn("Agent output contract failed for range_code_review", stdout)
        self.assertIn(
            "Review completed; found 1 blocker and 1 major finding.",
            stdout,
        )
        self.assertNotIn("blocker/major findings: 0", stdout)
        self.assertNotIn("code review: docs/code-review-CR-0001.md", stdout)
        self.assertFalse((root / "docs" / "code-review-CR-0001.md").exists())
        self.assertEqual(list_code, 0, list_stderr)
        self.assertIn("CR-0001 codebase@", list_stdout)
        self.assertIn("status=failed", list_stdout)

    def test_code_review_repairs_malformed_review_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_repairable_review_runtime(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
            initialize_git_repo(root)
            create_commit(root, "src/one.py", "one = 1\n", "code: one")
            StateStore(root).init_run(run_id="run-1")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "code-review"]
            )
            summary = read_code_review_summary(root)

        self.assertEqual(code, 0, stderr)
        self.assertIn("code review id: CR-0001", stdout)
        self.assertNotIn("Agent output contract failed", stdout)
        self.assertIn("blocker/major findings: 2", stdout)
        self.assertIn("Blocker/major findings: 2", summary)
        self.assertIn("CODEBASE-001", summary)
        self.assertIn("Missing admission validation.", summary)
        self.assertIn("CODEBASE-002", summary)
        self.assertIn("Scheduler state update is incomplete.", summary)

    def test_code_review_list_shows_records_and_verbose_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_range_review_runtime(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
            initialize_git_repo(root)
            create_commit(root, "src/one.py", "one = 1\n", "code: one")
            StateStore(root).init_run(run_id="run-1")

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "code-review"]
            )
            list_code, list_stdout, list_stderr = self.run_cli(
                ["--root", str(root), "code-review", "list"]
            )
            verbose_code, verbose_stdout, verbose_stderr = self.run_cli(
                ["--root", str(root), "code-review", "list", "CR-0001", "--verbose"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(list_code, 0, list_stderr)
        self.assertIn("CR-0001 codebase@", list_stdout)
        self.assertIn("blocker/major=1", list_stdout)
        self.assertIn("report=docs/code-review-CR-0001.md", list_stdout)
        self.assertEqual(verbose_code, 0, verbose_stderr)
        self.assertIn("findings:", verbose_stdout)
        self.assertIn("Commit does not match the approved plan.", verbose_stdout)

    def test_code_review_without_target_rejects_fix_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            StateStore(root).init_run(run_id="run-1")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "code-review", "--fix-in-place"]
            )

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("requires a commit or commit range target", stderr)

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
            summary = read_code_review_summary(root)

        self.assertEqual(code, 0, stderr)
        self.assertNotEqual(new_head, sha)
        self.assertIn("blocker/major findings: 1", stdout)
        self.assertIn("blocker/major findings: 0", stdout)
        self.assertIn("Fix in place: yes", summary)
        self.assertIn("Status: verified", summary)

    def test_code_review_fix_followup_appends_commit_and_reruns_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fix_followup_runtime(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
            initialize_git_repo(root)
            sha = create_commit(root, "src/work.py", "work = False\n", "code: work")
            StateStore(root).init_run(run_id="run-1")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "code-review", f"{sha}..{sha}", "--fix-followup"]
            )

            new_head = git_head(root)
            reviewed_commit = git_revision(root, f"{new_head}~1")
            summary = read_code_review_summary(root)

        self.assertEqual(code, 0, stderr)
        self.assertEqual(reviewed_commit, sha)
        self.assertNotEqual(new_head, sha)
        self.assertIn("blocker/major findings: 1", stdout)
        self.assertIn("blocker/major findings: 0", stdout)
        self.assertIn("Fix follow-up: yes", summary)
        self.assertIn("Status: verified", summary)

    def test_code_review_codebase_fix_followup_appends_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_codebase_fix_followup_runtime(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
            initialize_git_repo(root)
            sha = create_commit(root, "src/work.py", "work = False\n", "code: work")
            StateStore(root).init_run(run_id="run-1")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "code-review", "--fix-followup"]
            )

            new_head = git_head(root)
            reviewed_commit = git_revision(root, f"{new_head}~1")
            summary = read_code_review_summary(root)

        self.assertEqual(code, 0, stderr)
        self.assertEqual(reviewed_commit, sha)
        self.assertNotEqual(new_head, sha)
        self.assertIn("reviewed target: codebase", stdout)
        self.assertIn("blocker/major findings: 1", stdout)
        self.assertIn("blocker/major findings: 0", stdout)
        self.assertIn("Mode: full codebase review", summary)
        self.assertIn("Fix follow-up: yes", summary)
        self.assertIn("Status: verified", summary)

    def test_code_review_id_fix_followup_uses_existing_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_codebase_fix_followup_runtime(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
            initialize_git_repo(root)
            sha = create_commit(root, "src/work.py", "work = False\n", "code: work")
            StateStore(root).init_run(run_id="run-1")

            review_code, review_stdout, review_stderr = self.run_cli(
                ["--root", str(root), "code-review"]
            )
            fix_code, fix_stdout, fix_stderr = self.run_cli(
                ["--root", str(root), "code-review", "CR-0001", "--fix-followup"]
            )

            new_head = git_head(root)
            reviewed_commit = git_revision(root, f"{new_head}~1")
            summary = read_code_review_summary(root)

        self.assertEqual(review_code, 0, review_stderr)
        self.assertIn("blocker/major findings: 1", review_stdout)
        self.assertEqual(fix_code, 0, fix_stderr)
        self.assertEqual(reviewed_commit, sha)
        self.assertNotEqual(new_head, sha)
        self.assertIn("code review id: CR-0001", fix_stdout)
        self.assertIn("blocker/major findings: 1", fix_stdout)
        self.assertIn("blocker/major findings: 0", fix_stdout)
        self.assertIn("Status: verified", summary)

    def test_code_review_fix_in_place_blocks_dirty_tree_without_review_issue(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
            initialize_git_repo(root)
            sha = create_commit(root, "src/work.py", "work = False\n", "code: work")
            StateStore(root).init_run(run_id="run-1")
            write_file(root / "src" / "work.py", "work = 'unrelated'\n")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "code-review", f"{sha}..{sha}", "--fix-in-place"]
            )

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("requires a clean tracked worktree: src/work.py", stderr)

    def test_code_review_fix_in_place_resumes_dirty_interrupted_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_resume_dirty_fix_runtime(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
            initialize_git_repo(root)
            sha = create_commit(root, "src/work.py", "work = False\n", "code: work")
            StateStore(root).init_run(run_id="run-1")
            issue_file = "code-review-CR-0001.jsonl"
            write_existing_code_review_record(root, "CR-0001", sha)
            write_existing_range_issue(root, issue_file, sha)
            write_file(root / "src" / "work.py", "work = 'partial fix'\n")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "code-review", "CR-0001", "--fix-in-place"]
            )

            new_head = git_head(root)
            summary = read_code_review_summary(root)
            prompts = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (
                    root
                    / ".electroboy"
                    / "shared"
                    / "runs"
                    / "run-1"
                    / "messages"
                ).glob("*-prompt.md")
            )

        self.assertEqual(code, 0, stderr)
        self.assertNotEqual(new_head, sha)
        self.assertIn("resuming interrupted fix", stdout)
        self.assertIn("blocker/major findings: 1", stdout)
        self.assertIn("blocker/major findings: 0", stdout)
        self.assertIn("Status: verified", summary)
        self.assertIn("resuming after an interrupted previous fix", prompts)
        self.assertIn("src/work.py", prompts)

    def test_code_review_fix_in_place_resumes_in_progress_rebase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rebase_resume_runtime(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
            initialize_git_repo(root)
            sha = create_commit(root, "src/work.py", "work = False\n", "code: work")
            StateStore(root).init_run(run_id="run-1")
            issue_file = "code-review-CR-0001.jsonl"
            write_existing_code_review_record(root, "CR-0001", sha)
            write_existing_range_issue(root, issue_file, sha)
            subprocess.run(
                ["git", "-C", str(root), "checkout", "--detach", f"{sha}^"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            write_fake_rebase_state(root)
            write_file(root / "docs" / "requirements.md", "# Requirements\npartial\n")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "code-review", "CR-0001", "--fix-in-place"]
            )

            new_head = git_head(root)
            summary = read_code_review_summary(root)
            prompts = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (
                    root
                    / ".electroboy"
                    / "shared"
                    / "runs"
                    / "run-1"
                    / "messages"
                ).glob("*-prompt.md")
            )

        self.assertEqual(code, 0, stderr)
        self.assertNotEqual(new_head, sha)
        self.assertIn("resuming interrupted fix during in-progress rebase", stdout)
        self.assertIn("blocker/major findings: 0", stdout)
        self.assertIn("Status: verified", summary)
        self.assertIn("in-place rewrite/rebase", prompts)
        self.assertIn("progress: 20/41", prompts)
        self.assertIn("Continue the amend or rebase workflow until it succeeds", prompts)


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
    return git_revision(root, "HEAD")


def git_revision(root: Path, revision: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", revision],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def read_code_review_summary(root: Path, review_id: str = "CR-0001") -> str:
    return (root / "docs" / f"code-review-{review_id}.md").read_text(
        encoding="utf-8"
    )


def write_existing_code_review_record(
    root: Path,
    review_id: str,
    sha: str,
) -> None:
    record = {
        "schema_version": 1,
        "review_id": review_id,
        "target_type": "commit",
        "target_spec": sha,
        "start_sha": sha,
        "end_sha": sha,
        "base_sha": git_revision(root, f"{sha}^"),
        "commits": [sha],
        "mode_label": "single commit review",
        "commit_count": 1,
        "issue_file": f"code-review-{review_id}.jsonl",
        "summary_path": f"docs/code-review-{review_id}.md",
        "status": "blocking",
        "fix_mode": "review-only",
        "finding_count": 1,
        "blocker_major_count": 1,
        "minor_count": 0,
        "open_count": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    path = (
        root
        / ".electroboy"
        / "shared"
        / "runs"
        / "run-1"
        / "code-reviews.jsonl"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


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


def write_invalid_review_runtime(root: Path) -> None:
    write_file(
        root / "agent.py",
        """
from __future__ import annotations

import json

issues = [
    {
        "issue_id": "CODEBASE-001",
        "severity": "blocker",
        "status": "open",
        "summary": "",
    },
    {
        "issue_id": "CODEBASE-002",
        "severity": "major",
        "status": "open",
        "summary": "",
    },
]
print(json.dumps({
    "ok": True,
    "final_message": "Review completed; found 1 blocker and 1 major finding.",
    "issues": issues,
}))
""".lstrip(),
    )
    write_runtime_config(root)


def write_repairable_review_runtime(root: Path) -> None:
    write_file(
        root / "agent.py",
        """
from __future__ import annotations

import json
import sys

prompt = sys.stdin.read()
if "Repair structured review output." in prompt:
    print(json.dumps({
        "ok": True,
        "final_message": "Review completed; found 1 blocker and 1 major finding.",
        "issues": [
            {
                "issue_id": "CODEBASE-001",
                "severity": "blocker",
                "status": "open",
                "summary": "Missing admission validation.",
                "artifact": "src/one.py",
                "location": "src/one.py:1",
                "rationale": "Admissions must reject invalid requests.",
                "requested_change": "Add admission validation.",
            },
            {
                "issue_id": "CODEBASE-002",
                "severity": "major",
                "status": "open",
                "summary": "Scheduler state update is incomplete.",
                "artifact": "src/one.py",
                "location": "src/one.py:1",
                "rationale": "Scheduler state must remain consistent.",
                "requested_change": "Complete the scheduler state update.",
            },
        ],
    }))
else:
    print(json.dumps({
        "ok": True,
        "final_message": "Review completed; found 1 blocker and 1 major finding.",
        "issues": [
            {
                "issue_id": "CODEBASE-001",
                "severity": "blocker",
                "status": "open",
                "summary": "",
                "artifact": "src/one.py",
                "requested_change": "Add admission validation.",
            },
            {
                "issue_id": "CODEBASE-002",
                "severity": "major",
                "status": "open",
                "summary": "",
                "artifact": "src/one.py",
                "requested_change": "Complete the scheduler state update.",
            },
        ],
    }))
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


def write_fix_followup_runtime(root: Path) -> None:
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
if "Fix code-review findings as follow-up commits" in prompt:
    path = pathlib.Path("src/followup.py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("followup = True\\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/followup.py"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "code: follow-up fix"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print(json.dumps({"ok": True, "final_message": "fixed"}))
else:
    commits = re.findall(r"- ([0-9a-f]{12}) ([0-9a-f]{40}) ", prompt)
    commit = commits[0][1] if commits else ""
    fixed = pathlib.Path("src/followup.py").exists()
    issue = {
        "issue_id": "RCR-FOLLOWUP-001",
        "severity": "major",
        "status": "verified" if fixed else "open",
        "summary": "Commit needs a follow-up fix.",
        "commit": commit,
        "artifact": "src/work.py",
        "location": "src/work.py:1",
        "rationale": "The range should be fixed without rewriting it.",
        "requested_change": "Add a follow-up fix commit.",
    }
    print(json.dumps({"ok": True, "final_message": "reviewed", "issues": [issue]}))
""".lstrip(),
    )
    write_runtime_config(root)


def write_codebase_fix_followup_runtime(root: Path) -> None:
    write_file(
        root / "agent.py",
        """
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

prompt = sys.stdin.read()
if "Fix full-codebase code-review findings" in prompt:
    path = pathlib.Path("src/codebase_fix.py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("codebase_fix = True\\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/codebase_fix.py"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "code: codebase follow-up fix"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print(json.dumps({"ok": True, "final_message": "fixed"}))
else:
    fixed = pathlib.Path("src/codebase_fix.py").exists()
    issue = {
        "issue_id": "CODEBASE-001",
        "severity": "major",
        "status": "verified" if fixed else "open",
        "summary": "Codebase needs a follow-up fix.",
        "artifact": "src/work.py",
        "location": "src/work.py:1",
        "rationale": "The full codebase review should request a follow-up fix.",
        "requested_change": "Add a follow-up fix commit.",
    }
    print(json.dumps({"ok": True, "final_message": "reviewed", "issues": [issue]}))
""".lstrip(),
    )
    write_runtime_config(root)


def write_resume_dirty_fix_runtime(root: Path) -> None:
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
    if "resuming after an interrupted previous fix" not in prompt:
        raise SystemExit("missing interrupted-fix resume instruction")
    if "src/work.py" not in prompt:
        raise SystemExit("missing dirty path")
    path = pathlib.Path("src/work.py")
    path.write_text("work = True\\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/work.py"], check=True)
    subprocess.run(
        ["git", "commit", "--amend", "--no-edit"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print(json.dumps({"ok": True, "final_message": "resumed"}))
else:
    commits = re.findall(r"- ([0-9a-f]{12}) ([0-9a-f]{40}) ", prompt)
    commit = commits[-1][1] if commits else ""
    fixed = pathlib.Path("src/work.py").read_text(encoding="utf-8").strip()
    issue = {
        "issue_id": "RCR-RESUME-001",
        "severity": "major",
        "status": "verified" if fixed == "work = True" else "open",
        "summary": "Commit needs a resumed in-place fix.",
        "commit": commit,
        "artifact": "src/work.py",
        "location": "src/work.py:1",
        "rationale": "Interrupted dirty edits must be resumed.",
        "requested_change": "Resume the interrupted fix.",
    }
    print(json.dumps({"ok": True, "final_message": "reviewed", "issues": [issue]}))
""".lstrip(),
    )
    write_runtime_config(root)


def write_rebase_resume_runtime(root: Path) -> None:
    write_file(
        root / "agent.py",
        """
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys

prompt = sys.stdin.read()
if "Fix code-review findings in place" in prompt:
    if "in-place rewrite/rebase" not in prompt:
        raise SystemExit("missing in-progress rebase instruction")
    if "Continue the amend or rebase workflow until it succeeds" not in prompt:
        raise SystemExit("missing conflict continuation instruction")
    shutil.rmtree(pathlib.Path(".git") / "rebase-merge")
    subprocess.run(["git", "checkout", "--", "docs/requirements.md"], check=True)
    path = pathlib.Path("src/work.py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("work = True\\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/work.py"], check=True)
    subprocess.run(
        ["git", "commit", "-m", "code: resumed rebase fix"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print(json.dumps({"ok": True, "final_message": "resumed rebase"}))
else:
    commits = re.findall(r"- ([0-9a-f]{12}) ([0-9a-f]{40}) ", prompt)
    commit = commits[-1][1] if commits else ""
    fixed = pathlib.Path("src/work.py").read_text(encoding="utf-8").strip()
    issue = {
        "issue_id": "RCR-RESUME-001",
        "severity": "major",
        "status": "verified" if fixed == "work = True" else "open",
        "summary": "Commit needs a resumed in-place fix.",
        "commit": commit,
        "artifact": "src/work.py",
        "location": "src/work.py:1",
        "rationale": "Interrupted rebase must be completed.",
        "requested_change": "Resume the interrupted rebase.",
    }
    print(json.dumps({"ok": True, "final_message": "reviewed", "issues": [issue]}))
""".lstrip(),
    )
    write_runtime_config(root)


def write_existing_range_issue(root: Path, issue_file: str, commit: str) -> None:
    path = root / ".electroboy" / "shared" / "runs" / "run-1" / issue_file
    path.parent.mkdir(parents=True, exist_ok=True)
    issue = {
        "issue_id": "RCR-RESUME-001",
        "severity": "major",
        "status": "open",
        "summary": "Commit needs a resumed in-place fix.",
        "commit": commit,
        "artifact": "src/work.py",
        "location": "src/work.py:1",
        "rationale": "Interrupted dirty edits must be resumed.",
        "requested_change": "Resume the interrupted fix.",
    }
    path.write_text(json.dumps(issue) + "\n", encoding="utf-8")


def write_fake_rebase_state(root: Path) -> None:
    rebase_dir = root / ".git" / "rebase-merge"
    rebase_dir.mkdir(parents=True, exist_ok=True)
    write_file(rebase_dir / "msgnum", "20\n")
    write_file(rebase_dir / "end", "41\n")
    write_file(
        rebase_dir / "stopped-sha",
        "814298cc4b859e6538349d9146edd35130655bcf\n",
    )
    write_file(rebase_dir / "head-name", "refs/heads/adm-sched-v01\n")


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
""".lstrip(),
    )


if __name__ == "__main__":
    unittest.main()
