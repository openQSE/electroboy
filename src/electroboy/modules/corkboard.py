"""Corkboard capability module declaration."""

from __future__ import annotations

import html
from http import HTTPStatus

from electroboy.service.corkboard import (
    CorkboardProvider,
    CorkboardWorkflowController,
)
from electroboy.service.http import HtmlResponse, JsonResponse, ServiceResponse
from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest
from electroboy.state_store import StateError

from .common import conflict, route
from .creative_workspace import render_corkboard_html


def _provider(request: RouteRequest) -> CorkboardProvider:
    context = request.services.contexts.require(request.context_id)
    workflow_id = context.workflow_id
    if not workflow_id:
        raise StateError("activate a workflow project first")
    controller = request.services.workflows.controller(
        workflow_id,
        CorkboardWorkflowController,
    )
    provider = controller.get_corkboard_provider()
    requested_provider = str(
        (request.params.get("provider") or [provider.provider_id])[0]
    ).strip()
    if requested_provider and requested_provider != provider.provider_id:
        raise StateError(
            f"corkboard provider is not active: {requested_provider}"
        )
    return provider


def _board_id(request: RouteRequest) -> str:
    return str(
        (request.params.get("board_id") or request.params.get("path") or [""])[0]
    ).strip()


def _require_matching_provider(
    provider: CorkboardProvider,
    payload: dict[str, object],
) -> None:
    requested = str(payload.get("provider") or provider.provider_id).strip()
    if requested != provider.provider_id:
        raise StateError(f"corkboard provider is not active: {requested}")


def _view(request: RouteRequest) -> HtmlResponse:
    try:
        provider = _provider(request)
        board_id = _board_id(request)
        title = str((request.params.get("title") or [""])[0]).strip() or None
        payload = provider.get_board(
            request.context_id,
            board_id,
            title=title,
        )
        page, status = render_corkboard_html(payload)
    except Exception as error:
        return HtmlResponse(
            f"<p>{html.escape(str(error))}</p>",
            status=HTTPStatus.CONFLICT,
        )
    return HtmlResponse(page, status=status)


def _board(request: RouteRequest) -> ServiceResponse:
    try:
        provider = _provider(request)
        payload = provider.get_board(
            request.context_id,
            _board_id(request),
            title=str((request.params.get("title") or [""])[0]).strip() or None,
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _boards(request: RouteRequest) -> ServiceResponse:
    try:
        provider = _provider(request)
        boards = provider.list_boards(request.context_id)
    except Exception as error:
        return conflict(error)
    return JsonResponse({"provider": provider.provider_id, "boards": boards})


def _save(request: RouteRequest) -> ServiceResponse:
    try:
        provider = _provider(request)
        body = request.body()
        _require_matching_provider(provider, body)
        payload = provider.apply_operation(
            request.context_id,
            body,
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _create(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        provider = _provider(request)
        _require_matching_provider(provider, payload)
        board_id = str(payload.get("board_id") or payload.get("path") or "")
        result = provider.create_board(
            request.context_id,
            board_id,
            title=str(payload.get("title") or "").strip() or None,
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


_HANDLERS = {
    "view": _view,
    "board": _board,
    "boards": _boards,
    "save": _save,
    "create": _create,
}


def module() -> ServiceModule:
    return ServiceModule(
        id="corkboard",
        label="Corkboard",
        routes=(
            route("GET", "/artifacts/corkboard", "corkboard", "view"),
            route("GET", "/api/corkboard", "corkboard", "board"),
            route("GET", "/api/corkboards", "corkboard", "boards"),
            route("POST", "/api/corkboard", "corkboard", "save"),
            route("POST", "/api/corkboards", "corkboard", "create"),
            # Compatibility aliases for pre-provider creative clients.
            route("GET", "/artifacts/creative-corkboard", "corkboard", "view"),
            route("POST", "/api/creative/corkboard", "corkboard", "save"),
            route("POST", "/api/creative/corkboards", "corkboard", "create"),
        ),
        handlers=_HANDLERS,
        assets=("js/modules/corkboard.js",),
        asset_package="electroboy.modules",
        capabilities=frozenset(
            {
                "corkboard-provider",
                "folder-corkboard",
                "freeform-corkboard",
                "selectable-corkboard-layout",
                "corkboard-auto-organize",
            }
        ),
        state_namespace="corkboard",
    )
