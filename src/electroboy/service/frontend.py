"""Frontend asset manifest and resource loading for the browser service."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources


SERVICE_ASSET_PACKAGE = "electroboy"
SERVICE_ASSET_DIRECTORY = ("assets", "service")


@dataclass(frozen=True)
class FrontendBundle:
    """A browser asset bundle provided by core, a module, or a workflow."""

    id: str
    label: str
    owner: str
    assets: tuple[str, ...]

    def payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "owner": self.owner,
            "assets": list(self.assets),
        }


def read_service_text_asset(name: str) -> str:
    return (
        resources.files(SERVICE_ASSET_PACKAGE)
        .joinpath(*SERVICE_ASSET_DIRECTORY, name)
        .read_text(encoding="utf-8")
    )


def built_in_frontend_bundles() -> tuple[FrontendBundle, ...]:
    return (
        FrontendBundle(
            id="core-shell",
            label="Core Browser Shell",
            owner="core",
            assets=("index.html",),
        ),
        FrontendBundle(
            id="pane-window",
            label="Pane Window",
            owner="core",
            assets=("pane-window.html",),
        ),
        FrontendBundle(
            id="file-browser",
            label="File Browser",
            owner="file_browser",
            assets=("file-browser.html",),
        ),
    )


def frontend_asset_payload() -> list[dict[str, object]]:
    return [bundle.payload() for bundle in built_in_frontend_bundles()]
