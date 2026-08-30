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

  window.ElectroBoyFrontend.registerModule({
    id: "mind_map",
    label: "Mind Map",
    capabilities: [
      "mind-map-provider",
      "mind-map-source-trace",
      "mind-map-pan-zoom",
      "mind-map-styles",
    ],
    actions: { show },
  });
})();
