from __future__ import annotations

import base64
import importlib.util
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.document_export import (  # noqa: E402
    _pdf_bullet_list,
    export_markdown_document,
    export_markdown_text,
)


SAMPLE_MARKDOWN = """# Exported Document

This document includes **formatted** text and a [link](https://example.com).

| ID | Description |
| --- | --- |
| REQ-001 | Export documents as Markdown, DOCX, and PDF. |

```python
print("hello")
```
"""

TOC_AND_WIDE_TABLE_MARKDOWN = (
    """# Exported Document

## Table of Contents

- [Wide Results](#wide-results)

## Wide Results

"""
    "| Column One With A Long Header | Column Two With A Long Header | "
    "Column Three With A Long Header | Column Four With A Long Header | "
    "Column Five With A Long Header |\n"
    "| --- | --- | --- | --- | --- |\n"
    "| Alpha value with a long explanation | "
    "Beta value with a long explanation | "
    "Gamma value with a long explanation | "
    "Delta value with a long explanation | "
    "Epsilon value with a long explanation |\n"
)

BULLET_MARKDOWN = """# Bullets

- First long bullet item that should wrap with hanging indentation in PDF output.
- Second bullet item should not have paragraph-style spacing before it.
"""

PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8A"
    "AQUBAScY42YAAAAASUVORK5CYII="
)
PIXEL_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
    "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
    "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjL/wAARCAACAAIDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQF"
    "BgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEI"
    "I0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNk"
    "ZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLD"
    "xMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEB"
    "AQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJB"
    "UQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZH"
    "SElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaan"
    "qKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oA"
    "DAMBAAIRAxEAPwCOiiivmj7A/9k="
)


