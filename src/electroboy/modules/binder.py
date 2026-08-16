"""Creative binder capability module declaration."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from electroboy.service.http import JsonResponse, ServiceResponse
from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest

from .common import conflict, route
from .creative_workspace import (
    _create_creative_document,
    _create_creative_folder,
    _creative_tree_payload,
    _delete_creative_entry,
    _rename_creative_entry,
)


def _tree(request: RouteRequest) -> ServiceResponse:
    try:
        root = request.services.contexts.active_project_root(request.context_id)
        payload = _creative_tree_payload(root)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _path_action(
    request: RouteRequest,
    action: Callable[[Path | str, str], str],
    status: str,
) -> ServiceResponse:
    try:
        payload = request.body()
        root = request.services.contexts.active_project_root(request.context_id)
        path = action(root, str(payload.get("path") or ""))
        result = {"status": status, "path": path}
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


def _create_folder(request: RouteRequest) -> ServiceResponse:
    return _path_action(request, _create_creative_folder, "created")


def _create_document(request: RouteRequest) -> ServiceResponse:
    return _path_action(request, _create_creative_document, "created")


def _rename(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        root = request.services.contexts.active_project_root(request.context_id)
        old_path, new_path = _rename_creative_entry(
            root,
            str(payload.get("path") or ""),
            str(payload.get("new_name") or ""),
        )
        result = {
            "status": "renamed",
            "old_path": old_path,
            "path": new_path,
        }
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


def _delete(request: RouteRequest) -> ServiceResponse:
    return _path_action(request, _delete_creative_entry, "deleted")


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
