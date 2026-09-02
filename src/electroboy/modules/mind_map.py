"""Mind Map capability module declaration."""

from __future__ import annotations

import base64
import html
import mimetypes
import posixpath
import zipfile
from http import HTTPStatus
from pathlib import Path
from xml.etree import ElementTree

from electroboy.service.http import (
    BinaryResponse,
    HtmlResponse,
    JsonResponse,
    ServiceResponse,
)
from electroboy.service.mind_map import MindMapProvider, MindMapWorkflowController
from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest
from electroboy.state_store import StateError

from .agenda_workspace import normalize_agenda_style
from .common import conflict, route
from .editable_mind_map_workspace import render_editable_mind_map_html
from .mind_map_documents import (
    default_mind_map_path,
    empty_mind_map,
    list_mind_maps,
    load_mind_map,
    save_mind_map,
)
from .mind_map_workspace import render_mind_map_html


def _provider(request: RouteRequest) -> MindMapProvider:
    context = request.services.contexts.require(request.context_id)
    if not context.workflow_id:
        raise StateError("activate a workflow project first")
    controller = request.services.workflows.controller(
        context.workflow_id,
        MindMapWorkflowController,
    )
    provider = controller.get_mind_map_provider()
    requested = str(
        (request.params.get("provider") or [provider.provider_id])[0]
    ).strip()
    if requested and requested != provider.provider_id:
        raise StateError(f"mind map provider is not active: {requested}")
    return provider


def _filters(request: RouteRequest) -> dict[str, str]:
    return {
        key.removeprefix("filter."): str(values[0])
        for key, values in request.params.items()
        if key.startswith("filter.") and values
    }


def _style(request: RouteRequest) -> str:
    return normalize_agenda_style((request.params.get("style") or ["default"])[0])


def _load(request: RouteRequest) -> dict[str, object]:
    return _provider(request).load_mind_map(
        request.context_id,
        filters=_filters(request),
        connection_id=request.connection_id,
    )


def _view(request: RouteRequest) -> HtmlResponse:
    try:
        path = str((request.params.get("path") or [""])[0]).strip()
        if path:
            root = request.services.contexts.active_project_root(request.context_id)
            page, status = render_editable_mind_map_html(
                load_mind_map(root, path),
                context_id=request.context_id,
                connection_id=request.connection_id,
                lease_token=request.lease_token,
            )
        else:
            page, status = render_mind_map_html(_load(request), style=_style(request))
    except Exception as error:
        return HtmlResponse(
            f'<section role="alert"><p>{html.escape(str(error))}</p></section>',
            status=HTTPStatus.CONFLICT,
        )
    return HtmlResponse(page, status=status)


def _mind_map(request: RouteRequest) -> ServiceResponse:
    try:
        payload = _load(request)
    except Exception as error:
        return conflict(error)
    return JsonResponse(payload)


def _documents(request: RouteRequest) -> ServiceResponse:
    try:
        root = request.services.contexts.active_project_root(request.context_id)
        return JsonResponse({"mind_maps": list_mind_maps(root)})
    except Exception as error:
        return conflict(error)


def _document(request: RouteRequest) -> ServiceResponse:
    try:
        root = request.services.contexts.active_project_root(request.context_id)
        path = str((request.params.get("path") or [""])[0])
        return JsonResponse(load_mind_map(root, path))
    except Exception as error:
        return conflict(error)


def _create_document(request: RouteRequest) -> ServiceResponse:
    try:
        root = request.services.contexts.active_project_root(request.context_id)
        body = request.body()
        title = str(body.get("title") or "Untitled mind map").strip()
        path = str(body.get("path") or default_mind_map_path(title))
        document = (
            body["document"] if "document" in body else empty_mind_map(title)
        )
        return JsonResponse(save_mind_map(root, path, document, create=True))
    except Exception as error:
        return conflict(error)


def _save_document(request: RouteRequest) -> ServiceResponse:
    try:
        root = request.services.contexts.active_project_root(request.context_id)
        body = request.body()
        revision = body.get("expected_revision")
        return JsonResponse(
            save_mind_map(
                root,
                str(body.get("path") or ""),
                body.get("document"),
                expected_revision=None if revision is None else str(revision),
            )
        )
    except Exception as error:
        return conflict(error)


