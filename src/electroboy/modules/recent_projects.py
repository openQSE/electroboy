"""Recent project capability module declaration."""

from __future__ import annotations

import json
from pathlib import Path

from electroboy.service.registry import ServiceModule
from electroboy.models import utc_now

RECENT_PROJECTS_RELATIVE_PATH = Path(".electroboy") / "service" / "recent-projects.json"
RECENT_PROJECT_LIMIT = 12


def module() -> ServiceModule:
    return ServiceModule(
        id="recent_projects",
        label="Recent Projects",
        capabilities=frozenset({"recent-projects"}),
        state_namespace="recent_projects",
    )


def recent_projects_path(service_root: Path | str) -> Path:
    return Path(service_root).expanduser().resolve() / RECENT_PROJECTS_RELATIVE_PATH


def load_recent_projects(service_root: Path | str) -> dict[str, object]:
    path = recent_projects_path(service_root)
    if not path.exists():
        return {"schema_version": 1, "projects": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "projects": []}
    if not isinstance(data, dict):
        return {"schema_version": 1, "projects": []}
    if not isinstance(data.get("projects"), list):
        data["projects"] = []
    data["schema_version"] = 1
    return data


def save_recent_projects(service_root: Path | str, data: dict[str, object]) -> None:
    path = recent_projects_path(service_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def recent_project_entries(service_root: Path | str) -> list[dict[str, object]]:
    data = load_recent_projects(service_root)
    entries: list[dict[str, object]] = []
    for entry in data.get("projects", []):
        if not isinstance(entry, dict):
            continue
        project_path = str(entry.get("path") or "").strip()
        if not project_path:
            continue
        kind = str(entry.get("kind") or "project").strip()
        if kind not in {"project", "meta", "creative"}:
            kind = "project"
        label = str(entry.get("label") or Path(project_path).name or project_path)
        entries.append(
            {
                "kind": kind,
                "label": label,
                "path": project_path,
                "opened_at": str(entry.get("opened_at") or ""),
            }
        )
    return entries[:RECENT_PROJECT_LIMIT]


def remember_recent_project(
    service_root: Path | str,
    project_root: Path | str,
    kind: str,
) -> None:
    project_path = str(Path(project_root).expanduser().resolve())
    if kind not in {"project", "meta", "creative"}:
        kind = "project"
    data = load_recent_projects(service_root)
    existing = [
        entry
        for entry in data.get("projects", [])
        if isinstance(entry, dict) and str(entry.get("path") or "") != project_path
    ]
    data["projects"] = [
        {
            "kind": kind,
            "label": Path(project_path).name or project_path,
            "path": project_path,
            "opened_at": utc_now(),
        },
        *existing,
    ][:RECENT_PROJECT_LIMIT]
    save_recent_projects(service_root, data)
