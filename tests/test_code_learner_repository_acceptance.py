from __future__ import annotations

import json
from pathlib import Path

import pytest

from electroboy.adapters.base import AgentInvocation, AgentResult
from electroboy.workflows.code_learner.analysis_adapters import (
    SymbolEvidenceCollector,
)
from electroboy.workflows.code_learner.course_builder import CourseBuilder
from electroboy.workflows.code_learner.domain import (
    analyze_repository,
    repository_revision,
)
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore


class FixtureRuntime:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.records = records
        self.invocations: list[AgentInvocation] = []

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        self.invocations.append(invocation)
        return AgentResult(
            ok=True,
            final_message="\n".join(json.dumps(item) for item in self.records),
        )


@pytest.mark.parametrize(
    ("layout", "language", "expected_paths", "expected_symbols"),
    [
        (
            "python",
            "python",
            {
                "packages/app/__init__.py",
                "services/api.py",
                "persistence/store.py",
            },
            {"create_app", "handle_request", "save_record"},
        ),
        (
            "javascript",
            "javascript",
            {"src/routes.js", "src/component.js", "src/runtime.js"},
            {"routeRequest", "renderComponent", "startRuntime"},
        ),
        (
            "c",
            "c",
            {"src/core.c", "src/providers/memory.c", "src/providers/tcp.c"},
            {"dispatch", "memory_send", "tcp_send"},
        ),
    ],
)
def test_repository_shapes_build_broad_architecture_without_source_mutation(
    tmp_path: Path,
    layout: str,
    language: str,
    expected_paths: set[str],
    expected_symbols: set[str],
) -> None:
    repository, module_sources = _write_repository(tmp_path / layout, layout)
    before = _source_snapshot(repository)
    analysis = analyze_repository(repository)
    symbols = SymbolEvidenceCollector(repository).collect()["symbols"]
    symbol_names = {str(item["name"]) for item in symbols}
    store = _save_knowledge(repository, language, module_sources)
    runtime = FixtureRuntime(
        _architecture_course(repository, language, tuple(module_sources))
    )

    result = CourseBuilder(
        repository,
        runtime_factory=lambda _role, _root: runtime,
        max_attempts=1,
    ).build_architecture()

    assert expected_paths <= set(analysis.source_files)
    assert expected_symbols <= symbol_names
    assert language in analysis.language_counts
    assert len(runtime.invocations) == 1
    markdown = (repository / result.markdown_path).read_text(encoding="utf-8")
    assert "flowchart LR" in markdown
    assert "sequenceDiagram" in markdown
    assert set(store.load_course("architecture", "repository.root")[1][
        "knowledge_entity_ids"
    ]) >= set(module_sources)
    assert _source_snapshot(repository) == before


def _write_repository(
    root: Path, layout: str
) -> tuple[Path, dict[str, str]]:
    root.mkdir()
    (root / "README.md").write_text(f"# {layout} acceptance\n", encoding="utf-8")
    if layout == "python":
        _write(root / "packages/app/__init__.py", "def create_app():\n    return {}\n")
        _write(
            root / "services/api.py",
            "def handle_request(request):\n    return request\n",
        )
        _write(
            root / "persistence/store.py",
            "def save_record(record):\n    return record\n",
        )
        (root / "pyproject.toml").write_text(
            "[project]\nname = 'acceptance'\n",
            encoding="utf-8",
        )
        modules = {
            "module.package": "packages/app/__init__.py",
            "module.service": "services/api.py",
            "module.persistence": "persistence/store.py",
        }
    elif layout == "javascript":
        _write(
            root / "src/routes.js",
            "export function routeRequest(request) { return request; }\n",
        )
        _write(
            root / "src/component.js",
            "export function renderComponent(value) { return String(value); }\n",
        )
        _write(
            root / "src/runtime.js",
            "export function startRuntime() { return true; }\n",
        )
        (root / "package.json").write_text(
            '{"name":"acceptance","dependencies":{"router":"1.0.0"}}\n',
            encoding="utf-8",
        )
        modules = {
            "module.routes": "src/routes.js",
            "module.components": "src/component.js",
            "module.runtime": "src/runtime.js",
        }
    else:
        _write(
            root / "src/core.c",
            "typedef int (*send_fn)(int);\n"
            "int dispatch(send_fn send, int value) { return send(value); }\n",
        )
        _write(
            root / "src/providers/memory.c",
            "int memory_send(int value) { return value; }\n",
        )
        _write(
            root / "src/providers/tcp.c",
            "int tcp_send(int value) { return value; }\n",
        )
        (root / "Makefile").write_text(
            "all:\n\tcc src/core.c src/providers/*.c\n",
            encoding="utf-8",
        )
        modules = {
            "module.core": "src/core.c",
            "module.provider-memory": "src/providers/memory.c",
            "module.provider-tcp": "src/providers/tcp.c",
        }
    return root, modules


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _save_knowledge(
    root: Path,
    language: str,
    module_sources: dict[str, str],
) -> KnowledgeStore:
    revision = repository_revision(root)
    common = {
        "schema_version": 1,
        "analysis_run_id": f"acceptance-{language}",
        "repository_revision": revision,
    }
    readme = _source("README.md")
    records: list[dict[str, object]] = [
        {
            **common,
            "record_type": "knowledge_manifest",
            "id": "knowledge.manifest",
            "repository_name": f"{language}-acceptance",
            "scope_path": ".",
            "status": "validated",
            "entity_count": len(module_sources) + 1,
            "relationship_count": 0,
            "flow_count": 0,
            "diagnostic_count": 0,
            "attributes": {
                "inventory": {
                    "languages": [
                        {
                            "name": language,
                            "evidence_paths": list(module_sources.values()),
                        }
                    ],
                    "excluded_regions": [],
                },
                "module_catalog": {
                    "major_module_ids": list(module_sources),
                },
            },
        },
        {
            **common,
            "record_type": "entity",
            "id": "repository.root",
            "kind": "repository",
            "name": f"{language}-acceptance",
            "summary": "Cross-language acceptance repository.",
            "source_refs": [readme],
            "confidence": "verified",
        },
    ]
    records.extend(
        {
            **common,
            "record_type": "entity",
            "id": module_id,
            "kind": "module",
            "name": module_id,
            "summary": f"Owns {path} behavior.",
            "parent_id": "repository.root",
            "source_refs": [_source(path)],
            "confidence": "high",
        }
        for module_id, path in module_sources.items()
    )
    store = KnowledgeStore(root)
    store.save_knowledge(records)
    return store


