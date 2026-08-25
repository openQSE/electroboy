(function () {
  "use strict";

  const CURSOR_HIDE_SEQUENCE = "\x1b[?25l";
  const cursorlessTerminals = new WeakSet();

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

  function hideCursor(terminal) {
    if (!terminal || typeof terminal.write !== "function") {
      return false;
    }
    terminal.write(CURSOR_HIDE_SEQUENCE);
    return true;
  }

  function install(terminal, options = {}) {
    if (!terminal) {
      return;
    }
    if (typeof terminal.attachCustomKeyEventHandler === "function") {
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
    if (
      terminal.parser &&
      typeof terminal.parser.registerCsiHandler === "function"
    ) {
      terminal.parser.registerCsiHandler(
        { final: "J" },
        (params) => params.length > 0 && params[0] === 3,
      );
      if (options.hideCursor === true) {
        // DECTCEM enables the terminal cursor. Output-only panes keep it hidden.
        terminal.parser.registerCsiHandler(
          { prefix: "?", final: "h" },
          (params) => params.length === 1 && params[0] === 25,
        );
      }
    }
    if (options.hideCursor === true) {
      cursorlessTerminals.add(terminal);
      hideCursor(terminal);
    }
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
    try {
      fitAddon.fit();
    } catch (error) {
      marker?.dispose();
      throw error;
    }

    try {
      const nextBuffer = terminal.buffer && terminal.buffer.active;
      if (!nextBuffer) {
        return true;
      }
      if (atBottom) {
        terminal.scrollToBottom();
      } else if (marker && marker.line >= 0) {
        terminal.scrollToLine(marker.line);
      } else {
        terminal.scrollToLine(Math.max(0, nextBuffer.baseY - distanceFromBottom));
      }
    } finally {
      marker?.dispose();
    }
    return true;
  }

  function reset(terminal) {
    if (!terminal) {
      return false;
    }
    let didReset = false;
    if (typeof terminal.reset === "function") {
      terminal.reset();
      didReset = true;
    }
    if (typeof terminal.clear === "function") {
      terminal.clear();
      if (cursorlessTerminals.has(terminal)) {
        hideCursor(terminal);
      }
      return true;
    }
    if (cursorlessTerminals.has(terminal)) {
      hideCursor(terminal);
    }
    return didReset;
  }

  window.ElectroBoyTerminalBehavior = { fit, install, reset };
})();
