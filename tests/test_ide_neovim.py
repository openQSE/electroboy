from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from electroboy.ide import IDEProfile
from electroboy.ide.artifacts import RuntimeArtifact, RuntimeArtifactManifest
from electroboy.ide.downloads import AuditedDownloadClient
from electroboy.ide.neovim import NeovimProfileManager


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
                    "name": "vscode-neovim",
                    "publisher": "asvetliakov",
                    "version": "1.19.0",
                }
            ),
        )
        archive.writestr("extension/dist/extension.js", "module.exports = {};\n")
    return output.getvalue()


def fake_nvim(path: Path, version: str) -> None:
    path.write_text(f"#!/bin/sh\nprintf 'NVIM v{version}\\n'\n", encoding="utf-8")
    path.chmod(0o755)


def neovim_archive(version: str = "0.10.4") -> bytes:
    output = io.BytesIO()
    content = f"#!/bin/sh\nprintf 'NVIM v{version}\\n'\n".encode()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        entry = tarfile.TarInfo("nvim-test/bin/nvim")
        entry.mode = 0o755
        entry.size = len(content)
        bundle.addfile(entry, io.BytesIO(content))
    return output.getvalue()


class IDENeovimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.archive = extension_archive()
        self.downloads = AuditedDownloadClient(
            open_url=lambda *_args, **_kwargs: Response(self.archive)
        )
        self.manager = NeovimProfileManager(self.root, self.downloads)
        self.manager.artifact = replace(
            self.manager.artifact,
            url="https://example.invalid/vscode-neovim.vsix",
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

    def test_compatible_neovim_installs_verified_default_profile(self) -> None:
        executable = self.root / "nvim"
        fake_nvim(executable, "0.10.4")
        self.manager.configure(enabled=True, executable=str(executable))

        status = self.manager.prepare(self.profile)

        self.assertEqual(status["status"], "enabled")
        self.assertTrue(status["installed"])
        extension = self.profile.extensions / self.manager.extension_directory_name
        self.assertTrue((extension / "package.json").is_file())
        self.assertTrue(
            (self.profile.extensions / "electroboy-bridge" / "extension.js").is_file()
        )
        settings = json.loads(
            (self.profile.user_data / "User/settings.json").read_text()
        )
        self.assertEqual(
            settings["vscode-neovim.neovimExecutablePaths.linux"],
            str(executable),
        )
        self.assertTrue(settings["vscode-neovim.neovimClean"])
        self.assertEqual(self.downloads.events()[-1]["status"], "verified")

    def test_missing_old_and_disabled_states_do_not_block_profile(self) -> None:
        missing = self.manager.status()
        old = self.root / "old-nvim"
        fake_nvim(old, "0.9.5")
        self.manager.configure(enabled=True, executable=str(old))
        incompatible = self.manager.prepare(self.profile)
        disabled = self.manager.configure(enabled=False)

        self.assertEqual(missing["status"], "unavailable")
        self.assertEqual(incompatible["status"], "incompatible")
        self.assertEqual(disabled["status"], "disabled")
        self.assertEqual(self.downloads.events(), [])

    def test_configuration_does_not_touch_user_neovim_files(self) -> None:
        user_config = self.root / "home/.config/nvim/init.lua"
        user_config.parent.mkdir(parents=True)
        user_config.write_text("-- user config\n")

        self.manager.configure(enabled=False, executable="/custom/nvim")

        self.assertEqual(user_config.read_text(), "-- user config\n")
        stored = json.loads(self.manager.config_path.read_text())
        self.assertEqual(stored["executable"], "/custom/nvim")

    def test_prepare_installs_managed_neovim_when_system_runtime_is_missing(
        self,
    ) -> None:
        runtime = neovim_archive()
        runtime_artifact = RuntimeArtifact(
            platform="linux",
            architecture="x86_64",
            url="https://example.invalid/neovim.tar.gz",
            sha256=hashlib.sha256(runtime).hexdigest(),
            size=len(runtime),
            archive_format="tar.gz",
            archive_root="nvim-test",
            executable="bin/nvim",
        )
        manifest = RuntimeArtifactManifest(
            1,
            "neovim",
            "0.10.4",
            (runtime_artifact,),
        )

        def open_url(request, **_kwargs):
            return Response(
                runtime
                if str(request.full_url).endswith("neovim.tar.gz")
                else self.archive
            )

        downloads = AuditedDownloadClient(open_url=open_url)
        manager = NeovimProfileManager(
            self.root,
            downloads,
            architecture="x86_64",
            runtime_manifest=manifest,
        )
        manager.artifact = replace(
            manager.artifact,
            url="https://example.invalid/vscode-neovim.vsix",
            size=len(self.archive),
            sha256=hashlib.sha256(self.archive).hexdigest(),
        )

        status = manager.prepare(self.profile)

        self.assertEqual(status["status"], "enabled")
        self.assertEqual(status["origin"], "managed")
        self.assertTrue(status["installed"])
        self.assertEqual(
            [event["status"] for event in downloads.events()],
            ["verified", "verified"],
        )

    def test_managed_neovim_failure_keeps_profile_available(self) -> None:
        runtime = neovim_archive()
        artifact = RuntimeArtifact(
            platform="linux",
            architecture="x86_64",
            url="https://example.invalid/neovim.tar.gz",
            sha256=hashlib.sha256(runtime).hexdigest(),
            size=len(runtime),
            archive_format="tar.gz",
            archive_root="nvim-test",
            executable="bin/nvim",
        )
        manager = NeovimProfileManager(
            self.root,
            AuditedDownloadClient(open_url=lambda *_args, **_kwargs: Response(b"bad")),
            architecture="x86_64",
            runtime_manifest=RuntimeArtifactManifest(
                1,
                "neovim",
                "0.10.4",
                (artifact,),
            ),
        )

        status = manager.prepare(self.profile)

        self.assertEqual(status["status"], "unavailable")
        self.assertIn("managed Neovim installation failed", status["reason"])
        self.assertFalse(status["installed"])


@unittest.skipUnless(
    os.environ.get("ELECTROBOY_NETWORK_INTEGRATION") == "1",
    "set ELECTROBOY_NETWORK_INTEGRATION=1 for Open VSX coverage",
)
class IDENeovimNetworkTests(unittest.TestCase):
    def test_pinned_open_vsx_artifact_downloads_and_installs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "nvim"
            fake_nvim(executable, "0.10.4")
            manager = NeovimProfileManager(root, AuditedDownloadClient())
            manager.configure(enabled=True, executable=str(executable))
            profile = IDEProfile(
                root=root / "profile",
                user_data=root / "profile/user-data",
                extensions=root / "profile/extensions",
                server_data=root / "profile/server-data",
                logs=root / "profile/logs",
            )

            status = manager.prepare(profile)

            self.assertEqual(status["status"], "enabled")
            self.assertTrue(
                (
                    profile.extensions
                    / manager.extension_directory_name
                    / "package.json"
                ).is_file()
            )


if __name__ == "__main__":
    unittest.main()
