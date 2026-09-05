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
    _empty_creative_trash,
    _permanently_delete_creative_trash_entry,
    _rename_creative_entry,
    _restore_creative_trash_entry,
    _set_creative_folder_color,
    _trash_creative_entry,
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
    try:
        payload = request.body()
        root = request.services.contexts.active_project_root(request.context_id)
        result = _trash_creative_entry(root, str(payload.get("path") or ""))
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


def _trash_id_action(
    request: RouteRequest,
    action: Callable[[Path | str, str], dict[str, object]],
) -> ServiceResponse:
    try:
        payload = request.body()
        root = request.services.contexts.active_project_root(request.context_id)
        result = action(root, str(payload.get("trash_id") or ""))
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


def _restore_trash_entry(request: RouteRequest) -> ServiceResponse:
    return _trash_id_action(request, _restore_creative_trash_entry)


def _permanently_delete_trash_entry(request: RouteRequest) -> ServiceResponse:
    return _trash_id_action(request, _permanently_delete_creative_trash_entry)


def _empty_trash(request: RouteRequest) -> ServiceResponse:
    try:
        root = request.services.contexts.active_project_root(request.context_id)
        result = _empty_creative_trash(root)
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


def _set_folder_color(request: RouteRequest) -> ServiceResponse:
    try:
        payload = request.body()
        root = request.services.contexts.active_project_root(request.context_id)
        path, color = _set_creative_folder_color(
            root,
            str(payload.get("path") or ""),
            payload.get("color"),
        )
        result = {"status": "updated", "path": path, "color": color}
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


_HANDLERS = {
    "tree": _tree,
    "create_folder": _create_folder,
    "create_document": _create_document,
    "rename": _rename,
    "delete": _delete,
    "restore_trash_entry": _restore_trash_entry,
    "permanently_delete_trash_entry": _permanently_delete_trash_entry,
    "empty_trash": _empty_trash,
    "set_folder_color": _set_folder_color,
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
            route(
                "POST",
                "/api/creative/trash/restore",
                "binder",
                "restore_trash_entry",
            ),
            route(
                "POST",
                "/api/creative/trash/delete",
                "binder",
                "permanently_delete_trash_entry",
            ),
            route(
                "POST",
                "/api/creative/trash/empty",
                "binder",
                "empty_trash",
            ),
            route(
                "POST",
                "/api/creative/folder-color",
                "binder",
                "set_folder_color",
            ),
        ),
        handlers=_HANDLERS,
        assets=("js/modules/binder.js",),
        asset_package="electroboy.modules",
        capabilities=frozenset({"filesystem-tree", "creative-documents"}),
        state_namespace="binder",
    )
