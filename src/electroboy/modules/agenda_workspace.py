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
    {"id": "timeline-stack", "label": "Timeline Stack"},
    {"id": "radar", "label": "Radar"},
    {"id": "family-orbit", "label": "Family Orbit"},
    {"id": "month-hud", "label": "Month HUD"},
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
    body.agenda-style-timeline-stack {{
      --ink: #1d2a2b;
      --muted: #637271;
      --line: #c6d4d2;
      --paper: #fbfdfc;
      --wash: #e9f0ef;
      --accent: #26706a;
      --accent-soft: #d7ebe8;
      --warning: #9b4d28;
      --warning-soft: #fff0e4;
      --shadow: 0 20px 44px rgba(35, 55, 56, .16);
      background:
        linear-gradient(90deg, rgba(38, 112, 106, .12) 1px, transparent 1px),
        var(--wash);
      background-size: 44px 100%, auto;
    }}
    body.agenda-style-timeline-stack .agenda-header {{
      background: #243b3d;
      color: #f7fffd;
      box-shadow: 0 10px 30px rgba(29, 42, 43, .2);
    }}
    body.agenda-style-timeline-stack .agenda-kicker {{
      color: #bdd8d3;
      letter-spacing: 0;
    }}
    body.agenda-style-timeline-stack h1,
    body.agenda-style-timeline-stack .agenda-section-heading {{
      font-family: Inter, ui-sans-serif, system-ui, sans-serif;
      font-weight: 850;
    }}
    body.agenda-style-timeline-stack .agenda-content {{
      width: min(980px, 100%);
    }}
    body.agenda-style-timeline-stack .agenda-section {{
      position: relative;
      padding-left: 38px;
      perspective: 1400px;
    }}
    body.agenda-style-timeline-stack .agenda-section::before {{
      content: "";
      position: absolute;
      top: 36px;
      bottom: -16px;
      left: 12px;
      width: 2px;
      border-radius: 999px;
      background: linear-gradient(#26706a, rgba(38, 112, 106, .08));
    }}
    body.agenda-style-timeline-stack .agenda-section-heading {{
      position: relative;
      color: #243b3d;
    }}
    body.agenda-style-timeline-stack .agenda-section-heading::before {{
      content: "";
      position: absolute;
      left: -34px;
      top: .45em;
      width: 12px;
      height: 12px;
      border: 3px solid #26706a;
      border-radius: 50%;
      background: #f7fffd;
      box-shadow: 0 0 0 6px rgba(38, 112, 106, .12);
    }}
    body.agenda-style-timeline-stack .agenda-items {{
      gap: 14px;
      perspective: 1400px;
      transform-style: preserve-3d;
    }}
    body.agenda-style-timeline-stack .agenda-item {{
      border-color: #c4d4d0;
      border-radius: 8px;
      background: var(--paper);
      box-shadow: var(--shadow);
      transform:
        perspective(1400px)
        rotateX(2deg)
        rotateY(-4deg)
        translateZ(calc(var(--agenda-index, 0) * -3px));
      transform-origin: left center;
      transition: box-shadow .18s ease, transform .18s ease;
      animation: agenda-stack-settle .36s ease-out both;
      animation-delay: calc(var(--agenda-index, 0) * 28ms);
    }}
    body.agenda-style-timeline-stack .agenda-item:nth-child(even) {{
      transform:
        perspective(1400px)
        rotateX(2deg)
        rotateY(4deg)
        translateZ(calc(var(--agenda-index, 0) * -3px));
    }}
    body.agenda-style-timeline-stack .agenda-item:hover,
    body.agenda-style-timeline-stack .agenda-item:focus-within {{
      box-shadow: 0 24px 52px rgba(35, 55, 56, .22);
      transform: perspective(1400px) rotateX(0) rotateY(0) translateY(-4px);
    }}
    body.agenda-style-timeline-stack .agenda-time {{
      background: #edf7f5;
      color: #26706a;
    }}
    body.agenda-style-timeline-stack .agenda-kind,
    body.agenda-style-timeline-stack .agenda-meta dt {{
      letter-spacing: 0;
    }}
    body.agenda-style-timeline-stack .agenda-badge,
    body.agenda-style-timeline-stack .agenda-person,
    body.agenda-style-timeline-stack .item-action {{
      border-radius: 6px;
    }}
    @keyframes agenda-stack-settle {{
      from {{
        opacity: 0;
        transform: perspective(1400px) rotateX(8deg) translateY(12px);
      }}
      to {{
        opacity: 1;
      }}
    }}
    @media (max-width: 720px) {{
      body.agenda-style-timeline-stack .agenda-section {{
        padding-left: 20px;
      }}
      body.agenda-style-timeline-stack .agenda-section::before,
      body.agenda-style-timeline-stack .agenda-section-heading::before {{
        display: none;
      }}
      body.agenda-style-timeline-stack .agenda-item,
      body.agenda-style-timeline-stack .agenda-item:nth-child(even) {{
        transform: none;
      }}
    }}
    body.agenda-style-radar {{
      --ink: #effff8;
      --muted: #a4c0b9;
      --line: rgba(72, 213, 165, .26);
      --paper: rgba(6, 28, 36, .92);
      --wash: #061821;
      --accent: #48d5a5;
      --accent-soft: rgba(72, 213, 165, .14);
      --warning: #ffd27d;
      --warning-soft: rgba(255, 210, 125, .14);
      --shadow: 0 20px 42px rgba(0, 0, 0, .3);
      background:
        radial-gradient(circle at 20% 18%, rgba(72, 213, 165, .12), transparent 28%),
        linear-gradient(160deg, #061821, #0a222d 52%, #061821);
    }}
    body.agenda-style-radar .agenda-header {{
      border-bottom: 1px solid rgba(72, 213, 165, .28);
      background: rgba(4, 20, 28, .94);
      color: #effff8;
      box-shadow: 0 12px 32px rgba(0, 0, 0, .32);
    }}
    body.agenda-style-radar .agenda-kicker,
    body.agenda-style-radar .agenda-kind,
    body.agenda-style-radar .agenda-meta dt {{
      letter-spacing: 0;
    }}
    body.agenda-style-radar h1,
    body.agenda-style-radar .agenda-section-heading {{
      font-family: Inter, ui-sans-serif, system-ui, sans-serif;
      font-weight: 850;
    }}
    body.agenda-style-radar .agenda-content {{
      width: min(1240px, 100%);
    }}
    body.agenda-style-radar .agenda-summary {{
      color: #bdd6d0;
    }}
    body.agenda-style-radar .agenda-section {{
      position: relative;
      margin-bottom: 42px;
    }}
    body.agenda-style-radar .agenda-section-heading {{
      color: #effff8;
    }}
    body.agenda-style-radar .agenda-count {{
      border: 1px solid rgba(72, 213, 165, .34);
      background: rgba(72, 213, 165, .14);
      color: #a8ffd7;
    }}
    body.agenda-style-radar .agenda-items {{
      position: relative;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
      min-height: 360px;
      overflow: hidden;
      padding: 64px 28px 28px;
      border: 1px solid rgba(72, 213, 165, .22);
      border-radius: 8px;
      background:
        radial-gradient(circle at center, transparent 0 21%, rgba(72, 213, 165, .18) 21.5% 22%, transparent 22.5% 41%, rgba(72, 213, 165, .16) 41.5% 42%, transparent 42.5% 62%, rgba(72, 213, 165, .14) 62.5% 63%, transparent 63.5%),
        linear-gradient(rgba(72, 213, 165, .08) 1px, transparent 1px),
        linear-gradient(90deg, rgba(72, 213, 165, .08) 1px, transparent 1px),
        rgba(3, 16, 22, .44);
      background-size: auto, 32px 32px, 32px 32px, auto;
    }}
    body.agenda-style-radar .agenda-items::before {{
      content: "";
      position: absolute;
      inset: -38%;
      z-index: 0;
      background: conic-gradient(
        from 0deg,
        rgba(72, 213, 165, .38),
        rgba(72, 213, 165, .08) 32deg,
        transparent 58deg
      );
      opacity: .55;
      transform-origin: center;
      animation: agenda-radar-sweep 8s linear infinite;
      pointer-events: none;
    }}
    body.agenda-style-radar .agenda-items::after {{
      content: "";
      position: absolute;
      inset: 50% auto auto 50%;
      z-index: 0;
      width: 14px;
      height: 14px;
      border-radius: 50%;
      background: #48d5a5;
      box-shadow: 0 0 0 8px rgba(72, 213, 165, .12);
      transform: translate(-50%, -50%);
    }}
    body.agenda-style-radar .agenda-item {{
      position: relative;
      z-index: 1;
      grid-template-columns: 1fr;
      border-color: rgba(72, 213, 165, .28);
      border-radius: 8px;
      background: rgba(6, 28, 36, .9);
      box-shadow: var(--shadow);
      animation: agenda-radar-contact 3.4s ease-in-out infinite;
      animation-delay: calc(var(--agenda-index, 0) * 140ms);
    }}
    body.agenda-style-radar .agenda-item:nth-child(3n + 1) {{
      transform: translateY(-18px);
    }}
    body.agenda-style-radar .agenda-item:nth-child(3n + 2) {{
      transform: translateY(26px);
    }}
    body.agenda-style-radar .agenda-time {{
      border-right: 0;
      border-bottom: 1px solid rgba(72, 213, 165, .18);
      background: rgba(72, 213, 165, .1);
      color: #a8ffd7;
      text-align: left;
    }}
    body.agenda-style-radar .agenda-item h3 {{
      color: #effff8;
    }}
    body.agenda-style-radar .agenda-kind,
    body.agenda-style-radar .agenda-description,
    body.agenda-style-radar .agenda-meta dt,
    body.agenda-style-radar .agenda-meta dd {{
      color: #bdd6d0;
    }}
    body.agenda-style-radar .agenda-badge,
    body.agenda-style-radar .agenda-person {{
      border: 1px solid rgba(72, 213, 165, .24);
      background: rgba(72, 213, 165, .13);
      color: #a8ffd7;
    }}
    body.agenda-style-radar .item-action {{
      border-color: rgba(72, 213, 165, .32);
      border-radius: 6px;
      background: rgba(3, 16, 22, .7);
      color: #effff8;
    }}
    body.agenda-style-radar .item-action.primary {{
      border-color: #48d5a5;
      background: #48d5a5;
      color: #06202a;
    }}
    body.agenda-style-radar .agenda-warning {{
      border: 1px solid rgba(255, 210, 125, .3);
      color: #ffe0a0;
    }}
    body.agenda-style-radar .agenda-metadata {{
      border-top-color: rgba(72, 213, 165, .18);
    }}
    @keyframes agenda-radar-sweep {{
      to {{ transform: rotate(360deg); }}
    }}
    @keyframes agenda-radar-contact {{
      0%, 100% {{ box-shadow: 0 20px 42px rgba(0, 0, 0, .3); }}
      50% {{ box-shadow: 0 20px 42px rgba(0, 0, 0, .3), 0 0 0 4px rgba(72, 213, 165, .12); }}
    }}
    @media (max-width: 720px) {{
      body.agenda-style-radar .agenda-items {{
        min-height: 0;
        padding: 18px;
      }}
      body.agenda-style-radar .agenda-item:nth-child(n) {{
        transform: none;
      }}
    }}
    body.agenda-style-family-orbit {{
      --ink: #20283a;
      --muted: #677386;
      --line: #cad7df;
      --paper: rgba(255, 255, 255, .94);
      --wash: #edf4f6;
      --accent: #237f86;
      --accent-soft: #d8f0ed;
      --warning: #a24a2b;
      --warning-soft: #fff0e7;
      --shadow: 0 18px 38px rgba(30, 50, 70, .14);
      background:
        radial-gradient(circle at 14% 16%, rgba(35, 127, 134, .14), transparent 28%),
        radial-gradient(circle at 88% 22%, rgba(215, 92, 120, .14), transparent 26%),
        #edf4f6;
    }}
    body.agenda-style-family-orbit .agenda-header {{
      border-bottom: 1px solid #c4d3dc;
      background: #24324a;
      color: #f8fbff;
      box-shadow: 0 12px 30px rgba(36, 50, 74, .18);
    }}
    body.agenda-style-family-orbit .agenda-kicker {{
      color: #bfd7dd;
      letter-spacing: 0;
    }}
    body.agenda-style-family-orbit h1,
    body.agenda-style-family-orbit .agenda-section-heading {{
      font-family: Inter, ui-sans-serif, system-ui, sans-serif;
      font-weight: 850;
    }}
    body.agenda-style-family-orbit .agenda-content {{
      width: min(1220px, 100%);
    }}
    body.agenda-style-family-orbit .agenda-section {{
      position: relative;
      margin-bottom: 42px;
    }}
    body.agenda-style-family-orbit .agenda-section-heading {{
      color: #24324a;
    }}
    body.agenda-style-family-orbit .agenda-count {{
      border: 1px solid #afd2d0;
      background: #d8f0ed;
      color: #237f86;
    }}
    body.agenda-style-family-orbit .agenda-items {{
      position: relative;
      grid-template-columns: repeat(auto-fit, minmax(245px, 1fr));
      gap: 18px;
      min-height: 380px;
      overflow: hidden;
      padding: 52px 32px 34px;
      border: 1px solid rgba(54, 94, 122, .18);
      border-radius: 8px;
      background:
        radial-gradient(ellipse at center, transparent 0 18%, rgba(35, 127, 134, .18) 18.5% 19%, transparent 19.5% 38%, rgba(215, 92, 120, .15) 38.5% 39%, transparent 39.5% 58%, rgba(69, 106, 164, .14) 58.5% 59%, transparent 59.5%),
        linear-gradient(135deg, rgba(255, 255, 255, .9), rgba(236, 245, 246, .72));
    }}
    body.agenda-style-family-orbit .agenda-items::before {{
      content: "";
      position: absolute;
      inset: 50% auto auto 50%;
      z-index: 0;
      width: 76px;
      height: 76px;
      border: 1px solid rgba(35, 127, 134, .28);
      border-radius: 50%;
      background:
        radial-gradient(circle, rgba(35, 127, 134, .2), rgba(35, 127, 134, .05));
      box-shadow:
        0 0 0 14px rgba(35, 127, 134, .08),
        0 0 0 32px rgba(215, 92, 120, .06);
      transform: translate(-50%, -50%);
      pointer-events: none;
    }}
    body.agenda-style-family-orbit .agenda-item {{
      position: relative;
      z-index: 1;
      grid-template-columns: 1fr;
      border-color: rgba(54, 94, 122, .2);
      border-radius: 8px;
      background: var(--paper);
      box-shadow: var(--shadow);
      animation: agenda-orbit-float 5.6s ease-in-out infinite;
      animation-delay: calc(var(--agenda-index, 0) * 180ms);
    }}
    body.agenda-style-family-orbit .agenda-item:nth-child(4n + 1) {{
      transform: translateY(-20px) rotate(-1.2deg);
    }}
    body.agenda-style-family-orbit .agenda-item:nth-child(4n + 2) {{
      transform: translateY(24px) rotate(.9deg);
    }}
    body.agenda-style-family-orbit .agenda-item:nth-child(4n + 3) {{
      transform: translateY(-8px) rotate(1.4deg);
    }}
    body.agenda-style-family-orbit .agenda-time {{
      border-right: 0;
      border-bottom: 1px solid #e2edf1;
      background: #ecf7f6;
      color: #237f86;
      text-align: left;
    }}
    body.agenda-style-family-orbit .agenda-kind,
    body.agenda-style-family-orbit .agenda-meta dt {{
      letter-spacing: 0;
    }}
    body.agenda-style-family-orbit .agenda-badge,
    body.agenda-style-family-orbit .agenda-person {{
      border-radius: 6px;
      background: #e8edf9;
      color: #405d95;
    }}
    body.agenda-style-family-orbit .agenda-person {{
      background: #d8f0ed;
      color: #237f86;
    }}
    body.agenda-style-family-orbit .item-action {{
      border-radius: 6px;
    }}
    @keyframes agenda-orbit-float {{
      0%, 100% {{ margin-top: 0; }}
      50% {{ margin-top: -7px; }}
    }}
    @media (max-width: 720px) {{
      body.agenda-style-family-orbit .agenda-items {{
        min-height: 0;
        padding: 18px;
      }}
      body.agenda-style-family-orbit .agenda-item:nth-child(n) {{
        transform: none;
      }}
      body.agenda-style-family-orbit .agenda-items::before {{
        display: none;
      }}
    }}
    body.agenda-style-month-hud {{
      --ink: #eaf9f7;
      --muted: #9dbab6;
      --line: rgba(98, 230, 217, .25);
      --paper: rgba(7, 24, 31, .9);
      --wash: #061014;
      --accent: #62e6d9;
      --accent-soft: rgba(98, 230, 217, .16);
      --warning: #ffbf75;
      --warning-soft: rgba(255, 191, 117, .14);
      --shadow: 0 26px 64px rgba(0, 0, 0, .36);
      background:
        linear-gradient(rgba(98, 230, 217, .045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(98, 230, 217, .04) 1px, transparent 1px),
        linear-gradient(160deg, #061014, #071b22 48%, #061014);
      background-size: 36px 36px, 36px 36px, auto;
    }}
    body.agenda-style-month-hud .agenda-header {{
      border-bottom: 1px solid rgba(98, 230, 217, .24);
      background: rgba(4, 15, 20, .94);
      color: #eaf9f7;
      box-shadow: 0 14px 42px rgba(0, 0, 0, .4);
      backdrop-filter: blur(12px);
    }}
    body.agenda-style-month-hud .agenda-kicker,
    body.agenda-style-month-hud .agenda-kind,
    body.agenda-style-month-hud .agenda-meta dt {{
      letter-spacing: 0;
    }}
    body.agenda-style-month-hud h1 {{
      font-family: Inter, ui-sans-serif, system-ui, sans-serif;
      font-size: 24px;
      font-weight: 850;
    }}
    body.agenda-style-month-hud .agenda-content {{
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      width: 100%;
      min-height: calc(100svh - 84px);
      padding: clamp(10px, 2vh, 20px) clamp(10px, 2vw, 24px) clamp(14px, 3vh, 30px);
    }}
    body.agenda-embedded.agenda-style-month-hud .agenda-content {{
      min-height: 100svh;
    }}
    body.agenda-style-month-hud .agenda-summary {{
      position: relative;
      z-index: 4;
      color: #a9c9c5;
      font-weight: 740;
    }}
    body.agenda-style-month-hud #agendaSections {{
      display: grid;
      min-height: 0;
    }}
    body.agenda-style-month-hud .month-hud {{
      display: grid;
      min-height: 0;
    }}
    body.agenda-style-month-hud .month-hud-stage {{
      --month-hud-node-size: clamp(112px, 9vw, 146px);
      --month-hud-active-size: clamp(210px, 19vw, 284px);
      --month-hud-branch-width: clamp(238px, 23vw, 336px);
      --stage-pan-x: 0px;
      --stage-pan-y: 0px;
      --stage-zoom: 1;
      position: relative;
      isolation: isolate;
      overflow: hidden;
      min-height: max(clamp(650px, calc(100svh - 144px), 980px), var(--month-hud-dynamic-height, 0px));
      border: 1px solid rgba(98, 230, 217, .22);
      border-radius: 8px;
      background:
        linear-gradient(180deg, rgba(16, 43, 52, .9), rgba(5, 19, 25, .92)),
        radial-gradient(circle at 50% 42%, rgba(98, 230, 217, .12), transparent 44%);
      box-shadow:
        var(--shadow),
        inset 0 1px 0 rgba(255, 255, 255, .08);
      cursor: default;
      touch-action: pan-y;
      user-select: none;
    }}
    body.agenda-embedded.agenda-style-month-hud .month-hud-stage {{
      min-height: max(clamp(650px, calc(100svh - 64px), 980px), var(--month-hud-dynamic-height, 0px));
    }}
    body.agenda-style-month-hud .month-hud-stage::before {{
      content: "";
      position: absolute;
      inset: 0;
      z-index: 0;
      background:
        linear-gradient(rgba(255, 255, 255, .04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 255, 255, .035) 1px, transparent 1px);
      background-size: 100% 18px, 18px 100%;
      opacity: .42;
      pointer-events: none;
    }}
    body.agenda-style-month-hud .month-hud.is-dragging-timeline .month-hud-stage {{
      cursor: ew-resize;
    }}
    body.agenda-style-month-hud .month-hud.is-panning-stage .month-hud-stage {{
      cursor: move;
    }}
    body.agenda-style-month-hud .month-hud-canvas {{
      position: absolute;
      inset: 0;
      z-index: 2;
      transform: translate(var(--stage-pan-x), var(--stage-pan-y)) scale(var(--stage-zoom));
      transform-origin: center;
      transition: opacity .46s ease, filter .46s ease, transform .46s cubic-bezier(.2, .8, .2, 1);
      will-change: transform;
      pointer-events: none;
    }}
    body.agenda-style-month-hud .month-hud-canvas::after {{
      content: "";
      position: absolute;
      inset: 50% auto auto 50%;
      z-index: 4;
      width: calc(var(--month-hud-active-size) + 84px);
      height: calc(var(--month-hud-active-size) + 84px);
      border: 1px solid rgba(98, 230, 217, .24);
      border-radius: 50%;
      background:
        radial-gradient(circle, rgba(98, 230, 217, .14), transparent 52%),
        conic-gradient(from 12deg, transparent, rgba(98, 230, 217, .14), transparent 22%, rgba(255, 191, 117, .12), transparent 48%, rgba(98, 230, 217, .12), transparent 74%);
      box-shadow:
        0 0 0 28px rgba(98, 230, 217, .035),
        0 0 70px rgba(98, 230, 217, .18);
      opacity: .86;
      transform: translate(-50%, -50%);
      pointer-events: none;
    }}
    body.agenda-style-month-hud .month-hud:not(.has-selection) .month-hud-canvas::after {{
      opacity: 0;
    }}
    body.agenda-style-month-hud .month-hud-viewport {{
      position: absolute;
      inset: 0;
      z-index: 3;
      overflow: hidden;
      pointer-events: none;
    }}
    body.agenda-style-month-hud .month-hud-year-control {{
      position: absolute;
      left: 50%;
      bottom: clamp(18px, 4vh, 42px);
      z-index: 12;
      display: grid;
      grid-template-columns: minmax(58px, auto) 42px minmax(120px, auto) 42px minmax(58px, auto);
      align-items: center;
      gap: 10px;
      transform: translateX(-50%);
      pointer-events: auto;
    }}
    body.agenda-style-month-hud .month-hud-year-ghost {{
      min-width: 58px;
      color: rgba(169, 201, 197, .45);
      font-size: 13px;
      font-weight: 850;
      text-align: center;
      text-shadow: 0 0 16px rgba(98, 230, 217, .16);
    }}
    body.agenda-style-month-hud .month-hud-year-step,
    body.agenda-style-month-hud .month-hud-year-value,
    body.agenda-style-month-hud .month-hud-year-input {{
      border: 1px solid rgba(98, 230, 217, .32);
      background:
        linear-gradient(135deg, rgba(12, 39, 48, .9), rgba(5, 17, 23, .88));
      box-shadow:
        0 18px 38px rgba(0, 0, 0, .28),
        inset 0 1px 0 rgba(255, 255, 255, .08),
        0 0 32px rgba(98, 230, 217, .12);
      color: #eaf9f7;
      font-family: Inter, ui-sans-serif, system-ui, sans-serif;
      font-weight: 900;
    }}
    body.agenda-style-month-hud .month-hud-year-step {{
      display: grid;
      width: 42px;
      height: 42px;
      place-items: center;
      border-radius: 50%;
      font-size: 22px;
      line-height: 1;
      cursor: pointer;
    }}
    body.agenda-style-month-hud .month-hud-year-value,
    body.agenda-style-month-hud .month-hud-year-input {{
      min-width: 120px;
      min-height: 50px;
      border-radius: 8px;
      color: #8bf7ee;
      font-size: clamp(26px, 3vw, 44px);
      letter-spacing: 0;
      text-align: center;
      text-shadow: 0 0 24px rgba(98, 230, 217, .28);
    }}
    body.agenda-style-month-hud .month-hud-year-value {{
      cursor: text;
    }}
    body.agenda-style-month-hud .month-hud-year-input {{
      padding: 0 10px;
    }}
    body.agenda-style-month-hud .month-hud-year-value[hidden],
    body.agenda-style-month-hud .month-hud-year-input[hidden] {{
      display: none;
    }}
    body.agenda-style-month-hud .month-hud-year-step:hover,
    body.agenda-style-month-hud .month-hud-year-step:focus-visible,
    body.agenda-style-month-hud .month-hud-year-value:hover,
    body.agenda-style-month-hud .month-hud-year-value:focus-visible,
    body.agenda-style-month-hud .month-hud-year-input:focus-visible {{
      border-color: rgba(98, 230, 217, .58);
      box-shadow:
        0 20px 42px rgba(0, 0, 0, .32),
        inset 0 1px 0 rgba(255, 255, 255, .1),
        0 0 44px rgba(98, 230, 217, .2);
      outline: 0;
    }}
    body.agenda-style-month-hud .month-hud.is-changing-year .month-hud-rail,
    body.agenda-style-month-hud .month-hud.is-changing-year .month-hud-branches {{
      opacity: .38;
      filter: blur(.8px) saturate(.75);
    }}
    body.agenda-style-month-hud .month-hud-rail {{
      position: absolute;
      inset: 0;
      min-width: 0;
      perspective: 1400px;
      transform-style: preserve-3d;
      transition: filter .34s ease, opacity .34s ease;
      pointer-events: none;
    }}
    body.agenda-style-month-hud .month-hud-rail::before {{
      content: "";
      position: absolute;
      top: 50%;
      left: -160vw;
      width: 320vw;
      height: 2px;
      background:
        repeating-linear-gradient(90deg, rgba(98, 230, 217, .55) 0 22px, transparent 22px 34px),
        linear-gradient(90deg, transparent, rgba(98, 230, 217, .58), transparent);
      box-shadow: 0 0 24px rgba(98, 230, 217, .22);
      opacity: .74;
      transform: translateY(-50%);
      pointer-events: none;
    }}
    body.agenda-style-month-hud .month-hud.has-selection .month-hud-rail {{
      filter: saturate(.78);
      opacity: .82;
    }}
    body.agenda-style-month-hud .month-hud.has-selection .month-hud-rail::before {{
      opacity: .38;
    }}
    body.agenda-style-month-hud .month-hud-node {{
      position: absolute;
      top: 50%;
      left: 50%;
      z-index: 2;
      display: grid;
      width: var(--month-hud-node-size);
      height: var(--month-hud-node-size);
      min-height: 0;
      min-width: 0;
      place-items: center;
      align-content: center;
      gap: 4px;
      padding: 12px;
      border: 1px solid rgba(98, 230, 217, .22);
      border-radius: 50%;
      background:
        radial-gradient(circle at 50% 35%, rgba(98, 230, 217, .16), transparent 60%),
        rgba(5, 20, 26, .78);
      color: #dffaf7;
      cursor: pointer;
      opacity: var(--month-opacity, .42);
      box-shadow:
        0 18px 42px rgba(0, 0, 0, .24),
        inset 0 1px 0 rgba(255, 255, 255, .08);
      filter: saturate(.85) blur(.1px);
      transform: translate(calc(-50% + var(--month-x, 0px)), calc(-50% + var(--month-y, 0px))) scale(var(--month-scale, .66));
      transition:
        width .42s cubic-bezier(.2, .8, .2, 1),
        height .42s cubic-bezier(.2, .8, .2, 1),
        opacity .34s ease,
        filter .34s ease,
        border-color .22s ease,
        background .22s ease,
        box-shadow .34s ease,
        transform .42s cubic-bezier(.2, .8, .2, 1);
      transform-style: preserve-3d;
      will-change: transform, opacity;
      pointer-events: auto;
    }}
    body.agenda-style-month-hud .month-hud.has-selection .month-hud-node:not(.selected) {{
      box-shadow:
        0 10px 30px rgba(0, 0, 0, .18),
        inset 0 1px 0 rgba(255, 255, 255, .05);
      filter: saturate(.72) blur(.15px);
    }}
    body.agenda-style-month-hud .month-hud-node:hover,
    body.agenda-style-month-hud .month-hud-node:focus-visible {{
      border-color: rgba(98, 230, 217, .42);
      background:
        radial-gradient(circle at 50% 35%, rgba(98, 230, 217, .24), transparent 62%),
        rgba(8, 29, 36, .88);
      outline: 0;
      opacity: .9;
      filter: none;
    }}
    body.agenda-style-month-hud .month-hud-node.selected {{
      z-index: 9;
      width: var(--month-hud-active-size);
      height: var(--month-hud-active-size);
      border-color: rgba(98, 230, 217, .62);
      border-radius: 50%;
      background:
        radial-gradient(circle at 50% 38%, rgba(98, 230, 217, .28), transparent 64%),
        linear-gradient(145deg, rgba(15, 50, 60, .96), rgba(5, 19, 25, .96));
      opacity: 1;
      filter: none;
      box-shadow:
        0 38px 86px rgba(0, 0, 0, .42),
        0 0 0 16px rgba(98, 230, 217, .06),
        0 0 70px rgba(98, 230, 217, .22),
        inset 0 1px 0 rgba(255, 255, 255, .12);
      transform: translate(calc(-50% + var(--month-x, 0px)), calc(-50% + var(--month-y, 0px))) scale(1);
    }}
    body.agenda-style-month-hud .month-hud-ring {{
      position: relative;
      display: grid;
      width: 64%;
      aspect-ratio: 1;
      place-items: center;
      border: 1px solid rgba(98, 230, 217, .48);
      border-radius: 50%;
      background:
        radial-gradient(circle, rgba(98, 230, 217, .22), rgba(98, 230, 217, .04) 58%, transparent 59%);
      box-shadow:
        0 0 0 7px rgba(98, 230, 217, .06),
        0 0 24px rgba(98, 230, 217, .16);
      animation: agenda-month-hud-idle 5.8s ease-in-out infinite;
    }}
    body.agenda-style-month-hud .month-hud-node.selected .month-hud-ring {{
      width: 58%;
      max-width: 178px;
      box-shadow:
        0 0 0 11px rgba(98, 230, 217, .08),
        0 0 46px rgba(98, 230, 217, .3);
    }}
    body.agenda-style-month-hud .month-hud-ring::before {{
      content: "";
      position: absolute;
      inset: 6px;
      border-radius: 50%;
      background: conic-gradient(
        from 0deg,
        rgba(98, 230, 217, .7),
        transparent 46deg,
        rgba(255, 191, 117, .38) 112deg,
        transparent 170deg,
        rgba(98, 230, 217, .5) 260deg,
        transparent 330deg
      );
      opacity: .72;
      mask: radial-gradient(circle, transparent 0 56%, #000 57%);
      animation: agenda-month-hud-spin 8.5s linear infinite;
      pointer-events: none;
    }}
    body.agenda-style-month-hud .month-hud-core {{
      position: relative;
      z-index: 1;
      display: grid;
      width: 54%;
      aspect-ratio: 1;
      place-items: center;
      border: 1px solid rgba(98, 230, 217, .22);
      border-radius: 50%;
      background: rgba(5, 20, 26, .9);
      color: #7ff5ea;
      font-size: clamp(14px, 1.7vw, 22px);
      font-weight: 850;
    }}
    body.agenda-style-month-hud .month-hud-node.has-events .month-hud-core {{
      background: rgba(98, 230, 217, .16);
      color: #f2fffd;
    }}
    body.agenda-style-month-hud .month-hud-node.has-warning .month-hud-ring {{
      border-color: rgba(255, 191, 117, .58);
      animation:
        agenda-month-hud-idle 5.8s ease-in-out infinite,
        agenda-month-hud-warning 2.6s ease-in-out infinite;
    }}
    body.agenda-style-month-hud .month-hud-pip {{
      position: absolute;
      top: 50%;
      left: 50%;
      width: 5px;
      height: 5px;
      border-radius: 50%;
      background: #62e6d9;
      box-shadow: 0 0 8px rgba(98, 230, 217, .8);
      transform: rotate(calc(var(--pip-index, 0) * 38deg)) translateY(calc(var(--month-hud-node-size) * -.31));
      transform-origin: 0 0;
    }}
    body.agenda-style-month-hud .month-hud-node.selected .month-hud-pip {{
      width: 7px;
      height: 7px;
      transform: rotate(calc(var(--pip-index, 0) * 38deg)) translateY(calc(var(--month-hud-active-size) * -.24));
    }}
    body.agenda-style-month-hud .month-hud-node.has-warning .month-hud-pip {{
      background: #ffbf75;
      box-shadow: 0 0 8px rgba(255, 191, 117, .85);
    }}
    body.agenda-style-month-hud .month-hud-month {{
      color: #dffaf7;
      font-size: clamp(13px, 1.2vw, 16px);
      font-weight: 850;
      text-transform: uppercase;
    }}
    body.agenda-style-month-hud .month-hud-node.selected .month-hud-month {{
      font-size: clamp(19px, 2vw, 28px);
      letter-spacing: .08em;
    }}
    body.agenda-style-month-hud .month-hud-count {{
      min-width: 34px;
      padding: 3px 8px;
      border: 1px solid rgba(98, 230, 217, .22);
      border-radius: 999px;
      background: rgba(98, 230, 217, .09);
      color: #a9c9c5;
      font-size: 12px;
      font-weight: 780;
      text-align: center;
    }}
    body.agenda-style-month-hud .month-hud-node.selected .month-hud-count {{
      border-color: rgba(98, 230, 217, .36);
      background: rgba(98, 230, 217, .14);
      color: #dffaf7;
      font-size: 13px;
    }}
    body.agenda-style-month-hud .month-hud-branches {{
      position: absolute;
      inset: 0;
      z-index: 7;
      pointer-events: none;
    }}
    body.agenda-style-month-hud .month-hud:not(.has-selection) .month-hud-branches {{
      display: none;
    }}
    body.agenda-style-month-hud .month-hud-branch {{
      position: absolute;
      inset: 0;
      opacity: 0;
      pointer-events: none;
      animation: agenda-month-hud-branch-in .38s ease-out both;
      animation-delay: calc(var(--agenda-index, 0) * 54ms);
    }}
    body.agenda-style-month-hud .month-hud-circuit {{
      position: absolute;
      inset: 0;
      pointer-events: none;
    }}
    body.agenda-style-month-hud .month-hud-circuit-segment {{
      position: absolute;
      left: var(--circuit-left, 50%);
      top: var(--circuit-top, 50%);
      width: var(--circuit-length, 0px);
      height: 2px;
      border-radius: 999px;
      background: linear-gradient(90deg, rgba(98, 230, 217, .88), rgba(98, 230, 217, .14));
      box-shadow: 0 0 14px rgba(98, 230, 217, .2);
      transform: rotate(var(--circuit-angle, 0deg));
      transform-origin: left center;
    }}
    body.agenda-style-month-hud .month-hud-circuit-segment.is-secondary {{
      background: linear-gradient(90deg, rgba(98, 230, 217, .62), rgba(255, 191, 117, .18));
    }}
    body.agenda-style-month-hud .month-hud-circuit-segment.is-secondary::after {{
      content: "";
      position: absolute;
      right: -3px;
      top: 50%;
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #62e6d9;
      box-shadow: 0 0 12px rgba(98, 230, 217, .72);
      transform: translateY(-50%);
    }}
    body.agenda-style-month-hud .month-hud-branch .agenda-item {{
      position: absolute;
      left: var(--branch-card-left, 50%);
      top: var(--branch-card-top, 50%);
      width: var(--branch-card-width, var(--month-hud-branch-width));
      max-width: calc(100% - 28px);
      grid-template-columns: 1fr;
      border-color: rgba(98, 230, 217, .25);
      border-radius: 8px;
      background:
        linear-gradient(135deg, rgba(14, 42, 51, .94), rgba(5, 17, 23, .92));
      box-shadow:
        0 18px 42px rgba(0, 0, 0, .3),
        inset 0 1px 0 rgba(255, 255, 255, .08);
      transform: translate(-50%, -50%) perspective(1200px) rotateX(1deg);
      transition: box-shadow .18s ease, transform .18s ease;
      pointer-events: auto;
    }}
    body.agenda-style-month-hud .month-hud-branch .agenda-item:hover,
    body.agenda-style-month-hud .month-hud-branch .agenda-item:focus-within {{
      box-shadow: 0 24px 52px rgba(0, 0, 0, .36);
      transform: translate(-50%, calc(-50% - 3px)) perspective(1200px) rotateX(0) rotateY(0);
    }}
    body.agenda-style-month-hud .month-hud-branch .agenda-item.month-hud-editable-card {{
      cursor: pointer;
    }}
    body.agenda-style-month-hud .month-hud.is-editing-card .month-hud-canvas {{
      opacity: .28;
      filter: blur(1.6px) saturate(.54);
      transform: translate(var(--stage-pan-x), var(--stage-pan-y)) scale(calc(var(--stage-zoom) * .92));
    }}
    body.agenda-style-month-hud .month-hud.is-editing-card .month-hud-stage::before {{
      opacity: .2;
    }}
    body.agenda-style-month-hud .month-hud-edit-layer {{
      position: absolute;
      inset: 0;
      z-index: 30;
      display: grid;
      place-items: center;
      padding: clamp(18px, 4vw, 44px);
      background:
        radial-gradient(circle at center, rgba(98, 230, 217, .16), transparent 34%),
        rgba(2, 9, 12, .46);
      opacity: 1;
      transition: opacity .5s ease;
      pointer-events: auto;
    }}
    body.agenda-style-month-hud .month-hud-edit-layer.is-closing {{
      opacity: 0;
    }}
    body.agenda-style-month-hud .month-hud-card-editor {{
      display: grid;
      width: min(640px, 100%);
      max-height: min(760px, calc(100svh - 86px));
      overflow: auto;
      gap: 16px;
      padding: 20px;
      border: 1px solid rgba(98, 230, 217, .34);
      border-radius: 8px;
      background:
        linear-gradient(135deg, #0d303a, #06131a);
      box-shadow:
        0 42px 92px rgba(0, 0, 0, .48),
        0 0 0 1px rgba(255, 255, 255, .06) inset,
        0 0 86px rgba(98, 230, 217, .18);
      color: #eaf9f7;
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0) scale(1);
      transition: opacity .46s ease, filter .3s ease, transform .5s cubic-bezier(.2, .8, .2, 1);
      user-select: text;
    }}
    body.agenda-style-month-hud .month-hud-card-editor.has-confirmation {{
      filter: blur(1.2px) saturate(.62);
      opacity: .32;
      pointer-events: none;
      transform: translateY(0) scale(.985);
    }}
    body.agenda-style-month-hud .month-hud-edit-layer.is-closing .month-hud-card-editor {{
      opacity: 0;
      pointer-events: none;
      transform: translateY(14px) scale(.96);
    }}
    body.agenda-style-month-hud .month-hud-confirm-layer {{
      position: absolute;
      inset: 0;
      z-index: 4;
      display: grid;
      place-items: center;
      padding: clamp(18px, 4vw, 44px);
      background:
        radial-gradient(circle at center, rgba(255, 91, 91, .22), transparent 36%),
        rgba(20, 3, 7, .5);
      opacity: 0;
      pointer-events: auto;
      transition: opacity .28s ease;
    }}
    body.agenda-style-month-hud .month-hud-confirm-layer.is-open {{
      opacity: 1;
    }}
    body.agenda-style-month-hud .month-hud-confirm-layer.is-closing {{
      opacity: 0;
    }}
    body.agenda-style-month-hud .month-hud-confirm-dialog {{
      display: grid;
      width: min(460px, 100%);
      gap: 14px;
      padding: 20px;
      border: 1px solid rgba(255, 103, 103, .48);
      border-radius: 8px;
      background:
        linear-gradient(135deg, #42141a, #16070a);
      box-shadow:
        0 42px 92px rgba(0, 0, 0, .5),
        0 0 0 1px rgba(255, 255, 255, .06) inset,
        0 0 86px rgba(255, 91, 91, .18);
      color: #fff2f2;
      opacity: 0;
      transform: translateY(16px) scale(.96);
      transition: opacity .28s ease, transform .32s cubic-bezier(.2, .8, .2, 1);
    }}
    body.agenda-style-month-hud .month-hud-confirm-layer.is-open .month-hud-confirm-dialog {{
      opacity: 1;
      transform: translateY(0) scale(1);
    }}
    body.agenda-style-month-hud .month-hud-confirm-layer.is-closing .month-hud-confirm-dialog {{
      opacity: 0;
      transform: translateY(12px) scale(.96);
    }}
    body.agenda-style-month-hud .month-hud-confirm-dialog header {{
      display: grid;
      gap: 6px;
    }}
    body.agenda-style-month-hud .month-hud-confirm-kicker {{
      color: #ffb1a7;
      font-size: 12px;
      font-weight: 850;
      text-transform: uppercase;
    }}
    body.agenda-style-month-hud .month-hud-confirm-dialog h3 {{
      margin: 0;
      color: #fffafa;
      font-size: 22px;
      line-height: 1.18;
    }}
    body.agenda-style-month-hud .month-hud-confirm-dialog p {{
      margin: 0;
      color: #ffd6d2;
      font-size: 14px;
      font-weight: 650;
      line-height: 1.5;
    }}
    body.agenda-style-month-hud .month-hud-card-editor header {{
      display: grid;
      gap: 5px;
      padding-bottom: 12px;
      border-bottom: 1px solid rgba(98, 230, 217, .18);
    }}
    body.agenda-style-month-hud .month-hud-edit-kicker {{
      color: #8bf7ee;
      font-size: 12px;
      font-weight: 850;
      text-transform: uppercase;
    }}
    body.agenda-style-month-hud .month-hud-card-editor h2 {{
      margin: 0;
      color: #f2fffd;
      font-size: 24px;
      line-height: 1.18;
    }}
    body.agenda-style-month-hud .month-hud-edit-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    body.agenda-style-month-hud .month-hud-edit-field {{
      display: grid;
      gap: 5px;
      min-width: 0;
      color: #a9c9c5;
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
    }}
    body.agenda-style-month-hud .month-hud-edit-field.wide {{
      grid-column: 1 / -1;
    }}
    body.agenda-style-month-hud .month-hud-edit-field input,
    body.agenda-style-month-hud .month-hud-edit-field select,
    body.agenda-style-month-hud .month-hud-check-menu,
    body.agenda-style-month-hud .month-hud-edit-field textarea {{
      width: 100%;
      min-width: 0;
      border: 1px solid rgba(98, 230, 217, .26);
      border-radius: 8px;
      background: rgba(5, 17, 23, .88);
      color: #f2fffd;
      font: inherit;
      font-size: 14px;
      font-weight: 650;
      padding: 9px 10px;
      text-transform: none;
    }}
    body.agenda-style-month-hud .month-hud-edit-field select {{
      appearance: auto;
    }}
    body.agenda-style-month-hud .month-hud-check-menu {{
      position: relative;
      padding: 0;
    }}
    body.agenda-style-month-hud .month-hud-check-menu summary {{
      min-height: 38px;
      padding: 9px 10px;
      cursor: pointer;
      list-style-position: inside;
    }}
    body.agenda-style-month-hud .month-hud-check-options {{
      display: grid;
      gap: 4px;
      max-height: 190px;
      overflow: auto;
      padding: 2px 10px 10px;
    }}
    body.agenda-style-month-hud .month-hud-check-option {{
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 30px;
      color: #eaf9f7;
      font-size: 13px;
      font-weight: 700;
      text-transform: none;
      cursor: pointer;
    }}
    body.agenda-style-month-hud .month-hud-check-option input {{
      width: 16px;
      min-width: 16px;
      height: 16px;
      padding: 0;
      accent-color: #62e6d9;
    }}
    body.agenda-style-month-hud .month-hud-check-empty {{
      padding: 0 10px 10px;
      color: #a9c9c5;
      font-size: 13px;
      font-weight: 650;
      text-transform: none;
    }}
    body.agenda-style-month-hud .month-hud-edit-field textarea {{
      resize: vertical;
    }}
    body.agenda-style-month-hud .month-hud-edit-field input:focus-visible,
    body.agenda-style-month-hud .month-hud-edit-field select:focus-visible,
    body.agenda-style-month-hud .month-hud-check-menu:focus-within,
    body.agenda-style-month-hud .month-hud-edit-field textarea:focus-visible {{
      border-color: #62e6d9;
      outline: 2px solid rgba(98, 230, 217, .18);
      outline-offset: 1px;
    }}
    body.agenda-style-month-hud .month-hud-edit-actions,
    body.agenda-style-month-hud .month-hud-confirm-actions {{
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      flex-wrap: wrap;
      padding-top: 2px;
    }}
    body.agenda-style-month-hud .month-hud-edit-actions .item-action,
    body.agenda-style-month-hud .month-hud-confirm-actions .item-action {{
      min-height: 38px;
      border-color: rgba(98, 230, 217, .32);
      border-radius: 6px;
      background: rgba(7, 24, 31, .82);
      color: #eaf9f7;
      padding: 0 16px;
    }}
    body.agenda-style-month-hud .month-hud-edit-actions .item-action.primary,
    body.agenda-style-month-hud .month-hud-confirm-actions .item-action.primary {{
      border-color: #62e6d9;
      background: #62e6d9;
      color: #041115;
    }}
    body.agenda-style-month-hud .month-hud-edit-actions .item-action.danger,
    body.agenda-style-month-hud .month-hud-confirm-actions .item-action.danger {{
      border-color: rgba(255, 191, 117, .45);
      background: rgba(255, 191, 117, .12);
      color: #ffd5a1;
    }}
    body.agenda-style-month-hud .month-hud-confirm-actions .item-action.danger {{
      border-color: #ff6767;
      background: #ff6767;
      color: #21070a;
    }}
    body.agenda-style-month-hud .month-hud-branch .agenda-time {{
      border-right: 0;
      border-bottom: 1px solid rgba(98, 230, 217, .18);
      background: rgba(98, 230, 217, .09);
      color: #8bf7ee;
      padding: 10px 12px;
      font-size: 12px;
      text-align: left;
    }}
    body.agenda-style-month-hud .month-hud-branch .agenda-item-body {{
      padding: 12px 13px 13px;
    }}
    body.agenda-style-month-hud .month-hud-branch .agenda-item h3 {{
      color: #f2fffd;
      font-size: 15px;
    }}
    body.agenda-style-month-hud .month-hud-branch .agenda-kind,
    body.agenda-style-month-hud .month-hud-branch .agenda-description,
    body.agenda-style-month-hud .month-hud-branch .agenda-meta dt,
    body.agenda-style-month-hud .month-hud-branch .agenda-meta dd {{
      color: #a9c9c5;
    }}
    body.agenda-style-month-hud .month-hud-branch .agenda-description {{
      display: -webkit-box;
      overflow: hidden;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
    }}
    body.agenda-style-month-hud .month-hud-branch .agenda-badge,
    body.agenda-style-month-hud .month-hud-branch .agenda-person {{
      border: 1px solid rgba(98, 230, 217, .24);
      background: rgba(98, 230, 217, .13);
      color: #b6fff8;
    }}
    body.agenda-style-month-hud .month-hud-branch .agenda-warning {{
      border: 1px solid rgba(255, 191, 117, .34);
      color: #ffd5a1;
    }}
    body.agenda-style-month-hud .month-hud-branch .agenda-metadata {{
      border-top-color: rgba(98, 230, 217, .18);
    }}
    body.agenda-style-month-hud .month-hud-branch .item-action {{
      border-color: rgba(98, 230, 217, .32);
      border-radius: 6px;
      background: rgba(7, 24, 31, .74);
      color: #eaf9f7;
    }}
    body.agenda-style-month-hud .month-hud-branch .item-action.primary {{
      border-color: #62e6d9;
      background: #2cc8b8;
      color: #051115;
    }}
    body.agenda-style-month-hud .month-hud-empty {{
      position: absolute;
      left: var(--branch-card-left, 50%);
      top: var(--branch-card-top, calc(50% + 180px));
      z-index: 8;
      width: min(320px, calc(100% - 34px));
      padding: 18px 20px;
      border: 1px dashed rgba(98, 230, 217, .28);
      border-radius: 8px;
      background: rgba(98, 230, 217, .06);
      color: #a9c9c5;
      font-weight: 720;
      text-align: center;
      transform: translate(-50%, -50%);
      pointer-events: none;
    }}
    body.agenda-style-month-hud .agenda-empty {{
      border-color: rgba(98, 230, 217, .28);
      background: rgba(7, 24, 31, .78);
      color: #a9c9c5;
    }}
    body.agenda-style-month-hud .agenda-modal {{
      border: 1px solid rgba(98, 230, 217, .26);
      background: #07171d;
    }}
    body.agenda-style-month-hud .agenda-modal header {{
      border-bottom-color: rgba(98, 230, 217, .2);
    }}
    body.agenda-style-month-hud .editor-field input,
    body.agenda-style-month-hud .editor-field textarea,
    body.agenda-style-month-hud .editor-field select {{
      border-color: rgba(98, 230, 217, .28);
      background: rgba(5, 17, 23, .96);
      color: #eaf9f7;
    }}
    @keyframes agenda-month-hud-idle {{
      0%, 100% {{
        box-shadow:
          0 0 0 7px rgba(98, 230, 217, .06),
          0 0 24px rgba(98, 230, 217, .16);
      }}
      50% {{
        box-shadow:
          0 0 0 10px rgba(98, 230, 217, .1),
          0 0 34px rgba(98, 230, 217, .26);
      }}
    }}
    @keyframes agenda-month-hud-spin {{
      to {{ transform: rotate(360deg); }}
    }}
    @keyframes agenda-month-hud-warning {{
      0%, 100% {{ box-shadow: 0 0 0 7px rgba(255, 191, 117, .08), 0 0 24px rgba(98, 230, 217, .16); }}
      50% {{ box-shadow: 0 0 0 10px rgba(255, 191, 117, .16), 0 0 36px rgba(255, 191, 117, .24); }}
    }}
    @keyframes agenda-month-hud-branch-in {{
      from {{
        opacity: 0;
        transform: scale(.97);
      }}
      to {{
        opacity: 1;
      }}
    }}
    @keyframes agenda-month-hud-card-focus {{
      from {{
        opacity: 0;
        transform: perspective(1200px) rotateX(5deg) translateY(18px) scale(.96);
      }}
      to {{
        opacity: 1;
        transform: perspective(1200px) rotateX(0) translateY(0) scale(1);
      }}
    }}
    @media (max-width: 720px) {{
      body.agenda-style-month-hud .agenda-content {{
        padding: 12px;
      }}
      body.agenda-style-month-hud .month-hud-stage {{
        --month-hud-node-size: clamp(90px, 25vw, 116px);
        --month-hud-active-size: clamp(172px, 52vw, 228px);
        --month-hud-branch-width: min(330px, calc(100vw - 42px));
        min-height: max(clamp(700px, calc(100svh - 88px), 920px), var(--month-hud-dynamic-height, 0px));
      }}
      body.agenda-style-month-hud .month-hud-node {{
        padding: 8px;
      }}
      body.agenda-style-month-hud .month-hud-node.selected .month-hud-month {{
        font-size: clamp(17px, 6vw, 23px);
      }}
      body.agenda-style-month-hud .month-hud-circuit-segment {{
        opacity: .7;
      }}
      body.agenda-style-month-hud .month-hud-branch .agenda-item,
      body.agenda-style-month-hud .month-hud-branch .agenda-item:hover,
      body.agenda-style-month-hud .month-hud-branch .agenda-item:focus-within {{
        transform: translate(-50%, -50%);
      }}
      body.agenda-style-month-hud .month-hud-edit-layer {{
        padding: 14px;
      }}
      body.agenda-style-month-hud .month-hud-edit-grid {{
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
      const current = new URLSearchParams(window.location.search);
      for (const key of ["workspace_id", "context_id", "connection_id", "lease_token"]) {{
        const value = current.get(key);
        if (value) url.searchParams.set(key, value);
      }}
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

    function itemDate(item) {{
      const value = item.start_at || item.due_at;
      if (!value) return null;
      const parsed = new Date(value);
      return Number.isNaN(parsed.getTime()) ? null : parsed;
    }}

    function monthKeyFromDate(date) {{
      return `${{date.getUTCFullYear()}}-${{String(date.getUTCMonth() + 1).padStart(2, "0")}}`;
    }}

    function itemMonthKey(item) {{
      const parsed = itemDate(item);
      return parsed ? monthKeyFromDate(parsed) : "";
    }}

    function referenceDate() {{
      const value = AGENDA_DATA.reference_date || new Date().toISOString().slice(0, 10);
      const parsed = new Date(`${{value}}T12:00:00Z`);
      return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
    }}

    function monthDescriptor(key) {{
      const [year, month] = key.split("-").map((part) => Number.parseInt(part, 10));
      const date = new Date(Date.UTC(year, month - 1, 1, 12));
      return {{
        key,
        short: new Intl.DateTimeFormat(undefined, {{ month: "short", timeZone: "UTC" }}).format(date),
        label: new Intl.DateTimeFormat(undefined, {{ month: "long", year: "numeric", timeZone: "UTC" }}).format(date),
      }};
    }}

    function monthSequence(year) {{
      const keys = [];
      for (let index = 0; index < 12; index += 1) {{
        keys.push(`${{year}}-${{String(index + 1).padStart(2, "0")}}`);
      }}
      return keys.map(monthDescriptor);
    }}

    function itemNeedsAttention(item) {{
      const status = String(item.status || "").toLowerCase();
      return Boolean(item.warning) || item.kind === "warning" ||
        ["overdue", "needs_review", "needs-attention"].includes(status);
    }}

    function jumpToToday() {{
      if ((AGENDA_DATA.style || "default") === "month-hud") {{
        const monthButton = sectionsRoot.querySelector(`[data-month="${{monthKeyFromDate(referenceDate())}}"]`);
        monthButton?.click();
        sectionsRoot.scrollIntoView({{ behavior: "smooth", block: "start" }});
        return;
      }}
      document.getElementById("section-today")?.scrollIntoView({{ behavior: "smooth" }});
    }}

    function itemTime(item) {{
      const parsed = itemDate(item);
      if (!parsed) return "No date";
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

    async function submitAgendaAction(item, action) {{
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
      return response.json();
    }}

    async function invokeAction(item, action) {{
      if (action.editor) {{
        await openEditor(item, action);
        return;
      }}
      await submitAgendaAction(item, action);
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

    function renderItem(item, index = 0, options = {{}}) {{
      const article = element("article", `agenda-item ${{item.status || ""}}`);
      article.dataset.itemId = item.id;
      article.style.setProperty("--agenda-index", String(index));
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
      if (!options.hideActions && (item.actions || []).length) {{
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

    function agendaInlineDateValue(item) {{
      const parsed = itemDate(item);
      return parsed ? parsed.toISOString().slice(0, 16) : "";
    }}

    function agendaInlineDateSerialized(value) {{
      if (!value) return "";
      const parsed = new Date(value);
      return Number.isNaN(parsed.getTime()) ? "" : parsed.toISOString();
    }}

    function agendaInlineCsvLabels(values) {{
      return (values || [])
        .map((entry) => entry && (entry.label || entry.value || entry.id || entry))
        .map((entry) => String(entry || "").trim())
        .filter(Boolean)
        .join(", ");
    }}

    function agendaInlineCsvEntries(value) {{
      return String(value || "")
        .split(",")
        .map((entry) => entry.trim())
        .filter(Boolean)
        .map((label, index) => ({{
          id: `inline:${{index}}:${{label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}}`,
          label,
        }}));
    }}

    function agendaInlinePeopleEntries(value) {{
      const entries = Array.isArray(value) ? value : agendaInlineCsvEntries(value);
      return entries
        .map((entry, index) => {{
          if (!entry) return null;
          const label = String(entry.label || entry.value || entry.id || entry).trim();
          if (!label) return null;
          return {{
            id: entry.id || `inline:${{index}}:${{label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}}`,
            label,
            ...(entry.color ? {{ color: entry.color }} : {{}}),
          }};
        }})
        .filter(Boolean);
    }}

    function applyAgendaInlineDraft(item, draft) {{
      item.title = draft.title || item.title || "Untitled item";
      item.kind = draft.kind || item.kind || "item";
      if (draft.status) item.status = draft.status;
      else delete item.status;

      const dateTarget = item.start_at
        ? "start_at"
        : (item.due_at ? "due_at" : (item.kind === "event" ? "start_at" : "due_at"));
      delete item.start_at;
      delete item.due_at;
      const when = agendaInlineDateSerialized(draft.when);
      if (when) item[dateTarget] = when;
      item.date_only = false;

      if (draft.description) item.description = draft.description;
      else delete item.description;

      const badges = agendaInlineCsvEntries(draft.badges).map((entry) => entry.label);
      if (badges.length) item.badges = badges;
      else delete item.badges;

      const people = agendaInlinePeopleEntries(draft.people);
      delete item.participants;
      delete item.assignees;
      if (people.length && item.kind === "event") item.participants = people;
      else if (people.length) item.assignees = people;

      if (draft.warning) {{
        item.warning = {{
          ...(typeof item.warning === "object" && item.warning ? item.warning : {{}}),
          message: draft.warning,
        }};
      }} else {{
        delete item.warning;
      }}
    }}

    function removeAgendaInlineItem(item) {{
      const items = AGENDA_DATA.items || [];
      const index = items.findIndex((entry) => entry.id === item.id);
      if (index >= 0) items.splice(index, 1);
    }}

    function replaceAgendaInlineItem(item, replacement) {{
      if (!replacement) return item;
      const items = AGENDA_DATA.items || [];
      const index = items.findIndex((entry) => entry.id === item.id);
      Object.assign(item, replacement);
      if (index >= 0) items[index] = item;
      else items.push(item);
      return item;
    }}

    async function submitMonthHudEditor(item, submissionId, values = {{}}) {{
      const response = await fetch(contextUrl("/api/agenda/editor"), {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          provider: AGENDA_DATA.provider,
          item_id: item.id,
          item_version: item.version,
          action_id: "edit",
          submission_id: submissionId,
          values,
          idempotency_key: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
        }}),
      }});
      if (!response.ok) throw new Error((await response.text()) || "Could not save agenda card");
      return response.json();
    }}

    function monthHudEditField(labelText, control, wide = false) {{
      const wrapperTag = control.tagName === "DETAILS" ? "div" : "label";
      const label = element(wrapperTag, wide ? "month-hud-edit-field wide" : "month-hud-edit-field");
      label.append(element("span", "", labelText), control);
      return label;
    }}

    function monthHudOptionLabel(value) {{
      if (!value) return "None";
      return String(value)
        .replaceAll("_", " ")
        .replaceAll("-", " ")
        .split(" ")
        .filter(Boolean)
        .map((part) => `${{part.charAt(0).toUpperCase()}}${{part.slice(1)}}`)
        .join(" ");
    }}

    function monthHudOptionValues(defaultValues, currentValue) {{
      const values = [...defaultValues];
      const current = String(currentValue || "").trim();
      if (current && !values.includes(current)) values.push(current);
      return values;
    }}

    function monthHudSelect(name, options, selectedValue) {{
      const select = element("select", "month-hud-edit-select");
      select.name = name;
      const selected = String(selectedValue || "");
      for (const value of options) {{
        const option = element("option", "", monthHudOptionLabel(value));
        option.value = value;
        option.selected = value === selected;
        select.append(option);
      }}
      return select;
    }}

    function monthHudPersonKey(person) {{
      const id = String(person?.id || "").trim();
      if (id) return id;
      return String(person?.label || person?.value || person || "").trim().toLowerCase();
    }}

    function monthHudPeopleOptions() {{
      const peopleByKey = new Map();
      for (const agendaItem of AGENDA_DATA.items || []) {{
        for (const person of [...(agendaItem.participants || []), ...(agendaItem.assignees || [])]) {{
          const key = monthHudPersonKey(person);
          const label = String(person?.label || person?.value || person?.id || person || "").trim();
          if (!key || !label || peopleByKey.has(key)) continue;
          peopleByKey.set(key, {{
            id: String(person?.id || key),
            label,
            ...(person?.color ? {{ color: person.color }} : {{}}),
          }});
        }}
      }}
      return Array.from(peopleByKey.values())
        .sort((left, right) => left.label.localeCompare(right.label));
    }}

    function monthHudSelectedPersonKeys(item) {{
      return new Set([...(item.participants || []), ...(item.assignees || [])]
        .map(monthHudPersonKey)
        .filter(Boolean));
    }}

    function monthHudCheckedPeople(menu) {{
      return Array.from(menu.querySelectorAll('input[type="checkbox"]:checked'))
        .map((checkbox) => ({{
          id: checkbox.value,
          label: checkbox.dataset.label || checkbox.value,
          ...(checkbox.dataset.color ? {{ color: checkbox.dataset.color }} : {{}}),
        }}));
    }}

    function monthHudPeoplePicker(item) {{
      const menu = element("details", "month-hud-check-menu");
      const summary = element("summary");
      const optionsRoot = element("div", "month-hud-check-options");
      const choices = monthHudPeopleOptions();
      const selected = monthHudSelectedPersonKeys(item);

      function updateSummary() {{
        const labels = Array.from(menu.querySelectorAll('input[type="checkbox"]:checked'))
          .map((checkbox) => checkbox.dataset.label || checkbox.value);
        summary.textContent = labels.length === 0
          ? "No people"
          : (labels.length === 1 ? labels[0] : `${{labels[0]}} + ${{labels.length - 1}}`);
      }}

      if (!choices.length) {{
        optionsRoot.append(element("div", "month-hud-check-empty", "No people available"));
      }}
      for (const person of choices) {{
        const label = element("label", "month-hud-check-option");
        const checkbox = element("input");
        checkbox.type = "checkbox";
        checkbox.value = person.id || person.label;
        checkbox.dataset.label = person.label;
        checkbox.dataset.personKey = monthHudPersonKey(person);
        checkbox.checked = selected.has(checkbox.dataset.personKey);
        if (person.color) checkbox.dataset.color = person.color;
        checkbox.addEventListener("change", updateSummary);
        label.append(checkbox, element("span", "", person.label));
        optionsRoot.append(label);
      }}
      menu.append(summary, optionsRoot);
      updateSummary();
      return menu;
    }}

    function openMonthHudCardEditor(root, host, item, callbacks) {{
      host.querySelector(".month-hud-edit-layer")?.remove();
      root.classList.add("is-editing-card");
      const layer = element("div", "month-hud-edit-layer");
      const form = element("form", "month-hud-card-editor");
      form.noValidate = true;
      form.setAttribute("aria-label", `Edit ${{item.title || "agenda item"}}`);
      const header = element("header");
      header.append(
        element("div", "month-hud-edit-kicker", `${{itemTime(item)}} · ${{item.kind || "item"}}`),
        element("h2", "", item.title || "Untitled item"),
      );

      const title = element("input");
      title.name = "title";
      title.value = item.title || "";
      title.required = true;

      const kind = monthHudSelect(
        "kind",
        monthHudOptionValues(["event", "task", "note", "warning"], item.kind || "task"),
        item.kind || "task",
      );

      const status = monthHudSelect(
        "status",
        monthHudOptionValues([
          "",
          "suggested",
          "proposed",
          "needs_review",
          "needs-attention",
          "overdue",
          "complete",
          "dismissed",
        ], item.status || ""),
        item.status || "",
      );

      const when = element("input");
      when.name = "when";
      when.type = "datetime-local";
      when.value = agendaInlineDateValue(item);

      const people = monthHudPeoplePicker(item);

      const badges = element("input");
      badges.name = "badges";
      badges.value = agendaInlineCsvLabels(item.badges || []);

      const description = element("textarea");
      description.name = "description";
      description.rows = 4;
      description.value = item.description || "";

      const warning = element("textarea");
      warning.name = "warning";
      warning.rows = 2;
      warning.value = item.warning
        ? String(item.warning.message || item.warning || "")
        : "";

      const grid = element("div", "month-hud-edit-grid");
      grid.append(
        monthHudEditField("Title", title, true),
        monthHudEditField("Kind", kind),
        monthHudEditField("Status", status),
        monthHudEditField("When", when),
        monthHudEditField("People", people),
        monthHudEditField("Badges", badges, true),
        monthHudEditField("Description", description, true),
        monthHudEditField("Warning", warning, true),
      );

      const actions = element("div", "month-hud-edit-actions");
      const discard = element("button", "item-action danger", "Discard");
      discard.type = "button";
      const approve = element("button", "item-action primary", "Approve");
      approve.type = "button";
      const error = element("div", "editor-error");
      error.setAttribute("role", "alert");
      actions.append(discard, approve);
      let editorClosing = false;
      let discardConfirmation = null;

      function closeEditor() {{
        if (editorClosing) return;
        editorClosing = true;
        root.classList.remove("is-editing-card");
        layer.classList.add("is-closing");
        const removeLayer = () => {{
          if (layer.isConnected) layer.remove();
        }};
        layer.addEventListener("transitionend", (event) => {{
          if (event.target === layer) removeLayer();
        }}, {{ once: true }});
        window.setTimeout(removeLayer, 560);
      }}

      function closeDiscardConfirmation() {{
        if (!discardConfirmation || discardConfirmation.classList.contains("is-closing")) return;
        const confirmation = discardConfirmation;
        discardConfirmation = null;
        form.classList.remove("has-confirmation");
        confirmation.classList.remove("is-open");
        confirmation.classList.add("is-closing");
        const removeConfirmation = () => {{
          if (confirmation.isConnected) confirmation.remove();
        }};
        confirmation.addEventListener("transitionend", (event) => {{
          if (event.target === confirmation) removeConfirmation();
        }}, {{ once: true }});
        window.setTimeout(removeConfirmation, 360);
      }}

      function openDiscardConfirmation() {{
        if (editorClosing || discardConfirmation) return;
        form.classList.add("has-confirmation");
        const confirmation = element("div", "month-hud-confirm-layer");
        confirmation.setAttribute("role", "dialog");
        confirmation.setAttribute("aria-modal", "true");
        confirmation.setAttribute("aria-label", "Discard agenda card");
        const dialog = element("section", "month-hud-confirm-dialog");
        const confirmHeader = element("header");
        confirmHeader.append(
          element("div", "month-hud-confirm-kicker", "Delete event"),
          element("h3", "", "Discard this card?"),
        );
        const message = element(
          "p",
          "",
          "Discarding this card will delete the event from the agenda.",
        );
        const confirmActions = element("div", "month-hud-confirm-actions");
        const cancel = element("button", "item-action", "Cancel");
        cancel.type = "button";
        const ok = element("button", "item-action danger", "OK");
        ok.type = "button";
        confirmActions.append(cancel, ok);
        dialog.append(confirmHeader, message, confirmActions);
        confirmation.append(dialog);
        confirmation.addEventListener("click", (event) => {{
          event.stopPropagation();
          if (event.target === confirmation) closeDiscardConfirmation();
        }});
        cancel.addEventListener("click", closeDiscardConfirmation);
        ok.addEventListener("click", async () => {{
          if (editorClosing) return;
          ok.disabled = true;
          cancel.disabled = true;
          discard.disabled = true;
          approve.disabled = true;
          error.textContent = "";
          try {{
            await callbacks.onDiscard();
            closeEditor();
          }} catch (problem) {{
            error.textContent = problem.message || "Could not discard agenda card";
            ok.disabled = false;
            cancel.disabled = false;
            discard.disabled = false;
            approve.disabled = false;
            closeDiscardConfirmation();
          }}
        }});
        layer.append(confirmation);
        discardConfirmation = confirmation;
        requestAnimationFrame(() => confirmation.classList.add("is-open"));
        cancel.focus();
      }}

      async function approveDraft() {{
        if (editorClosing || approve.disabled) return;
        approve.disabled = true;
        discard.disabled = true;
        error.textContent = "";
        try {{
          await callbacks.onApprove({{
            title: title.value.trim(),
            kind: kind.value,
            status: status.value,
            when: when.value,
            people: monthHudCheckedPeople(people),
            badges: badges.value,
            description: description.value.trim(),
            warning: warning.value.trim(),
          }});
          closeEditor();
        }} catch (problem) {{
          error.textContent = problem.message || "Could not save agenda card";
          approve.disabled = false;
          discard.disabled = false;
        }}
      }}

      form.addEventListener("submit", (event) => {{
        event.preventDefault();
        void approveDraft();
      }});
      approve.addEventListener("click", () => {{
        void approveDraft();
      }});
      discard.addEventListener("click", () => {{
        openDiscardConfirmation();
      }});
      layer.addEventListener("click", (event) => {{
        event.stopPropagation();
        if (editorClosing) return;
        if (event.target === layer) closeEditor();
      }});
      form.append(header, grid, error, actions);
      layer.append(form);
      host.append(layer);
      title.focus();
      title.select();
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
      today.addEventListener("click", jumpToToday);
      controls.append(today);
    }}

    function renderMonthHud() {{
      renderControls();
      sectionsRoot.replaceChildren();
      const allItems = AGENDA_DATA.items || [];
      let grouped = new Map();

      function rebuildMonthGroups() {{
        grouped = new Map();
        for (const item of allItems) {{
          const key = itemMonthKey(item);
          if (!key) continue;
          if (!grouped.has(key)) grouped.set(key, []);
          grouped.get(key).push(item);
        }}
        for (const [key, items] of grouped.entries()) {{
          grouped.set(key, [...items].sort((left, right) => {{
            const leftDate = itemDate(left);
            const rightDate = itemDate(right);
            return (leftDate ? leftDate.getTime() : 0) - (rightDate ? rightDate.getTime() : 0);
          }}));
        }}
      }}

      function updateMonthHudSummary() {{
        const datedCount = allItems.filter((item) => itemMonthKey(item)).length;
        const undated = allItems.length - datedCount;
        if (allItems.length === 1) {{
          summary.textContent = undated ? "1 item · no dated month" : "1 item by month";
        }} else {{
          summary.textContent = `${{allItems.length}} items by month${{undated ? ` · ${{undated}} unscheduled` : ""}}`;
        }}
        notifyAgendaHost();
      }}

      rebuildMonthGroups();
      let displayYear = referenceDate().getUTCFullYear();
      let months = monthSequence(displayYear);
      updateMonthHudSummary();

      const root = element("section", "month-hud");
      root.setAttribute("aria-label", "Month HUD agenda");
      const stage = element("div", "month-hud-stage");
      const canvas = element("div", "month-hud-canvas");
      const viewport = element("div", "month-hud-viewport");
      const rail = element("div", "month-hud-rail");
      const branchesRoot = element("div", "month-hud-branches");
      branchesRoot.setAttribute("aria-live", "polite");
      const yearControl = element("div", "month-hud-year-control");
      yearControl.setAttribute("aria-label", "Month HUD year");
      const previousYearGhost = element("span", "month-hud-year-ghost");
      const previousYear = element("button", "month-hud-year-step", "‹");
      previousYear.type = "button";
      previousYear.setAttribute("aria-label", "Previous year");
      const yearValue = element("button", "month-hud-year-value");
      yearValue.type = "button";
      yearValue.setAttribute("aria-label", "Edit year");
      const yearInput = element("input", "month-hud-year-input");
      yearInput.type = "number";
      yearInput.inputMode = "numeric";
      yearInput.min = "1900";
      yearInput.max = "9999";
      yearInput.hidden = true;
      yearInput.setAttribute("aria-label", "Year");
      const nextYear = element("button", "month-hud-year-step", "›");
      nextYear.type = "button";
      nextYear.setAttribute("aria-label", "Next year");
      const nextYearGhost = element("span", "month-hud-year-ghost");
      yearControl.append(previousYearGhost, previousYear, yearValue, nextYear, nextYearGhost);
      let layoutFrame = 0;
      let timelineOffset = 0;
      let stagePanX = 0;
      let stagePanY = 0;
      let stageZoom = 1;
      let dragState = null;
      let suppressClickUntil = 0;
      const MIN_MONTH_HUD_YEAR = 1900;
      const MAX_MONTH_HUD_YEAR = 9999;
      const MIN_MONTH_HUD_ZOOM = 0.45;
      const MAX_MONTH_HUD_ZOOM = 2.8;
      const MONTH_HUD_ZOOM_FACTOR = 1.1;

      const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

      function scheduleMonthHudLayout() {{
        if (layoutFrame) window.cancelAnimationFrame(layoutFrame);
        layoutFrame = window.requestAnimationFrame(() => {{
          layoutFrame = 0;
          layoutMonthHud();
        }});
      }}

      function selectedMonthKey() {{
        return root.dataset.selectedMonth || "";
      }}

      function updateYearControl() {{
        previousYearGhost.textContent = String(displayYear - 1);
        yearValue.textContent = String(displayYear);
        yearInput.value = String(displayYear);
        nextYearGhost.textContent = String(displayYear + 1);
        yearControl.dataset.year = String(displayYear);
      }}

      function clampMonthHudYear(value) {{
        const year = Number.parseInt(String(value || ""), 10);
        if (!Number.isFinite(year)) return displayYear;
        return Math.max(MIN_MONTH_HUD_YEAR, Math.min(MAX_MONTH_HUD_YEAR, year));
      }}

      function closeYearEdit() {{
        yearInput.hidden = true;
        yearValue.hidden = false;
        updateYearControl();
      }}

      function commitYearEdit() {{
        if (yearInput.hidden) return;
        const nextDisplayYear = clampMonthHudYear(yearInput.value);
        closeYearEdit();
        setDisplayYear(nextDisplayYear);
      }}

      function cancelYearEdit() {{
        if (yearInput.hidden) return;
        closeYearEdit();
        yearValue.focus();
      }}

      function startYearEdit() {{
        if (root.classList.contains("is-editing-card")) return;
        yearValue.hidden = true;
        yearInput.hidden = false;
        yearInput.value = String(displayYear);
        yearInput.focus();
        yearInput.select();
      }}

      function renderMonthRail() {{
        rail.replaceChildren();
        for (const [index, month] of months.entries()) {{
          const button = element("button", "month-hud-node");
          button.type = "button";
          button.dataset.month = month.key;
          button.dataset.monthIndex = String(index);
          button.setAttribute("aria-pressed", "false");
          syncMonthButton(button, month);
          button.addEventListener("click", () => {{
            if (root.classList.contains("is-editing-card")) return;
            if (Date.now() < suppressClickUntil) return;
            if (root.classList.contains("has-selection") && !button.classList.contains("selected")) {{
              clearMonthSelection();
              return;
            }}
            selectMonth(month.key);
          }});
          rail.append(button);
        }}
      }}

      function setDisplayYear(value) {{
        const nextDisplayYear = clampMonthHudYear(value);
        if (nextDisplayYear === displayYear) {{
          updateYearControl();
          return;
        }}
        displayYear = nextDisplayYear;
        months = monthSequence(displayYear);
        timelineOffset = 0;
        clearMonthSelection();
        renderMonthRail();
        updateYearControl();
        updateMonthHudSummary();
        root.classList.add("is-changing-year");
        window.setTimeout(() => root.classList.remove("is-changing-year"), 280);
        scheduleMonthHudLayout();
      }}

      function updateStageTransform() {{
        stage.style.setProperty("--stage-pan-x", `${{Math.round(stagePanX)}}px`);
        stage.style.setProperty("--stage-pan-y", `${{Math.round(stagePanY)}}px`);
        stage.style.setProperty("--stage-zoom", String(stageZoom));
      }}

      function clampMonthHudZoom(value) {{
        const zoom = Number(value);
        if (!Number.isFinite(zoom)) return 1;
        return Math.round(clamp(zoom, MIN_MONTH_HUD_ZOOM, MAX_MONTH_HUD_ZOOM) * 1000) / 1000;
      }}

      function updateMonthHudZoom(value, clientX = null, clientY = null) {{
        const nextZoom = clampMonthHudZoom(value);
        if (nextZoom === stageZoom) return;
        if (Number.isFinite(clientX) && Number.isFinite(clientY)) {{
          const rect = stage.getBoundingClientRect();
          const pointerX = clientX - rect.left;
          const pointerY = clientY - rect.top;
          const originX = rect.width / 2;
          const originY = rect.height / 2;
          const previousZoom = stageZoom;
          const worldX = (
            pointerX - stagePanX - (1 - previousZoom) * originX
          ) / previousZoom;
          const worldY = (
            pointerY - stagePanY - (1 - previousZoom) * originY
          ) / previousZoom;
          stagePanX = pointerX - worldX * nextZoom - (1 - nextZoom) * originX;
          stagePanY = pointerY - worldY * nextZoom - (1 - nextZoom) * originY;
        }}
        stageZoom = nextZoom;
        updateStageTransform();
      }}

      function setMonthNodePosition(button, x, y, scale, opacity) {{
        button.style.setProperty("--month-x", `${{Math.round(x)}}px`);
        button.style.setProperty("--month-y", `${{Math.round(y)}}px`);
        button.style.setProperty("--month-scale", String(scale));
        button.style.setProperty("--month-opacity", String(opacity));
      }}

      function timelineSpacing(width) {{
        return clamp(width * (width < 760 ? .31 : .13), width < 760 ? 98 : 128, width < 760 ? 138 : 178);
      }}

      function layoutMonthNodes(width, height) {{
        const buttons = Array.from(rail.querySelectorAll(".month-hud-node"));
        if (!buttons.length) return;
        const selectedKey = selectedMonthKey();
        const selectedIndex = selectedKey
          ? Math.max(0, months.findIndex((month) => month.key === selectedKey))
          : (months.length - 1) / 2;
        const spacing = timelineSpacing(width);
        for (const button of buttons) {{
          const monthIndex = Number(button.dataset.monthIndex || "0");
          const hasEvents = button.classList.contains("has-events");
          if (selectedKey && button.dataset.month === selectedKey) {{
            setMonthNodePosition(button, 0, 0, 1, 1);
            continue;
          }}
          const x = (monthIndex - selectedIndex) * spacing + timelineOffset;
          const scale = selectedKey ? (width < 760 ? .48 : .56) : (width < 760 ? .74 : .9);
          const opacity = selectedKey
            ? (hasEvents ? .42 : .28)
            : (hasEvents ? .92 : .68);
          setMonthNodePosition(button, x, 0, scale, opacity);
        }}
      }}

      function branchCardWidth(width) {{
        return Math.round(clamp(width * .24, 236, 340));
      }}

      function setCircuitSegment(segment, startX, startY, endX, endY) {{
        segment.style.setProperty("--circuit-left", `${{Math.round(startX)}}px`);
        segment.style.setProperty("--circuit-top", `${{Math.round(startY)}}px`);
        segment.style.setProperty("--circuit-length", `${{Math.round(Math.hypot(endX - startX, endY - startY))}}px`);
        segment.style.setProperty("--circuit-angle", `${{Math.atan2(endY - startY, endX - startX)}}rad`);
      }}

      function setBranchPosition(branch, centerX, centerY, cardLeft, cardTop, cardWidth, cardHeight, activeRadius, index) {{
        branch.style.setProperty("--branch-card-left", `${{Math.round(cardLeft)}}px`);
        branch.style.setProperty("--branch-card-top", `${{Math.round(cardTop)}}px`);
        branch.style.setProperty("--branch-card-width", `${{cardWidth}}px`);
        const circuit = branch.querySelector(".month-hud-circuit");
        const first = circuit?.querySelector(".is-primary");
        const second = circuit?.querySelector(".is-secondary");
        if (!first || !second) return;
        const aboveTimeline = cardTop < centerY;
        const horizontalDirection = cardLeft === centerX
          ? (index % 2 === 0 ? 1 : -1)
          : (cardLeft < centerX ? -1 : 1);
        const verticalDirection = aboveTimeline ? -1 : 1;
        const startX = centerX + horizontalDirection * activeRadius * .34;
        const startY = centerY + verticalDirection * activeRadius * .58;
        const targetX = cardLeft;
        const targetY = cardTop - verticalDirection * (cardHeight / 2);
        const tailLength = index % 2 === 0 ? 44 : 62;
        const elbowX = targetX;
        const elbowY = targetY - verticalDirection * tailLength;
        setCircuitSegment(first, startX, startY, elbowX, elbowY);
        setCircuitSegment(second, elbowX, elbowY, targetX, targetY);
      }}

      function sortMonthEvents(key) {{
        const events = grouped.get(key) || [];
        return [...events].sort((left, right) => {{
          const leftAttention = itemNeedsAttention(left) ? 0 : 1;
          const rightAttention = itemNeedsAttention(right) ? 0 : 1;
          if (leftAttention !== rightAttention) return leftAttention - rightAttention;
          const leftDate = itemDate(left);
          const rightDate = itemDate(right);
          const leftTime = leftDate ? leftDate.getTime() : Number.POSITIVE_INFINITY;
          const rightTime = rightDate ? rightDate.getTime() : Number.POSITIVE_INFINITY;
          if (leftTime !== rightTime) return leftTime - rightTime;
          return String(left.title || "").localeCompare(String(right.title || ""));
        }});
      }}

      function layoutMonthBranches(width, height) {{
        if (!selectedMonthKey()) {{
          stage.style.setProperty("--month-hud-dynamic-height", "0px");
          return;
        }}
        const branches = Array.from(branchesRoot.querySelectorAll(".month-hud-branch"));
        const selected = rail.querySelector(".month-hud-node.selected");
        const activeRadius = selected ? selected.offsetWidth / 2 : Math.min(width, height) * .16;
        const centerX = width / 2;
        const centerY = height / 2;
        const empty = branchesRoot.querySelector(".month-hud-empty");
        const compact = width < 760;
        if (empty) {{
          const top = centerY + activeRadius + (compact ? 100 : 116);
          stage.style.setProperty("--month-hud-dynamic-height", "0px");
          empty.style.setProperty("--branch-card-left", `${{Math.round(centerX)}}px`);
          empty.style.setProperty("--branch-card-top", `${{Math.round(top)}}px`);
          return;
        }}
        if (!branches.length) {{
          stage.style.setProperty("--month-hud-dynamic-height", "0px");
          return;
        }}

        const cardWidth = branchCardWidth(width);
        const gap = compact ? 18 : 24;
        const margin = compact ? 18 : 34;
        const availableWidth = Math.max(cardWidth, width - margin * 2);
        const columns = compact
          ? 1
          : Math.max(1, Math.floor((availableWidth + gap) / (cardWidth + gap)));
        const cardHeights = branches.map((branch) => {{
          const card = branch.querySelector(".agenda-item");
          return card ? card.offsetHeight || 136 : 136;
        }});
        const rowHeight = Math.max(compact ? 160 : 176, Math.max(...cardHeights) + gap);
        const slotCount = columns * 2;
        const rows = Math.ceil(branches.length / slotCount);
        const laneGap = branches.length <= 2
          ? (compact ? 22 : 30)
          : (rows <= 1 ? (compact ? 34 : 42) : (compact ? 56 : 72));
        stage.style.setProperty("--month-hud-dynamic-height", "0px");
        for (const [index, branch] of branches.entries()) {{
          const cardHeight = cardHeights[index] || 136;
          const pairStart = Math.floor(index / slotCount) * slotCount;
          const pairRemaining = Math.min(slotCount, branches.length - pairStart);
          const aboveCount = Math.min(columns, pairRemaining);
          const belowCount = Math.max(0, pairRemaining - aboveCount);
          const slot = index % slotCount;
          const row = Math.floor(index / slotCount);
          const aboveTimeline = slot < aboveCount;
          const laneIndex = aboveTimeline ? slot : slot - aboveCount;
          const laneCount = aboveTimeline ? aboveCount : belowCount;
          const laneWidth = laneCount * cardWidth + (laneCount - 1) * gap;
          const cardLeft = centerX - laneWidth / 2 + cardWidth / 2 + laneIndex * (cardWidth + gap);
          const cardOffset = activeRadius + laneGap + cardHeight / 2 + row * rowHeight;
          const cardTop = centerY + (aboveTimeline ? -cardOffset : cardOffset);
          setBranchPosition(branch, centerX, centerY, cardLeft, cardTop, cardWidth, cardHeight, activeRadius, index);
        }}
      }}

      function layoutMonthHud() {{
        const width = stage.clientWidth || stage.getBoundingClientRect().width || 1;
        const height = stage.clientHeight || stage.getBoundingClientRect().height || 1;
        layoutMonthNodes(width, height);
        layoutMonthBranches(width, height);
      }}

      function renderMonthBranches(key) {{
        const month = months.find((entry) => entry.key === key) || months[0];
        const events = month ? sortMonthEvents(month.key) : [];
        const warnings = events.filter(itemNeedsAttention).length;
        const itemLabel = events.length === 1 ? "1 item" : `${{events.length}} items`;
        stage.setAttribute(
          "aria-label",
          month
            ? `${{month.label}}: ${{itemLabel}}${{warnings ? `, ${{warnings}} need review` : ""}}`
            : "Month HUD agenda",
        );
        branchesRoot.replaceChildren();
        if (!events.length) {{
          branchesRoot.append(element("div", "month-hud-empty", "No dated agenda items in this month."));
        }} else {{
          for (const [index, item] of events.entries()) {{
            const branch = element("div", "month-hud-branch");
            const circuit = element("span", "month-hud-circuit");
            circuit.append(
              element("span", "month-hud-circuit-segment is-primary"),
              element("span", "month-hud-circuit-segment is-secondary"),
            );
            branch.style.setProperty("--agenda-index", String(index));
            const card = renderItem(item, index, {{ hideActions: true }});
            card.classList.add("month-hud-editable-card");
            card.tabIndex = 0;
            card.setAttribute("role", "button");
            card.setAttribute("aria-label", `Edit ${{item.title || "agenda item"}}`);
            const openCardEditor = () => {{
              openMonthHudCardEditor(root, stage, item, {{
                onApprove: async (draft) => {{
                  const result = await submitMonthHudEditor(item, "approve", draft);
                  if (result && result.item) replaceAgendaInlineItem(item, result.item);
                  else applyAgendaInlineDraft(item, draft);
                  rebuildMonthGroups();
                  syncMonthButtons();
                  updateMonthHudSummary();
                  renderMonthBranches(selectedMonthKey() || key);
                }},
                onDiscard: async () => {{
                  await submitAgendaAction(item, {{ id: "discard" }});
                  removeAgendaInlineItem(item);
                  rebuildMonthGroups();
                  syncMonthButtons();
                  updateMonthHudSummary();
                  renderMonthBranches(selectedMonthKey() || key);
                }},
              }});
            }};
            card.addEventListener("click", (event) => {{
              if (event.target.closest("button,input,textarea,select,a")) return;
              openCardEditor();
            }});
            card.addEventListener("keydown", (event) => {{
              if (event.target.closest("button,input,textarea,select,a")) return;
              if (event.key !== "Enter" && event.key !== " ") return;
              event.preventDefault();
              openCardEditor();
            }});
            branch.append(circuit, card);
            branchesRoot.append(branch);
          }}
        }}
        scheduleMonthHudLayout();
      }}

      function selectMonth(key) {{
        if (!key) return;
        root.dataset.selectedMonth = key;
        root.classList.add("has-selection");
        timelineOffset = 0;
        for (const button of rail.querySelectorAll(".month-hud-node")) {{
          const selected = button.dataset.month === key;
          button.classList.toggle("selected", selected);
          button.setAttribute("aria-pressed", selected ? "true" : "false");
        }}
        renderMonthBranches(key);
      }}

      function clearMonthSelection() {{
        delete root.dataset.selectedMonth;
        root.classList.remove("has-selection");
        for (const button of rail.querySelectorAll(".month-hud-node")) {{
          button.classList.remove("selected");
          button.setAttribute("aria-pressed", "false");
        }}
        branchesRoot.replaceChildren();
        stage.setAttribute("aria-label", "Month timeline");
        scheduleMonthHudLayout();
      }}

      function syncMonthButton(button, month) {{
        const events = grouped.get(month.key) || [];
        const hasWarnings = events.some(itemNeedsAttention);
        button.classList.toggle("has-events", events.length > 0);
        button.classList.toggle("has-warning", hasWarnings);
        const itemLabel = events.length === 1 ? "1 item" : `${{events.length}} items`;
        button.setAttribute("aria-label", `${{month.label}}: ${{itemLabel}}`);
        button.replaceChildren();
        const ring = element("span", "month-hud-ring");
        ring.append(element("span", "month-hud-core", String(events.length)));
        for (let index = 0; index < Math.min(events.length, 10); index += 1) {{
          const pip = element("span", "month-hud-pip");
          pip.style.setProperty("--pip-index", String(index));
          ring.append(pip);
        }}
        button.append(
          ring,
          element("span", "month-hud-month", month.short),
          element("span", "month-hud-count", itemLabel),
        );
      }}

      function syncMonthButtons() {{
        for (const button of rail.querySelectorAll(".month-hud-node")) {{
          const month = months.find((entry) => entry.key === button.dataset.month);
          if (month) syncMonthButton(button, month);
        }}
      }}

      yearControl.addEventListener("click", (event) => event.stopPropagation());
      yearControl.addEventListener("pointerdown", (event) => event.stopPropagation());
      previousYear.addEventListener("click", () => setDisplayYear(displayYear - 1));
      nextYear.addEventListener("click", () => setDisplayYear(displayYear + 1));
      yearValue.addEventListener("click", startYearEdit);
      yearInput.addEventListener("keydown", (event) => {{
        if (event.key === "Enter") {{
          event.preventDefault();
          commitYearEdit();
        }} else if (event.key === "Escape") {{
          event.preventDefault();
          cancelYearEdit();
        }}
      }});
      yearInput.addEventListener("blur", commitYearEdit);

      updateYearControl();
      renderMonthRail();

      viewport.append(rail);
      canvas.append(viewport, branchesRoot);
      stage.append(canvas, yearControl);
      root.append(stage);
      sectionsRoot.append(root);

      function beginMonthHudDrag(event) {{
        if (root.classList.contains("is-editing-card")) return;
        if (event.button !== 2 && event.button !== 1) return;
        event.preventDefault();
        const mode = event.button === 2 ? "timeline" : "stage";
        dragState = {{
          mode,
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          timelineOffset,
          stagePanX,
          stagePanY,
          stageZoom,
          moved: false,
        }};
        suppressClickUntil = Date.now() + 80;
        root.classList.toggle("is-dragging-timeline", mode === "timeline");
        root.classList.toggle("is-panning-stage", mode === "stage");
        if (stage.setPointerCapture) stage.setPointerCapture(event.pointerId);
      }}

      function updateMonthHudDrag(event) {{
        if (!dragState || event.pointerId !== dragState.pointerId) return;
        event.preventDefault();
        const dx = event.clientX - dragState.startX;
        const dy = event.clientY - dragState.startY;
        dragState.moved = dragState.moved || Math.abs(dx) + Math.abs(dy) > 3;
        if (dragState.mode === "timeline") {{
          timelineOffset = dragState.timelineOffset + dx / dragState.stageZoom;
          scheduleMonthHudLayout();
        }} else {{
          stagePanX = dragState.stagePanX + dx;
          stagePanY = dragState.stagePanY + dy;
          updateStageTransform();
        }}
      }}

      function endMonthHudDrag(event) {{
        if (!dragState || event.pointerId !== dragState.pointerId) return;
        if (dragState.moved) suppressClickUntil = Date.now() + 250;
        if (stage.releasePointerCapture) stage.releasePointerCapture(event.pointerId);
        dragState = null;
        root.classList.remove("is-dragging-timeline", "is-panning-stage");
      }}

      function handleMonthHudWheel(event) {{
        if (root.classList.contains("is-editing-card")) return;
        if (event.target.closest(".month-hud-edit-layer")) return;
        event.preventDefault();
        if (event.deltaY === 0) return;
        const factor = event.deltaY < 0
          ? MONTH_HUD_ZOOM_FACTOR
          : 1 / MONTH_HUD_ZOOM_FACTOR;
        updateMonthHudZoom(stageZoom * factor, event.clientX, event.clientY);
      }}

      stage.addEventListener("wheel", handleMonthHudWheel, {{ passive: false }});
      stage.addEventListener("pointerdown", beginMonthHudDrag);
      stage.addEventListener("pointermove", updateMonthHudDrag);
      stage.addEventListener("pointerup", endMonthHudDrag);
      stage.addEventListener("pointercancel", endMonthHudDrag);
      stage.addEventListener("contextmenu", (event) => event.preventDefault());
      stage.addEventListener("auxclick", (event) => {{
        if (event.button === 1) event.preventDefault();
      }});
      stage.addEventListener("click", (event) => {{
        if (root.classList.contains("is-editing-card")) return;
        if (!root.classList.contains("has-selection")) return;
        if (Date.now() < suppressClickUntil) return;
        if (event.target.closest(".agenda-item, .month-hud-node.selected")) return;
        clearMonthSelection();
      }});
      window.addEventListener("resize", scheduleMonthHudLayout, {{ passive: true }});

      updateStageTransform();
      branchesRoot.replaceChildren();
      stage.setAttribute("aria-label", "Month timeline");
      scheduleMonthHudLayout();
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
        for (const [index, item] of section.items.entries()) items.append(renderItem(item, index));
        container.append(heading, items);
        sectionsRoot.append(container);
      }}
    }}

    function renderSelectedAgendaStyle() {{
      if ((AGENDA_DATA.style || "default") === "month-hud") {{
        renderMonthHud();
        return;
      }}
      renderAgenda();
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
        jumpToToday();
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
    if (!restoreStoredFilters()) renderSelectedAgendaStyle();
  </script>
</body>
</html>
""",
        HTTPStatus.OK,
    )
