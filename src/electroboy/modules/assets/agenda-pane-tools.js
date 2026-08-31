(function () {
  "use strict";

  function element(tag, className = "", text = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== "") node.textContent = text;
    return node;
  }

  function datePart(value) {
    const match = String(value || "").match(/^\d{4}-\d{2}-\d{2}/);
    return match ? match[0] : "";
  }

  function addDays(value, amount) {
    const date = new Date(`${value}T12:00:00Z`);
    date.setUTCDate(date.getUTCDate() + amount);
    return date.toISOString().slice(0, 10);
  }

  function monthEnd(value) {
    const [year, month] = value.split("-").map(Number);
    return new Date(Date.UTC(year, month, 0, 12)).toISOString().slice(0, 10);
  }

  function rangeValue(value, end = false) {
    return value ? `${value}T${end ? "23:59:59.999" : "00:00:00"}` : "";
  }

  function agendaStyleClass(value) {
    const style = String(value || "default").trim().toLowerCase();
    return style.replace(/[^a-z0-9-]+/g, "-") || "default";
  }

  function telemetryEnabled() {
    const current = new URLSearchParams(window.location.search);
    if (current.get("telemetry_page_id") || current.get("telemetry_tab_id")) {
      return true;
    }
    return ["telemetry", "frontend_telemetry", "frontend_debug"].some((key) => {
      const value = String(current.get(key) || "").trim().toLowerCase();
      return ["1", "true", "yes", "on"].includes(value);
    });
  }

  function telemetryParam(key) {
    return new URLSearchParams(window.location.search).get(key) || "";
  }

  function mount(options) {
    const controller = options.controller;
    const frame = options.frame;
    const paneRoot = options.host
      || (frame && frame.closest(".pane-body"))
      || document.body;
    const initialStyleProvided = Boolean(String(options.initialStyle || "").trim());
    const initialStyle = agendaStyleClass(options.initialStyle);
    let agendaState = initialStyleProvided ? { style: initialStyle } : null;
    let stateUpdateCount = 0;

    function emitToolsTelemetry(eventName, details = {}) {
      if (!telemetryEnabled()) return;
      window.fetch("/api/frontend/debug", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "agenda-pane-tools",
          event: eventName,
          created_at: new Date().toISOString(),
          pane_kind: "agenda",
          pane_instance_id: telemetryParam("pane_instance_id"),
          workspace_id: telemetryParam("workspace_id"),
          context_id: telemetryParam("context_id"),
          connection_id: telemetryParam("connection_id"),
          telemetry_page_id: telemetryParam("telemetry_page_id"),
          telemetry_tab_id: telemetryParam("telemetry_tab_id"),
          initial_style: initialStyleProvided ? initialStyle : "",
          current_style: paneRoot.dataset.agendaStyle || "",
          state_update_count: stateUpdateCount,
          ...details,
        }),
        keepalive: true,
      }).catch(() => {
        // Diagnostic telemetry must never affect pane tools.
      });
    }

    const displayBody = controller.addSection("agenda-display", "Display");
    const styleLabel = element("label", "agenda-tool-style-field");
    styleLabel.append(element("span", "", "Style"));
    const styleSelect = element("select", "agenda-tool-select");
    styleSelect.setAttribute("aria-label", "Agenda style");
    styleLabel.append(styleSelect);
    displayBody.append(styleLabel);

    const filterBody = controller.addSection("agenda-filters", "Filters");
    filterBody.classList.add("agenda-tool-filters");

    const dateBody = controller.addSection("agenda-date", "Date");
    dateBody.classList.add("agenda-tool-date");
    const quickDates = element("div", "agenda-tool-quick-dates");
    const customDates = element("div", "agenda-tool-custom-dates");
    const startLabel = element("label", "agenda-tool-date-field");
    startLabel.append(element("span", "", "From"));
    const startInput = element("input");
    startInput.type = "date";
    startInput.setAttribute("aria-label", "Agenda start date");
    startLabel.append(startInput);
    const endLabel = element("label", "agenda-tool-date-field");
    endLabel.append(element("span", "", "Through"));
    const endInput = element("input");
    endInput.type = "date";
    endInput.setAttribute("aria-label", "Agenda end date");
    endLabel.append(endInput);
    customDates.append(startLabel, endLabel);
    const dateActions = element("div", "agenda-tool-date-actions");
    const applyDates = element("button", "primary", "Apply dates");
    applyDates.type = "button";
    const clearDates = element("button", "", "Any date");
    clearDates.type = "button";
    dateActions.append(applyDates, clearDates);
    dateBody.append(quickDates, customDates, dateActions);

    const resultsBody = controller.addSection("agenda-results", "Results", {
      open: false,
    });
    const resultCount = element("div", "agenda-tool-result-count", "Loading agenda…");
    const jumpToday = element("button", "", "Jump to today");
    jumpToday.type = "button";
    const reset = element("button", "", "Clear all filters");
    reset.type = "button";
    resultsBody.append(resultCount, jumpToday, reset);

    function post(action, values = {}) {
      if (!frame || !frame.contentWindow) {
        emitToolsTelemetry("agenda.tools.command_skipped", {
          action,
          reason: "missing_frame",
        });
        return;
      }
      emitToolsTelemetry("agenda.tools.command_posted", {
        action,
        request_reason: String(values.requestReason || ""),
      });
      frame.contentWindow.postMessage({
        type: "electroboy-agenda-command",
        action,
        ...values,
      }, window.location.origin);
    }

    function filterControl(filter) {
      const group = element("div", "agenda-tool-filter-group");
      group.append(element("div", "agenda-tool-filter-label", filter.label));
      if (filter.control === "list") {
        const choices = element("div", "agenda-tool-choices");
        choices.setAttribute("role", "radiogroup");
        choices.setAttribute("aria-label", filter.label);
        for (const option of filter.options || []) {
          const choice = element("button", "agenda-tool-choice");
          choice.type = "button";
          choice.setAttribute("role", "radio");
          const selected = option.value === filter.value;
          choice.classList.toggle("selected", selected);
          choice.setAttribute("aria-checked", String(selected));
          const marker = element("span", "agenda-tool-choice-marker");
          marker.dataset.color = String(option.color || "all");
          choice.append(marker, element("span", "", option.label));
          choice.addEventListener("click", () => post("set-filter", {
            filterId: filter.id,
            value: option.value,
          }));
          choices.append(choice);
        }
        group.append(choices);
        return group;
      }

      const select = element("select", "agenda-tool-select");
      select.setAttribute("aria-label", filter.label);
      for (const option of filter.options || []) {
        const node = element("option", "", option.label);
        node.value = option.value;
        node.selected = option.value === filter.value;
        select.append(node);
      }
      select.addEventListener("change", () => post("set-filter", {
        filterId: filter.id,
        value: select.value,
      }));
      group.append(select);
      return group;
    }

    function renderFilters() {
      filterBody.replaceChildren();
      const filters = agendaState && Array.isArray(agendaState.filters)
        ? agendaState.filters
        : [];
      if (!filters.length) {
        filterBody.append(element("div", "agenda-tool-help", "No filters available."));
        return;
      }
      for (const filter of filters) filterBody.append(filterControl(filter));
    }

    function renderStyles() {
      styleSelect.replaceChildren();
      const styles = agendaState && Array.isArray(agendaState.styles)
        ? agendaState.styles
        : [];
      const selected = String(agendaState && agendaState.style || "default");
      for (const style of styles) {
        const option = element("option", "", style.label || style.id);
        option.value = style.id;
        option.selected = style.id === selected;
        styleSelect.append(option);
      }
      displayBody.closest("details").hidden = styles.length === 0;
      styleSelect.disabled = styles.length < 2;
    }

    function applyAgendaStyle(reason = "state") {
      const previousStyle = paneRoot.dataset.agendaStyle || "";
      const nextStyle = agendaStyleClass(
        agendaState && agendaState.style || initialStyle,
      );
      paneRoot.dataset.agendaStyle = nextStyle;
      emitToolsTelemetry("agenda.tools.style_applied", {
        reason,
        previous_style: previousStyle,
        next_style: nextStyle,
        state_style: agendaStyleClass(agendaState && agendaState.style),
        style_changed: previousStyle !== nextStyle,
      });
    }

    function setRange(start, end) {
      post("set-range", {
        rangeStart: rangeValue(start),
        rangeEnd: rangeValue(end, true),
      });
    }

    function renderQuickDates() {
      quickDates.replaceChildren();
      const today = datePart(agendaState && agendaState.referenceDate)
        || new Date().toISOString().slice(0, 10);
      for (const [label, start, end] of [
        ["Today", today, today],
        ["Next 7 days", today, addDays(today, 6)],
        ["This month", today.slice(0, 8) + "01", monthEnd(today)],
      ]) {
        const button = element("button", "agenda-tool-quick-date", label);
        button.type = "button";
        button.addEventListener("click", () => setRange(start, end));
        quickDates.append(button);
      }
    }

    function renderState(reason = "state") {
      applyAgendaStyle(reason);
      renderStyles();
      renderFilters();
      renderQuickDates();
      const range = agendaState.range || {};
      startInput.value = datePart(range.range_start);
      endInput.value = datePart(range.range_end);
      const count = Number(agendaState.itemCount || 0);
      resultCount.textContent = count === 1 ? "Showing 1 item" : `Showing ${count} items`;
    }

    function agendaActionHost() {
      if (window.parent !== window) return window.parent;
      if (window.opener && !window.opener.closed) return window.opener;
      return null;
    }

    function handleMessage(event) {
      if (event.origin !== window.location.origin || event.source !== frame.contentWindow) {
        return;
      }
      const data = event.data || {};
      if (data.type === "electroboy-agenda-state") {
        const previousStyle = agendaStyleClass(
          agendaState && agendaState.style || initialStyle,
        );
        agendaState = data.state || {};
        stateUpdateCount += 1;
        const stateStyle = agendaStyleClass(agendaState.style);
        emitToolsTelemetry("agenda.tools.state_received", {
          previous_style: previousStyle,
          state_style: stateStyle,
          item_count: Number(agendaState.itemCount || 0),
          filter_count: Array.isArray(agendaState.filters)
            ? agendaState.filters.length
            : 0,
          style_count: Array.isArray(agendaState.styles)
            ? agendaState.styles.length
            : 0,
        });
        if (
          initialStyleProvided &&
          stateUpdateCount === 1 &&
          previousStyle !== stateStyle
        ) {
          emitToolsTelemetry("agenda.tools.initial_style_mismatch", {
            initial_style: initialStyle,
            state_style: stateStyle,
          });
        }
        renderState("state_received");
        return;
      }
      if (data.type !== "electroboy-agenda-action") return;
      const host = agendaActionHost();
      if (host) host.postMessage(data, window.location.origin);
    }

    applyDates.addEventListener("click", () => {
      if (startInput.value && endInput.value && startInput.value > endInput.value) {
        endInput.setCustomValidity("End date must be on or after the start date.");
        endInput.reportValidity();
        return;
      }
      endInput.setCustomValidity("");
      setRange(startInput.value, endInput.value);
    });
    clearDates.addEventListener("click", () => setRange("", ""));
    styleSelect.addEventListener("change", () => post("set-style", {
      style: styleSelect.value,
    }));
    jumpToday.addEventListener("click", () => post("jump-today"));
    reset.addEventListener("click", () => post("reset"));
    frame.addEventListener("load", () => post("request-state", {
      requestReason: "frame_load",
    }));
    window.addEventListener("message", handleMessage);
    applyAgendaStyle("mount");
    emitToolsTelemetry("agenda.tools.mounted", {
      initial_style_provided: initialStyleProvided,
      resolved_initial_style: paneRoot.dataset.agendaStyle || "",
      has_frame: Boolean(frame && frame.contentWindow),
    });
    post("request-state", { requestReason: "mount" });

    return {
      refresh: () => post("request-state"),
    };
  }

  window.ElectroBoyAgendaPaneTools = { mount };
})();
