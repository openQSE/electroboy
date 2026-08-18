(function () {
  "use strict";

  let terminal = null;
  let terminalFit = null;
  let eventSource = null;
  let paneSync = null;
  let latestProgressState = { entries: [] };

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

  function clearProgressOutput(runtime) {
    if (terminal) {
      terminal.clear();
      return;
    }
    runtime.elements.progressOutput.replaceChildren();
  }

  function renderProgressState(runtime, state, publish = false) {
    if (!state || !Array.isArray(state.entries)) {
      return;
    }
    initializeProgressTerminal(runtime);
    latestProgressState = {
      entries: state.entries.map((entry) => ({
        text: String(entry.text || ""),
        className: entry.className || "",
      })),
    };
    clearProgressOutput(runtime);
    latestProgressState.entries.forEach((entry) => {
      appendProgressOutput(runtime, entry.text, entry.className);
    });
    if (publish && paneSync) {
      paneSync.publish(latestProgressState);
    }
  }

  function connectProgressEvents(runtime) {
    closeProgressEventStream();
    runtime.layout.showProgressPane(true);
    eventSource = runtime.http.eventSource("/api/progress/events");
    eventSource.addEventListener("progress-event", (event) => {
      const payload = JSON.parse(event.data);
      renderProgressState(runtime, {
        entries: [{
          text: payload.text || "",
          className: payload.type === "error" ? "error" : "",
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
            className: "error",
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
      receive: (state) => renderProgressState(runtime, state),
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
      connectProgressEvents,
      closeProgressEventStream: () => closeProgressEventStream(),
      terminal: () => terminal,
      fit: () => fit(),
    },
    mount,
  });
})();
