from __future__ import annotations

import unittest
from importlib.resources import files

from electroboy.modules.ide import module
from electroboy.service.frontend import read_service_text_asset
from electroboy.service.registry import build_module_registry, build_workflow_registry


class IDEPaneAssetTests(unittest.TestCase):
    def test_module_registers_reusable_ide_pane(self) -> None:
        definition = module()
        script = files("electroboy.modules").joinpath("assets", "ide.js").read_text()

        self.assertEqual(definition.assets, ("ide.css", "ide.js"))
        self.assertIn('id: "ide"', script)
        self.assertIn('label: "IDE"', script)
        self.assertIn("panes: [", script)
        self.assertIn("window.ElectroBoyIDEPane = { mount }", script)
        self.assertIn("options.popOut?.()", script)
        self.assertIn("/api/ide/views/attach", script)
        self.assertIn("/api/ide/views/detach", script)

    def test_core_discovers_contributed_panes_and_mounts_ide(self) -> None:
        modules = build_module_registry()
        workflows = build_workflow_registry(modules)
        runtime = read_service_text_asset("js/core/runtime.js", modules, workflows)
        pane_window = read_service_text_asset("pane-window.html", modules, workflows)

        self.assertIn("module.panes", runtime)
        self.assertIn("PANE_LAYOUT_KINDS[kind]", runtime)
        self.assertIn('PANE_KIND === "ide"', pane_window)
        self.assertIn("window.ElectroBoyIDEPane.mount", pane_window)

    def test_pane_has_explicit_lifecycle_and_context_controls(self) -> None:
        script = files("electroboy.modules").joinpath("assets", "ide.js").read_text()
        stylesheet = (
            files("electroboy.modules").joinpath("assets", "ide.css").read_text()
        )

        for state in ("Starting IDE", "IDE ready", "IDE stopped", "IDE failed"):
            self.assertIn(state, script)
        for action in ("IDE configuration", "Diagnostics", "Restart IDE", "Stop IDE"):
            self.assertIn(action, script)
        self.assertIn(".ide-frame", stylesheet)
        self.assertIn(".ide-context-menu", stylesheet)


if __name__ == "__main__":
    unittest.main()
