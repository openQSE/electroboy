# ruff: noqa: E501
"""Provider-neutral Calendar HTML renderer."""

from __future__ import annotations

import html
import json
from http import HTTPStatus

from .agenda_workspace import normalize_agenda_style


def render_calendar_html(
    payload: dict[str, object],
    *,
    style: object = "default",
) -> tuple[str, HTTPStatus]:
    """Render a normalized calendar snapshot as a self-contained pane."""

    selected_style = normalize_agenda_style(style)
    snapshot = dict(payload)
    snapshot["style"] = selected_style
    encoded = json.dumps(snapshot, ensure_ascii=False).replace("<", "\\u003c")
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
      color-scheme: var(--theme-color-scheme, light);
      --ink: var(--theme-text, #23272f);
      --muted: var(--theme-muted, #667085);
      --line: var(--theme-border, #d9dee7);
      --paper: var(--theme-panel, #ffffff);
      --wash: var(--theme-bg, #f4f6f9);
      --panel: var(--theme-panel, #eef2f7);
      --shadow: 0 14px 34px rgba(20, 28, 43, .12);
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ min-height: 100%; height: 100%; }}
    body {{
      margin: 0;
      background: var(--wash);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system,
        BlinkMacSystemFont, "Segoe UI", sans-serif;
      overflow: hidden;
    }}
    button {{ font: inherit; }}
    .calendar-shell {{ min-height: 100vh; height: 100vh; display: grid; grid-template-rows: auto minmax(0, 1fr); }}
    .calendar-header {{
      position: sticky;
      top: 0;
      z-index: 4;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px clamp(16px, 4vw, 38px);
      background: var(--theme-panel, #202631);
      color: var(--theme-text, white);
      border-bottom: 1px solid color-mix(in srgb, var(--theme-border, #ffffff) 12%, transparent);
      box-shadow: 0 5px 18px rgba(24, 30, 41, .2);
    }}
    body.calendar-embedded .calendar-header {{ display: none; }}
    .calendar-heading {{ min-width: 180px; }}
    .calendar-kicker {{
      display: block;
      color: var(--theme-text, #b8c2d4);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .11em;
      text-transform: uppercase;
    }}
    h1 {{ margin: 3px 0 0; font-size: 24px; line-height: 1.2; }}
    .calendar-controls {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
    .calendar-button,
    .calendar-month-input {{
      min-height: 34px;
      border: 1px solid color-mix(in srgb, var(--theme-border, #ffffff) 28%, transparent);
      border-radius: 8px;
      background: color-mix(in srgb, var(--theme-panel, #ffffff) 8%, transparent);
      color: var(--theme-text, white);
      cursor: pointer;
      font-weight: 750;
      padding: 0 12px;
    }}
    .calendar-month-input {{
      width: 210px;
      color-scheme: var(--theme-color-scheme, dark);
    }}
    .calendar-button:hover, .calendar-button:focus-visible {{ background: color-mix(in srgb, var(--theme-panel, #ffffff) 16%, transparent); }}
    .calendar-content {{
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      gap: 14px;
      width: 100%;
      height: 100%;
      min-height: 0;
      margin: 0;
      overflow: hidden;
      padding: 14px clamp(10px, 2vw, 24px) 18px;
    }}
    body.calendar-embedded .calendar-content {{ padding-top: 14px; }}
    .calendar-toolbar {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
    }}
    .calendar-toolbar-main {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      flex-wrap: wrap;
      min-width: 0;
    }}
    .calendar-month-title {{
      margin: 0;
      border: 0;
      background: transparent;
      color: inherit;
      cursor: pointer;
      font: inherit;
      font-size: 22px;
      font-weight: 850;
      line-height: 1.2;
      padding: 0;
      text-align: left;
    }}
    .calendar-summary {{ color: var(--muted); font-size: 13px; font-weight: 650; }}
    .calendar-legend {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
    .calendar-legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 26px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--theme-panel, white);
      color: var(--theme-text, #344054);
      font-size: 12px;
      font-weight: 750;
      padding: 0 9px;
    }}
    .calendar-swatch {{ width: 9px; height: 9px; border-radius: 999px; background: var(--calendar-color); }}
    .calendar-toolbar .calendar-controls {{
      justify-content: flex-end;
    }}
    .calendar-toolbar .calendar-button,
    .calendar-toolbar .calendar-month-input {{
      border-color: var(--line);
      background: var(--theme-panel, white);
      color: var(--theme-text, #344054);
    }}
    .calendar-toolbar .calendar-button {{
      width: 38px;
      padding: 0;
      font-size: 22px;
      line-height: 1;
    }}
    .calendar-toolbar .calendar-button:hover,
    .calendar-toolbar .calendar-button:focus-visible,
    .calendar-toolbar .calendar-month-input:focus-visible {{
      border-color: var(--theme-accent, #2563eb);
      background: var(--theme-raised, #f8fafc);
      outline: 2px solid color-mix(in srgb, var(--theme-accent, #2563eb) 18%, transparent);
      outline-offset: 2px;
    }}
    .calendar-canvas-viewport {{
      position: relative;
      display: grid;
      justify-items: center;
      align-items: start;
      min-height: 0;
      overflow: hidden;
      border-radius: 0;
      cursor: default;
      touch-action: pan-y;
    }}
    .calendar-canvas {{
      --calendar-size: min(980px, calc(100vw - 48px), calc(100vh - 128px));
      display: block;
      width: var(--calendar-size);
      height: var(--calendar-size);
      margin: 0 auto;
      transform: translate(var(--calendar-pan-x, 0px), var(--calendar-pan-y, 0px)) scale(var(--calendar-zoom, 1));
      transform-origin: 0 0;
      transition: transform .12s ease;
      will-change: transform;
    }}
    body.calendar-day-open .calendar-shell {{
      filter: blur(3px) saturate(.72);
      transform: scale(.992);
      transition: filter .28s ease, transform .32s cubic-bezier(.2, .8, .2, 1);
    }}
    body.calendar-panning,
    body.calendar-panning .calendar-canvas-viewport {{
      cursor: grabbing;
      user-select: none;
    }}
    body.calendar-panning .calendar-canvas {{
      transition: none;
    }}
    .calendar-grid {{
      --calendar-span-lane-height: 24px;
      --calendar-span-top: 28px;
      --calendar-span-divider: color-mix(in srgb, var(--line) 88%, transparent);
      position: relative;
      display: grid;
      grid-template-columns: repeat(7, minmax(0, 1fr));
      grid-template-rows: 34px repeat(6, minmax(0, 1fr));
      height: 100%;
      overflow: hidden;
      border: 0;
      border-radius: 0;
      background: var(--paper);
      box-shadow: none;
    }}
    .calendar-weekday {{
      min-height: 34px;
      display: grid;
      place-items: center;
      border-right: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      color: var(--theme-text, #475467);
      font-size: 12px;
      font-weight: 850;
      text-transform: uppercase;
    }}
    .calendar-weekday:nth-child(7n) {{ border-right: 0; }}
    .calendar-day {{
      position: relative;
      z-index: 1;
      min-height: 0;
      display: grid;
      grid-template-rows: auto 1fr;
      gap: 6px;
      border: 0;
      border-right: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      padding: 8px;
      background: var(--theme-panel, white);
      min-width: 0;
      cursor: pointer;
    }}
    .calendar-day:nth-child(7n) {{ border-right: 0; }}
    .calendar-day.outside {{ background: var(--theme-raised, #f8fafc); color: var(--theme-muted, #98a2b3); }}
    .calendar-day.today {{ box-shadow: inset 0 0 0 2px #111827; }}
    .calendar-day.selected {{
      box-shadow: inset 0 0 0 3px #2563eb;
      z-index: 1;
    }}
    .calendar-date {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-width: 0;
      font-size: 12px;
      font-weight: 850;
    }}
    .calendar-day-count {{ color: var(--muted); font-weight: 750; }}
    .calendar-events {{
      display: grid;
      align-content: start;
      gap: 5px;
      min-width: 0;
      margin-top: calc(var(--calendar-row-lanes, 0) * var(--calendar-span-lane-height));
    }}
    .calendar-event,
    .calendar-event-span {{
      border: 0;
      border-left: 4px solid var(--calendar-color);
      border-radius: 6px;
      background: color-mix(in srgb, var(--calendar-color) 12%, var(--theme-panel, white));
      color: var(--theme-text, #1f2937);
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
    .calendar-event {{
      display: block;
      width: 100%;
      min-height: 24px;
    }}
    .calendar-event-span {{
      position: relative;
      z-index: 4;
      display: flex;
      align-items: center;
      min-width: 0;
      height: 20px;
      margin: calc(var(--calendar-span-top) + var(--calendar-span-lane, 0) * var(--calendar-span-lane-height)) 2px 0;
      box-shadow: 0 7px 18px color-mix(in srgb, var(--calendar-color) 18%, transparent);
    }}
    .calendar-event-span::after {{
      content: "";
      position: absolute;
      inset: 0;
      border-radius: inherit;
      pointer-events: none;
      background:
        linear-gradient(to right, transparent calc(100% - 1px), var(--calendar-span-divider) calc(100% - 1px)) 0 0 / calc(100% / var(--calendar-span-days, 1)) 100%;
    }}
    .calendar-event-span.continues-before {{
      border-left-width: 0;
      border-top-left-radius: 0;
      border-bottom-left-radius: 0;
      padding-left: 8px;
    }}
    .calendar-event-span.continues-after {{
      border-top-right-radius: 0;
      border-bottom-right-radius: 0;
    }}
    .calendar-event.cancelled,
    .calendar-event-span.cancelled {{
      opacity: .58;
      text-decoration: line-through;
    }}
    .calendar-event-time {{ color: var(--theme-text, #475467); font-weight: 850; margin-right: 4px; }}
    .calendar-day-panel-overlay {{
      position: fixed;
      inset: 0;
      z-index: 18;
      display: grid;
      place-items: center;
      padding: clamp(16px, 4vw, 44px);
      background:
        radial-gradient(circle at center, color-mix(in srgb, var(--theme-accent-soft, #62e6d9) 14%, transparent), transparent 34%),
        color-mix(in srgb, var(--theme-inset, #030c10) 46%, transparent);
      opacity: 0;
      pointer-events: none;
      transition: opacity .28s ease;
    }}
    .calendar-day-panel-overlay[hidden] {{ display: none; }}
    .calendar-day-panel-overlay.open {{
      opacity: 1;
      pointer-events: auto;
    }}
    .calendar-day-panel-overlay.closing {{
      opacity: 0;
    }}
    .calendar-day-panel {{
      display: grid;
      width: min(760px, 100%);
      max-height: min(82vh, 760px);
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--paper);
      box-shadow:
        0 42px 92px rgba(15, 23, 42, .32),
        inset 0 1px 0 rgba(255, 255, 255, .08);
      opacity: 0;
      transform: perspective(1200px) rotateX(4deg) translateY(18px) scale(.96);
      transition: opacity .28s ease, transform .34s cubic-bezier(.2, .8, .2, 1);
    }}
    .calendar-day-panel-overlay.open .calendar-day-panel {{
      opacity: 1;
      transform: perspective(1200px) rotateX(0) translateY(0) scale(1);
    }}
    .calendar-day-panel-overlay.closing .calendar-day-panel {{
      opacity: 0;
      transform: perspective(1200px) rotateX(3deg) translateY(14px) scale(.96);
    }}
    .calendar-day-panel-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    .calendar-day-panel-title {{
      margin: 0;
      font-size: 17px;
      line-height: 1.2;
    }}
    .calendar-day-panel-heading {{
      display: grid;
      gap: 4px;
      min-width: 0;
    }}
    .calendar-day-panel-summary {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
    }}
    .calendar-day-slots {{
      display: grid;
      max-height: min(62vh, 580px);
      overflow: auto;
      background: var(--paper);
    }}
    .calendar-day-slot {{
      display: grid;
      grid-template-columns: 88px minmax(0, 1fr);
      min-height: 44px;
      border-bottom: 1px solid var(--line);
    }}
    .calendar-day-slot-time {{
      border-right: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
      padding: 10px 12px;
      text-align: right;
    }}
    .calendar-day-slot-events {{
      display: grid;
      align-content: start;
      gap: 6px;
      padding: 7px 8px;
      min-width: 0;
    }}
    .calendar-day-slot-empty {{
      color: color-mix(in srgb, var(--muted) 70%, transparent);
      font-size: 12px;
      font-weight: 650;
    }}
    .calendar-day-slot .calendar-event {{
      max-width: 460px;
      white-space: normal;
    }}
    .calendar-modal {{
      position: fixed;
      inset: 0;
      z-index: 20;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 18px;
      background: color-mix(in srgb, var(--theme-bg, #0f172a) 42%, transparent);
    }}
    .calendar-modal.open {{ display: flex; }}
    .calendar-dialog {{
      width: min(560px, 100%);
      max-height: min(760px, 92vh);
      overflow: auto;
      border: 1px solid color-mix(in srgb, var(--theme-border, #ffffff) 40%, transparent);
      border-radius: 10px;
      background: var(--theme-panel, white);
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
      display: grid;
      place-items: center;
      flex: 0 0 auto;
      width: 34px;
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 8px;
      appearance: none;
      padding: 0;
      background: color-mix(in srgb, var(--panel) 70%, var(--theme-panel, white));
      color: var(--ink);
      cursor: pointer;
      font: 850 20px/1 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, .42);
      transition: border-color .16s ease, background .16s ease, color .16s ease, box-shadow .16s ease, transform .12s ease;
    }}
    .calendar-close:hover,
    .calendar-close:focus-visible {{
      border-color: color-mix(in srgb, var(--ink) 28%, var(--line));
      background: color-mix(in srgb, var(--panel) 58%, var(--theme-panel, white));
      outline: 2px solid color-mix(in srgb, var(--ink) 16%, transparent);
      outline-offset: 2px;
    }}
    .calendar-close:active {{
      transform: translateY(1px);
    }}
    body.calendar-style-hud,
    body.calendar-style-radar {{
      color-scheme: var(--theme-color-scheme, dark);
    }}
    body.calendar-style-hud {{
      --ink: var(--theme-text, #eefcf8);
      --muted: var(--theme-muted, #9fb4ae);
      --line: color-mix(in srgb, var(--theme-accent, #74e5d4) 24%, transparent);
      --paper: color-mix(in srgb, var(--theme-text, #08171c) 90%, transparent);
      --wash: var(--theme-bg, #081116);
      --panel: color-mix(in srgb, var(--theme-panel, #35dec8) 10%, transparent);
      --shadow: 0 26px 58px rgba(0, 0, 0, .32);
      background:
        linear-gradient(color-mix(in srgb, var(--theme-panel, #ffffff) 3.5%, transparent) 1px, transparent 1px),
        linear-gradient(90deg, color-mix(in srgb, var(--theme-panel, #ffffff) 3.5%, transparent) 1px, transparent 1px),
        var(--theme-inset, #081116);
      background-size: 32px 32px, 32px 32px, auto;
    }}
    body.calendar-style-hud .calendar-content {{
      padding: clamp(12px, 2vw, 24px);
    }}
    body.calendar-style-hud .calendar-toolbar {{
      border: 1px solid color-mix(in srgb, var(--theme-accent, #74e5d4) 26%, transparent);
      border-radius: 8px;
      background: color-mix(in srgb, var(--theme-inset, #051116) 86%, transparent);
      box-shadow:
        0 18px 42px rgba(0, 0, 0, .26),
        inset 0 1px 0 rgba(255, 255, 255, .07);
    }}
    body.calendar-style-hud .calendar-month-title,
    body.calendar-style-hud .calendar-day-panel-title,
    body.calendar-style-hud .calendar-dialog-title {{
      color: var(--theme-text, #f4fffb);
      font-weight: 850;
    }}
    body.calendar-style-hud .calendar-summary,
    body.calendar-style-hud .calendar-day-panel-summary {{
      color: var(--theme-text, #b8cbc6);
    }}
    body.calendar-style-hud .calendar-toolbar .calendar-button,
    body.calendar-style-hud .calendar-toolbar .calendar-month-input,
    body.calendar-style-hud .calendar-close {{
      border-color: color-mix(in srgb, var(--theme-accent, #74e5d4) 32%, transparent);
      background: color-mix(in srgb, var(--theme-inset, #071419) 72%, transparent);
      color: var(--theme-text, #eefcf8);
    }}
    body.calendar-style-hud .calendar-toolbar .calendar-button:hover,
    body.calendar-style-hud .calendar-toolbar .calendar-button:focus-visible,
    body.calendar-style-hud .calendar-toolbar .calendar-month-input:focus-visible,
    body.calendar-style-hud .calendar-close:hover,
    body.calendar-style-hud .calendar-close:focus-visible {{
      border-color: var(--theme-accent, #35dec8);
      background: color-mix(in srgb, var(--theme-accent-soft, #35dec8) 16%, transparent);
      outline-color: color-mix(in srgb, var(--theme-accent, #35dec8) 20%, transparent);
    }}
    body.calendar-style-hud .calendar-grid {{
      --calendar-span-divider: color-mix(in srgb, var(--theme-accent, #74e5d4) 30%, transparent);
      background:
        linear-gradient(135deg, color-mix(in srgb, var(--theme-panel, #0f272e) 92%, transparent), color-mix(in srgb, var(--theme-inset, #061116) 88%, transparent));
      box-shadow:
        0 24px 58px rgba(0, 0, 0, .28),
        inset 0 1px 0 rgba(255, 255, 255, .06);
    }}
    body.calendar-style-hud .calendar-weekday,
    body.calendar-style-hud .calendar-day,
    body.calendar-style-hud .calendar-day-panel-header,
    body.calendar-style-hud .calendar-day-slot {{
      border-color: color-mix(in srgb, var(--theme-accent, #74e5d4) 22%, transparent);
      background: color-mix(in srgb, var(--theme-accent-soft, #35dec8) 8%, transparent);
      color: var(--theme-text, #eefcf8);
    }}
    body.calendar-style-hud .calendar-day {{
      background:
        linear-gradient(135deg, color-mix(in srgb, var(--theme-panel, #0f272e) 72%, transparent), color-mix(in srgb, var(--theme-inset, #061116) 68%, transparent));
    }}
    body.calendar-style-hud .calendar-day.outside {{
      background: color-mix(in srgb, var(--theme-inset, #051116) 58%, transparent);
      color: var(--theme-muted, #637b77);
    }}
    body.calendar-style-hud .calendar-day.today,
    body.calendar-style-hud .calendar-day.selected {{
      box-shadow:
        inset 0 0 0 2px #35dec8,
        0 0 24px rgba(53, 222, 200, .12);
    }}
    body.calendar-style-hud .calendar-event,
    body.calendar-style-hud .calendar-event-span {{
      background: color-mix(in srgb, var(--calendar-color) 24%, color-mix(in srgb, var(--theme-inset, #071419) 90%, transparent));
      color: var(--theme-text, #f4fffb);
    }}
    body.calendar-style-hud .calendar-event-time,
    body.calendar-style-hud .calendar-day-slot-time {{
      border-color: color-mix(in srgb, var(--theme-accent, #74e5d4) 22%, transparent);
      color: var(--theme-accent, #7af1dd);
    }}
    body.calendar-style-hud .calendar-legend-item,
    body.calendar-style-hud .calendar-dialog,
    body.calendar-style-hud .calendar-day-panel {{
      border-color: color-mix(in srgb, var(--theme-accent, #74e5d4) 26%, transparent);
      background: color-mix(in srgb, var(--theme-bg, #08171c) 94%, transparent);
      color: var(--theme-text, #eefcf8);
    }}
    body.calendar-style-command-center {{
      --ink: var(--theme-text, #16202a);
      --muted: var(--theme-muted, #5f6d79);
      --line: var(--theme-border, #cbd7e1);
      --paper: var(--theme-panel, #fbfdff);
      --wash: var(--theme-bg, #e7eef4);
      --panel: var(--theme-panel, #edf5f8);
      --shadow: 0 16px 32px rgba(32, 52, 67, .12);
      background: var(--wash);
    }}
    body.calendar-style-command-center .calendar-toolbar {{
      border: 1px solid var(--theme-border, #bdd0dc);
      border-radius: 8px;
      background: var(--theme-panel, #fbfdff);
      box-shadow: var(--shadow);
    }}
    body.calendar-style-command-center .calendar-month-title {{
      color: var(--theme-text, #213547);
      font-weight: 850;
    }}
    body.calendar-style-command-center .calendar-toolbar .calendar-button,
    body.calendar-style-command-center .calendar-toolbar .calendar-month-input,
    body.calendar-style-command-center .calendar-close {{
      border-color: var(--theme-border, #a9cbd2);
      border-radius: 6px;
      background: var(--theme-raised, #edf5f8);
      color: var(--theme-accent, #164f5a);
    }}
    body.calendar-style-command-center .calendar-grid {{
      --calendar-span-divider: color-mix(in srgb, var(--theme-text, #cbd7e1) 90%, transparent);
      background: var(--theme-panel, #fbfdff);
      box-shadow: var(--shadow);
    }}
    body.calendar-style-command-center .calendar-weekday {{
      border-color: var(--theme-border, #cad7e0);
      background: var(--theme-panel, #16313f);
      color: var(--theme-accent, #d8f0f3);
    }}
    body.calendar-style-command-center .calendar-day {{
      border-color: var(--theme-border, #d4dee6);
      background: var(--theme-panel, #fbfdff);
    }}
    body.calendar-style-command-center .calendar-day.outside {{
      background: var(--theme-raised, #eef4f8);
      color: var(--theme-muted, #8ca0ad);
    }}
    body.calendar-style-command-center .calendar-day.today,
    body.calendar-style-command-center .calendar-day.selected {{
      box-shadow: inset 0 0 0 2px #006b7a;
    }}
    body.calendar-style-command-center .calendar-event,
    body.calendar-style-command-center .calendar-event-span {{
      border-radius: 6px;
      background: color-mix(in srgb, var(--calendar-color) 18%, var(--theme-panel, #fbfdff));
      color: var(--theme-text, #16202a);
    }}
    body.calendar-style-command-center .calendar-event-time {{
      color: var(--theme-accent, #006b7a);
    }}
    body.calendar-style-timeline-stack {{
      --ink: var(--theme-text, #1d2a2b);
      --muted: var(--theme-muted, #637271);
      --line: var(--theme-border, #c6d4d2);
      --paper: var(--theme-panel, #fbfdfc);
      --wash: var(--theme-bg, #e9f0ef);
      --panel: var(--theme-panel, #edf7f5);
      --shadow: 0 20px 44px rgba(35, 55, 56, .16);
      background:
        linear-gradient(90deg, color-mix(in srgb, var(--theme-accent-soft, #26706a) 12%, transparent) 1px, transparent 1px),
        var(--wash);
      background-size: 44px 100%, auto;
    }}
    body.calendar-style-timeline-stack .calendar-toolbar {{
      border: 1px solid var(--theme-border, #c4d4d0);
      border-radius: 8px;
      background: var(--theme-panel, #fbfdfc);
      box-shadow: var(--shadow);
    }}
    body.calendar-style-timeline-stack .calendar-month-title {{
      color: var(--theme-text, #243b3d);
      font-weight: 850;
    }}
    body.calendar-style-timeline-stack .calendar-grid {{
      --calendar-span-divider: color-mix(in srgb, var(--theme-accent, #26706a) 26%, transparent);
      background: var(--theme-panel, #fbfdfc);
      box-shadow: var(--shadow);
      transform: perspective(1400px) rotateX(1.2deg);
      transform-origin: center top;
    }}
    body.calendar-style-timeline-stack .calendar-weekday {{
      border-color: var(--theme-border, #c4d4d0);
      background: var(--theme-raised, #243b3d);
      color: var(--theme-text, #f7fffd);
    }}
    body.calendar-style-timeline-stack .calendar-day {{
      border-color: var(--theme-border, #c4d4d0);
      background: linear-gradient(135deg, var(--theme-panel, #fbfdfc), var(--theme-raised, #f2f8f6));
    }}
    body.calendar-style-timeline-stack .calendar-day.outside {{
      background: var(--theme-raised, #edf3f1);
      color: var(--theme-muted, #879895);
    }}
    body.calendar-style-timeline-stack .calendar-day.today,
    body.calendar-style-timeline-stack .calendar-day.selected {{
      box-shadow: inset 0 0 0 2px #26706a;
    }}
    body.calendar-style-timeline-stack .calendar-event,
    body.calendar-style-timeline-stack .calendar-event-span {{
      border-radius: 6px;
      background: color-mix(in srgb, var(--calendar-color) 16%, var(--theme-raised, #edf7f5));
    }}
    body.calendar-style-timeline-stack .calendar-toolbar .calendar-button,
    body.calendar-style-timeline-stack .calendar-toolbar .calendar-month-input,
    body.calendar-style-timeline-stack .calendar-close {{
      border-color: var(--theme-border, #b7cec9);
      border-radius: 6px;
      background: var(--theme-raised, #edf7f5);
      color: var(--theme-accent, #26706a);
    }}
    body.calendar-style-radar {{
      --ink: var(--theme-text, #effff8);
      --muted: var(--theme-muted, #a4c0b9);
      --line: color-mix(in srgb, var(--theme-accent, #48d5a5) 26%, transparent);
      --paper: color-mix(in srgb, var(--theme-text, #061c24) 92%, transparent);
      --wash: var(--theme-bg, #061821);
      --panel: color-mix(in srgb, var(--theme-panel, #48d5a5) 10%, transparent);
      --shadow: 0 20px 42px rgba(0, 0, 0, .3);
      background:
        radial-gradient(circle at 20% 18%, color-mix(in srgb, var(--theme-success-soft, #48d5a5) 12%, transparent), transparent 28%),
        linear-gradient(160deg, var(--theme-bg, #061821), var(--theme-bg, #0a222d) 52%, var(--theme-bg, #061821));
    }}
    body.calendar-style-radar .calendar-toolbar {{
      border: 1px solid color-mix(in srgb, var(--theme-accent, #48d5a5) 24%, transparent);
      border-radius: 8px;
      background: color-mix(in srgb, var(--theme-inset, #04141c) 84%, transparent);
      box-shadow: var(--shadow);
    }}
    body.calendar-style-radar .calendar-month-title,
    body.calendar-style-radar .calendar-day-panel-title,
    body.calendar-style-radar .calendar-dialog-title {{
      color: var(--theme-text, #effff8);
      font-weight: 850;
    }}
    body.calendar-style-radar .calendar-summary,
    body.calendar-style-radar .calendar-day-panel-summary {{
      color: var(--theme-text, #bdd6d0);
    }}
    body.calendar-style-radar .calendar-grid {{
      --calendar-span-divider: color-mix(in srgb, var(--theme-success, #48d5a5) 34%, transparent);
      background:
        radial-gradient(circle at center, transparent 0 21%, color-mix(in srgb, var(--theme-success-soft, #48d5a5) 18%, transparent) 21.5% 22%, transparent 22.5% 41%, color-mix(in srgb, var(--theme-success-soft, #48d5a5) 16%, transparent) 41.5% 42%, transparent 42.5% 62%, color-mix(in srgb, var(--theme-success-soft, #48d5a5) 14%, transparent) 62.5% 63%, transparent 63.5%),
        linear-gradient(color-mix(in srgb, var(--theme-success-soft, #48d5a5) 8%, transparent) 1px, transparent 1px),
        linear-gradient(90deg, color-mix(in srgb, var(--theme-success-soft, #48d5a5) 8%, transparent) 1px, transparent 1px),
        color-mix(in srgb, var(--theme-inset, #031016) 44%, transparent);
      background-size: auto, 32px 32px, 32px 32px, auto;
      box-shadow: var(--shadow);
    }}
    body.calendar-style-radar .calendar-weekday,
    body.calendar-style-radar .calendar-day,
    body.calendar-style-radar .calendar-day-panel-header,
    body.calendar-style-radar .calendar-day-slot {{
      border-color: color-mix(in srgb, var(--theme-accent, #48d5a5) 22%, transparent);
      background: color-mix(in srgb, var(--theme-bg, #061c24) 74%, transparent);
      color: var(--theme-text, #effff8);
    }}
    body.calendar-style-radar .calendar-day.outside {{
      background: color-mix(in srgb, var(--theme-inset, #031016) 58%, transparent);
      color: var(--theme-muted, #56736d);
    }}
    body.calendar-style-radar .calendar-day.today,
    body.calendar-style-radar .calendar-day.selected {{
      box-shadow:
        inset 0 0 0 2px #48d5a5,
        0 0 22px rgba(72, 213, 165, .12);
    }}
    body.calendar-style-radar .calendar-event,
    body.calendar-style-radar .calendar-event-span {{
      background: color-mix(in srgb, var(--calendar-color) 24%, color-mix(in srgb, var(--theme-bg, #061c24) 92%, transparent));
      color: var(--theme-text, #effff8);
      animation: calendar-radar-contact 3.8s ease-in-out infinite;
    }}
    body.calendar-style-radar .calendar-event-time,
    body.calendar-style-radar .calendar-day-slot-time {{
      border-color: color-mix(in srgb, var(--theme-accent, #48d5a5) 22%, transparent);
      color: var(--theme-success, #a8ffd7);
    }}
    body.calendar-style-radar .calendar-toolbar .calendar-button,
    body.calendar-style-radar .calendar-toolbar .calendar-month-input,
    body.calendar-style-radar .calendar-close,
    body.calendar-style-radar .calendar-legend-item,
    body.calendar-style-radar .calendar-dialog,
    body.calendar-style-radar .calendar-day-panel {{
      border-color: color-mix(in srgb, var(--theme-accent, #48d5a5) 28%, transparent);
      background: color-mix(in srgb, var(--theme-inset, #031016) 78%, transparent);
      color: var(--theme-text, #effff8);
    }}
    @keyframes calendar-radar-contact {{
      0%, 100% {{ box-shadow: 0 7px 18px color-mix(in srgb, var(--calendar-color) 18%, transparent); }}
      50% {{ box-shadow: 0 7px 18px color-mix(in srgb, var(--calendar-color) 22%, transparent), 0 0 0 3px rgba(72, 213, 165, .1); }}
    }}
    body.calendar-style-family-orbit {{
      --ink: var(--theme-text, #20283a);
      --muted: var(--theme-muted, #677386);
      --line: var(--theme-border, #cad7df);
      --paper: color-mix(in srgb, var(--theme-text, #ffffff) 94%, transparent);
      --wash: var(--theme-bg, #edf4f6);
      --panel: var(--theme-panel, #ecf7f6);
      --shadow: 0 18px 38px rgba(30, 50, 70, .14);
      background:
        radial-gradient(circle at 14% 16%, color-mix(in srgb, var(--theme-accent-soft, #237f86) 14%, transparent), transparent 28%),
        radial-gradient(circle at 88% 22%, color-mix(in srgb, var(--theme-error-soft, #d75c78) 14%, transparent), transparent 26%),
        var(--theme-raised, #edf4f6);
    }}
    body.calendar-style-family-orbit .calendar-toolbar {{
      border: 1px solid color-mix(in srgb, var(--theme-border, #365e7a) 18%, transparent);
      border-radius: 8px;
      background: color-mix(in srgb, var(--theme-panel, #ffffff) 90%, transparent);
      box-shadow: var(--shadow);
    }}
    body.calendar-style-family-orbit .calendar-month-title {{
      color: var(--theme-text, #24324a);
      font-weight: 850;
    }}
    body.calendar-style-family-orbit .calendar-grid {{
      --calendar-span-divider: color-mix(in srgb, var(--theme-text, #365e7a) 24%, transparent);
      background:
        radial-gradient(ellipse at center, transparent 0 18%, color-mix(in srgb, var(--theme-accent-soft, #237f86) 18%, transparent) 18.5% 19%, transparent 19.5% 38%, color-mix(in srgb, var(--theme-error-soft, #d75c78) 15%, transparent) 38.5% 39%, transparent 39.5% 58%, color-mix(in srgb, var(--theme-raised, #456aa4) 14%, transparent) 58.5% 59%, transparent 59.5%),
        linear-gradient(135deg, color-mix(in srgb, var(--theme-panel, #ffffff) 90%, transparent), color-mix(in srgb, var(--theme-raised, #ecf5f6) 72%, transparent));
      box-shadow: var(--shadow);
    }}
    body.calendar-style-family-orbit .calendar-weekday {{
      border-color: var(--theme-border, #c4d3dc);
      background: var(--theme-raised, #24324a);
      color: var(--theme-text, #f8fbff);
    }}
    body.calendar-style-family-orbit .calendar-day {{
      border-color: color-mix(in srgb, var(--theme-border, #365e7a) 20%, transparent);
      background: color-mix(in srgb, var(--theme-panel, #ffffff) 82%, transparent);
    }}
    body.calendar-style-family-orbit .calendar-day.outside {{
      background: color-mix(in srgb, var(--theme-raised, #ecf5f6) 72%, transparent);
      color: var(--theme-muted, #8d9bab);
    }}
    body.calendar-style-family-orbit .calendar-day.today,
    body.calendar-style-family-orbit .calendar-day.selected {{
      box-shadow:
        inset 0 0 0 2px #237f86,
        0 0 0 5px rgba(35, 127, 134, .08);
    }}
    body.calendar-style-family-orbit .calendar-event,
    body.calendar-style-family-orbit .calendar-event-span {{
      border-radius: 8px;
      background: color-mix(in srgb, var(--calendar-color) 18%, color-mix(in srgb, var(--theme-panel, #ffffff) 94%, transparent));
      color: var(--theme-text, #20283a);
    }}
    body.calendar-style-family-orbit .calendar-toolbar .calendar-button,
    body.calendar-style-family-orbit .calendar-toolbar .calendar-month-input,
    body.calendar-style-family-orbit .calendar-close {{
      border-color: var(--theme-border, #afd2d0);
      border-radius: 6px;
      background: var(--theme-raised, #d8f0ed);
      color: var(--theme-accent, #237f86);
    }}
    body.calendar-style-month-hud {{
      color-scheme: var(--theme-color-scheme, dark);
      --ink: var(--theme-text, #eaf9f7);
      --muted: var(--theme-muted, #a9c9c5);
      --line: color-mix(in srgb, var(--theme-accent, #62e6d9) 22%, transparent);
      --paper: color-mix(in srgb, var(--theme-text, #051117) 72%, transparent);
      --wash: var(--theme-bg, #041115);
      --panel: color-mix(in srgb, var(--theme-panel, #62e6d9) 8%, transparent);
      --shadow: 0 30px 80px rgba(0, 0, 0, .38);
      background:
        radial-gradient(circle at 50% 42%, color-mix(in srgb, var(--theme-accent-soft, #62e6d9) 16%, transparent), transparent 28%),
        linear-gradient(color-mix(in srgb, var(--theme-accent-soft, #62e6d9) 4.5%, transparent) 1px, transparent 1px),
        linear-gradient(90deg, color-mix(in srgb, var(--theme-accent-soft, #62e6d9) 4.5%, transparent) 1px, transparent 1px),
        var(--theme-inset, #041115);
      background-size: auto, 36px 36px, 36px 36px, auto;
    }}
    body.calendar-style-month-hud .calendar-content {{
      padding: clamp(12px, 2vw, 22px);
    }}
    body.calendar-style-month-hud .calendar-toolbar {{
      border: 1px solid color-mix(in srgb, var(--theme-accent, #62e6d9) 18%, transparent);
      border-radius: 8px;
      background: color-mix(in srgb, var(--theme-inset, #051117) 76%, transparent);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, .05);
      padding: 10px 12px;
    }}
    body.calendar-style-month-hud .calendar-month-title {{
      color: var(--theme-text, #f2fffd);
      font-size: clamp(22px, 2.6vw, 34px);
      font-weight: 860;
    }}
    body.calendar-style-month-hud .calendar-summary {{
      color: var(--theme-text, #a9c9c5);
    }}
    body.calendar-style-month-hud .calendar-toolbar .calendar-button,
    body.calendar-style-month-hud .calendar-toolbar .calendar-month-input {{
      border-color: color-mix(in srgb, var(--theme-accent, #62e6d9) 32%, transparent);
      background: color-mix(in srgb, var(--theme-bg, #07181f) 82%, transparent);
      color: var(--theme-text, #eaf9f7);
    }}
    body.calendar-style-month-hud .calendar-toolbar .calendar-button:hover,
    body.calendar-style-month-hud .calendar-toolbar .calendar-button:focus-visible,
    body.calendar-style-month-hud .calendar-toolbar .calendar-month-input:focus-visible {{
      border-color: var(--theme-accent, #62e6d9);
      background: color-mix(in srgb, var(--theme-accent-soft, #62e6d9) 13%, transparent);
      outline-color: color-mix(in srgb, var(--theme-accent, #62e6d9) 20%, transparent);
    }}
    body.calendar-style-month-hud .calendar-legend-item {{
      border-color: color-mix(in srgb, var(--theme-accent, #62e6d9) 22%, transparent);
      background: color-mix(in srgb, var(--theme-bg, #07181f) 72%, transparent);
      color: var(--theme-accent, #c8fffa);
    }}
    body.calendar-style-month-hud .calendar-grid {{
      --calendar-span-divider: color-mix(in srgb, var(--theme-accent, #62e6d9) 34%, transparent);
      border: 0;
      background: color-mix(in srgb, var(--theme-inset, #041115) 78%, transparent);
      box-shadow: none;
    }}
    body.calendar-style-month-hud .calendar-day-panel-overlay {{
      background:
        radial-gradient(circle at center, color-mix(in srgb, var(--theme-accent-soft, #62e6d9) 22%, transparent), transparent 36%),
        color-mix(in srgb, var(--theme-inset, #030c10) 58%, transparent);
    }}
    body.calendar-style-month-hud .calendar-day-panel {{
      border: 1px solid color-mix(in srgb, var(--theme-accent, #62e6d9) 18%, transparent);
      background:
        linear-gradient(135deg, color-mix(in srgb, var(--theme-bg, #081f25) 96%, transparent), color-mix(in srgb, var(--theme-inset, #041115) 94%, transparent));
      box-shadow:
        0 42px 92px rgba(0, 0, 0, .44),
        0 0 72px rgba(98, 230, 217, .13),
        inset 0 1px 0 rgba(255, 255, 255, .05);
    }}
    body.calendar-style-month-hud .calendar-weekday {{
      border-color: color-mix(in srgb, var(--theme-accent, #62e6d9) 18%, transparent);
      background: color-mix(in srgb, var(--theme-accent-soft, #62e6d9) 8%, transparent);
      color: var(--theme-accent, #8bf7ee);
    }}
    body.calendar-style-month-hud .calendar-day {{
      border-color: color-mix(in srgb, var(--theme-accent, #62e6d9) 16%, transparent);
      background:
        linear-gradient(135deg, color-mix(in srgb, var(--theme-bg, #091e24) 78%, transparent), color-mix(in srgb, var(--theme-inset, #041115) 68%, transparent));
      color: var(--theme-text, #eaf9f7);
    }}
    body.calendar-style-month-hud .calendar-day.outside {{
      background: color-mix(in srgb, var(--theme-inset, #050f13) 64%, transparent);
      color: var(--theme-muted, #5c7d7a);
    }}
    body.calendar-style-month-hud .calendar-day.today,
    body.calendar-style-month-hud .calendar-day.selected {{
      box-shadow:
        inset 0 0 0 2px #62e6d9,
        0 0 26px rgba(98, 230, 217, .12);
    }}
    body.calendar-style-month-hud .calendar-event,
    body.calendar-style-month-hud .calendar-event-span {{
      background: color-mix(in srgb, var(--calendar-color) 22%, color-mix(in srgb, var(--theme-bg, #07181f) 86%, transparent));
      color: var(--theme-text, #f2fffd);
    }}
    body.calendar-style-month-hud .calendar-event-time {{
      color: var(--theme-accent, #8bf7ee);
    }}
    body.calendar-style-month-hud .calendar-day-panel-header,
    body.calendar-style-month-hud .calendar-day-slot {{
      border-color: color-mix(in srgb, var(--theme-accent, #62e6d9) 18%, transparent);
      background: color-mix(in srgb, var(--theme-bg, #07181f) 70%, transparent);
    }}
    body.calendar-style-month-hud .calendar-close {{
      border-color: color-mix(in srgb, var(--theme-accent, #62e6d9) 34%, transparent);
      background: color-mix(in srgb, var(--theme-bg, #07181f) 78%, transparent);
      color: var(--theme-accent, #8bf7ee);
      box-shadow:
        0 0 18px rgba(98, 230, 217, .08),
        inset 0 1px 0 rgba(255, 255, 255, .06);
    }}
    body.calendar-style-month-hud .calendar-close:hover,
    body.calendar-style-month-hud .calendar-close:focus-visible {{
      border-color: var(--theme-accent, #62e6d9);
      background: color-mix(in srgb, var(--theme-accent-soft, #62e6d9) 15%, transparent);
      color: var(--theme-text, #f2fffd);
      outline-color: color-mix(in srgb, var(--theme-accent, #62e6d9) 24%, transparent);
    }}
    body.calendar-style-month-hud .calendar-day-panel-title {{
      color: var(--theme-text, #f2fffd);
    }}
    body.calendar-style-month-hud .calendar-day-slot-time {{
      border-color: color-mix(in srgb, var(--theme-accent, #62e6d9) 18%, transparent);
      color: var(--theme-accent, #8bf7ee);
    }}
    @media (max-width: 760px) {{
      .calendar-header {{ position: static; align-items: flex-start; flex-direction: column; }}
      .calendar-toolbar {{ grid-template-columns: 1fr; }}
      .calendar-toolbar-main {{ align-items: flex-start; flex-direction: column; }}
      .calendar-toolbar .calendar-controls {{ justify-content: flex-start; }}
      .calendar-canvas {{
        --calendar-size: min(680px, calc(100vw - 24px), calc(100vh - 160px));
      }}
      .calendar-day {{ padding: 6px; }}
      .calendar-event {{ font-size: 11px; }}
      .calendar-detail-row {{ grid-template-columns: 1fr; gap: 4px; }}
    }}
  </style>
</head>
<body class="calendar-style-{selected_style}">
  <main class="calendar-shell">
    <header class="calendar-header">
      <div class="calendar-heading">
        <span class="calendar-kicker">Calendar</span>
        <h1>{title}</h1>
      </div>
      <div class="calendar-controls">
        <button class="calendar-button" type="button" data-calendar-action="previous" aria-label="Previous month">‹</button>
        <button class="calendar-button" type="button" data-calendar-action="next" aria-label="Next month">›</button>
      </div>
    </header>
    <section class="calendar-content">
      <div class="calendar-toolbar">
        <div class="calendar-toolbar-main">
          <div>
            <button id="monthTitle" class="calendar-month-title" type="button" aria-label="Choose calendar month"></button>
            <div id="summary" class="calendar-summary" aria-live="polite"></div>
          </div>
          <div class="calendar-controls" aria-label="Calendar month controls">
            <button class="calendar-button" type="button" data-calendar-action="previous" aria-label="Previous month">‹</button>
            <input id="monthPicker" class="calendar-month-input" type="month" aria-label="Calendar month">
            <button class="calendar-button" type="button" data-calendar-action="next" aria-label="Next month">›</button>
          </div>
        </div>
        <div id="legend" class="calendar-legend"></div>
      </div>
      <div id="calendarViewport" class="calendar-canvas-viewport">
        <div id="calendarCanvas" class="calendar-canvas">
          <div id="grid" class="calendar-grid" aria-label="Calendar month"></div>
        </div>
      </div>
    </section>
  </main>
  <div id="dayModal" class="calendar-day-panel-overlay" role="dialog" aria-modal="true" aria-labelledby="dayDialogTitle" hidden>
    <section id="dayView" class="calendar-day-panel" aria-live="polite"></section>
  </div>
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
    const viewport = document.getElementById("calendarViewport");
    const canvas = document.getElementById("calendarCanvas");
    const grid = document.getElementById("grid");
    const dayModal = document.getElementById("dayModal");
    const dayView = document.getElementById("dayView");
    const legend = document.getElementById("legend");
    const summary = document.getElementById("summary");
    const monthTitle = document.getElementById("monthTitle");
    const monthPicker = document.getElementById("monthPicker");
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
    const dayHeadingFormatter = new Intl.DateTimeFormat(undefined, {{
      weekday: "long", month: "long", day: "numeric", year: "numeric",
      timeZone: CALENDAR_DATA.timezone,
    }});
    const MIN_CANVAS_ZOOM = 0.55;
    const MAX_CANVAS_ZOOM = 2.4;
    const CANVAS_ZOOM_FACTOR = 1.1;
    const MS_PER_DAY = 24 * 60 * 60 * 1000;
    let canvasZoom = 1;
    let canvasPanX = 0;
    let canvasPanY = 0;
    let canvasPanState = null;
    let selectedDayKey = "";

    function localDate(dateText) {{
      const [year, month, day] = String(dateText || "").split("-").map(Number);
      return new Date(year || 1970, (month || 1) - 1, day || 1);
    }}

    function eventDate(event) {{
      if (event.start_date) return localDate(event.start_date);
      return new Date(String(event.start_at || ""));
    }}

    function dateOnly(value) {{
      if (!(value instanceof Date) || Number.isNaN(value.getTime())) return null;
      return new Date(value.getFullYear(), value.getMonth(), value.getDate());
    }}

    function addDays(date, days) {{
      const next = new Date(date);
      next.setDate(date.getDate() + days);
      return next;
    }}

    function dayNumber(date) {{
      return Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / MS_PER_DAY;
    }}

    function dayOffset(from, to) {{
      return Math.round(dayNumber(to) - dayNumber(from));
    }}

    function eventStartDate(event) {{
      return dateOnly(eventDate(event));
    }}

    function eventDisplayEndDate(event) {{
      const start = eventStartDate(event);
      if (!start) return null;
      let end = null;
      if (event.end_date) {{
        end = localDate(event.end_date);
        if (event.all_day || event.start_date) {{
          end = addDays(end, -1);
        }}
      }} else if (event.end_at) {{
        end = dateOnly(new Date(String(event.end_at)));
      }}
      if (!end || Number.isNaN(end.getTime()) || end < start) return start;
      return end;
    }}

    function eventDateRange(event) {{
      const start = eventStartDate(event);
      const end = eventDisplayEndDate(event);
      if (!start || !end) return null;
      return {{ start, end }};
    }}

    function eventCoversDay(event, key) {{
      const range = eventDateRange(event);
      if (!range) return false;
      const day = localDate(key);
      return day >= range.start && day <= range.end;
    }}

    function eventSpansMultipleDays(event) {{
      const range = eventDateRange(event);
      return Boolean(range && dateKey(range.start) !== dateKey(range.end));
    }}

    function dateKey(date) {{
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, "0");
      const day = String(date.getDate()).padStart(2, "0");
      return `${{year}}-${{month}}-${{day}}`;
    }}

    function monthKey(date) {{
      return dateKey(date).slice(0, 7);
    }}

    function monthFromKey(value) {{
      if (!/^\\d{{4}}-\\d{{2}}$/.test(value || "")) return null;
      const [year, month] = value.split("-").map(Number);
      return new Date(year, month - 1, 1);
    }}

    function monthWindow(date) {{
      const monthStart = new Date(date.getFullYear(), date.getMonth(), 1);
      const start = new Date(monthStart);
      start.setDate(monthStart.getDate() - monthStart.getDay());
      const end = new Date(start);
      end.setDate(start.getDate() + 41);
      return {{
        month: monthKey(monthStart),
        rangeStart: dateKey(start),
        rangeEnd: dateKey(end),
      }};
    }}

    function initialMonth() {{
      const requested = params.get("month") || params.get("calendar_month");
      if (/^\\d{{4}}-\\d{{2}}$/.test(requested || "")) {{
        return monthFromKey(requested);
      }}
      return localDate(CALENDAR_DATA.reference_date || dateKey(new Date()));
    }}

    let visibleMonth = initialMonth();

    function clamp(value, min, max) {{
      return Math.min(Math.max(value, min), max);
    }}

    function clampCanvasZoom(value) {{
      const zoom = Number(value);
      if (!Number.isFinite(zoom)) return 1;
      return Math.round(clamp(zoom, MIN_CANVAS_ZOOM, MAX_CANVAS_ZOOM) * 1000) / 1000;
    }}

    function applyCanvasTransform() {{
      canvas.style.setProperty("--calendar-pan-x", `${{Math.round(canvasPanX)}}px`);
      canvas.style.setProperty("--calendar-pan-y", `${{Math.round(canvasPanY)}}px`);
      canvas.style.setProperty("--calendar-zoom", String(canvasZoom));
    }}

    function updateCanvasZoom(value, clientX = null, clientY = null) {{
      const nextZoom = clampCanvasZoom(value);
      if (nextZoom === canvasZoom) return;
      if (Number.isFinite(clientX) && Number.isFinite(clientY)) {{
        const rect = canvas.getBoundingClientRect();
        const localX = clientX - rect.left;
        const localY = clientY - rect.top;
        const scaleRatio = nextZoom / canvasZoom;
        canvasPanX += localX * (1 - scaleRatio);
        canvasPanY += localY * (1 - scaleRatio);
      }}
      canvasZoom = nextZoom;
      applyCanvasTransform();
    }}

    function requestMonth(date) {{
      const target = new Date(date.getFullYear(), date.getMonth(), 1);
      const range = monthWindow(target);
      visibleMonth = target;
      selectedDayKey = "";
      closeDayView({{ animate: false, clearSelection: false }});
      renderMonth();
      if (window.parent !== window) {{
        window.parent.postMessage({{
          type: "electroboy-calendar-month-change",
          month: range.month,
          rangeStart: range.rangeStart,
          rangeEnd: range.rangeEnd,
        }}, window.location.origin);
        return;
      }}
      const nextUrl = new URL(window.location.href);
      nextUrl.searchParams.set("month", range.month);
      nextUrl.searchParams.set("range_start", range.rangeStart);
      nextUrl.searchParams.set("range_end", range.rangeEnd);
      window.location.assign(nextUrl.href);
    }}

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
        const start = eventStartDate(event);
        const end = eventDisplayEndDate(event);
        if (start && end && dateKey(end) !== dateKey(start)) {{
          return `${{dateFormatter.format(start)}} - ${{dateFormatter.format(end)}}`;
        }}
        return start ? dateFormatter.format(start) : "";
      }}
      const start = new Date(String(event.start_at || ""));
      const end = event.end_at ? new Date(String(event.end_at)) : null;
      if (Number.isNaN(start.getTime())) return "";
      if (end && !Number.isNaN(end.getTime())) {{
        return `${{dateFormatter.format(start)}} · ${{timeFormatter.format(start)}} - ${{timeFormatter.format(end)}}`;
      }}
      return `${{dateFormatter.format(start)}} · ${{timeFormatter.format(start)}}`;
    }}

    function eventsByDay(rangeStart = null, rangeEnd = null) {{
      const grouped = new Map();
      for (const event of CALENDAR_DATA.events || []) {{
        const range = eventDateRange(event);
        if (!range) continue;
        let cursor = rangeStart && range.start < rangeStart ? new Date(rangeStart) : new Date(range.start);
        const end = rangeEnd && range.end > rangeEnd ? new Date(rangeEnd) : new Date(range.end);
        while (cursor <= end) {{
          const key = dateKey(cursor);
          if (!grouped.has(key)) grouped.set(key, []);
          grouped.get(key).push(event);
          cursor = addDays(cursor, 1);
        }}
      }}
      return grouped;
    }}

    function eventsForDay(key) {{
      return (CALENDAR_DATA.events || []).filter((event) => eventCoversDay(event, key));
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
      button.addEventListener("click", (clickEvent) => {{
        clickEvent.stopPropagation();
        openEvent(event);
      }});
      return button;
    }}

    function reserveSpanLane(weekLanes, startColumn, endColumn) {{
      for (let lane = 0; lane < weekLanes.length; lane += 1) {{
        if (weekLanes[lane] < startColumn) {{
          weekLanes[lane] = endColumn;
          return lane;
        }}
      }}
      weekLanes.push(endColumn);
      return weekLanes.length - 1;
    }}

    function eventSegments(gridStart, events) {{
      const gridEnd = addDays(gridStart, 41);
      const weekLanes = Array.from({{ length: 6 }}, () => []);
      const segments = [];
      for (const event of events) {{
        if (!eventSpansMultipleDays(event)) continue;
        const range = eventDateRange(event);
        if (!range || range.end < gridStart || range.start > gridEnd) continue;
        const clippedStart = range.start < gridStart ? new Date(gridStart) : new Date(range.start);
        const clippedEnd = range.end > gridEnd ? new Date(gridEnd) : new Date(range.end);
        for (let week = 0; week < 6; week += 1) {{
          const weekStart = addDays(gridStart, week * 7);
          const weekEnd = addDays(weekStart, 6);
          if (clippedEnd < weekStart || clippedStart > weekEnd) continue;
          const segmentStart = clippedStart > weekStart ? clippedStart : weekStart;
          const segmentEnd = clippedEnd < weekEnd ? clippedEnd : weekEnd;
          const startColumn = dayOffset(weekStart, segmentStart);
          const endColumn = dayOffset(weekStart, segmentEnd);
          const lane = reserveSpanLane(weekLanes[week], startColumn, endColumn);
          segments.push({{
            event,
            week,
            startColumn,
            endColumn,
            lane,
            startsHere: dateKey(segmentStart) === dateKey(range.start),
            endsHere: dateKey(segmentEnd) === dateKey(range.end),
          }});
        }}
      }}
      return {{
        segments,
        laneCounts: weekLanes.map((lanes) => lanes.length),
      }};
    }}

    function renderEventSpan(segment) {{
      const event = segment.event;
      const button = element("button", "calendar-event-span", event.title || "Untitled event");
      button.type = "button";
      button.style.gridColumn = `${{segment.startColumn + 1}} / ${{segment.endColumn + 2}}`;
      button.style.gridRow = String(segment.week + 2);
      button.style.setProperty("--calendar-span-lane", String(segment.lane));
      button.style.setProperty("--calendar-span-days", String(segment.endColumn - segment.startColumn + 1));
      button.style.setProperty("--calendar-color", calendarColor(event.calendar_id));
      button.classList.toggle("continues-before", !segment.startsHere);
      button.classList.toggle("continues-after", !segment.endsHere);
      button.classList.toggle("cancelled", String(event.status || "").toLowerCase() === "cancelled");
      button.title = `${{calendarLabel(event.calendar_id)}} · ${{eventFullTimeLabel(event)}}`;
      button.addEventListener("click", (clickEvent) => {{
        clickEvent.stopPropagation();
        openEvent(event);
      }});
      return button;
    }}

    function slotTimeLabel(hour) {{
      const date = new Date(2000, 0, 1, hour, 0, 0);
      return timeFormatter.format(date);
    }}

    function eventStartHour(event) {{
      if (event.all_day || event.start_date) return -1;
      const start = new Date(String(event.start_at || ""));
      if (Number.isNaN(start.getTime())) return -1;
      return start.getHours();
    }}

    function openDayView(key) {{
      if (!key) {{
        closeDayView({{ animate: false }});
        return;
      }}
      const date = localDate(key);
      const events = eventsForDay(key);
      const timedEvents = events.filter((event) => eventStartHour(event) >= 0);
      const allDayEvents = events.filter((event) => eventStartHour(event) < 0);
      dayView.replaceChildren();
      const header = element("header", "calendar-day-panel-header");
      const heading = element("div", "calendar-day-panel-heading");
      heading.append(
        element("h3", "calendar-day-panel-title", dayHeadingFormatter.format(date)),
        element(
          "div",
          "calendar-day-panel-summary",
          events.length === 1 ? "1 event" : `${{events.length}} events`,
        ),
      );
      const close = element("button", "calendar-close", "×");
      close.type = "button";
      close.setAttribute("aria-label", "Close day schedule");
      close.addEventListener("click", () => closeDayView());
      header.append(
        heading,
        close,
      );
      const slots = element("div", "calendar-day-slots");
      const allDaySlot = element("div", "calendar-day-slot");
      allDaySlot.append(
        element("div", "calendar-day-slot-time", "All day"),
        element("div", "calendar-day-slot-events"),
      );
      const allDayContainer = allDaySlot.querySelector(".calendar-day-slot-events");
      if (allDayEvents.length) {{
        allDayEvents.forEach((event) => allDayContainer.append(renderEvent(event)));
      }} else {{
        allDayContainer.append(element("span", "calendar-day-slot-empty", "No all-day events"));
      }}
      slots.append(allDaySlot);
      for (let hour = 0; hour < 24; hour += 1) {{
        const slot = element("div", "calendar-day-slot");
        const slotEvents = timedEvents.filter((event) => eventStartHour(event) === hour);
        const slotBody = element("div", "calendar-day-slot-events");
        if (slotEvents.length) {{
          slotEvents.forEach((event) => slotBody.append(renderEvent(event)));
        }} else {{
          slotBody.append(element("span", "calendar-day-slot-empty", ""));
        }}
        slot.append(element("div", "calendar-day-slot-time", slotTimeLabel(hour)), slotBody);
        slots.append(slot);
      }}
      dayView.append(header, slots);
      dayModal.hidden = false;
      dayModal.classList.remove("closing");
      window.requestAnimationFrame(() => {{
        dayModal.classList.add("open");
        document.body.classList.add("calendar-day-open");
      }});
    }}

    function closeDayView(options = {{}}) {{
      const animate = options.animate !== false;
      const clearSelection = options.clearSelection !== false;
      if (clearSelection && selectedDayKey) {{
        selectedDayKey = "";
        renderMonth();
      }}
      if (dayModal.hidden) {{
        dayView.replaceChildren();
        document.body.classList.remove("calendar-day-open");
        return;
      }}
      dayModal.classList.remove("open");
      if (!animate) {{
        dayModal.classList.remove("closing");
        dayModal.hidden = true;
        dayView.replaceChildren();
        document.body.classList.remove("calendar-day-open");
        return;
      }}
      dayModal.classList.add("closing");
      document.body.classList.remove("calendar-day-open");
      window.setTimeout(() => {{
        dayModal.classList.remove("closing");
        dayModal.hidden = true;
        dayView.replaceChildren();
      }}, 280);
    }}

    function selectDay(key) {{
      selectedDayKey = key;
      renderMonth();
      openDayView(key);
    }}

    function renderMonth() {{
      const current = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 1);
      monthTitle.textContent = monthFormatter.format(current);
      monthPicker.value = monthKey(current);
      const visibleEvents = CALENDAR_DATA.events || [];
      summary.textContent = `${{visibleEvents.length}} event${{visibleEvents.length === 1 ? "" : "s"}} · ${{(CALENDAR_DATA.calendars || []).filter((calendar) => calendar.selected).length}} calendar${{(CALENDAR_DATA.calendars || []).filter((calendar) => calendar.selected).length === 1 ? "" : "s"}}`;
      const start = new Date(current);
      start.setDate(current.getDate() - current.getDay());
      const end = addDays(start, 41);
      const grouped = eventsByDay(start, end);
      const spans = eventSegments(start, visibleEvents);
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
        const cellEvents = dayEvents.filter((event) => !eventSpansMultipleDays(event));
        const cell = element("section", "calendar-day");
        cell.style.gridColumn = String((index % 7) + 1);
        cell.style.gridRow = String(Math.floor(index / 7) + 2);
        cell.style.setProperty("--calendar-row-lanes", String(spans.laneCounts[Math.floor(index / 7)] || 0));
        cell.tabIndex = 0;
        cell.setAttribute("role", "button");
        cell.setAttribute(
          "aria-label",
          `${{dayHeadingFormatter.format(day)}}: ${{dayEvents.length === 1 ? "1 event" : `${{dayEvents.length}} events`}}`,
        );
        cell.classList.toggle("outside", day.getMonth() !== current.getMonth());
        cell.classList.toggle("today", key === todayKey);
        cell.classList.toggle("selected", key === selectedDayKey);
        cell.addEventListener("click", () => selectDay(key));
        cell.addEventListener("keydown", (event) => {{
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          selectDay(key);
        }});
        const header = element("div", "calendar-date");
        header.append(
          element("span", "", String(day.getDate())),
          dayEvents.length ? element("span", "calendar-day-count", String(dayEvents.length)) : document.createTextNode(""),
        );
        const events = element("div", "calendar-events");
        cellEvents.forEach((event) => events.append(renderEvent(event)));
        cell.append(header, events);
        grid.append(cell);
      }}
      spans.segments.forEach((segment) => grid.append(renderEventSpan(segment)));
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
      const range = monthWindow(visibleMonth);
      window.parent.postMessage({{
        type: "electroboy-calendar-state",
        state: {{
          provider: CALENDAR_DATA.provider,
          month: range.month,
          rangeStart: range.rangeStart,
          rangeEnd: range.rangeEnd,
          calendars: CALENDAR_DATA.calendars || [],
        }},
      }}, window.location.origin);
    }}

    function handleCalendarAction(action) {{
      if (action === "previous") {{
        requestMonth(new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() - 1, 1));
      }} else if (action === "next") {{
        requestMonth(new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + 1, 1));
      }}
    }}

    function openMonthPicker() {{
      monthPicker.focus();
      if (typeof monthPicker.showPicker === "function") {{
        monthPicker.showPicker();
      }}
    }}

    function beginCanvasPan(event) {{
      if (event.button !== 1) return;
      event.preventDefault();
      canvasPanState = {{
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        panX: canvasPanX,
        panY: canvasPanY,
      }};
      document.body.classList.add("calendar-panning");
      if (viewport.setPointerCapture) viewport.setPointerCapture(event.pointerId);
    }}

    function updateCanvasPan(event) {{
      if (!canvasPanState || event.pointerId !== canvasPanState.pointerId) return;
      event.preventDefault();
      canvasPanX = canvasPanState.panX + event.clientX - canvasPanState.startX;
      canvasPanY = canvasPanState.panY + event.clientY - canvasPanState.startY;
      applyCanvasTransform();
    }}

    function endCanvasPan(event) {{
      if (!canvasPanState || event.pointerId !== canvasPanState.pointerId) return;
      if (viewport.releasePointerCapture) viewport.releasePointerCapture(event.pointerId);
      canvasPanState = null;
      document.body.classList.remove("calendar-panning");
    }}

    function handleCanvasWheel(event) {{
      if (modal.classList.contains("open")) return;
      if (!dayModal.hidden) return;
      event.preventDefault();
      if (event.deltaY === 0) return;
      const factor = event.deltaY < 0
        ? CANVAS_ZOOM_FACTOR
        : 1 / CANVAS_ZOOM_FACTOR;
      updateCanvasZoom(canvasZoom * factor, event.clientX, event.clientY);
    }}

    for (const button of document.querySelectorAll("[data-calendar-action]")) {{
      button.addEventListener("click", () => handleCalendarAction(button.dataset.calendarAction));
    }}
    monthPicker.addEventListener("change", () => {{
      const nextMonth = monthFromKey(monthPicker.value);
      if (nextMonth) requestMonth(nextMonth);
    }});
    monthTitle.addEventListener("click", openMonthPicker);
    viewport.addEventListener("wheel", handleCanvasWheel, {{ passive: false }});
    viewport.addEventListener("pointerdown", beginCanvasPan);
    viewport.addEventListener("pointermove", updateCanvasPan);
    viewport.addEventListener("pointerup", endCanvasPan);
    viewport.addEventListener("pointercancel", endCanvasPan);
    viewport.addEventListener("auxclick", (event) => {{
      if (event.button === 1) event.preventDefault();
    }});
    document.addEventListener("mouseup", (event) => {{
      if (canvasPanState && event.button === 1) {{
        canvasPanState = null;
        document.body.classList.remove("calendar-panning");
      }}
    }});
    document.getElementById("closeModal").addEventListener("click", closeModal);
    dayModal.addEventListener("click", (event) => {{
      if (event.target === dayModal) closeDayView();
    }});
    modal.addEventListener("click", (event) => {{
      if (event.target === modal) closeModal();
    }});
    window.addEventListener("keydown", (event) => {{
      if (event.key !== "Escape") return;
      if (modal.classList.contains("open")) {{
        closeModal();
        return;
      }}
      if (!dayModal.hidden) closeDayView();
    }});
    applyCanvasTransform();
    renderLegend();
    renderMonth();
  </script>
</body>
</html>""",
        HTTPStatus.OK,
    )
