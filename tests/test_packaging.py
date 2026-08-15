from __future__ import annotations

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


def test_optional_frontend_assets_follow_package_ownership() -> None:
    assert (ROOT / "src/electroboy/modules/assets/corkboard.js").is_file()
    assert (
        ROOT / "src/electroboy/workflows/software/assets/frontend.js"
    ).is_file()
    assert (
        ROOT / "src/electroboy/workflows/creative_writing/assets/frontend.js"
    ).is_file()
    legacy_asset = ROOT / "src/electroboy/assets/service/js/workflows/software.js"
    assert not legacy_asset.exists()
