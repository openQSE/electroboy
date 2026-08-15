"""Software workflow domain operations and configuration."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from electroboy.artifacts import ArtifactManager
from electroboy.feature_artifacts import read_feature_record
from electroboy.models import (
    STAGE_COMPLETE,
    STAGE_DESIGN,
    STAGE_DESIGN_ACCEPTANCE,
    STAGE_DESIGN_REVIEW,
    STAGE_DOCS_REVIEW,
    STAGE_IMPLEMENTATION,
    STAGE_PLAN,
    STAGE_REQUIREMENTS,
    STAGE_TEST_PLAN,
    STAGE_VALIDATION,
    ActivityEvent,
    utc_now,
)
from electroboy.service.commands import electroboy_command
from electroboy.service.sessions import AgentSessionError
from electroboy.state_store import StateError, StateStore

if TYPE_CHECKING:
    from electroboy.service.context import BrowserContext

_electroboy_command = electroboy_command


def _force_reset_workflow_stage(
    project_root: Path,
    workflow_stage: str,
    target_stage: str,
) -> tuple[str, str]:
    from electroboy.cli import _force_reset_to_stage

    stdout = io.StringIO()
    stderr = io.StringIO()
    store = StateStore(project_root)
    reason = f"Set workflow stage to {workflow_stage} from the GUI."
    with redirect_stdout(stdout), redirect_stderr(stderr):
        decision_id = _force_reset_to_stage(store, target_stage, reason)
    output = "\n".join(
        part.strip()
        for part in [stderr.getvalue(), stdout.getvalue()]
        if part.strip()
    )
    return decision_id, output


WORK_ITEM_REGISTRY_RELATIVE_PATH = Path(".electroboy") / "shared" / "work-items.json"
META_REGISTRY_RELATIVE_PATH = Path(".electroboy") / "shared" / "repositories.json"

WORKFLOW_STAGES = [
    "project",
    "requirements",
    "design",
    "design-review",
    "implementation-plan",
    "code",
    "test-plan",
    "validate",
    "document",
]

APPROVAL_WORKFLOW_STAGES = frozenset(
    {
        "requirements-approve",
        "design-approve",
        "plan-approve",
        "code-approve",
        "test-plan-approve",
        "validation-approve",
    }
)

APPROVAL_STAGE_OWNERS = {
    "requirements-approve": "requirements",
    "design-approve": "design-review",
    "plan-approve": "implementation-plan",
    "code-approve": "code",
    "test-plan-approve": "test-plan",
    "validation-approve": "validate",
}

DURABLE_STAGE_OWNERS = {
    STAGE_DESIGN_ACCEPTANCE: "design-review",
    STAGE_PLAN: "implementation-plan",
    STAGE_IMPLEMENTATION: "code",
    STAGE_TEST_PLAN: "test-plan",
    STAGE_VALIDATION: "validate",
    STAGE_DOCS_REVIEW: "document",
    STAGE_COMPLETE: "document",
}

SESSION_ARTIFACT_LOCKS = {
    "requirements": frozenset({"docs/requirements.md", "docs/requirements.jsonl"}),
    "design": frozenset({"docs/detailed-design.md", "docs/detailed-design.jsonl"}),
    "design-review": frozenset(
        {
            "docs/detailed-design.md",
            "docs/detailed-design.jsonl",
            "design-review.jsonl",
        }
    ),
    "implementation-plan": frozenset(
        {"docs/implementation-plan.md", "docs/implementation-plan.jsonl"}
    ),
    "code": frozenset(
        {
            "docs/implementation-log.md",
            "docs/implementation-report.md",
        }
    ),
    "test-plan": frozenset({"docs/test-plan.md", "docs/test-plan.jsonl"}),
    "validate": frozenset(
        {
            "docs/test-review.md",
            "docs/validation-report.md",
            "validation-test-review.jsonl",
            "validation-review.jsonl",
        }
    ),
    "documentation": frozenset(),
}

GENERIC_STAGE_CONFIG: dict[str, dict[str, object]] = {
    "implementation-plan": {
        "command": "implementation-plan",
        "approval_command": "plan-approve",
        "artifact_path": "docs/implementation-plan.md",
        "artifact_title": "Implementation Plan",
        "interactive_default": True,
        "interactive_arg": False,
        "reason_arg": True,
        "approval_reason_arg": True,
        "next_stage": "code",
    },
    "code": {
        "command": "code",
        "approval_command": "code-approve",
        "artifact_path": "docs/implementation-report.md",
        "artifact_title": "Implementation Report",
        "interactive_default": False,
        "interactive_arg": True,
        "reason_arg": True,
        "approval_reason_arg": False,
        "next_stage": "test-plan",
    },
    "test-plan": {
        "command": "test-plan",
        "approval_command": "test-plan-approve",
        "artifact_path": "docs/test-plan.md",
        "artifact_title": "Test Plan",
        "interactive_default": True,
        "interactive_arg": False,
        "reason_arg": True,
        "approval_reason_arg": True,
        "next_stage": "validate",
    },
    "validate": {
        "command": "validate",
        "approval_command": "validation-approve",
        "artifact_path": "docs/validation-report.md",
        "artifact_title": "Validation Report",
        "interactive_default": False,
        "interactive_arg": True,
        "reason_arg": False,
        "approval_reason_arg": True,
        "next_stage": "document",
    },
}

WORKFLOW_STAGE_RESET_TARGETS = {
    "requirements": STAGE_REQUIREMENTS,
    "design": STAGE_DESIGN,
    "design-review": STAGE_DESIGN_REVIEW,
    "implementation-plan": STAGE_PLAN,
    "code": STAGE_IMPLEMENTATION,
    "test-plan": STAGE_TEST_PLAN,
    "validate": STAGE_VALIDATION,
}


def initialize_project(project_root: Path | str):
    from electroboy.cli import (
        _init_git_repository,
        _write_project_bin,
        _write_project_config,
        _write_project_gitignore,
        _write_project_runtime,
    )

    project_root = Path(project_root).expanduser().resolve()
    project_root.mkdir(parents=True, exist_ok=True)
    _init_git_repository(project_root)
    ArtifactManager(project_root).init_templates()
    _write_project_config(project_root)
    _write_project_gitignore(project_root)
    _write_project_runtime(project_root)
    _write_project_bin(project_root)

    store = StateStore(project_root)
    return store.init_run()


def initialize_meta_project(path: Path | str) -> tuple[Path, dict[str, object]]:
    from electroboy.cli import (
        _meta_registry_file,
        _read_meta_registry,
        _write_meta_environment,
        _write_meta_registry,
    )

    meta_root = _resolve_project_path(str(path))
    meta_root.mkdir(parents=True, exist_ok=True)
    _write_meta_environment(meta_root)
    registry_exists = _meta_registry_file(meta_root).exists()
    registry = _read_meta_registry(meta_root)
    if not registry_exists:
        _write_meta_registry(meta_root, registry)
    return meta_root, registry


def _resolve_project_path(path: str) -> Path:
    path = path.strip()
    if not path:
        raise StateError("project path is required")
    return Path(path).expanduser().resolve()


def _is_meta_project_path(path: str | Path) -> bool:
    try:
        project_root = Path(path).expanduser().resolve()
    except OSError:
        return False
    return (project_root / META_REGISTRY_RELATIVE_PATH).exists()


def _existing_meta_context(path: str | Path) -> dict[str, object]:
    meta_root = _resolve_project_path(str(path))
    if not meta_root.exists():
        raise StateError(f"meta-project directory does not exist: {meta_root}")
    if not meta_root.is_dir():
        raise StateError(f"meta-project path is not a directory: {meta_root}")
    if not _is_meta_project_path(meta_root):
        raise StateError(
            "no ElectroBoy meta-project exists at this path; create it first"
        )
    return _meta_context(meta_root)


def _meta_context(meta_root: Path) -> dict[str, object]:
    from electroboy.cli import _meta_repository_by_name, _read_meta_registry

    registry = _read_meta_registry(meta_root)
    repositories = _meta_repository_payloads(registry)
    active_name = str(registry.get("active") or "")
    active_project_root: Path | None = None
    workflow_stage: str | None = None
    if active_name:
        record = _meta_repository_by_name(registry, active_name)
        if record is not None:
            candidate = Path(str(record.get("path", ""))).expanduser().resolve()
            if (
                candidate.exists()
                and candidate.is_dir()
                and StateStore(candidate).current_run_id()
            ):
                active_project_root = candidate
                workflow_stage = _active_workflow_stage(candidate)
    return {
        "meta_root": meta_root,
        "active_project_root": active_project_root,
        "active_repository_name": active_name or None,
        "registered_repositories": repositories,
        "workflow_stage": workflow_stage,
    }


def _meta_repository_payloads(
    registry: dict[str, object],
) -> list[dict[str, object]]:
    from electroboy.cli import _meta_repositories

    return [
        {
            "name": str(repo.get("name") or ""),
            "path": str(repo.get("path") or ""),
        }
        for repo in _meta_repositories(registry)
    ]


def _add_meta_repository(meta_root: Path, path: str) -> dict[str, object]:
    from electroboy.cli import (
        _read_meta_registry,
        _register_meta_repository,
        _resolve_existing_repo_path,
    )

    registry = _read_meta_registry(meta_root)
    repo_path = _resolve_existing_repo_path(meta_root, path)
    _register_meta_repository(meta_root, repo_path, registry)
    return _meta_context(meta_root)


def _start_meta_repository(meta_root: Path, repository: str) -> dict[str, object]:
    from electroboy.cli import (
        _ensure_target_pipeline_project,
        _read_meta_registry,
        _register_meta_repository,
        _resolve_meta_repository,
        _write_meta_registry,
    )

    repository = repository.strip()
    if not repository:
        raise StateError("repository is required")
    registry = _read_meta_registry(meta_root)
    repo_path, record = _resolve_meta_repository(meta_root, registry, repository)
    registry, record = _register_meta_repository(meta_root, repo_path, registry)
    registry["active"] = record["name"]
    _write_meta_registry(meta_root, registry)
    _ensure_target_pipeline_project(repo_path)
    return _meta_context(meta_root)


def _remove_meta_repository(meta_root: Path, repository: str) -> dict[str, object]:
    from electroboy.cli import (
        _candidate_repo_path,
        _meta_repositories,
        _meta_repository_by_name,
        _read_meta_registry,
        _write_meta_registry,
    )

    repository = repository.strip()
    if not repository:
        raise StateError("repository is required")
    registry = _read_meta_registry(meta_root)
    record = _meta_repository_by_name(registry, repository)
    if record is None:
        candidate_path = _candidate_repo_path(meta_root, repository)
        for repo in _meta_repositories(registry):
            repo_path = Path(str(repo.get("path", ""))).expanduser().resolve()
            if repo_path == candidate_path:
                record = repo
                break
    if record is None:
        raise StateError(f"repository is not registered: {repository}")
    name = str(record.get("name") or "")
    path = Path(str(record.get("path") or "")).expanduser().resolve()
    registry["repositories"] = [
        repo
        for repo in _meta_repositories(registry)
        if str(repo.get("name") or "") != name
        and Path(str(repo.get("path", ""))).expanduser().resolve() != path
    ]
    if registry.get("active") == name:
        registry["active"] = None
    _write_meta_registry(meta_root, registry)
    return _meta_context(meta_root)


def _existing_project_root(path: str) -> Path:
    project_root = _resolve_project_path(path)
    if not project_root.exists():
        raise StateError(f"project directory does not exist: {project_root}")
    if not project_root.is_dir():
        raise StateError(f"project path is not a directory: {project_root}")
    try:
        current_run_id = StateStore(project_root).current_run_id()
    except OSError as error:
        raise StateError(f"could not read ElectroBoy project: {error}") from error
    if not current_run_id:
        raise StateError(
            "no ElectroBoy project exists at this path; create it first"
        )
    return project_root


def _stage_operations(
    stage: str,
    active_project_root: Path | str | None,
) -> list[str]:
    if stage == "project":
        operations = ["Open", "Create"]
        if active_project_root:
            operations.append("Deactivate")
        return operations
    if stage == "requirements" and active_project_root:
        return [
            "Set stage",
            "Start",
            "Approve",
            "Skip approval",
            "Open requirements",
        ]
    if stage == "design" and active_project_root:
        return ["Set stage", "Start", "Complete", "Open design"]
    if stage == "design-review" and active_project_root:
        return [
            "Set stage",
            "Run automatic review",
            "Run interactive review",
            "Stop review",
            "Approve",
            "Skip approval",
        ]
    if stage == "implementation-plan" and active_project_root:
        return [
            "Set stage",
            "Start",
            "Approve",
            "Skip approval",
            "Open implementation plan",
        ]
    if stage == "code" and active_project_root:
        return [
            "Set stage",
            "Start automatic",
            "Start interactive",
            "Stop",
            "Approve",
            "Skip approval",
            "Open implementation report",
        ]
    if stage == "test-plan" and active_project_root:
        return [
            "Set stage",
            "Start",
            "Approve",
            "Skip approval",
            "Open test plan",
        ]
    if stage == "validate" and active_project_root:
        return [
            "Set stage",
            "Start automatic",
            "Start interactive",
            "Stop",
            "Approve",
            "Skip approval",
            "Open validation report",
        ]
    return []


def workflow_payload(
    active_project_root: Path | str | None = None,
) -> dict[str, object]:
    return {
        "stages": [
            {
                "id": stage,
                "label": stage,
                "operations": _stage_operations(stage, active_project_root),
            }
            for stage in WORKFLOW_STAGES
        ]
    }


def project_payload_extension(
    context: "BrowserContext",
    active_root: Path | None,
) -> dict[str, object]:
    requirements_session = context.requirements_session
    design_session = context.design_session
    design_review_session = context.design_review_session
    return {
        "requirements_started": bool(active_root and context.requirements_started),
        "requirements_running": bool(
            active_root
            and requirements_session is not None
            and requirements_session.is_active()
        ),
        "requirements_approved": bool(
            active_root
            and _stage_has_approvals(
                active_root,
                STAGE_REQUIREMENTS,
                ["human-approval", "author-confirmation"],
            )
        ),
        "design_started": bool(active_root and context.design_started),
        "design_running": bool(
            active_root and design_session is not None and design_session.is_active()
        ),
        "design_review_started": bool(
            active_root and context.design_review_started
        ),
        "design_review_running": bool(
            active_root
            and design_review_session is not None
            and design_review_session.is_active()
        ),
        "design_review_interactive": bool(
            active_root
            and design_review_session is not None
            and design_review_session.is_active()
            and context.design_review_interactive
        ),
        "stage_runs": (
            _generic_stage_run_payload(context, active_root) if active_root else {}
        ),
        "design_approved": bool(
            active_root
            and _stage_has_approvals(
                active_root,
                STAGE_DESIGN_ACCEPTANCE,
                ["human-approval"],
            )
        ),
        "work_items": (
            _work_item_payload(active_root)
            if active_root
            else _empty_work_item_payload()
        ),
    }


def _generic_stage_run_payload(
    context: Any,
    active_root: Path | None,
) -> dict[str, dict[str, object]]:
    payload: dict[str, dict[str, object]] = {}
    for stage in GENERIC_STAGE_CONFIG:
        session = context.stage_sessions.get(stage)
        running = bool(active_root and session is not None and session.is_active())
        payload[stage] = {
            "started": bool(active_root and stage in context.stage_started),
            "running": running,
            "interactive": bool(
                running and session is not None and session.interactive
            ),
        }
    return payload


def _empty_work_item_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "active_collection_id": None,
        "active_feature_slug": None,
        "active_bug_slug": None,
        "collections": [],
        "features": [],
        "bugs": [],
    }


def _work_item_payload(project_root: Path) -> dict[str, object]:
    registry = _load_work_item_registry(project_root)
    feature = _current_feature_record(project_root)
    bug = _current_bug_record(project_root)
    if feature is not None:
        existing = _feature_by_slug(registry, str(feature.get("slug") or ""))
        collection = _ensure_collection_for_feature(
            registry,
            (
                str(existing.get("collection_id"))
                if existing and existing.get("collection_id")
                else None
            ),
            parent_slug=(
                str(existing.get("parent_slug"))
                if existing and existing.get("parent_slug")
                else None
            ),
        )
        _upsert_feature_record(
            registry,
            feature,
            collection_id=str(collection["id"]),
            parent_slug=(
                str(existing.get("parent_slug"))
                if existing and existing.get("parent_slug")
                else None
            ),
        )
        registry["active_collection_id"] = collection["id"]
        registry["active_feature_slug"] = feature.get("slug")
    if bug is not None:
        _upsert_bug_record(registry, bug)
        registry["active_bug_slug"] = bug.get("slug")
    return {
        "schema_version": 1,
        "active_collection_id": registry.get("active_collection_id"),
        "active_feature_slug": registry.get("active_feature_slug"),
        "active_bug_slug": registry.get("active_bug_slug"),
        "collections": _registry_list(registry, "collections"),
        "features": _registry_list(registry, "features"),
        "bugs": _registry_list(registry, "bugs"),
    }


def _registry_list(
    registry: dict[str, object],
    key: str,
) -> list[dict[str, object]]:
    values = registry.get(key)
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def _load_work_item_registry(project_root: Path) -> dict[str, object]:
    path = project_root / WORK_ITEM_REGISTRY_RELATIVE_PATH
    if not path.exists():
        return {
            **_empty_work_item_payload(),
            "collections": [_default_feature_collection()],
            "active_collection_id": "default",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    registry = {
        **_empty_work_item_payload(),
        **data,
    }
    collections = _registry_list(registry, "collections")
    if not collections:
        collections = [_default_feature_collection()]
    elif _feature_collection_by_id(registry, "default") is None:
        collections.insert(0, _default_feature_collection())
    registry["collections"] = collections
    registry["features"] = _registry_list(registry, "features")
    registry["bugs"] = _registry_list(registry, "bugs")
    if not registry.get("active_collection_id"):
        registry["active_collection_id"] = collections[0].get("id")
    return registry


def _save_work_item_registry(project_root: Path, registry: dict[str, object]) -> None:
    path = project_root / WORK_ITEM_REGISTRY_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _default_feature_collection() -> dict[str, object]:
    return {
        "id": "default",
        "name": "Default",
        "feature_slugs": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def _upsert_feature_collection(
    registry: dict[str, object],
    name: str,
) -> dict[str, object]:
    collections = _registry_list(registry, "collections")
    collection_id = _slugify_work_item(name)
    existing = _feature_collection_by_id(registry, collection_id)
    if existing is not None:
        existing["name"] = name
        existing["updated_at"] = utc_now()
        return existing
    collection = {
        "id": collection_id,
        "name": name,
        "feature_slugs": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    collections.append(collection)
    registry["collections"] = collections
    return collection


def _feature_collection_by_id(
    registry: dict[str, object],
    collection_id: str,
) -> dict[str, object] | None:
    for collection in _registry_list(registry, "collections"):
        if collection.get("id") == collection_id:
            return collection
    return None


def _ensure_collection_for_feature(
    registry: dict[str, object],
    collection_id: str | None,
    *,
    parent_slug: str | None = None,
) -> dict[str, object]:
    if collection_id:
        collection = _feature_collection_by_id(registry, collection_id)
        if collection is not None:
            return collection
    if parent_slug:
        parent = _feature_by_slug(registry, parent_slug)
        if parent and parent.get("collection_id"):
            collection = _feature_collection_by_id(
                registry,
                str(parent.get("collection_id")),
            )
            if collection is not None:
                return collection
    active_id = registry.get("active_collection_id")
    if active_id:
        collection = _feature_collection_by_id(registry, str(active_id))
        if collection is not None:
            return collection
    collections = _registry_list(registry, "collections")
    if collections:
        return collections[0]
    collection = _default_feature_collection()
    registry["collections"] = [collection]
    registry["active_collection_id"] = collection["id"]
    return collection


def _feature_by_slug(
    registry: dict[str, object],
    slug: str,
) -> dict[str, object] | None:
    for feature in _registry_list(registry, "features"):
        if feature.get("slug") == slug:
            return feature
    return None


def _bug_by_slug(
    registry: dict[str, object],
    slug: str,
) -> dict[str, object] | None:
    for bug in _registry_list(registry, "bugs"):
        if bug.get("slug") == slug:
            return bug
    return None


def _upsert_feature_record(
    registry: dict[str, object],
    record: dict[str, object],
    *,
    collection_id: str,
    parent_slug: str | None,
) -> None:
    slug = str(record.get("slug") or "").strip()
    if not slug:
        return
    features = [
        feature
        for feature in _registry_list(registry, "features")
        if feature.get("slug") != slug
    ]
    feature = dict(record)
    feature["collection_id"] = collection_id
    feature["parent_slug"] = parent_slug
    feature["updated_at"] = utc_now()
    features.append(feature)
    registry["features"] = sorted(
        features,
        key=lambda item: str(item.get("name") or item.get("slug") or ""),
    )
    collection = _ensure_collection_for_feature(registry, collection_id)
    feature_slugs = [
        value
        for value in collection.get("feature_slugs", [])
        if isinstance(value, str) and value != slug
    ]
    feature_slugs.append(slug)
    collection["feature_slugs"] = feature_slugs
    collection["updated_at"] = utc_now()


def _upsert_bug_record(
    registry: dict[str, object],
    record: dict[str, object],
) -> None:
    slug = str(record.get("slug") or "").strip()
    if not slug:
        return
    bugs = [
        bug
        for bug in _registry_list(registry, "bugs")
        if bug.get("slug") != slug
    ]
    bug = dict(record)
    bug["updated_at"] = utc_now()
    bugs.append(bug)
    registry["bugs"] = sorted(
        bugs,
        key=lambda item: str(item.get("title") or item.get("slug") or ""),
    )


def _current_feature_record(project_root: Path) -> dict[str, object] | None:
    store = StateStore(project_root)
    run_id = store.current_run_id()
    if not run_id:
        return None
    return read_feature_record(project_root, run_id)


def _current_bug_record(project_root: Path) -> dict[str, object] | None:
    store = StateStore(project_root)
    run_id = store.current_run_id()
    if not run_id:
        return None
    path = store.run_dir(run_id) / "bug.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _write_current_bug_record(project_root: Path, record: dict[str, object]) -> None:
    store = StateStore(project_root)
    run_id = store.current_run_id()
    if not run_id:
        raise StateError("project has no active run")
    path = store.run_dir(run_id) / "bug.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _feature_record_label(record: dict[str, object] | None) -> str:
    if not record:
        return "feature"
    return str(
        record.get("name")
        or record.get("title")
        or record.get("slug")
        or "feature"
    )


def _bug_record_label(record: dict[str, object] | None) -> str:
    if not record:
        return "bug"
    return str(record.get("title") or record.get("slug") or "bug")


def _run_feature_start_context(
    project_root: Path,
    *,
    title: str,
    feature_name: str | None,
    amend: bool,
    branch: bool,
    stash_subrepo_changes: bool = False,
    branch_name: str | None = None,
) -> str:
    from electroboy.cli import _cmd_feature_start

    args = SimpleNamespace(
        title_or_issue_url=title,
        feature_name=feature_name,
        amend=amend,
        branch=(branch_name or "") if branch else None,
        stash_subrepo_changes=stash_subrepo_changes,
    )
    return _run_orchestrator_command(project_root, _cmd_feature_start, args)


def _run_bug_start_context(
    project_root: Path,
    *,
    issue_reference: str,
    branch: bool,
    stash_subrepo_changes: bool = False,
) -> str:
    from electroboy.cli import _cmd_bug_start

    args = SimpleNamespace(
        issue_reference=issue_reference,
        provider=None,
        branch="" if branch else None,
        stash_subrepo_changes=stash_subrepo_changes,
    )
    return _run_orchestrator_command(project_root, _cmd_bug_start, args)


def _run_orchestrator_command(
    project_root: Path,
    command: Callable[[StateStore, Any], int],
    args: Any,
) -> str:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = command(StateStore(project_root), args)
    output = "\n".join(
        part.strip()
        for part in [stderr.getvalue(), stdout.getvalue()]
        if part.strip()
    )
    if code != 0:
        raise AgentSessionError(output or "work item command failed")
    return output


def _run_electroboy_cli_command(project_root: Path, args: list[str]) -> str:
    from electroboy.cli import main

    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(["--root", str(project_root), *args])
    output = "\n".join(
        part.strip()
        for part in [stderr.getvalue(), stdout.getvalue()]
        if part.strip()
    )
    if code != 0:
        raise AgentSessionError(output or f"electroboy {' '.join(args)} failed")
    return output


def _work_item_error_payload(error: BaseException) -> dict[str, object]:
    message = str(error)
    payload: dict[str, object] = {"error": message}
    if "nested repository changes require stashing" in message:
        payload["stash_subrepo_changes_required"] = True
    return payload


def _generic_stage_config(stage: str) -> dict[str, object]:
    try:
        return GENERIC_STAGE_CONFIG[stage]
    except KeyError as error:
        raise AgentSessionError(f"unsupported workflow stage: {stage}") from error


def _stage_display_label(stage: str) -> str:
    return str(
        _generic_stage_config(stage).get("artifact_title")
        or stage.replace("-", " ")
    ).lower()


def _generic_stage_command(
    root: Path,
    stage: str,
    *,
    force: bool = False,
    reason: str | None = None,
    interactive: bool = False,
) -> list[str]:
    config = _generic_stage_config(stage)
    command_parts = [str(config["command"])]
    if force:
        command_parts.append("--force")
    if reason and bool(config.get("reason_arg")):
        command_parts.extend(["--reason", reason])
    if interactive and bool(config.get("interactive_arg")):
        command_parts.append("--interactive")
    return _electroboy_command(root, command_parts)


def _generic_agent_route(path: str) -> tuple[str, str] | None:
    prefix = "/api/agents/"
    if not path.startswith(prefix):
        return None
    suffix = path[len(prefix):]
    for stage in GENERIC_STAGE_CONFIG:
        stage_prefix = f"{stage}/"
        if suffix.startswith(stage_prefix):
            return stage, suffix[len(stage_prefix):]
    return None


def _slugify_work_item(value: str) -> str:
    chars: list[str] = []
    previous_dash = False
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
            previous_dash = False
            continue
        if not previous_dash:
            chars.append("-")
            previous_dash = True
    slug = "".join(chars).strip("-")
    return slug or "default"


def _visible_workflow_stage(stage: str) -> str:
    return DURABLE_STAGE_OWNERS.get(stage, APPROVAL_STAGE_OWNERS.get(stage, stage))


def _active_workflow_stage(project_root: Path | str) -> str:
    try:
        manifest = StateStore(project_root).load_current_manifest()
    except OSError as error:
        raise StateError(f"could not read ElectroBoy project: {error}") from error
    return _visible_workflow_stage(manifest.active_stage)


def _stage_has_approvals(
    project_root: Path | str,
    stage: str,
    approval_types: list[str],
) -> bool:
    try:
        approvals = StateStore(project_root).read_approvals()
    except (OSError, StateError):
        return False
    return all(
        any(
            approval.get("stage") == stage
            and approval.get("approval_type") == approval_type
            for approval in approvals
        )
        for approval_type in approval_types
    )


def _reopen_requirements_for_restart(project_root: Path) -> None:
    store = StateStore(project_root)
    manifest = store.load_current_manifest()
    from electroboy.cli import _is_backward_stage_request, _record_stage_reopen

    if _is_backward_stage_request(manifest.active_stage, STAGE_REQUIREMENTS):
        _record_stage_reopen(
            store=store,
            manifest=manifest,
            target_stage=STAGE_REQUIREMENTS,
            reason="Requirements authoring restarted from the GUI.",
            actor="human-operator",
            action="gui-requirements-restarted",
            summary="Reopened requirements authoring from the GUI.",
        )
        return
    store.append_activity(
        ActivityEvent(
            actor="human-operator",
            stage=STAGE_REQUIREMENTS,
            action="gui-requirements-restarted",
            summary="Restarted requirements authoring from the GUI.",
        )
    )


def _reopen_design_for_restart(project_root: Path) -> None:
    store = StateStore(project_root)
    manifest = store.load_current_manifest()
    from electroboy.cli import _is_backward_stage_request, _record_stage_reopen

    if _is_backward_stage_request(manifest.active_stage, STAGE_DESIGN):
        _record_stage_reopen(
            store=store,
            manifest=manifest,
            target_stage=STAGE_DESIGN,
            reason="Design authoring restarted from the GUI.",
            actor="human-operator",
            action="gui-design-restarted",
            summary="Reopened design authoring from the GUI.",
        )
        return
    store.append_activity(
        ActivityEvent(
            actor="human-operator",
            stage=STAGE_DESIGN,
            action="gui-design-restarted",
            summary="Restarted design authoring from the GUI.",
        )
    )


def _record_requirements_complete(project_root: Path, *, skipped: bool = False) -> None:
    store = StateStore(project_root)
    manifest = store.load_current_manifest()
    action = (
        "gui-requirements-approval-skipped"
        if skipped
        else "gui-requirements-authoring-completed"
    )
    summary = (
        "Skipped explicit requirements approval from the GUI and advanced "
        "with a forced approval warning."
        if skipped
        else "Completed requirements authoring and approved the requirements baseline."
    )
    store.append_activity(
        ActivityEvent(
            actor="human-operator",
            stage=STAGE_REQUIREMENTS,
            action=action,
            summary=summary,
            inputs=[manifest.active_stage],
        )
    )


def _record_design_complete(project_root: Path) -> None:
    store = StateStore(project_root)
    manifest = store.load_current_manifest()
    store.append_activity(
        ActivityEvent(
            actor="human-operator",
            stage=STAGE_DESIGN,
            action="gui-design-authoring-completed",
            summary="Completed design authoring and moved to design review.",
            inputs=[manifest.active_stage],
        )
    )


def _should_force_completed_requirements_approval(store: StateStore) -> bool:
    from electroboy.cli import _has_successful_agent_event

    if _has_successful_agent_event(store, "design_author", STAGE_REQUIREMENTS):
        return False
    completion_actions = {
        "gui-requirements-authoring-completed",
        "gui-requirements-authoring-skipped",
        "gui-requirements-approval-skipped",
    }
    return any(
        event.get("actor") == "human-operator"
        and event.get("stage") == STAGE_REQUIREMENTS
        and event.get("action") in completion_actions
        for event in store.read_activity()
    )


def _requirements_command(root: Path) -> list[str]:
    return _electroboy_command(root, ["requirements"])


def _stage_command(
    root: Path,
    command: str,
    *,
    force: bool = False,
    reason: str | None = None,
    interactive: bool = False,
) -> list[str]:
    command_parts = ["electroboy", command]
    if force:
        command_parts.append("--force")
    if reason:
        command_parts.extend(["--reason", reason])
    if interactive:
        command_parts.append("--interactive")
    return _electroboy_command(root, command_parts[1:])


def _documentation_command(
    root: Path,
    *,
    interactive: bool = True,
    target: str | None = None,
) -> list[str]:
    args = ["document", "--sidecar"]
    if interactive:
        args.append("--interactive")
    if target:
        args.extend(["--target", target])
    return _electroboy_command(root, args)
