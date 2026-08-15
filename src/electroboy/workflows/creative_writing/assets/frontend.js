(function () {
  "use strict";

  let creativeProjectMenuButton = null;
  let creativeProjectActions = null;
  let creativeOpenProject = null;
  let creativeNewProject = null;
  let creativeRecentProjects = null;
  let creativeCloseProject = null;
  let creativeActiveProjectSection = null;
  let creativeProjectName = null;
  let creativeAgentMenuButton = null;
  let creativeAgentActions = null;
  let creativeStartAgent = null;

  function renderNavigation(container, runtime) {
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
            <div class="recent-project-list" role="group" hidden
                 data-creative-control="recent-projects"></div>
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
    creativeRecentProjects = find("recent-projects");
    creativeCloseProject = find("close-project");
    creativeActiveProjectSection = find("active-project");
    creativeProjectName = find("project-name");
    creativeAgentMenuButton = find("agent-menu");
    creativeAgentActions = find("agent-actions");
    creativeStartAgent = find("start-agent");
    runtime.elements.creativeTree = find("tree");

    creativeProjectMenuButton.addEventListener("click", () => {
      runtime.actions.toggleCreativeActionGroup("project");
    });
    creativeAgentMenuButton.addEventListener("click", () => {
      runtime.actions.toggleCreativeActionGroup("agent");
    });
    creativeOpenProject.addEventListener("click", () => {
      runtime.actions.openProjectBrowser("open", true);
    });
    creativeNewProject.addEventListener("click", () => {
      runtime.actions.openProjectBrowser("new", true);
    });
    creativeCloseProject.addEventListener("click", () => {
      runtime.actions.deactivateProject();
    });
    creativeStartAgent.addEventListener("click", () => {
      startAgent(runtime);
    });
    updateCreativeBinderActions();
  }

  function refreshNavigation() {
    if (creativeProjectMenuButton) {
      updateCreativeBinderActions();
    }
  }

  function activate(runtime) {
    runtime.actions.setWorkflowSideSheetCollapsed(false);
    runtime.actions.applyCreativeWorkspace();
    runtime.actions.restoreScratchPad();
    runtime.actions.refreshCreativeBinder();
  }

  function deactivate(runtime) {
    runtime.elements.creativeTree = null;
    creativeProjectMenuButton = null;
    creativeProjectActions = null;
    creativeOpenProject = null;
    creativeNewProject = null;
    creativeRecentProjects = null;
    creativeCloseProject = null;
    creativeActiveProjectSection = null;
    creativeProjectName = null;
    creativeAgentMenuButton = null;
    creativeAgentActions = null;
    creativeStartAgent = null;
  }

  async function startAgent(runtime) {
    const state = runtime.getState();
    const action = runtime.actions;
    if (!state.activeProjectRoot || !state.contextId) {
      action.appendOutput("activate a project first\n", "error");
      return;
    }
    action.setAgentInputVisible(true);
    action.clearAgentOutput();
    action.appendOutput("$ codex creative-writing\n", "system");
    const response = await fetch(action.contextUrl("/api/creative/agent/start"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        active_document: state.creativeActiveDocument,
        active_target: action.activeCreativeTarget(),
      }),
    });
    const payload = await response
      .json()
      .catch(() => ({ error: "start failed" }));
    if (!response.ok) {
      action.appendOutput(`${payload.error || "start failed"}\n`, "error");
      return;
    }
    action.updateProjectState(payload);
    const sessionId = payload.session_id || runtime.getState().selectedSessionId;
    action.connectSessionEvents(sessionId);
    action.sendTerminalResize();
  }

  function selectFolder(runtime, path) {
    if (!path) {
      return;
    }
    runtime.updateState({
      creativeActiveFolder: path,
      creativeActiveDocument: "",
      creativeLastNotifiedTarget: "",
    });
    runtime.actions.showCreativeCorkboard(path);
    runtime.actions.renderCreativeTree();
    runtime.actions.renderCreativeProjectStatus();
    runtime.actions.notifyCreativeAgentTargetSwitch();
  }

  function selectCorkboard(runtime, path) {
    if (!path) {
      return;
    }
    runtime.updateState({
      creativeActiveDocument: path,
      creativeActiveFolder: runtime.actions.creativeParentPath(path),
      creativeLastNotifiedTarget: "",
    });
    runtime.actions.showCreativeCorkboard(path, { freeform: true });
    runtime.actions.renderCreativeTree();
    runtime.actions.renderCreativeProjectStatus();
    runtime.actions.notifyCreativeAgentTargetSwitch();
  }

  function showDocument(runtime, path) {
    if (!path) {
      return;
    }
    const target = {
      label: runtime.actions.basename(path),
      path,
    };
    runtime.actions.showArtifactPreviews(
      [
        {
          id: "creative-document",
          kind: "document",
          title: target.label,
          target,
          editing: false,
        },
      ],
      { manual: true, stage: "creative-writing" },
    );
  }

  function selectDocument(runtime, path, options = {}) {
    if (!path) {
      return;
    }
    const state = runtime.getState();
    runtime.updateState({
      creativeActiveDocument: path,
      creativeActiveFolder: runtime.actions.creativeParentPath(path),
      creativeLastNotifiedTarget: options.notifyAgent === false
        ? state.creativeLastNotifiedTarget
        : "",
    });
    showDocument(runtime, path);
    runtime.actions.renderCreativeTree();
    runtime.actions.renderCreativeProjectStatus();
    if (options.notifyAgent !== false) {
      runtime.actions.notifyCreativeAgentTargetSwitch();
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
      creativeRecentProjects.hidden = entries.length === 0;
      if (entries.length === 0) {
        return;
      }
      const heading = document.createElement("div");
      heading.className = "stage-action-heading";
      heading.textContent = "Recent";
      creativeRecentProjects.append(heading);
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
      return window.ElectroBoyFrontend.invokeModule(
        "binder",
        "showMessage",
        message,
      );
    }

    function renderCreativeTree() {
      return window.ElectroBoyFrontend.invokeModule("binder", "renderTree");
    }

    function showCreativeCorkboard(path, options = {}) {
      return window.ElectroBoyFrontend.invokeModule(
        "corkboard",
        "show",
        path,
        options,
      );
    }

    function selectCreativeFolder(path) {
      return window.ElectroBoyFrontend.invokeWorkflow(
        "creative-writing",
        "selectFolder",
        path,
      );
    }

    function selectCreativeCorkboard(path) {
      return window.ElectroBoyFrontend.invokeWorkflow(
        "creative-writing",
        "selectCorkboard",
        path,
      );
    }

    function showCreativeDocument(path) {
      return window.ElectroBoyFrontend.invokeWorkflow(
        "creative-writing",
        "showDocument",
        path,
      );
    }

    function selectCreativeDocument(path, options = {}) {
      return window.ElectroBoyFrontend.invokeWorkflow(
        "creative-writing",
        "selectDocument",
        path,
        options,
      );
    }

    function creativeAgentSession() {
      return agentSessions.some(
        (session) => session.kind === "creative-writing" && session.status === "running",
      )
        ? agentSessions.find(
            (session) => session.kind === "creative-writing" && session.status === "running",
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
        "creative-writing",
        "startAgent",
      );
    }

  window.ElectroBoyFrontend.registerWorkflow({
    id: "creative-writing",
    mode: "creative",
    label: "Creative writing",
    order: 20,
    backendPackage: "electroboy.workflows.creative_writing",
    navigation: "sidebar",
    capabilities: ["creative-workspace"],
    layoutClass: "creative-workflow",
    splashImage: "__CREATIVE_SPLASH_IMAGE_ROUTE__",
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
      applyCreativeWorkspace: (_runtime, ...args) => applyCreativeWorkspace(...args),
      updateCreativeBinderActions: (_runtime, ...args) => updateCreativeBinderActions(...args),
      renderCreativeRecentProjects: (_runtime, ...args) => renderCreativeRecentProjects(...args),
      updateCreativeActionGroup: (_runtime, ...args) => updateCreativeActionGroup(...args),
      toggleCreativeActionGroup: (_runtime, ...args) => toggleCreativeActionGroup(...args),
      refreshCreativeBinder: (_runtime, ...args) => refreshCreativeBinder(...args),
      firstCreativeMarkdown: (_runtime, ...args) => firstCreativeMarkdown(...args),
      showCreativeTreeMessage: (_runtime, ...args) => showCreativeTreeMessage(...args),
      renderCreativeTree: (_runtime, ...args) => renderCreativeTree(...args),
      showCreativeCorkboard: (_runtime, ...args) => showCreativeCorkboard(...args),
      selectCreativeFolder: (_runtime, ...args) => selectCreativeFolder(...args),
      selectCreativeCorkboard: (_runtime, ...args) => selectCreativeCorkboard(...args),
      showCreativeDocument: (_runtime, ...args) => showCreativeDocument(...args),
      selectCreativeDocument: (_runtime, ...args) => selectCreativeDocument(...args),
      creativeAgentSession: (_runtime, ...args) => creativeAgentSession(...args),
      creativeAgentRunning: (_runtime, ...args) => creativeAgentRunning(...args),
      activeCreativeTarget: (_runtime, ...args) => activeCreativeTarget(...args),
      creativeTargetKey: (_runtime, ...args) => creativeTargetKey(...args),
      creativeTargetContextLines: (_runtime, ...args) => creativeTargetContextLines(...args),
      notifyCreativeAgentTargetSwitch: (_runtime, ...args) => notifyCreativeAgentTargetSwitch(...args),
      creativePromptMessage: (_runtime, ...args) => creativePromptMessage(...args),
      loadCreativeScratchPad: (_runtime, ...args) => loadCreativeScratchPad(...args),
      queueCreativeScratchPadSave: (_runtime, ...args) => queueCreativeScratchPadSave(...args),
      saveCreativeScratchPad: (_runtime, ...args) => saveCreativeScratchPad(...args),
      initializeCreativeWorkspace: (_runtime, ...args) => initializeCreativeWorkspace(...args),
      ensureCreativeWorkspaceLoaded: (_runtime, ...args) => ensureCreativeWorkspaceLoaded(...args),
      creativeEntryChildren: (_runtime, ...args) => creativeEntryChildren(...args),
      findCreativeEntry: (_runtime, ...args) => findCreativeEntry(...args),
      uniqueCreativeChildPath: (_runtime, ...args) => uniqueCreativeChildPath(...args),
      creativeParentPath: (_runtime, ...args) => creativeParentPath(...args),
      creativePathIsCorkboard: (_runtime, ...args) => creativePathIsCorkboard(...args),
      creativePathIsInside: (_runtime, ...args) => creativePathIsInside(...args),
      remapCreativePath: (_runtime, ...args) => remapCreativePath(...args),
      beginCreativeRename: (_runtime, ...args) => beginCreativeRename(...args),
      cancelCreativeRename: (_runtime, ...args) => cancelCreativeRename(...args),
      normalizedCreativeName: (_runtime, ...args) => normalizedCreativeName(...args),
      finishCreativeRename: (_runtime, ...args) => finishCreativeRename(...args),
      createCreativeFolderInline: (_runtime, ...args) => createCreativeFolderInline(...args),
      createCreativeDocumentInline: (_runtime, ...args) => createCreativeDocumentInline(...args),
      createCreativeCorkboardInline: (_runtime, ...args) => createCreativeCorkboardInline(...args),
      deleteCreativeEntry: (_runtime, ...args) => deleteCreativeEntry(...args),
      startCreativeWritingAgent: (_runtime, ...args) => startCreativeWritingAgent(...args),
    },
  });
})();
