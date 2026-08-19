from __future__ import annotations

import http.client
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.cli import build_parser  # noqa: E402
from electroboy.modules.agenda_workspace import render_agenda_html  # noqa: E402
from electroboy.modules.creative_workspace import (  # noqa: E402
    render_corkboard_html,
)
from electroboy.service import (  # noqa: E402
    CREATIVE_SPLASH_IMAGE_ROUTE,
    FILE_BROWSER_WINDOW_HTML,
    GENERIC_STAGE_CONFIG,
    INDEX_HTML,
    MAX_TERMINAL_COLUMNS,
    MAX_TERMINAL_ROWS,
    MIN_TERMINAL_COLUMNS,
    MIN_TERMINAL_ROWS,
    PANE_WINDOW_HTML,
    SPLASH_IMAGE_ROUTE,
    AgentSession,
    AgentSessionError,
    SESSION_ARTIFACT_LOCKS,
    ServiceState,
    TmuxAgentSession,
    _agent_process_env,
    _artifact_event_document_path,
    _clean_terminal_output,
    _file_signature,
    _progress_once_command,
    _progress_snapshot,
    _progress_snapshot_markdown,
    _reopen_requirements_for_restart,
    _requirements_command,
    _session_events_markdown,
    _service_session_records_path,
    _status_command,
    _status_snapshot,
    _terminal_input_chunks_for_message,
    _terminal_input_for_key,
    _terminal_input_for_message,
    artifact_editor_html,
    browse_directories,
    browse_files,
    browse_markdown_files,
    create_server,
    creative_corkboard_html,
    document_target_html,
    file_browser_window_html,
    pane_window_html,
    requirements_document_html,
    save_artifact_edit,
    splash_image_bytes,
    workflow_payload,
)
from electroboy.service.agenda import normalize_agenda_snapshot  # noqa: E402
from electroboy.service.corkboard import (  # noqa: E402
    CorkboardWorkflowController,
    normalize_board_snapshot,
)
from electroboy.service.frontend import (  # noqa: E402
    read_service_text_asset,
    render_service_index,
)
from electroboy.service.services import ServiceServices  # noqa: E402
from electroboy.service.registry import (  # noqa: E402
    MODULE_ENTRY_POINT_GROUP,
    WORKFLOW_ENTRY_POINT_GROUP,
    InstalledFactory,
    ServiceModule,
    WorkflowDefinition,
    WorkflowStage,
    build_module_registry,
    build_workflow_registry,
    installed_module_factories,
)
from electroboy.service.routes import build_route_dispatcher  # noqa: E402
from electroboy.service.workflow_config import (  # noqa: E402
    WorkflowConfig,
    add_configured_workflow,
    configured_workflows,
    load_workflow_config,
    save_workflow_config,
)
from electroboy.models import (  # noqa: E402
    STAGE_DESIGN,
    STAGE_DESIGN_ACCEPTANCE,
    STAGE_DESIGN_REVIEW,
    STAGE_REQUIREMENTS,
)
from electroboy.state_store import StateError, StateStore  # noqa: E402


