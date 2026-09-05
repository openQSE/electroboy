from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from electroboy.workflows.code_learner.course_builder import CourseBuildResult
from electroboy.workflows.code_learner.domain import (
    CodeLearnerError,
    repository_revision,
)
from electroboy.workflows.code_learner.initialization import (
    InitializationLease,
    InitializationPipeline,
    initialization_ready,
    mark_pipeline_activated,
)
from electroboy.workflows.code_learner.knowledge_store import KnowledgeStore
from electroboy.workflows.code_learner.progress import (
    AgentActivityReporter,
    InvocationHeartbeat,
)


class FakeAnalysis:
    def __init__(self, root: Path) -> None:
        self.root = root

    def run(self, progress_callback=None):
        store = KnowledgeStore(self.root)
        if not store.load_knowledge(validate_sources=False):
            store.save_knowledge(_knowledge(self.root))
        store.save_checkpoint(
            {
                "schema_version": 1,
                "analysis_run_id": "run-init",
                "repository_revision": repository_revision(self.root),
                "status": "validated",
                "passes": {
                    "inventory": {"status": "completed"},
                    "modules": {"status": "completed"},
                },
            }
        )
        if progress_callback:
            progress_callback(
                {
                    "phase": "modules",
                    "percent": 24,
                    "message": "Module catalog complete.",
                    "scope_ids": ["module.app", "module.extra"],
                }
            )
        return store.load_knowledge()


class FakeEnrichment:
    def __init__(self, _root: Path) -> None:
        pass

    def run(self, progress_callback=None):
        if progress_callback:
            progress_callback(
                {
                    "phase": "knowledge_enrichment",
                    "percent": 90,
                    "message": "No blocking gaps remain.",
                }
            )
        return SimpleNamespace(complete=True)


class FakeSelector:
    def module_ids(self) -> tuple[str, ...]:
        return ("module.app", "module.extra")


class FakeCourses:
    instances: list[FakeCourses] = []
    fail: set[str] = set()

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = KnowledgeStore(root)
        self.selector = FakeSelector()
        self.built: list[str] = []
        self.instances.append(self)

    def build_architecture(self, *, progress_callback=None) -> CourseBuildResult:
        self.built.append("architecture:repository.root")
        if progress_callback:
            progress_callback(
                {
                    "phase": "architecture_course",
                    "percent": 94,
                    "message": "Building Architecture course.",
                    "scope_ids": ["repository.root"],
                }
            )
        return _save_course(self.root, "architecture", "repository.root")

    def build_module(
        self, module_id: str, *, progress_callback=None
    ) -> CourseBuildResult:
        self.built.append(f"module:{module_id}")
        if module_id in self.fail:
            raise CodeLearnerError(f"failed {module_id}")
        if progress_callback:
            progress_callback(
                {
                    "phase": "module_course",
                    "percent": 94,
                    "message": f"Building {module_id}.",
                    "scope_ids": [module_id],
                }
            )
        return _save_course(self.root, "module", module_id)


def _knowledge(root: Path) -> list[dict[str, object]]:
    revision = repository_revision(root)
    common = {
        "schema_version": 1,
        "analysis_run_id": "run-init",
        "repository_revision": revision,
    }
    source = {
        "path": "README.md",
        "start_line": 1,
        "end_line": 1,
        "reason": "Initialization fixture.",
    }
    return [
        {
            **common,
            "record_type": "knowledge_manifest",
            "id": "knowledge.manifest",
            "repository_name": "Init",
            "scope_path": ".",
            "status": "validated",
            "entity_count": 3,
            "relationship_count": 2,
            "flow_count": 0,
            "diagnostic_count": 0,
            "attributes": {
                "module_catalog": {
                    "major_module_ids": ["module.app", "module.extra"]
                }
            },
        },
        {
            **common,
            "record_type": "entity",
            "id": "repository.root",
            "kind": "repository",
            "name": "Init",
            "summary": "Initialization fixture.",
            "source_refs": [source],
            "confidence": "high",
        },
        *[
            {
                **common,
                "record_type": "entity",
                "id": module_id,
                "kind": "module",
                "name": module_id,
                "summary": f"{module_id} fixture.",
                "parent_id": "repository.root",
                "source_refs": [source],
                "confidence": "high",
            }
            for module_id in ("module.app", "module.extra")
        ],
        *[
            {
                **common,
                "record_type": "relationship",
                "id": f"relationship.contains-{module_id}",
                "kind": "contains",
                "from_id": "repository.root",
                "to_id": module_id,
                "summary": f"Repository contains {module_id}.",
                "source_refs": [source],
                "confidence": "high",
            }
            for module_id in ("module.app", "module.extra")
        ],
    ]


