"""Software-engineering workflow definition."""

from __future__ import annotations

from electroboy.service.registry import (
    CliCommandDefinition,
    DocumentSchemaDefinition,
    RuntimeRoleDefinition,
    WorkflowDefinition,
    WorkflowStage,
)
from electroboy.workflows.software.agent_rules import SOFTWARE_AGENT_RULES
from electroboy.workflows.software.controller import SoftwareWorkflowController
from electroboy.workflows.software.domain import _stage_operations
from electroboy.workflows.software.routes import HANDLERS, ROUTES


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
            "corkboard",
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
            WorkflowStage(
                "corkboard",
                "Corkboard",
                None,
                actions=("open", "new"),
            ),
        ),
        project_kinds=("project", "meta-project"),
        backend_package="electroboy.workflows.software",
        frontend_bundle="workflows/software.js",
        frontend_stylesheets=("css/workflows/software.css",),
        asset_package="electroboy.workflows.software",
        controller_factory=SoftwareWorkflowController,
        stage_operations_factory=_stage_operations,
        routes=ROUTES,
        handlers=HANDLERS,
        commands=tuple(
            CliCommandDefinition(command, f"electroboy {command}")
            for command in (
                "requirements",
                "requirements-approve",
                "design",
                "design-review",
                "design-approve",
                "implementation-plan",
                "plan-approve",
                "code",
                "code-review",
                "code-approve",
                "test-plan",
                "test-plan-approve",
                "validate",
                "validation-approve",
                "document",
            )
        ),
        document_schemas=tuple(
            DocumentSchemaDefinition(schema_id, label)
            for schema_id, label in (
                ("requirements", "Requirements"),
                ("detailed-design", "Detailed Design"),
                ("implementation-plan", "Implementation Plan"),
                ("test-plan", "Test Plan"),
                ("implementation-log", "Implementation Log"),
                ("implementation-report", "Implementation Report"),
                ("validation-report", "Validation Report"),
            )
        ),
        agent_rules=SOFTWARE_AGENT_RULES,
        runtime_roles=(
            RuntimeRoleDefinition(
                "artifact-author",
                "Artifact Author",
                interactive=True,
                mutating=True,
            ),
            RuntimeRoleDefinition("reviewer", "Reviewer"),
            RuntimeRoleDefinition("implementation", "Implementation", mutating=True),
            RuntimeRoleDefinition("validator", "Validator", mutating=True),
        ),
    )
