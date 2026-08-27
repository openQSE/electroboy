from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from electroboy.modules.creative_workspace import render_corkboard_html
from electroboy.service import create_server
from electroboy.service.workflow_config import WorkflowConfig, save_workflow_config

CHROME = shutil.which("google-chrome") or shutil.which("chromium")
NODE = shutil.which("node")


def browser_dom(server: object, profile: Path) -> subprocess.CompletedProcess[str]:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        return subprocess.run(
            [
                str(CHROME),
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=4000",
                "--dump-dom",
                f"http://127.0.0.1:{port}/",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def browser_file_dom(page: str, root: Path) -> subprocess.CompletedProcess[str]:
    page_path = root / "corkboard.html"
    page_path.write_text(page, encoding="utf-8")
    return subprocess.run(
        [
            str(CHROME),
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            f"--user-data-dir={root / 'chrome-profile'}",
            "--virtual-time-budget=1000",
            "--dump-dom",
            page_path.as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_document_navigation_controller_exposes_link_helpers() -> None:
    asset = (
        Path(__file__).resolve().parents[1]
        / "src/electroboy/modules/assets/document-navigation.js"
    )
    script = """
global.window = { location: { origin: "http://127.0.0.1" } };
require(process.argv[1]);
const navigation = window.ElectroBoyDocumentNavigation.create();
for (const name of [
  "destination",
  "entry",
  "frameEntry",
  "location",
  "restoreFrame",
  "target",
]) {
  if (typeof navigation[name] !== "function") {
    throw new Error(`missing navigation helper: ${name}`);
  }
}
const destination = navigation.destination({
  target: { path: "guide.md", label: "Guide" },
  location: { fragment: "install" },
});
if (destination.target.path !== "guide.md") {
  throw new Error("document link destination was not normalized");
}
"""

    completed = subprocess.run(
        [str(NODE), "-e", script, str(asset)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_input_history_keeps_the_latest_two_thousand_entries() -> None:
    asset = (
        Path(__file__).resolve().parents[1]
        / "src/electroboy/modules/assets/input-history.js"
    )
    script = """
const values = new Map();
global.window = {
  localStorage: {
    getItem: (key) => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, value),
  },
};
require(process.argv[1]);
const history = window.ElectroBoyInputHistory;
for (let index = 0; index < 2005; index += 1) {
  history.appendEntry(`entry-${index}`);
}
history.appendEntry("   ");
const entries = history.loadEntries();
if (history.MAX_ENTRIES !== 2000 || entries.length !== 2000) {
  throw new Error(`unexpected history size: ${entries.length}`);
}
if (entries[0] !== "entry-5" || entries.at(-1) !== "entry-2004") {
  throw new Error("history did not retain the latest entries");
}
"""

    completed = subprocess.run(
        [str(NODE), "-e", script, str(asset)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_input_history_scopes_entries_by_project_and_agent_session() -> None:
    asset = (
        Path(__file__).resolve().parents[1]
        / "src/electroboy/modules/assets/input-history.js"
    )
    script = """
const values = new Map();
global.window = {
  localStorage: {
    getItem: (key) => values.has(key) ? values.get(key) : null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
  },
};
require(process.argv[1]);
const history = window.ElectroBoyInputHistory;
history.appendEntry("project-a/session-1", {
  projectRoot: "/project-a",
  sessionId: "session-1",
});
history.appendEntry("project-a/session-2", {
  projectRoot: "/project-a",
  sessionId: "session-2",
});
history.appendEntry("project-b/session-1", {
  projectRoot: "/project-b",
  sessionId: "session-1",
});
const first = history.loadEntries({
  projectRoot: "/project-a",
  sessionId: "session-1",
});
const second = history.loadEntries({
  projectRoot: "/project-a",
  sessionId: "session-2",
});
const otherProject = history.loadEntries({
  projectRoot: "/project-b",
  sessionId: "session-1",
});
if (first.join("|") !== "project-a/session-1") {
  throw new Error(`unexpected first session history: ${first.join("|")}`);
}
if (second.join("|") !== "project-a/session-2") {
  throw new Error(`unexpected second session history: ${second.join("|")}`);
}
if (otherProject.join("|") !== "project-b/session-1") {
  throw new Error(`unexpected other project history: ${otherProject.join("|")}`);
}
history.appendEntry("local draft", {
  projectRoot: "/project-a",
  sessionId: "local-session",
});
history.appendEntry("provider continuation", {
  projectRoot: "/project-a",
  sessionId: "provider-session",
  localSessionId: "local-session",
});
const continued = history.loadEntries({
  projectRoot: "/project-a",
  sessionId: "provider-session",
  localSessionId: "local-session",
});
if (continued.join("|") !== "local draft|provider continuation") {
  throw new Error(`unexpected continued session history: ${continued.join("|")}`);
}
"""

    completed = subprocess.run(
        [str(NODE), "-e", script, str(asset)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(CHROME is None, reason="headless Chrome is not installed")
def test_browser_shell_loads_and_connects(tmp_path: Path) -> None:
    server = create_server(tmp_path / "service", port=0)
    completed = browser_dom(server, tmp_path / "chrome-profile")

    assert completed.returncode == 0, completed.stdout
    assert 'id="connection" class="connection"' in completed.stdout
    assert 'title="connected">connected</div>' in completed.stdout
    assert 'data-stage="requirements"' in completed.stdout
    assert 'id="sessionSwitcher"' in completed.stdout
    assert 'data-provider="electroboy' in completed.stdout
    assert 'data-pane-drag-handle="true"' in completed.stdout
    assert 'id="agentSendShortcut"' in completed.stdout
    assert 'id="showInputHistory"' in completed.stdout
    assert 'class="input-history-overlay"' in completed.stdout
    assert 'class="pane-drag-detach-target"' in completed.stdout
    assert ">Software Engineering</option>" in completed.stdout
    assert ">Creative Writing</option>" in completed.stdout
    assert "Software Engineering (electroboy" not in completed.stdout
    assert "Creative Writing (electroboy" not in completed.stdout
    assert completed.stdout.count('data-pane-kind="agent"') == 1
    assert completed.stdout.count('data-pane-kind="scratch"') == 1
    assert completed.stdout.count('data-pane-kind="status"') == 1


@pytest.mark.skipif(CHROME is None, reason="headless Chrome is not installed")
def test_browser_shell_loads_creative_workflow_navigation(tmp_path: Path) -> None:
    root = tmp_path / "creative-service"
    save_workflow_config(
        root,
        WorkflowConfig(enabled_builtins=("creative-writing",)),
    )
    completed = browser_dom(
        create_server(root, port=0),
        tmp_path / "creative-chrome-profile",
    )

    assert completed.returncode == 0, completed.stdout
    assert 'class="creative-binder"' in completed.stdout
    assert 'data-creative-control="project-menu"' in completed.stdout
    assert 'data-creative-control="recent-projects-menu"' in completed.stdout
    assert ">Recent projects</span>" in completed.stdout
    assert 'data-stage="requirements"' not in completed.stdout
    assert completed.stdout.count('data-pane-kind="empty"') == 1
    assert 'class="pane-layout-leaf active pane-layout-root"' in completed.stdout
    assert '<option value="empty">Choose pane</option>' in completed.stdout


@pytest.mark.skipif(CHROME is None, reason="headless Chrome is not installed")
def test_browser_corkboard_uses_provider_default_grid_layout(tmp_path: Path) -> None:
    completed = browser_file_dom(
        render_corkboard_html(
            {
                "provider": "example",
                "board_id": "family",
                "board_type": "freeform",
                "layout_modes": ["grid", "freeform"],
                "default_layout_mode": "grid",
                "title": "Family board",
                "capabilities": ["move-card"],
                "cards": [
                    {
                        "id": "card-1",
                        "title": "Existing card",
                        "note": "Keeps its current data",
                        "x": 320,
                        "y": 180,
                    }
                ],
            }
        )[0],
        tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    assert 'class="board grid"' in completed.stdout
    assert '<option value="grid">Grid</option>' in completed.stdout
    assert '<option value="freeform">Freeform</option>' in completed.stdout
    assert 'id="autoOrganize"' in completed.stdout
    assert 'id="layoutControl" class="layout-control"' in completed.stdout


@pytest.mark.skipif(CHROME is None, reason="headless Chrome is not installed")
def test_browser_shell_has_clean_empty_workflow_state(tmp_path: Path) -> None:
    root = tmp_path / "core-service"
    save_workflow_config(root, WorkflowConfig(enabled_builtins=()))
    completed = browser_dom(
        create_server(root, port=0),
        tmp_path / "core-chrome-profile",
    )

    assert completed.returncode == 0, completed.stdout
    assert "No workflows are installed or enabled." in completed.stdout
    assert 'data-stage="requirements"' not in completed.stdout
    assert 'class="creative-binder"' not in completed.stdout
