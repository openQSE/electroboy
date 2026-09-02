"""Browser workspace for editable mind-map documents."""

from __future__ import annotations

import json
from http import HTTPStatus
from urllib.parse import urlencode


def render_editable_mind_map_html(
    payload: dict[str, object],
    *,
    context_id: str,
    connection_id: str,
    lease_token: str = "",
) -> tuple[str, HTTPStatus]:
    """Render the document-backed editor without changing provider maps."""

    encoded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    request_parameters = {
        "workspace_id": context_id,
        "context_id": context_id,
        "connection_id": connection_id,
    }
    if lease_token:
        request_parameters["lease_token"] = lease_token
    request_context = urlencode(request_parameters)
    page = _PAGE.replace("__MIND_MAP_DATA__", encoded).replace(
        "__REQUEST_CONTEXT__", request_context
    )
    return page, HTTPStatus.OK


_PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mind Map</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, system-ui, sans-serif; }
    * { box-sizing: border-box; }
    html, body { width: 100%; height: 100%; margin: 0; overflow: hidden; }
    body { background: #111824; color: #e7edf7; }
    button, input, textarea { font: inherit; }
    button { border: 1px solid #46566e; border-radius: 5px; background: #263246;
      color: #e7edf7; padding: .34rem .55rem; cursor: pointer; }
    button:hover:not(:disabled) { background: #33435d; border-color: #6d83a5; }
    button:disabled { opacity: .42; cursor: default; }
    button[aria-pressed="true"] { border-color: #66d9e8; background: #174050;
      box-shadow: inset 0 0 0 1px #66d9e8; color: #e9fbff; }
    .shell { display: grid; grid-template-rows: auto 1fr auto; height: 100%; }
    body.embedded .shell { grid-template-rows: 1fr auto; }
    body.embedded .tools { display: none; }
    .tools { display: flex; gap: .7rem; align-items: stretch; padding: .45rem .55rem;
      border-bottom: 1px solid #344258; background: #182131; overflow-x: auto; }
    .tool-group { display: flex; align-items: center; gap: .3rem; padding-right: .65rem;
      border-right: 1px solid #344258; white-space: nowrap; }
    .tool-group:last-child { border-right: 0; }
    .tool-group strong { color: #93a5be; font-size: .75rem; text-transform: uppercase;
      letter-spacing: .05em; margin-right: .1rem; }
    .workspace { position: relative; min-height: 0; overflow: hidden; }
    .canvas { position: absolute; inset: 0; overflow: hidden; outline: none;
      background-color: #111824;
      background-image: radial-gradient(#344258 1px, transparent 1px);
      background-size: 24px 24px; }
    .viewport { position: absolute; left: 0; top: 0; transform-origin: 0 0;
      width: 1px; height: 1px; }
    .edges { position: absolute; left: 0; top: 0; width: 1px;
      height: 1px; overflow: visible; pointer-events: none; }
    .edge { stroke: #617594; stroke-width: 2.2; fill: none; }
    .node { position: absolute; width: 260px; min-height: 58px; padding: .7rem .8rem;
      border: 2px solid var(--node-border, #536984); border-radius: 10px;
      background: var(--node-background, #202c3e);
      color: #eef4ff; box-shadow: 0 7px 18px #05080d88; cursor: default;
      user-select: none; }
    .node.root { --node-border: #b287e8; --node-background: #302443; }
    .node[data-color="violet"] { --node-border: #bb93ef; --node-background: #4a3566; }
    .node[data-color="blue"] { --node-border: #72b9f4; --node-background: #234f78; }
    .node[data-color="teal"] { --node-border: #69d4d9; --node-background: #24585d; }
    .node[data-color="green"] { --node-border: #86d7a0; --node-background: #2c593d; }
    .node[data-color="amber"] { --node-border: #efc16e; --node-background: #6a4c20; }
    .node[data-color="rose"] { --node-border: #efa0b3; --node-background: #693744; }
    .node.focused { border-color: #64d8ff; box-shadow: 0 0 0 3px #64d8ff4d,
      0 8px 22px #02050a; }
    .node.drop-target { border-color: #70eca9; box-shadow: 0 0 0 4px #70eca955; }
    .node.dimmed { opacity: .22; }
    .node.dragging { opacity: .86; cursor: grabbing; pointer-events: none; }
    .node-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.35;
      font-size: var(--node-font-size, 16px); user-select: text; }
    .node.compact .node-text { display: -webkit-box; -webkit-line-clamp: 3;
      -webkit-box-orient: vertical; overflow: hidden; max-height: 4.05em; }
    .node textarea { width: 100%; min-height: 6rem; resize: both; border: 1px solid #7187a7;
      border-radius: 5px; background: #0f1724; color: #fff; padding: .45rem;
      font-size: var(--node-font-size, 16px); user-select: text; }
    .node-more { display: inline; margin-top: .35rem; padding: 0; border: 0;
      color: #74d8ff; background: none; font-size: .8rem; }
    .node-collapse-count { float: right; color: #ffd886; font-size: .76rem; }
    .node-resize-handle { position: absolute; right: -5px; bottom: -5px;
      width: 14px; height: 14px; border: 2px solid #111824; border-radius: 3px;
      background: #7ddfff; cursor: nwse-resize; opacity: 0; pointer-events: none;
      touch-action: none; }
    .node.focused .node-resize-handle { opacity: 1; pointer-events: auto; }
    .links { display: flex; gap: .3rem; flex-wrap: wrap; margin-top: .45rem; }
    .link { color: #a9dcff; background: #102238; border-color: #365d7e;
      max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
    .empty { position: absolute; inset: 0; display: grid; place-items: center;
      color: #8fa0b8; pointer-events: none; text-align: center; }
    .empty[hidden] { display: none; }
    .overlay { position: absolute; right: 0; top: 0; bottom: 0; width: min(48rem, 52%);
      background: #111824; border-left: 1px solid #46566e; box-shadow: -8px 0 24px #0008;
      display: grid; grid-template-rows: auto 1fr; z-index: 20; }
    .overlay[hidden] { display: none; }
    .overlay header { display: flex; align-items: center; gap: .5rem; padding: .45rem;
      background: #1b2637; border-bottom: 1px solid #344258; }
    .overlay-title { flex: 1; overflow: hidden; text-overflow: ellipsis;
      white-space: nowrap; }
    .overlay iframe { width: 100%; height: 100%; border: 0; background: white; }
    .mind-map-dialog { width: min(680px, calc(100vw - 40px)); max-height: min(720px,
      calc(100vh - 40px)); padding: 0; overflow: hidden; border: 1px solid #46566e;
      border-radius: 8px; background: #182131; color: #e7edf7;
      box-shadow: 0 24px 64px #05080dcc; }
    .mind-map-dialog::backdrop { background: #05080d99; backdrop-filter: blur(2px); }
    .mind-map-dialog.danger { border-color: #a64b56; box-shadow: 0 24px 64px #150306dd; }
    .mind-map-dialog.danger .mind-map-dialog-header { background: #3a1d25;
      border-bottom-color: #733440; }
    .mind-map-dialog.danger .mind-map-dialog-header h2 { color: #ffc4ca; }
    .mind-map-dialog.danger .mind-map-dialog-fields { background: #25151a; }
    .mind-map-dialog.danger .mind-map-dialog-footer { background: #321a20;
      border-top-color: #733440; }
    .mind-map-dialog.danger .mind-map-dialog-submit { border-color: #c45a66;
      background: #7d2633; color: #fff4f5; }
    .mind-map-dialog.danger .mind-map-dialog-submit:hover { background: #963442; }
    .mind-map-dialog-form { display: grid; grid-template-rows: auto minmax(0, 1fr) auto;
      max-height: min(720px, calc(100vh - 40px)); }
    .mind-map-dialog-header, .mind-map-dialog-footer { display: flex; align-items: center;
      justify-content: space-between; gap: 16px; padding: 16px 18px; background: #1b2637; }
    .mind-map-dialog-header { border-bottom: 1px solid #344258; }
    .mind-map-dialog-header h2, .mind-map-dialog-header p { margin: 0; }
    .mind-map-dialog-header h2 { font-size: 16px; font-weight: 600; }
    .mind-map-dialog-header p { margin-top: 3px; color: #9fb0c8; font-size: .82rem; }
    .mind-map-dialog-close { width: 32px; height: 32px; padding: 0;
      border-color: transparent; background: transparent; font-size: 22px; }
    .mind-map-dialog-fields { display: grid; gap: 14px; padding: 18px; overflow: auto; }
    .mind-map-dialog-field { display: grid; gap: 6px; color: #b8c6da; font-size: .82rem; }
    .mind-map-dialog-field input, .mind-map-dialog-field select {
      width: 100%; min-width: 0; padding: 9px 10px; border: 1px solid #46566e;
      border-radius: 5px; outline: none; background: #0f1724; color: #e7edf7; }
    .mind-map-dialog-field input:focus, .mind-map-dialog-field select:focus {
      border-color: #66d9e8; box-shadow: 0 0 0 1px #66d9e8; }
    .mind-map-dialog-path-row { display: grid; grid-template-columns: minmax(0, 1fr) auto;
      gap: 7px; }
    .mind-map-dialog-error { margin: 0; color: #ff9f9f; font-size: .82rem; }
    .mind-map-dialog-footer { justify-content: flex-end; border-top: 1px solid #344258; }
    .mind-map-dialog-submit { border-color: #3f8196; background: #174050; }
    .status { min-height: 1.8rem; padding: .3rem .65rem; border-top: 1px solid #344258;
      background: #182131; color: #9fb0c8; font-size: .82rem; }
    .status.error { color: #ff9f9f; }
    @media (max-width: 760px) {
      .overlay { width: 90%; }
      .tool-group strong { display: none; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <nav class="tools" aria-label="Mind map context tools">
      <section class="tool-group"><strong>File</strong>
        <button data-action="new">New</button><button data-action="open">Open</button>
        <button data-action="save">Save</button><button data-action="save-as">Save As</button>
      </section>
      <section class="tool-group"><strong>Edit</strong>
        <button data-action="undo" title="Undo (Ctrl/Cmd+Z)">↶</button>
        <button data-action="redo" title="Redo (Ctrl/Cmd+Shift+Z)">↷</button>
      </section>
      <section class="tool-group"><strong>Node</strong>
        <button data-action="root">Independent</button><button data-action="child">Child</button>
        <button data-action="sibling">Sibling</button><button data-action="edit">Edit</button>
        <button data-action="delete">Delete</button>
      </section>
      <section class="tool-group"><strong>Color</strong>
        <button data-action="color-default">Inherit</button>
        <button data-action="color-violet">Violet</button>
        <button data-action="color-blue">Blue</button>
        <button data-action="color-teal">Teal</button>
        <button data-action="color-green">Green</button>
        <button data-action="color-amber">Amber</button>
        <button data-action="color-rose">Rose</button>
      </section>
      <section class="tool-group"><strong>Link</strong>
        <button data-action="link-file">File</button><button data-action="link-web">Web</button>
        <button data-action="create-document">Create document</button>
        <button data-action="remove-link">Remove</button>
      </section>
      <section class="tool-group"><strong>View</strong>
        <button data-action="compact">Compact</button><button data-action="expand">Expanded</button>
        <button data-action="zoom-out">−</button><input id="zoomValue" aria-label="Zoom percent"
          title="Zoom percent" value="100" style="width:4.4rem"><button data-action="zoom-in">+</button>
        <button data-action="fit">Fit</button><button data-action="focus">Focus</button>
        <button data-action="collapse">Collapse All</button><button data-action="tidy">Tidy Branch</button>
      </section>
    </nav>
    <section class="workspace">
      <div id="canvas" class="canvas" tabindex="0" role="tree"
           aria-label="Editable mind map canvas">
        <div id="viewport" class="viewport"><svg id="edges" class="edges"></svg><div id="nodes"></div></div>
        <div id="empty" class="empty">Shift+Enter creates an independent node.<br>Tab creates a child of the focused node.</div>
      </div>
      <aside id="overlay" class="overlay" hidden>
        <header><span id="overlayTitle" class="overlay-title"></span>
          <button id="overlayPreview" hidden>Preview</button>
          <button id="overlayEdit" hidden>Edit</button>
          <button id="overlayClose" aria-label="Close linked content">×</button></header>
        <iframe id="overlayFrame" title="Linked content"></iframe>
      </aside>
      <dialog id="mindMapDialog" class="mind-map-dialog">
        <form id="mindMapDialogForm" class="mind-map-dialog-form" method="dialog">
          <header class="mind-map-dialog-header">
            <div><h2 id="mindMapDialogTitle">Mind Map</h2>
              <p id="mindMapDialogDescription"></p></div>
            <button id="mindMapDialogClose" class="mind-map-dialog-close" type="button"
              aria-label="Close">&times;</button>
          </header>
          <section id="mindMapDialogFields" class="mind-map-dialog-fields"></section>
          <footer class="mind-map-dialog-footer">
            <button id="mindMapDialogCancel" type="button">Cancel</button>
            <button id="mindMapDialogSubmit" class="mind-map-dialog-submit"
              type="button">Continue</button>
          </footer>
        </form>
      </dialog>
    </section>
    <footer id="status" class="status">Ready</footer>
  </main>
  <script>
  (() => {
    "use strict";
    const initial = __MIND_MAP_DATA__;
    let requestContext = "__REQUEST_CONTEXT__";
    const canvas = document.getElementById("canvas");
    const viewport = document.getElementById("viewport");
    const nodesLayer = document.getElementById("nodes");
    const edgesLayer = document.getElementById("edges");
    const empty = document.getElementById("empty");
    const status = document.getElementById("status");
    const overlay = document.getElementById("overlay");
    const overlayFrame = document.getElementById("overlayFrame");
    const overlayTitle = document.getElementById("overlayTitle");
    const overlayPreview = document.getElementById("overlayPreview");
    const overlayEdit = document.getElementById("overlayEdit");
    const mindMapDialog = document.getElementById("mindMapDialog");
    const mindMapDialogForm = document.getElementById("mindMapDialogForm");
    const mindMapDialogTitle = document.getElementById("mindMapDialogTitle");
    const mindMapDialogDescription = document.getElementById("mindMapDialogDescription");
    const mindMapDialogFields = document.getElementById("mindMapDialogFields");
    const mindMapDialogSubmit = document.getElementById("mindMapDialogSubmit");
    let documentState = structuredClone(initial.document);
    let revision = initial.revision;
    let path = initial.path;
    let selectedId = null;
    let editingId = null;
    let pan = { x: 80, y: 70 };
    let zoom = 1;
    let compact = true;
    let expanded = new Set();
    let collapsed = new Set();
    let focusMode = false;
    let undoStack = [];
    let redoStack = [];
    let dirty = false;
    let changeVersion = 0;
    let autosaveTimer = null;
    let savePromise = null;
    let pendingEditRender = false;
    let drag = null;
    let overlayLink = null;
    let pendingFilePicker = null;
    const AUTOSAVE_DELAY_MS = 800;
    const ROOT_NODE_FONT_SIZE = 24;
    const NODE_GENERATION_FONT_STEP = 3;
    const MINIMUM_NODE_FONT_SIZE = 14;
    const FONT_CONTROL_STEP = 1;
    const DEFAULT_NODE_WIDTH = 260;
    const DEFAULT_NODE_MIN_HEIGHT = 58;
    const MINIMUM_NODE_WIDTH = 140;
    const MINIMUM_NODE_HEIGHT = 58;
    const BRANCH_COLORS = Object.freeze([
      "violet", "blue", "teal", "green", "amber", "rose",
    ]);
    const stateKey = `electroboy:editable-mind-map:${path}:view`;

    function showDialog(options = {}) {
      mindMapDialogTitle.textContent = options.title || "Mind Map";
      mindMapDialogDescription.textContent = options.description || "";
      mindMapDialogSubmit.textContent = options.submitLabel || "Continue";
      mindMapDialog.classList.toggle("danger", Boolean(options.danger));
      mindMapDialogFields.replaceChildren();
      const controls = new Map();
      (options.fields || []).forEach((field) => {
        const label = document.createElement("label");
        label.className = "mind-map-dialog-field";
        const caption = document.createElement("span");
        caption.textContent = field.label;
        let control;
        if (Array.isArray(field.choices)) {
          control = document.createElement("select");
          field.choices.forEach((choice) => {
            const option = document.createElement("option");
            option.value = choice.value;
            option.textContent = choice.label;
            control.append(option);
          });
        } else {
          control = document.createElement("input");
          control.type = field.type || "text";
          control.placeholder = field.placeholder || "";
        }
        control.name = field.name;
        control.value = field.value || "";
        control.required = Boolean(field.required);
        controls.set(field.name, control);
        label.append(caption);
        if (field.browseMode) {
          const row = document.createElement("div");
          row.className = "mind-map-dialog-path-row";
          const browse = document.createElement("button");
          browse.type = "button";
          browse.textContent = "Browse…";
          browse.addEventListener("click", async () => {
            const selected = await chooseFile(field.browseMode);
            if (selected) { control.value = selected; control.focus(); }
          });
          row.append(control, browse);
          label.append(row);
        } else {
          label.append(control);
        }
        mindMapDialogFields.append(label);
      });
      const error = document.createElement("p");
      error.className = "mind-map-dialog-error";
      error.hidden = true;
      mindMapDialogFields.append(error);
      return new Promise((resolve) => {
        let finished = false;
        const finish = (value) => {
          if (finished) return;
          finished = true;
          if (mindMapDialog.open) mindMapDialog.close();
          resolve(value);
        };
        document.getElementById("mindMapDialogClose").onclick = () => finish(null);
        document.getElementById("mindMapDialogCancel").onclick = () => finish(null);
        mindMapDialog.oncancel = (event) => { event.preventDefault(); finish(null); };
        const submit = () => {
          const values = {};
          for (const [name, control] of controls) {
            const value = String(control.value || "").trim();
            if (control.required && !value) {
              error.textContent = `${control.previousElementSibling?.textContent || name} is required.`;
              error.hidden = false;
              control.focus();
              return;
            }
            values[name] = value;
          }
          finish(values);
        };
        mindMapDialogSubmit.onclick = submit;
        mindMapDialogForm.onsubmit = (event) => {
          event.preventDefault();
          submit();
        };
        mindMapDialog.showModal();
        const first = controls.values().next().value;
        if (first) first.focus(); else mindMapDialogSubmit.focus();
      });
    }

    async function confirmDialog(
      title, description, submitLabel = "Continue", danger = false,
    ) {
      return Boolean(await showDialog({ title, description, submitLabel, danger }));
    }

    function mapDirectory() {
      const separator = path.lastIndexOf("/");
      return separator > 0 ? path.slice(0, separator) : "/";
    }

    function finishFilePicker(value) {
      if (!pendingFilePicker) return;
      const pending = pendingFilePicker;
      pendingFilePicker = null;
      window.clearInterval(pending.timer);
      pending.resolve(value);
    }

    function chooseFile(mode) {
      if (pendingFilePicker) {
        pendingFilePicker.popup?.focus();
        return Promise.resolve(null);
      }
      const parameters = new URLSearchParams({ path: mapDirectory(), mode });
      const popup = window.open(
        `/file-browser?${parameters.toString()}`,
        `electroboy-mind-map-${mode}`,
        "popup=yes,width=980,height=720,menubar=no,toolbar=no,location=no,"
          + "status=no,scrollbars=yes,resizable=yes",
      );
      if (!popup) {
        setStatus("File picker was blocked by the browser.", true);
        return Promise.resolve(null);
      }
      return new Promise((resolve) => {
        const timer = window.setInterval(() => {
          if (popup.closed) finishFilePicker(null);
        }, 300);
        pendingFilePicker = { mode, popup, resolve, timer };
      });
    }

    function nodeById(id) { return documentState.nodes.find((node) => node.id === id); }
    function childrenOf(parentId) {
      return documentState.nodes.filter((node) => node.parent_id === parentId)
        .sort((a, b) => a.order - b.order);
    }
    function nodeDepth(node) {
      let depth = 1; let current = node;
      while (current && current.parent_id) { depth += 1; current = nodeById(current.parent_id); }
      return depth;
    }
    function nodeFontSize(node) {
      const stored = Number(node?.font_size);
      if (node?.font_size_mode === "custom" && Number.isFinite(stored) && stored > 0) {
        return stored;
      }
      const parent = node?.parent_id ? nodeById(node.parent_id) : null;
      return parent
        ? Math.max(MINIMUM_NODE_FONT_SIZE,
            nodeFontSize(parent) - NODE_GENERATION_FONT_STEP)
        : ROOT_NODE_FONT_SIZE;
    }
    function initialNodeFontSize(kind, selected) {
      if (kind === "root" || !selected) return ROOT_NODE_FONT_SIZE;
      if (kind === "sibling") return nodeFontSize(selected);
      return Math.max(MINIMUM_NODE_FONT_SIZE,
        nodeFontSize(selected) - NODE_GENERATION_FONT_STEP);
    }
    function nodeWidth(node) {
      const width = Number(node?.width);
      return Number.isFinite(width) && width > 0 ? width : DEFAULT_NODE_WIDTH;
    }
    function nodeMinHeight(node) {
      const height = Number(node?.min_height);
      return Number.isFinite(height) && height > 0
        ? height : DEFAULT_NODE_MIN_HEIGHT;
    }
    function resolvedNodeColor(node) {
      let current = node;
      while (current) {
        const color = current.color || "default";
        if (color !== "default") return color;
        current = current.parent_id ? nodeById(current.parent_id) : null;
      }
      return "default";
    }
    function initialNodeColor(parentId) {
      const parent = nodeById(parentId);
      if (!parent || parent.parent_id !== null) return "default";
      const used = new Set(childrenOf(parentId).map((node) => node.color)
        .filter((color) => BRANCH_COLORS.includes(color)));
      const available = BRANCH_COLORS.filter((color) => !used.has(color));
      const choices = available.length ? available : BRANCH_COLORS;
      return choices[Math.floor(Math.random() * choices.length)];
    }
    function setStatus(message, error = false) {
      status.textContent = message; status.classList.toggle("error", error);
    }
    function saveView() {
      try {
        localStorage.setItem(stateKey, JSON.stringify({ pan, zoom, selectedId, compact,
          expanded: Array.from(expanded), collapsed: Array.from(collapsed), focusMode }));
      } catch (_error) { /* View persistence is optional. */ }
    }
    function restoreView() {
      try {
        const stored = JSON.parse(localStorage.getItem(stateKey) || "null");
        if (!stored) return;
        if (stored.pan) pan = stored.pan;
        if (Number.isFinite(stored.zoom)) zoom = Math.min(4, Math.max(.15, stored.zoom));
        if (nodeById(stored.selectedId)) selectedId = stored.selectedId;
        compact = stored.compact !== false;
        expanded = new Set(Array.isArray(stored.expanded) ? stored.expanded : []);
        collapsed = new Set(Array.isArray(stored.collapsed) ? stored.collapsed : []);
        focusMode = Boolean(stored.focusMode);
      } catch (_error) { /* Ignore invalid per-browser view state. */ }
    }
    function snapshot() { return JSON.stringify(documentState); }
    function checkpoint() {
      undoStack.push(snapshot());
      if (undoStack.length > 200) undoStack.shift();
      redoStack = [];
    }
    function scheduleAutosave() {
      if (autosaveTimer) window.clearTimeout(autosaveTimer);
      autosaveTimer = window.setTimeout(() => {
        autosaveTimer = null;
        if (editingId) { scheduleAutosave(); return; }
        save({ automatic: true }).catch((error) => setStatus(error.message, true));
      }, AUTOSAVE_DELAY_MS);
    }
    function markDirty() {
      changeVersion += 1;
      dirty = true;
      scheduleAutosave();
    }
    function restoreSnapshot(serialized) {
      documentState = JSON.parse(serialized); editingId = null; markDirty(); render();
    }
    function undo() {
      if (!undoStack.length) return;
      redoStack.push(snapshot()); restoreSnapshot(undoStack.pop());
    }
    function redo() {
      if (!redoStack.length) return;
      undoStack.push(snapshot()); restoreSnapshot(redoStack.pop());
    }
    function nextId() {
      return `node-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
    }
    function nextPosition(parent) {
      if (!parent) {
        const roots = childrenOf(null);
        return { x: 80 + (roots.length % 3) * 310, y: 80 + Math.floor(roots.length / 3) * 150 };
      }
      const siblings = childrenOf(parent.id);
      return { x: parent.x + nodeWidth(parent) + 70,
        y: parent.y + siblings.length * 110 };
    }
    function addNode(kind) {
      const selected = nodeById(selectedId);
      if ((kind === "child" || kind === "sibling") && !selected) {
        setStatus("Focus a node first.", true); return;
      }
      checkpoint();
      const parentId = kind === "child" ? selected.id
        : kind === "sibling" ? selected.parent_id : null;
      const positionParent = kind === "child" ? selected
        : kind === "sibling" && selected.parent_id ? nodeById(selected.parent_id) : null;
      const position = nextPosition(positionParent);
      if (kind === "sibling") { position.x = selected.x; position.y = selected.y + 110; }
      if (kind === "root" && selected) { position.x = selected.x; position.y = selected.y + 130; }
      const node = { id: nextId(), text: "New idea", parent_id: parentId,
        order: childrenOf(parentId).length, x: position.x, y: position.y,
        color: initialNodeColor(parentId), font_size: initialNodeFontSize(kind, selected),
        font_size_mode: "auto",
        width: DEFAULT_NODE_WIDTH, min_height: DEFAULT_NODE_MIN_HEIGHT, links: [] };
      documentState.nodes.push(node); selectedId = node.id; editingId = node.id; markDirty();
      render();
    }
    function descendants(id, result = new Set()) {
      childrenOf(id).forEach((child) => { result.add(child.id); descendants(child.id, result); });
      return result;
    }
    function hiddenNodeIds() {
      const hidden = new Set();
      collapsed.forEach((id) => descendants(id, hidden));
      return hidden;
    }
    function focusNodeIds() {
      if (!focusMode || !selectedId) return null;
      return new Set([selectedId]);
    }
    async function deleteSelected() {
      if (!selectedId) return;
      const node = nodeById(selectedId);
      if (!node) return;
      const childCount = descendants(node.id).size;
      if (childCount && !await confirmDialog(
        "Delete branch?",
        `Delete this node and ${childCount} descendant(s)? This can be undone.`,
        "Delete",
        true,
      )) return;
      checkpoint();
      const removed = descendants(node.id); removed.add(node.id);
      documentState.nodes = documentState.nodes.filter((candidate) => !removed.has(candidate.id));
      documentState.relationships = documentState.relationships.filter(
        (edge) => !removed.has(edge.source) && !removed.has(edge.target));
      selectedId = node.parent_id && nodeById(node.parent_id) ? node.parent_id : null;
      editingId = null; markDirty(); render();
    }
    function beginEdit() {
      if (!selectedId) return;
      editingId = selectedId; render();
    }
    function commitEdit(nodeId, textarea, options = {}) {
      const node = nodeById(nodeId);
      if (!node) return;
      const value = textarea.value;
      if (value !== node.text) { checkpoint(); node.text = value; markDirty(); }
      if (editingId === nodeId) editingId = null;
      if (options.render !== false) render();
      if (options.focus !== false) canvas.focus();
    }
    function setNodeColor(color) {
      const node = nodeById(selectedId);
      if (!node || node.color === color) return;
      checkpoint(); node.color = color; markDirty(); render();
    }
    function setNodeFontSize(value) {
      const node = nodeById(selectedId);
      const fontSize = Number(value);
      if (!node || !Number.isFinite(fontSize) || fontSize <= 0) return;
      const normalized = Math.round(fontSize * 100) / 100;
      if (node.font_size_mode === "custom" && nodeFontSize(node) === normalized) return;
      checkpoint(); node.font_size = normalized; node.font_size_mode = "custom";
      markDirty(); render();
    }
    function adjustNodeFontSize(delta) {
      const node = nodeById(selectedId);
      if (!node) return;
      setNodeFontSize(Math.max(.1,
        nodeFontSize(node) + delta));
    }
    function useAutomaticNodeFontSize() {
      const node = nodeById(selectedId);
      if (!node || node.font_size_mode !== "custom") return;
      checkpoint(); node.font_size_mode = "auto"; delete node.font_size;
      markDirty(); render();
    }
    function transform() {
      viewport.style.transform = `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`;
      document.getElementById("zoomValue").value = String(Math.round(zoom * 100));
      saveView();
    }
    function renderEdges(visibleIds = new Set(documentState.nodes.map((node) => node.id))) {
      edgesLayer.replaceChildren();
      const add = (source, target, extra = false) => {
        if (!source || !target) return;
        const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
        const sourceElement = nodesLayer.querySelector(
          `[data-id="${CSS.escape(source.id)}"]`);
        const targetElement = nodesLayer.querySelector(
          `[data-id="${CSS.escape(target.id)}"]`);
        const sourceWidth = sourceElement?.offsetWidth || nodeWidth(source);
        const sourceHeight = sourceElement?.offsetHeight || nodeMinHeight(source);
        const targetHeight = targetElement?.offsetHeight || nodeMinHeight(target);
        const sx = source.x + sourceWidth; const sy = source.y + sourceHeight / 2;
        const tx = target.x; const ty = target.y + targetHeight / 2;
        const bend = Math.max(45, Math.abs(tx - sx) * .45);
        line.setAttribute("d", `M ${sx} ${sy} C ${sx + bend} ${sy}, ${tx - bend} ${ty}, ${tx} ${ty}`);
        line.setAttribute("class", "edge");
        if (extra) line.setAttribute("stroke-dasharray", "7 5");
        edgesLayer.append(line);
      };
      documentState.nodes.forEach((node) => {
        if (visibleIds.has(node.id) && visibleIds.has(node.parent_id)) add(nodeById(node.parent_id), node);
      });
      documentState.relationships.forEach((edge) => {
        if (visibleIds.has(edge.source) && visibleIds.has(edge.target)) add(nodeById(edge.source), nodeById(edge.target), true);
      });
    }
    function resolvedFileTarget(target) {
      if (target.startsWith("/")) return target;
      const base = path.slice(0, path.lastIndexOf("/") + 1);
      return decodeURIComponent(new URL(target, `file://${base}`).pathname);
    }
    function showOverlay(mode = "preview", create = false) {
      if (!overlayLink) return;
      const link = overlayLink;
      if (link.type === "url" || link.type === "web") {
        const parameters = new URLSearchParams(requestContext);
        parameters.set("url", link.target);
        overlayFrame.src = `/artifacts/external-link?${parameters}`;
      } else {
        const parameters = new URLSearchParams(requestContext);
        const resolvedTarget = resolvedFileTarget(link.target);
        parameters.set("path", resolvedTarget);
        if (/\.md$/i.test(link.target)) {
          parameters.set("title", link.label || link.target);
          if (mode === "edit") {
            parameters.set("artifact", "document");
            if (create) parameters.set("create", "1");
            overlayFrame.src = `/artifacts/edit?${parameters}`;
          } else {
            parameters.set("embed", "1");
            if (create) parameters.set("create", "1");
            overlayFrame.src = `/artifacts/document?${parameters}`;
          }
        } else {
          overlayFrame.src = `/api/mind-map/link-content?${parameters}`;
        }
      }
      const editable = link.type !== "url" && link.type !== "web" && /\.md$/i.test(link.target);
      overlayPreview.hidden = !editable || mode === "preview";
      overlayEdit.hidden = !editable || mode === "edit";
      overlayTitle.textContent = link.label || link.target; overlay.hidden = false;
    }
    function openLink(link) {
      overlayLink = link; showOverlay("preview");
    }
    function updateControlsAndState() {
      document.querySelector('[data-action="undo"]').disabled = !undoStack.length;
      document.querySelector('[data-action="redo"]').disabled = !redoStack.length;
      document.querySelectorAll('[data-action="child"], [data-action="sibling"], [data-action="edit"], [data-action="delete"], [data-action^="color-"], [data-action^="link-"], [data-action="create-document"], [data-action="remove-link"], [data-action="focus"]')
        .forEach((button) => { button.disabled = !selectedId; });
      document.querySelector('[data-action="focus"]')
        .setAttribute("aria-pressed", String(Boolean(focusMode && selectedId)));
      document.title = `${dirty ? "*" : ""}${documentState.title} — Mind Map`;
      if (dirty && !status.classList.contains("error")) setStatus("Unsaved changes");
      if (window.parent !== window) window.parent.postMessage({
        type: "electroboy-mind-map-state", selected: Boolean(selectedId),
        selectedColor: nodeById(selectedId)?.color || "default",
        selectedResolvedColor: selectedId ? resolvedNodeColor(nodeById(selectedId)) : "default",
        selectedFontSize: selectedId ? nodeFontSize(nodeById(selectedId)) : ROOT_NODE_FONT_SIZE,
        selectedFontSizeMode: nodeById(selectedId)?.font_size_mode || "auto",
        focusMode: Boolean(focusMode && selectedId),
        mapPath: path,
        canUndo: Boolean(undoStack.length), canRedo: Boolean(redoStack.length), dirty,
      }, window.location.origin);
    }
    function updateSelectionPresentation() {
      const focusedNodes = focusNodeIds();
      nodesLayer.querySelectorAll(".node").forEach((element) => {
        const selected = element.dataset.id === selectedId;
        element.classList.toggle("focused", selected);
        element.classList.toggle("dimmed",
          Boolean(focusedNodes && !focusedNodes.has(element.dataset.id)));
        element.setAttribute("aria-selected", String(selected));
      });
      updateControlsAndState();
      saveView();
    }
    function renderNode(node) {
      const element = document.createElement("article");
      element.className = `node${node.parent_id === null ? " root" : ""}${node.id === selectedId ? " focused" : ""}`;
      const focusedBranch = focusNodeIds();
      if (focusedBranch && !focusedBranch.has(node.id)) element.classList.add("dimmed");
      element.dataset.id = node.id; element.style.left = `${node.x}px`; element.style.top = `${node.y}px`;
      element.dataset.color = resolvedNodeColor(node);
      element.dataset.ownColor = node.color || "default";
      element.style.setProperty("--node-font-size",
        `${nodeFontSize(node)}px`);
      element.style.width = `${nodeWidth(node)}px`;
      element.style.minHeight = `${nodeMinHeight(node)}px`;
      element.setAttribute("role", "treeitem");
      element.setAttribute("aria-level", String(nodeDepth(node)));
      element.setAttribute("aria-selected", String(node.id === selectedId));
      element.setAttribute("aria-label", node.text || "Empty mind map node");
      if (childrenOf(node.id).length) {
        element.setAttribute("aria-expanded", String(!collapsed.has(node.id)));
      }
      if (editingId === node.id) {
        const editor = document.createElement("textarea"); editor.value = node.text;
        editor.addEventListener("pointerdown", (event) => event.stopPropagation());
        editor.addEventListener("click", (event) => event.stopPropagation());
        editor.addEventListener("keydown", (event) => {
          if (event.key === "Escape") { event.stopPropagation(); editingId = null; render(); canvas.focus(); }
          else if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
            event.preventDefault(); event.stopPropagation(); commitEdit(node.id, editor);
          }
        });
        editor.addEventListener("blur", () => editingId === node.id &&
          commitEdit(node.id, editor, { focus: false }));
        element.append(editor); queueMicrotask(() => { editor.focus(); editor.select(); });
      } else {
        const text = document.createElement("div"); text.className = "node-text"; text.textContent = node.text || "(empty)";
        const isLong = node.text.length > 80 || node.text.split("\n").length > 3;
        const isExpanded = expanded.has(node.id);
        if (compact && isLong && !isExpanded) element.classList.add("compact");
        element.append(text);
        if (compact && isLong) {
          const more = document.createElement("button"); more.className = "node-more";
          more.textContent = isExpanded ? "… less" : "… more";
          more.addEventListener("click", (event) => { event.stopPropagation();
            isExpanded ? expanded.delete(node.id) : expanded.add(node.id); render(); });
          element.append(more);
        }
        if (node.links.length) {
          const links = document.createElement("div"); links.className = "links";
          node.links.forEach((link) => { const button = document.createElement("button");
            button.className = "link"; button.textContent = link.label || link.target;
            button.title = link.target; button.addEventListener("click", (event) => {
              event.stopPropagation(); openLink(link); }); links.append(button); });
          element.append(links);
        }
        if (collapsed.has(node.id)) {
          const count = document.createElement("span"); count.className = "node-collapse-count";
          count.textContent = `${descendants(node.id).size} hidden`; element.append(count);
        }
      }
      const resizeHandle = document.createElement("span");
      resizeHandle.className = "node-resize-handle";
      resizeHandle.title = "Resize node";
      resizeHandle.setAttribute("aria-hidden", "true");
      resizeHandle.addEventListener("dblclick", (event) => event.stopPropagation());
      resizeHandle.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || editingId) return;
        event.preventDefault(); event.stopPropagation(); selectedId = node.id;
        updateSelectionPresentation();
        const descendantPositions = new Map(Array.from(descendants(node.id)).map(
          (id) => { const item = nodeById(id); return [id, { x: item.x, y: item.y }]; }));
        const followingIds = new Set();
        childrenOf(node.parent_id).filter((item) => item.order > node.order)
          .forEach((item) => {
            followingIds.add(item.id);
            descendants(item.id, followingIds);
          });
        const followingPositions = new Map(Array.from(followingIds).map(
          (id) => { const item = nodeById(id); return [id, { x: item.x, y: item.y }]; }));
        drag = { type: "resize", id: node.id, x: event.clientX, y: event.clientY,
          startWidth: element.offsetWidth, startHeight: element.offsetHeight,
          descendantPositions, followingPositions, before: snapshot(), moved: false };
        try { resizeHandle.setPointerCapture(event.pointerId); }
        catch (_error) { /* Synthetic and legacy pointer events may not capture. */ }
      });
      element.append(resizeHandle);
      element.addEventListener("click", (event) => {
        if (event.target.closest("button,textarea,.node-resize-handle")) return;
        selectedId = node.id; updateSelectionPresentation(); canvas.focus();
      });
      element.addEventListener("dblclick", (event) => { event.stopPropagation(); selectedId = node.id; beginEdit(); });
      element.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || editingId || event.target.closest("button,textarea")) return;
        event.stopPropagation(); selectedId = node.id;
        updateSelectionPresentation();
        drag = { type: "node", id: node.id, x: event.clientX, y: event.clientY,
          startX: node.x, startY: node.y, before: snapshot(), moved: false };
        element.setPointerCapture(event.pointerId);
      });
      return element;
    }
    function render() {
      pendingEditRender = false;
      const hidden = hiddenNodeIds();
      const visible = documentState.nodes.filter((node) => !hidden.has(node.id));
      const visibleIds = new Set(visible.map((node) => node.id));
      nodesLayer.replaceChildren(...visible.map(renderNode));
      renderEdges(visibleIds); empty.hidden = documentState.nodes.length > 0; transform();
      updateControlsAndState();
    }
    function adjustZoom(next, originX = canvas.clientWidth / 2, originY = canvas.clientHeight / 2) {
      const old = zoom; zoom = Math.min(4, Math.max(.15, next));
      const worldX = (originX - pan.x) / old; const worldY = (originY - pan.y) / old;
      pan.x = originX - worldX * zoom; pan.y = originY - worldY * zoom; transform();
    }
    function fit() {
      if (!documentState.nodes.length) { pan = { x: 80, y: 70 }; zoom = 1; transform(); return; }
      const minX = Math.min(...documentState.nodes.map((node) => node.x));
      const minY = Math.min(...documentState.nodes.map((node) => node.y));
      const maxX = Math.max(...documentState.nodes.map((node) => {
        const element = nodesLayer.querySelector(`[data-id="${CSS.escape(node.id)}"]`);
        return node.x + (element?.offsetWidth || nodeWidth(node));
      }));
      const maxY = Math.max(...documentState.nodes.map((node) => {
        const element = nodesLayer.querySelector(`[data-id="${CSS.escape(node.id)}"]`);
        return node.y + (element?.offsetHeight || nodeMinHeight(node));
      }));
      zoom = Math.min(1.5, Math.max(.15, Math.min((canvas.clientWidth - 80) / (maxX - minX),
        (canvas.clientHeight - 80) / (maxY - minY))));
      pan = { x: 40 - minX * zoom, y: 40 - minY * zoom }; transform();
    }
    function focusSelected() {
      const node = nodeById(selectedId); if (!node) return;
      const element = nodesLayer.querySelector(`[data-id="${CSS.escape(node.id)}"]`);
      const width = element?.offsetWidth || nodeWidth(node);
      const height = element?.offsetHeight || nodeMinHeight(node);
      pan = { x: canvas.clientWidth / 2 - (node.x + width / 2) * zoom,
        y: canvas.clientHeight / 2 - (node.y + height / 2) * zoom }; transform();
    }
    function toggleFocus() {
      if (!selectedId) return;
      focusMode = !focusMode;
      if (focusMode) focusSelected();
      render();
    }
    function tidy() {
      if (!documentState.nodes.length) return; checkpoint();
      const root = nodeById(selectedId); let row = 0;
      function arrange(parentId, depth) {
        childrenOf(parentId).forEach((node) => {
          node.x = 70 + depth * 330; node.y = 70 + row * 115; row += 1; arrange(node.id, depth + 1);
        });
      }
      if (root) {
        const baseX = root.x; const baseY = root.y;
        function arrangeBranch(parentId, depth) {
          childrenOf(parentId).forEach((node) => { node.x = baseX + depth * 330;
            node.y = baseY + (++row) * 115; arrangeBranch(node.id, depth + 1); });
        }
        arrangeBranch(root.id, 1);
      } else arrange(null, 0);
      markDirty(); render(); fit();
    }
    function toggleCollapseAll() {
      const branchIds = documentState.nodes.filter((node) => childrenOf(node.id).length).map((node) => node.id);
      collapsed = collapsed.size ? new Set() : new Set(branchIds); render();
    }
    function selectDirectional(key) {
      const current = nodeById(selectedId);
      if (!current) return;
      const hidden = hiddenNodeIds();
      const directions = { ArrowLeft: [-1, 0], ArrowRight: [1, 0],
        ArrowUp: [0, -1], ArrowDown: [0, 1] };
      const [dx, dy] = directions[key];
      const candidates = documentState.nodes.filter((node) => {
        if (node.id === current.id || hidden.has(node.id)) return false;
        const x = node.x - current.x; const y = node.y - current.y;
        return dx ? Math.sign(x) === dx && Math.abs(x) >= Math.abs(y) * .25
          : Math.sign(y) === dy && Math.abs(y) >= Math.abs(x) * .25;
      });
      candidates.sort((a, b) => Math.hypot(a.x - current.x, a.y - current.y)
        - Math.hypot(b.x - current.x, b.y - current.y));
      if (candidates[0]) { selectedId = candidates[0].id; render(); focusSelected(); }
    }
    async function save(options = {}) {
      const automatic = options.automatic === true;
      if (!automatic && editingId) {
        const editor = nodesLayer.querySelector(`[data-id="${CSS.escape(editingId)}"] textarea`);
        if (editor) commitEdit(editingId, editor);
      }
      if (!dirty) {
        if (!automatic) setStatus(`Saved ${path}`);
        return true;
      }
      if (savePromise) {
        await savePromise;
        return dirty ? save(options) : true;
      }
      if (autosaveTimer) {
        window.clearTimeout(autosaveTimer);
        autosaveTimer = null;
      }
      const savingVersion = changeVersion;
      const savingDocument = JSON.parse(snapshot());
      setStatus(automatic ? "Autosaving…" : "Saving…");
      savePromise = (async () => {
        const response = await fetch(`/api/mind-map/document?${requestContext}`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path, expected_revision: revision, document: savingDocument }),
        });
        const payload = await response.json().catch(() => ({ error: "save failed" }));
        if (!response.ok) { setStatus(payload.error || "Save failed", true); return false; }
        revision = payload.revision;
        if (changeVersion === savingVersion) {
          documentState = payload.document;
          dirty = false;
          setStatus(`${automatic ? "Autosaved" : "Saved"} ${path}`);
        } else {
          dirty = true;
          scheduleAutosave();
        }
        render();
        return true;
      })();
      try {
        return await savePromise;
      } finally {
        savePromise = null;
      }
    }
    async function createAt(target, document, title) {
      const response = await fetch(`/api/mind-map/documents?${requestContext}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: target, title, document }),
      });
      const payload = await response.json().catch(() => ({ error: "creation failed" }));
      if (!response.ok) throw new Error(payload.error || "creation failed");
      return payload;
    }
    async function newMap() {
      if (dirty && !await confirmDialog(
        "Discard unsaved changes?",
        "Creating another map will discard the unsaved changes in this pane.",
        "Discard and continue",
      )) return;
      const values = await showDialog({
        title: "New Mind Map",
        description: "Create a mind map at a project-relative or absolute path.",
        submitLabel: "Create",
        fields: [
          { name: "title", label: "Name", value: "Untitled mind map", required: true },
          { name: "path", label: "Path",
            value: ".electroboy/shared/mind-maps/untitled.mindmap.json", required: true },
        ],
      });
      if (!values) return;
      const { title, path: target } = values;
      const blank = { schema_version: 1, type: "electroboy.mind-map", title,
        nodes: [], relationships: [] };
      const payload = await createAt(target, blank, title);
      window.location.search = `${requestContext}&path=${encodeURIComponent(payload.path)}`;
    }
    async function openMap() {
      if (dirty && !await confirmDialog(
        "Discard unsaved changes?",
        "Opening another map will discard the unsaved changes in this pane.",
        "Discard and continue",
      )) return;
      const values = await showDialog({
        title: "Open Mind Map",
        description: "Open a project-relative or absolute mind-map file.",
        submitLabel: "Open",
        fields: [{ name: "path", label: "Path", value: path, required: true }],
      });
      if (!values) return;
      window.location.search = `${requestContext}&path=${encodeURIComponent(values.path)}`;
    }
    async function saveAs() {
      const values = await showDialog({
        title: "Save Mind Map As",
        description: "Save a copy at a project-relative or absolute path.",
        submitLabel: "Save",
        fields: [{ name: "path", label: "Path", value: path, required: true }],
      });
      if (!values || values.path === path) return;
      const payload = await createAt(values.path, documentState, documentState.title);
      window.location.search = `${requestContext}&path=${encodeURIComponent(payload.path)}`;
    }
    async function addLink(type, requestedTarget = "") {
      const node = nodeById(selectedId); if (!node) return;
      const values = await showDialog({
        title: type === "url" ? "Add Web Link" : "Add File Link",
        description: type === "url"
          ? "Link this node to an HTTP or HTTPS address."
          : "Link this node to any file supported by ElectroBoy.",
        submitLabel: "Add link",
        fields: [
          { name: "target", label: type === "url" ? "Web address" : "File path",
            placeholder: type === "url" ? "https://example.com" : "/path/to/file",
            value: requestedTarget, required: true,
            browseMode: type === "file" ? "link" : "" },
          { name: "label", label: "Label (optional)" },
        ],
      });
      if (!values) return;
      checkpoint(); node.links.push({ type, target: values.target, label: values.label });
      markDirty(); render();
    }
    async function createDocument(data = {}) {
      const node = nodeById(selectedId); if (!node) return;
      const heading = (node.text.split("\n").find((line) => line.trim()) || "mind-map-note").trim();
      const target = String(data.target || "").trim()
        || await chooseFile("document-new");
      if (!target) return;
      checkpoint(); node.links.push({ type: "document", target, label: heading });
      markDirty(); render();
      overlayLink = node.links[node.links.length - 1]; showOverlay("edit", true);
    }
    async function removeLink() {
      const node = nodeById(selectedId); if (!node || !node.links.length) return;
      const values = await showDialog({
        title: "Remove Link",
        description: "Choose the link to remove from this node.",
        submitLabel: "Remove",
        fields: [{ name: "index", label: "Link", choices: node.links.map(
          (link, index) => ({ value: String(index), label: link.label || link.target })) }],
      });
      if (!values) return;
      const selected = Number.parseInt(values.index, 10);
      if (!Number.isInteger(selected) || !node.links[selected]) return;
      checkpoint(); node.links.splice(selected, 1); markDirty(); render();
    }
    const actions = { new: newMap, open: openMap, save, "save-as": saveAs, undo, redo, root: () => addNode("root"),
      child: () => addNode("child"), sibling: () => addNode("sibling"), edit: beginEdit,
      delete: deleteSelected, "link-file": (data) => addLink("file", data?.target),
      "link-web": () => addLink("url"),
      "create-document": createDocument, "remove-link": removeLink,
      "color-default": () => setNodeColor("default"),
      "color-violet": () => setNodeColor("violet"),
      "color-blue": () => setNodeColor("blue"), "color-teal": () => setNodeColor("teal"),
      "color-green": () => setNodeColor("green"), "color-amber": () => setNodeColor("amber"),
      "color-rose": () => setNodeColor("rose"),
      "font-size-decrease": () => adjustNodeFontSize(-FONT_CONTROL_STEP),
      "font-size-increase": () => adjustNodeFontSize(FONT_CONTROL_STEP),
      "font-size-set": (data) => setNodeFontSize(data?.fontSize),
      "font-size-auto": useAutomaticNodeFontSize,
      compact: () => { compact = true; render(); }, expand: () => { compact = false; render(); },
      "zoom-out": () => adjustZoom(zoom / 1.2), "zoom-in": () => adjustZoom(zoom * 1.2),
      fit, focus: toggleFocus,
      collapse: toggleCollapseAll, tidy };
    document.querySelectorAll("[data-action]").forEach((button) => button.addEventListener("click", () => {
      const action = actions[button.dataset.action]; if (action) Promise.resolve(action()).catch((error) => setStatus(error.message, true));
    }));
    window.addEventListener("message", (event) => {
      if (event.origin !== window.location.origin) return;
      const data = event.data || {};
      if (
        data.type === "electroboy-file-browser-select"
        && pendingFilePicker
        && data.mode === pendingFilePicker.mode
        && event.source === pendingFilePicker.popup
      ) {
        finishFilePicker(String(data.path || "").trim() || null);
        return;
      }
      if (data.type === "electroboy-mind-map-context") {
        const parameters = new URLSearchParams(requestContext);
        parameters.set("workspace_id", String(data.workspaceId || data.contextId || ""));
        parameters.set("context_id", String(data.contextId || data.workspaceId || ""));
        parameters.set("connection_id", String(data.connectionId || ""));
        if (data.leaseToken) parameters.set("lease_token", String(data.leaseToken));
        else parameters.delete("lease_token");
        requestContext = parameters.toString();
        return;
      }
      if (data.type !== "electroboy-mind-map-command") return;
      const action = actions[data.action];
      if (action) Promise.resolve(action(data)).catch((error) => setStatus(error.message, true));
    });
    canvas.addEventListener("keydown", (event) => {
      if (editingId) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault(); event.shiftKey ? redo() : undo(); return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") { event.preventDefault(); redo(); return; }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); save(); return; }
      if (event.key === "Tab" && selectedId) { event.preventDefault(); addNode("child"); }
      else if (event.key === "Enter" && event.shiftKey) { event.preventDefault(); addNode("root"); }
      else if (event.key === "Enter" && selectedId) { event.preventDefault(); addNode("sibling"); }
      else if (event.key === "F2" && selectedId) { event.preventDefault(); beginEdit(); }
      else if (event.key === "Delete" && selectedId) {
        event.preventDefault();
        deleteSelected().catch((error) => setStatus(error.message, true));
      }
      else if (event.key === "Escape") {
        selectedId = null; editingId = null; focusMode = false; render();
      }
      else if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
        event.preventDefault(); selectDirectional(event.key);
      }
    });
    canvas.addEventListener("pointerdown", (event) => {
      if (!editingId || event.target.closest("textarea")) return;
      const editor = nodesLayer.querySelector(`[data-id="${CSS.escape(editingId)}"] textarea`);
      if (!editor) return;
      commitEdit(editingId, editor, { render: false, focus: false });
      pendingEditRender = true;
    }, { capture: true });
    canvas.addEventListener("pointerdown", (event) => {
      if (event.button === 1) { event.preventDefault(); drag = { type: "pan", x: event.clientX,
        y: event.clientY, startX: pan.x, startY: pan.y }; canvas.setPointerCapture(event.pointerId); }
      else if (event.button === 0 && event.target === canvas) {
        selectedId = null; focusMode = false; render(); canvas.focus();
      }
    });
    canvas.addEventListener("click", () => {
      if (!pendingEditRender) return;
      pendingEditRender = false;
      render();
    });
    canvas.addEventListener("dblclick", (event) => {
      if (event.target !== canvas) return;
      const rect = canvas.getBoundingClientRect(); checkpoint();
      const node = { id: nextId(), text: "New idea", parent_id: null,
        order: childrenOf(null).length, x: (event.clientX - rect.left - pan.x) / zoom,
        y: (event.clientY - rect.top - pan.y) / zoom, color: "default",
        font_size: ROOT_NODE_FONT_SIZE, font_size_mode: "auto",
        width: DEFAULT_NODE_WIDTH,
        min_height: DEFAULT_NODE_MIN_HEIGHT, links: [] };
      documentState.nodes.push(node); selectedId = node.id; editingId = node.id; markDirty(); render();
    });
    canvas.addEventListener("auxclick", (event) => { if (event.button === 1) event.preventDefault(); });
    canvas.addEventListener("pointermove", (event) => {
      if (!drag) return;
      if (drag.type === "pan") { pan.x = drag.startX + event.clientX - drag.x;
        pan.y = drag.startY + event.clientY - drag.y; transform(); }
      else if (drag.type === "resize") {
        const node = nodeById(drag.id); if (!node) return;
        const dx = (event.clientX - drag.x) / zoom;
        const dy = (event.clientY - drag.y) / zoom;
        if (Math.abs(dx) + Math.abs(dy) <= 1 && !drag.moved) return;
        drag.moved = true;
        node.width = Math.round(Math.max(
          MINIMUM_NODE_WIDTH, drag.startWidth + dx) * 100) / 100;
        node.min_height = Math.round(Math.max(
          MINIMUM_NODE_HEIGHT, drag.startHeight + dy) * 100) / 100;
        const element = nodesLayer.querySelector(`[data-id="${CSS.escape(node.id)}"]`);
        if (element) {
          element.style.width = `${node.width}px`;
          element.style.minHeight = `${node.min_height}px`;
        }
        const widthDelta = node.width - drag.startWidth;
        drag.descendantPositions.forEach((position, id) => {
          const descendant = nodeById(id);
          if (descendant) descendant.x = position.x + widthDelta;
        });
        const heightDelta = (element?.offsetHeight || node.min_height) - drag.startHeight;
        drag.followingPositions.forEach((position, id) => {
          const following = nodeById(id);
          if (following) following.y = position.y + heightDelta;
        });
        for (const shifted of [...drag.descendantPositions.keys(),
          ...drag.followingPositions.keys()]) {
          const shiftedNode = nodeById(shifted);
          const shiftedElement = nodesLayer.querySelector(
            `[data-id="${CSS.escape(shifted)}"]`);
          if (shiftedNode && shiftedElement) {
            shiftedElement.style.left = `${shiftedNode.x}px`;
            shiftedElement.style.top = `${shiftedNode.y}px`;
          }
        }
        renderEdges(new Set(documentState.nodes
          .filter((candidate) => !hiddenNodeIds().has(candidate.id))
          .map((candidate) => candidate.id)));
      } else {
        const node = nodeById(drag.id); if (!node) return;
        const dx = (event.clientX - drag.x) / zoom; const dy = (event.clientY - drag.y) / zoom;
        if (Math.abs(dx) + Math.abs(dy) <= 2 && !drag.moved) return;
        drag.moved = true;
        node.x = drag.startX + dx; node.y = drag.startY + dy;
        const element = nodesLayer.querySelector(`[data-id="${CSS.escape(node.id)}"]`);
        if (element) {
          element.classList.add("dragging");
          element.style.left = `${node.x}px`; element.style.top = `${node.y}px`;
        }
        renderEdges(new Set(documentState.nodes.filter((candidate) => !hiddenNodeIds().has(candidate.id))
          .map((candidate) => candidate.id)));
        nodesLayer.querySelectorAll(".drop-target").forEach((candidate) => candidate.classList.remove("drop-target"));
        const target = document.elementFromPoint(event.clientX, event.clientY)?.closest(".node");
        if (target && target.dataset.id !== drag.id) target.classList.add("drop-target");
      }
    });
    canvas.addEventListener("pointerup", (event) => {
      if (drag && drag.type === "resize" && drag.moved) {
        undoStack.push(drag.before); redoStack = []; markDirty(); render();
      } else if (drag && drag.type === "node" && drag.moved) {
        const node = nodeById(drag.id);
        const target = document.elementFromPoint(event.clientX, event.clientY)?.closest(".node");
        const targetId = target && target.dataset.id !== drag.id ? target.dataset.id : null;
        if (targetId && descendants(node.id).has(targetId)) {
          documentState = JSON.parse(drag.before); setStatus("A node cannot be attached to its descendant.", true);
        } else {
          const previousParentId = node.parent_id;
          node.parent_id = targetId;
          node.order = childrenOf(targetId).filter((item) => item.id !== node.id).length;
          if (targetId !== previousParentId && node.color === "default") {
            node.color = initialNodeColor(targetId);
          }
          undoStack.push(drag.before); redoStack = [];
          markDirty();
        }
        render();
      }
      drag = null;
    });
    canvas.addEventListener("wheel", (event) => { event.preventDefault(); const rect = canvas.getBoundingClientRect();
      adjustZoom(zoom * Math.exp(-event.deltaY * .0015), event.clientX - rect.left, event.clientY - rect.top);
    }, { passive: false });
    document.getElementById("overlayClose").addEventListener("click", () => {
      overlay.hidden = true; overlayFrame.src = "about:blank"; overlayLink = null;
    });
    overlayPreview.addEventListener("click", () => showOverlay("preview"));
    overlayEdit.addEventListener("click", () => showOverlay("edit"));
    document.getElementById("zoomValue").addEventListener("change", (event) => {
      const percent = Number(event.target.value); if (Number.isFinite(percent)) adjustZoom(percent / 100);
    });
    window.addEventListener("beforeunload", (event) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
    if (new URLSearchParams(window.location.search).get("embed") === "1") {
      document.body.classList.add("embedded");
    }
    restoreView(); render(); canvas.focus();
  })();
  </script>
</body>
</html>"""
