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
    const controls = options.controls || {};
    const actions = options.actions || {};
    const onBoardChange = typeof options.onBoardChange === "function"
      ? options.onBoardChange
      : () => {};
    let boardState = null;
    const boundFrames = new WeakSet();

    function target() {
      return getTarget() || {};
    }

    function actionErrorMessage(error) {
      return error && error.message ? error.message : String(error);
    }

    function setActionStatus(message, error = false) {
      actionStatus.textContent = message || "";
      actionStatus.classList.toggle("error", error);
    }

    function runAction(name, fallback, ...args) {
      try {
        const result = typeof actions[name] === "function"
          ? actions[name](target(), ...args)
          : fallback(...args);
        Promise.resolve(result).catch((error) => {
          setActionStatus(actionErrorMessage(error), true);
        });
      } catch (error) {
        setActionStatus(actionErrorMessage(error), true);
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

    const actionsBody = controller.addSection("actions", "Actions");
    const pop = button("Pop", () => {
      runAction("pop", () => {});
    });
    const fileMenu = menu("File", "pane-tool-file-menu");
    const open = menuButton("Open", () => {
      runAction("open", () => {});
    });
    const create = menuButton("New", () => {
      runAction("new", () => {});
    });
    const refreshButton = menuButton("Refresh", () => {
      runAction("refresh", () => controls.refresh?.click());
    });
    fileMenu.list.append(open, create, refreshButton);
    const actionStatus = document.createElement("div");
    actionStatus.className = "pane-tool-status";
    actionsBody.append(pop, fileMenu.details, actionStatus);

    const boardViewBody = controller.addSection("corkboard-view", "Board view");

    function postBoardTool(action, value = null) {
      const frame = getFrame();
      if (!frame || !frame.contentWindow) return;
      frame.contentWindow.postMessage({
        type: "electroboy-corkboard-tool",
        action,
        value,
      }, window.location.origin);
    }

    function labeledSelect(labelText, ariaLabel, action) {
      const wrapper = document.createElement("label");
      wrapper.className = "pane-tool-slider";
      const label = document.createElement("span");
      label.textContent = labelText;
      const select = document.createElement("select");
      select.setAttribute("aria-label", ariaLabel);
      select.addEventListener("change", () => postBoardTool(action, select.value));
      wrapper.append(label, select);
      boardViewBody.append(wrapper);
      return { wrapper, select };
    }

    const boardPicker = labeledSelect("Board", "Corkboard", "select-board");
    const boardLayout = labeledSelect("Layout", "Corkboard layout", "set-layout");
    const organizeMenu = menu("Auto-organize", "pane-tool-organize-menu");
    const organizeGrid = menuButton("Grid", () => {
      postBoardTool("organize-grid");
    });
    const organizeLayout = menuButton("Layout", () => {
      postBoardTool("organize-layout");
    });
    organizeMenu.list.append(organizeGrid, organizeLayout);
    const autoLayout = document.createElement("label");
    autoLayout.className = "pane-tool-toggle";
    const autoLayoutInput = document.createElement("input");
    autoLayoutInput.type = "checkbox";
    autoLayoutInput.addEventListener("change", () => {
      postBoardTool("set-auto-layout", autoLayoutInput.checked);
    });
    const autoLayoutText = document.createElement("span");
    autoLayoutText.textContent = "Auto layout on card resize";
    autoLayout.append(autoLayoutInput, autoLayoutText);
    const undoOrganize = button("Undo organize", () => {
      postBoardTool("undo-organize");
    });
    boardViewBody.append(organizeMenu.details, autoLayout, undoOrganize);

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
      exportHelp.textContent = "Preparing image...";
      exportHelp.classList.remove("error");
      postBoardTool("export", exportFormat.value);
    }, "primary");
    const exportHelp = document.createElement("div");
    exportHelp.className = "pane-tool-status";
    boardExportBody.append(exportFormat, exportBoard, exportHelp);

    function applyBoardState(state) {
      boardState = state;
      const boards = Array.isArray(state.boards) ? state.boards : [];
      boardPicker.select.replaceChildren(...boards.map((entry) => {
        const option = document.createElement("option");
        option.value = String(entry.id || "");
        option.textContent = String(entry.title || entry.id || "Untitled board");
        return option;
      }));
      boardPicker.wrapper.hidden = boards.length < 2;
      boardPicker.select.value = String(state.boardPath || "");
      const layouts = Array.isArray(state.layoutModes) ? state.layoutModes : [];
      boardLayout.select.replaceChildren(...layouts.map((mode) => {
        const option = document.createElement("option");
        option.value = mode;
        option.textContent = mode === "grid" ? "Grid" : "Freeform";
        return option;
      }));
      boardLayout.wrapper.hidden = layouts.length < 2;
      boardLayout.select.value = String(state.layoutMode || "");
      organizeMenu.details.hidden = !state.canAutoOrganize;
      autoLayout.hidden = !state.canAutoLayout;
      autoLayoutInput.checked = Boolean(state.autoLayoutEnabled);
      undoOrganize.hidden = !state.canUndoOrganize;
      boardZoom.input.value = String(state.zoomSlider ?? 500);
      boardZoom.output.textContent = state.zoomLabel || "100%";
      cardSize.input.value = String(state.cardScale ?? 100);
      cardSize.output.textContent = `${state.cardScale ?? 100}%`;
      cardFont.input.value = String(state.cardFontScale ?? 125);
      cardFont.output.textContent = `${state.cardFontScale ?? 125}%`;
      const supportsCardColor = state.canChangeColor !== false;
      cardColor.disabled = !supportsCardColor;
      randomColor.disabled = !supportsCardColor;
      if (state.selectedColor) cardColor.value = state.selectedColor;
      colorHelp.textContent = !supportsCardColor
        ? "This board does not support card color changes."
        : state.hasSelection
        ? "Changes are saved to the selected card."
        : "Select a card, then choose a color.";
    }

    function handleBoardMessage(event) {
      const frame = getFrame();
      if (!frame || event.source !== frame.contentWindow) return;
      const data = event.data || {};
      if (data.type === "electroboy-corkboard-tool-state") {
        const currentPath = String(target().path || "");
        if (currentPath && data.boardPath && currentPath !== data.boardPath) return;
        applyBoardState(data);
        onBoardChange(data);
      } else if (data.type === "electroboy-corkboard-selected") {
        onBoardChange(data);
      } else if (data.type === "electroboy-corkboard-exported") {
        exportHelp.textContent = data.error
          || `Exported ${String(data.format || "image").toUpperCase()}`;
        exportHelp.classList.toggle("error", Boolean(data.error));
      }
    }

    function bindFrameTools() {
      try {
        const frame = getFrame();
        if (!frame || !frame.contentWindow) return;
        controller.bindKeyboardTarget(frame.contentWindow);
        if (!boundFrames.has(frame)) {
          boundFrames.add(frame);
          frame.addEventListener("load", () => {
            controller.bindKeyboardTarget(frame.contentWindow);
            postBoardTool("request-state");
          });
        }
        postBoardTool("request-state");
      } catch (error) {
        // Cross-origin content keeps its native keyboard behavior.
      }
    }

    function refresh() {
      const current = target();
      const hasBoard = current.kind === "corkboard" ||
        current.kind === "creative-corkboard";
      pop.hidden = typeof actions.pop !== "function" || current.canPop === false;
      open.hidden = typeof actions.open !== "function";
      create.hidden = typeof actions.new !== "function";
      refreshButton.hidden = current.canRefresh === false;
      fileMenu.details.hidden = open.hidden && create.hidden && refreshButton.hidden;
      actionsBody.closest("details").hidden = pop.hidden && fileMenu.details.hidden;
      boardViewBody.closest("details").hidden = !hasBoard;
      boardColorBody.closest("details").hidden = !hasBoard;
      boardExportBody.closest("details").hidden = !hasBoard;
      if (controls.refresh) controls.refresh.hidden = true;
      controller.setEnabled(true);
      setActionStatus("");
      if (hasBoard) {
        if (boardState && current.path && boardState.boardPath !== current.path) {
          boardState = null;
        }
        applyBoardState(boardState || {});
        window.setTimeout(() => postBoardTool("request-state"), 0);
      }
      bindFrameTools();
    }

    window.addEventListener("message", handleBoardMessage);
    if (fixedFrame) fixedFrame.addEventListener("load", bindFrameTools);
    refresh();

    return { refresh };
  }

  window.ElectroBoyCorkboardPaneTools = { mount };
})();
