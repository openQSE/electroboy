from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_standard_distribution_registers_built_in_contributions() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '[project.entry-points."electroboy.modules"]' in project
    assert 'core = "electroboy.service.core_module:module"' in project
    assert '[project.entry-points."electroboy.workflows"]' in project
    assert 'software = "electroboy.workflows.software.plugin:workflow"' in project
    assert (
        'creative-writing = '
        '"electroboy.workflows.creative_writing.plugin:workflow"'
    ) in project


def test_production_distributions_have_independent_manifests() -> None:
    expected = {
        "electroboy-core": "electroboy.service.core_module:module",
        "electroboy-modules": "electroboy.modules.corkboard:module",
        "electroboy-workflow-software": (
            "electroboy.workflows.software.plugin:workflow"
        ),
        "electroboy-workflow-creative-writing": (
            "electroboy.workflows.creative_writing.plugin:workflow"
        ),
    }

    for distribution, entry_point in expected.items():
        manifest = ROOT / "packages" / distribution / "pyproject.toml"
        text = manifest.read_text(encoding="utf-8")
        assert f'name = "{distribution}"' in text
        assert entry_point in text

    software_manifest = (
        ROOT / "packages/electroboy-workflow-software/pyproject.toml"
    ).read_text(encoding="utf-8")
    assert '[project.entry-points."electroboy.cli"]' in software_manifest
    assert (
        'software = "electroboy.workflows.software.cli:command_provider"'
        in software_manifest
    )


def test_optional_frontend_assets_follow_package_ownership() -> None:
    core_runtime = ROOT / "src/electroboy/assets/service/js/core/runtime.js"
    legacy_runtime = ROOT / "src/electroboy/assets/service/js/app.js"
    assert core_runtime.is_file()
    assert not legacy_runtime.exists()
    assert (ROOT / "src/electroboy/modules/assets/agent-sessions.js").is_file()
    assert (ROOT / "src/electroboy/modules/assets/documents.js").is_file()
    assert (ROOT / "src/electroboy/modules/assets/progress.js").is_file()
    assert (ROOT / "src/electroboy/modules/assets/project-shell.js").is_file()
    assert (ROOT / "src/electroboy/modules/assets/corkboard.js").is_file()
    assert (
        ROOT / "src/electroboy/workflows/software/assets/frontend.js"
    ).is_file()
    assert (
        ROOT / "src/electroboy/workflows/creative_writing/assets/frontend.js"
    ).is_file()
    assert (
        ROOT
        / "src/electroboy/workflows/creative_writing/assets/creative-writing.css"
    ).is_file()
    legacy_asset = ROOT / "src/electroboy/assets/service/js/workflows/software.js"
    assert not legacy_asset.exists()

    core_manifest = (
        ROOT / "packages/electroboy-core/pyproject.toml"
    ).read_text(encoding="utf-8")
    assert '"assets/service/js/core/*.js"' in core_manifest
    assert '"assets/service/js/*.js"' not in core_manifest

    creative_manifest = (
        ROOT / "packages/electroboy-workflow-creative-writing/pyproject.toml"
    ).read_text(encoding="utf-8")
    assert '"assets/*.css"' in creative_manifest


def test_workflow_controllers_do_not_import_service_app() -> None:
    controllers = (
        ROOT / "src/electroboy/workflows/software/controller.py",
        ROOT / "src/electroboy/workflows/creative_writing/controller.py",
    )

    for controller in controllers:
        source = controller.read_text(encoding="utf-8")
        assert "service import app" not in source
        assert "service.app" not in source
        assert "service_app" not in source


def test_service_app_does_not_own_capability_domain_implementations() -> None:
    source = (ROOT / "src/electroboy/service/app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    moved_implementations = {
        "requirements_document_html",
        "artifact_editor_html",
        "save_artifact_edit",
        "creative_corkboard_html",
        "_creative_tree_payload",
        "_save_creative_freeform_corkboard_card",
        "_progress_snapshot",
        "_session_events_markdown",
        "_load_work_item_registry",
        "_run_feature_start_context",
    }

    assert definitions.isdisjoint(moved_implementations)


def test_service_app_has_no_optional_package_imports() -> None:
    source = (ROOT / "src/electroboy/service/app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module or ""
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
    }
    imported_modules.update(
        alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert not any(
        module.startswith("electroboy.modules")
        or module.startswith("electroboy.workflows.software")
        or module.startswith("electroboy.workflows.creative_writing")
        for module in imported_modules
    )
