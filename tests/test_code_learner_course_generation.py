from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from electroboy.adapters.base import AgentInvocation, AgentResult
from electroboy.workflows.code_learner.course_generation import (
    CourseGenerationService,
)
from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.store import LearnerStore


class DirectWriteRuntime:
    def __init__(self, root: Path, *, fail: bool = False) -> None:
        self.root = root
        self.fail = fail
        self.invocations: list[AgentInvocation] = []

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        self.invocations.append(invocation)
        if self.fail:
            return AgentResult(False, "failed", error="runtime failed")
        store = LearnerStore(self.root)
        invocation_id = re.search(
            r"Your unique invocation UUID is:\n([^\n]+)", invocation.prompt
        ).group(1)
        store.raw_knowledge_root.joinpath(f"notes-{invocation_id}.md").write_text(
            "# Accumulated knowledge\n",
            encoding="utf-8",
        )
        if "Write the component array directly" in invocation.prompt:
            store.components_path.write_text(
                json.dumps(
                    [
                        {
                            "eb_comp_id": "comp-001",
                            "ai_component_name": "Core",
                            "ai_file_list": ["core.py"],
                        }
                    ]
                ),
                encoding="utf-8",
            )
        elif "Write the module array directly" in invocation.prompt:
            store.modules_path.write_text(
                json.dumps(
                    [
                        {
                            "eb_module_id": "mod-001",
                            "ai_module_name": "Core module",
                            "ai_comp_list": ["comp-001"],
                        }
                    ]
                ),
                encoding="utf-8",
            )
        else:
            _write_architecture(store)
        return AgentResult(
            True,
            "complete",
            provider="codex",
            provider_session_id="primary-session",
        )


def _write_architecture(store: LearnerStore) -> None:
    concept = store.architecture_root / "01.System"
    concept.mkdir(parents=True, exist_ok=True)
    store.course_index_path("architecture").write_text(
        json.dumps(
            {
                "course_type": "architecture",
                "course_title": "Architecture",
                "concepts": [
                    {
                        "directory_name": "01.System",
                        "concept_title": "System",
                        "lessons": [
                            {
                                "file_name": "01.Overview.jsonl",
                                "lesson_title": "Overview",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (concept / "01.Overview.jsonl").write_text(
        json.dumps(
            {
                "record_type": "document",
                "id": "architecture-overview",
                "title": "Overview",
            }
        )
        + "\n"
        + json.dumps(
            {
                "record_type": "section",
                "id": "architecture-overview-purpose",
                "parent_id": "architecture-overview",
                "order": 10,
                "title": "Purpose",
                "body": "Architecture details.",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_initialization_uses_three_turns_and_resumes_primary_session(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    runtime = DirectWriteRuntime(root)
    service = CourseGenerationService(
        root, runtime_factory=lambda _role, _root: runtime
    )

    result = service.run()

    assert result.status == "complete"
    assert len(runtime.invocations) == 3
    assert runtime.invocations[0].provider_session_id is None
    assert runtime.invocations[1].provider_session_id == "primary-session"
    assert runtime.invocations[2].provider_session_id == "primary-session"
    prompts = [invocation.prompt for invocation in runtime.invocations]
    invocation_ids = {
        re.search(r"Your unique invocation UUID is:\n([^\n]+)", prompt).group(1)
        for prompt in prompts
    }
    assert len(invocation_ids) == 3
    assert len(list(LearnerStore(root).raw_knowledge_root.glob("*.md"))) == 3
    assert LearnerStore(root).load_status()["status"] == "initialized"


def test_continue_skips_ai_outputs_already_written(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    store = LearnerStore(root)
    store.initialize_layout()
    store.components_path.write_text("[]", encoding="utf-8")
    store.modules_path.write_text("[]", encoding="utf-8")
    runtime = DirectWriteRuntime(root)

    CourseGenerationService(
        root, runtime_factory=lambda _role, _root: runtime
    ).run()

    assert len(runtime.invocations) == 1
    assert "Architecture course" in runtime.invocations[0].prompt


def test_operational_ai_failure_is_not_retried(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    runtime = DirectWriteRuntime(root, fail=True)

    with pytest.raises(CodeLearnerError, match="runtime failed"):
        CourseGenerationService(
            root, runtime_factory=lambda _role, _root: runtime
        ).run()

    assert len(runtime.invocations) == 1
