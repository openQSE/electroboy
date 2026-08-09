"""Local browser service for ElectroBoy."""

from __future__ import annotations

import errno
import fcntl
import html
import io
import json
import os
import pty
import re
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
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from .artifacts import ArtifactManager
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


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
TERMINAL_SUBMIT_DELAY_SECONDS = 0.08
META_REGISTRY_RELATIVE_PATH = Path(".electroboy") / "shared" / "repositories.json"

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
    "documentation": frozenset(
        {
            "documentation.jsonl",
            "README.md",
            "docs/api.md",
        }
    ),
}

INDEX_HTML = """<!doctype html>
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
      --ink: #1b1f2a;
      --muted: #697386;
      --border: #d8dde8;
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

    .shell {
      position: relative;
      display: grid;
      grid-template-rows:
        var(--workflow-pane-height, 230px) 7px
        minmax(0, 1fr);
      height: 100vh;
      min-height: 560px;
    }

    .workflow-pane {
      position: relative;
      z-index: 10;
      padding: 20px 24px 16px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
      overflow: visible;
    }

    .shell-resize-handle,
    .input-resize-handle,
    .output-resize-handle,
    .workbench-resize-handle,
    .side-pane-resize-handle,
    .artifact-pane-resize-handle {
      touch-action: none;
      user-select: none;
    }

    .shell-resize-handle {
      position: relative;
      z-index: 8;
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
      overflow-x: auto;
      overflow-y: hidden;
      margin: 0 -24px;
      padding: 0 24px 12px;
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

    .connection {
      position: absolute;
      right: 24px;
      top: 16px;
      color: var(--active);
      font-size: var(--ui-font-size);
      font-weight: 650;
    }

    .stage-graph {
      position: relative;
      display: grid;
      grid-template-columns: repeat(9, minmax(136px, 1fr));
      gap: 12px;
      min-width: 1240px;
      padding-top: 54px;
    }

    .stage-graph::before {
      position: absolute;
      top: 77px;
      left: 56px;
      right: calc(16.6667% - 4px);
      height: 2px;
      background: var(--border);
      content: "";
    }

    .stage-node {
      position: relative;
      z-index: 1;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 0;
      min-height: 48px;
      padding: 0 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--disabled);
      color: var(--muted);
      font-size: var(--ui-font-size);
      font-weight: 650;
      letter-spacing: 0;
      white-space: normal;
      text-align: center;
      line-height: 1.15;
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
      background: #007f8a;
      color: #ffffff;
    }

    .stage-node.available {
      border-color: #6f91a8;
      background: #ffffff;
      color: #243f53;
    }

    .stage-node.complete {
      border-color: #9fb4c9;
      background: #edf7ff;
      color: #27445e;
    }

    .stage-node.disabled {
      border-color: var(--border);
      background: var(--disabled);
      color: var(--muted);
      cursor: default;
    }

    .stage-node.sidecar {
      border-style: dashed;
    }

    .stage-node.sidecar::before {
      position: absolute;
      top: 50%;
      left: -28px;
      width: 28px;
      height: 4px;
      transform: translateY(-50%);
      background: var(--paper);
      content: "";
      pointer-events: none;
    }

    .stage-node.sidecar.available {
      border-color: #7b8fb1;
      background: #f8fbff;
      color: #314763;
    }

    button.stage-node.available:hover {
      border-color: #1d7180;
      background: #effbfc;
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

    .project-panel {
      position: absolute;
      z-index: 25;
      top: 176px;
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

    .project-panel[hidden] {
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

    .left-output-pane {
      display: grid;
      min-height: 0;
      min-width: 0;
      background: var(--terminal);
    }

    .output-split {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      min-height: 0;
      background: var(--terminal);
    }

    .output-split.split {
      grid-template-columns:
        minmax(0, 1fr) 7px
        minmax(280px, var(--progress-pane-width, 42%));
    }

    .output-resize-handle {
      min-height: 0;
      background: #202838;
      cursor: col-resize;
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
    .side-pane.resizing-artifact .artifact-pane-resize-handle {
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
    .output-resize-handle[hidden] {
      display: none;
    }

    .agent-output,
    .progress-output {
      min-height: 0;
      overflow: hidden;
      padding: 0;
      color: var(--terminal-text);
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: var(--terminal-font-size);
      line-height: 1.45;
      white-space: pre-wrap;
    }

    .progress-output {
      border-left: 0;
    }

    .progress-output[hidden] {
      display: none;
    }

    .agent-output .xterm,
    .progress-output .xterm {
      height: 100%;
      padding: 10px 12px;
    }

    .agent-output .xterm-viewport,
    .progress-output .xterm-viewport {
      background: var(--terminal);
    }

    .agent-output .system,
    .progress-output .system {
      color: #8bd8ca;
    }

    .agent-output .error,
    .progress-output .error {
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

    .side-pane.preview-visible {
      grid-template-rows:
        minmax(100px, var(--scratch-pane-height, 30%)) 7px
        minmax(140px, var(--artifact-pane-height, 36%)) 7px
        minmax(100px, 1fr);
    }

    .side-pane-resize-handle {
      min-height: 0;
      background: #253044;
      cursor: row-resize;
    }

    .artifact-pane-resize-handle {
      min-height: 0;
      background: #253044;
      cursor: row-resize;
    }

    .scratch-pane,
    .artifact-preview-pane,
    .project-status-pane {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      min-height: 0;
      min-width: 0;
    }

    .artifact-preview-pane[hidden],
    .artifact-pane-resize-handle[hidden] {
      display: none;
    }

    .side-pane-header {
      display: flex;
      align-items: center;
      min-height: 34px;
      border-bottom: 1px solid #2a3142;
      padding: 0 12px;
      color: #aab8cf;
      font-size: var(--ui-small-font-size);
      font-weight: 750;
      text-transform: uppercase;
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
      font-size: var(--terminal-font-size);
      line-height: 1.45;
      outline: none;
      white-space: pre-wrap;
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
      background: #f7f8fb;
    }

    .input-pane {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      min-height: 0;
      gap: 8px;
      border-top: 1px solid #2a3142;
      background: #151b29;
      padding: 12px;
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
      font-size: var(--terminal-font-size);
      line-height: 1.45;
    }

    .agent-input:disabled {
      color: #7c879a;
      background: #121827;
      cursor: default;
    }

    .agent-actions {
      display: grid;
      grid-template-rows: auto auto auto auto;
      min-height: 0;
      gap: 8px;
      align-self: stretch;
      overflow: auto;
      scrollbar-width: thin;
      width: 196px;
    }

    .session-control {
      display: grid;
      gap: 4px;
    }

    .session-label {
      color: #aab8cf;
      font-size: var(--ui-small-font-size);
      font-weight: 750;
    }

    .session-switcher {
      width: 100%;
      min-height: 38px;
      height: calc(var(--ui-font-size) + 25px);
      min-width: 0;
      border: 1px solid #303746;
      border-radius: 6px;
      background: #171d2b;
      color: #e7edf7;
      font: inherit;
      font-size: var(--ui-font-size);
      font-weight: 650;
      padding: 0 8px;
    }

    .session-switcher:disabled {
      color: #667085;
      cursor: default;
    }

    .terminal-font-controls {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
    }

    .terminal-font-button,
    .agent-action-button {
      border-radius: 8px;
      cursor: pointer;
      font-family: inherit;
      font-size: var(--ui-font-size);
      font-weight: 750;
    }

    .terminal-font-button {
      min-height: 32px;
      height: calc(var(--ui-font-size) + 19px);
      border: 1px solid #364156;
      background: #1d2638;
      color: var(--terminal-text);
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

      .stage-graph {
        grid-template-columns: repeat(15, minmax(112px, 1fr));
        min-width: 1840px;
      }

      .stage-graph::before {
        right: 50%;
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

      .project-panel {
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

      .output-split.split {
        grid-template-columns: minmax(0, 1fr);
        grid-template-rows:
          minmax(0, 1fr) 7px
          minmax(180px, var(--progress-pane-height, 45%));
      }

      .output-resize-handle {
        cursor: row-resize;
      }

      .progress-output {
        border-top: 0;
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <section class="workflow-pane" aria-label="Project workflow">
      <div id="connection" class="connection"></div>
      <div class="stage-scroll">
        <div class="stage-graph" aria-label="Project stages">
          <button class="stage-node active" type="button" data-stage="project">
            project
          </button>
          <button
            class="stage-node disabled"
            type="button"
            data-stage="requirements"
            disabled
          >
            requirements
          </button>
          <button class="stage-node disabled" type="button" data-stage="design" disabled>
            design
          </button>
          <button class="stage-node disabled" type="button" data-stage="design-review" disabled>
            design-review
          </button>
          <button
            class="stage-node disabled"
            type="button"
            data-stage="implementation-plan"
            disabled
          >
            implementation-plan
          </button>
          <button class="stage-node disabled" type="button" data-stage="code" disabled>
            code
          </button>
          <button class="stage-node disabled" type="button" data-stage="test-plan" disabled>
            test-plan
          </button>
          <button class="stage-node disabled" type="button" data-stage="validate" disabled>
            validate
          </button>
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
        <button id="deactivateProject" type="button" disabled>Deactivate</button>
      </div>
      <div id="requirementsMenu" class="stage-menu" hidden>
        <button id="startRequirements" type="button">Start</button>
        <button id="restartRequirements" type="button">Restart</button>
        <button id="approveRequirements" type="button">Approve</button>
        <button id="skipRequirementsApproval" type="button">Skip approval</button>
        <button id="openRequirements" type="button">Open requirements</button>
      </div>
      <div id="designMenu" class="stage-menu" hidden>
        <button id="startDesign" type="button">Start</button>
        <button id="restartDesign" type="button">Restart</button>
        <button id="completeDesign" type="button">Complete</button>
        <button id="openDesign" type="button">Open design</button>
      </div>
      <div id="designReviewMenu" class="stage-menu" hidden>
        <button id="startAutomaticDesignReview" type="button">Start automatic</button>
        <button id="startInteractiveDesignReview" type="button">Start interactive</button>
        <button id="stopDesignReview" type="button">Stop</button>
        <button id="approveDesignReview" type="button">Approve</button>
        <button id="skipDesignReviewApproval" type="button">Skip approval</button>
        <button id="restartDesignReview" type="button">Restart review</button>
        <button id="openDesignReview" type="button">Open review</button>
        <button id="openDesignFromReview" type="button">Open design</button>
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
            <div id="agentOutput" class="agent-output" aria-live="polite"></div>
            <div
              id="outputResizeHandle"
              class="output-resize-handle"
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize agent and progress panes"
              hidden
            ></div>
            <div
              id="progressOutput"
              class="progress-output"
              aria-live="polite"
              hidden
            ></div>
          </div>
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
          aria-label="Scratch pad, artifact preview, and status"
        >
          <section class="scratch-pane" aria-label="Scratch pad">
            <div class="side-pane-header">Scratch pad</div>
            <textarea
              id="scratchPad"
              class="scratch-pad"
              spellcheck="false"
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
          <section
            id="artifactPreviewPane"
            class="artifact-preview-pane"
            aria-label="Artifact preview"
            hidden
          >
            <div id="artifactPreviewHeader" class="side-pane-header">Requirements</div>
            <iframe
              id="artifactPreviewFrame"
              class="artifact-preview-frame"
              title="Rendered artifact preview"
              sandbox=""
            ></iframe>
          </section>
          <div
            id="artifactPaneResizeHandle"
            class="artifact-pane-resize-handle"
            role="separator"
            aria-orientation="horizontal"
            aria-label="Resize artifact preview and status panes"
            hidden
          ></div>
          <section class="project-status-pane" aria-label="Project status">
            <div class="side-pane-header">Project status</div>
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
        <textarea
          id="agentInput"
          class="agent-input"
          spellcheck="false"
          disabled
          aria-label="Requirements agent input"
        ></textarea>
        <div class="agent-actions">
          <div class="terminal-font-controls" aria-label="UI font size">
            <button
              id="decreaseTerminalFont"
              class="terminal-font-button"
              type="button"
              title="Decrease font size"
              aria-label="Decrease font size"
            >
              A-
            </button>
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
          <div class="session-control">
            <label class="session-label" for="sessionSwitcher">Select Agent</label>
            <select
              id="sessionSwitcher"
              class="session-switcher"
              disabled
              aria-label="Select Agent"
            ></select>
          </div>
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
    const documentStage = document.querySelector("[data-stage='document']");
    const projectMenu = document.getElementById("projectMenu");
    const requirementsMenu = document.getElementById("requirementsMenu");
    const designMenu = document.getElementById("designMenu");
    const designReviewMenu = document.getElementById("designReviewMenu");
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
    const deactivateProject = document.getElementById("deactivateProject");
    const startRequirements = document.getElementById("startRequirements");
    const restartRequirements = document.getElementById("restartRequirements");
    const approveRequirements = document.getElementById("approveRequirements");
    const skipRequirementsApproval = document.getElementById("skipRequirementsApproval");
    const openRequirements = document.getElementById("openRequirements");
    const startDesign = document.getElementById("startDesign");
    const restartDesign = document.getElementById("restartDesign");
    const completeDesign = document.getElementById("completeDesign");
    const openDesign = document.getElementById("openDesign");
    const startAutomaticDesignReview = document.getElementById("startAutomaticDesignReview");
    const startInteractiveDesignReview = document.getElementById("startInteractiveDesignReview");
    const stopDesignReview = document.getElementById("stopDesignReview");
    const approveDesignReview = document.getElementById("approveDesignReview");
    const skipDesignReviewApproval = document.getElementById("skipDesignReviewApproval");
    const restartDesignReview = document.getElementById("restartDesignReview");
    const openDesignReview = document.getElementById("openDesignReview");
    const openDesignFromReview = document.getElementById("openDesignFromReview");
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
    const fileBrowser = document.getElementById("fileBrowser");
    const browserPath = document.getElementById("browserPath");
    const upDirectory = document.getElementById("upDirectory");
    const selectDirectory = document.getElementById("selectDirectory");
    const closeBrowser = document.getElementById("closeBrowser");
    const directoryList = document.getElementById("directoryList");
    const agentPane = document.getElementById("agentPane");
    const outputWorkbench = document.getElementById("outputWorkbench");
    const workbenchResizeHandle = document.getElementById("workbenchResizeHandle");
    const outputSplit = document.getElementById("outputSplit");
    const agentOutput = document.getElementById("agentOutput");
    const outputResizeHandle = document.getElementById("outputResizeHandle");
    const progressOutput = document.getElementById("progressOutput");
    const sidePane = document.getElementById("sidePane");
    const sidePaneResizeHandle = document.getElementById("sidePaneResizeHandle");
    const scratchPad = document.getElementById("scratchPad");
    const artifactPreviewPane = document.getElementById("artifactPreviewPane");
    const artifactPaneResizeHandle = document.getElementById("artifactPaneResizeHandle");
    const artifactPreviewHeader = document.getElementById("artifactPreviewHeader");
    const artifactPreviewFrame = document.getElementById("artifactPreviewFrame");
    const projectStatusOutput = document.getElementById("projectStatusOutput");
    const inputResizeHandle = document.getElementById("inputResizeHandle");
    const inputPane = document.getElementById("inputPane");
    const agentInput = document.getElementById("agentInput");
    const sessionSwitcher = document.getElementById("sessionSwitcher");
    const decreaseTerminalFont = document.getElementById("decreaseTerminalFont");
    const increaseTerminalFont = document.getElementById("increaseTerminalFont");
    const interruptAgent = document.getElementById("interruptAgent");
    const insertFileLink = document.getElementById("insertFileLink");
    const CONTEXT_STORAGE_KEY = "electroboy.contextId";
    const TERMINAL_FONT_STORAGE_KEY = "electroboy.terminalFontSize";
    const WORKFLOW_PANE_HEIGHT_STORAGE_KEY = "electroboy.workflowPaneHeight";
    const INPUT_PANE_HEIGHT_STORAGE_KEY = "electroboy.inputPaneHeight";
    const PROGRESS_PANE_WIDTH_STORAGE_KEY = "electroboy.progressPaneWidth";
    const PROGRESS_PANE_HEIGHT_STORAGE_KEY = "electroboy.progressPaneHeight";
    const RIGHT_PANE_WIDTH_STORAGE_KEY = "electroboy.rightPaneWidth";
    const RIGHT_PANE_HEIGHT_STORAGE_KEY = "electroboy.rightPaneHeight";
    const SCRATCH_PANE_HEIGHT_STORAGE_KEY = "electroboy.scratchPaneHeight";
    const ARTIFACT_PANE_HEIGHT_STORAGE_KEY = "electroboy.artifactPaneHeight";
    const SCRATCH_PAD_STORAGE_KEY = "electroboy.scratchPad";
    const DOCUMENT_TARGETS_STORAGE_KEY = "electroboy.documentTargets";
    const DEFAULT_DOCUMENT_TARGETS = [
      { label: "README", path: "README.md" },
      { label: "API", path: "docs/api.md" },
    ];
    const DEFAULT_TERMINAL_FONT_SIZE = 15;
    const MIN_TERMINAL_FONT_SIZE = 11;
    const MAX_TERMINAL_FONT_SIZE = 24;
    const MIN_INPUT_PANE_HEIGHT = 56;
    const ARTIFACT_PREVIEW_REFRESH_MS = 1500;
    let eventSource = null;
    let progressEventSource = null;
    let terminal = null;
    let terminalFit = null;
    let progressTerminal = null;
    let progressTerminalFit = null;
    let terminalFontSize = storedTerminalFontSize();
    let resizeShellState = null;
    let resizeInputState = null;
    let resizeOutputState = null;
    let resizeWorkbenchState = null;
    let resizeSidePaneState = null;
    let resizeArtifactPaneState = null;
    let resizeTimer = null;
    let statusRefreshTimer = null;
    let statusRefreshSequence = 0;
    let artifactRefreshTimer = null;
    let artifactPreviewKind = "";
    let activeAgentKind = "";
    let requirementsRunning = false;
    let requirementsStarted = false;
    let requirementsApproved = false;
    let designRunning = false;
    let designStarted = false;
    let designReviewRunning = false;
    let designReviewStarted = false;
    let designReviewInteractive = false;
    let designApproved = false;
    let documentationRunning = false;
    let currentWorkflowStage = "project";
    let agentSessions = [];
    let selectedSessionId = "";
    let contextId = "";
    let projectMode = "open";
    let serviceRoot = "";
    let activationRoot = "";
    let activeProjectMode = "none";
    let activeProjectRoot = "";
    let activeRepositoryName = "";
    let registeredRepositories = [];
    let customDocumentTargets = storedDocumentTargets();
    let currentBrowsePath = "";
    let currentBrowseParent = "";
    let currentBrowserMode = "project";
    let currentSelectedFile = "";

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

    function clampTerminalFontSize(value) {
      return Math.max(
        MIN_TERMINAL_FONT_SIZE,
        Math.min(MAX_TERMINAL_FONT_SIZE, value),
      );
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

    function applyStoredPaneSizes() {
      const workflowHeight = storedNumber(WORKFLOW_PANE_HEIGHT_STORAGE_KEY);
      if (workflowHeight) {
        shell.style.setProperty("--workflow-pane-height", `${workflowHeight}px`);
      }
      const inputHeight = storedNumber(INPUT_PANE_HEIGHT_STORAGE_KEY);
      if (inputHeight) {
        agentPane.style.setProperty("--input-pane-height", `${inputHeight}px`);
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

    function applyStoredWorkbenchPaneSize() {
      const rightWidth = storedNumber(RIGHT_PANE_WIDTH_STORAGE_KEY);
      if (rightWidth) {
        outputWorkbench.style.setProperty("--right-pane-width", `${rightWidth}px`);
      }
      const rightHeight = storedNumber(RIGHT_PANE_HEIGHT_STORAGE_KEY);
      if (rightHeight) {
        outputWorkbench.style.setProperty("--right-pane-height", `${rightHeight}px`);
      }
      const scratchHeight = storedNumber(SCRATCH_PANE_HEIGHT_STORAGE_KEY);
      if (scratchHeight) {
        sidePane.style.setProperty("--scratch-pane-height", `${scratchHeight}px`);
      }
      const artifactHeight = storedNumber(ARTIFACT_PANE_HEIGHT_STORAGE_KEY);
      if (artifactHeight) {
        sidePane.style.setProperty("--artifact-pane-height", `${artifactHeight}px`);
      }
    }

    function saveProgressPaneWidth(width) {
      saveNumber(PROGRESS_PANE_WIDTH_STORAGE_KEY, width);
    }

    function saveProgressPaneHeight(height) {
      saveNumber(PROGRESS_PANE_HEIGHT_STORAGE_KEY, height);
    }

    function saveRightPaneWidth(width) {
      saveNumber(RIGHT_PANE_WIDTH_STORAGE_KEY, width);
    }

    function saveRightPaneHeight(height) {
      saveNumber(RIGHT_PANE_HEIGHT_STORAGE_KEY, height);
    }

    function saveScratchPaneHeight(height) {
      saveNumber(SCRATCH_PANE_HEIGHT_STORAGE_KEY, height);
    }

    function saveArtifactPaneHeight(height) {
      saveNumber(ARTIFACT_PANE_HEIGHT_STORAGE_KEY, height);
    }

    function restoreScratchPad() {
      try {
        scratchPad.value = window.localStorage.getItem(SCRATCH_PAD_STORAGE_KEY) || "";
      } catch (error) {
        scratchPad.value = "";
      }
    }

    function saveScratchPad() {
      try {
        window.localStorage.setItem(SCRATCH_PAD_STORAGE_KEY, scratchPad.value);
      } catch (error) {
        return;
      }
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

    function initializeTerminal() {
      if (!window.Terminal) {
        appendPlainOutput("terminal renderer unavailable; using plain text\\n", "error");
        return;
      }
      terminal = new window.Terminal(terminalOptions());
      if (window.FitAddon && window.FitAddon.FitAddon) {
        terminalFit = new window.FitAddon.FitAddon();
        terminal.loadAddon(terminalFit);
      }
      terminal.open(agentOutput);
      applyTerminalFontSize();
      fitTerminal();
      window.addEventListener("resize", fitTerminal);
    }

    function initializeProgressTerminal() {
      if (progressTerminal || !window.Terminal) {
        return;
      }
      progressTerminal = new window.Terminal(terminalOptions());
      if (window.FitAddon && window.FitAddon.FitAddon) {
        progressTerminalFit = new window.FitAddon.FitAddon();
        progressTerminal.loadAddon(progressTerminalFit);
      }
      progressTerminal.open(progressOutput);
      applyTerminalFontSize();
    }

    function terminalOptions() {
      return {
        allowProposedApi: false,
        convertEol: true,
        cursorBlink: false,
        disableStdin: true,
        fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace',
        fontSize: terminalFontSize,
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

    function changeTerminalFontSize(delta) {
      terminalFontSize = clampTerminalFontSize(terminalFontSize + delta);
      saveTerminalFontSize();
      applyTerminalFontSize();
    }

    function applyTerminalFontSize() {
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
      if (terminal) {
        terminal.options.fontSize = terminalFontSize;
      }
      if (progressTerminal) {
        progressTerminal.options.fontSize = terminalFontSize;
      }
      decreaseTerminalFont.disabled = terminalFontSize <= MIN_TERMINAL_FONT_SIZE;
      increaseTerminalFont.disabled = terminalFontSize >= MAX_TERMINAL_FONT_SIZE;
      window.requestAnimationFrame(fitTerminal);
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
      if (progressTerminalFit && !progressOutput.hidden) {
        try {
          progressTerminalFit.fit();
        } catch (error) {
          return;
        }
      }
      queueTerminalResize();
    }

    function queueTerminalResize() {
      if (!agentProcessRunning() || !contextId || !terminal || !selectedSessionId) {
        return;
      }
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(sendTerminalResize, 120);
    }

    async function sendTerminalResize() {
      if (!agentProcessRunning() || !contextId || !terminal || !selectedSessionId) {
        return;
      }
      await fetch(contextUrl("/api/sessions/resize"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          columns: terminal.cols,
          rows: terminal.rows,
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

    function setAgentInputVisible(isVisible) {
      inputPane.hidden = !isVisible;
      inputResizeHandle.hidden = !isVisible;
      agentPane.classList.toggle("noninteractive", !isVisible);
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
        maxHeight: Math.max(140, shellRect.height - 240),
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
        140,
        resizeShellState.maxHeight,
      );
      shell.style.setProperty("--workflow-pane-height", `${nextHeight}px`);
      saveNumber(WORKFLOW_PANE_HEIGHT_STORAGE_KEY, nextHeight);
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
      if (artifactPreviewPane.hidden) {
        return;
      }
      event.preventDefault();
      const sideRect = sidePane.getBoundingClientRect();
      const artifactRect = artifactPreviewPane.getBoundingClientRect();
      resizeArtifactPaneState = {
        startY: event.clientY,
        startHeight: artifactRect.height,
        maxHeight: Math.max(140, sideRect.height - 180),
      };
      artifactPaneResizeHandle.setPointerCapture(event.pointerId);
      sidePane.classList.add("resizing-artifact");
    }

    function updateArtifactPaneResize(event) {
      if (!resizeArtifactPaneState) {
        return;
      }
      const deltaY = event.clientY - resizeArtifactPaneState.startY;
      const nextHeight = clampValue(
        resizeArtifactPaneState.startHeight + deltaY,
        140,
        resizeArtifactPaneState.maxHeight,
      );
      sidePane.style.setProperty("--artifact-pane-height", `${nextHeight}px`);
      saveArtifactPaneHeight(nextHeight);
    }

    function finishArtifactPaneResize(event) {
      if (!resizeArtifactPaneState) {
        return;
      }
      resizeArtifactPaneState = null;
      sidePane.classList.remove("resizing-artifact");
      try {
        artifactPaneResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
    }

    function showProgressPane(show) {
      if (show) {
        progressOutput.hidden = false;
        outputResizeHandle.hidden = false;
        outputSplit.style.gridTemplateRows = "";
        applyStoredProgressPaneSize();
        initializeProgressTerminal();
        prepareTerminalStream();
      } else {
        progressOutput.hidden = true;
        outputResizeHandle.hidden = true;
        outputSplit.style.gridTemplateRows = "";
        closeProgressEventStream();
      }
      outputSplit.classList.toggle("split", show);
      window.requestAnimationFrame(fitTerminal);
    }

    function startOutputResize(event) {
      if (progressOutput.hidden) {
        return;
      }
      event.preventDefault();
      const splitRect = outputSplit.getBoundingClientRect();
      const progressRect = progressOutput.getBoundingClientRect();
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
      connection.textContent = activationRoot
        ? `connected · ${activationRoot}`
        : "connected";
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

    function storedContextId() {
      try {
        return window.sessionStorage.getItem(CONTEXT_STORAGE_KEY) || "";
      } catch (error) {
        return "";
      }
    }

    function saveContextId(value) {
      try {
        if (value) {
          window.sessionStorage.setItem(CONTEXT_STORAGE_KEY, value);
        } else {
          window.sessionStorage.removeItem(CONTEXT_STORAGE_KEY);
        }
      } catch (error) {
        return;
      }
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
      if (!existingContextId) {
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
        if (session.kind === "design-review" && !isInteractive && session.status === "running") {
          connectProgressEvents();
        }
        sendTerminalResize();
      }
    }

    function updateProjectState(payload) {
      serviceRoot = payload.service_root || "";
      activationRoot = payload.activation_root || payload.active_project_root || "";
      activeProjectMode = payload.project_mode || (activationRoot ? "project" : "none");
      activeProjectRoot = payload.active_project_root || "";
      activeRepositoryName = payload.active_repository_name || "";
      registeredRepositories = Array.isArray(payload.registered_repositories)
        ? payload.registered_repositories
        : [];
      requirementsStarted = Boolean(payload.requirements_started);
      requirementsRunning = Boolean(payload.requirements_running);
      requirementsApproved = Boolean(payload.requirements_approved);
      designStarted = Boolean(payload.design_started);
      designRunning = Boolean(payload.design_running);
      designReviewStarted = Boolean(payload.design_review_started);
      designReviewRunning = Boolean(payload.design_review_running);
      designReviewInteractive = Boolean(payload.design_review_interactive);
      designApproved = Boolean(payload.design_approved);
      documentationRunning = Boolean(payload.documentation_running);
      agentSessions = Array.isArray(payload.sessions) ? payload.sessions : [];
      selectedSessionId = payload.selected_session_id || selectedSessionId || "";
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
      deactivateProject.disabled = !hasProjectContext;
      renderMetaRepositoryMenus();
      updateRequirementsMenuState();
      updateDesignMenuState();
      updateDesignReviewMenuState();
      updateDocumentMenuState();
      syncArtifactPreviewWithProject();
      projectStatus.textContent = projectStatusLine();
      queueProjectStatusRefresh();
    }

    function projectStatusLine() {
      if (!activationRoot) {
        return "";
      }
      if (activeProjectMode === "meta") {
        if (activeProjectRoot) {
          return `meta: ${activationRoot} · active repo: ${activeRepositoryName || activeProjectRoot}`;
        }
        return activeRepositoryName
          ? `meta: ${activationRoot} · active repo: ${activeRepositoryName} (not initialized)`
          : `meta: ${activationRoot} · active repo: none`;
      }
      return `active: ${activeProjectRoot || activationRoot}`;
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
      sessionSwitcher.disabled = false;
      sessionSwitcher.value = selectedSessionId || agentSessions[0].session_id;
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
      renderSessionSwitcher();
      const session = selectedSession();
      activeAgentKind = session ? session.kind || "" : "";
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
      startRequirements.disabled =
        !hasActiveProject || !inRequirementsStage || requirementsRunning;
      restartRequirements.disabled =
        !hasActiveProject || (inRequirementsStage && !requirementsStarted);
      approveRequirements.disabled = !hasActiveProject || !inRequirementsStage;
      skipRequirementsApproval.disabled = !hasActiveProject || !inRequirementsStage;
      openRequirements.disabled =
        !hasActiveProject ||
        (inRequirementsStage && !requirementsStarted && !requirementsApproved);
    }

    function updateDesignMenuState() {
      const hasActiveProject = Boolean(activeProjectRoot);
      const inDesignStage = currentWorkflowStage === "design";
      startDesign.disabled = !hasActiveProject || !inDesignStage || designRunning;
      restartDesign.disabled = !hasActiveProject || inDesignStage;
      completeDesign.disabled = !hasActiveProject || !inDesignStage;
      openDesign.disabled = !hasActiveProject || !inDesignStage || !designStarted;
    }

    function updateDesignReviewMenuState() {
      const hasActiveProject = Boolean(activeProjectRoot);
      const inDesignReviewStage = currentWorkflowStage === "design-review";
      startAutomaticDesignReview.disabled =
        !hasActiveProject || !inDesignReviewStage || designReviewRunning || designReviewStarted;
      startInteractiveDesignReview.disabled =
        !hasActiveProject || !inDesignReviewStage || designReviewRunning || designReviewStarted;
      stopDesignReview.disabled =
        !hasActiveProject || !inDesignReviewStage || !designReviewRunning;
      approveDesignReview.disabled = !hasActiveProject || !inDesignReviewStage;
      skipDesignReviewApproval.disabled = !hasActiveProject || !inDesignReviewStage;
      restartDesignReview.disabled =
        !hasActiveProject || (inDesignReviewStage && !designReviewStarted);
      openDesignReview.disabled =
        !hasActiveProject || !inDesignReviewStage || !designReviewStarted;
      openDesignFromReview.disabled = !hasActiveProject || !inDesignReviewStage;
    }

    function updateDocumentMenuState() {
      const hasActiveProject = Boolean(activeProjectRoot);
      createDocumentTarget.disabled = !hasActiveProject;
      addDocumentTarget.disabled = !hasActiveProject;
      customDocumentName.disabled = !hasActiveProject;
      renderDocumentTargets();
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
      const disabled = !activeProjectRoot || documentationRunning;
      for (const target of allDocumentTargets()) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = target.label;
        button.title = target.path;
        button.disabled = disabled;
        button.addEventListener("click", () => {
          startDocumentationAgent(target);
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
        : `docs/${raw.replace(/\\s+/g, "-").toLowerCase()}.md`;
      const label = raw.replace(/\\.md$/i, "") || path;
      return { label, path };
    }

    function addCustomDocumentTarget() {
      if (!activeProjectRoot) {
        return;
      }
      const target = documentTargetFromInput(customDocumentName.value);
      if (!target) {
        return;
      }
      customDocumentTargets = customDocumentTargets.filter(
        (existing) => existing.path !== target.path,
      );
      customDocumentTargets.push(target);
      saveDocumentTargets();
      customDocumentName.value = "";
      customDocumentForm.hidden = true;
      renderDocumentTargets();
    }

    function artifactPreviewUrl(kind) {
      if (kind === "requirements") {
        return `${contextUrl("/artifacts/requirements?embed=1")}&refresh=${Date.now()}`;
      }
      return "";
    }

    function showArtifactPreview(kind) {
      if (!activeProjectRoot) {
        hideArtifactPreview();
        return;
      }
      const url = artifactPreviewUrl(kind);
      if (!url) {
        return;
      }
      artifactPreviewKind = kind;
      artifactPreviewHeader.textContent =
        kind === "requirements" ? "Requirements" : "Artifact";
      artifactPreviewPane.hidden = false;
      artifactPaneResizeHandle.hidden = false;
      sidePane.classList.add("preview-visible");
      refreshArtifactPreview();
      scheduleArtifactPreviewRefresh();
    }

    function hideArtifactPreview() {
      window.clearTimeout(artifactRefreshTimer);
      artifactRefreshTimer = null;
      artifactPreviewKind = "";
      artifactPreviewPane.hidden = true;
      artifactPaneResizeHandle.hidden = true;
      artifactPreviewFrame.removeAttribute("src");
      sidePane.classList.remove("preview-visible");
    }

    function refreshArtifactPreview() {
      const url = artifactPreviewUrl(artifactPreviewKind);
      if (!url) {
        return;
      }
      artifactPreviewFrame.src = url;
    }

    function scheduleArtifactPreviewRefresh() {
      window.clearTimeout(artifactRefreshTimer);
      artifactRefreshTimer = null;
      if (artifactPreviewKind !== "requirements" || !requirementsRunning) {
        return;
      }
      artifactRefreshTimer = window.setTimeout(() => {
        refreshArtifactPreview();
        scheduleArtifactPreviewRefresh();
      }, ARTIFACT_PREVIEW_REFRESH_MS);
    }

    function syncArtifactPreviewWithProject() {
      if (!activeProjectRoot) {
        hideArtifactPreview();
        return;
      }
      if (requirementsRunning) {
        showArtifactPreview("requirements");
        return;
      }
      if (artifactPreviewKind === "requirements" && !requirementsStarted) {
        hideArtifactPreview();
        return;
      }
      scheduleArtifactPreviewRefresh();
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
      if (!contextId || !activationRoot) {
        statusRefreshSequence += 1;
        projectStatusOutput.textContent = "no active project";
        return;
      }
      statusRefreshTimer = window.setTimeout(refreshProjectStatus, delay);
    }

    async function refreshProjectStatus() {
      if (!contextId || !activationRoot) {
        projectStatusOutput.textContent = "no active project";
        return;
      }
      const sequence = ++statusRefreshSequence;
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

    async function applyProjectSelection() {
      const endpoint = projectEndpoint(projectMode);
      const selectedPath = projectPath.value.trim();
      if (!selectedPath) {
        const message = projectMode === "meta-start"
          ? "choose a repository name or path first"
          : "choose a project directory first";
        projectStatus.textContent = message;
        appendOutput(`${message}\\n`, "error");
        return;
      }
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
      activeProjectRoot = payload.active_project_root || "";
      activationRoot = payload.activation_root || activeProjectRoot;
      projectPath.value = activeProjectRoot || activationRoot;
      fileBrowser.hidden = true;
      projectPanel.hidden = true;
      hideStageMenus();
      appendOutput(`${payload.status}: ${activationRoot || activeProjectRoot}\\n`, "system");
      updateProjectState(payload);
      activateProject.disabled = false;
    }

    function projectEndpoint(mode) {
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
      appendOutput(`${payload.status}: ${reference}\\n`, "system");
      updateProjectState(payload);
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
      showProgressPane(false);
      activationRoot = "";
      activeProjectMode = "none";
      activeProjectRoot = "";
      activeRepositoryName = "";
      registeredRepositories = [];
      projectPath.value = serviceRoot;
      projectMenu.hidden = true;
      requirementsMenu.hidden = true;
      hideStageMenus();
      hideStageMenus();
      documentMenu.hidden = true;
      agentInput.disabled = true;
      interruptAgent.disabled = true;
      startRequirements.disabled = false;
      requirementsRunning = false;
      designRunning = false;
      designReviewRunning = false;
      documentationRunning = false;
      agentSessions = [];
      selectedSessionId = "";
      renderSessionSwitcher();
      activeAgentKind = "";
      agentInput.value = "";
      setAgentInputVisible(true);
      clearAgentOutput();
      clearProgressOutput();
      hideArtifactPreview();
      appendOutput(`deactivated: ${previousProject}\\n`, "system");
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
      agentInput.disabled = !acceptsInput;
      insertFileLink.disabled = !acceptsInput;
      interruptAgent.disabled = !sessionIsRunning(selectedSession());
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
      }
      if (kind === "requirements") {
        if (isRunning) {
          showArtifactPreview("requirements");
        } else {
          refreshArtifactPreview();
        }
        scheduleArtifactPreviewRefresh();
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

    async function restartRequirementsAgent() {
      if (currentWorkflowStage === "requirements" && !requirementsStarted) {
        return;
      }
      await runRequirementsAgent(
        "/api/agents/requirements/restart",
        "$ restart requirements authoring",
        true,
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

    async function restartDesignAgent() {
      if (currentWorkflowStage === "design") {
        return;
      }
      await runStageAgent(
        "design",
        "/api/agents/design/restart",
        "$ restart design authoring",
        true,
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

    async function restartDesignReviewAgent() {
      if (currentWorkflowStage === "design-review" && !designReviewStarted) {
        return;
      }
      designReviewInteractive = false;
      await runStageAgent(
        "design-review",
        "/api/agents/design-review/restart",
        "$ restart design review",
        true,
        false,
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

    function openRequirementsDocument() {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      if (currentWorkflowStage === "requirements" && !requirementsStarted) {
        return;
      }
      hideStageMenus();
      window.open(contextUrl("/artifacts/requirements"), "_blank", "noopener");
    }

    function openDesignDocument() {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      hideStageMenus();
      window.open(contextUrl("/artifacts/design"), "_blank", "noopener");
    }

    function openDesignReviewDocument() {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      hideStageMenus();
      window.open(contextUrl("/artifacts/design-review"), "_blank", "noopener");
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
      connectSessionEvents(sessionId);
      sendTerminalResize();
    }

    async function sendMessage() {
      if (!selectedSessionAcceptsInput()) {
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
        body: JSON.stringify({ message }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ error: "send failed" }));
        appendOutput(`${payload.error || "send failed"}\\n`, "error");
      }
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
        documentMenu,
      ];
      for (const menu of menus) {
        if (menu !== exceptMenu) {
          menu.hidden = true;
        }
      }
      if (exceptMenu !== projectMenu) {
        hideSubmenu(metaProjectSubmenu, metaProjectMenuButton);
      }
      hideSubmenu(startMetaRepositorySubmenu, startMetaRepository);
      hideSubmenu(removeMetaRepositorySubmenu, removeMetaRepository);
    }

    function toggleStageMenu(menu, stage) {
      const shouldOpen = menu.hidden;
      hideStageMenus(menu);
      menu.hidden = !shouldOpen;
      if (shouldOpen) {
        positionStageMenu(menu, stage);
      } else if (menu === projectMenu) {
        hideSubmenu(metaProjectSubmenu, metaProjectMenuButton);
        hideSubmenu(startMetaRepositorySubmenu, startMetaRepository);
        hideSubmenu(removeMetaRepositorySubmenu, removeMetaRepository);
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
      if (!documentMenu.hidden) {
        positionStageMenu(documentMenu, documentStage);
      }
    }

    async function handleWorkflowStageClick(stageNode) {
      const stageId = stageNode.dataset.stage || "";
      if (!activeProjectRoot || stageNode.disabled) {
        return;
      }
      const wasCurrentStage = stageId === currentWorkflowStage;
      hideStageMenus();
      if (stageId === "requirements") {
        if (wasCurrentStage) {
          toggleStageMenu(requirementsMenu, requirementsStage);
        } else {
          requirementsMenu.hidden = false;
          positionStageMenu(requirementsMenu, requirementsStage);
        }
        return;
      }
      if (stageId === "design") {
        if (wasCurrentStage) {
          toggleStageMenu(designMenu, designStage);
        } else {
          designMenu.hidden = false;
          positionStageMenu(designMenu, designStage);
        }
        return;
      }
      if (stageId === "design-review") {
        if (wasCurrentStage) {
          toggleStageMenu(designReviewMenu, designReviewStage);
        } else {
          designReviewMenu.hidden = false;
          positionStageMenu(designReviewMenu, designReviewStage);
        }
        return;
      }
      if (stageId === "document") {
        toggleStageMenu(documentMenu, documentStage);
        return;
      }
      if (!wasCurrentStage) {
        const selected = await selectWorkflowStage(stageId);
        if (!selected) {
          return;
        }
      }
      hideStageMenus();
    }

    projectStage.addEventListener("click", () => {
      toggleStageMenu(projectMenu, projectStage);
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

    openProject.addEventListener("click", () => showProjectPanel("open"));
    newProject.addEventListener("click", () => showProjectPanel("new"));
    openMetaProject.addEventListener("click", () => showProjectPanel("open"));
    newMetaProject.addEventListener("click", () => showProjectPanel("meta-new"));
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
    deactivateProject.addEventListener("click", deactivateActiveProject);
    browseProject.addEventListener("click", () => {
      browseDirectory(
        projectPath.value || activeProjectRoot || activationRoot || serviceRoot || ".",
        "project",
      );
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

    startRequirements.addEventListener("click", startRequirementsAgent);
    restartRequirements.addEventListener("click", restartRequirementsAgent);
    approveRequirements.addEventListener("click", approveRequirementsStage);
    skipRequirementsApproval.addEventListener("click", skipRequirementsApprovalStage);
    openRequirements.addEventListener("click", openRequirementsDocument);
    startDesign.addEventListener("click", startDesignAgent);
    restartDesign.addEventListener("click", restartDesignAgent);
    completeDesign.addEventListener("click", completeDesignAgent);
    openDesign.addEventListener("click", openDesignDocument);
    startAutomaticDesignReview.addEventListener("click", startAutomaticDesignReviewAgent);
    startInteractiveDesignReview.addEventListener("click", startInteractiveDesignReviewAgent);
    stopDesignReview.addEventListener("click", stopDesignReviewAgent);
    approveDesignReview.addEventListener("click", approveDesignReviewStage);
    skipDesignReviewApproval.addEventListener("click", skipDesignReviewApprovalStage);
    restartDesignReview.addEventListener("click", restartDesignReviewAgent);
    openDesignReview.addEventListener("click", openDesignReviewDocument);
    openDesignFromReview.addEventListener("click", openDesignDocument);
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
    decreaseTerminalFont.addEventListener("click", () => changeTerminalFontSize(-1));
    increaseTerminalFont.addEventListener("click", () => changeTerminalFontSize(1));
    shellResizeHandle.addEventListener("pointerdown", startShellResize);
    shellResizeHandle.addEventListener("pointermove", updateShellResize);
    shellResizeHandle.addEventListener("pointerup", finishShellResize);
    shellResizeHandle.addEventListener("pointercancel", finishShellResize);
    inputResizeHandle.addEventListener("pointerdown", startInputResize);
    inputResizeHandle.addEventListener("pointermove", updateInputResize);
    inputResizeHandle.addEventListener("pointerup", finishInputResize);
    inputResizeHandle.addEventListener("pointercancel", finishInputResize);
    outputResizeHandle.addEventListener("pointerdown", startOutputResize);
    outputResizeHandle.addEventListener("pointermove", updateOutputResize);
    outputResizeHandle.addEventListener("pointerup", finishOutputResize);
    outputResizeHandle.addEventListener("pointercancel", finishOutputResize);
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
    insertFileLink.addEventListener("click", () => {
      if (insertFileLink.disabled) {
        return;
      }
      browseDirectory(activeProjectRoot || serviceRoot || ".", "link");
    });
    stageScroll.addEventListener("scroll", repositionOpenStageMenu);
    window.addEventListener("resize", repositionOpenStageMenu);

    agentInput.addEventListener("keydown", (event) => {
      const isEnter =
        event.key === "Enter" ||
        event.code === "Enter" ||
        event.code === "NumpadEnter";
      if (isEnter && event.shiftKey) {
        event.preventDefault();
        sendMessage();
      }
    });
    scratchPad.addEventListener("input", saveScratchPad);

    async function initialize() {
      applyStageDescriptions();
      applyStoredPaneSizes();
      applyStoredProgressPaneSize();
      applyStoredWorkbenchPaneSize();
      restoreScratchPad();
      applyTerminalFontSize();
      initializeTerminal();
      await checkConnection();
      await restoreContext();
    }

    initialize().catch(() => {});
  </script>
</body>
</html>
"""


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
    documentation_session: AgentSession | None = None
    selected_session_id: str | None = None
    workflow_stage: str | None = None
    requirements_started: bool = False
    design_started: bool = False
    design_review_started: bool = False
    design_review_interactive: bool = False


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
            context.documentation_session = None
            context.selected_session_id = None
            context.workflow_stage = workflow_stage
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
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
            context.documentation_session = None
            context.selected_session_id = None
            context.workflow_stage = _visible_workflow_stage(manifest.active_stage)
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
        return {
            **project_payload(self.root, context, project_root),
            "status": "created",
            "run_id": manifest.run_id,
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
            context.documentation_session = None
            context.selected_session_id = None
            context.workflow_stage = meta_context["workflow_stage"]
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            project_root = context.active_project_root
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
            context.documentation_session = None
            context.selected_session_id = None
            context.workflow_stage = None
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
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
            context.documentation_session = None
            context.selected_session_id = None
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
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
            context.documentation_session = None
            context.selected_session_id = None
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            project_root = context.active_project_root
        return {
            **project_payload(self.root, context, project_root),
            "status": "removed",
        }

    def deactivate_project(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            sessions = self._context_sessions_locked(context)
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
            context.documentation_session = None
            context.selected_session_id = None
            context.workflow_stage = None
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
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
            if (
                context.documentation_session is not None
                and context.documentation_session.is_active()
            ):
                context.selected_session_id = context.documentation_session.session_id
                return context.documentation_session, False
            lock_names = SESSION_ARTIFACT_LOCKS["documentation"]
            self._require_session_locks_available_locked(context, lock_names)
            target_path = (target or "").strip()
            label_target = f" ({target_path})" if target_path else ""
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
            )
            context.documentation_session = session
            context.selected_session_id = session.session_id
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.documentation_session is session:
                    context.documentation_session = None
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
            return context.documentation_session

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

    def has_running_progress_agent(self, context_id: str) -> bool:
        with self.lock:
            context = self._context_locked(context_id)
            design_review_session = context.design_review_session
            return bool(
                design_review_session is not None
                and design_review_session.is_active()
                and not context.design_review_interactive
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
                context.documentation_session,
            ]
            if session is not None
        ]

    def _all_sessions_locked(self) -> list[AgentSession]:
        sessions: list[AgentSession] = []
        seen: set[int] = set()
        for context in self.contexts.values():
            for session in self._context_sessions_locked(context):
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
            if context.documentation_session is session:
                context.documentation_session = None
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
            for session in self._context_sessions_locked(context)
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
    ) -> None:
        self.session_id = uuid4().hex
        self.command = command
        self.cwd = Path(cwd).resolve()
        self.columns = columns
        self.rows = rows
        self.label = label
        self.kind = kind
        self.interactive = interactive
        self.lock_names = frozenset(lock_names or ())
        self.created_at = utc_now()
        self.on_completed = on_completed
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
        }

    def start(self) -> None:
        if self.process is not None:
            return
        master_fd, slave_fd = pty.openpty()
        env = _agent_process_env()
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
        self.columns = max(20, min(columns, 300))
        self.rows = max(5, min(rows, 120))
        fd = self._master_fd
        if fd is None:
            return
        _set_terminal_size(fd, self.columns, self.rows)

    def events_after(self, event_id: int) -> list[dict[str, object]]:
        with self._condition:
            return [
                event.copy()
                for event in self._events
                if int(event.get("id", 0)) > event_id
            ]

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
    documentation_session = context.documentation_session
    documentation_running = bool(
        active_root
        and documentation_session is not None
        and documentation_session.is_active()
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
        "documentation_running": documentation_running,
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
            if activation_root
            else None
        ),
        "selected_session_id": context.selected_session_id,
        "sessions": _session_payloads(context),
    }


