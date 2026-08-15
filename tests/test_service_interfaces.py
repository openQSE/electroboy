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


if __name__ == "__main__":
    unittest.main()