def _save_course(root: Path, mode: str, scope_id: str) -> CourseBuildResult:
    store = KnowledgeStore(root)
    revision = repository_revision(root)
    document_id = (
        "course.architecture.repository.root"
        if mode == "architecture"
        else f"course.module.{scope_id}"
    )
    entity_id = "repository.root" if mode == "architecture" else scope_id
    records = [
        {
            "schema_version": 1,
            "analysis_run_id": "run-init",
            "repository_revision": revision,
            "record_type": "document",
            "id": document_id,
            "title": f"{mode} course",
            "course_mode": mode,
            "scope_id": scope_id,
            "status": "ready",
        },
        {
            "schema_version": 1,
            "analysis_run_id": "run-init",
            "repository_revision": revision,
            "record_type": "section",
            "id": f"{document_id}.overview",
            "parent_id": document_id,
            "heading_level": 2,
            "order": 1,
            "title": "Overview",
            "body": "Evidence-grounded course material.",
            "detail_level": mode,
            "previous_section_id": None,
            "next_section_id": None,
            "return_section_id": None,
            "deep_dive_ids": [],
            "knowledge_entity_ids": [entity_id],
            "relationship_ids": [],
            "runtime_flow_ids": [],
            "diagnostic_ids": [],
            "related_module_ids": (
                [scope_id] if mode == "module" else ["module.app", "module.extra"]
            ),
            "related_symbol_ids": [],
            "prerequisite_section_ids": [],
            "source_refs": [
                {
                    "path": "README.md",
                    "start_line": 1,
                    "end_line": 1,
                    "reason": "Initialization fixture.",
                }
            ],
            "confidence": "high",
            "diagrams": [],
        },
    ]
    path = store.save_course(mode, scope_id, records)
    markdown = store.course_markdown_path(mode, scope_id)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text("# Course\n", encoding="utf-8")
    store.record_course_status(
        mode,
        scope_id,
        "ready",
        path=path.relative_to(root).as_posix(),
    )
    return CourseBuildResult(
        mode,
        scope_id,
        path.relative_to(root).as_posix(),
        markdown.relative_to(root).as_posix(),
        len(records),
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# Init\n", encoding="utf-8")
    FakeCourses.instances.clear()
    FakeCourses.fail = set()
    return tmp_path


def _pipeline(root: Path) -> InitializationPipeline:
    return InitializationPipeline(
        root,
        analysis_factory=FakeAnalysis,
        enrichment_factory=FakeEnrichment,
        course_factory=FakeCourses,
    )


def test_pipeline_reports_counts_jobs_and_reserves_100_for_host(
    repository: Path,
) -> None:
    events: list[dict[str, object]] = []

    result = _pipeline(repository).run(events.append)

    assert result.revision == repository_revision(repository)
    assert len(result.modules) == 2
    assert max(int(event["percent"]) for event in events) == 99
    assert any(event["record_counts"].get("entity") == 3 for event in events)
    assert any(event["scope_ids"] for event in events)
    assert any(
        event["completed_analysis_scopes"]
        == ["inventory:all", "modules:all"]
        for event in events
    )
    assert events[-1]["completed_module_courses"] == [
        "module.app",
        "module.extra",
    ]
    checkpoint = KnowledgeStore(repository).load_checkpoint()
    assert checkpoint["pipeline_status"] == "ready_for_activation"
    mark_pipeline_activated(repository)
    assert initialization_ready(repository)


def test_pipeline_resumes_completed_courses_after_partial_failure(
    repository: Path,
) -> None:
    FakeCourses.fail = {"module.extra"}
    with pytest.raises(CodeLearnerError, match="module.extra"):
        _pipeline(repository).run()
    first = FakeCourses.instances[-1]
    assert "module:module.app" in first.built

    FakeCourses.fail = set()
    _pipeline(repository).run()
    resumed = FakeCourses.instances[-1]

    assert "architecture:repository.root" not in resumed.built
    assert "module:module.app" not in resumed.built
    assert resumed.built == ["module:module.extra"]


def test_pipeline_resumes_at_missing_render_without_repeating_ai_course(
    repository: Path,
) -> None:
    _pipeline(repository).run()
    markdown = KnowledgeStore(repository).course_markdown_path(
        "module", "module.app"
    )
    markdown.unlink()

    _pipeline(repository).run()
    resumed = FakeCourses.instances[-1]

    assert markdown.is_file()
    assert resumed.built == []


def test_initialization_lease_rejects_conflicting_process_job(
    repository: Path,
) -> None:
    first = InitializationLease.acquire(
        repository, "job-1", repository_revision="revision-1"
    )
    try:
        owner = json.loads(first.path.read_text(encoding="utf-8"))
        assert owner["repository_revision"] == "revision-1"
        with pytest.raises(CodeLearnerError, match="already running"):
            InitializationLease.acquire(
                repository, "job-2", repository_revision="revision-1"
            )
    finally:
        first.release()
    second = InitializationLease.acquire(repository, "job-3")
    second.release()


def test_invocation_heartbeat_repeats_bounded_progress() -> None:
    events: list[dict[str, object]] = []
    with InvocationHeartbeat(
        events.append,
        {"phase": "symbols", "percent": 74, "message": "Still indexing."},
        interval=0.01,
    ):
        time.sleep(0.035)

    assert len(events) >= 2
    assert all(event["heartbeat"] is True for event in events)
    assert all(event["percent"] == 74 for event in events)


def test_agent_activity_reporter_projects_reasoning_and_command_output() -> None:
    events: list[dict[str, object]] = []
    reporter = AgentActivityReporter(
        events.append,
        phase="inventory",
        percent=8,
        scope_ids=["repository.root"],
    )

    reporter(
        {
            "stream": "stdout",
            "event": {
                "type": "item.completed",
                "item": {"type": "reasoning", "text": "Mapping entry points."},
            },
        }
    )
    reporter(
        {
            "stream": "stdout",
            "event": {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "rg --files",
                    "exit_code": 0,
                    "aggregated_output": "README.md\nsrc/app.py\n",
                },
            },
        }
    )

    assert events[0]["activity"] is True
    assert events[0]["activity_kind"] == "reasoning"
    assert events[0]["message"] == "AI reasoning: Mapping entry points."
    assert events[1]["activity_kind"] == "command"
    assert "rg --files" in str(events[1]["message"])
    assert "src/app.py" in str(events[1]["message"])


def test_agent_activity_reporter_summarizes_structured_final_output() -> None:
    events: list[dict[str, object]] = []
    reporter = AgentActivityReporter(events.append, phase="modules", percent=24)

    reporter(
        {
            "stream": "stdout",
            "event": {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": '{"record_type":"entity"}'},
            },
        }
    )

    assert events[0]["message"] == "AI returned structured output (24 characters)."


def test_pipeline_preserves_agent_activity_metadata(repository: Path) -> None:
    events: list[dict[str, object]] = []
    activity = {
        "record_type": "activity",
        "activity": True,
        "activity_kind": "reasoning",
        "phase": "inventory",
        "percent": 8,
        "message": "AI reasoning: Mapping repository entry points.",
    }

    _pipeline(repository)._forward(activity, events.append)

    assert events == [activity]
