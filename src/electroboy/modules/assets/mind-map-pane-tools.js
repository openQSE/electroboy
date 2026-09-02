(function () {
  "use strict";

  const ICONS = Object.freeze({
    "file-plus": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><path d="M12 12v6"></path><path d="M9 15h6"></path>',
    "folder-open": '<path d="M3 7h7l2 2h9l-2 9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><path d="M3 7v11"></path>',
    save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><path d="M17 21v-8H7v8"></path><path d="M7 3v5h8"></path>',
    "save-as": '<path d="M12 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v4"></path><path d="M7 3v5h8"></path><path d="M7 21v-8h8v2"></path><path d="m16 19 4-4 2 2-4 4-3 1z"></path>',
    undo: '<path d="M9 7 4 12l5 5"></path><path d="M20 17a8 8 0 0 0-8-8H4"></path>',
    redo: '<path d="m15 7 5 5-5 5"></path><path d="M4 17a8 8 0 0 1 8-8h8"></path>',
    "node-root": '<circle cx="12" cy="12" r="7"></circle><path d="M12 9v6"></path><path d="M9 12h6"></path>',
    "node-child": '<circle cx="6" cy="6" r="2"></circle><circle cx="18" cy="18" r="2"></circle><path d="M6 8v4a6 6 0 0 0 6 6h4"></path><path d="M16 12h4"></path><path d="M18 10v4"></path>',
    "node-sibling": '<circle cx="6" cy="7" r="2"></circle><circle cx="18" cy="7" r="2"></circle><path d="M8 7h8"></path><path d="M12 7v10"></path><path d="M9 14v6"></path><path d="M6 17h6"></path>',
    edit: '<path d="M12 20h9"></path><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"></path>',
    delete: '<path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="m19 6-1 14H6L5 6"></path><path d="M10 11v5"></path><path d="M14 11v5"></path>',
    "file-link": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><path d="m10 13-1 1a2 2 0 0 0 3 3l1-1"></path><path d="m14 12 1-1a2 2 0 0 1 3 3l-1 1"></path><path d="m11 15 4-2"></path>',
    web: '<circle cx="12" cy="12" r="9"></circle><path d="M3 12h18"></path><path d="M12 3a15 15 0 0 1 0 18"></path><path d="M12 3a15 15 0 0 0 0 18"></path>',
    unlink: '<path d="m8 8-1-1a4 4 0 0 0-6 6l3 3a4 4 0 0 0 6 0l1-1"></path><path d="m16 16 1 1a4 4 0 0 0 6-6l-3-3a4 4 0 0 0-6 0l-1 1"></path><path d="m2 2 20 20"></path>',
    compact: '<path d="m8 3 4 4 4-4"></path><path d="M12 7V1"></path><path d="m8 21 4-4 4 4"></path><path d="M12 17v6"></path>',
    expanded: '<path d="m8 7 4-4 4 4"></path><path d="M12 3v6"></path><path d="m8 17 4 4 4-4"></path><path d="M12 21v-6"></path>',
    "zoom-out": '<circle cx="10.5" cy="10.5" r="7.5"></circle><path d="m16 16 5 5"></path><path d="M7.5 10.5h6"></path>',
    "zoom-in": '<circle cx="10.5" cy="10.5" r="7.5"></circle><path d="m16 16 5 5"></path><path d="M7.5 10.5h6"></path><path d="M10.5 7.5v6"></path>',
    fit: '<path d="M8 3H3v5"></path><path d="M16 3h5v5"></path><path d="M8 21H3v-5"></path><path d="M16 21h5v-5"></path>',
    focus: '<circle cx="12" cy="12" r="3"></circle><path d="M12 2v3"></path><path d="M12 19v3"></path><path d="M2 12h3"></path><path d="M19 12h3"></path>',
    collapse: '<path d="m7 3 5 5 5-5"></path><path d="m7 21 5-5 5 5"></path>',
    tidy: '<path d="M4 6h16"></path><path d="M7 12h10"></path><path d="M10 18h4"></path>',
    minus: '<path d="M5 12h14"></path>',
    plus: '<path d="M12 5v14"></path><path d="M5 12h14"></path>',
  });

  function iconSvg(name) {
    return `<svg class="mind-map-tool-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
  }

  function button(label, action, post, options = {}) {
    const control = document.createElement("button");
    control.type = "button";
    control.title = options.title || label;
    control.dataset.mindMapAction = action;
    if (options.iconOnly) {
      control.classList.add("mind-map-tool-icon-only");
      control.setAttribute("aria-label", options.title || label);
    }
    if (options.icon) {
      const icon = document.createElement("span");
      icon.className = "mind-map-tool-icon-wrap";
      icon.innerHTML = iconSvg(options.icon);
      control.append(icon);
    }
    const text = document.createElement("span");
    text.className = "mind-map-tool-label";
    text.textContent = label;
    control.append(text);
    control.addEventListener("click", () => post(action));
    return control;
  }

  function group(body, entries, post) {
    const wrapper = document.createElement("div");
    wrapper.className = "mind-map-tool-button-group";
    entries.forEach(([label, action, title, icon]) => {
      wrapper.append(button(label, action, post, { title, icon }));
    });
    body.append(wrapper);
  }

  function section(controller, id, label) {
    return controller.addSection(id, label, { open: false });
  }

  function fontSizeGroup(body, post) {
    const wrapper = document.createElement("div");
    wrapper.className = "mind-map-tool-font-row";
    const decrease = button("Decrease font size", "font-size-decrease", post, {
      icon: "minus",
      iconOnly: true,
    });
    const input = document.createElement("input");
    input.type = "number";
    input.min = "0.1";
    input.step = "1";
    input.value = "16";
    input.className = "mind-map-tool-font-size";
    input.setAttribute("aria-label", "Selected node font size in pixels");
    input.title = "Selected node font size in pixels";
    const increase = button("Increase font size", "font-size-increase", post, {
      icon: "plus",
      iconOnly: true,
    });
    function submit() {
      const fontSize = Number(input.value);
      if (!Number.isFinite(fontSize) || fontSize <= 0) return;
      post("font-size-set", { fontSize });
    }
    input.addEventListener("change", submit);
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      submit();
      input.blur();
    });
    wrapper.append(decrease, input, increase);
    body.append(wrapper);
    const automatic = button("Use generation size", "font-size-auto", post, {
      title: "Use the automatic size for this node generation",
    });
    automatic.classList.add("mind-map-tool-font-auto");
    body.append(automatic);
    return { decrease, input, increase, automatic };
  }

  function mount(options) {
    const controller = options.controller;
    const frame = options.frame;
    const controls = [];
    const selectionChannel = `mind-map-${Date.now().toString(36)}-${
      Math.random().toString(36).slice(2, 8)}`;
    let mapPath = "";
    let pendingPicker = null;
    let pendingPickerAction = "";

    function mapDirectory() {
      const separator = mapPath.lastIndexOf("/");
      return separator > 0 ? mapPath.slice(0, separator) : "/";
    }

    function send(action, details = {}) {
      if (!frame || !frame.contentWindow) return;
      frame.contentWindow.postMessage(
        { type: "electroboy-mind-map-command", action, ...details },
        window.location.origin,
      );
    }

    function openPicker(action) {
      if (pendingPicker && !pendingPicker.closed) {
        pendingPicker.focus();
        return;
      }
      const mode = action === "create-document" ? "document-new" : "link";
      const parameters = new URLSearchParams({
        path: mapDirectory(),
        mode,
        selection_channel: selectionChannel,
      });
      pendingPicker = window.open(
        `/file-browser?${parameters.toString()}`,
        `electroboy-${selectionChannel}`,
        "popup=yes,width=980,height=720,menubar=no,toolbar=no,location=no,"
          + "status=no,scrollbars=yes,resizable=yes",
      );
      pendingPickerAction = pendingPicker ? action : "";
    }

    function post(action, details = {}) {
      if (["link-file", "create-document"].includes(action) && !details.target) {
        openPicker(action);
        return;
      }
      send(action, details);
    }

    group(section(controller, "mind-map-file", "File"), [
      ["New", "new", "New mind map", "file-plus"],
      ["Open", "open", "Open mind map", "folder-open"],
      ["Save", "save", "Save mind map", "save"],
      ["Save As", "save-as", "Save mind map as", "save-as"],
    ], post);
    group(section(controller, "mind-map-edit", "Edit"), [
      ["Undo", "undo", "Undo", "undo"],
      ["Redo", "redo", "Redo", "redo"],
    ], post);
    group(section(controller, "mind-map-node", "Node"), [
      ["Independent", "root", "Add independent node", "node-root"],
      ["Child", "child", "Add child node", "node-child"],
      ["Sibling", "sibling", "Add sibling node", "node-sibling"],
      ["Edit", "edit", "Edit selected node", "edit"],
      ["Delete", "delete", "Delete selected node", "delete"],
    ], post);
    group(section(controller, "mind-map-color", "Color"), [
      ["Inherit", "color-default", "Inherit the nearest parent color"],
      ["Violet", "color-violet", "Use violet"],
      ["Blue", "color-blue", "Use blue"],
      ["Teal", "color-teal", "Use teal"],
      ["Green", "color-green", "Use green"],
      ["Amber", "color-amber", "Use amber"],
      ["Rose", "color-rose", "Use rose"],
    ], post);
    const fontControls = fontSizeGroup(
      section(controller, "mind-map-font", "Font size"),
      post,
    );
    group(section(controller, "mind-map-link", "Link"), [
      ["File", "link-file", "Link a file", "file-link"],
      ["Web", "link-web", "Link a website", "web"],
      ["Create document", "create-document", "Create linked document", "file-plus"],
      ["Remove", "remove-link", "Remove link", "unlink"],
    ], post);
    group(section(controller, "mind-map-view", "View"), [
      ["Compact", "compact", "Use compact nodes", "compact"],
      ["Expanded", "expand", "Expand node text", "expanded"],
      ["Zoom out", "zoom-out", "Zoom out", "zoom-out"],
      ["Zoom in", "zoom-in", "Zoom in", "zoom-in"],
      ["Fit", "fit", "Fit map to view", "fit"],
      ["Focus", "focus", "Focus selected node", "focus"],
      ["Collapse All", "collapse", "Collapse all branches", "collapse"],
      ["Tidy Branch", "tidy", "Tidy selected branch", "tidy"],
    ], post);
    document.querySelectorAll("[data-mind-map-action]").forEach((control) => {
      controls.push(control);
    });
    const needsSelection = new Set([
      "child", "sibling", "edit", "delete", "link-file", "link-web",
      "create-document", "remove-link", "color-default", "color-violet",
      "color-blue", "color-teal", "color-green", "color-amber", "color-rose",
      "font-size-decrease", "font-size-increase", "font-size-auto", "focus",
    ]);
    controls.forEach((control) => {
      control.disabled = needsSelection.has(control.dataset.mindMapAction)
        || ["undo", "redo"].includes(control.dataset.mindMapAction);
    });
    fontControls.input.disabled = true;

    function update(event) {
      if (event.origin !== window.location.origin) return;
      const data = event.data || {};
      if (
        data.type === "electroboy-file-browser-select"
        && data.selection_channel === selectionChannel
        && data.path
      ) {
        const action = pendingPickerAction
          || (data.mode === "document-new" ? "create-document" : "link-file");
        pendingPicker = null;
        pendingPickerAction = "";
        send(action, { target: String(data.path) });
        return;
      }
      if (data.type !== "electroboy-mind-map-state") return;
      mapPath = String(data.mapPath || mapPath);
      fontControls.input.disabled = !data.selected;
      if (document.activeElement !== fontControls.input) {
        fontControls.input.value = data.selected
          ? String(data.selectedFontSize || 16)
          : "16";
      }
      fontControls.automatic.setAttribute(
        "aria-pressed",
        String(Boolean(data.selected && data.selectedFontSizeMode !== "custom")),
      );
      controls.forEach((control) => {
        const action = control.dataset.mindMapAction;
        control.disabled = needsSelection.has(action) && !data.selected;
        if (action === "undo") control.disabled = !data.canUndo;
        if (action === "redo") control.disabled = !data.canRedo;
        if (action === "focus") {
          control.setAttribute("aria-pressed", String(Boolean(data.focusMode)));
        }
        if (action.startsWith("color-")) {
          control.setAttribute(
            "aria-pressed",
            String(data.selected && action === `color-${data.selectedColor || "default"}`),
          );
        }
      });
    }
    window.addEventListener("message", update);
    return {
      dispose: () => window.removeEventListener("message", update),
      setEditable: (editable) => controller.setEnabled(Boolean(editable)),
    };
  }

  window.ElectroBoyMindMapPaneTools = { mount };
})();
