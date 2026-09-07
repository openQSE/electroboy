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
            self.assertEqual(
                machine_settings["workbench.colorTheme"],
                "ElectroBoy",
            )
            self.assertEqual(settings["electroboy.bridge.directory"], "/tmp/bridge")
            self.assertEqual(
                machine_settings["electroboy.bridge.directory"],
                "/tmp/bridge",
            )
            self.assertEqual(package["displayName"], "ElectroBoy Theme")
            self.assertEqual(package["version"], "1.1.0")
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


if __name__ == "__main__":
    unittest.main()
