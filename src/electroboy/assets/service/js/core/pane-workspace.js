(function (global) {
  "use strict";

  function createWorkspace(options) {
    const root = options && options.root;
    const initialKind = String(options && options.initialKind || "agent");
    const kinds = Array.isArray(options && options.kinds) ? options.kinds : [];
    const kindMap = new Map(kinds.map((kind) => [kind.id, kind]));
    const storageKey = String(options && options.storageKey || "");
    let idSequence = 0;
    let layout = storedLayout();
    let cornerSplitCancel = null;
    let dragController = null;
    const paneFrames = new Map();

    if (!(root instanceof Element)) {
      throw new Error("pane workspace requires a root element");
    }

    function newId(prefix = "pane") {
      idSequence += 1;
      return `${prefix}-${Date.now()}-${idSequence}`;
    }

    function leaf(kind = "empty") {
      return { type: "leaf", id: newId(), kind };
    }

    function split(direction, first, second, ratio = 0.5) {
      return {
        type: "split",
        id: newId("split"),
        direction: direction === "column" ? "column" : "row",
        ratio: clamp(Number(ratio) || 0.5, 0.12, 0.88),
        first,
        second,
      };
    }

    function defaultLayout() {
      return leaf(kindMap.has(initialKind) ? initialKind : "empty");
    }

    function normalize(node) {
      if (!node || typeof node !== "object") {
        return null;
      }
      if (node.type === "leaf") {
        const kind = String(node.kind || "empty");
        return leaf(kind === "empty" || kindMap.has(kind) ? kind : "empty");
      }
      if (node.type !== "split") {
        return null;
      }
      const first = normalize(node.first);
      const second = normalize(node.second);
      if (!first || !second) {
        return null;
      }
      return split(node.direction, first, second, node.ratio);
    }

    function storedLayout() {
      if (!storageKey) {
        return defaultLayout();
      }
      try {
        return normalize(JSON.parse(global.localStorage.getItem(storageKey))) ||
          defaultLayout();
      } catch (error) {
        return defaultLayout();
      }
    }

    function saveLayout() {
      if (!storageKey) {
        return;
      }
      try {
        global.localStorage.setItem(storageKey, JSON.stringify(layout));
      } catch (error) {
        return;
      }
    }

    function clamp(value, minimum, maximum) {
      return Math.max(minimum, Math.min(maximum, value));
    }

    function leaves(node = layout, result = []) {
      if (node.type === "leaf") {
        result.push(node);
        return result;
      }
      leaves(node.first, result);
      leaves(node.second, result);
      return result;
    }

    function leafById(id) {
      return leaves().find((item) => item.id === id) || null;
    }

    function replaceNode(node, id, replacement) {
      if (node.id === id) {
        return replacement;
      }
      if (node.type === "leaf") {
        return node;
      }
      node.first = replaceNode(node.first, id, replacement);
      node.second = replaceNode(node.second, id, replacement);
      return node;
    }

    function removeLeaf(node, id) {
      if (node.type === "leaf") {
        return node.id === id ? null : node;
      }
      if (node.first.id === id) {
        return node.second;
      }
      if (node.second.id === id) {
        return node.first;
      }
      const first = removeLeaf(node.first, id);
      const second = removeLeaf(node.second, id);
      if (!first) return second;
      if (!second) return first;
      node.first = first;
      node.second = second;
      return node;
    }

    function toolbar(item) {
      const element = document.createElement("div");
      element.className = "workspace-pane-toolbar";
      element.dataset.paneDragHandle = "true";
      element.title = "Drag title or Shift-drag pane to move";

      const select = document.createElement("select");
      select.className = "workspace-pane-kind";
      select.title = "Choose pane type";
      select.setAttribute("aria-label", "Choose pane type");
      const emptyOption = document.createElement("option");
      emptyOption.value = "empty";
      emptyOption.textContent = "Choose pane";
      select.append(emptyOption);
      for (const kind of kinds) {
        const option = document.createElement("option");
        option.value = kind.id;
        option.textContent = kind.label;
        select.append(option);
      }
      select.value = item.kind;
      select.addEventListener("change", () => changeKind(item.id, select.value));

      const splitRight = commandButton("split-right", "Split pane right");
      splitRight.addEventListener("click", () => splitLeaf(item.id, "row"));
      const splitDown = commandButton("split-down", "Split pane down");
      splitDown.addEventListener("click", () => splitLeaf(item.id, "column"));
      const close = commandButton("close-pane", "Close pane and join area", "×");
      close.disabled = leaves().length <= 1;
      close.addEventListener("click", () => closeLeaf(item.id));
      const reset = commandButton("reset-layout", "Reset pane workspace", "↺");
      reset.addEventListener("click", resetLayout);
      element.append(select, splitRight, splitDown, close, reset);
      return element;
    }

    function commandButton(className, label, text = "") {
      const button = document.createElement("button");
      button.className = `workspace-pane-command ${className}`;
      button.type = "button";
      button.title = label;
      button.setAttribute("aria-label", label);
      button.textContent = text;
      return button;
    }

    function applySplitTemplate(element, node) {
      const ratio = clamp(Number(node.ratio) || 0.5, 0.12, 0.88);
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

    function startResize(event, node, splitElement, divider) {
      event.preventDefault();
      const pointerId = event.pointerId;
      divider.setPointerCapture(pointerId);
      divider.classList.add("resizing");
      const update = (moveEvent) => {
        const rect = splitElement.getBoundingClientRect();
        const available = node.direction === "column" ? rect.height - 7 : rect.width - 7;
        if (available <= 0) return;
        const position = node.direction === "column"
          ? moveEvent.clientY - rect.top - 3.5
          : moveEvent.clientX - rect.left - 3.5;
        node.ratio = clamp(position / available, 0.12, 0.88);
        applySplitTemplate(splitElement, node);
      };
      const finish = () => {
        divider.classList.remove("resizing");
        divider.removeEventListener("pointermove", update);
        divider.removeEventListener("pointerup", finish);
        divider.removeEventListener("pointercancel", finish);
        try {
          divider.releasePointerCapture(pointerId);
        } catch (error) {
          // Pointer capture may already be released.
        }
        saveLayout();
      };
      divider.addEventListener("pointermove", update);
      divider.addEventListener("pointerup", finish);
      divider.addEventListener("pointercancel", finish);
    }

    function cornerCandidate(event, state) {
      const topRight = state.corner === "top-right";
      const inwardX = topRight
        ? state.startX - event.clientX
        : event.clientX - state.startX;
      const inwardY = topRight
        ? event.clientY - state.startY
        : state.startY - event.clientY;
      if (Math.max(inwardX, inwardY) < 12) return null;
      const row = inwardX >= inwardY;
      const ratio = row
        ? (event.clientX - state.rect.left) / Math.max(state.rect.width, 1)
        : (event.clientY - state.rect.top) / Math.max(state.rect.height, 1);
      return {
        direction: row ? "row" : "column",
        emptyFirst: row ? !topRight : topRight,
        ratio: clamp(ratio, 0.12, 0.88),
      };
    }

    function showCornerPreview(preview, candidate) {
      preview.hidden = !candidate;
      if (!candidate) return;
      const ratio = candidate.ratio * 100;
      Object.assign(preview.style, {
        top: "0",
        right: "auto",
        bottom: "auto",
        left: "0",
        width: "100%",
        height: "100%",
      });
      if (candidate.direction === "row") {
        preview.style.width = candidate.emptyFirst ? `${ratio}%` : `${100 - ratio}%`;
        preview.style.left = candidate.emptyFirst ? "0" : `${ratio}%`;
      } else {
        preview.style.height = candidate.emptyFirst ? `${ratio}%` : `${100 - ratio}%`;
        preview.style.top = candidate.emptyFirst ? "0" : `${ratio}%`;
      }
    }

    function startCornerSplit(event, item, leafElement, corner, preview) {
      if (event.button !== 0) return;
      if (cornerSplitCancel) cornerSplitCancel();
      event.preventDefault();
      event.stopPropagation();
      const handle = event.currentTarget;
      const state = {
        corner,
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        rect: leafElement.getBoundingClientRect(),
        candidate: null,
        finished: false,
      };
      handle.setPointerCapture(event.pointerId);
      leafElement.classList.add("splitting");
      document.body.classList.add("workspace-splitting");
      const update = (moveEvent) => {
        state.candidate = cornerCandidate(moveEvent, state);
        showCornerPreview(preview, state.candidate);
      };
      const finish = (commit) => {
        if (state.finished) return;
        state.finished = true;
        cornerSplitCancel = null;
        handle.removeEventListener("pointermove", update);
        handle.removeEventListener("pointerup", pointerUp);
        handle.removeEventListener("pointercancel", pointerCancel);
        global.removeEventListener("keydown", keyDown);
        leafElement.classList.remove("splitting");
        document.body.classList.remove("workspace-splitting");
        showCornerPreview(preview, null);
        try {
          handle.releasePointerCapture(state.pointerId);
        } catch (error) {
          // Pointer capture may already be released.
        }
        if (commit && state.candidate) {
          splitLeaf(
            item.id,
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
      cornerSplitCancel = () => finish(false);
      handle.addEventListener("pointermove", update);
      handle.addEventListener("pointerup", pointerUp);
      handle.addEventListener("pointercancel", pointerCancel);
      global.addEventListener("keydown", keyDown);
    }

    function corner(item, leafElement, name, preview) {
      const handle = document.createElement("div");
      handle.className = `workspace-pane-corner ${name}`;
      handle.title = "Drag inward to split pane";
      handle.setAttribute("aria-hidden", "true");
      handle.addEventListener("pointerdown", (event) => {
        startCornerSplit(event, item, leafElement, name, preview);
      });
      return handle;
    }

    function paneFrame(item) {
      const existing = paneFrames.get(item.id);
      if (existing && existing.kind === item.kind) {
        return existing.frame;
      }
      const frame = document.createElement("iframe");
      frame.className = "workspace-pane-frame";
      frame.title = `${kindMap.get(item.kind).label} pane`;
      frame.src = options.paneUrl(item.kind);
      paneFrames.set(item.id, { kind: item.kind, frame });
      return frame;
    }

    function renderNode(node) {
      if (node.type === "leaf") {
        const element = document.createElement("div");
        element.className = "workspace-pane-leaf";
        element.dataset.workspacePaneId = node.id;
        element.dataset.paneKind = node.kind;
        element.append(toolbar(node));
        if (node.kind === "empty") {
          const empty = document.createElement("div");
          empty.className = "workspace-pane-empty";
          empty.textContent = "Choose a pane type";
          element.append(empty);
        } else {
          element.append(paneFrame(node));
        }
        const preview = document.createElement("div");
        preview.className = "workspace-pane-split-preview";
        preview.hidden = true;
        preview.setAttribute("aria-hidden", "true");
        element.append(
          preview,
          corner(node, element, "top-right", preview),
          corner(node, element, "bottom-left", preview),
        );
        return element;
      }

      const element = document.createElement("div");
      element.className = `workspace-pane-split ${node.direction}`;
      element.dataset.workspacePaneId = node.id;
      const first = renderNode(node.first);
      const divider = document.createElement("div");
      divider.className = `workspace-pane-divider ${node.direction}`;
      divider.setAttribute("role", "separator");
      divider.setAttribute(
        "aria-orientation",
        node.direction === "column" ? "horizontal" : "vertical",
      );
      divider.setAttribute("aria-label", "Resize split panes");
      divider.addEventListener("pointerdown", (event) => {
        startResize(event, node, element, divider);
      });
      element.append(first, divider, renderNode(node.second));
      applySplitTemplate(element, node);
      return element;
    }

    function render() {
      if (cornerSplitCancel) cornerSplitCancel();
      const element = renderNode(layout);
      element.classList.add("workspace-pane-root");
      root.replaceChildren(element);
      const activeIds = new Set(leaves().map((item) => item.id));
      for (const id of paneFrames.keys()) {
        if (!activeIds.has(id)) {
          paneFrames.delete(id);
        }
      }
      if (typeof options.onChange === "function") {
        options.onChange(layout, leaves());
      }
    }

    function splitLeaf(id, direction, ratio = 0.5, emptyFirst = false) {
      const item = leafById(id);
      if (!item) return;
      const existing = { ...item };
      const empty = leaf();
      layout = replaceNode(
        layout,
        id,
        split(
          direction,
          emptyFirst ? empty : existing,
          emptyFirst ? existing : empty,
          ratio,
        ),
      );
      saveLayout();
      render();
    }

    function changeKind(id, kind) {
      const item = leafById(id);
      if (!item || (kind !== "empty" && !kindMap.has(kind))) return;
      item.kind = kind;
      saveLayout();
      render();
    }

    function closeLeaf(id) {
      if (leaves().length <= 1 || !leafById(id)) return;
      layout = removeLeaf(layout, id);
      saveLayout();
      render();
    }

    function moveLeaf(sourceId, targetId, position) {
      const source = leafById(sourceId);
      const target = leafById(targetId);
      if (!source || !target || source === target) return;
      if (position === "center") {
        const kind = source.kind;
        source.kind = target.kind;
        target.kind = kind;
      } else {
        const moved = { ...source };
        layout = removeLeaf(layout, sourceId);
        const remainingTarget = leafById(targetId);
        if (!remainingTarget) return;
        const direction = position === "left" || position === "right"
          ? "row"
          : "column";
        const movedFirst = position === "left" || position === "top";
        layout = replaceNode(
          layout,
          remainingTarget.id,
          split(
            direction,
            movedFirst ? moved : remainingTarget,
            movedFirst ? remainingTarget : moved,
          ),
        );
      }
      saveLayout();
      render();
    }

    function resetLayout() {
      layout = defaultLayout();
      saveLayout();
      render();
    }

    function initializeDrag() {
      if (!global.ElectroBoyPaneDrag) return;
      dragController = global.ElectroBoyPaneDrag.createController({
        root,
        canDetach: false,
        sourceSelector: ".workspace-pane-leaf",
        source(element) {
          const item = leafById(String(element.dataset.workspacePaneId || ""));
          if (!item) return null;
          return {
            id: item.id,
            kind: item.kind,
            label: kindMap.get(item.kind)?.label || "Pane",
          };
        },
        canDrag(source) {
          return source.kind !== "empty";
        },
        label(source) {
          return source.label;
        },
        onDrop(source, target, position) {
          moveLeaf(source.id, target.id, position);
        },
      });
    }

    if (options.resetButton) {
      options.resetButton.addEventListener("click", resetLayout);
    }
    initializeDrag();
    render();
    return {
      reset: resetLayout,
      split: splitLeaf,
      layout: () => layout,
      destroy() {
        if (cornerSplitCancel) cornerSplitCancel();
        if (dragController) dragController.destroy();
      },
    };
  }

  global.ElectroBoyPaneWorkspace = { create: createWorkspace };
})(window);
