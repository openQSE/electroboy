from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from electroboy.ide import (
    IDEInstanceManager,
    IDERuntime,
    IDERuntimeMode,
    IDERuntimeOrigin,
    IDEWorkspace,
    OpenVSCodeProvider,
)
from tests.test_ide_lifecycle import RejectingInstaller, StaticResolver


@unittest.skipUnless(
    os.environ.get("ELECTROBOY_OPENVSCODE_EXECUTABLE"),
    "set ELECTROBOY_OPENVSCODE_EXECUTABLE for OpenVSCode integration coverage",
)
class IDEBridgeOpenVSCodeTests(unittest.TestCase):
    def test_real_runtime_starts_with_registered_bridge_extension(self) -> None:
        executable = Path(os.environ["ELECTROBOY_OPENVSCODE_EXECUTABLE"]).resolve()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = IDERuntime(
                "openvscode",
                "integration",
                "linux",
                "x86_64",
                executable,
                IDERuntimeOrigin.SYSTEM,
            )
            provider = OpenVSCodeProvider()
            manager = IDEInstanceManager(
                provider,
                StaticResolver(runtime),
                RejectingInstaller(),
                root,
                startup_timeout=20,
            )
            repository = root / "repository"
            repository.mkdir()
            try:
                instance, started = manager.start(
                    IDEWorkspace("bridge-integration", repository),
                    mode=IDERuntimeMode.SYSTEM,
                )
                self.assertTrue(started)
                self.assertTrue(
                    (
                        instance.profile.extensions
                        / "electroboy-bridge"
                        / "extension.js"
                    ).is_file()
                )
                self.assertTrue(
                    (instance.profile.root / "bridge" / "registration.json").is_file()
                )
            finally:
                manager.stop_all()


if __name__ == "__main__":
    unittest.main()