def _link_content(request: RouteRequest) -> ServiceResponse:
    try:
        root = request.services.contexts.active_project_root(request.context_id)
        raw_path = str((request.params.get("path") or [""])[0]).strip()
        if not raw_path:
            raise StateError("linked file path is required")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve(strict=True)
        if not path.is_file():
            raise StateError("linked path must refer to a file")
        allowed_suffixes = {
            ".docx",
            ".gif",
            ".jpeg",
            ".jpg",
            ".json",
            ".pdf",
            ".png",
            ".txt",
            ".webp",
        }
        if path.suffix.lower() not in allowed_suffixes:
            raise StateError("linked file format is not supported for preview")
        if path.suffix.lower() == ".docx":
            return HtmlResponse(_docx_preview(path))
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return BinaryResponse(path.read_bytes(), content_type)
    except Exception as error:
        return conflict(error)


def _docx_preview(path: Path) -> str:
    """Return a safe, dependency-free preview of DOCX text and images."""

    word = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    relationships = (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    )
    package_relationships = (
        "http://schemas.openxmlformats.org/package/2006/relationships"
    )
    drawing = "http://schemas.openxmlformats.org/drawingml/2006/main"
    with zipfile.ZipFile(path) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
        relationship_targets: dict[str, str] = {}
        try:
            relationship_document = ElementTree.fromstring(
                archive.read("word/_rels/document.xml.rels")
            )
            for relation in relationship_document.findall(
                f"{{{package_relationships}}}Relationship"
            ):
                relationship_targets[str(relation.get("Id") or "")] = str(
                    relation.get("Target") or ""
                )
        except KeyError:
            pass

        blocks: list[str] = []
        for paragraph in document.iter(f"{{{word}}}p"):
            text = "".join(
                node.text or "" for node in paragraph.iter(f"{{{word}}}t")
            ).strip()
            if text:
                blocks.append(f"<p>{html.escape(text)}</p>")
            for image in paragraph.iter(f"{{{drawing}}}blip"):
                relation_id = image.get(f"{{{relationships}}}embed") or ""
                target = relationship_targets.get(relation_id, "")
                if not target:
                    continue
                entry = posixpath.normpath(posixpath.join("word", target))
                if not entry.startswith("word/media/"):
                    continue
                try:
                    data = archive.read(entry)
                except KeyError:
                    continue
                content_type = mimetypes.guess_type(entry)[0] or "image/png"
                encoded = base64.b64encode(data).decode("ascii")
                blocks.append(
                    f'<img src="data:{content_type};base64,{encoded}" '
                    'alt="Embedded document image">'
                )
    title = html.escape(path.name)
    content = "".join(blocks) or "<p>This document has no previewable content.</p>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:70rem;margin:2rem auto;
padding:0 2rem;color:#202632}}img{{max-width:100%;height:auto}}</style></head>
<body><h1>{title}</h1>{content}</body></html>"""


_HANDLERS = {
    "view": _view,
    "mind_map": _mind_map,
    "documents": _documents,
    "document": _document,
    "create_document": _create_document,
    "save_document": _save_document,
    "link_content": _link_content,
}


def module() -> ServiceModule:
    return ServiceModule(
        id="mind_map",
        label="Mind Map",
        routes=(
            route("GET", "/artifacts/mind-map", "mind_map", "view"),
            route("GET", "/api/mind-map", "mind_map", "mind_map"),
            route("GET", "/api/mind-map/documents", "mind_map", "documents"),
            route("GET", "/api/mind-map/document", "mind_map", "document"),
            route("POST", "/api/mind-map/documents", "mind_map", "create_document"),
            route("POST", "/api/mind-map/document", "mind_map", "save_document"),
            route("GET", "/api/mind-map/link-content", "mind_map", "link_content"),
        ),
        handlers=_HANDLERS,
        assets=(
            "css/mind-map-pane-tools.css",
            "js/modules/mind-map.js",
            "js/modules/mind-map-pane-tools.js",
        ),
        asset_package="electroboy.modules",
        capabilities=frozenset(
            {
                "mind-map-provider",
                "mind-map-source-trace",
                "mind-map-pan-zoom",
                "mind-map-relationship-modes",
                "mind-map-styles",
                "editable-mind-map",
                "mind-map-documents",
            }
        ),
        state_namespace="mind_map",
    )
