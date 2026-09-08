from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electroboy.ide.domain import IDERuntime, IDERuntimeOrigin
from electroboy.ide.keybinding_telemetry import (
    COMMAND_EVENT,
    RESOLUTION_EVENT,
    instrument_keybinding_resolver,
)


class IDEKeybindingTelemetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.executable = self.root / "bin/openvscode-server"
        self.executable.parent.mkdir()
        self.executable.write_text("#!/bin/sh\n", encoding="utf-8")
        self.bundle = self.root / "out/vs/code/browser/workbench/workbench.js"
        self.bundle.parent.mkdir(parents=True)
        self.html = self.bundle.with_name("workbench.html")
        self.html.write_text(
            '<script type="module" '
            'src="{{WORKBENCH_WEB_BASE_URL}}/out/vs/code/browser/workbench/'
            'workbench.js"></script>\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def runtime(self, origin: IDERuntimeOrigin) -> IDERuntime:
        return IDERuntime(
            "openvscode",
            "1.109.5",
            "linux",
            "x86_64",
            self.executable,
            origin,
        )

    def test_instruments_managed_resolver_once(self) -> None:
        self.bundle.write_text(
            "const r=this.s.getContext(e),a=s.getLabel(),"
            "l=this.z().resolve(r,o,n);switch(l.kind){};"
            'typeof l.commandArgs>"u"?this.t.executeCommand(l.commandId)'
            ".then(void 0,c=>this.w.warn(c)):this.t.executeCommand("
            "l.commandId,l.commandArgs).then(void 0,c=>this.w.warn(c))",
            encoding="utf-8",
        )
        runtime = self.runtime(IDERuntimeOrigin.MANAGED)

        self.assertTrue(instrument_keybinding_resolver(runtime))
        first = self.bundle.read_text(encoding="utf-8")
        self.assertTrue(instrument_keybinding_resolver(runtime))

        self.assertEqual(self.bundle.read_text(encoding="utf-8"), first)
        self.assertIn(RESOLUTION_EVENT, first)
        self.assertIn(COMMAND_EVENT, first)
        self.assertIn("resolved_command", first)
        self.assertIn("command_args", first)
        self.assertIn('neovim_init:$ebValue("neovim.init")', first)
        self.assertIn(
            "workbench.js?electroboy-keybinding-telemetry=3",
            self.html.read_text(encoding="utf-8"),
        )
        self.assertTrue(
            self.root.joinpath(".electroboy-keybinding-telemetry.json").is_file()
        )

    def test_rejects_unknown_managed_resolver_bundle(self) -> None:
        self.bundle.write_text("unknown bundle", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "resolver anchor"):
            instrument_keybinding_resolver(self.runtime(IDERuntimeOrigin.MANAGED))

    def test_does_not_modify_system_runtime(self) -> None:
        self.bundle.write_text("system bundle", encoding="utf-8")

        self.assertFalse(
            instrument_keybinding_resolver(self.runtime(IDERuntimeOrigin.SYSTEM))
        )
        self.assertEqual(self.bundle.read_text(encoding="utf-8"), "system bundle")
