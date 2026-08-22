"""Creative agent commands and scoped provider session history."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Collection
from datetime import datetime, timezone
from pathlib import Path

from electroboy.adapters.codex_sessions import (
    CodexSessionSummary,
    codex_session_by_id,
    codex_session_from_path,
    codex_session_paths,
    codex_sessions_directory,
)


CREATIVE_AGENT_CATALOG_RELATIVE_PATH = (
    Path(".electroboy") / "service" / "creative-agent-sessions.json"
)
CREATIVE_GENERAL_SCOPE = "general"
CREATIVE_DOCUMENT_SCOPE = "document"
CREATIVE_GENERAL_SCOPE_KEY = "general"
_CREATIVE_PROMPT_PREFIX = "Act as a creative writing collaborator inside this project."
_CATALOG_LOCK = threading.Lock()


def creative_document_scope_key(document_path: str) -> str:
    return f"document:{document_path}"


def creative_session_history(
    service_root: Path,
    project_root: Path,
    *,
    scope: str,
    scope_key: str,
) -> list[dict[str, object]]:
    """Return validated indexed creative sessions for one scope."""

    resolved_root = project_root.expanduser().resolve()
    with _CATALOG_LOCK:
        catalog = _load_catalog(service_root)
        retained: list[dict[str, object]] = []
        scoped_entries: list[dict[str, object]] = []
        for entry in catalog["sessions"]:
            if (
                _entry_project_root(entry) != resolved_root
                or str(entry.get("scope_key") or "") != scope_key
            ):
                retained.append(entry)
                continue
            session = _indexed_session(entry, resolved_root)
            if session is None:
                continue
            scoped_entries.append(
                _history_entry(
                    session,
                    scope=scope,
                    scope_key=scope_key,
                    document_path=str(entry.get("document_path") or ""),
                    target_type=str(entry.get("target_type") or ""),
                    target_path=str(entry.get("target_path") or ""),
                    electroboy_session_id=str(
                        entry.get("electroboy_session_id") or ""
                    ),
                    title=str(entry.get("title") or "Creative session"),
                )
            )
        catalog["sessions"] = [*scoped_entries, *retained]
        _save_catalog(service_root, catalog)
        return sorted(
            [_history_payload(entry) for entry in scoped_entries],
            key=lambda entry: str(entry.get("updated_at") or ""),
            reverse=True,
        )


def remember_creative_session(
    service_root: Path,
    session: CodexSessionSummary,
    *,
    scope: str,
    scope_key: str,
    document_path: str = "",
    target_type: str = "",
    target_path: str = "",
    electroboy_session_id: str = "",
    title: str | None = None,
) -> dict[str, object]:
    """Record a provider session explicitly selected for creative work."""

    with _CATALOG_LOCK:
        catalog = _load_catalog(service_root)
        existing = next(
            (
                entry
                for entry in catalog["sessions"]
                if str(entry.get("provider_session_id") or "") == session.session_id
                and str(entry.get("scope_key") or "") == scope_key
            ),
            None,
        )
        entry = _history_entry(
            session,
            scope=scope,
            scope_key=scope_key,
            document_path=document_path,
            target_type=target_type,
            target_path=target_path,
            electroboy_session_id=(
                electroboy_session_id
                or str((existing or {}).get("electroboy_session_id") or "")
            ),
            title=title or str((existing or {}).get("title") or "") or None,
        )
        _upsert_catalog_entry(catalog, entry)
        _save_catalog(service_root, catalog)
        return entry


def resumable_creative_session(
    service_root: Path,
    provider_session_id: str,
    project_root: Path,
    *,
    scope_key: str,
) -> CodexSessionSummary | None:
    """Resolve an indexed UUID, importing an explicit UUID when necessary."""

    resolved_root = project_root.expanduser().resolve()
    with _CATALOG_LOCK:
        catalog = _load_catalog(service_root)
        indexed = next(
            (
                entry
                for entry in catalog["sessions"]
                if str(entry.get("provider_session_id") or "").lower()
                == provider_session_id.lower()
                and str(entry.get("scope_key") or "") == scope_key
            ),
            None,
        )
    session = _indexed_session(indexed, resolved_root) if indexed else None
    if session is None and indexed is None:
        session = codex_session_by_id(provider_session_id)
    if session is None or session.cwd != resolved_root:
        return None
    return session


def start_creative_session_tracking(
    service_root: Path,
    project_root: Path,
    electroboy_session_id: str,
    known_paths: Collection[Path],
    is_active: Callable[[], bool],
    *,
    scope: str,
    scope_key: str,
    document_path: str = "",
    target_type: str = "",
    target_path: str = "",
    on_registered: Callable[[CodexSessionSummary], None] | None = None,
) -> threading.Thread:
    """Register the one Codex rollout created by a new creative launch."""

    thread = threading.Thread(
        target=_track_new_creative_session,
        args=(
            service_root,
            project_root,
            electroboy_session_id,
            frozenset(path.resolve() for path in known_paths),
            is_active,
            scope,
            scope_key,
            document_path,
            target_type,
            target_path,
            on_registered,
        ),
        name=f"electroboy-creative-index-{electroboy_session_id[:8]}",
        daemon=True,
    )
    thread.start()
    return thread


def _track_new_creative_session(
    service_root: Path,
    project_root: Path,
    electroboy_session_id: str,
    known_paths: frozenset[Path],
    is_active: Callable[[], bool],
    scope: str,
    scope_key: str,
    document_path: str,
    target_type: str,
    target_path: str,
    on_registered: Callable[[CodexSessionSummary], None] | None,
) -> None:
    resolved_root = project_root.expanduser().resolve()
    while True:
        for path in codex_session_paths() - known_paths:
            session = codex_session_from_path(path)
            if (
                session is None
                or session.cwd != resolved_root
                or not _is_creative_session(session)
            ):
                continue
            remember_creative_session(
                service_root,
                session,
                scope=scope,
                scope_key=scope_key,
                document_path=document_path,
                target_type=target_type,
                target_path=target_path,
                electroboy_session_id=electroboy_session_id,
            )
            if on_registered is not None:
                on_registered(session)
            return
        if not is_active():
            return
        time.sleep(0.25)


def _is_creative_session(session: CodexSessionSummary) -> bool:
    return any(
        message.strip().startswith(_CREATIVE_PROMPT_PREFIX)
        for message in session.user_messages
    )


def _history_entry(
    session: CodexSessionSummary,
    *,
    scope: str,
    scope_key: str,
    document_path: str = "",
    target_type: str = "",
    target_path: str = "",
    electroboy_session_id: str = "",
    title: str | None = None,
) -> dict[str, object]:
    return {
        **session.payload(),
        "scope": scope,
        "scope_key": scope_key,
        "document_path": document_path,
        "target_type": target_type,
        "target_path": target_path,
        "electroboy_session_id": electroboy_session_id,
        "title": title or _session_title(session),
        "last_validated_at": datetime.now(timezone.utc).isoformat(),
        "resumable": True,
    }


def _session_title(session: CodexSessionSummary) -> str:
    for message in session.user_messages:
        text = message.strip()
        if (
            not text
            or text.startswith(_CREATIVE_PROMPT_PREFIX)
            or text.startswith("<environment_context>")
        ):
            continue
        single_line = " ".join(text.split())
        return single_line[:117] + "..." if len(single_line) > 120 else single_line
    return "Creative session"


def _history_payload(entry: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in entry.items()
        if key not in {"session_path", "last_validated_at"}
    }


def _catalog_path(service_root: Path) -> Path:
    return service_root.expanduser().resolve() / CREATIVE_AGENT_CATALOG_RELATIVE_PATH


def _load_catalog(service_root: Path) -> dict[str, object]:
    path = _catalog_path(service_root)
    if not path.exists():
        return {"schema_version": 1, "sessions": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "sessions": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), list):
        return {"schema_version": 1, "sessions": []}
    return {
        "schema_version": 1,
        "sessions": [
            dict(entry) for entry in payload["sessions"] if isinstance(entry, dict)
        ],
    }


def _save_catalog(service_root: Path, catalog: dict[str, object]) -> None:
    path = _catalog_path(service_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    sessions = catalog.get("sessions", [])
    payload = {
        "schema_version": 1,
        "sessions": sessions[:500] if isinstance(sessions, list) else [],
    }
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _entry_project_root(entry: dict[str, object]) -> Path | None:
    value = str(entry.get("project_root") or "").strip()
    return Path(value).expanduser().resolve() if value else None


def _indexed_session(
    entry: dict[str, object] | None,
    project_root: Path,
) -> CodexSessionSummary | None:
    if not entry:
        return None
    session_id = str(entry.get("provider_session_id") or "").strip().lower()
    if not session_id:
        return None
    path_value = str(entry.get("session_path") or "").strip()
    if path_value:
        path = Path(path_value).expanduser().resolve()
        sessions_root = codex_sessions_directory().expanduser().resolve()
        if not path.is_relative_to(sessions_root):
            return None
        session = codex_session_from_path(path, include_messages=False)
    else:
        session = codex_session_by_id(session_id, include_messages=False)
    if (
        session is None
        or session.session_id.lower() != session_id
        or session.cwd != project_root
    ):
        return None
    return session


def _upsert_catalog_entry(
    catalog: dict[str, object],
    entry: dict[str, object],
) -> None:
    session_id = str(entry.get("provider_session_id") or "")
    scope_key = str(entry.get("scope_key") or "")
    sessions = catalog.setdefault("sessions", [])
    if not isinstance(sessions, list):
        sessions = []
        catalog["sessions"] = sessions
    sessions[:] = [
        entry,
        *[
            existing
            for existing in sessions
            if isinstance(existing, dict)
            and (
                str(existing.get("provider_session_id") or "") != session_id
                or str(existing.get("scope_key") or "") != scope_key
            )
        ],
    ]
