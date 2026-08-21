(function () {
  "use strict";

  function show(runtime, source = {}, options = {}) {
    const descriptor = typeof source === "string"
      ? { provider: source }
      : { ...(source || {}) };
    const provider = String(descriptor.provider || options.provider || "").trim();
    const label = String(descriptor.title || options.title || "Agenda").trim();
    const item = {
      id: `agenda-${provider || "active"}`,
      kind: "agenda",
      title: label,
      editing: false,
      agenda: { provider, label },
    };
    runtime.layout.assignPane("agenda", item);
  }

  window.ElectroBoyFrontend.registerModule({
    id: "agenda",
    label: "Agenda",
    capabilities: [
      "agenda-provider",
      "agenda-filters",
      "agenda-actions",
      "agenda-modal-editor",
    ],
    actions: { show },
  });
})();
