"""Creative binder capability module declaration."""

from __future__ import annotations

from electroboy.service.registry import ServiceModule

from .common import route


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
        capabilities=frozenset({"filesystem-tree", "creative-documents"}),
        state_namespace="binder",
    )

