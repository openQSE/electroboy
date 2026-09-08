from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from electroboy.ide.service import IDEConfiguration, IDEService


class IDEConfigurationTests(unittest.TestCase):
    def test_gui_configuration_updates_manager_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary)
            environment = {"ELECTROBOY_IDE_DATA_ROOT": str(data_root)}
            with mock.patch.dict("os.environ", environment, clear=True):
                service = IDEService(IDEConfiguration.from_environment())
                result = service.configure(
                    "workspace-1",
                    {
                        "runtime_mode": "managed",
                        "system_executable": "/opt/openvscode-server",
                        "maximum_instances": 4,
                        "maximum_views_per_instance": 3,
                        "idle_timeout": 0,
                        "startup_timeout": 45,
                    },
                )
                restored = IDEConfiguration.from_environment()
                service.close()

            persisted = json.loads(
                (data_root / "ide" / "configuration.json").read_text()
            )
            self.assertEqual(result["status"], "configured")
            self.assertEqual(result["configuration"]["runtime_mode"], "managed")
            self.assertEqual(service.manager.maximum_instances, 4)
            self.assertEqual(service.manager.idle_timeout, 0)
            self.assertEqual(service.manager.startup_timeout, 45)
            self.assertEqual(persisted["maximum_views_per_instance"], 3)
            self.assertEqual(restored.runtime_mode.value, "managed")
            self.assertEqual(restored.idle_timeout, 0)

    def test_gui_configuration_rejects_out_of_range_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = IDEService(IDEConfiguration(data_root=Path(temporary)))

            with self.assertRaisesRegex(ValueError, "maximum_instances"):
                service.configure(
                    "workspace-1",
                    {
                        "runtime_mode": "auto",
                        "maximum_instances": 0,
                        "maximum_views_per_instance": 2,
                        "idle_timeout": 900,
                        "startup_timeout": 30,
                    },
                )

            service.close()


if __name__ == "__main__":
    unittest.main()
