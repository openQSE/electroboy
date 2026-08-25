"""Document rendering, editing, and structured artifact operations."""

from __future__ import annotations

import html
import json
import re
from http import HTTPStatus
from pathlib import Path

from electroboy.feature_artifacts import (
    artifact_paths_for_run,
    resolve_artifact_path,
)
from electroboy.service.sessions import AgentSessionError
from electroboy.state_store import StateError, StateStore
from electroboy.structured_artifacts import (
    ARTIFACT_DEFAULT_MARKDOWN_PATHS,
    ARTIFACT_TITLES,
    artifact_jsonl_path,
    artifact_markdown_path,
    import_artifact,
    read_artifact_records,
    render_artifact,
)

_STAGE_DOCUMENT_CONFIG = {
    "implementation-plan": {
        "artifact_path": "docs/implementation-plan.md",
        "artifact_title": "Implementation Plan",
    },
    "code": {
        "artifact_path": "docs/implementation-report.md",
        "artifact_title": "Implementation Report",
    },
    "implementation-log": {
        "artifact_path": "docs/implementation-log.md",
        "artifact_title": "Implementation Log",
    },
    "test-plan": {
        "artifact_path": "docs/test-plan.md",
        "artifact_title": "Test Plan",
    },
    "validate": {
        "artifact_path": "docs/validation-report.md",
        "artifact_title": "Validation Report",
    },
}


def _generic_stage_config(stage: str) -> dict[str, object]:
    try:
        return _STAGE_DOCUMENT_CONFIG[stage]
    except KeyError as error:
        raise AgentSessionError(f"unsupported workflow stage: {stage}") from error


ARTIFACT_EVENT_ROUTE_PATHS = {
    "/artifacts/requirements": "docs/requirements.md",
    "/artifacts/design": "docs/detailed-design.md",
    "/artifacts/design-review": "docs/design-review.md",
    "/artifacts/implementation-plan": "docs/implementation-plan.md",
    "/artifacts/implementation-log": "docs/implementation-log.md",
    "/artifacts/implementation-report": "docs/implementation-report.md",
    "/artifacts/test-plan": "docs/test-plan.md",
    "/artifacts/validation-report": "docs/validation-report.md",
}

STRUCTURED_ARTIFACT_BY_MARKDOWN_PATH = {
    path: artifact
    for artifact, path in ARTIFACT_DEFAULT_MARKDOWN_PATHS.items()
}

ARTIFACT_EDITOR_LIST_FIELDS = {
    "acceptance_criteria",
    "commit_tasks",
    "consequences",
    "dependencies",
    "design_sections",
    "expected_results",
    "exit_criteria",
    "implementation_units",
    "interfaces",
    "out_of_scope",
    "paths",
    "personas",
    "plan_tasks",
    "preconditions",
    "requirements",
    "scope",
    "steps",
    "verification",
}

ARTIFACT_EDITOR_JSON_FIELDS = {"automation", "schema"}


def requirements_document_html(
    project_root: Path | str,
    *,
    embedded: bool = False,
    zoom_percent: int = 100,
) -> tuple[str, HTTPStatus]:
    relative_path = _resolved_artifact_relative_path(
        project_root,
        "docs/requirements.md",
    )
    return markdown_document_html(
        project_root,
        relative_path,
        "Requirements",
        "Requirements document does not exist yet.",
        embedded=embedded,
        zoom_percent=zoom_percent,
    )


def design_document_html(project_root: Path | str) -> tuple[str, HTTPStatus]:
    relative_path = _resolved_artifact_relative_path(
        project_root,
        "docs/detailed-design.md",
    )
    return markdown_document_html(
        project_root,
        relative_path,
        "Design",
        "Design document does not exist yet.",
    )


def design_review_document_html(project_root: Path | str) -> tuple[str, HTTPStatus]:
    relative_path = _resolved_artifact_relative_path(
        project_root,
        "docs/design-review.md",
    )
    return markdown_document_html(
        project_root,
        relative_path,
        "Design Review",
        "Design review document does not exist yet.",
    )


def stage_document_html(
    project_root: Path | str,
    stage: str,
) -> tuple[str, HTTPStatus]:
    config = _generic_stage_config(stage)
    title = str(config["artifact_title"])
    relative_path = _resolved_artifact_relative_path(
        project_root,
        str(config["artifact_path"]),
    )
    return markdown_document_html(
        project_root,
        relative_path,
        title,
        f"{title} document does not exist yet.",
    )


def document_target_html(
    project_root: Path | str,
    relative_path: str,
    *,
    title: str | None = None,
    embedded: bool = False,
    create_missing: bool = False,
    zoom_percent: int = 100,
) -> tuple[str, HTTPStatus]:
    normalized_path = (
        _ensure_document_target(project_root, relative_path)
        if create_missing
        else _document_target_path(project_root, relative_path)[0]
    )
    display_title = title or normalized_path
    return markdown_document_html(
        project_root,
        normalized_path,
        display_title,
        f"{normalized_path} document does not exist yet.",
        embedded=embedded,
        zoom_percent=zoom_percent,
    )


def artifact_editor_html(
    project_root: Path | str,
    artifact: str,
    requested_path: str = "",
    *,
    title: str | None = None,
    create_missing: bool = False,
    context_id: str = "",
    rich_editor: bool = False,
    editor_font_size: int | None = None,
) -> tuple[str, HTTPStatus]:
    """Return a live editor page for a Markdown or structured artifact."""

    project_root = Path(project_root).expanduser().resolve()
    edit_data = _artifact_edit_payload(
        project_root,
        artifact,
        requested_path,
        title=title,
        create_missing=create_missing,
        rich_editor=rich_editor,
        editor_font_size=editor_font_size,
    )
    edit_data["context_id"] = context_id
    page = _artifact_editor_page(edit_data)
    return page, HTTPStatus.OK


