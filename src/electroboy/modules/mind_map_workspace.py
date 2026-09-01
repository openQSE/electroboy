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
    .mind-map-control[aria-pressed="true"] {{
      border-color: var(--accent);
      background: var(--accent);
      color: #ffffff;
    }}
    .mind-map-legend {{
      position: fixed;
      z-index: 6;
      top: 16px;
      right: 18px;
      width: min(300px, calc(100vw - 36px));
      max-height: calc(100vh - 32px);
      overflow: auto;
      padding: 12px;
      border: 1px solid rgba(0, 0, 0, 0.12);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.9);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }}
    .mind-map-legend h2 {{
      margin: 0;
      font-size: 13px;
    }}
    .mind-map-legend__count {{
      margin: 5px 0 10px;
      color: var(--muted);
      font-size: 11px;
    }}
    .mind-map-legend__items {{ display: grid; gap: 5px; }}
    .mind-map-legend__item {{
      display: grid;
      grid-template-columns: 34px 1fr auto;
      align-items: center;
      gap: 8px;
      width: 100%;
      padding: 6px;
      border: 1px solid transparent;
      border-radius: 6px;
      background: transparent;
      color: var(--ink);
      cursor: pointer;
      text-align: left;
      font-size: 11px;
    }}
    .mind-map-legend__item:hover {{ border-color: var(--line); }}
    .mind-map-legend__item[aria-pressed="true"] {{ opacity: 0.42; }}
    .mind-map-legend__swatch {{
      display: block;
      border-top: 3px solid var(--edge-color);
    }}
    .mind-map-legend__item[data-state="uncertain"] .mind-map-legend__swatch {{
      border-top-style: dashed;
    }}
    .mind-map-relationship {{
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px solid var(--line);
      font-size: 11px;
      line-height: 1.4;
    }}
    .mind-map-relationship strong {{ display: block; margin-bottom: 4px; }}
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
      pointer-events: auto;
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
      cursor: pointer;
      pointer-events: stroke;
    }}
    .mind-map-edge[data-state="uncertain"],
    .mind-map-edge[data-state="review"] {{
      stroke-dasharray: 10 7;
    }}
    .mind-map-edge[data-state="historical"],
    .mind-map-edge[data-state="superseded"] {{
      stroke-dasharray: 3 7;
      opacity: 0.58;
    }}
    .mind-map-edge.is-selected {{
      stroke-width: 5;
      filter: drop-shadow(0 0 4px currentColor);
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
    .mind-map-style-hud .mind-map-legend,
    .mind-map-style-month-hud .mind-map-legend {{
      border-color: var(--line);
      background: rgba(4, 18, 24, 0.9);
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
        <button id="mindMapCleanMode" class="mind-map-control" type="button"
                aria-pressed="true">Clean</button>
        <button id="mindMapFullMode" class="mind-map-control" type="button"
                aria-pressed="false">Full</button>
        <button id="mindMapResetLayout" class="mind-map-control" type="button">
          Reset layout
        </button>
      </div>
    </header>
    <aside id="mindMapLegend" class="mind-map-legend" aria-label="Relationship legend">
      <h2>Relationships</h2>
      <div id="mindMapLegendCount" class="mind-map-legend__count"></div>
      <div id="mindMapLegendItems" class="mind-map-legend__items"></div>
      <div id="mindMapRelationship" class="mind-map-relationship" hidden></div>
    </aside>
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
    const SIBLING_GAP = 24;
    const NODE_WIDTH = 300;
    const NODE_HEIGHT = 116;
    const CANVAS_BASE_WIDTH = 4200;
    const CANVAS_BASE_HEIGHT = 2800;
    const CANVAS_PADDING = 420;
    const LAYOUT_VERSION = 7;
    const NODE_DRAG_THRESHOLD = 4;
    const viewport = document.getElementById("mindMapViewport");
    const canvas = document.getElementById("mindMapCanvas");
    const nodeLayer = document.getElementById("mindMapNodes");
    const edgeLayer = document.getElementById("mindMapEdges");
    const resetLayoutButton = document.getElementById("mindMapResetLayout");
    const cleanModeButton = document.getElementById("mindMapCleanMode");
    const fullModeButton = document.getElementById("mindMapFullMode");
    const legendCount = document.getElementById("mindMapLegendCount");
    const legendItems = document.getElementById("mindMapLegendItems");
    const relationshipPanel = document.getElementById("mindMapRelationship");
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
    let graphMode = "clean";
    let selectedEdgeId = null;
    const hiddenFamilies = new Set();
    const graphTelemetryId = (() => {{
      try {{
        return window.crypto.randomUUID();
      }} catch (_error) {{
        return `mind-map-${{Date.now()}}-${{Math.random().toString(16).slice(2)}}`;
      }}
    }})();

    function telemetryEnabled() {{
      let params;
      try {{
        params = new URLSearchParams(window.location.search);
      }} catch (_error) {{
        return false;
      }}
      if (params.get("telemetry_page_id") || params.get("telemetry_tab_id")) {{
        return true;
      }}
      return ["telemetry", "frontend_telemetry", "frontend_debug"].some((key) => {{
        const value = String(params.get(key) || "").trim().toLowerCase();
        return ["1", "true", "yes", "on"].includes(value);
      }});
    }}

    function telemetryParam(key) {{
      try {{
        return new URLSearchParams(window.location.search).get(key) || "";
      }} catch (_error) {{
        return "";
      }}
    }}

    const mindMapTelemetryQueue = [];
    let mindMapTelemetrySending = false;

    async function drainMindMapTelemetryQueue() {{
      if (mindMapTelemetrySending) return;
      mindMapTelemetrySending = true;
      try {{
        while (mindMapTelemetryQueue.length) {{
          const payload = mindMapTelemetryQueue.shift();
          try {{
            await window.fetch("/api/frontend/debug", {{
              method: "POST",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify(payload),
            }});
          }} catch (_error) {{
            // Diagnostic telemetry must never affect Mind Map rendering.
          }}
        }}
      }} finally {{
        mindMapTelemetrySending = false;
        if (mindMapTelemetryQueue.length) {{
          void drainMindMapTelemetryQueue();
        }}
      }}
    }}

    function queueMindMapTelemetry(payload) {{
      mindMapTelemetryQueue.push(payload);
      void drainMindMapTelemetryQueue();
    }}

    function emitMindMapTelemetry(eventName, details = {{}}) {{
      if (!telemetryEnabled()) return;
      const payload = {{
        source: "mind-map-renderer",
        event: eventName,
        created_at: new Date().toISOString(),
        provider: String(MIND_MAP_DATA.provider || ""),
        graph_mode: graphMode,
        graph_instance_id: graphTelemetryId,
        telemetry_page_id: telemetryParam("telemetry_page_id"),
        telemetry_tab_id: telemetryParam("telemetry_tab_id"),
        workspace_id: telemetryParam("workspace_id"),
        context_id: telemetryParam("context_id"),
        connection_id: telemetryParam("connection_id"),
        ...details,
      }};
      queueMindMapTelemetry(payload);
    }}

    function telemetrySlice(values, limit = 120) {{
      return {{
        items: values.slice(0, limit),
        omitted_count: Math.max(0, values.length - limit),
        total_count: values.length,
      }};
    }}

    function emitTelemetryChunks(eventName, values, chunkSize = 60) {{
      const chunkCount = Math.max(1, Math.ceil(values.length / chunkSize));
      for (let chunkIndex = 0; chunkIndex < chunkCount; chunkIndex += 1) {{
        emitMindMapTelemetry(eventName, {{
          chunk_index: chunkIndex,
          chunk_count: chunkCount,
          total_count: values.length,
          items: values.slice(
            chunkIndex * chunkSize,
            (chunkIndex + 1) * chunkSize
          ),
        }});
      }}
    }}

    function telemetryNodeDescriptor(node) {{
      const display = nodeDisplay(node);
      return {{
        id: String(node && node.id || ""),
        label: String(display.title || node && node.title || node && node.id || "")
          .slice(0, 160),
        kind: String(node && node.kind || ""),
        observation_kind: String(node && node.observation_kind || ""),
        fact_type: String(node && node.fact_type || ""),
        status: String(node && node.status || ""),
      }};
    }}

    function telemetryEdgeDescriptor(edge) {{
      return {{
        id: String(edge && edge.id || ""),
        from: String(edge && edge.from || ""),
        to: String(edge && edge.to || ""),
        tree_from: String(edge && (edge.tree_from || edge.from) || ""),
        tree_to: String(edge && (edge.tree_to || edge.to) || ""),
        relationship: String(edge && edge.relationship || ""),
        family: String(edge && edge.family || ""),
        primary: Boolean(edge && edge.primary),
        selected_for_tree: Boolean(edge && primaryEdgeIds.has(edge.id)),
      }};
    }}

    function telemetryNodeLayout(nodeId, layout) {{
      const node = nodeById.get(nodeId) || {{ id: nodeId }};
      const element = nodeLayer.querySelector(
        `[data-node-id="${{CSS.escape(String(nodeId))}}"]`
      );
      const viewportRect = viewport.getBoundingClientRect();
      const rect = element ? element.getBoundingClientRect() : null;
      const position = layout.positions.get(nodeId);
      return {{
        ...telemetryNodeDescriptor(node),
        depth: Number(layout.depthById.get(nodeId) ?? -1),
        rendered: Boolean(element),
        in_viewport: Boolean(rect &&
          rect.right >= viewportRect.left &&
          rect.bottom >= viewportRect.top &&
          rect.left <= viewportRect.right &&
          rect.top <= viewportRect.bottom),
        world_position: position ? {{
          x: Math.round(position.x),
          y: Math.round(position.y),
          height: Math.round(nodeHeight(nodeId)),
        }} : null,
        viewport_position: rect ? {{
          x: Math.round(rect.left - viewportRect.left),
          y: Math.round(rect.top - viewportRect.top),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        }} : null,
      }};
    }}

    function emitGraphTelemetry(layout) {{
      const explicitPrimaryEdges = edges.filter((edge) => edge.primary);
      const selectedEdges = edges.filter((edge) => primaryEdgeIds.has(edge.id));
      const selectedTargets = new Set(
        selectedEdges.map((edge) => edge.tree_to || edge.to)
      );
      const orphanNodes = nodes.filter((node) =>
        node.kind !== "source" && !selectedTargets.has(node.id)
      );
      window.requestAnimationFrame(() => {{
        emitMindMapTelemetry("mind_map.graph.received", {{
          schema_version: Number(MIND_MAP_DATA.schema_version || 0),
          node_counts: {{
            total: nodes.length,
            sources: (MIND_MAP_DATA.sources || []).length,
            observations: (MIND_MAP_DATA.observations || []).length,
            provider_events: (MIND_MAP_DATA.provider_events || []).length,
            facts: (MIND_MAP_DATA.facts || []).length,
          }},
          edge_counts: {{
            received: edges.length,
            explicit_primary: explicitPrimaryEdges.length,
            selected_for_tree: selectedEdges.length,
            dropped_explicit_primary: explicitPrimaryEdges.filter(
              (edge) => !primaryEdgeIds.has(edge.id)
            ).length,
          }},
          orphan_nodes: telemetrySlice(
            orphanNodes.map(telemetryNodeDescriptor)
          ),
          visible_nodes: telemetrySlice(
            [...layout.visibleIds].map((nodeId) =>
              telemetryNodeLayout(nodeId, layout)
            )
          ),
          expanded_node_ids: [...expanded],
          viewport: {{
            width: viewport.clientWidth,
            height: viewport.clientHeight,
            scale,
            pan_x: Math.round(pan.x),
            pan_y: Math.round(pan.y),
          }},
        }});
        emitTelemetryChunks(
          "mind_map.graph.nodes",
          nodes.map(telemetryNodeDescriptor)
        );
        emitTelemetryChunks(
          "mind_map.graph.edges",
          edges.map(telemetryEdgeDescriptor)
        );
      }});
    }}

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
        graphMode = stored.mode === "full" ? "full" : "clean";
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
        mode: graphMode,
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

    const nodes = allNodes();
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const nodeOrder = new Map(nodes.map((node, index) => [node.id, index]));
    const edges = (MIND_MAP_DATA.edges || []).map((edge, index) => ({{
      ...edge,
      id: edge.id || `edge-${{index + 1}}`,
      family: edge.family || "other",
      state: edge.state || "active",
      directed: edge.directed !== false,
    }}));
    const defaultRelationshipStyles = {{
      provenance: {{ label: "Provenance", color: "#4DA3FF" }},
      containment: {{ label: "Containment", color: "#22D3EE" }},
      responsibility: {{ label: "Responsibility", color: "#FF9F43" }},
      fulfillment: {{ label: "Fulfillment", color: "#4ADE80" }},
      assignment: {{ label: "Assignment", color: "#C084FC" }},
      dependency: {{ label: "Dependency", color: "#FACC15" }},
      identity: {{ label: "Identity review", color: "#F472B6" }},
      conflict: {{ label: "Conflict", color: "#FB7185" }},
      historical: {{ label: "Historical", color: "#94A3B8" }},
      other: {{ label: "Other", color: "#4DA3FF" }},
    }};
    const relationshipStyles = {{
      ...defaultRelationshipStyles,
      ...(MIND_MAP_DATA.relationship_styles || {{}}),
    }};
    const primaryEdgeIds = selectPrimaryEdgeIds(edges);
    const treeEdges = edges
      .filter((edge) => primaryEdgeIds.has(edge.id))
      .map((edge) => ({{
        ...edge,
        from: edge.tree_from || edge.from,
        to: edge.tree_to || edge.to,
      }}));
    const outgoing = edgeIndex(treeEdges);

    function edgeIndex(indexedEdges) {{
      const result = new Map();
      indexedEdges.forEach((edge) => {{
        if (!result.has(edge.from)) result.set(edge.from, []);
        result.get(edge.from).push(edge);
      }});
      return result;
    }}

    function selectPrimaryEdgeIds(candidateEdges) {{
      const result = new Set();
      const selectedTargets = new Set();
      candidateEdges.forEach((edge) => {{
        const treeTarget = edge.tree_to || edge.to;
        if (!edge.primary || selectedTargets.has(treeTarget)) return;
        result.add(edge.id);
        selectedTargets.add(treeTarget);
      }});
      candidateEdges.forEach((edge) => {{
        const treeSource = edge.tree_from || edge.from;
        const treeTarget = edge.tree_to || edge.to;
        if (selectedTargets.has(treeTarget)) return;
        const parent = nodeById.get(treeSource);
        const child = nodeById.get(treeTarget);
        if (!parent || !child || !childKindsFor(parent).includes(child.kind)) return;
        result.add(edge.id);
        selectedTargets.add(treeTarget);
      }});
      return result;
    }}

    function childrenFor(nodeId, kinds = null) {{
      return (outgoing.get(nodeId) || [])
        .map((edge) => nodeById.get(edge.to))
        .filter(Boolean)
        .filter((node) => !kinds || kinds.includes(node.kind));
    }}

    function childKindsFor(node) {{
      if (node.kind === "source") return ["observation", "provider_event"];
      if (node.kind === "observation") return ["observation", "fact"];
      if (node.kind === "provider_event") return ["fact"];
      if (node.kind === "fact") return ["fact"];
      return [];
    }}

    function totalSpan(spans) {{
      return spans.reduce(
        (total, span, index) => total + span + (index === 0 ? 0 : SIBLING_GAP),
        0
      );
    }}

    function nodeHeight(nodeId) {{
      const measured = Number(measuredNodeHeights.get(nodeId));
      return Number.isFinite(measured) && measured > 0
        ? measured
        : NODE_HEIGHT;
    }}

    function offsetForNode(nodeId) {{
      return manualOffsets.get(nodeId) || {{ x: 0, y: 0 }};
    }}

    function median(values) {{
      if (!values.length) return null;
      const sorted = [...values].sort((left, right) => left - right);
      const middle = Math.floor(sorted.length / 2);
      return sorted.length % 2
        ? sorted[middle]
        : (sorted[middle - 1] + sorted[middle]) / 2;
    }}

    function collectVisibleGraph() {{
      const visibleIds = new Set();
      const depthById = new Map();
      const parentsById = new Map();
      const queue = [];
      (MIND_MAP_DATA.sources || []).forEach((source) => {{
        if (visibleIds.has(source.id)) return;
        visibleIds.add(source.id);
        depthById.set(source.id, 0);
        queue.push(source.id);
      }});
      for (let cursor = 0; cursor < queue.length; cursor += 1) {{
        const parentId = queue[cursor];
        const parent = nodeById.get(parentId);
        if (!parent || !expanded.has(parentId)) continue;
        const parentDepth = Number(depthById.get(parentId) || 0);
        childrenFor(parentId, childKindsFor(parent)).forEach((child) => {{
          if (visibleIds.has(child.id)) return;
          visibleIds.add(child.id);
          depthById.set(child.id, parentDepth + 1);
          queue.push(child.id);
        }});
      }}
      treeEdges.forEach((edge) => {{
        if (!visibleIds.has(edge.from) || !visibleIds.has(edge.to)) return;
        const parent = nodeById.get(edge.from);
        const child = nodeById.get(edge.to);
        if (!parent || !child || !childKindsFor(parent).includes(child.kind)) return;
        if (!parentsById.has(child.id)) parentsById.set(child.id, new Set());
        parentsById.get(child.id).add(parent.id);
      }});
      return {{ visibleIds, depthById, parentsById }};
    }}

    function positionVisibleNodes(graph) {{
      const positions = new Map();
      const inheritedXOffsets = new Map();
      let sourceCursor = SOURCE_Y;
      (MIND_MAP_DATA.sources || []).forEach((source) => {{
        if (!graph.visibleIds.has(source.id)) return;
        const height = nodeHeight(source.id);
        const offset = offsetForNode(source.id);
        positions.set(source.id, {{
          x: SOURCE_X + offset.x,
          y: sourceCursor + offset.y,
        }});
        inheritedXOffsets.set(source.id, offset.x);
        sourceCursor += height + ROOT_GAP;
      }});

      const maxDepth = Math.max(0, ...graph.depthById.values());
      for (let depth = 1; depth <= maxDepth; depth += 1) {{
        const entries = [...graph.visibleIds]
          .filter((nodeId) => graph.depthById.get(nodeId) === depth)
          .map((nodeId) => {{
            const parentIds = [...(graph.parentsById.get(nodeId) || [])]
              .filter((parentId) => positions.has(parentId));
            const parentCenters = parentIds.map((parentId) => {{
              const parentPosition = positions.get(parentId);
              return parentPosition.y + nodeHeight(parentId) / 2;
            }});
            const parentXOffsets = parentIds
              .map((parentId) => inheritedXOffsets.get(parentId))
              .filter((value) => Number.isFinite(value));
            return {{
              nodeId,
              preferredCenter: median(parentCenters) ?? SOURCE_Y,
              inheritedXOffset: median(parentXOffsets) ?? 0,
              offset: offsetForNode(nodeId),
            }};
          }});
        entries.sort((left, right) =>
          left.preferredCenter - right.preferredCenter ||
          Number(nodeOrder.get(left.nodeId) || 0) -
            Number(nodeOrder.get(right.nodeId) || 0)
        );
        const columnSpan = totalSpan(
          entries.map((entry) => nodeHeight(entry.nodeId))
        );
        const columnCenter = median(
          entries.map((entry) => entry.preferredCenter)
        ) ?? SOURCE_Y;
        let columnCursor = Math.max(SOURCE_Y, columnCenter - columnSpan / 2);
        entries.forEach((entry) => {{
          const effectiveXOffset = entry.inheritedXOffset + entry.offset.x;
          positions.set(entry.nodeId, {{
            x: SOURCE_X + depth * COLUMN_GAP + effectiveXOffset,
            y: columnCursor + entry.offset.y,
          }});
          inheritedXOffsets.set(entry.nodeId, effectiveXOffset);
          columnCursor += nodeHeight(entry.nodeId) + SIBLING_GAP;
        }});
      }}
      return positions;
    }}

    function visibleSubtreeIds(rootNodeId, visibleIds) {{
      const subtreeIds = [];
      const visited = new Set();
      const visit = (nodeId) => {{
        if (!visibleIds.has(nodeId) || visited.has(nodeId)) return;
        visited.add(nodeId);
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

    function nodesOverlapHorizontally(left, right) {{
      return (
        left.position.x < right.position.x + NODE_WIDTH &&
        right.position.x < left.position.x + NODE_WIDTH
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
          const currentBottom = current.position.y + nodeHeight(current.nodeId);
          for (let nextIndex = index + 1; nextIndex < items.length; nextIndex += 1) {{
            const next = items[nextIndex];
            if (!nodesOverlapHorizontally(current, next)) continue;
            if (next.position.y >= currentBottom) continue;
            shiftSubtree(
              positions,
              visibleIds,
              next.nodeId,
              0,
              currentBottom + SIBLING_GAP - next.position.y
            );
            changed = true;
          }}
        }}
        if (!changed) break;
      }}
    }}

    function displayedLayout() {{
      const graph = collectVisibleGraph();
      const positions = positionVisibleNodes(graph);
      resolveLayoutCollisions(positions, graph.visibleIds);
      return {{
        positions,
        visibleIds: graph.visibleIds,
        depthById: graph.depthById,
        parentsById: graph.parentsById,
        visibleEdges: (graphMode === "full" ? edges : treeEdges).filter(
          (edge) => graph.visibleIds.has(edge.from) && graph.visibleIds.has(edge.to)
        ),
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
      const definitions = document.createElementNS("http://www.w3.org/2000/svg", "defs");
      const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
      marker.setAttribute("id", "mindMapArrow");
      marker.setAttribute("viewBox", "0 0 10 10");
      marker.setAttribute("refX", "9");
      marker.setAttribute("refY", "5");
      marker.setAttribute("markerWidth", "7");
      marker.setAttribute("markerHeight", "7");
      marker.setAttribute("orient", "auto-start-reverse");
      const arrow = document.createElementNS("http://www.w3.org/2000/svg", "path");
      arrow.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
      arrow.setAttribute("fill", "context-stroke");
      marker.append(arrow);
      definitions.append(marker);
      edgeLayer.append(definitions);
      layout.visibleEdges
        .filter((edge) => !hiddenFamilies.has(edge.family || "other"))
        .forEach((edge) => {{
        const fromPosition = layout.positions.get(edge.from);
        const toPosition = layout.positions.get(edge.to);
        if (!fromPosition || !toPosition) return;
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("class", "mind-map-edge");
        path.dataset.edgeId = edge.id;
        path.dataset.state = edge.state || "active";
        const style = relationshipStyle(edge);
        path.style.stroke = style.color;
        path.style.color = style.color;
        if (edge.directed !== false) path.setAttribute("marker-end", "url(#mindMapArrow)");
        if (edge.id === selectedEdgeId) path.classList.add("is-selected");
        path.setAttribute("d", edgePath(edge, fromPosition, toPosition));
        path.setAttribute("tabindex", "0");
        path.setAttribute("role", "button");
        path.setAttribute("aria-label", relationshipLabel(edge));
        path.addEventListener("click", (event) => {{
          event.stopPropagation();
          selectedEdgeId = edge.id;
          render();
        }});
        path.addEventListener("keydown", (event) => {{
          if (!["Enter", " "].includes(event.key)) return;
          event.preventDefault();
          selectedEdgeId = edge.id;
          render();
        }});
        edgeLayer.append(path);
      }});
    }}

    function relationshipStyle(edge) {{
      return relationshipStyles[edge.family || "other"] || relationshipStyles.other;
    }}

    function relationshipLabel(edge) {{
      const from = nodeById.get(edge.from);
      const to = nodeById.get(edge.to);
      return `${{from?.title || edge.from}} · ${{edge.relationship || "linked"}} · ${{to?.title || edge.to}}`;
    }}

    function renderLegend(layout) {{
      cleanModeButton.setAttribute("aria-pressed", String(graphMode === "clean"));
      fullModeButton.setAttribute("aria-pressed", String(graphMode === "full"));
      const counts = new Map();
      layout.visibleEdges.forEach((edge) => {{
        const family = edge.family || "other";
        counts.set(family, Number(counts.get(family) || 0) + 1);
      }});
      const visibleCount = layout.visibleEdges.filter(
        (edge) => !hiddenFamilies.has(edge.family || "other")
      ).length;
      legendCount.textContent = `Displaying ${{visibleCount}} of ${{layout.visibleEdges.length}} relationships`;
      legendItems.replaceChildren();
      [...counts.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .forEach(([family, count]) => {{
          const style = relationshipStyles[family] || relationshipStyles.other;
          const button = document.createElement("button");
          button.type = "button";
          button.className = "mind-map-legend__item";
          button.dataset.state = family === "historical" ? "historical" : "active";
          button.setAttribute("aria-pressed", String(hiddenFamilies.has(family)));
          const swatch = document.createElement("span");
          swatch.className = "mind-map-legend__swatch";
          swatch.style.setProperty("--edge-color", style.color);
          const label = document.createElement("span");
          label.textContent = style.label || family;
          const countNode = document.createElement("span");
          countNode.textContent = String(count);
          button.append(swatch, label, countNode);
          button.addEventListener("click", () => {{
            if (hiddenFamilies.has(family)) hiddenFamilies.delete(family);
            else hiddenFamilies.add(family);
            render();
          }});
          legendItems.append(button);
        }});
      const selected = edges.find((edge) => edge.id === selectedEdgeId);
      relationshipPanel.hidden = !selected;
      relationshipPanel.replaceChildren();
      if (selected) {{
        const title = document.createElement("strong");
        title.textContent = selected.relationship || "linked";
        const summary = document.createElement("div");
        summary.textContent = relationshipLabel(selected);
        const details = document.createElement("div");
        const confidence = selected.confidence === null || selected.confidence === undefined
          ? ""
          : ` · ${{Math.round(Number(selected.confidence) * 100)}}% confidence`;
        details.textContent = `${{selected.origin || "provider"}} · ${{selected.state || "active"}}${{confidence}}`;
        relationshipPanel.append(title, summary, details);
      }}
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
      const childEdges = outgoing.get(node.id) || [];
      if (childEdges.length === 0) {{
        emitMindMapTelemetry("mind_map.node.toggle.ignored", {{
          node: telemetryNodeDescriptor(node),
          reason: "no_children",
        }});
        return;
      }}
      const before = collectVisibleGraph();
      const wasExpanded = expanded.has(node.id);
      emitMindMapTelemetry("mind_map.node.toggle.requested", {{
        node: telemetryNodeDescriptor(node),
        action: wasExpanded ? "collapse" : "expand",
        expected_children: telemetrySlice(
          childEdges.map((edge) => ({{
            edge: telemetryEdgeDescriptor(edge),
            node: telemetryNodeDescriptor(nodeById.get(edge.to) || {{ id: edge.to }}),
          }}))
        ),
        visible_node_count_before: before.visibleIds.size,
        expanded_node_ids_before: [...expanded],
      }});
      if (wasExpanded) {{
        expanded.delete(node.id);
      }} else {{
        expanded.add(node.id);
      }}
      const layout = render();
      const addedIds = [...layout.visibleIds].filter(
        (nodeId) => !before.visibleIds.has(nodeId)
      );
      const removedIds = [...before.visibleIds].filter(
        (nodeId) => !layout.visibleIds.has(nodeId)
      );
      window.requestAnimationFrame(() => {{
        emitMindMapTelemetry("mind_map.node.toggle.completed", {{
          node: telemetryNodeDescriptor(node),
          action: wasExpanded ? "collapse" : "expand",
          expanded: expanded.has(node.id),
          added_nodes: telemetrySlice(
            addedIds.map((nodeId) => telemetryNodeLayout(nodeId, layout))
          ),
          removed_nodes: telemetrySlice(
            removedIds.map((nodeId) => telemetryNodeDescriptor(
              nodeById.get(nodeId) || {{ id: nodeId }}
            ))
          ),
          visible_nodes: telemetrySlice(
            [...layout.visibleIds].map((nodeId) =>
              telemetryNodeLayout(nodeId, layout)
            )
          ),
          visible_node_count_after: layout.visibleIds.size,
          expanded_node_ids_after: [...expanded],
          viewport: {{
            width: viewport.clientWidth,
            height: viewport.clientHeight,
            scale,
            pan_x: Math.round(pan.x),
            pan_y: Math.round(pan.y),
          }},
        }});
      }});
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
      renderLegend(layout);
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

    [cleanModeButton, fullModeButton].forEach((button) => {{
      button.addEventListener("pointerdown", (event) => event.stopPropagation());
    }});

    cleanModeButton.addEventListener("click", () => {{
      graphMode = "clean";
      selectedEdgeId = null;
      saveView();
      render();
    }});

    fullModeButton.addEventListener("click", () => {{
      graphMode = "full";
      saveView();
      render();
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
    emitGraphTelemetry(initialLayout);
  </script>
</body>
</html>""",
        HTTPStatus.OK,
    )
