(function () {
  "use strict";

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
        appendOutput("activate a project first\n", "error");
        return;
      }
      showProjectShellPane(true);
      initializeProjectShellTerminal();
      appendProjectShellOutput("starting project shell...\r\n", "system");
      const response = await fetch(contextUrl("/api/shell/start"), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "shell start failed" }));
      if (!response.ok) {
        appendProjectShellOutput(`${payload.error || "shell start failed"}\r\n`, "error");
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
          appendProjectShellOutput(`${payload.text}\r\n`, payload.type);
        } else if (payload.type === "completed") {
          appendProjectShellOutput(
            `\r\nproject shell exited with code ${payload.returncode}\r\n`,
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
        appendProjectShellOutput(`${payload.error || "shell stop failed"}\r\n`, "error");
        return;
      }
      projectShellRunning = false;
      projectShellPaneDismissed = false;
      closeProjectShellEventStream();
      updateProjectState(payload);
    }


  function mount(runtime) {
    const element = runtime.elements;
    const action = runtime.actions;
    element.openProjectShell.addEventListener(
      "click",
      () => action.startProjectShell(),
    );
    element.toggleProjectShellPane.addEventListener("click", () => {
      action.toggleProjectShellFromToolbar().catch((error) => {
        action.appendOutput(`project shell failed: ${error}\n`, "error");
      });
    });
    element.closeProjectShellPane.addEventListener(
      "click",
      () => action.hideProjectShellPane(),
    );
    element.stopProjectShell.addEventListener(
      "click",
      () => action.stopProjectShellProcess(),
    );
  }

  window.ElectroBoyFrontend.registerModule({
    id: "project-shell",
    label: "Project Shell",
    capabilities: ["shell", "terminal"],
    actions: {
      initializeProjectShellTerminal: (_runtime, ...args) => initializeProjectShellTerminal(...args),
      queueProjectShellResize: (_runtime, ...args) => queueProjectShellResize(...args),
      sendProjectShellResize: (_runtime, ...args) => sendProjectShellResize(...args),
      appendProjectShellOutput: (_runtime, ...args) => appendProjectShellOutput(...args),
      clearProjectShellOutput: (_runtime, ...args) => clearProjectShellOutput(...args),
      applyProjectShellPaneVisibility: (_runtime, ...args) => applyProjectShellPaneVisibility(...args),
      showProjectShellPane: (_runtime, ...args) => showProjectShellPane(...args),
      hideProjectShellPane: (_runtime, ...args) => hideProjectShellPane(...args),
      syncProjectShellPane: (_runtime, ...args) => syncProjectShellPane(...args),
      toggleProjectShellFromToolbar: (_runtime, ...args) => toggleProjectShellFromToolbar(...args),
      updateProjectShellToggle: (_runtime, ...args) => updateProjectShellToggle(...args),
      startProjectShell: (_runtime, ...args) => startProjectShell(...args),
      connectProjectShellEvents: (_runtime, ...args) => connectProjectShellEvents(...args),
      closeProjectShellEventStream: (_runtime, ...args) => closeProjectShellEventStream(...args),
      disposeProjectShellTerminal: (_runtime, ...args) => disposeProjectShellTerminal(...args),
      sendProjectShellInput: (_runtime, ...args) => sendProjectShellInput(...args),
      stopProjectShellProcess: (_runtime, ...args) => stopProjectShellProcess(...args),
    },
    mount,
  });
})();
