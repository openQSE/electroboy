"""Creative workspace, binder, corkboard, and agent operations."""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
from http import HTTPStatus
from pathlib import Path
from uuid import uuid4

from electroboy.modules.document_service import (
    _document_starter_markdown,
    _document_target_path,
)
from electroboy.service.commands import electroboy_command
from electroboy.state_store import StateError

_electroboy_command = electroboy_command


def _slugify_work_item(value: str) -> str:
    chars: list[str] = []
    previous_dash = False
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
            previous_dash = False
            continue
        if not previous_dash:
            chars.append("-")
            previous_dash = True
    return "".join(chars).strip("-") or "default"


def _resolve_project_path(path: str) -> Path:
    return Path(path).expanduser().resolve()


CREATIVE_DEFAULT_FOLDERS = (
    "chapters",
    "scratchpad",
    "characters",
    "corkboard",
    "reviews",
    "research",
)

CREATIVE_SCRATCHPAD_PATH = "scratchpad/scratchpad.md"

CREATIVE_IGNORED_NAMES = frozenset({".git", ".electroboy", "__pycache__"})

CREATIVE_CORKBOARD_SUFFIX = ".corkboard.json"

CREATIVE_CORKBOARD_GROUP_DIRECTORY = Path("corkboard") / "groups"

CREATIVE_CORKBOARD_STATE_RELATIVE_PATH = (
    Path(".electroboy") / "creative" / "corkboards.json"
)

CREATIVE_CARD_PALETTE: tuple[dict[str, str], ...] = (
    {"id": "butter", "label": "Butter", "value": "#fff6cf"},
    {"id": "rose", "label": "Rose", "value": "#f9e7dd"},
    {"id": "sky", "label": "Sky", "value": "#e6f0ff"},
    {"id": "mint", "label": "Mint", "value": "#e8f7e6"},
    {"id": "lilac", "label": "Lilac", "value": "#f1e9ff"},
    {"id": "peach", "label": "Peach", "value": "#ffe8cc"},
    {"id": "slate", "label": "Slate", "value": "#e9edf5"},
)

CREATIVE_CARD_PALETTE_IDS = frozenset(entry["id"] for entry in CREATIVE_CARD_PALETTE)

CREATIVE_CARD_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")


def _existing_creative_project_root(path: str) -> Path:
    project_root = _resolve_project_path(path)
    if not project_root.exists():
        raise StateError(f"project directory does not exist: {project_root}")
    if not project_root.is_dir():
        raise StateError(f"project path is not a directory: {project_root}")
    return project_root


def _normalize_creative_relative_path(relative_path: str) -> str:
    raw = relative_path.strip().replace("\\", "/")
    if not raw:
        raise StateError("path is required")
    path = Path(raw)
    if path.is_absolute():
        raise StateError("path must be relative")
    if any(part in {"", ".."} for part in path.parts):
        raise StateError("path cannot escape the project")
    return path.as_posix()


def _creative_path(project_root: Path | str, relative_path: str) -> tuple[str, Path]:
    project_root = Path(project_root).expanduser().resolve()
    normalized_path = _normalize_creative_relative_path(relative_path)
    resolved = (project_root / normalized_path).resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as error:
        raise StateError("path cannot escape the project") from error
    return normalized_path, resolved


def _ensure_creative_workspace(project_root: Path | str) -> None:
    project_root = Path(project_root).expanduser().resolve()
    (project_root / ".electroboy").mkdir(parents=True, exist_ok=True)
    for folder in CREATIVE_DEFAULT_FOLDERS:
        (project_root / folder).mkdir(parents=True, exist_ok=True)
    _ensure_creative_scratchpad(project_root)
    chapters = project_root / "chapters"
    if not any(chapters.glob("*.md")):
        _create_creative_document(project_root, "chapters/chapter-01.md")
    for path in [
        "characters/characters.md",
        "reviews/review-notes.md",
    ]:
        _create_creative_document(project_root, path)
    _create_creative_corkboard(
        project_root,
        f"corkboard/ideas{CREATIVE_CORKBOARD_SUFFIX}",
    )


def _ensure_creative_scratchpad(project_root: Path | str) -> Path:
    _relative, path = _document_target_path(project_root, CREATIVE_SCRATCHPAD_PATH)
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Scratchpad\n\n", encoding="utf-8")
    return path


def _create_creative_folder(project_root: Path | str, relative_path: str) -> str:
    normalized_path, folder_path = _creative_path(project_root, relative_path)
    if folder_path.exists() and not folder_path.is_dir():
        raise StateError("folder path already exists as a file")
    folder_path.mkdir(parents=True, exist_ok=True)
    return normalized_path


def _create_creative_document(project_root: Path | str, relative_path: str) -> str:
    normalized_path, document_path = _document_target_path(project_root, relative_path)
    if document_path.exists() and not document_path.is_file():
        raise StateError("document path already exists as a folder")
    if not document_path.exists() or not document_path.read_text(encoding="utf-8").strip():
        document_path.parent.mkdir(parents=True, exist_ok=True)
        document_path.write_text(
            _document_starter_markdown(normalized_path),
            encoding="utf-8",
        )
    return normalized_path


def _normalize_creative_corkboard_title(value: object, fallback: str) -> str:
    title = str(value or "").strip()
    return (title or fallback.strip() or "Untitled corkboard")[:200]


def _empty_creative_corkboard_document(
    title: str = "Untitled corkboard",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "type": "electroboy.creative.corkboard",
        "title": _normalize_creative_corkboard_title(title, "Untitled corkboard"),
        "cards": [],
    }


