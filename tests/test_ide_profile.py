from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from electroboy.ide import IDEProfile
from electroboy.ide.profile import configure_managed_profile


class IDEProfileTests(unittest.TestCase):
    def test_profile_installs_and_selects_local_electroboy_theme(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = IDEProfile(
                root=root,
                user_data=root / "user-data",
                extensions=root / "extensions",
                server_data=root / "server-data",
                logs=root / "logs",
            )

            configure_managed_profile(
                profile,
                {"electroboy.bridge.directory": "/tmp/bridge"},
            )

            settings = json.loads(
                (profile.user_data / "User" / "settings.json").read_text()
            )
            machine_settings = json.loads(
                (profile.user_data / "Machine" / "settings.json").read_text()
            )
            package = json.loads(
                (
                    profile.extensions
                    / "electroboy-theme"
                    / "package.json"
                ).read_text()
            )
            self.assertEqual(settings["workbench.colorTheme"], "ElectroBoy")
            self.assertFalse(settings["editor.editContext"])
            self.assertEqual(settings["keyboard.dispatch"], "keyCode")
            self.assertEqual(
                machine_settings["workbench.colorTheme"],
                "ElectroBoy",
            )
            self.assertFalse(machine_settings["editor.editContext"])
            self.assertEqual(machine_settings["keyboard.dispatch"], "keyCode")
            self.assertEqual(settings["electroboy.bridge.directory"], "/tmp/bridge")
            self.assertEqual(
                machine_settings["electroboy.bridge.directory"],
                "/tmp/bridge",
            )
            self.assertEqual(package["displayName"], "ElectroBoy Theme")
            self.assertEqual(package["version"], "1.1.0")
            registry = json.loads(
                (profile.extensions / "extensions.json").read_text()
            )
            registered = {
                entry["identifier"]["id"]: entry for entry in registry
            }
            self.assertEqual(
                registered["electroboy.electroboy-theme"]["version"],
                "1.1.0",
            )
            self.assertEqual(
                registered["electroboy.electroboy-bridge"]["version"],
                "1.5.1",
            )
            self.assertTrue(
                (
                    profile.extensions
                    / "electroboy-theme"
                    / "themes"
                    / "electroboy-color-theme.json"
                ).is_file()
            )
            theme = json.loads(
                (
                    profile.extensions
                    / "electroboy-theme"
                    / "themes"
                    / "electroboy-color-theme.json"
                ).read_text()
            )
            self.assertEqual(theme["colors"]["editor.background"], "#10141F")
            self.assertEqual(theme["colors"]["focusBorder"], "#66D9E8")
            self.assertEqual(
                theme["colors"]["quickInputList.focusBackground"],
                "#1F6F8B",
            )

    def test_profile_removes_retired_managed_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = IDEProfile(
                root=root,
                user_data=root / "user-data",
                extensions=root / "extensions",
                server_data=root / "server-data",
                logs=root / "logs",
            )
            settings_path = profile.user_data / "User" / "settings.json"
            settings_path.parent.mkdir(parents=True)
            settings_path.write_text(
                json.dumps({"retired.setting": True, "user.setting": "kept"})
            )

            configure_managed_profile(
                profile,
                removed_settings=("retired.setting",),
            )

            settings = json.loads(settings_path.read_text())
            self.assertNotIn("retired.setting", settings)
            self.assertEqual(settings["user.setting"], "kept")


if __name__ == "__main__":
    unittest.main()
