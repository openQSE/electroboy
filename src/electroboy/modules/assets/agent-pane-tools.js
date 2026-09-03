(function () {
  "use strict";

  function button(label, action, className = "") {
    const element = document.createElement("button");
    element.type = "button";
    element.textContent = label;
    if (className) element.className = className;
    element.addEventListener("click", action);
    return element;
  }

  function menu(label, className = "") {
    const details = document.createElement("details");
    details.className = `pane-tool-menu ${className}`.trim();
    const summary = document.createElement("summary");
    summary.className = "pane-tool-menu-trigger";
    const text = document.createElement("span");
    text.textContent = label;
    const chevron = document.createElement("span");
    chevron.className = "pane-tool-menu-chevron";
    chevron.setAttribute("aria-hidden", "true");
    summary.append(text, chevron);
    const list = document.createElement("div");
    list.className = "pane-tool-menu-list";
    details.append(summary, list);
    return { details, list };
  }

  function menuButton(label, action, className = "") {
    return button(label, action, `pane-tool-menu-button ${className}`.trim());
  }

  function mount(options) {
    const controller = options.controller;
    const controls = options.controls || {};
    const actions = options.actions || {};
    const getSession = typeof options.getSession === "function"
      ? options.getSession
      : () => null;
    const getTarget = typeof options.getTarget === "function"
      ? options.getTarget
      : () => ({});
    const getSessions = typeof options.getSessions === "function"
      ? options.getSessions
      : () => [];
    const displayLabel = typeof options.displayLabel === "function"
      ? options.displayLabel
      : (session) => `${session.kind || "agent"} · ${session.status || "done"}`;

    function session() {
      return getSession() || null;
    }

    function sessions() {
      const value = getSessions();
      return Array.isArray(value) ? value : [];
    }

    function runningSessions() {
      return sessions().filter((candidate) =>
        candidate && candidate.session_id && candidate.status === "running"
      );
    }

    function target() {
      return getTarget() || {};
    }

    function actionErrorMessage(error) {
      return error && error.message ? error.message : String(error);
    }

    function setActionStatus(text, isError = false) {
      actionStatus.textContent = text || "";
      actionStatus.classList.toggle("error", Boolean(isError));
    }

    function runAction(name, fallback, ...args) {
      try {
        const currentSession = session();
        const result = typeof actions[name] === "function"
          ? actions[name](currentSession, target(), ...args)
          : fallback(currentSession, target(), ...args);
        Promise.resolve(result)
          .then((value) => {
            if (typeof value === "string") {
              setActionStatus(value);
            } else if (name === "terminate" && value) {
              setActionStatus("Agent closed");
            } else if (name === "interrupt") {
              setActionStatus("Interrupt sent");
            } else if (name === "export") {
              setActionStatus("");
            }
            refresh();
          })
          .catch((error) => {
            setActionStatus(actionErrorMessage(error), true);
            refresh();
          });
      } catch (error) {
        setActionStatus(actionErrorMessage(error), true);
        refresh();
      }
    }

    function sessionLabel(candidate) {
      return String(displayLabel(candidate) || candidate.session_id || "agent");
    }

    function chooseRunningSession() {
      const choices = runningSessions();
      if (choices.length === 0) {
        setActionStatus("No running sessions", true);
        return Promise.resolve("");
      }
      const dialog = document.createElement("dialog");
      dialog.className = "agent-focus-session-dialog";
      dialog.innerHTML = `
        <form method="dialog" class="agent-focus-session-form">
          <header class="agent-focus-session-header">
            <div>
              <h2>Focus session</h2>
              <p>Select a running agent session.</p>
            </div>
            <button
              type="button"
              class="agent-focus-session-close"
              aria-label="Close"
            >x</button>
          </header>
          <fieldset class="agent-focus-session-options">
            <legend>Running sessions</legend>
            <div class="agent-focus-session-list"></div>
          </fieldset>
          <footer class="agent-focus-session-footer">
            <button type="button" class="agent-focus-session-cancel">Cancel</button>
            <button type="submit" class="agent-focus-session-submit">Focus</button>
          </footer>
        </form>
      `;
      const list = dialog.querySelector(".agent-focus-session-list");
      const currentSessionId = session()?.session_id || "";
      choices.forEach((candidate, index) => {
        const label = document.createElement("label");
        label.className = "agent-focus-session-option";
        const input = document.createElement("input");
        input.type = "radio";
        input.name = "agent-focus-session";
        input.value = String(candidate.session_id || "");
        input.checked = currentSessionId
          ? candidate.session_id === currentSessionId
          : index === 0;
        const copy = document.createElement("span");
        copy.className = "agent-focus-session-option-copy";
        const title = document.createElement("strong");
        title.textContent = sessionLabel(candidate);
        const details = document.createElement("span");
        details.textContent = String(candidate.session_id || "");
        copy.append(title, details);
        label.append(input, copy);
        list.append(label);
      });
      document.body.append(dialog);
      return new Promise((resolve) => {
        const finish = (sessionId) => {
          dialog.close();
          dialog.remove();
          resolve(sessionId);
        };
        dialog.querySelector(".agent-focus-session-close").onclick = () => {
          finish("");
        };
        dialog.querySelector(".agent-focus-session-cancel").onclick = () => {
          finish("");
        };
        dialog.oncancel = (event) => {
          event.preventDefault();
          finish("");
        };
        dialog.querySelector("form").onsubmit = (event) => {
          event.preventDefault();
          const selected = dialog.querySelector(
            'input[name="agent-focus-session"]:checked',
          );
          finish(selected ? selected.value : "");
        };
        dialog.showModal();
      });
    }

    function focusRunningSession() {
      chooseRunningSession()
        .then((sessionId) => {
          if (sessionId) {
            runAction("focus", () => {}, sessionId);
          }
        })
        .catch((error) => {
          setActionStatus(actionErrorMessage(error), true);
          refresh();
        });
    }

    const viewBody = controller.addSection("agent-view", "View");
    if (controls.font) {
      controls.font.hidden = false;
      controls.font.classList.add("pane-tool-font-row");
      viewBody.append(controls.font);
    }

    const actionsBody = controller.addSection("agent-actions", "Actions");
    const exportButton = button("Export transcript", () => {
      runAction("export", () => controls.exportButton?.click());
    }, "primary");

    const paneMenu = menu("Pane", "pane-tool-agent-pane-menu");
    const pop = menuButton("Pop", () => {
      runAction("pop", () => controls.popButton?.click());
    });
    const dock = menuButton("Dock", () => {
      runAction("dock", () => controls.dockButton?.click());
    });
    const closePane = menuButton("Close pane", () => {
      runAction("closePane", () => {});
    });
    paneMenu.list.append(pop, dock, closePane);

    const agentMenu = menu("Agent", "pane-tool-agent-session-menu");
    const focus = menuButton("Focus session", focusRunningSession);
    const interrupt = menuButton("Interrupt", () => {
      runAction("interrupt", () => {});
    });
    const terminate = menuButton("Terminate agent", () => {
      runAction("terminate", () => {});
    }, "danger");
    agentMenu.list.append(focus, interrupt, terminate);

    const actionStatus = document.createElement("div");
    actionStatus.className = "pane-tool-status";
    actionsBody.append(
      exportButton,
      paneMenu.details,
      agentMenu.details,
      actionStatus,
    );

    function hideLegacyControls() {
      if (controls.exportButton) controls.exportButton.hidden = true;
      if (controls.popButton) controls.popButton.hidden = true;
      if (controls.dockButton) controls.dockButton.hidden = true;
    }

    function refresh() {
      hideLegacyControls();
      const currentSession = session();
      const currentTarget = target();
      const runningSessionCount = runningSessions().length;
      const hasSession = Boolean(currentSession);
      const isRunning = currentSession && currentSession.status === "running";
      const canPop = currentTarget.canPop !== false;
      const canDock = Boolean(currentTarget.canDock);
      const canClosePane = currentTarget.canClosePane !== false;
      exportButton.disabled = !hasSession;
      focus.disabled = runningSessionCount === 0;
      interrupt.disabled = !isRunning;
      terminate.disabled = !hasSession;
      pop.hidden = !canPop;
      dock.hidden = !canDock;
      closePane.hidden = !canClosePane;
      const paneMenuVisible = !pop.hidden || !dock.hidden || !closePane.hidden;
      paneMenu.details.hidden = !paneMenuVisible;
      agentMenu.details.hidden = !hasSession && runningSessionCount === 0;
      const hasControls = (
        Boolean(controls.font) ||
        hasSession ||
        runningSessionCount > 0 ||
        paneMenuVisible
      );
      controller.setEnabled(hasControls);
    }

    refresh();

    return { refresh };
  }

  window.ElectroBoyAgentPaneTools = { mount };
})();
