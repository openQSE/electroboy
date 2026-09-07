from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode

from electroboy.ide import IDEWorkspace
from electroboy.ide.service import _ide_view_path
from electroboy.service import create_server


class FakeIDEService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.closed = False

    def runtime_status(self):
        self.calls.append(("runtime", None))
        return {"status": "ready", "runtime": {"provider": "fake"}}

    def install(self):
        self.calls.append(("install", None))
        return {"status": "ready"}

    def start(self, workspace_id, project_root):
        self.calls.append(("start", (workspace_id, project_root)))
        return {
            "status": "started",
            "instance": {
                "workspace_id": workspace_id,
                "status": "ready",
                "endpoint": {"authentication": "managed"},
            },
            "view_path": f"/ide/{workspace_id}/",
        }

    def status(self, workspace_id, project_root=None):
        self.calls.append(("status", (workspace_id, project_root)))
        return {"status": "ready", "instance": {"workspace_id": workspace_id}}

    def stop(self, workspace_id, reason="requested"):
        self.calls.append(("stop", (workspace_id, reason)))
        return {"status": "stopped"}

    def open_location(self, workspace_id, location):
        self.calls.append(("open", (workspace_id, location)))
        return {"status": "opened", "location": location.__dict__}

    def diagnostics(self, workspace_id):
        self.calls.append(("diagnostics", workspace_id))
        return {"instance": None, "provider_output": []}

    def record_input_event(self, workspace_id, payload):
        self.calls.append(("record_input_event", (workspace_id, payload)))
        return {"status": "recorded", "event": payload}

    def configuration_status(self, workspace_id):
        self.calls.append(("configuration", workspace_id))
        return {
            "status": "ready",
            "configuration": {"runtime_mode": "auto"},
        }

    def configure(self, workspace_id, values):
        self.calls.append(("configure", (workspace_id, values)))
        return {
            "status": "configured",
            "configuration": values,
            "restart_required": True,
        }

    def network_status(self, workspace_id):
        self.calls.append(("network_status", workspace_id))
        return {
            "mode": "deny",
            "rules": [],
            "temporary_rules": [],
            "events": [],
        }

    def configure_network(
        self,
        workspace_id,
        *,
        mode,
        rules,
        temporary_rules,
        audit_acknowledged,
    ):
        self.calls.append(
            (
                "configure_network",
                (
                    workspace_id,
                    mode,
                    rules,
                    temporary_rules,
                    audit_acknowledged,
                ),
            )
        )
        return {"mode": mode, "restart_required": True}

    def clear_network_events(self, workspace_id):
        self.calls.append(("clear_network_events", workspace_id))
        return {"mode": "deny", "events": []}

    def editor_context(self, workspace_id):
        self.calls.append(("editor_context", workspace_id))
        return {"workspace_id": workspace_id, "path": "src/main.py"}

    def neovim_status(self):
        self.calls.append(("neovim_status", None))
        return {"status": "enabled", "enabled": True}

    def launch_neovim(self, workspace_id):
        self.calls.append(("launch_neovim", workspace_id))
        return {"status": "enabled", "enabled": True, "restart_required": True}

    def configure_neovim(self, *, enabled, executable=""):
        self.calls.append(("configure_neovim", (enabled, executable)))
        return {"status": "enabled" if enabled else "disabled", "enabled": enabled}

    def record_csp_violation(self, payload, workspace_id=""):
        self.calls.append(("csp", (workspace_id, payload)))
        return {"status": "recorded"}

    def attach_view(self, workspace_id, view_id):
        self.calls.append(("attach_view", (workspace_id, view_id)))
        return {"status": "attached", "view_id": view_id, "view_count": 1}

    def detach_view(self, workspace_id, view_id):
        self.calls.append(("detach_view", (workspace_id, view_id)))
        return {"status": "detached", "view_count": 0}

    def close(self):
        self.closed = True


class IDEServiceAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.server = create_server(self.root, port=0, state_root=self.root / "state")
        assert self.server.service_state is not None
        self.state = self.server.service_state
        self.ide = FakeIDEService()
        self.state.ide_service = self.ide
        context = self.state.create_context("tab-1", "software")
        self.workspace_id = str(context["workspace_id"])
        self.lease_token = str(context["lease_token"])
        with self.state.lock:
            active = self.state.context_store.require(self.workspace_id)
            active.reset_project(
                workflow_id="software",
                project_mode="existing",
                activation_root=self.root,
                active_project_root=self.root,
            )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.temporary.cleanup()

    def query(self, *, lease_token: str | None = None) -> str:
        return urlencode(
            {
                "workspace_id": self.workspace_id,
                "connection_id": "tab-1",
                "lease_token": lease_token or self.lease_token,
            }
        )

    def request(self, method: str, path: str, payload=None):
        host, port = self.server.server_address[:2]
        connection = http.client.HTTPConnection(host, port, timeout=3)
        try:
            connection.request(
                method,
                f"{path}?{self.query()}",
                body=json.dumps(payload).encode() if payload is not None else None,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_runtime_start_status_stop_and_diagnostics_routes(self) -> None:
        runtime = self.request("GET", "/api/ide/runtime")
        started = self.request("POST", "/api/ide/start", {})
        status = self.request("GET", "/api/ide/status")
        diagnostics = self.request("GET", "/api/ide/diagnostics")
        stopped = self.request("POST", "/api/ide/stop", {"reason": "test"})

        self.assertEqual([row[0] for row in self.ide.calls], [
            "runtime",
            "start",
            "status",
            "diagnostics",
            "stop",
        ])
        self.assertTrue(all(result[0] == 200 for result in (
            runtime,
            started,
            status,
            diagnostics,
            stopped,
        )))
        self.assertNotIn("token", json.dumps(started[1]))

    def test_ide_view_path_opens_the_active_project_folder(self) -> None:
        workspace = IDEWorkspace(
            "workspace-1",
            Path("/tmp/project with spaces"),
        )

        self.assertEqual(
            _ide_view_path(workspace),
            "/ide/workspace-1/?folder=%2Ftmp%2Fproject+with+spaces",
        )

    def test_start_consumes_body_before_next_keep_alive_request(self) -> None:
        host, port = self.server.server_address[:2]
        connection = http.client.HTTPConnection(host, port, timeout=3)
        headers = {"Content-Type": "application/json"}
        try:
            connection.request(
                "POST",
                f"/api/ide/start?{self.query()}",
                body=b"{}",
                headers=headers,
            )
            started = connection.getresponse()
            started.read()
            connection.request(
                "POST",
                f"/api/ide/views/attach?{self.query()}",
                body=b'{"view_id":"pane-1"}',
                headers=headers,
            )
            attached = connection.getresponse()
            payload = json.loads(attached.read())
        finally:
            connection.close()

        self.assertEqual(started.status, 200)
        self.assertEqual(attached.status, 200)
        self.assertEqual(payload["status"], "attached")

    def test_open_location_is_provider_neutral(self) -> None:
        status, payload = self.request(
            "POST",
            "/api/ide/open",
            {"path": "src/main.py", "line": 12, "end_line": 14},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["location"]["path"], "src/main.py")
        location = self.ide.calls[-1][1][1]
        self.assertEqual(location.line, 12)

    def test_view_routes_share_workspace_instance_capacity(self) -> None:
        attached = self.request(
            "POST",
            "/api/ide/views/attach",
            {"view_id": "pane-1"},
        )
        detached = self.request(
            "POST",
            "/api/ide/views/detach",
            {"view_id": "pane-1"},
        )

        self.assertEqual(attached[1]["view_count"], 1)
        self.assertEqual(detached[1]["view_count"], 0)

    def test_editor_context_route_returns_provider_neutral_context(self) -> None:
        response = self.request("GET", "/api/ide/context")

        self.assertEqual(response[0], 200)
        self.assertEqual(response[1]["editor_context"]["path"], "src/main.py")

    def test_neovim_status_and_configuration_routes(self) -> None:
        status = self.request("GET", "/api/ide/neovim")
        launched = self.request("POST", "/api/ide/neovim/launch", {})
        configured = self.request(
            "POST",
            "/api/ide/neovim/configure",
            {"enabled": False, "executable": "/usr/bin/nvim"},
        )

        self.assertEqual(status[1]["status"], "enabled")
        self.assertTrue(launched[1]["restart_required"])
        self.assertEqual(configured[1]["status"], "disabled")
        self.assertEqual(
            self.ide.calls[-1],
            ("configure_neovim", (False, "/usr/bin/nvim")),
        )

    def test_ide_configuration_routes(self) -> None:
        status = self.request("GET", "/api/ide/configuration")
        configured = self.request(
            "POST",
            "/api/ide/configure",
            {
                "runtime_mode": "managed",
                "system_executable": "",
                "maximum_instances": 3,
                "maximum_views_per_instance": 2,
                "idle_timeout": 1200,
                "startup_timeout": 45,
            },
        )

        self.assertEqual(status[1]["configuration"]["runtime_mode"], "auto")
        self.assertEqual(configured[1]["status"], "configured")
        self.assertEqual(
            [call[0] for call in self.ide.calls[-2:]],
            ["configuration", "configure"],
        )

    def test_input_event_route_records_sanitized_diagnostics(self) -> None:
        status, payload = self.request(
            "POST",
            "/api/ide/input-events",
            {"event_type": "keydown", "key_group": "navigation"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "recorded")
        self.assertEqual(self.ide.calls[-1][0], "record_input_event")

    def test_network_policy_configuration_and_clear_routes(self) -> None:
        status = self.request("GET", "/api/ide/network")
        configured = self.request(
            "POST",
            "/api/ide/network/configure",
            {
                "mode": "allowlist",
                "rules": [
                    {
                        "destination": "example.com",
                        "ports": [443],
                        "protocols": ["tcp"],
                    }
                ],
                "temporary_rules": [],
            },
        )
        cleared = self.request("POST", "/api/ide/network/events/clear", {})

        self.assertEqual(status[1]["mode"], "deny")
        self.assertEqual(configured[1]["mode"], "allowlist")
        self.assertTrue(configured[1]["restart_required"])
        self.assertEqual(cleared[1]["events"], [])
        self.assertEqual(
            [call[0] for call in self.ide.calls[-3:]],
            ["network_status", "configure_network", "clear_network_events"],
        )

    def test_routes_reject_wrong_workspace_lease(self) -> None:
        host, port = self.server.server_address[:2]
        connection = http.client.HTTPConnection(host, port, timeout=3)
        try:
            connection.request(
                "POST",
                f"/api/ide/start?{self.query(lease_token='wrong')}",
                body=b"{}",
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            response.read()
        finally:
            connection.close()

        self.assertEqual(response.status, 409)
        self.assertFalse(any(name == "start" for name, _value in self.ide.calls))

    def test_deactivation_and_server_close_stop_owned_ide(self) -> None:
        self.state.deactivate_project(self.workspace_id)
        self.server.server_close()

        self.assertIn(
            ("stop", (self.workspace_id, "project deactivated")),
            self.ide.calls,
        )
        self.assertTrue(self.ide.closed)


if __name__ == "__main__":
    unittest.main()