class DocumentExportTests(unittest.TestCase):
    def test_markdown_export_returns_original_document(self) -> None:
        exported = export_markdown_text(
            SAMPLE_MARKDOWN,
            "docs/requirements-feature.md",
            "markdown",
        )

        self.assertEqual(exported.filename, "requirements-feature.md")
        self.assertEqual(exported.content_type, "text/markdown; charset=utf-8")
        self.assertEqual(exported.data.decode("utf-8"), SAMPLE_MARKDOWN)

    def test_docx_export_contains_markdown_content(self) -> None:
        exported = export_markdown_text(SAMPLE_MARKDOWN, "docs/guide.md", "docx")

        self.assertEqual(exported.filename, "guide.docx")
        self.assertEqual(
            exported.content_type,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        with zipfile.ZipFile(io.BytesIO(exported.data)) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8")

        self.assertIn("Exported Document", document_xml)
        self.assertIn("REQ-001", document_xml)
        self.assertIn('print("hello")', document_xml)

    def test_docx_export_preserves_toc_links_and_wraps_wide_tables(self) -> None:
        exported = export_markdown_text(
            TOC_AND_WIDE_TABLE_MARKDOWN,
            "docs/guide.md",
            "docx",
        )

        with zipfile.ZipFile(io.BytesIO(exported.data)) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8")

        self.assertIn('w:bookmarkStart w:id="3" w:name="wide_results"', document_xml)
        self.assertIn('<w:hyperlink w:anchor="wide_results">', document_xml)
        self.assertIn('<w:tblW w:w="5000" w:type="pct"/>', document_xml)
        self.assertIn('<w:tblLayout w:type="fixed"/>', document_xml)
        self.assertIn("<w:tblGrid>", document_xml)

    def test_docx_export_preserves_external_links(self) -> None:
        exported = export_markdown_text(SAMPLE_MARKDOWN, "docs/guide.md", "docx")

        with zipfile.ZipFile(io.BytesIO(exported.data)) as archive:
            relationships_xml = archive.read(
                "word/_rels/document.xml.rels",
            ).decode("utf-8")

        self.assertIn("relationships/hyperlink", relationships_xml)
        self.assertIn('Target="https://example.com"', relationships_xml)

    def test_docx_export_embeds_local_png_and_jpeg_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = root / "images"
            images.mkdir()
            (images / "pixel.png").write_bytes(PIXEL_PNG)
            (images / "photo.jpg").write_bytes(PIXEL_JPEG)
            document = root / "guide.md"
            document.write_text(
                "# Images\n\n"
                "![Pixel](images/pixel.png)\n\n"
                "![Photo](images/photo.jpg)\n",
                encoding="utf-8",
            )

            exported = export_markdown_document(document, "guide.md", "docx")

        with zipfile.ZipFile(io.BytesIO(exported.data)) as archive:
            names = set(archive.namelist())
            document_xml = archive.read("word/document.xml").decode("utf-8")
            relationships_xml = archive.read(
                "word/_rels/document.xml.rels"
            ).decode("utf-8")
            content_types_xml = archive.read("[Content_Types].xml").decode("utf-8")
            png_data = archive.read("word/media/image1.png")
            jpeg_data = archive.read("word/media/image2.jpg")

        self.assertIn("word/media/image1.png", names)
        self.assertIn("word/media/image2.jpg", names)
        self.assertEqual(png_data, PIXEL_PNG)
        self.assertEqual(jpeg_data, PIXEL_JPEG)
        self.assertEqual(document_xml.count("<w:drawing>"), 2)
        self.assertIn('descr="Pixel"', document_xml)
        self.assertIn('descr="Photo"', document_xml)
        self.assertEqual(relationships_xml.count("relationships/image"), 2)
        self.assertIn('Extension="png" ContentType="image/png"', content_types_xml)
        self.assertIn('Extension="jpg" ContentType="image/jpeg"', content_types_xml)

    @unittest.skipIf(
        importlib.util.find_spec("reportlab") is None,
        "reportlab is not installed",
    )
    def test_pdf_export_returns_pdf_bytes(self) -> None:
        exported = export_markdown_text(SAMPLE_MARKDOWN, "docs/guide.md", "pdf")

        self.assertEqual(exported.filename, "guide.pdf")
        self.assertEqual(exported.content_type, "application/pdf")
        self.assertTrue(exported.data.startswith(b"%PDF"))

    @unittest.skipIf(
        importlib.util.find_spec("reportlab") is None,
        "reportlab is not installed",
    )
    def test_pdf_export_handles_toc_links_and_wide_tables(self) -> None:
        exported = export_markdown_text(
            TOC_AND_WIDE_TABLE_MARKDOWN,
            "docs/guide.md",
            "pdf",
        )

        self.assertEqual(exported.content_type, "application/pdf")
        self.assertTrue(exported.data.startswith(b"%PDF"))

    @unittest.skipIf(
        importlib.util.find_spec("reportlab") is None,
        "reportlab is not installed",
    )
    def test_pdf_export_embeds_local_png_and_jpeg_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = root / "images"
            images.mkdir()
            (images / "pixel.png").write_bytes(PIXEL_PNG)
            (images / "photo.jpg").write_bytes(PIXEL_JPEG)
            document = root / "guide.md"
            document.write_text(
                "# Images\n\n"
                "![Pixel](images/pixel.png)\n\n"
                "![Photo](images/photo.jpg)\n",
                encoding="utf-8",
            )

            exported = export_markdown_document(document, "guide.md", "pdf")

        self.assertTrue(exported.data.startswith(b"%PDF"))
        self.assertGreaterEqual(exported.data.count(b"/Subtype /Image"), 2)

    @unittest.skipIf(
        importlib.util.find_spec("reportlab") is None,
        "reportlab is not installed",
    )
    def test_pdf_bullets_use_hanging_list_without_item_spacing(self) -> None:
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import ListFlowable, ListItem, Paragraph

        bullet_list = _pdf_bullet_list(
            [
                "First long bullet item that should wrap under the text.",
                "Second bullet item.",
            ],
            ListFlowable,
            ListItem,
            Paragraph,
            ParagraphStyle,
            getSampleStyleSheet(),
        )
        exported = export_markdown_text(BULLET_MARKDOWN, "docs/guide.md", "pdf")

        self.assertIsInstance(bullet_list, ListFlowable)
        self.assertEqual(getattr(bullet_list, "spaceAfter"), 0)
        self.assertEqual(getattr(bullet_list, "_leftIndent"), 18)
        self.assertEqual(getattr(bullet_list, "_bulletDedent"), 8)
        self.assertEqual(len(bullet_list._flowables), 2)
        for item in bullet_list._flowables:
            self.assertIsInstance(item, ListItem)
            self.assertEqual(item._params["spaceBefore"], 0)
            self.assertEqual(item._params["spaceAfter"], 0)
        self.assertTrue(exported.data.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
