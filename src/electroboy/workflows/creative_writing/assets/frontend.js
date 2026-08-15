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
  let creativeLastNotifiedTarget = "";
  let expandedCreativeFolders = new Set();
  let restoredScratchContextId = "";
  let creativeScratchSaveTimer = null;
  let creativeProjectActionsExpanded = false;
  let creativeAgentActionsExpanded = false;

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
    creativeLastNotifiedTarget = state.creativeLastNotifiedTarget || "";
    expandedCreativeFolders = state.expandedCreativeFolders instanceof Set
      ? state.expandedCreativeFolders
      : new Set(state.expandedCreativeFolders || []);
  }

  function publishState() {
    runtimeApi.updateState({
      artifactPaneRequested,
      creativeTreePayload,
      creativeActiveDocument,
      creativeActiveFolder,
      creativeEditingPath,
      creativeEditingType,
      creativeLastNotifiedTarget,
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

  function basename(path) {
    return runtimeApi.paths.basename(path);
  }

  function setAgentInputVisible(visible) {
    runtimeApi.ui.setAgentInputVisible(visible);
  }

  function showProgressPane(visible) {
    runtimeApi.layout.showProgressPane(visible);
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

  function openRecentProject(project) {
    return runtimeApi.recent.open(project);
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
    if (data.type !== "electroboy-creative-open" || !data.path) {
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
    creativeCloseProject.addEventListener("click", () => {
      runtime.project.deactivate();
    });
    creativeStartAgent.addEventListener("click", () => {
      startAgent(runtime);
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
    creativeRecentProjectsButton = null;
    creativeRecentProjects = null;
    creativeCloseProject = null;
    creativeActiveProjectSection = null;
    creativeProjectName = null;
    creativeAgentMenuButton = null;
    creativeAgentActions = null;
    creativeStartAgent = null;
    creativeRecentProjectsExpanded = false;
  }

  async function startAgent(runtime) {
    bindRuntime(runtime);
    const state = runtime.getState();
    if (!state.activeProjectRoot || !state.contextId) {
      appendOutput("activate a project first\n", "error");
      return;
    }
    setAgentInputVisible(true);
    runtime.agent.clearOutput();
    appendOutput("$ codex creative-writing\n", "system");
    const response = await runtime.http.fetch(contextUrl("/api/creative/agent/start"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        active_document: state.creativeActiveDocument,
        active_target: activeCreativeTarget(),
      }),
    });
    const payload = await response
      .json()
      .catch(() => ({ error: "start failed" }));
    if (!response.ok) {
      appendOutput(`${payload.error || "start failed"}\n`, "error");
      return;
    }
    runtime.project.update(payload);
    bindRuntime(runtime);
    const sessionId = payload.session_id || runtime.getState().selectedSessionId;
    runtime.modules.invoke("agent-sessions", "connectSessionEvents", sessionId);
    runtime.agent.sendResize();
  }

  function selectFolder(runtime, path) {
    bindRuntime(runtime);
    if (!path) {
      return;
    }
    runtime.updateState({
      creativeActiveFolder: path,
      creativeActiveDocument: "",
      creativeLastNotifiedTarget: "",
    });
    showCreativeCorkboard(path);
    renderCreativeTree();
    renderProjectStatus(runtime);
    notifyCreativeAgentTargetSwitch();
  }

  function selectCorkboard(runtime, path, options = {}) {
    bindRuntime(runtime);
    if (!path) {
      return;
    }
    runtime.updateState({
      creativeActiveDocument: path,
      creativeActiveFolder: creativeParentPath(path),
      creativeLastNotifiedTarget: "",
    });
    showCreativeCorkboard(path, {
      freeform: true,
      title: options.title || "",
    });
    renderCreativeTree();
    renderProjectStatus(runtime);
    notifyCreativeAgentTargetSwitch();
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
    const state = runtime.getState();
    runtime.updateState({
      creativeActiveDocument: path,
      creativeActiveFolder: creativeParentPath(path),
      creativeLastNotifiedTarget: options.notifyAgent === false
        ? state.creativeLastNotifiedTarget
        : "",
    });
    showDocument(runtime, path);
    renderCreativeTree();
    renderProjectStatus(runtime);
    if (options.notifyAgent !== false) {
      notifyCreativeAgentTargetSwitch();
    }
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
        artifactPaneRequested = true;
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
        button.addEventListener("click", () => {
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
      if (!creativeActiveDocument) {
        const firstDocument = firstCreativeMarkdown(payload.entries || []);
        if (firstDocument) {
          selectCreativeDocument(firstDocument.path, { notifyAgent: false });
        }
      }
    }

    function firstCreativeMarkdown(entries) {
      for (const entry of entries) {
        if ((entry.type || "") === "file" && entry.markdown) {
          return entry;
        }
        const child = firstCreativeMarkdown(entry.children || []);
        if (child) {
          return child;
        }
      }
      return null;
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

    function creativeAgentSession() {
      return agentSessions.some(
        (session) => session.kind === WORKFLOW_ID && session.status === "running",
      )
        ? agentSessions.find(
            (session) => session.kind === WORKFLOW_ID && session.status === "running",
          )
        : null;
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

    function creativeTargetKey(target) {
      return `${target.type || "none"}:${target.path || ""}`;
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

    async function notifyCreativeAgentTargetSwitch() {
      const target = activeCreativeTarget();
      const targetKey = creativeTargetKey(target);
      const session = creativeAgentSession();
      if (
        !creativeModeActive() ||
        target.type === "none" ||
        targetKey === creativeLastNotifiedTarget ||
        !session ||
        !session.interactive
      ) {
        return;
      }
      creativeLastNotifiedTarget = targetKey;
      const message = [
        "[ElectroBoy creative-writing context update]",
        ...creativeTargetContextLines(target),
        "The target is now displayed in the middle pane.",
        "Do not modify it unless the writer asks.",
        "[/ElectroBoy creative-writing context update]",
      ].join("\n");
      await fetch(contextUrl("/api/sessions/message"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session.session_id, message }),
      }).catch(() => {});
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
        if (!name.toLowerCase().endsWith(CREATIVE_CORKBOARD_SUFFIX)) {
          name = name.replace(/\.(md|json)$/i, "");
          name = `${name}${CREATIVE_CORKBOARD_SUFFIX}`;
        }
        return name;
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
      if (!newName || newName === basename(path)) {
        creativeEditingPath = "";
        creativeEditingType = "";
        renderCreativeTree();
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
      const response = await fetch(contextUrl("/api/creative/corkboards"), {
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

    async function startCreativeWritingAgent() {
      return window.ElectroBoyFrontend.invokeWorkflow(
        WORKFLOW_ID,
        "startAgent",
      );
    }

  window.ElectroBoyFrontend.registerWorkflow({
    id: WORKFLOW_ID,
    mode: "creative",
    label: "Creative writing",
    order: 20,
    backendPackage: "electroboy.workflows.creative_writing",
    navigation: "sidebar",
    capabilities: ["creative-workspace"],
    layoutClass: "creative-workflow",
    splashImage: "__CREATIVE_SPLASH_IMAGE_ROUTE__",
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
      firstCreativeMarkdown: (runtime, ...args) => invoke(runtime, firstCreativeMarkdown, args),
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
      creativeTargetKey: (runtime, ...args) => invoke(runtime, creativeTargetKey, args),
      creativeTargetContextLines: (runtime, ...args) => invoke(runtime, creativeTargetContextLines, args),
      notifyCreativeAgentTargetSwitch: (runtime, ...args) => invoke(runtime, notifyCreativeAgentTargetSwitch, args),
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
      startCreativeWritingAgent: (runtime, ...args) => invoke(runtime, startCreativeWritingAgent, args),
    },
  });
})();
