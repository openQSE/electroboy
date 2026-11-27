(function () {
  "use strict";

  function button(label, action, className = "", options = {}) {
    if (window.ElectroBoyPaneTools?.actionButton) {
      return window.ElectroBoyPaneTools.actionButton(label, action, {
        ...options,
        className,
        primary: className.split(/\s+/).includes("primary"),
        danger: className.split(/\s+/).includes("danger"),
      });
    }
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

  async function configureAgentChoice(dialog, contextUrl, initialBinary, onChange) {
    const response = await fetch(contextUrl("/api/workspaces/agent-config"));
    if (!response.ok) throw new Error("Could not load agent selections.");
    const config = await response.json();
    let label = dialog.querySelector(".agent-launch-selection");
    if (!label) {
      label = document.createElement("label");
      label.className = "agent-launch-selection";
      label.append(document.createTextNode("Agent "));
      const select = document.createElement("select");
      select.setAttribute("aria-label", "Agent for this session");
      label.append(select);
      const form = dialog.querySelector("form");
      form.insertBefore(label, form.querySelector("fieldset"));
    }
    const select = label.querySelector("select");
    select.replaceChildren(...(config.backends || []).map((binary) => {
      const option = document.createElement("option");
      option.value = binary;
      option.textContent = binary;
      option.disabled = config.availability?.[binary] === false;
      return option;
    }));
    select.value = initialBinary || config.backend;
    if (!select.value) throw new Error("Selected agent is unavailable.");
    select.onchange = () => onChange(select.value);
    return select;
  }

  async function chooseAgentForLaunch(contextUrl, initialBinary = "") {
    const dialog = document.createElement("dialog");
    dialog.className = "agent-focus-session-dialog";
    dialog.innerHTML = `<form method="dialog"><h2>Start agent</h2>
      <fieldset><legend>Agent selection</legend></fieldset>
      <button type="button" class="cancel">Cancel</button>
      <button type="submit">Start</button></form>`;
    document.body.append(dialog);
    let selection;
    try {
      selection = await configureAgentChoice(dialog, contextUrl, initialBinary, () => {});
    } catch (error) {
      dialog.remove();
      throw error;
    }
    return new Promise((resolve) => {
      const finish = (value) => { dialog.close(); dialog.remove(); resolve(value); };
      dialog.querySelector(".cancel").onclick = () => finish(null);
      dialog.oncancel = (event) => { event.preventDefault(); finish(null); };
      dialog.querySelector("form").onsubmit = (event) => {
        event.preventDefault(); finish(selection.value);
      };
      dialog.showModal();
    });
  }

  function confirmUnresolvedAgent(binary) {
    const dialog = document.createElement("dialog");
    dialog.className = "agent-focus-session-dialog";
    dialog.innerHTML = `<form method="dialog"><h2>Confirm session agent</h2>
      <p></p><button type="button" class="cancel">Cancel</button>
      <button type="submit">Resume</button></form>`;
    dialog.querySelector("p").textContent =
      `This session has no saved agent. Resume it with ${binary}?`;
    document.body.append(dialog);
    return new Promise((resolve) => {
      const finish = (value) => { dialog.close(); dialog.remove(); resolve(value); };
      dialog.querySelector(".cancel").onclick = () => finish(false);
      dialog.oncancel = (event) => { event.preventDefault(); finish(false); };
      dialog.querySelector("form").onsubmit = (event) => {
        event.preventDefault(); finish(true);
      };
      dialog.showModal();
    });
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
    const getWorkspaceId = options.getWorkspaceId || (() => "");
    let configuredWorkspace = "";
    let selectedBinary = "";
    let selectionChanged = false;

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

    function confirmTerminateSession(candidate) {
      const running = candidate && candidate.status === "running";
      const action = running ? "Terminate" : "Close";
      const dialog = document.createElement("dialog");
      dialog.className = "agent-focus-session-dialog agent-terminate-dialog";
      dialog.innerHTML = `
        <form method="dialog" class="agent-focus-session-form">
          <header class="agent-focus-session-header">
            <div>
              <h2>${action} agent?</h2>
              <p></p>
            </div>
            <button
              type="button"
              class="agent-focus-session-close"
              aria-label="Close"
            >&times;</button>
          </header>
          <section class="agent-terminate-session-body">
            <p>${running
              ? "The running process will be stopped and its pane will be closed."
              : "The completed session will be removed from this workspace."}</p>
          </section>
          <footer class="agent-focus-session-footer">
            <button type="button" class="agent-focus-session-cancel">Cancel</button>
            <button
              type="submit"
              class="agent-focus-session-submit agent-terminate-session-submit"
            >${action}</button>
          </footer>
        </form>
      `;
      dialog.querySelector(".agent-focus-session-header p").textContent =
        sessionLabel(candidate);
      document.body.append(dialog);
      return new Promise((resolve) => {
        const finish = (confirmed) => {
          dialog.close();
          dialog.remove();
          resolve(confirmed);
        };
        dialog.querySelector(".agent-focus-session-close").onclick = () => {
          finish(false);
        };
        dialog.querySelector(".agent-focus-session-cancel").onclick = () => {
          finish(false);
        };
        dialog.oncancel = (event) => {
          event.preventDefault();
          finish(false);
        };
        dialog.querySelector("form").onsubmit = (event) => {
          event.preventDefault();
          finish(true);
        };
        dialog.showModal();
      });
    }

    function terminateSession() {
      const candidate = session();
      if (!candidate) {
        setActionStatus("Select an agent session first", true);
        return;
      }
      confirmTerminateSession(candidate)
        .then((confirmed) => {
          if (confirmed) runAction("terminate", () => {});
        })
        .catch((error) => {
          setActionStatus(actionErrorMessage(error), true);
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
    const selectionLabel = document.createElement("label");
    selectionLabel.textContent = "Agent for next start";
    const selection = document.createElement("select");
    selection.setAttribute("aria-label", "Agent for next start");
    selection.disabled = true;
    selectionLabel.append(selection);
    selection.addEventListener("change", () => {
      selectedBinary = selection.value;
      selectionChanged = true;
    });
    async function refreshAgentSelection() {
      if (typeof options.loadAgentConfig !== "function") return;
      const workspace = String(getWorkspaceId() || "");
      if (!workspace) return;
      const config = await options.loadAgentConfig();
      if (workspace !== String(getWorkspaceId() || "")) return;
      if (configuredWorkspace !== workspace) {
        configuredWorkspace = workspace;
        selectedBinary = "";
        selectionChanged = false;
      }
      if (!selectionChanged) selectedBinary = String(config.backend || "");
      selection.replaceChildren(...(config.backends || []).map((binary) => {
        const option = document.createElement("option");
        option.value = binary;
        option.textContent = binary;
        option.disabled = config.availability?.[binary] === false;
        return option;
      }));
      selection.value = selectedBinary;
      selection.disabled = false;
    }
    agentMenu.details.addEventListener("toggle", () => {
      if (agentMenu.details.open) {
        refreshAgentSelection().catch((error) => setActionStatus(actionErrorMessage(error), true));
      }
    });
    const start = menuButton("Start agent", () => {
      const binary = configuredWorkspace === String(getWorkspaceId() || "")
        ? selectedBinary : "";
      runAction("start", () => {}, { agentBinary: binary });
    });
    const info = menuButton("Info", async () => {
      const current = session();
      const workspace = String(getWorkspaceId() || "");
      const dialog = document.createElement("dialog");
      dialog.className = "agent-focus-session-dialog";
      const title = document.createElement("h2");
      title.textContent = "Agent info";
      const details = document.createElement("p");
      const list = document.createElement("ul");
      const metadata = current?.metadata || {};
      const provider = String(metadata.provider || "");
      const binary = String(metadata.provider_binary || "");
      details.textContent = current
        ? [sessionLabel(current), `Status: ${current.status || "unknown"}`,
          `Provider: ${provider || "unresolved"}`,
          `Agent: ${binary || "unresolved"}`,
          `Binary: ${metadata.provider_executable || "unavailable"}`,
          `Workspace: ${getWorkspaceId() || "unknown"}`,
          `Project: ${target().projectRoot || "unknown"}`,
          `Session: ${current.session_id || "unknown"}`,
          `Provider session: ${metadata.provider_session_id || "unknown"}`].join(" · ")
        : "No agent session selected.";
      if (current && binary && provider) {
        try {
          const entries = typeof options.loadAgentSessions === "function"
            ? await options.loadAgentSessions() : [];
          if (workspace !== String(getWorkspaceId() || "")) return;
          for (const entry of entries) {
            if (entry.provider !== provider || entry.provider_binary !== binary) continue;
            const item = document.createElement("li");
            item.textContent = `${entry.name || "Agent"} · ${entry.status || "unknown"} · ${entry.session_id || ""}`;
            list.append(item);
          }
        } catch (error) {
          const item = document.createElement("li");
          item.textContent = `Could not load sessions: ${actionErrorMessage(error)}`;
          list.append(item);
        }
      }
      const close = button("Close", () => { dialog.close(); dialog.remove(); });
      dialog.append(title, details, list, close);
      dialog.addEventListener("cancel", () => dialog.remove(), { once: true });
      document.body.append(dialog);
      dialog.showModal();
    });
    const focus = menuButton("Focus session", focusRunningSession);
    const interrupt = menuButton("Interrupt", () => {
      runAction("interrupt", () => {});
    });
    const terminate = menuButton("Terminate agent", terminateSession, "danger");
    agentMenu.list.append(selectionLabel, start, info, focus, interrupt, terminate);

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
      const canStart = typeof actions.start === "function"
        && currentTarget.canStart !== false;
      exportButton.disabled = !hasSession;
      start.disabled = !canStart;
      focus.disabled = runningSessionCount === 0;
      interrupt.disabled = !isRunning;
      terminate.disabled = !hasSession;
      pop.hidden = !canPop;
      dock.hidden = !canDock;
      closePane.hidden = !canClosePane;
      const paneMenuVisible = !pop.hidden || !dock.hidden || !closePane.hidden;
      paneMenu.details.hidden = !paneMenuVisible;
      agentMenu.details.hidden = !canStart && !hasSession && runningSessionCount === 0;
      const hasControls = (
        Boolean(controls.font) ||
        canStart ||
        hasSession ||
        runningSessionCount > 0 ||
        paneMenuVisible
      );
      controller.setEnabled(hasControls);
    }

    refresh();

    return { refresh };
  }

  window.ElectroBoyAgentPaneTools = {
    mount, configureAgentChoice, chooseAgentForLaunch, confirmUnresolvedAgent,
  };
})();
