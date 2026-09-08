"""Shared Markdown rendering for ElectroBoy presentation surfaces."""

from __future__ import annotations

import html
import re


_DETAILS_TAG_RE = re.compile(r"<details(?P<attrs>[^>]*)>", re.IGNORECASE)
_MERMAID_BLOCK_RE = re.compile(
    r'<pre><code class="(?:language-)?mermaid">(?P<body>.*?)</code></pre>',
    re.DOTALL,
)


def render_markdown(text: str) -> str:
    """Render Markdown with the same behavior across ElectroBoy views."""

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
                f' class="language-{html.escape(language)}"' if language else ""
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


def _promote_mermaid_blocks(rendered: str) -> str:
    return _MERMAID_BLOCK_RE.sub(
        lambda match: f'<div class="mermaid">{match.group("body")}</div>',
        rendered,
    )
