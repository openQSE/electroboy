"""Ad-hoc agent commands and project-scoped provider session history."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from electroboy.adapters.codex_sessions import (
    CodexSessionSummary,
    codex_session_by_id,
    codex_sessions_for_root,
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
    """Discover and persist resumable ad-hoc sessions for one project root."""

    resolved_root = project_root.expanduser().resolve()
    provider_sessions = codex_sessions_for_root(resolved_root)
    with _CATALOG_LOCK:
        catalog = _load_catalog(service_root)
        known_ids = {
            str(entry.get("provider_session_id") or "")
            for entry in catalog["sessions"]
            if str(entry.get("project_root") or "") == str(resolved_root)
        }
        discovered = [
            _history_entry(session)
            for session in provider_sessions
            if session.session_id in known_ids or _is_ad_hoc_session(session)
        ]
        catalog["sessions"] = [
            entry
            for entry in catalog["sessions"]
            if str(entry.get("project_root") or "") != str(resolved_root)
        ]
        for entry in discovered:
            _upsert_catalog_entry(catalog, entry)
        _save_catalog(service_root, catalog)
        return sorted(
            [
                dict(entry)
                for entry in catalog["sessions"]
                if str(entry.get("project_root") or "") == str(resolved_root)
            ],
            key=lambda entry: str(entry.get("updated_at") or ""),
            reverse=True,
        )


def remember_ad_hoc_session(
    service_root: Path,
    session: CodexSessionSummary,
) -> dict[str, object]:
    """Record a provider session explicitly selected for ad-hoc use."""

    with _CATALOG_LOCK:
        catalog = _load_catalog(service_root)
        entry = _history_entry(session)
        _upsert_catalog_entry(catalog, entry)
        _save_catalog(service_root, catalog)
        return entry


def resumable_ad_hoc_session(
    provider_session_id: str,
    project_root: Path,
) -> CodexSessionSummary | None:
    """Resolve a provider UUID only when it belongs to the active project."""

    session = codex_session_by_id(provider_session_id)
    if session is None or session.cwd != project_root.expanduser().resolve():
        return None
    return session


def _is_ad_hoc_session(session: CodexSessionSummary) -> bool:
    return any(_is_ad_hoc_prompt(message) for message in session.user_messages)


def _is_ad_hoc_prompt(message: str) -> bool:
    stripped = message.strip()
    return stripped == _LEGACY_AD_HOC_PROMPT or stripped.startswith(
        _AD_HOC_PROMPT_PREFIX
    )


def _history_entry(session: CodexSessionSummary) -> dict[str, object]:
    return {
        **session.payload(),
        "title": _session_title(session),
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


def _catalog_path(service_root: Path) -> Path:
    return service_root.expanduser().resolve() / AD_HOC_CATALOG_RELATIVE_PATH


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
