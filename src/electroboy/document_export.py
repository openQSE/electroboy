"""Export Markdown documents to downloadable formats."""

from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.sax.saxutils import escape as xml_escape


SUPPORTED_DOCUMENT_EXPORT_FORMATS = {"markdown", "md", "docx", "pdf"}
MARKDOWN_IMAGE_CONTENT_TYPES = {
    ".avif": "image/avif",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_EXPORT_IMAGE_CONTENT_TYPES = {
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
}
_MARKDOWN_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\(\s*"
    r"(?P<source><[^>\n]+>|[^)\s]+)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
)


@dataclass(frozen=True)
class DocumentExport:
    """Rendered document export payload."""

    data: bytes
    filename: str
    content_type: str


@dataclass(frozen=True)
class MarkdownBlock:
    """Simple Markdown block used by export renderers."""

    kind: str
    text: str = ""
    level: int = 0
    anchor: str = ""
    language: str = ""
    rows: tuple[tuple[str, ...], ...] = ()
    image_source: str = ""


@dataclass(frozen=True)
class ExportImage:
    """Resolved local image included in a rendered document."""

    data: bytes
    content_type: str
    extension: str
    width: int
    height: int


class DocumentExportError(RuntimeError):
    """Raised when a document cannot be exported."""


def export_markdown_document(
    document_path: Path,
    relative_path: str,
    export_format: str,
) -> DocumentExport:
    """Export a Markdown document from disk."""

    if not document_path.exists():
        raise DocumentExportError(f"document does not exist: {relative_path}")
    if not document_path.is_file():
        raise DocumentExportError(f"document path is not a file: {relative_path}")
    markdown = document_path.read_text(encoding="utf-8")
    return export_markdown_text(
        markdown,
        relative_path,
        export_format,
        source_path=document_path,
    )


def export_markdown_text(
    markdown: str,
    source_name: str,
    export_format: str,
    *,
    source_path: Path | None = None,
) -> DocumentExport:
    """Export Markdown text as Markdown, DOCX, or PDF."""

    normalized_format = normalize_document_export_format(export_format)
    stem = _export_stem(source_name)
    if normalized_format == "markdown":
        return DocumentExport(
            data=markdown.encode("utf-8"),
            filename=f"{stem}.md",
            content_type="text/markdown; charset=utf-8",
        )
    blocks = parse_markdown_blocks(markdown)
    images = _export_images(blocks, source_path)
    if normalized_format == "docx":
        return DocumentExport(
            data=_docx_bytes(blocks, images),
            filename=f"{stem}.docx",
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        )
    return DocumentExport(
        data=_pdf_bytes(
            blocks,
            images,
            title=_document_title(blocks, stem),
        ),
        filename=f"{stem}.pdf",
        content_type="application/pdf",
    )


def normalize_document_export_format(value: str) -> str:
    """Normalize document export format aliases."""

    normalized = value.strip().lower()
    if normalized == "md":
        return "markdown"
    if normalized not in SUPPORTED_DOCUMENT_EXPORT_FORMATS:
        known = ", ".join(["markdown", "docx", "pdf"])
        raise DocumentExportError(
            f"unsupported document export format: {value}; choose {known}"
        )
    return normalized


def parse_markdown_blocks(markdown: str) -> list[MarkdownBlock]:
    """Parse enough Markdown structure for document exports."""

    blocks: list[MarkdownBlock] = []
    paragraph: list[str] = []
    code_lines: list[str] = []
    code_language = ""
    anchors: set[str] = set()
    index = 0
    lines = markdown.splitlines()

    def flush_paragraph() -> None:
        if paragraph:
            _append_paragraph_blocks(
                blocks,
                _join_paragraph(paragraph),
            )
            paragraph.clear()

    def flush_code() -> None:
        nonlocal code_language
        blocks.append(
            MarkdownBlock(
                "code",
                "\n".join(code_lines).rstrip("\n"),
                language=code_language,
            )
        )
        code_lines.clear()
        code_language = ""

    while index < len(lines):
        raw_line = lines[index]
        stripped = raw_line.strip()
        if code_language:
            if stripped == "```":
                flush_code()
            else:
                code_lines.append(raw_line)
            index += 1
            continue
        if stripped.startswith("```"):
            flush_paragraph()
            code_language = stripped[3:].strip() or "text"
            index += 1
            continue
        table = _parse_markdown_table(lines, index)
        if table is not None:
            flush_paragraph()
            rows, next_index = table
            blocks.append(
                MarkdownBlock("table", rows=tuple(tuple(row) for row in rows))
            )
            index = next_index
            continue
        if not stripped:
            flush_paragraph()
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", stripped)
        if heading:
            flush_paragraph()
            heading_text = _plain_inline_text(heading.group(2))
            anchor = _unique_anchor(_anchor_slug(heading_text), anchors)
            blocks.append(
                MarkdownBlock(
                    "heading",
                    heading_text,
                    level=len(heading.group(1)),
                    anchor=anchor,
                )
            )
            index += 1
            continue
        unordered = re.match(r"^[-*]\s+(.+)$", stripped)
        if unordered:
            flush_paragraph()
            blocks.append(
                MarkdownBlock("bullet", _clean_inline_markdown(unordered.group(1)))
            )
            index += 1
            continue
        ordered = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if ordered:
            flush_paragraph()
            blocks.append(
                MarkdownBlock("numbered", _clean_inline_markdown(ordered.group(1)))
            )
            index += 1
            continue
        paragraph.append(_clean_inline_markdown(stripped))
        index += 1
    if code_language:
        flush_code()
    flush_paragraph()
    return blocks


def resolve_markdown_image_path(
    document_path: Path,
    image_source: str,
) -> tuple[Path, str]:
    """Resolve a local Markdown image relative to its source document."""

    source = html.unescape(image_source).strip()
    parsed = urlsplit(source)
    if parsed.scheme not in {"", "file"} or (
        parsed.scheme == "file" and parsed.netloc not in {"", "localhost"}
    ):
        raise DocumentExportError("document image must use a local path")
    raw_path = unquote(parsed.path).replace("\\", "/")
    if not raw_path:
        raise DocumentExportError("document image path is required")
    requested_path = Path(raw_path).expanduser()
    image_path = (
        requested_path.resolve()
        if requested_path.is_absolute()
        else (document_path.parent / requested_path).resolve()
    )
    content_type = MARKDOWN_IMAGE_CONTENT_TYPES.get(image_path.suffix.lower())
    if content_type is None:
        raise DocumentExportError("unsupported document image format")
    if not image_path.exists():
        raise DocumentExportError(f"document image does not exist: {image_path}")
    if not image_path.is_file():
        raise DocumentExportError(
            f"document image path is not a file: {image_path}"
        )
    return image_path, content_type


def _append_paragraph_blocks(
    blocks: list[MarkdownBlock],
    paragraph: str,
) -> None:
    cursor = 0
    for match in _MARKDOWN_IMAGE_RE.finditer(paragraph):
        preceding = paragraph[cursor : match.start()].strip()
        if preceding:
            blocks.append(MarkdownBlock("paragraph", preceding))
        source = match.group("source").strip()
        if source.startswith("<") and source.endswith(">"):
            source = source[1:-1]
        blocks.append(
            MarkdownBlock(
                "image",
                text=_plain_inline_text(match.group("alt")),
                image_source=source,
            )
        )
        cursor = match.end()
    trailing = paragraph[cursor:].strip()
    if trailing:
        blocks.append(MarkdownBlock("paragraph", trailing))


def _export_images(
    blocks: list[MarkdownBlock],
    source_path: Path | None,
) -> dict[str, ExportImage]:
    if source_path is None:
        return {}
    images: dict[str, ExportImage] = {}
    for block in blocks:
        if block.kind != "image" or block.image_source in images:
            continue
        try:
            image_path, content_type = resolve_markdown_image_path(
                source_path,
                block.image_source,
            )
        except DocumentExportError:
            continue
        extension = image_path.suffix.lower()
        if extension not in _EXPORT_IMAGE_CONTENT_TYPES:
            continue
        data = image_path.read_bytes()
        width, height = _image_pixel_dimensions(data, content_type)
        images[block.image_source] = ExportImage(
            data=data,
            content_type=content_type,
            extension=extension.lstrip("."),
            width=width,
            height=height,
        )
    return images


def _image_pixel_dimensions(data: bytes, content_type: str) -> tuple[int, int]:
    if content_type == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) >= 24:
            width = int.from_bytes(data[16:20], "big")
            height = int.from_bytes(data[20:24], "big")
            if width > 0 and height > 0:
                return width, height
    if content_type == "image/jpeg" and data.startswith(b"\xff\xd8"):
        cursor = 2
        start_of_frame = {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }
        while cursor + 8 < len(data):
            if data[cursor] != 0xFF:
                cursor += 1
                continue
            while cursor < len(data) and data[cursor] == 0xFF:
                cursor += 1
            if cursor >= len(data):
                break
            marker = data[cursor]
            cursor += 1
            if marker in {0x01, *range(0xD0, 0xDA)}:
                continue
            if cursor + 2 > len(data):
                break
            segment_length = int.from_bytes(data[cursor : cursor + 2], "big")
            if segment_length < 2 or cursor + segment_length > len(data):
                break
            if marker in start_of_frame and segment_length >= 7:
                height = int.from_bytes(data[cursor + 3 : cursor + 5], "big")
                width = int.from_bytes(data[cursor + 5 : cursor + 7], "big")
                if width > 0 and height > 0:
                    return width, height
            cursor += segment_length
    return 640, 480


