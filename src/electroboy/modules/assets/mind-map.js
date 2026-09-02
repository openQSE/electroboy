(function () {
  "use strict";

  const MIND_MAP_STYLES = Object.freeze([
    "default",
    "hud",
    "command-center",
    "timeline-stack",
    "radar",
    "family-orbit",
    "month-hud",
  ]);

  function normalizeStyle(value) {
    const requested = String(value || "default").trim().toLowerCase();
    return MIND_MAP_STYLES.includes(requested) ? requested : "default";
  }

  function show(runtime, source = {}, options = {}) {
    const descriptor = typeof source === "string"
      ? { provider: source }
      : { ...(source || {}) };
    const provider = String(descriptor.provider || options.provider || "").trim();
    const label = String(descriptor.title || options.title || "Mind Map").trim();
    const style = normalizeStyle(descriptor.style || options.style);
    const item = {
      id: `mind-map-${provider || "active"}`,
      kind: "mind-map",
      title: label,
      editing: false,
      mindMap: {
        provider,
        label,
        style,
      },
    };
    const assign = options.replaceWorkspacePane &&
        runtime.layout.assignWorkspacePane
      ? runtime.layout.assignWorkspacePane
      : runtime.layout.assignPane;
    assign("mind-map", item);
  }

  function showDocument(runtime, source = {}, options = {}) {
    const descriptor = typeof source === "string" ? { path: source } : { ...(source || {}) };
    const path = String(descriptor.path || "").trim();
    if (!path) throw new Error("mind map path is required");
    const label = String(descriptor.title || options.title || runtime.paths.basename(path)
      .replace(/\.mindmap\.json$/i, "") || "Mind Map").trim();
    const item = {
      id: `mind-map-document-${path}`,
      kind: "mind-map",
      title: label,
      editing: true,
      mindMap: { path, label, editable: true },
    };
    const assign = options.replaceWorkspacePane && runtime.layout.assignWorkspacePane
      ? runtime.layout.assignWorkspacePane : runtime.layout.assignPane;
    assign("mind-map", item);
  }

  function contextUrl(runtime, path) {
    return runtime.http.contextUrl(path);
  }

  async function maps(runtime) {
    const response = await fetch(contextUrl(runtime, "/api/mind-map/documents"), {
      headers: { Accept: "application/json" },
    });
    const payload = await response.json().catch(() => ({ error: "mind map list failed" }));
    if (!response.ok) throw new Error(payload.error || "mind map list failed");
    return payload.mind_maps || [];
  }

  function picker() {
    let dialog = document.getElementById("mindMapDocumentPicker");
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.id = "mindMapDocumentPicker";
    dialog.className = "ad-hoc-session-dialog mind-map-picker-dialog";
    dialog.innerHTML = `
      <form method="dialog" class="ad-hoc-session-form">
        <header class="ad-hoc-session-header">
          <div><h2 class="mind-map-picker-title">Mind Map</h2>
            <p class="mind-map-picker-description"></p></div>
          <button class="ad-hoc-session-close" type="button" aria-label="Close">&times;</button>
        </header>
        <fieldset class="ad-hoc-session-options mind-map-picker-existing">
          <legend>Mind maps</legend>
          <div class="ad-hoc-session-list mind-map-picker-list"></div>
        </fieldset>
        <label class="ad-hoc-session-custom mind-map-picker-path">Or open a path
          <input class="ad-hoc-session-uuid mind-map-picker-path-input"
                 autocomplete="off" placeholder="/path/to/plan.mindmap.json"></label>
        <label class="ad-hoc-session-custom mind-map-picker-new">Name
          <input class="ad-hoc-session-uuid mind-map-picker-name" autocomplete="off"></label>
        <p class="ad-hoc-session-error mind-map-picker-error" hidden></p>
        <footer class="ad-hoc-session-footer">
          <button class="mind-map-picker-cancel" type="button">Cancel</button>
          <button class="ad-hoc-session-submit mind-map-picker-submit" type="submit">Open</button>
        </footer>
      </form>`;
    document.body.append(dialog);
    return dialog;
  }

  async function choose(runtime, mode) {
    const dialog = picker();
    const creating = mode === "new";
    const existing = dialog.querySelector(".mind-map-picker-existing");
    const list = dialog.querySelector(".mind-map-picker-list");
    const nameLabel = dialog.querySelector(".mind-map-picker-new");
    const name = dialog.querySelector(".mind-map-picker-name");
    const pathLabel = dialog.querySelector(".mind-map-picker-path");
    const pathInput = dialog.querySelector(".mind-map-picker-path-input");
    const error = dialog.querySelector(".mind-map-picker-error");
    const submit = dialog.querySelector(".mind-map-picker-submit");
    dialog.querySelector(".mind-map-picker-title").textContent = creating ? "New Mind Map" : "Open Mind Map";
    dialog.querySelector(".mind-map-picker-description").textContent = creating
      ? "Create a project mind map." : "Choose a project mind map.";
    existing.hidden = creating; nameLabel.hidden = !creating; pathLabel.hidden = creating;
    error.hidden = true; pathInput.value = "";
    submit.textContent = creating ? "Create" : "Open"; name.value = ""; list.replaceChildren();
    if (!creating) {
      const documents = await maps(runtime);
      if (!documents.length) list.textContent = "No mind maps yet.";
      documents.forEach((entry, index) => {
        const label = document.createElement("label");
        label.className = "ad-hoc-session-option";
        const input = document.createElement("input"); input.type = "radio";
        input.name = "mind-map-document"; input.value = entry.path; input.dataset.title = entry.title;
        if (index === 0) input.checked = true;
        const copy = document.createElement("span"); copy.className = "ad-hoc-session-option-copy";
        const title = document.createElement("strong"); title.textContent = entry.title;
        const details = document.createElement("span"); details.className = "ad-hoc-session-details";
        details.textContent = entry.relative_path;
        copy.append(title, details); label.append(input, copy); list.append(label);
      });
    }
    return new Promise((resolve) => {
      let finished = false;
      const finish = (value) => {
        if (finished) return;
        finished = true; dialog.close(); resolve(value);
      };
      dialog.querySelector(".ad-hoc-session-close").onclick = () => finish(null);
      dialog.querySelector(".mind-map-picker-cancel").onclick = () => finish(null);
      dialog.oncancel = (event) => { event.preventDefault(); finish(null); };
      dialog.querySelector("form").onsubmit = async (event) => {
        event.preventDefault();
        try {
          if (!creating) {
            const selected = list.querySelector('input[name="mind-map-document"]:checked');
            const requestedPath = pathInput.value.trim();
            if (!requestedPath && !selected) throw new Error("Choose a mind map or enter a path.");
            finish(requestedPath
              ? {
                  path: requestedPath,
                  title: runtime.paths.basename(requestedPath).replace(/\.mindmap\.json$/i, ""),
                }
              : { path: selected.value, title: selected.dataset.title });
            return;
          }
          const title = name.value.trim(); if (!title) throw new Error("Enter a name.");
          const response = await fetch(contextUrl(runtime, "/api/mind-map/documents"), {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title }),
          });
          const payload = await response.json().catch(() => ({ error: "creation failed" }));
          if (!response.ok) throw new Error(payload.error || "creation failed");
          finish({ path: payload.path, title: payload.document.title });
        } catch (caught) { error.textContent = caught.message; error.hidden = false; }
      };
      dialog.showModal(); if (creating) name.focus();
    });
  }

  async function openDocument(runtime) {
    const selected = await choose(runtime, "open");
    if (selected) showDocument(runtime, selected, { replaceWorkspacePane: true });
  }

  async function newDocument(runtime) {
    const selected = await choose(runtime, "new");
    if (selected) showDocument(runtime, selected, { replaceWorkspacePane: true });
  }

  window.ElectroBoyFrontend.registerModule({
    id: "mind_map",
    label: "Mind Map",
    capabilities: [
      "mind-map-provider",
      "mind-map-source-trace",
      "mind-map-pan-zoom",
      "mind-map-relationship-modes",
      "mind-map-styles",
      "editable-mind-map",
      "mind-map-documents",
    ],
    actions: { show, showDocument, openDocument, newDocument },
  });
})();
