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

  window.ElectroBoyPaneTools = { create };
})();
