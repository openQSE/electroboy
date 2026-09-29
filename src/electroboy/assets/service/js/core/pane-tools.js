(function () {
  "use strict";

  function editableTarget(target) {
    return Boolean(
      target
      && (
        target.isContentEditable
        || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
      )
    );
  }

  const ICONS = Object.freeze({
    "arrow-down": '<path d="M12 5v14"></path><path d="m19 12-7 7-7-7"></path>',
    "arrow-left": '<path d="M19 12H5"></path><path d="m12 19-7-7 7-7"></path>',
    "arrow-right": '<path d="M5 12h14"></path><path d="m12 5 7 7-7 7"></path>',
    "arrow-up": '<path d="M12 19V5"></path><path d="m5 12 7-7 7 7"></path>',
    calendar: '<path d="M8 2v4"></path><path d="M16 2v4"></path><path d="M3 10h18"></path><rect x="3" y="4" width="18" height="18" rx="2"></rect>',
    check: '<path d="m20 6-11 11-5-5"></path>',
    close: '<path d="M18 6 6 18"></path><path d="m6 6 12 12"></path>',
    code: '<path d="m16 18 6-6-6-6"></path><path d="m8 6-6 6 6 6"></path>',
    crosshair: '<circle cx="12" cy="12" r="8"></circle><path d="M12 2v4"></path><path d="M12 18v4"></path><path d="M2 12h4"></path><path d="M18 12h4"></path>',
    delete: '<path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="m19 6-1 14H6L5 6"></path><path d="M10 11v5"></path><path d="M14 11v5"></path>',
    dock: '<rect x="3" y="4" width="18" height="16" rx="2"></rect><path d="M8 20v-5h8v5"></path>',
    download: '<path d="M12 3v12"></path><path d="m7 10 5 5 5-5"></path><path d="M5 21h14"></path>',
    edit: '<path d="M12 20h9"></path><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"></path>',
    "external-link": '<path d="M15 3h6v6"></path><path d="m10 14 11-11"></path><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"></path><circle cx="12" cy="12" r="3"></circle>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path>',
    "file-down": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><path d="M12 12v5"></path><path d="m9 15 3 3 3-3"></path>',
    "file-plus": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><path d="M12 12v6"></path><path d="M9 15h6"></path>',
    "file-text": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><path d="M8 13h8"></path><path d="M8 17h5"></path>',
    filter: '<path d="M22 3H2l8 9v7l4 2v-9z"></path>',
    "filter-x": '<path d="M22 3H2l8 9v7l4 2v-9z"></path><path d="m17 14 4 4"></path><path d="m21 14-4 4"></path>',
    "folder-open": '<path d="M3 7h7l2 2h9l-2 9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><path d="M3 7v11"></path>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"></rect><rect x="14" y="3" width="7" height="7" rx="1"></rect><rect x="3" y="14" width="7" height="7" rx="1"></rect><rect x="14" y="14" width="7" height="7" rx="1"></rect>',
    layout: '<rect x="3" y="4" width="18" height="16" rx="2"></rect><path d="M3 10h18"></path><path d="M9 10v10"></path>',
    minus: '<path d="M5 12h14"></path>',
    network: '<rect x="16" y="16" width="6" height="6" rx="1"></rect><rect x="2" y="16" width="6" height="6" rx="1"></rect><rect x="9" y="2" width="6" height="6" rx="1"></rect><path d="M5 16v-3a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v3"></path><path d="M12 8v8"></path>',
    palette: '<circle cx="13.5" cy="6.5" r=".5"></circle><circle cx="17.5" cy="10.5" r=".5"></circle><circle cx="8.5" cy="7.5" r=".5"></circle><circle cx="6.5" cy="12.5" r=".5"></circle><path d="M12 2a10 10 0 0 0 0 20h1.5a2.5 2.5 0 0 0 0-5H12a2 2 0 0 1 0-4h1a9 9 0 0 0 9-9 2 2 0 0 0-2-2z"></path>',
    play: '<path d="m5 3 14 9-14 9z"></path>',
    plus: '<path d="M12 5v14"></path><path d="M5 12h14"></path>',
    refresh: '<path d="M21 12a9 9 0 0 1-15.4 6.4L3 16"></path><path d="M3 21v-5h5"></path><path d="M3 12a9 9 0 0 1 15.4-6.4L21 8"></path><path d="M21 3v5h-5"></path>',
    replace: '<path d="M3 7h12a4 4 0 0 1 0 8H7"></path><path d="m7 11-4 4 4 4"></path><path d="M17 17h4"></path><path d="M19 15v4"></path>',
    settings: '<path d="M12 15.5A3.5 3.5 0 1 0 12 8a3.5 3.5 0 0 0 0 7.5Z"></path><path d="M19.4 15a1.8 1.8 0 0 0 .4 2l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1.8 1.8 0 0 0-2-.4 1.8 1.8 0 0 0-1 1.6V21a2 2 0 0 1-4 0v-.1a1.8 1.8 0 0 0-1-1.6 1.8 1.8 0 0 0-2 .4l-.1.1a2 2 0 0 1-2.8-2.8l.1-.1a1.8 1.8 0 0 0 .4-2 1.8 1.8 0 0 0-1.6-1H3a2 2 0 0 1 0-4h.1a1.8 1.8 0 0 0 1.6-1 1.8 1.8 0 0 0-.4-2l-.1-.1A2 2 0 0 1 7 4l.1.1a1.8 1.8 0 0 0 2 .4 1.8 1.8 0 0 0 1-1.6V3a2 2 0 0 1 4 0v.1a1.8 1.8 0 0 0 1 1.6 1.8 1.8 0 0 0 2-.4l.1-.1A2 2 0 0 1 20 7l-.1.1a1.8 1.8 0 0 0-.4 2 1.8 1.8 0 0 0 1.6 1h.1a2 2 0 0 1 0 4h-.1a1.8 1.8 0 0 0-1.6 1Z"></path>',
    sparkles: '<path d="m12 3 1.7 4.6L18 9.3l-4.3 1.7L12 16l-1.7-5L6 9.3l4.3-1.7Z"></path><path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8Z"></path>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="1"></rect>',
    undo: '<path d="M9 7 4 12l5 5"></path><path d="M20 17a8 8 0 0 0-8-8H4"></path>',
    "zoom-in": '<circle cx="10.5" cy="10.5" r="7.5"></circle><path d="m16 16 5 5"></path><path d="M7.5 10.5h6"></path><path d="M10.5 7.5v6"></path>',
    "zoom-out": '<circle cx="10.5" cy="10.5" r="7.5"></circle><path d="m16 16 5 5"></path><path d="M7.5 10.5h6"></path>',
  });

  const LABEL_ICONS = Object.freeze({
    "+": "zoom-in",
    "-": "zoom-out",
    "−": "zoom-out",
    "↑": "arrow-up",
    "↓": "arrow-down",
    "←": "arrow-left",
    "→": "arrow-right",
    "Any date": "calendar",
    "Apply dates": "check",
    "Apply configuration": "check",
    "Apply VSCode Neovim": "check",
    "Clear all filters": "filter-x",
    Close: "close",
    "Close pane": "close",
    DOCX: "file-text",
    Dock: "dock",
    Edit: "edit",
    "Export cards": "download",
    "Export transcript": "download",
    "Focus session": "crosshair",
    "Generate Corkboard…": "grid",
    Grid: "grid",
    Diagnostics: "sparkles",
    "IDE configuration": "settings",
    Interrupt: "stop",
    "Jump to today": "calendar",
    Layout: "layout",
    Markdown: "file-text",
    "Network access": "network",
    New: "file-plus",
    "Next 7 days": "calendar",
    Open: "folder-open",
    "Open in IDE": "code",
    "Open network settings": "network",
    PDF: "file-down",
    Pop: "external-link",
    "Pop out": "external-link",
    Preview: "eye",
    "Random color": "palette",
    Refresh: "refresh",
    "Refresh diagnostics": "sparkles",
    Replace: "replace",
    "Restart IDE": "refresh",
    "Restart now": "refresh",
    "Start agent": "play",
    "Stop IDE": "stop",
    "Terminate agent": "delete",
    "This month": "calendar",
    Today: "calendar",
    "Undo organize": "undo",
    "Use standard editor": "edit",
    "VSCode Neovim": "code",
    "Launch with VSCode Neovim": "code",
  });

  function iconNameFor(label, title = "") {
    return LABEL_ICONS[label] || LABEL_ICONS[title] || "";
  }

  function iconSvg(name, className = "pane-tool-button-icon") {
    return `<svg class="${className}" viewBox="0 0 24 24" fill="none" `
      + `stroke="currentColor" stroke-width="2" stroke-linecap="round" `
      + `stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
  }

  function actionButton(label, action, options = {}) {
    const control = document.createElement("button");
    control.type = "button";
    control.title = options.title || label;
    control.className = `pane-tool-action-button ${options.className || ""}`.trim();
    if (options.primary) control.classList.add("primary");
    if (options.danger) control.classList.add("danger");
    if (options.pressed) control.setAttribute("aria-pressed", "true");
    if (options.dataset) {
      Object.entries(options.dataset).forEach(([key, value]) => {
        control.dataset[key] = String(value);
      });
    }
    const iconName = options.icon === false
      ? ""
      : (options.icon || iconNameFor(label, control.title));
    if (options.iconOnly) {
      control.classList.add("pane-tool-icon-only");
      control.setAttribute("aria-label", options.title || label);
    }
    if (iconName) {
      const icon = document.createElement("span");
      icon.className = "pane-tool-button-icon-wrap";
      icon.innerHTML = iconSvg(iconName);
      control.append(icon);
    }
    const text = document.createElement("span");
    text.className = "pane-tool-button-label";
    text.textContent = label;
    control.append(text);
    if (typeof action === "function") control.addEventListener("click", action);
    return control;
  }

  function buttonGroup(className = "") {
    const wrapper = document.createElement("div");
    wrapper.className = `pane-tool-button-group ${className}`.trim();
    return wrapper;
  }

  function create(options) {
    const host = options.host;
    const shelf = options.shelf;
    const content = options.content;
    const toggleButton = options.toggleButton;
    const closeButton = options.closeButton;
    const resizeHandle = options.resizeHandle;
    const storageKey = String(options.storageKey || "");
    const side = options.side === "left" ? "left" : "right";
    const onResize = typeof options.onResize === "function"
      ? options.onResize
      : () => {};
    const sections = new Map();
    let enabled = false;
    let open = false;

    function storedOpen() {
      if (!storageKey) return Boolean(options.defaultOpen);
      try {
        const value = window.localStorage.getItem(`${storageKey}.open`);
        return value === null ? Boolean(options.defaultOpen) : value === "true";
      } catch (error) {
        return Boolean(options.defaultOpen);
      }
    }

    let preferredOpen = storedOpen();

    function storedWidth() {
      if (!storageKey) return 280;
      try {
        const value = Number(window.localStorage.getItem(`${storageKey}.width`) || "280");
        return Number.isFinite(value) ? Math.max(210, Math.min(520, value)) : 280;
      } catch (error) {
        return 280;
      }
    }

    function saveWidth(width) {
      if (!storageKey) return;
      try {
        window.localStorage.setItem(`${storageKey}.width`, String(width));
      } catch (error) {
        // Resizing remains available when storage is unavailable.
      }
    }

    function applyOpenState(nextOpen, remember = true) {
      if (remember) {
        preferredOpen = Boolean(nextOpen);
        if (storageKey) {
          try {
            window.localStorage.setItem(
              `${storageKey}.open`,
              String(preferredOpen),
            );
          } catch (error) {
            // Open state persistence is optional.
          }
        }
      }
      open = enabled && Boolean(nextOpen);
      host.classList.toggle("pane-tools-open", open);
      shelf.hidden = !open;
      toggleButton.setAttribute("aria-expanded", String(open));
      toggleButton.title = open ? "Close pane tools (N)" : "Open pane tools (N)";
      window.requestAnimationFrame(onResize);
    }

    function setEnabled(nextEnabled) {
      enabled = Boolean(nextEnabled);
      toggleButton.hidden = !enabled;
      applyOpenState(enabled ? preferredOpen : false, false);
    }

    function addSection(id, label, options = {}) {
      const details = document.createElement("details");
      details.className = "pane-tool-section";
      details.dataset.toolSection = id;
      details.open = options.open !== false;
      const summary = document.createElement("summary");
      summary.textContent = label;
      const body = document.createElement("div");
      body.className = "pane-tool-section-body";
      details.append(summary, body);
      content.append(details);
      sections.set(id, { details, body });
      setEnabled(true);
      return body;
    }

    function openSection(id = "") {
      applyOpenState(true);
      const section = sections.get(id);
      if (section) {
        section.details.open = true;
        const focusTarget = section.body.querySelector(
          "input:not(:disabled), button:not(:disabled), select:not(:disabled)",
        );
        if (focusTarget) focusTarget.focus();
      }
    }

    function handleKeydown(event) {
      if (
        event.defaultPrevented
        || event.altKey
        || event.ctrlKey
        || event.metaKey
        || event.shiftKey
        || String(event.key).toLowerCase() !== "n"
        || editableTarget(event.target)
      ) {
        return;
      }
      event.preventDefault();
      applyOpenState(!open);
    }

    function bindKeyboardTarget(targetWindow) {
      try {
        targetWindow.addEventListener("keydown", handleKeydown);
      } catch (error) {
        // Cross-origin content cannot participate in pane shortcuts.
      }
    }

    function startResize(event) {
      if (event.button !== 0) return;
      event.preventDefault();
      const pointerId = event.pointerId;
      resizeHandle.setPointerCapture(pointerId);
      const update = (moveEvent) => {
        const rect = host.getBoundingClientRect();
        const requestedWidth = side === "left"
          ? moveEvent.clientX - rect.left
          : rect.right - moveEvent.clientX;
        const width = Math.max(210, Math.min(520, requestedWidth));
        shelf.style.width = `${width}px`;
        onResize();
      };
      const finish = () => {
        resizeHandle.removeEventListener("pointermove", update);
        resizeHandle.removeEventListener("pointerup", finish);
        resizeHandle.removeEventListener("pointercancel", finish);
        try {
          resizeHandle.releasePointerCapture(pointerId);
        } catch (error) {
          // Pointer capture may already be released.
        }
        saveWidth(shelf.getBoundingClientRect().width);
        onResize();
      };
      resizeHandle.addEventListener("pointermove", update);
      resizeHandle.addEventListener("pointerup", finish);
      resizeHandle.addEventListener("pointercancel", finish);
    }

    shelf.style.width = `${storedWidth()}px`;
    toggleButton.addEventListener("click", () => applyOpenState(!open));
    closeButton.addEventListener("click", () => applyOpenState(false));
    resizeHandle.addEventListener("pointerdown", startResize);
    bindKeyboardTarget(window);
    setEnabled(false);

    return {
      addSection,
      bindKeyboardTarget,
      close: () => applyOpenState(false),
      isOpen: () => open,
      open: openSection,
      setEnabled,
    };
  }

  window.ElectroBoyPaneTools = { actionButton, buttonGroup, create, iconSvg };
})();
