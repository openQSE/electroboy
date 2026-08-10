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
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from .artifacts import ArtifactManager
from .feature_artifacts import read_feature_record
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
WORK_ITEM_REGISTRY_RELATIVE_PATH = Path(".electroboy") / "shared" / "work-items.json"

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
    "documentation": frozenset(
        {
            "documentation.jsonl",
            "README.md",
            "docs/api.md",
        }
    ),
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

    .workflow-toolbar {
      position: absolute;
      top: 14px;
      left: 24px;
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
      height: calc(var(--ui-font-size) + 29px);
      min-height: 38px;
      overflow: hidden;
      border: 1px solid #c8d5e2;
      border-radius: 8px;
      background: #f7fbff;
      box-shadow:
        0 1px 0 rgb(255 255 255 / 80%) inset,
        0 6px 16px rgb(17 24 39 / 6%);
    }

    .toolbar-control-label {
      display: inline-flex;
      align-items: center;
      align-self: stretch;
      flex: 0 0 calc(var(--ui-font-size) * 4.7);
      border-right: 1px solid #d8e1ec;
      color: #4a5a6d;
      padding: 0 10px;
      font-size: var(--ui-small-font-size);
      font-weight: 800;
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
      background: #edf6fb;
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
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 1180px;
      padding-top: 54px;
    }

    .stage-graph::before {
      content: none;
    }

    .stage-connector {
      position: relative;
      z-index: 1;
      flex: 0 0 28px;
      color: #6f7f90;
      font-size: var(--ui-small-font-size);
      font-weight: 850;
      text-align: center;
      pointer-events: none;
    }

    .stage-node {
      position: relative;
      z-index: 1;
      flex: 1 0 112px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 0;
      min-height: 46px;
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
      margin-left: 22px;
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

    .output-workbench.side-popped {
      grid-template-columns: minmax(0, 1fr);
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

    .output-resize-handle,
    .artifact-pane-resize-handle {
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
    .output-split.resizing-artifact .artifact-pane-resize-handle {
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
    .side-pane-resize-handle[hidden] {
      display: none;
    }

    .terminal-pane,
    .artifact-preview-pane {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      min-height: 0;
      min-width: 0;
      overflow: hidden;
      background: var(--terminal);
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
      font-weight: 750;
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

    .pane-actions,
    .document-zoom-controls {
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
    }

    .document-zoom-controls {
      color: #d8e3f4;
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

    .document-zoom-button:hover:not(:disabled) {
      border-color: #4e7f9d;
      background: #22314a;
    }

    .document-zoom-button:disabled {
      cursor: default;
      opacity: 0.45;
    }

    .document-zoom-level {
      min-width: 42px;
      text-align: center;
      color: #aab8cf;
      font-size: var(--ui-small-font-size);
      font-weight: 750;
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
      grid-template-rows: auto minmax(0, 1fr);
      grid-template-columns:
        minmax(260px, 1fr) 7px
        minmax(160px, var(--input-actions-width, 196px));
      min-height: 0;
      gap: 8px;
      border-top: 1px solid #2a3142;
      background: #151b29;
      padding: 12px;
    }

    .input-pane-header {
      grid-column: 1 / -1;
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
      font-size: var(--terminal-font-size);
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
      font-weight: 650;
      padding: 0 32px 0 0;
    }

    .session-switcher:disabled {
      color: #667085;
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
      font-weight: 750;
    }

    .terminal-font-button {
      align-self: stretch;
      flex: 0 0 calc(var(--ui-font-size) + 31px);
      min-width: 40px;
      border-radius: 0;
    }

    .terminal-font-button + .terminal-font-value,
    .terminal-font-value + .terminal-font-button {
      border-left: 1px solid #d8e1ec;
    }

    .terminal-font-value {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      align-self: stretch;
      flex: 1 1 auto;
      min-width: 54px;
      color: #4a5a6d;
      font-size: var(--ui-small-font-size);
      font-weight: 800;
      background: #ffffff;
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
        min-width: 1260px;
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
  <main class="shell">
    <section class="workflow-pane" aria-label="Project workflow">
      <div id="connection" class="connection"></div>
      <div class="workflow-toolbar" aria-label="Agent controls">
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
      </div>
      <div class="stage-scroll">
        <div class="stage-graph" aria-label="Project stages">
          <button class="stage-node active" type="button" data-stage="project">
            project
          </button>
          <span class="stage-connector" aria-hidden="true">&lt;-&gt;</span>
          <button
            class="stage-node disabled"
            type="button"
            data-stage="requirements"
            disabled
          >
            requirements
          </button>
          <span class="stage-connector" aria-hidden="true">&lt;-&gt;</span>
          <button class="stage-node disabled" type="button" data-stage="design" disabled>
            design
          </button>
          <span class="stage-connector" aria-hidden="true">&lt;-&gt;</span>
          <button class="stage-node disabled" type="button" data-stage="design-review" disabled>
            design-review
          </button>
          <span class="stage-connector" aria-hidden="true">&lt;-&gt;</span>
          <button
            class="stage-node disabled"
            type="button"
            data-stage="implementation-plan"
            disabled
          >
            implementation-plan
          </button>
          <span class="stage-connector" aria-hidden="true">&lt;-&gt;</span>
          <button class="stage-node disabled" type="button" data-stage="code" disabled>
            code
          </button>
          <span class="stage-connector" aria-hidden="true">&lt;-&gt;</span>
          <button class="stage-node disabled" type="button" data-stage="test-plan" disabled>
            test-plan
          </button>
          <span class="stage-connector" aria-hidden="true">&lt;-&gt;</span>
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
      <div id="implementationPlanMenu" class="stage-menu" hidden>
        <button id="startImplementationPlan" type="button">Start</button>
        <button id="restartImplementationPlan" type="button">Restart</button>
        <button id="approveImplementationPlan" type="button">Approve</button>
        <button id="skipImplementationPlanApproval" type="button">Skip approval</button>
        <button id="openImplementationPlan" type="button">Open implementation plan</button>
      </div>
      <div id="codeMenu" class="stage-menu" hidden>
        <button id="startAutomaticCode" type="button">Start automatic</button>
        <button id="startInteractiveCode" type="button">Start interactive</button>
        <button id="stopCode" type="button">Stop</button>
        <button id="approveCode" type="button">Approve</button>
        <button id="skipCodeApproval" type="button">Skip approval</button>
        <button id="restartCode" type="button">Restart</button>
        <button id="openImplementationReport" type="button">Open implementation report</button>
      </div>
      <div id="testPlanMenu" class="stage-menu" hidden>
        <button id="startTestPlan" type="button">Start</button>
        <button id="restartTestPlan" type="button">Restart</button>
        <button id="approveTestPlan" type="button">Approve</button>
        <button id="skipTestPlanApproval" type="button">Skip approval</button>
        <button id="openTestPlan" type="button">Open test plan</button>
      </div>
      <div id="validateMenu" class="stage-menu" hidden>
        <button id="startAutomaticValidate" type="button">Start automatic</button>
        <button id="startInteractiveValidate" type="button">Start interactive</button>
        <button id="stopValidate" type="button">Stop</button>
        <button id="approveValidate" type="button">Approve</button>
        <button id="skipValidateApproval" type="button">Skip approval</button>
        <button id="restartValidate" type="button">Restart</button>
        <button id="openValidationReport" type="button">Open validation report</button>
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
                <button
                  id="popoutAgentPane"
                  class="pane-popout-button"
                  type="button"
                  title="Pop out agent output"
                  aria-label="Pop out agent output"
                >Pop</button>
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
              <div id="artifactPreviewHeader" class="pane-header">
                <span id="artifactPreviewTitle" class="pane-title">Requirements</span>
                <div class="pane-actions">
                  <div class="document-zoom-controls" aria-label="Document zoom">
                    <button
                      id="decreaseDocumentZoom"
                      class="document-zoom-button"
                      type="button"
                      title="Zoom document out"
                      aria-label="Zoom document out"
                    >-</button>
                    <span id="documentZoomLevel" class="document-zoom-level">100%</span>
                    <button
                      id="increaseDocumentZoom"
                      class="document-zoom-button"
                      type="button"
                      title="Zoom document in"
                      aria-label="Zoom document in"
                    >+</button>
                  </div>
                  <button
                    id="popoutArtifactPane"
                    class="pane-popout-button"
                    type="button"
                    title="Pop out artifact preview"
                    aria-label="Pop out artifact preview"
                  >Pop</button>
                </div>
              </div>
              <iframe
        id="artifactPreviewFrame"
        class="artifact-preview-frame"
        title="Rendered artifact preview"
        sandbox="allow-scripts allow-popups"
      ></iframe>
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
                <button
                  id="popoutProgressPane"
                  class="pane-popout-button"
                  type="button"
                  title="Pop out progress output"
                  aria-label="Pop out progress output"
                >Pop</button>
              </div>
              <div id="progressOutput" class="progress-output" aria-live="polite"></div>
            </section>
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
          aria-label="Scratch pad and status"
        >
          <section class="scratch-pane" aria-label="Scratch pad">
            <div class="side-pane-header">
              <span class="pane-title">Scratch pad</span>
              <button
                id="popoutScratchPane"
                class="pane-popout-button"
                type="button"
                title="Pop out scratch pad"
                aria-label="Pop out scratch pad"
              >Pop</button>
            </div>
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
          <section class="project-status-pane" aria-label="Project status">
            <div class="side-pane-header">
              <span class="pane-title">Project status</span>
              <button
                id="popoutStatusPane"
                class="pane-popout-button"
                type="button"
                title="Pop out project status"
                aria-label="Pop out project status"
              >Pop</button>
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
          <button
            id="popoutInputPane"
            class="pane-popout-button"
            type="button"
            title="Pop out AI agent input"
            aria-label="Pop out AI agent input"
          >Pop</button>
        </div>
        <textarea
          id="agentInput"
          class="agent-input"
          spellcheck="false"
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
    const startImplementationPlan = document.getElementById("startImplementationPlan");
    const restartImplementationPlan = document.getElementById("restartImplementationPlan");
    const approveImplementationPlan = document.getElementById("approveImplementationPlan");
    const skipImplementationPlanApproval =
      document.getElementById("skipImplementationPlanApproval");
    const openImplementationPlan = document.getElementById("openImplementationPlan");
    const startAutomaticCode = document.getElementById("startAutomaticCode");
    const startInteractiveCode = document.getElementById("startInteractiveCode");
    const stopCode = document.getElementById("stopCode");
    const approveCode = document.getElementById("approveCode");
    const skipCodeApproval = document.getElementById("skipCodeApproval");
    const restartCode = document.getElementById("restartCode");
    const openImplementationReport = document.getElementById("openImplementationReport");
    const startTestPlan = document.getElementById("startTestPlan");
    const restartTestPlan = document.getElementById("restartTestPlan");
    const approveTestPlan = document.getElementById("approveTestPlan");
    const skipTestPlanApproval = document.getElementById("skipTestPlanApproval");
    const openTestPlan = document.getElementById("openTestPlan");
    const startAutomaticValidate = document.getElementById("startAutomaticValidate");
    const startInteractiveValidate = document.getElementById("startInteractiveValidate");
    const stopValidate = document.getElementById("stopValidate");
    const approveValidate = document.getElementById("approveValidate");
    const skipValidateApproval = document.getElementById("skipValidateApproval");
    const restartValidate = document.getElementById("restartValidate");
    const openValidationReport = document.getElementById("openValidationReport");
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
    const agentOutputPane = document.getElementById("agentOutputPane");
    const agentOutput = document.getElementById("agentOutput");
    const outputResizeHandle = document.getElementById("outputResizeHandle");
    const progressOutputPane = document.getElementById("progressOutputPane");
    const progressOutput = document.getElementById("progressOutput");
    const sidePane = document.getElementById("sidePane");
    const sidePaneResizeHandle = document.getElementById("sidePaneResizeHandle");
    const scratchPane = document.querySelector(".scratch-pane");
    const scratchPad = document.getElementById("scratchPad");
    const artifactPreviewPane = document.getElementById("artifactPreviewPane");
    const artifactPaneResizeHandle = document.getElementById("artifactPaneResizeHandle");
    const artifactPreviewTitle = document.getElementById("artifactPreviewTitle");
    const artifactPreviewFrame = document.getElementById("artifactPreviewFrame");
    const decreaseDocumentZoom = document.getElementById("decreaseDocumentZoom");
    const documentZoomLevel = document.getElementById("documentZoomLevel");
    const increaseDocumentZoom = document.getElementById("increaseDocumentZoom");
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
    const interruptAgent = document.getElementById("interruptAgent");
    const insertFileLink = document.getElementById("insertFileLink");
    const popoutAgentPane = document.getElementById("popoutAgentPane");
    const popoutArtifactPane = document.getElementById("popoutArtifactPane");
    const popoutProgressPane = document.getElementById("popoutProgressPane");
    const popoutScratchPane = document.getElementById("popoutScratchPane");
    const popoutStatusPane = document.getElementById("popoutStatusPane");
    const popoutInputPane = document.getElementById("popoutInputPane");
    const CONTEXT_STORAGE_KEY = "electroboy.contextId";
    const TERMINAL_FONT_STORAGE_KEY = "electroboy.terminalFontSize";
    const DOCUMENT_ZOOM_STORAGE_KEY = "electroboy.documentZoom";
    const WORKFLOW_PANE_HEIGHT_STORAGE_KEY = "electroboy.workflowPaneHeight";
    const INPUT_PANE_HEIGHT_STORAGE_KEY = "electroboy.inputPaneHeight";
    const INPUT_ACTIONS_WIDTH_STORAGE_KEY = "electroboy.inputActionsWidth";
    const PROGRESS_PANE_WIDTH_STORAGE_KEY = "electroboy.progressPaneWidth";
    const PROGRESS_PANE_HEIGHT_STORAGE_KEY = "electroboy.progressPaneHeight";
    const RIGHT_PANE_WIDTH_STORAGE_KEY = "electroboy.rightPaneWidth";
    const RIGHT_PANE_HEIGHT_STORAGE_KEY = "electroboy.rightPaneHeight";
    const SCRATCH_PANE_HEIGHT_STORAGE_KEY = "electroboy.scratchPaneHeight";
    const ARTIFACT_PANE_WIDTH_STORAGE_KEY = "electroboy.artifactPaneWidth";
    const ARTIFACT_PANE_HEIGHT_STORAGE_KEY = "electroboy.artifactPaneHeight";
    const SCRATCH_PAD_STORAGE_KEY = "electroboy.scratchPad";
    const DOCUMENT_TARGETS_STORAGE_KEY = "electroboy.documentTargets";
    const PANE_POPUP_FEATURES =
      "popup=yes,width=980,height=720,menubar=no,toolbar=no,location=no,status=no,scrollbars=yes,resizable=yes";
    const DEFAULT_DOCUMENT_TARGETS = [
      { label: "README", path: "README.md" },
      { label: "API", path: "docs/api.md" },
    ];
    const DEFAULT_TERMINAL_FONT_SIZE = 15;
    const MIN_TERMINAL_FONT_SIZE = 11;
    const MAX_TERMINAL_FONT_SIZE = 24;
    const DEFAULT_DOCUMENT_ZOOM = 100;
    const DOCUMENT_ZOOM_STEP = 10;
    const MIN_DOCUMENT_ZOOM = 70;
    const MAX_DOCUMENT_ZOOM = 180;
    const MIN_INPUT_PANE_HEIGHT = 56;
    const MIN_INPUT_ACTIONS_WIDTH = 160;
    const MIN_AGENT_INPUT_WIDTH = 260;
    let eventSource = null;
    let progressEventSource = null;
    let artifactEventSource = null;
    let terminal = null;
    let terminalFit = null;
    let progressTerminal = null;
    let progressTerminalFit = null;
    let terminalFontSize = storedTerminalFontSize();
    let documentZoom = storedDocumentZoom();
    let resizeShellState = null;
    let resizeInputState = null;
    let resizeInputActionsState = null;
    let resizeOutputState = null;
    let resizeWorkbenchState = null;
    let resizeSidePaneState = null;
    let resizeArtifactPaneState = null;
    let resizeTimer = null;
    let statusRefreshTimer = null;
    let statusRefreshSequence = 0;
    let artifactPreviewKind = "";
    let artifactPreviewDocumentTarget = null;
    let artifactPreviewVersion = 0;
    let progressPaneRequested = false;
    let artifactPaneRequested = false;
    let inputPaneRequested = true;
    const poppedPanes = new Set();
    const poppedPaneWindows = new Map();
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
    let workItemState = { collections: [], features: [], bugs: [] };
    let stageRunState = {};
    let workItemMode = "";
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

    function applyStoredPaneSizes() {
      const workflowHeight = storedNumber(WORKFLOW_PANE_HEIGHT_STORAGE_KEY);
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

    function saveRightPaneWidth(width) {
      saveNumber(RIGHT_PANE_WIDTH_STORAGE_KEY, width);
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

    function changeDocumentZoom(delta) {
      documentZoom = clampDocumentZoom(documentZoom + delta);
      saveDocumentZoom();
      applyDocumentZoom();
      if (artifactPreviewKind) {
        refreshArtifactPreview();
      }
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

    function applyDocumentZoom() {
      documentZoomLevel.textContent = `${documentZoom}%`;
      decreaseDocumentZoom.disabled = documentZoom <= MIN_DOCUMENT_ZOOM;
      increaseDocumentZoom.disabled = documentZoom >= MAX_DOCUMENT_ZOOM;
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
        artifactPaneRequested && artifactPreviewKind && !poppedPanes.has("artifact");
      const progressVisible = progressPaneRequested && !poppedPanes.has("progress");
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

    function paneUrl(kind) {
      const parameters = new URLSearchParams();
      if (contextId) {
        parameters.set("context_id", contextId);
      }
      if (selectedSessionId) {
        parameters.set("session_id", selectedSessionId);
      }
      if (artifactPreviewKind) {
        parameters.set("artifact", artifactPreviewKind);
      }
      if (artifactPreviewKind === "document" && artifactPreviewDocumentTarget) {
        parameters.set("document_path", artifactPreviewDocumentTarget.path);
        parameters.set("document_title", artifactPreviewDocumentTarget.label);
      }
      parameters.set("font_size", String(terminalFontSize));
      parameters.set("document_zoom", String(documentZoom));
      return `/pane/${encodeURIComponent(kind)}?${parameters.toString()}`;
    }

    function popOutPane(kind) {
      if (!contextId && kind !== "scratch") {
        appendOutput("create a browser context first\\n", "error");
        return;
      }
      const popup = window.open(
        paneUrl(kind),
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
        applyOutputPaneVisibility();
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
        if (!isInteractive && session.status === "running") {
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
      workItemState = payload.work_items || { collections: [], features: [], bugs: [] };
      stageRunState = payload.stage_runs || {};
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
      syncArtifactPreviewWithProject();
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
        ? `${session.kind || "agent"}: ${status}`
        : "No selected agent";
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
        const status = session.status === "running" ? "running" : session.status || "done";
        option.textContent = `${session.kind || "agent"} · ${status}`;
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

    function updateGenericStageMenuStates() {
      updateAuthoringStageMenuState(
        "implementation-plan",
        startImplementationPlan,
        restartImplementationPlan,
        approveImplementationPlan,
        skipImplementationPlanApproval,
        openImplementationPlan,
      );
      updateAutomaticStageMenuState(
        "code",
        startAutomaticCode,
        startInteractiveCode,
        stopCode,
        approveCode,
        skipCodeApproval,
        restartCode,
        openImplementationReport,
      );
      updateAuthoringStageMenuState(
        "test-plan",
        startTestPlan,
        restartTestPlan,
        approveTestPlan,
        skipTestPlanApproval,
        openTestPlan,
      );
      updateAutomaticStageMenuState(
        "validate",
        startAutomaticValidate,
        startInteractiveValidate,
        stopValidate,
        approveValidate,
        skipValidateApproval,
        restartValidate,
        openValidationReport,
      );
    }

    function updateAuthoringStageMenuState(
      stage,
      startButton,
      restartButton,
      approveButton,
      skipButton,
      openButton,
    ) {
      const hasActiveProject = Boolean(activeProjectRoot);
      const inStage = currentWorkflowStage === stage;
      const runState = genericStageRun(stage);
      startButton.disabled = !hasActiveProject || !inStage || runState.running;
      restartButton.disabled = !hasActiveProject || (inStage && !runState.started);
      approveButton.disabled = !hasActiveProject || !inStage;
      skipButton.disabled = !hasActiveProject || !inStage;
      openButton.disabled = !hasActiveProject || (inStage && !runState.started);
    }

    function updateAutomaticStageMenuState(
      stage,
      startAutomaticButton,
      startInteractiveButton,
      stopButton,
      approveButton,
      skipButton,
      restartButton,
      openButton,
    ) {
      const hasActiveProject = Boolean(activeProjectRoot);
      const inStage = currentWorkflowStage === stage;
      const runState = genericStageRun(stage);
      startAutomaticButton.disabled =
        !hasActiveProject || !inStage || runState.running || runState.started;
      startInteractiveButton.disabled =
        !hasActiveProject || !inStage || runState.running || runState.started;
      stopButton.disabled = !hasActiveProject || !inStage || !runState.running;
      approveButton.disabled = !hasActiveProject || !inStage;
      skipButton.disabled = !hasActiveProject || !inStage;
      restartButton.disabled = !hasActiveProject || (inStage && !runState.started);
      openButton.disabled = !hasActiveProject || (inStage && !runState.started);
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
      showDocumentPreview(target);
    }

    function artifactPreviewUrl(kind) {
      if (kind === "requirements") {
        return `${contextUrl("/artifacts/requirements?embed=1")}&zoom=${documentZoom}&version=${artifactPreviewVersion}`;
      }
      if (kind === "document" && artifactPreviewDocumentTarget) {
        const parameters = new URLSearchParams();
        parameters.set("path", artifactPreviewDocumentTarget.path);
        parameters.set("title", artifactPreviewDocumentTarget.label);
        parameters.set("embed", "1");
        parameters.set("create", "1");
        parameters.set("zoom", String(documentZoom));
        parameters.set("version", String(artifactPreviewVersion));
        return contextUrl(`/artifacts/document?${parameters.toString()}`);
      }
      return "";
    }

    function showArtifactPreview(kind, options = {}) {
      if (!activeProjectRoot) {
        hideArtifactPreview();
        return;
      }
      if (kind === "document") {
        artifactPreviewDocumentTarget = options.target || artifactPreviewDocumentTarget;
      } else {
        artifactPreviewDocumentTarget = null;
      }
      const url = artifactPreviewUrl(kind);
      if (!url) {
        return;
      }
      artifactPreviewKind = kind;
      artifactPaneRequested = true;
      artifactPreviewTitle.textContent =
        kind === "requirements"
          ? "Requirements"
          : (artifactPreviewDocumentTarget?.label || "Document");
      applyStoredArtifactPaneSize();
      applyOutputPaneVisibility();
      refreshArtifactPreview();
      connectArtifactEvents(kind);
    }

    function showDocumentPreview(target) {
      if (!target) {
        return;
      }
      showArtifactPreview("document", { target });
    }

    function hideArtifactPreview() {
      artifactPreviewKind = "";
      artifactPreviewDocumentTarget = null;
      artifactPaneRequested = false;
      closeArtifactEventStream();
      artifactPreviewFrame.removeAttribute("src");
      applyOutputPaneVisibility();
    }

    function refreshArtifactPreview() {
      artifactPreviewVersion += 1;
      const url = artifactPreviewUrl(artifactPreviewKind);
      if (!url) {
        return;
      }
      artifactPreviewFrame.src = url;
    }

    function connectArtifactEvents(kind) {
      closeArtifactEventStream();
      if (kind !== "requirements" || !requirementsRunning) {
        return;
      }
      artifactEventSource = new EventSource(
        contextUrl("/api/artifacts/events?artifact=requirements"),
      );
      artifactEventSource.addEventListener("artifact-event", () => {
        refreshArtifactPreview();
      });
      artifactEventSource.onerror = () => {};
    }

    function closeArtifactEventStream() {
      if (artifactEventSource) {
        artifactEventSource.close();
        artifactEventSource = null;
      }
    }

    function syncArtifactPreviewWithProject() {
      if (!activeProjectRoot) {
        hideArtifactPreview();
        return;
      }
      if (artifactPreviewKind === "document") {
        connectArtifactEvents(artifactPreviewKind);
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
      if (artifactPreviewKind) {
        connectArtifactEvents(artifactPreviewKind);
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
        applyWorkItem.disabled = false;
        return;
      }
      hideWorkItemPanel();
      appendOutput(`${payload.status}: ${payload.label || title}\\n`, "system");
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
      hideStageMenus();
      const response = await fetch(contextUrl(endpoint), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => ({ error: "switch failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "switch failed"}\\n`, "error");
        return;
      }
      appendOutput(`${successLabel}: ${payload.label || ""}\\n`, "system");
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
      workItemState = { collections: [], features: [], bugs: [] };
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
      stageRunState = {};
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
      hideWorkItemPanel();
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
          if (artifactPreviewKind !== "document") {
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

    async function startGenericStageAgent(stage, label, acceptsInput = true) {
      if (currentWorkflowStage !== stage) {
        return;
      }
      const endpoint = acceptsInput
        ? `/api/agents/${stage}/start-interactive`
        : `/api/agents/${stage}/start`;
      await runStageAgent(stage, endpoint, label, acceptsInput === false, acceptsInput);
    }

    async function restartGenericStageAgent(stage, label, acceptsInput = true) {
      const runState = genericStageRun(stage);
      if (currentWorkflowStage === stage && !runState.started) {
        return;
      }
      await runStageAgent(
        stage,
        `/api/agents/${stage}/restart`,
        label,
        true,
        acceptsInput,
      );
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

    function openStageDocument(stage, path) {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      window.open(contextUrl(path), "_blank", "noopener");
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

    async function sendTerminalKey(key) {
      if (!selectedSessionAcceptsInput()) {
        return;
      }
      const response = await fetch(contextUrl("/api/sessions/key"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ error: "send failed" }));
        appendOutput(`${payload.error || "send failed"}\\n`, "error");
      }
    }

    function terminalKeyForInputEvent(event) {
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
      if (event.key === "Escape") return "escape";
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
      if (stageId === "implementation-plan") {
        openWorkflowStageMenu(
          implementationPlanMenu,
          implementationPlanStage,
          wasCurrentStage,
        );
        return;
      }
      if (stageId === "code") {
        openWorkflowStageMenu(codeMenu, codeStage, wasCurrentStage);
        return;
      }
      if (stageId === "test-plan") {
        openWorkflowStageMenu(testPlanMenu, testPlanStage, wasCurrentStage);
        return;
      }
      if (stageId === "validate") {
        openWorkflowStageMenu(validateMenu, validateStage, wasCurrentStage);
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

    function openWorkflowStageMenu(menu, stageNode, wasCurrentStage) {
      if (wasCurrentStage) {
        toggleStageMenu(menu, stageNode);
      } else {
        menu.hidden = false;
        positionStageMenu(menu, stageNode);
      }
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
    workItemTitle.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        applyWorkItemSelection();
      }
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
    startImplementationPlan.addEventListener("click", () => {
      startGenericStageAgent(
        "implementation-plan",
        "$ electroboy implementation-plan",
        true,
      );
    });
    restartImplementationPlan.addEventListener("click", () => {
      restartGenericStageAgent(
        "implementation-plan",
        "$ restart implementation planning",
        true,
      );
    });
    approveImplementationPlan.addEventListener("click", () => {
      approveGenericStage("implementation-plan", "implementation plan");
    });
    skipImplementationPlanApproval.addEventListener("click", () => {
      skipGenericStageApproval("implementation-plan", "Implementation plan");
    });
    openImplementationPlan.addEventListener("click", () => {
      openStageDocument("implementation-plan", "/artifacts/implementation-plan");
    });
    startAutomaticCode.addEventListener("click", () => {
      startGenericStageAgent("code", "$ electroboy code", false);
    });
    startInteractiveCode.addEventListener("click", () => {
      startGenericStageAgent("code", "$ electroboy code --interactive", true);
    });
    stopCode.addEventListener("click", () => stopGenericStageAgent("code", "code"));
    approveCode.addEventListener("click", () => approveGenericStage("code", "code"));
    skipCodeApproval.addEventListener("click", () => {
      skipGenericStageApproval("code", "Code");
    });
    restartCode.addEventListener("click", () => {
      restartGenericStageAgent("code", "$ restart code", false);
    });
    openImplementationReport.addEventListener("click", () => {
      openStageDocument("code", "/artifacts/implementation-report");
    });
    startTestPlan.addEventListener("click", () => {
      startGenericStageAgent("test-plan", "$ electroboy test-plan", true);
    });
    restartTestPlan.addEventListener("click", () => {
      restartGenericStageAgent("test-plan", "$ restart test planning", true);
    });
    approveTestPlan.addEventListener("click", () => {
      approveGenericStage("test-plan", "test plan");
    });
    skipTestPlanApproval.addEventListener("click", () => {
      skipGenericStageApproval("test-plan", "Test plan");
    });
    openTestPlan.addEventListener("click", () => {
      openStageDocument("test-plan", "/artifacts/test-plan");
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
    restartValidate.addEventListener("click", () => {
      restartGenericStageAgent("validate", "$ restart validation", false);
    });
    openValidationReport.addEventListener("click", () => {
      openStageDocument("validate", "/artifacts/validation-report");
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
    decreaseTerminalFont.addEventListener("click", () => changeTerminalFontSize(-1));
    increaseTerminalFont.addEventListener("click", () => changeTerminalFontSize(1));
    decreaseDocumentZoom.addEventListener(
      "click",
      () => changeDocumentZoom(-DOCUMENT_ZOOM_STEP),
    );
    increaseDocumentZoom.addEventListener(
      "click",
      () => changeDocumentZoom(DOCUMENT_ZOOM_STEP),
    );
    popoutAgentPane.addEventListener("click", () => popOutPane("agent"));
    popoutArtifactPane.addEventListener("click", () => popOutPane("artifact"));
    popoutProgressPane.addEventListener("click", () => popOutPane("progress"));
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

    async function initialize() {
      applyStageDescriptions();
      applyStoredPaneSizes();
      applyStoredProgressPaneSize();
      applyStoredArtifactPaneSize();
      applyStoredWorkbenchPaneSize();
      applySidePaneVisibility();
      restoreScratchPad();
      applyTerminalFontSize();
      applyDocumentZoom();
      initializeTerminal();
      await checkConnection();
      await restoreContext();
    }

    initialize().catch(() => {});
  </script>
</body>
</html>
"""


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
      font-weight: 750;
      text-transform: uppercase;
    }

    .pane-toolbar button,
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

    .input-actions select {
      min-width: 150px;
      cursor: pointer;
    }

    .pane-actions,
    .artifact-zoom-controls {
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
      height: 100%;
      padding: 10px 12px;
    }

    .artifact-frame {
      background: #f7f8fb;
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
      grid-template-columns: auto minmax(160px, 1fr) auto auto;
      align-items: end;
      gap: 8px;
      border-top: 1px solid var(--border);
      background: #151b29;
      padding: 8px;
    }

    .input-font-controls {
      display: flex;
      gap: 6px;
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
        <button id="dockPane" type="button">Dock</button>
      </div>
    </header>
    <section class="pane-body">
      <div id="terminalHost" class="terminal-host" hidden></div>
      <iframe
        id="artifactFrame"
        class="artifact-frame"
        title="Rendered artifact preview"
        sandbox="allow-scripts allow-popups"
        hidden
      ></iframe>
      <textarea id="scratchPad" class="scratch-pad" spellcheck="false" hidden></textarea>
      <pre id="statusOutput" class="status-output" hidden></pre>
      <div id="inputLayout" class="input-layout" hidden>
        <textarea id="agentInput" class="input-text" spellcheck="false"></textarea>
        <div class="input-actions">
          <div class="input-font-controls" aria-label="UI font size">
            <button
              id="decreasePaneFont"
              type="button"
              title="Decrease font size"
              aria-label="Decrease font size"
            >A-</button>
            <button
              id="increasePaneFont"
              type="button"
              title="Increase font size"
              aria-label="Increase font size"
            >A+</button>
          </div>
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
    const TERMINAL_FONT_STORAGE_KEY = "electroboy.terminalFontSize";
    const DEFAULT_FONT_SIZE = 15;
    const MIN_FONT_SIZE = 11;
    const MAX_FONT_SIZE = 24;
    let fontSize = storedFontSize();
    const MIN_ARTIFACT_ZOOM = 70;
    const MAX_ARTIFACT_ZOOM = 180;
    const ARTIFACT_ZOOM_STEP = 10;
    let artifactZoom = clampArtifactZoom(Number(params.get("document_zoom") || "100"));
    const scratchKey = "electroboy.scratchPad";
    const paneTitle = document.getElementById("paneTitle");
    const dockPane = document.getElementById("dockPane");
    const artifactZoomControls = document.getElementById("artifactZoomControls");
    const decreaseArtifactZoom = document.getElementById("decreaseArtifactZoom");
    const artifactZoomLevel = document.getElementById("artifactZoomLevel");
    const increaseArtifactZoom = document.getElementById("increaseArtifactZoom");
    const terminalHost = document.getElementById("terminalHost");
    const artifactFrame = document.getElementById("artifactFrame");
    const scratchPad = document.getElementById("scratchPad");
    const statusOutput = document.getElementById("statusOutput");
    const inputLayout = document.getElementById("inputLayout");
    const agentInput = document.getElementById("agentInput");
    const decreasePaneFont = document.getElementById("decreasePaneFont");
    const increasePaneFont = document.getElementById("increasePaneFont");
    const sessionSwitcher = document.getElementById("sessionSwitcher");
    const sendAgentInput = document.getElementById("sendAgentInput");
    const interruptAgent = document.getElementById("interruptAgent");
    let agentSessions = [];
    let terminal = null;
    let terminalFit = null;
    let eventSource = null;
    let artifactEventSource = null;
    let artifactVersion = 0;
    let statusTimer = null;

    applyFontSize();

    function storedFontSize() {
      const requested = Number(params.get("font_size") || "");
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

    function clampFontSize(value) {
      return Math.max(MIN_FONT_SIZE, Math.min(MAX_FONT_SIZE, Math.round(value)));
    }

    function saveFontSize() {
      try {
        window.localStorage.setItem(TERMINAL_FONT_STORAGE_KEY, String(fontSize));
      } catch (error) {
        return;
      }
    }

    function applyFontSize() {
      document.documentElement.style.setProperty("--font-size", `${fontSize}px`);
      if (terminal) {
        terminal.options.fontSize = fontSize;
        window.requestAnimationFrame(fitTerminal);
      }
      decreasePaneFont.disabled = fontSize <= MIN_FONT_SIZE;
      increasePaneFont.disabled = fontSize >= MAX_FONT_SIZE;
    }

    function changeFontSize(delta) {
      fontSize = clampFontSize(fontSize + delta);
      saveFontSize();
      applyFontSize();
    }

    function titleForPane(kind) {
      if (kind === "agent") return "Agent output";
      if (kind === "artifact") {
        if (artifactKind === "document" && artifactDocumentTitle) {
          return artifactDocumentTitle;
        }
        return "Artifact preview";
      }
      if (kind === "progress") return "Progress";
      if (kind === "scratch") return "Scratch pad";
      if (kind === "status") return "Project status";
      if (kind === "input") return "AI agent input";
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
      refreshArtifact();
    }

    function terminalOptions() {
      return {
        allowProposedApi: false,
        convertEol: true,
        cursorBlink: false,
        disableStdin: true,
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

    function showTerminal() {
      terminalHost.hidden = false;
      terminal = new window.Terminal(terminalOptions());
      if (window.FitAddon && window.FitAddon.FitAddon) {
        terminalFit = new window.FitAddon.FitAddon();
        terminal.loadAddon(terminalFit);
      }
      terminal.open(terminalHost);
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
      return "";
    }

    function refreshArtifact() {
      artifactVersion += 1;
      artifactFrame.src = artifactUrl();
    }

    function connectArtifactStream() {
      artifactFrame.hidden = false;
      artifactZoomControls.hidden = false;
      applyArtifactZoom();
      refreshArtifact();
      if (!contextId || artifactKind !== "requirements") {
        return;
      }
      artifactEventSource = new EventSource(
        contextUrl("/api/artifacts/events?artifact=requirements"),
      );
      artifactEventSource.addEventListener("artifact-event", refreshArtifact);
      artifactEventSource.onerror = () => {};
    }

    function showScratchPad() {
      scratchPad.hidden = false;
      try {
        scratchPad.value = window.localStorage.getItem(scratchKey) || "";
      } catch (error) {
        scratchPad.value = "";
      }
      scratchPad.addEventListener("input", () => {
        try {
          window.localStorage.setItem(scratchKey, scratchPad.value);
        } catch (error) {
          return;
        }
      });
      scratchPad.focus();
    }

    async function refreshStatus() {
      if (!contextId) {
        statusOutput.textContent = "no active project\n";
        return;
      }
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

    async function sendTerminalKey(key) {
      await fetch(contextUrl("/api/sessions/key"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key }),
      });
    }

    function terminalKeyForInputEvent(event) {
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
      if (event.key === "Escape") return "escape";
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
    decreasePaneFont.addEventListener("click", () => changeFontSize(-1));
    increasePaneFont.addEventListener("click", () => changeFontSize(1));
    sessionSwitcher.addEventListener("change", () => {
      selectAgentSession(sessionSwitcher.value);
    });
    sendAgentInput.addEventListener("click", sendMessage);
    interruptAgent.addEventListener("click", interruptAgentSession);
    agentInput.addEventListener("keydown", (event) => {
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
    if (PANE_KIND === "agent") connectAgentStream();
    else if (PANE_KIND === "progress") connectProgressStream();
    else if (PANE_KIND === "artifact") connectArtifactStream();
    else if (PANE_KIND === "scratch") showScratchPad();
    else if (PANE_KIND === "status") showStatus();
    else if (PANE_KIND === "input") showInput();

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
            self._require_no_active_agent_locked(context)
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
            self._require_no_active_agent_locked(context)
        registry = _load_work_item_registry(project_root)
        feature = _feature_by_slug(registry, slug)
        if feature is None:
            raise AgentSessionError("unknown feature")
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
            self._require_no_active_agent_locked(context)
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
            self._require_no_active_agent_locked(context)
        registry = _load_work_item_registry(project_root)
        bug = _bug_by_slug(registry, slug)
        if bug is None:
            raise AgentSessionError("unknown bug")
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
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = workflow_stage
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
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
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = _visible_workflow_stage(manifest.active_stage)
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
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
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = meta_context["workflow_stage"]
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
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
            context.documentation_session = None
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
            if target_path:
                target_path = _ensure_document_target(project_root, target_path)
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

    def send_selected_session_key(self, context_id: str, key: str) -> None:
        session = self.selected_session(context_id)
        if session is None:
            raise AgentSessionError("no agent session is selected")
        if not session.interactive:
            raise AgentSessionError(f"{session.label} does not accept input")
        session.send_key(key)

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
            for stage, stage_session in list(context.stage_sessions.items()):
                if stage_session is session:
                    context.stage_sessions.pop(stage, None)
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

    def send_key(self, key: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        if self._master_fd is None:
            raise AgentSessionError(f"{self.label} input is not available")
        try:
            os.write(self._master_fd, _terminal_input_for_key(key).encode("utf-8"))
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
        "stage_runs": _generic_stage_run_payload(context, active_root),
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
        "work_items": _work_item_payload(active_root) if active_root else _empty_work_item_payload(),
    }


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
    if stage == "implementation-plan" and active_project_root:
        return [
            "Start",
            "Restart",
            "Approve",
            "Skip approval",
            "Open implementation plan",
        ]
    if stage == "code" and active_project_root:
        return [
            "Start automatic",
            "Start interactive",
            "Stop",
            "Approve",
            "Skip approval",
            "Restart",
            "Open implementation report",
        ]
    if stage == "test-plan" and active_project_root:
        return [
            "Start",
            "Restart",
            "Approve",
            "Skip approval",
            "Open test plan",
        ]
    if stage == "validate" and active_project_root:
        return [
            "Start automatic",
            "Start interactive",
            "Stop",
            "Approve",
            "Skip approval",
            "Restart",
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
    return markdown_document_html(
        project_root,
        "docs/requirements.md",
        "Requirements",
        "Requirements document does not exist yet.",
        embedded=embedded,
        zoom_percent=zoom_percent,
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


def stage_document_html(
    project_root: Path | str,
    stage: str,
) -> tuple[str, HTTPStatus]:
    config = _generic_stage_config(stage)
    title = str(config["artifact_title"])
    return markdown_document_html(
        project_root,
        str(config["artifact_path"]),
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
      max-width: 880px;
      margin: 0 auto;
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
        document_path.write_text("", encoding="utf-8")
    if not document_path.is_file():
        raise StateError("document path must refer to a file")
    return normalized_path


def _document_target_path(project_root: Path | str, relative_path: str) -> tuple[str, Path]:
    project_root = Path(project_root).expanduser().resolve()
    normalized_path = _normalize_document_target_path(relative_path)
    document_path = (project_root / normalized_path).resolve()
    try:
        document_path.relative_to(project_root)
    except ValueError as error:
        raise StateError("document path cannot escape the project") from error
    return normalized_path, document_path


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
    rendered = str(markdown_library.markdown(text, extensions=["extra", "sane_lists"]))
    return _promote_mermaid_blocks(rendered)


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
      height: auto;
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
      const zoomLevel = document.getElementById("zoomLevel");
      const zoomOut = document.getElementById("zoomOut");
      const zoomReset = document.getElementById("zoomReset");
      const zoomIn = document.getElementById("zoomIn");

      function readSvgDimensions(svg) {
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
        const availableWidth = Math.max(320, viewportRect.width - 48);
        const availableHeight = Math.max(220, viewportRect.height - 48);
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
      initializeDiagramPopup("Mermaid diagram");
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


def _terminal_input_for_key(key: str) -> str:
    if re.fullmatch(r"[0-9]", key):
        return key
    keys = {
        "enter": "\r",
        "escape": "\x1b",
        "tab": "\t",
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
            if path == "/api/progress/events":
                self._send_progress_events(parsed.query)
                return
            if path == "/api/artifacts/events":
                self._send_artifact_events(parsed.query)
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
            if path == "/api/sessions/select":
                self._select_session(parsed.query)
                return
            if path == "/api/sessions/message":
                self._send_selected_session_message(parsed.query)
                return
            if path == "/api/sessions/key":
                self._send_selected_session_key(parsed.query)
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

        def _send_artifact_events(self, query: str) -> None:
            params = parse_qs(query)
            artifact = str((params.get("artifact") or [""])[0]).strip()
            if artifact != "requirements":
                self._send_json(
                    {"error": "unknown artifact"},
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            try:
                context_id = self._context_id(query)
                project_root = state.requirements_document_root(context_id)
            except (AgentSessionError, StateError) as error:
                self._send_json(
                    {"error": str(error)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._stream_artifact_events(
                artifact,
                project_root / "docs" / "requirements.md",
            )

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
