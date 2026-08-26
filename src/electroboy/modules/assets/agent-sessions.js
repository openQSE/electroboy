(function () {
  "use strict";

  let runtimeApi = null;
  let runtimeState = null;
  let inputPaneSync = null;
  let inputSyncQueue = Promise.resolve();
  let agentEventStreamVersion = 0;
  const agentEventStreams = new Map();
  const inputDrafts = new Map();
  let agentPaneTools = null;

  function bindRuntime(runtime) {
    runtimeApi = runtime;
    runtimeState = runtime.state;
  }

  function invoke(runtime, handler, args) {
    bindRuntime(runtime);
    return handler(...args);
  }

  const exportSafeName = (...args) => runtimeApi.downloads.safeName(...args);
  const timestampForDownload = (...args) => runtimeApi.downloads.timestamp(...args);
  const appendOutput = (...args) => runtimeApi.notifications.appendOutput(...args);
  const contextUrl = (...args) => runtimeApi.http.contextUrl(...args);
  const exportMarkdown = (...args) => runtimeApi.downloads.exportMarkdown(...args);
  const documentTargetForSession = (...args) =>
    runtimeApi.modules.invoke("documents", "documentTargetForSession", ...args);
  const documentTargetLabel = (...args) =>
    runtimeApi.modules.invoke("documents", "documentTargetLabel", ...args);
  const syncOpenDocumentTargetsFromSessions = (...args) =>
    runtimeApi.modules.invoke(
      "documents",
      "syncOpenDocumentTargetsFromSessions",
      ...args,
    );
  const showDocumentPreview = (...args) =>
    runtimeApi.modules.invoke("documents", "showDocumentPreview", ...args);
  const refreshArtifactPreview = (...args) =>
    runtimeApi.modules.invoke("documents", "refreshArtifactPreview", ...args);
  const showArtifactPreview = (...args) =>
    runtimeApi.modules.invoke("documents", "showArtifactPreview", ...args);
  const closeArtifactEventStream = (...args) =>
    runtimeApi.modules.invoke("documents", "closeArtifactEventStream", ...args);
  const sendTerminalResize = (...args) => runtimeApi.agent.sendResize(...args);
  const updateProjectState = (...args) => runtimeApi.project.update(...args);
  const showProgressPane = (...args) => runtimeApi.layout.showProgressPane(...args);
  const setAgentInputVisible = (...args) =>
    runtimeApi.ui.setAgentInputVisible(...args);
  const clearProgressOutput = (...args) =>
    runtimeApi.modules.invoke("progress", "clearProgressOutput", ...args);
  const connectProgressEvents = (...args) =>
    runtimeApi.modules.invoke("progress", "connectProgressEvents", ...args);
  const closeProgressEventStream = (...args) =>
    runtimeApi.modules.invoke("progress", "closeProgressEventStream", ...args);
  const prepareTerminalStream = (...args) =>
    runtimeApi.agent.prepareTerminal(...args);
  const appendAgentOutput = (...args) => runtimeApi.agent.appendOutput(...args);
  const refreshProject = (...args) => runtimeApi.project.refresh(...args);
  const creativePromptMessage = (...args) =>
    runtimeApi.workflows.preparePrompt(...args);

  function closeSessionEventStream(sessionId) {
    const stream = agentEventStreams.get(sessionId);
    if (!stream) {
      return;
    }
    stream.source.close();
    agentEventStreams.delete(sessionId);
    if (runtimeState.eventSource === stream.source) {
      runtimeState.eventSource = null;
    }
  }

  function replaceAgentEventSource(sessionId = "") {
    agentEventStreamVersion += 1;
    if (sessionId) {
      closeSessionEventStream(sessionId);
      return agentEventStreamVersion;
    }
    for (const streamSessionId of Array.from(agentEventStreams.keys())) {
      closeSessionEventStream(streamSessionId);
    }
    if (runtimeState.eventSource && typeof runtimeState.eventSource.close === "function") {
      runtimeState.eventSource.close();
      runtimeState.eventSource = null;
    }
    return agentEventStreamVersion;
  }

  function isCurrentSessionEventSource(sessionId, source, version) {
    const stream = agentEventStreams.get(sessionId);
    return Boolean(
      stream &&
      stream.source === source &&
      stream.version === version &&
      version <= agentEventStreamVersion
    );
  }

  function isCurrentLegacyAgentEventSource(source, version) {
    return version === agentEventStreamVersion && runtimeState.eventSource === source;
  }

  function appendSessionMessage(sessionId, text, className = "") {
    appendAgentOutput(`${text}\n`, sessionId, className);
  }

  function handleSessionEvent(sessionId, payload) {
    const session = runtimeState.agentSessions.find(
      (candidate) => candidate.session_id === sessionId,
    );
    if (payload.type === "output") {
      const outputText = runtimeState.terminal
        ? payload.terminal || payload.text || ""
        : payload.text || "";
      appendAgentOutput(outputText, sessionId);
    } else if (payload.type === "system") {
      appendSessionMessage(sessionId, payload.text, "system");
    } else if (payload.type === "error") {
      appendSessionMessage(sessionId, payload.text, "error");
    } else if (payload.type === "completed") {
      appendSessionMessage(
        sessionId,
        `\nprocess exited with code ${payload.returncode}`,
        "system",
      );
      if (session && session.kind === "requirements") {
        refreshArtifactPreview();
      }
      if (session && !session.interactive) {
        closeProgressEventStream();
      }
      refreshProject();
    }
  }

  function ensureSessionEventStream(sessionId) {
    if (!sessionId || agentEventStreams.has(sessionId) || !runtimeState.contextId) {
      return;
    }
    const source = runtimeApi.http.eventSource(
      `/api/sessions/events?session_id=${encodeURIComponent(sessionId)}`,
    );
    agentEventStreamVersion += 1;
    const version = agentEventStreamVersion;
    agentEventStreams.set(sessionId, { source, version });
    if (runtimeState.selectedSessionId === sessionId) {
      runtimeState.eventSource = source;
    }
    source.addEventListener("agent-event", (event) => {
      if (!isCurrentSessionEventSource(sessionId, source, version)) {
        return;
      }
      const payload = JSON.parse(event.data);
      handleSessionEvent(sessionId, payload);
    });
    source.onerror = () => {};
  }

  function ensureRunningSessionStreams() {
    for (const session of runtimeState.agentSessions) {
      if (sessionIsRunning(session)) {
        ensureSessionEventStream(session.session_id);
      }
    }
  }

  function agentInputState() {
    return {
      sessionId: runtimeState.selectedSessionId || "",
      value: runtimeApi.elements.agentInput.value,
    };
  }

  function publishAgentInputState() {
    if (inputPaneSync) {
      inputPaneSync.publish(agentInputState());
    }
  }

  async function applySharedAgentInputState(state) {
    if (!state || typeof state.value !== "string") {
      return;
    }
    const sessionId = String(state.sessionId || "");
    const previousSessionId = runtimeState.selectedSessionId || "";
    if (previousSessionId) {
      inputDrafts.set(previousSessionId, runtimeApi.elements.agentInput.value);
    }
    if (sessionId && sessionId !== previousSessionId) {
      await selectAgentSession(sessionId);
    }
    if (sessionId) {
      inputDrafts.set(sessionId, state.value);
    }
    runtimeApi.elements.agentInput.value = state.value;
  }

  async function selectAgentInputSession(sessionId) {
    const previousSessionId = runtimeState.selectedSessionId || "";
    if (previousSessionId) {
      inputDrafts.set(previousSessionId, runtimeApi.elements.agentInput.value);
    }
    await selectAgentSession(sessionId);
    runtimeApi.elements.agentInput.value = inputDrafts.get(sessionId) || "";
    publishAgentInputState();
  }

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
      return runtimeState.agentSessions.find((session) => session.session_id === runtimeState.selectedSessionId) || null;
    }

    function sessionIsRunning(session) {
      return session && session.status === "running";
    }

    function selectedSessionAcceptsInput() {
      const session = selectedSession();
      return Boolean(session && session.interactive && sessionIsRunning(session));
    }

    function selectedInputSession() {
      const session = selectedSession();
      return session && session.interactive && sessionIsRunning(session)
        ? session
        : null;
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
      runtimeApi.elements.agentSessionIndicator.className = className;
      runtimeApi.elements.agentSessionIndicator.title = session
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
      return [];
    }

    function serviceSessionDisplayLabel(session) {
      const baseLabel = agentSessionDisplayLabel(session);
      const project = String(session.active_project_root || "").split("/").filter(Boolean).pop();
      return project ? `${project}: ${baseLabel}` : baseLabel;
    }

    function renderSessionSwitcher() {
      runtimeApi.elements.sessionSwitcher.replaceChildren();
      const remoteSessions = attachableServiceSessions();
      if (runtimeState.agentSessions.length === 0 && remoteSessions.length === 0) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "No streams";
        runtimeApi.elements.sessionSwitcher.append(option);
        runtimeApi.elements.sessionSwitcher.disabled = true;
        updateSessionIndicator(null);
        return;
      }
      if (runtimeState.agentSessions.length === 0 && remoteSessions.length > 0) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "Attach service stream...";
        runtimeApi.elements.sessionSwitcher.append(option);
      }
      const localParent = runtimeState.agentSessions.length > 0
        ? document.createElement("optgroup")
        : runtimeApi.elements.sessionSwitcher;
      if (runtimeState.agentSessions.length > 0) {
        localParent.label = "Current workspace";
        runtimeApi.elements.sessionSwitcher.append(localParent);
      }
      for (const session of runtimeState.agentSessions) {
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
        runtimeApi.elements.sessionSwitcher.append(remoteParent);
      }
      runtimeApi.elements.sessionSwitcher.disabled = false;
      if (!runtimeState.agentSessions.some((session) => session.session_id === runtimeState.selectedSessionId)) {
        const selected = runtimeState.agentSessions.find((session) => session.selected) || runtimeState.agentSessions[0];
        runtimeState.selectedSessionId = selected ? selected.session_id : "";
      }
      runtimeApi.elements.sessionSwitcher.value = runtimeState.selectedSessionId;
      updateSessionIndicator(selectedSession());
      ensureRunningSessionStreams();
      ensureSelectedSessionStream();
    }

    function selectAgentSessionLocally(sessionId, sessions = null) {
      if (Array.isArray(sessions)) {
        runtimeState.agentSessions = sessions;
      }
      runtimeState.selectedSessionId = sessionId;
      runtimeApi.elements.agentInput.value = inputDrafts.get(sessionId) || "";
      syncOpenDocumentTargetsFromSessions();
      renderSessionSwitcher();
      const session = selectedSession();
      runtimeState.activeAgentKind = session ? session.kind || "" : "";
      const documentTarget = documentTargetForSession(session);
      if (documentTarget) {
        showDocumentPreview(documentTarget);
      }
      connectSessionEvents(runtimeState.selectedSessionId);
      updateAgentControls();
      sendTerminalResize();
    }

    function ensureSelectedSessionStream(options = {}) {
      if (
        !runtimeState.selectedSessionId ||
        agentEventStreams.has(runtimeState.selectedSessionId)
      ) {
        return;
      }
      const runningOnly = options.runningOnly !== false;
      window.setTimeout(() => {
        if (
          !runtimeState.selectedSessionId ||
          agentEventStreams.has(runtimeState.selectedSessionId)
        ) {
          return;
        }
        const session = selectedSession();
        if (!session || (runningOnly && !sessionIsRunning(session))) {
          return;
        }
        connectSessionEvents(runtimeState.selectedSessionId, { ensurePane: false });
        updateAgentControls();
        sendTerminalResize();
      }, 0);
    }

    async function selectAgentSession(sessionId) {
      if (sessionId && sessionId.startsWith("attach:")) {
        await attachAgentSession(sessionId.slice("attach:".length));
        return;
      }
      if (!sessionId) {
        return;
      }
      if (sessionId === runtimeState.selectedSessionId) {
        ensureSelectedSessionStream({ runningOnly: false });
        return;
      }
      const previousSessionId = runtimeState.selectedSessionId || "";
      if (previousSessionId) {
        inputDrafts.set(previousSessionId, runtimeApi.elements.agentInput.value);
      }
      const response = await runtimeApi.http.fetch(contextUrl("/api/sessions/select"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      const payload = await response.json().catch(() => ({ error: "session switch failed" }));
      if (!response.ok) {
        if (
          response.status === 404 &&
          runtimeState.agentSessions.some((session) => session.session_id === sessionId)
        ) {
          selectAgentSessionLocally(sessionId);
          return;
        }
        appendOutput(`${payload.error || "session switch failed"}\n`, "error");
        renderSessionSwitcher();
        return;
      }
      selectAgentSessionLocally(
        payload.selected_session_id || sessionId,
        payload.sessions,
      );
    }

    async function refreshServiceSessions() {
      runtimeState.serviceSessions = [];
      renderSessionSwitcher();
    }

    async function attachAgentSession(sessionId) {
      appendOutput(
        `agent session ${sessionId || ""} belongs to another workspace\n`,
        "error",
      );
      renderSessionSwitcher();
    }

    function connectAgentEvents(kind) {
      const session = runtimeState.agentSessions.find((candidate) => candidate.kind === kind);
      if (session) {
        connectSessionEvents(session.session_id);
        return;
      }
      const streamVersion = replaceAgentEventSource();
      runtimeState.activeAgentKind = kind;
      prepareTerminalStream();
      const source = runtimeApi.http.eventSource(`/api/agents/${kind}/events`);
      runtimeState.eventSource = source;
      source.addEventListener("agent-event", (event) => {
        if (!isCurrentLegacyAgentEventSource(source, streamVersion)) {
          return;
        }
        const payload = JSON.parse(event.data);
        if (payload.type === "output") {
          const outputText = runtimeState.terminal
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
      source.onerror = () => {};
    }

    function connectSessionEvents(sessionId, options = {}) {
      if (!sessionId) {
        return;
      }
      if (options.ensurePane !== false) {
        runtimeApi.layout.ensurePane("agent");
      }
      const previousSessionId = runtimeState.selectedSessionId || "";
      if (previousSessionId && previousSessionId !== sessionId) {
        inputDrafts.set(previousSessionId, runtimeApi.elements.agentInput.value);
      }
      runtimeState.selectedSessionId = sessionId;
      if (previousSessionId !== sessionId) {
        runtimeApi.elements.agentInput.value = inputDrafts.get(sessionId) || "";
      }
      publishAgentInputState();
      const session = selectedSession();
      if (!session) {
        runtimeState.selectedSessionId = "";
        runtimeState.activeAgentKind = "";
        updateAgentControls();
        return;
      }
      runtimeState.activeAgentKind = session ? session.kind || "" : runtimeState.activeAgentKind;
      prepareTerminalStream(sessionId);
      ensureSessionEventStream(sessionId);
      const stream = agentEventStreams.get(sessionId);
      runtimeState.eventSource = stream ? stream.source : null;
    }

    function closeAgentEventStream() {
      replaceAgentEventSource();
    }

    function agentProcessRunning() {
      return runtimeState.agentSessions.some((session) => session.status === "running");
    }

    function updateAgentControls() {
      const acceptsInput = selectedSessionAcceptsInput();
      const session = selectedSession();
      runtimeApi.elements.agentInput.disabled = !acceptsInput;
      runtimeApi.elements.insertFileLink.disabled = !acceptsInput;
      runtimeApi.elements.interruptAgent.disabled = !sessionIsRunning(session);
      runtimeApi.elements.exportAgentOutput.disabled = !session;
      runtimeApi.elements.exportProgressOutput.disabled = !runtimeState.activationRoot;
      if (agentPaneTools) {
        agentPaneTools.refresh();
      }
    }

    function setAgentRunning(kind, isRunning) {
      if (kind === "requirements") {
        runtimeState.requirementsRunning = isRunning;
      } else if (kind === "design") {
        runtimeState.designRunning = isRunning;
      } else if (kind === "design-review") {
        runtimeState.designReviewRunning = isRunning;
        if (!isRunning) {
          runtimeState.designReviewInteractive = false;
        }
      } else if (kind === "documentation") {
        runtimeState.documentationRunning = isRunning;
      } else if (runtimeState.stageRunState[kind]) {
        runtimeState.stageRunState = {
          ...runtimeState.stageRunState,
          [kind]: {
            ...runtimeState.stageRunState[kind],
            running: isRunning,
            started: runtimeState.stageRunState[kind].started || isRunning,
          },
        };
      }
      if (kind === "requirements") {
        if (isRunning) {
          if (!runtimeState.manualArtifactPreview) {
            showArtifactPreview("requirements");
          }
        } else {
          closeArtifactEventStream();
          refreshArtifactPreview();
        }
      }
      if (isRunning) {
        runtimeState.activeAgentKind = kind;
      } else if (runtimeState.activeAgentKind === kind) {
        runtimeState.activeAgentKind = "";
      }
      updateAgentControls();
      runtimeApi.workflows.updateMenus();
    }

    async function sendMessage() {
      const session = selectedInputSession();
      if (!session) {
        return;
      }
      if (runtimeState.slashCommandMode) {
        sendTerminalKey("enter");
        finishSlashCommandMode();
        return;
      }
      const message = runtimeApi.elements.agentInput.value;
      if (!message.trim()) {
        return;
      }
      runtimeApi.elements.agentInput.value = "";
      publishAgentInputState();
      const response = await runtimeApi.http.fetch(contextUrl("/api/sessions/message"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: session.session_id,
          message: creativePromptMessage(message),
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ error: "send failed" }));
        appendOutput(`${payload.error || "send failed"}\n`, "error");
      }
    }

    function queueTerminalInput(task) {
      const next = runtimeState.terminalInputQueue.catch(() => {}).then(task);
      runtimeState.terminalInputQueue = next.catch(() => {});
      return next;
    }

    function sendTerminalKey(key) {
      const session = selectedInputSession();
      if (!session) {
        return Promise.resolve();
      }
      return queueTerminalInput(async () => {
        const response = await runtimeApi.http.fetch(contextUrl("/api/sessions/key"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: session.session_id, key }),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({ error: "send failed" }));
          appendOutput(`${payload.error || "send failed"}\n`, "error");
        }
      });
    }

    function sendTerminalRaw(data) {
      const session = selectedInputSession();
      if (!session || !data) {
        return Promise.resolve();
      }
      return queueTerminalInput(async () => {
        const response = await runtimeApi.http.fetch(contextUrl("/api/sessions/raw"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: session.session_id, data }),
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
        if (!runtimeApi.elements.agentInput.value.trimStart().startsWith("/")) {
          runtimeState.slashCommandMode = false;
        }
      }, 0);
    }

    function finishSlashCommandMode() {
      runtimeState.slashCommandMode = false;
      runtimeApi.elements.agentInput.value = "";
      publishAgentInputState();
    }

    function handleSlashCommandInput(event) {
      if (
        !runtimeState.slashCommandMode &&
        printableInputEvent(event) &&
        event.key === "/" &&
        runtimeApi.elements.agentInput.value.trim().length === 0
      ) {
        runtimeState.slashCommandMode = true;
        sendTerminalRaw(event.key);
        return true;
      }
      if (!runtimeState.slashCommandMode) {
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
      if (runtimeApi.elements.agentInput.value.length > 0) {
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
      const session = selectedSession();
      if (!sessionIsRunning(session)) {
        return;
      }
      const response = await runtimeApi.http.fetch(contextUrl("/api/sessions/interrupt"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session.session_id }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ error: "interrupt failed" }));
        appendOutput(`${payload.error || "interrupt failed"}\n`, "error");
      }
    }

    async function terminateActiveAgent() {
      const session = selectedSession();
      if (!session) {
        appendOutput("select an agent session first\n", "error");
        return false;
      }
      const actionLabel = sessionIsRunning(session) ? "Terminate" : "Close";
      if (!window.confirm(`${actionLabel} ${agentSessionDisplayLabel(session)}?`)) {
        return false;
      }
      const response = await runtimeApi.http.fetch(contextUrl("/api/sessions/terminate"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session.session_id }),
      });
      const payload = await response.json().catch(() => ({ error: "terminate failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "terminate failed"}\n`, "error");
        return false;
      }
      closeSessionEventStream(session.session_id);
      if (Array.isArray(payload.sessions)) {
        runtimeState.agentSessions = payload.sessions;
      } else {
        runtimeState.agentSessions = runtimeState.agentSessions.filter(
          (candidate) => candidate.session_id !== session.session_id,
        );
      }
      runtimeState.selectedSessionId = payload.selected_session_id || "";
      syncOpenDocumentTargetsFromSessions();
      renderSessionSwitcher();
      updateAgentControls();
      refreshProject();
      return true;
    }

    function mountAgentPaneTools(runtime) {
      const element = runtime.elements;
      if (
        !window.ElectroBoyPaneTools ||
        !window.ElectroBoyAgentPaneTools ||
        !element.agentOutputPane ||
        !element.agentPaneToolsShelf ||
        !element.agentPaneToolsContent ||
        !element.agentPaneToolsToggle ||
        !element.closeAgentPaneTools ||
        !element.agentPaneToolsResizeHandle
      ) {
        return;
      }
      const controller = window.ElectroBoyPaneTools.create({
        host: element.agentOutputPane,
        shelf: element.agentPaneToolsShelf,
        content: element.agentPaneToolsContent,
        toggleButton: element.agentPaneToolsToggle,
        closeButton: element.closeAgentPaneTools,
        resizeHandle: element.agentPaneToolsResizeHandle,
        storageKey: `electroboy.agentPaneTools.${runtimeState.contextId || "default"}`,
        defaultOpen: false,
        side: "right",
        onResize: runtime.terminals.fitAll,
      });
      agentPaneTools = window.ElectroBoyAgentPaneTools.mount({
        controller,
        getSession: selectedSession,
        getTarget: () => ({
          canPop: !runtime.layout.isPopped("agent"),
          canClosePane: runtime.layout.hasPane("agent"),
        }),
        actions: {
          export: exportAgentSession,
          interrupt: interruptActiveAgent,
          terminate: terminateActiveAgent,
          pop: () => runtime.layout.popOutPane("agent"),
          closePane: () => runtime.layout.closePane("agent"),
        },
        controls: {
          font: element.agentFontControls,
          exportButton: element.exportAgentOutput,
          popButton: element.popoutAgentPane,
        },
      });
    }


  function mount(runtime) {
    bindRuntime(runtime);
    const element = runtime.elements;
    mountAgentPaneTools(runtime);
    inputPaneSync = runtime.sharedPanes.connect("input", {
      snapshot: agentInputState,
      receive: (state) => {
        inputSyncQueue = inputSyncQueue
          .catch(() => {})
          .then(() => applySharedAgentInputState(state))
          .catch((error) => {
            runtime.notifications.appendOutput(`input synchronization failed: ${error}\n`, "error");
          });
      },
    });
    window.addEventListener("pagehide", () => inputPaneSync.close(), { once: true });
    const shortcutController = window.ElectroBoyInputShortcut.bindRecorder(
      runtime.input.sendShortcut,
    );
    element.sessionSwitcher.addEventListener("change", () => {
      selectAgentInputSession(element.sessionSwitcher.value).catch((error) => {
        runtime.notifications.appendOutput(
          `session switch failed: ${error}\n`,
          "error",
        );
      });
    });
    element.exportAgentOutput.addEventListener("click", () => {
      exportAgentSession().catch((error) => {
        runtime.notifications.appendOutput(`export failed: ${error}\n`, "error");
      });
    });
    element.interruptAgent.addEventListener(
      "click",
      () => interruptActiveAgent(),
    );
    element.agentInput.addEventListener("keydown", (event) => {
      if (handleSlashCommandInput(event)) {
        return;
      }
      if (shortcutController.matches(event)) {
        event.preventDefault();
        if (element.agentInput.value.trim()) {
          sendMessage();
        } else {
          sendTerminalKey("enter");
        }
        return;
      }
      const terminalKey = terminalKeyForInputEvent(event);
      if (terminalKey) {
        event.preventDefault();
        sendTerminalKey(terminalKey);
        return;
      }
    });
    element.agentInput.addEventListener("input", () => {
      const sessionId = runtimeState.selectedSessionId || "";
      if (sessionId) {
        inputDrafts.set(sessionId, element.agentInput.value);
      }
      publishAgentInputState();
    });
  }

  window.ElectroBoyFrontend.registerModule({
    id: "agent-sessions",
    label: "Agent Sessions",
    capabilities: [
      "session-switching",
      "terminal-input",
      "session-export",
      "configurable-send-shortcut",
    ],
    actions: {
      sessionExportName: (runtime, ...args) => invoke(runtime, sessionExportName, args),
      exportAgentSession: (runtime, ...args) => invoke(runtime, exportAgentSession, args),
      selectedSession: (runtime, ...args) => invoke(runtime, selectedSession, args),
      sessionIsRunning: (runtime, ...args) => invoke(runtime, sessionIsRunning, args),
      selectedSessionAcceptsInput: (runtime, ...args) => invoke(runtime, selectedSessionAcceptsInput, args),
      selectedInputSession: (runtime, ...args) => invoke(runtime, selectedInputSession, args),
      updateSessionIndicator: (runtime, ...args) => invoke(runtime, updateSessionIndicator, args),
      sessionMetadata: (runtime, ...args) => invoke(runtime, sessionMetadata, args),
      agentSessionDisplayLabel: (runtime, ...args) => invoke(runtime, agentSessionDisplayLabel, args),
      attachableServiceSessions: (runtime, ...args) => invoke(runtime, attachableServiceSessions, args),
      serviceSessionDisplayLabel: (runtime, ...args) => invoke(runtime, serviceSessionDisplayLabel, args),
      renderSessionSwitcher: (runtime, ...args) => invoke(runtime, renderSessionSwitcher, args),
      selectAgentSession: (runtime, ...args) => invoke(runtime, selectAgentSession, args),
      refreshServiceSessions: (runtime, ...args) => invoke(runtime, refreshServiceSessions, args),
      attachAgentSession: (runtime, ...args) => invoke(runtime, attachAgentSession, args),
      connectAgentEvents: (runtime, ...args) => invoke(runtime, connectAgentEvents, args),
      connectSessionEvents: (runtime, ...args) => invoke(runtime, connectSessionEvents, args),
      closeAgentEventStream: (runtime, ...args) => invoke(runtime, closeAgentEventStream, args),
      agentProcessRunning: (runtime, ...args) => invoke(runtime, agentProcessRunning, args),
      updateAgentControls: (runtime, ...args) => invoke(runtime, updateAgentControls, args),
      setAgentRunning: (runtime, ...args) => invoke(runtime, setAgentRunning, args),
      sendMessage: (runtime, ...args) => invoke(runtime, sendMessage, args),
      queueTerminalInput: (runtime, ...args) => invoke(runtime, queueTerminalInput, args),
      sendTerminalKey: (runtime, ...args) => invoke(runtime, sendTerminalKey, args),
      sendTerminalRaw: (runtime, ...args) => invoke(runtime, sendTerminalRaw, args),
      printableInputEvent: (runtime, ...args) => invoke(runtime, printableInputEvent, args),
      slashCommandTerminalKeyForInputEvent: (runtime, ...args) => invoke(runtime, slashCommandTerminalKeyForInputEvent, args),
      refreshSlashCommandModeAfterEdit: (runtime, ...args) => invoke(runtime, refreshSlashCommandModeAfterEdit, args),
      finishSlashCommandMode: (runtime, ...args) => invoke(runtime, finishSlashCommandMode, args),
      handleSlashCommandInput: (runtime, ...args) => invoke(runtime, handleSlashCommandInput, args),
      terminalKeyForInputEvent: (runtime, ...args) => invoke(runtime, terminalKeyForInputEvent, args),
      interruptActiveAgent: (runtime, ...args) => invoke(runtime, interruptActiveAgent, args),
      terminateActiveAgent: (runtime, ...args) => invoke(runtime, terminateActiveAgent, args),
    },
    mount,
  });
})();
