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
from .corkboard_generation import GENERATION_MANAGER, generation_passes
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
        connection_id=request.connection_id,
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
            connection_id=request.connection_id,
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _boards(request: RouteRequest) -> ServiceResponse:
    try:
        provider = _provider(request)
        boards = provider.list_boards(
            request.context_id,
            connection_id=request.connection_id,
        )
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
            connection_id=request.connection_id,
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
            connection_id=request.connection_id,
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


def _delete_boards(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        provider = _provider(request)
        _require_matching_provider(provider, payload)
        requested = payload.get("board_ids")
        if not isinstance(requested, list):
            raise StateError("corkboard selection must be a list")
        board_ids = [str(board_id or "").strip() for board_id in requested]
        if any(not board_id for board_id in board_ids):
            raise StateError("corkboard ids cannot be empty")
        result = provider.delete_boards(
            request.context_id,
            board_ids,
            connection_id=request.connection_id,
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


def _generation_passes(request: RouteRequest) -> ServiceResponse:
    try:
        context = request.services.contexts.require(request.context_id)
        workflow_id = str(context.workflow_id or "")
        passes = generation_passes(workflow_id)
        if not passes:
            raise StateError("active workflow does not support corkboard generation")
    except Exception as error:
        return conflict(error)
    return JsonResponse({"workflow": workflow_id, "passes": passes})


def _start_generation(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        provider = _provider(request)
        _require_matching_provider(provider, payload)
        job = GENERATION_MANAGER.start(
            request.services,
            provider,
            request.context_id,
            payload,
            connection_id=request.connection_id,
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(job, status=HTTPStatus.ACCEPTED)


def _generation_status(request: RouteRequest) -> ServiceResponse:
    try:
        job_id = str((request.params.get("job_id") or [""])[0]).strip()
        job = (
            GENERATION_MANAGER.get(request.context_id, job_id)
            if job_id
            else GENERATION_MANAGER.latest(request.context_id)
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(job or {"status": "idle", "job_id": ""})


_HANDLERS = {
    "view": _view,
    "board": _board,
    "boards": _boards,
    "save": _save,
    "create": _create,
    "delete_boards": _delete_boards,
    "generation_passes": _generation_passes,
    "start_generation": _start_generation,
    "generation_status": _generation_status,
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
            route(
                "POST",
                "/api/corkboards/delete",
                "corkboard",
                "delete_boards",
            ),
            route(
                "GET",
                "/api/corkboard-generation/passes",
                "corkboard",
                "generation_passes",
            ),
            route(
                "POST",
                "/api/corkboard-generation",
                "corkboard",
                "start_generation",
            ),
            route(
                "GET",
                "/api/corkboard-generation",
                "corkboard",
                "generation_status",
            ),
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
                "corkboard-board-selector",
                "corkboard-generation",
                "corkboard-board-deletion",
            }
        ),
        state_namespace="corkboard",
    )