def _session_payloads(context: BrowserContext) -> list[dict[str, object]]:
    selected_session_id = context.selected_session_id
    payloads: list[dict[str, object]] = []
    for session in [
        context.requirements_session,
        context.design_session,
        context.design_review_session,
        context.documentation_session,
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
            }
        )
    return payloads


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
    except OSError:
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


def browse_directories(path: Path | str) -> dict[str, object]:
    directory = Path(path).expanduser().resolve()
    if not directory.exists():
        raise StateError(f"directory does not exist: {directory}")
    if not directory.is_dir():
        raise StateError(f"path is not a directory: {directory}")

    try:
        children = sorted(
            [child for child in directory.iterdir() if child.is_dir()],
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


def browse_files(path: Path | str) -> dict[str, object]:
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
            "Start",
            "Restart",
            "Approve",
            "Skip approval",
            "Open requirements",
        ]
    if stage == "design" and active_project_root:
        return ["Start", "Restart", "Complete", "Open design"]
    if stage == "design-review" and active_project_root:
        return [
            "Start automatic",
            "Start interactive",
            "Stop",
            "Approve",
            "Skip approval",
            "Restart review",
            "Open review",
            "Open design",
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
) -> tuple[str, HTTPStatus]:
    return markdown_document_html(
        project_root,
        "docs/requirements.md",
        "Requirements",
        "Requirements document does not exist yet.",
        embedded=embedded,
    )


