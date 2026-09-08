(function () {
  "use strict";

  let terminal = null;
  let terminalFit = null;
  let eventSource = null;
  let paneSync = null;
  let latestProgressState = { entries: [] };
  let backgroundTaskId = "";
  let backgroundActivityIds = new Set();

  function initializeProgressTerminal(runtime) {
    if (terminal || !window.Terminal) {
      return;
    }
    terminal = new window.Terminal(runtime.terminals.options(true, "progress"));
    if (window.FitAddon && window.FitAddon.FitAddon) {
      terminalFit = new window.FitAddon.FitAddon();
      terminal.loadAddon(terminalFit);
    }
    terminal.open(runtime.elements.progressOutput);
    window.ElectroBoyTerminalBehavior.install(terminal);
    runtime.terminals.applyFontSize();
  }

  async function exportProgressLog(runtime) {
    await runtime.downloads.exportMarkdown(
      runtime.http.contextUrl("/api/progress/export"),
      `progress-log-${runtime.downloads.timestamp()}.md`,
    );
  }

  function appendProgressOutput(runtime, text, className = "") {
    if (terminal) {
      terminal.write(runtime.terminals.formatMessage(text, className));
      return;
    }
    const span = document.createElement("span");
    span.textContent = text;
    if (className) {
      span.className = className;
    }
    const output = runtime.elements.progressOutput;
    output.appendChild(span);
    output.scrollTop = output.scrollHeight;
  }

  function resetProgressOutput(runtime) {
    if (runtime.terminals.reset(terminal)) {
      return;
    }
    runtime.elements.progressOutput.replaceChildren();
  }

  function clearProgressOutput(runtime) {
    backgroundTaskId = "";
    backgroundActivityIds = new Set();
    resetProgressOutput(runtime);
  }

  function renderProgressState(runtime, state, publish = false) {
    if (!state || !Array.isArray(state.entries)) {
      return;
    }
    initializeProgressTerminal(runtime);
    latestProgressState = normalizedProgressState(state);
    resetProgressOutput(runtime);
    latestProgressState.entries.forEach((entry) => {
      appendProgressOutput(runtime, entry.text, entry.className);
    });
    if (publish && paneSync) {
      paneSync.publish(latestProgressState);
    }
  }

  function backgroundActivityEntry(activity) {
    const timestamp = String(activity.timestamp || "");
    const time = timestamp.includes("T")
      ? timestamp.split("T")[1].replace(/Z$/, "").split(".")[0]
      : "";
    const prefix = time ? `${time}  ` : "";
    return {
      text: `${prefix}${String(activity.text || "")}\r\n`,
      className: activity.type === "error" ? "error" : "",
    };
  }

  function renderBackgroundTask(runtime, task) {
    if (!task || !task.job_id) {
      return;
    }
    initializeProgressTerminal(runtime);
    const taskId = String(task.job_id);
    const activities = Array.isArray(task.activities) ? task.activities : [];
    if (backgroundTaskId !== taskId) {
      backgroundTaskId = taskId;
      backgroundActivityIds = new Set();
      const entries = [{
        text: `Corkboard generation: ${String(task.title || "Untitled")}\r\n`,
        className: "system",
      }];
      activities.forEach((activity) => {
        backgroundActivityIds.add(String(activity.id || ""));
        entries.push(backgroundActivityEntry(activity));
      });
      renderProgressState(runtime, { entries }, true);
      return;
    }
    const additions = [];
    activities.forEach((activity) => {
      const activityId = String(activity.id || "");
      if (!activityId || backgroundActivityIds.has(activityId)) {
        return;
      }
      backgroundActivityIds.add(activityId);
      additions.push(backgroundActivityEntry(activity));
    });
    if (!additions.length) {
      return;
    }
    latestProgressState = {
      entries: [...latestProgressState.entries, ...additions],
    };
    additions.forEach((entry) => {
      appendProgressOutput(runtime, entry.text, entry.className);
    });
    if (paneSync) {
      paneSync.publish(latestProgressState);
    }
  }

  function normalizedProgressState(state) {
    return {
      entries: state.entries.map((entry) => ({
        text: String(entry.text || ""),
        className: entry.className || "",
      })),
    };
  }

  function progressEntryMatches(left, right) {
    return left.text === right.text && left.className === right.className;
  }

  function progressStateExtends(current, next) {
    if (next.entries.length < current.entries.length) {
      return false;
    }
    return current.entries.every((entry, index) => (
      progressEntryMatches(entry, next.entries[index])
    ));
  }

  function renderProgressStateIncrementally(runtime, state, publish = false) {
    if (!state || !Array.isArray(state.entries)) {
      return;
    }
    const nextState = normalizedProgressState(state);
    if (!progressStateExtends(latestProgressState, nextState)) {
      renderProgressState(runtime, nextState, publish);
      return;
    }
    const additions = nextState.entries.slice(latestProgressState.entries.length);
    if (!additions.length) {
      return;
    }
    initializeProgressTerminal(runtime);
    additions.forEach((entry) => {
      appendProgressOutput(runtime, entry.text, entry.className);
    });
    latestProgressState = nextState;
    if (publish && paneSync) {
      paneSync.publish(latestProgressState);
    }
  }

  function clearBackgroundTask(runtime, taskId) {
    if (!backgroundTaskId || backgroundTaskId !== String(taskId || "")) {
      return;
    }
    clearProgressOutput(runtime);
    latestProgressState = { entries: [] };
    if (paneSync) paneSync.publish(latestProgressState);
  }

  function showProgressSnapshot(runtime, state, options = {}) {
    runtime.layout.showProgressPane(true, options);
    renderProgressStateIncrementally(runtime, state, true);
  }

  function connectProgressEvents(runtime, options = {}) {
    closeProgressEventStream();
    backgroundTaskId = "";
    backgroundActivityIds = new Set();
    runtime.layout.showProgressPane(true, options);
    eventSource = runtime.http.eventSource("/api/progress/events");
    eventSource.addEventListener("progress-event", (event) => {
      const payload = JSON.parse(event.data);
      renderProgressState(runtime, {
        entries: [{
          text: payload.text || "",
          className: ["warning", "error"].includes(payload.type)
            ? payload.type
            : "",
        }],
      }, true);
      if (payload.running === false) {
        closeProgressEventStream();
      }
    });
    eventSource.addEventListener("progress-issue", (event) => {
      const payload = JSON.parse(event.data);
      const severity = String(payload.severity || "issue").toUpperCase();
      renderProgressState(runtime, {
        entries: [
          ...latestProgressState.entries,
          {
            text: `\r\nISSUE FOUND - ${severity} - ${payload.summary || ""}\r\n`,
            className: String(payload.severity || "").toLowerCase() === "warning"
              ? "warning"
              : "error",
          },
        ],
      }, true);
    });
    eventSource.onerror = () => {};
  }

  function closeProgressEventStream() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  function fit() {
    if (!terminalFit) {
      return;
    }
    try {
      window.ElectroBoyTerminalBehavior.fit(terminal, terminalFit);
    } catch (error) {
      // The pane may be between layout states.
    }
  }

  function mount(runtime) {
    paneSync = runtime.sharedPanes.connect("progress", {
      snapshot: () => latestProgressState,
      receive: (state) => renderProgressStateIncrementally(runtime, state),
    });
    window.addEventListener("pagehide", () => paneSync.close(), { once: true });
    runtime.elements.exportProgressOutput.addEventListener("click", () => {
      exportProgressLog(runtime).catch((error) => {
        runtime.notifications.appendOutput(`export failed: ${error}\n`, "error");
      });
    });
  }

  window.ElectroBoyFrontend.registerModule({
    id: "progress",
    label: "Progress",
    capabilities: ["progress-stream", "issue-announcements"],
    actions: {
      initializeProgressTerminal,
      exportProgressLog,
      appendProgressOutput,
      clearProgressOutput,
      renderBackgroundTask,
      clearBackgroundTask,
      showProgressSnapshot,
      connectProgressEvents,
      closeProgressEventStream: () => closeProgressEventStream(),
      terminal: () => terminal,
      fit: () => fit(),
    },
    mount,
  });
})();
