"""Software-engineering workflow package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from electroboy.service.registry import WorkflowDefinition


def workflow() -> WorkflowDefinition:
    """Load the software workflow factory without eager controller imports."""

    from .plugin import workflow as factory

    return factory()


__all__ = ["workflow"]
