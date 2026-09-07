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

    assert "id: WORKFLOW_ID" in frontend
    assert 'navigation: "sidebar"' in frontend
    assert 'kind: "code-learner"' in frontend
    assert "window.ElectroBoyCodeLearnerPane" in frontend
    assert "refresh: () => loadPaneState(state)" in frontend
    assert "electroboy-code-learner-context" in frontend
    assert "preparePrompt" in frontend
    assert (
        "preparePrompt: (runtime, ...args) => invoke(runtime, preparePrompt, args)"
        in frontend
    )
    prepare_prompt_source = frontend[
        frontend.index("function preparePrompt") : frontend.index(
            "function handleWindowMessage"
        )
    ]
    assert "async function preparePrompt" in frontend
    assert "await tutorContextWrite;" in prepare_prompt_source
    assert "return message;" in prepare_prompt_source
    assert 'contextUrl("/api/code-learner/context")' in prepare_prompt_source
    assert "Source excerpt:" not in prepare_prompt_source
    assert "[ElectroBoy Code Learner context]" not in frontend
    assert 'contextUrl("/api/code-learner/walkthrough")' in frontend
    assert 'contextUrl("/api/code-learner/init/status")' in frontend
    assert 'data-code-learner-control="project-menu"' in frontend
    assert 'data-code-learner-control="open-project"' in frontend
    assert 'data-code-learner-control="clear-cache"' in frontend
    assert 'contextUrl("/api/code-learner/cache/clear")' in frontend
    assert "async function clearCourseCache()" in frontend
    assert "learnerState = emptyLearnerState();" in frontend
    assert "navigationExpanded.outline = false;" in frontend
    assert (
        "nav.clearCache.disabled = !hasProject || initializing || !initialized;"
        in frontend
    )
    assert "function openCourseDocument" not in frontend
    assert "function closeCourseDocument" not in frontend
    assert (
        "openLearnerPane({ activate: false, refresh: true, reset: true });" in frontend
    )
    assert "reset: () => resetPaneState(state)" in frontend
    assert "function resetPaneState(state)" in frontend
    assert "state.loadSequence += 1;" in frontend
    assert "loadSequence: 0," in frontend
    assert "const sequence = ++state.loadSequence;" in frontend
    assert "if (sequence !== state.loadSequence) {" in frontend
    assert 'if (Object.hasOwn(payload, "state_path")) {' in frontend
    assert 'if (Object.hasOwn(payload, "current_walkthrough")) {' in frontend
    assert "state.walkthrough = payload.current_walkthrough || null;" in frontend
    assert 'if (Object.hasOwn(payload, "source")) {' in frontend
    assert "state.source = payload.source || null;" in frontend
    assert 'clearButton.textContent = "Clear list";' in frontend
    assert 'separator.className = "stage-action-separator";' in frontend
    assert "runtimeApi.recent.clear(entries)" in frontend
    assert "clearButton.disabled = entries.length === 0;" in frontend
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
    assert 'data-code-learner-control="abort-initialization"' in frontend
    assert 'contextUrl("/api/code-learner/init/abort")' in frontend
    assert "async function abortInitialization()" in frontend
    assert "function ensureInitializationChoiceDialog()" in frontend
    assert "function chooseInitializationMode()" in frontend
    assert "code-learner-initialization-dialog" in frontend
    assert "<strong>Continue</strong>" in frontend
    assert "<strong>Replace</strong>" in frontend
    assert "statusPayload.initialization.choice_required" in frontend
    assert "body: JSON.stringify({ mode })" in frontend
    assert 'if (mode === "replace") {' in frontend
    assert "resetLearnerUi(payload);" in frontend
    assert "window.confirm" not in frontend
    assert 'status === "aborting"' in frontend
    assert 'data-code-learner-control="init-completion"' in frontend
    assert "renderInitializationCompletion()" in frontend
    assert 'initializationStatus !== "aborted"' in frontend
    assert "priorCompletionApplies && learnerState.completionStatus" in frontend
    assert 'terminal === "complete_with_warnings"' in frontend
    assert 'terminal === "failed"' in frontend
    assert "return learnerState.initialized;" in frontend
    assert "phase2_initialized" not in frontend
    assert "phase3_initialized" not in frontend
    assert 'else if (initializing) {\n      setStatus("");' in frontend
    assert ".code-learner-status:empty" in stylesheet
    assert 'runtimeApi.modules.invoke("progress", "showProgressSnapshot", {' in frontend
    assert (
        'runtimeApi.modules.invoke("progress", "closeProgressEventStream");' in frontend
    )
    assert "initialization.progress_events" in frontend
    assert ".filter((event) => (" in frontend
    assert (
        '["status", "turn", "warning", "error"].includes(event.activity_kind)'
        in frontend
    )
    assert "!event.heartbeat" in frontend
    assert ".map((event) => ({" in frontend
    assert '["warning", "error"].includes(event.activity_kind)' in frontend
    assert "if (event.activity)" in frontend
    assert "`[AI] ${message}\\r\\n`" in frontend
    assert "initializationProgressEventText(event)" in frontend
    assert "sanitizedInitializationProgress(event.message" in frontend
    assert "if (!running)" not in frontend
    assert 'data-code-learner-control="module"' in frontend
    assert 'data-code-learner-control="module-start"' in frontend
    assert 'data-code-learner-control="function"' in frontend
    assert 'data-code-learner-control="function-start"' in frontend
    assert 'role="status" aria-live="polite"' in frontend
    assert 'generateCourse({ mode: "module" })' in frontend
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
    assert "module.course_status" in frontend
    assert "function pollInitializationStatus(options = {})" in frontend
    assert "const wasInitialized = learnerInitialized();" in frontend
    assert "if (!wasInitialized) {" in frontend
    assert "elapsed_seconds" not in frontend
    assert "estimated_remaining_seconds" not in frontend
    assert 'state.contextUrl("/api/code-learner/init/status")' in frontend
    assert 'state.contextUrl("/api/code-learner/init"),' not in frontend
    assert 'button.classList.toggle("active"' not in frontend
    assert 'setAttribute("aria-current", "step")' in frontend
    assert 'controls.dataset.codeLearnerPaneToolbar = ""' in frontend
    toolbar_source = frontend[
        frontend.index("function mountPaneToolbar") : frontend.index(
            "function mountPaneTools"
        )
    ]
    assert ">Previous</button>" in toolbar_source
    assert ">Next</button>" in toolbar_source
    assert ">Back</button>" in toolbar_source
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
    assert 'data-code-learner-pane="question-form"' not in frontend
    assert 'data-code-learner-pane="question"' not in frontend
    assert "preparePaneQuestion" not in frontend
    assert "electroboy-code-learner-question" not in frontend
    assert (
        'activeLine.scrollIntoView({ block: "center", inline: "nearest" });' in frontend
    )
    assert ".code-learner-pane-grid" in stylesheet
    assert 'data-code-learner-pane-divider' in frontend
    assert 'role="separator"' in frontend
    assert "function startPaneSplitResize" in frontend
    assert "function resizePaneSplitWithKeyboard" in frontend
    assert "PANE_SPLIT_STORAGE_KEY" in frontend
    learner_state_source = frontend[
        frontend.index("function emptyLearnerState") : frontend.index(
            "function bindRuntime"
        )
    ]
    pane_state_source = frontend[
        frontend.index("function mountPane") : frontend.index(
            "function mountPaneToolbar"
        )
    ]
    assert "loadPaneSplitRatio()" not in learner_state_source
    assert "splitRatio: loadPaneSplitRatio()," in pane_state_source
    assert "--code-learner-pane-split" in stylesheet
    assert "cursor: col-resize;" in stylesheet
    assert "cursor: row-resize;" in stylesheet
    assert ".code-learner-progress-fill" in stylesheet
    assert ".tok-keyword" in stylesheet
    assert 'data-kind="resolving"' in stylesheet
    assert 'data-kind="analyzing"' in stylesheet
    assert 'data-kind="generating"' in stylesheet
    assert 'data-kind="validating"' in stylesheet
    assert 'data-kind="ready"' in stylesheet
    assert 'data-kind="ambiguous"' in stylesheet
    assert 'data-kind="missing"' in stylesheet
    assert 'data-kind="failed"' in stylesheet
    assert "state.host.dataset.renderMilliseconds" in frontend
    assert "function renderSlideMarkdown(markdown)" not in frontend
    assert "step.explanation_html" in frontend
    assert "renderMermaidDiagrams(state.host);" in frontend
    assert "window.ElectroBoyMermaid.render(host);" in frontend
    assert "function loadMermaid()" not in frontend
    assert ".code-learner-slide-body .mermaid" in stylesheet
    assert "cursor: zoom-in;" in stylesheet
    assert ".code-learner-slide-body table" in stylesheet
    assert "const referenceText = referenceLabel(reference);" in frontend
    assert "referenceText ?" in frontend
    assert '${reference.file_path || ""}:${reference.start_line || 1}' not in frontend
    assert "markdown_path" not in frontend
    assert "--code-learner-code-font-size: calc(var(--font-size) - 2px);" in stylesheet
    assert "font-size: var(--code-learner-code-font-size);" in stylesheet
    assert "font-size: calc(var(--font-size) + 9px);" in stylesheet
    assert "font-size: var(--font-size);" in stylesheet
    assert "line-height: var(--code-learner-code-line-height);" in stylesheet
    assert ".code-learner-question-form" not in stylesheet
    assert ".code-learner-question-actions" not in stylesheet
    assert ".code-learner-initialization-dialog" in stylesheet