def _architecture_course(
    root: Path, language: str, module_ids: tuple[str, ...]
) -> list[dict[str, object]]:
    revision = repository_revision(root)
    common = {
        "schema_version": 1,
        "analysis_run_id": f"acceptance-{language}",
        "repository_revision": revision,
    }
    document_id = "course.architecture.repository.root"
    return [
        {
            **common,
            "record_type": "document",
            "id": document_id,
            "title": "Repository Architecture",
            "course_mode": "architecture",
            "scope_id": "repository.root",
            "status": "ready",
        },
        {
            **common,
            "record_type": "section",
            "id": f"{document_id}.components",
            "parent_id": document_id,
            "heading_level": 2,
            "order": 1,
            "title": "Components",
            "body": "```mermaid\nflowchart LR\n  Entry --> Core\n```",
            "detail_level": "architecture",
            "previous_section_id": None,
            "next_section_id": f"{document_id}.sequence",
            "return_section_id": None,
            "deep_dive_ids": [f"course.module.{item}" for item in module_ids],
            "knowledge_entity_ids": ["repository.root", *module_ids],
            "relationship_ids": [],
            "runtime_flow_ids": [],
            "diagnostic_ids": [],
            "related_module_ids": list(module_ids),
            "related_symbol_ids": [],
            "prerequisite_section_ids": [],
            "source_refs": [_source("README.md")],
            "confidence": "high",
            "diagrams": [
                {
                    "id": "diagram.components",
                    "type": "flowchart",
                    "question": "How are the repository components connected?",
                }
            ],
        },
        {
            **common,
            "record_type": "section",
            "id": f"{document_id}.sequence",
            "parent_id": document_id,
            "heading_level": 2,
            "order": 2,
            "title": "Runtime Sequence",
            "body": (
                "```mermaid\nsequenceDiagram\n"
                "  User->>Entry: request\n  Entry->>Core: dispatch\n```"
            ),
            "detail_level": "architecture",
            "previous_section_id": f"{document_id}.components",
            "next_section_id": None,
            "return_section_id": None,
            "deep_dive_ids": [],
            "knowledge_entity_ids": ["repository.root", *module_ids],
            "relationship_ids": [],
            "runtime_flow_ids": [],
            "diagnostic_ids": [],
            "related_module_ids": list(module_ids),
            "related_symbol_ids": [],
            "prerequisite_section_ids": [f"{document_id}.components"],
            "source_refs": [_source("README.md")],
            "confidence": "high",
            "diagrams": [
                {
                    "id": "diagram.sequence",
                    "type": "sequenceDiagram",
                    "question": "How does a request cross the repository?",
                }
            ],
        },
    ]


def _source(path: str) -> dict[str, object]:
    return {
        "path": path,
        "start_line": 1,
        "end_line": 1,
        "reason": "Acceptance fixture evidence.",
    }


def _source_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".electroboy" not in path.parts
    }