def _parse_markdown_table(
    lines: list[str],
    index: int,
) -> tuple[list[list[str]], int] | None:
    if index + 1 >= len(lines):
        return None
    header = _markdown_table_cells(lines[index])
    separator = _markdown_table_cells(lines[index + 1])
    if not header or not separator or len(separator) < len(header):
        return None
    if not all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in separator):
        return None
    rows = [header]
    cursor = index + 2
    while cursor < len(lines):
        cells = _markdown_table_cells(lines[cursor])
        if not cells:
            break
        if len(cells) < len(header):
            cells.extend([""] * (len(header) - len(cells)))
        rows.append(cells[: len(header)])
        cursor += 1
    if len(rows) == 1:
        return None
    return rows, cursor


def _markdown_table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _docx_bytes(
    blocks: list[MarkdownBlock],
    images: dict[str, ExportImage],
) -> bytes:
    relationships = _docx_external_link_relationships(blocks)
    image_relationships = {
        source: (f"rIdImage{index}", f"image{index}.{image.extension}")
        for index, (source, image) in enumerate(images.items(), start=1)
    }
    document_xml = _docx_document_xml(
        blocks,
        relationships,
        images,
        image_relationships,
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            _docx_content_types_xml(images),
        )
        archive.writestr("_rels/.rels", _docx_relationships_xml())
        archive.writestr("word/document.xml", document_xml)
        archive.writestr(
            "word/_rels/document.xml.rels",
            _docx_document_rels_xml(relationships, image_relationships),
        )
        archive.writestr("word/styles.xml", _docx_styles_xml())
        for source, image in images.items():
            _relationship_id, filename = image_relationships[source]
            archive.writestr(f"word/media/{filename}", image.data)
    return output.getvalue()


