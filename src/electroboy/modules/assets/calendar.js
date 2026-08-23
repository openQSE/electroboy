(function () {
  "use strict";

  function selectedCalendarIds(source = {}, options = {}) {
    const hasSourceIds = Object.prototype.hasOwnProperty.call(source, "calendarIds") ||
      Object.prototype.hasOwnProperty.call(source, "calendar_ids");
    const hasOptionIds = Object.prototype.hasOwnProperty.call(options, "calendarIds");
    const values = hasSourceIds
      ? (source.calendarIds || source.calendar_ids || [])
      : (hasOptionIds ? options.calendarIds : []);
    if (!Array.isArray(values)) {
      return { explicit: hasSourceIds || hasOptionIds, ids: [] };
    }
    return {
      explicit: hasSourceIds || hasOptionIds,
      ids: values.map((value) => String(value || "").trim()).filter(Boolean),
    };
  }

  function show(runtime, source = {}, options = {}) {
    const descriptor = typeof source === "string"
      ? { provider: source }
      : { ...(source || {}) };
    const provider = String(descriptor.provider || options.provider || "").trim();
    const label = String(descriptor.title || options.title || "Calendar").trim();
    const calendarSelection = selectedCalendarIds(descriptor, options);
    const item = {
      id: `calendar-${provider || "active"}`,
      kind: "calendar",
      title: label,
      editing: false,
      calendar: {
        provider,
        label,
        calendarIds: calendarSelection.ids,
        calendarIdsExplicit: calendarSelection.explicit,
      },
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
