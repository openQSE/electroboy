from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.service.routes import RouteRequest  # noqa: E402
from electroboy.service.services import ServiceServices  # noqa: E402
from electroboy.service.workflow_controller import (  # noqa: E402
    BoundWorkflowController,
)


class ServiceInterfaceTests(unittest.TestCase):
    def test_bound_controller_exposes_only_typed_services(self) -> None:
        dependency = object()
        services = ServiceServices(
            contexts=dependency,
            workspaces=dependency,
            sessions=dependency,
            files=dependency,
            workflows=dependency,
        )

        controller = BoundWorkflowController(services)

        self.assertIs(controller.services, services)
        self.assertNotIn("__getattr__", BoundWorkflowController.__dict__)

    def test_route_request_uses_public_transport_protocol(self) -> None:
        source = inspect.getsource(RouteRequest)

        self.assertNotIn("transport._", source)
        self.assertNotIn("Any", source)
        self.assertNotIn("def operation(", source)
        self.assertNotIn("state:", source)
        self.assertIn("services: ServiceServices", source)

    def test_plugin_routes_do_not_access_central_service_state(self) -> None:
        plugin_roots = (
            ROOT / "src" / "electroboy" / "modules",
            ROOT / "src" / "electroboy" / "workflows",
        )
        for plugin_root in plugin_roots:
            for path in plugin_root.rglob("*.py"):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("request.state", source, str(path))
                self.assertNotIn("getattr(request.state", source, str(path))

    def test_public_plugin_api_exports_service_contracts(self) -> None:
        from electroboy.service import plugin_api

        self.assertIs(plugin_api.RouteRequest, RouteRequest)
        self.assertIs(plugin_api.ServiceServices, ServiceServices)
        self.assertIn("ContextServices", plugin_api.__all__)
        self.assertIn("WorkspaceServices", plugin_api.__all__)
        self.assertIn("CorkboardProvider", plugin_api.__all__)
        self.assertIn("CorkboardWorkflowController", plugin_api.__all__)
        self.assertIn("SessionServices", plugin_api.__all__)
        self.assertIn("WorkflowServices", plugin_api.__all__)


if __name__ == "__main__":
    unittest.main()
