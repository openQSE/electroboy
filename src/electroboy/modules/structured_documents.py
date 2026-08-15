"""Structured document capability module declaration."""

from __future__ import annotations

import html
from http import HTTPStatus

from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest

from .common import route, send_conflict


def _editor(request: RouteRequest) -> None:
    try:
        params = request.params
        root = request.state.active_project_root(request.context_id)
        artifact = str((params.get("artifact") or [""])[0]).strip()
        requested_path = str((params.get("path") or [""])[0])
        title = str((params.get("title") or [""])[0]).strip() or None
        create_missing = str((params.get("create") or [""])[0]) == "1"
        rich_editor = (
            request.state.project_mode(request.context_id) == "creative"
            and artifact == "document"
        )
        font_size = request.operation("artifact_editor_font_size", params)
        page, status = request.operation(
            "artifact_editor_html",
            root,
            artifact,
            requested_path,
            title=title,
            create_missing=create_missing,
            context_id=request.context_id,
            rich_editor=rich_editor,
            editor_font_size=font_size,
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
        root = request.state.active_project_root(request.context_id)
        payload = request.body()
        result = request.operation(
            "save_artifact_edit",
            root,
            str(payload.get("artifact") or ""),
            str(payload.get("path") or ""),
            payload,
        )
    except Exception as error:
        send_conflict(request, error)
        return
    request.send_json(result)


def _view(request: RouteRequest) -> None:
    artifact = request.path.removeprefix("/artifacts/")
    try:
        if artifact == "requirements":
            root = request.state.requirements_document_root(request.context_id)
            embedded = str((request.params.get("embed") or [""])[0]) == "1"
            zoom = request.operation("document_zoom", request.params)
            page, status = request.operation(
                "requirements_document_html",
                root,
                embedded=embedded,
                zoom_percent=zoom,
            )
        elif artifact == "design":
            root = request.state.active_project_root(request.context_id)
            page, status = request.operation("design_document_html", root)
        else:
            root = request.state.active_project_root(request.context_id)
            stage = {
                "implementation-report": "code",
                "validation-report": "validate",
            }.get(artifact, artifact)
            page, status = request.operation("stage_document_html", root, stage)
    except Exception as error:
        request.send_text(
            f"<p>{html.escape(str(error))}</p>",
            "text/html; charset=utf-8",
            status=HTTPStatus.CONFLICT,
        )
        return
    request.send_text(page, "text/html; charset=utf-8", status=status)


_HANDLERS = {"editor": _editor, "save": _save, "view": _view}


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
            route(
                "GET",
                "/artifacts/implementation-report",
                "structured_documents",
                "view",
            ),
            route(
                "GET",
                "/artifacts/validation-report",
                "structured_documents",
                "view",
            ),
        ),
        handlers=_HANDLERS,
        capabilities=frozenset({"jsonl-source", "markdown-render", "schema-edit"}),
        state_namespace="structured_documents",
    )
