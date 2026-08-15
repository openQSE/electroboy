"""Corkboard capability module declaration."""

from __future__ import annotations

import html
from http import HTTPStatus

from electroboy.service.http import HtmlResponse, JsonResponse, ServiceResponse
from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest

from .common import conflict, route
from .creative_workspace import (
    _create_creative_corkboard,
    creative_corkboard_html,
    save_creative_corkboard,
)


def _view(request: RouteRequest) -> HtmlResponse:
    try:
        root = request.services.contexts.active_project_root(request.context_id)
        folder = str((request.params.get("path") or [""])[0])
        title = str((request.params.get("title") or [""])[0]).strip() or None
        page, status = creative_corkboard_html(
            root,
            folder,
            title=title,
            context_id=request.context_id,
        )
    except Exception as error:
        return HtmlResponse(
            f"<p>{html.escape(str(error))}</p>",
            status=HTTPStatus.CONFLICT,
        )
    return HtmlResponse(page, status=status)


def _save(request: RouteRequest) -> ServiceResponse:
    try:
        root = request.services.contexts.active_project_root(request.context_id)
        payload = save_creative_corkboard(
            root,
            request.body(),
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _create(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        root = request.services.contexts.active_project_root(request.context_id)
        path = _create_creative_corkboard(root, str(payload.get("path") or ""))
        result = {"status": "created", "path": path}
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


_HANDLERS = {"view": _view, "save": _save, "create": _create}


def module() -> ServiceModule:
    return ServiceModule(
        id="corkboard",
        label="Corkboard",
        routes=(
            route("GET", "/artifacts/creative-corkboard", "corkboard", "view"),
            route("POST", "/api/creative/corkboard", "corkboard", "save"),
            route("POST", "/api/creative/corkboards", "corkboard", "create"),
        ),
        handlers=_HANDLERS,
        assets=("js/modules/corkboard.js",),
        asset_package="electroboy.modules",
        capabilities=frozenset({"folder-corkboard", "freeform-corkboard"}),
        state_namespace="corkboard",
    )
