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
    const frame = options.frame;
    const getTarget = options.getTarget;
    const contextUrl = options.contextUrl;
    const controls = options.controls;

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
    controls.zoom.hidden = false;
    viewBody.append(controls.zoom);

    const actionsBody = controller.addSection("actions", "Actions");
    const startAgent = button("Start agent", () => {
      startFileAgent().catch((error) => setActionStatus(String(error), true));
    }, "primary");
    const modeRow = document.createElement("div");
    modeRow.className = "pane-tool-button-row";
    modeRow.append(controls.preview, controls.edit);
    const actionRow = document.createElement("div");
    actionRow.className = "pane-tool-button-row";
    actionRow.append(controls.refresh, controls.exportFormat, controls.exportButton);
    const actionStatus = document.createElement("div");
    actionStatus.className = "pane-tool-status";
    actionsBody.append(startAgent, modeRow, actionRow, actionStatus);

    function searchable() {
      const target = getTarget();
      return target.kind === "document" || target.kind === "requirements";
    }

    function frameText() {
      try {
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
        controller.bindKeyboardTarget(frame.contentWindow);
        frame.contentWindow.addEventListener("keydown", handleFindShortcut);
      } catch (error) {
        // Cross-origin content keeps its native keyboard behavior.
      }
    }

    function setActionStatus(message, error = false) {
      actionStatus.textContent = message || "";
      actionStatus.classList.toggle("error", error);
    }

    async function startFileAgent() {
      const target = getTarget();
      if (target.kind !== "document" || !target.path) {
        setActionStatus("This content does not support a file agent.", true);
        return;
      }
      setActionStatus("Starting agent…");
      const response = await fetch(contextUrl("/api/agents/documentation/start"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: target.path }),
      });
      const payload = await response.json().catch(() => ({ error: "start failed" }));
      if (!response.ok) {
        setActionStatus(payload.error || "start failed", true);
        return;
      }
      setActionStatus("Agent started");
    }

    function refresh() {
      const target = getTarget();
      const canSearch = searchable();
      findBody.closest("details").hidden = !canSearch;
      startAgent.hidden = target.kind !== "document" || !target.path;
      const isBoard = target.kind === "corkboard" || target.kind === "creative-corkboard";
      viewBody.closest("details").hidden = isBoard;
      controls.preview.hidden = isBoard;
      controls.edit.hidden = isBoard;
      controls.exportFormat.hidden = isBoard;
      controls.exportButton.hidden = isBoard;
      setActionStatus("");
    }

    findInput.addEventListener("input", () => find(1));
    findInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        find(event.shiftKey ? -1 : 1);
      } else if (event.key === "Escape") {
        event.preventDefault();
        controller.close();
        frame.focus();
      }
    });
    matchCase.addEventListener("change", () => find(1));
    window.addEventListener("keydown", handleFindShortcut);
    frame.addEventListener("load", bindFrameShortcuts);
    bindFrameShortcuts();
    refresh();

    return { refresh };
  }

  window.ElectroBoyFilePaneTools = { mount };
})();
