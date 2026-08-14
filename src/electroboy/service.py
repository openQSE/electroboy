"""Local browser service for ElectroBoy."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import html
import io
import json
import os
import pty
import re
import shutil
import signal
import shlex
import struct
import subprocess
import sys
import termios
import threading
import time
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from .artifacts import ArtifactManager
from .document_export import (
    DocumentExportError,
    export_markdown_document,
)
from .feature_artifacts import (
    artifact_paths_for_run,
    read_feature_record,
    resolve_artifact_path,
)
from .models import (
    ActivityEvent,
    GATE_DESIGN,
    STAGE_COMPLETE,
    STAGE_DESIGN,
    STAGE_DESIGN_ACCEPTANCE,
    STAGE_DESIGN_REVIEW,
    STAGE_DOCS_REVIEW,
    STAGE_IMPLEMENTATION,
    STAGE_PLAN,
    STAGE_REQUIREMENTS,
    STAGE_TEST_PLAN,
    STAGE_VALIDATION,
    utc_now,
)
from .state_store import StateError, StateStore
from .structured_artifacts import (
    ARTIFACT_DEFAULT_MARKDOWN_PATHS,
    ARTIFACT_TITLES,
    artifact_jsonl_path,
    artifact_markdown_path,
    import_artifact,
    read_artifact_records,
    render_artifact,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
SPLASH_IMAGE_ROUTE = "/assets/electroboy-splash-16x9.png"
CREATIVE_SPLASH_IMAGE_ROUTE = "/assets/electroboy-splash-creative-writing-16x9.png"
SPLASH_IMAGE_PACKAGE = "electroboy"
SPLASH_IMAGE_RESOURCE = "electroboy-splash-16x9.png"
CREATIVE_SPLASH_IMAGE_RESOURCE = "electroboy-splash-creative-writing-16x9.png"
TERMINAL_SUBMIT_DELAY_SECONDS = 0.08
MIN_TERMINAL_COLUMNS = 20
MAX_TERMINAL_COLUMNS = 1000
MIN_TERMINAL_ROWS = 5
MAX_TERMINAL_ROWS = 120
META_REGISTRY_RELATIVE_PATH = Path(".electroboy") / "shared" / "repositories.json"
WORK_ITEM_REGISTRY_RELATIVE_PATH = Path(".electroboy") / "shared" / "work-items.json"
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
RECENT_PROJECTS_RELATIVE_PATH = Path(".electroboy") / "service" / "recent-projects.json"
RECENT_PROJECT_LIMIT = 12
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

_CONTROL_CHARS_TO_DROP = frozenset(
    chr(code)
    for code in [*range(0x00, 0x08), *range(0x0B, 0x0D), *range(0x0E, 0x20), 0x7F]
)

WORKFLOW_STAGES = [
    "project",
    "requirements",
    "design",
    "design-review",
    "implementation-plan",
    "code",
    "test-plan",
    "validate",
    "document",
]

APPROVAL_WORKFLOW_STAGES = frozenset(
    {
        "requirements-approve",
        "design-approve",
        "plan-approve",
        "code-approve",
        "test-plan-approve",
        "validation-approve",
    }
)

APPROVAL_STAGE_OWNERS = {
    "requirements-approve": "requirements",
    "design-approve": "design-review",
    "plan-approve": "implementation-plan",
    "code-approve": "code",
    "test-plan-approve": "test-plan",
    "validation-approve": "validate",
}

DURABLE_STAGE_OWNERS = {
    STAGE_DESIGN_ACCEPTANCE: "design-review",
    STAGE_PLAN: "implementation-plan",
    STAGE_IMPLEMENTATION: "code",
    STAGE_TEST_PLAN: "test-plan",
    STAGE_VALIDATION: "validate",
    STAGE_DOCS_REVIEW: "document",
    STAGE_COMPLETE: "document",
}

SESSION_ARTIFACT_LOCKS = {
    "requirements": frozenset({"docs/requirements.md", "docs/requirements.jsonl"}),
    "design": frozenset({"docs/detailed-design.md", "docs/detailed-design.jsonl"}),
    "design-review": frozenset(
        {
            "docs/detailed-design.md",
            "docs/detailed-design.jsonl",
            "design-review.jsonl",
        }
    ),
    "implementation-plan": frozenset(
        {"docs/implementation-plan.md", "docs/implementation-plan.jsonl"}
    ),
    "code": frozenset(
        {
            "docs/implementation-log.md",
            "docs/implementation-report.md",
        }
    ),
    "test-plan": frozenset({"docs/test-plan.md", "docs/test-plan.jsonl"}),
    "validate": frozenset(
        {
            "docs/test-review.md",
            "docs/validation-report.md",
            "validation-test-review.jsonl",
            "validation-review.jsonl",
        }
    ),
    "documentation": frozenset(),
}

GENERIC_STAGE_CONFIG: dict[str, dict[str, object]] = {
    "implementation-plan": {
        "command": "implementation-plan",
        "approval_command": "plan-approve",
        "artifact_path": "docs/implementation-plan.md",
        "artifact_title": "Implementation Plan",
        "interactive_default": True,
        "interactive_arg": False,
        "reason_arg": True,
        "approval_reason_arg": True,
        "next_stage": "code",
    },
    "code": {
        "command": "code",
        "approval_command": "code-approve",
        "artifact_path": "docs/implementation-report.md",
        "artifact_title": "Implementation Report",
        "interactive_default": False,
        "interactive_arg": True,
        "reason_arg": True,
        "approval_reason_arg": False,
        "next_stage": "test-plan",
    },
    "test-plan": {
        "command": "test-plan",
        "approval_command": "test-plan-approve",
        "artifact_path": "docs/test-plan.md",
        "artifact_title": "Test Plan",
        "interactive_default": True,
        "interactive_arg": False,
        "reason_arg": True,
        "approval_reason_arg": True,
        "next_stage": "validate",
    },
    "validate": {
        "command": "validate",
        "approval_command": "validation-approve",
        "artifact_path": "docs/validation-report.md",
        "artifact_title": "Validation Report",
        "interactive_default": False,
        "interactive_arg": True,
        "reason_arg": False,
        "approval_reason_arg": True,
        "next_stage": "document",
    },
}

WORKFLOW_STAGE_RESET_TARGETS = {
    "requirements": STAGE_REQUIREMENTS,
    "design": STAGE_DESIGN,
    "design-review": STAGE_DESIGN_REVIEW,
    "implementation-plan": STAGE_PLAN,
    "code": STAGE_IMPLEMENTATION,
    "test-plan": STAGE_TEST_PLAN,
    "validate": STAGE_VALIDATION,
}

ARTIFACT_EVENT_ROUTE_PATHS = {
    "/artifacts/requirements": "docs/requirements.md",
    "/artifacts/design": "docs/detailed-design.md",
    "/artifacts/design-review": "docs/design-review.md",
    "/artifacts/implementation-plan": "docs/implementation-plan.md",
    "/artifacts/implementation-report": "docs/implementation-report.md",
    "/artifacts/test-plan": "docs/test-plan.md",
    "/artifacts/validation-report": "docs/validation-report.md",
}

STRUCTURED_ARTIFACT_BY_MARKDOWN_PATH = {
    path: artifact
    for artifact, path in ARTIFACT_DEFAULT_MARKDOWN_PATHS.items()
}

ARTIFACT_EDITOR_LIST_FIELDS = {
    "acceptance_criteria",
    "commit_tasks",
    "consequences",
    "dependencies",
    "design_sections",
    "expected_results",
    "exit_criteria",
    "implementation_units",
    "interfaces",
    "out_of_scope",
    "paths",
    "personas",
    "plan_tasks",
    "preconditions",
    "requirements",
    "scope",
    "steps",
    "verification",
}

ARTIFACT_EDITOR_JSON_FIELDS = {"automation", "schema"}

INDEX_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ElectroBoy</title>
  <link
    rel="stylesheet"
    href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css"
  >
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fb;
      --panel: #ffffff;
      --top-surface: #dce9f6;
      --top-surface-strong: #c9dced;
      --side-surface: #d3e2f0;
      --side-surface-strong: #c2d5e7;
      --blue-surface-hover: #c8dbea;
      --blue-surface-active: #b7d7de;
      --ink: #1b1f2a;
      --muted: #53657a;
      --border: #aebfd0;
      --active: #0f766e;
      --active-soft: #dff6f2;
      --disabled: #eef1f6;
      --terminal: #10141f;
      --terminal-text: #e7edf7;
      --error: #b42318;
      --ui-font-size: 13px;
      --ui-small-font-size: 12px;
      --ui-menu-font-size: 14px;
      --terminal-font-size: 15px;
    }

    * {
      box-sizing: border-box;
    }

    html,
    body {
      height: 100%;
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family:
        Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      font-size: var(--ui-font-size);
    }

    body {
      overflow: hidden;
    }

    .splash-overlay {
      position: fixed;
      inset: 0;
      z-index: 1000;
      display: grid;
      place-items: center;
      background:
        radial-gradient(circle at center, rgb(24 40 61 / 58%), rgb(5 8 14 / 86%));
      backdrop-filter: blur(7px);
      cursor: pointer;
      padding: 32px;
    }

    .splash-overlay[hidden] {
      display: none;
    }

    .splash-card {
      position: relative;
      width: min(94vw, calc((100vh - 64px) * 16 / 9), 1800px);
      aspect-ratio: 16 / 9;
      overflow: hidden;
      border: 1px solid rgb(102 217 232 / 42%);
      border-radius: 10px;
      background: #10141f;
      box-shadow:
        0 0 0 1px rgb(255 255 255 / 5%) inset,
        0 28px 72px rgb(0 0 0 / 48%),
        0 0 48px rgb(102 217 232 / 20%);
      cursor: default;
    }

    .splash-card img {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: cover;
    }

    .splash-close {
      position: absolute;
      top: 14px;
      right: 14px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      border: 1px solid rgb(102 217 232 / 40%);
      border-radius: 50%;
      background: rgb(16 20 31 / 74%);
      color: #e7edf7;
      cursor: pointer;
      font: inherit;
      font-size: 20px;
      line-height: 1;
    }

    .splash-close:hover,
    .splash-close:focus-visible {
      border-color: #66d9e8;
      background: rgb(29 38 56 / 88%);
      outline: none;
    }

    .shell {
      position: relative;
      display: grid;
      grid-template-columns: var(--workflow-side-sheet-width, 320px) minmax(0, 1fr);
      grid-template-rows:
        var(--workflow-pane-height, 86px) 7px
        minmax(0, 1fr);
      height: 100vh;
      min-height: 560px;
    }

    .shell.side-sheet-collapsed {
      --workflow-side-sheet-width: 64px;
    }

    .workflow-pane {
      position: relative;
      z-index: 10;
      grid-column: 2;
      grid-row: 1;
      padding: 8px 18px 4px;
      border-bottom: 1px solid var(--border);
      background: var(--top-surface);
      overflow: visible;
    }

    .workflow-side-sheet {
      grid-column: 1;
      grid-row: 1 / 4;
      z-index: 18;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      min-width: 0;
      min-height: 0;
      border-right: 1px solid var(--border);
      background: var(--side-surface);
      box-shadow: 3px 0 16px rgb(15 43 70 / 9%);
    }

    .side-sheet-header {
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 64px;
      border-bottom: 1px solid var(--border);
      background: var(--side-surface-strong);
      padding: 0 12px;
    }

    .side-sheet-toggle {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 40px;
      height: 40px;
      border: 1px solid transparent;
      border-radius: 999px;
      background: transparent;
      color: #29435d;
      cursor: pointer;
      font: inherit;
    }

    .side-sheet-toggle:hover,
    .side-sheet-toggle:focus-visible {
      border-color: #9bb4cb;
      background: #dceaf5;
      outline: none;
    }

    .side-sheet-toggle-icon {
      display: block;
      width: 22px;
      height: 22px;
      fill: none;
      stroke: currentColor;
      stroke-linecap: round;
      stroke-linejoin: round;
      stroke-width: 2;
    }

    .side-sheet-toggle-icon-open {
      display: none;
    }

    .shell.side-sheet-collapsed .side-sheet-toggle-icon-close {
      display: none;
    }

    .shell.side-sheet-collapsed .side-sheet-toggle-icon-open {
      display: block;
    }

    .side-sheet-title {
      min-width: 0;
      flex: 1 1 auto;
      overflow: hidden;
      color: #1d3348;
      font-size: var(--ui-font-size);
      font-weight: 400;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .workflow-mode-select {
      min-width: 0;
      flex: 1 1 auto;
      height: 34px;
      border: 1px solid #9fb4c8;
      border-radius: 7px;
      background: #eef6fb;
      color: #1d3348;
      font: inherit;
      font-size: var(--ui-small-font-size);
      padding: 0 8px;
    }

    .shell.side-sheet-collapsed .side-sheet-header {
      justify-content: center;
      padding: 0;
    }

    .shell.side-sheet-collapsed .side-sheet-title,
    .shell.side-sheet-collapsed .workflow-mode-select,
    .shell.side-sheet-collapsed .stage-action-panel {
      display: none;
    }

    .workflow-toolbar {
      position: absolute;
      top: 8px;
      left: 18px;
      z-index: 12;
      display: flex;
      align-items: center;
      gap: 34px;
      min-width: 0;
      max-width: calc(100% - 180px);
    }

    .workflow-toolbar .toolbar-control-group + .toolbar-control-group {
      position: relative;
    }

    .workflow-toolbar .toolbar-control-group + .toolbar-control-group::before {
      position: absolute;
      top: 50%;
      left: -27px;
      width: 20px;
      height: 1px;
      transform: translateY(-50%);
      background: #b7c5d4;
      content: "";
    }

    .toolbar-control-group {
      display: inline-flex;
      align-items: center;
      gap: 0;
      width: clamp(270px, calc(var(--ui-font-size) * 21), 360px);
      height: calc(var(--ui-font-size) + 23px);
      min-height: 34px;
      overflow: hidden;
      border: 1px solid #9fb4c8;
      border-radius: 8px;
      background: var(--top-surface-strong);
      box-shadow:
        0 1px 0 rgb(255 255 255 / 45%) inset,
        0 6px 16px rgb(15 43 70 / 7%);
    }

    .toolbar-control-label {
      display: inline-flex;
      align-items: center;
      align-self: stretch;
      flex: 0 0 calc(var(--ui-font-size) * 4.7);
      border-right: 1px solid #a8bbcd;
      color: #2d465f;
      padding: 0 10px;
      font-size: var(--ui-small-font-size);
      font-weight: 500;
      text-transform: uppercase;
      white-space: nowrap;
    }

    .toolbar-control-group button,
    .toolbar-control-group select {
      border: 0;
      background: transparent;
      color: var(--ink);
      font-family: inherit;
    }

    .toolbar-control-group button:hover:not(:disabled),
    .toolbar-control-group select:hover:not(:disabled) {
      background: var(--blue-surface-hover);
    }

    .shell-control {
      width: clamp(150px, calc(var(--ui-font-size) * 12), 220px);
    }

    .toolbar-command-button {
      flex: 1 1 auto;
      align-self: stretch;
      padding: 0 14px;
      font-size: var(--ui-small-font-size);
      font-weight: 400;
      text-transform: uppercase;
    }

    .toolbar-command-button.active {
      background: #b8ddd6;
      color: #155349;
    }

    .shell-resize-handle,
    .input-resize-handle,
    .output-resize-handle,
    .workbench-resize-handle,
    .side-pane-resize-handle,
    .artifact-pane-resize-handle,
    .shell-pane-divider {
      touch-action: none;
      user-select: none;
    }

    .shell-resize-handle {
      position: relative;
      z-index: 8;
      grid-column: 2;
      grid-row: 2;
      min-height: 0;
      background: #d0d9e6;
      cursor: row-resize;
    }

    .shell-resize-handle:hover,
    .shell.resizing .shell-resize-handle {
      background: #7398b4;
    }

    .stage-scroll {
      position: relative;
      display: none;
      overflow-x: auto;
      overflow-y: hidden;
      margin: 0 -18px;
      padding: 0 18px;
    }

    .stage-scroll::-webkit-scrollbar {
      height: 10px;
    }

    .stage-scroll::-webkit-scrollbar-thumb {
      border: 3px solid var(--panel);
      border-radius: 999px;
      background: #c6d1df;
    }

    .stage-scroll::-webkit-scrollbar-track {
      background: transparent;
    }

    .stage-scroll {
      scrollbar-color: #c6d1df transparent;
      scrollbar-width: thin;
    }

    .stage-icon-defs {
      position: absolute;
      width: 0;
      height: 0;
      overflow: hidden;
    }

    .connection {
      position: absolute;
      right: 18px;
      top: 10px;
      color: #264e66;
      font-size: var(--ui-font-size);
      font-weight: 400;
    }

    .stage-graph {
      position: relative;
      display: grid;
      align-items: center;
      grid-template-columns:
        repeat(7, minmax(96px, 1fr) minmax(34px, 0.35fr))
        minmax(96px, 1fr) minmax(24px, 0.28fr) minmax(96px, 1fr);
      gap: clamp(6px, 0.45vw, 10px);
      width: 100%;
      min-width: 1180px;
      padding-top: 36px;
    }

    .stage-graph::before {
      content: none;
    }

    .stage-connector {
      position: relative;
      z-index: 1;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      min-width: 34px;
      color: #587086;
      pointer-events: none;
    }

    .stage-connector-icon {
      width: clamp(28px, 2.3vw, 36px);
      height: clamp(28px, 2.3vw, 36px);
      filter: drop-shadow(0 1px 1px rgb(17 24 39 / 12%));
      opacity: 0.9;
    }

    .stage-node {
      position: relative;
      z-index: 1;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      min-width: 106px;
      min-height: 42px;
      padding: 0 10px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: linear-gradient(180deg, #f8fbff 0%, #edf2f7 100%);
      color: var(--muted);
      font-size: var(--ui-font-size);
      font-weight: 650;
      letter-spacing: 0;
      white-space: normal;
      text-align: center;
      line-height: 1.15;
      overflow-wrap: anywhere;
      box-shadow:
        0 1px 0 rgb(255 255 255 / 90%) inset,
        0 5px 14px rgb(17 24 39 / 7%);
    }

    button.stage-node {
      cursor: pointer;
      font-family: inherit;
    }

    button.stage-node:focus-visible,
    .stage-menu button:focus-visible,
    .agent-input:focus-visible {
      outline: 3px solid #9bd6cf;
      outline-offset: 2px;
    }

    .stage-node.active {
      border-color: #005f66;
      background: linear-gradient(180deg, #008b94 0%, #006b73 100%);
      color: #ffffff;
      box-shadow:
        0 1px 0 rgb(255 255 255 / 20%) inset,
        0 8px 18px rgb(0 95 102 / 20%);
    }

    .stage-node.available {
      border-color: #6f91a8;
      background: linear-gradient(180deg, #ffffff 0%, #f4fbfc 100%);
      color: #243f53;
    }

    .stage-node.complete {
      border-color: #9fb4c9;
      background: linear-gradient(180deg, #f4fbff 0%, #e2f2fb 100%);
      color: #27445e;
    }

    .stage-node.disabled {
      border-color: var(--border);
      background: linear-gradient(180deg, #f3f5f8 0%, #e8edf3 100%);
      color: var(--muted);
      cursor: default;
    }

    .stage-node.sidecar {
      border-style: dashed;
      border-color: #9b7a45;
      background: linear-gradient(180deg, #fffdf7 0%, #f7efe0 100%);
      color: #614a1e;
      box-shadow:
        0 1px 0 rgb(255 255 255 / 90%) inset,
        0 5px 14px rgb(97 74 30 / 8%);
    }

    .stage-node.sidecar.available {
      border-color: #9b7a45;
      background: linear-gradient(180deg, #fffaf0 0%, #f3e5c7 100%);
      color: #614a1e;
    }

    .stage-spacer {
      min-width: 24px;
    }

    button.stage-node.available:hover {
      border-color: #1d7180;
      background: linear-gradient(180deg, #f8ffff 0%, #e8f8fa 100%);
    }

    .stage-menu {
      position: absolute;
      z-index: 30;
      top: 128px;
      left: 24px;
      width: 192px;
      display: grid;
      gap: 6px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 14px 34px rgb(17 24 39 / 14%);
      padding: 8px;
    }

    .stage-menu[hidden] {
      display: none;
    }

    .stage-action-panel {
      display: grid;
      align-content: start;
      min-height: 0;
      overflow: auto;
      padding: 8px;
    }

    .stage-action-panel[hidden] {
      display: none;
    }

    .stage-action-body {
      display: grid;
      align-content: start;
      align-self: start;
      gap: 2px;
      min-width: 0;
    }

    .shell.creative-workflow .stage-action-body {
      display: none;
    }

    .creative-binder {
      display: grid;
      align-content: start;
      align-self: start;
      gap: 4px;
      min-width: 0;
      color: #1d3348;
    }

    .creative-binder[hidden] {
      display: none;
    }

    .creative-section {
      display: grid;
      gap: 2px;
      min-width: 0;
    }

    .creative-active-project {
      display: grid;
      gap: 8px;
      min-width: 0;
      margin-top: 8px;
    }

    .creative-active-project[hidden] {
      display: none;
    }

    .creative-divider {
      height: 1px;
      margin: 4px 4px 6px;
      background: #b8c8d7;
    }

    .creative-project-name {
      min-width: 0;
      overflow: hidden;
      color: #1d3348;
      font-size: var(--ui-small-font-size);
      font-weight: 650;
      line-height: 1.35;
      padding: 0 8px 2px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .creative-binder-status {
      min-height: 18px;
      color: #48627a;
      font-size: var(--ui-small-font-size);
      line-height: 1.35;
      padding: 0 8px;
    }

    .creative-tree {
      display: grid;
      gap: 3px;
      min-width: 0;
      margin-top: 2px;
    }

    .creative-tree-row {
      display: grid;
      grid-template-columns: 22px minmax(0, 1fr) 26px 26px;
      align-items: center;
      width: calc(100% - var(--creative-depth-indent, 0px));
      margin-left: var(--creative-depth-indent, 0px);
      min-height: 32px;
      border: 1px solid #c0d0df;
      border-radius: 6px;
      background: #f8fbff;
      color: #243f53;
      font: inherit;
      font-size: var(--ui-small-font-size);
      text-align: left;
      cursor: pointer;
      padding: 0 8px;
    }

    .creative-tree-row.directory {
      grid-template-columns: 18px minmax(0, 1fr) 26px 26px 18px;
      min-height: 34px;
      border-color: #18324d;
      border-radius: 999px;
      background: #1f3f5f;
      color: #ffffff;
      font-weight: 400;
      padding: 0 10px;
      box-shadow:
        0 1px 0 rgb(255 255 255 / 16%) inset,
        0 8px 18px rgb(18 48 78 / 14%);
    }

    .creative-tree-row.directory:hover,
    .creative-tree-row.directory.expanded {
      background: #254b70;
    }

    .creative-tree-row.file {
      background: #ffffff;
    }

    .creative-tree-row.active {
      border-color: #005f66;
      background: #006b73;
      color: #ffffff;
    }

    .creative-tree-row.directory.active {
      border-color: #00a1ad;
      background: #006b73;
      color: #ffffff;
    }

    .creative-tree-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 18px;
      height: 18px;
      color: #42617a;
      text-align: center;
    }

    .creative-tree-icon.folder {
      color: #8bd3dd;
    }

    .creative-tree-icon.markdown {
      color: #1c7ed6;
    }

    .creative-tree-icon.corkboard {
      color: #9f7aea;
    }

    .creative-tree-row.active .creative-tree-icon {
      color: currentColor;
    }

    .creative-tree-icon svg,
    .creative-tree-disclosure svg {
      width: 16px;
      height: 16px;
      stroke: currentColor;
    }

    .creative-tree-disclosure {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 18px;
      height: 18px;
      color: currentColor;
    }

    .creative-tree-row.directory .creative-tree-disclosure {
      position: relative;
      justify-self: end;
    }

    .creative-tree-row.directory .creative-tree-disclosure::before {
      position: absolute;
      top: 5px;
      left: 5px;
      width: 7px;
      height: 7px;
      border-right: 2px solid currentColor;
      border-bottom: 2px solid currentColor;
      transform: rotate(-45deg);
      transform-origin: center;
      content: "";
    }

    .creative-tree-row.directory.expanded .creative-tree-disclosure::before {
      top: 4px;
      transform: rotate(45deg);
    }

    .creative-tree-name {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .creative-tree-name-input {
      min-width: 0;
      width: 100%;
      border: 1px solid #66d9e8;
      border-radius: 5px;
      background: #ffffff;
      color: #16283a;
      font: inherit;
      font-size: var(--ui-small-font-size);
      padding: 3px 6px;
    }

    .creative-tree-icon-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      border: 1px solid transparent;
      border-radius: 999px;
      background: transparent;
      color: currentColor;
      cursor: pointer;
      opacity: 0.78;
      padding: 0;
    }

    .creative-tree-icon-button:hover {
      border-color: rgb(102 217 232 / 50%);
      background: rgb(255 255 255 / 18%);
      opacity: 1;
    }

    .creative-tree-icon-button.danger:hover {
      border-color: #ffb3b3;
      background: rgb(255 235 235 / 28%);
      color: #fff0f0;
    }

    .creative-tree-icon-button svg {
      width: 14px;
      height: 14px;
      fill: none;
      stroke: currentColor;
      stroke-linecap: round;
      stroke-linejoin: round;
      stroke-width: 2;
    }

    .creative-tree-actions {
      display: flex;
      gap: 6px;
      min-width: 0;
      width: calc(100% - var(--creative-depth-indent, 0px));
      margin-left: var(--creative-depth-indent, 0px);
      padding: 0 0 4px;
    }

    .creative-tree-action {
      min-height: 28px;
      border: 1px solid #b8c8d7;
      border-radius: 999px;
      background: #ffffff;
      color: #243f53;
      cursor: pointer;
      font: inherit;
      font-size: var(--ui-small-font-size);
      padding: 0 10px;
    }

    .creative-tree-action:hover {
      border-color: #1f3f5f;
      background: #eef6fb;
    }

    .stage-action-heading {
      margin: 12px 8px 4px;
      color: #48627a;
      font-size: var(--ui-small-font-size);
      font-weight: 400;
      text-transform: uppercase;
    }

    .stage-action-group {
      display: grid;
      min-width: 0;
    }

    .stage-action-stage {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 22px;
      align-items: center;
      min-height: 48px;
      width: 100%;
      border: 1px solid transparent;
      border-radius: 999px;
      background: transparent;
      color: #273f58;
      cursor: pointer;
      font: inherit;
      font-size: var(--ui-menu-font-size);
      font-weight: 400;
      gap: 8px;
      padding: 0 10px 0 16px;
      text-align: left;
    }

    .stage-action-stage:hover:not(:disabled),
    .stage-action-stage.expanded {
      background: var(--blue-surface-hover);
      color: #172a3d;
    }

    .stage-action-stage.expanded {
      font-weight: 650;
    }

    .stage-action-stage.active {
      border-color: #18324d;
      background: #1f3f5f;
      color: #ffffff;
      box-shadow:
        0 1px 0 rgb(255 255 255 / 16%) inset,
        0 8px 18px rgb(18 48 78 / 18%);
    }

    .stage-action-stage.complete {
      color: #2c5471;
    }

    .stage-action-stage.active.complete {
      color: #ffffff;
    }

    .shell.creative-workflow .creative-section > .stage-action-stage {
      border-color: #18324d;
      background: #1f3f5f;
      color: #ffffff;
      box-shadow:
        0 1px 0 rgb(255 255 255 / 16%) inset,
        0 8px 18px rgb(18 48 78 / 18%);
    }

    .shell.creative-workflow .creative-section > .stage-action-stage:hover:not(:disabled),
    .shell.creative-workflow .creative-section > .stage-action-stage.expanded {
      background: #254b70;
      color: #ffffff;
    }

    .stage-action-stage:disabled {
      color: #7d91a4;
      cursor: default;
    }

    .stage-action-label {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .stage-action-chevron {
      position: relative;
      width: 18px;
      height: 18px;
      justify-self: end;
    }

    .stage-action-chevron::before {
      position: absolute;
      top: 5px;
      left: 5px;
      width: 7px;
      height: 7px;
      border-right: 2px solid currentColor;
      border-bottom: 2px solid currentColor;
      transform: rotate(-45deg);
      transform-origin: center;
      content: "";
    }

    .stage-action-stage.expanded .stage-action-chevron::before {
      top: 4px;
      transform: rotate(45deg);
    }

    .stage-action-list {
      display: grid;
      gap: 4px;
      padding: 4px 0 8px 18px;
    }

    .recent-project-list {
      display: grid;
      gap: 4px;
      min-width: 0;
    }

    .recent-project-list[hidden] {
      display: none;
    }

    .stage-action-list[hidden] {
      display: none;
    }

    .stage-action-subgroup {
      display: grid;
      min-width: 0;
    }

    .stage-action-subgroup-trigger {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 20px;
      align-items: center;
      min-height: 38px;
      border: 0;
      border-radius: 999px;
      background: transparent;
      color: #304a63;
      cursor: pointer;
      font: inherit;
      font-size: var(--ui-menu-font-size);
      font-weight: 400;
      gap: 8px;
      padding: 0 10px 0 18px;
      text-align: left;
    }

    .stage-action-subgroup-trigger:hover,
    .stage-action-subgroup-trigger.expanded {
      background: var(--blue-surface-hover);
      color: #172a3d;
    }

    .stage-action-subgroup-trigger.expanded {
      font-weight: 650;
    }

    .stage-action-subgroup-list {
      display: grid;
      gap: 4px;
      padding: 3px 0 6px 14px;
    }

    .stage-action-button {
      min-height: 40px;
      border: 0;
      border-radius: 999px;
      background: transparent;
      color: #304a63;
      cursor: pointer;
      font: inherit;
      font-size: var(--ui-menu-font-size);
      font-weight: 400;
      text-align: left;
      padding: 0 12px 0 18px;
    }

    .stage-action-button.primary {
      background: #c2dfe5;
      color: #164f5a;
      font-weight: 400;
    }

    .stage-action-button:hover:not(:disabled) {
      background: var(--blue-surface-hover);
    }

    .stage-action-button:disabled {
      cursor: default;
      opacity: 0.5;
    }

    .stage-action-form {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      padding: 4px 8px 6px 0;
    }

    .stage-menu button {
      width: 100%;
      min-height: 38px;
      padding: 7px 10px;
      border: 1px solid transparent;
      border-radius: 6px;
      background: var(--active);
      color: white;
      cursor: pointer;
      font-family: inherit;
      font-size: var(--ui-menu-font-size);
      font-weight: 700;
    }

    .stage-menu button:disabled {
      cursor: default;
      opacity: 0.65;
    }

    .menu-branch {
      position: relative;
    }

    .menu-branch > button {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }

    .menu-branch > button::after {
      content: ">";
      color: currentColor;
      font-weight: 800;
    }

    .stage-submenu {
      position: absolute;
      z-index: 40;
      top: 0;
      left: calc(100% + 8px);
      display: grid;
      width: 220px;
      gap: 6px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 14px 34px rgb(17 24 39 / 14%);
      padding: 8px;
    }

    .stage-submenu[hidden] {
      display: none;
    }

    .repo-menu-item.active-repo {
      border-color: #005f66;
      background: #007f8a;
    }

    .document-targets {
      display: grid;
      gap: 6px;
    }

    .menu-form {
      display: grid;
      gap: 6px;
    }

    .menu-form[hidden] {
      display: none;
    }

    .menu-text-input {
      width: 100%;
      height: 38px;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0 10px;
      color: var(--ink);
      font: inherit;
    }

    .project-panel,
    .work-item-panel {
      position: absolute;
      z-index: 25;
      top: 70px;
      left: 24px;
      right: 24px;
      display: grid;
      grid-template-columns: minmax(260px, 1fr) auto auto;
      gap: 8px;
      align-items: center;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 14px 34px rgb(17 24 39 / 14%);
      padding: 10px;
    }

    .work-item-panel {
      grid-template-columns:
        minmax(220px, 1.4fr) minmax(160px, 1fr) minmax(160px, 0.8fr)
        auto auto auto;
    }

    .project-panel[hidden],
    .work-item-panel[hidden] {
      display: none;
    }

    .project-path {
      width: 100%;
      height: 38px;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0 10px;
      color: var(--ink);
      font: inherit;
    }

    .project-command,
    .directory-entry {
      height: 38px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: #ffffff;
      color: var(--ink);
      cursor: pointer;
      font: inherit;
      font-weight: 650;
    }

    .project-command.primary {
      border-color: var(--active);
      background: var(--active);
      color: #ffffff;
    }

    .project-status {
      grid-column: 1 / -1;
      min-height: 20px;
      color: var(--muted);
      font-size: var(--ui-font-size);
    }

    .work-item-select {
      background: #ffffff;
      color: var(--ink);
      border-color: var(--border);
    }

    .work-item-checkbox {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 38px;
      color: var(--ink);
      font-weight: 650;
      white-space: nowrap;
    }

    .work-item-recovery {
      grid-column: 1 / -1;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }

    .work-item-recovery[hidden] {
      display: none;
    }

    .directory-list {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 6px;
      min-height: 0;
      overflow: auto;
    }

    .directory-entry {
      overflow: hidden;
      padding: 0 10px;
      text-align: left;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .directory-entry.file {
      color: #243f53;
      font-weight: 550;
    }

    .directory-entry.selected {
      border-color: #007f8a;
      background: #effbfc;
    }

    .file-browser {
      position: fixed;
      z-index: 60;
      inset: 72px;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      gap: 10px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 24px 70px rgb(17 24 39 / 22%);
      padding: 12px;
    }

    .file-browser[hidden] {
      display: none;
    }

    .browser-toolbar {
      display: grid;
      grid-template-columns: minmax(260px, 1fr) auto auto auto;
      gap: 8px;
      align-items: center;
    }

    .browser-path {
      width: 100%;
      height: 38px;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0 10px;
      color: var(--ink);
      font: inherit;
    }

    .agent-pane {
      position: relative;
      z-index: 0;
      grid-column: 2;
      grid-row: 3;
      display: grid;
      grid-template-rows:
        minmax(0, 1fr) 7px
        var(--input-pane-height, 148px);
      min-height: 0;
      background: var(--terminal);
    }

    .agent-pane.noninteractive {
      grid-template-rows: minmax(0, 1fr);
    }

    .output-workbench {
      display: grid;
      grid-template-columns:
        minmax(0, 1fr) 7px
        minmax(260px, var(--right-pane-width, 360px));
      min-height: 0;
      background: var(--terminal);
    }

    .output-workbench.side-popped {
      grid-template-columns: minmax(0, 1fr);
    }

    .output-workbench.pane-layout-enabled {
      position: relative;
      display: block;
      min-width: 0;
      overflow: hidden;
    }

    .pane-layout-root,
    .pane-layout-split,
    .pane-layout-leaf {
      min-width: 0;
      min-height: 0;
      width: 100%;
      height: 100%;
    }

    .pane-layout-split {
      display: grid;
      overflow: hidden;
    }

    .pane-layout-leaf {
      position: relative;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      overflow: hidden;
      background: var(--terminal);
      container-type: inline-size;
    }

    .pane-layout-leaf[hidden],
    .pane-layout-split[hidden],
    .pane-layout-divider[hidden] {
      display: none;
    }

    .pane-layout-toolbar {
      display: grid;
      grid-template-columns: minmax(76px, 1fr) 28px 28px 28px 28px;
      gap: 4px;
      align-items: center;
      min-width: 0;
      height: 32px;
      border-bottom: 1px solid #2a3142;
      background: #151d2b;
      padding: 3px 5px;
    }

    .pane-layout-kind {
      min-width: 0;
      width: 100%;
      height: 24px;
      border: 1px solid #364156;
      border-radius: 4px;
      background: #1d2638;
      color: #d8e3f4;
      font: inherit;
      font-size: var(--ui-small-font-size);
      padding: 0 5px;
    }

    .pane-layout-command {
      position: relative;
      width: 28px;
      height: 24px;
      border: 1px solid #364156;
      border-radius: 4px;
      background: #1d2638;
      color: #d8e3f4;
      cursor: pointer;
      font: inherit;
      font-size: 16px;
      line-height: 1;
    }

    .pane-layout-command:hover:not(:disabled) {
      border-color: #4e7f9d;
      background: #22314a;
    }

    .pane-layout-command:disabled {
      cursor: default;
      opacity: 0.35;
    }

    .pane-layout-command.split-right::before,
    .pane-layout-command.split-down::before {
      position: absolute;
      inset: 5px 6px;
      border: 1px solid currentcolor;
      border-radius: 1px;
      content: "";
    }

    .pane-layout-command.split-right::after,
    .pane-layout-command.split-down::after {
      position: absolute;
      background: currentcolor;
      content: "";
    }

    .pane-layout-command.split-right::after {
      top: 5px;
      bottom: 5px;
      left: 13px;
      width: 1px;
    }

    .pane-layout-command.split-down::after {
      right: 6px;
      bottom: 11px;
      left: 6px;
      height: 1px;
    }

    .pane-layout-empty {
      display: grid;
      place-items: center;
      min-width: 0;
      min-height: 0;
      color: #77849a;
      font-size: var(--ui-small-font-size);
    }

    .pane-layout-divider {
      min-width: 0;
      min-height: 0;
      touch-action: none;
      background: #253044;
    }

    .pane-layout-divider.row {
      cursor: col-resize;
    }

    .pane-layout-divider.column {
      cursor: row-resize;
    }

    .pane-layout-divider:hover,
    .pane-layout-divider.resizing {
      background: #3a78a0;
    }

    .pane-layout-corner {
      position: absolute;
      z-index: 9;
      width: 14px;
      height: 14px;
      border: 0;
      background: transparent;
      color: #60758d;
      cursor: nesw-resize;
      touch-action: none;
    }

    .pane-layout-corner.top-right {
      top: 32px;
      right: 0;
    }

    .pane-layout-corner.bottom-left {
      bottom: 0;
      left: 0;
    }

    .pane-layout-corner::before {
      position: absolute;
      width: 7px;
      height: 7px;
      content: "";
    }

    .pane-layout-corner.top-right::before {
      top: 2px;
      right: 2px;
      border-top: 2px solid currentcolor;
      border-right: 2px solid currentcolor;
    }

    .pane-layout-corner.bottom-left::before {
      bottom: 2px;
      left: 2px;
      border-bottom: 2px solid currentcolor;
      border-left: 2px solid currentcolor;
    }

    .pane-layout-corner:hover,
    .pane-layout-corner:focus-visible,
    .pane-layout-leaf.splitting .pane-layout-corner {
      color: #66d9e8;
      outline: none;
    }

    .pane-layout-split-preview {
      position: absolute;
      z-index: 8;
      border: 2px solid #66d9e8;
      background: rgb(31 111 139 / 24%);
      pointer-events: none;
    }

    .pane-layout-split-preview[hidden] {
      display: none;
    }

    body.pane-layout-splitting {
      cursor: nesw-resize;
      user-select: none;
    }

    body.pane-layout-splitting-row {
      cursor: col-resize;
    }

    body.pane-layout-splitting-column {
      cursor: row-resize;
    }

    @container (max-width: 180px) {
      .pane-layout-toolbar {
        grid-template-columns: minmax(42px, 1fr) 24px 24px 24px;
        gap: 2px;
      }

      .pane-layout-command {
        width: 24px;
      }

      .pane-layout-command.reset-layout {
        display: none;
      }
    }

    @container (max-width: 138px) {
      .pane-layout-toolbar {
        grid-template-columns: minmax(36px, 1fr) 24px 24px;
      }

      .pane-layout-command.split-down {
        display: none;
      }
    }

    .left-output-pane {
      display: grid;
      grid-template-rows: minmax(0, 1fr);
      min-height: 0;
      min-width: 0;
      background: var(--terminal);
    }

    .left-output-pane.shell-visible {
      grid-template-rows:
        minmax(0, 1fr) 7px
        minmax(180px, var(--shell-pane-height, 260px));
    }

    .output-split {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      min-height: 0;
      background: var(--terminal);
    }

    .output-split.artifact-visible {
      grid-template-columns:
        minmax(0, 1fr) 7px
        minmax(320px, var(--artifact-pane-width, 42%));
    }

    .output-split.split {
      grid-template-columns:
        minmax(0, 1fr) 7px
        minmax(280px, var(--progress-pane-width, 42%));
    }

    .output-split.split.artifact-visible {
      grid-template-columns:
        minmax(0, 1fr) 7px
        minmax(320px, var(--artifact-pane-width, 36%)) 7px
        minmax(280px, var(--progress-pane-width, 30%));
    }

    .output-split.agent-popped.artifact-visible:not(.split),
    .output-split.agent-popped.split:not(.artifact-visible) {
      grid-template-columns: minmax(0, 1fr);
    }

    .output-split.agent-popped.split.artifact-visible {
      grid-template-columns:
        minmax(320px, 1fr) 7px
        minmax(280px, var(--progress-pane-width, 34%));
    }

    .shell.creative-workflow .output-workbench {
      grid-template-columns:
        minmax(0, 1fr) 7px
        minmax(220px, var(--right-pane-width, 320px));
    }

    .shell.creative-workflow .output-split.artifact-visible {
      grid-template-columns:
        minmax(260px, 1fr) 7px
        minmax(360px, var(--artifact-pane-width, 54%));
    }

    .shell.creative-workflow .artifact-preview-pane {
      min-width: 0;
    }

    .shell.creative-workflow .side-pane {
      grid-template-rows:
        minmax(120px, var(--scratch-pane-height, 1fr)) 7px
        minmax(96px, 140px);
    }

    .shell.creative-workflow .project-status-pane {
      min-height: 96px;
    }

    .output-resize-handle,
    .artifact-pane-resize-handle,
    .shell-pane-divider {
      min-height: 0;
      background: #202838;
      cursor: col-resize;
    }

    .shell-pane-divider {
      cursor: row-resize;
    }

    .workbench-resize-handle {
      min-height: 0;
      background: #253044;
      cursor: col-resize;
    }

    .output-resize-handle:hover,
    .output-split.resizing .output-resize-handle,
    .workbench-resize-handle:hover,
    .output-workbench.resizing .workbench-resize-handle,
    .side-pane-resize-handle:hover,
    .side-pane.resizing .side-pane-resize-handle,
    .artifact-pane-resize-handle:hover,
    .output-split.resizing-artifact .artifact-pane-resize-handle,
    .shell-pane-divider:hover,
    .left-output-pane.resizing-shell .shell-pane-divider {
      background: #3a78a0;
    }

    .input-resize-handle {
      min-height: 0;
      background: #202838;
      cursor: row-resize;
    }

    .input-resize-handle:hover,
    .agent-pane.resizing-input .input-resize-handle {
      background: #3a78a0;
    }

    .input-resize-handle[hidden],
    .output-resize-handle[hidden],
    .workbench-resize-handle[hidden],
    .side-pane-resize-handle[hidden],
    .shell-pane-divider[hidden] {
      display: none;
    }

    .terminal-pane,
    .artifact-preview-pane {
      display: grid;
      min-height: 0;
      min-width: 0;
      overflow: hidden;
      background: var(--terminal);
    }

    .terminal-pane {
      grid-template-rows: auto minmax(0, 1fr);
    }

    .artifact-preview-pane {
      grid-template-rows: minmax(0, 1fr);
    }

    .terminal-pane[hidden],
    .artifact-preview-pane[hidden],
    .artifact-pane-resize-handle[hidden] {
      display: none;
    }

    .pane-header,
    .side-pane-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      min-height: 34px;
      border-bottom: 1px solid #2a3142;
      padding: 0 10px 0 12px;
      color: #aab8cf;
      font-size: var(--ui-small-font-size);
      font-weight: 400;
      text-transform: uppercase;
    }

    .pane-title {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .pane-popout-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 42px;
      height: 26px;
      border: 1px solid #364156;
      border-radius: 6px;
      background: #1d2638;
      color: #d8e3f4;
      cursor: pointer;
      font: inherit;
      font-size: var(--ui-small-font-size);
      line-height: 1;
    }

    .pane-popout-button:hover {
      border-color: #4e7f9d;
      background: #22314a;
    }

    .pane-popout-button.active {
      border-color: #66d9e8;
      background: #1f6f8b;
      color: #ffffff;
    }

    .pane-actions,
    .document-zoom-controls,
    .pane-font-controls {
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
    }

    .document-zoom-controls {
      color: #d8e3f4;
    }

    .document-target-switcher {
      min-width: 160px;
      max-width: 320px;
      height: 30px;
      border: 1px solid #364156;
      border-radius: 6px;
      background: #1d2638;
      color: #d8e3f4;
      cursor: pointer;
      font: inherit;
      font-size: var(--ui-small-font-size);
      font-weight: 600;
      padding: 0 8px;
    }

    .document-target-switcher:disabled {
      cursor: default;
      opacity: 0.82;
    }

    .document-export-format {
      min-width: 92px;
      height: 26px;
      border: 1px solid #364156;
      border-radius: 6px;
      background: #1d2638;
      color: #d8e3f4;
      cursor: pointer;
      font: inherit;
      font-size: var(--ui-small-font-size);
      font-weight: 750;
    }

    .document-zoom-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 26px;
      border: 1px solid #364156;
      border-radius: 6px;
      background: #1d2638;
      color: #d8e3f4;
      cursor: pointer;
      font: inherit;
      font-size: var(--ui-small-font-size);
      font-weight: 750;
      line-height: 1;
    }

    .pane-font-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 28px;
      height: 26px;
      border: 1px solid #364156;
      border-radius: 6px;
      background: #1d2638;
      color: #d8e3f4;
      cursor: pointer;
      font: inherit;
      font-size: var(--ui-small-font-size);
      font-weight: 750;
      line-height: 1;
    }

    .pane-font-reset {
      min-width: 34px;
    }

    .document-zoom-button:hover:not(:disabled) {
      border-color: #4e7f9d;
      background: #22314a;
    }

    .pane-font-button:hover:not(:disabled) {
      border-color: #4e7f9d;
      background: #22314a;
    }

    .document-zoom-button:disabled,
    .pane-font-button:disabled {
      cursor: default;
      opacity: 0.45;
    }

    .document-zoom-level,
    .pane-font-level {
      min-width: 42px;
      text-align: center;
      color: #aab8cf;
      font-size: var(--ui-small-font-size);
      font-weight: 750;
    }

    .artifact-preview-stack {
      display: grid;
      grid-template-rows: minmax(0, 1fr);
      min-height: 0;
      min-width: 0;
    }

    .artifact-preview-stack.split {
      grid-template-rows: minmax(0, 1fr) 1px minmax(0, 1fr);
    }

    .artifact-preview-item {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      min-height: 0;
      min-width: 0;
      overflow: hidden;
      background: var(--terminal);
    }

    .artifact-preview-divider {
      min-height: 1px;
      background: #2a3142;
    }

    .agent-output,
    .progress-output,
    .shell-output {
      min-height: 0;
      min-width: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      padding: 0;
      color: var(--terminal-text);
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      line-height: 1.45;
      white-space: pre-wrap;
    }

    .agent-output {
      font-size: var(--agent-output-font-size, var(--terminal-font-size));
    }

    .progress-output {
      font-size: var(--progress-output-font-size, var(--terminal-font-size));
    }

    .shell-output {
      font-size: var(--project-shell-font-size, var(--terminal-font-size));
    }

    .progress-output,
    .shell-output {
      border-left: 0;
    }

    .agent-output .xterm,
    .progress-output .xterm,
    .shell-output .xterm {
      width: 100%;
      height: 100%;
      box-sizing: border-box;
      padding: 10px 12px;
    }

    .agent-output .xterm-viewport,
    .progress-output .xterm-viewport,
    .shell-output .xterm-viewport {
      background: var(--terminal);
    }

    .agent-output .system,
    .progress-output .system,
    .shell-output .system {
      color: #8bd8ca;
    }

    .agent-output .error,
    .progress-output .error,
    .shell-output .error {
      color: #ffb4a9;
    }

    .side-pane {
      display: grid;
      grid-template-rows:
        minmax(120px, var(--scratch-pane-height, 50%)) 7px
        minmax(120px, 1fr);
      min-height: 0;
      min-width: 0;
      border-left: 1px solid #2a3142;
      background: #111827;
    }

    .side-pane.scratch-popped,
    .side-pane.status-popped {
      grid-template-rows: minmax(0, 1fr);
    }

    .side-pane-resize-handle {
      min-height: 0;
      background: #253044;
      cursor: row-resize;
    }

    .scratch-pane,
    .project-status-pane {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      min-height: 0;
      min-width: 0;
    }

    .scratch-pane[hidden],
    .project-status-pane[hidden] {
      display: none;
    }

    .scratch-pad,
    .project-status-output {
      min-height: 0;
      width: 100%;
      margin: 0;
      border: 0;
      background: #10141f;
      color: var(--terminal-text);
      padding: 10px 12px;
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      line-height: 1.45;
      outline: none;
      white-space: pre-wrap;
    }

    .scratch-pad {
      font-size: var(--scratch-pad-font-size, var(--terminal-font-size));
    }

    .project-status-output {
      font-size: var(--project-status-font-size, var(--terminal-font-size));
    }

    .scratch-pad {
      display: block;
      resize: none;
    }

    .project-status-output {
      overflow: auto;
    }

    .artifact-preview-frame {
      width: 100%;
      height: 100%;
      min-height: 0;
      border: 0;
      background: var(--terminal);
      color-scheme: dark;
      opacity: 1;
      transition: opacity 80ms ease;
    }

    .artifact-preview-frame.loading {
      opacity: 0;
    }

    .input-pane {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      grid-template-columns:
        minmax(260px, 1fr) 7px
        minmax(160px, var(--input-actions-width, 196px));
      min-height: 0;
      gap: 8px;
      border-top: 1px solid #2a3142;
      background: #151b29;
      padding: 0 12px 12px;
    }

    .input-pane-header {
      grid-column: 1 / -1;
      margin: 0 -12px;
      background: #151b29;
    }

    .input-pane[hidden] {
      display: none;
    }

    .agent-input {
      display: block;
      width: 100%;
      height: 100%;
      min-height: 0;
      resize: none;
      border: 1px solid #364156;
      border-radius: 8px;
      background: #0f1420;
      color: var(--terminal-text);
      padding: 12px;
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: var(--agent-input-font-size, var(--terminal-font-size));
      line-height: 1.45;
    }

    .agent-input:disabled {
      color: #7c879a;
      background: #121827;
      cursor: default;
    }

    .input-action-resize-handle {
      min-height: 0;
      border-radius: 4px;
      background: #253044;
      cursor: col-resize;
    }

    .input-action-resize-handle:hover,
    .input-pane.resizing-actions .input-action-resize-handle {
      background: #3a78a0;
    }

    .agent-actions {
      display: grid;
      grid-template-rows: auto auto;
      min-height: 0;
      min-width: 0;
      gap: 8px;
      align-self: stretch;
      overflow: auto;
      scrollbar-width: thin;
    }

    .session-control {
      min-width: 0;
    }

    .agent-session-indicator {
      width: 9px;
      height: 9px;
      margin: 0 8px;
      border-radius: 999px;
      background: #9aa7b6;
      box-shadow: 0 0 0 3px rgb(154 167 182 / 14%);
      flex: 0 0 auto;
    }

    .agent-session-indicator.running {
      background: #0f766e;
      box-shadow: 0 0 0 3px rgb(15 118 110 / 16%);
    }

    .agent-session-indicator.error {
      background: #b42318;
      box-shadow: 0 0 0 3px rgb(180 35 24 / 14%);
    }

    .agent-session-indicator.done {
      background: #456179;
      box-shadow: 0 0 0 3px rgb(69 97 121 / 14%);
    }

    .session-switcher {
      flex: 1 1 auto;
      width: 100%;
      height: 100%;
      min-width: 0;
      font-size: var(--ui-font-size);
      font-weight: 400;
      padding: 0 32px 0 0;
    }

    .session-switcher:disabled {
      color: #526a82;
      cursor: default;
    }

    .terminal-font-controls {
      gap: 0;
    }

    .terminal-font-button,
    .agent-action-button {
      border-radius: 8px;
      cursor: pointer;
      font-family: inherit;
      font-size: var(--ui-font-size);
      font-weight: 400;
    }

    .terminal-font-button {
      align-self: stretch;
      flex: 0 0 calc(var(--ui-font-size) + 31px);
      min-width: 40px;
      border-radius: 0;
    }

    .terminal-font-button + .terminal-font-value,
    .terminal-font-value + .terminal-font-button {
      border-left: 1px solid #a8bbcd;
    }

    .terminal-font-value {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      align-self: stretch;
      flex: 1 1 auto;
      min-width: 54px;
      color: #2d465f;
      font-size: var(--ui-small-font-size);
      font-weight: 400;
      background: #d6e6f3;
    }

    .agent-action-button {
      min-height: 38px;
      height: calc(var(--ui-font-size) + 25px);
    }

    .agent-interrupt {
      border: 1px solid #73342f;
      background: #3b1718;
      color: #ffd9d5;
    }

    .agent-link {
      border: 1px solid #305e6f;
      background: #12303b;
      color: #d5f4ff;
    }

    .agent-action-button:disabled {
      border-color: #303746;
      background: #171d2b;
      color: #667085;
      cursor: default;
    }

    @media (max-width: 760px) {
      .shell {
        grid-template-rows: 212px minmax(0, 1fr);
      }

      .workflow-pane {
        padding: 16px;
      }

      .stage-scroll {
        margin: 0 -16px;
        padding: 0 16px 12px;
      }

      .connection {
        right: 16px;
      }

      .stage-menu {
        left: 16px;
        top: 120px;
      }

      .stage-submenu {
        position: static;
        width: auto;
        margin-top: 6px;
      }

      .project-panel,
      .work-item-panel {
        left: 16px;
        right: 16px;
        top: 168px;
        grid-template-columns: 1fr;
      }

      .file-browser {
        inset: 40px 16px;
      }

      .browser-toolbar {
        grid-template-columns: 1fr;
      }

      .output-workbench {
        grid-template-columns: minmax(0, 1fr);
        grid-template-rows:
          minmax(0, 1fr) 7px
          minmax(200px, var(--right-pane-height, 38%));
      }

      .workbench-resize-handle {
        cursor: row-resize;
      }

      .side-pane {
        border-top: 1px solid #2a3142;
        border-left: 0;
      }

      .output-split.artifact-visible {
        grid-template-columns: minmax(0, 1fr);
        grid-template-rows:
          minmax(0, 1fr) 7px
          minmax(220px, var(--artifact-pane-height, 45%));
      }

      .output-split.split {
        grid-template-columns: minmax(0, 1fr);
        grid-template-rows:
          minmax(0, 1fr) 7px
          minmax(180px, var(--progress-pane-height, 45%));
      }

      .output-split.split.artifact-visible {
        grid-template-columns: minmax(0, 1fr);
        grid-template-rows:
          minmax(0, 1fr) 7px
          minmax(220px, var(--artifact-pane-height, 38%)) 7px
          minmax(180px, var(--progress-pane-height, 32%));
      }

      .output-split.agent-popped.split.artifact-visible {
        grid-template-rows:
          minmax(220px, 1fr) 7px
          minmax(180px, var(--progress-pane-height, 35%));
      }

      .output-resize-handle,
      .artifact-pane-resize-handle {
        cursor: row-resize;
      }

      .progress-output {
        border-top: 0;
      }

      .input-pane {
        grid-template-columns: minmax(0, 1fr);
        grid-template-rows: auto minmax(0, 1fr) auto;
      }

      .input-action-resize-handle {
        display: none;
      }

      .agent-actions {
        grid-template-columns: minmax(0, 1fr);
      }
    }
  </style>
</head>
<body>
  <div
    id="splashOverlay"
    class="splash-overlay"
    role="dialog"
    aria-label="ElectroBoy splash screen"
    hidden
  >
    <div class="splash-card" role="document">
      <img
        id="splashImage"
        src="__SPLASH_IMAGE_ROUTE__"
        alt="I am Electroboy"
        draggable="false"
      >
      <button
        id="closeSplash"
        class="splash-close"
        type="button"
        title="Close splash screen"
        aria-label="Close splash screen"
      >&times;</button>
    </div>
  </div>
  <main class="shell">
    <svg
      class="stage-icon-defs"
      aria-hidden="true"
      focusable="false"
    >
      <symbol id="panelLeftCloseIcon" viewBox="0 0 24 24">
        <rect width="18" height="18" x="3" y="3" rx="2"></rect>
        <path d="M9 3v18"></path>
        <path d="m16 15-3-3 3-3"></path>
      </symbol>
      <symbol id="panelLeftOpenIcon" viewBox="0 0 24 24">
        <rect width="18" height="18" x="3" y="3" rx="2"></rect>
        <path d="M9 3v18"></path>
        <path d="m14 9 3 3-3 3"></path>
      </symbol>
      <symbol id="stageDoubleArrowIcon" viewBox="0 0 58 58">
        <path
          fill="currentColor"
          d="M57.484,28.125l-19-10.5c-0.311-0.171-0.687-0.165-0.992,0.014C37.187,17.818,37,18.146,37,18.5v5h-6c-0.552,0-1,0.448-1,1v9c0,0.552,0.448,1,1,1h6v5c0,0.354,0.187,0.682,0.492,0.861C37.648,40.453,37.824,40.5,38,40.5c0.167,0,0.333-0.042,0.484-0.125l19-10.5C57.802,29.699,58,29.364,58,29S57.802,28.301,57.484,28.125z M39,37.805V33.5c0-0.552-0.448-1-1-1h-6v-7h6c0.552,0,1-0.448,1-1v-4.305L54.933,29L39,37.805z"
        />
        <path
          fill="currentColor"
          d="M27,23.5h-6v-5c0-0.354-0.187-0.682-0.492-0.861c-0.305-0.179-0.682-0.185-0.992-0.014l-19,10.5C0.198,28.301,0,28.636,0,29c0,0.364,0.198,0.699,0.516,0.875l19,10.5C19.667,40.458,19.833,40.5,20,40.5c0.176,0,0.352-0.046,0.508-0.139C20.813,40.182,21,39.854,21,39.5v-5h6c0.552,0,1-0.448,1-1v-9C28,23.948,27.552,23.5,27,23.5z M26,32.5h-6c-0.552,0-1,0.448-1,1v4.305L3.067,29L19,20.195V24.5c0,0.552,0.448,1,1,1h6V32.5z"
        />
      </symbol>
    </svg>
    <aside
      id="workflowSideSheet"
      class="workflow-side-sheet"
      aria-label="Workflow actions"
    >
      <header class="side-sheet-header">
        <button
          id="toggleWorkflowSideSheet"
          class="side-sheet-toggle"
          type="button"
          aria-label="Collapse workflow side sheet"
          title="Collapse workflow side sheet"
        >
          <svg
            class="side-sheet-toggle-icon side-sheet-toggle-icon-close"
            aria-hidden="true"
            focusable="false"
          >
            <use href="#panelLeftCloseIcon"></use>
          </svg>
          <svg
            class="side-sheet-toggle-icon side-sheet-toggle-icon-open"
            aria-hidden="true"
            focusable="false"
          >
            <use href="#panelLeftOpenIcon"></use>
          </svg>
        </button>
        <select
          id="workflowModeSelect"
          class="workflow-mode-select"
          aria-label="Workflow type"
        >
          <option value="software">Software engineering</option>
          <option value="creative">Creative writing</option>
        </select>
      </header>
      <nav
        id="stageActionPanel"
        class="stage-action-panel"
        aria-label="Workflow stage actions"
      >
        <div id="stageActionBody" class="stage-action-body"></div>
        <section
          id="creativeBinder"
          class="creative-binder"
          aria-label="Creative writing binder"
          hidden
        >
          <div class="creative-section">
            <button
              id="creativeProjectMenuButton"
              class="stage-action-stage"
              type="button"
              aria-expanded="false"
            >
              <span class="stage-action-label">Project</span>
              <span class="stage-action-chevron" aria-hidden="true"></span>
            </button>
            <div
              id="creativeProjectActions"
              class="stage-action-list"
              role="group"
              hidden
            >
              <button id="creativeOpenProject" class="stage-action-button" type="button">
                Open
              </button>
              <button id="creativeNewProject" class="stage-action-button" type="button">
                New
              </button>
              <div
                id="creativeRecentProjects"
                class="recent-project-list"
                role="group"
                hidden
              ></div>
              <button id="creativeCloseProject" class="stage-action-button" type="button" disabled>
                Close
              </button>
            </div>
          </div>
          <div
            id="creativeActiveProjectSection"
            class="creative-active-project"
            hidden
          >
            <div class="creative-divider" aria-hidden="true"></div>
            <div id="creativeProjectName" class="creative-project-name"></div>
            <div class="creative-section">
              <button
                id="creativeAgentMenuButton"
                class="stage-action-stage"
                type="button"
                aria-expanded="false"
              >
                <span class="stage-action-label">Agent</span>
                <span class="stage-action-chevron" aria-hidden="true"></span>
              </button>
              <div
                id="creativeAgentActions"
                class="stage-action-list"
                role="group"
                hidden
              >
                <button
                  id="creativeStartAgent"
                  class="stage-action-button primary"
                  type="button"
                  disabled
                >
                  Start
                </button>
              </div>
            </div>
            <div id="creativeTree" class="creative-tree" role="tree"></div>
          </div>
        </section>
      </nav>
    </aside>
    <section class="workflow-pane" aria-label="Project workflow">
      <div id="connection" class="connection"></div>
      <div class="workflow-toolbar" aria-label="Agent controls">
        <div class="splash-control toolbar-control-group">
          <span class="toolbar-control-label">Splash</span>
          <button
            id="showSplash"
            class="toolbar-command-button"
            type="button"
            title="Show the ElectroBoy splash screen"
            aria-label="Show the ElectroBoy splash screen"
          >
            Show
          </button>
        </div>
        <div class="terminal-font-controls toolbar-control-group" aria-label="UI font size">
          <span class="toolbar-control-label">Text</span>
          <button
            id="decreaseTerminalFont"
            class="terminal-font-button"
            type="button"
            title="Decrease font size"
            aria-label="Decrease font size"
          >
            A-
          </button>
          <span
            id="terminalFontValue"
            class="terminal-font-value"
            aria-live="polite"
          >15px</span>
          <button
            id="increaseTerminalFont"
            class="terminal-font-button"
            type="button"
            title="Increase font size"
            aria-label="Increase font size"
          >
            A+
          </button>
        </div>
        <div class="session-control toolbar-control-group">
          <label class="toolbar-control-label" for="sessionSwitcher">Agent</label>
          <span
            id="agentSessionIndicator"
            class="agent-session-indicator"
            aria-hidden="true"
          ></span>
          <select
            id="sessionSwitcher"
            class="session-switcher"
            disabled
            aria-label="Select Agent"
          ></select>
        </div>
        <div class="shell-control toolbar-control-group">
          <span class="toolbar-control-label">Shell</span>
          <button
            id="toggleProjectShellPane"
            class="toolbar-command-button"
            type="button"
            disabled
            title="Open or hide the project shell"
            aria-label="Open or hide the project shell"
          >
            Shell
          </button>
        </div>
      </div>
      <div class="stage-scroll">
        <div class="stage-graph" aria-label="Project stages">
          <button class="stage-node active" type="button" data-stage="project">
            project
          </button>
          <span class="stage-connector" aria-hidden="true">
            <svg
              class="stage-connector-icon"
              viewBox="0 0 58 58"
              focusable="false"
            >
              <use href="#stageDoubleArrowIcon"></use>
            </svg>
          </span>
          <button
            class="stage-node disabled"
            type="button"
            data-stage="requirements"
            disabled
          >
            requirements
          </button>
          <span class="stage-connector" aria-hidden="true">
            <svg
              class="stage-connector-icon"
              viewBox="0 0 58 58"
              focusable="false"
            >
              <use href="#stageDoubleArrowIcon"></use>
            </svg>
          </span>
          <button class="stage-node disabled" type="button" data-stage="design" disabled>
            design
          </button>
          <span class="stage-connector" aria-hidden="true">
            <svg
              class="stage-connector-icon"
              viewBox="0 0 58 58"
              focusable="false"
            >
              <use href="#stageDoubleArrowIcon"></use>
            </svg>
          </span>
          <button class="stage-node disabled" type="button" data-stage="design-review" disabled>
            design-review
          </button>
          <span class="stage-connector" aria-hidden="true">
            <svg
              class="stage-connector-icon"
              viewBox="0 0 58 58"
              focusable="false"
            >
              <use href="#stageDoubleArrowIcon"></use>
            </svg>
          </span>
          <button
            class="stage-node disabled"
            type="button"
            data-stage="implementation-plan"
            disabled
          >
            implementation-plan
          </button>
          <span class="stage-connector" aria-hidden="true">
            <svg
              class="stage-connector-icon"
              viewBox="0 0 58 58"
              focusable="false"
            >
              <use href="#stageDoubleArrowIcon"></use>
            </svg>
          </span>
          <button class="stage-node disabled" type="button" data-stage="code" disabled>
            code
          </button>
          <span class="stage-connector" aria-hidden="true">
            <svg
              class="stage-connector-icon"
              viewBox="0 0 58 58"
              focusable="false"
            >
              <use href="#stageDoubleArrowIcon"></use>
            </svg>
          </span>
          <button class="stage-node disabled" type="button" data-stage="test-plan" disabled>
            test-plan
          </button>
          <span class="stage-connector" aria-hidden="true">
            <svg
              class="stage-connector-icon"
              viewBox="0 0 58 58"
              focusable="false"
            >
              <use href="#stageDoubleArrowIcon"></use>
            </svg>
          </span>
          <button class="stage-node disabled" type="button" data-stage="validate" disabled>
            validate
          </button>
          <span class="stage-spacer" aria-hidden="true"></span>
          <button class="stage-node disabled sidecar" type="button" data-stage="document" disabled>
            document
          </button>
        </div>
      </div>
      <div id="projectMenu" class="stage-menu" hidden>
        <button id="openProject" type="button">Open project</button>
        <button id="newProject" type="button">New project</button>
        <div id="metaProjectBranch" class="menu-branch">
          <button
            id="metaProjectMenuButton"
            type="button"
            aria-haspopup="true"
            aria-expanded="false"
          >
            Meta project
          </button>
          <div id="metaProjectSubmenu" class="stage-submenu" hidden>
            <button id="openMetaProject" type="button">Open</button>
            <button id="newMetaProject" type="button">New</button>
            <button id="addMetaRepository" type="button" disabled>Add repo</button>
            <div id="startMetaRepositoryBranch" class="menu-branch">
              <button
                id="startMetaRepository"
                type="button"
                disabled
                aria-haspopup="true"
                aria-expanded="false"
              >
                Start repo
              </button>
              <div id="startMetaRepositorySubmenu" class="stage-submenu" hidden></div>
            </div>
            <div id="removeMetaRepositoryBranch" class="menu-branch">
              <button
                id="removeMetaRepository"
                type="button"
                disabled
                aria-haspopup="true"
                aria-expanded="false"
              >
                Remove repo
              </button>
              <div id="removeMetaRepositorySubmenu" class="stage-submenu" hidden></div>
            </div>
          </div>
        </div>
        <div id="workItemBranch" class="menu-branch">
          <button
            id="workItemMenuButton"
            type="button"
            disabled
            aria-haspopup="true"
            aria-expanded="false"
          >
            Project
          </button>
          <div id="workItemSubmenu" class="stage-submenu" hidden>
            <div id="switchFeatureWorkItemBranch" class="menu-branch">
              <button
                id="switchFeatureWorkItem"
                type="button"
                disabled
                aria-haspopup="true"
                aria-expanded="false"
              >
                Features
              </button>
              <div id="switchFeatureWorkItemSubmenu" class="stage-submenu" hidden></div>
            </div>
            <button id="newFeatureWorkItem" type="button" disabled>Add feature</button>
            <button id="newBugWorkItem" type="button" disabled>Add bug resolution</button>
            <div id="switchBugWorkItemBranch" class="menu-branch">
              <button
                id="switchBugWorkItem"
                type="button"
                disabled
                aria-haspopup="true"
                aria-expanded="false"
              >
                Bug resolutions
              </button>
              <div id="switchBugWorkItemSubmenu" class="stage-submenu" hidden></div>
            </div>
          </div>
        </div>
        <button id="deactivateProject" type="button" disabled>Deactivate</button>
      </div>
      <div id="requirementsMenu" class="stage-menu" hidden>
        <button
          id="setRequirementsStage"
          type="button"
          title="Move the workflow to requirements without starting an agent."
        >Set stage</button>
        <button
          id="startRequirements"
          type="button"
          title="Launch or resume the interactive requirements authoring agent."
        >Start</button>
        <button
          id="approveRequirements"
          type="button"
          title="Record requirements approval and advance the workflow."
        >Approve</button>
        <button
          id="skipRequirementsApproval"
          type="button"
          title="Force requirements approval when the operator accepts the risk."
        >Skip approval</button>
      </div>
      <div id="designMenu" class="stage-menu" hidden>
        <button
          id="setDesignStage"
          type="button"
          title="Move the workflow to design without starting an agent."
        >Set stage</button>
        <button
          id="startDesign"
          type="button"
          title="Launch or resume the interactive design authoring agent."
        >Start</button>
        <button
          id="completeDesign"
          type="button"
          title="Finish design authoring and move to design review."
        >Complete</button>
      </div>
      <div id="designReviewMenu" class="stage-menu" hidden>
        <button
          id="setDesignReviewStage"
          type="button"
          title="Move the workflow to design-review without starting a review."
        >Set stage</button>
        <button
          id="startAutomaticDesignReview"
          type="button"
          title="Run the non-interactive design review and design-update loop."
        >Run automatic review</button>
        <button
          id="startInteractiveDesignReview"
          type="button"
          title="Open an interactive design-review agent session."
        >Run interactive review</button>
        <button
          id="stopDesignReview"
          type="button"
          title="Stop the running design-review agent or review loop."
        >Stop review</button>
        <button
          id="approveDesignReview"
          type="button"
          title="Approve the reviewed design and advance to implementation planning."
        >Approve</button>
        <button
          id="skipDesignReviewApproval"
          type="button"
          title="Force design approval when the operator accepts the risk."
        >Skip approval</button>
      </div>
      <div id="implementationPlanMenu" class="stage-menu" hidden>
        <button
          id="setImplementationPlanStage"
          type="button"
          title="Move the workflow to implementation-plan without starting an agent."
        >Set stage</button>
        <button
          id="startImplementationPlan"
          type="button"
          title="Launch or resume the interactive implementation-plan agent."
        >Start</button>
        <button
          id="approveImplementationPlan"
          type="button"
          title="Approve the implementation plan and advance to code."
        >Approve</button>
        <button
          id="skipImplementationPlanApproval"
          type="button"
          title="Force plan approval when the operator accepts the risk."
        >Skip approval</button>
      </div>
      <div id="codeMenu" class="stage-menu" hidden>
        <button
          id="setCodeStage"
          type="button"
          title="Move the workflow to code without starting implementation."
        >Set stage</button>
        <button
          id="startAutomaticCode"
          type="button"
          title="Run the non-interactive coding and review cycle."
        >Start automatic</button>
        <button
          id="startInteractiveCode"
          type="button"
          title="Open an interactive coding agent session."
        >Start interactive</button>
        <button
          id="startCodeAdHocAgent"
          type="button"
          disabled
          title="Start a plain interactive agent without staged workflow instructions."
        >Start ad-hoc</button>
        <button
          id="stopCode"
          type="button"
          title="Stop the running coding agent."
        >Stop</button>
        <button
          id="approveCode"
          type="button"
          title="Approve implementation and advance to test planning."
        >Approve</button>
        <button
          id="skipCodeApproval"
          type="button"
          title="Force code approval when the operator accepts the risk."
        >Skip approval</button>
      </div>
      <div id="testPlanMenu" class="stage-menu" hidden>
        <button
          id="setTestPlanStage"
          type="button"
          title="Move the workflow to test-plan without starting an agent."
        >Set stage</button>
        <button
          id="startTestPlan"
          type="button"
          title="Launch or resume the interactive system test-plan agent."
        >Start</button>
        <button
          id="approveTestPlan"
          type="button"
          title="Approve the test plan and advance to validation."
        >Approve</button>
        <button
          id="skipTestPlanApproval"
          type="button"
          title="Force test-plan approval when the operator accepts the risk."
        >Skip approval</button>
      </div>
      <div id="validateMenu" class="stage-menu" hidden>
        <button
          id="setValidateStage"
          type="button"
          title="Move the workflow to validate without starting validation."
        >Set stage</button>
        <button
          id="startAutomaticValidate"
          type="button"
          title="Run the non-interactive validation command set."
        >Start automatic</button>
        <button
          id="startInteractiveValidate"
          type="button"
          title="Open an interactive validation agent session."
        >Start interactive</button>
        <button
          id="stopValidate"
          type="button"
          title="Stop the running validation agent."
        >Stop</button>
        <button
          id="approveValidate"
          type="button"
          title="Approve validation and record the validation reports."
        >Approve</button>
        <button
          id="skipValidateApproval"
          type="button"
          title="Force validation approval when the operator accepts the risk."
        >Skip approval</button>
      </div>
      <div id="documentMenu" class="stage-menu" hidden>
        <div id="documentTargets" class="document-targets"></div>
        <button id="createDocumentTarget" type="button">Create your own</button>
        <div id="customDocumentForm" class="menu-form" hidden>
          <input
            id="customDocumentName"
            class="menu-text-input"
            type="text"
            autocomplete="off"
            placeholder="docs/guide.md"
            aria-label="Document name"
          >
          <button id="addDocumentTarget" type="button">Add document</button>
        </div>
      </div>
      <div id="projectPanel" class="project-panel" hidden>
        <input
          id="projectPath"
          class="project-path"
          type="text"
          autocomplete="off"
          aria-label="Project path"
        >
        <button id="browseProject" class="project-command" type="button">Browse</button>
        <button id="activateProject" class="project-command primary" type="button">
          Activate
        </button>
        <div id="projectStatus" class="project-status"></div>
      </div>
      <div id="workItemPanel" class="work-item-panel" hidden>
        <input
          id="workItemTitle"
          class="project-path"
          type="text"
          autocomplete="off"
          aria-label="Work item title"
        >
        <input
          id="workItemName"
          class="project-path"
          type="text"
          autocomplete="off"
          aria-label="Work item name"
        >
        <label id="workItemBranchLabel" class="work-item-checkbox">
          <input id="workItemBranchCheckbox" type="checkbox">
          Branch
        </label>
        <button id="applyWorkItem" class="project-command primary" type="button">
          Start
        </button>
        <button id="cancelWorkItem" class="project-command" type="button">Cancel</button>
        <div id="workItemStatus" class="project-status"></div>
        <div id="workItemRecovery" class="work-item-recovery" hidden>
          <button id="openProjectShell" class="project-command" type="button">
            Open project shell
          </button>
          <button id="retryWorkItem" class="project-command primary" type="button">
            Retry
          </button>
        </div>
      </div>
      <div
        id="fileBrowser"
        class="file-browser"
        role="dialog"
        aria-label="Directory browser"
        hidden
      >
        <div class="browser-toolbar">
          <input
            id="browserPath"
            class="browser-path"
            type="text"
            readonly
            aria-label="Current directory"
          >
          <button id="upDirectory" class="project-command" type="button">Up</button>
          <button id="selectDirectory" class="project-command primary" type="button">
            Select
          </button>
          <button id="closeBrowser" class="project-command" type="button">Close</button>
        </div>
        <div id="directoryList" class="directory-list"></div>
      </div>
    </section>
    <div
      id="shellResizeHandle"
      class="shell-resize-handle"
      role="separator"
      aria-orientation="horizontal"
      aria-label="Resize workflow and agent panes"
    ></div>
    <section id="agentPane" class="agent-pane" aria-label="Agent session">
      <div id="outputWorkbench" class="output-workbench">
        <div class="left-output-pane">
          <div id="outputSplit" class="output-split">
            <section id="agentOutputPane" class="terminal-pane" aria-label="Agent output">
              <div class="pane-header">
                <span class="pane-title">Agent output</span>
                <div class="pane-actions">
                  <div
                    class="pane-font-controls"
                    data-pane-font-controls="agent"
                    aria-label="Agent output font size"
                  >
                    <button
                      class="pane-font-button"
                      type="button"
                      data-pane-font="agent"
                      data-pane-font-delta="-1"
                      title="Decrease agent output font size"
                      aria-label="Decrease agent output font size"
                    >A-</button>
                    <span class="pane-font-level" data-pane-font-level="agent">15px</span>
                    <button
                      class="pane-font-button pane-font-reset"
                      type="button"
                      data-pane-font="agent"
                      data-pane-font-reset="1"
                      title="Reset agent output font size"
                      aria-label="Reset agent output font size"
                    >0</button>
                    <button
                      class="pane-font-button"
                      type="button"
                      data-pane-font="agent"
                      data-pane-font-delta="1"
                      title="Increase agent output font size"
                      aria-label="Increase agent output font size"
                    >A+</button>
                  </div>
                  <button
                    id="exportAgentOutput"
                    class="pane-popout-button"
                    type="button"
                    title="Export selected agent session as Markdown"
                    aria-label="Export selected agent session as Markdown"
                  >Export</button>
                  <button
                    id="popoutAgentPane"
                    class="pane-popout-button"
                    type="button"
                    title="Pop out agent output"
                    aria-label="Pop out agent output"
                  >Pop</button>
                </div>
              </div>
              <div id="agentOutput" class="agent-output" aria-live="polite"></div>
            </section>
            <div
              id="artifactPaneResizeHandle"
              class="artifact-pane-resize-handle"
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize agent and artifact panes"
              hidden
            ></div>
            <section
              id="artifactPreviewPane"
              class="artifact-preview-pane"
              aria-label="Artifact preview"
              hidden
            >
              <div id="artifactPreviewStack" class="artifact-preview-stack"></div>
            </section>
            <div
              id="outputResizeHandle"
              class="output-resize-handle"
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize agent and progress panes"
              hidden
            ></div>
            <section
              id="progressOutputPane"
              class="terminal-pane"
              aria-label="Progress output"
              hidden
            >
              <div class="pane-header">
                <span class="pane-title">Progress</span>
                <div class="pane-actions">
                  <div
                    class="pane-font-controls"
                    data-pane-font-controls="progress"
                    aria-label="Progress font size"
                  >
                    <button
                      class="pane-font-button"
                      type="button"
                      data-pane-font="progress"
                      data-pane-font-delta="-1"
                      title="Decrease progress font size"
                      aria-label="Decrease progress font size"
                    >A-</button>
                    <span class="pane-font-level" data-pane-font-level="progress">15px</span>
                    <button
                      class="pane-font-button pane-font-reset"
                      type="button"
                      data-pane-font="progress"
                      data-pane-font-reset="1"
                      title="Reset progress font size"
                      aria-label="Reset progress font size"
                    >0</button>
                    <button
                      class="pane-font-button"
                      type="button"
                      data-pane-font="progress"
                      data-pane-font-delta="1"
                      title="Increase progress font size"
                      aria-label="Increase progress font size"
                    >A+</button>
                  </div>
                  <button
                    id="exportProgressOutput"
                    class="pane-popout-button"
                    type="button"
                    title="Export progress log as Markdown"
                    aria-label="Export progress log as Markdown"
                  >Export</button>
                  <button
                    id="popoutProgressPane"
                    class="pane-popout-button"
                    type="button"
                    title="Pop out progress output"
                    aria-label="Pop out progress output"
                  >Pop</button>
                </div>
              </div>
              <div id="progressOutput" class="progress-output" aria-live="polite"></div>
            </section>
          </div>
          <div
            id="shellPaneDivider"
            class="shell-pane-divider"
            role="separator"
            aria-orientation="horizontal"
            aria-label="Project shell divider"
            hidden
          ></div>
          <section
            id="projectShellPane"
            class="terminal-pane"
            aria-label="Project shell"
            hidden
          >
            <div class="pane-header">
              <span class="pane-title">Project shell</span>
              <div class="pane-actions">
                <div
                  class="pane-font-controls"
                  data-pane-font-controls="shell"
                  aria-label="Project shell font size"
                >
                  <button
                    class="pane-font-button"
                    type="button"
                    data-pane-font="shell"
                    data-pane-font-delta="-1"
                    title="Decrease project shell font size"
                    aria-label="Decrease project shell font size"
                  >A-</button>
                  <span class="pane-font-level" data-pane-font-level="shell">15px</span>
                  <button
                    class="pane-font-button pane-font-reset"
                    type="button"
                    data-pane-font="shell"
                    data-pane-font-reset="1"
                    title="Reset project shell font size"
                    aria-label="Reset project shell font size"
                  >0</button>
                  <button
                    class="pane-font-button"
                    type="button"
                    data-pane-font="shell"
                    data-pane-font-delta="1"
                    title="Increase project shell font size"
                    aria-label="Increase project shell font size"
                  >A+</button>
                </div>
                <button
                  id="closeProjectShellPane"
                  class="pane-popout-button"
                  type="button"
                  title="Hide project shell"
                  aria-label="Hide project shell"
                >Close</button>
                <button
                  id="stopProjectShell"
                  class="pane-popout-button"
                  type="button"
                  title="Stop project shell"
                  aria-label="Stop project shell"
                >Stop</button>
                <button
                  id="popoutProjectShellPane"
                  class="pane-popout-button"
                  type="button"
                  title="Pop out project shell"
                  aria-label="Pop out project shell"
                >Pop</button>
              </div>
            </div>
            <div id="projectShellOutput" class="shell-output" aria-live="polite"></div>
          </section>
        </div>
        <div
          id="workbenchResizeHandle"
          class="workbench-resize-handle"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize terminal and side panes"
        ></div>
        <aside
          id="sidePane"
          class="side-pane"
          aria-label="Scratch pad and status"
        >
          <section class="scratch-pane" aria-label="Scratch pad">
            <div class="side-pane-header">
              <span class="pane-title">Scratch pad</span>
              <div class="pane-actions">
                <div
                  class="pane-font-controls"
                  data-pane-font-controls="scratch"
                  aria-label="Scratch pad font size"
                >
                  <button
                    class="pane-font-button"
                    type="button"
                    data-pane-font="scratch"
                    data-pane-font-delta="-1"
                    title="Decrease scratch pad font size"
                    aria-label="Decrease scratch pad font size"
                  >A-</button>
                  <span class="pane-font-level" data-pane-font-level="scratch">15px</span>
                  <button
                    class="pane-font-button pane-font-reset"
                    type="button"
                    data-pane-font="scratch"
                    data-pane-font-reset="1"
                    title="Reset scratch pad font size"
                    aria-label="Reset scratch pad font size"
                  >0</button>
                  <button
                    class="pane-font-button"
                    type="button"
                    data-pane-font="scratch"
                    data-pane-font-delta="1"
                    title="Increase scratch pad font size"
                    aria-label="Increase scratch pad font size"
                  >A+</button>
                </div>
                <button
                  id="popoutScratchPane"
                  class="pane-popout-button"
                  type="button"
                  title="Pop out scratch pad"
                  aria-label="Pop out scratch pad"
                >Pop</button>
              </div>
            </div>
            <textarea
              id="scratchPad"
              class="scratch-pad"
              spellcheck="true"
              aria-label="Scratch pad"
            ></textarea>
          </section>
          <div
            id="sidePaneResizeHandle"
            class="side-pane-resize-handle"
            role="separator"
            aria-orientation="horizontal"
            aria-label="Resize scratch pad and status panes"
          ></div>
          <section class="project-status-pane" aria-label="Project status">
            <div class="side-pane-header">
              <span class="pane-title">Project status</span>
              <div class="pane-actions">
                <div
                  class="pane-font-controls"
                  data-pane-font-controls="status"
                  aria-label="Project status font size"
                >
                  <button
                    class="pane-font-button"
                    type="button"
                    data-pane-font="status"
                    data-pane-font-delta="-1"
                    title="Decrease project status font size"
                    aria-label="Decrease project status font size"
                  >A-</button>
                  <span class="pane-font-level" data-pane-font-level="status">15px</span>
                  <button
                    class="pane-font-button pane-font-reset"
                    type="button"
                    data-pane-font="status"
                    data-pane-font-reset="1"
                    title="Reset project status font size"
                    aria-label="Reset project status font size"
                  >0</button>
                  <button
                    class="pane-font-button"
                    type="button"
                    data-pane-font="status"
                    data-pane-font-delta="1"
                    title="Increase project status font size"
                    aria-label="Increase project status font size"
                  >A+</button>
                </div>
                <button
                  id="popoutStatusPane"
                  class="pane-popout-button"
                  type="button"
                  title="Pop out project status"
                  aria-label="Pop out project status"
                >Pop</button>
              </div>
            </div>
            <pre id="projectStatusOutput" class="project-status-output">no active project</pre>
          </section>
        </aside>
      </div>
      <div
        id="inputResizeHandle"
        class="input-resize-handle"
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize output and input panes"
      ></div>
      <div id="inputPane" class="input-pane">
        <div class="input-pane-header pane-header">
          <span class="pane-title">AI agent input</span>
          <div class="pane-actions">
            <div
              class="pane-font-controls"
              data-pane-font-controls="input"
              aria-label="AI agent input font size"
            >
              <button
                class="pane-font-button"
                type="button"
                data-pane-font="input"
                data-pane-font-delta="-1"
                title="Decrease AI agent input font size"
                aria-label="Decrease AI agent input font size"
              >A-</button>
              <span class="pane-font-level" data-pane-font-level="input">15px</span>
              <button
                class="pane-font-button pane-font-reset"
                type="button"
                data-pane-font="input"
                data-pane-font-reset="1"
                title="Reset AI agent input font size"
                aria-label="Reset AI agent input font size"
              >0</button>
              <button
                class="pane-font-button"
                type="button"
                data-pane-font="input"
                data-pane-font-delta="1"
                title="Increase AI agent input font size"
                aria-label="Increase AI agent input font size"
              >A+</button>
            </div>
            <button
              id="popoutInputPane"
              class="pane-popout-button"
              type="button"
              title="Pop out AI agent input"
              aria-label="Pop out AI agent input"
            >Pop</button>
          </div>
        </div>
        <textarea
          id="agentInput"
          class="agent-input"
          spellcheck="true"
          disabled
          aria-label="Requirements agent input"
        ></textarea>
        <div
          id="inputActionResizeHandle"
          class="input-action-resize-handle"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize agent input and controls"
        ></div>
        <div class="agent-actions">
          <button
            id="interruptAgent"
            class="agent-action-button agent-interrupt"
            type="button"
            disabled
          >
            Interrupt
          </button>
          <button
            id="insertFileLink"
            class="agent-action-button agent-link"
            type="button"
            disabled
          >
            Link file
          </button>
        </div>
      </div>
    </section>
  </main>
  <script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js"></script>
  <script>
    const shell = document.querySelector(".shell");
    const connection = document.getElementById("connection");
    const workflowPane = document.querySelector(".workflow-pane");
    const shellResizeHandle = document.getElementById("shellResizeHandle");
    const workflowSideSheet = document.getElementById("workflowSideSheet");
    const toggleWorkflowSideSheet = document.getElementById("toggleWorkflowSideSheet");
    const workflowModeSelect = document.getElementById("workflowModeSelect");
    const stageScroll = document.querySelector(".stage-scroll");
    const stageNodes = Array.from(document.querySelectorAll(".stage-node[data-stage]"));
    const STAGE_DESCRIPTIONS = {
      project: "Open an existing ElectroBoy project or create a new one.",
      requirements: "Author or resume docs/requirements.md with the requirements agent.",
      design: "Author docs/detailed-design.md from the approved requirements.",
      "design-review": "Review the detailed design and capture blocking design issues.",
      "implementation-plan": "Author docs/implementation-plan.md with the implementation phases.",
      code: "Implement and commit the planned code changes.",
      "test-plan": "Author docs/test-plan.md with validation commands and acceptance checks.",
      validate: "Run validation commands and tests, then write the validation report.",
      document: "Update final project documentation after validation passes.",
    };
    const projectStage = document.querySelector("[data-stage='project']");
    const requirementsStage = document.querySelector("[data-stage='requirements']");
    const designStage = document.querySelector("[data-stage='design']");
    const designReviewStage = document.querySelector("[data-stage='design-review']");
    const implementationPlanStage =
      document.querySelector("[data-stage='implementation-plan']");
    const codeStage = document.querySelector("[data-stage='code']");
    const testPlanStage = document.querySelector("[data-stage='test-plan']");
    const validateStage = document.querySelector("[data-stage='validate']");
    const documentStage = document.querySelector("[data-stage='document']");
    const stageActionPanel = document.getElementById("stageActionPanel");
    const stageActionBody = document.getElementById("stageActionBody");
    const creativeBinder = document.getElementById("creativeBinder");
    const creativeProjectMenuButton = document.getElementById("creativeProjectMenuButton");
    const creativeProjectActions = document.getElementById("creativeProjectActions");
    const creativeOpenProject = document.getElementById("creativeOpenProject");
    const creativeNewProject = document.getElementById("creativeNewProject");
    const creativeRecentProjects = document.getElementById("creativeRecentProjects");
    const creativeCloseProject = document.getElementById("creativeCloseProject");
    const creativeActiveProjectSection =
      document.getElementById("creativeActiveProjectSection");
    const creativeProjectName = document.getElementById("creativeProjectName");
    const creativeAgentMenuButton = document.getElementById("creativeAgentMenuButton");
    const creativeAgentActions = document.getElementById("creativeAgentActions");
    const creativeStartAgent = document.getElementById("creativeStartAgent");
    const creativeTree = document.getElementById("creativeTree");
    const projectMenu = document.getElementById("projectMenu");
    const requirementsMenu = document.getElementById("requirementsMenu");
    const designMenu = document.getElementById("designMenu");
    const designReviewMenu = document.getElementById("designReviewMenu");
    const implementationPlanMenu = document.getElementById("implementationPlanMenu");
    const codeMenu = document.getElementById("codeMenu");
    const testPlanMenu = document.getElementById("testPlanMenu");
    const validateMenu = document.getElementById("validateMenu");
    const documentMenu = document.getElementById("documentMenu");
    const openProject = document.getElementById("openProject");
    const newProject = document.getElementById("newProject");
    const metaProjectBranch = document.getElementById("metaProjectBranch");
    const metaProjectMenuButton = document.getElementById("metaProjectMenuButton");
    const metaProjectSubmenu = document.getElementById("metaProjectSubmenu");
    const openMetaProject = document.getElementById("openMetaProject");
    const newMetaProject = document.getElementById("newMetaProject");
    const addMetaRepository = document.getElementById("addMetaRepository");
    const startMetaRepositoryBranch = document.getElementById("startMetaRepositoryBranch");
    const startMetaRepository = document.getElementById("startMetaRepository");
    const startMetaRepositorySubmenu = document.getElementById("startMetaRepositorySubmenu");
    const removeMetaRepositoryBranch = document.getElementById("removeMetaRepositoryBranch");
    const removeMetaRepository = document.getElementById("removeMetaRepository");
    const removeMetaRepositorySubmenu = document.getElementById("removeMetaRepositorySubmenu");
    const workItemBranch = document.getElementById("workItemBranch");
    const workItemMenuButton = document.getElementById("workItemMenuButton");
    const workItemSubmenu = document.getElementById("workItemSubmenu");
    const newFeatureWorkItem = document.getElementById("newFeatureWorkItem");
    const switchFeatureWorkItemBranch = document.getElementById("switchFeatureWorkItemBranch");
    const switchFeatureWorkItem = document.getElementById("switchFeatureWorkItem");
    const switchFeatureWorkItemSubmenu =
      document.getElementById("switchFeatureWorkItemSubmenu");
    const newBugWorkItem = document.getElementById("newBugWorkItem");
    const switchBugWorkItemBranch = document.getElementById("switchBugWorkItemBranch");
    const switchBugWorkItem = document.getElementById("switchBugWorkItem");
    const switchBugWorkItemSubmenu = document.getElementById("switchBugWorkItemSubmenu");
    const deactivateProject = document.getElementById("deactivateProject");
    const setRequirementsStage = document.getElementById("setRequirementsStage");
    const startRequirements = document.getElementById("startRequirements");
    const approveRequirements = document.getElementById("approveRequirements");
    const skipRequirementsApproval = document.getElementById("skipRequirementsApproval");
    const setDesignStage = document.getElementById("setDesignStage");
    const startDesign = document.getElementById("startDesign");
    const completeDesign = document.getElementById("completeDesign");
    const setDesignReviewStage = document.getElementById("setDesignReviewStage");
    const startAutomaticDesignReview = document.getElementById("startAutomaticDesignReview");
    const startInteractiveDesignReview = document.getElementById("startInteractiveDesignReview");
    const stopDesignReview = document.getElementById("stopDesignReview");
    const approveDesignReview = document.getElementById("approveDesignReview");
    const skipDesignReviewApproval = document.getElementById("skipDesignReviewApproval");
    const setImplementationPlanStage = document.getElementById("setImplementationPlanStage");
    const startImplementationPlan = document.getElementById("startImplementationPlan");
    const approveImplementationPlan = document.getElementById("approveImplementationPlan");
    const skipImplementationPlanApproval =
      document.getElementById("skipImplementationPlanApproval");
    const setCodeStage = document.getElementById("setCodeStage");
    const startAutomaticCode = document.getElementById("startAutomaticCode");
    const startInteractiveCode = document.getElementById("startInteractiveCode");
    const startCodeAdHocAgentButton = document.getElementById("startCodeAdHocAgent");
    const stopCode = document.getElementById("stopCode");
    const approveCode = document.getElementById("approveCode");
    const skipCodeApproval = document.getElementById("skipCodeApproval");
    const setTestPlanStage = document.getElementById("setTestPlanStage");
    const startTestPlan = document.getElementById("startTestPlan");
    const approveTestPlan = document.getElementById("approveTestPlan");
    const skipTestPlanApproval = document.getElementById("skipTestPlanApproval");
    const setValidateStage = document.getElementById("setValidateStage");
    const startAutomaticValidate = document.getElementById("startAutomaticValidate");
    const startInteractiveValidate = document.getElementById("startInteractiveValidate");
    const stopValidate = document.getElementById("stopValidate");
    const approveValidate = document.getElementById("approveValidate");
    const skipValidateApproval = document.getElementById("skipValidateApproval");
    const documentTargets = document.getElementById("documentTargets");
    const createDocumentTarget = document.getElementById("createDocumentTarget");
    const customDocumentForm = document.getElementById("customDocumentForm");
    const customDocumentName = document.getElementById("customDocumentName");
    const addDocumentTarget = document.getElementById("addDocumentTarget");
    const projectPanel = document.getElementById("projectPanel");
    const projectPath = document.getElementById("projectPath");
    const browseProject = document.getElementById("browseProject");
    const activateProject = document.getElementById("activateProject");
    const projectStatus = document.getElementById("projectStatus");
    const workItemPanel = document.getElementById("workItemPanel");
    const workItemTitle = document.getElementById("workItemTitle");
    const workItemName = document.getElementById("workItemName");
    const workItemBranchLabel = document.getElementById("workItemBranchLabel");
    const workItemBranchCheckbox = document.getElementById("workItemBranchCheckbox");
    const applyWorkItem = document.getElementById("applyWorkItem");
    const cancelWorkItem = document.getElementById("cancelWorkItem");
    const workItemStatus = document.getElementById("workItemStatus");
    const workItemRecovery = document.getElementById("workItemRecovery");
    const openProjectShell = document.getElementById("openProjectShell");
    const retryWorkItem = document.getElementById("retryWorkItem");
    const fileBrowser = document.getElementById("fileBrowser");
    const browserPath = document.getElementById("browserPath");
    const upDirectory = document.getElementById("upDirectory");
    const selectDirectory = document.getElementById("selectDirectory");
    const closeBrowser = document.getElementById("closeBrowser");
    const directoryList = document.getElementById("directoryList");
    const agentPane = document.getElementById("agentPane");
    const outputWorkbench = document.getElementById("outputWorkbench");
    const workbenchResizeHandle = document.getElementById("workbenchResizeHandle");
    const leftOutputPane = document.querySelector(".left-output-pane");
    const outputSplit = document.getElementById("outputSplit");
    const agentOutputPane = document.getElementById("agentOutputPane");
    const agentOutput = document.getElementById("agentOutput");
    const exportAgentOutput = document.getElementById("exportAgentOutput");
    const outputResizeHandle = document.getElementById("outputResizeHandle");
    const progressOutputPane = document.getElementById("progressOutputPane");
    const progressOutput = document.getElementById("progressOutput");
    const exportProgressOutput = document.getElementById("exportProgressOutput");
    const shellPaneDivider = document.getElementById("shellPaneDivider");
    const projectShellPane = document.getElementById("projectShellPane");
    const projectShellOutput = document.getElementById("projectShellOutput");
    const closeProjectShellPane = document.getElementById("closeProjectShellPane");
    const stopProjectShell = document.getElementById("stopProjectShell");
    const sidePane = document.getElementById("sidePane");
    const sidePaneResizeHandle = document.getElementById("sidePaneResizeHandle");
    const scratchPane = document.querySelector(".scratch-pane");
    const scratchPad = document.getElementById("scratchPad");
    const artifactPreviewPane = document.getElementById("artifactPreviewPane");
    const artifactPaneResizeHandle = document.getElementById("artifactPaneResizeHandle");
    const artifactPreviewStack = document.getElementById("artifactPreviewStack");
    const projectStatusPane = document.querySelector(".project-status-pane");
    const projectStatusOutput = document.getElementById("projectStatusOutput");
    const inputResizeHandle = document.getElementById("inputResizeHandle");
    const inputPane = document.getElementById("inputPane");
    const agentInput = document.getElementById("agentInput");
    const inputActionResizeHandle = document.getElementById("inputActionResizeHandle");
    const sessionSwitcher = document.getElementById("sessionSwitcher");
    const decreaseTerminalFont = document.getElementById("decreaseTerminalFont");
    const terminalFontValue = document.getElementById("terminalFontValue");
    const increaseTerminalFont = document.getElementById("increaseTerminalFont");
    const agentSessionIndicator = document.getElementById("agentSessionIndicator");
    const toggleProjectShellPane = document.getElementById("toggleProjectShellPane");
    const showSplashButton = document.getElementById("showSplash");
    const interruptAgent = document.getElementById("interruptAgent");
    const insertFileLink = document.getElementById("insertFileLink");
    const popoutAgentPane = document.getElementById("popoutAgentPane");
    const popoutProgressPane = document.getElementById("popoutProgressPane");
    const popoutProjectShellPane = document.getElementById("popoutProjectShellPane");
    const popoutScratchPane = document.getElementById("popoutScratchPane");
    const popoutStatusPane = document.getElementById("popoutStatusPane");
    const popoutInputPane = document.getElementById("popoutInputPane");
    const splashOverlay = document.getElementById("splashOverlay");
    const splashImage = document.getElementById("splashImage");
    const closeSplash = document.getElementById("closeSplash");
    const CONTEXT_STORAGE_KEY = "electroboy.contextId";
    const CONTEXT_TAB_STORAGE_KEY = "electroboy.contextTabId";
    const CONTEXT_OWNER_STORAGE_PREFIX = "electroboy.contextOwner.";
    const SPLASH_DISMISSED_STORAGE_KEY = "electroboy.splash.dismissed.v1";
    const SOFTWARE_SPLASH_IMAGE_ROUTE = "__SPLASH_IMAGE_ROUTE__";
    const CREATIVE_SPLASH_IMAGE_ROUTE = "__CREATIVE_SPLASH_IMAGE_ROUTE__";
    const CONTEXT_OWNER_TTL_MS = 15000;
    const CONTEXT_OWNER_HEARTBEAT_MS = 5000;
    const WORKFLOW_SIDE_SHEET_STORAGE_KEY = "electroboy.workflowSideSheetCollapsed";
    const WORKFLOW_MODE_STORAGE_KEY = "electroboy.workflowMode";
    const TERMINAL_FONT_STORAGE_KEY = "electroboy.terminalFontSize";
    const PANE_FONT_OFFSET_STORAGE_PREFIX = "electroboy.paneFontOffset.";
    const DOCUMENT_ZOOM_STORAGE_KEY = "electroboy.documentZoom";
    const WORKFLOW_PANE_HEIGHT_STORAGE_KEY = "electroboy.workflowPaneHeight";
    const WORKFLOW_PANE_HEIGHT_STORAGE_VERSION_KEY =
      "electroboy.workflowPaneHeightVersion";
    const WORKFLOW_PANE_HEIGHT_STORAGE_VERSION = "compact-v2";
    const DEFAULT_WORKFLOW_PANE_HEIGHT = 86;
    const MIN_WORKFLOW_PANE_HEIGHT = 86;
    const INPUT_PANE_HEIGHT_STORAGE_KEY = "electroboy.inputPaneHeight";
    const INPUT_ACTIONS_WIDTH_STORAGE_KEY = "electroboy.inputActionsWidth";
    const PROGRESS_PANE_WIDTH_STORAGE_KEY = "electroboy.progressPaneWidth";
    const PROGRESS_PANE_HEIGHT_STORAGE_KEY = "electroboy.progressPaneHeight";
    const PROJECT_SHELL_PANE_HEIGHT_STORAGE_KEY =
      "electroboy.projectShellPaneHeight";
    const RIGHT_PANE_WIDTH_STORAGE_KEY = "electroboy.rightPaneWidth";
    const CREATIVE_RIGHT_PANE_WIDTH_STORAGE_KEY =
      "electroboy.creativeRightPaneWidth";
    const RIGHT_PANE_HEIGHT_STORAGE_KEY = "electroboy.rightPaneHeight";
    const SCRATCH_PANE_HEIGHT_STORAGE_KEY = "electroboy.scratchPaneHeight";
    const ARTIFACT_PANE_WIDTH_STORAGE_KEY = "electroboy.artifactPaneWidth";
    const ARTIFACT_PANE_HEIGHT_STORAGE_KEY = "electroboy.artifactPaneHeight";
    const PANE_LAYOUT_STORAGE_KEY = "electroboy.paneLayout.v1";
    const SCRATCH_PAD_STORAGE_KEY = "electroboy.scratchPad";
    const DOCUMENT_TARGETS_STORAGE_KEY = "electroboy.documentTargets";
    const CREATIVE_WORKFLOW_MODE = "creative";
    const SOFTWARE_WORKFLOW_MODE = "software";
    const PANE_POPUP_FEATURES =
      "popup=yes,width=980,height=720,menubar=no,toolbar=no,location=no,status=no,scrollbars=yes,resizable=yes";
    const DEFAULT_DOCUMENT_TARGETS = [
      { label: "README", path: "README.md" },
      { label: "API", path: "docs/api.md" },
    ];
    const STAGE_ARTIFACT_PREVIEWS = {
      requirements: [
        { id: "requirements", kind: "requirements", title: "Requirements" },
      ],
      design: [
        {
          id: "design",
          kind: "route",
          title: "Detailed Design",
          path: "/artifacts/design",
        },
      ],
      "design-review": [
        {
          id: "design",
          kind: "route",
          title: "Detailed Design",
          path: "/artifacts/design",
        },
        {
          id: "design-review",
          kind: "route",
          title: "Design Review",
          path: "/artifacts/design-review",
        },
      ],
      "implementation-plan": [
        {
          id: "implementation-plan",
          kind: "route",
          title: "Implementation Plan",
          path: "/artifacts/implementation-plan",
        },
      ],
      code: [
        {
          id: "implementation-report",
          kind: "route",
          title: "Implementation Report",
          path: "/artifacts/implementation-report",
        },
      ],
      "test-plan": [
        {
          id: "test-plan",
          kind: "route",
          title: "Test Plan",
          path: "/artifacts/test-plan",
        },
      ],
      validate: [
        {
          id: "validation-report",
          kind: "route",
          title: "Validation Report",
          path: "/artifacts/validation-report",
        },
      ],
    };
    const DEFAULT_TERMINAL_FONT_SIZE = 15;
    const MIN_TERMINAL_FONT_SIZE = 11;
    const MAX_TERMINAL_FONT_SIZE = 24;
    const MIN_PANE_FONT_OFFSET = -6;
    const MAX_PANE_FONT_OFFSET = 6;
    const PANE_FONT_KEYS = ["agent", "progress", "shell", "input", "scratch", "status"];
    const PANE_FONT_CSS_PROPERTIES = {
      agent: "--agent-output-font-size",
      progress: "--progress-output-font-size",
      shell: "--project-shell-font-size",
      input: "--agent-input-font-size",
      scratch: "--scratch-pad-font-size",
      status: "--project-status-font-size",
    };
    const DEFAULT_DOCUMENT_ZOOM = 100;
    const DOCUMENT_ZOOM_STEP = 10;
    const MIN_DOCUMENT_ZOOM = 70;
    const MAX_DOCUMENT_ZOOM = 180;
    const MIN_INPUT_PANE_HEIGHT = 56;
    const MIN_INPUT_ACTIONS_WIDTH = 160;
    const MIN_AGENT_INPUT_WIDTH = 260;
    let eventSource = null;
    let progressEventSource = null;
    let projectShellEventSource = null;
    let artifactEventSources = [];
    let terminal = null;
    let terminalFit = null;
    let progressTerminal = null;
    let progressTerminalFit = null;
    let projectShellTerminal = null;
    let projectShellTerminalFit = null;
    let terminalFontSize = storedTerminalFontSize();
    let paneFontOffsets = storedPaneFontOffsets();
    let documentZoom = storedDocumentZoom();
    let resizeShellState = null;
    let resizeInputState = null;
    let resizeInputActionsState = null;
    let resizeOutputState = null;
    let resizeWorkbenchState = null;
    let resizeSidePaneState = null;
    let resizeArtifactPaneState = null;
    let resizeProjectShellState = null;
    let paneLayout = null;
    let paneLayoutObserver = null;
    let paneLayoutIdSequence = 0;
    let paneCornerSplitCancel = null;
    let terminalResizeObserver = null;
    let resizeTimer = null;
    let pendingTerminalResize = null;
    let shellResizeTimer = null;
    let statusRefreshTimer = null;
    let statusRefreshSequence = 0;
    let workflowSideSheetCollapsed = storedWorkflowSideSheetCollapsed();
    let workflowMode = storedWorkflowMode();
    let artifactPreviewKind = "";
    let artifactPreviewDocumentTarget = null;
    let artifactPreviewItems = [];
    let openDocumentTargets = [];
    let manualArtifactPreview = false;
    let manualArtifactPreviewStage = "";
    let artifactPreviewStage = "";
    let artifactPreviewVersion = 0;
    let artifactSaveTokenSequence = 0;
    let progressPaneRequested = false;
    let artifactPaneRequested = false;
    let projectShellPaneRequested = false;
    let projectShellPaneDismissed = false;
    let inputPaneRequested = true;
    let projectShellRunning = false;
    const poppedPanes = new Set();
    const poppedPaneWindows = new Map();
    const pendingArtifactSaves = new Map();
    let slashCommandMode = false;
    let terminalInputQueue = Promise.resolve();
    let activeAgentKind = "";
    let requirementsRunning = false;
    let requirementsApproved = false;
    let designRunning = false;
    let designReviewRunning = false;
    let designReviewInteractive = false;
    let designApproved = false;
    let documentationRunning = false;
    let adHocRunning = false;
    let currentWorkflowStage = "project";
    let agentSessions = [];
    let selectedSessionId = "";
    let contextId = "";
    const pageInstanceId = newContextOwnerId();
    let browserTabId = "";
    let ownedContextId = "";
    let contextOwnerTimer = null;
    let projectMode = "open";
    let projectBrowserActivatesSelection = false;
    let serviceRoot = "";
    let activationRoot = "";
    let activeProjectMode = "none";
    let activeProjectRoot = "";
    let activeRepositoryName = "";
    let registeredRepositories = [];
    let recentProjects = [];
    let workItemState = { collections: [], features: [], bugs: [] };
    let stageRunState = {};
    let workItemMode = "";
    let customDocumentTargets = storedDocumentTargets();
    let currentBrowsePath = "";
    let currentBrowseParent = "";
    let currentBrowserMode = "project";
    let currentSelectedFile = "";
    let expandedWorkflowStages = new Set();
    let expandedProjectActionGroups = new Set();
    let restoredScratchContextId = "";
    let creativeTreePayload = null;
    let creativeActiveDocument = "";
    let creativeActiveFolder = "";
    let creativeEditingPath = "";
    let creativeEditingType = "";
    let expandedCreativeFolders = new Set();
    let creativeScratchSaveTimer = null;
    let creativeLastNotifiedTarget = "";
    let creativeProjectActionsExpanded = false;
    let creativeAgentActionsExpanded = false;
    let projectStatusMessages = [];
    const PROJECT_STATUS_MESSAGE_LIMIT = 80;
    const CREATIVE_CORKBOARD_SUFFIX = ".corkboard.json";

    const PANE_LAYOUT_KINDS = {
      agent: { label: "Agent", element: agentOutputPane },
      progress: { label: "Progress", element: progressOutputPane },
      artifact: { label: "Artifact", element: artifactPreviewPane },
      shell: { label: "Shell", element: projectShellPane },
      scratch: { label: "Scratch", element: scratchPane },
      status: { label: "Status", element: projectStatusPane },
    };

    function newPaneLayoutId(prefix = "pane") {
      paneLayoutIdSequence += 1;
      return `${prefix}-${Date.now()}-${paneLayoutIdSequence}`;
    }

    function paneLayoutLeaf(kind = "empty") {
      return { type: "leaf", id: newPaneLayoutId(), kind };
    }

    function paneLayoutSplit(direction, first, second, ratio = 0.5) {
      return {
        type: "split",
        id: newPaneLayoutId("split"),
        direction,
        ratio,
        first,
        second,
      };
    }

    function defaultPaneLayout() {
      return paneLayoutSplit(
        "row",
        paneLayoutLeaf("agent"),
        paneLayoutSplit(
          "column",
          paneLayoutLeaf("scratch"),
          paneLayoutLeaf("status"),
          0.62,
        ),
        0.72,
      );
    }

    function normalizePaneLayoutNode(value, seenKinds) {
      if (!value || typeof value !== "object") {
        return null;
      }
      if (value.type === "leaf") {
        const requestedKind = String(value.kind || "empty");
        const validKind = requestedKind === "empty" || PANE_LAYOUT_KINDS[requestedKind];
        const kind = validKind && !seenKinds.has(requestedKind) ? requestedKind : "empty";
        if (kind !== "empty") {
          seenKinds.add(kind);
        }
        return paneLayoutLeaf(kind);
      }
      if (value.type !== "split") {
        return null;
      }
      const first = normalizePaneLayoutNode(value.first, seenKinds);
      const second = normalizePaneLayoutNode(value.second, seenKinds);
      if (!first || !second) {
        return null;
      }
      const ratio = Number(value.ratio);
      return paneLayoutSplit(
        value.direction === "column" ? "column" : "row",
        first,
        second,
        Number.isFinite(ratio) ? clampValue(ratio, 0.12, 0.88) : 0.5,
      );
    }

    function storedPaneLayout() {
      try {
        const stored = JSON.parse(window.localStorage.getItem(PANE_LAYOUT_STORAGE_KEY));
        return normalizePaneLayoutNode(stored, new Set()) || defaultPaneLayout();
      } catch (error) {
        return defaultPaneLayout();
      }
    }

    function savePaneLayout() {
      try {
        window.localStorage.setItem(PANE_LAYOUT_STORAGE_KEY, JSON.stringify(paneLayout));
      } catch (error) {
        return;
      }
    }

    function paneLayoutLeaves(node = paneLayout, leaves = []) {
      if (!node) {
        return leaves;
      }
      if (node.type === "leaf") {
        leaves.push(node);
        return leaves;
      }
      paneLayoutLeaves(node.first, leaves);
      paneLayoutLeaves(node.second, leaves);
      return leaves;
    }

    function paneLayoutLeafById(id) {
      return paneLayoutLeaves().find((leaf) => leaf.id === id) || null;
    }

    function paneLayoutLeafByKind(kind) {
      return paneLayoutLeaves().find((leaf) => leaf.kind === kind) || null;
    }

    function replacePaneLayoutNode(node, id, replacement) {
      if (node.id === id) {
        return replacement;
      }
      if (node.type === "leaf") {
        return node;
      }
      node.first = replacePaneLayoutNode(node.first, id, replacement);
      node.second = replacePaneLayoutNode(node.second, id, replacement);
      return node;
    }

    function removePaneLayoutLeaf(node, id) {
      if (node.type === "leaf") {
        return node.id === id ? null : node;
      }
      if (node.first.id === id) {
        return node.second;
      }
      if (node.second.id === id) {
        return node.first;
      }
      const first = removePaneLayoutLeaf(node.first, id);
      const second = removePaneLayoutLeaf(node.second, id);
      if (!first) {
        return second;
      }
      if (!second) {
        return first;
      }
      node.first = first;
      node.second = second;
      return node;
    }

    function paneLayoutKindAvailable(kind) {
      if (kind !== "artifact") {
        return true;
      }
      return artifactPreviewItems.length > 0 || Boolean(paneLayoutLeafByKind("artifact"));
    }

    function buildPaneLayoutToolbar(leaf) {
      const toolbar = document.createElement("div");
      toolbar.className = "pane-layout-toolbar";

      const select = document.createElement("select");
      select.className = "pane-layout-kind";
      select.title = "Choose pane type";
      select.setAttribute("aria-label", "Choose pane type");
      const emptyOption = document.createElement("option");
      emptyOption.value = "empty";
      emptyOption.textContent = "Choose pane";
      select.append(emptyOption);
      for (const [kind, definition] of Object.entries(PANE_LAYOUT_KINDS)) {
        const option = document.createElement("option");
        option.value = kind;
        option.textContent = definition.label;
        option.disabled = !paneLayoutKindAvailable(kind);
        select.append(option);
      }
      select.value = leaf.kind;
      select.addEventListener("change", () => {
        changePaneLayoutKind(leaf.id, select.value);
      });

      const splitRight = document.createElement("button");
      splitRight.className = "pane-layout-command split-right";
      splitRight.type = "button";
      splitRight.title = "Split pane right";
      splitRight.setAttribute("aria-label", "Split pane right");
      splitRight.addEventListener("click", () => splitPaneLayoutLeaf(leaf.id, "row"));

      const splitDown = document.createElement("button");
      splitDown.className = "pane-layout-command split-down";
      splitDown.type = "button";
      splitDown.title = "Split pane down";
      splitDown.setAttribute("aria-label", "Split pane down");
      splitDown.addEventListener("click", () => splitPaneLayoutLeaf(leaf.id, "column"));

      const close = document.createElement("button");
      close.className = "pane-layout-command close-pane";
      close.type = "button";
      close.title = "Close pane and join area";
      close.setAttribute("aria-label", "Close pane and join area");
      close.textContent = "×";
      close.disabled = paneLayoutLeaves().length <= 1;
      close.addEventListener("click", () => closePaneLayoutLeaf(leaf.id));

      const reset = document.createElement("button");
      reset.className = "pane-layout-command reset-layout";
      reset.type = "button";
      reset.title = "Reset pane layout";
      reset.setAttribute("aria-label", "Reset pane layout");
      reset.textContent = "↺";
      reset.addEventListener("click", resetPaneLayout);

      toolbar.append(select, splitRight, splitDown, close, reset);
      return toolbar;
    }

    function applyPaneLayoutSplitTemplate(element, node) {
      const ratio = clampValue(Number(node.ratio) || 0.5, 0.12, 0.88);
      if (node.direction === "column") {
        element.style.gridTemplateColumns = "minmax(0, 1fr)";
        element.style.gridTemplateRows =
          `minmax(0, ${ratio}fr) 7px minmax(0, ${1 - ratio}fr)`;
      } else {
        element.style.gridTemplateRows = "minmax(0, 1fr)";
        element.style.gridTemplateColumns =
          `minmax(0, ${ratio}fr) 7px minmax(0, ${1 - ratio}fr)`;
      }
    }

    function startPaneLayoutResize(event, node, splitElement, divider) {
      event.preventDefault();
      const pointerId = event.pointerId;
      divider.setPointerCapture(pointerId);
      divider.classList.add("resizing");
      const update = (moveEvent) => {
        const rect = splitElement.getBoundingClientRect();
        const available = node.direction === "column" ? rect.height - 7 : rect.width - 7;
        if (available <= 0) {
          return;
        }
        const position = node.direction === "column"
          ? moveEvent.clientY - rect.top - 3.5
          : moveEvent.clientX - rect.left - 3.5;
        node.ratio = clampValue(position / available, 0.12, 0.88);
        applyPaneLayoutSplitTemplate(splitElement, node);
        fitTerminal();
      };
      const finish = () => {
        divider.classList.remove("resizing");
        divider.removeEventListener("pointermove", update);
        divider.removeEventListener("pointerup", finish);
        divider.removeEventListener("pointercancel", finish);
        try {
          divider.releasePointerCapture(pointerId);
        } catch (error) {
          // Pointer capture may already be released by the browser.
        }
        savePaneLayout();
        fitTerminal();
      };
      divider.addEventListener("pointermove", update);
      divider.addEventListener("pointerup", finish);
      divider.addEventListener("pointercancel", finish);
    }

    function paneCornerSplitCandidate(event, state) {
      const topRight = state.corner === "top-right";
      const inwardX = topRight
        ? state.startX - event.clientX
        : event.clientX - state.startX;
      const inwardY = topRight
        ? event.clientY - state.startY
        : state.startY - event.clientY;
      if (Math.max(inwardX, inwardY) < 12) {
        return null;
      }
      const row = inwardX >= inwardY;
      const ratio = row
        ? (event.clientX - state.rect.left) / state.rect.width
        : (event.clientY - state.rect.top) / state.rect.height;
      return {
        direction: row ? "row" : "column",
        emptyFirst: row ? !topRight : topRight,
        ratio: clampValue(ratio, 0.12, 0.88),
      };
    }

    function showPaneCornerSplitPreview(preview, candidate) {
      preview.hidden = !candidate;
      if (!candidate) {
        return;
      }
      const ratioPercent = candidate.ratio * 100;
      preview.style.top = "0";
      preview.style.right = "auto";
      preview.style.bottom = "auto";
      preview.style.left = "0";
      preview.style.width = "100%";
      preview.style.height = "100%";
      if (candidate.direction === "row") {
        preview.style.width = candidate.emptyFirst
          ? `${ratioPercent}%`
          : `${100 - ratioPercent}%`;
        preview.style.left = candidate.emptyFirst ? "0" : `${ratioPercent}%`;
      } else {
        preview.style.height = candidate.emptyFirst
          ? `${ratioPercent}%`
          : `${100 - ratioPercent}%`;
        preview.style.top = candidate.emptyFirst ? "0" : `${ratioPercent}%`;
      }
    }

    function startPaneCornerSplit(event, leaf, leafElement, corner, preview) {
      if (event.button !== 0) {
        return;
      }
      if (paneCornerSplitCancel) {
        paneCornerSplitCancel();
      }
      event.preventDefault();
      event.stopPropagation();
      const state = {
        corner,
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        rect: leafElement.getBoundingClientRect(),
        candidate: null,
        finished: false,
      };
      event.currentTarget.setPointerCapture(event.pointerId);
      const handle = event.currentTarget;
      leafElement.classList.add("splitting");
      document.body.classList.add("pane-layout-splitting");

      const update = (moveEvent) => {
        state.candidate = paneCornerSplitCandidate(moveEvent, state);
        showPaneCornerSplitPreview(preview, state.candidate);
        document.body.classList.toggle(
          "pane-layout-splitting-row",
          state.candidate?.direction === "row",
        );
        document.body.classList.toggle(
          "pane-layout-splitting-column",
          state.candidate?.direction === "column",
        );
      };
      const finish = (commit) => {
        if (state.finished) {
          return;
        }
        state.finished = true;
        paneCornerSplitCancel = null;
        handle.removeEventListener("pointermove", update);
        handle.removeEventListener("pointerup", pointerUp);
        handle.removeEventListener("pointercancel", pointerCancel);
        window.removeEventListener("keydown", keyDown);
        leafElement.classList.remove("splitting");
        document.body.classList.remove(
          "pane-layout-splitting",
          "pane-layout-splitting-row",
          "pane-layout-splitting-column",
        );
        showPaneCornerSplitPreview(preview, null);
        try {
          handle.releasePointerCapture(state.pointerId);
        } catch (error) {
          // Pointer capture may already be released by the browser.
        }
        if (commit && state.candidate) {
          splitPaneLayoutLeaf(
            leaf.id,
            state.candidate.direction,
            state.candidate.ratio,
            state.candidate.emptyFirst,
          );
        }
      };
      const pointerUp = () => finish(true);
      const pointerCancel = () => finish(false);
      const keyDown = (keyEvent) => {
        if (keyEvent.key === "Escape") {
          keyEvent.preventDefault();
          finish(false);
        }
      };
      paneCornerSplitCancel = () => finish(false);
      handle.addEventListener("pointermove", update);
      handle.addEventListener("pointerup", pointerUp);
      handle.addEventListener("pointercancel", pointerCancel);
      window.addEventListener("keydown", keyDown);
    }

    function buildPaneLayoutCorner(leaf, leafElement, corner, preview) {
      const handle = document.createElement("div");
      handle.className = `pane-layout-corner ${corner}`;
      handle.title = "Drag inward to split pane";
      handle.setAttribute("aria-hidden", "true");
      handle.addEventListener("pointerdown", (event) => {
        startPaneCornerSplit(event, leaf, leafElement, corner, preview);
      });
      return handle;
    }

    function renderPaneLayoutNode(node) {
      if (node.type === "leaf") {
        const leaf = document.createElement("div");
        leaf.className = "pane-layout-leaf";
        leaf.dataset.paneLayoutId = node.id;
        leaf.dataset.paneKind = node.kind;
        leaf.append(buildPaneLayoutToolbar(node));
        if (node.kind === "empty") {
          const empty = document.createElement("div");
          empty.className = "pane-layout-empty";
          empty.textContent = "Choose a pane type";
          leaf.append(empty);
        } else {
          leaf.append(PANE_LAYOUT_KINDS[node.kind].element);
        }
        const preview = document.createElement("div");
        preview.className = "pane-layout-split-preview";
        preview.hidden = true;
        preview.setAttribute("aria-hidden", "true");
        leaf.append(
          preview,
          buildPaneLayoutCorner(node, leaf, "top-right", preview),
          buildPaneLayoutCorner(node, leaf, "bottom-left", preview),
        );
        return leaf;
      }

      const split = document.createElement("div");
      split.className = `pane-layout-split ${node.direction}`;
      split.dataset.paneLayoutId = node.id;
      const first = renderPaneLayoutNode(node.first);
      const divider = document.createElement("div");
      divider.className = `pane-layout-divider ${node.direction}`;
      divider.setAttribute("role", "separator");
      divider.setAttribute(
        "aria-orientation",
        node.direction === "column" ? "horizontal" : "vertical",
      );
      divider.setAttribute("aria-label", "Resize split panes");
      divider.addEventListener("pointerdown", (event) => {
        startPaneLayoutResize(event, node, split, divider);
      });
      const second = renderPaneLayoutNode(node.second);
      split.append(first, divider, second);
      applyPaneLayoutSplitTemplate(split, node);
      return split;
    }

    function refreshPaneLayoutVisibility(node = paneLayout, element = outputWorkbench.firstElementChild) {
      if (!node || !element) {
        return false;
      }
      if (node.type === "leaf") {
        const visible = node.kind === "empty" || !PANE_LAYOUT_KINDS[node.kind].element.hidden;
        element.hidden = !visible;
        return visible;
      }
      const firstElement = element.children[0];
      const divider = element.children[1];
      const secondElement = element.children[2];
      const firstVisible = refreshPaneLayoutVisibility(node.first, firstElement);
      const secondVisible = refreshPaneLayoutVisibility(node.second, secondElement);
      element.hidden = !firstVisible && !secondVisible;
      divider.hidden = !firstVisible || !secondVisible;
      if (firstVisible && secondVisible) {
        applyPaneLayoutSplitTemplate(element, node);
      } else if (node.direction === "column") {
        element.style.gridTemplateColumns = "minmax(0, 1fr)";
        element.style.gridTemplateRows = "minmax(0, 1fr)";
      } else {
        element.style.gridTemplateRows = "minmax(0, 1fr)";
        element.style.gridTemplateColumns = "minmax(0, 1fr)";
      }
      return firstVisible || secondVisible;
    }

    function renderPaneLayout() {
      if (paneCornerSplitCancel) {
        paneCornerSplitCancel();
      }
      const root = renderPaneLayoutNode(paneLayout);
      root.classList.add("pane-layout-root");
      outputWorkbench.replaceChildren(root);
      refreshPaneLayoutVisibility();
      window.requestAnimationFrame(fitTerminal);
    }

    function splitPaneLayoutLeaf(id, direction, ratio = 0.5, emptyFirst = false) {
      const leaf = paneLayoutLeafById(id);
      if (!leaf) {
        return;
      }
      const existingLeaf = paneLayoutLeaf(leaf.kind);
      const emptyLeaf = paneLayoutLeaf();
      const replacement = paneLayoutSplit(
        direction,
        emptyFirst ? emptyLeaf : existingLeaf,
        emptyFirst ? existingLeaf : emptyLeaf,
        ratio,
      );
      paneLayout = replacePaneLayoutNode(paneLayout, id, replacement);
      savePaneLayout();
      renderPaneLayout();
    }

    function changePaneLayoutKind(id, kind) {
      const leaf = paneLayoutLeafById(id);
      if (!leaf || (kind !== "empty" && !PANE_LAYOUT_KINDS[kind])) {
        return;
      }
      const previousKind = leaf.kind;
      const existing = kind === "empty" ? null : paneLayoutLeafByKind(kind);
      if (existing && existing !== leaf) {
        existing.kind = previousKind;
      }
      leaf.kind = kind;
      savePaneLayout();
      renderPaneLayout();
      activatePaneLayoutKind(kind);
      if (previousKind !== kind && !paneLayoutLeafByKind(previousKind)) {
        deactivatePaneLayoutKind(previousKind);
      }
    }

    function closePaneLayoutLeaf(id) {
      if (paneLayoutLeaves().length <= 1) {
        return;
      }
      const leaf = paneLayoutLeafById(id);
      if (!leaf) {
        return;
      }
      const removedKind = leaf.kind;
      paneLayout = removePaneLayoutLeaf(paneLayout, id);
      savePaneLayout();
      renderPaneLayout();
      if (!paneLayoutLeafByKind(removedKind)) {
        deactivatePaneLayoutKind(removedKind);
      }
    }

    function activatePaneLayoutKind(kind) {
      if (poppedPanes.has(kind)) {
        dockPoppedPane(kind);
      }
      if (kind === "progress") {
        showProgressPane(true);
      } else if (kind === "artifact") {
        artifactPaneRequested = true;
        applyOutputPaneVisibility();
      } else if (kind === "shell") {
        showProjectShellPane(true);
      }
    }

    function deactivatePaneLayoutKind(kind) {
      if (kind === "progress") {
        showProgressPane(false);
      } else if (kind === "artifact") {
        artifactPaneRequested = false;
        applyOutputPaneVisibility();
      } else if (kind === "shell") {
        hideProjectShellPane();
      }
    }

    function ensurePaneInLayout(kind, targetKind = "agent", direction = "row") {
      if (!paneLayout || paneLayoutLeafByKind(kind)) {
        return;
      }
      const target = paneLayoutLeafByKind(targetKind) || paneLayoutLeaves()[0];
      if (!target) {
        paneLayout = paneLayoutLeaf(kind);
      } else {
        const replacement = paneLayoutSplit(
          direction,
          paneLayoutLeaf(target.kind),
          paneLayoutLeaf(kind),
        );
        paneLayout = replacePaneLayoutNode(paneLayout, target.id, replacement);
      }
      savePaneLayout();
      renderPaneLayout();
    }

    function resetPaneLayout() {
      paneLayout = defaultPaneLayout();
      savePaneLayout();
      renderPaneLayout();
      if (progressPaneRequested) {
        ensurePaneInLayout("progress", "agent", "row");
      }
      if (artifactPaneRequested && artifactPreviewItems.length > 0) {
        ensurePaneInLayout("artifact", "agent", "row");
      }
      if (projectShellPaneRequested) {
        ensurePaneInLayout("shell", "agent", "column");
      }
    }

    function initializePaneLayout() {
      paneLayout = storedPaneLayout();
      outputWorkbench.classList.add("pane-layout-enabled");
      renderPaneLayout();
      paneLayoutObserver = new MutationObserver(() => refreshPaneLayoutVisibility());
      for (const definition of Object.values(PANE_LAYOUT_KINDS)) {
        paneLayoutObserver.observe(definition.element, {
          attributes: true,
          attributeFilter: ["hidden"],
        });
      }
    }

    function storedTerminalFontSize() {
      try {
        const stored = Number(window.localStorage.getItem(TERMINAL_FONT_STORAGE_KEY));
        if (Number.isFinite(stored)) {
          return clampTerminalFontSize(stored);
        }
      } catch (error) {
        return DEFAULT_TERMINAL_FONT_SIZE;
      }
      return DEFAULT_TERMINAL_FONT_SIZE;
    }

    function saveTerminalFontSize() {
      try {
        window.localStorage.setItem(
          TERMINAL_FONT_STORAGE_KEY,
          String(terminalFontSize),
        );
      } catch (error) {
        return;
      }
    }

    function storedPaneFontOffsets() {
      const offsets = {};
      for (const pane of PANE_FONT_KEYS) {
        offsets[pane] = storedPaneFontOffset(pane);
      }
      return offsets;
    }

    function storedPaneFontOffset(pane) {
      try {
        const stored = Number(
          window.localStorage.getItem(PANE_FONT_OFFSET_STORAGE_PREFIX + pane),
        );
        if (Number.isFinite(stored)) {
          return clampPaneFontOffset(stored);
        }
      } catch (error) {
        return 0;
      }
      return 0;
    }

    function savePaneFontOffset(pane) {
      try {
        window.localStorage.setItem(
          PANE_FONT_OFFSET_STORAGE_PREFIX + pane,
          String(paneFontOffset(pane)),
        );
      } catch (error) {
        return;
      }
    }

    function storedDocumentZoom() {
      try {
        const stored = Number(window.localStorage.getItem(DOCUMENT_ZOOM_STORAGE_KEY));
        if (Number.isFinite(stored)) {
          return clampDocumentZoom(stored);
        }
      } catch (error) {
        return DEFAULT_DOCUMENT_ZOOM;
      }
      return DEFAULT_DOCUMENT_ZOOM;
    }

    function saveDocumentZoom() {
      try {
        window.localStorage.setItem(DOCUMENT_ZOOM_STORAGE_KEY, String(documentZoom));
      } catch (error) {
        return;
      }
    }

    function clampTerminalFontSize(value) {
      return Math.max(
        MIN_TERMINAL_FONT_SIZE,
        Math.min(MAX_TERMINAL_FONT_SIZE, value),
      );
    }

    function clampPaneFontOffset(value) {
      return Math.max(
        MIN_PANE_FONT_OFFSET,
        Math.min(MAX_PANE_FONT_OFFSET, Math.round(value)),
      );
    }

    function paneFontOffset(pane) {
      return paneFontOffsets[pane] || 0;
    }

    function effectivePaneFontSize(pane) {
      return clampTerminalFontSize(terminalFontSize + paneFontOffset(pane));
    }

    function paneFontKeyForKind(kind) {
      if (kind === "shell") return "shell";
      if (kind === "progress") return "progress";
      if (kind === "input") return "input";
      if (kind === "scratch") return "scratch";
      if (kind === "status") return "status";
      return "agent";
    }

    function terminalForPane(pane) {
      if (pane === "agent") return terminal;
      if (pane === "progress") return progressTerminal;
      if (pane === "shell") return projectShellTerminal;
      return null;
    }

    function clampDocumentZoom(value) {
      if (!Number.isFinite(value)) {
        return DEFAULT_DOCUMENT_ZOOM;
      }
      const stepped = Math.round(value / DOCUMENT_ZOOM_STEP) * DOCUMENT_ZOOM_STEP;
      return Math.max(MIN_DOCUMENT_ZOOM, Math.min(MAX_DOCUMENT_ZOOM, stepped));
    }

    function storedNumber(key) {
      try {
        const stored = Number(window.localStorage.getItem(key));
        if (Number.isFinite(stored) && stored > 0) {
          return stored;
        }
      } catch (error) {
        return 0;
      }
      return 0;
    }

    function saveNumber(key, value) {
      try {
        window.localStorage.setItem(key, String(Math.round(value)));
      } catch (error) {
        return;
      }
    }

    function storedWorkflowPaneHeight() {
      const workflowHeight = storedNumber(WORKFLOW_PANE_HEIGHT_STORAGE_KEY);
      if (!workflowHeight) {
        return 0;
      }
      let version = "";
      try {
        version = window.localStorage.getItem(
          WORKFLOW_PANE_HEIGHT_STORAGE_VERSION_KEY,
        ) || "";
      } catch (error) {
        version = "";
      }
      if (
        version !== WORKFLOW_PANE_HEIGHT_STORAGE_VERSION &&
        workflowHeight > DEFAULT_WORKFLOW_PANE_HEIGHT
      ) {
        saveWorkflowPaneHeight(DEFAULT_WORKFLOW_PANE_HEIGHT);
        return DEFAULT_WORKFLOW_PANE_HEIGHT;
      }
      return Math.max(MIN_WORKFLOW_PANE_HEIGHT, workflowHeight);
    }

    function saveWorkflowPaneHeight(height) {
      saveNumber(WORKFLOW_PANE_HEIGHT_STORAGE_KEY, height);
      try {
        window.localStorage.setItem(
          WORKFLOW_PANE_HEIGHT_STORAGE_VERSION_KEY,
          WORKFLOW_PANE_HEIGHT_STORAGE_VERSION,
        );
      } catch (error) {
        return;
      }
    }

    function applyStoredPaneSizes() {
      const workflowHeight = storedWorkflowPaneHeight();
      if (workflowHeight) {
        shell.style.setProperty("--workflow-pane-height", `${workflowHeight}px`);
      }
      const inputHeight = storedNumber(INPUT_PANE_HEIGHT_STORAGE_KEY);
      if (inputHeight) {
        agentPane.style.setProperty("--input-pane-height", `${inputHeight}px`);
      }
      const inputActionsWidth = storedNumber(INPUT_ACTIONS_WIDTH_STORAGE_KEY);
      if (inputActionsWidth) {
        inputPane.style.setProperty(
          "--input-actions-width",
          `${inputActionsWidth}px`,
        );
      }
    }

    function applyStoredProgressPaneWidth() {
      const stored = storedNumber(PROGRESS_PANE_WIDTH_STORAGE_KEY);
      if (stored) {
        outputSplit.style.setProperty("--progress-pane-width", `${stored}px`);
      }
    }

    function applyStoredProgressPaneHeight() {
      const stored = storedNumber(PROGRESS_PANE_HEIGHT_STORAGE_KEY);
      if (stored) {
        outputSplit.style.setProperty("--progress-pane-height", `${stored}px`);
      }
    }

    function applyStoredProgressPaneSize() {
      applyStoredProgressPaneWidth();
      applyStoredProgressPaneHeight();
    }

    function applyStoredProjectShellPaneHeight() {
      const stored = storedNumber(PROJECT_SHELL_PANE_HEIGHT_STORAGE_KEY);
      if (stored) {
        leftOutputPane.style.setProperty("--shell-pane-height", `${stored}px`);
      }
    }

    function applyStoredWorkbenchPaneSize() {
      const rightWidth = storedNumber(
        creativeModeActive()
          ? CREATIVE_RIGHT_PANE_WIDTH_STORAGE_KEY
          : RIGHT_PANE_WIDTH_STORAGE_KEY,
      );
      if (rightWidth) {
        outputWorkbench.style.setProperty("--right-pane-width", `${rightWidth}px`);
      } else {
        outputWorkbench.style.removeProperty("--right-pane-width");
      }
      const rightHeight = storedNumber(RIGHT_PANE_HEIGHT_STORAGE_KEY);
      if (rightHeight) {
        outputWorkbench.style.setProperty("--right-pane-height", `${rightHeight}px`);
      }
      const scratchHeight = storedNumber(SCRATCH_PANE_HEIGHT_STORAGE_KEY);
      if (scratchHeight) {
        sidePane.style.setProperty("--scratch-pane-height", `${scratchHeight}px`);
      }
    }

    function applyStoredArtifactPaneSize() {
      const artifactWidth = storedNumber(ARTIFACT_PANE_WIDTH_STORAGE_KEY);
      if (artifactWidth) {
        outputSplit.style.setProperty("--artifact-pane-width", `${artifactWidth}px`);
      }
      const artifactHeight = storedNumber(ARTIFACT_PANE_HEIGHT_STORAGE_KEY);
      if (artifactHeight) {
        outputSplit.style.setProperty("--artifact-pane-height", `${artifactHeight}px`);
      }
    }

    function saveProgressPaneWidth(width) {
      saveNumber(PROGRESS_PANE_WIDTH_STORAGE_KEY, width);
    }

    function saveProgressPaneHeight(height) {
      saveNumber(PROGRESS_PANE_HEIGHT_STORAGE_KEY, height);
    }

    function saveProjectShellPaneHeight(height) {
      saveNumber(PROJECT_SHELL_PANE_HEIGHT_STORAGE_KEY, height);
    }

    function saveRightPaneWidth(width) {
      saveNumber(
        creativeModeActive()
          ? CREATIVE_RIGHT_PANE_WIDTH_STORAGE_KEY
          : RIGHT_PANE_WIDTH_STORAGE_KEY,
        width,
      );
    }

    function saveRightPaneHeight(height) {
      saveNumber(RIGHT_PANE_HEIGHT_STORAGE_KEY, height);
    }

    function saveScratchPaneHeight(height) {
      saveNumber(SCRATCH_PANE_HEIGHT_STORAGE_KEY, height);
    }

    function saveArtifactPaneWidth(width) {
      saveNumber(ARTIFACT_PANE_WIDTH_STORAGE_KEY, width);
    }

    function saveArtifactPaneHeight(height) {
      saveNumber(ARTIFACT_PANE_HEIGHT_STORAGE_KEY, height);
    }

    function restoreScratchPad() {
      if (creativeModeActive()) {
        loadCreativeScratchPad();
        return;
      }
      const storageKey = scratchPadStorageKey();
      if (!storageKey) {
        scratchPad.value = "";
        restoredScratchContextId = "";
        return;
      }
      try {
        scratchPad.value = window.localStorage.getItem(storageKey) || "";
        restoredScratchContextId = contextId;
      } catch (error) {
        scratchPad.value = "";
      }
    }

    function saveScratchPad() {
      if (creativeModeActive()) {
        queueCreativeScratchPadSave();
        return;
      }
      const storageKey = scratchPadStorageKey();
      if (!storageKey) {
        return;
      }
      try {
        window.localStorage.setItem(storageKey, scratchPad.value);
      } catch (error) {
        return;
      }
    }

    function scratchPadStorageKey() {
      if (!contextId) {
        return "";
      }
      return `${SCRATCH_PAD_STORAGE_KEY}.${contextId}`;
    }

    function storedDocumentTargets() {
      try {
        const parsed = JSON.parse(
          window.localStorage.getItem(DOCUMENT_TARGETS_STORAGE_KEY) || "[]",
        );
        if (!Array.isArray(parsed)) {
          return [];
        }
        return parsed
          .map((target) => ({
            label: String(target.label || target.path || "").trim(),
            path: String(target.path || "").trim(),
          }))
          .filter((target) => target.label && target.path);
      } catch (error) {
        return [];
      }
    }

    function saveDocumentTargets() {
      try {
        window.localStorage.setItem(
          DOCUMENT_TARGETS_STORAGE_KEY,
          JSON.stringify(customDocumentTargets),
        );
      } catch (error) {
        return;
      }
    }

    function storedWorkflowSideSheetCollapsed() {
      try {
        return window.localStorage.getItem(WORKFLOW_SIDE_SHEET_STORAGE_KEY) === "1";
      } catch (error) {
        return false;
      }
    }

    function saveWorkflowSideSheetCollapsed() {
      try {
        window.localStorage.setItem(
          WORKFLOW_SIDE_SHEET_STORAGE_KEY,
          workflowSideSheetCollapsed ? "1" : "0",
        );
      } catch (error) {
        return;
      }
    }

    function storedWorkflowMode() {
      try {
        const stored = window.localStorage.getItem(WORKFLOW_MODE_STORAGE_KEY);
        return stored === CREATIVE_WORKFLOW_MODE
          ? CREATIVE_WORKFLOW_MODE
          : SOFTWARE_WORKFLOW_MODE;
      } catch (error) {
        return SOFTWARE_WORKFLOW_MODE;
      }
    }

    function saveWorkflowMode() {
      try {
        window.localStorage.setItem(WORKFLOW_MODE_STORAGE_KEY, workflowMode);
      } catch (error) {
        return;
      }
    }

    function creativeModeActive() {
      return workflowMode === CREATIVE_WORKFLOW_MODE;
    }

    function applyWorkflowMode(options = {}) {
      workflowModeSelect.value = workflowMode;
      shell.classList.toggle("creative-workflow", creativeModeActive());
      updateSplashImage();
      applyStoredWorkbenchPaneSize();
      creativeBinder.hidden = !creativeModeActive();
      stageActionBody.hidden = creativeModeActive();
      if (options.deferWorkspace) {
        refreshStageActionPanel();
        updateCreativeBinderActions();
        window.requestAnimationFrame(fitTerminal);
        return;
      }
      if (creativeModeActive()) {
        setWorkflowSideSheetCollapsed(false);
        applyCreativeWorkspace();
        restoreScratchPad();
        refreshCreativeBinder();
      } else {
        restoreSoftwareWorkspace();
      }
      refreshStageActionPanel();
      updateCreativeBinderActions();
      window.requestAnimationFrame(fitTerminal);
    }

    async function setWorkflowMode(mode) {
      const nextMode = mode === CREATIVE_WORKFLOW_MODE
        ? CREATIVE_WORKFLOW_MODE
        : SOFTWARE_WORKFLOW_MODE;
      if (nextMode === workflowMode) {
        applyWorkflowMode();
        return;
      }
      releaseContextOwner();
      contextId = "";
      resetWorkflowContextView();
      workflowMode = nextMode;
      saveWorkflowMode();
      applyWorkflowMode({ deferWorkspace: true });
      await restoreContext();
    }

    function applyWorkflowSideSheetState() {
      shell.classList.toggle("side-sheet-collapsed", workflowSideSheetCollapsed);
      toggleWorkflowSideSheet.setAttribute(
        "aria-label",
        workflowSideSheetCollapsed
          ? "Expand workflow side sheet"
          : "Collapse workflow side sheet",
      );
      toggleWorkflowSideSheet.title = workflowSideSheetCollapsed
        ? "Expand workflow side sheet"
        : "Collapse workflow side sheet";
      window.requestAnimationFrame(fitTerminal);
    }

    function setWorkflowSideSheetCollapsed(collapsed) {
      workflowSideSheetCollapsed = Boolean(collapsed);
      applyWorkflowSideSheetState();
      saveWorkflowSideSheetCollapsed();
    }

    function toggleWorkflowSideSheetCollapsed() {
      setWorkflowSideSheetCollapsed(!workflowSideSheetCollapsed);
    }

    function initializeTerminal() {
      if (!window.Terminal) {
        appendPlainOutput("terminal renderer unavailable; using plain text\\n", "error");
        return;
      }
      terminal = new window.Terminal(terminalOptions(true, "agent"));
      if (window.FitAddon && window.FitAddon.FitAddon) {
        terminalFit = new window.FitAddon.FitAddon();
        terminal.loadAddon(terminalFit);
      }
      terminal.open(agentOutput);
      terminal.onResize(({ cols, rows }) => {
        queueTerminalResize(cols, rows);
      });
      applyTerminalFontSize();
      fitTerminal();
      window.addEventListener("resize", fitTerminal);
    }

    function initializeProgressTerminal() {
      if (progressTerminal || !window.Terminal) {
        return;
      }
      progressTerminal = new window.Terminal(terminalOptions(true, "progress"));
      if (window.FitAddon && window.FitAddon.FitAddon) {
        progressTerminalFit = new window.FitAddon.FitAddon();
        progressTerminal.loadAddon(progressTerminalFit);
      }
      progressTerminal.open(progressOutput);
      applyTerminalFontSize();
    }

    function initializeProjectShellTerminal() {
      if (projectShellTerminal || !window.Terminal) {
        return;
      }
      projectShellTerminal = new window.Terminal(terminalOptions(false, "shell"));
      if (window.FitAddon && window.FitAddon.FitAddon) {
        projectShellTerminalFit = new window.FitAddon.FitAddon();
        projectShellTerminal.loadAddon(projectShellTerminalFit);
      }
      projectShellTerminal.onData((data) => {
        sendProjectShellInput(data);
      });
      projectShellTerminal.open(projectShellOutput);
      applyTerminalFontSize();
    }

    function terminalOptions(disableStdin = true, pane = "agent") {
      return {
        allowProposedApi: false,
        convertEol: true,
        cursorBlink: false,
        disableStdin,
        fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace',
        fontSize: effectivePaneFontSize(pane),
        scrollback: 10000,
        termName: "xterm-256color",
        theme: {
          background: "#10141f",
          foreground: "#e7edf7",
          cursor: "#e7edf7",
          selectionBackground: "#2b6173",
          black: "#151923",
          red: "#ff6b6b",
          green: "#51cf66",
          yellow: "#ffd43b",
          blue: "#74c0fc",
          magenta: "#da77f2",
          cyan: "#66d9e8",
          white: "#f1f3f5",
          brightBlack: "#5c677d",
          brightRed: "#ff8787",
          brightGreen: "#69db7c",
          brightYellow: "#ffe066",
          brightBlue: "#91caff",
          brightMagenta: "#e599f7",
          brightCyan: "#99e9f2",
          brightWhite: "#ffffff",
        },
      };
    }

    function timestampForDownload() {
      return new Date().toISOString().replace(/[:.]/g, "-");
    }

    function exportSafeName(value, fallback = "export") {
      return String(value || fallback)
        .replace(/[^A-Za-z0-9._-]+/g, "-")
        .replace(/^-+|-+$/g, "")
        || fallback;
    }

    function documentExportFormats() {
      return [
        {
          value: "markdown",
          label: "Markdown",
          extension: "md",
          description: "Markdown",
          accept: {
            "text/markdown": [".md"],
            "text/plain": [".txt"],
          },
        },
        {
          value: "docx",
          label: "DOCX",
          extension: "docx",
          description: "Word document",
          accept: {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [
              ".docx",
            ],
          },
        },
        {
          value: "pdf",
          label: "PDF",
          extension: "pdf",
          description: "PDF",
          accept: {
            "application/pdf": [".pdf"],
          },
        },
      ];
    }

    function documentExportFormat(format) {
      return documentExportFormats().find((candidate) => candidate.value === format)
        || documentExportFormats()[0];
    }

    function documentExportPickerTypes(format = "markdown") {
      const selected = documentExportFormat(format);
      return [
        {
          description: selected.description,
          accept: selected.accept,
        },
      ];
    }

    function downloadBlob(fileName, blob) {
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
    }

    async function writeBlobWithPicker(
      blob,
      suggestedName,
      pickerTypes = documentExportPickerTypes("markdown"),
    ) {
      if (!window.showSaveFilePicker) {
        downloadBlob(suggestedName, blob);
        return;
      }
      try {
        const handle = await window.showSaveFilePicker({
          suggestedName,
          types: pickerTypes,
        });
        const writable = await handle.createWritable();
        await writable.write(blob);
        await writable.close();
      } catch (error) {
        if (error && error.name === "AbortError") {
          return;
        }
        appendOutput(`export picker failed: ${error}\\n`, "error");
        downloadBlob(suggestedName, blob);
      }
    }

    async function exportBlob(url, suggestedName, format = "markdown") {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) {
        const message = await response.text();
        appendOutput(`${message || "export failed"}\\n`, "error");
        return;
      }
      const blob = await response.blob();
      await writeBlobWithPicker(
        blob,
        suggestedName,
        documentExportPickerTypes(format),
      );
    }

    async function exportMarkdown(url, suggestedName) {
      await exportBlob(url, suggestedName, "markdown");
    }

    function sessionExportName(session) {
      const kind = exportSafeName(session && session.kind, "agent");
      return `agent-session-${kind}-${timestampForDownload()}.md`;
    }

    async function exportAgentSession() {
      const session = selectedSession();
      if (!session) {
        appendOutput("select an agent session first\\n", "error");
        return;
      }
      const url = contextUrl(
        `/api/sessions/export?session_id=${encodeURIComponent(session.session_id)}`,
      );
      await exportMarkdown(url, sessionExportName(session));
    }

    async function exportProgressLog() {
      await exportMarkdown(
        contextUrl("/api/progress/export"),
        `progress-log-${timestampForDownload()}.md`,
      );
    }

    function artifactDocumentBaseName(item) {
      if (item.kind === "document" && item.target) {
        return exportSafeName(item.target.path || item.target.label || item.title);
      }
      if (item.kind === "route" && item.title) {
        return exportSafeName(item.title);
      }
      return exportSafeName(item.title || item.kind || "document");
    }

    function artifactDocumentExportName(item, format) {
      const selected = documentExportFormat(format);
      return `${artifactDocumentBaseName(item)}.${selected.extension}`;
    }

    function artifactDocumentExportUrl(item, format) {
      const parameters = new URLSearchParams();
      parameters.set("artifact", artifactKindForPane(item));
      parameters.set("format", format);
      if (item.kind === "document" && item.target) {
        parameters.set("path", item.target.path);
      }
      if (item.kind === "route" && item.path) {
        parameters.set("path", item.path);
      }
      return contextUrl(`/api/documents/export?${parameters.toString()}`);
    }

    async function exportArtifactDocument(item, format) {
      await exportBlob(
        artifactDocumentExportUrl(item, format),
        artifactDocumentExportName(item, format),
        format,
      );
    }

    function changeTerminalFontSize(delta) {
      terminalFontSize = clampTerminalFontSize(terminalFontSize + delta);
      saveTerminalFontSize();
      applyTerminalFontSize();
    }

    function changePaneFontOffset(pane, delta) {
      if (!PANE_FONT_KEYS.includes(pane)) {
        return;
      }
      paneFontOffsets[pane] = clampPaneFontOffset(paneFontOffset(pane) + delta);
      savePaneFontOffset(pane);
      applyPaneFontSize(pane);
    }

    function resetPaneFontOffset(pane) {
      if (!PANE_FONT_KEYS.includes(pane)) {
        return;
      }
      paneFontOffsets[pane] = 0;
      savePaneFontOffset(pane);
      applyPaneFontSize(pane);
    }

    function changeDocumentZoom(delta) {
      documentZoom = clampDocumentZoom(documentZoom + delta);
      saveDocumentZoom();
      applyDocumentZoom();
      if (artifactPreviewItems.length > 0) {
        refreshArtifactPreview({ includeEditing: false });
      }
    }

    function artifactEditorFontSize() {
      return Math.max(11, Math.min(28, Math.round(16 * (documentZoom / 100))));
    }

    function applyTerminalFontSize() {
      terminalFontValue.textContent = `${terminalFontSize}px`;
      document.documentElement.style.setProperty(
        "--terminal-font-size",
        `${terminalFontSize}px`,
      );
      document.documentElement.style.setProperty(
        "--ui-font-size",
        `${terminalFontSize}px`,
      );
      document.documentElement.style.setProperty(
        "--ui-small-font-size",
        `${Math.max(10, terminalFontSize - 2)}px`,
      );
      document.documentElement.style.setProperty(
        "--ui-menu-font-size",
        `${Math.max(11, terminalFontSize - 1)}px`,
      );
      applyPaneFontSizes();
      decreaseTerminalFont.disabled = terminalFontSize <= MIN_TERMINAL_FONT_SIZE;
      increaseTerminalFont.disabled = terminalFontSize >= MAX_TERMINAL_FONT_SIZE;
      window.requestAnimationFrame(fitTerminal);
    }

    function applyPaneFontSizes() {
      for (const pane of PANE_FONT_KEYS) {
        applyPaneFontSize(pane);
      }
    }

    function applyPaneFontSize(pane) {
      const cssProperty = PANE_FONT_CSS_PROPERTIES[pane];
      const fontSize = effectivePaneFontSize(pane);
      if (cssProperty) {
        document.documentElement.style.setProperty(cssProperty, `${fontSize}px`);
      }
      const paneTerminal = terminalForPane(pane);
      if (paneTerminal) {
        paneTerminal.options.fontSize = fontSize;
      }
      updatePaneFontControls(pane);
      window.requestAnimationFrame(fitTerminal);
    }

    function updatePaneFontControls(pane) {
      const offset = paneFontOffset(pane);
      const fontSize = effectivePaneFontSize(pane);
      for (const level of document.querySelectorAll(`[data-pane-font-level="${pane}"]`)) {
        level.textContent = `${fontSize}px`;
        level.title = offset === 0 ? "Global font size" : `Global ${offset > 0 ? "+" : ""}${offset}px`;
      }
      for (const button of document.querySelectorAll(`[data-pane-font="${pane}"]`)) {
        if (button.dataset.paneFontReset) {
          button.disabled = offset === 0;
          continue;
        }
        const delta = Number(button.dataset.paneFontDelta || "0");
        if (delta < 0) {
          button.disabled = offset <= MIN_PANE_FONT_OFFSET;
        } else if (delta > 0) {
          button.disabled = offset >= MAX_PANE_FONT_OFFSET;
        }
      }
    }

    function applyDocumentZoom() {
      for (const level of artifactPreviewStack.querySelectorAll(".document-zoom-level")) {
        level.textContent = `${documentZoom}%`;
      }
      for (const button of artifactPreviewStack.querySelectorAll("[data-zoom='out']")) {
        button.disabled = documentZoom <= MIN_DOCUMENT_ZOOM;
      }
      for (const button of artifactPreviewStack.querySelectorAll("[data-zoom='in']")) {
        button.disabled = documentZoom >= MAX_DOCUMENT_ZOOM;
      }
      postArtifactEditorFontSize();
    }

    function postArtifactEditorFontSize(targetFrame = null) {
      const frames = targetFrame
        ? [targetFrame]
        : Array.from(artifactPreviewStack.querySelectorAll(".artifact-preview-frame"));
      for (const frame of frames) {
        const item = artifactPreviewItems.find(
          (candidate) => candidate.id === frame.dataset.artifactId,
        );
        if (!item || !item.editing || !frame.contentWindow) {
          continue;
        }
        frame.contentWindow.postMessage(
          {
            type: "electroboy-editor-font-size",
            font_size: artifactEditorFontSize(),
          },
          window.location.origin,
        );
      }
    }

    function prepareTerminalStream() {
      applyTerminalFontSize();
      fitTerminal();
    }

    function fitTerminal() {
      if (terminalFit) {
        try {
          terminalFit.fit();
        } catch (error) {
          return;
        }
      }
      if (progressTerminalFit && !progressOutputPane.hidden) {
        try {
          progressTerminalFit.fit();
        } catch (error) {
          return;
        }
      }
      if (projectShellTerminalFit && !projectShellPane.hidden) {
        try {
          projectShellTerminalFit.fit();
        } catch (error) {
          return;
        }
      }
      queueTerminalResize();
      queueProjectShellResize();
    }

    function observeTerminalPaneResizes() {
      if (!window.ResizeObserver) {
        return;
      }
      terminalResizeObserver = new window.ResizeObserver(() => {
        window.requestAnimationFrame(fitTerminal);
      });
      terminalResizeObserver.observe(agentOutput);
      terminalResizeObserver.observe(progressOutput);
      terminalResizeObserver.observe(projectShellOutput);
    }

    function terminalResizePayload(columns = null, rows = null) {
      const session = selectedSession();
      if (!sessionIsRunning(session) || !contextId || !terminal) {
        return null;
      }
      return {
        session_id: session.session_id,
        columns: Number(columns || terminal.cols || 120),
        rows: Number(rows || terminal.rows || 32),
      };
    }

    function queueTerminalResize(columns = null, rows = null) {
      const payload = terminalResizePayload(columns, rows);
      if (!payload) {
        return;
      }
      pendingTerminalResize = payload;
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => {
        const resize = pendingTerminalResize;
        pendingTerminalResize = null;
        sendTerminalResize(resize);
      }, 120);
    }

    async function sendTerminalResize(payload = null) {
      const resize = payload || terminalResizePayload();
      if (!resize) {
        return;
      }
      await fetch(contextUrl("/api/sessions/resize"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(resize),
      }).catch(() => {});
    }

    function queueProjectShellResize() {
      if (
        !projectShellRunning ||
        !contextId ||
        !projectShellTerminal ||
        projectShellPane.hidden
      ) {
        return;
      }
      window.clearTimeout(shellResizeTimer);
      shellResizeTimer = window.setTimeout(sendProjectShellResize, 120);
    }

    async function sendProjectShellResize() {
      if (!projectShellRunning || !contextId || !projectShellTerminal) {
        return;
      }
      await fetch(contextUrl("/api/shell/resize"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          columns: projectShellTerminal.cols,
          rows: projectShellTerminal.rows,
        }),
      }).catch(() => {});
    }

    function appendOutput(text, className = "") {
      if (terminal) {
        terminal.write(formatTerminalMessage(text, className));
        return;
      }
      appendPlainOutput(text, className);
    }

    function appendPlainOutput(text, className = "") {
      const span = document.createElement("span");
      span.textContent = text;
      if (className) {
        span.className = className;
      }
      agentOutput.appendChild(span);
      agentOutput.scrollTop = agentOutput.scrollHeight;
    }

    function recordProjectStatusMessage(message) {
      const text = String(message || "").trim();
      if (!text) {
        return;
      }
      const timestamp = new Date().toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
      projectStatusMessages.push(`${timestamp} ${text}`);
      if (projectStatusMessages.length > PROJECT_STATUS_MESSAGE_LIMIT) {
        projectStatusMessages = projectStatusMessages.slice(-PROJECT_STATUS_MESSAGE_LIMIT);
      }
      if (creativeModeActive()) {
        renderCreativeProjectStatus();
      } else {
        projectStatusOutput.textContent = `${projectStatusMessages.slice(-12).join("\\n")}\\n`;
      }
    }

    function renderCreativeProjectStatus() {
      if (!projectStatusOutput) {
        return;
      }
      if (!creativeModeActive()) {
        return;
      }
      const lines = [];
      if (activeProjectRoot || activationRoot) {
        lines.push(`project: ${activeProjectRoot || activationRoot}`);
      } else {
        lines.push("no active project");
      }
      if (creativeActiveDocument) {
        lines.push(`document: ${creativeActiveDocument}`);
      } else if (creativeActiveFolder) {
        lines.push(`folder: ${creativeActiveFolder}`);
      }
      if (projectStatusMessages.length > 0) {
        lines.push("");
        lines.push(...projectStatusMessages.slice(-12));
      }
      projectStatusOutput.textContent = `${lines.join("\\n")}\\n`;
    }

    function appendAgentOutput(text) {
      if (terminal) {
        terminal.write(text);
        return;
      }
      appendPlainOutput(text);
    }

    function clearAgentOutput() {
      if (terminal) {
        terminal.clear();
        return;
      }
      agentOutput.replaceChildren();
    }

    function appendProgressOutput(text, className = "") {
      if (progressTerminal) {
        progressTerminal.write(formatTerminalMessage(text, className));
        return;
      }
      const span = document.createElement("span");
      span.textContent = text;
      if (className) {
        span.className = className;
      }
      progressOutput.appendChild(span);
      progressOutput.scrollTop = progressOutput.scrollHeight;
    }

    function clearProgressOutput() {
      if (progressTerminal) {
        progressTerminal.clear();
        return;
      }
      progressOutput.replaceChildren();
    }

    function appendProjectShellOutput(text, className = "") {
      if (projectShellTerminal) {
        projectShellTerminal.write(
          className ? formatTerminalMessage(text, className) : text,
        );
        return;
      }
      const span = document.createElement("span");
      span.textContent = text;
      if (className) {
        span.className = className;
      }
      projectShellOutput.appendChild(span);
      projectShellOutput.scrollTop = projectShellOutput.scrollHeight;
    }

    function clearProjectShellOutput() {
      if (projectShellTerminal) {
        projectShellTerminal.clear();
        return;
      }
      projectShellOutput.replaceChildren();
    }

    function applyProjectShellPaneVisibility() {
      const visible = projectShellPaneRequested && !poppedPanes.has("shell");
      if (visible) {
        ensurePaneInLayout("shell", "agent", "column");
      }
      projectShellPane.hidden = !visible;
      shellPaneDivider.hidden = !visible;
      leftOutputPane.classList.toggle("shell-visible", visible);
      if (visible) {
        applyStoredProjectShellPaneHeight();
        initializeProjectShellTerminal();
      }
      window.requestAnimationFrame(fitTerminal);
      updateProjectShellToggle();
    }

    function showProjectShellPane(show) {
      if (show) {
        projectShellPaneDismissed = false;
      }
      projectShellPaneRequested = show;
      applyProjectShellPaneVisibility();
    }

    function hideProjectShellPane() {
      projectShellPaneDismissed = projectShellRunning;
      projectShellPaneRequested = false;
      applyProjectShellPaneVisibility();
    }

    function syncProjectShellPane() {
      if (
        projectShellRunning &&
        !projectShellPaneRequested &&
        !projectShellPaneDismissed
      ) {
        projectShellPaneRequested = true;
      }
      if (!projectShellRunning) {
        projectShellPaneDismissed = false;
        closeProjectShellEventStream();
      }
      applyProjectShellPaneVisibility();
      if (projectShellRunning && !projectShellEventSource) {
        window.setTimeout(connectProjectShellEvents, 0);
      }
    }

    async function toggleProjectShellFromToolbar() {
      if (!activeProjectRoot || !contextId) {
        return;
      }
      const visible = projectShellPaneRequested && !poppedPanes.has("shell");
      if (visible) {
        hideProjectShellPane();
        return;
      }
      if (poppedPanes.has("shell")) {
        dockPoppedPane("shell");
      }
      if (projectShellRunning) {
        showProjectShellPane(true);
        projectShellTerminal?.focus();
        return;
      }
      await startProjectShell();
    }

    function updateProjectShellToggle() {
      if (!toggleProjectShellPane) {
        return;
      }
      const hasActiveProject = Boolean(activeProjectRoot);
      const visible = projectShellPaneRequested && !poppedPanes.has("shell");
      toggleProjectShellPane.disabled = !hasActiveProject;
      toggleProjectShellPane.classList.toggle("active", visible);
      if (!hasActiveProject) {
        toggleProjectShellPane.textContent = "Shell";
        toggleProjectShellPane.title = "Activate a project to open a shell";
      } else if (visible) {
        toggleProjectShellPane.textContent = "Hide";
        toggleProjectShellPane.title = "Hide the project shell pane";
      } else if (projectShellRunning) {
        toggleProjectShellPane.textContent = poppedPanes.has("shell") ? "Dock" : "Show";
        toggleProjectShellPane.title = "Show the running project shell";
      } else {
        toggleProjectShellPane.textContent = "Open";
        toggleProjectShellPane.title = "Open a shell in the active project";
      }
    }

    async function startProjectShell() {
      if (!activeProjectRoot || !contextId) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      showProjectShellPane(true);
      initializeProjectShellTerminal();
      appendProjectShellOutput("starting project shell...\\r\\n", "system");
      const response = await fetch(contextUrl("/api/shell/start"), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "shell start failed" }));
      if (!response.ok) {
        appendProjectShellOutput(`${payload.error || "shell start failed"}\\r\\n`, "error");
        return;
      }
      projectShellRunning = Boolean(payload.project_shell_running);
      updateProjectState(payload);
      projectShellTerminal?.focus();
    }

    function connectProjectShellEvents() {
      if (!contextId) {
        return;
      }
      if (projectShellEventSource) {
        projectShellEventSource.close();
      }
      showProjectShellPane(true);
      initializeProjectShellTerminal();
      projectShellEventSource = new EventSource(contextUrl("/api/shell/events"));
      projectShellEventSource.addEventListener("agent-event", (event) => {
        const payload = JSON.parse(event.data);
        if (payload.type === "output") {
          appendProjectShellOutput(payload.terminal || payload.text || "");
        } else if (payload.type === "system" || payload.type === "error") {
          appendProjectShellOutput(`${payload.text}\\r\\n`, payload.type);
        } else if (payload.type === "completed") {
          appendProjectShellOutput(
            `\\r\\nproject shell exited with code ${payload.returncode}\\r\\n`,
            "system",
          );
          projectShellRunning = false;
          projectShellPaneDismissed = false;
          closeProjectShellEventStream();
          refreshProject();
        }
      });
      projectShellEventSource.onerror = () => {};
      window.requestAnimationFrame(sendProjectShellResize);
    }

    function closeProjectShellEventStream() {
      if (projectShellEventSource) {
        projectShellEventSource.close();
        projectShellEventSource = null;
      }
    }

    function disposeProjectShellTerminal() {
      if (projectShellTerminal) {
        try {
          projectShellTerminal.dispose();
        } catch (error) {
          // Best effort cleanup; the shell process itself remains attached server-side.
        }
        projectShellTerminal = null;
        projectShellTerminalFit = null;
      }
      projectShellOutput.replaceChildren();
    }

    async function sendProjectShellInput(data) {
      if (!projectShellRunning || !contextId || !data) {
        return;
      }
      await fetch(contextUrl("/api/shell/input"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data }),
      }).catch(() => {});
    }

    async function stopProjectShellProcess() {
      if (!contextId) {
        return;
      }
      const response = await fetch(contextUrl("/api/shell/stop"), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "shell stop failed" }));
      if (!response.ok) {
        appendProjectShellOutput(`${payload.error || "shell stop failed"}\\r\\n`, "error");
        return;
      }
      projectShellRunning = false;
      projectShellPaneDismissed = false;
      closeProjectShellEventStream();
      updateProjectState(payload);
    }

    function setAgentInputVisible(isVisible) {
      inputPaneRequested = isVisible;
      const visible = isVisible && !poppedPanes.has("input");
      inputPane.hidden = !visible;
      inputResizeHandle.hidden = !visible;
      agentPane.classList.toggle("noninteractive", !visible);
      if (isVisible) {
        applyStoredPaneSizes();
      }
      if (!isVisible) {
        agentInput.disabled = true;
        insertFileLink.disabled = true;
      }
      window.requestAnimationFrame(fitTerminal);
    }

    function startShellResize(event) {
      event.preventDefault();
      const shellRect = shell.getBoundingClientRect();
      const workflowRect = workflowPane.getBoundingClientRect();
      resizeShellState = {
        startY: event.clientY,
        startHeight: workflowRect.height,
        maxHeight: Math.max(MIN_WORKFLOW_PANE_HEIGHT, shellRect.height - 240),
      };
      shellResizeHandle.setPointerCapture(event.pointerId);
      shell.classList.add("resizing");
    }

    function updateShellResize(event) {
      if (!resizeShellState) {
        return;
      }
      const deltaY = event.clientY - resizeShellState.startY;
      const nextHeight = clampValue(
        resizeShellState.startHeight + deltaY,
        MIN_WORKFLOW_PANE_HEIGHT,
        resizeShellState.maxHeight,
      );
      shell.style.setProperty("--workflow-pane-height", `${nextHeight}px`);
      saveWorkflowPaneHeight(nextHeight);
      repositionOpenStageMenu();
      fitTerminal();
    }

    function finishShellResize(event) {
      if (!resizeShellState) {
        return;
      }
      resizeShellState = null;
      shell.classList.remove("resizing");
      try {
        shellResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
      repositionOpenStageMenu();
      fitTerminal();
    }

    function startInputResize(event) {
      if (inputPane.hidden) {
        return;
      }
      event.preventDefault();
      const agentRect = agentPane.getBoundingClientRect();
      const inputRect = inputPane.getBoundingClientRect();
      resizeInputState = {
        startY: event.clientY,
        startHeight: inputRect.height,
        maxHeight: Math.max(MIN_INPUT_PANE_HEIGHT, agentRect.height - 160),
      };
      inputResizeHandle.setPointerCapture(event.pointerId);
      agentPane.classList.add("resizing-input");
    }

    function updateInputResize(event) {
      if (!resizeInputState) {
        return;
      }
      const deltaY = resizeInputState.startY - event.clientY;
      const nextHeight = clampValue(
        resizeInputState.startHeight + deltaY,
        MIN_INPUT_PANE_HEIGHT,
        resizeInputState.maxHeight,
      );
      agentPane.style.setProperty("--input-pane-height", `${nextHeight}px`);
      saveNumber(INPUT_PANE_HEIGHT_STORAGE_KEY, nextHeight);
      fitTerminal();
    }

    function finishInputResize(event) {
      if (!resizeInputState) {
        return;
      }
      resizeInputState = null;
      agentPane.classList.remove("resizing-input");
      try {
        inputResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
      fitTerminal();
    }

    function startInputActionsResize(event) {
      if (inputPane.hidden || window.matchMedia("(max-width: 760px)").matches) {
        return;
      }
      event.preventDefault();
      const inputPaneRect = inputPane.getBoundingClientRect();
      const inputPaneStyle = window.getComputedStyle(inputPane);
      const horizontalPadding =
        Number.parseFloat(inputPaneStyle.paddingLeft) +
        Number.parseFloat(inputPaneStyle.paddingRight);
      const columnGap = Number.parseFloat(inputPaneStyle.columnGap) || 0;
      const handleWidth = inputActionResizeHandle.getBoundingClientRect().width;
      const availableColumnWidth =
        inputPaneRect.width - horizontalPadding - handleWidth - (columnGap * 2);
      const actionsRect =
        inputPane.querySelector(".agent-actions").getBoundingClientRect();
      resizeInputActionsState = {
        startX: event.clientX,
        startWidth: actionsRect.width,
        maxWidth: Math.max(
          MIN_INPUT_ACTIONS_WIDTH,
          availableColumnWidth - MIN_AGENT_INPUT_WIDTH,
        ),
      };
      inputActionResizeHandle.setPointerCapture(event.pointerId);
      inputPane.classList.add("resizing-actions");
    }

    function updateInputActionsResize(event) {
      if (!resizeInputActionsState) {
        return;
      }
      const deltaX = resizeInputActionsState.startX - event.clientX;
      const nextWidth = clampValue(
        resizeInputActionsState.startWidth + deltaX,
        MIN_INPUT_ACTIONS_WIDTH,
        resizeInputActionsState.maxWidth,
      );
      inputPane.style.setProperty("--input-actions-width", `${nextWidth}px`);
      saveNumber(INPUT_ACTIONS_WIDTH_STORAGE_KEY, nextWidth);
    }

    function finishInputActionsResize(event) {
      if (!resizeInputActionsState) {
        return;
      }
      resizeInputActionsState = null;
      inputPane.classList.remove("resizing-actions");
      try {
        inputActionResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
    }

    function startWorkbenchResize(event) {
      event.preventDefault();
      const workbenchRect = outputWorkbench.getBoundingClientRect();
      const sideRect = sidePane.getBoundingClientRect();
      resizeWorkbenchState = {
        vertical: window.matchMedia("(max-width: 760px)").matches,
        startX: event.clientX,
        startY: event.clientY,
        startWidth: sideRect.width,
        startHeight: sideRect.height,
        maxWidth: Math.max(260, workbenchRect.width - 340),
        maxHeight: Math.max(200, workbenchRect.height - 220),
      };
      workbenchResizeHandle.setPointerCapture(event.pointerId);
      outputWorkbench.classList.add("resizing");
    }

    function updateWorkbenchResize(event) {
      if (!resizeWorkbenchState) {
        return;
      }
      if (resizeWorkbenchState.vertical) {
        const deltaY = resizeWorkbenchState.startY - event.clientY;
        const nextHeight = clampValue(
          resizeWorkbenchState.startHeight + deltaY,
          200,
          resizeWorkbenchState.maxHeight,
        );
        outputWorkbench.style.setProperty("--right-pane-height", `${nextHeight}px`);
        outputWorkbench.style.gridTemplateRows = `minmax(0, 1fr) 7px ${nextHeight}px`;
        saveRightPaneHeight(nextHeight);
      } else {
        const deltaX = resizeWorkbenchState.startX - event.clientX;
        const nextWidth = clampValue(
          resizeWorkbenchState.startWidth + deltaX,
          260,
          resizeWorkbenchState.maxWidth,
        );
        outputWorkbench.style.setProperty("--right-pane-width", `${nextWidth}px`);
        saveRightPaneWidth(nextWidth);
      }
      fitTerminal();
    }

    function finishWorkbenchResize(event) {
      if (!resizeWorkbenchState) {
        return;
      }
      resizeWorkbenchState = null;
      outputWorkbench.classList.remove("resizing");
      try {
        workbenchResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
      fitTerminal();
    }

    function startSidePaneResize(event) {
      event.preventDefault();
      const sideRect = sidePane.getBoundingClientRect();
      const scratchRect = scratchPad.getBoundingClientRect();
      resizeSidePaneState = {
        startY: event.clientY,
        startHeight: scratchRect.height,
        maxHeight: Math.max(120, sideRect.height - 150),
      };
      sidePaneResizeHandle.setPointerCapture(event.pointerId);
      sidePane.classList.add("resizing");
    }

    function updateSidePaneResize(event) {
      if (!resizeSidePaneState) {
        return;
      }
      const deltaY = event.clientY - resizeSidePaneState.startY;
      const nextHeight = clampValue(
        resizeSidePaneState.startHeight + deltaY,
        120,
        resizeSidePaneState.maxHeight,
      );
      sidePane.style.setProperty("--scratch-pane-height", `${nextHeight}px`);
      saveScratchPaneHeight(nextHeight);
    }

    function finishSidePaneResize(event) {
      if (!resizeSidePaneState) {
        return;
      }
      resizeSidePaneState = null;
      sidePane.classList.remove("resizing");
      try {
        sidePaneResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
    }

    function startArtifactPaneResize(event) {
      if (artifactPreviewPane.hidden || poppedPanes.has("agent")) {
        return;
      }
      event.preventDefault();
      const splitRect = outputSplit.getBoundingClientRect();
      const artifactRect = artifactPreviewPane.getBoundingClientRect();
      resizeArtifactPaneState = {
        vertical: window.matchMedia("(max-width: 760px)").matches,
        startX: event.clientX,
        startY: event.clientY,
        startWidth: artifactRect.width,
        startHeight: artifactRect.height,
        maxWidth: Math.max(320, splitRect.width - 360),
        maxHeight: Math.max(220, splitRect.height - 240),
      };
      artifactPaneResizeHandle.setPointerCapture(event.pointerId);
      outputSplit.classList.add("resizing-artifact");
    }

    function updateArtifactPaneResize(event) {
      if (!resizeArtifactPaneState) {
        return;
      }
      if (resizeArtifactPaneState.vertical) {
        const deltaY = resizeArtifactPaneState.startY - event.clientY;
        const nextHeight = clampValue(
          resizeArtifactPaneState.startHeight + deltaY,
          220,
          resizeArtifactPaneState.maxHeight,
        );
        outputSplit.style.setProperty("--artifact-pane-height", `${nextHeight}px`);
        outputSplit.style.gridTemplateRows = `minmax(0, 1fr) 7px ${nextHeight}px`;
        saveArtifactPaneHeight(nextHeight);
      } else {
        const deltaX = resizeArtifactPaneState.startX - event.clientX;
        const nextWidth = clampValue(
          resizeArtifactPaneState.startWidth + deltaX,
          320,
          resizeArtifactPaneState.maxWidth,
        );
        outputSplit.style.setProperty("--artifact-pane-width", `${nextWidth}px`);
        saveArtifactPaneWidth(nextWidth);
      }
      fitTerminal();
    }

    function finishArtifactPaneResize(event) {
      if (!resizeArtifactPaneState) {
        return;
      }
      resizeArtifactPaneState = null;
      outputSplit.classList.remove("resizing-artifact");
      try {
        artifactPaneResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
    }

    function applyOutputPaneVisibility() {
      const agentVisible = !poppedPanes.has("agent");
      const artifactVisible =
        artifactPaneRequested && artifactPreviewItems.length > 0 && !poppedPanes.has("artifact");
      const progressVisible = progressPaneRequested && !poppedPanes.has("progress");
      if (artifactVisible) {
        ensurePaneInLayout("artifact", "agent", "row");
      }
      if (progressVisible) {
        ensurePaneInLayout("progress", "agent", "row");
      }
      agentOutputPane.hidden = !agentVisible;
      artifactPreviewPane.hidden = !artifactVisible;
      progressOutputPane.hidden = !progressVisible;
      artifactPaneResizeHandle.hidden = !artifactVisible || !agentVisible;
      outputResizeHandle.hidden =
        !progressVisible || (!agentVisible && !artifactVisible);
      outputSplit.classList.toggle("agent-popped", !agentVisible);
      outputSplit.classList.toggle("artifact-visible", Boolean(artifactVisible));
      outputSplit.classList.toggle("split", progressVisible);
      window.requestAnimationFrame(fitTerminal);
    }

    function showProgressPane(show) {
      progressPaneRequested = show;
      if (show) {
        outputSplit.style.gridTemplateRows = "";
        applyStoredProgressPaneSize();
        initializeProgressTerminal();
        prepareTerminalStream();
      } else {
        outputSplit.style.gridTemplateRows = "";
        closeProgressEventStream();
      }
      applyOutputPaneVisibility();
      window.requestAnimationFrame(fitTerminal);
    }

    function startOutputResize(event) {
      if (progressOutputPane.hidden) {
        return;
      }
      event.preventDefault();
      const splitRect = outputSplit.getBoundingClientRect();
      const progressRect = progressOutputPane.getBoundingClientRect();
      resizeOutputState = {
        vertical: window.matchMedia("(max-width: 760px)").matches,
        startX: event.clientX,
        startY: event.clientY,
        startSize: progressRect.width,
        startHeight: progressRect.height,
        maxWidth: Math.max(280, splitRect.width - 320),
        maxHeight: Math.max(180, splitRect.height - 220),
      };
      outputResizeHandle.setPointerCapture(event.pointerId);
      outputSplit.classList.add("resizing");
    }

    function updateOutputResize(event) {
      if (!resizeOutputState) {
        return;
      }
      if (resizeOutputState.vertical) {
        const deltaY = resizeOutputState.startY - event.clientY;
        const nextHeight = clampValue(
          resizeOutputState.startHeight + deltaY,
          180,
          resizeOutputState.maxHeight,
        );
        outputSplit.style.setProperty("--progress-pane-height", `${nextHeight}px`);
        outputSplit.style.gridTemplateRows = `minmax(0, 1fr) 7px ${nextHeight}px`;
        saveProgressPaneHeight(nextHeight);
      } else {
        const deltaX = resizeOutputState.startX - event.clientX;
        const nextWidth = clampValue(
          resizeOutputState.startSize + deltaX,
          280,
          resizeOutputState.maxWidth,
        );
        outputSplit.style.setProperty("--progress-pane-width", `${nextWidth}px`);
        saveProgressPaneWidth(nextWidth);
      }
      fitTerminal();
    }

    function finishOutputResize(event) {
      if (!resizeOutputState) {
        return;
      }
      resizeOutputState = null;
      outputSplit.classList.remove("resizing");
      try {
        outputResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
      fitTerminal();
    }

    function startProjectShellPaneResize(event) {
      if (projectShellPane.hidden) {
        return;
      }
      event.preventDefault();
      const leftOutputRect = leftOutputPane.getBoundingClientRect();
      const shellRect = projectShellPane.getBoundingClientRect();
      resizeProjectShellState = {
        startY: event.clientY,
        startHeight: shellRect.height,
        maxHeight: Math.max(180, leftOutputRect.height - 220),
      };
      shellPaneDivider.setPointerCapture(event.pointerId);
      leftOutputPane.classList.add("resizing-shell");
    }

    function updateProjectShellPaneResize(event) {
      if (!resizeProjectShellState) {
        return;
      }
      const deltaY = resizeProjectShellState.startY - event.clientY;
      const nextHeight = clampValue(
        resizeProjectShellState.startHeight + deltaY,
        180,
        resizeProjectShellState.maxHeight,
      );
      leftOutputPane.style.setProperty("--shell-pane-height", `${nextHeight}px`);
      saveProjectShellPaneHeight(nextHeight);
      fitTerminal();
    }

    function finishProjectShellPaneResize(event) {
      if (!resizeProjectShellState) {
        return;
      }
      resizeProjectShellState = null;
      leftOutputPane.classList.remove("resizing-shell");
      try {
        shellPaneDivider.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
      fitTerminal();
    }

    function clampValue(value, minimum, maximum) {
      const upper = Math.max(minimum, maximum);
      return Math.max(minimum, Math.min(upper, value));
    }

    function formatTerminalMessage(text, className) {
      if (className === "error") {
        return `\\x1b[31m${text}\\x1b[0m`;
      }
      if (className === "system") {
        return `\\x1b[36m${text}\\x1b[0m`;
      }
      return text;
    }

    function setConnected() {
      connection.textContent = connectionBadgeLabel();
    }

    function connectionBadgeLabel() {
      const parts = ["connected"];
      if (activationRoot) {
        parts.push(activationRoot);
      }
      const feature = activeWorkItemFeature();
      if (feature) {
        parts.push(`feature: ${feature.name || feature.slug}`);
      }
      return parts.join(" · ");
    }

    function applyStageDescriptions() {
      for (const stageNode of stageNodes) {
        const stageId = stageNode.dataset.stage || "";
        const description = STAGE_DESCRIPTIONS[stageId] || "";
        if (!description) {
          continue;
        }
        const label = stageNode.textContent.trim();
        stageNode.title = description;
        stageNode.setAttribute("aria-label", `${label}: ${description}`);
      }
    }

    async function checkConnection() {
      const response = await fetch("/api/health", { cache: "no-store" });
      if (response.ok) {
        setConnected();
      }
    }

    function contextUrl(path) {
      const separator = path.includes("?") ? "&" : "?";
      return `${path}${separator}context_id=${encodeURIComponent(contextId)}`;
    }

    function paneUrl(kind, requestedArtifactItem = null) {
      const parameters = new URLSearchParams();
      if (contextId) {
        parameters.set("context_id", contextId);
      }
      if (selectedSessionId) {
        parameters.set("session_id", selectedSessionId);
      }
      const artifactItem = requestedArtifactItem || artifactPreviewItems[0] || null;
      if (artifactItem) {
        parameters.set("artifact", artifactKindForPane(artifactItem));
      }
      if (artifactItem && artifactItem.kind === "document" && artifactItem.target) {
        parameters.set("document_path", artifactItem.target.path);
        parameters.set("document_title", artifactItem.target.label);
      }
      if (
        artifactItem &&
        artifactItem.kind === "creative-corkboard" &&
        artifactItem.folder
      ) {
        parameters.set("folder_path", artifactItem.folder.path);
        parameters.set("folder_title", artifactItem.folder.label || artifactItem.title);
      }
      if (
        artifactItem &&
        artifactItem.kind === "creative-corkboard" &&
        artifactItem.corkboard
      ) {
        parameters.set("corkboard_path", artifactItem.corkboard.path);
        parameters.set(
          "corkboard_title",
          artifactItem.corkboard.label || artifactItem.title,
        );
      }
      const fontPane = paneFontKeyForKind(kind);
      parameters.set("base_font_size", String(terminalFontSize));
      parameters.set("font_pane", fontPane);
      parameters.set("font_offset", String(paneFontOffset(fontPane)));
      parameters.set("font_size", String(effectivePaneFontSize(fontPane)));
      parameters.set("document_zoom", String(documentZoom));
      return `/pane/${encodeURIComponent(kind)}?${parameters.toString()}`;
    }

    function popOutPane(kind, artifactItem = null) {
      if (!contextId && kind !== "scratch") {
        appendOutput("create a browser context first\\n", "error");
        return;
      }
      const popup = window.open(
        paneUrl(kind, artifactItem),
        `electroboy-${kind}-${contextId || "local"}`,
        PANE_POPUP_FEATURES,
      );
      if (!popup) {
        appendOutput("popup was blocked by the browser\\n", "error");
        return;
      }
      const existing = poppedPaneWindows.get(kind);
      if (existing) {
        window.clearInterval(existing.poll);
      }
      setPanePoppedOut(kind, true);
      const poll = window.setInterval(() => {
        if (!popup.closed) {
          return;
        }
        window.clearInterval(poll);
        poppedPaneWindows.delete(kind);
        setPanePoppedOut(kind, false);
      }, 500);
      poppedPaneWindows.set(kind, { popup, poll });
    }

    function dockPoppedPane(kind) {
      const existing = poppedPaneWindows.get(kind);
      if (existing) {
        window.clearInterval(existing.poll);
        try {
          existing.popup.close();
        } catch (error) {
          // The browser may block closing a user-managed window.
        }
        poppedPaneWindows.delete(kind);
      }
      setPanePoppedOut(kind, false);
    }

    function setPanePoppedOut(kind, poppedOut) {
      if (poppedOut) {
        poppedPanes.add(kind);
      } else {
        poppedPanes.delete(kind);
      }
      if (kind === "scratch" || kind === "status") {
        applySidePaneVisibility();
      }
      if (kind === "input") {
        setAgentInputVisible(inputPaneRequested);
      }
      if (kind === "agent" || kind === "artifact" || kind === "progress") {
        if (kind === "artifact") {
          if (poppedOut) {
            artifactPreviewStack.replaceChildren();
          } else if (artifactPreviewItems.length > 0) {
            renderArtifactPreviewItems();
          }
        }
        applyOutputPaneVisibility();
      }
      if (kind === "shell") {
        if (poppedOut) {
          closeProjectShellEventStream();
          disposeProjectShellTerminal();
        }
        applyProjectShellPaneVisibility();
        if (
          !poppedOut &&
          projectShellRunning &&
          projectShellPaneRequested &&
          !projectShellEventSource
        ) {
          window.setTimeout(connectProjectShellEvents, 0);
        }
      }
      window.requestAnimationFrame(fitTerminal);
    }

    function applySidePaneVisibility() {
      const scratchPopped = poppedPanes.has("scratch");
      const statusPopped = poppedPanes.has("status");
      const sideVisible = !(scratchPopped && statusPopped);
      scratchPane.hidden = scratchPopped;
      projectStatusPane.hidden = statusPopped;
      sidePaneResizeHandle.hidden = scratchPopped || statusPopped;
      sidePane.hidden = !sideVisible;
      workbenchResizeHandle.hidden = !sideVisible;
      outputWorkbench.classList.toggle("side-popped", !sideVisible);
      sidePane.classList.toggle("scratch-popped", scratchPopped && !statusPopped);
      sidePane.classList.toggle("status-popped", statusPopped && !scratchPopped);
    }

    window.addEventListener("message", (event) => {
      if (event.origin !== window.location.origin) {
        return;
      }
      const data = event.data || {};
      if (data.type === "electroboy-file-browser-select" && data.path) {
        if (data.mode === "link") {
          insertTextAtCursor(data.path);
          agentInput.focus();
          return;
        }
        if (data.mode === "document" || data.mode === "document-new") {
          const target = documentTargetFromSelectedPath(data.path);
          if (target) {
            launchDocumentTarget(target);
          }
          return;
        }
        if (
          (data.mode === "project" || data.mode === "project-new") &&
          (projectBrowserActivatesSelection || data.project_action)
        ) {
          if (data.project_action) {
            projectMode = data.project_action;
          }
          projectBrowserActivatesSelection = false;
          applyProjectSelection(data.path).catch((error) => {
            appendOutput(`project update failed: ${error}\\n`, "error");
          });
          return;
        }
        projectPath.value = data.path;
        projectStatus.textContent = `selected: ${data.path}`;
        projectPath.focus();
        return;
      }
      if (data.type === "electroboy-artifact-saved") {
        refreshArtifactPreview({ includeEditing: false });
        recordProjectStatusMessage(`saved: ${data.path || "artifact"}`);
        return;
      }
      if (data.type === "electroboy-artifact-save-complete") {
        const token = data.token || "";
        const pending = pendingArtifactSaves.get(token);
        if (pending) {
          window.clearTimeout(pending.timeout);
          pendingArtifactSaves.delete(token);
          pending.resolve(Boolean(data.ok));
        }
        return;
      }
      if (data.type === "electroboy-creative-open" && data.path) {
        if (data.entry_type === "directory") {
          selectCreativeFolder(data.path);
        } else if (data.entry_type === "corkboard") {
          selectCreativeCorkboard(data.path);
        } else {
          selectCreativeDocument(data.path);
        }
        return;
      }
      if (
        data.type === "electroboy-pane-font-offset" &&
        PANE_FONT_KEYS.includes(data.pane)
      ) {
        paneFontOffsets[data.pane] = clampPaneFontOffset(Number(data.offset || 0));
        applyPaneFontSize(data.pane);
        return;
      }
      if (data.type !== "electroboy-pane-restore" || !data.pane) {
        return;
      }
      const entry = poppedPaneWindows.get(data.pane);
      if (entry) {
        window.clearInterval(entry.poll);
        poppedPaneWindows.delete(data.pane);
      }
      setPanePoppedOut(data.pane, false);
    });

    function contextWorkflowStorageKey(mode = workflowMode) {
      const suffix = mode === CREATIVE_WORKFLOW_MODE
        ? CREATIVE_WORKFLOW_MODE
        : SOFTWARE_WORKFLOW_MODE;
      return `${CONTEXT_STORAGE_KEY}.${suffix}`;
    }

    function splashDismissed() {
      try {
        return window.sessionStorage.getItem(SPLASH_DISMISSED_STORAGE_KEY) === "1";
      } catch (error) {
        return false;
      }
    }

    function openSplash() {
      if (!splashOverlay) {
        return;
      }
      updateSplashImage();
      splashOverlay.hidden = false;
    }

    function updateSplashImage() {
      if (!splashImage) {
        return;
      }
      splashImage.src = creativeModeActive()
        ? CREATIVE_SPLASH_IMAGE_ROUTE
        : SOFTWARE_SPLASH_IMAGE_ROUTE;
    }

    function showSplashIfNeeded() {
      if (!splashOverlay || splashDismissed()) {
        return;
      }
      openSplash();
    }

    function dismissSplash() {
      if (!splashOverlay || splashOverlay.hidden) {
        return;
      }
      splashOverlay.hidden = true;
      try {
        window.sessionStorage.setItem(SPLASH_DISMISSED_STORAGE_KEY, "1");
      } catch (error) {
        return;
      }
    }

    function clearLegacyContextId() {
      try {
        window.sessionStorage.removeItem(CONTEXT_STORAGE_KEY);
      } catch (error) {
        return;
      }
    }

    function storedContextId(mode = workflowMode) {
      try {
        return window.sessionStorage.getItem(contextWorkflowStorageKey(mode)) || "";
      } catch (error) {
        return "";
      }
    }

    function newContextOwnerId() {
      try {
        if (
          window.crypto &&
          typeof window.crypto.randomUUID === "function"
        ) {
          return window.crypto.randomUUID();
        }
      } catch (error) {
        // Fall through to the timestamp/random fallback below.
      }
      return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    }

    function storedBrowserTabId() {
      try {
        return window.sessionStorage.getItem(CONTEXT_TAB_STORAGE_KEY) || "";
      } catch (error) {
        return "";
      }
    }

    function saveBrowserTabId(value) {
      try {
        if (value) {
          window.sessionStorage.setItem(CONTEXT_TAB_STORAGE_KEY, value);
        } else {
          window.sessionStorage.removeItem(CONTEXT_TAB_STORAGE_KEY);
        }
      } catch (error) {
        return;
      }
    }

    function currentBrowserTabId() {
      if (browserTabId) {
        return browserTabId;
      }
      browserTabId = storedBrowserTabId();
      if (!browserTabId) {
        browserTabId = newContextOwnerId();
        saveBrowserTabId(browserTabId);
      }
      return browserTabId;
    }

    function navigationType() {
      try {
        const entries = window.performance.getEntriesByType("navigation");
        return entries.length ? entries[0].type || "" : "";
      } catch (error) {
        return "";
      }
    }

    function contextOwnerKey(value) {
      return `${CONTEXT_OWNER_STORAGE_PREFIX}${value}`;
    }

    function readContextOwner(value) {
      try {
        const raw = window.localStorage.getItem(contextOwnerKey(value));
        return raw ? JSON.parse(raw) : null;
      } catch (error) {
        return null;
      }
    }

    function writeContextOwner(value) {
      try {
        window.localStorage.setItem(
          contextOwnerKey(value),
          JSON.stringify({
            tab_id: currentBrowserTabId(),
            page_id: pageInstanceId,
            updated_at: Date.now(),
          }),
        );
      } catch (error) {
        return;
      }
    }

    function contextOwnerIsFresh(owner) {
      if (!owner || !owner.updated_at) {
        return false;
      }
      return Date.now() - Number(owner.updated_at) < CONTEXT_OWNER_TTL_MS;
    }

    function hasConflictingContextOwner(value) {
      const owner = readContextOwner(value);
      if (!contextOwnerIsFresh(owner)) {
        return false;
      }
      if (owner.page_id === pageInstanceId) {
        return false;
      }
      if (owner.tab_id !== currentBrowserTabId()) {
        return true;
      }
      const type = navigationType();
      return type !== "reload" && type !== "back_forward";
    }

    function refreshContextOwner() {
      if (ownedContextId) {
        writeContextOwner(ownedContextId);
      }
    }

    function releaseContextOwner() {
      const releasedContextId = ownedContextId;
      ownedContextId = "";
      if (contextOwnerTimer) {
        window.clearInterval(contextOwnerTimer);
        contextOwnerTimer = null;
      }
      if (!releasedContextId) {
        return;
      }
      try {
        const owner = readContextOwner(releasedContextId);
        if (owner && owner.page_id === pageInstanceId) {
          window.localStorage.removeItem(contextOwnerKey(releasedContextId));
        }
      } catch (error) {
        return;
      }
    }

    function claimContextOwner(value) {
      if (!value) {
        releaseContextOwner();
        return true;
      }
      if (ownedContextId === value) {
        refreshContextOwner();
        return true;
      }
      if (hasConflictingContextOwner(value)) {
        return false;
      }
      releaseContextOwner();
      ownedContextId = value;
      refreshContextOwner();
      contextOwnerTimer = window.setInterval(
        refreshContextOwner,
        CONTEXT_OWNER_HEARTBEAT_MS,
      );
      return true;
    }

    function saveContextId(value, mode = workflowMode) {
      try {
        clearLegacyContextId();
        if (value) {
          if (!claimContextOwner(value)) {
            return false;
          }
          window.sessionStorage.setItem(contextWorkflowStorageKey(mode), value);
        } else {
          releaseContextOwner();
          window.sessionStorage.removeItem(contextWorkflowStorageKey(mode));
        }
        return true;
      } catch (error) {
        return false;
      }
    }

    function resetWorkflowContextView() {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      closeProgressEventStream();
      closeProjectShellEventStream();
      showProgressPane(false);
      showProjectShellPane(false);
      activationRoot = "";
      activeProjectMode = "none";
      activeProjectRoot = "";
      activeRepositoryName = "";
      registeredRepositories = [];
      projectPath.value = serviceRoot || "";
      workItemState = { collections: [], features: [], bugs: [] };
      stageRunState = {};
      requirementsRunning = false;
      requirementsApproved = false;
      designRunning = false;
      designReviewRunning = false;
      designReviewInteractive = false;
      designApproved = false;
      documentationRunning = false;
      adHocRunning = false;
      projectShellRunning = false;
      agentSessions = [];
      selectedSessionId = "";
      activeAgentKind = "";
      openDocumentTargets = [];
      currentWorkflowStage = "project";
      creativeActiveDocument = "";
      creativeActiveFolder = "";
      creativeEditingPath = "";
      creativeEditingType = "";
      expandedCreativeFolders = new Set();
      creativeLastNotifiedTarget = "";
      creativeTreePayload = null;
      restoredScratchContextId = "";
      projectStatusMessages = [];
      clearAgentOutput();
      clearProgressOutput();
      clearProjectShellOutput();
      hideArtifactPreview();
      hideWorkItemPanel();
      renderSessionSwitcher();
      updateAgentControls();
    }

    async function createContext() {
      const response = await fetch("/api/contexts", { method: "POST" });
      if (!response.ok) {
        projectStatus.textContent = "could not create browser context";
        return;
      }
      const payload = await response.json();
      contextId = payload.context_id || "";
      saveContextId(contextId);
      updateProjectState(payload);
    }

    async function restoreContext() {
      const existingContextId = storedContextId();
      if (!existingContextId || !claimContextOwner(existingContextId)) {
        if (existingContextId) {
          saveContextId("");
        }
        await createContext();
        return;
      }
      contextId = existingContextId;
      const response = await fetch(contextUrl("/api/project"), { cache: "no-store" });
      if (!response.ok) {
        saveContextId("");
        contextId = "";
        await createContext();
        return;
      }
      const payload = await response.json();
      contextId = payload.context_id || existingContextId;
      saveContextId(contextId);
      updateProjectState(payload);
      const session = selectedSession();
      if (session) {
        clearAgentOutput();
        const isInteractive = Boolean(session.interactive);
        if (isInteractive) {
          showProgressPane(false);
          setAgentInputVisible(true);
        } else {
          clearProgressOutput();
          showProgressPane(true);
          setAgentInputVisible(false);
        }
        activeAgentKind = session.kind || "";
        connectSessionEvents(session.session_id);
        if (!isInteractive && session.status === "running") {
          connectProgressEvents();
        }
        sendTerminalResize();
      }
    }

    function updateProjectState(payload, options = {}) {
      const previousActiveProjectRoot = activeProjectRoot;
      const nextActiveProjectRoot = payload.active_project_root || "";
      serviceRoot = payload.service_root || "";
      activationRoot = payload.activation_root || nextActiveProjectRoot || "";
      activeProjectMode = payload.project_mode || (activationRoot ? "project" : "none");
      activeProjectRoot = nextActiveProjectRoot;
      if (previousActiveProjectRoot && previousActiveProjectRoot !== activeProjectRoot) {
        hideArtifactPreview();
        openDocumentTargets = [];
        creativeActiveDocument = "";
        creativeActiveFolder = "";
        creativeEditingPath = "";
        creativeEditingType = "";
        expandedCreativeFolders = new Set();
        creativeLastNotifiedTarget = "";
        creativeTreePayload = null;
        restoredScratchContextId = "";
      }
      activeRepositoryName = payload.active_repository_name || "";
      registeredRepositories = Array.isArray(payload.registered_repositories)
        ? payload.registered_repositories
        : [];
      recentProjects = Array.isArray(payload.recent_projects)
        ? payload.recent_projects
        : [];
      workItemState = payload.work_items || { collections: [], features: [], bugs: [] };
      stageRunState = payload.stage_runs || {};
      requirementsRunning = Boolean(payload.requirements_running);
      requirementsApproved = Boolean(payload.requirements_approved);
      designRunning = Boolean(payload.design_running);
      designReviewRunning = Boolean(payload.design_review_running);
      designReviewInteractive = Boolean(payload.design_review_interactive);
      designApproved = Boolean(payload.design_approved);
      documentationRunning = Boolean(payload.documentation_running);
      adHocRunning = Boolean(payload.ad_hoc_running);
      projectShellRunning = Boolean(payload.project_shell_running);
      agentSessions = Array.isArray(payload.sessions) ? payload.sessions : [];
      selectedSessionId = payload.selected_session_id || selectedSessionId || "";
      syncOpenDocumentTargetsFromSessions();
      if (!agentSessions.some((session) => session.session_id === selectedSessionId)) {
        const selected = agentSessions.find((session) => session.selected) || agentSessions[0];
        selectedSessionId = selected ? selected.session_id : "";
      }
      renderSessionSwitcher();
      updateAgentControls();
      const hasProjectContext = Boolean(activationRoot);
      const hasStageTarget = Boolean(activeProjectRoot);
      const workflowStage = payload.workflow_stage || (hasStageTarget ? "requirements" : "project");
      currentWorkflowStage = workflowStage;
      if (!projectPath.value) {
        projectPath.value = activeProjectRoot || activationRoot || serviceRoot;
      }
      setConnected();
      updateStageNodes(hasProjectContext, hasStageTarget, workflowStage);
      openProject.disabled = hasProjectContext;
      newProject.disabled = hasProjectContext;
      openMetaProject.disabled = hasProjectContext;
      newMetaProject.disabled = hasProjectContext;
      addMetaRepository.disabled = activeProjectMode !== "meta";
      startMetaRepository.disabled =
        activeProjectMode !== "meta" || registeredRepositories.length === 0;
      removeMetaRepository.disabled =
        activeProjectMode !== "meta" || registeredRepositories.length === 0;
      workItemMenuButton.disabled = !hasStageTarget;
      workItemMenuButton.textContent = activeProjectMenuLabel();
      newFeatureWorkItem.disabled = !hasStageTarget;
      switchFeatureWorkItem.disabled = !hasStageTarget;
      newBugWorkItem.disabled = !hasStageTarget;
      switchBugWorkItem.disabled = !hasStageTarget;
      deactivateProject.disabled = !hasProjectContext;
      renderMetaRepositoryMenus();
      renderWorkItemMenus();
      updateRequirementsMenuState();
      updateDesignMenuState();
      updateDesignReviewMenuState();
      updateGenericStageMenuStates();
      updateDocumentMenuState();
      updateCreativeBinderActions();
      if (restoredScratchContextId !== contextId) {
        restoreScratchPad();
      }
      syncProjectShellPane();
      if (creativeModeActive()) {
        applyCreativeWorkspace();
        if (!options.deferCreativeWorkspaceInit) {
          ensureCreativeWorkspaceLoaded();
        }
      } else {
        syncArtifactPreviewWithProject();
      }
      projectStatus.textContent = projectStatusLine();
      queueProjectStatusRefresh();
    }

    function activeProjectMenuLabel() {
      if (!activeProjectRoot) {
        return "Project";
      }
      if (activeProjectMode === "meta" && activeRepositoryName) {
        return activeRepositoryName;
      }
      return basename(activeProjectRoot || activationRoot || "Project");
    }

    function basename(path) {
      const normalized = String(path || "").replace(/[/]+$/, "");
      const parts = normalized.split(/[\\/]+/).filter(Boolean);
      return parts.length ? parts[parts.length - 1] : normalized || "Project";
    }

    function recentProjectsForWorkflow() {
      if (creativeModeActive()) {
        return recentProjects.filter((recent) => recent.kind === "creative");
      }
      return recentProjects.filter((recent) => recent.kind !== "creative");
    }

    function recentProjectLabel(recent) {
      const label = recent.label || basename(recent.path || "");
      if (recent.kind === "meta") {
        return `Meta: ${label}`;
      }
      if (recent.kind === "creative") {
        return `Creative: ${label}`;
      }
      return `Project: ${label}`;
    }

    function recentProjectActionsForWorkflow() {
      const entries = recentProjectsForWorkflow();
      if (entries.length === 0) {
        return [
          {
            label: "No recent projects",
            title: "No projects have been opened in this service yet.",
            disabled: true,
          },
        ];
      }
      return entries.map((recent) => ({
        label: recentProjectLabel(recent),
        title: recent.path || recentProjectLabel(recent),
        disabled: Boolean(activationRoot),
        run: () => openRecentProject(recent),
      }));
    }

    async function openRecentProject(recent) {
      const path = String((recent && recent.path) || "").trim();
      if (!path || activationRoot) {
        return;
      }
      projectMode = "open";
      await applyProjectSelection(path);
    }

    function projectStatusLine() {
      if (!activationRoot) {
        return "";
      }
      if (activeProjectMode === "meta") {
        if (activeProjectRoot) {
          return appendWorkItemStatus(
            `meta: ${activationRoot} · active repo: ${activeRepositoryName || activeProjectRoot}`,
          );
        }
        return activeRepositoryName
          ? `meta: ${activationRoot} · active repo: ${activeRepositoryName} (not initialized)`
          : `meta: ${activationRoot} · active repo: none`;
      }
      return appendWorkItemStatus(`active: ${activeProjectRoot || activationRoot}`);
    }

    function appendWorkItemStatus(line) {
      const parts = [];
      const feature = activeWorkItemFeature();
      const bug = activeWorkItemBug();
      if (feature) {
        parts.push(`feature: ${feature.name || feature.slug}`);
      }
      if (bug) {
        parts.push(`bug resolution: ${bug.title || bug.slug}`);
      }
      return parts.length ? `${line} · ${parts.join(" · ")}` : line;
    }

    function workItemFeatures() {
      return Array.isArray(workItemState.features) ? workItemState.features : [];
    }

    function workItemBugs() {
      return Array.isArray(workItemState.bugs) ? workItemState.bugs : [];
    }

    function activeWorkItemFeature() {
      const activeSlug = workItemState.active_feature_slug || "";
      return workItemFeatures().find((feature) => feature.slug === activeSlug) || null;
    }

    function activeWorkItemBug() {
      const activeSlug = workItemState.active_bug_slug || "";
      return workItemBugs().find((bug) => bug.slug === activeSlug) || null;
    }

    function repositoryLabel(repository) {
      const name = String(repository.name || "");
      const path = String(repository.path || "");
      return name || path || "repo";
    }

    function renderMetaRepositoryMenus() {
      renderMetaRepositoryMenu(startMetaRepositorySubmenu, startMetaRepositoryFromMenu);
      renderMetaRepositoryMenu(removeMetaRepositorySubmenu, removeMetaRepositoryFromMenu);
      if (startMetaRepository.disabled) {
        hideSubmenu(startMetaRepositorySubmenu, startMetaRepository);
      }
      if (removeMetaRepository.disabled) {
        hideSubmenu(removeMetaRepositorySubmenu, removeMetaRepository);
      }
    }

    function renderWorkItemMenus() {
      renderFeatureMenu();
      renderBugMenu();
      if (workItemMenuButton.disabled) {
        hideSubmenu(workItemSubmenu, workItemMenuButton);
      }
      if (switchFeatureWorkItem.disabled) {
        hideSubmenu(switchFeatureWorkItemSubmenu, switchFeatureWorkItem);
      }
      if (switchBugWorkItem.disabled) {
        hideSubmenu(switchBugWorkItemSubmenu, switchBugWorkItem);
      }
    }

    function renderFeatureMenu() {
      switchFeatureWorkItemSubmenu.replaceChildren();
      const features = workItemFeatures();
      if (features.length === 0) {
        appendDisabledMenuItem(switchFeatureWorkItemSubmenu, "No features");
        return;
      }
      for (const feature of features) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = featureLabel(feature);
        button.title = feature.title || feature.slug || "";
        button.classList.toggle(
          "active-repo",
          feature.slug === workItemState.active_feature_slug,
        );
        button.addEventListener("click", () => switchFeatureWorkItemContext(feature.slug));
        switchFeatureWorkItemSubmenu.append(button);
      }
    }

    function renderBugMenu() {
      switchBugWorkItemSubmenu.replaceChildren();
      const bugs = workItemBugs();
      if (bugs.length === 0) {
        appendDisabledMenuItem(switchBugWorkItemSubmenu, "No bug resolutions");
        return;
      }
      for (const bug of bugs) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = bug.title || bug.slug || "Bug";
        button.title = bug.reference || bug.slug || "";
        button.classList.toggle("active-repo", bug.slug === workItemState.active_bug_slug);
        button.addEventListener("click", () => switchBugWorkItemContext(bug.slug));
        switchBugWorkItemSubmenu.append(button);
      }
    }

    function appendDisabledMenuItem(menu, label) {
      const emptyButton = document.createElement("button");
      emptyButton.type = "button";
      emptyButton.disabled = true;
      emptyButton.textContent = label;
      menu.append(emptyButton);
    }

    function featureLabel(feature) {
      const label = feature.name || feature.slug || "Feature";
      return feature.parent_slug ? `${label} (subfeature)` : label;
    }

    function renderMetaRepositoryMenu(submenu, handler) {
      submenu.replaceChildren();
      if (registeredRepositories.length === 0) {
        const emptyButton = document.createElement("button");
        emptyButton.type = "button";
        emptyButton.disabled = true;
        emptyButton.textContent = "No repos";
        submenu.append(emptyButton);
        return;
      }
      for (const repository of registeredRepositories) {
        const button = document.createElement("button");
        const label = repositoryLabel(repository);
        const path = String(repository.path || "");
        button.type = "button";
        button.className = "repo-menu-item";
        button.textContent = label;
        button.title = path || label;
        button.classList.toggle("active-repo", label === activeRepositoryName);
        button.addEventListener("click", () => handler(repository));
        submenu.append(button);
      }
    }

    function selectedSession() {
      return agentSessions.find((session) => session.session_id === selectedSessionId) || null;
    }

    function sessionIsRunning(session) {
      return session && session.status === "running";
    }

    function selectedSessionAcceptsInput() {
      const session = selectedSession();
      return Boolean(session && session.interactive && sessionIsRunning(session));
    }

    function updateSessionIndicator(session) {
      const status = session ? session.status || "done" : "idle";
      let className = "agent-session-indicator";
      if (status === "running") {
        className += " running";
      } else if (status === "error" || status === "failed") {
        className += " error";
      } else if (session) {
        className += " done";
      }
      agentSessionIndicator.className = className;
      agentSessionIndicator.title = session
        ? agentSessionDisplayLabel(session)
        : "No selected agent";
    }

    function sessionMetadata(session) {
      return session && session.metadata && typeof session.metadata === "object"
        ? session.metadata
        : {};
    }

    function documentTargetKey(target) {
      return String(target && target.path ? target.path : "").trim();
    }

    function documentTargetLabel(target) {
      return String((target && (target.label || target.path)) || "Document");
    }

    function documentTargetForSession(session) {
      const metadata = sessionMetadata(session);
      const path = String(metadata.document_path || "").trim();
      if (!path) {
        return null;
      }
      const fallback = documentTargetFromInput(path) || { label: path, path };
      return {
        label: String(metadata.document_label || fallback.label || path),
        path,
      };
    }

    function documentationSessionForTarget(target) {
      const path = documentTargetKey(target);
      if (!path) {
        return null;
      }
      return (
        agentSessions.find((session) => {
          const sessionTarget = documentTargetForSession(session);
          return sessionTarget && sessionTarget.path === path;
        }) || null
      );
    }

    function agentSessionDisplayLabel(session) {
      const status = session.status === "running" ? "running" : session.status || "done";
      const documentTarget = documentTargetForSession(session);
      if (documentTarget) {
        return `Document: ${documentTargetLabel(documentTarget)} · ${status}`;
      }
      return `${session.kind || "agent"} · ${status}`;
    }

    function rememberOpenDocumentTarget(target) {
      const path = documentTargetKey(target);
      if (!path) {
        return;
      }
      const storedTarget = {
        label: documentTargetLabel(target),
        path,
      };
      const existingIndex = openDocumentTargets.findIndex(
        (candidate) => documentTargetKey(candidate) === path,
      );
      if (existingIndex >= 0) {
        openDocumentTargets.splice(existingIndex, 1, storedTarget);
      } else {
        openDocumentTargets.push(storedTarget);
      }
    }

    function syncOpenDocumentTargetsFromSessions() {
      for (const session of agentSessions) {
        const target = documentTargetForSession(session);
        if (target) {
          rememberOpenDocumentTarget(target);
        }
      }
      refreshDocumentTargetSwitchers();
    }

    function renderDocumentTargetSwitcher(select) {
      select.replaceChildren();
      const targets = openDocumentTargets.length > 0
        ? openDocumentTargets
        : artifactPreviewDocumentTarget
          ? [artifactPreviewDocumentTarget]
          : [];
      for (const target of targets) {
        const option = document.createElement("option");
        option.value = target.path;
        option.textContent = documentTargetLabel(target);
        select.append(option);
      }
      select.value = documentTargetKey(artifactPreviewDocumentTarget);
      select.disabled = targets.length <= 1;
    }

    function refreshDocumentTargetSwitchers() {
      for (const select of artifactPreviewStack.querySelectorAll(
        ".document-target-switcher",
      )) {
        renderDocumentTargetSwitcher(select);
      }
    }

    function renderSessionSwitcher() {
      sessionSwitcher.replaceChildren();
      if (agentSessions.length === 0) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "No streams";
        sessionSwitcher.append(option);
        sessionSwitcher.disabled = true;
        updateSessionIndicator(null);
        return;
      }
      for (const session of agentSessions) {
        const option = document.createElement("option");
        option.value = session.session_id;
        option.textContent = agentSessionDisplayLabel(session);
        sessionSwitcher.append(option);
      }
      sessionSwitcher.disabled = false;
      if (!agentSessions.some((session) => session.session_id === selectedSessionId)) {
        const selected = agentSessions.find((session) => session.selected) || agentSessions[0];
        selectedSessionId = selected ? selected.session_id : "";
      }
      sessionSwitcher.value = selectedSessionId;
      updateSessionIndicator(selectedSession());
    }

    async function selectAgentSession(sessionId) {
      if (!sessionId || sessionId === selectedSessionId) {
        return;
      }
      const response = await fetch(contextUrl("/api/sessions/select"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      const payload = await response.json().catch(() => ({ error: "session switch failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "session switch failed"}\\n`, "error");
        renderSessionSwitcher();
        return;
      }
      agentSessions = Array.isArray(payload.sessions) ? payload.sessions : agentSessions;
      selectedSessionId = payload.selected_session_id || sessionId;
      syncOpenDocumentTargetsFromSessions();
      renderSessionSwitcher();
      const session = selectedSession();
      activeAgentKind = session ? session.kind || "" : "";
      const documentTarget = documentTargetForSession(session);
      if (documentTarget) {
        showDocumentPreview(documentTarget);
      }
      clearAgentOutput();
      connectSessionEvents(selectedSessionId);
      updateAgentControls();
      sendTerminalResize();
    }

    function showSubmenu(submenu, button) {
      if (button.disabled) {
        return;
      }
      submenu.hidden = false;
      button.setAttribute("aria-expanded", "true");
    }

    function hideSubmenu(submenu, button) {
      submenu.hidden = true;
      button.setAttribute("aria-expanded", "false");
    }

    function toggleSubmenu(submenu, button) {
      if (submenu.hidden) {
        showSubmenu(submenu, button);
      } else {
        hideSubmenu(submenu, button);
      }
    }

    function updateStageNodes(hasProjectContext, hasStageTarget, workflowStage) {
      for (const stageNode of stageNodes) {
        const stageId = stageNode.dataset.stage || "";
        const isProject = stageId === "project";
        const isSidecar = stageId === "document";
        const isActive = isProject
          ? !hasProjectContext
          : hasStageTarget && !isSidecar && stageId === workflowStage;
        const isEnabled = isProject || hasStageTarget;
        const isComplete = isProject && hasProjectContext;
        stageNode.disabled = !isEnabled;
        stageNode.setAttribute("aria-disabled", isEnabled ? "false" : "true");
        stageNode.classList.toggle("disabled", !isEnabled);
        stageNode.classList.toggle("available", isEnabled && !isActive && !isComplete);
        stageNode.classList.toggle("active", isActive);
        stageNode.classList.toggle("complete", isComplete);
        stageNode.classList.toggle("sidecar", isSidecar);
      }
    }

    function updateRequirementsMenuState() {
      const hasActiveProject = Boolean(activeProjectRoot);
      const inRequirementsStage = currentWorkflowStage === "requirements";
      setRequirementsStage.disabled = !hasActiveProject || inRequirementsStage;
      startRequirements.disabled =
        !hasActiveProject || !inRequirementsStage || requirementsRunning;
      approveRequirements.disabled = !hasActiveProject || !inRequirementsStage;
      skipRequirementsApproval.disabled = !hasActiveProject || !inRequirementsStage;
    }

    function updateDesignMenuState() {
      const hasActiveProject = Boolean(activeProjectRoot);
      const inDesignStage = currentWorkflowStage === "design";
      setDesignStage.disabled = !hasActiveProject || inDesignStage;
      startDesign.disabled = !hasActiveProject || !inDesignStage || designRunning;
      completeDesign.disabled = !hasActiveProject || !inDesignStage;
    }

    function updateDesignReviewMenuState() {
      const hasActiveProject = Boolean(activeProjectRoot);
      const inDesignReviewStage = currentWorkflowStage === "design-review";
      setDesignReviewStage.disabled = !hasActiveProject || inDesignReviewStage;
      startAutomaticDesignReview.disabled =
        !hasActiveProject || !inDesignReviewStage || designReviewRunning;
      startInteractiveDesignReview.disabled =
        !hasActiveProject || !inDesignReviewStage || designReviewRunning;
      stopDesignReview.disabled =
        !hasActiveProject || !inDesignReviewStage || !designReviewRunning;
      approveDesignReview.disabled = !hasActiveProject || !inDesignReviewStage;
      skipDesignReviewApproval.disabled = !hasActiveProject || !inDesignReviewStage;
    }

    function updateGenericStageMenuStates() {
      updateAuthoringStageMenuState(
        "implementation-plan",
        setImplementationPlanStage,
        startImplementationPlan,
        approveImplementationPlan,
        skipImplementationPlanApproval,
      );
      updateAutomaticStageMenuState(
        "code",
        setCodeStage,
        startAutomaticCode,
        startInteractiveCode,
        stopCode,
        approveCode,
        skipCodeApproval,
      );
      startCodeAdHocAgentButton.disabled = !Boolean(activeProjectRoot);
      startCodeAdHocAgentButton.textContent = adHocRunning
        ? "Focus ad-hoc"
        : "Start ad-hoc";
      updateAuthoringStageMenuState(
        "test-plan",
        setTestPlanStage,
        startTestPlan,
        approveTestPlan,
        skipTestPlanApproval,
      );
      updateAutomaticStageMenuState(
        "validate",
        setValidateStage,
        startAutomaticValidate,
        startInteractiveValidate,
        stopValidate,
        approveValidate,
        skipValidateApproval,
      );
    }

    function updateAuthoringStageMenuState(
      stage,
      setStageButton,
      startButton,
      approveButton,
      skipButton,
    ) {
      const hasActiveProject = Boolean(activeProjectRoot);
      const inStage = currentWorkflowStage === stage;
      const runState = genericStageRun(stage);
      setStageButton.disabled = !hasActiveProject || inStage;
      startButton.disabled = !hasActiveProject || !inStage || runState.running;
      approveButton.disabled = !hasActiveProject || !inStage;
      skipButton.disabled = !hasActiveProject || !inStage;
    }

    function updateAutomaticStageMenuState(
      stage,
      setStageButton,
      startAutomaticButton,
      startInteractiveButton,
      stopButton,
      approveButton,
      skipButton,
    ) {
      const hasActiveProject = Boolean(activeProjectRoot);
      const inStage = currentWorkflowStage === stage;
      const runState = genericStageRun(stage);
      setStageButton.disabled = !hasActiveProject || inStage;
      startAutomaticButton.disabled =
        !hasActiveProject || !inStage || runState.running;
      startInteractiveButton.disabled =
        !hasActiveProject || !inStage || runState.running;
      stopButton.disabled = !hasActiveProject || !inStage || !runState.running;
      approveButton.disabled = !hasActiveProject || !inStage;
      skipButton.disabled = !hasActiveProject || !inStage;
    }

    function genericStageRun(stage) {
      return stageRunState[stage] || { started: false, running: false, interactive: false };
    }

    function updateDocumentMenuState() {
      const hasActiveProject = Boolean(activeProjectRoot);
      createDocumentTarget.disabled = !hasActiveProject;
      addDocumentTarget.disabled = !hasActiveProject;
      customDocumentName.disabled = !hasActiveProject;
      renderDocumentTargets();
      refreshStageActionPanel();
    }

    function refreshStageActionPanel() {
      renderStageActionPanel();
    }

    function showStageActionPanel(stageId) {
      expandedWorkflowStages.add(stageId);
      hideStageMenus();
      setWorkflowSideSheetCollapsed(false);
      renderStageActionPanel();
    }

    function hideStageActionPanel() {
      expandedWorkflowStages.clear();
      expandedProjectActionGroups.clear();
      stageActionBody.replaceChildren();
    }

    function stageActionName(stageId) {
      if (stageId === "project") {
        return "Project";
      }
      return stageId;
    }

    function renderStageActionPanel() {
      stageActionBody.replaceChildren();
      for (const stageNode of stageNodes) {
        const stageId = stageNode.dataset.stage || "";
        if (!stageId) {
          continue;
        }
        stageActionBody.append(stageActionGroup(stageId, stageNode));
      }
    }

    function stageActionGroup(stageId, stageNode) {
      const group = document.createElement("div");
      group.className = "stage-action-group";

      const trigger = document.createElement("button");
      trigger.type = "button";
      trigger.className = "stage-action-stage";
      const isExpanded = expandedWorkflowStages.has(stageId);
      trigger.classList.toggle("active", stageNode.classList.contains("active"));
      trigger.classList.toggle("complete", stageNode.classList.contains("complete"));
      trigger.classList.toggle("expanded", isExpanded);
      trigger.disabled = stageNode.disabled;
      trigger.title = STAGE_DESCRIPTIONS[stageId] || stageId;
      trigger.setAttribute("aria-expanded", isExpanded ? "true" : "false");

      const label = document.createElement("span");
      label.className = "stage-action-label";
      label.textContent = stageActionName(stageId);
      const chevron = document.createElement("span");
      chevron.className = "stage-action-chevron";
      chevron.setAttribute("aria-hidden", "true");
      trigger.append(label, chevron);
      trigger.addEventListener("click", () => toggleStageActionGroup(stageId));
      group.append(trigger);

      if (isExpanded) {
        const list = document.createElement("div");
        list.className = "stage-action-list";
        list.setAttribute("role", "group");
        if (stageId === "document") {
          renderDocumentActionPanel(list);
        } else {
          renderStageActionList(list, stageActions(stageId));
        }
        group.append(list);
      }
      return group;
    }

    function toggleStageActionGroup(stageId) {
      const stageNode = stageNodes.find((node) => node.dataset.stage === stageId);
      if (!stageNode || stageNode.disabled) {
        return;
      }
      if (expandedWorkflowStages.has(stageId)) {
        expandedWorkflowStages.delete(stageId);
      } else {
        expandedWorkflowStages.add(stageId);
      }
      setWorkflowSideSheetCollapsed(false);
      renderStageActionPanel();
    }

    function renderStageActionList(container, actions) {
      for (const action of actions) {
        if (action.subgroup) {
          container.append(stageActionSubgroup(action));
          continue;
        }
        if (action.heading) {
          const heading = document.createElement("div");
          heading.className = "stage-action-heading";
          heading.textContent = action.heading;
          container.append(heading);
          continue;
        }
        container.append(stageActionButton(action));
      }
    }

    function stageActionSubgroup(action) {
      const group = document.createElement("div");
      group.className = "stage-action-subgroup";
      const isExpanded = expandedProjectActionGroups.has(action.subgroup);

      const trigger = document.createElement("button");
      trigger.type = "button";
      trigger.className = "stage-action-subgroup-trigger";
      trigger.classList.toggle("expanded", isExpanded);
      trigger.disabled = Boolean(action.disabled);
      trigger.title = action.title || action.label;
      trigger.setAttribute("aria-expanded", isExpanded ? "true" : "false");

      const label = document.createElement("span");
      label.className = "stage-action-label";
      label.textContent = action.label;
      const chevron = document.createElement("span");
      chevron.className = "stage-action-chevron";
      chevron.setAttribute("aria-hidden", "true");
      trigger.append(label, chevron);
      trigger.addEventListener("click", () => toggleProjectActionGroup(action.subgroup));
      group.append(trigger);

      if (isExpanded) {
        const list = document.createElement("div");
        list.className = "stage-action-subgroup-list";
        list.setAttribute("role", "group");
        renderStageActionList(list, action.actions || []);
        group.append(list);
      }
      return group;
    }

    function toggleProjectActionGroup(groupId) {
      if (expandedProjectActionGroups.has(groupId)) {
        expandedProjectActionGroups.delete(groupId);
      } else {
        expandedProjectActionGroups.add(groupId);
      }
      renderStageActionPanel();
    }

    function stageActionButton(action) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "stage-action-button";
      if (action.primary) {
        button.classList.add("primary");
      }
      button.textContent = action.label;
      button.title = action.title || action.label;
      button.disabled = Boolean(
        typeof action.disabled === "function" ? action.disabled() : action.disabled,
      );
      button.addEventListener("click", () => runStageAction(action));
      return button;
    }

    function runStageAction(action) {
      if (!action || typeof action.run !== "function") {
        return;
      }
      const disabled = Boolean(
        typeof action.disabled === "function" ? action.disabled() : action.disabled,
      );
      if (disabled) {
        return;
      }
      Promise.resolve(action.run()).catch((error) => {
        appendOutput(`action failed: ${error}\\n`, "error");
      });
    }

    function stageActions(stageId) {
      if (stageId === "project") {
        return projectStageActions();
      }
      if (stageId === "requirements") {
        const inStage = currentWorkflowStage === "requirements";
        return [
          {
            label: "Set stage",
            title: "Move the workflow to requirements without starting an agent.",
            disabled: !activeProjectRoot || inStage,
            run: () => setWorkflowStageFromMenu("requirements"),
          },
          {
            label: "Start",
            title: "Launch or resume the interactive requirements authoring agent.",
            primary: true,
            disabled: !activeProjectRoot || !inStage || requirementsRunning,
            run: startRequirementsAgent,
          },
          {
            label: "Approve",
            title: "Record requirements approval and advance the workflow.",
            disabled: !activeProjectRoot || !inStage,
            run: approveRequirementsStage,
          },
          {
            label: "Skip approval",
            title: "Force requirements approval when the operator accepts the risk.",
            disabled: !activeProjectRoot || !inStage,
            run: skipRequirementsApprovalStage,
          },
        ];
      }
      if (stageId === "design") {
        const inStage = currentWorkflowStage === "design";
        return [
          {
            label: "Set stage",
            title: "Move the workflow to design without starting an agent.",
            disabled: !activeProjectRoot || inStage,
            run: () => setWorkflowStageFromMenu("design"),
          },
          {
            label: "Start",
            title: "Launch or resume the interactive design authoring agent.",
            primary: true,
            disabled: !activeProjectRoot || !inStage || designRunning,
            run: startDesignAgent,
          },
          {
            label: "Complete",
            title: "Finish design authoring and move to design review.",
            disabled: !activeProjectRoot || !inStage,
            run: completeDesignAgent,
          },
        ];
      }
      if (stageId === "design-review") {
        const inStage = currentWorkflowStage === "design-review";
        return automaticStageActions({
          stage: "design-review",
          label: "design review",
          inStage,
          running: designReviewRunning,
          setStage: () => setWorkflowStageFromMenu("design-review"),
          startAutomatic: startAutomaticDesignReviewAgent,
          startInteractive: startInteractiveDesignReviewAgent,
          stop: stopDesignReviewAgent,
          approve: approveDesignReviewStage,
          skip: skipDesignReviewApprovalStage,
          automaticTitle: "Run the non-interactive design review and design-update loop.",
          interactiveTitle: "Open an interactive design-review agent session.",
        });
      }
      if (stageId === "implementation-plan") {
        return authoringStageActions({
          stage: "implementation-plan",
          label: "implementation plan",
          setStage: () => setWorkflowStageFromMenu("implementation-plan"),
          start: () => startGenericStageAgent(
            "implementation-plan",
            "$ electroboy implementation-plan",
            true,
          ),
          approve: () => approveGenericStage("implementation-plan", "implementation plan"),
          skip: () => skipGenericStageApproval("implementation-plan", "Implementation plan"),
          startTitle: "Launch or resume the interactive implementation-plan agent.",
        });
      }
      if (stageId === "code") {
        const actions = automaticStageActions({
          stage: "code",
          label: "code",
          inStage: currentWorkflowStage === "code",
          running: genericStageRun("code").running,
          setStage: () => setWorkflowStageFromMenu("code"),
          startAutomatic: () => startGenericStageAgent("code", "$ electroboy code", false),
          startInteractive: () => startGenericStageAgent(
            "code",
            "$ electroboy code --interactive",
            true,
          ),
          stop: () => stopGenericStageAgent("code", "code"),
          approve: () => approveGenericStage("code", "code"),
          skip: () => skipGenericStageApproval("code", "Code"),
          automaticTitle: "Run the non-interactive coding and review cycle.",
          interactiveTitle: "Open an interactive coding agent session.",
        });
        actions.splice(3, 0, {
          label: adHocRunning ? "Focus ad-hoc" : "Start ad-hoc",
          title: adHocRunning
            ? "Focus the running ad-hoc agent."
            : "Start a plain interactive agent without staged workflow instructions.",
          disabled: !activeProjectRoot,
          run: startAdHocAgent,
        });
        return actions;
      }
      if (stageId === "test-plan") {
        return authoringStageActions({
          stage: "test-plan",
          label: "test plan",
          setStage: () => setWorkflowStageFromMenu("test-plan"),
          start: () => startGenericStageAgent("test-plan", "$ electroboy test-plan", true),
          approve: () => approveGenericStage("test-plan", "test plan"),
          skip: () => skipGenericStageApproval("test-plan", "Test plan"),
          startTitle: "Launch or resume the interactive system test-plan agent.",
        });
      }
      if (stageId === "validate") {
        return automaticStageActions({
          stage: "validate",
          label: "validation",
          inStage: currentWorkflowStage === "validate",
          running: genericStageRun("validate").running,
          setStage: () => setWorkflowStageFromMenu("validate"),
          startAutomatic: () => startGenericStageAgent("validate", "$ electroboy validate", false),
          startInteractive: () => startGenericStageAgent(
            "validate",
            "$ electroboy validate --interactive",
            true,
          ),
          stop: () => stopGenericStageAgent("validate", "validation"),
          approve: () => approveGenericStage("validate", "validation"),
          skip: () => skipGenericStageApproval("validate", "Validation"),
          automaticTitle: "Run the non-interactive validation command set.",
          interactiveTitle: "Open an interactive validation agent session.",
        });
      }
      return [];
    }

    function projectStageActions() {
      const hasContext = Boolean(activationRoot);
      const hasProject = Boolean(activeProjectRoot);
      const recentActions = recentProjectActionsForWorkflow();
      const metaActions = [
        {
          label: "Open meta-project",
          title: "Activate an existing ElectroBoy meta-project.",
          disabled: hasContext,
          run: () => openProjectBrowser("open", true),
        },
        {
          label: "New meta-project",
          title: "Create and activate a new ElectroBoy meta-project.",
          disabled: hasContext,
          run: () => openProjectBrowser("meta-new", true),
        },
        {
          label: "Add repo",
          title: "Register another repository with the active meta-project.",
          disabled: activeProjectMode !== "meta",
          run: () => showProjectPanel("meta-add"),
        },
      ];
      for (const repository of registeredRepositories) {
        const label = repositoryLabel(repository);
        metaActions.push({
          label: `Start repo: ${label}`,
          title: String(repository.path || label),
          disabled: activeProjectMode !== "meta" || label === activeRepositoryName,
          run: () => startMetaRepositoryFromMenu(repository),
        });
      }
      for (const repository of registeredRepositories) {
        const label = repositoryLabel(repository);
        metaActions.push({
          label: `Remove repo: ${label}`,
          title: String(repository.path || label),
          disabled: activeProjectMode !== "meta",
          run: () => removeMetaRepositoryFromMenu(repository),
        });
      }

      const workItemActions = [
        {
          label: "Add feature",
          title: "Start a new feature workflow in the active project.",
          disabled: !hasProject,
          run: () => showWorkItemPanel("feature-new"),
        },
        {
          label: "Add bug resolution",
          title: "Start a new bug-resolution workflow in the active project.",
          disabled: !hasProject,
          run: () => showWorkItemPanel("bug-new"),
        },
      ];
      for (const feature of workItemFeatures()) {
        workItemActions.push({
          label: `Switch feature: ${featureLabel(feature)}`,
          title: feature.title || feature.slug || "",
          disabled: !hasProject || feature.slug === workItemState.active_feature_slug,
          run: () => switchFeatureWorkItemContext(feature.slug),
        });
      }
      for (const bug of workItemBugs()) {
        workItemActions.push({
          label: `Switch bug: ${bug.title || bug.slug || "Bug"}`,
          title: bug.reference || bug.slug || "",
          disabled: !hasProject || bug.slug === workItemState.active_bug_slug,
          run: () => switchBugWorkItemContext(bug.slug),
        });
      }

      return [
        {
          label: "Open project",
          title: "Activate an existing ElectroBoy project.",
          disabled: hasContext,
          run: () => openProjectBrowser("open", true),
        },
        {
          label: "New project",
          title: "Create and activate a new ElectroBoy project.",
          disabled: hasContext,
          run: () => openProjectBrowser("new", true),
        },
        {
          subgroup: "project-recent",
          label: "Recently opened",
          title: "Open a recently used project.",
          actions: recentActions,
        },
        {
          subgroup: "project-meta",
          label: "Meta project",
          title: "Open, create, or manage repositories in a meta-project.",
          actions: metaActions,
        },
        {
          subgroup: "project-work-items",
          label: "Work items",
          title: "Start or switch feature and bug-resolution workflows.",
          actions: workItemActions,
        },
        {
          label: "Deactivate",
          title: "Deactivate this browser context's active project.",
          disabled: !hasContext,
          run: deactivateActiveProject,
        },
      ];
    }

    function authoringStageActions(options) {
      const inStage = currentWorkflowStage === options.stage;
      const runState = genericStageRun(options.stage);
      return [
        {
          label: "Set stage",
          title: `Move the workflow to ${options.stage} without starting an agent.`,
          disabled: !activeProjectRoot || inStage,
          run: options.setStage,
        },
        {
          label: "Start",
          title: options.startTitle,
          primary: true,
          disabled: !activeProjectRoot || !inStage || runState.running,
          run: options.start,
        },
        {
          label: "Approve",
          title: `Approve ${options.label} and advance the workflow.`,
          disabled: !activeProjectRoot || !inStage,
          run: options.approve,
        },
        {
          label: "Skip approval",
          title: `Force ${options.label} approval when the operator accepts the risk.`,
          disabled: !activeProjectRoot || !inStage,
          run: options.skip,
        },
      ];
    }

    function automaticStageActions(options) {
      const hasProject = Boolean(activeProjectRoot);
      return [
        {
          label: "Set stage",
          title: `Move the workflow to ${options.stage} without starting an agent.`,
          disabled: !hasProject || options.inStage,
          run: options.setStage,
        },
        {
          label: "Start automatic",
          title: options.automaticTitle,
          primary: true,
          disabled: !hasProject || !options.inStage || options.running,
          run: options.startAutomatic,
        },
        {
          label: "Start interactive",
          title: options.interactiveTitle,
          disabled: !hasProject || !options.inStage || options.running,
          run: options.startInteractive,
        },
        {
          label: "Stop",
          title: `Stop the running ${options.label} agent.`,
          disabled: !hasProject || !options.inStage || !options.running,
          run: options.stop,
        },
        {
          label: "Approve",
          title: `Approve ${options.label} and advance the workflow.`,
          disabled: !hasProject || !options.inStage,
          run: options.approve,
        },
        {
          label: "Skip approval",
          title: `Force ${options.label} approval when the operator accepts the risk.`,
          disabled: !hasProject || !options.inStage,
          run: options.skip,
        },
      ];
    }

    function renderDocumentActionPanel(container) {
      container.append(
        stageActionButton({
          label: "Open",
          title: "Choose an existing Markdown file and start the documentation agent.",
          primary: true,
          disabled: !activeProjectRoot,
          run: openDocumentFileBrowser,
        }),
      );
      container.append(
        stageActionButton({
          label: "New",
          title: "Choose where to create a Markdown document and start the agent.",
          disabled: !activeProjectRoot,
          run: openNewDocumentFileBrowser,
        }),
      );
    }

    function allDocumentTargets() {
      const byPath = new Map();
      for (const target of [...DEFAULT_DOCUMENT_TARGETS, ...customDocumentTargets]) {
        byPath.set(target.path, target);
      }
      return Array.from(byPath.values());
    }

    function renderDocumentTargets() {
      documentTargets.replaceChildren();
      const disabled = !activeProjectRoot;
      for (const target of allDocumentTargets()) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = target.label;
        button.title = target.path;
        button.disabled = disabled;
        button.addEventListener("click", () => {
          launchDocumentTarget(target);
        });
        documentTargets.append(button);
      }
    }

    function documentTargetFromInput(value) {
      const raw = value.trim();
      if (!raw) {
        return null;
      }
      const path = raw.includes("/") || raw.endsWith(".md")
        ? raw
        : raw.toLowerCase() === "readme"
          ? "README.md"
        : `docs/${raw.replace(/\\s+/g, "-").toLowerCase()}.md`;
      const label = raw.replace(/\\.md$/i, "") || path;
      return { label, path };
    }

    function documentTargetFromSelectedPath(path) {
      const selected = String(path || "").trim();
      const root = String(activeProjectRoot || "").replace(/\/+$/, "");
      if (!selected) {
        return null;
      }
      let relativePath = selected;
      if (root && selected.startsWith(`${root}/`)) {
        relativePath = selected.slice(root.length + 1);
      }
      if (relativePath.startsWith("/")) {
        appendOutput(
          `document must be under the active project: ${selected}\\n`,
          "error",
        );
        return null;
      }
      return documentTargetFromInput(relativePath);
    }

    function registerDocumentTarget(target) {
      if (!target) {
        return;
      }
      customDocumentTargets = customDocumentTargets.filter(
        (existing) => existing.path !== target.path,
      );
      customDocumentTargets.push(target);
      saveDocumentTargets();
      renderDocumentTargets();
      refreshStageActionPanel();
    }

    function launchDocumentTarget(target) {
      if (!target) {
        return;
      }
      registerDocumentTarget(target);
      startDocumentationAgent(target);
    }

    function selectOpenDocumentTarget(path) {
      const target = openDocumentTargets.find(
        (candidate) => documentTargetKey(candidate) === path,
      );
      if (!target) {
        return;
      }
      const session = documentationSessionForTarget(target);
      if (session) {
        if (session.session_id === selectedSessionId) {
          showDocumentPreview(target);
          return;
        }
        selectAgentSession(session.session_id).catch((error) => {
          appendOutput(`session switch failed: ${error}\\n`, "error");
        });
        return;
      }
      launchDocumentTarget(target);
    }

    function startCustomDocumentTargetFromValue(value) {
      if (!activeProjectRoot) {
        return;
      }
      const target = documentTargetFromInput(value);
      if (!target) {
        return;
      }
      if (customDocumentName) {
        customDocumentName.value = "";
        customDocumentForm.hidden = true;
      }
      launchDocumentTarget(target);
    }

    function addCustomDocumentTarget() {
      startCustomDocumentTargetFromValue(customDocumentName.value);
    }

    function artifactKindForPane(item) {
      if (!item) {
        return "";
      }
      if (item.kind === "route") {
        return "route";
      }
      return item.kind || "";
    }

    function artifactRouteUrl(path, version = artifactPreviewVersion) {
      return `${contextUrl(`${path}?embed=1`)}&zoom=${documentZoom}&version=${version}`;
    }

    function artifactPreviewUrl(item) {
      if (!item) {
        return "";
      }
      if (item.kind === "requirements") {
        return artifactRouteUrl("/artifacts/requirements");
      }
      if (item.kind === "creative-corkboard") {
        const board = item.folder || item.corkboard;
        if (!board) {
          return "";
        }
        const parameters = new URLSearchParams();
        parameters.set("path", board.path);
        parameters.set("title", board.label || item.title);
        parameters.set("embed", "1");
        parameters.set("version", String(artifactPreviewVersion));
        return contextUrl(`/artifacts/creative-corkboard?${parameters.toString()}`);
      }
      if (item.kind === "route" && item.path) {
        return artifactRouteUrl(item.path);
      }
      if (item.kind === "document" && item.target) {
        const parameters = new URLSearchParams();
        parameters.set("path", item.target.path);
        parameters.set("title", item.target.label);
        parameters.set("embed", "1");
        parameters.set("create", "1");
        parameters.set("zoom", String(documentZoom));
        parameters.set("version", String(artifactPreviewVersion));
        return contextUrl(`/artifacts/document?${parameters.toString()}`);
      }
      return "";
    }

    function artifactEditUrl(item) {
      if (!item) {
        return "";
      }
      if (item.kind === "creative-corkboard") {
        return artifactPreviewUrl(item);
      }
      const parameters = new URLSearchParams();
      parameters.set("artifact", artifactKindForPane(item));
      parameters.set("document_zoom", String(documentZoom));
      parameters.set("font_size", String(artifactEditorFontSize()));
      if (item.kind === "document" && item.target) {
        parameters.set("path", item.target.path);
        parameters.set("title", item.target.label);
        parameters.set("create", "1");
      }
      if (item.kind === "route" && item.path) {
        parameters.set("path", item.path);
        parameters.set("title", item.title);
      }
      return contextUrl(`/artifacts/edit?${parameters.toString()}`);
    }

    function artifactPaneSupportsModeSwitch(item) {
      return item && item.kind !== "creative-corkboard";
    }

    function artifactPaneSupportsDocumentExport(item) {
      return item && item.kind !== "creative-corkboard";
    }

    function artifactPaneSupportsDocumentZoom(item) {
      return item && item.kind !== "creative-corkboard";
    }

    function artifactPreviewsForStage(stage) {
      return (STAGE_ARTIFACT_PREVIEWS[stage] || []).map((item) => ({ ...item }));
    }

    function setArtifactCompatibilityState(items) {
      const first = items[0] || null;
      artifactPreviewKind = first ? artifactKindForPane(first) : "";
      artifactPreviewDocumentTarget =
        first && first.kind === "document" && first.target ? first.target : null;
    }

    function showArtifactPreviews(items, options = {}) {
      if (!activeProjectRoot) {
        hideArtifactPreview();
        return;
      }
      const nextItems = items.filter((item) => artifactPreviewUrl(item));
      if (nextItems.length === 0) {
        hideArtifactPreview();
        return;
      }
      artifactPreviewItems = nextItems;
      manualArtifactPreview = Boolean(options.manual);
      manualArtifactPreviewStage = manualArtifactPreview ? currentWorkflowStage : "";
      artifactPreviewStage = options.stage || currentWorkflowStage;
      setArtifactCompatibilityState(nextItems);
      artifactPaneRequested = true;
      applyStoredArtifactPaneSize();
      renderArtifactPreviewItems();
      applyOutputPaneVisibility();
      connectArtifactEvents();
    }

    function showStageArtifactPreview(stage) {
      const previews = artifactPreviewsForStage(stage);
      if (previews.length === 0) {
        hideArtifactPreview();
        return;
      }
      showArtifactPreviews(previews, { stage });
    }

    function showArtifactPreview(kind, options = {}) {
      if (kind === "document") {
        const target = options.target || artifactPreviewDocumentTarget;
        if (!target) {
          return;
        }
        showArtifactPreviews(
          [
            {
              id: "document",
              kind: "document",
              title: target.label || target.path || "Document",
              target,
            },
          ],
          { manual: true },
        );
        return;
      }
      const item = kind === "requirements"
        ? { id: "requirements", kind: "requirements", title: "Requirements" }
        : null;
      if (item) {
        showArtifactPreviews([item], options);
      }
    }

    function showDocumentPreview(target) {
      if (!target) {
        return;
      }
      rememberOpenDocumentTarget(target);
      showArtifactPreview("document", { target });
      refreshDocumentTargetSwitchers();
    }

    function applyCreativeWorkspace() {
      scratchPad.spellcheck = true;
      setAgentInputVisible(true);
      showProgressPane(false);
      if (creativeActiveDocument) {
        if (creativePathIsCorkboard(creativeActiveDocument)) {
          showCreativeCorkboard(creativeActiveDocument, { freeform: true });
        } else {
          showCreativeDocument(creativeActiveDocument);
        }
      } else if (creativeActiveFolder) {
        showCreativeCorkboard(creativeActiveFolder);
      } else {
        artifactPaneRequested = true;
        applyOutputPaneVisibility();
      }
    }

    function restoreSoftwareWorkspace() {
      scratchPad.spellcheck = true;
      restoreScratchPad();
      syncArtifactPreviewWithProject();
    }

    function updateCreativeBinderActions() {
      const hasProject = Boolean(activeProjectRoot);
      creativeOpenProject.disabled = Boolean(activationRoot);
      creativeNewProject.disabled = Boolean(activationRoot);
      creativeCloseProject.disabled = !Boolean(activationRoot);
      creativeActiveProjectSection.hidden = !hasProject;
      creativeProjectName.textContent = hasProject
        ? `Project: ${basename(activeProjectRoot)}`
        : "";
      creativeStartAgent.disabled = !hasProject;
      updateCreativeActionGroup(
        creativeProjectActions,
        creativeProjectMenuButton,
        creativeProjectActionsExpanded,
      );
      updateCreativeActionGroup(
        creativeAgentActions,
        creativeAgentMenuButton,
        creativeAgentActionsExpanded,
      );
      renderCreativeRecentProjects();
    }

    function renderCreativeRecentProjects() {
      creativeRecentProjects.replaceChildren();
      const entries = recentProjectsForWorkflow();
      creativeRecentProjects.hidden = entries.length === 0;
      if (entries.length === 0) {
        return;
      }
      const heading = document.createElement("div");
      heading.className = "stage-action-heading";
      heading.textContent = "Recent";
      creativeRecentProjects.append(heading);
      for (const recent of entries) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "stage-action-button";
        button.textContent = basename(recent.path || recent.label || "Project");
        button.title = recent.path || recentProjectLabel(recent);
        button.disabled = Boolean(activationRoot);
        button.addEventListener("click", () => {
          openRecentProject(recent).catch((error) => {
            appendOutput(`action failed: ${error}\\n`, "error");
          });
        });
        creativeRecentProjects.append(button);
      }
    }

    function updateCreativeActionGroup(actions, button, expanded) {
      actions.hidden = !expanded;
      button.classList.toggle("expanded", expanded);
      button.setAttribute("aria-expanded", expanded ? "true" : "false");
    }

    function toggleCreativeActionGroup(group) {
      if (group === "project") {
        creativeProjectActionsExpanded = !creativeProjectActionsExpanded;
      } else if (group === "agent") {
        creativeAgentActionsExpanded = !creativeAgentActionsExpanded;
      }
      updateCreativeBinderActions();
    }

    async function refreshCreativeBinder() {
      if (!creativeModeActive()) {
        return;
      }
      updateCreativeBinderActions();
      if (!activeProjectRoot || !contextId) {
        showCreativeTreeMessage("Open or create a project to start writing.");
        return;
      }
      showCreativeTreeMessage("Loading Binder...");
      const response = await fetch(contextUrl("/api/creative/tree"), {
        cache: "no-store",
      });
      const payload = await response.json().catch(() => ({ error: "Binder failed" }));
      if (!response.ok) {
        showCreativeTreeMessage(payload.error || "Binder failed");
        return;
      }
      creativeTreePayload = payload;
      renderCreativeTree();
      if (!creativeActiveDocument) {
        const firstDocument = firstCreativeMarkdown(payload.entries || []);
        if (firstDocument) {
          selectCreativeDocument(firstDocument.path, { notifyAgent: false });
        }
      }
    }

    function firstCreativeMarkdown(entries) {
      for (const entry of entries) {
        if ((entry.type || "") === "file" && entry.markdown) {
          return entry;
        }
        const child = firstCreativeMarkdown(entry.children || []);
        if (child) {
          return child;
        }
      }
      return null;
    }

    function showCreativeTreeMessage(message) {
      creativeTree.replaceChildren();
      const empty = document.createElement("div");
      empty.className = "creative-binder-status";
      empty.textContent = message;
      creativeTree.append(empty);
    }

    function renderCreativeTree() {
      creativeTree.replaceChildren();
      const entries = creativeTreePayload && Array.isArray(creativeTreePayload.entries)
        ? creativeTreePayload.entries
        : [];
      if (entries.length === 0) {
        showCreativeTreeMessage("No writing documents yet.");
        return;
      }
      for (const entry of entries) {
        appendCreativeTreeEntry(entry, 0);
      }
    }

    function creativeTreeIconSvg(name) {
      const icons = {
        file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path>',
        folder: '<path d="M3 7h7l2 2h9v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>',
        "folder-open": '<path d="M3 7h7l2 2h9l-2 9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><path d="M3 7v11"></path>',
        markdown: '<rect x="3" y="5" width="18" height="14" rx="2"></rect><path d="M7 15V9l3 3 3-3v6"></path><path d="M17 9v6"></path><path d="M15 13l2 2 2-2"></path>',
        corkboard: '<rect x="4" y="4" width="16" height="16" rx="2"></rect><path d="M8 8h5v4H8z"></path><path d="M14 12h4v5h-4z"></path><path d="M8 14h4v3H8z"></path>',
      };
      return `<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.file}</svg>`;
    }

    function creativeTreeIconName(entry, expanded) {
      if ((entry.type || "") === "directory") {
        return expanded ? "folder-open" : "folder";
      }
      if (entry.corkboard) {
        return "corkboard";
      }
      return entry.markdown ? "markdown" : "file";
    }

    function creativeTreeIconClass(entry) {
      if ((entry.type || "") === "directory") {
        return "folder";
      }
      if (entry.corkboard) {
        return "corkboard";
      }
      return entry.markdown ? "markdown" : "file";
    }

    function creativeTreeActionIconSvg(name) {
      const icons = {
        rename: '<path d="m12 20h9"></path><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"></path>',
        trash: '<path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="m19 6-1 14H6L5 6"></path><path d="M10 11v5"></path><path d="M14 11v5"></path>',
      };
      return `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || ""}</svg>`;
    }

    function appendCreativeTreeEntry(entry, depth) {
      const type = entry.type || "file";
      const entryActionType = entry.corkboard ? "corkboard" : type;
      const path = String(entry.path || "");
      const isDirectory = type === "directory";
      const expanded = isDirectory && expandedCreativeFolders.has(path);
      const row = document.createElement("div");
      row.className = `creative-tree-row ${type}`;
      row.classList.toggle("expanded", expanded);
      row.style.setProperty("--creative-depth-indent", `${depth * 16}px`);
      row.title = path;
      row.tabIndex = 0;
      row.classList.toggle(
        "active",
        (isDirectory && path === creativeActiveFolder) ||
          (!isDirectory && path === creativeActiveDocument),
      );
      row.setAttribute("role", "treeitem");
      if (isDirectory) {
        row.setAttribute("aria-expanded", expanded ? "true" : "false");
      }

      const icon = document.createElement("span");
      icon.className = `creative-tree-icon ${creativeTreeIconClass(entry)}`;
      icon.innerHTML = creativeTreeIconSvg(creativeTreeIconName(entry, expanded));

      const name = creativeEditingPath === path
        ? creativeRenameInput(entry, type, path)
        : creativeTreeName(entry, path);

      const rename = creativeTreeIconButton(
        "rename",
        `Rename ${path}`,
        () => beginCreativeRename(path, entryActionType),
      );
      const remove = creativeTreeIconButton(
        "trash",
        `Delete ${path}`,
        () => deleteCreativeEntry(path, entryActionType),
        "danger",
      );

      if (isDirectory) {
        const disclosure = document.createElement("span");
        disclosure.className = "creative-tree-disclosure";
        disclosure.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          toggleCreativeFolder(path);
        });
        row.append(icon, name, rename, remove, disclosure);
      } else {
        row.append(icon, name, rename, remove);
      }
      row.addEventListener("click", () => activateCreativeTreeEntry(entry, path, type));
      row.addEventListener("dblclick", (event) => {
        event.preventDefault();
        beginCreativeRename(path, entryActionType);
      });
      row.addEventListener("keydown", (event) => {
        if (event.target !== row) {
          return;
        }
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activateCreativeTreeEntry(entry, path, type);
        } else if (event.key === "F2") {
          event.preventDefault();
          beginCreativeRename(path, entryActionType);
        } else if (event.key === "Delete") {
          event.preventDefault();
          deleteCreativeEntry(path, entryActionType);
        }
      });
      creativeTree.append(row);

      if (isDirectory && expanded) {
        for (const child of entry.children || []) {
          appendCreativeTreeEntry(child, depth + 1);
        }
        appendCreativeFolderActions(path, depth + 1);
      }
    }

    function creativeTreeName(entry, path) {
      const name = document.createElement("span");
      name.className = "creative-tree-name";
      name.textContent = String(entry.name || path || "Untitled");
      return name;
    }

    function creativeTreeIconButton(iconName, title, handler, extraClass = "") {
      const button = document.createElement("button");
      button.className = `creative-tree-icon-button ${extraClass}`.trim();
      button.type = "button";
      button.title = title;
      button.setAttribute("aria-label", title);
      button.innerHTML = creativeTreeActionIconSvg(iconName);
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        handler();
      });
      button.addEventListener("dblclick", (event) => {
        event.preventDefault();
        event.stopPropagation();
      });
      return button;
    }

    function activateCreativeTreeEntry(entry, path, type) {
      if (type === "directory") {
        selectCreativeFolder(path);
        return;
      }
      if (entry.corkboard) {
        selectCreativeCorkboard(path);
        return;
      }
      if (entry.markdown) {
        selectCreativeDocument(path);
        return;
      }
      appendOutput(`${path} is visible in the Binder but is not editable yet.\\n`, "system");
    }

    function creativeRenameInput(entry, type, path) {
      const input = document.createElement("input");
      input.className = "creative-tree-name-input";
      input.type = "text";
      input.value = String(entry.name || basename(path));
      input.setAttribute("aria-label", `Rename ${path}`);
      input.addEventListener("click", (event) => event.stopPropagation());
      input.addEventListener("dblclick", (event) => event.stopPropagation());
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          finishCreativeRename(path, type, input.value);
        } else if (event.key === "Escape") {
          event.preventDefault();
          cancelCreativeRename();
        }
      });
      input.addEventListener("blur", () => {
        finishCreativeRename(path, type, input.value);
      });
      window.requestAnimationFrame(() => {
        input.focus();
        input.select();
      });
      return input;
    }

    function appendCreativeFolderActions(path, depth) {
      const actions = document.createElement("div");
      actions.className = "creative-tree-actions";
      actions.style.setProperty("--creative-depth-indent", `${depth * 16}px`);

      const newFolder = document.createElement("button");
      newFolder.className = "creative-tree-action";
      newFolder.type = "button";
      newFolder.textContent = "New folder";
      newFolder.addEventListener("click", (event) => {
        event.stopPropagation();
        creativeActiveFolder = path;
        renderCreativeTree();
        createCreativeFolderInline(path);
      });

      const newFile = document.createElement("button");
      newFile.className = "creative-tree-action";
      newFile.type = "button";
      newFile.textContent = "New file";
      newFile.addEventListener("click", (event) => {
        event.stopPropagation();
        creativeActiveFolder = path;
        renderCreativeTree();
        createCreativeDocumentInline(path);
      });

      const newBoard = document.createElement("button");
      newBoard.className = "creative-tree-action";
      newBoard.type = "button";
      newBoard.textContent = "New board";
      newBoard.addEventListener("click", (event) => {
        event.stopPropagation();
        creativeActiveFolder = path;
        renderCreativeTree();
        createCreativeCorkboardInline(path);
      });

      actions.append(newFolder, newFile, newBoard);
      creativeTree.append(actions);
    }

    function toggleCreativeFolder(path) {
      if (!path) {
        return;
      }
      if (expandedCreativeFolders.has(path)) {
        expandedCreativeFolders.delete(path);
      } else {
        expandedCreativeFolders.add(path);
      }
      renderCreativeTree();
    }

    function showCreativeCorkboard(path, options = {}) {
      if (!path) {
        return;
      }
      const freeform = Boolean(options.freeform) || creativePathIsCorkboard(path);
      const label = freeform
        ? basename(path).replace(/\.corkboard\.json$/i, "")
        : basename(path);
      const board = {
        label,
        path,
      };
      const item = {
        id: `creative-corkboard-${path}`,
        kind: "creative-corkboard",
        title: `${freeform ? "Corkboard" : "Folder board"}: ${label}`,
        editing: false,
      };
      if (freeform) {
        item.corkboard = board;
      } else {
        item.folder = board;
      }
      showArtifactPreviews(
        [item],
        { manual: true, stage: "creative-writing" },
      );
    }

    function selectCreativeFolder(path) {
      if (!path) {
        return;
      }
      creativeActiveFolder = path;
      creativeActiveDocument = "";
      creativeLastNotifiedTarget = "";
      showCreativeCorkboard(path);
      renderCreativeTree();
      renderCreativeProjectStatus();
      notifyCreativeAgentTargetSwitch();
    }

    function selectCreativeCorkboard(path) {
      if (!path) {
        return;
      }
      creativeActiveDocument = path;
      creativeActiveFolder = creativeParentPath(path);
      creativeLastNotifiedTarget = "";
      showCreativeCorkboard(path, { freeform: true });
      renderCreativeTree();
      renderCreativeProjectStatus();
      notifyCreativeAgentTargetSwitch();
    }

    function showCreativeDocument(path) {
      if (!path) {
        return;
      }
      const target = {
        label: basename(path),
        path,
      };
      showArtifactPreviews(
        [
          {
            id: "creative-document",
            kind: "document",
            title: target.label,
            target,
            editing: false,
          },
        ],
        { manual: true, stage: "creative-writing" },
      );
    }

    function selectCreativeDocument(path, options = {}) {
      if (!path) {
        return;
      }
      creativeActiveDocument = path;
      creativeActiveFolder = path.includes("/") ? path.split("/").slice(0, -1).join("/") : "";
      creativeLastNotifiedTarget = options.notifyAgent === false
        ? creativeLastNotifiedTarget
        : "";
      showCreativeDocument(path);
      renderCreativeTree();
      renderCreativeProjectStatus();
      if (options.notifyAgent !== false) {
        notifyCreativeAgentTargetSwitch();
      }
    }

    function creativeAgentSession() {
      return agentSessions.some(
        (session) => session.kind === "creative-writing" && session.status === "running",
      )
        ? agentSessions.find(
            (session) => session.kind === "creative-writing" && session.status === "running",
          )
        : null;
    }

    function creativeAgentRunning() {
      return Boolean(creativeAgentSession());
    }

    function activeCreativeTarget() {
      if (creativeActiveDocument) {
        if (creativePathIsCorkboard(creativeActiveDocument)) {
          return {
            type: "freeform-corkboard",
            path: creativeActiveDocument,
          };
        }
        return {
          type: "document",
          path: creativeActiveDocument,
        };
      }
      if (creativeActiveFolder) {
        return {
          type: "folder-corkboard",
          path: creativeActiveFolder,
        };
      }
      return {
        type: "none",
        path: "",
      };
    }

    function creativeTargetKey(target) {
      return `${target.type || "none"}:${target.path || ""}`;
    }

    function creativeTargetContextLines(target) {
      if (!target || target.type === "none") {
        return ["Active target: none"];
      }
      if (target.type === "document") {
        return [
          "Active target: document",
          `Path: ${target.path}`,
          "Mode: markdown editing",
          "Use the active document as the writing target unless the writer names another file.",
        ];
      }
      if (target.type === "freeform-corkboard") {
        return [
          "Active target: freeform corkboard",
          `Path: ${target.path}`,
          "Mode: arbitrary cards with x/y positions",
          "API guide: docs/corkboard-api.md",
          "Use `electroboy corkboard` commands for card changes.",
          "Do not edit corkboard JSON directly unless the writer explicitly asks.",
        ];
      }
      return [
        "Active target: folder corkboard",
        `Path: ${target.path}`,
        "Mode: folder-backed card ordering and notes",
        "API guide: docs/corkboard-api.md",
        "Use `electroboy corkboard folder` commands for notes and order.",
        "Create, delete, or rename files only when the writer explicitly asks.",
      ];
    }

    async function notifyCreativeAgentTargetSwitch() {
      const target = activeCreativeTarget();
      const targetKey = creativeTargetKey(target);
      const session = creativeAgentSession();
      if (
        !creativeModeActive() ||
        target.type === "none" ||
        targetKey === creativeLastNotifiedTarget ||
        !session ||
        !session.interactive
      ) {
        return;
      }
      creativeLastNotifiedTarget = targetKey;
      const message = [
        "[ElectroBoy creative-writing context update]",
        ...creativeTargetContextLines(target),
        "The target is now displayed in the middle pane.",
        "Do not modify it unless the writer asks.",
        "[/ElectroBoy creative-writing context update]",
      ].join("\\n");
      await fetch(contextUrl("/api/sessions/message"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session.session_id, message }),
      }).catch(() => {});
    }

    function creativePromptMessage(message) {
      if (!creativeModeActive()) {
        return message;
      }
      const target = activeCreativeTarget();
      const contextLines = [
        "[ElectroBoy creative-writing context]",
        ...creativeTargetContextLines(target),
        "Project scratchpad: scratchpad/scratchpad.md",
        "[/ElectroBoy creative-writing context]",
        "",
        message,
      ];
      return contextLines.join("\\n");
    }

    async function loadCreativeScratchPad() {
      if (!creativeModeActive() || !activeProjectRoot || !contextId) {
        scratchPad.value = "";
        restoredScratchContextId = contextId;
        return;
      }
      const response = await fetch(contextUrl("/api/creative/scratch"), {
        cache: "no-store",
      });
      const payload = await response.json().catch(() => ({ markdown: "" }));
      scratchPad.value = response.ok ? String(payload.markdown || "") : "";
      restoredScratchContextId = contextId;
    }

    function queueCreativeScratchPadSave() {
      window.clearTimeout(creativeScratchSaveTimer);
      creativeScratchSaveTimer = window.setTimeout(saveCreativeScratchPad, 450);
    }

    async function saveCreativeScratchPad() {
      if (!creativeModeActive() || !activeProjectRoot || !contextId) {
        return;
      }
      await fetch(contextUrl("/api/creative/scratch"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ markdown: scratchPad.value }),
      }).catch(() => {});
    }

    async function initializeCreativeWorkspace() {
      if (!activeProjectRoot || !contextId) {
        return;
      }
      await fetch(contextUrl("/api/creative/init"), { method: "POST" }).catch(() => {});
    }

    async function ensureCreativeWorkspaceLoaded() {
      if (!creativeModeActive() || !activeProjectRoot || !contextId) {
        return;
      }
      await refreshCreativeBinder();
    }

    function creativeEntryChildren(basePath = "") {
      const entries = creativeTreePayload && Array.isArray(creativeTreePayload.entries)
        ? creativeTreePayload.entries
        : [];
      if (!basePath) {
        return entries;
      }
      const entry = findCreativeEntry(entries, basePath);
      return entry && Array.isArray(entry.children) ? entry.children : [];
    }

    function findCreativeEntry(entries, path) {
      for (const entry of entries || []) {
        if (String(entry.path || "") === path) {
          return entry;
        }
        const child = findCreativeEntry(entry.children || [], path);
        if (child) {
          return child;
        }
      }
      return null;
    }

    function uniqueCreativeChildPath(basePath, stem, extension = "") {
      const existing = new Set(
        creativeEntryChildren(basePath).map((entry) =>
          String(entry.name || "").toLowerCase(),
        ),
      );
      let index = 1;
      let name = `${stem}${extension}`;
      while (existing.has(name.toLowerCase())) {
        index += 1;
        name = `${stem}-${index}${extension}`;
      }
      return basePath ? `${basePath}/${name}` : name;
    }

    function creativeParentPath(path) {
      return path.includes("/") ? path.split("/").slice(0, -1).join("/") : "";
    }

    function creativePathIsCorkboard(path) {
      return String(path || "").toLowerCase().endsWith(CREATIVE_CORKBOARD_SUFFIX);
    }

    function creativePathIsInside(path, container) {
      return path === container || path.startsWith(`${container}/`);
    }

    function remapCreativePath(path, oldPath, newPath) {
      if (!path) {
        return "";
      }
      if (path === oldPath) {
        return newPath;
      }
      if (path.startsWith(`${oldPath}/`)) {
        return `${newPath}/${path.slice(oldPath.length + 1)}`;
      }
      return path;
    }

    function beginCreativeRename(path, type) {
      creativeEditingPath = path;
      creativeEditingType = type;
      renderCreativeTree();
    }

    function cancelCreativeRename() {
      creativeEditingPath = "";
      creativeEditingType = "";
      renderCreativeTree();
    }

    function normalizedCreativeName(raw, type) {
      let name = String(raw || "").trim();
      name = name.replace(/[\\/]+/g, "-");
      if (!name || name === "." || name === "..") {
        return "";
      }
      if (type === "corkboard") {
        if (!name.toLowerCase().endsWith(CREATIVE_CORKBOARD_SUFFIX)) {
          name = name.replace(/\.(md|json)$/i, "");
          name = `${name}${CREATIVE_CORKBOARD_SUFFIX}`;
        }
        return name;
      }
      if (type === "file" && !/\.[^./]+$/.test(name)) {
        name = `${name}.md`;
      }
      return name;
    }

    async function finishCreativeRename(path, type, rawName) {
      if (creativeEditingPath !== path) {
        return;
      }
      const newName = normalizedCreativeName(rawName, type);
      if (!newName || newName === basename(path)) {
        creativeEditingPath = "";
        creativeEditingType = "";
        renderCreativeTree();
        return;
      }
      const response = await fetch(contextUrl("/api/creative/rename"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, new_name: newName }),
      });
      const payload = await response.json().catch(() => ({ error: "rename failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "rename failed"}\\n`, "error");
        renderCreativeTree();
        return;
      }
      const newPath = String(payload.path || "");
      creativeActiveDocument = remapCreativePath(creativeActiveDocument, path, newPath);
      creativeActiveFolder = remapCreativePath(creativeActiveFolder, path, newPath);
      expandedCreativeFolders = new Set(
        Array.from(expandedCreativeFolders).map((folder) =>
          remapCreativePath(folder, path, newPath),
        ),
      );
      creativeEditingPath = "";
      creativeEditingType = "";
      await refreshCreativeBinder();
      recordProjectStatusMessage(`renamed: ${newPath}`);
      if (creativeActiveDocument) {
        if (creativePathIsCorkboard(creativeActiveDocument)) {
          showCreativeCorkboard(creativeActiveDocument, { freeform: true });
        } else {
          showCreativeDocument(creativeActiveDocument);
        }
      }
    }

    async function createCreativeFolderInline(basePath = "") {
      if (!activeProjectRoot) {
        return;
      }
      const path = uniqueCreativeChildPath(basePath, "new-folder");
      const response = await fetch(contextUrl("/api/creative/folders"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const payload = await response.json().catch(() => ({ error: "folder failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "folder failed"}\\n`, "error");
        return;
      }
      expandedCreativeFolders.add(basePath);
      creativeActiveFolder = payload.path || path;
      creativeEditingPath = payload.path || path;
      creativeEditingType = "directory";
      await refreshCreativeBinder();
      recordProjectStatusMessage(`created folder: ${payload.path || path}`);
    }

    async function createCreativeDocumentInline(basePath = "") {
      if (!activeProjectRoot) {
        return;
      }
      const path = uniqueCreativeChildPath(basePath, "untitled", ".md");
      const response = await fetch(contextUrl("/api/creative/documents"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const payload = await response.json().catch(() => ({ error: "document failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "document failed"}\\n`, "error");
        return;
      }
      creativeActiveDocument = payload.path || path;
      creativeActiveFolder = basePath;
      creativeEditingPath = payload.path || path;
      creativeEditingType = "file";
      await refreshCreativeBinder();
      showCreativeDocument(creativeActiveDocument);
      recordProjectStatusMessage(`created file: ${payload.path || path}`);
    }

    async function createCreativeCorkboardInline(basePath = "") {
      if (!activeProjectRoot) {
        return;
      }
      const path = uniqueCreativeChildPath(
        basePath,
        "ideas",
        CREATIVE_CORKBOARD_SUFFIX,
      );
      const response = await fetch(contextUrl("/api/creative/corkboards"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const payload = await response.json().catch(() => ({ error: "corkboard failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "corkboard failed"}\\n`, "error");
        return;
      }
      creativeActiveDocument = payload.path || path;
      creativeActiveFolder = basePath;
      creativeEditingPath = payload.path || path;
      creativeEditingType = "corkboard";
      await refreshCreativeBinder();
      showCreativeCorkboard(creativeActiveDocument, { freeform: true });
      recordProjectStatusMessage(`created board: ${payload.path || path}`);
    }

    async function deleteCreativeEntry(path, type) {
      if (!activeProjectRoot || !path) {
        return;
      }
      const label = type === "directory"
        ? "folder and all of its contents"
        : type === "corkboard" ? "corkboard" : "file";
      if (!window.confirm(`Delete this ${label}?\\n\\n${path}`)) {
        return;
      }
      const response = await fetch(contextUrl("/api/creative/delete"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const payload = await response.json().catch(() => ({ error: "delete failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "delete failed"}\\n`, "error");
        return;
      }
      if (creativePathIsInside(creativeActiveDocument, path)) {
        creativeActiveDocument = "";
        hideArtifactPreview();
      }
      if (creativePathIsInside(creativeActiveFolder, path)) {
        creativeActiveFolder = creativeParentPath(path);
      }
      if (creativePathIsInside(creativeEditingPath, path)) {
        creativeEditingPath = "";
        creativeEditingType = "";
      }
      expandedCreativeFolders = new Set(
        Array.from(expandedCreativeFolders).filter(
          (folder) => !creativePathIsInside(folder, path),
        ),
      );
      await refreshCreativeBinder();
      recordProjectStatusMessage(`deleted ${type}: ${path}`);
    }

    async function startCreativeWritingAgent() {
      if (!activeProjectRoot || !contextId) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      setAgentInputVisible(true);
      clearAgentOutput();
      appendOutput("$ codex creative-writing\\n", "system");
      const response = await fetch(contextUrl("/api/creative/agent/start"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          active_document: creativeActiveDocument,
          active_target: activeCreativeTarget(),
        }),
      });
      const payload = await response.json().catch(() => ({ error: "start failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "start failed"}\\n`, "error");
        return;
      }
      updateProjectState(payload);
      const sessionId = payload.session_id || selectedSessionId;
      connectSessionEvents(sessionId);
      sendTerminalResize();
    }

    function markArtifactFrameLoading(frame) {
      frame.classList.add("loading");
      frame.addEventListener(
        "load",
        () => {
          frame.classList.remove("loading");
        },
        { once: true },
      );
    }

    function renderArtifactPreviewItems() {
      artifactPreviewStack.replaceChildren();
      if (poppedPanes.has("artifact")) {
        artifactPreviewStack.classList.remove("split");
        return;
      }
      artifactPreviewStack.classList.toggle("split", artifactPreviewItems.length > 1);
      for (const [index, item] of artifactPreviewItems.entries()) {
        if (index > 0) {
          const divider = document.createElement("div");
          divider.className = "artifact-preview-divider";
          artifactPreviewStack.append(divider);
        }
        const section = document.createElement("section");
        section.className = "artifact-preview-item";
        section.setAttribute("aria-label", `${item.title} preview`);

        const header = document.createElement("div");
        header.className = "pane-header";

        const title = document.createElement("span");
        title.className = "pane-title";
        title.textContent = item.title;

        const actions = document.createElement("div");
        actions.className = "pane-actions";
        const supportsZoom = artifactPaneSupportsDocumentZoom(item);
        const supportsExport = artifactPaneSupportsDocumentExport(item);
        const supportsModeSwitch = artifactPaneSupportsModeSwitch(item);

        const zoomControls = document.createElement("div");
        zoomControls.className = "document-zoom-controls";
        zoomControls.setAttribute("aria-label", "Document zoom");

        const zoomOut = document.createElement("button");
        zoomOut.className = "document-zoom-button";
        zoomOut.type = "button";
        zoomOut.title = "Zoom document out";
        zoomOut.setAttribute("aria-label", "Zoom document out");
        zoomOut.dataset.zoom = "out";
        zoomOut.textContent = "-";
        zoomOut.addEventListener("click", () => {
          changeDocumentZoom(-DOCUMENT_ZOOM_STEP);
        });

        const zoomLevel = document.createElement("span");
        zoomLevel.className = "document-zoom-level";
        zoomLevel.textContent = `${documentZoom}%`;

        const zoomIn = document.createElement("button");
        zoomIn.className = "document-zoom-button";
        zoomIn.type = "button";
        zoomIn.title = "Zoom document in";
        zoomIn.setAttribute("aria-label", "Zoom document in");
        zoomIn.dataset.zoom = "in";
        zoomIn.textContent = "+";
        zoomIn.addEventListener("click", () => {
          changeDocumentZoom(DOCUMENT_ZOOM_STEP);
        });

        const refresh = document.createElement("button");
        refresh.className = "pane-popout-button";
        refresh.type = "button";
        refresh.title = `Refresh ${item.title}`;
        refresh.setAttribute("aria-label", `Refresh ${item.title}`);
        refresh.textContent = "Refresh";
        refresh.addEventListener("click", refreshArtifactPreview);

        const preview = document.createElement("button");
        preview.className = "pane-popout-button";
        preview.type = "button";
        preview.title = `Preview ${item.title}`;
        preview.setAttribute("aria-label", `Preview ${item.title}`);
        preview.textContent = "Preview";
        preview.classList.toggle("active", !item.editing);
        preview.addEventListener("click", () => {
          setArtifactPreviewEditing(item, false);
        });

        const edit = document.createElement("button");
        edit.className = "pane-popout-button";
        edit.type = "button";
        edit.title = `Edit ${item.title}`;
        edit.setAttribute("aria-label", `Edit ${item.title}`);
        edit.textContent = "Edit";
        edit.classList.toggle("active", Boolean(item.editing));
        edit.addEventListener("click", () => {
          setArtifactPreviewEditing(item, true);
        });

        const exportFormat = document.createElement("select");
        exportFormat.className = "document-export-format";
        exportFormat.title = `Export format for ${item.title}`;
        exportFormat.setAttribute("aria-label", `Export format for ${item.title}`);
        for (const format of documentExportFormats()) {
          const option = document.createElement("option");
          option.value = format.value;
          option.textContent = format.label;
          exportFormat.append(option);
        }

        const exportButton = document.createElement("button");
        exportButton.className = "pane-popout-button";
        exportButton.type = "button";
        exportButton.title = `Export ${item.title}`;
        exportButton.setAttribute("aria-label", `Export ${item.title}`);
        exportButton.textContent = "Export";
        exportButton.addEventListener("click", () => {
          exportArtifactDocument(item, exportFormat.value).catch((error) => {
            appendOutput(`export failed: ${error}\\n`, "error");
          });
        });

        const popout = document.createElement("button");
        popout.className = "pane-popout-button";
        popout.type = "button";
        popout.title = `Pop out ${item.title}`;
        popout.setAttribute("aria-label", `Pop out ${item.title}`);
        popout.textContent = "Pop";
        popout.addEventListener("click", () => {
          popOutArtifactPreview(item);
        });

        zoomControls.append(zoomOut, zoomLevel, zoomIn);
        if (supportsZoom) {
          actions.append(zoomControls);
        }
        if (supportsExport) {
          actions.append(exportFormat, exportButton);
        }
        actions.append(refresh);
        if (supportsModeSwitch) {
          actions.append(preview, edit);
        }
        actions.append(popout);
        if (item.kind === "document") {
          const documentSwitcher = document.createElement("select");
          documentSwitcher.className = "document-target-switcher";
          documentSwitcher.title = "Open documents";
          documentSwitcher.setAttribute("aria-label", "Open documents");
          renderDocumentTargetSwitcher(documentSwitcher);
          documentSwitcher.addEventListener("change", () => {
            selectOpenDocumentTarget(documentSwitcher.value);
          });
          header.append(documentSwitcher, actions);
        } else {
          header.append(title, actions);
        }

        const frame = document.createElement("iframe");
        frame.className = "artifact-preview-frame loading";
        frame.title = `${item.title} preview`;
        frame.setAttribute(
          "sandbox",
          "allow-scripts allow-popups allow-modals allow-same-origin",
        );
        frame.dataset.artifactId = item.id;
        markArtifactFrameLoading(frame);
        frame.addEventListener("load", () => {
          postArtifactEditorFontSize(frame);
        });
        frame.src = item.editing ? artifactEditUrl(item) : artifactPreviewUrl(item);

        section.append(header, frame);
        artifactPreviewStack.append(section);
      }
      applyDocumentZoom();
    }

    function artifactFrameForItem(item) {
      if (!item) {
        return null;
      }
      const escapedId = CSS.escape(item.id || "");
      return artifactPreviewStack.querySelector(
        `.artifact-preview-frame[data-artifact-id="${escapedId}"]`,
      );
    }

    function requestArtifactEditorSave(item) {
      const frame = artifactFrameForItem(item);
      if (!frame || !frame.contentWindow) {
        return Promise.resolve(true);
      }
      const token = `artifact-save-${++artifactSaveTokenSequence}`;
      return new Promise((resolve) => {
        const timeout = window.setTimeout(() => {
          pendingArtifactSaves.delete(token);
          resolve(false);
        }, 15000);
        pendingArtifactSaves.set(token, { resolve, timeout });
        frame.contentWindow.postMessage(
          { type: "electroboy-save-request", token },
          window.location.origin,
        );
      });
    }

    async function setArtifactPreviewEditing(item, editing) {
      if (!editing && item && item.editing) {
        const saved = await requestArtifactEditorSave(item);
        if (!saved) {
          appendOutput("preview blocked: save failed\\n", "error");
          return;
        }
      }
      item.editing = Boolean(editing);
      renderArtifactPreviewItems();
    }

    function popOutArtifactPreview(item) {
      if (item.kind === "creative-corkboard") {
        popOutPane("artifact", item);
        return;
      }
      if (!contextId) {
        appendOutput("create a browser context first\\n", "error");
        return;
      }
      const parameters = new URLSearchParams();
      parameters.set("context_id", contextId);
      parameters.set("artifact", artifactKindForPane(item));
      parameters.set("font_size", String(terminalFontSize));
      parameters.set("base_font_size", String(terminalFontSize));
      parameters.set("document_zoom", String(documentZoom));
      if (item.kind === "document" && item.target) {
        parameters.set("document_path", item.target.path);
        parameters.set("document_title", item.target.label);
      }
      if (item.kind === "route" && item.path) {
        parameters.set("artifact_path", item.path);
        parameters.set("artifact_title", item.title);
      }
      if (item.kind === "creative-corkboard" && item.folder) {
        parameters.set("folder_path", item.folder.path);
        parameters.set("folder_title", item.folder.label || item.title);
      }
      if (item.kind === "creative-corkboard" && item.corkboard) {
        parameters.set("corkboard_path", item.corkboard.path);
        parameters.set("corkboard_title", item.corkboard.label || item.title);
      }
      const popup = window.open(
        `/pane/artifact?${parameters.toString()}`,
        `electroboy-artifact-${item.id}-${contextId}`,
        PANE_POPUP_FEATURES,
      );
      if (!popup) {
        appendOutput("popup was blocked by the browser\\n", "error");
      }
    }

    function fileBrowserUrl(path, mode = "project", projectAction = "") {
      const parameters = new URLSearchParams();
      parameters.set("path", path || activeProjectRoot || activationRoot || serviceRoot || ".");
      parameters.set("mode", mode);
      if (projectAction) {
        parameters.set("project_action", projectAction);
      }
      return `/file-browser?${parameters.toString()}`;
    }

    function openProjectBrowser(mode = projectMode, activateSelection = false) {
      if (activationRoot && mode !== "meta-add" && mode !== "meta-start") {
        return;
      }
      if ((mode === "meta-add" || mode === "meta-start") && activeProjectMode !== "meta") {
        return;
      }
      projectMode = mode;
      projectBrowserActivatesSelection = Boolean(activateSelection);
      hideStageMenus();
      hideWorkItemPanel();
      projectPanel.hidden = true;
      const path = projectPath.value || activeProjectRoot || activationRoot || serviceRoot || ".";
      const browserMode = mode === "new" || mode === "meta-new"
        ? "project-new"
        : "project";
      const popup = window.open(
        fileBrowserUrl(path, browserMode, activateSelection ? mode : ""),
        "electroboy-file-browser",
        PANE_POPUP_FEATURES,
      );
      if (!popup) {
        projectBrowserActivatesSelection = false;
        projectStatus.textContent = "popup was blocked by the browser";
        appendOutput("popup was blocked by the browser\\n", "error");
      }
    }

    function openLinkFileBrowser() {
      projectBrowserActivatesSelection = false;
      const path = activeProjectRoot || activationRoot || serviceRoot || projectPath.value || ".";
      const popup = window.open(
        fileBrowserUrl(path, "link"),
        "electroboy-file-link-browser",
        PANE_POPUP_FEATURES,
      );
      if (!popup) {
        appendOutput("popup was blocked by the browser\\n", "error");
      }
    }

    function openDocumentFileBrowser() {
      projectBrowserActivatesSelection = false;
      if (!activeProjectRoot) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      const popup = window.open(
        fileBrowserUrl(activeProjectRoot, "document"),
        "electroboy-document-browser",
        PANE_POPUP_FEATURES,
      );
      if (!popup) {
        appendOutput("popup was blocked by the browser\\n", "error");
      }
    }

    function openNewDocumentFileBrowser() {
      projectBrowserActivatesSelection = false;
      if (!activeProjectRoot) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      const popup = window.open(
        fileBrowserUrl(activeProjectRoot, "document-new"),
        "electroboy-new-document-browser",
        PANE_POPUP_FEATURES,
      );
      if (!popup) {
        appendOutput("popup was blocked by the browser\\n", "error");
      }
    }

    function hideArtifactPreview() {
      artifactPreviewKind = "";
      artifactPreviewDocumentTarget = null;
      artifactPreviewItems = [];
      manualArtifactPreview = false;
      manualArtifactPreviewStage = "";
      artifactPreviewStage = "";
      artifactPaneRequested = false;
      closeArtifactEventStream();
      artifactPreviewStack.replaceChildren();
      artifactPreviewStack.classList.remove("split");
      applyOutputPaneVisibility();
    }

    function refreshArtifactPreview(options = {}) {
      const includeEditing = options.includeEditing !== false;
      artifactPreviewVersion += 1;
      for (const frame of artifactPreviewStack.querySelectorAll(".artifact-preview-frame")) {
        const item = artifactPreviewItems.find(
          (candidate) => candidate.id === frame.dataset.artifactId,
        );
        if (item && item.editing && !includeEditing) {
          continue;
        }
        const url = item && item.editing ? artifactEditUrl(item) : artifactPreviewUrl(item);
        if (url) {
          markArtifactFrameLoading(frame);
          frame.src = url;
        }
      }
    }

    function artifactEventUrl(item) {
      if (!item) {
        return "";
      }
      if (item.kind === "requirements") {
        return contextUrl("/api/artifacts/events?artifact=requirements");
      }
      const parameters = new URLSearchParams();
      if (item.kind === "document" && item.target) {
        parameters.set("artifact", "document");
        parameters.set("path", item.target.path);
        return contextUrl(`/api/artifacts/events?${parameters.toString()}`);
      }
      if (item.kind === "route" && item.path) {
        parameters.set("artifact", "route");
        parameters.set("path", item.path);
        return contextUrl(`/api/artifacts/events?${parameters.toString()}`);
      }
      return "";
    }

    function connectArtifactEvents() {
      closeArtifactEventStream();
      if (!contextId) {
        return;
      }
      const urls = new Set(artifactPreviewItems.map(artifactEventUrl).filter(Boolean));
      for (const url of urls) {
        const source = new EventSource(url);
        source.addEventListener("artifact-event", () => {
          refreshArtifactPreview({ includeEditing: false });
        });
        source.onerror = () => {};
        artifactEventSources.push(source);
      }
    }

    function closeArtifactEventStream() {
      for (const source of artifactEventSources) {
        source.close();
      }
      artifactEventSources = [];
    }

    function stageIsRunning(stage) {
      if (stage === "requirements") {
        return requirementsRunning;
      }
      if (stage === "design") {
        return designRunning;
      }
      if (stage === "design-review") {
        return designReviewRunning;
      }
      return Boolean(genericStageRun(stage).running);
    }

    function syncArtifactPreviewWithProject() {
      if (!activeProjectRoot) {
        hideArtifactPreview();
        return;
      }
      if (manualArtifactPreview && manualArtifactPreviewStage === currentWorkflowStage) {
        connectArtifactEvents();
        return;
      }
      manualArtifactPreview = false;
      manualArtifactPreviewStage = "";
      if (artifactPreviewStage === currentWorkflowStage && artifactPreviewItems.length > 0) {
        connectArtifactEvents();
        return;
      }
      if (stageIsRunning(currentWorkflowStage)) {
        showStageArtifactPreview(currentWorkflowStage);
        return;
      }
      if (artifactPreviewStage && artifactPreviewStage !== currentWorkflowStage) {
        hideArtifactPreview();
      }
    }

    async function refreshProject() {
      if (!contextId) {
        return;
      }
      const response = await fetch(contextUrl("/api/project"), { cache: "no-store" });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      updateProjectState(payload);
    }

    function queueProjectStatusRefresh(delay = 120) {
      window.clearTimeout(statusRefreshTimer);
      const sequence = ++statusRefreshSequence;
      if (creativeModeActive()) {
        renderCreativeProjectStatus();
        return;
      }
      if (!contextId || !activationRoot) {
        projectStatusOutput.textContent = "no active project";
        return;
      }
      projectStatusOutput.textContent = "refreshing status...\\n";
      statusRefreshTimer = window.setTimeout(
        () => refreshProjectStatus(sequence),
        delay,
      );
    }

    async function refreshProjectStatus(sequence = ++statusRefreshSequence) {
      if (creativeModeActive()) {
        renderCreativeProjectStatus();
        return;
      }
      if (!contextId || !activationRoot) {
        if (sequence === statusRefreshSequence) {
          projectStatusOutput.textContent = "no active project";
        }
        return;
      }
      projectStatusOutput.textContent = "refreshing status...\\n";
      const response = await fetch(contextUrl("/api/project/status"), {
        cache: "no-store",
      });
      const payload = await response.json().catch(() => ({ error: "status failed" }));
      if (sequence !== statusRefreshSequence) {
        return;
      }
      if (!response.ok) {
        projectStatusOutput.textContent = `${payload.error || "status failed"}\\n`;
        return;
      }
      projectStatusOutput.textContent = payload.output || "status: none\\n";
    }

    async function selectWorkflowStage(stageId) {
      if (!activeProjectRoot || stageId === "project") {
        return false;
      }
      const response = await fetch(contextUrl("/api/workflow/stage"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: stageId }),
      });
      const payload = await response.json().catch(() => ({ error: "stage update failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "stage update failed"}\\n`, "error");
        return false;
      }
      if (payload.terminated_agent || payload.workflow_stage !== "requirements") {
        closeAgentEventStream();
        showProgressPane(false);
        setAgentInputVisible(true);
        setRequirementsRunning(false);
        agentInput.value = "";
      }
      updateProjectState(payload);
      return true;
    }

    async function setWorkflowStageFromMenu(stageId) {
      if (!activeProjectRoot || currentWorkflowStage === stageId) {
        return;
      }
      hideStageMenus();
      const selected = await selectWorkflowStage(stageId);
      if (selected) {
        appendOutput(`stage set: ${stageId}\\n`, "system");
      }
    }

    async function approveRequirementsStage(skipApproval = false) {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      if (currentWorkflowStage !== "requirements") {
        return;
      }
      hideStageMenus();
      closeAgentEventStream();
      const endpoint = skipApproval
        ? "/api/agents/requirements/skip-approval"
        : "/api/agents/requirements/approve";
      const response = await fetch(contextUrl(endpoint), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "approval failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "approval failed"}\\n`, "error");
        if (payload.output) {
          appendOutput(`${payload.output}\\n`, "error");
        }
        return;
      }
      setRequirementsRunning(false);
      agentInput.value = "";
      clearAgentOutput();
      if (payload.output) {
        appendOutput(`${payload.output}\\n`, "system");
      }
      if (payload.warning) {
        appendOutput(`${payload.warning}\\n`, "system");
      }
      appendOutput(
        skipApproval
          ? "requirements approval skipped; next: design\\n"
          : "requirements approved; next: design\\n",
        "system",
      );
      updateProjectState(payload);
    }

    async function skipRequirementsApprovalStage() {
      if (
        !requirementsApproved &&
        !window.confirm(
          "Requirements have not been explicitly approved.\\n\\nSkip approval and advance to design anyway?",
        )
      ) {
        return;
      }
      await approveRequirementsStage(true);
    }

    async function browseDirectory(path = projectPath.value || ".", mode = currentBrowserMode) {
      currentBrowserMode = mode;
      currentSelectedFile = "";
      fileBrowser.hidden = false;
      browserPath.value = path;
      selectDirectory.textContent = mode === "link" ? "Insert" : "Select";
      selectDirectory.disabled = mode === "link";
      fileBrowser.setAttribute(
        "aria-label",
        mode === "link" ? "File browser" : "Directory browser",
      );
      directoryList.replaceChildren();
      const modeParameter = mode === "link" ? "&mode=file" : "";
      const response = await fetch(
        `/api/files/browse?path=${encodeURIComponent(path)}${modeParameter}`,
        { cache: "no-store" },
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ error: "browse failed" }));
        projectStatus.textContent = payload.error || "browse failed";
        return;
      }
      const payload = await response.json();
      currentBrowsePath = payload.path;
      currentBrowseParent = payload.parent || "";
      browserPath.value = payload.path;
      upDirectory.disabled = !currentBrowseParent;
      directoryList.replaceChildren();
      for (const entry of payload.entries) {
        directoryList.appendChild(
          directoryButton(entry.name, entry.path, entry.type || "directory"),
        );
      }
    }

    function directoryButton(label, path, type = "directory") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `directory-entry ${type === "file" ? "file" : "directory"}`;
      button.textContent = label;
      button.title = path;
      button.addEventListener("click", () => {
        if (type === "file") {
          selectFileForInput(path, button);
        } else {
          browseDirectory(path, currentBrowserMode);
        }
      });
      return button;
    }

    function selectFileForInput(path, button) {
      currentSelectedFile = path;
      for (const entry of directoryList.querySelectorAll(".directory-entry")) {
        entry.classList.toggle("selected", entry === button);
      }
      selectDirectory.disabled = false;
    }

    function showProjectPanel(mode) {
      const isMetaAction = mode === "meta-add" || mode === "meta-start";
      if (activationRoot && !isMetaAction) {
        return;
      }
      if (isMetaAction && activeProjectMode !== "meta") {
        return;
      }
      projectMode = mode;
      hideStageMenus();
      hideWorkItemPanel();
      projectPanel.hidden = false;
      activateProject.textContent = projectActionLabel(mode);
      projectStatus.textContent = projectStatusLine();
      projectPath.focus();
    }

    function projectActionLabel(mode) {
      if (mode === "new") {
        return "Create";
      }
      if (mode === "meta-new") {
        return "Create meta";
      }
      if (mode === "meta-add") {
        return "Add repo";
      }
      if (mode === "meta-start") {
        return "Start repo";
      }
      return "Activate";
    }

    function selectCurrentDirectory() {
      if (currentBrowserMode === "link") {
        insertSelectedFilePath();
        return;
      }
      if (!currentBrowsePath) {
        return;
      }
      projectPath.value = currentBrowsePath;
      projectStatus.textContent = `selected: ${currentBrowsePath}`;
      fileBrowser.hidden = true;
      projectPath.focus();
    }

    function insertSelectedFilePath() {
      if (!currentSelectedFile) {
        return;
      }
      insertTextAtCursor(currentSelectedFile);
      fileBrowser.hidden = true;
      currentSelectedFile = "";
      agentInput.focus();
    }

    function insertTextAtCursor(text) {
      const start = agentInput.selectionStart ?? agentInput.value.length;
      const end = agentInput.selectionEnd ?? start;
      const value = agentInput.value;
      const needsLeadingSpace = start > 0 && !/\\s/.test(value[start - 1]);
      const insertion = `${needsLeadingSpace ? " " : ""}${text}`;
      agentInput.value = `${value.slice(0, start)}${insertion}${value.slice(end)}`;
      const cursor = start + insertion.length;
      agentInput.setSelectionRange(cursor, cursor);
    }

    async function applyProjectSelection(selectedPathOverride = "") {
      const endpoint = projectEndpoint(projectMode);
      const selectedPath = String(selectedPathOverride || projectPath.value).trim();
      if (!selectedPath) {
        const message = projectMode === "meta-start"
          ? "choose a repository name or path first"
          : "choose a project directory first";
        projectStatus.textContent = message;
        appendOutput(`${message}\\n`, "error");
        return;
      }
      projectPath.value = selectedPath;
      activateProject.disabled = true;
      projectStatus.textContent = projectPendingLabel(projectMode, selectedPath);
      let response;
      try {
        response = await fetch(contextUrl(endpoint), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(projectRequestBody(projectMode, selectedPath)),
        });
      } catch (error) {
        projectStatus.textContent = `activation request failed: ${error}`;
        appendOutput(`activation request failed: ${error}\\n`, "error");
        activateProject.disabled = false;
        return;
      }
      const payload = await response.json().catch(() => ({ error: "project update failed" }));
      if (!response.ok) {
        const message = payload.error || "project update failed";
        projectStatus.textContent = message;
        appendOutput(`${message}\\n`, "error");
        activateProject.disabled = false;
        return;
      }
      const nextProjectRoot = payload.active_project_root || payload.activation_root || "";
      if (nextProjectRoot && nextProjectRoot !== activeProjectRoot) {
        projectStatusMessages = [];
      }
      activeProjectRoot = payload.active_project_root || "";
      activationRoot = payload.activation_root || activeProjectRoot;
      projectPath.value = activeProjectRoot || activationRoot;
      fileBrowser.hidden = true;
      projectPanel.hidden = true;
      hideStageMenus();
      recordProjectStatusMessage(`${payload.status}: ${activationRoot || activeProjectRoot}`);
      updateProjectState(payload, { deferCreativeWorkspaceInit: creativeModeActive() });
      if (creativeModeActive()) {
        await ensureCreativeWorkspaceLoaded();
      }
      activateProject.disabled = false;
    }

    function projectEndpoint(mode) {
      if (creativeModeActive() && mode === "open") {
        return "/api/creative/project/open";
      }
      if (creativeModeActive() && mode === "new") {
        return "/api/creative/project/new";
      }
      if (mode === "new") {
        return "/api/project/new";
      }
      if (mode === "meta-new") {
        return "/api/meta/init";
      }
      if (mode === "meta-add") {
        return "/api/meta/add";
      }
      if (mode === "meta-start") {
        return "/api/meta/start";
      }
      return "/api/project/open";
    }

    function projectRequestBody(mode, selectedPath) {
      if (mode === "meta-start") {
        return { repository: selectedPath };
      }
      return { path: selectedPath };
    }

    function projectPendingLabel(mode, selectedPath) {
      if (mode === "new") {
        return `creating: ${selectedPath}`;
      }
      if (mode === "meta-new") {
        return `creating meta-project: ${selectedPath}`;
      }
      if (mode === "meta-add") {
        return `adding repo: ${selectedPath}`;
      }
      if (mode === "meta-start") {
        return `starting repo: ${selectedPath}`;
      }
      return `activating: ${selectedPath}`;
    }

    function repositoryReference(repository) {
      return String(repository.name || repository.path || "").trim();
    }

    async function startMetaRepositoryFromMenu(repository) {
      await applyMetaRepositoryAction("/api/meta/start", repository, "starting repo");
    }

    async function removeMetaRepositoryFromMenu(repository) {
      const reference = repositoryReference(repository);
      if (!reference) {
        return;
      }
      const label = repositoryLabel(repository);
      const shouldRemove = window.confirm(
        `Remove ${label} from this meta-project? Repository files will not be deleted.`,
      );
      if (!shouldRemove) {
        return;
      }
      await applyMetaRepositoryAction("/api/meta/remove", repository, "removing repo");
    }

    async function applyMetaRepositoryAction(endpoint, repository, pendingLabel) {
      const reference = repositoryReference(repository);
      if (!reference) {
        return;
      }
      hideStageMenus();
      projectStatus.textContent = `${pendingLabel}: ${reference}`;
      let response;
      try {
        response = await fetch(contextUrl(endpoint), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repository: reference }),
        });
      } catch (error) {
        projectStatus.textContent = `repo update failed: ${error}`;
        appendOutput(`repo update failed: ${error}\\n`, "error");
        return;
      }
      const payload = await response.json().catch(() => ({ error: "repo update failed" }));
      if (!response.ok) {
        const message = payload.error || "repo update failed";
        projectStatus.textContent = message;
        appendOutput(`${message}\\n`, "error");
        return;
      }
      activeProjectRoot = payload.active_project_root || "";
      activationRoot = payload.activation_root || activationRoot;
      projectPath.value = activeProjectRoot || activationRoot;
      clearAgentOutput();
      recordProjectStatusMessage(`${payload.status}: ${reference}`);
      updateProjectState(payload);
    }

    function showWorkItemPanel(mode) {
      if (!activeProjectRoot) {
        return;
      }
      workItemMode = mode;
      hideStageMenus();
      projectPanel.hidden = true;
      workItemPanel.hidden = false;
      workItemTitle.value = "";
      workItemName.value = "";
      workItemBranchCheckbox.checked = false;
      hideWorkItemRecovery();
      workItemName.hidden = mode === "bug-new";
      workItemBranchLabel.hidden = false;
      if (mode === "bug-new") {
        workItemTitle.placeholder = "Bug issue URL or reference";
        workItemName.placeholder = "";
        applyWorkItem.textContent = "Add bug resolution";
        workItemStatus.textContent = "Start a focused bug-resolution workflow.";
      } else {
        workItemTitle.placeholder = "Feature title or issue URL";
        workItemName.placeholder = "artifact name (optional)";
        applyWorkItem.textContent = "Add feature";
        workItemStatus.textContent = "Start or register feature work.";
      }
      workItemTitle.focus();
    }

    function hideWorkItemPanel() {
      workItemPanel.hidden = true;
      hideWorkItemRecovery();
      workItemMode = "";
    }

    async function applyWorkItemSelection() {
      if (!activeProjectRoot || !workItemMode) {
        return;
      }
      const title = workItemTitle.value.trim();
      if (!title) {
        workItemStatus.textContent = "enter a title or reference first";
        return;
      }
      if (!confirmWorkItemAgentStop()) {
        return;
      }
      hideWorkItemRecovery();
      applyWorkItem.disabled = true;
      workItemStatus.textContent = workItemPendingLabel();
      const endpoint = workItemEndpoint();
      let body = workItemRequestBody(title);
      let response;
      try {
        response = await fetch(contextUrl(endpoint), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      } catch (error) {
        workItemStatus.textContent = `work item update failed: ${error}`;
        applyWorkItem.disabled = false;
        return;
      }
      let payload = await response.json().catch(() => ({ error: "work item failed" }));
      if (!response.ok && shouldRetryWithSubrepoStash(payload, body)) {
        body = { ...body, stash_subrepo_changes: true };
        workItemStatus.textContent = "stashing nested repository changes";
        try {
          response = await fetch(contextUrl(endpoint), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
        } catch (error) {
          workItemStatus.textContent = `work item update failed: ${error}`;
          applyWorkItem.disabled = false;
          return;
        }
        payload = await response.json().catch(() => ({ error: "work item failed" }));
      }
      if (!response.ok) {
        const message = payload.error || "work item failed";
        workItemStatus.textContent = message;
        appendOutput(`${message}\\n`, "error");
        if (recoverableWorkItemError(message, payload)) {
          showWorkItemRecovery();
        } else {
          hideWorkItemRecovery();
        }
        applyWorkItem.disabled = false;
        return;
      }
      hideWorkItemRecovery();
      hideWorkItemPanel();
      recordProjectStatusMessage(`${payload.status}: ${payload.label || title}`);
      if (payload.terminated_agent) {
        recordProjectStatusMessage("stopped running agent for work-item context");
      }
      if (payload.output) {
        appendOutput(`${payload.output}\\n`, "system");
      }
      updateProjectState(payload);
      applyWorkItem.disabled = false;
    }

    function shouldRetryWithSubrepoStash(payload, body) {
      if (
        !body.branch ||
        body.stash_subrepo_changes ||
        !payload.stash_subrepo_changes_required
      ) {
        return false;
      }
      return window.confirm(
        "Nested repositories have tracked changes.\\n\\nStash those changes before switching all repositories to the new branch?",
      );
    }

    function workItemEndpoint() {
      if (workItemMode === "bug-new") {
        return "/api/work-items/bugs";
      }
      return "/api/work-items/features";
    }

    function workItemRequestBody(title) {
      if (workItemMode === "bug-new") {
        return {
          issue_reference: title,
          branch: workItemBranchCheckbox.checked,
        };
      }
      return {
        title,
        name: workItemName.value.trim(),
        branch: workItemBranchCheckbox.checked,
      };
    }

    function workItemPendingLabel() {
      if (workItemMode === "bug-new") {
        return "starting bug-resolution workflow";
      }
      return "starting feature workflow";
    }

    async function switchFeatureWorkItemContext(slug) {
      await switchWorkItemContext(
        "/api/work-items/features/switch",
        { slug },
        "switched feature",
      );
    }

    async function switchBugWorkItemContext(slug) {
      await switchWorkItemContext(
        "/api/work-items/bugs/switch",
        { slug },
        "switched bug resolution",
      );
    }

    async function switchWorkItemContext(endpoint, body, successLabel) {
      if (!activeProjectRoot) {
        return;
      }
      if (!confirmWorkItemAgentStop()) {
        return;
      }
      hideWorkItemRecovery();
      hideStageMenus();
      const response = await fetch(contextUrl(endpoint), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => ({ error: "switch failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "switch failed"}\\n`, "error");
        if (recoverableWorkItemError(payload.error || "switch failed", payload)) {
          showWorkItemRecovery();
        }
        return;
      }
      appendOutput(`${successLabel}: ${payload.label || ""}\\n`, "system");
      if (payload.terminated_agent) {
        appendOutput("stopped running agent for work-item context\\n", "system");
      }
      updateProjectState(payload);
    }

    function confirmWorkItemAgentStop() {
      if (!agentProcessRunning()) {
        return true;
      }
      return window.confirm(
        "A workflow agent is running in this browser context.\\n\\nStarting or switching work items will stop that agent. Continue?",
      );
    }

    function showWorkItemRecovery() {
      workItemRecovery.hidden = false;
    }

    function hideWorkItemRecovery() {
      workItemRecovery.hidden = true;
    }

    function recoverableWorkItemError(message, payload = {}) {
      if (payload.stash_subrepo_changes_required) {
        return true;
      }
      return /\\b(branch|checkout|switch|dirty|uncommitted|tracked changes|merge|rebase|conflict|index\\.lock|permission|stash|worktree|repository)\\b/i
        .test(message || "");
    }

    async function deactivateActiveProject() {
      if (!activationRoot) {
        return;
      }
      const previousProject = activationRoot;
      const response = await fetch(contextUrl("/api/project/deactivate"), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "deactivate failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "deactivate failed"}\\n`, "error");
        return;
      }
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      closeProgressEventStream();
      closeProjectShellEventStream();
      showProgressPane(false);
      showProjectShellPane(false);
      activationRoot = "";
      activeProjectMode = "none";
      activeProjectRoot = "";
      activeRepositoryName = "";
      registeredRepositories = [];
      workItemState = { collections: [], features: [], bugs: [] };
      projectPath.value = serviceRoot;
      projectMenu.hidden = true;
      requirementsMenu.hidden = true;
      hideStageActionPanel();
      hideStageMenus();
      hideStageMenus();
      documentMenu.hidden = true;
      agentInput.disabled = true;
      interruptAgent.disabled = true;
      startRequirements.disabled = false;
      requirementsRunning = false;
      designRunning = false;
      designReviewRunning = false;
      stageRunState = {};
      documentationRunning = false;
      adHocRunning = false;
      projectShellRunning = false;
      projectShellPaneDismissed = false;
      agentSessions = [];
      selectedSessionId = "";
      renderSessionSwitcher();
      activeAgentKind = "";
      agentInput.value = "";
      setAgentInputVisible(true);
      clearAgentOutput();
      clearProgressOutput();
      clearProjectShellOutput();
      hideArtifactPreview();
      hideWorkItemPanel();
      creativeActiveDocument = "";
      creativeActiveFolder = "";
      creativeEditingPath = "";
      creativeEditingType = "";
      expandedCreativeFolders = new Set();
      creativeLastNotifiedTarget = "";
      creativeTreePayload = null;
      recordProjectStatusMessage(`deactivated: ${previousProject}`);
      updateProjectState(payload);
    }

    function connectAgentEvents(kind) {
      const session = agentSessions.find((candidate) => candidate.kind === kind);
      if (session) {
        connectSessionEvents(session.session_id);
        return;
      }
      if (eventSource) {
        eventSource.close();
      }
      activeAgentKind = kind;
      prepareTerminalStream();
      eventSource = new EventSource(contextUrl(`/api/agents/${kind}/events`));
      eventSource.addEventListener("agent-event", (event) => {
        const payload = JSON.parse(event.data);
        if (payload.type === "output") {
          const outputText = terminal
            ? payload.terminal || payload.text || ""
            : payload.text || "";
          appendAgentOutput(outputText);
        } else if (payload.type === "system") {
          appendOutput(`${payload.text}\\n`, "system");
        } else if (payload.type === "error") {
          appendOutput(`${payload.text}\\n`, "error");
        } else if (payload.type === "completed") {
          appendOutput(`\\nprocess exited with code ${payload.returncode}\\n`, "system");
          if (kind === "requirements") {
            refreshArtifactPreview();
          }
          if (kind === "design-review") {
            closeProgressEventStream();
          }
          setAgentRunning(kind, false);
          refreshProject();
        }
      });
      eventSource.onerror = () => {};
    }

    function connectSessionEvents(sessionId) {
      if (!sessionId) {
        return;
      }
      if (eventSource) {
        eventSource.close();
      }
      selectedSessionId = sessionId;
      const session = selectedSession();
      activeAgentKind = session ? session.kind || "" : activeAgentKind;
      prepareTerminalStream();
      eventSource = new EventSource(
        contextUrl(`/api/sessions/events?session_id=${encodeURIComponent(sessionId)}`),
      );
      eventSource.addEventListener("agent-event", (event) => {
        const payload = JSON.parse(event.data);
        if (payload.type === "output") {
          const outputText = terminal
            ? payload.terminal || payload.text || ""
            : payload.text || "";
          appendAgentOutput(outputText);
        } else if (payload.type === "system") {
          appendOutput(`${payload.text}\\n`, "system");
        } else if (payload.type === "error") {
          appendOutput(`${payload.text}\\n`, "error");
        } else if (payload.type === "completed") {
          appendOutput(`\\nprocess exited with code ${payload.returncode}\\n`, "system");
          if (session && session.kind === "requirements") {
            refreshArtifactPreview();
          }
          if (session && !session.interactive) {
            closeProgressEventStream();
          }
          refreshProject();
        }
      });
      eventSource.onerror = () => {};
    }

    function connectProgressEvents() {
      if (progressEventSource) {
        progressEventSource.close();
      }
      showProgressPane(true);
      progressEventSource = new EventSource(contextUrl("/api/progress/events"));
      progressEventSource.addEventListener("progress-event", (event) => {
        const payload = JSON.parse(event.data);
        clearProgressOutput();
        appendProgressOutput(
          payload.text || "",
          payload.type === "error" ? "error" : "",
        );
        if (payload.running === false) {
          closeProgressEventStream();
        }
      });
      progressEventSource.onerror = () => {};
    }

    function closeAgentEventStream() {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
    }

    function closeProgressEventStream() {
      if (progressEventSource) {
        progressEventSource.close();
        progressEventSource = null;
      }
    }

    function agentProcessRunning() {
      return agentSessions.some((session) => session.status === "running");
    }

    function updateAgentControls() {
      const acceptsInput = selectedSessionAcceptsInput();
      const session = selectedSession();
      agentInput.disabled = !acceptsInput;
      insertFileLink.disabled = !acceptsInput;
      interruptAgent.disabled = !sessionIsRunning(session);
      exportAgentOutput.disabled = !session;
      exportProgressOutput.disabled = !activationRoot;
    }

    function setAgentRunning(kind, isRunning) {
      if (kind === "requirements") {
        requirementsRunning = isRunning;
      } else if (kind === "design") {
        designRunning = isRunning;
      } else if (kind === "design-review") {
        designReviewRunning = isRunning;
        if (!isRunning) {
          designReviewInteractive = false;
        }
      } else if (kind === "documentation") {
        documentationRunning = isRunning;
      } else if (stageRunState[kind]) {
        stageRunState = {
          ...stageRunState,
          [kind]: {
            ...stageRunState[kind],
            running: isRunning,
            started: stageRunState[kind].started || isRunning,
          },
        };
      }
      if (kind === "requirements") {
        if (isRunning) {
          if (!manualArtifactPreview) {
            showArtifactPreview("requirements");
          }
        } else {
          closeArtifactEventStream();
          refreshArtifactPreview();
        }
      }
      if (isRunning) {
        activeAgentKind = kind;
      } else if (activeAgentKind === kind) {
        activeAgentKind = "";
      }
      updateAgentControls();
      updateRequirementsMenuState();
      updateDesignMenuState();
      updateDesignReviewMenuState();
      updateGenericStageMenuStates();
      updateDocumentMenuState();
    }

    function setRequirementsRunning(isRunning) {
      setAgentRunning("requirements", isRunning);
    }

    async function runStageAgent(
      kind,
      endpoint,
      label,
      clearOutput = false,
      acceptsInput = true,
    ) {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      hideStageMenus();
      closeAgentEventStream();
      if (acceptsInput) {
        showProgressPane(false);
      } else {
        showProgressPane(true);
        clearProgressOutput();
      }
      showStageArtifactPreview(kind);
      setAgentInputVisible(acceptsInput);
      if (clearOutput) {
        clearAgentOutput();
      }
      setAgentRunning(kind, true);
      agentInput.disabled = !acceptsInput;
      if (acceptsInput) {
        agentInput.focus();
      }
      appendOutput(`${label}\\n`, "system");
      const response = await fetch(contextUrl(endpoint), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "start failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "start failed"}\\n`, "error");
        if (!acceptsInput) {
          closeProgressEventStream();
          showProgressPane(false);
          setAgentInputVisible(true);
        }
        if (artifactPreviewStage === kind) {
          hideArtifactPreview();
        }
        setAgentRunning(kind, false);
        return;
      }
      updateProjectState(payload);
      setAgentRunning(kind, true);
      agentInput.disabled = !acceptsInput;
      connectAgentEvents(kind);
      if (!acceptsInput) {
        connectProgressEvents();
      }
      sendTerminalResize();
    }

    async function startAdHocAgent() {
      if (!activationRoot) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      hideStageMenus();
      closeAgentEventStream();
      closeProgressEventStream();
      showProgressPane(false);
      hideArtifactPreview();
      setAgentInputVisible(true);
      clearAgentOutput();
      agentInput.disabled = false;
      agentInput.focus();
      appendOutput("$ codex ad-hoc\\n", "system");
      const response = await fetch(contextUrl("/api/agents/ad-hoc/start"), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "start failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "start failed"}\\n`, "error");
        return;
      }
      updateProjectState(payload);
      const sessionId = payload.session_id || selectedSessionId;
      selectedSessionId = sessionId;
      renderSessionSwitcher();
      connectSessionEvents(sessionId);
      sendTerminalResize();
    }

    async function runRequirementsAgent(endpoint, label, clearOutput = false) {
      await runStageAgent("requirements", endpoint, label, clearOutput, true);
    }

    async function startRequirementsAgent() {
      if (currentWorkflowStage !== "requirements") {
        return;
      }
      await runRequirementsAgent(
        "/api/agents/requirements/start",
        "$ electroboy requirements",
      );
    }

    async function completeRequirementsAgent() {
      await approveRequirementsStage(false);
    }

    async function startDesignAgent() {
      if (currentWorkflowStage !== "design") {
        return;
      }
      await runStageAgent(
        "design",
        "/api/agents/design/start",
        "$ electroboy design",
        false,
        true,
      );
    }

    async function completeDesignAgent() {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      if (currentWorkflowStage !== "design") {
        return;
      }
      designMenu.hidden = true;
      closeAgentEventStream();
      const response = await fetch(contextUrl("/api/agents/design/complete"), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "complete failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "complete failed"}\\n`, "error");
        return;
      }
      setAgentRunning("design", false);
      agentInput.value = "";
      clearAgentOutput();
      updateProjectState(payload);
    }

    async function startAutomaticDesignReviewAgent() {
      if (currentWorkflowStage !== "design-review") {
        return;
      }
      designReviewInteractive = false;
      await runStageAgent(
        "design-review",
        "/api/agents/design-review/start",
        "$ electroboy design-review",
        true,
        false,
      );
    }

    async function startInteractiveDesignReviewAgent() {
      if (currentWorkflowStage !== "design-review") {
        return;
      }
      designReviewInteractive = true;
      await runStageAgent(
        "design-review",
        "/api/agents/design-review/start-interactive",
        "$ electroboy design-review --interactive",
        true,
        true,
      );
    }

    async function stopDesignReviewAgent() {
      if (currentWorkflowStage !== "design-review" || !designReviewRunning) {
        return;
      }
      hideStageMenus();
      const response = await fetch(contextUrl("/api/agents/design-review/stop"), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "stop failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "stop failed"}\\n`, "error");
        return;
      }
      closeAgentEventStream();
      closeProgressEventStream();
      setAgentRunning("design-review", false);
      appendOutput("design review stopped\\n", "system");
      updateProjectState(payload);
    }

    async function completeDesignReviewAgent() {
      await approveDesignReviewStage(false);
    }

    async function approveDesignReviewStage(skipApproval = false) {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      if (currentWorkflowStage !== "design-review") {
        return;
      }
      designReviewMenu.hidden = true;
      closeAgentEventStream();
      closeProgressEventStream();
      const endpoint = skipApproval
        ? "/api/agents/design-review/skip-approval"
        : "/api/agents/design-review/approve";
      const response = await fetch(contextUrl(endpoint), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "approval failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "approval failed"}\\n`, "error");
        if (payload.output) {
          appendOutput(`${payload.output}\\n`, "error");
        }
        setAgentRunning("design-review", false);
        refreshProject();
        return;
      }
      setAgentRunning("design-review", false);
      if (payload.output) {
        appendOutput(`${payload.output}\\n`, "system");
      }
      if (payload.warning) {
        appendOutput(`${payload.warning}\\n`, "system");
      }
      appendOutput(
        skipApproval
          ? "design approval skipped; next: implementation-plan\\n"
          : "design approved; next: implementation-plan\\n",
        "system",
      );
      updateProjectState(payload);
    }

    async function skipDesignReviewApprovalStage() {
      if (
        !designApproved &&
        !window.confirm(
          "Design has not been explicitly approved.\\n\\nSkip approval and advance to implementation planning anyway?",
        )
      ) {
        return;
      }
      await approveDesignReviewStage(true);
    }

    async function startGenericStageAgent(stage, label, acceptsInput = true) {
      if (currentWorkflowStage !== stage) {
        return;
      }
      const endpoint = acceptsInput
        ? `/api/agents/${stage}/start-interactive`
        : `/api/agents/${stage}/start`;
      await runStageAgent(stage, endpoint, label, acceptsInput === false, acceptsInput);
    }

    async function stopGenericStageAgent(stage, label) {
      const runState = genericStageRun(stage);
      if (currentWorkflowStage !== stage || !runState.running) {
        return;
      }
      hideStageMenus();
      const response = await fetch(contextUrl(`/api/agents/${stage}/stop`), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "stop failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "stop failed"}\\n`, "error");
        return;
      }
      closeAgentEventStream();
      closeProgressEventStream();
      setAgentRunning(stage, false);
      appendOutput(`${label} stopped\\n`, "system");
      updateProjectState(payload);
    }

    async function approveGenericStage(stage, label, skipApproval = false) {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      if (currentWorkflowStage !== stage) {
        return;
      }
      hideStageMenus();
      closeAgentEventStream();
      closeProgressEventStream();
      const endpoint = skipApproval
        ? `/api/agents/${stage}/skip-approval`
        : `/api/agents/${stage}/approve`;
      const response = await fetch(contextUrl(endpoint), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "approval failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "approval failed"}\\n`, "error");
        if (payload.output) {
          appendOutput(`${payload.output}\\n`, "error");
        }
        setAgentRunning(stage, false);
        refreshProject();
        return;
      }
      setAgentRunning(stage, false);
      if (payload.output) {
        appendOutput(`${payload.output}\\n`, "system");
      }
      if (payload.warning) {
        appendOutput(`${payload.warning}\\n`, "system");
      }
      appendOutput(
        skipApproval
          ? `${label} approval skipped\\n`
          : `${label} approved\\n`,
        "system",
      );
      updateProjectState(payload);
    }

    async function skipGenericStageApproval(stage, label) {
      if (
        !window.confirm(
          `${label} has not been explicitly approved.\\n\\nSkip approval and advance anyway?`,
        )
      ) {
        return;
      }
      await approveGenericStage(stage, label, true);
    }

    async function startDocumentationAgent(target = DEFAULT_DOCUMENT_TARGETS[0]) {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      const documentTarget = target || DEFAULT_DOCUMENT_TARGETS[0];
      hideStageMenus();
      closeAgentEventStream();
      showProgressPane(false);
      showDocumentPreview(documentTarget);
      setAgentInputVisible(true);
      clearAgentOutput();
      setAgentRunning("documentation", true);
      agentInput.disabled = false;
      agentInput.focus();
      appendOutput(
        `$ electroboy document --sidecar --interactive --target ${documentTarget.path}\\n`,
        "system",
      );
      const response = await fetch(contextUrl("/api/agents/documentation/start"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: documentTarget.path }),
      });
      const payload = await response.json().catch(() => ({ error: "start failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "start failed"}\\n`, "error");
        setAgentRunning("documentation", false);
        return;
      }
      updateProjectState(payload);
      setAgentRunning("documentation", true);
      const sessionId = payload.session_id || selectedSessionId;
      selectedSessionId = sessionId;
      renderSessionSwitcher();
      connectSessionEvents(sessionId);
      sendTerminalResize();
    }

    async function sendMessage() {
      if (!selectedSessionAcceptsInput()) {
        return;
      }
      if (slashCommandMode) {
        sendTerminalKey("enter");
        finishSlashCommandMode();
        return;
      }
      const message = agentInput.value;
      if (!message.trim()) {
        return;
      }
      agentInput.value = "";
      const response = await fetch(contextUrl("/api/sessions/message"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: creativePromptMessage(message) }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ error: "send failed" }));
        appendOutput(`${payload.error || "send failed"}\\n`, "error");
      }
    }

    function queueTerminalInput(task) {
      const next = terminalInputQueue.catch(() => {}).then(task);
      terminalInputQueue = next.catch(() => {});
      return next;
    }

    function sendTerminalKey(key) {
      if (!selectedSessionAcceptsInput()) {
        return Promise.resolve();
      }
      return queueTerminalInput(async () => {
        const response = await fetch(contextUrl("/api/sessions/key"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key }),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({ error: "send failed" }));
          appendOutput(`${payload.error || "send failed"}\\n`, "error");
        }
      });
    }

    function sendTerminalRaw(data) {
      if (!selectedSessionAcceptsInput() || !data) {
        return Promise.resolve();
      }
      return queueTerminalInput(async () => {
        const response = await fetch(contextUrl("/api/sessions/raw"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ data }),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({ error: "send failed" }));
          appendOutput(`${payload.error || "send failed"}\\n`, "error");
        }
      });
    }

    function printableInputEvent(event) {
      return (
        !event.altKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        event.key &&
        event.key.length === 1
      );
    }

    function slashCommandTerminalKeyForInputEvent(event) {
      if (event.altKey || event.ctrlKey || event.metaKey) {
        return "";
      }
      if (
        event.key === "Enter" ||
        event.code === "Enter" ||
        event.code === "NumpadEnter"
      ) {
        return "enter";
      }
      if (event.key === "Escape") return "escape";
      if (event.key === "ArrowUp") return "up";
      if (event.key === "ArrowDown") return "down";
      if (event.key === "ArrowLeft") return "left";
      if (event.key === "ArrowRight") return "right";
      if (event.key === "Backspace") return "backspace";
      if (event.key === "Delete") return "delete";
      if (event.key === "Tab") return "tab";
      return "";
    }

    function refreshSlashCommandModeAfterEdit() {
      window.setTimeout(() => {
        if (!agentInput.value.trimStart().startsWith("/")) {
          slashCommandMode = false;
        }
      }, 0);
    }

    function finishSlashCommandMode() {
      slashCommandMode = false;
      agentInput.value = "";
    }

    function handleSlashCommandInput(event) {
      if (
        !slashCommandMode &&
        printableInputEvent(event) &&
        event.key === "/" &&
        agentInput.value.trim().length === 0
      ) {
        slashCommandMode = true;
        sendTerminalRaw(event.key);
        return true;
      }
      if (!slashCommandMode) {
        return false;
      }
      const slashKey = slashCommandTerminalKeyForInputEvent(event);
      if (slashKey) {
        sendTerminalKey(slashKey);
        if (slashKey === "enter" || slashKey === "escape") {
          event.preventDefault();
          finishSlashCommandMode();
        } else if (slashKey === "backspace" || slashKey === "delete") {
          refreshSlashCommandModeAfterEdit();
        } else {
          event.preventDefault();
        }
        return true;
      }
      if (printableInputEvent(event)) {
        sendTerminalRaw(event.key);
        return true;
      }
      return false;
    }

    function terminalKeyForInputEvent(event) {
      if (
        !event.altKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.shiftKey &&
        event.key === "Escape"
      ) {
        return "escape";
      }
      if (agentInput.value.length > 0) {
        return "";
      }
      if (
        event.ctrlKey &&
        !event.altKey &&
        !event.metaKey &&
        !event.shiftKey &&
        /^[0-9]$/.test(event.key)
      ) {
        return event.key;
      }
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
        return "";
      }
      if (
        event.key === "Enter" ||
        event.code === "Enter" ||
        event.code === "NumpadEnter"
      ) {
        return "enter";
      }
      if (event.key === "ArrowUp") return "up";
      if (event.key === "ArrowDown") return "down";
      if (event.key === "ArrowLeft") return "left";
      if (event.key === "ArrowRight") return "right";
      if (event.key === "Tab") return "tab";
      return "";
    }

    async function interruptActiveAgent() {
      if (!sessionIsRunning(selectedSession())) {
        return;
      }
      const response = await fetch(contextUrl("/api/sessions/interrupt"), {
        method: "POST",
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ error: "interrupt failed" }));
        appendOutput(`${payload.error || "interrupt failed"}\\n`, "error");
      }
    }

    function positionStageMenu(menu, stage) {
      const paneRect = workflowPane.getBoundingClientRect();
      const stageRect = stage.getBoundingClientRect();
      const menuWidth = menu.offsetWidth || 192;
      const inset = 8;
      const left = Math.max(
        inset,
        Math.min(stageRect.left - paneRect.left, workflowPane.clientWidth - menuWidth - inset),
      );
      menu.style.left = `${left}px`;
      menu.style.top = `${stageRect.bottom - paneRect.top + inset}px`;
    }

    function hideStageMenus(exceptMenu = null) {
      const menus = [
        projectMenu,
        requirementsMenu,
        designMenu,
        designReviewMenu,
        implementationPlanMenu,
        codeMenu,
        testPlanMenu,
        validateMenu,
        documentMenu,
      ];
      for (const menu of menus) {
        if (menu !== exceptMenu) {
          menu.hidden = true;
        }
      }
      if (exceptMenu !== projectMenu) {
        hideSubmenu(metaProjectSubmenu, metaProjectMenuButton);
        hideSubmenu(workItemSubmenu, workItemMenuButton);
      }
      hideSubmenu(startMetaRepositorySubmenu, startMetaRepository);
      hideSubmenu(removeMetaRepositorySubmenu, removeMetaRepository);
      hideSubmenu(switchFeatureWorkItemSubmenu, switchFeatureWorkItem);
      hideSubmenu(switchBugWorkItemSubmenu, switchBugWorkItem);
    }

    function toggleStageMenu(menu, stage) {
      const shouldOpen = menu.hidden;
      hideStageMenus(menu);
      menu.hidden = !shouldOpen;
      if (shouldOpen) {
        positionStageMenu(menu, stage);
      } else if (menu === projectMenu) {
        hideSubmenu(metaProjectSubmenu, metaProjectMenuButton);
        hideSubmenu(workItemSubmenu, workItemMenuButton);
        hideSubmenu(startMetaRepositorySubmenu, startMetaRepository);
        hideSubmenu(removeMetaRepositorySubmenu, removeMetaRepository);
        hideSubmenu(switchFeatureWorkItemSubmenu, switchFeatureWorkItem);
        hideSubmenu(switchBugWorkItemSubmenu, switchBugWorkItem);
      }
    }

    function repositionOpenStageMenu() {
      if (!projectMenu.hidden) {
        positionStageMenu(projectMenu, projectStage);
      }
      if (!requirementsMenu.hidden) {
        positionStageMenu(requirementsMenu, requirementsStage);
      }
      if (!designMenu.hidden) {
        positionStageMenu(designMenu, designStage);
      }
      if (!designReviewMenu.hidden) {
        positionStageMenu(designReviewMenu, designReviewStage);
      }
      if (!implementationPlanMenu.hidden) {
        positionStageMenu(implementationPlanMenu, implementationPlanStage);
      }
      if (!codeMenu.hidden) {
        positionStageMenu(codeMenu, codeStage);
      }
      if (!testPlanMenu.hidden) {
        positionStageMenu(testPlanMenu, testPlanStage);
      }
      if (!validateMenu.hidden) {
        positionStageMenu(validateMenu, validateStage);
      }
      if (!documentMenu.hidden) {
        positionStageMenu(documentMenu, documentStage);
      }
    }

    async function handleWorkflowStageClick(stageNode) {
      const stageId = stageNode.dataset.stage || "";
      if (stageNode.disabled) {
        return;
      }
      showStageActionPanel(stageId);
    }

    projectStage.addEventListener("click", () => {
      showStageActionPanel("project");
    });
    for (const stageNode of stageNodes) {
      if (stageNode.dataset.stage === "project") {
        continue;
      }
      stageNode.addEventListener("click", () => {
        handleWorkflowStageClick(stageNode).catch((error) => {
          appendOutput(`stage update failed: ${error}\\n`, "error");
        });
      });
    }

    openProject.addEventListener("click", () => openProjectBrowser("open", true));
    newProject.addEventListener("click", () => openProjectBrowser("new", true));
    openMetaProject.addEventListener("click", () => openProjectBrowser("open", true));
    newMetaProject.addEventListener("click", () => openProjectBrowser("meta-new", true));
    addMetaRepository.addEventListener("click", () => showProjectPanel("meta-add"));
    metaProjectMenuButton.addEventListener("click", () => {
      toggleSubmenu(metaProjectSubmenu, metaProjectMenuButton);
    });
    metaProjectBranch.addEventListener("mouseenter", () => {
      showSubmenu(metaProjectSubmenu, metaProjectMenuButton);
    });
    metaProjectBranch.addEventListener("mouseleave", () => {
      hideSubmenu(metaProjectSubmenu, metaProjectMenuButton);
    });
    startMetaRepository.addEventListener("click", () => {
      toggleSubmenu(startMetaRepositorySubmenu, startMetaRepository);
    });
    startMetaRepositoryBranch.addEventListener("mouseenter", () => {
      showSubmenu(startMetaRepositorySubmenu, startMetaRepository);
    });
    startMetaRepositoryBranch.addEventListener("mouseleave", () => {
      hideSubmenu(startMetaRepositorySubmenu, startMetaRepository);
    });
    removeMetaRepository.addEventListener("click", () => {
      toggleSubmenu(removeMetaRepositorySubmenu, removeMetaRepository);
    });
    removeMetaRepositoryBranch.addEventListener("mouseenter", () => {
      showSubmenu(removeMetaRepositorySubmenu, removeMetaRepository);
    });
    removeMetaRepositoryBranch.addEventListener("mouseleave", () => {
      hideSubmenu(removeMetaRepositorySubmenu, removeMetaRepository);
    });
    workItemMenuButton.addEventListener("click", () => {
      toggleSubmenu(workItemSubmenu, workItemMenuButton);
    });
    workItemBranch.addEventListener("mouseenter", () => {
      showSubmenu(workItemSubmenu, workItemMenuButton);
    });
    workItemBranch.addEventListener("mouseleave", () => {
      hideSubmenu(workItemSubmenu, workItemMenuButton);
    });
    switchFeatureWorkItem.addEventListener("click", () => {
      toggleSubmenu(switchFeatureWorkItemSubmenu, switchFeatureWorkItem);
    });
    switchFeatureWorkItemBranch.addEventListener("mouseenter", () => {
      showSubmenu(switchFeatureWorkItemSubmenu, switchFeatureWorkItem);
    });
    switchFeatureWorkItemBranch.addEventListener("mouseleave", () => {
      hideSubmenu(switchFeatureWorkItemSubmenu, switchFeatureWorkItem);
    });
    switchBugWorkItem.addEventListener("click", () => {
      toggleSubmenu(switchBugWorkItemSubmenu, switchBugWorkItem);
    });
    switchBugWorkItemBranch.addEventListener("mouseenter", () => {
      showSubmenu(switchBugWorkItemSubmenu, switchBugWorkItem);
    });
    switchBugWorkItemBranch.addEventListener("mouseleave", () => {
      hideSubmenu(switchBugWorkItemSubmenu, switchBugWorkItem);
    });
    newFeatureWorkItem.addEventListener("click", () => showWorkItemPanel("feature-new"));
    newBugWorkItem.addEventListener("click", () => showWorkItemPanel("bug-new"));
    applyWorkItem.addEventListener("click", applyWorkItemSelection);
    cancelWorkItem.addEventListener("click", hideWorkItemPanel);
    openProjectShell.addEventListener("click", startProjectShell);
    retryWorkItem.addEventListener("click", applyWorkItemSelection);
    toggleProjectShellPane.addEventListener("click", () => {
      toggleProjectShellFromToolbar().catch((error) => {
        appendOutput(`project shell failed: ${error}\\n`, "error");
      });
    });
    workItemTitle.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        applyWorkItemSelection();
      }
    });
    deactivateProject.addEventListener("click", deactivateActiveProject);
    browseProject.addEventListener("click", () => {
      openProjectBrowser();
    });
    activateProject.addEventListener("click", applyProjectSelection);
    upDirectory.addEventListener("click", () => {
      if (currentBrowseParent) {
        browseDirectory(currentBrowseParent, currentBrowserMode);
      }
    });
    selectDirectory.addEventListener("click", selectCurrentDirectory);
    closeBrowser.addEventListener("click", () => {
      fileBrowser.hidden = true;
      if (currentBrowserMode === "link") {
        agentInput.focus();
      } else {
        projectPath.focus();
      }
    });

    setRequirementsStage.addEventListener("click", () => {
      setWorkflowStageFromMenu("requirements");
    });
    startRequirements.addEventListener("click", startRequirementsAgent);
    approveRequirements.addEventListener("click", approveRequirementsStage);
    skipRequirementsApproval.addEventListener("click", skipRequirementsApprovalStage);
    setDesignStage.addEventListener("click", () => {
      setWorkflowStageFromMenu("design");
    });
    startDesign.addEventListener("click", startDesignAgent);
    completeDesign.addEventListener("click", completeDesignAgent);
    setDesignReviewStage.addEventListener("click", () => {
      setWorkflowStageFromMenu("design-review");
    });
    startAutomaticDesignReview.addEventListener("click", startAutomaticDesignReviewAgent);
    startInteractiveDesignReview.addEventListener("click", startInteractiveDesignReviewAgent);
    stopDesignReview.addEventListener("click", stopDesignReviewAgent);
    approveDesignReview.addEventListener("click", approveDesignReviewStage);
    skipDesignReviewApproval.addEventListener("click", skipDesignReviewApprovalStage);
    setImplementationPlanStage.addEventListener("click", () => {
      setWorkflowStageFromMenu("implementation-plan");
    });
    startImplementationPlan.addEventListener("click", () => {
      startGenericStageAgent(
        "implementation-plan",
        "$ electroboy implementation-plan",
        true,
      );
    });
    approveImplementationPlan.addEventListener("click", () => {
      approveGenericStage("implementation-plan", "implementation plan");
    });
    skipImplementationPlanApproval.addEventListener("click", () => {
      skipGenericStageApproval("implementation-plan", "Implementation plan");
    });
    setCodeStage.addEventListener("click", () => {
      setWorkflowStageFromMenu("code");
    });
    startAutomaticCode.addEventListener("click", () => {
      startGenericStageAgent("code", "$ electroboy code", false);
    });
    startInteractiveCode.addEventListener("click", () => {
      startGenericStageAgent("code", "$ electroboy code --interactive", true);
    });
    startCodeAdHocAgentButton.addEventListener("click", startAdHocAgent);
    stopCode.addEventListener("click", () => stopGenericStageAgent("code", "code"));
    approveCode.addEventListener("click", () => approveGenericStage("code", "code"));
    skipCodeApproval.addEventListener("click", () => {
      skipGenericStageApproval("code", "Code");
    });
    setTestPlanStage.addEventListener("click", () => {
      setWorkflowStageFromMenu("test-plan");
    });
    startTestPlan.addEventListener("click", () => {
      startGenericStageAgent("test-plan", "$ electroboy test-plan", true);
    });
    approveTestPlan.addEventListener("click", () => {
      approveGenericStage("test-plan", "test plan");
    });
    skipTestPlanApproval.addEventListener("click", () => {
      skipGenericStageApproval("test-plan", "Test plan");
    });
    setValidateStage.addEventListener("click", () => {
      setWorkflowStageFromMenu("validate");
    });
    startAutomaticValidate.addEventListener("click", () => {
      startGenericStageAgent("validate", "$ electroboy validate", false);
    });
    startInteractiveValidate.addEventListener("click", () => {
      startGenericStageAgent("validate", "$ electroboy validate --interactive", true);
    });
    stopValidate.addEventListener("click", () => {
      stopGenericStageAgent("validate", "validation");
    });
    approveValidate.addEventListener("click", () => {
      approveGenericStage("validate", "validation");
    });
    skipValidateApproval.addEventListener("click", () => {
      skipGenericStageApproval("validate", "Validation");
    });
    createDocumentTarget.addEventListener("click", () => {
      customDocumentForm.hidden = !customDocumentForm.hidden;
      if (!customDocumentForm.hidden) {
        customDocumentName.focus();
      }
    });
    addDocumentTarget.addEventListener("click", addCustomDocumentTarget);
    customDocumentName.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        addCustomDocumentTarget();
      }
    });
    sessionSwitcher.addEventListener("change", () => {
      selectAgentSession(sessionSwitcher.value).catch((error) => {
        appendOutput(`session switch failed: ${error}\\n`, "error");
      });
    });
    exportAgentOutput.addEventListener("click", () => {
      exportAgentSession().catch((error) => {
        appendOutput(`export failed: ${error}\\n`, "error");
      });
    });
    exportProgressOutput.addEventListener("click", () => {
      exportProgressLog().catch((error) => {
        appendOutput(`export failed: ${error}\\n`, "error");
      });
    });
    decreaseTerminalFont.addEventListener("click", () => changeTerminalFontSize(-1));
    increaseTerminalFont.addEventListener("click", () => changeTerminalFontSize(1));
    document.querySelectorAll("[data-pane-font-delta]").forEach((button) => {
      button.addEventListener("click", () => {
        changePaneFontOffset(
          button.dataset.paneFont || "",
          Number(button.dataset.paneFontDelta || "0"),
        );
      });
    });
    document.querySelectorAll("[data-pane-font-reset]").forEach((button) => {
      button.addEventListener("click", () => {
        resetPaneFontOffset(button.dataset.paneFont || "");
      });
    });
    window.addEventListener("storage", (event) => {
      if (!event.key || !event.key.startsWith(PANE_FONT_OFFSET_STORAGE_PREFIX)) {
        return;
      }
      const pane = event.key.slice(PANE_FONT_OFFSET_STORAGE_PREFIX.length);
      if (!PANE_FONT_KEYS.includes(pane)) {
        return;
      }
      paneFontOffsets[pane] = storedPaneFontOffset(pane);
      applyPaneFontSize(pane);
    });
    popoutAgentPane.addEventListener("click", () => popOutPane("agent"));
    popoutProgressPane.addEventListener("click", () => popOutPane("progress"));
    popoutProjectShellPane.addEventListener("click", () => popOutPane("shell"));
    popoutScratchPane.addEventListener("click", () => popOutPane("scratch"));
    popoutStatusPane.addEventListener("click", () => popOutPane("status"));
    popoutInputPane.addEventListener("click", () => popOutPane("input"));
    shellResizeHandle.addEventListener("pointerdown", startShellResize);
    shellResizeHandle.addEventListener("pointermove", updateShellResize);
    shellResizeHandle.addEventListener("pointerup", finishShellResize);
    shellResizeHandle.addEventListener("pointercancel", finishShellResize);
    inputResizeHandle.addEventListener("pointerdown", startInputResize);
    inputResizeHandle.addEventListener("pointermove", updateInputResize);
    inputResizeHandle.addEventListener("pointerup", finishInputResize);
    inputResizeHandle.addEventListener("pointercancel", finishInputResize);
    inputActionResizeHandle.addEventListener("pointerdown", startInputActionsResize);
    inputActionResizeHandle.addEventListener("pointermove", updateInputActionsResize);
    inputActionResizeHandle.addEventListener("pointerup", finishInputActionsResize);
    inputActionResizeHandle.addEventListener("pointercancel", finishInputActionsResize);
    outputResizeHandle.addEventListener("pointerdown", startOutputResize);
    outputResizeHandle.addEventListener("pointermove", updateOutputResize);
    outputResizeHandle.addEventListener("pointerup", finishOutputResize);
    outputResizeHandle.addEventListener("pointercancel", finishOutputResize);
    shellPaneDivider.addEventListener("pointerdown", startProjectShellPaneResize);
    shellPaneDivider.addEventListener("pointermove", updateProjectShellPaneResize);
    shellPaneDivider.addEventListener("pointerup", finishProjectShellPaneResize);
    shellPaneDivider.addEventListener("pointercancel", finishProjectShellPaneResize);
    workbenchResizeHandle.addEventListener("pointerdown", startWorkbenchResize);
    workbenchResizeHandle.addEventListener("pointermove", updateWorkbenchResize);
    workbenchResizeHandle.addEventListener("pointerup", finishWorkbenchResize);
    workbenchResizeHandle.addEventListener("pointercancel", finishWorkbenchResize);
    sidePaneResizeHandle.addEventListener("pointerdown", startSidePaneResize);
    sidePaneResizeHandle.addEventListener("pointermove", updateSidePaneResize);
    sidePaneResizeHandle.addEventListener("pointerup", finishSidePaneResize);
    sidePaneResizeHandle.addEventListener("pointercancel", finishSidePaneResize);
    artifactPaneResizeHandle.addEventListener("pointerdown", startArtifactPaneResize);
    artifactPaneResizeHandle.addEventListener("pointermove", updateArtifactPaneResize);
    artifactPaneResizeHandle.addEventListener("pointerup", finishArtifactPaneResize);
    artifactPaneResizeHandle.addEventListener("pointercancel", finishArtifactPaneResize);
    interruptAgent.addEventListener("click", interruptActiveAgent);
    closeProjectShellPane.addEventListener("click", hideProjectShellPane);
    stopProjectShell.addEventListener("click", stopProjectShellProcess);
    insertFileLink.addEventListener("click", () => {
      if (insertFileLink.disabled) {
        return;
      }
      openLinkFileBrowser();
    });
    toggleWorkflowSideSheet.addEventListener("click", toggleWorkflowSideSheetCollapsed);
    stageScroll.addEventListener("scroll", repositionOpenStageMenu);
    window.addEventListener("resize", repositionOpenStageMenu);
    closeSplash.addEventListener("click", dismissSplash);
    showSplashButton.addEventListener("click", openSplash);
    splashOverlay.addEventListener("click", (event) => {
      if (event.target === splashOverlay) {
        dismissSplash();
      }
    });
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && splashOverlay && !splashOverlay.hidden) {
        dismissSplash();
      }
    });

    agentInput.addEventListener("keydown", (event) => {
      if (handleSlashCommandInput(event)) {
        return;
      }
      const terminalKey = terminalKeyForInputEvent(event);
      if (terminalKey) {
        event.preventDefault();
        sendTerminalKey(terminalKey);
        return;
      }
      const isEnter =
        event.key === "Enter" ||
        event.code === "Enter" ||
        event.code === "NumpadEnter";
      if (isEnter && event.shiftKey) {
        event.preventDefault();
        if (agentInput.value.trim()) {
          sendMessage();
        } else {
          sendTerminalKey("enter");
        }
      }
    });
    scratchPad.addEventListener("input", saveScratchPad);
    workflowModeSelect.addEventListener("change", () => {
      setWorkflowMode(workflowModeSelect.value).catch((error) => {
        appendOutput(`workflow switch failed: ${error}\n`, "error");
      });
    });
    creativeProjectMenuButton.addEventListener("click", () => {
      toggleCreativeActionGroup("project");
    });
    creativeAgentMenuButton.addEventListener("click", () => {
      toggleCreativeActionGroup("agent");
    });
    creativeOpenProject.addEventListener("click", () => {
      openProjectBrowser("open", true);
    });
    creativeNewProject.addEventListener("click", () => {
      openProjectBrowser("new", true);
    });
    creativeCloseProject.addEventListener("click", deactivateActiveProject);
    creativeStartAgent.addEventListener("click", () => {
      startCreativeWritingAgent();
    });

    async function initialize() {
      applyStageDescriptions();
      applyWorkflowSideSheetState();
      applyWorkflowMode();
      renderStageActionPanel();
      initializePaneLayout();
      applyStoredPaneSizes();
      applyStoredProgressPaneSize();
      applyStoredArtifactPaneSize();
      applyStoredWorkbenchPaneSize();
      applySidePaneVisibility();
      restoreScratchPad();
      applyTerminalFontSize();
      applyDocumentZoom();
      initializeTerminal();
      observeTerminalPaneResizes();
      showSplashIfNeeded();
      await checkConnection();
      await restoreContext();
    }

    window.addEventListener("pagehide", releaseContextOwner);
    window.addEventListener("pageshow", () => {
      if (contextId) {
        claimContextOwner(contextId);
      }
    });

    initialize().catch(() => {});
  </script>
</body>
</html>
"""

INDEX_HTML = (
    INDEX_HTML_TEMPLATE.replace("__SPLASH_IMAGE_ROUTE__", SPLASH_IMAGE_ROUTE)
    .replace("__CREATIVE_SPLASH_IMAGE_ROUTE__", CREATIVE_SPLASH_IMAGE_ROUTE)
)


PANE_WINDOW_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ElectroBoy Pane</title>
  <link
    rel="stylesheet"
    href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css"
  >
  <style>
    :root {
      --terminal: #10141f;
      --terminal-text: #e7edf7;
      --border: #2a3142;
      --font-size: 15px;
    }

    * {
      box-sizing: border-box;
    }

    html,
    body {
      height: 100%;
      margin: 0;
      background: var(--terminal);
      color: var(--terminal-text);
      font-family:
        Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      font-size: var(--font-size);
      overflow: hidden;
    }

    .pane-window {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      height: 100vh;
      min-height: 0;
    }

    .pane-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-height: 38px;
      border-bottom: 1px solid var(--border);
      background: #151b29;
      padding: 0 10px 0 12px;
      font-weight: 400;
      text-transform: uppercase;
    }

    .pane-toolbar button,
    .pane-toolbar select,
    .input-actions button,
    .input-actions select {
      min-height: 30px;
      border: 1px solid #364156;
      border-radius: 6px;
      background: #1d2638;
      color: var(--terminal-text);
      cursor: pointer;
      font: inherit;
      font-size: calc(var(--font-size) - 2px);
      font-weight: 750;
    }

    .pane-toolbar select {
      min-width: 100px;
      cursor: pointer;
    }

    .pane-toolbar button.active {
      border-color: #66d9e8;
      background: #1f6f8b;
      color: #ffffff;
    }

    .input-actions select {
      min-width: 150px;
      cursor: pointer;
    }

    .pane-actions,
    .artifact-zoom-controls,
    .pane-font-controls {
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
    }

    .artifact-zoom-controls[hidden] {
      display: none;
    }

    .artifact-zoom-level {
      min-width: 44px;
      text-align: center;
      color: #aab8cf;
      font-size: calc(var(--font-size) - 2px);
      font-weight: 750;
    }

    .pane-font-level {
      min-width: 44px;
      text-align: center;
      color: #aab8cf;
      font-size: calc(var(--font-size) - 2px);
      font-weight: 750;
    }

    .pane-body {
      min-height: 0;
      overflow: hidden;
    }

    .terminal-host,
    .artifact-frame,
    .scratch-pad,
    .status-output,
    .input-text {
      width: 100%;
      height: 100%;
      min-height: 0;
      border: 0;
      background: var(--terminal);
      color: var(--terminal-text);
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: var(--font-size);
      line-height: 1.45;
      outline: none;
    }

    .terminal-host .xterm {
      width: 100%;
      height: 100%;
      box-sizing: border-box;
      padding: 10px 12px;
    }

    .artifact-frame {
      background: var(--terminal);
      color-scheme: dark;
      opacity: 1;
      transition: opacity 80ms ease;
    }

    .artifact-frame.loading {
      opacity: 0;
    }

    .scratch-pad,
    .status-output,
    .input-text {
      padding: 10px 12px;
      resize: none;
      white-space: pre-wrap;
    }

    .status-output {
      margin: 0;
      overflow: auto;
    }

    .input-layout {
      display: grid;
      grid-template-rows: minmax(0, 1fr) auto;
      height: 100%;
      min-height: 0;
    }

    .input-actions {
      display: grid;
      grid-template-columns: minmax(160px, 1fr) auto auto;
      align-items: end;
      gap: 8px;
      border-top: 1px solid var(--border);
      background: #151b29;
      padding: 8px;
    }

    .input-session-control {
      display: grid;
      gap: 4px;
      min-width: 0;
    }

    .input-session-control label {
      color: #aab8cf;
      font-size: calc(var(--font-size) - 3px);
      font-weight: 750;
    }

    .input-session-control select {
      width: 100%;
      min-width: 0;
    }

    [hidden] {
      display: none;
    }
  </style>
</head>
<body>
  <main class="pane-window">
    <header class="pane-toolbar">
      <span id="paneTitle">Pane</span>
      <div class="pane-actions">
        <div id="paneFontControls" class="pane-font-controls" aria-label="Pane font size">
          <button
            id="decreasePaneFont"
            type="button"
            title="Decrease pane font size"
            aria-label="Decrease pane font size"
          >A-</button>
          <span id="paneFontLevel" class="pane-font-level">15px</span>
          <button
            id="resetPaneFont"
            type="button"
            title="Reset pane font size"
            aria-label="Reset pane font size"
          >0</button>
          <button
            id="increasePaneFont"
            type="button"
            title="Increase pane font size"
            aria-label="Increase pane font size"
          >A+</button>
        </div>
        <div id="artifactZoomControls" class="artifact-zoom-controls" hidden>
          <button
            id="decreaseArtifactZoom"
            type="button"
            title="Zoom document out"
            aria-label="Zoom document out"
          >-</button>
          <span id="artifactZoomLevel" class="artifact-zoom-level">100%</span>
          <button
            id="increaseArtifactZoom"
            type="button"
            title="Zoom document in"
            aria-label="Zoom document in"
          >+</button>
        </div>
        <button
          id="refreshArtifact"
          type="button"
          title="Refresh document"
          aria-label="Refresh document"
          hidden
        >Refresh</button>
        <button
          id="previewArtifact"
          type="button"
          title="Preview document"
          aria-label="Preview document"
          hidden
        >Preview</button>
        <button
          id="editArtifact"
          type="button"
          title="Edit document"
          aria-label="Edit document"
          hidden
        >Edit</button>
        <select
          id="exportPaneFormat"
          title="Export format"
          aria-label="Export format"
          hidden
        >
          <option value="markdown">Markdown</option>
          <option value="docx">DOCX</option>
          <option value="pdf">PDF</option>
        </select>
        <button
          id="exportPaneOutput"
          type="button"
          title="Export pane output or document"
          aria-label="Export pane output or document"
          hidden
        >Export</button>
        <button id="dockPane" type="button">Dock</button>
      </div>
    </header>
    <section class="pane-body">
      <div id="terminalHost" class="terminal-host" hidden></div>
      <iframe
        id="artifactFrame"
        class="artifact-frame"
        title="Rendered artifact preview"
        sandbox="allow-scripts allow-popups allow-modals allow-same-origin"
        hidden
      ></iframe>
      <textarea id="scratchPad" class="scratch-pad" spellcheck="true" hidden></textarea>
      <pre id="statusOutput" class="status-output" hidden></pre>
      <div id="inputLayout" class="input-layout" hidden>
        <textarea id="agentInput" class="input-text" spellcheck="true"></textarea>
        <div class="input-actions">
          <div class="input-session-control">
            <label for="sessionSwitcher">Select Agent</label>
            <select
              id="sessionSwitcher"
              aria-label="Select Agent"
              disabled
            ></select>
          </div>
          <button id="interruptAgent" type="button">Interrupt</button>
          <button id="sendAgentInput" type="button">Send</button>
        </div>
      </div>
    </section>
  </main>
  <script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js"></script>
  <script>
    const PANE_KIND = __PANE_KIND__;
    const params = new URLSearchParams(window.location.search);
    const contextId = params.get("context_id") || "";
    let selectedSessionId = params.get("session_id") || "";
    const artifactKind = params.get("artifact") || "requirements";
    const artifactDocumentPath = params.get("document_path") || "";
    const artifactDocumentTitle = params.get("document_title") || "";
    const artifactRoutePath = params.get("artifact_path") || "";
    const artifactRouteTitle = params.get("artifact_title") || "";
    const artifactFolderPath = params.get("folder_path") || "";
    const artifactFolderTitle = params.get("folder_title") || "";
    const artifactCorkboardPath = params.get("corkboard_path") || "";
    const artifactCorkboardTitle = params.get("corkboard_title") || "";
    const TERMINAL_FONT_STORAGE_KEY = "electroboy.terminalFontSize";
    const PANE_FONT_OFFSET_STORAGE_PREFIX = "electroboy.paneFontOffset.";
    const DEFAULT_FONT_SIZE = 15;
    const MIN_FONT_SIZE = 11;
    const MAX_FONT_SIZE = 24;
    const MIN_FONT_OFFSET = -6;
    const MAX_FONT_OFFSET = 6;
    const fontPane = params.get("font_pane") || paneFontKeyForKind(PANE_KIND);
    let baseFontSize = storedBaseFontSize();
    let fontOffset = storedFontOffset();
    let fontSize = effectiveFontSize();
    const MIN_ARTIFACT_ZOOM = 70;
    const MAX_ARTIFACT_ZOOM = 180;
    const ARTIFACT_ZOOM_STEP = 10;
    let artifactZoom = clampArtifactZoom(Number(params.get("document_zoom") || "100"));
    const SCRATCH_PAD_STORAGE_KEY = "electroboy.scratchPad";
    const paneTitle = document.getElementById("paneTitle");
    const dockPane = document.getElementById("dockPane");
    const paneFontControls = document.getElementById("paneFontControls");
    const decreasePaneFont = document.getElementById("decreasePaneFont");
    const paneFontLevel = document.getElementById("paneFontLevel");
    const resetPaneFont = document.getElementById("resetPaneFont");
    const increasePaneFont = document.getElementById("increasePaneFont");
    const artifactZoomControls = document.getElementById("artifactZoomControls");
    const decreaseArtifactZoom = document.getElementById("decreaseArtifactZoom");
    const artifactZoomLevel = document.getElementById("artifactZoomLevel");
    const increaseArtifactZoom = document.getElementById("increaseArtifactZoom");
    const refreshArtifactButton = document.getElementById("refreshArtifact");
    const previewArtifactButton = document.getElementById("previewArtifact");
    const editArtifactButton = document.getElementById("editArtifact");
    const exportPaneFormat = document.getElementById("exportPaneFormat");
    const exportPaneOutput = document.getElementById("exportPaneOutput");
    const terminalHost = document.getElementById("terminalHost");
    const artifactFrame = document.getElementById("artifactFrame");
    const scratchPad = document.getElementById("scratchPad");
    const statusOutput = document.getElementById("statusOutput");
    const inputLayout = document.getElementById("inputLayout");
    const agentInput = document.getElementById("agentInput");
    const sessionSwitcher = document.getElementById("sessionSwitcher");
    const sendAgentInput = document.getElementById("sendAgentInput");
    const interruptAgent = document.getElementById("interruptAgent");
    let agentSessions = [];
    let terminal = null;
    let terminalFit = null;
    let terminalResizeObserver = null;
    let terminalResizeTimer = null;
    let pendingTerminalResize = null;
    let eventSource = null;
    let artifactEventSource = null;
    let slashCommandMode = false;
    let terminalInputQueue = Promise.resolve();
    let artifactVersion = 0;
    let artifactEditing = false;
    let statusTimer = null;

    applyFontSize();

    function paneFontKeyForKind(kind) {
      if (kind === "shell") return "shell";
      if (kind === "progress") return "progress";
      if (kind === "input") return "input";
      if (kind === "scratch") return "scratch";
      if (kind === "status") return "status";
      return "agent";
    }

    function storedBaseFontSize() {
      const requested = Number(
        params.get("base_font_size") || params.get("font_size") || "",
      );
      if (Number.isFinite(requested) && requested > 0) {
        return clampFontSize(requested);
      }
      try {
        const stored = Number(window.localStorage.getItem(TERMINAL_FONT_STORAGE_KEY));
        if (Number.isFinite(stored) && stored > 0) {
          return clampFontSize(stored);
        }
      } catch (error) {
        return DEFAULT_FONT_SIZE;
      }
      return DEFAULT_FONT_SIZE;
    }

    function storedFontOffset() {
      if (params.has("font_offset")) {
        const requested = Number(params.get("font_offset") || "");
        if (Number.isFinite(requested)) {
          return clampFontOffset(requested);
        }
      }
      return localStoredFontOffset();
    }

    function localStoredFontOffset() {
      try {
        const stored = Number(
          window.localStorage.getItem(PANE_FONT_OFFSET_STORAGE_PREFIX + fontPane),
        );
        if (Number.isFinite(stored)) {
          return clampFontOffset(stored);
        }
      } catch (error) {
        return 0;
      }
      return 0;
    }

    function clampFontSize(value) {
      return Math.max(MIN_FONT_SIZE, Math.min(MAX_FONT_SIZE, Math.round(value)));
    }

    function clampFontOffset(value) {
      return Math.max(MIN_FONT_OFFSET, Math.min(MAX_FONT_OFFSET, Math.round(value)));
    }

    function effectiveFontSize() {
      return clampFontSize(baseFontSize + fontOffset);
    }

    function saveFontOffset() {
      try {
        window.localStorage.setItem(
          PANE_FONT_OFFSET_STORAGE_PREFIX + fontPane,
          String(fontOffset),
        );
      } catch (error) {
        return;
      }
    }

    function notifyFontOffsetChanged() {
      if (window.opener) {
        window.opener.postMessage(
          {
            type: "electroboy-pane-font-offset",
            pane: fontPane,
            offset: fontOffset,
          },
          window.location.origin,
        );
      }
    }

    function applyFontSize() {
      fontSize = effectiveFontSize();
      document.documentElement.style.setProperty("--font-size", `${fontSize}px`);
      if (terminal) {
        terminal.options.fontSize = fontSize;
        window.requestAnimationFrame(fitTerminal);
      }
      paneFontControls.hidden = PANE_KIND === "artifact";
      paneFontLevel.textContent = `${fontSize}px`;
      paneFontLevel.title = fontOffset === 0
        ? "Global font size"
        : `Global ${fontOffset > 0 ? "+" : ""}${fontOffset}px`;
      decreasePaneFont.disabled = fontOffset <= MIN_FONT_OFFSET;
      resetPaneFont.disabled = fontOffset === 0;
      increasePaneFont.disabled = fontOffset >= MAX_FONT_OFFSET;
    }

    function changeFontSize(delta) {
      fontOffset = clampFontOffset(fontOffset + delta);
      saveFontOffset();
      applyFontSize();
      notifyFontOffsetChanged();
    }

    function resetFontSize() {
      fontOffset = 0;
      saveFontOffset();
      applyFontSize();
      notifyFontOffsetChanged();
    }

    function titleForPane(kind) {
      if (kind === "agent") return "Agent output";
      if (kind === "artifact") {
        if (artifactKind === "document" && artifactDocumentTitle) {
          return artifactDocumentTitle;
        }
        if (artifactKind === "route" && artifactRouteTitle) {
          return artifactRouteTitle;
        }
        if (artifactKind === "creative-corkboard") {
          return artifactCorkboardTitle || artifactFolderTitle || "Corkboard";
        }
        return "Artifact preview";
      }
      if (kind === "progress") return "Progress";
      if (kind === "scratch") return "Scratch pad";
      if (kind === "status") return "Project status";
      if (kind === "input") return "AI agent input";
      if (kind === "shell") return "Project shell";
      return "Pane";
    }

    function contextUrl(path) {
      const separator = path.includes("?") ? "&" : "?";
      return `${path}${separator}context_id=${encodeURIComponent(contextId)}`;
    }

    function renderSessionSwitcher() {
      sessionSwitcher.replaceChildren();
      if (agentSessions.length === 0) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "No streams";
        sessionSwitcher.append(option);
        sessionSwitcher.disabled = true;
        return;
      }
      for (const session of agentSessions) {
        const option = document.createElement("option");
        option.value = session.session_id;
        const status = session.status === "running" ? "running" : session.status || "done";
        option.textContent = `${session.kind || "agent"} · ${status}`;
        sessionSwitcher.append(option);
      }
      if (!agentSessions.some((session) => session.session_id === selectedSessionId)) {
        const selected = agentSessions.find((session) => session.selected) || agentSessions[0];
        selectedSessionId = selected ? selected.session_id : "";
      }
      sessionSwitcher.value = selectedSessionId;
      sessionSwitcher.disabled = false;
    }

    async function refreshSessions() {
      if (!contextId) {
        renderSessionSwitcher();
        return;
      }
      const response = await fetch(contextUrl("/api/project"), { cache: "no-store" });
      const payload = await response.json().catch(() => ({ error: "project load failed" }));
      if (!response.ok) {
        renderSessionSwitcher();
        return;
      }
      agentSessions = Array.isArray(payload.sessions) ? payload.sessions : [];
      selectedSessionId = payload.selected_session_id || selectedSessionId || "";
      renderSessionSwitcher();
    }

    async function selectAgentSession(sessionId) {
      if (!sessionId || sessionId === selectedSessionId) {
        return;
      }
      const response = await fetch(contextUrl("/api/sessions/select"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      const payload = await response.json().catch(() => ({ error: "session switch failed" }));
      if (!response.ok) {
        renderSessionSwitcher();
        return;
      }
      agentSessions = Array.isArray(payload.sessions) ? payload.sessions : agentSessions;
      selectedSessionId = payload.selected_session_id || sessionId;
      renderSessionSwitcher();
      if (PANE_KIND === "input") {
        agentInput.focus();
      }
      if (PANE_KIND === "agent") {
        connectAgentStream();
      }
    }

    function clampArtifactZoom(value) {
      if (!Number.isFinite(value)) {
        return 100;
      }
      const stepped = Math.round(value / ARTIFACT_ZOOM_STEP) * ARTIFACT_ZOOM_STEP;
      return Math.max(MIN_ARTIFACT_ZOOM, Math.min(MAX_ARTIFACT_ZOOM, stepped));
    }

    function applyArtifactZoom() {
      artifactZoomLevel.textContent = `${artifactZoom}%`;
      decreaseArtifactZoom.disabled = artifactZoom <= MIN_ARTIFACT_ZOOM;
      increaseArtifactZoom.disabled = artifactZoom >= MAX_ARTIFACT_ZOOM;
    }

    function changeArtifactZoom(delta) {
      artifactZoom = clampArtifactZoom(artifactZoom + delta);
      applyArtifactZoom();
      if (artifactEditing) {
        postArtifactEditorFontSize();
        return;
      }
      refreshArtifact();
    }

    function artifactEditorFontSize() {
      return Math.max(11, Math.min(28, Math.round(16 * (artifactZoom / 100))));
    }

    function postArtifactEditorFontSize() {
      if (!artifactEditing || !artifactFrame.contentWindow) {
        return;
      }
      artifactFrame.contentWindow.postMessage(
        {
          type: "electroboy-editor-font-size",
          font_size: artifactEditorFontSize(),
        },
        window.location.origin,
      );
    }

    function terminalOptions(disableStdin = true) {
      return {
        allowProposedApi: false,
        convertEol: true,
        cursorBlink: false,
        disableStdin,
        fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace',
        fontSize,
        scrollback: 10000,
        termName: "xterm-256color",
        theme: {
          background: "#10141f",
          foreground: "#e7edf7",
          cursor: "#e7edf7",
          selectionBackground: "#2b6173",
          black: "#151923",
          red: "#ff6b6b",
          green: "#51cf66",
          yellow: "#ffd43b",
          blue: "#74c0fc",
          magenta: "#da77f2",
          cyan: "#66d9e8",
          white: "#f1f3f5",
          brightBlack: "#5c677d",
          brightRed: "#ff8787",
          brightGreen: "#69db7c",
          brightYellow: "#ffe066",
          brightBlue: "#91caff",
          brightMagenta: "#e599f7",
          brightCyan: "#99e9f2",
          brightWhite: "#ffffff",
        },
      };
    }

    function reportPaneError(message) {
      if (terminal) {
        terminal.write(formatTerminalMessage(`${message}\r\n`, "error"));
        return;
      }
      window.alert(message);
    }

    function timestampForDownload() {
      return new Date().toISOString().replace(/[:.]/g, "-");
    }

    function exportSafeName(value, fallback = "export") {
      return String(value || fallback)
        .replace(/[^A-Za-z0-9._-]+/g, "-")
        .replace(/^-+|-+$/g, "")
        || fallback;
    }

    function documentExportFormats() {
      return [
        {
          value: "markdown",
          label: "Markdown",
          extension: "md",
          description: "Markdown",
          accept: {
            "text/markdown": [".md"],
            "text/plain": [".txt"],
          },
        },
        {
          value: "docx",
          label: "DOCX",
          extension: "docx",
          description: "Word document",
          accept: {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [
              ".docx",
            ],
          },
        },
        {
          value: "pdf",
          label: "PDF",
          extension: "pdf",
          description: "PDF",
          accept: {
            "application/pdf": [".pdf"],
          },
        },
      ];
    }

    function documentExportFormat(format) {
      return documentExportFormats().find((candidate) => candidate.value === format)
        || documentExportFormats()[0];
    }

    function documentExportPickerTypes(format = "markdown") {
      const selected = documentExportFormat(format);
      return [
        {
          description: selected.description,
          accept: selected.accept,
        },
      ];
    }

    function downloadBlob(fileName, blob) {
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
    }

    async function writeBlobWithPicker(
      blob,
      suggestedName,
      pickerTypes = documentExportPickerTypes("markdown"),
    ) {
      if (!window.showSaveFilePicker) {
        downloadBlob(suggestedName, blob);
        return;
      }
      try {
        const handle = await window.showSaveFilePicker({
          suggestedName,
          types: pickerTypes,
        });
        const writable = await handle.createWritable();
        await writable.write(blob);
        await writable.close();
      } catch (error) {
        if (error && error.name === "AbortError") {
          return;
        }
        reportPaneError(`export picker failed: ${error}`);
        downloadBlob(suggestedName, blob);
      }
    }

    async function exportBlob(url, suggestedName, format = "markdown") {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) {
        const message = await response.text();
        reportPaneError(message || "export failed");
        return;
      }
      const blob = await response.blob();
      await writeBlobWithPicker(
        blob,
        suggestedName,
        documentExportPickerTypes(format),
      );
    }

    async function exportMarkdown(url, suggestedName) {
      await exportBlob(url, suggestedName, "markdown");
    }

    function canExportPaneOutput() {
      return PANE_KIND === "agent"
        || PANE_KIND === "progress"
        || PANE_KIND === "artifact";
    }

    function artifactExportBaseName() {
      if (artifactKind === "document" && artifactDocumentPath) {
        return exportSafeName(artifactDocumentPath);
      }
      if (artifactKind === "route" && artifactRouteTitle) {
        return exportSafeName(artifactRouteTitle);
      }
      return exportSafeName(artifactKind || "document");
    }

    function paneExportFileName(format = "markdown") {
      if (PANE_KIND === "artifact") {
        const selected = documentExportFormat(format);
        return `${artifactExportBaseName()}.${selected.extension}`;
      }
      if (PANE_KIND === "progress") {
        return `progress-log-${timestampForDownload()}.md`;
      }
      return `agent-session-${timestampForDownload()}.md`;
    }

    function artifactDocumentExportUrl(format) {
      const parameters = new URLSearchParams();
      parameters.set("artifact", artifactKind);
      parameters.set("format", format);
      if (artifactKind === "document" && artifactDocumentPath) {
        parameters.set("path", artifactDocumentPath);
      }
      if (artifactKind === "route" && artifactRoutePath) {
        parameters.set("path", artifactRoutePath);
      }
      return contextUrl(`/api/documents/export?${parameters.toString()}`);
    }

    async function exportCurrentPaneOutput() {
      if (PANE_KIND === "artifact") {
        const format = exportPaneFormat.value || "markdown";
        await exportBlob(
          artifactDocumentExportUrl(format),
          paneExportFileName(format),
          format,
        );
        return;
      }
      if (PANE_KIND === "progress") {
        await exportMarkdown(
          contextUrl("/api/progress/export"),
          paneExportFileName(),
        );
        return;
      }
      await exportMarkdown(
        contextUrl(
          `/api/sessions/export?session_id=${encodeURIComponent(selectedSessionId)}`,
        ),
        paneExportFileName(),
      );
    }

    function showTerminal(disableStdin = true, onData = null) {
      terminalHost.hidden = false;
      terminal = new window.Terminal(terminalOptions(disableStdin));
      if (onData) {
        terminal.onData(onData);
      }
      if (window.FitAddon && window.FitAddon.FitAddon) {
        terminalFit = new window.FitAddon.FitAddon();
        terminal.loadAddon(terminalFit);
      }
      terminal.open(terminalHost);
      terminal.onResize(({ cols, rows }) => {
        if (PANE_KIND === "shell") {
          queueShellResize(cols, rows);
        } else if (PANE_KIND === "agent") {
          queueAgentResize(cols, rows);
        }
      });
      observeTerminalPaneResize();
      fitTerminal();
      window.addEventListener("resize", fitTerminal);
    }

    function fitTerminal() {
      if (!terminalFit) {
        return;
      }
      try {
        terminalFit.fit();
      } catch (error) {
        return;
      }
      if (PANE_KIND === "shell") {
        window.requestAnimationFrame(() => queueShellResize());
      } else if (PANE_KIND === "agent") {
        window.requestAnimationFrame(() => queueAgentResize());
      }
    }

    function observeTerminalPaneResize() {
      if (!window.ResizeObserver || terminalResizeObserver) {
        return;
      }
      terminalResizeObserver = new window.ResizeObserver(() => {
        window.requestAnimationFrame(fitTerminal);
      });
      terminalResizeObserver.observe(terminalHost);
    }

    async function sendShellInput(data) {
      if (!contextId || !data) {
        return;
      }
      await fetch(contextUrl("/api/shell/input"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data }),
      }).catch(() => {});
    }

    async function sendShellResize(columns = null, rows = null) {
      if (!contextId || !terminal) {
        return;
      }
      await fetch(contextUrl("/api/shell/resize"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          columns: Number(columns || terminal.cols || 120),
          rows: Number(rows || terminal.rows || 32),
        }),
      }).catch(() => {});
    }

    function agentResizePayload(columns = null, rows = null) {
      if (!contextId || !terminal || !selectedSessionId) {
        return null;
      }
      return {
        session_id: selectedSessionId,
        columns: Number(columns || terminal.cols || 120),
        rows: Number(rows || terminal.rows || 32),
      };
    }

    function queueAgentResize(columns = null, rows = null) {
      const payload = agentResizePayload(columns, rows);
      if (!payload) {
        return;
      }
      pendingTerminalResize = payload;
      window.clearTimeout(terminalResizeTimer);
      terminalResizeTimer = window.setTimeout(() => {
        const resize = pendingTerminalResize;
        pendingTerminalResize = null;
        sendAgentResize(resize);
      }, 120);
    }

    async function sendAgentResize(payload = null) {
      const resize = payload || agentResizePayload();
      if (!resize) {
        return;
      }
      await fetch(contextUrl("/api/sessions/resize"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(resize),
      }).catch(() => {});
    }

    function queueShellResize(columns = null, rows = null) {
      window.clearTimeout(terminalResizeTimer);
      terminalResizeTimer = window.setTimeout(
        () => sendShellResize(columns, rows),
        120,
      );
    }

    function formatTerminalMessage(text, type) {
      if (type === "error") return `\x1b[31m${text}\x1b[0m`;
      if (type === "system") return `\x1b[36m${text}\x1b[0m`;
      return text;
    }

    function connectAgentStream() {
      showTerminal();
      if (!contextId || !selectedSessionId) {
        terminal.write("\x1b[31mno selected stream\x1b[0m\r\n");
        return;
      }
      if (eventSource) {
        eventSource.close();
      }
      eventSource = new EventSource(
        contextUrl(
          `/api/sessions/events?session_id=${encodeURIComponent(selectedSessionId)}`,
        ),
      );
      eventSource.addEventListener("agent-event", (event) => {
        const payload = JSON.parse(event.data);
        if (payload.type === "output") {
          terminal.write(payload.terminal || payload.text || "");
        } else if (payload.type === "system" || payload.type === "error") {
          terminal.write(formatTerminalMessage(`${payload.text}\r\n`, payload.type));
        } else if (payload.type === "completed") {
          terminal.write(formatTerminalMessage(
            `\r\nprocess exited with code ${payload.returncode}\r\n`,
            "system",
          ));
        }
      });
      eventSource.onerror = () => {};
    }

    function connectProgressStream() {
      showTerminal();
      if (!contextId) {
        terminal.write("\x1b[31mno active context\x1b[0m\r\n");
        return;
      }
      eventSource = new EventSource(contextUrl("/api/progress/events"));
      eventSource.addEventListener("progress-event", (event) => {
        const payload = JSON.parse(event.data);
        terminal.clear();
        terminal.write(formatTerminalMessage(payload.text || "", payload.type));
        if (payload.running === false) {
          eventSource.close();
        }
      });
      eventSource.onerror = () => {};
    }

    function connectShellStream() {
      showTerminal(false, sendShellInput);
      if (!contextId) {
        terminal.write("\x1b[31mno active context\x1b[0m\r\n");
        return;
      }
      eventSource = new EventSource(contextUrl("/api/shell/events"));
      eventSource.addEventListener("agent-event", (event) => {
        const payload = JSON.parse(event.data);
        if (payload.type === "output") {
          terminal.write(payload.terminal || payload.text || "");
        } else if (payload.type === "system" || payload.type === "error") {
          terminal.write(formatTerminalMessage(`${payload.text}\r\n`, payload.type));
        } else if (payload.type === "completed") {
          terminal.write(formatTerminalMessage(
            `\r\nproject shell exited with code ${payload.returncode}\r\n`,
            "system",
          ));
        }
      });
      eventSource.onerror = () => {};
      window.requestAnimationFrame(sendShellResize);
    }

    function artifactUrl() {
      if (artifactKind === "requirements") {
        return `${contextUrl("/artifacts/requirements?embed=1")}&zoom=${artifactZoom}&version=${artifactVersion}`;
      }
      if (artifactKind === "document" && artifactDocumentPath) {
        const parameters = new URLSearchParams();
        parameters.set("path", artifactDocumentPath);
        parameters.set("title", artifactDocumentTitle || artifactDocumentPath);
        parameters.set("embed", "1");
        parameters.set("create", "1");
        parameters.set("zoom", String(artifactZoom));
        parameters.set("version", String(artifactVersion));
        return contextUrl(`/artifacts/document?${parameters.toString()}`);
      }
      if (artifactKind === "route" && artifactRoutePath) {
        const routeUrl = contextUrl(`${artifactRoutePath}?embed=1`);
        return `${routeUrl}&zoom=${artifactZoom}&version=${artifactVersion}`;
      }
      if (artifactKind === "creative-corkboard") {
        const corkboardPath = artifactCorkboardPath || artifactFolderPath;
        if (!corkboardPath) {
          return "";
        }
        const parameters = new URLSearchParams();
        parameters.set("path", corkboardPath);
        parameters.set(
          "title",
          artifactCorkboardTitle || artifactFolderTitle || corkboardPath,
        );
        parameters.set("embed", "1");
        parameters.set("version", String(artifactVersion));
        return contextUrl(`/artifacts/creative-corkboard?${parameters.toString()}`);
      }
      return "";
    }

    function artifactEditUrl() {
      if (artifactKind === "creative-corkboard") {
        return artifactUrl();
      }
      const parameters = new URLSearchParams();
      parameters.set("artifact", artifactKind);
      parameters.set("document_zoom", String(artifactZoom));
      parameters.set("font_size", String(artifactEditorFontSize()));
      if (artifactKind === "document" && artifactDocumentPath) {
        parameters.set("path", artifactDocumentPath);
        parameters.set("title", artifactDocumentTitle || artifactDocumentPath);
        parameters.set("create", "1");
      }
      if (artifactKind === "route" && artifactRoutePath) {
        parameters.set("path", artifactRoutePath);
        parameters.set("title", artifactRouteTitle || artifactRoutePath);
      }
      return contextUrl(`/artifacts/edit?${parameters.toString()}`);
    }

    function refreshArtifact() {
      artifactVersion += 1;
      artifactFrame.classList.add("loading");
      artifactFrame.src = artifactEditing ? artifactEditUrl() : artifactUrl();
    }

    function setArtifactEditMode(editing) {
      artifactEditing = Boolean(editing);
      previewArtifactButton.classList.toggle("active", !artifactEditing);
      editArtifactButton.classList.toggle("active", artifactEditing);
      refreshArtifact();
    }

    function artifactEventUrl() {
      if (artifactKind === "requirements") {
        return contextUrl("/api/artifacts/events?artifact=requirements");
      }
      const parameters = new URLSearchParams();
      if (artifactKind === "document" && artifactDocumentPath) {
        parameters.set("artifact", "document");
        parameters.set("path", artifactDocumentPath);
        return contextUrl(`/api/artifacts/events?${parameters.toString()}`);
      }
      if (artifactKind === "route" && artifactRoutePath) {
        parameters.set("artifact", "route");
        parameters.set("path", artifactRoutePath);
        return contextUrl(`/api/artifacts/events?${parameters.toString()}`);
      }
      return "";
    }

    function connectArtifactStream() {
      const isCorkboard = artifactKind === "creative-corkboard";
      artifactFrame.hidden = false;
      artifactZoomControls.hidden = isCorkboard;
      refreshArtifactButton.hidden = false;
      previewArtifactButton.hidden = isCorkboard;
      editArtifactButton.hidden = isCorkboard;
      exportPaneFormat.hidden = isCorkboard;
      exportPaneOutput.hidden = isCorkboard;
      previewArtifactButton.classList.toggle("active", !artifactEditing);
      editArtifactButton.classList.toggle("active", artifactEditing);
      applyArtifactZoom();
      refreshArtifact();
      if (!contextId) {
        return;
      }
      const eventUrl = artifactEventUrl();
      if (!eventUrl) {
        return;
      }
      artifactEventSource = new EventSource(eventUrl);
      artifactEventSource.addEventListener("artifact-event", refreshArtifact);
      artifactEventSource.onerror = () => {};
    }

    function showScratchPad() {
      scratchPad.hidden = false;
      const storageKey = scratchPadStorageKey();
      try {
        scratchPad.value = storageKey
          ? window.localStorage.getItem(storageKey) || ""
          : "";
      } catch (error) {
        scratchPad.value = "";
      }
      scratchPad.addEventListener("input", () => {
        const activeStorageKey = scratchPadStorageKey();
        if (!activeStorageKey) {
          return;
        }
        try {
          window.localStorage.setItem(activeStorageKey, scratchPad.value);
        } catch (error) {
          return;
        }
      });
      scratchPad.focus();
    }

    function scratchPadStorageKey() {
      if (!contextId) {
        return "";
      }
      return `${SCRATCH_PAD_STORAGE_KEY}.${contextId}`;
    }

    async function refreshStatus() {
      if (!contextId) {
        statusOutput.textContent = "no active project\n";
        return;
      }
      statusOutput.textContent = "refreshing status...\n";
      const response = await fetch(contextUrl("/api/project/status"), {
        cache: "no-store",
      });
      const payload = await response.json().catch(() => ({ error: "status failed" }));
      statusOutput.textContent = response.ok
        ? payload.output || "status: none\n"
        : `${payload.error || "status failed"}\n`;
    }

    function showStatus() {
      statusOutput.hidden = false;
      refreshStatus();
      statusTimer = window.setInterval(refreshStatus, 2500);
    }

    async function sendMessage() {
      if (slashCommandMode) {
        sendTerminalKey("enter");
        finishSlashCommandMode();
        return;
      }
      const message = agentInput.value;
      if (!message.trim()) {
        return;
      }
      agentInput.value = "";
      await fetch(contextUrl("/api/sessions/message"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
    }

    function queueTerminalInput(task) {
      const next = terminalInputQueue.catch(() => {}).then(task);
      terminalInputQueue = next.catch(() => {});
      return next;
    }

    function sendTerminalKey(key) {
      return queueTerminalInput(async () => {
        await fetch(contextUrl("/api/sessions/key"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key }),
        });
      });
    }

    function sendTerminalRaw(data) {
      if (!data) {
        return Promise.resolve();
      }
      return queueTerminalInput(async () => {
        await fetch(contextUrl("/api/sessions/raw"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ data }),
        });
      });
    }

    function printableInputEvent(event) {
      return (
        !event.altKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        event.key &&
        event.key.length === 1
      );
    }

    function slashCommandTerminalKeyForInputEvent(event) {
      if (event.altKey || event.ctrlKey || event.metaKey) {
        return "";
      }
      if (
        event.key === "Enter" ||
        event.code === "Enter" ||
        event.code === "NumpadEnter"
      ) {
        return "enter";
      }
      if (event.key === "Escape") return "escape";
      if (event.key === "ArrowUp") return "up";
      if (event.key === "ArrowDown") return "down";
      if (event.key === "ArrowLeft") return "left";
      if (event.key === "ArrowRight") return "right";
      if (event.key === "Backspace") return "backspace";
      if (event.key === "Delete") return "delete";
      if (event.key === "Tab") return "tab";
      return "";
    }

    function refreshSlashCommandModeAfterEdit() {
      window.setTimeout(() => {
        if (!agentInput.value.trimStart().startsWith("/")) {
          slashCommandMode = false;
        }
      }, 0);
    }

    function finishSlashCommandMode() {
      slashCommandMode = false;
      agentInput.value = "";
    }

    function handleSlashCommandInput(event) {
      if (
        !slashCommandMode &&
        printableInputEvent(event) &&
        event.key === "/" &&
        agentInput.value.trim().length === 0
      ) {
        slashCommandMode = true;
        sendTerminalRaw(event.key);
        return true;
      }
      if (!slashCommandMode) {
        return false;
      }
      const slashKey = slashCommandTerminalKeyForInputEvent(event);
      if (slashKey) {
        sendTerminalKey(slashKey);
        if (slashKey === "enter" || slashKey === "escape") {
          event.preventDefault();
          finishSlashCommandMode();
        } else if (slashKey === "backspace" || slashKey === "delete") {
          refreshSlashCommandModeAfterEdit();
        } else {
          event.preventDefault();
        }
        return true;
      }
      if (printableInputEvent(event)) {
        sendTerminalRaw(event.key);
        return true;
      }
      return false;
    }

    function terminalKeyForInputEvent(event) {
      if (
        !event.altKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.shiftKey &&
        event.key === "Escape"
      ) {
        return "escape";
      }
      if (agentInput.value.length > 0) {
        return "";
      }
      if (
        event.ctrlKey &&
        !event.altKey &&
        !event.metaKey &&
        !event.shiftKey &&
        /^[0-9]$/.test(event.key)
      ) {
        return event.key;
      }
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
        return "";
      }
      if (
        event.key === "Enter" ||
        event.code === "Enter" ||
        event.code === "NumpadEnter"
      ) {
        return "enter";
      }
      if (event.key === "ArrowUp") return "up";
      if (event.key === "ArrowDown") return "down";
      if (event.key === "ArrowLeft") return "left";
      if (event.key === "ArrowRight") return "right";
      if (event.key === "Tab") return "tab";
      return "";
    }

    async function interruptAgentSession() {
      await fetch(contextUrl("/api/sessions/interrupt"), { method: "POST" });
    }

    function showInput() {
      inputLayout.hidden = false;
      refreshSessions();
      applyFontSize();
      agentInput.focus();
    }

    dockPane.addEventListener("click", () => {
      if (window.opener) {
        window.opener.postMessage(
          { type: "electroboy-pane-restore", pane: PANE_KIND },
          window.location.origin,
        );
      }
      window.close();
    });
    decreaseArtifactZoom.addEventListener(
      "click",
      () => changeArtifactZoom(-ARTIFACT_ZOOM_STEP),
    );
    increaseArtifactZoom.addEventListener(
      "click",
      () => changeArtifactZoom(ARTIFACT_ZOOM_STEP),
    );
    refreshArtifactButton.addEventListener("click", refreshArtifact);
    artifactFrame.addEventListener("load", () => {
      artifactFrame.classList.remove("loading");
      postArtifactEditorFontSize();
    });
    previewArtifactButton.addEventListener("click", () => setArtifactEditMode(false));
    editArtifactButton.addEventListener("click", () => setArtifactEditMode(true));
    exportPaneOutput.addEventListener("click", () => {
      exportCurrentPaneOutput().catch((error) => {
        if (terminal) {
          terminal.write(formatTerminalMessage(`export failed: ${error}\r\n`, "error"));
        }
      });
    });
    decreasePaneFont.addEventListener("click", () => changeFontSize(-1));
    resetPaneFont.addEventListener("click", resetFontSize);
    increasePaneFont.addEventListener("click", () => changeFontSize(1));
    window.addEventListener("storage", (event) => {
      if (event.key === TERMINAL_FONT_STORAGE_KEY) {
        const nextBase = Number(event.newValue || "");
        if (Number.isFinite(nextBase) && nextBase > 0) {
          baseFontSize = clampFontSize(nextBase);
          applyFontSize();
        }
        return;
      }
      if (event.key !== PANE_FONT_OFFSET_STORAGE_PREFIX + fontPane) {
        return;
      }
      fontOffset = localStoredFontOffset();
      applyFontSize();
    });
    window.addEventListener("message", (event) => {
      if (event.origin !== window.location.origin) {
        return;
      }
      const data = event.data || {};
      if (data.type === "electroboy-artifact-saved") {
        artifactVersion += 1;
        if (!artifactEditing) {
          refreshArtifact();
        }
      }
    });
    sessionSwitcher.addEventListener("change", () => {
      selectAgentSession(sessionSwitcher.value);
    });
    sendAgentInput.addEventListener("click", sendMessage);
    interruptAgent.addEventListener("click", interruptAgentSession);
    agentInput.addEventListener("keydown", (event) => {
      if (handleSlashCommandInput(event)) {
        return;
      }
      const terminalKey = terminalKeyForInputEvent(event);
      if (terminalKey) {
        event.preventDefault();
        sendTerminalKey(terminalKey);
        return;
      }
      const isEnter =
        event.key === "Enter" ||
        event.code === "Enter" ||
        event.code === "NumpadEnter";
      if (isEnter && event.shiftKey) {
        event.preventDefault();
        if (agentInput.value.trim()) {
          sendMessage();
        } else {
          sendTerminalKey("enter");
        }
      }
    });

    paneTitle.textContent = titleForPane(PANE_KIND);
    exportPaneFormat.hidden = PANE_KIND !== "artifact";
    exportPaneOutput.hidden = !canExportPaneOutput();
    if (PANE_KIND === "agent") connectAgentStream();
    else if (PANE_KIND === "progress") connectProgressStream();
    else if (PANE_KIND === "artifact") connectArtifactStream();
    else if (PANE_KIND === "scratch") showScratchPad();
    else if (PANE_KIND === "status") showStatus();
    else if (PANE_KIND === "input") showInput();
    else if (PANE_KIND === "shell") connectShellStream();

    window.addEventListener("beforeunload", () => {
      if (eventSource) eventSource.close();
      if (artifactEventSource) artifactEventSource.close();
      if (statusTimer) window.clearInterval(statusTimer);
    });
  </script>
</body>
</html>
"""


def pane_window_html(kind: str) -> str:
    return PANE_WINDOW_HTML.replace("__PANE_KIND__", json.dumps(kind))


FILE_BROWSER_WINDOW_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ElectroBoy File Browser</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #eef3f7;
      --panel: #ffffff;
      --ink: #17212f;
      --muted: #6c7788;
      --border: #cfd9e3;
      --active: #007f8a;
      --active-soft: #e7f7f8;
      --folder: #d48a1f;
      --file: #5f6f85;
      --markdown: #1c7ed6;
      --git: #d9480f;
      font-family:
        Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      font-size: 14px;
    }

    * {
      box-sizing: border-box;
    }

    body {
      display: grid;
      grid-template-rows: auto auto auto minmax(0, 1fr) auto;
      gap: 10px;
      height: 100vh;
      margin: 0;
      overflow: hidden;
      background: var(--bg);
      color: var(--ink);
      padding: 14px;
    }

    button,
    input {
      font: inherit;
    }

    .path-form {
      display: grid;
      grid-template-columns: minmax(260px, 1fr) auto auto;
      gap: 8px;
      align-items: center;
    }

    .path-input,
    .search-input {
      width: 100%;
      height: 38px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: #ffffff;
      color: var(--ink);
      padding: 0 10px;
    }

    .browser-button {
      height: 38px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: #ffffff;
      color: var(--ink);
      cursor: pointer;
      font-weight: 650;
      padding: 0 12px;
      white-space: nowrap;
    }

    .browser-button.primary {
      border-color: var(--active);
      background: var(--active);
      color: #ffffff;
    }

    .browser-button:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }

    .filter-row {
      display: grid;
      grid-template-columns: minmax(220px, 1fr) auto;
      gap: 8px;
      align-items: center;
    }

    .hidden-toggle {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      font-weight: 650;
      white-space: nowrap;
    }

    .breadcrumbs {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      min-height: 28px;
      align-items: center;
    }

    .breadcrumb-button {
      border: 0;
      border-radius: 4px;
      background: transparent;
      color: var(--active);
      cursor: pointer;
      padding: 3px 5px;
      font: inherit;
      font-weight: 650;
    }

    .breadcrumb-separator {
      color: var(--muted);
    }

    .tree-panel {
      min-height: 0;
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      padding: 6px;
    }

    .file-tree {
      outline: none;
    }

    .file-tree-row {
      display: grid;
      grid-template-columns: 24px 22px minmax(0, 1fr);
      gap: 6px;
      align-items: center;
      min-height: 30px;
      border-radius: 5px;
      color: var(--ink);
      cursor: default;
      padding: 2px 8px 2px 0;
      user-select: none;
    }

    .file-tree-row:hover {
      background: #f4f8fb;
    }

    .file-tree-row.selected {
      background: var(--active-soft);
      box-shadow: inset 3px 0 0 var(--active);
    }

    .file-tree-name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .file-disclosure {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      border: 0;
      border-radius: 4px;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      padding: 0;
    }

    .file-disclosure:hover {
      background: #e8eef5;
      color: var(--ink);
    }

    .file-disclosure.placeholder {
      cursor: default;
    }

    .file-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: var(--file);
    }

    .file-icon.folder {
      color: var(--folder);
    }

    .file-icon.markdown {
      color: var(--markdown);
    }

    .file-icon.git {
      color: var(--git);
    }

    .file-icon svg,
    .file-disclosure svg {
      width: 16px;
      height: 16px;
      stroke: currentColor;
    }

    .status-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(180px, 0.55fr) auto auto;
      gap: 8px;
      align-items: center;
      color: var(--muted);
    }

    .new-document-input[hidden] {
      display: none;
    }

    .selected-path {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  </style>
</head>
<body>
  <form id="pathForm" class="path-form">
    <input
      id="pathInput"
      class="path-input"
      type="text"
      autocomplete="off"
      aria-label="Path"
    >
    <button id="goPath" class="browser-button" type="submit">Go</button>
    <button id="refreshPath" class="browser-button" type="button">Refresh</button>
  </form>
  <div class="filter-row">
    <input
      id="searchInput"
      class="search-input"
      type="search"
      autocomplete="off"
      placeholder="Search visible files and folders"
      aria-label="Search visible files and folders"
    >
    <label class="hidden-toggle">
      <input id="showHidden" type="checkbox">
      Show hidden
    </label>
  </div>
  <div id="breadcrumbs" class="breadcrumbs" aria-label="Breadcrumbs"></div>
  <section class="tree-panel" aria-label="File tree">
    <div id="fileTree" class="file-tree" role="tree" tabindex="0"></div>
  </section>
  <div class="status-row">
    <div id="selectedPath" class="selected-path">Selected: none</div>
    <input
      id="newDocumentName"
      class="path-input new-document-input"
      type="text"
      autocomplete="off"
      placeholder="new-document.md"
      aria-label="New document file name"
      hidden
    >
    <button id="selectPath" class="browser-button primary" type="button" disabled>
      Activate
    </button>
    <button id="cancelBrowser" class="browser-button" type="button">Cancel</button>
  </div>

  <script>
    const INITIAL_PATH = __INITIAL_PATH__;
    const SELECT_MODE = __SELECT_MODE__;
    const PROJECT_ACTION =
      new URLSearchParams(window.location.search).get("project_action") || "";
    const pathForm = document.getElementById("pathForm");
    const pathInput = document.getElementById("pathInput");
    const refreshPath = document.getElementById("refreshPath");
    const searchInput = document.getElementById("searchInput");
    const showHidden = document.getElementById("showHidden");
    const breadcrumbs = document.getElementById("breadcrumbs");
    const fileTree = document.getElementById("fileTree");
    const selectedPathLabel = document.getElementById("selectedPath");
    const newDocumentName = document.getElementById("newDocumentName");
    const selectPath = document.getElementById("selectPath");
    const cancelBrowser = document.getElementById("cancelBrowser");
    selectPath.textContent =
      SELECT_MODE === "link"
        ? "Insert selected file"
      : SELECT_MODE === "document-new"
        ? "Create or open document"
      : SELECT_MODE === "project-new"
        ? "Create or activate project"
      : SELECT_MODE === "document"
        ? "Open selected document"
      : "Activate";
    newDocumentName.hidden =
      SELECT_MODE !== "document-new" && SELECT_MODE !== "project-new";
    newDocumentName.placeholder =
      SELECT_MODE === "project-new" ? "optional-new-folder" : "new-document.md";
    newDocumentName.setAttribute(
      "aria-label",
      SELECT_MODE === "project-new"
        ? "Optional new project folder name"
        : "New document file name",
    );

    let rootPayload = null;
    let currentPath = "";
    let selectedPath = "";
    let selectedType = "";
    let expandedPaths = new Set();
    let childCache = new Map();
    let flatRows = [];
    let selectedIndex = -1;

    function iconSvg(name) {
      const icons = {
        "chevron-right": '<polyline points="9 18 15 12 9 6"></polyline>',
        "chevron-down": '<polyline points="6 9 12 15 18 9"></polyline>',
        folder: '<path d="M3 7h7l2 2h9v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>',
        "folder-open": '<path d="M3 7h7l2 2h9l-2 9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><path d="M3 7v11"></path>',
        file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path>',
        markdown: '<rect x="3" y="5" width="18" height="14" rx="2"></rect><path d="M7 15V9l3 3 3-3v6"></path><path d="M17 9v6"></path><path d="M15 13l2 2 2-2"></path>',
        git: '<path d="M12 2 2 12l10 10 10-10z"></path><circle cx="9" cy="12" r="1.5"></circle><circle cx="15" cy="9" r="1.5"></circle><circle cx="15" cy="15" r="1.5"></circle><path d="M10.5 11 13.5 9.5"></path><path d="M10.5 13 13.5 14.5"></path>',
      };
      return `<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.file}</svg>`;
    }

    function baseName(path) {
      const trimmed = String(path || "").replace(/\/+$/, "");
      if (!trimmed || trimmed === "/") {
        return trimmed || "/";
      }
      return trimmed.split("/").pop() || trimmed;
    }

    function iconName(entry, expanded) {
      if ((entry.type || "directory") === "directory") {
        if (entry.name === ".git") {
          return "git";
        }
        return expanded ? "folder-open" : "folder";
      }
      if (/\.md$/i.test(entry.name || entry.path || "")) {
        return "markdown";
      }
      return "file";
    }

    function iconClass(entry) {
      if ((entry.type || "directory") === "directory") {
        return entry.name === ".git" ? "git" : "folder";
      }
      return /\.md$/i.test(entry.name || entry.path || "") ? "markdown" : "file";
    }

    function browseUrl(path) {
      const parameters = new URLSearchParams();
      parameters.set("path", path || ".");
      parameters.set(
        "mode",
        SELECT_MODE === "document" || SELECT_MODE === "document-new"
          ? "markdown"
          : "file",
      );
      parameters.set("hidden", showHidden.checked ? "1" : "0");
      return `/api/files/browse?${parameters.toString()}`;
    }

    async function fetchDirectory(path) {
      const response = await fetch(browseUrl(path), { cache: "no-store" });
      const payload = await response.json().catch(() => ({ error: "browse failed" }));
      if (!response.ok) {
        throw new Error(payload.error || "browse failed");
      }
      return payload;
    }

    async function navigateTo(path) {
      selectedPathLabel.textContent = "Loading...";
      selectPath.disabled = true;
      try {
        const payload = await fetchDirectory(path);
        rootPayload = payload;
        currentPath = payload.path;
        selectedPath = payload.path;
        selectedType = "directory";
        pathInput.value = payload.path;
        expandedPaths.add(payload.path);
        childCache.set(payload.path, payload.entries || []);
        render();
        updateSelectedPath();
      } catch (error) {
        selectedPathLabel.textContent = error.message || String(error);
      }
    }

    async function toggleDirectory(entry) {
      if ((entry.type || "directory") !== "directory") {
        return;
      }
      if (expandedPaths.has(entry.path)) {
        expandedPaths.delete(entry.path);
        render();
        return;
      }
      expandedPaths.add(entry.path);
      if (!childCache.has(entry.path)) {
        try {
          const payload = await fetchDirectory(entry.path);
          childCache.set(entry.path, payload.entries || []);
        } catch (error) {
          selectedPathLabel.textContent = error.message || String(error);
          expandedPaths.delete(entry.path);
        }
      }
      render();
    }

    function matchesFilter(entry) {
      const filter = searchInput.value.trim().toLowerCase();
      if (!filter) {
        return true;
      }
      return (
        String(entry.name || "").toLowerCase().includes(filter) ||
        String(entry.path || "").toLowerCase().includes(filter)
      );
    }

    function shouldShow(entry) {
      if (matchesFilter(entry)) {
        return true;
      }
      if ((entry.type || "directory") !== "directory") {
        return false;
      }
      return (childCache.get(entry.path) || []).some(shouldShow);
    }

    function renderBreadcrumbs() {
      breadcrumbs.replaceChildren();
      if (!currentPath) {
        return;
      }
      const parts = currentPath.split("/").filter(Boolean);
      let path = currentPath.startsWith("/") ? "/" : "";
      const rootButton = breadcrumbButton(path || parts[0] || currentPath, path || parts[0]);
      breadcrumbs.append(rootButton);
      const start = currentPath.startsWith("/") ? 0 : 1;
      for (let index = start; index < parts.length; index += 1) {
        const separator = document.createElement("span");
        separator.className = "breadcrumb-separator";
        separator.textContent = "/";
        breadcrumbs.append(separator);
        path = path === "/" ? `/${parts[index]}` : `${path}/${parts[index]}`;
        breadcrumbs.append(breadcrumbButton(parts[index], path));
      }
    }

    function breadcrumbButton(label, path) {
      const button = document.createElement("button");
      button.className = "breadcrumb-button";
      button.type = "button";
      button.textContent = label || "/";
      button.title = path;
      button.addEventListener("click", () => navigateTo(path));
      return button;
    }

    function render() {
      fileTree.replaceChildren();
      flatRows = [];
      selectedIndex = -1;
      renderBreadcrumbs();
      if (!rootPayload) {
        return;
      }
      const rootEntry = {
        name: baseName(rootPayload.path),
        path: rootPayload.path,
        type: "directory",
      };
      appendEntry(fileTree, rootEntry, 0, true);
      updateSelectedPath();
    }

    function appendEntry(container, entry, depth, root = false) {
      if (!root && !shouldShow(entry)) {
        return;
      }
      const type = entry.type || "directory";
      const expanded = root || expandedPaths.has(entry.path);
      const row = document.createElement("div");
      row.className = "file-tree-row";
      row.setAttribute("role", "treeitem");
      row.tabIndex = -1;
      row.title = entry.path;
      row.dataset.path = entry.path;
      row.style.paddingLeft = `${depth * 18}px`;
      if (entry.path === selectedPath) {
        row.classList.add("selected");
        selectedIndex = flatRows.length;
      }

      const disclosure = document.createElement("button");
      disclosure.className = "file-disclosure";
      disclosure.type = "button";
      disclosure.tabIndex = -1;
      if (type === "directory") {
        disclosure.title = expanded ? "Collapse directory" : "Expand directory";
        disclosure.innerHTML = iconSvg(expanded ? "chevron-down" : "chevron-right");
        disclosure.addEventListener("click", (event) => {
          event.stopPropagation();
          toggleDirectory(entry);
        });
      } else {
        disclosure.classList.add("placeholder");
        disclosure.disabled = true;
      }

      const icon = document.createElement("span");
      icon.className = `file-icon ${iconClass(entry)}`;
      icon.innerHTML = iconSvg(iconName(entry, expanded));

      const name = document.createElement("span");
      name.className = "file-tree-name";
      name.textContent = entry.name || entry.path;

      row.append(disclosure, icon, name);
      row.addEventListener("click", () => selectEntry(entry));
      row.addEventListener("dblclick", () => {
        if (type === "directory") {
          navigateTo(entry.path);
        } else if (
          SELECT_MODE === "link" ||
          SELECT_MODE === "document" ||
          SELECT_MODE === "document-new"
        ) {
          selectCurrentPath();
        }
      });
      container.append(row);
      flatRows.push(entry);

      if (type !== "directory" || !expanded) {
        return;
      }
      for (const child of childCache.get(entry.path) || []) {
        appendEntry(container, child, depth + 1);
      }
    }

    function selectEntry(entry, options = {}) {
      selectedPath = entry.path;
      selectedType = entry.type || "directory";
      pathInput.value = entry.path;
      updateSelectedPath();
      if (options.render !== false) {
        render();
      }
    }

    function updateSelectedPath() {
      if (!selectedPath) {
        selectedPathLabel.textContent = "Selected: none";
        selectPath.disabled = true;
        return;
      }
      selectedPathLabel.textContent = `Selected: ${selectedPath}`;
      selectPath.disabled = !canSelectCurrentPath();
    }

    function canSelectCurrentPath() {
      if (!selectedPath) {
        return false;
      }
      if (SELECT_MODE === "link") {
        return selectedType === "file";
      }
      if (SELECT_MODE === "document") {
        return selectedType === "file" && /\.md$/i.test(selectedPath);
      }
      if (SELECT_MODE === "document-new") {
        if (selectedType === "file") {
          return /\.md$/i.test(selectedPath);
        }
        return selectedType === "directory" && Boolean(documentNewTargetPath());
      }
      if (SELECT_MODE === "project-new") {
        return selectedType === "directory";
      }
      return selectedType === "directory";
    }

    function focusSelectedRow() {
      const row = fileTree.querySelector(`[data-path="${CSS.escape(selectedPath)}"]`);
      if (row) {
        row.focus();
        row.scrollIntoView({ block: "nearest" });
      }
    }

    function moveSelection(delta) {
      if (!flatRows.length) {
        return;
      }
      const nextIndex = Math.max(
        0,
        Math.min(flatRows.length - 1, selectedIndex + delta),
      );
      selectEntry(flatRows[nextIndex]);
      focusSelectedRow();
    }

    async function expandSelected() {
      const entry = flatRows[selectedIndex];
      if (!entry || (entry.type || "directory") !== "directory") {
        return;
      }
      if (!expandedPaths.has(entry.path)) {
        await toggleDirectory(entry);
      }
      focusSelectedRow();
    }

    function collapseSelected() {
      const entry = flatRows[selectedIndex];
      if (!entry || (entry.type || "directory") !== "directory") {
        return;
      }
      if (expandedPaths.has(entry.path) && entry.path !== currentPath) {
        expandedPaths.delete(entry.path);
        render();
        focusSelectedRow();
        return;
      }
      const parent = flatRows
        .slice(0, selectedIndex)
        .reverse()
        .find((candidate) => entry.path.startsWith(`${candidate.path}/`));
      if (parent) {
        selectEntry(parent);
        focusSelectedRow();
      }
    }

    function documentNewTargetPath() {
      if (SELECT_MODE !== "document-new" || selectedType !== "directory") {
        return "";
      }
      const raw = newDocumentName.value.trim().replace(/\\+/g, "/");
      if (!raw) {
        return "";
      }
      const path = raw.toLowerCase().endsWith(".md") ? raw : `${raw}.md`;
      if (path.startsWith("/")) {
        return path;
      }
      return `${selectedPath.replace(/\/+$/, "")}/${path}`;
    }

    function projectNewTargetPath() {
      if (SELECT_MODE !== "project-new" || selectedType !== "directory") {
        return "";
      }
      const raw = newDocumentName.value.trim().replace(/\\+/g, "/");
      if (!raw) {
        return selectedPath;
      }
      if (raw.startsWith("/")) {
        return raw;
      }
      return `${selectedPath.replace(/\/+$/, "")}/${raw}`;
    }

    function selectCurrentPath() {
      if (!canSelectCurrentPath()) {
        selectedPathLabel.textContent =
          SELECT_MODE === "link"
            ? "Select a file first."
          : SELECT_MODE === "document-new"
            ? "Select a Markdown file or choose a directory and name."
          : SELECT_MODE === "project-new"
            ? "Select a project directory or enter a new folder name."
          : SELECT_MODE === "document"
            ? "Select a Markdown file first."
            : "Select a directory first.";
        return;
      }
      const outputPath =
        SELECT_MODE === "document-new" && selectedType === "directory"
          ? documentNewTargetPath()
        : SELECT_MODE === "project-new" && selectedType === "directory"
          ? projectNewTargetPath()
          : selectedPath;
      if (window.opener) {
        window.opener.postMessage(
          {
            type: "electroboy-file-browser-select",
            path: outputPath,
            mode: SELECT_MODE,
            project_action: PROJECT_ACTION,
          },
          window.location.origin,
        );
      }
      window.close();
    }

    pathForm.addEventListener("submit", (event) => {
      event.preventDefault();
      navigateTo(pathInput.value || ".");
    });
    refreshPath.addEventListener("click", () => {
      childCache.clear();
      navigateTo(currentPath || pathInput.value || ".");
    });
    searchInput.addEventListener("input", render);
    newDocumentName.addEventListener("input", updateSelectedPath);
    showHidden.addEventListener("change", () => {
      childCache.clear();
      navigateTo(currentPath || pathInput.value || ".");
    });
    selectPath.addEventListener("click", selectCurrentPath);
    cancelBrowser.addEventListener("click", () => window.close());
    fileTree.addEventListener("keydown", async (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        moveSelection(1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        moveSelection(-1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        await expandSelected();
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        collapseSelected();
      } else if (event.key === "Enter" && event.ctrlKey) {
        event.preventDefault();
        selectCurrentPath();
      } else if (event.key === "Enter") {
        event.preventDefault();
        const entry = flatRows[selectedIndex];
        if (entry && (entry.type || "directory") === "directory") {
          navigateTo(entry.path);
        }
      } else if (event.key === "Escape") {
        event.preventDefault();
        window.close();
      }
    });

    navigateTo(INITIAL_PATH || ".");
  </script>
</body>
</html>
"""


def file_browser_window_html(initial_path: str, mode: str = "project") -> str:
    select_mode = (
        mode
        if mode in {"link", "document", "document-new", "project-new"}
        else "project"
    )
    return (
        FILE_BROWSER_WINDOW_HTML.replace(
            "__INITIAL_PATH__",
            json.dumps(initial_path),
        )
        .replace("__SELECT_MODE__", json.dumps(select_mode))
    )


@dataclass
class BrowserContext:
    context_id: str
    activation_root: Path | None = None
    project_mode: str = "none"
    active_project_root: Path | None = None
    active_repository_name: str | None = None
    registered_repositories: list[dict[str, object]] = field(default_factory=list)
    requirements_session: AgentSession | None = None
    design_session: AgentSession | None = None
    design_review_session: AgentSession | None = None
    documentation_sessions: dict[str, AgentSession] = field(default_factory=dict)
    creative_session: AgentSession | None = None
    ad_hoc_session: AgentSession | None = None
    project_shell_session: AgentSession | None = None
    stage_sessions: dict[str, AgentSession] = field(default_factory=dict)
    selected_session_id: str | None = None
    workflow_stage: str | None = None
    requirements_started: bool = False
    design_started: bool = False
    design_review_started: bool = False
    design_review_interactive: bool = False
    stage_started: set[str] = field(default_factory=set)


@dataclass
class ServiceState:
    root: Path
    lock: threading.Lock = field(default_factory=threading.Lock)
    contexts: dict[str, BrowserContext] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root = self.root.resolve()

    def create_context(self) -> dict[str, object]:
        context = BrowserContext(context_id=uuid4().hex)
        with self.lock:
            self.contexts[context.context_id] = context
        return {
            **project_payload(self.root, context),
            "status": "created",
        }

    def project_payload(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            active_project_root = context.active_project_root
        return project_payload(self.root, context, active_project_root)

    def project_mode(self, context_id: str) -> str:
        with self.lock:
            context = self._context_locked(context_id)
            return context.project_mode

    def workflow_payload(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            active_project_root = context.active_project_root
        return workflow_payload(active_project_root)

    def project_status_payload(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            command_root = self._command_root_locked(context)
        if command_root is None:
            raise StateError("activate a project first")
        output, ok = _status_snapshot(command_root)
        return {
            "ok": ok,
            "output": output,
        }

    def create_feature_collection(
        self,
        context_id: str,
        name: str,
    ) -> dict[str, object]:
        collection_name = name.strip()
        if not collection_name:
            raise StateError("feature collection name is required")
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise StateError("activate a project first")
            self._require_no_active_agent_locked(context)
        registry = _load_work_item_registry(project_root)
        collection = _upsert_feature_collection(registry, collection_name)
        registry["active_collection_id"] = collection["id"]
        _save_work_item_registry(project_root, registry)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "created collection",
            "label": collection["name"],
        }

    def switch_feature_collection(
        self,
        context_id: str,
        collection_id: str,
    ) -> dict[str, object]:
        collection_id = collection_id.strip()
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise StateError("activate a project first")
            self._require_no_active_agent_locked(context)
        registry = _load_work_item_registry(project_root)
        collection = _feature_collection_by_id(registry, collection_id)
        if collection is None:
            raise StateError("unknown feature collection")
        registry["active_collection_id"] = collection["id"]
        _save_work_item_registry(project_root, registry)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "switched collection",
            "label": collection["name"],
        }

    def start_feature_work_item(
        self,
        context_id: str,
        *,
        title: str,
        feature_name: str | None = None,
        collection_id: str | None = None,
        parent_slug: str | None = None,
        branch: bool = False,
        stash_subrepo_changes: bool = False,
    ) -> dict[str, object]:
        title = title.strip()
        if not title:
            raise AgentSessionError("feature title is required")
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
        terminated_agent = self._terminate_workflow_sessions(context_id)
        output = _run_feature_start_context(
            project_root,
            title=title,
            feature_name=feature_name,
            amend=True,
            branch=branch,
            stash_subrepo_changes=stash_subrepo_changes,
        )
        registry = _load_work_item_registry(project_root)
        feature_record = _current_feature_record(project_root)
        if feature_record is not None:
            effective_collection_id = (
                collection_id if collection_id or parent_slug else "default"
            )
            collection = _ensure_collection_for_feature(
                registry,
                effective_collection_id,
                parent_slug=parent_slug,
            )
            _upsert_feature_record(
                registry,
                feature_record,
                collection_id=str(collection["id"]),
                parent_slug=parent_slug,
            )
            registry["active_collection_id"] = collection["id"]
            registry["active_feature_slug"] = feature_record.get("slug")
            registry["active_bug_slug"] = None
            _save_work_item_registry(project_root, registry)
        with self.lock:
            context = self._context_locked(context_id)
            context.workflow_stage = _active_workflow_stage(project_root)
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "started feature",
            "label": _feature_record_label(feature_record) if feature_record else title,
            "output": output,
            "terminated_agent": terminated_agent,
        }

    def switch_feature_work_item(
        self,
        context_id: str,
        slug: str,
    ) -> dict[str, object]:
        slug = slug.strip()
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
        registry = _load_work_item_registry(project_root)
        feature = _feature_by_slug(registry, slug)
        if feature is None:
            raise AgentSessionError("unknown feature")
        terminated_agent = self._terminate_workflow_sessions(context_id)
        output = _run_feature_start_context(
            project_root,
            title=str(feature.get("input") or feature.get("title") or slug),
            feature_name=str(feature.get("name") or slug),
            amend=True,
            branch=bool(feature.get("branch")),
            branch_name=(
                str(feature.get("branch"))
                if isinstance(feature.get("branch"), str)
                and str(feature.get("branch")).strip()
                else None
            ),
        )
        feature_record = _current_feature_record(project_root)
        if feature_record is not None:
            _upsert_feature_record(
                registry,
                feature_record,
                collection_id=str(feature.get("collection_id") or ""),
                parent_slug=(
                    str(feature.get("parent_slug"))
                    if feature.get("parent_slug")
                    else None
                ),
            )
        registry["active_feature_slug"] = slug
        registry["active_bug_slug"] = None
        if feature.get("collection_id"):
            registry["active_collection_id"] = feature.get("collection_id")
        _save_work_item_registry(project_root, registry)
        with self.lock:
            context = self._context_locked(context_id)
            context.workflow_stage = _active_workflow_stage(project_root)
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "switched feature",
            "label": _feature_record_label(feature),
            "output": output,
            "terminated_agent": terminated_agent,
        }

    def start_bug_work_item(
        self,
        context_id: str,
        *,
        issue_reference: str,
        branch: bool = False,
        stash_subrepo_changes: bool = False,
    ) -> dict[str, object]:
        issue_reference = issue_reference.strip()
        if not issue_reference:
            raise AgentSessionError("bug issue reference is required")
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
        terminated_agent = self._terminate_workflow_sessions(context_id)
        output = _run_bug_start_context(
            project_root,
            issue_reference=issue_reference,
            branch=branch,
            stash_subrepo_changes=stash_subrepo_changes,
        )
        registry = _load_work_item_registry(project_root)
        bug_record = _current_bug_record(project_root)
        if bug_record is not None:
            _upsert_bug_record(registry, bug_record)
            registry["active_bug_slug"] = bug_record.get("slug")
            registry["active_feature_slug"] = None
            _save_work_item_registry(project_root, registry)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "started bug resolution",
            "label": _bug_record_label(bug_record) if bug_record else issue_reference,
            "output": output,
            "terminated_agent": terminated_agent,
        }

    def switch_bug_work_item(
        self,
        context_id: str,
        slug: str,
    ) -> dict[str, object]:
        slug = slug.strip()
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
        registry = _load_work_item_registry(project_root)
        bug = _bug_by_slug(registry, slug)
        if bug is None:
            raise AgentSessionError("unknown bug")
        terminated_agent = self._terminate_workflow_sessions(context_id)
        _write_current_bug_record(project_root, bug)
        registry["active_bug_slug"] = slug
        registry["active_feature_slug"] = None
        _save_work_item_registry(project_root, registry)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "switched bug resolution",
            "label": _bug_record_label(bug),
            "terminated_agent": terminated_agent,
        }

    def select_workflow_stage(
        self,
        context_id: str,
        stage: str,
    ) -> dict[str, object]:
        stage = stage.strip()
        if stage in APPROVAL_WORKFLOW_STAGES:
            raise StateError(f"approval stage is not directly selectable: {stage}")
        if stage == "project" or stage not in WORKFLOW_STAGES:
            raise StateError(f"unknown workflow stage: {stage}")
        target_stage = WORKFLOW_STAGE_RESET_TARGETS.get(stage)
        if target_stage is None:
            raise StateError(f"stage cannot be set directly: {stage}")
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise StateError("activate a project first")
            previous_stage = context.workflow_stage
            sessions = (
                self._context_sessions_locked(context)
                if previous_stage != stage
                else []
            )
        terminated_agent = False
        if sessions:
            terminated_agent = self._terminate_sessions(sessions)
        reset_decision = None
        reset_output = ""
        if previous_stage != stage:
            reset_decision, reset_output = _force_reset_workflow_stage(
                project_root,
                stage,
                target_stage,
            )
        with self.lock:
            context = self._context_locked(context_id)
            context.workflow_stage = stage
            self._clear_sessions_locked(context, sessions)
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "selected",
            "previous_stage": previous_stage,
            "terminated_agent": terminated_agent,
            "reset_decision": reset_decision,
            "reset_output": reset_output,
        }

    def approve_requirements(
        self,
        context_id: str,
        *,
        skip_approval: bool = False,
    ) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage not in {"requirements", "requirements-approve"}:
                raise AgentSessionError("requirements stage is not active")
            requirements_started = context.requirements_started
        self._terminate_requirements_session(context_id)
        _record_requirements_complete(project_root, skipped=skip_approval)
        from .cli import _cmd_stage, _stage_args
        from .gates import GateEngine

        stdout = io.StringIO()
        stderr = io.StringIO()
        store = StateStore(project_root)
        engine = GateEngine(project_root)
        previously_approved = _stage_has_approvals(
            project_root,
            STAGE_REQUIREMENTS,
            ["human-approval", "author-confirmation"],
        )
        if skip_approval:
            force_approval = True
            reason = (
                "Requirements approval was skipped from the GUI during an "
                "update after a previous requirements approval."
                if previously_approved
                else "WARNING: requirements approval was skipped from the GUI. "
                "The operator accepted the risk that requirements were not "
                "explicitly approved."
            )
        else:
            force_approval = _should_force_completed_requirements_approval(store)
            reason = (
                "Requirements authoring was completed from the GUI without "
                "agent confirmation; approval "
                "force-records the missing author confirmation."
                if force_approval
                else None
            )
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = _cmd_stage(
                store,
                engine,
                _stage_args(
                    STAGE_REQUIREMENTS,
                    human=True,
                    author=True,
                    force=force_approval,
                    reason=reason,
                ),
            )
        output = "\n".join(
            part.strip() for part in [stderr.getvalue(), stdout.getvalue()] if part.strip()
        )
        if code != 0:
            raise AgentSessionError(output or "requirements approval failed")
        with self.lock:
            context = self._context_locked(context_id)
            context.workflow_stage = "design"
            context.requirements_session = None
            context.requirements_started = requirements_started
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "skipped" if skip_approval else "approved",
            "next_stage": "design",
            "output": output,
            "warning": (
                "WARNING: requirements approval was skipped; advancing to design "
                "with forced approval records."
                if skip_approval and not previously_approved
                else None
            ),
        }

    def open_project(self, context_id: str, path: str) -> dict[str, object]:
        if _is_meta_project_path(path):
            return self.open_meta_project(context_id, path)
        project_root = _existing_project_root(path)
        workflow_stage = _active_workflow_stage(project_root)
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
            context.activation_root = project_root
            context.project_mode = "project"
            context.active_project_root = project_root
            context.active_repository_name = None
            context.registered_repositories = []
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = workflow_stage
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
        _remember_recent_project(self.root, project_root, "project")
        return {
            **project_payload(self.root, context, project_root),
            "status": "opened",
        }

    def create_project(self, context_id: str, path: str) -> dict[str, object]:
        project_root = _resolve_project_path(path)
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
        manifest = initialize_project(project_root)
        with self.lock:
            context = self._context_locked(context_id)
            context.activation_root = project_root
            context.project_mode = "project"
            context.active_project_root = project_root
            context.active_repository_name = None
            context.registered_repositories = []
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = _visible_workflow_stage(manifest.active_stage)
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
        _remember_recent_project(self.root, project_root, "project")
        return {
            **project_payload(self.root, context, project_root),
            "status": "created",
            "run_id": manifest.run_id,
        }

    def open_creative_project(self, context_id: str, path: str) -> dict[str, object]:
        project_root = _existing_creative_project_root(path)
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
        _ensure_creative_workspace(project_root)
        with self.lock:
            context = self._context_locked(context_id)
            context.activation_root = project_root
            context.project_mode = "creative"
            context.active_project_root = project_root
            context.active_repository_name = None
            context.registered_repositories = []
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = "project"
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
        _remember_recent_project(self.root, project_root, "creative")
        return {
            **project_payload(self.root, context, project_root),
            "status": "opened",
        }

    def create_creative_project(self, context_id: str, path: str) -> dict[str, object]:
        project_root = _resolve_project_path(path)
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
        project_root.mkdir(parents=True, exist_ok=True)
        _ensure_creative_workspace(project_root)
        with self.lock:
            context = self._context_locked(context_id)
            context.activation_root = project_root
            context.project_mode = "creative"
            context.active_project_root = project_root
            context.active_repository_name = None
            context.registered_repositories = []
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = "project"
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
        _remember_recent_project(self.root, project_root, "creative")
        return {
            **project_payload(self.root, context, project_root),
            "status": "created",
        }

    def open_meta_project(self, context_id: str, path: str) -> dict[str, object]:
        meta_context = _existing_meta_context(path)
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
            context.activation_root = meta_context["meta_root"]
            context.project_mode = "meta"
            context.active_project_root = meta_context["active_project_root"]
            context.active_repository_name = meta_context["active_repository_name"]
            context.registered_repositories = meta_context["registered_repositories"]
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = meta_context["workflow_stage"]
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
            project_root = context.active_project_root
        _remember_recent_project(self.root, meta_context["meta_root"], "meta")
        return {
            **project_payload(self.root, context, project_root),
            "status": "opened",
        }

    def create_meta_project(self, context_id: str, path: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
        meta_root, registry = initialize_meta_project(path)
        repositories = _meta_repository_payloads(registry)
        with self.lock:
            context = self._context_locked(context_id)
            context.activation_root = meta_root
            context.project_mode = "meta"
            context.active_project_root = None
            context.active_repository_name = None
            context.registered_repositories = repositories
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = None
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
        _remember_recent_project(self.root, meta_root, "meta")
        return {
            **project_payload(self.root, context, None),
            "status": "created",
        }

    def add_meta_repository(self, context_id: str, path: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
            meta_root = context.activation_root
            if meta_root is None or context.project_mode != "meta":
                raise StateError("activate a meta-project first")
        meta_context = _add_meta_repository(meta_root, path)
        with self.lock:
            context = self._context_locked(context_id)
            context.registered_repositories = meta_context["registered_repositories"]
            context.active_repository_name = meta_context["active_repository_name"]
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "registered",
        }

    def start_meta_repository(self, context_id: str, repository: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
            meta_root = context.activation_root
            if meta_root is None or context.project_mode != "meta":
                raise StateError("activate a meta-project first")
        meta_context = _start_meta_repository(meta_root, repository)
        with self.lock:
            context = self._context_locked(context_id)
            context.active_project_root = meta_context["active_project_root"]
            context.active_repository_name = meta_context["active_repository_name"]
            context.registered_repositories = meta_context["registered_repositories"]
            context.workflow_stage = meta_context["workflow_stage"]
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "started",
        }

    def remove_meta_repository(self, context_id: str, repository: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
            meta_root = context.activation_root
            if meta_root is None or context.project_mode != "meta":
                raise StateError("activate a meta-project first")
        meta_context = _remove_meta_repository(meta_root, repository)
        with self.lock:
            context = self._context_locked(context_id)
            context.active_project_root = meta_context["active_project_root"]
            context.active_repository_name = meta_context["active_repository_name"]
            context.registered_repositories = meta_context["registered_repositories"]
            context.workflow_stage = meta_context["workflow_stage"]
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "removed",
        }

    def deactivate_project(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            sessions = self._context_process_sessions_locked(context)
        self._terminate_sessions(sessions)
        with self.lock:
            context = self._context_locked(context_id)
            context.activation_root = None
            context.project_mode = "none"
            context.active_project_root = None
            context.active_repository_name = None
            context.registered_repositories = []
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = None
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
        return {
            **project_payload(self.root, context, None),
            "status": "deactivated",
        }

    def start_requirements_agent(
        self,
        context_id: str,
        *,
        allow_stage_reopen: bool = False,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            command_root = self._command_root_locked(context)
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != "requirements" and not allow_stage_reopen:
                raise AgentSessionError("requirements stage is not active")
            if (
                context.requirements_session is not None
                and context.requirements_session.is_active()
            ):
                return context.requirements_session, False
            lock_names = SESSION_ARTIFACT_LOCKS["requirements"]
            self._require_session_locks_available_locked(context, lock_names)
            session = AgentSession(
                command=_requirements_command(command_root),
                cwd=command_root,
                label="requirements agent",
                kind="requirements",
                interactive=True,
                lock_names=lock_names,
            )
            context.requirements_session = session
            context.selected_session_id = session.session_id
            context.workflow_stage = "requirements"
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.requirements_session is session:
                    context.requirements_session = None
                    if context.selected_session_id == session.session_id:
                        context.selected_session_id = None
                    context.requirements_started = False
            raise
        with self.lock:
            context = self._context_locked(context_id)
            if context.requirements_session is session:
                context.requirements_started = True
        return session, True

    def restart_requirements_agent(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if (
                context.workflow_stage == "requirements"
                and not context.requirements_started
            ):
                raise AgentSessionError("start requirements first")
        self._terminate_requirements_session(context_id)
        _reopen_requirements_for_restart(project_root)
        return self.start_requirements_agent(context_id, allow_stage_reopen=True)

    def complete_requirements_agent(self, context_id: str) -> dict[str, object]:
        return self.approve_requirements(context_id)

    def skip_requirements_agent(self, context_id: str) -> dict[str, object]:
        return self.approve_requirements(context_id, skip_approval=True)

    def start_design_agent(
        self,
        context_id: str,
        *,
        allow_stage_reopen: bool = False,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            command_root = self._command_root_locked(context)
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != "design" and not allow_stage_reopen:
                raise AgentSessionError("design stage is not active")
            if (
                context.design_session is not None
                and context.design_session.is_active()
            ):
                return context.design_session, False
            lock_names = SESSION_ARTIFACT_LOCKS["design"]
            self._require_session_locks_available_locked(context, lock_names)
            session = AgentSession(
                command=_stage_command(command_root, "design"),
                cwd=command_root,
                label="design agent",
                kind="design",
                interactive=True,
                lock_names=lock_names,
            )
            context.design_session = session
            context.selected_session_id = session.session_id
            context.workflow_stage = "design"
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.design_session is session:
                    context.design_session = None
                    if context.selected_session_id == session.session_id:
                        context.selected_session_id = None
                    context.design_started = False
            raise
        with self.lock:
            context = self._context_locked(context_id)
            if context.design_session is session:
                context.design_started = True
        return session, True

    def restart_design_agent(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage == "design":
                raise AgentSessionError("design stage is already active")
        self._terminate_workflow_sessions(context_id)
        _reopen_design_for_restart(project_root)
        with self.lock:
            context = self._context_locked(context_id)
            context.design_review_started = False
            context.design_review_interactive = False
        return self.start_design_agent(context_id, allow_stage_reopen=True)

    def complete_design_agent(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != "design":
                raise AgentSessionError("design stage is not active")
            design_started = context.design_started
        self._terminate_design_session(context_id)
        _record_design_complete(project_root)
        with self.lock:
            context = self._context_locked(context_id)
            context.workflow_stage = "design-review"
            context.design_session = None
            context.design_started = design_started
            context.design_review_session = None
            context.design_review_started = False
            context.design_review_interactive = False
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "completed",
            "next_stage": "design-review",
        }

    def start_design_review_agent(
        self,
        context_id: str,
        *,
        force: bool = False,
        allow_stage_reopen: bool = False,
        interactive: bool = False,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            command_root = self._command_root_locked(context)
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != "design-review" and not allow_stage_reopen:
                raise AgentSessionError("design review stage is not active")
            if (
                context.design_review_session is not None
                and context.design_review_session.is_active()
            ):
                return context.design_review_session, False
            lock_names = SESSION_ARTIFACT_LOCKS["design-review"]
            self._require_session_locks_available_locked(context, lock_names)
            session = AgentSession(
                command=_stage_command(
                    command_root,
                    "design-review",
                    force=force,
                    interactive=interactive,
                ),
                cwd=command_root,
                label=(
                    "interactive design-review agent"
                    if interactive
                    else "design-review agent"
                ),
                kind="design-review",
                interactive=interactive,
                lock_names=lock_names,
                on_completed=(
                    None
                    if interactive
                    else lambda returncode: self._mark_design_review_completed(
                        context_id,
                        returncode,
                    )
                ),
            )
            context.design_review_session = session
            context.selected_session_id = session.session_id
            context.design_review_interactive = interactive
            context.workflow_stage = "design-review"
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.design_review_session is session:
                    context.design_review_session = None
                    if context.selected_session_id == session.session_id:
                        context.selected_session_id = None
                    context.design_review_started = False
                    context.design_review_interactive = False
            raise
        with self.lock:
            context = self._context_locked(context_id)
            if context.design_review_session is session:
                context.design_review_started = True
        return session, True

    def restart_design_review_agent(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            force = context.workflow_stage != "design-review"
            if context.workflow_stage == "design-review" and not context.design_review_started:
                raise AgentSessionError("start design review first")
        self._terminate_workflow_sessions(context_id)
        return self.start_design_review_agent(
            context_id,
            force=force,
            allow_stage_reopen=True,
        )

    def start_documentation_agent(
        self,
        context_id: str,
        *,
        interactive: bool = True,
        target: str | None = None,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            command_root = self._command_root_locked(context)
            if project_root is None:
                raise AgentSessionError("activate a project first")
            target_path = (target or "").strip()
            if target_path:
                target_path = _ensure_document_target(project_root, target_path)
            session_key = target_path or "__default__"
            existing_session = context.documentation_sessions.get(session_key)
            if existing_session is not None and existing_session.is_active():
                context.selected_session_id = existing_session.session_id
                return existing_session, False
            lock_names = frozenset({f"documentation:{session_key}"})
            self._require_session_locks_available_locked(context, lock_names)
            label_target = f" ({target_path})" if target_path else ""
            document_label = Path(target_path).name if target_path else "Documentation"
            session = AgentSession(
                command=_documentation_command(
                    command_root,
                    interactive=interactive,
                    target=target_path or None,
                ),
                cwd=command_root,
                label=(
                    f"interactive documentation agent{label_target}"
                    if interactive
                    else f"documentation agent{label_target}"
                ),
                kind="documentation",
                interactive=interactive,
                lock_names=lock_names,
                metadata={
                    "document_path": target_path,
                    "document_label": document_label,
                },
            )
            context.documentation_sessions[session_key] = session
            context.selected_session_id = session.session_id
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.documentation_sessions.get(session_key) is session:
                    context.documentation_sessions.pop(session_key, None)
                    context.selected_session_id = None
            raise
        return session, True

    def initialize_creative_workspace(self, context_id: str) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        _ensure_creative_workspace(project_root)
        return self.creative_tree(context_id)

    def creative_tree(self, context_id: str) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        return _creative_tree_payload(project_root)

    def create_creative_folder(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        path = _create_creative_folder(project_root, relative_path)
        return {
            "status": "created",
            "path": path,
        }

    def create_creative_document(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        path = _create_creative_document(project_root, relative_path)
        return {
            "status": "created",
            "path": path,
        }

    def create_creative_corkboard(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        path = _create_creative_corkboard(project_root, relative_path)
        return {
            "status": "created",
            "path": path,
        }

    def rename_creative_entry(
        self,
        context_id: str,
        relative_path: str,
        new_name: str,
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        old_path, new_path = _rename_creative_entry(
            project_root,
            relative_path,
            new_name,
        )
        return {
            "status": "renamed",
            "old_path": old_path,
            "path": new_path,
        }

    def delete_creative_entry(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        path = _delete_creative_entry(project_root, relative_path)
        return {
            "status": "deleted",
            "path": path,
        }

    def creative_scratchpad(self, context_id: str) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        path = _ensure_creative_scratchpad(project_root)
        return {
            "path": path.relative_to(project_root).as_posix(),
            "markdown": path.read_text(encoding="utf-8"),
        }

    def save_creative_scratchpad(
        self,
        context_id: str,
        markdown: str,
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        path = _ensure_creative_scratchpad(project_root)
        path.write_text(markdown, encoding="utf-8")
        return {
            "status": "saved",
            "path": path.relative_to(project_root).as_posix(),
        }

    def save_creative_corkboard(
        self,
        context_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
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
            return {
                "status": "saved",
                "order": saved_order,
            }
        if board_type == "folder":
            card = _save_creative_folder_corkboard_card(
                project_root,
                folder_path=str(payload.get("folder") or ""),
                card_path=str(payload.get("path") or ""),
                note=str(payload.get("note") or ""),
                color=payload.get("color"),
            )
            return {
                "status": "saved",
                "card": card,
            }
        if board_type == "freeform":
            if str(payload.get("action") or "") == "delete":
                card_id = _delete_creative_freeform_corkboard_card(
                    project_root,
                    corkboard_path=str(payload.get("corkboard") or ""),
                    card_id=str(payload.get("card_id") or ""),
                )
                return {
                    "status": "deleted",
                    "card_id": card_id,
                }
            card_payload = payload.get("card")
            if not isinstance(card_payload, dict):
                raise StateError("freeform corkboard card is required")
            card = _save_creative_freeform_corkboard_card(
                project_root,
                corkboard_path=str(payload.get("corkboard") or ""),
                card_payload=card_payload,
            )
            return {
                "status": "saved",
                "card": card,
            }
        raise StateError(f"unknown corkboard type: {board_type}")

    def start_creative_writing_agent(
        self,
        context_id: str,
        *,
        active_document: str | None = None,
        active_target: dict[str, object] | None = None,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if (
                context.creative_session is not None
                and context.creative_session.is_active()
            ):
                context.selected_session_id = context.creative_session.session_id
                return context.creative_session, False
            document_path = ""
            if active_document:
                document_path = _document_target_path(project_root, active_document)[0]
            target = _creative_agent_target(
                project_root,
                active_target=active_target,
                active_document=document_path or None,
            )
            session = AgentSession(
                command=_creative_writing_command(project_root, target),
                cwd=project_root,
                label="creative writing agent",
                kind="creative-writing",
                interactive=True,
            )
            context.creative_session = session
            context.selected_session_id = session.session_id
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.creative_session is session:
                    context.creative_session = None
                    context.selected_session_id = None
            raise
        return session, True

    def stop_design_review_agent(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != "design-review":
                raise AgentSessionError("design review stage is not active")
            session = context.design_review_session
            if session is None or not session.is_active():
                raise AgentSessionError("design review is not running")
        session.terminate()
        with self.lock:
            context = self._context_locked(context_id)
            if context.design_review_session is session:
                context.design_review_session = None
                context.design_review_interactive = False
            session_id = getattr(session, "session_id", None)
            if session_id is not None and context.selected_session_id == session_id:
                context.selected_session_id = None
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "stopped",
        }

    def complete_design_review_agent(self, context_id: str) -> dict[str, object]:
        return self.approve_design(context_id)

    def approve_design(
        self,
        context_id: str,
        *,
        skip_approval: bool = False,
    ) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage not in {"design-review", "design-approve"}:
                raise AgentSessionError("design review stage is not active")
            session = context.design_review_session
            design_review_started = context.design_review_started
            needs_design_review_completion = context.workflow_stage == "design-review"
        if session is not None and session.is_active():
            session.terminate()
        from .cli import _cmd_stage, _stage_args
        from .gates import GateEngine

        stdout = io.StringIO()
        stderr = io.StringIO()
        store = StateStore(project_root)
        engine = GateEngine(project_root)
        manifest = store.load_current_manifest()
        if needs_design_review_completion and not manifest.has_gate(GATE_DESIGN):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = _cmd_stage(
                    store,
                    engine,
                    _stage_args(
                        STAGE_DESIGN_REVIEW,
                        force=True,
                        reason="Design review was completed from the GUI approval action.",
                    ),
                )
            if code != 0:
                output = "\n".join(
                    part.strip()
                    for part in [stderr.getvalue(), stdout.getvalue()]
                    if part.strip()
                )
                with self.lock:
                    context = self._context_locked(context_id)
                    if context.design_review_session is session:
                        context.design_review_session = None
                        if (
                            session is not None
                            and context.selected_session_id
                            == getattr(session, "session_id", None)
                        ):
                            context.selected_session_id = None
                        context.design_review_interactive = False
                raise AgentSessionError(output or "design review completion failed")
            store = StateStore(project_root)
            engine = GateEngine(project_root)
        previously_approved = _stage_has_approvals(
            project_root,
            STAGE_DESIGN_ACCEPTANCE,
            ["human-approval"],
        )
        if skip_approval:
            reason = (
                "Design approval was skipped from the GUI during an update "
                "after a previous design approval."
                if previously_approved
                else "WARNING: design approval was skipped from the GUI. "
                "The operator accepted the risk that design was not "
                "explicitly approved."
            )
        else:
            reason = None
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = _cmd_stage(
                store,
                engine,
                _stage_args(
                    STAGE_DESIGN_ACCEPTANCE,
                    human=True,
                    force=skip_approval,
                    reason=reason,
                ),
            )
        output = "\n".join(
            part.strip()
            for part in [stderr.getvalue(), stdout.getvalue()]
            if part.strip()
        )
        if code != 0:
            raise AgentSessionError(output or "design approval failed")
        with self.lock:
            context = self._context_locked(context_id)
            context.workflow_stage = "implementation-plan"
            context.design_review_session = None
            context.design_review_interactive = False
            context.design_review_started = design_review_started
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "skipped" if skip_approval else "approved",
            "next_stage": "implementation-plan",
            "output": output,
            "warning": (
                "WARNING: design approval was skipped; advancing to "
                "implementation planning with a forced approval record."
                if skip_approval and not previously_approved
                else None
            ),
        }

    def start_workflow_stage_agent(
        self,
        context_id: str,
        stage: str,
        *,
        interactive: bool | None = None,
        force: bool = False,
        allow_stage_reopen: bool = False,
    ) -> tuple[AgentSession, bool]:
        config = _generic_stage_config(stage)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            command_root = self._command_root_locked(context)
            if project_root is None or command_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != stage and not allow_stage_reopen:
                raise AgentSessionError(f"{stage} stage is not active")
            existing = context.stage_sessions.get(stage)
            if existing is not None and existing.is_active():
                return existing, False
            lock_names = SESSION_ARTIFACT_LOCKS.get(stage, frozenset())
            self._require_session_locks_available_locked(context, lock_names)
            accepts_input = (
                bool(config["interactive_default"])
                if interactive is None
                else interactive
            )
            session = AgentSession(
                command=_generic_stage_command(
                    command_root,
                    stage,
                    force=force,
                    reason=(
                        f"{_stage_display_label(stage)} restarted from the GUI."
                        if force and bool(config.get("reason_arg"))
                        else None
                    ),
                    interactive=accepts_input,
                ),
                cwd=command_root,
                label=(
                    f"interactive {_stage_display_label(stage)} agent"
                    if accepts_input
                    else f"{_stage_display_label(stage)} agent"
                ),
                kind=stage,
                interactive=accepts_input,
                lock_names=lock_names,
                on_completed=lambda returncode: self._mark_generic_stage_completed(
                    context_id,
                    stage,
                    returncode,
                ),
            )
            context.stage_sessions[stage] = session
            context.selected_session_id = session.session_id
            context.workflow_stage = stage
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.stage_sessions.get(stage) is session:
                    context.stage_sessions.pop(stage, None)
                    if context.selected_session_id == session.session_id:
                        context.selected_session_id = None
                    context.stage_started.discard(stage)
            raise
        with self.lock:
            context = self._context_locked(context_id)
            if context.stage_sessions.get(stage) is session:
                context.stage_started.add(stage)
        return session, True

    def restart_workflow_stage_agent(
        self,
        context_id: str,
        stage: str,
        *,
        interactive: bool | None = None,
    ) -> tuple[AgentSession, bool]:
        _generic_stage_config(stage)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage == stage and stage not in context.stage_started:
                raise AgentSessionError(f"start {stage} first")
        self._terminate_workflow_sessions(context_id)
        return self.start_workflow_stage_agent(
            context_id,
            stage,
            interactive=interactive,
            force=True,
            allow_stage_reopen=True,
        )

    def stop_workflow_stage_agent(self, context_id: str, stage: str) -> dict[str, object]:
        _generic_stage_config(stage)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != stage:
                raise AgentSessionError(f"{stage} stage is not active")
            session = context.stage_sessions.get(stage)
            if session is None or not session.is_active():
                raise AgentSessionError(f"{stage} agent is not running")
        session.terminate()
        with self.lock:
            context = self._context_locked(context_id)
            if context.stage_sessions.get(stage) is session:
                context.stage_sessions.pop(stage, None)
            if context.selected_session_id == session.session_id:
                context.selected_session_id = None
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "stopped",
        }

    def approve_workflow_stage(
        self,
        context_id: str,
        stage: str,
        *,
        skip_approval: bool = False,
    ) -> dict[str, object]:
        config = _generic_stage_config(stage)
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != stage:
                raise AgentSessionError(f"{stage} stage is not active")
            session = context.stage_sessions.get(stage)
        if session is not None and session.is_active():
            session.terminate()
        command = [str(config["approval_command"])]
        warning = None
        if skip_approval:
            command.append("--force")
            if bool(config.get("approval_reason_arg", config.get("reason_arg"))):
                command.extend(
                    [
                        "--reason",
                        (
                            f"WARNING: {_stage_display_label(stage)} approval was "
                            "skipped from the GUI. The operator accepted the risk "
                            "that the stage was not explicitly approved."
                        ),
                    ]
                )
            warning = (
                f"WARNING: {_stage_display_label(stage)} approval was skipped; "
                "advancing with forced approval records."
            )
        output = _run_electroboy_cli_command(project_root, command)
        with self.lock:
            context = self._context_locked(context_id)
            if context.stage_sessions.get(stage) is session:
                context.stage_sessions.pop(stage, None)
            context.stage_started.add(stage)
            context.workflow_stage = _active_workflow_stage(project_root)
            if session is not None and context.selected_session_id == session.session_id:
                context.selected_session_id = None
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "skipped" if skip_approval else "approved",
            "next_stage": context.workflow_stage,
            "output": output,
            "warning": warning,
        }

    def _mark_generic_stage_completed(
        self,
        context_id: str,
        stage: str,
        returncode: int,
    ) -> None:
        if returncode != 0:
            return
        with self.lock:
            try:
                context = self._context_locked(context_id)
            except StateError:
                return
            context.stage_started.add(stage)
            project_root = context.active_project_root
            if project_root is not None:
                context.workflow_stage = _active_workflow_stage(project_root)

    def requirements_document_root(self, context_id: str) -> Path:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise StateError("activate a project first")
            if (
                context.workflow_stage == "requirements"
                and not context.requirements_started
            ):
                raise AgentSessionError("start requirements first")
            return project_root

    def active_project_root(self, context_id: str) -> Path:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise StateError("activate a project first")
            return project_root

    def command_root(self, context_id: str) -> Path:
        with self.lock:
            context = self._context_locked(context_id)
            command_root = self._command_root_locked(context)
            if command_root is None:
                raise StateError("activate a project first")
            return command_root

    def current_requirements_session(self, context_id: str) -> AgentSession | None:
        with self.lock:
            context = self._context_locked(context_id)
            return context.requirements_session

    def current_design_session(self, context_id: str) -> AgentSession | None:
        with self.lock:
            context = self._context_locked(context_id)
            return context.design_session

    def current_design_review_session(self, context_id: str) -> AgentSession | None:
        with self.lock:
            context = self._context_locked(context_id)
            return context.design_review_session

    def current_documentation_session(self, context_id: str) -> AgentSession | None:
        with self.lock:
            context = self._context_locked(context_id)
            selected_session_id = context.selected_session_id
            if selected_session_id:
                for session in context.documentation_sessions.values():
                    if session.session_id == selected_session_id:
                        return session
            for session in reversed(list(context.documentation_sessions.values())):
                if session.is_active():
                    return session
            if context.documentation_sessions:
                return list(context.documentation_sessions.values())[-1]
            return None

    def start_ad_hoc_agent(self, context_id: str) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            command_root = self._command_root_locked(context)
            if command_root is None:
                raise AgentSessionError("activate a project first")
            if (
                context.ad_hoc_session is not None
                and context.ad_hoc_session.is_active()
            ):
                context.selected_session_id = context.ad_hoc_session.session_id
                return context.ad_hoc_session, False
            session = AgentSession(
                command=_ad_hoc_agent_command(command_root),
                cwd=command_root,
                label="ad-hoc agent",
                kind="ad-hoc",
                interactive=True,
            )
            context.ad_hoc_session = session
            context.selected_session_id = session.session_id
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.ad_hoc_session is session:
                    context.ad_hoc_session = None
                    context.selected_session_id = None
            raise
        return session, True

    def current_project_shell_session(self, context_id: str) -> AgentSession | None:
        with self.lock:
            context = self._context_locked(context_id)
            return context.project_shell_session

    def start_project_shell(self, context_id: str) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if (
                context.project_shell_session is not None
                and context.project_shell_session.is_active()
            ):
                return context.project_shell_session, False
            session = AgentSession(
                command=_project_shell_command(),
                cwd=project_root,
                label="project shell",
                kind="project-shell",
                interactive=True,
                echo_input=True,
            )
            context.project_shell_session = session
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.project_shell_session is session:
                    context.project_shell_session = None
            raise
        return session, True

    def send_project_shell_input(self, context_id: str, data: str) -> None:
        session = self.current_project_shell_session(context_id)
        if session is None:
            raise AgentSessionError("project shell has not been started")
        session.send_raw(data)

    def resize_project_shell(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None:
        session = self.current_project_shell_session(context_id)
        if session is None:
            raise AgentSessionError("project shell has not been started")
        session.resize(columns, rows)

    def stop_project_shell(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.project_shell_session
        if session is None or not session.is_active():
            raise AgentSessionError("project shell is not running")
        session.terminate()
        with self.lock:
            context = self._context_locked(context_id)
            if context.project_shell_session is session:
                context.project_shell_session = None
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "stopped project shell",
        }

    def session_payload(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            selected_session = self._selected_session_locked(context)
            return {
                "context_id": context.context_id,
                "selected_session_id": (
                    selected_session.session_id if selected_session is not None else None
                ),
                "sessions": _session_payloads(context),
            }

    def select_session(self, context_id: str, session_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            session = self._session_by_id_locked(context, session_id)
            context.selected_session_id = session.session_id
            return {
                "context_id": context.context_id,
                "selected_session_id": session.session_id,
                "sessions": _session_payloads(context),
            }

    def selected_session(self, context_id: str) -> AgentSession | None:
        with self.lock:
            context = self._context_locked(context_id)
            return self._selected_session_locked(context)

    def session_by_id(self, context_id: str, session_id: str) -> AgentSession:
        with self.lock:
            context = self._context_locked(context_id)
            return self._session_by_id_locked(context, session_id)

    def send_selected_session_message(self, context_id: str, message: str) -> None:
        session = self.selected_session(context_id)
        if session is None:
            raise AgentSessionError("no agent session is selected")
        if not session.interactive:
            raise AgentSessionError(f"{session.label} does not accept input")
        session.send(message)

    def send_session_message(
        self,
        context_id: str,
        session_id: str,
        message: str,
    ) -> None:
        session = self.session_by_id(context_id, session_id)
        if not session.interactive:
            raise AgentSessionError(f"{session.label} does not accept input")
        session.send(message)

    def send_selected_session_key(self, context_id: str, key: str) -> None:
        session = self.selected_session(context_id)
        if session is None:
            raise AgentSessionError("no agent session is selected")
        if not session.interactive:
            raise AgentSessionError(f"{session.label} does not accept input")
        session.send_key(key)

    def send_selected_session_raw(self, context_id: str, data: str) -> None:
        session = self.selected_session(context_id)
        if session is None:
            raise AgentSessionError("no agent session is selected")
        if not session.interactive:
            raise AgentSessionError(f"{session.label} does not accept input")
        session.send_raw(data)

    def interrupt_selected_session(self, context_id: str) -> None:
        session = self.selected_session(context_id)
        if session is None:
            raise AgentSessionError("no agent session is selected")
        session.interrupt()

    def resize_selected_session(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None:
        session = self.selected_session(context_id)
        if session is None:
            raise AgentSessionError("no agent session is selected")
        session.resize(columns, rows)

    def resize_session(
        self,
        context_id: str,
        session_id: str,
        columns: int,
        rows: int,
    ) -> None:
        session = self.session_by_id(context_id, session_id)
        session.resize(columns, rows)

    def has_running_progress_agent(self, context_id: str) -> bool:
        with self.lock:
            context = self._context_locked(context_id)
            design_review_session = context.design_review_session
            generic_running = any(
                session.is_active() and not session.interactive
                for session in context.stage_sessions.values()
            )
            return bool(
                (
                    design_review_session is not None
                    and design_review_session.is_active()
                    and not context.design_review_interactive
                )
                or generic_running
            )

    def resize_requirements_agent(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.requirements_session
        if session is None:
            raise AgentSessionError("requirements agent has not been started")
        session.resize(columns, rows)

    def resize_design_agent(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.design_session
        if session is None:
            raise AgentSessionError("design agent has not been started")
        session.resize(columns, rows)

    def resize_design_review_agent(
        self,
        context_id: str,
        columns: int,
        rows: int,
    ) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.design_review_session
        if session is None:
            raise AgentSessionError("design review agent has not been started")
        session.resize(columns, rows)

    def interrupt_requirements_agent(self, context_id: str) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.requirements_session
        if session is None:
            raise AgentSessionError("requirements agent has not been started")
        session.interrupt()

    def interrupt_design_agent(self, context_id: str) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.design_session
        if session is None:
            raise AgentSessionError("design agent has not been started")
        session.interrupt()

    def interrupt_design_review_agent(self, context_id: str) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.design_review_session
        if session is None:
            raise AgentSessionError("design review agent has not been started")
        session.interrupt()

    def _terminate_requirements_session(self, context_id: str) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.requirements_session
        if session is not None and session.is_active():
            session.terminate()
        with self.lock:
            context = self._context_locked(context_id)
            if context.requirements_session is session:
                context.requirements_session = None
            session_id = getattr(session, "session_id", None)
            if session_id is not None and context.selected_session_id == session_id:
                context.selected_session_id = None

    def _terminate_design_session(self, context_id: str) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.design_session
        if session is not None and session.is_active():
            session.terminate()
        with self.lock:
            context = self._context_locked(context_id)
            if context.design_session is session:
                context.design_session = None
            session_id = getattr(session, "session_id", None)
            if session_id is not None and context.selected_session_id == session_id:
                context.selected_session_id = None

    def _terminate_all_context_sessions(self, context_id: str) -> bool:
        with self.lock:
            context = self._context_locked(context_id)
            sessions = self._context_sessions_locked(context)
        terminated = self._terminate_sessions(sessions)
        with self.lock:
            context = self._context_locked(context_id)
            self._clear_sessions_locked(context, sessions)
        return terminated

    def _terminate_workflow_sessions(self, context_id: str) -> bool:
        with self.lock:
            context = self._context_locked(context_id)
            sessions = [
                session
                for session in [
                    context.requirements_session,
                    context.design_session,
                    context.design_review_session,
                    *context.stage_sessions.values(),
                    context.ad_hoc_session,
                ]
                if session is not None
            ]
        terminated = self._terminate_sessions(sessions)
        with self.lock:
            context = self._context_locked(context_id)
            self._clear_sessions_locked(context, sessions)
        return terminated

    def terminate_all_sessions(self) -> bool:
        with self.lock:
            sessions = self._all_sessions_locked()
        terminated = self._terminate_sessions(sessions)
        with self.lock:
            for context in self.contexts.values():
                self._clear_sessions_locked(context, sessions)
        return terminated

    def _mark_design_review_completed(
        self,
        context_id: str,
        returncode: int,
    ) -> None:
        if returncode != 0:
            return
        with self.lock:
            try:
                context = self._context_locked(context_id)
            except StateError:
                return
            if context.workflow_stage == "design-review":
                context.design_review_started = True

    def _context_sessions_locked(
        self,
        context: BrowserContext,
    ) -> list[AgentSession]:
        return [
            session
            for session in [
                context.requirements_session,
                context.design_session,
                context.design_review_session,
                *context.stage_sessions.values(),
                *context.documentation_sessions.values(),
                context.creative_session,
                context.ad_hoc_session,
            ]
            if session is not None
        ]

    def _context_process_sessions_locked(
        self,
        context: BrowserContext,
    ) -> list[AgentSession]:
        sessions = self._context_sessions_locked(context)
        if context.project_shell_session is not None:
            sessions.append(context.project_shell_session)
        return sessions

    def _all_sessions_locked(self) -> list[AgentSession]:
        sessions: list[AgentSession] = []
        seen: set[int] = set()
        for context in self.contexts.values():
            for session in self._context_process_sessions_locked(context):
                identifier = id(session)
                if identifier in seen:
                    continue
                seen.add(identifier)
                sessions.append(session)
        return sessions

    def _clear_sessions_locked(
        self,
        context: BrowserContext,
        sessions: list[AgentSession],
    ) -> None:
        for session in sessions:
            if context.requirements_session is session:
                context.requirements_session = None
            if context.design_session is session:
                context.design_session = None
            if context.design_review_session is session:
                context.design_review_session = None
                context.design_review_interactive = False
            for stage, stage_session in list(context.stage_sessions.items()):
                if stage_session is session:
                    context.stage_sessions.pop(stage, None)
            for key, documentation_session in list(context.documentation_sessions.items()):
                if documentation_session is session:
                    context.documentation_sessions.pop(key, None)
            if context.creative_session is session:
                context.creative_session = None
            if context.ad_hoc_session is session:
                context.ad_hoc_session = None
            if context.project_shell_session is session:
                context.project_shell_session = None
            session_id = getattr(session, "session_id", None)
            if session_id is not None and context.selected_session_id == session_id:
                context.selected_session_id = None

    def _terminate_sessions(self, sessions: list[AgentSession]) -> bool:
        terminated = False
        for session in sessions:
            if session.is_active():
                session.terminate()
                terminated = True
        return terminated

    def _context_locked(self, context_id: str) -> BrowserContext:
        context_id = context_id.strip()
        if not context_id:
            raise StateError("missing browser context; refresh the page")
        context = self.contexts.get(context_id)
        if context is None:
            raise StateError("unknown browser context; refresh the page")
        return context

    def _session_by_id_locked(
        self,
        context: BrowserContext,
        session_id: str,
    ) -> AgentSession:
        session_id = session_id.strip()
        for session in self._context_sessions_locked(context):
            if session.session_id == session_id:
                return session
        raise AgentSessionError("unknown agent session")

    def _selected_session_locked(
        self,
        context: BrowserContext,
    ) -> AgentSession | None:
        selected_session_id = context.selected_session_id
        sessions = self._context_sessions_locked(context)
        if selected_session_id:
            for session in sessions:
                if session.session_id == selected_session_id:
                    return session
        for session in sessions:
            if session.is_active():
                context.selected_session_id = session.session_id
                return session
        if sessions:
            context.selected_session_id = sessions[-1].session_id
            return sessions[-1]
        context.selected_session_id = None
        return None

    def _command_root_locked(self, context: BrowserContext) -> Path | None:
        return context.activation_root or context.active_project_root

    def _require_no_active_agent_locked(self, context: BrowserContext) -> None:
        active_labels = [
            getattr(session, "label", "agent")
            for session in self._context_process_sessions_locked(context)
            if session.is_active()
        ]
        if active_labels:
            raise AgentSessionError(
                "cannot change projects while this context's "
                f"{active_labels[0]} is running"
            )

    def _require_session_locks_available_locked(
        self,
        context: BrowserContext,
        lock_names: frozenset[str],
    ) -> None:
        if not lock_names:
            return
        for session in self._context_sessions_locked(context):
            if not session.is_active():
                continue
            overlap = sorted(frozenset(getattr(session, "lock_names", ())).intersection(lock_names))
            if overlap:
                raise AgentSessionError(
                    f"{session.label} is already using {', '.join(overlap)}"
                )

    def _require_requirements_started_locked(self, context: BrowserContext) -> None:
        if not context.requirements_started:
            raise AgentSessionError("start requirements first")


def _force_reset_workflow_stage(
    project_root: Path,
    workflow_stage: str,
    target_stage: str,
) -> tuple[str, str]:
    from .cli import _force_reset_to_stage

    stdout = io.StringIO()
    stderr = io.StringIO()
    store = StateStore(project_root)
    reason = f"Set workflow stage to {workflow_stage} from the GUI."
    with redirect_stdout(stdout), redirect_stderr(stderr):
        decision_id = _force_reset_to_stage(store, target_stage, reason)
    output = "\n".join(
        part.strip()
        for part in [stderr.getvalue(), stdout.getvalue()]
        if part.strip()
    )
    return decision_id, output


@dataclass(frozen=True)
class ServiceConfig:
    root: Path
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT


class AgentSessionError(RuntimeError):
    """Raised when an agent session cannot accept an operation."""


class AgentSession:
    """One browser-mediated child process attached through a pseudo-terminal."""

    def __init__(
        self,
        command: list[str],
        cwd: Path | str,
        columns: int = 120,
        rows: int = 32,
        label: str = "agent",
        kind: str = "agent",
        interactive: bool = True,
        lock_names: frozenset[str] | set[str] | None = None,
        on_completed: Callable[[int], None] | None = None,
        echo_input: bool = False,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.session_id = uuid4().hex
        self.command = command
        self.cwd = Path(cwd).resolve()
        self.columns = _clamp_terminal_columns(columns)
        self.rows = _clamp_terminal_rows(rows)
        self.label = label
        self.kind = kind
        self.interactive = interactive
        self.echo_input = echo_input
        self.lock_names = frozenset(lock_names or ())
        self.created_at = utc_now()
        self.on_completed = on_completed
        self.metadata = dict(metadata or {})
        self.process: subprocess.Popen[bytes] | None = None
        self.status = "created"
        self.returncode: int | None = None
        self._master_fd: int | None = None
        self._events: list[dict[str, object]] = []
        self._next_event_id = 1
        self._terminal_pending = ""
        self._condition = threading.Condition()
        self._reader_thread: threading.Thread | None = None
        self._waiter_thread: threading.Thread | None = None

    def payload(self, selected: bool = False) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "kind": self.kind,
            "label": self.label,
            "status": "running" if self.is_active() else self.status,
            "returncode": self.returncode,
            "interactive": self.interactive,
            "locks": sorted(self.lock_names),
            "selected": selected,
            "created_at": self.created_at,
            "command": list(self.command),
            "metadata": dict(self.metadata),
        }

    def start(self) -> None:
        if self.process is not None:
            return
        master_fd, slave_fd = pty.openpty()
        env = _agent_process_env()
        env["ELECTROBOY_PROJECT_ROOT"] = str(self.cwd)
        env["AI_PIPELINE_PROJECT_ROOT"] = str(self.cwd)
        if not self.echo_input:
            _disable_terminal_echo(slave_fd)
        _set_terminal_size(slave_fd, self.columns, self.rows)
        popen_kwargs: dict[str, Any] = {
            "args": self.command,
            "cwd": self.cwd,
            "stdin": slave_fd,
            "stdout": slave_fd,
            "stderr": slave_fd,
            "env": env,
            "close_fds": True,
        }
        if sys.version_info >= (3, 11):
            popen_kwargs["process_group"] = 0
        else:
            popen_kwargs["start_new_session"] = True
        try:
            self.process = subprocess.Popen(**popen_kwargs)
        except Exception:
            os.close(master_fd)
            os.close(slave_fd)
            raise
        os.close(slave_fd)
        self._master_fd = master_fd
        self.status = "running"
        self._append_event(
            {
                "type": "system",
                "text": f"started: {' '.join(self.command)}",
            }
        )
        self._reader_thread = threading.Thread(
            target=self._read_output,
            name="electroboy-agent-output",
            daemon=True,
        )
        self._waiter_thread = threading.Thread(
            target=self._wait_for_exit,
            name="electroboy-agent-wait",
            daemon=True,
        )
        self._reader_thread.start()
        self._waiter_thread.start()

    def send(self, message: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        if self._master_fd is None:
            raise AgentSessionError(f"{self.label} input is not available")
        try:
            for index, text in enumerate(_terminal_input_chunks_for_message(message)):
                if index > 0:
                    time.sleep(TERMINAL_SUBMIT_DELAY_SECONDS)
                os.write(self._master_fd, text.encode("utf-8"))
        except OSError as error:
            raise AgentSessionError(f"could not write to {self.label}: {error}")

    def send_key(self, key: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        if self._master_fd is None:
            raise AgentSessionError(f"{self.label} input is not available")
        try:
            os.write(self._master_fd, _terminal_input_for_key(key).encode("utf-8"))
        except OSError as error:
            raise AgentSessionError(f"could not write to {self.label}: {error}")

    def send_raw(self, data: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        if self._master_fd is None:
            raise AgentSessionError(f"{self.label} input is not available")
        try:
            os.write(self._master_fd, data.encode("utf-8", errors="ignore"))
        except OSError as error:
            raise AgentSessionError(f"could not write to {self.label}: {error}")

    def interrupt(self) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        fd = self._master_fd
        if fd is not None:
            try:
                os.write(fd, b"\x1b")
            except OSError as error:
                raise AgentSessionError(
                    f"could not interrupt {self.label}: {error}"
                )

    def terminate(self, timeout: float = 2.0) -> None:
        process = self.process
        if process is None:
            self._close_master()
            return
        if process.poll() is not None:
            self._close_master()
            return
        _terminate_process_tree(process, timeout=timeout)
        self.returncode = process.returncode
        self.status = "terminated"
        self._close_master()

    def resize(self, columns: int, rows: int) -> None:
        self.columns = _clamp_terminal_columns(columns)
        self.rows = _clamp_terminal_rows(rows)
        fd = self._master_fd
        if fd is None:
            return
        _set_terminal_size(fd, self.columns, self.rows)
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGWINCH)
        except ProcessLookupError:
            return
        except OSError:
            return

    def events_after(self, event_id: int) -> list[dict[str, object]]:
        with self._condition:
            return [
                event.copy()
                for event in self._events
                if int(event.get("id", 0)) > event_id
            ]

    def events(self) -> list[dict[str, object]]:
        with self._condition:
            return [event.copy() for event in self._events]

    def wait_for_events_after(
        self,
        event_id: int,
        timeout: float,
    ) -> list[dict[str, object]]:
        with self._condition:
            if (
                not any(int(event.get("id", 0)) > event_id for event in self._events)
                and self.is_active()
            ):
                self._condition.wait(timeout=timeout)
            return [
                event.copy()
                for event in self._events
                if int(event.get("id", 0)) > event_id
            ]

    def is_active(self) -> bool:
        process = self.process
        return process is not None and process.poll() is None

    def _append_event(self, payload: dict[str, object]) -> None:
        with self._condition:
            payload["id"] = self._next_event_id
            self._next_event_id += 1
            self._events.append(payload)
            self._condition.notify_all()

    def _read_output(self) -> None:
        fd = self._master_fd
        if fd is None:
            return
        while True:
            try:
                chunk = os.read(fd, 4096)
            except OSError as error:
                if error.errno in {errno.EBADF, errno.EIO}:
                    break
                self._append_event(
                    {
                        "type": "error",
                        "text": f"agent output stream failed: {error}",
                    }
                )
                break
            if not chunk:
                break
            terminal_text = chunk.decode("utf-8", errors="replace")
            text, self._terminal_pending = _clean_terminal_output(
                terminal_text,
                self._terminal_pending,
            )
            if not text and not terminal_text:
                continue
            self._append_event(
                {
                    "type": "output",
                    "text": text,
                    "terminal": terminal_text,
                }
            )

    def _wait_for_exit(self) -> None:
        process = self.process
        if process is None:
            return
        returncode = process.wait()
        time.sleep(0.05)
        self.returncode = returncode
        self.status = "completed"
        if self.on_completed is not None:
            try:
                self.on_completed(returncode)
            except Exception as error:
                self._append_event(
                    {
                        "type": "error",
                        "text": f"completion hook failed: {error}",
                    }
                )
        self._append_event(
            {
                "type": "completed",
                "returncode": returncode,
            }
        )
        self._close_master()

    def _close_master(self) -> None:
        fd = self._master_fd
        if fd is None:
            return
        self._master_fd = None
        try:
            os.close(fd)
        except OSError:
            return


def _terminate_process_tree(
    process: subprocess.Popen[bytes],
    timeout: float,
) -> None:
    root_pid = process.pid
    pids = [root_pid, *_descendant_process_ids(root_pid)]
    _signal_process_ids(root_pid, pids, signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _signal_process_ids(root_pid, pids, signal.SIGKILL)
        process.wait(timeout=1)
        return

    survivors = [pid for pid in pids if pid != root_pid and _process_exists(pid)]
    if survivors:
        _signal_process_ids(root_pid, survivors, signal.SIGKILL)


def _signal_process_ids(root_pid: int, pids: list[int], sig: int) -> None:
    try:
        os.killpg(root_pid, sig)
    except ProcessLookupError:
        pass
    except OSError:
        pass
    for pid in reversed(pids):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            continue
        except OSError:
            continue


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _descendant_process_ids(root_pid: int) -> list[int]:
    parent_map = _process_parent_map()
    if not parent_map:
        return []
    children_by_parent: dict[int, list[int]] = {}
    for pid, parent_pid in parent_map.items():
        children_by_parent.setdefault(parent_pid, []).append(pid)

    descendants: list[int] = []
    stack = list(children_by_parent.get(root_pid, []))
    while stack:
        pid = stack.pop()
        descendants.append(pid)
        stack.extend(children_by_parent.get(pid, []))
    return descendants


def _process_parent_map() -> dict[int, int]:
    proc = Path("/proc")
    if not proc.exists():
        return {}
    parent_map: dict[int, int] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8")
            pid = int(entry.name)
            close_paren = stat.rfind(")")
            fields = stat[close_paren + 2 :].split()
            parent_map[pid] = int(fields[1])
        except (IndexError, OSError, ValueError):
            continue
    return parent_map


class ElectroBoyHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        bind_and_activate: bool = True,
        service_state: ServiceState | None = None,
    ) -> None:
        self.service_state = service_state
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)

    def server_close(self) -> None:
        if self.service_state is not None:
            self.service_state.terminate_all_sessions()
        super().server_close()


def create_server(
    root: Path | str,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> ElectroBoyHTTPServer:
    config = ServiceConfig(
        root=Path(root).expanduser().resolve(),
        host=host,
        port=port,
    )
    state = ServiceState(root=config.root)
    return ElectroBoyHTTPServer(
        (config.host, config.port),
        _handler_for(config, state),
        service_state=state,
    )


def run_service(
    root: Path | str,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> int:
    server = create_server(root, host=host, port=port)
    stop_signal: int | None = None
    previous_signal_handlers: dict[int, Any] = {}

    def handle_stop_signal(signum: int, _frame: Any) -> None:
        nonlocal stop_signal
        stop_signal = signum
        raise KeyboardInterrupt

    if threading.current_thread() is threading.main_thread():
        for stop in [signal.SIGTERM, getattr(signal, "SIGHUP", None)]:
            if stop is None:
                continue
            previous_signal_handlers[stop] = signal.getsignal(stop)
            signal.signal(stop, handle_stop_signal)

    address, actual_port = server.server_address[:2]
    display_host = host if address in {"", "0.0.0.0"} else address
    print(
        f"ElectroBoy service listening on http://{display_host}:{actual_port}",
        flush=True,
    )
    print(f"root: {Path(root).expanduser().resolve()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nElectroBoy service stopped.")
        if stop_signal is not None:
            return 128 + stop_signal
        return 130
    finally:
        for signum, previous_handler in previous_signal_handlers.items():
            signal.signal(signum, previous_handler)
        server.server_close()
    return 0


def health_payload(root: Path | str) -> dict[str, str]:
    return {
        "status": "connected",
        "service": "electroboy",
        "root": str(Path(root).expanduser().resolve()),
    }


def splash_image_bytes(resource: str = SPLASH_IMAGE_RESOURCE) -> bytes:
    return (
        resources.files(SPLASH_IMAGE_PACKAGE)
        .joinpath("assets", resource)
        .read_bytes()
    )


def project_payload(
    service_root: Path | str,
    context: BrowserContext,
    active_project_root: Path | str | None = None,
) -> dict[str, object]:
    service_root = Path(service_root).expanduser().resolve()
    active_root = (
        Path(active_project_root).expanduser().resolve()
        if active_project_root
        else None
    )
    activation_root = (
        Path(context.activation_root).expanduser().resolve()
        if context.activation_root
        else active_root
    )
    requirements_session = context.requirements_session
    requirements_running = bool(
        active_root
        and requirements_session is not None
        and requirements_session.is_active()
    )
    design_session = context.design_session
    design_running = bool(
        active_root
        and design_session is not None
        and design_session.is_active()
    )
    design_review_session = context.design_review_session
    design_review_running = bool(
        active_root
        and design_review_session is not None
        and design_review_session.is_active()
    )
    documentation_running = bool(
        active_root
        and any(session.is_active() for session in context.documentation_sessions.values())
    )
    creative_session = context.creative_session
    creative_running = bool(
        active_root
        and creative_session is not None
        and creative_session.is_active()
    )
    ad_hoc_session = context.ad_hoc_session
    ad_hoc_running = bool(
        activation_root
        and ad_hoc_session is not None
        and ad_hoc_session.is_active()
    )
    project_shell_session = context.project_shell_session
    project_shell_running = bool(
        active_root
        and project_shell_session is not None
        and project_shell_session.is_active()
    )
    workflow_stage = (
        _visible_workflow_stage(context.workflow_stage)
        if active_root and context.workflow_stage
        else ("requirements" if active_root else "project")
    )
    return {
        "context_id": context.context_id,
        "service_root": str(service_root),
        "activation_root": str(activation_root) if activation_root else None,
        "project_mode": context.project_mode,
        "active_project_root": str(active_root) if active_root else None,
        "active_repository_name": context.active_repository_name,
        "registered_repositories": context.registered_repositories,
        "workflow_stage": workflow_stage,
        "requirements_started": bool(active_root and context.requirements_started),
        "requirements_running": requirements_running,
        "requirements_approved": bool(
            active_root
            and _stage_has_approvals(
                active_root,
                STAGE_REQUIREMENTS,
                ["human-approval", "author-confirmation"],
            )
        ),
        "design_started": bool(active_root and context.design_started),
        "design_running": design_running,
        "design_review_started": bool(active_root and context.design_review_started),
        "design_review_running": design_review_running,
        "design_review_interactive": bool(
            active_root and design_review_running and context.design_review_interactive
        ),
        "stage_runs": _generic_stage_run_payload(context, active_root),
        "documentation_running": documentation_running,
        "creative_writing_running": creative_running,
        "ad_hoc_running": ad_hoc_running,
        "project_shell_running": project_shell_running,
        "design_approved": bool(
            active_root
            and _stage_has_approvals(
                active_root,
                STAGE_DESIGN_ACCEPTANCE,
                ["human-approval"],
            )
        ),
        "activate_command": (
            f"source {activation_root / '.electroboy' / 'bin' / 'activate'}"
            if activation_root and context.project_mode != "creative"
            else None
        ),
        "selected_session_id": context.selected_session_id,
        "sessions": _session_payloads(context),
        "work_items": _work_item_payload(active_root) if active_root else _empty_work_item_payload(),
        "recent_projects": _recent_project_entries(service_root),
    }


def _recent_projects_path(service_root: Path | str) -> Path:
    return Path(service_root).expanduser().resolve() / RECENT_PROJECTS_RELATIVE_PATH


def _load_recent_projects(service_root: Path | str) -> dict[str, object]:
    path = _recent_projects_path(service_root)
    if not path.exists():
        return {"schema_version": 1, "projects": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "projects": []}
    if not isinstance(data, dict):
        return {"schema_version": 1, "projects": []}
    if not isinstance(data.get("projects"), list):
        data["projects"] = []
    data["schema_version"] = 1
    return data


def _save_recent_projects(service_root: Path | str, data: dict[str, object]) -> None:
    path = _recent_projects_path(service_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _recent_project_entries(service_root: Path | str) -> list[dict[str, object]]:
    data = _load_recent_projects(service_root)
    entries: list[dict[str, object]] = []
    for entry in data.get("projects", []):
        if not isinstance(entry, dict):
            continue
        project_path = str(entry.get("path") or "").strip()
        if not project_path:
            continue
        kind = str(entry.get("kind") or "project").strip()
        if kind not in {"project", "meta", "creative"}:
            kind = "project"
        label = str(entry.get("label") or Path(project_path).name or project_path)
        entries.append(
            {
                "kind": kind,
                "label": label,
                "path": project_path,
                "opened_at": str(entry.get("opened_at") or ""),
            }
        )
    return entries[:RECENT_PROJECT_LIMIT]


def _remember_recent_project(
    service_root: Path | str,
    project_root: Path | str,
    kind: str,
) -> None:
    project_path = str(Path(project_root).expanduser().resolve())
    if kind not in {"project", "meta", "creative"}:
        kind = "project"
    data = _load_recent_projects(service_root)
    existing = [
        entry
        for entry in data.get("projects", [])
        if isinstance(entry, dict) and str(entry.get("path") or "") != project_path
    ]
    data["projects"] = [
        {
            "kind": kind,
            "label": Path(project_path).name or project_path,
            "path": project_path,
            "opened_at": utc_now(),
        },
        *existing,
    ][:RECENT_PROJECT_LIMIT]
    _save_recent_projects(service_root, data)


def _generic_stage_run_payload(
    context: BrowserContext,
    active_root: Path | None,
) -> dict[str, dict[str, object]]:
    payload: dict[str, dict[str, object]] = {}
    for stage in GENERIC_STAGE_CONFIG:
        session = context.stage_sessions.get(stage)
        running = bool(active_root and session is not None and session.is_active())
        payload[stage] = {
            "started": bool(active_root and stage in context.stage_started),
            "running": running,
            "interactive": bool(running and session is not None and session.interactive),
        }
    return payload


def _session_payloads(context: BrowserContext) -> list[dict[str, object]]:
    selected_session_id = context.selected_session_id
    payloads: list[dict[str, object]] = []
    for session in [
        context.requirements_session,
        context.design_session,
        context.design_review_session,
        *context.stage_sessions.values(),
        *context.documentation_sessions.values(),
        context.creative_session,
        context.ad_hoc_session,
    ]:
        if session is None:
            continue
        session_id = str(getattr(session, "session_id", f"legacy-{id(session)}"))
        if hasattr(session, "payload"):
            payloads.append(
                session.payload(selected=session_id == selected_session_id)  # type: ignore[attr-defined]
            )
            continue
        payloads.append(
            {
                "session_id": session_id,
                "kind": getattr(session, "kind", "agent"),
                "label": getattr(session, "label", "agent"),
                "status": "running" if session.is_active() else "completed",
                "returncode": getattr(session, "returncode", None),
                "interactive": bool(getattr(session, "interactive", True)),
                "locks": sorted(getattr(session, "lock_names", [])),
                "selected": session_id == selected_session_id,
                "created_at": getattr(session, "created_at", ""),
                "command": list(getattr(session, "command", [])),
                "metadata": dict(getattr(session, "metadata", {}) or {}),
            }
        )
    return payloads


def _empty_work_item_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "active_collection_id": None,
        "active_feature_slug": None,
        "active_bug_slug": None,
        "collections": [],
        "features": [],
        "bugs": [],
    }


def _work_item_payload(project_root: Path) -> dict[str, object]:
    registry = _load_work_item_registry(project_root)
    feature = _current_feature_record(project_root)
    bug = _current_bug_record(project_root)
    if feature is not None:
        existing = _feature_by_slug(registry, str(feature.get("slug") or ""))
        collection = _ensure_collection_for_feature(
            registry,
            (
                str(existing.get("collection_id"))
                if existing and existing.get("collection_id")
                else None
            ),
            parent_slug=(
                str(existing.get("parent_slug"))
                if existing and existing.get("parent_slug")
                else None
            ),
        )
        _upsert_feature_record(
            registry,
            feature,
            collection_id=str(collection["id"]),
            parent_slug=(
                str(existing.get("parent_slug"))
                if existing and existing.get("parent_slug")
                else None
            ),
        )
        registry["active_collection_id"] = collection["id"]
        registry["active_feature_slug"] = feature.get("slug")
    if bug is not None:
        _upsert_bug_record(registry, bug)
        registry["active_bug_slug"] = bug.get("slug")
    return {
        "schema_version": 1,
        "active_collection_id": registry.get("active_collection_id"),
        "active_feature_slug": registry.get("active_feature_slug"),
        "active_bug_slug": registry.get("active_bug_slug"),
        "collections": _registry_list(registry, "collections"),
        "features": _registry_list(registry, "features"),
        "bugs": _registry_list(registry, "bugs"),
    }


def _registry_list(
    registry: dict[str, object],
    key: str,
) -> list[dict[str, object]]:
    values = registry.get(key)
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def _load_work_item_registry(project_root: Path) -> dict[str, object]:
    path = project_root / WORK_ITEM_REGISTRY_RELATIVE_PATH
    if not path.exists():
        return {
            **_empty_work_item_payload(),
            "collections": [_default_feature_collection()],
            "active_collection_id": "default",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    registry = {
        **_empty_work_item_payload(),
        **data,
    }
    collections = _registry_list(registry, "collections")
    if not collections:
        collections = [_default_feature_collection()]
    elif _feature_collection_by_id(registry, "default") is None:
        collections.insert(0, _default_feature_collection())
    registry["collections"] = collections
    registry["features"] = _registry_list(registry, "features")
    registry["bugs"] = _registry_list(registry, "bugs")
    if not registry.get("active_collection_id"):
        registry["active_collection_id"] = collections[0].get("id")
    return registry


def _save_work_item_registry(project_root: Path, registry: dict[str, object]) -> None:
    path = project_root / WORK_ITEM_REGISTRY_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _default_feature_collection() -> dict[str, object]:
    return {
        "id": "default",
        "name": "Default",
        "feature_slugs": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def _upsert_feature_collection(
    registry: dict[str, object],
    name: str,
) -> dict[str, object]:
    collections = _registry_list(registry, "collections")
    collection_id = _slugify_work_item(name)
    existing = _feature_collection_by_id(registry, collection_id)
    if existing is not None:
        existing["name"] = name
        existing["updated_at"] = utc_now()
        return existing
    collection = {
        "id": collection_id,
        "name": name,
        "feature_slugs": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    collections.append(collection)
    registry["collections"] = collections
    return collection


def _feature_collection_by_id(
    registry: dict[str, object],
    collection_id: str,
) -> dict[str, object] | None:
    for collection in _registry_list(registry, "collections"):
        if collection.get("id") == collection_id:
            return collection
    return None


def _ensure_collection_for_feature(
    registry: dict[str, object],
    collection_id: str | None,
    *,
    parent_slug: str | None = None,
) -> dict[str, object]:
    if collection_id:
        collection = _feature_collection_by_id(registry, collection_id)
        if collection is not None:
            return collection
    if parent_slug:
        parent = _feature_by_slug(registry, parent_slug)
        if parent and parent.get("collection_id"):
            collection = _feature_collection_by_id(
                registry,
                str(parent.get("collection_id")),
            )
            if collection is not None:
                return collection
    active_id = registry.get("active_collection_id")
    if active_id:
        collection = _feature_collection_by_id(registry, str(active_id))
        if collection is not None:
            return collection
    collections = _registry_list(registry, "collections")
    if collections:
        return collections[0]
    collection = _default_feature_collection()
    registry["collections"] = [collection]
    registry["active_collection_id"] = collection["id"]
    return collection


def _feature_by_slug(
    registry: dict[str, object],
    slug: str,
) -> dict[str, object] | None:
    for feature in _registry_list(registry, "features"):
        if feature.get("slug") == slug:
            return feature
    return None


def _bug_by_slug(
    registry: dict[str, object],
    slug: str,
) -> dict[str, object] | None:
    for bug in _registry_list(registry, "bugs"):
        if bug.get("slug") == slug:
            return bug
    return None


def _upsert_feature_record(
    registry: dict[str, object],
    record: dict[str, object],
    *,
    collection_id: str,
    parent_slug: str | None,
) -> None:
    slug = str(record.get("slug") or "").strip()
    if not slug:
        return
    features = [
        feature
        for feature in _registry_list(registry, "features")
        if feature.get("slug") != slug
    ]
    feature = dict(record)
    feature["collection_id"] = collection_id
    feature["parent_slug"] = parent_slug
    feature["updated_at"] = utc_now()
    features.append(feature)
    registry["features"] = sorted(
        features,
        key=lambda item: str(item.get("name") or item.get("slug") or ""),
    )
    collection = _ensure_collection_for_feature(registry, collection_id)
    feature_slugs = [
        value
        for value in collection.get("feature_slugs", [])
        if isinstance(value, str) and value != slug
    ]
    feature_slugs.append(slug)
    collection["feature_slugs"] = feature_slugs
    collection["updated_at"] = utc_now()


def _upsert_bug_record(
    registry: dict[str, object],
    record: dict[str, object],
) -> None:
    slug = str(record.get("slug") or "").strip()
    if not slug:
        return
    bugs = [
        bug
        for bug in _registry_list(registry, "bugs")
        if bug.get("slug") != slug
    ]
    bug = dict(record)
    bug["updated_at"] = utc_now()
    bugs.append(bug)
    registry["bugs"] = sorted(
        bugs,
        key=lambda item: str(item.get("title") or item.get("slug") or ""),
    )


def _current_feature_record(project_root: Path) -> dict[str, object] | None:
    store = StateStore(project_root)
    run_id = store.current_run_id()
    if not run_id:
        return None
    return read_feature_record(project_root, run_id)


def _current_bug_record(project_root: Path) -> dict[str, object] | None:
    store = StateStore(project_root)
    run_id = store.current_run_id()
    if not run_id:
        return None
    path = store.run_dir(run_id) / "bug.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _write_current_bug_record(project_root: Path, record: dict[str, object]) -> None:
    store = StateStore(project_root)
    run_id = store.current_run_id()
    if not run_id:
        raise StateError("project has no active run")
    path = store.run_dir(run_id) / "bug.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _feature_record_label(record: dict[str, object] | None) -> str:
    if not record:
        return "feature"
    return str(
        record.get("name")
        or record.get("title")
        or record.get("slug")
        or "feature"
    )


def _bug_record_label(record: dict[str, object] | None) -> str:
    if not record:
        return "bug"
    return str(record.get("title") or record.get("slug") or "bug")


def _run_feature_start_context(
    project_root: Path,
    *,
    title: str,
    feature_name: str | None,
    amend: bool,
    branch: bool,
    stash_subrepo_changes: bool = False,
    branch_name: str | None = None,
) -> str:
    from .cli import _cmd_feature_start

    args = SimpleNamespace(
        title_or_issue_url=title,
        feature_name=feature_name,
        amend=amend,
        branch=(branch_name or "") if branch else None,
        stash_subrepo_changes=stash_subrepo_changes,
    )
    return _run_orchestrator_command(project_root, _cmd_feature_start, args)


def _run_bug_start_context(
    project_root: Path,
    *,
    issue_reference: str,
    branch: bool,
    stash_subrepo_changes: bool = False,
) -> str:
    from .cli import _cmd_bug_start

    args = SimpleNamespace(
        issue_reference=issue_reference,
        provider=None,
        branch="" if branch else None,
        stash_subrepo_changes=stash_subrepo_changes,
    )
    return _run_orchestrator_command(project_root, _cmd_bug_start, args)


def _run_orchestrator_command(
    project_root: Path,
    command: Callable[[StateStore, Any], int],
    args: Any,
) -> str:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = command(StateStore(project_root), args)
    output = "\n".join(
        part.strip()
        for part in [stderr.getvalue(), stdout.getvalue()]
        if part.strip()
    )
    if code != 0:
        raise AgentSessionError(output or "work item command failed")
    return output


def _run_electroboy_cli_command(project_root: Path, args: list[str]) -> str:
    from .cli import main

    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(["--root", str(project_root), *args])
    output = "\n".join(
        part.strip()
        for part in [stderr.getvalue(), stdout.getvalue()]
        if part.strip()
    )
    if code != 0:
        raise AgentSessionError(output or f"electroboy {' '.join(args)} failed")
    return output


def _work_item_error_payload(error: BaseException) -> dict[str, object]:
    message = str(error)
    payload: dict[str, object] = {"error": message}
    if "nested repository changes require stashing" in message:
        payload["stash_subrepo_changes_required"] = True
    return payload


def _generic_stage_config(stage: str) -> dict[str, object]:
    try:
        return GENERIC_STAGE_CONFIG[stage]
    except KeyError as error:
        raise AgentSessionError(f"unsupported workflow stage: {stage}") from error


def _stage_display_label(stage: str) -> str:
    return str(
        _generic_stage_config(stage).get("artifact_title")
        or stage.replace("-", " ")
    ).lower()


def _generic_stage_command(
    root: Path,
    stage: str,
    *,
    force: bool = False,
    reason: str | None = None,
    interactive: bool = False,
) -> list[str]:
    config = _generic_stage_config(stage)
    command_parts = [str(config["command"])]
    if force:
        command_parts.append("--force")
    if reason and bool(config.get("reason_arg")):
        command_parts.extend(["--reason", reason])
    if interactive and bool(config.get("interactive_arg")):
        command_parts.append("--interactive")
    return _electroboy_command(root, command_parts)


def _generic_agent_route(path: str) -> tuple[str, str] | None:
    prefix = "/api/agents/"
    if not path.startswith(prefix):
        return None
    suffix = path[len(prefix):]
    for stage in GENERIC_STAGE_CONFIG:
        stage_prefix = f"{stage}/"
        if suffix.startswith(stage_prefix):
            return stage, suffix[len(stage_prefix):]
    return None


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
    slug = "".join(chars).strip("-")
    return slug or "default"


def _visible_workflow_stage(stage: str) -> str:
    return DURABLE_STAGE_OWNERS.get(stage, APPROVAL_STAGE_OWNERS.get(stage, stage))


def _active_workflow_stage(project_root: Path | str) -> str:
    try:
        manifest = StateStore(project_root).load_current_manifest()
    except OSError as error:
        raise StateError(f"could not read ElectroBoy project: {error}") from error
    return _visible_workflow_stage(manifest.active_stage)


def _stage_has_approvals(
    project_root: Path | str,
    stage: str,
    approval_types: list[str],
) -> bool:
    try:
        approvals = StateStore(project_root).read_approvals()
    except (OSError, StateError):
        return False
    return all(
        any(
            approval.get("stage") == stage
            and approval.get("approval_type") == approval_type
            for approval in approvals
        )
        for approval_type in approval_types
    )


def workflow_payload(active_project_root: Path | str | None = None) -> dict[str, object]:
    return {
        "stages": [
            {
                "id": stage,
                "label": stage,
                "operations": _stage_operations(stage, active_project_root),
            }
            for stage in WORKFLOW_STAGES
        ]
    }


def browse_directories(path: Path | str, *, show_hidden: bool = False) -> dict[str, object]:
    directory = Path(path).expanduser().resolve()
    if not directory.exists():
        raise StateError(f"directory does not exist: {directory}")
    if not directory.is_dir():
        raise StateError(f"path is not a directory: {directory}")

    try:
        children = sorted(
            [
                child
                for child in directory.iterdir()
                if child.is_dir() and _browser_entry_visible(child, show_hidden)
            ],
            key=lambda child: child.name.lower(),
        )
    except OSError as error:
        raise StateError(f"could not read directory: {error}") from error
    return {
        "path": str(directory),
        "parent": str(directory.parent) if directory.parent != directory else None,
        "entries": [
            {
                "name": child.name,
                "path": str(child),
            }
            for child in children[:200]
        ],
    }


def browse_files(path: Path | str, *, show_hidden: bool = False) -> dict[str, object]:
    directory = Path(path).expanduser().resolve()
    if not directory.exists():
        raise StateError(f"directory does not exist: {directory}")
    if not directory.is_dir():
        raise StateError(f"path is not a directory: {directory}")

    try:
        children = sorted(
            [
                child
                for child in directory.iterdir()
                if child.is_dir() or child.is_file()
                if _browser_entry_visible(child, show_hidden)
            ],
            key=lambda child: (not child.is_dir(), child.name.lower()),
        )
    except OSError as error:
        raise StateError(f"could not read directory: {error}") from error
    return {
        "path": str(directory),
        "parent": str(directory.parent) if directory.parent != directory else None,
        "entries": [
            {
                "name": child.name,
                "path": str(child),
                "type": "directory" if child.is_dir() else "file",
            }
            for child in children[:300]
        ],
    }


def browse_markdown_files(
    path: Path | str,
    *,
    show_hidden: bool = False,
) -> dict[str, object]:
    directory = Path(path).expanduser().resolve()
    if not directory.exists():
        raise StateError(f"directory does not exist: {directory}")
    if not directory.is_dir():
        raise StateError(f"path is not a directory: {directory}")

    try:
        children = sorted(
            [
                child
                for child in directory.iterdir()
                if child.is_dir()
                or (child.is_file() and child.suffix.lower() == ".md")
                if _browser_entry_visible(child, show_hidden)
            ],
            key=lambda child: (not child.is_dir(), child.name.lower()),
        )
    except OSError as error:
        raise StateError(f"could not read directory: {error}") from error
    return {
        "path": str(directory),
        "parent": str(directory.parent) if directory.parent != directory else None,
        "entries": [
            {
                "name": child.name,
                "path": str(child),
                "type": "directory" if child.is_dir() else "file",
            }
            for child in children[:300]
        ],
    }


def _browser_entry_visible(path: Path, show_hidden: bool) -> bool:
    return show_hidden or not path.name.startswith(".")


def initialize_project(project_root: Path | str):
    from .cli import (
        _init_git_repository,
        _write_project_bin,
        _write_project_config,
        _write_project_gitignore,
        _write_project_runtime,
    )

    project_root = Path(project_root).expanduser().resolve()
    project_root.mkdir(parents=True, exist_ok=True)
    _init_git_repository(project_root)
    ArtifactManager(project_root).init_templates()
    _write_project_config(project_root)
    _write_project_gitignore(project_root)
    _write_project_runtime(project_root)
    _write_project_bin(project_root)

    store = StateStore(project_root)
    return store.init_run()


def initialize_meta_project(path: Path | str) -> tuple[Path, dict[str, object]]:
    from .cli import (
        _meta_registry_file,
        _read_meta_registry,
        _write_meta_environment,
        _write_meta_registry,
    )

    meta_root = _resolve_project_path(str(path))
    meta_root.mkdir(parents=True, exist_ok=True)
    _write_meta_environment(meta_root)
    registry_exists = _meta_registry_file(meta_root).exists()
    registry = _read_meta_registry(meta_root)
    if not registry_exists:
        _write_meta_registry(meta_root, registry)
    return meta_root, registry


def _resolve_project_path(path: str) -> Path:
    path = path.strip()
    if not path:
        raise StateError("project path is required")
    return Path(path).expanduser().resolve()


def _is_meta_project_path(path: str | Path) -> bool:
    try:
        project_root = Path(path).expanduser().resolve()
    except OSError:
        return False
    return (project_root / META_REGISTRY_RELATIVE_PATH).exists()


def _existing_meta_context(path: str | Path) -> dict[str, object]:
    meta_root = _resolve_project_path(str(path))
    if not meta_root.exists():
        raise StateError(f"meta-project directory does not exist: {meta_root}")
    if not meta_root.is_dir():
        raise StateError(f"meta-project path is not a directory: {meta_root}")
    if not _is_meta_project_path(meta_root):
        raise StateError(
            "no ElectroBoy meta-project exists at this path; create it first"
        )
    return _meta_context(meta_root)


def _meta_context(meta_root: Path) -> dict[str, object]:
    from .cli import _meta_repository_by_name, _read_meta_registry

    registry = _read_meta_registry(meta_root)
    repositories = _meta_repository_payloads(registry)
    active_name = str(registry.get("active") or "")
    active_project_root: Path | None = None
    workflow_stage: str | None = None
    if active_name:
        record = _meta_repository_by_name(registry, active_name)
        if record is not None:
            candidate = Path(str(record.get("path", ""))).expanduser().resolve()
            if (
                candidate.exists()
                and candidate.is_dir()
                and StateStore(candidate).current_run_id()
            ):
                active_project_root = candidate
                workflow_stage = _active_workflow_stage(candidate)
    return {
        "meta_root": meta_root,
        "active_project_root": active_project_root,
        "active_repository_name": active_name or None,
        "registered_repositories": repositories,
        "workflow_stage": workflow_stage,
    }


def _meta_repository_payloads(registry: dict[str, object]) -> list[dict[str, object]]:
    from .cli import _meta_repositories

    return [
        {
            "name": str(repo.get("name") or ""),
            "path": str(repo.get("path") or ""),
        }
        for repo in _meta_repositories(registry)
    ]


def _add_meta_repository(meta_root: Path, path: str) -> dict[str, object]:
    from .cli import (
        _read_meta_registry,
        _register_meta_repository,
        _resolve_existing_repo_path,
    )

    registry = _read_meta_registry(meta_root)
    repo_path = _resolve_existing_repo_path(meta_root, path)
    _register_meta_repository(meta_root, repo_path, registry)
    return _meta_context(meta_root)


def _start_meta_repository(meta_root: Path, repository: str) -> dict[str, object]:
    from .cli import (
        _ensure_target_pipeline_project,
        _read_meta_registry,
        _register_meta_repository,
        _resolve_meta_repository,
        _write_meta_registry,
    )

    repository = repository.strip()
    if not repository:
        raise StateError("repository is required")
    registry = _read_meta_registry(meta_root)
    repo_path, record = _resolve_meta_repository(meta_root, registry, repository)
    registry, record = _register_meta_repository(meta_root, repo_path, registry)
    registry["active"] = record["name"]
    _write_meta_registry(meta_root, registry)
    _ensure_target_pipeline_project(repo_path)
    return _meta_context(meta_root)


def _remove_meta_repository(meta_root: Path, repository: str) -> dict[str, object]:
    from .cli import (
        _candidate_repo_path,
        _meta_repository_by_name,
        _meta_repositories,
        _read_meta_registry,
        _write_meta_registry,
    )

    repository = repository.strip()
    if not repository:
        raise StateError("repository is required")
    registry = _read_meta_registry(meta_root)
    record = _meta_repository_by_name(registry, repository)
    if record is None:
        candidate_path = _candidate_repo_path(meta_root, repository)
        for repo in _meta_repositories(registry):
            repo_path = Path(str(repo.get("path", ""))).expanduser().resolve()
            if repo_path == candidate_path:
                record = repo
                break
    if record is None:
        raise StateError(f"repository is not registered: {repository}")
    name = str(record.get("name") or "")
    path = Path(str(record.get("path", ""))).expanduser().resolve()
    remaining = [
        repo
        for repo in _meta_repositories(registry)
        if str(repo.get("name") or "") != name
        and Path(str(repo.get("path", ""))).expanduser().resolve() != path
    ]
    registry["repositories"] = remaining
    if registry.get("active") == name:
        registry["active"] = None
    _write_meta_registry(meta_root, registry)
    return _meta_context(meta_root)


def _existing_project_root(path: str) -> Path:
    project_root = _resolve_project_path(path)
    if not project_root.exists():
        raise StateError(f"project directory does not exist: {project_root}")
    if not project_root.is_dir():
        raise StateError(f"project path is not a directory: {project_root}")
    try:
        current_run_id = StateStore(project_root).current_run_id()
    except OSError as error:
        raise StateError(f"could not read ElectroBoy project: {error}") from error
    if not current_run_id:
        raise StateError(
            "no ElectroBoy project exists at this path; create it first"
        )
    return project_root


def _existing_creative_project_root(path: str) -> Path:
    project_root = _resolve_project_path(path)
    if not project_root.exists():
        raise StateError(f"project directory does not exist: {project_root}")
    if not project_root.is_dir():
        raise StateError(f"project path is not a directory: {project_root}")
    return project_root


def _stage_operations(
    stage: str,
    active_project_root: Path | str | None,
) -> list[str]:
    if stage == "project":
        operations = ["Open", "Create"]
        if active_project_root:
            operations.append("Deactivate")
        return operations
    if stage == "requirements" and active_project_root:
        return [
            "Set stage",
            "Start",
            "Approve",
            "Skip approval",
            "Open requirements",
        ]
    if stage == "design" and active_project_root:
        return ["Set stage", "Start", "Complete", "Open design"]
    if stage == "design-review" and active_project_root:
        return [
            "Set stage",
            "Run automatic review",
            "Run interactive review",
            "Stop review",
            "Approve",
            "Skip approval",
        ]
    if stage == "implementation-plan" and active_project_root:
        return [
            "Set stage",
            "Start",
            "Approve",
            "Skip approval",
            "Open implementation plan",
        ]
    if stage == "code" and active_project_root:
        return [
            "Set stage",
            "Start automatic",
            "Start interactive",
            "Stop",
            "Approve",
            "Skip approval",
            "Open implementation report",
        ]
    if stage == "test-plan" and active_project_root:
        return [
            "Set stage",
            "Start",
            "Approve",
            "Skip approval",
            "Open test plan",
        ]
    if stage == "validate" and active_project_root:
        return [
            "Set stage",
            "Start automatic",
            "Start interactive",
            "Stop",
            "Approve",
            "Skip approval",
            "Open validation report",
        ]
    return []


def _reopen_requirements_for_restart(project_root: Path) -> None:
    store = StateStore(project_root)
    manifest = store.load_current_manifest()
    from .cli import _is_backward_stage_request, _record_stage_reopen

    if _is_backward_stage_request(manifest.active_stage, STAGE_REQUIREMENTS):
        _record_stage_reopen(
            store=store,
            manifest=manifest,
            target_stage=STAGE_REQUIREMENTS,
            reason="Requirements authoring restarted from the GUI.",
            actor="human-operator",
            action="gui-requirements-restarted",
            summary="Reopened requirements authoring from the GUI.",
        )
        return
    store.append_activity(
        ActivityEvent(
            actor="human-operator",
            stage=STAGE_REQUIREMENTS,
            action="gui-requirements-restarted",
            summary="Restarted requirements authoring from the GUI.",
        )
    )


def _reopen_design_for_restart(project_root: Path) -> None:
    store = StateStore(project_root)
    manifest = store.load_current_manifest()
    from .cli import _is_backward_stage_request, _record_stage_reopen

    if _is_backward_stage_request(manifest.active_stage, STAGE_DESIGN):
        _record_stage_reopen(
            store=store,
            manifest=manifest,
            target_stage=STAGE_DESIGN,
            reason="Design authoring restarted from the GUI.",
            actor="human-operator",
            action="gui-design-restarted",
            summary="Reopened design authoring from the GUI.",
        )
        return
    store.append_activity(
        ActivityEvent(
            actor="human-operator",
            stage=STAGE_DESIGN,
            action="gui-design-restarted",
            summary="Restarted design authoring from the GUI.",
        )
    )


def _record_requirements_complete(project_root: Path, *, skipped: bool = False) -> None:
    store = StateStore(project_root)
    manifest = store.load_current_manifest()
    action = (
        "gui-requirements-approval-skipped"
        if skipped
        else "gui-requirements-authoring-completed"
    )
    summary = (
        "Skipped explicit requirements approval from the GUI and advanced "
        "with a forced approval warning."
        if skipped
        else "Completed requirements authoring and approved the requirements baseline."
    )
    store.append_activity(
        ActivityEvent(
            actor="human-operator",
            stage=STAGE_REQUIREMENTS,
            action=action,
            summary=summary,
            inputs=[manifest.active_stage],
        )
    )


def _record_design_complete(project_root: Path) -> None:
    store = StateStore(project_root)
    manifest = store.load_current_manifest()
    store.append_activity(
        ActivityEvent(
            actor="human-operator",
            stage=STAGE_DESIGN,
            action="gui-design-authoring-completed",
            summary="Completed design authoring and moved to design review.",
            inputs=[manifest.active_stage],
        )
    )


def _should_force_completed_requirements_approval(store: StateStore) -> bool:
    from .cli import _has_successful_agent_event

    if _has_successful_agent_event(store, "design_author", STAGE_REQUIREMENTS):
        return False
    completion_actions = {
        "gui-requirements-authoring-completed",
        "gui-requirements-authoring-skipped",
        "gui-requirements-approval-skipped",
    }
    return any(
        event.get("actor") == "human-operator"
        and event.get("stage") == STAGE_REQUIREMENTS
        and event.get("action") in completion_actions
        for event in store.read_activity()
    )


def requirements_document_html(
    project_root: Path | str,
    *,
    embedded: bool = False,
    zoom_percent: int = 100,
) -> tuple[str, HTTPStatus]:
    relative_path = _resolved_artifact_relative_path(
        project_root,
        "docs/requirements.md",
    )
    return markdown_document_html(
        project_root,
        relative_path,
        "Requirements",
        "Requirements document does not exist yet.",
        embedded=embedded,
        zoom_percent=zoom_percent,
    )


def design_document_html(project_root: Path | str) -> tuple[str, HTTPStatus]:
    relative_path = _resolved_artifact_relative_path(
        project_root,
        "docs/detailed-design.md",
    )
    return markdown_document_html(
        project_root,
        relative_path,
        "Design",
        "Design document does not exist yet.",
    )


def design_review_document_html(project_root: Path | str) -> tuple[str, HTTPStatus]:
    relative_path = _resolved_artifact_relative_path(
        project_root,
        "docs/design-review.md",
    )
    return markdown_document_html(
        project_root,
        relative_path,
        "Design Review",
        "Design review document does not exist yet.",
    )


def stage_document_html(
    project_root: Path | str,
    stage: str,
) -> tuple[str, HTTPStatus]:
    config = _generic_stage_config(stage)
    title = str(config["artifact_title"])
    relative_path = _resolved_artifact_relative_path(
        project_root,
        str(config["artifact_path"]),
    )
    return markdown_document_html(
        project_root,
        relative_path,
        title,
        f"{title} document does not exist yet.",
    )


def document_target_html(
    project_root: Path | str,
    relative_path: str,
    *,
    title: str | None = None,
    embedded: bool = False,
    create_missing: bool = False,
    zoom_percent: int = 100,
) -> tuple[str, HTTPStatus]:
    normalized_path = (
        _ensure_document_target(project_root, relative_path)
        if create_missing
        else _document_target_path(project_root, relative_path)[0]
    )
    display_title = title or normalized_path
    return markdown_document_html(
        project_root,
        normalized_path,
        display_title,
        f"{normalized_path} document does not exist yet.",
        embedded=embedded,
        zoom_percent=zoom_percent,
    )


def artifact_editor_html(
    project_root: Path | str,
    artifact: str,
    requested_path: str = "",
    *,
    title: str | None = None,
    create_missing: bool = False,
    context_id: str = "",
    rich_editor: bool = False,
    editor_font_size: int | None = None,
) -> tuple[str, HTTPStatus]:
    """Return a live editor page for a Markdown or structured artifact."""

    project_root = Path(project_root).expanduser().resolve()
    edit_data = _artifact_edit_payload(
        project_root,
        artifact,
        requested_path,
        title=title,
        create_missing=create_missing,
        rich_editor=rich_editor,
        editor_font_size=editor_font_size,
    )
    edit_data["context_id"] = context_id
    page = _artifact_editor_page(edit_data)
    return page, HTTPStatus.OK


def markdown_document_html(
    project_root: Path | str,
    relative_path: str,
    title: str,
    missing_message: str,
    *,
    embedded: bool = False,
    zoom_percent: int = 100,
) -> tuple[str, HTTPStatus]:
    project_root = Path(project_root).expanduser().resolve()
    document_path = project_root / relative_path
    if document_path.exists():
        text = document_path.read_text(encoding="utf-8")
        body = _render_markdown(text)
        status = HTTPStatus.OK
    else:
        body = f"<p>{html.escape(missing_message)}</p>"
        status = HTTPStatus.NOT_FOUND
    main_max_width = "none" if embedded else "880px"
    main_margin = "0" if embedded else "0 auto"
    main_padding = "16px" if embedded else "40px 24px 64px"
    article_padding = "18px" if embedded else "28px"
    article_radius = "0" if embedded else "8px"
    article_border = "0" if embedded else "1px solid var(--doc-border)"
    zoom_percent = _clamp_document_zoom(zoom_percent)
    document_font_size = 16 * (zoom_percent / 100)
    mermaid_script = _mermaid_script(body)
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: dark;
      --doc-bg: #10141f;
      --doc-surface: #10141f;
      --doc-text: #e7edf7;
      --doc-heading: #ffffff;
      --doc-link: #66d9e8;
      --doc-muted: #aab8cf;
      --doc-border: #2a3142;
      --doc-code-bg: #151b29;
      --doc-code-text: #e7edf7;
      --doc-table-head: #151b29;
      --doc-accent: #8bd8ca;
      --doc-font-size: {document_font_size:.2f}px;
    }}
    html {{
      background: var(--doc-bg);
    }}
    body {{
      margin: 0;
      background: var(--doc-bg);
      color: var(--doc-text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: var(--doc-font-size);
      line-height: 1.55;
    }}
    main {{
      max-width: {main_max_width};
      margin: {main_margin};
      padding: {main_padding};
    }}
    article {{
      background: var(--doc-surface);
      border: {article_border};
      border-radius: {article_radius};
      color: var(--doc-text);
      padding: {article_padding};
    }}
    article, article :where(p, li, td, dd, strong, em, summary, details, figcaption) {{
      color: var(--doc-text);
    }}
    h1, h2, h3, h4, h5, h6 {{
      color: var(--doc-heading);
      line-height: 1.2;
    }}
    a {{
      color: var(--doc-link);
    }}
    blockquote {{
      margin-left: 0;
      border-left: 4px solid var(--doc-accent);
      color: var(--doc-muted);
      padding-left: 14px;
    }}
    hr {{
      border: 0;
      border-top: 1px solid var(--doc-border);
    }}
    img {{
      max-width: 100%;
      height: auto;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
    }}
    th, td {{
      border: 1px solid var(--doc-border);
      padding: 8px 10px;
    }}
    th {{
      background: var(--doc-table-head);
      color: var(--doc-heading);
    }}
    pre, code {{
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    }}
    code {{
      color: var(--doc-code-text);
      background: var(--doc-code-bg);
      border-radius: 4px;
      padding: 1px 4px;
    }}
    pre {{
      overflow: auto;
      padding: 12px;
      background: var(--doc-code-bg);
      color: var(--doc-code-text);
      border: 1px solid var(--doc-border);
      border-radius: 6px;
    }}
    pre code {{
      background: transparent;
      border-radius: 0;
      padding: 0;
    }}
    .mermaid {{
      display: flex;
      justify-content: center;
      overflow: auto;
      margin: 16px 0;
      padding: 14px;
      border: 1px solid var(--doc-border);
      border-radius: 6px;
      background: var(--doc-code-bg);
      cursor: zoom-in;
      transition: border-color 120ms ease, background 120ms ease;
    }}
    .mermaid:hover,
    .mermaid:focus-visible {{
      border-color: var(--doc-accent);
      outline: none;
    }}
    .mermaid svg {{
      max-width: 100%;
      height: auto;
    }}
  </style>
  {mermaid_script}
</head>
<body>
  <main>
    <article>
      {body}
    </article>
  </main>
</body>
</html>
"""
    return page, status


def _clamp_document_zoom(value: int) -> int:
    stepped = int(((value + 5) // 10) * 10)
    return max(70, min(180, stepped))


def _document_zoom_from_params(params: dict[str, list[str]]) -> int:
    raw = params.get("zoom", ["100"])[0]
    try:
        return _clamp_document_zoom(int(raw))
    except (TypeError, ValueError):
        return 100


def _clamp_artifact_editor_font_size(value: object) -> int:
    try:
        requested = int(value) if value is not None else 16
    except (TypeError, ValueError):
        requested = 16
    return max(11, min(28, requested))


def _artifact_editor_font_size_from_params(params: dict[str, list[str]]) -> int:
    raw_font_size = (params.get("font_size") or [""])[0]
    if raw_font_size:
        return _clamp_artifact_editor_font_size(raw_font_size)
    raw_zoom = (params.get("document_zoom") or params.get("zoom") or [""])[0]
    try:
        zoom = _clamp_document_zoom(int(raw_zoom))
    except (TypeError, ValueError):
        zoom = 100
    return _clamp_artifact_editor_font_size(round(16 * (zoom / 100)))


def _normalize_document_target_path(relative_path: str) -> str:
    raw = relative_path.strip().replace("\\", "/")
    if not raw:
        raise StateError("document path is required")
    path = Path(raw)
    if path.is_absolute():
        raise StateError("document path must be relative")
    if any(part in {"..", ""} for part in path.parts):
        raise StateError("document path cannot escape the project")
    if path.suffix.lower() != ".md":
        raise StateError("document path must be a markdown file")
    return path.as_posix()


def _ensure_document_target(project_root: Path | str, relative_path: str) -> str:
    normalized_path, document_path = _document_target_path(project_root, relative_path)
    if not document_path.exists():
        document_path.parent.mkdir(parents=True, exist_ok=True)
        document_path.write_text(
            _document_starter_markdown(normalized_path),
            encoding="utf-8",
        )
    if not document_path.is_file():
        raise StateError("document path must refer to a file")
    if not document_path.read_text(encoding="utf-8").strip():
        document_path.write_text(
            _document_starter_markdown(normalized_path),
            encoding="utf-8",
        )
    return normalized_path


def _document_starter_markdown(relative_path: str) -> str:
    title = _document_starter_title(relative_path)
    return f"# {title}\n\n## Overview\n\n## Notes\n"


def _document_starter_title(relative_path: str) -> str:
    stem = Path(relative_path).stem.strip()
    if not stem:
        return "Document"
    if stem.lower() == "readme":
        return "README"
    if stem.lower() == "api":
        return "API"
    return stem.replace("-", " ").replace("_", " ").title()


def _artifact_edit_payload(
    project_root: Path,
    artifact: str,
    requested_path: str,
    *,
    title: str | None = None,
    create_missing: bool = False,
    rich_editor: bool = False,
    editor_font_size: int | None = None,
) -> dict[str, object]:
    artifact = artifact.strip()
    editor_font_size = _clamp_artifact_editor_font_size(editor_font_size)
    structured_artifact, markdown_path = _structured_artifact_for_edit_request(
        project_root,
        artifact,
        requested_path,
    )
    if structured_artifact:
        records, jsonl_path = _ensure_structured_edit_records(
            project_root,
            structured_artifact,
            markdown_path,
        )
        return {
            "mode": "structured",
            "artifact": artifact,
            "artifact_name": structured_artifact,
            "path": requested_path,
            "title": title or ARTIFACT_TITLES[structured_artifact],
            "markdown_path": markdown_path,
            "jsonl_path": jsonl_path,
            "records": records,
            "list_fields": sorted(ARTIFACT_EDITOR_LIST_FIELDS),
            "json_fields": sorted(ARTIFACT_EDITOR_JSON_FIELDS),
            "editor_font_size": editor_font_size,
        }

    if artifact == "document":
        markdown_path = (
            _ensure_document_target(project_root, requested_path)
            if create_missing
            else _document_target_path(project_root, requested_path)[0]
        )
        document_path = _document_target_path(project_root, markdown_path)[1]
    else:
        document_path = _artifact_event_document_path(
            project_root,
            artifact,
            requested_path,
        )
        markdown_path = document_path.relative_to(project_root).as_posix()
    if not document_path.exists():
        document_path.parent.mkdir(parents=True, exist_ok=True)
        document_path.write_text(
            _document_starter_markdown(markdown_path),
            encoding="utf-8",
        )
    return {
        "mode": "markdown",
        "artifact": artifact,
        "path": requested_path,
        "title": title or markdown_path,
        "markdown_path": markdown_path,
        "markdown": document_path.read_text(encoding="utf-8"),
        "rich_editor": bool(rich_editor and artifact == "document"),
        "editor_font_size": editor_font_size,
    }


def _structured_artifact_for_edit_request(
    project_root: Path,
    artifact: str,
    requested_path: str,
) -> tuple[str | None, str]:
    if artifact == "requirements":
        structured_artifact = "requirements"
        return structured_artifact, artifact_markdown_path(project_root, structured_artifact)
    if artifact == "route":
        default_path = ARTIFACT_EVENT_ROUTE_PATHS.get(requested_path, "")
        structured_artifact = STRUCTURED_ARTIFACT_BY_MARKDOWN_PATH.get(default_path)
        if structured_artifact:
            return (
                structured_artifact,
                _resolved_artifact_relative_path(project_root, default_path),
            )
        return None, default_path
    if artifact == "document" and requested_path:
        try:
            markdown_path = _document_target_path(project_root, requested_path)[0]
        except StateError:
            return None, ""
        for structured_artifact in ARTIFACT_DEFAULT_MARKDOWN_PATHS:
            if markdown_path == artifact_markdown_path(project_root, structured_artifact):
                return structured_artifact, markdown_path
    return None, ""


def _ensure_structured_edit_records(
    project_root: Path,
    artifact: str,
    markdown_path: str,
) -> tuple[list[dict[str, object]], str]:
    jsonl_path = artifact_jsonl_path(project_root, artifact, markdown_path)
    jsonl_file = _safe_project_document_path(project_root, jsonl_path)
    if jsonl_file.exists():
        return read_artifact_records(project_root, jsonl_path), jsonl_path

    markdown_file = _safe_project_document_path(project_root, markdown_path)
    if markdown_file.exists():
        import_artifact(
            project_root,
            artifact,
            markdown_path=markdown_path,
            jsonl_path=jsonl_path,
        )
        return read_artifact_records(project_root, jsonl_path), jsonl_path

    records = [
        {
            "schema_version": 1,
            "artifact_type": artifact,
            "record_type": "document",
            "id": _artifact_document_record_id(artifact),
            "order": 0,
            "title": ARTIFACT_TITLES[artifact],
            "body": "",
            "status": "draft",
        }
    ]
    _write_artifact_records(project_root, jsonl_path, records, artifact)
    render_artifact(
        project_root,
        artifact,
        jsonl_path=jsonl_path,
        markdown_path=markdown_path,
    )
    return records, jsonl_path


def _artifact_document_record_id(artifact: str) -> str:
    return {
        "requirements": "REQ-DOC",
        "design": "DES-DOC",
        "implementation-plan": "PLAN-DOC",
        "test-plan": "TEST-DOC",
    }.get(artifact, "DOC")


def _safe_project_document_path(project_root: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute():
        raise StateError("document path must be relative")
    resolved = (project_root / path).resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as error:
        raise StateError("document path cannot escape the project") from error
    return resolved


def _write_artifact_records(
    project_root: Path,
    jsonl_path: str,
    records: list[dict[str, object]],
    artifact: str,
) -> None:
    if not records:
        raise StateError("artifact must contain at least one record")
    normalized_records: list[dict[str, object]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise StateError(f"record {index + 1} must be an object")
        normalized = dict(record)
        normalized.setdefault("schema_version", 1)
        normalized.setdefault("artifact_type", artifact)
        normalized.setdefault("record_type", "section")
        normalized_records.append(normalized)
    output_path = _safe_project_document_path(project_root, jsonl_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in normalized_records)
        + "\n",
        encoding="utf-8",
    )


def save_artifact_edit(
    project_root: Path | str,
    artifact: str,
    requested_path: str,
    payload: dict[str, object],
) -> dict[str, object]:
    project_root = Path(project_root).expanduser().resolve()
    artifact = artifact.strip()
    mode = str(payload.get("mode") or "")
    structured_artifact, markdown_path = _structured_artifact_for_edit_request(
        project_root,
        artifact,
        requested_path,
    )
    if structured_artifact:
        records = payload.get("records")
        if not isinstance(records, list):
            raise StateError("records must be a list")
        jsonl_path = artifact_jsonl_path(project_root, structured_artifact, markdown_path)
        _write_artifact_records(
            project_root,
            jsonl_path,
            records,
            structured_artifact,
        )
        result = render_artifact(
            project_root,
            structured_artifact,
            jsonl_path=jsonl_path,
            markdown_path=markdown_path,
        )
        return {
            "status": "saved",
            "mode": "structured",
            "artifact": structured_artifact,
            "markdown_path": result.markdown_path,
            "jsonl_path": result.jsonl_path,
            "record_count": result.record_count,
        }

    if mode != "markdown":
        raise StateError("artifact is not backed by a structured JSONL document")
    markdown = str(payload.get("markdown") or "")
    document_path = _artifact_event_document_path(
        project_root,
        artifact,
        requested_path,
    )
    document_path.parent.mkdir(parents=True, exist_ok=True)
    document_path.write_text(markdown, encoding="utf-8")
    return {
        "status": "saved",
        "mode": "markdown",
        "markdown_path": document_path.relative_to(project_root).as_posix(),
    }


def _artifact_editor_page(edit_data: dict[str, object]) -> str:
    data_json = json.dumps(edit_data).replace("</", "<\\/")
    title = html.escape(str(edit_data.get("title") or "Artifact Editor"))
    editor_font_size = _clamp_artifact_editor_font_size(
        edit_data.get("editor_font_size")
    )
    rich_editor_script = (
        _rich_markdown_editor_script() if edit_data.get("rich_editor") else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} Editor</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #10141f;
      --panel: #151b29;
      --panel-soft: #1d2638;
      --text: #e7edf7;
      --muted: #aab8cf;
      --border: #2a3142;
      --accent: #66d9e8;
      --accent-strong: #1f6f8b;
      --dirty: #ffd43b;
      --ok: #8ce99a;
      --error: #ff8787;
      --editor-font-size: {editor_font_size}px;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      font-size: 14px;
    }}

    * {{
      box-sizing: border-box;
    }}

    html,
    body {{
      height: 100%;
      margin: 0;
      background: var(--bg);
      color: var(--text);
    }}

    body {{
      overflow: auto;
    }}

    body.markdown-mode {{
      overflow: hidden;
    }}

    main {{
      display: grid;
      gap: 14px;
      max-width: 1040px;
      margin: 0 auto;
      padding: 16px;
    }}

    body.markdown-mode main {{
      display: block;
      width: 100%;
      height: 100%;
      max-width: none;
      margin: 0;
      padding: 0;
    }}

    .editor-header,
    .record-editor,
    .markdown-editor {{
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
    }}

    .editor-header {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      padding: 12px;
    }}

    .editor-title {{
      min-width: 0;
    }}

    h1 {{
      margin: 0;
      font-size: 17px;
      line-height: 1.25;
    }}

    .editor-meta {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
    }}

    .editor-actions {{
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }}

    button,
    .editor-actions select {{
      min-height: 34px;
      border: 1px solid #364156;
      border-radius: 6px;
      background: var(--panel-soft);
      color: var(--text);
      cursor: pointer;
      font: inherit;
      font-weight: 650;
      padding: 0 12px;
    }}

    .editor-actions select {{
      min-width: 130px;
      cursor: pointer;
      font-weight: 500;
    }}

    button.primary {{
      border-color: var(--accent-strong);
      background: var(--accent-strong);
      color: #ffffff;
    }}

    button:disabled {{
      cursor: not-allowed;
      opacity: 0.55;
    }}

    .status {{
      color: var(--muted);
      min-height: 20px;
      font-size: 13px;
    }}

    .status.dirty {{
      color: var(--dirty);
    }}

    .status.saved {{
      color: var(--ok);
    }}

    .status.error {{
      color: var(--error);
    }}

    body.markdown-mode .editor-header {{
      position: sticky;
      top: 0;
      z-index: 3;
      border-width: 0 0 1px;
      border-radius: 0;
    }}

    body.markdown-mode .status {{
      position: fixed;
      right: 10px;
      bottom: 10px;
      z-index: 2;
      min-height: 0;
      border-radius: 999px;
      background: rgba(15, 20, 32, 0.9);
      color: var(--muted);
      padding: 4px 10px;
      box-shadow: 0 8px 22px rgba(0, 0, 0, 0.22);
      pointer-events: none;
    }}

    body.markdown-mode .status:empty {{
      display: none;
    }}

    body.markdown-mode .status.error {{
      color: var(--error);
    }}

    .records {{
      display: grid;
      gap: 10px;
    }}

    body.markdown-mode .records {{
      display: block;
      height: 100%;
    }}

    details.record-editor > summary {{
      cursor: pointer;
      padding: 12px;
      color: var(--text);
      font-weight: 650;
    }}

    .record-summary {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
    }}

    .record-summary-text {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    .record-summary-kind {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 500;
    }}

    .record-body {{
      display: grid;
      gap: 12px;
      border-top: 1px solid var(--border);
      padding: 12px;
    }}

    .record-actions {{
      display: flex;
      gap: 8px;
      justify-content: flex-end;
    }}

    .field-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
    }}

    label {{
      display: grid;
      gap: 5px;
      min-width: 0;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      text-transform: uppercase;
    }}

    input,
    select,
    textarea {{
      width: 100%;
      border: 1px solid #364156;
      border-radius: 6px;
      background: #0f1420;
      color: var(--text);
      font: inherit;
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      line-height: 1.45;
      padding: 8px;
      text-transform: none;
    }}

    textarea {{
      min-height: 92px;
      resize: vertical;
    }}

    textarea.body-field {{
      min-height: 180px;
      font-size: var(--editor-font-size);
    }}

    .generated-fields {{
      border: 1px dashed #364156;
      border-radius: 7px;
      background: #101725;
      color: var(--muted);
    }}

    .generated-fields > summary {{
      cursor: pointer;
      padding: 8px 10px;
      font-size: 12px;
      font-weight: 650;
      text-transform: uppercase;
    }}

    .generated-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 8px;
      padding: 0 10px 10px;
    }}

    .generated-field {{
      display: grid;
      gap: 3px;
      min-width: 0;
      font-size: 12px;
    }}

    .generated-field code {{
      overflow: hidden;
      border-radius: 4px;
      background: #0f1420;
      color: var(--text);
      padding: 4px 6px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    .markdown-editor {{
      display: grid;
      gap: 10px;
      padding: 12px;
    }}

    body.markdown-mode .markdown-editor {{
      display: block;
      height: 100%;
      border: 0;
      border-radius: 0;
      background: transparent;
      padding: 0;
    }}

    .markdown-editor textarea {{
      min-height: 62vh;
    }}

    body.markdown-mode .markdown-editor textarea {{
      display: block;
      width: 100%;
      height: 100%;
      min-height: 100%;
      border: 0;
      border-radius: 0;
      font-size: var(--editor-font-size);
      resize: none;
      padding: 14px 16px 36px;
    }}

    body.rich-markdown-mode .markdown-editor {{
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      min-height: 100%;
    }}

    .rich-toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
      border-bottom: 1px solid var(--border);
      background: #121827;
      padding: 8px;
    }}

    .rich-toolbar select,
    .rich-toolbar button {{
      min-height: 30px;
      border: 1px solid #354058;
      border-radius: 5px;
      background: #171f31;
      color: var(--text);
      font-size: 12px;
      padding: 0 9px;
    }}

    .rich-toolbar button {{
      min-width: 32px;
    }}

    .rich-toolbar button.active {{
      border-color: var(--accent);
      color: #ffffff;
      background: #1f3b4b;
    }}

    .rich-editor-surface {{
      min-height: 0;
      overflow: auto;
      background: #0f1420;
    }}

    .rich-editor-surface .tiptap {{
      min-height: 100%;
      font-size: var(--editor-font-size);
      outline: none;
      padding: 16px 18px 40px;
    }}

    .rich-editor-surface .tiptap > :first-child {{
      margin-top: 0;
    }}

    .rich-editor-surface .tiptap table {{
      border-collapse: collapse;
      width: 100%;
    }}

    .rich-editor-surface .tiptap th,
    .rich-editor-surface .tiptap td {{
      border: 1px solid var(--border);
      padding: 6px 8px;
      vertical-align: top;
    }}

    .rich-editor-surface .tiptap th {{
      background: #151b29;
    }}

    body.rich-markdown-mode .markdown-editor textarea.rich-source-fallback[hidden] {{
      display: none;
    }}

    .markdown-editor.rich-fallback {{
      grid-template-rows: auto minmax(0, 1fr);
    }}
  </style>
</head>
<body>
  <main>
    <header class="editor-header">
      <div class="editor-title">
        <h1>{title}</h1>
        <div id="editorMeta" class="editor-meta"></div>
      </div>
      <div class="editor-actions">
        <select id="recordType" aria-label="Record type to add">
          <option value="section">Section</option>
          <option value="requirement">Requirement</option>
          <option value="decision">Decision</option>
          <option value="interface">Interface</option>
          <option value="unit">Implementation unit</option>
          <option value="suite">Test suite</option>
          <option value="test">Test case</option>
        </select>
        <button id="addRecord" type="button">Add record</button>
        <button id="saveArtifact" class="primary" type="button" disabled>Save</button>
      </div>
    </header>
    <div id="status" class="status"></div>
    <section id="records" class="records"></section>
  </main>
  <script>
    const EDIT_DATA = {data_json};
    const LIST_FIELDS = new Set(EDIT_DATA.list_fields || []);
    const JSON_FIELDS = new Set(EDIT_DATA.json_fields || []);
    const RICH_EDITOR_ENABLED = Boolean(EDIT_DATA.rich_editor);
    const MIN_EDITOR_FONT_SIZE = 11;
    const MAX_EDITOR_FONT_SIZE = 28;
    const CORE_FIELDS = new Set([
      "schema_version",
      "artifact_type",
      "record_type",
      "id",
      "unit_id",
      "title",
      "order",
      "status",
      "phase",
      "sequence",
      "body",
    ]);
    const recordsRoot = document.getElementById("records");
    const recordType = document.getElementById("recordType");
    const addRecord = document.getElementById("addRecord");
    const saveArtifact = document.getElementById("saveArtifact");
    const statusLine = document.getElementById("status");
    const editorMeta = document.getElementById("editorMeta");
    let records = Array.isArray(EDIT_DATA.records)
      ? EDIT_DATA.records.map((record) => ({{ ...record }}))
      : [];
    let saveInFlight = false;
    let dirty = false;
    let markdownTextarea = null;
    let richMarkdownEditor = null;
    let richToolbar = null;
    let richEditorLoading = false;
    let editorFontSize = clampEditorFontSize(EDIT_DATA.editor_font_size || 16);

    const GENERATED_FIELDS = new Set([
      "schema_version",
      "artifact_type",
      "id",
      "unit_id",
      "order",
      "heading_level",
      "parent_id",
      "updated_at",
    ]);

    const COMMON_FIELDS = ["record_type", "title", "status", "body"];
    const RECORD_FIELDS = {{
      document: ["title", "summary", "scope", "out_of_scope", "personas", "status", "body"],
      section: ["title", "status", "body", "requirements", "tags", "links"],
      requirement: [
        "title",
        "statement",
        "body",
        "rationale",
        "priority",
        "acceptance_criteria",
        "verification",
        "dependencies",
        "status",
      ],
      decision: [
        "title",
        "context",
        "decision",
        "body",
        "consequences",
        "requirements",
        "status",
      ],
      interface: [
        "title",
        "kind",
        "producer",
        "consumer",
        "body",
        "schema",
        "requirements",
        "status",
      ],
      unit: [
        "title",
        "phase",
        "sequence",
        "body",
        "scope",
        "commit_tasks",
        "paths",
        "requirements",
        "design_sections",
        "dependencies",
        "exit_criteria",
        "status",
      ],
      suite: ["title", "body", "scope", "requirements", "status"],
      test: [
        "title",
        "level",
        "suite",
        "body",
        "requirements",
        "design_sections",
        "implementation_units",
        "preconditions",
        "steps",
        "expected_results",
        "automation",
        "status",
      ],
    }};

    function contextUrl(path) {{
      const contextId = EDIT_DATA.context_id || "";
      if (!contextId) {{
        return path;
      }}
      const separator = path.includes("?") ? "&" : "?";
      return `${{path}}${{separator}}context_id=${{encodeURIComponent(contextId)}}`;
    }}

    function setStatus(message, error = false) {{
      statusLine.textContent = message || "";
      statusLine.classList.toggle("error", Boolean(error));
      statusLine.classList.toggle("dirty", !error && dirty);
      statusLine.classList.toggle("saved", !error && !dirty && Boolean(message));
    }}

    function setDirty(nextDirty = true) {{
      dirty = Boolean(nextDirty);
      saveArtifact.disabled = saveInFlight || !dirty;
      if (dirty) {{
        setStatus("unsaved changes");
      }}
    }}

    function markDirty() {{
      setDirty(true);
    }}

    function clampEditorFontSize(value) {{
      const requested = Number(value);
      if (!Number.isFinite(requested)) {{
        return 16;
      }}
      return Math.max(
        MIN_EDITOR_FONT_SIZE,
        Math.min(MAX_EDITOR_FONT_SIZE, Math.round(requested)),
      );
    }}

    function applyEditorFontSize(value = editorFontSize) {{
      editorFontSize = clampEditorFontSize(value);
      document.documentElement.style.setProperty(
        "--editor-font-size",
        `${{editorFontSize}}px`,
      );
    }}

    function displayId(record) {{
      return record.id || record.unit_id || "";
    }}

    function recordSummary(record, index) {{
      const id = displayId(record);
      const title = record.title || "Untitled";
      const type = record.record_type || "section";
      return `${{id ? `${{id}}. ` : ""}}${{title}} · ${{type}} #${{index + 1}}`;
    }}

    function stringValue(value) {{
      if (value === undefined || value === null) {{
        return "";
      }}
      return String(value);
    }}

    function arrayValue(value) {{
      if (Array.isArray(value)) {{
        return value.join("\\n");
      }}
      return stringValue(value);
    }}

    function jsonValue(value) {{
      if (value === undefined || value === null || value === "") {{
        return "";
      }}
      if (typeof value === "string") {{
        return value;
      }}
      return JSON.stringify(value, null, 2);
    }}

    function recordKind(record) {{
      return String(record.record_type || "section");
    }}

    function generatedFieldEntries(record) {{
      return Object.entries(record)
        .filter(([field]) => GENERATED_FIELDS.has(field))
        .filter(([, value]) => value !== undefined && value !== null && value !== "");
    }}

    function editableFieldsForRecord(record) {{
      const fields = new Set(RECORD_FIELDS[recordKind(record)] || COMMON_FIELDS);
      fields.add("record_type");
      for (const field of Object.keys(record)) {{
        if (!GENERATED_FIELDS.has(field)) {{
          fields.add(field);
        }}
      }}
      return Array.from(fields);
    }}

    function fieldInputOptions(field) {{
      if (field === "record_type") {{
        return {{
          kind: "select",
          values: ["document", "section", "requirement", "decision", "interface", "unit", "suite", "test"],
        }};
      }}
      if (field === "status") {{
        return {{
          kind: "select",
          values: ["draft", "approved", "changed", "deprecated", "deferred"],
        }};
      }}
      if (field === "priority") {{
        return {{ kind: "select", values: ["", "must", "should", "could", "deferred"] }};
      }}
      if (["order", "phase", "sequence"].includes(field)) {{
        return {{ numeric: true }};
      }}
      if (field === "body" || LIST_FIELDS.has(field) || JSON_FIELDS.has(field)) {{
        return {{
          kind: "textarea",
          list: LIST_FIELDS.has(field),
          json: JSON_FIELDS.has(field),
        }};
      }}
      return {{}};
    }}

    function fieldLabel(field) {{
      if (field === "record_type") {{
        return "Type";
      }}
      return field.replace(/_/g, " ");
    }}

    function appendInput(container, record, field, label, options = {{}}) {{
      const wrapper = document.createElement("label");
      wrapper.textContent = label;
      let input;
      if (options.kind === "select") {{
        input = document.createElement("select");
        for (const optionValue of options.values || []) {{
          const option = document.createElement("option");
          option.value = optionValue;
          option.textContent = optionValue || "none";
          input.append(option);
        }}
        input.value = stringValue(record[field]);
      }} else if (options.kind === "textarea") {{
        input = document.createElement("textarea");
        input.value = options.list
          ? arrayValue(record[field])
          : options.json
          ? jsonValue(record[field])
          : stringValue(record[field]);
      }} else {{
        input = document.createElement("input");
        input.type = options.numeric ? "number" : "text";
        input.value = stringValue(record[field]);
      }}
      input.dataset.field = field;
      if (options.list) {{
        input.dataset.list = "1";
      }}
      if (options.json) {{
        input.dataset.json = "1";
      }}
      if (options.numeric) {{
        input.dataset.numeric = "1";
      }}
      if (field === "body") {{
        input.classList.add("body-field");
        input.placeholder = "Markdown text, tables, code fences, and Mermaid diagrams";
      }}
      input.addEventListener("input", markDirty);
      input.addEventListener("change", markDirty);
      wrapper.append(input);
      container.append(wrapper);
      return input;
    }}

    function renderStructuredEditor() {{
      document.body.classList.remove("markdown-mode", "rich-markdown-mode");
      if (richMarkdownEditor) {{
        richMarkdownEditor.destroy();
        richMarkdownEditor = null;
      }}
      markdownTextarea = null;
      richToolbar = null;
      editorMeta.textContent = `${{EDIT_DATA.markdown_path}} · source ${{EDIT_DATA.jsonl_path}}`;
      addRecord.hidden = false;
      recordType.hidden = false;
      recordsRoot.replaceChildren();
      for (const [index, record] of records.entries()) {{
        const details = document.createElement("details");
        details.className = "record-editor";
        details.open = index === 0 || dirty;
        details.dataset.index = String(index);

        const summary = document.createElement("summary");
        const summaryInner = document.createElement("span");
        summaryInner.className = "record-summary";
        const summaryText = document.createElement("span");
        summaryText.className = "record-summary-text";
        summaryText.textContent = recordSummary(record, index);
        const summaryKind = document.createElement("span");
        summaryKind.className = "record-summary-kind";
        summaryKind.textContent = recordKind(record);
        summaryInner.append(summaryText, summaryKind);
        summary.append(summaryInner);
        details.append(summary);

        const body = document.createElement("div");
        body.className = "record-body";
        const grid = document.createElement("div");
        grid.className = "field-grid";
        for (const field of editableFieldsForRecord(record)) {{
          if (field === "body") {{
            continue;
          }}
          appendInput(grid, record, field, fieldLabel(field), fieldInputOptions(field));
        }}
        body.append(grid);
        if (editableFieldsForRecord(record).includes("body")) {{
          appendInput(body, record, "body", "Markdown body", fieldInputOptions("body"));
        }}

        const generatedEntries = generatedFieldEntries(record);
        if (generatedEntries.length > 0) {{
          const generated = document.createElement("details");
          generated.className = "generated-fields";
          const generatedSummary = document.createElement("summary");
          generatedSummary.textContent = "Generated fields";
          generated.append(generatedSummary);
          const generatedGrid = document.createElement("div");
          generatedGrid.className = "generated-grid";
          for (const [field, value] of generatedEntries) {{
            const wrapper = document.createElement("div");
            wrapper.className = "generated-field";
            const name = document.createElement("span");
            name.textContent = field.replace(/_/g, " ");
            const code = document.createElement("code");
            code.textContent = Array.isArray(value) || typeof value === "object"
              ? JSON.stringify(value)
              : String(value);
            wrapper.append(name, code);
            generatedGrid.append(wrapper);
          }}
          generated.append(generatedGrid);
          body.append(generated);
        }}

        const actions = document.createElement("div");
        actions.className = "record-actions";
        const duplicate = document.createElement("button");
        duplicate.type = "button";
        duplicate.textContent = "Duplicate";
        duplicate.addEventListener("click", () => duplicateRecord(index));
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "Delete";
        remove.disabled = records.length <= 1;
        remove.addEventListener("click", () => deleteRecord(index));
        actions.append(duplicate, remove);
        body.append(actions);

        details.append(body);
        recordsRoot.append(details);
      }}
    }}

    function markdownValue() {{
      if (
        richMarkdownEditor &&
        typeof richMarkdownEditor.getMarkdown === "function"
      ) {{
        return richMarkdownEditor.getMarkdown();
      }}
      return markdownTextarea ? markdownTextarea.value : "";
    }}

    function setMarkdownValue(value) {{
      const nextValue = String(value || "");
      if (markdownTextarea) {{
        markdownTextarea.value = nextValue;
      }}
      if (
        richMarkdownEditor &&
        richMarkdownEditor.commands &&
        typeof richMarkdownEditor.commands.setContent === "function"
      ) {{
        richMarkdownEditor.commands.setContent(nextValue, {{ contentType: "markdown" }});
      }}
    }}

    function appendMarkdownSnippet(snippet) {{
      const prefix = markdownValue().replace(/\\s*$/, "");
      const nextValue = `${{prefix}}${{prefix ? "\\n\\n" : ""}}${{snippet}}\\n`;
      setMarkdownValue(nextValue);
      markDirty();
    }}

    {rich_editor_script}

    function renderMarkdownEditor() {{
      document.body.classList.add("markdown-mode");
      document.body.classList.toggle("rich-markdown-mode", RICH_EDITOR_ENABLED);
      if (richMarkdownEditor) {{
        richMarkdownEditor.destroy();
        richMarkdownEditor = null;
      }}
      editorMeta.textContent = EDIT_DATA.markdown_path || "";
      addRecord.hidden = true;
      recordType.hidden = true;
      recordsRoot.replaceChildren();
      const wrapper = document.createElement("section");
      wrapper.className = "markdown-editor";
      if (RICH_EDITOR_ENABLED) {{
        wrapper.classList.add("rich-markdown-editor", "rich-fallback");
      }}
      const textarea = document.createElement("textarea");
      textarea.id = "markdownSource";
      textarea.className = RICH_EDITOR_ENABLED ? "rich-source-fallback" : "";
      textarea.setAttribute("aria-label", EDIT_DATA.markdown_path || "Markdown");
      textarea.spellcheck = true;
      textarea.value = EDIT_DATA.markdown || "";
      textarea.addEventListener("input", markDirty);
      textarea.addEventListener("change", markDirty);
      markdownTextarea = textarea;
      if (RICH_EDITOR_ENABLED) {{
        wrapper.append(createRichToolbar());
        const surface = document.createElement("div");
        surface.className = "rich-editor-surface";
        surface.setAttribute("aria-label", EDIT_DATA.markdown_path || "Markdown");
        wrapper.append(surface, textarea);
        recordsRoot.append(wrapper);
        initializeRichMarkdownEditor(wrapper, surface);
      }} else {{
        wrapper.append(textarea);
        recordsRoot.append(wrapper);
      }}
    }}

    function splitLines(value) {{
      return String(value || "")
        .split(/\\r?\\n/)
        .map((line) => line.trim())
        .filter(Boolean);
    }}

    function parseInputValue(input) {{
      if (input.dataset.list === "1") {{
        return splitLines(input.value);
      }}
      if (input.dataset.json === "1") {{
        const raw = input.value.trim();
        if (!raw) {{
          return {{}};
        }}
        return JSON.parse(raw);
      }}
      if (input.dataset.numeric === "1") {{
        if (!input.value.trim()) {{
          return undefined;
        }}
        return Number(input.value);
      }}
      return input.value;
    }}

    function collectStructuredRecords() {{
      const collected = [];
      for (const details of recordsRoot.querySelectorAll(".record-editor")) {{
        const original = records[Number(details.dataset.index || "0")] || {{}};
        const record = {{ ...original }};
        record.schema_version = original.schema_version || 1;
        record.artifact_type = original.artifact_type || EDIT_DATA.artifact_name;
        for (const input of details.querySelectorAll("[data-field]")) {{
          const field = input.dataset.field;
          const value = parseInputValue(input);
          if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) {{
            continue;
          }}
          if (JSON_FIELDS.has(field) && Object.keys(value).length === 0) {{
            continue;
          }}
          record[field] = value;
        }}
        collected.push(record);
      }}
      return collected;
    }}

    function collectMarkdownDocument() {{
      return markdownValue();
    }}

    function nextGeneratedId(type) {{
      const existing = new Set(records.map((record) => displayId(record)).filter(Boolean));
      const prefixByType = {{
        document: "DOC",
        section: `${{String(EDIT_DATA.artifact_name || "doc").toUpperCase().replace(/[^A-Z0-9]+/g, "")}}SEC`,
        requirement: "REQ",
        decision: "DEC",
        interface: "IFACE",
        unit: "PH1-C",
        suite: "TS",
        test: "TEST",
      }};
      const prefix = prefixByType[type] || "REC";
      for (let index = 1; index < 10000; index += 1) {{
        const candidate = type === "unit"
          ? `${{prefix}}${{index}}`
          : `${{prefix}}-${{String(index).padStart(3, "0")}}`;
        if (!existing.has(candidate)) {{
          return candidate;
        }}
      }}
      return `${{prefix}}-${{Date.now()}}`;
    }}

    function nextOrder() {{
      const nextOrder = records.reduce((maximum, record) => {{
        const order = Number(record.order || 0);
        return Number.isFinite(order) ? Math.max(maximum, order) : maximum;
      }}, 0) + 10;
      return nextOrder;
    }}

    function newRecord(type) {{
      const record = {{
        schema_version: 1,
        artifact_type: EDIT_DATA.artifact_name,
        record_type: type,
        title: `New ${{type.replace(/-/g, " ")}}`,
        order: nextOrder(),
        body: "",
        status: "draft",
      }};
      if (type === "unit") {{
        record.unit_id = nextGeneratedId(type);
        record.phase = 1;
        record.sequence = 1;
      }} else {{
        record.id = nextGeneratedId(type);
      }}
      return record;
    }}

    function addSectionRecord() {{
      records.push(newRecord(recordType.value || "section"));
      renderStructuredEditor();
      const last = recordsRoot.querySelector(".record-editor:last-child");
      if (last) {{
        last.open = true;
        last.scrollIntoView({{ block: "nearest" }});
      }}
      markDirty();
    }}

    function duplicateRecord(index) {{
      const original = records[index];
      if (!original) {{
        return;
      }}
      const copy = {{ ...original, order: nextOrder(), title: `${{original.title || "Record"}} copy` }};
      if (copy.unit_id) {{
        copy.unit_id = nextGeneratedId("unit");
      }} else if (copy.id) {{
        copy.id = nextGeneratedId(recordKind(copy));
      }}
      records.splice(index + 1, 0, copy);
      renderStructuredEditor();
      markDirty();
    }}

    function deleteRecord(index) {{
      if (records.length <= 1) {{
        return;
      }}
      const record = records[index];
      const name = record ? recordSummary(record, index) : "this record";
      if (!window.confirm(`Delete ${{name}}?`)) {{
        return;
      }}
      records.splice(index, 1);
      renderStructuredEditor();
      markDirty();
    }}

    async function save(options = {{}}) {{
      if (saveInFlight) {{
        return false;
      }}
      if (!dirty && !options.force) {{
        return true;
      }}
      saveInFlight = true;
      saveArtifact.disabled = true;
      setStatus("saving...");
      try {{
        const payload = EDIT_DATA.mode === "structured"
          ? {{
              mode: "structured",
              artifact: EDIT_DATA.artifact,
              path: EDIT_DATA.path || "",
              records: collectStructuredRecords(),
            }}
          : {{
              mode: "markdown",
              artifact: EDIT_DATA.artifact,
              path: EDIT_DATA.path || "",
              markdown: collectMarkdownDocument(),
            }};
        const response = await fetch(contextUrl("/api/artifacts/edit"), {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload),
        }});
        const result = await response.json().catch(() => ({{ error: "save failed" }}));
        if (!response.ok) {{
          throw new Error(result.error || "save failed");
        }}
        if (EDIT_DATA.mode === "structured") {{
          records = collectStructuredRecords();
        }}
        setDirty(false);
        setStatus(`saved ${{result.markdown_path || EDIT_DATA.markdown_path}}`);
        if (window.parent) {{
          window.parent.postMessage(
            {{
              type: "electroboy-artifact-saved",
              path: result.markdown_path || EDIT_DATA.markdown_path,
            }},
            window.location.origin,
          );
        }}
        return true;
      }} catch (error) {{
        setStatus(error.message || String(error), true);
        return false;
      }} finally {{
        saveInFlight = false;
        saveArtifact.disabled = !dirty;
      }}
    }}

    addRecord.addEventListener("click", addSectionRecord);
    saveArtifact.addEventListener("click", () => {{
      save({{ force: true }});
    }});
    window.addEventListener("message", async (event) => {{
      if (event.origin !== window.location.origin) {{
        return;
      }}
      const data = event.data || {{}};
      if (data.type === "electroboy-editor-font-size") {{
        applyEditorFontSize(data.font_size);
        return;
      }}
      if (data.type !== "electroboy-save-request") {{
        return;
      }}
      const ok = await save({{ force: true }});
      if (window.parent) {{
        window.parent.postMessage(
          {{
            type: "electroboy-artifact-save-complete",
            token: data.token || "",
            ok,
          }},
          window.location.origin,
        );
      }}
    }});
    window.addEventListener("beforeunload", (event) => {{
      if (!dirty) {{
        return;
      }}
      event.preventDefault();
      event.returnValue = "";
    }});
    applyEditorFontSize();
    if (EDIT_DATA.mode === "structured") {{
      renderStructuredEditor();
    }} else {{
      renderMarkdownEditor();
    }}
  </script>
</body>
</html>
"""


def _rich_markdown_editor_script() -> str:
    return """
    function richButton(command, label, title) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.command = command;
      button.title = title;
      button.setAttribute("aria-label", title);
      button.textContent = label;
      button.addEventListener("click", () => executeRichCommand(command));
      return button;
    }

    function createRichToolbar() {
      const toolbar = document.createElement("div");
      toolbar.className = "rich-toolbar";

      const heading = document.createElement("select");
      heading.dataset.heading = "1";
      heading.title = "Block style";
      heading.setAttribute("aria-label", "Block style");
      for (const [value, label] of [
        ["paragraph", "Paragraph"],
        ["1", "Heading 1"],
        ["2", "Heading 2"],
        ["3", "Heading 3"],
      ]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        heading.append(option);
      }
      heading.addEventListener("change", () => {
        if (!richMarkdownEditor) {
          return;
        }
        if (heading.value === "paragraph") {
          richMarkdownEditor.chain().focus().setParagraph().run();
        } else {
          richMarkdownEditor
            .chain()
            .focus()
            .toggleHeading({ level: Number(heading.value) })
            .run();
        }
      });

      toolbar.append(
        heading,
        richButton("bold", "B", "Bold"),
        richButton("italic", "I", "Italic"),
        richButton("code", "`", "Inline code"),
        richButton("bulletList", "Bullet", "Bullet list"),
        richButton("orderedList", "1.", "Numbered list"),
        richButton("blockquote", "Quote", "Quote"),
        richButton("codeBlock", "Code", "Code block"),
        richButton("link", "Link", "Link"),
        richButton("table", "Table", "Insert table"),
        richButton("mermaid", "Mermaid", "Insert Mermaid block"),
      );
      richToolbar = toolbar;
      return toolbar;
    }

    function executeRichCommand(command) {
      if (!richMarkdownEditor) {
        return;
      }
      const chain = richMarkdownEditor.chain().focus();
      if (command === "bold") {
        chain.toggleBold().run();
      } else if (command === "italic") {
        chain.toggleItalic().run();
      } else if (command === "code") {
        chain.toggleCode().run();
      } else if (command === "bulletList") {
        chain.toggleBulletList().run();
      } else if (command === "orderedList") {
        chain.toggleOrderedList().run();
      } else if (command === "blockquote") {
        chain.toggleBlockquote().run();
      } else if (command === "codeBlock") {
        chain.toggleCodeBlock().run();
      } else if (command === "link") {
        const previous = richMarkdownEditor.getAttributes("link").href || "";
        const href = window.prompt("Link URL", previous);
        if (href === null) {
          return;
        }
        if (!href.trim()) {
          chain.unsetLink().run();
        } else {
          chain.setLink({ href: href.trim() }).run();
        }
      } else if (command === "table") {
        chain.insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run();
      } else if (command === "mermaid") {
        appendMarkdownSnippet(
          "```mermaid\\ngraph TD\\n  A[Start] --> B[Next]\\n```",
        );
      }
      updateRichToolbarState();
    }

    function updateRichToolbarState() {
      if (!richToolbar || !richMarkdownEditor) {
        return;
      }
      const heading = richToolbar.querySelector("[data-heading]");
      if (heading) {
        if (richMarkdownEditor.isActive("heading", { level: 1 })) {
          heading.value = "1";
        } else if (richMarkdownEditor.isActive("heading", { level: 2 })) {
          heading.value = "2";
        } else if (richMarkdownEditor.isActive("heading", { level: 3 })) {
          heading.value = "3";
        } else {
          heading.value = "paragraph";
        }
      }
      for (const button of richToolbar.querySelectorAll("[data-command]")) {
        const command = button.dataset.command || "";
        const activeByCommand = {
          bold: "bold",
          italic: "italic",
          code: "code",
          bulletList: "bulletList",
          orderedList: "orderedList",
          blockquote: "blockquote",
          codeBlock: "codeBlock",
          link: "link",
        };
        button.classList.toggle(
          "active",
          Boolean(activeByCommand[command]) &&
            richMarkdownEditor.isActive(activeByCommand[command]),
        );
      }
    }

    async function initializeRichMarkdownEditor(wrapper, surface) {
      if (!RICH_EDITOR_ENABLED || richEditorLoading) {
        return;
      }
      richEditorLoading = true;
      surface.setAttribute("aria-busy", "true");
      setStatus("loading rich editor...");
      try {
        const [
          coreModule,
          starterKitModule,
          markdownModule,
          linkModule,
          tableModule,
          tableRowModule,
          tableHeaderModule,
          tableCellModule,
        ] = await Promise.all([
          import("https://esm.sh/@tiptap/core"),
          import("https://esm.sh/@tiptap/starter-kit"),
          import("https://esm.sh/@tiptap/markdown"),
          import("https://esm.sh/@tiptap/extension-link"),
          import("https://esm.sh/@tiptap/extension-table"),
          import("https://esm.sh/@tiptap/extension-table-row"),
          import("https://esm.sh/@tiptap/extension-table-header"),
          import("https://esm.sh/@tiptap/extension-table-cell"),
        ]);
        const Editor = coreModule.Editor;
        const StarterKit = starterKitModule.default || starterKitModule.StarterKit;
        const Markdown = markdownModule.Markdown || markdownModule.default;
        const Link = linkModule.default || linkModule.Link;
        const Table = tableModule.default || tableModule.Table;
        const TableRow = tableRowModule.default || tableRowModule.TableRow;
        const TableHeader = tableHeaderModule.default || tableHeaderModule.TableHeader;
        const TableCell = tableCellModule.default || tableCellModule.TableCell;
        if (!Editor || !StarterKit || !Markdown) {
          throw new Error("Tiptap Markdown modules are unavailable");
        }
        richMarkdownEditor = new Editor({
          element: surface,
          extensions: [
            StarterKit,
            Markdown,
            Link ? Link.configure({ openOnClick: false }) : null,
            Table ? Table.configure({ resizable: true }) : null,
            TableRow,
            TableHeader,
            TableCell,
          ].filter(Boolean),
          content: markdownTextarea ? markdownTextarea.value : "",
          contentType: "markdown",
          editorProps: {
            attributes: {
              spellcheck: "true",
            },
          },
          onUpdate: () => {
            if (markdownTextarea) {
              markdownTextarea.value = markdownValue();
            }
            markDirty();
          },
          onSelectionUpdate: updateRichToolbarState,
          onFocus: updateRichToolbarState,
        });
        surface.removeAttribute("aria-busy");
        if (markdownTextarea) {
          markdownTextarea.hidden = true;
        }
        wrapper.classList.remove("rich-fallback");
        setStatus("");
        updateRichToolbarState();
      } catch (error) {
        wrapper.classList.add("rich-fallback");
        surface.remove();
        if (markdownTextarea) {
          markdownTextarea.hidden = false;
        }
        setStatus(`rich editor unavailable: ${error.message || error}`, true);
      } finally {
        richEditorLoading = false;
      }
    }
"""


def _document_target_path(project_root: Path | str, relative_path: str) -> tuple[str, Path]:
    project_root = Path(project_root).expanduser().resolve()
    normalized_path = _normalize_document_target_path(relative_path)
    document_path = (project_root / normalized_path).resolve()
    try:
        document_path.relative_to(project_root)
    except ValueError as error:
        raise StateError("document path cannot escape the project") from error
    return normalized_path, document_path


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


def _empty_creative_corkboard_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "type": "electroboy.creative.corkboard",
        "cards": [],
    }


def _create_creative_corkboard(project_root: Path | str, relative_path: str) -> str:
    normalized_path, corkboard_path = _creative_path(project_root, relative_path)
    if not normalized_path.endswith(CREATIVE_CORKBOARD_SUFFIX):
        raise StateError(f"corkboard path must end with {CREATIVE_CORKBOARD_SUFFIX}")
    if corkboard_path.exists() and not corkboard_path.is_file():
        raise StateError("corkboard path already exists as a folder")
    if not corkboard_path.exists() or not corkboard_path.read_text(encoding="utf-8").strip():
        corkboard_path.parent.mkdir(parents=True, exist_ok=True)
        corkboard_path.write_text(
            json.dumps(_empty_creative_corkboard_document(), indent=2) + "\n",
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
    """Return an interactive corkboard for a folder or corkboard file."""

    payload = _creative_corkboard_payload(
        project_root,
        board_path,
        title=title,
        context_id=context_id,
    )
    data_json = json.dumps(payload).replace("</", "<\\/")
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

    h1 {{
      margin: 2px 0 0;
      color: #fff9e8;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 22px;
      font-weight: 700;
      line-height: 1.15;
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

    .card-stack-icon {{
      position: relative;
      width: 14px;
      height: 12px;
      border: 1.5px solid currentcolor;
      border-radius: 2px;
    }}

    .card-stack-icon::before,
    .card-stack-icon::after {{
      position: absolute;
      width: 14px;
      height: 12px;
      border: 1.5px solid currentcolor;
      border-radius: 2px;
      content: "";
    }}

    .card-stack-icon::before {{
      top: 3px;
      left: -4px;
      opacity: 0.74;
    }}

    .card-stack-icon::after {{
      top: 6px;
      left: -8px;
      opacity: 0.48;
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
        <h1>{html.escape(str(payload["title"]))}</h1>
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
    const canvasViewport = document.getElementById("canvasViewport");
    const board = document.getElementById("board");
    const boardEyebrow = document.getElementById("boardEyebrow");
    const addCard = document.getElementById("addCard");
    const cardSizeSlider = document.getElementById("cardSizeSlider");
    const cardSizeValue = document.getElementById("cardSizeValue");
    const boardType = CORKBOARD_DATA.board_type || "folder";
    const cards = Array.isArray(CORKBOARD_DATA.cards) ? CORKBOARD_DATA.cards : [];
    const CARD_PALETTE = Array.isArray(CORKBOARD_DATA.palette)
      ? CORKBOARD_DATA.palette
      : [];
    const saveTimers = new Map();
    const cardSaveRequests = new Map();
    const CARD_SCALE_STORAGE_PREFIX = "electroboy.creative.corkboard.cardScale.";
    const CANVAS_PAN_STORAGE_PREFIX = "electroboy.creative.corkboard.canvasPan.";
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

    function contextUrl(path) {{
      const contextId = CORKBOARD_DATA.context_id || "";
      if (!contextId) {{
        return path;
      }}
      const separator = path.includes("?") ? "&" : "?";
      return `${{path}}${{separator}}context_id=${{encodeURIComponent(contextId)}}`;
    }}

    function boardStoragePath() {{
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
      if (!CORKBOARD_DATA.context_id) {{
        return null;
      }}
      let payload = null;
      if (boardType === "folder") {{
        payload = {{
          board_type: "folder",
          folder: CORKBOARD_DATA.folder.path,
          path: card.path,
          note: card.note || "",
          color: cardColorName(card),
        }};
      }} else {{
        payload = {{
          board_type: "freeform",
          corkboard: CORKBOARD_DATA.corkboard.path,
          card: {{
            id: card.id,
            title: card.title || "",
            note: card.note || "",
            x: Number(card.x) || 0,
            y: Number(card.y) || 0,
            rotation: Number(card.rotation) || 0,
            color: cardColorName(card),
            card_type: cardKind(card),
            board_path: card.board_path || "",
          }},
        }};
      }}
      const response = await fetch(contextUrl("/api/creative/corkboard"), {{
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
      if (boardType !== "freeform") {{
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
        const response = await fetch(contextUrl("/api/creative/corkboard"), {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            board_type: "freeform",
            action: "delete",
            corkboard: CORKBOARD_DATA.corkboard.path,
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
      if (!CORKBOARD_DATA.context_id || boardType !== "folder") {{
        return;
      }}
      await fetch(contextUrl("/api/creative/corkboard"), {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          board_type: "folder",
          folder: CORKBOARD_DATA.folder.path,
          order: cards.map((card) => card.path),
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
          type: "electroboy-creative-open",
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
          type: "electroboy-creative-open",
          path: card.board_path,
          entry_type: "corkboard",
        }},
        window.location.origin,
      );
    }}

    async function convertCardToGroup(card, cardElement, button) {{
      if (boardType !== "freeform") {{
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
      const icon = document.createElement("span");
      icon.className = "card-stack-icon";
      icon.setAttribute("aria-hidden", "true");
      button.append(icon);
      return button;
    }}

    function startDrag(event) {{
      if (event.button !== 0 || event.target.closest("textarea, button")) {{
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

    function renderCards() {{
      board.replaceChildren();
      folderInsertionMarker = null;
      clearFolderInsertionMarker();
      board.className = `board ${{boardType}}`;
      boardEyebrow.textContent = boardType === "freeform"
        ? "Freeform corkboard"
        : "Folder board";
      addCard.hidden = boardType !== "freeform";
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
          cardElement.draggable = true;
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
          title.addEventListener("input", () => {{
            card.title = title.value;
            queueSave(card);
          }});
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
          tools.append(buildColorButton(card, cardElement));
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
          tools.append(buildColorButton(card, cardElement));
          tools.append(buildGroupButton(card, cardElement));
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
          tools.append(remove);
          head.append(titleBox, tools);
        }}

        const note = document.createElement("textarea");
        note.className = "card-note";
        note.spellcheck = true;
        note.value = card.note || "";
        note.addEventListener("input", () => {{
          card.note = note.value;
          queueSave(card);
        }});

        cardElement.append(head, note);
        board.append(cardElement);
      }}
      sizeBoard();
    }}

    addCard.addEventListener("click", makeFreeformCard);
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
    return {
        "schema_version": 1,
        "board_type": "freeform",
        "context_id": context_id,
        "palette": _creative_card_palette_payload(),
        "title": title or corkboard_path.name.removesuffix(CREATIVE_CORKBOARD_SUFFIX),
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
    return [
        child
        for child in children
        if child.name not in CREATIVE_IGNORED_NAMES and not child.name.startswith(".")
    ]


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


def _ensure_creative_card_group_corkboard(
    project_root: Path | str,
    *,
    parent_corkboard_path: str,
    card_id: str,
    board_path: object,
) -> str:
    normalized_board_path = _normalize_creative_corkboard_reference(board_path)
    if not normalized_board_path:
        normalized_board_path = _creative_card_group_default_path(
            parent_corkboard_path,
            card_id,
        )
    _create_creative_corkboard(project_root, normalized_board_path)
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
    cards = _creative_corkboard_folder_cards(folder_state)
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


def _resolved_artifact_relative_path(
    project_root: Path | str,
    default_relative_path: str,
) -> str:
    project_root = Path(project_root).expanduser().resolve()
    relative_path = default_relative_path
    run_id = StateStore(project_root).current_run_id()
    if run_id:
        relative_path = resolve_artifact_path(
            artifact_paths_for_run(project_root, run_id),
            default_relative_path,
        )
    return _document_target_path(project_root, relative_path)[0]


def _resolved_artifact_document_path(
    project_root: Path | str,
    default_relative_path: str,
) -> Path:
    project_root = Path(project_root).expanduser().resolve()
    relative_path = _resolved_artifact_relative_path(
        project_root,
        default_relative_path,
    )
    return _document_target_path(project_root, relative_path)[1]


def _artifact_event_document_path(
    project_root: Path | str,
    artifact: str,
    requested_path: str,
) -> Path:
    project_root = Path(project_root).expanduser().resolve()
    if artifact == "requirements":
        return _resolved_artifact_document_path(project_root, "docs/requirements.md")
    if artifact == "document":
        return _document_target_path(project_root, requested_path)[1]
    if artifact == "route":
        relative_path = ARTIFACT_EVENT_ROUTE_PATHS.get(requested_path)
        if relative_path is None:
            raise StateError(f"unknown artifact route: {requested_path}")
        return _resolved_artifact_document_path(project_root, relative_path)
    raise StateError(f"unknown artifact: {artifact}")


def _file_signature(path: Path) -> dict[str, object]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {"exists": False, "mtime_ns": 0, "size": 0}
    return {
        "exists": True,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def _render_markdown(text: str) -> str:
    try:
        import markdown as markdown_library
    except ImportError:
        return _render_basic_markdown(text)
    rendered = str(
        markdown_library.markdown(
            _enable_markdown_in_details(text),
            extensions=["extra", "sane_lists", "md_in_html"],
        )
    )
    return _promote_mermaid_blocks(rendered)


_DETAILS_TAG_RE = re.compile(r"<details(?P<attrs>[^>]*)>", re.IGNORECASE)


def _enable_markdown_in_details(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        attrs = match.group("attrs") or ""
        if re.search(r"\smarkdown\s*=", attrs, re.IGNORECASE):
            return match.group(0)
        return f'<details{attrs} markdown="1">'

    return _DETAILS_TAG_RE.sub(replace, text)


def _render_basic_markdown(text: str) -> str:
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    code_lines: list[str] = []
    code_language = ""

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{html.escape(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            items = "".join(f"<li>{html.escape(item)}</li>" for item in list_items)
            blocks.append(f"<ul>{items}</ul>")
            list_items.clear()

    def flush_code() -> None:
        nonlocal code_language
        escaped = html.escape("\n".join(code_lines))
        language = code_language.strip().lower()
        if language == "mermaid":
            blocks.append(f'<div class="mermaid">{escaped}</div>')
        else:
            class_attr = (
                f' class="language-{html.escape(language)}"'
                if language
                else ""
            )
            blocks.append(f"<pre><code{class_attr}>{escaped}</code></pre>")
        code_lines.clear()
        code_language = ""

    for raw_line in text.splitlines():
        if code_language:
            if raw_line.strip() == "```":
                flush_code()
            else:
                code_lines.append(raw_line)
            continue
        line = raw_line.strip()
        if line.startswith("```"):
            flush_paragraph()
            flush_list()
            code_language = line[3:].strip() or "plain"
            continue
        if not line:
            flush_paragraph()
            flush_list()
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading is not None:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            title = html.escape(heading.group(2).strip())
            blocks.append(f"<h{level}>{title}</h{level}>")
            continue
        if line.startswith("- "):
            flush_paragraph()
            list_items.append(line[2:].strip())
            continue
        flush_list()
        paragraph.append(line)
    if code_language:
        flush_code()
    flush_paragraph()
    flush_list()
    return "\n".join(blocks) if blocks else "<p></p>"


_MERMAID_BLOCK_RE = re.compile(
    r'<pre><code class="(?:language-)?mermaid">(?P<body>.*?)</code></pre>',
    re.DOTALL,
)


def _promote_mermaid_blocks(rendered: str) -> str:
    return _MERMAID_BLOCK_RE.sub(
        lambda match: f'<div class="mermaid">{match.group("body")}</div>',
        rendered,
    )


def _mermaid_script(rendered: str) -> str:
    if 'class="mermaid"' not in rendered:
        return ""
    return """
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <script>
    window.addEventListener("DOMContentLoaded", () => {
      const popupFeatures =
        "popup=yes,width=980,height=720,menubar=no,toolbar=no,location=no,status=no,scrollbars=yes,resizable=yes";

      function prepareMermaidPopouts() {
        for (const diagram of document.querySelectorAll(".mermaid")) {
          if (diagram.dataset.electroboyPopout === "1") {
            continue;
          }
          diagram.dataset.electroboyPopout = "1";
          diagram.tabIndex = 0;
          diagram.setAttribute("role", "button");
          diagram.setAttribute(
            "aria-label",
            "Open Mermaid diagram in a separate window",
          );
          diagram.title = "Open diagram";
          diagram.addEventListener("click", () => openMermaidPopup(diagram));
          diagram.addEventListener("keydown", (event) => {
            if (event.key !== "Enter" && event.key !== " ") {
              return;
            }
            event.preventDefault();
            openMermaidPopup(diagram);
          });
        }
      }

      function openMermaidPopup(diagram) {
        let popupUrl = "";
        try {
          popupUrl = URL.createObjectURL(new Blob(
            [mermaidPopupHtml(diagramMarkup(diagram))],
            { type: "text/html" },
          ));
        } catch (error) {
          console.warn("Could not prepare Mermaid popup", error);
          return;
        }
        const popup = window.open(
          popupUrl,
          "electroboy-mermaid-diagram",
          popupFeatures,
        );
        if (!popup) {
          URL.revokeObjectURL(popupUrl);
          return;
        }
        window.setTimeout(() => URL.revokeObjectURL(popupUrl), 30000);
      }

      function diagramMarkup(diagram) {
        const clone = diagram.cloneNode(true);
        clone.classList.add("popup-mermaid-diagram");
        clone.removeAttribute("tabindex");
        clone.removeAttribute("role");
        clone.removeAttribute("title");
        return clone.outerHTML;
      }

      function mermaidPopupHtml(diagramHtml) {
        return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mermaid diagram</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #10141f;
      --panel: #151b29;
      --text: #e7edf7;
      --muted: #aab8cf;
      --border: #2a3142;
      --button: #1d2638;
      --accent: #66d9e8;
    }
    * {
      box-sizing: border-box;
    }
    html,
    body {
      height: 100%;
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system,
        BlinkMacSystemFont, "Segoe UI", sans-serif;
      overflow: hidden;
    }
    .diagram-window {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      height: 100vh;
    }
    .diagram-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 42px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
      padding: 0 12px;
    }
    .diagram-title {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
      text-transform: uppercase;
    }
    .diagram-controls {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .diagram-controls button {
      min-width: 34px;
      height: 30px;
      border: 1px solid #364156;
      border-radius: 6px;
      background: var(--button);
      color: var(--text);
      cursor: pointer;
      font: inherit;
      font-size: 13px;
      font-weight: 750;
    }
    .diagram-controls button:hover:not(:disabled) {
      border-color: var(--accent);
      background: #22314a;
    }
    .diagram-controls button:disabled {
      cursor: default;
      opacity: 0.45;
    }
    .zoom-level {
      min-width: 48px;
      text-align: center;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
    }
    .diagram-viewport {
      min-height: 0;
      height: 100%;
      width: 100%;
      overflow: auto;
      background: var(--bg);
      cursor: grab;
      user-select: none;
    }
    .diagram-viewport.dragging {
      cursor: grabbing;
    }
    .diagram-viewport.dragging * {
      user-select: none;
    }
    .diagram-content {
      display: inline-block;
      min-height: 100%;
      min-width: 100%;
      padding: 24px;
    }
    .diagram-content .mermaid {
      display: inline-block;
      margin: 0;
      padding: 0;
      border: 0;
      background: transparent;
      cursor: default;
    }
    .diagram-content svg {
      display: block;
      max-width: none !important;
      max-height: none !important;
      height: auto;
      overflow: visible;
    }
  </style>
</head>
<body>
  <main class="diagram-window">
    <header class="diagram-toolbar">
      <span id="diagramTitle" class="diagram-title">Mermaid diagram</span>
      <div class="diagram-controls">
        <button id="zoomOut" type="button" title="Zoom out" aria-label="Zoom out">-</button>
        <span id="zoomLevel" class="zoom-level">100%</span>
        <button id="zoomReset" type="button" title="Reset zoom" aria-label="Reset zoom">100%</button>
        <button id="zoomIn" type="button" title="Zoom in" aria-label="Zoom in">+</button>
      </div>
    </header>
    <section class="diagram-viewport">
      <div id="diagramContent" class="diagram-content">${diagramHtml}</div>
    </section>
  </main>
  <script>
    (() => {
      const minimumZoom = 0.4;
      const maximumZoom = 4;
      const zoomStep = 0.25;
      let zoom = 1;
      let naturalWidth = 0;
      let naturalHeight = 0;
      let baseWidth = 0;
      let baseHeight = 0;
      let panState = null;
      const content = document.getElementById("diagramContent");
      const viewport = document.querySelector(".diagram-viewport");
      const toolbar = document.querySelector(".diagram-toolbar");
      const zoomLevel = document.getElementById("zoomLevel");
      const zoomOut = document.getElementById("zoomOut");
      const zoomReset = document.getElementById("zoomReset");
      const zoomIn = document.getElementById("zoomIn");

      function contentBox(svg) {
        try {
          const box = svg.getBBox();
          if (
            Number.isFinite(box.x) &&
            Number.isFinite(box.y) &&
            Number.isFinite(box.width) &&
            Number.isFinite(box.height) &&
            box.width > 0 &&
            box.height > 0
          ) {
            return box;
          }
        } catch (error) {
          return null;
        }
        return null;
      }

      function readSvgDimensions(svg) {
        const box = contentBox(svg);
        if (box) {
          svg.setAttribute(
            "viewBox",
            [box.x, box.y, box.width, box.height].join(" "),
          );
          svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
          return { width: box.width, height: box.height };
        }
        const viewBox = (svg.getAttribute("viewBox") || "")
          .trim()
          .split(/\\s+/)
          .map(Number);
        const width = viewBox.length === 4 && Number.isFinite(viewBox[2])
          ? viewBox[2]
          : Number.parseFloat(svg.getAttribute("width")) || svg.clientWidth || 800;
        const height = viewBox.length === 4 && Number.isFinite(viewBox[3])
          ? viewBox[3]
          : Number.parseFloat(svg.getAttribute("height")) || svg.clientHeight || 600;
        return { width, height };
      }

      function updateBaseSize() {
        if (!naturalWidth || !naturalHeight) {
          return;
        }
        const viewportRect = viewport.getBoundingClientRect();
        const toolbarRect = toolbar.getBoundingClientRect();
        const viewportWidth = viewportRect.width || window.innerWidth || 980;
        const viewportHeight =
          viewportRect.height ||
          Math.max(220, (window.innerHeight || 720) - toolbarRect.height);
        const availableWidth = Math.max(320, viewportWidth - 48);
        const availableHeight = Math.max(220, viewportHeight - 48);
        const fitScale = Math.min(
          availableWidth / naturalWidth,
          availableHeight / naturalHeight,
        );
        const scale = Math.max(0.1, fitScale);
        baseWidth = naturalWidth * scale;
        baseHeight = naturalHeight * scale;
      }

      function applyZoom() {
        const svg = content.querySelector("svg");
        if (svg) {
          svg.style.width = (baseWidth * zoom) + "px";
          svg.style.height = (baseHeight * zoom) + "px";
        } else {
          content.style.fontSize = (16 * zoom) + "px";
        }
        zoomLevel.textContent = Math.round(zoom * 100) + "%";
        zoomOut.disabled = zoom <= minimumZoom;
        zoomIn.disabled = zoom >= maximumZoom;
      }

      function changeZoom(delta) {
        zoom = Math.max(minimumZoom, Math.min(maximumZoom, zoom + delta));
        applyZoom();
      }

      function startPan(event) {
        if (event.button !== 0 || event.target.closest("a")) {
          return;
        }
        event.preventDefault();
        panState = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          scrollLeft: viewport.scrollLeft,
          scrollTop: viewport.scrollTop,
        };
        viewport.classList.add("dragging");
        viewport.setPointerCapture(event.pointerId);
      }

      function updatePan(event) {
        if (!panState || event.pointerId !== panState.pointerId) {
          return;
        }
        event.preventDefault();
        viewport.scrollLeft = panState.scrollLeft - (event.clientX - panState.startX);
        viewport.scrollTop = panState.scrollTop - (event.clientY - panState.startY);
      }

      function finishPan(event) {
        if (!panState || event.pointerId !== panState.pointerId) {
          return;
        }
        panState = null;
        viewport.classList.remove("dragging");
        try {
          viewport.releasePointerCapture(event.pointerId);
        } catch (error) {
          return;
        }
      }

      function initializeDiagramPopup(title) {
        const svg = content.querySelector("svg");
        if (svg) {
          const dimensions = readSvgDimensions(svg);
          naturalWidth = dimensions.width;
          naturalHeight = dimensions.height;
          updateBaseSize();
        }
        applyZoom();
      }

      function fitAfterLayout() {
        initializeDiagramPopup("Mermaid diagram");
      }

      zoomOut.addEventListener("click", () => changeZoom(-zoomStep));
      zoomReset.addEventListener("click", () => {
        zoom = 1;
        applyZoom();
      });
      zoomIn.addEventListener("click", () => changeZoom(zoomStep));
      viewport.addEventListener("pointerdown", startPan);
      viewport.addEventListener("pointermove", updatePan);
      viewport.addEventListener("pointerup", finishPan);
      viewport.addEventListener("pointercancel", finishPan);
      window.addEventListener("resize", () => {
        updateBaseSize();
        applyZoom();
      });
      window.requestAnimationFrame(() => {
        fitAfterLayout();
        window.requestAnimationFrame(fitAfterLayout);
      });
      window.setTimeout(fitAfterLayout, 100);
    })();
  <\\/script>
</body>
</html>`;
      }

      async function renderMermaidBlocks() {
        if (!window.mermaid) {
          prepareMermaidPopouts();
          return;
        }
        window.mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "base",
          themeVariables: {
            background: "#10141f",
            mainBkg: "#151b29",
            primaryColor: "#151b29",
            primaryTextColor: "#e7edf7",
            primaryBorderColor: "#364156",
            lineColor: "#66d9e8",
            secondaryColor: "#1d2638",
            secondaryTextColor: "#e7edf7",
            tertiaryColor: "#10141f",
            tertiaryTextColor: "#e7edf7",
            textColor: "#e7edf7",
            nodeBorder: "#364156",
            clusterBkg: "#10141f",
            clusterBorder: "#2a3142",
            edgeLabelBackground: "#10141f",
            fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
          },
        });
        try {
          await window.mermaid.run({ querySelector: ".mermaid" });
        } catch (error) {
          console.warn("Mermaid render failed", error);
        }
        prepareMermaidPopouts();
      }

      renderMermaidBlocks();
    });
  </script>
"""


def _requirements_command(root: Path) -> list[str]:
    return _electroboy_command(root, ["requirements"])


def _stage_command(
    root: Path,
    command: str,
    *,
    force: bool = False,
    reason: str | None = None,
    interactive: bool = False,
) -> list[str]:
    command_parts = ["electroboy", command]
    if force:
        command_parts.append("--force")
    if reason:
        command_parts.extend(["--reason", reason])
    if interactive:
        command_parts.append("--interactive")
    return _electroboy_command(root, command_parts[1:])


def _progress_once_command(root: Path) -> list[str]:
    return _electroboy_command(root, ["progress", "--once"])


def _status_command(root: Path) -> list[str]:
    return _electroboy_command(root, ["status"])


def _documentation_command(
    root: Path,
    *,
    interactive: bool = True,
    target: str | None = None,
) -> list[str]:
    args = ["document", "--sidecar"]
    if interactive:
        args.append("--interactive")
    if target:
        args.extend(["--target", target])
    return _electroboy_command(root, args)


def _ad_hoc_agent_command(root: Path) -> list[str]:
    return [
        "codex",
        "--cd",
        str(root),
        "--sandbox",
        "workspace-write",
        _ad_hoc_agent_prompt(),
    ]


def _ad_hoc_agent_prompt() -> str:
    return "Here is the code base. Follow what the operator says."


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


def _project_shell_command() -> list[str]:
    candidates = [
        os.environ.get("SHELL", "").strip(),
        "/bin/bash",
        "/bin/sh",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return [candidate]
    return ["/bin/sh"]


def _electroboy_command(root: Path, args: list[str]) -> list[str]:
    activate_script = root / ".electroboy" / "bin" / "activate"
    command_parts = [
        sys.executable,
        "-m",
        "electroboy",
        "--root",
        str(root),
        *args,
    ]
    command_text = " ".join(shlex.quote(part) for part in command_parts)
    if activate_script.exists():
        module_path = shlex.quote(str(_service_module_search_path()))
        return [
            "/bin/sh",
            "-c",
            f". {shlex.quote(str(activate_script))} >/dev/null && "
            f"PYTHONPATH={module_path}${{PYTHONPATH:+:$PYTHONPATH}} "
            f"{command_text}",
        ]
    return command_parts


def _service_module_search_path() -> Path:
    return Path(__file__).resolve().parents[1]


def _progress_snapshot(root: Path | str, timeout: float = 5.0) -> tuple[str, bool]:
    project_root = Path(root).expanduser().resolve()
    try:
        completed = subprocess.run(
            _progress_once_command(project_root),
            cwd=project_root,
            env=_agent_process_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        output = _subprocess_output_text(error.stdout)
        if output and not output.endswith("\n"):
            output += "\n"
        return f"{output}progress command timed out\n", False
    output = completed.stdout or ""
    if completed.returncode != 0:
        if output and not output.endswith("\n"):
            output += "\n"
        output += f"progress command exited with code {completed.returncode}\n"
        return output, False
    return output or "progress: none\n", True


def _status_snapshot(root: Path | str, timeout: float = 5.0) -> tuple[str, bool]:
    project_root = Path(root).expanduser().resolve()
    try:
        completed = subprocess.run(
            _status_command(project_root),
            cwd=project_root,
            env=_agent_process_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        output = _subprocess_output_text(error.stdout)
        if output and not output.endswith("\n"):
            output += "\n"
        return f"{output}status command timed out\n", False
    output = completed.stdout or ""
    if completed.returncode != 0:
        if output and not output.endswith("\n"):
            output += "\n"
        output += f"status command exited with code {completed.returncode}\n"
        return output, False
    return output or "status: none\n", True


def _subprocess_output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _terminal_input_for_message(message: str) -> str:
    return "".join(_terminal_input_chunks_for_message(message))


def _terminal_input_for_key(key: str) -> str:
    if re.fullmatch(r"[0-9]", key):
        return key
    keys = {
        "enter": "\r",
        "escape": "\x1b",
        "tab": "\t",
        "backspace": "\x7f",
        "delete": "\x1b[3~",
        "up": "\x1b[A",
        "down": "\x1b[B",
        "right": "\x1b[C",
        "left": "\x1b[D",
    }
    try:
        return keys[key]
    except KeyError:
        choices = ", ".join(sorted(keys))
        raise AgentSessionError(
            f"unknown terminal key {key!r}; choose one of: {choices}, 0-9"
        )


def _terminal_input_chunks_for_message(message: str) -> list[str]:
    text = message.replace("\r\n", "\n").replace("\r", "\n")
    text = text.rstrip("\n")
    if "\n" in text:
        return [f"\x1b[200~{text}\x1b[201~", "\r"]
    return [text, "\r"]


def _disable_terminal_echo(slave_fd: int) -> None:
    try:
        attributes = termios.tcgetattr(slave_fd)
        attributes[3] &= ~(
            termios.ECHO
            | termios.ECHOE
            | termios.ECHOK
            | termios.ECHONL
        )
        termios.tcsetattr(slave_fd, termios.TCSANOW, attributes)
    except termios.error:
        return


def _clamp_terminal_columns(columns: int) -> int:
    return max(MIN_TERMINAL_COLUMNS, min(columns, MAX_TERMINAL_COLUMNS))


def _clamp_terminal_rows(rows: int) -> int:
    return max(MIN_TERMINAL_ROWS, min(rows, MAX_TERMINAL_ROWS))


def _set_terminal_size(fd: int, columns: int, rows: int) -> None:
    columns = _clamp_terminal_columns(columns)
    rows = _clamp_terminal_rows(rows)
    packed_size = struct.pack("HHHH", rows, columns, 0, 0)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, packed_size)
    except OSError:
        return


def _agent_process_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    env["ELECTROBOY_DISABLE_SESSION_RESUME"] = "1"
    env.pop("NO_COLOR", None)
    env.pop("CLICOLOR", None)
    env.pop("FORCE_COLOR", None)
    module_path = str(_module_search_path())
    existing_pythonpath = env.get("PYTHONPATH", "")
    entries = [module_path]
    entries.extend(
        entry
        for entry in existing_pythonpath.split(os.pathsep)
        if entry and entry != module_path
    )
    env["PYTHONPATH"] = os.pathsep.join(entries)
    return env


def _module_search_path() -> Path:
    return Path(__file__).resolve().parents[1]


def _clean_terminal_output(
    text: str,
    pending: str = "",
) -> tuple[str, str]:
    combined = f"{pending}{text}"
    output: list[str] = []
    index = 0
    while index < len(combined):
        char = combined[index]
        if char == "\x1b":
            consumed, incomplete = _terminal_escape_length(combined, index)
            if incomplete:
                return _normalize_terminal_text("".join(output)), combined[index:]
            index += consumed
            continue
        if char == "\r":
            if index + 1 < len(combined) and combined[index + 1] == "\n":
                output.append("\n")
                index += 2
            else:
                output.append("\n")
                index += 1
            continue
        if char == "\b":
            if output and output[-1] != "\n":
                output.pop()
            index += 1
            continue
        if char in _CONTROL_CHARS_TO_DROP:
            index += 1
            continue
        output.append(char)
        index += 1
    return _normalize_terminal_text("".join(output)), ""


def _terminal_escape_length(text: str, index: int) -> tuple[int, bool]:
    if index + 1 >= len(text):
        return len(text) - index, True
    introducer = text[index + 1]
    if introducer == "[":
        return _consume_until_final_byte(text, index, 2)
    if introducer == "]":
        return _consume_string_control(text, index)
    if introducer in {"P", "^", "_", "X"}:
        return _consume_string_control(text, index)
    if introducer in {"(", ")", "*", "+", "-", ".", "/"}:
        if index + 2 >= len(text):
            return len(text) - index, True
        return 3, False
    if "@" <= introducer <= "_":
        return 2, False
    return 1, False


def _consume_until_final_byte(
    text: str,
    index: int,
    offset: int,
) -> tuple[int, bool]:
    cursor = index + offset
    while cursor < len(text):
        if "@" <= text[cursor] <= "~":
            return cursor - index + 1, False
        cursor += 1
    return len(text) - index, True


def _consume_string_control(text: str, index: int) -> tuple[int, bool]:
    cursor = index + 2
    while cursor < len(text):
        char = text[cursor]
        if char == "\x07":
            return cursor - index + 1, False
        if char == "\x1b":
            if cursor + 1 < len(text) and text[cursor + 1] == "\\":
                return cursor - index + 2, False
            return cursor - index, False
        cursor += 1
    return len(text) - index, True


def _normalize_terminal_text(text: str) -> str:
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text


def _markdown_code_block(text: str, language: str = "") -> str:
    body = text.rstrip("\n")
    fence = "```"
    while fence in body:
        fence += "`"
    return f"{fence}{language}\n{body}\n{fence}"


def _session_export_filename(session: AgentSession) -> str:
    kind = _download_name_part(session.kind or "agent")
    timestamp = _download_name_part(utc_now())
    return f"agent-session-{kind}-{timestamp}.md"


def _progress_export_filename() -> str:
    return f"progress-log-{_download_name_part(utc_now())}.md"


def _download_name_part(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    text = text.strip(".-")
    return text or "export"


def _session_events_markdown(session: AgentSession) -> str:
    events = session.events()
    payload = session.payload()
    lines = [
        "# Agent Session Export",
        "",
        "## Metadata",
        "",
        f"- Session id: `{session.session_id}`",
        f"- Kind: `{session.kind}`",
        f"- Label: {session.label}",
        f"- Status: `{payload.get('status', session.status)}`",
        f"- Created: {session.created_at}",
        f"- Exported: {utc_now()}",
        f"- Working directory: `{session.cwd}`",
        f"- Interactive: `{str(session.interactive).lower()}`",
        f"- Return code: `{session.returncode}`",
        "",
        "### Command",
        "",
        _markdown_code_block(shlex.join(session.command), "console"),
        "",
        "## Transcript",
        "",
    ]
    if not events:
        lines.extend(["No events were recorded.", ""])
        return "\n".join(lines).rstrip() + "\n"

    pending_output: list[str] = []
    pending_start: int | None = None
    pending_end: int | None = None

    def flush_output() -> None:
        nonlocal pending_output, pending_start, pending_end
        if not pending_output:
            return
        title = (
            f"### Output Events {pending_start}-{pending_end}"
            if pending_start != pending_end
            else f"### Output Event {pending_start}"
        )
        lines.extend([title, "", _markdown_code_block("".join(pending_output), "text"), ""])
        pending_output = []
        pending_start = None
        pending_end = None

    for event in events:
        event_id = int(event.get("id", 0) or 0)
        event_type = str(event.get("type") or "event")
        if event_type == "output":
            if pending_start is None:
                pending_start = event_id
            pending_end = event_id
            pending_output.append(str(event.get("text") or ""))
            continue
        flush_output()
        if event_type == "completed":
            lines.extend(
                [
                    f"### Event {event_id}: completed",
                    "",
                    f"- Return code: `{event.get('returncode')}`",
                    "",
                ]
            )
            continue
        text = str(event.get("text") or "")
        lines.extend(
            [
                f"### Event {event_id}: {event_type}",
                "",
                _markdown_code_block(text, "text") if text else "_No event text._",
                "",
            ]
        )
    flush_output()
    return "\n".join(lines).rstrip() + "\n"


def _progress_snapshot_markdown(project_root: Path, text: str, ok: bool) -> str:
    return "\n".join(
        [
            "# Progress Log Export",
            "",
            "## Metadata",
            "",
            f"- Project root: `{project_root}`",
            f"- Exported: {utc_now()}",
            f"- Snapshot status: `{'ok' if ok else 'error'}`",
            "",
            "## Progress",
            "",
            _markdown_code_block(text, "text"),
            "",
        ]
    )


def _handler_for(
    config: ServiceConfig,
    state: ServiceState,
) -> type[BaseHTTPRequestHandler]:
    class ElectroBoyRequestHandler(BaseHTTPRequestHandler):
        server_version = "ElectroBoyService/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path in {"/", "/index.html"}:
                self._send_text(INDEX_HTML, "text/html; charset=utf-8")
                return
            if path == SPLASH_IMAGE_ROUTE:
                self._send_splash_image(SPLASH_IMAGE_RESOURCE)
                return
            if path == CREATIVE_SPLASH_IMAGE_ROUTE:
                self._send_splash_image(CREATIVE_SPLASH_IMAGE_RESOURCE)
                return
            if path == "/file-browser":
                self._send_file_browser_window(parsed.query)
                return
            if path.startswith("/pane/"):
                self._send_pane_window(path)
                return
            if path == "/api/health":
                self._send_json(health_payload(config.root))
                return
            if path == "/api/project":
                self._send_context_json(
                    parsed.query,
                    lambda context_id: state.project_payload(context_id),
                )
                return
            if path == "/api/project/status":
                self._send_context_json(
                    parsed.query,
                    lambda context_id: state.project_status_payload(context_id),
                )
                return
            if path == "/api/workflow":
                self._send_context_json(
                    parsed.query,
                    lambda context_id: state.workflow_payload(context_id),
                )
                return
            if path == "/api/sessions":
                self._send_context_json(
                    parsed.query,
                    lambda context_id: state.session_payload(context_id),
                )
                return
            if path == "/api/sessions/export":
                self._send_session_export(parsed.query)
                return
            if path == "/api/progress/export":
                self._send_progress_export(parsed.query)
                return
            if path == "/api/documents/export":
                self._send_document_export(parsed.query)
                return
            if path == "/api/creative/tree":
                self._send_context_json(
                    parsed.query,
                    lambda context_id: state.creative_tree(context_id),
                )
                return
            if path == "/api/creative/scratch":
                self._send_context_json(
                    parsed.query,
                    lambda context_id: state.creative_scratchpad(context_id),
                )
                return
            if path == "/artifacts/edit":
                self._send_artifact_editor(parsed.query)
                return
            if path == "/api/files/browse":
                self._browse_files(parsed.query)
                return
            if path == "/artifacts/requirements":
                self._send_requirements_document(parsed.query)
                return
            if path == "/artifacts/design":
                self._send_design_document(parsed.query)
                return
            if path == "/artifacts/design-review":
                self._send_design_review_document(parsed.query)
                return
            if path == "/artifacts/implementation-plan":
                self._send_stage_document(parsed.query, "implementation-plan")
                return
            if path == "/artifacts/test-plan":
                self._send_stage_document(parsed.query, "test-plan")
                return
            if path == "/artifacts/implementation-report":
                self._send_stage_document(parsed.query, "code")
                return
            if path == "/artifacts/validation-report":
                self._send_stage_document(parsed.query, "validate")
                return
            if path == "/artifacts/document":
                self._send_document_target(parsed.query)
                return
            if path == "/artifacts/creative-corkboard":
                self._send_creative_corkboard(parsed.query)
                return
            if path == "/api/progress/events":
                self._send_progress_events(parsed.query)
                return
            if path == "/api/artifacts/events":
                self._send_artifact_events(parsed.query)
                return
            if path == "/api/sessions/events":
                self._send_selected_session_events(parsed.query)
                return
            if path == "/api/shell/events":
                self._send_project_shell_events(parsed.query)
                return
            if path == "/api/agents/requirements/events":
                self._send_agent_events(parsed.query)
                return
            if path == "/api/agents/design/events":
                self._send_design_agent_events(parsed.query)
                return
            if path == "/api/agents/design-review/events":
                self._send_design_review_agent_events(parsed.query)
                return
            self._send_json(
                {"error": "not found"},
                status=HTTPStatus.NOT_FOUND,
            )

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/contexts":
                self._send_json(state.create_context())
                return
            if path == "/api/project/open":
                self._open_project(parsed.query)
                return
            if path == "/api/project/new":
                self._create_project(parsed.query)
                return
            if path == "/api/meta/init":
                self._create_meta_project(parsed.query)
                return
            if path == "/api/meta/add":
                self._add_meta_repository(parsed.query)
                return
            if path == "/api/meta/start":
                self._start_meta_repository(parsed.query)
                return
            if path == "/api/meta/remove":
                self._remove_meta_repository(parsed.query)
                return
            if path == "/api/work-items/collections":
                self._create_feature_collection(parsed.query)
                return
            if path == "/api/work-items/collections/switch":
                self._switch_feature_collection(parsed.query)
                return
            if path == "/api/work-items/features":
                self._start_feature_work_item(parsed.query)
                return
            if path == "/api/work-items/features/switch":
                self._switch_feature_work_item(parsed.query)
                return
            if path == "/api/work-items/bugs":
                self._start_bug_work_item(parsed.query)
                return
            if path == "/api/work-items/bugs/switch":
                self._switch_bug_work_item(parsed.query)
                return
            if path == "/api/project/deactivate":
                self._deactivate_project(parsed.query)
                return
            if path == "/api/workflow/stage":
                self._select_workflow_stage(parsed.query)
                return
            if path == "/api/artifacts/edit":
                self._save_artifact_editor(parsed.query)
                return
            if path == "/api/creative/project/open":
                self._open_creative_project(parsed.query)
                return
            if path == "/api/creative/project/new":
                self._create_creative_project(parsed.query)
                return
            if path == "/api/creative/init":
                self._initialize_creative_workspace(parsed.query)
                return
            if path == "/api/creative/folders":
                self._create_creative_folder(parsed.query)
                return
            if path == "/api/creative/documents":
                self._create_creative_document(parsed.query)
                return
            if path == "/api/creative/corkboards":
                self._create_creative_corkboard(parsed.query)
                return
            if path == "/api/creative/rename":
                self._rename_creative_entry(parsed.query)
                return
            if path == "/api/creative/delete":
                self._delete_creative_entry(parsed.query)
                return
            if path == "/api/creative/scratch":
                self._save_creative_scratchpad(parsed.query)
                return
            if path == "/api/creative/corkboard":
                self._save_creative_corkboard(parsed.query)
                return
            if path == "/api/creative/agent/start":
                self._start_creative_writing_agent(parsed.query)
                return
            if path == "/api/agents/ad-hoc/start":
                self._start_ad_hoc_agent(parsed.query)
                return
            if path == "/api/sessions/select":
                self._select_session(parsed.query)
                return
            if path == "/api/sessions/message":
                self._send_selected_session_message(parsed.query)
                return
            if path == "/api/sessions/key":
                self._send_selected_session_key(parsed.query)
                return
            if path == "/api/sessions/raw":
                self._send_selected_session_raw(parsed.query)
                return
            if path == "/api/sessions/interrupt":
                self._interrupt_selected_session(parsed.query)
                return
            if path == "/api/sessions/resize":
                self._resize_selected_session(parsed.query)
                return
            if path == "/api/shell/start":
                self._start_project_shell(parsed.query)
                return
            if path == "/api/shell/input":
                self._send_project_shell_input(parsed.query)
                return
            if path == "/api/shell/resize":
                self._resize_project_shell(parsed.query)
                return
            if path == "/api/shell/stop":
                self._stop_project_shell(parsed.query)
                return
            if path == "/api/agents/requirements/start":
                self._start_requirements_agent(parsed.query)
                return
            if path == "/api/agents/requirements/restart":
                self._restart_requirements_agent(parsed.query)
                return
            if path == "/api/agents/requirements/complete":
                self._complete_requirements_agent(parsed.query)
                return
            if path == "/api/agents/requirements/skip":
                self._skip_requirements_approval(parsed.query)
                return
            if path == "/api/agents/requirements/skip-approval":
                self._skip_requirements_approval(parsed.query)
                return
            if path == "/api/agents/requirements/approve":
                self._approve_requirements(parsed.query)
                return
            if path == "/api/agents/requirements/message":
                self._send_requirements_message(parsed.query)
                return
            if path == "/api/agents/requirements/interrupt":
                self._interrupt_requirements_agent(parsed.query)
                return
            if path == "/api/agents/requirements/resize":
                self._resize_requirements_agent(parsed.query)
                return
            if path == "/api/agents/design/start":
                self._start_design_agent(parsed.query)
                return
            if path == "/api/agents/design/restart":
                self._restart_design_agent(parsed.query)
                return
            if path == "/api/agents/design/complete":
                self._complete_design_agent(parsed.query)
                return
            if path == "/api/agents/design/message":
                self._send_design_message(parsed.query)
                return
            if path == "/api/agents/design/interrupt":
                self._interrupt_design_agent(parsed.query)
                return
            if path == "/api/agents/design/resize":
                self._resize_design_agent(parsed.query)
                return
            if path == "/api/agents/design-review/start":
                self._start_design_review_agent(parsed.query)
                return
            if path == "/api/agents/design-review/start-interactive":
                self._start_interactive_design_review_agent(parsed.query)
                return
            if path == "/api/agents/design-review/stop":
                self._stop_design_review_agent(parsed.query)
                return
            if path == "/api/agents/design-review/complete":
                self._complete_design_review_agent(parsed.query)
                return
            if path == "/api/agents/design-review/approve":
                self._approve_design(parsed.query)
                return
            if path == "/api/agents/design-review/skip-approval":
                self._skip_design_approval(parsed.query)
                return
            if path == "/api/agents/design-review/restart":
                self._restart_design_review_agent(parsed.query)
                return
            if path == "/api/agents/design-review/interrupt":
                self._interrupt_design_review_agent(parsed.query)
                return
            if path == "/api/agents/design-review/resize":
                self._resize_design_review_agent(parsed.query)
                return
            generic_route = _generic_agent_route(path)
            if generic_route is not None:
                stage, action = generic_route
                self._handle_generic_stage_agent(parsed.query, stage, action)
                return
            if path == "/api/agents/documentation/start":
                self._start_documentation_agent(parsed.query)
                return
            if path == "/api/agents/design-approve/approve":
                self._approve_design(parsed.query)
                return
            self._send_json(
                {"error": "not found"},
                status=HTTPStatus.NOT_FOUND,
            )

        def do_HEAD(self) -> None:
            path = urlparse(self.path).path
            if path in {"/", "/index.html"}:
                self._send_headers(
                    HTTPStatus.OK,
                    "text/html; charset=utf-8",
                    len(INDEX_HTML.encode("utf-8")),
                )
                return
            if path == SPLASH_IMAGE_ROUTE:
                self._send_splash_image(
                    SPLASH_IMAGE_RESOURCE,
                    headers_only=True,
                )
                return
            if path == CREATIVE_SPLASH_IMAGE_ROUTE:
                self._send_splash_image(
                    CREATIVE_SPLASH_IMAGE_RESOURCE,
                    headers_only=True,
                )
                return
            if path == "/api/health":
                data = json.dumps(health_payload(config.root)).encode("utf-8")
                self._send_headers(
                    HTTPStatus.OK,
                    "application/json; charset=utf-8",
                    len(data),
                )
                return
            self._send_headers(
                HTTPStatus.NOT_FOUND,
                "application/json; charset=utf-8",
                len(b'{"error": "not found"}'),
            )

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_splash_image(
            self,
            resource: str = SPLASH_IMAGE_RESOURCE,
            *,
            headers_only: bool = False,
        ) -> None:
            try:
                data = splash_image_bytes(resource)
            except FileNotFoundError:
                self._send_json(
                    {"error": "splash image not found"},
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            self._send_headers(HTTPStatus.OK, "image/png", len(data))
            if not headers_only:
                self.wfile.write(data)

        def _browse_files(self, query: str) -> None:
            params = parse_qs(query)
            path = (params.get("path") or [str(state.root)])[0]
            mode = (params.get("mode") or ["directory"])[0]
            show_hidden = (params.get("hidden") or ["0"])[0] == "1"
            try:
                if mode == "file":
                    payload = browse_files(path, show_hidden=show_hidden)
                elif mode == "markdown":
                    payload = browse_markdown_files(path, show_hidden=show_hidden)
                else:
                    payload = browse_directories(path, show_hidden=show_hidden)
            except StateError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            self._send_json(payload)

        def _open_project(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.open_project(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _create_project(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.create_project(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _open_creative_project(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.open_creative_project(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _create_creative_project(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.create_creative_project(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _create_meta_project(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.create_meta_project(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _add_meta_repository(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.add_meta_repository(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _start_meta_repository(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                repository = payload.get("repository") or payload.get("path") or ""
                self._send_json(
                    state.start_meta_repository(
                        context_id,
                        str(repository),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _remove_meta_repository(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                repository = payload.get("repository") or payload.get("path") or ""
                self._send_json(
                    state.remove_meta_repository(
                        context_id,
                        str(repository),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _create_feature_collection(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.create_feature_collection(
                        context_id,
                        str(payload.get("name") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _switch_feature_collection(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.switch_feature_collection(
                        context_id,
                        str(payload.get("collection_id") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _start_feature_work_item(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.start_feature_work_item(
                        context_id,
                        title=str(payload.get("title") or ""),
                        feature_name=str(payload.get("name") or "") or None,
                        collection_id=str(payload.get("collection_id") or "") or None,
                        parent_slug=str(payload.get("parent_slug") or "") or None,
                        branch=bool(payload.get("branch")),
                        stash_subrepo_changes=bool(
                            payload.get("stash_subrepo_changes")
                        ),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    _work_item_error_payload(error),
                    status=HTTPStatus.CONFLICT,
                )

        def _switch_feature_work_item(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.switch_feature_work_item(
                        context_id,
                        str(payload.get("slug") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _start_bug_work_item(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.start_bug_work_item(
                        context_id,
                        issue_reference=str(payload.get("issue_reference") or ""),
                        branch=bool(payload.get("branch")),
                        stash_subrepo_changes=bool(
                            payload.get("stash_subrepo_changes")
                        ),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    _work_item_error_payload(error),
                    status=HTTPStatus.CONFLICT,
                )

        def _switch_bug_work_item(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.switch_bug_work_item(
                        context_id,
                        str(payload.get("slug") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _deactivate_project(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.deactivate_project(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _select_workflow_stage(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.select_workflow_stage(
                        context_id,
                        str(payload.get("stage") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _select_session(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.select_session(
                        context_id,
                        str(payload.get("session_id") or ""),
                    )
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _send_selected_session_events(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                params = parse_qs(query)
                session_id = str((params.get("session_id") or [""])[0])
                session = (
                    state.session_by_id(context_id, session_id)
                    if session_id
                    else state.selected_session(context_id)
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            if session is None:
                self._send_json(
                    {"error": "no agent session is selected"},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._stream_session_events(session)

        def _send_session_export(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                params = parse_qs(query)
                session_id = str((params.get("session_id") or [""])[0])
                session = (
                    state.session_by_id(context_id, session_id)
                    if session_id
                    else state.selected_session(context_id)
                )
            except (AgentSessionError, StateError) as error:
                self._send_text(
                    str(error),
                    "text/plain; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            if session is None:
                self._send_text(
                    "no agent session is selected",
                    "text/plain; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_download(
                _session_events_markdown(session),
                _session_export_filename(session),
            )

        def _send_selected_session_message(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                message = str(payload.get("message") or "")
                if not message.strip():
                    self._send_json(
                        {"error": "message is empty"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                session_id = str(payload.get("session_id") or "")
                if session_id:
                    state.send_session_message(context_id, session_id, message)
                else:
                    state.send_selected_session_message(context_id, message)
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "sent"})

        def _send_selected_session_key(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                key = str(payload.get("key") or "")
                if not key:
                    self._send_json(
                        {"error": "key is required"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                state.send_selected_session_key(context_id, key)
            except AgentSessionError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except (StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            self._send_json({"status": "sent"})

        def _send_selected_session_raw(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                data = str(payload.get("data") or "")
                if not data:
                    self._send_json(
                        {"error": "data is required"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                state.send_selected_session_raw(context_id, data)
            except AgentSessionError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except (StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            self._send_json({"status": "sent"})

        def _interrupt_selected_session(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                state.interrupt_selected_session(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "interrupted"})

        def _resize_selected_session(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                columns = int(payload.get("columns") or 120)
                rows = int(payload.get("rows") or 32)
                session_id = str(payload.get("session_id") or "").strip()
                if session_id:
                    state.resize_session(context_id, session_id, columns, rows)
                else:
                    state.resize_selected_session(context_id, columns, rows)
            except (AgentSessionError, StateError, TypeError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "resized"})

        def _start_project_shell(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, started = state.start_project_shell(context_id)
                self._send_json(
                    {
                        **state.project_payload(context_id),
                        "status": "started" if started else "already running",
                        "shell_session": session.payload(selected=False),
                    }
                )
            except (AgentSessionError, OSError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _send_project_shell_events(self, query: str) -> None:
            self._send_session_events(
                query,
                state.current_project_shell_session,
                "project shell has not been started",
            )

        def _send_project_shell_input(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                state.send_project_shell_input(
                    context_id,
                    str(payload.get("data") or ""),
                )
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "sent"})

        def _resize_project_shell(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                columns = int(payload.get("columns") or 120)
                rows = int(payload.get("rows") or 32)
                state.resize_project_shell(context_id, columns, rows)
            except (AgentSessionError, StateError, TypeError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "resized"})

        def _stop_project_shell(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.stop_project_shell(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _send_requirements_document(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                project_root = state.requirements_document_root(context_id)
                params = parse_qs(query)
                embedded = str((params.get("embed") or [""])[0]) == "1"
                zoom_percent = _document_zoom_from_params(params)
                page, status = requirements_document_html(
                    project_root,
                    embedded=embedded,
                    zoom_percent=zoom_percent,
                )
            except (AgentSessionError, OSError, StateError) as error:
                self._send_text(
                    f"<p>{html.escape(str(error))}</p>",
                    "text/html; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_text(page, "text/html; charset=utf-8", status=status)

        def _send_pane_window(self, path: str) -> None:
            kind = path.rsplit("/", 1)[-1].strip()
            if kind not in {
                "agent",
                "artifact",
                "progress",
                "scratch",
                "status",
                "input",
                "shell",
            }:
                self._send_json(
                    {"error": "unknown pane"},
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            self._send_text(
                pane_window_html(kind),
                "text/html; charset=utf-8",
            )

        def _send_file_browser_window(self, query: str) -> None:
            params = parse_qs(query)
            initial_path = (params.get("path") or [str(state.root)])[0]
            mode = (params.get("mode") or ["project"])[0]
            self._send_text(
                file_browser_window_html(initial_path, mode),
                "text/html; charset=utf-8",
            )

        def _send_design_document(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                page, status = design_document_html(project_root)
            except (OSError, StateError) as error:
                self._send_text(
                    f"<p>{html.escape(str(error))}</p>",
                    "text/html; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_text(page, "text/html; charset=utf-8", status=status)

        def _send_design_review_document(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                page, status = design_review_document_html(project_root)
            except (OSError, StateError) as error:
                self._send_text(
                    f"<p>{html.escape(str(error))}</p>",
                    "text/html; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_text(page, "text/html; charset=utf-8", status=status)

        def _send_stage_document(self, query: str, stage: str) -> None:
            try:
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                page, status = stage_document_html(project_root, stage)
            except (AgentSessionError, OSError, StateError) as error:
                self._send_text(
                    f"<p>{html.escape(str(error))}</p>",
                    "text/html; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_text(page, "text/html; charset=utf-8", status=status)

        def _send_document_target(self, query: str) -> None:
            try:
                params = parse_qs(query)
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                path = params.get("path", [""])[0]
                title = params.get("title", [""])[0].strip() or None
                embedded = params.get("embed", ["0"])[0] == "1"
                create_missing = params.get("create", ["0"])[0] == "1"
                zoom_percent = _document_zoom_from_params(params)
                page, status = document_target_html(
                    project_root,
                    path,
                    title=title,
                    embedded=embedded,
                    create_missing=create_missing,
                    zoom_percent=zoom_percent,
                )
            except (AgentSessionError, OSError, StateError) as error:
                self._send_text(
                    f"<p>{html.escape(str(error))}</p>",
                    "text/html; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_text(page, "text/html; charset=utf-8", status=status)

        def _send_creative_corkboard(self, query: str) -> None:
            try:
                params = parse_qs(query)
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                folder_path = str((params.get("path") or [""])[0])
                title = str((params.get("title") or [""])[0]).strip() or None
                page, status = creative_corkboard_html(
                    project_root,
                    folder_path,
                    title=title,
                    context_id=context_id,
                )
            except (AgentSessionError, OSError, StateError) as error:
                self._send_text(
                    f"<p>{html.escape(str(error))}</p>",
                    "text/html; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_text(page, "text/html; charset=utf-8", status=status)

        def _send_artifact_editor(self, query: str) -> None:
            try:
                params = parse_qs(query)
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                artifact = str((params.get("artifact") or [""])[0]).strip()
                requested_path = str((params.get("path") or [""])[0])
                title = str((params.get("title") or [""])[0]).strip() or None
                create_missing = str((params.get("create") or [""])[0]) == "1"
                rich_editor = (
                    state.project_mode(context_id) == "creative"
                    and artifact == "document"
                )
                editor_font_size = _artifact_editor_font_size_from_params(params)
                page, status = artifact_editor_html(
                    project_root,
                    artifact,
                    requested_path,
                    title=title,
                    create_missing=create_missing,
                    context_id=context_id,
                    rich_editor=rich_editor,
                    editor_font_size=editor_font_size,
                )
            except (AgentSessionError, OSError, StateError) as error:
                self._send_text(
                    f"<p>{html.escape(str(error))}</p>",
                    "text/html; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_text(page, "text/html; charset=utf-8", status=status)

        def _save_artifact_editor(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                payload = self._read_json_body()
                artifact = str(payload.get("artifact") or "")
                requested_path = str(payload.get("path") or "")
                self._send_json(
                    save_artifact_edit(
                        project_root,
                        artifact,
                        requested_path,
                        payload,
                    )
                )
            except (AgentSessionError, OSError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _save_creative_corkboard(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.save_creative_corkboard(context_id, payload)
                )
            except (AgentSessionError, OSError, StateError, TypeError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _handle_generic_stage_agent(
            self,
            query: str,
            stage: str,
            action: str,
        ) -> None:
            if action == "start":
                self._start_generic_stage_agent(query, stage, interactive=None)
                return
            if action == "start-interactive":
                self._start_generic_stage_agent(query, stage, interactive=True)
                return
            if action == "restart":
                self._restart_generic_stage_agent(query, stage)
                return
            if action == "stop":
                self._stop_generic_stage_agent(query, stage)
                return
            if action == "approve":
                self._approve_generic_stage(query, stage, skip_approval=False)
                return
            if action == "skip-approval":
                self._approve_generic_stage(query, stage, skip_approval=True)
                return
            self._send_json(
                {"error": "not found"},
                status=HTTPStatus.NOT_FOUND,
            )

        def _start_generic_stage_agent(
            self,
            query: str,
            stage: str,
            *,
            interactive: bool | None,
        ) -> None:
            try:
                context_id = self._context_id(query)
                session, started = state.start_workflow_stage_agent(
                    context_id,
                    stage,
                    interactive=interactive,
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start {stage}: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "started" if started else "running",
                    "command": session.command,
                }
            )

        def _restart_generic_stage_agent(self, query: str, stage: str) -> None:
            try:
                context_id = self._context_id(query)
                session, _started = state.restart_workflow_stage_agent(
                    context_id,
                    stage,
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not restart {stage}: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "restarted",
                    "command": session.command,
                }
            )

        def _stop_generic_stage_agent(self, query: str, stage: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.stop_workflow_stage_agent(context_id, stage))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _approve_generic_stage(
            self,
            query: str,
            stage: str,
            *,
            skip_approval: bool,
        ) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(
                    state.approve_workflow_stage(
                        context_id,
                        stage,
                        skip_approval=skip_approval,
                    )
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )

        def _start_requirements_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, started = state.start_requirements_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start requirements agent: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "started" if started else "running",
                    "command": session.command,
                }
            )

        def _restart_requirements_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, _started = state.restart_requirements_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not restart requirements agent: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "restarted",
                    "command": session.command,
                }
            )

        def _complete_requirements_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.complete_requirements_agent(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _approve_requirements(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.approve_requirements(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _skip_requirements_approval(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(
                    state.approve_requirements(context_id, skip_approval=True)
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _send_requirements_message(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session = state.current_requirements_session(context_id)
            except StateError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            if session is None:
                self._send_json(
                    {"error": "requirements agent has not been started"},
                    status=HTTPStatus.CONFLICT,
                )
                return
            try:
                payload = self._read_json_body()
            except ValueError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            message = str(payload.get("message") or "")
            if not message.strip():
                self._send_json(
                    {"error": "message is empty"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                session.send(message)
            except AgentSessionError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "sent"})

        def _interrupt_requirements_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                state.interrupt_requirements_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "interrupted"})

        def _send_agent_events(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session = state.current_requirements_session(context_id)
            except StateError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            if session is None:
                self._send_json(
                    {"error": "requirements agent has not been started"},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last_event_id = self._last_event_id()
            try:
                while True:
                    events = session.wait_for_events_after(last_event_id, timeout=15)
                    if not events and session.is_active():
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        continue
                    for event in events:
                        event_id = int(event["id"])
                        self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
                        self.wfile.write(b"event: agent-event\n")
                        self.wfile.write(
                            f"data: {json.dumps(event, sort_keys=True)}\n\n".encode(
                                "utf-8"
                            )
                        )
                        self.wfile.flush()
                        last_event_id = event_id
                    if not session.is_active():
                        break
            except (BrokenPipeError, ConnectionError, OSError):
                return

        def _resize_requirements_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                columns = int(payload.get("columns") or 120)
                rows = int(payload.get("rows") or 32)
                state.resize_requirements_agent(context_id, columns, rows)
            except (AgentSessionError, StateError, TypeError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "resized"})

        def _start_design_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, started = state.start_design_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start design agent: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "started" if started else "running",
                    "command": session.command,
                }
            )

        def _restart_design_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, _started = state.restart_design_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not restart design agent: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "restarted",
                    "command": session.command,
                }
            )

        def _complete_design_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.complete_design_agent(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _start_design_review_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, started = state.start_design_review_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start design review: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "started" if started else "running",
                    "command": session.command,
                }
            )

        def _start_interactive_design_review_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, started = state.start_design_review_agent(
                    context_id,
                    interactive=True,
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start interactive design review: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "started" if started else "running",
                    "command": session.command,
                }
            )

        def _start_documentation_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                session, started = state.start_documentation_agent(
                    context_id,
                    interactive=True,
                    target=str(payload.get("target") or ""),
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except ValueError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start documentation agent: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "started" if started else "running",
                    "command": session.command,
                    "session_id": session.session_id,
                }
            )

        def _initialize_creative_workspace(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.initialize_creative_workspace(context_id))
            except (AgentSessionError, StateError, OSError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _create_creative_folder(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.create_creative_folder(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, OSError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _create_creative_document(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.create_creative_document(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, OSError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _create_creative_corkboard(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.create_creative_corkboard(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, OSError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _rename_creative_entry(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.rename_creative_entry(
                        context_id,
                        str(payload.get("path") or ""),
                        str(payload.get("new_name") or ""),
                    )
                )
            except (AgentSessionError, StateError, OSError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _delete_creative_entry(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.delete_creative_entry(
                        context_id,
                        str(payload.get("path") or ""),
                    )
                )
            except (AgentSessionError, StateError, OSError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _save_creative_scratchpad(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                self._send_json(
                    state.save_creative_scratchpad(
                        context_id,
                        str(payload.get("markdown") or ""),
                    )
                )
            except (AgentSessionError, StateError, OSError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _start_creative_writing_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                active_target = payload.get("active_target")
                session, started = state.start_creative_writing_agent(
                    context_id,
                    active_document=str(payload.get("active_document") or ""),
                    active_target=(
                        active_target if isinstance(active_target, dict) else None
                    ),
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start creative writing agent: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "started" if started else "running",
                    "command": session.command,
                    "session_id": session.session_id,
                }
            )

        def _start_ad_hoc_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, started = state.start_ad_hoc_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not start ad-hoc agent: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "started" if started else "running",
                    "command": session.command,
                    "session_id": session.session_id,
                }
            )

        def _restart_design_review_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                session, _started = state.restart_design_review_agent(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"could not restart design review: {error}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    **state.project_payload(context_id),
                    "status": "restarted",
                    "command": session.command,
                }
            )

        def _stop_design_review_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.stop_design_review_agent(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _complete_design_review_agent(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.complete_design_review_agent(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _approve_design(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.approve_design(context_id))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _skip_design_approval(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.approve_design(context_id, skip_approval=True))
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return

        def _send_design_message(self, query: str) -> None:
            self._send_agent_message(
                query,
                state.current_design_session,
                "design agent has not been started",
            )

        def _interrupt_design_agent(self, query: str) -> None:
            self._send_interrupt(query, state.interrupt_design_agent)

        def _interrupt_design_review_agent(self, query: str) -> None:
            self._send_interrupt(query, state.interrupt_design_review_agent)

        def _send_design_agent_events(self, query: str) -> None:
            self._send_session_events(
                query,
                state.current_design_session,
                "design agent has not been started",
            )

        def _send_design_review_agent_events(self, query: str) -> None:
            self._send_session_events(
                query,
                state.current_design_review_session,
                "design review has not been started",
            )

        def _send_progress_events(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                command_root = state.command_root(context_id)
            except StateError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._stream_progress_events(context_id, command_root)

        def _send_progress_export(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                command_root = state.command_root(context_id)
                text, ok = _progress_snapshot(command_root)
            except StateError as error:
                self._send_text(
                    str(error),
                    "text/plain; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_download(
                _progress_snapshot_markdown(command_root, text, ok),
                _progress_export_filename(),
            )

        def _send_document_export(self, query: str) -> None:
            params = parse_qs(query)
            artifact = str((params.get("artifact") or [""])[0]).strip()
            requested_path = str((params.get("path") or [""])[0])
            export_format = str((params.get("format") or ["markdown"])[0])
            try:
                context_id = self._context_id(query)
                project_root = Path(state.active_project_root(context_id)).resolve()
                if artifact == "document" and requested_path:
                    _ensure_document_target(project_root, requested_path)
                document_path = _artifact_event_document_path(
                    project_root,
                    artifact,
                    requested_path,
                )
                relative_path = document_path.relative_to(project_root).as_posix()
                exported = export_markdown_document(
                    document_path,
                    relative_path,
                    export_format,
                )
            except (
                AgentSessionError,
                DocumentExportError,
                OSError,
                StateError,
                ValueError,
            ) as error:
                self._send_text(
                    str(error),
                    "text/plain; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_binary_download(
                exported.data,
                exported.filename,
                exported.content_type,
            )

        def _send_artifact_events(self, query: str) -> None:
            params = parse_qs(query)
            artifact = str((params.get("artifact") or [""])[0]).strip()
            try:
                context_id = self._context_id(query)
                project_root = state.active_project_root(context_id)
                document_path = _artifact_event_document_path(
                    project_root,
                    artifact,
                    str((params.get("path") or [""])[0]),
                )
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._stream_artifact_events(artifact, document_path)

        def _resize_design_agent(self, query: str) -> None:
            self._send_resize(query, state.resize_design_agent)

        def _resize_design_review_agent(self, query: str) -> None:
            self._send_resize(query, state.resize_design_review_agent)

        def _send_interrupt(
            self,
            query: str,
            interrupt: Callable[[str], None],
        ) -> None:
            try:
                context_id = self._context_id(query)
                interrupt(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "interrupted"})

        def _send_agent_message(
            self,
            query: str,
            session_for_context: Callable[[str], AgentSession | None],
            missing_message: str,
        ) -> None:
            try:
                context_id = self._context_id(query)
                session = session_for_context(context_id)
            except StateError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            if session is None:
                self._send_json(
                    {"error": missing_message},
                    status=HTTPStatus.CONFLICT,
                )
                return
            try:
                payload = self._read_json_body()
            except ValueError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            message = str(payload.get("message") or "")
            if not message.strip():
                self._send_json(
                    {"error": "message is empty"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                session.send(message)
            except AgentSessionError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "sent"})

        def _send_session_events(
            self,
            query: str,
            session_for_context: Callable[[str], AgentSession | None],
            missing_message: str,
        ) -> None:
            try:
                context_id = self._context_id(query)
                session = session_for_context(context_id)
            except StateError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            if session is None:
                self._send_json(
                    {"error": missing_message},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._stream_session_events(session)

        def _stream_session_events(self, session: AgentSession) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last_event_id = self._last_event_id()
            try:
                while True:
                    events = session.wait_for_events_after(last_event_id, timeout=15)
                    if not events and session.is_active():
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        continue
                    for event in events:
                        event_id = int(event["id"])
                        self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
                        self.wfile.write(b"event: agent-event\n")
                        self.wfile.write(
                            f"data: {json.dumps(event, sort_keys=True)}\n\n".encode(
                                "utf-8"
                            )
                        )
                        self.wfile.flush()
                        last_event_id = event_id
                    if not session.is_active():
                        break
            except (BrokenPipeError, ConnectionError, OSError):
                return

        def _stream_artifact_events(self, artifact: str, document_path: Path) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last_signature: dict[str, object] | None = None
            event_id = 1
            try:
                while True:
                    signature = _file_signature(document_path)
                    if signature != last_signature:
                        payload = {
                            "artifact": artifact,
                            "path": str(document_path),
                            "signature": signature,
                        }
                        self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
                        self.wfile.write(b"event: artifact-event\n")
                        self.wfile.write(
                            f"data: {json.dumps(payload, sort_keys=True)}\n\n".encode(
                                "utf-8"
                            )
                        )
                        self.wfile.flush()
                        event_id += 1
                        last_signature = signature
                    else:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                    time.sleep(0.75)
            except (BrokenPipeError, ConnectionError, OSError):
                return

        def _stream_progress_events(self, context_id: str, project_root: Path) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last_snapshot = ""
            event_id = 1
            try:
                while True:
                    text, ok = _progress_snapshot(project_root)
                    running = state.has_running_progress_agent(context_id)
                    payload = {
                        "type": "snapshot" if ok else "error",
                        "text": text,
                        "running": running,
                    }
                    snapshot = json.dumps(payload, sort_keys=True)
                    if snapshot != last_snapshot:
                        self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
                        self.wfile.write(b"event: progress-event\n")
                        self.wfile.write(f"data: {snapshot}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        event_id += 1
                        last_snapshot = snapshot
                    else:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                    if not running:
                        break
                    time.sleep(1)
            except (BrokenPipeError, ConnectionError, OSError, StateError):
                return

        def _send_resize(
            self,
            query: str,
            resize: Callable[[str, int, int], None],
        ) -> None:
            try:
                context_id = self._context_id(query)
                payload = self._read_json_body()
                columns = int(payload.get("columns") or 120)
                rows = int(payload.get("rows") or 32)
                resize(context_id, columns, rows)
            except (AgentSessionError, StateError, TypeError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "resized"})

        def _send_context_json(
            self,
            query: str,
            build_payload: Callable[[str], dict[str, object]],
        ) -> None:
            try:
                payload = build_payload(self._context_id(query))
            except StateError as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json(payload)

        def _context_id(self, query: str) -> str:
            params = parse_qs(query)
            return str((params.get("context_id") or [""])[0])

        def _read_json_body(self) -> dict[str, object]:
            try:
                content_length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError as error:
                raise ValueError("invalid Content-Length") from error
            if content_length <= 0:
                return {}
            body = self.rfile.read(content_length).decode("utf-8")
            if not body.strip():
                return {}
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as error:
                raise ValueError("request body is not valid JSON") from error
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            return payload

        def _last_event_id(self) -> int:
            header = self.headers.get("Last-Event-ID", "")
            try:
                return int(header)
            except ValueError:
                return 0

        def _send_download(
            self,
            text: str,
            filename: str,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            data = text.encode("utf-8")
            safe_name = _download_name_part(filename)
            if not safe_name.endswith(".md"):
                safe_name = f"{safe_name}.md"
            self._send_binary_download(
                data,
                safe_name,
                "text/markdown; charset=utf-8",
                status=status,
            )

        def _send_binary_download(
            self,
            data: bytes,
            filename: str,
            content_type: str,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            safe_name = _download_name_part(filename)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{safe_name}"',
            )
            self.end_headers()
            self.wfile.write(data)

        def _send_text(
            self,
            text: str,
            content_type: str,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            data = text.encode("utf-8")
            self._send_headers(status, content_type, len(data))
            self.wfile.write(data)

        def _send_json(
            self,
            payload: dict[str, object],
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            data = json.dumps(payload, sort_keys=True).encode("utf-8")
            self._send_headers(
                status,
                "application/json; charset=utf-8",
                len(data),
            )
            self.wfile.write(data)

        def _send_headers(
            self,
            status: HTTPStatus,
            content_type: str,
            content_length: int,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(content_length))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

    return ElectroBoyRequestHandler
