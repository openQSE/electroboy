"""Project layered Phase 2 courses into the stable learner-pane view model."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .course_graph import CourseGraph
from .domain import CodeLearnerError, SourceAdapter
from .knowledge_store import KnowledgeStore


def phase2_analysis_payload(root: Path | str) -> dict[str, object]:
    """Return menu-oriented module and symbol summaries from durable knowledge."""

    store = KnowledgeStore(root)
    records = store.load_knowledge(validate_sources=False)
    manifest = next(
        (
            record
            for record in records
            if record.get("record_type") == "knowledge_manifest"
        ),
        {},
    )
    attributes = manifest.get("attributes")
    inventory = attributes.get("inventory") if isinstance(attributes, dict) else {}
    languages = inventory.get("languages", []) if isinstance(inventory, dict) else []
    modules = []
    symbols = []
    source_files: set[str] = set()
    for record in records:
        references = [
            reference
            for reference in record.get("source_refs", [])
            if isinstance(reference, dict)
        ]
        source_files.update(
            str(reference.get("path") or "")
            for reference in references
            if reference.get("path")
        )
        if record.get("record_type") != "entity":
            continue
        if record.get("kind") == "module":
            modules.append(
                {
                    "id": record.get("id"),
                    "path": record.get("id"),
                    "name": record.get("name"),
                    "summary": record.get("summary"),
                    "file_count": len(
                        {str(reference.get("path")) for reference in references}
                    ),
                    "source_refs": references,
                }
            )
        elif record.get("kind") == "symbol":
            details = record.get("attributes")
            details = details if isinstance(details, dict) else {}
            primary = references[0] if references else {}
            symbols.append(
                {
                    "id": record.get("id"),
                    "name": record.get("name"),
                    "qualified_name": details.get("qualified_name")
                    or record.get("name"),
                    "kind": details.get("symbol_kind") or "symbol",
                    "module_id": record.get("parent_id"),
                    "file_path": primary.get("path") or "",
                    "start_line": primary.get("start_line") or 1,
                    "end_line": primary.get("end_line") or 1,
                }
            )
    return {
        "source_root": str(store.root),
        "source_files": sorted(source_files),
        "language_counts": {
            str(item.get("name") or "unknown").lower(): len(
                item.get("evidence_paths", [])
            )
            for item in languages
            if isinstance(item, dict)
        },
        "modules": sorted(modules, key=lambda item: str(item.get("name") or "")),
        "symbols": sorted(
            symbols, key=lambda item: str(item.get("qualified_name") or "")
        ),
        "truncated": False,
    }


def project_navigation(
    root: Path | str,
    navigation: Mapping[str, object],
) -> dict[str, object]:
    """Build the learner pane payload for one layered navigation location."""

    repository = Path(root).expanduser().resolve()
    store = KnowledgeStore(repository)
    current = navigation.get("current")
    if not isinstance(current, Mapping):
        raise CodeLearnerError("course navigation has no current section")
    mode = str(current.get("mode") or "")
    scope_id = str(current.get("scope_id") or "")
    course_id = str(current.get("course_id") or "")
    section_id = str(current.get("id") or "")
    records = store.load_course(mode, scope_id, validate_sources=False)
    document = next(
        record for record in records if record.get("record_type") == "document"
    )
    sections = sorted(
        (record for record in records if record.get("record_type") == "section"),
        key=lambda record: (int(record.get("order") or 0), str(record.get("id"))),
    )
    walkthrough = {
        "id": course_id,
        "title": document.get("title") or course_id,
        "source_root": str(repository),
        "learning_mode": mode,
        "mode_target": scope_id if mode != "architecture" else "",
        "intended_audience": "",
        "steps": [_project_section(section) for section in sections],
        "current_step_id": section_id,
        "generated_at": document.get("generated_at") or "",
        "source_revision": document.get("repository_revision") or "",
        "review_status": document.get("status") or "ready",
        "qa_history": [],
        "breadcrumbs": list(navigation.get("breadcrumbs", [])),
        "can_go_back": len(navigation.get("breadcrumbs", [])) > 1,
    }
    source = _source_payload(repository, navigation, current)
    graph = CourseGraph.from_store(store)
    summaries = [
        {
            "id": document_id,
            "title": value.get("title") or document_id,
            "learning_mode": value.get("course_mode"),
            "mode_target": value.get("scope_id"),
            "current_step_id": (
                section_id if document_id == course_id else ""
            ),
            "source_revision": value.get("repository_revision"),
            "review_status": value.get("status"),
            "step_count": sum(
                1 for node in graph.nodes.values() if node.course_id == document_id
            ),
            "qa_count": 0,
        }
        for document_id, value in graph.documents.items()
    ]
    return {
        "status": "ready",
        "walkthrough": walkthrough,
        "current_walkthrough": walkthrough,
        "walkthroughs": summaries,
        "source": source,
        "course_navigation": dict(navigation),
        "course_artifact": {
            "mode": mode,
            "scope_id": scope_id,
            "jsonl_path": store.course_path(mode, scope_id)
            .relative_to(repository)
            .as_posix(),
            "markdown_path": store.course_markdown_path(mode, scope_id)
            .relative_to(repository)
            .as_posix(),
            "title": document.get("title") or course_id,
        },
    }


def _project_section(section: Mapping[str, object]) -> dict[str, object]:
    references = [
        reference
        for reference in section.get("source_refs", [])
        if isinstance(reference, dict)
    ]
    primary = references[0] if references else {}
    return {
        "id": section.get("id"),
        "title": section.get("title"),
        "explanation": section.get("body"),
        "primary_reference": _project_reference(primary),
        "secondary_references": [
            _project_reference(reference) for reference in references[1:]
        ],
        "deep_dive_ids": list(section.get("deep_dive_ids", [])),
        "knowledge_entity_ids": list(section.get("knowledge_entity_ids", [])),
        "relationship_ids": list(section.get("relationship_ids", [])),
        "runtime_flow_ids": list(section.get("runtime_flow_ids", [])),
        "diagrams": list(section.get("diagrams", [])),
    }


def _project_reference(reference: Mapping[str, object]) -> dict[str, object]:
    return {
        "file_path": str(reference.get("path") or ""),
        "start_line": int(reference.get("start_line") or 1),
        "end_line": int(reference.get("end_line") or 1),
        "symbol": str(reference.get("symbol") or ""),
        "label": str(reference.get("reason") or ""),
        "kind": "course-evidence",
    }


def _source_payload(
    root: Path,
    navigation: Mapping[str, object],
    current: Mapping[str, object],
) -> dict[str, object] | None:
    state = navigation.get("navigation")
    state = state if isinstance(state, Mapping) else {}
    code_view = state.get("code_view")
    code_view = code_view if isinstance(code_view, Mapping) else {}
    reference = current.get("source_ref")
    reference = reference if isinstance(reference, Mapping) else {}
    path = str(code_view.get("path") or reference.get("path") or "")
    if not path:
        return None
    start = int(
        code_view.get("selected_start_line")
        or reference.get("start_line")
        or 1
    )
    end = int(
        code_view.get("selected_end_line") or reference.get("end_line") or start
    )
    return SourceAdapter(root).source_payload(
        path,
        start_line=start,
        end_line=end,
        padding=80,
    )
