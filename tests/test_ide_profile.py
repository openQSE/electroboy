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

            configure_managed_profile(profile)

            settings = json.loads(
                (profile.user_data / "User" / "settings.json").read_text()
            )
            package = json.loads(
                (
                    profile.extensions
                    / "electroboy-theme"
                    / "package.json"
                ).read_text()
            )
            self.assertEqual(settings["workbench.colorTheme"], "ElectroBoy")
            self.assertEqual(package["displayName"], "ElectroBoy Theme")
            self.assertTrue(
                (
                    profile.extensions
                    / "electroboy-theme"
                    / "themes"
                    / "electroboy-color-theme.json"
                ).is_file()
            )


if __name__ == "__main__":
    unittest.main()
