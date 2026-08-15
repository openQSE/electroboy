(function () {
  "use strict";

  function fileBrowserUrl(path, mode = "project", projectAction = "") {
    const parameters = new URLSearchParams();
    parameters.set(
      "path",
      path || activeProjectRoot || activationRoot || serviceRoot || ".",
    );
    parameters.set("mode", mode);
    if (projectAction) {
      parameters.set("project_action", projectAction);
    }
    return `/file-browser?${parameters.toString()}`;
  }

  function openProjectBrowser(mode = projectMode, activateSelection = false) {
    if (activationRoot && mode !== "meta-add" && mode !== "meta-start") {
      return;
    }
    if (
      (mode === "meta-add" || mode === "meta-start") &&
      activeProjectMode !== "meta"
    ) {
      return;
    }
    projectMode = mode;
    projectBrowserActivatesSelection = Boolean(activateSelection);
    hideStageMenus();
    hideWorkItemPanel();
    projectPanel.hidden = true;
    const path = projectPath.value || activeProjectRoot || activationRoot || serviceRoot || ".";
    const browserMode = mode === "new" || mode === "meta-new"
      ? "project-new"
      : "project";
    const popup = window.open(
      fileBrowserUrl(path, browserMode, activateSelection ? mode : ""),
      "electroboy-file-browser",
      PANE_POPUP_FEATURES,
    );
    if (!popup) {
      projectBrowserActivatesSelection = false;
      projectStatus.textContent = "popup was blocked by the browser";
      appendOutput("popup was blocked by the browser\n", "error");
    }
  }

  function openLinkFileBrowser() {
    projectBrowserActivatesSelection = false;
    const path = activeProjectRoot || activationRoot || serviceRoot || projectPath.value || ".";
    const popup = window.open(
      fileBrowserUrl(path, "link"),
      "electroboy-file-link-browser",
      PANE_POPUP_FEATURES,
    );
    if (!popup) {
      appendOutput("popup was blocked by the browser\n", "error");
    }
  }

  function openDocumentFileBrowser() {
    projectBrowserActivatesSelection = false;
    if (!activeProjectRoot) {
      appendOutput("activate a project first\n", "error");
      return;
    }
    const popup = window.open(
      fileBrowserUrl(activeProjectRoot, "document"),
      "electroboy-document-browser",
      PANE_POPUP_FEATURES,
    );
    if (!popup) {
      appendOutput("popup was blocked by the browser\n", "error");
    }
  }

  function openNewDocumentFileBrowser() {
    projectBrowserActivatesSelection = false;
    if (!activeProjectRoot) {
      appendOutput("activate a project first\n", "error");
      return;
    }
    const popup = window.open(
      fileBrowserUrl(activeProjectRoot, "document-new"),
      "electroboy-new-document-browser",
      PANE_POPUP_FEATURES,
    );
    if (!popup) {
      appendOutput("popup was blocked by the browser\n", "error");
    }
  }

  function handleFileBrowserMessage(data) {
    if (data.type !== "electroboy-file-browser-select" || !data.path) {
      return false;
    }
    if (data.mode === "link") {
      insertTextAtCursor(data.path);
      agentInput.focus();
      return true;
    }
    if (data.mode === "document" || data.mode === "document-new") {
      const target = documentTargetFromSelectedPath(data.path);
      if (target) {
        launchDocumentTarget(target);
      }
      return true;
    }
    if (
      (data.mode === "project" || data.mode === "project-new") &&
      (projectBrowserActivatesSelection || data.project_action)
    ) {
      if (data.project_action) {
        projectMode = data.project_action;
      }
      projectBrowserActivatesSelection = false;
      applyProjectSelection(data.path).catch((error) => {
        appendOutput(`project update failed: ${error}\n`, "error");
      });
      return true;
    }
    projectPath.value = data.path;
    projectStatus.textContent = `selected: ${data.path}`;
    projectPath.focus();
    return true;
  }

  window.ElectroBoyFrontend.registerModule({
    id: "file-browser",
    label: "File Browser",
    capabilities: ["directory-picker", "file-picker"],
    actions: {
      fileBrowserUrl: (_runtime, ...args) => fileBrowserUrl(...args),
      openProjectBrowser: (_runtime, ...args) => openProjectBrowser(...args),
      openLinkFileBrowser: (_runtime, ...args) => openLinkFileBrowser(...args),
      openDocumentFileBrowser: (_runtime, ...args) => openDocumentFileBrowser(...args),
      openNewDocumentFileBrowser: (_runtime, ...args) => openNewDocumentFileBrowser(...args),
      handleFileBrowserMessage: (_runtime, ...args) => handleFileBrowserMessage(...args),
    },
  });
})();
