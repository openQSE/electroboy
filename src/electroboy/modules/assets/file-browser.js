(function () {
  "use strict";

  const PANE_POPUP_FEATURES =
    "popup=yes,width=980,height=720,menubar=no,toolbar=no,location=no,status=no,scrollbars=yes,resizable=yes";
  let runtimeApi = null;

  function bindRuntime(runtime) {
    runtimeApi = runtime;
  }

  function state() {
    return runtimeApi.state;
  }

  function fileBrowserUrl(path, mode = "project", projectAction = "") {
    const current = state();
    const parameters = new URLSearchParams();
    parameters.set(
      "path",
      path || current.activeProjectRoot || current.activationRoot
        || current.serviceRoot || ".",
    );
    parameters.set("mode", mode);
    if (projectAction) {
      parameters.set("project_action", projectAction);
    }
    return `/file-browser?${parameters.toString()}`;
  }

  function openProjectBrowser(mode = state().projectMode, activateSelection = false) {
    const current = state();
    if (current.activationRoot && mode !== "meta-add" && mode !== "meta-start") {
      return;
    }
    if (
      (mode === "meta-add" || mode === "meta-start") &&
      current.activeProjectMode !== "meta"
    ) {
      return;
    }
    current.projectMode = mode;
    current.projectBrowserActivatesSelection = Boolean(activateSelection);
    runtimeApi.ui.hideStageMenus();
    runtimeApi.ui.hideWorkItemPanel();
    runtimeApi.elements.projectPanel.hidden = true;
    const path = runtimeApi.elements.projectPath.value || current.activeProjectRoot
      || current.activationRoot || current.serviceRoot || ".";
    const browserMode = mode === "new" || mode === "meta-new"
      ? "project-new"
      : "project";
    const popup = window.open(
      fileBrowserUrl(path, browserMode, activateSelection ? mode : ""),
      "electroboy-file-browser",
      PANE_POPUP_FEATURES,
    );
    if (!popup) {
      current.projectBrowserActivatesSelection = false;
      runtimeApi.elements.projectStatus.textContent = "popup was blocked by the browser";
      runtimeApi.notifications.appendOutput("popup was blocked by the browser\n", "error");
    }
  }

  function openLinkFileBrowser() {
    const current = state();
    current.projectBrowserActivatesSelection = false;
    const path = current.activeProjectRoot || current.activationRoot
      || current.serviceRoot || runtimeApi.elements.projectPath.value || ".";
    const popup = window.open(
      fileBrowserUrl(path, "link"),
      "electroboy-file-link-browser",
      PANE_POPUP_FEATURES,
    );
    if (!popup) {
      runtimeApi.notifications.appendOutput("popup was blocked by the browser\n", "error");
    }
  }

  function openDocumentFileBrowser() {
    const current = state();
    current.projectBrowserActivatesSelection = false;
    if (!current.activeProjectRoot) {
      runtimeApi.notifications.appendOutput("activate a project first\n", "error");
      return;
    }
    const popup = window.open(
      fileBrowserUrl(current.activeProjectRoot, "document"),
      "electroboy-document-browser",
      PANE_POPUP_FEATURES,
    );
    if (!popup) {
      runtimeApi.notifications.appendOutput("popup was blocked by the browser\n", "error");
    }
  }

  function openNewDocumentFileBrowser() {
    const current = state();
    current.projectBrowserActivatesSelection = false;
    if (!current.activeProjectRoot) {
      runtimeApi.notifications.appendOutput("activate a project first\n", "error");
      return;
    }
    const popup = window.open(
      fileBrowserUrl(current.activeProjectRoot, "document-new"),
      "electroboy-new-document-browser",
      PANE_POPUP_FEATURES,
    );
    if (!popup) {
      runtimeApi.notifications.appendOutput("popup was blocked by the browser\n", "error");
    }
  }

  function handleFileBrowserMessage(data) {
    if (data.type !== "electroboy-file-browser-select" || !data.path) {
      return false;
    }
    const current = state();
    if (data.mode === "link") {
      runtimeApi.ui.insertTextAtCursor(data.path);
      runtimeApi.elements.agentInput.focus();
      return true;
    }
    if (data.mode === "document" || data.mode === "document-new") {
      const target = runtimeApi.modules.invoke(
        "documents",
        "documentTargetFromSelectedPath",
        data.path,
      );
      if (target) {
        runtimeApi.modules.invoke("documents", "openDocumentTarget", target);
      }
      return true;
    }
    if (
      (data.mode === "project" || data.mode === "project-new") &&
      (current.projectBrowserActivatesSelection || data.project_action)
    ) {
      if (data.project_action) {
        current.projectMode = data.project_action;
      }
      current.projectBrowserActivatesSelection = false;
      runtimeApi.ui.applyProjectSelection(data.path).catch((error) => {
        runtimeApi.notifications.appendOutput(
          `project update failed: ${error}\n`,
          "error",
        );
      });
      return true;
    }
    runtimeApi.elements.projectPath.value = data.path;
    runtimeApi.elements.projectStatus.textContent = `selected: ${data.path}`;
    runtimeApi.elements.projectPath.focus();
    return true;
  }

  function invoke(runtime, handler, args) {
    bindRuntime(runtime);
    return handler(...args);
  }

  window.ElectroBoyFrontend.registerModule({
    id: "file-browser",
    label: "File Browser",
    capabilities: ["directory-picker", "file-picker"],
    actions: {
      fileBrowserUrl: (runtime, ...args) => invoke(runtime, fileBrowserUrl, args),
      openProjectBrowser: (runtime, ...args) => invoke(runtime, openProjectBrowser, args),
      openLinkFileBrowser: (runtime, ...args) => invoke(runtime, openLinkFileBrowser, args),
      openDocumentFileBrowser: (runtime, ...args) => invoke(runtime, openDocumentFileBrowser, args),
      openNewDocumentFileBrowser: (runtime, ...args) => invoke(runtime, openNewDocumentFileBrowser, args),
      handleFileBrowserMessage: (runtime, ...args) => invoke(runtime, handleFileBrowserMessage, args),
    },
    mount: bindRuntime,
  });
})();
