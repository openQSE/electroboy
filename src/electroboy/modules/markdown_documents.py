"""Markdown document capability module declaration."""

from __future__ import annotations

from electroboy.service.registry import ServiceModule

from .common import route


def module() -> ServiceModule:
    return ServiceModule(
        id="markdown_documents",
        label="Markdown Documents",
        routes=(
            route("GET", "/artifacts/document", "markdown_documents", "preview"),
            route("GET", "/api/documents/export", "markdown_documents", "export"),
            route("GET", "/api/artifacts/events", "markdown_documents", "events"),
        ),
        assets=("js/modules/documents.js",),
        asset_package="electroboy.modules",
        capabilities=frozenset({"markdown-preview", "markdown-edit", "export"}),
        state_namespace="markdown_documents",
    )
