from __future__ import annotations

from pathlib import Path

from electroboy.adapters.base import AgentInvocation, AgentResult
from electroboy.workflows.code_learner.agent_sessions import (
    AgentSessionRegistry,
    ReusableAgentRuntime,
)


class RecordingRuntime:
    def __init__(self, session_ids: list[str]) -> None:
        self.session_ids = session_ids
        self.invocations: list[AgentInvocation] = []

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        self.invocations.append(invocation)
        return AgentResult(
            True,
            "ok",
            provider="codex",
            provider_session_id=self.session_ids.pop(0),
        )


def test_primary_session_is_persisted_and_resumed(tmp_path: Path) -> None:
    registry = AgentSessionRegistry(tmp_path)
    registry.prepare("revision-1")
    runtime = RecordingRuntime(["primary-id", "primary-id"])
    reusable = ReusableAgentRuntime(runtime, registry, slot="primary")

    reusable.invoke(AgentInvocation(role="analysis", prompt="first"))
    reusable.invoke(AgentInvocation(role="analysis", prompt="second"))

    assert runtime.invocations[0].provider_session_id is None
    assert runtime.invocations[1].provider_session_id == "primary-id"
    assert AgentSessionRegistry(tmp_path).session_id("primary") == "primary-id"


def test_worker_session_forks_once_then_resumes_its_own_session(
    tmp_path: Path,
) -> None:
    registry = AgentSessionRegistry(tmp_path)
    registry.prepare("revision-1")
    primary_runtime = RecordingRuntime(["primary-id"])
    ReusableAgentRuntime(primary_runtime, registry, slot="primary").invoke(
        AgentInvocation(role="analysis", prompt="discover")
    )
    worker_runtime = RecordingRuntime(["worker-id", "worker-id"])
    worker = ReusableAgentRuntime(
        worker_runtime,
        registry,
        slot="worker:0",
        fork_from_slot="primary",
    )

    worker.invoke(AgentInvocation(role="course", prompt="first module"))
    worker.invoke(AgentInvocation(role="course", prompt="second module"))

    assert worker_runtime.invocations[0].fork_provider_session_id == "primary-id"
    assert worker_runtime.invocations[0].provider_session_id is None
    assert worker_runtime.invocations[1].provider_session_id == "worker-id"
    assert worker_runtime.invocations[1].fork_provider_session_id is None


def test_new_revision_discards_stale_session_slots(tmp_path: Path) -> None:
    registry = AgentSessionRegistry(tmp_path)
    registry.prepare("revision-1")
    runtime = RecordingRuntime(["primary-id"])
    ReusableAgentRuntime(runtime, registry, slot="primary").invoke(
        AgentInvocation(role="analysis", prompt="discover")
    )

    registry.prepare("revision-2")

    assert registry.session_id("primary") == ""
    assert registry.snapshot()["repository_identity"] == "revision-2"
