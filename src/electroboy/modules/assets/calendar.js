(function () {
  "use strict";

  const CALENDAR_STYLES = Object.freeze([
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
    return CALENDAR_STYLES.includes(requested) ? requested : "default";
  }

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

  function calendarRange(source = {}, options = {}) {
    const descriptor = source || {};
    const month = String(
      descriptor.month || descriptor.calendarMonth || options.month || "",
    ).trim();
    const rangeStart = String(
      descriptor.rangeStart || descriptor.range_start || options.rangeStart || "",
    ).trim();
    const rangeEnd = String(
      descriptor.rangeEnd || descriptor.range_end || options.rangeEnd || "",
    ).trim();
    return { month, rangeStart, rangeEnd };
  }

  function show(runtime, source = {}, options = {}) {
    const descriptor = typeof source === "string"
      ? { provider: source }
      : { ...(source || {}) };
    const provider = String(descriptor.provider || options.provider || "").trim();
    const label = String(descriptor.title || options.title || "Calendar").trim();
    const calendarSelection = selectedCalendarIds(descriptor, options);
    const range = calendarRange(descriptor, options);
    const style = normalizeStyle(descriptor.style || options.style);
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
        month: range.month,
        rangeStart: range.rangeStart,
        rangeEnd: range.rangeEnd,
        style,
      },
    };
    const assign = options.replaceWorkspacePane &&
        runtime.layout.assignWorkspacePane
      ? runtime.layout.assignWorkspacePane
      : runtime.layout.assignPane;
    assign("calendar", item);
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
