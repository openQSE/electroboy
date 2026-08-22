(function () {
  "use strict";

  const AGENDA_STYLES = Object.freeze([
    Object.freeze({ id: "default", label: "Default" }),
    Object.freeze({ id: "hud", label: "HUD" }),
    Object.freeze({ id: "command-center", label: "Command Center" }),
    Object.freeze({ id: "timeline-stack", label: "Timeline Stack" }),
    Object.freeze({ id: "radar", label: "Radar" }),
    Object.freeze({ id: "family-orbit", label: "Family Orbit" }),
    Object.freeze({ id: "month-hud", label: "Month HUD" }),
  ]);

  function styles() {
    return AGENDA_STYLES.map((style) => ({ ...style }));
  }

  function normalizeStyle(value) {
    const requested = String(value || "default").trim().toLowerCase();
    return AGENDA_STYLES.some((style) => style.id === requested)
      ? requested
      : "default";
  }

  function show(runtime, source = {}, options = {}) {
    const descriptor = typeof source === "string"
      ? { provider: source }
      : { ...(source || {}) };
    const provider = String(descriptor.provider || options.provider || "").trim();
    const label = String(descriptor.title || options.title || "Agenda").trim();
    const style = normalizeStyle(descriptor.style || options.style);
    const item = {
      id: `agenda-${provider || "active"}`,
      kind: "agenda",
      title: label,
      editing: false,
      agenda: { provider, label, style },
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
      "agenda-styles",
      "agenda-modal-editor",
    ],
    actions: { show, styles },
  });
})();
