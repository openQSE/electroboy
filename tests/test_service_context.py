from __future__ import annotations

from pathlib import Path

from electroboy.service.app import ServiceState
from electroboy.service.context import BrowserContext, ContextStore


def test_context_compatibility_properties_use_namespaced_state() -> None:
    context = BrowserContext(context_id="tab-1")
    requirements_session = object()
    shell_session = object()

    context.requirements_session = requirements_session  # type: ignore[assignment]
    context.requirements_started = True
    context.project_shell_session = shell_session  # type: ignore[assignment]

    assert context.workflow_state == {
        "software": {
            "requirements_session": requirements_session,
            "requirements_started": True,
        }
    }
    assert context.module_state == {
        "project_shell": {"session": shell_session}
    }


def test_project_reset_switches_workflow_without_cross_workflow_fields() -> None:
    context = BrowserContext(context_id="tab-1")
    context.requirements_started = True

    context.reset_project(
        workflow_id="creative-writing",
        project_mode="creative",
        activation_root=Path("/tmp/story"),
        active_project_root=Path("/tmp/story"),
        workflow_stage="project",
    )

    assert context.workflow_id == "creative-writing"
    assert context.workflow_state == {
        "creative-writing": {"stage": "project"}
    }
    assert context.module_state == {}
    assert context.requirements_started is False


def test_context_store_owns_context_lifecycle() -> None:
    store = ContextStore()

    context = store.create("tab-1")

    assert store.get("tab-1") is context
    assert store.require("tab-1") is context
    assert store.get_or_create("tab-1") is context


def test_service_module_state_uses_declared_namespace(tmp_path: Path) -> None:
    state = ServiceState(tmp_path)
    payload = state.create_context()
    context_id = str(payload["context_id"])

    module_state = state.module_context_state(context_id, "project_shell")
    module_state["visible"] = True

    context = state.context_store.require(context_id)
    assert context.module_state["project_shell"] == {"visible": True}