def _docx_document_xml(
    blocks: list[MarkdownBlock],
    relationships: dict[str, str],
    images: dict[str, ExportImage],
    image_relationships: dict[str, tuple[str, str]],
) -> str:
    body: list[str] = []
    bookmark_id = 1
    drawing_id = 1
    for block in blocks or [MarkdownBlock("paragraph", "")]:
        if block.kind == "heading":
            level = max(1, min(block.level, 6))
            body.append(
                _docx_paragraph(
                    block.text,
                    style=f"Heading{level}",
                    bookmark=_docx_bookmark_name(block.anchor),
                    bookmark_id=bookmark_id,
                    relationships=relationships,
                )
            )
            bookmark_id += 1
            continue
        if block.kind == "bullet":
            body.append(
                _docx_paragraph(f"\u2022 {block.text}", relationships=relationships)
            )
            continue
        if block.kind == "numbered":
            body.append(_docx_paragraph(block.text, relationships=relationships))
            continue
        if block.kind == "code":
            body.append(_docx_paragraph(block.text, style="Code"))
            continue
        if block.kind == "table":
            body.append(_docx_table(block.rows, relationships))
            continue
        if block.kind == "image":
            image = images.get(block.image_source)
            image_relationship = image_relationships.get(block.image_source)
            if image is not None and image_relationship is not None:
                body.append(
                    _docx_image_paragraph(
                        image,
                        image_relationship[0],
                        block.text,
                        drawing_id,
                    )
                )
                drawing_id += 1
            else:
                body.append(_docx_paragraph(block.text or block.image_source))
            continue
        body.append(_docx_paragraph(block.text, relationships=relationships))
    body.append(
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" '
        'w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
        "</w:sectPr>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships">'
        f"<w:body>{''.join(body)}</w:body>"
        "</w:document>"
    )