class ServiceTests(unittest.TestCase):
    def test_installed_entry_points_register_provider_metadata(self) -> None:
        class Distribution:
            metadata = {"Name": "sample-capabilities"}

        class EntryPoint:
            name = "sample"
            value = "sample_package:module"
            dist = Distribution()

            @staticmethod
            def load():
                return lambda: ServiceModule(id="sample", label="Sample")

        factories = installed_module_factories((EntryPoint(),))
        contribution = factories["sample"]()

        self.assertEqual(factories["sample"].provider, "sample-capabilities")
        self.assertEqual(contribution.provider, "sample-capabilities")
        self.assertEqual(contribution.entry_point, "sample_package:module")

    def test_installed_workflow_can_be_enabled_by_entry_point_id(self) -> None:
        definition = WorkflowDefinition(
            id="sample-workflow",
            label="Sample Workflow",
            modules=("core",),
            stages=(WorkflowStage("project", "Project", None),),
            project_kinds=("sample",),
            backend_package="sample_workflow",
            frontend_bundle="workflows/sample.js",
        )
        factory = InstalledFactory(
            id="sample-workflow",
            group=WORKFLOW_ENTRY_POINT_GROUP,
            provider="sample-workflow-package",
            reference="sample_workflow:workflow",
            factory=lambda: definition,
        )
        installed = {"sample-workflow": factory}

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "electroboy.service.workflow_config.installed_workflow_factories",
                return_value=installed,
            ):
                add_configured_workflow(tmp, "sample-workflow", "")
                config = load_workflow_config(tmp)
                workflows = configured_workflows(tmp, installed)

        self.assertEqual(
            config.extra_workflows[0].factory,
            "entry-point:sample-workflow",
        )
        self.assertEqual(
            [workflow.id for workflow in workflows],
            ["sample-workflow"],
        )
        self.assertEqual(workflows[0].provider, "sample-workflow-package")

    def test_installed_factory_rejects_mismatched_definition_id(self) -> None:
        factory = InstalledFactory(
            id="declared",
            group=MODULE_ENTRY_POINT_GROUP,
            provider="sample-package",
            reference="sample_package:module",
            factory=lambda: ServiceModule(id="returned", label="Returned"),
        )

        with self.assertRaisesRegex(ValueError, "entry point name"):
            factory()

    def test_index_includes_only_registered_contribution_scripts(self) -> None:
        modules = build_module_registry(
            (
                ServiceModule(
                    id="sample-module",
                    label="Sample Module",
                    assets=("js/modules/sample.js",),
                ),
            )
        )
        workflows = build_workflow_registry(
            modules,
            (
                WorkflowDefinition(
                    id="sample-workflow",
                    label="Sample Workflow",
                    modules=("sample-module",),
                    stages=(WorkflowStage("project", "Project", None),),
                    project_kinds=("sample",),
                    backend_package="sample_workflow",
                    frontend_bundle="workflows/sample.js",
                ),
            ),
        )
        template = (
            "<!-- __ELECTROBOY_CONTRIBUTION_SCRIPTS__ -->\n"
            '<script src="/assets/service/js/core/runtime.js"></script>'
        )

        page = render_service_index(template, modules, workflows)

        self.assertIn("/assets/service/js/modules/sample.js", page)
        self.assertIn("/assets/service/js/workflows/sample.js", page)
        self.assertNotIn("creative-writing.js", page)

    def test_health_endpoint_reports_connected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = request(server, "/api/health")
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        payload = json.loads(body)
        self.assertEqual(payload["status"], "connected")
        self.assertEqual(payload["service"], "electroboy")
        self.assertEqual(payload["root"], str(root.resolve()))
        self.assertIn("agent_sessions", payload["modules"])
        self.assertIn("software", payload["workflows"])

        self.assertIn("core-shell", payload["frontend_bundles"])
        module_plugins = {
            entry["id"]: entry for entry in payload["plugins"]["modules"]
        }
        workflow_plugins = {
            entry["id"]: entry for entry in payload["plugins"]["workflows"]
        }
        self.assertTrue(module_plugins["core"]["provider"])
        self.assertEqual(
            module_plugins["core"]["entry_point"],
            "electroboy.service.core_module:module",
        )
        self.assertTrue(workflow_plugins["software"]["provider"])
        self.assertEqual(
            workflow_plugins["software"]["entry_point"],
            "electroboy.workflows.software.plugin:workflow",
        )

    def test_server_loads_workflows_and_state_from_separate_state_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browse_root = Path(tmp) / "browse"
            state_root = Path(tmp) / "state"
            browse_root.mkdir()
            state_root.mkdir()
            save_workflow_config(
                state_root,
                WorkflowConfig(enabled_builtins=("creative-writing",)),
            )
            try:
                server = create_server(browse_root, port=0, state_root=state_root)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            try:
                self.assertEqual(server.service_state.root, browse_root.resolve())
                self.assertEqual(server.service_state.state_root, state_root.resolve())
                self.assertEqual(
                    [
                        workflow.id
                        for workflow in server.service_state.workflow_registry.values()
                    ],
                    ["creative-writing"],
                )
                self.assertTrue(
                    (state_root / ".electroboy/service/session-transcripts").is_dir()
                )
                self.assertFalse(
                    (browse_root / ".electroboy/service/session-transcripts").exists()
                )
            finally:
                server.server_close()

    def test_registry_endpoint_reports_backend_modules_and_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = request(server, "/api/registry")
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        payload = json.loads(body)
        modules = {entry["id"]: entry for entry in payload["modules"]}
        workflows = {entry["id"]: entry for entry in payload["workflows"]}
        frontend_bundles = {
            entry["id"]: entry for entry in payload["frontend_bundles"]
        }
        self.assertIn("agent_sessions", modules)
        self.assertIn("structured_documents", modules)
        self.assertIn("agenda", modules)
        self.assertIn("corkboard", modules)
        agenda_routes = {
            (route["method"], route["path"])
            for route in modules["agenda"]["routes"]
        }
        self.assertIn(("GET", "/artifacts/agenda"), agenda_routes)
        self.assertIn(("GET", "/api/agenda"), agenda_routes)
        self.assertIn(("POST", "/api/agenda/action"), agenda_routes)
        self.assertIn(("GET", "/api/agenda/editor"), agenda_routes)
        self.assertIn(("POST", "/api/agenda/editor"), agenda_routes)
        self.assertIn("agenda-provider", modules["agenda"]["capabilities"])
        corkboard_routes = {
            (route["method"], route["path"])
            for route in modules["corkboard"]["routes"]
        }
        self.assertIn(("GET", "/artifacts/corkboard"), corkboard_routes)
        self.assertIn(("GET", "/api/corkboard"), corkboard_routes)
        self.assertIn(("GET", "/api/corkboards"), corkboard_routes)
        self.assertIn(("POST", "/api/corkboard"), corkboard_routes)
        self.assertIn("corkboard-provider", modules["corkboard"]["capabilities"])
        self.assertIn(
            "selectable-corkboard-layout",
            modules["corkboard"]["capabilities"],
        )
        self.assertIn(
            "corkboard-auto-organize",
            modules["corkboard"]["capabilities"],
        )
        self.assertIn(
            "corkboard-board-selector",
            modules["corkboard"]["capabilities"],
        )
        core_handlers = {route["handler"] for route in modules["core"]["routes"]}
        self.assertIn("workflow_config", core_handlers)
        self.assertIn("add_configured_workflow", core_handlers)
        self.assertIn("software", workflows)
        self.assertIn("creative-writing", workflows)
        self.assertIn("agent_sessions", workflows["software"]["modules"])
        self.assertIn("core-shell", frontend_bundles)
        self.assertIn("index.html", frontend_bundles["core-shell"]["assets"])
        self.assertIn(
            "js/core/pane-layout-drag.js",
            frontend_bundles["core-shell"]["assets"],
        )
        self.assertIn(
            "js/core/input-shortcut.js",
            frontend_bundles["core-shell"]["assets"],
        )
        self.assertIn(
            "js/core/pane-sync.js",
            frontend_bundles["core-shell"]["assets"],
        )
        self.assertIn(
            "js/core/pane-tools.js",
            frontend_bundles["core-shell"]["assets"],
        )
        self.assertIn(
            "js/core/terminal-behavior.js",
            frontend_bundles["core-shell"]["assets"],
        )
        self.assertIn("software-workflow", frontend_bundles)
        self.assertIn("creative-writing-workflow", frontend_bundles)
        self.assertIn("documents", frontend_bundles)
        self.assertIn("agenda", frontend_bundles)
        self.assertIn("binder", frontend_bundles)
        self.assertIn("pane-window", frontend_bundles)
        self.assertIn(
            "js/core/pane-workspace.js",
            frontend_bundles["pane-window"]["assets"],
        )
        self.assertIn(
            "js/core/pane-sync.js",
            frontend_bundles["pane-window"]["assets"],
        )
        self.assertIn(
            "js/core/pane-tools.js",
            frontend_bundles["pane-window"]["assets"],
        )
        self.assertIn(
            "js/core/terminal-behavior.js",
            frontend_bundles["pane-window"]["assets"],
        )
        self.assertIn(
            "js/modules/file-pane-tools.js",
            frontend_bundles["documents"]["assets"],
        )
        self.assertEqual(
            payload["workflow_config"]["enabled_builtins"],
            ["software", "creative-writing"],
        )

    def test_frontend_contributions_own_workflow_and_module_behavior(self) -> None:
        modules = build_module_registry()
        workflows = build_workflow_registry(modules)
        registry = read_service_text_asset("js/core/registry.js")
        software = read_service_text_asset(
            "js/workflows/software.js", modules, workflows
        )
        creative = read_service_text_asset(
            "js/workflows/creative-writing.js", modules, workflows
        )
        sessions = read_service_text_asset("js/modules/agent-sessions.js")
        input_shortcut = read_service_text_asset("js/core/input-shortcut.js")
        pane_sync = read_service_text_asset("js/core/pane-sync.js")
        pane_tools = read_service_text_asset("js/core/pane-tools.js")
        terminal_behavior = read_service_text_asset(
            "js/core/terminal-behavior.js"
        )
        documents = read_service_text_asset("js/modules/documents.js")
        file_pane_tools = read_service_text_asset(
            "js/modules/file-pane-tools.js",
            modules,
            workflows,
        )
        binder = read_service_text_asset("js/modules/binder.js")
        corkboard = read_service_text_asset("js/modules/corkboard.js")
        agenda = read_service_text_asset("js/modules/agenda.js")
        file_browser = read_service_text_asset("js/modules/file-browser.js")
        progress = read_service_text_asset("js/modules/progress.js")
        project_shell = read_service_text_asset("js/modules/project-shell.js")
        app = read_service_text_asset("js/core/runtime.js")

        self.assertIn("bindRuntime(nextRuntime)", registry)
        self.assertIn("invokeWorkflow(id, action, ...args)", registry)
        self.assertIn("invokeModule(id, action, ...args)", registry)
        self.assertIn("function stageActions(stageId, runtime)", software)
        self.assertIn('if (stageId === "corkboard")', software)
        self.assertIn('sidecarStages: ["document", "corkboard"]', software)
        self.assertIn('contextUrl("/api/corkboards")', software)
        self.assertIn('navigation: "stages"', software)
        self.assertIn("function resetSoftwareWorkflowState()", software)
        self.assertIn("deactivate,", software)
        self.assertIn("stageDescriptions: STAGE_DESCRIPTIONS", software)
        self.assertNotIn("function mount(runtime)", software)
        self.assertIn("async function startAgent(runtime)", creative)
        self.assertIn("function selectFolder(runtime, path)", creative)
        self.assertIn("function renderNavigation(container, runtime)", creative)
        self.assertIn('const WORKFLOW_ID = "creative-writing"', creative)
        self.assertIn("runtimeApi.getState().workflowMode === WORKFLOW_ID", creative)
        self.assertNotIn('workflowMode === "creative"', creative)
        self.assertIn("function resetCreativeWorkflowState()", creative)
        self.assertIn("window.clearTimeout(creativeScratchSaveTimer);", creative)
        self.assertIn("Recent projects", software)
        self.assertIn('action.openProjectBrowser("meta-add", true)', software)
        self.assertIn('subgroup: "project-meta-remove"', software)
        self.assertIn('subgroup: "project-meta-start"', software)
        self.assertIn('label: isActive ? `Active: ${label}` : label', software)
        self.assertNotIn('subgroup: "project-meta-repositories"', software)
        self.assertIn('data-creative-control="recent-projects-menu"', creative)
        self.assertIn("creativeRecentProjectsExpanded = false", creative)
        self.assertIn('navigation: "sidebar"', creative)
        self.assertIn("function renderTree(runtime)", binder)
        self.assertIn("function show(runtime, source, options = {})", corkboard)
        self.assertIn('kind: "corkboard"', corkboard)
        self.assertIn('kind: "agenda"', agenda)
        self.assertIn('id: "agenda"', agenda)
        self.assertIn("function artifactPaneIsAgenda(item)", documents)
        self.assertIn("function artifactPaneIsProviderView(item)", documents)
        self.assertIn("/artifacts/agenda", documents)
        self.assertNotIn('invokeWorkflow(\n        "creative-writing"', corkboard)
        self.assertIn("async function refreshServiceSessions()", sessions)
        self.assertIn("ElectroBoyInputShortcut.bindRecorder", sessions)
        self.assertIn("shortcutController.matches(event)", sessions)
        self.assertNotIn("isEnter && event.shiftKey", sessions)
        self.assertIn("function bindRecorder(button)", input_shortcut)
        self.assertIn("electroboy.agentSendShortcut.v1", input_shortcut)
        self.assertIn("Hover to record a new shortcut", input_shortcut)
        self.assertIn("function connect(options = {})", pane_sync)
        self.assertIn("window.BroadcastChannel", pane_sync)
        self.assertNotIn("creative-writing", pane_sync)
        self.assertNotIn("software", pane_sync)
        self.assertIn("function create(options)", pane_tools)
        self.assertIn("function addSection(id, label", pane_tools)
        self.assertIn("function bindKeyboardTarget(targetWindow)", pane_tools)
        self.assertIn('String(event.key).toLowerCase() !== "n"', pane_tools)
        self.assertNotIn("documentation/start", pane_tools)
        self.assertNotIn("creative-writing", pane_tools)
        self.assertIn('controller.addSection("corkboard-view", "Board view")', file_pane_tools)
        self.assertIn('controller.addSection("corkboard-color", "Selected card")', file_pane_tools)
        self.assertIn('controller.addSection("corkboard-export", "Export")', file_pane_tools)
        self.assertIn('postBoardTool("random-card-color")', file_pane_tools)
        self.assertIn('postBoardTool("export", exportFormat.value)', file_pane_tools)
        self.assertIn('type: "electroboy-corkboard-tool"', file_pane_tools)
        self.assertIn("const supportsCardColor = state.canChangeColor !== false;", file_pane_tools)
        self.assertIn("This board does not support card color changes.", file_pane_tools)
        self.assertIn("Select a card, then choose a color.", file_pane_tools)
        self.assertIn("terminal.hasSelection()", terminal_behavior)
        self.assertIn("navigator.clipboard.writeText", terminal_behavior)
        self.assertIn("terminal.registerMarker", terminal_behavior)
        self.assertIn("terminal.scrollToBottom()", terminal_behavior)
        self.assertIn("terminal.scrollToLine(marker.line)", terminal_behavior)
        self.assertIn("window.ElectroBoyFilePaneTools", file_pane_tools)
        self.assertIn('controller.addSection("find", "Find")', file_pane_tools)
        self.assertIn('controller.addSection("actions", "Actions")', file_pane_tools)
        self.assertIn('menu("File", "pane-tool-file-menu")', file_pane_tools)
        self.assertIn('menu("Export", "pane-tool-export-menu")', file_pane_tools)
        self.assertLess(
            file_pane_tools.index('["markdown", "Markdown"]'),
            file_pane_tools.index('["pdf", "PDF"]'),
        )
        self.assertLess(
            file_pane_tools.index('["pdf", "PDF"]'),
            file_pane_tools.index('["docx", "DOCX"]'),
        )
        self.assertIn("frame.contentWindow.find(", file_pane_tools)
        self.assertIn(
            'contextUrl("/api/agents/documentation/start")',
            file_pane_tools,
        )
        self.assertIn('runtime.sharedPanes.connect("input"', sessions)
        self.assertIn('runtime.sharedPanes.connect("progress"', progress)
        self.assertNotIn('sharedPanes.connect("input"', app)
        self.assertNotIn('sharedPanes.connect("progress"', app)
        self.assertIn('frontendRuntime.sharedPanes.connect("scratch"', app)
        self.assertIn('frontendRuntime.sharedPanes.connect("status"', app)
        self.assertIn(
            "function showArtifactPreviews(items, options = {})",
            documents,
        )
        self.assertIn("function mountDockedPaneTools()", documents)
        self.assertIn("ElectroBoyPaneTools.create", documents)
        self.assertIn("ElectroBoyFilePaneTools.mount", documents)
        self.assertIn("electroboy.paneTools.docked.artifact", documents)
        self.assertIn(
            "runtimeState.manualArtifactPreview\n"
            "        && runtimeState.artifactPreviewItems.length > 0",
            documents,
        )
        self.assertIn(
            'if (item.kind === "document" && item.target)',
            documents,
        )
        self.assertIn("rememberOpenDocumentTarget(item.target);", documents)
        self.assertIn("function buildDocumentMenu(item)", documents)
        self.assertIn('summary.textContent = "Document"', documents)
        self.assertIn('"Preview",', documents)
        self.assertIn('"Edit",', documents)
        self.assertIn('"Refresh",', documents)
        self.assertIn('exportLabel.textContent = "Export"', documents)
        self.assertNotIn('exportFormat.className = "document-export-format"', documents)
        self.assertIn("function openDocumentTarget(target)", documents)
        self.assertIn("function popOutArtifactPreview(item)", documents)
        self.assertNotIn('popOutPane("artifact", item)', documents)
        self.assertIn(
            'parameters.set("corkboard_id", board.id || board.path)',
            documents,
        )
        self.assertIn("/artifacts/corkboard", documents)
        self.assertIn(
            "`electroboy-artifact-${item.id}-${runtimeState.contextId}`",
            documents,
        )
        self.assertIn('agentButton.textContent = "Start agent"', documents)
        self.assertNotIn("launchDocumentTarget", documents)
        self.assertIn(
            "function openProjectBrowser(mode = state().projectMode",
            file_browser,
        )
        self.assertIn('"documents", "openDocumentTarget"', file_browser)
        self.assertNotIn("_runtime", sessions)
        self.assertNotIn("_runtime", documents)
        self.assertNotIn("_runtime", file_browser)
        self.assertIn("function connectProgressEvents(runtime)", progress)
        self.assertIn("async function startProjectShell(runtime)", project_shell)
        self.assertIn(
            'window.open("", popupName, SHELL_POPUP_FEATURES)',
            project_shell,
        )
        self.assertIn('parameters.set("shell_session_id", sessionId)', project_shell)
        self.assertIn("nextState.projectShellPaneRequested", project_shell)
        self.assertIn("projectShellPaneRequested: false", project_shell)
        self.assertIn('runtime.sharedPanes.connect("file-catalog"', documents)
        self.assertIn("function openFileCatalogState()", documents)
        self.assertIn("function updateSelectOptions(select, options", documents)
        document_switcher_start = documents.index("function renderDocumentTargetSwitcher(select)")
        document_switcher_end = documents.index(
            "function refreshDocumentTargetSwitchers()",
            document_switcher_start,
        )
        document_switcher_source = documents[
            document_switcher_start:document_switcher_end
        ]
        self.assertIn("updateSelectOptions(", document_switcher_source)
        self.assertNotIn("replaceChildren", document_switcher_source)
        self.assertNotIn(
            "showProjectShellPane(runtime, true);\n"
            "    initializeProjectShellTerminal(runtime);\n"
            "    appendProjectShellOutput",
            project_shell,
        )
        self.assertNotIn("_runtime", progress)
        self.assertNotIn("_runtime", project_shell)
        self.assertIn("runtime.http.eventSource", progress)
        self.assertIn("runtime.http.eventSource", project_shell)
        self.assertIn("async function startRequirementsAgent()", software)
        ad_hoc_start_offset = software.index("async function startAdHocAgent()")
        ad_hoc_start = software[
            ad_hoc_start_offset : software.index(
                "async function runRequirementsAgent",
                ad_hoc_start_offset,
            )
        ]
        self.assertNotIn("hideArtifactPreview()", ad_hoc_start)
        self.assertIn('contextUrl("/api/agents/ad-hoc/sessions")', software)
        self.assertIn("function ensureAdHocSessionDialog()", software)
        self.assertIn("provider_session_id: choice.providerSessionId", ad_hoc_start)
        self.assertIn("async function startGenericStageAgent(", software)
        self.assertIn("function bindRuntime(runtime)", software)
        self.assertIn("function bindRuntime(runtime)", creative)
        self.assertIn('contextUrl("/api/corkboards")', creative)
        self.assertNotIn('contextUrl("/api/creative/corkboards")', creative)
        self.assertIn('contextUrl("/api/corkboard")', creative)
        self.assertIn("action: \"rename-board\"", creative)
        self.assertIn(
            "renameInput(runtime, entry, entryActionType, path)",
            binder,
        )
        self.assertIn(
            "action.finishCreativeRename(path, actionType, input.value);",
            binder,
        )
        self.assertNotIn(
            "action.finishCreativeRename(path, type, input.value);",
            binder,
        )
        self.assertNotIn("runtime.actions", software)
        self.assertNotIn("runtime.actions", creative)
        self.assertNotIn("runtime.actions", binder)
        self.assertNotIn("runtime.actions", corkboard)
        self.assertNotIn("runtimeApi.actions", documents)
        self.assertNotIn('invokeWorkflow("software"', app)
        self.assertNotIn('invokeWorkflow("creative-writing"', app)
        self.assertIn('invokeActiveWorkflowHook("projectChanged"', app)
        self.assertIn(
            "async function notifyCreativeAgentTargetSwitch()",
            creative,
        )
        self.assertNotIn("function projectStageActions()", app)
        self.assertNotIn("function appendCreativeTreeEntry", app)
        self.assertNotIn("async function refreshServiceSessions()", app)
        self.assertNotIn(
            "function showArtifactPreviews(items, options = {})",
            app,
        )
        self.assertNotIn("function connectProgressEvents()", app)
        self.assertNotIn("async function startProjectShell()", app)
        self.assertNotIn("async function startRequirementsAgent()", app)
        self.assertNotIn("async function startGenericStageAgent(", app)
        self.assertNotIn("const SOFTWARE_WORKFLOW_MODE", app)
        self.assertNotIn("const CREATIVE_WORKFLOW_MODE", app)
        self.assertIn("event.source !== entry.popup", app)
        self.assertIn("event.key === scratchPadStorageKey()", app)
        self.assertIn('scratchPad.value = event.newValue || "";', app)

    def test_project_activation_preserves_explicit_pane_layout(self) -> None:
        modules = build_module_registry()
        workflows = build_workflow_registry(modules)
        runtime = read_service_text_asset("js/core/runtime.js")
        documents = read_service_text_asset("js/modules/documents.js")
        creative = read_service_text_asset(
            "js/workflows/creative-writing.js",
            modules,
            workflows,
        )

        self.assertIn(
            'hasPane: (kind) => Boolean(paneLayoutLeafByKind(kind))',
            runtime,
        )
        self.assertIn(
            'runtimeState.artifactPaneRequested = runtimeApi.layout.hasPane("artifact")',
            documents,
        )
        self.assertNotIn(
            "runtimeState.artifactPaneRequested = "
            "Boolean(runtimeState.activeProjectRoot)",
            documents,
        )
        sync_start = documents.index("function syncArtifactPreviewWithProject()")
        sync_end = documents.index("async function startDocumentationAgent", sync_start)
        sync_source = documents[sync_start:sync_end]
        self.assertIn('if (runtimeApi.layout.hasPane("artifact"))', sync_source)
        self.assertNotIn(
            "\n      runtimeState.artifactPaneRequested = true;\n"
            "      applyOutputPaneVisibility();",
            sync_source,
        )
        self.assertIn(
            'artifactPaneRequested = runtimeApi.layout.hasPane("artifact")',
            creative,
        )

    def test_pane_layout_allows_independent_duplicate_types(self) -> None:
        runtime = read_service_text_asset("js/core/runtime.js")
        documents = read_service_text_asset("js/modules/documents.js")
        workspace = read_service_text_asset("js/core/pane-workspace.js")
        styles = read_service_text_asset("css/shell.css")

        self.assertNotIn("existing.kind = previousKind", runtime)
        self.assertIn('requestedKind === "agent" && seenKinds.has("agent")', runtime)
        self.assertIn("buildPaneLayoutInstanceFrame(node)", runtime)
        self.assertIn("function setActivePaneLayoutLeaf(id)", runtime)
        self.assertIn('message.type === "electroboy:pane-activate"', runtime)
        self.assertIn("function paneLayoutArtifactIsProjectScoped(item)", runtime)
        self.assertIn('item.kind === "agenda"', runtime)
        self.assertIn('provider === "creative-files"', runtime)
        self.assertIn('provider === "project-files"', runtime)
        self.assertIn("leaf.projectRoot === activeProjectRoot", runtime)
        self.assertIn("assignArtifact: assignArtifactToPane", runtime)
        self.assertIn("function paneLayoutRequestedArtifact(leaf)", runtime)
        self.assertIn("function updateLoadedPaneLayoutFrame(frame, leaf, nextUrl)", runtime)
        self.assertIn('type: "electroboy:pane-set-artifact"', runtime)
        self.assertIn("function paneLayoutStorageKey(mode = workflowMode)", runtime)
        self.assertIn("storedPaneLayout(mode = workflowMode)", runtime)
        self.assertIn("key.startsWith(`${PANE_LAYOUT_STORAGE_KEY}.`)", runtime)
        self.assertIn("loadPaneLayoutForWorkflow();", runtime)
        self.assertIn("function serviceFingerprintFromPayload(payload)", runtime)
        self.assertIn("function clearStaleServiceBrowserState()", runtime)
        self.assertIn("function hasServiceBrowserState()", runtime)
        self.assertIn("SERVICE_FINGERPRINT_STORAGE_KEY", runtime)
        self.assertIn(
            'const SERVICE_FINGERPRINT_STORAGE_KEY = "electroboy.serviceFingerprint.v2";',
            runtime,
        )
        self.assertIn("LEGACY_SERVICE_FINGERPRINT_STORAGE_KEYS", runtime)
        self.assertIn("hasLegacyFingerprint || hasServiceBrowserState()", runtime)
        self.assertIn("window.localStorage.removeItem(PANE_LAYOUT_STORAGE_KEY)", runtime)
        self.assertIn("async function applyWorkflowMode(options = {})", runtime)
        self.assertIn("await contribution.activate(frontendRuntime);", runtime)
        self.assertIn("await applyWorkflowMode({ deferWorkspace: true });", runtime)
        self.assertIn("function syncStageNodeState()", runtime)
        self.assertIn("syncStageNodeState();", runtime)
        self.assertIn('frame.dataset.paneLoaded = "1";', runtime)
        initialize_start = runtime.index("async function initialize()")
        initialize_source = runtime[initialize_start:]
        self.assertLess(
            initialize_source.index("await applyWorkflowMode({ deferWorkspace: true });"),
            initialize_source.index("await restoreContext();"),
        )
        self.assertLess(
            initialize_source.index("await restoreContext();"),
            initialize_source.index("await applyWorkflowMode();"),
        )
        switch_start = runtime.index("async function setWorkflowMode(")
        switch_end = runtime.index("function applyWorkflowSideSheetState(", switch_start)
        switch_source = runtime[switch_start:switch_end]
        self.assertLess(
            switch_source.index("resetWorkflowContextView();"),
            switch_source.index("previous.deactivate(frontendRuntime);"),
        )
        self.assertLess(
            switch_source.index("saveWorkflowMode();"),
            switch_source.index("loadPaneLayoutForWorkflow();"),
        )
        self.assertLess(
            switch_source.index("loadPaneLayoutForWorkflow();"),
            switch_source.index("await applyWorkflowMode({ deferWorkspace: true });"),
        )
        self.assertLess(
            switch_source.index("await restoreContext();"),
            switch_source.index("await applyWorkflowMode();", switch_source.index("await restoreContext();")),
        )
        assign_start = runtime.index("function assignArtifactToPane(")
        assign_end = runtime.index("function handlePaneLayoutMessage(", assign_start)
        assign_source = runtime[assign_start:assign_end]
        self.assertIn("refreshPaneLayoutInstanceFrames();", assign_source)
        self.assertNotIn("renderPaneLayout();", assign_source)
        self.assertIn("runtimeApi.layout.assignArtifact(nextItems[0]);", documents)
        self.assertIn('kind === "agent" &&', workspace)
        self.assertIn(".pane-layout-leaf.active::before", styles)
        self.assertIn("border: 3px solid #9bd6cf;", styles)
        self.assertIn("pointer-events: none;", styles)
        self.assertIn(".artifact-preview-frame.loading {\n      opacity: 1;", styles)

    def test_agent_input_actions_are_fixed_height_and_top_aligned(self) -> None:
        styles = read_service_text_asset("css/shell.css")

        self.assertIn("var(--input-pane-height, 220px)", styles)
        self.assertIn("grid-template-rows: repeat(3, 42px);", styles)
        self.assertIn("gap: 10px;\n      align-content: start;", styles)
        self.assertIn("min-height: 42px;\n      height: 42px;", styles)
        self.assertNotIn("repeat(3, minmax(30px, auto))", styles)

    def test_workflow_payload_exposes_plugin_contract_metadata(self) -> None:
        modules = build_module_registry()
        workflows = build_workflow_registry(modules)
        software = workflows.get("software").payload()
        creative = workflows.get("creative-writing").payload()

        self.assertIn(
            "implementation-plan",
            {command["id"] for command in software["commands"]},
        )
        self.assertIn(
            "requirements",
            {schema["id"] for schema in software["document_schemas"]},
        )
        self.assertIn(
            "reviewer",
            {role["id"] for role in software["runtime_roles"]},
        )
        self.assertEqual(
            creative["document_schemas"][0]["source_format"],
            "markdown",
        )

        page = render_service_index(
            read_service_text_asset("index.html"),
            modules,
            workflows,
        )
        self.assertLess(
            page.index("js/modules/documents.js"),
            page.index("js/core/runtime.js"),
        )
        self.assertLess(
            page.index("js/workflows/software.js"),
            page.index("js/core/runtime.js"),
        )
        self.assertLess(
            page.index("js/core/pane-layout-drag.js"),
            page.index("js/core/runtime.js"),
        )
        self.assertIn("css/workflows/software.css", page)
        self.assertIn("css/workflows/creative-writing.css", page)

        empty_modules = build_module_registry(())
        empty_workflows = build_workflow_registry(empty_modules, ())
        core_page = render_service_index(
            read_service_text_asset("index.html"),
            empty_modules,
            empty_workflows,
        )
        self.assertNotIn("js/workflows/software.js", core_page)
        self.assertNotIn("js/workflows/creative-writing.js", core_page)
        self.assertNotIn("css/workflows/software.css", core_page)
        self.assertNotIn("css/workflows/creative-writing.css", core_page)
        self.assertNotIn('data-stage="requirements"', core_page)
        self.assertNotIn("Creative writing", core_page)

    def test_workflow_side_sheet_is_resizable_with_a_text_aware_minimum(self) -> None:
        page = read_service_text_asset("index.html")
        css = read_service_text_asset("css/shell.css")
        runtime = read_service_text_asset("js/core/runtime.js")

        self.assertIn('id="workflowSideSheetResizeHandle"', page)
        self.assertIn('aria-label="Resize workflow menu"', page)
        self.assertIn(".workflow-side-sheet-resize-handle", css)
        self.assertIn("--workflow-side-sheet-min-width", css)
        self.assertIn("WORKFLOW_SIDE_SHEET_WIDTH_STORAGE_KEY", runtime)
        self.assertIn("function measuredWorkflowSideSheetMinimumWidth()", runtime)
        self.assertIn("context.measureText(value).width", runtime)
        self.assertIn("function startWorkflowSideSheetResize(event)", runtime)
        self.assertIn("function updateWorkflowSideSheetResize(event)", runtime)
        self.assertIn("function finishWorkflowSideSheetResize(event)", runtime)
        self.assertIn("initializeWorkflowSideSheetResize();", runtime)

    def test_route_dispatcher_uses_registered_module_routes(self) -> None:
        dispatcher = build_route_dispatcher(build_module_registry())

        match = dispatcher.match("GET", "/api/health")

        self.assertIsNotNone(match)
        self.assertEqual(match.owner, "core")
        self.assertEqual(match.handler_name, "health")
        self.assertTrue(callable(match.handler))

    def test_all_registered_routes_have_executable_handlers(self) -> None:
        modules = build_module_registry()
        workflows = build_workflow_registry(modules)

        dispatcher = build_route_dispatcher(modules, workflows)

        for module in modules.values():
            for route in module.routes:
                match = dispatcher.match(route.method, route.path)
                self.assertIsNotNone(match)
                self.assertTrue(callable(match.handler))
        for workflow in workflows.values():
            for route in workflow.routes:
                match = dispatcher.match(route.method, route.path)
                self.assertIsNotNone(match)
                self.assertTrue(callable(match.handler))

    def test_workflow_registry_binds_executable_controller(self) -> None:
        class SampleController:
            workflow_id = "sample"

            def __init__(self, services: ServiceServices) -> None:
                self.services = services

        dependency = object()
        services = ServiceServices(
            contexts=dependency,
            sessions=dependency,
            files=dependency,
            workflows=dependency,
        )
        definition = WorkflowDefinition(
            id="sample",
            label="Sample",
            modules=("core",),
            stages=(WorkflowStage("project", "Project", None),),
            project_kinds=("sample",),
            backend_package="sample",
            frontend_bundle="workflows/sample.js",
            controller_factory=SampleController,
        )
        registry = build_workflow_registry(
            build_module_registry(),
            (definition,),
        )

        controllers = registry.create_controllers(services)

        self.assertEqual(set(controllers), {"sample"})
        self.assertIs(controllers["sample"].services, services)

    def test_workflow_registry_rejects_mismatched_controller(self) -> None:
        class WrongController:
            workflow_id = "wrong"

            def __init__(self, services: ServiceServices) -> None:
                self.services = services

        definition = WorkflowDefinition(
            id="sample",
            label="Sample",
            modules=("core",),
            stages=(WorkflowStage("project", "Project", None),),
            project_kinds=("sample",),
            backend_package="sample",
            frontend_bundle="workflows/sample.js",
            controller_factory=WrongController,
        )
        registry = build_workflow_registry(
            build_module_registry(),
            (definition,),
        )

        with self.assertRaisesRegex(ValueError, "controller id"):
            registry.create_controllers(
                ServiceServices(
                    contexts=object(),
                    sessions=object(),
                    files=object(),
                    workflows=object(),
                )
            )

    def test_configured_workflow_endpoint_persists_extra_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "service"
            plugin_dir = Path(tmp) / "plugins"
            root.mkdir()
            plugin_dir.mkdir()
            (plugin_dir / "sample_workflow.py").write_text(
                "\n".join(
                    [
                        "from electroboy.service.registry import WorkflowDefinition",
                        "from electroboy.service.registry import WorkflowStage",
                        "",
                        "class SampleController:",
                        "    workflow_id = 'sample-workflow'",
                        "",
                        "    def __init__(self, runtime):",
                        "        self.runtime = runtime",
                        "",
                        "def workflow():",
                        "    return WorkflowDefinition(",
                        "        id='sample-workflow',",
                        "        label='Sample Workflow',",
                        "        modules=('core',),",
                        "        stages=(WorkflowStage('project', 'Project', None),),",
                        "        project_kinds=('sample',),",
                        "        backend_package='sample_workflow',",
                        "        frontend_bundle='workflows/sample.js',",
                        "        controller_factory=SampleController,",
                        "    )",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            sys.path.insert(0, str(plugin_dir))
            try:
                try:
                    server = create_server(root, port=0)
                except PermissionError as error:
                    self.skipTest(f"local socket creation is not permitted: {error}")
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    status, body, content_type = post_json(
                        server,
                        "/api/workflows/config/workflows",
                        {
                            "id": "sample-workflow",
                            "factory": "sample_workflow:workflow",
                        },
                    )
                    registry_status, registry_body, _registry_type = request(
                        server,
                        "/api/registry",
                    )
                    config_path = root / ".electroboy" / "service" / "workflows.json"
                    config_exists = config_path.exists()
                    controller_ids = set(server.service_state.workflow_controllers)
                finally:
                    server.shutdown()
                    thread.join(timeout=2)
                    server.server_close()
            finally:
                sys.path.remove(str(plugin_dir))

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        payload = json.loads(body)
        self.assertEqual(payload["status"], "added")
        self.assertEqual(registry_status, 200)
        registry = json.loads(registry_body)
        workflows = {entry["id"]: entry for entry in registry["workflows"]}
        self.assertIn("software", workflows)
        self.assertIn("creative-writing", workflows)
        self.assertIn("sample-workflow", workflows)
        self.assertNotIn("sample-workflow", controller_ids)
        self.assertTrue(config_exists)

    def test_service_state_creates_and_closes_workflow_controller_lazily(self) -> None:
        created: list[object] = []

        class SampleController:
            workflow_id = "sample"

            def __init__(self, _services: ServiceServices) -> None:
                self.closed = False
                created.append(self)

            def close(self) -> None:
                self.closed = True

        definition = WorkflowDefinition(
            id="sample",
            label="Sample",
            modules=("core",),
            stages=(WorkflowStage("project", "Project", None),),
            project_kinds=("sample",),
            backend_package="sample",
            frontend_bundle="workflows/sample.js",
            controller_factory=SampleController,
        )
        registry = build_workflow_registry(build_module_registry(), (definition,))

        with tempfile.TemporaryDirectory() as tmp:
            state = ServiceState(Path(tmp), workflow_registry=registry)
            self.assertEqual(created, [])

            first = state.workflow_controller("sample")
            second = state.workflow_controller("sample")
            state.close_workflow_controllers()

        self.assertIs(first, second)
        self.assertEqual(created, [first])
        self.assertTrue(first.closed)

    def test_splash_image_endpoint_serves_packaged_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type, headers = request_bytes(
                    server,
                    SPLASH_IMAGE_ROUTE,
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "image/png")
        self.assertEqual(body, splash_image_bytes())
        self.assertEqual(headers["Content-Length"], str(len(body)))

    def test_service_asset_endpoint_serves_extracted_frontend_files(self) -> None:
        self.assertIn("/assets/service/css/shell.css", INDEX_HTML)
        self.assertIn("/assets/service/css/pane-tools.css", INDEX_HTML)
        self.assertIn("/assets/service/js/core/pane-layout-drag.js", INDEX_HTML)
        self.assertIn("/assets/service/js/core/input-shortcut.js", INDEX_HTML)
        self.assertIn("/assets/service/js/core/pane-sync.js", INDEX_HTML)
        self.assertIn("/assets/service/js/core/pane-tools.js", INDEX_HTML)
        self.assertIn("/assets/service/js/core/terminal-behavior.js", INDEX_HTML)
        self.assertIn("/assets/service/js/core/runtime.js", INDEX_HTML)
        self.assertIn('id="artifactPaneToolsToggle"', INDEX_HTML)
        self.assertIn('id="artifactPaneToolsShelf"', INDEX_HTML)
        self.assertIn('id="artifactPaneToolsResizeHandle"', INDEX_HTML)
        self.assertIn('id="artifactPaneToolsContent"', INDEX_HTML)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                css_status, css_body, css_type, _css_headers = request_bytes(
                    server,
                    "/assets/service/css/shell.css",
                )
                pane_css_status, pane_css_body, pane_css_type, _ = request_bytes(
                    server,
                    "/assets/service/css/pane-tools.css",
                )
                js_status, js_body, js_type, _js_headers = request_bytes(
                    server,
                    "/assets/service/js/core/runtime.js",
                )
                registry_status, registry_body, registry_type, _registry_headers = (
                    request_bytes(
                        server,
                        "/assets/service/js/core/registry.js",
                    )
                )
                drag_status, drag_body, drag_type, _drag_headers = request_bytes(
                    server,
                    "/assets/service/js/core/pane-layout-drag.js",
                )
                workspace_status, workspace_body, workspace_type, _ = request_bytes(
                    server,
                    "/assets/service/js/core/pane-workspace.js",
                )
                shortcut_status, shortcut_body, shortcut_type, _shortcut_headers = (
                    request_bytes(
                        server,
                        "/assets/service/js/core/input-shortcut.js",
                    )
                )
                sync_status, sync_body, sync_type, _sync_headers = request_bytes(
                    server,
                    "/assets/service/js/core/pane-sync.js",
                )
                tools_status, tools_body, tools_type, _tools_headers = request_bytes(
                    server,
                    "/assets/service/js/core/pane-tools.js",
                )
                (
                    terminal_behavior_status,
                    terminal_behavior_body,
                    terminal_behavior_type,
                    _,
                ) = request_bytes(
                    server,
                    "/assets/service/js/core/terminal-behavior.js",
                )
                file_tools_status, file_tools_body, file_tools_type, _ = request_bytes(
                    server,
                    "/assets/service/js/modules/file-pane-tools.js",
                )
                software_status, software_body, software_type, _software_headers = (
                    request_bytes(
                        server,
                        "/assets/service/js/workflows/software.js",
                    )
                )
                software_css_status, software_css_body, software_css_type, _ = (
                    request_bytes(
                        server,
                        "/assets/service/css/workflows/software.css",
                    )
                )
                creative_status, creative_body, creative_type, _creative_headers = (
                    request_bytes(
                        server,
                        "/assets/service/js/workflows/creative-writing.js",
                    )
                )
                creative_css_status, creative_css_body, creative_css_type, _ = (
                    request_bytes(
                        server,
                        "/assets/service/css/workflows/creative-writing.css",
                    )
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(css_status, 200)
        self.assertEqual(css_type, "text/css; charset=utf-8")
        self.assertIn(b":root", css_body)
        self.assertEqual(pane_css_status, 200)
        self.assertEqual(pane_css_type, "text/css; charset=utf-8")
        self.assertIn(b".pane-tool-menu", pane_css_body)
        self.assertIn(b"top: 44px", pane_css_body)
        self.assertIn(b"font-size: 10px", pane_css_body)
        self.assertIn(b"font-weight: 400", pane_css_body)
        self.assertEqual(js_status, 200)
        self.assertEqual(js_type, "application/javascript; charset=utf-8")
        self.assertIn(b"async function initialize()", js_body)
        self.assertNotIn(CREATIVE_SPLASH_IMAGE_ROUTE.encode("utf-8"), js_body)
        self.assertNotIn(b"__CREATIVE_SPLASH_IMAGE_ROUTE__", js_body)
        self.assertEqual(registry_status, 200)
        self.assertEqual(registry_type, "application/javascript; charset=utf-8")
        self.assertIn(b"registerWorkflow", registry_body)
        self.assertEqual(drag_status, 200)
        self.assertEqual(drag_type, "application/javascript; charset=utf-8")
        self.assertIn(b"function createController(options)", drag_body)
        self.assertIn(b"event.ctrlKey", drag_body)
        self.assertNotIn(b"pane-layout-shift-ready", drag_body)
        self.assertIn(b"pane-layout-ctrl-ready", drag_body)
        self.assertIn(b"options.onDetach", drag_body)
        self.assertIn(b"options.canDetach !== false", drag_body)
        self.assertEqual(workspace_status, 200)
        self.assertEqual(workspace_type, "application/javascript; charset=utf-8")
        self.assertIn(b"function createWorkspace(options)", workspace_body)
        self.assertIn(b"function startCornerSplit(", workspace_body)
        self.assertEqual(shortcut_status, 200)
        self.assertEqual(shortcut_type, "application/javascript; charset=utf-8")
        self.assertIn(b"function bindRecorder(button)", shortcut_body)
        self.assertIn(b"Shift", shortcut_body)
        self.assertEqual(sync_status, 200)
        self.assertEqual(sync_type, "application/javascript; charset=utf-8")
        self.assertIn(b"function connect(options = {})", sync_body)
        self.assertEqual(tools_status, 200)
        self.assertEqual(tools_type, "application/javascript; charset=utf-8")
        self.assertIn(b"function addSection(id, label", tools_body)
        self.assertEqual(terminal_behavior_status, 200)
        self.assertEqual(
            terminal_behavior_type,
            "application/javascript; charset=utf-8",
        )
        self.assertIn(b"window.ElectroBoyTerminalBehavior", terminal_behavior_body)
        self.assertEqual(file_tools_status, 200)
        self.assertEqual(file_tools_type, "application/javascript; charset=utf-8")
        self.assertIn(b"window.ElectroBoyFilePaneTools", file_tools_body)
        self.assertEqual(software_status, 200)
        self.assertEqual(software_type, "application/javascript; charset=utf-8")
        self.assertIn(b"Software engineering", software_body)
        self.assertEqual(software_css_status, 200)
        self.assertEqual(software_css_type, "text/css; charset=utf-8")
        self.assertIn(b".ad-hoc-session-dialog", software_css_body)
        self.assertEqual(creative_status, 200)
        self.assertEqual(creative_type, "application/javascript; charset=utf-8")
        self.assertIn(CREATIVE_SPLASH_IMAGE_ROUTE.encode("utf-8"), creative_body)
        self.assertNotIn(b"__CREATIVE_SPLASH_IMAGE_ROUTE__", creative_body)
        self.assertEqual(creative_css_status, 200)
        self.assertEqual(creative_css_type, "text/css; charset=utf-8")
        self.assertIn(b".creative-binder", creative_css_body)

    def test_creative_splash_image_endpoint_serves_packaged_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type, headers = request_bytes(
                    server,
                    CREATIVE_SPLASH_IMAGE_ROUTE,
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "image/png")
        self.assertEqual(
            body,
            splash_image_bytes("electroboy-splash-creative-writing-16x9.png"),
        )
        self.assertEqual(headers["Content-Length"], str(len(body)))

    def test_pane_window_endpoint_serves_stripped_down_pane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = request(server, "/pane/agent")
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn('const PANE_KIND = "agent";', body)
        self.assertIn("Dock", body)
        self.assertIn("xterm@5.3.0", body)
        self.assertNotIn("__PANE_KIND__", body)

    def test_pane_window_supports_persistent_split_workspaces(self) -> None:
        page = pane_window_html("agent")
        workspace = read_service_text_asset("js/core/pane-workspace.js")

        self.assertIn('id="workspaceWindow"', page)
        self.assertIn('id="workspaceLayout"', page)
        self.assertIn('id="resetWorkspace"', page)
        self.assertIn('id="dockWorkspace"', page)
        self.assertIn('params.get("embedded") === "1"', page)
        self.assertIn("ElectroBoyPaneWorkspace.create", page)
        self.assertIn("electroboy.paneWorkspaceLayout.v2.${PANE_KIND}", page)
        self.assertIn('/assets/service/js/core/pane-workspace.js', page)
        self.assertIn('/assets/service/js/core/pane-sync.js', page)
        self.assertIn('/assets/service/js/core/pane-tools.js', page)
        self.assertIn('/assets/service/css/pane-tools.css', page)
        self.assertIn('/assets/service/js/modules/file-pane-tools.js', page)
        self.assertIn('paneParameters.set("embedded", "1")', page)
        self.assertIn('function initialPaneWorkspaceLayout()', page)
        self.assertIn('first: { type: "leaf", kind: "agent" }', page)
        self.assertIn('second: { type: "leaf", kind: "input" }', page)
        self.assertIn('initialLayout: initialPaneWorkspaceLayout()', page)
        self.assertIn('function splitLeaf(', workspace)
        self.assertIn('function startCornerSplit(', workspace)
        self.assertIn('function startResize(', workspace)
        self.assertIn('function moveLeaf(', workspace)
        self.assertIn('item.kind = kind;', workspace)
        self.assertIn('const paneFrames = new Map();', workspace)
        self.assertIn('const existing = { ...item };', workspace)
        self.assertIn('canDetach: false', workspace)
        self.assertIn('if (EMBEDDED_PANE) {\n        return;\n      }', page)
        self.assertNotIn(
            'dockPane.addEventListener("click", restorePoppedPane);',
            page,
        )
        self.assertIn(
            '["scratch", "progress", "status", "input"].includes(PANE_KIND)',
            page,
        )
        self.assertIn("function initializeSharedPaneSync()", page)
        self.assertIn("function renderSharedProgressState(", page)
        self.assertIn("function applySharedAgentInputState(", page)

    def test_pane_window_html_includes_reconnect_streams(self) -> None:
        page = pane_window_html("artifact")

        self.assertIn("__PANE_KIND__", PANE_WINDOW_HTML)
        self.assertIn('const PANE_KIND = "artifact";', page)
        self.assertIn('contextUrl("/api/artifacts/events?artifact=requirements")', page)
        self.assertIn('params.get("document_path")', page)
        self.assertIn('params.get("document_zoom")', page)
        self.assertIn('params.get("folder_path")', page)
        self.assertIn('params.get("corkboard_path")', page)
        self.assertIn('params.get("corkboard_id")', page)
        self.assertIn('params.get("corkboard_provider")', page)
        self.assertIn('id="artifactZoomControls"', page)
        self.assertIn('id="paneToolsToggle"', page)
        self.assertIn('id="paneToolsShelf"', page)
        self.assertIn('id="paneToolsResizeHandle"', page)
        self.assertIn('id="paneToolsContent"', page)
        self.assertIn("ElectroBoyPaneTools.create", page)
        self.assertIn("ElectroBoyFilePaneTools.mount", page)
        self.assertIn('id="dockPane"', page)
        self.assertIn('id="refreshArtifact"', page)
        self.assertIn('id="previewArtifact"', page)
        self.assertIn('id="editArtifact"', page)
        self.assertIn('id="exportPaneFormat"', page)
        self.assertIn('id="exportPaneOutput"', page)
        self.assertIn(".artifact-frame.loading", page)
        self.assertIn(".artifact-frame.loading {\n      opacity: 1;", page)
        self.assertIn("function applyArtifactItem(item)", page)
        self.assertIn("function syncArtifactUrlState()", page)
        self.assertIn("function reconnectArtifactStream()", page)
        self.assertIn('data.type === "electroboy:pane-set-artifact"', page)
        self.assertIn("function artifactEventUrl()", page)
        self.assertIn("function artifactEditUrl()", page)
        self.assertIn("function setArtifactEditMode(editing)", page)
        self.assertIn('artifactFrame.classList.add("loading");', page)
        self.assertIn('artifactFrame.addEventListener("load"', page)
        self.assertIn("let directPaneActivationNotifier = null;", page)
        self.assertIn("function bindArtifactFrameActivation()", page)
        self.assertIn("artifactFrame.contentDocument", page)
        self.assertIn(
            'frameDocument.addEventListener("pointerdown", notifyPaneActivated, true);',
            page,
        )
        self.assertIn(
            'frameDocument.addEventListener("focusin", notifyPaneActivated, true);',
            page,
        )
        self.assertIn("function artifactEditorFontSize()", page)
        self.assertIn("function postArtifactEditorFontSize()", page)
        self.assertIn('type: "electroboy-editor-font-size"', page)
        self.assertIn('artifactKind === "creative-corkboard"', page)
        self.assertIn("/artifacts/corkboard", page)
        self.assertIn("function updateSelectOptions(select, options", page)
        self.assertIn("function fileSwitcherPlaceholderLabel()", page)
        self.assertIn('return artifactCorkboardTitle || artifactFolderTitle || artifactCorkboardId', page)
        file_switcher_start = page.index("function renderFileSwitcher()")
        file_switcher_end = page.index("function fileSwitcherPlaceholderLabel()", file_switcher_start)
        file_switcher_source = page[file_switcher_start:file_switcher_end]
        self.assertIn("updateSelectOptions(", file_switcher_source)
        self.assertIn('label: placeholderLabel || "Choose file"', file_switcher_source)
        self.assertNotIn("replaceChildren", file_switcher_source)
        self.assertIn(
            'if (artifactKind === "document" && files.length > 0 && !contentSwitcher.value)',
            page,
        )
        self.assertIn("path: artifactTargetPath()", page)
        self.assertIn("title: artifactTargetTitle()", page)
        self.assertIn("editing: artifactEditing", page)
        self.assertIn(
            'if (!contentSwitcher.value) {\n'
            "          return;\n"
            "        }\n"
            "        selectFileTarget(",
            page,
        )
        self.assertIn("function artifactDocumentExportUrl(format)", page)
        self.assertIn('parameters.set("artifact", "document")', page)
        self.assertIn('parameters.set("font_size", String(artifactEditorFontSize()))', page)
        self.assertIn('parameters.set("artifact", "route")', page)
        self.assertIn("function changeArtifactZoom(delta)", page)
        self.assertIn("function exportBlob(url, suggestedName, format = \"markdown\")", page)
        self.assertIn("function exportMarkdown(url, suggestedName)", page)
        self.assertIn("function exportCurrentPaneOutput()", page)
        self.assertIn("exportPaneFormat.hidden = PANE_KIND !== \"artifact\";", page)
        self.assertIn("exportPaneOutput.hidden = !canExportPaneOutput();", page)
        self.assertIn("previewArtifactButton.hidden = isProviderView;", page)
        self.assertIn("editArtifactButton.hidden = isProviderView;", page)
        self.assertIn('artifactKind === "agenda"', page)
        self.assertIn('params.get("agenda_provider")', page)
        self.assertIn('exportPaneOutput.addEventListener("click"', page)
        self.assertIn("function terminalKeyForInputEvent(event)", PANE_WINDOW_HTML)
        self.assertIn('id="agentSendShortcut"', PANE_WINDOW_HTML)
        self.assertIn("ElectroBoyInputShortcut.bindRecorder", PANE_WINDOW_HTML)
        self.assertIn("shortcutController.matches(event)", PANE_WINDOW_HTML)
        self.assertNotIn("isEnter && event.shiftKey", PANE_WINDOW_HTML)
        self.assertLess(
            PANE_WINDOW_HTML.index('event.key === "Escape"'),
            PANE_WINDOW_HTML.index("if (agentInput.value.length > 0)"),
        )
        self.assertIn('const PANE_FONT_OFFSET_STORAGE_PREFIX = "electroboy.paneFontOffset.";', PANE_WINDOW_HTML)
        self.assertIn('params.get("font_pane")', PANE_WINDOW_HTML)
        self.assertIn("let terminalResizeObserver = null;", PANE_WINDOW_HTML)
        self.assertIn("function observeTerminalPaneResize()", PANE_WINDOW_HTML)
        self.assertIn("terminalResizeObserver.observe(terminalHost);", PANE_WINDOW_HTML)
        self.assertIn(
            "ElectroBoyTerminalBehavior.fit(terminal, terminalFit)",
            PANE_WINDOW_HTML,
        )
        self.assertIn("ElectroBoyTerminalBehavior.install(terminal)", PANE_WINDOW_HTML)
        self.assertIn("queueAgentResize(cols, rows);", PANE_WINDOW_HTML)
        self.assertIn('contextUrl("/api/sessions/resize")', PANE_WINDOW_HTML)
        self.assertIn("session_id: selectedSessionId,", PANE_WINDOW_HTML)
        self.assertIn(".terminal-host .xterm {\n      width: 100%;", PANE_WINDOW_HTML)
        self.assertIn("function effectiveFontSize()", PANE_WINDOW_HTML)
        self.assertIn("function resetFontSize()", PANE_WINDOW_HTML)
        self.assertIn('contextUrl("/api/sessions/key")', PANE_WINDOW_HTML)
        self.assertIn('contextUrl("/api/sessions/raw")', PANE_WINDOW_HTML)
        self.assertIn("let slashCommandMode = false;", PANE_WINDOW_HTML)
        self.assertIn("let terminalInputQueue = Promise.resolve();", PANE_WINDOW_HTML)
        self.assertIn("function queueTerminalInput(task)", PANE_WINDOW_HTML)
        self.assertIn("function handleSlashCommandInput(event)", PANE_WINDOW_HTML)
        self.assertIn("if (slashCommandMode) {\n        sendTerminalKey(\"enter\");", PANE_WINDOW_HTML)
        self.assertIn('event.key === "/"', PANE_WINDOW_HTML)
        self.assertIn("sendTerminalRaw(event.key);", PANE_WINDOW_HTML)
        self.assertIn('if (slashKey === "enter" || slashKey === "escape")', PANE_WINDOW_HTML)
        self.assertIn('if (event.key === "Backspace") return "backspace";', PANE_WINDOW_HTML)
        self.assertIn('if (event.key === "Delete") return "delete";', PANE_WINDOW_HTML)
        self.assertIn('id="decreasePaneFont"', PANE_WINDOW_HTML)
        self.assertIn('id="resetPaneFont"', PANE_WINDOW_HTML)
        self.assertIn('id="increasePaneFont"', PANE_WINDOW_HTML)
        self.assertIn('id="paneContentControl" class="pane-content-control" hidden', PANE_WINDOW_HTML)
        self.assertIn('id="paneContentLabel" for="contentSwitcher">Content</label>', PANE_WINDOW_HTML)
        self.assertIn('id="contentSwitcher"', PANE_WINDOW_HTML)
        self.assertLess(
            PANE_WINDOW_HTML.index('id="contentSwitcher"'),
            PANE_WINDOW_HTML.index('id="terminalHost"'),
        )
        self.assertIn('paneContentLabel.textContent = "Agent";', PANE_WINDOW_HTML)
        self.assertIn('paneContentLabel.textContent = "File";', PANE_WINDOW_HTML)
        self.assertIn('paneContentLabel.textContent = "Shell";', PANE_WINDOW_HTML)
        self.assertIn("function updateSelectOptions(select, options", PANE_WINDOW_HTML)
        self.assertIn("function renderFileSwitcher()", PANE_WINDOW_HTML)
        self.assertIn("function renderShellSwitcher()", PANE_WINDOW_HTML)
        shell_switcher_start = PANE_WINDOW_HTML.index("function renderShellSwitcher()")
        shell_switcher_end = PANE_WINDOW_HTML.index(
            "async function refreshShellSessions()",
            shell_switcher_start,
        )
        shell_switcher_source = PANE_WINDOW_HTML[
            shell_switcher_start:shell_switcher_end
        ]
        self.assertIn("updateSelectOptions(", shell_switcher_source)
        self.assertNotIn("replaceChildren", shell_switcher_source)
        self.assertIn('contextUrl("/api/shell/sessions")', PANE_WINDOW_HTML)
        self.assertIn('{ id: "artifact", label: "File" }', PANE_WINDOW_HTML)
        self.assertIn('id="interruptAgent" class="input-interrupt"', PANE_WINDOW_HTML)
        self.assertIn('id="linkAgentFile" class="input-link"', PANE_WINDOW_HTML)
        self.assertIn("background: #3a1d1a;", PANE_WINDOW_HTML)
        self.assertIn("background: #12303b;", PANE_WINDOW_HTML)
        self.assertIn("grid-template-rows: repeat(3, 42px);", PANE_WINDOW_HTML)
        self.assertIn(".input-actions button {\n      height: 42px;", PANE_WINDOW_HTML)
        self.assertIn("align-content: start;\n      gap: 10px;", PANE_WINDOW_HTML)
        self.assertNotIn('id="sendAgentInput"', PANE_WINDOW_HTML)
        self.assertLess(
            PANE_WINDOW_HTML.index('id="agentInput"'),
            PANE_WINDOW_HTML.index('id="interruptAgent"'),
        )
        self.assertLess(
            PANE_WINDOW_HTML.index('id="linkAgentFile"'),
            PANE_WINDOW_HTML.index('id="agentSendShortcut"'),
        )
        self.assertIn("function openLinkFileBrowser()", PANE_WINDOW_HTML)
        self.assertIn('data.mode === "link"', PANE_WINDOW_HTML)
        self.assertIn("function refreshSessions()", PANE_WINDOW_HTML)
        self.assertIn("function selectAgentSession(sessionId)", PANE_WINDOW_HTML)
        self.assertIn("function scratchPadStorageKey()", PANE_WINDOW_HTML)
        self.assertIn("`${SCRATCH_PAD_STORAGE_KEY}.${contextId}`", PANE_WINDOW_HTML)
        self.assertIn("window.localStorage.getItem(storageKey)", PANE_WINDOW_HTML)
        self.assertIn("window.localStorage.setItem(activeStorageKey", PANE_WINDOW_HTML)
        self.assertIn(
            'PANE_KIND === "scratch" && event.key === scratchPadStorageKey()',
            PANE_WINDOW_HTML,
        )
        self.assertIn(
            '<textarea id="scratchPad" class="scratch-pad" spellcheck="true" hidden>',
            PANE_WINDOW_HTML,
        )
        self.assertIn(
            '<textarea id="agentInput" class="input-text" spellcheck="true">',
            PANE_WINDOW_HTML,
        )
        self.assertIn('contextUrl("/api/project")', PANE_WINDOW_HTML)
        self.assertIn('contextUrl("/api/sessions/select")', PANE_WINDOW_HTML)
        self.assertIn('if (kind === "shell") return "Project shell";', PANE_WINDOW_HTML)
        self.assertIn("function connectShellStream()", PANE_WINDOW_HTML)
        self.assertIn('shellContextUrl("/api/shell/events")', PANE_WINDOW_HTML)
        self.assertIn('shellContextUrl("/api/shell/input")', PANE_WINDOW_HTML)
        self.assertIn('shellContextUrl("/api/shell/resize")', PANE_WINDOW_HTML)
        self.assertIn('params.get("shell_session_id")', PANE_WINDOW_HTML)
        self.assertIn("function stopDisposableShell()", PANE_WINDOW_HTML)
        self.assertIn('contextUrl("/api/shell/stop")', PANE_WINDOW_HTML)
        self.assertIn('stopUrl.searchParams.set("session_id", ownedShellSessionId)', PANE_WINDOW_HTML)
        self.assertIn("dockWorkspace.hidden = true", PANE_WINDOW_HTML)
        self.assertIn('if (kind === "input") return "AI agent input";', PANE_WINDOW_HTML)
        self.assertIn(
            'sandbox="allow-scripts allow-popups allow-modals allow-same-origin"',
            page,
        )
        self.assertIn('contextUrl(`/artifacts/document?${parameters.toString()}`)', page)
        self.assertIn('contextUrl("/api/progress/events")', page)
        self.assertIn('contextUrl("/api/sessions/message")', page)
        self.assertIn('contextUrl("/api/sessions/raw")', page)

    def test_session_events_markdown_exports_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = AgentSession(
                command=["codex", "exec", "hello"],
                cwd=tmp,
                label="requirements agent",
                kind="requirements",
                interactive=True,
            )
            session._append_event({"type": "system", "text": "started: codex"})
            session._append_event({"type": "output", "text": "hello\n"})
            session._append_event({"type": "output", "text": "world\n"})
            session._append_event({"type": "completed", "returncode": 0})

            markdown = _session_events_markdown(session)

        self.assertIn("# Agent Session Export", markdown)
        self.assertIn(f"- Session id: `{session.session_id}`", markdown)
        self.assertIn("- Kind: `requirements`", markdown)
        self.assertIn("```console\ncodex exec hello\n```", markdown)
        self.assertIn("### Output Events 2-3", markdown)
        self.assertIn("hello\nworld", markdown)
        self.assertIn("### Event 4: completed", markdown)
        self.assertIn("- Return code: `0`", markdown)

    def test_progress_snapshot_markdown_exports_snapshot(self) -> None:
        markdown = _progress_snapshot_markdown(Path("/tmp/project"), "phase 1\n", True)

        self.assertIn("# Progress Log Export", markdown)
        self.assertIn("- Project root: `/tmp/project`", markdown)
        self.assertIn("- Snapshot status: `ok`", markdown)
        self.assertIn("```text\nphase 1\n```", markdown)

    def test_file_browser_window_html_includes_tree_picker_controls(self) -> None:
        page = file_browser_window_html("~/ORNL")

        self.assertIn("ElectroBoy File Browser", page)
        self.assertIn("__INITIAL_PATH__", FILE_BROWSER_WINDOW_HTML)
        self.assertIn('const INITIAL_PATH = "~/ORNL";', page)
        self.assertIn('const SELECT_MODE = "project";', page)
        self.assertIn("grid-template-rows: auto auto auto minmax(0, 1fr) auto;", page)
        self.assertIn("height: 100vh;", page)
        self.assertIn("overflow: hidden;", page)
        self.assertIn('id="pathInput"', page)
        self.assertIn('id="searchInput"', page)
        self.assertIn('id="showHidden"', page)
        self.assertIn('id="breadcrumbs"', page)
        self.assertIn('id="fileTree"', page)
        self.assertIn("function toggleDirectory(entry)", page)
        self.assertIn("function renderBreadcrumbs()", page)
        self.assertIn("function moveSelection(delta)", page)
        self.assertIn(
            'new URLSearchParams(window.location.search).get("project_action")',
            page,
        )
        self.assertIn('event.key === "ArrowRight"', page)
        self.assertIn('event.key === "ArrowLeft"', page)
        self.assertIn("window.opener.postMessage", page)
        self.assertIn("electroboy-file-browser-select", page)
        self.assertIn("project_action: PROJECT_ACTION", page)
        self.assertIn('PROJECT_ACTION === "meta-add"', page)
        self.assertIn("Add repository", page)
        self.assertIn("Activate", page)
        self.assertIn("Cancel", page)
        self.assertIn("<svg viewBox=", page)

    def test_file_browser_window_html_supports_link_selection_mode(self) -> None:
        page = file_browser_window_html("~/ORNL", mode="link")

        self.assertIn('const SELECT_MODE = "link";', page)
        self.assertIn("Insert selected file", page)
        self.assertIn("Select a file first.", page)
        self.assertIn("mode: SELECT_MODE", page)

    def test_file_browser_window_html_supports_document_selection_mode(self) -> None:
        page = file_browser_window_html("~/ORNL", mode="document")

        self.assertIn('const SELECT_MODE = "document";', page)
        self.assertIn("Open selected document", page)
        self.assertIn("Select a Markdown file first.", page)
        self.assertIn(
            'SELECT_MODE === "document" || SELECT_MODE === "document-new"',
            page,
        )

    def test_file_browser_window_html_supports_new_document_mode(self) -> None:
        page = file_browser_window_html("~/ORNL", mode="document-new")

        self.assertIn('const SELECT_MODE = "document-new";', page)
        self.assertIn('id="newDocumentName"', page)
        self.assertIn("Create or open document", page)
        self.assertIn("function documentNewTargetPath()", page)
        self.assertIn("Select a Markdown file or choose a directory and name.", page)
        self.assertIn(
            'SELECT_MODE === "document-new" && selectedType === "directory"',
            page,
        )
        self.assertIn(
            "function documentNewTargetPath() {\n"
            '      if (SELECT_MODE !== "document-new" || selectedType !== "directory") {\n'
            '        return "";\n'
            "      }\n"
            '      const raw = newDocumentName.value.trim().replace(/\\\\+/g, "/");\n'
            "      if (!raw) {\n"
            '        return "";\n'
            "      }",
            page,
        )

    def test_file_browser_window_html_supports_new_project_mode(self) -> None:
        page = file_browser_window_html("~/ORNL", mode="project-new")

        self.assertIn('const SELECT_MODE = "project-new";', page)
        self.assertIn('id="newDocumentName"', page)
        self.assertIn("Create or activate project", page)
        self.assertIn("function projectNewTargetPath()", page)
        self.assertIn(
            "Select a project directory or enter a new folder name.",
            page,
        )
        self.assertIn('"Optional new project folder name"', page)
        self.assertIn(
            'return selectedType === "directory";',
            page,
        )
        self.assertIn(
            "function projectNewTargetPath() {\n"
            '      if (SELECT_MODE !== "project-new" || selectedType !== "directory") {\n'
            '        return "";\n'
            "      }\n"
            '      const raw = newDocumentName.value.trim().replace(/\\\\+/g, "/");\n'
            "      if (!raw) {\n"
            "        return selectedPath;\n"
            "      }",
            page,
        )

    def test_file_browser_endpoint_serves_popout_picker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = request(
                    server,
                    "/file-browser?path=%2Ftmp",
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn('const INITIAL_PATH = "/tmp";', body)
        self.assertIn("Activate", body)
        self.assertIn('const SELECT_MODE = "project";', body)

    def test_file_browser_endpoint_serves_link_picker_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = request(
                    server,
                    "/file-browser?path=%2Ftmp&mode=link",
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn('const SELECT_MODE = "link";', body)
        self.assertIn("Insert selected file", body)

    def test_file_browser_endpoint_serves_document_picker_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = request(
                    server,
                    "/file-browser?path=%2Ftmp&mode=document",
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn('const SELECT_MODE = "document";', body)
        self.assertIn("Open selected document", body)

    def test_file_browser_endpoint_serves_new_document_picker_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = request(
                    server,
                    "/file-browser?path=%2Ftmp&mode=document-new",
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn('const SELECT_MODE = "document-new";', body)
        self.assertIn("Create or open document", body)

    def test_file_browser_endpoint_serves_new_project_picker_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = request(
                    server,
                    "/file-browser?path=%2Ftmp&mode=project-new",
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn('const SELECT_MODE = "project-new";', body)
        self.assertIn("Create or activate project", body)

    def test_document_target_renderer_creates_markdown_starter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            page, status = document_target_html(
                root,
                "docs/guide.md",
                title="Guide",
                embedded=True,
                create_missing=True,
            )

            target = root / "docs" / "guide.md"
            self.assertTrue(target.exists())
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "# Guide\n\n## Overview\n\n## Notes\n",
            )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("<title>Guide</title>", page)
        self.assertIn("<h1>Guide</h1>", page)
        self.assertIn("<h2>Overview</h2>", page)
        self.assertIn("--doc-bg: #10141f;", page)
        self.assertIn("--doc-text: #e7edf7;", page)
        self.assertIn("article, article :where", page)
        self.assertIn("--doc-surface: #10141f;", page)

    def test_document_target_renderer_seeds_blank_existing_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "README.md"
            target.write_text("\n", encoding="utf-8")

            page, status = document_target_html(
                root,
                "README.md",
                create_missing=True,
            )

            self.assertEqual(status, HTTPStatus.OK)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "# README\n\n## Overview\n\n## Notes\n",
            )
            self.assertIn("<h1>README</h1>", page)

    def test_document_target_renderer_accepts_zoom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Project\n", encoding="utf-8")

            page, status = document_target_html(root, "README.md", zoom_percent=130)

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("--doc-font-size: 20.80px;", page)

    def test_document_target_renderer_handles_code_fences_and_mermaid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "README.md"
            target.write_text(
                "# Project\n\n"
                "### Clone the repositories\n\n"
                "```bash\nmkdir -p qhpc\ncd qhpc\n```\n\n"
                "```mermaid\ngraph TD\n  A --> B\n```\n",
                encoding="utf-8",
            )

            page, status = document_target_html(root, "README.md")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("<h3>Clone the repositories</h3>", page)
        self.assertIn('<pre><code class="language-bash">mkdir -p qhpc', page)
        self.assertIn('<div class="mermaid">graph TD', page)
        self.assertIn("mermaid@10", page)
        self.assertIn("function openMermaidPopup(diagram)", page)
        self.assertIn("URL.createObjectURL(new Blob", page)
        self.assertIn("function diagramMarkup(diagram)", page)
        self.assertIn("function initializeDiagramPopup(title)", page)
        self.assertIn("function contentBox(svg)", page)
        self.assertIn("function updateBaseSize()", page)
        self.assertIn("availableWidth / naturalWidth", page)
        self.assertIn('"viewBox"', page)
        self.assertIn('"preserveAspectRatio"', page)
        self.assertIn("window.requestAnimationFrame", page)
        self.assertIn("function startPan(event)", page)
        self.assertIn("viewport.scrollLeft", page)
        self.assertIn('viewport.addEventListener("pointerdown", startPan);', page)
        self.assertIn('securityLevel: "strict"', page)
        self.assertIn('querySelector: ".mermaid"', page)

    def test_document_target_renderer_renders_markdown_inside_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "README.md"
            target.write_text(
                "# Project\n\n"
                "<details id=\"configuration\" closed>\n"
                "<summary><strong>Configuration</strong></summary>\n\n"
                "Intro text.\n\n"
                "| Owner | Configuration | Purpose |\n"
                "| --- | --- | --- |\n"
                "| Site administrator | Site files | Shared infrastructure |\n\n"
                "### Site Configuration\n\n"
                "More text.\n"
                "</details>\n",
                encoding="utf-8",
            )

            page, status = document_target_html(root, "README.md")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn('<details closed="closed" id="configuration">', page)
        self.assertIn("<table>", page)
        self.assertIn("<th>Owner</th>", page)
        self.assertIn("<td>Site administrator</td>", page)
        self.assertIn("<h3>Site Configuration</h3>", page)
        self.assertNotIn("| Owner | Configuration | Purpose |", page)
        self.assertNotIn("### Site Configuration", page)

    def test_document_target_renderer_rejects_unsafe_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with self.assertRaises(StateError):
                document_target_html(root, "../outside.md", create_missing=True)
            with self.assertRaises(StateError):
                document_target_html(root, "docs/guide.txt", create_missing=True)

    def test_artifact_editor_html_imports_markdown_to_structured_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            StateStore(root).init_run(run_id="run-1")
            docs = root / "docs"
            docs.mkdir()
            (docs / "requirements.md").write_text(
                "# Requirements\n\n## REQ-001. Login\n\nMarkdown body.\n",
                encoding="utf-8",
            )

            page, status = artifact_editor_html(
                root,
                "requirements",
                context_id="ctx-1",
            )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn('"mode": "structured"', page)
        self.assertIn('"jsonl_path": "docs/requirements.jsonl"', page)
        self.assertIn("Markdown body", page)
        self.assertIn("/api/artifacts/edit", page)
        self.assertIn('id="recordType"', page)
        self.assertIn('id="saveArtifact"', page)
        self.assertIn("function markDirty()", page)
        self.assertIn('input.addEventListener("input", markDirty);', page)
        self.assertIn('className = "generated-fields"', page)
        self.assertNotIn("function queueSave()", page)

    def test_artifact_editor_markdown_mode_uses_direct_pane_editor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "guide.md").write_text("# Guide\n\nBody.\n", encoding="utf-8")

            page, status = artifact_editor_html(
                root,
                "document",
                "docs/guide.md",
                title="Guide",
            )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn('document.body.classList.add("markdown-mode");', page)
        self.assertIn('textarea.setAttribute("aria-label"', page)
        self.assertIn('id="saveArtifact"', page)
        self.assertIn("body.markdown-mode .editor-header", page)
        self.assertIn("body.markdown-mode .markdown-editor", page)
        self.assertIn('textarea.addEventListener("input", markDirty);', page)
        self.assertNotIn('label.textContent = "Markdown";', page)
        self.assertNotIn("@tiptap/core", page)

    def test_artifact_editor_creative_markdown_mode_uses_tiptap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chapters = root / "chapters"
            chapters.mkdir()
            (chapters / "chapter-01.md").write_text(
                "# Chapter 1\n\nOpening paragraph.\n",
                encoding="utf-8",
            )

            page, status = artifact_editor_html(
                root,
                "document",
                "chapters/chapter-01.md",
                title="Chapter 1",
                rich_editor=True,
                editor_font_size=20,
            )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn('"rich_editor": true', page)
        self.assertIn('"editor_font_size": 20', page)
        self.assertIn("--editor-font-size: 20px;", page)
        self.assertIn("RICH_EDITOR_ENABLED", page)
        self.assertIn("function applyEditorFontSize(value = editorFontSize)", page)
        self.assertIn('data.type === "electroboy-editor-font-size"', page)
        self.assertIn('className = "rich-editor-surface"', page)
        self.assertIn('import("https://esm.sh/@tiptap/core")', page)
        self.assertIn('import("https://esm.sh/@tiptap/markdown")', page)
        self.assertIn("function collectMarkdownDocument()", page)

    def test_save_artifact_edit_writes_jsonl_and_renders_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            StateStore(root).init_run(run_id="run-1")

            result = save_artifact_edit(
                root,
                "requirements",
                "",
                {
                    "mode": "structured",
                    "records": [
                        {
                            "record_type": "document",
                            "title": "Requirements",
                        },
                        {
                            "record_type": "requirement",
                            "id": "REQ-001",
                            "title": "Accept Markdown",
                            "statement": "The editor stores Markdown body text.",
                            "body": (
                                "| Input | Expected |\n"
                                "| --- | --- |\n"
                                "| save | rendered |"
                            ),
                        },
                    ],
                },
            )
            rendered = (root / "docs" / "requirements.md").read_text(
                encoding="utf-8",
            )
            jsonl = (root / "docs" / "requirements.jsonl").read_text(
                encoding="utf-8",
            )

        self.assertEqual(result["status"], "saved")
        self.assertIn("| Input | Expected |", rendered)
        self.assertIn("The editor stores Markdown body text.", rendered)
        self.assertIn('"body": "| Input | Expected |', jsonl)

    def test_save_artifact_edit_rejects_malformed_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            StateStore(root).init_run(run_id="run-1")

            with self.assertRaisesRegex(StateError, "record 1 must be an object"):
                save_artifact_edit(
                    root,
                    "requirements",
                    "",
                    {
                        "mode": "structured",
                        "records": ["not a record object"],
                    },
                )

    def test_artifact_editor_endpoint_serves_active_project_editor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            StateStore(root).init_run(run_id="run-1")
            (root / "docs").mkdir()
            (root / "docs" / "requirements.md").write_text(
                "# Requirements\n",
                encoding="utf-8",
            )
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            payload = server.service_state.create_context()
            context_id = str(payload["context_id"])
            server.service_state.open_project(context_id, str(root))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = request(
                    server,
                    f"/artifacts/edit?context_id={context_id}&artifact=requirements",
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn("Requirements Editor", body)
        self.assertIn('"mode": "structured"', body)

    def test_artifact_editor_endpoint_enables_rich_editor_for_creative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            try:
                server = create_server(service_root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            payload = server.service_state.create_context()
            context_id = str(payload["context_id"])
            server.service_state.create_creative_project(context_id, str(project_root))
            server.service_state.initialize_creative_workspace(context_id)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = request(
                    server,
                    (
                        f"/artifacts/edit?context_id={context_id}"
                        "&artifact=document&path=chapters/chapter-01.md"
                        "&font_size=22"
                    ),
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn('"mode": "markdown"', body)
        self.assertIn('"rich_editor": true', body)
        self.assertIn('"editor_font_size": 22', body)
        self.assertIn("@tiptap/core", body)

    def test_document_export_endpoint_serves_active_project_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "requirements.md").write_text(
                "# Requirements\n\n| ID | Body |\n| --- | --- |\n| REQ-001 | Export docs. |\n",
                encoding="utf-8",
            )
            StateStore(root).init_run(run_id="run-1")
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            payload = server.service_state.create_context()
            context_id = str(payload["context_id"])
            server.service_state.open_project(context_id, str(root))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type, headers = request_bytes(
                    server,
                    (
                        "/api/documents/export"
                        f"?context_id={context_id}&artifact=requirements&format=docx"
                    ),
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"PK"))
        self.assertEqual(
            content_type,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(
            headers.get("Content-Disposition"),
            'attachment; filename="requirements.docx"',
        )

    def test_project_declares_markdown_renderer_dependency(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('"Markdown>=3.6"', pyproject)
        self.assertIn('"reportlab>=4"', pyproject)

    def test_server_close_terminates_context_agent_sessions(self) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.terminated = False

            def is_active(self) -> bool:
                return not self.terminated

            def terminate(self) -> None:
                self.terminated = True

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")

            session = FakeSession()
            self.assertIsNotNone(server.service_state)
            payload = server.service_state.create_context()
            context_id = str(payload["context_id"])
            with server.service_state.lock:
                context = server.service_state._context_locked(context_id)
                context.requirements_session = session

            server.server_close()

        self.assertTrue(session.terminated)


    def test_index_page_is_a_workflow_agnostic_shell(self) -> None:
        modules = build_module_registry()
        workflows = build_workflow_registry(modules)
        template = read_service_text_asset("index.html")
        runtime = read_service_text_asset("js/core/runtime.js")
        software = read_service_text_asset(
            "js/workflows/software.js", modules, workflows
        )
        creative = read_service_text_asset(
            "js/workflows/creative-writing.js", modules, workflows
        )
        core_styles = read_service_text_asset("css/shell.css")

        self.assertIn('fetch("/api/health"', runtime)
        self.assertIn('fetch("/api/registry"', runtime)
        self.assertIn('id="workflowModeSelect"', template)
        self.assertIn('id="workflowStageGraph"', template)
        self.assertNotIn('data-stage="requirements"', template)
        self.assertNotIn('id="creativeBinder"', template)
        self.assertNotIn("Software engineering", template)
        self.assertNotIn("Creative writing", template)

        self.assertIn("function renderStageGraph(definition, contribution)", runtime)
        self.assertIn("function renderWorkflowNavigation()", runtime)
        self.assertIn(
            'else if (typeof contribution.refreshNavigation === "function")',
            runtime,
        )
        self.assertIn("No workflows are installed or enabled.", runtime)
        self.assertIn("activeWorkflowDefinitions", runtime)
        self.assertNotIn("const SOFTWARE_WORKFLOW_MODE", runtime)
        self.assertNotIn("const CREATIVE_WORKFLOW_MODE", runtime)
        self.assertNotIn("const STAGE_DESCRIPTIONS", runtime)
        self.assertNotIn(".creative-binder", core_styles)
        self.assertIn(".stage-action-subgroup-list[hidden]", core_styles)
        self.assertIn(
            ".stage-action-subgroup-trigger.expanded .stage-action-chevron::before",
            core_styles,
        )

        self.assertIn('navigation: "stages"', software)
        self.assertIn("stageDescriptions: STAGE_DESCRIPTIONS", software)
        self.assertIn('data-creative-control="project-menu"', creative)
        self.assertIn("function renderNavigation(container, runtime)", creative)
        self.assertIn('navigation: "sidebar"', creative)

        self.assertIn('id="projectPanel"', template)
        self.assertIn('id="fileBrowser"', template)
        self.assertIn('id="sessionSwitcher"', template)
        self.assertIn('id="agentOutput"', template)
        self.assertIn('id="artifactPreviewPane"', template)
        self.assertIn('id="progressOutputPane"', template)
        self.assertIn('id="projectShellPane"', template)
        self.assertIn('id="scratchPad"', template)

    def test_artifact_event_document_path_resolves_visible_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            self.assertEqual(
                _artifact_event_document_path(root, "requirements", ""),
                root.resolve() / "docs" / "requirements.md",
            )
            self.assertEqual(
                _artifact_event_document_path(root, "document", "README.md"),
                root.resolve() / "README.md",
            )
            self.assertEqual(
                _artifact_event_document_path(
                    root,
                    "route",
                    "/artifacts/design",
                ),
                root.resolve() / "docs" / "detailed-design.md",
            )

            with self.assertRaises(StateError):
                _artifact_event_document_path(root, "document", "../README.md")
            with self.assertRaises(StateError):
                _artifact_event_document_path(root, "route", "/artifacts/unknown")

    def test_artifact_event_document_path_uses_feature_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            StateStore(root).init_run(run_id="run-1")
            feature_path = (
                root / ".electroboy" / "shared" / "runs" / "run-1" / "feature.json"
            )
            feature_path.write_text(
                json.dumps(
                    {
                        "slug": "munge",
                        "artifacts": {
                            "requirements": "docs/requirements-munge.md",
                            "design": "docs/detailed-design-munge.md",
                            "implementation_plan": "docs/implementation-plan-munge.md",
                        },
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                _artifact_event_document_path(root, "requirements", ""),
                root.resolve() / "docs" / "requirements-munge.md",
            )
            self.assertEqual(
                _artifact_event_document_path(root, "route", "/artifacts/design"),
                root.resolve() / "docs" / "detailed-design-munge.md",
            )
            self.assertEqual(
                _artifact_event_document_path(
                    root,
                    "route",
                    "/artifacts/implementation-plan",
                ),
                root.resolve() / "docs" / "implementation-plan-munge.md",
            )
    def test_workflow_payload_exposes_project_operations_before_activation(
        self,
    ) -> None:
        payload = workflow_payload()
        stages = payload["stages"]
        self.assertIsInstance(stages, list)
        operations = {
            str(stage["id"]): stage["operations"]
            for stage in stages
            if isinstance(stage, dict)
        }

        self.assertEqual(operations["project"], ["Open", "Create"])
        self.assertEqual(operations["requirements"], [])
        stage_ids = [str(stage["id"]) for stage in stages if isinstance(stage, dict)]
        self.assertEqual(
            stage_ids,
            [
                "project",
                "requirements",
                "design",
                "design-review",
                "implementation-plan",
                "code",
                "test-plan",
                "validate",
                "document",
                "corkboard",
            ],
        )
        for stage, stage_operations in operations.items():
            if stage not in {"project", "requirements"}:
                self.assertEqual(stage_operations, [])

    def test_workflow_payload_exposes_requirements_start_after_activation(
        self,
    ) -> None:
        payload = workflow_payload(ROOT)
        operations = {
            str(stage["id"]): stage["operations"]
            for stage in payload["stages"]
            if isinstance(stage, dict)
        }

        self.assertEqual(operations["project"], ["Open", "Create", "Deactivate"])
        self.assertEqual(
            operations["requirements"],
            ["Set stage", "Start", "Approve", "Skip approval", "Open requirements"],
        )
        self.assertEqual(
            operations["design"],
            ["Set stage", "Start", "Complete", "Open design"],
        )
        self.assertEqual(
            operations["design-review"],
            [
                "Set stage",
                "Run automatic review",
                "Run interactive review",
                "Stop review",
                "Approve",
                "Skip approval",
            ],
        )
        self.assertEqual(
            operations["implementation-plan"],
            ["Set stage", "Start", "Approve", "Skip approval", "Open implementation plan"],
        )
        self.assertEqual(
            operations["code"],
            [
                "Set stage",
                "Start automatic",
                "Start interactive",
                "Stop",
                "Approve",
                "Skip approval",
                "Open implementation report",
            ],
        )
        self.assertEqual(
            operations["test-plan"],
            ["Set stage", "Start", "Approve", "Skip approval", "Open test plan"],
        )
        self.assertEqual(
            operations["validate"],
            [
                "Set stage",
                "Start automatic",
                "Start interactive",
                "Stop",
                "Approve",
                "Skip approval",
                "Open validation report",
            ],
        )

    def test_generic_stage_approval_config_matches_cli_parser(self) -> None:
        parser = build_parser()
        for stage, config in GENERIC_STAGE_CONFIG.items():
            command = str(config["approval_command"])
            argv = [command, "--force"]
            if config.get("approval_reason_arg"):
                argv.extend(["--reason", f"{stage} approval override"])
            args = parser.parse_args(argv)
            self.assertEqual(args.command, command)

    def test_service_state_opens_existing_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            payload = state.open_project(context_id, str(project_root))

        self.assertEqual(payload["status"], "opened")
        self.assertEqual(payload["context_id"], context_id)
        self.assertEqual(payload["active_project_root"], str(project_root.resolve()))
        self.assertEqual(payload["activation_root"], str(project_root.resolve()))
        self.assertEqual(payload["project_mode"], "project")
        self.assertIsNone(payload["active_repository_name"])
        self.assertEqual(payload["registered_repositories"], [])
        self.assertEqual(payload["workflow_stage"], "requirements")
        self.assertFalse(payload["requirements_started"])
        self.assertFalse(payload["requirements_running"])
        self.assertFalse(payload["design_started"])
        self.assertFalse(payload["design_running"])
        self.assertFalse(payload["design_review_started"])
        self.assertFalse(payload["design_review_running"])
        self.assertFalse(payload["design_review_interactive"])
        self.assertFalse(payload["documentation_running"])
        self.assertIsNone(payload["selected_session_id"])
        self.assertEqual(payload["sessions"], [])
        self.assertEqual(
            payload["activate_command"],
            f"source {project_root.resolve() / '.electroboy' / 'bin' / 'activate'}",
        )

    def test_service_state_opens_existing_project_at_manifest_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            store = StateStore(project_root)
            manifest = store.init_run(run_id="run-1")
            manifest.set_active_stage(STAGE_DESIGN)
            store.save_manifest(manifest)

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            payload = state.open_project(context_id, str(project_root))

        self.assertEqual(payload["status"], "opened")
        self.assertEqual(payload["workflow_stage"], "design")
        self.assertFalse(payload["requirements_started"])
        self.assertFalse(payload["design_started"])

    def test_service_state_opens_existing_project_at_visible_approval_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            store = StateStore(project_root)
            manifest = store.init_run(run_id="run-1")
            manifest.set_active_stage(STAGE_DESIGN_ACCEPTANCE)
            store.save_manifest(manifest)

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            payload = state.open_project(context_id, str(project_root))

        self.assertEqual(payload["status"], "opened")
        self.assertEqual(payload["workflow_stage"], "design-review")

    def test_service_state_creates_meta_project_without_active_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            meta_root = Path(tmp) / "openQSE"
            service_root.mkdir()

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            payload = state.create_meta_project(context_id, str(meta_root))

        self.assertEqual(payload["status"], "created")
        self.assertEqual(payload["project_mode"], "meta")
        self.assertEqual(payload["activation_root"], str(meta_root.resolve()))
        self.assertIsNone(payload["active_project_root"])
        self.assertIsNone(payload["active_repository_name"])
        self.assertEqual(payload["registered_repositories"], [])
        self.assertEqual(payload["workflow_stage"], "project")
        self.assertEqual(
            payload["activate_command"],
            f"source {meta_root.resolve() / '.electroboy' / 'bin' / 'activate'}",
        )

    def test_service_state_open_auto_detects_meta_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            meta_root = Path(tmp) / "openQSE"
            service_root.mkdir()

            state = ServiceState(service_root)
            first_context = str(state.create_context()["context_id"])
            state.create_meta_project(first_context, str(meta_root))
            second_context = str(state.create_context()["context_id"])

            payload = state.open_project(second_context, str(meta_root))

        self.assertEqual(payload["status"], "opened")
        self.assertEqual(payload["project_mode"], "meta")
        self.assertEqual(payload["activation_root"], str(meta_root.resolve()))
        self.assertIsNone(payload["active_project_root"])

    def test_service_state_tracks_recent_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            creative_root = Path(tmp) / "story"
            meta_root = Path(tmp) / "openQSE"
            service_root.mkdir()

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            created_project = state.create_project(context_id, str(project_root))
            created_creative = state.create_creative_project(
                context_id,
                str(creative_root),
            )
            created_meta = state.create_meta_project(context_id, str(meta_root))
            reopened_project = state.open_project(context_id, str(project_root))
            recent = reopened_project["recent_projects"]
            recent_paths = [entry["path"] for entry in recent]
            registry_path = (
                service_root / ".electroboy" / "service" / "recent-projects.json"
            )
            registry_exists = registry_path.is_file()
            registry_data = json.loads(registry_path.read_text(encoding="utf-8"))

        self.assertEqual(created_project["recent_projects"][0]["kind"], "project")
        self.assertEqual(created_creative["recent_projects"][0]["kind"], "creative")
        self.assertEqual(created_meta["recent_projects"][0]["kind"], "meta")
        self.assertEqual(
            [entry["kind"] for entry in recent[:3]],
            ["project", "meta", "creative"],
        )
        self.assertEqual(recent_paths.count(str(project_root.resolve())), 1)
        self.assertTrue(registry_exists)
        self.assertEqual(
            registry_data["projects"][0]["path"],
            str(project_root.resolve()),
        )

    def test_service_state_initializes_creative_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            created = state.create_creative_project(context_id, str(project_root))
            (project_root / ".gitignore").write_text("*.tmp\n", encoding="utf-8")

            tree = state.initialize_creative_workspace(context_id)
            state.create_creative_folder(context_id, "chapters/act-1")
            document = state.create_creative_document(
                context_id,
                "chapters/act-1/scene-01.md",
            )
            renamed_document = state.rename_creative_entry(
                context_id,
                "chapters/act-1/scene-01.md",
                "scene-02.md",
            )
            renamed_folder = state.rename_creative_entry(
                context_id,
                "chapters/act-1",
                "act-one",
            )
            deleted_folder = state.delete_creative_entry(
                context_id,
                "chapters/act-one",
            )
            state.save_creative_scratchpad(context_id, "# Notes\n\nKeep this.\n")
            scratch = state.creative_scratchpad(context_id)

            self.assertTrue((project_root / "chapters").is_dir())
            self.assertTrue((project_root / "characters").is_dir())
            self.assertTrue((project_root / "chapters" / "chapter-01.md").is_file())
            self.assertFalse((project_root / "docs" / "requirements.md").exists())
            self.assertTrue((project_root / ".electroboy").is_dir())
            self.assertEqual(created["project_mode"], "creative")
            self.assertIsNone(created["activate_command"])
            self.assertEqual(document["path"], "chapters/act-1/scene-01.md")
            self.assertEqual(
                renamed_document["path"],
                "chapters/act-1/scene-02.md",
            )
            self.assertEqual(renamed_folder["path"], "chapters/act-one")
            self.assertEqual(deleted_folder["path"], "chapters/act-one")
            self.assertFalse((project_root / "chapters" / "act-one").exists())
            self.assertIn("chapters", [entry["name"] for entry in tree["entries"]])
            self.assertNotIn(".gitignore", [entry["name"] for entry in tree["entries"]])
            self.assertEqual(scratch["path"], "scratchpad/scratchpad.md")
            self.assertIn("Keep this.", scratch["markdown"])

    def test_service_state_opens_creative_project_with_electroboy_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            project_root.mkdir()
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])

            payload = state.open_creative_project(context_id, str(project_root))

            self.assertEqual(payload["status"], "opened")
            self.assertEqual(payload["project_mode"], "creative")
            self.assertEqual(payload["active_project_root"], str(project_root.resolve()))
            self.assertTrue((project_root / "chapters").is_dir())
            self.assertTrue((project_root / ".electroboy").is_dir())

    def test_service_state_repairs_creative_corkboard_renamed_as_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_creative_project(context_id, str(project_root))
            board_path = project_root / "corkboard" / "ideas.corkboard.json"
            broken_path = project_root / "corkboard" / "ideas.md"
            board_path.rename(broken_path)

            tree = state.initialize_creative_workspace(context_id)
            page, status = creative_corkboard_html(
                project_root,
                "corkboard/ideas.corkboard.json",
                context_id=context_id,
            )
            corkboard_folder = next(
                entry for entry in tree["entries"] if entry["path"] == "corkboard"
            )
            repaired_entry = next(
                entry
                for entry in corkboard_folder["children"]
                if entry["path"] == "corkboard/ideas.corkboard.json"
            )

            self.assertTrue(board_path.is_file())
            self.assertFalse(broken_path.exists())
            self.assertTrue(repaired_entry["corkboard"])
            self.assertFalse(repaired_entry["markdown"])
            self.assertEqual(repaired_entry["title"], "ideas")
            self.assertEqual(status, HTTPStatus.OK)
            self.assertIn('"board_type": "freeform"', page)

    def test_creative_tree_hides_duplicate_markdown_corkboard_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_creative_project(context_id, str(project_root))
            board_path = project_root / "corkboard" / "ideas.corkboard.json"
            broken_path = project_root / "corkboard" / "ideas.md"
            broken_path.write_text(board_path.read_text(encoding="utf-8"), encoding="utf-8")

            tree = state.creative_tree(context_id)
            corkboard_folder = next(
                entry for entry in tree["entries"] if entry["path"] == "corkboard"
            )
            child_paths = [
                child["path"] for child in corkboard_folder["children"]
            ]

            self.assertIn("corkboard/ideas.corkboard.json", child_paths)
            self.assertNotIn("corkboard/ideas.md", child_paths)
            self.assertTrue(broken_path.is_file())

    def test_creative_folder_board_renders_and_saves_ordered_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_creative_project(context_id, str(project_root))
            state.create_creative_document(context_id, "chapters/chapter-02.md")

            page, status = creative_corkboard_html(
                project_root,
                "chapters",
                context_id=context_id,
            )
            saved = state.save_creative_corkboard(
                context_id,
                {
                    "board_type": "folder",
                    "folder": "chapters",
                    "path": "chapters/chapter-01.md",
                    "note": "Escalate this beat.",
                    "color": "sky",
                },
            )
            ordered = state.save_creative_corkboard(
                context_id,
                {
                    "board_type": "folder",
                    "folder": "chapters",
                    "order": [
                        "chapters/chapter-02.md",
                        "chapters/chapter-01.md",
                    ],
                },
            )
            saved_page, saved_status = creative_corkboard_html(
                project_root,
                "chapters",
                context_id=context_id,
            )

            self.assertEqual(status, HTTPStatus.OK)
            self.assertIn('"board_type": "folder"', page)
            self.assertIn("index-card", page)
            self.assertIn("card-size-control", page)
            self.assertIn('id="cardSizeSlider"', page)
            self.assertIn('id="cardFontSlider"', page)
            self.assertIn('id="boardZoomSlider"', page)
            self.assertIn(
                'class="board-controls" aria-label="Corkboard display controls" hidden',
                page,
            )
            self.assertIn('aria-label="Zoom corkboard out"', page)
            self.assertIn('aria-label="Zoom corkboard in"', page)
            self.assertIn("function updateBoardZoom", page)
            self.assertIn("function handleBoardWheel(event)", page)
            self.assertIn(
                'canvasViewport.addEventListener("wheel", handleBoardWheel',
                page,
            )
            self.assertIn("board.style.width = `${100 / scale}%`;", page)
            self.assertIn(
                'if (rawStored === null || rawStored.trim() === "")',
                page,
            )
            self.assertIn('window.CSS.supports("zoom", "1")', page)
            self.assertIn("board.style.zoom = String(scale);", page)
            self.assertIn('board.style.transform = "none";', page)
            self.assertIn(
                'board.style.transform = scale === 1 ? "none"',
                page,
            )
            self.assertIn("text-rendering: optimizeLegibility;", page)
            self.assertNotIn("will-change: transform;", page)
            self.assertIn(
                'id="cardSizeSlider"\n        type="range"\n        min="100"',
                page,
            )
            self.assertIn('max="400"', page)
            self.assertIn("const MIN_CARD_SCALE = 100;", page)
            self.assertIn("const MAX_CARD_SCALE = 400;", page)
            self.assertIn("const MIN_BOARD_ZOOM = 1;", page)
            self.assertIn("const MAX_BOARD_ZOOM = 10000;", page)
            self.assertIn("function boardZoomFromSlider(value)", page)
            self.assertIn("const BOARD_ZOOM_FACTOR = 1.1;", page)
            self.assertIn("function updateCardScale", page)
            self.assertIn("function setSelectedCardColor(color)", page)
            self.assertIn("function randomCardColor()", page)
            self.assertIn("function occupiedCardBounds()", page)
            self.assertIn("async function exportBoardImage(format", page)
            self.assertIn("const maximumDimension = 16384;", page)
            self.assertIn("const maximumPixels = 64_000_000;", page)
            self.assertIn('message.action === "set-board-zoom"', page)
            self.assertIn('message.action === "export"', page)
            self.assertIn('"electroboy.creative.corkboard"', page)
            self.assertIn("CORKBOARD_STORAGE_NAMESPACE", page)
            self.assertIn(
                "repeat(auto-fill, var(--card-width, 320px))",
                page,
            )
            self.assertNotIn("--card-grid-min-width", page)
            self.assertIn(".index-card.selected", page)
            self.assertNotIn('id="status" class="status"', page)
            self.assertNotIn("function setStatus", page)
            self.assertIn('let selectedCardKey = "";', page)
            self.assertIn("function selectCard(card, cardElement)", page)
            self.assertIn('cardElement.setAttribute("aria-selected"', page)
            self.assertIn("--card-title-font-size", page)
            self.assertIn("--card-note-font-size", page)
            self.assertIn("--card-type-font-size", page)
            self.assertIn("--card-note-line-height", page)
            self.assertIn("const BASE_CARD_WIDTH = 320;", page)
            self.assertIn("const DEFAULT_CARD_FONT_SCALE = 125;", page)
            self.assertIn("function updateCardFontScale", page)
            self.assertIn("function randomCardRotation", page)
            self.assertIn("rotation: randomCardRotation()", page)
            self.assertIn("insertion-marker", page)
            self.assertIn("function showFolderInsertionMarker", page)
            self.assertIn("function folderInsertionPlacement", page)
            self.assertIn("repeating-linear-gradient(27deg", page)
            self.assertIn("CARD_PALETTE", page)
            self.assertIn("card-palette", page)
            self.assertIn("function buildColorButton(card, cardElement)", page)
            self.assertIn("chapter-01.md", page)
            self.assertIn("/api/creative/corkboard", page)
            self.assertIn("electroboy-creative-open", page)
            self.assertNotIn("drop-target", page)
            self.assertEqual(saved["status"], "saved")
            self.assertEqual(saved["card"]["path"], "chapters/chapter-01.md")
            self.assertEqual(saved["card"]["color"], "sky")
            self.assertEqual(
                ordered["order"][:2],
                ["chapters/chapter-02.md", "chapters/chapter-01.md"],
            )
            self.assertEqual(saved_status, HTTPStatus.OK)
            self.assertIn("Escalate this beat.", saved_page)
            self.assertLess(
                saved_page.index("chapter-02.md"),
                saved_page.index("chapter-01.md"),
            )
            self.assertTrue(
                (
                    project_root
                    / ".electroboy"
                    / "creative"
                    / "corkboards.json"
                ).is_file()
            )

    def test_creative_freeform_corkboard_renders_and_saves_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_creative_project(context_id, str(project_root))
            state.create_creative_corkboard(
                context_id,
                "corkboard/plot.corkboard.json",
            )

            saved = state.save_creative_corkboard(
                context_id,
                {
                    "board_type": "freeform",
                    "corkboard": "corkboard/plot.corkboard.json",
                    "card": {
                        "id": "opening-beat",
                        "title": "Opening beat",
                        "note": "Start with a quiet contradiction.",
                        "x": -188,
                        "y": 8144,
                        "color": "mint",
                    },
                },
            )
            recolored = state.save_creative_corkboard(
                context_id,
                {
                    "board_type": "freeform",
                    "corkboard": "corkboard/plot.corkboard.json",
                    "card": {
                        **saved["card"],
                        "color": "#a1b2c3",
                    },
                },
            )
            saved_layout = state.save_creative_corkboard(
                context_id,
                {
                    "board_type": "freeform",
                    "action": "layout",
                    "corkboard": "corkboard/plot.corkboard.json",
                    "layout": "grid",
                },
            )
            state.save_creative_corkboard(
                context_id,
                {
                    "board_type": "freeform",
                    "action": "title",
                    "corkboard": "corkboard/plot.corkboard.json",
                    "title": "Plot ideas",
                },
            )
            page, status = creative_corkboard_html(
                project_root,
                "corkboard/plot.corkboard.json",
                context_id=context_id,
            )
            document = json.loads(
                (project_root / "corkboard" / "plot.corkboard.json").read_text(
                    encoding="utf-8",
                )
            )
            deleted = state.save_creative_corkboard(
                context_id,
                {
                    "board_type": "freeform",
                    "action": "delete",
                    "corkboard": "corkboard/plot.corkboard.json",
                    "card_id": "opening-beat",
                },
            )
            deleted_document = json.loads(
                (project_root / "corkboard" / "plot.corkboard.json").read_text(
                    encoding="utf-8",
                )
            )
            tree = state.creative_tree(context_id)
            corkboard_folder = next(
                entry for entry in tree["entries"] if entry["path"] == "corkboard"
            )
            tree_board = next(
                entry
                for entry in corkboard_folder["children"]
                if entry["path"] == "corkboard/plot.corkboard.json"
            )

            self.assertEqual(status, HTTPStatus.OK)
            self.assertIn('"board_type": "freeform"', page)
            self.assertIn('"layout_modes": ["grid", "freeform"]', page)
            self.assertIn('"default_layout_mode": "grid"', page)
            self.assertIn("Add card", page)
            self.assertIn("Resize corkboard cards", page)
            self.assertIn('id="canvasViewport"', page)
            self.assertIn("function startCanvasPan(event)", page)
            self.assertIn("event.button !== 1", page)
            self.assertIn("function applyCanvasPan()", page)
            self.assertIn(
                "`translate(${canvasPan.x / scale}px, ${canvasPan.y / scale}px)`",
                page,
            )
            self.assertIn(
                "`translate(${canvasPan.x}px, ${canvasPan.y}px) scale(${scale})`",
                page,
            )
            self.assertIn("const worldX = (pointerX - canvasPan.x) / previousScale;", page)
            self.assertIn(
                "dragState.originalX + (event.clientX - dragState.startX) / scale",
                page,
            )
            self.assertIn("CANVAS_PAN_STORAGE_PREFIX", page)
            self.assertIn("BOARD_ZOOM_STORAGE_PREFIX", page)
            self.assertIn('document.body.classList.add("canvas-panning")', page)
            self.assertIn("card-delete-icon", page)
            self.assertIn('remove.title = "Delete card";', page)
            self.assertIn("function deleteFreeformCard(card, button)", page)
            self.assertIn("card.delete_confirmation", page)
            self.assertIn("await cardSaveRequests.get(key);", page)
            self.assertIn("function cardColorName(card)", page)
            self.assertIn("function buildColorButton(card, cardElement)", page)
            self.assertIn("card-color-icon", page)
            self.assertIn('action: "delete-card"', page)
            self.assertNotIn('"Idea"', page)
            self.assertIn("selectedCardKey = card.id;", page)
            self.assertIn("Opening beat", page)
            self.assertEqual(saved_layout["layout"], "grid")
            self.assertEqual(document["layout"], "grid")
            self.assertEqual(tree_board["name"], "plot.corkboard.json")
            self.assertEqual(tree_board["title"], "Plot ideas")
            self.assertIn("Start with a quiet contradiction.", page)
            self.assertEqual(saved["card"]["id"], "opening-beat")
            self.assertEqual(recolored["card"]["color"], "#a1b2c3")
            self.assertEqual(document["cards"][0]["id"], "opening-beat")
            self.assertEqual(document["cards"][0]["x"], -188)
            self.assertEqual(document["cards"][0]["y"], 8144)
            self.assertEqual(document["cards"][0]["color"], "#a1b2c3")
            self.assertEqual(document["cards"][0]["card_type"], "card")
            self.assertEqual(deleted["status"], "deleted")
            self.assertEqual(deleted["card_id"], "opening-beat")
            self.assertEqual(deleted_document["cards"], [])

    def test_creative_corkboard_provider_renders_through_generic_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_creative_project(context_id, str(project_root))
            controller = state.workflow_controller("creative-writing")

            self.assertIsInstance(controller, CorkboardWorkflowController)
            provider = controller.get_corkboard_provider()
            snapshot = provider.get_board(context_id, "chapters")
            ideas_snapshot = provider.get_board(
                context_id,
                "corkboard/ideas.corkboard.json",
            )
            saved_layout = provider.apply_operation(
                context_id,
                {
                    "provider": "creative-files",
                    "board_id": "corkboard/ideas.corkboard.json",
                    "board_type": "freeform",
                    "action": "change-layout",
                    "layout": "grid",
                },
            )
            saved = provider.apply_operation(
                context_id,
                {
                    "provider": "creative-files",
                    "board_id": "chapters",
                    "board_type": "folder",
                    "action": "update-card",
                    "card": {
                        "id": "chapters/chapter-01.md",
                        "note": "Provider-backed note.",
                        "color": "mint",
                    },
                },
            )
            page, status = render_corkboard_html(snapshot)

        self.assertEqual(provider.provider_id, "creative-files")
        self.assertEqual(snapshot["provider"], "creative-files")
        self.assertEqual(snapshot["board_id"], "chapters")
        self.assertEqual(snapshot["board_type"], "folder")
        self.assertEqual(ideas_snapshot["layout_modes"], ["grid", "freeform"])
        self.assertEqual(ideas_snapshot["default_layout_mode"], "freeform")
        self.assertEqual(saved_layout["layout"], "grid")
        self.assertIn("open-card", snapshot["capabilities"])
        self.assertEqual(saved["card"]["note"], "Provider-backed note.")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("/api/corkboard", page)
        self.assertIn("electroboy-corkboard-open", page)
        self.assertNotIn("/api/creative/corkboard", page)

    def test_software_workflow_uses_shared_project_corkboard_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_project(context_id, str(project_root))
            controller = state.workflow_controller("software")

            self.assertIsInstance(controller, CorkboardWorkflowController)
            provider = controller.get_corkboard_provider()
            created = provider.create_board(
                context_id,
                "Release tasks",
                title="Release tasks",
            )
            saved = provider.apply_operation(
                context_id,
                {
                    "provider": "project-files",
                    "board_id": created["board_id"],
                    "action": "update-card",
                    "card": {
                        "id": "verify-package",
                        "title": "Verify package",
                        "note": "Build and install the release wheel.",
                        "color": "sky",
                    },
                },
            )
            boards = provider.list_boards(context_id)
            snapshot = provider.get_board(context_id, created["board_id"])

        self.assertEqual(provider.provider_id, "project-files")
        self.assertEqual(
            created["board_id"],
            ".electroboy/shared/corkboards/release-tasks.corkboard.json",
        )
        self.assertEqual(boards[0]["title"], "Release tasks")
        self.assertEqual(snapshot["provider"], "project-files")
        self.assertEqual(snapshot["board_type"], "freeform")
        self.assertNotIn("group-card", snapshot["capabilities"])
        self.assertEqual(saved["card"]["id"], "verify-package")

    def test_agenda_contract_groups_items_and_renders_generic_controls(self) -> None:
        snapshot = normalize_agenda_snapshot(
            {
                "title": "Shared plan",
                "timezone": "UTC",
                "filters": [
                    {
                        "id": "kind",
                        "label": "Items",
                        "value": "all",
                        "options": [
                            {"value": "all", "label": "All"},
                            {"value": "event", "label": "Events"},
                        ],
                    }
                ],
                "items": [
                    {
                        "id": "event:today",
                        "kind": "event",
                        "title": "Practice",
                        "start_at": "2026-08-17T17:00:00+00:00",
                        "participants": [{"id": "member:1", "label": "Ari"}],
                        "actions": [
                            {
                                "id": "edit",
                                "label": "Edit",
                                "editor": True,
                            }
                        ],
                    },
                    {
                        "id": "task:later",
                        "kind": "task",
                        "title": "Return form",
                        "due_at": "2026-08-19T12:00:00+00:00",
                    },
                    {
                        "id": "note:undated",
                        "kind": "note",
                        "title": "Bring snacks",
                        "status": "suggested",
                        "confidence": 0.81,
                        "badges": ["Suggested"],
                    },
                    {
                        "id": "warning:review",
                        "kind": "warning",
                        "title": "Date needs review",
                        "warning": {"message": "No date was extracted"},
                    },
                ],
            },
            provider_id="fixture-agenda",
            now=datetime(2026, 8, 17, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(
            [section["id"] for section in snapshot["sections"]],
            ["needs-attention", "today", "this-week", "unscheduled"],
        )
        self.assertEqual(
            sum(len(section["items"]) for section in snapshot["sections"]),
            4,
        )
        page, status = render_agenda_html(snapshot)
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn('id="agendaControls"', page)
        self.assertIn('element("div", "agenda-modal-overlay")', page)
        self.assertIn("async function invokeAction", page)
        self.assertIn("async function openEditor", page)
        self.assertIn('"provider": "fixture-agenda"', page)

    def test_agenda_contract_rejects_invalid_snapshots(self) -> None:
        with self.assertRaisesRegex(StateError, "agenda title is required"):
            normalize_agenda_snapshot(
                {"title": "", "items": []},
                provider_id="fixture-agenda",
            )
        with self.assertRaisesRegex(StateError, "agenda items must be a list"):
            normalize_agenda_snapshot(
                {"title": "Agenda", "items": {}},
                provider_id="fixture-agenda",
            )
        with self.assertRaisesRegex(StateError, "start_at must be an ISO timestamp"):
            normalize_agenda_snapshot(
                {
                    "title": "Agenda",
                    "items": [
                        {
                            "id": "event:1",
                            "kind": "event",
                            "title": "Invalid",
                            "start_at": "tomorrow",
                        }
                    ],
                },
                provider_id="fixture-agenda",
            )

    def test_corkboard_provider_contract_rejects_invalid_snapshots(self) -> None:
        with self.assertRaisesRegex(StateError, "unknown corkboard type"):
            normalize_board_snapshot(
                {"title": "Backlog", "cards": []},
                provider_id="better-planned",
                board_id="backlog",
            )
        with self.assertRaisesRegex(StateError, "unknown corkboard layout mode"):
            normalize_board_snapshot(
                {
                    "board_type": "freeform",
                    "title": "Backlog",
                    "layout_modes": ["stacked"],
                    "cards": [],
                },
                provider_id="better-planned",
                board_id="backlog",
            )
        with self.assertRaisesRegex(StateError, "default corkboard layout mode"):
            normalize_board_snapshot(
                {
                    "board_type": "freeform",
                    "title": "Backlog",
                    "layout_modes": ["grid", "freeform"],
                    "default_layout_mode": "columns",
                    "cards": [],
                },
                provider_id="better-planned",
                board_id="backlog",
            )

    def test_generic_corkboard_renders_database_record_cards(self) -> None:
        snapshot = normalize_board_snapshot(
            {
                "board_type": "freeform",
                "layout_modes": ["grid", "freeform"],
                "default_layout_mode": "grid",
                "title": "Family board",
                "context_id": "context-1",
                "capabilities": ["open-card"],
                "card_aspect_ratio": 0.75,
                "cards": [
                    {
                        "id": "activity-184",
                        "title": "Soccer practice",
                        "note": "Bring the blue uniform.",
                        "x": 120,
                        "y": 80,
                        "color": "sky",
                        "target": {
                            "type": "better-planned-entry",
                            "id": "184",
                        },
                        "metadata": {
                            "people": ["Ari", "Amir"],
                            "deadline": "2026-08-20",
                            "status": "needs-review",
                        },
                    }
                ],
            },
            provider_id="better-planned",
            board_id="family-1",
        )

        page, status = render_corkboard_html(snapshot)

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(snapshot["card_aspect_ratio"], 0.75)
        self.assertEqual(snapshot["layout_modes"], ["grid", "freeform"])
        self.assertEqual(snapshot["default_layout_mode"], "grid")
        self.assertIn('"provider": "better-planned"', page)
        self.assertIn('"type": "better-planned-entry"', page)
        self.assertIn('"deadline": "2026-08-20"', page)
        self.assertIn("function buildCardMetadata(card)", page)
        self.assertIn('card.target && supports("open-card")', page)
        self.assertIn('boardTitle.readOnly =', page)
        self.assertIn('"card_aspect_ratio": 0.75', page)
        self.assertIn('"fixed-card-ratio"', page)
        self.assertIn('"--card-height"', page)
        self.assertIn("const CARD_ASPECT_RATIO", page)
        self.assertIn('id="layoutSelect"', page)
        self.assertIn('id="boardSelect"', page)
        self.assertIn('id="autoOrganize"', page)
        self.assertIn('id="undoOrganize"', page)
        self.assertIn("function selectLayoutMode(nextMode)", page)
        self.assertIn("function organizeFreeformCards", page)
        self.assertIn("function captureGridPositions", page)
        self.assertIn("function applyGridColumns()", page)
        self.assertIn("canvasViewport.clientWidth / boardZoomFactor()", page)
        self.assertIn('board.style.minWidth = "0";', page)
        self.assertIn(
            '`repeat(${columnCount}, minmax(0, ${cardWidth}px))`',
            page,
        )
        self.assertIn("async function configureBoardSelector", page)
        self.assertIn('type: "electroboy-corkboard-selected"', page)

    def test_generic_corkboard_routes_use_active_creative_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            try:
                server = create_server(service_root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            context_id = str(server.service_state.create_context()["context_id"])
            server.service_state.create_creative_project(
                context_id,
                str(project_root),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = request(
                    server,
                    f"/artifacts/corkboard?context_id={context_id}"
                    "&provider=creative-files&board_id=chapters",
                )
                api_status, api_body, _api_content_type = request(
                    server,
                    f"/api/corkboard?context_id={context_id}"
                    "&provider=creative-files&board_id=chapters",
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn("electroboy-corkboard-open", body)
        self.assertEqual(api_status, HTTPStatus.OK)
        api_payload = json.loads(api_body)
        self.assertEqual(api_payload["provider"], "creative-files")
        self.assertEqual(api_payload["board_id"], "chapters")

    def test_creative_freeform_corkboard_converts_card_to_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_creative_project(context_id, str(project_root))
            state.create_creative_corkboard(
                context_id,
                "corkboard/plot.corkboard.json",
            )

            saved = state.save_creative_corkboard(
                context_id,
                {
                    "board_type": "freeform",
                    "corkboard": "corkboard/plot.corkboard.json",
                    "card": {
                        "id": "scene-one",
                        "title": "Scene one",
                        "note": "Break this scene down.",
                        "card_type": "group",
                    },
                },
            )
            page, status = creative_corkboard_html(
                project_root,
                "corkboard/plot.corkboard.json",
                context_id=context_id,
            )
            document = json.loads(
                (project_root / "corkboard" / "plot.corkboard.json").read_text(
                    encoding="utf-8",
                )
            )

            board_path = str(saved["card"]["board_path"])
            child_document = json.loads(
                (project_root / board_path).read_text(encoding="utf-8")
            )
            child_page, child_status = creative_corkboard_html(
                project_root,
                board_path,
                context_id=context_id,
            )
            duplicate = state.save_creative_corkboard(
                context_id,
                {
                    "board_type": "freeform",
                    "corkboard": "corkboard/plot.corkboard.json",
                    "card": {
                        "id": "scene-two",
                        "title": "Scene one",
                        "card_type": "group",
                    },
                },
            )
            duplicate_path = str(duplicate["card"]["board_path"])
            duplicate_document = json.loads(
                (project_root / duplicate_path).read_text(encoding="utf-8")
            )
            renamed = state.save_creative_corkboard(
                context_id,
                {
                    "board_type": "freeform",
                    "action": "title",
                    "corkboard": board_path,
                    "title": "Scene outline",
                },
            )
            renamed_document = json.loads(
                (project_root / board_path).read_text(encoding="utf-8")
            )
            renamed_parent_document = json.loads(
                (project_root / "corkboard" / "plot.corkboard.json").read_text(
                    encoding="utf-8",
                )
            )
            tree = state.creative_tree(context_id)

            self.assertEqual(status, HTTPStatus.OK)
            self.assertEqual(child_status, HTTPStatus.OK)
            self.assertEqual(saved["card"]["card_type"], "group")
            self.assertTrue(board_path.endswith(".corkboard.json"))
            self.assertTrue((project_root / board_path).is_file())
            self.assertEqual(document["cards"][0]["card_type"], "group")
            self.assertEqual(document["cards"][0]["board_path"], board_path)
            self.assertEqual(child_document["title"], "Scene one")
            self.assertIn('id="boardTitle"', child_page)
            self.assertIn('value="Scene one"', child_page)
            self.assertNotEqual(duplicate_path, board_path)
            self.assertEqual(duplicate_document["title"], "Scene one")
            self.assertEqual(renamed["title"], "Scene outline")
            self.assertEqual(renamed_document["title"], "Scene outline")
            self.assertEqual(
                renamed_parent_document["cards"][0]["title"],
                "Scene outline",
            )
            self.assertEqual(
                renamed["group_cards"],
                [
                    {
                        "corkboard": "corkboard/plot.corkboard.json",
                        "card_id": "scene-one",
                    }
                ],
            )
            self.assertTrue((project_root / board_path).is_file())
            self.assertNotIn("corkboard/groups", json.dumps(tree))
            self.assertIn(
                "function convertCardToGroup(card, cardElement, button)",
                page,
            )
            self.assertIn("function openGroupCard(card)", page)
            self.assertIn("card-group-action", page)
            self.assertIn("card-group-icon", page)
            self.assertIn("Double-click to open card group", page)
            self.assertIn("currentPress - previousTitlePress <= 500", page)
            self.assertIn('action: "rename-board"', child_page)
            self.assertIn('type: "corkboard-title-changed"', child_page)
            self.assertIn("new window.BroadcastChannel", child_page)
            self.assertIn('"card_type": "group"', page)
            self.assertIn(board_path, page)

    def test_service_state_starts_creative_writing_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_creative_project(context_id, str(project_root))
            state.initialize_creative_workspace(context_id)

            with mock.patch("electroboy.service.AgentSession.start"):
                session, started = state.start_creative_writing_agent(
                    context_id,
                    active_document="chapters/chapter-01.md",
                )

        self.assertTrue(started)
        self.assertEqual(session.kind, "creative-writing")
        self.assertIn("codex", session.command[0])
        self.assertIn("--cd", session.command)
        self.assertIn("creative writing collaborator", session.command[-1])
        self.assertIn("chapters/chapter-01.md", session.command[-1])

    def test_service_state_starts_creative_agent_for_corkboard_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_creative_project(context_id, str(project_root))
            state.initialize_creative_workspace(context_id)

            with mock.patch("electroboy.service.AgentSession.start"):
                session, started = state.start_creative_writing_agent(
                    context_id,
                    active_target={
                        "type": "freeform-corkboard",
                        "path": "corkboard/ideas.corkboard.json",
                    },
                )

        self.assertTrue(started)
        self.assertIn("Current active target: freeform corkboard", session.command[-1])
        self.assertIn("corkboard/ideas.corkboard.json", session.command[-1])
        self.assertIn("docs/corkboard-api.md", session.command[-1])
        self.assertIn("electroboy corkboard", session.command[-1])

    def test_service_state_starts_creative_agent_for_folder_board_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_creative_project(context_id, str(project_root))
            state.initialize_creative_workspace(context_id)

            with mock.patch("electroboy.service.AgentSession.start"):
                session, started = state.start_creative_writing_agent(
                    context_id,
                    active_target={
                        "type": "folder-corkboard",
                        "path": "chapters",
                    },
                )

        self.assertTrue(started)
        self.assertIn("Current active target: folder corkboard", session.command[-1])
        self.assertIn("chapters", session.command[-1])
        self.assertIn("electroboy corkboard folder", session.command[-1])

    def test_service_state_meta_add_and_start_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            meta_root = Path(tmp) / "openQSE"
            repo_root = meta_root / "QFw"
            service_root.mkdir()
            repo_root.mkdir(parents=True)

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_meta_project(context_id, str(meta_root))

            add_payload = state.add_meta_repository(context_id, "QFw")
            start_payload = state.start_meta_repository(context_id, "QFw")
            current_run_exists = (
                repo_root / ".electroboy" / "shared" / "current-run"
            ).exists()

        self.assertEqual(add_payload["status"], "registered")
        self.assertEqual(add_payload["project_mode"], "meta")
        self.assertIsNone(add_payload["active_project_root"])
        self.assertEqual(add_payload["registered_repositories"][0]["name"], "QFw")
        self.assertEqual(start_payload["status"], "started")
        self.assertEqual(start_payload["project_mode"], "meta")
        self.assertEqual(start_payload["activation_root"], str(meta_root.resolve()))
        self.assertEqual(start_payload["active_project_root"], str(repo_root.resolve()))
        self.assertEqual(start_payload["active_repository_name"], "QFw")
        self.assertEqual(start_payload["workflow_stage"], "requirements")
        self.assertTrue(current_run_exists)

    def test_service_state_meta_start_switches_registered_repositories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            meta_root = Path(tmp) / "openQSE"
            first_repo = meta_root / "QFw"
            second_repo = meta_root / "qSchedSim"
            service_root.mkdir()
            first_repo.mkdir(parents=True)
            second_repo.mkdir(parents=True)

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_meta_project(context_id, str(meta_root))
            state.add_meta_repository(context_id, "QFw")
            state.add_meta_repository(context_id, "qSchedSim")
            first_payload = state.start_meta_repository(context_id, "QFw")
            second_payload = state.start_meta_repository(context_id, "qSchedSim")

        self.assertEqual(first_payload["active_repository_name"], "QFw")
        self.assertEqual(first_payload["active_project_root"], str(first_repo.resolve()))
        self.assertEqual(second_payload["status"], "started")
        self.assertEqual(second_payload["active_repository_name"], "qSchedSim")
        self.assertEqual(second_payload["active_project_root"], str(second_repo.resolve()))
        self.assertEqual(
            [repo["name"] for repo in second_payload["registered_repositories"]],
            ["QFw", "qSchedSim"],
        )

    def test_service_state_registers_features_in_default_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            feature_payload = state.start_feature_work_item(
                context_id,
                title="Add admissions",
                feature_name="admissions",
            )
            subfeature_payload = state.start_feature_work_item(
                context_id,
                title="Add scheduler",
                feature_name="scheduler",
                parent_slug="admissions",
            )
            switched_payload = state.switch_feature_work_item(context_id, "admissions")
            feature_record = json.loads(
                (
                    project_root
                    / ".electroboy"
                    / "shared"
                    / "runs"
                    / "run-1"
                    / "feature.json"
                ).read_text(encoding="utf-8")
            )

        self.assertEqual(feature_payload["status"], "started feature")
        self.assertEqual(subfeature_payload["status"], "started feature")
        self.assertEqual(switched_payload["status"], "switched feature")
        self.assertEqual(feature_record["slug"], "admissions")
        work_items = subfeature_payload["work_items"]
        self.assertEqual(work_items["active_collection_id"], "default")
        self.assertEqual(work_items["active_feature_slug"], "scheduler")
        collections = {
            collection["id"]: collection for collection in work_items["collections"]
        }
        self.assertIn("default", collections)
        features = {
            feature["slug"]: feature for feature in work_items["features"]
        }
        self.assertEqual(features["scheduler"]["parent_slug"], "admissions")
        self.assertEqual(features["admissions"]["collection_id"], "default")
        self.assertEqual(features["scheduler"]["collection_id"], "default")

    def test_service_state_feature_start_stops_running_requirements_agent(self) -> None:
        class FakeSession:
            session_id = "requirements-session"
            label = "requirements agent"

            def __init__(self) -> None:
                self.terminated = False

            def is_active(self) -> bool:
                return not self.terminated

            def terminate(self) -> None:
                self.terminated = True

        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            session = FakeSession()
            with state.lock:
                context = state.contexts[context_id]
                context.requirements_session = session  # type: ignore[assignment]
                context.selected_session_id = session.session_id

            payload = state.start_feature_work_item(
                context_id,
                title="Add admissions",
                feature_name="admissions",
            )

        self.assertTrue(session.terminated)
        self.assertEqual(payload["status"], "started feature")
        self.assertTrue(payload["terminated_agent"])
        self.assertIsNone(state.current_requirements_session(context_id))
        self.assertEqual(payload["selected_session_id"], None)

    def test_unknown_feature_switch_keeps_running_requirements_agent(self) -> None:
        class FakeSession:
            session_id = "requirements-session"
            label = "requirements agent"

            def __init__(self) -> None:
                self.terminated = False

            def is_active(self) -> bool:
                return not self.terminated

            def terminate(self) -> None:
                self.terminated = True

        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            session = FakeSession()
            with state.lock:
                context = state.contexts[context_id]
                context.requirements_session = session  # type: ignore[assignment]
                context.selected_session_id = session.session_id

            with self.assertRaisesRegex(AgentSessionError, "unknown feature"):
                state.switch_feature_work_item(context_id, "missing")

        self.assertFalse(session.terminated)
        self.assertIs(state.current_requirements_session(context_id), session)

    def test_service_state_starts_bug_work_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            payload = state.start_bug_work_item(
                context_id,
                issue_reference="https://tracker.example.com/issues/123",
            )
            bug_record = json.loads(
                (
                    project_root
                    / ".electroboy"
                    / "shared"
                    / "runs"
                    / "run-1"
                    / "bug.json"
                ).read_text(encoding="utf-8")
            )

        self.assertEqual(payload["status"], "started bug resolution")
        self.assertEqual(payload["work_items"]["active_bug_slug"], "123")
        self.assertEqual(payload["work_items"]["active_feature_slug"], None)
        self.assertEqual(bug_record["slug"], "123")
        self.assertEqual(bug_record["workflow"], "bug")

    def test_service_state_meta_remove_repository_clears_active_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            meta_root = Path(tmp) / "openQSE"
            repo_root = meta_root / "QFw"
            service_root.mkdir()
            repo_root.mkdir(parents=True)

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_meta_project(context_id, str(meta_root))
            state.add_meta_repository(context_id, "QFw")
            state.start_meta_repository(context_id, "QFw")
            payload = state.remove_meta_repository(context_id, "QFw")

        self.assertEqual(payload["status"], "removed")
        self.assertEqual(payload["project_mode"], "meta")
        self.assertEqual(payload["activation_root"], str(meta_root.resolve()))
        self.assertIsNone(payload["active_project_root"])
        self.assertIsNone(payload["active_repository_name"])
        self.assertEqual(payload["registered_repositories"], [])
        self.assertEqual(payload["workflow_stage"], "project")

    def test_project_status_payload_uses_meta_activation_root_without_active_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            meta_root = Path(tmp) / "openQSE"
            service_root.mkdir()

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_meta_project(context_id, str(meta_root))

            with mock.patch(
                "electroboy.service.app._status_snapshot",
                return_value=("meta-project status\n", True),
            ) as status_snapshot:
                payload = state.project_status_payload(context_id)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["output"], "meta-project status\n")
        status_snapshot.assert_called_once_with(meta_root.resolve())

    def test_meta_stage_agent_runs_from_meta_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            meta_root = Path(tmp) / "openQSE"
            repo_root = meta_root / "QFw"
            service_root.mkdir()
            repo_root.mkdir(parents=True)

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_meta_project(context_id, str(meta_root))
            state.start_meta_repository(context_id, "QFw")

            with mock.patch("electroboy.service.AgentSession.start"):
                session, started = state.start_requirements_agent(context_id)

        self.assertTrue(started)
        self.assertEqual(session.cwd, meta_root.resolve())
        self.assertEqual(session.command[:2], ["/bin/sh", "-c"])
        self.assertIn(
            str(meta_root.resolve() / ".electroboy" / "bin" / "activate"),
            session.command[2],
        )
        self.assertIn("-m electroboy --root", session.command[2])
        self.assertIn("requirements", session.command[2])

    def test_service_state_starts_ad_hoc_agent_with_minimal_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            controller = state.workflow_controller("software")
            with mock.patch("electroboy.service.AgentSession.start"):
                session, started = controller.start_ad_hoc_agent(context_id)
            payload = state.project_payload(context_id)

        self.assertTrue(started)
        self.assertEqual(session.kind, "ad-hoc")
        self.assertEqual(session.label, "ad-hoc agent")
        self.assertTrue(session.interactive)
        self.assertEqual(session.cwd, project_root.resolve())
        self.assertEqual(session.command[:2], ["codex", "--cd"])
        self.assertEqual(str(project_root.resolve()), session.command[2])
        self.assertIn("--sandbox", session.command)
        prompt = session.command[-1]
        self.assertIn("ad-hoc agent for this code base", prompt)
        self.assertIn("workflow stage is irrelevant", prompt)
        self.assertIn("until the operator gives you a task", prompt)
        self.assertIn("Do not run any electroboy workflow command", prompt)
        self.assertIn(
            "Wait for and then follow the operator's next instruction",
            prompt,
        )
        self.assertNotIn("requirements", session.command[-1])
        self.assertNotIn("detailed-design", session.command[-1])
        self.assertEqual(payload["selected_session_id"], session.session_id)
        self.assertEqual(payload["sessions"][0]["kind"], "ad-hoc")

    def test_ad_hoc_history_lists_and_resumes_project_codex_sessions(self) -> None:
        provider_session_id = "019f3cb6-60c3-7320-896b-e5eb9a6a8dd2"
        older_session_id = "019f3cb6-60c3-7320-896b-e5eb9a6a8dd1"
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            codex_home = Path(tmp) / "codex"
            session_path = codex_home / "sessions" / "2026" / "08" / "17"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")
            session_path.mkdir(parents=True)
            current_session_path = (
                session_path / f"rollout-{provider_session_id}.jsonl"
            )
            current_session_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "session_meta",
                                "payload": {
                                    "session_id": provider_session_id,
                                    "timestamp": "2026-08-17T12:00:00+00:00",
                                    "cwd": str(project_root),
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "input_text",
                                            "text": (
                                                "You are an ad-hoc agent for this "
                                                "code base.\nWait for the operator."
                                            ),
                                        }
                                    ],
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "input_text",
                                            "text": "Prototype the import service.",
                                        }
                                    ],
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            older_session_path = session_path / f"rollout-{older_session_id}.jsonl"
            older_session_path.write_text(
                current_session_path.read_text(encoding="utf-8")
                .replace(provider_session_id, older_session_id)
                .replace("Prototype the import service.", "Investigate the parser."),
                encoding="utf-8",
            )
            os.utime(older_session_path, (1, 1))

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            controller = state.workflow_controller("software")
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                history = controller.ad_hoc_sessions(context_id)
                with mock.patch("electroboy.service.AgentSession.start"):
                    session, started = controller.start_ad_hoc_agent(
                        context_id,
                        provider_session_id,
                    )
            catalog = json.loads(
                (
                    service_root
                    / ".electroboy"
                    / "service"
                    / "ad-hoc-sessions.json"
                ).read_text(encoding="utf-8")
            )

        self.assertEqual(history["project_root"], str(project_root.resolve()))
        self.assertEqual(len(history["sessions"]), 2)
        self.assertEqual(
            history["sessions"][0]["provider_session_id"],
            provider_session_id,
        )
        self.assertEqual(
            history["sessions"][0]["title"],
            "Prototype the import service.",
        )
        self.assertTrue(started)
        self.assertEqual(session.command[-2:], ["resume", provider_session_id])
        self.assertEqual(
            session.metadata["provider_session_id"],
            provider_session_id,
        )
        self.assertTrue(session.metadata["resumed_session"])
        self.assertEqual(
            catalog["sessions"][0]["provider_session_id"],
            provider_session_id,
        )

    def test_ad_hoc_resume_rejects_session_from_another_project(self) -> None:
        provider_session_id = "019f3cb6-60c3-7320-896b-e5eb9a6a8dd2"
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            other_root = Path(tmp) / "other"
            codex_home = Path(tmp) / "codex"
            session_path = (
                codex_home / "sessions" / f"rollout-{provider_session_id}.jsonl"
            )
            service_root.mkdir()
            project_root.mkdir()
            other_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")
            session_path.parent.mkdir(parents=True)
            session_path.write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "session_id": provider_session_id,
                            "timestamp": "2026-08-17T12:00:00+00:00",
                            "cwd": str(other_root),
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            controller = state.workflow_controller("software")
            with (
                mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}),
                self.assertRaisesRegex(AgentSessionError, "active project"),
            ):
                controller.start_ad_hoc_agent(context_id, provider_session_id)

    def test_service_session_registry_records_and_attaches_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            first_context = str(state.create_context()["context_id"])
            second_context = str(state.create_context()["context_id"])
            state.open_project(first_context, str(project_root))

            controller = state.workflow_controller("software")
            with mock.patch("electroboy.service.AgentSession.start"):
                session, _started = controller.start_ad_hoc_agent(first_context)

            registry = state.session_registry_payload()
            attach_payload = state.attach_session(second_context, session.session_id)
            records = json.loads(
                _service_session_records_path(service_root).read_text(
                    encoding="utf-8",
                )
            )

        self.assertEqual(registry["sessions"][0]["session_id"], session.session_id)
        self.assertTrue(registry["sessions"][0]["attachable"])
        self.assertEqual(
            registry["sessions"][0]["active_project_root"],
            str(project_root.resolve()),
        )
        self.assertEqual(records["sessions"][0]["session_id"], session.session_id)
        self.assertEqual(attach_payload["status"], "attached")
        self.assertEqual(
            attach_payload["active_project_root"],
            str(project_root.resolve()),
        )
        self.assertEqual(attach_payload["selected_session_id"], session.session_id)
        self.assertEqual(attach_payload["sessions"][0]["session_id"], session.session_id)

    def test_service_state_tmux_backend_wraps_new_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root, session_backend="tmux")
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            controller = state.workflow_controller("software")
            with mock.patch("electroboy.service.TmuxAgentSession.start"):
                session, started = controller.start_ad_hoc_agent(context_id)

            registry = state.session_registry_payload()

        self.assertTrue(started)
        self.assertIsInstance(session, TmuxAgentSession)
        self.assertEqual(session.backend, "tmux")
        self.assertTrue(session.tmux_name.startswith("electroboy-"))
        self.assertEqual(registry["sessions"][0]["backend"], "tmux")
        self.assertEqual(registry["sessions"][0]["tmux_session"], session.tmux_name)

    def test_service_state_restores_running_tmux_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            record_path = _service_session_records_path(service_root)
            record_path.parent.mkdir(parents=True, exist_ok=True)
            record_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "sessions": [
                            {
                                "active_project_root": str(project_root),
                                "activation_root": str(project_root),
                                "backend": "tmux",
                                "command": [sys.executable, "-c", "print('ready')"],
                                "context_id": "ctx-restored",
                                "cwd": str(project_root),
                                "interactive": True,
                                "kind": "ad-hoc",
                                "label": "ad-hoc agent",
                                "metadata": {},
                                "project_mode": "project",
                                "session_id": "session-restored",
                                "status": "running",
                                "tmux_session": "electroboy-session-restored",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch(
                    "electroboy.service.app.shutil.which",
                    return_value="/usr/bin/tmux",
                ),
                mock.patch("electroboy.service.app._tmux_has_session", return_value=True),
                mock.patch(
                    "electroboy.service.TmuxAgentSession.attach_existing"
                ) as attach_existing,
            ):
                state = ServiceState(service_root, session_backend="tmux")
                registry = state.session_registry_payload()

        attach_existing.assert_called_once()
        self.assertEqual(registry["sessions"][0]["session_id"], "session-restored")
        self.assertEqual(registry["sessions"][0]["backend"], "tmux")
        self.assertTrue(registry["sessions"][0]["attachable"])
        self.assertEqual(
            registry["sessions"][0]["active_project_root"],
            str(project_root),
        )

    def test_documentation_sidecar_session_does_not_change_workflow_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            with mock.patch("electroboy.service.AgentSession.start"):
                session, started = state.start_documentation_agent(
                    context_id,
                    target="README.md",
                )
            payload = state.project_payload(context_id)
            target_exists = (project_root / "README.md").exists()

        self.assertTrue(started)
        self.assertTrue(target_exists)
        self.assertEqual(session.kind, "documentation")
        self.assertTrue(session.interactive)
        command_text = " ".join(session.command)
        self.assertIn("-m electroboy --root", command_text)
        self.assertIn("document", command_text)
        self.assertIn("--sidecar", command_text)
        self.assertIn("--interactive", command_text)
        self.assertIn("--target", command_text)
        self.assertIn("README.md", command_text)
        self.assertIn("README.md", session.label)
        self.assertEqual(session.metadata["document_path"], "README.md")
        self.assertEqual(session.metadata["document_label"], "README.md")
        self.assertEqual(session.lock_names, frozenset({"documentation:README.md"}))
        self.assertEqual(payload["workflow_stage"], "requirements")
        self.assertEqual(payload["selected_session_id"], session.session_id)
        self.assertEqual(payload["sessions"][0]["kind"], "documentation")
        self.assertEqual(
            payload["sessions"][0]["metadata"]["document_path"],
            "README.md",
        )

    def test_documentation_sidecar_tracks_one_session_per_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            with mock.patch("electroboy.service.AgentSession.start"):
                readme_session, readme_started = state.start_documentation_agent(
                    context_id,
                    target="README.md",
                )
                api_session, api_started = state.start_documentation_agent(
                    context_id,
                    target="docs/api.md",
                )
            payload = state.project_payload(context_id)

        self.assertTrue(readme_started)
        self.assertTrue(api_started)
        self.assertNotEqual(readme_session.session_id, api_session.session_id)
        self.assertEqual(readme_session.metadata["document_path"], "README.md")
        self.assertEqual(api_session.metadata["document_path"], "docs/api.md")
        self.assertEqual(payload["selected_session_id"], api_session.session_id)
        self.assertEqual(len(payload["sessions"]), 2)
        self.assertEqual(
            [session["metadata"]["document_path"] for session in payload["sessions"]],
            ["README.md", "docs/api.md"],
        )

    def test_project_shell_starts_in_active_project_without_agent_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            with mock.patch("electroboy.service.AgentSession.start"):
                session, started = state.start_project_shell(context_id)
                second_session, second_started = state.start_project_shell(context_id)
            payload = state.project_payload(context_id)
            shell_sessions = state.contexts[context_id].project_shell_sessions
            shell_payloads = state.project_shell_payloads(context_id)

        self.assertTrue(started)
        self.assertTrue(second_started)
        self.assertNotEqual(session.session_id, second_session.session_id)
        self.assertEqual(
            set(shell_sessions),
            {session.session_id, second_session.session_id},
        )
        self.assertEqual(session.kind, "project-shell")
        self.assertEqual(session.label, "project shell")
        self.assertEqual(session.cwd, project_root.resolve())
        self.assertTrue(session.echo_input)
        self.assertTrue(session.controlling_terminal)
        self.assertIsNone(payload["selected_session_id"])
        self.assertEqual(payload["sessions"], [])
        self.assertEqual(
            {item["session_id"] for item in shell_payloads},
            {session.session_id, second_session.session_id},
        )

    def test_project_shell_payload_reports_running_separately(self) -> None:
        class FakeShell:
            session_id = "shell-session"
            kind = "project-shell"
            label = "project shell"

            def is_active(self) -> bool:
                return True

        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            with state.lock:
                state.contexts[context_id].project_shell_session = FakeShell()  # type: ignore[assignment]
            payload = state.project_payload(context_id)

        self.assertTrue(payload["project_shell_running"])
        self.assertEqual(payload["sessions"], [])

    def test_project_shell_stop_removes_only_the_requested_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            with mock.patch("electroboy.service.AgentSession.start"):
                first, _ = state.start_project_shell(context_id)
                second, _ = state.start_project_shell(context_id)

            stopped = state.stop_project_shell(context_id, first.session_id)

            self.assertEqual(stopped["status"], "stopped project shell")
            self.assertIsNone(
                state.current_project_shell_session(context_id, first.session_id)
            )
            self.assertIs(
                state.current_project_shell_session(context_id, second.session_id),
                second,
            )

    def test_project_shell_http_routes_address_independent_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")
            try:
                server = create_server(service_root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            state = server.service_state
            self.assertIsNotNone(state)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                first_status, first_body, _ = post_json(
                    server,
                    f"/api/shell/start?context_id={context_id}",
                    {},
                )
                second_status, second_body, _ = post_json(
                    server,
                    f"/api/shell/start?context_id={context_id}",
                    {},
                )
                if first_status == HTTPStatus.CONFLICT:
                    self.skipTest(json.loads(first_body).get("error", "shell unavailable"))
                first_id = json.loads(first_body)["shell_session"]["session_id"]
                second_id = json.loads(second_body)["shell_session"]["session_id"]
                sessions_status, sessions_body, _ = request(
                    server,
                    f"/api/shell/sessions?context_id={context_id}",
                )

                stop_status, _, _ = post_json(
                    server,
                    (
                        f"/api/shell/stop?context_id={context_id}"
                        f"&session_id={first_id}"
                    ),
                    {},
                )

                self.assertEqual(first_status, HTTPStatus.OK)
                self.assertEqual(second_status, HTTPStatus.OK)
                self.assertNotEqual(first_id, second_id)
                self.assertEqual(sessions_status, HTTPStatus.OK)
                self.assertEqual(
                    {
                        item["session_id"]
                        for item in json.loads(sessions_body)["sessions"]
                    },
                    {first_id, second_id},
                )
                self.assertEqual(stop_status, HTTPStatus.OK)
                self.assertIsNone(
                    state.current_project_shell_session(context_id, first_id)
                )
                self.assertIsNotNone(
                    state.current_project_shell_session(context_id, second_id)
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

    def test_documentation_sidecar_can_run_while_design_lock_is_active(self) -> None:
        class FakeActiveSession:
            label = "design agent"
            kind = "design"
            interactive = True
            lock_names = SESSION_ARTIFACT_LOCKS["design"]
            session_id = "design-session"
            returncode = None
            command: list[str] = []
            created_at = ""

            def is_active(self) -> bool:
                return True

        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            with state.lock:
                context = state.contexts[context_id]
                context.design_session = FakeActiveSession()  # type: ignore[assignment]

            with mock.patch("electroboy.service.AgentSession.start"):
                session, started = state.start_documentation_agent(context_id)

        self.assertTrue(started)
        self.assertEqual(session.kind, "documentation")

    def test_artifact_lock_blocks_conflicting_design_review_session(self) -> None:
        class FakeActiveSession:
            label = "design agent"
            kind = "design"
            interactive = True
            lock_names = SESSION_ARTIFACT_LOCKS["design"]
            session_id = "design-session"
            returncode = None
            command: list[str] = []
            created_at = ""

            def is_active(self) -> bool:
                return True

        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            with state.lock:
                context = state.contexts[context_id]
                context.workflow_stage = "design-review"
                context.design_session = FakeActiveSession()  # type: ignore[assignment]

            with self.assertRaisesRegex(AgentSessionError, "docs/detailed-design"):
                state.start_design_review_agent(context_id)

    def test_new_context_starts_without_active_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            StateStore(root).init_run(run_id="run-1")

            state = ServiceState(root)
            payload = state.create_context()

        self.assertIsNone(payload["active_project_root"])
        self.assertIsNone(payload["activation_root"])
        self.assertEqual(payload["project_mode"], "none")
        self.assertIsNone(payload["active_repository_name"])
        self.assertEqual(payload["registered_repositories"], [])
        self.assertEqual(payload["service_root"], str(root.resolve()))
        self.assertFalse(payload["requirements_started"])
        self.assertFalse(payload["requirements_running"])
        self.assertFalse(payload["design_started"])
        self.assertFalse(payload["design_running"])
        self.assertFalse(payload["design_review_started"])
        self.assertFalse(payload["design_review_running"])
        self.assertFalse(payload["design_review_interactive"])

    def test_project_status_payload_requires_active_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = ServiceState(Path(tmp))
            context_id = str(state.create_context()["context_id"])

            with self.assertRaisesRegex(StateError, "activate a project first"):
                state.project_status_payload(context_id)

    def test_project_status_payload_reads_active_project_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            with mock.patch(
                "electroboy.service.app._status_snapshot",
                return_value=("active stage: requirements\n", True),
            ) as status_snapshot:
                payload = state.project_status_payload(context_id)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["output"], "active stage: requirements\n")
        status_snapshot.assert_called_once_with(project_root.resolve())

    def test_project_payload_reports_running_requirements_session(self) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.terminated = False

            def is_active(self) -> bool:
                return not self.terminated

        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            session = FakeSession()
            with state.lock:
                state.contexts[context_id].requirements_session = session  # type: ignore[assignment]

            running_payload = state.project_payload(context_id)
            session.terminated = True
            stopped_payload = state.project_payload(context_id)

        self.assertTrue(running_payload["requirements_running"])
        self.assertFalse(stopped_payload["requirements_running"])

    def test_project_payload_reports_running_design_sessions(self) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.terminated = False

            def is_active(self) -> bool:
                return not self.terminated

        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            design_session = FakeSession()
            review_session = FakeSession()
            with state.lock:
                context = state.contexts[context_id]
                context.design_session = design_session  # type: ignore[assignment]
                context.design_review_session = review_session  # type: ignore[assignment]
                context.design_review_interactive = True

            running_payload = state.project_payload(context_id)
            design_session.terminated = True
            review_session.terminated = True
            stopped_payload = state.project_payload(context_id)

        self.assertTrue(running_payload["design_running"])
        self.assertTrue(running_payload["design_review_running"])
        self.assertTrue(running_payload["design_review_interactive"])
        self.assertFalse(stopped_payload["design_running"])
        self.assertFalse(stopped_payload["design_review_running"])
        self.assertFalse(stopped_payload["design_review_interactive"])

    def test_service_state_keeps_project_activation_per_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            first_project = Path(tmp) / "first"
            second_project = Path(tmp) / "second"
            service_root.mkdir()
            first_project.mkdir()
            second_project.mkdir()
            StateStore(first_project).init_run(run_id="run-1")
            StateStore(second_project).init_run(run_id="run-2")

            state = ServiceState(service_root)
            first_context = str(state.create_context()["context_id"])
            second_context = str(state.create_context()["context_id"])

            state.open_project(first_context, str(first_project))

            self.assertEqual(
                state.project_payload(first_context)["active_project_root"],
                str(first_project.resolve()),
            )
            self.assertIsNone(
                state.project_payload(second_context)["active_project_root"]
            )

            state.open_project(second_context, str(second_project))

            self.assertEqual(
                state.project_payload(first_context)["active_project_root"],
                str(first_project.resolve()),
            )
            self.assertEqual(
                state.project_payload(second_context)["active_project_root"],
                str(second_project.resolve()),
            )

    def test_project_deactivation_is_scoped_to_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            first_project = Path(tmp) / "first"
            second_project = Path(tmp) / "second"
            service_root.mkdir()
            first_project.mkdir()
            second_project.mkdir()
            StateStore(first_project).init_run(run_id="run-1")
            StateStore(second_project).init_run(run_id="run-2")

            state = ServiceState(service_root)
            first_context = str(state.create_context()["context_id"])
            second_context = str(state.create_context()["context_id"])
            state.open_project(first_context, str(first_project))
            state.open_project(second_context, str(second_project))

            payload = state.deactivate_project(first_context)

            self.assertEqual(payload["status"], "deactivated")
            self.assertIsNone(
                state.project_payload(first_context)["active_project_root"]
            )
            self.assertEqual(
                state.project_payload(second_context)["active_project_root"],
                str(second_project.resolve()),
            )

    def test_project_deactivation_terminates_running_requirements_agent(self) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.terminated = False

            def is_active(self) -> bool:
                return not self.terminated

            def terminate(self) -> None:
                self.terminated = True

        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            session = FakeSession()
            with state.lock:
                state.contexts[context_id].requirements_session = session  # type: ignore[assignment]

            payload = state.deactivate_project(context_id)

        self.assertTrue(session.terminated)
        self.assertEqual(payload["status"], "deactivated")
        self.assertIsNone(payload["active_project_root"])
        self.assertIsNone(state.current_requirements_session(context_id))

    def test_requirements_approve_terminates_agent_and_advances_to_design(self) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.terminated = False

            def is_active(self) -> bool:
                return not self.terminated

            def terminate(self) -> None:
                self.terminated = True

        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            initialize_git_repo(project_root)
            write_file(project_root / "docs" / "requirements.md", "# Requirements\n")
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            session = FakeSession()
            with state.lock:
                state.contexts[context_id].requirements_session = session  # type: ignore[assignment]
                state.contexts[context_id].requirements_started = True

            payload = state.approve_requirements(context_id)

        self.assertTrue(session.terminated)
        self.assertEqual(payload["status"], "approved")
        self.assertEqual(payload["workflow_stage"], "design")
        self.assertTrue(payload["requirements_started"])
        self.assertTrue(payload["requirements_approved"])
        self.assertEqual(payload["next_stage"], "design")
        self.assertEqual(payload["active_project_root"], str(project_root.resolve()))
        self.assertIsNone(state.current_requirements_session(context_id))

    def test_requirements_restart_and_document_require_start_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            with self.assertRaisesRegex(AgentSessionError, "start requirements first"):
                state.restart_requirements_agent(context_id)
            with self.assertRaisesRegex(AgentSessionError, "start requirements first"):
                state.requirements_document_root(context_id)

    def test_requirements_approval_can_run_before_start_with_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            initialize_git_repo(project_root)
            write_file(project_root / "docs" / "requirements.md", "# Requirements\n")
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            payload = state.approve_requirements(context_id)

        self.assertEqual(payload["status"], "approved")
        self.assertEqual(payload["workflow_stage"], "design")
        self.assertFalse(payload["requirements_started"])
        self.assertEqual(payload["next_stage"], "design")
        self.assertTrue(payload["requirements_approved"])
        self.assertIsNone(state.current_requirements_session(context_id))

    def test_service_state_selects_workflow_stage_after_activation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            payload = state.select_workflow_stage(context_id, "design")
            manifest = StateStore(project_root).load_current_manifest()

        self.assertEqual(payload["status"], "selected")
        self.assertEqual(payload["previous_stage"], "requirements")
        self.assertFalse(payload["terminated_agent"])
        self.assertIsNotNone(payload["reset_decision"])
        self.assertIn("forced stage reset: yes", str(payload["reset_output"]))
        self.assertEqual(payload["workflow_stage"], "design")
        self.assertEqual(payload["active_project_root"], str(project_root.resolve()))
        self.assertEqual(manifest.active_stage, STAGE_DESIGN)

    def test_service_state_rejects_direct_approval_stage_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            with self.assertRaisesRegex(
                StateError,
                "approval stage is not directly selectable",
            ):
                state.select_workflow_stage(context_id, "requirements-approve")

    def test_service_state_rejects_workflow_stage_selection_before_activation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = ServiceState(Path(tmp))
            context_id = str(state.create_context()["context_id"])

            with self.assertRaisesRegex(StateError, "activate a project first"):
                state.select_workflow_stage(context_id, "design")
            with self.assertRaisesRegex(StateError, "unknown workflow stage"):
                state.select_workflow_stage(context_id, "project")

    def test_service_state_terminates_requirements_agent_when_jumping_stage(self) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.terminated = False

            def is_active(self) -> bool:
                return not self.terminated

            def terminate(self) -> None:
                self.terminated = True

        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            session = FakeSession()
            with state.lock:
                state.contexts[context_id].requirements_session = session  # type: ignore[assignment]

            payload = state.select_workflow_stage(context_id, "design")
            manifest = StateStore(project_root).load_current_manifest()

        self.assertTrue(session.terminated)
        self.assertTrue(payload["terminated_agent"])
        self.assertIsNotNone(payload["reset_decision"])
        self.assertEqual(payload["workflow_stage"], "design")
        self.assertIsNone(state.current_requirements_session(context_id))
        self.assertEqual(manifest.active_stage, STAGE_DESIGN)

    def test_after_requirements_approval_only_allows_requirements_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            initialize_git_repo(project_root)
            write_file(project_root / "docs" / "requirements.md", "# Requirements\n")
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            state.approve_requirements(context_id)

            with self.assertRaisesRegex(
                AgentSessionError,
                "requirements stage is not active",
            ):
                state.start_requirements_agent(context_id)
            with self.assertRaisesRegex(
                AgentSessionError,
                "requirements stage is not active",
            ):
                state.complete_requirements_agent(context_id)
            self.assertEqual(
                state.requirements_document_root(context_id),
                project_root.resolve(),
            )

            with mock.patch("electroboy.service.AgentSession.start"):
                _session, started = state.restart_requirements_agent(context_id)

            payload = state.project_payload(context_id)

        self.assertTrue(started)
        self.assertEqual(payload["workflow_stage"], "requirements")
        self.assertTrue(payload["requirements_started"])

    def test_requirements_approval_advances_to_design(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            with state.lock:
                state.contexts[context_id].workflow_stage = "requirements-approve"

            with mock.patch(
                "electroboy.workflows.software.cli._cmd_stage",
                return_value=0,
            ):
                payload = state.approve_requirements(context_id)

        self.assertEqual(payload["status"], "approved")
        self.assertEqual(payload["workflow_stage"], "design")
        self.assertEqual(payload["next_stage"], "design")

    def test_design_complete_terminates_agent_and_moves_to_review(self) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.terminated = False

            def is_active(self) -> bool:
                return not self.terminated

            def terminate(self) -> None:
                self.terminated = True

        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            session = FakeSession()
            with state.lock:
                context = state.contexts[context_id]
                context.workflow_stage = "design"
                context.design_session = session  # type: ignore[assignment]
                context.design_started = True
                context.design_review_started = True
                context.design_review_interactive = True

            payload = state.complete_design_agent(context_id)

        self.assertTrue(session.terminated)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["workflow_stage"], "design-review")
        self.assertTrue(payload["design_started"])
        self.assertFalse(payload["design_review_started"])
        self.assertFalse(payload["design_review_interactive"])
        self.assertEqual(payload["next_stage"], "design-review")

    def test_design_restart_only_runs_when_design_is_not_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            with state.lock:
                state.contexts[context_id].workflow_stage = "design"

            with self.assertRaisesRegex(AgentSessionError, "design stage is already active"):
                state.restart_design_agent(context_id)

            with state.lock:
                context = state.contexts[context_id]
                context.workflow_stage = "design-review"
                context.design_review_started = True
                context.design_review_interactive = True
            with mock.patch("electroboy.service.AgentSession.start"):
                _session, started = state.restart_design_agent(context_id)

            payload = state.project_payload(context_id)

        self.assertTrue(started)
        self.assertEqual(payload["workflow_stage"], "design")
        self.assertTrue(payload["design_started"])
        self.assertFalse(payload["design_review_started"])
        self.assertFalse(payload["design_review_interactive"])

    def test_design_review_completion_stays_on_review_for_folded_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            with state.lock:
                state.contexts[context_id].workflow_stage = "design-review"

            state._mark_design_review_completed(context_id, 1)
            failed_payload = state.project_payload(context_id)
            state._mark_design_review_completed(context_id, 0)
            passed_payload = state.project_payload(context_id)

        self.assertEqual(failed_payload["workflow_stage"], "design-review")
        self.assertEqual(passed_payload["workflow_stage"], "design-review")
        self.assertTrue(passed_payload["design_review_started"])

    def test_interactive_design_review_start_uses_interactive_cli_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            with state.lock:
                state.contexts[context_id].workflow_stage = "design-review"

            with mock.patch("electroboy.service.AgentSession.start"):
                session, started = state.start_design_review_agent(
                    context_id,
                    interactive=True,
                )
            with state.lock:
                context = state.contexts[context_id]
                stored_interactive = context.design_review_interactive

        self.assertTrue(started)
        self.assertIn("--interactive", session.command)
        self.assertEqual(session.label, "interactive design-review agent")
        self.assertIsNone(session.on_completed)
        self.assertTrue(stored_interactive)

    def test_design_review_stop_terminates_session_without_advancing(self) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.terminated = False

            def is_active(self) -> bool:
                return not self.terminated

            def terminate(self) -> None:
                self.terminated = True

        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            session = FakeSession()
            with state.lock:
                context = state.contexts[context_id]
                context.workflow_stage = "design-review"
                context.design_review_started = True
                context.design_review_session = session  # type: ignore[assignment]

            payload = state.stop_design_review_agent(context_id)

        self.assertTrue(session.terminated)
        self.assertEqual(payload["status"], "stopped")
        self.assertEqual(payload["workflow_stage"], "design-review")
        self.assertTrue(payload["design_review_started"])
        self.assertFalse(payload["design_review_running"])

    def test_design_review_approve_terminates_session_and_advances(self) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.terminated = False

            def is_active(self) -> bool:
                return not self.terminated

            def terminate(self) -> None:
                self.terminated = True

        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            session = FakeSession()
            with state.lock:
                context = state.contexts[context_id]
                context.workflow_stage = "design-review"
                context.design_review_started = True
                context.design_review_session = session  # type: ignore[assignment]

            with mock.patch(
                "electroboy.workflows.software.cli._cmd_stage",
                return_value=0,
            ) as cmd_stage:
                payload = state.approve_design(context_id)

            stage_args = [call.args[2] for call in cmd_stage.call_args_list]

        self.assertTrue(session.terminated)
        self.assertEqual([args.stage for args in stage_args], [STAGE_DESIGN_REVIEW, STAGE_DESIGN_ACCEPTANCE])
        self.assertTrue(stage_args[0].force)
        self.assertFalse(stage_args[1].force)
        self.assertEqual(payload["status"], "approved")
        self.assertEqual(payload["workflow_stage"], "implementation-plan")
        self.assertEqual(payload["next_stage"], "implementation-plan")
        self.assertTrue(payload["design_review_started"])
        self.assertFalse(payload["design_review_running"])

    def test_design_approval_advances_to_implementation_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            with state.lock:
                state.contexts[context_id].workflow_stage = "design-approve"

            with mock.patch(
                "electroboy.workflows.software.cli._cmd_stage",
                return_value=0,
            ):
                payload = state.approve_design(context_id)

        self.assertEqual(payload["status"], "approved")
        self.assertEqual(payload["workflow_stage"], "implementation-plan")
        self.assertEqual(payload["next_stage"], "implementation-plan")

    def test_design_skip_approval_force_records_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            with state.lock:
                context = state.contexts[context_id]
                context.workflow_stage = "design-review"
                context.design_review_started = True

            with mock.patch(
                "electroboy.workflows.software.cli._cmd_stage",
                return_value=0,
            ) as cmd_stage:
                payload = state.approve_design(context_id, skip_approval=True)

            stage_args = [call.args[2] for call in cmd_stage.call_args_list]

        self.assertEqual([args.stage for args in stage_args], [STAGE_DESIGN_REVIEW, STAGE_DESIGN_ACCEPTANCE])
        self.assertTrue(stage_args[0].force)
        self.assertTrue(stage_args[1].force)
        self.assertEqual(payload["status"], "skipped")
        self.assertEqual(payload["workflow_stage"], "implementation-plan")
        self.assertEqual(payload["next_stage"], "implementation-plan")
        self.assertIn("WARNING: design approval was skipped", str(payload["warning"]))

    def test_completed_requirements_approval_force_records_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            initialize_git_repo(project_root)
            write_file(project_root / "docs" / "requirements.md", "# Requirements\n")
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            payload = state.approve_requirements(context_id)
            store = StateStore(project_root)
            approvals = store.read_approvals()

        self.assertEqual(payload["status"], "approved")
        self.assertEqual(payload["workflow_stage"], "design")
        self.assertEqual(payload["next_stage"], "design")
        self.assertIn("forced approval: yes", str(payload["output"]))
        self.assertTrue(
            any(
                approval.get("stage") == STAGE_REQUIREMENTS
                and approval.get("approval_type") == "author-confirmation"
                and "force-recorded" in str(approval.get("summary"))
                for approval in approvals
            )
        )

    def test_requirements_skip_approval_records_warning_and_advances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            initialize_git_repo(project_root)
            write_file(project_root / "docs" / "requirements.md", "# Requirements\n")
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            payload = state.approve_requirements(context_id, skip_approval=True)
            store = StateStore(project_root)
            approvals = store.read_approvals()

        self.assertEqual(payload["status"], "skipped")
        self.assertEqual(payload["workflow_stage"], "design")
        self.assertEqual(payload["next_stage"], "design")
        self.assertIn("WARNING: requirements approval was skipped", str(payload["warning"]))
        self.assertIn("forced approval: yes", str(payload["output"]))
        self.assertTrue(
            any(
                approval.get("stage") == STAGE_REQUIREMENTS
                and approval.get("approval_type") == "human-approval"
                and "force-recorded" in str(approval.get("summary"))
                for approval in approvals
            )
        )

    def test_requirements_approval_requires_requirements_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            with state.lock:
                state.contexts[context_id].workflow_stage = "design"

            with self.assertRaisesRegex(
                AgentSessionError,
                "requirements stage is not active",
            ):
                state.approve_requirements(context_id)

    def test_failed_requirements_start_does_not_unlock_later_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))

            with mock.patch(
                "electroboy.service.AgentSession.start",
                side_effect=OSError("boom"),
            ):
                with self.assertRaisesRegex(OSError, "boom"):
                    state.start_requirements_agent(context_id)

            self.assertFalse(state.project_payload(context_id)["requirements_started"])
            self.assertIsNone(state.current_requirements_session(context_id))

    def test_requirements_restart_reopens_requirements_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            store = StateStore(project_root)
            manifest = store.init_run(run_id="run-1")
            manifest.set_active_stage(STAGE_DESIGN)
            store.save_manifest(manifest)

            _reopen_requirements_for_restart(project_root)

            manifest = store.load_current_manifest()
            change_requests = store.read_change_requests()

        self.assertEqual(manifest.active_stage, STAGE_REQUIREMENTS)
        self.assertTrue(change_requests)

    def test_service_state_rejects_unknown_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = ServiceState(Path(tmp))

            with self.assertRaisesRegex(StateError, "unknown browser context"):
                state.project_payload("missing")

    def test_browse_directories_lists_child_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "alpha").mkdir()
            (root / "file.txt").write_text("ignored\n", encoding="utf-8")

            payload = browse_directories(root)

        self.assertEqual(payload["path"], str(root.resolve()))
        self.assertIn(
            {"name": "alpha", "path": str((root / "alpha").resolve())},
            payload["entries"],
        )

    def test_browse_files_lists_directories_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "alpha").mkdir()
            (root / "example.txt").write_text("example\n", encoding="utf-8")

            payload = browse_files(root)

        self.assertIn(
            {
                "name": "alpha",
                "path": str((root / "alpha").resolve()),
                "type": "directory",
            },
            payload["entries"],
        )
        self.assertIn(
            {
                "name": "example.txt",
                "path": str((root / "example.txt").resolve()),
                "type": "file",
            },
            payload["entries"],
        )

    def test_browse_files_hides_dotfiles_unless_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hidden").mkdir()
            (root / "visible").mkdir()

            hidden_payload = browse_files(root)
            visible_payload = browse_files(root, show_hidden=True)

        hidden_names = {entry["name"] for entry in hidden_payload["entries"]}
        visible_names = {entry["name"] for entry in visible_payload["entries"]}
        self.assertNotIn(".hidden", hidden_names)
        self.assertIn("visible", hidden_names)
        self.assertIn(".hidden", visible_names)

    def test_browse_markdown_files_lists_directories_and_markdown_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "README.md").write_text("# Readme\n", encoding="utf-8")
            (root / "notes.txt").write_text("notes\n", encoding="utf-8")

            payload = browse_markdown_files(root)

        names = {entry["name"] for entry in payload["entries"]}
        self.assertIn("docs", names)
        self.assertIn("README.md", names)
        self.assertNotIn("notes.txt", names)

    def test_requirements_document_html_renders_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "requirements.md").write_text(
                "# Requirements\n\n- First requirement\n",
                encoding="utf-8",
            )

            page, status = requirements_document_html(root)

        self.assertEqual(status.value, 200)
        self.assertIn("<h1>Requirements</h1>", page)
        self.assertIn("First requirement", page)

    def test_requirements_document_html_uses_feature_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            StateStore(root).init_run(run_id="run-1")
            (docs / "requirements.md").write_text(
                "# Requirements\n\nGeneric requirements\n",
                encoding="utf-8",
            )
            (docs / "requirements-munge.md").write_text(
                "# Requirements\n\nFeature requirements\n",
                encoding="utf-8",
            )
            feature_path = (
                root / ".electroboy" / "shared" / "runs" / "run-1" / "feature.json"
            )
            feature_path.write_text(
                json.dumps(
                    {
                        "slug": "munge",
                        "artifacts": {
                            "requirements": "docs/requirements-munge.md",
                        },
                    }
                ),
                encoding="utf-8",
            )

            page, status = requirements_document_html(root)

        self.assertEqual(status.value, 200)
        self.assertIn("Feature requirements", page)
        self.assertNotIn("Generic requirements", page)

    def test_requirements_document_html_supports_embedded_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "requirements.md").write_text(
                "# Requirements\n",
                encoding="utf-8",
            )

            page, status = requirements_document_html(root, embedded=True)

        self.assertEqual(status.value, 200)
        self.assertIn("max-width: none;", page)
        self.assertIn("margin: 0;", page)
        self.assertIn("padding: 16px;", page)
        self.assertIn("border: 0;", page)

    def test_file_signature_reports_artifact_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "docs" / "requirements.md"
            missing = _file_signature(path)
            path.parent.mkdir()
            path.write_text("# Requirements\n", encoding="utf-8")
            present = _file_signature(path)

        self.assertFalse(missing["exists"])
        self.assertEqual(missing["size"], 0)
        self.assertTrue(present["exists"])
        self.assertEqual(present["size"], len("# Requirements\n"))
        self.assertIsInstance(present["mtime_ns"], int)

    def test_agent_session_streams_output_and_accepts_messages(self) -> None:
        script = (
            "import sys\n"
            "print('ready', flush=True)\n"
            "line = sys.stdin.readline()\n"
            "print('got:' + line.strip(), flush=True)\n"
        )
        session = AgentSession([sys.executable, "-c", script], ROOT)
        try:
            try:
                session.start()
            except PermissionError as error:
                self.skipTest(f"pseudo-terminal creation is not permitted: {error}")
            self.assertIn("ready", wait_for_output(self, session, "ready"))

            session.send("hello agent")

            output = wait_for_output(self, session, "got:hello agent")
            self.assertIn("got:hello agent", output)
            wait_for_exit(self, session)
            self.assertFalse(session.is_active())
        finally:
            if session.is_active() and session.process is not None:
                session.process.terminate()

    def test_agent_session_clamps_terminal_dimensions(self) -> None:
        session = AgentSession(
            [sys.executable, "-c", "pass"],
            ROOT,
            columns=MAX_TERMINAL_COLUMNS + 500,
            rows=MAX_TERMINAL_ROWS + 500,
        )

        self.assertEqual(session.columns, MAX_TERMINAL_COLUMNS)
        self.assertEqual(session.rows, MAX_TERMINAL_ROWS)

        session.resize(850, 64)

        self.assertEqual(session.columns, 850)
        self.assertEqual(session.rows, 64)

        session.resize(MIN_TERMINAL_COLUMNS - 1, MIN_TERMINAL_ROWS - 1)

        self.assertEqual(session.columns, MIN_TERMINAL_COLUMNS)
        self.assertEqual(session.rows, MIN_TERMINAL_ROWS)

    def test_agent_session_can_claim_pty_as_controlling_terminal(self) -> None:
        script = (
            "import os\n"
            "descriptor = os.open('/dev/tty', os.O_RDWR)\n"
            "os.close(descriptor)\n"
            "assert os.tcgetpgrp(0) == os.getpgrp()\n"
            "print('controlling-terminal-ready', flush=True)\n"
        )
        session = AgentSession(
            [sys.executable, "-c", script],
            ROOT,
            controlling_terminal=True,
        )
        try:
            try:
                session.start()
            except PermissionError as error:
                self.skipTest(f"pseudo-terminal creation is not permitted: {error}")
            output = wait_for_output(
                self,
                session,
                "controlling-terminal-ready",
            )
            self.assertIn("controlling-terminal-ready", output)
            wait_for_exit(self, session)
        finally:
            if session.is_active():
                session.terminate()

    def test_agent_session_writes_transcript_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript_path = Path(tmp) / "session.jsonl"
            session = AgentSession([sys.executable, "-c", "pass"], ROOT)
            session.persist_to(
                context_id="ctx-1",
                transcript_path=transcript_path,
            )

            session._append_event(  # pylint: disable=protected-access
                {
                    "type": "output",
                    "text": "hello\n",
                    "terminal": "hello\r\n",
                }
            )

            events = session.events()
            markdown = _session_events_markdown(session)

        self.assertEqual(events[0]["text"], "hello\n")
        self.assertEqual(events[0]["terminal"], "hello\r\n")
        self.assertIn("hello", markdown)

    def test_agent_session_resize_signals_process_group(self) -> None:
        session = AgentSession([sys.executable, "-c", "pass"], ROOT)
        session._master_fd = 123
        session.process = mock.Mock()
        session.process.pid = 456
        session.process.poll.return_value = None

        with (
            mock.patch("electroboy.service.sessions._set_terminal_size") as set_size,
            mock.patch("electroboy.service.sessions.os.killpg") as killpg,
        ):
            session.resize(100, 40)

        set_size.assert_called_once_with(123, 100, 40)
        killpg.assert_called_once_with(456, signal.SIGWINCH)

    def test_agent_session_submits_raw_terminal_input(self) -> None:
        script = (
            "import sys\n"
            "import termios\n"
            "import tty\n"
            "print('ready', flush=True)\n"
            "fd = sys.stdin.fileno()\n"
            "old = termios.tcgetattr(fd)\n"
            "chars = []\n"
            "try:\n"
            "    tty.setraw(fd)\n"
            "    while True:\n"
            "        ch = sys.stdin.read(1)\n"
            "        if ch in {'\\r', '\\n'}:\n"
            "            break\n"
            "        chars.append(ch)\n"
            "finally:\n"
            "    termios.tcsetattr(fd, termios.TCSANOW, old)\n"
            "print('raw:' + ''.join(chars), flush=True)\n"
            "print('submit:' + repr(ch), flush=True)\n"
        )
        session = AgentSession([sys.executable, "-c", script], ROOT)
        try:
            try:
                session.start()
            except PermissionError as error:
                self.skipTest(f"pseudo-terminal creation is not permitted: {error}")
            self.assertIn("ready", wait_for_output(self, session, "ready"))

            session.send("hello agent")

            self.assertIn("raw:hello agent", wait_for_output(self, session, "raw:"))
            self.assertIn("submit:'\\r'", wait_for_output(self, session, "submit:"))
            wait_for_exit(self, session)
            self.assertFalse(session.is_active())
        finally:
            if session.is_active() and session.process is not None:
                session.process.terminate()

    def test_agent_session_writes_raw_terminal_data(self) -> None:
        script = (
            "import sys\n"
            "print('ready', flush=True)\n"
            "line = sys.stdin.readline()\n"
            "print('raw:' + line.strip(), flush=True)\n"
        )
        session = AgentSession([sys.executable, "-c", script], ROOT)
        try:
            try:
                session.start()
            except PermissionError as error:
                self.skipTest(f"pseudo-terminal creation is not permitted: {error}")
            self.assertIn("ready", wait_for_output(self, session, "ready"))

            session.send_raw("shell input\n")

            self.assertIn("raw:shell input", wait_for_output(self, session, "raw:"))
            wait_for_exit(self, session)
            self.assertFalse(session.is_active())
        finally:
            if session.is_active() and session.process is not None:
                session.process.terminate()

    def test_agent_session_sends_named_terminal_key(self) -> None:
        script = (
            "import sys\n"
            "import termios\n"
            "import tty\n"
            "print('ready', flush=True)\n"
            "fd = sys.stdin.fileno()\n"
            "old = termios.tcgetattr(fd)\n"
            "try:\n"
            "    tty.setraw(fd)\n"
            "    key = sys.stdin.read(1)\n"
            "finally:\n"
            "    termios.tcsetattr(fd, termios.TCSANOW, old)\n"
            "print('key:' + repr(key), flush=True)\n"
        )
        session = AgentSession([sys.executable, "-c", script], ROOT)
        try:
            try:
                session.start()
            except PermissionError as error:
                self.skipTest(f"pseudo-terminal creation is not permitted: {error}")
            self.assertIn("ready", wait_for_output(self, session, "ready"))

            session.send_key("enter")

            self.assertIn("key:'\\r'", wait_for_output(self, session, "key:"))
            wait_for_exit(self, session)
            self.assertFalse(session.is_active())
        finally:
            if session.is_active() and session.process is not None:
                session.process.terminate()

    def test_agent_session_interrupts_running_process(self) -> None:
        script = (
            "import os\n"
            "import sys\n"
            "import termios\n"
            "import tty\n"
            "print('ready', flush=True)\n"
            "fd = sys.stdin.fileno()\n"
            "old = termios.tcgetattr(fd)\n"
            "try:\n"
            "    tty.setraw(fd)\n"
            "    key = sys.stdin.read(1)\n"
            "finally:\n"
            "    termios.tcsetattr(fd, termios.TCSANOW, old)\n"
            "if key == '\\x1b':\n"
            "    print('interrupted', flush=True)\n"
            "    os._exit(0)\n"
            "os._exit(1)\n"
        )
        session = AgentSession([sys.executable, "-c", script], ROOT)
        try:
            try:
                session.start()
            except PermissionError as error:
                self.skipTest(f"pseudo-terminal creation is not permitted: {error}")
            self.assertIn("ready", wait_for_output(self, session, "ready"))

            session.interrupt()

            self.assertIn(
                "interrupted",
                wait_for_output(self, session, "interrupted"),
            )
            wait_for_exit(self, session)
            self.assertFalse(session.is_active())
        finally:
            if session.is_active() and session.process is not None:
                session.process.terminate()

    def test_agent_session_terminate_stops_running_process(self) -> None:
        script = (
            "import time\n"
            "print('ready', flush=True)\n"
            "time.sleep(30)\n"
        )
        session = AgentSession([sys.executable, "-c", script], ROOT)
        try:
            try:
                session.start()
            except PermissionError as error:
                self.skipTest(f"pseudo-terminal creation is not permitted: {error}")
            self.assertIn("ready", wait_for_output(self, session, "ready"))

            session.terminate()

            self.assertFalse(session.is_active())
            self.assertIsNotNone(session.returncode)
            self.assertNotEqual(session.returncode, 0)
        finally:
            if session.is_active():
                session.terminate()

    def test_agent_session_terminate_stops_detached_child_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            child_pid_path = Path(tmp) / "child.pid"
            child_script = "import time\nprint('child', flush=True)\ntime.sleep(30)\n"
            parent_script = (
                "import pathlib\n"
                "import subprocess\n"
                "import sys\n"
                "import time\n"
                "pid_path = pathlib.Path(sys.argv[1])\n"
                "child = subprocess.Popen(\n"
                "    [sys.executable, '-c', sys.argv[2]],\n"
                "    start_new_session=True,\n"
                ")\n"
                "pid_path.write_text(str(child.pid), encoding='utf-8')\n"
                "print('ready', flush=True)\n"
                "time.sleep(30)\n"
            )
            session = AgentSession(
                [sys.executable, "-c", parent_script, str(child_pid_path), child_script],
                ROOT,
            )
            child_pid = 0
            try:
                try:
                    session.start()
                except PermissionError as error:
                    self.skipTest(f"pseudo-terminal creation is not permitted: {error}")
                self.assertIn("ready", wait_for_output(self, session, "ready"))
                child_pid = int(child_pid_path.read_text(encoding="utf-8"))

                session.terminate()

                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and process_exists(child_pid):
                    time.sleep(0.05)
                self.assertFalse(process_exists(child_pid))
            finally:
                if session.is_active():
                    session.terminate()
                if child_pid and process_exists(child_pid):
                    os.kill(child_pid, signal.SIGKILL)

    def test_agent_session_preserves_raw_terminal_output(self) -> None:
        script = (
            "import sys\n"
            "sys.stdout.write('\\x1b[31mred\\x1b[0m\\n')\n"
            "sys.stdout.flush()\n"
        )
        session = AgentSession([sys.executable, "-c", script], ROOT)
        try:
            try:
                session.start()
            except PermissionError as error:
                self.skipTest(f"pseudo-terminal creation is not permitted: {error}")
            self.assertIn("red", wait_for_output(self, session, "red"))
            wait_for_exit(self, session)
        finally:
            if session.is_active() and session.process is not None:
                session.process.terminate()

        output_events = [
            event for event in session.events_after(0)
            if event.get("type") == "output"
        ]
        self.assertTrue(output_events)
        terminal_output = "".join(
            str(event.get("terminal", "")) for event in output_events
        )
        text_output = "".join(str(event.get("text", "")) for event in output_events)
        self.assertIn("\x1b[31m", terminal_output)
        self.assertNotIn("\x1b[31m", text_output)

    def test_agent_process_env_prepends_absolute_module_path(self) -> None:
        original_pythonpath = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = "src"
        try:
            env = _agent_process_env()
        finally:
            if original_pythonpath is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = original_pythonpath

        entries = env["PYTHONPATH"].split(os.pathsep)
        self.assertEqual(entries[0], str((ROOT / "src").resolve()))
        self.assertIn("src", entries)
        self.assertEqual(env["TERM"], "xterm-256color")
        self.assertEqual(env["COLORTERM"], "truecolor")
        self.assertEqual(env["ELECTROBOY_DISABLE_SESSION_RESUME"], "1")
        self.assertNotIn("NO_COLOR", env)
        self.assertNotIn("CLICOLOR", env)
        self.assertNotIn("FORCE_COLOR", env)

    def test_terminal_output_cleaner_strips_ansi_screen_updates(self) -> None:
        raw = (
            "7 \x1b[1B\x1b[1G\x1b[K\x1b[1B\x1b[1G\x1b[K"
            " 8 \x1b[39;49m\x1b[K   \x1b[38;5;6;49mq"
            "\x1b[39m\x1b[49m\x1b[0m\n"
            "\x1b[39;49m\x1b[K \x1b[39m\x1b[49m\x1b[0m\n"
            "\x1b[?25l\x1b[?2026l\x1b]0;QFw\x1b\\\x1b[?2026h"
        )

        cleaned, pending = _clean_terminal_output(raw)

        self.assertEqual(pending, "")
        self.assertNotIn("\x1b", cleaned)
        self.assertIn("q", cleaned)
        self.assertNotIn("[1B", cleaned)
        self.assertNotIn("[39;49m", cleaned)
        self.assertNotIn("]0;QFw", cleaned)

    def test_terminal_output_cleaner_buffers_split_escape_sequences(self) -> None:
        cleaned, pending = _clean_terminal_output("plain \x1b[38;")
        self.assertEqual(cleaned, "plain ")
        self.assertEqual(pending, "\x1b[38;")

        cleaned, pending = _clean_terminal_output("5;6mgreen\x1b[0m", pending)

        self.assertEqual(cleaned, "green")
        self.assertEqual(pending, "")

    def test_terminal_output_cleaner_normalizes_carriage_returns(self) -> None:
        cleaned, pending = _clean_terminal_output("first\rsecond\r\nthird\b")

        self.assertEqual(pending, "")
        self.assertEqual(cleaned, "first\nsecond\nthir")

    def test_terminal_input_uses_enter_key_for_single_line_submit(self) -> None:
        self.assertEqual(_terminal_input_for_message("hello"), "hello\r")
        self.assertEqual(_terminal_input_chunks_for_message("hello"), ["hello", "\r"])

    def test_terminal_input_supports_named_enter_key(self) -> None:
        self.assertEqual(_terminal_input_for_key("enter"), "\r")
        self.assertEqual(_terminal_input_for_key("escape"), "\x1b")
        self.assertEqual(_terminal_input_for_key("up"), "\x1b[A")
        self.assertEqual(_terminal_input_for_key("down"), "\x1b[B")
        self.assertEqual(_terminal_input_for_key("backspace"), "\x7f")
        self.assertEqual(_terminal_input_for_key("delete"), "\x1b[3~")
        self.assertEqual(_terminal_input_for_key("1"), "1")
        with self.assertRaises(AgentSessionError):
            _terminal_input_for_key("space")

    def test_terminal_input_uses_bracketed_paste_for_multiline_submit(self) -> None:
        self.assertEqual(
            _terminal_input_for_message("line one\nline two\n"),
            "\x1b[200~line one\nline two\x1b[201~\r",
        )
        self.assertEqual(
            _terminal_input_chunks_for_message("line one\nline two\n"),
            ["\x1b[200~line one\nline two\x1b[201~", "\r"],
        )

    def test_requirements_command_sources_project_activation_when_available(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            activate = root / ".electroboy" / "bin" / "activate"
            activate.parent.mkdir(parents=True)
            activate.write_text("export ELECTROBOY_PROJECT_ROOT=x\n", encoding="utf-8")

            command = _requirements_command(root)

        self.assertEqual(command[:2], ["/bin/sh", "-c"])
        self.assertIn(". ", command[2])
        self.assertIn("-m electroboy --root", command[2])
        self.assertIn("requirements", command[2])

    def test_progress_command_sources_project_activation_when_available(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            activate = root / ".electroboy" / "bin" / "activate"
            activate.parent.mkdir(parents=True)
            activate.write_text("export ELECTROBOY_PROJECT_ROOT=x\n", encoding="utf-8")

            command = _progress_once_command(root)

        self.assertEqual(command[:2], ["/bin/sh", "-c"])
        self.assertIn(". ", command[2])
        self.assertIn("-m electroboy --root", command[2])
        self.assertIn("progress --once", command[2])

    def test_status_command_sources_project_activation_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            activate = root / ".electroboy" / "bin" / "activate"
            activate.parent.mkdir(parents=True)
            activate.write_text("export ELECTROBOY_PROJECT_ROOT=x\n", encoding="utf-8")

            command = _status_command(root)

        self.assertEqual(command[:2], ["/bin/sh", "-c"])
        self.assertIn(". ", command[2])
        self.assertIn("-m electroboy --root", command[2])
        self.assertIn("status", command[2])

    def test_progress_snapshot_reads_progress_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = StateStore(root)
            store.init_run(run_id="run-1")
            progress = (
                root
                / ".electroboy"
                / "shared"
                / "runs"
                / "run-1"
                / "progress"
                / "design-review-progress.md"
            )
            progress.parent.mkdir(parents=True)
            progress.write_text("- reviewing design\n", encoding="utf-8")

            output, ok = _progress_snapshot(root)

        self.assertTrue(ok)
        self.assertIn("design-review-progress.md", output)
        self.assertIn("- reviewing design", output)

    def test_status_snapshot_runs_status_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            completed = subprocess.CompletedProcess(
                args=["electroboy", "status"],
                returncode=0,
                stdout="active stage: requirements\n",
            )

            with mock.patch(
                "electroboy.service.app.subprocess.run",
                return_value=completed,
            ) as run:
                output, ok = _status_snapshot(root)

        self.assertTrue(ok)
        self.assertEqual(output, "active stage: requirements\n")
        self.assertEqual(run.call_args.kwargs["cwd"], root.resolve())

    def test_serve_accepts_subcommand_root_argument(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["serve", "--root", "/tmp/example", "--port", "0"])

        self.assertEqual(args.command, "serve")
        self.assertEqual(args.root, "/tmp/example")
        self.assertIsNone(args.host)
        self.assertEqual(args.port, 0)

    def test_document_accepts_sidecar_option(self) -> None:
        parser = build_parser()

        args = parser.parse_args(
            ["document", "--sidecar", "--interactive", "--target", "README.md"]
        )

        self.assertEqual(args.command, "document")
        self.assertTrue(args.sidecar)
        self.assertTrue(args.interactive)
        self.assertEqual(args.target, "README.md")


def request(
    server: object,
    path: str,
) -> tuple[int, str, str]:
    host, port = server.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=2)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        content_type = response.getheader("Content-Type", "")
    finally:
        connection.close()
    return response.status, body, content_type


def post_json(
    server: object,
    path: str,
    payload: dict[str, object],
) -> tuple[int, str, str]:
    host, port = server.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=2)
    try:
        connection.request(
            "POST",
            path,
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        content_type = response.getheader("Content-Type", "")
    finally:
        connection.close()
    return response.status, body, content_type


def request_bytes(
    server: object,
    path: str,
) -> tuple[int, bytes, str, dict[str, str]]:
    host, port = server.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=2)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        content_type = response.getheader("Content-Type", "")
        headers = {key: value for key, value in response.getheaders()}
    finally:
        connection.close()
    return response.status, body, content_type, headers


def wait_for_output(
    test_case: unittest.TestCase,
    session: AgentSession,
    expected: str,
    timeout: float = 3,
) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        output = "".join(
            str(event.get("text", ""))
            for event in session.events_after(0)
            if event.get("type") == "output"
        )
        if expected in output:
            return output
        time.sleep(0.05)
    test_case.fail(f"timed out waiting for {expected!r}")


def wait_for_exit(
    test_case: unittest.TestCase,
    session: AgentSession,
    timeout: float = 3,
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not session.is_active():
            return
        time.sleep(0.05)
    test_case.fail("timed out waiting for agent session to exit")


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def initialize_git_repo(root: Path) -> None:
    subprocess.run(
        ["git", "-C", str(root), "init"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.com"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Test User"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


if __name__ == "__main__":
    unittest.main()
