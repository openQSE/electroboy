from __future__ import annotations

import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from electroboy.service import ServiceState, create_server
from electroboy.service.http import JsonResponse
from electroboy.service.registry import RouteDefinition
from electroboy.service.routes import RouteDispatcher, RouteOperations, RouteRequest
from electroboy.service.sessions import AgentSessionError
from electroboy.service.workspaces import WorkspaceRegistry
from electroboy.state_store import StateStore


class WorkspaceIsolationTests(unittest.TestCase):
    @staticmethod
    def _request(
        server: object,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object]]:
        host, port = server.server_address[:2]
        connection = http.client.HTTPConnection(host, port, timeout=2)
        try:
            connection.request(
                method,
                path,
                body=(json.dumps(payload).encode("utf-8") if payload else None),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body
        finally:
            connection.close()

    def test_route_can_opt_out_of_workspace_lease_validation(self) -> None:
        class RejectingWorkspaces:
            def validate(self, *_args: object) -> None:
                raise ValueError("workspace lease should not be validated")

        class CapturingTransport:
            response: object | None = None

            def read_json_body(self) -> dict[str, object]:
                return {}

            def stream_session_events(self, _session: object) -> None:
                raise AssertionError("unexpected stream")

            def stream_agent_events(self, _context_id: str) -> None:
                raise AssertionError("unexpected stream")

            def stream_artifact_events(self, _targets: object) -> None:
                raise AssertionError("unexpected stream")

            def stream_progress_events(self, *_args: object) -> None:
                raise AssertionError("unexpected stream")

            def emit_response(self, response: object) -> None:
                self.response = response

        dispatcher = RouteDispatcher()
        dispatcher.register(
            RouteDefinition(
                "POST",
                "/api/workflow/recover",
                "workflow",
                "recover",
                requires_workspace_lease=False,
            ),
            lambda _request: JsonResponse({"status": "recovered"}),
        )
        transport = CapturingTransport()
        request = RouteRequest(
            method="POST",
            path="/api/workflow/recover",
            query="workspace_id=workspace-1&connection_id=tab-a&lease_token=stale",
            services=mock.Mock(workspaces=RejectingWorkspaces()),
            config=mock.Mock(root=Path("."), state_root=Path(".")),
            transport=transport,
            operations=RouteOperations(
                service_index_factory=lambda: "",
                health_payload_factory=lambda: {},
                frontend_asset_payload_factory=lambda: [],
                file_browser_factory=lambda _path, _mode: "",
            ),
        )

        self.assertTrue(dispatcher.dispatch(request))
        self.assertIsInstance(transport.response, JsonResponse)
        assert isinstance(transport.response, JsonResponse)
        self.assertEqual(transport.response.payload, {"status": "recovered"})

    def test_workspace_routes_enforce_leases_and_switch_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = create_server(Path(tmp), port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                first_status, first = self._request(
                    server,
                    "POST",
                    "/api/contexts",
                    {"connection_id": "tab-a", "workflow_id": "software"},
                )
                workspace_id = str(first["workspace_id"])
                first_token = str(first["lease_token"])
                query = (
                    f"workspace_id={workspace_id}&connection_id=tab-a"
                    "&lease_token=wrong"
                )
                rejected_status, _rejected = self._request(
                    server,
                    "GET",
                    f"/api/project?{query}",
                )

                second_status, second = self._request(
                    server,
                    "POST",
                    "/api/contexts",
                    {"connection_id": "tab-b", "workflow_id": "software"},
                )
                second_id = str(second["workspace_id"])
                second_token = str(second["lease_token"])
                second_query = (
                    f"workspace_id={second_id}&connection_id=tab-b"
                    f"&lease_token={second_token}"
                )
                conflict_status, _conflict = self._request(
                    server,
                    "POST",
                    f"/api/workspaces/attach?{second_query}",
                    {
                        "workspace_id": workspace_id,
                        "connection_id": "tab-b",
                        "lease_token": second_token,
                    },
                )
                first_query = (
                    f"workspace_id={workspace_id}&connection_id=tab-a"
                    f"&lease_token={first_token}"
                )
                detached_status, _detached = self._request(
                    server,
                    "POST",
                    f"/api/workspaces/detach?{first_query}",
                    {"connection_id": "tab-a", "lease_token": first_token},
                )
                attached_status, attached = self._request(
                    server,
                    "POST",
                    f"/api/workspaces/attach?{second_query}",
                    {
                        "workspace_id": workspace_id,
                        "connection_id": "tab-b",
                        "lease_token": second_token,
                    },
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertEqual(rejected_status, 409)
        self.assertEqual(conflict_status, 409)
        self.assertEqual(detached_status, 200)
        self.assertEqual(attached_status, 200)
        self.assertEqual(attached["workspace_id"], workspace_id)

    def test_clear_route_removes_only_detached_workspaces_for_workflow(self) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.active = True

            def is_active(self) -> bool:
                return self.active

            def terminate(self) -> None:
                self.active = False

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = create_server(root, port=0)
            state = server.service_state
            self.assertIsNotNone(state)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                software = state.create_context("tab-a", "software")
                software_id = str(software["workspace_id"])
                state.workspace_registry.adopt_context(
                    state.context_store.require(software_id),
                    name="Software workspace",
                    project_identity=str(root / "software"),
                )
                session = FakeSession()
                state.context_store.require(software_id).ad_hoc_session = session
                state.workspace_registry.detach(
                    software_id,
                    "tab-a",
                    str(software["lease_token"]),
                )

                creative = state.create_context("tab-b", "creative-writing")
                creative_id = str(creative["workspace_id"])
                state.workspace_registry.adopt_context(
                    state.context_store.require(creative_id),
                    name="Creative workspace",
                    project_identity=str(root / "creative"),
                )
                state.workspace_registry.detach(
                    creative_id,
                    "tab-b",
                    str(creative["lease_token"]),
                )

                status, payload = self._request(
                    server,
                    "POST",
                    "/api/workspaces/clear?workflow_id=software",
                )
                software_status, software_payload = self._request(
                    server,
                    "GET",
                    "/api/workspaces?workflow_id=software",
                )
                creative_status, creative_payload = self._request(
                    server,
                    "GET",
                    "/api/workspaces?workflow_id=creative-writing",
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

            restored = ServiceState(root)

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "cleared")
        self.assertEqual(payload["cleared_workspace_count"], 1)
        self.assertEqual(payload["terminated_session_count"], 1)
        self.assertFalse(session.active)
        self.assertEqual(software_status, 200)
        self.assertEqual(software_payload["workspaces"], [])
        self.assertEqual(creative_status, 200)
        self.assertEqual(
            [row["workspace_id"] for row in creative_payload["workspaces"]],
            [creative_id],
        )
        self.assertNotIn(software_id, restored.workspace_registry.records)
        self.assertIn(creative_id, restored.workspace_registry.records)

    def test_clear_route_removes_only_selected_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = create_server(root, port=0)
            state = server.service_state
            self.assertIsNotNone(state)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                selected = state.create_context("tab-a", "software")
                selected_id = str(selected["workspace_id"])
                state.workspace_registry.adopt_context(
                    state.context_store.require(selected_id),
                    name="Selected workspace",
                    project_identity=str(root / "selected"),
                )
                state.workspace_registry.detach(
                    selected_id,
                    "tab-a",
                    str(selected["lease_token"]),
                )

                retained = state.create_context("tab-b", "software")
                retained_id = str(retained["workspace_id"])
                state.workspace_registry.adopt_context(
                    state.context_store.require(retained_id),
                    name="Retained workspace",
                    project_identity=str(root / "retained"),
                )
                state.workspace_registry.detach(
                    retained_id,
                    "tab-b",
                    str(retained["lease_token"]),
                )

                other_workflow = state.create_context("tab-c", "creative-writing")
                other_workflow_id = str(other_workflow["workspace_id"])
                state.workspace_registry.adopt_context(
                    state.context_store.require(other_workflow_id),
                    name="Other workflow workspace",
                    project_identity=str(root / "other-workflow"),
                )
                state.workspace_registry.detach(
                    other_workflow_id,
                    "tab-c",
                    str(other_workflow["lease_token"]),
                )

                invalid_status, invalid_payload = self._request(
                    server,
                    "POST",
                    "/api/workspaces/clear?workflow_id=software",
                    {"workspace_ids": selected_id},
                )
                status, payload = self._request(
                    server,
                    "POST",
                    "/api/workspaces/clear?workflow_id=software",
                    {"workspace_ids": [selected_id, other_workflow_id]},
                )
                software_status, software_payload = self._request(
                    server,
                    "GET",
                    "/api/workspaces?workflow_id=software",
                )
                creative_status, creative_payload = self._request(
                    server,
                    "GET",
                    "/api/workspaces?workflow_id=creative-writing",
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(invalid_status, 400)
        self.assertIn("workspace_ids", str(invalid_payload["error"]))
        self.assertEqual(status, 200)
        self.assertEqual(payload["cleared_workspace_count"], 1)
        self.assertEqual(software_status, 200)
        self.assertEqual(
            [row["workspace_id"] for row in software_payload["workspaces"]],
            [retained_id],
        )
        self.assertEqual(creative_status, 200)
        self.assertEqual(
            [row["workspace_id"] for row in creative_payload["workspaces"]],
            [other_workflow_id],
        )

    def test_detached_project_resumes_original_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service_root = root / "service"
            project_root = root / "QFw"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            first = state.create_context("tab-a", "software")
            opened = state.open_project(
                str(first["workspace_id"]),
                str(project_root),
            )
            workspace_id = str(opened["workspace_id"])
            state.workspace_registry.detach(
                workspace_id,
                "tab-a",
                str(first["lease_token"]),
            )

            second = state.create_context("tab-b", "software")
            resumed = state.open_project(
                str(second["workspace_id"]),
                str(project_root),
            )

        self.assertEqual(resumed["status"], "resumed")
        self.assertEqual(resumed["workspace_id"], workspace_id)
        self.assertEqual(resumed["active_project_root"], str(project_root.resolve()))

    def test_workspace_payload_requires_workflow_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service_root = root / "service"
            project_root = root / "QFw"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            first = state.create_context("tab-a", "software")
            opened = state.open_project(
                str(first["workspace_id"]),
                str(project_root),
            )
            workspace_id = str(opened["workspace_id"])
            state.workspace_registry.detach(
                workspace_id,
                "tab-a",
                str(first["lease_token"]),
            )

            unfiltered = state.workspace_payload()
            filtered = state.workspace_payload(workflow_id="software")

        self.assertEqual(unfiltered["workspaces"], [])
        self.assertEqual(
            [workspace["workspace_id"] for workspace in filtered["workspaces"]],
            [workspace_id],
        )

    def test_attached_project_rejects_second_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service_root = root / "service"
            project_root = root / "QFw"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            first = state.create_context("tab-a", "software")
            state.open_project(str(first["workspace_id"]), str(project_root))
            second = state.create_context("tab-b", "software")

            with self.assertRaisesRegex(ValueError, "already in use"):
                state.open_project(
                    str(second["workspace_id"]),
                    str(project_root),
                )

    def test_workspace_persists_namespaced_state_across_service_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service_root = root / "service"
            project_root = root / "QFw"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            created = state.create_context("tab-a", "software")
            workspace_id = str(created["workspace_id"])
            state.open_project(workspace_id, str(project_root))
            context = state.context_store.require(workspace_id)
            context.workflow("software")["custom_marker"] = "preserved"
            state.workspace_registry.save_client_state(
                workspace_id,
                {
                    "open_documents": [
                        {"label": "README", "path": "README.md"}
                    ]
                },
            )
            state.workspace_registry.detach(
                workspace_id,
                "tab-a",
                str(created["lease_token"]),
            )

            restored = ServiceState(service_root)
            payload = restored.project_payload(workspace_id)

        restored_context = restored.context_store.require(workspace_id)
        self.assertEqual(
            restored_context.workflow("software")["custom_marker"],
            "preserved",
        )
        self.assertEqual(
            payload["workspace_client_state"]["open_documents"][0]["path"],
            "README.md",
        )

    def test_exclusive_lease_expires_and_allows_new_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = ServiceState(Path(tmp))
            state.workspace_registry.lease_seconds = 0.01
            created = state.create_context("tab-a", "software")
            workspace_id = str(created["workspace_id"])
            first_token = str(created["lease_token"])
            time.sleep(0.02)

            attached = state.workspace_registry.attach(workspace_id, "tab-b")

            with self.assertRaisesRegex(ValueError, "not attached"):
                state.workspace_registry.heartbeat(
                    workspace_id,
                    "tab-a",
                    first_token,
                )

        self.assertTrue(attached["lease_token"])
        self.assertEqual(attached["connection_count"], 1)

    def test_expired_lease_recovers_with_matching_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = ServiceState(Path(tmp))
            state.workspace_registry.lease_seconds = 0.01
            created = state.create_context("tab-a", "software")
            workspace_id = str(created["workspace_id"])
            lease_token = str(created["lease_token"])
            time.sleep(0.02)

            state.workspace_registry.list_detached(workflow_id="software")
            record = state.workspace_registry.require_record(workspace_id)
            self.assertNotIn("tab-a", record.connections)
            self.assertIn("tab-a", record.expired_connections)

            state.workspace_registry.validate(
                workspace_id,
                "tab-a",
                lease_token,
            )
            renewed = state.workspace_registry.heartbeat(
                workspace_id,
                "tab-a",
                lease_token,
            )

        self.assertTrue(renewed["attached"])
        self.assertEqual(renewed["connection_count"], 1)
        self.assertIn("tab-a", record.connections)
        self.assertNotIn("tab-a", record.expired_connections)

    def test_shared_singleton_accepts_multiple_connections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = ServiceState(Path(tmp))
            first = state.create_context("tab-a", "software")
            workspace, token_a, created = (
                state.workspace_registry.resolve_shared_singleton(
                    str(first["workspace_id"]),
                    workflow_id="better-planned-family",
                    owner_key="actor-1",
                    name="Better Planned",
                    connection_id="tab-a",
                )
            )
            second = state.create_context("tab-b", "software")
            same_workspace, token_b, created_again = (
                state.workspace_registry.resolve_shared_singleton(
                    str(second["workspace_id"]),
                    workflow_id="better-planned-family",
                    owner_key="actor-1",
                    name="Better Planned",
                    connection_id="tab-b",
                )
            )
            metadata = state.workspace_registry.metadata(workspace.context_id)

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(same_workspace.context_id, workspace.context_id)
        self.assertNotEqual(token_a, token_b)
        self.assertEqual(metadata["connection_count"], 2)

        first_state = state.workspace_registry.connection_state(
            workspace.context_id,
            "tab-a",
            "better-planned",
        )
        second_state = state.workspace_registry.connection_state(
            workspace.context_id,
            "tab-b",
            "better-planned",
        )
        first_state["selected_account"] = "family-a"
        second_state["selected_account"] = "family-b"
        self.assertEqual(first_state["selected_account"], "family-a")
        self.assertEqual(second_state["selected_account"], "family-b")

        with self.assertRaisesRegex(ValueError, "workflow authentication"):
            state.workspace_registry.switch(
                workspace.context_id,
                workspace.context_id,
                "tab-a",
                token_a,
            )

    def test_agent_process_cannot_attach_to_another_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_root = root / "QFw"
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")
            state = ServiceState(root)
            first = state.create_context()
            second = state.create_context()
            state.open_project(str(first["workspace_id"]), str(project_root))
            controller = state.workflow_controller("software")
            with mock.patch("electroboy.service.AgentSession.start"):
                session, _started = controller.start_ad_hoc_agent(
                    str(first["workspace_id"])
                )

            with self.assertRaises(AgentSessionError):
                state.attach_session(
                    str(second["workspace_id"]),
                    session.session_id,
                )

    def test_process_without_workspace_identity_is_not_restored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = root / ".electroboy" / "service" / "sessions.json"
            records.parent.mkdir(parents=True)
            records.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "sessions": [
                            {
                                "backend": "tmux",
                                "session_id": "orphan",
                                "tmux_session": "electroboy-orphan",
                                "command": ["codex"],
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
                mock.patch(
                    "electroboy.service.app._tmux_has_session",
                    return_value=True,
                ),
                mock.patch(
                    "electroboy.service.TmuxAgentSession.attach_existing"
                ) as attach_existing,
            ):
                state = ServiceState(root, session_backend="tmux")

        attach_existing.assert_not_called()
        self.assertEqual(state.context_store.contexts, {})


if __name__ == "__main__":
    unittest.main()
