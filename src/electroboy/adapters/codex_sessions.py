"""Read resumable Codex session metadata without depending on the Codex UI."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from functools import lru_cache
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
    path: Path
    executable: str = ""

    def payload(self) -> dict[str, object]:
        return {
            "provider": "codex",
            "provider_session_id": self.session_id,
            "project_root": str(self.cwd),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "session_path": str(self.path),
            **({"provider_executable": self.executable} if self.executable else {}),
        }


def codex_sessions_for_root(root: Path | str) -> list[CodexSessionSummary]:
    """Return locally persisted Codex sessions for one exact working directory."""

    expected_root = Path(root).expanduser().resolve()
    sessions = [
        session
        for path in codex_session_paths()
        if (session := _read_codex_session(path)) is not None
        and session.cwd == expected_root
    ]
    return sorted(sessions, key=lambda session: session.updated_at, reverse=True)


def codex_session_by_id(
    session_id: str,
    *,
    include_messages: bool = True,
    executable: str | None = None,
    root: Path | None = None,
) -> CodexSessionSummary | None:
    """Return one locally persisted Codex session by its provider UUID."""

    normalized_id = session_id.strip().lower()
    if CODEX_SESSION_ID_RE.fullmatch(normalized_id) is None:
        return None
    for path in codex_session_paths(executable=executable, root=root):
        if normalized_id not in path.name.lower():
            continue
        session = codex_session_from_path(
            path, include_messages=include_messages, executable=executable
        )
        if session is not None and session.session_id.lower() == normalized_id:
            return session
    return None


def codex_sessions_directory(
    *, executable: str | None = None, root: Path | None = None
) -> Path:
    """Resolve storage through the selected executable, including its wrapper."""

    if executable:
        command = shutil.which(executable)
        if command:
            home = _reported_codex_home(
                command,
                str((root or Path.cwd()).resolve()),
                os.environ.get("CODEX_HOME", ""),
                os.environ.get("HOME", ""),
                Path(command).stat().st_mtime_ns,
            )
            if home:
                return Path(home) / "sessions"

    # Older clients do not report codexHome; preserve their inherited setting.
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "sessions"
    return Path.home() / ".codex" / "sessions"


@lru_cache(maxsize=128)
def _reported_codex_home(
    executable: str, root: str, inherited_home: str, user_home: str, modified: int
) -> str | None:
    """Ask the executable for its home without starting an agent conversation."""
    request = (
        json.dumps(
            {
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "electroboy", "version": "0.1.0"}},
            }
        )
        + "\n"
    )
    environment = os.environ.copy()
    for key, value in (("CODEX_HOME", inherited_home), ("HOME", user_home)):
        if value:
            environment[key] = value
        else:
            environment.pop(key, None)
    try:
        with subprocess.Popen(
            [executable, "app-server"],
            cwd=root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
            env=environment,
        ) as process:
            try:
                output, _ = process.communicate(request, timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
                return None
    except OSError:
        return None
    for line in output.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("id") != 1:
            continue
        result = record.get("result")
        home = result.get("codexHome") if isinstance(result, dict) else None
        if isinstance(home, str) and Path(home).is_absolute():
            return str(Path(home).resolve())
    return None


def codex_session_paths(
    *,
    executable: str | None = None,
    root: Path | None = None,
    directory: Path | None = None,
) -> frozenset[Path]:
    """Return Codex rollout paths without parsing their contents."""

    sessions_dir = directory or codex_sessions_directory(
        executable=executable, root=root
    )
    if not sessions_dir.exists():
        return frozenset()
    sessions_dir = sessions_dir.expanduser().resolve()
    try:
        return frozenset(
            resolved
            for path in sessions_dir.rglob("*.jsonl")
            if (resolved := path.resolve()).is_relative_to(sessions_dir)
        )
    except OSError:
        return frozenset()


def codex_session_from_path(
    path: Path | str,
    *,
    include_messages: bool = True,
    executable: str | None = None,
) -> CodexSessionSummary | None:
    """Read one known Codex rollout instead of searching session history."""

    session = _read_codex_session(
        Path(path).expanduser().resolve(),
        include_messages=include_messages,
    )
    return replace(session, executable=executable or "") if session else None


def start_codex_session_tracking(
    root: Path | str,
    known_paths: Collection[Path],
    is_active: Callable[[], bool],
    on_discovered: Callable[[CodexSessionSummary], None],
    *,
    name: str = "electroboy-codex-session-index",
    executable: str | None = None,
) -> threading.Thread:
    """Report the Codex rollout created by one newly launched session."""

    expected_root = Path(root).expanduser().resolve()
    known = frozenset(path.resolve() for path in known_paths)
    directory = codex_sessions_directory(executable=executable, root=expected_root)

    def track() -> None:
        while is_active():
            for path in codex_session_paths(directory=directory) - known:
                session = codex_session_from_path(
                    path, include_messages=False, executable=executable
                )
                if session is None or session.cwd != expected_root:
                    continue
                on_discovered(session)
                return
            time.sleep(0.25)

    thread = threading.Thread(target=track, name=name, daemon=True)
    thread.start()
    return thread


def _read_codex_session(
    path: Path,
    *,
    include_messages: bool = True,
) -> CodexSessionSummary | None:
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
                    if not include_messages:
                        break
                if not include_messages:
                    continue
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
        path=path.resolve(),
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
