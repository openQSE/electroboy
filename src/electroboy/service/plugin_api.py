"""Stable route and service interfaces for ElectroBoy plugins."""

from .agenda import (
    AgendaProvider,
    AgendaWorkflowController,
    normalize_agenda_snapshot,
)
from .corkboard import (
    CorkboardProvider,
    CorkboardWorkflowController,
    normalize_board_snapshot,
)
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
    "AgendaProvider",
    "AgendaWorkflowController",
    "BinaryResponse",
    "CliCommandDefinition",
    "ContextServices",
    "CorkboardProvider",
    "CorkboardWorkflowController",
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
    "normalize_agenda_snapshot",
    "normalize_board_snapshot",
]
