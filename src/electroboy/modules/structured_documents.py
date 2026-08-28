"""Structured document capability module declaration."""

from __future__ import annotations

import html
from http import HTTPStatus

from electroboy.service.http import HtmlResponse, JsonResponse, ServiceResponse
from electroboy.service.registry import AgentRuleDefinition, ServiceModule
from electroboy.service.routes import RouteRequest

from .common import conflict, route
from .document_service import (
    _artifact_editor_font_size_from_params,
    _document_zoom_from_params,
    artifact_editor_html,
    design_document_html,
    requirements_document_html,
    save_artifact_edit,
    stage_document_html,
)


def _editor(request: RouteRequest) -> HtmlResponse:
    try:
        params = request.params
        root = request.services.contexts.active_project_root(request.context_id)
        artifact = str((params.get("artifact") or [""])[0]).strip()
        requested_path = str((params.get("path") or [""])[0])
        title = str((params.get("title") or [""])[0]).strip() or None
        create_missing = str((params.get("create") or [""])[0]) == "1"
        rich_editor = (
            request.services.contexts.project_mode(request.context_id) == "creative"
            and artifact == "document"
        )
        font_size = _artifact_editor_font_size_from_params(params)
        page, status = artifact_editor_html(
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
        return HtmlResponse(
            f"<p>{html.escape(str(error))}</p>",
            status=HTTPStatus.CONFLICT,
        )
    return HtmlResponse(page, status=status)


def _save(request: RouteRequest) -> ServiceResponse:
    try:
        root = request.services.contexts.active_project_root(request.context_id)
        payload = request.body()
        result = save_artifact_edit(
            root,
            str(payload.get("artifact") or ""),
            str(payload.get("path") or ""),
            payload,
        )
    except Exception as error:
        return conflict(error)
    return JsonResponse(result)


def _view(request: RouteRequest) -> HtmlResponse:
    artifact = request.path.removeprefix("/artifacts/")
    try:
        if artifact == "requirements":
            root = request.services.contexts.requirements_document_root(
                request.context_id
            )
            embedded = str((request.params.get("embed") or [""])[0]) == "1"
            zoom = _document_zoom_from_params(request.params)
            page, status = requirements_document_html(
                root,
                embedded=embedded,
                zoom_percent=zoom,
            )
        elif artifact == "design":
            root = request.services.contexts.active_project_root(request.context_id)
            page, status = design_document_html(root)
        else:
            root = request.services.contexts.active_project_root(request.context_id)
            stage = {
                "implementation-log": "implementation-log",
                "implementation-report": "code",
                "validation-report": "validate",
            }.get(artifact, artifact)
            page, status = stage_document_html(root, stage)
    except Exception as error:
        return HtmlResponse(
            f"<p>{html.escape(str(error))}</p>",
            status=HTTPStatus.CONFLICT,
        )
    return HtmlResponse(page, status=status)


_HANDLERS = {"editor": _editor, "save": _save, "view": _view}

_STRUCTURED_DOCUMENT_RULES = AgentRuleDefinition(
    id="structured-documents.source-of-truth",
    label="Structured Document Sources",
    priority=20,
    content="""\
The following rules are required when a document has a JSONL source and a
generated Markdown companion.

- Edit the JSONL file as the source of truth. Do not edit its generated
  Markdown companion by hand.
- Keep stable record identifiers in record fields rather than title text. Use
  human-readable titles.
- Preserve hierarchy with `parent_id` or `heading_level` instead of flattening
  the outline.
- Put prose, lists, tables, and Mermaid diagrams in Markdown-capable body
  fields.
- After changing a source, run `electroboy render-artifact <artifact>` to
  validate the JSONL and regenerate the Markdown companion.
- Inspect the existing records before editing. Preserve schema fields and
  record identifiers that are unrelated to the requested change.

These rules apply regardless of the agent role that performs the edit.""",
)


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
                "/artifacts/implementation-log",
                "structured_documents",
                "view",
            ),
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
        agent_rules=(_STRUCTURED_DOCUMENT_RULES,),
        state_namespace="structured_documents",
    )
