(function () {
  "use strict";

  async function startAgent(runtime) {
    const state = runtime.getState();
    const action = runtime.actions;
    if (!state.activeProjectRoot || !state.contextId) {
      action.appendOutput("activate a project first\n", "error");
      return;
    }
    action.setAgentInputVisible(true);
    action.clearAgentOutput();
    action.appendOutput("$ codex creative-writing\n", "system");
    const response = await fetch(action.contextUrl("/api/creative/agent/start"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        active_document: state.creativeActiveDocument,
        active_target: action.activeCreativeTarget(),
      }),
    });
    const payload = await response
      .json()
      .catch(() => ({ error: "start failed" }));
    if (!response.ok) {
      action.appendOutput(`${payload.error || "start failed"}\n`, "error");
      return;
    }
    action.updateProjectState(payload);
    const sessionId = payload.session_id || runtime.getState().selectedSessionId;
    action.connectSessionEvents(sessionId);
    action.sendTerminalResize();
  }

  function selectFolder(runtime, path) {
    if (!path) {
      return;
    }
    runtime.updateState({
      creativeActiveFolder: path,
      creativeActiveDocument: "",
      creativeLastNotifiedTarget: "",
    });
    runtime.actions.showCreativeCorkboard(path);
    runtime.actions.renderCreativeTree();
    runtime.actions.renderCreativeProjectStatus();
    runtime.actions.notifyCreativeAgentTargetSwitch();
  }

  function selectCorkboard(runtime, path) {
    if (!path) {
      return;
    }
    runtime.updateState({
      creativeActiveDocument: path,
      creativeActiveFolder: runtime.actions.creativeParentPath(path),
      creativeLastNotifiedTarget: "",
    });
    runtime.actions.showCreativeCorkboard(path, { freeform: true });
    runtime.actions.renderCreativeTree();
    runtime.actions.renderCreativeProjectStatus();
    runtime.actions.notifyCreativeAgentTargetSwitch();
  }

  function showDocument(runtime, path) {
    if (!path) {
      return;
    }
    const target = {
      label: runtime.actions.basename(path),
      path,
    };
    runtime.actions.showArtifactPreviews(
      [
        {
          id: "creative-document",
          kind: "document",
          title: target.label,
          target,
          editing: false,
        },
      ],
      { manual: true, stage: "creative-writing" },
    );
  }

  function selectDocument(runtime, path, options = {}) {
    if (!path) {
      return;
    }
    const state = runtime.getState();
    runtime.updateState({
      creativeActiveDocument: path,
      creativeActiveFolder: runtime.actions.creativeParentPath(path),
      creativeLastNotifiedTarget: options.notifyAgent === false
        ? state.creativeLastNotifiedTarget
        : "",
    });
    showDocument(runtime, path);
    runtime.actions.renderCreativeTree();
    runtime.actions.renderCreativeProjectStatus();
    if (options.notifyAgent !== false) {
      runtime.actions.notifyCreativeAgentTargetSwitch();
    }
  }

  function mount(runtime) {
    const element = runtime.elements;
    const action = runtime.actions;
    element.creativeProjectMenuButton.addEventListener("click", () => {
      action.toggleCreativeActionGroup("project");
    });
    element.creativeAgentMenuButton.addEventListener("click", () => {
      action.toggleCreativeActionGroup("agent");
    });
    element.creativeOpenProject.addEventListener("click", () => {
      action.openProjectBrowser("open", true);
    });
    element.creativeNewProject.addEventListener("click", () => {
      action.openProjectBrowser("new", true);
    });
    element.creativeCloseProject.addEventListener(
      "click",
      () => action.deactivateProject(),
    );
    element.creativeStartAgent.addEventListener("click", () => {
      startAgent(runtime);
    });
  }

  window.ElectroBoyFrontend.registerWorkflow({
    id: "creative-writing",
    mode: "creative",
    label: "Creative writing",
    order: 20,
    backendPackage: "electroboy.workflows.creative_writing",
    actions: {
      startAgent,
      selectFolder,
      selectCorkboard,
      showDocument,
      selectDocument,
    },
    mount,
  });
})();
