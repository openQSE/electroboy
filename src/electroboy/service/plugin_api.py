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
    CliCommandDefinition,
    DocumentSchemaDefinition,
    RouteDefinition,
    RouteHandler,
    RuntimeRoleDefinition,
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
    "CliCommandDefinition",
    "ContextServices",
    "DocumentSchemaDefinition",
    "HtmlResponse",
    "JsonResponse",
    "ProjectFileServices",
    "RouteDefinition",
    "RouteHandler",
    "RouteRequest",
    "RuntimeRoleDefinition",
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
