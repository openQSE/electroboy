# ruff: noqa: E501
"""Provider-neutral Agenda HTML renderer."""

from __future__ import annotations

import html
import json
from http import HTTPStatus

AGENDA_STYLES = (
    {"id": "default", "label": "Default"},
    {"id": "hud", "label": "HUD"},
    {"id": "command-center", "label": "Command Center"},
)
AGENDA_STYLE_IDS = frozenset(style["id"] for style in AGENDA_STYLES)


def available_agenda_styles() -> list[dict[str, str]]:
    return [dict(style) for style in AGENDA_STYLES]


def normalize_agenda_style(value: object) -> str:
    style = str(value or "default").strip().lower()
    return style if style in AGENDA_STYLE_IDS else "default"


def render_agenda_html(
    payload: dict[str, object],
    *,
    style: object = "default",
) -> tuple[str, HTTPStatus]:
    """Render a normalized agenda snapshot as a self-contained pane."""

    selected_style = normalize_agenda_style(style)
    view_payload = {
        **payload,
        "style": selected_style,
        "styles": available_agenda_styles(),
    }
    encoded = json.dumps(view_payload, ensure_ascii=False).replace("<", "\\u003c")
    title = html.escape(str(payload.get("title") or "Agenda"))
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
      --ink: #2f2a25;
      --muted: #746a60;
      --line: #ded4c6;
      --paper: #fffdf8;
      --wash: #f5efe4;
      --accent: #356a5d;
      --accent-soft: #dcebe6;
      --warning: #9b4d28;
      --warning-soft: #fff0e4;
      --shadow: 0 12px 32px rgba(52, 40, 30, 0.12);
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
    button, select, input, textarea {{ font: inherit; }}
    button, select {{ min-height: 36px; }}
    .agenda {{ min-height: 100vh; }}
    .agenda-header {{
      position: sticky;
      top: 0;
      z-index: 5;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 18px clamp(18px, 4vw, 48px);
      border-bottom: 1px solid rgba(255,255,255,.18);
      background: #493a2f;
      color: #fffaf1;
      box-shadow: 0 4px 16px rgba(48, 34, 24, .14);
    }}
    .agenda-heading {{ min-width: 180px; }}
    .agenda-kicker {{
      display: block;
      color: #d8c8b7;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .12em;
      text-transform: uppercase;
    }}
    h1 {{ margin: 3px 0 0; font-family: Georgia, serif; font-size: 25px; }}
    .agenda-controls {{
      display: flex;
      align-items: flex-end;
      justify-content: flex-end;
      gap: 9px;
      flex-wrap: wrap;
    }}
    body.agenda-embedded .agenda-header {{
      display: none;
    }}
    .agenda-filter {{ display: grid; gap: 3px; font-size: 11px; font-weight: 750; }}
    .agenda-filter select {{
      border: 1px solid rgba(255,255,255,.35);
      border-radius: 9px;
      background: rgba(255,255,255,.09);
      color: #fffaf1;
      padding: 0 30px 0 11px;
    }}
    .agenda-filter option {{ color: var(--ink); background: white; }}
    .agenda-button {{
      border: 1px solid rgba(255,255,255,.4);
      border-radius: 9px;
      background: transparent;
      color: inherit;
      cursor: pointer;
      font-weight: 750;
      padding: 0 13px;
    }}
    .agenda-button:hover, .agenda-button:focus-visible {{ background: rgba(255,255,255,.12); }}
    .agenda-content {{
      width: min(1060px, 100%);
      margin: 0 auto;
      padding: 30px clamp(16px, 4vw, 46px) 64px;
    }}
    .agenda-summary {{ margin: 0 0 24px; color: var(--muted); }}
    .agenda-section {{ margin: 0 0 34px; scroll-margin-top: 110px; }}
    .agenda-section-heading {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin: 0 0 12px;
      font-family: Georgia, serif;
      font-size: 20px;
    }}
    .agenda-count {{
      display: inline-grid;
      min-width: 25px;
      height: 25px;
      place-items: center;
      border-radius: 999px;
      background: #e4dacb;
      font-family: Inter, sans-serif;
      font-size: 12px;
    }}
    .agenda-items {{ display: grid; gap: 11px; }}
    .agenda-item {{
      display: grid;
      grid-template-columns: 120px minmax(0, 1fr);
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--paper);
      box-shadow: 0 3px 12px rgba(54, 41, 30, .06);
    }}
    .agenda-item.proposed, .agenda-item.suggested {{ border-left: 5px solid #8a6db0; }}
    .agenda-item.warning {{ border-left: 5px solid var(--warning); }}
    .agenda-time {{
      padding: 18px 14px;
      border-right: 1px solid var(--line);
      color: var(--accent);
      font-size: 13px;
      font-weight: 850;
      text-align: center;
    }}
    .agenda-item-body {{ padding: 16px 18px 17px; min-width: 0; }}
    .agenda-item-top {{ display: flex; justify-content: space-between; gap: 14px; }}
    .agenda-item h3 {{ margin: 0; font-size: 17px; line-height: 1.3; }}
    .agenda-kind {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .08em;
      text-transform: uppercase;
      white-space: nowrap;
    }}
    .agenda-description {{ margin: 7px 0 0; color: #5e554d; white-space: pre-wrap; }}
    .agenda-badges, .agenda-people, .agenda-actions {{
      display: flex;
      align-items: center;
      gap: 7px;
      flex-wrap: wrap;
      margin-top: 10px;
    }}
    .agenda-badge, .agenda-person {{
      border-radius: 999px;
      background: var(--accent-soft);
      color: #29564b;
      font-size: 11px;
      font-weight: 800;
      padding: 4px 9px;
    }}
    .agenda-badge {{ background: #eee5f7; color: #634b7e; }}
    .agenda-warning {{
      margin-top: 11px;
      border-radius: 9px;
      background: var(--warning-soft);
      color: #74391f;
      padding: 9px 11px;
      font-size: 13px;
    }}
    .agenda-metadata {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 7px 14px;
      margin: 12px 0 0;
      padding-top: 11px;
      border-top: 1px solid #ece4d9;
    }}
    .agenda-meta {{ min-width: 0; }}
    .agenda-meta dt {{ color: var(--muted); font-size: 10px; font-weight: 800; text-transform: uppercase; }}
    .agenda-meta dd {{ margin: 2px 0 0; overflow-wrap: anywhere; font-size: 12px; }}
    .item-action {{
      min-height: 32px;
      border: 1px solid #bcb1a4;
      border-radius: 8px;
      background: white;
      color: var(--ink);
      cursor: pointer;
      font-size: 12px;
      font-weight: 800;
      padding: 0 11px;
    }}
    .item-action.primary {{ border-color: var(--accent); background: var(--accent); color: white; }}
    .item-action.danger {{ border-color: #b96245; color: #8a3e27; }}
    .agenda-empty {{
      border: 1px dashed #cbbdad;
      border-radius: 16px;
      background: rgba(255,255,255,.5);
      color: var(--muted);
      padding: 54px 24px;
      text-align: center;
    }}
    .agenda-modal-overlay {{
      position: fixed;
      inset: 0;
      z-index: 20;
      display: grid;
      place-items: center;
      padding: 20px;
      background: rgba(35, 27, 22, .62);
    }}
    .agenda-modal {{
      width: min(680px, 100%);
      max-height: min(820px, 92vh);
      overflow: auto;
      border-radius: 16px;
      background: var(--paper);
      box-shadow: var(--shadow);
    }}
    .agenda-modal header {{ display: flex; justify-content: space-between; gap: 16px; padding: 19px 22px; border-bottom: 1px solid var(--line); }}
    .agenda-modal h2 {{ margin: 0; font: 22px Georgia, serif; }}
    .agenda-modal form {{ display: grid; gap: 14px; padding: 20px 22px 24px; }}
    .editor-field {{ display: grid; gap: 5px; font-size: 13px; font-weight: 750; }}
    .editor-field input, .editor-field textarea, .editor-field select {{ border: 1px solid #bfb4a8; border-radius: 8px; padding: 9px 10px; background: white; color: var(--ink); }}
    .editor-error {{ color: #9b321f; min-height: 20px; }}
    .editor-actions {{ display: flex; justify-content: flex-end; gap: 9px; flex-wrap: wrap; }}
    body.agenda-style-command-center {{
      --ink: #16202a;
      --muted: #5f6d79;
      --line: #cbd7e1;
      --paper: #fbfdff;
      --wash: #e7eef4;
      --accent: #006b7a;
      --accent-soft: #d8f0f3;
      --warning: #9b4b20;
      --warning-soft: #fff0dd;
      --shadow: 0 16px 32px rgba(32, 52, 67, .12);
      background: var(--wash);
    }}
    body.agenda-style-command-center .agenda-header {{
      border-bottom: 1px solid #bdd0dc;
      background: #16313f;
      color: #f8fcff;
      box-shadow: 0 10px 28px rgba(21, 49, 63, .18);
    }}
    body.agenda-style-command-center .agenda-kicker {{
      color: #a9d9e0;
      letter-spacing: 0;
    }}
    body.agenda-style-command-center h1,
    body.agenda-style-command-center .agenda-section-heading {{
      font-family: Inter, ui-sans-serif, system-ui, sans-serif;
      font-weight: 850;
    }}
    body.agenda-style-command-center .agenda-content {{
      width: min(1280px, 100%);
    }}
    body.agenda-style-command-center .agenda-summary {{
      margin-bottom: 20px;
      font-weight: 750;
    }}
    body.agenda-style-command-center .agenda-section {{
      display: grid;
      grid-template-columns: 190px minmax(0, 1fr);
      gap: 18px;
      margin-bottom: 28px;
      padding-top: 18px;
      border-top: 1px solid #cbd7e1;
    }}
    body.agenda-style-command-center .agenda-section-heading {{
      align-content: start;
      align-self: start;
      display: grid;
      gap: 8px;
      margin: 0;
      color: #213547;
      font-size: 17px;
    }}
    body.agenda-style-command-center .agenda-count {{
      width: fit-content;
      border: 1px solid #a9cbd2;
      border-radius: 6px;
      background: #d8f0f3;
      color: #164f5a;
    }}
    body.agenda-style-command-center .agenda-items {{
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      align-items: start;
    }}
    body.agenda-style-command-center .agenda-item {{
      grid-template-columns: 1fr;
      border-color: #cad7e0;
      border-radius: 8px;
      background: var(--paper);
      box-shadow: var(--shadow);
    }}
    body.agenda-style-command-center .agenda-time {{
      border-right: 0;
      border-bottom: 1px solid #e0e9ef;
      background: #edf5f8;
      color: #006b7a;
      text-align: left;
    }}
    body.agenda-style-command-center .agenda-item-body {{
      padding: 15px 16px 16px;
    }}
    body.agenda-style-command-center .agenda-kind,
    body.agenda-style-command-center .agenda-meta dt {{
      letter-spacing: 0;
    }}
    body.agenda-style-command-center .agenda-badge,
    body.agenda-style-command-center .agenda-person {{
      border-radius: 6px;
    }}
    body.agenda-style-command-center .item-action {{
      border-radius: 6px;
    }}
    @media (max-width: 860px) {{
      body.agenda-style-command-center .agenda-section {{
        grid-template-columns: 1fr;
      }}
      body.agenda-style-command-center .agenda-items {{
        grid-template-columns: 1fr;
      }}
    }}
    body.agenda-style-hud {{
      --ink: #eefcf8;
      --muted: #9fb4ae;
      --line: rgba(116, 229, 212, .24);
      --paper: rgba(8, 23, 28, .9);
      --wash: #081116;
      --accent: #35dec8;
      --accent-soft: rgba(53, 222, 200, .16);
      --warning: #ffbd7a;
      --warning-soft: rgba(255, 189, 122, .14);
      --shadow: 0 26px 58px rgba(0, 0, 0, .32);
      background:
        linear-gradient(rgba(255, 255, 255, .035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 255, 255, .035) 1px, transparent 1px),
        #081116;
      background-size: 32px 32px, 32px 32px, auto;
    }}
    body.agenda-style-hud .agenda-header {{
      border-bottom: 1px solid rgba(116, 229, 212, .28);
      background: rgba(5, 17, 22, .94);
      color: #eefcf8;
      box-shadow: 0 14px 42px rgba(0, 0, 0, .42);
      backdrop-filter: blur(12px);
    }}
    body.agenda-style-hud .agenda-kicker,
    body.agenda-style-hud .agenda-kind,
    body.agenda-style-hud .agenda-meta dt {{
      letter-spacing: 0;
    }}
    body.agenda-style-hud h1 {{
      font-family: Inter, ui-sans-serif, system-ui, sans-serif;
      font-size: 24px;
      font-weight: 850;
    }}
    body.agenda-style-hud .agenda-content {{
      width: min(1180px, 100%);
      padding-top: 34px;
    }}
    body.agenda-style-hud .agenda-summary {{
      color: #b8cbc6;
    }}
    body.agenda-style-hud .agenda-section {{
      perspective: 1200px;
    }}
    body.agenda-style-hud .agenda-section-heading {{
      color: #eefcf8;
      font-family: Inter, ui-sans-serif, system-ui, sans-serif;
      font-size: 18px;
      font-weight: 850;
    }}
    body.agenda-style-hud .agenda-count {{
      border: 1px solid rgba(116, 229, 212, .32);
      background: rgba(53, 222, 200, .14);
      color: #7af1dd;
    }}
    body.agenda-style-hud .agenda-item {{
      position: relative;
      grid-template-columns: 128px minmax(0, 1fr);
      border-color: rgba(116, 229, 212, .25);
      border-radius: 8px;
      background:
        linear-gradient(135deg, rgba(15, 39, 46, .96), rgba(6, 17, 22, .92));
      box-shadow:
        0 18px 42px rgba(0, 0, 0, .3),
        inset 0 1px 0 rgba(255, 255, 255, .08);
      transform: rotateX(.8deg);
    }}
    body.agenda-style-hud .agenda-item::before {{
      content: "";
      position: absolute;
      inset: 0;
      border-radius: inherit;
      background:
        linear-gradient(90deg, rgba(53, 222, 200, .18), transparent 34%),
        linear-gradient(rgba(255, 255, 255, .05) 1px, transparent 1px);
      background-size: auto, 100% 18px;
      pointer-events: none;
    }}
    body.agenda-style-hud .agenda-time {{
      position: relative;
      z-index: 1;
      border-right-color: rgba(116, 229, 212, .22);
      background: rgba(53, 222, 200, .08);
      color: #7af1dd;
    }}
    body.agenda-style-hud .agenda-item-body {{
      position: relative;
      z-index: 1;
    }}
    body.agenda-style-hud .agenda-item h3 {{
      color: #f4fffb;
    }}
    body.agenda-style-hud .agenda-kind,
    body.agenda-style-hud .agenda-description,
    body.agenda-style-hud .agenda-meta dt,
    body.agenda-style-hud .agenda-meta dd {{
      color: #b8cbc6;
    }}
    body.agenda-style-hud .agenda-badge,
    body.agenda-style-hud .agenda-person {{
      border: 1px solid rgba(116, 229, 212, .24);
      background: rgba(53, 222, 200, .14);
      color: #a8fff0;
    }}
    body.agenda-style-hud .agenda-warning {{
      border: 1px solid rgba(255, 189, 122, .34);
      color: #ffd5a6;
    }}
    body.agenda-style-hud .agenda-metadata {{
      border-top-color: rgba(116, 229, 212, .18);
    }}
    body.agenda-style-hud .item-action {{
      border-color: rgba(116, 229, 212, .32);
      border-radius: 6px;
      background: rgba(7, 20, 25, .72);
      color: #eefcf8;
    }}
    body.agenda-style-hud .item-action.primary {{
      border-color: #35dec8;
      background: #1aa996;
      color: #061316;
    }}
    body.agenda-style-hud .agenda-empty {{
      border-color: rgba(116, 229, 212, .32);
      background: rgba(7, 20, 25, .72);
      color: #b8cbc6;
    }}
    body.agenda-style-hud .agenda-modal {{
      border: 1px solid rgba(116, 229, 212, .26);
      background: #0b1a20;
    }}
    body.agenda-style-hud .agenda-modal header {{
      border-bottom-color: rgba(116, 229, 212, .2);
    }}
    body.agenda-style-hud .editor-field input,
    body.agenda-style-hud .editor-field textarea,
    body.agenda-style-hud .editor-field select {{
      border-color: rgba(116, 229, 212, .28);
      background: rgba(5, 17, 22, .96);
      color: #eefcf8;
    }}
    @media (max-width: 720px) {{
      .agenda-header {{ position: static; align-items: flex-start; flex-direction: column; }}
      .agenda-controls {{ justify-content: flex-start; }}
      .agenda-item {{ grid-template-columns: 1fr; }}
      .agenda-time {{ border-right: 0; border-bottom: 1px solid var(--line); text-align: left; padding: 10px 16px; }}
    }}
  </style>
</head>
<body class="agenda-style-{selected_style}">
  <main class="agenda">
    <header class="agenda-header">
      <div class="agenda-heading">
        <span class="agenda-kicker">Agenda</span>
        <h1 id="agendaTitle">{title}</h1>
      </div>
      <div id="agendaControls" class="agenda-controls"></div>
    </header>
    <div class="agenda-content">
      <p id="agendaSummary" class="agenda-summary" aria-live="polite"></p>
      <div id="agendaSections"></div>
    </div>
  </main>
  <script>
    const AGENDA_DATA = {encoded};
    const controls = document.getElementById("agendaControls");
    const sectionsRoot = document.getElementById("agendaSections");
    const summary = document.getElementById("agendaSummary");
    const formatter = new Intl.DateTimeFormat(undefined, {{
      hour: "numeric", minute: "2-digit", timeZone: AGENDA_DATA.timezone,
    }});
    const dateFormatter = new Intl.DateTimeFormat(undefined, {{
      month: "short", day: "numeric", timeZone: AGENDA_DATA.timezone,
    }});
    const filterStorageKey = `electroboy.agenda.filters.${{AGENDA_DATA.provider}}`;
    const embeddedAgenda = new URLSearchParams(window.location.search).get("embed") === "1";
    document.body.classList.toggle("agenda-embedded", embeddedAgenda);

    function contextUrl(path) {{
      const url = new URL(path, window.location.origin);
      const contextId = new URLSearchParams(window.location.search).get("context_id");
      if (contextId) url.searchParams.set("context_id", contextId);
      return url.toString();
    }}

    function element(tag, className = "", text = "") {{
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== "") node.textContent = text;
      return node;
    }}

    function agendaRange() {{
      const parameters = new URLSearchParams(window.location.search);
      return {{
        range_start: parameters.get("range_start") || "",
        range_end: parameters.get("range_end") || "",
      }};
    }}

    function notifyAgendaHost() {{
      if (window.parent === window) return;
      window.parent.postMessage({{
        type: "electroboy-agenda-state",
        state: {{
          provider: AGENDA_DATA.provider,
          filters: AGENDA_DATA.filters || [],
          style: AGENDA_DATA.style || "default",
          styles: AGENDA_DATA.styles || [],
          range: agendaRange(),
          referenceDate: AGENDA_DATA.reference_date,
          itemCount: (AGENDA_DATA.items || []).length,
        }},
      }}, window.location.origin);
    }}

    function saveSelectedFilters(values) {{
      try {{ window.localStorage.setItem(filterStorageKey, JSON.stringify(values)); }}
      catch (_error) {{ /* Local persistence is optional. */ }}
    }}

    function selectedFilterValues(override = {{}}) {{
      return Object.fromEntries((AGENDA_DATA.filters || []).map((filter) => [
        filter.id,
        Object.hasOwn(override, filter.id) ? override[filter.id] : filter.value,
      ]));
    }}

    function itemTime(item) {{
      const value = item.start_at || item.due_at;
      if (!value) return "No date";
      const parsed = new Date(value);
      if (item.date_only) return dateFormatter.format(parsed);
      return `${{dateFormatter.format(parsed)}} · ${{formatter.format(parsed)}}`;
    }}

    function appendPeople(root, item) {{
      const people = [...(item.participants || []), ...(item.assignees || [])];
      if (!people.length) return;
      const row = element("div", "agenda-people");
      for (const person of people) {{
        const chip = element("span", "agenda-person", person.label || person.id || "");
        if (person.color) chip.style.setProperty("--person-color", person.color);
        row.append(chip);
      }}
      root.append(row);
    }}

    function appendMetadata(root, item) {{
      if (!(item.metadata || []).length) return;
      const list = element("dl", "agenda-metadata");
      for (const entry of item.metadata) {{
        const wrapper = element("div", "agenda-meta");
        wrapper.append(
          element("dt", "", entry.label || "Detail"),
          element("dd", "", entry.value == null ? "" : String(entry.value)),
        );
        list.append(wrapper);
      }}
      root.append(list);
    }}

    async function invokeAction(item, action) {{
      if (action.editor) {{
        await openEditor(item, action);
        return;
      }}
      const response = await fetch(contextUrl("/api/agenda/action"), {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          provider: AGENDA_DATA.provider,
          item_id: item.id,
          item_version: item.version,
          action_id: action.id,
          idempotency_key: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
        }}),
      }});
      if (!response.ok) throw new Error((await response.text()) || "Agenda action failed");
      window.location.reload();
    }}

    function closeModal(overlay, form, force = false) {{
      if (!force && form.dataset.dirty === "true" &&
          !window.confirm("Discard your unsaved changes?")) return false;
      overlay.remove();
      return true;
    }}

    async function openEditor(item, action) {{
      const query = new URLSearchParams({{
        provider: AGENDA_DATA.provider,
        item_id: item.id,
        item_version: String(item.version),
        action_id: action.id,
      }});
      const response = await fetch(contextUrl(`/api/agenda/editor?${{query}}`));
      if (!response.ok) throw new Error((await response.text()) || "Could not open editor");
      const editor = await response.json();
      const overlay = element("div", "agenda-modal-overlay");
      const dialog = element("section", "agenda-modal");
      dialog.setAttribute("role", "dialog");
      dialog.setAttribute("aria-modal", "true");
      const header = element("header");
      header.append(element("h2", "", editor.title || action.label || "Edit item"));
      const close = element("button", "agenda-button", "Cancel");
      close.type = "button";
      const form = element("form");
      const error = element("div", "editor-error");
      error.setAttribute("role", "alert");
      for (const field of editor.fields || []) {{
        const label = element("label", "editor-field", field.label || field.id);
        let input;
        if (field.type === "textarea") {{
          input = element("textarea");
        }} else if (field.type === "select") {{
          input = element("select");
          for (const option of field.options || []) {{
            const node = element("option", "", option.label || option.value);
            node.value = option.value;
            input.append(node);
          }}
        }} else {{
          input = element("input");
          input.type = field.type || "text";
        }}
        input.name = field.id;
        input.value = field.value == null ? "" : String(field.value);
        input.required = Boolean(field.required);
        input.disabled = Boolean(field.readonly);
        label.append(input);
        form.append(label);
      }}
      const actionRow = element("div", "editor-actions");
      for (const submission of editor.submissions || []) {{
        const button = element("button", `item-action ${{submission.style || ""}}`, submission.label || submission.id);
        button.type = "submit";
        button.value = submission.id;
        button.name = "submission";
        actionRow.append(button);
      }}
      form.append(error, actionRow);
      header.append(close);
      dialog.append(header, form);
      overlay.append(dialog);
      document.body.append(overlay);
      form.addEventListener("input", () => {{ form.dataset.dirty = "true"; }});
      close.addEventListener("click", () => closeModal(overlay, form));
      overlay.addEventListener("click", (event) => {{
        if (event.target === overlay) closeModal(overlay, form);
      }});
      dialog.addEventListener("keydown", (event) => {{
        if (event.key === "Escape") {{ event.preventDefault(); closeModal(overlay, form); }}
        if (event.key !== "Tab") return;
        const focusable = Array.from(dialog.querySelectorAll("button,input,select,textarea:not([disabled])"));
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {{ event.preventDefault(); last.focus(); }}
        else if (!event.shiftKey && document.activeElement === last) {{ event.preventDefault(); first.focus(); }}
      }});
      form.addEventListener("submit", async (event) => {{
        event.preventDefault();
        const submitter = event.submitter;
        const values = Object.fromEntries(new FormData(form).entries());
        delete values.submission;
        try {{
          const saved = await fetch(contextUrl("/api/agenda/editor"), {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{
              provider: AGENDA_DATA.provider,
              item_id: item.id,
              item_version: item.version,
              action_id: action.id,
              submission_id: submitter ? submitter.value : "save",
              values,
              idempotency_key: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
            }}),
          }});
          if (!saved.ok) throw new Error((await saved.text()) || "Could not save item");
          form.dataset.dirty = "false";
          closeModal(overlay, form, true);
          window.location.reload();
        }} catch (problem) {{ error.textContent = problem.message; }}
      }});
      (form.querySelector("input,select,textarea") || close).focus();
    }}

    function renderItem(item) {{
      const article = element("article", `agenda-item ${{item.status || ""}}`);
      article.dataset.itemId = item.id;
      article.append(element("div", "agenda-time", itemTime(item)));
      const body = element("div", "agenda-item-body");
      const top = element("div", "agenda-item-top");
      top.append(element("h3", "", item.title), element("span", "agenda-kind", item.kind));
      body.append(top);
      if (item.description) body.append(element("p", "agenda-description", item.description));
      if ((item.badges || []).length || item.confidence != null) {{
        const badges = element("div", "agenda-badges");
        for (const badge of item.badges || []) badges.append(element("span", "agenda-badge", badge));
        if (item.confidence != null) badges.append(element("span", "agenda-badge", `${{Math.round(item.confidence * 100)}}% confidence`));
        body.append(badges);
      }}
      appendPeople(body, item);
      if (item.warning) body.append(element("div", "agenda-warning", item.warning.message || String(item.warning)));
      appendMetadata(body, item);
      if ((item.actions || []).length) {{
        const actions = element("div", "agenda-actions");
        for (const action of item.actions) {{
          const button = element("button", `item-action ${{action.style || ""}}`, action.label || action.id);
          button.type = "button";
          button.addEventListener("click", async () => {{
            button.disabled = true;
            try {{ await invokeAction(item, action); }}
            catch (problem) {{ window.alert(problem.message); button.disabled = false; }}
          }});
          actions.append(button);
        }}
        body.append(actions);
      }}
      article.append(body);
      return article;
    }}

    function renderControls() {{
      controls.replaceChildren();
      if ((AGENDA_DATA.styles || []).length) {{
        const styleLabel = element("label", "agenda-filter");
        styleLabel.append(element("span", "", "Style"));
        const styleSelect = element("select");
        styleSelect.setAttribute("aria-label", "Agenda style");
        for (const style of AGENDA_DATA.styles || []) {{
          const node = element("option", "", style.label || style.id);
          node.value = style.id;
          node.selected = style.id === (AGENDA_DATA.style || "default");
          styleSelect.append(node);
        }}
        styleSelect.addEventListener("change", () => {{
          const url = new URL(window.location.href);
          url.searchParams.set("style", styleSelect.value);
          window.location.assign(url);
        }});
        styleLabel.append(styleSelect);
        controls.append(styleLabel);
      }}
      for (const filter of AGENDA_DATA.filters || []) {{
        const label = element("label", "agenda-filter");
        label.append(element("span", "", filter.label));
        const select = element("select");
        select.setAttribute("aria-label", filter.label);
        for (const option of filter.options || []) {{
          const node = element("option", "", option.label);
          node.value = option.value;
          node.selected = option.value === filter.value;
          select.append(node);
        }}
        select.addEventListener("change", () => {{
          const url = new URL(window.location.href);
          url.searchParams.set(`filter.${{filter.id}}`, select.value);
          const selected = Object.fromEntries(
            Array.from(controls.querySelectorAll("select[data-filter-id]")).map(
              (entry) => [entry.dataset.filterId, entry.value],
            ),
          );
          selected[filter.id] = select.value;
          saveSelectedFilters(selected);
          window.location.assign(url);
        }});
        select.dataset.filterId = filter.id;
        label.append(select);
        controls.append(label);
      }}
      const today = element("button", "agenda-button", "Today");
      today.type = "button";
      today.addEventListener("click", () => document.getElementById("section-today")?.scrollIntoView({{ behavior: "smooth" }}));
      controls.append(today);
    }}

    function renderAgenda() {{
      renderControls();
      sectionsRoot.replaceChildren();
      const itemCount = (AGENDA_DATA.items || []).length;
      summary.textContent = itemCount === 1 ? "1 item" : `${{itemCount}} items`;
      notifyAgendaHost();
      if (!(AGENDA_DATA.sections || []).length) {{
        sectionsRoot.append(element("section", "agenda-empty", AGENDA_DATA.empty_message || "Nothing is on the agenda."));
        return;
      }}
      for (const section of AGENDA_DATA.sections) {{
        const container = element("section", "agenda-section");
        container.id = `section-${{section.id}}`;
        const heading = element("h2", "agenda-section-heading");
        heading.append(element("span", "", section.label), element("span", "agenda-count", String(section.items.length)));
        const items = element("div", "agenda-items");
        for (const item of section.items) items.append(renderItem(item));
        container.append(heading, items);
        sectionsRoot.append(container);
      }}
    }}

    function handleAgendaCommand(event) {{
      if (event.origin !== window.location.origin || event.source !== window.parent) return;
      const command = event.data || {{}};
      if (command.type !== "electroboy-agenda-command") return;
      if (command.action === "request-state") {{
        notifyAgendaHost();
        return;
      }}
      if (command.action === "jump-today") {{
        document.getElementById("section-today")?.scrollIntoView({{ behavior: "smooth" }});
        return;
      }}
      const url = new URL(window.location.href);
      if (command.action === "set-filter") {{
        const filter = (AGENDA_DATA.filters || []).find(
          (entry) => entry.id === String(command.filterId || ""),
        );
        const value = String(command.value || "");
        if (!filter || !(filter.options || []).some((option) => option.value === value)) return;
        url.searchParams.set(`filter.${{filter.id}}`, value);
        saveSelectedFilters(selectedFilterValues({{ [filter.id]: value }}));
      }} else if (command.action === "set-range") {{
        for (const [parameter, value] of [
          ["range_start", command.rangeStart],
          ["range_end", command.rangeEnd],
        ]) {{
          if (value) url.searchParams.set(parameter, String(value));
          else url.searchParams.delete(parameter);
        }}
      }} else if (command.action === "set-style") {{
        const value = String(command.style || "");
        if (!(AGENDA_DATA.styles || []).some((style) => style.id === value)) return;
        url.searchParams.set("style", value);
      }} else if (command.action === "reset") {{
        for (const filter of AGENDA_DATA.filters || []) {{
          url.searchParams.delete(`filter.${{filter.id}}`);
        }}
        url.searchParams.delete("range_start");
        url.searchParams.delete("range_end");
        try {{ window.localStorage.removeItem(filterStorageKey); }}
        catch (_error) {{ /* Local persistence is optional. */ }}
      }} else {{
        return;
      }}
      window.location.assign(url);
    }}

    function restoreStoredFilters() {{
      const url = new URL(window.location.href);
      if ((AGENDA_DATA.filters || []).some((filter) =>
        url.searchParams.has(`filter.${{filter.id}}`),
      )) return false;
      let stored = null;
      try {{ stored = JSON.parse(window.localStorage.getItem(filterStorageKey)); }}
      catch (_error) {{ return false; }}
      if (!stored || typeof stored !== "object") return false;
      let changed = false;
      for (const filter of AGENDA_DATA.filters || []) {{
        const available = new Set((filter.options || []).map((option) => option.value));
        if (available.has(stored[filter.id]) && stored[filter.id] !== filter.value) {{
          url.searchParams.set(`filter.${{filter.id}}`, stored[filter.id]);
          changed = true;
        }}
      }}
      if (changed) window.location.replace(url);
      return changed;
    }}

    window.addEventListener("message", handleAgendaCommand);
    if (!restoreStoredFilters()) renderAgenda();
  </script>
</body>
</html>
""",
        HTTPStatus.OK,
    )
