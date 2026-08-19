(function () {
  "use strict";

  let runtimeApi = null;
  let scratchPad = null;
  let agentInput = null;
  let activationRoot = "";
  let activeProjectRoot = "";
  let currentWorkflowStage = "project";
  let requirementsApproved = false;
  let designApproved = false;
  let designReviewInteractive = false;
  let designReviewRunning = false;
  let artifactPreviewStage = "";
  let selectedSessionId = "";
  let adHocSessionDialog = null;
  let corkboardDialog = null;

  function bindRuntime(runtime) {
    runtimeApi = runtime;
    const state = runtime.getState();
    scratchPad = runtime.elements.scratchPad;
    agentInput = runtime.elements.agentInput;
    activationRoot = state.activationRoot || "";
    activeProjectRoot = state.activeProjectRoot || "";
    currentWorkflowStage = state.currentWorkflowStage || "project";
    requirementsApproved = Boolean(state.requirementsApproved);
    designApproved = Boolean(state.designApproved);
    designReviewInteractive = Boolean(state.designReviewInteractive);
    designReviewRunning = Boolean(state.designReviewRunning);
    artifactPreviewStage = state.artifactPreviewStage || "";
    selectedSessionId = state.selectedSessionId || "";
  }

  function resetSoftwareWorkflowState() {
    if (adHocSessionDialog) {
      adHocSessionDialog.remove();
      adHocSessionDialog = null;
    }
    if (corkboardDialog) {
      corkboardDialog.remove();
      corkboardDialog = null;
    }
    scratchPad = null;
    agentInput = null;
    activationRoot = "";
    activeProjectRoot = "";
    currentWorkflowStage = "project";
    requirementsApproved = false;
    designApproved = false;
    designReviewInteractive = false;
    designReviewRunning = false;
    artifactPreviewStage = "";
    selectedSessionId = "";
  }

  function deactivate(runtime) {
    bindRuntime(runtime);
    resetSoftwareWorkflowState();
  }

  function invoke(runtime, handler, args) {
    bindRuntime(runtime);
    return handler(...args);
  }

  function contextUrl(path) {
    return runtimeApi.http.contextUrl(path);
  }

  function appendOutput(text, kind) {
    runtimeApi.notifications.appendOutput(text, kind);
  }

  function updateProjectState(payload) {
    runtimeApi.project.update(payload);
    bindRuntime(runtimeApi);
  }

  function refreshProject() {
    return runtimeApi.project.refresh();
  }

  function restoreScratchPad() {
    return runtimeApi.scratch.restore();
  }

  function hideStageMenus() {
    runtimeApi.ui.hideStageMenus();
  }

  function setAgentInputVisible(visible) {
    runtimeApi.ui.setAgentInputVisible(visible);
  }

  function clearAgentOutput() {
    runtimeApi.agent.clearOutput();
  }

  function sendTerminalResize() {
    runtimeApi.agent.sendResize();
  }

  function closeAgentEventStream() {
    return runtimeApi.modules.invoke("agent-sessions", "closeAgentEventStream");
  }

  function connectAgentEvents(kind) {
    return runtimeApi.modules.invoke("agent-sessions", "connectAgentEvents", kind);
  }

  function connectSessionEvents(sessionId) {
    return runtimeApi.modules.invoke("agent-sessions", "connectSessionEvents", sessionId);
  }

  function renderSessionSwitcher() {
    return runtimeApi.modules.invoke("agent-sessions", "renderSessionSwitcher");
  }

  function setAgentRunning(kind, running) {
    return runtimeApi.modules.invoke("agent-sessions", "setAgentRunning", kind, running);
  }

  function showProgressPane(visible) {
    runtimeApi.layout.showProgressPane(visible);
  }

  function clearProgressOutput() {
    return runtimeApi.modules.invoke("progress", "clearProgressOutput");
  }

  function connectProgressEvents() {
    return runtimeApi.modules.invoke("progress", "connectProgressEvents");
  }

  function closeProgressEventStream() {
    return runtimeApi.modules.invoke("progress", "closeProgressEventStream");
  }

  function showStageArtifactPreview(stage) {
    return runtimeApi.modules.invoke("documents", "showStageArtifactPreview", stage);
  }

  function hideArtifactPreview() {
    return runtimeApi.modules.invoke("documents", "hideArtifactPreview");
  }

  function syncArtifactPreviewWithProject() {
    return runtimeApi.modules.invoke("documents", "syncArtifactPreviewWithProject");
  }

  function genericStageRun(stage) {
    return runtimeApi.workflows.stageRun(stage);
  }

  function workflowActions(runtime) {
    bindRuntime(runtime);
    return {
      approveDesignReviewStage,
      approveGenericStage,
      approveRequirementsStage,
      completeDesignAgent,
      deactivateProject: runtime.project.deactivate,
      genericStageRun,
      openProjectBrowser: runtime.browser.openProject,
      openWorkspace: runtime.workspaces.openSelector,
      recentProjectActions: runtime.recent.actions,
      removeMetaRepository: runtime.metaProject.removeRepository,
      repositoryLabel: runtime.metaProject.repositoryLabel,
      setWorkflowStage: setWorkflowStageFromMenu,
      showProjectPanel: runtime.ui.showProjectPanel,
      showWorkItemPanel: runtime.ui.showWorkItemPanel,
      skipDesignReviewApprovalStage,
      skipGenericStageApproval,
      skipRequirementsApprovalStage,
      startAdHocAgent,
      startAutomaticDesignReviewAgent,
      startDesignAgent,
      startGenericStageAgent,
      startInteractiveDesignReviewAgent,
      startMetaRepository: runtime.metaProject.startRepository,
      startRequirementsAgent,
      stopDesignReviewAgent,
      stopGenericStageAgent,
      switchBug: runtime.workItems.switchBug,
      switchFeature: runtime.workItems.switchFeature,
      workItemBugs: runtime.workItems.bugs,
      workItemFeatures: runtime.workItems.features,
    };
  }

  const STAGE_DESCRIPTIONS = {
    project: "Open an existing ElectroBoy project or create a new one.",
    requirements: "Author or resume the requirements document with the requirements agent.",
    design: "Author the detailed design from the approved requirements.",
    "design-review": "Review the detailed design and capture blocking design issues.",
    "implementation-plan": "Author the implementation plan and implementation units.",
    code: "Implement and commit the planned code changes.",
    "test-plan": "Author the test plan with validation commands and acceptance checks.",
    validate: "Run validation commands and tests, then write the validation report.",
    document: "Update final project documentation after validation passes.",
    corkboard: "Open or create a project corkboard for tasks and working notes.",
  };

  const ARTIFACT_PREVIEWS = {
    requirements: [
      { id: "requirements", kind: "requirements", title: "Requirements" },
    ],
    design: [
      { id: "design", kind: "route", title: "Detailed Design", path: "/artifacts/design" },
    ],
    "design-review": [
      { id: "design", kind: "route", title: "Detailed Design", path: "/artifacts/design" },
      {
        id: "design-review",
        kind: "route",
        title: "Design Review",
        path: "/artifacts/design-review",
      },
    ],
    "implementation-plan": [
      {
        id: "implementation-plan",
        kind: "route",
        title: "Implementation Plan",
        path: "/artifacts/implementation-plan",
      },
    ],
    code: [
      {
        id: "implementation-report",
        kind: "route",
        title: "Implementation Report",
        path: "/artifacts/implementation-report",
      },
    ],
    "test-plan": [
      { id: "test-plan", kind: "route", title: "Test Plan", path: "/artifacts/test-plan" },
    ],
    validate: [
      {
        id: "validation-report",
        kind: "route",
        title: "Validation Report",
        path: "/artifacts/validation-report",
      },
    ],
  };

  function featureLabel(feature) {
    const label = feature.name || feature.slug || "Feature";
    return feature.parent_slug ? `${label} (subfeature)` : label;
  }

  function stageActions(stageId, runtime) {
    bindRuntime(runtime);
    const state = runtime.getState();
    const action = workflowActions(runtime);
    if (stageId === "project") {
      return projectStageActions(runtime, state);
    }
    if (stageId === "requirements") {
      const inStage = state.currentWorkflowStage === "requirements";
      return [
        {
          label: "Set stage",
          title: "Move the workflow to requirements without starting an agent.",
          disabled: !state.activeProjectRoot || inStage,
          run: () => action.setWorkflowStage("requirements"),
        },
        {
          label: "Start",
          title: "Launch or resume the interactive requirements authoring agent.",
          primary: true,
          disabled: !state.activeProjectRoot || !inStage || state.requirementsRunning,
          run: action.startRequirementsAgent,
        },
        {
          label: "Approve",
          title: "Record requirements approval and advance the workflow.",
          disabled: !state.activeProjectRoot || !inStage,
          run: action.approveRequirementsStage,
        },
        {
          label: "Skip approval",
          title: "Force requirements approval when the operator accepts the risk.",
          disabled: !state.activeProjectRoot || !inStage,
          run: action.skipRequirementsApprovalStage,
        },
      ];
    }
    if (stageId === "design") {
      const inStage = state.currentWorkflowStage === "design";
      return [
        {
          label: "Set stage",
          title: "Move the workflow to design without starting an agent.",
          disabled: !state.activeProjectRoot || inStage,
          run: () => action.setWorkflowStage("design"),
        },
        {
          label: "Start",
          title: "Launch or resume the interactive design authoring agent.",
          primary: true,
          disabled: !state.activeProjectRoot || !inStage || state.designRunning,
          run: action.startDesignAgent,
        },
        {
          label: "Complete",
          title: "Finish design authoring and move to design review.",
          disabled: !state.activeProjectRoot || !inStage,
          run: action.completeDesignAgent,
        },
      ];
    }
    if (stageId === "design-review") {
      return automaticStageActions(runtime, {
        stage: "design-review",
        label: "design review",
        inStage: state.currentWorkflowStage === "design-review",
        running: state.designReviewRunning,
        setStage: () => action.setWorkflowStage("design-review"),
        startAutomatic: action.startAutomaticDesignReviewAgent,
        startInteractive: action.startInteractiveDesignReviewAgent,
        stop: action.stopDesignReviewAgent,
        approve: action.approveDesignReviewStage,
        skip: action.skipDesignReviewApprovalStage,
        automaticTitle: "Run the non-interactive design review and design-update loop.",
        interactiveTitle: "Open an interactive design-review agent session.",
      });
    }
    if (stageId === "implementation-plan") {
      return authoringStageActions(runtime, {
        stage: "implementation-plan",
        label: "implementation plan",
        setStage: () => action.setWorkflowStage("implementation-plan"),
        start: () => action.startGenericStageAgent(
          "implementation-plan",
          "$ electroboy implementation-plan",
          true,
        ),
        approve: () => action.approveGenericStage(
          "implementation-plan",
          "implementation plan",
        ),
        skip: () => action.skipGenericStageApproval(
          "implementation-plan",
          "Implementation plan",
        ),
        startTitle: "Launch or resume the interactive implementation-plan agent.",
      });
    }
    if (stageId === "code") {
      const actions = automaticStageActions(runtime, {
        stage: "code",
        label: "code",
        inStage: state.currentWorkflowStage === "code",
        running: action.genericStageRun("code").running,
        setStage: () => action.setWorkflowStage("code"),
        startAutomatic: () => action.startGenericStageAgent(
          "code",
          "$ electroboy code",
          false,
        ),
        startInteractive: () => action.startGenericStageAgent(
          "code",
          "$ electroboy code --interactive",
          true,
        ),
        stop: () => action.stopGenericStageAgent("code", "code"),
        approve: () => action.approveGenericStage("code", "code"),
        skip: () => action.skipGenericStageApproval("code", "Code"),
        automaticTitle: "Run the non-interactive coding and review cycle.",
        interactiveTitle: "Open an interactive coding agent session.",
      });
      actions.splice(3, 0, {
        label: state.adHocRunning ? "Focus ad-hoc" : "Start ad-hoc",
        title: state.adHocRunning
          ? "Focus the running ad-hoc agent."
          : "Start a plain interactive agent without staged workflow instructions.",
        disabled: !state.activeProjectRoot,
        run: action.startAdHocAgent,
      });
      return actions;
    }
    if (stageId === "test-plan") {
      return authoringStageActions(runtime, {
        stage: "test-plan",
        label: "test plan",
        setStage: () => action.setWorkflowStage("test-plan"),
        start: () => action.startGenericStageAgent(
          "test-plan",
          "$ electroboy test-plan",
          true,
        ),
        approve: () => action.approveGenericStage("test-plan", "test plan"),
        skip: () => action.skipGenericStageApproval("test-plan", "Test plan"),
        startTitle: "Launch or resume the interactive system test-plan agent.",
      });
    }
    if (stageId === "validate") {
      return automaticStageActions(runtime, {
        stage: "validate",
        label: "validation",
        inStage: state.currentWorkflowStage === "validate",
        running: action.genericStageRun("validate").running,
        setStage: () => action.setWorkflowStage("validate"),
        startAutomatic: () => action.startGenericStageAgent(
          "validate",
          "$ electroboy validate",
          false,
        ),
        startInteractive: () => action.startGenericStageAgent(
          "validate",
          "$ electroboy validate --interactive",
          true,
        ),
        stop: () => action.stopGenericStageAgent("validate", "validation"),
        approve: () => action.approveGenericStage("validate", "validation"),
        skip: () => action.skipGenericStageApproval("validate", "Validation"),
        automaticTitle: "Run the non-interactive validation command set.",
        interactiveTitle: "Open an interactive validation agent session.",
      });
    }
    if (stageId === "corkboard") {
      return [
        {
          label: "Open",
          title: "Open an existing project corkboard.",
          disabled: !state.activeProjectRoot,
          run: openProjectCorkboard,
        },
        {
          label: "New",
          title: "Create and open a new project corkboard.",
          disabled: !state.activeProjectRoot,
          run: newProjectCorkboard,
        },
      ];
    }
    return [];
  }

  function ensureCorkboardDialog() {
    if (corkboardDialog) {
      return corkboardDialog;
    }
    const dialog = document.createElement("dialog");
    dialog.className = "ad-hoc-session-dialog corkboard-picker-dialog";
    dialog.innerHTML = `
      <form method="dialog" class="ad-hoc-session-form">
        <header class="ad-hoc-session-header">
          <div>
            <h2 class="corkboard-picker-title">Project corkboard</h2>
            <p class="corkboard-picker-description"></p>
          </div>
          <button class="ad-hoc-session-close" type="button" aria-label="Close">&times;</button>
        </header>
        <fieldset class="ad-hoc-session-options corkboard-picker-existing">
          <legend>Corkboards</legend>
          <div class="ad-hoc-session-list corkboard-picker-list"></div>
        </fieldset>
        <label class="ad-hoc-session-custom corkboard-picker-new">
          Board name
          <input class="ad-hoc-session-uuid corkboard-picker-name"
                 type="text" maxlength="200" autocomplete="off">
        </label>
        <p class="ad-hoc-session-error corkboard-picker-error" hidden></p>
        <footer class="ad-hoc-session-footer">
          <button class="corkboard-picker-cancel" type="button">Cancel</button>
          <button class="ad-hoc-session-submit corkboard-picker-submit"
                  type="submit">Open</button>
        </footer>
      </form>
    `;
    document.body.append(dialog);
    corkboardDialog = dialog;
    return dialog;
  }

  async function projectCorkboards() {
    const response = await fetch(contextUrl("/api/corkboards"), {
      cache: "no-store",
    });
    const payload = await response.json().catch(() => ({
      error: "corkboard list failed",
    }));
    if (!response.ok) {
      throw new Error(payload.error || "corkboard list failed");
    }
    return payload;
  }

  function showProjectCorkboard(board) {
    runtimeApi.modules.invoke(
      "corkboard",
      "show",
      {
        id: board.board_id,
        provider: board.provider,
        title: board.title,
        freeform: true,
      },
      { stage: "corkboard", freeform: true },
    );
  }

  async function chooseProjectCorkboard(mode) {
    const dialog = ensureCorkboardDialog();
    const existing = dialog.querySelector(".corkboard-picker-existing");
    const newBoard = dialog.querySelector(".corkboard-picker-new");
    const list = dialog.querySelector(".corkboard-picker-list");
    const name = dialog.querySelector(".corkboard-picker-name");
    const error = dialog.querySelector(".corkboard-picker-error");
    const submit = dialog.querySelector(".corkboard-picker-submit");
    const creating = mode === "new";
    dialog.querySelector(".corkboard-picker-title").textContent = creating
      ? "New project corkboard"
      : "Open project corkboard";
    dialog.querySelector(".corkboard-picker-description").textContent = creating
      ? "Create a shared board in this project."
      : "Choose a board associated with this project.";
    existing.hidden = creating;
    newBoard.hidden = !creating;
    error.hidden = true;
    name.value = "";
    submit.textContent = creating ? "Create" : "Open";

    if (!creating) {
      const payload = await projectCorkboards();
      const boards = Array.isArray(payload.boards) ? payload.boards : [];
      if (boards.length === 0) {
        list.innerHTML = '<span class="ad-hoc-session-details">No corkboards yet.</span>';
        submit.disabled = true;
      } else {
        submit.disabled = false;
        list.replaceChildren(...boards.map((board, index) => {
          const option = document.createElement("label");
          option.className = "ad-hoc-session-option";
          const input = document.createElement("input");
          input.type = "radio";
          input.name = "project-corkboard";
          input.value = String(index);
          input.checked = index === 0;
          const copy = document.createElement("span");
          copy.className = "ad-hoc-session-option-copy";
          const title = document.createElement("strong");
          title.textContent = String(board.title || board.board_id);
          const details = document.createElement("span");
          details.className = "ad-hoc-session-details";
          details.textContent = String(board.board_id || "");
          copy.append(title, details);
          option.append(input, copy);
          option.dataset.board = JSON.stringify(board);
          return option;
        }));
      }
    } else {
      submit.disabled = false;
    }

    return new Promise((resolve) => {
      const finish = (value) => {
        dialog.close();
        resolve(value);
      };
      dialog.querySelector(".ad-hoc-session-close").onclick = () => finish(null);
      dialog.querySelector(".corkboard-picker-cancel").onclick = () => finish(null);
      dialog.oncancel = (event) => {
        event.preventDefault();
        finish(null);
      };
      dialog.querySelector("form").onsubmit = (event) => {
        event.preventDefault();
        if (creating) {
          const title = name.value.trim();
          if (!title) {
            error.textContent = "Enter a board name.";
            error.hidden = false;
            name.focus();
            return;
          }
          finish({ title });
          return;
        }
        const selected = list.querySelector('input[name="project-corkboard"]:checked');
        const option = selected ? selected.closest(".ad-hoc-session-option") : null;
        finish(option ? JSON.parse(option.dataset.board) : null);
      };
      dialog.showModal();
      if (creating) {
        name.focus();
      }
    });
  }

  async function openProjectCorkboard() {
    try {
      const board = await chooseProjectCorkboard("open");
      if (board) {
        showProjectCorkboard(board);
      }
    } catch (error) {
      appendOutput(`${error.message || "corkboard open failed"}\n`, "error");
    }
  }

  async function newProjectCorkboard() {
    const choice = await chooseProjectCorkboard("new");
    if (!choice) {
      return;
    }
    const response = await fetch(contextUrl("/api/corkboards"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ board_id: choice.title, title: choice.title }),
    });
    const payload = await response.json().catch(() => ({
      error: "corkboard creation failed",
    }));
    if (!response.ok) {
      appendOutput(`${payload.error || "corkboard creation failed"}\n`, "error");
      return;
    }
    showProjectCorkboard(payload);
  }

  function projectStageActions(runtime, state) {
    const action = workflowActions(runtime);
    const hasContext = Boolean(state.activationRoot);
    const hasProject = Boolean(state.activeProjectRoot);
    const metaActions = [
      {
        label: "Open meta-project",
        title: "Activate an existing ElectroBoy meta-project.",
        disabled: hasContext,
        run: () => action.openProjectBrowser("open", true),
      },
      {
        label: "New meta-project",
        title: "Create and activate a new ElectroBoy meta-project.",
        disabled: hasContext,
        run: () => action.openProjectBrowser("meta-new", true),
      },
      {
        label: "Add",
        title: "Choose and register another repository with the active meta-project.",
        disabled: state.activeProjectMode !== "meta",
        run: () => action.openProjectBrowser("meta-add", true),
      },
    ];
    const startRepositoryActions = [];
    const removeRepositoryActions = [];
    for (const repository of state.registeredRepositories) {
      const label = action.repositoryLabel(repository);
      const isActive = label === state.activeRepositoryName;
      startRepositoryActions.push({
        label: isActive ? `Active: ${label}` : label,
        title: String(repository.path || label),
        disabled: state.activeProjectMode !== "meta" || isActive,
        run: () => action.startMetaRepository(repository),
      });
      removeRepositoryActions.push({
        label,
        title: String(repository.path || label),
        disabled: state.activeProjectMode !== "meta",
        run: () => action.removeMetaRepository(repository),
      });
    }
    if (startRepositoryActions.length === 0) {
      const emptyAction = {
        label: "No repositories added",
        title: "Use Add to register a repository first.",
        disabled: true,
      };
      startRepositoryActions.push(emptyAction);
      removeRepositoryActions.push({ ...emptyAction });
    }
    metaActions.push(
      {
        subgroup: "project-meta-remove",
        label: "Remove",
        title: "Remove a repository from this meta-project.",
        disabled: state.activeProjectMode !== "meta",
        actions: removeRepositoryActions,
      },
      {
        subgroup: "project-meta-start",
        label: "Start",
        title: "Start or switch to a registered repository.",
        disabled: state.activeProjectMode !== "meta",
        actions: startRepositoryActions,
      },
    );

    const workItemActions = [
      {
        label: "Add feature",
        title: "Start a new feature workflow in the active project.",
        disabled: !hasProject,
        run: () => action.showWorkItemPanel("feature-new"),
      },
      {
        label: "Add bug resolution",
        title: "Start a new bug-resolution workflow in the active project.",
        disabled: !hasProject,
        run: () => action.showWorkItemPanel("bug-new"),
      },
    ];
    for (const feature of action.workItemFeatures()) {
      workItemActions.push({
        label: `Switch feature: ${featureLabel(feature)}`,
        title: feature.title || feature.slug || "",
        disabled: !hasProject ||
          feature.slug === state.workItemState.active_feature_slug,
        run: () => action.switchFeature(feature.slug),
      });
    }
    for (const bug of action.workItemBugs()) {
      workItemActions.push({
        label: `Switch bug: ${bug.title || bug.slug || "Bug"}`,
        title: bug.reference || bug.slug || "",
        disabled: !hasProject || bug.slug === state.workItemState.active_bug_slug,
        run: () => action.switchBug(bug.slug),
      });
    }

    return [
      {
        label: "Open project",
        title: "Activate an existing ElectroBoy project.",
        disabled: hasContext,
        run: () => action.openProjectBrowser("open", true),
      },
      {
        label: "New project",
        title: "Create and activate a new ElectroBoy project.",
        disabled: hasContext,
        run: () => action.openProjectBrowser("new", true),
      },
      {
        label: "Workspace",
        title: "Attach a detached ElectroBoy workspace.",
        run: action.openWorkspace,
      },
      {
        subgroup: "project-recent",
        label: "Recent projects",
        title: "Open a recently used project.",
        actions: action.recentProjectActions(),
      },
      {
        subgroup: "project-meta",
        label: "Meta project",
        title: "Open, create, or manage repositories in a meta-project.",
        actions: metaActions,
      },
      {
        subgroup: "project-work-items",
        label: "Work items",
        title: "Start or switch feature and bug-resolution workflows.",
        actions: workItemActions,
      },
      {
        label: "Deactivate",
        title: "Deactivate this browser context's active project.",
        disabled: !hasContext,
        run: action.deactivateProject,
      },
    ];
  }

  function authoringStageActions(runtime, options) {
    const state = runtime.getState();
    const inStage = state.currentWorkflowStage === options.stage;
    const runState = genericStageRun(options.stage);
    return [
      {
        label: "Set stage",
        title: `Move the workflow to ${options.stage} without starting an agent.`,
        disabled: !state.activeProjectRoot || inStage,
        run: options.setStage,
      },
      {
        label: "Start",
        title: options.startTitle,
        primary: true,
        disabled: !state.activeProjectRoot || !inStage || runState.running,
        run: options.start,
      },
      {
        label: "Approve",
        title: `Approve ${options.label} and advance the workflow.`,
        disabled: !state.activeProjectRoot || !inStage,
        run: options.approve,
      },
      {
        label: "Skip approval",
        title: `Force ${options.label} approval when the operator accepts the risk.`,
        disabled: !state.activeProjectRoot || !inStage,
        run: options.skip,
      },
    ];
  }

  function automaticStageActions(runtime, options) {
    const hasProject = Boolean(runtime.getState().activeProjectRoot);
    return [
      {
        label: "Set stage",
        title: `Move the workflow to ${options.stage} without starting an agent.`,
        disabled: !hasProject || options.inStage,
        run: options.setStage,
      },
      {
        label: "Start automatic",
        title: options.automaticTitle,
        primary: true,
        disabled: !hasProject || !options.inStage || options.running,
        run: options.startAutomatic,
      },
      {
        label: "Start interactive",
        title: options.interactiveTitle,
        disabled: !hasProject || !options.inStage || options.running,
        run: options.startInteractive,
      },
      {
        label: "Stop",
        title: `Stop the running ${options.label} agent.`,
        disabled: !hasProject || !options.inStage || !options.running,
        run: options.stop,
      },
      {
        label: "Approve",
        title: `Approve ${options.label} and advance the workflow.`,
        disabled: !hasProject || !options.inStage,
        run: options.approve,
      },
      {
        label: "Skip approval",
        title: `Force ${options.label} approval when the operator accepts the risk.`,
        disabled: !hasProject || !options.inStage,
        run: options.skip,
      },
    ];
  }

    function restoreSoftwareWorkspace() {
      scratchPad.spellcheck = true;
      restoreScratchPad();
      syncArtifactPreviewWithProject();
    }

    async function selectWorkflowStage(stageId) {
      if (!activeProjectRoot || stageId === "project") {
        return false;
      }
      const response = await fetch(contextUrl("/api/workflow/stage"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: stageId }),
      });
      const payload = await response.json().catch(() => ({ error: "stage update failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "stage update failed"}\n`, "error");
        return false;
      }
      if (payload.terminated_agent || payload.workflow_stage !== "requirements") {
        closeAgentEventStream();
        showProgressPane(false);
        setAgentInputVisible(true);
        setRequirementsRunning(false);
        agentInput.value = "";
      }
      updateProjectState(payload);
      return true;
    }

    async function setWorkflowStageFromMenu(stageId) {
      if (!activeProjectRoot || currentWorkflowStage === stageId) {
        return;
      }
      hideStageMenus();
      const selected = await selectWorkflowStage(stageId);
      if (selected) {
        appendOutput(`stage set: ${stageId}\n`, "system");
      }
    }

    async function approveRequirementsStage(skipApproval = false) {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\n", "error");
        return;
      }
      if (currentWorkflowStage !== "requirements") {
        return;
      }
      hideStageMenus();
      closeAgentEventStream();
      const endpoint = skipApproval
        ? "/api/agents/requirements/skip-approval"
        : "/api/agents/requirements/approve";
      const response = await fetch(contextUrl(endpoint), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "approval failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "approval failed"}\n`, "error");
        if (payload.output) {
          appendOutput(`${payload.output}\n`, "error");
        }
        return;
      }
      setRequirementsRunning(false);
      agentInput.value = "";
      clearAgentOutput();
      if (payload.output) {
        appendOutput(`${payload.output}\n`, "system");
      }
      if (payload.warning) {
        appendOutput(`${payload.warning}\n`, "system");
      }
      appendOutput(
        skipApproval
          ? "requirements approval skipped; next: design\n"
          : "requirements approved; next: design\n",
        "system",
      );
      updateProjectState(payload);
    }

    async function skipRequirementsApprovalStage() {
      if (
        !requirementsApproved &&
        !window.confirm(
          "Requirements have not been explicitly approved.\n\nSkip approval and advance to design anyway?",
        )
      ) {
        return;
      }
      await approveRequirementsStage(true);
    }

    function setRequirementsRunning(isRunning) {
      setAgentRunning("requirements", isRunning);
    }

    async function runStageAgent(
      kind,
      endpoint,
      label,
      clearOutput = false,
      acceptsInput = true,
    ) {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\n", "error");
        return;
      }
      hideStageMenus();
      closeAgentEventStream();
      if (acceptsInput) {
        showProgressPane(false);
      } else {
        showProgressPane(true);
        clearProgressOutput();
      }
      showStageArtifactPreview(kind);
      setAgentInputVisible(acceptsInput);
      if (clearOutput) {
        clearAgentOutput();
      }
      setAgentRunning(kind, true);
      agentInput.disabled = !acceptsInput;
      if (acceptsInput) {
        agentInput.focus();
      }
      appendOutput(`${label}\n`, "system");
      const response = await fetch(contextUrl(endpoint), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "start failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "start failed"}\n`, "error");
        if (!acceptsInput) {
          closeProgressEventStream();
          showProgressPane(false);
          setAgentInputVisible(true);
        }
        if (artifactPreviewStage === kind) {
          hideArtifactPreview();
        }
        setAgentRunning(kind, false);
        return;
      }
      updateProjectState(payload);
      setAgentRunning(kind, true);
      agentInput.disabled = !acceptsInput;
      connectAgentEvents(kind);
      if (!acceptsInput) {
        connectProgressEvents();
      }
      sendTerminalResize();
    }

    function adHocSessionDate(session) {
      const value = String(session.updated_at || session.created_at || "");
      const parsed = new Date(value);
      return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
    }

    function ensureAdHocSessionDialog() {
      if (adHocSessionDialog) {
        return adHocSessionDialog;
      }
      const dialog = document.createElement("dialog");
      dialog.className = "ad-hoc-session-dialog";
      dialog.innerHTML = `
        <form method="dialog" class="ad-hoc-session-form">
          <header class="ad-hoc-session-header">
            <div>
              <h2>Start ad-hoc agent</h2>
              <p>Start fresh or resume a Codex session from this project.</p>
            </div>
            <button
              type="button"
              class="ad-hoc-session-close"
              aria-label="Close"
            >&times;</button>
          </header>
          <fieldset class="ad-hoc-session-options">
            <legend>Session</legend>
            <div class="ad-hoc-session-list"></div>
            <label class="ad-hoc-session-option ad-hoc-session-custom">
              <input type="radio" name="ad-hoc-session" value="custom">
              <span class="ad-hoc-session-option-copy">
                <strong>Resume by UUID</strong>
                <input
                  class="ad-hoc-session-uuid"
                  type="text"
                  autocomplete="off"
                  spellcheck="false"
                  placeholder="00000000-0000-0000-0000-000000000000"
                >
              </span>
            </label>
          </fieldset>
          <p class="ad-hoc-session-error" role="alert" hidden></p>
          <footer class="ad-hoc-session-footer">
            <button type="button" class="ad-hoc-session-cancel">Cancel</button>
            <button type="submit" class="ad-hoc-session-submit">Start</button>
          </footer>
        </form>
      `;
      document.body.append(dialog);
      adHocSessionDialog = dialog;
      return dialog;
    }

    function adHocSessionOption(session, index) {
      const label = document.createElement("label");
      label.className = "ad-hoc-session-option";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "ad-hoc-session";
      input.value = String(session.provider_session_id || "");
      input.id = `ad-hoc-session-${index}`;
      const copy = document.createElement("span");
      copy.className = "ad-hoc-session-option-copy";
      const title = document.createElement("strong");
      title.textContent = String(session.title || "Ad-hoc session");
      const details = document.createElement("span");
      details.className = "ad-hoc-session-details";
      details.textContent = `${adHocSessionDate(session)} · ${input.value}`;
      copy.append(title, details);
      label.append(input, copy);
      return label;
    }

    async function chooseAdHocSession() {
      const response = await fetch(
        contextUrl("/api/agents/ad-hoc/sessions"),
        { cache: "no-store" },
      );
      const payload = await response.json().catch(() => ({
        error: "session history failed",
      }));
      if (!response.ok) {
        throw new Error(payload.error || "session history failed");
      }
      const dialog = ensureAdHocSessionDialog();
      const list = dialog.querySelector(".ad-hoc-session-list");
      const customInput = dialog.querySelector(".ad-hoc-session-uuid");
      const customRadio = dialog.querySelector('input[value="custom"]');
      const error = dialog.querySelector(".ad-hoc-session-error");
      const submit = dialog.querySelector(".ad-hoc-session-submit");
      const newOption = document.createElement("label");
      newOption.className = "ad-hoc-session-option";
      newOption.innerHTML = `
        <input type="radio" name="ad-hoc-session" value="" checked>
        <span class="ad-hoc-session-option-copy">
          <strong>New session</strong>
          <span class="ad-hoc-session-details">
            Start with a clean ad-hoc context.
          </span>
        </span>
      `;
      const sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
      list.replaceChildren(
        newOption,
        ...sessions.map((session, index) => adHocSessionOption(session, index)),
      );
      customInput.value = "";
      error.hidden = true;
      submit.textContent = "Start";
      dialog.querySelector(".ad-hoc-session-options").onchange = (event) => {
        if (event.target.name !== "ad-hoc-session") {
          return;
        }
        submit.textContent = event.target.value ? "Resume" : "Start";
        error.hidden = true;
      };
      customInput.onfocus = () => {
        customRadio.checked = true;
        submit.textContent = "Resume";
      };

      return new Promise((resolve) => {
        const finish = (choice) => {
          dialog.close();
          resolve(choice);
        };
        dialog.querySelector(".ad-hoc-session-close").onclick = () => {
          finish(null);
        };
        dialog.querySelector(".ad-hoc-session-cancel").onclick = () => {
          finish(null);
        };
        dialog.oncancel = (event) => {
          event.preventDefault();
          finish(null);
        };
        dialog.querySelector("form").onsubmit = (event) => {
          event.preventDefault();
          const selected = dialog.querySelector(
            'input[name="ad-hoc-session"]:checked',
          );
          let providerSessionId = selected ? selected.value : "";
          if (providerSessionId === "custom") {
            providerSessionId = customInput.value.trim().toLowerCase();
            const validSessionId = (
              /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/
            ).test(providerSessionId);
            if (!validSessionId) {
              error.textContent = "Enter a valid Codex session UUID.";
              error.hidden = false;
              return;
            }
          }
          finish({ providerSessionId });
        };
        dialog.showModal();
      });
    }

    async function startAdHocAgent() {
      if (!activationRoot) {
        appendOutput("activate a project first\n", "error");
        return;
      }
      let choice = { providerSessionId: "" };
      if (!runtimeApi.getState().adHocRunning) {
        try {
          choice = await chooseAdHocSession();
        } catch (error) {
          appendOutput(`${error.message || "session history failed"}\n`, "error");
          return;
        }
        if (!choice) {
          return;
        }
      }
      hideStageMenus();
      closeAgentEventStream();
      closeProgressEventStream();
      showProgressPane(false);
      setAgentInputVisible(true);
      clearAgentOutput();
      agentInput.disabled = false;
      agentInput.focus();
      appendOutput(
        choice.providerSessionId
          ? `$ codex resume ${choice.providerSessionId}\n`
          : "$ codex ad-hoc\n",
        "system",
      );
      const response = await fetch(contextUrl("/api/agents/ad-hoc/start"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider_session_id: choice.providerSessionId || "",
        }),
      });
      const payload = await response.json().catch(() => ({ error: "start failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "start failed"}\n`, "error");
        return;
      }
      updateProjectState(payload);
      const sessionId = payload.session_id || selectedSessionId;
      selectedSessionId = sessionId;
      runtimeApi.updateState({ selectedSessionId });
      renderSessionSwitcher();
      connectSessionEvents(sessionId);
      sendTerminalResize();
    }

    async function runRequirementsAgent(endpoint, label, clearOutput = false) {
      await runStageAgent("requirements", endpoint, label, clearOutput, true);
    }

    async function startRequirementsAgent() {
      if (currentWorkflowStage !== "requirements") {
        return;
      }
      await runRequirementsAgent(
        "/api/agents/requirements/start",
        "$ electroboy requirements",
      );
    }

    async function completeRequirementsAgent() {
      await approveRequirementsStage(false);
    }

    async function startDesignAgent() {
      if (currentWorkflowStage !== "design") {
        return;
      }
      await runStageAgent(
        "design",
        "/api/agents/design/start",
        "$ electroboy design",
        false,
        true,
      );
    }

    async function completeDesignAgent() {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\n", "error");
        return;
      }
      if (currentWorkflowStage !== "design") {
        return;
      }
      hideStageMenus();
      closeAgentEventStream();
      const response = await fetch(contextUrl("/api/agents/design/complete"), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "complete failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "complete failed"}\n`, "error");
        return;
      }
      setAgentRunning("design", false);
      agentInput.value = "";
      clearAgentOutput();
      updateProjectState(payload);
    }

    async function startAutomaticDesignReviewAgent() {
      if (currentWorkflowStage !== "design-review") {
        return;
      }
      designReviewInteractive = false;
      runtimeApi.updateState({ designReviewInteractive });
      await runStageAgent(
        "design-review",
        "/api/agents/design-review/start",
        "$ electroboy design-review",
        true,
        false,
      );
    }

    async function startInteractiveDesignReviewAgent() {
      if (currentWorkflowStage !== "design-review") {
        return;
      }
      designReviewInteractive = true;
      runtimeApi.updateState({ designReviewInteractive });
      await runStageAgent(
        "design-review",
        "/api/agents/design-review/start-interactive",
        "$ electroboy design-review --interactive",
        true,
        true,
      );
    }

    async function stopDesignReviewAgent() {
      if (currentWorkflowStage !== "design-review" || !designReviewRunning) {
        return;
      }
      hideStageMenus();
      const response = await fetch(contextUrl("/api/agents/design-review/stop"), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "stop failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "stop failed"}\n`, "error");
        return;
      }
      closeAgentEventStream();
      closeProgressEventStream();
      setAgentRunning("design-review", false);
      appendOutput("design review stopped\n", "system");
      updateProjectState(payload);
    }

    async function completeDesignReviewAgent() {
      await approveDesignReviewStage(false);
    }

    async function approveDesignReviewStage(skipApproval = false) {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\n", "error");
        return;
      }
      if (currentWorkflowStage !== "design-review") {
        return;
      }
      hideStageMenus();
      closeAgentEventStream();
      closeProgressEventStream();
      const endpoint = skipApproval
        ? "/api/agents/design-review/skip-approval"
        : "/api/agents/design-review/approve";
      const response = await fetch(contextUrl(endpoint), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "approval failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "approval failed"}\n`, "error");
        if (payload.output) {
          appendOutput(`${payload.output}\n`, "error");
        }
        setAgentRunning("design-review", false);
        refreshProject();
        return;
      }
      setAgentRunning("design-review", false);
      if (payload.output) {
        appendOutput(`${payload.output}\n`, "system");
      }
      if (payload.warning) {
        appendOutput(`${payload.warning}\n`, "system");
      }
      appendOutput(
        skipApproval
          ? "design approval skipped; next: implementation-plan\n"
          : "design approved; next: implementation-plan\n",
        "system",
      );
      updateProjectState(payload);
    }

    async function skipDesignReviewApprovalStage() {
      if (
        !designApproved &&
        !window.confirm(
          "Design has not been explicitly approved.\n\nSkip approval and advance to implementation planning anyway?",
        )
      ) {
        return;
      }
      await approveDesignReviewStage(true);
    }

    async function startGenericStageAgent(stage, label, acceptsInput = true) {
      if (currentWorkflowStage !== stage) {
        return;
      }
      const endpoint = acceptsInput
        ? `/api/agents/${stage}/start-interactive`
        : `/api/agents/${stage}/start`;
      await runStageAgent(stage, endpoint, label, acceptsInput === false, acceptsInput);
    }

    async function stopGenericStageAgent(stage, label) {
      const runState = genericStageRun(stage);
      if (currentWorkflowStage !== stage || !runState.running) {
        return;
      }
      hideStageMenus();
      const response = await fetch(contextUrl(`/api/agents/${stage}/stop`), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "stop failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "stop failed"}\n`, "error");
        return;
      }
      closeAgentEventStream();
      closeProgressEventStream();
      setAgentRunning(stage, false);
      appendOutput(`${label} stopped\n`, "system");
      updateProjectState(payload);
    }

    async function approveGenericStage(stage, label, skipApproval = false) {
      if (!activeProjectRoot) {
        appendOutput("activate a project first\n", "error");
        return;
      }
      if (currentWorkflowStage !== stage) {
        return;
      }
      hideStageMenus();
      closeAgentEventStream();
      closeProgressEventStream();
      const endpoint = skipApproval
        ? `/api/agents/${stage}/skip-approval`
        : `/api/agents/${stage}/approve`;
      const response = await fetch(contextUrl(endpoint), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "approval failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "approval failed"}\n`, "error");
        if (payload.output) {
          appendOutput(`${payload.output}\n`, "error");
        }
        setAgentRunning(stage, false);
        refreshProject();
        return;
      }
      setAgentRunning(stage, false);
      if (payload.output) {
        appendOutput(`${payload.output}\n`, "system");
      }
      if (payload.warning) {
        appendOutput(`${payload.warning}\n`, "system");
      }
      appendOutput(
        skipApproval
          ? `${label} approval skipped\n`
          : `${label} approved\n`,
        "system",
      );
      updateProjectState(payload);
    }

    async function skipGenericStageApproval(stage, label) {
      if (
        !window.confirm(
          `${label} has not been explicitly approved.\n\nSkip approval and advance anyway?`,
        )
      ) {
        return;
      }
      await approveGenericStage(stage, label, true);
    }

  window.ElectroBoyFrontend.registerWorkflow({
    id: "software",
    mode: "software",
    label: "Software engineering",
    order: 10,
    backendPackage: "electroboy.workflows.software",
    navigation: "stages",
    defaultPaneLayout: {
      type: "split",
      direction: "row",
      ratio: 0.72,
      first: { type: "leaf", kind: "agent" },
      second: {
        type: "split",
        direction: "column",
        ratio: 0.62,
        first: { type: "leaf", kind: "scratch" },
        second: { type: "leaf", kind: "status" },
      },
    },
    sidecarStages: ["document", "corkboard"],
    stageDescriptions: STAGE_DESCRIPTIONS,
    artifactPreviews: ARTIFACT_PREVIEWS,
    splashImage: "__SPLASH_IMAGE_ROUTE__",
    recentProjectFilter: (project) => project.kind !== "creative",
    activate(runtime) {
      bindRuntime(runtime);
      restoreSoftwareWorkspace();
    },
    deactivate,
    stageActions,
    actions: {
      restoreSoftwareWorkspace: (runtime, ...args) => invoke(runtime, restoreSoftwareWorkspace, args),
      selectWorkflowStage: (runtime, ...args) => invoke(runtime, selectWorkflowStage, args),
      setWorkflowStageFromMenu: (runtime, ...args) => invoke(runtime, setWorkflowStageFromMenu, args),
      approveRequirementsStage: (runtime, ...args) => invoke(runtime, approveRequirementsStage, args),
      skipRequirementsApprovalStage: (runtime, ...args) => invoke(runtime, skipRequirementsApprovalStage, args),
      setRequirementsRunning: (runtime, ...args) => invoke(runtime, setRequirementsRunning, args),
      runStageAgent: (runtime, ...args) => invoke(runtime, runStageAgent, args),
      startAdHocAgent: (runtime, ...args) => invoke(runtime, startAdHocAgent, args),
      runRequirementsAgent: (runtime, ...args) => invoke(runtime, runRequirementsAgent, args),
      startRequirementsAgent: (runtime, ...args) => invoke(runtime, startRequirementsAgent, args),
      completeRequirementsAgent: (runtime, ...args) => invoke(runtime, completeRequirementsAgent, args),
      startDesignAgent: (runtime, ...args) => invoke(runtime, startDesignAgent, args),
      completeDesignAgent: (runtime, ...args) => invoke(runtime, completeDesignAgent, args),
      startAutomaticDesignReviewAgent: (runtime, ...args) => invoke(runtime, startAutomaticDesignReviewAgent, args),
      startInteractiveDesignReviewAgent: (runtime, ...args) => invoke(runtime, startInteractiveDesignReviewAgent, args),
      stopDesignReviewAgent: (runtime, ...args) => invoke(runtime, stopDesignReviewAgent, args),
      completeDesignReviewAgent: (runtime, ...args) => invoke(runtime, completeDesignReviewAgent, args),
      approveDesignReviewStage: (runtime, ...args) => invoke(runtime, approveDesignReviewStage, args),
      skipDesignReviewApprovalStage: (runtime, ...args) => invoke(runtime, skipDesignReviewApprovalStage, args),
      startGenericStageAgent: (runtime, ...args) => invoke(runtime, startGenericStageAgent, args),
      stopGenericStageAgent: (runtime, ...args) => invoke(runtime, stopGenericStageAgent, args),
      approveGenericStage: (runtime, ...args) => invoke(runtime, approveGenericStage, args),
      skipGenericStageApproval: (runtime, ...args) => invoke(runtime, skipGenericStageApproval, args),
    },
  });
})();