def markdown_document_html(
    project_root: Path | str,
    relative_path: str,
    title: str,
    missing_message: str,
    *,
    embedded: bool = False,
    zoom_percent: int = 100,
) -> tuple[str, HTTPStatus]:
    project_root = Path(project_root).expanduser().resolve()
    document_path = project_root / relative_path
    if document_path.exists():
        text = document_path.read_text(encoding="utf-8")
        body = _render_markdown(text)
        status = HTTPStatus.OK
    else:
        body = f"<p>{html.escape(missing_message)}</p>"
        status = HTTPStatus.NOT_FOUND
    main_max_width = "none" if embedded else "880px"
    main_margin = "0" if embedded else "0 auto"
    main_padding = "16px" if embedded else "40px 24px 64px"
    article_padding = "18px" if embedded else "28px"
    article_radius = "0" if embedded else "8px"
    article_border = "0" if embedded else "1px solid var(--doc-border)"
    zoom_percent = _clamp_document_zoom(zoom_percent)
    document_font_size = 16 * (zoom_percent / 100)
    mermaid_script = _mermaid_script(body)
    document_link_script = _document_link_script(relative_path)
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: dark;
      --doc-bg: #10141f;
      --doc-surface: #10141f;
      --doc-text: #e7edf7;
      --doc-heading: #ffffff;
      --doc-link: #66d9e8;
      --doc-muted: #aab8cf;
      --doc-border: #2a3142;
      --doc-code-bg: #151b29;
      --doc-code-text: #e7edf7;
      --doc-table-head: #151b29;
      --doc-accent: #8bd8ca;
      --doc-font-size: {document_font_size:.2f}px;
    }}
    html {{
      background: var(--doc-bg);
    }}
    body {{
      margin: 0;
      background: var(--doc-bg);
      color: var(--doc-text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: var(--doc-font-size);
      line-height: 1.55;
    }}
    main {{
      max-width: {main_max_width};
      margin: {main_margin};
      padding: {main_padding};
    }}
    article {{
      background: var(--doc-surface);
      border: {article_border};
      border-radius: {article_radius};
      color: var(--doc-text);
      padding: {article_padding};
    }}
    article, article :where(p, li, td, dd, strong, em, summary, details, figcaption) {{
      color: var(--doc-text);
    }}
    h1, h2, h3, h4, h5, h6 {{
      color: var(--doc-heading);
      line-height: 1.2;
    }}
    a {{
      color: var(--doc-link);
    }}
    blockquote {{
      margin-left: 0;
      border-left: 4px solid var(--doc-accent);
      color: var(--doc-muted);
      padding-left: 14px;
    }}
    hr {{
      border: 0;
      border-top: 1px solid var(--doc-border);
    }}
    img {{
      max-width: 100%;
      height: auto;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
    }}
    th, td {{
      border: 1px solid var(--doc-border);
      padding: 8px 10px;
    }}
    th {{
      background: var(--doc-table-head);
      color: var(--doc-heading);
    }}
    pre, code {{
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    }}
    code {{
      color: var(--doc-code-text);
      background: var(--doc-code-bg);
      border-radius: 4px;
      padding: 1px 4px;
    }}
    pre {{
      overflow: auto;
      padding: 12px;
      background: var(--doc-code-bg);
      color: var(--doc-code-text);
      border: 1px solid var(--doc-border);
      border-radius: 6px;
    }}
    pre code {{
      background: transparent;
      border-radius: 0;
      padding: 0;
    }}
    .mermaid {{
      display: flex;
      justify-content: center;
      overflow: auto;
      margin: 16px 0;
      padding: 14px;
      border: 1px solid var(--doc-border);
      border-radius: 6px;
      background: var(--doc-code-bg);
      cursor: zoom-in;
      transition: border-color 120ms ease, background 120ms ease;
    }}
    .mermaid:hover,
    .mermaid:focus-visible {{
      border-color: var(--doc-accent);
      outline: none;
    }}
    .mermaid svg {{
      max-width: 100%;
      height: auto;
    }}
  </style>
  {mermaid_script}
</head>
<body>
  <main>
    <article>
      {body}
    </article>
  </main>
  {document_link_script}
</body>
</html>
"""
    return page, status


def _clamp_document_zoom(value: int) -> int:
    stepped = int(((value + 5) // 10) * 10)
    return max(70, min(180, stepped))


def _document_zoom_from_params(params: dict[str, list[str]]) -> int:
    raw = params.get("zoom", ["100"])[0]
    try:
        return _clamp_document_zoom(int(raw))
    except (TypeError, ValueError):
        return 100


def _clamp_artifact_editor_font_size(value: object) -> int:
    try:
        requested = int(value) if value is not None else 16
    except (TypeError, ValueError):
        requested = 16
    return max(11, min(28, requested))


def _artifact_editor_font_size_from_params(params: dict[str, list[str]]) -> int:
    raw_font_size = (params.get("font_size") or [""])[0]
    if raw_font_size:
        return _clamp_artifact_editor_font_size(raw_font_size)
    raw_zoom = (params.get("document_zoom") or params.get("zoom") or [""])[0]
    try:
        zoom = _clamp_document_zoom(int(raw_zoom))
    except (TypeError, ValueError):
        zoom = 100
    return _clamp_artifact_editor_font_size(round(16 * (zoom / 100)))


def _normalize_document_target_path(relative_path: str) -> str:
    raw = relative_path.strip().replace("\\", "/")
    if not raw:
        raise StateError("document path is required")
    path = Path(raw)
    if path.is_absolute():
        raise StateError("document path must be relative")
    if any(part in {"..", ""} for part in path.parts):
        raise StateError("document path cannot escape the project")
    if path.suffix.lower() != ".md":
        raise StateError("document path must be a markdown file")
    return path.as_posix()


def _ensure_document_target(project_root: Path | str, relative_path: str) -> str:
    normalized_path, document_path = _document_target_path(project_root, relative_path)
    if not document_path.exists():
        document_path.parent.mkdir(parents=True, exist_ok=True)
        document_path.write_text(
            _document_starter_markdown(normalized_path),
            encoding="utf-8",
        )
    if not document_path.is_file():
        raise StateError("document path must refer to a file")
    if not document_path.read_text(encoding="utf-8").strip():
        document_path.write_text(
            _document_starter_markdown(normalized_path),
            encoding="utf-8",
        )
    return normalized_path


def _document_starter_markdown(relative_path: str) -> str:
    title = _document_starter_title(relative_path)
    return f"# {title}\n\n## Overview\n\n## Notes\n"


def _document_starter_title(relative_path: str) -> str:
    stem = Path(relative_path).stem.strip()
    if not stem:
        return "Document"
    if stem.lower() == "readme":
        return "README"
    if stem.lower() == "api":
        return "API"
    return stem.replace("-", " ").replace("_", " ").title()


def _artifact_edit_payload(
    project_root: Path,
    artifact: str,
    requested_path: str,
    *,
    title: str | None = None,
    create_missing: bool = False,
    rich_editor: bool = False,
    editor_font_size: int | None = None,
) -> dict[str, object]:
    artifact = artifact.strip()
    editor_font_size = _clamp_artifact_editor_font_size(editor_font_size)
    structured_artifact, markdown_path = _structured_artifact_for_edit_request(
        project_root,
        artifact,
        requested_path,
    )
    if structured_artifact:
        records, jsonl_path = _ensure_structured_edit_records(
            project_root,
            structured_artifact,
            markdown_path,
        )
        return {
            "mode": "structured",
            "artifact": artifact,
            "artifact_name": structured_artifact,
            "path": requested_path,
            "title": title or ARTIFACT_TITLES[structured_artifact],
            "markdown_path": markdown_path,
            "jsonl_path": jsonl_path,
            "records": records,
            "list_fields": sorted(ARTIFACT_EDITOR_LIST_FIELDS),
            "json_fields": sorted(ARTIFACT_EDITOR_JSON_FIELDS),
            "editor_font_size": editor_font_size,
        }

    if artifact == "document":
        markdown_path = (
            _ensure_document_target(project_root, requested_path)
            if create_missing
            else _document_target_path(project_root, requested_path)[0]
        )
        document_path = _document_target_path(project_root, markdown_path)[1]
    else:
        document_path = _artifact_event_document_path(
            project_root,
            artifact,
            requested_path,
        )
        markdown_path = document_path.relative_to(project_root).as_posix()
    if not document_path.exists():
        document_path.parent.mkdir(parents=True, exist_ok=True)
        document_path.write_text(
            _document_starter_markdown(markdown_path),
            encoding="utf-8",
        )
    return {
        "mode": "markdown",
        "artifact": artifact,
        "path": requested_path,
        "title": title or markdown_path,
        "markdown_path": markdown_path,
        "markdown": document_path.read_text(encoding="utf-8"),
        "rich_editor": bool(rich_editor and artifact == "document"),
        "editor_font_size": editor_font_size,
    }


def _structured_artifact_for_edit_request(
    project_root: Path,
    artifact: str,
    requested_path: str,
) -> tuple[str | None, str]:
    if artifact == "requirements":
        structured_artifact = "requirements"
        return structured_artifact, artifact_markdown_path(project_root, structured_artifact)
    if artifact == "route":
        default_path = ARTIFACT_EVENT_ROUTE_PATHS.get(requested_path, "")
        structured_artifact = STRUCTURED_ARTIFACT_BY_MARKDOWN_PATH.get(default_path)
        if structured_artifact:
            return (
                structured_artifact,
                _resolved_artifact_relative_path(project_root, default_path),
            )
        return None, default_path
    if artifact == "document" and requested_path:
        try:
            markdown_path = _document_target_path(project_root, requested_path)[0]
        except StateError:
            return None, ""
        for structured_artifact in ARTIFACT_DEFAULT_MARKDOWN_PATHS:
            if markdown_path == artifact_markdown_path(project_root, structured_artifact):
                return structured_artifact, markdown_path
    return None, ""


def _ensure_structured_edit_records(
    project_root: Path,
    artifact: str,
    markdown_path: str,
) -> tuple[list[dict[str, object]], str]:
    jsonl_path = artifact_jsonl_path(project_root, artifact, markdown_path)
    jsonl_file = _safe_project_document_path(project_root, jsonl_path)
    if jsonl_file.exists():
        return read_artifact_records(project_root, jsonl_path), jsonl_path

    markdown_file = _safe_project_document_path(project_root, markdown_path)
    if markdown_file.exists():
        import_artifact(
            project_root,
            artifact,
            markdown_path=markdown_path,
            jsonl_path=jsonl_path,
        )
        return read_artifact_records(project_root, jsonl_path), jsonl_path

    records = [
        {
            "schema_version": 1,
            "artifact_type": artifact,
            "record_type": "document",
            "id": _artifact_document_record_id(artifact),
            "order": 0,
            "title": ARTIFACT_TITLES[artifact],
            "body": "",
            "status": "draft",
        }
    ]
    _write_artifact_records(project_root, jsonl_path, records, artifact)
    render_artifact(
        project_root,
        artifact,
        jsonl_path=jsonl_path,
        markdown_path=markdown_path,
    )
    return records, jsonl_path


def _artifact_document_record_id(artifact: str) -> str:
    return {
        "requirements": "REQ-DOC",
        "design": "DES-DOC",
        "implementation-plan": "PLAN-DOC",
        "test-plan": "TEST-DOC",
    }.get(artifact, "DOC")


def _safe_project_document_path(project_root: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute():
        raise StateError("document path must be relative")
    resolved = (project_root / path).resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as error:
        raise StateError("document path cannot escape the project") from error
    return resolved


def _write_artifact_records(
    project_root: Path,
    jsonl_path: str,
    records: list[dict[str, object]],
    artifact: str,
) -> None:
    if not records:
        raise StateError("artifact must contain at least one record")
    normalized_records: list[dict[str, object]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise StateError(f"record {index + 1} must be an object")
        normalized = dict(record)
        normalized.setdefault("schema_version", 1)
        normalized.setdefault("artifact_type", artifact)
        normalized.setdefault("record_type", "section")
        normalized_records.append(normalized)
    output_path = _safe_project_document_path(project_root, jsonl_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in normalized_records)
        + "\n",
        encoding="utf-8",
    )


def save_artifact_edit(
    project_root: Path | str,
    artifact: str,
    requested_path: str,
    payload: dict[str, object],
) -> dict[str, object]:
    project_root = Path(project_root).expanduser().resolve()
    artifact = artifact.strip()
    mode = str(payload.get("mode") or "")
    structured_artifact, markdown_path = _structured_artifact_for_edit_request(
        project_root,
        artifact,
        requested_path,
    )
    if structured_artifact:
        records = payload.get("records")
        if not isinstance(records, list):
            raise StateError("records must be a list")
        jsonl_path = artifact_jsonl_path(project_root, structured_artifact, markdown_path)
        _write_artifact_records(
            project_root,
            jsonl_path,
            records,
            structured_artifact,
        )
        result = render_artifact(
            project_root,
            structured_artifact,
            jsonl_path=jsonl_path,
            markdown_path=markdown_path,
        )
        return {
            "status": "saved",
            "mode": "structured",
            "artifact": structured_artifact,
            "markdown_path": result.markdown_path,
            "jsonl_path": result.jsonl_path,
            "record_count": result.record_count,
        }

    if mode != "markdown":
        raise StateError("artifact is not backed by a structured JSONL document")
    markdown = str(payload.get("markdown") or "")
    document_path = _artifact_event_document_path(
        project_root,
        artifact,
        requested_path,
    )
    document_path.parent.mkdir(parents=True, exist_ok=True)
    document_path.write_text(markdown, encoding="utf-8")
    return {
        "status": "saved",
        "mode": "markdown",
        "markdown_path": document_path.relative_to(project_root).as_posix(),
    }


def _artifact_editor_page(edit_data: dict[str, object]) -> str:
    data_json = json.dumps(edit_data).replace("</", "<\\/")
    title = html.escape(str(edit_data.get("title") or "Artifact Editor"))
    editor_font_size = _clamp_artifact_editor_font_size(
        edit_data.get("editor_font_size")
    )
    rich_editor_script = (
        _rich_markdown_editor_script() if edit_data.get("rich_editor") else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} Editor</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #10141f;
      --panel: #151b29;
      --panel-soft: #1d2638;
      --text: #e7edf7;
      --muted: #aab8cf;
      --border: #2a3142;
      --accent: #66d9e8;
      --accent-strong: #1f6f8b;
      --dirty: #ffd43b;
      --ok: #8ce99a;
      --error: #ff8787;
      --editor-font-size: {editor_font_size}px;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      font-size: 14px;
    }}

    * {{
      box-sizing: border-box;
    }}

    html,
    body {{
      height: 100%;
      margin: 0;
      background: var(--bg);
      color: var(--text);
    }}

    body {{
      overflow: auto;
    }}

    body.markdown-mode {{
      overflow: hidden;
    }}

    main {{
      display: grid;
      gap: 14px;
      max-width: 1040px;
      margin: 0 auto;
      padding: 16px;
    }}

    body.markdown-mode main {{
      display: block;
      width: 100%;
      height: 100%;
      max-width: none;
      margin: 0;
      padding: 0;
    }}

    .editor-header,
    .record-editor,
    .markdown-editor {{
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
    }}

    .editor-header {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      padding: 12px;
    }}

    .editor-title {{
      min-width: 0;
    }}

    h1 {{
      margin: 0;
      font-size: 17px;
      line-height: 1.25;
    }}

    .editor-meta {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
    }}

    .editor-actions {{
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }}

    button,
    .editor-actions select {{
      min-height: 34px;
      border: 1px solid #364156;
      border-radius: 6px;
      background: var(--panel-soft);
      color: var(--text);
      cursor: pointer;
      font: inherit;
      font-weight: 650;
      padding: 0 12px;
    }}

    .editor-actions select {{
      min-width: 130px;
      cursor: pointer;
      font-weight: 500;
    }}

    button.primary {{
      border-color: var(--accent-strong);
      background: var(--accent-strong);
      color: #ffffff;
    }}

    button:disabled {{
      cursor: not-allowed;
      opacity: 0.55;
    }}

    .status {{
      color: var(--muted);
      min-height: 20px;
      font-size: 13px;
    }}

    .status.dirty {{
      color: var(--dirty);
    }}

    .status.saved {{
      color: var(--ok);
    }}

    .status.error {{
      color: var(--error);
    }}

    body.markdown-mode .editor-header {{
      position: sticky;
      top: 0;
      z-index: 3;
      border-width: 0 0 1px;
      border-radius: 0;
    }}

    body.markdown-mode .status {{
      position: fixed;
      right: 10px;
      bottom: 10px;
      z-index: 2;
      min-height: 0;
      border-radius: 999px;
      background: rgba(15, 20, 32, 0.9);
      color: var(--muted);
      padding: 4px 10px;
      box-shadow: 0 8px 22px rgba(0, 0, 0, 0.22);
      pointer-events: none;
    }}

    body.markdown-mode .status:empty {{
      display: none;
    }}

    body.markdown-mode .status.error {{
      color: var(--error);
    }}

    .records {{
      display: grid;
      gap: 10px;
    }}

    body.markdown-mode .records {{
      display: block;
      height: 100%;
    }}

    details.record-editor > summary {{
      cursor: pointer;
      padding: 12px;
      color: var(--text);
      font-weight: 650;
    }}

    .record-summary {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
    }}

    .record-summary-text {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    .record-summary-kind {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 500;
    }}

    .record-body {{
      display: grid;
      gap: 12px;
      border-top: 1px solid var(--border);
      padding: 12px;
    }}

    .record-actions {{
      display: flex;
      gap: 8px;
      justify-content: flex-end;
    }}

    .field-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
    }}

    label {{
      display: grid;
      gap: 5px;
      min-width: 0;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      text-transform: uppercase;
    }}

    input,
    select,
    textarea {{
      width: 100%;
      border: 1px solid #364156;
      border-radius: 6px;
      background: #0f1420;
      color: var(--text);
      font: inherit;
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      line-height: 1.45;
      padding: 8px;
      text-transform: none;
    }}

    textarea {{
      min-height: 92px;
      resize: vertical;
    }}

    textarea.body-field {{
      min-height: 180px;
      font-size: var(--editor-font-size);
    }}

    .generated-fields {{
      border: 1px dashed #364156;
      border-radius: 7px;
      background: #101725;
      color: var(--muted);
    }}

    .generated-fields > summary {{
      cursor: pointer;
      padding: 8px 10px;
      font-size: 12px;
      font-weight: 650;
      text-transform: uppercase;
    }}

    .generated-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 8px;
      padding: 0 10px 10px;
    }}

    .generated-field {{
      display: grid;
      gap: 3px;
      min-width: 0;
      font-size: 12px;
    }}

    .generated-field code {{
      overflow: hidden;
      border-radius: 4px;
      background: #0f1420;
      color: var(--text);
      padding: 4px 6px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    .markdown-editor {{
      display: grid;
      gap: 10px;
      padding: 12px;
    }}

    body.markdown-mode .markdown-editor {{
      display: block;
      height: 100%;
      border: 0;
      border-radius: 0;
      background: transparent;
      padding: 0;
    }}

    .markdown-editor textarea {{
      min-height: 62vh;
    }}

    body.markdown-mode .markdown-editor textarea {{
      display: block;
      width: 100%;
      height: 100%;
      min-height: 100%;
      border: 0;
      border-radius: 0;
      font-size: var(--editor-font-size);
      resize: none;
      padding: 14px 16px 36px;
    }}

    body.rich-markdown-mode .markdown-editor {{
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      min-height: 100%;
    }}

    .rich-toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
      border-bottom: 1px solid var(--border);
      background: #121827;
      padding: 8px;
    }}

    .rich-toolbar select,
    .rich-toolbar button {{
      min-height: 30px;
      border: 1px solid #354058;
      border-radius: 5px;
      background: #171f31;
      color: var(--text);
      font-size: 12px;
      padding: 0 9px;
    }}

    .rich-toolbar button {{
      min-width: 32px;
    }}

    .rich-toolbar button.active {{
      border-color: var(--accent);
      color: #ffffff;
      background: #1f3b4b;
    }}

    .rich-editor-surface {{
      min-height: 0;
      overflow: auto;
      background: #0f1420;
    }}

    .rich-editor-surface .tiptap {{
      min-height: 100%;
      font-size: var(--editor-font-size);
      outline: none;
      padding: 16px 18px 40px;
    }}

    .rich-editor-surface .tiptap > :first-child {{
      margin-top: 0;
    }}

    .rich-editor-surface .tiptap table {{
      border-collapse: collapse;
      width: 100%;
    }}

    .rich-editor-surface .tiptap th,
    .rich-editor-surface .tiptap td {{
      border: 1px solid var(--border);
      padding: 6px 8px;
      vertical-align: top;
    }}

    .rich-editor-surface .tiptap th {{
      background: #151b29;
    }}

    body.rich-markdown-mode .markdown-editor textarea.rich-source-fallback[hidden] {{
      display: none;
    }}

    .markdown-editor.rich-fallback {{
      grid-template-rows: auto minmax(0, 1fr);
    }}
  </style>
</head>
<body>
  <main>
    <header class="editor-header">
      <div class="editor-title">
        <h1>{title}</h1>
        <div id="editorMeta" class="editor-meta"></div>
      </div>
      <div class="editor-actions">
        <select id="recordType" aria-label="Record type to add">
          <option value="section">Section</option>
          <option value="requirement">Requirement</option>
          <option value="decision">Decision</option>
          <option value="interface">Interface</option>
          <option value="unit">Implementation unit</option>
          <option value="suite">Test suite</option>
          <option value="test">Test case</option>
        </select>
        <button id="addRecord" type="button">Add record</button>
        <button id="saveArtifact" class="primary" type="button" disabled>Save</button>
      </div>
    </header>
    <div id="status" class="status"></div>
    <section id="records" class="records"></section>
  </main>
  <script>
    const EDIT_DATA = {data_json};
    const LIST_FIELDS = new Set(EDIT_DATA.list_fields || []);
    const JSON_FIELDS = new Set(EDIT_DATA.json_fields || []);
    const RICH_EDITOR_ENABLED = Boolean(EDIT_DATA.rich_editor);
    const MIN_EDITOR_FONT_SIZE = 11;
    const MAX_EDITOR_FONT_SIZE = 28;
    const CORE_FIELDS = new Set([
      "schema_version",
      "artifact_type",
      "record_type",
      "id",
      "unit_id",
      "title",
      "order",
      "status",
      "phase",
      "sequence",
      "body",
    ]);
    const recordsRoot = document.getElementById("records");
    const recordType = document.getElementById("recordType");
    const addRecord = document.getElementById("addRecord");
    const saveArtifact = document.getElementById("saveArtifact");
    const statusLine = document.getElementById("status");
    const editorMeta = document.getElementById("editorMeta");
    let records = Array.isArray(EDIT_DATA.records)
      ? EDIT_DATA.records.map((record) => ({{ ...record }}))
      : [];
    let saveInFlight = false;
    let dirty = false;
    let markdownTextarea = null;
    let richMarkdownEditor = null;
    let richToolbar = null;
    let richEditorLoading = false;
    let editorFontSize = clampEditorFontSize(EDIT_DATA.editor_font_size || 16);

    const GENERATED_FIELDS = new Set([
      "schema_version",
      "artifact_type",
      "id",
      "unit_id",
      "order",
      "heading_level",
      "parent_id",
      "updated_at",
    ]);

    const COMMON_FIELDS = ["record_type", "title", "status", "body"];
    const RECORD_FIELDS = {{
      document: ["title", "summary", "scope", "out_of_scope", "personas", "status", "body"],
      section: ["title", "status", "body", "requirements", "tags", "links"],
      requirement: [
        "title",
        "statement",
        "body",
        "rationale",
        "priority",
        "acceptance_criteria",
        "verification",
        "dependencies",
        "status",
      ],
      decision: [
        "title",
        "context",
        "decision",
        "body",
        "consequences",
        "requirements",
        "status",
      ],
      interface: [
        "title",
        "kind",
        "producer",
        "consumer",
        "body",
        "schema",
        "requirements",
        "status",
      ],
      unit: [
        "title",
        "phase",
        "sequence",
        "body",
        "scope",
        "commit_tasks",
        "paths",
        "requirements",
        "design_sections",
        "dependencies",
        "exit_criteria",
        "status",
      ],
      suite: ["title", "body", "scope", "requirements", "status"],
      test: [
        "title",
        "level",
        "suite",
        "body",
        "requirements",
        "design_sections",
        "implementation_units",
        "preconditions",
        "steps",
        "expected_results",
        "automation",
        "status",
      ],
    }};

    function contextUrl(path) {{
      const contextId = EDIT_DATA.context_id || "";
      if (!contextId) {{
        return path;
      }}
      const separator = path.includes("?") ? "&" : "?";
      return `${{path}}${{separator}}context_id=${{encodeURIComponent(contextId)}}`;
    }}

    function setStatus(message, error = false) {{
      statusLine.textContent = message || "";
      statusLine.classList.toggle("error", Boolean(error));
      statusLine.classList.toggle("dirty", !error && dirty);
      statusLine.classList.toggle("saved", !error && !dirty && Boolean(message));
    }}

    function setDirty(nextDirty = true) {{
      dirty = Boolean(nextDirty);
      saveArtifact.disabled = saveInFlight || !dirty;
      if (dirty) {{
        setStatus("unsaved changes");
      }}
    }}

    function markDirty() {{
      setDirty(true);
    }}

    function clampEditorFontSize(value) {{
      const requested = Number(value);
      if (!Number.isFinite(requested)) {{
        return 16;
      }}
      return Math.max(
        MIN_EDITOR_FONT_SIZE,
        Math.min(MAX_EDITOR_FONT_SIZE, Math.round(requested)),
      );
    }}

    function applyEditorFontSize(value = editorFontSize) {{
      editorFontSize = clampEditorFontSize(value);
      document.documentElement.style.setProperty(
        "--editor-font-size",
        `${{editorFontSize}}px`,
      );
    }}

    function displayId(record) {{
      return record.id || record.unit_id || "";
    }}

    function recordSummary(record, index) {{
      const id = displayId(record);
      const title = record.title || "Untitled";
      const type = record.record_type || "section";
      return `${{id ? `${{id}}. ` : ""}}${{title}} · ${{type}} #${{index + 1}}`;
    }}

    function stringValue(value) {{
      if (value === undefined || value === null) {{
        return "";
      }}
      return String(value);
    }}

    function arrayValue(value) {{
      if (Array.isArray(value)) {{
        return value.join("\\n");
      }}
      return stringValue(value);
    }}

    function jsonValue(value) {{
      if (value === undefined || value === null || value === "") {{
        return "";
      }}
      if (typeof value === "string") {{
        return value;
      }}
      return JSON.stringify(value, null, 2);
    }}

    function recordKind(record) {{
      return String(record.record_type || "section");
    }}

    function generatedFieldEntries(record) {{
      return Object.entries(record)
        .filter(([field]) => GENERATED_FIELDS.has(field))
        .filter(([, value]) => value !== undefined && value !== null && value !== "");
    }}

    function editableFieldsForRecord(record) {{
      const fields = new Set(RECORD_FIELDS[recordKind(record)] || COMMON_FIELDS);
      fields.add("record_type");
      for (const field of Object.keys(record)) {{
        if (!GENERATED_FIELDS.has(field)) {{
          fields.add(field);
        }}
      }}
      return Array.from(fields);
    }}

    function fieldInputOptions(field) {{
      if (field === "record_type") {{
        return {{
          kind: "select",
          values: ["document", "section", "requirement", "decision", "interface", "unit", "suite", "test"],
        }};
      }}
      if (field === "status") {{
        return {{
          kind: "select",
          values: ["draft", "approved", "changed", "deprecated", "deferred"],
        }};
      }}
      if (field === "priority") {{
        return {{ kind: "select", values: ["", "must", "should", "could", "deferred"] }};
      }}
      if (["order", "phase", "sequence"].includes(field)) {{
        return {{ numeric: true }};
      }}
      if (field === "body" || LIST_FIELDS.has(field) || JSON_FIELDS.has(field)) {{
        return {{
          kind: "textarea",
          list: LIST_FIELDS.has(field),
          json: JSON_FIELDS.has(field),
        }};
      }}
      return {{}};
    }}

    function fieldLabel(field) {{
      if (field === "record_type") {{
        return "Type";
      }}
      return field.replace(/_/g, " ");
    }}

    function appendInput(container, record, field, label, options = {{}}) {{
      const wrapper = document.createElement("label");
      wrapper.textContent = label;
      let input;
      if (options.kind === "select") {{
        input = document.createElement("select");
        for (const optionValue of options.values || []) {{
          const option = document.createElement("option");
          option.value = optionValue;
          option.textContent = optionValue || "none";
          input.append(option);
        }}
        input.value = stringValue(record[field]);
      }} else if (options.kind === "textarea") {{
        input = document.createElement("textarea");
        input.value = options.list
          ? arrayValue(record[field])
          : options.json
          ? jsonValue(record[field])
          : stringValue(record[field]);
      }} else {{
        input = document.createElement("input");
        input.type = options.numeric ? "number" : "text";
        input.value = stringValue(record[field]);
      }}
      input.dataset.field = field;
      if (options.list) {{
        input.dataset.list = "1";
      }}
      if (options.json) {{
        input.dataset.json = "1";
      }}
      if (options.numeric) {{
        input.dataset.numeric = "1";
      }}
      if (field === "body") {{
        input.classList.add("body-field");
        input.placeholder = "Markdown text, tables, code fences, and Mermaid diagrams";
      }}
      input.addEventListener("input", markDirty);
      input.addEventListener("change", markDirty);
      wrapper.append(input);
      container.append(wrapper);
      return input;
    }}

    function renderStructuredEditor() {{
      document.body.classList.remove("markdown-mode", "rich-markdown-mode");
      if (richMarkdownEditor) {{
        richMarkdownEditor.destroy();
        richMarkdownEditor = null;
      }}
      markdownTextarea = null;
      richToolbar = null;
      editorMeta.textContent = `${{EDIT_DATA.markdown_path}} · source ${{EDIT_DATA.jsonl_path}}`;
      addRecord.hidden = false;
      recordType.hidden = false;
      recordsRoot.replaceChildren();
      for (const [index, record] of records.entries()) {{
        const details = document.createElement("details");
        details.className = "record-editor";
        details.open = index === 0 || dirty;
        details.dataset.index = String(index);

        const summary = document.createElement("summary");
        const summaryInner = document.createElement("span");
        summaryInner.className = "record-summary";
        const summaryText = document.createElement("span");
        summaryText.className = "record-summary-text";
        summaryText.textContent = recordSummary(record, index);
        const summaryKind = document.createElement("span");
        summaryKind.className = "record-summary-kind";
        summaryKind.textContent = recordKind(record);
        summaryInner.append(summaryText, summaryKind);
        summary.append(summaryInner);
        details.append(summary);

        const body = document.createElement("div");
        body.className = "record-body";
        const grid = document.createElement("div");
        grid.className = "field-grid";
        for (const field of editableFieldsForRecord(record)) {{
          if (field === "body") {{
            continue;
          }}
          appendInput(grid, record, field, fieldLabel(field), fieldInputOptions(field));
        }}
        body.append(grid);
        if (editableFieldsForRecord(record).includes("body")) {{
          appendInput(body, record, "body", "Markdown body", fieldInputOptions("body"));
        }}

        const generatedEntries = generatedFieldEntries(record);
        if (generatedEntries.length > 0) {{
          const generated = document.createElement("details");
          generated.className = "generated-fields";
          const generatedSummary = document.createElement("summary");
          generatedSummary.textContent = "Generated fields";
          generated.append(generatedSummary);
          const generatedGrid = document.createElement("div");
          generatedGrid.className = "generated-grid";
          for (const [field, value] of generatedEntries) {{
            const wrapper = document.createElement("div");
            wrapper.className = "generated-field";
            const name = document.createElement("span");
            name.textContent = field.replace(/_/g, " ");
            const code = document.createElement("code");
            code.textContent = Array.isArray(value) || typeof value === "object"
              ? JSON.stringify(value)
              : String(value);
            wrapper.append(name, code);
            generatedGrid.append(wrapper);
          }}
          generated.append(generatedGrid);
          body.append(generated);
        }}

        const actions = document.createElement("div");
        actions.className = "record-actions";
        const duplicate = document.createElement("button");
        duplicate.type = "button";
        duplicate.textContent = "Duplicate";
        duplicate.addEventListener("click", () => duplicateRecord(index));
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "Delete";
        remove.disabled = records.length <= 1;
        remove.addEventListener("click", () => deleteRecord(index));
        actions.append(duplicate, remove);
        body.append(actions);

        details.append(body);
        recordsRoot.append(details);
      }}
    }}

    function markdownValue() {{
      if (
        richMarkdownEditor &&
        typeof richMarkdownEditor.getMarkdown === "function"
      ) {{
        return richMarkdownEditor.getMarkdown();
      }}
      return markdownTextarea ? markdownTextarea.value : "";
    }}

    function setMarkdownValue(value) {{
      const nextValue = String(value || "");
      if (markdownTextarea) {{
        markdownTextarea.value = nextValue;
      }}
      if (
        richMarkdownEditor &&
        richMarkdownEditor.commands &&
        typeof richMarkdownEditor.commands.setContent === "function"
      ) {{
        richMarkdownEditor.commands.setContent(nextValue, {{ contentType: "markdown" }});
      }}
    }}

    function appendMarkdownSnippet(snippet) {{
      const prefix = markdownValue().replace(/\\s*$/, "");
      const nextValue = `${{prefix}}${{prefix ? "\\n\\n" : ""}}${{snippet}}\\n`;
      setMarkdownValue(nextValue);
      markDirty();
    }}

    {rich_editor_script}

    function renderMarkdownEditor() {{
      document.body.classList.add("markdown-mode");
      document.body.classList.toggle("rich-markdown-mode", RICH_EDITOR_ENABLED);
      if (richMarkdownEditor) {{
        richMarkdownEditor.destroy();
        richMarkdownEditor = null;
      }}
      editorMeta.textContent = EDIT_DATA.markdown_path || "";
      addRecord.hidden = true;
      recordType.hidden = true;
      recordsRoot.replaceChildren();
      const wrapper = document.createElement("section");
      wrapper.className = "markdown-editor";
      if (RICH_EDITOR_ENABLED) {{
        wrapper.classList.add("rich-markdown-editor", "rich-fallback");
      }}
      const textarea = document.createElement("textarea");
      textarea.id = "markdownSource";
      textarea.className = RICH_EDITOR_ENABLED ? "rich-source-fallback" : "";
      textarea.setAttribute("aria-label", EDIT_DATA.markdown_path || "Markdown");
      textarea.spellcheck = true;
      textarea.value = EDIT_DATA.markdown || "";
      textarea.addEventListener("input", markDirty);
      textarea.addEventListener("change", markDirty);
      markdownTextarea = textarea;
      if (RICH_EDITOR_ENABLED) {{
        wrapper.append(createRichToolbar());
        const surface = document.createElement("div");
        surface.className = "rich-editor-surface";
        surface.setAttribute("aria-label", EDIT_DATA.markdown_path || "Markdown");
        wrapper.append(surface, textarea);
        recordsRoot.append(wrapper);
        initializeRichMarkdownEditor(wrapper, surface);
      }} else {{
        wrapper.append(textarea);
        recordsRoot.append(wrapper);
      }}
    }}

    function splitLines(value) {{
      return String(value || "")
        .split(/\\r?\\n/)
        .map((line) => line.trim())
        .filter(Boolean);
    }}

    function parseInputValue(input) {{
      if (input.dataset.list === "1") {{
        return splitLines(input.value);
      }}
      if (input.dataset.json === "1") {{
        const raw = input.value.trim();
        if (!raw) {{
          return {{}};
        }}
        return JSON.parse(raw);
      }}
      if (input.dataset.numeric === "1") {{
        if (!input.value.trim()) {{
          return undefined;
        }}
        return Number(input.value);
      }}
      return input.value;
    }}

    function collectStructuredRecords() {{
      const collected = [];
      for (const details of recordsRoot.querySelectorAll(".record-editor")) {{
        const original = records[Number(details.dataset.index || "0")] || {{}};
        const record = {{ ...original }};
        record.schema_version = original.schema_version || 1;
        record.artifact_type = original.artifact_type || EDIT_DATA.artifact_name;
        for (const input of details.querySelectorAll("[data-field]")) {{
          const field = input.dataset.field;
          const value = parseInputValue(input);
          if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) {{
            continue;
          }}
          if (JSON_FIELDS.has(field) && Object.keys(value).length === 0) {{
            continue;
          }}
          record[field] = value;
        }}
        collected.push(record);
      }}
      return collected;
    }}

    function collectMarkdownDocument() {{
      return markdownValue();
    }}

    function nextGeneratedId(type) {{
      const existing = new Set(records.map((record) => displayId(record)).filter(Boolean));
      const prefixByType = {{
        document: "DOC",
        section: `${{String(EDIT_DATA.artifact_name || "doc").toUpperCase().replace(/[^A-Z0-9]+/g, "")}}SEC`,
        requirement: "REQ",
        decision: "DEC",
        interface: "IFACE",
        unit: "PH1-C",
        suite: "TS",
        test: "TEST",
      }};
      const prefix = prefixByType[type] || "REC";
      for (let index = 1; index < 10000; index += 1) {{
        const candidate = type === "unit"
          ? `${{prefix}}${{index}}`
          : `${{prefix}}-${{String(index).padStart(3, "0")}}`;
        if (!existing.has(candidate)) {{
          return candidate;
        }}
      }}
      return `${{prefix}}-${{Date.now()}}`;
    }}

    function nextOrder() {{
      const nextOrder = records.reduce((maximum, record) => {{
        const order = Number(record.order || 0);
        return Number.isFinite(order) ? Math.max(maximum, order) : maximum;
      }}, 0) + 10;
      return nextOrder;
    }}

    function newRecord(type) {{
      const record = {{
        schema_version: 1,
        artifact_type: EDIT_DATA.artifact_name,
        record_type: type,
        title: `New ${{type.replace(/-/g, " ")}}`,
        order: nextOrder(),
        body: "",
        status: "draft",
      }};
      if (type === "unit") {{
        record.unit_id = nextGeneratedId(type);
        record.phase = 1;
        record.sequence = 1;
      }} else {{
        record.id = nextGeneratedId(type);
      }}
      return record;
    }}

    function addSectionRecord() {{
      records.push(newRecord(recordType.value || "section"));
      renderStructuredEditor();
      const last = recordsRoot.querySelector(".record-editor:last-child");
      if (last) {{
        last.open = true;
        last.scrollIntoView({{ block: "nearest" }});
      }}
      markDirty();
    }}

    function duplicateRecord(index) {{
      const original = records[index];
      if (!original) {{
        return;
      }}
      const copy = {{ ...original, order: nextOrder(), title: `${{original.title || "Record"}} copy` }};
      if (copy.unit_id) {{
        copy.unit_id = nextGeneratedId("unit");
      }} else if (copy.id) {{
        copy.id = nextGeneratedId(recordKind(copy));
      }}
      records.splice(index + 1, 0, copy);
      renderStructuredEditor();
      markDirty();
    }}

    function deleteRecord(index) {{
      if (records.length <= 1) {{
        return;
      }}
      const record = records[index];
      const name = record ? recordSummary(record, index) : "this record";
      if (!window.confirm(`Delete ${{name}}?`)) {{
        return;
      }}
      records.splice(index, 1);
      renderStructuredEditor();
      markDirty();
    }}

    async function save(options = {{}}) {{
      if (saveInFlight) {{
        return false;
      }}
      if (!dirty && !options.force) {{
        return true;
      }}
      saveInFlight = true;
      saveArtifact.disabled = true;
      setStatus("saving...");
      try {{
        const payload = EDIT_DATA.mode === "structured"
          ? {{
              mode: "structured",
              artifact: EDIT_DATA.artifact,
              path: EDIT_DATA.path || "",
              records: collectStructuredRecords(),
            }}
          : {{
              mode: "markdown",
              artifact: EDIT_DATA.artifact,
              path: EDIT_DATA.path || "",
              markdown: collectMarkdownDocument(),
            }};
        const response = await fetch(contextUrl("/api/artifacts/edit"), {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload),
        }});
        const result = await response.json().catch(() => ({{ error: "save failed" }}));
        if (!response.ok) {{
          throw new Error(result.error || "save failed");
        }}
        if (EDIT_DATA.mode === "structured") {{
          records = collectStructuredRecords();
        }}
        setDirty(false);
        setStatus(`saved ${{result.markdown_path || EDIT_DATA.markdown_path}}`);
        if (window.parent) {{
          window.parent.postMessage(
            {{
              type: "electroboy-artifact-saved",
              path: result.markdown_path || EDIT_DATA.markdown_path,
            }},
            window.location.origin,
          );
        }}
        return true;
      }} catch (error) {{
        setStatus(error.message || String(error), true);
        return false;
      }} finally {{
        saveInFlight = false;
        saveArtifact.disabled = !dirty;
      }}
    }}

    addRecord.addEventListener("click", addSectionRecord);
    saveArtifact.addEventListener("click", () => {{
      save({{ force: true }});
    }});
    window.addEventListener("message", async (event) => {{
      if (event.origin !== window.location.origin) {{
        return;
      }}
      const data = event.data || {{}};
      if (data.type === "electroboy-editor-font-size") {{
        applyEditorFontSize(data.font_size);
        return;
      }}
      if (data.type !== "electroboy-save-request") {{
        return;
      }}
      const ok = await save({{ force: true }});
      if (window.parent) {{
        window.parent.postMessage(
          {{
            type: "electroboy-artifact-save-complete",
            token: data.token || "",
            ok,
          }},
          window.location.origin,
        );
      }}
    }});
    window.addEventListener("beforeunload", (event) => {{
      if (!dirty) {{
        return;
      }}
      event.preventDefault();
      event.returnValue = "";
    }});
    applyEditorFontSize();
    if (EDIT_DATA.mode === "structured") {{
      renderStructuredEditor();
    }} else {{
      renderMarkdownEditor();
    }}
  </script>
</body>
</html>
"""


def _rich_markdown_editor_script() -> str:
    return """
    function richButton(command, label, title) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.command = command;
      button.title = title;
      button.setAttribute("aria-label", title);
      button.textContent = label;
      button.addEventListener("click", () => executeRichCommand(command));
      return button;
    }

    function createRichToolbar() {
      const toolbar = document.createElement("div");
      toolbar.className = "rich-toolbar";

      const heading = document.createElement("select");
      heading.dataset.heading = "1";
      heading.title = "Block style";
      heading.setAttribute("aria-label", "Block style");
      for (const [value, label] of [
        ["paragraph", "Paragraph"],
        ["1", "Heading 1"],
        ["2", "Heading 2"],
        ["3", "Heading 3"],
      ]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        heading.append(option);
      }
      heading.addEventListener("change", () => {
        if (!richMarkdownEditor) {
          return;
        }
        if (heading.value === "paragraph") {
          richMarkdownEditor.chain().focus().setParagraph().run();
        } else {
          richMarkdownEditor
            .chain()
            .focus()
            .toggleHeading({ level: Number(heading.value) })
            .run();
        }
      });

      toolbar.append(
        heading,
        richButton("bold", "B", "Bold"),
        richButton("italic", "I", "Italic"),
        richButton("code", "`", "Inline code"),
        richButton("bulletList", "Bullet", "Bullet list"),
        richButton("orderedList", "1.", "Numbered list"),
        richButton("blockquote", "Quote", "Quote"),
        richButton("codeBlock", "Code", "Code block"),
        richButton("link", "Link", "Link"),
        richButton("table", "Table", "Insert table"),
        richButton("mermaid", "Mermaid", "Insert Mermaid block"),
      );
      richToolbar = toolbar;
      return toolbar;
    }

    function executeRichCommand(command) {
      if (!richMarkdownEditor) {
        return;
      }
      const chain = richMarkdownEditor.chain().focus();
      if (command === "bold") {
        chain.toggleBold().run();
      } else if (command === "italic") {
        chain.toggleItalic().run();
      } else if (command === "code") {
        chain.toggleCode().run();
      } else if (command === "bulletList") {
        chain.toggleBulletList().run();
      } else if (command === "orderedList") {
        chain.toggleOrderedList().run();
      } else if (command === "blockquote") {
        chain.toggleBlockquote().run();
      } else if (command === "codeBlock") {
        chain.toggleCodeBlock().run();
      } else if (command === "link") {
        const previous = richMarkdownEditor.getAttributes("link").href || "";
        const href = window.prompt("Link URL", previous);
        if (href === null) {
          return;
        }
        if (!href.trim()) {
          chain.unsetLink().run();
        } else {
          chain.setLink({ href: href.trim() }).run();
        }
      } else if (command === "table") {
        chain.insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run();
      } else if (command === "mermaid") {
        appendMarkdownSnippet(
          "```mermaid\\ngraph TD\\n  A[Start] --> B[Next]\\n```",
        );
      }
      updateRichToolbarState();
    }

    function updateRichToolbarState() {
      if (!richToolbar || !richMarkdownEditor) {
        return;
      }
      const heading = richToolbar.querySelector("[data-heading]");
      if (heading) {
        if (richMarkdownEditor.isActive("heading", { level: 1 })) {
          heading.value = "1";
        } else if (richMarkdownEditor.isActive("heading", { level: 2 })) {
          heading.value = "2";
        } else if (richMarkdownEditor.isActive("heading", { level: 3 })) {
          heading.value = "3";
        } else {
          heading.value = "paragraph";
        }
      }
      for (const button of richToolbar.querySelectorAll("[data-command]")) {
        const command = button.dataset.command || "";
        const activeByCommand = {
          bold: "bold",
          italic: "italic",
          code: "code",
          bulletList: "bulletList",
          orderedList: "orderedList",
          blockquote: "blockquote",
          codeBlock: "codeBlock",
          link: "link",
        };
        button.classList.toggle(
          "active",
          Boolean(activeByCommand[command]) &&
            richMarkdownEditor.isActive(activeByCommand[command]),
        );
      }
    }

    async function initializeRichMarkdownEditor(wrapper, surface) {
      if (!RICH_EDITOR_ENABLED || richEditorLoading) {
        return;
      }
      richEditorLoading = true;
      surface.setAttribute("aria-busy", "true");
      setStatus("loading rich editor...");
      try {
        const [
          coreModule,
          starterKitModule,
          markdownModule,
          linkModule,
          tableModule,
          tableRowModule,
          tableHeaderModule,
          tableCellModule,
        ] = await Promise.all([
          import("https://esm.sh/@tiptap/core"),
          import("https://esm.sh/@tiptap/starter-kit"),
          import("https://esm.sh/@tiptap/markdown"),
          import("https://esm.sh/@tiptap/extension-link"),
          import("https://esm.sh/@tiptap/extension-table"),
          import("https://esm.sh/@tiptap/extension-table-row"),
          import("https://esm.sh/@tiptap/extension-table-header"),
          import("https://esm.sh/@tiptap/extension-table-cell"),
        ]);
        const Editor = coreModule.Editor;
        const StarterKit = starterKitModule.default || starterKitModule.StarterKit;
        const Markdown = markdownModule.Markdown || markdownModule.default;
        const Link = linkModule.default || linkModule.Link;
        const Table = tableModule.default || tableModule.Table;
        const TableRow = tableRowModule.default || tableRowModule.TableRow;
        const TableHeader = tableHeaderModule.default || tableHeaderModule.TableHeader;
        const TableCell = tableCellModule.default || tableCellModule.TableCell;
        if (!Editor || !StarterKit || !Markdown) {
          throw new Error("Tiptap Markdown modules are unavailable");
        }
        richMarkdownEditor = new Editor({
          element: surface,
          extensions: [
            StarterKit,
            Markdown,
            Link ? Link.configure({ openOnClick: false }) : null,
            Table ? Table.configure({ resizable: true }) : null,
            TableRow,
            TableHeader,
            TableCell,
          ].filter(Boolean),
          content: markdownTextarea ? markdownTextarea.value : "",
          contentType: "markdown",
          editorProps: {
            attributes: {
              spellcheck: "true",
            },
          },
          onUpdate: () => {
            if (markdownTextarea) {
              markdownTextarea.value = markdownValue();
            }
            markDirty();
          },
          onSelectionUpdate: updateRichToolbarState,
          onFocus: updateRichToolbarState,
        });
        surface.removeAttribute("aria-busy");
        if (markdownTextarea) {
          markdownTextarea.hidden = true;
        }
        wrapper.classList.remove("rich-fallback");
        setStatus("");
        updateRichToolbarState();
      } catch (error) {
        wrapper.classList.add("rich-fallback");
        surface.remove();
        if (markdownTextarea) {
          markdownTextarea.hidden = false;
        }
        setStatus(`rich editor unavailable: ${error.message || error}`, true);
      } finally {
        richEditorLoading = false;
      }
    }
"""


def _document_target_path(project_root: Path | str, relative_path: str) -> tuple[str, Path]:
    project_root = Path(project_root).expanduser().resolve()
    normalized_path = _normalize_document_target_path(relative_path)
    document_path = (project_root / normalized_path).resolve()
    try:
        document_path.relative_to(project_root)
    except ValueError as error:
        raise StateError("document path cannot escape the project") from error
    return normalized_path, document_path


def _resolved_artifact_relative_path(
    project_root: Path | str,
    default_relative_path: str,
) -> str:
    project_root = Path(project_root).expanduser().resolve()
    relative_path = default_relative_path
    run_id = StateStore(project_root).current_run_id()
    if run_id:
        relative_path = resolve_artifact_path(
            artifact_paths_for_run(project_root, run_id),
            default_relative_path,
        )
    return _document_target_path(project_root, relative_path)[0]


def _resolved_artifact_document_path(
    project_root: Path | str,
    default_relative_path: str,
) -> Path:
    project_root = Path(project_root).expanduser().resolve()
    relative_path = _resolved_artifact_relative_path(
        project_root,
        default_relative_path,
    )
    return _document_target_path(project_root, relative_path)[1]


def _artifact_event_document_path(
    project_root: Path | str,
    artifact: str,
    requested_path: str,
) -> Path:
    project_root = Path(project_root).expanduser().resolve()
    if artifact == "requirements":
        return _resolved_artifact_document_path(project_root, "docs/requirements.md")
    if artifact == "document":
        return _document_target_path(project_root, requested_path)[1]
    if artifact == "route":
        relative_path = ARTIFACT_EVENT_ROUTE_PATHS.get(requested_path)
        if relative_path is None:
            raise StateError(f"unknown artifact route: {requested_path}")
        return _resolved_artifact_document_path(project_root, relative_path)
    raise StateError(f"unknown artifact: {artifact}")


def _render_markdown(text: str) -> str:
    try:
        import markdown as markdown_library
    except ImportError:
        return _render_basic_markdown(text)
    rendered = str(
        markdown_library.markdown(
            _enable_markdown_in_details(text),
            extensions=["extra", "sane_lists", "md_in_html", "toc"],
        )
    )
    return _promote_mermaid_blocks(rendered)


def _document_link_script(relative_path: str) -> str:
    encoded_path = json.dumps(relative_path, ensure_ascii=False).replace(
        "<", "\\u003c"
    )
    script = r"""
  <script>
    (() => {
      const currentDocumentPath = __DOCUMENT_PATH__;

      function decodeLinkPart(value) {
        try {
          return decodeURIComponent(value);
        } catch (error) {
          return value;
        }
      }

      function repositoryDocumentTarget(href) {
        const rawHref = String(href || "").trim();
        if (
          !rawHref ||
          /^[a-z][a-z0-9+.-]*:/i.test(rawHref) ||
          rawHref.startsWith("//")
        ) {
          return null;
        }
        const hashIndex = rawHref.indexOf("#");
        const rawFragment = hashIndex >= 0 ? rawHref.slice(hashIndex + 1) : "";
        const pathAndQuery = hashIndex >= 0 ? rawHref.slice(0, hashIndex) : rawHref;
        const queryIndex = pathAndQuery.indexOf("?");
        const rawPath = queryIndex >= 0
          ? pathAndQuery.slice(0, queryIndex)
          : pathAndQuery;
        if (!rawPath) {
          return {
            path: currentDocumentPath,
            label: currentDocumentPath.replace(/\.md$/i, "") || currentDocumentPath,
            fragment: decodeLinkPart(rawFragment),
          };
        }
        const linkPath = decodeLinkPart(rawPath).replace(/\\/g, "/");
        const segments = linkPath.startsWith("/")
          ? []
          : currentDocumentPath.split("/").slice(0, -1);
        for (const segment of linkPath.split("/")) {
          if (!segment || segment === ".") {
            continue;
          }
          if (segment === "..") {
            if (segments.length === 0) {
              return null;
            }
            segments.pop();
            continue;
          }
          segments.push(segment);
        }
        const path = segments.join("/");
        if (!/\.md$/i.test(path)) {
          return null;
        }
        return {
          path,
          label: path.replace(/\.md$/i, "") || path,
          fragment: decodeLinkPart(rawFragment),
        };
      }

      function scrollToDocumentFragment(fragment) {
        if (!fragment) {
          window.scrollTo({ top: 0, behavior: "auto" });
          const nextUrl = new URL(window.location.href);
          nextUrl.hash = "";
          window.history.replaceState(
            null,
            "",
            `${nextUrl.pathname}${nextUrl.search}`,
          );
          return;
        }
        const target = document.getElementById(fragment);
        if (!target) {
          return;
        }
        target.scrollIntoView({ block: "start" });
        window.history.replaceState(null, "", `#${encodeURIComponent(fragment)}`);
      }

      function currentDocumentLocation() {
        const hash = String(window.location.hash || "").replace(/^#/, "");
        return {
          fragment: decodeLinkPart(hash),
          scrollX: window.scrollX,
          scrollY: window.scrollY,
        };
      }

      function applyDocumentLocation(value) {
        const location = value && typeof value === "object" ? value : {};
        const hasScrollPosition =
          Number.isFinite(location.scrollX) && Number.isFinite(location.scrollY);
        window.requestAnimationFrame(() => {
          window.requestAnimationFrame(() => {
            if (!hasScrollPosition) {
              scrollToDocumentFragment(String(location.fragment || ""));
              return;
            }
            window.scrollTo({
              left: Math.max(0, location.scrollX),
              top: Math.max(0, location.scrollY),
              behavior: "auto",
            });
            const nextUrl = new URL(window.location.href);
            nextUrl.hash = String(location.fragment || "");
            window.history.replaceState(
              null,
              "",
              `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`,
            );
          });
        });
      }

      document.addEventListener("click", (event) => {
        if (
          event.defaultPrevented ||
          event.button !== 0 ||
          event.altKey ||
          event.ctrlKey ||
          event.metaKey ||
          event.shiftKey ||
          !(event.target instanceof Element)
        ) {
          return;
        }
        const link = event.target.closest("a[href]");
        if (!link || link.hasAttribute("download")) {
          return;
        }
        const target = repositoryDocumentTarget(link.getAttribute("href"));
        if (!target) {
          return;
        }
        event.preventDefault();
        if (window.parent === window) {
          if (target.path === currentDocumentPath) {
            scrollToDocumentFragment(target.fragment);
            return;
          }
          const nextUrl = new URL(window.location.href);
          nextUrl.searchParams.set("path", target.path);
          nextUrl.searchParams.set("title", target.label);
          nextUrl.hash = target.fragment;
          window.location.assign(nextUrl);
          return;
        }
        window.parent.postMessage(
          {
            type: "electroboy:document-link",
            target: { path: target.path, label: target.label },
            source: {
              target: {
                path: currentDocumentPath,
                label: currentDocumentPath.replace(/\.md$/i, "")
                  || currentDocumentPath,
              },
              location: currentDocumentLocation(),
            },
            location: { fragment: target.fragment },
            fragment: target.fragment,
          },
          window.location.origin,
        );
      });
      window.addEventListener("message", (event) => {
        if (event.origin !== window.location.origin) {
          return;
        }
        const data = event.data || {};
        if (
          data.type !== "electroboy:document-location" ||
          data.path !== currentDocumentPath
        ) {
          return;
        }
        applyDocumentLocation(data.location);
      });
    })();
  </script>
"""
    return script.replace("__DOCUMENT_PATH__", encoded_path)


_DETAILS_TAG_RE = re.compile(r"<details(?P<attrs>[^>]*)>", re.IGNORECASE)


def _enable_markdown_in_details(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        attrs = match.group("attrs") or ""
        if re.search(r"\smarkdown\s*=", attrs, re.IGNORECASE):
            return match.group(0)
        return f'<details{attrs} markdown="1">'

    return _DETAILS_TAG_RE.sub(replace, text)


def _render_basic_markdown(text: str) -> str:
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    code_lines: list[str] = []
    code_language = ""

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{html.escape(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            items = "".join(f"<li>{html.escape(item)}</li>" for item in list_items)
            blocks.append(f"<ul>{items}</ul>")
            list_items.clear()

    def flush_code() -> None:
        nonlocal code_language
        escaped = html.escape("\n".join(code_lines))
        language = code_language.strip().lower()
        if language == "mermaid":
            blocks.append(f'<div class="mermaid">{escaped}</div>')
        else:
            class_attr = (
                f' class="language-{html.escape(language)}"'
                if language
                else ""
            )
            blocks.append(f"<pre><code{class_attr}>{escaped}</code></pre>")
        code_lines.clear()
        code_language = ""

    for raw_line in text.splitlines():
        if code_language:
            if raw_line.strip() == "```":
                flush_code()
            else:
                code_lines.append(raw_line)
            continue
        line = raw_line.strip()
        if line.startswith("```"):
            flush_paragraph()
            flush_list()
            code_language = line[3:].strip() or "plain"
            continue
        if not line:
            flush_paragraph()
            flush_list()
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading is not None:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            title = html.escape(heading.group(2).strip())
            blocks.append(f"<h{level}>{title}</h{level}>")
            continue
        if line.startswith("- "):
            flush_paragraph()
            list_items.append(line[2:].strip())
            continue
        flush_list()
        paragraph.append(line)
    if code_language:
        flush_code()
    flush_paragraph()
    flush_list()
    return "\n".join(blocks) if blocks else "<p></p>"


_MERMAID_BLOCK_RE = re.compile(
    r'<pre><code class="(?:language-)?mermaid">(?P<body>.*?)</code></pre>',
    re.DOTALL,
)


def _promote_mermaid_blocks(rendered: str) -> str:
    return _MERMAID_BLOCK_RE.sub(
        lambda match: f'<div class="mermaid">{match.group("body")}</div>',
        rendered,
    )


def _mermaid_script(rendered: str) -> str:
    if 'class="mermaid"' not in rendered:
        return ""
    return """
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <script>
    window.addEventListener("DOMContentLoaded", () => {
      const popupFeatures =
        "popup=yes,width=980,height=720,menubar=no,toolbar=no,location=no,status=no,scrollbars=yes,resizable=yes";

      function prepareMermaidPopouts() {
        for (const diagram of document.querySelectorAll(".mermaid")) {
          if (diagram.dataset.electroboyPopout === "1") {
            continue;
          }
          diagram.dataset.electroboyPopout = "1";
          diagram.tabIndex = 0;
          diagram.setAttribute("role", "button");
          diagram.setAttribute(
            "aria-label",
            "Open Mermaid diagram in a separate window",
          );
          diagram.title = "Open diagram";
          diagram.addEventListener("click", () => openMermaidPopup(diagram));
          diagram.addEventListener("keydown", (event) => {
            if (event.key !== "Enter" && event.key !== " ") {
              return;
            }
            event.preventDefault();
            openMermaidPopup(diagram);
          });
        }
      }

      function openMermaidPopup(diagram) {
        let popupUrl = "";
        try {
          popupUrl = URL.createObjectURL(new Blob(
            [mermaidPopupHtml(diagramMarkup(diagram))],
            { type: "text/html" },
          ));
        } catch (error) {
          console.warn("Could not prepare Mermaid popup", error);
          return;
        }
        const popup = window.open(
          popupUrl,
          "electroboy-mermaid-diagram",
          popupFeatures,
        );
        if (!popup) {
          URL.revokeObjectURL(popupUrl);
          return;
        }
        window.setTimeout(() => URL.revokeObjectURL(popupUrl), 30000);
      }

      function diagramMarkup(diagram) {
        const clone = diagram.cloneNode(true);
        clone.classList.add("popup-mermaid-diagram");
        clone.removeAttribute("tabindex");
        clone.removeAttribute("role");
        clone.removeAttribute("title");
        return clone.outerHTML;
      }

      function mermaidPopupHtml(diagramHtml) {
        return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mermaid diagram</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #10141f;
      --panel: #151b29;
      --text: #e7edf7;
      --muted: #aab8cf;
      --border: #2a3142;
      --button: #1d2638;
      --accent: #66d9e8;
    }
    * {
      box-sizing: border-box;
    }
    html,
    body {
      height: 100%;
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system,
        BlinkMacSystemFont, "Segoe UI", sans-serif;
      overflow: hidden;
    }
    .diagram-window {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      height: 100vh;
    }
    .diagram-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 42px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
      padding: 0 12px;
    }
    .diagram-title {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
      text-transform: uppercase;
    }
    .diagram-controls {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .diagram-controls button {
      min-width: 34px;
      height: 30px;
      border: 1px solid #364156;
      border-radius: 6px;
      background: var(--button);
      color: var(--text);
      cursor: pointer;
      font: inherit;
      font-size: 13px;
      font-weight: 750;
    }
    .diagram-controls button:hover:not(:disabled) {
      border-color: var(--accent);
      background: #22314a;
    }
    .diagram-controls button:disabled {
      cursor: default;
      opacity: 0.45;
    }
    .zoom-level {
      min-width: 48px;
      text-align: center;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
    }
    .diagram-viewport {
      min-height: 0;
      height: 100%;
      width: 100%;
      overflow: auto;
      background: var(--bg);
      cursor: grab;
      user-select: none;
    }
    .diagram-viewport.dragging {
      cursor: grabbing;
    }
    .diagram-viewport.dragging * {
      user-select: none;
    }
    .diagram-content {
      display: inline-block;
      min-height: 100%;
      min-width: 100%;
      padding: 24px;
    }
    .diagram-content .mermaid {
      display: inline-block;
      margin: 0;
      padding: 0;
      border: 0;
      background: transparent;
      cursor: default;
    }
    .diagram-content svg {
      display: block;
      max-width: none !important;
      max-height: none !important;
      height: auto;
      overflow: visible;
    }
  </style>
</head>
<body>
  <main class="diagram-window">
    <header class="diagram-toolbar">
      <span id="diagramTitle" class="diagram-title">Mermaid diagram</span>
      <div class="diagram-controls">
        <button id="zoomOut" type="button" title="Zoom out" aria-label="Zoom out">-</button>
        <span id="zoomLevel" class="zoom-level">100%</span>
        <button id="zoomReset" type="button" title="Reset zoom" aria-label="Reset zoom">100%</button>
        <button id="zoomIn" type="button" title="Zoom in" aria-label="Zoom in">+</button>
      </div>
    </header>
    <section class="diagram-viewport">
      <div id="diagramContent" class="diagram-content">${diagramHtml}</div>
    </section>
  </main>
  <script>
    (() => {
      const minimumZoom = 0.4;
      const maximumZoom = 4;
      const zoomStep = 0.25;
      const wheelZoomFactor = 1.1;
      let zoom = 1;
      let naturalWidth = 0;
      let naturalHeight = 0;
      let baseWidth = 0;
      let baseHeight = 0;
      let panState = null;
      const content = document.getElementById("diagramContent");
      const viewport = document.querySelector(".diagram-viewport");
      const toolbar = document.querySelector(".diagram-toolbar");
      const zoomLevel = document.getElementById("zoomLevel");
      const zoomOut = document.getElementById("zoomOut");
      const zoomReset = document.getElementById("zoomReset");
      const zoomIn = document.getElementById("zoomIn");

      function contentBox(svg) {
        try {
          const box = svg.getBBox();
          if (
            Number.isFinite(box.x) &&
            Number.isFinite(box.y) &&
            Number.isFinite(box.width) &&
            Number.isFinite(box.height) &&
            box.width > 0 &&
            box.height > 0
          ) {
            return box;
          }
        } catch (error) {
          return null;
        }
        return null;
      }

      function readSvgDimensions(svg) {
        const box = contentBox(svg);
        if (box) {
          svg.setAttribute(
            "viewBox",
            [box.x, box.y, box.width, box.height].join(" "),
          );
          svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
          return { width: box.width, height: box.height };
        }
        const viewBox = (svg.getAttribute("viewBox") || "")
          .trim()
          .split(/\\s+/)
          .map(Number);
        const width = viewBox.length === 4 && Number.isFinite(viewBox[2])
          ? viewBox[2]
          : Number.parseFloat(svg.getAttribute("width")) || svg.clientWidth || 800;
        const height = viewBox.length === 4 && Number.isFinite(viewBox[3])
          ? viewBox[3]
          : Number.parseFloat(svg.getAttribute("height")) || svg.clientHeight || 600;
        return { width, height };
      }

      function updateBaseSize() {
        if (!naturalWidth || !naturalHeight) {
          return;
        }
        const viewportRect = viewport.getBoundingClientRect();
        const toolbarRect = toolbar.getBoundingClientRect();
        const viewportWidth = viewportRect.width || window.innerWidth || 980;
        const viewportHeight =
          viewportRect.height ||
          Math.max(220, (window.innerHeight || 720) - toolbarRect.height);
        const availableWidth = Math.max(320, viewportWidth - 48);
        const availableHeight = Math.max(220, viewportHeight - 48);
        const fitScale = Math.min(
          availableWidth / naturalWidth,
          availableHeight / naturalHeight,
        );
        const scale = Math.max(0.1, fitScale);
        baseWidth = naturalWidth * scale;
        baseHeight = naturalHeight * scale;
      }

      function applyZoom() {
        const svg = content.querySelector("svg");
        if (svg) {
          if (!baseWidth || !baseHeight) {
            const dimensions = readSvgDimensions(svg);
            naturalWidth = dimensions.width;
            naturalHeight = dimensions.height;
            updateBaseSize();
          }
          svg.style.width = (baseWidth * zoom) + "px";
          svg.style.height = (baseHeight * zoom) + "px";
        } else {
          content.style.fontSize = (16 * zoom) + "px";
        }
        zoomLevel.textContent = Math.round(zoom * 100) + "%";
        zoomOut.disabled = zoom <= minimumZoom;
        zoomIn.disabled = zoom >= maximumZoom;
      }

      function zoomTo(nextZoom, clientX = null, clientY = null) {
        const clampedZoom = Math.max(
          minimumZoom,
          Math.min(maximumZoom, nextZoom),
        );
        if (clampedZoom === zoom) {
          return;
        }
        let anchor = null;
        if (Number.isFinite(clientX) && Number.isFinite(clientY)) {
          const anchorElement = content.querySelector("svg") || content;
          const rect = anchorElement.getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0) {
            anchor = {
              element: anchorElement,
              x: clientX,
              y: clientY,
              ratioX: (clientX - rect.left) / rect.width,
              ratioY: (clientY - rect.top) / rect.height,
            };
          }
        }
        zoom = clampedZoom;
        applyZoom();
        if (anchor) {
          const rect = anchor.element.getBoundingClientRect();
          viewport.scrollLeft += rect.left + rect.width * anchor.ratioX - anchor.x;
          viewport.scrollTop += rect.top + rect.height * anchor.ratioY - anchor.y;
        }
      }

      function changeZoom(delta) {
        zoomTo(zoom + delta);
      }

      function handleWheelZoom(event) {
        event.preventDefault();
        if (event.deltaY === 0) {
          return;
        }
        const factor = event.deltaY < 0
          ? wheelZoomFactor
          : 1 / wheelZoomFactor;
        zoomTo(zoom * factor, event.clientX, event.clientY);
      }

      function startPan(event) {
        if (event.button !== 1 || event.target.closest("a")) {
          return;
        }
        event.preventDefault();
        panState = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          scrollLeft: viewport.scrollLeft,
          scrollTop: viewport.scrollTop,
        };
        viewport.classList.add("dragging");
        viewport.setPointerCapture(event.pointerId);
      }

      function updatePan(event) {
        if (!panState || event.pointerId !== panState.pointerId) {
          return;
        }
        event.preventDefault();
        viewport.scrollLeft = panState.scrollLeft - (event.clientX - panState.startX);
        viewport.scrollTop = panState.scrollTop - (event.clientY - panState.startY);
      }

      function finishPan(event) {
        if (!panState || event.pointerId !== panState.pointerId) {
          return;
        }
        panState = null;
        viewport.classList.remove("dragging");
        try {
          viewport.releasePointerCapture(event.pointerId);
        } catch (error) {
          return;
        }
      }

      function initializeDiagramPopup(title) {
        const svg = content.querySelector("svg");
        if (svg) {
          const dimensions = readSvgDimensions(svg);
          naturalWidth = dimensions.width;
          naturalHeight = dimensions.height;
          updateBaseSize();
        }
        applyZoom();
      }

      function fitAfterLayout() {
        initializeDiagramPopup("Mermaid diagram");
      }

      zoomOut.addEventListener("click", () => changeZoom(-zoomStep));
      zoomReset.addEventListener("click", () => {
        zoomTo(1);
      });
      zoomIn.addEventListener("click", () => changeZoom(zoomStep));
      viewport.addEventListener("wheel", handleWheelZoom, { passive: false });
      viewport.addEventListener("pointerdown", startPan);
      viewport.addEventListener("pointermove", updatePan);
      viewport.addEventListener("pointerup", finishPan);
      viewport.addEventListener("pointercancel", finishPan);
      viewport.addEventListener("auxclick", (event) => {
        if (event.button === 1) {
          event.preventDefault();
        }
      });
      window.addEventListener("resize", () => {
        updateBaseSize();
        applyZoom();
      });
      window.requestAnimationFrame(() => {
        fitAfterLayout();
        window.requestAnimationFrame(fitAfterLayout);
      });
      window.setTimeout(fitAfterLayout, 100);
    })();
  <\\/script>
</body>
</html>`;
      }

      async function renderMermaidBlocks() {
        if (!window.mermaid) {
          prepareMermaidPopouts();
          return;
        }
        window.mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "base",
          themeVariables: {
            background: "#10141f",
            mainBkg: "#151b29",
            primaryColor: "#151b29",
            primaryTextColor: "#e7edf7",
            primaryBorderColor: "#364156",
            lineColor: "#66d9e8",
            secondaryColor: "#1d2638",
            secondaryTextColor: "#e7edf7",
            tertiaryColor: "#10141f",
            tertiaryTextColor: "#e7edf7",
            textColor: "#e7edf7",
            nodeBorder: "#364156",
            clusterBkg: "#10141f",
            clusterBorder: "#2a3142",
            edgeLabelBackground: "#10141f",
            fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
          },
        });
        try {
          await window.mermaid.run({ querySelector: ".mermaid" });
        } catch (error) {
          console.warn("Mermaid render failed", error);
        }
        prepareMermaidPopouts();
      }

      renderMermaidBlocks();
    });
  </script>
"""
