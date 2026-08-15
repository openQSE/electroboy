"""Frontend asset manifest and resource loading for the browser service."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources


SERVICE_ASSET_PACKAGE = "electroboy"
SERVICE_ASSET_DIRECTORY = ("assets", "service")
SERVICE_STATIC_ROUTE_PREFIX = "/assets/service/"


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


def read_service_binary_asset(relative_path: str) -> bytes:
    parts = _asset_path_parts(relative_path)
    return (
        resources.files(SERVICE_ASSET_PACKAGE)
        .joinpath(*SERVICE_ASSET_DIRECTORY, *parts)
        .read_bytes()
    )


def service_asset_content_type(relative_path: str) -> str:
    suffix = relative_path.rsplit(".", 1)[-1].lower()
    return {
        "css": "text/css; charset=utf-8",
        "html": "text/html; charset=utf-8",
        "js": "application/javascript; charset=utf-8",
        "json": "application/json; charset=utf-8",
        "png": "image/png",
        "svg": "image/svg+xml",
    }.get(suffix, "application/octet-stream")


def built_in_frontend_bundles() -> tuple[FrontendBundle, ...]:
    return (
        FrontendBundle(
            id="core-shell",
            label="Core Browser Shell",
            owner="core",
            assets=(
                "index.html",
                "css/shell.css",
                "js/core/registry.js",
                "js/app.js",
            ),
        ),
        FrontendBundle(
            id="documents",
            label="Document Panes",
            owner="markdown_documents",
            assets=("js/modules/documents.js",),
        ),
        FrontendBundle(
            id="binder",
            label="Binder Tree",
            owner="binder",
            assets=("js/modules/binder.js",),
        ),
        FrontendBundle(
            id="corkboard",
            label="Corkboard Pane",
            owner="corkboard",
            assets=("js/modules/corkboard.js",),
        ),
        FrontendBundle(
            id="file-browser-module",
            label="File Browser Module",
            owner="file_browser",
            assets=("js/modules/file-browser.js",),
        ),
        FrontendBundle(
            id="progress",
            label="Progress Pane",
            owner="progress",
            assets=("js/modules/progress.js",),
        ),
        FrontendBundle(
            id="project-shell",
            label="Project Shell",
            owner="project_shell",
            assets=("js/modules/project-shell.js",),
        ),
        FrontendBundle(
            id="software-workflow",
            label="Software Engineering Workflow",
            owner="software",
            assets=("js/workflows/software.js",),
        ),
        FrontendBundle(
            id="creative-writing-workflow",
            label="Creative Writing Workflow",
            owner="creative-writing",
            assets=("js/workflows/creative-writing.js",),
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


def _asset_path_parts(relative_path: str) -> tuple[str, ...]:
    parts = tuple(part for part in relative_path.split("/") if part)
    if not parts or any(part in {".", ".."} for part in parts):
        raise FileNotFoundError(relative_path)
    return parts
