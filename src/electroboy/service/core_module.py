"""Core service module contribution."""

from __future__ import annotations

import json
import time
from http import HTTPStatus

from .http import HtmlResponse, JsonResponse, ServiceResponse
from .registry import (
    RouteDefinition,
    ServiceModule,
    build_module_registry,
    build_workflow_registry,
    installed_workflow_factories,
    registry_payload,
)
from .routes import RouteRequest
from .workflow_config import (
    add_configured_workflow,
    configured_workflows,
    workflow_config_payload,
)


FRONTEND_DEBUG_LOG_LIMIT_BYTES = 5_000_000
FRONTEND_DEBUG_PAYLOAD_LIMIT_BYTES = 40_000


def _route(method: str, path: str, handler_name: str) -> RouteDefinition:
    return RouteDefinition(method, path, "core", handler_name)


def _conflict(error: Exception) -> JsonResponse:
    return JsonResponse({"error": str(error)}, status=HTTPStatus.CONFLICT)


def _index(request: RouteRequest) -> HtmlResponse:
    return HtmlResponse(request.operations.service_index())


def _health(request: RouteRequest) -> JsonResponse:
    return JsonResponse(request.operations.health_payload())


def _create_context(request: RouteRequest) -> JsonResponse:
    payload = request.body()
    return JsonResponse(
        request.services.contexts.create(
            str(payload.get("connection_id") or ""),
            str(payload.get("workflow_id") or ""),
        )
    )


def _workspaces(request: RouteRequest) -> JsonResponse:
    workflow_id = str((request.params.get("workflow_id") or [""])[0])
    return JsonResponse(request.services.workspaces.payload(workflow_id))


