(function (global) {
  "use strict";

  const DEFAULT_SOURCE_SELECTOR = ".pane-layout-leaf";
  const DEFAULT_HANDLE_SELECTOR = "[data-pane-drag-handle]";
  const DEFAULT_INTERACTIVE_SELECTOR = [
    "button",
    "select",
    "input",
    "textarea",
    "a",
    "[contenteditable='true']",
    "[data-pane-drag-ignore]",
  ].join(",");
  const DRAG_THRESHOLD = 6;
  const EDGE_RATIO = 0.28;

  function pointInside(rect, x, y) {
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
  }

  function dropPosition(rect, x, y) {
    const horizontal = (x - rect.left) / Math.max(rect.width, 1);
    const vertical = (y - rect.top) / Math.max(rect.height, 1);
    const edges = [
      { position: "left", distance: horizontal },
      { position: "right", distance: 1 - horizontal },
      { position: "top", distance: vertical },
      { position: "bottom", distance: 1 - vertical },
    ].sort((left, right) => left.distance - right.distance);
    return edges[0].distance <= EDGE_RATIO ? edges[0].position : "center";
  }

  function previewRect(rect, position) {
    const preview = {
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height,
    };
    if (position === "left" || position === "right") {
      preview.width = rect.width / 2;
      if (position === "right") {
        preview.left += preview.width;
      }
    } else if (position === "top" || position === "bottom") {
      preview.height = rect.height / 2;
      if (position === "bottom") {
        preview.top += preview.height;
      }
    }
    return preview;
  }

  function createOverlay(className, text = "") {
    const element = document.createElement("div");
    element.className = className;
    element.textContent = text;
    element.hidden = true;
    element.setAttribute("aria-hidden", "true");
    document.body.append(element);
    return element;
  }

  function createController(options) {
    const root = options && options.root;
    if (!(root instanceof Element)) {
      throw new Error("pane drag controller requires a root element");
    }
    if (typeof options.source !== "function") {
      throw new Error("pane drag controller requires a source callback");
    }

    const sourceSelector = options.sourceSelector || DEFAULT_SOURCE_SELECTOR;
    const handleSelector = options.handleSelector || DEFAULT_HANDLE_SELECTOR;
    const interactiveSelector =
      options.interactiveSelector || DEFAULT_INTERACTIVE_SELECTOR;
    const canDetach = options.canDetach !== false;
    const detachTarget = createOverlay(
      "pane-drag-detach-target",
      options.detachLabel || "Open in window",
    );
    const preview = createOverlay("pane-drag-preview");
    const ghost = createOverlay("pane-drag-ghost");
    let state = null;
    let suppressClick = false;

    function sourceElement(target) {
      if (!(target instanceof Element)) {
        return null;
      }
      const element = target.closest(sourceSelector);
      return element && root.contains(element) ? element : null;
    }

    function allowedStart(event, element) {
      if (event.button !== 0 || !element) {
        return false;
      }
      const source = options.source(element);
      if (!source || (options.canDrag && !options.canDrag(source, element))) {
        return false;
      }
      if (event.ctrlKey) {
        return !event.target.closest("[data-pane-drag-ignore]");
      }
      const handle = event.target.closest(handleSelector);
      return Boolean(
        handle &&
        element.contains(handle) &&
        !event.target.closest(interactiveSelector),
      );
    }

    function outsideViewport(event) {
      return (
        event.clientX <= 0 ||
        event.clientY <= 0 ||
        event.clientX >= global.innerWidth - 1 ||
        event.clientY >= global.innerHeight - 1
      );
    }

    function targetCandidate(event) {
      if (canDetach) {
        const detachRect = detachTarget.getBoundingClientRect();
        if (pointInside(detachRect, event.clientX, event.clientY)) {
          return { type: "detach" };
        }
        if (outsideViewport(event)) {
          return { type: "detach", outside: true };
        }
      }
      for (const element of root.querySelectorAll(sourceSelector)) {
        if (element === state.element || element.hidden) {
          continue;
        }
        const rect = element.getBoundingClientRect();
        if (
          rect.width <= 0 ||
          rect.height <= 0 ||
          !pointInside(rect, event.clientX, event.clientY)
        ) {
          continue;
        }
        const target = options.source(element);
        if (!target) {
          continue;
        }
        return {
          type: "layout",
          element,
          target,
          position: dropPosition(rect, event.clientX, event.clientY),
          rect,
        };
      }
      return null;
    }

    function positionOverlay(element, rect) {
      element.style.left = `${Math.round(rect.left)}px`;
      element.style.top = `${Math.round(rect.top)}px`;
      element.style.width = `${Math.max(0, Math.round(rect.width))}px`;
      element.style.height = `${Math.max(0, Math.round(rect.height))}px`;
    }

    function showCandidate(candidate) {
      detachTarget.classList.toggle("active", candidate?.type === "detach");
      if (!candidate || candidate.type !== "layout") {
        preview.hidden = true;
        return;
      }
      preview.dataset.position = candidate.position;
      positionOverlay(preview, previewRect(candidate.rect, candidate.position));
      preview.hidden = false;
    }

    function moveGhost(event) {
      ghost.style.left = `${event.clientX + 14}px`;
      ghost.style.top = `${event.clientY + 14}px`;
    }

    function beginDrag(event) {
      state.dragging = true;
      state.element.classList.add("pane-drag-source");
      document.body.classList.add("pane-dragging");
      detachTarget.hidden = !canDetach;
      ghost.textContent = options.label
        ? options.label(state.source)
        : String(state.source.label || state.source.kind || "Pane");
      ghost.hidden = false;
      moveGhost(event);
      if (typeof options.onStart === "function") {
        options.onStart(state.source);
      }
    }

    function clearState(didDrag) {
      if (!state) {
        return;
      }
      const previous = state;
      state = null;
      previous.element.classList.remove("pane-drag-source");
      document.body.classList.remove("pane-dragging");
      detachTarget.hidden = true;
      detachTarget.classList.remove("active");
      preview.hidden = true;
      ghost.hidden = true;
      try {
        previous.element.releasePointerCapture(previous.pointerId);
      } catch (error) {
        // Pointer capture may already be released by the browser.
      }
      if (didDrag) {
        suppressClick = true;
        global.setTimeout(() => {
          suppressClick = false;
        }, 0);
      }
      if (typeof options.onEnd === "function") {
        options.onEnd(previous.source, didDrag);
      }
    }

    function pointerDown(event) {
      if (state) {
        return;
      }
      const element = sourceElement(event.target);
      if (!allowedStart(event, element)) {
        return;
      }
      const source = options.source(element);
      state = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        element,
        source,
        candidate: null,
        dragging: false,
      };
      event.preventDefault();
      event.stopPropagation();
      element.setPointerCapture(event.pointerId);
    }

    function pointerMove(event) {
      if (!state || event.pointerId !== state.pointerId) {
        return;
      }
      const distance = Math.hypot(
        event.clientX - state.startX,
        event.clientY - state.startY,
      );
      if (!state.dragging && distance < DRAG_THRESHOLD) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      if (!state.dragging) {
        beginDrag(event);
      }
      state.candidate = targetCandidate(event);
      moveGhost(event);
      showCandidate(state.candidate);
    }

    function pointerUp(event) {
      if (!state || event.pointerId !== state.pointerId) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      const previous = state;
      const candidate = previous.dragging ? targetCandidate(event) : null;
      clearState(previous.dragging);
      if (!candidate) {
        return;
      }
      if (candidate.type === "detach") {
        if (typeof options.onDetach === "function") {
          options.onDetach(previous.source);
        }
        return;
      }
      if (typeof options.onDrop === "function") {
        options.onDrop(previous.source, candidate.target, candidate.position);
      }
    }

    function pointerCancel(event) {
      if (state && event.pointerId === state.pointerId) {
        clearState(state.dragging);
      }
    }

    function keyDown(event) {
      if (event.key === "Control") {
        root.classList.add("pane-layout-ctrl-ready");
      }
      if (event.key === "Escape" && state) {
        event.preventDefault();
        clearState(state.dragging);
      }
    }

    function keyUp(event) {
      if (event.key === "Control") {
        root.classList.remove("pane-layout-ctrl-ready");
      }
    }

    function windowBlur() {
      root.classList.remove("pane-layout-ctrl-ready");
      if (state) {
        clearState(state.dragging);
      }
    }

    function click(event) {
      if (!suppressClick) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      suppressClick = false;
    }

    root.addEventListener("pointerdown", pointerDown, true);
    root.addEventListener("pointermove", pointerMove, true);
    root.addEventListener("pointerup", pointerUp, true);
    root.addEventListener("pointercancel", pointerCancel, true);
    root.addEventListener("click", click, true);
    global.addEventListener("keydown", keyDown, true);
    global.addEventListener("keyup", keyUp, true);
    global.addEventListener("blur", windowBlur);

    return Object.freeze({
      cancel() {
        clearState(Boolean(state && state.dragging));
      },
      destroy() {
        clearState(Boolean(state && state.dragging));
        root.classList.remove("pane-layout-ctrl-ready");
        root.removeEventListener("pointerdown", pointerDown, true);
        root.removeEventListener("pointermove", pointerMove, true);
        root.removeEventListener("pointerup", pointerUp, true);
        root.removeEventListener("pointercancel", pointerCancel, true);
        root.removeEventListener("click", click, true);
        global.removeEventListener("keydown", keyDown, true);
        global.removeEventListener("keyup", keyUp, true);
        global.removeEventListener("blur", windowBlur);
        detachTarget.remove();
        preview.remove();
        ghost.remove();
      },
    });
  }

  global.ElectroBoyPaneDrag = Object.freeze({
    createController,
  });
})(window);
