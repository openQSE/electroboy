(function () {
  "use strict";

  const CURSOR_HIDE_SEQUENCE = "\x1b[?25l";
  const cursorlessTerminals = new WeakSet();
  const terminalWriteStates = new WeakMap();
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
        lockedViewport: null,
        viewportLockRefreshTimer: null,
        viewportInteractionEpoch: 0,
        viewportPointerActive: false,
        viewportScrollPending: false,
        trackingInstalled: false,
      };
      terminalWriteStates.set(terminal, state);
    }
    return state;
  }

  function noteViewportInteraction(terminal) {
    const state = writeStateFor(terminal);
    state.viewportInteractionEpoch += 1;
    state.viewportScrollPending = true;
    scheduleViewportLockRefresh(terminal, state);
  }

  function beginViewportPointerInteraction(terminal) {
    const state = writeStateFor(terminal);
    state.viewportPointerActive = true;
    noteViewportInteraction(terminal);
  }

  function endViewportPointerInteraction(terminal) {
    writeStateFor(terminal).viewportPointerActive = false;
  }

  function clearViewportLock(state) {
    if (!state) {
      return;
    }
    disposeViewportSnapshot(state.lockedViewport);
    state.lockedViewport = null;
  }

  function replaceViewportLock(state, snapshot) {
    if (!state) {
      disposeViewportSnapshot(snapshot);
      return null;
    }
    disposeViewportSnapshot(state.lockedViewport);
    state.lockedViewport = snapshot;
    return snapshot;
  }

  function lockedViewport(state) {
    const snapshot = state ? state.lockedViewport : null;
    if (
      snapshot &&
      snapshot.marker &&
      typeof snapshot.marker.line === "number" &&
      snapshot.marker.line < 0
    ) {
      clearViewportLock(state);
      return null;
    }
    return snapshot && !snapshot.atBottom ? snapshot : null;
  }

  function refreshViewportLock(terminal, state = writeStateFor(terminal)) {
    state.viewportScrollPending = false;
    const snapshot = viewportSnapshot(terminal);
    if (!snapshot) {
      clearViewportLock(state);
      return null;
    }
    if (snapshot.atBottom) {
      disposeViewportSnapshot(snapshot);
      clearViewportLock(state);
      return null;
    }
    return replaceViewportLock(state, snapshot);
  }

  function scheduleViewportLockRefresh(terminal, state) {
    if (
      !state ||
      state.viewportLockRefreshTimer !== null ||
      typeof window.setTimeout !== "function"
    ) {
      return;
    }
    state.viewportLockRefreshTimer = window.setTimeout(() => {
      state.viewportLockRefreshTimer = null;
      if (state.viewportScrollPending) {
        refreshViewportLock(terminal, state);
      }
    }, 0);
  }

  function clearViewportLockRefresh(state) {
    if (!state || state.viewportLockRefreshTimer === null) {
      return;
    }
    if (typeof window.clearTimeout === "function") {
      window.clearTimeout(state.viewportLockRefreshTimer);
    }
    state.viewportLockRefreshTimer = null;
  }

  function handleViewportScroll(terminal, state) {
    if (!state) {
      return;
    }
    if (state.viewportLockRefreshTimer !== null) {
      clearViewportLockRefresh(state);
    }
    if (state.viewportScrollPending || !state.writing) {
      refreshViewportLock(terminal, state);
    }
  }

  function installViewportTracking(terminal) {
    const state = writeStateFor(terminal);
    if (state.trackingInstalled) {
      return;
    }
    state.trackingInstalled = true;
    if (terminal.element) {
      terminal.element.addEventListener(
        "wheel",
        () => noteViewportInteraction(terminal),
        { passive: true },
      );
      terminal.element.addEventListener(
        "pointerdown",
        () => beginViewportPointerInteraction(terminal),
        { passive: true },
      );
      terminal.element.addEventListener(
        "pointermove",
        (event) => {
          if (state.viewportPointerActive || event.buttons) {
            noteViewportInteraction(terminal);
          }
        },
        { passive: true },
      );
      terminal.element.addEventListener(
        "pointerup",
        () => endViewportPointerInteraction(terminal),
        { passive: true },
      );
      terminal.element.addEventListener(
        "pointercancel",
        () => endViewportPointerInteraction(terminal),
        { passive: true },
      );
      terminal.element.addEventListener(
        "touchstart",
        () => beginViewportPointerInteraction(terminal),
        { passive: true },
      );
      terminal.element.addEventListener(
        "touchmove",
        () => noteViewportInteraction(terminal),
        { passive: true },
      );
      terminal.element.addEventListener(
        "touchend",
        () => endViewportPointerInteraction(terminal),
        { passive: true },
      );
      terminal.element.addEventListener(
        "touchcancel",
        () => endViewportPointerInteraction(terminal),
        { passive: true },
      );
      terminal.element.addEventListener("keydown", (event) => {
        if (VIEWPORT_SCROLL_KEYS.has(event.key)) {
          noteViewportInteraction(terminal);
        }
      });
    }
    if (typeof terminal.onScroll === "function") {
      terminal.onScroll(() => handleViewportScroll(terminal, state));
    }
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

  function liveTailVisible(terminal, buffer) {
    const rows = Number(terminal.rows || 0);
    if (rows <= 0) {
      return buffer.viewportY >= buffer.baseY;
    }
    const cursorLine = buffer.baseY + buffer.cursorY;
    return cursorLine >= buffer.viewportY && cursorLine < buffer.viewportY + rows;
  }

  function viewportSnapshot(terminal) {
    const buffer = activeBuffer(terminal);
    if (!buffer) {
      return null;
    }
    const baseY = buffer.baseY;
    const viewportY = buffer.viewportY;
    const atBottom = viewportY >= baseY;
    const tailVisible = liveTailVisible(terminal, buffer);
    let marker = null;
    if (!tailVisible && typeof terminal.registerMarker === "function") {
      marker = terminal.registerMarker(viewportY - (baseY + buffer.cursorY));
    }
    return {
      atBottom,
      distanceFromBottom: Math.max(0, baseY - viewportY),
      marker,
      tailVisible,
    };
  }

  function scrollToViewportSnapshot(terminal, snapshot) {
    if (!snapshot) {
      return;
    }
    const buffer = activeBuffer(terminal);
    if (!buffer) {
      return;
    }
    if (snapshot.atBottom) {
      terminal.scrollToBottom();
    } else if (snapshot.tailVisible) {
      // Keep the same distance from the bottom so every new row pushes the
      // complete visible viewport upward while the live tail remains visible.
      terminal.scrollToLine(
        Math.max(0, buffer.baseY - snapshot.distanceFromBottom),
      );
    } else if (snapshot.marker && snapshot.marker.line >= 0) {
      terminal.scrollToLine(snapshot.marker.line);
    } else {
      terminal.scrollToLine(
        Math.max(0, buffer.baseY - snapshot.distanceFromBottom),
      );
    }
  }

  function restoreViewport(terminal, snapshot) {
    try {
      scrollToViewportSnapshot(terminal, snapshot);
    } finally {
      disposeViewportSnapshot(snapshot);
    }
  }

  function restoreLockedViewport(terminal, state) {
    const snapshot = lockedViewport(state);
    if (!snapshot) {
      return false;
    }
    scrollToViewportSnapshot(terminal, snapshot);
    return true;
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
        restoreLockedViewport(terminal, state)
      ) {
        disposeViewportSnapshot(snapshot);
      } else if (
        item.generation === state.generation &&
        interactionEpoch === state.viewportInteractionEpoch
      ) {
        restoreViewport(terminal, snapshot);
      } else {
        if (state.viewportScrollPending) {
          refreshViewportLock(terminal, state);
          restoreLockedViewport(terminal, state);
        }
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
    state.viewportPointerActive = false;
    state.viewportScrollPending = false;
    clearViewportLockRefresh(state);
    clearViewportLock(state);
  }

  function followOutput(terminal) {
    if (!terminal) {
      return false;
    }
    const state = writeStateFor(terminal);
    state.viewportInteractionEpoch += 1;
    state.viewportPointerActive = false;
    state.viewportScrollPending = false;
    clearViewportLockRefresh(state);
    clearViewportLock(state);
    if (typeof terminal.scrollToBottom === "function") {
      terminal.scrollToBottom();
    }
    return true;
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
    const state = writeStateFor(terminal);
    if (restoreLockedViewport(terminal, state)) {
      disposeViewportSnapshot(snapshot);
    } else {
      restoreViewport(terminal, snapshot);
    }
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

  window.ElectroBoyTerminalBehavior = {
    clearWrites,
    fit,
    followOutput,
    install,
    reset,
    write,
  };
})();
