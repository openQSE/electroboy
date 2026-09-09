(function (global) {
  "use strict";

  function moveBefore(parent, node, reference = null) {
    if (!parent || !node || typeof parent.moveBefore !== "function") {
      return false;
    }
    try {
      parent.moveBefore(node, reference);
      return true;
    } catch (error) {
      return false;
    }
  }

  function collapseSplit(split, removed, root, rootClass) {
    if (!split || !removed || removed.parentElement !== split) {
      return null;
    }
    const first = split.firstElementChild;
    const last = split.lastElementChild;
    const survivor = removed === first
      ? last
      : removed === last
        ? first
        : null;
    const destination = split.parentElement;
    if (!survivor || !destination || !moveBefore(destination, survivor, split)) {
      return null;
    }
    if (destination === root && rootClass) {
      survivor.classList.add(rootClass);
    }
    split.remove();
    return survivor;
  }

  global.ElectroBoyStatefulDOM = Object.freeze({ collapseSplit, moveBefore });
})(window);
