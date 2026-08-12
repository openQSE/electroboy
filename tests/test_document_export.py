from __future__ import annotations

import importlib.util
import io
import sys
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.document_export import export_markdown_text  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
