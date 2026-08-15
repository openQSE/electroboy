"""Helpers shared by built-in backend capability modules."""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus

from electroboy.service.registry import RouteDefinition
from electroboy.service.routes import RouteRequest


def route(method: str, path: str, owner: str, handler_name: str) -> RouteDefinition:
    """Return route metadata for a module-owned HTTP endpoint."""

    return RouteDefinition(method, path, owner, handler_name)


def send_conflict(request: RouteRequest, error: Exception) -> None:
    """Return the standard state/action conflict response."""

    request.send_json({"error": str(error)}, status=HTTPStatus.CONFLICT)


def context_payload(
    request: RouteRequest,
    build: Callable[[str], dict[str, object]],
) -> None:
    """Render a context-scoped state payload with standard error handling."""

    try:
        payload = build(request.context_id)
    except Exception as error:
        send_conflict(request, error)
        return
    request.send_json(payload)
