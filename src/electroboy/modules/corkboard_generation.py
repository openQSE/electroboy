"""Shared non-interactive corkboard generation jobs."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from electroboy.adapters.base import AgentInvocation, AgentRuntime
from electroboy.runtime import runtime_for_role
from electroboy.service.corkboard import CorkboardProvider
from electroboy.service.services import ServiceServices
from electroboy.state_store import StateError

MAX_GENERATED_CARDS = 75
IGNORED_PARTS = frozenset(
    {".electroboy", ".git", ".hg", ".svn", "__pycache__", "node_modules"}
)
CREATIVE_EXTENSIONS = frozenset({".md", ".markdown", ".rst", ".txt"})
SOFTWARE_EXTENSIONS = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".go",
        ".h",
        ".hpp",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".py",
        ".rs",
        ".rst",
        ".sh",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
)

PASS_DEFINITIONS: dict[str, tuple[dict[str, str], ...]] = {
    "creative-writing": (
        {
            "id": "story-scenes",
            "label": "Story / Scenes",
            "description": "Extract scenes, ideas, storylines, and causal progression.",
        },
        {
            "id": "characters",
            "label": "Characters",
            "description": "Map characters, motivations, conflicts, and relationships.",
        },
        {
            "id": "events-timeline",
            "label": "Events / Timeline",
            "description": (
                "Arrange events chronologically and connect causes to effects."
            ),
        },
    ),
    "software": (
        {
            "id": "architecture-components",
            "label": "Architecture / Components",
            "description": "Map components, responsibilities, and architectural flow.",
        },
        {
            "id": "dependencies-data-flow",
            "label": "Dependencies / Data Flow",
            "description": (
                "Show dependencies and how data or control moves through them."
            ),
        },
        {
            "id": "requirements-tasks",
            "label": "Requirements / Tasks",
            "description": (
                "Turn requirements into ordered implementation work and risks."
            ),
        },
    ),
}

ROLE_COLORS = {
    "scene": "butter",
    "story": "sky",
    "storyline": "sky",
    "timeline": "peach",
    "event": "peach",
    "character": "lilac",
    "relationship": "lilac",
    "idea": "mint",
    "conflict": "rose",
    "component": "sky",
    "architecture": "sky",
    "dependency": "peach",
    "data-flow": "peach",
    "requirement": "mint",
    "task": "butter",
    "risk": "rose",
    "decision": "lilac",
}


def generation_passes(workflow_id: str) -> list[dict[str, str]]:
    """Return generation passes available to one workflow."""

    return [dict(item) for item in PASS_DEFINITIONS.get(workflow_id, ())]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: object, fallback: str = "card") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug or fallback


def _safe_source_path(root: Path, value: object) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise StateError(
            "generation source must be inside the active project"
        ) from error
    if any(part in IGNORED_PARTS for part in relative.parts):
        raise StateError("generation source is not available")
    if not candidate.is_file():
        raise StateError(
            f"generation source file does not exist: {relative.as_posix()}"
        )
    return relative.as_posix()


def _project_manifest(root: Path, workflow_id: str) -> list[str]:
    extensions = (
        CREATIVE_EXTENSIONS
        if workflow_id == "creative-writing"
        else SOFTWARE_EXTENSIONS
    )
    paths: list[str] = []
    for path in sorted(root.rglob("*")):
        if len(paths) >= 500:
            break
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        try:
            path.resolve().relative_to(root)
        except ValueError:
            continue
        if path.stat().st_size > 2_000_000:
            continue
        paths.append(relative.as_posix())
    if not paths:
        raise StateError("the active project has no supported source files")
    return paths


def _default_title(scope: dict[str, str], pass_definition: dict[str, str]) -> str:
    if scope["type"] == "file":
        source = Path(scope["path"]).name
        stem = source.rsplit(".", 1)[0] if "." in source else source
        return f"{stem} — {pass_definition['label']}"
    return f"Project — {pass_definition['label']}"


def _board_id(
    provider: CorkboardProvider,
    context_id: str,
    title: str,
    *,
    connection_id: str,
) -> str:
    existing = {
        str(item.get("board_id") or "")
        for item in provider.list_boards(
            context_id,
            connection_id=connection_id,
        )
    }
    stem = _slug(title, "generated-board")
    if provider.provider_id == "creative-files":
        candidate = f"corkboard/{stem}.corkboard.json"
        index = 2
        while candidate in existing:
            candidate = f"corkboard/{stem}-{index}.corkboard.json"
            index += 1
        return candidate
    candidate = stem
    index = 2
    suffix = f"/{stem}.corkboard.json"
    while any(item.endswith(suffix) for item in existing):
        candidate = f"{stem}-{index}"
        suffix = f"/{candidate}.corkboard.json"
        index += 1
    return candidate


def _prompt(
    workflow_id: str,
    scope: dict[str, str],
    pass_definition: dict[str, str],
    manifest: list[str],
) -> str:
    creative = workflow_id == "creative-writing"
    domain = "creative writing" if creative else "software"
    scope_instruction = (
        f'Analyze only the project-relative file "{scope["path"]}".'
        if scope["type"] == "file"
        else "Analyze the project as a whole using the supplied source manifest."
    )
    pass_instructions = {
        "story-scenes": (
            "Break the content into meaningful scenes, beats, ideas, and storylines. "
            "Preserve narrative order. Distinguish timeline/event cards from storyline "
            "cards using role values, and connect cards only where one causally "
            "affects another."
        ),
        "characters": (
            "Identify important characters, motivations, goals, conflicts, changes, "
            "and relationships. Use causal connectors for influence, conflict, "
            "revelation, or change."
        ),
        "events-timeline": (
            "Extract events in chronological order, including parallel timelines "
            "when present. Connect causes to consequences and distinguish event, "
            "timeline, and storyline roles."
        ),
        "architecture-components": (
            "Identify components, responsibilities, public boundaries, and "
            "architectural flow. Connect a component to another only when a "
            "dependency or invocation exists."
        ),
        "dependencies-data-flow": (
            "Trace dependencies and data or control flow from inputs toward outputs. "
            "Use causal connectors and order cards from left to right."
        ),
        "requirements-tasks": (
            "Extract requirements, implementation tasks, decisions, and risks. "
            "Order prerequisites before dependents and connect only genuine "
            "dependency relationships."
        ),
    }[pass_definition["id"]]
    manifest_text = "\n".join(f"- {path}" for path in manifest)
    return f"""You are generating an ElectroBoy corkboard from {domain} source material.

