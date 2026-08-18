(function () {
  "use strict";

  const fitVersions = new WeakMap();

  function legacyCopy(text) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.append(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
    } finally {
      textarea.remove();
    }
  }

  function copyText(text) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      return navigator.clipboard.writeText(text).catch(() => legacyCopy(text));
    }
    legacyCopy(text);
    return Promise.resolve();
  }

  function isCopySelectionEvent(terminal, event) {
    return event.type === "keydown"
      && (event.ctrlKey || event.metaKey)
      && !event.altKey
      && String(event.key).toLowerCase() === "c"
      && terminal.hasSelection();
  }

  function install(terminal) {
    if (!terminal || typeof terminal.attachCustomKeyEventHandler !== "function") {
      return;
    }
    terminal.attachCustomKeyEventHandler((event) => {
      if (!isCopySelectionEvent(terminal, event)) {
        return true;
      }
      event.preventDefault();
      event.stopPropagation();
      void copyText(terminal.getSelection());
      return false;
    });
  }

  function fit(terminal, fitAddon) {
    if (!terminal || !fitAddon) {
      return false;
    }
    const buffer = terminal.buffer && terminal.buffer.active;
    const baseY = buffer ? buffer.baseY : 0;
    const viewportY = buffer ? buffer.viewportY : 0;
    const atBottom = viewportY >= baseY;
    const distanceFromBottom = Math.max(0, baseY - viewportY);
    const marker = !atBottom && buffer && typeof terminal.registerMarker === "function"
      ? terminal.registerMarker(viewportY - (baseY + buffer.cursorY))
      : null;
    const version = (fitVersions.get(terminal) || 0) + 1;
    fitVersions.set(terminal, version);

    try {
      fitAddon.fit();
    } catch (error) {
      marker?.dispose();
      throw error;
    }

    window.requestAnimationFrame(() => {
      if (fitVersions.get(terminal) !== version) {
        marker?.dispose();
        return;
      }
      const nextBuffer = terminal.buffer && terminal.buffer.active;
      if (!nextBuffer) {
        marker?.dispose();
        return;
      }
      if (atBottom) {
        terminal.scrollToBottom();
      } else if (marker && marker.line >= 0) {
        terminal.scrollToLine(marker.line);
      } else {
        terminal.scrollToLine(Math.max(0, nextBuffer.baseY - distanceFromBottom));
      }
      marker?.dispose();
    });
    return true;
  }

  window.ElectroBoyTerminalBehavior = { fit, install };
})();
