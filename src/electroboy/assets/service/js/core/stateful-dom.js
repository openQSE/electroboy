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

  global.ElectroBoyStatefulDOM = Object.freeze({ moveBefore });
})(window);
