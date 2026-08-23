(function () {
  "use strict";

  function selectedCalendarIds(source = {}, options = {}) {
    const values = source.calendarIds || source.calendar_ids || options.calendarIds || [];
    if (!Array.isArray(values)) return [];
    return values.map((value) => String(value || "").trim()).filter(Boolean);
  }

  function show(runtime, source = {}, options = {}) {
    const descriptor = typeof source === "string"
      ? { provider: source }
      : { ...(source || {}) };
    const provider = String(descriptor.provider || options.provider || "").trim();
    const label = String(descriptor.title || options.title || "Calendar").trim();
    const calendarIds = selectedCalendarIds(descriptor, options);
    const item = {
      id: `calendar-${provider || "active"}`,
      kind: "calendar",
      title: label,
      editing: false,
      calendar: { provider, label, calendarIds },
    };
    runtime.layout.assignPane("calendar", item);
  }

  window.ElectroBoyFrontend.registerModule({
    id: "calendar",
    label: "Calendar",
    capabilities: [
      "calendar-provider",
      "calendar-event-colors",
      "calendar-multi-select",
    ],
    actions: { show },
  });
})();
