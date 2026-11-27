(function () {
  "use strict";

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
      let configWorkspace = "";
      let busy = false;
      let disposed = false;

      function workspace() {
        return String(runtime.getState().contextId || "");
      }

      async function request(options) {
        const url = runtime.http.contextUrl("/api/workspaces/agent-config");
        const response = await fetch(url, {cache: "no-store", ...options});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Agent selection failed.");
        return payload;
      }

      function render() {
        if (config && configWorkspace === workspace()) {
          select.replaceChildren(...config.backends.map((binary) => {
            const option = document.createElement("option");
            option.value = binary;
            option.textContent = binary;
            option.disabled = config.availability?.[binary] === false;
            if (option.disabled) option.title = "Executable unavailable in the service environment";
            return option;
          }));
          select.value = config.backend;
        }
        select.disabled = busy || !config || configWorkspace !== workspace();
      }

      async function refresh() {
        if (busy || disposed) return;
        const requestedWorkspace = workspace();
        if (!requestedWorkspace) {
          config = null;
          configWorkspace = "";
          render();
          return;
        }
        try {
          const current = await request();
          if (busy || disposed || requestedWorkspace !== workspace()) return;
          config = current;
          configWorkspace = requestedWorkspace;
          status.textContent = "";
          render();
        } catch (error) {
          if (requestedWorkspace !== workspace()) return;
          config = null;
          configWorkspace = "";
          status.textContent = error.message;
          render();
        }
      }

      select.addEventListener("change", async () => {
        const target = select.value;
        const requestedWorkspace = workspace();
        if (busy || !config || configWorkspace !== requestedWorkspace ||
            target === config.backend) return;
        busy = true;
        render();
        try {
          const updated = await request({
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({backend: target}),
          });
          if (requestedWorkspace === workspace()) {
            config = updated;
            configWorkspace = requestedWorkspace;
            status.textContent = `Default for new agents: ${updated.backend}`;
          }
        } catch (error) {
          status.textContent = error.message;
          runtime.notifications.appendOutput(`Agent selection failed: ${error.message}\n`, "error");
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
