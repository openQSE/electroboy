(function () {
  "use strict";

  const PICKER_PROPERTIES = [
    "--electroboy-select-picker-bg",
    "--electroboy-select-picker-border",
    "--electroboy-select-picker-hover",
    "--electroboy-select-picker-selected",
    "--electroboy-select-picker-text",
  ];
  let activeSelect = null;
  let menu = null;

  function ensureMenu() {
    if (menu) return menu;
    menu = document.createElement("div");
    menu.className = "electroboy-select-menu";
    menu.setAttribute("role", "listbox");
    menu.hidden = true;
    menu.addEventListener("keydown", handleMenuKeydown);
    document.body.append(menu);
    return menu;
  }

  function optionButtons() {
    return menu
      ? Array.from(menu.querySelectorAll(".electroboy-select-option:not(:disabled)"))
      : [];
  }

  function closeMenu(options = {}) {
    if (!activeSelect || !menu) return;
    const select = activeSelect;
    activeSelect = null;
    menu.hidden = true;
    menu.replaceChildren();
    select.setAttribute("aria-expanded", "false");
    if (options.focus !== false) select.focus({ preventScroll: true });
  }

  function chooseOption(index) {
    if (!activeSelect) return;
    const option = activeSelect.options[index];
    if (!option || option.disabled || option.parentElement?.disabled) return;
    const changed = activeSelect.selectedIndex !== index;
    activeSelect.selectedIndex = index;
    if (changed) {
      activeSelect.dispatchEvent(new Event("input", { bubbles: true }));
      activeSelect.dispatchEvent(new Event("change", { bubbles: true }));
    }
    closeMenu();
  }

  function appendOption(select, option, index) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "electroboy-select-option";
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", String(index === select.selectedIndex));
    item.disabled = Boolean(option.disabled || option.parentElement?.disabled);
    item.dataset.optionIndex = String(index);
    const mark = document.createElement("span");
    mark.className = "electroboy-select-option-mark";
    mark.setAttribute("aria-hidden", "true");
    mark.textContent = index === select.selectedIndex ? "✓" : "";
    const label = document.createElement("span");
    label.className = "electroboy-select-option-label";
    label.textContent = option.label || option.textContent || "";
    item.append(mark, label);
    item.addEventListener("click", () => chooseOption(index));
    menu.append(item);
  }

  function renderMenu(select) {
    const picker = ensureMenu();
    picker.replaceChildren();
    let lastGroup = null;
    Array.from(select.options).forEach((option, index) => {
      const group = option.parentElement instanceof HTMLOptGroupElement
        ? option.parentElement
        : null;
      if (group && group !== lastGroup) {
        const heading = document.createElement("div");
        heading.className = "electroboy-select-group";
        heading.textContent = group.label;
        picker.append(heading);
      }
      lastGroup = group;
      appendOption(select, option, index);
    });
  }

  function positionMenu(select) {
    const rect = select.getBoundingClientRect();
    const gap = 4;
    const viewportPadding = 8;
    menu.style.minWidth = `${Math.max(140, Math.round(rect.width))}px`;
    menu.style.left = `${Math.max(
      viewportPadding,
      Math.min(rect.left, window.innerWidth - menu.offsetWidth - viewportPadding),
    )}px`;
    const roomBelow = window.innerHeight - rect.bottom - viewportPadding;
    const openAbove = menu.offsetHeight > roomBelow && rect.top > roomBelow;
    const top = openAbove
      ? Math.max(viewportPadding, rect.top - menu.offsetHeight - gap)
      : Math.min(
        rect.bottom + gap,
        window.innerHeight - menu.offsetHeight - viewportPadding,
      );
    menu.style.top = `${Math.max(viewportPadding, top)}px`;
  }

  function openMenu(select) {
    if (select.disabled || select.multiple || Number(select.size || 0) > 1) return;
    if (activeSelect === select) {
      closeMenu();
      return;
    }
    closeMenu({ focus: false });
    activeSelect = select;
    renderMenu(select);
    const computed = getComputedStyle(select);
    for (const property of PICKER_PROPERTIES) {
      menu.style.setProperty(property, computed.getPropertyValue(property));
    }
    menu.hidden = false;
    select.setAttribute("aria-expanded", "true");
    positionMenu(select);
    const selected = menu.querySelector('[aria-selected="true"]:not(:disabled)');
    (selected || optionButtons()[0])?.focus({ preventScroll: true });
  }

  function handleMenuKeydown(event) {
    const buttons = optionButtons();
    const current = buttons.indexOf(document.activeElement);
    let next = -1;
    if (event.key === "ArrowDown") next = Math.min(buttons.length - 1, current + 1);
    if (event.key === "ArrowUp") next = Math.max(0, current - 1);
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = buttons.length - 1;
    if (next >= 0) {
      event.preventDefault();
      buttons[next]?.focus({ preventScroll: true });
      return;
    }
    if (event.key === "Escape" || event.key === "Tab") {
      if (event.key === "Escape") event.preventDefault();
      closeMenu();
    }
  }

  function enhanceSelect(select) {
    if (
      !(select instanceof HTMLSelectElement)
      || select.dataset.electroboyNativeSelect === "true"
      || select.multiple
      || Number(select.size || 0) > 1
      || select.classList.contains("electroboy-custom-select")
    ) {
      return;
    }
    select.classList.add("electroboy-custom-select");
    select.setAttribute("aria-haspopup", "listbox");
    select.setAttribute("aria-expanded", "false");
    select.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || select.disabled) return;
      event.preventDefault();
      select.focus({ preventScroll: true });
      openMenu(select);
    });
    select.addEventListener("click", (event) => event.preventDefault());
    select.addEventListener("keydown", (event) => {
      if (["Enter", " ", "ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault();
        openMenu(select);
      } else if (event.key === "Escape" && activeSelect === select) {
        event.preventDefault();
        closeMenu();
      }
    });
  }

  function enhanceTree(root) {
    if (root instanceof HTMLSelectElement) enhanceSelect(root);
    root.querySelectorAll?.("select").forEach(enhanceSelect);
  }

  function start() {
    enhanceTree(document);
    new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (node instanceof Element) enhanceTree(node);
        }
      }
      if (activeSelect && !activeSelect.isConnected) closeMenu({ focus: false });
    }).observe(document.documentElement, { childList: true, subtree: true });
    document.addEventListener("pointerdown", (event) => {
      if (
        activeSelect
        && event.target !== activeSelect
        && !menu?.contains(event.target)
      ) {
        closeMenu({ focus: false });
      }
    }, true);
    window.addEventListener("resize", () => closeMenu({ focus: false }));
    window.addEventListener("scroll", (event) => {
      if (menu && (event.target === menu || menu.contains(event.target))) {
        return;
      }
      closeMenu({ focus: false });
    }, true);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }

  window.ElectroBoySelectMenu = { enhance: enhanceTree, close: closeMenu };
})();
