"""Export Markdown documents to downloadable formats."""

from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape


SUPPORTED_DOCUMENT_EXPORT_FORMATS = {"markdown", "md", "docx", "pdf"}


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
    return export_markdown_text(markdown, relative_path, export_format)


def export_markdown_text(
    markdown: str,
    source_name: str,
    export_format: str,
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
    if normalized_format == "docx":
        return DocumentExport(
            data=_docx_bytes(blocks),
            filename=f"{stem}.docx",
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        )
    return DocumentExport(
        data=_pdf_bytes(blocks, title=_document_title(blocks, stem)),
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
            blocks.append(MarkdownBlock("paragraph", _join_paragraph(paragraph)))
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


def _docx_bytes(blocks: list[MarkdownBlock]) -> bytes:
    relationships = _docx_external_link_relationships(blocks)
    document_xml = _docx_document_xml(blocks, relationships)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _docx_content_types_xml())
        archive.writestr("_rels/.rels", _docx_relationships_xml())
        archive.writestr("word/document.xml", document_xml)
        archive.writestr(
            "word/_rels/document.xml.rels",
            _docx_document_rels_xml(relationships),
        )
        archive.writestr("word/styles.xml", _docx_styles_xml())
    return output.getvalue()


def _docx_document_xml(
    blocks: list[MarkdownBlock],
    relationships: dict[str, str],
) -> str:
    body: list[str] = []
    bookmark_id = 1
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


def _docx_content_types_xml() -> str:
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


def _docx_document_rels_xml(relationships: dict[str, str]) -> str:
    hyperlink_relationships = "".join(
        '<Relationship Id="{relationship_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/hyperlink" Target="{target}" TargetMode="External"/>'.format(
            relationship_id=xml_escape(relationship_id),
            target=xml_escape(target),
        )
        for target, relationship_id in relationships.items()
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


def _pdf_bytes(blocks: list[MarkdownBlock], *, title: str) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import (
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
    for block in blocks or [MarkdownBlock("paragraph", "")]:
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
        elif block.kind == "bullet":
            story.append(
                _pdf_paragraph(f"\u2022 {block.text}", styles["BodyText"], Paragraph)
            )
        elif block.kind == "numbered":
            story.append(_pdf_paragraph(block.text, styles["BodyText"], Paragraph))
        elif block.kind == "code":
            story.append(Preformatted(block.text or " ", styles["Code"]))
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
        else:
            story.append(
                _pdf_paragraph(block.text or " ", styles["BodyText"], Paragraph)
            )
        story.append(Spacer(1, 8))
    document.build(story)
    return output.getvalue()


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
