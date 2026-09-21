"""Shared file content type detection for ElectroBoy artifacts."""

from __future__ import annotations

import json
from pathlib import Path

DOCUMENT_TYPE_MARKDOWN = "markdown"
DOCUMENT_TYPE_CORKBOARD = "corkboard"
DOCUMENT_TYPE_MIND_MAP = "mind-map"

_TYPE_ALIASES = {
    "markdown": DOCUMENT_TYPE_MARKDOWN,
    "mark-down": DOCUMENT_TYPE_MARKDOWN,
    "document": DOCUMENT_TYPE_MARKDOWN,
    "corkboard": DOCUMENT_TYPE_CORKBOARD,
    "creative-corkboard": DOCUMENT_TYPE_CORKBOARD,
    "electroboy.creative.corkboard": DOCUMENT_TYPE_CORKBOARD,
    "mind-map": DOCUMENT_TYPE_MIND_MAP,
    "mindmap": DOCUMENT_TYPE_MIND_MAP,
    "mind_map": DOCUMENT_TYPE_MIND_MAP,
    "electroboy.mind-map": DOCUMENT_TYPE_MIND_MAP,
}


def normalize_document_type(value: object) -> str:
    """Return the canonical document type for a raw file header value."""

    return _TYPE_ALIASES.get(str(value or "").strip().lower(), "")


def markdown_document_header(document_type: str = DOCUMENT_TYPE_MARKDOWN) -> str:
    """Return the front matter header used by text-backed documents."""

    canonical = normalize_document_type(document_type) or DOCUMENT_TYPE_MARKDOWN
    return f"---\ntype: {canonical}\n---\n\n"


def document_type_from_path(
    path: Path | str,
    *,
    plain_text_is_markdown: bool = False,
) -> str:
    """Read a file header/content and return its canonical document type."""

    try:
        return document_type_from_text(
            Path(path).read_text(encoding="utf-8"),
            plain_text_is_markdown=plain_text_is_markdown,
        )
    except (OSError, UnicodeDecodeError):
        return ""


def document_type_from_text(
    text: str,
    *,
    plain_text_is_markdown: bool = False,
) -> str:
    """Return the canonical type declared inside document text."""

    content = text.lstrip("\ufeff")
    stripped = content.lstrip()
    if stripped.startswith(("{", "[")):
        return _json_document_type(content)
    front_matter_type = _front_matter_document_type(content)
    if front_matter_type:
        return front_matter_type
    leading_header_type = _leading_type_line_document_type(content)
    if leading_header_type:
        return leading_header_type
    if plain_text_is_markdown and content.strip():
        return DOCUMENT_TYPE_MARKDOWN
    return ""


def strip_document_type_header(text: str) -> str:
    """Remove a recognized Markdown type header before rendering content."""

    content = text.lstrip("\ufeff")
    if not content.startswith("---"):
        leading_header_span = _leading_type_line_span(content)
        if leading_header_span is not None:
            return content[leading_header_span:]
        return text
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    header_lines: list[str] = []
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            if _front_matter_lines_type(header_lines):
                return "".join(lines[index + 1 :])
            return text
        header_lines.append(line)
    return text


def _json_document_type(text: str) -> str:
    if not text.lstrip().startswith("{"):
        return ""
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return ""
    if not isinstance(value, dict):
        return ""
    return normalize_document_type(value.get("type"))


def _front_matter_document_type(text: str) -> str:
    if not text.startswith("---"):
        return ""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    header_lines: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            return _front_matter_lines_type(header_lines)
        header_lines.append(line)
    return ""


def _front_matter_lines_type(lines: list[str]) -> str:
    for line in lines:
        key, separator, raw_value = line.partition(":")
        if separator and key.strip().lower() == "type":
            return normalize_document_type(raw_value.strip().strip("\"'"))
    return ""


def _leading_type_line_document_type(text: str) -> str:
    span = _leading_type_line_span(text)
    if span is None:
        return ""
    first_line = text[:span].strip()
    _key, _separator, raw_value = first_line.partition(":")
    return normalize_document_type(raw_value.strip().rstrip(",").strip("\"'"))


def _leading_type_line_span(text: str) -> int | None:
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            offset += len(line)
            continue
        key, separator, raw_value = stripped.partition(":")
        if not separator:
            return None
        if key.strip().strip("\"'").lower() != "type":
            return None
        if normalize_document_type(raw_value.strip().rstrip(",").strip("\"'")):
            return offset + len(line)
        return None
    return None
