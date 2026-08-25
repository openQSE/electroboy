    const shell = document.querySelector(".shell");
    const connection = document.getElementById("connection");
    const workflowPane = document.querySelector(".workflow-pane");
    const shellResizeHandle = document.getElementById("shellResizeHandle");
    const workflowSideSheet = document.getElementById("workflowSideSheet");
    const workflowSideSheetResizeHandle = document.getElementById(
      "workflowSideSheetResizeHandle",
    );
    const toggleWorkflowSideSheet = document.getElementById("toggleWorkflowSideSheet");
    const workflowModeSelect = document.getElementById("workflowModeSelect");
    const stageScroll = document.querySelector(".stage-scroll");
    const workflowStageGraph = document.getElementById("workflowStageGraph");
    let stageNodes = [];
    let activeWorkflowDefinitions = [];
    let activeModuleDefinitions = [];
    const stageActionPanel = document.getElementById("stageActionPanel");
    const stageActionBody = document.getElementById("stageActionBody");
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
    const agentSendShortcut = document.getElementById("agentSendShortcut");
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
    const helpOverlay = document.getElementById("helpOverlay");
    const showHelpButton = document.getElementById("showHelp");
    const closeHelpButton = document.getElementById("closeHelp");
    const helpSummary = document.getElementById("helpSummary");
    const helpTour = document.getElementById("helpTour");
    const helpControls = document.getElementById("helpControls");
    const helpWorkflowTitle = document.getElementById("helpWorkflowTitle");
    const helpWorkflowSummary = document.getElementById("helpWorkflowSummary");
    const helpWorkflowFeatures = document.getElementById("helpWorkflowFeatures");
    const helpShortcuts = document.getElementById("helpShortcuts");
    const helpWorkflowBadge = document.getElementById("helpWorkflowBadge");
    const helpVersion = document.getElementById("helpVersion");
    const CONTEXT_STORAGE_KEY = "electroboy.contextId";
    const WORKSPACE_LEASE_STORAGE_KEY = "electroboy.workspaceLease";
    const CONTEXT_TAB_STORAGE_KEY = "electroboy.contextTabId";
    const CONTEXT_OWNER_STORAGE_PREFIX = "electroboy.contextOwner.";
    const SERVICE_FINGERPRINT_STORAGE_KEY = "electroboy.serviceFingerprint.v2";
    const LEGACY_SERVICE_FINGERPRINT_STORAGE_KEYS = [
      "electroboy.serviceFingerprint.v1",
    ];
    const SPLASH_DISMISSED_STORAGE_KEY = "electroboy.splash.dismissed.v1";
    const CONTEXT_OWNER_TTL_MS = 15000;
    const CONTEXT_OWNER_HEARTBEAT_MS = 5000;
    const WORKSPACE_HEARTBEAT_MS = 5000;
    const FRONTEND_DEBUG_INTERVAL_MS = 5000;
    const FRONTEND_DEBUG_EVENT_LOOP_INTERVAL_MS = 1000;
    const FRONTEND_DEBUG_PAINT_INTERVAL_MS = 1000;
    const FRONTEND_DEBUG_SUSPENSION_GAP_MS = 5000;
    const FRONTEND_DEBUG_EVENT_LIMIT = 100;
    const FRONTEND_DEBUG_ENDPOINT = "/api/frontend/debug";
    const FRONTEND_DEBUG_STORAGE_KEY = "electroboy.frontendDebug.last";
    const FRONTEND_DEBUG_HEARTBEAT_ID = "electroboyFrontendDebugHeartbeat";
    const FRONTEND_TELEMETRY_STORAGE_KEY = "electroboy.telemetry.enabled.v1";
    const DEFAULT_FRONTEND_TELEMETRY_ENABLED = false;
    const FRONTEND_TELEMETRY_QUERY_KEYS = [
      "telemetry",
      "frontend_telemetry",
      "frontend_debug",
    ];
    const WORKFLOW_SIDE_SHEET_STORAGE_KEY = "electroboy.workflowSideSheetCollapsed";
    const WORKFLOW_SIDE_SHEET_WIDTH_STORAGE_KEY = "electroboy.workflowSideSheetWidth";
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
    const MIN_WORKFLOW_SIDE_SHEET_WIDTH = 260;
    const MIN_WORKFLOW_CONTENT_WIDTH = 360;
    const INPUT_PANE_HEIGHT_STORAGE_KEY = "electroboy.inputPaneHeight";
    const INPUT_ACTIONS_WIDTH_STORAGE_KEY = "electroboy.inputActionsWidth";
    const PROGRESS_PANE_WIDTH_STORAGE_KEY = "electroboy.progressPaneWidth";
    const PROGRESS_PANE_HEIGHT_STORAGE_KEY = "electroboy.progressPaneHeight";
    const PROJECT_SHELL_PANE_HEIGHT_STORAGE_KEY =
      "electroboy.projectShellPaneHeight";
    const RIGHT_PANE_WIDTH_STORAGE_KEY = "electroboy.rightPaneWidth";
    const RIGHT_PANE_HEIGHT_STORAGE_KEY = "electroboy.rightPaneHeight";
    const SCRATCH_PANE_HEIGHT_STORAGE_KEY = "electroboy.scratchPaneHeight";
    const ARTIFACT_PANE_WIDTH_STORAGE_KEY = "electroboy.artifactPaneWidth";
    const ARTIFACT_PANE_HEIGHT_STORAGE_KEY = "electroboy.artifactPaneHeight";
    const PANE_LAYOUT_STORAGE_KEY = "electroboy.paneLayout.v1";
    const SCRATCH_PAD_STORAGE_KEY = "electroboy.scratchPad";
    const DOCUMENT_TARGETS_STORAGE_KEY = "electroboy.documentTargets";
    const PANE_POPUP_FEATURES =
      "popup=yes,width=980,height=720,menubar=no,toolbar=no,location=no,status=no,scrollbars=yes,resizable=yes";
    const DEFAULT_DOCUMENT_TARGETS = [
      { label: "README", path: "README.md" },
      { label: "API", path: "docs/api.md" },
    ];
    const DEFAULT_TERMINAL_FONT_SIZE = 15;
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
    const AGENT_OUTPUT_FLUSH_BUDGET_MS = 8;
    const AGENT_OUTPUT_FLUSH_CHARS = 65536;
    const DEFAULT_AGENT_TERMINAL_ID = "__electroboy_agent_default__";
    let eventSource = null;
    let artifactEventSources = [];
    const agentTerminalContexts = new Map();
    let activeAgentTerminalSessionId = DEFAULT_AGENT_TERMINAL_ID;
    let terminal = null;
    let terminalFit = null;
    let terminalWindowResizeListenerInstalled = false;
    let terminalFontSize = storedTerminalFontSize();
    let paneFontOffsets = storedPaneFontOffsets();
    let documentZoom = storedDocumentZoom();
    let serviceVersion = "";
    let helpPreviousFocus = null;
    let serviceSessions = [];
    let resizeShellState = null;
    let resizeWorkflowSideSheetState = null;
    let resizeInputState = null;
    let resizeInputActionsState = null;
    let resizeOutputState = null;
    let resizeWorkbenchState = null;
    let resizeSidePaneState = null;
    let resizeArtifactPaneState = null;
    let resizeProjectShellState = null;
    let workflowSideSheetMutationObserver = null;
    let workflowSideSheetTextCanvas = null;
    let paneLayout = null;
    let paneLayoutObserver = null;
    let paneDragController = null;
    let paneLayoutIdSequence = 0;
    let activePaneLayoutLeafId = "";
    let paneCornerSplitCancel = null;
    let terminalResizeObserver = null;
    let fitTerminalFrame = 0;
    let frontendTelemetryEnabled = storedFrontendTelemetryEnabled();
    let frontendDebugDiagnosticsStarted = false;
    let frontendDebugFrameInstrumented = false;
    let frontendDebugFetchInstrumented = false;
    let frontendDebugRafPulseActive = false;
    let frontendDebugListenersBound = false;
    let frontendDebugNativeRequestAnimationFrame = null;
    let frontendDebugLastTick = 0;
    let frontendDebugMaxEventLoopLagMs = 0;
    let frontendDebugLongTaskCount = 0;
    let frontendDebugMaxLongTaskMs = 0;
    let frontendDebugSendTimer = null;
    let frontendDebugTickTimer = null;
    let frontendDebugLongTaskObserver = null;
    let frontendDebugLastError = "";
    let frontendDebugBaseTitle = document.title || "ElectroBoy";
    let frontendDebugPaintMarker = null;
    let frontendDebugPaintSequence = 0;
    let frontendDebugLastPaintMutationMs = 0;
    let frontendDebugLastPaintMutationAt = "";
    let frontendDebugPaintExpectedWidth = 0;
    let frontendDebugPaintActualWidth = 0;
    let frontendDebugPaintProbeOk = false;
    let frontendDebugPaintProbeFailures = 0;
    let frontendDebugRafLastTimestamp = 0;
    let frontendDebugRafTotalFrames = 0;
    let frontendDebugRafFramesSinceSnapshot = 0;
    let frontendDebugRafMaxGapMs = 0;
    let frontendDebugRafLastFrameAt = "";
    let frontendDebugInputLastEvent = "";
    let frontendDebugInputLastAt = "";
    let frontendDebugInputLastTarget = {};
    let frontendDebugLifecycleFrozen = false;
    let frontendDebugLifecycleLastEvent = "";
    let frontendDebugLifecycleLastAt = "";
    let frontendDebugLifecycleDroppedEvents = 0;
    let frontendDebugNetworkDroppedEvents = 0;
    let frontendDebugEventSourceSequence = 0;
    let frontendDebugFetchSequence = 0;
    let frontendDebugNativeFetch = null;
    let frontendDebugResponseBodyPending = 0;
    let frontendDebugResponseBodyMaxPending = 0;
    let frontendDebugResponseBodyDrainStarted = 0;
    let frontendDebugResponseBodyDrainCompleted = 0;
    let frontendDebugResponseBodyDrainFailed = 0;
    let frontendDebugResponseBodyRequestFailed = 0;
    let frontendDebugResponseBodyBytesDrained = 0;
    let frontendDebugResponseBodyLastResult = null;
    const frontendDebugLifecycleEvents = [];
    const frontendDebugNetworkEvents = [];
    const frontendDebugFetchMetadata = new WeakMap();
    const frontendDebugCounters = Object.create(null);
    const frontendDebugInputCounters = Object.create(null);
    let resizeTimer = null;
    let pendingTerminalResize = null;
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
    const poppedPaneLeafIds = new Set();
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
    let workspaceLeaseToken = "";
    let workspaceAttachmentPolicy = "exclusive";
    let workspaceHeartbeatTimer = null;
    let workspaceRecoveryPromise = null;
    let workspaceStateSaveTimer = null;
    let workspaceStateHydrating = false;
    const pageInstanceId = newContextOwnerId();
    let browserTabId = "";
    let ownedContextId = "";
    let contextOwnerTimer = null;
    let projectMode = "open";
    let projectBrowserActivatesSelection = false;
    let serviceRoot = "";
    let serviceFingerprint = "";
    let activationRoot = "";
    let activeProjectMode = "none";
    let activeProjectRoot = "";
    let activeRepositoryName = "";
    let registeredRepositories = [];
    let recentProjects = [];
    let workItemState = { collections: [], features: [], bugs: [] };
    let stageRunState = {};
    let workItemMode = "";
    let customDocumentTargets = [];
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
      artifact: { label: "File", element: artifactPreviewPane },
      agenda: { label: "Agenda", element: null },
      calendar: { label: "Calendar", element: null },
      shell: { label: "Shell", element: projectShellPane },
      scratch: { label: "Scratch", element: scratchPane },
      status: { label: "Status", element: projectStatusPane },
    };
    const INSTANCE_PANE_LAYOUT_KINDS = new Set(["artifact", "agenda", "calendar"]);
    const SINGLETON_PANE_LAYOUT_KINDS = new Set(["progress"]);
    const RESTORABLE_PANE_LAYOUT_KINDS = new Set([
      "empty",
      "agent",
      "artifact",
      "agenda",
      "calendar",
      "scratch",
      "status",
    ]);

    function newPaneLayoutId(prefix = "pane") {
      paneLayoutIdSequence += 1;
      return `${prefix}-${Date.now()}-${paneLayoutIdSequence}`;
    }

    function paneLayoutLeaf(kind = "empty", content = null, projectRoot = "") {
      return { type: "leaf", id: newPaneLayoutId(), kind, content, projectRoot };
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

    function paneLayoutFromDefinition(definition) {
      if (typeof definition === "string") {
        return paneLayoutLeaf(
          definition === "empty" || PANE_LAYOUT_KINDS[definition]
            ? definition
            : "empty",
        );
      }
      if (!definition || typeof definition !== "object") {
        return null;
      }
      if (definition.type === "leaf") {
        return paneLayoutFromDefinition(String(definition.kind || "empty"));
      }
      if (definition.type !== "split") {
        return null;
      }
      const first = paneLayoutFromDefinition(definition.first);
      const second = paneLayoutFromDefinition(definition.second);
      if (!first || !second) {
        return null;
      }
      const ratio = Number(definition.ratio);
      return paneLayoutSplit(
        definition.direction === "column" ? "column" : "row",
        first,
        second,
        Number.isFinite(ratio) ? clampValue(ratio, 0.12, 0.88) : 0.5,
      );
    }

    function paneLayoutDescription(node) {
      if (!node || node.type === "leaf") {
        return { type: "leaf", kind: String((node && node.kind) || "empty") };
      }
      return {
        type: "split",
        direction: node.direction === "column" ? "column" : "row",
        ratio: Number(node.ratio) || 0.5,
        first: paneLayoutDescription(node.first),
        second: paneLayoutDescription(node.second),
      };
    }

    function paneLayoutContribution(mode = workflowMode) {
      const frontend = window.ElectroBoyFrontend;
      return frontend && typeof frontend.workflowForSelection === "function"
        ? frontend.workflowForSelection(mode)
        : null;
    }

    function defaultPaneLayout(mode = workflowMode) {
      const contribution = paneLayoutContribution(mode);
      return paneLayoutFromDefinition(
        contribution && contribution.defaultPaneLayout,
      ) || paneLayoutLeaf("empty");
    }

    function migratePaneLayoutForWorkflow(layout, mode = workflowMode) {
      const contribution = paneLayoutContribution(mode);
      if (
        !layout ||
        !contribution ||
        typeof contribution.migratePaneLayout !== "function" ||
        contribution.migratePaneLayout(paneLayoutDescription(layout)) !== true
      ) {
        return layout;
      }
      return defaultPaneLayout(mode);
    }

    function paneLayoutHasRestorableLeaf(node) {
      if (!node) {
        return false;
      }
      if (node.type === "leaf") {
        return RESTORABLE_PANE_LAYOUT_KINDS.has(node.kind);
      }
      return paneLayoutHasRestorableLeaf(node.first) ||
        paneLayoutHasRestorableLeaf(node.second);
    }

    function restoredPaneLayoutForWorkflow(layout, mode = workflowMode) {
      const migrated = migratePaneLayoutForWorkflow(layout, mode);
      if (!paneLayoutHasRestorableLeaf(migrated)) {
        return defaultPaneLayout(mode);
      }
      return migrated;
    }

    function paneLayoutStorageKey(mode = workflowMode) {
      return `${PANE_LAYOUT_STORAGE_KEY}.${mode || "none"}.${contextId || "detached"}`;
    }

    function workspacePresentationStorage() {
      return workspaceAllowsSharedConnections()
        ? window.sessionStorage
        : window.localStorage;
    }

    function workspaceClientStateStorageKey() {
      return `electroboy.workspaceClientState.${contextId || "detached"}`;
    }

    function normalizePaneLayoutNode(value, seenKinds) {
      if (!value || typeof value !== "object") {
        return null;
      }
      if (value.type === "leaf") {
        const requestedKind = String(value.kind || "empty");
        const validKind = requestedKind === "empty" || PANE_LAYOUT_KINDS[requestedKind];
        const duplicateSingleton = SINGLETON_PANE_LAYOUT_KINDS.has(requestedKind) &&
          seenKinds.has(requestedKind);
        if (validKind && duplicateSingleton) {
          return null;
        }
        const content = value.content && typeof value.content === "object"
          ? value.content
          : null;
        const kind = validKind && requestedKind === "artifact" &&
            content?.kind === "agenda"
          ? "agenda"
          : validKind ? requestedKind : "empty";
        if (SINGLETON_PANE_LAYOUT_KINDS.has(kind)) {
          seenKinds.add(kind);
        }
        const projectRoot = content ? String(value.projectRoot || "") : "";
        return paneLayoutLeaf(kind, content, projectRoot);
      }
      if (value.type !== "split") {
        return null;
      }
      const first = normalizePaneLayoutNode(value.first, seenKinds);
      const second = normalizePaneLayoutNode(value.second, seenKinds);
      if (!first && !second) {
        return null;
      }
      if (!first) {
        return second;
      }
      if (!second) {
        return first;
      }
      const ratio = Number(value.ratio);
      return paneLayoutSplit(
        value.direction === "column" ? "column" : "row",
        first,
        second,
        Number.isFinite(ratio) ? clampValue(ratio, 0.12, 0.88) : 0.5,
      );
    }

    function storedPaneLayout(mode = workflowMode) {
      try {
        const storageKey = paneLayoutStorageKey(mode);
        const storage = workspacePresentationStorage();
        const raw = storage.getItem(storageKey);
        if (raw !== null) {
          const stored = normalizePaneLayoutNode(JSON.parse(raw), new Set());
          const migrated = restoredPaneLayoutForWorkflow(stored, mode);
          if (migrated && migrated !== stored) {
            storage.setItem(storageKey, JSON.stringify(migrated));
          }
          return migrated || defaultPaneLayout(mode);
        }
        const legacyRaw = workspaceAllowsSharedConnections()
          ? null
          : window.localStorage.getItem(PANE_LAYOUT_STORAGE_KEY);
        if (legacyRaw !== null) {
          window.localStorage.removeItem(PANE_LAYOUT_STORAGE_KEY);
          const stored = normalizePaneLayoutNode(JSON.parse(legacyRaw), new Set());
          const migrated = restoredPaneLayoutForWorkflow(stored, mode);
          if (migrated) {
            storage.setItem(storageKey, JSON.stringify(migrated));
            return migrated;
          }
        }
        return defaultPaneLayout(mode);
      } catch (error) {
        return defaultPaneLayout(mode);
      }
    }

    function serviceFingerprintFromPayload(payload) {
      const workflowConfig = payload && payload.workflow_config
        ? payload.workflow_config
        : {};
      const workflows = Array.isArray(payload && payload.workflows)
        ? payload.workflows
        : [];
      return JSON.stringify({
        root: String((payload && payload.root) || ""),
        state_root: String((payload && payload.state_root) || ""),
        workflow_config: String(workflowConfig.path || ""),
        workflows: workflows.map((workflow) => String(workflow)).sort(),
      });
    }

    function clearStaleServiceBrowserState() {
      try {
        for (const key of Object.keys(window.sessionStorage)) {
          if (
            key === CONTEXT_STORAGE_KEY ||
            key === CONTEXT_TAB_STORAGE_KEY ||
            key.startsWith(`${CONTEXT_STORAGE_KEY}.`) ||
            key.startsWith(`${WORKSPACE_LEASE_STORAGE_KEY}.`)
          ) {
            window.sessionStorage.removeItem(key);
          }
        }
      } catch (error) {
        // Ignore storage failures; the server will reject stale contexts anyway.
      }
      try {
        for (const key of Object.keys(window.localStorage)) {
          if (
            key === PANE_LAYOUT_STORAGE_KEY ||
            key.startsWith(`${PANE_LAYOUT_STORAGE_KEY}.`) ||
            key.startsWith(CONTEXT_OWNER_STORAGE_PREFIX)
          ) {
            window.localStorage.removeItem(key);
          }
        }
      } catch (error) {
        // Ignore storage failures; a fresh context will still be created.
      }
    }

    function hasServiceBrowserState() {
      try {
        for (const key of Object.keys(window.sessionStorage)) {
          if (
            key === CONTEXT_STORAGE_KEY ||
            key === CONTEXT_TAB_STORAGE_KEY ||
            key.startsWith(`${CONTEXT_STORAGE_KEY}.`) ||
            key.startsWith(`${WORKSPACE_LEASE_STORAGE_KEY}.`)
          ) {
            return true;
          }
        }
      } catch (error) {
        // Ignore storage failures; this is only a migration hint.
      }
      try {
        for (const key of Object.keys(window.localStorage)) {
          if (
            key === PANE_LAYOUT_STORAGE_KEY ||
            key.startsWith(`${PANE_LAYOUT_STORAGE_KEY}.`) ||
            key.startsWith(CONTEXT_OWNER_STORAGE_PREFIX)
          ) {
            return true;
          }
        }
      } catch (error) {
        // Ignore storage failures; this is only a migration hint.
      }
      return false;
    }

    function applyServiceFingerprint(payload) {
      const nextFingerprint = serviceFingerprintFromPayload(payload);
      if (!nextFingerprint) {
        return;
      }
      try {
        const storedFingerprint = window.localStorage.getItem(
          SERVICE_FINGERPRINT_STORAGE_KEY,
        ) || "";
        const hasLegacyFingerprint = LEGACY_SERVICE_FINGERPRINT_STORAGE_KEYS.some(
          (key) => window.localStorage.getItem(key) !== null,
        );
        if (!storedFingerprint) {
          if (hasLegacyFingerprint || hasServiceBrowserState()) {
            clearStaleServiceBrowserState();
          }
        } else if (storedFingerprint !== nextFingerprint) {
          clearStaleServiceBrowserState();
        }
        for (const key of LEGACY_SERVICE_FINGERPRINT_STORAGE_KEYS) {
          window.localStorage.removeItem(key);
        }
        window.localStorage.setItem(
          SERVICE_FINGERPRINT_STORAGE_KEY,
          nextFingerprint,
        );
      } catch (error) {
        // Keep operating when storage is unavailable.
      }
      serviceFingerprint = nextFingerprint;
    }

    function savePaneLayout() {
      try {
        workspacePresentationStorage().setItem(
          paneLayoutStorageKey(),
          JSON.stringify(paneLayout),
        );
        window.localStorage.removeItem(PANE_LAYOUT_STORAGE_KEY);
      } catch (error) {
        return;
      }
      queueWorkspaceStateSave();
    }

    function workspaceClientState() {
      return {
        pane_layout: paneLayout,
        open_documents: openDocumentTargets.map((target) => ({
          label: String(target.label || target.path || "Document"),
          path: String(target.path || ""),
        })).filter((target) => target.path),
        scratchpad: scratchPad.value,
      };
    }

    function paneLayoutIsMounted() {
      return outputWorkbench.classList.contains("pane-layout-enabled") &&
        Boolean(outputWorkbench.firstElementChild);
    }

    function parseFrontendTelemetryPreference(value) {
      const normalized = String(value || "").trim().toLowerCase();
      if (["1", "true", "yes", "on", "enable", "enabled"].includes(normalized)) {
        return true;
      }
      if (["0", "false", "no", "off", "disable", "disabled"].includes(normalized)) {
        return false;
      }
      return null;
    }

    function storedFrontendTelemetryEnabled() {
      try {
        const stored = parseFrontendTelemetryPreference(
          window.localStorage.getItem(FRONTEND_TELEMETRY_STORAGE_KEY),
        );
        return stored === null ? DEFAULT_FRONTEND_TELEMETRY_ENABLED : stored;
      } catch (error) {
        return DEFAULT_FRONTEND_TELEMETRY_ENABLED;
      }
    }

    function saveFrontendTelemetryEnabled(enabled) {
      try {
        window.localStorage.setItem(
          FRONTEND_TELEMETRY_STORAGE_KEY,
          enabled ? "1" : "0",
        );
      } catch (error) {
        return;
      }
    }

    function frontendTelemetryPreferenceFromUrl() {
      const parameters = new URLSearchParams(window.location.search);
      for (const key of FRONTEND_TELEMETRY_QUERY_KEYS) {
        if (!parameters.has(key)) {
          continue;
        }
        const preference = parseFrontendTelemetryPreference(parameters.get(key));
        if (preference !== null) {
          return preference;
        }
      }
      return null;
    }

    function applyFrontendTelemetryUrlPreference() {
      const preference = frontendTelemetryPreferenceFromUrl();
      if (preference !== null) {
        setFrontendTelemetryEnabled(preference);
      }
    }

    function frontendTelemetryIsEnabled() {
      return frontendTelemetryEnabled;
    }

    function setFrontendTelemetryEnabled(enabled, options = {}) {
      const nextEnabled = Boolean(enabled);
      const persist = options.persist !== false;
      if (persist) {
        saveFrontendTelemetryEnabled(nextEnabled);
      }
      if (frontendTelemetryEnabled === nextEnabled) {
        return frontendTelemetryEnabled;
      }
      frontendTelemetryEnabled = nextEnabled;
      if (frontendTelemetryEnabled) {
        startFrontendDebugDiagnostics();
      } else {
        stopFrontendDebugDiagnostics();
      }
      return frontendTelemetryEnabled;
    }

    function frontendDebugNow() {
      return window.performance && typeof window.performance.now === "function"
        ? window.performance.now()
        : Date.now();
    }

    function bumpFrontendDebugCounter(name, amount = 1) {
      if (!frontendTelemetryEnabled) {
        return;
      }
      frontendDebugCounters[name] = (frontendDebugCounters[name] || 0) + amount;
    }

    function instrumentFrontendDebugFrames() {
      if (frontendDebugFrameInstrumented) {
        return;
      }
      frontendDebugFrameInstrumented = true;
      frontendDebugNativeRequestAnimationFrame =
        window.requestAnimationFrame.bind(window);
      window.requestAnimationFrame = (callback) => {
        bumpFrontendDebugCounter("requestAnimationFrame.scheduled");
        return frontendDebugNativeRequestAnimationFrame((timestamp) => {
          bumpFrontendDebugCounter("requestAnimationFrame.callback");
          return callback(timestamp);
        });
      };
    }

    function ensureFrontendDebugPaintMarker() {
      if (frontendDebugPaintMarker && frontendDebugPaintMarker.isConnected) {
        return frontendDebugPaintMarker;
      }
      let marker = document.getElementById(FRONTEND_DEBUG_HEARTBEAT_ID);
      if (!marker) {
        marker = document.createElement("div");
        marker.id = FRONTEND_DEBUG_HEARTBEAT_ID;
        marker.setAttribute("aria-hidden", "true");
        marker.style.position = "fixed";
        marker.style.right = "4px";
        marker.style.bottom = "4px";
        marker.style.height = "14px";
        marker.style.padding = "0 3px";
        marker.style.borderRadius = "2px";
        marker.style.background = "rgba(0, 0, 0, 0.65)";
        marker.style.color = "#fff";
        marker.style.font = "10px/14px monospace";
        marker.style.pointerEvents = "none";
        marker.style.zIndex = "2147483647";
        marker.style.opacity = "0.72";
        marker.textContent = "EB 0";
        document.body.append(marker);
      }
      frontendDebugPaintMarker = marker;
      return marker;
    }

    function mutateFrontendDebugPaintMarker(now) {
      if (now - frontendDebugLastPaintMutationMs < FRONTEND_DEBUG_PAINT_INTERVAL_MS) {
        return;
      }
      const marker = ensureFrontendDebugPaintMarker();
      frontendDebugLastPaintMutationMs = now;
      frontendDebugLastPaintMutationAt = new Date().toISOString();
      frontendDebugPaintSequence += 1;
      frontendDebugPaintExpectedWidth = 34 + (frontendDebugPaintSequence % 2);
      marker.textContent = `EB ${frontendDebugPaintSequence % 1000}`;
      marker.style.width = `${frontendDebugPaintExpectedWidth}px`;
      marker.style.transform = `translateX(${frontendDebugPaintSequence % 2}px)`;
      marker.dataset.frontendDebugPulse = String(frontendDebugPaintSequence);
      document.title = `${frontendDebugBaseTitle} [${frontendDebugPaintSequence}]`;
      const rect = marker.getBoundingClientRect();
      frontendDebugPaintActualWidth = rect.width;
      frontendDebugPaintProbeOk =
        Math.abs(rect.width - frontendDebugPaintExpectedWidth) < 1;
      if (!frontendDebugPaintProbeOk) {
        frontendDebugPaintProbeFailures += 1;
      }
    }

    function scheduleFrontendDebugRafPulse() {
      if (!frontendTelemetryEnabled || !frontendDebugRafPulseActive) {
        return;
      }
      const requestFrame = frontendDebugNativeRequestAnimationFrame ||
        window.requestAnimationFrame.bind(window);
      requestFrame((timestamp) => {
        if (!frontendTelemetryEnabled || !frontendDebugRafPulseActive) {
          return;
        }
        if (frontendDebugRafLastTimestamp) {
          frontendDebugRafMaxGapMs = Math.max(
            frontendDebugRafMaxGapMs,
            timestamp - frontendDebugRafLastTimestamp,
          );
        }
        frontendDebugRafLastTimestamp = timestamp;
        frontendDebugRafTotalFrames += 1;
        frontendDebugRafFramesSinceSnapshot += 1;
        frontendDebugRafLastFrameAt = new Date().toISOString();
        mutateFrontendDebugPaintMarker(timestamp);
        scheduleFrontendDebugRafPulse();
      });
    }

    function frontendDebugRafPayload() {
      const framesSinceSnapshot = frontendDebugRafFramesSinceSnapshot;
      frontendDebugRafFramesSinceSnapshot = 0;
      const lastFrameAgeMs = frontendDebugRafLastTimestamp
        ? Math.max(0, frontendDebugNow() - frontendDebugRafLastTimestamp)
        : null;
      return {
        total_frames: frontendDebugRafTotalFrames,
        frames_since_last_snapshot: framesSinceSnapshot,
        max_gap_ms: Math.round(frontendDebugRafMaxGapMs),
        last_frame_age_ms: lastFrameAgeMs === null
          ? null
          : Math.round(lastFrameAgeMs),
        last_frame_at: frontendDebugRafLastFrameAt,
      };
    }

    function frontendDebugPaintPayload() {
      const lastMutationAgeMs = frontendDebugLastPaintMutationMs
        ? Math.max(0, frontendDebugNow() - frontendDebugLastPaintMutationMs)
        : null;
      return {
        sequence: frontendDebugPaintSequence,
        last_mutation_at: frontendDebugLastPaintMutationAt,
        last_mutation_age_ms: lastMutationAgeMs === null
          ? null
          : Math.round(lastMutationAgeMs),
        expected_width: frontendDebugPaintExpectedWidth,
        actual_width: Math.round(frontendDebugPaintActualWidth * 100) / 100,
        layout_probe_ok: frontendDebugPaintProbeOk,
        layout_probe_failures: frontendDebugPaintProbeFailures,
      };
    }

    function recordFrontendDebugInput(event) {
      if (!frontendTelemetryEnabled) {
        return;
      }
      const type = String(event.type || "event");
      frontendDebugInputCounters[type] =
        (frontendDebugInputCounters[type] || 0) + 1;
      frontendDebugInputLastEvent = type;
      frontendDebugInputLastAt = new Date().toISOString();
      const target = event.target instanceof Element ? event.target : null;
      const leaf = target ? target.closest(".pane-layout-leaf") : null;
      frontendDebugInputLastTarget = target
        ? {
            tag: target.tagName.toLowerCase(),
            id: target.id || "",
            class_name: String(target.className || ""),
            pane_kind: leaf?.dataset.paneKind || "",
            pane_layout_id: leaf?.dataset.paneLayoutId || "",
          }
        : {};
      bumpFrontendDebugCounter(`input.${type}`);
    }

    function frontendDebugInputPayload() {
      return {
        last_event: frontendDebugInputLastEvent,
        last_event_at: frontendDebugInputLastAt,
        last_target: frontendDebugInputLastTarget,
        counters: { ...frontendDebugInputCounters },
        visibility_state: document.visibilityState || "",
        has_focus: document.hasFocus ? document.hasFocus() : false,
      };
    }

    function queueFrontendDebugEvent(queue, event, droppedCounter) {
      if (!frontendTelemetryEnabled) {
        return droppedCounter;
      }
      if (queue.length >= FRONTEND_DEBUG_EVENT_LIMIT) {
        queue.shift();
        droppedCounter += 1;
      }
      queue.push({
        ...event,
        at: event.at || new Date().toISOString(),
      });
      return droppedCounter;
    }

    function recordFrontendDebugLifecycle(event) {
      if (!frontendTelemetryEnabled) {
        return;
      }
      const type = String(event.type || "lifecycle");
      frontendDebugLifecycleLastEvent = type;
      frontendDebugLifecycleLastAt = new Date().toISOString();
      if (type === "freeze") {
        frontendDebugLifecycleFrozen = true;
      } else if (type === "resume" || type === "pageshow") {
        frontendDebugLifecycleFrozen = false;
      }
      frontendDebugLifecycleDroppedEvents = queueFrontendDebugEvent(
        frontendDebugLifecycleEvents,
        {
          type,
          visibility_state: document.visibilityState || "",
          persisted: Boolean(event.persisted),
        },
        frontendDebugLifecycleDroppedEvents,
      );
      bumpFrontendDebugCounter(`lifecycle.${type}`);
      if (type === "freeze" || type === "resume") {
        sendFrontendDebugSnapshot(type);
      }
    }

    function recordFrontendDebugTimerGap(durationMs) {
      frontendDebugLifecycleLastEvent = "timer-gap";
      frontendDebugLifecycleLastAt = new Date().toISOString();
      frontendDebugLifecycleDroppedEvents = queueFrontendDebugEvent(
        frontendDebugLifecycleEvents,
        {
          type: "timer-gap",
          duration_ms: Math.round(durationMs),
          visibility_state: document.visibilityState || "",
          exceeded_workspace_lease: durationMs >= 20_000,
        },
        frontendDebugLifecycleDroppedEvents,
      );
      bumpFrontendDebugCounter("lifecycle.timer-gap");
    }

    function frontendDebugLifecyclePayload() {
      const events = frontendDebugLifecycleEvents.splice(
        0,
        frontendDebugLifecycleEvents.length,
      );
      return {
        frozen: frontendDebugLifecycleFrozen,
        was_discarded: Boolean(document.wasDiscarded),
        last_event: frontendDebugLifecycleLastEvent,
        last_event_at: frontendDebugLifecycleLastAt,
        dropped_events: frontendDebugLifecycleDroppedEvents,
        events,
      };
    }

    function frontendDebugRequestDescription(value) {
      try {
        const raw = value instanceof Request ? value.url : String(value || "");
        const url = new URL(raw, window.location.href);
        return {
          path: url.origin === window.location.origin
            ? url.pathname
            : `${url.origin}${url.pathname}`,
          query_keys: [...new Set(url.searchParams.keys())]
            .filter((key) => key !== "lease_token")
            .sort(),
        };
      } catch (error) {
        return { path: "invalid-url", query_keys: [] };
      }
    }

    function recordFrontendDebugNetworkEvent(event) {
      frontendDebugNetworkDroppedEvents = queueFrontendDebugEvent(
        frontendDebugNetworkEvents,
        event,
        frontendDebugNetworkDroppedEvents,
      );
    }

    function instrumentFrontendDebugFetch() {
      if (frontendDebugFetchInstrumented) {
        return;
      }
      frontendDebugFetchInstrumented = true;
      frontendDebugNativeFetch = window.fetch.bind(window);
      window.fetch = (input, options = {}) => {
        const request = frontendDebugRequestDescription(input);
        if (
          !frontendTelemetryEnabled ||
          request.path === FRONTEND_DEBUG_ENDPOINT
        ) {
          return frontendDebugNativeFetch(input, options);
        }
        frontendDebugFetchSequence += 1;
        const requestId = frontendDebugFetchSequence;
        const method = String(
          options.method || (input instanceof Request ? input.method : "GET"),
        ).toUpperCase();
        const startedAt = frontendDebugNow();
        recordFrontendDebugNetworkEvent({
          type: "fetch-start",
          request_id: requestId,
          method,
          ...request,
        });
        return frontendDebugNativeFetch(input, options).then(
          (response) => {
            frontendDebugFetchMetadata.set(response, {
              request_id: requestId,
              method,
              ...request,
            });
            recordFrontendDebugNetworkEvent({
              type: "fetch-response",
              request_id: requestId,
              method,
              status: response.status,
              ok: response.ok,
              duration_ms: Math.round(frontendDebugNow() - startedAt),
              ...request,
            });
            return response;
          },
          (error) => {
            recordFrontendDebugNetworkEvent({
              type: "fetch-error",
              request_id: requestId,
              method,
              error: String(error).slice(0, 300),
              duration_ms: Math.round(frontendDebugNow() - startedAt),
              ...request,
            });
            throw error;
          },
        );
      };
    }

    function frontendDebugResponseBodyPayload() {
      return {
        pending: frontendDebugResponseBodyPending,
        max_pending: frontendDebugResponseBodyMaxPending,
        drain_started: frontendDebugResponseBodyDrainStarted,
        drain_completed: frontendDebugResponseBodyDrainCompleted,
        drain_failed: frontendDebugResponseBodyDrainFailed,
        request_failed: frontendDebugResponseBodyRequestFailed,
        bytes_drained: frontendDebugResponseBodyBytesDrained,
        last_result: frontendDebugResponseBodyLastResult,
      };
    }

    function discardedFetchResponseDetails(response, details) {
      const metadata = frontendDebugFetchMetadata.get(response) || {};
      return {
        ...metadata,
        ...details,
        status: response.status,
        ok: response.ok,
      };
    }

    async function drainDiscardedFetchResponse(response, details = {}) {
      if (!response) {
        return false;
      }
      const tracked = frontendTelemetryEnabled;
      const description = discardedFetchResponseDetails(response, details);
      const startedAt = frontendDebugNow();
      const bodyUsedBefore = Boolean(response.bodyUsed);
      let bytesDrained = 0;
      let errorMessage = "";
      let succeeded = false;
      if (tracked) {
        frontendDebugResponseBodyPending += 1;
        frontendDebugResponseBodyMaxPending = Math.max(
          frontendDebugResponseBodyMaxPending,
          frontendDebugResponseBodyPending,
        );
        frontendDebugResponseBodyDrainStarted += 1;
        bumpFrontendDebugCounter("responseBody.drainStarted");
        recordFrontendDebugNetworkEvent({
          type: "fetch-body-drain-start",
          body_used_before: bodyUsedBefore,
          pending: frontendDebugResponseBodyPending,
          ...description,
        });
      }
      try {
        if (!bodyUsedBefore) {
          const body = await response.arrayBuffer();
          bytesDrained = body.byteLength;
        }
        succeeded = true;
      } catch (error) {
        errorMessage = String(error).slice(0, 300);
        try {
          if (!response.bodyUsed && response.body) {
            await response.body.cancel();
          }
        } catch (cancelError) {
          errorMessage = `${errorMessage}; cancel: ${String(cancelError)}`.slice(
            0,
            300,
          );
        }
      } finally {
        if (tracked) {
          frontendDebugResponseBodyPending = Math.max(
            0,
            frontendDebugResponseBodyPending - 1,
          );
          const result = {
            ...description,
            body_used_before: bodyUsedBefore,
            body_used_after: Boolean(response.bodyUsed),
            bytes_drained: bytesDrained,
            duration_ms: Math.round(frontendDebugNow() - startedAt),
            pending: frontendDebugResponseBodyPending,
            completed_at: new Date().toISOString(),
          };
          if (succeeded) {
            frontendDebugResponseBodyDrainCompleted += 1;
            frontendDebugResponseBodyBytesDrained += bytesDrained;
            bumpFrontendDebugCounter("responseBody.drainCompleted");
            recordFrontendDebugNetworkEvent({
              type: "fetch-body-drained",
              ...result,
            });
          } else {
            frontendDebugResponseBodyDrainFailed += 1;
            bumpFrontendDebugCounter("responseBody.drainFailed");
            result.error = errorMessage;
            recordFrontendDebugNetworkEvent({
              type: "fetch-body-drain-error",
              ...result,
            });
          }
          frontendDebugResponseBodyLastResult = {
            outcome: succeeded ? "drained" : "error",
            ...result,
          };
        }
      }
      return succeeded;
    }

    function recordDiscardedFetchRequestFailure(details, error) {
      if (!frontendTelemetryEnabled) {
        return;
      }
      const result = {
        ...details,
        error: String(error).slice(0, 300),
        completed_at: new Date().toISOString(),
      };
      frontendDebugResponseBodyRequestFailed += 1;
      frontendDebugResponseBodyLastResult = {
        outcome: "request-error",
        ...result,
      };
      bumpFrontendDebugCounter("responseBody.requestFailed");
      recordFrontendDebugNetworkEvent({
        type: "fetch-body-request-error",
        ...result,
      });
    }

    function frontendDebugNetworkPayload() {
      const events = frontendDebugNetworkEvents.splice(
        0,
        frontendDebugNetworkEvents.length,
      );
      return {
        dropped_events: frontendDebugNetworkDroppedEvents,
        events,
      };
    }

    function frontendDebugPaneKinds() {
      return paneLayoutLeaves().map((leaf) => leaf.kind);
    }

    function frontendDebugMemoryPayload() {
      const memory = window.performance && window.performance.memory;
      if (!memory) {
        return null;
      }
      return {
        js_heap_size_limit: Number(memory.jsHeapSizeLimit || 0),
        total_js_heap_size: Number(memory.totalJSHeapSize || 0),
        used_js_heap_size: Number(memory.usedJSHeapSize || 0),
      };
    }

    function frontendDebugSnapshot(reason) {
      return {
        reason,
        page_id: pageInstanceId,
        tab_id: currentBrowserTabId(),
        workspace_id: contextId,
        workflow_mode: workflowMode,
        active_project_root: activeProjectRoot,
        selected_session_id: selectedSessionId,
        project_shell_running: projectShellRunning,
        progress_requested: progressPaneRequested,
        artifact_requested: artifactPaneRequested,
        pane_kinds: frontendDebugPaneKinds(),
        visible_panes: {
          agent: paneIsVisible(agentOutputPane),
          progress: paneIsVisible(progressOutputPane),
          artifact: paneIsVisible(artifactPreviewPane),
          shell: paneIsVisible(projectShellPane),
          scratch: paneIsVisible(scratchPane),
          status: paneIsVisible(projectStatusPane),
        },
        counters: { ...frontendDebugCounters },
        last_error: frontendDebugLastError,
        max_event_loop_lag_ms: Math.round(frontendDebugMaxEventLoopLagMs),
        long_task_count: frontendDebugLongTaskCount,
        max_long_task_ms: Math.round(frontendDebugMaxLongTaskMs),
        raf: frontendDebugRafPayload(),
        paint_heartbeat: frontendDebugPaintPayload(),
        input: frontendDebugInputPayload(),
        lifecycle: frontendDebugLifecyclePayload(),
        network: frontendDebugNetworkPayload(),
        response_bodies: frontendDebugResponseBodyPayload(),
        dom_nodes: document.getElementsByTagName("*").length,
        memory: frontendDebugMemoryPayload(),
        created_at: new Date().toISOString(),
      };
    }

    function persistFrontendDebugSnapshot(snapshot) {
      try {
        window.localStorage.setItem(
          FRONTEND_DEBUG_STORAGE_KEY,
          JSON.stringify(snapshot),
        );
      } catch (error) {
        // Diagnostics should never affect the main UI.
      }
    }

    function sendFrontendDebugSnapshot(reason, options = {}) {
      if (!frontendTelemetryEnabled) {
        return false;
      }
      const snapshot = frontendDebugSnapshot(reason);
      persistFrontendDebugSnapshot(snapshot);
      const body = JSON.stringify(snapshot);
      const useBeacon = Boolean(options.beacon);
      if (
        useBeacon
        && navigator.sendBeacon
        && navigator.sendBeacon(FRONTEND_DEBUG_ENDPOINT, body)
      ) {
        return true;
      }
      const fetchImpl = frontendDebugNativeFetch || window.fetch.bind(window);
      fetchImpl(FRONTEND_DEBUG_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        keepalive: useBeacon,
      }).then(
        (response) => drainDiscardedFetchResponse(response, {
          operation: "frontend-debug",
          method: "POST",
          path: FRONTEND_DEBUG_ENDPOINT,
          query_keys: [],
        }),
        (error) => recordDiscardedFetchRequestFailure({
          operation: "frontend-debug",
          method: "POST",
          path: FRONTEND_DEBUG_ENDPOINT,
          query_keys: [],
        }, error),
      );
      return true;
    }

    function createDebugEventSourceForUrl(url) {
      if (!frontendTelemetryEnabled) {
        return new EventSource(url);
      }
      bumpFrontendDebugCounter("eventSource.created");
      frontendDebugEventSourceSequence += 1;
      const sourceId = frontendDebugEventSourceSequence;
      const request = frontendDebugRequestDescription(url);
      const source = new EventSource(url);
      const nativeAddEventListener = source.addEventListener.bind(source);
      recordFrontendDebugNetworkEvent({
        type: "event-source-created",
        source_id: sourceId,
        ...request,
      });
      nativeAddEventListener("open", () => {
        bumpFrontendDebugCounter("eventSource.open");
        recordFrontendDebugNetworkEvent({
          type: "event-source-open",
          source_id: sourceId,
          ready_state: source.readyState,
          ...request,
        });
      });
      nativeAddEventListener("error", () => {
        bumpFrontendDebugCounter("eventSource.error");
        recordFrontendDebugNetworkEvent({
          type: "event-source-error",
          source_id: sourceId,
          ready_state: source.readyState,
          ...request,
        });
      });
      source.addEventListener = (type, listener, options) => {
        bumpFrontendDebugCounter(`eventSource.listener.${type}`);
        return nativeAddEventListener(type, (event) => {
          bumpFrontendDebugCounter(`eventSource.event.${type}`);
          if (typeof listener === "function") {
            return listener.call(source, event);
          }
          if (listener && typeof listener.handleEvent === "function") {
            return listener.handleEvent(event);
          }
          return undefined;
        }, options);
      };
      const nativeClose = source.close.bind(source);
      source.close = () => {
        bumpFrontendDebugCounter("eventSource.closed");
        recordFrontendDebugNetworkEvent({
          type: "event-source-closed",
          source_id: sourceId,
          ready_state: source.readyState,
          ...request,
        });
        return nativeClose();
      };
      return source;
    }

    function createDebugEventSource(path) {
      return createDebugEventSourceForUrl(contextUrl(path));
    }

    function recordFrontendDebugError(event) {
      bumpFrontendDebugCounter("window.error");
      frontendDebugLastError = String(event.message || "error").slice(0, 500);
    }

    function recordFrontendDebugUnhandledRejection(event) {
      bumpFrontendDebugCounter("window.unhandledrejection");
      frontendDebugLastError = String(event.reason || "rejection").slice(0, 500);
    }

    function bindFrontendDebugListeners() {
      if (frontendDebugListenersBound) {
        return;
      }
      frontendDebugListenersBound = true;
      window.addEventListener("error", recordFrontendDebugError);
      window.addEventListener(
        "unhandledrejection",
        recordFrontendDebugUnhandledRejection,
      );
      for (const eventName of ["pointerdown", "pointerup", "click", "keydown"]) {
        window.addEventListener(eventName, recordFrontendDebugInput, true);
      }
      window.addEventListener("focus", recordFrontendDebugInput, true);
      window.addEventListener("blur", recordFrontendDebugInput, true);
      document.addEventListener("visibilitychange", recordFrontendDebugInput, true);
      document.addEventListener("visibilitychange", recordFrontendDebugLifecycle, true);
      document.addEventListener("freeze", recordFrontendDebugLifecycle, true);
      document.addEventListener("resume", recordFrontendDebugLifecycle, true);
      window.addEventListener("pagehide", recordFrontendDebugLifecycle, true);
      window.addEventListener("pageshow", recordFrontendDebugLifecycle, true);
    }

    function unbindFrontendDebugListeners() {
      if (!frontendDebugListenersBound) {
        return;
      }
      frontendDebugListenersBound = false;
      window.removeEventListener("error", recordFrontendDebugError);
      window.removeEventListener(
        "unhandledrejection",
        recordFrontendDebugUnhandledRejection,
      );
      for (const eventName of ["pointerdown", "pointerup", "click", "keydown"]) {
        window.removeEventListener(eventName, recordFrontendDebugInput, true);
      }
      window.removeEventListener("focus", recordFrontendDebugInput, true);
      window.removeEventListener("blur", recordFrontendDebugInput, true);
      document.removeEventListener("visibilitychange", recordFrontendDebugInput, true);
      document.removeEventListener("visibilitychange", recordFrontendDebugLifecycle, true);
      document.removeEventListener("freeze", recordFrontendDebugLifecycle, true);
      document.removeEventListener("resume", recordFrontendDebugLifecycle, true);
      window.removeEventListener("pagehide", recordFrontendDebugLifecycle, true);
      window.removeEventListener("pageshow", recordFrontendDebugLifecycle, true);
    }

    function stopFrontendDebugDiagnostics() {
      frontendDebugDiagnosticsStarted = false;
      frontendDebugRafPulseActive = false;
      if (frontendDebugTickTimer) {
        window.clearInterval(frontendDebugTickTimer);
        frontendDebugTickTimer = null;
      }
      if (frontendDebugSendTimer) {
        window.clearInterval(frontendDebugSendTimer);
        frontendDebugSendTimer = null;
      }
      if (frontendDebugLongTaskObserver) {
        frontendDebugLongTaskObserver.disconnect();
        frontendDebugLongTaskObserver = null;
      }
      unbindFrontendDebugListeners();
      if (frontendDebugPaintMarker) {
        frontendDebugPaintMarker.remove();
        frontendDebugPaintMarker = null;
      }
      if (document.title !== frontendDebugBaseTitle) {
        document.title = frontendDebugBaseTitle;
      }
    }

    function startFrontendDebugDiagnostics() {
      if (!frontendTelemetryEnabled) {
        stopFrontendDebugDiagnostics();
        return;
      }
      if (frontendDebugDiagnosticsStarted) {
        return;
      }
      frontendDebugDiagnosticsStarted = true;
      frontendDebugRafPulseActive = true;
      instrumentFrontendDebugFrames();
      instrumentFrontendDebugFetch();
      ensureFrontendDebugPaintMarker();
      scheduleFrontendDebugRafPulse();
      frontendDebugLastTick = frontendDebugNow();
      if (!frontendDebugTickTimer) {
        frontendDebugTickTimer = window.setInterval(() => {
          const now = frontendDebugNow();
          const lag = Math.max(
            0,
            now - frontendDebugLastTick - FRONTEND_DEBUG_EVENT_LOOP_INTERVAL_MS,
          );
          frontendDebugLastTick = now;
          bumpFrontendDebugCounter("eventLoop.tick");
          if (lag > 50) {
            bumpFrontendDebugCounter("eventLoop.lag");
            frontendDebugMaxEventLoopLagMs = Math.max(
              frontendDebugMaxEventLoopLagMs,
              lag,
            );
          }
          if (lag >= FRONTEND_DEBUG_SUSPENSION_GAP_MS) {
            recordFrontendDebugTimerGap(lag);
          }
        }, FRONTEND_DEBUG_EVENT_LOOP_INTERVAL_MS);
      }
      if (
        !frontendDebugLongTaskObserver &&
        window.PerformanceObserver &&
        PerformanceObserver.supportedEntryTypes &&
        PerformanceObserver.supportedEntryTypes.includes("longtask")
      ) {
        try {
          frontendDebugLongTaskObserver = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              frontendDebugLongTaskCount += 1;
              frontendDebugMaxLongTaskMs = Math.max(
                frontendDebugMaxLongTaskMs,
                Number(entry.duration || 0),
              );
            }
          });
          frontendDebugLongTaskObserver.observe({ entryTypes: ["longtask"] });
        } catch (error) {
          frontendDebugLongTaskObserver = null;
        }
      }
      if (!frontendDebugSendTimer) {
        frontendDebugSendTimer = window.setInterval(
          () => sendFrontendDebugSnapshot("interval"),
          FRONTEND_DEBUG_INTERVAL_MS,
        );
      }
      bindFrontendDebugListeners();
    }

    const frontendTelemetryRuntime = Object.freeze({
      isEnabled: frontendTelemetryIsEnabled,
      setEnabled: setFrontendTelemetryEnabled,
      enable() {
        return setFrontendTelemetryEnabled(true);
      },
      disable() {
        return setFrontendTelemetryEnabled(false);
      },
      snapshot(reason = "manual") {
        return frontendDebugSnapshot(reason);
      },
      sendSnapshot(reason = "manual") {
        return sendFrontendDebugSnapshot(reason);
      },
      storageKey: FRONTEND_TELEMETRY_STORAGE_KEY,
      queryKeys() {
        return [...FRONTEND_TELEMETRY_QUERY_KEYS];
      },
    });

    function queueWorkspaceStateSave(delay = 250) {
      bumpFrontendDebugCounter("workspaceStateSave.queued");
      if (workspaceStateHydrating || !contextId || !workspaceLeaseToken) {
        return;
      }
      if (workspaceAllowsSharedConnections()) {
        window.sessionStorage.setItem(
          workspaceClientStateStorageKey(),
          JSON.stringify(workspaceClientState()),
        );
        return;
      }
      window.clearTimeout(workspaceStateSaveTimer);
      workspaceStateSaveTimer = window.setTimeout(() => {
        bumpFrontendDebugCounter("workspaceStateSave.sent");
        fetch(contextUrl("/api/workspaces/state"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(workspaceClientState()),
        }).catch(() => {});
      }, delay);
    }

    function applyWorkspaceClientState(payload) {
      let state = payload && payload.workspace_client_state;
      let shouldPersistRestoredState = false;
      let shouldRenderRestoredPaneLayout = false;
      if (workspaceAllowsSharedConnections()) {
        try {
          state = JSON.parse(
            window.sessionStorage.getItem(workspaceClientStateStorageKey()) ||
              "null",
          );
        } catch (error) {
          state = null;
        }
      }
      if (!state || typeof state !== "object") {
        return;
      }
      workspaceStateHydrating = true;
      try {
        if (state.pane_layout) {
          const restored = restoredPaneLayoutForWorkflow(
            normalizePaneLayoutNode(state.pane_layout, new Set()),
          );
          if (restored) {
            paneLayout = restored;
            shouldRenderRestoredPaneLayout = paneLayoutIsMounted();
            shouldPersistRestoredState = true;
            workspacePresentationStorage().setItem(
              paneLayoutStorageKey(),
              JSON.stringify(restored),
            );
          }
        }
        if (Array.isArray(state.open_documents)) {
          openDocumentTargets = state.open_documents.filter(
            (target) => target && target.path,
          ).map((target) => ({
            label: String(target.label || target.path),
            path: String(target.path),
          }));
          shouldPersistRestoredState = true;
        }
        if (typeof state.scratchpad === "string") {
          scratchPad.value = state.scratchpad;
          saveScratchPad();
          shouldPersistRestoredState = true;
        }
      } finally {
        workspaceStateHydrating = false;
      }
      if (shouldRenderRestoredPaneLayout) {
        bumpFrontendDebugCounter("paneLayout.hydrateRender");
        renderPaneLayout();
      }
      if (shouldPersistRestoredState) {
        queueWorkspaceStateSave(0);
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

    function ensureActivePaneLayoutLeaf(preferredKind = "") {
      if (paneLayoutLeafById(activePaneLayoutLeafId)) {
        return;
      }
      const preferred = preferredKind ? paneLayoutLeafByKind(preferredKind) : null;
      const fallback = preferred || paneLayoutLeaves()[0] || null;
      activePaneLayoutLeafId = fallback ? fallback.id : "";
    }

    function setActivePaneLayoutLeaf(id) {
      const leaf = paneLayoutLeafById(String(id || ""));
      if (!leaf) {
        ensureActivePaneLayoutLeaf();
        return;
      }
      activePaneLayoutLeafId = leaf.id;
      for (const element of outputWorkbench.querySelectorAll(
        ".pane-layout-leaf",
      )) {
        element.classList.toggle(
          "active",
          element.dataset.paneLayoutId === activePaneLayoutLeafId,
        );
      }
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

    function paneLayoutKindAvailable(kind, leaf = null) {
      if (SINGLETON_PANE_LAYOUT_KINDS.has(kind)) {
        const existingLeaf = paneLayoutLeafByKind(kind);
        return !existingLeaf || existingLeaf === leaf;
      }
      if (kind === "agenda") {
        return Boolean(window.ElectroBoyFrontend?.module("agenda"));
      }
      if (kind === "calendar") {
        return Boolean(window.ElectroBoyFrontend?.module("calendar"));
      }
      return true;
    }

    function markPaneLayoutControl(element) {
      element.dataset.paneDragIgnore = "true";
      element.addEventListener("pointerdown", (event) => {
        event.stopPropagation();
      });
      element.addEventListener("click", (event) => {
        event.stopPropagation();
      });
    }

    function bindPaneLayoutCommand(button, handler) {
      markPaneLayoutControl(button);
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        handler();
      });
    }

    function buildPaneLayoutToolbar(leaf) {
      const toolbar = document.createElement("div");
      toolbar.className = "pane-layout-toolbar";
      toolbar.dataset.paneDragHandle = "true";
      toolbar.title = "Drag title or Ctrl-drag pane to move";

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
        option.disabled = !paneLayoutKindAvailable(kind, leaf);
        select.append(option);
      }
      select.value = leaf.kind;
      markPaneLayoutControl(select);
      select.addEventListener("change", () => {
        setActivePaneLayoutLeaf(leaf.id);
        changePaneLayoutKind(leaf.id, select.value);
      });

      const splitRight = document.createElement("button");
      splitRight.className = "pane-layout-command split-right";
      splitRight.type = "button";
      splitRight.title = "Split pane right";
      splitRight.setAttribute("aria-label", "Split pane right");
      bindPaneLayoutCommand(splitRight, () => splitPaneLayoutLeaf(leaf.id, "row"));

      const splitDown = document.createElement("button");
      splitDown.className = "pane-layout-command split-down";
      splitDown.type = "button";
      splitDown.title = "Split pane down";
      splitDown.setAttribute("aria-label", "Split pane down");
      bindPaneLayoutCommand(
        splitDown,
        () => splitPaneLayoutLeaf(leaf.id, "column"),
      );

      const close = document.createElement("button");
      close.className = "pane-layout-command close-pane";
      close.type = "button";
      close.title = "Close pane and join area";
      close.setAttribute("aria-label", "Close pane and join area");
      close.textContent = "×";
      close.disabled = paneLayoutLeaves().length <= 1;
      bindPaneLayoutCommand(close, () => closePaneLayoutLeaf(leaf.id));

      const reset = document.createElement("button");
      reset.className = "pane-layout-command reset-layout";
      reset.type = "button";
      reset.title = "Reset pane layout";
      reset.setAttribute("aria-label", "Reset pane layout");
      reset.textContent = "↺";
      bindPaneLayoutCommand(reset, resetPaneLayout);

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
      const resizeController = window.ElectroBoySplitResize
        ? window.ElectroBoySplitResize.create({
          layout: paneLayout,
          node,
          splitElement,
          startX: event.clientX,
          startY: event.clientY,
          elementForNode(candidate) {
            return outputWorkbench.querySelector(
              `[data-pane-layout-id="${candidate.id}"]`,
            );
          },
          applyTemplate: applyPaneLayoutSplitTemplate,
          afterUpdate: fitTerminal,
        })
        : null;
      const update = (moveEvent) => {
        if (resizeController && resizeController.update(moveEvent)) {
          return;
        }
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

    function paneLayoutArtifactIsProjectScoped(item) {
      if (!item || typeof item !== "object") {
        return false;
      }
      if (item.kind === "agenda" || item.kind === "calendar") {
        return false;
      }
      if (item.kind === "corkboard" || item.kind === "creative-corkboard") {
        const board = item.board || item.folder || item.corkboard || {};
        const provider = String(board.provider || item.provider || "").trim();
        return !provider ||
          provider === "creative-files" ||
          provider === "project-files";
      }
      return true;
    }

    function paneLayoutRequestedArtifact(leaf) {
      if (leaf.kind !== "artifact") {
        return undefined;
      }
      const content = leaf.content && typeof leaf.content === "object"
        ? leaf.content
        : null;
      if (!content) {
        return null;
      }
      if (!paneLayoutArtifactIsProjectScoped(content)) {
        return content;
      }
      return activeProjectRoot && leaf.projectRoot === activeProjectRoot
        ? content
        : null;
    }

    function paneLayoutRequestedContent(leaf) {
      if (leaf.kind === "agent") {
        return leaf.content && typeof leaf.content === "object"
          ? leaf.content
          : null;
      }
      if (leaf.kind === "agenda") {
        return leaf.content && typeof leaf.content === "object"
          ? leaf.content
          : null;
      }
      if (leaf.kind === "calendar") {
        return leaf.content && typeof leaf.content === "object"
          ? leaf.content
          : null;
      }
      return paneLayoutRequestedArtifact(leaf);
    }

    function paneLayoutInstanceUrl(leaf) {
      const requestedContent = paneLayoutRequestedContent(leaf);
      const paneOptions = leaf.kind === "agent"
        ? { sessionId: String(requestedContent?.sessionId || selectedSessionId || "") }
        : {};
      const url = new URL(
        paneUrl(leaf.kind, requestedContent, paneOptions),
        window.location.origin,
      );
      url.searchParams.set("embedded", "1");
      url.searchParams.set("pane_instance_id", leaf.id);
      return `${url.pathname}${url.search}`;
    }

    function buildPaneLayoutInstanceFrame(leaf) {
      const frame = document.createElement("iframe");
      frame.className = "pane-layout-instance-frame";
      frame.title = `${PANE_LAYOUT_KINDS[leaf.kind].label} pane`;
      frame.src = paneLayoutInstanceUrl(leaf);
      frame.addEventListener("load", () => {
        frame.dataset.paneLoaded = "1";
      });
      frame.addEventListener("focus", () => {
        setActivePaneLayoutLeaf(leaf.id);
      });
      return frame;
    }

    function updateLoadedPaneLayoutFrame(frame, leaf, nextUrl) {
      if (
        (leaf.kind !== "agent" && !INSTANCE_PANE_LAYOUT_KINDS.has(leaf.kind)) ||
        frame.dataset.paneLoaded !== "1" ||
        !frame.contentWindow
      ) {
        return false;
      }
      const currentUrl = new URL(frame.src, window.location.origin);
      if (
        currentUrl.pathname !== nextUrl.pathname ||
        currentUrl.searchParams.get("context_id") !==
          nextUrl.searchParams.get("context_id")
      ) {
        return false;
      }
      frame.contentWindow.postMessage(
        leaf.kind === "agent"
          ? {
            type: "electroboy:pane-set-agent-session",
            paneInstanceId: leaf.id,
            sessionId: String(
              paneLayoutRequestedContent(leaf)?.sessionId || selectedSessionId || "",
            ),
          }
          : {
            type: leaf.kind === "artifact"
              ? "electroboy:pane-set-artifact"
              : "electroboy:pane-set-content",
            paneInstanceId: leaf.id,
            item: paneLayoutRequestedContent(leaf),
          },
        window.location.origin,
      );
      return true;
    }

    function refreshPaneLayoutInstanceFrames() {
      if (!paneLayout) {
        return;
      }
      for (const frame of outputWorkbench.querySelectorAll(
        ".pane-layout-instance-frame",
      )) {
        const leafElement = frame.closest(".pane-layout-leaf");
        const leaf = paneLayoutLeafById(leafElement?.dataset.paneLayoutId || "");
        if (!leaf) {
          continue;
        }
        const nextUrl = new URL(
          paneLayoutInstanceUrl(leaf),
          window.location.origin,
        );
        if (updateLoadedPaneLayoutFrame(frame, leaf, nextUrl)) {
          continue;
        }
        if (frame.src !== nextUrl.href) {
          frame.dataset.paneLoaded = "";
          frame.src = nextUrl.href;
        }
      }
    }

    function renderPaneLayoutNode(node, renderedKinds = new Set()) {
      if (node.type === "leaf") {
        const leaf = document.createElement("div");
        leaf.className = "pane-layout-leaf";
        leaf.dataset.paneLayoutId = node.id;
        leaf.dataset.paneKind = node.kind;
        leaf.classList.toggle("active", node.id === activePaneLayoutLeafId);
        leaf.addEventListener("pointerdown", () => {
          setActivePaneLayoutLeaf(node.id);
        });
        leaf.addEventListener("focusin", () => {
          setActivePaneLayoutLeaf(node.id);
        });
        leaf.append(buildPaneLayoutToolbar(node));
        if (node.kind === "empty") {
          const empty = document.createElement("div");
          empty.className = "pane-layout-empty";
          empty.textContent = "Choose a pane type";
          leaf.append(empty);
        } else if (
          INSTANCE_PANE_LAYOUT_KINDS.has(node.kind) ||
          (node.kind === "agent" && Boolean(node.content?.sessionId)) ||
          renderedKinds.has(node.kind)
        ) {
          leaf.append(buildPaneLayoutInstanceFrame(node));
        } else {
          renderedKinds.add(node.kind);
          const paneElement = PANE_LAYOUT_KINDS[node.kind].element;
          for (const header of paneElement.querySelectorAll(
            ".pane-header, .side-pane-header",
          )) {
            header.dataset.paneDragHandle = "true";
            header.title = "Drag title or Ctrl-drag pane to move";
          }
          leaf.append(paneElement);
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
      const first = renderPaneLayoutNode(node.first, renderedKinds);
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
      const second = renderPaneLayoutNode(node.second, renderedKinds);
      split.append(first, divider, second);
      applyPaneLayoutSplitTemplate(split, node);
      return split;
    }

    function refreshPaneLayoutVisibility(node = paneLayout, element = outputWorkbench.firstElementChild) {
      if (element === outputWorkbench.firstElementChild) {
        bumpFrontendDebugCounter("paneLayout.refreshVisibility");
      }
      if (!node || !element) {
        return false;
      }
      if (node.type === "leaf") {
        const isInstance = Boolean(element.querySelector(".pane-layout-instance-frame"));
        const visible = !poppedPaneLeafIds.has(node.id) &&
          !poppedPanes.has(node.kind) && (
          node.kind === "empty" || isInstance ||
          !PANE_LAYOUT_KINDS[node.kind].element.hidden
        );
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
      bumpFrontendDebugCounter("paneLayout.render");
      if (paneCornerSplitCancel) {
        paneCornerSplitCancel();
      }
      ensureActivePaneLayoutLeaf();
      const root = renderPaneLayoutNode(paneLayout);
      root.classList.add("pane-layout-root");
      outputWorkbench.replaceChildren(root);
      refreshPaneLayoutVisibility();
      scheduleFitTerminal();
    }

    function splitPaneLayoutLeaf(id, direction, ratio = 0.5, emptyFirst = false) {
      const leaf = paneLayoutLeafById(id);
      if (!leaf) {
        return;
      }
      const existingLeaf = { ...leaf };
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
      if (!paneLayoutKindAvailable(kind, leaf)) {
        return;
      }
      const previousKind = leaf.kind;
      leaf.kind = kind;
      setActivePaneLayoutLeaf(leaf.id);
      savePaneLayout();
      renderPaneLayout();
      const manualChangeOptions = {
        ensureRequestedPanes: false,
        updateOutputSplit: false,
      };
      activatePaneLayoutKind(kind, manualChangeOptions);
      if (previousKind !== kind && !paneLayoutLeafByKind(previousKind)) {
        deactivatePaneLayoutKind(previousKind, manualChangeOptions);
      }
    }

    function closePaneLayoutLeaf(id) {
      bumpFrontendDebugCounter("paneLayout.closeClick");
      if (paneLayoutLeaves().length <= 1) {
        bumpFrontendDebugCounter("paneLayout.closeSkippedLastLeaf");
        return;
      }
      const leaf = paneLayoutLeafById(id);
      if (!leaf) {
        bumpFrontendDebugCounter("paneLayout.closeSkippedMissingLeaf");
        return;
      }
      const removedKind = leaf.kind;
      paneLayout = removePaneLayoutLeaf(paneLayout, id);
      if (activePaneLayoutLeafId === id) {
        activePaneLayoutLeafId = paneLayoutLeaves()[0]?.id || "";
      }
      savePaneLayout();
      renderPaneLayout();
      bumpFrontendDebugCounter("paneLayout.closeRemoved");
      if (!paneLayoutLeafByKind(removedKind)) {
        deactivatePaneLayoutKind(removedKind);
      }
    }

    function movePaneLayoutLeaf(sourceId, targetId, position) {
      const source = paneLayoutLeafById(sourceId);
      const target = paneLayoutLeafById(targetId);
      if (!source || !target || source === target) {
        return;
      }
      if (position === "center") {
        const sourceKind = source.kind;
        source.kind = target.kind;
        target.kind = sourceKind;
        const sourceContent = source.content;
        source.content = target.content;
        target.content = sourceContent;
        const sourceProjectRoot = source.projectRoot;
        source.projectRoot = target.projectRoot;
        target.projectRoot = sourceProjectRoot;
      } else {
        const movedLeaf = { ...source };
        paneLayout = removePaneLayoutLeaf(paneLayout, sourceId);
        const remainingTarget = paneLayoutLeafById(targetId);
        if (!remainingTarget) {
          return;
        }
        const direction = position === "left" || position === "right"
          ? "row"
          : "column";
        const movedFirst = position === "left" || position === "top";
        const replacement = paneLayoutSplit(
          direction,
          movedFirst ? movedLeaf : remainingTarget,
          movedFirst ? remainingTarget : movedLeaf,
        );
        paneLayout = replacePaneLayoutNode(
          paneLayout,
          remainingTarget.id,
          replacement,
        );
      }
      savePaneLayout();
      renderPaneLayout();
    }

    function activatePaneLayoutKind(kind, options = {}) {
      if (poppedPanes.has(kind)) {
        dockPoppedPane(kind);
      }
      if (kind === "progress") {
        showProgressPane(true, options);
      } else if (kind === "artifact") {
        artifactPaneRequested = true;
        applyOutputPaneVisibility(options);
      } else if (kind === "agenda") {
        refreshPaneLayoutInstanceFrames();
      } else if (kind === "calendar") {
        refreshPaneLayoutInstanceFrames();
      } else if (kind === "shell") {
        showProjectShellPane(true);
      }
    }

    function deactivatePaneLayoutKind(kind, options = {}) {
      if (kind === "progress") {
        showProgressPane(false, options);
      } else if (kind === "artifact") {
        artifactPaneRequested = false;
        applyOutputPaneVisibility(options);
      } else if (kind === "shell") {
        hideProjectShellPane();
      }
    }

    function ensurePaneInLayout(kind, targetKind = "agent", direction = "row", options = {}) {
      if (!paneLayout) {
        return;
      }
      const existing = paneLayoutLeafByKind(kind);
      if (existing) {
        setActivePaneLayoutLeaf(existing.id);
        if (options.activateExisting !== false) {
          activatePaneLayoutKind(kind);
        }
        return;
      }
      const activeLeaf = paneLayoutLeafById(activePaneLayoutLeafId);
      const availableEmpty = activeLeaf && activeLeaf.kind === "empty"
        ? activeLeaf
        : paneLayoutLeafByKind("empty");
      if (availableEmpty) {
        availableEmpty.kind = kind;
        availableEmpty.content = null;
        availableEmpty.projectRoot = "";
        setActivePaneLayoutLeaf(availableEmpty.id);
        savePaneLayout();
        renderPaneLayout();
        activatePaneLayoutKind(kind);
        return;
      }
      const target = paneLayoutLeafByKind(targetKind) || paneLayoutLeaves()[0];
      if (!target) {
        paneLayout = paneLayoutLeaf(kind);
        activePaneLayoutLeafId = paneLayout.id;
      } else {
        const newLeaf = paneLayoutLeaf(kind);
        const replacement = paneLayoutSplit(
          direction,
          { ...target },
          newLeaf,
        );
        paneLayout = replacePaneLayoutNode(paneLayout, target.id, replacement);
        activePaneLayoutLeafId = newLeaf.id;
      }
      savePaneLayout();
      renderPaneLayout();
    }

    function clonePaneLayoutContent(content) {
      if (!content || typeof content !== "object") {
        return null;
      }
      try {
        return JSON.parse(JSON.stringify(content));
      } catch (error) {
        return null;
      }
    }

    function assignArtifactToPane(item, requestedLeafId = "") {
      if (item && item.kind === "agenda") {
        assignPaneContent("agenda", item, requestedLeafId);
        return;
      }
      if (item && item.kind === "calendar") {
        assignPaneContent("calendar", item, requestedLeafId);
        return;
      }
      assignPaneContent("artifact", item, requestedLeafId);
    }

    function assignPaneContent(kind, item, requestedLeafId = "") {
      if (!INSTANCE_PANE_LAYOUT_KINDS.has(kind)) {
        return;
      }
      let leaf = paneLayoutLeafById(requestedLeafId || activePaneLayoutLeafId);
      if (!leaf || leaf.kind !== kind) {
        leaf = paneLayoutLeafByKind(kind);
      }
      if (!leaf) {
        ensurePaneInLayout(kind, "agent", "row");
        leaf = paneLayoutLeafByKind(kind);
      }
      if (!leaf) {
        return;
      }
      leaf.content = clonePaneLayoutContent(item);
      leaf.projectRoot = activeProjectRoot;
      setActivePaneLayoutLeaf(leaf.id);
      savePaneLayout();
      refreshPaneLayoutInstanceFrames();
    }

    function handlePaneLayoutMessage(event) {
      if (event.origin !== window.location.origin) {
        return;
      }
      const message = event.data;
      if (!message) {
        return;
      }
      const leaf = paneLayoutLeafById(String(message.paneInstanceId || ""));
      if (!leaf) {
        return;
      }
      if (message.type === "electroboy:pane-activate") {
        setActivePaneLayoutLeaf(leaf.id);
        return;
      }
      if (
        message.type === "electroboy:pane-agent-session-change" &&
        leaf.kind === "agent"
      ) {
        const sessionId = String(message.sessionId || "");
        if (!sessionId) {
          return;
        }
        leaf.content = { sessionId };
        leaf.projectRoot = activeProjectRoot;
        setActivePaneLayoutLeaf(leaf.id);
        savePaneLayout();
        return;
      }
      if (
        message.type !== "electroboy:pane-artifact-change" ||
        !INSTANCE_PANE_LAYOUT_KINDS.has(leaf.kind)
      ) {
        return;
      }
      leaf.content = clonePaneLayoutContent(message.item);
      leaf.projectRoot = activeProjectRoot;
      setActivePaneLayoutLeaf(leaf.id);
      savePaneLayout();
    }

    function resetPaneLayout() {
      paneLayout = defaultPaneLayout(workflowMode);
      savePaneLayout();
      renderPaneLayout();
      if (progressPaneRequested) {
        ensurePaneInLayout("progress", "agent", "row", { activateExisting: false });
      }
      if (artifactPaneRequested && artifactPreviewItems.length > 0) {
        ensurePaneInLayout("artifact", "agent", "row", { activateExisting: false });
      }
      if (projectShellPaneRequested) {
        ensurePaneInLayout("shell", "agent", "column", { activateExisting: false });
      }
    }

    function loadPaneLayoutForWorkflow(mode = workflowMode) {
      paneLayout = storedPaneLayout(mode);
      activePaneLayoutLeafId = paneLayoutLeaves()[0]?.id || "";
      renderPaneLayout();
    }

    function initializePaneDragController() {
      if (paneDragController || !window.ElectroBoyPaneDrag) {
        return;
      }
      paneDragController = window.ElectroBoyPaneDrag.createController({
        root: outputWorkbench,
        source(element) {
          const id = String(element.dataset.paneLayoutId || "");
          const leaf = paneLayoutLeafById(id);
          if (!leaf) {
            return null;
          }
          return {
            id: leaf.id,
            kind: leaf.kind,
            label: PANE_LAYOUT_KINDS[leaf.kind]?.label || "Pane",
          };
        },
        canDrag(source) {
          return source.kind !== "empty" && Boolean(PANE_LAYOUT_KINDS[source.kind]);
        },
        label(source) {
          return source.label;
        },
        onDrop(source, target, position) {
          movePaneLayoutLeaf(source.id, target.id, position);
        },
        onDetach(source) {
          const leaf = paneLayoutLeafById(source.id);
          if (leaf) {
            popOutPaneLayoutLeaf(leaf);
          }
        },
      });
    }

    function initializePaneLayout() {
      outputWorkbench.classList.add("pane-layout-enabled");
      initializePaneDragController();
      loadPaneLayoutForWorkflow();
      window.addEventListener("message", handlePaneLayoutMessage);
      paneLayoutObserver = new MutationObserver(() => {
        bumpFrontendDebugCounter("mutationObserver.paneLayout");
        refreshPaneLayoutVisibility();
      });
      for (const definition of Object.values(PANE_LAYOUT_KINDS)) {
        if (!definition.element) {
          continue;
        }
        paneLayoutObserver.observe(definition.element, {
          attributes: true,
          attributeFilter: ["hidden"],
        });
      }
    }

    function storedTerminalFontSize() {
      try {
        const stored = fontSizeFromValue(
          window.localStorage.getItem(TERMINAL_FONT_STORAGE_KEY),
        );
        if (stored !== null) {
          return stored;
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
        if (Number.isFinite(stored) && terminalFontSize + stored > 0) {
          return stored;
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

    function fontSizeFromValue(value) {
      const normalized = String(value ?? "")
        .trim()
        .replace(/px$/i, "")
        .trim();
      const parsed = Number(normalized);
      return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
    }

    function displayFontSize(value) {
      return `${value}px`;
    }

    function bindFontSizeInput(input, currentValue, applyValue) {
      if (!input) {
        return;
      }
      let cancelBlurCommit = false;
      const restore = () => {
        input.value = displayFontSize(currentValue());
      };
      const commit = () => {
        if (!applyValue(input.value)) {
          restore();
        }
      };
      input.addEventListener("focus", () => input.select());
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          input.blur();
          return;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopImmediatePropagation();
          cancelBlurCommit = true;
          restore();
          input.blur();
        }
      });
      input.addEventListener("blur", () => {
        if (cancelBlurCommit) {
          cancelBlurCommit = false;
          return;
        }
        commit();
      });
    }

    function paneFontOffset(pane) {
      return paneFontOffsets[pane] || 0;
    }

    function effectivePaneFontSize(pane) {
      const value = terminalFontSize + paneFontOffset(pane);
      return value > 0 ? value : terminalFontSize;
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
      if (pane === "progress") {
        return window.ElectroBoyFrontend.invokeModule("progress", "terminal");
      }
      if (pane === "shell") {
        return window.ElectroBoyFrontend.invokeModule("project-shell", "terminal");
      }
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

    function workflowSideSheetTextWidth(element, text = element.textContent || "") {
      const value = String(text).trim();
      if (!value) {
        return 0;
      }
      workflowSideSheetTextCanvas ||= document.createElement("canvas");
      const context = workflowSideSheetTextCanvas.getContext("2d");
      if (!context) {
        return 0;
      }
      const style = window.getComputedStyle(element);
      context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      return context.measureText(value).width;
    }

    function measuredWorkflowSideSheetMinimumWidth() {
      let widestText = 0;
      const textElements = stageActionBody.querySelectorAll(
        ".stage-action-label, .stage-action-heading, .stage-action-button",
      );
      for (const element of textElements) {
        widestText = Math.max(widestText, workflowSideSheetTextWidth(element));
      }
      for (const option of workflowModeSelect.options) {
        widestText = Math.max(
          widestText,
          workflowSideSheetTextWidth(workflowModeSelect, option.textContent),
        );
      }
      return Math.max(
        MIN_WORKFLOW_SIDE_SHEET_WIDTH,
        Math.ceil(widestText + 96),
      );
    }

    function updateWorkflowSideSheetMinimumWidth() {
      if (workflowSideSheetCollapsed) {
        return MIN_WORKFLOW_SIDE_SHEET_WIDTH;
      }
      const minimum = measuredWorkflowSideSheetMinimumWidth();
      shell.style.setProperty("--workflow-side-sheet-min-width", `${minimum}px`);
      return minimum;
    }

    function applyStoredWorkflowSideSheetWidth() {
      const stored = storedNumber(WORKFLOW_SIDE_SHEET_WIDTH_STORAGE_KEY);
      if (!stored) {
        return;
      }
      const minimum = updateWorkflowSideSheetMinimumWidth();
      const maximum = Math.max(minimum, shell.clientWidth - MIN_WORKFLOW_CONTENT_WIDTH);
      shell.style.setProperty(
        "--workflow-side-sheet-width",
        `${clampValue(stored, minimum, maximum)}px`,
      );
    }

    function initializeWorkflowSideSheetResize() {
      workflowSideSheetMutationObserver = new MutationObserver(() => {
        bumpFrontendDebugCounter("mutationObserver.workflowSideSheet");
        window.requestAnimationFrame(updateWorkflowSideSheetMinimumWidth);
      });
      workflowSideSheetMutationObserver.observe(stageActionBody, {
        childList: true,
        subtree: true,
        characterData: true,
      });
      updateWorkflowSideSheetMinimumWidth();
    }

    function applyStoredPaneSizes() {
      applyStoredWorkflowSideSheetWidth();
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
        activeWorkflowSetting("rightPaneStorageKey", RIGHT_PANE_WIDTH_STORAGE_KEY),
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
        activeWorkflowSetting("rightPaneStorageKey", RIGHT_PANE_WIDTH_STORAGE_KEY),
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
      if (invokeActiveWorkflowHook("restoreScratchPad") === true) {
        return;
      }
      const storageKey = scratchPadStorageKey();
      if (!storageKey) {
        scratchPad.value = "";
        restoredScratchContextId = "";
        return;
      }
      try {
        scratchPad.value = workspacePresentationStorage().getItem(storageKey) || "";
        restoredScratchContextId = contextId;
      } catch (error) {
        scratchPad.value = "";
      }
    }

    function saveScratchPad() {
      if (invokeActiveWorkflowHook("saveScratchPad") === true) {
        return;
      }
      const storageKey = scratchPadStorageKey();
      if (!storageKey) {
        return;
      }
      try {
        workspacePresentationStorage().setItem(storageKey, scratchPad.value);
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
        return window.localStorage.getItem(WORKFLOW_MODE_STORAGE_KEY) || "";
      } catch (error) {
        return "";
      }
    }

    function registeredWorkflows() {
      const frontend = window.ElectroBoyFrontend;
      if (!frontend || typeof frontend.workflow !== "function") {
        return [];
      }
      return activeWorkflowDefinitions
        .filter((definition) => frontend.workflow(definition.id))
        .map((definition) => ({
          ...frontend.workflow(definition.id),
          definition,
          id: definition.id,
          label: definition.label,
        }));
    }

    async function loadWorkflowRegistry() {
      const response = await fetch("/api/registry", { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`workflow registry failed: ${response.status}`);
      }
      const payload = await response.json();
      activeModuleDefinitions = Array.isArray(payload.modules)
        ? payload.modules
        : [];
      activeWorkflowDefinitions = Array.isArray(payload.workflows)
        ? payload.workflows
        : [];
    }

    function workflowDefinition(workflowId = workflowMode) {
      return activeWorkflowDefinitions.find(
        (definition) => definition.id === workflowId,
      ) || null;
    }

    function activeWorkflowContribution() {
      return window.ElectroBoyFrontend.workflowForSelection(workflowMode);
    }

    function workflowHasCapability(capability) {
      const contribution = activeWorkflowContribution();
      return Boolean(
        contribution &&
        Array.isArray(contribution.capabilities) &&
        contribution.capabilities.includes(capability),
      );
    }

    function renderWorkflowModeOptions() {
      const workflows = registeredWorkflows();
      workflowModeSelect.replaceChildren();
      if (workflows.length === 0) {
        const option = document.createElement("option");
        option.textContent = "No workflows installed";
        option.value = "";
        workflowModeSelect.append(option);
        workflowModeSelect.disabled = true;
        workflowMode = "";
        return;
      }
      workflows.forEach((workflow) => {
        const option = document.createElement("option");
        const provider = String(workflow.definition.provider || "").trim();
        const entryPoint = String(workflow.definition.entry_point || "").trim();
        option.value = workflow.id;
        option.textContent = workflow.label;
        option.title = entryPoint
          ? `Provided by ${provider || "installed plugin"}: ${entryPoint}`
          : `Provided by ${provider || "the service"}`;
        option.dataset.provider = provider;
        option.dataset.entryPoint = entryPoint;
        workflowModeSelect.append(option);
      });
      const stored = workflowMode;
      const selected = workflows.find(
        (workflow) => workflow.id === stored || workflow.mode === stored,
      ) || workflows[0];
      workflowMode = selected.id;
      workflowModeSelect.value = workflowMode;
      workflowModeSelect.disabled = workflows.length < 2;
      const workflowProvider = String(selected.definition.provider || "the service");
      const moduleProviders = activeModuleDefinitions
        .filter((module) => selected.definition.modules.includes(module.id))
        .map((module) => `${module.label}: ${module.provider || "the service"}`);
      workflowModeSelect.title = [
        `${selected.label} provided by ${workflowProvider}`,
        ...moduleProviders,
      ].join("\n");
    }

    function saveWorkflowMode() {
      try {
        window.localStorage.setItem(WORKFLOW_MODE_STORAGE_KEY, workflowMode);
      } catch (error) {
        return;
      }
    }

    function activeWorkflowSetting(name, fallback = undefined) {
      const contribution = activeWorkflowContribution();
      return contribution && Object.hasOwn(contribution, name)
        ? contribution[name]
        : fallback;
    }

    function invokeActiveWorkflowHook(name, ...args) {
      const contribution = activeWorkflowContribution();
      const handler = contribution ? contribution[name] : null;
      return typeof handler === "function"
        ? handler(frontendRuntime, ...args)
        : undefined;
    }

    function stageConnector() {
      const connector = document.createElement("span");
      connector.className = "stage-connector";
      connector.setAttribute("aria-hidden", "true");
      connector.innerHTML = [
        '<svg class="stage-connector-icon" viewBox="0 0 58 58" focusable="false">',
        '<use href="#stageDoubleArrowIcon"></use>',
        "</svg>",
      ].join("");
      return connector;
    }

    function renderStageGraph(definition, contribution) {
      workflowStageGraph.replaceChildren();
      const stages = Array.isArray(definition.stages) ? definition.stages : [];
      const sidecars = new Set(contribution.sidecarStages || []);
      stages.forEach((stage, index) => {
        if (index > 0 && !sidecars.has(stage.id)) {
          workflowStageGraph.append(stageConnector());
        } else if (sidecars.has(stage.id)) {
          const spacer = document.createElement("span");
          spacer.className = "stage-spacer";
          spacer.setAttribute("aria-hidden", "true");
          workflowStageGraph.append(spacer);
        }
        const button = document.createElement("button");
        button.type = "button";
        button.className = "stage-node disabled";
        button.dataset.stage = stage.id;
        button.textContent = stage.id;
        button.disabled = true;
        if (sidecars.has(stage.id)) {
          button.classList.add("sidecar");
        }
        button.addEventListener("click", () => {
          handleWorkflowStageClick(button).catch((error) => {
            appendOutput(`stage update failed: ${error}\n`, "error");
          });
        });
        workflowStageGraph.append(button);
      });
      stageNodes = Array.from(
        workflowStageGraph.querySelectorAll(".stage-node[data-stage]"),
      );
      applyStageDescriptions();
      syncStageNodeState();
    }

    function renderWorkflowNavigation() {
      stageActionBody.replaceChildren();
      workflowStageGraph.replaceChildren();
      stageNodes = [];
      const contribution = activeWorkflowContribution();
      const definition = workflowDefinition();
      if (!contribution || !definition) {
        stageScroll.hidden = true;
        const empty = document.createElement("div");
        empty.className = "workflow-empty-state";
        empty.textContent = activeWorkflowDefinitions.length
          ? "An enabled workflow frontend failed to load."
          : "No workflows are installed or enabled.";
        stageActionBody.append(empty);
        return;
      }
      stageScroll.hidden = contribution.navigation !== "stages";
      if (contribution.navigation === "stages") {
        renderStageGraph(definition, contribution);
        renderStageActionPanel();
      } else if (typeof contribution.renderNavigation === "function") {
        contribution.renderNavigation(stageActionBody, frontendRuntime, definition);
      }
    }

    async function applyWorkflowMode(options = {}) {
      workflowModeSelect.value = workflowMode;
      for (const workflow of registeredWorkflows()) {
        if (workflow.layoutClass) {
          shell.classList.toggle(
            workflow.layoutClass,
            workflow.id === workflowMode,
          );
        }
      }
      renderWorkflowNavigation();
      updateSplashImage();
      applyStoredWorkbenchPaneSize();
      if (options.deferWorkspace) {
        refreshStageActionPanel();
        scheduleFitTerminal();
        return;
      }
      const contribution = activeWorkflowContribution();
      if (contribution && typeof contribution.activate === "function") {
        await contribution.activate(frontendRuntime);
      }
      refreshStageActionPanel();
      scheduleFitTerminal();
    }

    async function setWorkflowMode(mode) {
      const available = registeredWorkflows();
      const selected = available.find(
        (workflow) => workflow.id === mode || workflow.mode === mode,
      );
      if (!selected) {
        throw new Error(`workflow is not installed or enabled: ${mode}`);
      }
      const nextMode = selected.id;
      if (nextMode === workflowMode) {
        await applyWorkflowMode();
        return;
      }
      const previous = activeWorkflowContribution();
      await detachCurrentWorkspace();
      stopWorkspaceHeartbeat();
      releaseContextOwner();
      contextId = "";
      workspaceLeaseToken = "";
      resetWorkflowContextView();
      if (previous && typeof previous.deactivate === "function") {
        previous.deactivate(frontendRuntime);
      }
      workflowMode = nextMode;
      saveWorkflowMode();
      loadPaneLayoutForWorkflow();
      await applyWorkflowMode({ deferWorkspace: true });
      await restoreContext();
      await applyWorkflowMode();
    }

    async function detachCurrentWorkspace() {
      if (!contextId) {
        return;
      }
      try {
        await fetch(contextUrl("/api/workspaces/detach"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ connection_id: currentBrowserTabId() }),
          keepalive: true,
        });
      } catch (error) {
        return;
      }
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
      window.requestAnimationFrame(() => {
        updateWorkflowSideSheetMinimumWidth();
        fitTerminal();
      });
    }

    function setWorkflowSideSheetCollapsed(collapsed) {
      workflowSideSheetCollapsed = Boolean(collapsed);
      applyWorkflowSideSheetState();
      saveWorkflowSideSheetCollapsed();
    }

    function toggleWorkflowSideSheetCollapsed() {
      setWorkflowSideSheetCollapsed(!workflowSideSheetCollapsed);
    }

    function normalizeAgentTerminalSessionId(sessionId = "") {
      return String(sessionId || selectedSessionId || DEFAULT_AGENT_TERMINAL_ID);
    }

    function agentTerminalContext(sessionId = "") {
      const terminalSessionId = normalizeAgentTerminalSessionId(sessionId);
      return agentTerminalContexts.get(terminalSessionId) || null;
    }

    function createAgentTerminalContext(sessionId = "") {
      if (!window.Terminal) {
        return null;
      }
      const terminalSessionId = normalizeAgentTerminalSessionId(sessionId);
      const existing = agentTerminalContexts.get(terminalSessionId);
      if (existing) {
        return existing;
      }
      const host = document.createElement("div");
      host.className = "agent-terminal-host";
      host.dataset.sessionId = terminalSessionId;
      host.hidden = true;
      agentOutput.append(host);
      const nextTerminal = new window.Terminal(terminalOptions(true, "agent"));
      let nextFit = null;
      if (window.FitAddon && window.FitAddon.FitAddon) {
        nextFit = new window.FitAddon.FitAddon();
        nextTerminal.loadAddon(nextFit);
      }
      nextTerminal.open(host);
      window.ElectroBoyTerminalBehavior.install(nextTerminal, {
        hideCursor: true,
      });
      nextTerminal.onResize(({ cols, rows }) => {
        queueTerminalResize(cols, rows, terminalSessionId);
      });
      const context = {
        sessionId: terminalSessionId,
        host,
        terminal: nextTerminal,
        fit: nextFit,
        outputQueue: [],
        flushTimer: null,
      };
      agentTerminalContexts.set(terminalSessionId, context);
      return context;
    }

    function selectAgentTerminal(sessionId = "") {
      const context = createAgentTerminalContext(sessionId);
      if (!context) {
        return null;
      }
      activeAgentTerminalSessionId = context.sessionId;
      for (const candidate of agentTerminalContexts.values()) {
        candidate.host.hidden = candidate.sessionId !== context.sessionId;
      }
      terminal = context.terminal;
      terminalFit = context.fit;
      terminal.options.fontSize = effectivePaneFontSize("agent");
      scheduleFitTerminal();
      return context;
    }

    function currentAgentTerminalContext() {
      return agentTerminalContext(activeAgentTerminalSessionId);
    }

    function disposeAgentTerminalContext(context) {
      if (!context) {
        return;
      }
      clearAgentOutputQueue(context);
      try {
        context.terminal.dispose();
      } catch (error) {
        // Best effort cleanup; browser reloads should not depend on xterm disposal.
      }
      context.host.remove();
    }

    function disposeAgentTerminals() {
      for (const context of agentTerminalContexts.values()) {
        disposeAgentTerminalContext(context);
      }
      agentTerminalContexts.clear();
      activeAgentTerminalSessionId = DEFAULT_AGENT_TERMINAL_ID;
      terminal = null;
      terminalFit = null;
      agentOutput.replaceChildren();
      initializeTerminal();
    }

    function initializeTerminal() {
      if (!window.Terminal) {
        appendPlainOutput("terminal renderer unavailable; using plain text\n", "error");
        return;
      }
      if (!selectAgentTerminal(activeAgentTerminalSessionId)) {
        return;
      }
      applyTerminalFontSize();
      fitTerminal();
      if (!terminalWindowResizeListenerInstalled) {
        terminalWindowResizeListenerInstalled = true;
        window.addEventListener("resize", scheduleFitTerminal);
      }
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
        cursorInactiveStyle: pane === "agent" ? "none" : "outline",
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
      const next = fontSizeFromValue(terminalFontSize + delta);
      if (next === null) {
        return;
      }
      terminalFontSize = next;
      for (const pane of PANE_FONT_KEYS) {
        if (terminalFontSize + paneFontOffset(pane) <= 0) {
          paneFontOffsets[pane] = 0;
          savePaneFontOffset(pane);
        }
      }
      saveTerminalFontSize();
      applyTerminalFontSize();
    }

    function setTerminalFontSize(value) {
      const next = fontSizeFromValue(value);
      if (next === null) {
        return false;
      }
      terminalFontSize = next;
      for (const pane of PANE_FONT_KEYS) {
        if (terminalFontSize + paneFontOffset(pane) <= 0) {
          paneFontOffsets[pane] = 0;
          savePaneFontOffset(pane);
        }
      }
      saveTerminalFontSize();
      applyTerminalFontSize();
      return true;
    }

    function changePaneFontOffset(pane, delta) {
      if (!PANE_FONT_KEYS.includes(pane)) {
        return;
      }
      const nextSize = effectivePaneFontSize(pane) + delta;
      if (fontSizeFromValue(nextSize) === null) {
        return;
      }
      paneFontOffsets[pane] = nextSize - terminalFontSize;
      savePaneFontOffset(pane);
      applyPaneFontSize(pane);
    }

    function setPaneFontSize(pane, value) {
      if (!PANE_FONT_KEYS.includes(pane)) {
        return false;
      }
      const next = fontSizeFromValue(value);
      if (next === null) {
        return false;
      }
      paneFontOffsets[pane] = next - terminalFontSize;
      savePaneFontOffset(pane);
      applyPaneFontSize(pane);
      return true;
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
      if (document.activeElement !== terminalFontValue) {
        terminalFontValue.value = displayFontSize(terminalFontSize);
      }
      document.documentElement.style.setProperty(
        "--terminal-font-size",
        displayFontSize(terminalFontSize),
      );
      document.documentElement.style.setProperty(
        "--ui-font-size",
        displayFontSize(terminalFontSize),
      );
      document.documentElement.style.setProperty(
        "--ui-small-font-size",
        displayFontSize(terminalFontSize * 0.87),
      );
      document.documentElement.style.setProperty(
        "--ui-menu-font-size",
        displayFontSize(terminalFontSize * 0.93),
      );
      applyPaneFontSizes();
      decreaseTerminalFont.disabled = terminalFontSize - 1 <= 0;
      increaseTerminalFont.disabled = false;
      scheduleFitTerminal();
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
        document.documentElement.style.setProperty(
          cssProperty,
          displayFontSize(fontSize),
        );
      }
      if (pane === "agent") {
        for (const context of agentTerminalContexts.values()) {
          context.terminal.options.fontSize = fontSize;
        }
      } else {
        const paneTerminal = terminalForPane(pane);
        if (paneTerminal) {
          paneTerminal.options.fontSize = fontSize;
        }
      }
      updatePaneFontControls(pane);
      scheduleFitTerminal();
    }

    function updatePaneFontControls(pane) {
      const offset = paneFontOffset(pane);
      const fontSize = effectivePaneFontSize(pane);
      for (const level of document.querySelectorAll(`[data-pane-font-level="${pane}"]`)) {
        if (document.activeElement !== level) {
          level.value = displayFontSize(fontSize);
        }
        level.title = offset === 0 ? "Global font size" : `Global ${offset > 0 ? "+" : ""}${offset}px`;
      }
      for (const button of document.querySelectorAll(`[data-pane-font="${pane}"]`)) {
        const delta = Number(button.dataset.paneFontDelta || "0");
        if (delta < 0) {
          button.disabled = fontSize + delta <= 0;
        } else if (delta > 0) {
          button.disabled = false;
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

    function prepareTerminalStream(sessionId = "") {
      selectAgentTerminal(sessionId);
      applyTerminalFontSize();
      fitTerminal();
    }

    function paneIsVisible(element) {
      return Boolean(
        element &&
        element.isConnected &&
        !element.hidden &&
        !element.closest("[hidden]")
      );
    }

    function scheduleFitTerminal() {
      bumpFrontendDebugCounter("terminalFit.schedule");
      if (fitTerminalFrame) {
        bumpFrontendDebugCounter("terminalFit.scheduleSkipped");
        return;
      }
      fitTerminalFrame = window.requestAnimationFrame(() => {
        fitTerminalFrame = 0;
        fitTerminal();
      });
    }

    function fitTerminal() {
      bumpFrontendDebugCounter("terminalFit.run");
      if (terminalFit && paneIsVisible(agentOutputPane)) {
        try {
          window.ElectroBoyTerminalBehavior.fit(terminal, terminalFit);
        } catch (error) {
          return;
        }
        queueTerminalResize();
      }
      if (paneIsVisible(progressOutputPane)) {
        window.ElectroBoyFrontend.invokeModule("progress", "fit");
      }
      if (paneIsVisible(projectShellPane)) {
        window.ElectroBoyFrontend.invokeModule("project-shell", "fit");
      }
      queueProjectShellResize();
    }

    function observeTerminalPaneResizes() {
      if (!window.ResizeObserver) {
        return;
      }
      terminalResizeObserver = new window.ResizeObserver((entries) => {
        bumpFrontendDebugCounter("resizeObserver.terminal");
        if (!entries.some((entry) => entry.target.isConnected)) {
          return;
        }
        scheduleFitTerminal();
      });
      terminalResizeObserver.observe(agentOutput);
      terminalResizeObserver.observe(progressOutput);
      terminalResizeObserver.observe(projectShellOutput);
    }

    function terminalResizePayload(columns = null, rows = null, sessionId = "") {
      const requestedSessionId = String(sessionId || selectedSessionId || "");
      const session = requestedSessionId
        ? agentSessions.find((candidate) => candidate.session_id === requestedSessionId)
        : selectedSession();
      const context = agentTerminalContext(session ? session.session_id : "");
      if (!sessionIsRunning(session) || !contextId || !context) {
        return null;
      }
      return {
        session_id: session.session_id,
        columns: Number(columns || context.terminal.cols || 120),
        rows: Number(rows || context.terminal.rows || 32),
      };
    }

    function queueTerminalResize(columns = null, rows = null, sessionId = "") {
      const payload = terminalResizePayload(columns, rows, sessionId);
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

    function scheduleAgentOutputFlush(context) {
      if (!context || context.flushTimer !== null) {
        return;
      }
      context.flushTimer = window.setTimeout(
        () => flushAgentOutputQueue(context),
        0,
      );
    }

    function flushAgentOutputQueue(context) {
      if (!context) {
        return;
      }
      context.flushTimer = null;
      if (context.outputQueue.length === 0) {
        return;
      }
      const start = window.performance ? window.performance.now() : Date.now();
      let chunk = "";
      while (context.outputQueue.length > 0) {
        const remainingCapacity = AGENT_OUTPUT_FLUSH_CHARS - chunk.length;
        if (remainingCapacity <= 0) {
          break;
        }
        const next = context.outputQueue[0] || "";
        if (!next) {
          context.outputQueue.shift();
          continue;
        }
        if (next.length <= remainingCapacity) {
          chunk += next;
          context.outputQueue.shift();
        } else {
          chunk += next.slice(0, remainingCapacity);
          context.outputQueue[0] = next.slice(remainingCapacity);
        }
        const elapsed = (window.performance ? window.performance.now() : Date.now()) -
          start;
        if (
          chunk.length >= AGENT_OUTPUT_FLUSH_CHARS ||
          elapsed >= AGENT_OUTPUT_FLUSH_BUDGET_MS
        ) {
          break;
        }
      }
      if (chunk) {
        context.terminal.write(chunk);
      }
      if (context.outputQueue.length > 0) {
        scheduleAgentOutputFlush(context);
      }
    }

    function clearAgentOutputQueue(context) {
      if (!context) {
        return;
      }
      context.outputQueue = [];
      if (context.flushTimer !== null) {
        window.clearTimeout(context.flushTimer);
        context.flushTimer = null;
      }
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
      if (invokeActiveWorkflowHook("renderProjectStatus") !== true) {
        projectStatusOutput.textContent = `${projectStatusMessages.slice(-12).join("\n")}\n`;
      }
    }

    function appendAgentOutput(text, sessionId = "", className = "") {
      const context = createAgentTerminalContext(sessionId);
      const outputText = className
        ? formatTerminalMessage(String(text ?? ""), className)
        : String(text ?? "");
      if (context) {
        context.outputQueue.push(outputText);
        scheduleAgentOutputFlush(context);
        return;
      }
      appendPlainOutput(text, className);
    }

    function resetTerminalOutput(terminalInstance) {
      if (
        window.ElectroBoyTerminalBehavior &&
        typeof window.ElectroBoyTerminalBehavior.reset === "function"
      ) {
        return window.ElectroBoyTerminalBehavior.reset(terminalInstance);
      }
      if (terminalInstance && typeof terminalInstance.clear === "function") {
        terminalInstance.clear();
        return true;
      }
      return false;
    }

    function clearAgentOutput(sessionId = "") {
      const context = sessionId
        ? agentTerminalContext(sessionId)
        : currentAgentTerminalContext();
      if (context) {
        clearAgentOutputQueue(context);
        resetTerminalOutput(context.terminal);
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
      scheduleFitTerminal();
    }

    function startWorkflowSideSheetResize(event) {
      if (workflowSideSheetCollapsed) {
        return;
      }
      event.preventDefault();
      const shellRect = shell.getBoundingClientRect();
      const sideSheetRect = workflowSideSheet.getBoundingClientRect();
      const minimum = updateWorkflowSideSheetMinimumWidth();
      resizeWorkflowSideSheetState = {
        startX: event.clientX,
        startWidth: sideSheetRect.width,
        minimum,
        maximum: Math.max(minimum, shellRect.width - MIN_WORKFLOW_CONTENT_WIDTH),
      };
      workflowSideSheetResizeHandle.setPointerCapture(event.pointerId);
      shell.classList.add("resizing-side-sheet");
    }

    function updateWorkflowSideSheetResize(event) {
      if (!resizeWorkflowSideSheetState) {
        return;
      }
      const nextWidth = clampValue(
        resizeWorkflowSideSheetState.startWidth +
          (event.clientX - resizeWorkflowSideSheetState.startX),
        resizeWorkflowSideSheetState.minimum,
        resizeWorkflowSideSheetState.maximum,
      );
      shell.style.setProperty("--workflow-side-sheet-width", `${nextWidth}px`);
      saveNumber(WORKFLOW_SIDE_SHEET_WIDTH_STORAGE_KEY, nextWidth);
      fitTerminal();
    }

    function finishWorkflowSideSheetResize(event) {
      if (!resizeWorkflowSideSheetState) {
        return;
      }
      resizeWorkflowSideSheetState = null;
      shell.classList.remove("resizing-side-sheet");
      try {
        workflowSideSheetResizeHandle.releasePointerCapture(event.pointerId);
      } catch (error) {
        return;
      }
      fitTerminal();
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

    function applyOutputPaneVisibility(options = {}) {
      const ensureRequestedPanes = options.ensureRequestedPanes !== false;
      const updateOutputSplit = options.updateOutputSplit !== false;
      const agentVisible = !poppedPanes.has("agent");
      const artifactVisible =
        artifactPaneRequested && !poppedPanes.has("artifact");
      const progressVisible = progressPaneRequested && !poppedPanes.has("progress");
      if (ensureRequestedPanes && artifactVisible) {
        ensurePaneInLayout("artifact", "agent", "row", { activateExisting: false });
      }
      if (ensureRequestedPanes && progressVisible) {
        ensurePaneInLayout("progress", "agent", "row", { activateExisting: false });
      }
      agentOutputPane.hidden = !agentVisible;
      artifactPreviewPane.hidden = !artifactVisible;
      progressOutputPane.hidden = !progressVisible;
      if (!updateOutputSplit) {
        artifactPaneResizeHandle.hidden = true;
        outputResizeHandle.hidden = true;
        outputSplit.classList.remove("artifact-visible", "split");
        outputSplit.classList.toggle("agent-popped", !agentVisible);
        scheduleFitTerminal();
        return;
      }
      artifactPaneResizeHandle.hidden = !artifactVisible || !agentVisible;
      outputResizeHandle.hidden =
        !progressVisible || (!agentVisible && !artifactVisible);
      outputSplit.classList.toggle("agent-popped", !agentVisible);
      outputSplit.classList.toggle("artifact-visible", Boolean(artifactVisible));
      outputSplit.classList.toggle("split", progressVisible);
      scheduleFitTerminal();
    }

    function showProgressPane(show, options = {}) {
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
      applyOutputPaneVisibility(options);
      scheduleFitTerminal();
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
      const label = connectionBadgeLabel();
      connection.textContent = label;
      connection.title = label;
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
      const contribution = activeWorkflowContribution();
      const descriptions = contribution && contribution.stageDescriptions
        ? contribution.stageDescriptions
        : {};
      for (const stageNode of stageNodes) {
        const stageId = stageNode.dataset.stage || "";
        const description = descriptions[stageId] || "";
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
        const payload = await response.json().catch(() => ({}));
        applyServiceFingerprint(payload);
        serviceVersion = String(payload.version || "");
        setConnected();
      }
    }

    function contextUrl(path) {
      const separator = path.includes("?") ? "&" : "?";
      const parameters = new URLSearchParams();
      parameters.set("context_id", contextId);
      parameters.set("workspace_id", contextId);
      parameters.set("connection_id", currentBrowserTabId());
      if (workspaceLeaseToken) {
        parameters.set("lease_token", workspaceLeaseToken);
      }
      appendFrontendTelemetryParameters(parameters);
      return `${path}${separator}${parameters.toString()}`;
    }

    function appendFrontendTelemetryParameters(parameters) {
      if (!frontendTelemetryEnabled) {
        return parameters;
      }
      parameters.set("telemetry_page_id", pageInstanceId);
      parameters.set("telemetry_tab_id", currentBrowserTabId());
      return parameters;
    }

    function paneUrl(kind, requestedArtifactItem = undefined, options = {}) {
      const parameters = new URLSearchParams();
      if (contextId) {
        parameters.set("context_id", contextId);
        parameters.set("workspace_id", contextId);
        parameters.set("connection_id", currentBrowserTabId());
        if (workspaceLeaseToken) {
          parameters.set("lease_token", workspaceLeaseToken);
        }
        appendFrontendTelemetryParameters(parameters);
      }
      const paneSessionId = String(options.sessionId || selectedSessionId || "");
      if (paneSessionId) {
        parameters.set("session_id", paneSessionId);
      }
      const artifactItem = requestedArtifactItem === undefined
        ? artifactPreviewItems[0] || null
        : requestedArtifactItem;
      if (artifactItem) {
        parameters.set("artifact", artifactKindForPane(artifactItem));
      } else if (kind === "artifact") {
        parameters.set("artifact", "empty");
      }
      if (artifactItem && artifactItem.kind === "document" && artifactItem.target) {
        parameters.set("document_path", artifactItem.target.path);
        parameters.set("document_title", artifactItem.target.label);
      }
      if (
        artifactItem &&
        (artifactItem.kind === "corkboard" ||
          artifactItem.kind === "creative-corkboard")
      ) {
        const board = artifactItem.board || artifactItem.folder || artifactItem.corkboard;
        if (board) {
          parameters.set("corkboard_id", board.id || board.path);
          parameters.set("corkboard_title", board.label || artifactItem.title);
          if (board.provider) {
            parameters.set("corkboard_provider", board.provider);
          }
        }
      }
      if (artifactItem && artifactItem.kind === "route" && artifactItem.path) {
        parameters.set("artifact_path", artifactItem.path);
        parameters.set("artifact_title", artifactItem.title || artifactItem.path);
      }
      if (artifactItem && artifactItem.kind === "agenda") {
        const agenda = artifactItem.agenda || {};
        if (agenda.provider) {
          parameters.set("agenda_provider", agenda.provider);
        }
        if (agenda.style) {
          parameters.set("agenda_style", agenda.style);
        }
      }
      if (artifactItem && artifactItem.kind === "calendar") {
        const calendar = artifactItem.calendar || {};
        if (calendar.provider) {
          parameters.set("calendar_provider", calendar.provider);
        }
        if (calendar.calendarIdsExplicit) {
          parameters.set("calendar_ids_explicit", "1");
        }
        if (Array.isArray(calendar.calendarIds) && calendar.calendarIds.length) {
          parameters.set("calendar_ids", calendar.calendarIds.join(","));
        }
        if (calendar.month) {
          parameters.set("calendar_month", calendar.month);
        }
        if (calendar.rangeStart) {
          parameters.set("range_start", calendar.rangeStart);
        }
        if (calendar.rangeEnd) {
          parameters.set("range_end", calendar.rangeEnd);
        }
        if (calendar.style) {
          parameters.set("calendar_style", calendar.style);
        }
      }
      const fontPane = paneFontKeyForKind(kind);
      parameters.set("base_font_size", String(terminalFontSize));
      parameters.set("font_pane", fontPane);
      parameters.set("font_offset", String(paneFontOffset(fontPane)));
      parameters.set("font_size", String(effectivePaneFontSize(fontPane)));
      parameters.set("document_zoom", String(documentZoom));
      return `/pane/${encodeURIComponent(kind)}?${parameters.toString()}`;
    }

    function poppedPaneKey(kind, options = {}) {
      if (options.leafId) {
        return `${kind}:leaf:${String(options.leafId)}`;
      }
      if (kind === "agent") {
        return `agent:${String(options.sessionId || selectedSessionId || "default")}`;
      }
      return kind;
    }

    function poppedPaneWindowName(kind, options = {}) {
      if (options.leafId) {
        return `electroboy-${kind}-${contextId || "local"}-${String(options.leafId)}`;
      }
      if (kind === "agent") {
        return `electroboy-agent-${contextId || "local"}-${String(options.sessionId || selectedSessionId || "default")}`;
      }
      return `electroboy-${kind}-${contextId || "local"}`;
    }

    function hasPoppedPaneKind(kind) {
      if (poppedPaneWindows.has(kind)) {
        return true;
      }
      if (kind !== "agent") {
        return false;
      }
      for (const key of poppedPaneWindows.keys()) {
        if (key.startsWith("agent:")) {
          return true;
        }
      }
      return false;
    }

    function popOutPaneLayoutLeaf(leaf) {
      const requestedContent = paneLayoutRequestedContent(leaf);
      popOutPane(
        leaf.kind,
        INSTANCE_PANE_LAYOUT_KINDS.has(leaf.kind) ? requestedContent : null,
        {
          leafId: leaf.id,
          sessionId: leaf.kind === "agent"
            ? String(requestedContent?.sessionId || selectedSessionId || "")
            : "",
        },
      );
    }

    function popOutPane(kind, artifactItem = null, options = {}) {
      if (!contextId && kind !== "scratch") {
        appendOutput("create a browser context first\n", "error");
        return;
      }
      const popoutOptions = {
        leafId: String(options.leafId || ""),
        sessionId: kind === "agent"
          ? String(options.sessionId || selectedSessionId || "")
          : "",
      };
      const popoutKey = poppedPaneKey(kind, popoutOptions);
      const popup = window.open(
        paneUrl(kind, artifactItem, popoutOptions),
        poppedPaneWindowName(kind, popoutOptions),
        PANE_POPUP_FEATURES,
      );
      if (!popup) {
        appendOutput("popup was blocked by the browser\n", "error");
        return;
      }
      const existing = poppedPaneWindows.get(popoutKey);
      if (existing) {
        window.clearInterval(existing.poll);
      }
      setPanePoppedOut(kind, true, popoutOptions.leafId);
      const poll = window.setInterval(() => {
        if (!popup.closed) {
          return;
        }
        window.clearInterval(poll);
        poppedPaneWindows.delete(popoutKey);
        setPanePoppedOut(
          kind,
          popoutOptions.leafId ? false : hasPoppedPaneKind(kind),
          popoutOptions.leafId,
        );
      }, 500);
      poppedPaneWindows.set(popoutKey, {
        popup,
        poll,
        kind,
        leafId: popoutOptions.leafId,
      });
    }

    function dockPoppedPane(kind) {
      const key = poppedPaneKey(kind);
      const existing = poppedPaneWindows.get(key) || poppedPaneWindows.get(kind);
      if (existing) {
        window.clearInterval(existing.poll);
        try {
          existing.popup.close();
        } catch (error) {
          // The browser may block closing a user-managed window.
        }
        poppedPaneWindows.delete(key);
        poppedPaneWindows.delete(kind);
      }
      setPanePoppedOut(kind, hasPoppedPaneKind(kind));
    }

    function setPanePoppedOut(kind, poppedOut, leafId = "") {
      if (leafId) {
        if (poppedOut) {
          poppedPaneLeafIds.add(leafId);
        } else {
          poppedPaneLeafIds.delete(leafId);
        }
        refreshPaneLayoutVisibility();
        scheduleFitTerminal();
        return;
      }
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
        const shellStatus = window.ElectroBoyFrontend.invokeModule(
          "project-shell",
          "status",
        );
        if (
          !poppedOut &&
          projectShellRunning &&
          projectShellPaneRequested &&
          !shellStatus.connected
        ) {
          window.setTimeout(connectProjectShellEvents, 0);
        }
      }
      if (kind === "agent" || INSTANCE_PANE_LAYOUT_KINDS.has(kind)) {
        refreshPaneLayoutVisibility();
      }
      scheduleFitTerminal();
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
      if (invokeActiveWorkflowHook("handleWindowMessage", data) === true) {
        return;
      }
      if (
        data.type === "electroboy-pane-font-offset" &&
        PANE_FONT_KEYS.includes(data.pane)
      ) {
        const offset = Number(data.offset);
        if (!Number.isFinite(offset) || terminalFontSize + offset <= 0) {
          return;
        }
        paneFontOffsets[data.pane] = offset;
        applyPaneFontSize(data.pane);
        return;
      }
      if (data.type !== "electroboy-pane-restore" || !data.pane) {
        return;
      }
      let entryKey = "";
      let entry = null;
      for (const [key, candidate] of poppedPaneWindows.entries()) {
        if (candidate.kind === data.pane && event.source === candidate.popup) {
          entryKey = key;
          entry = candidate;
          break;
        }
      }
      if (!entry) {
        return;
      }
      window.clearInterval(entry.poll);
      poppedPaneWindows.delete(entryKey);
      setPanePoppedOut(
        data.pane,
        entry.leafId ? false : hasPoppedPaneKind(data.pane),
        entry.leafId,
      );
    });

    function contextWorkflowStorageKey(mode = workflowMode) {
      return `${CONTEXT_STORAGE_KEY}.${mode || "none"}`;
    }

    function workflowWorkspacePolicy() {
      const definition = workflowDefinition();
      return definition && definition.workspace_policy === "shared-singleton"
        ? "shared-singleton"
        : "exclusive";
    }

    function workspaceAllowsSharedConnections() {
      return workspaceAttachmentPolicy === "shared-singleton" ||
        workflowWorkspacePolicy() === "shared-singleton";
    }

    function workspaceLeaseStorageKey(mode = workflowMode) {
      return `${WORKSPACE_LEASE_STORAGE_KEY}.${mode || "none"}`;
    }

    function storedWorkspaceLease(mode = workflowMode) {
      try {
        return window.sessionStorage.getItem(workspaceLeaseStorageKey(mode)) || "";
      } catch (error) {
        return "";
      }
    }

    function saveWorkspaceLease(value, mode = workflowMode) {
      try {
        if (value) {
          window.sessionStorage.setItem(workspaceLeaseStorageKey(mode), value);
        } else {
          window.sessionStorage.removeItem(workspaceLeaseStorageKey(mode));
        }
      } catch (error) {
        return;
      }
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
      if (!splashImage || !splashImage.getAttribute("src")) {
        return;
      }
      splashOverlay.hidden = false;
    }

    function updateSplashImage() {
      if (!splashImage) {
        return;
      }
      const contribution = activeWorkflowContribution();
      const route = contribution && contribution.splashImage
        ? contribution.splashImage
        : "";
      if (route) {
        splashImage.setAttribute("src", route);
      } else {
        splashImage.removeAttribute("src");
      }
      showSplashButton.disabled = !route;
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

    function renderHelpPairs(container, entries, keyElement = "strong") {
      container.replaceChildren();
      for (const [label, description] of entries) {
        const item = document.createElement("div");
        item.className = keyElement === "kbd"
          ? "help-shortcut-item"
          : "help-guide-item";
        const key = document.createElement(keyElement);
        key.textContent = label;
        const detail = document.createElement("span");
        detail.textContent = description;
        item.append(key, detail);
        container.append(item);
      }
    }

    function renderHelp() {
      const contribution = activeWorkflowContribution() || {};
      const workflowHelp = contribution.help || {};
      const workflowLabel = contribution.label || "ElectroBoy";
      helpSummary.textContent =
        "A workspace for working with agents, project files, and live tools.";
      renderHelpPairs(helpTour, [
        ["Workflow menu", "Choose a workflow and open its project actions."],
        ["Workflow map", "Follow the current stages and open stage-specific actions."],
        ["Workspace panes", "Arrange agent output, files, shells, notes, and status."],
        ["Context tools", "Use each pane's tool button for actions specific to its content."],
      ]);
      renderHelpPairs(helpControls, [
        ["Agent input", "The only field that sends instructions to an agent."],
        ["Agent output", "A read-only live terminal view; select the agent above it."],
        ["Send shortcut", "Hover over its badge to record the key chord you prefer."],
        ["Interrupt", "Sends Escape to the selected agent."],
        ["Link file", "Insert a filesystem file reference into the agent input."],
        ["Pane controls", "Pop out, close, split, assign content, or open context tools."],
        ["Text size", "Use A-/A+ or enter an exact positive size in the middle field."],
      ]);
      const shortcutApi = window.ElectroBoyInputShortcut;
      const sendShortcut = shortcutApi
        ? shortcutApi.label(shortcutApi.load())
        : "Shift+Enter";
      renderHelpPairs(helpShortcuts, [
        [sendShortcut, "Send the Agent Input message."],
        ["Escape", "Interrupt the selected agent from Agent Input; close Help here."],
        ["Ctrl/Cmd+C", "Copy selected terminal output."],
        ["F1", "Open this Help overlay."],
      ], "kbd");
      helpWorkflowTitle.textContent = `${workflowLabel} workflow`;
      helpWorkflowSummary.textContent = workflowHelp.summary ||
        "Use the workflow controls to organize project work and agent activity.";
      helpWorkflowFeatures.replaceChildren();
      const features = Array.isArray(workflowHelp.features)
        ? workflowHelp.features
        : [];
      for (const feature of features) {
        const item = document.createElement("li");
        item.textContent = feature;
        helpWorkflowFeatures.append(item);
      }
      helpWorkflowBadge.textContent = workflowLabel;
      helpVersion.textContent = serviceVersion
        ? `Version ${serviceVersion}`
        : "Local browser service";
    }

    function helpFocusableElements() {
      if (!helpOverlay) {
        return [];
      }
      return Array.from(
        helpOverlay.querySelectorAll(
          'button:not([disabled]), [href], input:not([disabled]), ' +
          'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => !element.hidden);
    }

    function openHelp() {
      if (!helpOverlay) {
        return;
      }
      renderHelp();
      helpPreviousFocus = document.activeElement;
      helpOverlay.hidden = false;
      closeHelpButton.focus();
    }

    function dismissHelp() {
      if (!helpOverlay || helpOverlay.hidden) {
        return;
      }
      helpOverlay.hidden = true;
      if (helpPreviousFocus && typeof helpPreviousFocus.focus === "function") {
        helpPreviousFocus.focus();
      }
      helpPreviousFocus = null;
    }

    function handleHelpKeydown(event) {
      if (helpOverlay && !helpOverlay.hidden) {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopImmediatePropagation();
          dismissHelp();
          return;
        }
        if (event.key !== "Tab") {
          return;
        }
        const focusable = helpFocusableElements();
        if (focusable.length === 0) {
          event.preventDefault();
          return;
        }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
        return;
      }
      if (event.key === "F1") {
        event.preventDefault();
        event.stopImmediatePropagation();
        openHelp();
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
          if (workspaceAllowsSharedConnections()) {
            releaseContextOwner();
          } else if (!claimContextOwner(value)) {
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
      closeAgentEventStream();
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
      disposeAgentTerminals();
      clearProgressOutput();
      clearProjectShellOutput();
      hideArtifactPreview();
      hideWorkItemPanel();
      renderSessionSwitcher();
      updateAgentControls();
    }

    async function createContext() {
      const response = await fetch("/api/contexts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          connection_id: currentBrowserTabId(),
          workflow_id: workflowMode,
        }),
      });
      if (!response.ok) {
        projectStatus.textContent = "could not create workspace connection";
        return;
      }
      const payload = await response.json();
      contextId = payload.workspace_id || payload.context_id || "";
      workspaceLeaseToken = payload.lease_token || "";
      saveContextId(contextId);
      saveWorkspaceLease(workspaceLeaseToken);
      updateProjectState(payload);
    }

    function stopWorkspaceHeartbeat() {
      if (workspaceHeartbeatTimer) {
        window.clearInterval(workspaceHeartbeatTimer);
        workspaceHeartbeatTimer = null;
      }
    }

    async function recoverWorkspaceAttachment() {
      if (!contextId || !workspaceLeaseToken) {
        return false;
      }
      if (workspaceRecoveryPromise) {
        return workspaceRecoveryPromise;
      }
      const recoveringContextId = contextId;
      workspaceRecoveryPromise = (async () => {
        const response = await fetch(contextUrl("/api/workspaces/attach"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            workspace_id: recoveringContextId,
            connection_id: currentBrowserTabId(),
            lease_token: workspaceLeaseToken,
          }),
        });
        if (!response.ok || contextId !== recoveringContextId) {
          return false;
        }
        const payload = await response.json();
        workspaceLeaseToken = payload.lease_token || workspaceLeaseToken;
        saveWorkspaceLease(workspaceLeaseToken);
        updateProjectState(payload, { workspaceRecovery: true });
        return true;
      })();
      try {
        return await workspaceRecoveryPromise;
      } finally {
        workspaceRecoveryPromise = null;
      }
    }

    async function sendWorkspaceHeartbeat() {
      if (!contextId || !workspaceLeaseToken) {
        return false;
      }
      const response = await fetch(contextUrl("/api/workspaces/heartbeat"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          connection_id: currentBrowserTabId(),
          lease_token: workspaceLeaseToken,
        }),
      });
      const responseOk = response.ok;
      await drainDiscardedFetchResponse(response, {
        operation: "workspace-heartbeat",
      });
      if (!responseOk) {
        const recovered = await recoverWorkspaceAttachment();
        if (!recovered) {
          stopWorkspaceHeartbeat();
        }
        return recovered;
      }
      return true;
    }

    async function resumeWorkspaceAttachment() {
      if (!contextId || !workspaceLeaseToken) {
        return;
      }
      if (await sendWorkspaceHeartbeat()) {
        startWorkspaceHeartbeat();
      }
    }

    function startWorkspaceHeartbeat() {
      stopWorkspaceHeartbeat();
      if (!contextId || !workspaceLeaseToken) {
        return;
      }
      workspaceHeartbeatTimer = window.setInterval(
        () => sendWorkspaceHeartbeat().catch(() => {}),
        WORKSPACE_HEARTBEAT_MS,
      );
    }

    async function restoreContext() {
      const existingContextId = storedContextId();
      const ownerAccepted = workspaceAllowsSharedConnections() ||
        claimContextOwner(existingContextId);
      if (!existingContextId || !ownerAccepted) {
        if (existingContextId) {
          saveContextId("");
        }
        await createContext();
        return;
      }
      contextId = existingContextId;
      workspaceLeaseToken = storedWorkspaceLease();
      const attachResponse = await fetch(contextUrl("/api/workspaces/attach"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_id: existingContextId,
          connection_id: currentBrowserTabId(),
        }),
      });
      if (!attachResponse.ok) {
        saveContextId("");
        saveWorkspaceLease("");
        contextId = "";
        workspaceLeaseToken = "";
        await createContext();
        return;
      }
      const payload = await attachResponse.json();
      contextId = payload.workspace_id || payload.context_id || existingContextId;
      workspaceLeaseToken = payload.lease_token || workspaceLeaseToken;
      saveContextId(contextId);
      saveWorkspaceLease(workspaceLeaseToken);
      updateProjectState(payload);
      const session = selectedSession();
      if (session && session.status === "running") {
        const isInteractive = Boolean(session.interactive);
        if (isInteractive) {
          showProgressPane(false);
          setAgentInputVisible(true);
        } else {
          clearProgressOutput();
          showProgressPane(true, {
            ensureRequestedPanes: false,
            updateOutputSplit: false,
          });
          setAgentInputVisible(false);
        }
        activeAgentKind = session.kind || "";
        connectSessionEvents(session.session_id, { ensurePane: false });
        if (!isInteractive && session.status === "running") {
          connectProgressEvents({
            ensureRequestedPanes: false,
            updateOutputSplit: false,
          });
        }
        sendTerminalResize();
      }
    }

    function updateProjectState(payload, options = {}) {
      bumpFrontendDebugCounter("workspace.updateProjectState");
      const previousWorkspaceId = contextId;
      workspaceAttachmentPolicy = payload.attachment_policy ||
        workflowWorkspacePolicy();
      const nextWorkspaceId = payload.workspace_id || payload.context_id || contextId;
      if (nextWorkspaceId && nextWorkspaceId !== contextId) {
        contextId = nextWorkspaceId;
        saveContextId(contextId);
      }
      if (payload.lease_token) {
        workspaceLeaseToken = payload.lease_token;
        saveWorkspaceLease(workspaceLeaseToken);
      }
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
      applyWorkspaceClientState(payload);
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
      const definition = workflowDefinition();
      const stages = definition && Array.isArray(definition.stages)
        ? definition.stages
        : [];
      const firstProjectStage = stages.find((stage) => stage.id !== "project");
      const workflowStage = payload.workflow_stage || (
        hasStageTarget && firstProjectStage ? firstProjectStage.id : "project"
      );
      currentWorkflowStage = workflowStage;
      if (!projectPath.value) {
        projectPath.value = activeProjectRoot || activationRoot || serviceRoot;
      }
      setConnected();
      updateStageNodes(hasProjectContext, hasStageTarget, workflowStage);
      refreshStageActionPanel();
      if (restoredScratchContextId !== contextId) {
        restoreScratchPad();
      }
      syncProjectShellPane();
      if (invokeActiveWorkflowHook("projectChanged", payload, options) !== true) {
        syncArtifactPreviewWithProject();
      }
      projectStatus.textContent = projectStatusLine();
      queueProjectStatusRefresh();
      refreshPaneLayoutInstanceFrames();
      if (previousWorkspaceId !== contextId) {
        loadPaneLayoutForWorkflow();
        renderPaneLayout();
      }
      startWorkspaceHeartbeat();
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
      const contribution = activeWorkflowContribution();
      const filter = contribution ? contribution.recentProjectFilter : null;
      return typeof filter === "function"
        ? recentProjects.filter((recent) => filter(recent))
        : [...recentProjects];
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

    function updateStageNodes(hasProjectContext, hasStageTarget, workflowStage) {
      const contribution = activeWorkflowContribution();
      const sidecars = new Set(
        contribution && Array.isArray(contribution.sidecarStages)
          ? contribution.sidecarStages
          : [],
      );
      for (const stageNode of stageNodes) {
        const stageId = stageNode.dataset.stage || "";
        const isProject = stageId === "project";
        const isSidecar = sidecars.has(stageId);
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

    function syncStageNodeState() {
      updateStageNodes(
        Boolean(activationRoot),
        Boolean(activeProjectRoot),
        currentWorkflowStage,
      );
    }

    function genericStageRun(stage) {
      return stageRunState[stage] || { started: false, running: false, interactive: false };
    }

    function refreshStageActionPanel() {
      const contribution = activeWorkflowContribution();
      if (!contribution) {
        return;
      }
      if (contribution.navigation === "stages") {
        renderStageActionPanel();
      } else if (typeof contribution.refreshNavigation === "function") {
        contribution.refreshNavigation(frontendRuntime);
      }
    }

    function showStageActionPanel(stageId) {
      expandedWorkflowStages.add(stageId);
      setWorkflowSideSheetCollapsed(false);
      renderStageActionPanel();
    }

    function hideStageActionPanel() {
      expandedWorkflowStages.clear();
      expandedProjectActionGroups.clear();
      const contribution = activeWorkflowContribution();
      if (!contribution) {
        stageActionBody.replaceChildren();
      } else if (contribution.navigation === "stages") {
        renderStageActionPanel();
      } else if (typeof contribution.refreshNavigation === "function") {
        contribution.refreshNavigation(frontendRuntime);
      }
    }

    function stageActionName(stageId) {
      const definition = workflowDefinition();
      const stage = definition && Array.isArray(definition.stages)
        ? definition.stages.find((entry) => entry.id === stageId)
        : null;
      return stage ? stage.label : stageId;
    }

    function renderStageActionPanel() {
      stageActionBody.replaceChildren();
      const contribution = activeWorkflowContribution();
      const hiddenActionStages = new Set(
        contribution && Array.isArray(contribution.hiddenActionStages)
          ? contribution.hiddenActionStages
          : [],
      );
      for (const stageNode of stageNodes) {
        const stageId = stageNode.dataset.stage || "";
        if (!stageId || hiddenActionStages.has(stageId)) {
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
      const contribution = activeWorkflowContribution();
      const descriptions = contribution && contribution.stageDescriptions
        ? contribution.stageDescriptions
        : {};
      trigger.title = descriptions[stageId] || stageId;
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
        renderStageActionList(list, stageActions(stageId));
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

    function documentTargetFromInput(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "documentTargetFromInput", ...args);
    }

    function documentTargetFromSelectedPath(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "documentTargetFromSelectedPath", ...args);
    }

    function registerDocumentTarget(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "registerDocumentTarget", ...args);
    }

    function openDocumentTarget(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "openDocumentTarget", ...args);
    }

    function selectOpenDocumentTarget(...args) {
      return window.ElectroBoyFrontend.invokeModule("documents", "selectOpenDocumentTarget", ...args);
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

    function ensureWorkspaceDialog() {
      let dialog = document.getElementById("workspaceSelectorDialog");
      if (dialog) {
        return dialog;
      }
      dialog = document.createElement("dialog");
      dialog.id = "workspaceSelectorDialog";
      dialog.className = "workspace-selector-dialog";
      dialog.innerHTML = `
        <form method="dialog" class="workspace-selector-form">
          <header class="workspace-selector-header">
            <div>
              <h2>Open workspace</h2>
              <p>Choose a detached workspace to continue.</p>
            </div>
            <button class="workspace-selector-close" type="button"
                    aria-label="Close">&times;</button>
          </header>
          <fieldset class="workspace-selector-options">
            <legend>Available workspaces</legend>
            <div class="workspace-selector-toolbar">
              <label class="workspace-selector-select-all">
                <input type="checkbox" class="workspace-selector-select-all-input">
                <span>Select all</span>
              </label>
              <span>Select one to attach or clear; select multiple to clear.</span>
            </div>
            <div class="workspace-selector-list"></div>
          </fieldset>
          <p class="workspace-selector-error" role="alert" hidden></p>
          <footer class="workspace-selector-footer">
            <button class="workspace-selector-cancel" type="button">Cancel</button>
            <button class="workspace-selector-clear" type="button">Clear</button>
            <button class="workspace-selector-submit" type="submit">Attach</button>
          </footer>
        </form>
      `;
      document.body.append(dialog);
      return dialog;
    }

    function workspaceDetails(workspace) {
      const details = [];
      if (workspace.workflow_stage) {
        details.push(String(workspace.workflow_stage));
      }
      const agents = Number(workspace.running_agent_count || 0);
      details.push(`${agents} agent${agents === 1 ? "" : "s"} running`);
      if (workspace.active_project_root) {
        details.push(String(workspace.active_project_root));
      }
      return details.join(" · ");
    }

    function selectedWorkspaceChoices(dialog) {
      return Array.from(dialog.querySelectorAll(
        'input[name="workspace-selector"]:checked',
      ));
    }

    function syncWorkspaceSelectorActions(dialog) {
      const choices = Array.from(dialog.querySelectorAll(
        'input[name="workspace-selector"]',
      ));
      const selected = choices.filter((choice) => choice.checked);
      const selectAll = dialog.querySelector(".workspace-selector-select-all-input");
      const submit = dialog.querySelector(".workspace-selector-submit");
      const clear = dialog.querySelector(".workspace-selector-clear");
      submit.disabled = selected.length !== 1;
      clear.disabled = selected.length === 0;
      selectAll.disabled = choices.length === 0;
      selectAll.checked = choices.length > 0 && selected.length === choices.length;
      selectAll.indeterminate = selected.length > 0 && selected.length < choices.length;
    }

    async function loadWorkspaceChoices(dialog) {
      const list = dialog.querySelector(".workspace-selector-list");
      const submit = dialog.querySelector(".workspace-selector-submit");
      const clear = dialog.querySelector(".workspace-selector-clear");
      const selectAll = dialog.querySelector(".workspace-selector-select-all-input");
      const error = dialog.querySelector(".workspace-selector-error");
      error.hidden = true;
      list.textContent = "Loading workspaces...";
      submit.disabled = true;
      clear.disabled = true;
      selectAll.checked = false;
      selectAll.indeterminate = false;
      selectAll.disabled = true;
      const parameters = new URLSearchParams({ workflow_id: workflowMode });
      appendFrontendTelemetryParameters(parameters);
      const response = await fetch(`/api/workspaces?${parameters.toString()}`, {
        cache: "no-store",
      });
      const payload = await response.json().catch(() => ({ error: "workspace list failed" }));
      if (!response.ok) {
        list.replaceChildren();
        error.textContent = payload.error || "workspace list failed";
        error.hidden = false;
        return;
      }
      const workspaces = Array.isArray(payload.workspaces) ? payload.workspaces : [];
      if (workspaces.length === 0) {
        list.textContent = "No detached workspaces are available.";
        return;
      }
      list.replaceChildren(...workspaces.map((workspace) => {
        const option = document.createElement("label");
        option.className = "workspace-selector-option";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.name = "workspace-selector";
        input.value = String(workspace.workspace_id || "");
        input.addEventListener("change", () => syncWorkspaceSelectorActions(dialog));
        const copy = document.createElement("span");
        copy.className = "workspace-selector-option-copy";
        const title = document.createElement("strong");
        title.textContent = String(workspace.name || "Workspace");
        const details = document.createElement("span");
        details.className = "workspace-selector-details";
        details.textContent = workspaceDetails(workspace);
        copy.append(title, details);
        option.append(input, copy);
        return option;
      }));
      syncWorkspaceSelectorActions(dialog);
    }

    async function clearWorkspaceChoices(dialog) {
      const error = dialog.querySelector(".workspace-selector-error");
      const workspaceIds = selectedWorkspaceChoices(dialog).map((choice) => choice.value);
      if (workspaceIds.length === 0) {
        return;
      }
      dialog.querySelector(".workspace-selector-submit").disabled = true;
      dialog.querySelector(".workspace-selector-clear").disabled = true;
      dialog.querySelector(".workspace-selector-select-all-input").disabled = true;
      const parameters = new URLSearchParams({ workflow_id: workflowMode });
      appendFrontendTelemetryParameters(parameters);
      const response = await fetch(`/api/workspaces/clear?${parameters.toString()}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace_ids: workspaceIds }),
      });
      const payload = await response.json().catch(() => ({ error: "workspace clear failed" }));
      if (!response.ok) {
        error.textContent = payload.error || "workspace clear failed";
        error.hidden = false;
        syncWorkspaceSelectorActions(dialog);
        return;
      }
      await loadWorkspaceChoices(dialog);
    }

    async function showWorkspaceSelector() {
      const dialog = ensureWorkspaceDialog();
      const error = dialog.querySelector(".workspace-selector-error");
      await loadWorkspaceChoices(dialog);
      return new Promise((resolve) => {
        const finish = (value) => {
          dialog.close();
          resolve(value);
        };
        dialog.querySelector(".workspace-selector-close").onclick = () => finish(false);
        dialog.querySelector(".workspace-selector-cancel").onclick = () => finish(false);
        dialog.querySelector(".workspace-selector-select-all-input").onchange = (event) => {
          dialog.querySelectorAll('input[name="workspace-selector"]').forEach((choice) => {
            choice.checked = event.currentTarget.checked;
          });
          syncWorkspaceSelectorActions(dialog);
        };
        dialog.querySelector(".workspace-selector-clear").onclick = () => {
          const selectedCount = selectedWorkspaceChoices(dialog).length;
          if (selectedCount === 0) {
            return;
          }
          if (!window.confirm(
            `Clear ${selectedCount} selected workspace${selectedCount === 1 ? "" : "s"}? `
              + "Running sessions in them will be stopped.",
          )) {
            return;
          }
          clearWorkspaceChoices(dialog).catch((problem) => {
            error.textContent = problem.message || String(problem);
            error.hidden = false;
            syncWorkspaceSelectorActions(dialog);
          });
        };
        dialog.oncancel = (event) => {
          event.preventDefault();
          finish(false);
        };
        dialog.querySelector("form").onsubmit = async (event) => {
          event.preventDefault();
          const selected = selectedWorkspaceChoices(dialog);
          if (selected.length !== 1) {
            return;
          }
          dialog.querySelector(".workspace-selector-submit").disabled = true;
          dialog.querySelector(".workspace-selector-clear").disabled = true;
          dialog.querySelector(".workspace-selector-select-all-input").disabled = true;
          const response = await fetch(contextUrl("/api/workspaces/attach"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              workspace_id: selected[0].value,
              connection_id: currentBrowserTabId(),
            }),
          });
          const payload = await response.json().catch(() => ({ error: "workspace attach failed" }));
          if (!response.ok) {
            await loadWorkspaceChoices(dialog);
            error.textContent = payload.error || "workspace attach failed";
            error.hidden = false;
            return;
          }
          resetWorkflowContextView();
          updateProjectState(payload, { workspaceSwitch: true });
          finish(true);
        };
        dialog.showModal();
      });
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
      if (invokeActiveWorkflowHook("renderProjectStatus") === true) {
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
      if (invokeActiveWorkflowHook("renderProjectStatus") === true) {
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
      agentInput.dispatchEvent(new Event("input", { bubbles: true }));
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
      updateProjectState(payload);
      activateProject.disabled = false;
    }

    function projectEndpoint(mode) {
      const workflowEndpoint = invokeActiveWorkflowHook("projectEndpoint", mode);
      if (workflowEndpoint) {
        return workflowEndpoint;
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
      disposeAgentTerminals();
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
      const runningSessions = agentSessions.filter(
        (session) => session && session.status === "running",
      );
      let terminateAgents = false;
      if (runningSessions.length > 0) {
        const labels = runningSessions
          .slice(0, 3)
          .map((session) => session.label || session.kind || "agent")
          .join(", ");
        const suffix = runningSessions.length > 3 ? ", ..." : "";
        const confirmed = window.confirm(
          `Deactivate will stop ${runningSessions.length} running agent ` +
          `session${runningSessions.length === 1 ? "" : "s"}: ` +
          `${labels}${suffix}. Continue?`,
        );
        if (!confirmed) {
          return;
        }
        terminateAgents = true;
      }
      const response = await fetch(contextUrl("/api/project/deactivate"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ terminate_agents: terminateAgents }),
      });
      const payload = await response.json().catch(() => ({ error: "deactivate failed" }));
      if (!response.ok) {
        appendOutput(`${payload.error || "deactivate failed"}\n`, "error");
        return;
      }
      closeAgentEventStream();
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
      hideStageActionPanel();
      agentInput.disabled = true;
      interruptAgent.disabled = true;
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
      disposeAgentTerminals();
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

    function hideStageMenus() {}

    async function handleWorkflowStageClick(stageNode) {
      const stageId = stageNode.dataset.stage || "";
      if (stageNode.disabled) {
        return;
      }
      showStageActionPanel(stageId);
    }

    applyWorkItem.addEventListener("click", applyWorkItemSelection);
    cancelWorkItem.addEventListener("click", hideWorkItemPanel);
    retryWorkItem.addEventListener("click", applyWorkItemSelection);
    workItemTitle.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        applyWorkItemSelection();
      }
    });
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
    bindFontSizeInput(
      terminalFontValue,
      () => terminalFontSize,
      setTerminalFontSize,
    );
    document.querySelectorAll("[data-pane-font-level]").forEach((input) => {
      const pane = input.dataset.paneFontLevel || "";
      bindFontSizeInput(
        input,
        () => effectivePaneFontSize(pane),
        (value) => setPaneFontSize(pane, value),
      );
    });
    document.querySelectorAll("[data-pane-font-delta]").forEach((button) => {
      button.addEventListener("click", () => {
        changePaneFontOffset(
          button.dataset.paneFont || "",
          Number(button.dataset.paneFontDelta || "0"),
        );
      });
    });
    window.addEventListener("storage", (event) => {
      if (
        !workspaceAllowsSharedConnections() &&
        event.key === scratchPadStorageKey()
      ) {
        const selectionStart = scratchPad.selectionStart;
        const selectionEnd = scratchPad.selectionEnd;
        scratchPad.value = event.newValue || "";
        if (document.activeElement === scratchPad) {
          const length = scratchPad.value.length;
          scratchPad.setSelectionRange(
            Math.min(selectionStart, length),
            Math.min(selectionEnd, length),
          );
        }
        return;
      }
      if (event.key === TERMINAL_FONT_STORAGE_KEY) {
        terminalFontSize = storedTerminalFontSize();
        for (const pane of PANE_FONT_KEYS) {
          if (terminalFontSize + paneFontOffset(pane) <= 0) {
            paneFontOffsets[pane] = 0;
            savePaneFontOffset(pane);
          }
        }
        applyTerminalFontSize();
        return;
      }
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
    function popOutMountedPane(kind) {
      const paneElement = PANE_LAYOUT_KINDS[kind]?.element;
      const leafElement = paneElement?.closest(".pane-layout-leaf");
      const leaf = paneLayoutLeafById(leafElement?.dataset.paneLayoutId || "");
      if (leaf) {
        popOutPaneLayoutLeaf(leaf);
        return;
      }
      popOutPane(kind);
    }

    popoutAgentPane.addEventListener("click", () => popOutMountedPane("agent"));
    popoutProgressPane.addEventListener("click", () => popOutMountedPane("progress"));
    popoutProjectShellPane.addEventListener("click", () => popOutMountedPane("shell"));
    popoutScratchPane.addEventListener("click", () => popOutMountedPane("scratch"));
    popoutStatusPane.addEventListener("click", () => popOutMountedPane("status"));
    popoutInputPane.addEventListener("click", () => popOutPane("input"));
    workflowSideSheetResizeHandle.addEventListener(
      "pointerdown",
      startWorkflowSideSheetResize,
    );
    workflowSideSheetResizeHandle.addEventListener(
      "pointermove",
      updateWorkflowSideSheetResize,
    );
    workflowSideSheetResizeHandle.addEventListener(
      "pointerup",
      finishWorkflowSideSheetResize,
    );
    workflowSideSheetResizeHandle.addEventListener(
      "pointercancel",
      finishWorkflowSideSheetResize,
    );
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
    closeSplash.addEventListener("click", dismissSplash);
    showSplashButton.addEventListener("click", openSplash);
    showHelpButton.addEventListener("click", openHelp);
    closeHelpButton.addEventListener("click", dismissHelp);
    helpOverlay.addEventListener("click", (event) => {
      if (event.target === helpOverlay) {
        dismissHelp();
      }
    });
    splashOverlay.addEventListener("click", (event) => {
      if (event.target === splashOverlay) {
        dismissSplash();
      }
    });
    window.addEventListener("keydown", handleHelpKeydown, true);
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && splashOverlay && !splashOverlay.hidden) {
        dismissSplash();
      }
    });

    scratchPad.addEventListener("input", () => {
      saveScratchPad();
      queueWorkspaceStateSave();
      scratchPaneSync.publish({ value: scratchPad.value });
    });
    workflowModeSelect.addEventListener("change", () => {
      setWorkflowMode(workflowModeSelect.value).catch((error) => {
        appendOutput(`workflow switch failed: ${error}
`, "error");
      });
    });

    const frontendRuntime = {
      elements: {
        creativeTree: null,
        scratchPad,
        exportProgressOutput,
        progressOutput,
        progressOutputPane,
        artifactPreviewStack,
        projectPanel,
        projectPath,
        projectStatus,
        openProjectShell,
        toggleProjectShellPane,
        closeProjectShellPane,
        stopProjectShell,
        projectShellOutput,
        projectShellPane,
        shellPaneDivider,
        leftOutputPane,
        sessionSwitcher,
        agentSessionIndicator,
        insertFileLink,
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
          requirementsApproved,
          designRunning,
          designReviewRunning,
          designReviewInteractive,
          designApproved,
          adHocRunning,
          projectShellRunning,
          projectShellPaneRequested,
          projectShellPaneDismissed,
          selectedSessionId,
          agentSessions,
          artifactPaneRequested,
          artifactPreviewStage,
          creativeTreePayload,
          creativeActiveDocument,
          creativeActiveFolder,
          creativeEditingPath,
          creativeEditingType,
          creativeLastNotifiedTarget,
          expandedCreativeFolders,
        };
      },
      updateState(patch) {
        if (Object.hasOwn(patch, "artifactPaneRequested")) {
          artifactPaneRequested = Boolean(patch.artifactPaneRequested);
        }
        if (Object.hasOwn(patch, "creativeTreePayload")) {
          creativeTreePayload = patch.creativeTreePayload;
        }
        if (Object.hasOwn(patch, "creativeActiveDocument")) {
          creativeActiveDocument = patch.creativeActiveDocument;
        }
        if (Object.hasOwn(patch, "creativeActiveFolder")) {
          creativeActiveFolder = patch.creativeActiveFolder;
        }
        if (Object.hasOwn(patch, "creativeEditingPath")) {
          creativeEditingPath = patch.creativeEditingPath;
        }
        if (Object.hasOwn(patch, "creativeEditingType")) {
          creativeEditingType = patch.creativeEditingType;
        }
        if (Object.hasOwn(patch, "creativeLastNotifiedTarget")) {
          creativeLastNotifiedTarget = patch.creativeLastNotifiedTarget;
        }
        if (Object.hasOwn(patch, "expandedCreativeFolders")) {
          expandedCreativeFolders = patch.expandedCreativeFolders;
        }
        if (Object.hasOwn(patch, "selectedSessionId")) {
          selectedSessionId = patch.selectedSessionId || "";
        }
        if (Object.hasOwn(patch, "designReviewInteractive")) {
          designReviewInteractive = Boolean(patch.designReviewInteractive);
        }
        if (Object.hasOwn(patch, "projectShellRunning")) {
          projectShellRunning = Boolean(patch.projectShellRunning);
        }
        if (Object.hasOwn(patch, "projectShellPaneRequested")) {
          projectShellPaneRequested = Boolean(patch.projectShellPaneRequested);
        }
        if (Object.hasOwn(patch, "projectShellPaneDismissed")) {
          projectShellPaneDismissed = Boolean(patch.projectShellPaneDismissed);
        }
      },
      state: {
        get activationRoot() { return activationRoot; },
        set activationRoot(value) { activationRoot = value; },
        get activeProjectMode() { return activeProjectMode; },
        set activeProjectMode(value) { activeProjectMode = value; },
        get activeProjectRoot() { return activeProjectRoot; },
        set activeProjectRoot(value) { activeProjectRoot = value; },
        get agentSessions() { return agentSessions; },
        set agentSessions(value) { agentSessions = value; },
        get selectedSessionId() { return selectedSessionId; },
        set selectedSessionId(value) { selectedSessionId = value; },
        get contextId() { return contextId; },
        set contextId(value) { contextId = value; },
        get currentWorkflowStage() { return currentWorkflowStage; },
        set currentWorkflowStage(value) { currentWorkflowStage = value; },
        get workflowMode() { return workflowMode; },
        set workflowMode(value) { workflowMode = value; },
        get requirementsRunning() { return requirementsRunning; },
        set requirementsRunning(value) { requirementsRunning = value; },
        get designRunning() { return designRunning; },
        set designRunning(value) { designRunning = value; },
        get designReviewRunning() { return designReviewRunning; },
        set designReviewRunning(value) { designReviewRunning = value; },
        get artifactPaneRequested() { return artifactPaneRequested; },
        set artifactPaneRequested(value) { artifactPaneRequested = value; },
        get artifactPreviewKind() { return artifactPreviewKind; },
        set artifactPreviewKind(value) { artifactPreviewKind = value; },
        get artifactPreviewDocumentTarget() { return artifactPreviewDocumentTarget; },
        set artifactPreviewDocumentTarget(value) { artifactPreviewDocumentTarget = value; },
        get artifactPreviewItems() { return artifactPreviewItems; },
        set artifactPreviewItems(value) { artifactPreviewItems = value; },
        get openDocumentTargets() { return openDocumentTargets; },
        set openDocumentTargets(value) { openDocumentTargets = value; },
        get manualArtifactPreview() { return manualArtifactPreview; },
        set manualArtifactPreview(value) { manualArtifactPreview = value; },
        get manualArtifactPreviewStage() { return manualArtifactPreviewStage; },
        set manualArtifactPreviewStage(value) { manualArtifactPreviewStage = value; },
        get artifactPreviewStage() { return artifactPreviewStage; },
        set artifactPreviewStage(value) { artifactPreviewStage = value; },
        get artifactPreviewVersion() { return artifactPreviewVersion; },
        set artifactPreviewVersion(value) { artifactPreviewVersion = value; },
        get artifactSaveTokenSequence() { return artifactSaveTokenSequence; },
        set artifactSaveTokenSequence(value) { artifactSaveTokenSequence = value; },
        get artifactEventSources() { return artifactEventSources; },
        set artifactEventSources(value) { artifactEventSources = value; },
        get pendingArtifactSaves() { return pendingArtifactSaves; },
        get customDocumentTargets() { return customDocumentTargets; },
        set customDocumentTargets(value) { customDocumentTargets = value; },
        get documentZoom() { return documentZoom; },
        set documentZoom(value) { documentZoom = value; },
        get terminalFontSize() { return terminalFontSize; },
        set terminalFontSize(value) { terminalFontSize = value; },
        get projectMode() { return projectMode; },
        set projectMode(value) { projectMode = value; },
        get projectBrowserActivatesSelection() { return projectBrowserActivatesSelection; },
        set projectBrowserActivatesSelection(value) { projectBrowserActivatesSelection = value; },
        get serviceRoot() { return serviceRoot; },
        set serviceRoot(value) { serviceRoot = value; },
        get activeAgentKind() { return activeAgentKind; },
        set activeAgentKind(value) { activeAgentKind = value; },
        get designReviewInteractive() { return designReviewInteractive; },
        set designReviewInteractive(value) { designReviewInteractive = value; },
        get documentationRunning() { return documentationRunning; },
        set documentationRunning(value) { documentationRunning = value; },
        get eventSource() { return eventSource; },
        set eventSource(value) { eventSource = value; },
        get serviceSessions() { return serviceSessions; },
        set serviceSessions(value) { serviceSessions = value; },
        get slashCommandMode() { return slashCommandMode; },
        set slashCommandMode(value) { slashCommandMode = value; },
        get stageRunState() { return stageRunState; },
        set stageRunState(value) { stageRunState = value; },
        get terminal() { return terminal; },
        set terminal(value) { terminal = value; },
        get terminalInputQueue() { return terminalInputQueue; },
        set terminalInputQueue(value) { terminalInputQueue = value; },
      },
      input: {
        sendShortcut: agentSendShortcut,
      },
      telemetry: frontendTelemetryRuntime,
      http: {
        contextUrl,
        contextParameters: () => {
          const url = new URL(contextUrl("/"), window.location.origin);
          return new URLSearchParams(url.search);
        },
        fetch: (...args) => window.fetch(...args),
        eventSource: createDebugEventSource,
        rawEventSource: createDebugEventSourceForUrl,
      },
      terminals: {
        options: terminalOptions,
        formatMessage: formatTerminalMessage,
        applyFontSize: applyTerminalFontSize,
        fitAll: scheduleFitTerminal,
        reset: resetTerminalOutput,
      },
      downloads: {
        exportMarkdown,
        exportBlob,
        safeName: exportSafeName,
        timestamp: timestampForDownload,
      },
      layout: {
        ensurePane: ensurePaneInLayout,
        assignArtifact: assignArtifactToPane,
        assignPane: assignPaneContent,
        hasPane: (kind) => Boolean(paneLayoutLeafByKind(kind)),
        isPopped: (kind) => poppedPanes.has(kind),
        dockPane: dockPoppedPane,
        showProgressPane,
        applyStoredShellHeight: applyStoredProjectShellPaneHeight,
      },
      notifications: {
        appendOutput,
      },
      project: {
        update: updateProjectState,
        refresh: refreshProject,
        recordStatus: recordProjectStatusMessage,
        statusMessages: () => [...projectStatusMessages],
        renderStatus: (lines) => {
          projectStatusOutput.textContent = `${lines.join("\n")}\n`;
        },
        deactivate: deactivateActiveProject,
      },
      workspaces: {
        openSelector: showWorkspaceSelector,
        saveState: queueWorkspaceStateSave,
        detach: detachCurrentWorkspace,
      },
      paths: {
        basename,
      },
      recent: {
        list: recentProjectsForWorkflow,
        label: recentProjectLabel,
        open: openRecentProject,
        actions: recentProjectActionsForWorkflow,
      },
      browser: {
        openProject: (...args) =>
          window.ElectroBoyFrontend.invokeModule("file-browser", "openProjectBrowser", ...args),
      },
      metaProject: {
        repositoryLabel,
        startRepository: startMetaRepositoryFromMenu,
        removeRepository: removeMetaRepositoryFromMenu,
      },
      workItems: {
        features: workItemFeatures,
        bugs: workItemBugs,
        switchFeature: switchFeatureWorkItemContext,
        switchBug: switchBugWorkItemContext,
      },
      scratch: {
        restore: restoreScratchPad,
      },
      sharedPanes: {
        connect: (pane, options = {}) => window.ElectroBoyPaneSync.connect({
          ...options,
          pane,
          context: () => `${contextId}:${currentBrowserTabId()}`,
          priority: 100,
        }),
      },
      modules: {
        invoke: (moduleId, action, ...args) =>
          window.ElectroBoyFrontend.invokeModule(moduleId, action, ...args),
      },
      ui: {
        stageActionButton,
        refreshStageActionPanel,
        hideStageMenus,
        setAgentInputVisible,
        applyOutputPaneVisibility,
        popOutPane,
        hideWorkItemPanel,
        showProjectPanel,
        showWorkItemPanel,
        applyProjectSelection,
        insertTextAtCursor,
        setWorkflowSideSheetCollapsed,
      },
      artifacts: {
        applyStoredPaneSize: applyStoredArtifactPaneSize,
        editorFontSize: artifactEditorFontSize,
        postEditorFontSize: postArtifactEditorFontSize,
        applyDocumentZoom,
        changeDocumentZoom,
      },
      workflows: {
        stageRun: genericStageRun,
        preparePrompt: (message) => {
          const definition = workflowDefinition();
          const handler = definition && definition.actions
            ? definition.actions.preparePrompt
            : null;
          return typeof handler === "function"
            ? handler(frontendRuntime, message)
            : message;
        },
        updateMenus: refreshStageActionPanel,
      },
      agent: {
        appendOutput: appendAgentOutput,
        clearOutput: clearAgentOutput,
        prepareTerminal: prepareTerminalStream,
        sendResize: sendTerminalResize,
        insertFileLink,
      },
    };

    const scratchPaneSync = frontendRuntime.sharedPanes.connect("scratch", {
      snapshot: () => ({ value: scratchPad.value }),
      receive: (state) => {
        if (!state || typeof state.value !== "string") {
          return;
        }
        const selectionStart = scratchPad.selectionStart;
        const selectionEnd = scratchPad.selectionEnd;
        scratchPad.value = state.value;
        if (document.activeElement === scratchPad) {
          const length = scratchPad.value.length;
          scratchPad.setSelectionRange(
            Math.min(selectionStart, length),
            Math.min(selectionEnd, length),
          );
        }
        saveScratchPad();
      },
    });
    let lastSharedStatusText = projectStatusOutput.textContent;
    const statusPaneSync = frontendRuntime.sharedPanes.connect("status", {
      snapshot: () => ({ text: projectStatusOutput.textContent }),
      receive: (state) => {
        if (!state || typeof state.text !== "string") {
          return;
        }
        lastSharedStatusText = state.text;
        projectStatusOutput.textContent = state.text;
      },
    });
    const projectStatusObserver = new MutationObserver(() => {
      bumpFrontendDebugCounter("mutationObserver.projectStatus");
      const text = projectStatusOutput.textContent;
      if (text === lastSharedStatusText) {
        return;
      }
      lastSharedStatusText = text;
      statusPaneSync.publish({ text });
    });
    projectStatusObserver.observe(projectStatusOutput, {
      childList: true,
      characterData: true,
      subtree: true,
    });

    async function initialize() {
      applyFrontendTelemetryUrlPreference();
      startFrontendDebugDiagnostics();
      window.ElectroBoyFrontend.bindRuntime(frontendRuntime);
      await checkConnection();
      await loadWorkflowRegistry();
      renderWorkflowModeOptions();
      applyWorkflowSideSheetState();
      await applyWorkflowMode({ deferWorkspace: true });
      initializeWorkflowSideSheetResize();
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
      if (!workflowMode) {
        return;
      }
      await restoreContext();
      await applyWorkflowMode();
    }

    window.addEventListener("pagehide", releaseContextOwner);
    window.addEventListener("pagehide", () => {
      sendFrontendDebugSnapshot("pagehide", { beacon: true });
    });
    window.addEventListener("pagehide", () => {
      stopWorkspaceHeartbeat();
      if (contextId && navigator.sendBeacon) {
        const payload = new Blob(
          [JSON.stringify({ connection_id: currentBrowserTabId() })],
          { type: "application/json" },
        );
        navigator.sendBeacon(contextUrl("/api/workspaces/detach"), payload);
      }
      scratchPaneSync.close();
      statusPaneSync.close();
      projectStatusObserver.disconnect();
    });
    window.addEventListener("pageshow", () => {
      if (contextId) {
        claimContextOwner(contextId);
      }
      resumeWorkspaceAttachment().catch(() => {});
    });
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        resumeWorkspaceAttachment().catch(() => {});
      }
    });
    document.addEventListener("resume", () => {
      resumeWorkspaceAttachment().catch(() => {});
    });

    if (document.readyState === "loading") {
      window.addEventListener("DOMContentLoaded", () => {
        initialize().catch(() => {});
      }, { once: true });
    } else {
      initialize().catch(() => {});
    }
