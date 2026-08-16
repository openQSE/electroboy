(function () {
  "use strict";

  let terminal = null;
  let terminalFit = null;
  let eventSource = null;

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

  function connectProgressEvents(runtime) {
    closeProgressEventStream();
    runtime.layout.showProgressPane(true);
    eventSource = runtime.http.eventSource("/api/progress/events");
    eventSource.addEventListener("progress-event", (event) => {
      const payload = JSON.parse(event.data);
      clearProgressOutput(runtime);
      appendProgressOutput(
        runtime,
        payload.text || "",
        payload.type === "error" ? "error" : "",
      );
      if (payload.running === false) {
        closeProgressEventStream();
      }
    });
    eventSource.addEventListener("progress-issue", (event) => {
      const payload = JSON.parse(event.data);
      const severity = String(payload.severity || "issue").toUpperCase();
      appendProgressOutput(
        runtime,
        `\r\nISSUE FOUND - ${severity} - ${payload.summary || ""}\r\n`,
        "error",
      );
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
      terminalFit.fit();
    } catch (error) {
      // The pane may be between layout states.
    }
  }

  function mount(runtime) {
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
