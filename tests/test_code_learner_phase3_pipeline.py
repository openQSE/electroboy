from __future__ import annotations

import json
from pathlib import Path

import pytest
from code_learner_phase3_fixtures import build_catalog, build_course_records

from electroboy.adapters.base import AgentInvocation, AgentResult
from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.phase3_courses import Phase3CourseService
from electroboy.workflows.code_learner.phase3_pipeline import (
    STAGES,
    Phase3InitializationPipeline,
    _ObservedRuntime,
    phase3_initialization_ready,
)


class _Runtime:
    def __init__(self, result: AgentResult, *, emit: bool = False) -> None:
        self.result = result
        self.emit = emit

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        if self.emit and invocation.event_callback is not None:
            invocation.event_callback(
                {
                    "event": {
                        "type": "item.completed",
                        "item": {"type": "reasoning", "text": "Tracing entry points"},
                    }
                }
            )
        return self.result


def _checkpoint(pipeline: Phase3InitializationPipeline) -> dict[str, object]:
    return pipeline._checkpoint("fixture-revision", "fixture-job")


@pytest.mark.parametrize("stage", STAGES)
def test_every_stage_checkpoints_an_interruption(tmp_path: Path, stage: str) -> None:
    pipeline = Phase3InitializationPipeline(tmp_path, eager_function_budget=0)
    checkpoint = _checkpoint(pipeline)

    with pytest.raises(RuntimeError, match="interrupted"):
        pipeline._run_stage(
            checkpoint,
            stage,
            lambda: (_ for _ in ()).throw(RuntimeError("interrupted")),
            ready=lambda: False,
        )

    saved = pipeline.store.read_json(pipeline.store.checkpoint_path)
    assert saved is not None
    assert saved["stages"][stage]["status"] == "failed"
    assert saved["stages"][stage]["error"] == "interrupted"
    assert saved["stages"][stage]["duration_seconds"] >= 0
    progress = pipeline.store.read_jsonl(pipeline.store.progress_path)
    assert any(
        item.get("activity_kind") == "error"
        and "interrupted" in str(item.get("message"))
        for item in progress
    )
    assert all(int(item.get("percent") or 0) < 100 for item in progress)


def test_warning_tolerant_scope_records_error_and_continues(tmp_path: Path) -> None:
    pipeline = Phase3InitializationPipeline(tmp_path, eager_function_budget=0)
    checkpoint = _checkpoint(pipeline)

    result = pipeline._run_stage(
        checkpoint,
        "relationships",
        lambda: (_ for _ in ()).throw(CodeLearnerError("bad endpoint")),
        ready=lambda: False,
        warning_tolerant=True,
        fallback=lambda: ["preserved"],
    )

    assert result == ["preserved"]
    assert checkpoint["stages"]["relationships"]["status"] == ("complete_with_warnings")
    assert checkpoint["stages"]["relationships"]["duration_seconds"] >= 0
    assert pipeline.store.active_diagnostics("warning")[0]["message"] == (
        "bad endpoint"
    )


def test_observed_runtime_streams_activity_and_rejects_direct_writes() -> None:
    events: list[dict[str, object]] = []
    runtime = _ObservedRuntime(
        _Runtime(
            AgentResult(
                True,
                "{}",
                raw_events=[
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": "rg entry",
                            "exit_code": 0,
                            "aggregated_output": "src/main.py:1",
                        },
                    }
                ],
                changed_files=["src/main.py"],
            ),
            emit=True,
        ),
        events.append,
        stage="components",
        percent=14,
    )

    result = runtime.invoke(AgentInvocation(role="code_learner_analysis", prompt="p"))

    assert result.ok is False
    assert "direct repository/state writes" in str(result.error)
    assert "src/main.py" in str(result.error)
    assert any(item.get("activity_kind") == "reasoning" for item in events)
    assert any(item.get("activity_kind") == "command" for item in events)
    assert all(item.get("percent") == 14 for item in events)


