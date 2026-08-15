"""Persistent workflow configuration for the browser service."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .registry import WorkflowDefinition, installed_workflow_factories

ENTRY_POINT_FACTORY_PREFIX = "entry-point:"

DEFAULT_WORKFLOW_IDS = ("software", "creative-writing")
WORKFLOW_CONFIG_RELATIVE_PATH = Path(".electroboy") / "service" / "workflows.json"


@dataclass(frozen=True)
class WorkflowFactoryReference:
    """Importable workflow factory saved in service configuration."""

    id: str
    factory: str

    def payload(self) -> dict[str, str]:
        return {"id": self.id, "factory": self.factory}


@dataclass(frozen=True)
class WorkflowConfig:
    """Enabled built-ins and extra workflow factories."""

    enabled_builtins: tuple[str, ...] = DEFAULT_WORKFLOW_IDS
    extra_workflows: tuple[WorkflowFactoryReference, ...] = ()

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "enabled_builtins": list(self.enabled_builtins),
            "extra_workflows": [
                workflow.payload() for workflow in self.extra_workflows
            ],
        }


def workflow_config_path(service_root: Path | str) -> Path:
    """Return the persisted workflow configuration path for a service root."""

    return Path(service_root).expanduser().resolve() / WORKFLOW_CONFIG_RELATIVE_PATH


def load_workflow_config(service_root: Path | str) -> WorkflowConfig:
    """Load service workflow configuration, defaulting to built-ins."""

    path = workflow_config_path(service_root)
    if not path.exists():
        return WorkflowConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return WorkflowConfig()
    enabled_builtins = _string_tuple(
        data.get("enabled_builtins"),
        DEFAULT_WORKFLOW_IDS,
    )
    extra_workflows = tuple(
        WorkflowFactoryReference(
            id=str(entry.get("id") or "").strip(),
            factory=str(entry.get("factory") or "").strip(),
        )
        for entry in data.get("extra_workflows", [])
        if isinstance(entry, dict)
        and str(entry.get("id") or "").strip()
        and str(entry.get("factory") or "").strip()
    )
    return WorkflowConfig(
        enabled_builtins=enabled_builtins,
        extra_workflows=extra_workflows,
    )


def save_workflow_config(service_root: Path | str, config: WorkflowConfig) -> Path:
    """Persist service workflow configuration."""

    path = workflow_config_path(service_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.payload(), indent=2, sort_keys=True) + "\n")
    return path


def add_configured_workflow(
    service_root: Path | str,
    workflow_id: str,
    factory: str,
) -> WorkflowConfig:
    """Add or replace an extra workflow factory in persisted configuration."""

    normalized_id = workflow_id.strip()
    normalized_factory = factory.strip()
    if not normalized_id:
        raise ValueError("workflow id is required")
    if not normalized_factory:
        normalized_factory = f"{ENTRY_POINT_FACTORY_PREFIX}{normalized_id}"
    available = installed_workflow_factories()
    _load_workflow_factory(normalized_factory, available)
    config = load_workflow_config(service_root)
    references = [
        reference
        for reference in config.extra_workflows
        if reference.id != normalized_id
    ]
    references.append(
        WorkflowFactoryReference(id=normalized_id, factory=normalized_factory)
    )
    updated = WorkflowConfig(
        enabled_builtins=config.enabled_builtins,
        extra_workflows=tuple(references),
    )
    save_workflow_config(service_root, updated)
    return updated


def configured_workflows(
    service_root: Path | str,
    builtins: dict[str, Callable[[], WorkflowDefinition]],
) -> tuple[WorkflowDefinition, ...]:
    """Return built-in defaults plus persisted extra workflow definitions."""

    config = load_workflow_config(service_root)
    workflows: list[WorkflowDefinition] = []
    for workflow_id in config.enabled_builtins:
        factory = builtins.get(workflow_id)
        if factory is not None:
            workflows.append(factory())
    for reference in config.extra_workflows:
        factory = _load_workflow_factory(reference.factory, builtins)
        workflow = factory()
        if workflow.id != reference.id:
            raise ValueError(
                "configured workflow id does not match factory output: "
                f"{reference.id} != {workflow.id}"
            )
        workflows.append(workflow)
    return tuple(workflows)


def workflow_config_payload(service_root: Path | str) -> dict[str, object]:
    """Return the persisted workflow configuration and path."""

    config = load_workflow_config(service_root)
    installed = installed_workflow_factories()
    return {
        **config.payload(),
        "path": str(workflow_config_path(service_root)),
        "installed_workflows": [
            {
                "id": workflow_id,
                "provider": factory.provider,
                "entry_point": factory.reference,
                "enabled": workflow_id in config.enabled_builtins
                or any(
                    reference.id == workflow_id
                    for reference in config.extra_workflows
                ),
            }
            for workflow_id, factory in installed.items()
        ],
    }


def _string_tuple(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return default
    values = tuple(str(entry).strip() for entry in value if str(entry).strip())
    return values or default


def _load_workflow_factory(
    factory_reference: str,
    installed: dict[str, Callable[[], WorkflowDefinition]] | None = None,
) -> Callable[[], WorkflowDefinition]:
    if factory_reference.startswith(ENTRY_POINT_FACTORY_PREFIX):
        workflow_id = factory_reference.removeprefix(ENTRY_POINT_FACTORY_PREFIX)
        available = installed or installed_workflow_factories()
        try:
            return available[workflow_id]
        except KeyError as error:
            raise ValueError(
                f"installed workflow entry point was not found: {workflow_id}"
            ) from error
    module_name, separator, attribute = factory_reference.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("workflow factory must use the form module.path:callable")
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute)
    if not callable(factory):
        raise ValueError(f"workflow factory is not callable: {factory_reference}")
    return factory
