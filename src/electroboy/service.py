"""Local browser service for ElectroBoy."""

from __future__ import annotations

import errno
import fcntl
import json
import os
import pty
import re
import shlex
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from .artifacts import ArtifactManager
from .state_store import StateError, StateStore


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

_CONTROL_CHARS_TO_DROP = frozenset(
    chr(code)
    for code in [*range(0x00, 0x08), *range(0x0B, 0x0D), *range(0x0E, 0x20), 0x7F]
)

WORKFLOW_STAGES = [
    "project",
    "requirements",
    "requirements-approve",
    "design",
    "design-review",
    "design-approve",
    "implementation-plan",
    "plan-approve",
    "code",
    "test-plan",
    "test-plan-approve",
    "validate",
    "validation-approve",
    "document",
    "code-approve",
]

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
    }

    body {
      overflow: hidden;
    }

    .shell {
      display: grid;
      grid-template-rows: 230px minmax(0, 1fr);
      height: 100vh;
      min-height: 560px;
    }

    .workflow-pane {
      position: relative;
      padding: 20px 24px 16px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
      overflow-x: auto;
      overflow-y: visible;
    }

    .connection {
      position: absolute;
      right: 24px;
      top: 16px;
      color: var(--active);
      font-size: 13px;
      font-weight: 650;
    }

    .stage-graph {
      position: relative;
      display: grid;
      grid-template-columns: repeat(15, minmax(126px, 1fr));
      gap: 12px;
      min-width: 1880px;
      padding-top: 54px;
    }

    .stage-graph::before {
      position: absolute;
      top: 77px;
      left: 56px;
      right: 56px;
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
      height: 48px;
      padding: 0 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--disabled);
      color: var(--muted);
      font-size: 13px;
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
      border-color: var(--active);
      background: var(--active-soft);
      color: #064e49;
    }

    .stage-node.complete {
      border-color: #9fb4c9;
      background: #edf7ff;
      color: #27445e;
    }

    .stage-node.disabled {
      cursor: default;
    }

    .stage-menu {
      position: absolute;
      z-index: 3;
      top: 128px;
      left: 24px;
      width: 192px;
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
      height: 38px;
      border: 1px solid transparent;
      border-radius: 6px;
      background: var(--active);
      color: white;
      cursor: pointer;
      font-family: inherit;
      font-size: 14px;
      font-weight: 700;
    }

    .stage-menu button + button {
      margin-top: 6px;
    }

    .stage-menu button:disabled {
      cursor: default;
      opacity: 0.65;
    }

    .project-panel {
      position: absolute;
      z-index: 2;
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
      font-size: 13px;
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

    .file-browser {
      position: fixed;
      z-index: 20;
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
      display: grid;
      grid-template-rows: minmax(0, 1fr) 148px;
      min-height: 0;
      background: var(--terminal);
    }

    .agent-output {
      min-height: 0;
      overflow: auto;
      padding: 0;
      color: var(--terminal-text);
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 13px;
      line-height: 1.45;
      white-space: pre-wrap;
    }

    .agent-output .xterm {
      height: 100%;
      padding: 10px 12px;
    }

    .agent-output .xterm-viewport {
      background: var(--terminal);
    }

    .agent-output .system {
      color: #8bd8ca;
    }

    .agent-output .error {
      color: #ffb4a9;
    }

    .input-pane {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      border-top: 1px solid #2a3142;
      background: #151b29;
      padding: 12px;
    }

    .agent-input {
      display: block;
      width: 100%;
      height: 100%;
      resize: none;
      border: 1px solid #364156;
      border-radius: 8px;
      background: #0f1420;
      color: var(--terminal-text);
      padding: 12px;
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 13px;
      line-height: 1.45;
    }

    .agent-input:disabled {
      color: #7c879a;
      background: #121827;
      cursor: default;
    }

    .agent-interrupt {
      width: 104px;
      border: 1px solid #73342f;
      border-radius: 8px;
      background: #3b1718;
      color: #ffd9d5;
      cursor: pointer;
      font-family: inherit;
      font-size: 13px;
      font-weight: 750;
    }

    .agent-interrupt:disabled {
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

      .connection {
        right: 16px;
      }

      .stage-graph {
        grid-template-columns: repeat(15, minmax(112px, 1fr));
        min-width: 1840px;
      }

      .stage-menu {
        left: 16px;
        top: 120px;
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
    }
  </style>
</head>
<body>
  <main class="shell">
    <section class="workflow-pane" aria-label="Project workflow">
      <div id="connection" class="connection"></div>
      <div class="stage-graph" aria-label="Project stages">
        <button class="stage-node active" type="button" data-stage="project">
          project
        </button>
        <button class="stage-node disabled" type="button" data-stage="requirements" disabled>
          requirements
        </button>
        <div class="stage-node disabled" aria-disabled="true">
          requirements-approve
        </div>
        <div class="stage-node disabled" aria-disabled="true">design</div>
        <div class="stage-node disabled" aria-disabled="true">design-review</div>
        <div class="stage-node disabled" aria-disabled="true">design-approve</div>
        <div class="stage-node disabled" aria-disabled="true">
          implementation-plan
        </div>
        <div class="stage-node disabled" aria-disabled="true">plan-approve</div>
        <div class="stage-node disabled" aria-disabled="true">code</div>
        <div class="stage-node disabled" aria-disabled="true">test-plan</div>
        <div class="stage-node disabled" aria-disabled="true">test-plan-approve</div>
        <div class="stage-node disabled" aria-disabled="true">validate</div>
        <div class="stage-node disabled" aria-disabled="true">validation-approve</div>
        <div class="stage-node disabled" aria-disabled="true">document</div>
        <div class="stage-node disabled" aria-disabled="true">code-approve</div>
      </div>
      <div id="projectMenu" class="stage-menu" hidden>
        <button id="openProject" type="button">Open</button>
        <button id="newProject" type="button">Create</button>
        <button id="deactivateProject" type="button" disabled>Deactivate</button>
      </div>
      <div id="requirementsMenu" class="stage-menu" hidden>
        <button id="startRequirements" type="button">Start</button>
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
    <section class="agent-pane" aria-label="Requirements agent">
      <div id="agentOutput" class="agent-output" aria-live="polite"></div>
      <div class="input-pane">
        <textarea
          id="agentInput"
          class="agent-input"
          spellcheck="false"
          disabled
          aria-label="Requirements agent input"
        ></textarea>
        <button
          id="interruptAgent"
          class="agent-interrupt"
          type="button"
          disabled
        >
          Interrupt
        </button>
      </div>
    </section>
  </main>
  <script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js"></script>
  <script>
    const connection = document.getElementById("connection");
    const projectStage = document.querySelector("[data-stage='project']");
    const requirementsStage = document.querySelector("[data-stage='requirements']");
    const projectMenu = document.getElementById("projectMenu");
    const requirementsMenu = document.getElementById("requirementsMenu");
    const openProject = document.getElementById("openProject");
    const newProject = document.getElementById("newProject");
    const deactivateProject = document.getElementById("deactivateProject");
    const startRequirements = document.getElementById("startRequirements");
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
    const agentOutput = document.getElementById("agentOutput");
    const agentInput = document.getElementById("agentInput");
    const interruptAgent = document.getElementById("interruptAgent");
    let eventSource = null;
    let terminal = null;
    let terminalFit = null;
    let resizeTimer = null;
    let requirementsRunning = false;
    let contextId = "";
    let projectMode = "open";
    let serviceRoot = "";
    let activeProjectRoot = "";
    let currentBrowsePath = "";
    let currentBrowseParent = "";

    function initializeTerminal() {
      if (!window.Terminal) {
        appendPlainOutput("terminal renderer unavailable; using plain text\\n", "error");
        return;
      }
      terminal = new window.Terminal({
        allowProposedApi: false,
        convertEol: true,
        cursorBlink: false,
        disableStdin: true,
        fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace',
        fontSize: 13,
        scrollback: 10000,
        theme: {
          background: "#10141f",
          foreground: "#e7edf7",
          cursor: "#e7edf7",
          selectionBackground: "#2b6173",
        },
      });
      if (window.FitAddon && window.FitAddon.FitAddon) {
        terminalFit = new window.FitAddon.FitAddon();
        terminal.loadAddon(terminalFit);
      }
      terminal.open(agentOutput);
      fitTerminal();
      window.addEventListener("resize", fitTerminal);
    }

    function fitTerminal() {
      if (!terminal) {
        return;
      }
      if (terminalFit) {
        try {
          terminalFit.fit();
        } catch (error) {
          return;
        }
      }
      queueTerminalResize();
    }

    function queueTerminalResize() {
      if (!requirementsRunning || !contextId || !terminal) {
        return;
      }
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(sendTerminalResize, 120);
    }

    async function sendTerminalResize() {
      if (!requirementsRunning || !contextId || !terminal) {
        return;
      }
      await fetch(contextUrl("/api/agents/requirements/resize"), {
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
      connection.textContent = activeProjectRoot
        ? `connected · ${activeProjectRoot}`
        : "connected";
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

    async function createContext() {
      const response = await fetch("/api/contexts", { method: "POST" });
      if (!response.ok) {
        projectStatus.textContent = "could not create browser context";
        return;
      }
      const payload = await response.json();
      contextId = payload.context_id || "";
      updateProjectState(payload);
    }

    function updateProjectState(payload) {
      serviceRoot = payload.service_root || "";
      activeProjectRoot = payload.active_project_root || "";
      if (!projectPath.value) {
        projectPath.value = activeProjectRoot || serviceRoot;
      }
      setConnected();
      projectStage.classList.toggle("complete", Boolean(activeProjectRoot));
      projectStage.classList.toggle("active", !activeProjectRoot);
      requirementsStage.disabled = !activeProjectRoot;
      requirementsStage.classList.toggle("disabled", !activeProjectRoot);
      requirementsStage.classList.toggle("active", Boolean(activeProjectRoot));
      deactivateProject.disabled = !activeProjectRoot;
      projectStatus.textContent = activeProjectRoot
        ? `active: ${activeProjectRoot}`
        : "";
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

    async function browseDirectory(path = projectPath.value || ".") {
      fileBrowser.hidden = false;
      browserPath.value = path;
      directoryList.replaceChildren();
      const response = await fetch(
        `/api/files/browse?path=${encodeURIComponent(path)}`,
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
        directoryList.appendChild(directoryButton(entry.name, entry.path));
      }
    }

    function directoryButton(label, path) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "directory-entry";
      button.textContent = label;
      button.title = path;
      button.addEventListener("click", () => browseDirectory(path));
      return button;
    }

    function showProjectPanel(mode) {
      projectMode = mode;
      projectMenu.hidden = true;
      requirementsMenu.hidden = true;
      projectPanel.hidden = false;
      activateProject.textContent = mode === "new" ? "Create" : "Activate";
      projectStatus.textContent = activeProjectRoot ? `active: ${activeProjectRoot}` : "";
      projectPath.focus();
    }

    function selectCurrentDirectory() {
      if (!currentBrowsePath) {
        return;
      }
      projectPath.value = currentBrowsePath;
      projectStatus.textContent = `selected: ${currentBrowsePath}`;
      fileBrowser.hidden = true;
      projectPath.focus();
    }

    async function applyProjectSelection() {
      const endpoint = projectMode === "new" ? "/api/project/new" : "/api/project/open";
      const selectedPath = projectPath.value.trim();
      if (!selectedPath) {
        projectStatus.textContent = "choose a project directory first";
        appendOutput("choose a project directory first\\n", "error");
        return;
      }
      activateProject.disabled = true;
      projectStatus.textContent =
        projectMode === "new" ? `creating: ${selectedPath}` : `activating: ${selectedPath}`;
      let response;
      try {
        response = await fetch(contextUrl(endpoint), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: selectedPath }),
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
      projectPath.value = activeProjectRoot;
      fileBrowser.hidden = true;
      projectPanel.hidden = true;
      projectMenu.hidden = true;
      projectStatus.textContent = `active: ${activeProjectRoot}`;
      appendOutput(`${payload.status}: ${activeProjectRoot}\\n`, "system");
      await refreshProject();
      activateProject.disabled = false;
    }

    async function deactivateActiveProject() {
      if (!activeProjectRoot) {
        return;
      }
      const previousProject = activeProjectRoot;
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
      activeProjectRoot = "";
      projectPath.value = serviceRoot;
      projectMenu.hidden = true;
      requirementsMenu.hidden = true;
      agentInput.disabled = true;
      interruptAgent.disabled = true;
      startRequirements.disabled = false;
      requirementsRunning = false;
      appendOutput(`deactivated: ${previousProject}\\n`, "system");
      updateProjectState(payload);
    }

    function connectAgentEvents() {
      if (eventSource) {
        eventSource.close();
      }
      eventSource = new EventSource(contextUrl("/api/agents/requirements/events"));
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
          agentInput.disabled = true;
          interruptAgent.disabled = true;
          startRequirements.disabled = false;
          requirementsRunning = false;
        }
      });
      eventSource.onerror = () => {};
    }

    async function startRequirementsAgent() {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\\n", "error");
        return;
      }
      requirementsMenu.hidden = true;
      startRequirements.disabled = true;
      requirementsRunning = true;
      agentInput.disabled = false;
      interruptAgent.disabled = false;
      agentInput.focus();
      appendOutput("$ electroboy requirements\\n", "system");
      const response = await fetch(contextUrl("/api/agents/requirements/start"), {
        method: "POST",
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ error: "start failed" }));
        appendOutput(`${payload.error || "start failed"}\\n`, "error");
        agentInput.disabled = true;
        interruptAgent.disabled = true;
        startRequirements.disabled = false;
        requirementsRunning = false;
        return;
      }
      connectAgentEvents();
      sendTerminalResize();
    }

    async function sendMessage() {
      const message = agentInput.value;
      if (!message.trim()) {
        return;
      }
      agentInput.value = "";
      const response = await fetch(contextUrl("/api/agents/requirements/message"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ error: "send failed" }));
        appendOutput(`${payload.error || "send failed"}\\n`, "error");
      }
    }

    async function interruptRequirementsAgent() {
      if (!requirementsRunning) {
        return;
      }
      const response = await fetch(contextUrl("/api/agents/requirements/interrupt"), {
        method: "POST",
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ error: "interrupt failed" }));
        appendOutput(`${payload.error || "interrupt failed"}\\n`, "error");
      }
    }

    requirementsStage.addEventListener("click", () => {
      if (requirementsStage.disabled) {
        return;
      }
      projectMenu.hidden = true;
      requirementsMenu.hidden = !requirementsMenu.hidden;
    });

    projectStage.addEventListener("click", () => {
      requirementsMenu.hidden = true;
      projectMenu.hidden = !projectMenu.hidden;
    });

    openProject.addEventListener("click", () => showProjectPanel("open"));
    newProject.addEventListener("click", () => showProjectPanel("new"));
    deactivateProject.addEventListener("click", deactivateActiveProject);
    browseProject.addEventListener("click", () => {
      browseDirectory(projectPath.value || activeProjectRoot || serviceRoot || ".");
    });
    activateProject.addEventListener("click", applyProjectSelection);
    upDirectory.addEventListener("click", () => {
      if (currentBrowseParent) {
        browseDirectory(currentBrowseParent);
      }
    });
    selectDirectory.addEventListener("click", selectCurrentDirectory);
    closeBrowser.addEventListener("click", () => {
      fileBrowser.hidden = true;
      projectPath.focus();
    });

    startRequirements.addEventListener("click", startRequirementsAgent);
    interruptAgent.addEventListener("click", interruptRequirementsAgent);

    agentInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && event.shiftKey) {
        event.preventDefault();
        sendMessage();
      }
    });

    async function initialize() {
      initializeTerminal();
      await checkConnection();
      await createContext();
    }

    initialize().catch(() => {});
  </script>
