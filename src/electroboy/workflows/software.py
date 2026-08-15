"""Software-engineering workflow definition."""

from __future__ import annotations

from electroboy.service.registry import WorkflowDefinition, WorkflowStage
from electroboy.workflows.software_controller import SoftwareWorkflowController


def workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        id="software",
        label="Software Engineering",
        modules=(
            "core",
            "agent_sessions",
            "structured_documents",
            "markdown_documents",
            "progress",
            "project_shell",
            "file_browser",
            "review_reports",
            "recent_projects",
        ),
        stages=(
            WorkflowStage("project", "Project", None, next_stage="requirements"),
            WorkflowStage(
                "requirements",
                "Requirements",
                "electroboy requirements",
                documents=("requirements",),
                actions=("start", "approve", "set-stage"),
                next_stage="design",
            ),
            WorkflowStage(
                "design",
                "Design",
                "electroboy design",
                documents=("detailed-design",),
                actions=("start", "set-stage"),
                next_stage="design-review",
            ),
            WorkflowStage(
                "design-review",
                "Design Review",
                "electroboy design-review",
                documents=("detailed-design", "design-review"),
                actions=("start", "approve", "set-stage"),
                next_stage="implementation-plan",
            ),
            WorkflowStage(
                "implementation-plan",
                "Implementation Plan",
                "electroboy implementation-plan",
                documents=("implementation-plan",),
                actions=("start", "approve", "set-stage"),
                next_stage="code",
            ),
            WorkflowStage(
                "code",
                "Code",
                "electroboy code",
                documents=("implementation-report",),
                actions=("start", "review", "approve", "set-stage"),
                next_stage="test-plan",
            ),
            WorkflowStage(
                "test-plan",
                "Test Plan",
                "electroboy test-plan",
                documents=("test-plan",),
                actions=("start", "approve", "set-stage"),
                next_stage="validate",
            ),
            WorkflowStage(
                "validate",
                "Validate",
                "electroboy validate",
                documents=("validation-report",),
                actions=("start", "approve", "set-stage"),
                next_stage="document",
            ),
            WorkflowStage(
                "document",
                "Document",
                "electroboy document",
                actions=("start", "set-stage"),
            ),
        ),
        project_kinds=("project", "meta-project"),
        backend_package="electroboy.workflows.software",
        frontend_bundle="workflows/software.js",
        controller_factory=SoftwareWorkflowController,
    )
