    const shell = document.querySelector(".shell");
    const connection = document.getElementById("connection");
    const workflowPane = document.querySelector(".workflow-pane");
    const shellResizeHandle = document.getElementById("shellResizeHandle");
    const workflowSideSheet = document.getElementById("workflowSideSheet");
    const toggleWorkflowSideSheet = document.getElementById("toggleWorkflowSideSheet");
    const workflowModeSelect = document.getElementById("workflowModeSelect");
    const stageScroll = document.querySelector(".stage-scroll");
    const stageNodes = Array.from(document.querySelectorAll(".stage-node[data-stage]"));
    const STAGE_DESCRIPTIONS = {
      project: "Open an existing ElectroBoy project or create a new one.",
      requirements: "Author or resume docs/requirements.md with the requirements agent.",
      design: "Author docs/detailed-design.md from the approved requirements.",
      "design-review": "Review the detailed design and capture blocking design issues.",
      "implementation-plan": "Author docs/implementation-plan.md with the implementation phases.",
      code: "Implement and commit the planned code changes.",
      "test-plan": "Author docs/test-plan.md with validation commands and acceptance checks.",
      validate: "Run validation commands and tests, then write the validation report.",
      document: "Update final project documentation after validation passes.",
    };
    const projectStage = document.querySelector("[data-stage='project']");
    const requirementsStage = document.querySelector("[data-stage='requirements']");
    const designStage = document.querySelector("[data-stage='design']");
    const designReviewStage = document.querySelector("[data-stage='design-review']");
    const implementationPlanStage =
      document.querySelector("[data-stage='implementation-plan']");
    const codeStage = document.querySelector("[data-stage='code']");
    const testPlanStage = document.querySelector("[data-stage='test-plan']");
    const validateStage = document.querySelector("[data-stage='validate']");
    const documentStage = document.querySelector("[data-stage='document']");
    const stageActionPanel = document.getElementById("stageActionPanel");
    const stageActionBody = document.getElementById("stageActionBody");
    const creativeBinder = document.getElementById("creativeBinder");
    const creativeProjectMenuButton = document.getElementById("creativeProjectMenuButton");
    const creativeProjectActions = document.getElementById("creativeProjectActions");
    const creativeOpenProject = document.getElementById("creativeOpenProject");
    const creativeNewProject = document.getElementById("creativeNewProject");
    const creativeRecentProjects = document.getElementById("creativeRecentProjects");
    const creativeCloseProject = document.getElementById("creativeCloseProject");
    const creativeActiveProjectSection =
      document.getElementById("creativeActiveProjectSection");
    const creativeProjectName = document.getElementById("creativeProjectName");
    const creativeAgentMenuButton = document.getElementById("creativeAgentMenuButton");
    const creativeAgentActions = document.getElementById("creativeAgentActions");
    const creativeStartAgent = document.getElementById("creativeStartAgent");
    const creativeTree = document.getElementById("creativeTree");
    const projectMenu = document.getElementById("projectMenu");
    const requirementsMenu = document.getElementById("requirementsMenu");
    const designMenu = document.getElementById("designMenu");
    const designReviewMenu = document.getElementById("designReviewMenu");
    const implementationPlanMenu = document.getElementById("implementationPlanMenu");
    const codeMenu = document.getElementById("codeMenu");
    const testPlanMenu = document.getElementById("testPlanMenu");
    const validateMenu = document.getElementById("validateMenu");
    const documentMenu = document.getElementById("documentMenu");
    const openProject = document.getElementById("openProject");
    const newProject = document.getElementById("newProject");
    const metaProjectBranch = document.getElementById("metaProjectBranch");
    const metaProjectMenuButton = document.getElementById("metaProjectMenuButton");
    const metaProjectSubmenu = document.getElementById("metaProjectSubmenu");
    const openMetaProject = document.getElementById("openMetaProject");
    const newMetaProject = document.getElementById("newMetaProject");
    const addMetaRepository = document.getElementById("addMetaRepository");
    const startMetaRepositoryBranch = document.getElementById("startMetaRepositoryBranch");
    const startMetaRepository = document.getElementById("startMetaRepository");
    const startMetaRepositorySubmenu = document.getElementById("startMetaRepositorySubmenu");
    const removeMetaRepositoryBranch = document.getElementById("removeMetaRepositoryBranch");
    const removeMetaRepository = document.getElementById("removeMetaRepository");
    const removeMetaRepositorySubmenu = document.getElementById("removeMetaRepositorySubmenu");
    const workItemBranch = document.getElementById("workItemBranch");
    const workItemMenuButton = document.getElementById("workItemMenuButton");
    const workItemSubmenu = document.getElementById("workItemSubmenu");
    const newFeatureWorkItem = document.getElementById("newFeatureWorkItem");
    const switchFeatureWorkItemBranch = document.getElementById("switchFeatureWorkItemBranch");
    const switchFeatureWorkItem = document.getElementById("switchFeatureWorkItem");
    const switchFeatureWorkItemSubmenu =
      document.getElementById("switchFeatureWorkItemSubmenu");
    const newBugWorkItem = document.getElementById("newBugWorkItem");
    const switchBugWorkItemBranch = document.getElementById("switchBugWorkItemBranch");
    const switchBugWorkItem = document.getElementById("switchBugWorkItem");
    const switchBugWorkItemSubmenu = document.getElementById("switchBugWorkItemSubmenu");
    const deactivateProject = document.getElementById("deactivateProject");
    const setRequirementsStage = document.getElementById("setRequirementsStage");
    const startRequirements = document.getElementById("startRequirements");
    const approveRequirements = document.getElementById("approveRequirements");
    const skipRequirementsApproval = document.getElementById("skipRequirementsApproval");
    const setDesignStage = document.getElementById("setDesignStage");
    const startDesign = document.getElementById("startDesign");
    const completeDesign = document.getElementById("completeDesign");
    const setDesignReviewStage = document.getElementById("setDesignReviewStage");
    const startAutomaticDesignReview = document.getElementById("startAutomaticDesignReview");
    const startInteractiveDesignReview = document.getElementById("startInteractiveDesignReview");
    const stopDesignReview = document.getElementById("stopDesignReview");
    const approveDesignReview = document.getElementById("approveDesignReview");
    const skipDesignReviewApproval = document.getElementById("skipDesignReviewApproval");
    const setImplementationPlanStage = document.getElementById("setImplementationPlanStage");
    const startImplementationPlan = document.getElementById("startImplementationPlan");
    const approveImplementationPlan = document.getElementById("approveImplementationPlan");
    const skipImplementationPlanApproval =
      document.getElementById("skipImplementationPlanApproval");
    const setCodeStage = document.getElementById("setCodeStage");
    const startAutomaticCode = document.getElementById("startAutomaticCode");
    const startInteractiveCode = document.getElementById("startInteractiveCode");
    const startCodeAdHocAgentButton = document.getElementById("startCodeAdHocAgent");
    const stopCode = document.getElementById("stopCode");
    const approveCode = document.getElementById("approveCode");
    const skipCodeApproval = document.getElementById("skipCodeApproval");
    const setTestPlanStage = document.getElementById("setTestPlanStage");
    const startTestPlan = document.getElementById("startTestPlan");
    const approveTestPlan = document.getElementById("approveTestPlan");
    const skipTestPlanApproval = document.getElementById("skipTestPlanApproval");
    const setValidateStage = document.getElementById("setValidateStage");
    const startAutomaticValidate = document.getElementById("startAutomaticValidate");
    const startInteractiveValidate = document.getElementById("startInteractiveValidate");
    const stopValidate = document.getElementById("stopValidate");
    const approveValidate = document.getElementById("approveValidate");
    const skipValidateApproval = document.getElementById("skipValidateApproval");
    const documentTargets = document.getElementById("documentTargets");
    const createDocumentTarget = document.getElementById("createDocumentTarget");
    const customDocumentForm = document.getElementById("customDocumentForm");
    const customDocumentName = document.getElementById("customDocumentName");
    const addDocumentTarget = document.getElementById("addDocumentTarget");
    const projectPanel = document.getElementById("projectPanel");
    const projectPath = document.getElementById("projectPath");
    const browseProject = document.getElementById("browseProject");
    const activateProject = document.getElementById("activateProject");
    const projectStatus = document.getElementById("projectStatus");
    const workItemPanel = document.getElementById("workItemPanel");
    const workItemTitle = document.getElementById("workItemTitle");
    const workItemName = document.getElementById("workItemName");
    const workItemBranchLabel = document.getElementById("workItemBranchLabel");
    const workItemBranchCheckbox = document.getElementById("workItemBranchCheckbox");
    const applyWorkItem = document.getElementById("applyWorkItem");
    const cancelWorkItem = document.getElementById("cancelWorkItem");
    const workItemStatus = document.getElementById("workItemStatus");
    const workItemRecovery = document.getElementById("workItemRecovery");
    const openProjectShell = document.getElementById("openProjectShell");
    const retryWorkItem = document.getElementById("retryWorkItem");
    const fileBrowser = document.getElementById("fileBrowser");
    const browserPath = document.getElementById("browserPath");
    const upDirectory = document.getElementById("upDirectory");
    const selectDirectory = document.getElementById("selectDirectory");
    const closeBrowser = document.getElementById("closeBrowser");
    const directoryList = document.getElementById("directoryList");
    const agentPane = document.getElementById("agentPane");
    const outputWorkbench = document.getElementById("outputWorkbench");
    const workbenchResizeHandle = document.getElementById("workbenchResizeHandle");
    const leftOutputPane = document.querySelector(".left-output-pane");
    const outputSplit = document.getElementById("outputSplit");
    const agentOutputPane = document.getElementById("agentOutputPane");
    const agentOutput = document.getElementById("agentOutput");
    const exportAgentOutput = document.getElementById("exportAgentOutput");
    const outputResizeHandle = document.getElementById("outputResizeHandle");
    const progressOutputPane = document.getElementById("progressOutputPane");
    const progressOutput = document.getElementById("progressOutput");
    const exportProgressOutput = document.getElementById("exportProgressOutput");
    const shellPaneDivider = document.getElementById("shellPaneDivider");
    const projectShellPane = document.getElementById("projectShellPane");
    const projectShellOutput = document.getElementById("projectShellOutput");
    const closeProjectShellPane = document.getElementById("closeProjectShellPane");
    const stopProjectShell = document.getElementById("stopProjectShell");
    const sidePane = document.getElementById("sidePane");
    const sidePaneResizeHandle = document.getElementById("sidePaneResizeHandle");
    const scratchPane = document.querySelector(".scratch-pane");
    const scratchPad = document.getElementById("scratchPad");
    const artifactPreviewPane = document.getElementById("artifactPreviewPane");
    const artifactPaneResizeHandle = document.getElementById("artifactPaneResizeHandle");
    const artifactPreviewStack = document.getElementById("artifactPreviewStack");
    const projectStatusPane = document.querySelector(".project-status-pane");
    const projectStatusOutput = document.getElementById("projectStatusOutput");
    const inputResizeHandle = document.getElementById("inputResizeHandle");
    const inputPane = document.getElementById("inputPane");
    const agentInput = document.getElementById("agentInput");
    const inputActionResizeHandle = document.getElementById("inputActionResizeHandle");
    const sessionSwitcher = document.getElementById("sessionSwitcher");
    const decreaseTerminalFont = document.getElementById("decreaseTerminalFont");
    const terminalFontValue = document.getElementById("terminalFontValue");
    const increaseTerminalFont = document.getElementById("increaseTerminalFont");
    const agentSessionIndicator = document.getElementById("agentSessionIndicator");
    const toggleProjectShellPane = document.getElementById("toggleProjectShellPane");
    const showSplashButton = document.getElementById("showSplash");
    const interruptAgent = document.getElementById("interruptAgent");
    const insertFileLink = document.getElementById("insertFileLink");
    const popoutAgentPane = document.getElementById("popoutAgentPane");
    const popoutProgressPane = document.getElementById("popoutProgressPane");
    const popoutProjectShellPane = document.getElementById("popoutProjectShellPane");
    const popoutScratchPane = document.getElementById("popoutScratchPane");
    const popoutStatusPane = document.getElementById("popoutStatusPane");
    const popoutInputPane = document.getElementById("popoutInputPane");
    const splashOverlay = document.getElementById("splashOverlay");
    const splashImage = document.getElementById("splashImage");
    const closeSplash = document.getElementById("closeSplash");
    const CONTEXT_STORAGE_KEY = "electroboy.contextId";
    const CONTEXT_TAB_STORAGE_KEY = "electroboy.contextTabId";
    const CONTEXT_OWNER_STORAGE_PREFIX = "electroboy.contextOwner.";
    const SPLASH_DISMISSED_STORAGE_KEY = "electroboy.splash.dismissed.v1";
    const SOFTWARE_SPLASH_IMAGE_ROUTE = "__SPLASH_IMAGE_ROUTE__";
    const CREATIVE_SPLASH_IMAGE_ROUTE = "__CREATIVE_SPLASH_IMAGE_ROUTE__";
    const CONTEXT_OWNER_TTL_MS = 15000;
    const CONTEXT_OWNER_HEARTBEAT_MS = 5000;
    const WORKFLOW_SIDE_SHEET_STORAGE_KEY = "electroboy.workflowSideSheetCollapsed";
    const WORKFLOW_MODE_STORAGE_KEY = "electroboy.workflowMode";
    const TERMINAL_FONT_STORAGE_KEY = "electroboy.terminalFontSize";
    const PANE_FONT_OFFSET_STORAGE_PREFIX = "electroboy.paneFontOffset.";
    const DOCUMENT_ZOOM_STORAGE_KEY = "electroboy.documentZoom";
    const WORKFLOW_PANE_HEIGHT_STORAGE_KEY = "electroboy.workflowPaneHeight";
    const WORKFLOW_PANE_HEIGHT_STORAGE_VERSION_KEY =
      "electroboy.workflowPaneHeightVersion";
    const WORKFLOW_PANE_HEIGHT_STORAGE_VERSION = "compact-v2";
    const DEFAULT_WORKFLOW_PANE_HEIGHT = 86;
    const MIN_WORKFLOW_PANE_HEIGHT = 86;
    const INPUT_PANE_HEIGHT_STORAGE_KEY = "electroboy.inputPaneHeight";
    const INPUT_ACTIONS_WIDTH_STORAGE_KEY = "electroboy.inputActionsWidth";
    const PROGRESS_PANE_WIDTH_STORAGE_KEY = "electroboy.progressPaneWidth";
    const PROGRESS_PANE_HEIGHT_STORAGE_KEY = "electroboy.progressPaneHeight";
    const PROJECT_SHELL_PANE_HEIGHT_STORAGE_KEY =
      "electroboy.projectShellPaneHeight";
    const RIGHT_PANE_WIDTH_STORAGE_KEY = "electroboy.rightPaneWidth";
    const CREATIVE_RIGHT_PANE_WIDTH_STORAGE_KEY =
      "electroboy.creativeRightPaneWidth";
    const RIGHT_PANE_HEIGHT_STORAGE_KEY = "electroboy.rightPaneHeight";
    const SCRATCH_PANE_HEIGHT_STORAGE_KEY = "electroboy.scratchPaneHeight";
    const ARTIFACT_PANE_WIDTH_STORAGE_KEY = "electroboy.artifactPaneWidth";
    const ARTIFACT_PANE_HEIGHT_STORAGE_KEY = "electroboy.artifactPaneHeight";
    const PANE_LAYOUT_STORAGE_KEY = "electroboy.paneLayout.v1";
    const SCRATCH_PAD_STORAGE_KEY = "electroboy.scratchPad";
    const DOCUMENT_TARGETS_STORAGE_KEY = "electroboy.documentTargets";
    const CREATIVE_WORKFLOW_MODE = "creative";
    const SOFTWARE_WORKFLOW_MODE = "software";
    const PANE_POPUP_FEATURES =
      "popup=yes,width=980,height=720,menubar=no,toolbar=no,location=no,status=no,scrollbars=yes,resizable=yes";
    const DEFAULT_DOCUMENT_TARGETS = [
      { label: "README", path: "README.md" },
      { label: "API", path: "docs/api.md" },
    ];
    const STAGE_ARTIFACT_PREVIEWS = {
      requirements: [
        { id: "requirements", kind: "requirements", title: "Requirements" },
      ],
      design: [
        {
          id: "design",
          kind: "route",
          title: "Detailed Design",
          path: "/artifacts/design",
        },
      ],
      "design-review": [
        {
          id: "design",
          kind: "route",
          title: "Detailed Design",
          path: "/artifacts/design",
        },
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
        {
          id: "test-plan",
          kind: "route",
          title: "Test Plan",
          path: "/artifacts/test-plan",
        },
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
    const DEFAULT_TERMINAL_FONT_SIZE = 15;
    const MIN_TERMINAL_FONT_SIZE = 11;
    const MAX_TERMINAL_FONT_SIZE = 24;
    const MIN_PANE_FONT_OFFSET = -6;
    const MAX_PANE_FONT_OFFSET = 6;
    const PANE_FONT_KEYS = ["agent", "progress", "shell", "input", "scratch", "status"];
    const PANE_FONT_CSS_PROPERTIES = {
      agent: "--agent-output-font-size",
      progress: "--progress-output-font-size",
      shell: "--project-shell-font-size",
      input: "--agent-input-font-size",
      scratch: "--scratch-pad-font-size",
      status: "--project-status-font-size",
    };
    const DEFAULT_DOCUMENT_ZOOM = 100;
    const DOCUMENT_ZOOM_STEP = 10;
    const MIN_DOCUMENT_ZOOM = 70;
    const MAX_DOCUMENT_ZOOM = 180;
    const MIN_INPUT_PANE_HEIGHT = 56;
    const MIN_INPUT_ACTIONS_WIDTH = 160;
    const MIN_AGENT_INPUT_WIDTH = 260;
    let eventSource = null;
    let progressEventSource = null;
    let projectShellEventSource = null;
    let artifactEventSources = [];
    let terminal = null;
    let terminalFit = null;
    let progressTerminal = null;
    let progressTerminalFit = null;
    let projectShellTerminal = null;
    let projectShellTerminalFit = null;
    let terminalFontSize = storedTerminalFontSize();
    let paneFontOffsets = storedPaneFontOffsets();
    let documentZoom = storedDocumentZoom();
    let serviceSessions = [];
    let resizeShellState = null;
    let resizeInputState = null;
    let resizeInputActionsState = null;
    let resizeOutputState = null;
    let resizeWorkbenchState = null;
    let resizeSidePaneState = null;
    let resizeArtifactPaneState = null;
    let resizeProjectShellState = null;
    let paneLayout = null;
    let paneLayoutObserver = null;
    let paneLayoutIdSequence = 0;
    let paneCornerSplitCancel = null;
    let terminalResizeObserver = null;
    let resizeTimer = null;
    let pendingTerminalResize = null;
    let shellResizeTimer = null;
    let statusRefreshTimer = null;
    let statusRefreshSequence = 0;
    let workflowSideSheetCollapsed = storedWorkflowSideSheetCollapsed();
    let workflowMode = storedWorkflowMode();
    let artifactPreviewKind = "";
    let artifactPreviewDocumentTarget = null;
    let artifactPreviewItems = [];
    let openDocumentTargets = [];
    let manualArtifactPreview = false;
    let manualArtifactPreviewStage = "";
    let artifactPreviewStage = "";
    let artifactPreviewVersion = 0;
    let artifactSaveTokenSequence = 0;
    let progressPaneRequested = false;
    let artifactPaneRequested = false;
    let projectShellPaneRequested = false;
    let projectShellPaneDismissed = false;
    let inputPaneRequested = true;
    let projectShellRunning = false;
    const poppedPanes = new Set();
    const poppedPaneWindows = new Map();
    const pendingArtifactSaves = new Map();
    let slashCommandMode = false;
    let terminalInputQueue = Promise.resolve();
    let activeAgentKind = "";
    let requirementsRunning = false;
    let requirementsApproved = false;
    let designRunning = false;
    let designReviewRunning = false;
    let designReviewInteractive = false;
    let designApproved = false;
    let documentationRunning = false;
    let adHocRunning = false;
    let currentWorkflowStage = "project";
    let agentSessions = [];
    let selectedSessionId = "";
    let contextId = "";
    const pageInstanceId = newContextOwnerId();
    let browserTabId = "";
    let ownedContextId = "";
    let contextOwnerTimer = null;
    let projectMode = "open";
    let projectBrowserActivatesSelection = false;
    let serviceRoot = "";
    let activationRoot = "";
    let activeProjectMode = "none";
    let activeProjectRoot = "";
    let activeRepositoryName = "";
    let registeredRepositories = [];
    let recentProjects = [];
    let workItemState = { collections: [], features: [], bugs: [] };
    let stageRunState = {};
    let workItemMode = "";
    let customDocumentTargets = storedDocumentTargets();
    let currentBrowsePath = "";
    let currentBrowseParent = "";
    let currentBrowserMode = "project";
    let currentSelectedFile = "";
    let expandedWorkflowStages = new Set();
    let expandedProjectActionGroups = new Set();
    let restoredScratchContextId = "";
    let creativeTreePayload = null;
    let creativeActiveDocument = "";
    let creativeActiveFolder = "";
    let creativeEditingPath = "";
    let creativeEditingType = "";
    let expandedCreativeFolders = new Set();
    let creativeScratchSaveTimer = null;
    let creativeLastNotifiedTarget = "";
    let creativeProjectActionsExpanded = false;
    let creativeAgentActionsExpanded = false;
    let projectStatusMessages = [];
    const PROJECT_STATUS_MESSAGE_LIMIT = 80;
    const CREATIVE_CORKBOARD_SUFFIX = ".corkboard.json";

    const PANE_LAYOUT_KINDS = {
      agent: { label: "Agent", element: agentOutputPane },
      progress: { label: "Progress", element: progressOutputPane },
      artifact: { label: "Artifact", element: artifactPreviewPane },
      shell: { label: "Shell", element: projectShellPane },
      scratch: { label: "Scratch", element: scratchPane },
      status: { label: "Status", element: projectStatusPane },
    };

    function newPaneLayoutId(prefix = "pane") {
      paneLayoutIdSequence += 1;
      return `${prefix}-${Date.now()}-${paneLayoutIdSequence}`;
    }

    function paneLayoutLeaf(kind = "empty") {
      return { type: "leaf", id: newPaneLayoutId(), kind };
    }

    function paneLayoutSplit(direction, first, second, ratio = 0.5) {
      return {
        type: "split",
        id: newPaneLayoutId("split"),
        direction,
        ratio,
        first,
        second,
      };
    }

    function defaultPaneLayout() {
      return paneLayoutSplit(
        "row",
        paneLayoutLeaf("agent"),
        paneLayoutSplit(
          "column",
          paneLayoutLeaf("scratch"),
          paneLayoutLeaf("status"),
          0.62,
        ),
        0.72,
      );
    }

    function normalizePaneLayoutNode(value, seenKinds) {
      if (!value || typeof value !== "object") {
        return null;
      }
      if (value.type === "leaf") {
        const requestedKind = String(value.kind || "empty");
        const validKind = requestedKind === "empty" || PANE_LAYOUT_KINDS[requestedKind];
        const kind = validKind && !seenKinds.has(requestedKind) ? requestedKind : "empty";
        if (kind !== "empty") {
          seenKinds.add(kind);
        }
        return paneLayoutLeaf(kind);
      }
      if (value.type !== "split") {
        return null;
      }
      const first = normalizePaneLayoutNode(value.first, seenKinds);
      const second = normalizePaneLayoutNode(value.second, seenKinds);
      if (!first || !second) {
        return null;
      }
      const ratio = Number(value.ratio);
      return paneLayoutSplit(
        value.direction === "column" ? "column" : "row",
        first,
        second,
        Number.isFinite(ratio) ? clampValue(ratio, 0.12, 0.88) : 0.5,
      );
    }

    function storedPaneLayout() {
      try {
        const stored = JSON.parse(window.localStorage.getItem(PANE_LAYOUT_STORAGE_KEY));
        return normalizePaneLayoutNode(stored, new Set()) || defaultPaneLayout();
      } catch (error) {
        return defaultPaneLayout();
      }
    }

    function savePaneLayout() {
      try {
        window.localStorage.setItem(PANE_LAYOUT_STORAGE_KEY, JSON.stringify(paneLayout));
      } catch (error) {
        return;
      }
    }

    function paneLayoutLeaves(node = paneLayout, leaves = []) {
      if (!node) {
        return leaves;
      }
      if (node.type === "leaf") {
        leaves.push(node);
        return leaves;
      }
      paneLayoutLeaves(node.first, leaves);
      paneLayoutLeaves(node.second, leaves);
      return leaves;
    }

    function paneLayoutLeafById(id) {
      return paneLayoutLeaves().find((leaf) => leaf.id === id) || null;
    }

    function paneLayoutLeafByKind(kind) {
      return paneLayoutLeaves().find((leaf) => leaf.kind === kind) || null;
    }

    function replacePaneLayoutNode(node, id, replacement) {
      if (node.id === id) {
        return replacement;
      }
      if (node.type === "leaf") {
        return node;
      }
      node.first = replacePaneLayoutNode(node.first, id, replacement);
      node.second = replacePaneLayoutNode(node.second, id, replacement);
      return node;
    }

    function removePaneLayoutLeaf(node, id) {
      if (node.type === "leaf") {
        return node.id === id ? null : node;
      }
      if (node.first.id === id) {
        return node.second;
      }
      if (node.second.id === id) {
        return node.first;
      }
      const first = removePaneLayoutLeaf(node.first, id);
      const second = removePaneLayoutLeaf(node.second, id);
      if (!first) {
        return second;
      }
      if (!second) {
        return first;
      }
      node.first = first;
      node.second = second;
      return node;
    }

    function paneLayoutKindAvailable(kind) {
      if (kind !== "artifact") {
        return true;
      }
      return artifactPreviewItems.length > 0 || Boolean(paneLayoutLeafByKind("artifact"));
    }

    function buildPaneLayoutToolbar(leaf) {
      const toolbar = document.createElement("div");
      toolbar.className = "pane-layout-toolbar";

      const select = document.createElement("select");
      select.className = "pane-layout-kind";
      select.title = "Choose pane type";
      select.setAttribute("aria-label", "Choose pane type");
      const emptyOption = document.createElement("option");
      emptyOption.value = "empty";
      emptyOption.textContent = "Choose pane";
      select.append(emptyOption);
      for (const [kind, definition] of Object.entries(PANE_LAYOUT_KINDS)) {
        const option = document.createElement("option");
        option.value = kind;
        option.textContent = definition.label;
        option.disabled = !paneLayoutKindAvailable(kind);
        select.append(option);
      }
      select.value = leaf.kind;
      select.addEventListener("change", () => {
        changePaneLayoutKind(leaf.id, select.value);
      });

      const splitRight = document.createElement("button");
      splitRight.className = "pane-layout-command split-right";
      splitRight.type = "button";
      splitRight.title = "Split pane right";
      splitRight.setAttribute("aria-label", "Split pane right");
      splitRight.addEventListener("click", () => splitPaneLayoutLeaf(leaf.id, "row"));

      const splitDown = document.createElement("button");
      splitDown.className = "pane-layout-command split-down";
      splitDown.type = "button";
      splitDown.title = "Split pane down";
      splitDown.setAttribute("aria-label", "Split pane down");
      splitDown.addEventListener("click", () => splitPaneLayoutLeaf(leaf.id, "column"));

      const close = document.createElement("button");
      close.className = "pane-layout-command close-pane";
      close.type = "button";
      close.title = "Close pane and join area";
      close.setAttribute("aria-label", "Close pane and join area");
      close.textContent = "×";
      close.disabled = paneLayoutLeaves().length <= 1;
      close.addEventListener("click", () => closePaneLayoutLeaf(leaf.id));

      const reset = document.createElement("button");
      reset.className = "pane-layout-command reset-layout";
      reset.type = "button";
      reset.title = "Reset pane layout";
      reset.setAttribute("aria-label", "Reset pane layout");
      reset.textContent = "↺";
      reset.addEventListener("click", resetPaneLayout);

      toolbar.append(select, splitRight, splitDown, close, reset);
      return toolbar;
    }

    function applyPaneLayoutSplitTemplate(element, node) {
      const ratio = clampValue(Number(node.ratio) || 0.5, 0.12, 0.88);
      if (node.direction === "column") {
        element.style.gridTemplateColumns = "minmax(0, 1fr)";
        element.style.gridTemplateRows =
          `minmax(0, ${ratio}fr) 7px minmax(0, ${1 - ratio}fr)`;
      } else {
        element.style.gridTemplateRows = "minmax(0, 1fr)";
        element.style.gridTemplateColumns =
          `minmax(0, ${ratio}fr) 7px minmax(0, ${1 - ratio}fr)`;
      }
    }

    function startPaneLayoutResize(event, node, splitElement, divider) {
      event.preventDefault();
      const pointerId = event.pointerId;
      divider.setPointerCapture(pointerId);
      divider.classList.add("resizing");
      const update = (moveEvent) => {
        const rect = splitElement.getBoundingClientRect();
        const available = node.direction === "column" ? rect.height - 7 : rect.width - 7;
        if (available <= 0) {
          return;
        }
        const position = node.direction === "column"
          ? moveEvent.clientY - rect.top - 3.5
          : moveEvent.clientX - rect.left - 3.5;
        node.ratio = clampValue(position / available, 0.12, 0.88);
        applyPaneLayoutSplitTemplate(splitElement, node);
        fitTerminal();
      };
      const finish = () => {
        divider.classList.remove("resizing");
        divider.removeEventListener("pointermove", update);
        divider.removeEventListener("pointerup", finish);
        divider.removeEventListener("pointercancel", finish);
        try {
          divider.releasePointerCapture(pointerId);
        } catch (error) {
          // Pointer capture may already be released by the browser.
        }
        savePaneLayout();
        fitTerminal();
      };
      divider.addEventListener("pointermove", update);
      divider.addEventListener("pointerup", finish);
      divider.addEventListener("pointercancel", finish);
    }

    function paneCornerSplitCandidate(event, state) {
      const topRight = state.corner === "top-right";
      const inwardX = topRight
        ? state.startX - event.clientX
        : event.clientX - state.startX;
      const inwardY = topRight
        ? event.clientY - state.startY
        : state.startY - event.clientY;
      if (Math.max(inwardX, inwardY) < 12) {
        return null;
      }
      const row = inwardX >= inwardY;
      const ratio = row
        ? (event.clientX - state.rect.left) / state.rect.width
        : (event.clientY - state.rect.top) / state.rect.height;
      return {
        direction: row ? "row" : "column",
        emptyFirst: row ? !topRight : topRight,
        ratio: clampValue(ratio, 0.12, 0.88),
      };
    }

    function showPaneCornerSplitPreview(preview, candidate) {
      preview.hidden = !candidate;
      if (!candidate) {
        return;
      }
      const ratioPercent = candidate.ratio * 100;
      preview.style.top = "0";
      preview.style.right = "auto";
      preview.style.bottom = "auto";
      preview.style.left = "0";
      preview.style.width = "100%";
      preview.style.height = "100%";
      if (candidate.direction === "row") {
        preview.style.width = candidate.emptyFirst
          ? `${ratioPercent}%`
          : `${100 - ratioPercent}%`;
        preview.style.left = candidate.emptyFirst ? "0" : `${ratioPercent}%`;
      } else {
        preview.style.height = candidate.emptyFirst
          ? `${ratioPercent}%`
          : `${100 - ratioPercent}%`;
        preview.style.top = candidate.emptyFirst ? "0" : `${ratioPercent}%`;
      }
    }

    function startPaneCornerSplit(event, leaf, leafElement, corner, preview) {
      if (event.button !== 0) {
        return;
      }
      if (paneCornerSplitCancel) {
        paneCornerSplitCancel();
      }
      event.preventDefault();
      event.stopPropagation();
      const state = {
        corner,
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        rect: leafElement.getBoundingClientRect(),
        candidate: null,
        finished: false,
      };
      event.currentTarget.setPointerCapture(event.pointerId);
      const handle = event.currentTarget;
      leafElement.classList.add("splitting");
      document.body.classList.add("pane-layout-splitting");

      const update = (moveEvent) => {
        state.candidate = paneCornerSplitCandidate(moveEvent, state);
        showPaneCornerSplitPreview(preview, state.candidate);
        document.body.classList.toggle(
          "pane-layout-splitting-row",
          state.candidate?.direction === "row",
        );
        document.body.classList.toggle(
          "pane-layout-splitting-column",
          state.candidate?.direction === "column",
        );
      };
      const finish = (commit) => {
        if (state.finished) {
          return;
        }
        state.finished = true;
        paneCornerSplitCancel = null;
        handle.removeEventListener("pointermove", update);
        handle.removeEventListener("pointerup", pointerUp);
        handle.removeEventListener("pointercancel", pointerCancel);
        window.removeEventListener("keydown", keyDown);
        leafElement.classList.remove("splitting");
        document.body.classList.remove(
          "pane-layout-splitting",
          "pane-layout-splitting-row",
          "pane-layout-splitting-column",
        );
        showPaneCornerSplitPreview(preview, null);
        try {
          handle.releasePointerCapture(state.pointerId);
        } catch (error) {
          // Pointer capture may already be released by the browser.
        }
        if (commit && state.candidate) {
          splitPaneLayoutLeaf(
            leaf.id,
            state.candidate.direction,
            state.candidate.ratio,
            state.candidate.emptyFirst,
          );
        }
      };
      const pointerUp = () => finish(true);
      const pointerCancel = () => finish(false);
      const keyDown = (keyEvent) => {
        if (keyEvent.key === "Escape") {
          keyEvent.preventDefault();
          finish(false);
        }
      };
      paneCornerSplitCancel = () => finish(false);
      handle.addEventListener("pointermove", update);
      handle.addEventListener("pointerup", pointerUp);
      handle.addEventListener("pointercancel", pointerCancel);
      window.addEventListener("keydown", keyDown);
    }

    function buildPaneLayoutCorner(leaf, leafElement, corner, preview) {
      const handle = document.createElement("div");
      handle.className = `pane-layout-corner ${corner}`;
      handle.title = "Drag inward to split pane";
      handle.setAttribute("aria-hidden", "true");
      handle.addEventListener("pointerdown", (event) => {
        startPaneCornerSplit(event, leaf, leafElement, corner, preview);
      });
      return handle;
    }

    function renderPaneLayoutNode(node) {
      if (node.type === "leaf") {
        const leaf = document.createElement("div");
        leaf.className = "pane-layout-leaf";
        leaf.dataset.paneLayoutId = node.id;
        leaf.dataset.paneKind = node.kind;
        leaf.append(buildPaneLayoutToolbar(node));
        if (node.kind === "empty") {
          const empty = document.createElement("div");
          empty.className = "pane-layout-empty";
          empty.textContent = "Choose a pane type";
          leaf.append(empty);
        } else {
          leaf.append(PANE_LAYOUT_KINDS[node.kind].element);
        }
        const preview = document.createElement("div");
        preview.className = "pane-layout-split-preview";
        preview.hidden = true;
        preview.setAttribute("aria-hidden", "true");
        leaf.append(
          preview,
          buildPaneLayoutCorner(node, leaf, "top-right", preview),
          buildPaneLayoutCorner(node, leaf, "bottom-left", preview),
        );
        return leaf;
      }

      const split = document.createElement("div");
      split.className = `pane-layout-split ${node.direction}`;
      split.dataset.paneLayoutId = node.id;
      const first = renderPaneLayoutNode(node.first);
      const divider = document.createElement("div");
      divider.className = `pane-layout-divider ${node.direction}`;
      divider.setAttribute("role", "separator");
      divider.setAttribute(
        "aria-orientation",
        node.direction === "column" ? "horizontal" : "vertical",
      );
      divider.setAttribute("aria-label", "Resize split panes");
      divider.addEventListener("pointerdown", (event) => {
        startPaneLayoutResize(event, node, split, divider);
      });
      const second = renderPaneLayoutNode(node.second);
      split.append(first, divider, second);
      applyPaneLayoutSplitTemplate(split, node);
      return split;
    }

    function refreshPaneLayoutVisibility(node = paneLayout, element = outputWorkbench.firstElementChild) {
      if (!node || !element) {
        return false;
      }
      if (node.type === "leaf") {
        const visible = node.kind === "empty" || !PANE_LAYOUT_KINDS[node.kind].element.hidden;
        element.hidden = !visible;
        return visible;
      }
      const firstElement = element.children[0];
      const divider = element.children[1];
      const secondElement = element.children[2];
      const firstVisible = refreshPaneLayoutVisibility(node.first, firstElement);
      const secondVisible = refreshPaneLayoutVisibility(node.second, secondElement);
      element.hidden = !firstVisible && !secondVisible;
      divider.hidden = !firstVisible || !secondVisible;
      if (firstVisible && secondVisible) {
        applyPaneLayoutSplitTemplate(element, node);
      } else if (node.direction === "column") {
        element.style.gridTemplateColumns = "minmax(0, 1fr)";
        element.style.gridTemplateRows = "minmax(0, 1fr)";
      } else {
        element.style.gridTemplateRows = "minmax(0, 1fr)";
        element.style.gridTemplateColumns = "minmax(0, 1fr)";
      }
      return firstVisible || secondVisible;
    }

    function renderPaneLayout() {
      if (paneCornerSplitCancel) {
        paneCornerSplitCancel();
      }
      const root = renderPaneLayoutNode(paneLayout);
      root.classList.add("pane-layout-root");
      outputWorkbench.replaceChildren(root);
      refreshPaneLayoutVisibility();
      window.requestAnimationFrame(fitTerminal);
    }

    function splitPaneLayoutLeaf(id, direction, ratio = 0.5, emptyFirst = false) {
      const leaf = paneLayoutLeafById(id);
      if (!leaf) {
        return;
      }
      const existingLeaf = paneLayoutLeaf(leaf.kind);
      const emptyLeaf = paneLayoutLeaf();
      const replacement = paneLayoutSplit(
        direction,
        emptyFirst ? emptyLeaf : existingLeaf,
        emptyFirst ? existingLeaf : emptyLeaf,
        ratio,
      );
      paneLayout = replacePaneLayoutNode(paneLayout, id, replacement);
      savePaneLayout();
      renderPaneLayout();
    }

    function changePaneLayoutKind(id, kind) {
      const leaf = paneLayoutLeafById(id);
      if (!leaf || (kind !== "empty" && !PANE_LAYOUT_KINDS[kind])) {
        return;
      }
      const previousKind = leaf.kind;
      const existing = kind === "empty" ? null : paneLayoutLeafByKind(kind);
      if (existing && existing !== leaf) {
        existing.kind = previousKind;
      }
      leaf.kind = kind;
      savePaneLayout();
      renderPaneLayout();
      activatePaneLayoutKind(kind);
      if (previousKind !== kind && !paneLayoutLeafByKind(previousKind)) {
        deactivatePaneLayoutKind(previousKind);
      }
    }

    function closePaneLayoutLeaf(id) {
      if (paneLayoutLeaves().length <= 1) {
        return;
      }
      const leaf = paneLayoutLeafById(id);
      if (!leaf) {
        return;
      }
      const removedKind = leaf.kind;
      paneLayout = removePaneLayoutLeaf(paneLayout, id);
      savePaneLayout();
      renderPaneLayout();
      if (!paneLayoutLeafByKind(removedKind)) {
        deactivatePaneLayoutKind(removedKind);
      }
    }

    function activatePaneLayoutKind(kind) {
      if (poppedPanes.has(kind)) {
        dockPoppedPane(kind);
      }
      if (kind === "progress") {
        showProgressPane(true);
      } else if (kind === "artifact") {
        artifactPaneRequested = true;
        applyOutputPaneVisibility();
      } else if (kind === "shell") {
        showProjectShellPane(true);
      }
    }

    function deactivatePaneLayoutKind(kind) {
      if (kind === "progress") {
        showProgressPane(false);
      } else if (kind === "artifact") {
        artifactPaneRequested = false;
        applyOutputPaneVisibility();
      } else if (kind === "shell") {
        hideProjectShellPane();
      }
    }

    function ensurePaneInLayout(kind, targetKind = "agent", direction = "row") {
      if (!paneLayout || paneLayoutLeafByKind(kind)) {
        return;
      }
      const target = paneLayoutLeafByKind(targetKind) || paneLayoutLeaves()[0];
      if (!target) {
        paneLayout = paneLayoutLeaf(kind);
      } else {
        const replacement = paneLayoutSplit(
          direction,
          paneLayoutLeaf(target.kind),
          paneLayoutLeaf(kind),
        );
        paneLayout = replacePaneLayoutNode(paneLayout, target.id, replacement);
      }
      savePaneLayout();
      renderPaneLayout();
    }

    function resetPaneLayout() {
      paneLayout = defaultPaneLayout();
      savePaneLayout();
      renderPaneLayout();
      if (progressPaneRequested) {
        ensurePaneInLayout("progress", "agent", "row");
      }
      if (artifactPaneRequested && artifactPreviewItems.length > 0) {
        ensurePaneInLayout("artifact", "agent", "row");
      }
      if (projectShellPaneRequested) {
        ensurePaneInLayout("shell", "agent", "column");
      }
    }

    function initializePaneLayout() {
      paneLayout = storedPaneLayout();
      outputWorkbench.classList.add("pane-layout-enabled");
      renderPaneLayout();
      paneLayoutObserver = new MutationObserver(() => refreshPaneLayoutVisibility());
      for (const definition of Object.values(PANE_LAYOUT_KINDS)) {
        paneLayoutObserver.observe(definition.element, {
          attributes: true,
          attributeFilter: ["hidden"],
        });
      }
    }

    function storedTerminalFontSize() {
      try {
        const stored = Number(window.localStorage.getItem(TERMINAL_FONT_STORAGE_KEY));
        if (Number.isFinite(stored)) {
          return clampTerminalFontSize(stored);
        }
      } catch (error) {
        return DEFAULT_TERMINAL_FONT_SIZE;
      }
      return DEFAULT_TERMINAL_FONT_SIZE;
    }

    function saveTerminalFontSize() {
      try {
        window.localStorage.setItem(
          TERMINAL_FONT_STORAGE_KEY,
          String(terminalFontSize),
        );
      } catch (error) {
        return;
      }
    }

    function storedPaneFontOffsets() {
      const offsets = {};
      for (const pane of PANE_FONT_KEYS) {
        offsets[pane] = storedPaneFontOffset(pane);
      }
      return offsets;
    }

    function storedPaneFontOffset(pane) {
      try {
        const stored = Number(
          window.localStorage.getItem(PANE_FONT_OFFSET_STORAGE_PREFIX + pane),
        );
        if (Number.isFinite(stored)) {
          return clampPaneFontOffset(stored);
        }
      } catch (error) {
        return 0;
      }
      return 0;
    }

    function savePaneFontOffset(pane) {
      try {
        window.localStorage.setItem(
          PANE_FONT_OFFSET_STORAGE_PREFIX + pane,
          String(paneFontOffset(pane)),
        );
      } catch (error) {
        return;
      }
    }

    function storedDocumentZoom() {
      try {
        const stored = Number(window.localStorage.getItem(DOCUMENT_ZOOM_STORAGE_KEY));
        if (Number.isFinite(stored)) {
          return clampDocumentZoom(stored);
        }
      } catch (error) {
        return DEFAULT_DOCUMENT_ZOOM;
      }
      return DEFAULT_DOCUMENT_ZOOM;
    }

    function saveDocumentZoom() {
      try {
        window.localStorage.setItem(DOCUMENT_ZOOM_STORAGE_KEY, String(documentZoom));
      } catch (error) {
        return;
      }
    }

    function clampTerminalFontSize(value) {
      return Math.max(
        MIN_TERMINAL_FONT_SIZE,
        Math.min(MAX_TERMINAL_FONT_SIZE, value),
      );
    }

    function clampPaneFontOffset(value) {
      return Math.max(
        MIN_PANE_FONT_OFFSET,
        Math.min(MAX_PANE_FONT_OFFSET, Math.round(value)),
      );
    }

    function paneFontOffset(pane) {
      return paneFontOffsets[pane] || 0;
    }

    function effectivePaneFontSize(pane) {
      return clampTerminalFontSize(terminalFontSize + paneFontOffset(pane));
    }

    function paneFontKeyForKind(kind) {
      if (kind === "shell") return "shell";
      if (kind === "progress") return "progress";
      if (kind === "input") return "input";
      if (kind === "scratch") return "scratch";
      if (kind === "status") return "status";
      return "agent";
    }

    function terminalForPane(pane) {
      if (pane === "agent") return terminal;
      if (pane === "progress") return progressTerminal;
      if (pane === "shell") return projectShellTerminal;
      return null;
    }

    function clampDocumentZoom(value) {
      if (!Number.isFinite(value)) {
        return DEFAULT_DOCUMENT_ZOOM;
      }
      const stepped = Math.round(value / DOCUMENT_ZOOM_STEP) * DOCUMENT_ZOOM_STEP;
      return Math.max(MIN_DOCUMENT_ZOOM, Math.min(MAX_DOCUMENT_ZOOM, stepped));
    }

    function storedNumber(key) {
      try {
        const stored = Number(window.localStorage.getItem(key));
        if (Number.isFinite(stored) && stored > 0) {
          return stored;
        }
      } catch (error) {
        return 0;
      }
      return 0;
    }

    function saveNumber(key, value) {
      try {
        window.localStorage.setItem(key, String(Math.round(value)));
      } catch (error) {
        return;
      }
    }

    function storedWorkflowPaneHeight() {
      const workflowHeight = storedNumber(WORKFLOW_PANE_HEIGHT_STORAGE_KEY);
      if (!workflowHeight) {
        return 0;
      }
      let version = "";
      try {
        version = window.localStorage.getItem(
          WORKFLOW_PANE_HEIGHT_STORAGE_VERSION_KEY,
        ) || "";
      } catch (error) {
        version = "";
      }
      if (
        version !== WORKFLOW_PANE_HEIGHT_STORAGE_VERSION &&
        workflowHeight > DEFAULT_WORKFLOW_PANE_HEIGHT
      ) {
        saveWorkflowPaneHeight(DEFAULT_WORKFLOW_PANE_HEIGHT);
        return DEFAULT_WORKFLOW_PANE_HEIGHT;
      }
      return Math.max(MIN_WORKFLOW_PANE_HEIGHT, workflowHeight);
    }

    function saveWorkflowPaneHeight(height) {
      saveNumber(WORKFLOW_PANE_HEIGHT_STORAGE_KEY, height);
      try {
        window.localStorage.setItem(
          WORKFLOW_PANE_HEIGHT_STORAGE_VERSION_KEY,
          WORKFLOW_PANE_HEIGHT_STORAGE_VERSION,
        );
      } catch (error) {
        return;
      }
    }

    function applyStoredPaneSizes() {
      const workflowHeight = storedWorkflowPaneHeight();
      if (workflowHeight) {
        shell.style.setProperty("--workflow-pane-height", `${workflowHeight}px`);
      }
      const inputHeight = storedNumber(INPUT_PANE_HEIGHT_STORAGE_KEY);
      if (inputHeight) {
        agentPane.style.setProperty("--input-pane-height", `${inputHeight}px`);
      }
      const inputActionsWidth = storedNumber(INPUT_ACTIONS_WIDTH_STORAGE_KEY);
      if (inputActionsWidth) {
        inputPane.style.setProperty(
          "--input-actions-width",
          `${inputActionsWidth}px`,
        );
      }
    }

    function applyStoredProgressPaneWidth() {
      const stored = storedNumber(PROGRESS_PANE_WIDTH_STORAGE_KEY);
      if (stored) {
        outputSplit.style.setProperty("--progress-pane-width", `${stored}px`);
      }
    }

    function applyStoredProgressPaneHeight() {
      const stored = storedNumber(PROGRESS_PANE_HEIGHT_STORAGE_KEY);
      if (stored) {
        outputSplit.style.setProperty("--progress-pane-height", `${stored}px`);
      }
    }

    function applyStoredProgressPaneSize() {
      applyStoredProgressPaneWidth();
      applyStoredProgressPaneHeight();
    }

    function applyStoredProjectShellPaneHeight() {
      const stored = storedNumber(PROJECT_SHELL_PANE_HEIGHT_STORAGE_KEY);
      if (stored) {
        leftOutputPane.style.setProperty("--shell-pane-height", `${stored}px`);
      }
    }

    function applyStoredWorkbenchPaneSize() {
      const rightWidth = storedNumber(
        creativeModeActive()
          ? CREATIVE_RIGHT_PANE_WIDTH_STORAGE_KEY
          : RIGHT_PANE_WIDTH_STORAGE_KEY,
      );
      if (rightWidth) {
        outputWorkbench.style.setProperty("--right-pane-width", `${rightWidth}px`);
      } else {
        outputWorkbench.style.removeProperty("--right-pane-width");
      }
      const rightHeight = storedNumber(RIGHT_PANE_HEIGHT_STORAGE_KEY);
      if (rightHeight) {
        outputWorkbench.style.setProperty("--right-pane-height", `${rightHeight}px`);
      }
      const scratchHeight = storedNumber(SCRATCH_PANE_HEIGHT_STORAGE_KEY);
      if (scratchHeight) {
        sidePane.style.setProperty("--scratch-pane-height", `${scratchHeight}px`);
      }
    }

    function applyStoredArtifactPaneSize() {
      const artifactWidth = storedNumber(ARTIFACT_PANE_WIDTH_STORAGE_KEY);
      if (artifactWidth) {
        outputSplit.style.setProperty("--artifact-pane-width", `${artifactWidth}px`);
      }
      const artifactHeight = storedNumber(ARTIFACT_PANE_HEIGHT_STORAGE_KEY);
      if (artifactHeight) {
        outputSplit.style.setProperty("--artifact-pane-height", `${artifactHeight}px`);
      }
    }

    function saveProgressPaneWidth(width) {
      saveNumber(PROGRESS_PANE_WIDTH_STORAGE_KEY, width);
    }

    function saveProgressPaneHeight(height) {
      saveNumber(PROGRESS_PANE_HEIGHT_STORAGE_KEY, height);
    }

    function saveProjectShellPaneHeight(height) {
      saveNumber(PROJECT_SHELL_PANE_HEIGHT_STORAGE_KEY, height);
    }

    function saveRightPaneWidth(width) {
      saveNumber(
        creativeModeActive()
          ? CREATIVE_RIGHT_PANE_WIDTH_STORAGE_KEY
          : RIGHT_PANE_WIDTH_STORAGE_KEY,
        width,
      );
    }

    function saveRightPaneHeight(height) {
      saveNumber(RIGHT_PANE_HEIGHT_STORAGE_KEY, height);
    }

    function saveScratchPaneHeight(height) {
      saveNumber(SCRATCH_PANE_HEIGHT_STORAGE_KEY, height);
    }

    function saveArtifactPaneWidth(width) {
      saveNumber(ARTIFACT_PANE_WIDTH_STORAGE_KEY, width);
    }

    function saveArtifactPaneHeight(height) {
      saveNumber(ARTIFACT_PANE_HEIGHT_STORAGE_KEY, height);
    }

    function restoreScratchPad() {
      if (creativeModeActive()) {
        loadCreativeScratchPad();
        return;
      }
      const storageKey = scratchPadStorageKey();
      if (!storageKey) {
        scratchPad.value = "";
        restoredScratchContextId = "";
        return;
      }
      try {
        scratchPad.value = window.localStorage.getItem(storageKey) || "";
        restoredScratchContextId = contextId;
      } catch (error) {
        scratchPad.value = "";
      }
    }

    function saveScratchPad() {
      if (creativeModeActive()) {
        queueCreativeScratchPadSave();
        return;
      }
      const storageKey = scratchPadStorageKey();
      if (!storageKey) {
        return;
      }
      try {
        window.localStorage.setItem(storageKey, scratchPad.value);
      } catch (error) {
        return;
      }
    }

    function scratchPadStorageKey() {
      if (!contextId) {
        return "";
      }
      return `${SCRATCH_PAD_STORAGE_KEY}.${contextId}`;
    }

    function storedDocumentTargets(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "storedDocumentTargets", ...args);
    }

    function saveDocumentTargets(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "saveDocumentTargets", ...args);
    }

    function storedWorkflowSideSheetCollapsed() {
      try {
        return window.localStorage.getItem(WORKFLOW_SIDE_SHEET_STORAGE_KEY) === "1";
      } catch (error) {
        return false;
      }
    }

    function saveWorkflowSideSheetCollapsed() {
      try {
        window.localStorage.setItem(
          WORKFLOW_SIDE_SHEET_STORAGE_KEY,
          workflowSideSheetCollapsed ? "1" : "0",
        );
      } catch (error) {
        return;
      }
    }

    function storedWorkflowMode() {
      try {
        const stored = window.localStorage.getItem(WORKFLOW_MODE_STORAGE_KEY);
        return stored === CREATIVE_WORKFLOW_MODE
          ? CREATIVE_WORKFLOW_MODE
          : SOFTWARE_WORKFLOW_MODE;
      } catch (error) {
        return SOFTWARE_WORKFLOW_MODE;
      }
    }

    function registeredWorkflows() {
      const frontend = window.ElectroBoyFrontend;
      if (frontend && typeof frontend.listWorkflows === "function") {
        const workflows = frontend.listWorkflows();
        if (workflows.length) {
          return workflows;
        }
      }
      return [
        {
          id: "software",
          mode: SOFTWARE_WORKFLOW_MODE,
          label: "Software engineering",
        },
        {
          id: "creative-writing",
          mode: CREATIVE_WORKFLOW_MODE,
          label: "Creative writing",
        },
      ];
    }

    function renderWorkflowModeOptions() {
      const workflows = registeredWorkflows();
      workflowModeSelect.replaceChildren();
      workflows.forEach((workflow) => {
        const option = document.createElement("option");
        option.value = workflow.mode;
        option.textContent = workflow.label;
        workflowModeSelect.append(option);
      });
    }

    function saveWorkflowMode() {
      try {
        window.localStorage.setItem(WORKFLOW_MODE_STORAGE_KEY, workflowMode);
      } catch (error) {
        return;
      }
    }

    function creativeModeActive() {
      return workflowMode === CREATIVE_WORKFLOW_MODE;
    }

    function applyWorkflowMode(options = {}) {
      workflowModeSelect.value = workflowMode;
      shell.classList.toggle("creative-workflow", creativeModeActive());
      updateSplashImage();
      applyStoredWorkbenchPaneSize();
      creativeBinder.hidden = !creativeModeActive();
      stageActionBody.hidden = creativeModeActive();
      if (options.deferWorkspace) {
        refreshStageActionPanel();
        updateCreativeBinderActions();
        window.requestAnimationFrame(fitTerminal);
        return;
      }
      if (creativeModeActive()) {
        setWorkflowSideSheetCollapsed(false);
        applyCreativeWorkspace();
        restoreScratchPad();
        refreshCreativeBinder();
      } else {
        restoreSoftwareWorkspace();
      }
      refreshStageActionPanel();
      updateCreativeBinderActions();
      window.requestAnimationFrame(fitTerminal);
    }

    async function setWorkflowMode(mode) {
      const nextMode = mode === CREATIVE_WORKFLOW_MODE
        ? CREATIVE_WORKFLOW_MODE
        : SOFTWARE_WORKFLOW_MODE;
      if (nextMode === workflowMode) {
        applyWorkflowMode();
        return;
      }
      releaseContextOwner();
      contextId = "";
      resetWorkflowContextView();
      workflowMode = nextMode;
      saveWorkflowMode();
      applyWorkflowMode({ deferWorkspace: true });
      await restoreContext();
    }

    function applyWorkflowSideSheetState() {
      shell.classList.toggle("side-sheet-collapsed", workflowSideSheetCollapsed);
      toggleWorkflowSideSheet.setAttribute(
        "aria-label",
        workflowSideSheetCollapsed
          ? "Expand workflow side sheet"
          : "Collapse workflow side sheet",
      );
      toggleWorkflowSideSheet.title = workflowSideSheetCollapsed
        ? "Expand workflow side sheet"
        : "Collapse workflow side sheet";
      window.requestAnimationFrame(fitTerminal);
    }

    function setWorkflowSideSheetCollapsed(collapsed) {
      workflowSideSheetCollapsed = Boolean(collapsed);
      applyWorkflowSideSheetState();
      saveWorkflowSideSheetCollapsed();
    }

    function toggleWorkflowSideSheetCollapsed() {
      setWorkflowSideSheetCollapsed(!workflowSideSheetCollapsed);
    }

    function initializeTerminal() {
      if (!window.Terminal) {
        appendPlainOutput("terminal renderer unavailable; using plain text\n", "error");
        return;
      }
      terminal = new window.Terminal(terminalOptions(true, "agent"));
      if (window.FitAddon && window.FitAddon.FitAddon) {
        terminalFit = new window.FitAddon.FitAddon();
        terminal.loadAddon(terminalFit);
      }
      terminal.open(agentOutput);
      terminal.onResize(({ cols, rows }) => {
        queueTerminalResize(cols, rows);
      });
      applyTerminalFontSize();
      fitTerminal();
      window.addEventListener("resize", fitTerminal);
    }

    function initializeProgressTerminal(...args) {
      return window.ElectroBoyFrontend.invokeModule("progress", "initializeProgressTerminal", ...args);
    }

    function initializeProjectShellTerminal(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "initializeProjectShellTerminal", ...args);
    }

    function terminalOptions(disableStdin = true, pane = "agent") {
      return {
        allowProposedApi: false,
        convertEol: true,
        cursorBlink: false,
        disableStdin,
        fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace',
        fontSize: effectivePaneFontSize(pane),
        scrollback: 10000,
        termName: "xterm-256color",
        theme: {
          background: "#10141f",
          foreground: "#e7edf7",
          cursor: "#e7edf7",
          selectionBackground: "#2b6173",
          black: "#151923",
          red: "#ff6b6b",
          green: "#51cf66",
          yellow: "#ffd43b",
          blue: "#74c0fc",
          magenta: "#da77f2",
          cyan: "#66d9e8",
          white: "#f1f3f5",
          brightBlack: "#5c677d",
          brightRed: "#ff8787",
          brightGreen: "#69db7c",
          brightYellow: "#ffe066",
          brightBlue: "#91caff",
          brightMagenta: "#e599f7",
          brightCyan: "#99e9f2",
          brightWhite: "#ffffff",
        },
      };
    }

    function timestampForDownload() {
      return new Date().toISOString().replace(/[:.]/g, "-");
    }

    function exportSafeName(value, fallback = "export") {
      return String(value || fallback)
        .replace(/[^A-Za-z0-9._-]+/g, "-")
        .replace(/^-+|-+$/g, "")
        || fallback;
    }

    function documentExportFormats(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "documentExportFormats", ...args);
    }

    function documentExportFormat(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "documentExportFormat", ...args);
    }

    function documentExportPickerTypes(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "documentExportPickerTypes", ...args);
    }

    function downloadBlob(fileName, blob) {
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
    }

    async function writeBlobWithPicker(
      blob,
      suggestedName,
      pickerTypes = documentExportPickerTypes("markdown"),
    ) {
      if (!window.showSaveFilePicker) {
        downloadBlob(suggestedName, blob);
        return;
      }
      try {
        const handle = await window.showSaveFilePicker({
          suggestedName,
          types: pickerTypes,
        });
        const writable = await handle.createWritable();
        await writable.write(blob);
        await writable.close();
      } catch (error) {
        if (error && error.name === "AbortError") {
          return;
        }
        appendOutput(`export picker failed: ${error}\n`, "error");
        downloadBlob(suggestedName, blob);
      }
    }

    async function exportBlob(url, suggestedName, format = "markdown") {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) {
        const message = await response.text();
        appendOutput(`${message || "export failed"}\n`, "error");
        return;
      }
      const blob = await response.blob();
      await writeBlobWithPicker(
        blob,
        suggestedName,
        documentExportPickerTypes(format),
      );
    }

    async function exportMarkdown(url, suggestedName) {
      await exportBlob(url, suggestedName, "markdown");
    }

    function sessionExportName(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "sessionExportName", ...args);
    }

    function exportAgentSession(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "exportAgentSession", ...args);
    }

    function exportProgressLog(...args) {
      return window.ElectroBoyFrontend.invokeModule("progress", "exportProgressLog", ...args);
    }

    function artifactDocumentBaseName(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "artifactDocumentBaseName", ...args);
    }

    function artifactDocumentExportName(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "artifactDocumentExportName", ...args);
    }

    function artifactDocumentExportUrl(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "artifactDocumentExportUrl", ...args);
    }

    function exportArtifactDocument(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "exportArtifactDocument", ...args);
    }

    function changeTerminalFontSize(delta) {
      terminalFontSize = clampTerminalFontSize(terminalFontSize + delta);
      saveTerminalFontSize();
      applyTerminalFontSize();
    }

    function changePaneFontOffset(pane, delta) {
      if (!PANE_FONT_KEYS.includes(pane)) {
        return;
      }
      paneFontOffsets[pane] = clampPaneFontOffset(paneFontOffset(pane) + delta);
      savePaneFontOffset(pane);
      applyPaneFontSize(pane);
    }

    function resetPaneFontOffset(pane) {
      if (!PANE_FONT_KEYS.includes(pane)) {
        return;
      }
      paneFontOffsets[pane] = 0;
      savePaneFontOffset(pane);
      applyPaneFontSize(pane);
    }

    function changeDocumentZoom(delta) {
      documentZoom = clampDocumentZoom(documentZoom + delta);
      saveDocumentZoom();
      applyDocumentZoom();
      if (artifactPreviewItems.length > 0) {
        refreshArtifactPreview({ includeEditing: false });
      }
    }

    function artifactEditorFontSize() {
      return Math.max(11, Math.min(28, Math.round(16 * (documentZoom / 100))));
    }

    function applyTerminalFontSize() {
      terminalFontValue.textContent = `${terminalFontSize}px`;
      document.documentElement.style.setProperty(
        "--terminal-font-size",
        `${terminalFontSize}px`,
      );
      document.documentElement.style.setProperty(
        "--ui-font-size",
        `${terminalFontSize}px`,
      );
      document.documentElement.style.setProperty(
        "--ui-small-font-size",
        `${Math.max(10, terminalFontSize - 2)}px`,
      );
      document.documentElement.style.setProperty(
        "--ui-menu-font-size",
        `${Math.max(11, terminalFontSize - 1)}px`,
      );
      applyPaneFontSizes();
      decreaseTerminalFont.disabled = terminalFontSize <= MIN_TERMINAL_FONT_SIZE;
      increaseTerminalFont.disabled = terminalFontSize >= MAX_TERMINAL_FONT_SIZE;
      window.requestAnimationFrame(fitTerminal);
    }

    function applyPaneFontSizes() {
      for (const pane of PANE_FONT_KEYS) {
        applyPaneFontSize(pane);
      }
    }

    function applyPaneFontSize(pane) {
      const cssProperty = PANE_FONT_CSS_PROPERTIES[pane];
      const fontSize = effectivePaneFontSize(pane);
      if (cssProperty) {
        document.documentElement.style.setProperty(cssProperty, `${fontSize}px`);
      }
      const paneTerminal = terminalForPane(pane);
      if (paneTerminal) {
        paneTerminal.options.fontSize = fontSize;
      }
      updatePaneFontControls(pane);
      window.requestAnimationFrame(fitTerminal);
    }

    function updatePaneFontControls(pane) {
      const offset = paneFontOffset(pane);
      const fontSize = effectivePaneFontSize(pane);
      for (const level of document.querySelectorAll(`[data-pane-font-level="${pane}"]`)) {
        level.textContent = `${fontSize}px`;
        level.title = offset === 0 ? "Global font size" : `Global ${offset > 0 ? "+" : ""}${offset}px`;
      }
      for (const button of document.querySelectorAll(`[data-pane-font="${pane}"]`)) {
        if (button.dataset.paneFontReset) {
          button.disabled = offset === 0;
          continue;
        }
        const delta = Number(button.dataset.paneFontDelta || "0");
        if (delta < 0) {
          button.disabled = offset <= MIN_PANE_FONT_OFFSET;
        } else if (delta > 0) {
          button.disabled = offset >= MAX_PANE_FONT_OFFSET;
        }
      }
    }

    function applyDocumentZoom() {
      for (const level of artifactPreviewStack.querySelectorAll(".document-zoom-level")) {
        level.textContent = `${documentZoom}%`;
      }
      for (const button of artifactPreviewStack.querySelectorAll("[data-zoom='out']")) {
        button.disabled = documentZoom <= MIN_DOCUMENT_ZOOM;
      }
      for (const button of artifactPreviewStack.querySelectorAll("[data-zoom='in']")) {
        button.disabled = documentZoom >= MAX_DOCUMENT_ZOOM;
      }
      postArtifactEditorFontSize();
    }

    function postArtifactEditorFontSize(targetFrame = null) {
      const frames = targetFrame
        ? [targetFrame]
        : Array.from(artifactPreviewStack.querySelectorAll(".artifact-preview-frame"));
      for (const frame of frames) {
        const item = artifactPreviewItems.find(
          (candidate) => candidate.id === frame.dataset.artifactId,
        );
        if (!item || !item.editing || !frame.contentWindow) {
          continue;
        }
        frame.contentWindow.postMessage(
          {
            type: "electroboy-editor-font-size",
            font_size: artifactEditorFontSize(),
          },
          window.location.origin,
        );
      }
    }

    function prepareTerminalStream() {
      applyTerminalFontSize();
      fitTerminal();
    }

    function fitTerminal() {
      if (terminalFit) {
        try {
          terminalFit.fit();
        } catch (error) {
          return;
        }
      }
      if (progressTerminalFit && !progressOutputPane.hidden) {
        try {
          progressTerminalFit.fit();
        } catch (error) {
          return;
        }
      }
      if (projectShellTerminalFit && !projectShellPane.hidden) {
        try {
          projectShellTerminalFit.fit();
        } catch (error) {
          return;
        }
      }
      queueTerminalResize();
      queueProjectShellResize();
    }

    function observeTerminalPaneResizes() {
      if (!window.ResizeObserver) {
        return;
      }
      terminalResizeObserver = new window.ResizeObserver(() => {
        window.requestAnimationFrame(fitTerminal);
      });
      terminalResizeObserver.observe(agentOutput);
      terminalResizeObserver.observe(progressOutput);
      terminalResizeObserver.observe(projectShellOutput);
    }

    function terminalResizePayload(columns = null, rows = null) {
      const session = selectedSession();
      if (!sessionIsRunning(session) || !contextId || !terminal) {
        return null;
      }
      return {
        session_id: session.session_id,
        columns: Number(columns || terminal.cols || 120),
        rows: Number(rows || terminal.rows || 32),
      };
    }

    function queueTerminalResize(columns = null, rows = null) {
      const payload = terminalResizePayload(columns, rows);
      if (!payload) {
        return;
      }
      pendingTerminalResize = payload;
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => {
        const resize = pendingTerminalResize;
        pendingTerminalResize = null;
        sendTerminalResize(resize);
      }, 120);
    }

    async function sendTerminalResize(payload = null) {
      const resize = payload || terminalResizePayload();
      if (!resize) {
        return;
      }
      await fetch(contextUrl("/api/sessions/resize"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(resize),
      }).catch(() => {});
    }

    function queueProjectShellResize(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "queueProjectShellResize", ...args);
    }

    function sendProjectShellResize(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "sendProjectShellResize", ...args);
    }

    function appendOutput(text, className = "") {
      if (terminal) {
        terminal.write(formatTerminalMessage(text, className));
        return;
      }
      appendPlainOutput(text, className);
    }

    function appendPlainOutput(text, className = "") {
      const span = document.createElement("span");
      span.textContent = text;
      if (className) {
        span.className = className;
      }
      agentOutput.appendChild(span);
      agentOutput.scrollTop = agentOutput.scrollHeight;
    }

    function recordProjectStatusMessage(message) {
      const text = String(message || "").trim();
      if (!text) {
        return;
      }
      const timestamp = new Date().toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
      projectStatusMessages.push(`${timestamp} ${text}`);
      if (projectStatusMessages.length > PROJECT_STATUS_MESSAGE_LIMIT) {
        projectStatusMessages = projectStatusMessages.slice(-PROJECT_STATUS_MESSAGE_LIMIT);
      }
      if (creativeModeActive()) {
        renderCreativeProjectStatus();
      } else {
        projectStatusOutput.textContent = `${projectStatusMessages.slice(-12).join("\n")}\n`;
      }
    }

    function renderCreativeProjectStatus() {
      if (!projectStatusOutput) {
        return;
      }
      if (!creativeModeActive()) {
        return;
      }
      const lines = [];
      if (activeProjectRoot || activationRoot) {
        lines.push(`project: ${activeProjectRoot || activationRoot}`);
      } else {
        lines.push("no active project");
      }
      if (creativeActiveDocument) {
        lines.push(`document: ${creativeActiveDocument}`);
      } else if (creativeActiveFolder) {
        lines.push(`folder: ${creativeActiveFolder}`);
      }
      if (projectStatusMessages.length > 0) {
        lines.push("");
        lines.push(...projectStatusMessages.slice(-12));
      }
      projectStatusOutput.textContent = `${lines.join("\n")}\n`;
    }

    function appendAgentOutput(text) {
      if (terminal) {
        terminal.write(text);
        return;
      }
      appendPlainOutput(text);
    }

    function clearAgentOutput() {
      if (terminal) {
        terminal.clear();
        return;
      }
      agentOutput.replaceChildren();
    }

    function appendProgressOutput(...args) {
      return window.ElectroBoyFrontend.invokeModule("progress", "appendProgressOutput", ...args);
    }

    function clearProgressOutput(...args) {
      return window.ElectroBoyFrontend.invokeModule("progress", "clearProgressOutput", ...args);
    }

    function appendProjectShellOutput(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "appendProjectShellOutput", ...args);
    }

    function clearProjectShellOutput(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "clearProjectShellOutput", ...args);
    }

    function applyProjectShellPaneVisibility(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "applyProjectShellPaneVisibility", ...args);
    }

    function showProjectShellPane(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "showProjectShellPane", ...args);
    }

    function hideProjectShellPane(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "hideProjectShellPane", ...args);
    }

    function syncProjectShellPane(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "syncProjectShellPane", ...args);
    }

    function toggleProjectShellFromToolbar(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "toggleProjectShellFromToolbar", ...args);
    }

    function updateProjectShellToggle(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "updateProjectShellToggle", ...args);
    }

    function startProjectShell(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "startProjectShell", ...args);
    }

    function connectProjectShellEvents(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "connectProjectShellEvents", ...args);
    }

    function closeProjectShellEventStream(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "closeProjectShellEventStream", ...args);
    }

    function disposeProjectShellTerminal(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "disposeProjectShellTerminal", ...args);
    }

    function sendProjectShellInput(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "sendProjectShellInput", ...args);
    }

    function stopProjectShellProcess(...args) {
      return window.ElectroBoyFrontend.invokeModule("project-shell", "stopProjectShellProcess", ...args);
    }

    function setAgentInputVisible(isVisible) {
      inputPaneRequested = isVisible;
      const visible = isVisible && !poppedPanes.has("input");
      inputPane.hidden = !visible;
      inputResizeHandle.hidden = !visible;
      agentPane.classList.toggle("noninteractive", !visible);
      if (isVisible) {
        applyStoredPaneSizes();
      }
      if (!isVisible) {
        agentInput.disabled = true;
        insertFileLink.disabled = true;
      }
      window.requestAnimationFrame(fitTerminal);
    }

    function startShellResize(event) {
      event.preventDefault();
      const shellRect = shell.getBoundingClientRect();
      const workflowRect = workflowPane.getBoundingClientRect();
      resizeShellState = {
        startY: event.clientY,
        startHeight: workflowRect.height,
        maxHeight: Math.max(MIN_WORKFLOW_PANE_HEIGHT, shellRect.height - 240),
      };
      shellResizeHandle.setPointerCapture(event.pointerId);
      shell.classList.add("resizing");
    }

    function updateShellResize(event) {
      if (!resizeShellState) {
        return;
      }
      const deltaY = event.clientY - resizeShellState.startY;
      const nextHeight = clampValue(
        resizeShellState.startHeight + deltaY,
        MIN_WORKFLOW_PANE_HEIGHT,
        resizeShellState.maxHeight,
      );
      shell.style.setProperty("--workflow-pane-height", `${nextHeight}px`);
      saveWorkflowPaneHeight(nextHeight);
      repositionOpenStageMenu();
      fitTerminal();
    }

    function finishShellResize(event) {
      if (!resizeShellState) {
        return;
      }
      resizeShellState = null;
      shell.classList.remove("resizing");
      try {
        shellResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
      repositionOpenStageMenu();
      fitTerminal();
    }

    function startInputResize(event) {
      if (inputPane.hidden) {
        return;
      }
      event.preventDefault();
      const agentRect = agentPane.getBoundingClientRect();
      const inputRect = inputPane.getBoundingClientRect();
      resizeInputState = {
        startY: event.clientY,
        startHeight: inputRect.height,
        maxHeight: Math.max(MIN_INPUT_PANE_HEIGHT, agentRect.height - 160),
      };
      inputResizeHandle.setPointerCapture(event.pointerId);
      agentPane.classList.add("resizing-input");
    }

    function updateInputResize(event) {
      if (!resizeInputState) {
        return;
      }
      const deltaY = resizeInputState.startY - event.clientY;
      const nextHeight = clampValue(
        resizeInputState.startHeight + deltaY,
        MIN_INPUT_PANE_HEIGHT,
        resizeInputState.maxHeight,
      );
      agentPane.style.setProperty("--input-pane-height", `${nextHeight}px`);
      saveNumber(INPUT_PANE_HEIGHT_STORAGE_KEY, nextHeight);
      fitTerminal();
    }

    function finishInputResize(event) {
      if (!resizeInputState) {
        return;
      }
      resizeInputState = null;
      agentPane.classList.remove("resizing-input");
      try {
        inputResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
      fitTerminal();
    }

    function startInputActionsResize(event) {
      if (inputPane.hidden || window.matchMedia("(max-width: 760px)").matches) {
        return;
      }
      event.preventDefault();
      const inputPaneRect = inputPane.getBoundingClientRect();
      const inputPaneStyle = window.getComputedStyle(inputPane);
      const horizontalPadding =
        Number.parseFloat(inputPaneStyle.paddingLeft) +
        Number.parseFloat(inputPaneStyle.paddingRight);
      const columnGap = Number.parseFloat(inputPaneStyle.columnGap) || 0;
      const handleWidth = inputActionResizeHandle.getBoundingClientRect().width;
      const availableColumnWidth =
        inputPaneRect.width - horizontalPadding - handleWidth - (columnGap * 2);
      const actionsRect =
        inputPane.querySelector(".agent-actions").getBoundingClientRect();
      resizeInputActionsState = {
        startX: event.clientX,
        startWidth: actionsRect.width,
        maxWidth: Math.max(
          MIN_INPUT_ACTIONS_WIDTH,
          availableColumnWidth - MIN_AGENT_INPUT_WIDTH,
        ),
      };
      inputActionResizeHandle.setPointerCapture(event.pointerId);
      inputPane.classList.add("resizing-actions");
    }

    function updateInputActionsResize(event) {
      if (!resizeInputActionsState) {
        return;
      }
      const deltaX = resizeInputActionsState.startX - event.clientX;
      const nextWidth = clampValue(
        resizeInputActionsState.startWidth + deltaX,
        MIN_INPUT_ACTIONS_WIDTH,
        resizeInputActionsState.maxWidth,
      );
      inputPane.style.setProperty("--input-actions-width", `${nextWidth}px`);
      saveNumber(INPUT_ACTIONS_WIDTH_STORAGE_KEY, nextWidth);
    }

    function finishInputActionsResize(event) {
      if (!resizeInputActionsState) {
        return;
      }
      resizeInputActionsState = null;
      inputPane.classList.remove("resizing-actions");
      try {
        inputActionResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
    }

    function startWorkbenchResize(event) {
      event.preventDefault();
      const workbenchRect = outputWorkbench.getBoundingClientRect();
      const sideRect = sidePane.getBoundingClientRect();
      resizeWorkbenchState = {
        vertical: window.matchMedia("(max-width: 760px)").matches,
        startX: event.clientX,
        startY: event.clientY,
        startWidth: sideRect.width,
        startHeight: sideRect.height,
        maxWidth: Math.max(260, workbenchRect.width - 340),
        maxHeight: Math.max(200, workbenchRect.height - 220),
      };
      workbenchResizeHandle.setPointerCapture(event.pointerId);
      outputWorkbench.classList.add("resizing");
    }

    function updateWorkbenchResize(event) {
      if (!resizeWorkbenchState) {
        return;
      }
      if (resizeWorkbenchState.vertical) {
        const deltaY = resizeWorkbenchState.startY - event.clientY;
        const nextHeight = clampValue(
          resizeWorkbenchState.startHeight + deltaY,
          200,
          resizeWorkbenchState.maxHeight,
        );
        outputWorkbench.style.setProperty("--right-pane-height", `${nextHeight}px`);
        outputWorkbench.style.gridTemplateRows = `minmax(0, 1fr) 7px ${nextHeight}px`;
        saveRightPaneHeight(nextHeight);
      } else {
        const deltaX = resizeWorkbenchState.startX - event.clientX;
        const nextWidth = clampValue(
          resizeWorkbenchState.startWidth + deltaX,
          260,
          resizeWorkbenchState.maxWidth,
        );
        outputWorkbench.style.setProperty("--right-pane-width", `${nextWidth}px`);
        saveRightPaneWidth(nextWidth);
      }
      fitTerminal();
    }

    function finishWorkbenchResize(event) {
      if (!resizeWorkbenchState) {
        return;
      }
      resizeWorkbenchState = null;
      outputWorkbench.classList.remove("resizing");
      try {
        workbenchResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
      fitTerminal();
    }

    function startSidePaneResize(event) {
      event.preventDefault();
      const sideRect = sidePane.getBoundingClientRect();
      const scratchRect = scratchPad.getBoundingClientRect();
      resizeSidePaneState = {
        startY: event.clientY,
        startHeight: scratchRect.height,
        maxHeight: Math.max(120, sideRect.height - 150),
      };
      sidePaneResizeHandle.setPointerCapture(event.pointerId);
      sidePane.classList.add("resizing");
    }

    function updateSidePaneResize(event) {
      if (!resizeSidePaneState) {
        return;
      }
      const deltaY = event.clientY - resizeSidePaneState.startY;
      const nextHeight = clampValue(
        resizeSidePaneState.startHeight + deltaY,
        120,
        resizeSidePaneState.maxHeight,
      );
      sidePane.style.setProperty("--scratch-pane-height", `${nextHeight}px`);
      saveScratchPaneHeight(nextHeight);
    }

    function finishSidePaneResize(event) {
      if (!resizeSidePaneState) {
        return;
      }
      resizeSidePaneState = null;
      sidePane.classList.remove("resizing");
      try {
        sidePaneResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
    }

    function startArtifactPaneResize(event) {
      if (artifactPreviewPane.hidden || poppedPanes.has("agent")) {
        return;
      }
      event.preventDefault();
      const splitRect = outputSplit.getBoundingClientRect();
      const artifactRect = artifactPreviewPane.getBoundingClientRect();
      resizeArtifactPaneState = {
        vertical: window.matchMedia("(max-width: 760px)").matches,
        startX: event.clientX,
        startY: event.clientY,
        startWidth: artifactRect.width,
        startHeight: artifactRect.height,
        maxWidth: Math.max(320, splitRect.width - 360),
        maxHeight: Math.max(220, splitRect.height - 240),
      };
      artifactPaneResizeHandle.setPointerCapture(event.pointerId);
      outputSplit.classList.add("resizing-artifact");
    }

    function updateArtifactPaneResize(event) {
      if (!resizeArtifactPaneState) {
        return;
      }
      if (resizeArtifactPaneState.vertical) {
        const deltaY = resizeArtifactPaneState.startY - event.clientY;
        const nextHeight = clampValue(
          resizeArtifactPaneState.startHeight + deltaY,
          220,
          resizeArtifactPaneState.maxHeight,
        );
        outputSplit.style.setProperty("--artifact-pane-height", `${nextHeight}px`);
        outputSplit.style.gridTemplateRows = `minmax(0, 1fr) 7px ${nextHeight}px`;
        saveArtifactPaneHeight(nextHeight);
      } else {
        const deltaX = resizeArtifactPaneState.startX - event.clientX;
        const nextWidth = clampValue(
          resizeArtifactPaneState.startWidth + deltaX,
          320,
          resizeArtifactPaneState.maxWidth,
        );
        outputSplit.style.setProperty("--artifact-pane-width", `${nextWidth}px`);
        saveArtifactPaneWidth(nextWidth);
      }
      fitTerminal();
    }

    function finishArtifactPaneResize(event) {
      if (!resizeArtifactPaneState) {
        return;
      }
      resizeArtifactPaneState = null;
      outputSplit.classList.remove("resizing-artifact");
      try {
        artifactPaneResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
    }

    function applyOutputPaneVisibility() {
      const agentVisible = !poppedPanes.has("agent");
      const artifactVisible =
        artifactPaneRequested && artifactPreviewItems.length > 0 && !poppedPanes.has("artifact");
      const progressVisible = progressPaneRequested && !poppedPanes.has("progress");
      if (artifactVisible) {
        ensurePaneInLayout("artifact", "agent", "row");
      }
      if (progressVisible) {
        ensurePaneInLayout("progress", "agent", "row");
      }
      agentOutputPane.hidden = !agentVisible;
      artifactPreviewPane.hidden = !artifactVisible;
      progressOutputPane.hidden = !progressVisible;
      artifactPaneResizeHandle.hidden = !artifactVisible || !agentVisible;
      outputResizeHandle.hidden =
        !progressVisible || (!agentVisible && !artifactVisible);
      outputSplit.classList.toggle("agent-popped", !agentVisible);
      outputSplit.classList.toggle("artifact-visible", Boolean(artifactVisible));
      outputSplit.classList.toggle("split", progressVisible);
      window.requestAnimationFrame(fitTerminal);
    }

    function showProgressPane(show) {
      progressPaneRequested = show;
      if (show) {
        outputSplit.style.gridTemplateRows = "";
        applyStoredProgressPaneSize();
        initializeProgressTerminal();
        prepareTerminalStream();
      } else {
        outputSplit.style.gridTemplateRows = "";
        closeProgressEventStream();
      }
      applyOutputPaneVisibility();
      window.requestAnimationFrame(fitTerminal);
    }

    function startOutputResize(event) {
      if (progressOutputPane.hidden) {
        return;
      }
      event.preventDefault();
      const splitRect = outputSplit.getBoundingClientRect();
      const progressRect = progressOutputPane.getBoundingClientRect();
      resizeOutputState = {
        vertical: window.matchMedia("(max-width: 760px)").matches,
        startX: event.clientX,
        startY: event.clientY,
        startSize: progressRect.width,
        startHeight: progressRect.height,
        maxWidth: Math.max(280, splitRect.width - 320),
        maxHeight: Math.max(180, splitRect.height - 220),
      };
      outputResizeHandle.setPointerCapture(event.pointerId);
      outputSplit.classList.add("resizing");
    }

    function updateOutputResize(event) {
      if (!resizeOutputState) {
        return;
      }
      if (resizeOutputState.vertical) {
        const deltaY = resizeOutputState.startY - event.clientY;
        const nextHeight = clampValue(
          resizeOutputState.startHeight + deltaY,
          180,
          resizeOutputState.maxHeight,
        );
        outputSplit.style.setProperty("--progress-pane-height", `${nextHeight}px`);
        outputSplit.style.gridTemplateRows = `minmax(0, 1fr) 7px ${nextHeight}px`;
        saveProgressPaneHeight(nextHeight);
      } else {
        const deltaX = resizeOutputState.startX - event.clientX;
        const nextWidth = clampValue(
          resizeOutputState.startSize + deltaX,
          280,
          resizeOutputState.maxWidth,
        );
        outputSplit.style.setProperty("--progress-pane-width", `${nextWidth}px`);
        saveProgressPaneWidth(nextWidth);
      }
      fitTerminal();
    }

    function finishOutputResize(event) {
      if (!resizeOutputState) {
        return;
      }
      resizeOutputState = null;
      outputSplit.classList.remove("resizing");
      try {
        outputResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
      fitTerminal();
    }

    function startProjectShellPaneResize(event) {
      if (projectShellPane.hidden) {
        return;
      }
      event.preventDefault();
      const leftOutputRect = leftOutputPane.getBoundingClientRect();
      const shellRect = projectShellPane.getBoundingClientRect();
      resizeProjectShellState = {
        startY: event.clientY,
        startHeight: shellRect.height,
        maxHeight: Math.max(180, leftOutputRect.height - 220),
      };
      shellPaneDivider.setPointerCapture(event.pointerId);
      leftOutputPane.classList.add("resizing-shell");
    }

    function updateProjectShellPaneResize(event) {
      if (!resizeProjectShellState) {
        return;
      }
      const deltaY = resizeProjectShellState.startY - event.clientY;
      const nextHeight = clampValue(
        resizeProjectShellState.startHeight + deltaY,
        180,
        resizeProjectShellState.maxHeight,
      );
      leftOutputPane.style.setProperty("--shell-pane-height", `${nextHeight}px`);
      saveProjectShellPaneHeight(nextHeight);
      fitTerminal();
    }

    function finishProjectShellPaneResize(event) {
      if (!resizeProjectShellState) {
        return;
      }
      resizeProjectShellState = null;
      leftOutputPane.classList.remove("resizing-shell");
      try {
        shellPaneDivider.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
      fitTerminal();
    }

    function clampValue(value, minimum, maximum) {
      const upper = Math.max(minimum, maximum);
      return Math.max(minimum, Math.min(upper, value));
    }

    function formatTerminalMessage(text, className) {
      if (className === "error") {
        return `\x1b[31m${text}\x1b[0m`;
      }
      if (className === "system") {
        return `\x1b[36m${text}\x1b[0m`;
      }
      return text;
    }

    function setConnected() {
      connection.textContent = connectionBadgeLabel();
    }

    function connectionBadgeLabel() {
      const parts = ["connected"];
      if (activationRoot) {
        parts.push(activationRoot);
      }
      const feature = activeWorkItemFeature();
      if (feature) {
        parts.push(`feature: ${feature.name || feature.slug}`);
      }
      return parts.join(" · ");
    }

    function applyStageDescriptions() {
      for (const stageNode of stageNodes) {
        const stageId = stageNode.dataset.stage || "";
        const description = STAGE_DESCRIPTIONS[stageId] || "";
        if (!description) {
          continue;
        }
        const label = stageNode.textContent.trim();
        stageNode.title = description;
        stageNode.setAttribute("aria-label", `${label}: ${description}`);
      }
    }

    async function checkConnection() {
      const response = await fetch("/api/health", { cache: "no-store" });
      if (response.ok) {
        setConnected();
      }
    }

    function contextUrl(path) {
      const separator = path.includes("?") ? "&" : "?";
      return `${path}${separator}context_id=${encodeURIComponent(contextId)}`;
    }

    function paneUrl(kind, requestedArtifactItem = null) {
      const parameters = new URLSearchParams();
      if (contextId) {
        parameters.set("context_id", contextId);
      }
      if (selectedSessionId) {
        parameters.set("session_id", selectedSessionId);
      }
      const artifactItem = requestedArtifactItem || artifactPreviewItems[0] || null;
      if (artifactItem) {
        parameters.set("artifact", artifactKindForPane(artifactItem));
      }
      if (artifactItem && artifactItem.kind === "document" && artifactItem.target) {
        parameters.set("document_path", artifactItem.target.path);
        parameters.set("document_title", artifactItem.target.label);
      }
      if (
        artifactItem &&
        artifactItem.kind === "creative-corkboard" &&
        artifactItem.folder
      ) {
        parameters.set("folder_path", artifactItem.folder.path);
        parameters.set("folder_title", artifactItem.folder.label || artifactItem.title);
      }
      if (
        artifactItem &&
        artifactItem.kind === "creative-corkboard" &&
        artifactItem.corkboard
      ) {
        parameters.set("corkboard_path", artifactItem.corkboard.path);
        parameters.set(
          "corkboard_title",
          artifactItem.corkboard.label || artifactItem.title,
        );
      }
      const fontPane = paneFontKeyForKind(kind);
      parameters.set("base_font_size", String(terminalFontSize));
      parameters.set("font_pane", fontPane);
      parameters.set("font_offset", String(paneFontOffset(fontPane)));
      parameters.set("font_size", String(effectivePaneFontSize(fontPane)));
      parameters.set("document_zoom", String(documentZoom));
      return `/pane/${encodeURIComponent(kind)}?${parameters.toString()}`;
    }

    function popOutPane(kind, artifactItem = null) {
      if (!contextId && kind !== "scratch") {
        appendOutput("create a browser context first\n", "error");
        return;
      }
      const popup = window.open(
        paneUrl(kind, artifactItem),
        `electroboy-${kind}-${contextId || "local"}`,
        PANE_POPUP_FEATURES,
      );
      if (!popup) {
        appendOutput("popup was blocked by the browser\n", "error");
        return;
      }
      const existing = poppedPaneWindows.get(kind);
      if (existing) {
        window.clearInterval(existing.poll);
      }
      setPanePoppedOut(kind, true);
      const poll = window.setInterval(() => {
        if (!popup.closed) {
          return;
        }
        window.clearInterval(poll);
        poppedPaneWindows.delete(kind);
        setPanePoppedOut(kind, false);
      }, 500);
      poppedPaneWindows.set(kind, { popup, poll });
    }

    function dockPoppedPane(kind) {
      const existing = poppedPaneWindows.get(kind);
      if (existing) {
        window.clearInterval(existing.poll);
        try {
          existing.popup.close();
        } catch (error) {
          // The browser may block closing a user-managed window.
        }
        poppedPaneWindows.delete(kind);
      }
      setPanePoppedOut(kind, false);
    }

    function setPanePoppedOut(kind, poppedOut) {
      if (poppedOut) {
        poppedPanes.add(kind);
      } else {
        poppedPanes.delete(kind);
      }
      if (kind === "scratch" || kind === "status") {
        applySidePaneVisibility();
      }
      if (kind === "input") {
        setAgentInputVisible(inputPaneRequested);
      }
      if (kind === "agent" || kind === "artifact" || kind === "progress") {
        if (kind === "artifact") {
          if (poppedOut) {
            artifactPreviewStack.replaceChildren();
          } else if (artifactPreviewItems.length > 0) {
            renderArtifactPreviewItems();
          }
        }
        applyOutputPaneVisibility();
      }
      if (kind === "shell") {
        if (poppedOut) {
          closeProjectShellEventStream();
          disposeProjectShellTerminal();
        }
        applyProjectShellPaneVisibility();
        if (
          !poppedOut &&
          projectShellRunning &&
          projectShellPaneRequested &&
          !projectShellEventSource
        ) {
          window.setTimeout(connectProjectShellEvents, 0);
        }
      }
      window.requestAnimationFrame(fitTerminal);
    }

    function applySidePaneVisibility() {
      const scratchPopped = poppedPanes.has("scratch");
      const statusPopped = poppedPanes.has("status");
      const sideVisible = !(scratchPopped && statusPopped);
      scratchPane.hidden = scratchPopped;
      projectStatusPane.hidden = statusPopped;
      sidePaneResizeHandle.hidden = scratchPopped || statusPopped;
      sidePane.hidden = !sideVisible;
      workbenchResizeHandle.hidden = !sideVisible;
      outputWorkbench.classList.toggle("side-popped", !sideVisible);
      sidePane.classList.toggle("scratch-popped", scratchPopped && !statusPopped);
      sidePane.classList.toggle("status-popped", statusPopped && !scratchPopped);
    }

    window.addEventListener("message", (event) => {
      if (event.origin !== window.location.origin) {
        return;
      }
      const data = event.data || {};
      if (handleFileBrowserMessage(data)) {
        return;
      }
      if (data.type === "electroboy-artifact-saved") {
        refreshArtifactPreview({ includeEditing: false });
        recordProjectStatusMessage(`saved: ${data.path || "artifact"}`);
        return;
      }
      if (data.type === "electroboy-artifact-save-complete") {
        const token = data.token || "";
        const pending = pendingArtifactSaves.get(token);
        if (pending) {
          window.clearTimeout(pending.timeout);
          pendingArtifactSaves.delete(token);
          pending.resolve(Boolean(data.ok));
        }
        return;
      }
      if (data.type === "electroboy-creative-open" && data.path) {
        if (data.entry_type === "directory") {
          selectCreativeFolder(data.path);
        } else if (data.entry_type === "corkboard") {
          selectCreativeCorkboard(data.path);
        } else {
          selectCreativeDocument(data.path);
        }
        return;
      }
      if (
        data.type === "electroboy-pane-font-offset" &&
        PANE_FONT_KEYS.includes(data.pane)
      ) {
        paneFontOffsets[data.pane] = clampPaneFontOffset(Number(data.offset || 0));
        applyPaneFontSize(data.pane);
        return;
      }
      if (data.type !== "electroboy-pane-restore" || !data.pane) {
        return;
      }
      const entry = poppedPaneWindows.get(data.pane);
      if (entry) {
        window.clearInterval(entry.poll);
        poppedPaneWindows.delete(data.pane);
      }
      setPanePoppedOut(data.pane, false);
    });

    function contextWorkflowStorageKey(mode = workflowMode) {
      const suffix = mode === CREATIVE_WORKFLOW_MODE
        ? CREATIVE_WORKFLOW_MODE
        : SOFTWARE_WORKFLOW_MODE;
      return `${CONTEXT_STORAGE_KEY}.${suffix}`;
    }

    function splashDismissed() {
      try {
        return window.sessionStorage.getItem(SPLASH_DISMISSED_STORAGE_KEY) === "1";
      } catch (error) {
        return false;
      }
    }

    function openSplash() {
      if (!splashOverlay) {
        return;
      }
      updateSplashImage();
      splashOverlay.hidden = false;
    }

    function updateSplashImage() {
      if (!splashImage) {
        return;
      }
      splashImage.src = creativeModeActive()
        ? CREATIVE_SPLASH_IMAGE_ROUTE
        : SOFTWARE_SPLASH_IMAGE_ROUTE;
    }

    function showSplashIfNeeded() {
      if (!splashOverlay || splashDismissed()) {
        return;
      }
      openSplash();
    }

    function dismissSplash() {
      if (!splashOverlay || splashOverlay.hidden) {
        return;
      }
      splashOverlay.hidden = true;
      try {
        window.sessionStorage.setItem(SPLASH_DISMISSED_STORAGE_KEY, "1");
      } catch (error) {
        return;
      }
    }

    function clearLegacyContextId() {
      try {
        window.sessionStorage.removeItem(CONTEXT_STORAGE_KEY);
      } catch (error) {
        return;
      }
    }

    function storedContextId(mode = workflowMode) {
      try {
        return window.sessionStorage.getItem(contextWorkflowStorageKey(mode)) || "";
      } catch (error) {
        return "";
      }
    }

    function newContextOwnerId() {
      try {
        if (
          window.crypto &&
          typeof window.crypto.randomUUID === "function"
        ) {
          return window.crypto.randomUUID();
        }
      } catch (error) {
        // Fall through to the timestamp/random fallback below.
      }
      return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    }

    function storedBrowserTabId() {
      try {
        return window.sessionStorage.getItem(CONTEXT_TAB_STORAGE_KEY) || "";
      } catch (error) {
        return "";
      }
    }

    function saveBrowserTabId(value) {
      try {
        if (value) {
          window.sessionStorage.setItem(CONTEXT_TAB_STORAGE_KEY, value);
        } else {
          window.sessionStorage.removeItem(CONTEXT_TAB_STORAGE_KEY);
        }
      } catch (error) {
        return;
      }
    }

    function currentBrowserTabId() {
      if (browserTabId) {
        return browserTabId;
      }
      browserTabId = storedBrowserTabId();
      if (!browserTabId) {
        browserTabId = newContextOwnerId();
        saveBrowserTabId(browserTabId);
      }
      return browserTabId;
    }

    function navigationType() {
      try {
        const entries = window.performance.getEntriesByType("navigation");
        return entries.length ? entries[0].type || "" : "";
      } catch (error) {
        return "";
      }
    }

    function contextOwnerKey(value) {
      return `${CONTEXT_OWNER_STORAGE_PREFIX}${value}`;
    }

    function readContextOwner(value) {
      try {
        const raw = window.localStorage.getItem(contextOwnerKey(value));
        return raw ? JSON.parse(raw) : null;
      } catch (error) {
        return null;
      }
    }

    function writeContextOwner(value) {
      try {
        window.localStorage.setItem(
          contextOwnerKey(value),
          JSON.stringify({
            tab_id: currentBrowserTabId(),
            page_id: pageInstanceId,
            updated_at: Date.now(),
          }),
        );
      } catch (error) {
        return;
      }
    }

    function contextOwnerIsFresh(owner) {
      if (!owner || !owner.updated_at) {
        return false;
      }
      return Date.now() - Number(owner.updated_at) < CONTEXT_OWNER_TTL_MS;
    }

    function hasConflictingContextOwner(value) {
      const owner = readContextOwner(value);
      if (!contextOwnerIsFresh(owner)) {
        return false;
      }
      if (owner.page_id === pageInstanceId) {
        return false;
      }
      if (owner.tab_id !== currentBrowserTabId()) {
        return true;
      }
      const type = navigationType();
      return type !== "reload" && type !== "back_forward";
    }

    function refreshContextOwner() {
      if (ownedContextId) {
        writeContextOwner(ownedContextId);
      }
    }

    function releaseContextOwner() {
      const releasedContextId = ownedContextId;
      ownedContextId = "";
      if (contextOwnerTimer) {
        window.clearInterval(contextOwnerTimer);
        contextOwnerTimer = null;
      }
      if (!releasedContextId) {
        return;
      }
      try {
        const owner = readContextOwner(releasedContextId);
        if (owner && owner.page_id === pageInstanceId) {
          window.localStorage.removeItem(contextOwnerKey(releasedContextId));
        }
      } catch (error) {
        return;
      }
    }

    function claimContextOwner(value) {
      if (!value) {
        releaseContextOwner();
        return true;
      }
      if (ownedContextId === value) {
        refreshContextOwner();
        return true;
      }
      if (hasConflictingContextOwner(value)) {
        return false;
      }
      releaseContextOwner();
      ownedContextId = value;
      refreshContextOwner();
      contextOwnerTimer = window.setInterval(
        refreshContextOwner,
        CONTEXT_OWNER_HEARTBEAT_MS,
      );
      return true;
    }

    function saveContextId(value, mode = workflowMode) {
      try {
        clearLegacyContextId();
        if (value) {
          if (!claimContextOwner(value)) {
            return false;
          }
          window.sessionStorage.setItem(contextWorkflowStorageKey(mode), value);
        } else {
          releaseContextOwner();
          window.sessionStorage.removeItem(contextWorkflowStorageKey(mode));
        }
        return true;
      } catch (error) {
        return false;
      }
    }

    function resetWorkflowContextView() {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      closeProgressEventStream();
      closeProjectShellEventStream();
      showProgressPane(false);
      showProjectShellPane(false);
      activationRoot = "";
      activeProjectMode = "none";
      activeProjectRoot = "";
      activeRepositoryName = "";
      registeredRepositories = [];
      projectPath.value = serviceRoot || "";
      workItemState = { collections: [], features: [], bugs: [] };
      stageRunState = {};
      requirementsRunning = false;
      requirementsApproved = false;
      designRunning = false;
      designReviewRunning = false;
      designReviewInteractive = false;
      designApproved = false;
      documentationRunning = false;
      adHocRunning = false;
      projectShellRunning = false;
      agentSessions = [];
      selectedSessionId = "";
      activeAgentKind = "";
      openDocumentTargets = [];
      currentWorkflowStage = "project";
      creativeActiveDocument = "";
      creativeActiveFolder = "";
      creativeEditingPath = "";
      creativeEditingType = "";
      expandedCreativeFolders = new Set();
      creativeLastNotifiedTarget = "";
      creativeTreePayload = null;
      restoredScratchContextId = "";
      projectStatusMessages = [];
      clearAgentOutput();
      clearProgressOutput();
      clearProjectShellOutput();
      hideArtifactPreview();
      hideWorkItemPanel();
      renderSessionSwitcher();
      updateAgentControls();
    }

    async function createContext() {
      const response = await fetch("/api/contexts", { method: "POST" });
      if (!response.ok) {
        projectStatus.textContent = "could not create browser context";
        return;
      }
      const payload = await response.json();
      contextId = payload.context_id || "";
      saveContextId(contextId);
      updateProjectState(payload);
    }

    async function restoreContext() {
      const existingContextId = storedContextId();
      if (!existingContextId || !claimContextOwner(existingContextId)) {
        if (existingContextId) {
          saveContextId("");
        }
        await createContext();
        return;
      }
      contextId = existingContextId;
      const response = await fetch(contextUrl("/api/project"), { cache: "no-store" });
      if (!response.ok) {
        saveContextId("");
        contextId = "";
        await createContext();
        return;
      }
      const payload = await response.json();
      contextId = payload.context_id || existingContextId;
      saveContextId(contextId);
      updateProjectState(payload);
      const session = selectedSession();
      if (session) {
        clearAgentOutput();
        const isInteractive = Boolean(session.interactive);
        if (isInteractive) {
          showProgressPane(false);
          setAgentInputVisible(true);
        } else {
          clearProgressOutput();
          showProgressPane(true);
          setAgentInputVisible(false);
        }
        activeAgentKind = session.kind || "";
        connectSessionEvents(session.session_id);
        if (!isInteractive && session.status === "running") {
          connectProgressEvents();
        }
        sendTerminalResize();
      }
    }

    function updateProjectState(payload, options = {}) {
      const previousActiveProjectRoot = activeProjectRoot;
      const nextActiveProjectRoot = payload.active_project_root || "";
      serviceRoot = payload.service_root || "";
      activationRoot = payload.activation_root || nextActiveProjectRoot || "";
      activeProjectMode = payload.project_mode || (activationRoot ? "project" : "none");
      activeProjectRoot = nextActiveProjectRoot;
      if (previousActiveProjectRoot && previousActiveProjectRoot !== activeProjectRoot) {
        hideArtifactPreview();
        openDocumentTargets = [];
        creativeActiveDocument = "";
        creativeActiveFolder = "";
        creativeEditingPath = "";
        creativeEditingType = "";
        expandedCreativeFolders = new Set();
        creativeLastNotifiedTarget = "";
        creativeTreePayload = null;
        restoredScratchContextId = "";
      }
      activeRepositoryName = payload.active_repository_name || "";
      registeredRepositories = Array.isArray(payload.registered_repositories)
        ? payload.registered_repositories
        : [];
      recentProjects = Array.isArray(payload.recent_projects)
        ? payload.recent_projects
        : [];
      workItemState = payload.work_items || { collections: [], features: [], bugs: [] };
      stageRunState = payload.stage_runs || {};
      requirementsRunning = Boolean(payload.requirements_running);
      requirementsApproved = Boolean(payload.requirements_approved);
      designRunning = Boolean(payload.design_running);
      designReviewRunning = Boolean(payload.design_review_running);
      designReviewInteractive = Boolean(payload.design_review_interactive);
      designApproved = Boolean(payload.design_approved);
      documentationRunning = Boolean(payload.documentation_running);
      adHocRunning = Boolean(payload.ad_hoc_running);
      projectShellRunning = Boolean(payload.project_shell_running);
      agentSessions = Array.isArray(payload.sessions) ? payload.sessions : [];
      selectedSessionId = payload.selected_session_id || selectedSessionId || "";
      syncOpenDocumentTargetsFromSessions();
      if (!agentSessions.some((session) => session.session_id === selectedSessionId)) {
        const selected = agentSessions.find((session) => session.selected) || agentSessions[0];
        selectedSessionId = selected ? selected.session_id : "";
      }
      renderSessionSwitcher();
      updateAgentControls();
      const hasProjectContext = Boolean(activationRoot);
      const hasStageTarget = Boolean(activeProjectRoot);
      const workflowStage = payload.workflow_stage || (hasStageTarget ? "requirements" : "project");
      currentWorkflowStage = workflowStage;
      if (!projectPath.value) {
        projectPath.value = activeProjectRoot || activationRoot || serviceRoot;
      }
      setConnected();
      updateStageNodes(hasProjectContext, hasStageTarget, workflowStage);
      openProject.disabled = hasProjectContext;
      newProject.disabled = hasProjectContext;
      openMetaProject.disabled = hasProjectContext;
      newMetaProject.disabled = hasProjectContext;
      addMetaRepository.disabled = activeProjectMode !== "meta";
      startMetaRepository.disabled =
        activeProjectMode !== "meta" || registeredRepositories.length === 0;
      removeMetaRepository.disabled =
        activeProjectMode !== "meta" || registeredRepositories.length === 0;
      workItemMenuButton.disabled = !hasStageTarget;
      workItemMenuButton.textContent = activeProjectMenuLabel();
      newFeatureWorkItem.disabled = !hasStageTarget;
      switchFeatureWorkItem.disabled = !hasStageTarget;
      newBugWorkItem.disabled = !hasStageTarget;
      switchBugWorkItem.disabled = !hasStageTarget;
      deactivateProject.disabled = !hasProjectContext;
      renderMetaRepositoryMenus();
      renderWorkItemMenus();
      updateRequirementsMenuState();
      updateDesignMenuState();
      updateDesignReviewMenuState();
      updateGenericStageMenuStates();
      updateDocumentMenuState();
      updateCreativeBinderActions();
      if (restoredScratchContextId !== contextId) {
        restoreScratchPad();
      }
      syncProjectShellPane();
      if (creativeModeActive()) {
        applyCreativeWorkspace();
        if (!options.deferCreativeWorkspaceInit) {
          ensureCreativeWorkspaceLoaded();
        }
      } else {
        syncArtifactPreviewWithProject();
      }
      projectStatus.textContent = projectStatusLine();
      queueProjectStatusRefresh();
    }

    function activeProjectMenuLabel() {
      if (!activeProjectRoot) {
        return "Project";
      }
      if (activeProjectMode === "meta" && activeRepositoryName) {
        return activeRepositoryName;
      }
      return basename(activeProjectRoot || activationRoot || "Project");
    }

    function basename(path) {
      const normalized = String(path || "").replace(/[/]+$/, "");
      const parts = normalized.split(/[\/]+/).filter(Boolean);
      return parts.length ? parts[parts.length - 1] : normalized || "Project";
    }

    function recentProjectsForWorkflow() {
      if (creativeModeActive()) {
        return recentProjects.filter((recent) => recent.kind === "creative");
      }
      return recentProjects.filter((recent) => recent.kind !== "creative");
    }

    function recentProjectLabel(recent) {
      const label = recent.label || basename(recent.path || "");
      if (recent.kind === "meta") {
        return `Meta: ${label}`;
      }
      if (recent.kind === "creative") {
        return `Creative: ${label}`;
      }
      return `Project: ${label}`;
    }

    function recentProjectActionsForWorkflow() {
      const entries = recentProjectsForWorkflow();
      if (entries.length === 0) {
        return [
          {
            label: "No recent projects",
            title: "No projects have been opened in this service yet.",
            disabled: true,
          },
        ];
      }
      return entries.map((recent) => ({
        label: recentProjectLabel(recent),
        title: recent.path || recentProjectLabel(recent),
        disabled: Boolean(activationRoot),
        run: () => openRecentProject(recent),
      }));
    }

    async function openRecentProject(recent) {
      const path = String((recent && recent.path) || "").trim();
      if (!path || activationRoot) {
        return;
      }
      projectMode = "open";
      await applyProjectSelection(path);
    }

    function projectStatusLine() {
      if (!activationRoot) {
        return "";
      }
      if (activeProjectMode === "meta") {
        if (activeProjectRoot) {
          return appendWorkItemStatus(
            `meta: ${activationRoot} · active repo: ${activeRepositoryName || activeProjectRoot}`,
          );
        }
        return activeRepositoryName
          ? `meta: ${activationRoot} · active repo: ${activeRepositoryName} (not initialized)`
          : `meta: ${activationRoot} · active repo: none`;
      }
      return appendWorkItemStatus(`active: ${activeProjectRoot || activationRoot}`);
    }

    function appendWorkItemStatus(line) {
      const parts = [];
      const feature = activeWorkItemFeature();
      const bug = activeWorkItemBug();
      if (feature) {
        parts.push(`feature: ${feature.name || feature.slug}`);
      }
      if (bug) {
        parts.push(`bug resolution: ${bug.title || bug.slug}`);
      }
      return parts.length ? `${line} · ${parts.join(" · ")}` : line;
    }

    function workItemFeatures() {
      return Array.isArray(workItemState.features) ? workItemState.features : [];
    }

    function workItemBugs() {
      return Array.isArray(workItemState.bugs) ? workItemState.bugs : [];
    }

    function activeWorkItemFeature() {
      const activeSlug = workItemState.active_feature_slug || "";
      return workItemFeatures().find((feature) => feature.slug === activeSlug) || null;
    }

    function activeWorkItemBug() {
      const activeSlug = workItemState.active_bug_slug || "";
      return workItemBugs().find((bug) => bug.slug === activeSlug) || null;
    }

    function repositoryLabel(repository) {
      const name = String(repository.name || "");
      const path = String(repository.path || "");
      return name || path || "repo";
    }

    function renderMetaRepositoryMenus() {
      renderMetaRepositoryMenu(startMetaRepositorySubmenu, startMetaRepositoryFromMenu);
      renderMetaRepositoryMenu(removeMetaRepositorySubmenu, removeMetaRepositoryFromMenu);
      if (startMetaRepository.disabled) {
        hideSubmenu(startMetaRepositorySubmenu, startMetaRepository);
      }
      if (removeMetaRepository.disabled) {
        hideSubmenu(removeMetaRepositorySubmenu, removeMetaRepository);
      }
    }

    function renderWorkItemMenus() {
      renderFeatureMenu();
      renderBugMenu();
      if (workItemMenuButton.disabled) {
        hideSubmenu(workItemSubmenu, workItemMenuButton);
      }
      if (switchFeatureWorkItem.disabled) {
        hideSubmenu(switchFeatureWorkItemSubmenu, switchFeatureWorkItem);
      }
      if (switchBugWorkItem.disabled) {
        hideSubmenu(switchBugWorkItemSubmenu, switchBugWorkItem);
      }
    }

    function renderFeatureMenu() {
      switchFeatureWorkItemSubmenu.replaceChildren();
      const features = workItemFeatures();
      if (features.length === 0) {
        appendDisabledMenuItem(switchFeatureWorkItemSubmenu, "No features");
        return;
      }
      for (const feature of features) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = featureLabel(feature);
        button.title = feature.title || feature.slug || "";
        button.classList.toggle(
          "active-repo",
          feature.slug === workItemState.active_feature_slug,
        );
        button.addEventListener("click", () => switchFeatureWorkItemContext(feature.slug));
        switchFeatureWorkItemSubmenu.append(button);
      }
    }

    function renderBugMenu() {
      switchBugWorkItemSubmenu.replaceChildren();
      const bugs = workItemBugs();
      if (bugs.length === 0) {
        appendDisabledMenuItem(switchBugWorkItemSubmenu, "No bug resolutions");
        return;
      }
      for (const bug of bugs) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = bug.title || bug.slug || "Bug";
        button.title = bug.reference || bug.slug || "";
        button.classList.toggle("active-repo", bug.slug === workItemState.active_bug_slug);
        button.addEventListener("click", () => switchBugWorkItemContext(bug.slug));
        switchBugWorkItemSubmenu.append(button);
      }
    }

    function appendDisabledMenuItem(menu, label) {
      const emptyButton = document.createElement("button");
      emptyButton.type = "button";
      emptyButton.disabled = true;
      emptyButton.textContent = label;
      menu.append(emptyButton);
    }

    function featureLabel(feature) {
      const label = feature.name || feature.slug || "Feature";
      return feature.parent_slug ? `${label} (subfeature)` : label;
    }

    function renderMetaRepositoryMenu(submenu, handler) {
      submenu.replaceChildren();
      if (registeredRepositories.length === 0) {
        const emptyButton = document.createElement("button");
        emptyButton.type = "button";
        emptyButton.disabled = true;
        emptyButton.textContent = "No repos";
        submenu.append(emptyButton);
        return;
      }
      for (const repository of registeredRepositories) {
        const button = document.createElement("button");
        const label = repositoryLabel(repository);
        const path = String(repository.path || "");
        button.type = "button";
        button.className = "repo-menu-item";
        button.textContent = label;
        button.title = path || label;
        button.classList.toggle("active-repo", label === activeRepositoryName);
        button.addEventListener("click", () => handler(repository));
        submenu.append(button);
      }
    }

    function selectedSession(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "selectedSession", ...args);
    }

    function sessionIsRunning(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "sessionIsRunning", ...args);
    }

    function selectedSessionAcceptsInput(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "selectedSessionAcceptsInput", ...args);
    }

    function updateSessionIndicator(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "updateSessionIndicator", ...args);
    }

    function sessionMetadata(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "sessionMetadata", ...args);
    }

    function documentTargetKey(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "documentTargetKey", ...args);
    }

    function documentTargetLabel(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "documentTargetLabel", ...args);
    }

    function documentTargetForSession(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "documentTargetForSession", ...args);
    }

    function documentationSessionForTarget(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "documentationSessionForTarget", ...args);
    }

    function agentSessionDisplayLabel(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "agentSessionDisplayLabel", ...args);
    }

    function attachableServiceSessions(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "attachableServiceSessions", ...args);
    }

    function serviceSessionDisplayLabel(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "serviceSessionDisplayLabel", ...args);
    }

    function rememberOpenDocumentTarget(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "rememberOpenDocumentTarget", ...args);
    }

    function syncOpenDocumentTargetsFromSessions(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "syncOpenDocumentTargetsFromSessions", ...args);
    }

    function renderDocumentTargetSwitcher(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "renderDocumentTargetSwitcher", ...args);
    }

    function refreshDocumentTargetSwitchers(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "refreshDocumentTargetSwitchers", ...args);
    }

    function renderSessionSwitcher(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "renderSessionSwitcher", ...args);
    }

    function selectAgentSession(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "selectAgentSession", ...args);
    }

    function refreshServiceSessions(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "refreshServiceSessions", ...args);
    }

    function attachAgentSession(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "attachAgentSession", ...args);
    }

    function showSubmenu(submenu, button) {
      if (button.disabled) {
        return;
      }
      submenu.hidden = false;
      button.setAttribute("aria-expanded", "true");
    }

    function hideSubmenu(submenu, button) {
      submenu.hidden = true;
      button.setAttribute("aria-expanded", "false");
    }

    function toggleSubmenu(submenu, button) {
      if (submenu.hidden) {
        showSubmenu(submenu, button);
      } else {
        hideSubmenu(submenu, button);
      }
    }

    function updateStageNodes(hasProjectContext, hasStageTarget, workflowStage) {
      for (const stageNode of stageNodes) {
        const stageId = stageNode.dataset.stage || "";
        const isProject = stageId === "project";
        const isSidecar = stageId === "document";
        const isActive = isProject
          ? !hasProjectContext
          : hasStageTarget && !isSidecar && stageId === workflowStage;
        const isEnabled = isProject || hasStageTarget;
        const isComplete = isProject && hasProjectContext;
        stageNode.disabled = !isEnabled;
        stageNode.setAttribute("aria-disabled", isEnabled ? "false" : "true");
        stageNode.classList.toggle("disabled", !isEnabled);
        stageNode.classList.toggle("available", isEnabled && !isActive && !isComplete);
        stageNode.classList.toggle("active", isActive);
        stageNode.classList.toggle("complete", isComplete);
        stageNode.classList.toggle("sidecar", isSidecar);
      }
    }

    function updateRequirementsMenuState() {
      const hasActiveProject = Boolean(activeProjectRoot);
      const inRequirementsStage = currentWorkflowStage === "requirements";
      setRequirementsStage.disabled = !hasActiveProject || inRequirementsStage;
      startRequirements.disabled =
        !hasActiveProject || !inRequirementsStage || requirementsRunning;
      approveRequirements.disabled = !hasActiveProject || !inRequirementsStage;
      skipRequirementsApproval.disabled = !hasActiveProject || !inRequirementsStage;
    }

    function updateDesignMenuState() {
      const hasActiveProject = Boolean(activeProjectRoot);
      const inDesignStage = currentWorkflowStage === "design";
      setDesignStage.disabled = !hasActiveProject || inDesignStage;
      startDesign.disabled = !hasActiveProject || !inDesignStage || designRunning;
      completeDesign.disabled = !hasActiveProject || !inDesignStage;
    }

    function updateDesignReviewMenuState() {
      const hasActiveProject = Boolean(activeProjectRoot);
      const inDesignReviewStage = currentWorkflowStage === "design-review";
      setDesignReviewStage.disabled = !hasActiveProject || inDesignReviewStage;
      startAutomaticDesignReview.disabled =
        !hasActiveProject || !inDesignReviewStage || designReviewRunning;
      startInteractiveDesignReview.disabled =
        !hasActiveProject || !inDesignReviewStage || designReviewRunning;
      stopDesignReview.disabled =
        !hasActiveProject || !inDesignReviewStage || !designReviewRunning;
      approveDesignReview.disabled = !hasActiveProject || !inDesignReviewStage;
      skipDesignReviewApproval.disabled = !hasActiveProject || !inDesignReviewStage;
    }

    function updateGenericStageMenuStates() {
      updateAuthoringStageMenuState(
        "implementation-plan",
        setImplementationPlanStage,
        startImplementationPlan,
        approveImplementationPlan,
        skipImplementationPlanApproval,
      );
      updateAutomaticStageMenuState(
        "code",
        setCodeStage,
        startAutomaticCode,
        startInteractiveCode,
        stopCode,
        approveCode,
        skipCodeApproval,
      );
      startCodeAdHocAgentButton.disabled = !Boolean(activeProjectRoot);
      startCodeAdHocAgentButton.textContent = adHocRunning
        ? "Focus ad-hoc"
        : "Start ad-hoc";
      updateAuthoringStageMenuState(
        "test-plan",
        setTestPlanStage,
        startTestPlan,
        approveTestPlan,
        skipTestPlanApproval,
      );
      updateAutomaticStageMenuState(
        "validate",
        setValidateStage,
        startAutomaticValidate,
        startInteractiveValidate,
        stopValidate,
        approveValidate,
        skipValidateApproval,
      );
    }

    function updateAuthoringStageMenuState(
      stage,
      setStageButton,
      startButton,
      approveButton,
      skipButton,
    ) {
      const hasActiveProject = Boolean(activeProjectRoot);
      const inStage = currentWorkflowStage === stage;
      const runState = genericStageRun(stage);
      setStageButton.disabled = !hasActiveProject || inStage;
      startButton.disabled = !hasActiveProject || !inStage || runState.running;
      approveButton.disabled = !hasActiveProject || !inStage;
      skipButton.disabled = !hasActiveProject || !inStage;
    }

    function updateAutomaticStageMenuState(
      stage,
      setStageButton,
      startAutomaticButton,
      startInteractiveButton,
      stopButton,
      approveButton,
      skipButton,
    ) {
      const hasActiveProject = Boolean(activeProjectRoot);
      const inStage = currentWorkflowStage === stage;
      const runState = genericStageRun(stage);
      setStageButton.disabled = !hasActiveProject || inStage;
      startAutomaticButton.disabled =
        !hasActiveProject || !inStage || runState.running;
      startInteractiveButton.disabled =
        !hasActiveProject || !inStage || runState.running;
      stopButton.disabled = !hasActiveProject || !inStage || !runState.running;
      approveButton.disabled = !hasActiveProject || !inStage;
      skipButton.disabled = !hasActiveProject || !inStage;
    }

    function genericStageRun(stage) {
      return stageRunState[stage] || { started: false, running: false, interactive: false };
    }

    function updateDocumentMenuState() {
      const hasActiveProject = Boolean(activeProjectRoot);
      createDocumentTarget.disabled = !hasActiveProject;
      addDocumentTarget.disabled = !hasActiveProject;
      customDocumentName.disabled = !hasActiveProject;
      renderDocumentTargets();
      refreshStageActionPanel();
    }

    function refreshStageActionPanel() {
      renderStageActionPanel();
    }

    function showStageActionPanel(stageId) {
      expandedWorkflowStages.add(stageId);
      hideStageMenus();
      setWorkflowSideSheetCollapsed(false);
      renderStageActionPanel();
    }

    function hideStageActionPanel() {
      expandedWorkflowStages.clear();
      expandedProjectActionGroups.clear();
      stageActionBody.replaceChildren();
    }

    function stageActionName(stageId) {
      if (stageId === "project") {
        return "Project";
      }
      return stageId;
    }

    function renderStageActionPanel() {
      stageActionBody.replaceChildren();
      for (const stageNode of stageNodes) {
        const stageId = stageNode.dataset.stage || "";
        if (!stageId) {
          continue;
        }
        stageActionBody.append(stageActionGroup(stageId, stageNode));
      }
    }

    function stageActionGroup(stageId, stageNode) {
      const group = document.createElement("div");
      group.className = "stage-action-group";

      const trigger = document.createElement("button");
      trigger.type = "button";
      trigger.className = "stage-action-stage";
      const isExpanded = expandedWorkflowStages.has(stageId);
      trigger.classList.toggle("active", stageNode.classList.contains("active"));
      trigger.classList.toggle("complete", stageNode.classList.contains("complete"));
      trigger.classList.toggle("expanded", isExpanded);
      trigger.disabled = stageNode.disabled;
      trigger.title = STAGE_DESCRIPTIONS[stageId] || stageId;
      trigger.setAttribute("aria-expanded", isExpanded ? "true" : "false");

      const label = document.createElement("span");
      label.className = "stage-action-label";
      label.textContent = stageActionName(stageId);
      const chevron = document.createElement("span");
      chevron.className = "stage-action-chevron";
      chevron.setAttribute("aria-hidden", "true");
      trigger.append(label, chevron);
      trigger.addEventListener("click", () => toggleStageActionGroup(stageId));
      group.append(trigger);

      if (isExpanded) {
        const list = document.createElement("div");
        list.className = "stage-action-list";
        list.setAttribute("role", "group");
        if (stageId === "document") {
          renderDocumentActionPanel(list);
        } else {
          renderStageActionList(list, stageActions(stageId));
        }
        group.append(list);
      }
      return group;
    }

    function toggleStageActionGroup(stageId) {
      const stageNode = stageNodes.find((node) => node.dataset.stage === stageId);
      if (!stageNode || stageNode.disabled) {
        return;
      }
      if (expandedWorkflowStages.has(stageId)) {
        expandedWorkflowStages.delete(stageId);
      } else {
        expandedWorkflowStages.add(stageId);
      }
      setWorkflowSideSheetCollapsed(false);
      renderStageActionPanel();
    }

    function renderStageActionList(container, actions) {
      for (const action of actions) {
        if (action.subgroup) {
          container.append(stageActionSubgroup(action));
          continue;
        }
        if (action.heading) {
          const heading = document.createElement("div");
          heading.className = "stage-action-heading";
          heading.textContent = action.heading;
          container.append(heading);
          continue;
        }
        container.append(stageActionButton(action));
      }
    }

    function stageActionSubgroup(action) {
      const group = document.createElement("div");
      group.className = "stage-action-subgroup";
      const isExpanded = expandedProjectActionGroups.has(action.subgroup);

      const trigger = document.createElement("button");
      trigger.type = "button";
      trigger.className = "stage-action-subgroup-trigger";
      trigger.classList.toggle("expanded", isExpanded);
      trigger.disabled = Boolean(action.disabled);
      trigger.title = action.title || action.label;
      trigger.setAttribute("aria-expanded", isExpanded ? "true" : "false");

      const label = document.createElement("span");
      label.className = "stage-action-label";
      label.textContent = action.label;
      const chevron = document.createElement("span");
      chevron.className = "stage-action-chevron";
      chevron.setAttribute("aria-hidden", "true");
      trigger.append(label, chevron);
      trigger.addEventListener("click", () => toggleProjectActionGroup(action.subgroup));
      group.append(trigger);

      if (isExpanded) {
        const list = document.createElement("div");
        list.className = "stage-action-subgroup-list";
        list.setAttribute("role", "group");
        renderStageActionList(list, action.actions || []);
        group.append(list);
      }
      return group;
    }

    function toggleProjectActionGroup(groupId) {
      if (expandedProjectActionGroups.has(groupId)) {
        expandedProjectActionGroups.delete(groupId);
      } else {
        expandedProjectActionGroups.add(groupId);
      }
      renderStageActionPanel();
    }

    function stageActionButton(action) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "stage-action-button";
      if (action.primary) {
        button.classList.add("primary");
      }
      button.textContent = action.label;
      button.title = action.title || action.label;
      button.disabled = Boolean(
        typeof action.disabled === "function" ? action.disabled() : action.disabled,
      );
      button.addEventListener("click", () => runStageAction(action));
      return button;
    }

    function runStageAction(action) {
      if (!action || typeof action.run !== "function") {
        return;
      }
      const disabled = Boolean(
        typeof action.disabled === "function" ? action.disabled() : action.disabled,
      );
      if (disabled) {
        return;
      }
      Promise.resolve(action.run()).catch((error) => {
        appendOutput(`action failed: ${error}\n`, "error");
      });
    }

    function stageActions(stageId) {
      return window.ElectroBoyFrontend.stageActions(
        workflowMode,
        stageId,
      );
    }

    function renderDocumentActionPanel(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "renderDocumentActionPanel", ...args);
    }

    function allDocumentTargets(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "allDocumentTargets", ...args);
    }

    function renderDocumentTargets(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "renderDocumentTargets", ...args);
    }

    function documentTargetFromInput(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "documentTargetFromInput", ...args);
    }

    function documentTargetFromSelectedPath(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "documentTargetFromSelectedPath", ...args);
    }

    function registerDocumentTarget(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "registerDocumentTarget", ...args);
    }

    function launchDocumentTarget(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "launchDocumentTarget", ...args);
    }

    function selectOpenDocumentTarget(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "selectOpenDocumentTarget", ...args);
    }

    function startCustomDocumentTargetFromValue(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "startCustomDocumentTargetFromValue", ...args);
    }

    function addCustomDocumentTarget(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "addCustomDocumentTarget", ...args);
    }

    function artifactKindForPane(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "artifactKindForPane", ...args);
    }

    function artifactRouteUrl(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "artifactRouteUrl", ...args);
    }

    function artifactPreviewUrl(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "artifactPreviewUrl", ...args);
    }

    function artifactEditUrl(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "artifactEditUrl", ...args);
    }

    function artifactPaneSupportsModeSwitch(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "artifactPaneSupportsModeSwitch", ...args);
    }

    function artifactPaneSupportsDocumentExport(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "artifactPaneSupportsDocumentExport", ...args);
    }

    function artifactPaneSupportsDocumentZoom(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "artifactPaneSupportsDocumentZoom", ...args);
    }

    function artifactPreviewsForStage(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "artifactPreviewsForStage", ...args);
    }

    function setArtifactCompatibilityState(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "setArtifactCompatibilityState", ...args);
    }

    function showArtifactPreviews(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "showArtifactPreviews", ...args);
    }

    function showStageArtifactPreview(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "showStageArtifactPreview", ...args);
    }

    function showArtifactPreview(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "showArtifactPreview", ...args);
    }

    function showDocumentPreview(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "showDocumentPreview", ...args);
    }

    function applyCreativeWorkspace(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "applyCreativeWorkspace", ...args);
    }

    function restoreSoftwareWorkspace(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "restoreSoftwareWorkspace", ...args);
    }

    function updateCreativeBinderActions(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "updateCreativeBinderActions", ...args);
    }

    function renderCreativeRecentProjects(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "renderCreativeRecentProjects", ...args);
    }

    function updateCreativeActionGroup(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "updateCreativeActionGroup", ...args);
    }

    function toggleCreativeActionGroup(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "toggleCreativeActionGroup", ...args);
    }

    function refreshCreativeBinder(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "refreshCreativeBinder", ...args);
    }

    function firstCreativeMarkdown(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "firstCreativeMarkdown", ...args);
    }

    function showCreativeTreeMessage(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "showCreativeTreeMessage", ...args);
    }

    function renderCreativeTree(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "renderCreativeTree", ...args);
    }

    function showCreativeCorkboard(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "showCreativeCorkboard", ...args);
    }

    function selectCreativeFolder(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "selectCreativeFolder", ...args);
    }

    function selectCreativeCorkboard(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "selectCreativeCorkboard", ...args);
    }

    function showCreativeDocument(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "showCreativeDocument", ...args);
    }

    function selectCreativeDocument(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "selectCreativeDocument", ...args);
    }

    function creativeAgentSession(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "creativeAgentSession", ...args);
    }

    function creativeAgentRunning(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "creativeAgentRunning", ...args);
    }

    function activeCreativeTarget(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "activeCreativeTarget", ...args);
    }

    function creativeTargetKey(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "creativeTargetKey", ...args);
    }

    function creativeTargetContextLines(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "creativeTargetContextLines", ...args);
    }

    function notifyCreativeAgentTargetSwitch(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "notifyCreativeAgentTargetSwitch", ...args);
    }

    function creativePromptMessage(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "creativePromptMessage", ...args);
    }

    function loadCreativeScratchPad(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "loadCreativeScratchPad", ...args);
    }

    function queueCreativeScratchPadSave(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "queueCreativeScratchPadSave", ...args);
    }

    function saveCreativeScratchPad(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "saveCreativeScratchPad", ...args);
    }

    function initializeCreativeWorkspace(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "initializeCreativeWorkspace", ...args);
    }

    function ensureCreativeWorkspaceLoaded(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "ensureCreativeWorkspaceLoaded", ...args);
    }

    function creativeEntryChildren(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "creativeEntryChildren", ...args);
    }

    function findCreativeEntry(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "findCreativeEntry", ...args);
    }

    function uniqueCreativeChildPath(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "uniqueCreativeChildPath", ...args);
    }

    function creativeParentPath(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "creativeParentPath", ...args);
    }

    function creativePathIsCorkboard(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "creativePathIsCorkboard", ...args);
    }

    function creativePathIsInside(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "creativePathIsInside", ...args);
    }

    function remapCreativePath(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "remapCreativePath", ...args);
    }

    function beginCreativeRename(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "beginCreativeRename", ...args);
    }

    function cancelCreativeRename(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "cancelCreativeRename", ...args);
    }

    function normalizedCreativeName(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "normalizedCreativeName", ...args);
    }

    function finishCreativeRename(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "finishCreativeRename", ...args);
    }

    function createCreativeFolderInline(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "createCreativeFolderInline", ...args);
    }

    function createCreativeDocumentInline(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "createCreativeDocumentInline", ...args);
    }

    function createCreativeCorkboardInline(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "createCreativeCorkboardInline", ...args);
    }

    function deleteCreativeEntry(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "deleteCreativeEntry", ...args);
    }

    function startCreativeWritingAgent(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("creative-writing", "startCreativeWritingAgent", ...args);
    }

    function markArtifactFrameLoading(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "markArtifactFrameLoading", ...args);
    }

    function renderArtifactPreviewItems(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "renderArtifactPreviewItems", ...args);
    }

    function artifactFrameForItem(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "artifactFrameForItem", ...args);
    }

    function requestArtifactEditorSave(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "requestArtifactEditorSave", ...args);
    }

    function setArtifactPreviewEditing(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "setArtifactPreviewEditing", ...args);
    }

    function popOutArtifactPreview(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "popOutArtifactPreview", ...args);
    }

    function fileBrowserUrl(...args) {
      return window.ElectroBoyFrontend.invokeModule("file-browser", "fileBrowserUrl", ...args);
    }

    function openProjectBrowser(...args) {
      return window.ElectroBoyFrontend.invokeModule("file-browser", "openProjectBrowser", ...args);
    }

    function openLinkFileBrowser(...args) {
      return window.ElectroBoyFrontend.invokeModule("file-browser", "openLinkFileBrowser", ...args);
    }

    function openDocumentFileBrowser(...args) {
      return window.ElectroBoyFrontend.invokeModule("file-browser", "openDocumentFileBrowser", ...args);
    }

    function openNewDocumentFileBrowser(...args) {
      return window.ElectroBoyFrontend.invokeModule("file-browser", "openNewDocumentFileBrowser", ...args);
    }

    function handleFileBrowserMessage(...args) {
      return window.ElectroBoyFrontend.invokeModule("file-browser", "handleFileBrowserMessage", ...args);
    }

    function hideArtifactPreview(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "hideArtifactPreview", ...args);
    }

    function refreshArtifactPreview(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "refreshArtifactPreview", ...args);
    }

    function artifactEventUrl(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "artifactEventUrl", ...args);
    }

    function connectArtifactEvents(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "connectArtifactEvents", ...args);
    }

    function closeArtifactEventStream(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "closeArtifactEventStream", ...args);
    }

    function stageIsRunning(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "stageIsRunning", ...args);
    }

    function syncArtifactPreviewWithProject(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "syncArtifactPreviewWithProject", ...args);
    }

    async function refreshProject() {
      if (!contextId) {
        return;
      }
      const response = await fetch(contextUrl("/api/project"), { cache: "no-store" });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      updateProjectState(payload);
    }

    function queueProjectStatusRefresh(delay = 120) {
      window.clearTimeout(statusRefreshTimer);
      const sequence = ++statusRefreshSequence;
      if (creativeModeActive()) {
        renderCreativeProjectStatus();
        return;
      }
      if (!contextId || !activationRoot) {
        projectStatusOutput.textContent = "no active project";
        return;
      }
      projectStatusOutput.textContent = "refreshing status...\n";
      statusRefreshTimer = window.setTimeout(
        () => refreshProjectStatus(sequence),
        delay,
      );
    }

    async function refreshProjectStatus(sequence = ++statusRefreshSequence) {
      if (creativeModeActive()) {
        renderCreativeProjectStatus();
        return;
      }
      if (!contextId || !activationRoot) {
        if (sequence === statusRefreshSequence) {
          projectStatusOutput.textContent = "no active project";
        }
        return;
      }
      projectStatusOutput.textContent = "refreshing status...\n";
      const response = await fetch(contextUrl("/api/project/status"), {
        cache: "no-store",
      });
      const payload = await response.json().catch(() => ({ error: "status failed" }));
      if (sequence !== statusRefreshSequence) {
        return;
      }
      if (!response.ok) {
        projectStatusOutput.textContent = `${payload.error || "status failed"}\n`;
        return;
      }
      projectStatusOutput.textContent = payload.output || "status: none\n";
    }

    function selectWorkflowStage(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "selectWorkflowStage", ...args);
    }

    function setWorkflowStageFromMenu(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "setWorkflowStageFromMenu", ...args);
    }

    function approveRequirementsStage(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "approveRequirementsStage", ...args);
    }

    function skipRequirementsApprovalStage(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "skipRequirementsApprovalStage", ...args);
    }

    async function browseDirectory(path = projectPath.value || ".", mode = currentBrowserMode) {
      currentBrowserMode = mode;
      currentSelectedFile = "";
      fileBrowser.hidden = false;
      browserPath.value = path;
      selectDirectory.textContent = mode === "link" ? "Insert" : "Select";
      selectDirectory.disabled = mode === "link";
      fileBrowser.setAttribute(
        "aria-label",
        mode === "link" ? "File browser" : "Directory browser",
      );
      directoryList.replaceChildren();
      const modeParameter = mode === "link" ? "&mode=file" : "";
      const response = await fetch(
        `/api/files/browse?path=${encodeURIComponent(path)}${modeParameter}`,
        { cache: "no-store" },
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({ error: "browse failed" }));
        projectStatus.textContent = payload.error || "browse failed";
        return;
      }
      const payload = await response.json();
      currentBrowsePath = payload.path;
      currentBrowseParent = payload.parent || "";
      browserPath.value = payload.path;
      upDirectory.disabled = !currentBrowseParent;
      directoryList.replaceChildren();
      for (const entry of payload.entries) {
        directoryList.appendChild(
          directoryButton(entry.name, entry.path, entry.type || "directory"),
        );
      }
    }

    function directoryButton(label, path, type = "directory") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `directory-entry ${type === "file" ? "file" : "directory"}`;
      button.textContent = label;
      button.title = path;
      button.addEventListener("click", () => {
        if (type === "file") {
          selectFileForInput(path, button);
        } else {
          browseDirectory(path, currentBrowserMode);
        }
      });
      return button;
    }

    function selectFileForInput(path, button) {
      currentSelectedFile = path;
      for (const entry of directoryList.querySelectorAll(".directory-entry")) {
        entry.classList.toggle("selected", entry === button);
      }
      selectDirectory.disabled = false;
    }

    function showProjectPanel(mode) {
      const isMetaAction = mode === "meta-add" || mode === "meta-start";
      if (activationRoot && !isMetaAction) {
        return;
      }
      if (isMetaAction && activeProjectMode !== "meta") {
        return;
      }
      projectMode = mode;
      hideStageMenus();
      hideWorkItemPanel();
      projectPanel.hidden = false;
      activateProject.textContent = projectActionLabel(mode);
      projectStatus.textContent = projectStatusLine();
      projectPath.focus();
    }

    function projectActionLabel(mode) {
      if (mode === "new") {
        return "Create";
      }
      if (mode === "meta-new") {
        return "Create meta";
      }
      if (mode === "meta-add") {
        return "Add repo";
      }
      if (mode === "meta-start") {
        return "Start repo";
      }
      return "Activate";
    }

    function selectCurrentDirectory() {
      if (currentBrowserMode === "link") {
        insertSelectedFilePath();
        return;
      }
      if (!currentBrowsePath) {
        return;
      }
      projectPath.value = currentBrowsePath;
      projectStatus.textContent = `selected: ${currentBrowsePath}`;
      fileBrowser.hidden = true;
      projectPath.focus();
    }

    function insertSelectedFilePath() {
      if (!currentSelectedFile) {
        return;
      }
      insertTextAtCursor(currentSelectedFile);
      fileBrowser.hidden = true;
      currentSelectedFile = "";
      agentInput.focus();
    }

    function insertTextAtCursor(text) {
      const start = agentInput.selectionStart ?? agentInput.value.length;
      const end = agentInput.selectionEnd ?? start;
      const value = agentInput.value;
      const needsLeadingSpace = start > 0 && !/\s/.test(value[start - 1]);
      const insertion = `${needsLeadingSpace ? " " : ""}${text}`;
      agentInput.value = `${value.slice(0, start)}${insertion}${value.slice(end)}`;
      const cursor = start + insertion.length;
      agentInput.setSelectionRange(cursor, cursor);
    }

    async function applyProjectSelection(selectedPathOverride = "") {
      const endpoint = projectEndpoint(projectMode);
      const selectedPath = String(selectedPathOverride || projectPath.value).trim();
      if (!selectedPath) {
        const message = projectMode === "meta-start"
          ? "choose a repository name or path first"
          : "choose a project directory first";
        projectStatus.textContent = message;
        appendOutput(`${message}\n`, "error");
        return;
      }
      projectPath.value = selectedPath;
      activateProject.disabled = true;
      projectStatus.textContent = projectPendingLabel(projectMode, selectedPath);
      let response;
      try {
        response = await fetch(contextUrl(endpoint), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(projectRequestBody(projectMode, selectedPath)),
        });
      } catch (error) {
        projectStatus.textContent = `activation request failed: ${error}`;
        appendOutput(`activation request failed: ${error}\n`, "error");
        activateProject.disabled = false;
        return;
      }
      const payload = await response.json().catch(() => ({ error: "project update failed" }));
      if (!response.ok) {
        const message = payload.error || "project update failed";
        projectStatus.textContent = message;
        appendOutput(`${message}\n`, "error");
        activateProject.disabled = false;
        return;
      }
      const nextProjectRoot = payload.active_project_root || payload.activation_root || "";
      if (nextProjectRoot && nextProjectRoot !== activeProjectRoot) {
        projectStatusMessages = [];
      }
      activeProjectRoot = payload.active_project_root || "";
      activationRoot = payload.activation_root || activeProjectRoot;
      projectPath.value = activeProjectRoot || activationRoot;
      fileBrowser.hidden = true;
      projectPanel.hidden = true;
      hideStageMenus();
      recordProjectStatusMessage(`${payload.status}: ${activationRoot || activeProjectRoot}`);
      updateProjectState(payload, { deferCreativeWorkspaceInit: creativeModeActive() });
      if (creativeModeActive()) {
        await ensureCreativeWorkspaceLoaded();
      }
      activateProject.disabled = false;
    }

    function projectEndpoint(mode) {
      if (creativeModeActive() && mode === "open") {
        return "/api/creative/project/open";
      }
      if (creativeModeActive() && mode === "new") {
        return "/api/creative/project/new";
      }
      if (mode === "new") {
        return "/api/project/new";
      }
      if (mode === "meta-new") {
        return "/api/meta/init";
      }
      if (mode === "meta-add") {
        return "/api/meta/add";
      }
      if (mode === "meta-start") {
        return "/api/meta/start";
      }
      return "/api/project/open";
    }

    function projectRequestBody(mode, selectedPath) {
      if (mode === "meta-start") {
        return { repository: selectedPath };
      }
      return { path: selectedPath };
    }

    function projectPendingLabel(mode, selectedPath) {
      if (mode === "new") {
        return `creating: ${selectedPath}`;
      }
      if (mode === "meta-new") {
        return `creating meta-project: ${selectedPath}`;
      }
      if (mode === "meta-add") {
        return `adding repo: ${selectedPath}`;
      }
      if (mode === "meta-start") {
        return `starting repo: ${selectedPath}`;
      }
      return `activating: ${selectedPath}`;
    }

    function repositoryReference(repository) {
      return String(repository.name || repository.path || "").trim();
    }

    async function startMetaRepositoryFromMenu(repository) {
      await applyMetaRepositoryAction("/api/meta/start", repository, "starting repo");
    }

    async function removeMetaRepositoryFromMenu(repository) {
      const reference = repositoryReference(repository);
      if (!reference) {
        return;
      }
      const label = repositoryLabel(repository);
      const shouldRemove = window.confirm(
        `Remove ${label} from this meta-project? Repository files will not be deleted.`,
      );
      if (!shouldRemove) {
        return;
      }
      await applyMetaRepositoryAction("/api/meta/remove", repository, "removing repo");
    }

    async function applyMetaRepositoryAction(endpoint, repository, pendingLabel) {
      const reference = repositoryReference(repository);
      if (!reference) {
        return;
      }
      hideStageMenus();
      projectStatus.textContent = `${pendingLabel}: ${reference}`;
      let response;
      try {
        response = await fetch(contextUrl(endpoint), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repository: reference }),
        });
      } catch (error) {
        projectStatus.textContent = `repo update failed: ${error}`;
        appendOutput(`repo update failed: ${error}\n`, "error");
        return;
      }
      const payload = await response.json().catch(() => ({ error: "repo update failed" }));
      if (!response.ok) {
        const message = payload.error || "repo update failed";
        projectStatus.textContent = message;
        appendOutput(`${message}\n`, "error");
        return;
      }
      activeProjectRoot = payload.active_project_root || "";
      activationRoot = payload.activation_root || activationRoot;
      projectPath.value = activeProjectRoot || activationRoot;
      clearAgentOutput();
      recordProjectStatusMessage(`${payload.status}: ${reference}`);
      updateProjectState(payload);
    }

    function showWorkItemPanel(mode) {
      if (!activeProjectRoot) {
        return;
      }
      workItemMode = mode;
      hideStageMenus();
      projectPanel.hidden = true;
      workItemPanel.hidden = false;
      workItemTitle.value = "";
      workItemName.value = "";
      workItemBranchCheckbox.checked = false;
      hideWorkItemRecovery();
      workItemName.hidden = mode === "bug-new";
      workItemBranchLabel.hidden = false;
      if (mode === "bug-new") {
        workItemTitle.placeholder = "Bug issue URL or reference";
        workItemName.placeholder = "";
        applyWorkItem.textContent = "Add bug resolution";
        workItemStatus.textContent = "Start a focused bug-resolution workflow.";
      } else {
        workItemTitle.placeholder = "Feature title or issue URL";
        workItemName.placeholder = "artifact name (optional)";
        applyWorkItem.textContent = "Add feature";
        workItemStatus.textContent = "Start or register feature work.";
      }
      workItemTitle.focus();
    }

    function hideWorkItemPanel() {
      workItemPanel.hidden = true;
      hideWorkItemRecovery();
      workItemMode = "";
    }

    async function applyWorkItemSelection() {
      if (!activeProjectRoot || !workItemMode) {
        return;
      }
      const title = workItemTitle.value.trim();
      if (!title) {
        workItemStatus.textContent = "enter a title or reference first";
        return;
      }
      if (!confirmWorkItemAgentStop()) {
        return;
      }
      hideWorkItemRecovery();
      applyWorkItem.disabled = true;
      workItemStatus.textContent = workItemPendingLabel();
      const endpoint = workItemEndpoint();
      let body = workItemRequestBody(title);
      let response;
      try {
        response = await fetch(contextUrl(endpoint), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      } catch (error) {
        workItemStatus.textContent = `work item update failed: ${error}`;
        applyWorkItem.disabled = false;
        return;
      }
      let payload = await response.json().catch(() => ({ error: "work item failed" }));
      if (!response.ok && shouldRetryWithSubrepoStash(payload, body)) {
        body = { ...body, stash_subrepo_changes: true };
        workItemStatus.textContent = "stashing nested repository changes";
        try {
          response = await fetch(contextUrl(endpoint), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
        } catch (error) {
          workItemStatus.textContent = `work item update failed: ${error}`;
          applyWorkItem.disabled = false;
          return;
        }
        payload = await response.json().catch(() => ({ error: "work item failed" }));
      }
      if (!response.ok) {
        const message = payload.error || "work item failed";
        workItemStatus.textContent = message;
        appendOutput(`${message}\n`, "error");
        if (recoverableWorkItemError(message, payload)) {
          showWorkItemRecovery();
        } else {
          hideWorkItemRecovery();
        }
        applyWorkItem.disabled = false;
        return;
      }
      hideWorkItemRecovery();
      hideWorkItemPanel();
      recordProjectStatusMessage(`${payload.status}: ${payload.label || title}`);
      if (payload.terminated_agent) {
        recordProjectStatusMessage("stopped running agent for work-item context");
      }
      if (payload.output) {
        appendOutput(`${payload.output}\n`, "system");
      }
      updateProjectState(payload);
      applyWorkItem.disabled = false;
    }

    function shouldRetryWithSubrepoStash(payload, body) {
      if (
        !body.branch ||
        body.stash_subrepo_changes ||
        !payload.stash_subrepo_changes_required
      ) {
        return false;
      }
      return window.confirm(
        "Nested repositories have tracked changes.\n\nStash those changes before switching all repositories to the new branch?",
      );
    }

    function workItemEndpoint() {
      if (workItemMode === "bug-new") {
        return "/api/work-items/bugs";
      }
      return "/api/work-items/features";
    }

    function workItemRequestBody(title) {
      if (workItemMode === "bug-new") {
        return {
          issue_reference: title,
          branch: workItemBranchCheckbox.checked,
        };
      }
      return {
        title,
        name: workItemName.value.trim(),
        branch: workItemBranchCheckbox.checked,
      };
    }

    function workItemPendingLabel() {
      if (workItemMode === "bug-new") {
        return "starting bug-resolution workflow";
      }
      return "starting feature workflow";
    }

    async function switchFeatureWorkItemContext(slug) {
      await switchWorkItemContext(
        "/api/work-items/features/switch",
        { slug },
        "switched feature",
      );
    }

    async function switchBugWorkItemContext(slug) {
      await switchWorkItemContext(
        "/api/work-items/bugs/switch",
        { slug },
        "switched bug resolution",
      );
    }

    async function switchWorkItemContext(endpoint, body, successLabel) {
      if (!activeProjectRoot) {
        return;
      }
      if (!confirmWorkItemAgentStop()) {
        return;
      }
      hideWorkItemRecovery();
      hideStageMenus();
      const response = await fetch(contextUrl(endpoint), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => ({ error: "switch failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "switch failed"}\n`, "error");
        if (recoverableWorkItemError(payload.error || "switch failed", payload)) {
          showWorkItemRecovery();
        }
        return;
      }
      appendOutput(`${successLabel}: ${payload.label || ""}\n`, "system");
      if (payload.terminated_agent) {
        appendOutput("stopped running agent for work-item context\n", "system");
      }
      updateProjectState(payload);
    }

    function confirmWorkItemAgentStop() {
      if (!agentProcessRunning()) {
        return true;
      }
      return window.confirm(
        "A workflow agent is running in this browser context.\n\nStarting or switching work items will stop that agent. Continue?",
      );
    }

    function showWorkItemRecovery() {
      workItemRecovery.hidden = false;
    }

    function hideWorkItemRecovery() {
      workItemRecovery.hidden = true;
    }

    function recoverableWorkItemError(message, payload = {}) {
      if (payload.stash_subrepo_changes_required) {
        return true;
      }
      return /\b(branch|checkout|switch|dirty|uncommitted|tracked changes|merge|rebase|conflict|index\.lock|permission|stash|worktree|repository)\b/i
        .test(message || "");
    }

    async function deactivateActiveProject() {
      if (!activationRoot) {
        return;
      }
      const previousProject = activationRoot;
      const response = await fetch(contextUrl("/api/project/deactivate"), {
        method: "POST",
      });
      const payload = await response.json().catch(() => ({ error: "deactivate failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "deactivate failed"}\n`, "error");
        return;
      }
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      closeProgressEventStream();
      closeProjectShellEventStream();
      showProgressPane(false);
      showProjectShellPane(false);
      activationRoot = "";
      activeProjectMode = "none";
      activeProjectRoot = "";
      activeRepositoryName = "";
      registeredRepositories = [];
      workItemState = { collections: [], features: [], bugs: [] };
      projectPath.value = serviceRoot;
      projectMenu.hidden = true;
      requirementsMenu.hidden = true;
      hideStageActionPanel();
      hideStageMenus();
      hideStageMenus();
      documentMenu.hidden = true;
      agentInput.disabled = true;
      interruptAgent.disabled = true;
      startRequirements.disabled = false;
      requirementsRunning = false;
      designRunning = false;
      designReviewRunning = false;
      stageRunState = {};
      documentationRunning = false;
      adHocRunning = false;
      projectShellRunning = false;
      projectShellPaneDismissed = false;
      agentSessions = [];
      selectedSessionId = "";
      renderSessionSwitcher();
      activeAgentKind = "";
      agentInput.value = "";
      setAgentInputVisible(true);
      clearAgentOutput();
      clearProgressOutput();
      clearProjectShellOutput();
      hideArtifactPreview();
      hideWorkItemPanel();
      creativeActiveDocument = "";
      creativeActiveFolder = "";
      creativeEditingPath = "";
      creativeEditingType = "";
      expandedCreativeFolders = new Set();
      creativeLastNotifiedTarget = "";
      creativeTreePayload = null;
      recordProjectStatusMessage(`deactivated: ${previousProject}`);
      updateProjectState(payload);
    }

    function connectAgentEvents(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "connectAgentEvents", ...args);
    }

    function connectSessionEvents(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "connectSessionEvents", ...args);
    }

    function connectProgressEvents(...args) {
      return window.ElectroBoyFrontend.invokeModule("progress", "connectProgressEvents", ...args);
    }

    function closeAgentEventStream(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "closeAgentEventStream", ...args);
    }

    function closeProgressEventStream(...args) {
      return window.ElectroBoyFrontend.invokeModule("progress", "closeProgressEventStream", ...args);
    }

    function agentProcessRunning(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "agentProcessRunning", ...args);
    }

    function updateAgentControls(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "updateAgentControls", ...args);
    }

    function setAgentRunning(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "setAgentRunning", ...args);
    }

    function setRequirementsRunning(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "setRequirementsRunning", ...args);
    }

    function runStageAgent(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "runStageAgent", ...args);
    }

    function startAdHocAgent(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "startAdHocAgent", ...args);
    }

    function runRequirementsAgent(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "runRequirementsAgent", ...args);
    }

    function startRequirementsAgent(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "startRequirementsAgent", ...args);
    }

    function completeRequirementsAgent(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "completeRequirementsAgent", ...args);
    }

    function startDesignAgent(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "startDesignAgent", ...args);
    }

    function completeDesignAgent(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "completeDesignAgent", ...args);
    }

    function startAutomaticDesignReviewAgent(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "startAutomaticDesignReviewAgent", ...args);
    }

    function startInteractiveDesignReviewAgent(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "startInteractiveDesignReviewAgent", ...args);
    }

    function stopDesignReviewAgent(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "stopDesignReviewAgent", ...args);
    }

    function completeDesignReviewAgent(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "completeDesignReviewAgent", ...args);
    }

    function approveDesignReviewStage(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "approveDesignReviewStage", ...args);
    }

    function skipDesignReviewApprovalStage(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "skipDesignReviewApprovalStage", ...args);
    }

    function startGenericStageAgent(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "startGenericStageAgent", ...args);
    }

    function stopGenericStageAgent(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "stopGenericStageAgent", ...args);
    }

    function approveGenericStage(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "approveGenericStage", ...args);
    }

    function skipGenericStageApproval(...args) {
      return window.ElectroBoyFrontend.invokeWorkflow("software", "skipGenericStageApproval", ...args);
    }

    function startDocumentationAgent(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "startDocumentationAgent", ...args);
    }

    function sendMessage(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "sendMessage", ...args);
    }

    function queueTerminalInput(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "queueTerminalInput", ...args);
    }

    function sendTerminalKey(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "sendTerminalKey", ...args);
    }

    function sendTerminalRaw(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "sendTerminalRaw", ...args);
    }

    function printableInputEvent(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "printableInputEvent", ...args);
    }

    function slashCommandTerminalKeyForInputEvent(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "slashCommandTerminalKeyForInputEvent", ...args);
    }

    function refreshSlashCommandModeAfterEdit(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "refreshSlashCommandModeAfterEdit", ...args);
    }

    function finishSlashCommandMode(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "finishSlashCommandMode", ...args);
    }

    function handleSlashCommandInput(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "handleSlashCommandInput", ...args);
    }

    function terminalKeyForInputEvent(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "terminalKeyForInputEvent", ...args);
    }

    function interruptActiveAgent(...args) {
      return window.ElectroBoyFrontend.invokeModule("agent-sessions", "interruptActiveAgent", ...args);
    }

    function positionStageMenu(menu, stage) {
      const paneRect = workflowPane.getBoundingClientRect();
      const stageRect = stage.getBoundingClientRect();
      const menuWidth = menu.offsetWidth || 192;
      const inset = 8;
      const left = Math.max(
        inset,
        Math.min(stageRect.left - paneRect.left, workflowPane.clientWidth - menuWidth - inset),
      );
      menu.style.left = `${left}px`;
      menu.style.top = `${stageRect.bottom - paneRect.top + inset}px`;
    }

    function hideStageMenus(exceptMenu = null) {
      const menus = [
        projectMenu,
        requirementsMenu,
        designMenu,
        designReviewMenu,
        implementationPlanMenu,
        codeMenu,
        testPlanMenu,
        validateMenu,
        documentMenu,
      ];
      for (const menu of menus) {
        if (menu !== exceptMenu) {
          menu.hidden = true;
        }
      }
      if (exceptMenu !== projectMenu) {
        hideSubmenu(metaProjectSubmenu, metaProjectMenuButton);
        hideSubmenu(workItemSubmenu, workItemMenuButton);
      }
      hideSubmenu(startMetaRepositorySubmenu, startMetaRepository);
      hideSubmenu(removeMetaRepositorySubmenu, removeMetaRepository);
      hideSubmenu(switchFeatureWorkItemSubmenu, switchFeatureWorkItem);
      hideSubmenu(switchBugWorkItemSubmenu, switchBugWorkItem);
    }

    function toggleStageMenu(menu, stage) {
      const shouldOpen = menu.hidden;
      hideStageMenus(menu);
      menu.hidden = !shouldOpen;
      if (shouldOpen) {
        positionStageMenu(menu, stage);
      } else if (menu === projectMenu) {
        hideSubmenu(metaProjectSubmenu, metaProjectMenuButton);
        hideSubmenu(workItemSubmenu, workItemMenuButton);
        hideSubmenu(startMetaRepositorySubmenu, startMetaRepository);
        hideSubmenu(removeMetaRepositorySubmenu, removeMetaRepository);
        hideSubmenu(switchFeatureWorkItemSubmenu, switchFeatureWorkItem);
        hideSubmenu(switchBugWorkItemSubmenu, switchBugWorkItem);
      }
    }

    function repositionOpenStageMenu() {
      if (!projectMenu.hidden) {
        positionStageMenu(projectMenu, projectStage);
      }
      if (!requirementsMenu.hidden) {
        positionStageMenu(requirementsMenu, requirementsStage);
      }
      if (!designMenu.hidden) {
        positionStageMenu(designMenu, designStage);
      }
      if (!designReviewMenu.hidden) {
        positionStageMenu(designReviewMenu, designReviewStage);
      }
      if (!implementationPlanMenu.hidden) {
        positionStageMenu(implementationPlanMenu, implementationPlanStage);
      }
      if (!codeMenu.hidden) {
        positionStageMenu(codeMenu, codeStage);
      }
      if (!testPlanMenu.hidden) {
        positionStageMenu(testPlanMenu, testPlanStage);
      }
      if (!validateMenu.hidden) {
        positionStageMenu(validateMenu, validateStage);
      }
      if (!documentMenu.hidden) {
        positionStageMenu(documentMenu, documentStage);
      }
    }

    async function handleWorkflowStageClick(stageNode) {
      const stageId = stageNode.dataset.stage || "";
      if (stageNode.disabled) {
        return;
      }
      showStageActionPanel(stageId);
    }

    openProject.addEventListener("click", () => openProjectBrowser("open", true));
    newProject.addEventListener("click", () => openProjectBrowser("new", true));
    openMetaProject.addEventListener("click", () => openProjectBrowser("open", true));
    newMetaProject.addEventListener("click", () => openProjectBrowser("meta-new", true));
    addMetaRepository.addEventListener("click", () => showProjectPanel("meta-add"));
    metaProjectMenuButton.addEventListener("click", () => {
      toggleSubmenu(metaProjectSubmenu, metaProjectMenuButton);
    });
    metaProjectBranch.addEventListener("mouseenter", () => {
      showSubmenu(metaProjectSubmenu, metaProjectMenuButton);
    });
    metaProjectBranch.addEventListener("mouseleave", () => {
      hideSubmenu(metaProjectSubmenu, metaProjectMenuButton);
    });
    startMetaRepository.addEventListener("click", () => {
      toggleSubmenu(startMetaRepositorySubmenu, startMetaRepository);
    });
    startMetaRepositoryBranch.addEventListener("mouseenter", () => {
      showSubmenu(startMetaRepositorySubmenu, startMetaRepository);
    });
    startMetaRepositoryBranch.addEventListener("mouseleave", () => {
      hideSubmenu(startMetaRepositorySubmenu, startMetaRepository);
    });
    removeMetaRepository.addEventListener("click", () => {
      toggleSubmenu(removeMetaRepositorySubmenu, removeMetaRepository);
    });
    removeMetaRepositoryBranch.addEventListener("mouseenter", () => {
      showSubmenu(removeMetaRepositorySubmenu, removeMetaRepository);
    });
    removeMetaRepositoryBranch.addEventListener("mouseleave", () => {
      hideSubmenu(removeMetaRepositorySubmenu, removeMetaRepository);
    });
    workItemMenuButton.addEventListener("click", () => {
      toggleSubmenu(workItemSubmenu, workItemMenuButton);
    });
    workItemBranch.addEventListener("mouseenter", () => {
      showSubmenu(workItemSubmenu, workItemMenuButton);
    });
    workItemBranch.addEventListener("mouseleave", () => {
      hideSubmenu(workItemSubmenu, workItemMenuButton);
    });
    switchFeatureWorkItem.addEventListener("click", () => {
      toggleSubmenu(switchFeatureWorkItemSubmenu, switchFeatureWorkItem);
    });
    switchFeatureWorkItemBranch.addEventListener("mouseenter", () => {
      showSubmenu(switchFeatureWorkItemSubmenu, switchFeatureWorkItem);
    });
    switchFeatureWorkItemBranch.addEventListener("mouseleave", () => {
      hideSubmenu(switchFeatureWorkItemSubmenu, switchFeatureWorkItem);
    });
    switchBugWorkItem.addEventListener("click", () => {
      toggleSubmenu(switchBugWorkItemSubmenu, switchBugWorkItem);
    });
    switchBugWorkItemBranch.addEventListener("mouseenter", () => {
      showSubmenu(switchBugWorkItemSubmenu, switchBugWorkItem);
    });
    switchBugWorkItemBranch.addEventListener("mouseleave", () => {
      hideSubmenu(switchBugWorkItemSubmenu, switchBugWorkItem);
    });
    newFeatureWorkItem.addEventListener("click", () => showWorkItemPanel("feature-new"));
    newBugWorkItem.addEventListener("click", () => showWorkItemPanel("bug-new"));
    applyWorkItem.addEventListener("click", applyWorkItemSelection);
    cancelWorkItem.addEventListener("click", hideWorkItemPanel);
    retryWorkItem.addEventListener("click", applyWorkItemSelection);
    workItemTitle.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        applyWorkItemSelection();
      }
    });
    deactivateProject.addEventListener("click", deactivateActiveProject);
    browseProject.addEventListener("click", () => {
      openProjectBrowser();
    });
    activateProject.addEventListener("click", applyProjectSelection);
    upDirectory.addEventListener("click", () => {
      if (currentBrowseParent) {
        browseDirectory(currentBrowseParent, currentBrowserMode);
      }
    });
    selectDirectory.addEventListener("click", selectCurrentDirectory);
    closeBrowser.addEventListener("click", () => {
      fileBrowser.hidden = true;
      if (currentBrowserMode === "link") {
        agentInput.focus();
      } else {
        projectPath.focus();
      }
    });

    decreaseTerminalFont.addEventListener("click", () => changeTerminalFontSize(-1));
    increaseTerminalFont.addEventListener("click", () => changeTerminalFontSize(1));
    document.querySelectorAll("[data-pane-font-delta]").forEach((button) => {
      button.addEventListener("click", () => {
        changePaneFontOffset(
          button.dataset.paneFont || "",
          Number(button.dataset.paneFontDelta || "0"),
        );
      });
    });
    document.querySelectorAll("[data-pane-font-reset]").forEach((button) => {
      button.addEventListener("click", () => {
        resetPaneFontOffset(button.dataset.paneFont || "");
      });
    });
    window.addEventListener("storage", (event) => {
      if (!event.key || !event.key.startsWith(PANE_FONT_OFFSET_STORAGE_PREFIX)) {
        return;
      }
      const pane = event.key.slice(PANE_FONT_OFFSET_STORAGE_PREFIX.length);
      if (!PANE_FONT_KEYS.includes(pane)) {
        return;
      }
      paneFontOffsets[pane] = storedPaneFontOffset(pane);
      applyPaneFontSize(pane);
    });
    popoutAgentPane.addEventListener("click", () => popOutPane("agent"));
    popoutProgressPane.addEventListener("click", () => popOutPane("progress"));
    popoutProjectShellPane.addEventListener("click", () => popOutPane("shell"));
    popoutScratchPane.addEventListener("click", () => popOutPane("scratch"));
    popoutStatusPane.addEventListener("click", () => popOutPane("status"));
    popoutInputPane.addEventListener("click", () => popOutPane("input"));
    shellResizeHandle.addEventListener("pointerdown", startShellResize);
    shellResizeHandle.addEventListener("pointermove", updateShellResize);
    shellResizeHandle.addEventListener("pointerup", finishShellResize);
    shellResizeHandle.addEventListener("pointercancel", finishShellResize);
    inputResizeHandle.addEventListener("pointerdown", startInputResize);
    inputResizeHandle.addEventListener("pointermove", updateInputResize);
    inputResizeHandle.addEventListener("pointerup", finishInputResize);
    inputResizeHandle.addEventListener("pointercancel", finishInputResize);
    inputActionResizeHandle.addEventListener("pointerdown", startInputActionsResize);
    inputActionResizeHandle.addEventListener("pointermove", updateInputActionsResize);
    inputActionResizeHandle.addEventListener("pointerup", finishInputActionsResize);
    inputActionResizeHandle.addEventListener("pointercancel", finishInputActionsResize);
    outputResizeHandle.addEventListener("pointerdown", startOutputResize);
    outputResizeHandle.addEventListener("pointermove", updateOutputResize);
    outputResizeHandle.addEventListener("pointerup", finishOutputResize);
    outputResizeHandle.addEventListener("pointercancel", finishOutputResize);
    shellPaneDivider.addEventListener("pointerdown", startProjectShellPaneResize);
    shellPaneDivider.addEventListener("pointermove", updateProjectShellPaneResize);
    shellPaneDivider.addEventListener("pointerup", finishProjectShellPaneResize);
    shellPaneDivider.addEventListener("pointercancel", finishProjectShellPaneResize);
    workbenchResizeHandle.addEventListener("pointerdown", startWorkbenchResize);
    workbenchResizeHandle.addEventListener("pointermove", updateWorkbenchResize);
    workbenchResizeHandle.addEventListener("pointerup", finishWorkbenchResize);
    workbenchResizeHandle.addEventListener("pointercancel", finishWorkbenchResize);
    sidePaneResizeHandle.addEventListener("pointerdown", startSidePaneResize);
    sidePaneResizeHandle.addEventListener("pointermove", updateSidePaneResize);
    sidePaneResizeHandle.addEventListener("pointerup", finishSidePaneResize);
    sidePaneResizeHandle.addEventListener("pointercancel", finishSidePaneResize);
    artifactPaneResizeHandle.addEventListener("pointerdown", startArtifactPaneResize);
    artifactPaneResizeHandle.addEventListener("pointermove", updateArtifactPaneResize);
    artifactPaneResizeHandle.addEventListener("pointerup", finishArtifactPaneResize);
    artifactPaneResizeHandle.addEventListener("pointercancel", finishArtifactPaneResize);
    insertFileLink.addEventListener("click", () => {
      if (insertFileLink.disabled) {
        return;
      }
      openLinkFileBrowser();
    });
    toggleWorkflowSideSheet.addEventListener("click", toggleWorkflowSideSheetCollapsed);
    stageScroll.addEventListener("scroll", repositionOpenStageMenu);
    window.addEventListener("resize", repositionOpenStageMenu);
    closeSplash.addEventListener("click", dismissSplash);
    showSplashButton.addEventListener("click", openSplash);
    splashOverlay.addEventListener("click", (event) => {
      if (event.target === splashOverlay) {
        dismissSplash();
      }
    });
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && splashOverlay && !splashOverlay.hidden) {
        dismissSplash();
      }
    });

    scratchPad.addEventListener("input", saveScratchPad);
    workflowModeSelect.addEventListener("change", () => {
      setWorkflowMode(workflowModeSelect.value).catch((error) => {
        appendOutput(`workflow switch failed: ${error}
`, "error");
      });
    });

    const frontendRuntime = {
      elements: {
        projectStage,
        stageNodes,
        creativeTree,
        creativeProjectMenuButton,
        creativeAgentMenuButton,
        creativeOpenProject,
        creativeNewProject,
        creativeCloseProject,
        creativeStartAgent,
        setRequirementsStage,
        startRequirements,
        approveRequirements,
        skipRequirementsApproval,
        setDesignStage,
        startDesign,
        completeDesign,
        setDesignReviewStage,
        startAutomaticDesignReview,
        startInteractiveDesignReview,
        stopDesignReview,
        approveDesignReview,
        skipDesignReviewApproval,
        setImplementationPlanStage,
        startImplementationPlan,
        approveImplementationPlan,
        skipImplementationPlanApproval,
        setCodeStage,
        startAutomaticCode,
        startInteractiveCode,
        startCodeAdHocAgent: startCodeAdHocAgentButton,
        stopCode,
        approveCode,
        skipCodeApproval,
        setTestPlanStage,
        startTestPlan,
        approveTestPlan,
        skipTestPlanApproval,
        setValidateStage,
        startAutomaticValidate,
        startInteractiveValidate,
        stopValidate,
        approveValidate,
        skipValidateApproval,
        createDocumentTarget,
        customDocumentForm,
        customDocumentName,
        addDocumentTarget,
        exportProgressOutput,
        openProjectShell,
        toggleProjectShellPane,
        closeProjectShellPane,
        stopProjectShell,
        sessionSwitcher,
        exportAgentOutput,
        interruptAgent,
        agentInput,
      },
      getState() {
        return {
          contextId,
          workflowMode,
          currentWorkflowStage,
          activationRoot,
          activeProjectRoot,
          activeProjectMode,
          activeRepositoryName,
          registeredRepositories,
          workItemState,
          requirementsRunning,
          designRunning,
          designReviewRunning,
          adHocRunning,
          selectedSessionId,
          creativeTreePayload,
          creativeActiveDocument,
          creativeActiveFolder,
          creativeEditingPath,
          creativeLastNotifiedTarget,
          expandedCreativeFolders,
        };
      },
      updateState(patch) {
        if (Object.hasOwn(patch, "creativeActiveDocument")) {
          creativeActiveDocument = patch.creativeActiveDocument;
        }
        if (Object.hasOwn(patch, "creativeActiveFolder")) {
          creativeActiveFolder = patch.creativeActiveFolder;
        }
        if (Object.hasOwn(patch, "creativeEditingPath")) {
          creativeEditingPath = patch.creativeEditingPath;
        }
        if (Object.hasOwn(patch, "creativeLastNotifiedTarget")) {
          creativeLastNotifiedTarget = patch.creativeLastNotifiedTarget;
        }
      },
      actions: {
        appendOutput,
        showStageActionPanel,
        handleWorkflowStageClick,
        setAgentInputVisible,
        clearAgentOutput,
        contextUrl,
        updateProjectState,
        connectSessionEvents,
        sendTerminalResize,
        activeCreativeTarget,
        basename,
        creativePathIsCorkboard,
        creativeParentPath,
        showArtifactPreviews,
        showCreativeCorkboard,
        renderCreativeTree,
        renderCreativeProjectStatus,
        notifyCreativeAgentTargetSwitch,
        beginCreativeRename,
        cancelCreativeRename,
        finishCreativeRename,
        deleteCreativeEntry,
        createCreativeFolder: createCreativeFolderInline,
        createCreativeDocument: createCreativeDocumentInline,
        createCreativeCorkboard: createCreativeCorkboardInline,
        selectCreativeFolder,
        selectCreativeCorkboard,
        selectCreativeDocument,
        toggleCreativeActionGroup,
        openProjectBrowser,
        deactivateProject: deactivateActiveProject,
        setWorkflowStage: setWorkflowStageFromMenu,
        startRequirementsAgent,
        approveRequirementsStage,
        skipRequirementsApprovalStage,
        startDesignAgent,
        completeDesignAgent,
        startAutomaticDesignReviewAgent,
        startInteractiveDesignReviewAgent,
        stopDesignReviewAgent,
        approveDesignReviewStage,
        skipDesignReviewApprovalStage,
        genericStageRun,
        startGenericStageAgent,
        stopGenericStageAgent,
        approveGenericStage,
        skipGenericStageApproval,
        startAdHocAgent,
        recentProjectActions: recentProjectActionsForWorkflow,
        repositoryLabel,
        startMetaRepository: startMetaRepositoryFromMenu,
        removeMetaRepository: removeMetaRepositoryFromMenu,
        showProjectPanel,
        showWorkItemPanel,
        workItemFeatures,
        workItemBugs,
        featureLabel,
        switchFeature: switchFeatureWorkItemContext,
        switchBug: switchBugWorkItemContext,
        storedDocumentTargets,
        saveDocumentTargets,
        initializeProgressTerminal,
        initializeProjectShellTerminal,
        documentExportFormats,
        documentExportFormat,
        documentExportPickerTypes,
        sessionExportName,
        exportAgentSession,
        exportProgressLog,
        artifactDocumentBaseName,
        artifactDocumentExportName,
        artifactDocumentExportUrl,
        exportArtifactDocument,
        queueProjectShellResize,
        sendProjectShellResize,
        appendProgressOutput,
        clearProgressOutput,
        appendProjectShellOutput,
        clearProjectShellOutput,
        applyProjectShellPaneVisibility,
        showProjectShellPane,
        hideProjectShellPane,
        syncProjectShellPane,
        toggleProjectShellFromToolbar,
        updateProjectShellToggle,
        startProjectShell,
        connectProjectShellEvents,
        closeProjectShellEventStream,
        disposeProjectShellTerminal,
        sendProjectShellInput,
        stopProjectShellProcess,
        selectedSession,
        sessionIsRunning,
        selectedSessionAcceptsInput,
        updateSessionIndicator,
        sessionMetadata,
        documentTargetKey,
        documentTargetLabel,
        documentTargetForSession,
        documentationSessionForTarget,
        agentSessionDisplayLabel,
        attachableServiceSessions,
        serviceSessionDisplayLabel,
        rememberOpenDocumentTarget,
        syncOpenDocumentTargetsFromSessions,
        renderDocumentTargetSwitcher,
        refreshDocumentTargetSwitchers,
        renderSessionSwitcher,
        selectAgentSession,
        refreshServiceSessions,
        attachAgentSession,
        renderDocumentActionPanel,
        allDocumentTargets,
        renderDocumentTargets,
        documentTargetFromInput,
        documentTargetFromSelectedPath,
        registerDocumentTarget,
        launchDocumentTarget,
        selectOpenDocumentTarget,
        startCustomDocumentTargetFromValue,
        addCustomDocumentTarget,
        artifactKindForPane,
        artifactRouteUrl,
        artifactPreviewUrl,
        artifactEditUrl,
        artifactPaneSupportsModeSwitch,
        artifactPaneSupportsDocumentExport,
        artifactPaneSupportsDocumentZoom,
        artifactPreviewsForStage,
        setArtifactCompatibilityState,
        showStageArtifactPreview,
        showArtifactPreview,
        showDocumentPreview,
        applyCreativeWorkspace,
        restoreSoftwareWorkspace,
        updateCreativeBinderActions,
        renderCreativeRecentProjects,
        updateCreativeActionGroup,
        refreshCreativeBinder,
        firstCreativeMarkdown,
        showCreativeTreeMessage,
        showCreativeDocument,
        creativeAgentSession,
        creativeAgentRunning,
        creativeTargetKey,
        creativeTargetContextLines,
        creativePromptMessage,
        loadCreativeScratchPad,
        queueCreativeScratchPadSave,
        saveCreativeScratchPad,
        initializeCreativeWorkspace,
        ensureCreativeWorkspaceLoaded,
        creativeEntryChildren,
        findCreativeEntry,
        uniqueCreativeChildPath,
        creativePathIsInside,
        remapCreativePath,
        normalizedCreativeName,
        createCreativeFolderInline,
        createCreativeDocumentInline,
        createCreativeCorkboardInline,
        startCreativeWritingAgent,
        markArtifactFrameLoading,
        renderArtifactPreviewItems,
        artifactFrameForItem,
        requestArtifactEditorSave,
        setArtifactPreviewEditing,
        popOutArtifactPreview,
        hideArtifactPreview,
        refreshArtifactPreview,
        artifactEventUrl,
        connectArtifactEvents,
        closeArtifactEventStream,
        stageIsRunning,
        syncArtifactPreviewWithProject,
        selectWorkflowStage,
        setWorkflowStageFromMenu,
        connectAgentEvents,
        connectProgressEvents,
        closeAgentEventStream,
        closeProgressEventStream,
        agentProcessRunning,
        updateAgentControls,
        setAgentRunning,
        setRequirementsRunning,
        runStageAgent,
        runRequirementsAgent,
        completeRequirementsAgent,
        completeDesignReviewAgent,
        startDocumentationAgent,
        sendMessage,
        queueTerminalInput,
        sendTerminalKey,
        sendTerminalRaw,
        printableInputEvent,
        slashCommandTerminalKeyForInputEvent,
        refreshSlashCommandModeAfterEdit,
        finishSlashCommandMode,
        handleSlashCommandInput,
        terminalKeyForInputEvent,
        interruptActiveAgent,
      },
    };

    async function initialize() {
      window.ElectroBoyFrontend.bindRuntime(frontendRuntime);
      renderWorkflowModeOptions();
      applyStageDescriptions();
      applyWorkflowSideSheetState();
      applyWorkflowMode();
      renderStageActionPanel();
      initializePaneLayout();
      applyStoredPaneSizes();
      applyStoredProgressPaneSize();
      applyStoredArtifactPaneSize();
      applyStoredWorkbenchPaneSize();
      applySidePaneVisibility();
      restoreScratchPad();
      applyTerminalFontSize();
      applyDocumentZoom();
      initializeTerminal();
      observeTerminalPaneResizes();
      showSplashIfNeeded();
      await checkConnection();
      await restoreContext();
      await refreshServiceSessions();
      window.setInterval(refreshServiceSessions, 10000);
    }

    window.addEventListener("pagehide", releaseContextOwner);
    window.addEventListener("pageshow", () => {
      if (contextId) {
        claimContextOwner(contextId);
      }
    });

    if (document.readyState === "loading") {
      window.addEventListener("DOMContentLoaded", () => {
        initialize().catch(() => {});
      }, { once: true });
    } else {
      initialize().catch(() => {});
    }
