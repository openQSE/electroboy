"""Agenda capability module declaration."""

from __future__ import annotations

import html
from http import HTTPStatus

from electroboy.service.agenda import AgendaProvider, AgendaWorkflowController
from electroboy.service.http import HtmlResponse, JsonResponse, ServiceResponse
from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest
from electroboy.state_store import StateError

from .agenda_workspace import normalize_agenda_style, render_agenda_html
from .common import conflict, route


def _provider(request: RouteRequest) -> AgendaProvider:
    context = request.services.contexts.require(request.context_id)
    if not context.workflow_id:
        raise StateError("activate a workflow project first")
    controller = request.services.workflows.controller(
        context.workflow_id,
        AgendaWorkflowController,
    )
    provider = controller.get_agenda_provider()
    requested = str(
        (request.params.get("provider") or [provider.provider_id])[0]
    ).strip()
    if requested and requested != provider.provider_id:
        raise StateError(f"agenda provider is not active: {requested}")
    return provider


def _require_matching_provider(
    provider: AgendaProvider,
    payload: dict[str, object],
) -> None:
    requested = str(payload.get("provider") or provider.provider_id).strip()
    if requested != provider.provider_id:
        raise StateError(f"agenda provider is not active: {requested}")


def _filters(request: RouteRequest) -> dict[str, str]:
    return {
        key.removeprefix("filter."): str(values[0])
        for key, values in request.params.items()
        if key.startswith("filter.") and values
    }


def _visible_range(request: RouteRequest) -> dict[str, str]:
    return {
        key: str((request.params.get(key) or [""])[0]).strip()
        for key in ("range_start", "range_end")
        if str((request.params.get(key) or [""])[0]).strip()
    }


def _style(request: RouteRequest) -> str:
    return normalize_agenda_style((request.params.get("style") or ["default"])[0])


def _load(request: RouteRequest) -> dict[str, object]:
    return _provider(request).load_agenda(
        request.context_id,
        filters=_filters(request),
        visible_range=_visible_range(request),
        connection_id=request.connection_id,
    )


def _view(request: RouteRequest) -> HtmlResponse:
    try:
        page, status = render_agenda_html(_load(request), style=_style(request))
    except Exception as error:
        return HtmlResponse(
            f'<section role="alert"><p>{html.escape(str(error))}</p></section>',
            status=HTTPStatus.CONFLICT,
        )
    return HtmlResponse(page, status=status)


def _agenda(request: RouteRequest) -> ServiceResponse:
    try:
        payload = _load(request)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _action(request: RouteRequest) -> ServiceResponse:
    try:
        provider = _provider(request)
        payload = request.body()
        _require_matching_provider(provider, payload)
        result = provider.invoke_agenda_action(
            request.context_id,
            payload,
            connection_id=request.connection_id,
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


def _editor_payload(request: RouteRequest) -> dict[str, object]:
    return {
        "provider": str((request.params.get("provider") or [""])[0]),
        "item_id": str((request.params.get("item_id") or [""])[0]),
        "item_version": str((request.params.get("item_version") or [""])[0]),
        "action_id": str((request.params.get("action_id") or [""])[0]),
    }


def _editor(request: RouteRequest) -> ServiceResponse:
    try:
        provider = _provider(request)
        payload = _editor_payload(request)
        _require_matching_provider(provider, payload)
        result = provider.load_agenda_editor(
            request.context_id,
            payload,
            connection_id=request.connection_id,
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


def _submit_editor(request: RouteRequest) -> ServiceResponse:
    try:
        provider = _provider(request)
        payload = request.body()
        _require_matching_provider(provider, payload)
        result = provider.submit_agenda_editor(
            request.context_id,
            payload,
            connection_id=request.connection_id,
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


_HANDLERS = {
    "view": _view,
    "agenda": _agenda,
    "action": _action,
    "editor": _editor,
    "submit_editor": _submit_editor,
}


def module() -> ServiceModule:
    return ServiceModule(
        id="agenda",
        label="Agenda",
        routes=(
            route("GET", "/artifacts/agenda", "agenda", "view"),
            route("GET", "/api/agenda", "agenda", "agenda"),
            route("POST", "/api/agenda/action", "agenda", "action"),
            route("GET", "/api/agenda/editor", "agenda", "editor"),
            route("POST", "/api/agenda/editor", "agenda", "submit_editor"),
        ),
        handlers=_HANDLERS,
        assets=(
            "css/agenda-pane-tools.css",
            "js/modules/agenda.js",
            "js/modules/agenda-pane-tools.js",
        ),
        asset_package="electroboy.modules",
        capabilities=frozenset(
            {
                "agenda-provider",
                "agenda-filters",
                "agenda-actions",
                "agenda-host-actions",
                "agenda-styles",
                "agenda-modal-editor",
            }
        ),
        state_namespace="agenda",
    )
