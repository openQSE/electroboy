(function () {
  "use strict";

  function stageActions(stageId, runtime) {
    const state = runtime.getState();
    const action = runtime.actions;
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
    return [];
  }

  function projectStageActions(runtime, state) {
    const action = runtime.actions;
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
        label: "Add repo",
        title: "Register another repository with the active meta-project.",
        disabled: state.activeProjectMode !== "meta",
        run: () => action.showProjectPanel("meta-add"),
      },
    ];
    for (const repository of state.registeredRepositories) {
      const label = action.repositoryLabel(repository);
      metaActions.push({
        label: `Start repo: ${label}`,
        title: String(repository.path || label),
        disabled: state.activeProjectMode !== "meta" ||
          label === state.activeRepositoryName,
        run: () => action.startMetaRepository(repository),
      });
    }
    for (const repository of state.registeredRepositories) {
      const label = action.repositoryLabel(repository);
      metaActions.push({
        label: `Remove repo: ${label}`,
        title: String(repository.path || label),
        disabled: state.activeProjectMode !== "meta",
        run: () => action.removeMetaRepository(repository),
      });
    }

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
        label: `Switch feature: ${action.featureLabel(feature)}`,
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
        subgroup: "project-recent",
        label: "Recently opened",
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
    const runState = runtime.actions.genericStageRun(options.stage);
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

    async function startAdHocAgent() {
      if (!activationRoot) {
        appendOutput("activate a project first\n", "error");
        return;
      }
      hideStageMenus();
      closeAgentEventStream();
      closeProgressEventStream();
      showProgressPane(false);
      hideArtifactPreview();
      setAgentInputVisible(true);
      clearAgentOutput();
      agentInput.disabled = false;
      agentInput.focus();
      appendOutput("$ codex ad-hoc\n", "system");
      const response = await fetch(contextUrl("/api/agents/ad-hoc/start"), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "start failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "start failed"}\n`, "error");
        return;
      }
      updateProjectState(payload);
      const sessionId = payload.session_id || selectedSessionId;
      selectedSessionId = sessionId;
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
      designMenu.hidden = true;
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
      designReviewMenu.hidden = true;
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


  function mount(runtime) {
    const element = runtime.elements;
    const action = runtime.actions;
    element.projectStage.addEventListener("click", () => {
      action.showStageActionPanel("project");
    });
    for (const stageNode of element.stageNodes) {
      if (stageNode.dataset.stage === "project") {
        continue;
      }
      stageNode.addEventListener("click", () => {
        action.handleWorkflowStageClick(stageNode).catch((error) => {
          action.appendOutput(`stage update failed: ${error}\n`, "error");
        });
      });
    }
    element.setRequirementsStage.addEventListener(
      "click",
      () => action.setWorkflowStage("requirements"),
    );
    element.startRequirements.addEventListener(
      "click",
      () => action.startRequirementsAgent(),
    );
    element.approveRequirements.addEventListener(
      "click",
      () => action.approveRequirementsStage(),
    );
    element.skipRequirementsApproval.addEventListener(
      "click",
      () => action.skipRequirementsApprovalStage(),
    );
    element.setDesignStage.addEventListener(
      "click",
      () => action.setWorkflowStage("design"),
    );
    element.startDesign.addEventListener("click", () => action.startDesignAgent());
    element.completeDesign.addEventListener("click", () => action.completeDesignAgent());
    element.setDesignReviewStage.addEventListener(
      "click",
      () => action.setWorkflowStage("design-review"),
    );
    element.startAutomaticDesignReview.addEventListener(
      "click",
      () => action.startAutomaticDesignReviewAgent(),
    );
    element.startInteractiveDesignReview.addEventListener(
      "click",
      () => action.startInteractiveDesignReviewAgent(),
    );
    element.stopDesignReview.addEventListener(
      "click",
      () => action.stopDesignReviewAgent(),
    );
    element.approveDesignReview.addEventListener(
      "click",
      () => action.approveDesignReviewStage(),
    );
    element.skipDesignReviewApproval.addEventListener(
      "click",
      () => action.skipDesignReviewApprovalStage(),
    );
    bindGenericStageControls(runtime);
  }

  function bindGenericStageControls(runtime) {
    const element = runtime.elements;
    const action = runtime.actions;
    element.setImplementationPlanStage.addEventListener(
      "click",
      () => action.setWorkflowStage("implementation-plan"),
    );
    element.startImplementationPlan.addEventListener("click", () => {
      action.startGenericStageAgent(
        "implementation-plan",
        "$ electroboy implementation-plan",
        true,
      );
    });
    element.approveImplementationPlan.addEventListener("click", () => {
      action.approveGenericStage("implementation-plan", "implementation plan");
    });
    element.skipImplementationPlanApproval.addEventListener("click", () => {
      action.skipGenericStageApproval("implementation-plan", "Implementation plan");
    });
    element.setCodeStage.addEventListener(
      "click",
      () => action.setWorkflowStage("code"),
    );
    element.startAutomaticCode.addEventListener("click", () => {
      action.startGenericStageAgent("code", "$ electroboy code", false);
    });
    element.startInteractiveCode.addEventListener("click", () => {
      action.startGenericStageAgent("code", "$ electroboy code --interactive", true);
    });
    element.startCodeAdHocAgent.addEventListener(
      "click",
      () => action.startAdHocAgent(),
    );
    element.stopCode.addEventListener(
      "click",
      () => action.stopGenericStageAgent("code", "code"),
    );
    element.approveCode.addEventListener(
      "click",
      () => action.approveGenericStage("code", "code"),
    );
    element.skipCodeApproval.addEventListener(
      "click",
      () => action.skipGenericStageApproval("code", "Code"),
    );
    element.setTestPlanStage.addEventListener(
      "click",
      () => action.setWorkflowStage("test-plan"),
    );
    element.startTestPlan.addEventListener("click", () => {
      action.startGenericStageAgent("test-plan", "$ electroboy test-plan", true);
    });
    element.approveTestPlan.addEventListener(
      "click",
      () => action.approveGenericStage("test-plan", "test plan"),
    );
    element.skipTestPlanApproval.addEventListener(
      "click",
      () => action.skipGenericStageApproval("test-plan", "Test plan"),
    );
    element.setValidateStage.addEventListener(
      "click",
      () => action.setWorkflowStage("validate"),
    );
    element.startAutomaticValidate.addEventListener("click", () => {
      action.startGenericStageAgent("validate", "$ electroboy validate", false);
    });
    element.startInteractiveValidate.addEventListener("click", () => {
      action.startGenericStageAgent(
        "validate",
        "$ electroboy validate --interactive",
        true,
      );
    });
    element.stopValidate.addEventListener(
      "click",
      () => action.stopGenericStageAgent("validate", "validation"),
    );
    element.approveValidate.addEventListener(
      "click",
      () => action.approveGenericStage("validate", "validation"),
    );
    element.skipValidateApproval.addEventListener(
      "click",
      () => action.skipGenericStageApproval("validate", "Validation"),
    );
  }

  window.ElectroBoyFrontend.registerWorkflow({
    id: "software",
    mode: "software",
    label: "Software engineering",
    order: 10,
    backendPackage: "electroboy.workflows.software",
    stageActions,
    actions: {
      restoreSoftwareWorkspace: (_runtime, ...args) => restoreSoftwareWorkspace(...args),
      selectWorkflowStage: (_runtime, ...args) => selectWorkflowStage(...args),
      setWorkflowStageFromMenu: (_runtime, ...args) => setWorkflowStageFromMenu(...args),
      approveRequirementsStage: (_runtime, ...args) => approveRequirementsStage(...args),
      skipRequirementsApprovalStage: (_runtime, ...args) => skipRequirementsApprovalStage(...args),
      setRequirementsRunning: (_runtime, ...args) => setRequirementsRunning(...args),
      runStageAgent: (_runtime, ...args) => runStageAgent(...args),
      startAdHocAgent: (_runtime, ...args) => startAdHocAgent(...args),
      runRequirementsAgent: (_runtime, ...args) => runRequirementsAgent(...args),
      startRequirementsAgent: (_runtime, ...args) => startRequirementsAgent(...args),
      completeRequirementsAgent: (_runtime, ...args) => completeRequirementsAgent(...args),
      startDesignAgent: (_runtime, ...args) => startDesignAgent(...args),
      completeDesignAgent: (_runtime, ...args) => completeDesignAgent(...args),
      startAutomaticDesignReviewAgent: (_runtime, ...args) => startAutomaticDesignReviewAgent(...args),
      startInteractiveDesignReviewAgent: (_runtime, ...args) => startInteractiveDesignReviewAgent(...args),
      stopDesignReviewAgent: (_runtime, ...args) => stopDesignReviewAgent(...args),
      completeDesignReviewAgent: (_runtime, ...args) => completeDesignReviewAgent(...args),
      approveDesignReviewStage: (_runtime, ...args) => approveDesignReviewStage(...args),
      skipDesignReviewApprovalStage: (_runtime, ...args) => skipDesignReviewApprovalStage(...args),
      startGenericStageAgent: (_runtime, ...args) => startGenericStageAgent(...args),
      stopGenericStageAgent: (_runtime, ...args) => stopGenericStageAgent(...args),
      approveGenericStage: (_runtime, ...args) => approveGenericStage(...args),
      skipGenericStageApproval: (_runtime, ...args) => skipGenericStageApproval(...args),
    },
    mount,
  });
})();
