"""Helpers shared by built-in backend capability modules."""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus

from electroboy.service.registry import RouteDefinition
from electroboy.service.routes import RouteRequest
from electroboy.service.http import JsonResponse, ServiceResponse


def route(method: str, path: str, owner: str, handler_name: str) -> RouteDefinition:
    """Return route metadata for a module-owned HTTP endpoint."""

    return RouteDefinition(method, path, owner, handler_name)


def conflict(error: Exception) -> JsonResponse:
    """Return the standard state/action conflict response."""

    return JsonResponse({"error": str(error)}, status=HTTPStatus.CONFLICT)


def context_payload(
    request: RouteRequest,
    build: Callable[[str], dict[str, object]],
) -> ServiceResponse:
    """Render a context-scoped state payload with standard error handling."""

    try:
        payload = build(request.context_id)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)
