from __future__ import annotations

import pytest

from electroboy.adapters.base import AgentResult
from electroboy.workflows.code_learner.agent_retry import (
    RetryableAgentError,
    parse_agent_jsonl,
    require_agent_output,
)
from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.phase3_contracts import (
    Phase3ContractError,
    parse_phase3_jsonl,
)


@pytest.mark.parametrize(
    "result",
    [
        AgentResult(False, "partial", error="process timed out"),
        AgentResult(False, "partial", error="process was interrupted"),
        AgentResult(False, "partial", error="output was truncated"),
        AgentResult(True, ""),
    ],
)
def test_retryable_runtime_and_empty_output_are_classified(result: AgentResult) -> None:
    with pytest.raises(RetryableAgentError):
        require_agent_output(result, operation="Fixture")


def test_unclassified_runtime_failure_is_not_retryable() -> None:
    result = AgentResult(False, "failure", error="permission denied")

    with pytest.raises(CodeLearnerError, match="permission denied") as captured:
        require_agent_output(result, operation="Fixture")

    assert not isinstance(captured.value, RetryableAgentError)


def test_malformed_json_is_retryable() -> None:
    with pytest.raises(RetryableAgentError):
        parse_agent_jsonl(
            '{"id":"unfinished"',
            artifact="Fixture",
            parser=parse_phase3_jsonl,
        )


def test_structurally_invalid_json_is_not_retryable() -> None:
    with pytest.raises(Phase3ContractError) as captured:
        parse_agent_jsonl(
            '["not", "an", "object"]',
            artifact="Fixture",
            parser=parse_phase3_jsonl,
        )

    assert not isinstance(captured.value, RetryableAgentError)
