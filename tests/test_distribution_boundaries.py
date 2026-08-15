from __future__ import annotations

import json
import os
import shutil
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
CHROME = shutil.which("google-chrome") or shutil.which("chromium")


def install_packages(
    destination: Path,
    wheels: dict[str, Path],
    packages: tuple[str, ...],
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(destination),
            *(str(wheels[package]) for package in packages),
        ],
        cwd=destination.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout


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
    install_packages(site_dir, production_wheels, packages)

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


@pytest.mark.skipif(CHROME is None, reason="headless Chrome is not installed")
@pytest.mark.parametrize(
    ("packages", "present", "absent", "workflow_asset"),
    [
        (
            ("electroboy-core",),
            "No workflows are installed or enabled.",
            'data-stage="requirements"',
            "",
        ),
        (
            (
                "electroboy-core",
                "electroboy-modules",
                "electroboy-workflow-software",
            ),
            'data-stage="requirements"',
            'class="creative-binder"',
            "js/workflows/software.js",
        ),
        (
            (
                "electroboy-core",
                "electroboy-modules",
                "electroboy-workflow-creative-writing",
            ),
            'class="creative-binder"',
            'data-stage="requirements"',
            "js/workflows/creative-writing.js",
        ),
    ],
)
def test_selected_wheels_compose_browser_frontend(
    production_wheels: dict[str, Path],
    tmp_path: Path,
    packages: tuple[str, ...],
    present: str,
    absent: str,
    workflow_asset: str,
) -> None:
    site_dir = tmp_path / "browser-site"
    install_packages(site_dir, production_wheels, packages)
    script = r"""
import json
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from electroboy.service.app import create_server

root = Path(sys.argv[1])
chrome = sys.argv[2]
profile = Path(sys.argv[3])
server = create_server(root, port=0)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    with urllib.request.urlopen(url, timeout=10) as response:
        index = response.read().decode("utf-8")
    browser = subprocess.run(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            f"--user-data-dir={profile}",
            "--virtual-time-budget=4000",
            "--dump-dom",
            url,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
        check=False,
    )
    print(json.dumps({
        "returncode": browser.returncode,
        "dom": browser.stdout,
        "index": index,
    }))
finally:
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(site_dir)
    environment["PYTHONNOUSERSITE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            script,
            str(tmp_path / "browser-service-root"),
            str(CHROME),
            str(tmp_path / "chrome-profile"),
        ],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=45,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["returncode"] == 0, payload["dom"]
    assert present in payload["dom"]
    assert absent not in payload["dom"]
    if workflow_asset:
        assert workflow_asset in payload["index"]
    else:
        assert "js/workflows/" not in payload["index"]
