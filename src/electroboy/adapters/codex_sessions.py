"""Read resumable Codex session metadata without depending on the Codex UI."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


CODEX_SESSION_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


@dataclass(frozen=True)
class CodexSessionSummary:
    """Stable metadata needed to display and resume one Codex session."""

    session_id: str
    cwd: Path
    created_at: str
    updated_at: str
    user_messages: tuple[str, ...]

    def payload(self) -> dict[str, object]:
        return {
            "provider": "codex",
            "provider_session_id": self.session_id,
            "project_root": str(self.cwd),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def codex_sessions_for_root(root: Path | str) -> list[CodexSessionSummary]:
    """Return locally persisted Codex sessions for one exact working directory."""

    expected_root = Path(root).expanduser().resolve()
    sessions = [
        session
        for path in _codex_session_paths()
        if (session := _read_codex_session(path)) is not None
        and session.cwd == expected_root
    ]
    return sorted(sessions, key=lambda session: session.updated_at, reverse=True)


def codex_session_by_id(session_id: str) -> CodexSessionSummary | None:
    """Return one locally persisted Codex session by its provider UUID."""

    normalized_id = session_id.strip().lower()
    if CODEX_SESSION_ID_RE.fullmatch(normalized_id) is None:
        return None
    for path in _codex_session_paths():
        if normalized_id not in path.name.lower():
            continue
        session = _read_codex_session(path)
        if session is not None and session.session_id.lower() == normalized_id:
            return session
    return None


def _codex_sessions_dir() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "sessions"
    return Path.home() / ".codex" / "sessions"


def _codex_session_paths() -> tuple[Path, ...]:
    sessions_dir = _codex_sessions_dir()
    if not sessions_dir.exists():
        return ()
    try:
        return tuple(sessions_dir.rglob("*.jsonl"))
    except OSError:
        return ()


def _read_codex_session(path: Path) -> CodexSessionSummary | None:
    metadata: dict[str, object] | None = None
    user_messages: list[str] = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    continue
                if record.get("type") == "session_meta" and metadata is None:
                    metadata = payload
                message = _user_message(payload)
                if message:
                    user_messages.append(message)
    except OSError:
        return None
    if metadata is None:
        return None
    session_id = str(metadata.get("session_id") or metadata.get("id") or "").strip()
    cwd_text = str(metadata.get("cwd") or "").strip()
    if CODEX_SESSION_ID_RE.fullmatch(session_id.lower()) is None or not cwd_text:
        return None
    created_at = str(metadata.get("timestamp") or "").strip()
    try:
        updated_at = datetime.fromtimestamp(
            path.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat()
    except OSError:
        updated_at = created_at
    return CodexSessionSummary(
        session_id=session_id,
        cwd=Path(cwd_text).expanduser().resolve(),
        created_at=created_at,
        updated_at=updated_at,
        user_messages=tuple(user_messages),
    )


def _user_message(payload: dict[str, object]) -> str:
    if payload.get("type") != "message" or payload.get("role") != "user":
        return ""
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    text = "\n".join(
        str(item.get("text") or "")
        for item in content
        if isinstance(item, dict) and item.get("type") == "input_text"
    ).strip()
    return text
