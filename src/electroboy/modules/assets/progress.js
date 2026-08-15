(function () {
  "use strict";

    function initializeProgressTerminal() {
      if (progressTerminal || !window.Terminal) {
        return;
      }
      progressTerminal = new window.Terminal(terminalOptions(true, "progress"));
      if (window.FitAddon && window.FitAddon.FitAddon) {
        progressTerminalFit = new window.FitAddon.FitAddon();
        progressTerminal.loadAddon(progressTerminalFit);
      }
      progressTerminal.open(progressOutput);
      applyTerminalFontSize();
    }

    async function exportProgressLog() {
      await exportMarkdown(
        contextUrl("/api/progress/export"),
        `progress-log-${timestampForDownload()}.md`,
      );
    }

    function appendProgressOutput(text, className = "") {
      if (progressTerminal) {
        progressTerminal.write(formatTerminalMessage(text, className));
        return;
      }
      const span = document.createElement("span");
      span.textContent = text;
      if (className) {
        span.className = className;
      }
      progressOutput.appendChild(span);
      progressOutput.scrollTop = progressOutput.scrollHeight;
    }

    function clearProgressOutput() {
      if (progressTerminal) {
        progressTerminal.clear();
        return;
      }
      progressOutput.replaceChildren();
    }

    function connectProgressEvents() {
      if (progressEventSource) {
        progressEventSource.close();
      }
      showProgressPane(true);
      progressEventSource = new EventSource(contextUrl("/api/progress/events"));
      progressEventSource.addEventListener("progress-event", (event) => {
        const payload = JSON.parse(event.data);
        clearProgressOutput();
        appendProgressOutput(
          payload.text || "",
          payload.type === "error" ? "error" : "",
        );
        if (payload.running === false) {
          closeProgressEventStream();
        }
      });
      progressEventSource.onerror = () => {};
    }

    function closeProgressEventStream() {
      if (progressEventSource) {
        progressEventSource.close();
        progressEventSource = null;
      }
    }


  function mount(runtime) {
    runtime.elements.exportProgressOutput.addEventListener("click", () => {
      runtime.actions.exportProgressLog().catch((error) => {
        runtime.actions.appendOutput(`export failed: ${error}\n`, "error");
      });
    });
  }

  window.ElectroBoyFrontend.registerModule({
    id: "progress",
    label: "Progress",
    capabilities: ["progress-stream", "issue-announcements"],
    actions: {
      initializeProgressTerminal: (_runtime, ...args) => initializeProgressTerminal(...args),
      exportProgressLog: (_runtime, ...args) => exportProgressLog(...args),
      appendProgressOutput: (_runtime, ...args) => appendProgressOutput(...args),
      clearProgressOutput: (_runtime, ...args) => clearProgressOutput(...args),
      connectProgressEvents: (_runtime, ...args) => connectProgressEvents(...args),
      closeProgressEventStream: (_runtime, ...args) => closeProgressEventStream(...args),
    },
    mount,
  });
})();
