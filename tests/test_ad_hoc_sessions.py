from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from electroboy.workflows.software.ad_hoc import (
    ad_hoc_session_history,
    start_ad_hoc_session_tracking,
)


SESSION_ID = "019f3cb6-60c3-7320-896b-e5eb9a6a8dd2"
UNINDEXED_SESSION_ID = "019f3cb6-60c3-7320-896b-e5eb9a6a8dd1"


def write_session(path: Path, session_id: str, project_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "session_id": session_id,
                            "timestamp": "2026-08-19T12:00:00+00:00",
                            "cwd": str(project_root),
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": (
                                        "You are an ad-hoc agent for this code "
                                        "base.\nWait for the operator."
                                    ),
                                }
                            ],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )


class AdHocSessionCatalogTests(unittest.TestCase):
    def test_history_reads_only_indexed_session_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service_root = root / "service"
            project_root = root / "project"
            codex_home = root / "codex"
            project_root.mkdir()
            session_path = codex_home / "sessions" / f"rollout-{SESSION_ID}.jsonl"
            unindexed_path = (
                codex_home
                / "sessions"
                / f"rollout-{UNINDEXED_SESSION_ID}.jsonl"
            )
            write_session(session_path, SESSION_ID, project_root)
            write_session(unindexed_path, UNINDEXED_SESSION_ID, project_root)
            catalog_path = (
                service_root / ".electroboy" / "service" / "ad-hoc-sessions.json"
            )
            catalog_path.parent.mkdir(parents=True)
            catalog_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "sessions": [
                            {
                                "provider": "codex",
                                "provider_session_id": SESSION_ID,
                                "project_root": str(project_root),
                                "session_path": str(session_path),
                                "title": "Indexed session",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}),
                mock.patch(
                    "electroboy.workflows.software.ad_hoc.codex_session_by_id",
                    side_effect=AssertionError("history search is not allowed"),
                ),
            ):
                history = ad_hoc_session_history(service_root, project_root)

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["provider_session_id"], SESSION_ID)
        self.assertEqual(history[0]["title"], "Indexed session")
        self.assertNotIn("session_path", history[0])

    def test_new_session_tracker_indexes_only_post_launch_rollout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service_root = root / "service"
            project_root = root / "project"
            codex_home = root / "codex"
            project_root.mkdir()
            session_path = codex_home / "sessions" / f"rollout-{SESSION_ID}.jsonl"
            write_session(session_path, SESSION_ID, project_root)

            with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                tracker = start_ad_hoc_session_tracking(
                    service_root,
                    project_root,
                    "electroboy-session",
                    frozenset(),
                    lambda: False,
                )
                tracker.join(timeout=2)

            catalog = json.loads(
                (
                    service_root
                    / ".electroboy"
                    / "service"
                    / "ad-hoc-sessions.json"
                ).read_text(encoding="utf-8")
            )

        self.assertFalse(tracker.is_alive())
        self.assertEqual(catalog["schema_version"], 2)
        self.assertEqual(catalog["sessions"][0]["provider_session_id"], SESSION_ID)
        self.assertEqual(
            catalog["sessions"][0]["electroboy_session_id"],
            "electroboy-session",
        )


if __name__ == "__main__":
    unittest.main()
