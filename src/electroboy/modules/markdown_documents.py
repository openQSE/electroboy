"""Markdown document capability module declaration."""

from __future__ import annotations

import html
from http import HTTPStatus
from pathlib import Path

from electroboy.document_export import export_markdown_document
from electroboy.service.http import (
    BinaryResponse,
    HtmlResponse,
    JsonResponse,
    ServiceResponse,
    StreamResponse,
    TextResponse,
)
from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest

from .common import route
from .document_service import (
    _artifact_event_document_path,
    _document_zoom_from_params,
    _ensure_document_target,
    document_target_html,
)


def _preview(request: RouteRequest) -> HtmlResponse:
    try:
        params = request.params
        root = request.state.active_project_root(request.context_id)
        path = str((params.get("path") or [""])[0])
        title = str((params.get("title") or [""])[0]).strip() or None
        page, status = document_target_html(
            root,
            path,
            title=title,
            embedded=(params.get("embed") or ["0"])[0] == "1",
            create_missing=(params.get("create") or ["0"])[0] == "1",
            zoom_percent=_document_zoom_from_params(params),
        )
    except Exception as error:
        return HtmlResponse(
            f"<p>{html.escape(str(error))}</p>",
            status=HTTPStatus.CONFLICT,
        )
    return HtmlResponse(page, status=status)


def _export(request: RouteRequest) -> ServiceResponse:
    params = request.params
    artifact = str((params.get("artifact") or [""])[0]).strip()
    requested_path = str((params.get("path") or [""])[0])
    export_format = str((params.get("format") or ["markdown"])[0])
    try:
        root = Path(request.state.active_project_root(request.context_id)).resolve()
        if artifact == "document" and requested_path:
            _ensure_document_target(root, requested_path)
        document_path = _artifact_event_document_path(
            root,
            artifact,
            requested_path,
        )
        relative_path = document_path.relative_to(root).as_posix()
        exported = export_markdown_document(
            document_path,
            relative_path,
            export_format,
        )
    except Exception as error:
        return TextResponse(str(error), status=HTTPStatus.CONFLICT)
    return BinaryResponse(
        exported.data,
        exported.content_type,
        filename=exported.filename,
    )


def _events(request: RouteRequest) -> ServiceResponse:
    params = request.params
    artifact = str((params.get("artifact") or [""])[0]).strip()
    try:
        root = request.state.active_project_root(request.context_id)
        path = _artifact_event_document_path(
            root,
            artifact,
            str((params.get("path") or [""])[0]),
        )
    except Exception as error:
        return JsonResponse({"error": str(error)}, status=HTTPStatus.CONFLICT)
    return StreamResponse(lambda: request.stream_artifact_events(artifact, path))


_HANDLERS = {"preview": _preview, "export": _export, "events": _events}


def module() -> ServiceModule:
    return ServiceModule(
        id="markdown_documents",
        label="Markdown Documents",
        routes=(
            route("GET", "/artifacts/document", "markdown_documents", "preview"),
            route("GET", "/api/documents/export", "markdown_documents", "export"),
            route("GET", "/api/artifacts/events", "markdown_documents", "events"),
        ),
        handlers=_HANDLERS,
        assets=("js/modules/documents.js",),
        asset_package="electroboy.modules",
        capabilities=frozenset({"markdown-preview", "markdown-edit", "export"}),
        state_namespace="markdown_documents",
    )
