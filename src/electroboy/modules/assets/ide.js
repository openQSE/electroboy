(function () {
  "use strict";

  function element(tag, className = "", text = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  async function openLocation(contextUrl, location, options = {}) {
    const request = async (path, body) => {
      const response = await fetch(contextUrl(path), {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      });
      const payload = await response.json().catch(() => ({ error: "request failed" }));
      if (!response.ok) {
        throw new Error(payload.error || `IDE request failed (${response.status})`);
      }
      return payload;
    };
    options.openPane?.();
    await request("/api/ide/start", {});
    return request("/api/ide/open", location);
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
    let currentNeovim = null;
    let recoveryRequested = false;
    let zoomPercent = 100;
    let inputSequence = 0;
    let inputTelemetryCleanup = null;
    const telemetry = options.telemetry || null;

    try {
      const storedValue = window.localStorage.getItem("electroboy.ide.zoom");
      if (storedValue !== null) {
        const storedZoom = Number(storedValue);
        if (Number.isFinite(storedZoom)) {
          zoomPercent = Math.max(75, Math.min(200, storedZoom));
        }
      }
    } catch (_error) {
      // Zoom remains available when browser storage is unavailable.
    }

    function report(stage, details = {}) {
      if (!telemetry) return;
      const payload = {
        reason: "ide-startup",
        stage,
        page_id: String(telemetry.pageId || ""),
        tab_id: String(telemetry.tabId || ""),
        workspace_id: workspaceId,
        pane_id: viewId,
        occurred_at: new Date().toISOString(),
        ...details,
      };
      fetch("/api/frontend/debug", {
        method: "POST",
        cache: "no-store",
        keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => {});
    }

    function inputKeyGroup(key) {
      if (/^(Arrow|Page)/.test(key) || ["Home", "End"].includes(key)) {
        return "navigation";
      }
      if (["Backspace", "Delete", "Enter", "Escape", "Insert", "Tab"].includes(key)) {
        return "editing";
      }
      if (["Alt", "AltGraph", "Control", "Meta", "Shift"].includes(key)) {
        return "modifier";
      }
      if (/^F\d{1,2}$/.test(key)) return "function";
      if (key.length === 1) return "printable";
      return "other";
    }

    function recordInputEvent(eventType, event = null) {
      if (!telemetry || !workspaceId || disposed) return;
      const key = String(event?.key || "");
      const targetKind = String(event?.target?.tagName || "").toLowerCase();
      inputSequence += 1;
      const payload = {
        event_type: eventType,
        sequence: inputSequence,
        occurred_at: new Date().toISOString(),
        editor_mode: currentNeovim?.enabled ? "neovim" : "standard",
        key_group: key ? inputKeyGroup(key) : null,
        named_key: key.length > 1 ? key : null,
        physical_code: String(event?.code || "").slice(0, 32) || null,
        key_code: Number(event?.keyCode || 0),
        vim_motion: key.length === 1 && "hjkl".includes(key.toLowerCase()),
        repeat: Boolean(event?.repeat),
        default_prevented: Boolean(event?.defaultPrevented),
        frame_has_focus: Boolean(frame.contentDocument?.hasFocus()),
        target_kind: targetKind || null,
        modifiers: {
          alt: Boolean(event?.altKey),
          control: Boolean(event?.ctrlKey),
          meta: Boolean(event?.metaKey),
          shift: Boolean(event?.shiftKey),
        },
      };
      submitInputEvent(payload);
    }

    function recordKeybindingResolution(event) {
      if (!telemetry || !workspaceId || disposed) return;
      const detail = event?.detail || {};
      inputSequence += 1;
      submitInputEvent({
        event_type: "keybinding-resolution",
        sequence: inputSequence,
        occurred_at: new Date().toISOString(),
        key_label: String(detail.key_label || "").slice(0, 32) || null,
        dispatch_chord: String(detail.dispatch_chord || "").slice(0, 64) || null,
        resolution_kind: Number(detail.resolution_kind),
        resolved_command:
          String(detail.resolved_command || "").slice(0, 160) || null,
        context:
          detail.context && typeof detail.context === "object"
            ? detail.context
            : {},
      });
    }

    function submitInputEvent(payload) {
      fetch(contextUrl("/api/ide/input-events"), {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => {});
    }

    function installInputTelemetry() {
      inputTelemetryCleanup?.();
      inputTelemetryCleanup = null;
      if (!telemetry || frame.src === "about:blank") return;
      try {
        const targetWindow = frame.contentWindow;
        if (!targetWindow) return;
        const keyEvent = (event) => {
          window.setTimeout(() => recordInputEvent(event.type, event), 0);
        };
        const pointerEvent = (event) => recordInputEvent("pointerdown", event);
        const keybindingEvent = (event) => recordKeybindingResolution(event);
        const focused = () => recordInputEvent("frame-focus");
        const blurred = () => recordInputEvent("frame-blur");
        targetWindow.addEventListener("keydown", keyEvent, true);
        targetWindow.addEventListener("keyup", keyEvent, true);
        targetWindow.addEventListener("pointerdown", pointerEvent, true);
        targetWindow.addEventListener(
          "electroboy-keybinding-resolution",
          keybindingEvent,
        );
        targetWindow.addEventListener("focus", focused, true);
        targetWindow.addEventListener("blur", blurred, true);
        inputTelemetryCleanup = () => {
          targetWindow.removeEventListener("keydown", keyEvent, true);
          targetWindow.removeEventListener("keyup", keyEvent, true);
          targetWindow.removeEventListener("pointerdown", pointerEvent, true);
          targetWindow.removeEventListener(
            "electroboy-keybinding-resolution",
            keybindingEvent,
          );
          targetWindow.removeEventListener("focus", focused, true);
          targetWindow.removeEventListener("blur", blurred, true);
        };
      } catch (error) {
        report("input-telemetry-unavailable", {
          message: String(error.message || error),
        });
      }
    }

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
    frame.style.transformOrigin = "top left";
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

    function applyZoom(nextZoom) {
      zoomPercent = Math.max(75, Math.min(200, Number(nextZoom) || 100));
      const scale = zoomPercent / 100;
      frame.style.transform = `scale(${scale})`;
      frame.style.width = `${100 / scale}%`;
      frame.style.height = `${100 / scale}%`;
      if (zoomLevel) zoomLevel.textContent = `${zoomPercent}%`;
      try {
        window.localStorage.setItem("electroboy.ide.zoom", String(zoomPercent));
      } catch (_error) {
        // Zoom persistence is optional.
      }
    }

    function changeZoom(delta) {
      applyZoom(zoomPercent + delta);
    }

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
      const method = String(init.method || "GET").toUpperCase();
      report("request-start", { method, request_path: path });
      let response;
      try {
        response = await fetch(contextUrl(path), {
          cache: "no-store",
          ...init,
          headers: {
            "Content-Type": "application/json",
            ...(init.headers || {}),
          },
        });
      } catch (error) {
        report("request-network-error", {
          method,
          request_path: path,
          message: String(error.message || error),
        });
        throw error;
      }
      const payload = await response.json().catch(() => ({ error: "request failed" }));
      report("request-response", {
        method,
        request_path: path,
        status: response.status,
        ok: response.ok,
        response_status: String(payload.status || ""),
        error: response.ok ? "" : String(payload.error || ""),
      });
      if (!response.ok) {
        const error = new Error(
          payload.error || `IDE request failed (${response.status})`,
        );
        if (response.status === 409 && !recoveryRequested && !disposed) {
          recoveryRequested = true;
          error.workspaceRecoveryRequested = true;
          setState(
            "starting",
            "Reconnecting IDE",
            "Restoring the workspace connection",
          );
          options.postMessage?.({
            type: "electroboy:pane-recover-workspace",
            paneInstanceId: viewId,
          });
        }
        throw error;
      }
      recoveryRequested = false;
      return payload;
    }

    function toolButton(label, action, className = "") {
      const button = element("button", className, label);
      button.type = "button";
      button.addEventListener("click", () => {
        Promise.resolve(action()).catch((error) => {
          setState("failed", "IDE action failed", error.message || String(error));
        });
      });
      return button;
    }

    function toolSection(id, label, open = false) {
      return options.toolsController
        ? options.toolsController.addSection(id, label, { open })
        : element("div");
    }

    const viewSection = toolSection("ide-view", "View", true);
    const zoomRow = element("div", "ide-zoom-row");
    const zoomOut = toolButton("−", () => changeZoom(-10));
    zoomOut.title = "Zoom IDE out";
    zoomOut.setAttribute("aria-label", "Zoom IDE out");
    const zoomLevel = element("button", "ide-zoom-level", `${zoomPercent}%`);
    zoomLevel.type = "button";
    zoomLevel.title = "Reset IDE zoom";
    zoomLevel.addEventListener("click", () => applyZoom(100));
    const zoomIn = toolButton("+", () => changeZoom(10));
    zoomIn.title = "Zoom IDE in";
    zoomIn.setAttribute("aria-label", "Zoom IDE in");
    zoomRow.append(zoomOut, zoomLevel, zoomIn);
    viewSection.append(zoomRow);

    const modeSection = toolSection("ide-mode", "Mode", true);
    const configurationSection = toolSection(
      "ide-configuration",
      "Configuration",
      true,
    );
    const neovimSection = toolSection("ide-neovim", "VSCode Neovim");
    const networkSection = toolSection("ide-network", "Network access");
    const diagnosticsSection = toolSection("ide-diagnostics", "Diagnostics");
    const actionsSection = toolSection("ide-actions", "Actions", true);
    const popAction = toolButton("Pop out", () => options.popOut?.());
    popAction.hidden = !options.canPop;
    actionsSection.append(
      toolButton("Restart IDE", restartIDE),
      toolButton("Stop IDE", stopIDE, "danger"),
      popAction,
    );

    configurationSection.textContent = "Loading configuration";
    modeSection.textContent = "Loading editor mode";
    neovimSection.textContent = "Loading VSCode Neovim status";
    networkSection.append(toolButton("Open network settings", showNetworkSettings));
    diagnosticsSection.append(toolButton("Refresh diagnostics", showDiagnostics));
    applyZoom(zoomPercent);

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
      report("start-entered");
      setState("starting", "Starting IDE", "Resolving the managed editor runtime");
      try {
        const project = await request("/api/project");
        workspaceId = String(project.workspace_id || project.context_id || "");
        const projectRoot = String(
          project.active_project_root || project.activation_root || "",
        );
        if (!workspaceId || !projectRoot || project.project_mode === "none") {
          report("project-inactive", {
            project_mode: String(project.project_mode || ""),
            has_project_root: Boolean(projectRoot),
          });
          currentStatus = { status: "inactive" };
          setState("stopped", "IDE unavailable", "Activate a project to open the IDE");
          retry.hidden = true;
          return;
        }
        const payload = await request("/api/ide/start", {
          method: "POST",
          body: "{}",
        });
        report("provider-started", {
          response_status: String(payload.status || ""),
          instance_status: String(payload.instance?.status || ""),
          has_view_path: Boolean(payload.view_path),
        });
        currentStatus = payload;
        await attachView();
        report("view-attached");
        frame.src = contextUrl(String(payload.view_path || `/ide/${workspaceId}/`));
        report("frame-navigation-started", {
          frame_path: new URL(frame.src, window.location.origin).pathname,
        });
        frame.hidden = false;
        const neovim = payload.neovim || {};
        currentNeovim = neovim;
        renderModeControls(neovim);
        const detail = neovim.status === "enabled"
          ? "Loading the editor workbench with VSCode Neovim"
          : `Loading the editor workbench; Neovim ${neovim.status || "unavailable"}`;
        setState("ready", "IDE ready", detail);
        stop.hidden = false;
        options.setTitle?.("IDE");
      } catch (error) {
        if (error.workspaceRecoveryRequested) return;
        report("start-failed", {
          message: String(error.message || error),
          stack: String(error.stack || "").slice(0, 2000),
        });
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
            frame.src = contextUrl(String(
              payload.view_path ||
              `/ide/${workspaceId}/?folder=${encodeURIComponent(active)}`
            ));
          }
          frame.hidden = false;
          setState("ready", "IDE ready", "Loading the editor workbench");
          return;
        }
        await start();
      } catch (error) {
        if (error.workspaceRecoveryRequested) return;
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

    async function showDiagnostics(openTools = true) {
      const section = diagnosticsSection;
      section.textContent = "Loading diagnostics";
      if (openTools) options.toolsController?.open("ide-diagnostics");
      try {
        const payload = await request("/api/ide/diagnostics");
        section.textContent = JSON.stringify(payload, null, 2);
      } catch (error) {
        section.textContent = error.message || String(error);
      }
    }

    function settingField(label, control) {
      const field = element("label", "ide-setting-field");
      field.append(element("span", "", label), control);
      return field;
    }

    function numberInput(value, minimum, maximum) {
      const input = element("input");
      input.type = "number";
      input.value = String(value);
      input.min = String(minimum);
      input.max = String(maximum);
      input.step = "1";
      return input;
    }

    async function showConfiguration(openTools = true) {
      const section = configurationSection;
      section.textContent = "Loading IDE configuration";
      if (openTools) options.toolsController?.open("ide-configuration");
      try {
        const payload = await request("/api/ide/configuration");
        const configuration = payload.configuration || {};
        const runtime = payload.runtime?.runtime || {};
        const provider = element(
          "div",
          "ide-setting-summary",
          `OpenVSCode ${runtime.version || "runtime not resolved"}`,
        );
        const runtimeMode = element("select");
        ["auto", "managed", "system", "disabled"].forEach((value) => {
          const option = element("option", "", value);
          option.value = value;
          option.selected = configuration.runtime_mode === value;
          runtimeMode.append(option);
        });
        const executable = element("input");
        executable.type = "text";
        executable.value = String(configuration.system_executable || "");
        executable.placeholder = "Auto-detect OpenVSCode executable";
        const maximumInstances = numberInput(
          configuration.maximum_instances,
          1,
          8,
        );
        const maximumViews = numberInput(
          configuration.maximum_views_per_instance,
          1,
          8,
        );
        const idleTimeout = numberInput(configuration.idle_timeout, 0, 86400);
        const startupTimeout = numberInput(configuration.startup_timeout, 1, 300);
        const updateExecutableState = () => {
          executable.disabled = runtimeMode.value !== "system";
        };
        runtimeMode.addEventListener("change", updateExecutableState);
        updateExecutableState();

        const result = element("div", "ide-setting-result");
        const restart = toolButton("Restart now", restartIDE);
        restart.hidden = !payload.restart_required;
        const apply = toolButton("Apply configuration", async () => {
          apply.disabled = true;
          result.textContent = "Saving configuration";
          try {
            const updated = await request("/api/ide/configure", {
              method: "POST",
              body: JSON.stringify({
                runtime_mode: runtimeMode.value,
                system_executable: executable.value.trim(),
                maximum_instances: Number(maximumInstances.value),
                maximum_views_per_instance: Number(maximumViews.value),
                idle_timeout: Number(idleTimeout.value),
                startup_timeout: Number(startupTimeout.value),
              }),
            });
            result.textContent = updated.restart_required
              ? "Saved. Restart the IDE to apply provider changes."
              : "Saved.";
            restart.hidden = !updated.restart_required;
          } catch (error) {
            result.textContent = error.message || String(error);
          } finally {
            apply.disabled = false;
          }
        }, "primary");
        section.replaceChildren(
          provider,
          settingField("Runtime mode", runtimeMode),
          settingField("System executable", executable),
          settingField("Maximum IDE instances", maximumInstances),
          settingField("Maximum views per IDE", maximumViews),
          settingField("Idle timeout (seconds)", idleTimeout),
          settingField("Startup timeout (seconds)", startupTimeout),
          apply,
          restart,
          result,
        );
      } catch (error) {
        section.textContent = error.message || String(error);
      }
    }

    async function showNeovimSettings(openTools = true) {
      const section = neovimSection;
      section.replaceChildren();
      if (openTools) options.toolsController?.open("ide-neovim");
      try {
        const payload = await request("/api/ide/neovim");
        currentNeovim = payload;
        renderModeControls(payload);
        const status = element(
          "div",
          `ide-neovim-status ${payload.status || "unavailable"}`,
          `Status: ${payload.status || "unavailable"}`,
        );
        const enabledLabel = element("label", "ide-setting-row");
        const enabled = element("input");
        enabled.type = "checkbox";
        enabled.checked = Boolean(payload.enabled);
        enabledLabel.append(enabled, document.createTextNode(" Enable VSCode Neovim"));
        const pathLabel = element("label", "ide-setting-field");
        pathLabel.append(element("span", "", "Neovim executable"));
        const executable = element("input");
        executable.type = "text";
        executable.value = String(payload.configured_executable || "");
        executable.placeholder = String(payload.executable || "Auto-detect nvim");
        pathLabel.append(executable);
        const result = element(
          "div",
          "ide-setting-result",
          String(payload.reason || `Extension ${payload.extension?.version || ""}`),
        );
        const restart = toolButton("Restart now", restartIDE);
        restart.hidden = !payload.restart_required;
        const apply = toolButton("Apply VSCode Neovim", async () => {
          apply.disabled = true;
          try {
            const updated = await request("/api/ide/neovim/configure", {
              method: "POST",
              body: JSON.stringify({
                enabled: enabled.checked,
                executable: executable.value.trim(),
              }),
            });
            currentNeovim = updated;
            result.textContent = updated.restart_required
              ? "Saved. Restart the IDE to apply this setting."
              : "Saved.";
            restart.hidden = !updated.restart_required;
          } catch (error) {
            result.textContent = error.message || String(error);
          } finally {
            apply.disabled = false;
          }
        }, "primary");
        section.append(status, enabledLabel, pathLabel, apply, restart, result);
      } catch (error) {
        section.textContent = error.message || String(error);
      }
    }

    function renderModeControls(neovim = currentNeovim || {}) {
      const selectedMode = neovim.enabled ? "neovim" : "standard";
      const choices = element("div", "ide-mode-choices");
      choices.setAttribute("role", "radiogroup");
      choices.setAttribute("aria-label", "Editor mode");
      [
        ["standard", "Standard"],
        ["neovim", "Neovim"],
      ].forEach(([mode, label]) => {
        const button = toolButton(label, () => setEditorMode(mode));
        const selected = mode === selectedMode;
        button.classList.add("ide-mode-choice");
        button.setAttribute("role", "radio");
        button.setAttribute("aria-checked", String(selected));
        button.disabled = !workspaceId || selected;
        choices.append(button);
      });
      modeSection.replaceChildren(choices);
    }

    async function setEditorMode(mode) {
      if (!workspaceId) return;
      if (!["standard", "neovim"].includes(mode)) return;
      options.toolsController?.open("ide-mode");
      const current = await request("/api/ide/neovim");
      const enableNeovim = mode === "neovim";
      if (Boolean(current.enabled) === enableNeovim) {
        renderModeControls(current);
        return;
      }
      modeSection.textContent = enableNeovim
        ? "Switching to Neovim"
        : "Switching to the standard editor";
      setState(
        "starting",
        "Switching editor mode",
        enableNeovim
          ? "Preparing the managed Neovim runtime and extension"
          : "Disabling the Neovim extension",
      );
      try {
        const payload = enableNeovim
          ? await request("/api/ide/neovim/launch", {
            method: "POST",
            body: JSON.stringify({}),
          })
          : await request("/api/ide/neovim/configure", {
            method: "POST",
            body: JSON.stringify({
              enabled: false,
              executable: current.configured_executable || "",
            }),
          });
        if (enableNeovim && payload.status !== "enabled") {
          throw new Error(payload.reason || "VSCode Neovim is unavailable");
        }
        currentNeovim = payload;
        renderModeControls(payload);
        await restartIDE();
        await showNeovimSettings(false);
      } catch (error) {
        renderModeControls(current);
        await showNeovimSettings(false);
        setState(
          "failed",
          "Editor mode could not change",
          error.message || String(error),
        );
      }
    }

    function formatEgressRules(rules) {
      return (rules || []).map((rule) => [
        String(rule.destination || ""),
        (rule.ports || []).join(","),
        (rule.protocols || ["tcp"]).join(","),
      ].join(" ")).join("\n");
    }

    function parseEgressRules(value) {
      return String(value || "").split("\n").map((line) => line.trim())
        .filter(Boolean).map((line) => {
          const [destination, portsText = "", protocolsText = "tcp"] =
            line.split(/\s+/);
          const ports = portsText.split(",").filter(Boolean).map(Number);
          const protocols = protocolsText.split(",").filter(Boolean);
          if (!destination || ports.some((port) => !Number.isInteger(port))) {
            throw new Error(`Invalid network rule: ${line}`);
          }
          return { destination, ports, protocols };
        });
    }

    async function showNetworkSettings(openTools = true) {
      const section = networkSection;
      section.replaceChildren();
      if (openTools) options.toolsController?.open("ide-network");
      try {
        const payload = await request("/api/ide/network");
        const modeLabel = element("label", "ide-setting-field");
        modeLabel.append(element("span", "", "Network mode"));
        const mode = element("select");
        ["deny", "allowlist", "audit"].forEach((value) => {
          const option = element("option", "", value);
          option.value = value;
          option.selected = payload.mode === value;
          mode.append(option);
        });
        modeLabel.append(mode);

        const rulesLabel = element("label", "ide-setting-field");
        rulesLabel.append(element("span", "", "Workspace rules"));
        const rules = element("textarea");
        rules.rows = 4;
        rules.placeholder = "example.com 443 tcp";
        rules.value = formatEgressRules(payload.rules);
        rulesLabel.append(rules);

        const temporaryLabel = element("label", "ide-setting-field");
        temporaryLabel.append(element("span", "", "Temporary exceptions"));
        const temporary = element("textarea");
        temporary.rows = 3;
        temporary.placeholder = "192.0.2.10 443 tcp";
        temporary.value = formatEgressRules(payload.temporary_rules);
        temporaryLabel.append(temporary);

        const enforcement = element(
          "div",
          `ide-network-status ${payload.enforcement?.enforced ? "enabled" : ""}`,
          payload.enforcement?.enforced
            ? `Enforced: ${payload.enforcement.implementation}`
            : `Unavailable: ${(payload.enforcement?.missing_tools || []).join(", ")}`,
        );
        const apply = element("button", "ide-command", "Apply");
        apply.type = "button";
        const clear = element("button", "ide-command", "Clear events");
        clear.type = "button";
        const actions = element("div", "ide-setting-actions");
        actions.append(apply, clear);
        const result = element("div", "ide-setting-result");
        const events = element("pre", "ide-network-events");
        events.textContent = JSON.stringify(
          {
            connections: payload.events || [],
            browser: payload.csp_violations || [],
          },
          null,
          2,
        );

        apply.addEventListener("click", async () => {
          const audit = mode.value === "audit";
          const acknowledged = !audit || window.confirm(
            "Audit mode permits the IDE and its tools to transmit source code and credentials.",
          );
          if (!acknowledged) return;
          apply.disabled = true;
          try {
            const updated = await request("/api/ide/network/configure", {
              method: "POST",
              body: JSON.stringify({
                mode: mode.value,
                rules: parseEgressRules(rules.value),
                temporary_rules: parseEgressRules(temporary.value),
                audit_acknowledged: acknowledged,
              }),
            });
            result.textContent = updated.restart_required
              ? "Saved. Restart the IDE to apply this network policy."
              : "Saved.";
          } catch (error) {
            result.textContent = error.message || String(error);
          } finally {
            apply.disabled = false;
          }
        });
        clear.addEventListener("click", async () => {
          clear.disabled = true;
          try {
            const updated = await request("/api/ide/network/events/clear", {
              method: "POST",
              body: "{}",
            });
            events.textContent = JSON.stringify(
              {
                connections: updated.events || [],
                browser: updated.csp_violations || [],
              },
              null,
              2,
            );
            result.textContent = "Network events cleared.";
          } catch (error) {
            result.textContent = error.message || String(error);
          } finally {
            clear.disabled = false;
          }
        });
        section.append(
          modeLabel,
          rulesLabel,
          temporaryLabel,
          enforcement,
          actions,
          result,
          events,
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
      showContextMenu(event.clientX, event.clientY);
    }

    function showContextMenu(clientX, clientY) {
      contextMenu.replaceChildren(
        menuButton("IDE configuration", showConfiguration),
        menuButton(
          currentNeovim?.enabled
            ? "Use standard editor"
            : "Launch with VSCode Neovim",
          () => setEditorMode(currentNeovim?.enabled ? "standard" : "neovim"),
          !workspaceId,
        ),
        menuButton("VSCode Neovim", showNeovimSettings),
        menuButton("Network access", showNetworkSettings),
        menuButton("Diagnostics", showDiagnostics),
        menuButton("Zoom out", () => changeZoom(-10)),
        menuButton(`Reset zoom (${zoomPercent}%)`, () => applyZoom(100)),
        menuButton("Zoom in", () => changeZoom(10)),
        menuButton("Restart IDE", restartIDE, !workspaceId),
        menuButton("Stop IDE", stopIDE, currentStatus?.status === "stopped"),
        menuButton("Pop out", () => options.popOut?.(), !options.canPop),
      );
      contextMenu.style.left = `${Math.max(4, Math.min(clientX, window.innerWidth - 180))}px`;
      contextMenu.hidden = false;
      contextMenu.style.top = `${Math.max(4, Math.min(
        clientY,
        window.innerHeight - contextMenu.offsetHeight - 4,
      ))}px`;
      contextMenu.querySelector("button:not(:disabled)")?.focus();
    }

    diagnosticsSection.classList.add("ide-diagnostics");

    const toolbarRefresh = element("button", "ide-toolbar-command", "↻");
    toolbarRefresh.type = "button";
    toolbarRefresh.title = "Restart IDE";
    toolbarRefresh.setAttribute("aria-label", "Restart IDE");
    toolbarRefresh.addEventListener("click", () => restartIDE());
    options.toolbarHost?.append(toolbarRefresh);

    retry.addEventListener("click", start);
    stop.addEventListener("click", stopIDE);
    frame.addEventListener("load", () => {
      report("frame-loaded", {
        frame_path: new URL(frame.src, window.location.origin).pathname,
      });
      if (root.dataset.state === "ready" && frame.src !== "about:blank") {
        state.hidden = true;
      }
      installInputTelemetry();
    });
    frame.addEventListener("error", () => {
      report("frame-load-error", {
        frame_path: new URL(frame.src, window.location.origin).pathname,
      });
    });
    root.addEventListener("contextmenu", openContextMenu);
    document.addEventListener("pointerdown", (event) => {
      if (!contextMenu.contains(event.target)) contextMenu.hidden = true;
    });
    showConfiguration(false);
    renderModeControls();
    showNeovimSettings(false);
    start();

    function dispose() {
      if (disposed) return;
      disposed = true;
      if (heartbeat) window.clearInterval(heartbeat);
      inputTelemetryCleanup?.();
      inputTelemetryCleanup = null;
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

  window.ElectroBoyIDE = { openLocation };
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
