"""Creative binder capability module declaration."""

from __future__ import annotations

from electroboy.service.http import JsonResponse, ServiceResponse
from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest

from .common import conflict, route


def _tree(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.state.creative_tree(request.context_id)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _path_action(request: RouteRequest, method: str) -> ServiceResponse:
    try:
        payload = request.body()
        result = getattr(request.state, method)(
            request.context_id,
            str(payload.get("path") or ""),
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


def _create_folder(request: RouteRequest) -> ServiceResponse:
    return _path_action(request, "create_creative_folder")


def _create_document(request: RouteRequest) -> ServiceResponse:
    return _path_action(request, "create_creative_document")


def _rename(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        result = request.state.rename_creative_entry(
            request.context_id,
            str(payload.get("path") or ""),
            str(payload.get("new_name") or ""),
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


def _delete(request: RouteRequest) -> ServiceResponse:
    return _path_action(request, "delete_creative_entry")


_HANDLERS = {
    "tree": _tree,
    "create_folder": _create_folder,
    "create_document": _create_document,
    "rename": _rename,
    "delete": _delete,
}


def module() -> ServiceModule:
    return ServiceModule(
        id="binder",
        label="Binder",
        routes=(
            route("GET", "/api/creative/tree", "binder", "tree"),
            route("POST", "/api/creative/folders", "binder", "create_folder"),
            route("POST", "/api/creative/documents", "binder", "create_document"),
            route("POST", "/api/creative/rename", "binder", "rename"),
            route("POST", "/api/creative/delete", "binder", "delete"),
        ),
        handlers=_HANDLERS,
        assets=("js/modules/binder.js",),
        asset_package="electroboy.modules",
        capabilities=frozenset({"filesystem-tree", "creative-documents"}),
        state_namespace="binder",
    )
