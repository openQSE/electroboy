"""Calendar capability module declaration."""

from __future__ import annotations

import html
from http import HTTPStatus

from electroboy.service.calendar import CalendarProvider, CalendarWorkflowController
from electroboy.service.http import HtmlResponse, JsonResponse, ServiceResponse
from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest
from electroboy.state_store import StateError

from .calendar_workspace import render_calendar_html
from .common import conflict, route


def _provider(request: RouteRequest) -> CalendarProvider:
    context = request.services.contexts.require(request.context_id)
    if not context.workflow_id:
        raise StateError("activate a workflow project first")
    controller = request.services.workflows.controller(
        context.workflow_id,
        CalendarWorkflowController,
    )
    provider = controller.get_calendar_provider()
    requested = str(
        (request.params.get("provider") or [provider.provider_id])[0]
    ).strip()
    if requested and requested != provider.provider_id:
        raise StateError(f"calendar provider is not active: {requested}")
    return provider


def _calendar_ids(request: RouteRequest) -> list[str]:
    values: list[str] = []
    for raw in request.params.get("calendar_ids") or []:
        values.extend(part.strip() for part in raw.split(",") if part.strip())
    return list(dict.fromkeys(values))


def _visible_range(request: RouteRequest) -> dict[str, str]:
    return {
        key: str((request.params.get(key) or [""])[0]).strip()
        for key in ("range_start", "range_end")
        if str((request.params.get(key) or [""])[0]).strip()
    }


def _load(request: RouteRequest) -> dict[str, object]:
    return _provider(request).load_calendar(
        request.context_id,
        calendar_ids=_calendar_ids(request),
        visible_range=_visible_range(request),
        connection_id=request.connection_id,
    )


def _view(request: RouteRequest) -> HtmlResponse:
    try:
        page, status = render_calendar_html(_load(request))
    except Exception as error:
        return HtmlResponse(
            f'<section role="alert"><p>{html.escape(str(error))}</p></section>',
            status=HTTPStatus.CONFLICT,
        )
    return HtmlResponse(page, status=status)


def _calendar(request: RouteRequest) -> ServiceResponse:
    try:
        payload = _load(request)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


_HANDLERS = {
    "view": _view,
    "calendar": _calendar,
}


def module() -> ServiceModule:
    return ServiceModule(
        id="calendar",
        label="Calendar",
        routes=(
            route("GET", "/artifacts/calendar", "calendar", "view"),
            route("GET", "/api/calendar", "calendar", "calendar"),
        ),
        handlers=_HANDLERS,
        assets=("js/modules/calendar.js",),
        asset_package="electroboy.modules",
        capabilities=frozenset(
            {
                "calendar-provider",
                "calendar-event-colors",
                "calendar-multi-select",
            }
        ),
        state_namespace="calendar",
    )
