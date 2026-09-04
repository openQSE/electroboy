from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.service.app import pane_window_html  # noqa: E402
from electroboy.service.frontend import read_service_text_asset  # noqa: E402
from electroboy.service.registry import (  # noqa: E402
    build_module_registry,
    build_workflow_registry,
)
from electroboy.workflows.code_learner.plugin import (  # noqa: E402
    workflow as code_learner_workflow,
)


def test_code_learner_frontend_registers_workflow_and_pane_renderer() -> None:
    modules = build_module_registry()
    workflows = build_workflow_registry(modules, (code_learner_workflow(),))
    frontend = read_service_text_asset(
        "js/workflows/code-learner.js",
        modules,
        workflows,
    )
    stylesheet = read_service_text_asset(
        "css/workflows/code-learner.css",
        modules,
        workflows,
    )

    assert 'id: WORKFLOW_ID' in frontend
    assert 'navigation: "sidebar"' in frontend
    assert 'kind: "code-learner"' in frontend
    assert "window.ElectroBoyCodeLearnerPane" in frontend
    assert "electroboy-code-learner-context" in frontend
    assert "electroboy-code-learner-question" in frontend
    assert "preparePrompt" in frontend
    assert 'contextUrl("/api/code-learner/walkthrough")' in frontend
    assert ".code-learner-pane-grid" in stylesheet
    assert ".tok-keyword" in stylesheet


def test_pane_window_loads_installed_workflow_assets_for_code_learner() -> None:
    modules = build_module_registry()
    workflows = build_workflow_registry(modules, (code_learner_workflow(),))

    page = pane_window_html("code-learner", workflows)

    assert "__ELECTROBOY_CONTRIBUTION" not in page
    assert "/assets/service/js/core/registry.js" in page
    assert "/assets/service/js/workflows/code-learner.js" in page
    assert "/assets/service/css/workflows/code-learner.css" in page
    assert "window.ElectroBoyCodeLearnerPane.mount" in page
    assert 'if (kind === "code-learner") return "Code Learner";' in page


def test_runtime_and_software_frontend_route_code_learner_as_separate_pane() -> None:
    modules = build_module_registry()
    workflows = build_workflow_registry(modules)
    runtime = read_service_text_asset("js/core/runtime.js")
    software = read_service_text_asset(
        "js/workflows/software.js",
        modules,
        workflows,
    )

    assert '"code-learner": { label: "Code Learner", element: null }' in runtime
    assert '"code-learner",' in runtime
    assert (
        'project.kind === "project" || project.kind === "meta"'
        in software
    )
