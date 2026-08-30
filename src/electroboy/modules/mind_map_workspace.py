# ruff: noqa: E501
"""Provider-neutral Mind Map HTML renderer."""

from __future__ import annotations

import html
import json
from http import HTTPStatus

from .agenda_workspace import available_agenda_styles, normalize_agenda_style


def render_mind_map_html(
    payload: dict[str, object],
    *,
    style: object = "default",
) -> tuple[str, HTTPStatus]:
    """Render a normalized source-first provenance graph as an infinite canvas."""

    selected_style = normalize_agenda_style(style)
    view_payload = {
        **payload,
        "style": selected_style,
        "styles": available_agenda_styles(),
    }
    encoded = json.dumps(view_payload, ensure_ascii=False).replace("<", "\\u003c")
    title = html.escape(str(payload.get("title") or "Mind Map"))
    return (
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #252525;
      --muted: #686868;
      --line: #d3d3d3;
      --paper: #fbfbfb;
      --wash: #f1f1f1;
      --accent: #2563eb;
      --accent-soft: rgba(37, 99, 235, 0.12);
      --source: #0f766e;
      --observation: #7c3aed;
      --fact: #c2410c;
      --shadow: 0 16px 44px rgba(0, 0, 0, 0.15);
      --node-shadow: 0 10px 28px rgba(0, 0, 0, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ min-height: 100%; }}
    body {{
      margin: 0;
      overflow: hidden;
      background: var(--wash);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    button {{ font: inherit; }}
    .mind-map-shell {{
      position: fixed;
      inset: 0;
      background:
        linear-gradient(rgba(0, 0, 0, 0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0, 0, 0, 0.04) 1px, transparent 1px),
        var(--wash);
      background-size: 48px 48px;
    }}
    .mind-map-header {{
      position: fixed;
      z-index: 5;
      top: 16px;
      left: 18px;
      display: flex;
      align-items: center;
      gap: 12px;
      pointer-events: none;
    }}
    .mind-map-title {{
      display: grid;
      gap: 2px;
      padding: 10px 12px;
      border: 1px solid rgba(0, 0, 0, 0.08);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.86);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }}
    .mind-map-title strong {{
      font-size: 14px;
      line-height: 1.15;
    }}
    .mind-map-title span {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.2;
    }}
    .mind-map-controls {{
      display: flex;
      align-items: center;
      gap: 8px;
      pointer-events: auto;
    }}
    .mind-map-control {{
      min-height: 34px;
      padding: 7px 10px;
      border: 1px solid rgba(37, 99, 235, 0.25);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.88);
      color: var(--ink);
      box-shadow: var(--node-shadow);
      cursor: pointer;
      font-size: 12px;
      font-weight: 750;
      line-height: 1;
      backdrop-filter: blur(12px);
    }}
    .mind-map-control:hover {{
      border-color: rgba(37, 99, 235, 0.45);
      background: #ffffff;
    }}
    #mindMapViewport {{
      position: fixed;
      inset: 0;
      overflow: hidden;
      cursor: grab;
      user-select: none;
    }}
    #mindMapViewport.is-panning {{ cursor: grabbing; }}
    #mindMapCanvas {{
      position: absolute;
      top: 0;
      left: 0;
      width: 4200px;
      height: 2800px;
      transform-origin: 0 0;
    }}
    #mindMapEdges {{
      position: absolute;
      inset: 0;
      width: 4200px;
      height: 2800px;
      overflow: visible;
      pointer-events: none;
    }}
    #mindMapNodes {{
      position: absolute;
      inset: 0;
    }}
    .mind-map-node {{
      position: absolute;
      box-sizing: border-box;
      width: 300px;
      min-height: 86px;
      padding: 12px;
      border: 1px solid var(--line);
      border-left: 4px solid var(--accent);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.95);
      box-shadow: var(--node-shadow);
      cursor: grab;
      text-align: left;
      touch-action: none;
      transition: transform 180ms ease, opacity 180ms ease, border-color 180ms ease, background 180ms ease, box-shadow 180ms ease;
      user-select: none;
    }}
    .mind-map-node:hover,
    .mind-map-node.is-expanded {{
      transform: translateY(-2px);
      border-color: rgba(37, 99, 235, 0.45);
      background: #ffffff;
    }}
    .mind-map-node:active,
    .mind-map-node.is-dragging {{
      cursor: grabbing;
    }}
    .mind-map-node.is-dragging,
    .mind-map-node.is-dragging:hover {{
      z-index: 5;
      opacity: 0.94;
      transform: none;
    }}
    .mind-map-node[data-kind="source"] {{ border-left-color: var(--source); }}
    .mind-map-node[data-kind="observation"],
    .mind-map-node[data-kind="provider_event"] {{ border-left-color: var(--observation); }}
    .mind-map-node[data-kind="fact"] {{ border-left-color: var(--fact); }}
    .mind-map-node.needs-review {{
      border-color: rgba(37, 99, 235, 0.48);
      box-shadow:
        0 18px 38px rgba(37, 99, 235, 0.16),
        0 0 0 1px rgba(37, 99, 235, 0.12);
    }}
    .mind-map-node__kind {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .mind-map-node__title {{
      margin-top: 8px;
      color: var(--ink);
      font-size: 15px;
      font-weight: 750;
      line-height: 1.22;
    }}
    .mind-map-node__meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 10px;
    }}
    .mind-map-node__summary {{
      margin-top: 10px;
      color: var(--ink);
      font-size: 12px;
      font-weight: 620;
      line-height: 1.35;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }}
    .mind-map-node__fields {{
      display: grid;
      gap: 6px;
      margin-top: 10px;
    }}
    .mind-map-node__field {{
      min-width: 0;
      padding: 7px 8px;
      border: 1px solid rgba(37, 99, 235, 0.14);
      border-radius: 7px;
      background: rgba(37, 99, 235, 0.06);
    }}
    .mind-map-node__field span {{
      display: block;
      color: var(--muted);
      font-size: 10px;
      font-weight: 780;
      text-transform: uppercase;
    }}
    .mind-map-node__field strong {{
      display: block;
      margin-top: 3px;
      color: var(--ink);
      font-size: 12px;
      line-height: 1.35;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
    }}
    .mind-map-node__review {{
      margin-top: 10px;
      padding: 8px 9px;
      border: 1px solid rgba(37, 99, 235, 0.2);
      border-radius: 8px;
      background: rgba(37, 99, 235, 0.08);
      color: #1d4f8d;
      font-size: 12px;
      font-weight: 750;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}
    .mind-map-node__actions {{
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 12px;
    }}
    .mind-map-node__details {{
      display: grid;
      gap: 8px;
      max-height: 260px;
      overflow: auto;
      margin-top: 12px;
      padding-top: 10px;
      border-top: 1px solid var(--line);
      cursor: auto;
      user-select: text;
    }}
    .mind-map-detail {{
      display: grid;
      gap: 3px;
      min-width: 0;
    }}
    .mind-map-detail dt {{
      color: var(--muted);
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .mind-map-detail dd {{
      margin: 0;
      min-width: 0;
      overflow-wrap: anywhere;
      color: var(--ink);
      font-size: 11px;
      line-height: 1.35;
    }}
    .mind-map-detail pre {{
      overflow: auto;
      max-height: 160px;
      margin: 0;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: rgba(0, 0, 0, 0.04);
      color: inherit;
      font: 10px/1.35 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      white-space: pre-wrap;
    }}
    .mind-map-action {{
      min-height: 30px;
      padding: 0 11px;
      border: 1px solid rgba(37, 99, 235, 0.22);
      border-radius: 6px;
      background: rgba(37, 99, 235, 0.08);
      color: var(--accent);
      cursor: pointer;
      font: inherit;
      font-size: 12px;
      font-weight: 800;
    }}
    .mind-map-action:hover {{
      border-color: rgba(37, 99, 235, 0.42);
      background: rgba(37, 99, 235, 0.14);
    }}
    .mind-map-action:disabled {{
      cursor: progress;
      opacity: 0.7;
    }}
    .mind-map-pill {{
      max-width: 100%;
      overflow: visible;
      padding: 3px 7px;
      border: 1px solid rgba(0, 0, 0, 0.08);
      border-radius: 999px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.1;
      overflow-wrap: anywhere;
      text-overflow: clip;
      white-space: normal;
    }}
    .mind-map-empty {{
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      color: var(--muted);
      font-size: 14px;
    }}
    .mind-map-edge {{
      fill: none;
      stroke: rgba(37, 99, 235, 0.34);
      stroke-width: 2.5;
    }}
    .mind-map-style-hud,
    .mind-map-style-month-hud {{
      --ink: #d9fbff;
      --muted: #88bac3;
      --line: rgba(75, 213, 238, 0.34);
      --paper: #071216;
      --wash: #03090c;
      --accent: #2dd4bf;
      --accent-soft: rgba(45, 212, 191, 0.16);
      --source: #22d3ee;
      --observation: #a78bfa;
      --fact: #fb923c;
      --shadow: 0 0 36px rgba(45, 212, 191, 0.16);
      --node-shadow: 0 0 28px rgba(34, 211, 238, 0.18);
    }}
    .mind-map-style-hud .mind-map-shell,
    .mind-map-style-month-hud .mind-map-shell {{
      background:
        radial-gradient(circle at 24% 18%, rgba(45, 212, 191, 0.12), transparent 30%),
        linear-gradient(rgba(45, 212, 191, 0.08) 1px, transparent 1px),
        linear-gradient(90deg, rgba(45, 212, 191, 0.08) 1px, transparent 1px),
        var(--wash);
      background-size: auto, 42px 42px, 42px 42px, auto;
    }}
    .mind-map-style-hud .mind-map-title,
    .mind-map-style-month-hud .mind-map-title,
    .mind-map-style-hud .mind-map-control,
    .mind-map-style-month-hud .mind-map-control,
    .mind-map-style-hud .mind-map-node,
    .mind-map-style-month-hud .mind-map-node {{
      background: rgba(4, 18, 24, 0.88);
      border-color: var(--line);
      box-shadow: var(--node-shadow);
    }}
    .mind-map-style-hud .mind-map-edge,
    .mind-map-style-month-hud .mind-map-edge {{
      stroke: rgba(45, 212, 191, 0.42);
    }}
    .mind-map-style-hud .mind-map-node__field,
    .mind-map-style-month-hud .mind-map-node__field {{
      border-color: rgba(45, 212, 191, 0.22);
      background: rgba(45, 212, 191, 0.08);
    }}
    .mind-map-style-hud .mind-map-node__review,
    .mind-map-style-month-hud .mind-map-node__review {{
      border-color: rgba(139, 216, 255, 0.34);
      background: rgba(59, 130, 246, 0.17);
      color: #d9f2ff;
    }}
    .mind-map-style-hud .mind-map-action,
    .mind-map-style-month-hud .mind-map-action,
    .mind-map-style-hud .mind-map-control,
    .mind-map-style-month-hud .mind-map-control {{
      border-color: rgba(45, 212, 191, 0.34);
      background: rgba(45, 212, 191, 0.12);
      color: #d9fbff;
      box-shadow: 0 0 18px rgba(45, 212, 191, 0.12);
    }}
    .mind-map-style-hud .mind-map-action:hover,
    .mind-map-style-month-hud .mind-map-action:hover,
    .mind-map-style-hud .mind-map-control:hover,
    .mind-map-style-month-hud .mind-map-control:hover {{
      border-color: rgba(45, 212, 191, 0.58);
      background: rgba(45, 212, 191, 0.2);
    }}
    .mind-map-style-command-center {{
      --ink: #202020;
      --muted: #626262;
      --wash: #ececec;
      --accent: #111827;
      --source: #155e75;
      --observation: #7c2d12;
      --fact: #365314;
    }}
    .mind-map-style-timeline-stack {{
      --accent: #9333ea;
      --source: #0f766e;
      --observation: #9333ea;
      --fact: #be123c;
    }}
    .mind-map-style-radar {{
      --accent: #059669;
      --source: #047857;
      --observation: #0e7490;
      --fact: #b45309;
    }}
    .mind-map-style-family-orbit {{
      --accent: #4f46e5;
      --source: #4338ca;
      --observation: #be185d;
      --fact: #ca8a04;
    }}
  </style>
</head>
<body class="mind-map-style-{html.escape(selected_style)}">
  <section class="mind-map-shell" aria-label="Mind map">
    <header class="mind-map-header">
      <div class="mind-map-title">
        <strong>{title}</strong>
        <span>{html.escape(str(payload.get("subtitle") or ""))}</span>
      </div>
      <div class="mind-map-controls">
        <button id="mindMapResetLayout" class="mind-map-control" type="button">
          Reset layout
        </button>
      </div>
    </header>
    <div id="mindMapViewport">
      <div id="mindMapCanvas">
        <svg id="mindMapEdges" aria-hidden="true"></svg>
        <div id="mindMapNodes"></div>
      </div>
    </div>
  </section>
  <script>
    const MIND_MAP_DATA = {encoded};
    const SOURCE_X = 80;
    const SOURCE_Y = 90;
    const COLUMN_GAP = 420;
    const ROOT_GAP = 54;
    const BRANCH_GAP = 42;
    const NODE_WIDTH = 300;
    const NODE_HEIGHT = 116;
    const NODE_CLEARANCE = 36;
    const NODE_SLOT_HEIGHT = 218;
    const CANVAS_BASE_WIDTH = 4200;
    const CANVAS_BASE_HEIGHT = 2800;
    const CANVAS_PADDING = 420;
    const LAYOUT_VERSION = 5;
    const NODE_DRAG_THRESHOLD = 4;
    const viewport = document.getElementById("mindMapViewport");
    const canvas = document.getElementById("mindMapCanvas");
    const nodeLayer = document.getElementById("mindMapNodes");
    const edgeLayer = document.getElementById("mindMapEdges");
    const resetLayoutButton = document.getElementById("mindMapResetLayout");
    const expanded = new Set();
    const manualOffsets = new Map();
    const measuredNodeHeights = new Map();
    const detailOpen = new Set();
    const mindMapDateFormatter = new Intl.DateTimeFormat(undefined, {{
      dateStyle: "medium",
      timeZone: "UTC",
    }});
    const mindMapDateTimeFormatter = new Intl.DateTimeFormat(undefined, {{
      dateStyle: "medium",
      timeStyle: "short",
    }});
    const stateKey = `electroboy:mind-map:${{MIND_MAP_DATA.provider || "default"}}:view`;
    let scale = 1;
    let pan = {{ x: 0, y: 0 }};
    let panStart = null;
    let nodeDrag = null;
    let suppressNextNodeClickFor = null;
    let pendingMeasuredRender = false;

    function restoreView() {{
      try {{
        const stored = JSON.parse(localStorage.getItem(stateKey) || "null");
        if (!stored) return;
        const storedScale = Number(stored.scale);
        const storedX = Number(stored.x);
        const storedY = Number(stored.y);
        scale = Number.isFinite(storedScale)
          ? Math.min(2.4, Math.max(0.35, storedScale))
          : 1;
        pan = {{
          x: Number.isFinite(storedX) ? storedX : 0,
          y: Number.isFinite(storedY) ? storedY : 0,
        }};
        manualOffsets.clear();
        if (Number(stored.layoutVersion) === LAYOUT_VERSION) {{
          Object.entries(stored.nodes || {{}}).forEach(([nodeId, point]) => {{
            const x = Number(point && point.x);
            const y = Number(point && point.y);
            if (Number.isFinite(x) && Number.isFinite(y)) {{
              manualOffsets.set(nodeId, {{ x, y }});
            }}
          }});
        }}
      }} catch (_error) {{
        scale = 1;
        pan = {{ x: 0, y: 0 }};
        manualOffsets.clear();
      }}
    }}

    function saveView() {{
      localStorage.setItem(stateKey, JSON.stringify({{
        layoutVersion: LAYOUT_VERSION,
        scale,
        x: pan.x,
        y: pan.y,
        nodes: Object.fromEntries(
          [...manualOffsets.entries()].map(([nodeId, position]) => [
            nodeId,
            {{ x: position.x, y: position.y }},
          ])
        ),
      }}));
    }}

    function applyTransform() {{
      canvas.style.transform = `translate(${{pan.x}}px, ${{pan.y}}px) scale(${{scale}})`;
    }}

    function allNodes() {{
      return [
        ...(MIND_MAP_DATA.sources || []),
        ...(MIND_MAP_DATA.observations || []),
        ...(MIND_MAP_DATA.provider_events || []),
        ...(MIND_MAP_DATA.facts || []),
      ];
    }}

    const nodeById = new Map(allNodes().map((node) => [node.id, node]));
    const edges = MIND_MAP_DATA.edges || [];
    const outgoing = new Map();
    edges.forEach((edge) => {{
      if (!outgoing.has(edge.from)) outgoing.set(edge.from, []);
      outgoing.get(edge.from).push(edge);
    }});

    function childrenFor(nodeId, kinds = null) {{
      return (outgoing.get(nodeId) || [])
        .map((edge) => nodeById.get(edge.to))
        .filter(Boolean)
        .filter((node) => !kinds || kinds.includes(node.kind));
    }}

    function childKindsFor(node) {{
      if (node.kind === "source") return ["observation", "provider_event"];
      if (node.kind === "observation" || node.kind === "provider_event") return ["fact"];
      if (node.kind === "fact") return ["fact"];
      return [];
    }}

    function totalSpan(spans) {{
      return spans.reduce(
        (total, span, index) => total + span + (index === 0 ? 0 : BRANCH_GAP),
        0
      );
    }}

    function nodeHeight(nodeId) {{
      const measured = Number(measuredNodeHeights.get(nodeId));
      return Number.isFinite(measured) && measured > 0
        ? Math.max(NODE_HEIGHT, measured)
        : NODE_HEIGHT;
    }}

    function nodeSlotHeight(nodeId) {{
      return Math.max(NODE_SLOT_HEIGHT, nodeHeight(nodeId) + NODE_CLEARANCE);
    }}

    function subtreeSpan(node) {{
      const childKinds = childKindsFor(node);
      const ownSpan = nodeSlotHeight(node.id);
      if (!expanded.has(node.id) || childKinds.length === 0) return ownSpan;
      const children = childrenFor(node.id, childKinds);
      if (!children.length) return ownSpan;
      return Math.max(ownSpan, totalSpan(children.map((child) => subtreeSpan(child))));
    }}

    function offsetForNode(nodeId) {{
      return manualOffsets.get(nodeId) || {{ x: 0, y: 0 }};
    }}

    function addOffsets(left, right) {{
      return {{
        x: left.x + right.x,
        y: left.y + right.y,
      }};
    }}

    function placeNode(
      node,
      depth,
      centerY,
      positions,
      visibleIds,
      inheritedOffset = {{ x: 0, y: 0 }}
    ) {{
      const height = nodeHeight(node.id);
      const autoPosition = {{
        x: SOURCE_X + depth * COLUMN_GAP,
        y: Math.max(SOURCE_Y, centerY - height / 2),
      }};
      const effectiveOffset = addOffsets(inheritedOffset, offsetForNode(node.id));
      positions.set(node.id, {{
        x: autoPosition.x + effectiveOffset.x,
        y: autoPosition.y + effectiveOffset.y,
      }});
      visibleIds.add(node.id);

      const childKinds = childKindsFor(node);
      if (!expanded.has(node.id) || childKinds.length === 0) return;
      const children = childrenFor(node.id, childKinds);
      if (!children.length) return;

      const childSpans = children.map((child) => subtreeSpan(child));
      const childrenSpan = totalSpan(childSpans);
      let childCursor = centerY - childrenSpan / 2;
      children.forEach((child, index) => {{
        const childSpan = childSpans[index];
        placeNode(
          child,
          depth + 1,
          childCursor + childSpan / 2,
          positions,
          visibleIds,
          effectiveOffset
        );
        childCursor += childSpan + BRANCH_GAP;
      }});
    }}

    function visibleSubtreeIds(rootNodeId, visibleIds) {{
      const subtreeIds = [];
      const visit = (nodeId) => {{
        if (!visibleIds.has(nodeId)) return;
        subtreeIds.push(nodeId);
        const node = nodeById.get(nodeId);
        if (!node || !expanded.has(nodeId)) return;
        childrenFor(nodeId, childKindsFor(node)).forEach((child) => visit(child.id));
      }};
      visit(rootNodeId);
      return subtreeIds;
    }}

    function shiftSubtree(positions, visibleIds, rootNodeId, dx, dy) {{
      visibleSubtreeIds(rootNodeId, visibleIds).forEach((nodeId) => {{
        const position = positions.get(nodeId);
        if (!position) return;
        position.x += dx;
        position.y += dy;
      }});
    }}

    function resolveColumnCollisions(positions, visibleIds) {{
      const columns = new Map();
      visibleIds.forEach((nodeId) => {{
        const position = positions.get(nodeId);
        if (!position) return;
        const key = String(Math.round(position.x));
        if (!columns.has(key)) columns.set(key, []);
        columns.get(key).push({{ nodeId, position }});
      }});
      columns.forEach((items) => {{
        items.sort((left, right) => left.position.y - right.position.y);
        let nextY = null;
        items.forEach((item) => {{
          if (nextY !== null && item.position.y < nextY) {{
            shiftSubtree(
              positions,
              visibleIds,
              item.nodeId,
              0,
              nextY - item.position.y
            );
          }}
          nextY = item.position.y + nodeHeight(item.nodeId) + BRANCH_GAP;
        }});
      }});
    }}

    function nodesOverlapHorizontally(left, right) {{
      const clearance = NODE_CLEARANCE / 2;
      return (
        left.position.x < right.position.x + NODE_WIDTH + clearance &&
        right.position.x < left.position.x + NODE_WIDTH + clearance
      );
    }}

    function resolveLayoutCollisions(positions, visibleIds) {{
      const items = [...visibleIds]
        .map((nodeId) => ({{ nodeId, position: positions.get(nodeId) }}))
        .filter((item) => item.position);
      for (let pass = 0; pass < items.length; pass += 1) {{
        let changed = false;
        items.sort((left, right) =>
          left.position.y - right.position.y || left.position.x - right.position.x
        );
        for (let index = 0; index < items.length; index += 1) {{
          const current = items[index];
          const currentBottom =
            current.position.y + nodeHeight(current.nodeId) + BRANCH_GAP;
          for (let nextIndex = index + 1; nextIndex < items.length; nextIndex += 1) {{
            const next = items[nextIndex];
            if (!nodesOverlapHorizontally(current, next)) continue;
            if (next.position.y >= currentBottom) continue;
            shiftSubtree(
              positions,
              visibleIds,
              next.nodeId,
              0,
              currentBottom - next.position.y
            );
            changed = true;
          }}
        }}
        if (!changed) break;
      }}
    }}

    function displayedLayout() {{
      const positions = new Map();
      const visibleIds = new Set();
      const sourceNodes = MIND_MAP_DATA.sources || [];
      let cursorY = SOURCE_Y;
      sourceNodes.forEach((source) => {{
        const sourceSpan = subtreeSpan(source);
        placeNode(source, 0, cursorY + sourceSpan / 2, positions, visibleIds);
        cursorY += sourceSpan + ROOT_GAP;
      }});
      resolveColumnCollisions(positions, visibleIds);
      resolveLayoutCollisions(positions, visibleIds);
      return {{
        positions,
        visibleIds,
        visibleEdges: edges.filter((edge) => visibleIds.has(edge.from) && visibleIds.has(edge.to)),
      }};
    }}

    function labelForKind(node) {{
      if (node.kind === "provider_event") return "provider event";
      if (node.kind === "fact") return node.fact_type || "fact";
      if (node.kind === "observation") return "observation";
      return node.kind || "source";
    }}

    function nodeMeta(node) {{
      const values = [];
      if (node.status) values.push(node.status);
      if (node.media_type) values.push(node.media_type);
      if (node.confidence !== null && node.confidence !== undefined) {{
        values.push(`${{Math.round(Number(node.confidence) * 100)}}%`);
      }}
      if (Array.isArray(node.member_labels)) {{
        node.member_labels.slice(0, 3).forEach((label) => values.push(label));
      }}
      if (Number(node.observation_count || 0) > 0) {{
        values.push(`${{node.observation_count}} observations`);
      }}
      if (Number(node.provider_event_count || 0) > 0) {{
        values.push(`${{node.provider_event_count}} events`);
      }}
      if (Number(node.fact_count || 0) > 0) {{
        values.push(`${{node.fact_count}} facts`);
      }}
      return values;
    }}

    function nodeDisplay(node) {{
      return node && node.display && typeof node.display === "object"
        ? node.display
        : {{}};
    }}

    function nodeReview(node) {{
      if (node && node.review && typeof node.review === "object") return node.review;
      const status = String(node?.status || "").toLowerCase();
      if (status === "needs_review") {{
        return {{ message: "Review this item before Better Planned relies on it." }};
      }}
      return null;
    }}

    function mindMapDateFromValue(value) {{
      if (!value) return null;
      const text = String(value);
      const parsed = /^\\d{{4}}-\\d{{2}}-\\d{{2}}$/.test(text)
        ? new Date(`${{text}}T12:00:00Z`)
        : new Date(text);
      return Number.isNaN(parsed.getTime()) ? null : parsed;
    }}

    function nodeDisplayFieldValue(field) {{
      const value = String(field.value || "").trim();
      if (!value) return "";
      if (field.kind === "date") {{
        const parsed = mindMapDateFromValue(value);
        return parsed ? mindMapDateFormatter.format(parsed) : value;
      }}
      if (field.kind === "datetime") {{
        const parsed = mindMapDateFromValue(value);
        return parsed ? mindMapDateTimeFormatter.format(parsed) : value;
      }}
      return value;
    }}

    function nodeDisplayFields(node) {{
      const display = nodeDisplay(node);
      return Array.isArray(display.fields)
        ? display.fields.filter((field) =>
            field && typeof field === "object" && String(field.value || "").trim()
          )
        : [];
    }}

    function createNodeDisplay(node) {{
      const display = nodeDisplay(node);
      const summary = String(display.summary || node.description || node.summary || "").trim();
      const fields = nodeDisplayFields(node);
      const review = nodeReview(node);
      if (!summary && !fields.length && !review) return null;
      const root = document.createElement("div");
      root.className = "mind-map-node__display";
      if (summary) {{
        const summaryNode = document.createElement("div");
        summaryNode.className = "mind-map-node__summary";
        summaryNode.textContent = summary;
        root.append(summaryNode);
      }}
      if (fields.length) {{
        const fieldRoot = document.createElement("div");
        fieldRoot.className = "mind-map-node__fields";
        fields.forEach((field) => {{
          const wrapper = document.createElement("div");
          wrapper.className = "mind-map-node__field";
          const label = document.createElement("span");
          label.textContent = field.label || "Detail";
          const value = document.createElement("strong");
          value.textContent = nodeDisplayFieldValue(field);
          wrapper.append(label, value);
          fieldRoot.append(wrapper);
        }});
        root.append(fieldRoot);
      }}
      if (review) {{
        const reviewNode = document.createElement("div");
        reviewNode.className = "mind-map-node__review";
        reviewNode.textContent = review.message || "Needs review";
        root.append(reviewNode);
      }}
      return root;
    }}

    function nodeActions(node) {{
      const actions = Array.isArray(node.actions)
        ? node.actions.filter((action) =>
        action && typeof action === "object" && String(action.id || "").trim()
      )
        : [];
      if (nodeDetailEntries(node).length) {{
        actions.push({{
          id: "__details",
          label: detailOpen.has(node.id) ? "Hide details" : "Details",
          local: "details",
        }});
      }}
      return actions;
    }}

    function nodeDetailEntries(node) {{
      const details = node.details;
      if (!details || typeof details !== "object" || Array.isArray(details)) return [];
      return Object.entries(details).filter((entry) => entry[1] !== undefined);
    }}

    function detailLabel(value) {{
      return String(value || "")
        .replaceAll("_", " ")
        .replaceAll("-", " ")
        .replace(/\\s+/g, " ")
        .trim();
    }}

    function appendDetailValue(root, value) {{
      if (value && typeof value === "object") {{
        const pre = document.createElement("pre");
        pre.textContent = JSON.stringify(value, null, 2);
        root.append(pre);
        return;
      }}
      root.textContent = value === null ? "null" : String(value);
    }}

    function createNodeDetails(node) {{
      const panel = document.createElement("dl");
      panel.className = "mind-map-node__details";
      panel.addEventListener("pointerdown", (event) => event.stopPropagation());
      panel.addEventListener("click", (event) => event.stopPropagation());
      nodeDetailEntries(node).forEach(([key, value]) => {{
        const wrapper = document.createElement("div");
        wrapper.className = "mind-map-detail";
        const term = document.createElement("dt");
        term.textContent = detailLabel(key);
        const description = document.createElement("dd");
        appendDetailValue(description, value);
        wrapper.append(term, description);
        panel.append(wrapper);
      }});
      return panel;
    }}

    function dispatchMindMapHostAction(node, action) {{
      if (window.parent === window) return;
      window.parent.postMessage({{
        type: "electroboy-mind-map-action",
        provider: MIND_MAP_DATA.provider,
        node_id: node.id,
        node_kind: node.kind || "",
        action_id: action.id,
        payload: action.payload && typeof action.payload === "object"
          ? action.payload
          : {{}},
      }}, window.location.origin);
    }}

    async function invokeNodeAction(node, action) {{
      if (action.local === "details") {{
        toggleNodeDetails(node.id);
        return;
      }}
      if (action.dispatch === "host") {{
        dispatchMindMapHostAction(node, action);
        return;
      }}
    }}

    function toggleNodeDetails(nodeId) {{
      if (detailOpen.has(nodeId)) detailOpen.delete(nodeId);
      else detailOpen.add(nodeId);
      render();
    }}

    function drawEdges(layout) {{
      edgeLayer.replaceChildren();
      layout.visibleEdges.forEach((edge) => {{
        const fromPosition = layout.positions.get(edge.from);
        const toPosition = layout.positions.get(edge.to);
        if (!fromPosition || !toPosition) return;
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("class", "mind-map-edge");
        path.setAttribute("d", edgePath(edge, fromPosition, toPosition));
        edgeLayer.append(path);
      }});
    }}

    function applyRenderedLayout(layout) {{
      resizeCanvasToLayout(layout);
      nodeLayer.querySelectorAll(".mind-map-node").forEach((element) => {{
        const nodeId = element.dataset.nodeId || "";
        const position = layout.positions.get(nodeId);
        if (!position) return;
        element.style.left = `${{position.x}}px`;
        element.style.top = `${{position.y}}px`;
      }});
      drawEdges(layout);
    }}

    function startNodeDrag(event, node, element) {{
      if (event.button !== 0) return;
      if (event.target && event.target.closest(".mind-map-action")) return;
      const startOffset = offsetForNode(node.id);
      event.stopPropagation();
      nodeDrag = {{
        nodeId: node.id,
        pointerId: event.pointerId,
        startClientX: event.clientX,
        startClientY: event.clientY,
        startOffset: {{ x: startOffset.x, y: startOffset.y }},
        element,
        moved: false,
      }};
      element.classList.add("is-dragging");
      try {{
        element.setPointerCapture(event.pointerId);
      }} catch (_error) {{
        // Pointer capture is best effort; window events still finish the drag.
      }}
    }}

    function updateNodeDrag(event) {{
      if (!nodeDrag || event.pointerId !== nodeDrag.pointerId) return;
      const clientDx = event.clientX - nodeDrag.startClientX;
      const clientDy = event.clientY - nodeDrag.startClientY;
      if (!nodeDrag.moved && Math.hypot(clientDx, clientDy) < NODE_DRAG_THRESHOLD) return;
      event.preventDefault();
      nodeDrag.moved = true;
      const nextOffset = {{
        x: nodeDrag.startOffset.x + clientDx / scale,
        y: nodeDrag.startOffset.y + clientDy / scale,
      }};
      manualOffsets.set(nodeDrag.nodeId, nextOffset);
      applyRenderedLayout(displayedLayout());
    }}

    function finishNodeDrag(event) {{
      if (!nodeDrag || event.pointerId !== nodeDrag.pointerId) return;
      const draggedNodeId = nodeDrag.nodeId;
      const element = nodeDrag.element;
      const moved = nodeDrag.moved;
      try {{
        element.releasePointerCapture(event.pointerId);
      }} catch (_error) {{
        // Release is best effort for browsers that lost capture during teardown.
      }}
      element.classList.remove("is-dragging");
      nodeDrag = null;
      if (!moved) return;
      suppressNextNodeClickFor = draggedNodeId;
      saveView();
      render();
    }}

    function toggleNode(node) {{
      if (childrenFor(node.id).length === 0) return;
      if (expanded.has(node.id)) {{
        expanded.delete(node.id);
      }} else {{
        expanded.add(node.id);
      }}
      render();
    }}

    function createNode(node, position) {{
      const element = document.createElement("article");
      const display = nodeDisplay(node);
      const review = nodeReview(node);
      element.className = "mind-map-node";
      element.dataset.nodeId = node.id;
      element.dataset.kind = node.kind || "";
      element.tabIndex = 0;
      if (childrenFor(node.id).length) element.setAttribute("role", "button");
      element.style.left = `${{position.x}}px`;
      element.style.top = `${{position.y}}px`;
      if (expanded.has(node.id)) element.classList.add("is-expanded");
      if (review) element.classList.add("needs-review");
      element.innerHTML = `
        <div class="mind-map-node__kind">
          <span>${{escapeHtml(labelForKind(node))}}</span>
          <span>${{childrenFor(node.id).length ? "+" : ""}}</span>
        </div>
        <div class="mind-map-node__title">${{escapeHtml(display.title || node.title || node.id)}}</div>
        <div class="mind-map-node__meta">
          ${{nodeMeta(node).map((value) => `<span class="mind-map-pill">${{escapeHtml(value)}}</span>`).join("")}}
        </div>
      `;
      const displayBlock = createNodeDisplay(node);
      if (displayBlock) element.append(displayBlock);
      const actions = nodeActions(node);
      if (actions.length) {{
        const actionRow = document.createElement("div");
        actionRow.className = "mind-map-node__actions";
        actions.forEach((action) => {{
          const button = document.createElement("button");
          button.type = "button";
          button.className = "mind-map-action";
          button.textContent = action.label || action.id;
          button.addEventListener("pointerdown", (event) => event.stopPropagation());
          button.addEventListener("click", async (event) => {{
            event.preventDefault();
            event.stopPropagation();
            button.disabled = true;
            try {{
              await invokeNodeAction(node, action);
              if (action.dispatch === "host") button.disabled = false;
            }} catch (error) {{
              window.alert(error.message || "Mind map action failed");
              button.disabled = false;
            }}
          }});
          actionRow.append(button);
        }});
        element.append(actionRow);
      }}
      if (detailOpen.has(node.id)) {{
        element.append(createNodeDetails(node));
      }}
      element.addEventListener("pointerdown", (event) => startNodeDrag(event, node, element));
      element.addEventListener("click", (event) => {{
        if (suppressNextNodeClickFor === node.id) {{
          event.preventDefault();
          suppressNextNodeClickFor = null;
          return;
        }}
        if (event.target && event.target.closest(".mind-map-action")) return;
        toggleNode(node);
      }});
      element.addEventListener("keydown", (event) => {{
        if (!["Enter", " "].includes(event.key)) return;
        if (event.target && event.target.closest(".mind-map-action")) return;
        event.preventDefault();
        toggleNode(node);
      }});
      return element;
    }}

    function edgePath(edge, fromPosition, toPosition) {{
      const startX = fromPosition.x + NODE_WIDTH;
      const startY = fromPosition.y + nodeHeight(edge.from) / 2;
      const endX = toPosition.x;
      const endY = toPosition.y + nodeHeight(edge.to) / 2;
      const midX = startX + (endX - startX) * 0.48;
      return `M ${{startX}} ${{startY}} C ${{midX}} ${{startY}}, ${{midX}} ${{endY}}, ${{endX}} ${{endY}}`;
    }}

    function resizeCanvasToLayout(layout) {{
      let width = CANVAS_BASE_WIDTH;
      let height = CANVAS_BASE_HEIGHT;
      layout.visibleIds.forEach((nodeId) => {{
        const position = layout.positions.get(nodeId);
        if (!position) return;
        width = Math.max(width, Math.ceil(position.x + NODE_WIDTH + CANVAS_PADDING));
        height = Math.max(height, Math.ceil(position.y + nodeHeight(nodeId) + CANVAS_PADDING));
      }});
      canvas.style.width = `${{width}}px`;
      canvas.style.height = `${{height}}px`;
      edgeLayer.style.width = `${{width}}px`;
      edgeLayer.style.height = `${{height}}px`;
      edgeLayer.setAttribute("width", String(width));
      edgeLayer.setAttribute("height", String(height));
    }}

    function measureRenderedNodes() {{
      let changed = false;
      nodeLayer.querySelectorAll(".mind-map-node").forEach((element) => {{
        const nodeId = element.dataset.nodeId || "";
        if (!nodeId) return;
        const height = Math.ceil(element.offsetHeight);
        if (!Number.isFinite(height) || height <= 0) return;
        const previous = Number(measuredNodeHeights.get(nodeId) || 0);
        if (Math.abs(previous - height) > 1) {{
          measuredNodeHeights.set(nodeId, height);
          changed = true;
        }}
      }});
      return changed;
    }}

    function scheduleMeasuredRender() {{
      if (pendingMeasuredRender) return;
      pendingMeasuredRender = true;
      window.requestAnimationFrame(() => {{
        pendingMeasuredRender = false;
        render();
      }});
    }}

    function render() {{
      const layout = displayedLayout();
      nodeLayer.replaceChildren();
      resizeCanvasToLayout(layout);
      drawEdges(layout);
      layout.visibleIds.forEach((nodeId) => {{
        const node = nodeById.get(nodeId);
        const position = layout.positions.get(nodeId);
        if (!node || !position) return;
        nodeLayer.append(createNode(node, position));
      }});
      if (layout.visibleIds.size === 0) {{
        const empty = document.createElement("div");
        empty.className = "mind-map-empty";
        empty.textContent = "No source traceability records";
        nodeLayer.append(empty);
      }}
      if (measureRenderedNodes()) scheduleMeasuredRender();
      return layout;
    }}

    function layoutHasVisibleNode(layout) {{
      for (const nodeId of layout.visibleIds) {{
        const position = layout.positions.get(nodeId);
        if (!position) continue;
        const left = pan.x + position.x * scale;
        const top = pan.y + position.y * scale;
        const right = left + NODE_WIDTH * scale;
        const bottom = top + nodeHeight(nodeId) * scale;
        if (
          right >= 0 &&
          bottom >= 0 &&
          left <= viewport.clientWidth &&
          top <= viewport.clientHeight
        ) {{
          return true;
        }}
      }}
      return layout.visibleIds.size === 0;
    }}

    function fitSourceColumn(layout) {{
      if (layout.visibleIds.size === 0) return;
      const visiblePositions = [...layout.visibleIds]
        .map((nodeId) => layout.positions.get(nodeId))
        .filter(Boolean);
      if (!visiblePositions.length) return;
      const minX = Math.min(...visiblePositions.map((position) => position.x));
      const minY = Math.min(...visiblePositions.map((position) => position.y));
      scale = 1;
      pan = {{
        x: Math.max(24, Math.min(120, viewport.clientWidth * 0.08)) - minX,
        y: Math.max(72, Math.min(120, viewport.clientHeight * 0.1)) - minY,
      }};
      applyTransform();
      saveView();
    }}

    function resetLayout() {{
      manualOffsets.clear();
      scale = 1;
      pan = {{ x: 0, y: 0 }};
      localStorage.removeItem(stateKey);
      applyTransform();
      const layout = render();
      if (layout.visibleIds.size > 0) {{
        fitSourceColumn(layout);
      }} else {{
        saveView();
      }}
    }}

    function zoomAt(pointerX, pointerY, nextScale) {{
      const previousScale = scale;
      const worldX = (pointerX - pan.x) / previousScale;
      const worldY = (pointerY - pan.y) / previousScale;
      scale = Math.min(2.4, Math.max(0.35, nextScale));
      pan.x = pointerX - worldX * scale;
      pan.y = pointerY - worldY * scale;
      applyTransform();
      saveView();
    }}

    function escapeHtml(value) {{
      return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }}

    resetLayoutButton.addEventListener("pointerdown", (event) => {{
      event.stopPropagation();
    }});

    resetLayoutButton.addEventListener("click", (event) => {{
      event.preventDefault();
      event.stopPropagation();
      resetLayout();
    }});

    viewport.addEventListener("wheel", (event) => {{
      event.preventDefault();
      const direction = event.deltaY < 0 ? 1 : -1;
      zoomAt(event.clientX, event.clientY, scale * (direction > 0 ? 1.08 : 0.92));
    }}, {{ passive: false }});

    viewport.addEventListener("mousedown", (event) => {{
      if (event.button !== 1) return;
      event.preventDefault();
      panStart = {{
        pointerX: event.clientX,
        pointerY: event.clientY,
        panX: pan.x,
        panY: pan.y,
      }};
      viewport.classList.add("is-panning");
    }});

    window.addEventListener("mousemove", (event) => {{
      if (!panStart) return;
      pan.x = panStart.panX + event.clientX - panStart.pointerX;
      pan.y = panStart.panY + event.clientY - panStart.pointerY;
      applyTransform();
    }});

    window.addEventListener("mouseup", () => {{
      if (!panStart) return;
      panStart = null;
      viewport.classList.remove("is-panning");
      saveView();
    }});

    viewport.addEventListener("auxclick", (event) => {{
      if (event.button === 1) event.preventDefault();
    }});

    window.addEventListener("pointermove", updateNodeDrag);
    window.addEventListener("pointerup", finishNodeDrag);
    window.addEventListener("pointercancel", finishNodeDrag);

    restoreView();
    applyTransform();
    const initialLayout = render();
    if (!layoutHasVisibleNode(initialLayout)) {{
      fitSourceColumn(initialLayout);
    }}
  </script>
</body>
</html>""",
        HTTPStatus.OK,
    )
