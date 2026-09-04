"""Code Learner workflow definition."""

from __future__ import annotations

from electroboy.service.registry import (
    RuntimeRoleDefinition,
    WorkflowDefinition,
    WorkflowStage,
)
from electroboy.workflows.code_learner.controller import (
    CodeLearnerWorkflowController,
)
from electroboy.workflows.code_learner.routes import HANDLERS, ROUTES


def workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        id="code-learner",
        label="Code Learner",
        modules=(
            "core",
            "agent_sessions",
            "file_browser",
            "project_shell",
            "recent_projects",
        ),
        stages=(
            WorkflowStage(
                "project",
                "Project",
                None,
                actions=("open", "close"),
                next_stage="course",
            ),
            WorkflowStage(
                "course",
                "Course",
                None,
                actions=("architecture", "module", "function"),
            ),
        ),
        project_kinds=("code-learner",),
        backend_package="electroboy.workflows.code_learner",
        frontend_bundle="workflows/code-learner.js",
        frontend_stylesheets=("css/workflows/code-learner.css",),
        asset_package="electroboy.workflows.code_learner",
        controller_factory=CodeLearnerWorkflowController,
        routes=ROUTES,
        handlers=HANDLERS,
        runtime_roles=(
            RuntimeRoleDefinition(
                "code-tutor",
                "Code Tutor",
                interactive=True,
            ),
        ),
    )
