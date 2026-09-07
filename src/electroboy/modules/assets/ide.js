(function () {
  "use strict";

  function element(tag, className = "", text = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function mount(options) {
    const host = options.host;
    const contextUrl = options.contextUrl;
    const viewId = String(
      options.paneInstanceId || window.crypto?.randomUUID?.() || Date.now(),
    );
    let workspaceId = "";
    let attached = false;
    let disposed = false;
    let heartbeat = null;
    let currentStatus = null;

    const root = element("div", "ide-pane");
    const frame = element("iframe", "ide-frame");
    frame.title = "ElectroBoy IDE";
    frame.hidden = true;
    frame.allow = "clipboard-read; clipboard-write; fullscreen";
    frame.setAttribute(
      "sandbox",
      [
        "allow-downloads",
        "allow-forms",
        "allow-modals",
        "allow-pointer-lock",
        "allow-popups",
        "allow-popups-to-escape-sandbox",
        "allow-same-origin",
        "allow-scripts",
      ].join(" "),
    );
    const state = element("div", "ide-state");
    const stateTitle = element("strong", "ide-state-title", "IDE");
    const stateDetail = element("span", "ide-state-detail", "Checking project state");
    const stateActions = element("div", "ide-state-actions");
    const retry = element("button", "ide-command", "Retry");
    retry.type = "button";
    const stop = element("button", "ide-command danger", "Stop");
    stop.type = "button";
    stop.hidden = true;
    stateActions.append(retry, stop);
    state.append(stateTitle, stateDetail, stateActions);
    root.append(frame, state);
    host.replaceChildren(root);

    const contextMenu = element("div", "ide-context-menu");
    contextMenu.hidden = true;
    contextMenu.setAttribute("role", "menu");
    document.body.append(contextMenu);

    function setState(kind, title, detail) {
      root.dataset.state = kind;
      state.hidden = false;
      stateTitle.textContent = title;
      stateDetail.textContent = detail || "";
      retry.hidden = !["failed", "stopped"].includes(kind);
      stop.hidden = !["starting", "ready"].includes(kind);
      if (kind !== "ready") frame.hidden = true;
    }

    async function request(path, init = {}) {
      const response = await fetch(contextUrl(path), {
        cache: "no-store",
        ...init,
        headers: {
          "Content-Type": "application/json",
          ...(init.headers || {}),
        },
      });
      const payload = await response.json().catch(() => ({ error: "request failed" }));
      if (!response.ok) {
        throw new Error(payload.error || `IDE request failed (${response.status})`);
      }
      return payload;
    }

    async function attachView() {
      const payload = await request("/api/ide/views/attach", {
        method: "POST",
        body: JSON.stringify({ view_id: viewId }),
      });
      attached = payload.status === "attached";
      if (attached && !heartbeat) {
        heartbeat = window.setInterval(() => {
          attachView().catch(() => {});
        }, 15000);
      }
    }

    async function start() {
      if (disposed) return;
      setState("starting", "Starting IDE", "Resolving the managed editor runtime");
      try {
        const project = await request("/api/project");
        workspaceId = String(project.workspace_id || project.context_id || "");
        const projectRoot = String(
          project.active_project_root || project.activation_root || "",
        );
        if (!workspaceId || !projectRoot || project.project_mode === "none") {
          currentStatus = { status: "inactive" };
          setState("stopped", "IDE unavailable", "Activate a project to open the IDE");
          retry.hidden = true;
          return;
        }
        const payload = await request("/api/ide/start", {
          method: "POST",
          body: "{}",
        });
        currentStatus = payload;
        await attachView();
        frame.src = contextUrl(String(payload.view_path || `/ide/${workspaceId}/`));
        frame.hidden = false;
        setState("ready", "IDE ready", "Loading the editor workbench");
        stop.hidden = false;
        options.setTitle?.("IDE");
      } catch (error) {
        currentStatus = { status: "failed", error: String(error.message || error) };
        setState("failed", "IDE failed to start", error.message || String(error));
      }
    }

    async function refresh() {
      if (disposed) return;
      try {
        const project = await request("/api/project");
        const active = String(
          project.active_project_root || project.activation_root || "",
        );
        if (!active || project.project_mode === "none") {
          frame.src = "about:blank";
          currentStatus = { status: "inactive" };
          setState("stopped", "IDE unavailable", "Activate a project to open the IDE");
          retry.hidden = true;
          return;
        }
        const payload = await request("/api/ide/status");
        currentStatus = payload;
        if (payload.status === "ready") {
          await attachView();
          if (!frame.src || frame.src === "about:blank") {
            workspaceId = String(project.workspace_id || project.context_id || "");
            frame.src = contextUrl(`/ide/${workspaceId}/`);
          }
          frame.hidden = false;
          setState("ready", "IDE ready", "Loading the editor workbench");
          return;
        }
        await start();
      } catch (error) {
        setState("failed", "IDE status unavailable", error.message || String(error));
      }
    }

    async function stopIDE() {
      setState("starting", "Stopping IDE", "Closing the workspace editor process");
      try {
        await request("/api/ide/stop", {
          method: "POST",
          body: JSON.stringify({ reason: "IDE pane stop action" }),
        });
        attached = false;
        frame.src = "about:blank";
        setState("stopped", "IDE stopped", "The workspace editor is not running");
      } catch (error) {
        setState("failed", "IDE could not stop", error.message || String(error));
      }
    }

    async function restartIDE() {
      await stopIDE();
      await start();
    }

    async function showDiagnostics() {
      const section = toolsSection;
      section.textContent = "Loading diagnostics";
      options.toolsController?.open("ide-diagnostics");
      try {
        const payload = await request("/api/ide/diagnostics");
        section.textContent = JSON.stringify(payload, null, 2);
      } catch (error) {
        section.textContent = error.message || String(error);
      }
    }

    async function showConfiguration() {
      const section = toolsSection;
      section.textContent = "Loading IDE configuration";
      options.toolsController?.open("ide-diagnostics");
      try {
        const payload = await request("/api/ide/diagnostics");
        section.textContent = JSON.stringify(
          {
            configuration: payload.configuration,
            limits: payload.limits,
            sandbox: payload.sandbox,
          },
          null,
          2,
        );
      } catch (error) {
        section.textContent = error.message || String(error);
      }
    }

    function menuButton(label, action, disabled = false) {
      const button = element("button", "ide-menu-item", label);
      button.type = "button";
      button.disabled = disabled;
      button.setAttribute("role", "menuitem");
      button.addEventListener("click", () => {
        contextMenu.hidden = true;
        Promise.resolve(action()).catch((error) => {
          setState("failed", "IDE action failed", error.message || String(error));
        });
      });
      return button;
    }

    function openContextMenu(event) {
      event.preventDefault();
      contextMenu.replaceChildren(
        menuButton("IDE configuration", showConfiguration),
        menuButton("Diagnostics", showDiagnostics),
        menuButton("Restart IDE", restartIDE, !workspaceId),
        menuButton("Stop IDE", stopIDE, currentStatus?.status === "stopped"),
        menuButton("Pop out", () => options.popOut?.(), !options.canPop),
      );
      contextMenu.style.left = `${Math.min(event.clientX, window.innerWidth - 180)}px`;
      contextMenu.style.top = `${Math.min(event.clientY, window.innerHeight - 210)}px`;
      contextMenu.hidden = false;
      contextMenu.querySelector("button:not(:disabled)")?.focus();
    }

    const toolsSection = options.toolsController
      ? options.toolsController.addSection("ide-diagnostics", "Diagnostics")
      : element("pre");
    toolsSection.classList.add("ide-diagnostics");
    toolsSection.textContent = "Open the IDE context menu to refresh diagnostics.";

    const toolbarRefresh = element("button", "ide-toolbar-command", "↻");
    toolbarRefresh.type = "button";
    toolbarRefresh.title = "Restart IDE";
    toolbarRefresh.setAttribute("aria-label", "Restart IDE");
    toolbarRefresh.addEventListener("click", () => restartIDE());
    options.toolbarHost?.append(toolbarRefresh);

    retry.addEventListener("click", start);
    stop.addEventListener("click", stopIDE);
    frame.addEventListener("load", () => {
      if (root.dataset.state === "ready" && frame.src !== "about:blank") {
        state.hidden = true;
      }
    });
    root.addEventListener("contextmenu", openContextMenu);
    document.addEventListener("pointerdown", (event) => {
      if (!contextMenu.contains(event.target)) contextMenu.hidden = true;
    });
    start();

    function dispose() {
      if (disposed) return;
      disposed = true;
      if (heartbeat) window.clearInterval(heartbeat);
      contextMenu.remove();
      toolbarRefresh.remove();
      frame.src = "about:blank";
      if (attached) {
        fetch(contextUrl("/api/ide/views/detach"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ view_id: viewId }),
          keepalive: true,
        }).catch(() => {});
      }
    }

    return { dispose, refresh, restart: restartIDE, stop: stopIDE };
  }

  window.ElectroBoyIDEPane = { mount };
  window.ElectroBoyFrontend.registerModule({
    id: "ide",
    label: "IDE",
    capabilities: ["ide", "editor", "navigation"],
    panes: [
      {
        id: "ide",
        label: "IDE",
        instance: true,
        restorable: true,
      },
    ],
    actions: {},
  });
})();