{scope_instruction}
Generation pass: {pass_definition['label']}.
{pass_instructions}

Read the source files, but do not modify any file and do not run destructive commands.
Return exactly one JSON object with this shape and no Markdown fence:
{{
  "title": "concise board title",
  "cards": [
    {{
      "id": "stable-short-id",
      "title": "short card title",
      "note": "concise useful summary",
      "role": "semantic role",
      "sequence": 1,
      "lane": "storyline, timeline, character arc, or subsystem",
      "source_path": "project-relative source path"
    }}
  ],
  "connectors": [
    {{
      "source": "source-card-id",
      "target": "target-card-id",
      "relation": "short causal relation",
      "label": "optional connector label"
    }}
  ]
}}

Rules:
- Return between 1 and {MAX_GENERATED_CARDS} cards.
- Keep titles compact and notes specific.
- Sequence must increase in reading, narrative, chronological, dependency,
  or data-flow order.
- The service computes collision-free coordinates; do not return x or y values.
- Use consistent lane names.
- Include only connectors supported by the source; adjacency alone is not causality.
- Every source_path must be one of the paths below.

Source manifest:
{manifest_text}
"""


def _json_plan(result: object) -> dict[str, object]:
    structured = getattr(result, "structured_payload", None)
    if isinstance(structured, dict) and isinstance(structured.get("cards"), list):
        return structured
    text = str(getattr(result, "final_message", "") or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise StateError("agent did not return a corkboard JSON plan") from error
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as nested_error:
            raise StateError(
                "agent returned an invalid corkboard JSON plan"
            ) from nested_error
    if not isinstance(payload, dict):
        raise StateError("agent corkboard plan must be an object")
    return payload


def normalize_generation_plan(
    root: Path,
    plan: dict[str, object],
    *,
    default_source: str = "",
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Validate semantic agent output and assign collision-free positions."""

    raw_cards = plan.get("cards")
    if not isinstance(raw_cards, list) or not raw_cards:
        raise StateError("agent corkboard plan contains no cards")
    if len(raw_cards) > MAX_GENERATED_CARDS:
        raise StateError(f"agent corkboard plan exceeds {MAX_GENERATED_CARDS} cards")
    seen: set[str] = set()
    prepared: list[tuple[float, int, dict[str, object]]] = []
    for index, raw in enumerate(raw_cards):
        if not isinstance(raw, dict):
            raise StateError(f"generated card {index + 1} must be an object")
        title = str(raw.get("title") or "").strip()
        if not title:
            raise StateError(f"generated card {index + 1} has no title")
        base_id = _slug(raw.get("id") or title, f"card-{index + 1}")[:80]
        card_id = base_id
        suffix = 2
        while card_id in seen:
            card_id = f"{base_id}-{suffix}"[:100]
            suffix += 1
        seen.add(card_id)
        try:
            sequence = float(raw.get("sequence", index + 1))
        except (TypeError, ValueError):
            sequence = float(index + 1)
        role = _slug(raw.get("role") or "idea", "idea")
        lane = str(raw.get("lane") or role).strip()[:100] or role
        source = str(raw.get("source_path") or default_source).strip()
        source = _safe_source_path(root, source) if source else ""
        card: dict[str, object] = {
            "id": card_id,
            "title": title[:200],
            "note": str(raw.get("note") or raw.get("summary") or "")[:5000],
            "color": ROLE_COLORS.get(role, "slate"),
            "card_type": "card",
            "metadata": {
                "role": role,
                "lane": lane,
                **({"source": source} if source else {}),
            },
        }
        if source:
            card.update(
                path=source,
                type="file",
                target={"type": "document", "path": source},
            )
        prepared.append((sequence, index, card))
    prepared.sort(key=lambda item: (item[0], item[1]))
    cards: list[dict[str, object]] = []
    for position, (_, _, card) in enumerate(prepared):
        card["x"] = 60 + position * 360
        card["y"] = 60
        cards.append(card)

    raw_connectors = plan.get("connectors", [])
    if not isinstance(raw_connectors, list):
        raise StateError("agent corkboard connectors must be a list")
    connector_ids: set[str] = set()
    connectors: list[dict[str, object]] = []
    for index, raw in enumerate(raw_connectors):
        if not isinstance(raw, dict):
            continue
        source = _slug(raw.get("source"), "")
        target = _slug(raw.get("target"), "")
        if not source or not target or source == target:
            continue
        if source not in seen or target not in seen:
            continue
        connector_id = _slug(
            raw.get("id") or f"{source}-to-{target}",
            f"link-{index + 1}",
        )
        if connector_id in connector_ids:
            connector_id = f"{connector_id}-{index + 1}"
        connector_ids.add(connector_id)
        relation = str(raw.get("relation") or "").strip()
        label = str(raw.get("label") or relation).strip()
        connectors.append(
            {
                "id": connector_id[:100],
                "source": {"card_id": source, "side": "right", "offset": 0.5},
                "target": {"card_id": target, "side": "left", "offset": 0.5},
                "color": "#ead8b0",
                "thickness": 3,
                "curve": 0.18,
                "style": "string",
                "label": label[:200],
            }
        )
    return cards, connectors


