"""Helpers shared by built-in backend capability modules."""

from __future__ import annotations

from electroboy.service.registry import RouteDefinition


def route(method: str, path: str, owner: str, handler_name: str) -> RouteDefinition:
    """Return route metadata for a module-owned HTTP endpoint."""

    return RouteDefinition(method, path, owner, handler_name)

