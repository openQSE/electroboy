from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.models import DecisionRecord, PhaseStatus, ReviewIssue  # noqa: E402
from electroboy.state_store import StateStore  # noqa: E402


class StateStoreTests(unittest.TestCase):
    def test_review_issue_jsonl_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.init_run(run_id="run-1")
            issue = ReviewIssue(
                issue_id="DES-1",
                source="design-review-agent",
                severity="major",
                status="open",
                summary="Missing workflow.",
            )

            store.append_review_issue("design-review.jsonl", issue)
            issues = store.read_review_issues("design-review.jsonl")

        self.assertEqual(issues[0]["issue_id"], "DES-1")
        self.assertEqual(issues[0]["severity"], "major")

    def test_phase_status_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            status = PhaseStatus(active_phase=2, phases={"2": {"status": "active"}})

            store.save_phase_status(status)
            loaded = store.load_phase_status()

        self.assertEqual(loaded.active_phase, 2)
        self.assertEqual(loaded.phases["2"]["status"], "active")

    def test_decisions_and_messages_redact_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(tmp)
            store.init_run(run_id="run-1")
            decision = DecisionRecord(
                decision_id="DEC-1",
                stage="requirements",
                summary="Use token",
                rationale="No secret in rationale",
            )

            store.append_decision(decision)
            path = store.write_message("EVT-1", "OPENAI_API_KEY=abc123")
            raw = {"OPENAI_API_KEY": "abc123", "safe": "value"}
            raw_path = store.write_raw_event("EVT-2", raw)

            decisions = store.read_decisions()
            message = path.read_text(encoding="utf-8")
            raw_text = raw_path.read_text(encoding="utf-8")
            decisions_path = (
                Path(tmp) / ".electroboy" / "shared" / "decisions.jsonl"
            )

            self.assertTrue(decisions_path.exists())
            self.assertIn(".electroboy/local/raw/run-1", str(raw_path.parent))

        self.assertEqual(decisions[0]["decision_id"], "DEC-1")
        self.assertIn("OPENAI_API_KEY=<redacted>", message)
        self.assertIn('"OPENAI_API_KEY": "<redacted>"', raw_text)


if __name__ == "__main__":
    unittest.main()
