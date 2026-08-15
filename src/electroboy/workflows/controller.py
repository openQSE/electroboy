"""Shared workflow-controller runtime adapter."""

from __future__ import annotations

from typing import Any


class BoundWorkflowController:
    """Base class for workflow behavior bound to the service runtime.

    Controllers own workflow policy while delegating generic context, session,
    and persistence primitives to the service runtime.
    """

    workflow_id = ""

    def __init__(self, runtime: object) -> None:
        self._runtime = runtime

    def __getattr__(self, name: str) -> Any:
        return getattr(self._runtime, name)
