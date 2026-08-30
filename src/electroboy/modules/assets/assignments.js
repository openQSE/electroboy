(function () {
  "use strict";

  function routePath(source = {}, options = {}) {
    return String(source.path || options.path || "").trim();
  }

  function show(runtime, source = {}, options = {}) {
    const descriptor = typeof source === "string"
      ? { path: source }
      : { ...(source || {}) };
    const path = routePath(descriptor, options);
    if (!path) return;
    const label = String(
      descriptor.title || options.title || "Assignments",
    ).trim();
    const item = {
      id: String(descriptor.id || options.id || `assignments-${path}`),
      kind: "route",
      title: label,
      editing: false,
      providerView: true,
      path,
    };
    const activate = options.activate !== false;
    const targetPane = String(options.targetPane || "agenda");
    const ratio = Number(options.ratio || 0.72);
    if (runtime.layout.ensurePane) {
      runtime.layout.ensurePane(
        "assignments",
        targetPane,
        "row",
        {
          ratio,
          activate,
          activateExisting: activate,
        },
      );
    }
    runtime.layout.assignPane("assignments", item, "", {
      activate,
      targetPane,
      direction: "row",
      ratio,
    });
  }

  window.ElectroBoyFrontend.registerModule({
    id: "assignments",
    label: "Assignments",
    capabilities: [
      "route-backed-assignments-pane",
      "workspace-companion-pane",
    ],
    actions: { show },
  });
})();
