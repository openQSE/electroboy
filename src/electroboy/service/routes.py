"""HTTP route dispatch primitives for the browser service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs

from .http import JsonResponse, ServiceResponse
from .registry import (
    ModuleRegistry,
    RouteDefinition,
    RouteHandler,
    WorkflowRegistry,
)
from .sessions import AgentSession
from .services import ServiceServices


class RouteServiceConfig(Protocol):
    """Immutable server configuration visible to route handlers."""

    root: Path
    state_root: Path
    module_registry: ModuleRegistry | None
    workflow_registry: WorkflowRegistry | None


class RouteTransport(Protocol):
    """Public transport adapter used by transport-neutral routes."""

    def read_json_body(self) -> dict[str, object]: ...

    def stream_session_events(self, session: AgentSession) -> None: ...

    def stream_agent_events(self, context_id: str) -> None: ...

    def stream_artifact_events(
        self,
        targets: list[tuple[str, Path]],
    ) -> None: ...

    def stream_progress_events(
        self,
        context_id: str,
        root: Path,
        snapshot: Callable[[Path], tuple[str, bool]],
    ) -> None: ...

    def emit_response(self, response: ServiceResponse) -> None: ...


@dataclass(frozen=True)
class RouteOperations:
    """Typed core operations needed by registered route handlers."""

    service_index_factory: Callable[[], str]
    health_payload_factory: Callable[[], dict[str, object]]
    frontend_asset_payload_factory: Callable[[], list[dict[str, object]]]
    file_browser_factory: Callable[[str, str], str]

    def service_index(self) -> str:
        return self.service_index_factory()

    def health_payload(self) -> dict[str, object]:
        return self.health_payload_factory()

    def frontend_asset_payload(self) -> list[dict[str, object]]:
        return self.frontend_asset_payload_factory()

    def file_browser_window_html(self, path: str, mode: str) -> str:
        return self.file_browser_factory(path, mode)


@dataclass
class RouteRequest:
    """Transport-neutral request passed to module-owned route handlers."""

    method: str
    path: str
    query: str
    services: ServiceServices
    config: RouteServiceConfig
    transport: RouteTransport = field(repr=False)
    operations: RouteOperations = field(repr=False)

    @property
    def params(self) -> dict[str, list[str]]:
        return parse_qs(self.query)

    @property
    def context_id(self) -> str:
        return self.workspace_id

    @property
    def workspace_id(self) -> str:
        return str(
            (
                self.params.get("workspace_id")
                or self.params.get("context_id")
                or [""]
            )[0]
        )

    @property
    def connection_id(self) -> str:
        return str((self.params.get("connection_id") or [""])[0])

    @property
    def lease_token(self) -> str:
        return str((self.params.get("lease_token") or [""])[0])

    def body(self) -> dict[str, object]:
        return self.transport.read_json_body()

    def stream_session_events(self, session: AgentSession) -> None:
        self.transport.stream_session_events(session)

    def stream_agent_events(self) -> None:
        self.transport.stream_agent_events(self.context_id)

    def stream_artifact_events(
        self,
        targets: list[tuple[str, Path]],
    ) -> None:
        self.transport.stream_artifact_events(targets)

    def stream_progress_events(
        self,
        context_id: str,
        root: Path,
        snapshot: Callable[[Path], tuple[str, bool]],
    ) -> None:
        self.transport.stream_progress_events(context_id, root, snapshot)


@dataclass(frozen=True)
class RouteMatch:
    """A registered exact route match."""

    method: str
    path: str
    owner: str
    handler_name: str
    handler: RouteHandler = field(repr=False, compare=False)


class RouteDispatcher:
    """Exact-route dispatcher built from registered service modules."""

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], RouteMatch] = {}

    def register(self, route: RouteDefinition, handler: RouteHandler) -> None:
        key = (route.method.upper(), route.path)
        if key in self._routes:
            raise ValueError(
                f"route is already registered: {route.method} {route.path}"
            )
        self._routes[key] = RouteMatch(
            method=route.method.upper(),
            path=route.path,
            owner=route.owner,
            handler_name=route.handler_name,
            handler=handler,
        )

    def match(self, method: str, path: str) -> RouteMatch | None:
        return self._routes.get((method.upper(), path))

    def dispatch(self, request: RouteRequest) -> bool:
        match = self.match(request.method, request.path)
        if match is None:
            return False
        workspace_routes = {
            "/api/workspaces",
            "/api/workspaces/clear",
            "/api/workspaces/attach",
            "/api/workspaces/detach",
            "/api/workspaces/heartbeat",
            "/api/workspaces/close",
        }
        if (
            "workspace_id" in request.params
            and request.workspace_id
            and request.path not in workspace_routes
        ):
            try:
                request.services.workspaces.validate(
                    request.workspace_id,
                    request.connection_id,
                    request.lease_token,
                )
            except Exception as error:
                request.transport.emit_response(
                    JsonResponse({"error": str(error)}, status=409)
                )
                return True
        request.transport.emit_response(match.handler(request))
        return True


def build_route_dispatcher(
    module_registry: ModuleRegistry,
    workflow_registry: WorkflowRegistry | None = None,
) -> RouteDispatcher:
    """Create an exact dispatcher from executable registry contributions."""

    dispatcher = RouteDispatcher()
    for module in module_registry.values():
        for route in module.routes:
            try:
                handler = module.handlers[route.handler_name]
            except KeyError as error:
                raise ValueError(
                    f"module {module.id} route has no executable handler: "
                    f"{route.handler_name}"
                ) from error
            dispatcher.register(route, handler)
    if workflow_registry is not None:
        for workflow in workflow_registry.values():
            for route in workflow.routes:
                try:
                    handler = workflow.handlers[route.handler_name]
                except KeyError as error:
                    raise ValueError(
                        f"workflow {workflow.id} route has no executable handler: "
                        f"{route.handler_name}"
                    ) from error
                dispatcher.register(route, handler)
    return dispatcher
