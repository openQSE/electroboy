"""Frontend asset manifest and resource loading for the browser service."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ModuleRegistry, WorkflowRegistry


SERVICE_ASSET_PACKAGE = "electroboy"
SERVICE_ASSET_DIRECTORY = ("assets", "service")
SERVICE_STATIC_ROUTE_PREFIX = "/assets/service/"
CONTRIBUTION_SCRIPT_MARKER = "<!-- __ELECTROBOY_CONTRIBUTION_SCRIPTS__ -->"
CONTRIBUTION_STYLE_MARKER = "<!-- __ELECTROBOY_CONTRIBUTION_STYLES__ -->"


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


def read_service_text_asset(
    name: str,
    module_registry: ModuleRegistry | None = None,
    workflow_registry: WorkflowRegistry | None = None,
) -> str:
    return _service_asset_resource(
        name,
        module_registry,
        workflow_registry,
    ).read_text(encoding="utf-8")


def read_service_binary_asset(
    relative_path: str,
    module_registry: ModuleRegistry | None = None,
    workflow_registry: WorkflowRegistry | None = None,
) -> bytes:
    return _service_asset_resource(
        relative_path,
        module_registry,
        workflow_registry,
    ).read_bytes()


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


def render_service_index(
    template: str,
    module_registry: ModuleRegistry | None = None,
    workflow_registry: WorkflowRegistry | None = None,
) -> str:
    """Render script tags for the installed and enabled contributions."""

    paths: list[str] = []
    if module_registry is not None:
        for module in module_registry.values():
            paths.extend(module.assets)
    if workflow_registry is not None:
        paths.extend(
            f"js/{workflow.frontend_bundle}"
            for workflow in workflow_registry.values()
            if workflow.frontend_bundle
        )
    scripts = "\n  ".join(
        f'<script src="{SERVICE_STATIC_ROUTE_PREFIX}{path}"></script>'
        for path in dict.fromkeys(paths)
    )
    stylesheets = [] if workflow_registry is None else [
        stylesheet
        for workflow in workflow_registry.values()
        for stylesheet in workflow.frontend_stylesheets
    ]
    links = "\n  ".join(
        f'<link rel="stylesheet" href="{SERVICE_STATIC_ROUTE_PREFIX}{path}">'
        for path in dict.fromkeys(stylesheets)
    )
    return (
        template.replace(CONTRIBUTION_STYLE_MARKER, links)
        .replace(CONTRIBUTION_SCRIPT_MARKER, scripts)
    )


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
                "js/core/pane-layout-drag.js",
                "js/core/input-shortcut.js",
                "js/core/runtime.js",
            ),
        ),
        FrontendBundle(
            id="agent-sessions",
            label="Agent Sessions",
            owner="agent_sessions",
            assets=("js/modules/agent-sessions.js",),
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


def frontend_asset_payload(
    module_registry: ModuleRegistry | None = None,
    workflow_registry: WorkflowRegistry | None = None,
) -> list[dict[str, object]]:
    bundles = built_in_frontend_bundles()
    if module_registry is None and workflow_registry is None:
        return [bundle.payload() for bundle in bundles]
    module_ids = {
        module.id for module in module_registry.values()
    } if module_registry is not None else set()
    workflow_ids = {
        workflow.id for workflow in workflow_registry.values()
    } if workflow_registry is not None else set()
    owners = {"core", *module_ids, *workflow_ids}
    active = [bundle for bundle in bundles if bundle.owner in owners]
    represented_owners = {bundle.owner for bundle in active}
    if module_registry is not None:
        active.extend(
            FrontendBundle(
                id=f"{module.id}-module",
                label=f"{module.label} Module",
                owner=module.id,
                assets=module.assets,
            )
            for module in module_registry.values()
            if module.assets and module.id not in represented_owners
        )
    if workflow_registry is not None:
        active.extend(
            FrontendBundle(
                id=f"{workflow.id}-workflow",
                label=f"{workflow.label} Workflow",
                owner=workflow.id,
                assets=(
                    f"js/{workflow.frontend_bundle}",
                    *workflow.frontend_stylesheets,
                ),
            )
            for workflow in workflow_registry.values()
            if workflow.frontend_bundle
            and workflow.id not in represented_owners
        )
    return [bundle.payload() for bundle in active]


def _asset_path_parts(relative_path: str) -> tuple[str, ...]:
    parts = tuple(part for part in relative_path.split("/") if part)
    if not parts or any(part in {".", ".."} for part in parts):
        raise FileNotFoundError(relative_path)
    return parts


def _service_asset_resource(
    relative_path: str,
    module_registry: ModuleRegistry | None,
    workflow_registry: WorkflowRegistry | None,
) -> object:
    parts = _asset_path_parts(relative_path)
    core_resource = resources.files(SERVICE_ASSET_PACKAGE).joinpath(
        *SERVICE_ASSET_DIRECTORY,
        *parts,
    )
    if core_resource.is_file():
        return core_resource

    for logical_path, package, root, resource_name in _contributed_assets(
        module_registry,
        workflow_registry,
    ):
        if logical_path != relative_path:
            continue
        try:
            resource = resources.files(package).joinpath(root, resource_name)
        except ModuleNotFoundError:
            continue
        if resource.is_file():
            return resource
    raise FileNotFoundError(relative_path)


def _contributed_assets(
    module_registry: ModuleRegistry | None,
    workflow_registry: WorkflowRegistry | None,
) -> tuple[tuple[str, str, str, str], ...]:
    assets: list[tuple[str, str, str, str]] = []
    if module_registry is not None:
        for module in module_registry.values():
            if not module.asset_package:
                continue
            for logical_path in module.assets:
                assets.append(
                    (
                        logical_path,
                        module.asset_package,
                        module.asset_root,
                        logical_path.rsplit("/", 1)[-1],
                    )
                )
    if workflow_registry is not None:
        for workflow in workflow_registry.values():
            if not workflow.asset_package:
                continue
            assets.append(
                (
                    f"js/{workflow.frontend_bundle}",
                    workflow.asset_package,
                    workflow.asset_root,
                    workflow.asset_resource,
                )
            )
            assets.extend(
                (
                    stylesheet,
                    workflow.asset_package,
                    workflow.asset_root,
                    stylesheet.rsplit("/", 1)[-1],
                )
                for stylesheet in workflow.frontend_stylesheets
            )
    # Compatibility for direct asset reads in source checkouts and tests.
    return tuple(assets) + (
        (
            "js/modules/agent-sessions.js",
            "electroboy.modules",
            "assets",
            "agent-sessions.js",
        ),
        (
            "js/modules/documents.js",
            "electroboy.modules",
            "assets",
            "documents.js",
        ),
        ("js/modules/binder.js", "electroboy.modules", "assets", "binder.js"),
        (
            "js/modules/corkboard.js",
            "electroboy.modules",
            "assets",
            "corkboard.js",
        ),
        (
            "js/modules/file-browser.js",
            "electroboy.modules",
            "assets",
            "file-browser.js",
        ),
        (
            "js/modules/progress.js",
            "electroboy.modules",
            "assets",
            "progress.js",
        ),
        (
            "js/modules/project-shell.js",
            "electroboy.modules",
            "assets",
            "project-shell.js",
        ),
    )