def _docx_image_paragraph(
    image: ExportImage,
    relationship_id: str,
    alt_text: str,
    drawing_id: int,
) -> str:
    native_width = max(1, image.width) * 9525
    native_height = max(1, image.height) * 9525
    scale = min(1.0, 5_943_600 / native_width, 6_858_000 / native_height)
    width = max(1, int(native_width * scale))
    height = max(1, int(native_height * scale))
    description = html.escape(alt_text, quote=True)
    name = f"Picture {drawing_id}"
    return (
        "<w:p><w:r><w:drawing>"
        '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/'
        '2006/wordprocessingDrawing" distT="0" distB="0" distL="0" '
        'distR="0">'
        f'<wp:extent cx="{width}" cy="{height}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        f'<wp:docPr id="{drawing_id}" name="{name}" '
        f'descr="{description}"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/'
        '2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/'
        'drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/'
        '2006/picture"><pic:nvPicPr>'
        f'<pic:cNvPr id="{drawing_id}" name="{name}" '
        f'descr="{description}"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill>'
        f'<a:blip r:embed="{relationship_id}"/>'
        '<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{width}" cy="{height}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "</pic:spPr></pic:pic></a:graphicData></a:graphic>"
        "</wp:inline></w:drawing></w:r></w:p>"
    )


def _docx_paragraph(
    text: str,
    *,
    style: str | None = None,
    bookmark: str = "",
    bookmark_id: int = 0,
    relationships: dict[str, str] | None = None,
) -> str:
    properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    start = ""
    end = ""
    if bookmark and bookmark_id > 0:
        start = f'<w:bookmarkStart w:id="{bookmark_id}" w:name="{bookmark}"/>'
        end = f'<w:bookmarkEnd w:id="{bookmark_id}"/>'
    runs = _docx_runs_for_markdown(text, relationships or {})
    return f"<w:p>{properties}{start}{runs}{end}</w:p>"


def _docx_table(
    rows: tuple[tuple[str, ...], ...],
    relationships: dict[str, str],
) -> str:
    normalized_rows = _normalized_table_rows(rows)
    if not normalized_rows:
        return ""
    column_count = len(normalized_rows[0])
    column_width = max(1, int(9360 / max(column_count, 1)))
    grid = "".join(
        f'<w:gridCol w:w="{column_width}"/>' for _ in range(column_count)
    )
    table_rows: list[str] = []
    for row in normalized_rows:
        cells = "".join(
            '<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>'
            "{paragraph}</w:tc>".format(
                width=column_width,
                paragraph=_docx_paragraph(cell, relationships=relationships),
            )
            for cell in row
        )
        table_rows.append(f"<w:tr>{cells}</w:tr>")
    return (
        "<w:tbl><w:tblPr>"
        '<w:tblW w:w="5000" w:type="pct"/>'
        '<w:tblLayout w:type="fixed"/>'
        "<w:tblBorders>"
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        "</w:tblBorders></w:tblPr>"
        f"<w:tblGrid>{grid}</w:tblGrid>"
        f"{''.join(table_rows)}</w:tbl>"
    )


def _docx_runs_for_markdown(text: str, relationships: dict[str, str]) -> str:
    parts: list[str] = []
    for segment in _inline_segments(text):
        if segment["kind"] == "link":
            href = str(segment["href"])
            label = str(segment["text"])
            link_runs = _docx_plain_runs(label, hyperlink=True)
            if href.startswith("#"):
                bookmark = _docx_bookmark_name(href[1:])
                parts.append(
                    f'<w:hyperlink w:anchor="{bookmark}">'
                    f"{link_runs}</w:hyperlink>"
                )
            else:
                relationship_id = relationships.get(href)
                if relationship_id:
                    parts.append(
                        f'<w:hyperlink r:id="{relationship_id}" w:history="1">'
                        f"{link_runs}</w:hyperlink>"
                    )
                else:
                    parts.append(_docx_plain_runs(label))
            continue
        parts.append(_docx_plain_runs(str(segment["text"])))
    return "".join(parts) or _docx_plain_runs("")


