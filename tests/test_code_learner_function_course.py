from __future__ import annotations

import json
from pathlib import Path

import pytest

from electroboy.adapters.base import AgentInvocation, AgentResult
from electroboy.workflows.code_learner.course_builder import CourseBuilder
from electroboy.workflows.code_learner.domain import (
    CodeLearnerError,
    repository_revision,
)
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore
from electroboy.workflows.code_learner.knowledge_validation import EnrichmentController

TOPICS = ("contract", "control-flow", "calls", "side-effects", "errors", "tests")


class FakeRuntime:
    def __init__(self, results: list[AgentResult]) -> None:
        self.results = list(results)
        self.invocations: list[AgentInvocation] = []

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        self.invocations.append(invocation)
        return self.results.pop(0)


def _source(line: int = 1) -> dict[str, object]:
    return {
        "path": "src/app.py",
        "start_line": line,
        "end_line": line,
        "reason": "Defines the function behavior.",
    }


def _symbol(
    common: dict[str, object],
    symbol_id: str,
    qualified_name: str,
    line: int,
    *,
    complete: bool = True,
    callers: list[str] | None = None,
    callees: list[str] | None = None,
) -> dict[str, object]:
    attributes: dict[str, object] = {
        "qualified_name": qualified_name,
        "symbol_kind": "function",
        "language": "python",
        "owning_module_id": "module.app",
        "implementation_refs": [_source(line)],
        "visibility": "public",
    }
    if complete:
        edge_ids = [*(callers or []), *(callees or [])]
        attributes.update(
            {
                "signature": f"{qualified_name.split('.')[-1]}()",
                "caller_ids": callers or [],
                "callee_ids": callees or [],
                "input_types": [],
                "output_types": ["int"],
                "side_effects": [],
                "state_access_ids": [],
                "test_ids": [],
                "analysis_limitations": [],
                "call_edge_confidence": {item: "verified" for item in edge_ids},
            }
        )
    return {
        **common,
        "record_type": "entity",
        "id": symbol_id,
        "kind": "symbol",
        "name": qualified_name.split(".")[-1],
        "summary": f"Function {qualified_name}.",
        "parent_id": "module.app",
        "source_refs": [_source(line)],
        "confidence": "high",
        "attributes": attributes,
    }


def _seed(root: Path, *, complete: bool = True) -> tuple[KnowledgeStore, str]:
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text(
        "def run():\n    return helper()\n"
        "def helper():\n    return 1\n"
        "def run_beta():\n    return 2\n",
        encoding="utf-8",
    )
    revision = repository_revision(root)
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-function",
        "repository_revision": revision,
    }
    records = [
        {
            **common,
            "record_type": "knowledge_manifest",
            "id": "knowledge.manifest",
            "repository_name": "functions",
            "scope_path": ".",
            "status": "validated",
            "entity_count": 5,
            "relationship_count": 1,
            "flow_count": 0,
            "diagnostic_count": 0,
        },
        {
            **common,
            "record_type": "entity",
            "id": "repository.root",
            "kind": "repository",
            "name": "functions",
            "summary": "Function fixture.",
            "source_refs": [_source()],
            "confidence": "verified",
        },
        {
            **common,
            "record_type": "entity",
            "id": "module.app",
            "kind": "module",
            "name": "App",
            "summary": "Application module.",
            "parent_id": "repository.root",
            "source_refs": [_source()],
            "confidence": "high",
        },
        _symbol(
            common,
            "symbol.alpha.run",
            "pkg.alpha.run",
            1,
            complete=complete,
            callees=["symbol.helper"] if complete else [],
        ),
        _symbol(common, "symbol.helper", "pkg.alpha.helper", 3),
        _symbol(common, "symbol.beta.run", "pkg.beta.run", 5),
        {
            **common,
            "record_type": "relationship",
            "id": "relationship.alpha-calls-helper",
            "kind": "calls",
            "from_id": "symbol.alpha.run",
            "to_id": "symbol.helper",
            "summary": "run calls helper.",
            "source_refs": [_source(2)],
            "confidence": "verified",
        },
    ]
    store = KnowledgeStore(root)
    store.save_knowledge(records)
    return store, revision


