from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from electroboy.ide import (
    BRIDGE_PROTOCOL_VERSION,
    IDEBridge,
    IDEEndpoint,
    IDEInstance,
    IDEInstanceStatus,
    IDELocation,
    IDEProfile,
    IDERuntime,
    IDERuntimeOrigin,
    IDEWorkspace,
)
from tools.build_ide_bridge_vsix import build


class IDEBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.profile = IDEProfile(
            root=self.root / "profile",
            user_data=self.root / "profile/user-data",
            extensions=self.root / "profile/extensions",
            server_data=self.root / "profile/server-data",
            logs=self.root / "profile/logs",
        )
        self.workspace = IDEWorkspace("workspace-1", self.root / "project")
        self.workspace.project_root.mkdir()
        self.bridge = IDEBridge(response_timeout=1)
        self.registration = self.bridge.prepare(
            self.profile,
            self.workspace,
            "instance-1",
        )
        self.instance = IDEInstance(
            instance_id="instance-1",
            provider="openvscode",
            workspace=self.workspace,
            runtime=IDERuntime(
                "openvscode",
                "test",
                "linux",
                "x86_64",
                Path("/tmp/openvscode"),
                IDERuntimeOrigin.SYSTEM,
            ),
            profile=self.profile,
            status=IDEInstanceStatus.READY,
            endpoint=IDEEndpoint("unix", "/tmp/ide.sock", "provider-token"),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_prepare_writes_private_versioned_registration(self) -> None:
        path = self.registration.directory / "registration.json"
        payload = json.loads(path.read_text())

        self.assertEqual(payload["protocol_version"], BRIDGE_PROTOCOL_VERSION)
        self.assertEqual(payload["workspace_id"], "workspace-1")
        self.assertEqual(payload["instance_id"], "instance-1")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        input_events = self.registration.directory / "input-events.jsonl"
        self.assertTrue(input_events.is_file())
        self.assertEqual(input_events.stat().st_mode & 0o777, 0o600)

    def test_context_requires_current_authenticated_registration(self) -> None:
        payload = self.envelope(
            {
                "path": "src/main.py",
                "language": "python",
                "cursor": {"line": 4, "column": 8},
                "selection": {
                    "start": {"line": 4, "column": 2},
                    "end": {"line": 4, "column": 8},
                },
                "dirty": True,
                "revision": 7,
            }
        )
        context_path = self.registration.directory / "context.json"
        context_path.write_text(json.dumps(payload))

        context = self.bridge.context(self.instance)

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.path, "src/main.py")
        self.assertEqual(context.cursor_line, 4)
        self.assertTrue(context.dirty)
        payload["auth"] = "wrong"
        context_path.write_text(json.dumps(payload))
        self.assertIsNone(self.bridge.context(self.instance))

    def test_navigation_uses_request_id_and_authenticated_response(self) -> None:
        request_id = self.bridge.open_location(
            self.instance,
            IDELocation("src/main.py", line=4, end_line=6, symbol="main"),
        )

        command = json.loads(
            (self.registration.directory / "commands.jsonl")
            .read_text()
            .splitlines()[-1]
        )
        self.assertEqual(command["command"], "open_location")
        self.assertEqual(command["location"]["symbol"], "main")
        self.assertEqual(command["request_id"], request_id)
        self.assertEqual(command["auth"], self.registration.secret)
        diagnostics = self.bridge.diagnostics(self.instance)
        self.assertEqual(diagnostics["pending_command_count"], 1)

    def test_input_diagnostics_are_sanitized_and_exposed(self) -> None:
        event = self.bridge.record_input_event(
            self.instance,
            {
                "event_type": "keydown",
                "sequence": 8,
                "occurred_at": "2026-09-07T16:00:00.000Z",
                "editor_mode": "neovim",
                "key_group": "printable",
                "named_key": "x",
                "physical_code": "KeyX",
                "key_code": 88,
                "vim_motion": False,
                "frame_has_focus": True,
                "target_kind": "textarea",
                "modifiers": {"control": True},
                "source_text": "must not be retained",
            },
        )

        diagnostics = self.bridge.diagnostics(self.instance)

        self.assertEqual(event["source"], "browser")
        self.assertIsNone(event["named_key"])
        self.assertEqual(event["physical_code"], "KeyX")
        self.assertEqual(event["key_code"], 88)
        self.assertEqual(event["modifiers"]["control"], True)
        self.assertNotIn("source_text", event)
        self.assertNotIn("auth", event)
        self.assertEqual(diagnostics["input_event_count"], 1)
        self.assertEqual(diagnostics["recent_input_events"], [event])

    def test_keybinding_resolution_context_is_sanitized(self) -> None:
        event = self.bridge.record_input_event(
            self.instance,
            {
                "event_type": "keybinding-resolution",
                "sequence": 9,
                "key_label": "UpArrow",
                "dispatch_chord": "up",
                "resolution_kind": 2,
                "resolved_command": "vscode-neovim.send",
                "command_argument": "<up>",
                "context": {
                    "editor_text_focus": True,
                    "neovim_init": True,
                    "neovim_mode": "normal",
                    "editor_language": "c",
                    "neovim_recording": False,
                    "editor_language_exclusions": ["output", "search-result"],
                    "unrequested": "discard me",
                },
            },
        )

        self.assertEqual(event["event_type"], "keybinding-resolution")
        self.assertEqual(event["resolved_command"], "vscode-neovim.send")
        self.assertEqual(event["command_argument"], "<up>")
        self.assertEqual(event["resolution_kind"], 2)
        self.assertEqual(event["context"]["neovim_mode"], "normal")
        self.assertNotIn("unrequested", event["context"])

    def test_keybinding_command_outcome_is_sanitized(self) -> None:
        event = self.bridge.record_input_event(
            self.instance,
            {
                "event_type": "keybinding-command",
                "sequence": 10,
                "resolved_command": "vscode-neovim.send",
                "command_argument": "<down>",
                "command_status": "rejected",
                "command_error": "command failed",
            },
        )

        self.assertEqual(event["event_type"], "keybinding-command")
        self.assertEqual(event["command_status"], "rejected")
        self.assertEqual(event["command_error"], "command failed")

    def test_vsix_build_is_reproducible_and_contains_extension(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "src/electroboy/ide/extensions/electroboy-bridge"
        )
        first = self.root / "first.vsix"
        second = self.root / "second.vsix"

        build(source, first)
        build(source, second)

        self.assertEqual(
            hashlib.sha256(first.read_bytes()).digest(),
            hashlib.sha256(second.read_bytes()).digest(),
        )
        with zipfile.ZipFile(first) as archive:
            self.assertIn("extension/package.json", archive.namelist())
            self.assertIn("extension/extension.js", archive.namelist())
            self.assertIn("extension.vsixmanifest", archive.namelist())

    def test_extension_applies_managed_theme_through_vscode_api(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "src/electroboy/ide/extensions/electroboy-bridge/extension.js"
        ).read_text()

        self.assertIn("async function activate(context)", source)
        self.assertIn("await applyManagedWorkbenchSettings()", source)
        self.assertIn('workbench.get("colorTheme")', source)
        self.assertIn("vscode.ConfigurationTarget.Global", source)

    def test_extension_records_editor_effects_without_document_text(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "src/electroboy/ide/extensions/electroboy-bridge/extension.js"
        ).read_text()

        self.assertIn("onDidChangeTextEditorSelection(selectionChanged)", source)
        self.assertIn('recordInputEffect("selection-change"', source)
        self.assertIn('recordInputEffect("document-change"', source)
        self.assertIn("event.contentChanges.length", source)
        self.assertIn(
            'executeCommand("workbench.action.focusActiveEditorGroup")', source
        )
        self.assertIn('executeCommand("_getNeovimClient")', source)
        self.assertIn('recordInputEffect("neovim-state"', source)
        self.assertNotIn("contentChange.text", source)

    def test_extension_does_not_compete_with_neovim_keybindings(self) -> None:
        extension_root = (
            Path(__file__).resolve().parents[1]
            / "src/electroboy/ide/extensions/electroboy-bridge"
        )
        package = json.loads(extension_root.joinpath("package.json").read_text())
        self.assertNotIn("keybindings", package["contributes"])
        source = extension_root.joinpath("extension.js").read_text()
        self.assertNotIn("electroboy.neovim.sendKey", source)

    def envelope(self, payload: dict[str, object]) -> dict[str, object]:
        return {
            "protocol_version": BRIDGE_PROTOCOL_VERSION,
            "workspace_id": self.registration.workspace_id,
            "instance_id": self.registration.instance_id,
            "auth": self.registration.secret,
            **payload,
        }


if __name__ == "__main__":
    unittest.main()
