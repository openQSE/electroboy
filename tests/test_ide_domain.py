from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electroboy.ide import (
    IDEEditorContext,
    IDEEndpoint,
    IDEError,
    IDEErrorCategory,
    IDEInstance,
    IDEInstanceRegistry,
    IDEInstanceStatus,
    IDELocation,
    IDEProfile,
    IDEProvider,
    IDERuntime,
    IDERuntimeOrigin,
    IDEWorkspace,
)


class FakeIDEProvider:
    provider_id = "fake"

    def __init__(self) -> None:
        self.locations: list[IDELocation] = []

    def start(
        self,
        workspace: IDEWorkspace,
        runtime: IDERuntime,
        profile: IDEProfile,
    ) -> IDEInstance:
        return IDEInstance(
            instance_id=f"fake:{workspace.workspace_id}",
            provider=self.provider_id,
            workspace=workspace,
            runtime=runtime,
            profile=profile,
            status=IDEInstanceStatus.READY,
            endpoint=IDEEndpoint("unix", "/tmp/fake.sock", "secret"),
        )

    def status(self, instance: IDEInstance) -> IDEInstanceStatus:
        return instance.status

    def endpoint(self, instance: IDEInstance) -> IDEEndpoint:
        assert instance.endpoint is not None
        return instance.endpoint

    def open_location(
        self,
        instance: IDEInstance,
        location: IDELocation,
    ) -> None:
        if instance.status is not IDEInstanceStatus.READY:
            raise IDEError(IDEErrorCategory.NOT_READY, "instance is not ready")
        self.locations.append(location)

    def stop(self, instance: IDEInstance, reason: str) -> IDEInstance:
        del reason
        return instance.with_status(IDEInstanceStatus.STOPPED)


class IDEDomainTests(unittest.TestCase):
    def make_values(self, root: Path, workspace_id: str = "workspace-1") -> tuple:
        runtime = IDERuntime(
            provider="fake",
            version="1.2.3",
            platform="linux",
            architecture="x86_64",
            executable=root / "fake-ide",
            origin=IDERuntimeOrigin.MANAGED,
        )
        workspace = IDEWorkspace(workspace_id, root / "project")
        profile = IDEProfile(
            root=root / "profile",
            user_data=root / "profile/user",
            extensions=root / "profile/extensions",
            server_data=root / "profile/server",
            logs=root / "profile/logs",
        )
        return runtime, workspace, profile

    def test_fake_provider_satisfies_contract_and_keeps_secret_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime, workspace, profile = self.make_values(Path(tmp))
            provider: IDEProvider = FakeIDEProvider()
            instance = provider.start(workspace, runtime, profile)
            provider.open_location(instance, IDELocation("src/main.py", line=7))

        self.assertEqual(provider.status(instance), IDEInstanceStatus.READY)
        self.assertEqual(provider.locations[0].path, "src/main.py")
        self.assertNotIn("secret", repr(instance))
        self.assertNotIn("secret", str(instance.public_payload()))

    def test_registry_enforces_one_instance_per_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime, workspace, profile = self.make_values(Path(tmp))
            provider = FakeIDEProvider()
            first = provider.start(workspace, runtime, profile)
            second = IDEInstance(
                **{**first.__dict__, "instance_id": "fake:other"},
            )
            registry = IDEInstanceRegistry()
            registry.claim(first)

            with self.assertRaises(IDEError) as raised:
                registry.claim(second)

        self.assertEqual(
            raised.exception.category,
            IDEErrorCategory.WORKSPACE_CONFLICT,
        )
        self.assertIs(registry.get(workspace.workspace_id), first)

    def test_editor_context_has_provider_neutral_payload(self) -> None:
        context = IDEEditorContext(
            workspace_id="workspace-1",
            path="src/main.py",
            language="python",
            cursor_line=8,
            cursor_column=3,
            selection_start_line=8,
            selection_start_column=3,
            selection_end_line=10,
            selection_end_column=4,
            dirty=True,
            revision=2,
        )

        self.assertEqual(context.payload()["cursor"], {"line": 8, "column": 3})
        self.assertTrue(context.payload()["dirty"])

    def test_location_rejects_nonpositive_positions(self) -> None:
        with self.assertRaisesRegex(ValueError, "line must be positive"):
            IDELocation("src/main.py", line=0)


if __name__ == "__main__":
    unittest.main()
