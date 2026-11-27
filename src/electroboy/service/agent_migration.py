"""One-time normalization of persisted agent selection metadata."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .agent_backend import migrate_agent_selection


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    """Replace one JSON file without leaving a partial write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        if path.exists():
            os.fchmod(descriptor, path.stat().st_mode & 0o777)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def preserve_unresolved_selection(
    original: dict[str, object], refreshed: dict[str, object],
) -> dict[str, object]:
    """Do not infer a legacy session's selection merely by listing history."""
    if original.get("selection_status") != "unresolved":
        return refreshed
    refreshed["provider_binary"] = ""
    refreshed["selection_status"] = "unresolved"
    if "provider_executable" in original:
        refreshed["provider_executable"] = original["provider_executable"]
    else:
        refreshed.pop("provider_executable", None)
    return refreshed


def migrate_session_catalog(path: Path, project_root: Path) -> None:
    """Normalize entries for one project; the owning module holds its lock."""
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), list):
        raise ValueError(f"Invalid agent session catalog: {path}")
    root = project_root.expanduser().resolve()
    changed = False
    for index, entry in enumerate(payload["sessions"]):
        if not isinstance(entry, dict):
            continue
        project = str(entry.get("project_root") or "")
        if not project or Path(project).expanduser().resolve() != root:
            continue
        normalized = migrate_agent_selection(entry)
        if normalized != entry:
            payload["sessions"][index] = normalized
            changed = True
    if changed:
        write_json_atomic(path, payload)


def migrate_workspace_sessions(path: Path, workspace_id: str, project_root: Path) -> None:
    """Normalize recorded selections for this workspace and project."""
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), list):
        raise ValueError(f"Invalid agent session records: {path}")
    root = project_root.expanduser().resolve()
    changed = False
    for entry in payload["sessions"]:
        if not isinstance(entry, dict) or entry.get("kind") == "project-shell":
            continue
        if str(entry.get("workspace_id") or entry.get("context_id") or "") != workspace_id:
            continue
        project = str(entry.get("active_project_root") or entry.get("activation_root") or "")
        if not project or Path(project).expanduser().resolve() != root:
            continue
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        normalized = migrate_agent_selection(metadata)
        if normalized != metadata:
            entry["metadata"] = normalized
            changed = True
    if changed:
        write_json_atomic(path, payload)
