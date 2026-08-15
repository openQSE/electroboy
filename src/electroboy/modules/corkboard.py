"""Corkboard capability module declaration."""

from __future__ import annotations

import html
from http import HTTPStatus

from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest

from .common import route, send_conflict
from .creative_workspace import creative_corkboard_html


def _view(request: RouteRequest) -> None:
    try:
        root = request.state.active_project_root(request.context_id)
        folder = str((request.params.get("path") or [""])[0])
        title = str((request.params.get("title") or [""])[0]).strip() or None
        page, status = creative_corkboard_html(
            root,
            folder,
            title=title,
            context_id=request.context_id,
        )
    except Exception as error:
        request.send_text(
            f"<p>{html.escape(str(error))}</p>",
            "text/html; charset=utf-8",
            status=HTTPStatus.CONFLICT,
        )
        return
    request.send_text(page, "text/html; charset=utf-8", status=status)


def _save(request: RouteRequest) -> None:
    try:
        payload = request.state.save_creative_corkboard(
            request.context_id,
            request.body(),
        )
    except Exception as error:
        send_conflict(request, error)
        return
    request.send_json(payload)


def _create(request: RouteRequest) -> None:
    try:
        payload = request.body()
        result = request.state.create_creative_corkboard(
            request.context_id,
            str(payload.get("path") or ""),
        )
    except Exception as error:
        send_conflict(request, error)
        return
    request.send_json(result)


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
