# ruff: noqa: E501
"""Provider-neutral Calendar HTML renderer."""

from __future__ import annotations

import html
import json
from http import HTTPStatus


def render_calendar_html(payload: dict[str, object]) -> tuple[str, HTTPStatus]:
    """Render a normalized calendar snapshot as a self-contained pane."""

    encoded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    title = html.escape(str(payload.get("title") or "Calendar"))
    return (
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #23272f;
      --muted: #667085;
      --line: #d9dee7;
      --paper: #ffffff;
      --wash: #f4f6f9;
      --panel: #eef2f7;
      --shadow: 0 14px 34px rgba(20, 28, 43, .12);
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ min-height: 100%; }}
    body {{
      margin: 0;
      background: var(--wash);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system,
        BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    button {{ font: inherit; }}
    .calendar-shell {{ min-height: 100vh; display: grid; grid-template-rows: auto 1fr; }}
    .calendar-header {{
      position: sticky;
      top: 0;
      z-index: 4;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px clamp(16px, 4vw, 38px);
      background: #202631;
      color: white;
      border-bottom: 1px solid rgba(255,255,255,.12);
      box-shadow: 0 5px 18px rgba(24, 30, 41, .2);
    }}
    body.calendar-embedded .calendar-header {{ display: none; }}
    .calendar-heading {{ min-width: 180px; }}
    .calendar-kicker {{
      display: block;
      color: #b8c2d4;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .11em;
      text-transform: uppercase;
    }}
    h1 {{ margin: 3px 0 0; font-size: 24px; line-height: 1.2; }}
    .calendar-controls {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
    .calendar-button {{
      min-height: 34px;
      border: 1px solid rgba(255,255,255,.28);
      border-radius: 8px;
      background: rgba(255,255,255,.08);
      color: white;
      cursor: pointer;
      font-weight: 750;
      padding: 0 12px;
    }}
    .calendar-button:hover, .calendar-button:focus-visible {{ background: rgba(255,255,255,.16); }}
    .calendar-content {{
      display: grid;
      gap: 14px;
      width: min(1180px, 100%);
      margin: 0 auto;
      padding: 18px clamp(12px, 3vw, 34px) 40px;
    }}
    body.calendar-embedded .calendar-content {{ padding-top: 12px; }}
    .calendar-toolbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      flex-wrap: wrap;
    }}
    .calendar-month-title {{ margin: 0; font-size: 22px; line-height: 1.2; }}
    .calendar-summary {{ color: var(--muted); font-size: 13px; font-weight: 650; }}
    .calendar-legend {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
    .calendar-legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 26px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: white;
      color: #344054;
      font-size: 12px;
      font-weight: 750;
      padding: 0 9px;
    }}
    .calendar-swatch {{ width: 9px; height: 9px; border-radius: 999px; background: var(--calendar-color); }}
    .calendar-grid {{
      display: grid;
      grid-template-columns: repeat(7, minmax(0, 1fr));
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--paper);
      box-shadow: var(--shadow);
    }}
    .calendar-weekday {{
      min-height: 34px;
      display: grid;
      place-items: center;
      border-right: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      color: #475467;
      font-size: 12px;
      font-weight: 850;
      text-transform: uppercase;
    }}
    .calendar-weekday:nth-child(7n) {{ border-right: 0; }}
    .calendar-day {{
      min-height: 124px;
      display: grid;
      grid-template-rows: auto 1fr;
      gap: 6px;
      border-right: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      padding: 8px;
      background: white;
      min-width: 0;
    }}
    .calendar-day:nth-child(7n) {{ border-right: 0; }}
    .calendar-day.outside {{ background: #f8fafc; color: #98a2b3; }}
    .calendar-day.today {{ box-shadow: inset 0 0 0 2px #111827; }}
    .calendar-date {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-width: 0;
      font-size: 12px;
      font-weight: 850;
    }}
    .calendar-day-count {{ color: var(--muted); font-weight: 750; }}
    .calendar-events {{ display: grid; align-content: start; gap: 5px; min-width: 0; }}
    .calendar-event {{
      display: block;
      width: 100%;
      min-height: 24px;
      border: 0;
      border-left: 4px solid var(--calendar-color);
      border-radius: 6px;
      background: color-mix(in srgb, var(--calendar-color) 12%, white);
      color: #1f2937;
      cursor: pointer;
      font-size: 12px;
      font-weight: 760;
      line-height: 1.25;
      padding: 4px 6px;
      text-align: left;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .calendar-event.cancelled {{ opacity: .58; text-decoration: line-through; }}
    .calendar-event-time {{ color: #475467; font-weight: 850; margin-right: 4px; }}
    .calendar-empty {{
      min-height: 280px;
      display: grid;
      place-items: center;
      border: 1px dashed var(--line);
      border-radius: 10px;
      color: var(--muted);
      background: rgba(255,255,255,.72);
      font-weight: 750;
    }}
    .calendar-modal {{
      position: fixed;
      inset: 0;
      z-index: 20;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 18px;
      background: rgba(15, 23, 42, .42);
    }}
    .calendar-modal.open {{ display: flex; }}
    .calendar-dialog {{
      width: min(560px, 100%);
      max-height: min(760px, 92vh);
      overflow: auto;
      border: 1px solid rgba(255,255,255,.4);
      border-radius: 10px;
      background: white;
      box-shadow: 0 28px 70px rgba(15, 23, 42, .32);
    }}
    .calendar-dialog-header {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 16px 18px;
      border-bottom: 1px solid var(--line);
    }}
    .calendar-dialog-title {{ margin: 0; font-size: 19px; }}
    .calendar-dialog-body {{ display: grid; gap: 12px; padding: 16px 18px 18px; }}
    .calendar-detail-row {{ display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 12px; }}
    .calendar-detail-label {{ color: var(--muted); font-size: 12px; font-weight: 850; text-transform: uppercase; }}
    .calendar-detail-value {{ min-width: 0; white-space: pre-wrap; overflow-wrap: anywhere; }}
    .calendar-close {{
      width: 34px;
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: white;
      cursor: pointer;
      font-size: 18px;
      line-height: 1;
    }}
    @media (max-width: 760px) {{
      .calendar-header {{ position: static; align-items: flex-start; flex-direction: column; }}
      .calendar-day {{ min-height: 104px; padding: 6px; }}
      .calendar-event {{ font-size: 11px; }}
      .calendar-detail-row {{ grid-template-columns: 1fr; gap: 4px; }}
    }}
  </style>
</head>
<body>
  <main class="calendar-shell">
    <header class="calendar-header">
      <div class="calendar-heading">
        <span class="calendar-kicker">Calendar</span>
        <h1>{title}</h1>
      </div>
      <div class="calendar-controls">
        <button id="prevMonth" class="calendar-button" type="button">Previous</button>
        <button id="todayMonth" class="calendar-button" type="button">Today</button>
        <button id="nextMonth" class="calendar-button" type="button">Next</button>
      </div>
    </header>
    <section class="calendar-content">
      <div class="calendar-toolbar">
        <div>
          <h2 id="monthTitle" class="calendar-month-title"></h2>
          <div id="summary" class="calendar-summary" aria-live="polite"></div>
        </div>
        <div id="legend" class="calendar-legend"></div>
      </div>
      <div id="grid" class="calendar-grid" aria-label="Calendar month"></div>
      <div id="empty" class="calendar-empty" hidden>No events in this view.</div>
    </section>
  </main>
  <div id="modal" class="calendar-modal" role="dialog" aria-modal="true" aria-labelledby="dialogTitle">
    <article class="calendar-dialog">
      <header class="calendar-dialog-header">
        <h2 id="dialogTitle" class="calendar-dialog-title"></h2>
        <button id="closeModal" class="calendar-close" type="button" aria-label="Close">×</button>
      </header>
      <div id="dialogBody" class="calendar-dialog-body"></div>
    </article>
  </div>
  <script>
    const CALENDAR_DATA = {encoded};
    const params = new URLSearchParams(window.location.search);
    document.body.classList.toggle("calendar-embedded", params.get("embed") === "1");
    const grid = document.getElementById("grid");
    const empty = document.getElementById("empty");
    const legend = document.getElementById("legend");
    const summary = document.getElementById("summary");
    const monthTitle = document.getElementById("monthTitle");
    const modal = document.getElementById("modal");
    const dialogTitle = document.getElementById("dialogTitle");
    const dialogBody = document.getElementById("dialogBody");
    const calendarsById = new Map((CALENDAR_DATA.calendars || []).map((calendar) => [calendar.id, calendar]));
    const monthFormatter = new Intl.DateTimeFormat(undefined, {{ month: "long", year: "numeric" }});
    const timeFormatter = new Intl.DateTimeFormat(undefined, {{
      hour: "numeric", minute: "2-digit", timeZone: CALENDAR_DATA.timezone,
    }});
    const dateFormatter = new Intl.DateTimeFormat(undefined, {{
      weekday: "short", month: "short", day: "numeric", timeZone: CALENDAR_DATA.timezone,
    }});

    function localDate(dateText) {{
      const [year, month, day] = String(dateText || "").split("-").map(Number);
      return new Date(year || 1970, (month || 1) - 1, day || 1);
    }}

    function eventDate(event) {{
      if (event.start_date) return localDate(event.start_date);
      return new Date(String(event.start_at || ""));
    }}

    function dateKey(date) {{
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, "0");
      const day = String(date.getDate()).padStart(2, "0");
      return `${{year}}-${{month}}-${{day}}`;
    }}

    function initialMonth() {{
      const requested = params.get("month");
      if (/^\\d{{4}}-\\d{{2}}$/.test(requested || "")) {{
        const [year, month] = requested.split("-").map(Number);
        return new Date(year, month - 1, 1);
      }}
      if ((CALENDAR_DATA.events || []).length) {{
        const date = eventDate(CALENDAR_DATA.events[0]);
        if (!Number.isNaN(date.getTime())) return new Date(date.getFullYear(), date.getMonth(), 1);
      }}
      return localDate(CALENDAR_DATA.reference_date || dateKey(new Date()));
    }}

    let visibleMonth = initialMonth();

    function calendarColor(calendarId) {{
      const calendar = calendarsById.get(calendarId) || {{}};
      return calendar.color || "#2563eb";
    }}

    function calendarLabel(calendarId) {{
      const calendar = calendarsById.get(calendarId) || {{}};
      return calendar.label || calendarId;
    }}

    function eventTimeLabel(event) {{
      if (event.all_day || event.start_date) return "All day";
      const start = new Date(String(event.start_at || ""));
      if (Number.isNaN(start.getTime())) return "";
      return timeFormatter.format(start);
    }}

    function eventFullTimeLabel(event) {{
      if (event.start_date) {{
        const start = localDate(event.start_date);
        if (event.end_date && event.end_date !== event.start_date) {{
          return `${{dateFormatter.format(start)}} - ${{dateFormatter.format(localDate(event.end_date))}}`;
        }}
        return dateFormatter.format(start);
      }}
      const start = new Date(String(event.start_at || ""));
      const end = event.end_at ? new Date(String(event.end_at)) : null;
      if (Number.isNaN(start.getTime())) return "";
      if (end && !Number.isNaN(end.getTime())) {{
        return `${{dateFormatter.format(start)}} · ${{timeFormatter.format(start)}} - ${{timeFormatter.format(end)}}`;
      }}
      return `${{dateFormatter.format(start)}} · ${{timeFormatter.format(start)}}`;
    }}

    function eventsByDay() {{
      const grouped = new Map();
      for (const event of CALENDAR_DATA.events || []) {{
        const date = eventDate(event);
        if (Number.isNaN(date.getTime())) continue;
        const key = dateKey(date);
        if (!grouped.has(key)) grouped.set(key, []);
        grouped.get(key).push(event);
      }}
      return grouped;
    }}

    function element(tag, className = "", text = "") {{
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== "") node.textContent = text;
      return node;
    }}

    function renderLegend() {{
      legend.replaceChildren();
      for (const calendar of CALENDAR_DATA.calendars || []) {{
        if (!calendar.selected) continue;
        const item = element("span", "calendar-legend-item");
        const swatch = element("span", "calendar-swatch");
        swatch.style.setProperty("--calendar-color", calendar.color || "#2563eb");
        item.append(swatch, document.createTextNode(calendar.label || calendar.id));
        legend.append(item);
      }}
    }}

    function renderEvent(event) {{
      const button = element("button", "calendar-event");
      button.type = "button";
      button.style.setProperty("--calendar-color", calendarColor(event.calendar_id));
      button.classList.toggle("cancelled", String(event.status || "").toLowerCase() === "cancelled");
      const time = eventTimeLabel(event);
      if (time && time !== "All day") {{
        button.append(element("span", "calendar-event-time", time));
      }}
      button.append(document.createTextNode(event.title || "Untitled event"));
      button.title = `${{calendarLabel(event.calendar_id)}} · ${{eventFullTimeLabel(event)}}`;
      button.addEventListener("click", () => openEvent(event));
      return button;
    }}

    function renderMonth() {{
      const grouped = eventsByDay();
      const current = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 1);
      monthTitle.textContent = monthFormatter.format(current);
      const visibleEvents = CALENDAR_DATA.events || [];
      summary.textContent = `${{visibleEvents.length}} event${{visibleEvents.length === 1 ? "" : "s"}} · ${{(CALENDAR_DATA.calendars || []).filter((calendar) => calendar.selected).length}} calendar${{(CALENDAR_DATA.calendars || []).filter((calendar) => calendar.selected).length === 1 ? "" : "s"}}`;
      const start = new Date(current);
      start.setDate(current.getDate() - current.getDay());
      grid.replaceChildren();
      for (const label of ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]) {{
        grid.append(element("div", "calendar-weekday", label));
      }}
      const todayKey = dateKey(new Date());
      for (let index = 0; index < 42; index += 1) {{
        const day = new Date(start);
        day.setDate(start.getDate() + index);
        const key = dateKey(day);
        const dayEvents = grouped.get(key) || [];
        const cell = element("section", "calendar-day");
        cell.classList.toggle("outside", day.getMonth() !== current.getMonth());
        cell.classList.toggle("today", key === todayKey);
        const header = element("div", "calendar-date");
        header.append(
          element("span", "", String(day.getDate())),
          dayEvents.length ? element("span", "calendar-day-count", String(dayEvents.length)) : document.createTextNode(""),
        );
        const events = element("div", "calendar-events");
        dayEvents.forEach((event) => events.append(renderEvent(event)));
        cell.append(header, events);
        grid.append(cell);
      }}
      empty.hidden = visibleEvents.length > 0;
      notifyHost();
    }}

    function detailRow(label, value) {{
      if (!value) return null;
      const row = element("div", "calendar-detail-row");
      row.append(element("div", "calendar-detail-label", label), element("div", "calendar-detail-value", value));
      return row;
    }}

    function openEvent(event) {{
      dialogTitle.textContent = event.title || "Untitled event";
      dialogBody.replaceChildren();
      const rows = [
        detailRow("Calendar", calendarLabel(event.calendar_id)),
        detailRow("When", eventFullTimeLabel(event)),
        detailRow("Location", event.location || ""),
        detailRow("Status", event.status || ""),
        detailRow("Description", event.description || ""),
      ];
      for (const metadata of event.metadata || []) {{
        rows.push(detailRow(metadata.label || metadata.id || "Detail", metadata.value || ""));
      }}
      for (const row of rows) {{
        if (row) dialogBody.append(row);
      }}
      modal.classList.add("open");
    }}

    function closeModal() {{
      modal.classList.remove("open");
    }}

    function notifyHost() {{
      if (window.parent === window) return;
      window.parent.postMessage({{
        type: "electroboy-calendar-state",
        state: {{
          provider: CALENDAR_DATA.provider,
          month: `${{visibleMonth.getFullYear()}}-${{String(visibleMonth.getMonth() + 1).padStart(2, "0")}}`,
          calendars: CALENDAR_DATA.calendars || [],
        }},
      }}, window.location.origin);
    }}

    document.getElementById("prevMonth").addEventListener("click", () => {{
      visibleMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() - 1, 1);
      renderMonth();
    }});
    document.getElementById("todayMonth").addEventListener("click", () => {{
      const today = new Date();
      visibleMonth = new Date(today.getFullYear(), today.getMonth(), 1);
      renderMonth();
    }});
    document.getElementById("nextMonth").addEventListener("click", () => {{
      visibleMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + 1, 1);
      renderMonth();
    }});
    document.getElementById("closeModal").addEventListener("click", closeModal);
    modal.addEventListener("click", (event) => {{
      if (event.target === modal) closeModal();
    }});
    window.addEventListener("keydown", (event) => {{
      if (event.key === "Escape") closeModal();
    }});
    renderLegend();
    renderMonth();
  </script>
</body>
</html>""",
        HTTPStatus.OK,
    )
