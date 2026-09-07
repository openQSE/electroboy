#!/usr/bin/env python3
"""Build the bundled ElectroBoy bridge extension as a reproducible VSIX."""

from __future__ import annotations

import argparse
import json
import zipfile
from html import escape
from pathlib import Path

SOURCE_DATE = (2020, 1, 1, 0, 0, 0)
CONTENT_TYPES = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="json" ContentType="application/json" />
  <Default Extension="js" ContentType="application/javascript" />
  <Default Extension="vsixmanifest" ContentType="text/xml" />
</Types>
"""


def build(source: Path, destination: Path) -> None:
    package = json.loads((source / "package.json").read_text(encoding="utf-8"))
    manifest = _manifest(package)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        _write(archive, "[Content_Types].xml", CONTENT_TYPES.encode())
        _write(archive, "extension.vsixmanifest", manifest.encode())
        for path in sorted(source.rglob("*")):
            if path.is_file():
                _write(
                    archive,
                    f"extension/{path.relative_to(source).as_posix()}",
                    path.read_bytes(),
                )


def _manifest(package: dict[str, object]) -> str:
    publisher = escape(str(package["publisher"]))
    name = escape(str(package["name"]))
    version = escape(str(package["version"]))
    display_name = escape(str(package["displayName"]))
    description = escape(str(package["description"]))
    return f"""<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id="{name}" Version="{version}"
              Publisher="{publisher}" />
    <DisplayName>{display_name}</DisplayName>
    <Description xml:space="preserve">{description}</Description>
    <Categories>Other</Categories>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code" />
  </Installation>
  <Dependencies />
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest"
           Path="extension/package.json" Addressable="true" />
  </Assets>
</PackageManifest>
"""


def _write(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, SOURCE_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def main() -> int:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--source",
        type=Path,
        default=root
        / "src/electroboy/ide/extensions/electroboy-bridge",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "dist/electroboy-bridge-1.0.0.vsix",
    )
    options = parser.parse_args()
    build(options.source.resolve(), options.output.resolve())
    print(options.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
