(function () {
  "use strict";

  const CURSOR_HIDE_SEQUENCE = "\x1b[?25l";
  const cursorlessTerminals = new WeakSet();
  const terminalWriteStates = new WeakMap();
  const VIEWPORT_INTERACTION_EVENTS = ["wheel", "pointerdown", "touchstart"];
  const VIEWPORT_SCROLL_KEYS = new Set([
    "ArrowDown",
    "ArrowUp",
    "End",
    "Home",
    "PageDown",
    "PageUp",
  ]);

  function writeStateFor(terminal) {
    let state = terminalWriteStates.get(terminal);
    if (!state) {
      state = {
        queue: [],
        writing: false,
        generation: 0,
        viewportInteractionEpoch: 0,
        trackingInstalled: false,
      };
      terminalWriteStates.set(terminal, state);
    }
    return state;
  }

  function noteViewportInteraction(terminal) {
    const state = writeStateFor(terminal);
    state.viewportInteractionEpoch += 1;
  }

  function installViewportTracking(terminal) {
    const state = writeStateFor(terminal);
    if (state.trackingInstalled || !terminal.element) {
      return;
    }
    state.trackingInstalled = true;
    for (const eventName of VIEWPORT_INTERACTION_EVENTS) {
      terminal.element.addEventListener(
        eventName,
        () => noteViewportInteraction(terminal),
        { passive: true },
      );
    }
    terminal.element.addEventListener("keydown", (event) => {
      if (VIEWPORT_SCROLL_KEYS.has(event.key)) {
        noteViewportInteraction(terminal);
      }
    });
  }

  function activeBuffer(terminal) {
    return terminal && terminal.buffer ? terminal.buffer.active : null;
  }

  function disposeViewportSnapshot(snapshot) {
    if (!snapshot || !snapshot.marker) {
      return;
    }
    snapshot.marker.dispose();
  }

  function viewportSnapshot(terminal) {
    const buffer = activeBuffer(terminal);
    if (!buffer) {
      return null;
    }
    const baseY = buffer.baseY;
    const viewportY = buffer.viewportY;
    const atBottom = viewportY >= baseY;
    let marker = null;
    if (!atBottom && typeof terminal.registerMarker === "function") {
      marker = terminal.registerMarker(viewportY - (baseY + buffer.cursorY));
    }
    return {
      atBottom,
      distanceFromBottom: Math.max(0, baseY - viewportY),
      marker,
    };
  }

  function restoreViewport(terminal, snapshot) {
    if (!snapshot) {
      return;
    }
    try {
      const buffer = activeBuffer(terminal);
      if (!buffer) {
        return;
      }
      if (snapshot.atBottom) {
        terminal.scrollToBottom();
      } else if (snapshot.marker && snapshot.marker.line >= 0) {
        terminal.scrollToLine(snapshot.marker.line);
      } else {
        terminal.scrollToLine(
          Math.max(0, buffer.baseY - snapshot.distanceFromBottom),
        );
      }
    } finally {
      disposeViewportSnapshot(snapshot);
    }
  }

  function flushWriteQueue(terminal, state) {
    if (!state || state.writing) {
      return;
    }
    const item = state.queue.shift();
    if (!item) {
      return;
    }
    state.writing = true;
    const snapshot = viewportSnapshot(terminal);
    const interactionEpoch = state.viewportInteractionEpoch;
    let completed = false;
    const complete = () => {
      if (completed) {
        return;
      }
      completed = true;
      state.writing = false;
      if (
        item.generation === state.generation &&
        interactionEpoch === state.viewportInteractionEpoch
      ) {
        restoreViewport(terminal, snapshot);
      } else {
        disposeViewportSnapshot(snapshot);
      }
      if (
        item.generation === state.generation &&
        typeof item.callback === "function"
      ) {
        item.callback();
      }
      flushWriteQueue(terminal, state);
    };
    try {
      terminal.write(item.text, complete);
    } catch (error) {
      complete();
      throw error;
    }
  }

  function write(terminal, text, callback = null) {
    if (!terminal || typeof terminal.write !== "function") {
      return false;
    }
    const output = String(text ?? "");
    if (!output) {
      if (typeof callback === "function") {
        callback();
      }
      return true;
    }
    const state = writeStateFor(terminal);
    state.queue.push({
      text: output,
      callback,
      generation: state.generation,
    });
    flushWriteQueue(terminal, state);
    return true;
  }

  function clearWrites(terminal) {
    const state = terminalWriteStates.get(terminal);
    if (!state) {
      return;
    }
    state.queue = [];
    state.generation += 1;
  }

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
    installViewportTracking(terminal);
    if (options.hideCursor === true) {
      cursorlessTerminals.add(terminal);
      hideCursor(terminal);
    }
  }

  function fit(terminal, fitAddon) {
    if (!terminal || !fitAddon) {
      return false;
    }
    const snapshot = viewportSnapshot(terminal);
    try {
      fitAddon.fit();
    } catch (error) {
      disposeViewportSnapshot(snapshot);
      throw error;
    }
    restoreViewport(terminal, snapshot);
    return true;
  }

  function reset(terminal) {
    if (!terminal) {
      return false;
    }
    clearWrites(terminal);
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

  window.ElectroBoyTerminalBehavior = { clearWrites, fit, install, reset, write };
})();
