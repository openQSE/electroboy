(function () {
  "use strict";

  const WORKFLOW_ID = "creative-writing";
  const CREATIVE_CORKBOARD_SUFFIX = ".corkboard.json";
  let runtimeApi = null;
  let scratchPad = null;
  let activationRoot = "";
  let activeProjectRoot = "";
  let contextId = "";
  let agentSessions = [];
  let artifactPaneRequested = false;
  let creativeTreePayload = null;
  let creativeActiveDocument = "";
  let creativeActiveFolder = "";
  let creativeEditingPath = "";
  let creativeEditingType = "";
  let expandedCreativeFolders = new Set();
  let restoredScratchContextId = "";
  let creativeScratchSaveTimer = null;
  let creativeProjectActionsExpanded = false;
  let creativeAgentActionsExpanded = false;
  let creativeSessionDialog = null;

  function creativePaneKinds(layout, result = []) {
    if (!layout || layout.type === "leaf") {
      result.push(String((layout && layout.kind) || "empty"));
      return result;
    }
    creativePaneKinds(layout.first, result);
    creativePaneKinds(layout.second, result);
    return result;
  }

  function migratePaneLayout(layout) {
    const kinds = creativePaneKinds(layout).sort();
    return kinds.length === 3 &&
      kinds.join(",") === "agent,scratch,status";
  }

  function bindRuntime(runtime) {
    runtimeApi = runtime;
    const state = runtime.getState();
    scratchPad = runtime.elements.scratchPad;
    activationRoot = state.activationRoot || "";
    activeProjectRoot = state.activeProjectRoot || "";
    contextId = state.contextId || "";
    agentSessions = Array.isArray(state.agentSessions) ? state.agentSessions : [];
    artifactPaneRequested = Boolean(state.artifactPaneRequested);
    creativeTreePayload = state.creativeTreePayload || null;
    creativeActiveDocument = state.creativeActiveDocument || "";
    creativeActiveFolder = state.creativeActiveFolder || "";
    creativeEditingPath = state.creativeEditingPath || "";
    creativeEditingType = state.creativeEditingType || "";
    expandedCreativeFolders = state.expandedCreativeFolders instanceof Set
      ? state.expandedCreativeFolders
      : new Set(state.expandedCreativeFolders || []);
  }

  function resetCreativeWorkflowState() {
    if (creativeScratchSaveTimer) {
      window.clearTimeout(creativeScratchSaveTimer);
      creativeScratchSaveTimer = null;
    }
    activationRoot = "";
    activeProjectRoot = "";
    contextId = "";
    agentSessions = [];
    artifactPaneRequested = false;
    creativeTreePayload = null;
    creativeActiveDocument = "";
    creativeActiveFolder = "";
    creativeEditingPath = "";
    creativeEditingType = "";
    expandedCreativeFolders = new Set();
    restoredScratchContextId = "";
    creativeProjectActionsExpanded = false;
    creativeAgentActionsExpanded = false;
    creativeRecentProjectsExpanded = false;
    if (creativeSessionDialog) {
      creativeSessionDialog.remove();
      creativeSessionDialog = null;
    }
    if (runtimeApi) {
      runtimeApi.updateState({
        artifactPaneRequested: false,
        creativeTreePayload: null,
        creativeActiveDocument: "",
        creativeActiveFolder: "",
        creativeEditingPath: "",
        creativeEditingType: "",
        expandedCreativeFolders,
      });
    }
  }

  function publishState() {
    runtimeApi.updateState({
      artifactPaneRequested,
      creativeTreePayload,
      creativeActiveDocument,
      creativeActiveFolder,
      creativeEditingPath,
      creativeEditingType,
      expandedCreativeFolders,
    });
  }

  function invoke(runtime, handler, args) {
    bindRuntime(runtime);
    return handler(...args);
  }

  function contextUrl(path) {
    return runtimeApi.http.contextUrl(path);
  }

  function appendOutput(text, kind) {
    runtimeApi.notifications.appendOutput(text, kind);
  }

  function updateProjectState(payload) {
    runtimeApi.project.update(payload);
    bindRuntime(runtimeApi);
  }

  function payloadWithCreativeSession(payload) {
    if (!payload || typeof payload !== "object" || !payload.session_id) {
      return payload;
    }
    const sessionId = String(payload.session_id || "");
    const sessions = Array.isArray(payload.sessions)
      ? [...payload.sessions]
      : [];
    if (!sessions.some((session) => session.session_id === sessionId)) {
      sessions.unshift({
        session_id: sessionId,
        kind: WORKFLOW_ID,
        label: "creative writing agent",
        status: payload.status || "running",
        interactive: true,
        selected: true,
        command: Array.isArray(payload.command) ? payload.command : [],
        metadata: {},
      });
    }
    return {
      ...payload,
      sessions,
      selected_session_id: sessionId,
    };
  }

  function hideStageMenus() {
    runtimeApi.ui.hideStageMenus();
  }

  function basename(path) {
    return runtimeApi.paths.basename(path);
  }

  function setAgentInputVisible(visible) {
    runtimeApi.ui.setAgentInputVisible(visible);
  }

  function showProgressPane(visible) {
    runtimeApi.layout.showProgressPane(visible);
  }

  function clearAgentOutput() {
    runtimeApi.agent.clearOutput();
  }

  function closeAgentEventStream() {
    return runtimeApi.modules.invoke("agent-sessions", "closeAgentEventStream");
  }

  function connectSessionEvents(sessionId) {
    return runtimeApi.modules.invoke(
      "agent-sessions",
      "connectSessionEvents",
      sessionId,
    );
  }

  function renderSessionSwitcher() {
    return runtimeApi.modules.invoke("agent-sessions", "renderSessionSwitcher");
  }

  function sendTerminalResize() {
    runtimeApi.agent.sendResize();
  }

  function applyOutputPaneVisibility() {
    runtimeApi.ui.applyOutputPaneVisibility();
  }

  function creativeModeActive() {
    return runtimeApi.getState().workflowMode === WORKFLOW_ID;
  }

  function recentProjectsForWorkflow() {
    return runtimeApi.recent.list();
  }

  function recentProjectLabel(project) {
    return runtimeApi.recent.label(project);
  }

  async function openRecentProject(project) {
    const path = String((project && project.path) || "").trim();
    if (!path) {
      return;
    }
    const response = await runtimeApi.http.fetch(contextUrl("/api/creative/project/open"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    const payload = await response
      .json()
      .catch(() => ({ error: "project update failed" }));
    if (!response.ok) {
      throw new Error(payload.error || "project update failed");
    }
    recordProjectStatusMessage(
      `${payload.status}: ${payload.activation_root || payload.active_project_root || path}`,
    );
    updateProjectState(payload);
  }

  function recordProjectStatusMessage(message) {
    runtimeApi.project.recordStatus(message);
  }

  function renderProjectStatus(runtime) {
    bindRuntime(runtime);
    const lines = [];
    if (activeProjectRoot || activationRoot) {
      lines.push(`project: ${activeProjectRoot || activationRoot}`);
    } else {
      lines.push("no active project");
    }
    if (creativeActiveDocument) {
      lines.push(`document: ${creativeActiveDocument}`);
    } else if (creativeActiveFolder) {
      lines.push(`folder: ${creativeActiveFolder}`);
    }
    const messages = runtime.project.statusMessages();
    if (messages.length > 0) {
      lines.push("", ...messages.slice(-12));
    }
    runtime.project.renderStatus(lines);
    return true;
  }

  function restoreWorkflowScratchPad(runtime) {
    bindRuntime(runtime);
    loadCreativeScratchPad();
    return true;
  }

  function saveWorkflowScratchPad(runtime) {
    bindRuntime(runtime);
    queueCreativeScratchPadSave();
    return true;
  }

  function projectChanged(runtime, _payload, options = {}) {
    bindRuntime(runtime);
    applyCreativeWorkspace();
    if (!options.deferWorkspaceInit) {
      ensureCreativeWorkspaceLoaded();
    }
    return true;
  }

  function handleWindowMessage(runtime, data) {
    bindRuntime(runtime);
    if (data.type === "corkboard-title-changed" && data.board_path) {
      const entry = findCreativeEntry(
        creativeTreePayload && creativeTreePayload.entries,
        data.board_path,
      );
      if (entry && entry.corkboard) {
        entry.title = String(data.title || "Untitled corkboard");
        renderCreativeTree();
      }
      return true;
    }
    if (
      !["electroboy-corkboard-open", "electroboy-creative-open"].includes(data.type) ||
      !data.path ||
      (data.provider && data.provider !== "creative-files")
    ) {
      return false;
    }
    if (data.entry_type === "directory") {
      selectFolder(runtime, data.path);
    } else if (data.entry_type === "corkboard") {
      selectCorkboard(runtime, data.path, { title: data.title || "" });
    } else {
      selectDocument(runtime, data.path);
    }
    return true;
  }

  function projectEndpoint(_runtime, mode) {
    if (mode === "open") {
      return "/api/creative/project/open";
    }
    if (mode === "new") {
      return "/api/creative/project/new";
    }
    return "";
  }

  function hideArtifactPreview() {
    return runtimeApi.modules.invoke("documents", "hideArtifactPreview");
  }

  let creativeProjectMenuButton = null;
  let creativeProjectActions = null;
  let creativeOpenProject = null;
  let creativeNewProject = null;
  let creativeWorkspace = null;
  let creativeRecentProjectsButton = null;
  let creativeRecentProjects = null;
  let creativeCloseProject = null;
  let creativeActiveProjectSection = null;
  let creativeProjectName = null;
  let creativeAgentMenuButton = null;
  let creativeAgentActions = null;
  let creativeStartAgent = null;
  let creativeRecentProjectsExpanded = false;

  function renderNavigation(container, runtime) {
    bindRuntime(runtime);
    container.innerHTML = `
      <section class="creative-binder" aria-label="Creative writing binder">
        <div class="creative-section">
          <button class="stage-action-stage" type="button" aria-expanded="false"
                  data-creative-control="project-menu">
            <span class="stage-action-label">Project</span>
            <span class="stage-action-chevron" aria-hidden="true"></span>
          </button>
          <div class="stage-action-list" role="group" hidden
               data-creative-control="project-actions">
            <button class="stage-action-button" type="button"
                    data-creative-control="open-project">Open</button>
            <button class="stage-action-button" type="button"
                    data-creative-control="new-project">New</button>
            <button class="stage-action-button" type="button"
                    data-creative-control="workspace">Workspace</button>
            <div class="stage-action-subgroup">
              <button class="stage-action-subgroup-trigger" type="button"
                      aria-expanded="false"
                      title="Open a recently used project."
                      data-creative-control="recent-projects-menu">
                <span class="stage-action-label">Recent projects</span>
                <span class="stage-action-chevron" aria-hidden="true"></span>
              </button>
              <div class="stage-action-subgroup-list" role="group" hidden
                   data-creative-control="recent-projects"></div>
            </div>
            <button class="stage-action-button" type="button" disabled
                    data-creative-control="close-project">Close</button>
          </div>
        </div>
        <div class="creative-active-project" hidden
             data-creative-control="active-project">
          <div class="creative-divider" aria-hidden="true"></div>
          <div class="creative-project-name" data-creative-control="project-name"></div>
          <div class="creative-section">
            <button class="stage-action-stage" type="button" aria-expanded="false"
                    data-creative-control="agent-menu">
              <span class="stage-action-label">Agent</span>
              <span class="stage-action-chevron" aria-hidden="true"></span>
            </button>
            <div class="stage-action-list" role="group" hidden
                 data-creative-control="agent-actions">
              <button class="stage-action-button primary" type="button" disabled
                      data-creative-control="start-agent">Start</button>
            </div>
          </div>
          <div class="creative-tree" role="tree" data-creative-control="tree"></div>
        </div>
      </section>
    `;
    const find = (name) => container.querySelector(`[data-creative-control="${name}"]`);
    creativeProjectMenuButton = find("project-menu");
    creativeProjectActions = find("project-actions");
    creativeOpenProject = find("open-project");
    creativeNewProject = find("new-project");
    creativeWorkspace = find("workspace");
    creativeRecentProjectsButton = find("recent-projects-menu");
    creativeRecentProjects = find("recent-projects");
    creativeCloseProject = find("close-project");
    creativeActiveProjectSection = find("active-project");
    creativeProjectName = find("project-name");
    creativeAgentMenuButton = find("agent-menu");
    creativeAgentActions = find("agent-actions");
    creativeStartAgent = find("start-agent");
    runtime.elements.creativeTree = find("tree");

    creativeProjectMenuButton.addEventListener("click", () => {
      toggleCreativeActionGroup("project");
    });
    creativeAgentMenuButton.addEventListener("click", () => {
      toggleCreativeActionGroup("agent");
    });
    creativeRecentProjectsButton.addEventListener("click", () => {
      toggleCreativeActionGroup("recent-projects");
    });
    creativeOpenProject.addEventListener("click", () => {
      runtime.modules.invoke("file-browser", "openProjectBrowser", "open", true);
    });
    creativeNewProject.addEventListener("click", () => {
      runtime.modules.invoke("file-browser", "openProjectBrowser", "new", true);
    });
    creativeWorkspace.addEventListener("click", () => {
      runtime.workspaces.openSelector();
    });
    creativeCloseProject.addEventListener("click", () => {
      runtime.project.deactivate();
    });
    creativeStartAgent.addEventListener("click", () => {
      startAgent(runtime).catch((error) => {
        appendOutput(`agent start failed: ${error.message || error}\n`, "error");
      });
    });
    updateCreativeBinderActions();
  }

  function refreshNavigation(runtime) {
    bindRuntime(runtime);
    if (creativeProjectMenuButton) {
      updateCreativeBinderActions();
    }
  }

  function activate(runtime) {
    bindRuntime(runtime);
    runtime.ui.setWorkflowSideSheetCollapsed(false);
    applyCreativeWorkspace();
    runtime.scratch.restore();
    refreshCreativeBinder();
  }

  function deactivate(runtime) {
    bindRuntime(runtime);
    runtime.elements.creativeTree = null;
    creativeProjectMenuButton = null;
    creativeProjectActions = null;
    creativeOpenProject = null;
    creativeNewProject = null;
    creativeWorkspace = null;
    creativeRecentProjectsButton = null;
    creativeRecentProjects = null;
    creativeCloseProject = null;
    creativeActiveProjectSection = null;
    creativeProjectName = null;
    creativeAgentMenuButton = null;
    creativeAgentActions = null;
    creativeStartAgent = null;
    resetCreativeWorkflowState();
  }

  async function startAgent(runtime, options = {}) {
    bindRuntime(runtime);
    const state = runtime.getState();
    if (!state.activeProjectRoot || !state.contextId) {
      appendOutput("activate a project first\n", "error");
      return;
    }
    const scope = options.scope === "document" ? "document" : "general";
    const documentPath = String(
      options.documentPath
        || (scope === "document" ? state.creativeActiveDocument : "")
        || "",
    );
    const target = options.activeTarget || (
      scope === "document" && documentPath
        ? { type: "document", path: documentPath }
        : null
    );
    const explicitSessionId = String(options.sessionId || "").trim();
    const explicitProviderSessionId = String(options.providerSessionId || "").trim();
    let choice = null;
    if (explicitSessionId || explicitProviderSessionId) {
      choice = {
        sessionId: explicitSessionId,
        providerSessionId: explicitProviderSessionId,
        startNew: false,
      };
    } else {
      try {
        choice = await chooseCreativeAgentSession({
          scope,
          documentPath,
          activeTarget: target,
        });
      } catch (error) {
        appendOutput(`${error.message || "session history failed"}\n`, "error");
        return;
      }
    }
    if (!choice) {
      return null;
    }
    hideStageMenus();
    closeAgentEventStream();
    showProgressPane(false);
    setAgentInputVisible(true);
    clearAgentOutput();
    runtime.elements.agentInput.disabled = false;
    runtime.elements.agentInput.focus();
    appendOutput(creativeAgentCommandLine(choice), "system");
    const response = await runtime.http.fetch(contextUrl("/api/creative/agent/start"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        active_document: scope === "document" ? documentPath : "",
        active_target: target || null,
        scope,
        session_id: choice.sessionId || "",
        provider_session_id: choice.providerSessionId || "",
        start_new: Boolean(choice.startNew),
      }),
    });
    const payload = await response
      .json()
      .catch(() => ({ error: "start failed" }));
    if (!response.ok) {
      appendOutput(`${payload.error || "start failed"}\n`, "error");
      return;
    }
    const startPayload = payloadWithCreativeSession(payload);
    updateProjectState(startPayload);
    const sessionId = startPayload.session_id || runtime.getState().selectedSessionId;
    renderSessionSwitcher();
    connectSessionEvents(sessionId);
    sendTerminalResize();
    return startPayload;
  }

  function selectFolder(runtime, path) {
    bindRuntime(runtime);
    if (!path) {
      return;
    }
    runtime.updateState({
      creativeActiveFolder: path,
      creativeActiveDocument: "",
    });
    showCreativeCorkboard(path);
    renderCreativeTree();
    renderProjectStatus(runtime);
  }

  function selectCorkboard(runtime, path, options = {}) {
    bindRuntime(runtime);
    if (!path) {
      return;
    }
    const entry = findCreativeEntry(
      creativeTreePayload && creativeTreePayload.entries,
      path,
    );
    const title = options.title || (
      entry && entry.corkboard ? String(entry.title || "") : ""
    );
    runtime.updateState({
      creativeActiveDocument: path,
      creativeActiveFolder: creativeParentPath(path),
    });
    showCreativeCorkboard(path, {
      freeform: true,
      title,
    });
    renderCreativeTree();
    renderProjectStatus(runtime);
  }

  function showDocument(runtime, path) {
    bindRuntime(runtime);
    if (!path) {
      return;
    }
    const target = {
      label: basename(path),
      path,
    };
    runtime.modules.invoke("documents", "showArtifactPreviews",
      [
        {
          id: "creative-document",
          kind: "document",
          title: target.label,
          target,
          editing: false,
        },
      ],
      { manual: true, stage: WORKFLOW_ID },
    );
  }

  function selectDocument(runtime, path, options = {}) {
    bindRuntime(runtime);
    if (!path) {
      return;
    }
    runtime.updateState({
      creativeActiveDocument: path,
      creativeActiveFolder: creativeParentPath(path),
    });
    showDocument(runtime, path);
    renderCreativeTree();
    renderProjectStatus(runtime);
  }

    function applyCreativeWorkspace() {
      scratchPad.spellcheck = true;
      setAgentInputVisible(true);
      showProgressPane(false);
      if (creativeActiveDocument) {
        if (creativePathIsCorkboard(creativeActiveDocument)) {
          showCreativeCorkboard(creativeActiveDocument, { freeform: true });
        } else {
          showCreativeDocument(creativeActiveDocument);
        }
      } else if (creativeActiveFolder) {
        showCreativeCorkboard(creativeActiveFolder);
      } else {
        artifactPaneRequested = runtimeApi.layout.hasPane("artifact");
        runtimeApi.updateState({ artifactPaneRequested });
        applyOutputPaneVisibility();
      }
    }

    function updateCreativeBinderActions() {
      const hasProject = Boolean(activeProjectRoot);
      creativeOpenProject.disabled = Boolean(activationRoot);
      creativeNewProject.disabled = Boolean(activationRoot);
      creativeCloseProject.disabled = !Boolean(activationRoot);
      creativeActiveProjectSection.hidden = !hasProject;
      creativeProjectName.textContent = hasProject
        ? `Project: ${basename(activeProjectRoot)}`
        : "";
      creativeStartAgent.disabled = !hasProject;
      updateCreativeActionGroup(
        creativeProjectActions,
        creativeProjectMenuButton,
        creativeProjectActionsExpanded,
      );
      updateCreativeActionGroup(
        creativeAgentActions,
        creativeAgentMenuButton,
        creativeAgentActionsExpanded,
      );
      renderCreativeRecentProjects();
    }

    function renderCreativeRecentProjects() {
      creativeRecentProjects.replaceChildren();
      const entries = recentProjectsForWorkflow();
      updateCreativeActionGroup(
        creativeRecentProjects,
        creativeRecentProjectsButton,
        creativeRecentProjectsExpanded,
      );
      if (entries.length === 0) {
        const empty = document.createElement("button");
        empty.type = "button";
        empty.className = "stage-action-button";
        empty.textContent = "No recent projects";
        empty.disabled = true;
        creativeRecentProjects.append(empty);
        return;
      }
      for (const recent of entries) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "stage-action-button";
        button.textContent = basename(recent.path || recent.label || "Project");
        button.title = recent.path || recentProjectLabel(recent);
        button.disabled = Boolean(activationRoot);
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          openRecentProject(recent).catch((error) => {
            appendOutput(`action failed: ${error}\n`, "error");
          });
        });
        creativeRecentProjects.append(button);
      }
    }

    function updateCreativeActionGroup(actions, button, expanded) {
      actions.hidden = !expanded;
      button.classList.toggle("expanded", expanded);
      button.setAttribute("aria-expanded", expanded ? "true" : "false");
    }

    function toggleCreativeActionGroup(group) {
      if (group === "project") {
        creativeProjectActionsExpanded = !creativeProjectActionsExpanded;
      } else if (group === "agent") {
        creativeAgentActionsExpanded = !creativeAgentActionsExpanded;
      } else if (group === "recent-projects") {
        creativeRecentProjectsExpanded = !creativeRecentProjectsExpanded;
      }
      updateCreativeBinderActions();
    }

    async function refreshCreativeBinder() {
      if (!creativeModeActive()) {
        return;
      }
      updateCreativeBinderActions();
      if (!activeProjectRoot || !contextId) {
        showCreativeTreeMessage("Open or create a project to start writing.");
        return;
      }
      showCreativeTreeMessage("Loading Binder...");
      const response = await fetch(contextUrl("/api/creative/tree"), {
        cache: "no-store",
      });
      const payload = await response.json().catch(() => ({ error: "Binder failed" }));
      if (!response.ok) {
        showCreativeTreeMessage(payload.error || "Binder failed");
        return;
      }
      creativeTreePayload = payload;
      renderCreativeTree();
    }

    function showCreativeTreeMessage(message) {
      publishState();
      return window.ElectroBoyFrontend.invokeModule(
        "binder",
        "showMessage",
        message,
      );
    }

    function renderCreativeTree() {
      publishState();
      return window.ElectroBoyFrontend.invokeModule("binder", "renderTree");
    }

    function showCreativeCorkboard(path, options = {}) {
      publishState();
      return window.ElectroBoyFrontend.invokeModule(
        "corkboard",
        "show",
        path,
        options,
      );
    }

    function selectCreativeFolder(path) {
      return window.ElectroBoyFrontend.invokeWorkflow(
        WORKFLOW_ID,
        "selectFolder",
        path,
      );
    }

    function selectCreativeCorkboard(path) {
      return window.ElectroBoyFrontend.invokeWorkflow(
        WORKFLOW_ID,
        "selectCorkboard",
        path,
      );
    }

    function showCreativeDocument(path) {
      publishState();
      return window.ElectroBoyFrontend.invokeWorkflow(
        WORKFLOW_ID,
        "showDocument",
        path,
      );
    }

    function selectCreativeDocument(path, options = {}) {
      publishState();
      return window.ElectroBoyFrontend.invokeWorkflow(
        WORKFLOW_ID,
        "selectDocument",
        path,
        options,
      );
    }

    function creativeSessionDate(session) {
      const value = String(session.updated_at || session.created_at || "");
      const parsed = new Date(value);
      return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
    }

    function ensureCreativeSessionDialog() {
      if (creativeSessionDialog) {
        return creativeSessionDialog;
      }
      const dialog = document.createElement("dialog");
      dialog.className = "ad-hoc-session-dialog creative-session-dialog";
      dialog.innerHTML = `
        <form method="dialog" class="ad-hoc-session-form">
          <header class="ad-hoc-session-header">
            <div>
              <h2>Start creative agent</h2>
              <p>Start fresh or resume an existing session.</p>
            </div>
            <button
              type="button"
              class="ad-hoc-session-close"
              aria-label="Close"
            >&times;</button>
          </header>
          <fieldset class="ad-hoc-session-options">
            <legend>Session</legend>
            <div class="ad-hoc-session-list"></div>
            <label class="ad-hoc-session-option ad-hoc-session-custom">
              <input type="radio" name="creative-session" value="custom">
              <span class="ad-hoc-session-option-copy">
                <strong>Resume by session id</strong>
                <input
                  class="ad-hoc-session-uuid"
                  type="text"
                  autocomplete="off"
                  spellcheck="false"
                  placeholder="ElectroBoy id or Codex UUID"
                >
              </span>
            </label>
          </fieldset>
          <p class="ad-hoc-session-error" role="alert" hidden></p>
          <footer class="ad-hoc-session-footer">
            <button type="button" class="ad-hoc-session-cancel">Cancel</button>
            <button type="submit" class="ad-hoc-session-submit">Start</button>
          </footer>
        </form>
      `;
      document.body.append(dialog);
      creativeSessionDialog = dialog;
      return dialog;
    }

    function creativeSessionOptionValue(session) {
      const status = String(session.status || "");
      const providerId = String(session.provider_session_id || "");
      const serviceId = String(
        session.electroboy_session_id || session.session_id || "",
      );
      if (status === "running" && serviceId) {
        return `service:${serviceId}`;
      }
      if (providerId) {
        return `provider:${providerId}`;
      }
      return serviceId ? `service:${serviceId}` : "";
    }

    function creativeSessionCanContinue(session) {
      return (
        String(session.status || "") !== "running"
        && session.resumable !== false
      );
    }

    function creativeSessionOption(session, index) {
      const label = document.createElement("label");
      label.className = "ad-hoc-session-option";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "creative-session";
      input.value = creativeSessionOptionValue(session);
      input.id = `creative-session-${index}`;
      const copy = document.createElement("span");
      copy.className = "ad-hoc-session-option-copy";
      const title = document.createElement("strong");
      title.textContent = String(session.title || "Creative session");
      const details = document.createElement("span");
      details.className = "ad-hoc-session-details";
      const date = creativeSessionDate(session);
      const status = String(session.status || "");
      const providerId = String(session.provider_session_id || "");
      const serviceId = String(
        session.electroboy_session_id || session.session_id || "",
      );
      details.textContent = [
        status,
        date,
        providerId || serviceId,
      ].filter(Boolean).join(" · ");
      copy.append(title, details);
      label.append(input, copy);
      return label;
    }

    function creativeSessionQuery({ scope, documentPath, activeTarget }) {
      const params = new URLSearchParams();
      params.set("scope", scope);
      if (documentPath) {
        params.set("active_document", documentPath);
      }
      if (activeTarget && activeTarget.type) {
        params.set("target_type", activeTarget.type);
      }
      if (activeTarget && activeTarget.path) {
        params.set("target_path", activeTarget.path);
      }
      return params.toString();
    }

    function creativeSessionChoice(value, customInput) {
      if (value === "custom") {
        const manualId = customInput.value.trim();
        return manualId ? { sessionId: manualId, startNew: false } : null;
      }
      if (value.startsWith("provider:")) {
        return {
          providerSessionId: value.slice("provider:".length),
          startNew: false,
        };
      }
      if (value.startsWith("service:")) {
        return {
          sessionId: value.slice("service:".length),
          startNew: false,
        };
      }
      return { startNew: true };
    }

    async function chooseCreativeAgentSession(options = {}) {
      const scope = options.scope === "document" ? "document" : "general";
      const query = creativeSessionQuery({
        scope,
        documentPath: options.documentPath || "",
        activeTarget: options.activeTarget || null,
      });
      const sessionPath = query
        ? `/api/creative/agent/sessions?${query}`
        : "/api/creative/agent/sessions";
      const response = await fetch(
        contextUrl(sessionPath),
        { cache: "no-store" },
      );
      const payload = await response.json().catch(() => ({
        error: "session history failed",
      }));
      if (!response.ok) {
        throw new Error(payload.error || "session history failed");
      }
      const dialog = ensureCreativeSessionDialog();
      const heading = dialog.querySelector(".ad-hoc-session-header h2");
      const summary = dialog.querySelector(".ad-hoc-session-header p");
      const list = dialog.querySelector(".ad-hoc-session-list");
      const customInput = dialog.querySelector(".ad-hoc-session-uuid");
      const customRadio = dialog.querySelector('input[value="custom"]');
      const error = dialog.querySelector(".ad-hoc-session-error");
      const submit = dialog.querySelector(".ad-hoc-session-submit");
      const newOption = document.createElement("label");
      newOption.className = "ad-hoc-session-option";
      newOption.innerHTML = `
        <input type="radio" name="creative-session" value="" checked>
        <span class="ad-hoc-session-option-copy">
          <strong>New session</strong>
          <span class="ad-hoc-session-details">
            Start with a clean creative context.
          </span>
        </span>
      `;
      const sessions = Array.isArray(payload.sessions)
        ? payload.sessions.filter(creativeSessionCanContinue)
        : [];
      heading.textContent = scope === "document"
        ? "Start document agent"
        : "Start creative agent";
      summary.textContent = scope === "document" && payload.document_path
        ? `Sessions scoped to ${payload.document_path}.`
        : "General creative sessions for this project.";
      list.replaceChildren(
        newOption,
        ...sessions.map((session, index) => creativeSessionOption(session, index)),
      );
      customInput.value = "";
      error.hidden = true;
      submit.textContent = "Start";
      dialog.querySelector(".ad-hoc-session-options").onchange = (event) => {
        if (event.target.name !== "creative-session") {
          return;
        }
        submit.textContent = event.target.value ? "Resume" : "Start";
        error.hidden = true;
      };
      customInput.onfocus = () => {
        customRadio.checked = true;
        submit.textContent = "Resume";
        error.hidden = true;
      };

      return new Promise((resolve) => {
        const finish = (choice) => {
          dialog.close();
          resolve(choice);
        };
        dialog.querySelector(".ad-hoc-session-close").onclick = () => {
          finish(null);
        };
        dialog.querySelector(".ad-hoc-session-cancel").onclick = () => {
          finish(null);
        };
        dialog.oncancel = (event) => {
          event.preventDefault();
          finish(null);
        };
        dialog.querySelector("form").onsubmit = (event) => {
          event.preventDefault();
          const selected = dialog.querySelector(
            'input[name="creative-session"]:checked',
          );
          const choice = creativeSessionChoice(
            selected ? selected.value : "",
            customInput,
          );
          if (!choice) {
            error.textContent = "Enter a session id.";
            error.hidden = false;
            return;
          }
          finish(choice);
        };
        dialog.showModal();
      });
    }

    function creativeAgentCommandLine(choice) {
      if (choice.providerSessionId) {
        return `$ codex resume ${choice.providerSessionId}\n`;
      }
      if (choice.sessionId) {
        return `$ electroboy session ${choice.sessionId}\n`;
      }
      return "$ codex creative-writing\n";
    }

    function creativeAgentSession(scopeKey = "general") {
      return agentSessions.find((session) => {
        if (session.kind !== WORKFLOW_ID || session.status !== "running") {
          return false;
        }
        const metadata = session.metadata || {};
        const sessionScopeKey = String(
          metadata.creative_scope_key || "general",
        );
        return sessionScopeKey === scopeKey;
      }) || null;
    }

    function creativeAgentRunning() {
      return Boolean(creativeAgentSession());
    }

    function activeCreativeTarget() {
      if (creativeActiveDocument) {
        if (creativePathIsCorkboard(creativeActiveDocument)) {
          return {
            type: "freeform-corkboard",
            path: creativeActiveDocument,
          };
        }
        return {
          type: "document",
          path: creativeActiveDocument,
        };
      }
      if (creativeActiveFolder) {
        return {
          type: "folder-corkboard",
          path: creativeActiveFolder,
        };
      }
      return {
        type: "none",
        path: "",
      };
    }

    function creativeTargetContextLines(target) {
      if (!target || target.type === "none") {
        return ["Active target: none"];
      }
      if (target.type === "document") {
        return [
          "Active target: document",
          `Path: ${target.path}`,
          "Mode: markdown editing",
          "Use the active document as the writing target unless the writer names another file.",
        ];
      }
      if (target.type === "freeform-corkboard") {
        return [
          "Active target: freeform corkboard",
          `Path: ${target.path}`,
          "Mode: arbitrary cards with x/y positions",
          "API guide: docs/corkboard-api.md",
          "Use `electroboy corkboard` commands for card changes.",
          "Do not edit corkboard JSON directly unless the writer explicitly asks.",
        ];
      }
      return [
        "Active target: folder corkboard",
        `Path: ${target.path}`,
        "Mode: folder-backed card ordering and notes",
        "API guide: docs/corkboard-api.md",
        "Use `electroboy corkboard folder` commands for notes and order.",
        "Create, delete, or rename files only when the writer explicitly asks.",
      ];
    }

    function creativePromptMessage(message) {
      if (!creativeModeActive()) {
        return message;
      }
      const target = activeCreativeTarget();
      const contextLines = [
        "[ElectroBoy creative-writing context]",
        ...creativeTargetContextLines(target),
        "Project scratchpad: scratchpad/scratchpad.md",
        "[/ElectroBoy creative-writing context]",
        "",
        message,
      ];
      return contextLines.join("\n");
    }

    async function loadCreativeScratchPad() {
      if (!creativeModeActive() || !activeProjectRoot || !contextId) {
        scratchPad.value = "";
        restoredScratchContextId = contextId;
        return;
      }
      const response = await fetch(contextUrl("/api/creative/scratch"), {
        cache: "no-store",
      });
      const payload = await response.json().catch(() => ({ markdown: "" }));
      scratchPad.value = response.ok ? String(payload.markdown || "") : "";
      restoredScratchContextId = contextId;
    }

    function queueCreativeScratchPadSave() {
      window.clearTimeout(creativeScratchSaveTimer);
      creativeScratchSaveTimer = window.setTimeout(saveCreativeScratchPad, 450);
    }

    async function saveCreativeScratchPad() {
      if (!creativeModeActive() || !activeProjectRoot || !contextId) {
        return;
      }
      await fetch(contextUrl("/api/creative/scratch"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ markdown: scratchPad.value }),
      }).catch(() => {});
    }

    async function initializeCreativeWorkspace() {
      if (!activeProjectRoot || !contextId) {
        return;
      }
      await fetch(contextUrl("/api/creative/init"), { method: "POST" }).catch(() => {});
    }

    async function ensureCreativeWorkspaceLoaded() {
      if (!creativeModeActive() || !activeProjectRoot || !contextId) {
        return;
      }
      await refreshCreativeBinder();
    }

    function creativeEntryChildren(basePath = "") {
      const entries = creativeTreePayload && Array.isArray(creativeTreePayload.entries)
        ? creativeTreePayload.entries
        : [];
      if (!basePath) {
        return entries;
      }
      const entry = findCreativeEntry(entries, basePath);
      return entry && Array.isArray(entry.children) ? entry.children : [];
    }

    function findCreativeEntry(entries, path) {
      for (const entry of entries || []) {
        if (String(entry.path || "") === path) {
          return entry;
        }
        const child = findCreativeEntry(entry.children || [], path);
        if (child) {
          return child;
        }
      }
      return null;
    }

    function uniqueCreativeChildPath(basePath, stem, extension = "") {
      const existing = new Set(
        creativeEntryChildren(basePath).map((entry) =>
          String(entry.name || "").toLowerCase(),
        ),
      );
      let index = 1;
      let name = `${stem}${extension}`;
      while (existing.has(name.toLowerCase())) {
        index += 1;
        name = `${stem}-${index}${extension}`;
      }
      return basePath ? `${basePath}/${name}` : name;
    }

    function creativeParentPath(path) {
      return path.includes("/") ? path.split("/").slice(0, -1).join("/") : "";
    }

    function creativePathIsCorkboard(path) {
      return String(path || "").toLowerCase().endsWith(CREATIVE_CORKBOARD_SUFFIX);
    }

    function creativePathIsInside(path, container) {
      return path === container || path.startsWith(`${container}/`);
    }

    function remapCreativePath(path, oldPath, newPath) {
      if (!path) {
        return "";
      }
      if (path === oldPath) {
        return newPath;
      }
      if (path.startsWith(`${oldPath}/`)) {
        return `${newPath}/${path.slice(oldPath.length + 1)}`;
      }
      return path;
    }

    function beginCreativeRename(path, type) {
      creativeEditingPath = path;
      creativeEditingType = type;
      renderCreativeTree();
    }

    function cancelCreativeRename() {
      creativeEditingPath = "";
      creativeEditingType = "";
      renderCreativeTree();
    }

    function normalizedCreativeName(raw, type) {
      let name = String(raw || "").trim();
      name = name.replace(/[\/]+/g, "-");
      if (!name || name === "." || name === "..") {
        return "";
      }
      if (type === "corkboard") {
        return name.slice(0, 200);
      }
      if (type === "file" && !/\.[^./]+$/.test(name)) {
        name = `${name}.md`;
      }
      return name;
    }

    async function finishCreativeRename(path, type, rawName) {
      if (creativeEditingPath !== path) {
        return;
      }
      const newName = normalizedCreativeName(rawName, type);
      const entry = findCreativeEntry(
        creativeTreePayload && creativeTreePayload.entries,
        path,
      );
      const currentName = type === "corkboard" && entry
        ? String(entry.title || "")
        : basename(path);
      if (!newName || newName === currentName) {
        creativeEditingPath = "";
        creativeEditingType = "";
        renderCreativeTree();
        return;
      }
      if (type === "corkboard") {
        const response = await fetch(contextUrl("/api/corkboard"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider: "creative-files",
            board_id: path,
            action: "rename-board",
            title: newName,
          }),
        });
        const payload = await response.json().catch(() => ({ error: "rename failed" }));
        if (!response.ok) {
          appendOutput(`${payload.error || "rename failed"}\n`, "error");
          renderCreativeTree();
          return;
        }
        if (entry) {
          entry.title = String(payload.title || newName);
        }
        creativeEditingPath = "";
        creativeEditingType = "";
        renderCreativeTree();
        if (creativeActiveDocument === path) {
          showCreativeCorkboard(path, { freeform: true, title: entry && entry.title });
        }
        recordProjectStatusMessage(`renamed board: ${payload.title || newName}`);
        return;
      }
      const response = await fetch(contextUrl("/api/creative/rename"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, new_name: newName }),
      });
      const payload = await response.json().catch(() => ({ error: "rename failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "rename failed"}\n`, "error");
        renderCreativeTree();
        return;
      }
      const newPath = String(payload.path || "");
      creativeActiveDocument = remapCreativePath(creativeActiveDocument, path, newPath);
      creativeActiveFolder = remapCreativePath(creativeActiveFolder, path, newPath);
      expandedCreativeFolders = new Set(
        Array.from(expandedCreativeFolders).map((folder) =>
          remapCreativePath(folder, path, newPath),
        ),
      );
      creativeEditingPath = "";
      creativeEditingType = "";
      await refreshCreativeBinder();
      recordProjectStatusMessage(`renamed: ${newPath}`);
      if (creativeActiveDocument) {
        if (creativePathIsCorkboard(creativeActiveDocument)) {
          showCreativeCorkboard(creativeActiveDocument, { freeform: true });
        } else {
          showCreativeDocument(creativeActiveDocument);
        }
      }
    }

    async function createCreativeFolderInline(basePath = "") {
      if (!activeProjectRoot) {
        return;
      }
      const path = uniqueCreativeChildPath(basePath, "new-folder");
      const response = await fetch(contextUrl("/api/creative/folders"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const payload = await response.json().catch(() => ({ error: "folder failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "folder failed"}\n`, "error");
        return;
      }
      expandedCreativeFolders.add(basePath);
      creativeActiveFolder = payload.path || path;
      creativeEditingPath = payload.path || path;
      creativeEditingType = "directory";
      await refreshCreativeBinder();
      recordProjectStatusMessage(`created folder: ${payload.path || path}`);
    }

    async function createCreativeDocumentInline(basePath = "") {
      if (!activeProjectRoot) {
        return;
      }
      const path = uniqueCreativeChildPath(basePath, "untitled", ".md");
      const response = await fetch(contextUrl("/api/creative/documents"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const payload = await response.json().catch(() => ({ error: "document failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "document failed"}\n`, "error");
        return;
      }
      creativeActiveDocument = payload.path || path;
      creativeActiveFolder = basePath;
      creativeEditingPath = payload.path || path;
      creativeEditingType = "file";
      await refreshCreativeBinder();
      showCreativeDocument(creativeActiveDocument);
      recordProjectStatusMessage(`created file: ${payload.path || path}`);
    }

    async function createCreativeCorkboardInline(basePath = "") {
      if (!activeProjectRoot) {
        return;
      }
      const path = uniqueCreativeChildPath(
        basePath,
        "ideas",
        CREATIVE_CORKBOARD_SUFFIX,
      );
      const response = await fetch(contextUrl("/api/corkboards"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const payload = await response.json().catch(() => ({ error: "corkboard failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "corkboard failed"}\n`, "error");
        return;
      }
      creativeActiveDocument = payload.path || path;
      creativeActiveFolder = basePath;
      creativeEditingPath = payload.path || path;
      creativeEditingType = "corkboard";
      await refreshCreativeBinder();
      showCreativeCorkboard(creativeActiveDocument, { freeform: true });
      recordProjectStatusMessage(`created board: ${payload.path || path}`);
    }

    async function deleteCreativeEntry(path, type) {
      if (!activeProjectRoot || !path) {
        return;
      }
      const label = type === "directory"
        ? "folder and all of its contents"
        : type === "corkboard" ? "corkboard" : "file";
      if (!window.confirm(`Delete this ${label}?\n\n${path}`)) {
        return;
      }
      const response = await fetch(contextUrl("/api/creative/delete"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const payload = await response.json().catch(() => ({ error: "delete failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "delete failed"}\n`, "error");
        return;
      }
      if (creativePathIsInside(creativeActiveDocument, path)) {
        creativeActiveDocument = "";
        hideArtifactPreview();
      }
      if (creativePathIsInside(creativeActiveFolder, path)) {
        creativeActiveFolder = creativeParentPath(path);
      }
      if (creativePathIsInside(creativeEditingPath, path)) {
        creativeEditingPath = "";
        creativeEditingType = "";
      }
      expandedCreativeFolders = new Set(
        Array.from(expandedCreativeFolders).filter(
          (folder) => !creativePathIsInside(folder, path),
        ),
      );
      await refreshCreativeBinder();
      recordProjectStatusMessage(`deleted ${type}: ${path}`);
    }

    async function startCreativeWritingAgent(options = {}) {
      return startAgent(runtimeApi, options);
    }

  window.ElectroBoyFrontend.registerWorkflow({
    id: WORKFLOW_ID,
    mode: "creative",
    label: "Creative writing",
    order: 20,
    backendPackage: "electroboy.workflows.creative_writing",
    navigation: "sidebar",
    defaultPaneLayout: { type: "leaf", kind: "empty" },
    migratePaneLayout,
    capabilities: ["creative-workspace"],
    layoutClass: "creative-workflow",
    splashImage: "__CREATIVE_SPLASH_IMAGE_ROUTE__",
    help: {
      summary:
        "Develop long-form writing with a binder, visual planning tools, documents, and agents.",
      features: [
        "Organize folders and documents in the binder while preserving your writing context.",
        "Plan scenes and milestones with corkboards, agendas, and calendars.",
        "Assign agents to writing tasks and review their output beside the source material.",
      ],
    },
    rightPaneStorageKey: "electroboy.creativeRightPaneWidth",
    recentProjectFilter: (project) => project.kind === "creative",
    projectEndpoint,
    projectChanged,
    handleWindowMessage,
    renderProjectStatus,
    restoreScratchPad: restoreWorkflowScratchPad,
    saveScratchPad: saveWorkflowScratchPad,
    renderNavigation,
    refreshNavigation,
    activate,
    deactivate,
    actions: {
      startAgent,
      selectFolder,
      selectCorkboard,
      showDocument,
      selectDocument,
      applyCreativeWorkspace: (runtime, ...args) => invoke(runtime, applyCreativeWorkspace, args),
      updateCreativeBinderActions: (runtime, ...args) => invoke(runtime, updateCreativeBinderActions, args),
      renderCreativeRecentProjects: (runtime, ...args) => invoke(runtime, renderCreativeRecentProjects, args),
      updateCreativeActionGroup: (runtime, ...args) => invoke(runtime, updateCreativeActionGroup, args),
      toggleCreativeActionGroup: (runtime, ...args) => invoke(runtime, toggleCreativeActionGroup, args),
      refreshCreativeBinder: (runtime, ...args) => invoke(runtime, refreshCreativeBinder, args),
      showCreativeTreeMessage: (runtime, ...args) => invoke(runtime, showCreativeTreeMessage, args),
      renderCreativeTree: (runtime, ...args) => invoke(runtime, renderCreativeTree, args),
      showCreativeCorkboard: (runtime, ...args) => invoke(runtime, showCreativeCorkboard, args),
      selectCreativeFolder: (runtime, ...args) => invoke(runtime, selectCreativeFolder, args),
      selectCreativeCorkboard: (runtime, ...args) => invoke(runtime, selectCreativeCorkboard, args),
      showCreativeDocument: (runtime, ...args) => invoke(runtime, showCreativeDocument, args),
      selectCreativeDocument: (runtime, ...args) => invoke(runtime, selectCreativeDocument, args),
      creativeAgentSession: (runtime, ...args) => invoke(runtime, creativeAgentSession, args),
      creativeAgentRunning: (runtime, ...args) => invoke(runtime, creativeAgentRunning, args),
      activeCreativeTarget: (runtime, ...args) => invoke(runtime, activeCreativeTarget, args),
      creativeTargetContextLines: (runtime, ...args) => invoke(runtime, creativeTargetContextLines, args),
      creativePromptMessage: (runtime, ...args) => invoke(runtime, creativePromptMessage, args),
      preparePrompt: (runtime, ...args) => invoke(runtime, creativePromptMessage, args),
      loadCreativeScratchPad: (runtime, ...args) => invoke(runtime, loadCreativeScratchPad, args),
      queueCreativeScratchPadSave: (runtime, ...args) => invoke(runtime, queueCreativeScratchPadSave, args),
      saveCreativeScratchPad: (runtime, ...args) => invoke(runtime, saveCreativeScratchPad, args),
      initializeCreativeWorkspace: (runtime, ...args) => invoke(runtime, initializeCreativeWorkspace, args),
      ensureCreativeWorkspaceLoaded: (runtime, ...args) => invoke(runtime, ensureCreativeWorkspaceLoaded, args),
      creativeEntryChildren: (runtime, ...args) => invoke(runtime, creativeEntryChildren, args),
      findCreativeEntry: (runtime, ...args) => invoke(runtime, findCreativeEntry, args),
      uniqueCreativeChildPath: (runtime, ...args) => invoke(runtime, uniqueCreativeChildPath, args),
      creativeParentPath: (runtime, ...args) => invoke(runtime, creativeParentPath, args),
      creativePathIsCorkboard: (runtime, ...args) => invoke(runtime, creativePathIsCorkboard, args),
      creativePathIsInside: (runtime, ...args) => invoke(runtime, creativePathIsInside, args),
      remapCreativePath: (runtime, ...args) => invoke(runtime, remapCreativePath, args),
      beginCreativeRename: (runtime, ...args) => invoke(runtime, beginCreativeRename, args),
      cancelCreativeRename: (runtime, ...args) => invoke(runtime, cancelCreativeRename, args),
      normalizedCreativeName: (runtime, ...args) => invoke(runtime, normalizedCreativeName, args),
      finishCreativeRename: (runtime, ...args) => invoke(runtime, finishCreativeRename, args),
      createCreativeFolderInline: (runtime, ...args) => invoke(runtime, createCreativeFolderInline, args),
      createCreativeDocumentInline: (runtime, ...args) => invoke(runtime, createCreativeDocumentInline, args),
      createCreativeCorkboardInline: (runtime, ...args) => invoke(runtime, createCreativeCorkboardInline, args),
      deleteCreativeEntry: (runtime, ...args) => invoke(runtime, deleteCreativeEntry, args),
      chooseCreativeAgentSession: (runtime, ...args) => invoke(runtime, chooseCreativeAgentSession, args),
      startCreativeWritingAgent: (runtime, ...args) => invoke(runtime, startCreativeWritingAgent, args),
    },
  });
})();
