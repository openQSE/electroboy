"""Progress and heartbeat primitives for blocking Code Learner AI work."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager

ProgressCallback = Callable[[dict[str, object]], None]
_ACTIVITY_TEXT_LIMIT = 200
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


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
    event = raw_event.get("event")
    if not isinstance(event, Mapping):
        return None

    event_type = str(event.get("type") or "")
    if event_type == "turn.started":
        return ("turn", "AI turn started.")
    if event_type == "turn.completed":
        return ("turn", "AI turn completed; validating structured output.")
    if event_type in {"error", "turn.failed"}:
        detail = sanitize_progress_message(
            event.get("message") or event.get("error")
        )
        return ("error", f"AI runtime error: {detail or event_type}")

    item = event.get("item")
    if not isinstance(item, Mapping):
        return None
    item_type = str(item.get("type") or "")
    if item_type == "reasoning":
        text = sanitize_progress_message(item.get("text") or item.get("summary"))
        return ("status", text) if text else None
    if item_type == "agent_message":
        text = sanitize_progress_message(item.get("text"))
        if text and not text.startswith(("{", "[")):
            return ("status", text)
    return None


def sanitize_progress_message(value: object) -> str:
    """Return one bounded display-safe status line without code formatting."""

    text = _ANSI_ESCAPE.sub("", str(value or ""))
    if "```" in text:
        text = text.split("```", 1)[0]
    text = " ".join(text.replace("`", "").split())
    if len(text) <= _ACTIVITY_TEXT_LIMIT:
        return text
    return text[: _ACTIVITY_TEXT_LIMIT - 3].rstrip() + "..."


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
