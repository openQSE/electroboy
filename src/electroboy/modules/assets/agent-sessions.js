(function () {
  "use strict";

    function sessionExportName(session) {
      const kind = exportSafeName(session && session.kind, "agent");
      return `agent-session-${kind}-${timestampForDownload()}.md`;
    }

    async function exportAgentSession() {
      const session = selectedSession();
      if (!session) {
        appendOutput("select an agent session first\n", "error");
        return;
      }
      const url = contextUrl(
        `/api/sessions/export?session_id=${encodeURIComponent(session.session_id)}`,
      );
      await exportMarkdown(url, sessionExportName(session));
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

    function agentSessionDisplayLabel(session) {
      const status = session.status === "running" ? "running" : session.status || "done";
      const documentTarget = documentTargetForSession(session);
      if (documentTarget) {
        return `Document: ${documentTargetLabel(documentTarget)} · ${status}`;
      }
      return `${session.kind || "agent"} · ${status}`;
    }

    function attachableServiceSessions() {
      const localIds = new Set(agentSessions.map((session) => session.session_id));
      return serviceSessions.filter((session) => {
        if (!session || !session.attachable || !session.session_id) {
          return false;
        }
        if (localIds.has(session.session_id)) {
          return false;
        }
        return session.kind !== "project-shell";
      });
    }

    function serviceSessionDisplayLabel(session) {
      const baseLabel = agentSessionDisplayLabel(session);
      const project = String(session.active_project_root || "").split("/").filter(Boolean).pop();
      return project ? `${project}: ${baseLabel}` : baseLabel;
    }

    function renderSessionSwitcher() {
      sessionSwitcher.replaceChildren();
      const remoteSessions = attachableServiceSessions();
      if (agentSessions.length === 0 && remoteSessions.length === 0) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "No streams";
        sessionSwitcher.append(option);
        sessionSwitcher.disabled = true;
        updateSessionIndicator(null);
        return;
      }
      if (agentSessions.length === 0 && remoteSessions.length > 0) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "Attach service stream...";
        sessionSwitcher.append(option);
      }
      const localParent = agentSessions.length > 0
        ? document.createElement("optgroup")
        : sessionSwitcher;
      if (agentSessions.length > 0) {
        localParent.label = "Current context";
        sessionSwitcher.append(localParent);
      }
      for (const session of agentSessions) {
        const option = document.createElement("option");
        option.value = session.session_id;
        option.textContent = agentSessionDisplayLabel(session);
        localParent.append(option);
      }
      if (remoteSessions.length > 0) {
        const remoteParent = document.createElement("optgroup");
        remoteParent.label = "Service sessions";
        for (const session of remoteSessions) {
          const option = document.createElement("option");
          option.value = `attach:${session.session_id}`;
          option.textContent = serviceSessionDisplayLabel(session);
          remoteParent.append(option);
        }
        sessionSwitcher.append(remoteParent);
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
      if (sessionId && sessionId.startsWith("attach:")) {
        await attachAgentSession(sessionId.slice("attach:".length));
        return;
      }
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
        appendOutput(`${payload.error || "session switch failed"}\n`, "error");
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

    async function refreshServiceSessions() {
      const response = await fetch("/api/session-registry", { cache: "no-store" });
      if (!response.ok) {
        return;
      }
      const payload = await response.json().catch(() => ({ sessions: [] }));
      serviceSessions = Array.isArray(payload.sessions) ? payload.sessions : [];
      renderSessionSwitcher();
    }

    async function attachAgentSession(sessionId) {
      if (!contextId || !sessionId) {
        return;
      }
      const response = await fetch(contextUrl("/api/sessions/attach"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      const payload = await response.json().catch(() => ({ error: "session attach failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "session attach failed"}\n`, "error");
        renderSessionSwitcher();
        return;
      }
      updateProjectState(payload);
      await refreshServiceSessions();
      const session = selectedSession();
      if (!session) {
        return;
      }
      clearAgentOutput();
      if (session.interactive) {
        showProgressPane(false);
        setAgentInputVisible(true);
      } else {
        clearProgressOutput();
        showProgressPane(true);
        setAgentInputVisible(false);
      }
      activeAgentKind = session.kind || "";
      const documentTarget = documentTargetForSession(session);
      if (documentTarget) {
        showDocumentPreview(documentTarget);
      }
      connectSessionEvents(session.session_id);
      if (!session.interactive && session.status === "running") {
        connectProgressEvents();
      }
      updateAgentControls();
      sendTerminalResize();
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
          appendOutput(`${payload.text}\n`, "system");
        } else if (payload.type === "error") {
          appendOutput(`${payload.text}\n`, "error");
        } else if (payload.type === "completed") {
          appendOutput(`\nprocess exited with code ${payload.returncode}\n`, "system");
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
          appendOutput(`${payload.text}\n`, "system");
        } else if (payload.type === "error") {
          appendOutput(`${payload.text}\n`, "error");
        } else if (payload.type === "completed") {
          appendOutput(`\nprocess exited with code ${payload.returncode}\n`, "system");
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

    function closeAgentEventStream() {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
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
        appendOutput(`${payload.error || "send failed"}\n`, "error");
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
          appendOutput(`${payload.error || "send failed"}\n`, "error");
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
          appendOutput(`${payload.error || "send failed"}\n`, "error");
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
        appendOutput(`${payload.error || "interrupt failed"}\n`, "error");
      }
    }


  function mount(runtime) {
    const element = runtime.elements;
    const action = runtime.actions;
    element.sessionSwitcher.addEventListener("change", () => {
      action.selectAgentSession(element.sessionSwitcher.value).catch((error) => {
        action.appendOutput(`session switch failed: ${error}\n`, "error");
      });
    });
    element.exportAgentOutput.addEventListener("click", () => {
      action.exportAgentSession().catch((error) => {
        action.appendOutput(`export failed: ${error}\n`, "error");
      });
    });
    element.interruptAgent.addEventListener(
      "click",
      () => action.interruptActiveAgent(),
    );
    element.agentInput.addEventListener("keydown", (event) => {
      if (action.handleSlashCommandInput(event)) {
        return;
      }
      const terminalKey = action.terminalKeyForInputEvent(event);
      if (terminalKey) {
        event.preventDefault();
        action.sendTerminalKey(terminalKey);
        return;
      }
      const isEnter = event.key === "Enter" || event.code === "Enter" ||
        event.code === "NumpadEnter";
      if (isEnter && event.shiftKey) {
        event.preventDefault();
        if (element.agentInput.value.trim()) {
          action.sendMessage();
        } else {
          action.sendTerminalKey("enter");
        }
      }
    });
  }

  window.ElectroBoyFrontend.registerModule({
    id: "agent-sessions",
    label: "Agent Sessions",
    capabilities: ["session-switching", "terminal-input", "session-export"],
    actions: {
      sessionExportName: (_runtime, ...args) => sessionExportName(...args),
      exportAgentSession: (_runtime, ...args) => exportAgentSession(...args),
      selectedSession: (_runtime, ...args) => selectedSession(...args),
      sessionIsRunning: (_runtime, ...args) => sessionIsRunning(...args),
      selectedSessionAcceptsInput: (_runtime, ...args) => selectedSessionAcceptsInput(...args),
      updateSessionIndicator: (_runtime, ...args) => updateSessionIndicator(...args),
      sessionMetadata: (_runtime, ...args) => sessionMetadata(...args),
      agentSessionDisplayLabel: (_runtime, ...args) => agentSessionDisplayLabel(...args),
      attachableServiceSessions: (_runtime, ...args) => attachableServiceSessions(...args),
      serviceSessionDisplayLabel: (_runtime, ...args) => serviceSessionDisplayLabel(...args),
      renderSessionSwitcher: (_runtime, ...args) => renderSessionSwitcher(...args),
      selectAgentSession: (_runtime, ...args) => selectAgentSession(...args),
      refreshServiceSessions: (_runtime, ...args) => refreshServiceSessions(...args),
      attachAgentSession: (_runtime, ...args) => attachAgentSession(...args),
      connectAgentEvents: (_runtime, ...args) => connectAgentEvents(...args),
      connectSessionEvents: (_runtime, ...args) => connectSessionEvents(...args),
      closeAgentEventStream: (_runtime, ...args) => closeAgentEventStream(...args),
      agentProcessRunning: (_runtime, ...args) => agentProcessRunning(...args),
      updateAgentControls: (_runtime, ...args) => updateAgentControls(...args),
      setAgentRunning: (_runtime, ...args) => setAgentRunning(...args),
      sendMessage: (_runtime, ...args) => sendMessage(...args),
      queueTerminalInput: (_runtime, ...args) => queueTerminalInput(...args),
      sendTerminalKey: (_runtime, ...args) => sendTerminalKey(...args),
      sendTerminalRaw: (_runtime, ...args) => sendTerminalRaw(...args),
      printableInputEvent: (_runtime, ...args) => printableInputEvent(...args),
      slashCommandTerminalKeyForInputEvent: (_runtime, ...args) => slashCommandTerminalKeyForInputEvent(...args),
      refreshSlashCommandModeAfterEdit: (_runtime, ...args) => refreshSlashCommandModeAfterEdit(...args),
      finishSlashCommandMode: (_runtime, ...args) => finishSlashCommandMode(...args),
      handleSlashCommandInput: (_runtime, ...args) => handleSlashCommandInput(...args),
      terminalKeyForInputEvent: (_runtime, ...args) => terminalKeyForInputEvent(...args),
      interruptActiveAgent: (_runtime, ...args) => interruptActiveAgent(...args),
    },
    mount,
  });
})();
