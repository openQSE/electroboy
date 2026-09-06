"""Projection of AI runtime events into useful learner progress."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

ProgressCallback = Callable[[dict[str, object]], None]
_ACTIVITY_TEXT_LIMIT = 240
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_GENERIC_STATUS = re.compile(
    r"^(still (working|processing)|working|processing|analyzing the repository|"
    r"creating the course)([. ]|$)",
    re.IGNORECASE,
)


class AgentActivityReporter:
    """Project detailed model messages while dropping protocol noise."""

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
    if event_type in {"error", "turn.failed"}:
        detail = sanitize_progress_message(event.get("message") or event.get("error"))
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
    """Return one bounded status line without code or generic heartbeats."""

    text = _ANSI_ESCAPE.sub("", str(value or ""))
    if "```" in text:
        text = text.split("```", 1)[0]
    text = " ".join(text.replace("`", "").split())
    if not text or _GENERIC_STATUS.match(text):
        return ""
    if len(text) <= _ACTIVITY_TEXT_LIMIT:
        return text
    return text[: _ACTIVITY_TEXT_LIMIT - 3].rstrip() + "..."