def _attach_workspace(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = request.services.workspaces.attach(
            request.workspace_id,
            str(payload.get("workspace_id") or ""),
            str(payload.get("connection_id") or request.connection_id),
            str(payload.get("lease_token") or request.lease_token),
        )
    except Exception as error:
        return _conflict(error)
    return JsonResponse(result)


def _detach_workspace(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = request.services.workspaces.detach(
            request.workspace_id,
            str(payload.get("connection_id") or request.connection_id),
            str(payload.get("lease_token") or request.lease_token),
        )
    except Exception as error:
        return _conflict(error)
    return JsonResponse(result)


def _close_workspace(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        request.services.workspaces.close(
            request.workspace_id,
            str(payload.get("connection_id") or request.connection_id),
            str(payload.get("lease_token") or request.lease_token),
        )
    except Exception as error:
        return _conflict(error)
    return JsonResponse({"status": "closed", "workspace_id": request.workspace_id})


def _heartbeat_workspace(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = request.services.workspaces.heartbeat(
            request.workspace_id,
            str(payload.get("connection_id") or request.connection_id),
            str(payload.get("lease_token") or request.lease_token),
        )
    except Exception as error:
        return _conflict(error)
    return JsonResponse(result)


def _save_workspace_state(request: RouteRequest) -> ServiceResponse:
    try:
        result = request.services.workspaces.save_client_state(
            request.workspace_id,
            request.body(),
        )
    except Exception as error:
        return _conflict(error)
    return JsonResponse({"status": "saved", "state": result})


def _frontend_debug(request: RouteRequest) -> ServiceResponse:
    payload = request.body()
    encoded_payload = json.dumps(payload, sort_keys=True, default=str)
    if len(encoded_payload.encode("utf-8")) > FRONTEND_DEBUG_PAYLOAD_LIMIT_BYTES:
        payload = {
            "truncated": True,
            "payload_bytes": len(encoded_payload.encode("utf-8")),
        }
    entry = {
        "received_at": time.time(),
        "payload": payload,
    }
    log_path = (
        request.config.state_root
        / ".electroboy"
        / "service"
        / "frontend-debug.jsonl"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists() and log_path.stat().st_size > FRONTEND_DEBUG_LOG_LIMIT_BYTES:
        previous_size = log_path.stat().st_size
        log_path.write_text(
            json.dumps(
                {
                    "received_at": time.time(),
                    "payload": {
                        "reason": "log-truncated",
                        "previous_bytes": previous_size,
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True, default=str))
        handle.write("\n")
    return JsonResponse({"status": "recorded"})


def _project_payload(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.contexts.project_payload(request.context_id)
    except Exception as error:
        return _conflict(error)
    return JsonResponse(payload)


def _project_status(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.contexts.project_status_payload(
            request.context_id
        )
    except Exception as error:
        return _conflict(error)
    return JsonResponse(payload)


def _deactivate_project(request: RouteRequest) -> ServiceResponse:
    try:
        body = request.body()
        payload = request.services.contexts.deactivate_project(
            request.context_id,
            terminate_agents=body.get("terminate_agents") is True,
        )
        if request.connection_id:
            replacement = request.services.contexts.create(
                request.connection_id,
                str(payload.get("workflow_id") or ""),
            )
            payload = {**replacement, "status": "deactivated"}
    except Exception as error:
        return _conflict(error)
    return JsonResponse(payload)


def _workflow_payload(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.contexts.workflow_payload(request.context_id)
    except Exception as error:
        return _conflict(error)
    return JsonResponse(payload)


def _set_workflow_stage(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = request.services.workflows.select_stage(
            request.context_id,
            str(payload.get("stage") or ""),
        )
    except Exception as error:
        return _conflict(error)
    return JsonResponse(result)


def _workflow_config(request: RouteRequest) -> JsonResponse:
    return JsonResponse(workflow_config_payload(request.config.state_root))


def _registry(request: RouteRequest) -> JsonResponse:
    modules = request.config.module_registry
    workflows = request.config.workflow_registry
    if modules is None or workflows is None:
        return JsonResponse(
            {"error": "service registry is not configured"},
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
        )
    return JsonResponse(
        {
            **registry_payload(modules, workflows),
            "frontend_bundles": request.operations.frontend_asset_payload(),
            "workflow_config": workflow_config_payload(request.config.state_root),
        }
    )


def _add_configured_workflow(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        workflow_id = str(payload.get("id") or "")
        factory = str(payload.get("factory") or "")
        workflow_config = add_configured_workflow(
            request.config.state_root,
            workflow_id,
            factory,
        )
        modules = request.config.module_registry or build_module_registry()
        request.config.workflow_registry = build_workflow_registry(
            modules,
            configured_workflows(
                request.config.state_root,
                installed_workflow_factories(),
            ),
        )
        request.services.workflows.bind_registry(request.config.workflow_registry)
    except (ImportError, AttributeError, TypeError, ValueError) as error:
        return _conflict(error)
    return JsonResponse(
        {
            "status": "added",
            "workflow_config": workflow_config.payload(),
            "registry": registry_payload(
                modules,
                request.config.workflow_registry,
            ),
        }
    )


_HANDLERS = {
    "index": _index,
    "health": _health,
    "create_context": _create_context,
    "workspaces": _workspaces,
    "attach_workspace": _attach_workspace,
    "detach_workspace": _detach_workspace,
    "close_workspace": _close_workspace,
    "heartbeat_workspace": _heartbeat_workspace,
    "save_workspace_state": _save_workspace_state,
    "frontend_debug": _frontend_debug,
    "project_payload": _project_payload,
    "project_status": _project_status,
    "deactivate_project": _deactivate_project,
    "workflow_payload": _workflow_payload,
    "set_workflow_stage": _set_workflow_stage,
    "workflow_config": _workflow_config,
    "registry": _registry,
    "add_configured_workflow": _add_configured_workflow,
}


def module() -> ServiceModule:
    """Return the module that exposes the service shell and workflow registry."""

    return ServiceModule(
        id="core",
        label="Service Core",
        routes=(
            _route("GET", "/", "index"),
            _route("GET", "/index.html", "index"),
            _route("GET", "/api/health", "health"),
            _route("POST", "/api/contexts", "create_context"),
            _route("GET", "/api/workspaces", "workspaces"),
            _route("POST", "/api/workspaces/attach", "attach_workspace"),
            _route("POST", "/api/workspaces/detach", "detach_workspace"),
            _route("POST", "/api/workspaces/close", "close_workspace"),
            _route("POST", "/api/workspaces/heartbeat", "heartbeat_workspace"),
            _route("POST", "/api/workspaces/state", "save_workspace_state"),
            _route("POST", "/api/frontend/debug", "frontend_debug"),
            _route("GET", "/api/project", "project_payload"),
            _route("GET", "/api/project/status", "project_status"),
            _route("POST", "/api/project/deactivate", "deactivate_project"),
            _route("GET", "/api/workflow", "workflow_payload"),
            _route("POST", "/api/workflow/stage", "set_workflow_stage"),
            _route("GET", "/api/workflows/config", "workflow_config"),
            _route("GET", "/api/registry", "registry"),
            _route(
                "POST",
                "/api/workflows/config/workflows",
                "add_configured_workflow",
            ),
        ),
        handlers=_HANDLERS,
        capabilities=frozenset({"context", "project", "workflow-registry"}),
        state_namespace="core",
    )
