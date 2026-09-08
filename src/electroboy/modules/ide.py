"""IDE capability module declaration."""

from __future__ import annotations

from electroboy.service.http import JsonResponse, ServiceResponse
from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest

from .common import conflict, route


def _runtime(request: RouteRequest) -> ServiceResponse:
    return JsonResponse(request.services.ide.runtime_status())


def _install(request: RouteRequest) -> ServiceResponse:
    try:
        request.body()
        payload = request.services.ide.install()
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _start(request: RouteRequest) -> ServiceResponse:
    try:
        request.body()
        payload = request.services.ide.start(request.context_id)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _status(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.ide.status(request.context_id)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _stop(request: RouteRequest) -> ServiceResponse:
    try:
        body = request.body()
        reason = str(body.get("reason") or "requested")
        payload = request.services.ide.stop(request.context_id, reason)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _open(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.ide.open_location(
            request.context_id,
            request.body(),
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _diagnostics(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.ide.diagnostics(request.context_id)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _record_input_event(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.ide.record_input_event(
            request.context_id,
            request.body(),
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _configuration(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.ide.configuration(request.context_id)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _configure(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.ide.configure(
            request.context_id,
            request.body(),
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _network_status(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.ide.network_status(request.context_id)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _configure_network(request: RouteRequest) -> ServiceResponse:
    try:
        body = request.body()
        payload = request.services.ide.configure_network(
            request.context_id,
            mode=str(body.get("mode") or "deny"),
            rules=body.get("rules"),
            temporary_rules=body.get("temporary_rules"),
            audit_acknowledged=bool(body.get("audit_acknowledged", False)),
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _clear_network_events(request: RouteRequest) -> ServiceResponse:
    try:
        request.body()
        payload = request.services.ide.clear_network_events(request.context_id)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _editor_context(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.ide.editor_context(request.context_id)
    except Exception as error:
        return conflict(error)
    return JsonResponse({"editor_context": payload})


def _neovim_status(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.ide.neovim_status(request.context_id)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _launch_neovim(request: RouteRequest) -> ServiceResponse:
    try:
        request.body()
        payload = request.services.ide.launch_neovim(request.context_id)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _configure_neovim(request: RouteRequest) -> ServiceResponse:
    try:
        body = request.body()
        payload = request.services.ide.configure_neovim(
            request.context_id,
            enabled=bool(body.get("enabled", True)),
            executable=str(body.get("executable") or ""),
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _csp_report(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.ide.record_csp_violation(
            request.context_id,
            request.body(),
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _attach_view(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.ide.attach_view(
            request.context_id,
            str(request.body().get("view_id") or ""),
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _detach_view(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.services.ide.detach_view(
            request.context_id,
            str(request.body().get("view_id") or ""),
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


_HANDLERS = {
    "runtime": _runtime,
    "install": _install,
    "start": _start,
    "status": _status,
    "stop": _stop,
    "open": _open,
    "diagnostics": _diagnostics,
    "record_input_event": _record_input_event,
    "configuration": _configuration,
    "configure": _configure,
    "network_status": _network_status,
    "configure_network": _configure_network,
    "clear_network_events": _clear_network_events,
    "editor_context": _editor_context,
    "neovim_status": _neovim_status,
    "launch_neovim": _launch_neovim,
    "configure_neovim": _configure_neovim,
    "csp_report": _csp_report,
    "attach_view": _attach_view,
    "detach_view": _detach_view,
}


def module() -> ServiceModule:
    return ServiceModule(
        id="ide",
        label="IDE",
        routes=(
            route("GET", "/api/ide/runtime", "ide", "runtime"),
            route("POST", "/api/ide/install", "ide", "install"),
            route("POST", "/api/ide/start", "ide", "start"),
            route("GET", "/api/ide/status", "ide", "status"),
            route("POST", "/api/ide/stop", "ide", "stop"),
            route("POST", "/api/ide/open", "ide", "open"),
            route("GET", "/api/ide/diagnostics", "ide", "diagnostics"),
            route(
                "POST",
                "/api/ide/input-events",
                "ide",
                "record_input_event",
            ),
            route("GET", "/api/ide/configuration", "ide", "configuration"),
            route("POST", "/api/ide/configure", "ide", "configure"),
            route("GET", "/api/ide/network", "ide", "network_status"),
            route(
                "POST",
                "/api/ide/network/configure",
                "ide",
                "configure_network",
            ),
            route(
                "POST",
                "/api/ide/network/events/clear",
                "ide",
                "clear_network_events",
            ),
            route("GET", "/api/ide/context", "ide", "editor_context"),
            route("GET", "/api/ide/neovim", "ide", "neovim_status"),
            route(
                "POST",
                "/api/ide/neovim/launch",
                "ide",
                "launch_neovim",
            ),
            route(
                "POST",
                "/api/ide/neovim/configure",
                "ide",
                "configure_neovim",
            ),
            route("POST", "/api/ide/csp-report", "ide", "csp_report"),
            route("POST", "/api/ide/views/attach", "ide", "attach_view"),
            route("POST", "/api/ide/views/detach", "ide", "detach_view"),
        ),
        handlers=_HANDLERS,
        assets=("ide.css", "ide.js"),
        asset_package="electroboy.modules",
        capabilities=frozenset({"ide", "editor", "navigation"}),
        state_namespace="ide",
    )
