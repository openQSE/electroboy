"""Stable route and service interfaces for ElectroBoy plugins."""

from .http import (
    BinaryResponse,
    HtmlResponse,
    JsonResponse,
    ServiceResponse,
    StreamResponse,
    TextResponse,
)
from .registry import (
    RouteDefinition,
    RouteHandler,
    ServiceModule,
    WorkflowController,
    WorkflowDefinition,
    WorkflowStage,
)
from .routes import RouteRequest
from .services import (
    ContextServices,
    ProjectFileServices,
    ServiceServices,
    SessionServices,
    WorkflowServices,
)

__all__ = [
    "BinaryResponse",
    "ContextServices",
    "HtmlResponse",
    "JsonResponse",
    "ProjectFileServices",
    "RouteDefinition",
    "RouteHandler",
    "RouteRequest",
    "ServiceModule",
    "ServiceResponse",
    "ServiceServices",
    "SessionServices",
    "StreamResponse",
    "TextResponse",
    "WorkflowController",
    "WorkflowDefinition",
    "WorkflowServices",
    "WorkflowStage",
]