def _create_creative_corkboard(
    project_root: Path | str,
    relative_path: str,
    *,
    title: str | None = None,
) -> str:
    normalized_path, corkboard_path = _creative_path(project_root, relative_path)
    if not normalized_path.endswith(CREATIVE_CORKBOARD_SUFFIX):
        raise StateError(f"corkboard path must end with {CREATIVE_CORKBOARD_SUFFIX}")
    if corkboard_path.exists() and not corkboard_path.is_file():
        raise StateError("corkboard path already exists as a folder")
    default_title = corkboard_path.name.removesuffix(CREATIVE_CORKBOARD_SUFFIX)
    if not corkboard_path.exists() or not corkboard_path.read_text(encoding="utf-8").strip():
        corkboard_path.parent.mkdir(parents=True, exist_ok=True)
        corkboard_path.write_text(
            json.dumps(
                _empty_creative_corkboard_document(
                    _normalize_creative_corkboard_title(title, default_title)
                ),
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    elif title:
        data = _load_creative_corkboard_document(corkboard_path)
        if not str(data.get("title") or "").strip():
            data["title"] = _normalize_creative_corkboard_title(title, default_title)
            corkboard_path.write_text(
                json.dumps(data, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    return normalized_path


def _normalize_creative_entry_name(name: str) -> str:
    normalized_name = name.strip()
    if not normalized_name:
        raise StateError("name is required")
    if normalized_name in {".", ".."}:
        raise StateError("name cannot be . or ..")
    if "/" in normalized_name or "\\" in normalized_name:
        raise StateError("name cannot contain path separators")
    return normalized_name


def _rename_creative_entry(
    project_root: Path | str,
    relative_path: str,
    new_name: str,
) -> tuple[str, str]:
    old_relative_path, source = _creative_path(project_root, relative_path)
    project_root = Path(project_root).expanduser().resolve()
    if not source.exists():
        raise StateError(f"path does not exist: {old_relative_path}")
    normalized_name = _normalize_creative_entry_name(new_name)
    destination = (source.parent / normalized_name).resolve()
    try:
        destination.relative_to(project_root)
    except ValueError as error:
        raise StateError("path cannot escape the project") from error
    if destination.exists():
        raise StateError(f"path already exists: {normalized_name}")
    source.rename(destination)
    new_relative_path = destination.relative_to(project_root).as_posix()
    _remap_creative_corkboard_paths(project_root, old_relative_path, new_relative_path)
    return old_relative_path, new_relative_path


def _delete_creative_entry(project_root: Path | str, relative_path: str) -> str:
    normalized_path, path = _creative_path(project_root, relative_path)
    if not path.exists():
        raise StateError(f"path does not exist: {normalized_path}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    _remove_creative_corkboard_paths(project_root, normalized_path)
    return normalized_path


def _creative_tree_payload(project_root: Path | str) -> dict[str, object]:
    project_root = Path(project_root).expanduser().resolve()
    return {
        "root": str(project_root),
        "entries": _creative_tree_entries(project_root, project_root),
    }


def _creative_tree_entries(
    project_root: Path,
    directory: Path,
    *,
    depth: int = 0,
) -> list[dict[str, object]]:
    if depth > 8:
        return []
    entries: list[dict[str, object]] = []
    try:
        children = sorted(
            directory.iterdir(),
            key=lambda path: (not path.is_dir(), path.name.lower()),
        )
    except OSError:
        return []
    for child in children:
        if child.name in CREATIVE_IGNORED_NAMES or child.name.startswith("."):
            continue
        relative_path = child.relative_to(project_root).as_posix()
        if relative_path == CREATIVE_CORKBOARD_GROUP_DIRECTORY.as_posix():
            continue
        if child.is_dir():
            entries.append(
                {
                    "name": child.name,
                    "path": relative_path,
                    "type": "directory",
                    "children": _creative_tree_entries(
                        project_root,
                        child,
                        depth=depth + 1,
                    ),
                }
            )
            continue
        entries.append(
            {
                "name": child.name,
                "path": relative_path,
                "type": "file",
                "markdown": child.suffix.lower() == ".md",
                "corkboard": child.name.endswith(CREATIVE_CORKBOARD_SUFFIX),
            }
        )
    return entries


def creative_corkboard_html(
    project_root: Path | str,
    board_path: str,
    *,
    title: str | None = None,
    context_id: str = "",
) -> tuple[str, HTTPStatus]:
    """Compatibility wrapper for creative file-backed corkboards."""
    payload = _creative_corkboard_payload(
        project_root,
        board_path,
        title=title,
        context_id=context_id,
    )
    return render_corkboard_html(
        payload,
        operation_url="/api/creative/corkboard",
        open_event_type="electroboy-creative-open",
    )


def render_corkboard_html(
    payload: dict[str, object],
    *,
    operation_url: str = "/api/corkboard",
    open_event_type: str = "electroboy-corkboard-open",
) -> tuple[str, HTTPStatus]:
    """Render a provider-neutral corkboard snapshot."""

    data_json = json.dumps(payload).replace("</", "<\\/")
    operation_url_json = json.dumps(operation_url)
    open_event_type_json = json.dumps(open_event_type)
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(str(payload["title"]))}</title>
  <style>
    :root {{
      color-scheme: dark;
      --cork: #a86d38;
      --cork-dark: #5f4128;
      --ink: #263247;
      --muted: #6b7280;
      --pin: #d1495b;
      --insert: #66d9e8;
      --shadow: rgba(15, 20, 32, 0.32);
    }}

    * {{
      box-sizing: border-box;
    }}

    html,
    body {{
      width: 100%;
      min-height: 100%;
      margin: 0;
      background-color: var(--cork);
      background:
        radial-gradient(ellipse at 18% 24%, rgba(89, 50, 22, 0.48) 0 2px, transparent 3px),
        radial-gradient(ellipse at 73% 38%, rgba(68, 39, 18, 0.38) 0 2px, transparent 4px),
        radial-gradient(ellipse at 41% 72%, rgba(219, 157, 88, 0.34) 0 2px, transparent 3px),
        radial-gradient(ellipse at 84% 82%, rgba(92, 52, 22, 0.32) 0 1px, transparent 3px),
        radial-gradient(ellipse at 31% 48%, rgba(236, 183, 112, 0.20) 0 1px, transparent 3px),
        repeating-linear-gradient(27deg, rgba(61, 36, 18, 0.10) 0 1px, transparent 1px 9px),
        repeating-linear-gradient(112deg, rgba(236, 183, 112, 0.08) 0 1px, transparent 1px 11px),
        var(--cork);
      background-size:
        46px 38px,
        53px 47px,
        61px 52px,
        37px 41px,
        29px 31px,
        31px 31px,
        43px 43px,
        auto;
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      overflow: auto;
    }}

    .board-shell {{
      min-width: 100%;
      min-height: 100vh;
      border: 14px solid var(--cork-dark);
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08);
    }}

    body.freeform-canvas {{
      height: 100vh;
      overflow: hidden;
    }}

    body.freeform-canvas .board-shell {{
      height: 100vh;
      overflow: hidden;
    }}

    .board-toolbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      min-height: 62px;
      border-bottom: 1px solid rgba(52, 34, 22, 0.34);
      background: rgba(52, 34, 22, 0.18);
      padding: 10px 18px;
    }}

    .board-eyebrow {{
      color: rgba(255, 248, 228, 0.84);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}

    .board-title {{
      width: min(560px, 70vw);
      margin: 2px 0 0;
      border: 1px solid transparent;
      border-radius: 4px;
      background: transparent;
      color: #fff9e8;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 22px;
      font-weight: 700;
      line-height: 1.15;
      outline: none;
      padding: 2px 5px;
    }}

    .board-title:not([readonly]):hover,
    .board-title:not([readonly]):focus {{
      border-color: rgba(255, 249, 232, 0.42);
      background: rgba(255, 249, 232, 0.10);
    }}

    .toolbar-button {{
      min-height: 32px;
      border: 1px solid rgba(255, 249, 232, 0.42);
      border-radius: 999px;
      background: rgba(255, 249, 232, 0.18);
      color: #fff9e8;
      cursor: pointer;
      font: inherit;
      font-size: 12px;
      font-weight: 800;
      padding: 0 14px;
    }}

    .toolbar-button[hidden] {{
      display: none;
    }}

    .canvas-viewport {{
      min-width: 100%;
      min-height: calc(100vh - 90px);
    }}

    .board {{
      min-width: 100%;
      min-height: calc(100vh - 90px);
      overflow: visible;
    }}

    body.freeform-canvas .canvas-viewport {{
      position: relative;
      width: 100%;
      height: calc(100vh - 90px);
      min-width: 0;
      min-height: 0;
      overflow: hidden;
      cursor: grab;
      touch-action: none;
    }}

    .board.folder {{
      position: relative;
      display: grid;
      grid-template-columns: repeat(auto-fill, var(--card-width, 218px));
      align-content: start;
      justify-content: start;
      gap: var(--card-gap, 24px);
      padding: 26px;
    }}

    .board.freeform {{
      position: absolute;
      inset: 0;
      min-width: 100%;
      min-height: 100%;
      transform-origin: 0 0;
      will-change: transform;
    }}

    body.canvas-panning,
    body.canvas-panning .canvas-viewport {{
      cursor: grabbing;
      user-select: none;
    }}

    .empty-board {{
      width: 240px;
      min-height: 140px;
      border-radius: 4px;
      background: #fff6cf;
      color: #596176;
      box-shadow: 0 18px 36px var(--shadow);
      padding: 22px;
      transform: rotate(-2deg);
    }}

    .board.freeform .empty-board {{
      position: absolute;
      top: 42px;
      left: 42px;
    }}

    .index-card {{
      min-height: var(--card-min-height, 158px);
      border: 1px solid rgba(38, 50, 71, 0.14);
      border-radius: 5px;
      background:
        linear-gradient(var(--paper), var(--paper)),
        repeating-linear-gradient(
          to bottom,
          transparent 0,
          transparent 25px,
          rgba(63, 77, 103, 0.16) 26px
        );
      box-shadow:
        0 18px 34px var(--shadow),
        0 2px 0 rgba(255, 255, 255, 0.55) inset;
      transform: rotate(var(--rotation));
      transform-origin: 50% 22px;
      touch-action: none;
    }}

    .index-card.selected {{
      outline: 3px solid var(--insert);
      outline-offset: 5px;
      box-shadow:
        0 0 0 1px rgba(255, 249, 232, 0.86),
        0 24px 46px rgba(15, 20, 32, 0.34),
        0 2px 0 rgba(255, 255, 255, 0.55) inset;
      z-index: 10;
    }}

    .index-card.group {{
      box-shadow:
        10px 10px 0 rgba(255, 249, 232, 0.38),
        18px 18px 30px rgba(15, 20, 32, 0.28),
        0 2px 0 rgba(255, 255, 255, 0.55) inset;
    }}

    .index-card.group.selected {{
      box-shadow:
        8px 8px 0 rgba(255, 249, 232, 0.38),
        0 0 0 1px rgba(255, 249, 232, 0.86),
        0 24px 46px rgba(15, 20, 32, 0.34),
        0 2px 0 rgba(255, 255, 255, 0.55) inset;
    }}

    .board.folder .index-card {{
      position: relative;
      width: auto;
    }}

    .board.folder .index-card.dragging {{
      opacity: 0.42;
    }}

    .insertion-marker {{
      position: absolute;
      width: 5px;
      min-height: 64px;
      border-radius: 999px;
      background: var(--insert);
      box-shadow:
        0 0 0 3px rgba(15, 20, 32, 0.22),
        0 0 20px rgba(102, 217, 232, 0.62);
      pointer-events: none;
      transform: translateX(-50%);
      transition:
        left 90ms ease,
        top 90ms ease,
        height 90ms ease;
      z-index: 1001;
    }}

    .insertion-marker[hidden] {{
      display: none;
    }}

    .board.freeform .index-card {{
      position: absolute;
      width: var(--card-width, 218px);
    }}

    .index-card.dragging {{
      cursor: grabbing;
      box-shadow:
        0 28px 54px rgba(15, 20, 32, 0.44),
        0 2px 0 rgba(255, 255, 255, 0.55) inset;
      z-index: 1000;
    }}

    .index-card::before {{
      content: "";
      position: absolute;
      top: -8px;
      left: 50%;
      width: 16px;
      height: 16px;
      border-radius: 999px;
      background:
        radial-gradient(circle at 35% 32%, rgba(255, 255, 255, 0.75), transparent 0 22%),
        var(--pin);
      box-shadow: 0 4px 8px rgba(48, 28, 22, 0.35);
      transform: translateX(-50%);
    }}

    .index-card::after {{
      content: "";
      position: absolute;
      top: 8px;
      left: 16px;
      right: 16px;
      height: 16px;
      border-radius: 2px;
      background: rgba(255, 255, 255, 0.26);
      mix-blend-mode: multiply;
      transform: rotate(-1deg);
      pointer-events: none;
    }}

    .card-head {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: start;
      padding: 18px 14px 8px;
      cursor: grab;
    }}

    .card-title {{
      min-width: 0;
      overflow: hidden;
      color: var(--ink);
      font-family: Georgia, "Times New Roman", serif;
      font-size: 17px;
      font-weight: 700;
      line-height: 1.15;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    .card-title-input {{
      width: 100%;
      border: 0;
      background: transparent;
      color: var(--ink);
      font-family: Georgia, "Times New Roman", serif;
      font-size: 17px;
      font-weight: 700;
      line-height: 1.15;
      outline: none;
      padding: 0;
    }}

    .card-type {{
      margin-top: 3px;
      color: var(--muted);
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}

    .card-open {{
      min-height: 24px;
      border: 1px solid rgba(38, 50, 71, 0.18);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.55);
      color: var(--ink);
      cursor: pointer;
      font: inherit;
      font-size: 11px;
      font-weight: 800;
      padding: 0 10px;
    }}

    .card-group-action {{
      display: grid;
      place-items: center;
      width: 26px;
      height: 26px;
      border: 1px solid rgba(38, 50, 71, 0.18);
      border-radius: 4px;
      background: rgba(255, 255, 255, 0.46);
      color: var(--ink);
      cursor: pointer;
      padding: 0;
    }}

    .card-group-action:hover {{
      background: rgba(255, 255, 255, 0.72);
    }}

    .card-group-action.active {{
      border-color: rgba(42, 87, 148, 0.38);
      background: rgba(216, 230, 255, 0.74);
    }}

    .card-group-icon {{
      width: 17px;
      height: 17px;
      fill: none;
      stroke: currentcolor;
      stroke-linecap: round;
      stroke-linejoin: round;
      stroke-width: 1.8;
    }}

    .card-tools {{
      position: relative;
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    .card-color {{
      display: grid;
      place-items: center;
      width: 26px;
      height: 26px;
      border: 1px solid rgba(38, 50, 71, 0.18);
      border-radius: 4px;
      background: rgba(255, 255, 255, 0.46);
      color: var(--ink);
      cursor: pointer;
      padding: 0;
    }}

    .card-color:hover {{
      background: rgba(255, 255, 255, 0.72);
    }}

    .card-color-icon {{
      width: 14px;
      height: 14px;
      border: 2px solid currentcolor;
      border-radius: 999px 999px 999px 2px;
      background: var(--selected-paper, #fff6cf);
      box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.62) inset;
      transform: rotate(-45deg);
    }}

    .card-palette {{
      position: absolute;
      top: calc(100% + 6px);
      right: 0;
      z-index: 1200;
      display: none;
      grid-template-columns: repeat(4, 24px);
      gap: 6px;
      border: 1px solid rgba(38, 50, 71, 0.18);
      border-radius: 8px;
      background: rgba(255, 249, 232, 0.96);
      box-shadow: 0 16px 32px rgba(15, 20, 32, 0.28);
      padding: 8px;
    }}

    .card-palette.open {{
      display: grid;
    }}

    .card-swatch {{
      width: 24px;
      height: 24px;
      border: 1px solid rgba(38, 50, 71, 0.2);
      border-radius: 999px;
      background: var(--swatch);
      cursor: pointer;
      padding: 0;
    }}

    .card-swatch.selected {{
      box-shadow:
        0 0 0 2px rgba(255, 249, 232, 0.9),
        0 0 0 4px rgba(38, 50, 71, 0.72);
    }}

    .card-delete {{
      display: grid;
      place-items: center;
      width: 26px;
      height: 26px;
      border: 1px solid rgba(38, 50, 71, 0.18);
      border-radius: 4px;
      background: rgba(255, 255, 255, 0.42);
      color: #6f3f45;
      cursor: pointer;
      padding: 0;
    }}

    .card-delete:hover:not(:disabled) {{
      border-color: rgba(140, 48, 58, 0.48);
      background: rgba(255, 238, 234, 0.78);
      color: #9b2634;
    }}

    .card-delete:disabled {{
      cursor: default;
      opacity: 0.45;
    }}

    .card-delete-icon {{
      position: relative;
      width: 11px;
      height: 11px;
      border: 1.5px solid currentcolor;
      border-top: 0;
      border-radius: 0 0 2px 2px;
    }}

    .card-delete-icon::before {{
      position: absolute;
      top: -4px;
      left: -2px;
      width: 13px;
      height: 1.5px;
      background: currentcolor;
      content: "";
    }}

    .card-delete-icon::after {{
      position: absolute;
      top: -7px;
      left: 2px;
      width: 5px;
      height: 3px;
      border: 1.5px solid currentcolor;
      border-bottom: 0;
      border-radius: 2px 2px 0 0;
      content: "";
    }}

    .card-note {{
      display: block;
      width: calc(100% - 24px);
      min-height: var(--card-note-min-height, 82px);
      margin: 0 12px 12px;
      border: 0;
      background:
        repeating-linear-gradient(
          to bottom,
          transparent 0,
          transparent 25px,
          rgba(63, 77, 103, 0.18) 26px
        );
      color: var(--ink);
      font: inherit;
      font-size: 13px;
      line-height: 26px;
      outline: none;
      resize: none;
    }}

    .card-metadata {{
      display: grid;
      grid-template-columns: max-content minmax(0, 1fr);
      gap: 3px 8px;
      margin: -2px 12px 12px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
    }}

    .card-metadata-key {{
      font-weight: 800;
      text-transform: capitalize;
    }}

    .card-metadata-value {{
      min-width: 0;
      margin: 0;
      overflow-wrap: anywhere;
    }}

    .card-size-control {{
      position: fixed;
      right: 12px;
      bottom: 12px;
      z-index: 1100;
      display: grid;
      gap: 6px;
      width: 220px;
      border: 1px solid rgba(255, 249, 232, 0.34);
      border-radius: 8px;
      background: rgba(15, 20, 32, 0.86);
      color: #d8e3f4;
      box-shadow: 0 10px 24px rgba(15, 20, 32, 0.26);
      padding: 8px 10px;
    }}

    .card-size-label {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
    }}

    .card-size-control input {{
      width: 100%;
      accent-color: var(--insert);
    }}

  </style>
</head>
<body>
  <main class="board-shell">
    <header class="board-toolbar">
      <div>
        <div id="boardEyebrow" class="board-eyebrow"></div>
        <input id="boardTitle" class="board-title" type="text"
               value="{html.escape(str(payload["title"]), quote=True)}"
               maxlength="200" aria-label="Corkboard title"
               title="Edit corkboard title"
               {"readonly" if payload["board_type"] != "freeform" else ""}>
      </div>
      <button id="addCard" class="toolbar-button" type="button" hidden>Add card</button>
    </header>
    <section id="canvasViewport" class="canvas-viewport">
      <section id="board" class="board" aria-label="{html.escape(str(payload["title"]))}"></section>
    </section>
  </main>
  <label class="card-size-control">
    <span class="card-size-label">
      <span>Card size</span>
      <output id="cardSizeValue">100%</output>
    </span>
    <input
      id="cardSizeSlider"
      type="range"
      min="70"
      max="300"
      step="5"
      value="100"
      aria-label="Resize corkboard cards"
    >
  </label>
  <script>
    const CORKBOARD_DATA = {data_json};
    const CORKBOARD_OPERATION_URL = {operation_url_json};
    const CORKBOARD_OPEN_EVENT_TYPE = {open_event_type_json};
    const canvasViewport = document.getElementById("canvasViewport");
    const board = document.getElementById("board");
    const boardEyebrow = document.getElementById("boardEyebrow");
    const boardTitle = document.getElementById("boardTitle");
    const addCard = document.getElementById("addCard");
    const cardSizeSlider = document.getElementById("cardSizeSlider");
    const cardSizeValue = document.getElementById("cardSizeValue");
    const boardType = CORKBOARD_DATA.board_type || "folder";
    const cards = Array.isArray(CORKBOARD_DATA.cards) ? CORKBOARD_DATA.cards : [];
    const BOARD_CAPABILITIES = new Set(
      Array.isArray(CORKBOARD_DATA.capabilities) ? CORKBOARD_DATA.capabilities : [],
    );
    const HAS_CAPABILITY_POLICY = BOARD_CAPABILITIES.size > 0;
    const CARD_PALETTE = Array.isArray(CORKBOARD_DATA.palette)
      ? CORKBOARD_DATA.palette
      : [];
    const saveTimers = new Map();
    const cardSaveRequests = new Map();
    let boardTitleSaveTimer = null;
    const corkboardChannel = typeof window.BroadcastChannel === "function"
      ? new window.BroadcastChannel(
          `electroboy.corkboard.${{CORKBOARD_DATA.context_id || "local"}}`,
        )
      : null;
    const CORKBOARD_STORAGE_NAMESPACE = CORKBOARD_DATA.provider
      ? `electroboy.corkboard.${{CORKBOARD_DATA.provider}}`
      : "electroboy.creative.corkboard";
    const CARD_SCALE_STORAGE_PREFIX = `${{CORKBOARD_STORAGE_NAMESPACE}}.cardScale.`;
    const CANVAS_PAN_STORAGE_PREFIX = `${{CORKBOARD_STORAGE_NAMESPACE}}.canvasPan.`;
    const MIN_CARD_SCALE = 70;
    const MAX_CARD_SCALE = 300;
    let dragState = null;
    let canvasPanState = null;
    let draggedPath = "";
    let folderInsertionMarker = null;
    let folderDropTarget = "";
    let folderDropPlacement = "before";
    let cardScale = storedCardScale();
    let canvasPan = storedCanvasPan();
    let selectedCardKey = "";

    document.body.classList.toggle("freeform-canvas", boardType === "freeform");
    boardTitle.readOnly = boardType !== "freeform" || !supports("rename-board");

    function supports(capability) {{
      return !HAS_CAPABILITY_POLICY || BOARD_CAPABILITIES.has(capability);
    }}

    function contextUrl(path) {{
      const contextId = CORKBOARD_DATA.context_id || "";
      if (!contextId) {{
        return path;
      }}
      const separator = path.includes("?") ? "&" : "?";
      return `${{path}}${{separator}}context_id=${{encodeURIComponent(contextId)}}`;
    }}

    function boardStoragePath() {{
      if (CORKBOARD_DATA.board_id) {{
        return CORKBOARD_DATA.board_id;
      }}
      if (CORKBOARD_DATA.corkboard && CORKBOARD_DATA.corkboard.path) {{
        return CORKBOARD_DATA.corkboard.path;
      }}
      if (CORKBOARD_DATA.folder && CORKBOARD_DATA.folder.path) {{
        return CORKBOARD_DATA.folder.path;
      }}
      return "default";
    }}

    function cardScaleStorageKey() {{
      return `${{CARD_SCALE_STORAGE_PREFIX}}${{boardType}}:${{boardStoragePath()}}`;
    }}

    function canvasPanStorageKey() {{
      return `${{CANVAS_PAN_STORAGE_PREFIX}}${{boardStoragePath()}}`;
    }}

    async function saveBoardTitle() {{
      window.clearTimeout(boardTitleSaveTimer);
      boardTitleSaveTimer = null;
      if (
        boardType !== "freeform" ||
        !supports("rename-board") ||
        !CORKBOARD_DATA.context_id
      ) {{
        return;
      }}
      const title = boardTitle.value.trim();
      if (!title) {{
        boardTitle.value = CORKBOARD_DATA.title || "Untitled corkboard";
        return;
      }}
      const response = await fetch(contextUrl(CORKBOARD_OPERATION_URL), {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          provider: CORKBOARD_DATA.provider || "",
          board_id: boardStoragePath(),
          action: "rename-board",
          title,
        }}),
      }}).catch(() => null);
      if (!response || !response.ok) {{
        boardTitle.value = CORKBOARD_DATA.title || "Untitled corkboard";
        return;
      }}
      const payload = await response.json().catch(() => ({{}}));
      CORKBOARD_DATA.title = payload.title || title;
      boardTitle.value = CORKBOARD_DATA.title;
      document.title = CORKBOARD_DATA.title;
      board.setAttribute("aria-label", CORKBOARD_DATA.title);
      if (corkboardChannel) {{
        corkboardChannel.postMessage({{
          type: "corkboard-title-changed",
          board_path: CORKBOARD_DATA.corkboard.path,
          title: CORKBOARD_DATA.title,
        }});
      }}
    }}

    function queueBoardTitleSave() {{
      window.clearTimeout(boardTitleSaveTimer);
      boardTitleSaveTimer = window.setTimeout(saveBoardTitle, 450);
    }}

    function storedCanvasPan() {{
      if (boardType !== "freeform") {{
        return {{ x: 0, y: 0 }};
      }}
      try {{
        const stored = JSON.parse(window.localStorage.getItem(canvasPanStorageKey()));
        const x = Number(stored && stored.x);
        const y = Number(stored && stored.y);
        if (Number.isFinite(x) && Number.isFinite(y)) {{
          return {{ x, y }};
        }}
      }} catch (error) {{
        return {{ x: 0, y: 0 }};
      }}
      return {{ x: 0, y: 0 }};
    }}

    function saveCanvasPan() {{
      try {{
        window.localStorage.setItem(canvasPanStorageKey(), JSON.stringify(canvasPan));
      }} catch (error) {{
        return;
      }}
    }}

    function applyCanvasPan() {{
      if (boardType !== "freeform") {{
        board.style.transform = "";
        return;
      }}
      board.style.transform = `translate(${{canvasPan.x}}px, ${{canvasPan.y}}px)`;
    }}

    function clampCardScale(value) {{
      const scale = Number(value);
      if (!Number.isFinite(scale)) {{
        return 100;
      }}
      return Math.max(MIN_CARD_SCALE, Math.min(MAX_CARD_SCALE, Math.round(scale)));
    }}

    function storedCardScale() {{
      try {{
        const stored = Number(window.localStorage.getItem(cardScaleStorageKey()));
        if (Number.isFinite(stored)) {{
          return clampCardScale(stored);
        }}
      }} catch (error) {{
        return 100;
      }}
      return 100;
    }}

    function saveCardScale() {{
      try {{
        window.localStorage.setItem(cardScaleStorageKey(), String(cardScale));
      }} catch (error) {{
        return;
      }}
    }}

    function scaledCardValue(value) {{
      return Math.round(value * cardScale / 100);
    }}

    function applyCardScale() {{
      const root = document.documentElement;
      root.style.setProperty("--card-width", `${{scaledCardValue(218)}}px`);
      root.style.setProperty("--card-min-height", `${{scaledCardValue(158)}}px`);
      root.style.setProperty("--card-note-min-height", `${{scaledCardValue(82)}}px`);
      root.style.setProperty("--card-gap", `${{Math.max(14, scaledCardValue(24))}}px`);
      cardSizeSlider.value = String(cardScale);
      cardSizeValue.value = `${{cardScale}}%`;
      cardSizeValue.textContent = `${{cardScale}}%`;
      sizeBoard();
    }}

    function updateCardScale(value) {{
      cardScale = clampCardScale(value);
      saveCardScale();
      applyCardScale();
    }}

    function cardKey(card) {{
      return String(card.id || card.path || "");
    }}

    function cardKind(card) {{
      return card && card.card_type === "group" ? "group" : "card";
    }}

    function cardCssType(card) {{
      if (boardType === "freeform") {{
        return cardKind(card);
      }}
      return card.type || "file";
    }}

    function selectCard(card, cardElement) {{
      selectedCardKey = cardKey(card);
      for (const element of board.querySelectorAll(".index-card.selected")) {{
        element.classList.remove("selected");
        element.setAttribute("aria-selected", "false");
      }}
      cardElement.classList.add("selected");
      cardElement.setAttribute("aria-selected", "true");
    }}

    function paletteEntryFor(color) {{
      const raw = String(color || "").trim();
      const lower = raw.toLowerCase();
      return CARD_PALETTE.find((entry) =>
        entry.id === raw || String(entry.value || "").toLowerCase() === lower,
      );
    }}

    function cardColorName(card) {{
      const entry = paletteEntryFor(card.color);
      if (entry) {{
        return entry.id;
      }}
      const raw = String(card.color || "").trim();
      return /^#[0-9a-f]{{6}}$/i.test(raw) ? raw.toLowerCase() : "butter";
    }}

    function cardColor(card) {{
      const entry = paletteEntryFor(card.color);
      if (entry) {{
        return entry.value;
      }}
      const raw = String(card.color || "").trim();
      return /^#[0-9a-f]{{6}}$/i.test(raw) ? raw.toLowerCase() : "#fff6cf";
    }}

    function closePalettes(except = null) {{
      for (const palette of board.querySelectorAll(".card-palette.open")) {{
        if (palette !== except) {{
          palette.classList.remove("open");
        }}
      }}
    }}

    function buildColorButton(card, cardElement) {{
      const wrapper = document.createElement("div");
      wrapper.className = "card-color-wrap";
      const button = document.createElement("button");
      button.className = "card-color";
      button.type = "button";
      button.title = "Change card color";
      button.setAttribute("aria-label", "Change card color");
      const icon = document.createElement("span");
      icon.className = "card-color-icon";
      icon.setAttribute("aria-hidden", "true");
      button.append(icon);
      const palette = document.createElement("div");
      palette.className = "card-palette";
      palette.addEventListener("click", (event) => event.stopPropagation());
      for (const entry of CARD_PALETTE) {{
        const swatch = document.createElement("button");
        swatch.className = "card-swatch";
        swatch.type = "button";
        swatch.title = entry.label || entry.id;
        swatch.setAttribute("aria-label", `Set card color to ${{entry.label || entry.id}}`);
        swatch.style.setProperty("--swatch", entry.value || "#fff6cf");
        swatch.classList.toggle("selected", cardColorName(card) === entry.id);
        swatch.addEventListener("click", (event) => {{
          event.stopPropagation();
          card.color = entry.id;
          cardElement.style.setProperty("--paper", cardColor(card));
          icon.style.setProperty("--selected-paper", cardColor(card));
          for (const item of palette.querySelectorAll(".card-swatch.selected")) {{
            item.classList.remove("selected");
          }}
          swatch.classList.add("selected");
          palette.classList.remove("open");
          queueSave(card);
        }});
        palette.append(swatch);
      }}
      button.addEventListener("click", (event) => {{
        event.stopPropagation();
        const isOpen = palette.classList.contains("open");
        closePalettes(palette);
        palette.classList.toggle("open", !isOpen);
      }});
      button.addEventListener("pointerdown", (event) => event.stopPropagation());
      wrapper.addEventListener("pointerdown", (event) => event.stopPropagation());
      icon.style.setProperty("--selected-paper", cardColor(card));
      wrapper.append(button, palette);
      return wrapper;
    }}

    function applyCardPosition(cardElement, card) {{
      cardElement.style.left = `${{Number(card.x) || 0}}px`;
      cardElement.style.top = `${{Number(card.y) || 0}}px`;
      cardElement.style.setProperty("--rotation", `${{Number(card.rotation) || 0}}deg`);
      cardElement.style.setProperty("--paper", cardColor(card));
    }}

    function sizeBoard() {{
      applyCanvasPan();
    }}

    function startCanvasPan(event) {{
      if (boardType !== "freeform" || event.button !== 1) {{
        return;
      }}
      event.preventDefault();
      canvasPanState = {{
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        originalX: canvasPan.x,
        originalY: canvasPan.y,
      }};
      canvasViewport.setPointerCapture(event.pointerId);
      document.body.classList.add("canvas-panning");
    }}

    function updateCanvasPan(event) {{
      if (!canvasPanState || event.pointerId !== canvasPanState.pointerId) {{
        return;
      }}
      canvasPan = {{
        x: canvasPanState.originalX + event.clientX - canvasPanState.startX,
        y: canvasPanState.originalY + event.clientY - canvasPanState.startY,
      }};
      applyCanvasPan();
    }}

    function finishCanvasPan(event) {{
      if (!canvasPanState || event.pointerId !== canvasPanState.pointerId) {{
        return;
      }}
      const pointerId = canvasPanState.pointerId;
      canvasPanState = null;
      document.body.classList.remove("canvas-panning");
      saveCanvasPan();
      try {{
        canvasViewport.releasePointerCapture(pointerId);
      }} catch (error) {{
        // Pointer capture may already be released by the browser.
      }}
    }}

    function queueSave(card) {{
      const key = cardKey(card);
      window.clearTimeout(saveTimers.get(key));
      saveTimers.set(
        key,
        window.setTimeout(() => {{
          saveTimers.delete(key);
          persistCard(card);
        }}, 350),
      );
    }}

    function persistCard(card) {{
      const key = cardKey(card);
      const request = saveCard(card);
      cardSaveRequests.set(key, request);
      request.finally(() => {{
        if (cardSaveRequests.get(key) === request) {{
          cardSaveRequests.delete(key);
        }}
      }});
      return request;
    }}

    async function saveCard(card) {{
      if (
        !CORKBOARD_DATA.context_id ||
        (!supports("edit-card") && !supports("move-card"))
      ) {{
        return null;
      }}
      const payload = {{
        provider: CORKBOARD_DATA.provider || "",
        board_id: boardStoragePath(),
        board_type: boardType,
        action: "update-card",
        card: {{
          ...card,
          id: cardKey(card),
          title: card.title || card.name || "",
          note: card.note || "",
          x: Number(card.x) || 0,
          y: Number(card.y) || 0,
          rotation: Number(card.rotation) || 0,
          color: cardColorName(card),
          card_type: cardKind(card),
          board_path: card.board_path || "",
        }},
      }};
      const response = await fetch(contextUrl(CORKBOARD_OPERATION_URL), {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(payload),
      }}).catch(() => null);
      if (!response || !response.ok) {{
        return null;
      }}
      return response.json().catch(() => null);
    }}

    async function deleteFreeformCard(card, button) {{
      if (boardType !== "freeform" || !supports("delete-card")) {{
        return;
      }}
      const title = card.title || "Untitled card";
      if (!window.confirm(`Delete "${{title}}"?`)) {{
        return;
      }}
      const key = cardKey(card);
      window.clearTimeout(saveTimers.get(key));
      saveTimers.delete(key);
      button.disabled = true;
      await cardSaveRequests.get(key);
      if (CORKBOARD_DATA.context_id) {{
        const response = await fetch(contextUrl(CORKBOARD_OPERATION_URL), {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            provider: CORKBOARD_DATA.provider || "",
            board_id: boardStoragePath(),
            action: "delete-card",
            card_id: card.id,
          }}),
        }}).catch(() => null);
        if (!response || !response.ok) {{
          const payload = response
            ? await response.json().catch(() => ({{}}))
            : {{}};
          button.disabled = false;
          window.alert(payload.error || "Unable to delete card.");
          return;
        }}
      }}
      const index = cards.findIndex((candidate) => cardKey(candidate) === key);
      if (index >= 0) {{
        cards.splice(index, 1);
      }}
      if (selectedCardKey === key) {{
        selectedCardKey = "";
      }}
      renderCards();
    }}

    async function saveOrder() {{
      if (
        !CORKBOARD_DATA.context_id ||
        boardType !== "folder" ||
        !supports("reorder-card")
      ) {{
        return;
      }}
      await fetch(contextUrl(CORKBOARD_OPERATION_URL), {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          provider: CORKBOARD_DATA.provider || "",
          board_id: boardStoragePath(),
          action: "reorder-cards",
          order: cards.map((card) => cardKey(card)),
        }}),
      }}).catch(() => null);
    }}

    function openCard(card) {{
      const targetWindow =
        window.parent && window.parent !== window ? window.parent : window.opener;
      if (!targetWindow) {{
        return;
      }}
      targetWindow.postMessage(
        {{
          type: CORKBOARD_OPEN_EVENT_TYPE,
          provider: CORKBOARD_DATA.provider || "creative-files",
          board_id: CORKBOARD_DATA.board_id || "",
          target: card.target || null,
          path: card.path,
          entry_type: card.corkboard ? "corkboard" : card.type,
        }},
        window.location.origin,
      );
    }}

    function openGroupCard(card) {{
      const targetWindow =
        window.parent && window.parent !== window ? window.parent : window.opener;
      if (!targetWindow || cardKind(card) !== "group" || !card.board_path) {{
        return;
      }}
      targetWindow.postMessage(
        {{
          type: CORKBOARD_OPEN_EVENT_TYPE,
          provider: CORKBOARD_DATA.provider || "creative-files",
          board_id: CORKBOARD_DATA.board_id || "",
          target: card.target || null,
          path: card.board_path,
          title: card.title || "Untitled card group",
          entry_type: "corkboard",
        }},
        window.location.origin,
      );
    }}

    async function convertCardToGroup(card, cardElement, button) {{
      if (boardType !== "freeform" || !supports("group-card")) {{
        return;
      }}
      if (cardKind(card) === "group") {{
        openGroupCard(card);
        return;
      }}
      const title = card.title || "Untitled card";
      if (!window.confirm(`Convert "${{title}}" to a card group?`)) {{
        return;
      }}
      const key = cardKey(card);
      window.clearTimeout(saveTimers.get(key));
      saveTimers.delete(key);
      button.disabled = true;
      await cardSaveRequests.get(key);
      card.card_type = "group";
      const saved = await persistCard(card);
      if (saved && saved.card) {{
        Object.assign(card, saved.card);
      }}
      button.disabled = false;
      renderCards();
      if (card.board_path) {{
        openGroupCard(card);
      }}
    }}

    function buildGroupButton(card, cardElement) {{
      const button = document.createElement("button");
      const isGroup = cardKind(card) === "group";
      button.className = `card-group-action ${{isGroup ? "active" : ""}}`;
      button.type = "button";
      button.title = isGroup ? "Open card group" : "Convert to card group";
      button.setAttribute(
        "aria-label",
        isGroup ? "Open card group" : "Convert to card group",
      );
      button.addEventListener("pointerdown", (event) => event.stopPropagation());
      button.addEventListener("click", () => convertCardToGroup(card, cardElement, button));
      const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      icon.classList.add("card-group-icon");
      icon.setAttribute("aria-hidden", "true");
      icon.setAttribute("viewBox", "0 0 24 24");
      icon.innerHTML = `
        <path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z"></path>
        <path d="m22 12.5-9.17 4.17a2 2 0 0 1-1.66 0L2 12.5"></path>
        <path d="m22 17.5-9.17 4.17a2 2 0 0 1-1.66 0L2 17.5"></path>
      `;
      button.append(icon);
      return button;
    }}

    function startDrag(event) {{
      if (
        !supports("move-card") ||
        event.button !== 0 ||
        event.target.closest("textarea, button")
      ) {{
        return;
      }}
      const cardElement = event.currentTarget;
      const card = cards.find((candidate) => cardKey(candidate) === cardElement.dataset.key);
      if (!card) {{
        return;
      }}
      dragState = {{
        card,
        cardElement,
        startX: event.clientX,
        startY: event.clientY,
        originalX: Number(card.x) || 0,
        originalY: Number(card.y) || 0,
      }};
      cardElement.classList.add("dragging");
      cardElement.setPointerCapture(event.pointerId);
    }}

    function updateDrag(event) {{
      if (!dragState) {{
        return;
      }}
      dragState.card.x = Math.max(
        -1000000,
        Math.min(1000000, dragState.originalX + event.clientX - dragState.startX),
      );
      dragState.card.y = Math.max(
        -1000000,
        Math.min(1000000, dragState.originalY + event.clientY - dragState.startY),
      );
      applyCardPosition(dragState.cardElement, dragState.card);
      sizeBoard();
    }}

    function finishDrag(event) {{
      if (!dragState) {{
        return;
      }}
      dragState.cardElement.classList.remove("dragging");
      try {{
        dragState.cardElement.releasePointerCapture(event.pointerId);
      }} catch (error) {{
        // Pointer capture may already be released if the window lost focus.
      }}
      queueSave(dragState.card);
      dragState = null;
    }}

    function startFolderDrag(event, card, cardElement) {{
      if (!supports("reorder-card")) {{
        event.preventDefault();
        return;
      }}
      draggedPath = card.path || "";
      cardElement.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", draggedPath);
    }}

    function finishFolderDrag(cardElement) {{
      draggedPath = "";
      clearFolderInsertionMarker();
      cardElement.classList.remove("dragging");
    }}

    function ensureFolderInsertionMarker() {{
      if (folderInsertionMarker && folderInsertionMarker.parentElement === board) {{
        return folderInsertionMarker;
      }}
      folderInsertionMarker = document.createElement("div");
      folderInsertionMarker.className = "insertion-marker";
      folderInsertionMarker.hidden = true;
      board.prepend(folderInsertionMarker);
      return folderInsertionMarker;
    }}

    function clearFolderInsertionMarker() {{
      folderDropTarget = "";
      folderDropPlacement = "before";
      if (folderInsertionMarker) {{
        folderInsertionMarker.hidden = true;
      }}
    }}

    function folderInsertionPlacement(event, cardElement) {{
      const rect = cardElement.getBoundingClientRect();
      return event.clientX < rect.left + rect.width / 2 ? "before" : "after";
    }}

    function showFolderInsertionMarker(event, card, cardElement) {{
      if (!draggedPath || draggedPath === card.path) {{
        clearFolderInsertionMarker();
        return;
      }}
      const placement = folderInsertionPlacement(event, cardElement);
      const marker = ensureFolderInsertionMarker();
      const cardRect = cardElement.getBoundingClientRect();
      const boardRect = board.getBoundingClientRect();
      const x = placement === "before"
        ? cardRect.left - boardRect.left
        : cardRect.right - boardRect.left;
      marker.style.left = `${{Math.max(0, x)}}px`;
      marker.style.top = `${{Math.max(0, cardRect.top - boardRect.top)}}px`;
      marker.style.height = `${{Math.max(64, cardRect.height)}}px`;
      marker.hidden = false;
      folderDropTarget = card.path || "";
      folderDropPlacement = placement;
    }}

    function dropFolderCard(event, targetCard, cardElement) {{
      event.preventDefault();
      const sourcePath = draggedPath || event.dataTransfer.getData("text/plain");
      if (!sourcePath || sourcePath === targetCard.path) {{
        clearFolderInsertionMarker();
        return;
      }}
      const sourceIndex = cards.findIndex((card) => card.path === sourcePath);
      const targetPath = folderDropTarget || targetCard.path;
      const placement = folderDropTarget
        ? folderDropPlacement
        : folderInsertionPlacement(event, cardElement);
      if (sourceIndex < 0 || !targetPath) {{
        clearFolderInsertionMarker();
        return;
      }}
      const [moved] = cards.splice(sourceIndex, 1);
      const targetIndex = cards.findIndex((card) => card.path === targetPath);
      if (targetIndex < 0) {{
        cards.splice(sourceIndex, 0, moved);
        clearFolderInsertionMarker();
        return;
      }}
      const insertIndex = placement === "after" ? targetIndex + 1 : targetIndex;
      cards.splice(insertIndex, 0, moved);
      clearFolderInsertionMarker();
      renderCards();
      saveOrder();
    }}

    function makeFreeformCard() {{
      if (!supports("create-card")) {{
        return;
      }}
      const index = cards.length;
      const card = {{
        id: `card-${{Date.now().toString(36)}}-${{Math.random().toString(36).slice(2, 8)}}`,
        title: "Untitled card",
        note: "",
        x: -canvasPan.x + 36 + (index % 4) * scaledCardValue(236),
        y: -canvasPan.y + 36 + Math.floor(index / 4) * scaledCardValue(206),
        rotation: (index % 5) - 2,
        color: CARD_PALETTE.length
          ? CARD_PALETTE[index % CARD_PALETTE.length].id
          : "#fff6cf",
        card_type: "card",
      }};
      cards.push(card);
      selectedCardKey = card.id;
      renderCards();
      persistCard(card);
    }}

    function buildCardMetadata(card) {{
      const metadata = card && card.metadata;
      if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {{
        return null;
      }}
      const entries = Object.entries(metadata).filter(([, value]) =>
        value !== null && value !== undefined && String(value).trim() !== "",
      );
      if (entries.length === 0) {{
        return null;
      }}
      const container = document.createElement("dl");
      container.className = "card-metadata";
      for (const [key, value] of entries) {{
        const term = document.createElement("dt");
        term.className = "card-metadata-key";
        term.textContent = key.replace(/[_-]+/g, " ");
        const detail = document.createElement("dd");
        detail.className = "card-metadata-value";
        detail.textContent = Array.isArray(value)
          ? value.join(", ")
          : typeof value === "object"
            ? JSON.stringify(value)
            : String(value);
        container.append(term, detail);
      }}
      return container;
    }}

    function renderCards() {{
      board.replaceChildren();
      folderInsertionMarker = null;
      clearFolderInsertionMarker();
      board.className = `board ${{boardType}}`;
      boardEyebrow.textContent = boardType === "freeform"
        ? "Freeform corkboard"
        : "Folder board";
      addCard.hidden = boardType !== "freeform" || !supports("create-card");
      if (cards.length === 0) {{
        const empty = document.createElement("section");
        empty.className = "empty-board";
        empty.textContent = boardType === "freeform"
          ? "No cards yet. Add one to start arranging ideas."
          : "No folders or files yet.";
        board.append(empty);
        return;
      }}
      for (const card of cards) {{
        const cardElement = document.createElement("article");
        cardElement.className = `index-card ${{cardCssType(card)}}`;
        cardElement.dataset.key = cardKey(card);
        cardElement.tabIndex = 0;
        cardElement.classList.toggle("selected", selectedCardKey === cardElement.dataset.key);
        cardElement.setAttribute(
          "aria-selected",
          selectedCardKey === cardElement.dataset.key ? "true" : "false",
        );
        cardElement.style.setProperty("--rotation", `${{Number(card.rotation) || 0}}deg`);
        cardElement.style.setProperty("--paper", cardColor(card));
        cardElement.addEventListener(
          "pointerdown",
          () => selectCard(card, cardElement),
          {{ capture: true }},
        );
        cardElement.addEventListener("focusin", () => selectCard(card, cardElement));
        if (boardType === "freeform") {{
          applyCardPosition(cardElement, card);
          cardElement.addEventListener("pointerdown", startDrag);
          cardElement.addEventListener("pointermove", updateDrag);
          cardElement.addEventListener("pointerup", finishDrag);
          cardElement.addEventListener("pointercancel", finishDrag);
        }} else {{
          ensureFolderInsertionMarker();
          cardElement.draggable = supports("reorder-card");
          cardElement.addEventListener("dragstart", (event) =>
            startFolderDrag(event, card, cardElement),
          );
          cardElement.addEventListener("dragend", () => finishFolderDrag(cardElement));
          cardElement.addEventListener("dragover", (event) => {{
            event.preventDefault();
            showFolderInsertionMarker(event, card, cardElement);
          }});
          cardElement.addEventListener("drop", (event) =>
            dropFolderCard(event, card, cardElement),
          );
        }}

        const head = document.createElement("div");
        head.className = "card-head";
        const titleBox = document.createElement("div");
        let title = null;
        if (boardType === "freeform") {{
          title = document.createElement("input");
          title.className = "card-title-input";
          title.type = "text";
          title.value = card.title || "Untitled card";
          title.readOnly = !supports("edit-card");
          if (supports("edit-card")) {{
            title.addEventListener("input", () => {{
              card.title = title.value;
              queueSave(card);
            }});
          }}
          const isGroupTitle = cardKind(card) === "group";
          let previousTitlePress = 0;
          title.addEventListener("pointerdown", (event) => {{
            event.stopPropagation();
            if (!isGroupTitle || event.button !== 0) {{
              return;
            }}
            const currentPress = window.performance.now();
            if (currentPress - previousTitlePress <= 500) {{
              event.preventDefault();
              previousTitlePress = 0;
              openGroupCard(card);
              return;
            }}
            previousTitlePress = currentPress;
          }});
          if (isGroupTitle) {{
            title.title = "Double-click to open card group";
          }}
        }} else {{
          title = document.createElement("div");
          title.className = "card-title";
          title.textContent = card.name || card.path;
        }}
        if (boardType === "folder") {{
          const type = document.createElement("div");
          type.className = "card-type";
          type.textContent = card.type === "directory"
            ? "Folder"
            : card.corkboard ? "Board" : "File";
          titleBox.append(title, type);
          const tools = document.createElement("div");
          tools.className = "card-tools";
          if (supports("change-color")) {{
            tools.append(buildColorButton(card, cardElement));
          }}
          const open = document.createElement("button");
          open.className = "card-open";
          open.type = "button";
          open.textContent = "Open";
          open.addEventListener("click", () => openCard(card));
          tools.append(open);
          head.append(titleBox, tools);
        }} else {{
          titleBox.append(title);
          const tools = document.createElement("div");
          tools.className = "card-tools";
          if (supports("change-color")) {{
            tools.append(buildColorButton(card, cardElement));
          }}
          if (supports("group-card")) {{
            tools.append(buildGroupButton(card, cardElement));
          }}
          if (card.target && supports("open-card")) {{
            const open = document.createElement("button");
            open.className = "card-open";
            open.type = "button";
            open.textContent = "Open";
            open.addEventListener("click", () => openCard(card));
            tools.append(open);
          }}
          const remove = document.createElement("button");
          remove.className = "card-delete";
          remove.type = "button";
          remove.title = "Delete card";
          remove.setAttribute("aria-label", `Delete ${{card.title || "card"}}`);
          remove.addEventListener("pointerdown", (event) => event.stopPropagation());
          remove.addEventListener("click", () => deleteFreeformCard(card, remove));
          const icon = document.createElement("span");
          icon.className = "card-delete-icon";
          icon.setAttribute("aria-hidden", "true");
          remove.append(icon);
          if (supports("delete-card")) {{
            tools.append(remove);
          }}
          head.append(titleBox, tools);
        }}

        const note = document.createElement("textarea");
        note.className = "card-note";
        note.spellcheck = true;
        note.value = card.note || "";
        note.readOnly = !supports("edit-card");
        if (supports("edit-card")) {{
          note.addEventListener("input", () => {{
            card.note = note.value;
            queueSave(card);
          }});
        }}

        cardElement.append(head, note);
        const metadata = buildCardMetadata(card);
        if (metadata) {{
          cardElement.append(metadata);
        }}
        board.append(cardElement);
      }}
      sizeBoard();
    }}

    addCard.addEventListener("click", makeFreeformCard);
    boardTitle.addEventListener("input", queueBoardTitleSave);
    boardTitle.addEventListener("blur", saveBoardTitle);
    boardTitle.addEventListener("keydown", (event) => {{
      if (event.key === "Enter") {{
        event.preventDefault();
        boardTitle.blur();
      }}
    }});
    if (corkboardChannel) {{
      corkboardChannel.addEventListener("message", (event) => {{
        const message = event.data || {{}};
        if (message.type !== "corkboard-title-changed" || !message.board_path) {{
          return;
        }}
        let changed = false;
        for (const card of cards) {{
          if (
            cardKind(card) === "group" &&
            card.board_path === message.board_path &&
            card.title !== message.title
          ) {{
            card.title = message.title || "Untitled card group";
            changed = true;
          }}
        }}
        if (changed) {{
          renderCards();
        }}
      }});
    }}
    document.addEventListener("click", () => closePalettes());
    cardSizeSlider.addEventListener("input", () => updateCardScale(cardSizeSlider.value));
    canvasViewport.addEventListener("pointerdown", startCanvasPan);
    canvasViewport.addEventListener("pointermove", updateCanvasPan);
    canvasViewport.addEventListener("pointerup", finishCanvasPan);
    canvasViewport.addEventListener("pointercancel", finishCanvasPan);
    canvasViewport.addEventListener("auxclick", (event) => {{
      if (event.button === 1) {{
        event.preventDefault();
      }}
    }});
    window.addEventListener("resize", sizeBoard);
    applyCardScale();
    renderCards();
  </script>
