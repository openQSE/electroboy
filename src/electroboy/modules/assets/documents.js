(function () {
  "use strict";

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
          JSON.stringify(customDocumentTargets),
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
        agentSessions.find((session) => {
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
      const existingIndex = openDocumentTargets.findIndex(
        (candidate) => documentTargetKey(candidate) === path,
      );
      if (existingIndex >= 0) {
        openDocumentTargets.splice(existingIndex, 1, storedTarget);
      } else {
        openDocumentTargets.push(storedTarget);
      }
    }

    function syncOpenDocumentTargetsFromSessions() {
      for (const session of agentSessions) {
        const target = documentTargetForSession(session);
        if (target) {
          rememberOpenDocumentTarget(target);
        }
      }
      refreshDocumentTargetSwitchers();
    }

    function renderDocumentTargetSwitcher(select) {
      select.replaceChildren();
      const targets = openDocumentTargets.length > 0
        ? openDocumentTargets
        : artifactPreviewDocumentTarget
          ? [artifactPreviewDocumentTarget]
          : [];
      for (const target of targets) {
        const option = document.createElement("option");
        option.value = target.path;
        option.textContent = documentTargetLabel(target);
        select.append(option);
      }
      select.value = documentTargetKey(artifactPreviewDocumentTarget);
      select.disabled = targets.length <= 1;
    }

    function refreshDocumentTargetSwitchers() {
      for (const select of artifactPreviewStack.querySelectorAll(
        ".document-target-switcher",
      )) {
        renderDocumentTargetSwitcher(select);
      }
    }

    function renderDocumentActionPanel(container) {
      container.append(
        stageActionButton({
          label: "Open",
          title: "Choose an existing Markdown file and start the documentation agent.",
          primary: true,
          disabled: !activeProjectRoot,
          run: openDocumentFileBrowser,
        }),
      );
      container.append(
        stageActionButton({
          label: "New",
          title: "Choose where to create a Markdown document and start the agent.",
          disabled: !activeProjectRoot,
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
      const root = String(activeProjectRoot || "").replace(/\/+$/, "");
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
      customDocumentTargets = customDocumentTargets.filter(
        (existing) => existing.path !== target.path,
      );
      customDocumentTargets.push(target);
      saveDocumentTargets();
      refreshStageActionPanel();
    }

    function launchDocumentTarget(target) {
      if (!target) {
        return;
      }
      registerDocumentTarget(target);
      startDocumentationAgent(target);
    }

    function selectOpenDocumentTarget(path) {
      const target = openDocumentTargets.find(
        (candidate) => documentTargetKey(candidate) === path,
      );
      if (!target) {
        return;
      }
      const session = documentationSessionForTarget(target);
      if (session) {
        if (session.session_id === selectedSessionId) {
          showDocumentPreview(target);
          return;
        }
        selectAgentSession(session.session_id).catch((error) => {
          appendOutput(`session switch failed: ${error}\n`, "error");
        });
        return;
      }
      launchDocumentTarget(target);
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

    function artifactRouteUrl(path, version = artifactPreviewVersion) {
      return `${contextUrl(`${path}?embed=1`)}&zoom=${documentZoom}&version=${version}`;
    }

    function artifactPreviewUrl(item) {
      if (!item) {
        return "";
      }
      if (item.kind === "requirements") {
        return artifactRouteUrl("/artifacts/requirements");
      }
      if (item.kind === "creative-corkboard") {
        const board = item.folder || item.corkboard;
        if (!board) {
          return "";
        }
        const parameters = new URLSearchParams();
        parameters.set("path", board.path);
        parameters.set("title", board.label || item.title);
        parameters.set("embed", "1");
        parameters.set("version", String(artifactPreviewVersion));
        return contextUrl(`/artifacts/creative-corkboard?${parameters.toString()}`);
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
        parameters.set("zoom", String(documentZoom));
        parameters.set("version", String(artifactPreviewVersion));
        return contextUrl(`/artifacts/document?${parameters.toString()}`);
      }
      return "";
    }

    function artifactEditUrl(item) {
      if (!item) {
        return "";
      }
      if (item.kind === "creative-corkboard") {
        return artifactPreviewUrl(item);
      }
      const parameters = new URLSearchParams();
      parameters.set("artifact", artifactKindForPane(item));
      parameters.set("document_zoom", String(documentZoom));
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
      return item && item.kind !== "creative-corkboard";
    }

    function artifactPaneSupportsDocumentExport(item) {
      return item && item.kind !== "creative-corkboard";
    }

    function artifactPaneSupportsDocumentZoom(item) {
      return item && item.kind !== "creative-corkboard";
    }

    function artifactPreviewsForStage(stage) {
      const frontend = window.ElectroBoyFrontend;
      const workflow = frontend && typeof frontend.workflowForSelection === "function"
        ? frontend.workflowForSelection(workflowMode)
        : null;
      const previews = workflow && workflow.artifactPreviews
        ? workflow.artifactPreviews[stage]
        : [];
      return (previews || []).map((item) => ({ ...item }));
    }

    function setArtifactCompatibilityState(items) {
      const first = items[0] || null;
      artifactPreviewKind = first ? artifactKindForPane(first) : "";
      artifactPreviewDocumentTarget =
        first && first.kind === "document" && first.target ? first.target : null;
    }

    function showArtifactPreviews(items, options = {}) {
      if (!activeProjectRoot) {
        hideArtifactPreview();
        return;
      }
      const nextItems = items.filter((item) => artifactPreviewUrl(item));
      if (nextItems.length === 0) {
        hideArtifactPreview();
        return;
      }
      artifactPreviewItems = nextItems;
      manualArtifactPreview = Boolean(options.manual);
      manualArtifactPreviewStage = manualArtifactPreview ? currentWorkflowStage : "";
      artifactPreviewStage = options.stage || currentWorkflowStage;
      setArtifactCompatibilityState(nextItems);
      artifactPaneRequested = true;
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
        const target = options.target || artifactPreviewDocumentTarget;
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
      artifactPreviewStack.replaceChildren();
      if (poppedPanes.has("artifact")) {
        artifactPreviewStack.classList.remove("split");
        return;
      }
      artifactPreviewStack.classList.toggle("split", artifactPreviewItems.length > 1);
      for (const [index, item] of artifactPreviewItems.entries()) {
        if (index > 0) {
          const divider = document.createElement("div");
          divider.className = "artifact-preview-divider";
          artifactPreviewStack.append(divider);
        }
        const section = document.createElement("section");
        section.className = "artifact-preview-item";
        section.setAttribute("aria-label", `${item.title} preview`);

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
        zoomLevel.textContent = `${documentZoom}%`;

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
        refresh.addEventListener("click", refreshArtifactPreview);

        const preview = document.createElement("button");
        preview.className = "pane-popout-button";
        preview.type = "button";
        preview.title = `Preview ${item.title}`;
        preview.setAttribute("aria-label", `Preview ${item.title}`);
        preview.textContent = "Preview";
        preview.classList.toggle("active", !item.editing);
        preview.addEventListener("click", () => {
          setArtifactPreviewEditing(item, false);
        });

        const edit = document.createElement("button");
        edit.className = "pane-popout-button";
        edit.type = "button";
        edit.title = `Edit ${item.title}`;
        edit.setAttribute("aria-label", `Edit ${item.title}`);
        edit.textContent = "Edit";
        edit.classList.toggle("active", Boolean(item.editing));
        edit.addEventListener("click", () => {
          setArtifactPreviewEditing(item, true);
        });

        const exportFormat = document.createElement("select");
        exportFormat.className = "document-export-format";
        exportFormat.title = `Export format for ${item.title}`;
        exportFormat.setAttribute("aria-label", `Export format for ${item.title}`);
        for (const format of documentExportFormats()) {
          const option = document.createElement("option");
          option.value = format.value;
          option.textContent = format.label;
          exportFormat.append(option);
        }

        const exportButton = document.createElement("button");
        exportButton.className = "pane-popout-button";
        exportButton.type = "button";
        exportButton.title = `Export ${item.title}`;
        exportButton.setAttribute("aria-label", `Export ${item.title}`);
        exportButton.textContent = "Export";
        exportButton.addEventListener("click", () => {
          exportArtifactDocument(item, exportFormat.value).catch((error) => {
            appendOutput(`export failed: ${error}\n`, "error");
          });
        });

        const popout = document.createElement("button");
        popout.className = "pane-popout-button";
        popout.type = "button";
        popout.title = `Pop out ${item.title}`;
        popout.setAttribute("aria-label", `Pop out ${item.title}`);
        popout.textContent = "Pop";
        popout.addEventListener("click", () => {
          popOutArtifactPreview(item);
        });

        zoomControls.append(zoomOut, zoomLevel, zoomIn);
        if (supportsZoom) {
          actions.append(zoomControls);
        }
        if (supportsExport) {
          actions.append(exportFormat, exportButton);
        }
        actions.append(refresh);
        if (supportsModeSwitch) {
          actions.append(preview, edit);
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
        });
        frame.src = item.editing ? artifactEditUrl(item) : artifactPreviewUrl(item);

        section.append(header, frame);
        artifactPreviewStack.append(section);
      }
      applyDocumentZoom();
    }

    function artifactFrameForItem(item) {
      if (!item) {
        return null;
      }
      const escapedId = CSS.escape(item.id || "");
      return artifactPreviewStack.querySelector(
        `.artifact-preview-frame[data-artifact-id="${escapedId}"]`,
      );
    }

    function requestArtifactEditorSave(item) {
      const frame = artifactFrameForItem(item);
      if (!frame || !frame.contentWindow) {
        return Promise.resolve(true);
      }
      const token = `artifact-save-${++artifactSaveTokenSequence}`;
      return new Promise((resolve) => {
        const timeout = window.setTimeout(() => {
          pendingArtifactSaves.delete(token);
          resolve(false);
        }, 15000);
        pendingArtifactSaves.set(token, { resolve, timeout });
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
      if (item.kind === "creative-corkboard") {
        popOutPane("artifact", item);
        return;
      }
      if (!contextId) {
        appendOutput("create a browser context first\n", "error");
        return;
      }
      const parameters = new URLSearchParams();
      parameters.set("context_id", contextId);
      parameters.set("artifact", artifactKindForPane(item));
      parameters.set("font_size", String(terminalFontSize));
      parameters.set("base_font_size", String(terminalFontSize));
      parameters.set("document_zoom", String(documentZoom));
      if (item.kind === "document" && item.target) {
        parameters.set("document_path", item.target.path);
        parameters.set("document_title", item.target.label);
      }
      if (item.kind === "route" && item.path) {
        parameters.set("artifact_path", item.path);
        parameters.set("artifact_title", item.title);
      }
      if (item.kind === "creative-corkboard" && item.folder) {
        parameters.set("folder_path", item.folder.path);
        parameters.set("folder_title", item.folder.label || item.title);
      }
      if (item.kind === "creative-corkboard" && item.corkboard) {
        parameters.set("corkboard_path", item.corkboard.path);
        parameters.set("corkboard_title", item.corkboard.label || item.title);
      }
      const popup = window.open(
        `/pane/artifact?${parameters.toString()}`,
        `electroboy-artifact-${item.id}-${contextId}`,
        PANE_POPUP_FEATURES,
      );
      if (!popup) {
        appendOutput("popup was blocked by the browser\n", "error");
      }
    }

    function hideArtifactPreview() {
      artifactPreviewKind = "";
      artifactPreviewDocumentTarget = null;
      artifactPreviewItems = [];
      manualArtifactPreview = false;
      manualArtifactPreviewStage = "";
      artifactPreviewStage = "";
      artifactPaneRequested = false;
      closeArtifactEventStream();
      artifactPreviewStack.replaceChildren();
      artifactPreviewStack.classList.remove("split");
      applyOutputPaneVisibility();
    }

    function refreshArtifactPreview(options = {}) {
      const includeEditing = options.includeEditing !== false;
      artifactPreviewVersion += 1;
      for (const frame of artifactPreviewStack.querySelectorAll(".artifact-preview-frame")) {
        const item = artifactPreviewItems.find(
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
      if (!contextId) {
        return;
      }
      const urls = new Set(artifactPreviewItems.map(artifactEventUrl).filter(Boolean));
      for (const url of urls) {
        const source = new EventSource(url);
        source.addEventListener("artifact-event", () => {
          refreshArtifactPreview({ includeEditing: false });
        });
        source.onerror = () => {};
        artifactEventSources.push(source);
      }
    }

    function closeArtifactEventStream() {
      for (const source of artifactEventSources) {
        source.close();
      }
      artifactEventSources = [];
    }

    function stageIsRunning(stage) {
      if (stage === "requirements") {
        return requirementsRunning;
      }
      if (stage === "design") {
        return designRunning;
      }
      if (stage === "design-review") {
        return designReviewRunning;
      }
      return Boolean(genericStageRun(stage).running);
    }

    function syncArtifactPreviewWithProject() {
      if (!activeProjectRoot) {
        hideArtifactPreview();
        return;
      }
      if (manualArtifactPreview && manualArtifactPreviewStage === currentWorkflowStage) {
        connectArtifactEvents();
        return;
      }
      manualArtifactPreview = false;
      manualArtifactPreviewStage = "";
      if (artifactPreviewStage === currentWorkflowStage && artifactPreviewItems.length > 0) {
        connectArtifactEvents();
        return;
      }
      if (stageIsRunning(currentWorkflowStage)) {
        showStageArtifactPreview(currentWorkflowStage);
        return;
      }
      if (artifactPreviewStage && artifactPreviewStage !== currentWorkflowStage) {
        hideArtifactPreview();
      }
    }

    async function startDocumentationAgent(target = DEFAULT_DOCUMENT_TARGETS[0]) {
      if (!activeProjectRoot) {
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
      agentInput.disabled = false;
      agentInput.focus();
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
      const sessionId = payload.session_id || selectedSessionId;
      selectedSessionId = sessionId;
      renderSessionSwitcher();
      connectSessionEvents(sessionId);
      sendTerminalResize();
    }

  window.ElectroBoyFrontend.registerModule({
    id: "documents",
    label: "Documents",
    capabilities: ["markdown-preview", "structured-edit", "export"],
    actions: {
      storedDocumentTargets: (_runtime, ...args) => storedDocumentTargets(...args),
      saveDocumentTargets: (_runtime, ...args) => saveDocumentTargets(...args),
      documentExportFormats: (_runtime, ...args) => documentExportFormats(...args),
      documentExportFormat: (_runtime, ...args) => documentExportFormat(...args),
      documentExportPickerTypes: (_runtime, ...args) => documentExportPickerTypes(...args),
      artifactDocumentBaseName: (_runtime, ...args) => artifactDocumentBaseName(...args),
      artifactDocumentExportName: (_runtime, ...args) => artifactDocumentExportName(...args),
      artifactDocumentExportUrl: (_runtime, ...args) => artifactDocumentExportUrl(...args),
      exportArtifactDocument: (_runtime, ...args) => exportArtifactDocument(...args),
      documentTargetKey: (_runtime, ...args) => documentTargetKey(...args),
      documentTargetLabel: (_runtime, ...args) => documentTargetLabel(...args),
      documentTargetForSession: (_runtime, ...args) => documentTargetForSession(...args),
      documentationSessionForTarget: (_runtime, ...args) => documentationSessionForTarget(...args),
      rememberOpenDocumentTarget: (_runtime, ...args) => rememberOpenDocumentTarget(...args),
      syncOpenDocumentTargetsFromSessions: (_runtime, ...args) => syncOpenDocumentTargetsFromSessions(...args),
      renderDocumentTargetSwitcher: (_runtime, ...args) => renderDocumentTargetSwitcher(...args),
      refreshDocumentTargetSwitchers: (_runtime, ...args) => refreshDocumentTargetSwitchers(...args),
      renderDocumentActionPanel: (_runtime, ...args) => renderDocumentActionPanel(...args),
      documentTargetFromInput: (_runtime, ...args) => documentTargetFromInput(...args),
      documentTargetFromSelectedPath: (_runtime, ...args) => documentTargetFromSelectedPath(...args),
      registerDocumentTarget: (_runtime, ...args) => registerDocumentTarget(...args),
      launchDocumentTarget: (_runtime, ...args) => launchDocumentTarget(...args),
      selectOpenDocumentTarget: (_runtime, ...args) => selectOpenDocumentTarget(...args),
      artifactKindForPane: (_runtime, ...args) => artifactKindForPane(...args),
      artifactRouteUrl: (_runtime, ...args) => artifactRouteUrl(...args),
      artifactPreviewUrl: (_runtime, ...args) => artifactPreviewUrl(...args),
      artifactEditUrl: (_runtime, ...args) => artifactEditUrl(...args),
      artifactPaneSupportsModeSwitch: (_runtime, ...args) => artifactPaneSupportsModeSwitch(...args),
      artifactPaneSupportsDocumentExport: (_runtime, ...args) => artifactPaneSupportsDocumentExport(...args),
      artifactPaneSupportsDocumentZoom: (_runtime, ...args) => artifactPaneSupportsDocumentZoom(...args),
      artifactPreviewsForStage: (_runtime, ...args) => artifactPreviewsForStage(...args),
      setArtifactCompatibilityState: (_runtime, ...args) => setArtifactCompatibilityState(...args),
      showArtifactPreviews: (_runtime, ...args) => showArtifactPreviews(...args),
      showStageArtifactPreview: (_runtime, ...args) => showStageArtifactPreview(...args),
      showArtifactPreview: (_runtime, ...args) => showArtifactPreview(...args),
      showDocumentPreview: (_runtime, ...args) => showDocumentPreview(...args),
      markArtifactFrameLoading: (_runtime, ...args) => markArtifactFrameLoading(...args),
      renderArtifactPreviewItems: (_runtime, ...args) => renderArtifactPreviewItems(...args),
      artifactFrameForItem: (_runtime, ...args) => artifactFrameForItem(...args),
      requestArtifactEditorSave: (_runtime, ...args) => requestArtifactEditorSave(...args),
      setArtifactPreviewEditing: (_runtime, ...args) => setArtifactPreviewEditing(...args),
      popOutArtifactPreview: (_runtime, ...args) => popOutArtifactPreview(...args),
      hideArtifactPreview: (_runtime, ...args) => hideArtifactPreview(...args),
      refreshArtifactPreview: (_runtime, ...args) => refreshArtifactPreview(...args),
      artifactEventUrl: (_runtime, ...args) => artifactEventUrl(...args),
      connectArtifactEvents: (_runtime, ...args) => connectArtifactEvents(...args),
      closeArtifactEventStream: (_runtime, ...args) => closeArtifactEventStream(...args),
      stageIsRunning: (_runtime, ...args) => stageIsRunning(...args),
      syncArtifactPreviewWithProject: (_runtime, ...args) => syncArtifactPreviewWithProject(...args),
      startDocumentationAgent: (_runtime, ...args) => startDocumentationAgent(...args),
    },
  });
})();
