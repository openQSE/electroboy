"""Mind Map capability module declaration."""

from __future__ import annotations

import html
from http import HTTPStatus

from electroboy.service.http import HtmlResponse, JsonResponse, ServiceResponse
from electroboy.service.mind_map import MindMapProvider, MindMapWorkflowController
from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest
from electroboy.state_store import StateError

from .agenda_workspace import normalize_agenda_style
from .common import conflict, route
from .mind_map_workspace import render_mind_map_html


def _provider(request: RouteRequest) -> MindMapProvider:
    context = request.services.contexts.require(request.context_id)
    if not context.workflow_id:
        raise StateError("activate a workflow project first")
    controller = request.services.workflows.controller(
        context.workflow_id,
        MindMapWorkflowController,
    )
    provider = controller.get_mind_map_provider()
    requested = str(
        (request.params.get("provider") or [provider.provider_id])[0]
    ).strip()
    if requested and requested != provider.provider_id:
        raise StateError(f"mind map provider is not active: {requested}")
    return provider


def _filters(request: RouteRequest) -> dict[str, str]:
    return {
        key.removeprefix("filter."): str(values[0])
        for key, values in request.params.items()
        if key.startswith("filter.") and values
    }


def _style(request: RouteRequest) -> str:
    return normalize_agenda_style((request.params.get("style") or ["default"])[0])


def _load(request: RouteRequest) -> dict[str, object]:
    return _provider(request).load_mind_map(
        request.context_id,
        filters=_filters(request),
        connection_id=request.connection_id,
    )


def _view(request: RouteRequest) -> HtmlResponse:
    try:
        page, status = render_mind_map_html(_load(request), style=_style(request))
    except Exception as error:
        return HtmlResponse(
            f'<section role="alert"><p>{html.escape(str(error))}</p></section>',
            status=HTTPStatus.CONFLICT,
        )
    return HtmlResponse(page, status=status)


def _mind_map(request: RouteRequest) -> ServiceResponse:
    try:
        payload = _load(request)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


_HANDLERS = {
    "view": _view,
    "mind_map": _mind_map,
}


def module() -> ServiceModule:
    return ServiceModule(
        id="mind_map",
        label="Mind Map",
        routes=(
            route("GET", "/artifacts/mind-map", "mind_map", "view"),
            route("GET", "/api/mind-map", "mind_map", "mind_map"),
        ),
        handlers=_HANDLERS,
        assets=("js/modules/mind-map.js",),
        asset_package="electroboy.modules",
        capabilities=frozenset(
            {
                "mind-map-provider",
                "mind-map-source-trace",
                "mind-map-pan-zoom",
                "mind-map-relationship-modes",
                "mind-map-styles",
            }
        ),
        state_namespace="mind_map",
    )