def design_document_html(project_root: Path | str) -> tuple[str, HTTPStatus]:
    return markdown_document_html(
        project_root,
        "docs/detailed-design.md",
        "Design",
        "Design document does not exist yet.",
    )


def design_review_document_html(project_root: Path | str) -> tuple[str, HTTPStatus]:
    return markdown_document_html(
        project_root,
        "docs/design-review.md",
        "Design Review",
        "Design review document does not exist yet.",
    )


def markdown_document_html(
    project_root: Path | str,
    relative_path: str,
    title: str,
    missing_message: str,
    *,
    embedded: bool = False,
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
    main_padding = "16px" if embedded else "40px 24px 64px"
    article_padding = "18px" if embedded else "28px"
    article_radius = "0" if embedded else "8px"
    article_border = "0" if embedded else "1px solid #d8dde8"
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{
      margin: 0;
      background: #f7f8fb;
      color: #1b1f2a;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.55;
    }}
    main {{
      max-width: 880px;
      margin: 0 auto;
      padding: {main_padding};
    }}
    article {{
      background: #ffffff;
      border: {article_border};
      border-radius: {article_radius};
      padding: {article_padding};
    }}
    pre, code {{
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    }}
    pre {{
      overflow: auto;
      padding: 12px;
      background: #f1f4f9;
      border-radius: 6px;
    }}
  </style>
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


