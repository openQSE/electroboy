"""Creative-writing workflow definition."""

from __future__ import annotations

from electroboy.service.registry import WorkflowDefinition, WorkflowStage
from electroboy.workflows.creative_writing_controller import (
    CreativeWritingWorkflowController,
)


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
        controller_factory=CreativeWritingWorkflowController,
    )
