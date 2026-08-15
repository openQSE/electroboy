(function () {
  "use strict";

  function show(runtime, path, options = {}) {
    if (!path) {
      return;
    }
    const freeform = Boolean(options.freeform) ||
      runtime.actions.creativePathIsCorkboard(path);
    const label = freeform
      ? runtime.actions.basename(path).replace(/\.corkboard\.json$/i, "")
      : runtime.actions.basename(path);
    const board = { label, path };
    const item = {
      id: `creative-corkboard-${path}`,
      kind: "creative-corkboard",
      title: `${freeform ? "Corkboard" : "Folder board"}: ${label}`,
      editing: false,
    };
    if (freeform) {
      item.corkboard = board;
    } else {
      item.folder = board;
    }
    runtime.actions.showArtifactPreviews(
      [item],
      { manual: true, stage: "creative-writing" },
    );
  }

  window.ElectroBoyFrontend.registerModule({
    id: "corkboard",
    label: "Corkboard",
    capabilities: ["folder-corkboard", "freeform-corkboard"],
    actions: { show },
  });
})();
