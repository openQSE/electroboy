from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from electroboy.modules.creative_workspace import render_corkboard_html
from electroboy.modules.editable_mind_map_workspace import (
    render_editable_mind_map_html,
)
from electroboy.modules.mind_map_documents import empty_mind_map
from electroboy.modules.mind_map_workspace import render_mind_map_html
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
global.window = {
  location: {
    href: "http://127.0.0.1/artifacts/document?path=guide.md",
    origin: "http://127.0.0.1",
  },
};
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
const external = navigation.destination({
  target: { url: "https://example.com/reference?x=1#intro", label: "Example" },
});
if (
  !external.target.external ||
  external.target.url !== "https://example.com/reference?x=1#intro"
) {
  throw new Error("external link destination was not normalized");
}
if (navigation.target({ url: "mailto:team@example.com" }) !== null) {
  throw new Error("non-http URL target was accepted");
}
navigation.record(destination);
const back = navigation.goBack(external);
if (!back || back.target.path !== "guide.md") {
  throw new Error("document back history entry was not restored");
}
const forward = navigation.goForward(back);
if (!forward || forward.target.url !== "https://example.com/reference?x=1#intro") {
  throw new Error("external forward history entry was not restored");
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
def test_terminal_behavior_locks_user_viewport_during_async_write() -> None:
    asset = (
        Path(__file__).resolve().parents[1]
        / "src/electroboy/assets/service/js/core/terminal-behavior.js"
    )
    script = """
global.window = {
  clearTimeout,
  setTimeout,
};
require(process.argv[1]);

function fakeTerminal() {
  const listeners = {};
  const scrollHandlers = [];
  let pendingWrite = null;
  const terminal = {
    rows: 20,
    buffer: {
      active: {
        baseY: 100,
        cursorY: 0,
        viewportY: 100,
      },
    },
    element: {
      addEventListener(name, handler) {
        listeners[name] = handler;
      },
    },
    scrollCalls: [],
    registerMarker(offset) {
      return {
        disposed: false,
        line: terminal.buffer.active.baseY +
          terminal.buffer.active.cursorY +
          offset,
        dispose() {
          this.disposed = true;
        },
      };
    },
    onScroll(handler) {
      scrollHandlers.push(handler);
      return { dispose() {} };
    },
    write(text, callback) {
      pendingWrite = callback;
    },
    scrollToBottom() {
      this.scrollCalls.push(["bottom"]);
      this.buffer.active.viewportY = this.buffer.active.baseY;
    },
    scrollToLine(line) {
      this.scrollCalls.push(["line", line]);
      this.buffer.active.viewportY = line;
    },
    emit(name, event = {}) {
      listeners[name]?.({
        key: "",
        ...event,
      });
    },
    emitScroll(viewportY) {
      this.buffer.active.viewportY = viewportY;
      for (const handler of scrollHandlers) {
        handler(viewportY);
      }
    },
    completeWrite() {
      const callback = pendingWrite;
      pendingWrite = null;
      callback();
    },
  };
  return terminal;
}

const behavior = window.ElectroBoyTerminalBehavior;
const terminal = fakeTerminal();
behavior.install(terminal);
let committed = false;
behavior.write(terminal, "streamed output", () => {
  committed = true;
});
terminal.emit("wheel");
terminal.emitScroll(42);
terminal.buffer.active.baseY = 108;
terminal.buffer.active.viewportY = 108;
terminal.completeWrite();

if (!committed) {
  throw new Error("write callback was not committed");
}
if (!terminal.scrollCalls.some((call) => call[0] === "line" && call[1] === 42)) {
  throw new Error("user-selected historical viewport was not restored");
}

const bottomTerminal = fakeTerminal();
bottomTerminal.buffer.active.viewportY = 40;
behavior.install(bottomTerminal);
bottomTerminal.emitScroll(40);
behavior.write(bottomTerminal, "streamed output", () => {});
bottomTerminal.emit("keydown", { key: "End" });
bottomTerminal.buffer.active.baseY = 108;
bottomTerminal.emitScroll(108);
bottomTerminal.completeWrite();
if (
  bottomTerminal.scrollCalls.some((call) => call[0] === "line" && call[1] === 40)
) {
  throw new Error("stale historical viewport was restored after returning bottom");
}

const draggingTerminal = fakeTerminal();
draggingTerminal.buffer.active.cursorY = 19;
behavior.install(draggingTerminal);
behavior.write(draggingTerminal, "streamed output", () => {});
draggingTerminal.emit("pointerdown");
draggingTerminal.emitScroll(42);
draggingTerminal.emit("pointermove", { buttons: 1 });
draggingTerminal.emitScroll(70);
draggingTerminal.emit("pointerup");
draggingTerminal.buffer.active.baseY = 108;
draggingTerminal.buffer.active.viewportY = 108;
draggingTerminal.completeWrite();
const draggingScroll = draggingTerminal.scrollCalls.at(-1);
if (!draggingScroll || draggingScroll[0] !== "line" || draggingScroll[1] !== 70) {
  throw new Error("active scrollbar drag did not preserve its latest viewport");
}

const visibleTailTerminal = fakeTerminal();
visibleTailTerminal.buffer.active.cursorY = 10;
visibleTailTerminal.buffer.active.viewportY = 92;
behavior.install(visibleTailTerminal);
behavior.write(visibleTailTerminal, "streamed output", () => {});
visibleTailTerminal.buffer.active.baseY = 108;
visibleTailTerminal.buffer.active.viewportY = 100;
visibleTailTerminal.completeWrite();
const visibleTailScroll = visibleTailTerminal.scrollCalls.at(-1);
if (
  !visibleTailScroll ||
  visibleTailScroll[0] !== "line" ||
  visibleTailScroll[1] !== 100
) {
  throw new Error("visible live output did not advance naturally");
}

const followTerminal = fakeTerminal();
followTerminal.buffer.active.cursorY = 19;
followTerminal.buffer.active.viewportY = 42;
behavior.install(followTerminal);
followTerminal.emitScroll(42);
behavior.write(followTerminal, "historical output", () => {});
followTerminal.buffer.active.baseY = 108;
followTerminal.buffer.active.viewportY = 108;
followTerminal.completeWrite();
if (!followTerminal.scrollCalls.some((call) => call[0] === "line" && call[1] === 42)) {
  throw new Error("hidden live output did not preserve the historical viewport");
}
const followCallCount = followTerminal.scrollCalls.length;
behavior.followOutput(followTerminal);
behavior.write(followTerminal, "new prompt output", () => {});
followTerminal.buffer.active.baseY = 116;
followTerminal.buffer.active.viewportY = 116;
followTerminal.completeWrite();
if (
  followTerminal.scrollCalls
    .slice(followCallCount)
    .some((call) => call[0] === "line" && call[1] === 42)
) {
  throw new Error("submitting input did not release the historical viewport");
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
def test_browser_mind_map_expands_children_without_reserving_subtree_space(
    tmp_path: Path,
) -> None:
    page, _status = render_mind_map_html(
        {
            "provider": "layout-test",
            "title": "Layout test",
            "sources": [
                {"id": "source", "kind": "source", "title": "Source"}
            ],
            "observations": [
                {"id": "observation-a", "kind": "observation", "title": "A"},
                {"id": "observation-b", "kind": "observation", "title": "B"},
                {"id": "observation-c", "kind": "observation", "title": "C"},
            ],
            "provider_events": [],
            "facts": [
                {"id": "fact-a", "kind": "fact", "title": "Fact A"},
                {"id": "fact-b", "kind": "fact", "title": "Fact B"},
                {"id": "fact-c", "kind": "fact", "title": "Fact C"},
                {"id": "fact-d", "kind": "fact", "title": "Fact D"},
                {"id": "fact-e", "kind": "fact", "title": "Fact E"},
            ],
            "edges": [
                {"from": "source", "to": "observation-a"},
                {"from": "source", "to": "observation-b"},
                {"from": "source", "to": "observation-c"},
                {"from": "observation-a", "to": "fact-a"},
                {"from": "observation-a", "to": "fact-b"},
                {"from": "observation-a", "to": "fact-c"},
                {"from": "observation-b", "to": "fact-b"},
                {"from": "observation-b", "to": "fact-c"},
                {"from": "observation-b", "to": "fact-d"},
                {"from": "fact-d", "to": "fact-e"},
            ],
        }
    )
    probe = """
<script>
  const mindMapNode = (nodeId) =>
    document.querySelector(`[data-node-id="${nodeId}"]`);
  const nodeTop = (nodeId) => Number.parseFloat(mindMapNode(nodeId).style.top);
  const verticalGaps = (nodeIds) => nodeIds.slice(1).map((nodeId, index) => {
    const previous = mindMapNode(nodeIds[index]);
    return Math.round(
      nodeTop(nodeId) - Number.parseFloat(previous.style.top) - previous.offsetHeight
    );
  });
  mindMapNode("source").click();
  render();
  const observationIds = ["observation-a", "observation-b", "observation-c"];
  const observationGaps = verticalGaps(observationIds);
  const collapsedTop = nodeTop("observation-b");
  mindMapNode("observation-a").click();
  render();
  const factGaps = verticalGaps(["fact-a", "fact-b", "fact-c"]);
  mindMapNode("observation-b").click();
  render();
  const dagFactIds = ["fact-a", "fact-b", "fact-c", "fact-d"]
    .sort((leftId, rightId) => nodeTop(leftId) - nodeTop(rightId));
  const dagGaps = verticalGaps(dagFactIds);
  mindMapNode("fact-d").click();
  render();
  const verticalSeparation = (leftId, rightId) => {
    const left = mindMapNode(leftId);
    const right = mindMapNode(rightId);
    if (nodeTop(leftId) <= nodeTop(rightId)) {
      return nodeTop(rightId) - nodeTop(leftId) - left.offsetHeight;
    }
    return nodeTop(leftId) - nodeTop(rightId) - right.offsetHeight;
  };
  const collisionGap = Math.round(Math.min(
    ...["fact-a", "fact-b", "fact-c"].map((nodeId) =>
      verticalSeparation("fact-d", nodeId)
    )
  ));
  const nodeCenter = (nodeId) => {
    const node = mindMapNode(nodeId);
    return nodeTop(nodeId) + node.offsetHeight / 2;
  };
  const result = document.createElement("div");
  result.id = "mindMapLayoutProbe";
  result.dataset.collapsedStable = String(
    Math.abs(nodeTop("observation-b") - collapsedTop) < 0.5
  );
  result.dataset.observationGaps = observationGaps.join(",");
  result.dataset.factGaps = factGaps.join(",");
  result.dataset.dagGaps = dagGaps.join(",");
  result.dataset.collisionGap = String(collisionGap);
  result.dataset.subtreeCentered = String(
    Math.abs(nodeCenter("fact-d") - nodeCenter("fact-e")) < 0.5
  );
  document.body.append(result);
</script>
"""
    page = page.replace("</body>", f"{probe}</body>")

    completed = browser_file_dom(page, tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert (
        '<div id="mindMapLayoutProbe" data-collapsed-stable="true" '
        'data-observation-gaps="24,24" data-fact-gaps="24,24" '
        'data-dag-gaps="24,24,24" '
        'data-collision-gap="24" data-subtree-centered="true"></div>'
        in completed.stdout
    )


@pytest.mark.skipif(CHROME is None, reason="headless Chrome is not installed")
def test_browser_mind_map_expands_nested_observation_to_assignment(
    tmp_path: Path,
) -> None:
    page, _status = render_mind_map_html(
        {
            "provider": "nested-observation-test",
            "title": "Nested observation test",
            "sources": [
                {"id": "source", "kind": "source", "title": "Source"}
            ],
            "observations": [
                {"id": "event", "kind": "observation", "title": "Event"},
                {
                    "id": "presentation",
                    "kind": "observation",
                    "title": "Presentation",
                },
            ],
            "provider_events": [],
            "facts": [
                {"id": "task", "kind": "fact", "title": "Attend"},
                {
                    "id": "assignment",
                    "kind": "fact",
                    "title": "Assign attendance",
                },
            ],
            "edges": [
                {
                    "id": "source-event",
                    "from": "source",
                    "to": "event",
                    "primary": True,
                },
                {
                    "id": "presentation-part-of-event",
                    "from": "presentation",
                    "to": "event",
                    "tree_from": "event",
                    "tree_to": "presentation",
                    "relationship": "part_of",
                    "primary": True,
                },
                {
                    "id": "presentation-task",
                    "from": "presentation",
                    "to": "task",
                    "primary": True,
                },
                {
                    "id": "task-assignment",
                    "from": "task",
                    "to": "assignment",
                    "relationship": "proposes_assignment",
                    "primary": True,
                },
            ],
        }
    )
    probe = """
<script>
  const nestedNode = (nodeId) =>
    document.querySelector(`[data-node-id="${nodeId}"]`);
  nestedNode("source").click();
  nestedNode("event").click();
  nestedNode("presentation").click();
  nestedNode("task").click();
  const result = document.createElement("div");
  result.id = "nestedObservationProbe";
  result.dataset.rendered = [
    "source",
    "event",
    "presentation",
    "task",
    "assignment",
  ].filter((nodeId) => nestedNode(nodeId)).join(",");
  document.body.append(result);
</script>
"""

    completed = browser_file_dom(
        page.replace("</body>", f"{probe}</body>"),
        tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    assert (
        '<div id="nestedObservationProbe" '
        'data-rendered="source,event,presentation,task,assignment"></div>'
        in completed.stdout
    )


@pytest.mark.skipif(CHROME is None, reason="headless Chrome is not installed")
def test_browser_mind_map_telemetry_describes_expansion_results(
    tmp_path: Path,
) -> None:
    page, _status = render_mind_map_html(
        {
            "provider": "telemetry-test",
            "title": "Telemetry test",
            "sources": [
                {"id": "source", "kind": "source", "title": "Source"}
            ],
            "observations": [
                {"id": "observation-a", "kind": "observation", "title": "A"},
                {"id": "observation-b", "kind": "observation", "title": "B"},
            ],
            "provider_events": [],
            "facts": [],
            "edges": [
                {
                    "id": "source-a",
                    "from": "source",
                    "to": "observation-a",
                    "relationship": "produced_observation",
                    "primary": True,
                },
                {
                    "id": "source-b",
                    "from": "source",
                    "to": "observation-b",
                    "relationship": "produced_observation",
                    "primary": True,
                },
            ],
        }
    )
    probe = """
<script>
  const telemetryEvents = [];
  let telemetryRequestsInFlight = 0;
  let maxTelemetryRequestsInFlight = 0;
  telemetryEnabled = () => true;
  window.fetch = (_url, options) => {
    telemetryRequestsInFlight += 1;
    maxTelemetryRequestsInFlight = Math.max(
      maxTelemetryRequestsInFlight,
      telemetryRequestsInFlight
    );
    telemetryEvents.push(JSON.parse(options.body));
    return new Promise((resolve) => window.setTimeout(() => {
      telemetryRequestsInFlight -= 1;
      resolve({ ok: true });
    }, 2));
  };
  emitGraphTelemetry(displayedLayout());
  document.querySelector('[data-node-id="source"]').click();
  window.setTimeout(() => {
    const requested = telemetryEvents.find(
      (event) => event.event === "mind_map.node.toggle.requested"
    );
    const completed = telemetryEvents.find(
      (event) => event.event === "mind_map.node.toggle.completed"
    );
    const graphReceived = telemetryEvents.find(
      (event) => event.event === "mind_map.graph.received"
    );
    const graphNodes = telemetryEvents.find(
      (event) => event.event === "mind_map.graph.nodes"
    );
    const graphEdges = telemetryEvents.find(
      (event) => event.event === "mind_map.graph.edges"
    );
    const result = document.createElement("div");
    result.id = "mindMapTelemetryProbe";
    result.dataset.requestedNode = requested.node.id;
    result.dataset.expectedChildren = String(
      requested.expected_children.total_count
    );
    result.dataset.completedNode = completed.node.id;
    result.dataset.clickedLabel = requested.node.label;
    result.dataset.addedNodes = String(completed.added_nodes.total_count);
    result.dataset.graphNodes = String(graphNodes.total_count);
    result.dataset.graphEdges = String(graphEdges.total_count);
    result.dataset.sameGraph = String(
      graphReceived.graph_instance_id === graphNodes.graph_instance_id &&
      graphNodes.graph_instance_id === graphEdges.graph_instance_id
    );
    result.dataset.maxRequestsInFlight = String(maxTelemetryRequestsInFlight);
    result.dataset.rendered = String(
      completed.added_nodes.items.every((node) => node.rendered)
    );
    result.dataset.hasTitles = String(
      telemetryEvents.some((event) => Object.hasOwn(event.node || {}, "title"))
    );
    document.body.append(result);
  }, 100);
</script>
"""

    completed = browser_file_dom(
        page.replace("</body>", f"{probe}</body>"),
        tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    assert (
        '<div id="mindMapTelemetryProbe" data-requested-node="source" '
        'data-expected-children="2" data-completed-node="source" '
        'data-clicked-label="Source" data-added-nodes="2" '
        'data-graph-nodes="3" data-graph-edges="2" '
        'data-same-graph="true" data-max-requests-in-flight="1" '
        'data-rendered="true" '
        'data-has-titles="false"></div>'
        in completed.stdout
    )


@pytest.mark.skipif(CHROME is None, reason="headless Chrome is not installed")
def test_browser_mind_map_full_mode_overlays_secondary_relationships(
    tmp_path: Path,
) -> None:
    page, _status = render_mind_map_html(
        {
            "provider": "relationship-test",
            "title": "Relationship test",
            "sources": [{"id": "source", "kind": "source", "title": "Source"}],
            "observations": [
                {"id": "observation-a", "kind": "observation", "title": "A"},
                {"id": "observation-b", "kind": "observation", "title": "B"},
            ],
            "provider_events": [],
            "facts": [{"id": "fact", "kind": "fact", "title": "Fact"}],
            "edges": [
                {
                    "id": "source-a",
                    "from": "source",
                    "to": "observation-a",
                    "family": "provenance",
                    "primary": True,
                },
                {
                    "id": "source-b",
                    "from": "source",
                    "to": "observation-b",
                    "family": "provenance",
                    "primary": True,
                },
                {
                    "id": "a-fact",
                    "from": "observation-a",
                    "to": "fact",
                    "family": "provenance",
                    "primary": True,
                },
                {
                    "id": "b-fact",
                    "from": "observation-b",
                    "to": "fact",
                    "relationship": "supports",
                    "family": "provenance",
                    "primary": False,
                },
            ],
        }
    )
    probe = """
<script>
  document.querySelector('[data-node-id="source"]').click();
  document.querySelector('[data-node-id="observation-a"]').click();
  document.querySelector('[data-node-id="observation-b"]').click();
  render();
  const cleanPosition = document.querySelector('[data-node-id="fact"]').style.cssText;
  const cleanEdges = document.querySelectorAll('.mind-map-edge').length;
  document.getElementById('mindMapFullMode').click();
  const fullPosition = document.querySelector('[data-node-id="fact"]').style.cssText;
  const result = document.createElement('div');
  result.id = 'mindMapModeProbe';
  result.dataset.cleanEdges = String(cleanEdges);
  result.dataset.fullEdges = String(document.querySelectorAll('.mind-map-edge').length);
  result.dataset.stable = String(cleanPosition === fullPosition);
  result.dataset.legend = document.getElementById('mindMapLegendCount').textContent;
  document.body.append(result);
</script>
"""
    completed = browser_file_dom(page.replace("</body>", f"{probe}</body>"), tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert (
        '<div id="mindMapModeProbe" data-clean-edges="3" data-full-edges="4" '
        'data-stable="true" data-legend="Displaying 4 of 4 relationships"></div>'
        in completed.stdout
    )


@pytest.mark.skipif(CHROME is None, reason="headless Chrome is not installed")
def test_browser_editable_mind_map_adds_child_and_zooms(tmp_path: Path) -> None:
    document = empty_mind_map("Planning")
    document["nodes"] = [
        {
            "id": "root",
            "text": "A long planning node " * 12,
            "parent_id": None,
            "order": 0,
            "x": 80,
            "y": 80,
            "links": [],
        }
    ]
    page, _status = render_editable_mind_map_html(
        {
            "path": "/tmp/planning.mindmap.json",
            "revision": "one",
            "document": document,
        },
        context_id="workspace-one",
        connection_id="connection-one",
    )
    probe = """
<script>
let autosaveUrl = '';
window.fetch = async (url, options) => {
  autosaveUrl = String(url);
  const request = JSON.parse(options.body);
  return {
    ok: true,
    json: async () => ({ revision: 'two', document: request.document }),
  };
};
const first = document.querySelector('.node');
const rootFontSize = getComputedStyle(first.querySelector('.node-text')).fontSize;
first.click();
const canvas = document.getElementById('canvas');
canvas.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
const editor = document.querySelector('.node textarea');
const childGenerationFontSize = getComputedStyle(editor).fontSize;
const randomBranchColor = document.querySelector('.node.focused').dataset.ownColor;
editor.value = 'Committed child';
editor.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
const doubleClickNode = document.querySelector('.node.focused');
doubleClickNode.click();
const firstClickPreservedNode = doubleClickNode.isConnected;
doubleClickNode.dispatchEvent(
  new MouseEvent('dblclick', { bubbles: true }),
);
const clickAwayEditor = document.querySelector('.node textarea');
clickAwayEditor.value = 'Single-click commit';
canvas.dispatchEvent(new PointerEvent('pointerdown', { button: 0, bubbles: true }));
canvas.click();
Array.from(document.querySelectorAll('.node')).find(
  (node) => node.querySelector('.node-text')?.textContent === 'Single-click commit',
).click();
document.querySelector('[data-action="color-blue"]').click();
canvas.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
const grandchildEditor = document.querySelector('.node textarea');
const grandchildGenerationFontSize = getComputedStyle(grandchildEditor).fontSize;
grandchildEditor.value = 'Inherited grandchild';
grandchildEditor.dispatchEvent(new KeyboardEvent('keydown', {
  key: 'Enter', bubbles: true,
}));
const grandchild = document.querySelector('.node.focused');
const grandchildInherits = grandchild.dataset.ownColor === 'default'
  && grandchild.dataset.color === 'blue';
Array.from(document.querySelectorAll('.node')).find(
  (node) => node.querySelector('.node-text')?.textContent === 'Single-click commit',
).click();
window.dispatchEvent(new MessageEvent('message', {
  origin: window.location.origin,
  data: {
    type: 'electroboy-mind-map-command',
    action: 'font-size-set',
    fontSize: 23.5,
  },
}));
for (const action of ['font-size-increase', 'font-size-decrease']) {
  window.dispatchEvent(new MessageEvent('message', {
    origin: window.location.origin,
    data: { type: 'electroboy-mind-map-command', action },
  }));
}
document.querySelector('[data-action="focus"]').click();
canvas.dispatchEvent(new WheelEvent('wheel', { deltaY: -100, bubbles: true }));
window.setTimeout(() => {
  let focused = document.querySelector('.node.focused');
  const resizeHandle = focused.querySelector('.node-resize-handle');
  resizeHandle.dispatchEvent(new PointerEvent('pointerdown', {
    button: 0, pointerId: 71, clientX: 100, clientY: 100, bubbles: true,
  }));
  canvas.dispatchEvent(new PointerEvent('pointermove', {
    button: 0, pointerId: 71, clientX: 160, clientY: 125, bubbles: true,
  }));
  canvas.dispatchEvent(new PointerEvent('pointerup', {
    button: 0, pointerId: 71, clientX: 160, clientY: 125, bubbles: true,
  }));
  focused = document.querySelector('.node.focused');
  document.querySelector('[data-action="link-web"]').click();
  const result = document.createElement('div');
  result.id = 'editableMindMapProbe';
  result.dataset.nodes = String(document.querySelectorAll('.node').length);
  result.dataset.editing = String(Boolean(document.querySelector('.node textarea')));
  result.dataset.committed = focused.querySelector('.node-text').textContent;
  result.dataset.color = focused.dataset.color;
  result.dataset.ownColor = focused.dataset.ownColor;
  result.dataset.fontSize = getComputedStyle(focused.querySelector('.node-text')).fontSize;
  result.dataset.rootFontSize = rootFontSize;
  result.dataset.childGenerationFontSize = childGenerationFontSize;
  result.dataset.grandchildGenerationFontSize = grandchildGenerationFontSize;
  result.dataset.randomBranchColor = String(randomBranchColor !== 'default');
  result.dataset.grandchildInherits = String(grandchildInherits);
  result.dataset.firstClickPreservedNode = String(firstClickPreservedNode);
  result.dataset.focusPressed = document.querySelector('[data-action="focus"]')
    .getAttribute('aria-pressed');
  result.dataset.rootDimmed = String(document.querySelector('.node.root').classList.contains('dimmed'));
  result.dataset.resizeHandle = String(Boolean(focused.querySelector('.node-resize-handle')));
  result.dataset.resized = String(Number.parseFloat(focused.style.width) > 300);
  result.dataset.styledDialog = String(document.getElementById('mindMapDialog').open);
  document.getElementById('mindMapDialogCancel').click();
  result.dataset.emptyDisplay = getComputedStyle(document.getElementById('empty')).display;
  result.dataset.zoomed = String(Number(document.getElementById('zoomValue').value) > 100);
  result.dataset.compact = String(Boolean(document.querySelector('.node-more')));
  result.dataset.autosaved = String(autosaveUrl.includes('/api/mind-map/document?'));
  document.body.append(result);
}, 900);
</script>
"""
    completed = browser_file_dom(page.replace("</body>", f"{probe}</body>"), tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert (
        '<div id="editableMindMapProbe" data-nodes="3" data-editing="false" '
        'data-committed="Single-click commit" data-color="blue" data-own-color="blue" '
        'data-font-size="23.5px" data-root-font-size="24px" '
        'data-child-generation-font-size="21px" data-grandchild-generation-font-size="18px" '
        'data-random-branch-color="true" data-grandchild-inherits="true" '
        'data-first-click-preserved-node="true" '
        'data-focus-pressed="true" '
        'data-root-dimmed="true" data-resize-handle="true" data-resized="true" '
        'data-styled-dialog="true" '
        'data-empty-display="none" '
        'data-zoomed="true" data-compact="true" data-autosaved="true"></div>'
        in completed.stdout
    )


@pytest.mark.skipif(CHROME is None, reason="headless Chrome is not installed")
def test_browser_editable_mind_map_confirms_branch_delete(tmp_path: Path) -> None:
    document = empty_mind_map("Planning")
    document["nodes"] = [
        {
            "id": "root",
            "text": "Root",
            "parent_id": None,
            "order": 0,
            "x": 80,
            "y": 80,
            "links": [],
        },
        {
            "id": "child",
            "text": "Child",
            "parent_id": "root",
            "order": 0,
            "x": 410,
            "y": 80,
            "links": [],
        },
    ]
    page, _status = render_editable_mind_map_html(
        {
            "path": "/tmp/planning.mindmap.json",
            "revision": "one",
            "document": document,
        },
        context_id="workspace-one",
        connection_id="connection-one",
    )
    probe = """
<script>
document.querySelector('.node.root').click();
window.dispatchEvent(new MessageEvent('message', {
  origin: window.location.origin,
  data: { type: 'electroboy-mind-map-command', action: 'delete' },
}));
const dialog = document.getElementById('mindMapDialog');
const warningOpen = dialog.open;
const dangerStyle = dialog.classList.contains('danger');
document.getElementById('mindMapDialogSubmit').click();
window.setTimeout(() => {
  const result = document.createElement('div');
  result.id = 'mindMapDeleteProbe';
  result.dataset.warningOpen = String(warningOpen);
  result.dataset.dangerStyle = String(dangerStyle);
  result.dataset.deleted = String(document.querySelectorAll('.node').length === 0);
  result.dataset.dialogClosed = String(!dialog.open);
  document.body.append(result);
}, 0);
</script>
"""
    completed = browser_file_dom(page.replace("</body>", f"{probe}</body>"), tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert (
        '<div id="mindMapDeleteProbe" data-warning-open="true" '
        'data-danger-style="true" data-deleted="true" '
        'data-dialog-closed="true"></div>' in completed.stdout
    )


@pytest.mark.skipif(CHROME is None, reason="headless Chrome is not installed")
def test_browser_editable_mind_map_drag_preserves_and_reparents(tmp_path: Path) -> None:
    document = empty_mind_map("Planning")
    document["nodes"] = [
        {"id": "root", "text": "Root", "parent_id": None, "order": 0,
         "x": 180, "y": 100, "links": []},
        {"id": "child-a", "text": "Child A", "parent_id": "root", "order": 0,
         "side": "right", "x": 470, "y": 100, "links": []},
        {"id": "grandchild", "text": "Grandchild", "parent_id": "child-a",
         "order": 0, "side": "right", "x": 760, "y": 100, "links": []},
        {"id": "child-b", "text": "Child B", "parent_id": "root", "order": 1,
         "side": "right", "x": 470, "y": 260, "links": []},
        {"id": "far-branch", "text": "Far branch", "parent_id": "root",
         "order": 2, "side": "left", "x": -250, "y": 760, "links": []},
        {"id": "free-root", "text": "Free root", "parent_id": None, "order": 1,
         "x": 180, "y": 390, "links": []},
        {"id": "free-root-right", "text": "Free root right", "parent_id": None,
         "order": 2, "x": 20, "y": 390, "links": []},
    ]
    page, _status = render_editable_mind_map_html(
        {"path": "/tmp/planning.mindmap.json", "revision": "one", "document": document},
        context_id="workspace-one",
        connection_id="connection-one",
    )
    probe = """
<script>
window.fetch = async (_url, options) => ({
  ok: true,
  json: async () => ({ revision: 'two', document: JSON.parse(options.body).document }),
});
const canvas = document.getElementById('canvas');
let pointerId = 100;
function node(id) {
  return document.querySelector(`[data-id="${CSS.escape(id)}"]`);
}
function startDrag(id, xRatio = .5) {
  const element = node(id);
  const rect = element.getBoundingClientRect();
  const x = rect.left + rect.width * xRatio;
  const y = rect.top + rect.height / 2;
  pointerId += 1;
  element.dispatchEvent(new PointerEvent('pointerdown', {
    button: 0, pointerId, clientX: x, clientY: y, bubbles: true,
  }));
  return { x, y };
}
function moveDrag(x, y) {
  canvas.dispatchEvent(new PointerEvent('pointermove', {
    button: 0, pointerId, clientX: x, clientY: y, bubbles: true,
  }));
}
function finishDrag(x, y) {
  canvas.dispatchEvent(new PointerEvent('pointerup', {
    button: 0, pointerId, clientX: x, clientY: y, bubbles: true,
  }));
}
function mapHasNoNodeOverlap() {
  const boxes = Array.from(document.querySelectorAll('.node')).map((element) => ({
    left: Number.parseFloat(element.style.left),
    top: Number.parseFloat(element.style.top),
    right: Number.parseFloat(element.style.left) + element.offsetWidth,
    bottom: Number.parseFloat(element.style.top) + element.offsetHeight,
  }));
  return boxes.every((box, index) => boxes.slice(index + 1).every((other) =>
    box.right <= other.left || other.right <= box.left
      || box.bottom <= other.top || other.bottom <= box.top));
}

const localLayoutInitiallyPressed = document.querySelector(
  '[data-action="layout-local"]').getAttribute('aria-pressed') === 'true';
document.querySelector('[data-action="layout-freeform"]').click();
const freeformLayoutPressed = document.querySelector(
  '[data-action="layout-freeform"]').getAttribute('aria-pressed') === 'true';
document.querySelector('[data-action="layout-repack"]').click();
const repackLayoutPressed = document.querySelector(
  '[data-action="layout-repack"]').getAttribute('aria-pressed') === 'true';
document.querySelector('[data-action="layout-local"]').click();
const storedLayoutView = JSON.parse(localStorage.getItem(
  'electroboy:editable-mind-map:/tmp/planning.mindmap.json:view'));
const localLayoutPersisted = storedLayoutView.layoutMode === 'local';
const farBranchPosition = {
  x: node('far-branch').style.left,
  y: node('far-branch').style.top,
};

const childStart = startDrag('child-a');
moveDrag(childStart.x + 35, childStart.y - 80);
finishDrag(childStart.x + 35, childStart.y - 80);
const emptyMoveKeptParent = node('child-a').dataset.parentId === 'root';
const rightBranchReflowed = node('grandchild').dataset.side === 'right'
  && Number.parseFloat(node('grandchild').style.left)
    > Number.parseFloat(node('child-a').style.left);

const childPosition = {
  x: node('child-a').style.left,
  y: node('child-a').style.top,
};
startDrag('child-a');
let targetRect = node('root').getBoundingClientRect();
moveDrag(targetRect.right - 2, targetRect.top + targetRect.height / 2);
const existingChildIntent = node('root').classList.contains('drop-child-right');
finishDrag(targetRect.right - 2, targetRect.top + targetRect.height / 2);
const existingChildNoop = node('child-a').style.left === childPosition.x
  && node('child-a').style.top === childPosition.y
  && node('child-a').dataset.parentId === 'root';

startDrag('child-a');
targetRect = node('root').getBoundingClientRect();
const emptyLeftPosition = targetRect.left - 150;
moveDrag(emptyLeftPosition, targetRect.top + targetRect.height / 2);
const emptyFlipHadNoDropTarget = !node('root').classList.contains('drop-target');
finishDrag(emptyLeftPosition, targetRect.top + targetRect.height / 2);
const rootBranchFlipped = node('child-a').dataset.side === 'left'
  && node('grandchild').dataset.side === 'left'
  && Number.parseFloat(node('root').style.left)
    > Number.parseFloat(node('child-a').style.left)
  && Number.parseFloat(node('child-a').style.left)
    > Number.parseFloat(node('grandchild').style.left);

startDrag('free-root');
targetRect = node('root').getBoundingClientRect();
moveDrag(targetRect.left + 2, targetRect.top + targetRect.height / 2);
const leftChildIntent = node('root').classList.contains('drop-child-left');
finishDrag(targetRect.left + 2, targetRect.top + targetRect.height / 2);
const leftChildAttached = node('free-root').dataset.parentId === 'root'
  && node('free-root').dataset.side === 'left'
  && Number.parseFloat(node('free-root').style.left)
    < Number.parseFloat(node('root').style.left);

startDrag('free-root-right', .95);
targetRect = node('root').getBoundingClientRect();
const pointerOutsideTarget = targetRect.right + 40;
moveDrag(pointerOutsideTarget, targetRect.top + targetRect.height / 2);
const rightChildIntent = node('root').classList.contains('drop-child-right');
finishDrag(pointerOutsideTarget, targetRect.top + targetRect.height / 2);
const rightChildAttached = node('free-root-right').dataset.parentId === 'root'
  && node('free-root-right').dataset.side === 'right'
  && Number.parseFloat(node('free-root-right').style.left)
    > Number.parseFloat(node('root').style.left);

startDrag('child-b');
targetRect = node('child-a').getBoundingClientRect();
moveDrag(targetRect.left + targetRect.width / 2, targetRect.top + 2);
const siblingIntent = node('child-a').classList.contains('drop-sibling-before');
finishDrag(targetRect.left + targetRect.width / 2, targetRect.top + 2);
const siblingInsertedBefore = node('child-b').dataset.parentId === 'root'
  && Number(node('child-b').dataset.order) < Number(node('child-a').dataset.order)
  && Number.parseFloat(node('child-b').style.top)
    < Number.parseFloat(node('child-a').style.top);
const siblingReflowHasNoOverlap = mapHasNoNodeOverlap();
const localLayoutPreservedFarBranch = node('far-branch').style.left
  === farBranchPosition.x && node('far-branch').style.top === farBranchPosition.y;

startDrag('child-b');
targetRect = node('child-a').getBoundingClientRect();
moveDrag(targetRect.left + targetRect.width / 2, targetRect.bottom - 2);
const siblingAfterIntent = node('child-a').classList.contains('drop-sibling-after');
finishDrag(targetRect.left + targetRect.width / 2, targetRect.bottom - 2);
const siblingInsertedAfter = Number(node('child-b').dataset.order)
  > Number(node('child-a').dataset.order)
  && Number.parseFloat(node('child-b').style.top)
    > Number.parseFloat(node('child-a').style.top);
const leftEdgeCoordinates = document.querySelector('[data-target-id="free-root"]')
  .getAttribute('d').match(/-?\\d+(?:\\.\\d+)?/g).map(Number);
const leftConnectorFacesOutward = leftEdgeCoordinates[0] > leftEdgeCoordinates[6];

node('root').click();
canvas.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
const automaticRootChildSide = document.querySelector('.node.focused').dataset.side;
document.querySelector('.node textarea').dispatchEvent(new KeyboardEvent('keydown', {
  key: 'Enter', bubbles: true,
}));

const result = document.createElement('div');
result.id = 'mindMapDragProbe';
result.dataset.localLayoutInitiallyPressed = String(localLayoutInitiallyPressed);
result.dataset.freeformLayoutPressed = String(freeformLayoutPressed);
result.dataset.repackLayoutPressed = String(repackLayoutPressed);
result.dataset.localLayoutPersisted = String(localLayoutPersisted);
result.dataset.localLayoutPreservedFarBranch = String(localLayoutPreservedFarBranch);
result.dataset.emptyMoveKeptParent = String(emptyMoveKeptParent);
result.dataset.rightBranchReflowed = String(rightBranchReflowed);
result.dataset.existingChildIntent = String(existingChildIntent);
result.dataset.existingChildNoop = String(existingChildNoop);
result.dataset.emptyFlipHadNoDropTarget = String(emptyFlipHadNoDropTarget);
result.dataset.rootBranchFlipped = String(rootBranchFlipped);
result.dataset.leftChildIntent = String(leftChildIntent);
result.dataset.leftChildAttached = String(leftChildAttached);
result.dataset.rightChildIntent = String(rightChildIntent);
result.dataset.rightChildAttached = String(rightChildAttached);
result.dataset.nodeBasedDrop = String(pointerOutsideTarget > targetRect.right
  && rightChildIntent);
result.dataset.siblingIntent = String(siblingIntent);
result.dataset.siblingInsertedBefore = String(siblingInsertedBefore);
result.dataset.siblingReflowHasNoOverlap = String(siblingReflowHasNoOverlap);
result.dataset.siblingAfterIntent = String(siblingAfterIntent);
result.dataset.siblingInsertedAfter = String(siblingInsertedAfter);
result.dataset.leftConnectorFacesOutward = String(leftConnectorFacesOutward);
result.dataset.automaticRootChildSide = automaticRootChildSide;
result.dataset.edges = String(document.querySelectorAll('.edge').length);
document.body.append(result);
</script>
"""
    completed = browser_file_dom(page.replace("</body>", f"{probe}</body>"), tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert (
        '<div id="mindMapDragProbe" data-local-layout-initially-pressed="true" '
        'data-freeform-layout-pressed="true" data-repack-layout-pressed="true" '
        'data-local-layout-persisted="true" '
        'data-local-layout-preserved-far-branch="true" '
        'data-empty-move-kept-parent="true" '
        'data-right-branch-reflowed="true" data-existing-child-intent="true" '
        'data-existing-child-noop="true" data-empty-flip-had-no-drop-target="true" '
        'data-root-branch-flipped="true" '
        'data-left-child-intent="true" '
        'data-left-child-attached="true" data-right-child-intent="true" '
        'data-right-child-attached="true" data-node-based-drop="true" '
        'data-sibling-intent="true" '
        'data-sibling-inserted-before="true" data-sibling-reflow-has-no-overlap="true" '
        'data-sibling-after-intent="true" '
        'data-sibling-inserted-after="true" '
        'data-left-connector-faces-outward="true" '
        'data-automatic-root-child-side="right" data-edges="7"></div>'
        in completed.stdout
    )


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
