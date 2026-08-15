from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIRS = (
    "electroboy-core",
    "electroboy-modules",
    "electroboy-workflow-software",
    "electroboy-workflow-creative-writing",
)


@pytest.fixture(scope="module")
def production_wheels(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    wheel_dir = tmp_path_factory.mktemp("production-wheels")
    command = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--wheel-dir",
        str(wheel_dir),
        *(str(ROOT / "packages" / package) for package in PACKAGE_DIRS),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout
    wheels: dict[str, Path] = {}
    for package in PACKAGE_DIRS:
        normalized = package.replace("-", "_")
        matches = tuple(wheel_dir.glob(f"{normalized}-*.whl"))
        assert len(matches) == 1, (package, matches)
        wheels[package] = matches[0]
    return wheels


@pytest.mark.parametrize(
    ("packages", "expected_workflows"),
    [
        (("electroboy-core",), []),
        (
            (
                "electroboy-core",
                "electroboy-modules",
                "electroboy-workflow-software",
            ),
            ["software"],
        ),
        (
            (
                "electroboy-core",
                "electroboy-modules",
                "electroboy-workflow-creative-writing",
            ),
            ["creative-writing"],
        ),
    ],
)
def test_selected_wheel_combinations_start_service(
    production_wheels: dict[str, Path],
    tmp_path: Path,
    packages: tuple[str, ...],
    expected_workflows: list[str],
) -> None:
    site_dir = tmp_path / "site"
    install = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(site_dir),
            *(str(production_wheels[package]) for package in packages),
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=90,
        check=False,
    )
    assert install.returncode == 0, install.stdout

    service_root = tmp_path / "service-root"
    script = """
import json
import sys
from pathlib import Path
from electroboy.service.app import create_server, health_payload

root = Path(sys.argv[1])
server = create_server(root, port=0)
try:
    registry = server.service_state.workflow_registry
    print(json.dumps(health_payload(root, registry.modules, registry)))
finally:
    server.server_close()
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(site_dir)
    environment["PYTHONNOUSERSITE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-S", "-c", script, str(service_root)],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["workflows"] == expected_workflows
    expected_modules = (
        {"core"}
        if len(packages) == 1
        else {
            "agent_sessions",
            "binder",
            "corkboard",
            "core",
            "file_browser",
            "markdown_documents",
            "progress",
            "project_shell",
            "recent_projects",
            "review_reports",
            "structured_documents",
        }
    )
    assert set(payload["modules"]) == expected_modules
    assert all(entry["provider"] for entry in payload["plugins"]["modules"])
    assert all(
        entry["entry_point"] for entry in payload["plugins"]["modules"]
    )