</body>
</html>
"""


@dataclass
class BrowserContext:
    context_id: str
    active_project_root: Path | None = None
    requirements_session: AgentSession | None = None


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

    def open_project(self, context_id: str, path: str) -> dict[str, object]:
        project_root = _existing_project_root(path)
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
            context.active_project_root = project_root
            context.requirements_session = None
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
            context.active_project_root = project_root
            context.requirements_session = None
        return {
            **project_payload(self.root, context, project_root),
            "status": "created",
            "run_id": manifest.run_id,
        }

    def deactivate_project(self, context_id: str) -> dict[str, object]:
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
            context.active_project_root = None
            context.requirements_session = None
        return {
            **project_payload(self.root, context, None),
            "status": "deactivated",
        }

    def start_requirements_agent(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if (
                context.requirements_session is not None
                and context.requirements_session.is_active()
            ):
                return context.requirements_session, False
            session = AgentSession(
                command=_requirements_command(project_root),
                cwd=project_root,
            )
            context.requirements_session = session
        session.start()
        return session, True

    def current_requirements_session(self, context_id: str) -> AgentSession | None:
        with self.lock:
            context = self._context_locked(context_id)
            return context.requirements_session

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

    def interrupt_requirements_agent(self, context_id: str) -> None:
        with self.lock:
            context = self._context_locked(context_id)
            session = context.requirements_session
        if session is None:
            raise AgentSessionError("requirements agent has not been started")
        session.interrupt()

    def _context_locked(self, context_id: str) -> BrowserContext:
        context_id = context_id.strip()
        if not context_id:
            raise StateError("missing browser context; refresh the page")
        context = self.contexts.get(context_id)
        if context is None:
            raise StateError("unknown browser context; refresh the page")
        return context

    def _require_no_active_agent_locked(self, context: BrowserContext) -> None:
        if (
            context.requirements_session is not None
            and context.requirements_session.is_active()
        ):
            raise AgentSessionError(
                "cannot change projects while this context's requirements "
                "agent is running"
            )


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
    ) -> None:
        self.command = command
        self.cwd = Path(cwd).resolve()
        self.columns = columns
        self.rows = rows
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

    def start(self) -> None:
        if self.process is not None:
            return
        master_fd, slave_fd = pty.openpty()
        env = _agent_process_env()
        _disable_terminal_echo(slave_fd)
        _set_terminal_size(slave_fd, self.columns, self.rows)
        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=env,
                close_fds=True,
                start_new_session=True,
            )
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
            raise AgentSessionError("requirements agent is not running")
        if self._master_fd is None:
            raise AgentSessionError("requirements agent input is not available")
        text = _terminal_input_for_message(message)
        try:
            os.write(self._master_fd, text.encode("utf-8"))
        except OSError as error:
            raise AgentSessionError(f"could not write to requirements agent: {error}")

    def interrupt(self) -> None:
        if not self.is_active():
            raise AgentSessionError("requirements agent is not running")
        process = self.process
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGINT)
            except ProcessLookupError:
                return
            except OSError:
                pass
        fd = self._master_fd
        if fd is not None:
            try:
                os.write(fd, b"\x03")
            except OSError as error:
                raise AgentSessionError(
                    f"could not interrupt requirements agent: {error}"
                )

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


class ElectroBoyHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


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
    )


def run_service(
    root: Path | str,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> int:
    server = create_server(root, host=host, port=port)
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
        return 130
    finally:
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
    return {
        "context_id": context.context_id,
        "service_root": str(service_root),
        "active_project_root": str(active_root) if active_root else None,
        "activate_command": (
            f"source {active_root / '.electroboy' / 'bin' / 'activate'}"
            if active_root
            else None
        ),
    }


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


def _resolve_project_path(path: str) -> Path:
    path = path.strip()
    if not path:
        raise StateError("project path is required")
    return Path(path).expanduser().resolve()


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
        return ["Start"]
    return []


def _requirements_command(root: Path) -> list[str]:
    activate_script = root / ".electroboy" / "bin" / "activate"
    if activate_script.exists():
        return [
            "/bin/sh",
            "-c",
            f". {shlex.quote(str(activate_script))} >/dev/null && "
            "electroboy requirements",
        ]
    return [
        sys.executable,
        "-m",
        "electroboy",
        "--root",
        str(root),
        "requirements",
    ]


def _terminal_input_for_message(message: str) -> str:
    text = message.replace("\r\n", "\n").replace("\r", "\n")
    text = text.rstrip("\n")
    if "\n" in text:
        return f"\x1b[200~{text}\x1b[201~\r"
    return f"{text}\r"


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
            if path == "/api/workflow":
                self._send_context_json(
                    parsed.query,
                    lambda context_id: state.workflow_payload(context_id),
                )
                return
            if path == "/api/files/browse":
                self._browse_files(parsed.query)
                return
            if path == "/api/agents/requirements/events":
                self._send_agent_events(parsed.query)
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
            if path == "/api/project/deactivate":
                self._deactivate_project(parsed.query)
                return
            if path == "/api/agents/requirements/start":
                self._start_requirements_agent(parsed.query)
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
            try:
                payload = browse_directories(path)
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

        def _deactivate_project(self, query: str) -> None:
            try:
                context_id = self._context_id(query)
                self._send_json(state.deactivate_project(context_id))
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
                    "status": "started" if started else "running",
                    "command": session.command,
                }
            )

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