def test_terminal_states_distinguish_clean_warning_and_failure(tmp_path: Path) -> None:
    pipeline, catalog = _ready_pipeline(tmp_path)

    clean = pipeline._activate(catalog.source.revision)
    assert clean["status"] == "complete"
    assert clean["course_active"] is True

    pipeline._warning("module_knowledge", "one module remains incomplete")
    warning = pipeline._activate(catalog.source.revision)
    assert warning["status"] == "complete_with_warnings"
    assert warning["warning_count"] == 1

    pipeline._active_stage = "architecture_knowledge"
    pipeline._fail(catalog.source.revision, CodeLearnerError("no architecture"))
    failed = pipeline.store.load_terminal_result()
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["course_active"] is False
    assert failed["failed_scope"] == "architecture_knowledge"
    assert "no architecture" in failed["recovery_action"]


def test_pipeline_resumes_completed_scopes_without_invoking_ai(tmp_path: Path) -> None:
    pipeline, catalog = _ready_pipeline(tmp_path)
    pipeline.ctags.raw_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline.ctags.raw_path.write_bytes(b"")
    pipeline.ctags.invocation_path.write_text(
        json.dumps(
            {
                "repository_revision": catalog.source.revision,
                "raw_tag_count": 0,
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    checkpoint = pipeline._checkpoint(catalog.source.revision, "first-job")
    for stage in STAGES:
        checkpoint["stages"][stage]["status"] = (
            "pending" if stage == "activation" else "complete"
        )
    pipeline.store.write_json(pipeline.store.checkpoint_path, checkpoint)

    result = pipeline.run(acquire_lease=False)

    assert result.status == "complete"
    assert result.module_course_count == len(catalog.modules.modules)
    assert phase3_initialization_ready(tmp_path)
    resumed = pipeline.store.read_json(pipeline.store.checkpoint_path)
    assert resumed is not None
    assert resumed["status"] == "complete"
    assert resumed["stages"]["activation"]["status"] == "complete"


def test_progress_counts_expose_every_phase3_catalog(tmp_path: Path) -> None:
    pipeline, _catalog = _ready_pipeline(tmp_path)

    counts = pipeline._counts()

    assert set(counts) == {
        "files",
        "raw_tags",
        "candidates",
        "overlap_groups",
        "reconciliations",
        "dispositions",
        "unresolved_files",
        "components",
        "modules",
        "relationships",
        "architecture_knowledge",
        "module_knowledge",
        "function_knowledge",
        "courses",
        "warnings",
    }
    assert counts["files"] == 2
    assert counts["components"] == 2
    assert counts["modules"] == 2
    assert counts["courses"] == 3


def _ready_pipeline(
    root: Path,
) -> tuple[Phase3InitializationPipeline, object]:
    catalog = build_catalog(root)

    def no_ai(_role: str, _root: Path):
        raise AssertionError("completed Phase 3 scopes must not invoke AI")

    pipeline = Phase3InitializationPipeline(
        root,
        runtime_factory=no_ai,
        eager_function_budget=0,
    )
    pipeline.store.write_jsonl(
        pipeline.architecture.path,
        [
            {
                "id": "knowledge:architecture",
                "repository_revision": catalog.source.revision,
            }
        ],
    )
    for module in catalog.modules.modules:
        module_id = str(module["id"])
        pipeline.store.write_jsonl(
            pipeline.module_knowledge._path(module_id),
            [
                {
                    "id": f"knowledge:{module_id}",
                    "repository_revision": catalog.source.revision,
                }
            ],
        )
    course_service = Phase3CourseService(root, store=pipeline.store)
    course_service.save(
        "architecture",
        "architecture:current",
        build_course_records(catalog, "architecture", "architecture:current"),
    )
    for index, module in enumerate(catalog.modules.modules):
        module_id = str(module["id"])
        course_service.save(
            "module",
            module_id,
            build_course_records(catalog, "module", module_id, source_index=index),
        )
    return pipeline, catalog
