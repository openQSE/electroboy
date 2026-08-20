(function () {
  "use strict";

  let terminal = null;
  let terminalFit = null;
  let eventSource = null;
  let resizeTimer = null;
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
    if (terminal) {
      terminal.clear();
      return;
    }
    runtime.elements.projectShellOutput.replaceChildren();
  }

  function applyProjectShellPaneVisibility(runtime) {
    const state = shellState(runtime);
    const visible = state.projectShellPaneRequested && !runtime.layout.isPopped("shell");
    if (visible) {
      runtime.layout.ensurePane("shell", "agent", "column", { activateExisting: false });
    }
    runtime.elements.projectShellPane.hidden = !visible;
    runtime.elements.shellPaneDivider.hidden = !visible;
    runtime.elements.leftOutputPane.classList.toggle("shell-visible", visible);
    if (visible) {
      runtime.layout.applyStoredShellHeight();
      initializeProjectShellTerminal(runtime);
    }
    window.requestAnimationFrame(() => runtime.terminals.fitAll());
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
    const toggle = runtime.elements.toggleProjectShellPane;
    if (!toggle) {
      return;
    }
    const state = shellState(runtime);
    const hasActiveProject = Boolean(state.activeProjectRoot);
    toggle.disabled = !hasActiveProject;
    toggle.classList.remove("active");
    toggle.textContent = "Shell";
    if (!hasActiveProject) {
      toggle.title = "Activate a project to open a shell";
    } else {
      toggle.title = "Open a new shell window in the active project";
    }
  }

  async function startProjectShell(runtime) {
    const state = shellState(runtime);
    if (!state.activeProjectRoot || !state.contextId) {
      runtime.notifications.appendOutput("activate a project first\n", "error");
      return;
    }
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
    const response = await runtime.http.fetch(
      runtime.http.contextUrl("/api/shell/start"),
      { method: "POST" },
    );
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
      const stopUrl = runtime.http.contextUrl(
        `/api/shell/stop?session_id=${encodeURIComponent(sessionId)}`,
      );
      const stopResponse = await runtime.http.fetch(stopUrl, { method: "POST" });
      const stopPayload = await stopResponse.json().catch(() => null);
      if (stopResponse.ok && stopPayload) {
        runtime.project.update(stopPayload);
      }
      return;
    }
    updateShellState(runtime, {
      projectShellRunning: Boolean(payload.project_shell_running),
      projectShellPaneDismissed: true,
      projectShellPaneRequested: false,
    });
    runtime.project.update(payload);
    const parameters = runtime.http.contextParameters();
    parameters.set("shell_session_id", sessionId);
    parameters.set("disposable", "1");
    parameters.set("font_size", String(state.terminalFontSize || 15));
    popup.location.replace(`/pane/shell?${parameters.toString()}`);
    popup.focus();
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
    runtime.elements.toggleProjectShellPane.addEventListener("click", () => {
      toggleProjectShellFromToolbar(runtime).catch((error) => {
        runtime.notifications.appendOutput(
          `project shell failed: ${error}\n`,
          "error",
        );
      });
    });
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
