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


class ReportingTests(unittest.TestCase):
    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_resume_reports_open_change_control_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(
                self.run_cli(["--root", str(root), "init", "--run-id", "run-1"])[0],
                0,
            )
            self.assertEqual(
                self.run_cli(
                    [
                        "--root",
                        str(root),
                        "change",
                        "open",
                        "--baseline",
                        "design",
                        "--reason",
                        "Need a design correction.",
                    ]
                )[0],
                0,
            )

            code, stdout, stderr = self.run_cli(["--root", str(root), "resume"])

            self.assertEqual(code, 0, stderr)
            self.assertIn("resume stage: requirements", stdout)
            self.assertIn("open change requests: 1", stdout)
            self.assertIn("change-control", stdout)

    def test_report_summary_and_trace_can_be_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(
                self.run_cli(["--root", str(root), "init", "--run-id", "run-1"])[0],
                0,
            )

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
