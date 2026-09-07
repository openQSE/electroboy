from __future__ import annotations

import hashlib
import io
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path

from electroboy.ide import IDEError, IDEErrorCategory
from electroboy.ide.artifacts import RuntimeArtifact, RuntimeArtifactManifest
from electroboy.ide.installer import ManagedRuntimeInstaller
from electroboy.ide.resolver import OpenVSCodeRuntimeResolver


class Response(io.BytesIO):
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def runtime_archive(*, escaping: bool = False) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        name = "../escape" if escaping else "runtime/bin/openvscode-server"
        content = b"#!/bin/sh\nprintf '1.2.3\\n'\n"
        entry = tarfile.TarInfo(name)
        entry.mode = 0o755
        entry.size = len(content)
        bundle.addfile(entry, io.BytesIO(content))
    return output.getvalue()


class IDERuntimeInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def installer(self, content: bytes, open_url=None) -> ManagedRuntimeInstaller:
        artifact = RuntimeArtifact(
            platform="linux",
            architecture="x86_64",
            url="https://example.invalid/runtime.tar.gz",
            sha256=hashlib.sha256(content).hexdigest(),
            size=len(content),
            archive_format="tar.gz",
            archive_root="runtime",
            executable="bin/openvscode-server",
        )
        manifest = RuntimeArtifactManifest(1, "openvscode", "1.2.3", (artifact,))
        resolver = OpenVSCodeRuntimeResolver(
            manifest,
            self.root,
            platform="linux",
            architecture="x86_64",
        )
        return ManagedRuntimeInstaller(
            resolver,
            open_url=open_url or (lambda *_args, **_kwargs: Response(content)),
        )

    def test_installs_verified_archive_and_reports_progress(self) -> None:
        content = runtime_archive()
        events: list[tuple[str, int | None]] = []

        runtime = self.installer(content).install(
            lambda message, percentage: events.append((message, percentage))
        )

        self.assertTrue(runtime.executable.is_file())
        self.assertEqual(events[-1], ("Managed IDE runtime is ready", 100))
        self.assertTrue(
            (runtime.executable.parents[1] / ".electroboy-runtime.json").is_file()
        )

    def test_reuses_verified_installation_without_downloading_again(self) -> None:
        content = runtime_archive()
        calls = 0

        def open_url(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            return Response(content)

        installer = self.installer(content, open_url)
        first = installer.install()
        second = installer.install()

        self.assertEqual(first, second)
        self.assertEqual(calls, 1)

    def test_checksum_mismatch_does_not_publish_installation(self) -> None:
        expected = runtime_archive()
        installer = self.installer(expected, lambda *_a, **_k: Response(b"x"))

        with self.assertRaises(IDEError) as raised:
            installer.install()

        self.assertEqual(
            raised.exception.category,
            IDEErrorCategory.INSTALLATION_FAILED,
        )
        self.assertFalse(installer.resolver.managed_install_root().exists())

    def test_rejects_escaping_archive_entry(self) -> None:
        installer = self.installer(runtime_archive(escaping=True))

        with self.assertRaisesRegex(IDEError, "escapes extraction root"):
            installer.install()

        self.assertFalse(installer.resolver.managed_install_root().exists())

    def test_interrupted_download_is_recoverable_and_not_published(self) -> None:
        content = runtime_archive()

        class Interrupted(Response):
            def read(self, size: int = -1) -> bytes:
                del size
                raise OSError("connection reset")

        installer = self.installer(content, lambda *_a, **_k: Interrupted(content))

        with self.assertRaises(IDEError) as raised:
            installer.install()

        self.assertTrue(raised.exception.recoverable)
        self.assertFalse(installer.resolver.managed_install_root().exists())

    def test_concurrent_installers_download_once(self) -> None:
        content = runtime_archive()
        calls = 0
        calls_lock = threading.Lock()

        def open_url(*_args, **_kwargs):
            nonlocal calls
            with calls_lock:
                calls += 1
            return Response(content)

        installer = self.installer(content, open_url)
        results: list[object] = []
        threads = [
            threading.Thread(target=lambda: results.append(installer.install()))
            for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), 4)
        self.assertEqual(calls, 1)

    def test_cleanup_removes_only_unused_versions(self) -> None:
        installer = self.installer(runtime_archive())
        provider_root = installer.resolver.managed_install_root().parents[1]
        old = provider_root / "0.9.0"
        current = provider_root / "1.2.3"
        old.mkdir(parents=True)
        current.mkdir()

        removed = installer.cleanup_unused_versions()

        self.assertEqual(removed, [old])
        self.assertFalse(old.exists())
        self.assertTrue(current.exists())


if __name__ == "__main__":
    unittest.main()
