"""Creative-writing workflow definition."""

from __future__ import annotations

from electroboy.service.registry import (
    CliCommandDefinition,
    DocumentSchemaDefinition,
    RuntimeRoleDefinition,
    WorkflowDefinition,
    WorkflowStage,
)
from electroboy.workflows.creative_writing.controller import (
    CreativeWritingWorkflowController,
)
from electroboy.workflows.creative_writing.routes import HANDLERS, ROUTES


def workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        id="creative-writing",
        label="Creative Writing",
        modules=(
            "core",
            "agent_sessions",
            "markdown_documents",
            "binder",
            "corkboard",
            "project_shell",
            "file_browser",
            "recent_projects",
            "mind_map",
        ),
        stages=(
            WorkflowStage(
                "project",
                "Project",
                None,
                actions=("open", "new", "close"),
                next_stage="binder",
            ),
            WorkflowStage(
                "binder",
                "Binder",
                None,
                actions=("new-folder", "new-document", "refresh"),
            ),
        ),
        project_kinds=("creative-writing",),
        backend_package="electroboy.workflows.creative_writing",
        frontend_bundle="workflows/creative-writing.js",
        frontend_stylesheets=("css/workflows/creative-writing.css",),
        asset_package="electroboy.workflows.creative_writing",
        controller_factory=CreativeWritingWorkflowController,
        routes=ROUTES,
        handlers=HANDLERS,
        commands=(
            CliCommandDefinition("creative-open", "Open writing project"),
            CliCommandDefinition("creative-new", "Create writing project"),
        ),
        document_schemas=(
            DocumentSchemaDefinition(
                "creative-markdown",
                "Creative Markdown",
                source_format="markdown",
            ),
        ),
        runtime_roles=(
            RuntimeRoleDefinition(
                "writing-partner",
                "Writing Partner",
                interactive=True,
                mutating=True,
            ),
        ),
    )
