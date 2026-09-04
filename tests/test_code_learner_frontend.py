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
    assert "refresh: () => loadPaneState(state)" in frontend
    assert "electroboy-code-learner-context" in frontend
    assert "electroboy-code-learner-question" in frontend
    assert "preparePrompt" in frontend
    assert 'contextUrl("/api/code-learner/walkthrough")' in frontend
    assert 'contextUrl("/api/code-learner/init/status")' in frontend
    assert 'data-code-learner-control="project-menu"' in frontend
    assert 'data-code-learner-control="open-project"' in frontend
    assert (
        'runtime.modules.invoke("file-browser", "openProjectBrowser", "open", true);'
        in frontend
    )
    assert '<span class="stage-action-label">Project</span>' in frontend
    assert '<span class="stage-action-label">Learn</span>' in frontend
    assert '<span class="stage-action-label">Outline</span>' in frontend
    assert 'data-code-learner-control="initialize"' in frontend
    assert 'data-code-learner-control="architecture-menu"' in frontend
    assert 'data-code-learner-control="architecture-start">Start lesson' in frontend
    assert 'generateCourse({ mode: "architecture" })' in frontend
    assert 'data-code-learner-control="init-progress"' in frontend
    assert 'runtimeApi.modules.invoke("progress", "showProgressSnapshot", {' in frontend
    assert 'runtimeApi.modules.invoke("progress", "closeProgressEventStream");' in frontend
    assert "initialization.progress_events" in frontend
    assert "initializationProgressEventText(event)" in frontend
    assert "if (!running)" in frontend
    assert 'data-code-learner-control="module"' in frontend
    assert 'data-code-learner-control="module-start"' in frontend
    assert 'data-code-learner-control="function"' in frontend
    assert 'data-code-learner-control="function-start"' in frontend
    assert "generateCourse({ mode: \"module\" })" in frontend
    assert 'let activeNavigationGroup = "project";' in frontend
    assert 'activeNavigationGroup === "project"' in frontend
    assert 'activeNavigationGroup === "learn"' in frontend
    assert 'activeNavigationGroup === "outline"' in frontend
    assert "initialized && navigationExpanded.module" in frontend
    assert "initialized && navigationExpanded.architecture" in frontend
    assert "initialized && navigationExpanded.function" in frontend
    assert "Boolean(walkthrough) && navigationExpanded.outline" in frontend
    assert (
        "nav.module.disabled = initializing || !initialized || modules.length === 0;"
        in frontend
    )
    assert "nav.outlineMenu.disabled = !Boolean(walkthrough);" in frontend
    assert "function renderModuleOptions(modules, initialized)" in frontend
    assert "function pollInitializationStatus(options = {})" in frontend
    assert 'state.contextUrl("/api/code-learner/init/status")' in frontend
    assert 'state.contextUrl("/api/code-learner/init"),' not in frontend
    assert 'button.classList.toggle("active"' not in frontend
    assert 'setAttribute("aria-current", "step")' in frontend
    assert 'controls.dataset.codeLearnerPaneToolbar = ""' in frontend
    toolbar_source = frontend[
        frontend.index("function mountPaneToolbar") :
        frontend.index("function mountPaneTools")
    ]
    assert ">Previous</button>" in toolbar_source
    assert ">Next</button>" in toolbar_source
    assert "Tutor" not in toolbar_source
    assert "Refresh" not in toolbar_source
    assert 'addSection("code-learner-view", "View")' in frontend
    assert '"Refresh lesson"' in frontend
    assert '"Start tutor"' in frontend
    assert 'paneToolButton("Pop out"' in frontend
    assert "button.code-learner-tool-action" in stylesheet
    assert "text-align: center;" in stylesheet
    assert '<header class="code-learner-pane-header">' not in frontend
    assert 'data-code-learner-pane="refresh"' not in frontend
    assert 'activeLine.scrollIntoView({ block: "center", inline: "nearest" });' in frontend
    assert ".code-learner-pane-grid" in stylesheet
    assert ".code-learner-progress-fill" in stylesheet
    assert ".tok-keyword" in stylesheet
    assert "--code-learner-code-font-size: calc(var(--font-size) - 2px);" in stylesheet
    assert "font-size: var(--code-learner-code-font-size);" in stylesheet
    assert "font-size: calc(var(--font-size) + 9px);" in stylesheet
    assert "font-size: var(--font-size);" in stylesheet
    assert "line-height: var(--code-learner-code-line-height);" in stylesheet


def test_code_learner_navigation_uses_shared_shell_menu_treatment() -> None:
    modules = build_module_registry()
    workflows = build_workflow_registry(modules, (code_learner_workflow(),))
    stylesheet = read_service_text_asset(
        "css/workflows/code-learner.css",
        modules,
        workflows,
    )

    assert ".code-learner-workflow .workflow-pane" not in stylesheet
    assert "background: var(--active);" in stylesheet
    assert "var(--active-soft)" not in stylesheet
    assert ".code-learner-step-button.active" not in stylesheet
    assert ".code-learner-nav .stage-action-subgroup-trigger:disabled" in stylesheet
    assert "var(--border)" in stylesheet
    assert "var(--disabled)" in stylesheet
    assert ".code-learner-mode-grid" not in stylesheet


def test_pane_window_loads_installed_workflow_assets_for_code_learner() -> None:
    modules = build_module_registry()
    workflows = build_workflow_registry(modules, (code_learner_workflow(),))

    page = pane_window_html("code-learner", workflows)

    assert "__ELECTROBOY_CONTRIBUTION" not in page
    assert "/assets/service/js/core/registry.js" in page
    assert "/assets/service/js/workflows/code-learner.js" in page
    assert "/assets/service/css/workflows/code-learner.css" in page
    assert "window.ElectroBoyCodeLearnerPane.mount" in page
    assert "codeLearnerPane = window.ElectroBoyCodeLearnerPane.mount" in page
    assert "codeLearnerPane.refresh();" in page
    assert "toolbarHost: paneActions" in page
    assert "fontControl: paneFontControls" in page
    assert "popOut: requestCurrentPanePopOut" in page
    assert 'type: "electroboy:pane-pop"' in page
    assert 'if (kind === "code-learner") return "code-learner";' in page
    assert "paneTitle.textContent = title" in page
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
    assert 'if (kind === "code-learner") return "code-learner";' in runtime
    assert "INSTANCE_PANE_LAYOUT_KINDS.has(leaf.kind)" in runtime
    assert 'leaf.kind !== "artifact"' in runtime
    assert 'message.type === "electroboy:pane-pop"' in runtime
    assert 'parameters.set("popped", "1")' in runtime
    assert (
        'project.kind === "project" || project.kind === "meta"'
        in software
    )
