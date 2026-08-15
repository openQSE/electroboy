from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.modules.review_service import review_report_index  # noqa: E402
from electroboy.service.http import JsonResponse  # noqa: E402
from electroboy.service.progress_events import progress_issue_events  # noqa: E402
from electroboy.service.registry import build_module_registry  # noqa: E402
from electroboy.state_store import StateStore  # noqa: E402


class ServiceCapabilityTests(unittest.TestCase):
    def test_registered_handlers_return_typed_responses(self) -> None:
        source_paths = [ROOT / "src/electroboy/service/core_module.py"]
        source_paths.extend((ROOT / "src/electroboy/modules").glob("*.py"))
        source_paths.extend(
            (ROOT / "src/electroboy/workflows").glob("*/routes.py")
        )

        for path in source_paths:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("request.send_json", source, path.as_posix())
            self.assertNotIn("request.send_text", source, path.as_posix())
            self.assertNotIn("request.send_download", source, path.as_posix())
            self.assertNotIn(
                "request.send_binary_download",
                source,
                path.as_posix(),
            )

        health = build_module_registry().get("core").handlers["health"]
        request = type(
            "Request",
            (),
            {
                "operations": type(
                    "Operations",
                    (),
                    {"health_payload": lambda self: {"status": "ok"}},
                )()
            },
        )()
        response = health(request)
        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.payload, {"status": "ok"})

    def test_review_index_includes_jsonl_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = StateStore(root)
            manifest = store.init_run(run_id="run-1")
            docs = root / "docs" / "reviews"
            docs.mkdir(parents=True)
            report = docs / "code-review-CR-0001.md"
            report.write_text("# Code Review\n", encoding="utf-8")
            run_dir = store.run_dir(manifest.run_id)
            (run_dir / "code-reviews.jsonl").write_text(
                json.dumps(
                    {
                        "review_id": "CR-0001",
                        "issue_file": "code-review-CR-0001.jsonl",
                        "summary_path": "docs/reviews/code-review-CR-0001.md",
                        "status": "complete",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "code-review-CR-0001.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "issue_id": "ISSUE-1",
                                "severity": "major",
                                "status": "open",
                            }
                        ),
                        json.dumps(
                            {
                                "issue_id": "ISSUE-2",
                                "severity": "minor",
                                "status": "resolved",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = review_report_index(root)

        review = payload["reviews"][0]
        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(review["id"], "CR-0001")
        self.assertEqual(review["category"], "code")
        self.assertEqual(review["finding_count"], 2)
        self.assertEqual(review["open_count"], 1)
        self.assertEqual(review["severity_counts"], {"major": 1, "minor": 1})
        self.assertEqual(
            review["metadata_path"],
            ".electroboy/shared/runs/run-1/code-review-CR-0001.jsonl",
        )

    def test_progress_issue_lines_become_structured_events(self) -> None:
        events = progress_issue_events(
            "working\nISSUE FOUND - MAJOR - Missing validation\n"
            "ISSUE FOUND - minor - Improve naming\n"
        )

        self.assertEqual(
            events,
            [
                {
                    "type": "issue",
                    "severity": "major",
                    "summary": "Missing validation",
                },
                {
                    "type": "issue",
                    "severity": "minor",
                    "summary": "Improve naming",
                },
            ],
        )

    def test_structured_documents_register_implementation_log(self) -> None:
        module = build_module_registry().get("structured_documents")

        self.assertIn(
            "/artifacts/implementation-log",
            {route.path for route in module.routes},
        )


if __name__ == "__main__":
    unittest.main()
