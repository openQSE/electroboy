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
  const MIND_MAP_SUFFIX = ".mindmap.json";
  let pendingFilePicker = null;
  let filePickerSequence = 0;

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
    assign("mind-map", item, options.requestedLeafId || "");
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
    assign("mind-map", item, options.requestedLeafId || "");
  }

  function contextUrl(runtime, path) {
    return runtime.http.contextUrl(path);
  }

  function projectRoot(runtime) {
    const state = runtime.getState ? runtime.getState() : {};
    return String(
      state.activeProjectRoot || state.activationRoot || state.serviceRoot || ".",
    );
  }

  function mindMapPathWithExtension(target) {
    const requested = String(target || "").trim();
    if (!requested) return "";
    return requested.toLowerCase().endsWith(MIND_MAP_SUFFIX)
      ? requested
      : `${requested}${MIND_MAP_SUFFIX}`;
  }

  function titleFromMindMapPath(target) {
    const requested = String(target || "").trim().replace(/\\+/g, "/");
    const name = requested.split("/").pop() || "Untitled mind map";
    return name.toLowerCase().endsWith(MIND_MAP_SUFFIX)
      ? name.slice(0, -MIND_MAP_SUFFIX.length)
      : name;
  }

  function finishFilePicker(value) {
    if (!pendingFilePicker) return;
    const pending = pendingFilePicker;
    pendingFilePicker = null;
    window.clearInterval(pending.timer);
    window.removeEventListener("message", pending.listener);
    pending.resolve(value);
  }

  function chooseFile(runtime, mode) {
    if (pendingFilePicker) {
      pendingFilePicker.popup?.focus();
      return Promise.resolve(null);
    }
    const browserMode = mode === "new" ? "file-new" : "file-open";
    const selectionChannel = `mind-map-${Date.now()}-${++filePickerSequence}`;
    const parameters = new URLSearchParams({
      path: projectRoot(runtime),
      mode: browserMode,
      new_extension: MIND_MAP_SUFFIX,
      selection_channel: selectionChannel,
    });
    const popup = window.open(
      `/file-browser?${parameters.toString()}`,
      `electroboy-${selectionChannel}`,
      "popup=yes,width=980,height=720,menubar=no,toolbar=no,location=no,"
        + "status=no,scrollbars=yes,resizable=yes",
    );
    if (!popup) {
      runtime.notifications?.appendOutput(
        "mind map file picker was blocked by the browser\n",
        "error",
      );
      return Promise.resolve(null);
    }
    return new Promise((resolve) => {
      const listener = (event) => {
        if (event.origin !== window.location.origin) return;
        const data = event.data || {};
        if (
          data.type === "electroboy-file-browser-select"
          && data.selection_channel === selectionChannel
          && event.source === popup
        ) {
          finishFilePicker(String(data.path || "").trim() || null);
        }
      };
      const timer = window.setInterval(() => {
        if (popup.closed) finishFilePicker(null);
      }, 300);
      pendingFilePicker = { listener, mode: browserMode, popup, resolve, timer };
      window.addEventListener("message", listener);
    });
  }

  async function openDocument(runtime, options = {}) {
    const path = await chooseFile(runtime, "open");
    if (path) showDocument(runtime, { path }, {
      replaceWorkspacePane: true,
      requestedLeafId: options.requestedLeafId || "",
    });
  }

  async function newDocument(runtime, options = {}) {
    const path = mindMapPathWithExtension(await chooseFile(runtime, "new"));
    if (!path) return;
    const title = titleFromMindMapPath(path);
    const response = await fetch(contextUrl(runtime, "/api/mind-map/documents"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, title }),
    });
    const payload = await response.json().catch(() => ({ error: "creation failed" }));
    if (!response.ok) throw new Error(payload.error || "creation failed");
    showDocument(
      runtime,
      {
        path: payload.path || path,
        title: payload.document?.title || title,
      },
      {
        replaceWorkspacePane: true,
        requestedLeafId: options.requestedLeafId || "",
      },
    );
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
