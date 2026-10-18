(function () {
  "use strict";

  let terminal = null;
  let terminalFit = null;
  let eventSource = null;
  let resizeTimer = null;
  const shellWindows = new Map();
  let shellListRequest = 0;
  let shellListScope = "";

  function shellWindowName(contextId, sessionId) {
    return `electroboy-shell-${contextId}-${sessionId}`;
  }

  function shellWindowUrl(runtime, sessionId, fontSize, contextParameters = runtime.http.contextParameters()) {
    const parameters = new URLSearchParams(contextParameters);
    parameters.set("shell_session_id", sessionId);
    parameters.set("disposable", "1");
    parameters.set("font_size", String(fontSize || 15));
    return `/pane/shell?${parameters.toString()}`;
  }

  async function refreshShellSessions(runtime) {
    const request = ++shellListRequest;
    const state = shellState(runtime);
    const select = document.getElementById("shellSessionSwitcher");
    const status = document.getElementById("shellSessionStatus");
    const contextId = state.contextId;
    const projectRoot = state.activeProjectRoot;
    if (!contextId || !projectRoot) {
      select.replaceChildren(new Option("Activate a project first", ""));
      select.disabled = true;
      delete select.dataset.sessions;
      status.textContent = "";
      return;
    }
    try {
      const response = await runtime.http.fetch(runtime.http.contextUrl("/api/shell/sessions"));
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Unable to list shells");
      const latest = shellState(runtime);
      if (request !== shellListRequest || latest.contextId !== contextId
          || latest.activeProjectRoot !== projectRoot) return;
      if (select.getAttribute("aria-expanded") === "true") return;
      const sessions = payload.sessions.filter((session) => session.status === "running");
      const selected = select.value;
      const options = [new Option(sessions.length ? "Select a shell…" : "No active shells", "")];
      for (const session of sessions) {
        options.push(new Option(
          `${session.name || session.label || "Shell"} · ${session.session_id.slice(0, 8)}`,
          session.session_id,
        ));
      }
      // Avoid rebuilding the custom picker while its user is choosing a shell.
      const signature = JSON.stringify(options.map((option) => [option.value, option.text]));
      if (select.dataset.sessions !== signature) {
        select.replaceChildren(...options);
        select.dataset.sessions = signature;
        select.value = sessions.some((session) => session.session_id === selected) ? selected : "";
      }
      select.disabled = !sessions.length;
      status.textContent = "";
      for (const [name, popup] of shellWindows) {
        if (popup.closed) shellWindows.delete(name);
      }
    } catch (error) {
      if (request !== shellListRequest || shellState(runtime).contextId !== contextId) return;
      select.disabled = true;
      status.textContent = `Unable to list shells: ${error.message}`;
    }
  }

  function focusShellSession(runtime, sessionId) {
    if (!sessionId) return;
    const state = shellState(runtime);
    const name = shellWindowName(state.contextId, sessionId);
    let popup = shellWindows.get(name);
    if (!popup || popup.closed) {
      // A stable name also finds windows opened before a main-page reload.
      popup = window.open("", name, SHELL_POPUP_FEATURES);
      if (!popup) {
        document.getElementById("shellSessionStatus").textContent = "Allow popups to open the shell window.";
        return;
      }
      if (popup.location.href === "about:blank") {
        popup.location.replace(shellWindowUrl(runtime, sessionId, state.terminalFontSize));
      }
      shellWindows.set(name, popup);
    }
    // Let the shared picker finish restoring focus before raising the window.
    window.setTimeout(() => popup.focus(), 0);
  }

  const SHELL_POPUP_FEATURES =
    "popup=yes,width=1100,height=760,menubar=no,toolbar=no,location=no,status=no,scrollbars=yes,resizable=yes";

  function shellState(runtime) {
    return runtime.getState();
  }

  function updateShellState(runtime, patch) {
    runtime.updateState(patch);
  }

  function initializeProjectShellTerminal(runtime) {
    if (terminal || !window.Terminal) {
      return;
    }
    terminal = new window.Terminal(runtime.terminals.options(false, "shell"));
    if (window.FitAddon && window.FitAddon.FitAddon) {
      terminalFit = new window.FitAddon.FitAddon();
      terminal.loadAddon(terminalFit);
    }
    terminal.onData((data) => sendProjectShellInput(runtime, data));
    terminal.open(runtime.elements.projectShellOutput);
    window.ElectroBoyTerminalBehavior.install(terminal);
    runtime.terminals.applyFontSize();
  }

  function queueProjectShellResize(runtime) {
    const state = shellState(runtime);
    if (
      !state.projectShellRunning ||
      !state.contextId ||
      !terminal ||
      runtime.elements.projectShellPane.hidden
    ) {
      return;
    }
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(
      () => sendProjectShellResize(runtime),
      120,
    );
  }

  async function sendProjectShellResize(runtime) {
    const state = shellState(runtime);
    if (!state.projectShellRunning || !state.contextId || !terminal) {
      return;
    }
    await runtime.http.fetch(runtime.http.contextUrl("/api/shell/resize"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ columns: terminal.cols, rows: terminal.rows }),
    }).catch(() => {});
  }

  function appendProjectShellOutput(runtime, text, className = "") {
    if (terminal) {
      terminal.write(
        className ? runtime.terminals.formatMessage(text, className) : text,
      );
      return;
    }
    const span = document.createElement("span");
    span.textContent = text;
    if (className) {
      span.className = className;
    }
    const output = runtime.elements.projectShellOutput;
    output.appendChild(span);
    output.scrollTop = output.scrollHeight;
  }

  function clearProjectShellOutput(runtime) {
    if (runtime.terminals.reset(terminal)) {
      return;
    }
    runtime.elements.projectShellOutput.replaceChildren();
  }

  function applyProjectShellPaneVisibility(runtime) {
    const state = shellState(runtime);
    const visible = state.projectShellPaneRequested && !runtime.layout.isPopped("shell");
    runtime.elements.projectShellPane.hidden = !visible;
    runtime.elements.shellPaneDivider.hidden = !visible;
    runtime.elements.leftOutputPane.classList.toggle("shell-visible", visible);
    if (visible) {
      runtime.layout.applyStoredShellHeight();
      initializeProjectShellTerminal(runtime);
    }
    window.requestAnimationFrame(() => runtime.terminals.fitAll());
    runtime.layout.reconcile("project-shell-visibility");
    updateProjectShellToggle(runtime);
  }

  function showProjectShellPane(runtime, show) {
    const patch = { projectShellPaneRequested: show };
    if (show) {
      patch.projectShellPaneDismissed = false;
    }
    updateShellState(runtime, patch);
    applyProjectShellPaneVisibility(runtime);
  }

  function hideProjectShellPane(runtime) {
    const state = shellState(runtime);
    updateShellState(runtime, {
      projectShellPaneDismissed: state.projectShellRunning,
      projectShellPaneRequested: false,
    });
    applyProjectShellPaneVisibility(runtime);
  }

  function syncProjectShellPane(runtime) {
    const state = shellState(runtime);
    const patch = {};
    if (!state.projectShellRunning) {
      patch.projectShellPaneDismissed = false;
      closeProjectShellEventStream();
    } else if (!state.projectShellPaneRequested) {
      closeProjectShellEventStream();
    }
    updateShellState(runtime, patch);
    applyProjectShellPaneVisibility(runtime);
    const nextState = shellState(runtime);
    if (
      nextState.projectShellRunning
      && nextState.projectShellPaneRequested
      && !eventSource
    ) {
      window.setTimeout(() => connectProjectShellEvents(runtime), 0);
    }
  }

  async function toggleProjectShellFromToolbar(runtime) {
    const state = shellState(runtime);
    if (!state.activeProjectRoot || !state.contextId) {
      return;
    }
    await startProjectShell(runtime);
  }

  function updateProjectShellToggle(runtime) {
    const start = document.getElementById("startShellSession");
    const state = shellState(runtime);
    start.disabled = !state.activeProjectRoot || !state.contextId;
    start.title = start.disabled ? "Activate a project to open a shell" : "Start a new shell window";
    const scope = JSON.stringify([state.contextId, state.activeProjectRoot]);
    if (scope !== shellListScope) {
      shellListScope = scope;
      const select = document.getElementById("shellSessionSwitcher");
      select.replaceChildren(new Option("Loading shells…", ""));
      select.disabled = true;
      delete select.dataset.sessions;
      refreshShellSessions(runtime);
    }
  }

  async function startProjectShell(runtime) {
    const state = shellState(runtime);
    if (!state.activeProjectRoot || !state.contextId) {
      runtime.notifications.appendOutput("activate a project first\n", "error");
      return;
    }
    const contextParameters = runtime.http.contextParameters();
    const stopEndpoint = runtime.http.contextUrl("/api/shell/stop");
    const popupName = `electroboy-shell-${state.contextId}-${Date.now()}-${Math.random()}`;
    const popup = window.open("", popupName, SHELL_POPUP_FEATURES);
    if (!popup) {
      runtime.notifications.appendOutput(
        "shell popup was blocked by the browser\n",
        "error",
      );
      return;
    }
    popup.document.title = "Starting ElectroBoy shell";
    popup.document.body.textContent = "Starting project shell...";
    let response;
    try {
      response = await runtime.http.fetch(
        runtime.http.contextUrl("/api/shell/start"),
        { method: "POST" },
      );
    } catch (error) {
      popup.close();
      throw error;
    }
    const payload = await response.json().catch(() => ({ error: "shell start failed" }));
    if (!response.ok) {
      popup.close();
      runtime.notifications.appendOutput(
        `${payload.error || "shell start failed"}\n`,
        "error",
      );
      return;
    }
    const sessionId = String(payload.shell_session?.session_id || "").trim();
    if (!sessionId) {
      popup.close();
      runtime.notifications.appendOutput("shell session was not created\n", "error");
      return;
    }
    if (popup.closed) {
      const stopUrl = new URL(stopEndpoint, window.location.href);
      stopUrl.searchParams.set("session_id", sessionId);
      const stopResponse = await runtime.http.fetch(stopUrl, { method: "POST" });
      const stopPayload = await stopResponse.json().catch(() => null);
      if (stopResponse.ok && stopPayload && shellState(runtime).contextId === state.contextId
          && shellState(runtime).activeProjectRoot === state.activeProjectRoot) {
        runtime.project.update(stopPayload);
      }
      return;
    }
    const latest = shellState(runtime);
    if (latest.contextId === state.contextId && latest.activeProjectRoot === state.activeProjectRoot) {
      updateShellState(runtime, {
        projectShellRunning: Boolean(payload.project_shell_running),
        projectShellPaneDismissed: true,
        projectShellPaneRequested: false,
      });
      runtime.project.update(payload);
    }
    const name = shellWindowName(state.contextId, sessionId);
    popup.name = name;
    shellWindows.set(name, popup);
    popup.location.replace(shellWindowUrl(runtime, sessionId, state.terminalFontSize, contextParameters));
    popup.focus();
    await refreshShellSessions(runtime);
  }

  function connectProjectShellEvents(runtime) {
    if (!shellState(runtime).contextId) {
      return;
    }
    closeProjectShellEventStream();
    showProjectShellPane(runtime, true);
    initializeProjectShellTerminal(runtime);
    eventSource = runtime.http.eventSource("/api/shell/events");
    eventSource.addEventListener("agent-event", (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === "output") {
        appendProjectShellOutput(runtime, payload.terminal || payload.text || "");
      } else if (payload.type === "system" || payload.type === "error") {
        appendProjectShellOutput(runtime, `${payload.text}\r\n`, payload.type);
      } else if (payload.type === "completed") {
        appendProjectShellOutput(
          runtime,
          `\r\nproject shell exited with code ${payload.returncode}\r\n`,
          "system",
        );
        updateShellState(runtime, {
          projectShellRunning: false,
          projectShellPaneDismissed: false,
        });
        closeProjectShellEventStream();
        runtime.project.refresh();
      }
    });
    eventSource.onerror = () => {};
    window.requestAnimationFrame(() => sendProjectShellResize(runtime));
  }

  function closeProjectShellEventStream() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  function disposeProjectShellTerminal(runtime) {
    if (terminal) {
      try {
        terminal.dispose();
      } catch (error) {
        // Best effort cleanup; the shell process remains attached server-side.
      }
      terminal = null;
      terminalFit = null;
    }
    runtime.elements.projectShellOutput.replaceChildren();
  }

  async function sendProjectShellInput(runtime, data) {
    const state = shellState(runtime);
    if (!state.projectShellRunning || !state.contextId || !data) {
      return;
    }
    await runtime.http.fetch(runtime.http.contextUrl("/api/shell/input"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data }),
    }).catch(() => {});
  }

  async function stopProjectShellProcess(runtime) {
    if (!shellState(runtime).contextId) {
      return;
    }
    const response = await runtime.http.fetch(
      runtime.http.contextUrl("/api/shell/stop"),
      { method: "POST" },
    );
    const payload = await response.json().catch(() => ({ error: "shell stop failed" }));
    if (!response.ok) {
      appendProjectShellOutput(
        runtime,
        `${payload.error || "shell stop failed"}\r\n`,
        "error",
      );
      return;
    }
    updateShellState(runtime, {
      projectShellRunning: false,
      projectShellPaneDismissed: false,
    });
    closeProjectShellEventStream();
    runtime.project.update(payload);
  }

  function fit() {
    if (!terminalFit) {
      return;
    }
    try {
      window.ElectroBoyTerminalBehavior.fit(terminal, terminalFit);
    } catch (error) {
      // The pane may be between layout states.
    }
  }

  function status(runtime) {
    return {
      ...shellState(runtime),
      connected: Boolean(eventSource),
    };
  }

  function mount(runtime) {
    runtime.elements.openProjectShell.addEventListener(
      "click",
      () => startProjectShell(runtime),
    );
    const menu = document.getElementById("shellSessionMenu");
    menu.addEventListener("toggle", () => {
      if (menu.open) refreshShellSessions(runtime);
    });
    document.getElementById("shellSessionSwitcher").addEventListener("change", (event) => {
      focusShellSession(runtime, event.target.value);
      // Reset so the same shell can be brought forward again.
      event.target.value = "";
    });
    document.getElementById("startShellSession").addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        await startProjectShell(runtime);
      } catch (error) {
        document.getElementById("shellSessionStatus").textContent = `Unable to start shell: ${error.message}`;
      } finally {
        updateProjectShellToggle(runtime);
      }
    });
    window.setInterval(() => {
      if (menu.open && !document.hidden) refreshShellSessions(runtime);
    }, 2000);
    runtime.elements.closeProjectShellPane.addEventListener(
      "click",
      () => hideProjectShellPane(runtime),
    );
    runtime.elements.stopProjectShell.addEventListener(
      "click",
      () => stopProjectShellProcess(runtime),
    );
  }

  window.ElectroBoyFrontend.registerModule({
    id: "project-shell",
    label: "Project Shell",
    capabilities: ["shell", "terminal"],
    actions: {
      initializeProjectShellTerminal,
      queueProjectShellResize,
      sendProjectShellResize,
      appendProjectShellOutput,
      clearProjectShellOutput,
      applyProjectShellPaneVisibility,
      showProjectShellPane,
      hideProjectShellPane,
      syncProjectShellPane,
      toggleProjectShellFromToolbar,
      updateProjectShellToggle,
      startProjectShell,
      connectProjectShellEvents,
      closeProjectShellEventStream: () => closeProjectShellEventStream(),
      disposeProjectShellTerminal,
      sendProjectShellInput,
      stopProjectShellProcess,
      terminal: () => terminal,
      fit: () => fit(),
      status,
    },
    mount,
  });
})();
