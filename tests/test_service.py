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
from urllib.parse import urlencode
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy import __version__  # noqa: E402
from electroboy.cli import build_parser  # noqa: E402
from electroboy.modules.agenda_workspace import render_agenda_html  # noqa: E402
from electroboy.modules.calendar_workspace import render_calendar_html  # noqa: E402
from electroboy.modules.mind_map_workspace import render_mind_map_html  # noqa: E402
from electroboy.modules.editable_mind_map_workspace import (  # noqa: E402
    render_editable_mind_map_html,
)
from electroboy.modules.mind_map_documents import (  # noqa: E402
    empty_mind_map,
    list_mind_maps,
    load_mind_map,
    normalize_mind_map,
    save_mind_map,
)
from electroboy.modules.creative_workspace import (  # noqa: E402
    render_corkboard_html,
)
from electroboy.service import (  # noqa: E402
    CREATIVE_SPLASH_IMAGE_ROUTE,
    FILE_BROWSER_WINDOW_HTML,
    GENERIC_STAGE_CONFIG,
    INDEX_HTML,
    SESSION_EVENT_REPLAY_LIMIT,
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
    _agent_event_cursor_id,
    _agent_process_env,
    _artifact_event_document_path,
    _clean_terminal_output,
    _file_signature,
    _limited_session_replay_events,
    _parse_agent_event_cursor,
    _progress_once_command,
    _progress_snapshot,
    _progress_snapshot_markdown,
    _reopen_requirements_for_restart,
    _requirements_command,
    _session_events_markdown,
    _service_session_records_path,
    _status_command,
    _status_snapshot,
    _terminal_output_is_transient_control,
    _terminal_input_chunks_for_message,
    _terminal_input_for_key,
    _terminal_input_for_message,
    _tmux_capture_delta,
    artifact_editor_html,
    browse_directories,
    browse_files,
    browse_markdown_files,
    create_server,
    creative_corkboard_html,
    document_target_html,
    external_link_html,
    file_browser_window_html,
    frontend_debug,
    pane_window_html,
    requirements_document_html,
    save_artifact_edit,
    splash_image_bytes,
    workflow_payload,
)
from electroboy.service.agenda import normalize_agenda_snapshot  # noqa: E402
from electroboy.service.calendar import normalize_calendar_snapshot  # noqa: E402
from electroboy.service.mind_map import normalize_mind_map_snapshot  # noqa: E402
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
                    assets=(
                        "css/sample.css",
                        "js/modules/sample.js",
                    ),
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
            "<!-- __ELECTROBOY_CONTRIBUTION_STYLES__ -->\n"
            "<!-- __ELECTROBOY_CONTRIBUTION_SCRIPTS__ -->\n"
            '<script src="/assets/service/js/core/runtime.js"></script>'
        )

        page = render_service_index(template, modules, workflows)

        self.assertIn("/assets/service/js/modules/sample.js", page)
        self.assertIn("/assets/service/js/workflows/sample.js", page)
        self.assertIn(
            '<link rel="stylesheet" href="/assets/service/css/sample.css">',
            page,
        )
        self.assertNotIn(
            '<script src="/assets/service/css/sample.css"></script>',
            page,
        )
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
        self.assertEqual(payload["version"], __version__)
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

    def test_frontend_debug_endpoint_records_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            state_root = Path(tmp) / "state"
            root.mkdir()
            state_root.mkdir()
            try:
                server = create_server(root, port=0, state_root=state_root)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = post_json(
                    server,
                    "/api/frontend/debug",
                    {
                        "reason": "test",
                        "workspace_id": "workspace-1",
                        "counters": {"terminalFit.run": 2},
                    },
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

            log_path = (
                state_root
                / ".electroboy"
                / "service"
                / "frontend-debug.jsonl"
            )
            log_entry = json.loads(log_path.read_text(encoding="utf-8").strip())
            previous_log_path = log_path.with_name("frontend-debug.previous.jsonl")
            previous_log_exists = previous_log_path.exists()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        self.assertEqual(json.loads(body)["status"], "recorded")
        self.assertFalse(previous_log_exists)
        self.assertEqual(log_entry["payload"]["reason"], "test")
        self.assertEqual(
            log_entry["payload"]["counters"]["terminalFit.run"],
            2,
        )

    def test_frontend_debug_log_rotates_with_bounded_generations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp)
            with mock.patch.object(
                frontend_debug,
                "FRONTEND_DEBUG_LOG_SEGMENT_LIMIT_BYTES",
                600,
            ):
                for sequence in range(3):
                    frontend_debug.append_frontend_debug_payload(
                        state_root,
                        {
                            "reason": "rotation-test",
                            "sequence": sequence,
                            "padding": "x" * 400,
                        },
                    )

            log_path = frontend_debug.frontend_debug_log_path(state_root)
            previous_path = log_path.with_name(
                frontend_debug.FRONTEND_DEBUG_PREVIOUS_LOG_NAME
            )
            current = json.loads(log_path.read_text(encoding="utf-8"))
            previous = json.loads(previous_path.read_text(encoding="utf-8"))

        self.assertEqual(current["payload"]["sequence"], 2)
        self.assertEqual(previous["payload"]["sequence"], 1)

    def test_frontend_debug_records_sanitized_http_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            state_root = Path(tmp) / "state"
            root.mkdir()
            state_root.mkdir()
            try:
                server = create_server(root, port=0, state_root=state_root)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, _, _ = request(
                    server,
                    "/api/project?workspace_id=missing&context_id=missing"
                    "&connection_id=tab-1&lease_token=secret"
                    "&telemetry_page_id=page-1&telemetry_tab_id=tab-1",
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

            log_path = frontend_debug.frontend_debug_log_path(state_root)
            encoded_log = log_path.read_text(encoding="utf-8")
            entry = json.loads(encoded_log)

        self.assertEqual(status, 409)
        self.assertNotIn("secret", encoded_log)
        self.assertEqual(entry["payload"]["reason"], "http-response")
        self.assertEqual(entry["payload"]["page_id"], "page-1")
        self.assertEqual(entry["payload"]["request"]["path"], "/api/project")
        self.assertEqual(entry["payload"]["request"]["status"], 409)
        self.assertNotIn(
            "lease_token",
            entry["payload"]["request"]["query_keys"],
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
        agent_session_routes = {
            (route["method"], route["path"])
            for route in modules["agent_sessions"]["routes"]
        }
        self.assertIn(("POST", "/api/sessions/terminate"), agent_session_routes)
        self.assertIn("recent_projects", modules)
        recent_project_routes = {
            (route["method"], route["path"])
            for route in modules["recent_projects"]["routes"]
        }
        self.assertIn(
            ("POST", "/api/recent-projects/clear"),
            recent_project_routes,
        )
        self.assertIn("structured_documents", modules)
        self.assertIn("agenda", modules)
        self.assertIn("calendar", modules)
        self.assertIn("mind_map", modules)
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
        self.assertIn("agenda-styles", modules["agenda"]["capabilities"])
        calendar_routes = {
            (route["method"], route["path"])
            for route in modules["calendar"]["routes"]
        }
        self.assertIn(("GET", "/artifacts/calendar"), calendar_routes)
        self.assertIn(("GET", "/api/calendar"), calendar_routes)
        self.assertIn("calendar-provider", modules["calendar"]["capabilities"])
        mind_map_routes = {
            (route["method"], route["path"])
            for route in modules["mind_map"]["routes"]
        }
        self.assertIn(("GET", "/artifacts/mind-map"), mind_map_routes)
        self.assertIn(("GET", "/api/mind-map"), mind_map_routes)
        self.assertIn(("GET", "/api/mind-map/documents"), mind_map_routes)
        self.assertIn(("POST", "/api/mind-map/document"), mind_map_routes)
        self.assertIn("mind-map-provider", modules["mind_map"]["capabilities"])
        self.assertIn("editable-mind-map", modules["mind_map"]["capabilities"])
        self.assertIn(
            "mind-map-relationship-modes",
            modules["mind_map"]["capabilities"],
        )
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
        self.assertIn("frontend_debug", core_handlers)
        self.assertIn("software", workflows)
        self.assertIn("creative-writing", workflows)
        self.assertIn("agent_sessions", workflows["software"]["modules"])
        self.assertIn("mind_map", workflows["software"]["modules"])
        self.assertIn("mind_map", workflows["creative-writing"]["modules"])
        self.assertIn(
            "mind-map",
            {stage["id"] for stage in workflows["software"]["stages"]},
        )
        self.assertIn("core-shell", frontend_bundles)
        self.assertIn("index.html", frontend_bundles["core-shell"]["assets"])
        self.assertIn(
            "js/core/pane-layout-drag.js",
            frontend_bundles["core-shell"]["assets"],
        )
        self.assertIn(
            "js/core/split-resize.js",
            frontend_bundles["core-shell"]["assets"],
        )
        self.assertIn(
            "js/core/input-shortcut.js",
            frontend_bundles["core-shell"]["assets"],
        )
        self.assertIn(
            "js/modules/input-history.js",
            frontend_bundles["agent-sessions"]["assets"],
        )
        self.assertIn(
            "css/input-history.css",
            frontend_bundles["agent-sessions"]["assets"],
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
        self.assertIn("agent-sessions", frontend_bundles)
        self.assertIn(
            "js/modules/agent-pane-tools.js",
            frontend_bundles["agent-sessions"]["assets"],
        )
        self.assertIn(
            "js/modules/agent-sessions.js",
            frontend_bundles["agent-sessions"]["assets"],
        )
        self.assertIn("documents", frontend_bundles)
        self.assertIn("agenda", frontend_bundles)
        self.assertIn("calendar", frontend_bundles)
        self.assertIn("binder", frontend_bundles)
        self.assertIn("pane-window", frontend_bundles)
        self.assertIn(
            "js/core/pane-workspace.js",
            frontend_bundles["pane-window"]["assets"],
        )
        self.assertIn(
            "js/core/split-resize.js",
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
            "js/modules/document-navigation.js",
            frontend_bundles["documents"]["assets"],
        )
        self.assertIn(
            "js/modules/file-pane-tools.js",
            frontend_bundles["documents"]["assets"],
        )
        self.assertIn(
            "js/modules/agenda-pane-tools.js",
            frontend_bundles["agenda"]["assets"],
        )
        self.assertIn(
            "css/agenda-pane-tools.css",
            frontend_bundles["agenda"]["assets"],
        )
        self.assertIn(
            "js/modules/calendar.js",
            frontend_bundles["calendar"]["assets"],
        )
        self.assertIn(
            "js/modules/assignments.js",
            frontend_bundles["assignments"]["assets"],
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
        input_history = read_service_text_asset(
            "js/modules/input-history.js", modules, workflows
        )
        pane_sync = read_service_text_asset("js/core/pane-sync.js")
        pane_tools = read_service_text_asset("js/core/pane-tools.js")
        pane_css = read_service_text_asset("css/pane-tools.css")
        terminal_behavior = read_service_text_asset(
            "js/core/terminal-behavior.js"
        )
        agent_pane_tools = read_service_text_asset("js/modules/agent-pane-tools.js")
        document_navigation = read_service_text_asset(
            "js/modules/document-navigation.js",
            modules,
            workflows,
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
        assignments = read_service_text_asset("js/modules/assignments.js")
        calendar = read_service_text_asset("js/modules/calendar.js")
        mind_map = read_service_text_asset("js/modules/mind-map.js")
        mind_map_tools = read_service_text_asset("js/modules/mind-map-pane-tools.js")
        mind_map_tools_css = read_service_text_asset(
            "css/mind-map-pane-tools.css"
        )
        file_browser = read_service_text_asset("js/modules/file-browser.js")
        progress = read_service_text_asset("js/modules/progress.js")
        project_shell = read_service_text_asset("js/modules/project-shell.js")
        template = read_service_text_asset("index.html")
        app = read_service_text_asset("js/core/runtime.js")
        pane_window = read_service_text_asset("pane-window.html")
        shell_css = read_service_text_asset("css/shell.css")
        input_history_css = read_service_text_asset(
            "css/input-history.css", modules, workflows
        )
        creative_css = read_service_text_asset(
            "css/workflows/creative-writing.css", modules, workflows
        )

        self.assertIn("bindRuntime(nextRuntime)", registry)
        self.assertIn("invokeWorkflow(id, action, ...args)", registry)
        self.assertIn("invokeModule(id, action, ...args)", registry)
        self.assertIn("function stageActions(stageId, runtime)", software)
        self.assertIn("help: {", software)
        self.assertIn("Guide a software project", software)
        self.assertIn("defaultPaneLayout: {", software)
        self.assertIn('kind: "agent"', software)
        self.assertIn('kind: "scratch"', software)
        self.assertIn('kind: "status"', software)
        self.assertIn('if (stageId === "corkboard")', software)
        self.assertIn(
            'sidecarStages: ["document", "corkboard", "mind-map"]', software
        )
        self.assertIn('if (stageId === "mind-map")', software)
        self.assertIn('data-creative-control="mind-map-menu"', creative)
        self.assertIn('data-creative-control="corkboard-menu"', creative)
        self.assertIn('data-creative-control="open-corkboard">Open', creative)
        self.assertIn('data-creative-control="new-corkboard">New', creative)
        mind_map_position = creative.index('data-creative-control="mind-map-menu"')
        corkboard_position = creative.index('data-creative-control="corkboard-menu"')
        folders_position = creative.index('class="creative-folder-title"')
        self.assertLess(mind_map_position, corkboard_position)
        self.assertLess(corkboard_position, folders_position)
        self.assertIn(
            'class="creative-divider" aria-hidden="true"',
            creative[corkboard_position:folders_position],
        )
        self.assertIn(">Folders</div>", creative)
        self.assertIn(".creative-folder-title {", creative_css)
        self.assertIn('hiddenActionStages: ["document"]', software)
        self.assertIn("hiddenActionStages.has(stageId)", app)
        self.assertNotIn('if (stageId === "document")', app)
        self.assertIn('contextUrl("/api/corkboards")', software)
        self.assertIn('navigation: "stages"', software)
        self.assertIn("function resetSoftwareWorkflowState()", software)
        self.assertIn("deactivate,", software)
        self.assertIn("stageDescriptions: STAGE_DESCRIPTIONS", software)
        self.assertNotIn("function mount(runtime)", software)
        self.assertIn("async function startAgent(runtime, options = {})", creative)
        self.assertIn("help: {", creative)
        self.assertIn("Develop long-form writing", creative)
        self.assertIn("async function chooseCreativeAgentSession", creative)
        self.assertIn("function payloadWithCreativeSession(payload)", creative)
        self.assertIn("selected_session_id: sessionId", creative)
        self.assertIn("const sessionPath = query", creative)
        self.assertIn("contextUrl(sessionPath)", creative)
        self.assertNotIn(
            '`${contextUrl("/api/creative/agent/sessions")}?${query}`',
            creative,
        )
        self.assertIn("if (!choice) {\n      return null;\n    }", creative)
        self.assertIn("return startPayload;", creative)
        self.assertIn('placeholder="ElectroBoy id or Codex UUID"', creative)
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
        self.assertIn("async function openRecentProject(project)", creative)
        self.assertIn("async function clearRecentProjects()", creative)
        self.assertNotIn("return runtimeApi.recent.open(project);", creative)
        self.assertIn('contextUrl("/api/creative/project/open")', creative)
        self.assertIn('clearButton.textContent = "Clear list";', creative)
        self.assertIn(
            'separator.className = "stage-action-separator";',
            creative,
        )
        self.assertIn("creativeRecentProjects.append(separator);", creative)
        self.assertIn("button.disabled = Boolean(activeProjectRoot)", creative)
        self.assertNotIn("button.disabled = Boolean(activationRoot)", creative)
        self.assertIn(
            "async function clearRecentProjects(entries = recentProjectsForWorkflow())",
            app,
        )
        self.assertIn('contextUrl("/api/recent-projects/clear")', app)
        self.assertIn("{ separator: true }", app)
        self.assertIn("clear: clearRecentProjects", app)
        self.assertIn("event.stopPropagation();", creative)
        self.assertIn('navigation: "sidebar"', creative)
        self.assertIn(
            'defaultPaneLayout: { type: "leaf", kind: "empty" }',
            creative,
        )
        self.assertIn("function migratePaneLayout(layout)", creative)
        self.assertNotIn("selectCreativeDocument(firstDocument.path", creative)
        self.assertIn('runtimeApi.layout.ensurePane("agent");', sessions)
        self.assertIn("function renderTree(runtime)", binder)
        self.assertIn("function folderEntryVisible(entry)", binder)
        self.assertIn('String(entry.path || "") !== "corkboard"', binder)
        self.assertNotIn('["New board",', binder)
        self.assertIn("function show(runtime, source, options = {})", corkboard)
        self.assertIn('kind: "corkboard"', corkboard)
        self.assertIn("async function openDocument(runtime, options = {})", corkboard)
        self.assertIn("async function newDocument(runtime, options = {})", corkboard)
        self.assertIn(
            'className = "ad-hoc-session-dialog corkboard-picker-dialog"',
            corkboard,
        )
        self.assertIn("actions: { show, openDocument, newDocument }", corkboard)
        self.assertIn('kind: "agenda"', agenda)
        self.assertIn('id: "agenda"', agenda)
        self.assertIn('id: "assignments"', assignments)
        self.assertIn('kind: "route"', assignments)
        self.assertIn('runtime.layout.ensurePane(', assignments)
        self.assertIn("const activate = options.activate !== false;", assignments)
        self.assertIn("activateExisting: activate", assignments)
        self.assertIn('runtime.layout.assignPane("assignments", item, "", {', assignments)
        self.assertIn('targetPane || "agenda"', assignments)
        self.assertIn('kind: "calendar"', calendar)
        self.assertIn('id: "calendar"', calendar)
        self.assertIn("runtime.layout.assignWorkspacePane", calendar)
        self.assertIn("function calendarRange(source = {}, options = {})", calendar)
        self.assertIn("rangeStart: range.rangeStart", calendar)
        self.assertIn("const style = normalizeStyle(descriptor.style || options.style);", calendar)
        self.assertIn('kind: "mind-map"', mind_map)
        self.assertIn('id: "mind_map"', mind_map)
        self.assertIn("async function openDocument(runtime)", mind_map)
        self.assertIn("async function newDocument(runtime)", mind_map)
        self.assertIn("runtime.layout.assignWorkspacePane", mind_map)
        self.assertIn(
            'className = "ad-hoc-session-dialog mind-map-picker-dialog"',
            mind_map,
        )
        self.assertIn('label.className = "ad-hoc-session-option"', mind_map)
        self.assertIn("ElectroBoyMindMapPaneTools", mind_map_tools)
        self.assertIn("const ICONS = Object.freeze", mind_map_tools)
        self.assertIn('class="mind-map-tool-icon"', mind_map_tools)
        self.assertIn(
            '["Open", "open", "Open mind map", "folder-open"]', mind_map_tools
        )
        self.assertIn(
            '["Delete", "delete", "Delete selected node", "delete"]',
            mind_map_tools,
        )
        self.assertIn(
            "return controller.addSection(id, label, { open: false });",
            mind_map_tools,
        )
        self.assertIn('section(controller, "mind-map-node", "Node")', mind_map_tools)
        self.assertIn('section(controller, "mind-map-color", "Color")', mind_map_tools)
        self.assertIn('section(controller, "mind-map-layout", "Layout")', mind_map_tools)
        self.assertIn(
            'section(controller, "mind-map-font", "Font size")', mind_map_tools
        )
        self.assertIn('post("font-size-set", { fontSize })', mind_map_tools)
        self.assertIn('action === "focus"', mind_map_tools)
        self.assertIn('String(Boolean(data.focusMode))', mind_map_tools)
        self.assertIn('action.startsWith("layout-")', mind_map_tools)
        self.assertIn(
            '[data-mind-map-action^="layout-"][aria-pressed="true"]',
            mind_map_tools_css,
        )
        self.assertIn("selection_channel: selectionChannel", mind_map_tools)
        self.assertIn('send(action, { target: String(data.path) })', mind_map_tools)
        self.assertIn("const style = normalizeStyle(descriptor.style || options.style);", mind_map)
        self.assertIn("function artifactPaneIsAgenda(item)", documents)
        self.assertIn("function artifactPaneIsCalendar(item)", documents)
        self.assertIn("function artifactPaneIsMindMap(item)", documents)
        self.assertIn("function artifactPaneIsProviderView(item)", documents)
        self.assertIn(
            'item && item.kind === "route" && item.providerView === true',
            documents,
        )
        self.assertIn("/artifacts/agenda", documents)
        self.assertIn("/artifacts/calendar", documents)
        self.assertIn("/artifacts/mind-map", documents)
        self.assertIn('parameters.set("style", agenda.style);', documents)
        self.assertIn('parameters.set("style", calendar.style);', documents)
        self.assertIn('parameters.set("style", mindMap.style);', documents)
        self.assertIn('parameters.set("agenda_style", agenda.style);', documents)
        self.assertIn('parameters.set("calendar_style", calendar.style);', app)
        self.assertIn('parameters.set("mind_map_style", mindMap.style);', app)
        self.assertIn(
            'agenda_style: url.searchParams.get("agenda_style") || ""',
            app,
        )
        self.assertIn(
            'calendar_style: url.searchParams.get("calendar_style") || ""',
            app,
        )
        self.assertIn(
            'mind_map_style: url.searchParams.get("mind_map_style") || ""',
            app,
        )
        self.assertIn('assignments: { label: "Assignments", element: null }', app)
        self.assertIn("pane_layout: frontendDebugPaneLayoutPayload()", app)
        self.assertIn(
            'let artifactAgendaStyle = params.get("agenda_style") || "";',
            pane_window,
        )
        self.assertIn(
            'let artifactCalendarProvider = params.get("calendar_provider") || "";',
            pane_window,
        )
        self.assertIn(
            'let artifactMindMapProvider = params.get("mind_map_provider") || "";',
            pane_window,
        )
        self.assertIn("ElectroBoyMindMapPaneTools.mount", pane_window)
        self.assertIn('parameters.set("style", artifactAgendaStyle);', pane_window)
        self.assertIn('parameters.set("agenda_style", agenda.style);', app)
        self.assertIn('calendar: { label: "Calendar", element: null }', app)
        self.assertIn('"mind-map": { label: "Mind Map", element: null }', app)
        self.assertIn('/artifacts/mind-map?${parameters.toString()}', pane_window)
        self.assertIn('/artifacts/calendar?${parameters.toString()}', pane_window)
        self.assertIn(
            "let artifactCalendarIdsExplicit = "
            'params.get("calendar_ids_explicit") === "1";',
            pane_window,
        )
        self.assertIn('parameters.set("calendar_ids_explicit", "1");', pane_window)
        self.assertIn('nextUrl.searchParams.set("calendar_month", artifactCalendarMonth);', pane_window)
        self.assertIn('parameters.set("month", artifactCalendarMonth);', pane_window)
        self.assertIn('parameters.set("range_start", artifactCalendarRangeStart);', pane_window)
        self.assertIn('parameters.set("style", artifactCalendarStyle);', pane_window)
        self.assertIn('data.type === "electroboy-calendar-month-change"', pane_window)
        self.assertIn('"electroboy-agenda-action"', pane_window)
        self.assertIn('"electroboy-mind-map-action"', pane_window)
        self.assertIn("function forwardArtifactHostAction(event, data)", pane_window)
        self.assertIn("ARTIFACT_HOST_ACTION_TYPES.has(data.type)", pane_window)
        self.assertIn("owner.postMessage(data, window.location.origin);", pane_window)
        self.assertIn('PANE_KIND === "calendar"', pane_window)
        self.assertIn('if (kind === "assignments") return "Assignments";', pane_window)
        self.assertIn('PANE_KIND === "assignments"', pane_window)
        self.assertIn(".ad-hoc-session-dialog", shell_css)
        self.assertIn('id="showHelp"', template)
        self.assertIn('id="helpOverlay"', template)
        self.assertIn('class="workflow-topbar"', template)
        self.assertIn(".workflow-topbar", shell_css)
        self.assertIn(
            "grid-template-columns:\n"
            "        minmax(0, 1fr)\n"
            "        max-content\n"
            "        38px;",
            shell_css,
        )
        self.assertIn("width: min(96vw, 1320px);", shell_css)
        self.assertIn("grid-template-columns: 160px minmax(0, 1fr);", shell_css)
        self.assertIn("grid-template-columns: 190px minmax(0, 1fr);", shell_css)
        self.assertIn("overflow-wrap: anywhere;", shell_css)
        self.assertIn('id="terminalFontValue"', template)
        self.assertIn('data-pane-font-level="agent"', template)
        self.assertIn('id="agentPaneToolsToggle"', template)
        self.assertIn('id="agentPaneToolsShelf"', template)
        self.assertIn('id="agentPaneToolsContent"', template)
        self.assertNotIn("data-pane-font-reset", template)
        self.assertIn("function renderHelp()", app)
        self.assertIn("function openHelp()", app)
        self.assertIn('event.key === "F1"', app)
        self.assertIn("bindFontSizeInput(", app)
        self.assertIn("function setTerminalFontSize(value)", app)
        self.assertIn("function setPaneFontSize(pane, value)", app)
        self.assertNotIn("MAX_TERMINAL_FONT_SIZE", app)
        self.assertNotIn("MAX_PANE_FONT_OFFSET", app)
        self.assertIn(".terminal-pane.pane-tools-open", shell_css)
        self.assertIn(".pane-tool-font-row", pane_css)
        self.assertIn(".pane-tool-menu-button.danger", pane_css)
        self.assertIn(".help-overlay", shell_css)
        self.assertIn('id="paneFontLevel"', pane_window)
        self.assertNotIn('id="resetPaneFont"', pane_window)
        self.assertIn("function setFontSize(value)", pane_window)
        self.assertNotIn("MAX_FONT_SIZE", pane_window)
        self.assertNotIn("MAX_FONT_OFFSET", pane_window)
        self.assertNotIn('invokeWorkflow(\n        "creative-writing"', corkboard)
        self.assertIn("async function refreshServiceSessions()", sessions)
        self.assertIn("function ensureSelectedSessionStream(options = {})", sessions)
        self.assertIn("const runningOnly = options.runningOnly !== false;", sessions)
        self.assertIn(
            "if (!session || (runningOnly && !sessionIsRunning(session)))",
            sessions,
        )
        self.assertIn("focusAgentSessionPane(sessionId);", sessions)
        self.assertIn("function selectAgentSessionLocally", sessions)
        self.assertIn("function mountAgentPaneTools(runtime)", sessions)
        self.assertIn("window.ElectroBoyAgentPaneTools.mount", sessions)
        self.assertIn("function connectSessionEvents(sessionId, options = {})", sessions)
        self.assertIn("function focusAgentSessionPane(sessionId)", sessions)
        self.assertIn("runtimeApi.layout.focusAgentSession", sessions)
        self.assertIn("let agentEventStreamVersion = 0;", sessions)
        self.assertIn("let agentEventSource = null;", sessions)
        self.assertIn("const agentEventLastIds = new Map();", sessions)
        self.assertIn("let agentPaneTools = null;", sessions)
        self.assertIn("function ensureAgentEventStream()", sessions)
        self.assertIn('eventSource("/api/sessions/events")', sessions)
        self.assertNotIn("/api/sessions/events?session_id=", sessions)
        self.assertIn("function ensureRunningSessionStreams()", sessions)
        self.assertIn("appendAgentOutput(outputText, sessionId);", sessions)
        self.assertIn("prepareTerminalStream(sessionId);", sessions)
        self.assertIn("if (options.ensurePane !== false)", sessions)
        self.assertIn(
            "connectSessionEvents(runtimeState.selectedSessionId, { ensurePane: false })",
            sessions,
        )
        self.assertIn("response.status === 404", sessions)
        self.assertIn("function selectedInputSession()", sessions)
        self.assertIn("session_id: session.session_id,\n          message:", sessions)
        self.assertIn(
            "JSON.stringify({ session_id: session.session_id, key })",
            sessions,
        )
        self.assertIn(
            "JSON.stringify({ session_id: session.session_id, data })",
            sessions,
        )
        self.assertIn(
            "body: JSON.stringify({ session_id: session.session_id })",
            sessions,
        )
        self.assertIn('contextUrl("/api/sessions/terminate")', sessions)
        self.assertIn("terminateActiveAgent", sessions)
        self.assertIn("agentFontControls", app)
        self.assertIn("agentPaneToolsShelf", app)
        self.assertIn("closePane: closeMountedPane", app)
        self.assertIn("popOutPane: popOutMountedPane", app)
        self.assertIn("window.ElectroBoyAgentPaneTools", agent_pane_tools)
        self.assertIn('controller.addSection("agent-view", "View")', agent_pane_tools)
        self.assertIn(
            'controller.addSection("agent-actions", "Actions")',
            agent_pane_tools,
        )
        self.assertIn("Export transcript", agent_pane_tools)
        self.assertIn('menu("Pane", "pane-tool-agent-pane-menu")', agent_pane_tools)
        self.assertIn(
            'menu("Agent", "pane-tool-agent-session-menu")',
            agent_pane_tools,
        )
        self.assertIn("Focus session", agent_pane_tools)
        self.assertIn("function chooseRunningSession()", agent_pane_tools)
        self.assertIn("Terminate agent", agent_pane_tools)
        self.assertIn('controls.font.classList.add("pane-tool-font-row")', agent_pane_tools)
        self.assertIn("controls.exportButton.hidden = true", agent_pane_tools)
        self.assertIn("AGENT_OUTPUT_FLUSH_BUDGET_MS", app)
        self.assertIn("const agentTerminalContexts = new Map();", app)
        self.assertIn("function createAgentTerminalContext(sessionId = \"\")", app)
        self.assertIn("function selectAgentTerminal(sessionId = \"\")", app)
        self.assertIn("function focusAgentSessionPane(sessionId = \"\")", app)
        self.assertIn("focusAgentSession: focusAgentSessionPane", app)
        self.assertIn("function flushAgentOutputQueue(context)", app)
        self.assertIn("function resetTerminalOutput(terminalInstance)", app)
        self.assertIn("reset: resetTerminalOutput", app)
        self.assertIn(
            'cursorInactiveStyle: pane === "agent" ? "none" : "outline",',
            app,
        )
        self.assertNotIn(".agent-terminal-host .xterm-cursor", shell_css)
        self.assertIn("const cursorlessTerminals = new WeakSet();", terminal_behavior)
        self.assertIn('{ prefix: "?", final: "h" }', terminal_behavior)
        self.assertIn(
            "(params) => params.length === 1 && params[0] === 25",
            terminal_behavior,
        )
        self.assertIn("hideCursor(terminal);", terminal_behavior)
        self.assertIn("function write(terminal, text, callback = null)", terminal_behavior)
        self.assertIn("function refreshViewportLock(terminal", terminal_behavior)
        self.assertIn("function restoreLockedViewport(terminal, state)", terminal_behavior)
        self.assertIn("function followOutput(terminal)", terminal_behavior)
        self.assertIn("snapshot.tailVisible", terminal_behavior)
        self.assertIn("state.viewportPointerActive", terminal_behavior)
        self.assertIn("state.viewportScrollPending = true;", terminal_behavior)
        self.assertIn("terminal.onScroll", terminal_behavior)
        self.assertIn("restoreViewport(terminal, snapshot);", terminal_behavior)
        self.assertIn("followOutput,\n    install,", terminal_behavior)
        self.assertIn("followOutput: followAgentOutput", app)
        self.assertIn("runtimeApi.agent.followOutput(session.session_id);", sessions)
        self.assertIn(
            "ElectroBoyTerminalBehavior.install(nextTerminal, {\n"
            "        hideCursor: true,",
            app,
        )
        self.assertIn("writeTerminalOutput(context.terminal, chunk,", app)
        self.assertIn("agentContext.fitAfterWrite = true;", app)
        self.assertIn("TERMINAL_OUTPUT_FLUSH_BUDGET_MS", pane_window)
        self.assertIn("const agentTerminalContexts = new Map();", pane_window)
        self.assertIn("const agentEventLastIds = new Map();", pane_window)
        self.assertIn("function flushTerminalOutputQueue(target = terminalOutputTarget())", pane_window)
        self.assertIn("function replacePaneEventSource(sessionId = \"\")", pane_window)
        self.assertIn("const streamSessionId = selectedSessionId;", pane_window)
        self.assertIn("queueTerminalOutput(payload.terminal || payload.text || \"\", sessionId)", pane_window)
        self.assertIn('contextUrl("/api/sessions/events")', pane_window)
        self.assertNotIn("/api/sessions/events?session_id=", pane_window)
        self.assertIn(
            "if (terminal) {\n        terminal.options.disableStdin = disableStdin;",
            pane_window,
        )
        self.assertIn("let pinnedAgentSessionId = PANE_KIND === \"agent\" ? selectedSessionId : \"\";", pane_window)
        self.assertIn("function selectAgentTerminal(sessionId = \"\")", pane_window)
        self.assertIn(
            'cursorInactiveStyle: PANE_KIND === "agent" ? "none" : "outline",',
            pane_window,
        )
        self.assertNotIn(".pane-agent-terminal-host .xterm-cursor", pane_window)
        self.assertIn(
            "ElectroBoyTerminalBehavior.install(nextTerminal, {\n"
            "        hideCursor: true,",
            pane_window,
        )
        self.assertIn("writeTerminalOutput(target.terminal, chunk,", pane_window)
        self.assertIn("agentContext.fitAfterWrite = true;", pane_window)
        self.assertIn("function ensureTerminalResizeTracking()", pane_window)
        self.assertIn("window.addEventListener(\"resize\", fitTerminal);", pane_window)
        self.assertIn("session_id: resizeSessionId,", pane_window)
        self.assertIn(
            'queueTerminalOutput(payload.terminal || payload.text || "")',
            pane_window,
        )
        self.assertIn("function selectedAgentSession()", pane_window)
        self.assertIn("no active agent stream", pane_window)
        self.assertIn('if (session && session.status === "running")', app)
        self.assertIn("showProgressPane(true, {", app)
        self.assertIn("ensureRequestedPanes: false,", app)
        self.assertIn("updateOutputSplit: false,", app)
        self.assertIn(
            'connectSessionEvents(session.session_id, { ensurePane: false })',
            app,
        )
        self.assertIn("connectProgressEvents({", app)
        self.assertIn("ensureRequestedPanes: false,", app)
        self.assertIn("updateOutputSplit: false,", app)
        self.assertIn("if (!session) {", sessions)
        self.assertIn("terminate_agents: terminateAgents", app)
        self.assertIn("Deactivate will stop", app)
        self.assertIn("ElectroBoyInputShortcut.bindRecorder", sessions)
        self.assertIn("runtimeApi.input.history.record(message);", sessions)
        self.assertIn("shortcutController.matches(event)", sessions)
        self.assertNotIn("isEnter && event.shiftKey", sessions)
        self.assertIn("function bindRecorder(button)", input_shortcut)
        self.assertIn("electroboy.agentSendShortcut.v1", input_shortcut)
        self.assertIn("Hover to record a new shortcut", input_shortcut)
        self.assertIn("const MAX_ENTRIES = 2000;", input_history)
        self.assertIn("SCOPED_STORAGE_PREFIX", input_history)
        self.assertIn("function storageKeysForScope(scope = {})", input_history)
        self.assertIn("scope.localSessionId", input_history)
        self.assertIn("removeEntriesForKey(aliasKey)", input_history)
        self.assertIn("entries.slice(-MAX_ENTRIES)", input_history)
        self.assertIn("function create(options = {})", input_history)
        self.assertIn("input.dispatchEvent(new Event(\"input\"", input_history)
        self.assertIn('id="showInputHistory"', template)
        self.assertLess(
            template.index('id="showInputHistory"'),
            template.index('id="interruptAgent"'),
        )
        self.assertIn("ElectroBoyInputHistory.create", app)
        self.assertIn("function agentInputHistoryScope()", app)
        self.assertIn("scope: agentInputHistoryScope", app)
        self.assertIn("metadata.provider_session_id", app)
        self.assertIn(
            'projectRoot: activeProjectRoot || activationRoot || serviceRoot || ""',
            app,
        )
        self.assertIn("history: agentInputHistory", app)
        self.assertIn('id="showInputHistory"', pane_window)
        self.assertLess(
            pane_window.index('id="showInputHistory"'),
            pane_window.index('id="interruptAgent"'),
        )
        self.assertIn("function selectedInputHistoryScope()", pane_window)
        self.assertIn("scope: selectedInputHistoryScope", pane_window)
        self.assertIn("inputHistory.record(message);", pane_window)
        self.assertIn(".input-history-card", input_history_css)
        self.assertIn("overflow: auto;", input_history_css)
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
        self.assertIn("terminal.scrollToLine(snapshot.marker.line)", terminal_behavior)
        self.assertIn("terminal.parser.registerCsiHandler", terminal_behavior)
        self.assertIn(
            '(params) => params.length > 0 && params[0] === 3',
            terminal_behavior,
        )
        self.assertNotIn("window.requestAnimationFrame", terminal_behavior)
        self.assertIn("function reset(terminal)", terminal_behavior)
        self.assertIn("terminal.reset()", terminal_behavior)
        self.assertIn("window.ElectroBoyFilePaneTools", file_pane_tools)
        self.assertIn('controller.addSection("find", "Find")', file_pane_tools)
        self.assertIn('controller.addSection("actions", "Actions")', file_pane_tools)
        self.assertIn('setActionStatus("Agent started")', file_pane_tools)
        self.assertIn('const pop = button("Pop"', file_pane_tools)
        self.assertIn('runAction("pop", () => {});', file_pane_tools)
        self.assertIn('menu("File", "pane-tool-file-menu")', file_pane_tools)
        self.assertIn('menu("Mode", "pane-tool-mode-menu")', file_pane_tools)
        self.assertIn('menu("Export", "pane-tool-export-menu")', file_pane_tools)
        file_menu_start = file_pane_tools.index("const fileMenu =")
        file_menu_end = file_pane_tools.index("const modeMenu =", file_menu_start)
        file_menu_source = file_pane_tools[file_menu_start:file_menu_end]
        self.assertLess(
            file_menu_source.index('menuButton("Open"'),
            file_menu_source.index('menuButton("New"'),
        )
        self.assertLess(
            file_menu_source.index('menuButton("New"'),
            file_menu_source.index('menuButton("Close"'),
        )
        self.assertLess(
            file_menu_source.index('menuButton("Close"'),
            file_menu_source.index('menuButton("Refresh"'),
        )
        mode_menu_start = file_menu_end
        mode_menu_end = file_pane_tools.index("const exportMenu =", mode_menu_start)
        mode_menu_source = file_pane_tools[mode_menu_start:mode_menu_end]
        self.assertLess(
            mode_menu_source.index('menuButton("Preview"'),
            mode_menu_source.index('menuButton("Edit"'),
        )
        self.assertIn(
            "fileMenu.details,\n      modeMenu.details,\n      exportMenu.details,",
            file_pane_tools,
        )
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
        self.assertIn("ElectroBoyDocumentNavigation.create", documents)
        self.assertIn("function followDocumentLink(frameWindow, data)", documents)
        self.assertIn("function navigateDocumentHistory(direction)", documents)
        self.assertIn("runtimeState.openDocumentTargets.find(", documents)
        self.assertIn(
            "function documentNavigationTargetKey(target)",
            documents,
        )
        self.assertIn("item.navigationTarget = normalized.target;", documents)
        self.assertIn("function externalLinkFrameUrl(target)", documents)
        self.assertIn("frame.src = url;", documents)
        self.assertIn("/artifacts/external-link", documents)
        self.assertIn(
            "allow-popups-to-escape-sandbox",
            documents,
        )
        self.assertIn("window.ElectroBoyDocumentNavigation =", document_navigation)
        self.assertIn(
            'const rawUrl = String(candidate.url || candidate.href || "").trim();',
            document_navigation,
        )
        self.assertIn("const backEntries = [];", document_navigation)
        self.assertIn("const forwardEntries = [];", document_navigation)
        self.assertIn('type: "electroboy:document-location"', document_navigation)
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
        self.assertNotIn("function buildDocumentMenu(item)", documents)
        self.assertNotIn('summary.textContent = "Document"', documents)
        self.assertNotIn("function renderDocumentActionPanel", documents)
        self.assertIn("open: () => openDocumentFileBrowser(),", documents)
        self.assertIn("new: () => openNewDocumentFileBrowser(),", documents)
        self.assertIn("if (item) popOutArtifactPreview(item);", documents)
        self.assertIn("function closeDocumentTarget(target)", documents)
        self.assertIn("closeDocumentTarget(item.target);", documents)
        self.assertIn('data.type !== "electroboy:document-file-action"', documents)
        self.assertIn("canSwitchMode: artifactPaneSupportsModeSwitch(item),", documents)
        self.assertIn("canExport: artifactPaneSupportsDocumentExport(item),", documents)
        self.assertNotIn(".pane-document-menu", shell_css)
        self.assertNotIn('exportFormat.className = "document-export-format"', documents)
        self.assertIn(
            "function openDocumentTarget(target, navigationLocation = null)",
            documents,
        )
        self.assertIn('data.type === "electroboy:document-link"', documents)
        self.assertIn('data.type === "electroboy:document-link"', pane_window)
        self.assertIn("let artifactNavigationTarget = null;", pane_window)
        self.assertIn("function currentPaneNavigationTarget()", pane_window)
        self.assertIn("function externalLinkFrameUrl(target)", pane_window)
        self.assertIn("artifactNavigationTarget = normalized.target;", pane_window)
        self.assertIn(
            "allow-popups-to-escape-sandbox",
            pane_window,
        )
        self.assertNotIn("document must be under the active project", documents)
        self.assertNotIn("document must be under the active project", pane_window)
        self.assertIn('addSection("navigation", "Navigation")', file_pane_tools)
        self.assertIn('const back = button("←"', file_pane_tools)
        self.assertIn('const forward = button("→"', file_pane_tools)
        self.assertIn('runAction("back"', file_pane_tools)
        self.assertIn('runAction("forward"', file_pane_tools)
        self.assertIn("function popOutArtifactPreview(item)", documents)
        self.assertNotIn('popOutPane("artifact", item)', documents)
        self.assertIn("function popOutCurrentArtifact()", pane_window)
        self.assertIn("pop: popOutCurrentArtifact,", pane_window)
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
        self.assertIn("function activeProjectIsCreative()", documents)
        self.assertIn('runtimeState.activeProjectMode === "creative"', documents)
        self.assertIn("async function startCreativeWritingAgent", documents)
        self.assertIn('"creative-writing",\n        "startAgent"', documents)
        self.assertIn("startDocumentAgent(item.target)", documents)
        self.assertIn(
            "if (activeProjectIsCreative()) {\n"
            "            return startDocumentAgent(item.target);",
            documents,
        )
        self.assertIn("const creativeProject = activeProjectIsCreative();", documents)
        self.assertIn(
            "const session = creativeProject\n"
            "            ? null\n"
            "            : documentationSessionForTarget(item.target);",
            documents,
        )
        self.assertIn("Start or resume an agent for ${item.title}", documents)
        self.assertIn("return payload;", documents)
        self.assertIn("value === null", file_pane_tools)
        self.assertNotIn("launchDocumentTarget", documents)
        self.assertIn(
            "function openProjectBrowser(mode = state().projectMode",
            file_browser,
        )
        self.assertIn('"documents", "openDocumentTarget"', file_browser)
        self.assertNotIn("_runtime", sessions)
        self.assertNotIn("_runtime", documents)
        self.assertNotIn("_runtime", file_browser)
        self.assertIn("function connectProgressEvents(runtime, options = {})", progress)
        self.assertIn("runtime.layout.showProgressPane(true, options)", progress)
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
        self.assertIn("runtimeApi.http.eventSource", sessions)
        self.assertNotIn("new EventSource(contextUrl", sessions)
        self.assertIn("function artifactEventTarget(item)", documents)
        self.assertIn('parameters.set("targets", JSON.stringify(targets))', documents)
        self.assertIn("runtimeApi.http.rawEventSource(", documents)
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
        self.assertNotIn("Focus ad-hoc", software)
        self.assertNotIn("runtimeApi.getState().adHocRunning", ad_hoc_start)
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
        self.assertNotIn("async function notifyCreativeAgentTargetSwitch()", creative)
        self.assertNotIn('contextUrl("/api/sessions/message")', creative)
        self.assertIn("const explicitSessionId = String(options.sessionId", creative)
        self.assertIn("choice = await chooseCreativeAgentSession({", creative)
        self.assertIn("function creativeSessionCanContinue(session)", creative)
        self.assertIn(
            'String(session.status || "") !== "running"\n'
            "        && session.resumable !== false",
            creative,
        )
        self.assertIn(".filter(creativeSessionCanContinue)", creative)
        self.assertIn("CODEX_SESSION_ID_PATTERN.test(manualId)", creative)
        self.assertIn("{ providerSessionId: manualId, startNew: false }", creative)
        self.assertIn("startNew: true,", documents)
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
        self.assertIn("event.source === candidate.popup", app)
        self.assertNotIn("function panePopoutHidesDockedPane(kind)", app)
        self.assertIn("const poppedPaneLeafIds = new Set();", app)
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
        agenda = read_service_text_asset("js/modules/agenda.js")
        project_shell = read_service_text_asset("js/modules/project-shell.js")
        workspace = read_service_text_asset("js/core/pane-workspace.js")
        styles = read_service_text_asset("css/shell.css")

        self.assertNotIn("existing.kind = previousKind", runtime)
        self.assertIn(
            'const SINGLETON_PANE_LAYOUT_KINDS = new Set(["progress"]);',
            runtime,
        )
        self.assertIn("const RESTORABLE_PANE_LAYOUT_KINDS = new Set([", runtime)
        self.assertIn(
            '"agent",\n      "artifact",\n      "agenda",\n'
            '      "assignments",\n      "calendar",\n'
            '      "mind-map",\n      "scratch",\n'
            '      "status"',
            runtime,
        )
        availability_start = runtime.index("function paneLayoutKindAvailable(")
        availability_end = runtime.index(
            "function markPaneLayoutControl(",
            availability_start,
        )
        availability_source = runtime[availability_start:availability_end]
        self.assertIn('if (kind === "agenda")', availability_source)
        self.assertIn('if (kind === "calendar")', availability_source)
        self.assertIn("return true;", availability_source)
        self.assertNotIn('kind !== "artifact"', availability_source)
        self.assertNotIn("artifactPreviewItems.length", availability_source)
        self.assertIn("const duplicateSingleton =", runtime)
        self.assertIn('["agenda", "calendar", "mind-map"].includes(content?.kind)', runtime)
        self.assertIn('item.kind === "agenda"', runtime)
        self.assertIn('item.kind === "calendar"', runtime)
        self.assertIn("SINGLETON_PANE_LAYOUT_KINDS.has(requestedKind)", runtime)
        self.assertIn("if (validKind && duplicateSingleton)", runtime)
        self.assertIn("return null;", runtime)
        self.assertIn("if (!first) {\n        return second;\n      }", runtime)
        self.assertIn("if (!second) {\n        return first;\n      }", runtime)
        self.assertIn("function paneLayoutHasRestorableLeaf(node)", runtime)
        self.assertIn("RESTORABLE_PANE_LAYOUT_KINDS.has(node.kind)", runtime)
        self.assertIn("function restoredPaneLayoutForWorkflow(layout, mode = workflowMode)", runtime)
        self.assertIn("return defaultPaneLayout(mode);", runtime)
        self.assertIn("const migrated = restoredPaneLayoutForWorkflow(stored, mode);", runtime)
        self.assertIn("function paneLayoutIsMounted()", runtime)
        self.assertIn("let shouldRenderRestoredPaneLayout = false;", runtime)
        self.assertIn("shouldRenderRestoredPaneLayout = paneLayoutIsMounted();", runtime)
        self.assertIn('bumpFrontendDebugCounter("paneLayout.hydrateRender")', runtime)
        self.assertIn("SINGLETON_PANE_LAYOUT_KINDS.has(kind)", runtime)
        self.assertIn("buildPaneLayoutInstanceFrame(node)", runtime)
        self.assertIn(
            "const reusableFrame = existingLeaf?.dataset.paneKind === leaf.kind",
            runtime,
        )
        self.assertIn(
            'updateLoadedPaneLayoutFrame(frame, leaf, nextUrl, "renderPaneLayout")',
            runtime,
        )
        self.assertIn('type: "electroboy:pane-set-context"', runtime)
        self.assertIn("frame.dataset.paneContextSignature", runtime)
        self.assertIn(
            '(node.kind === "agent" && Boolean(node.content?.sessionId))',
            runtime,
        )
        self.assertIn('element.dataset.paneDragIgnore = "true";', runtime)
        self.assertIn("function bindPaneLayoutCommand(button, handler)", runtime)
        self.assertIn("bindPaneLayoutCommand(close, () => closePaneLayoutLeaf(leaf.id));", runtime)
        self.assertIn('bumpFrontendDebugCounter("paneLayout.closeSkippedMissingLeaf")', runtime)
        self.assertIn("function setActivePaneLayoutLeaf(id)", runtime)
        self.assertIn("function ensureActivePaneLayoutLeaf(preferredKind = \"\")", runtime)
        self.assertIn("ensureActivePaneLayoutLeaf();\n      const root = renderPaneLayoutNode(paneLayout);", runtime)
        self.assertIn("window.ElectroBoySplitResize.create({", runtime)
        self.assertIn("layout: paneLayout,", runtime)
        self.assertIn("afterUpdate: fitTerminal,", runtime)
        self.assertIn("ElectroBoySplitResize.create({", workspace)
        self.assertIn("applyTemplate: applySplitTemplate,", workspace)
        self.assertIn("let shouldPersistRestoredState = false;", runtime)
        self.assertIn("queueWorkspaceStateSave(0);", runtime)
        self.assertIn("let fitTerminalFrame = 0;", runtime)
        self.assertIn("function paneIsVisible(element)", runtime)
        self.assertIn(
            '!element.hidden &&\n        !element.closest("[hidden]")',
            runtime,
        )
        self.assertIn("function scheduleFitTerminal()", runtime)
        self.assertIn("if (fitTerminalFrame)", runtime)
        self.assertIn("if (terminalFit && paneIsVisible(agentOutputPane))", runtime)
        terminal_fit_start = runtime.index("function fitTerminal()")
        terminal_fit_end = runtime.index(
            "function observeTerminalPaneResizes()",
            terminal_fit_start,
        )
        terminal_fit_source = runtime[terminal_fit_start:terminal_fit_end]
        visible_agent_fit = terminal_fit_source.index(
            "if (terminalFit && paneIsVisible(agentOutputPane))",
        )
        progress_fit = terminal_fit_source.index(
            "if (paneIsVisible(progressOutputPane))",
        )
        self.assertIn(
            "queueTerminalResize();",
            terminal_fit_source[visible_agent_fit:progress_fit],
        )
        self.assertNotIn(
            "queueTerminalResize();",
            terminal_fit_source[progress_fit:],
        )
        self.assertIn("if (paneIsVisible(progressOutputPane))", runtime)
        self.assertIn("if (paneIsVisible(projectShellPane))", runtime)
        self.assertIn('const FRONTEND_DEBUG_ENDPOINT = "/api/frontend/debug";', runtime)
        self.assertIn(
            'const FRONTEND_TELEMETRY_STORAGE_KEY = "electroboy.telemetry.enabled.v1";',
            runtime,
        )
        self.assertIn("const DEFAULT_FRONTEND_TELEMETRY_ENABLED = false;", runtime)
        self.assertIn('"telemetry",\n      "frontend_telemetry",\n      "frontend_debug"', runtime)
        self.assertIn("let frontendTelemetryEnabled = storedFrontendTelemetryEnabled();", runtime)
        self.assertIn(
            "return stored === null ? DEFAULT_FRONTEND_TELEMETRY_ENABLED : stored;",
            runtime,
        )
        self.assertIn("function setFrontendTelemetryEnabled(enabled, options = {})", runtime)
        self.assertIn("function applyFrontendTelemetryUrlPreference()", runtime)
        self.assertIn("if (!frontendTelemetryEnabled) {\n        return;\n      }", runtime)
        self.assertIn("if (!frontendTelemetryEnabled) {\n        return false;\n      }", runtime)
        self.assertIn(
            "return window.ElectroBoyLiveTransport.eventSource(url);",
            runtime,
        )
        self.assertIn("function stopFrontendDebugDiagnostics()", runtime)
        self.assertIn("frontendDebugRafPulseActive = false;", runtime)
        self.assertIn("telemetry: frontendTelemetryRuntime,", runtime)
        self.assertIn("enable() {\n        return setFrontendTelemetryEnabled(true);", runtime)
        self.assertIn("disable() {\n        return setFrontendTelemetryEnabled(false);", runtime)
        self.assertIn("applyFrontendTelemetryUrlPreference();", runtime)
        self.assertIn("function sendFrontendDebugSnapshot(reason, options = {})", runtime)
        self.assertIn("const useBeacon = Boolean(options.beacon);", runtime)
        self.assertIn(
            "navigator.sendBeacon(FRONTEND_DEBUG_ENDPOINT, body)",
            runtime,
        )
        self.assertNotIn(
            'new Blob([body], { type: "application/json" })',
            runtime,
        )
        self.assertIn("keepalive: useBeacon,", runtime)
        self.assertIn(
            'sendFrontendDebugSnapshot("pagehide", { beacon: true });',
            runtime,
        )
        self.assertIn("function startFrontendDebugDiagnostics()", runtime)
        self.assertIn("function scheduleFrontendDebugRafPulse()", runtime)
        self.assertIn("function mutateFrontendDebugPaintMarker(now)", runtime)
        self.assertIn("function recordFrontendDebugInput(event)", runtime)
        self.assertIn("paint_heartbeat: frontendDebugPaintPayload()", runtime)
        self.assertIn("raf: frontendDebugRafPayload()", runtime)
        self.assertIn("input: frontendDebugInputPayload()", runtime)
        self.assertIn("lifecycle: frontendDebugLifecyclePayload()", runtime)
        self.assertIn("network: frontendDebugNetworkPayload()", runtime)
        self.assertIn(
            "response_bodies: frontendDebugResponseBodyPayload()",
            runtime,
        )
        self.assertIn(
            "async function drainDiscardedFetchResponse(response, details = {})",
            runtime,
        )
        self.assertIn('type: "fetch-body-drained"', runtime)
        self.assertIn('type: "fetch-body-drain-error"', runtime)
        self.assertIn(
            'operation: "frontend-debug"',
            runtime,
        )
        self.assertIn(
            'operation: "workspace-heartbeat"',
            runtime,
        )
        self.assertIn("const responseOk = response.ok;", runtime)
        self.assertIn("await drainDiscardedFetchResponse(response, {", runtime)
        self.assertIn('document.addEventListener("freeze", recordFrontendDebugLifecycle, true);', runtime)
        self.assertIn('document.addEventListener("resume", recordFrontendDebugLifecycle, true);', runtime)
        self.assertIn('type: "timer-gap"', runtime)
        self.assertIn('type: "fetch-response"', runtime)
        self.assertIn('type: "fetch-error"', runtime)
        self.assertIn('type: "event-source-error"', runtime)
        self.assertIn('parameters.set("telemetry_page_id", pageInstanceId);', runtime)
        self.assertIn("last_target: frontendDebugInputLastTarget", runtime)
        self.assertIn("last_frame_age_ms:", runtime)
        self.assertIn("last_mutation_age_ms:", runtime)
        self.assertIn("document.title = `${frontendDebugBaseTitle} [${frontendDebugPaintSequence}]`;", runtime)
        self.assertIn('marker.id = FRONTEND_DEBUG_HEARTBEAT_ID;', runtime)
        self.assertIn("document.addEventListener(\"visibilitychange\", recordFrontendDebugInput, true);", runtime)
        self.assertIn("bumpFrontendDebugCounter(\"terminalFit.run\")", runtime)
        self.assertIn("bumpFrontendDebugCounter(\"mutationObserver.paneLayout\")", runtime)
        self.assertIn("bumpFrontendDebugCounter(\"resizeObserver.terminal\")", runtime)
        self.assertIn("eventSource: createDebugEventSource,", runtime)
        self.assertIn("rawEventSource: createDebugEventSourceForUrl,", runtime)
        self.assertNotIn("window.requestAnimationFrame(fitTerminal)", runtime)
        self.assertIn('window.addEventListener("resize", scheduleFitTerminal);', runtime)
        self.assertIn("fitAll: scheduleFitTerminal,", runtime)
        self.assertIn(
            "terminalResizeObserver = new window.ResizeObserver((entries) => {",
            runtime,
        )
        self.assertIn(
            "if (!entries.some((entry) => entry.target.isConnected))",
            runtime,
        )
        self.assertIn("scheduleFitTerminal();", runtime)
        self.assertIn(
            "function ensurePaneInLayout(kind, targetKind = \"agent\", direction = \"row\", options = {})",
            runtime,
        )
        self.assertIn("const existing = paneLayoutLeafByKind(kind);", runtime)
        self.assertIn("setActivePaneLayoutLeaf(existing.id);", runtime)
        self.assertIn("const shouldActivate = options.activate !== false;", runtime)
        self.assertIn(
            "if (shouldActivate && options.activateExisting !== false)",
            runtime,
        )
        self.assertIn("refreshPaneLayoutVisibility();", runtime)
        self.assertIn("const manualChangeOptions = {", runtime)
        self.assertIn("ensureRequestedPanes: false,", runtime)
        self.assertIn("updateOutputSplit: false,", runtime)
        self.assertIn("activatePaneLayoutKind(kind, manualChangeOptions);", runtime)
        self.assertIn(
            "deactivatePaneLayoutKind(previousKind, manualChangeOptions);",
            runtime,
        )
        visibility_start = runtime.index(
            "function applyOutputPaneVisibility(options = {})"
        )
        visibility_end = runtime.index(
            "function showProgressPane(show, options = {})",
            visibility_start,
        )
        visibility_source = runtime[visibility_start:visibility_end]
        self.assertIn(
            "const ensureRequestedPanes = options.ensureRequestedPanes !== false;",
            visibility_source,
        )
        self.assertIn(
            "const updateOutputSplit = options.updateOutputSplit !== false;",
            visibility_source,
        )
        self.assertIn(
            'if (ensureRequestedPanes && artifactVisible)',
            visibility_source,
        )
        self.assertIn(
            'ensurePaneInLayout("artifact", "agent", "row", { activateExisting: false })',
            visibility_source,
        )
        self.assertIn(
            'if (ensureRequestedPanes && progressVisible)',
            visibility_source,
        )
        self.assertIn(
            'ensurePaneInLayout("progress", "agent", "row", { activateExisting: false })',
            visibility_source,
        )
        self.assertIn("if (!updateOutputSplit)", visibility_source)
        self.assertIn(
            'outputSplit.classList.remove("artifact-visible", "split");',
            visibility_source,
        )
        self.assertIn(
            'runtime.layout.ensurePane("shell", "agent", "column", { activateExisting: false })',
            project_shell,
        )
        self.assertIn("activePaneLayoutLeafId = newLeaf.id;", runtime)
        self.assertIn('message.type === "electroboy:pane-activate"', runtime)
        self.assertIn("function paneLayoutArtifactIsProjectScoped(item)", runtime)
        self.assertIn('item.kind === "agenda"', runtime)
        self.assertIn('provider === "creative-files"', runtime)
        self.assertIn('provider === "project-files"', runtime)
        self.assertIn("leaf.projectRoot === activeProjectRoot", runtime)
        self.assertIn("assignArtifact: assignArtifactToPane", runtime)
        self.assertIn("assignPane: assignPaneContent", runtime)
        self.assertIn("assignWorkspacePane: assignWorkspacePaneContent", runtime)
        self.assertIn(
            "function assignWorkspacePaneContent(kind, item, requestedLeafId = \"\")",
            runtime,
        )
        self.assertIn("function paneLayoutRequestedArtifact(leaf)", runtime)
        self.assertIn(
            'const content = value.content && typeof value.content === "object"',
            runtime,
        )
        change_kind_start = runtime.index("function changePaneLayoutKind(id, kind)")
        change_kind_end = runtime.index(
            "function closePaneLayoutLeaf(id)",
            change_kind_start,
        )
        change_kind_source = runtime[change_kind_start:change_kind_end]
        self.assertNotIn("leaf.content = null", change_kind_source)
        self.assertNotIn('leaf.projectRoot = ""', change_kind_source)
        self.assertIn(
            'function updateLoadedPaneLayoutFrame(frame, leaf, nextUrl, reason = "pane-layout")',
            runtime,
        )
        self.assertIn('"electroboy:pane-set-agent-session"', runtime)
        self.assertIn('"electroboy:pane-agent-session-change"', runtime)
        self.assertIn('"electroboy:pane-set-artifact"', runtime)
        self.assertIn('"electroboy:pane-set-content"', runtime)
        self.assertIn("function paneLayoutStorageKey(mode = workflowMode)", runtime)
        self.assertIn("function paneLayoutFromDefinition(definition)", runtime)
        self.assertIn("function paneLayoutContribution(mode = workflowMode)", runtime)
        self.assertIn("function migratePaneLayoutForWorkflow(layout", runtime)
        self.assertIn("contribution.migratePaneLayout(paneLayoutDescription(layout))", runtime)
        self.assertIn('availableEmpty.kind = kind;', runtime)
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
        assign_end = runtime.index("function assignPaneLeafContent(", assign_start)
        assign_source = runtime[assign_start:assign_end]
        self.assertIn("refreshPaneLayoutInstanceFrameForLeaf(", assign_source)
        self.assertIn("reconcilePaneLayout(`assignPaneContent:${kind}`);", assign_source)
        self.assertIn("function paneLayoutConsistencyPayload()", runtime)
        self.assertIn("last_frame_refresh: frontendDebugLastPaneLayoutFrameRefresh", runtime)
        self.assertIn("function refreshPaneLayoutInstanceFrameForLeaf(", runtime)
        self.assertIn("function reconcilePaneLayout(", runtime)
        self.assertIn("paneLayout.reconcileRender", runtime)
        self.assertIn("consistency: paneLayoutConsistencyPayload()", runtime)
        self.assertIn("reconcile: reconcilePaneLayout", runtime)
        self.assertIn("runtimeApi.layout.assignArtifact(nextItems[0]);", documents)
        self.assertIn("runtime.layout.assignWorkspacePane", agenda)
        self.assertIn('kind === "agent" &&', workspace)
        self.assertIn(".pane-layout-leaf.active::before", styles)
        self.assertIn(
            ".pane-layout-toolbar {\n      position: relative;\n      z-index: 20;",
            styles,
        )
        self.assertIn("border: 3px solid #9bd6cf;", styles)
        self.assertIn("pointer-events: none;", styles)
        self.assertIn(".artifact-preview-frame.loading {\n      opacity: 1;", styles)

    def test_popped_layout_leaf_and_agent_session_assignment_are_persistent(self) -> None:
        runtime = read_service_text_asset("js/core/runtime.js")
        pane_window = read_service_text_asset("pane-window.html")

        self.assertIn("const poppedPaneLeafIds = new Set();", runtime)
        self.assertIn("!poppedPaneLeafIds.has(node.id)", runtime)
        self.assertIn("function popOutPaneLayoutLeaf(leaf)", runtime)
        self.assertIn(
            'const popoutContent = leaf.kind === "artifact" && !requestedContent\n'
            "        ? artifactPreviewItems[0] || null\n"
            "        : requestedContent;",
            runtime,
        )
        self.assertIn(
            "INSTANCE_PANE_LAYOUT_KINDS.has(leaf.kind) ? popoutContent : null",
            runtime,
        )
        self.assertIn("leafId: leaf.id,", runtime)
        self.assertIn("setPanePoppedOut(kind, true, popoutOptions.leafId);", runtime)
        self.assertIn(
            "popoutOptions.leafId ? false : hasPoppedPaneKind(kind)",
            runtime,
        )
        self.assertIn(
            "entry.leafId ? false : hasPoppedPaneKind(data.pane)",
            runtime,
        )
        self.assertIn("refreshPaneLayoutVisibility();", runtime)
        self.assertIn("popOutMountedPane(\"agent\")", runtime)

        self.assertIn('leaf.content = { sessionId };', runtime)
        self.assertIn('type: "electroboy:pane-set-agent-session"', runtime)
        self.assertIn(
            'type: "electroboy:pane-agent-session-change"',
            pane_window,
        )
        self.assertIn("function notifyPaneAgentSessionChange()", pane_window)
        self.assertIn('PANE_KIND === "agent"\n        ? agentSessions', pane_window)
        self.assertIn("notifyPaneAgentSessionChange();", pane_window)

    def test_frontend_recovers_workspace_attachment_after_resume(self) -> None:
        runtime = read_service_text_asset("js/core/runtime.js")

        self.assertIn("async function recoverWorkspaceAttachment()", runtime)
        self.assertIn("async function resumeWorkspaceAttachment()", runtime)
        self.assertIn(
            "const recovered = await recoverWorkspaceAttachment();",
            runtime,
        )
        self.assertIn("resumeWorkspaceAttachment().catch(() => {});", runtime)
        self.assertIn('document.addEventListener("resume", () => {', runtime)

    def test_workspace_selector_clears_detached_workspaces(self) -> None:
        runtime = read_service_text_asset("js/core/runtime.js")

        self.assertIn(
            'input type="checkbox" class="workspace-selector-select-all-input"',
            runtime,
        )
        self.assertIn('input.type = "checkbox";', runtime)
        self.assertIn(
            '<button class="workspace-selector-clear" type="button">Clear</button>',
            runtime,
        )
        self.assertNotIn("workspace-selector-refresh", runtime)
        self.assertIn("async function clearWorkspaceChoices(dialog)", runtime)
        self.assertIn("/api/workspaces/clear?${parameters.toString()}", runtime)
        self.assertIn('method: "POST"', runtime)
        self.assertIn("body: JSON.stringify({ workspace_ids: workspaceIds })", runtime)
        self.assertIn("submit.disabled = selected.length !== 1;", runtime)
        self.assertIn("clear.disabled = selected.length === 0;", runtime)
        self.assertIn("Running sessions in them will be stopped.", runtime)

    def test_agent_input_actions_are_fixed_height_and_top_aligned(self) -> None:
        styles = read_service_text_asset("css/shell.css")

        self.assertIn("var(--input-pane-height, 220px)", styles)
        self.assertIn("grid-template-rows: repeat(4, 42px);", styles)
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
        self.assertIn(
            "software.structured-artifacts",
            {rule["id"] for rule in software["agent_rules"]},
        )
        self.assertNotIn("content", software["agent_rules"][0])
        self.assertIn(
            "structured-documents.source-of-truth",
            {
                rule["id"]
                for rule in modules.get("structured_documents").payload()[
                    "agent_rules"
                ]
            },
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
            page.index("js/modules/document-navigation.js"),
            page.index("js/modules/documents.js"),
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
        self.assertLess(
            page.index("js/core/split-resize.js"),
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
        debug_match = dispatcher.match("POST", "/api/frontend/debug")
        self.assertIsNotNone(debug_match)
        self.assertEqual(debug_match.owner, "core")
        self.assertEqual(debug_match.handler_name, "frontend_debug")
        clear_recent_match = dispatcher.match("POST", "/api/recent-projects/clear")
        self.assertIsNotNone(clear_recent_match)
        self.assertEqual(clear_recent_match.owner, "recent_projects")
        self.assertEqual(clear_recent_match.handler_name, "clear")

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
            workspaces=dependency,
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
                    workspaces=object(),
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
        self.assertIn("/assets/service/js/core/split-resize.js", INDEX_HTML)
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
                split_resize_status, split_resize_body, split_resize_type, _ = (
                    request_bytes(
                        server,
                        "/assets/service/js/core/split-resize.js",
                    )
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
                agent_tools_status, agent_tools_body, agent_tools_type, _ = (
                    request_bytes(
                        server,
                        "/assets/service/js/modules/agent-pane-tools.js",
                    )
                )
                (
                    navigation_status,
                    navigation_body,
                    navigation_type,
                    _,
                ) = request_bytes(
                    server,
                    "/assets/service/js/modules/document-navigation.js",
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
        self.assertIn(b".ad-hoc-session-dialog", css_body)
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
        self.assertEqual(split_resize_status, 200)
        self.assertEqual(split_resize_type, "application/javascript; charset=utf-8")
        self.assertIn(b"ElectroBoySplitResize", split_resize_body)
        self.assertIn(b"createResizeController", split_resize_body)
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
        self.assertEqual(agent_tools_status, 200)
        self.assertEqual(agent_tools_type, "application/javascript; charset=utf-8")
        self.assertIn(b"window.ElectroBoyAgentPaneTools", agent_tools_body)
        self.assertEqual(navigation_status, 200)
        self.assertEqual(navigation_type, "application/javascript; charset=utf-8")
        self.assertIn(b"window.ElectroBoyDocumentNavigation", navigation_body)
        self.assertEqual(software_status, 200)
        self.assertEqual(software_type, "application/javascript; charset=utf-8")
        self.assertIn(b"Software engineering", software_body)
        self.assertEqual(software_css_status, 200)
        self.assertEqual(software_css_type, "text/css; charset=utf-8")
        self.assertIn(b"Shared session picker styles", software_css_body)
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
                (
                    calendar_status,
                    calendar_body,
                    calendar_content_type,
                ) = request(server, "/pane/calendar")
                (
                    mind_map_status,
                    mind_map_body,
                    mind_map_content_type,
                ) = request(server, "/pane/mind-map")
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
        self.assertEqual(calendar_status, 200)
        self.assertEqual(calendar_content_type, "text/html; charset=utf-8")
        self.assertIn('const PANE_KIND = "calendar";', calendar_body)
        self.assertEqual(mind_map_status, 200)
        self.assertEqual(mind_map_content_type, "text/html; charset=utf-8")
        self.assertIn('const PANE_KIND = "mind-map";', mind_map_body)

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
        self.assertIn('/assets/service/js/core/split-resize.js', page)
        self.assertLess(
            page.index('/assets/service/js/core/split-resize.js'),
            page.index('/assets/service/js/core/pane-workspace.js'),
        )
        self.assertIn('/assets/service/js/core/pane-sync.js', page)
        self.assertIn('/assets/service/js/core/pane-tools.js', page)
        self.assertIn('/assets/service/css/pane-tools.css', page)
        self.assertIn('/assets/service/js/modules/document-navigation.js', page)
        self.assertIn('/assets/service/js/modules/agent-pane-tools.js', page)
        self.assertIn('/assets/service/js/modules/file-pane-tools.js', page)
        self.assertLess(
            page.index('/assets/service/js/modules/document-navigation.js'),
            page.index('/assets/service/js/modules/agent-pane-tools.js'),
        )
        self.assertLess(
            page.index('/assets/service/js/modules/agent-pane-tools.js'),
            page.index('/assets/service/js/modules/file-pane-tools.js'),
        )
        self.assertIn('paneParameters.set("embedded", "1")', page)
        self.assertIn('paneParameters.set("pane_instance_id", item.id);', page)
        self.assertIn('type: "electroboy:pane-close"', page)
        self.assertIn('function initialPaneWorkspaceLayout()', page)
        self.assertIn('first: { type: "leaf", kind: "agent" }', page)
        self.assertIn('second: { type: "leaf", kind: "input" }', page)
        self.assertIn('initialLayout: initialPaneWorkspaceLayout()', page)
        self.assertIn('{ id: "mind-map", label: "Mind Map" }', page)
        self.assertIn("function hasNonEmptyLeaf(node)", workspace)
        self.assertIn("return defaultLayout();", workspace)
        self.assertIn('function splitLeaf(', workspace)
        self.assertIn('function startCornerSplit(', workspace)
        self.assertIn('function startResize(', workspace)
        self.assertIn("options.paneUrl(item.kind, item)", workspace)
        self.assertIn("function handlePaneMessage(event)", workspace)
        self.assertIn('data.type !== "electroboy:pane-close"', workspace)
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
        self.assertIn('params.get("workspace_id") || contextId', page)
        self.assertIn('params.get("connection_id") || ""', page)
        self.assertIn('params.get("lease_token") || ""', page)
        self.assertIn('params.get("telemetry_page_id") || ""', page)
        self.assertIn('params.get("telemetry_tab_id") || ""', page)
        self.assertIn('context.set("workspace_id", workspaceId)', page)
        self.assertIn('context.set("connection_id", connectionId)', page)
        self.assertIn('context.set("lease_token", leaseToken)', page)
        self.assertIn('context.set("telemetry_page_id", telemetryPageId)', page)
        self.assertIn('context.set("telemetry_tab_id", telemetryTabId)', page)
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
        self.assertIn("function openPaneDocumentFileBrowser(mode)", page)
        self.assertIn('open: () => openPaneDocumentFileBrowser("document")', page)
        self.assertIn('new: () => openPaneDocumentFileBrowser("document-new")', page)
        self.assertIn("close: closePaneDocument", page)
        self.assertIn("function closePaneDocument()", page)
        self.assertIn('postDocumentFileAction("close", target);', page)
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
        self.assertIn(
            "exportPaneOutput.hidden = Boolean(agentPaneTools) || !canExportPaneOutput();",
            page,
        )
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
        self.assertIn("ElectroBoyTerminalBehavior.reset(terminal)", PANE_WINDOW_HTML)
        self.assertIn("let pinnedAgentSessionId = PANE_KIND === \"agent\" ? selectedSessionId : \"\";", PANE_WINDOW_HTML)
        self.assertIn("function selectAgentTerminal(sessionId = \"\")", PANE_WINDOW_HTML)
        self.assertIn(
            "if (terminal) {\n        terminal.options.disableStdin = disableStdin;",
            PANE_WINDOW_HTML,
        )
        self.assertIn("function replacePaneEventSource(sessionId = \"\")", PANE_WINDOW_HTML)
        self.assertIn("function ensureTerminalResizeTracking()", PANE_WINDOW_HTML)
        self.assertIn("queueAgentResize(cols, rows, terminalSessionId);", PANE_WINDOW_HTML)
        self.assertIn('contextUrl("/api/sessions/resize")', PANE_WINDOW_HTML)
        self.assertIn("session_id: resizeSessionId,", PANE_WINDOW_HTML)
        self.assertIn("/assets/service/js/modules/agent-pane-tools.js", PANE_WINDOW_HTML)
        self.assertIn("let agentPaneTools = null;", PANE_WINDOW_HTML)
        self.assertIn("window.ElectroBoyAgentPaneTools.mount", PANE_WINDOW_HTML)
        self.assertIn("function popOutCurrentAgent()", PANE_WINDOW_HTML)
        self.assertIn("function closeAgentPaneWindow()", PANE_WINDOW_HTML)
        self.assertIn("function terminateAgentSession()", PANE_WINDOW_HTML)
        self.assertIn('contextUrl("/api/sessions/terminate")', PANE_WINDOW_HTML)
        self.assertIn(
            "body: JSON.stringify({ session_id: session.session_id })",
            PANE_WINDOW_HTML,
        )
        self.assertIn('type: "electroboy:pane-close"', PANE_WINDOW_HTML)
        self.assertIn(".terminal-host .xterm {\n      width: 100%;", PANE_WINDOW_HTML)
        self.assertIn("function effectiveFontSize()", PANE_WINDOW_HTML)
        self.assertNotIn("function resetFontSize()", PANE_WINDOW_HTML)
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
        self.assertNotIn('id="resetPaneFont"', PANE_WINDOW_HTML)
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
        self.assertIn("grid-template-rows: repeat(4, 42px);", PANE_WINDOW_HTML)
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
        self.assertIn("!data.selection_channel", PANE_WINDOW_HTML)
        self.assertIn("async function startPaneDocumentAgent(target)", PANE_WINDOW_HTML)
        self.assertIn('project.project_mode === "creative"', PANE_WINDOW_HTML)
        self.assertIn('"/api/creative/agent/start"', PANE_WINDOW_HTML)
        self.assertIn(
            "function choosePaneCreativeAgentSession(activeTarget)",
            PANE_WINDOW_HTML,
        )
        self.assertIn(
            "contextUrl(`/api/creative/agent/sessions?${query}`)",
            PANE_WINDOW_HTML,
        )
        self.assertIn(
            "? await choosePaneCreativeAgentSession(activeTarget)",
            PANE_WINDOW_HTML,
        )
        self.assertIn(
            "function paneCreativeSessionCanContinue(session)",
            PANE_WINDOW_HTML,
        )
        self.assertIn("session.resumable !== false", PANE_WINDOW_HTML)
        self.assertIn(
            ".filter(paneCreativeSessionCanContinue)",
            PANE_WINDOW_HTML,
        )
        self.assertIn('scope: "document",', PANE_WINDOW_HTML)
        self.assertIn('session_id: choice.sessionId || "",', PANE_WINDOW_HTML)
        self.assertIn(
            'provider_session_id: choice.providerSessionId || "",',
            PANE_WINDOW_HTML,
        )
        self.assertIn("return { startNew: true };", PANE_WINDOW_HTML)
        self.assertIn('placeholder="ElectroBoy id or Codex UUID"', PANE_WINDOW_HTML)
        self.assertIn('startAgent: startPaneDocumentAgent', PANE_WINDOW_HTML)
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
            'sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox '
            'allow-modals allow-same-origin"',
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
        self.assertIn("const SEARCH_PARAMETERS = new URLSearchParams", page)
        self.assertIn('SEARCH_PARAMETERS.get("project_action")', page)
        self.assertIn('SEARCH_PARAMETERS.get("selection_channel")', page)
        self.assertIn('event.key === "ArrowRight"', page)
        self.assertIn('event.key === "ArrowLeft"', page)
        self.assertIn("window.opener.postMessage", page)
        self.assertIn("electroboy-file-browser-select", page)
        self.assertIn("project_action: PROJECT_ACTION", page)
        self.assertIn("selection_channel: SELECTION_CHANNEL", page)
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
        self.assertIn('<h1 id="guide">Guide</h1>', page)
        self.assertIn('<h2 id="overview">Overview</h2>', page)
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
            self.assertIn('<h1 id="readme">README</h1>', page)

    def test_document_target_renderer_accepts_zoom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Project\n", encoding="utf-8")

            page, status = document_target_html(root, "README.md", zoom_percent=130)
            large_page, large_status = document_target_html(
                root,
                "README.md",
                zoom_percent=250,
            )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("--doc-font-size: 20.80px;", page)
        self.assertEqual(large_status, HTTPStatus.OK)
        self.assertIn("--doc-font-size: 40.00px;", large_page)

    def test_document_zoom_controls_have_no_upper_limit(self) -> None:
        runtime = read_service_text_asset("js/core/runtime.js")
        pane = PANE_WINDOW_HTML

        self.assertNotIn("MAX_DOCUMENT_ZOOM", runtime)
        self.assertNotIn("MAX_ARTIFACT_ZOOM", pane)
        self.assertIn(
            "return Math.max(DOCUMENT_ZOOM_STEP, stepped);",
            runtime,
        )
        self.assertIn(
            "return Math.max(ARTIFACT_ZOOM_STEP, stepped);",
            pane,
        )
        self.assertIn("increaseArtifactZoom.disabled = false;", pane)

    def test_document_zoom_defaults_when_browser_preference_is_missing(self) -> None:
        runtime = read_service_text_asset("js/core/runtime.js")

        self.assertIn("const DEFAULT_DOCUMENT_ZOOM = 100;", runtime)
        self.assertIn(
            'if (storedValue === null || storedValue.trim() === "") {',
            runtime,
        )
        self.assertIn("return DEFAULT_DOCUMENT_ZOOM;", runtime)

    def test_document_target_renderer_supports_repository_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "guide.md").write_text(
                "# Guide\n\n"
                "## Installation Notes\n\n"
                "[Jump](#installation-notes)\n\n"
                "[API](../reference/api.md#authentication)\n"
                "[Site](https://example.com/reference)\n",
                encoding="utf-8",
            )

            page, status = document_target_html(root, "docs/guide.md")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn('<h2 id="installation-notes">Installation Notes</h2>', page)
        self.assertIn('<a href="#installation-notes">Jump</a>', page)
        self.assertIn(
            '<a href="../reference/api.md#authentication">API</a>',
            page,
        )
        self.assertIn(
            '<a href="https://example.com/reference">Site</a>',
            page,
        )
        self.assertIn('const currentDocumentPath = "docs/guide.md";', page)
        self.assertIn('type: "electroboy:document-link"', page)
        self.assertIn("location: currentDocumentLocation()", page)
        self.assertIn('location: { fragment: target.fragment }', page)
        self.assertIn("function externalLinkTarget(href)", page)
        self.assertIn("window.location.assign(target.url);", page)
        self.assertIn(
            'window.open(target.url, "_blank", "noopener,noreferrer")',
            page,
        )
        self.assertIn("openedExternally", page)
        self.assertIn("url.origin === window.location.origin", page)
        self.assertIn('data.type !== "electroboy:document-location"', page)
        self.assertIn('const absolutePath = linkPath.startsWith("/");', page)
        self.assertIn('window.parent.postMessage(', page)

    def test_external_link_placeholder_uses_top_level_navigation(self) -> None:
        page, status = external_link_html("https://example.com/docs?q=1#intro")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("<title>External Link</title>", page)
        self.assertIn("example.com", page)
        self.assertIn('href="https://example.com/docs?q=1#intro"', page)
        self.assertIn('target="_blank"', page)
        self.assertIn(
            'window.open(externalUrl, "_blank", "noopener,noreferrer")',
            page,
        )

    def test_external_link_placeholder_rejects_non_http_urls(self) -> None:
        _, status = external_link_html("javascript:alert(1)")

        self.assertEqual(status, HTTPStatus.BAD_REQUEST)

    def test_document_target_renderer_rewrites_local_image_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            (docs / "guide.md").write_text(
                "# Guide\n\n"
                "![Diagram](images/diagram.png)\n\n"
                "![Photo](../photo.jpg)\n\n"
                "![Remote](https://example.com/remote.png)\n\n"
                "![Inline](data:image/png;base64,AA==)\n",
                encoding="utf-8",
            )

            page, status = document_target_html(
                root,
                "docs/guide.md",
                asset_context={
                    "context_id": "ctx-1",
                    "connection_id": "connection-1",
                },
            )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn(
            'src="/artifacts/document-image?document_path=docs%2Fguide.md'
            '&amp;image_path=images%2Fdiagram.png&amp;context_id=ctx-1'
            '&amp;connection_id=connection-1"',
            page,
        )
        self.assertIn(
            'src="/artifacts/document-image?document_path=docs%2Fguide.md'
            '&amp;image_path=..%2Fphoto.jpg&amp;context_id=ctx-1'
            '&amp;connection_id=connection-1"',
            page,
        )
        self.assertIn('src="https://example.com/remote.png"', page)
        self.assertIn('src="data:image/png;base64,AA=="', page)

    def test_document_target_renderer_handles_code_fences_and_mermaid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "README.md"
            target.write_text(
                "# Project\n\n"
                "### Clone the repositories\n\n"
                "```bash\nmkdir -p qhpc\ncd qhpc\n```\n\n"
                "```mermaid\nsequenceDiagram\n  Alice->>Bob: Hi\n```\n",
                encoding="utf-8",
            )

            page, status = document_target_html(root, "README.md")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn(
            '<h3 id="clone-the-repositories">Clone the repositories</h3>',
            page,
        )
        self.assertIn('<pre><code class="language-bash">mkdir -p qhpc', page)
        self.assertIn('<div class="mermaid">sequenceDiagram', page)
        self.assertIn("mermaid@10", page)
        self.assertIn("function openMermaidPopup(diagram)", page)
        self.assertIn("URL.createObjectURL(new Blob", page)
        self.assertIn("function diagramMarkup(diagram)", page)
        self.assertIn("function initializeDiagramPopup(title)", page)
        self.assertIn("function contentBox(svg)", page)
        self.assertIn("function updateBaseSize()", page)
        self.assertIn("availableWidth / naturalWidth", page)
        self.assertIn(r".split(/\\s+/)", page)
        self.assertIn('"viewBox"', page)
        self.assertIn('"preserveAspectRatio"', page)
        self.assertIn('id="sequenceHeader"', page)
        self.assertIn("function isSequenceDiagram(svg)", page)
        self.assertIn("function buildSequenceHeader()", page)
        self.assertIn("function syncSequenceHeader()", page)
        self.assertIn('svg.querySelector("text.actor")', page)
        self.assertIn('svg.querySelector(".actor-line")', page)
        self.assertIn('querySelectorAll("text.actor, .actor text")', page)
        self.assertIn('className = "sequence-header-actor"', page)
        self.assertIn(r'return text.replace(/\\s+/g, " ");', page)
        self.assertIn("overflow-wrap: anywhere;", page)
        self.assertIn("white-space: normal;", page)
        self.assertIn('candidate.matches?.("rect.actor")', page)
        self.assertIn("function sequenceDiagramScale(svg)", page)
        self.assertIn("rect.width / naturalWidth", page)
        self.assertIn("function sequenceHeaderMetrics(", page)
        self.assertIn("fontSize: Math.max(1, fontSize * scale),", page)
        self.assertIn("headerHeight: renderedHeight + 14 * scale,", page)
        self.assertIn(
            "const boxRect = actor.sourceBox?.getBoundingClientRect();",
            page,
        )
        self.assertIn(
            'sequenceHeader.style.height = headerHeight + "px";',
            page,
        )
        self.assertIn('actor.label.style.left = centerX + "px";', page)
        self.assertIn('actor.label.style.fontSize = metrics.fontSize + "px";', page)
        self.assertIn('actor.label.style.width = metrics.width + "px";', page)
        self.assertIn("window.requestAnimationFrame", page)
        self.assertIn("const wheelZoomFactor = 1.1;", page)
        self.assertIn("function zoomTo(nextZoom, clientX = null, clientY = null)", page)
        self.assertIn("viewport.scrollLeft += rect.left", page)
        self.assertIn("function handleWheelZoom(event)", page)
        self.assertIn("function startPan(event)", page)
        self.assertIn("event.button !== 1", page)
        self.assertIn("viewport.scrollLeft", page)
        self.assertIn(
            'viewport.addEventListener("wheel", handleWheelZoom, { passive: false });',
            page,
        )
        self.assertIn('viewport.addEventListener("scroll", syncSequenceHeader);', page)
        self.assertIn('viewport.addEventListener("pointerdown", startPan);', page)
        self.assertIn('viewport.addEventListener("auxclick", (event) => {', page)
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
        self.assertIn(
            '<h3 id="site-configuration">Site Configuration</h3>',
            page,
        )
        self.assertNotIn("| Owner | Configuration | Purpose |", page)
        self.assertNotIn("### Site Configuration", page)

    def test_document_target_renderer_supports_paths_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "project"
            root.mkdir()
            external = base / "shared" / "notes.md"
            external.parent.mkdir()
            external.write_text("# External notes\n", encoding="utf-8")

            page, status = document_target_html(root, str(external))
            editor, editor_status = artifact_editor_html(
                root,
                "document",
                str(external),
            )
            result = save_artifact_edit(
                root,
                "document",
                str(external),
                {"mode": "markdown", "markdown": "# Updated notes\n"},
            )
            created_page, created_status = document_target_html(
                root,
                "../outside.md",
                create_missing=True,
            )

            self.assertEqual(status, HTTPStatus.OK)
            self.assertIn('<h1 id="external-notes">External notes</h1>', page)
            self.assertIn(
                f"const currentDocumentPath = {json.dumps(str(external))};",
                page,
            )
            self.assertEqual(editor_status, HTTPStatus.OK)
            self.assertIn('"mode": "markdown"', editor)
            self.assertEqual(result["markdown_path"], str(external))
            self.assertEqual(
                external.read_text(encoding="utf-8"),
                "# Updated notes\n",
            )
            self.assertEqual(created_status, HTTPStatus.OK)
            self.assertTrue((base / "outside.md").is_file())
            self.assertIn('<h1 id="outside">Outside</h1>', created_page)

    def test_document_target_renderer_rejects_non_markdown_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

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
                editor_font_size=48,
            )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn('"rich_editor": true', page)
        self.assertIn('"editor_font_size": 48', page)
        self.assertIn("--editor-font-size: 48px;", page)
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

    def test_document_image_endpoint_serves_images_relative_to_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "project"
            root.mkdir()
            external_docs = base / "shared" / "docs"
            image_directory = external_docs / "images"
            image_directory.mkdir(parents=True)
            document = external_docs / "guide.md"
            document.write_text(
                "# Guide\n\n![Pixel](images/pixel.png)\n",
                encoding="utf-8",
            )
            images = {
                "images/pixel.png": (b"png-image-data", "image/png"),
                "images/photo.jpg": (b"jpeg-image-data", "image/jpeg"),
            }
            for relative_path, (image_data, _content_type) in images.items():
                (external_docs / relative_path).write_bytes(image_data)

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
                preview_status, preview_body, preview_type = request(
                    server,
                    "/artifacts/document?"
                    + urlencode(
                        {
                            "context_id": context_id,
                            "path": str(document),
                        }
                    ),
                )
                responses = {}
                for image_path in images:
                    responses[image_path] = request_bytes(
                        server,
                        "/artifacts/document-image?"
                        + urlencode(
                            {
                                "context_id": context_id,
                                "document_path": str(document),
                                "image_path": image_path,
                            }
                        ),
                    )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(preview_status, 200)
        self.assertEqual(preview_type, "text/html; charset=utf-8")
        self.assertIn("/artifacts/document-image?document_path=", preview_body)
        for image_path, (expected_data, expected_type) in images.items():
            status, body, content_type, headers = responses[image_path]
            self.assertEqual(status, 200)
            self.assertEqual(body, expected_data)
            self.assertEqual(content_type, expected_type)
            self.assertNotIn("Content-Disposition", headers)

    def test_document_export_endpoint_serves_document_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "project"
            root.mkdir()
            external = base / "shared.md"
            external.write_text("# Shared\n", encoding="utf-8")
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
                        f"?context_id={context_id}&artifact=document"
                        f"&format=markdown&path={external}"
                    ),
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(body, b"# Shared\n")
        self.assertEqual(content_type, "text/markdown; charset=utf-8")
        self.assertEqual(
            headers.get("Content-Disposition"),
            'attachment; filename="shared.md"',
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
        self.assertIn(".stage-action-separator", core_styles)
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

            self.assertEqual(
                _artifact_event_document_path(root, "document", "../README.md"),
                root.resolve().parent / "README.md",
            )
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
                "mind-map",
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

        self.assertEqual(payload["status"], "resumed")
        self.assertEqual(payload["workspace_id"], first_context)
        self.assertEqual(payload["project_mode"], "meta")
        self.assertEqual(payload["activation_root"], str(meta_root.resolve()))
        self.assertIsNone(payload["active_project_root"])

    def test_service_state_ignores_stale_project_workspace_on_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            stale_context_id = str(
                state.create_context(workflow_id="software")["context_id"]
            )
            stale_context = state.contexts[stale_context_id]
            state.workspace_registry.adopt_context(
                stale_context,
                name=project_root.name,
                project_identity=str(project_root),
            )
            context_id = str(
                state.create_context(workflow_id="software")["context_id"]
            )

            payload = state.open_project(context_id, str(project_root))

        self.assertEqual(payload["status"], "opened")
        self.assertEqual(payload["context_id"], context_id)
        self.assertEqual(payload["workspace_id"], context_id)
        self.assertEqual(
            payload["active_project_root"],
            str(project_root.resolve()),
        )

    def test_service_state_ignores_stale_creative_workspace_on_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            project_root.mkdir()

            state = ServiceState(service_root)
            stale_context_id = str(
                state.create_context(workflow_id="creative-writing")["context_id"]
            )
            stale_context = state.contexts[stale_context_id]
            state.workspace_registry.adopt_context(
                stale_context,
                name=project_root.name,
                project_identity=str(project_root),
            )
            context_id = str(
                state.create_context(workflow_id="creative-writing")["context_id"]
            )

            payload = state.open_creative_project(context_id, str(project_root))

        self.assertEqual(payload["status"], "opened")
        self.assertEqual(payload["context_id"], context_id)
        self.assertEqual(payload["workspace_id"], context_id)
        self.assertEqual(payload["project_mode"], "creative")
        self.assertEqual(
            payload["active_project_root"],
            str(project_root.resolve()),
        )

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

    def test_recent_project_clear_route_removes_requested_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            state_root = Path(tmp) / "state"
            project_root = Path(tmp) / "project"
            creative_root = Path(tmp) / "story"
            meta_root = Path(tmp) / "openQSE"
            root.mkdir()
            state_root.mkdir()
            try:
                server = create_server(root, port=0, state_root=state_root)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            context_id = str(server.service_state.create_context()["context_id"])
            server.service_state.create_project(context_id, str(project_root))
            server.service_state.create_creative_project(
                context_id,
                str(creative_root),
            )
            server.service_state.create_meta_project(context_id, str(meta_root))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = post_json(
                    server,
                    f"/api/recent-projects/clear?context_id={context_id}",
                    {
                        "projects": [
                            {
                                "kind": "creative",
                                "path": str(creative_root.resolve()),
                            }
                        ],
                    },
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        payload = json.loads(body)
        recent = payload["recent_projects"]
        recent_paths = [entry["path"] for entry in recent]
        self.assertEqual(payload["status"], "cleared")
        self.assertNotIn(str(creative_root.resolve()), recent_paths)
        self.assertIn(str(project_root.resolve()), recent_paths)
        self.assertIn(str(meta_root.resolve()), recent_paths)

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
                        "control": "list",
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
                                "id": "source",
                                "label": "Source",
                                "dispatch": "host",
                                "always_visible": True,
                                "payload": {"source_id": "source:1"},
                            },
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
        self.assertEqual(snapshot["filters"][0]["control"], "list")
        page, status = render_agenda_html(snapshot)
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn('<body class="agenda-style-default">', page)
        self.assertIn('id="agendaControls"', page)
        self.assertIn(
            "body.agenda-embedded .agenda-header {\n      display: none;",
            page,
        )
        self.assertIn('element("div", "agenda-modal-overlay")', page)
        self.assertIn("async function invokeAction", page)
        self.assertIn("function dispatchAgendaHostAction", page)
        self.assertIn('type: "electroboy-agenda-action"', page)
        self.assertIn('if (action.dispatch === "host")', page)
        self.assertIn("!options.hideActions || action.always_visible", page)
        self.assertIn("async function openEditor", page)
        self.assertIn(
            'for (const key of ["workspace_id", "context_id", "connection_id", "lease_token"])',
            page,
        )
        self.assertIn("const value = current.get(key);", page)
        self.assertIn('type: "electroboy-agenda-state"', page)
        self.assertIn('styles: AGENDA_DATA.styles || []', page)
        self.assertIn('command.action === "set-style"', page)
        self.assertIn('command.action === "set-range"', page)
        self.assertIn('"provider": "fixture-agenda"', page)
        self.assertIn('"style": "default"', page)
        hud_page, hud_status = render_agenda_html(snapshot, style="hud")
        self.assertEqual(hud_status, HTTPStatus.OK)
        self.assertIn('<body class="agenda-style-hud">', hud_page)
        self.assertIn("body.agenda-style-hud .agenda-item", hud_page)
        self.assertIn('"id": "hud", "label": "HUD"', hud_page)
        command_page, command_status = render_agenda_html(
            snapshot,
            style="command-center",
        )
        self.assertEqual(command_status, HTTPStatus.OK)
        self.assertIn('<body class="agenda-style-command-center">', command_page)
        self.assertIn(
            "body.agenda-style-command-center .agenda-section",
            command_page,
        )
        self.assertIn(
            '"id": "command-center", "label": "Command Center"',
            command_page,
        )
        timeline_page, timeline_status = render_agenda_html(
            snapshot,
            style="timeline-stack",
        )
        self.assertEqual(timeline_status, HTTPStatus.OK)
        self.assertIn('<body class="agenda-style-timeline-stack">', timeline_page)
        self.assertIn("@keyframes agenda-stack-settle", timeline_page)
        self.assertIn('article.style.setProperty("--agenda-index"', timeline_page)
        self.assertIn(
            '"id": "timeline-stack", "label": "Timeline Stack"',
            timeline_page,
        )
        radar_page, radar_status = render_agenda_html(snapshot, style="radar")
        self.assertEqual(radar_status, HTTPStatus.OK)
        self.assertIn('<body class="agenda-style-radar">', radar_page)
        self.assertIn("@keyframes agenda-radar-sweep", radar_page)
        self.assertIn("body.agenda-style-radar .agenda-items::before", radar_page)
        self.assertIn('"id": "radar", "label": "Radar"', radar_page)
        orbit_page, orbit_status = render_agenda_html(
            snapshot,
            style="family-orbit",
        )
        self.assertEqual(orbit_status, HTTPStatus.OK)
        self.assertIn('<body class="agenda-style-family-orbit">', orbit_page)
        self.assertIn("@keyframes agenda-orbit-float", orbit_page)
        self.assertIn(
            "body.agenda-style-family-orbit .agenda-items::before",
            orbit_page,
        )
        self.assertIn(
            '"id": "family-orbit", "label": "Family Orbit"',
            orbit_page,
        )
        month_page, month_status = render_agenda_html(snapshot, style="month-hud")
        self.assertEqual(month_status, HTTPStatus.OK)
        self.assertIn('<body class="agenda-style-month-hud">', month_page)
        self.assertIn("function renderMonthHud", month_page)
        self.assertIn("function agendaDateFromValue", month_page)
        self.assertIn("function itemIsDateOnly", month_page)
        self.assertIn("item.start_date || item.due_date || item.date", month_page)
        self.assertIn("function monthHudDebugGraph", month_page)
        self.assertIn("function monthHudDebugFactsByObservation", month_page)
        self.assertIn("...(graph.provider_events || [])", month_page)
        self.assertIn("function renderMonthHudFactCard", month_page)
        self.assertIn("function agendaEditableKind(item)", month_page)
        self.assertIn("@keyframes agenda-month-hud-idle", month_page)
        self.assertIn("@keyframes agenda-month-hud-branch-in", month_page)
        self.assertIn("@keyframes agenda-month-hud-card-focus", month_page)
        self.assertIn("--month-hud-active-size", month_page)
        self.assertIn("--stage-zoom", month_page)
        self.assertIn("scale(var(--stage-zoom))", month_page)
        self.assertIn("scale(calc(var(--stage-zoom) * .92))", month_page)
        self.assertIn("body.agenda-style-month-hud .month-hud-node", month_page)
        self.assertIn("body.agenda-style-month-hud .month-hud-node.selected", month_page)
        self.assertIn("body.agenda-style-month-hud .month-hud-year-control", month_page)
        self.assertIn("body.agenda-style-month-hud .month-hud-year-step", month_page)
        self.assertIn("body.agenda-style-month-hud .month-hud-year-value", month_page)
        self.assertIn("body.agenda-style-month-hud .month-hud-year-input", month_page)
        self.assertIn("body.agenda-style-month-hud .month-hud.is-changing-year", month_page)
        self.assertIn(
            "body.agenda-style-month-hud .month-hud.is-editing-card .month-hud-canvas",
            month_page,
        )
        self.assertIn("body.agenda-style-month-hud .month-hud-card-editor", month_page)
        self.assertIn(
            "body.agenda-style-month-hud .month-hud-card-editor.has-confirmation",
            month_page,
        )
        self.assertIn("body.agenda-style-month-hud .month-hud-check-menu", month_page)
        self.assertIn("body.agenda-style-month-hud .month-hud-edit-layer.is-closing", month_page)
        self.assertIn(
            "body.agenda-style-month-hud .month-hud-edit-layer.is-closing .month-hud-card-editor",
            month_page,
        )
        self.assertIn("body.agenda-style-month-hud .month-hud-confirm-layer", month_page)
        self.assertIn("body.agenda-style-month-hud .month-hud-confirm-layer.is-open", month_page)
        self.assertIn(
            "body.agenda-style-month-hud .month-hud-confirm-layer.is-closing",
            month_page,
        )
        self.assertIn("body.agenda-style-month-hud .month-hud-confirm-dialog", month_page)
        self.assertIn("body.agenda-style-month-hud .month-hud-fact-fanout", month_page)
        self.assertIn("body.agenda-style-month-hud .month-hud-fact-detail", month_page)
        self.assertIn("body.agenda-style-month-hud .month-hud-fact-card", month_page)
        self.assertIn(
            "body.agenda-style-month-hud .month-hud-branch.debug-expanded",
            month_page,
        )
        self.assertIn(
            "body.agenda-style-month-hud .month-hud-branches:has(.debug-expanded)",
            month_page,
        )
        self.assertIn("left: var(--branch-card-left, 50%);", month_page)
        self.assertIn("top: var(--branch-card-top, 50%);", month_page)
        self.assertIn("width: var(--branch-card-width, var(--month-hud-branch-width));", month_page)
        self.assertIn(
            'branch.style.setProperty("--branch-card-height"',
            month_page,
        )
        self.assertIn(
            "calc(-100% - (var(--branch-card-height, 136px) / 2) - 10px)",
            month_page,
        )
        self.assertIn("transform-origin: bottom center;", month_page)
        self.assertNotIn("translate(-50%, -50%) scale(1)", month_page)
        self.assertNotIn("const preferredFactTop", month_page)
        self.assertNotIn("facts-below-card", month_page)
        self.assertNotIn("facts-left", month_page)
        self.assertNotIn("facts-right", month_page)
        self.assertNotIn("facts-below\"", month_page)
        self.assertIn("function openMonthHudCardEditor", month_page)
        self.assertIn("function applyAgendaInlineDraft", month_page)
        self.assertIn("function removeAgendaInlineItem", month_page)
        self.assertIn("async function submitMonthHudEditor", month_page)
        self.assertIn("function monthHudSelect", month_page)
        self.assertIn("function monthHudPeoplePicker", month_page)
        self.assertIn("function monthHudCheckedPeople", month_page)
        self.assertIn("function closeDiscardConfirmation", month_page)
        self.assertIn("function openDiscardConfirmation", month_page)
        self.assertIn("function layoutMonthHud", month_page)
        self.assertIn("function renderMonthBranches", month_page)
        self.assertIn("function sortMonthEvents", month_page)
        self.assertIn("function setCircuitSegment", month_page)
        self.assertIn("function updateYearControl", month_page)
        self.assertIn("function clampMonthHudYear", month_page)
        self.assertIn("function startYearEdit", month_page)
        self.assertIn("function commitYearEdit", month_page)
        self.assertIn("function setDisplayYear", month_page)
        self.assertIn("function renderMonthRail", month_page)
        self.assertIn("function updateStageTransform", month_page)
        self.assertIn("function clampMonthHudZoom", month_page)
        self.assertIn("function updateMonthHudZoom", month_page)
        self.assertIn("function handleMonthHudWheel(event)", month_page)
        self.assertIn("const slotCount = columns * 2;", month_page)
        self.assertIn("const aboveCount = Math.min(columns, pairRemaining);", month_page)
        self.assertIn("const aboveTimeline = slot < aboveCount;", month_page)
        self.assertIn("const laneGap = branches.length <= 2", month_page)
        self.assertIn("const laneWidth = laneCount * cardWidth + (laneCount - 1) * gap;", month_page)
        self.assertIn(
            "const cardLeft = centerX - laneWidth / 2 + cardWidth / 2 + laneIndex * (cardWidth + gap);",
            month_page,
        )
        self.assertIn(
            "const targetY = cardTop - verticalDirection * (cardHeight / 2);",
            month_page,
        )
        self.assertIn("const elbowX = targetX;", month_page)
        self.assertIn("const elbowY = targetY - verticalDirection * tailLength;", month_page)
        self.assertIn("function clearMonthSelection", month_page)
        self.assertIn(
            'event.target.closest(".agenda-item, .month-hud-node.selected, .month-hud-fact-card")',
            month_page,
        )
        self.assertIn("function monthSequence(year)", month_page)
        self.assertIn("let displayYear = referenceDate().getUTCFullYear();", month_page)
        self.assertIn("let months = monthSequence(displayYear);", month_page)
        self.assertIn('let timelineOffset = 0;', month_page)
        self.assertIn('let stagePanX = 0;', month_page)
        self.assertIn('let stageZoom = 1;', month_page)
        self.assertIn('const MIN_MONTH_HUD_YEAR = 1900;', month_page)
        self.assertIn('const MAX_MONTH_HUD_YEAR = 9999;', month_page)
        self.assertIn('const MIN_MONTH_HUD_ZOOM = 0.45;', month_page)
        self.assertIn('const MAX_MONTH_HUD_ZOOM = 2.8;', month_page)
        self.assertIn('const MONTH_HUD_ZOOM_FACTOR = 1.1;', month_page)
        self.assertIn('stage.style.setProperty("--stage-zoom", String(stageZoom));', month_page)
        self.assertIn(
            "pointerX - stagePanX - (1 - previousZoom) * originX",
            month_page,
        )
        self.assertIn("timelineOffset = dragState.timelineOffset + dx / dragState.stageZoom;", month_page)
        self.assertIn(
            'stage.addEventListener("wheel", handleMonthHudWheel, { passive: false });',
            month_page,
        )
        self.assertIn('if (event.button !== 2 && event.button !== 1) return;', month_page)
        self.assertIn('const mode = event.button === 2 ? "timeline" : "stage";', month_page)
        self.assertIn('element("div", "month-hud-branches")', month_page)
        self.assertIn('element("div", "month-hud-canvas")', month_page)
        self.assertIn('element("div", "month-hud-year-control")', month_page)
        self.assertIn('element("button", "month-hud-year-step"', month_page)
        self.assertIn('element("button", "month-hud-year-value")', month_page)
        self.assertIn('element("input", "month-hud-year-input")', month_page)
        self.assertIn('stage.append(canvas, yearControl);', month_page)
        self.assertIn('previousYear.addEventListener("click"', month_page)
        self.assertIn('nextYear.addEventListener("click"', month_page)
        self.assertIn('yearValue.addEventListener("click", startYearEdit);', month_page)
        self.assertIn('yearInput.addEventListener("keydown"', month_page)
        self.assertIn('yearInput.addEventListener("blur", commitYearEdit);', month_page)
        self.assertIn('element("div", "month-hud-edit-layer")', month_page)
        self.assertIn('element("form", "month-hud-card-editor")', month_page)
        self.assertIn('element("div", "month-hud-confirm-layer")', month_page)
        self.assertIn('element("section", "month-hud-confirm-dialog")', month_page)
        self.assertIn('element("div", "month-hud-fact-fanout")', month_page)
        self.assertIn('element("select", "month-hud-edit-select")', month_page)
        self.assertIn('element("details", "month-hud-check-menu")', month_page)
        self.assertIn(
            'monthHudOptionValues(["event", "task", "deadline"], agendaEditableKind(item))',
            month_page,
        )
        self.assertIn('card.classList.add("month-hud-editable-card")', month_page)
        self.assertIn('card.classList.add("month-hud-debug-card")', month_page)
        self.assertIn("No derived facts for this trace node.", month_page)
        self.assertIn('root.classList.add("is-editing-card")', month_page)
        self.assertIn("form.noValidate = true;", month_page)
        self.assertIn('checkbox.type = "checkbox";', month_page)
        self.assertIn('approve.type = "button";', month_page)
        self.assertIn("let editorClosing = false;", month_page)
        self.assertIn('layer.classList.add("is-closing");', month_page)
        self.assertIn('window.setTimeout(removeLayer, 560);', month_page)
        self.assertIn('confirmation.setAttribute("role", "dialog");', month_page)
        self.assertIn('form.classList.add("has-confirmation");', month_page)
        self.assertIn('confirmation.classList.add("is-closing");', month_page)
        self.assertIn('requestAnimationFrame(() => confirmation.classList.add("is-open"));', month_page)
        self.assertIn("Discarding this card will delete the event from the agenda.", month_page)
        self.assertIn('const cancel = element("button", "item-action", "Cancel");', month_page)
        self.assertIn('const ok = element("button", "item-action danger", "OK");', month_page)
        self.assertIn("openDiscardConfirmation();", month_page)
        self.assertIn("event.stopPropagation();", month_page)
        self.assertIn("if (event.target === layer) closeEditor();", month_page)
        self.assertIn('element("button", "item-action primary", "Approve")', month_page)
        self.assertIn('element("button", "item-action danger", "Discard")', month_page)
        self.assertIn('renderItem(item, index, { hideActions: true })', month_page)
        self.assertIn("toggleFactFanout()", month_page)
        self.assertIn('const result = await submitMonthHudEditor(item, "approve", draft);', month_page)
        self.assertIn("replaceAgendaInlineItem(item, result.item)", month_page)
        self.assertIn('await submitAgendaAction(item, { id: "discard" });', month_page)
        self.assertIn('element("span", "month-hud-circuit-segment is-primary")', month_page)
        self.assertIn('element("span", "month-hud-circuit-segment is-secondary")', month_page)
        self.assertIn('stage.setAttribute("aria-label", "Month timeline");', month_page)
        self.assertNotIn("month-hud-panel", month_page)
        self.assertNotIn("selectMonth(months.some", month_page)
        self.assertIn(
            '"id": "month-hud", "label": "Month HUD"',
            month_page,
        )

    def test_mind_map_contract_renders_source_first_canvas(self) -> None:
        snapshot = normalize_mind_map_snapshot(
            {
                "title": "Household Mind Map",
                "subtitle": "Source traceability",
                "levels": ["source", "observation", "fact"],
                "sources": [
                    {
                        "id": "source:fall-calendar",
                        "kind": "source",
                        "title": "Fall calendar.pdf",
                        "media_type": "application/pdf",
                        "status": "observed",
                        "observation_count": 1,
                        "fact_count": 1,
                        "details": {
                            "record_type": "source",
                            "source_table": "bp_ingestion.sources",
                            "id": "fall-calendar",
                        },
                        "actions": [
                            {
                                "id": "source",
                                "label": "View",
                                "dispatch": "host",
                                "payload": {
                                    "source_id": "fall-calendar",
                                    "filename": "Fall calendar.pdf",
                                },
                            }
                        ],
                    }
                ],
                "observations": [
                    {
                        "id": "observation:labor-day",
                        "kind": "observation",
                        "title": "School closed for Labor Day",
                        "observation_kind": "event",
                        "confidence": 0.98,
                        "member_labels": ["Jacob"],
                        "details": {
                            "record_type": "observation",
                            "source_table": "bp_ingestion.observations",
                            "kind": "event",
                        },
                    }
                ],
                "provider_events": [],
                "facts": [
                    {
                        "id": "planning_fact:labor-day",
                        "kind": "fact",
                        "title": "School closed for Labor Day",
                        "fact_type": "schedule_exception",
                        "status": "candidate",
                        "confidence": 0.92,
                        "member_labels": ["Jacob"],
                        "details": {
                            "record_type": "planning_fact",
                            "source_table": "bp_planning.planning_facts",
                            "fact_type": "schedule_exception",
                        },
                    }
                ],
                "edges": [
                    {
                        "id": "source-observation",
                        "from": "source:fall-calendar",
                        "to": "observation:labor-day",
                        "relationship": "produced_observation",
                        "family": "provenance",
                        "primary": True,
                        "state": "active",
                    },
                    {
                        "from": "observation:labor-day",
                        "to": "planning_fact:labor-day",
                        "relationship": "produced_fact",
                    },
                ],
            },
            provider_id="fixture-mind-map",
        )

        page, status = render_mind_map_html(snapshot, style="month-hud")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(snapshot["provider"], "fixture-mind-map")
        self.assertIn('<body class="mind-map-style-month-hud">', page)
        self.assertIn('id="mindMapViewport"', page)
        self.assertIn('id="mindMapCanvas"', page)
        self.assertIn('id="mindMapResetLayout"', page)
        self.assertIn('id="mindMapCleanMode"', page)
        self.assertIn('id="mindMapFullMode"', page)
        self.assertIn('id="mindMapLegend"', page)
        self.assertIn(".mind-map-control", page)
        self.assertIn("function displayedLayout", page)
        self.assertIn("function selectPrimaryEdgeIds", page)
        self.assertIn("function emitMindMapTelemetry", page)
        self.assertIn("function emitGraphTelemetry", page)
        self.assertIn("function telemetryNodeLayout", page)
        self.assertIn('"mind_map.graph.received"', page)
        self.assertIn('"mind_map.graph.nodes"', page)
        self.assertIn('"mind_map.graph.edges"', page)
        self.assertIn('"mind_map.node.toggle.requested"', page)
        self.assertIn('"mind_map.node.toggle.completed"', page)
        self.assertIn("function renderLegend", page)

        self.assertIn("function relationshipStyle", page)
        self.assertIn("const SOURCE_X = 80;", page)
        self.assertIn("const ROOT_GAP = 54;", page)
        self.assertIn("const SIBLING_GAP = 24;", page)
        self.assertIn("const CANVAS_PADDING = 420;", page)
        self.assertIn("const LAYOUT_VERSION = 7;", page)
        self.assertIn("const NODE_DRAG_THRESHOLD = 4;", page)
        self.assertIn('"levels": ["source", "observation", "fact"]', page)
        self.assertIn('"family": "provenance"', page)
        self.assertIn('"primary": true', page)
        self.assertIn("event.button !== 1", page)
        self.assertIn("function zoomAt", page)
        self.assertIn("function layoutHasVisibleNode", page)
        self.assertIn("function fitSourceColumn", page)
        self.assertIn("function resetLayout", page)
        self.assertIn("function collectVisibleGraph", page)
        self.assertIn("function positionVisibleNodes", page)
        self.assertIn("function median", page)
        self.assertIn('if (node.kind === "fact") return ["fact"];', page)
        self.assertIn("function resolveLayoutCollisions", page)
        self.assertIn("function nodesOverlapHorizontally", page)
        self.assertIn("function nodeHeight", page)
        self.assertIn("function nodeDetailEntries", page)
        self.assertIn("function createNodeDetails", page)
        self.assertIn("function toggleNodeDetails", page)
        self.assertIn("function measureRenderedNodes", page)
        self.assertIn("function scheduleMeasuredRender", page)
        self.assertIn("function resizeCanvasToLayout", page)
        self.assertIn("function startNodeDrag", page)
        self.assertIn("function updateNodeDrag", page)
        self.assertIn("function nodeActions", page)
        self.assertIn("function dispatchMindMapHostAction", page)
        self.assertIn('type: "electroboy-mind-map-action"', page)
        self.assertIn('className = "mind-map-action"', page)
        self.assertIn(".mind-map-node__actions", page)
        self.assertIn("const manualOffsets = new Map();", page)
        self.assertIn('const resetLayoutButton = document.getElementById("mindMapResetLayout");', page)
        self.assertIn("const measuredNodeHeights = new Map();", page)
        self.assertIn("const detailOpen = new Set();", page)
        self.assertIn("layoutVersion: LAYOUT_VERSION", page)
        self.assertIn('nodes: Object.fromEntries(', page)
        self.assertIn("function offsetForNode", page)
        self.assertIn("function visibleSubtreeIds", page)
        self.assertIn("function shiftSubtree", page)
        self.assertIn("function applyRenderedLayout", page)
        self.assertIn("const inheritedXOffsets = new Map();", page)
        self.assertIn("manualOffsets.set(nodeDrag.nodeId, nextOffset);", page)
        self.assertIn("manualOffsets.clear();", page)
        self.assertIn("localStorage.removeItem(stateKey);", page)
        self.assertIn("resetLayoutButton.addEventListener(\"click\"", page)
        self.assertIn("element.dataset.nodeId = node.id;", page)
        self.assertIn('if (node.kind === "observation") return "observation";', page)
        self.assertIn('id: "__details"', page)
        self.assertIn('"source_table": "bp_ingestion.observations"', page)
        self.assertIn('"source_table": "bp_planning.planning_facts"', page)
        self.assertIn('element.addEventListener("pointerdown"', page)
        self.assertIn('window.addEventListener("pointermove", updateNodeDrag);', page)
        self.assertIn("const worldX = (pointerX - pan.x) / previousScale;", page)
        self.assertIn('"title": "Fall calendar.pdf"', page)
        self.assertIn('"fact_type": "schedule_exception"', page)

    def test_editable_mind_map_documents_save_with_revision_protection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = ".electroboy/shared/mind-maps/launch.mindmap.json"
            document = empty_mind_map("Launch plan")
            document["nodes"] = [
                {
                    "id": "root",
                    "text": "Launch plan",
                    "parent_id": None,
                    "order": 0,
                    "x": 80,
                    "y": 90,
                    "side": "left",
                    "color": "teal",
                    "font_size": 22.5,
                    "font_size_mode": "custom",
                    "links": [{"type": "file", "target": "launch.md"}],
                }
            ]

            created = save_mind_map(root, path, document, create=True)
            loaded = load_mind_map(root, path)

            self.assertEqual(loaded, created)
            self.assertEqual(loaded["document"]["nodes"][0]["color"], "teal")
            self.assertEqual(loaded["document"]["nodes"][0]["side"], "left")
            self.assertEqual(loaded["document"]["nodes"][0]["font_size"], 22.5)
            self.assertEqual(
                loaded["document"]["nodes"][0]["font_size_mode"], "custom"
            )
            self.assertEqual(loaded["document"]["nodes"][0]["width"], 260.0)
            self.assertEqual(loaded["document"]["nodes"][0]["min_height"], 58.0)
            self.assertEqual(list_mind_maps(root)[0]["title"], "Launch plan")
            updated = dict(loaded["document"])
            updated["title"] = "Updated launch plan"
            saved = save_mind_map(
                root,
                path,
                updated,
                expected_revision=str(loaded["revision"]),
            )
            self.assertNotEqual(saved["revision"], loaded["revision"])
            with self.assertRaisesRegex(StateError, "changed on disk"):
                save_mind_map(
                    root,
                    path,
                    updated,
                    expected_revision=str(loaded["revision"]),
                )

    def test_editable_mind_map_rejects_parent_cycles(self) -> None:
        with self.assertRaisesRegex(StateError, "parent cycle"):
            normalize_mind_map(
                {
                    "nodes": [
                        {"id": "one", "parent_id": "two"},
                        {"id": "two", "parent_id": "one"},
                    ]
                }
            )
        with self.assertRaisesRegex(StateError, "unsupported URL"):
            normalize_mind_map(
                {
                    "nodes": [
                        {
                            "id": "unsafe-link",
                            "links": [
                                {"type": "url", "target": "javascript:alert(1)"}
                            ],
                        }
                    ]
                }
            )
        with self.assertRaisesRegex(StateError, "invalid color"):
            normalize_mind_map({"nodes": [{"id": "invalid", "color": "infrared"}]})
        with self.assertRaisesRegex(StateError, "invalid side"):
            normalize_mind_map({"nodes": [{"id": "invalid", "side": "above"}]})
        with self.assertRaisesRegex(StateError, "greater than zero"):
            normalize_mind_map(
                {
                    "nodes": [
                        {
                            "id": "invalid",
                            "font_size": 0,
                            "font_size_mode": "custom",
                        }
                    ]
                }
            )
        with self.assertRaisesRegex(StateError, "width and min_height"):
            normalize_mind_map({"nodes": [{"id": "invalid", "width": 0}]})

    def test_editable_mind_map_defaults_font_size_by_generation(self) -> None:
        nodes = []
        parent_id = None
        for index in range(7):
            node_id = f"generation-{index}"
            node = {"id": node_id, "parent_id": parent_id}
            if index == 0:
                node["font_size"] = 16
            nodes.append(node)
            parent_id = node_id

        normalized = normalize_mind_map({"nodes": nodes})

        self.assertEqual(
            [node["font_size"] for node in normalized["nodes"]],
            [24.0, 21.0, 18.0, 15.0, 14.0, 14.0, 14.0],
        )

    def test_editable_mind_map_infers_legacy_branch_side(self) -> None:
        normalized = normalize_mind_map(
            {
                "nodes": [
                    {"id": "root", "x": 400, "width": 260},
                    {"id": "left", "parent_id": "root", "x": 60},
                    {"id": "right", "parent_id": "root", "x": 740},
                ]
            }
        )

        self.assertEqual(
            [node["side"] for node in normalized["nodes"]],
            ["right", "left", "right"],
        )

    def test_editable_mind_map_workspace_has_keyboard_canvas_and_links(self) -> None:
        page, status = render_editable_mind_map_html(
            {
                "path": "/tmp/launch.mindmap.json",
                "revision": "revision-one",
                "document": empty_mind_map("Launch plan"),
            },
            context_id="workspace-one",
            connection_id="connection-one",
            lease_token="lease-one",
        )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn('aria-label="Mind map context tools"', page)
        self.assertIn('data-action="child"', page)
        self.assertIn('data-action="create-document"', page)
        self.assertIn('event.key === "Tab"', page)
        self.assertIn('event.key === "Enter" && event.shiftKey', page)
        self.assertIn('event.button === 1', page)
        self.assertIn("Math.exp(-event.deltaY", page)
        self.assertIn("expected_revision: revision", page)
        self.assertIn(
            "workspace_id=workspace-one&amp;context_id=workspace-one&amp;"
            "connection_id=connection-one&amp;lease_token=lease-one",
            page.replace("&", "&amp;"),
        )
        self.assertIn("electroboy:editable-mind-map", page)
        self.assertIn('.empty[hidden] { display: none; }', page)
        self.assertIn('data-action="color-blue"', page)
        self.assertIn("function resolvedNodeColor(node)", page)
        self.assertIn("function initialNodeColor(parentId)", page)
        self.assertIn("BRANCH_COLORS = Object.freeze", page)
        self.assertIn("function dropIntentForNode(draggedId, previousIntent", page)
        self.assertIn("function applyNodeDrop(node, intent, before)", page)
        self.assertIn("function reflowMovedRootBranch(node)", page)
        self.assertIn("function reflowTree(root)", page)
        self.assertIn("function resolveLocalOverlaps(parent)", page)
        self.assertIn('let layoutMode = "local";', page)
        self.assertIn('"layout-freeform": () => setLayoutMode("freeform")', page)
        self.assertIn("const NODE_VERTICAL_SPACING = 20;", page)
        self.assertIn('className: `drop-child-${side}`', page)
        self.assertIn('label: `Sibling · ${placement}`', page)
        self.assertIn('element.dataset.color = resolvedNodeColor(node);', page)
        self.assertIn('"font-size-set": (data) => setNodeFontSize', page)
        self.assertIn("selectedFontSize:", page)
        self.assertIn("return new Set([selectedId]);", page)
        self.assertIn('className = "node-resize-handle"', page)
        self.assertIn('drag = { type: "resize"', page)
        self.assertIn("ROOT_NODE_FONT_SIZE = 24", page)
        self.assertIn("MINIMUM_NODE_FONT_SIZE = 14", page)
        self.assertIn('node.font_size_mode = "custom"', page)
        self.assertIn("useAutomaticNodeFontSize", page)
        self.assertIn('id="mindMapDialog" class="mind-map-dialog"', page)
        self.assertIn(".mind-map-dialog.danger", page)
        self.assertIn("mindMapDialogSubmit.onclick = submit;", page)
        self.assertIn('await chooseFile("document-new")', page)
        self.assertIn('browseMode: type === "file" ? "link" : ""', page)
        self.assertNotIn("prompt(", page)
        self.assertNotIn("confirm(", page)
        self.assertIn("commitEdit(node.id, editor)", page)
        self.assertIn("const AUTOSAVE_DELAY_MS = 800;", page)
        self.assertIn("save({ automatic: true })", page)
        self.assertIn("const savingVersion = changeVersion;", page)
        self.assertIn("pendingEditRender = true;", page)
        self.assertIn('{ render: false, focus: false }', page)
        self.assertIn('data.type === "electroboy-mind-map-context"', page)
        self.assertIn('parameters.set("lease_token", String(data.leaseToken))', page)

    def test_agenda_uses_a_dedicated_pane_and_filter_tools(self) -> None:
        runtime = read_service_text_asset("js/core/runtime.js")
        agenda = read_service_text_asset("js/modules/agenda.js")
        tools = read_service_text_asset("js/modules/agenda-pane-tools.js")
        styles = read_service_text_asset("css/agenda-pane-tools.css")
        page = pane_window_html("agenda")

        self.assertIn('agenda: { label: "Agenda", element: null }', runtime)
        self.assertIn("runtime.layout.assignWorkspacePane", agenda)
        self.assertIn("function styles()", agenda)
        self.assertIn('Object.freeze({ id: "hud", label: "HUD" })', agenda)
        self.assertIn(
            'Object.freeze({ id: "command-center", label: "Command Center" })',
            agenda,
        )
        self.assertIn(
            'Object.freeze({ id: "timeline-stack", label: "Timeline Stack" })',
            agenda,
        )
        self.assertIn('Object.freeze({ id: "radar", label: "Radar" })', agenda)
        self.assertIn(
            'Object.freeze({ id: "family-orbit", label: "Family Orbit" })',
            agenda,
        )
        self.assertIn(
            'Object.freeze({ id: "month-hud", label: "Month HUD" })',
            agenda,
        )
        self.assertNotIn('"documents",\n      "showArtifactPreviews"', agenda)
        self.assertIn('const PANE_KIND = "agenda";', page)
        self.assertIn("ElectroBoyAgendaPaneTools.mount", page)
        self.assertIn("initialStyle: artifactAgendaStyle", page)
        self.assertNotIn(
            'PANE_KIND === "agenda" && window.ElectroBoyFilePaneTools',
            page,
        )
        self.assertIn('controller.addSection("agenda-display", "Display")', tools)
        self.assertIn('controller.addSection("agenda-filters", "Filters")', tools)
        self.assertIn('controller.addSection("agenda-date", "Date")', tools)
        self.assertIn("function agendaStyleClass", tools)
        self.assertIn("paneRoot.dataset.agendaStyle = nextStyle", tools)
        self.assertIn("const initialStyle = agendaStyleClass(options.initialStyle)", tools)
        self.assertIn("agenda.tools.mounted", tools)
        self.assertIn("agenda.tools.style_applied", tools)
        self.assertIn("agenda.tools.state_received", tools)
        self.assertIn("agenda.tools.initial_style_mismatch", tools)
        self.assertIn('post("set-style"', tools)
        self.assertIn("function agendaActionHost()", tools)
        self.assertIn('data.type !== "electroboy-agenda-action"', tools)
        self.assertIn("host.postMessage(data, window.location.origin)", tools)
        self.assertIn(".agenda-tool-style-field", styles)
        self.assertIn(".agenda-pane .pane-tools-shelf", styles)
        self.assertIn('--agenda-tool-shelf-bg: #f8f3e9;', styles)
        self.assertIn(
            '.agenda-pane[data-agenda-style="command-center"]',
            styles,
        )
        self.assertIn('.agenda-pane[data-agenda-style="hud"]', styles)
        self.assertIn('.agenda-pane[data-agenda-style="radar"]', styles)
        self.assertIn(
            '.agenda-pane[data-agenda-style="family-orbit"]',
            styles,
        )
        self.assertIn(
            '.agenda-pane[data-agenda-style="month-hud"] .pane-tools-shelf',
            styles,
        )
        self.assertIn("grid-template-columns: minmax(0, 1fr);", styles)
        self.assertIn("inset: 0 auto 0 0;", styles)

    def test_calendar_contract_renders_month_grid_and_event_details(self) -> None:
        snapshot = normalize_calendar_snapshot(
            {
                "title": "Household Calendar",
                "timezone": "UTC",
                "range_start": "2026-08-01",
                "range_end": "2026-08-31",
                "selected_calendar_ids": ["family"],
                "calendars": [
                    {"id": "family", "label": "Family", "color": "#2563eb"},
                    {"id": "work", "label": "Work", "color": "#16a34a"},
                ],
                "events": [
                    {
                        "id": "event-0",
                        "calendar_id": "family",
                        "title": "Fall break",
                        "start_date": "2026-08-12",
                        "end_date": "2026-08-15",
                        "all_day": True,
                    },
                    {
                        "id": "event-1",
                        "calendar_id": "family",
                        "title": "Soccer",
                        "start_at": "2026-08-17T21:00:00+00:00",
                        "end_at": "2026-08-17T22:00:00+00:00",
                        "location": "Field",
                        "metadata": [{"label": "Provider", "value": "google"}],
                    },
                    {
                        "id": "event-2",
                        "calendar_id": "work",
                        "title": "Planning",
                        "start_at": "2026-08-18T15:00:00+00:00",
                    },
                ],
            },
            provider_id="fixture-calendar",
            now=datetime(2026, 8, 17, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(snapshot["provider"], "fixture-calendar")
        self.assertEqual(snapshot["selected_calendar_ids"], ["family"])
        self.assertEqual(
            [event["title"] for event in snapshot["events"]],
            ["Fall break", "Soccer"],
        )
        page, status = render_calendar_html(snapshot, style="month-hud")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("Calendar", page)
        self.assertIn('body class="calendar-style-month-hud"', page)
        self.assertIn("calendar-grid", page)
        self.assertIn('id="monthPicker"', page)
        self.assertIn('id="calendarViewport"', page)
        self.assertIn('id="calendarCanvas"', page)
        self.assertIn("--calendar-size: min(980px", page)
        self.assertIn("calendar-event-span", page)
        self.assertIn(".calendar-event-span::after", page)
        self.assertIn("--calendar-span-divider", page)
        self.assertIn("--calendar-span-days", page)
        self.assertNotIn(".calendar-grid::after", page)
        self.assertIn("cell.style.gridColumn", page)
        self.assertIn("cell.style.gridRow", page)
        self.assertIn("function eventDisplayEndDate", page)
        self.assertIn("function eventSegments", page)
        self.assertIn("spans.segments.forEach", page)
        self.assertNotIn("calendar-empty", page)
        self.assertNotIn("No events in this view", page)
        self.assertIn('id="dayModal"', page)
        self.assertIn('id="dayView"', page)
        self.assertIn("body.calendar-day-open .calendar-shell", page)
        self.assertIn("body.calendar-style-month-hud .calendar-close", page)
        self.assertIn("background: rgba(7, 24, 31, .78);", page)
        self.assertIn('aria-label="Previous month">‹</button>', page)
        self.assertIn('aria-label="Next month">›</button>', page)
        self.assertIn("function renderMonth", page)
        self.assertIn("function requestMonth", page)
        self.assertIn("function openDayView", page)
        self.assertIn("function closeDayView", page)
        self.assertIn("function selectDay", page)
        self.assertIn("function openMonthPicker", page)
        self.assertIn("const rect = canvas.getBoundingClientRect();", page)
        self.assertIn("const scaleRatio = nextZoom / canvasZoom;", page)
        self.assertIn("function handleCanvasWheel", page)
        self.assertIn("function beginCanvasPan", page)
        self.assertIn('type: "electroboy-calendar-month-change"', page)
        self.assertIn("function openEvent", page)
        self.assertIn("type: \"electroboy-calendar-state\"", page)
        self.assertIn('"provider": "fixture-calendar"', page)
        self.assertIn('"title": "Fall break"', page)
        self.assertIn('"title": "Soccer"', page)
        self.assertNotIn('"title": "Planning"', page)
        for style in (
            "hud",
            "command-center",
            "timeline-stack",
            "radar",
            "family-orbit",
        ):
            styled_page, styled_status = render_calendar_html(snapshot, style=style)
            self.assertEqual(styled_status, HTTPStatus.OK)
            self.assertIn(f'body class="calendar-style-{style}"', styled_page)
            self.assertIn(f"body.calendar-style-{style} .calendar-grid", styled_page)
            self.assertIn(f"body.calendar-style-{style} .calendar-event", styled_page)

        empty_selection = normalize_calendar_snapshot(
            {
                **snapshot,
                "selected_calendar_ids": [],
            },
            provider_id="fixture-calendar",
            now=datetime(2026, 8, 17, 9, tzinfo=timezone.utc),
        )
        self.assertEqual(empty_selection["selected_calendar_ids"], [])
        self.assertEqual(empty_selection["events"], [])

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

            with (
                mock.patch("electroboy.service.AgentSession.start"),
                mock.patch(
                    "electroboy.workflows.creative_writing.controller"
                    ".codex_session_paths",
                    return_value=frozenset(),
                ),
                mock.patch(
                    "electroboy.workflows.creative_writing.controller"
                    ".start_creative_session_tracking",
                ),
            ):
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

            with (
                mock.patch("electroboy.service.AgentSession.start"),
                mock.patch(
                    "electroboy.workflows.creative_writing.controller"
                    ".codex_session_paths",
                    return_value=frozenset(),
                ),
                mock.patch(
                    "electroboy.workflows.creative_writing.controller"
                    ".start_creative_session_tracking",
                ),
            ):
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

            with (
                mock.patch("electroboy.service.AgentSession.start"),
                mock.patch(
                    "electroboy.workflows.creative_writing.controller"
                    ".codex_session_paths",
                    return_value=frozenset(),
                ),
                mock.patch(
                    "electroboy.workflows.creative_writing.controller"
                    ".start_creative_session_tracking",
                ),
            ):
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

    def test_creative_general_and_document_agents_are_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_creative_project(context_id, str(project_root))
            state.initialize_creative_workspace(context_id)

            with (
                mock.patch("electroboy.service.AgentSession.start"),
                mock.patch(
                    "electroboy.workflows.creative_writing.controller"
                    ".codex_session_paths",
                    return_value=frozenset(),
                ),
                mock.patch(
                    "electroboy.workflows.creative_writing.controller"
                    ".start_creative_session_tracking",
                ),
            ):
                general, general_started = state.start_creative_writing_agent(
                    context_id,
                    scope="general",
                    start_new=True,
                )
                document, document_started = state.start_creative_writing_agent(
                    context_id,
                    scope="document",
                    active_document="chapters/chapter-01.md",
                    start_new=True,
                )
                selected, selected_started = state.start_creative_writing_agent(
                    context_id,
                    scope="general",
                    session_id=general.session_id,
                )
                general_history = state.creative_agent_sessions(
                    context_id,
                    scope="general",
                )
                document_history = state.creative_agent_sessions(
                    context_id,
                    scope="document",
                    active_document="chapters/chapter-01.md",
                )
                records = json.loads(
                    _service_session_records_path(service_root).read_text(
                        encoding="utf-8",
                    )
                )
                record_selection = {
                    entry["session_id"]: entry["selected"]
                    for entry in records["sessions"]
                    if entry["session_id"] in {general.session_id, document.session_id}
                }

        self.assertTrue(general_started)
        self.assertTrue(document_started)
        self.assertIs(selected, general)
        self.assertFalse(selected_started)
        self.assertNotEqual(general.session_id, document.session_id)
        self.assertEqual(general.metadata["creative_scope"], "general")
        self.assertEqual(general.metadata["creative_scope_key"], "general")
        self.assertEqual(document.metadata["creative_scope"], "document")
        self.assertEqual(
            document.metadata["creative_scope_key"],
            "document:chapters/chapter-01.md",
        )
        self.assertEqual(document.metadata["document_path"], "chapters/chapter-01.md")
        self.assertEqual(
            [entry["electroboy_session_id"] for entry in general_history["sessions"]],
            [general.session_id],
        )
        self.assertEqual(
            [entry["electroboy_session_id"] for entry in document_history["sessions"]],
            [document.session_id],
        )
        self.assertEqual(
            record_selection,
            {
                general.session_id: True,
                document.session_id: False,
            },
        )

    def test_creative_agent_start_defaults_to_new_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            service_root.mkdir()
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_creative_project(context_id, str(project_root))
            state.initialize_creative_workspace(context_id)

            with (
                mock.patch("electroboy.service.AgentSession.start"),
                mock.patch(
                    "electroboy.workflows.creative_writing.controller"
                    ".codex_session_paths",
                    return_value=frozenset(),
                ),
                mock.patch(
                    "electroboy.workflows.creative_writing.controller"
                    ".start_creative_session_tracking",
                ),
            ):
                first, first_started = state.start_creative_writing_agent(
                    context_id,
                    scope="general",
                )
                first.process = mock.Mock()
                first.process.poll.return_value = None
                second, second_started = state.start_creative_writing_agent(
                    context_id,
                    scope="general",
                )

        self.assertTrue(first_started)
        self.assertTrue(second_started)
        self.assertNotEqual(first.session_id, second.session_id)

    def test_creative_document_agent_resumes_codex_provider_session(self) -> None:
        provider_session_id = "019f3cb6-60c3-7320-896b-e5eb9a6a8dd2"
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            codex_home = Path(tmp) / "codex"
            session_dir = codex_home / "sessions" / "2026" / "08" / "17"
            session_path = session_dir / f"rollout-{provider_session_id}.jsonl"
            service_root.mkdir()
            project_root.mkdir()
            session_dir.mkdir(parents=True)
            session_path.write_text(
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
                                                "Act as a creative writing "
                                                "collaborator inside this project."
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
                                            "text": "Revise the opening scene.",
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
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_creative_project(context_id, str(project_root))
            state.initialize_creative_workspace(context_id)

            with (
                mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}),
                mock.patch("electroboy.service.AgentSession.start"),
            ):
                session, started = state.start_creative_writing_agent(
                    context_id,
                    scope="document",
                    active_document="chapters/chapter-01.md",
                    provider_session_id=provider_session_id,
                )
                resumed_again, resumed_again_started = (
                    state.start_creative_writing_agent(
                        context_id,
                        scope="document",
                        active_document="chapters/chapter-01.md",
                        session_id=session.session_id,
                    )
                )
                history = state.creative_agent_sessions(
                    context_id,
                    scope="document",
                    active_document="chapters/chapter-01.md",
                )
            catalog = json.loads(
                (
                    service_root
                    / ".electroboy"
                    / "service"
                    / "creative-agent-sessions.json"
                ).read_text(encoding="utf-8")
            )

        self.assertTrue(started)
        self.assertEqual(session.command[-2:], ["resume", provider_session_id])
        self.assertTrue(resumed_again_started)
        self.assertIsNot(resumed_again, session)
        self.assertEqual(resumed_again.command[-2:], ["resume", provider_session_id])
        self.assertEqual(session.metadata["provider_session_id"], provider_session_id)
        self.assertTrue(session.metadata["resumed_session"])
        self.assertEqual(session.metadata["creative_scope"], "document")
        self.assertEqual(session.metadata["document_path"], "chapters/chapter-01.md")
        self.assertEqual(history["scope"], "document")
        self.assertEqual(
            history["sessions"][0]["provider_session_id"],
            provider_session_id,
        )
        self.assertEqual(history["sessions"][0]["title"], "Revise the opening scene.")
        self.assertEqual(catalog["schema_version"], 1)
        self.assertEqual(
            catalog["sessions"][0]["provider_session_id"],
            provider_session_id,
        )
        self.assertEqual(
            catalog["sessions"][0]["scope_key"],
            "document:chapters/chapter-01.md",
        )

    def test_creative_agent_imports_unscoped_codex_session_by_id(self) -> None:
        provider_session_id = "019f99e8-c540-7503-a821-806d11807fda"
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "story"
            external_root = Path(tmp) / "outside-codex-project"
            codex_home = Path(tmp) / "codex"
            session_dir = codex_home / "sessions" / "2026" / "07" / "25"
            session_path = (
                session_dir
                / f"rollout-2026-07-25T11-33-16-{provider_session_id}.jsonl"
            )
            service_root.mkdir()
            project_root.mkdir()
            external_root.mkdir()
            session_dir.mkdir(parents=True)
            session_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "session_meta",
                                "payload": {
                                    "session_id": provider_session_id,
                                    "timestamp": "2026-07-25T11:33:16+00:00",
                                    "cwd": str(external_root),
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
                                            "text": "Independent draft session.",
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
            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.create_creative_project(context_id, str(project_root))
            state.initialize_creative_workspace(context_id)

            with (
                mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}),
                mock.patch("electroboy.service.AgentSession.start"),
            ):
                session, started = state.start_creative_writing_agent(
                    context_id,
                    scope="document",
                    active_document="chapters/chapter-01.md",
                    session_id=provider_session_id,
                )
                session.process = mock.Mock()
                session.process.poll.return_value = None
                running_history = state.creative_agent_sessions(
                    context_id,
                    scope="document",
                    active_document="chapters/chapter-01.md",
                )
                session.process.poll.return_value = 0
                state.contexts[context_id].creative_sessions.clear()
                history = state.creative_agent_sessions(
                    context_id,
                    scope="document",
                    active_document="chapters/chapter-01.md",
                )
            catalog = json.loads(
                (
                    service_root
                    / ".electroboy"
                    / "service"
                    / "creative-agent-sessions.json"
                ).read_text(encoding="utf-8")
            )

        self.assertTrue(started)
        self.assertEqual(session.command[-2:], ["resume", provider_session_id])
        self.assertEqual(session.metadata["provider_session_id"], provider_session_id)
        self.assertTrue(session.metadata["resumed_session"])
        self.assertEqual(running_history["sessions"][0]["status"], "running")
        self.assertEqual(history["sessions"][0]["provider_session_id"], provider_session_id)
        self.assertEqual(history["sessions"][0]["title"], "Independent draft session.")
        self.assertEqual(
            catalog["sessions"][0]["project_root"],
            str(project_root.resolve()),
        )
        self.assertEqual(
            catalog["sessions"][0]["provider_project_root"],
            str(external_root.resolve()),
        )
        self.assertEqual(
            catalog["sessions"][0]["scope_key"],
            "document:chapters/chapter-01.md",
        )

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
            rules_created = (
                project_root
                / ".electroboy"
                / "local"
                / "agent-rules"
                / "software.md"
            ).is_file()

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
        self.assertIn("Effective rules file:", prompt)
        self.assertTrue(rules_created)
        self.assertNotIn("requirements", session.command[-1])
        self.assertNotIn("detailed-design", session.command[-1])
        self.assertEqual(payload["selected_session_id"], session.session_id)
        self.assertEqual(payload["sessions"][0]["kind"], "ad-hoc")

    def test_service_state_starts_multiple_ad_hoc_agents(self) -> None:
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
            with mock.patch("electroboy.service.AgentSession.start") as start:
                first, first_started = controller.start_ad_hoc_agent(context_id)
                second, second_started = controller.start_ad_hoc_agent(context_id)
            payload = state.project_payload(context_id)
            ad_hoc_sessions = state.contexts[context_id].ad_hoc_sessions

        self.assertTrue(first_started)
        self.assertTrue(second_started)
        self.assertEqual(start.call_count, 2)
        self.assertNotEqual(first.session_id, second.session_id)
        self.assertEqual(
            set(ad_hoc_sessions),
            {first.session_id, second.session_id},
        )
        self.assertEqual(payload["selected_session_id"], second.session_id)
        self.assertEqual(
            [session["session_id"] for session in payload["sessions"]],
            [first.session_id, second.session_id],
        )
        self.assertEqual(
            [session["kind"] for session in payload["sessions"]],
            ["ad-hoc", "ad-hoc"],
        )

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
            catalog_path = (
                service_root
                / ".electroboy"
                / "service"
                / "ad-hoc-sessions.json"
            )
            catalog_path.parent.mkdir(parents=True)
            catalog_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "sessions": [
                            {
                                "provider": "codex",
                                "provider_session_id": provider_session_id,
                                "project_root": str(project_root),
                                "title": "Prototype the import service.",
                            },
                            {
                                "provider": "codex",
                                "provider_session_id": older_session_id,
                                "project_root": str(project_root),
                                "title": "Investigate the parser.",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            controller = state.workflow_controller("software")
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                history = controller.ad_hoc_sessions(context_id)
                with (
                    mock.patch("electroboy.service.AgentSession.start") as start,
                    mock.patch(
                        "electroboy.service.sessions.AgentSession.is_active",
                        return_value=True,
                    ),
                ):
                    session, started = controller.start_ad_hoc_agent(
                        context_id,
                        provider_session_id,
                    )
                    duplicate, duplicate_started = controller.start_ad_hoc_agent(
                        context_id,
                        provider_session_id,
                    )
                    filtered_history = controller.ad_hoc_sessions(context_id)
            catalog = json.loads(
                catalog_path.read_text(encoding="utf-8")
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
        self.assertIs(duplicate, session)
        self.assertFalse(duplicate_started)
        self.assertEqual(start.call_count, 1)
        self.assertEqual(
            [entry["provider_session_id"] for entry in filtered_history["sessions"]],
            [older_session_id],
        )
        self.assertEqual(session.command[-3:-1], ["resume", provider_session_id])
        self.assertIn("Effective rules file:", session.command[-1])
        self.assertIn("wait for the operator", session.command[-1])
        self.assertEqual(
            session.metadata["provider_session_id"],
            provider_session_id,
        )
        self.assertTrue(session.metadata["resumed_session"])
        self.assertEqual(
            catalog["sessions"][0]["provider_session_id"],
            provider_session_id,
        )
        self.assertEqual(catalog["schema_version"], 2)
        self.assertEqual(
            catalog["sessions"][0]["session_path"],
            str(current_session_path.resolve()),
        )
        self.assertEqual(
            catalog["sessions"][0]["title"],
            "Prototype the import service.",
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

    def test_service_session_registry_rejects_cross_workspace_attach(self) -> None:
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
            records = json.loads(
                _service_session_records_path(service_root).read_text(
                    encoding="utf-8",
                )
            )

            with self.assertRaisesRegex(AgentSessionError, "unknown agent session"):
                state.attach_session(second_context, session.session_id)

        self.assertEqual(registry["sessions"][0]["session_id"], session.session_id)
        self.assertFalse(registry["sessions"][0]["attachable"])
        self.assertEqual(
            registry["sessions"][0]["active_project_root"],
            str(project_root.resolve()),
        )
        self.assertEqual(records["sessions"][0]["session_id"], session.session_id)
        self.assertTrue(records["sessions"][0]["selected"])

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
        self.assertFalse(registry["sessions"][0]["attachable"])
        self.assertEqual(
            registry["sessions"][0]["active_project_root"],
            str(project_root),
        )

    def test_tmux_reattach_seeds_capture_without_replaying_screen(self) -> None:
        class FakeThread:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def start(self) -> None:
                return

        session = TmuxAgentSession(
            [sys.executable, "-c", "print('ready')"],
            ROOT,
            session_id="session-restored",
            tmux_name="electroboy-session-restored",
        )

        with (
            mock.patch(
                "electroboy.service.sessions._tmux_has_session",
                return_value=True,
            ),
            mock.patch(
                "electroboy.service.sessions._tmux_capture_pane",
                return_value="existing\nscreen\n",
            ),
            mock.patch("electroboy.service.sessions.threading.Thread", FakeThread),
        ):
            session.attach_existing()

        events = session.events_after(0)
        self.assertEqual(session._last_capture, "existing\nscreen\n")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "system")
        self.assertIn("reattached tmux session", str(events[0]["text"]))

    def test_tmux_capture_delta_suppresses_same_screen_repaints(self) -> None:
        previous = "line 1\nspinner |\nline 3\n"
        current = "line 1\nspinner /\nline 3\n"

        self.assertEqual(_tmux_capture_delta(previous, current), "")

    def test_tmux_capture_delta_keeps_scrolled_suffix(self) -> None:
        previous = "line 1\nline 2\nline 3\n"
        current = "line 2\nline 3\nline 4\n"

        self.assertEqual(_tmux_capture_delta(previous, current), "line 4\n")

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

    def test_agent_session_select_route_switches_selected_session(self) -> None:
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
            with mock.patch("electroboy.service.AgentSession.start"):
                first, _ = state.start_documentation_agent(
                    context_id,
                    target="README.md",
                )
                second, _ = state.start_documentation_agent(
                    context_id,
                    target="docs/api.md",
                )
            self.assertEqual(
                state.session_payload(context_id)["selected_session_id"],
                second.session_id,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = post_json(
                    server,
                    f"/api/sessions/select?context_id={context_id}",
                    {"session_id": first.session_id},
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        payload = json.loads(body)
        self.assertEqual(payload["selected_session_id"], first.session_id)
        self.assertEqual(
            {
                session["session_id"]: session["selected"]
                for session in payload["sessions"]
            },
            {
                first.session_id: True,
                second.session_id: False,
            },
        )

    def test_agent_session_input_routes_can_target_explicit_session(self) -> None:
        class FakeSession:
            def __init__(self, session_id: str) -> None:
                self.session_id = session_id
                self.kind = "documentation"
                self.label = session_id
                self.interactive = True
                self.metadata: dict[str, object] = {}
                self.sent: list[tuple[str, str]] = []
                self.interrupted = False
                self.terminated = False

            def is_active(self) -> bool:
                return not self.terminated

            def send(self, message: str) -> None:
                self.sent.append(("message", message))

            def send_key(self, key: str) -> None:
                self.sent.append(("key", key))

            def send_raw(self, data: str) -> None:
                self.sent.append(("raw", data))

            def interrupt(self) -> None:
                self.interrupted = True

            def terminate(self) -> None:
                self.terminated = True

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
            first = FakeSession("first-session")
            second = FakeSession("second-session")
            with state.lock:
                context = state.contexts[context_id]
                context.selected_session_id = first.session_id
                context.documentation_sessions["first"] = first  # type: ignore[assignment]
                context.documentation_sessions["second"] = second  # type: ignore[assignment]

            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                message_status, _, _ = post_json(
                    server,
                    f"/api/sessions/message?context_id={context_id}",
                    {
                        "session_id": second.session_id,
                        "message": "hello second",
                    },
                )
                key_status, _, _ = post_json(
                    server,
                    f"/api/sessions/key?context_id={context_id}",
                    {"session_id": second.session_id, "key": "enter"},
                )
                raw_status, _, _ = post_json(
                    server,
                    f"/api/sessions/raw?context_id={context_id}",
                    {"session_id": second.session_id, "data": "/"},
                )
                interrupt_status, _, _ = post_json(
                    server,
                    f"/api/sessions/interrupt?context_id={context_id}",
                    {"session_id": second.session_id},
                )
                terminate_status, terminate_body, _ = post_json(
                    server,
                    f"/api/sessions/terminate?context_id={context_id}",
                    {"session_id": second.session_id},
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(message_status, HTTPStatus.OK)
        self.assertEqual(key_status, HTTPStatus.OK)
        self.assertEqual(raw_status, HTTPStatus.OK)
        self.assertEqual(interrupt_status, HTTPStatus.OK)
        self.assertEqual(terminate_status, HTTPStatus.OK)
        terminate_payload = json.loads(terminate_body)
        self.assertEqual(terminate_payload["closed_session_id"], second.session_id)
        self.assertEqual(terminate_payload["selected_session_id"], first.session_id)
        self.assertEqual(first.sent, [])
        self.assertFalse(first.interrupted)
        self.assertEqual(
            second.sent,
            [
                ("message", "hello second"),
                ("key", "enter"),
                ("raw", "/"),
            ],
        )
        self.assertTrue(second.interrupted)
        self.assertTrue(second.terminated)

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

    def test_project_payload_clears_stale_selected_session_id(self) -> None:
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
                state.contexts[context_id].selected_session_id = "missing-session"

            payload = state.project_payload(context_id)

        self.assertIsNone(payload["selected_session_id"])
        self.assertEqual(payload["sessions"], [])

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
                self.label = "requirements agent"

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

            with self.assertRaisesRegex(
                AgentSessionError,
                "deactivation would terminate active agent sessions: requirements agent",
            ):
                state.deactivate_project(context_id)

            self.assertFalse(session.terminated)

            payload = state.deactivate_project(context_id, terminate_agents=True)

        self.assertTrue(session.terminated)
        self.assertEqual(payload["status"], "deactivated")
        self.assertIsNone(payload["active_project_root"])
        self.assertIsNone(state.current_requirements_session(context_id))

    def test_project_deactivation_endpoint_requires_active_agent_confirmation(
        self,
    ) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.terminated = False
                self.label = "requirements agent"

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
            try:
                server = create_server(service_root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")

            context_id = str(server.service_state.create_context()["context_id"])
            server.service_state.open_project(context_id, str(project_root))
            session = FakeSession()
            with server.service_state.lock:
                server.service_state.contexts[
                    context_id
                ].requirements_session = session  # type: ignore[assignment]

            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = post_json(
                    server,
                    f"/api/project/deactivate?context_id={context_id}",
                    {},
                )
                confirmed_status, confirmed_body, confirmed_content_type = post_json(
                    server,
                    f"/api/project/deactivate?context_id={context_id}",
                    {"terminate_agents": True},
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, HTTPStatus.CONFLICT)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        self.assertIn("active agent sessions", json.loads(body)["error"])
        self.assertEqual(confirmed_status, HTTPStatus.OK)
        self.assertEqual(
            confirmed_content_type,
            "application/json; charset=utf-8",
        )
        self.assertEqual(json.loads(confirmed_body)["status"], "deactivated")
        self.assertTrue(session.terminated)

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

    def test_workflow_stage_selection_preserves_non_workflow_agents(self) -> None:
        class FakeSession:
            def __init__(self, kind: str) -> None:
                self.terminated = False
                self.kind = kind
                self.label = f"{kind} agent"
                self.interactive = True
                self.metadata: dict[str, object] = {}

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
            requirements = FakeSession("requirements")
            ad_hoc = FakeSession("ad-hoc")
            documentation = FakeSession("documentation")
            with state.lock:
                context = state.contexts[context_id]
                context.requirements_session = requirements  # type: ignore[assignment]
                context.ad_hoc_session = ad_hoc  # type: ignore[assignment]
                context.documentation_sessions["README.md"] = documentation  # type: ignore[assignment]

            payload = state.select_workflow_stage(context_id, "design")

            with state.lock:
                context = state.contexts[context_id]
                preserved_ad_hoc = context.ad_hoc_session
                preserved_documentation = context.documentation_sessions.get(
                    "README.md"
                )

        self.assertTrue(requirements.terminated)
        self.assertFalse(ad_hoc.terminated)
        self.assertFalse(documentation.terminated)
        self.assertIs(preserved_ad_hoc, ad_hoc)
        self.assertIs(preserved_documentation, documentation)
        self.assertTrue(payload["terminated_agent"])
        self.assertEqual(payload["workflow_stage"], "design")

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
        self.assertIn('<h1 id="requirements">Requirements</h1>', page)
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

    def test_agent_event_stream_is_multiplexed_within_one_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            first = server.service_state.create_context("connection-1")
            second = server.service_state.create_context("connection-2")
            first_session = AgentSession(
                [sys.executable, "-c", "pass"],
                root,
                session_id="first-session",
            )
            second_session = AgentSession(
                [sys.executable, "-c", "pass"],
                root,
                session_id="second-session",
            )
            first_session._append_event({"type": "system", "text": "first"})
            second_session._append_event({"type": "system", "text": "second"})
            with server.service_state.lock:
                first_context = server.service_state._context_locked(
                    str(first["workspace_id"])
                )
                first_context.ad_hoc_session = first_session
                first_context.selected_session_id = first_session.session_id
                second_context = server.service_state._context_locked(
                    str(second["workspace_id"])
                )
                second_context.ad_hoc_session = second_session
                second_context.selected_session_id = second_session.session_id
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection(
                *server.server_address[:2],
                timeout=2,
            )

            try:
                connection.request(
                    "GET",
                    "/api/sessions/events?"
                    + urlencode(
                        {
                            "workspace_id": first["workspace_id"],
                            "connection_id": "connection-1",
                            "lease_token": first["lease_token"],
                        }
                    ),
                )
                response = connection.getresponse()
                payload = read_sse_payloads(response, 1)[0]
            finally:
                connection.close()
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["session_id"], "first-session")
        self.assertEqual(payload["event"]["text"], "first")

    def test_artifact_event_stream_watches_multiple_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs = root / "docs"
            docs.mkdir()
            first_path = docs / "first.md"
            second_path = docs / "second.md"
            first_path.write_text("# First\n", encoding="utf-8")
            second_path.write_text("# Second\n", encoding="utf-8")
            StateStore(root).init_run(run_id="run-1")
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            workspace = server.service_state.create_context("connection-1")
            server.service_state.open_project(
                str(workspace["workspace_id"]),
                str(root),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection(
                *server.server_address[:2],
                timeout=2,
            )
            targets = [
                {"artifact": "document", "path": "docs/first.md"},
                {"artifact": "document", "path": "docs/second.md"},
            ]

            try:
                connection.request(
                    "GET",
                    "/api/artifacts/events?"
                    + urlencode(
                        {
                            "workspace_id": workspace["workspace_id"],
                            "connection_id": "connection-1",
                            "lease_token": workspace["lease_token"],
                            "targets": json.dumps(targets),
                        }
                    ),
                )
                response = connection.getresponse()
                payloads = read_sse_payloads(response, 2)
            finally:
                connection.close()
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(response.status, 200)
        self.assertEqual(
            {payload["path"] for payload in payloads},
            {str(first_path), str(second_path)},
        )

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

    def test_agent_session_uses_resizable_pty_as_controlling_terminal(self) -> None:
        script = (
            "import os\n"
            "import signal\n"
            "descriptor = os.open('/dev/tty', os.O_RDWR)\n"
            "assert os.tcgetpgrp(0) == os.getpgrp()\n"
            "print('initial-size:' + repr(os.get_terminal_size(descriptor)), flush=True)\n"
            "def resized(*_args):\n"
            "    print('resized:' + repr(os.get_terminal_size(descriptor)), flush=True)\n"
            "    raise SystemExit(0)\n"
            "signal.signal(signal.SIGWINCH, resized)\n"
            "print('controlling-terminal-ready', flush=True)\n"
            "signal.pause()\n"
        )
        session = AgentSession(
            [sys.executable, "-c", script],
            ROOT,
            columns=137,
            rows=41,
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
            self.assertIn(
                "initial-size:os.terminal_size(columns=137, lines=41)",
                output,
            )
            self.assertIn("controlling-terminal-ready", output)
            session.resize(149, 47)
            output = wait_for_output(self, session, "resized:")
            self.assertIn("resized:os.terminal_size(columns=149, lines=47)", output)
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

    def test_agent_session_reads_event_tail_without_scanning_history(self) -> None:
        class UnreadableEvent(dict[str, object]):
            def get(self, key: str, default: object = None) -> object:
                raise AssertionError(f"older event was inspected: {key}")

        session = AgentSession([sys.executable, "-c", "pass"], ROOT)
        session._events = [  # pylint: disable=protected-access
            UnreadableEvent(id=1, type="output", text="old-1"),
            UnreadableEvent(id=2, type="output", text="old-2"),
            {"id": 3, "type": "output", "text": "new"},
        ]
        session._next_event_id = 4  # pylint: disable=protected-access

        self.assertEqual(session.events_after(2), [session._events[2]])
        self.assertEqual(
            session.wait_for_events_after(2, timeout=0),
            [session._events[2]],
        )

    def test_limited_session_replay_events_keeps_tail_and_notice(self) -> None:
        events = [
            {"id": index, "type": "output", "text": str(index)}
            for index in range(1, SESSION_EVENT_REPLAY_LIMIT + 6)
        ]

        limited = _limited_session_replay_events(events)

        self.assertEqual(len(limited), SESSION_EVENT_REPLAY_LIMIT + 1)
        self.assertEqual(limited[0]["id"], 5)
        self.assertEqual(limited[0]["type"], "system")
        self.assertIn("Skipped 5 older terminal events", str(limited[0]["text"]))
        self.assertEqual(limited[1]["id"], 6)
        self.assertEqual(limited[-1]["id"], SESSION_EVENT_REPLAY_LIMIT + 5)

    def test_limited_session_replay_events_caps_text_volume(self) -> None:
        char_limit = 25
        events = [
            {"id": index, "type": "output", "text": "x" * 10}
            for index in range(1, 6)
        ]

        limited = _limited_session_replay_events(
            events,
            limit=10,
            char_limit=char_limit,
        )

        self.assertEqual([event["id"] for event in limited], [3, 4, 5])
        self.assertIn("Skipped 3 older terminal events", str(limited[0]["text"]))
        self.assertLessEqual(
            sum(len(str(event.get("text") or "")) for event in limited[1:]),
            char_limit,
        )

    def test_agent_event_cursor_round_trips_session_positions(self) -> None:
        cursor_id = _agent_event_cursor_id(
            {
                "session-b": 12,
                "session-a": "7",  # type: ignore[dict-item]
                "": 9,
                "invalid": "nope",  # type: ignore[dict-item]
            }
        )

        self.assertEqual(cursor_id, '{"session-a":7,"session-b":12}')
        self.assertEqual(
            _parse_agent_event_cursor(cursor_id),
            {"session-a": 7, "session-b": 12},
        )
        self.assertEqual(_parse_agent_event_cursor("not json"), {})

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

    def test_agent_session_resize_ignores_unchanged_dimensions(self) -> None:
        session = AgentSession([sys.executable, "-c", "pass"], ROOT)
        session._master_fd = 123
        session.process = mock.Mock()

        with (
            mock.patch("electroboy.service.sessions._set_terminal_size") as set_size,
            mock.patch("electroboy.service.sessions.os.killpg") as killpg,
        ):
            session.resize(session.columns, session.rows)

        set_size.assert_not_called()
        killpg.assert_not_called()

    def test_tmux_session_can_force_initial_window_dimensions(self) -> None:
        session = TmuxAgentSession([sys.executable, "-c", "pass"], ROOT)

        with (
            mock.patch.object(session, "is_active", return_value=True),
            mock.patch("electroboy.service.sessions._tmux_run") as tmux_run,
        ):
            session._resize_window()

        tmux_run.assert_called_once_with(
            [
                "resize-window",
                "-t",
                session.tmux_name,
                "-x",
                str(session.columns),
                "-y",
                str(session.rows),
            ],
            check=False,
        )

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

    def test_terminal_output_filter_drops_transient_control_frames(self) -> None:
        frame = (
            "\x1b]0;\u2838 better-planned\x07"
            "\x1b[?2026h"
            "\x1b[39m\x1b[49m\x1b[0m"
            "\x1b[0 q"
            "\x1b[?25h"
            "\x1b[35;3H"
            "\x1b[?2026l"
        )

        cleaned, pending = _clean_terminal_output(frame)

        self.assertEqual(cleaned, "")
        self.assertEqual(pending, "")
        self.assertTrue(_terminal_output_is_transient_control(frame))

    def test_terminal_output_filter_keeps_visible_terminal_controls(self) -> None:
        self.assertFalse(_terminal_output_is_transient_control("\x1b[2J"))
        self.assertFalse(_terminal_output_is_transient_control("\x1b[35;3HWorking"))

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


def read_sse_payloads(
    response: http.client.HTTPResponse,
    count: int,
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    while len(payloads) < count:
        line = response.readline().decode("utf-8")
        if not line:
            raise AssertionError("SSE stream ended before the expected events arrived")
        if line.startswith("data: "):
            payloads.append(json.loads(line.removeprefix("data: ")))
    return payloads


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