@dataclass
class CorkboardGenerationJob:
    id: str
    context_id: str
    workflow_id: str
    provider_id: str
    scope: dict[str, str]
    pass_id: str
    title: str
    board_id: str
    status: str = "queued"
    step: str = "Queued"
    progress: int = 5
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    result: dict[str, object] | None = None
    error: str = ""

    def payload(self) -> dict[str, object]:
        return {
            "job_id": self.id,
            "status": self.status,
            "step": self.step,
            "progress": self.progress,
            "workflow": self.workflow_id,
            "provider": self.provider_id,
            "scope": dict(self.scope),
            "pass": self.pass_id,
            "title": self.title,
            "board_id": self.board_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": dict(self.result) if self.result else None,
            "error": self.error,
        }


RuntimeFactory = Callable[[str, Path], AgentRuntime]


def _default_runtime_factory(role: str, root: Path) -> AgentRuntime:
    return runtime_for_role(role, root, execution_root=root)


class CorkboardGenerationManager:
    """Run and retain background corkboard generation jobs."""

    def __init__(
        self,
        runtime_factory: RuntimeFactory = _default_runtime_factory,
    ) -> None:
        self.runtime_factory = runtime_factory
        self.lock = threading.RLock()
        self.jobs: dict[str, CorkboardGenerationJob] = {}

    def start(
        self,
        services: ServiceServices,
        provider: CorkboardProvider,
        context_id: str,
        payload: dict[str, object],
        *,
        connection_id: str = "",
    ) -> dict[str, object]:
        context = services.contexts.require(context_id)
        workflow_id = str(context.workflow_id or "")
        if not callable(getattr(provider, "create_generated_board", None)):
            raise StateError(
                "corkboard provider does not support generation: "
                f"{provider.provider_id}"
            )
        passes = {item["id"]: item for item in generation_passes(workflow_id)}
        pass_id = str(payload.get("pass") or "").strip()
        if pass_id not in passes:
            raise StateError(
                f"unknown corkboard generation pass: {pass_id or 'missing'}"
            )
        root = services.contexts.active_project_root(context_id).resolve()
        requested_scope = payload.get("scope")
        if not isinstance(requested_scope, dict):
            raise StateError("corkboard generation scope is required")
        scope_type = str(requested_scope.get("type") or "").strip()
        if scope_type == "file":
            scope = {
                "type": "file",
                "path": _safe_source_path(root, requested_scope.get("path")),
            }
            manifest = [scope["path"]]
        elif scope_type == "project":
            scope = {"type": "project", "path": ""}
            manifest = _project_manifest(root, workflow_id)
        else:
            raise StateError(
                f"unknown corkboard generation scope: {scope_type or 'missing'}"
            )
        title = str(payload.get("title") or "").strip()[:200]
        title = title or _default_title(scope, passes[pass_id])
        board_id = _board_id(
            provider,
            context_id,
            title,
            connection_id=connection_id,
        )
        job = CorkboardGenerationJob(
            id=uuid4().hex,
            context_id=context_id,
            workflow_id=workflow_id,
            provider_id=provider.provider_id,
            scope=scope,
            pass_id=pass_id,
            title=title,
            board_id=board_id,
        )
        with self.lock:
            if any(
                current.context_id == context_id
                and current.status in {"queued", "running"}
                for current in self.jobs.values()
            ):
                raise StateError("a corkboard generation is already running")
            self.jobs[job.id] = job
            self._trim_jobs()
        thread = threading.Thread(
            target=self._run,
            args=(
                services,
                provider,
                job,
                root,
                passes[pass_id],
                manifest,
                connection_id,
            ),
            name=f"corkboard-generation-{job.id[:8]}",
            daemon=True,
        )
        thread.start()
        return job.payload()

    def get(self, context_id: str, job_id: str) -> dict[str, object]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job.context_id != context_id:
                raise StateError("corkboard generation job was not found")
            return job.payload()

    def _update(self, job: CorkboardGenerationJob, **values: object) -> None:
        with self.lock:
            for key, value in values.items():
                setattr(job, key, value)
            job.updated_at = _utc_now()

    def _run(
        self,
        services: ServiceServices,
        provider: CorkboardProvider,
        job: CorkboardGenerationJob,
        root: Path,
        pass_definition: dict[str, str],
        manifest: list[str],
        connection_id: str,
    ) -> None:
        try:
            self._update(job, status="running", step="Analyzing source", progress=25)
            runtime = self.runtime_factory("corkboard_generation", root)
            result = runtime.invoke(
                AgentInvocation(
                    role="corkboard_generation",
                    prompt=_prompt(
                        job.workflow_id,
                        job.scope,
                        pass_definition,
                        manifest,
                    ),
                    context_paths=(
                        [str(root / job.scope["path"])]
                        if job.scope["type"] == "file"
                        else [str(root)]
                    ),
                )
            )
            if not result.ok:
                raise StateError(
                    result.error or result.final_message or "corkboard agent failed"
                )
            self._update(job, step="Validating plan", progress=70)
            plan = _json_plan(result)
            cards, connectors = normalize_generation_plan(
                root,
                plan,
                default_source=job.scope.get("path", ""),
            )
            self._update(job, step="Laying out cards", progress=82)
            current_root = services.contexts.active_project_root(
                job.context_id
            ).resolve()
            if current_root != root:
                raise StateError("active project changed during corkboard generation")
            self._update(job, step="Saving corkboard", progress=92)
            created = provider.create_generated_board(
                job.context_id,
                job.board_id,
                title=job.title,
                cards=cards,
                connectors=connectors,
                connection_id=connection_id,
            )
            self._update(
                job,
                status="complete",
                step="Complete",
                progress=100,
                result={
                    **created,
                    "card_count": len(cards),
                    "connector_count": len(connectors),
                },
            )
        except Exception as error:
            self._update(
                job,
                status="failed",
                step="Failed",
                progress=100,
                error=str(error),
            )

    def _trim_jobs(self) -> None:
        if len(self.jobs) <= 100:
            return
        completed = [
            job_id
            for job_id, job in self.jobs.items()
            if job.status in {"complete", "failed"}
        ]
        for job_id in completed[: len(self.jobs) - 100]:
            self.jobs.pop(job_id, None)


GENERATION_MANAGER = CorkboardGenerationManager()
