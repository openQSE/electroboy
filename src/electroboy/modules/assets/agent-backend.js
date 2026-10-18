(function () {
  "use strict";

  function confirmSwitch(target, config) {
    const dialog = document.createElement("dialog");
    dialog.className = "agent-focus-session-dialog agent-terminate-dialog";
    dialog.setAttribute("aria-labelledby", "backendConfirmTitle");
    dialog.innerHTML = `
      <form method="dialog" class="agent-focus-session-form">
        <header class="agent-focus-session-header">
          <h2 id="backendConfirmTitle">Switch agent backend?</h2>
          <button type="button" class="agent-focus-session-close" aria-label="Close">&times;</button>
        </header>
        <section class="agent-terminate-session-body"><p></p></section>
        <footer class="agent-focus-session-footer">
          <button type="button" class="agent-focus-session-cancel">Cancel</button>
          <button type="submit" class="agent-focus-session-submit agent-terminate-session-submit">Stop agents and switch</button>
        </footer>
      </form>`;
    const count = config.active_agents.length + config.background_agents;
    dialog.querySelector("section p").textContent =
      `Switch to ${target === "codex" ? "Codex" : "OpenCode"}? This will stop all active agents and cancel queued agent work across every workspace in this ElectroBoy service, including other browser tabs. ` +
      `${count} agent${count === 1 ? " is" : "s are"} currently active. Future agents will use the selected backend. Files already written will remain.`;
    document.body.append(dialog);
    return new Promise((resolve) => {
      const finish = (confirmed) => {
        dialog.close();
        dialog.remove();
        resolve(confirmed);
      };
      dialog.querySelector("form").onsubmit = (event) => {
        event.preventDefault();
        finish(true);
      };
      dialog.querySelector(".agent-focus-session-cancel").onclick = () => finish(false);
      dialog.querySelector(".agent-focus-session-close").onclick = () => finish(false);
      dialog.addEventListener("cancel", (event) => {
        event.preventDefault();
        finish(false);
      });
      dialog.showModal();
      dialog.querySelector(".agent-focus-session-cancel").focus();
    });
  }

  window.ElectroBoyFrontend.registerModule({
    id: "agent-backend",
    label: "Agent Backend",
    capabilities: ["backend-selection"],
    mount(runtime) {
      const select = document.getElementById("agentBackend");
      const status = document.getElementById("agentBackendStatus");
      if (!select) return;
      select.closest(".backend-control").hidden = false;
      let config = null;
      let busy = false;
      let disposed = false;
      async function request(options) {
        const response = await fetch("/api/runtime/config", {cache: "no-store", ...options});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Backend request failed.");
        return payload;
      }
      function render() {
        select.value = config?.backend || "codex";
        select.disabled = busy || !config || config.switching;
      }
      async function refresh() {
        if (busy || disposed) return;
        try {
          const current = await request();
          if (busy || disposed) return;
          const changed = config && config.revision !== current.revision;
          config = current;
          render();
          if (changed) runtime.modules.invoke("agent-sessions", "refreshServiceSessions");
        } catch (error) {
          status.textContent = error.message;
          select.title = error.message;
        }
      }
      select.addEventListener("change", async () => {
        const target = select.value;
        if (busy || !config || target === config.backend) return;
        busy = true;
        render();
        try {
          config = await request();
          if (target === config.backend) return;
          if (!await confirmSwitch(target, config)) return;
          status.textContent = "Stopping agents…";
          config = await request({
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({backend: target, confirmed: true, revision: config.revision}),
          });
          status.textContent = `Backend: ${config.backend === "codex" ? "Codex" : "OpenCode"}`;
          await runtime.modules.invoke("agent-sessions", "refreshServiceSessions");
        } catch (error) {
          status.textContent = error.message;
          select.title = error.message;
          runtime.notifications.appendOutput(`Backend switch failed: ${error.message}\n`, "error");
        } finally {
          busy = false;
          render();
          await refresh();
        }
      });
      const timer = setInterval(refresh, 2000);
      window.addEventListener("pagehide", () => { disposed = true; clearInterval(timer); }, {once: true});
      refresh();
    },
  });
})();
