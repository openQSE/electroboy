from __future__ import annotations

from electroboy.workflows.code_learner.progress import AgentActivityReporter


def _event(item_type: str, text: str) -> dict[str, object]:
    return {
        "event": {
            "type": "item.completed",
            "item": {"type": item_type, "text": text},
        }
    }


def test_progress_keeps_specific_messages_and_deduplicates_consecutive() -> None:
    events: list[dict[str, object]] = []
    reporter = AgentActivityReporter(events.append, phase="components", percent=10)

    reporter(_event("reasoning", "Inspecting src/runtime.py dispatch behavior."))
    reporter(_event("reasoning", "Inspecting src/runtime.py dispatch behavior."))
    reporter(_event("reasoning", "Still working on the repository."))
    reporter(_event("agent_message", "Recording the scheduler component boundary."))

    assert [event["message"] for event in events] == [
        "Inspecting src/runtime.py dispatch behavior.",
        "Recording the scheduler component boundary.",
    ]


def test_progress_preserves_runtime_errors() -> None:
    events: list[dict[str, object]] = []
    reporter = AgentActivityReporter(events.append, phase="module_course", percent=100)

    reporter({"event": {"type": "error", "message": "provider disconnected"}})

    assert events[0]["activity_kind"] == "error"
    assert events[0]["message"] == "AI runtime error: provider disconnected"
