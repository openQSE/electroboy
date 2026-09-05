"""Progress and heartbeat primitives for blocking Code Learner AI work."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager

ProgressCallback = Callable[[dict[str, object]], None]
_ACTIVITY_TEXT_LIMIT = 800


class AgentActivityReporter:
    """Project raw runtime events into bounded learner progress details."""

    def __init__(
        self,
        callback: ProgressCallback,
        *,
        phase: str,
        percent: int,
        scope_ids: list[str] | None = None,
    ) -> None:
        self.callback = callback
        self.phase = phase
        self.percent = percent
        self.scope_ids = list(scope_ids or [])
        self._last_message = ""

    def __call__(self, raw_event: dict[str, object]) -> None:
        activity = _runtime_activity(raw_event)
        if activity is None:
            return
        kind, message = activity
        if message == self._last_message:
            return
        self._last_message = message
        self.callback(
            {
                "record_type": "activity",
                "activity": True,
                "activity_kind": kind,
                "phase": self.phase,
                "percent": self.percent,
                "scope_ids": list(self.scope_ids),
                "message": message,
            }
        )


def _runtime_activity(raw_event: dict[str, object]) -> tuple[str, str] | None:
    stream = str(raw_event.get("stream") or "stdout")
    event = raw_event.get("event")
    if not isinstance(event, Mapping):
        text = _bounded_activity_text(raw_event.get("text"))
        if not text:
            return None
        return ("runtime", f"AI {stream}: {text}")

    event_type = str(event.get("type") or "")
    if event_type == "turn.started":
        return ("turn", "AI turn started.")
    if event_type == "turn.completed":
        return ("turn", "AI turn completed; validating structured output.")
    if event_type in {"error", "turn.failed"}:
        detail = _bounded_activity_text(event.get("message") or event.get("error"))
        return ("error", f"AI runtime error: {detail or event_type}")

    item = event.get("item")
    if not isinstance(item, Mapping):
        return None
    item_type = str(item.get("type") or "")
    if item_type == "reasoning":
        text = _bounded_activity_text(item.get("text") or item.get("summary"))
        return ("reasoning", f"AI reasoning: {text}") if text else None
    if item_type == "command_execution":
        return _command_activity(event_type, item)
    if item_type in {"mcp_tool_call", "tool_call"}:
        name = _bounded_activity_text(
            item.get("name") or item.get("tool") or item.get("server")
        )
        return ("tool", f"AI tool call: {name or 'repository tool'}")
    if item_type == "web_search":
        query = _bounded_activity_text(item.get("query"))
        return ("search", f"AI search: {query or 'repository context'}")
    if item_type == "agent_message":
        text = str(item.get("text") or "")
        if text:
            return (
                "response",
                f"AI returned structured output ({len(text):,} characters).",
            )
    return None


def _command_activity(
    event_type: str,
    item: Mapping[str, object],
) -> tuple[str, str]:
    command = _bounded_activity_text(item.get("command"), limit=500) or "command"
    if event_type == "item.started":
        return ("command", f"AI command started: {command}")
    exit_code = item.get("exit_code")
    status = f"exit {exit_code}" if exit_code is not None else str(
        item.get("status") or "completed"
    )
    output = _bounded_activity_text(item.get("aggregated_output"))
    suffix = f"\n{output}" if output else ""
    return ("command", f"AI command {status}: {command}{suffix}")


def _bounded_activity_text(
    value: object,
    *,
    limit: int = _ACTIVITY_TEXT_LIMIT,
) -> str:
    text = str(value or "").replace("\r", "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


class InvocationHeartbeat(AbstractContextManager["InvocationHeartbeat"]):
    """Emit bounded status while an AI runtime is waiting on its final reply."""

    def __init__(
        self,
        callback: ProgressCallback | None,
        event: Mapping[str, object],
        *,
        interval: float = 5.0,
    ) -> None:
        self.callback = callback
        self.event = dict(event)
        self.interval = max(0.01, interval)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> InvocationHeartbeat:
        if self.callback is None:
            return self
        self._thread = threading.Thread(
            target=self._run,
            name="code-learner-progress-heartbeat",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 0.5)
        return None

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            if self.callback is not None:
                self.callback({**self.event, "heartbeat": True})
