from __future__ import annotations

import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from electroboy.adapters.base import AgentInvocation, AgentResult
from electroboy.modules.corkboard_generation import (
    CorkboardGenerationManager,
    generation_passes,
    normalize_generation_plan,
)
from electroboy.modules.creative_workspace import (
    create_generated_creative_corkboard,
    save_creative_corkboard,
)
from electroboy.service.services import ServiceServices
from electroboy.state_store import StateError


class FakeContexts:
    def __init__(self, root: Path, workflow_id: str = "creative-writing") -> None:
        self.root = root
        self.context = SimpleNamespace(workflow_id=workflow_id)

    def require(self, context_id: str) -> object:
        if context_id != "context-1":
            raise StateError("context not found")
        return self.context

    def active_project_root(self, context_id: str) -> Path:
        self.require(context_id)
        return self.root


class FakeRuntime:
    def __init__(
        self,
        payload: dict[str, object],
        delay: float = 0.0,
        activities: list[str] | None = None,
    ) -> None:
        self.payload = payload
        self.delay = delay
        self.activities = activities or []
        self.invocation: AgentInvocation | None = None

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        self.invocation = invocation
        for activity in self.activities:
            if invocation.activity_callback:
                invocation.activity_callback(activity)
        if self.delay:
            time.sleep(self.delay)
        return AgentResult(
            ok=True,
            final_message="",
            structured_output=True,
            structured_payload=self.payload,
        )


class FakeProvider:
    provider_id = "creative-files"

    def __init__(self) -> None:
        self.generated: dict[str, object] | None = None

    def list_boards(
        self,
        context_id: str,
        *,
        connection_id: str = "",
    ) -> list[dict[str, object]]:
        return []

    def create_generated_board(
        self,
        context_id: str,
        board_id: str,
        *,
        title: str,
        cards: list[dict[str, object]],
        connectors: list[dict[str, object]],
        connection_id: str = "",
    ) -> dict[str, object]:
        self.generated = {
            "context_id": context_id,
            "board_id": board_id,
            "title": title,
            "cards": cards,
            "connectors": connectors,
        }
        return {
            "status": "created",
            "board_id": board_id,
            "provider": self.provider_id,
            "title": title,
        }