def test_progress_output_distinguishes_warning_and_error_colors() -> None:
    runtime = (ROOT / "src/electroboy/assets/service/js/core/runtime.js").read_text(
        encoding="utf-8"
    )
    progress = (ROOT / "src/electroboy/modules/assets/progress.js").read_text(
        encoding="utf-8"
    )
    stylesheet = (ROOT / "src/electroboy/assets/service/css/shell.css").read_text(
        encoding="utf-8"
    )

    assert 'className === "warning"' in runtime
    assert r"\x1b[33m" in runtime
    assert r"\x1b[31m" in runtime
    assert '["warning", "error"].includes(payload.type)' in progress
    assert ".progress-output .warning" in stylesheet
    assert ".progress-output .error" in stylesheet


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
    assert "codeLearnerPane.reset();" in page
    assert "toolbarHost: paneActions" in page
    assert "fontControl: paneFontControls" in page
    assert "popOut: requestCurrentPanePopOut" in page
    assert 'type: "electroboy:pane-pop"' in page
    assert 'if (kind === "code-learner") return "code-learner";' in page
    assert "paneTitle.textContent = title" in page
    assert 'if (kind === "code-learner") return "Code Learner";' in page
    assert (
        'if (PANE_KIND === "code-learner" && codeLearnerPane) {\n'
        "          codeLearnerPane.refresh();"
        in page
    )


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
    assert 'project.kind === "project" || project.kind === "meta"' in software
