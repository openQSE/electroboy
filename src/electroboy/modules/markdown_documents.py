"""Markdown document capability module declaration."""

from __future__ import annotations

import html
import json
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
from electroboy.service.registry import AgentRuleDefinition, ServiceModule
from electroboy.service.routes import RouteRequest

from .common import route
from .document_service import (
    _artifact_event_document_path,
    _document_image_asset,
    _document_target_path,
    _document_zoom_from_params,
    _ensure_document_target,
    document_target_html,
)

_DOCUMENT_ASSET_CONTEXT_KEYS = (
    "context_id",
    "workspace_id",
    "connection_id",
    "lease_token",
    "telemetry_page_id",
    "telemetry_tab_id",
)


def _preview(request: RouteRequest) -> HtmlResponse:
    try:
        params = request.params
        root = request.services.contexts.active_project_root(request.context_id)
        path = str((params.get("path") or [""])[0])
        title = str((params.get("title") or [""])[0]).strip() or None
        page, status = document_target_html(
            root,
            path,
            title=title,
            embedded=(params.get("embed") or ["0"])[0] == "1",
            create_missing=(params.get("create") or ["0"])[0] == "1",
            zoom_percent=_document_zoom_from_params(params),
            asset_context={
                key: str((params.get(key) or [""])[0])
                for key in _DOCUMENT_ASSET_CONTEXT_KEYS
                if (params.get(key) or [""])[0]
            },
        )
    except Exception as error:
        return HtmlResponse(
            f"<p>{html.escape(str(error))}</p>",
            status=HTTPStatus.CONFLICT,
        )
    return HtmlResponse(page, status=status)


def _image(request: RouteRequest) -> ServiceResponse:
    params = request.params
    document_target = str((params.get("document_path") or [""])[0])
    image_source = str((params.get("image_path") or [""])[0])
    try:
        root = request.services.contexts.active_project_root(request.context_id)
        image_path, content_type = _document_image_asset(
            root,
            document_target,
            image_source,
        )
        data = image_path.read_bytes()
    except Exception as error:
        return TextResponse(str(error), status=HTTPStatus.CONFLICT)
    return BinaryResponse(data, content_type)


def _export(request: RouteRequest) -> ServiceResponse:
    params = request.params
    artifact = str((params.get("artifact") or [""])[0]).strip()
    requested_path = str((params.get("path") or [""])[0])
    export_format = str((params.get("format") or ["markdown"])[0])
    try:
        root = Path(
            request.services.contexts.active_project_root(request.context_id)
        ).resolve()
        if artifact == "document" and requested_path:
            _ensure_document_target(root, requested_path)
        document_path = _artifact_event_document_path(
            root,
            artifact,
            requested_path,
        )
        relative_path = _document_target_path(root, str(document_path))[0]
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
    try:
        root = request.services.contexts.active_project_root(request.context_id)
        encoded_targets = str((params.get("targets") or [""])[0]).strip()
        requested_targets = json.loads(encoded_targets) if encoded_targets else [
            {
                "artifact": str((params.get("artifact") or [""])[0]),
                "path": str((params.get("path") or [""])[0]),
            }
        ]
        if not isinstance(requested_targets, list) or not requested_targets:
            raise ValueError("at least one artifact target is required")
        targets: list[tuple[str, Path]] = []
        seen: set[tuple[str, Path]] = set()
        for target in requested_targets:
            if not isinstance(target, dict):
                raise ValueError("artifact targets must be objects")
            artifact = str(target.get("artifact") or "").strip()
            path = _artifact_event_document_path(
                root,
                artifact,
                str(target.get("path") or ""),
            )
            key = (artifact, path)
            if key not in seen:
                seen.add(key)
                targets.append(key)
    except Exception as error:
        return JsonResponse({"error": str(error)}, status=HTTPStatus.CONFLICT)
    return StreamResponse(lambda: request.stream_artifact_events(targets))


_HANDLERS = {
    "preview": _preview,
    "image": _image,
    "export": _export,
    "events": _events,
}

_MARKDOWN_DOCUMENT_RULES = AgentRuleDefinition(
    id="markdown-documents.naming",
    label="Document Naming",
    priority=10,
    content="""\
When the operator asks to create a document without naming it, recommend a
conventional path before creating the file. Follow an established repository
convention when one exists. Otherwise, use lowercase kebab-case Markdown names
under `docs/`, such as `docs/error-recovery.md`.

Preserve conventional project names such as `README.md`, `CHANGELOG.md`, and
license files. Naming is a recommendation. Use the operator's requested name
when they specify one.""",
)


def module() -> ServiceModule:
    return ServiceModule(
        id="markdown_documents",
        label="Markdown Documents",
        routes=(
            route("GET", "/artifacts/document", "markdown_documents", "preview"),
            route(
                "GET",
                "/artifacts/document-image",
                "markdown_documents",
                "image",
            ),
            route("GET", "/api/documents/export", "markdown_documents", "export"),
            route("GET", "/api/artifacts/events", "markdown_documents", "events"),
        ),
        handlers=_HANDLERS,
        assets=(
            "js/modules/document-navigation.js",
            "js/modules/documents.js",
            "js/modules/file-pane-tools.js",
        ),
        asset_package="electroboy.modules",
        capabilities=frozenset({"markdown-preview", "markdown-edit", "export"}),
        agent_rules=(_MARKDOWN_DOCUMENT_RULES,),
        state_namespace="markdown_documents",
    )