def _parent_course(
    revision: str, mode: str, scope_id: str, document_id: str
) -> list[dict[str, object]]:
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-function",
        "repository_revision": revision,
    }
    return [
        {
            **common,
            "record_type": "document",
            "id": document_id,
            "title": mode.title(),
            "course_mode": mode,
            "scope_id": scope_id,
            "status": "ready",
        },
        {
            **common,
            "record_type": "section",
            "id": f"{document_id}.functions",
            "parent_id": document_id,
            "heading_level": 2,
            "order": 1,
            "title": "Functions",
            "body": "The app calls helper functions.",
            "detail_level": mode,
            "knowledge_entity_ids": ["module.app", "symbol.alpha.run"],
            "relationship_ids": ["relationship.alpha-calls-helper"],
            "runtime_flow_ids": [],
            "diagnostic_ids": [],
            "related_module_ids": ["module.app"],
            "related_symbol_ids": ["symbol.alpha.run"],
            "prerequisite_section_ids": [],
            "deep_dive_ids": [],
            "source_refs": [_source()],
            "confidence": "high",
            "diagrams": [],
        },
    ]


def _function_course(revision: str) -> list[dict[str, object]]:
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-function",
        "repository_revision": revision,
    }
    document_id = "course.function.symbol.alpha.run"
    records: list[dict[str, object]] = [
        {
            **common,
            "record_type": "document",
            "id": document_id,
            "title": "Function: pkg.alpha.run",
            "course_mode": "function",
            "scope_id": "symbol.alpha.run",
            "coverage_topics": list(TOPICS),
            "status": "ready",
        }
    ]
    for index, topic in enumerate(TOPICS):
        section_id = f"{document_id}.{topic}"
        body = f"Evidence-grounded {topic} explanation."
        diagrams: list[dict[str, object]] = []
        edge_confidence = None
        if topic == "calls":
            body += (
                "\n\n```mermaid\nflowchart LR\n"
                "  Run[run] -->|verified| Helper[helper]\n```"
            )
            diagrams = [
                {
                    "id": "diagram.function.calls",
                    "type": "flowchart",
                    "question": "What does run call?",
                }
            ]
            edge_confidence = {"symbol.helper": "verified"}
        record = {
            **common,
            "record_type": "section",
            "id": section_id,
            "parent_id": document_id,
            "heading_level": 2,
            "order": index,
            "title": topic.title(),
            "topic": topic,
            "body": body,
            "detail_level": "function",
            "previous_section_id": (
                f"{document_id}.{TOPICS[index - 1]}" if index else None
            ),
            "next_section_id": (
                f"{document_id}.{TOPICS[index + 1]}"
                if index + 1 < len(TOPICS)
                else None
            ),
            "return_section_id": None,
            "deep_dive_ids": [],
            "knowledge_entity_ids": ["symbol.alpha.run", "symbol.helper"],
            "relationship_ids": ["relationship.alpha-calls-helper"],
            "runtime_flow_ids": [],
            "diagnostic_ids": [],
            "related_module_ids": ["module.app"],
            "related_symbol_ids": ["symbol.helper"],
            "prerequisite_section_ids": [],
            "source_refs": [_source(1)],
            "confidence": "verified",
            "diagrams": diagrams,
        }
        if edge_confidence is not None:
            record["call_edge_confidence"] = edge_confidence
        records.append(record)
    return records


def _jsonl(records: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(record) for record in records)


def test_function_resolution_covers_exact_partial_ambiguous_and_missing(
    tmp_path: Path,
) -> None:
    _seed(tmp_path)
    builder = CourseBuilder(tmp_path)

    assert builder.resolve_function("pkg.alpha.run").status == "qualified"
    assert builder.resolve_function("symbol.alpha.run").status == "exact"
    assert builder.resolve_function("helper").status == "exact"
    assert builder.resolve_function("alpha.help").status == "partial"
    assert builder.resolve_function("run").status == "ambiguous"
    assert builder.resolve_function("does_not_exist").status == "missing"


