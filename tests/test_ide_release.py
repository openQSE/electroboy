from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from electroboy.ide.artifacts import load_runtime_manifest

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_manifest_covers_published_linux_architectures() -> None:
    manifest = load_runtime_manifest()

    assert {
        (artifact.platform, artifact.architecture)
        for artifact in manifest.artifacts
    } == {
        ("linux", "x86_64"),
        ("linux", "arm64"),
        ("linux", "armhf"),
    }
    assert all(artifact.url.endswith(".tar.gz") for artifact in manifest.artifacts)
    assert all(
        artifact.executable == "bin/openvscode-server"
        for artifact in manifest.artifacts
    )


def test_ide_package_contains_runtime_metadata_extensions_and_notices() -> None:
    package = files("electroboy.ide")

    assert package.joinpath("runtime-artifacts.json").is_file()
    assert package.joinpath("extension-artifacts.json").is_file()
    assert package.joinpath("THIRD_PARTY-NOTICES.md").is_file()
    assert package.joinpath(
        "extensions/electroboy-bridge/extension.js"
    ).is_file()
    assert package.joinpath(
        "extensions/electroboy-theme/themes/electroboy-color-theme.json"
    ).is_file()


def test_ide_uses_downloaded_binaries_without_source_submodules() -> None:
    assert not (ROOT / ".gitmodules").exists()
    assert not any(
        "openvscode" in path.name.lower() or path.name.lower() == "vscode"
        for path in ROOT.iterdir()
        if path.is_dir()
    )
