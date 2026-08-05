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
from electroboy.models import (  # noqa: E402
    ChangeRequest,
    PhaseStatus,
    ReviewIssue,
    STAGE_IMPLEMENTATION,
)
from electroboy.state_store import StateStore  # noqa: E402


class ReportingTests(unittest.TestCase):
    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_status_reports_open_change_control_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = StateStore(root)
            store.init_run(run_id="run-1")
            store.append_change_request(
                ChangeRequest(
                    request_id="CR-0001",
                    run_id="run-1",
                    baseline="design",
                    reason="Need a design correction.",
                    status="open",
                    event="opened",
                )
            )

            code, stdout, stderr = self.run_cli(["--root", str(root), "status"])

            self.assertEqual(code, 0, stderr)
            self.assertIn("active stage: requirements", stdout)
            self.assertIn("open change requests: 1", stdout)
            self.assertIn("change-control", stdout)

    def test_status_counts_only_active_workflow_review_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = StateStore(root)
            manifest = store.init_run(run_id="run-1")
            manifest.set_active_stage(STAGE_IMPLEMENTATION)
            store.save_manifest(manifest)
            store.save_phase_status(
                PhaseStatus(
                    active_phase=2,
                    phases={
                        "1": {"status": "operator-skipped"},
                        "2": {"status": "active"},
                    },
                )
            )
            for file_name, issue_id in [
                ("design-review.jsonl", "DR-001"),
                ("phase-1-code-review.jsonl", "PH1-001"),
                ("range-code-review-a-b.jsonl", "RCR-001"),
                ("code-review-CR-0001.jsonl", "CODEBASE-001"),
            ]:
                store.append_review_issue(
                    file_name,
                    ReviewIssue(
                        issue_id=issue_id,
                        source="agent",
                        severity="major",
                        status="open",
                        summary="Historical review issue.",
                    ),
                )

            code, stdout, stderr = self.run_cli(["--root", str(root), "status"])

            store.append_review_issue(
                "phase-2-code-review.jsonl",
                ReviewIssue(
                    issue_id="PH2-001",
                    source="agent",
                    severity="major",
                    status="open",
                    summary="Active phase review issue.",
                ),
            )
            active_code, active_stdout, active_stderr = self.run_cli(
                ["--root", str(root), "status"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("open review issues: 0", stdout)
        self.assertEqual(active_code, 0, active_stderr)
        self.assertIn("open review issues: 1", active_stdout)

    def test_report_summary_and_trace_can_be_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            StateStore(root).init_run(run_id="run-1")

            summary_code, _summary_stdout, summary_stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "report",
                    "summary",
                    "--output",
                    "reports/summary.md",
                ]
            )
            trace_code, _trace_stdout, trace_stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "report",
                    "trace",
                    "--output",
                    "reports/trace.md",
                ]
            )

            summary = (root / "reports" / "summary.md").read_text(
                encoding="utf-8"
            )
            trace = (root / "reports" / "trace.md").read_text(encoding="utf-8")

            self.assertEqual(summary_code, 0, summary_stderr)
            self.assertEqual(trace_code, 0, trace_stderr)
            self.assertIn("Run ID: run-1", summary)
            self.assertIn("Activity events: 1", summary)
            self.assertIn("run-created", trace)


if __name__ == "__main__":
    unittest.main()