class CorkboardGenerationTests(unittest.TestCase):
    def test_passes_are_workflow_specific(self) -> None:
        creative = generation_passes("creative-writing")
        software = generation_passes("software")

        self.assertEqual(
            [item["id"] for item in creative],
            ["story-scenes", "characters", "events-timeline"],
        )
        self.assertEqual(
            [item["id"] for item in software],
            [
                "architecture-components",
                "dependencies-data-flow",
                "requirements-tasks",
            ],
        )

    def test_plan_layout_is_left_to_right_and_preserves_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "chapter.md").write_text("# Chapter\n", encoding="utf-8")
            cards, connectors = normalize_generation_plan(
                root,
                {
                    "cards": [
                        {
                            "id": "effect",
                            "title": "Effect",
                            "role": "event",
                            "sequence": 2,
                            "lane": "timeline",
                            "source_path": "chapter.md",
                        },
                        {
                            "id": "cause",
                            "title": "Cause",
                            "role": "storyline",
                            "sequence": 1,
                            "lane": "main",
                            "source_path": "chapter.md",
                        },
                    ],
                    "connectors": [
                        {
                            "source": "cause",
                            "target": "effect",
                            "relation": "causes",
                        }
                    ],
                },
            )

        self.assertEqual([card["id"] for card in cards], ["cause", "effect"])
        self.assertEqual(
            [card["title"] for card in cards],
            ["1. Cause", "2. Effect"],
        )
        self.assertEqual(
            [card["metadata"]["sequence"] for card in cards],
            [1, 2],
        )
        self.assertLess(cards[0]["x"], cards[1]["x"])
        self.assertEqual(cards[0]["y"], cards[1]["y"])
        self.assertNotIn("width", cards[0])
        self.assertNotIn("height", cards[0])
        self.assertNotIn("rotation", cards[0])
        self.assertEqual(cards[0]["color"], "sky")
        self.assertEqual(cards[1]["color"], "peach")
        self.assertEqual(cards[0]["path"], "chapter.md")
        self.assertEqual(connectors[0]["source"]["side"], "right")
        self.assertEqual(connectors[0]["target"]["side"], "left")

    def test_file_generation_runs_non_interactively_and_applies_atomically(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "chapter.md"
            source.write_text("# Arrival\nThe alarm sounds.\n", encoding="utf-8")
            runtime = FakeRuntime(
                {
                    "cards": [
                        {
                            "id": "arrival",
                            "title": "Arrival",
                            "note": "The protagonist arrives.",
                            "role": "scene",
                            "sequence": 1,
                        },
                        {
                            "id": "alarm",
                            "title": "Alarm",
                            "note": "The arrival triggers the alarm.",
                            "role": "event",
                            "sequence": 2,
                        },
                    ],
                    "connectors": [
                        {
                            "source": "arrival",
                            "target": "alarm",
                            "relation": "causes",
                        }
                    ],
                }
            )
            manager = CorkboardGenerationManager(
                runtime_factory=lambda role, project_root: runtime
            )
            contexts = FakeContexts(root)
            dependency = object()
            services = ServiceServices(
                contexts=contexts,
                workspaces=dependency,
                sessions=dependency,
                files=dependency,
                workflows=dependency,
            )
            provider = FakeProvider()

            started = manager.start(
                services,
                provider,
                "context-1",
                {
                    "scope": {"type": "file", "path": "chapter.md"},
                    "pass": "story-scenes",
                },
            )
            deadline = time.monotonic() + 2
            status = manager.get("context-1", str(started["job_id"]))
            while status["status"] in {"queued", "running"}:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
                status = manager.get("context-1", str(started["job_id"]))

        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["result"]["card_count"], 2)
        self.assertEqual(runtime.invocation.role, "corkboard_generation")
        self.assertIn("do not modify any file", runtime.invocation.prompt)
        self.assertEqual(runtime.invocation.context_paths, [str(source)])
        self.assertIsNotNone(provider.generated)
        self.assertEqual(provider.generated["cards"][0]["title"], "1. Arrival")
        self.assertEqual(provider.generated["cards"][0]["path"], "chapter.md")
        self.assertEqual(len(provider.generated["connectors"]), 1)

    def test_generation_rejects_sources_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            root.mkdir()
            outside = Path(temporary) / "outside.md"
            outside.write_text("outside", encoding="utf-8")

            with self.assertRaisesRegex(StateError, "inside the active project"):
                normalize_generation_plan(
                    root,
                    {
                        "cards": [
                            {
                                "id": "outside",
                                "title": "Outside",
                                "source_path": str(outside),
                            }
                        ]
                    },
                )

    def test_project_generation_uses_safe_project_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "story.md").write_text("# Story\n", encoding="utf-8")
            internal = root / ".electroboy"
            internal.mkdir()
            (internal / "private.md").write_text("private", encoding="utf-8")
            runtime = FakeRuntime(
                {
                    "cards": [
                        {
                            "id": "protagonist",
                            "title": "Protagonist",
                            "role": "character",
                            "source_path": "story.md",
                        }
                    ]
                }
            )
            manager = CorkboardGenerationManager(
                runtime_factory=lambda role, project_root: runtime
            )
            dependency = object()
            services = ServiceServices(
                contexts=FakeContexts(root),
                workspaces=dependency,
                sessions=dependency,
                files=dependency,
                workflows=dependency,
            )
            provider = FakeProvider()
            started = manager.start(
                services,
                provider,
                "context-1",
                {"scope": {"type": "project"}, "pass": "characters"},
            )
            deadline = time.monotonic() + 2
            status = manager.get("context-1", str(started["job_id"]))
            while status["status"] in {"queued", "running"}:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
                status = manager.get("context-1", str(started["job_id"]))

        self.assertEqual(status["status"], "complete")
        self.assertIn("- story.md", runtime.invocation.prompt)
        self.assertNotIn("private.md", runtime.invocation.prompt)

    def test_generation_streams_distinct_ai_activity_without_heartbeats(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "story.md").write_text("# Story\n", encoding="utf-8")
            runtime = FakeRuntime(
                {"cards": [{"id": "opening", "title": "Opening"}]},
                delay=0.07,
                activities=[
                    "Reading the opening scene.",
                    "Reading the opening scene.",
                    "Mapping the scene's causal turn.",
                ],
            )
            manager = CorkboardGenerationManager(
                runtime_factory=lambda role, project_root: runtime,
                activity_interval=0.02,
            )
            dependency = object()
            services = ServiceServices(
                contexts=FakeContexts(root),
                workspaces=dependency,
                sessions=dependency,
                files=dependency,
                workflows=dependency,
            )
            started = manager.start(
                services,
                FakeProvider(),
                "context-1",
                {"scope": {"type": "project"}, "pass": "story-scenes"},
            )
            deadline = time.monotonic() + 2
            status = manager.get("context-1", str(started["job_id"]))
            while status["status"] in {"queued", "running"}:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
                status = manager.get("context-1", str(started["job_id"]))

        activities = status["activities"]
        self.assertEqual(
            [
                entry["text"]
                for entry in activities
                if entry.get("type") == "agent"
            ],
            ["Reading the opening scene.", "Mapping the scene's causal turn."],
        )
        self.assertFalse(
            any("seconds elapsed" in entry["text"] for entry in activities)
        )
        self.assertTrue(any("Validating" in entry["text"] for entry in activities))
        self.assertTrue(any("Laying out" in entry["text"] for entry in activities))
        self.assertTrue(any("Created 1 card" in entry["text"] for entry in activities))
        self.assertEqual(manager.latest("context-1")["job_id"], started["job_id"])

    def test_generated_board_write_is_atomic_and_does_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = create_generated_creative_corkboard(
                root,
                "corkboard/story.corkboard.json",
                title="Story",
                cards=[
                    {
                        "id": "opening",
                        "title": "Opening",
                        "note": "Begin here.",
                        "x": 60,
                        "y": 60,
                        "width": 340,
                        "height": 220,
                        "color": "storyline",
                        "metadata": {
                            "role": "storyline",
                            "lane": "main",
                        },
                    }
                ],
                connectors=[],
            )
            document = (root / path).read_text(encoding="utf-8")

            with self.assertRaisesRegex(StateError, "already exists"):
                create_generated_creative_corkboard(
                    root,
                    path,
                    title="Replacement",
                    cards=[],
                    connectors=[],
                )

        self.assertIn('"title": "Story"', document)
        self.assertIn('"role": "storyline"', document)
        self.assertNotIn('"width"', document)
        self.assertNotIn('"height"', document)

    def test_generated_board_survives_concurrent_card_updates_and_batch_layout(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            board_path = create_generated_creative_corkboard(
                root,
                "corkboard/story.corkboard.json",
                title="Story",
                cards=[
                    {
                        "id": f"scene-{index}",
                        "title": f"Scene {index}",
                        "x": index * 40,
                        "y": 40,
                    }
                    for index in range(48)
                ],
                connectors=[],
            )

            def update_card(index: int) -> dict[str, object]:
                return save_creative_corkboard(
                    root,
                    {
                        "board_type": "freeform",
                        "corkboard": board_path,
                        "card": {
                            "id": f"scene-{index}",
                            "x": 1000 + index,
                            "y": 2000 + index,
                        },
                    },
                )

            with ThreadPoolExecutor(max_workers=16) as executor:
                list(executor.map(update_card, range(48)))

            batch = save_creative_corkboard(
                root,
                {
                    "board_type": "freeform",
                    "action": "positions",
                    "corkboard": board_path,
                    "positions": [
                        {"id": f"scene-{index}", "x": index * 90, "y": 720}
                        for index in range(48)
                    ],
                },
            )
            document = json.loads((root / board_path).read_text(encoding="utf-8"))

        self.assertEqual(len(batch["positions"]), 48)
        self.assertEqual(len(document["cards"]), 48)
        self.assertEqual(
            [(card["x"], card["y"]) for card in document["cards"]],
            [(index * 90, 720) for index in range(48)],
        )

    def test_invalid_board_is_never_replaced_with_an_empty_document(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            board = root / "corkboard" / "broken.corkboard.json"
            board.parent.mkdir(parents=True)
            original = '{"cards": ['
            board.write_text(original, encoding="utf-8")

            with self.assertRaisesRegex(StateError, "invalid JSON"):
                save_creative_corkboard(
                    root,
                    {
                        "board_type": "freeform",
                        "corkboard": "corkboard/broken.corkboard.json",
                        "card": {"id": "new-card", "title": "New card"},
                    },
                )

            unchanged = board.read_text(encoding="utf-8")

        self.assertEqual(unchanged, original)


if __name__ == "__main__":
    unittest.main()
