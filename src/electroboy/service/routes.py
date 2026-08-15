"""HTTP route dispatch primitives for the browser service."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs

from .registry import (
    ModuleRegistry,
    RouteDefinition,
    RouteHandler,
    WorkflowRegistry,
)


@dataclass
class RouteRequest:
    """Transport-neutral request passed to module-owned route handlers."""

    method: str
    path: str
    query: str
    state: Any
    config: Any
    transport: Any = field(repr=False)
    operations: Mapping[str, Callable[..., Any]] = field(
        default_factory=dict,
        repr=False,
    )

    @property
    def params(self) -> dict[str, list[str]]:
        return parse_qs(self.query)

    @property
    def context_id(self) -> str:
        return str((self.params.get("context_id") or [""])[0])

    def body(self) -> dict[str, object]:
        return self.transport._read_json_body()

    def operation(self, name: str, *args: Any, **kwargs: Any) -> Any:
        try:
            operation = self.operations[name]
        except KeyError as error:
            raise RuntimeError(f"route operation is not configured: {name}") from error
        return operation(*args, **kwargs)

    def send_json(
        self,
        payload: dict[str, object],
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self.transport._send_json(payload, status=status)

    def send_text(
        self,
        text: str,
        content_type: str = "text/plain; charset=utf-8",
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self.transport._send_text(text, content_type, status=status)

    def send_download(self, text: str, filename: str) -> None:
        self.transport._send_download(text, filename)

    def send_binary_download(
        self,
        data: bytes,
        filename: str,
        content_type: str,
    ) -> None:
        self.transport._send_binary_download(data, filename, content_type)

    def stream_session_events(self, session: Any) -> None:
        self.transport._stream_session_events(session)

    def stream_artifact_events(self, artifact: str, path: Any) -> None:
        self.transport._stream_artifact_events(artifact, path)

    def stream_progress_events(
        self,
        context_id: str,
        root: Any,
        snapshot: Callable[[Any], tuple[str, bool]],
    ) -> None:
        self.transport._stream_progress_events(context_id, root, snapshot)


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
        match.handler(request)
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