def test_function_course_is_generated_cached_and_linked_to_parent_courses(
    tmp_path: Path,
) -> None:
    store, revision = _seed(tmp_path)
    store.save_course(
        "architecture",
        "repository.root",
        _parent_course(
            revision,
            "architecture",
            "repository.root",
            "course.architecture.repository.root",
        ),
    )
    store.save_course(
        "module",
        "module.app",
        _parent_course(
            revision, "module", "module.app", "course.module.module.app"
        ),
    )
    runtime = FakeRuntime(
        [AgentResult(ok=True, final_message=_jsonl(_function_course(revision)))]
    )
    builder = CourseBuilder(
        tmp_path,
        runtime_factory=lambda _role, _root: runtime,
        max_attempts=1,
    )

    first = builder.build_function("pkg.alpha.run")
    second = builder.build_function("symbol.alpha.run")

    assert first == second
    assert len(runtime.invocations) == 1
    assert (tmp_path / first.markdown_path).is_file()
    assert "flowchart LR" in (tmp_path / first.markdown_path).read_text()
    target = "course.function.symbol.alpha.run"
    for mode, scope in (
        ("architecture", "repository.root"),
        ("module", "module.app"),
    ):
        parent = store.load_course(mode, scope)
        section = next(item for item in parent if item["record_type"] == "section")
        assert target in section["deep_dive_ids"]


def test_missing_function_evidence_runs_targeted_enrichment_before_course(
    tmp_path: Path,
) -> None:
    store, revision = _seed(tmp_path, complete=False)
    current = store.get("symbol.alpha.run")
    enriched = _symbol(
        {
            "schema_version": 1,
            "analysis_run_id": "run-function",
            "repository_revision": revision,
        },
        "symbol.alpha.run",
        "pkg.alpha.run",
        1,
        callees=["symbol.helper"],
    )
    assert current["id"] == enriched["id"]
    enrichment_runtime = FakeRuntime(
        [AgentResult(ok=True, final_message=json.dumps(enriched))]
    )
    course_runtime = FakeRuntime(
        [AgentResult(ok=True, final_message=_jsonl(_function_course(revision)))]
    )

    result = CourseBuilder(
        tmp_path,
        runtime_factory=lambda _role, _root: course_runtime,
        enrichment_factory=lambda root: EnrichmentController(
            root,
            runtime_factory=lambda _role, _root: enrichment_runtime,
            max_attempts=1,
        ),
        max_attempts=1,
    ).build_function("pkg.alpha.run")

    assert result.scope_id == "symbol.alpha.run"
    assert len(enrichment_runtime.invocations) == 1
    assert "symbol.alpha.run" in enrichment_runtime.invocations[0].prompt
    request = store.get("request.function-evidence.symbol.alpha.run")
    assert request["status"] == "resolved"


def test_function_build_reports_ambiguous_and_missing_states(tmp_path: Path) -> None:
    _seed(tmp_path)
    builder = CourseBuilder(tmp_path)

    with pytest.raises(CodeLearnerError, match="ambiguous"):
        builder.build_function("run")
    with pytest.raises(CodeLearnerError, match="not found"):
        builder.build_function("missing")


def test_stale_function_course_is_regenerated(tmp_path: Path) -> None:
    store, revision = _seed(tmp_path)
    stale = _function_course(revision)
    stale[0]["status"] = "stale"
    store.save_course("function", "symbol.alpha.run", stale)
    runtime = FakeRuntime(
        [AgentResult(ok=True, final_message=_jsonl(_function_course(revision)))]
    )

    result = CourseBuilder(
        tmp_path,
        runtime_factory=lambda _role, _root: runtime,
        max_attempts=1,
    ).build_function("symbol.alpha.run")

    assert result.scope_id == "symbol.alpha.run"
    assert len(runtime.invocations) == 1
    assert store.load_course("function", "symbol.alpha.run")[0]["status"] == "ready"
