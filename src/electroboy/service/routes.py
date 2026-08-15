"""HTTP route dispatch primitives for the browser service."""

from __future__ import annotations

from dataclasses import dataclass

from .registry import ModuleRegistry, RouteDefinition


@dataclass(frozen=True)
class RouteMatch:
    """A registered exact route match."""

    method: str
    path: str
    owner: str
    handler_name: str
    handler_method: str


class RouteDispatcher:
    """Exact-route dispatcher built from registered service modules."""

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], RouteMatch] = {}

    def register(self, route: RouteDefinition, handler_method: str) -> None:
        key = (route.method.upper(), route.path)
        if key in self._routes:
            raise ValueError(f"route is already registered: {route.method} {route.path}")
        self._routes[key] = RouteMatch(
            method=route.method.upper(),
            path=route.path,
            owner=route.owner,
            handler_name=route.handler_name,
            handler_method=handler_method,
        )

    def match(self, method: str, path: str) -> RouteMatch | None:
        return self._routes.get((method.upper(), path))


def build_route_dispatcher(
    module_registry: ModuleRegistry,
    handler_methods: dict[str, str],
) -> RouteDispatcher:
    """Create an exact route dispatcher from module registry metadata."""

    dispatcher = RouteDispatcher()
    for module in module_registry.values():
        for route in module.routes:
            handler_method = handler_methods.get(
                f"{route.owner}:{route.handler_name}",
                handler_methods.get(route.handler_name),
            )
            if handler_method is None:
                continue
            dispatcher.register(route, handler_method)
    return dispatcher
