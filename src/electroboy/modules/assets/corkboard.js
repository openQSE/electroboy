(function () {
  "use strict";

  function show(runtime, source, options = {}) {
    const descriptor = typeof source === "string"
      ? {
          id: source,
          provider: options.provider || "creative-files",
          title: options.title || "",
        }
      : { ...(source || {}) };
    const boardId = String(descriptor.id || descriptor.board_id || "").trim();
    if (!boardId) {
      return;
    }
    const provider = String(descriptor.provider || options.provider || "").trim();
    const freeform = Boolean(options.freeform || descriptor.freeform) ||
      /\.corkboard\.json$/i.test(boardId);
    const label = String(descriptor.title || options.title || "").trim() || (freeform
      ? runtime.paths.basename(boardId).replace(/\.corkboard\.json$/i, "")
      : runtime.paths.basename(boardId));
    const board = {
      id: boardId,
      label,
      provider,
    };
    const item = {
      id: `corkboard-${provider || "active"}-${boardId}`,
      kind: "corkboard",
      title: `${freeform ? "Corkboard" : "Folder board"}: ${label}`,
      editing: false,
      board,
    };
    runtime.modules.invoke(
      "documents",
      "showArtifactPreviews",
      [item],
      { manual: true, stage: options.stage || runtime.getState().workflowMode },
    );
  }

  window.ElectroBoyFrontend.registerModule({
    id: "corkboard",
    label: "Corkboard",
    capabilities: [
      "corkboard-provider",
      "folder-corkboard",
      "freeform-corkboard",
      "selectable-corkboard-layout",
      "corkboard-auto-organize",
    ],
    actions: { show },
  });
})();
