"""Explicit retry boundaries for Code Learner AI invocations."""

from __future__ import annotations

from collections.abc import Callable

from electroboy.adapters.base import AgentResult

from .contracts import ContractError
from .domain import CodeLearnerError
from .phase3_contracts import Phase3ContractError

Record = dict[str, object]
ContractException = Phase3ContractError | ContractError

_RETRYABLE_RUNTIME_MARKERS = (
    "timeout",
    "timed out",
    "interrupted",
    "truncated",
    "unexpected eof",
    "unexpected end of file",
    "unexpected end of input",
)


class RetryableAgentError(CodeLearnerError):
    """An operational or syntactic AI failure that permits another invocation."""


def require_agent_output(result: AgentResult, *, operation: str) -> str:
    """Return usable output or classify the invocation failure."""

    output = result.final_message or ""
    if not output.strip():
        detail = str(result.error or "").strip()
        suffix = f": {detail}" if detail else ""
        raise RetryableAgentError(f"{operation} returned empty output{suffix}")
    if result.ok:
        return output

    detail = str(result.error or output or f"{operation} runtime failed").strip()
    if _has_retryable_runtime_marker(detail):
        raise RetryableAgentError(detail)
    raise CodeLearnerError(detail)


def parse_agent_jsonl(
    text: str,
    *,
    artifact: str,
    parser: Callable[..., list[Record]],
) -> list[Record]:
    """Retry malformed JSON, while preserving structural failures as semantic."""

    try:
        return parser(text, artifact=artifact)
    except (Phase3ContractError, ContractError) as error:
        if _is_malformed_json(error):
            raise RetryableAgentError(str(error)) from error
        raise


def _has_retryable_runtime_marker(message: str) -> bool:
    normalized = " ".join(message.lower().split())
    return any(marker in normalized for marker in _RETRYABLE_RUNTIME_MARKERS)


def _is_malformed_json(error: ContractException) -> bool:
    return bool(error.issues) and all(
        str(issue.path).startswith("line[")
        and str(issue.message) != "record must be an object"
        for issue in error.issues
    )
