"""Ad-hoc agent commands and project-scoped provider session history."""

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


AD_HOC_CATALOG_RELATIVE_PATH = (
    Path(".electroboy") / "service" / "ad-hoc-sessions.json"
)
_LEGACY_AD_HOC_PROMPT = "Here is the code base. Follow what the operator says."
_AD_HOC_PROMPT_PREFIX = "You are an ad-hoc agent for this code base."
_CATALOG_LOCK = threading.Lock()


def ad_hoc_agent_command(
    root: Path,
    provider_session_id: str | None = None,
) -> list[str]:
    """Build a new or resumed Codex TUI command for ad-hoc work."""

    command = [
        "codex",
        "--cd",
        str(root),
        "--sandbox",
        "workspace-write",
    ]
    if provider_session_id:
        command.extend(["resume", provider_session_id])
    else:
        command.append(ad_hoc_agent_prompt())
    return command


def ad_hoc_agent_prompt() -> str:
    """Keep an ad-hoc agent independent from the staged workflow."""

    return "\n".join(
        [
            _AD_HOC_PROMPT_PREFIX,
            "The active ElectroBoy workflow stage is irrelevant to this session.",
            "Do not inspect files, read .electroboy state, run commands, or launch",
            "another agent until the operator gives you a task.",
            "Do not infer a task from workflow state, project artifacts, or",
            "repository contents.",
            "Do not run any electroboy workflow command unless the operator",
            "explicitly asks for that exact command.",
            "Wait for and then follow the operator's next instruction directly.",
        ]
    )


def ad_hoc_session_history(
    service_root: Path,
    project_root: Path,
) -> list[dict[str, object]]:
    """Return validated indexed ad-hoc sessions for one project root."""

    resolved_root = project_root.expanduser().resolve()
    with _CATALOG_LOCK:
        catalog = _load_catalog(service_root)
        retained: list[dict[str, object]] = []
        project_entries: list[dict[str, object]] = []
        for entry in catalog["sessions"]:
            if _entry_project_root(entry) != resolved_root:
                retained.append(entry)
                continue
            session = _indexed_session(entry, resolved_root)
            if session is None:
                continue
            project_entries.append(
                _history_entry(
                    session,
                    electroboy_session_id=str(
                        entry.get("electroboy_session_id") or ""
                    ),
                    title=str(entry.get("title") or "Ad-hoc session"),
                )
            )
        catalog["sessions"] = [*project_entries, *retained]
        _save_catalog(service_root, catalog)
        return sorted(
            [_history_payload(entry) for entry in project_entries],
            key=lambda entry: str(entry.get("updated_at") or ""),
            reverse=True,
        )


def remember_ad_hoc_session(
    service_root: Path,
    session: CodexSessionSummary,
    *,
    electroboy_session_id: str = "",
    title: str | None = None,
) -> dict[str, object]:
    """Record a provider session explicitly selected for ad-hoc use."""

    with _CATALOG_LOCK:
        catalog = _load_catalog(service_root)
        existing = next(
            (
                entry
                for entry in catalog["sessions"]
                if str(entry.get("provider_session_id") or "")
                == session.session_id
            ),
            None,
        )
        entry = _history_entry(
            session,
            electroboy_session_id=(
                electroboy_session_id
                or str((existing or {}).get("electroboy_session_id") or "")
            ),
            title=title or str((existing or {}).get("title") or "") or None,
        )
        _upsert_catalog_entry(catalog, entry)
        _save_catalog(service_root, catalog)
        return entry


def resumable_ad_hoc_session(
    service_root: Path,
    provider_session_id: str,
    project_root: Path,
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
            ),
            None,
        )
    session = _indexed_session(indexed, resolved_root) if indexed else None
    if session is None and indexed is None:
        session = codex_session_by_id(provider_session_id)
    if session is None or session.cwd != resolved_root:
        return None
    return session


def start_ad_hoc_session_tracking(
    service_root: Path,
    project_root: Path,
    electroboy_session_id: str,
    known_paths: Collection[Path],
    is_active: Callable[[], bool],
    on_registered: Callable[[CodexSessionSummary], None] | None = None,
) -> threading.Thread:
    """Register the one Codex rollout created by a new ad-hoc launch."""

    thread = threading.Thread(
        target=_track_new_ad_hoc_session,
        args=(
            service_root,
            project_root,
            electroboy_session_id,
            frozenset(path.resolve() for path in known_paths),
            is_active,
            on_registered,
        ),
        name=f"electroboy-ad-hoc-index-{electroboy_session_id[:8]}",
        daemon=True,
    )
    thread.start()
    return thread


def _track_new_ad_hoc_session(
    service_root: Path,
    project_root: Path,
    electroboy_session_id: str,
    known_paths: frozenset[Path],
    is_active: Callable[[], bool],
    on_registered: Callable[[CodexSessionSummary], None] | None,
) -> None:
    resolved_root = project_root.expanduser().resolve()
    while True:
        for path in codex_session_paths() - known_paths:
            session = codex_session_from_path(path)
            if (
                session is None
                or session.cwd != resolved_root
                or not _is_ad_hoc_session(session)
            ):
                continue
            remember_ad_hoc_session(
                service_root,
                session,
                electroboy_session_id=electroboy_session_id,
            )
            if on_registered is not None:
                on_registered(session)
            return
        if not is_active():
            return
        time.sleep(0.25)


def _is_ad_hoc_session(session: CodexSessionSummary) -> bool:
    return any(_is_ad_hoc_prompt(message) for message in session.user_messages)


def _is_ad_hoc_prompt(message: str) -> bool:
    stripped = message.strip()
    return stripped == _LEGACY_AD_HOC_PROMPT or stripped.startswith(
        _AD_HOC_PROMPT_PREFIX
    )


def _history_entry(
    session: CodexSessionSummary,
    *,
    electroboy_session_id: str = "",
    title: str | None = None,
) -> dict[str, object]:
    return {
        **session.payload(),
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
            or _is_ad_hoc_prompt(text)
            or text.startswith("<environment_context>")
        ):
            continue
        single_line = " ".join(text.split())
        return single_line[:117] + "..." if len(single_line) > 120 else single_line
    return "Ad-hoc session"


def _history_payload(entry: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in entry.items()
        if key not in {"session_path", "last_validated_at"}
    }


def _catalog_path(service_root: Path) -> Path:
    return service_root.expanduser().resolve() / AD_HOC_CATALOG_RELATIVE_PATH


def _load_catalog(service_root: Path) -> dict[str, object]:
    path = _catalog_path(service_root)
    if not path.exists():
        return {"schema_version": 2, "sessions": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 2, "sessions": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), list):
        return {"schema_version": 2, "sessions": []}
    return {
        "schema_version": 2,
        "sessions": [
            dict(entry) for entry in payload["sessions"] if isinstance(entry, dict)
        ],
    }


def _save_catalog(service_root: Path, catalog: dict[str, object]) -> None:
    path = _catalog_path(service_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    sessions = catalog.get("sessions", [])
    payload = {
        "schema_version": 2,
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
    entry: dict[str, object],
    project_root: Path,
) -> CodexSessionSummary | None:
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
        # Schema version 1 catalogs did not persist rollout paths. Resolve only
        # the UUIDs already present in the catalog; do not discover new history.
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
            and str(existing.get("provider_session_id") or "") != session_id
        ],
    ]