def _docx_plain_runs(text: str, *, hyperlink: bool = False) -> str:
    run_properties = (
        '<w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr>'
        if hyperlink
        else ""
    )
    lines = text.splitlines() or [""]
    return "".join(
        f"<w:r>{run_properties}<w:t xml:space=\"preserve\">"
        f"{xml_escape(line)}</w:t></w:r>"
        + ("<w:r><w:br/></w:r>" if index < len(lines) - 1 else "")
        for index, line in enumerate(lines)
    )


def _docx_external_link_relationships(blocks: list[MarkdownBlock]) -> dict[str, str]:
    links: dict[str, str] = {}
    for text in _block_text_values(blocks):
        for segment in _inline_segments(text):
            href = str(segment.get("href") or "")
            if segment["kind"] == "link" and href and not href.startswith("#"):
                links.setdefault(href, f"rIdHyperlink{len(links) + 1}")
    return links


def _docx_content_types_xml(images: dict[str, ExportImage]) -> str:
    image_types = "".join(
        '<Default Extension="{extension}" ContentType="{content_type}"/>'.format(
            extension=html.escape(extension, quote=True),
            content_type=html.escape(content_type, quote=True),
        )
        for extension, content_type in sorted(
            {(image.extension, image.content_type) for image in images.values()}
        )
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'wordprocessingml.styles+xml"/>'
        f"{image_types}"
        "</Types>"
    )


def _docx_relationships_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
        '2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )


def _docx_document_rels_xml(
    relationships: dict[str, str],
    image_relationships: dict[str, tuple[str, str]],
) -> str:
    hyperlink_relationships = "".join(
        '<Relationship Id="{relationship_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/hyperlink" Target="{target}" TargetMode="External"/>'.format(
            relationship_id=xml_escape(relationship_id),
            target=xml_escape(target),
        )
        for target, relationship_id in relationships.items()
    )
    image_relationship_xml = "".join(
        '<Relationship Id="{relationship_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/image" Target="media/{filename}"/>'.format(
            relationship_id=html.escape(relationship_id, quote=True),
            filename=html.escape(filename, quote=True),
        )
        for relationship_id, filename in image_relationships.values()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
        '2006/relationships">'
        '<Relationship Id="rIdStyles" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/styles" '
        'Target="styles.xml"/>'
        f"{hyperlink_relationships}"
        f"{image_relationship_xml}"
        "</Relationships>"
    )


def _docx_styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/></w:style>'
        f"{_docx_heading_styles()}"
        '<w:style w:type="paragraph" w:styleId="Code">'
        '<w:name w:val="Code"/><w:rPr><w:rFonts w:ascii="Courier New"/>'
        "</w:rPr></w:style>"
        "</w:styles>"
    )


def _docx_heading_styles() -> str:
    return "".join(
        '<w:style w:type="paragraph" w:styleId="Heading{level}">'
        '<w:name w:val="heading {level}"/>'
        '<w:basedOn w:val="Normal"/>'
        '<w:rPr><w:b/><w:sz w:val="{size}"/></w:rPr>'
        "</w:style>".format(level=level, size=max(24, 40 - (level * 2)))
        for level in range(1, 7)
    )


