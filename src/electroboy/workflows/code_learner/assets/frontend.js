(function () {
  "use strict";

  const WORKFLOW_ID = "code-learner";
  const CONTEXT_HEADER = "[ElectroBoy Code Learner context]";
  const CONTEXT_FOOTER = "[/ElectroBoy Code Learner context]";
  const MODE_LABELS = {
    architecture: "Architecture",
    module: "Module",
    function: "Function",
  };
  const KEYWORDS = {
    python: [
      "and", "as", "assert", "async", "await", "break", "class", "continue",
      "def", "del", "elif", "else", "except", "False", "finally", "for",
      "from", "if", "import", "in", "is", "lambda", "None", "not", "or",
      "pass", "raise", "return", "True", "try", "while", "with", "yield",
    ],
    javascript: [
      "async", "await", "break", "case", "catch", "class", "const", "continue",
      "default", "else", "export", "false", "finally", "for", "from", "function",
      "if", "import", "let", "new", "null", "return", "switch", "this", "throw",
      "true", "try", "var", "while",
    ],
    typescript: [
      "async", "await", "break", "case", "catch", "class", "const", "continue",
      "default", "else", "export", "false", "finally", "for", "from", "function",
      "if", "import", "interface", "let", "new", "null", "return", "switch",
      "this", "throw", "true", "try", "type", "var", "while",
    ],
    json: ["false", "null", "true"],
    toml: ["false", "true"],
    shell: [
      "case", "do", "done", "elif", "else", "esac", "fi", "for", "function",
      "if", "in", "then", "while",
    ],
  };

  let runtimeApi = null;
  let contextId = "";
  let activeProjectRoot = "";
  let activationRoot = "";
  let learnerState = emptyLearnerState();
  let learnerContext = null;
  let nav = {};
  let courseMode = "architecture";
  let initializationState = null;
  let initializationPollTimer = null;
  const INITIALIZATION_POLL_INTERVAL_MS = 1500;
  const navigationExpanded = {
    project: true,
    learn: true,
    recent: false,
    module: false,
    function: false,
    outline: true,
  };
  let activeNavigationGroup = "project";
  let selectedModuleTarget = "";

  function emptyLearnerState() {
    return {
      analysis: null,
      walkthroughs: [],
      currentWalkthrough: null,
      source: null,
    };
  }

  function bindRuntime(runtime) {
    runtimeApi = runtime;
    const state = runtime.getState();
    contextId = state.contextId || "";
    activeProjectRoot = state.activeProjectRoot || "";
    activationRoot = state.activationRoot || activeProjectRoot;
  }

  function invoke(runtime, handler, args) {
    bindRuntime(runtime);
    return handler(...args);
  }

  function contextUrl(path) {
    return runtimeApi.http.contextUrl(path);
  }

  function basename(path) {
    return runtimeApi.paths.basename(path);
  }

  function appendOutput(text, kind = "system") {
    runtimeApi.notifications.appendOutput(text, kind);
  }

  function projectEndpoint(_runtime, mode) {
    return mode === "open" ? "/api/code-learner/project/open" : "";
  }

  function modeLabel(mode) {
    return MODE_LABELS[mode] || MODE_LABELS.architecture;
  }

  function projectChanged(payload) {
    if (payload && payload.code_learner) {
      applyLearnerPayload(payload.code_learner);
    }
    renderNavigationState();
    if (payload && (payload.active_project_root || payload.activation_root)) {
      openLearnerPane({ activate: false, refresh: true });
    }
    return true;
  }

  function activate(runtime) {
    bindRuntime(runtime);
    runtime.ui.setWorkflowSideSheetCollapsed(false);
    runtime.ui.setAgentInputVisible(true);
    runtime.layout.assignPane(
      "code-learner",
      learnerPaneItem(true),
      "",
      { targetPane: "agent", direction: "row", ratio: 0.66, activate: true },
    );
    if (!(activeProjectRoot || activationRoot)) {
      learnerState = emptyLearnerState();
      renderNavigationState();
    }
  }

  function deactivate(runtime) {
    bindRuntime(runtime);
    learnerState = emptyLearnerState();
    learnerContext = null;
    nav = {};
  }

  function renderNavigation(container, runtime) {
    bindRuntime(runtime);
    container.innerHTML = `
      <section class="code-learner-nav" aria-label="Code Learner">
        <div class="code-learner-section">
          <button class="stage-action-stage" type="button" aria-expanded="false"
                  data-code-learner-control="project-menu">
            <span class="stage-action-label">Project</span>
            <span class="stage-action-chevron" aria-hidden="true"></span>
          </button>
          <div class="stage-action-list" role="group" hidden
               data-code-learner-control="project-actions">
            <button class="stage-action-button" type="button"
                    data-code-learner-control="workspace">Workspace</button>
            <div class="stage-action-subgroup">
              <button class="stage-action-subgroup-trigger" type="button"
                      aria-expanded="false"
                      title="Open a recently used project."
                      data-code-learner-control="recent-projects-menu">
                <span class="stage-action-label">Recent projects</span>
                <span class="stage-action-chevron" aria-hidden="true"></span>
              </button>
              <div class="stage-action-subgroup-list" role="group" hidden
                   data-code-learner-control="recent"></div>
            </div>
            <button class="stage-action-button" type="button" disabled
                    data-code-learner-control="close">Deactivate</button>
          </div>
        </div>
        <form class="code-learner-section code-learner-course-form"
              data-code-learner-control="course-form">
          <button class="stage-action-stage" type="button" aria-expanded="false"
                  data-code-learner-control="learn-menu">
            <span class="stage-action-label">Learn</span>
            <span class="stage-action-chevron" aria-hidden="true"></span>
          </button>
          <div class="stage-action-list" role="group" hidden
               data-code-learner-control="learn-actions">
            <button class="stage-action-button primary" type="button"
                    data-code-learner-control="initialize">Initialize</button>
            <button class="stage-action-button code-learner-mode-action"
                    type="button" disabled
                    data-code-learner-control="architecture">Architecture</button>
            <div class="stage-action-subgroup">
              <button class="stage-action-subgroup-trigger" type="button"
                      aria-expanded="false" disabled
                      data-code-learner-control="module-menu">
                <span class="stage-action-label">Module</span>
                <span class="stage-action-chevron" aria-hidden="true"></span>
              </button>
              <div class="stage-action-subgroup-list" role="group" hidden
                   data-code-learner-control="module-actions">
                <label class="code-learner-field"
                       data-code-learner-control="module-field">
                  <span>Module</span>
                  <select disabled
                          data-code-learner-control="module"></select>
                </label>
                <button class="stage-action-button" type="button" disabled
                        data-code-learner-control="module-start">Start</button>
              </div>
            </div>
            <div class="stage-action-subgroup">
              <button class="stage-action-subgroup-trigger" type="button"
                      aria-expanded="false" disabled
                      data-code-learner-control="function-menu">
                <span class="stage-action-label">Function</span>
                <span class="stage-action-chevron" aria-hidden="true"></span>
              </button>
              <div class="stage-action-subgroup-list" role="group" hidden
                   data-code-learner-control="function-actions">
                <label class="code-learner-field"
                       data-code-learner-control="function-field">
                  <span>Symbol</span>
                  <input type="text" list="code-learner-symbols"
                         autocomplete="off" spellcheck="false" disabled
                         data-code-learner-control="function">
                  <datalist id="code-learner-symbols"
                            data-code-learner-control="symbols"></datalist>
                </label>
                <button class="stage-action-button" type="submit" disabled
                        data-code-learner-control="function-start">Start</button>
              </div>
            </div>
            <label class="code-learner-field">
              <span>Level</span>
              <input type="text" autocomplete="off" disabled
                     data-code-learner-control="audience"
                     placeholder="Optional">
            </label>
            <button class="stage-action-button" type="button" disabled
                    data-code-learner-control="start-agent">Start tutor</button>
            <div class="code-learner-status"
                 data-code-learner-control="status"></div>
            <div class="code-learner-progress" hidden
                 data-code-learner-control="init-progress">
              <div class="code-learner-progress-track">
                <div class="code-learner-progress-fill"
                     data-code-learner-control="init-progress-fill"></div>
              </div>
              <div class="code-learner-progress-meta"
                   data-code-learner-control="init-progress-meta"></div>
            </div>
          </div>
        </form>
        <div class="code-learner-section">
          <button class="stage-action-stage" type="button" aria-expanded="false"
                  data-code-learner-control="outline-menu">
            <span class="stage-action-label">Outline</span>
            <span class="stage-action-chevron" aria-hidden="true"></span>
          </button>
          <div class="stage-action-list" role="group" hidden
               data-code-learner-control="outline-actions">
            <div class="code-learner-outline"
                 data-code-learner-control="outline"></div>
          </div>
        </div>
      </section>
    `;
    nav = {
      projectMenu: control(container, "project-menu"),
      projectActions: control(container, "project-actions"),
      workspace: control(container, "workspace"),
      recentMenu: control(container, "recent-projects-menu"),
      close: control(container, "close"),
      recent: control(container, "recent"),
      form: control(container, "course-form"),
      learnMenu: control(container, "learn-menu"),
      learnActions: control(container, "learn-actions"),
      initialize: control(container, "initialize"),
      architecture: control(container, "architecture"),
      moduleMenu: control(container, "module-menu"),
      moduleActions: control(container, "module-actions"),
      moduleField: control(container, "module-field"),
      module: control(container, "module"),
      moduleStart: control(container, "module-start"),
      functionMenu: control(container, "function-menu"),
      functionActions: control(container, "function-actions"),
      functionField: control(container, "function-field"),
      function: control(container, "function"),
      functionStart: control(container, "function-start"),
      symbols: control(container, "symbols"),
      audience: control(container, "audience"),
      startAgent: control(container, "start-agent"),
      status: control(container, "status"),
      initProgress: control(container, "init-progress"),
      initProgressFill: control(container, "init-progress-fill"),
      initProgressMeta: control(container, "init-progress-meta"),
      outlineMenu: control(container, "outline-menu"),
      outlineActions: control(container, "outline-actions"),
      outline: control(container, "outline"),
    };
    nav.projectMenu.addEventListener(
      "click",
      () => toggleNavigationGroup("project", true),
    );
    nav.learnMenu.addEventListener(
      "click",
      () => toggleNavigationGroup("learn", true),
    );
    nav.outlineMenu.addEventListener(
      "click",
      () => toggleNavigationGroup("outline", true),
    );
    nav.recentMenu.addEventListener(
      "click",
      () => toggleNavigationGroup("recent"),
    );
    nav.moduleMenu.addEventListener("click", () => toggleNavigationGroup("module"));
    nav.functionMenu.addEventListener(
      "click",
      () => toggleNavigationGroup("function"),
    );
    nav.workspace.addEventListener("click", () => runtime.workspaces.openSelector());
    nav.close.addEventListener("click", () => runtime.project.deactivate());
    nav.initialize.addEventListener("click", () => {
      initializeCodeLearner().catch((error) => {
        setStatus(error.message || String(error), "error");
      });
    });
    nav.architecture.addEventListener("click", () => {
      generateCourse({ mode: "architecture" }).catch((error) => {
        setStatus(error.message || String(error), "error");
      });
    });
    nav.moduleStart.addEventListener("click", () => {
      generateCourse({ mode: "module" }).catch((error) => {
        setStatus(error.message || String(error), "error");
      });
    });
    nav.form.addEventListener("submit", (event) => {
      event.preventDefault();
      generateCourse({ mode: "function" }).catch((error) => {
        setStatus(error.message || String(error), "error");
      });
    });
    nav.startAgent.addEventListener("click", () => {
      startTutor(runtimeApi).catch((error) => {
        setStatus(error.message || String(error), "error");
      });
    });
    const debouncedSymbolLoad = debounce(loadMatchingSymbols, 160);
    nav.function.addEventListener("input", () => {
      renderNavigationState();
      debouncedSymbolLoad();
    });
    nav.module.addEventListener("change", () => {
      selectedModuleTarget = nav.module.value.trim();
      renderNavigationState();
    });
    renderNavigationState();
  }

  function refreshNavigation(runtime) {
    bindRuntime(runtime);
    renderNavigationState();
  }

  function control(container, name) {
    return container.querySelector(`[data-code-learner-control="${name}"]`);
  }

  function toggleNavigationGroup(group, activate = false) {
    if (activate) {
      activeNavigationGroup = group;
    }
    navigationExpanded[group] = !navigationExpanded[group];
    renderNavigationState();
  }

  function applyNavigationGroup(button, list, expanded) {
    if (!button || !list) {
      return;
    }
    button.classList.toggle("expanded", expanded);
    button.setAttribute("aria-expanded", expanded ? "true" : "false");
    list.hidden = !expanded;
  }

  function renderNavigationState() {
    if (!nav.form) {
      return;
    }
    const hasProject = Boolean(activeProjectRoot || activationRoot);
    const walkthrough = learnerState.currentWalkthrough;
    const initialized = learnerInitialized();
    const initializing = initializationRunning();
    const modules = learnerModules();
    const symbols = learnerSymbols();
    applyNavigationGroup(nav.projectMenu, nav.projectActions, navigationExpanded.project);
    applyNavigationGroup(nav.learnMenu, nav.learnActions, navigationExpanded.learn);
    applyNavigationGroup(
      nav.recentMenu,
      nav.recent,
      navigationExpanded.recent,
    );
    applyNavigationGroup(
      nav.moduleMenu,
      nav.moduleActions,
      initialized && navigationExpanded.module,
    );
    applyNavigationGroup(
      nav.functionMenu,
      nav.functionActions,
      initialized && navigationExpanded.function,
    );
    applyNavigationGroup(
      nav.outlineMenu,
      nav.outlineActions,
      Boolean(walkthrough) && navigationExpanded.outline,
    );
    nav.projectMenu.classList.toggle("active", activeNavigationGroup === "project");
    nav.learnMenu.classList.toggle("active", activeNavigationGroup === "learn");
    nav.outlineMenu.classList.toggle(
      "active",
      activeNavigationGroup === "outline" && Boolean(walkthrough),
    );
    nav.close.disabled = !Boolean(activationRoot);
    nav.initialize.disabled = !hasProject || initializing;
    nav.architecture.disabled = initializing || !initialized;
    nav.moduleMenu.disabled = initializing || !initialized;
    nav.module.disabled = initializing || !initialized || modules.length === 0;
    nav.moduleStart.disabled =
      initializing || !initialized || modules.length === 0 || !nav.module.value.trim();
    nav.functionMenu.disabled = initializing || !initialized;
    nav.function.disabled = initializing || !initialized;
    nav.functionStart.disabled =
      initializing || !initialized || !nav.function.value.trim();
    nav.audience.disabled = initializing || !initialized;
    nav.startAgent.disabled = initializing || !hasProject || !walkthrough;
    nav.outlineMenu.disabled = !Boolean(walkthrough);
    renderInitializationProgress();
    renderModuleOptions(modules, initialized);
    renderSymbolOptions(symbols);
    renderRecentProjects();
    renderOutline();
    if (!hasProject) {
      setStatus("No project active.");
    } else if (initializing) {
      setStatus(formatInitializationStatus(initializationState));
    } else if (!initialized) {
      setStatus("Initialize learning context.");
    } else if (!walkthrough) {
      setStatus(`Project: ${basename(activeProjectRoot || activationRoot)}`);
    }
  }

  function learnerInitialized() {
    return Boolean(
      learnerState.analysis ||
      learnerState.currentWalkthrough ||
      learnerState.walkthroughs.length,
    );
  }

  function initializationRunning() {
    const status = initializationState && initializationState.status;
    return status === "queued" || status === "running";
  }

  function initializationFailed() {
    return initializationState && initializationState.status === "failed";
  }

  function applyInitializationPayload(payload) {
    if (!payload || typeof payload !== "object") {
      return;
    }
    if (payload.initialization && typeof payload.initialization === "object") {
      initializationState = payload.initialization;
    }
    if (payload.code_learner) {
      applyLearnerPayload(payload.code_learner);
    }
  }

  function formatInitializationStatus(initialization) {
    if (!initialization) {
      return "Initializing AI course material...";
    }
    const percent = Number(initialization.percent || 0);
    const message = String(initialization.message || "Initializing AI course material.");
    const elapsed = formatDuration(initialization.elapsed_seconds);
    const remaining = formatDuration(initialization.estimated_remaining_seconds);
    const timing = [];
    if (elapsed) {
      timing.push(`${elapsed} elapsed`);
    }
    if (remaining) {
      timing.push(`about ${remaining} left`);
    }
    const suffix = timing.length ? ` (${timing.join(", ")})` : "";
    return `${percent}% ${message}${suffix}`;
  }

  function renderInitializationProgress() {
    if (!nav.initProgress || !nav.initProgressFill || !nav.initProgressMeta) {
      return;
    }
    const show = initializationRunning() || initializationFailed();
    nav.initProgress.hidden = !show;
    if (!show) {
      nav.initProgressFill.style.width = "0%";
      nav.initProgressMeta.textContent = "";
      return;
    }
    const percent = Math.max(0, Math.min(100, Number(initializationState.percent || 0)));
    nav.initProgressFill.style.width = `${percent}%`;
    nav.initProgressMeta.textContent = initializationFailed()
      ? String(initializationState.error || initializationState.message || "Initialization failed.")
      : formatInitializationStatus(initializationState);
  }

  function formatDuration(value) {
    const seconds = Number(value || 0);
    if (!Number.isFinite(seconds) || seconds <= 0) {
      return "";
    }
    if (seconds < 60) {
      return `${Math.round(seconds)}s`;
    }
    const minutes = Math.floor(seconds / 60);
    const remainder = Math.round(seconds % 60);
    return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;
  }

  function renderRecentProjects() {
    if (!nav.recent) {
      return;
    }
    const entries = runtimeApi.recent.list();
    nav.recent.replaceChildren();
    if (entries.length === 0) {
      const empty = document.createElement("button");
      empty.type = "button";
      empty.className = "stage-action-button";
      empty.disabled = true;
      empty.textContent = "No recent";
      nav.recent.append(empty);
    } else {
      for (const recent of entries) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "stage-action-button";
        button.textContent = basename(recent.path || recent.label || "Project");
        button.title = recent.path || runtimeApi.recent.label(recent);
        button.disabled = Boolean(activationRoot);
        button.addEventListener("click", () => {
          runtimeApi.recent.open(recent).catch((error) => {
            setStatus(error.message || String(error), "error");
          });
        });
        nav.recent.append(button);
      }
    }
  }

  function renderOutline() {
    if (!nav.outline) {
      return;
    }
    nav.outline.replaceChildren();
    const walkthrough = learnerState.currentWalkthrough;
    const steps = walkthroughSteps(walkthrough);
    if (!walkthrough || steps.length === 0) {
      const empty = document.createElement("button");
      empty.type = "button";
      empty.className = "stage-action-button";
      empty.disabled = true;
      empty.textContent = "No course";
      nav.outline.append(empty);
      return;
    }
    for (const step of steps) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "stage-action-button code-learner-step-button";
      button.textContent = step.title || step.id;
      button.title = referenceLabel(step.primary_reference);
      if (step.id === walkthrough.current_step_id) {
        button.setAttribute("aria-current", "step");
      }
      button.addEventListener("click", () => {
        selectStep(step.id).catch((error) => {
          setStatus(error.message || String(error), "error");
        });
      });
      nav.outline.append(button);
    }
  }

  function renderModuleOptions(modules, initialized) {
    if (!nav.module) {
      return;
    }
    const signature = JSON.stringify({
      initialized,
      selectedModuleTarget,
      modules: modules.map((module) => [module.path, module.file_count]),
    });
    if (nav.module.dataset.signature === signature) {
      return;
    }
    nav.module.replaceChildren();
    if (!initialized) {
      nav.module.append(moduleOption("", "Initialize first"));
    } else if (modules.length === 0) {
      nav.module.append(moduleOption("", "No modules"));
    } else {
      nav.module.append(moduleOption("", "Select module"));
      for (const module of modules) {
        const target = String(module.path || "");
        nav.module.append(moduleOption(target, moduleLabel(module)));
      }
    }
    selectedModuleTarget = moduleTargetExists(selectedModuleTarget, modules)
      ? selectedModuleTarget
      : "";
    nav.module.value = selectedModuleTarget;
    nav.module.dataset.signature = signature;
    nav.moduleStart.disabled =
      !initialized || modules.length === 0 || !nav.module.value.trim();
  }

  function disabledAction(label) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "stage-action-button";
    button.disabled = true;
    button.textContent = label;
    return button;
  }

  function moduleOption(value, label) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    return option;
  }

  function moduleTargetExists(target, modules) {
    return modules.some((module) => String(module.path || "") === target);
  }

  function renderSymbolOptions(symbols) {
    if (!nav.symbols) {
      return;
    }
    nav.symbols.replaceChildren();
    for (const symbol of symbols.slice(0, 80)) {
      const option = document.createElement("option");
      option.value = String(symbol.qualified_name || symbol.name || "");
      option.label = String(symbol.file_path || "");
      nav.symbols.append(option);
    }
  }

  function moduleLabel(module) {
    const path = String(module.path || "");
    const count = Number(module.file_count || 0);
    return count > 0 ? `${path} (${count})` : path;
  }

  function learnerModules() {
    const analysis = learnerState.analysis || {};
    return Array.isArray(analysis.modules) ? analysis.modules : [];
  }

  function learnerSymbols() {
    const analysis = learnerState.analysis || {};
    return Array.isArray(analysis.symbols) ? analysis.symbols : [];
  }

  async function loadMatchingSymbols() {
    if (!nav.function || !activeProjectRoot) {
      return;
    }
    const query = nav.function.value.trim();
    if (!query) {
      renderSymbolOptions(learnerSymbols());
      return;
    }
    const response = await runtimeApi.http.fetch(
      contextUrl(`/api/code-learner/symbols?query=${encodeURIComponent(query)}`),
      { cache: "no-store" },
    );
    const payload = await response.json().catch(() => ({ symbols: [] }));
    if (response.ok && Array.isArray(payload.symbols)) {
      renderSymbolOptions(payload.symbols);
    }
  }

  async function initializeCodeLearner() {
    if (!contextId || !(activeProjectRoot || activationRoot)) {
      return;
    }
    if (initializationRunning()) {
      pollInitializationStatus({ immediate: true }).catch((error) => {
        setStatus(error.message || String(error), "error");
      });
      return;
    }
    setStatus("Initializing AI course material...");
    setGenerating(true);
    let payload = null;
    try {
      const response = await runtimeApi.http.fetch(
        contextUrl("/api/code-learner/init"),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        },
      );
      payload = await response.json().catch(() => ({ error: "load failed" }));
      if (!response.ok) {
        throw new Error(payload.error || "load failed");
      }
    } catch (error) {
      setGenerating(false);
      throw error;
    }
    applyInitializationPayload(payload);
    renderNavigationState();
    if (payload.status === "initialized") {
      setGenerating(false);
      openLearnerPane({ activate: false, refresh: true });
      setInitializedStatus();
      return;
    }
    if (payload.status === "failed") {
      setGenerating(false);
      setStatus(payload.initialization.error || "Initialization failed.", "error");
      return;
    }
    scheduleInitializationPoll();
    setStatus(formatInitializationStatus(initializationState));
  }

  async function pollInitializationStatus(options = {}) {
    if (!contextId || !(activeProjectRoot || activationRoot)) {
      stopInitializationPolling();
      return;
    }
    if (options.immediate) {
      stopInitializationPolling();
    }
    const response = await runtimeApi.http.fetch(
      contextUrl("/api/code-learner/init/status"),
      { cache: "no-store" },
    );
    const payload = await response.json().catch(() => ({ error: "status failed" }));
    if (!response.ok) {
      stopInitializationPolling();
      setGenerating(false);
      throw new Error(payload.error || "status failed");
    }
    applyInitializationPayload(payload);
    renderNavigationState();
    if (payload.status === "initialized") {
      stopInitializationPolling();
      setGenerating(false);
      openLearnerPane({ activate: false, refresh: true });
      setInitializedStatus();
    } else if (payload.status === "failed") {
      stopInitializationPolling();
      setGenerating(false);
      setStatus(payload.initialization.error || "Initialization failed.", "error");
    } else if (payload.status === "initializing") {
      setGenerating(true);
      scheduleInitializationPoll();
    } else {
      stopInitializationPolling();
      setGenerating(false);
    }
  }

  function scheduleInitializationPoll() {
    if (initializationPollTimer !== null) {
      return;
    }
    initializationPollTimer = window.setTimeout(() => {
      initializationPollTimer = null;
      pollInitializationStatus().catch((error) => {
        setGenerating(false);
        setStatus(error.message || String(error), "error");
      });
    }, INITIALIZATION_POLL_INTERVAL_MS);
  }

  function stopInitializationPolling() {
    if (initializationPollTimer !== null) {
      window.clearTimeout(initializationPollTimer);
      initializationPollTimer = null;
    }
  }

  function setInitializedStatus() {
    const analysis = learnerState.analysis || {};
    const moduleCount = Array.isArray(analysis.modules) ? analysis.modules.length : 0;
    const symbolCount = Array.isArray(analysis.symbols) ? analysis.symbols.length : 0;
    setStatus(`AI course initialized: ${moduleCount} modules, ${symbolCount} symbols.`);
  }

  async function generateCourse(options = {}) {
    if (!activeProjectRoot && !activationRoot) {
      setStatus("Activate a project first.", "error");
      return;
    }
    if (!learnerInitialized()) {
      setStatus("Initialize learning context first.", "error");
      return;
    }
    const mode = normalizeCourseMode(options.mode || courseMode);
    courseMode = mode;
    const target = Object.hasOwn(options, "target") ? options.target : courseTarget(mode);
    if (mode === "module") {
      selectedModuleTarget = String(target || "");
    }
    if (mode !== "architecture" && !target) {
      setStatus(`${modeLabel(mode)} target required.`, "error");
      return;
    }
    setGenerating(true);
    setStatus(`Generating ${modeLabel(mode)} course...`);
    const response = await runtimeApi.http.fetch(
      contextUrl("/api/code-learner/walkthrough"),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          learning_mode: mode,
          target,
          intended_audience: nav.audience.value.trim(),
        }),
      },
    ).finally(() => {
      setGenerating(false);
    });
    const payload = await response.json().catch(() => ({ error: "generation failed" }));
    if (!response.ok) {
      throw new Error(payload.error || "generation failed");
    }
    applyLearnerPayload(payload);
    renderNavigationState();
    openLearnerPane({ refresh: true });
    setStatus(`Ready: ${payload.walkthrough.title || "course"}`);
  }

  function setGenerating(isGenerating) {
    if (!nav.learnActions) {
      return;
    }
    const hasProject = Boolean(activeProjectRoot || activationRoot);
    const initialized = learnerInitialized();
    const busy = isGenerating || initializationRunning();
    const modules = learnerModules();
    nav.initialize.disabled = busy || !hasProject;
    nav.architecture.disabled = busy || !initialized;
    nav.moduleMenu.disabled = busy || !initialized;
    nav.module.disabled = busy || !initialized || modules.length === 0;
    nav.functionMenu.disabled = busy || !initialized;
    nav.function.disabled = busy || !initialized;
    nav.audience.disabled = busy || !initialized;
    nav.startAgent.disabled = busy || !hasProject || !learnerState.currentWalkthrough;
    nav.moduleStart.disabled =
      busy || !initialized || modules.length === 0 || !nav.module.value.trim();
    nav.functionStart.disabled =
      busy || !initialized || !nav.function.value.trim();
  }

  function courseTarget(mode = courseMode) {
    if (mode === "module") {
      return selectedModuleTarget;
    }
    if (mode === "function") {
      return nav.function.value.trim();
    }
    return "";
  }

  function normalizeCourseMode(mode) {
    const normalized = String(mode || "").toLowerCase();
    return Object.hasOwn(MODE_LABELS, normalized) ? normalized : "architecture";
  }

  async function selectStep(stepId) {
    const walkthrough = learnerState.currentWalkthrough;
    if (!walkthrough || !stepId) {
      return;
    }
    const response = await runtimeApi.http.fetch(
      contextUrl("/api/code-learner/walkthrough/step"),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          walkthrough_id: walkthrough.id,
          step_id: stepId,
        }),
      },
    );
    const payload = await response.json().catch(() => ({ error: "step failed" }));
    if (!response.ok) {
      throw new Error(payload.error || "step failed");
    }
    applyLearnerPayload(payload);
    renderNavigationState();
    openLearnerPane({ refresh: true });
  }

  async function startTutor(runtime) {
    bindRuntime(runtime);
    const walkthrough = learnerState.currentWalkthrough;
    if (!walkthrough) {
      setStatus("Generate a course first.", "error");
      return null;
    }
    setStatus("Starting tutor...");
    runtime.ui.setAgentInputVisible(true);
    runtime.layout.ensurePane("agent", "code-learner", "row", {
      activate: false,
      ratio: 0.34,
    });
    const response = await runtime.http.fetch(
      contextUrl("/api/code-learner/agent/start"),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          walkthrough_id: walkthrough.id,
          ...contextOptionsFromCurrent(),
        }),
      },
    );
    const payload = await response.json().catch(() => ({ error: "start failed" }));
    if (!response.ok) {
      throw new Error(payload.error || "start failed");
    }
    runtime.project.update(payload);
    const sessionId = payload.session_id || runtime.getState().selectedSessionId;
    if (sessionId) {
      runtime.modules.invoke("agent-sessions", "connectSessionEvents", sessionId);
      runtime.agent.sendResize();
    }
    setStatus(payload.status === "running" ? "Tutor running." : "Tutor started.");
    return payload;
  }

  function openLearnerPane(options = {}) {
    if (!runtimeApi || !runtimeApi.layout) {
      return;
    }
    runtimeApi.layout.assignPane(
      "code-learner",
      learnerPaneItem(Boolean(options.refresh)),
      "",
      {
        targetPane: "agent",
        direction: "row",
        ratio: 0.66,
        activate: options.activate !== false,
      },
    );
  }

  function learnerPaneItem(refresh = false) {
    const walkthrough = learnerState.currentWalkthrough;
    return {
      id: "code-learner-main",
      kind: "code-learner",
      title: walkthrough ? walkthrough.title : "Code Learner",
      walkthroughId: walkthrough ? walkthrough.id : "",
      updatedAt: refresh ? String(Date.now()) : "",
    };
  }

  function applyLearnerPayload(payload) {
    if (!payload || typeof payload !== "object") {
      return;
    }
    if (Object.hasOwn(payload, "state_path") && !Object.hasOwn(payload, "analysis")) {
      learnerState.analysis = null;
    }
    if (Object.hasOwn(payload, "analysis")) {
      learnerState.analysis = payload.analysis;
    }
    if (Array.isArray(payload.walkthroughs)) {
      learnerState.walkthroughs = payload.walkthroughs;
    }
    if (Object.hasOwn(payload, "current_walkthrough")) {
      learnerState.currentWalkthrough = payload.current_walkthrough || null;
    }
    if (Object.hasOwn(payload, "walkthrough")) {
      learnerState.currentWalkthrough = payload.walkthrough || null;
    }
    syncCourseTargetFromWalkthrough();
    if (Object.hasOwn(payload, "source")) {
      learnerState.source = payload.source;
      learnerContext = payload.source ? contextFromState() : null;
    }
  }

  function syncCourseTargetFromWalkthrough() {
    const walkthrough = learnerState.currentWalkthrough;
    if (!walkthrough) {
      return;
    }
    courseMode = normalizeCourseMode(walkthrough.learning_mode);
    if (courseMode === "module") {
      selectedModuleTarget = String(walkthrough.mode_target || "");
    } else if (courseMode === "function" && nav.function && !nav.function.value) {
      nav.function.value = String(walkthrough.mode_target || "");
    }
  }

  function currentStep() {
    return currentStepForWalkthrough(learnerState.currentWalkthrough);
  }

  function currentStepForWalkthrough(walkthrough) {
    const steps = walkthroughSteps(walkthrough);
    if (steps.length === 0) {
      return null;
    }
    return steps.find((step) => step.id === walkthrough.current_step_id) || steps[0];
  }

  function walkthroughSteps(walkthrough) {
    return walkthrough && Array.isArray(walkthrough.steps) ? walkthrough.steps : [];
  }

  function currentStepPosition(walkthrough, stepId) {
    const steps = walkthroughSteps(walkthrough);
    const index = steps.findIndex((step) => step.id === stepId);
    return index >= 0 ? `${index + 1}/${steps.length}` : `?/${steps.length}`;
  }

  function contextFromState() {
    const walkthrough = learnerState.currentWalkthrough;
    const step = currentStep();
    const source = learnerState.source || {};
    if (!walkthrough || !step) {
      return null;
    }
    const reference = step.primary_reference || {};
    const start = Number(reference.start_line || source.active_start_line || 1);
    const end = Number(reference.end_line || source.active_end_line || start);
    return {
      workflow: WORKFLOW_ID,
      walkthrough_id: walkthrough.id || "",
      learning_mode: walkthrough.learning_mode || "",
      mode_target: walkthrough.mode_target || "",
      step_id: step.id || "",
      step_title: step.title || "",
      step_position: currentStepPosition(walkthrough, step.id),
      file_path: reference.file_path || source.path || "",
      start_line: start,
      end_line: end,
      symbol: reference.symbol || "",
      selected_file_path: "",
      selected_start_line: null,
      selected_end_line: null,
      visible_start_line: source.window_start_line || null,
      visible_end_line: source.window_end_line || null,
      source_excerpt: excerptFromSource(source, start, end),
    };
  }

  function contextOptionsFromCurrent() {
    const context = learnerContext || contextFromState() || {};
    return {
      selected_file_path: context.selected_file_path || "",
      selected_start_line: context.selected_start_line || null,
      selected_end_line: context.selected_end_line || null,
      visible_start_line: context.visible_start_line || null,
      visible_end_line: context.visible_end_line || null,
    };
  }

  function preparePrompt(runtime, message) {
    bindRuntime(runtime);
    const text = String(message || "").trim();
    if (!text || text.startsWith(CONTEXT_HEADER)) {
      return message;
    }
    const context = learnerContext || contextFromState();
    if (!context || !context.walkthrough_id) {
      return message;
    }
    return learnerPrompt(text, context);
  }

  function learnerPrompt(question, context) {
    const lines = [
      CONTEXT_HEADER,
      `Walkthrough: ${context.walkthrough_id || ""}`,
      `Mode: ${context.learning_mode || ""}`,
      `Target: ${context.mode_target || ""}`,
      `Step: ${context.step_position || ""} ${context.step_title || ""}`.trim(),
      (
        `Source: ${context.file_path || ""}:` +
        `${context.start_line || ""}-${context.end_line || ""}`
      ),
      "Use this context to answer the user's learning question. Explain only;",
      "do not edit files, run commands, or perform implementation work.",
    ];
    if (context.source_excerpt) {
      lines.push("", "Source excerpt:", context.source_excerpt);
    }
    lines.push(CONTEXT_FOOTER, "", question);
    return `${lines.join("\n").trim()}\n`;
  }

  function handleWindowMessage(runtime, data) {
    bindRuntime(runtime);
    if (!data || typeof data !== "object") {
      return false;
    }
    if (data.type === "electroboy-code-learner-context") {
      learnerContext = data.context || null;
      if (learnerContext && learnerContext.step_id && learnerState.currentWalkthrough) {
        learnerState.currentWalkthrough.current_step_id = learnerContext.step_id;
        renderNavigationState();
      }
      return true;
    }
    if (data.type === "electroboy-code-learner-question") {
      const prompt = String(data.prompt || "");
      if (prompt) {
        runtime.ui.setAgentInputVisible(true);
        runtime.ui.insertTextAtCursor(prompt);
      }
      return true;
    }
    if (data.type === "electroboy-code-learner-start-agent") {
      startTutor(runtime).catch((error) => {
        setStatus(error.message || String(error), "error");
      });
      return true;
    }
    return false;
  }

  function renderProjectStatus(runtime) {
    bindRuntime(runtime);
    const walkthrough = learnerState.currentWalkthrough;
    const lines = [];
    if (activeProjectRoot) {
      lines.push(`Project: ${activeProjectRoot}`);
    }
    if (walkthrough) {
      lines.push(`Course: ${walkthrough.title}`);
      lines.push(`Mode: ${modeLabel(walkthrough.learning_mode)}`);
      const step = currentStep();
      if (step) {
        lines.push(`Step: ${currentStepPosition(walkthrough, step.id)} ${step.title}`);
      }
    }
    runtime.project.renderStatus(lines.length ? lines : ["No project active."]);
  }

  function setStatus(message, kind = "") {
    if (!nav.status) {
      return;
    }
    nav.status.textContent = message || "";
    nav.status.dataset.kind = kind;
  }

  function referenceLabel(reference) {
    if (!reference) {
      return "";
    }
    return `${reference.file_path || ""}:${reference.start_line || 1}-${reference.end_line || 1}`;
  }

  function excerptFromSource(source, startLine, endLine) {
    const lines = source && Array.isArray(source.lines) ? source.lines : [];
    return lines
      .filter((line) => {
        const number = Number(line.number || 0);
        return number >= startLine && number <= endLine;
      })
      .map((line) => `${line.number}: ${line.text || ""}`)
      .join("\n");
  }

  function debounce(callback, delay) {
    let timer = null;
    return (...args) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => callback(...args), delay);
    };
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function highlightCodeLine(text, language) {
    const keywords = new Set(KEYWORDS[language] || []);
    const matcher = /("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|#[^\n]*|\/\/[^\n]*|\b\d+(?:\.\d+)?\b|\b[A-Za-z_$][\w$]*\b)/g;
    let cursor = 0;
    let html = "";
    String(text ?? "").replace(matcher, (match, _token, offset) => {
      html += escapeHtml(String(text ?? "").slice(cursor, offset));
      html += highlightedToken(match, keywords);
      cursor = offset + match.length;
      return match;
    });
    html += escapeHtml(String(text ?? "").slice(cursor));
    return html || " ";
  }

  function highlightedToken(token, keywords) {
    if (/^(#|\/\/)/.test(token)) {
      return `<span class="tok-comment">${escapeHtml(token)}</span>`;
    }
    if (/^("|')/.test(token)) {
      return `<span class="tok-string">${escapeHtml(token)}</span>`;
    }
    if (/^\d/.test(token)) {
      return `<span class="tok-number">${escapeHtml(token)}</span>`;
    }
    if (keywords.has(token)) {
      return `<span class="tok-keyword">${escapeHtml(token)}</span>`;
    }
    return escapeHtml(token);
  }

  function mountPane(options) {
    const host = options.host;
    const state = {
      host,
      contextUrl: options.contextUrl,
      postMessage: options.postMessage || (() => {}),
      walkthrough: null,
      source: null,
      analysis: null,
      initialization: null,
      busy: false,
      error: "",
      selectedStartLine: null,
      selectedEndLine: null,
      lastSelectedLine: null,
    };

    host.classList.add("code-learner-pane-host");
    renderPane(state);
    loadPaneState(state);
  }

  async function loadPaneState(state) {
    state.busy = true;
    state.error = "";
    renderPane(state);
    try {
      const response = await fetch(
        state.contextUrl("/api/code-learner/init/status"),
        { cache: "no-store" },
      );
      const payload = await response.json().catch(() => ({ error: "load failed" }));
      if (!response.ok) {
        throw new Error(payload.error || "load failed");
      }
      if (payload.initialization) {
        state.initialization = payload.initialization;
      }
      applyPanePayload(state, payload.code_learner || payload);
    } catch (error) {
      state.error = error.message || String(error);
    } finally {
      state.busy = false;
      renderPane(state);
      notifyPaneContext(state);
    }
  }

  function applyPanePayload(state, payload) {
    if (!payload || typeof payload !== "object") {
      return;
    }
    if (payload.analysis) {
      state.analysis = payload.analysis;
    }
    if (payload.initialization) {
      state.initialization = payload.initialization;
    }
    if (payload.current_walkthrough) {
      state.walkthrough = payload.current_walkthrough;
    }
    if (payload.walkthrough) {
      state.walkthrough = payload.walkthrough;
    }
    if (payload.source) {
      state.source = payload.source;
      state.selectedStartLine = null;
      state.selectedEndLine = null;
      state.lastSelectedLine = null;
    }
  }

  function renderPane(state) {
    const walkthrough = state.walkthrough;
    const step = currentPaneStep(state);
    state.host.innerHTML = `
      <article class="code-learner-pane">
        <header class="code-learner-pane-header">
          <div class="code-learner-pane-title">
            <strong>${escapeHtml(walkthrough ? walkthrough.title : "Code Learner")}</strong>
            <span>${escapeHtml(paneHeaderDetail(state))}</span>
          </div>
          <div class="code-learner-pane-actions">
            <button type="button" data-code-learner-pane="prev">Prev</button>
            <button type="button" data-code-learner-pane="next">Next</button>
            <button type="button" data-code-learner-pane="start-agent">Tutor</button>
            <button type="button" data-code-learner-pane="refresh">Refresh</button>
          </div>
        </header>
        <div class="code-learner-pane-grid">
          <section class="code-learner-code-surface">
            ${renderPaneSource(state)}
          </section>
          <section class="code-learner-slide">
            ${renderPaneSlide(state, step)}
          </section>
        </div>
      </article>
    `;
    bindPaneEvents(state);
  }

  function paneHeaderDetail(state) {
    if (state.busy) {
      return "Loading";
    }
    if (state.error) {
      return state.error;
    }
    if (paneInitializationRunning(state)) {
      return formatInitializationStatus(state.initialization);
    }
    const step = currentPaneStep(state);
    if (!state.walkthrough || !step) {
      return "No course";
    }
    return `${modeLabel(state.walkthrough.learning_mode)} - ${currentStepPosition(state.walkthrough, step.id)}`;
  }

  function currentPaneStep(state) {
    return currentStepForWalkthrough(state.walkthrough);
  }

  function paneInitializationRunning(state) {
    const status = state.initialization && state.initialization.status;
    return status === "queued" || status === "running";
  }

  function renderPaneSource(state) {
    const source = state.source || {};
    const lines = Array.isArray(source.lines) ? source.lines : [];
    if (state.busy) {
      return `<div class="code-learner-empty">Loading source</div>`;
    }
    if (state.error) {
      return `<div class="code-learner-empty">${escapeHtml(state.error)}</div>`;
    }
    if (paneInitializationRunning(state)) {
      return `<div class="code-learner-empty">${escapeHtml(formatInitializationStatus(state.initialization))}</div>`;
    }
    if (!lines.length) {
      return `<div class="code-learner-empty">No source selected</div>`;
    }
    const language = source.language || "plain";
    return `
      <div class="code-learner-code-header">
        <span>${escapeHtml(source.path || "")}</span>
        <span>${escapeHtml(language)}</span>
      </div>
      <div class="code-learner-code-lines" role="list">
        ${lines.map((line) => renderPaneLine(state, line, language)).join("")}
      </div>
    `;
  }

  function renderPaneLine(state, line, language) {
    const number = Number(line.number || 0);
    const selected = lineSelected(state, number);
    const active = Boolean(line.active);
    return `
      <button class="code-learner-code-line${active ? " active" : ""}${selected ? " selected" : ""}"
              type="button" data-line="${number}" role="listitem">
        <span class="code-learner-line-number">${number}</span>
        <code>${highlightCodeLine(line.text || "", language)}</code>
      </button>
    `;
  }

  function lineSelected(state, number) {
    if (state.selectedStartLine === null || state.selectedEndLine === null) {
      return false;
    }
    return number >= state.selectedStartLine && number <= state.selectedEndLine;
  }

  function renderPaneSlide(state, step) {
    if (!state.walkthrough || !step) {
      return `
        <div class="code-learner-empty">
          <strong>${escapeHtml(paneInitializationRunning(state) ? "Initializing" : "No course loaded")}</strong>
          <button type="button" data-code-learner-pane="refresh">Refresh</button>
        </div>
      `;
    }
    const reference = step.primary_reference || {};
    return `
      <div class="code-learner-slide-copy">
        <div class="code-learner-slide-kicker">
          ${escapeHtml(currentStepPosition(state.walkthrough, step.id))}
          ${escapeHtml(modeLabel(state.walkthrough.learning_mode))}
        </div>
        <h1>${escapeHtml(step.title || "Step")}</h1>
        <p>${escapeHtml(step.explanation || "")}</p>
        <div class="code-learner-reference">
          ${escapeHtml(referenceLabel(reference))}
        </div>
        ${renderRelatedReferences(step)}
      </div>
      <form class="code-learner-question-form"
            data-code-learner-pane="question-form">
        <textarea spellcheck="true" rows="4"
                  data-code-learner-pane="question"
                  placeholder="Ask about this code"></textarea>
        <div class="code-learner-question-actions">
          <button type="button" data-code-learner-pane="start-agent">Tutor</button>
          <button type="submit">Send to input</button>
        </div>
        <div class="code-learner-pane-status"
             data-code-learner-pane="status"></div>
      </form>
    `;
  }

  function renderRelatedReferences(step) {
    const references = Array.isArray(step.secondary_references)
      ? step.secondary_references
      : [];
    if (!references.length) {
      return "";
    }
    return `
      <div class="code-learner-related">
        ${references.slice(0, 6).map((reference) => (
          `<span>${escapeHtml(referenceLabel(reference))}</span>`
        )).join("")}
      </div>
    `;
  }

  function bindPaneEvents(state) {
    const find = (name) => state.host.querySelector(`[data-code-learner-pane="${name}"]`);
    const prev = find("prev");
    const next = find("next");
    const refresh = find("refresh");
    const startAgent = state.host.querySelectorAll('[data-code-learner-pane="start-agent"]');
    const questionForm = find("question-form");
    const steps = walkthroughSteps(state.walkthrough);
    const current = currentPaneStep(state);
    const index = current ? steps.findIndex((step) => step.id === current.id) : -1;
    if (prev) {
      prev.disabled = index <= 0;
      prev.addEventListener("click", () => {
        if (index > 0) {
          selectPaneStep(state, steps[index - 1].id);
        }
      });
    }
    if (next) {
      next.disabled = index < 0 || index >= steps.length - 1;
      next.addEventListener("click", () => {
        if (index >= 0 && index < steps.length - 1) {
          selectPaneStep(state, steps[index + 1].id);
        }
      });
    }
    if (refresh) {
      refresh.addEventListener("click", () => loadPaneState(state));
    }
    for (const button of startAgent) {
      button.addEventListener("click", () => {
        notifyPaneContext(state);
        state.postMessage({ type: "electroboy-code-learner-start-agent" });
      });
    }
    if (questionForm) {
      questionForm.addEventListener("submit", (event) => {
        event.preventDefault();
        preparePaneQuestion(state);
      });
    }
    state.host.querySelectorAll(".code-learner-code-line").forEach((line) => {
      line.addEventListener("click", (event) => {
        selectPaneLine(state, Number(line.dataset.line || "0"), event.shiftKey);
      });
    });
  }

  function selectPaneLine(state, lineNumber, extending) {
    if (!lineNumber) {
      return;
    }
    if (extending && state.lastSelectedLine !== null) {
      state.selectedStartLine = Math.min(state.lastSelectedLine, lineNumber);
      state.selectedEndLine = Math.max(state.lastSelectedLine, lineNumber);
    } else {
      state.selectedStartLine = lineNumber;
      state.selectedEndLine = lineNumber;
      state.lastSelectedLine = lineNumber;
    }
    renderPane(state);
    notifyPaneContext(state);
  }

  async function selectPaneStep(state, stepId) {
    if (!state.walkthrough || !stepId) {
      return;
    }
    state.busy = true;
    renderPane(state);
    try {
      const response = await fetch(
        state.contextUrl("/api/code-learner/walkthrough/step"),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            walkthrough_id: state.walkthrough.id,
            step_id: stepId,
          }),
        },
      );
      const payload = await response.json().catch(() => ({ error: "step failed" }));
      if (!response.ok) {
        throw new Error(payload.error || "step failed");
      }
      applyPanePayload(state, payload);
      notifyPaneContext(state);
    } catch (error) {
      state.error = error.message || String(error);
    } finally {
      state.busy = false;
      renderPane(state);
    }
  }

  async function preparePaneQuestion(state) {
    const input = state.host.querySelector('[data-code-learner-pane="question"]');
    const status = state.host.querySelector('[data-code-learner-pane="status"]');
    const question = input ? input.value.trim() : "";
    if (!question || !state.walkthrough) {
      return;
    }
    if (status) {
      status.textContent = "Preparing...";
    }
    const response = await fetch(state.contextUrl("/api/code-learner/question"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        walkthrough_id: state.walkthrough.id,
        ...paneContextOptions(state),
      }),
    });
    const payload = await response.json().catch(() => ({ error: "question failed" }));
    if (!response.ok) {
      if (status) {
        status.textContent = payload.error || "question failed";
      }
      return;
    }
    applyPanePayload(state, payload);
    state.postMessage({
      type: "electroboy-code-learner-question",
      prompt: payload.prompt || learnerPrompt(question, paneContext(state)),
      question,
    });
    if (input) {
      input.value = "";
    }
    if (status) {
      status.textContent = "Sent to input.";
    }
    notifyPaneContext(state);
  }

  function notifyPaneContext(state) {
    const context = paneContext(state);
    if (!context) {
      return;
    }
    state.postMessage({
      type: "electroboy-code-learner-context",
      context,
    });
  }

  function paneContextOptions(state) {
    const context = paneContext(state) || {};
    return {
      selected_file_path: context.selected_file_path || "",
      selected_start_line: context.selected_start_line || null,
      selected_end_line: context.selected_end_line || null,
      visible_start_line: context.visible_start_line || null,
      visible_end_line: context.visible_end_line || null,
    };
  }

  function paneContext(state) {
    const walkthrough = state.walkthrough;
    const step = currentPaneStep(state);
    const source = state.source || {};
    if (!walkthrough || !step) {
      return null;
    }
    const reference = step.primary_reference || {};
    const hasSelection = state.selectedStartLine !== null;
    const start = hasSelection
      ? state.selectedStartLine
      : Number(reference.start_line || source.active_start_line || 1);
    const end = hasSelection
      ? state.selectedEndLine
      : Number(reference.end_line || source.active_end_line || start);
    const path = source.path || reference.file_path || "";
    return {
      workflow: WORKFLOW_ID,
      walkthrough_id: walkthrough.id || "",
      learning_mode: walkthrough.learning_mode || "",
      mode_target: walkthrough.mode_target || "",
      step_id: step.id || "",
      step_title: step.title || "",
      step_position: currentStepPosition(walkthrough, step.id),
      file_path: path,
      start_line: start,
      end_line: end,
      symbol: reference.symbol || "",
      selection_active: hasSelection,
      selected_file_path: hasSelection ? path : "",
      selected_start_line: hasSelection ? start : null,
      selected_end_line: hasSelection ? end : null,
      visible_start_line: source.window_start_line || null,
      visible_end_line: source.window_end_line || null,
      source_excerpt: excerptFromSource(source, start, end),
    };
  }

  if (window.ElectroBoyFrontend) {
    window.ElectroBoyFrontend.registerWorkflow({
      id: WORKFLOW_ID,
      mode: WORKFLOW_ID,
      label: "Code Learner",
      order: 30,
      backendPackage: "electroboy.workflows.code_learner",
      navigation: "sidebar",
      defaultPaneLayout: {
        type: "split",
        direction: "row",
        ratio: 0.66,
        first: { type: "leaf", kind: "code-learner" },
        second: {
          type: "split",
          direction: "column",
          ratio: 0.62,
          first: { type: "leaf", kind: "agent" },
          second: { type: "leaf", kind: "input" },
        },
      },
      layoutClass: "code-learner-workflow",
      help: {
        summary:
          "Explore a project through generated architecture, module, and function lessons.",
        features: [
          "Generate source-linked course steps from a project scan.",
          "Select module and function targets for focused explanations.",
          "Keep learner questions grounded in the currently visible source range.",
        ],
      },
      recentProjectFilter: (project) => project.kind === "code-learner",
      projectEndpoint,
      projectChanged,
      renderProjectStatus,
      renderNavigation,
      refreshNavigation,
      activate,
      deactivate,
      handleWindowMessage,
      actions: {
        preparePrompt: (runtime, ...args) => invoke(runtime, preparePrompt, args),
        startTutor: (runtime, ...args) => invoke(runtime, startTutor, args),
        initializeCodeLearner: (runtime, ...args) =>
          invoke(runtime, initializeCodeLearner, args),
        generateCourse: (runtime, ...args) => invoke(runtime, generateCourse, args),
      },
    });
  }

  window.ElectroBoyCodeLearnerPane = {
    mount: mountPane,
  };
})();
