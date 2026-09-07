from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from electroboy.ide import (
    IDEEndpoint,
    IDEError,
    IDEErrorCategory,
    IDEInstance,
    IDEInstanceManager,
    IDEInstanceStatus,
    IDERuntime,
    IDERuntimeMode,
    IDERuntimeOrigin,
    IDEWorkspace,
    OpenVSCodeProvider,
)


class StaticResolver:
    def __init__(self, runtime: IDERuntime) -> None:
        self.runtime = runtime

    def resolve(self, _mode, *, system_executable=None):
        del system_executable
        return self.runtime


class RejectingInstaller:
    def install(self, progress=None):
        del progress
        raise AssertionError("installer should not run")


class FakeLifecycleProvider:
    provider_id = "fake"

    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0

    def start(self, workspace, runtime, profile):
        self.starts += 1
        return IDEInstance(
            instance_id=f"instance-{self.starts}",
            provider=self.provider_id,
            workspace=workspace,
            runtime=runtime,
            profile=profile,
            status=IDEInstanceStatus.STARTING,
            endpoint=IDEEndpoint("unix", f"/tmp/fake-{self.starts}", "secret"),
        )

    def status(self, instance):
        return instance.status

    def wait_until_ready(self, instance, timeout):
        del timeout
        return instance.with_status(IDEInstanceStatus.READY)

    def endpoint(self, instance):
        return instance.endpoint

    def open_location(self, instance, location):
        del instance, location

    def stop(self, instance, reason):
        del reason
        self.stops += 1
        return instance.with_status(IDEInstanceStatus.STOPPED)


def fake_openvscode(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import argparse
import os
import socket
import sys

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--socket-path')
parser.add_argument('--connection-token')
options, rest = parser.parse_known_args()
print('provider token=' + options.connection_token + ' ?secret=value', flush=True)
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(options.socket_path)
server.listen()
while True:
    connection, _ = server.accept()
    connection.recv(4096)
    connection.sendall(b'HTTP/1.1 403 Forbidden\\r\\nContent-Length: 0\\r\\n\\r\\n')
    connection.close()
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


class IDELifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        executable = self.root / "openvscode-server"
        fake_openvscode(executable)
        self.runtime = IDERuntime(
            "openvscode",
            "test",
            "linux",
            "x86_64",
            executable,
            IDERuntimeOrigin.SYSTEM,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def manager(self, provider=None, **options) -> IDEInstanceManager:
        return IDEInstanceManager(
            provider or FakeLifecycleProvider(),
            StaticResolver(self.runtime),
            RejectingInstaller(),
            self.root,
            **options,
        )

    def test_concurrent_starts_reuse_one_workspace_instance(self) -> None:
        provider = FakeLifecycleProvider()
        manager = self.manager(provider)
        workspace = IDEWorkspace("workspace-1", self.root)
        results = []
        threads = [
            threading.Thread(target=lambda: results.append(manager.start(workspace)))
            for _ in range(6)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(provider.starts, 1)
        self.assertEqual(len({row[0].instance_id for row in results}), 1)
        self.assertEqual(sum(1 for _instance, started in results if started), 1)

    def test_project_switch_stops_prior_workspace_instance(self) -> None:
        provider = FakeLifecycleProvider()
        manager = self.manager(provider)
        manager.start(IDEWorkspace("workspace-1", self.root / "first"))

        current, started = manager.start(
            IDEWorkspace("workspace-1", self.root / "second")
        )

        self.assertTrue(started)
        self.assertEqual(provider.starts, 2)
        self.assertEqual(provider.stops, 1)
        self.assertEqual(current.workspace.project_root, self.root / "second")

    def test_instance_limit_and_idle_cleanup(self) -> None:
        manager = self.manager(maximum_instances=1, idle_timeout=10)
        manager.start(IDEWorkspace("workspace-1", self.root / "first"))

        with self.assertRaises(IDEError) as raised:
            manager.start(IDEWorkspace("workspace-2", self.root / "second"))
        self.assertEqual(raised.exception.category, IDEErrorCategory.INSTANCE_LIMIT)

        expired = manager.cleanup_idle(now=time.monotonic() + 20)
        self.assertEqual(expired, ["workspace-1"])
        manager.start(IDEWorkspace("workspace-2", self.root / "second"))

    def test_openvscode_adapter_starts_redacts_and_stops_process(self) -> None:
        provider = OpenVSCodeProvider()
        manager = self.manager(provider, startup_timeout=3)
        instance, started = manager.start(
            IDEWorkspace("workspace-1", self.root),
            mode=IDERuntimeMode.SYSTEM,
        )

        self.assertTrue(started)
        self.assertEqual(instance.status, IDEInstanceStatus.READY)
        self.assertTrue(Path(instance.endpoint.address).exists())
        self.assertTrue(
            (
                instance.profile.extensions
                / "electroboy-bridge"
                / "extension.js"
            ).is_file()
        )
        time.sleep(0.05)
        diagnostics = provider.diagnostics(instance.instance_id)
        self.assertIn("[REDACTED]", diagnostics[0])
        self.assertNotIn(instance.endpoint.connection_token, diagnostics[0])
        process_id = instance.process_id

        manager.stop_all()

        self.assertFalse(Path(instance.endpoint.address).exists())
        assert process_id is not None
        with self.assertRaises(ProcessLookupError):
            os.kill(process_id, 0)

    def test_startup_timeout_cleans_process_and_socket(self) -> None:
        executable = self.root / "never-ready"
        executable.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
        executable.chmod(0o755)
        runtime = self.runtime.__class__(
            **{**self.runtime.__dict__, "executable": executable}
        )
        manager = IDEInstanceManager(
            OpenVSCodeProvider(),
            StaticResolver(runtime),
            RejectingInstaller(),
            self.root,
            startup_timeout=0.15,
        )

        with self.assertRaises(IDEError) as raised:
            manager.start(IDEWorkspace("workspace-1", self.root))

        self.assertEqual(raised.exception.category, IDEErrorCategory.READINESS_TIMEOUT)
        self.assertEqual(manager.registry.values(), ())

    def test_repeated_provider_cycles_do_not_leak_parent_descriptors(self) -> None:
        if not Path("/proc/self/fd").is_dir():
            self.skipTest("file descriptor accounting requires procfs")
        provider = OpenVSCodeProvider()
        manager = self.manager(provider, startup_timeout=3)
        before = len(list(Path("/proc/self/fd").iterdir()))
        for index in range(5):
            workspace_id = f"workspace-{index}"
            manager.start(IDEWorkspace(workspace_id, self.root))
            manager.stop(workspace_id)
        after = len(list(Path("/proc/self/fd").iterdir()))

        self.assertLessEqual(after, before + 2)

    def test_restart_rejects_and_terminates_stale_provider_process(self) -> None:
        first_provider = OpenVSCodeProvider()
        first_manager = self.manager(first_provider, startup_timeout=3)
        first, _started = first_manager.start(
            IDEWorkspace("workspace-1", self.root),
            mode=IDERuntimeMode.SYSTEM,
        )
        assert first.process_id is not None
        first_process = first_provider._processes[first.instance_id].launch.process

        second_provider = OpenVSCodeProvider()
        second_manager = self.manager(second_provider, startup_timeout=3)
        second, restarted = second_manager.start(
            IDEWorkspace("workspace-1", self.root),
            mode=IDERuntimeMode.SYSTEM,
        )

        try:
            self.assertTrue(restarted)
            self.assertNotEqual(first.process_id, second.process_id)
            self.assertIsNotNone(first_process.poll())
        finally:
            second_manager.stop_all()


if __name__ == "__main__":
    unittest.main()
