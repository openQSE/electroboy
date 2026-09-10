from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest import mock

from electroboy.ide import IDEProfile
from electroboy.ide.clangd import ClangdProfileManager
from electroboy.ide.downloads import AuditedDownloadClient


class Response(io.BytesIO):
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def extension_archive() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "extension/package.json",
            json.dumps(
                {
                    "name": "vscode-clangd",
                    "publisher": "llvm-vs-code-extensions",
                    "version": "0.6.0",
                }
            ),
        )
        archive.writestr("extension/extension.js", "module.exports = {};\n")
    return output.getvalue()


def fake_clangd(path: Path, version: str = "18.1.3") -> None:
    path.write_text(
        f"#!/bin/sh\nprintf 'clangd version {version}\\n'\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


class IDEClangdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.archive = extension_archive()
        self.downloads = AuditedDownloadClient(
            open_url=lambda *_args, **_kwargs: Response(self.archive)
        )
        self.manager = ClangdProfileManager(self.root, self.downloads)
        self.manager.artifact = replace(
            self.manager.artifact,
            url="https://example.invalid/vscode-clangd.vsix",
            size=len(self.archive),
            sha256=hashlib.sha256(self.archive).hexdigest(),
        )
        self.profile = IDEProfile(
            root=self.root / "profile",
            user_data=self.root / "profile/user-data",
            extensions=self.root / "profile/extensions",
            server_data=self.root / "profile/server-data",
            logs=self.root / "profile/logs",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_installs_clangd_extension_and_configures_language_server(self) -> None:
        executable = self.root / "clangd"
        fake_clangd(executable)

        with mock.patch(
            "electroboy.ide.clangd.shutil.which",
            return_value=str(executable),
        ):
            status = self.manager.prepare(self.profile)

        self.assertEqual(status["status"], "enabled")
        self.assertTrue(status["installed"])
        self.assertEqual(status["origin"], "system")
        self.assertEqual(status["executable"], str(executable))
        self.assertEqual(status["version"], "18.1.3")
        extension = self.profile.extensions / self.manager.extension_directory_name
        self.assertTrue((extension / "package.json").is_file())
        registry = json.loads(
            (self.profile.extensions / "extensions.json").read_text()
        )
        self.assertIn(
            "llvm-vs-code-extensions.vscode-clangd",
            {entry["identifier"]["id"] for entry in registry},
        )
        settings = json.loads(
            (self.profile.user_data / "User/settings.json").read_text()
        )
        self.assertEqual(settings["clangd.path"], str(executable))
        self.assertEqual(settings["clangd.arguments"], ["--background-index"])
        self.assertFalse(settings["clangd.checkUpdates"])

    def test_missing_clangd_keeps_ide_profile_available(self) -> None:
        with mock.patch(
            "electroboy.ide.clangd.shutil.which",
            return_value=None,
        ):
            status = self.manager.prepare(self.profile)

        self.assertEqual(status["status"], "unavailable")
        self.assertTrue(status["installed"])
        self.assertIn("clangd executable was not found", status["reason"])
        settings = json.loads(
            (self.profile.user_data / "User/settings.json").read_text()
        )
        self.assertEqual(settings["clangd.path"], "clangd")

    def test_failed_extension_install_reports_unavailable(self) -> None:
        bad_downloads = AuditedDownloadClient(
            open_url=lambda *_args, **_kwargs: Response(b"bad")
        )
        manager = ClangdProfileManager(self.root, bad_downloads)
        manager.artifact = replace(
            manager.artifact,
            url="https://example.invalid/vscode-clangd.vsix",
            size=3,
            sha256=hashlib.sha256(b"bad").hexdigest(),
        )

        status = manager.prepare(self.profile)

        self.assertEqual(status["status"], "unavailable")
        self.assertFalse(status["installed"])
        self.assertIn("extension installation failed", status["reason"])


if __name__ == "__main__":
    unittest.main()
