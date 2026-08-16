"""Shared workflow-controller runtime adapter."""

from __future__ import annotations

from .services import ServiceServices


class BoundWorkflowController:
    """Base class for workflow behavior bound to the service runtime.

    Controllers own workflow policy while delegating generic context, session,
    and persistence primitives to the service runtime.
    """

    workflow_id = ""

    def __init__(self, services: ServiceServices) -> None:
        self.services = services
