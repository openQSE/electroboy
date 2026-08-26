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

    function session() {
      return getSession() || null;
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
    const interrupt = menuButton("Interrupt", () => {
      runAction("interrupt", () => {});
    });
    const terminate = menuButton("Terminate agent", () => {
      runAction("terminate", () => {});
    }, "danger");
    agentMenu.list.append(interrupt, terminate);

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
      const hasSession = Boolean(currentSession);
      const isRunning = currentSession && currentSession.status === "running";
      const canPop = currentTarget.canPop !== false;
      const canDock = Boolean(currentTarget.canDock);
      const canClosePane = currentTarget.canClosePane !== false;
      exportButton.disabled = !hasSession;
      interrupt.disabled = !isRunning;
      terminate.disabled = !hasSession;
      pop.hidden = !canPop;
      dock.hidden = !canDock;
      closePane.hidden = !canClosePane;
      const paneMenuVisible = !pop.hidden || !dock.hidden || !closePane.hidden;
      paneMenu.details.hidden = !paneMenuVisible;
      agentMenu.details.hidden = !hasSession;
      const hasControls = Boolean(controls.font) || hasSession || paneMenuVisible;
      controller.setEnabled(hasControls);
    }

    refresh();

    return { refresh };
  }

  window.ElectroBoyAgentPaneTools = { mount };
})();