</body>
</html>
"""
    return page, HTTPStatus.OK


def _creative_corkboard_payload(
    project_root: Path | str,
    board_path: str,
    *,
    title: str | None = None,
    context_id: str = "",
) -> dict[str, object]:
    project_root = Path(project_root).expanduser().resolve()
    normalized_path, path = _creative_path(project_root, board_path)
    if path.exists() and path.is_dir():
        return _creative_folder_corkboard_payload(
            project_root,
            normalized_path,
            path,
            title=title,
            context_id=context_id,
        )
    if (
        path.exists()
        and path.is_file()
        and normalized_path.endswith(CREATIVE_CORKBOARD_SUFFIX)
    ):
        return _creative_freeform_corkboard_payload(
            project_root,
            normalized_path,
            path,
            title=title,
            context_id=context_id,
        )
    if normalized_path.endswith(CREATIVE_CORKBOARD_SUFFIX):
        raise StateError(f"corkboard does not exist: {normalized_path}")
    raise StateError(f"folder does not exist: {normalized_path}")


def _creative_folder_corkboard_payload(
    project_root: Path,
    normalized_folder: str,
    folder: Path,
    *,
    title: str | None = None,
    context_id: str = "",
) -> dict[str, object]:
    state = _load_creative_corkboard_state(project_root)
    folder_state = _creative_corkboard_folder_state(state, normalized_folder)
    card_states = _creative_corkboard_folder_cards(folder_state)
    cards = []
    for index, child in enumerate(_creative_corkboard_children(project_root, folder)):
        relative_path = child.relative_to(project_root).as_posix()
        card_state = card_states.get(relative_path, {})
        cards.append(
            _creative_folder_corkboard_card(
                child,
                relative_path,
                index,
                card_state if isinstance(card_state, dict) else {},
            )
        )
    order = folder_state.get("order")
    if isinstance(order, list):
        order_index = {str(path): index for index, path in enumerate(order)}
        natural_index = {str(card["path"]): index for index, card in enumerate(cards)}
        cards.sort(
            key=lambda card: (
                order_index.get(
                    str(card["path"]),
                    len(order) + natural_index[str(card["path"])],
                ),
                natural_index[str(card["path"])],
            )
        )
    return {
        "schema_version": 1,
        "board_type": "folder",
        "context_id": context_id,
        "palette": _creative_card_palette_payload(),
        "title": title or f"Folder board: {folder.name}",
        "folder": {
            "name": folder.name,
            "path": normalized_folder,
        },
        "cards": cards,
    }


def _creative_freeform_corkboard_payload(
    project_root: Path,
    normalized_path: str,
    corkboard_path: Path,
    *,
    title: str | None = None,
    context_id: str = "",
) -> dict[str, object]:
    data = _load_creative_corkboard_document(corkboard_path)
    stored_title = str(data.get("title") or "").strip()
    group_title = _creative_card_group_title(project_root, normalized_path)
    return {
        "schema_version": 1,
        "board_type": "freeform",
        "context_id": context_id,
        "palette": _creative_card_palette_payload(),
        "title": (
            stored_title
            or group_title
            or title
            or corkboard_path.name.removesuffix(CREATIVE_CORKBOARD_SUFFIX)
        ),
        "corkboard": {
            "name": corkboard_path.name,
            "path": normalized_path,
        },
        "cards": _freeform_corkboard_cards(data),
    }


def _creative_corkboard_children(project_root: Path, folder: Path) -> list[Path]:
    try:
        children = sorted(
            folder.iterdir(),
            key=lambda path: (not path.is_dir(), path.name.lower()),
        )
    except OSError:
        return []
    visible_children = []
    for child in children:
        if child.name in CREATIVE_IGNORED_NAMES or child.name.startswith("."):
            continue
        relative_path = child.relative_to(project_root).as_posix()
        if relative_path == CREATIVE_CORKBOARD_GROUP_DIRECTORY.as_posix():
            continue
        visible_children.append(child)
    return visible_children


def _creative_card_palette_payload() -> list[dict[str, str]]:
    return [dict(entry) for entry in CREATIVE_CARD_PALETTE]


def _creative_card_palette_default(index: int) -> str:
    return CREATIVE_CARD_PALETTE[index % len(CREATIVE_CARD_PALETTE)]["id"]


def _normalize_creative_card_color(value: object, default: str) -> str:
    raw = str(value or "").strip()
    if raw in CREATIVE_CARD_PALETTE_IDS:
        return raw
    if CREATIVE_CARD_COLOR_RE.fullmatch(raw):
        return raw.lower()
    return default


def _creative_freeform_card_type(value: object) -> str:
    return "group" if str(value or "").strip() == "group" else "card"


def _normalize_creative_corkboard_reference(value: object) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    try:
        relative_path = Path(raw)
    except ValueError:
        return ""
    if (
        relative_path.is_absolute()
        or any(part in {"", ".."} for part in relative_path.parts)
        or not relative_path.as_posix().endswith(CREATIVE_CORKBOARD_SUFFIX)
    ):
        return ""
    return relative_path.as_posix()


def _creative_card_group_default_path(parent_corkboard_path: str, card_id: str) -> str:
    parent_stem = parent_corkboard_path.removesuffix(CREATIVE_CORKBOARD_SUFFIX)
    parent_slug = _slugify_work_item(parent_stem.replace("/", "-"))
    card_slug = _slugify_work_item(card_id)
    return (
        CREATIVE_CORKBOARD_GROUP_DIRECTORY
        / parent_slug
        / f"{card_slug}{CREATIVE_CORKBOARD_SUFFIX}"
    ).as_posix()


def _creative_card_group_title(
    project_root: Path | str,
    board_path: str,
) -> str:
    project_root_path = Path(project_root).expanduser().resolve()
    for parent_path in project_root_path.rglob(f"*{CREATIVE_CORKBOARD_SUFFIX}"):
        if not parent_path.is_file():
            continue
        try:
            data = json.loads(parent_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cards = data.get("cards") if isinstance(data, dict) else None
        if not isinstance(cards, list):
            continue
        for card in cards:
            if not isinstance(card, dict):
                continue
            if (
                _creative_freeform_card_type(card.get("card_type")) == "group"
                and _normalize_creative_corkboard_reference(card.get("board_path"))
                == board_path
            ):
                return _normalize_creative_corkboard_title(
                    card.get("title"),
                    "Untitled card group",
                )
    return ""


def _ensure_creative_card_group_corkboard(
    project_root: Path | str,
    *,
    parent_corkboard_path: str,
    card_id: str,
    board_title: str,
    board_path: object,
) -> str:
    normalized_board_path = _normalize_creative_corkboard_reference(board_path)
    if not normalized_board_path:
        normalized_board_path = _creative_card_group_default_path(
            parent_corkboard_path,
            card_id,
        )
    _create_creative_corkboard(
        project_root,
        normalized_board_path,
        title=board_title,
    )
    return normalized_board_path


def _creative_folder_corkboard_card(
    path: Path,
    relative_path: str,
    index: int,
    state: dict[str, object],
) -> dict[str, object]:
    style = _creative_corkboard_card_style(relative_path, index)
    color = _normalize_creative_card_color(state.get("color"), str(style["color"]))
    return {
        "name": path.name,
        "path": relative_path,
        "type": "directory" if path.is_dir() else "file",
        "corkboard": path.name.endswith(CREATIVE_CORKBOARD_SUFFIX),
        "note": str(state.get("note") or ""),
        "rotation": style["rotation"],
        "color": color,
    }


def _creative_corkboard_card_style(
    relative_path: str,
    index: int,
) -> dict[str, object]:
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()
    rotation = (int(digest[4:6], 16) % 9) - 4
    return {
        "rotation": rotation,
        "color": _creative_card_palette_default(
            int(digest[6:8], 16) % len(CREATIVE_CARD_PALETTE)
        ),
    }


def _bounded_float(
    value: object,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _creative_corkboard_state_path(project_root: Path | str) -> Path:
    return Path(project_root).expanduser().resolve() / CREATIVE_CORKBOARD_STATE_RELATIVE_PATH


def _load_creative_corkboard_state(project_root: Path | str) -> dict[str, object]:
    path = _creative_corkboard_state_path(project_root)
    if not path.exists():
        return {"schema_version": 1, "folders": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "folders": {}}
    if not isinstance(data, dict):
        return {"schema_version": 1, "folders": {}}
    folders = data.get("folders")
    if not isinstance(folders, dict):
        data["folders"] = {}
    data["schema_version"] = 1
    return data


def _save_creative_corkboard_state(
    project_root: Path | str,
    state: dict[str, object],
) -> None:
    path = _creative_corkboard_state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _creative_corkboard_folder_state(
    state: dict[str, object],
    folder_path: str,
) -> dict[str, object]:
    folders = state.setdefault("folders", {})
    if not isinstance(folders, dict):
        state["folders"] = {}
        folders = state["folders"]
    folder_state = folders.setdefault(folder_path, {})
    if not isinstance(folder_state, dict):
        folder_state = {}
        folders[folder_path] = folder_state
    _creative_corkboard_folder_cards(folder_state)
    order = folder_state.setdefault("order", [])
    if not isinstance(order, list):
        folder_state["order"] = []
    return folder_state


def _creative_corkboard_folder_cards(
    folder_state: dict[str, object],
) -> dict[str, object]:
    cards = folder_state.setdefault("cards", {})
    if not isinstance(cards, dict):
        folder_state["cards"] = {}
        cards = folder_state["cards"]
    return cards


def _save_creative_folder_corkboard_card(
    project_root: Path | str,
    *,
    folder_path: str,
    card_path: str,
    note: str,
    color: object = None,
) -> dict[str, object]:
    normalized_folder, folder = _creative_path(project_root, folder_path)
    normalized_card, card = _creative_path(project_root, card_path)
    if not folder.exists() or not folder.is_dir():
        raise StateError(f"folder does not exist: {normalized_folder}")
    if not card.exists():
        raise StateError(f"card path does not exist: {normalized_card}")
    if card.parent.resolve() != folder.resolve():
        raise StateError("card does not belong to the corkboard folder")
    state = _load_creative_corkboard_state(project_root)
    folder_state = _creative_corkboard_folder_state(state, normalized_folder)
    card_states = _creative_corkboard_folder_cards(folder_state)
    previous = card_states.get(normalized_card, {})
    style = _creative_corkboard_card_style(normalized_card, len(card_states))
    previous_color = (
        previous.get("color")
        if isinstance(previous, dict)
        else None
    )
    default_color = _normalize_creative_card_color(previous_color, str(style["color"]))
    card_states[normalized_card] = {
        **(previous if isinstance(previous, dict) else {}),
        "note": note[:5000],
        "color": _normalize_creative_card_color(color, default_color),
    }
    _save_creative_corkboard_state(project_root, state)
    return {
        "path": normalized_card,
        **card_states[normalized_card],
    }


def _save_creative_folder_corkboard_order(
    project_root: Path | str,
    *,
    folder_path: str,
    order: list[str],
) -> list[str]:
    normalized_folder, folder = _creative_path(project_root, folder_path)
    if not folder.exists() or not folder.is_dir():
        raise StateError(f"folder does not exist: {normalized_folder}")
    project_root_path = Path(project_root).expanduser().resolve()
    valid_children = {
        child.relative_to(project_root_path).as_posix()
        for child in _creative_corkboard_children(project_root_path, folder)
    }
    saved_order: list[str] = []
    seen: set[str] = set()
    for item in order:
        normalized_item, item_path = _creative_path(project_root, item)
        if (
            normalized_item in valid_children
            and normalized_item not in seen
            and item_path.parent.resolve() == folder.resolve()
        ):
            saved_order.append(normalized_item)
            seen.add(normalized_item)
    for item in sorted(valid_children):
        if item not in seen:
            saved_order.append(item)
    state = _load_creative_corkboard_state(project_root)
    folder_state = _creative_corkboard_folder_state(state, normalized_folder)
    folder_state["order"] = saved_order
    _save_creative_corkboard_state(project_root, state)
    return saved_order


def _load_creative_corkboard_document(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_creative_corkboard_document()
    if not isinstance(data, dict):
        return _empty_creative_corkboard_document()
    if data.get("type") != "electroboy.creative.corkboard":
        data["type"] = "electroboy.creative.corkboard"
    data["schema_version"] = 1
    if not isinstance(data.get("cards"), list):
        data["cards"] = []
    return data


def _freeform_corkboard_cards(data: dict[str, object]) -> list[dict[str, object]]:
    cards = data.get("cards")
    if not isinstance(cards, list):
        return []
    normalized_cards: list[dict[str, object]] = []
    for index, raw_card in enumerate(cards):
        if not isinstance(raw_card, dict):
            continue
        card_id = str(raw_card.get("id") or f"card-{index + 1}")
        style = _creative_corkboard_card_style(card_id, index)
        color = _normalize_creative_card_color(
            raw_card.get("color"),
            str(style["color"]),
        )
        card_type = _creative_freeform_card_type(raw_card.get("card_type"))
        card = {
            "id": card_id[:100],
            "title": str(raw_card.get("title") or "Untitled card")[:200],
            "note": str(raw_card.get("note") or "")[:5000],
            "x": _bounded_float(
                raw_card.get("x"),
                36 + index * 24,
                -1_000_000,
                1_000_000,
            ),
            "y": _bounded_float(
                raw_card.get("y"),
                36 + index * 18,
                -1_000_000,
                1_000_000,
            ),
            "rotation": _bounded_float(
                raw_card.get("rotation"),
                float(style["rotation"]),
                -8,
                8,
            ),
            "color": color,
            "card_type": card_type,
        }
        if card_type == "group":
            board_path = _normalize_creative_corkboard_reference(
                raw_card.get("board_path")
            )
            if board_path:
                card["board_path"] = board_path
        normalized_cards.append(card)
    return normalized_cards


def _save_creative_freeform_corkboard_card(
    project_root: Path | str,
    *,
    corkboard_path: str,
    card_payload: dict[str, object],
) -> dict[str, object]:
    normalized_path, path = _creative_path(project_root, corkboard_path)
    if not normalized_path.endswith(CREATIVE_CORKBOARD_SUFFIX):
        raise StateError(f"corkboard path must end with {CREATIVE_CORKBOARD_SUFFIX}")
    if not path.exists():
        _create_creative_corkboard(project_root, normalized_path)
    if not path.is_file():
        raise StateError(f"corkboard is not a file: {normalized_path}")
    data = _load_creative_corkboard_document(path)
    cards = _freeform_corkboard_cards(data)
    card_id = str(card_payload.get("id") or uuid4().hex)[:100]
    style = _creative_corkboard_card_style(card_id, len(cards))
    existing_card: dict[str, object] = {}
    existing_color: object = None
    for existing in cards:
        if existing.get("id") == card_id:
            existing_card = existing
            existing_color = existing.get("color")
            break
    default_color = _normalize_creative_card_color(existing_color, str(style["color"]))
    card_type = _creative_freeform_card_type(
        card_payload.get("card_type") or existing_card.get("card_type")
    )
    card = {
        "id": card_id,
        "title": str(card_payload.get("title") or "Untitled card")[:200],
        "note": str(card_payload.get("note") or "")[:5000],
        "x": _bounded_float(
            card_payload.get("x"),
            36,
            -1_000_000,
            1_000_000,
        ),
        "y": _bounded_float(
            card_payload.get("y"),
            36,
            -1_000_000,
            1_000_000,
        ),
        "rotation": _bounded_float(
            card_payload.get("rotation"),
            float(style["rotation"]),
            -8,
            8,
        ),
        "color": _normalize_creative_card_color(
            card_payload.get("color"),
            default_color,
        ),
        "card_type": card_type,
    }
    if card_type == "group":
        card["board_path"] = _ensure_creative_card_group_corkboard(
            project_root,
            parent_corkboard_path=normalized_path,
            card_id=card_id,
            board_title=str(card["title"]),
            board_path=(
                card_payload.get("board_path")
                or existing_card.get("board_path")
            ),
        )
    replaced = False
    for index, existing in enumerate(cards):
        if existing.get("id") == card_id:
            cards[index] = card
            replaced = True
            break
    if not replaced:
        cards.append(card)
    data["cards"] = cards
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return card


def _delete_creative_freeform_corkboard_card(
    project_root: Path | str,
    *,
    corkboard_path: str,
    card_id: str,
) -> str:
    normalized_path, path = _creative_path(project_root, corkboard_path)
    if not normalized_path.endswith(CREATIVE_CORKBOARD_SUFFIX):
        raise StateError(f"corkboard path must end with {CREATIVE_CORKBOARD_SUFFIX}")
    if not path.is_file():
        raise StateError(f"corkboard does not exist: {normalized_path}")
    normalized_card_id = card_id.strip()[:100]
    if not normalized_card_id:
        raise StateError("freeform corkboard card id is required")
    data = _load_creative_corkboard_document(path)
    cards = _freeform_corkboard_cards(data)
    remaining_cards = [
        card for card in cards if card.get("id") != normalized_card_id
    ]
    if len(remaining_cards) == len(cards):
        raise StateError(f"card does not exist: {normalized_card_id}")
    data["cards"] = remaining_cards
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return normalized_card_id


def _save_creative_freeform_corkboard_title(
    project_root: Path | str,
    *,
    corkboard_path: str,
    title: object,
) -> dict[str, object]:
    normalized_path, path = _creative_path(project_root, corkboard_path)
    if not normalized_path.endswith(CREATIVE_CORKBOARD_SUFFIX):
        raise StateError(f"corkboard path must end with {CREATIVE_CORKBOARD_SUFFIX}")
    if not path.is_file():
        raise StateError(f"corkboard does not exist: {normalized_path}")
    normalized_title = _normalize_creative_corkboard_title(title, "")
    if not str(title or "").strip():
        raise StateError("corkboard title is required")
    data = _load_creative_corkboard_document(path)
    data["title"] = normalized_title
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    updated_groups: list[dict[str, str]] = []
    project_root_path = Path(project_root).expanduser().resolve()
    for parent_path in project_root_path.rglob(f"*{CREATIVE_CORKBOARD_SUFFIX}"):
        if not parent_path.is_file() or parent_path == path:
            continue
        try:
            parent_data = json.loads(parent_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cards = parent_data.get("cards") if isinstance(parent_data, dict) else None
        if not isinstance(cards, list):
            continue
        changed = False
        for card in cards:
            if not isinstance(card, dict):
                continue
            if (
                _creative_freeform_card_type(card.get("card_type")) == "group"
                and _normalize_creative_corkboard_reference(card.get("board_path"))
                == normalized_path
                and card.get("title") != normalized_title
            ):
                card["title"] = normalized_title
                changed = True
                updated_groups.append(
                    {
                        "corkboard": parent_path.relative_to(
                            project_root_path
                        ).as_posix(),
                        "card_id": str(card.get("id") or ""),
                    }
                )
        if changed:
            parent_path.write_text(
                json.dumps(parent_data, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    return {"title": normalized_title, "group_cards": updated_groups}


def save_creative_corkboard(
    project_root: Path | str,
    payload: dict[str, object],
) -> dict[str, object]:
    """Persist one folder or freeform corkboard operation."""

    board_type = str(payload.get("board_type") or "folder")
    if board_type == "folder" and "order" in payload:
        order = payload.get("order")
        if not isinstance(order, list):
            raise StateError("folder corkboard order must be a list")
        saved_order = _save_creative_folder_corkboard_order(
            project_root,
            folder_path=str(payload.get("folder") or ""),
            order=[str(item) for item in order],
        )
        return {"status": "saved", "order": saved_order}
    if board_type == "folder":
        card = _save_creative_folder_corkboard_card(
            project_root,
            folder_path=str(payload.get("folder") or ""),
            card_path=str(payload.get("path") or ""),
            note=str(payload.get("note") or ""),
            color=payload.get("color"),
        )
        return {"status": "saved", "card": card}
    if board_type == "freeform":
        action = str(payload.get("action") or "")
        if action == "title":
            title_result = _save_creative_freeform_corkboard_title(
                project_root,
                corkboard_path=str(payload.get("corkboard") or ""),
                title=payload.get("title"),
            )
            return {"status": "saved", **title_result}
        if action == "delete":
            card_id = _delete_creative_freeform_corkboard_card(
                project_root,
                corkboard_path=str(payload.get("corkboard") or ""),
                card_id=str(payload.get("card_id") or ""),
            )
            return {"status": "deleted", "card_id": card_id}
        card_payload = payload.get("card")
        if not isinstance(card_payload, dict):
            raise StateError("freeform corkboard card is required")
        card = _save_creative_freeform_corkboard_card(
            project_root,
            corkboard_path=str(payload.get("corkboard") or ""),
            card_payload=card_payload,
        )
        return {"status": "saved", "card": card}
    raise StateError(f"unknown corkboard type: {board_type}")


def _remap_creative_path_reference(path: str, old_path: str, new_path: str) -> str:
    if path == old_path:
        return new_path
    if path.startswith(f"{old_path}/"):
        return f"{new_path}/{path[len(old_path) + 1:]}"
    return path


def _remap_creative_corkboard_paths(
    project_root: Path | str,
    old_path: str,
    new_path: str,
) -> None:
    state_path = _creative_corkboard_state_path(project_root)
    if not state_path.exists():
        return
    state = _load_creative_corkboard_state(project_root)
    folders = state.get("folders")
    if not isinstance(folders, dict):
        return
    remapped_folders: dict[str, object] = {}
    for folder_key, folder_state in folders.items():
        if not isinstance(folder_key, str) or not isinstance(folder_state, dict):
            continue
        next_folder_key = _remap_creative_path_reference(folder_key, old_path, new_path)
        cards = folder_state.get("cards")
        if isinstance(cards, dict):
            folder_state["cards"] = {
                _remap_creative_path_reference(
                    str(card_path),
                    old_path,
                    new_path,
                ): card_state
                for card_path, card_state in cards.items()
            }
        order = folder_state.get("order")
        if isinstance(order, list):
            folder_state["order"] = [
                _remap_creative_path_reference(str(card_path), old_path, new_path)
                for card_path in order
            ]
        remapped_folders[next_folder_key] = folder_state
    state["folders"] = remapped_folders
    _save_creative_corkboard_state(project_root, state)


def _remove_creative_corkboard_paths(project_root: Path | str, removed_path: str) -> None:
    state_path = _creative_corkboard_state_path(project_root)
    if not state_path.exists():
        return
    state = _load_creative_corkboard_state(project_root)
    folders = state.get("folders")
    if not isinstance(folders, dict):
        return
    kept_folders: dict[str, object] = {}
    for folder_key, folder_state in folders.items():
        if not isinstance(folder_key, str) or _creative_path_is_inside(folder_key, removed_path):
            continue
        if isinstance(folder_state, dict):
            cards = folder_state.get("cards")
            if isinstance(cards, dict):
                folder_state["cards"] = {
                    str(card_path): card_state
                    for card_path, card_state in cards.items()
                    if not _creative_path_is_inside(str(card_path), removed_path)
                }
            order = folder_state.get("order")
            if isinstance(order, list):
                folder_state["order"] = [
                    str(card_path)
                    for card_path in order
                    if not _creative_path_is_inside(str(card_path), removed_path)
                ]
        kept_folders[folder_key] = folder_state
    state["folders"] = kept_folders
    _save_creative_corkboard_state(project_root, state)


def _creative_path_is_inside(path: str, container: str) -> bool:
    return path == container or path.startswith(f"{container}/")


def _creative_agent_target(
    root: Path,
    *,
    active_target: dict[str, object] | None = None,
    active_document: str | None = None,
) -> dict[str, str] | None:
    if isinstance(active_target, dict):
        target_type = str(active_target.get("type") or "").strip()
        target_path = str(active_target.get("path") or "").strip()
        if target_type == "document" and target_path:
            normalized_path, _path = _document_target_path(root, target_path)
            return {"type": "document", "path": normalized_path}
        if target_type == "freeform-corkboard" and target_path:
            normalized_path, path = _creative_path(root, target_path)
            if not normalized_path.endswith(CREATIVE_CORKBOARD_SUFFIX):
                raise StateError("freeform corkboard path must end in .corkboard.json")
            if not path.is_file():
                raise StateError("freeform corkboard path is not a file")
            return {"type": "freeform-corkboard", "path": normalized_path}
        if target_type == "folder-corkboard" and target_path:
            normalized_path, path = _creative_path(root, target_path)
            if not path.is_dir():
                raise StateError("folder corkboard path is not a directory")
            return {"type": "folder-corkboard", "path": normalized_path}
    if active_document:
        if active_document.endswith(CREATIVE_CORKBOARD_SUFFIX):
            normalized_path, _path = _creative_path(root, active_document)
            return {"type": "freeform-corkboard", "path": normalized_path}
        normalized_path, _path = _document_target_path(root, active_document)
        return {"type": "document", "path": normalized_path}
    return None


def _creative_writing_command(
    root: Path,
    active_target: dict[str, str] | None = None,
) -> list[str]:
    return [
        "codex",
        "--cd",
        str(root),
        "--sandbox",
        "workspace-write",
        _creative_writing_prompt(active_target),
    ]


def _creative_writing_prompt(active_target: dict[str, str] | None = None) -> str:
    target_lines = _creative_writing_target_prompt_lines(active_target)
    return "\n".join(
        [
            "Act as a creative writing collaborator inside this project.",
            "",
            "The writer may move fluidly among chapters, character notes,",
            "corkboard ideas, reviews, research, and scratchpad notes.",
            "Markdown files are the source of truth for prose and notes.",
            "Use docs/corkboard-api.md for corkboard operations.",
            "Do not edit corkboard JSON directly unless the writer asks.",
            "Do not rewrite or reorganize files until the writer asks.",
            "When asked to write or revise without naming a different file,",
            "work in the active target.",
            "Use scratchpad/scratchpad.md as optional context for rough notes.",
            "Keep responses concise unless the writer asks for a draft.",
            *target_lines,
        ]
    )


def _creative_writing_target_prompt_lines(
    active_target: dict[str, str] | None,
) -> list[str]:
    if not active_target:
        return []
    target_type = active_target.get("type", "")
    target_path = active_target.get("path", "")
    if target_type == "document":
        return [
            "",
            f"Current active target: document {target_path}.",
            "Treat it as the document displayed in the middle pane.",
        ]
    if target_type == "freeform-corkboard":
        return [
            "",
            f"Current active target: freeform corkboard {target_path}.",
            "This board contains arbitrary cards with x/y positions.",
            "Use `electroboy corkboard` commands from docs/corkboard-api.md",
            "for card additions, edits, moves, styling, and deletes.",
        ]
    if target_type == "folder-corkboard":
        return [
            "",
            f"Current active target: folder corkboard {target_path}.",
            "This board is backed by that folder's files and subfolders.",
            "Use `electroboy corkboard folder` commands for notes and order.",
            "Create, delete, or rename files only when the writer asks.",
        ]
    return []
