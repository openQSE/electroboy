(function () {
  "use strict";

  const DOCUMENT_TARGETS_STORAGE_KEY = "electroboy.documentTargets";
  const DOCUMENT_ZOOM_STEP = 10;
  const DEFAULT_DOCUMENT_TARGETS = [
    { label: "README", path: "README.md" },
    { label: "API", path: "docs/api.md" },
  ];
  const PANE_POPUP_FEATURES =
    "popup=yes,width=980,height=720,menubar=no,toolbar=no,location=no,status=no,scrollbars=yes,resizable=yes";
  let runtimeApi = null;
  let runtimeState = null;
  let documentMenuEventsBound = false;
  let fileCatalogSync = null;
  let dockedPaneTools = null;
  let dockedFilePaneTools = null;
  let activeArtifactToolItemId = "";

  function bindRuntime(runtime) {
    runtimeApi = runtime;
    runtimeState = runtime.state;
    bindDocumentMenuEvents();
    mountDockedPaneTools();
    if (runtimeState.customDocumentTargets.length === 0) {
      runtimeState.customDocumentTargets = storedDocumentTargets();
    }
    if (!fileCatalogSync) {
      fileCatalogSync = runtime.sharedPanes.connect("file-catalog", {
        snapshot: openFileCatalogState,
      });
      window.addEventListener("pagehide", () => fileCatalogSync.close(), {
        once: true,
      });
    }
  }

  function invoke(runtime, handler, args) {
    bindRuntime(runtime);
    return handler(...args);
  }

  const exportSafeName = (...args) => runtimeApi.downloads.safeName(...args);
  const contextUrl = (...args) => runtimeApi.http.contextUrl(...args);
  const exportBlob = (...args) => runtimeApi.downloads.exportBlob(...args);
  const sessionMetadata = (...args) =>
    runtimeApi.modules.invoke("agent-sessions", "sessionMetadata", ...args);
  const stageActionButton = (...args) => runtimeApi.ui.stageActionButton(...args);
  const openDocumentFileBrowser = (...args) =>
    runtimeApi.modules.invoke("file-browser", "openDocumentFileBrowser", ...args);
  const openNewDocumentFileBrowser = (...args) =>
    runtimeApi.modules.invoke("file-browser", "openNewDocumentFileBrowser", ...args);
  const appendOutput = (...args) => runtimeApi.notifications.appendOutput(...args);
  const refreshStageActionPanel = (...args) =>
    runtimeApi.ui.refreshStageActionPanel(...args);
  const selectAgentSession = (...args) =>
    runtimeApi.modules.invoke("agent-sessions", "selectAgentSession", ...args);
  const changeDocumentZoom = (...args) =>
    runtimeApi.artifacts.changeDocumentZoom(...args);
  const artifactEditorFontSize = (...args) =>
    runtimeApi.artifacts.editorFontSize(...args);
  const applyStoredArtifactPaneSize = (...args) =>
    runtimeApi.artifacts.applyStoredPaneSize(...args);
  const applyOutputPaneVisibility = (...args) =>
    runtimeApi.ui.applyOutputPaneVisibility(...args);
  const postArtifactEditorFontSize = (...args) =>
    runtimeApi.artifacts.postEditorFontSize(...args);
  const applyDocumentZoom = (...args) =>
    runtimeApi.artifacts.applyDocumentZoom(...args);
  const popOutPane = (...args) => runtimeApi.ui.popOutPane(...args);
  const genericStageRun = (...args) => runtimeApi.workflows.stageRun(...args);
  const hideStageMenus = (...args) => runtimeApi.ui.hideStageMenus(...args);
  const closeAgentEventStream = (...args) =>
    runtimeApi.modules.invoke("agent-sessions", "closeAgentEventStream", ...args);
  const showProgressPane = (...args) => runtimeApi.layout.showProgressPane(...args);
  const setAgentInputVisible = (...args) =>
    runtimeApi.ui.setAgentInputVisible(...args);
  const clearAgentOutput = (...args) =>
    runtimeApi.agent.clearOutput(...args);
  const setAgentRunning = (...args) =>
    runtimeApi.modules.invoke("agent-sessions", "setAgentRunning", ...args);
  const updateProjectState = (...args) => runtimeApi.project.update(...args);
  const renderSessionSwitcher = (...args) =>
    runtimeApi.modules.invoke("agent-sessions", "renderSessionSwitcher", ...args);
  const connectSessionEvents = (...args) =>
    runtimeApi.modules.invoke("agent-sessions", "connectSessionEvents", ...args);
  const sendTerminalResize = (...args) =>
    runtimeApi.agent.sendResize(...args);

  function activeArtifactToolItem() {
    return runtimeState.artifactPreviewItems.find(
      (item) => item.id === activeArtifactToolItemId,
    ) || runtimeState.artifactPreviewItems[0] || null;
  }

  function activateArtifactToolItem(itemId) {
    activeArtifactToolItemId = itemId;
    dockedFilePaneTools?.refresh();
  }

  function dockedPaneToolTarget() {
    const item = activeArtifactToolItem();
    if (!item) return {};
    return {
      kind: item.kind,
      path: item.kind === "document" && item.target
        ? item.target.path
        : item.path || "",
      title: item.title || "",
      editing: Boolean(item.editing),
    };
  }

  function mountDockedPaneTools() {
    if (dockedPaneTools || !window.ElectroBoyPaneTools || !window.ElectroBoyFilePaneTools) {
      return;
    }
    const pane = document.getElementById("artifactPreviewPane");
    dockedPaneTools = window.ElectroBoyPaneTools.create({
      host: pane,
      shelf: document.getElementById("artifactPaneToolsShelf"),
      content: document.getElementById("artifactPaneToolsContent"),
      toggleButton: document.getElementById("artifactPaneToolsToggle"),
      closeButton: document.getElementById("closeArtifactPaneTools"),
      resizeHandle: document.getElementById("artifactPaneToolsResizeHandle"),
      storageKey: "electroboy.paneTools.docked.artifact",
    });
    dockedFilePaneTools = window.ElectroBoyFilePaneTools.mount({
      controller: dockedPaneTools,
      getFrame: () => artifactFrameForItem(activeArtifactToolItem()),
      getTarget: dockedPaneToolTarget,
      contextUrl,
      actions: {
        zoomOut: () => changeDocumentZoom(-DOCUMENT_ZOOM_STEP),
        zoomIn: () => changeDocumentZoom(DOCUMENT_ZOOM_STEP),
        zoomLabel: () => `${runtimeState.documentZoom}%`,
        startAgent: () => {
          const item = activeArtifactToolItem();
          if (!item || item.kind !== "document" || !item.target) return;
          const session = documentationSessionForTarget(item.target);
          return session
            ? selectAgentSession(session.session_id)
            : startDocumentationAgent(item.target);
        },
        preview: () => {
          const item = activeArtifactToolItem();
          if (item) return setArtifactPreviewEditing(item, false);
        },
        edit: () => {
          const item = activeArtifactToolItem();
          if (item) return setArtifactPreviewEditing(item, true);
        },
        refresh: () => refreshArtifactPreview(),
        export: (_target, format) => {
          const item = activeArtifactToolItem();
          if (item) return exportArtifactDocument(item, format);
        },
      },
    });
  }

    function storedDocumentTargets() {
      try {
        const parsed = JSON.parse(
          window.localStorage.getItem(DOCUMENT_TARGETS_STORAGE_KEY) || "[]",
        );
        if (!Array.isArray(parsed)) {
          return [];
        }
        return parsed
          .map((target) => ({
            label: String(target.label || target.path || "").trim(),
            path: String(target.path || "").trim(),
          }))
          .filter((target) => target.label && target.path);
      } catch (error) {
        return [];
      }
    }

    function saveDocumentTargets() {
      try {
        window.localStorage.setItem(
          DOCUMENT_TARGETS_STORAGE_KEY,
          JSON.stringify(runtimeState.customDocumentTargets),
        );
      } catch (error) {
        return;
      }
    }

    function documentExportFormats() {
      return [
        {
          value: "markdown",
          label: "Markdown",
          extension: "md",
          description: "Markdown",
          accept: {
            "text/markdown": [".md"],
            "text/plain": [".txt"],
          },
        },
        {
          value: "docx",
          label: "DOCX",
          extension: "docx",
          description: "Word document",
          accept: {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [
              ".docx",
            ],
          },
        },
        {
          value: "pdf",
          label: "PDF",
          extension: "pdf",
          description: "PDF",
          accept: {
            "application/pdf": [".pdf"],
          },
        },
      ];
    }

    function documentExportFormat(format) {
      return documentExportFormats().find((candidate) => candidate.value === format)
        || documentExportFormats()[0];
    }

    function documentExportPickerTypes(format = "markdown") {
      const selected = documentExportFormat(format);
      return [
        {
          description: selected.description,
          accept: selected.accept,
        },
      ];
    }

    function closeDocumentMenus(except = null) {
      for (const menu of document.querySelectorAll(".pane-document-menu[open]")) {
        if (menu !== except) {
          menu.open = false;
        }
      }
    }

    function bindDocumentMenuEvents() {
      if (documentMenuEventsBound) {
        return;
      }
      documentMenuEventsBound = true;
      document.addEventListener("click", (event) => {
        const activeMenu = event.target instanceof Element
          ? event.target.closest(".pane-document-menu")
          : null;
        closeDocumentMenus(activeMenu);
      });
      document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") {
          return;
        }
        const openMenu = document.querySelector(".pane-document-menu[open]");
        if (!openMenu) {
          return;
        }
        event.preventDefault();
        openMenu.open = false;
        openMenu.querySelector("summary")?.focus();
      });
    }

    function documentMenuButton(label, title, run, options = {}) {
      const button = document.createElement("button");
      button.className = "pane-document-menu-item";
      button.type = "button";
      button.role = options.role || "menuitem";
      button.title = title;
      button.setAttribute("aria-label", title);
      if (options.checked !== undefined) {
        button.setAttribute("aria-checked", String(Boolean(options.checked)));
      }
      const check = document.createElement("span");
      check.className = "pane-document-menu-check";
      check.setAttribute("aria-hidden", "true");
      check.textContent = options.checked ? "\u2713" : "";
      const text = document.createElement("span");
      text.textContent = label;
      button.append(check, text);
      button.addEventListener("click", () => {
        closeDocumentMenus();
        run();
      });
      return button;
    }

    function buildDocumentMenu(item) {
      const menu = document.createElement("details");
      menu.className = "pane-document-menu";
      menu.addEventListener("toggle", () => {
        if (menu.open) {
          closeDocumentMenus(menu);
          return;
        }
        for (const submenu of menu.querySelectorAll("details[open]")) {
          submenu.open = false;
        }
      });

      const summary = document.createElement("summary");
      summary.className = "pane-document-menu-trigger";
      summary.title = `Document actions for ${item.title}`;
      summary.setAttribute("aria-label", `Document actions for ${item.title}`);
      summary.textContent = "Document";

      const panel = document.createElement("div");
      panel.className = "pane-document-menu-panel";
      panel.role = "menu";
      panel.setAttribute("aria-label", `Document actions for ${item.title}`);
      panel.append(
        documentMenuButton(
          "Preview",
          `Preview ${item.title}`,
          () => setArtifactPreviewEditing(item, false),
          { role: "menuitemradio", checked: !item.editing },
        ),
        documentMenuButton(
          "Edit",
          `Edit ${item.title}`,
          () => setArtifactPreviewEditing(item, true),
          { role: "menuitemradio", checked: Boolean(item.editing) },
        ),
      );

      const separator = document.createElement("div");
      separator.className = "pane-document-menu-separator";
      separator.role = "separator";
      panel.append(
        separator,
        documentMenuButton(
          "Refresh",
          `Refresh ${item.title}`,
          () => refreshArtifactPreview(),
        ),
      );

      const exportMenu = document.createElement("details");
      exportMenu.className = "pane-document-export-menu";
      const exportSummary = document.createElement("summary");
      exportSummary.className = "pane-document-menu-item pane-document-submenu-trigger";
      exportSummary.title = `Export ${item.title}`;
      exportSummary.setAttribute("aria-label", `Export ${item.title}`);
      const exportCheck = document.createElement("span");
      exportCheck.className = "pane-document-menu-check";
      exportCheck.setAttribute("aria-hidden", "true");
      const exportLabel = document.createElement("span");
      exportLabel.textContent = "Export";
      exportSummary.append(exportCheck, exportLabel);
      const exportPanel = document.createElement("div");
      exportPanel.className = "pane-document-export-panel";
      for (const format of documentExportFormats()) {
        exportPanel.append(
          documentMenuButton(
            format.label,
            `Export ${item.title} as ${format.label}`,
            () => {
              exportArtifactDocument(item, format.value).catch((error) => {
                appendOutput(`export failed: ${error}\n`, "error");
              });
            },
          ),
        );
      }
      exportMenu.append(exportSummary, exportPanel);
      panel.append(exportMenu);
      menu.append(summary, panel);
      return menu;
    }

    function artifactDocumentBaseName(item) {
      if (item.kind === "document" && item.target) {
        return exportSafeName(item.target.path || item.target.label || item.title);
      }
      if (item.kind === "route" && item.title) {
        return exportSafeName(item.title);
      }
      return exportSafeName(item.title || item.kind || "document");
    }

    function artifactDocumentExportName(item, format) {
      const selected = documentExportFormat(format);
      return `${artifactDocumentBaseName(item)}.${selected.extension}`;
    }

    function artifactDocumentExportUrl(item, format) {
      const parameters = new URLSearchParams();
      parameters.set("artifact", artifactKindForPane(item));
      parameters.set("format", format);
      if (item.kind === "document" && item.target) {
        parameters.set("path", item.target.path);
      }
      if (item.kind === "route" && item.path) {
        parameters.set("path", item.path);
      }
      return contextUrl(`/api/documents/export?${parameters.toString()}`);
    }

    async function exportArtifactDocument(item, format) {
      await exportBlob(
        artifactDocumentExportUrl(item, format),
        artifactDocumentExportName(item, format),
        format,
      );
    }

    function documentTargetKey(target) {
      return String(target && target.path ? target.path : "").trim();
    }

    function documentTargetLabel(target) {
      return String((target && (target.label || target.path)) || "Document");
    }

    function documentTargetForSession(session) {
      const metadata = sessionMetadata(session);
      const path = String(metadata.document_path || "").trim();
      if (!path) {
        return null;
      }
      const fallback = documentTargetFromInput(path) || { label: path, path };
      return {
        label: String(metadata.document_label || fallback.label || path),
        path,
      };
    }

    function documentationSessionForTarget(target) {
      const path = documentTargetKey(target);
      if (!path) {
        return null;
      }
      return (
        runtimeState.agentSessions.find((session) => {
          const sessionTarget = documentTargetForSession(session);
          return sessionTarget && sessionTarget.path === path;
        }) || null
      );
    }

  function rememberOpenDocumentTarget(target) {
      const path = documentTargetKey(target);
      if (!path) {
        return;
      }
      const storedTarget = {
        label: documentTargetLabel(target),
        path,
      };
      const existingIndex = runtimeState.openDocumentTargets.findIndex(
        (candidate) => documentTargetKey(candidate) === path,
      );
      if (existingIndex >= 0) {
        runtimeState.openDocumentTargets.splice(existingIndex, 1, storedTarget);
      } else {
        runtimeState.openDocumentTargets.push(storedTarget);
      }
      fileCatalogSync?.publish(openFileCatalogState());
    }

    function openFileCatalogState() {
      return {
        files: runtimeState.openDocumentTargets.map((target) => ({
          label: documentTargetLabel(target),
          path: documentTargetKey(target),
        })),
      };
    }

    function syncOpenDocumentTargetsFromSessions() {
      for (const session of runtimeState.agentSessions) {
        const target = documentTargetForSession(session);
        if (target) {
          rememberOpenDocumentTarget(target);
        }
      }
      refreshDocumentTargetSwitchers();
    }

    function renderDocumentTargetSwitcher(select) {
      select.replaceChildren();
      const targets = runtimeState.openDocumentTargets.length > 0
        ? runtimeState.openDocumentTargets
        : runtimeState.artifactPreviewDocumentTarget
          ? [runtimeState.artifactPreviewDocumentTarget]
          : [];
      for (const target of targets) {
        const option = document.createElement("option");
        option.value = target.path;
        option.textContent = documentTargetLabel(target);
        select.append(option);
      }
      select.value = documentTargetKey(runtimeState.artifactPreviewDocumentTarget);
      select.disabled = targets.length <= 1;
    }

    function refreshDocumentTargetSwitchers() {
      for (const select of runtimeApi.elements.artifactPreviewStack.querySelectorAll(
        ".document-target-switcher",
      )) {
        renderDocumentTargetSwitcher(select);
      }
    }

    function renderDocumentActionPanel(container) {
      container.append(
        stageActionButton({
          label: "Open",
          title: "Choose an existing Markdown file.",
          primary: true,
          disabled: !runtimeState.activeProjectRoot,
          run: openDocumentFileBrowser,
        }),
      );
      container.append(
        stageActionButton({
          label: "New",
          title: "Choose where to create a Markdown document.",
          disabled: !runtimeState.activeProjectRoot,
          run: openNewDocumentFileBrowser,
        }),
      );
    }

    function documentTargetFromInput(value) {
      const raw = value.trim();
      if (!raw) {
        return null;
      }
      const path = raw.includes("/") || raw.endsWith(".md")
        ? raw
        : raw.toLowerCase() === "readme"
          ? "README.md"
        : `docs/${raw.replace(/\s+/g, "-").toLowerCase()}.md`;
      const label = raw.replace(/\.md$/i, "") || path;
      return { label, path };
    }

    function documentTargetFromSelectedPath(path) {
      const selected = String(path || "").trim();
      const root = String(runtimeState.activeProjectRoot || "").replace(/\/+$/, "");
      if (!selected) {
        return null;
      }
      let relativePath = selected;
      if (root && selected.startsWith(`${root}/`)) {
        relativePath = selected.slice(root.length + 1);
      }
      if (relativePath.startsWith("/")) {
        appendOutput(
          `document must be under the active project: ${selected}\n`,
          "error",
        );
        return null;
      }
      return documentTargetFromInput(relativePath);
    }

    function registerDocumentTarget(target) {
      if (!target) {
        return;
      }
      runtimeState.customDocumentTargets = runtimeState.customDocumentTargets.filter(
        (existing) => existing.path !== target.path,
      );
      runtimeState.customDocumentTargets.push(target);
      saveDocumentTargets();
      refreshStageActionPanel();
    }

    function openDocumentTarget(target) {
      if (!target) {
        return;
      }
      registerDocumentTarget(target);
      showDocumentPreview(target);
    }

    function selectOpenDocumentTarget(path) {
      const target = runtimeState.openDocumentTargets.find(
        (candidate) => documentTargetKey(candidate) === path,
      );
      if (!target) {
        return;
      }
      const session = documentationSessionForTarget(target);
      if (session) {
        if (session.session_id === runtimeState.selectedSessionId) {
          showDocumentPreview(target);
          return;
        }
        selectAgentSession(session.session_id).catch((error) => {
          appendOutput(`session switch failed: ${error}\n`, "error");
        });
        return;
      }
      showDocumentPreview(target);
    }

    function artifactKindForPane(item) {
      if (!item) {
        return "";
      }
      if (item.kind === "route") {
        return "route";
      }
      return item.kind || "";
    }

    function artifactPaneIsCorkboard(item) {
      return Boolean(
        item && (item.kind === "corkboard" || item.kind === "creative-corkboard"),
      );
    }

    function artifactPaneIsAgenda(item) {
      return Boolean(item && item.kind === "agenda");
    }

    function artifactPaneIsProviderView(item) {
      return artifactPaneIsCorkboard(item) || artifactPaneIsAgenda(item);
    }

    function artifactRouteUrl(path, version = runtimeState.artifactPreviewVersion) {
      return `${contextUrl(`${path}?embed=1`)}&zoom=${runtimeState.documentZoom}&version=${version}`;
    }

    function artifactPreviewUrl(item) {
      if (!item) {
        return "";
      }
      if (item.kind === "requirements") {
        return artifactRouteUrl("/artifacts/requirements");
      }
      if (artifactPaneIsCorkboard(item)) {
        const board = item.board || item.folder || item.corkboard;
        if (!board) {
          return "";
        }
        const parameters = new URLSearchParams();
        parameters.set("board_id", board.id || board.path);
        if (board.provider) {
          parameters.set("provider", board.provider);
        }
        parameters.set("title", board.label || item.title);
        parameters.set("embed", "1");
        parameters.set("version", String(runtimeState.artifactPreviewVersion));
        return contextUrl(`/artifacts/corkboard?${parameters.toString()}`);
      }
      if (artifactPaneIsAgenda(item)) {
        const agenda = item.agenda || {};
        const parameters = new URLSearchParams();
        if (agenda.provider) parameters.set("provider", agenda.provider);
        parameters.set("embed", "1");
        parameters.set("version", String(runtimeState.artifactPreviewVersion));
        return contextUrl(`/artifacts/agenda?${parameters.toString()}`);
      }
      if (item.kind === "route" && item.path) {
        return artifactRouteUrl(item.path);
      }
      if (item.kind === "document" && item.target) {
        const parameters = new URLSearchParams();
        parameters.set("path", item.target.path);
        parameters.set("title", item.target.label);
        parameters.set("embed", "1");
        parameters.set("create", "1");
        parameters.set("zoom", String(runtimeState.documentZoom));
        parameters.set("version", String(runtimeState.artifactPreviewVersion));
        return contextUrl(`/artifacts/document?${parameters.toString()}`);
      }
      return "";
    }

    function artifactEditUrl(item) {
      if (!item) {
        return "";
      }
      if (artifactPaneIsProviderView(item)) {
        return artifactPreviewUrl(item);
      }
      const parameters = new URLSearchParams();
      parameters.set("artifact", artifactKindForPane(item));
      parameters.set("document_zoom", String(runtimeState.documentZoom));
      parameters.set("font_size", String(artifactEditorFontSize()));
      if (item.kind === "document" && item.target) {
        parameters.set("path", item.target.path);
        parameters.set("title", item.target.label);
        parameters.set("create", "1");
      }
      if (item.kind === "route" && item.path) {
        parameters.set("path", item.path);
        parameters.set("title", item.title);
      }
      return contextUrl(`/artifacts/edit?${parameters.toString()}`);
    }

    function artifactPaneSupportsModeSwitch(item) {
      return item && !artifactPaneIsProviderView(item);
    }

    function artifactPaneSupportsDocumentExport(item) {
      return item && !artifactPaneIsProviderView(item);
    }

    function artifactPaneSupportsDocumentZoom(item) {
      return item && !artifactPaneIsProviderView(item);
    }

    function artifactPreviewsForStage(stage) {
      const frontend = window.ElectroBoyFrontend;
      const workflow = frontend && typeof frontend.workflowForSelection === "function"
        ? frontend.workflowForSelection(runtimeState.workflowMode)
        : null;
      const previews = workflow && workflow.artifactPreviews
        ? workflow.artifactPreviews[stage]
        : [];
      return (previews || []).map((item) => ({ ...item }));
    }

    function setArtifactCompatibilityState(items) {
      const first = items[0] || null;
      runtimeState.artifactPreviewKind = first ? artifactKindForPane(first) : "";
      runtimeState.artifactPreviewDocumentTarget =
        first && first.kind === "document" && first.target ? first.target : null;
    }

    function showArtifactPreviews(items, options = {}) {
      const hasProviderView = items.some(artifactPaneIsProviderView);
      if (!runtimeState.activeProjectRoot && !hasProviderView) {
        hideArtifactPreview();
        return;
      }
      const nextItems = items.filter((item) => artifactPreviewUrl(item));
      if (nextItems.length === 0) {
        hideArtifactPreview();
        return;
      }
      for (const item of nextItems) {
        if (item.kind === "document" && item.target) {
          rememberOpenDocumentTarget(item.target);
        }
      }
      runtimeState.artifactPreviewItems = nextItems;
      runtimeState.manualArtifactPreview = Boolean(options.manual);
      runtimeState.manualArtifactPreviewStage = runtimeState.manualArtifactPreview ? runtimeState.currentWorkflowStage : "";
      runtimeState.artifactPreviewStage = options.stage || runtimeState.currentWorkflowStage;
      setArtifactCompatibilityState(nextItems);
      runtimeState.artifactPaneRequested = true;
      applyStoredArtifactPaneSize();
      renderArtifactPreviewItems();
      applyOutputPaneVisibility();
      connectArtifactEvents();
    }

    function showStageArtifactPreview(stage) {
      const previews = artifactPreviewsForStage(stage);
      if (previews.length === 0) {
        hideArtifactPreview();
        return;
      }
      showArtifactPreviews(previews, { stage });
    }

    function showArtifactPreview(kind, options = {}) {
      if (kind === "document") {
        const target = options.target || runtimeState.artifactPreviewDocumentTarget;
        if (!target) {
          return;
        }
        showArtifactPreviews(
          [
            {
              id: "document",
              kind: "document",
              title: target.label || target.path || "Document",
              target,
            },
          ],
          { manual: true },
        );
        return;
      }
      const item = kind === "requirements"
        ? { id: "requirements", kind: "requirements", title: "Requirements" }
        : null;
      if (item) {
        showArtifactPreviews([item], options);
      }
    }

    function showDocumentPreview(target) {
      if (!target) {
        return;
      }
      rememberOpenDocumentTarget(target);
      showArtifactPreview("document", { target });
      refreshDocumentTargetSwitchers();
    }

    function markArtifactFrameLoading(frame) {
      frame.classList.add("loading");
      frame.addEventListener(
        "load",
        () => {
          frame.classList.remove("loading");
        },
        { once: true },
      );
    }

    function renderArtifactPreviewItems() {
      runtimeApi.elements.artifactPreviewStack.replaceChildren();
      if (runtimeApi.layout.isPopped("artifact")) {
        runtimeApi.elements.artifactPreviewStack.classList.remove("split");
        activeArtifactToolItemId = "";
        dockedFilePaneTools?.refresh();
        return;
      }
      if (runtimeState.artifactPreviewItems.length === 0) {
        const empty = document.createElement("div");
        empty.className = "artifact-workspace-empty";
        empty.textContent = "No document open";
        runtimeApi.elements.artifactPreviewStack.classList.remove("split");
        runtimeApi.elements.artifactPreviewStack.append(empty);
        activeArtifactToolItemId = "";
        dockedFilePaneTools?.refresh();
        return;
      }
      if (!runtimeState.artifactPreviewItems.some(
        (item) => item.id === activeArtifactToolItemId,
      )) {
        activeArtifactToolItemId = runtimeState.artifactPreviewItems[0].id;
      }
      runtimeApi.elements.artifactPreviewStack.classList.toggle("split", runtimeState.artifactPreviewItems.length > 1);
      for (const [index, item] of runtimeState.artifactPreviewItems.entries()) {
        if (index > 0) {
          const divider = document.createElement("div");
          divider.className = "artifact-preview-divider";
          runtimeApi.elements.artifactPreviewStack.append(divider);
        }
        const section = document.createElement("section");
        section.className = "artifact-preview-item";
        section.setAttribute("aria-label", `${item.title} preview`);
        section.addEventListener("pointerenter", () => {
          activateArtifactToolItem(item.id);
        });
        section.addEventListener("focusin", () => {
          activateArtifactToolItem(item.id);
        });

        const header = document.createElement("div");
        header.className = "pane-header";

        const title = document.createElement("span");
        title.className = "pane-title";
        title.textContent = item.title;

        const actions = document.createElement("div");
        actions.className = "pane-actions";
        const supportsZoom = artifactPaneSupportsDocumentZoom(item);
        const supportsExport = artifactPaneSupportsDocumentExport(item);
        const supportsModeSwitch = artifactPaneSupportsModeSwitch(item);

        const zoomControls = document.createElement("div");
        zoomControls.className = "document-zoom-controls";
        zoomControls.setAttribute("aria-label", "Document zoom");

        const zoomOut = document.createElement("button");
        zoomOut.className = "document-zoom-button";
        zoomOut.type = "button";
        zoomOut.title = "Zoom document out";
        zoomOut.setAttribute("aria-label", "Zoom document out");
        zoomOut.dataset.zoom = "out";
        zoomOut.textContent = "-";
        zoomOut.addEventListener("click", () => {
          changeDocumentZoom(-DOCUMENT_ZOOM_STEP);
        });

        const zoomLevel = document.createElement("span");
        zoomLevel.className = "document-zoom-level";
        zoomLevel.textContent = `${runtimeState.documentZoom}%`;

        const zoomIn = document.createElement("button");
        zoomIn.className = "document-zoom-button";
        zoomIn.type = "button";
        zoomIn.title = "Zoom document in";
        zoomIn.setAttribute("aria-label", "Zoom document in");
        zoomIn.dataset.zoom = "in";
        zoomIn.textContent = "+";
        zoomIn.addEventListener("click", () => {
          changeDocumentZoom(DOCUMENT_ZOOM_STEP);
        });

        const refresh = document.createElement("button");
        refresh.className = "pane-popout-button";
        refresh.type = "button";
        refresh.title = `Refresh ${item.title}`;
        refresh.setAttribute("aria-label", `Refresh ${item.title}`);
        refresh.textContent = "Refresh";
        refresh.addEventListener("click", () => refreshArtifactPreview());

        const popout = document.createElement("button");
        popout.className = "pane-popout-button";
        popout.type = "button";
        popout.title = `Pop out ${item.title}`;
        popout.setAttribute("aria-label", `Pop out ${item.title}`);
        popout.textContent = "Pop";
        popout.addEventListener("click", () => {
          popOutArtifactPreview(item);
        });

        let agentButton = null;
        if (item.kind === "document" && item.target) {
          const session = documentationSessionForTarget(item.target);
          agentButton = document.createElement("button");
          agentButton.className = "pane-popout-button";
          agentButton.type = "button";
          if (session) {
            agentButton.textContent = "Agent";
            agentButton.title = `Select the agent for ${item.title}`;
            agentButton.setAttribute(
              "aria-label",
              `Select the agent for ${item.title}`,
            );
            agentButton.classList.toggle(
              "active",
              session.session_id === runtimeState.selectedSessionId,
            );
            agentButton.addEventListener("click", () => {
              selectAgentSession(session.session_id).catch((error) => {
                appendOutput(`session switch failed: ${error}\n`, "error");
              });
            });
          } else {
            agentButton.textContent = "Start agent";
            agentButton.title = `Start an agent for ${item.title}`;
            agentButton.setAttribute(
              "aria-label",
              `Start an agent for ${item.title}`,
            );
            agentButton.addEventListener("click", () => {
              startDocumentationAgent(item.target).catch((error) => {
                appendOutput(`agent start failed: ${error}\n`, "error");
              });
            });
          }
        }

        zoomControls.append(zoomOut, zoomLevel, zoomIn);
        if (supportsZoom) {
          actions.append(zoomControls);
        }
        if (supportsModeSwitch && supportsExport) {
          actions.append(buildDocumentMenu(item));
        } else {
          actions.append(refresh);
        }
        if (agentButton) {
          actions.append(agentButton);
        }
        actions.append(popout);
        if (item.kind === "document") {
          const documentSwitcher = document.createElement("select");
          documentSwitcher.className = "document-target-switcher";
          documentSwitcher.title = "Open documents";
          documentSwitcher.setAttribute("aria-label", "Open documents");
          renderDocumentTargetSwitcher(documentSwitcher);
          documentSwitcher.addEventListener("change", () => {
            selectOpenDocumentTarget(documentSwitcher.value);
          });
          header.append(documentSwitcher, actions);
        } else {
          header.append(title, actions);
        }

        const frame = document.createElement("iframe");
        frame.className = "artifact-preview-frame loading";
        frame.title = `${item.title} preview`;
        frame.setAttribute(
          "sandbox",
          "allow-scripts allow-popups allow-modals allow-same-origin",
        );
        frame.dataset.artifactId = item.id;
        markArtifactFrameLoading(frame);
        frame.addEventListener("load", () => {
          postArtifactEditorFontSize(frame);
          try {
            frame.contentWindow.addEventListener("pointerdown", () => {
              activateArtifactToolItem(item.id);
            });
          } catch (error) {
            // Cross-origin content cannot select the active docked artifact.
          }
          if (item.id === activeArtifactToolItemId) {
            dockedFilePaneTools?.refresh();
          }
        });
        frame.src = item.editing ? artifactEditUrl(item) : artifactPreviewUrl(item);

        section.append(header, frame);
        runtimeApi.elements.artifactPreviewStack.append(section);
      }
      applyDocumentZoom();
      dockedFilePaneTools?.refresh();
    }

    function artifactFrameForItem(item) {
      if (!item) {
        return null;
      }
      const escapedId = CSS.escape(item.id || "");
      return runtimeApi.elements.artifactPreviewStack.querySelector(
        `.artifact-preview-frame[data-artifact-id="${escapedId}"]`,
      );
    }

    function requestArtifactEditorSave(item) {
      const frame = artifactFrameForItem(item);
      if (!frame || !frame.contentWindow) {
        return Promise.resolve(true);
      }
      const token = `artifact-save-${++runtimeState.artifactSaveTokenSequence}`;
      return new Promise((resolve) => {
        const timeout = window.setTimeout(() => {
          runtimeState.pendingArtifactSaves.delete(token);
          resolve(false);
        }, 15000);
        runtimeState.pendingArtifactSaves.set(token, { resolve, timeout });
        frame.contentWindow.postMessage(
          { type: "electroboy-save-request", token },
          window.location.origin,
        );
      });
    }

    async function setArtifactPreviewEditing(item, editing) {
      if (!editing && item && item.editing) {
        const saved = await requestArtifactEditorSave(item);
        if (!saved) {
          appendOutput("preview blocked: save failed\n", "error");
          return;
        }
      }
      item.editing = Boolean(editing);
      renderArtifactPreviewItems();
    }

    function popOutArtifactPreview(item) {
      if (!runtimeState.contextId) {
        appendOutput("create a browser context first\n", "error");
        return;
      }
      const parameters = new URLSearchParams();
      parameters.set("context_id", runtimeState.contextId);
      parameters.set("artifact", artifactKindForPane(item));
      parameters.set("font_size", String(runtimeState.terminalFontSize));
      parameters.set("base_font_size", String(runtimeState.terminalFontSize));
      parameters.set("document_zoom", String(runtimeState.documentZoom));
      if (item.kind === "document" && item.target) {
        parameters.set("document_path", item.target.path);
        parameters.set("document_title", item.target.label);
      }
      if (item.kind === "route" && item.path) {
        parameters.set("artifact_path", item.path);
        parameters.set("artifact_title", item.title);
      }
      if (artifactPaneIsCorkboard(item)) {
        const board = item.board || item.folder || item.corkboard;
        if (board) {
          parameters.set("corkboard_id", board.id || board.path);
          parameters.set("corkboard_title", board.label || item.title);
          if (board.provider) {
            parameters.set("corkboard_provider", board.provider);
          }
        }
      }
      if (artifactPaneIsAgenda(item)) {
        const agenda = item.agenda || {};
        if (agenda.provider) parameters.set("agenda_provider", agenda.provider);
      }
      const popup = window.open(
        `/pane/artifact?${parameters.toString()}`,
        `electroboy-artifact-${item.id}-${runtimeState.contextId}`,
        PANE_POPUP_FEATURES,
      );
      if (!popup) {
        appendOutput("popup was blocked by the browser\n", "error");
      }
    }

    function hideArtifactPreview() {
      runtimeState.artifactPreviewKind = "";
      runtimeState.artifactPreviewDocumentTarget = null;
      runtimeState.artifactPreviewItems = [];
      runtimeState.manualArtifactPreview = false;
      runtimeState.manualArtifactPreviewStage = "";
      runtimeState.artifactPreviewStage = "";
      runtimeState.artifactPaneRequested = runtimeApi.layout.hasPane("artifact");
      closeArtifactEventStream();
      renderArtifactPreviewItems();
      applyOutputPaneVisibility();
    }

    function refreshArtifactPreview(options = {}) {
      const includeEditing = options.includeEditing !== false;
      runtimeState.artifactPreviewVersion += 1;
      for (const frame of runtimeApi.elements.artifactPreviewStack.querySelectorAll(".artifact-preview-frame")) {
        const item = runtimeState.artifactPreviewItems.find(
          (candidate) => candidate.id === frame.dataset.artifactId,
        );
        if (item && item.editing && !includeEditing) {
          continue;
        }
        const url = item && item.editing ? artifactEditUrl(item) : artifactPreviewUrl(item);
        if (url) {
          markArtifactFrameLoading(frame);
          frame.src = url;
        }
      }
    }

    function artifactEventUrl(item) {
      if (!item) {
        return "";
      }
      if (item.kind === "requirements") {
        return contextUrl("/api/artifacts/events?artifact=requirements");
      }
      const parameters = new URLSearchParams();
      if (item.kind === "document" && item.target) {
        parameters.set("artifact", "document");
        parameters.set("path", item.target.path);
        return contextUrl(`/api/artifacts/events?${parameters.toString()}`);
      }
      if (item.kind === "route" && item.path) {
        parameters.set("artifact", "route");
        parameters.set("path", item.path);
        return contextUrl(`/api/artifacts/events?${parameters.toString()}`);
      }
      return "";
    }

    function connectArtifactEvents() {
      closeArtifactEventStream();
      if (!runtimeState.contextId) {
        return;
      }
      const urls = new Set(runtimeState.artifactPreviewItems.map(artifactEventUrl).filter(Boolean));
      for (const url of urls) {
        const source = new EventSource(url);
        source.addEventListener("artifact-event", () => {
          refreshArtifactPreview({ includeEditing: false });
        });
        source.onerror = () => {};
        runtimeState.artifactEventSources.push(source);
      }
    }

    function closeArtifactEventStream() {
      for (const source of runtimeState.artifactEventSources) {
        source.close();
      }
      runtimeState.artifactEventSources = [];
    }

    function stageIsRunning(stage) {
      if (stage === "requirements") {
        return runtimeState.requirementsRunning;
      }
      if (stage === "design") {
        return runtimeState.designRunning;
      }
      if (stage === "design-review") {
        return runtimeState.designReviewRunning;
      }
      return Boolean(genericStageRun(stage).running);
    }

    function syncArtifactPreviewWithProject() {
      if (!runtimeState.activeProjectRoot) {
        if (runtimeState.artifactPreviewItems.some(artifactPaneIsProviderView)) {
          runtimeState.artifactPaneRequested = true;
          applyOutputPaneVisibility();
          connectArtifactEvents();
          return;
        }
        hideArtifactPreview();
        return;
      }
      if (runtimeApi.layout.hasPane("artifact")) {
        runtimeState.artifactPaneRequested = true;
        applyOutputPaneVisibility();
      }
      if (
        runtimeState.manualArtifactPreview
        && runtimeState.artifactPreviewItems.length > 0
      ) {
        runtimeState.manualArtifactPreviewStage = runtimeState.currentWorkflowStage;
        connectArtifactEvents();
        return;
      }
      runtimeState.manualArtifactPreview = false;
      runtimeState.manualArtifactPreviewStage = "";
      if (runtimeState.artifactPreviewStage === runtimeState.currentWorkflowStage && runtimeState.artifactPreviewItems.length > 0) {
        connectArtifactEvents();
        return;
      }
      if (stageIsRunning(runtimeState.currentWorkflowStage)) {
        showStageArtifactPreview(runtimeState.currentWorkflowStage);
        return;
      }
      if (runtimeState.artifactPreviewStage && runtimeState.artifactPreviewStage !== runtimeState.currentWorkflowStage) {
        hideArtifactPreview();
      }
    }

    async function startDocumentationAgent(target = DEFAULT_DOCUMENT_TARGETS[0]) {
      if (!runtimeState.activeProjectRoot) {
        appendOutput("activate a project first\n", "error");
        return;
      }
      const documentTarget = target || DEFAULT_DOCUMENT_TARGETS[0];
      hideStageMenus();
      closeAgentEventStream();
      showProgressPane(false);
      showDocumentPreview(documentTarget);
      setAgentInputVisible(true);
      clearAgentOutput();
      setAgentRunning("documentation", true);
      runtimeApi.elements.agentInput.disabled = false;
      runtimeApi.elements.agentInput.focus();
      appendOutput(
        `$ electroboy document --sidecar --interactive --target ${documentTarget.path}\n`,
        "system",
      );
      const response = await fetch(contextUrl("/api/agents/documentation/start"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: documentTarget.path }),
      });
      const payload = await response.json().catch(() => ({ error: "start failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "start failed"}\n`, "error");
        setAgentRunning("documentation", false);
        return;
      }
      updateProjectState(payload);
      setAgentRunning("documentation", true);
      const sessionId = payload.session_id || runtimeState.selectedSessionId;
      runtimeState.selectedSessionId = sessionId;
      renderSessionSwitcher();
      connectSessionEvents(sessionId);
      sendTerminalResize();
    }

  window.ElectroBoyFrontend.registerModule({
    id: "documents",
    label: "Documents",
    capabilities: ["markdown-preview", "structured-edit", "export"],
    actions: {
      storedDocumentTargets: (runtime, ...args) => invoke(runtime, storedDocumentTargets, args),
      saveDocumentTargets: (runtime, ...args) => invoke(runtime, saveDocumentTargets, args),
      documentExportFormats: (runtime, ...args) => invoke(runtime, documentExportFormats, args),
      documentExportFormat: (runtime, ...args) => invoke(runtime, documentExportFormat, args),
      documentExportPickerTypes: (runtime, ...args) => invoke(runtime, documentExportPickerTypes, args),
      artifactDocumentBaseName: (runtime, ...args) => invoke(runtime, artifactDocumentBaseName, args),
      artifactDocumentExportName: (runtime, ...args) => invoke(runtime, artifactDocumentExportName, args),
      artifactDocumentExportUrl: (runtime, ...args) => invoke(runtime, artifactDocumentExportUrl, args),
      exportArtifactDocument: (runtime, ...args) => invoke(runtime, exportArtifactDocument, args),
      documentTargetKey: (runtime, ...args) => invoke(runtime, documentTargetKey, args),
      documentTargetLabel: (runtime, ...args) => invoke(runtime, documentTargetLabel, args),
      documentTargetForSession: (runtime, ...args) => invoke(runtime, documentTargetForSession, args),
      documentationSessionForTarget: (runtime, ...args) => invoke(runtime, documentationSessionForTarget, args),
      rememberOpenDocumentTarget: (runtime, ...args) => invoke(runtime, rememberOpenDocumentTarget, args),
      syncOpenDocumentTargetsFromSessions: (runtime, ...args) => invoke(runtime, syncOpenDocumentTargetsFromSessions, args),
      renderDocumentTargetSwitcher: (runtime, ...args) => invoke(runtime, renderDocumentTargetSwitcher, args),
      refreshDocumentTargetSwitchers: (runtime, ...args) => invoke(runtime, refreshDocumentTargetSwitchers, args),
      renderDocumentActionPanel: (runtime, ...args) => invoke(runtime, renderDocumentActionPanel, args),
      documentTargetFromInput: (runtime, ...args) => invoke(runtime, documentTargetFromInput, args),
      documentTargetFromSelectedPath: (runtime, ...args) => invoke(runtime, documentTargetFromSelectedPath, args),
      registerDocumentTarget: (runtime, ...args) => invoke(runtime, registerDocumentTarget, args),
      openDocumentTarget: (runtime, ...args) => invoke(runtime, openDocumentTarget, args),
      selectOpenDocumentTarget: (runtime, ...args) => invoke(runtime, selectOpenDocumentTarget, args),
      artifactKindForPane: (runtime, ...args) => invoke(runtime, artifactKindForPane, args),
      artifactRouteUrl: (runtime, ...args) => invoke(runtime, artifactRouteUrl, args),
      artifactPreviewUrl: (runtime, ...args) => invoke(runtime, artifactPreviewUrl, args),
      artifactEditUrl: (runtime, ...args) => invoke(runtime, artifactEditUrl, args),
      artifactPaneSupportsModeSwitch: (runtime, ...args) => invoke(runtime, artifactPaneSupportsModeSwitch, args),
      artifactPaneSupportsDocumentExport: (runtime, ...args) => invoke(runtime, artifactPaneSupportsDocumentExport, args),
      artifactPaneSupportsDocumentZoom: (runtime, ...args) => invoke(runtime, artifactPaneSupportsDocumentZoom, args),
      artifactPreviewsForStage: (runtime, ...args) => invoke(runtime, artifactPreviewsForStage, args),
      setArtifactCompatibilityState: (runtime, ...args) => invoke(runtime, setArtifactCompatibilityState, args),
      showArtifactPreviews: (runtime, ...args) => invoke(runtime, showArtifactPreviews, args),
      showStageArtifactPreview: (runtime, ...args) => invoke(runtime, showStageArtifactPreview, args),
      showArtifactPreview: (runtime, ...args) => invoke(runtime, showArtifactPreview, args),
      showDocumentPreview: (runtime, ...args) => invoke(runtime, showDocumentPreview, args),
      markArtifactFrameLoading: (runtime, ...args) => invoke(runtime, markArtifactFrameLoading, args),
      renderArtifactPreviewItems: (runtime, ...args) => invoke(runtime, renderArtifactPreviewItems, args),
      artifactFrameForItem: (runtime, ...args) => invoke(runtime, artifactFrameForItem, args),
      requestArtifactEditorSave: (runtime, ...args) => invoke(runtime, requestArtifactEditorSave, args),
      setArtifactPreviewEditing: (runtime, ...args) => invoke(runtime, setArtifactPreviewEditing, args),
      popOutArtifactPreview: (runtime, ...args) => invoke(runtime, popOutArtifactPreview, args),
      hideArtifactPreview: (runtime, ...args) => invoke(runtime, hideArtifactPreview, args),
      refreshArtifactPreview: (runtime, ...args) => invoke(runtime, refreshArtifactPreview, args),
      artifactEventUrl: (runtime, ...args) => invoke(runtime, artifactEventUrl, args),
      connectArtifactEvents: (runtime, ...args) => invoke(runtime, connectArtifactEvents, args),
      closeArtifactEventStream: (runtime, ...args) => invoke(runtime, closeArtifactEventStream, args),
      stageIsRunning: (runtime, ...args) => invoke(runtime, stageIsRunning, args),
      syncArtifactPreviewWithProject: (runtime, ...args) => invoke(runtime, syncArtifactPreviewWithProject, args),
      startDocumentationAgent: (runtime, ...args) => invoke(runtime, startDocumentationAgent, args),
    },
    mount: bindRuntime,
  });
})();
