"""Thin Code Learner adapter over the generic structured-artifact renderer."""

from __future__ import annotations

from pathlib import Path

from electroboy.structured_artifacts import RenderResult, render_artifact

from .knowledge_store import KnowledgeStore


def render_saved_course(
    root: Path | str,
    mode: str,
    scope_id: str,
) -> RenderResult:
    """Render one validated course through the shared JSONL-to-Markdown path."""

    resolved_root = Path(root).expanduser().resolve()
    store = KnowledgeStore(resolved_root)
    jsonl_path = store.course_path(mode, scope_id)
    markdown_path = store.course_markdown_path(mode, scope_id)
    return render_artifact(
        resolved_root,
        "course",
        jsonl_path=jsonl_path.relative_to(resolved_root).as_posix(),
        markdown_path=markdown_path.relative_to(resolved_root).as_posix(),
    )