def _pdf_bytes(
    blocks: list[MarkdownBlock],
    images: dict[str, ExportImage],
    *,
    title: str,
) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import (
            Image,
            ListFlowable,
            ListItem,
            Paragraph,
            Preformatted,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as error:
        raise DocumentExportError(
            "PDF export requires the reportlab package. Refresh the ElectroBoy "
            "runtime or install reportlab."
        ) from error

    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=letter,
        title=title,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )
    styles = getSampleStyleSheet()
    story: list[object] = []
    export_blocks = blocks or [MarkdownBlock("paragraph", "")]
    index = 0
    while index < len(export_blocks):
        block = export_blocks[index]
        if block.kind == "heading":
            style_name = f"Heading{min(block.level, 3)}"
            story.append(
                _pdf_paragraph(
                    block.text,
                    styles[style_name],
                    Paragraph,
                    anchor=block.anchor,
                )
            )
            story.append(Spacer(1, 8))
        elif block.kind == "bullet":
            bullet_texts: list[str] = []
            while index < len(export_blocks) and export_blocks[index].kind == "bullet":
                bullet_texts.append(export_blocks[index].text)
                index += 1
            story.append(
                _pdf_bullet_list(
                    bullet_texts,
                    ListFlowable,
                    ListItem,
                    Paragraph,
                    ParagraphStyle,
                    styles,
                )
            )
            story.append(Spacer(1, 4))
            continue
        elif block.kind == "numbered":
            story.append(_pdf_paragraph(block.text, styles["BodyText"], Paragraph))
            story.append(Spacer(1, 8))
        elif block.kind == "code":
            story.append(Preformatted(block.text or " ", styles["Code"]))
            story.append(Spacer(1, 8))
        elif block.kind == "table":
            story.append(
                _pdf_table(
                    block.rows,
                    Table,
                    TableStyle,
                    Paragraph,
                    ParagraphStyle,
                    colors,
                    styles,
                    document.width,
                )
            )
            story.append(Spacer(1, 8))
        elif block.kind == "image":
            image = images.get(block.image_source)
            if image is None:
                story.append(
                    _pdf_paragraph(
                        block.text or block.image_source,
                        styles["BodyText"],
                        Paragraph,
                    )
                )
            else:
                native_width = max(1, image.width) * 0.75
                native_height = max(1, image.height) * 0.75
                scale = min(
                    1.0,
                    document.width / native_width,
                    (document.height * 0.8) / native_height,
                )
                flowable = Image(
                    io.BytesIO(image.data),
                    width=native_width * scale,
                    height=native_height * scale,
                )
                flowable.hAlign = "LEFT"
                story.append(flowable)
            story.append(Spacer(1, 8))
        else:
            story.append(
                _pdf_paragraph(block.text or " ", styles["BodyText"], Paragraph)
            )
            story.append(Spacer(1, 8))
        index += 1
    document.build(story)
    return output.getvalue()


def _pdf_bullet_list(
    bullet_texts,
    list_flowable_class,
    list_item_class,
    paragraph_class,
    paragraph_style_class,
    styles,
):
    item_style = paragraph_style_class(
        "ExportBulletItem",
        parent=styles["BodyText"],
        leftIndent=0,
        firstLineIndent=0,
        spaceBefore=0,
        spaceAfter=0,
    )
    items = [
        list_item_class(
            [paragraph_class(_pdf_inline_markup(text) or " ", item_style)],
            leftIndent=0,
            rightIndent=0,
            spaceBefore=0,
            spaceAfter=0,
        )
        for text in bullet_texts
    ]
    return list_flowable_class(
        items,
        bulletType="bullet",
        leftIndent=18,
        bulletDedent=8,
        bulletFontName="Helvetica",
        bulletFontSize=9,
        bulletOffsetY=1,
        spaceBefore=0,
        spaceAfter=0,
    )


def _pdf_paragraph(text: str, style, paragraph_class, *, anchor: str = ""):
    body = _pdf_inline_markup(text)
    if anchor:
        body = f'<a name="{html.escape(anchor, quote=True)}"/>{body}'
    return paragraph_class(body or " ", style)


