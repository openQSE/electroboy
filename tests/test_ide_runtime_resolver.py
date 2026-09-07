from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from electroboy.ide import IDEError, IDEErrorCategory, IDERuntimeMode
from electroboy.ide.artifacts import load_runtime_manifest
from electroboy.ide.resolver import OpenVSCodeRuntimeResolver


class IDERuntimeResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.manifest = load_runtime_manifest()
        self.resolver = OpenVSCodeRuntimeResolver(
            self.manifest,
            self.root,
            platform="linux",
            architecture="x86_64",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_disabled_mode_returns_no_runtime(self) -> None:
        self.assertIsNone(self.resolver.resolve(IDERuntimeMode.DISABLED))
        self.assertEqual(self.resolver.diagnostics()["status"], "disabled")

    def test_missing_managed_runtime_is_recoverable(self) -> None:
        with self.assertRaises(IDEError) as raised:
            self.resolver.resolve(IDERuntimeMode.MANAGED)

        self.assertEqual(raised.exception.category, IDEErrorCategory.RUNTIME_MISSING)
        self.assertTrue(raised.exception.recoverable)
        self.assertEqual(self.resolver.diagnostics()["status"], "error")

    def test_managed_runtime_resolves_from_pinned_install_path(self) -> None:
        executable = (
            self.resolver.managed_install_root() / "bin/openvscode-server"
        )
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)

        runtime = self.resolver.resolve(IDERuntimeMode.MANAGED)

        assert runtime is not None
        self.assertEqual(runtime.version, "1.109.5")
        self.assertEqual(runtime.executable, executable)

    def test_system_runtime_reports_queried_version(self) -> None:
        executable = self.root / "openvscode-server"
        executable.write_text("#!/bin/sh\nprintf '9.8.7\\ncommit\\nx64\\n'\n")
        executable.chmod(0o755)

        runtime = self.resolver.resolve(
            IDERuntimeMode.SYSTEM,
            system_executable=executable,
        )

        assert runtime is not None
        self.assertEqual(runtime.version, "9.8.7")
        self.assertEqual(self.resolver.diagnostics()["status"], "ready")

    def test_unsupported_platform_is_reported(self) -> None:
        resolver = OpenVSCodeRuntimeResolver(
            self.manifest,
            self.root,
            platform="windows",
            architecture="x86_64",
        )

        with self.assertRaises(IDEError) as raised:
            resolver.resolve(IDERuntimeMode.MANAGED)

        self.assertEqual(raised.exception.category, IDEErrorCategory.UNSUPPORTED)

    def test_invalid_system_version_is_incompatible(self) -> None:
        executable = self.root / "not-openvscode"
        executable.write_text("#!/bin/sh\nprintf 'unknown\\n'\n")
        executable.chmod(0o755)

        with self.assertRaises(IDEError) as raised:
            self.resolver.resolve(
                IDERuntimeMode.SYSTEM,
                system_executable=executable,
            )

        self.assertEqual(
            raised.exception.category,
            IDEErrorCategory.RUNTIME_INCOMPATIBLE,
        )

    def test_manifest_schema_rejects_invalid_digest(self) -> None:
        payload = json.loads(
            Path(self.manifest_path()).read_text(encoding="utf-8")
        )
        payload["artifacts"][0]["sha256"] = "bad"
        path = self.root / "bad-manifest.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaises(IDEError) as raised:
            load_runtime_manifest(path)

        self.assertEqual(
            raised.exception.category,
            IDEErrorCategory.RUNTIME_INCOMPATIBLE,
        )

    @staticmethod
    def manifest_path() -> Path:
        return Path(__file__).parents[1] / "src/electroboy/ide/runtime-artifacts.json"


if __name__ == "__main__":
    unittest.main()
