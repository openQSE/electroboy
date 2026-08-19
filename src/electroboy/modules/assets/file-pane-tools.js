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

  function mount(options) {
    const controller = options.controller;
    const fixedFrame = options.frame || null;
    const getFrame = typeof options.getFrame === "function"
      ? options.getFrame
      : () => fixedFrame;
    const getTarget = options.getTarget;
    const contextUrl = options.contextUrl;
    const controls = options.controls || {};
    const actions = options.actions || {};
    let boardState = null;
    const boundFrames = new WeakSet();

    function target() {
      return getTarget() || {};
    }

    function runAction(name, fallback, ...args) {
      try {
        const result = typeof actions[name] === "function"
          ? actions[name](target(), ...args)
          : fallback(...args);
        Promise.resolve(result).catch((error) => {
          setActionStatus(String(error), true);
        });
      } catch (error) {
        setActionStatus(String(error), true);
      }
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

    function menuButton(label, action) {
      return button(label, action, "pane-tool-menu-button");
    }

    const findBody = controller.addSection("find", "Find");
    const findRow = document.createElement("div");
    findRow.className = "pane-tool-find-row";
    const findInput = document.createElement("input");
    findInput.type = "search";
    findInput.placeholder = "Find in file";
    findInput.setAttribute("aria-label", "Find in file");
    const previous = button("↑", () => find(-1));
    previous.title = "Previous match (Shift+Enter)";
    const next = button("↓", () => find(1));
    next.title = "Next match (Enter)";
    findRow.append(findInput, previous, next);

    const findOptions = document.createElement("div");
    findOptions.className = "pane-tool-find-options";
    const caseLabel = document.createElement("label");
    const matchCase = document.createElement("input");
    matchCase.type = "checkbox";
    caseLabel.append(matchCase, " Match case");
    const findStatus = document.createElement("span");
    findStatus.textContent = "No search";
    findOptions.append(caseLabel, findStatus);
    findBody.append(findRow, findOptions);

    const viewBody = controller.addSection("view", "View");
    let zoomLevel = null;
    if (controls.zoom) {
      controls.zoom.hidden = false;
      viewBody.append(controls.zoom);
    } else {
      const zoomRow = document.createElement("div");
      zoomRow.className = "pane-tool-zoom-row";
      const zoomOut = menuButton("−", () => runAction("zoomOut", () => {}));
      zoomOut.title = "Zoom document out";
      zoomLevel = document.createElement("span");
      zoomLevel.className = "pane-tool-zoom-level";
      const zoomIn = menuButton("+", () => runAction("zoomIn", () => {}));
      zoomIn.title = "Zoom document in";
      zoomRow.append(zoomOut, zoomLevel, zoomIn);
      viewBody.append(zoomRow);
    }

    const actionsBody = controller.addSection("actions", "Actions");
    const startAgent = button("Start agent", () => {
      runAction("startAgent", startFileAgent);
    }, "primary");

    const fileMenu = menu("File", "pane-tool-file-menu");
    const preview = menuButton("Preview", () => {
      runAction("preview", () => controls.preview?.click());
    });
    const edit = menuButton("Edit", () => {
      runAction("edit", () => controls.edit?.click());
    });
    const refreshButton = menuButton("Refresh", () => {
      runAction("refresh", () => controls.refresh?.click());
    });
    fileMenu.list.append(preview, edit, refreshButton);

    const exportMenu = menu("Export", "pane-tool-export-menu");
    for (const [format, label] of [
      ["markdown", "Markdown"],
      ["pdf", "PDF"],
      ["docx", "DOCX"],
    ]) {
      exportMenu.list.append(
        menuButton(label, () => {
          runAction("export", () => {
            if (controls.exportFormat) controls.exportFormat.value = format;
            controls.exportButton?.click();
          }, format);
        }),
      );
    }
    fileMenu.list.append(exportMenu.details);

    const actionStatus = document.createElement("div");
    actionStatus.className = "pane-tool-status";
    actionsBody.append(startAgent, fileMenu.details, actionStatus);

    const boardViewBody = controller.addSection("corkboard-view", "Board view");

    function boardSlider(label, min, max, step, action) {
      const wrapper = document.createElement("label");
      wrapper.className = "pane-tool-slider";
      const heading = document.createElement("span");
      const text = document.createElement("span");
      text.textContent = label;
      const output = document.createElement("output");
      heading.append(text, output);
      const input = document.createElement("input");
      input.type = "range";
      input.min = String(min);
      input.max = String(max);
      input.step = String(step);
      input.addEventListener("input", () => {
        postBoardTool(action, input.value);
      });
      wrapper.append(heading, input);
      boardViewBody.append(wrapper);
      return { input, output };
    }

    const boardZoom = boardSlider("Board zoom", 0, 1000, 1, "set-board-zoom");
    const cardSize = boardSlider("Card size", 100, 400, 5, "set-card-size");
    const cardFont = boardSlider("Card font", 75, 200, 5, "set-card-font");

    const boardColorBody = controller.addSection("corkboard-color", "Selected card");
    const colorRow = document.createElement("div");
    colorRow.className = "pane-tool-color-row";
    const cardColor = document.createElement("input");
    cardColor.type = "color";
    cardColor.value = "#fff6cf";
    cardColor.setAttribute("aria-label", "Selected card color");
    const randomColor = button("Random color", () => {
      postBoardTool("random-card-color");
    });
    colorRow.append(cardColor, randomColor);
    const colorHelp = document.createElement("div");
    colorHelp.className = "pane-tool-status";
    colorHelp.textContent = "Select a card to change its color.";
    boardColorBody.append(colorRow, colorHelp);
    cardColor.addEventListener("input", () => {
      postBoardTool("set-card-color", cardColor.value);
    });

    const boardExportBody = controller.addSection("corkboard-export", "Export");
    const exportFormat = document.createElement("select");
    exportFormat.setAttribute("aria-label", "Corkboard image format");
    for (const [value, label] of [["png", "PNG"], ["jpeg", "JPEG"]]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      exportFormat.append(option);
    }
    const exportBoard = button("Export cards", () => {
      exportHelp.textContent = "Preparing image…";
      exportHelp.classList.remove("error");
      postBoardTool("export", exportFormat.value);
    }, "primary");
    const exportHelp = document.createElement("div");
    exportHelp.className = "pane-tool-status";
    boardExportBody.append(exportFormat, exportBoard, exportHelp);

    function postBoardTool(action, value = null) {
      const frame = getFrame();
      if (!frame || !frame.contentWindow) return;
      frame.contentWindow.postMessage({
        type: "electroboy-corkboard-tool",
        action,
        value,
      }, window.location.origin);
    }

    function applyBoardState(state) {
      boardState = state;
      boardZoom.input.value = String(state.zoomSlider ?? 500);
      boardZoom.output.textContent = state.zoomLabel || "100%";
      cardSize.input.value = String(state.cardScale ?? 100);
      cardSize.output.textContent = `${state.cardScale ?? 100}%`;
      cardFont.input.value = String(state.cardFontScale ?? 125);
      cardFont.output.textContent = `${state.cardFontScale ?? 125}%`;
      const canColor = Boolean(state.hasSelection && state.canChangeColor);
      cardColor.disabled = !canColor;
      randomColor.disabled = !canColor;
      if (state.selectedColor) cardColor.value = state.selectedColor;
      colorHelp.textContent = canColor
        ? "Changes are saved to the selected card."
        : "Select a card to change its color.";
    }

    function handleBoardMessage(event) {
      const frame = getFrame();
      if (!frame || event.source !== frame.contentWindow) return;
      const data = event.data || {};
      if (data.type === "electroboy-corkboard-tool-state") {
        const currentPath = String(target().path || "");
        if (currentPath && data.boardPath && currentPath !== data.boardPath) return;
        applyBoardState(data);
      } else if (data.type === "electroboy-corkboard-exported") {
        exportHelp.textContent = data.error
          || `Exported ${String(data.format || "image").toUpperCase()}`;
        exportHelp.classList.toggle("error", Boolean(data.error));
      }
    }

    function searchable() {
      const current = target();
      return current.kind === "document" || current.kind === "requirements";
    }

    function frameText() {
      try {
        const frame = getFrame();
        const documentBody = frame.contentDocument && frame.contentDocument.body;
        if (!documentBody) return "";
        const formText = Array.from(
          documentBody.querySelectorAll("textarea, input[type='text'], [contenteditable='true']"),
        ).map((element) => element.value || element.textContent || "").join("\n");
        return `${documentBody.innerText || ""}\n${formText}`;
      } catch (error) {
        return "";
      }
    }

    function matchCount(query) {
      if (!query) return 0;
      const source = matchCase.checked ? frameText() : frameText().toLocaleLowerCase();
      const needle = matchCase.checked ? query : query.toLocaleLowerCase();
      let count = 0;
      let offset = 0;
      while ((offset = source.indexOf(needle, offset)) >= 0) {
        count += 1;
        offset += Math.max(needle.length, 1);
      }
      return count;
    }

    function find(direction) {
      const query = findInput.value;
      if (!query || !searchable()) {
        findStatus.textContent = query ? "Search unavailable" : "No search";
        return;
      }
      let found = false;
      try {
        const frame = getFrame();
        found = frame.contentWindow.find(
          query,
          matchCase.checked,
          direction < 0,
          true,
          false,
          true,
          false,
        );
      } catch (error) {
        found = false;
      }
      const count = matchCount(query);
      findStatus.textContent = count === 1 ? "1 match" : `${count} matches`;
      findStatus.classList.toggle("error", !found && count === 0);
    }

    function handleFindShortcut(event) {
      if (event.ctrlKey && !event.altKey && !event.metaKey && event.key.toLowerCase() === "f") {
        event.preventDefault();
        controller.open("find");
        findInput.select();
      }
    }

    function bindFrameShortcuts() {
      try {
        const frame = getFrame();
        if (!frame || !frame.contentWindow) return;
        controller.bindKeyboardTarget(frame.contentWindow);
        if (!boundFrames.has(frame)) {
          boundFrames.add(frame);
          frame.contentWindow.addEventListener("keydown", handleFindShortcut);
          frame.addEventListener("load", () => {
            controller.bindKeyboardTarget(frame.contentWindow);
            frame.contentWindow.addEventListener("keydown", handleFindShortcut);
            if (target().kind === "corkboard" || target().kind === "creative-corkboard") {
              postBoardTool("request-state");
            }
          });
        }
        if (target().kind === "corkboard" || target().kind === "creative-corkboard") {
          postBoardTool("request-state");
        }
      } catch (error) {
        // Cross-origin content keeps its native keyboard behavior.
      }
    }

    function setActionStatus(message, error = false) {
      actionStatus.textContent = message || "";
      actionStatus.classList.toggle("error", error);
    }

    async function startFileAgent() {
      const current = target();
      if (current.kind !== "document" || !current.path) {
        setActionStatus("This content does not support a file agent.", true);
        return;
      }
      setActionStatus("Starting agent…");
      const response = await fetch(contextUrl("/api/agents/documentation/start"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: current.path }),
      });
      const payload = await response.json().catch(() => ({ error: "start failed" }));
      if (!response.ok) {
        setActionStatus(payload.error || "start failed", true);
        return;
      }
      setActionStatus("Agent started");
    }

    function refresh() {
      const current = target();
      const hasTarget = Boolean(current.kind);
      const canSearch = searchable();
      findBody.closest("details").hidden = !canSearch;
      startAgent.hidden = current.kind !== "document" || !current.path;
      const isBoard = current.kind === "corkboard" || current.kind === "creative-corkboard";
      viewBody.closest("details").hidden = isBoard;
      boardViewBody.closest("details").hidden = !isBoard;
      boardColorBody.closest("details").hidden = !isBoard;
      boardExportBody.closest("details").hidden = !isBoard;
      actionsBody.closest("details").hidden = isBoard;
      preview.hidden = isBoard;
      edit.hidden = isBoard;
      exportMenu.details.hidden = isBoard;
      preview.setAttribute("aria-pressed", String(!current.editing));
      edit.setAttribute("aria-pressed", String(Boolean(current.editing)));
      if (controls.preview) controls.preview.hidden = true;
      if (controls.edit) controls.edit.hidden = true;
      if (controls.refresh) controls.refresh.hidden = true;
      if (controls.exportFormat) controls.exportFormat.hidden = true;
      if (controls.exportButton) controls.exportButton.hidden = true;
      if (zoomLevel) {
        zoomLevel.textContent = typeof actions.zoomLabel === "function"
          ? actions.zoomLabel(current)
          : "100%";
      }
      controller.setEnabled(hasTarget);
      bindFrameShortcuts();
      setActionStatus("");
      if (isBoard) {
        if (boardState && current.path && boardState.boardPath !== current.path) {
          boardState = null;
        }
        applyBoardState(boardState || {});
        window.setTimeout(() => postBoardTool("request-state"), 0);
      }
    }

    findInput.addEventListener("input", () => find(1));
    findInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        find(event.shiftKey ? -1 : 1);
      } else if (event.key === "Escape") {
        event.preventDefault();
        controller.close();
        getFrame()?.focus();
      }
    });
    matchCase.addEventListener("change", () => find(1));
    window.addEventListener("keydown", handleFindShortcut);
    window.addEventListener("message", handleBoardMessage);
    if (fixedFrame) fixedFrame.addEventListener("load", bindFrameShortcuts);
    bindFrameShortcuts();
    refresh();

    return { refresh };
  }

  window.ElectroBoyFilePaneTools = { mount };
})();
