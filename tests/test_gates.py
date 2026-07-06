from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.gates import GateEngine  # noqa: E402
from electroboy.models import (  # noqa: E402
    GATE_CODE_REVIEW,
    GATE_COMMIT,
    GATE_IMPLEMENTATION,
    GATE_PLAN_CURRENCY,
    PhaseStatus,
    ReviewIssue,
)
from electroboy.state_store import StateStore  # noqa: E402


class GateTests(unittest.TestCase):
    def test_open_change_request_blocks_stage_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            manifest = store.init_run(run_id="run-1")
            store.append_change_request(
                {
                    "id": "CR-1",
                    "status": "open",
                    "baseline": "requirements",
                }
            )

            result = GateEngine(tmp).stage_order("requirements", manifest)

        self.assertFalse(result.passed)
        self.assertIn("open change-control request", result.messages[0])

    def test_plan_currency_blocks_active_phase_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.init_run(run_id="run-1")
            status = PhaseStatus(
                active_phase=1,
                phases={"1": {"plan_current": False}},
            )
            store.save_phase_status(status)

            result = GateEngine(tmp).evaluate(
                GATE_PLAN_CURRENCY,
                store.load_current_manifest(),
            )

        self.assertFalse(result.passed)
        self.assertEqual(result.messages, ["active phase has plan drift"])

    def test_code_review_blocks_on_open_major_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.init_run(run_id="run-1")
            store.save_phase_status(
                PhaseStatus(
                    active_phase=2,
                    phases={
                        "2": {
                            "code_review": "passed",
                            "code_review_event": "agent-00001",
                        }
                    },
                )
            )
            store.append_review_issue(
                "phase-2-code-review.jsonl",
                ReviewIssue(
                    issue_id="CODE-1",
                    source="code-review-agent",
                    severity="major",
                    status="open",
                    summary="Missing validation.",
                    phase=2,
                ),
            )

            result = GateEngine(tmp).evaluate(
                GATE_CODE_REVIEW,
                store.load_current_manifest(),
            )

        self.assertFalse(result.passed)
        self.assertIn("blocking review issues remain", result.messages[0])

    def test_code_review_requires_agent_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.init_run(run_id="run-1")
            store.save_phase_status(
                PhaseStatus(
                    active_phase=2,
                    phases={"2": {"code_review": "passed"}},
                )
            )

            result = GateEngine(tmp).evaluate(
                GATE_CODE_REVIEW,
                store.load_current_manifest(),
            )

        self.assertFalse(result.passed)
        self.assertIn("code review agent evidence is missing", result.messages[0])

    def test_commit_gate_passes_with_phase_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            manifest = store.init_run(run_id="run-1")
            manifest.complete_gate(GATE_IMPLEMENTATION)
            store.save_manifest(manifest)
            store.save_phase_status(
                PhaseStatus(
                    active_phase=1,
                    phases={
                        "1": {
                            "plan_current": True,
                            "code_review": "passed",
                            "code_review_event": "agent-00001",
                            "test_review": "passed",
                            "test_review_event": "agent-00002",
                        }
                    },
                )
            )

            result = GateEngine(tmp).evaluate(
                GATE_COMMIT,
                store.load_current_manifest(),
            )

        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