def _render_markdown(text: str) -> str:
    try:
        import markdown as markdown_library
    except ImportError:
        return f"<pre>{html.escape(text)}</pre>"
    return str(markdown_library.markdown(text, extensions=["extra", "sane_lists"]))


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


def _electroboy_command(root: Path, args: list[str]) -> list[str]:
    activate_script = root / ".electroboy" / "bin" / "activate"
    command_parts = ["electroboy", *args]
    command_text = " ".join(shlex.quote(part) for part in command_parts)
    if activate_script.exists():
        return [
            "/bin/sh",
            "-c",
            f". {shlex.quote(str(activate_script))} >/dev/null && "
            f"{command_text}",
        ]
    return [
        sys.executable,
        "-m",
        "electroboy",
        "--root",
        str(root),
        *args,
    ]


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


def _set_terminal_size(fd: int, columns: int, rows: int) -> None:
    columns = max(20, min(columns, 300))
    rows = max(5, min(rows, 120))
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
            if path == "/api/progress/events":
                self._send_progress_events(parsed.query)
                return
            if path == "/api/sessions/events":
                self._send_selected_session_events(parsed.query)
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
            if path == "/api/project/deactivate":
                self._deactivate_project(parsed.query)
                return
            if path == "/api/workflow/stage":
                self._select_workflow_stage(parsed.query)
                return
            if path == "/api/sessions/select":
                self._select_session(parsed.query)
                return
            if path == "/api/sessions/message":
                self._send_selected_session_message(parsed.query)
                return
            if path == "/api/sessions/interrupt":
                self._interrupt_selected_session(parsed.query)
                return
            if path == "/api/sessions/resize":
                self._resize_selected_session(parsed.query)
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

        def _browse_files(self, query: str) -> None:
            params = parse_qs(query)
            path = (params.get("path") or [str(state.root)])[0]
            mode = (params.get("mode") or ["directory"])[0]
            try:
                payload = (
                    browse_files(path)
                    if mode == "file"
                    else browse_directories(path)
                )
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
                state.send_selected_session_message(context_id, message)
            except (AgentSessionError, StateError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
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
                state.resize_selected_session(context_id, columns, rows)
            except (AgentSessionError, StateError, TypeError, ValueError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"status": "resized"})

        def _send_requirements_document(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                project_root = state.requirements_document_root(context_id)
                params = parse_qs(query)
                embedded = str((params.get("embed") or [""])[0]) == "1"
                page, status = requirements_document_html(
                    project_root,
                    embedded=embedded,
                )
            except (AgentSessionError, OSError, StateError) as error:
                self._send_text(
                    f"<p>{html.escape(str(error))}</p>",
                    "text/html; charset=utf-8",
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_text(page, "text/html; charset=utf-8", status=status)

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
