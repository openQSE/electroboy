"""Structured document capability module declaration."""

from __future__ import annotations

from electroboy.service.registry import ServiceModule

from .common import route


def module() -> ServiceModule:
    return ServiceModule(
        id="structured_documents",
        label="Structured Documents",
        routes=(
            route("GET", "/artifacts/edit", "structured_documents", "editor"),
            route("POST", "/api/artifacts/edit", "structured_documents", "save"),
            route("GET", "/artifacts/requirements", "structured_documents", "view"),
            route("GET", "/artifacts/design", "structured_documents", "view"),
            route(
                "GET",
                "/artifacts/implementation-plan",
                "structured_documents",
                "view",
            ),
            route("GET", "/artifacts/test-plan", "structured_documents", "view"),
        ),
        capabilities=frozenset({"jsonl-source", "markdown-render", "schema-edit"}),
        state_namespace="structured_documents",
    )