def _pdf_table(
    rows,
    table_class,
    table_style_class,
    paragraph_class,
    paragraph_style_class,
    colors_module,
    styles,
    available_width: float,
):
    normalized_rows = _normalized_table_rows(rows)
    if not normalized_rows:
        return table_class([[""]], colWidths=[available_width])
    header_style = paragraph_style_class(
        "ExportTableHeader",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        wordWrap="CJK",
    )
    cell_style = paragraph_style_class(
        "ExportTableCell",
        parent=styles["BodyText"],
        fontSize=7.5,
        leading=9,
        wordWrap="CJK",
    )
    table_data = []
    for row_index, row in enumerate(normalized_rows):
        style = header_style if row_index == 0 else cell_style
        table_data.append(
            [paragraph_class(_pdf_inline_markup(cell) or " ", style) for cell in row]
        )
    table = table_class(
        table_data,
        colWidths=_pdf_column_widths(normalized_rows, available_width),
        repeatRows=1,
        splitByRow=1,
    )
    table.setStyle(
        table_style_class(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors_module.HexColor("#9aa5b1")),
                ("BACKGROUND", (0, 0), (-1, 0), colors_module.HexColor("#e8edf3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _pdf_column_widths(rows: list[list[str]], available_width: float) -> list[float]:
    if not rows:
        return [available_width]
    column_count = len(rows[0])
    if column_count <= 0:
        return [available_width]
    if column_count > 6:
        return [available_width / column_count for _ in range(column_count)]
    weights: list[int] = []
    for column_index in range(column_count):
        values = [_plain_inline_text(row[column_index]) for row in rows]
        longest = max((len(value) for value in values), default=1)
        weights.append(max(8, min(longest, 36)))
    total = sum(weights) or column_count
    return [available_width * weight / total for weight in weights]


def _join_paragraph(lines: list[str]) -> str:
    return " ".join(line.strip() for line in lines if line.strip())


def _clean_inline_markdown(text: str) -> str:
    """Remove simple inline styling while preserving Markdown link syntax."""

    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    return text.strip()


def _plain_inline_text(text: str) -> str:
    text = _clean_inline_markdown(text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.strip()


def _inline_segments(text: str) -> list[dict[str, str]]:
    cleaned = _clean_inline_markdown(text)
    segments: list[dict[str, str]] = []
    cursor = 0
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", cleaned):
        if match.start() > cursor:
            segments.append({"kind": "text", "text": cleaned[cursor : match.start()]})
        segments.append(
            {
                "kind": "link",
                "text": _plain_inline_text(match.group(1)),
                "href": match.group(2).strip(),
            }
        )
        cursor = match.end()
    if cursor < len(cleaned):
        segments.append({"kind": "text", "text": cleaned[cursor:]})
    return segments or [{"kind": "text", "text": ""}]


def _anchor_slug(text: str) -> str:
    slug = _plain_inline_text(text).lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or "section"


def _unique_anchor(anchor: str, used: set[str]) -> str:
    candidate = anchor
    counter = 2
    while candidate in used:
        candidate = f"{anchor}-{counter}"
        counter += 1
    used.add(candidate)
    return candidate


def _docx_bookmark_name(anchor: str) -> str:
    slug = _anchor_slug(anchor).replace("-", "_")
    slug = re.sub(r"[^A-Za-z0-9_]", "_", slug)
    if not slug or not slug[0].isalpha():
        slug = f"b_{slug}"
    return slug[:40]


def _pdf_inline_markup(text: str) -> str:
    parts: list[str] = []
    for segment in _inline_segments(text):
        if segment["kind"] == "link":
            href = _pdf_href(segment["href"])
            label = html.escape(segment["text"], quote=False)
            parts.append(
                '<a href="{href}"><font color="#0563C1"><u>{label}</u></font></a>'
                .format(href=html.escape(href, quote=True), label=label)
            )
            continue
        parts.append(html.escape(segment["text"], quote=False))
    return "".join(parts)


def _pdf_href(href: str) -> str:
    if href.startswith("#"):
        return f"#{_anchor_slug(href[1:])}"
    return href


def _normalized_table_rows(rows: tuple[tuple[str, ...], ...]) -> list[list[str]]:
    if not rows:
        return []
    column_count = max((len(row) for row in rows), default=0)
    if column_count <= 0:
        return []
    normalized: list[list[str]] = []
    for row in rows:
        cells = list(row)
        if len(cells) < column_count:
            cells.extend([""] * (column_count - len(cells)))
        normalized.append(cells[:column_count])
    return normalized


def _block_text_values(blocks: list[MarkdownBlock]) -> list[str]:
    values: list[str] = []
    for block in blocks:
        if block.text:
            values.append(block.text)
        for row in block.rows:
            values.extend(cell for cell in row if cell)
    return values


def _document_title(blocks: list[MarkdownBlock], fallback: str) -> str:
    for block in blocks:
        if block.kind == "heading" and block.level == 1 and block.text:
            return block.text
    return fallback


def _export_stem(source_name: str) -> str:
    stem = Path(source_name).stem or "document"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-")
    return stem or "document"


def _pdf_escape(text: str) -> str:
    return html.escape(text, quote=False)
