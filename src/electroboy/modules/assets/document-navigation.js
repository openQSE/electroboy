(function () {
  "use strict";

  const DEFAULT_HISTORY_LIMIT = 100;

  function target(value) {
    const candidate = value && typeof value === "object" ? value : {};
    const path = String(candidate.path || "").trim();
    if (path) {
      return {
        path,
        label: String(candidate.label || path),
      };
    }
    const rawUrl = String(candidate.url || candidate.href || "").trim();
    if (!/^https?:\/\//i.test(rawUrl)) {
      return null;
    }
    try {
      const url = new URL(rawUrl);
      if (url.protocol !== "http:" && url.protocol !== "https:") {
        return null;
      }
      return {
        url: url.href,
        label: String(candidate.label || rawUrl),
        external: true,
      };
    } catch (error) {
      return null;
    }
  }

  function location(value) {
    if (typeof value === "string") {
      return { fragment: value, scrollX: null, scrollY: null };
    }
    const candidate = value && typeof value === "object" ? value : {};
    const hasScrollX = typeof candidate.scrollX === "number"
      && Number.isFinite(candidate.scrollX);
    const hasScrollY = typeof candidate.scrollY === "number"
      && Number.isFinite(candidate.scrollY);
    return {
      fragment: String(candidate.fragment || ""),
      scrollX: hasScrollX ? Math.max(0, candidate.scrollX) : null,
      scrollY: hasScrollY ? Math.max(0, candidate.scrollY) : null,
    };
  }

  function entry(value, fallbackTarget = null) {
    const candidate = value && typeof value === "object" ? value : {};
    const normalizedTarget = target(candidate.target || fallbackTarget);
    if (!normalizedTarget) {
      return null;
    }
    return {
      target: normalizedTarget,
      location: location(candidate.location || candidate.fragment || ""),
    };
  }

  function destination(data) {
    const candidate = data && typeof data === "object" ? data : {};
    return entry({
      target: candidate.target,
      location: candidate.location || candidate.fragment || "",
    });
  }

  function frameEntry(frame, currentTarget) {
    const normalizedTarget = target(currentTarget);
    if (!normalizedTarget || !frame || !frame.contentWindow) {
      return null;
    }
    try {
      const frameWindow = frame.contentWindow;
      const hash = String(frameWindow.location.hash || "").replace(/^#/, "");
      let fragment = hash;
      try {
        fragment = decodeURIComponent(hash);
      } catch (error) {
        fragment = hash;
      }
      return entry({
        target: normalizedTarget,
        location: {
          fragment,
          scrollX: frameWindow.scrollX,
          scrollY: frameWindow.scrollY,
        },
      });
    } catch (error) {
      return entry({ target: normalizedTarget });
    }
  }

  function restoreFrame(frame, documentPath, nextLocation) {
    if (!frame || !frame.contentWindow || !documentPath || !nextLocation) {
      return;
    }
    frame.contentWindow.postMessage(
      {
        type: "electroboy:document-location",
        path: String(documentPath),
        location: location(nextLocation),
      },
      window.location.origin,
    );
  }

  function create(options = {}) {
    const requestedLimit = Number(options.limit || DEFAULT_HISTORY_LIMIT);
    const limit = Number.isFinite(requestedLimit) && requestedLimit > 0
      ? Math.floor(requestedLimit)
      : DEFAULT_HISTORY_LIMIT;
    const backEntries = [];
    const forwardEntries = [];

    function push(stack, value) {
      const normalized = entry(value);
      if (!normalized) {
        return;
      }
      stack.push(normalized);
      if (stack.length > limit) {
        stack.splice(0, stack.length - limit);
      }
    }

    function record(value) {
      push(backEntries, value);
      forwardEntries.length = 0;
    }

    function goBack(current) {
      if (backEntries.length === 0) {
        return null;
      }
      push(forwardEntries, current);
      return backEntries.pop() || null;
    }

    function goForward(current) {
      if (forwardEntries.length === 0) {
        return null;
      }
      push(backEntries, current);
      return forwardEntries.pop() || null;
    }

    return {
      destination,
      entry,
      frameEntry,
      location,
      record,
      restoreFrame,
      target,
      goBack,
      goForward,
      get canGoBack() {
        return backEntries.length > 0;
      },
      get canGoForward() {
        return forwardEntries.length > 0;
      },
    };
  }

  window.ElectroBoyDocumentNavigation = {
    create,
    destination,
    entry,
    frameEntry,
    location,
    restoreFrame,
    target,
  };
})();
