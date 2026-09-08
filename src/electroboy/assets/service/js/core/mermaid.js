(function () {
  "use strict";

  const MERMAID_SCRIPT_URL =
    "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js";
  const popupFeatures =
    "popup=yes,width=980,height=720,menubar=no,toolbar=no,location=no,status=no,scrollbars=yes,resizable=yes";
  let loader = null;

  const mermaidConfiguration = {
    startOnLoad: false,
    securityLevel: "strict",
    theme: "base",
    themeVariables: {
      background: "#10141f",
      mainBkg: "#151b29",
      primaryColor: "#151b29",
      primaryTextColor: "#e7edf7",
      primaryBorderColor: "#364156",
      lineColor: "#66d9e8",
      secondaryColor: "#1d2638",
      secondaryTextColor: "#e7edf7",
      tertiaryColor: "#10141f",
      tertiaryTextColor: "#e7edf7",
      textColor: "#e7edf7",
      nodeBorder: "#364156",
      clusterBkg: "#10141f",
      clusterBorder: "#2a3142",
      edgeLabelBackground: "#10141f",
      fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
    },
  };

  function diagramsIn(root) {
    if (!root || typeof root.querySelectorAll !== "function") {
      return [];
    }
    const diagrams = Array.from(root.querySelectorAll(".mermaid"));
    if (typeof root.matches === "function" && root.matches(".mermaid")) {
      diagrams.unshift(root);
    }
    return diagrams;
  }

  function loadMermaid() {
    if (window.mermaid) {
      return Promise.resolve(window.mermaid);
    }
    if (loader) {
      return loader;
    }
    loader = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = MERMAID_SCRIPT_URL;
      script.dataset.electroboyMermaidLoader = "1";
      script.onload = () => resolve(window.mermaid);
      script.onerror = () => {
        loader = null;
        reject(new Error("Could not load Mermaid"));
      };
      document.head.append(script);
    });
    return loader;
  }

  function prepareMermaidPopouts(root = document) {
    for (const diagram of diagramsIn(root)) {
      if (diagram.dataset.electroboyPopout === "1") {
        continue;
      }
      diagram.dataset.electroboyPopout = "1";
      diagram.tabIndex = 0;
      diagram.setAttribute("role", "button");
      diagram.setAttribute(
        "aria-label",
        "Open Mermaid diagram in a separate window",
      );
      diagram.title = "Open diagram";
      diagram.addEventListener("click", () => openMermaidPopup(diagram));
      diagram.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") {
          return;
        }
        event.preventDefault();
        openMermaidPopup(diagram);
      });
    }
  }

  async function renderMermaidBlocks(root = document) {
    const diagrams = diagramsIn(root);
    if (!diagrams.length) {
      return;
    }
    const pending = diagrams.filter((diagram) => !diagram.querySelector("svg"));
    if (pending.length) {
      try {
        const mermaid = await loadMermaid();
        mermaid.initialize(mermaidConfiguration);
        await mermaid.run({ nodes: pending });
      } catch (error) {
        console.warn("Mermaid render failed", error);
      }
    }
    prepareMermaidPopouts(root);
  }

  function openMermaidPopup(diagram) {
    let popupUrl = "";
    try {
      popupUrl = URL.createObjectURL(new Blob(
        [mermaidPopupHtml(diagramMarkup(diagram))],
        { type: "text/html" },
      ));
    } catch (error) {
      console.warn("Could not prepare Mermaid popup", error);
      return;
    }
    const popup = window.open(
      popupUrl,
      "electroboy-mermaid-diagram",
      popupFeatures,
    );
    if (!popup) {
      URL.revokeObjectURL(popupUrl);
      return;
    }
    window.setTimeout(() => URL.revokeObjectURL(popupUrl), 30000);
  }

  function diagramMarkup(diagram) {
    const clone = diagram.cloneNode(true);
    clone.classList.add("popup-mermaid-diagram");
    clone.removeAttribute("tabindex");
    clone.removeAttribute("role");
    clone.removeAttribute("title");
    return clone.outerHTML;
  }

  function mermaidPopupHtml(diagramHtml) {
    return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mermaid diagram</title>
  <style>
:root {
  color-scheme: dark;
  --bg: #10141f;
  --panel: #151b29;
  --text: #e7edf7;
  --muted: #aab8cf;
  --border: #2a3142;
  --button: #1d2638;
  --accent: #66d9e8;
}
* {
  box-sizing: border-box;
}
html,
body {
  height: 100%;
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system,
    BlinkMacSystemFont, "Segoe UI", sans-serif;
  overflow: hidden;
}
.diagram-window {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  height: 100vh;
}
.diagram-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 42px;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
  padding: 0 12px;
}
.diagram-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  font-size: 12px;
  font-weight: 750;
  text-transform: uppercase;
}
.diagram-controls {
  display: flex;
  align-items: center;
  gap: 6px;
}
.diagram-controls button {
  min-width: 34px;
  height: 30px;
  border: 1px solid #364156;
  border-radius: 6px;
  background: var(--button);
  color: var(--text);
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  font-weight: 750;
}
.diagram-controls button:hover:not(:disabled) {
  border-color: var(--accent);
  background: #22314a;
}
.diagram-controls button:disabled {
  cursor: default;
  opacity: 0.45;
}
.zoom-level {
  min-width: 48px;
  text-align: center;
  color: var(--muted);
  font-size: 12px;
  font-weight: 750;
}
.diagram-stage {
  position: relative;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  background: var(--bg);
}
.sequence-header {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: 5;
  height: 44px;
  overflow: hidden;
  border-bottom: 1px solid rgb(102 217 232 / 24%);
  background: linear-gradient(
    180deg,
    rgb(21 27 41 / 96%),
    rgb(16 20 31 / 84%)
  );
  pointer-events: none;
}
.sequence-header[hidden] {
  display: none;
}
.sequence-header-track {
  position: relative;
  height: 100%;
  min-width: 100%;
}
.sequence-header-actor {
  position: absolute;
  top: 7px;
  left: 0;
  display: flex;
  height: 30px;
  max-width: 240px;
  min-width: 72px;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 1px solid #4e637e;
  border-radius: 6px;
  background: #202b3d;
  color: var(--text);
  box-shadow: 0 8px 24px rgb(0 0 0 / 28%);
  font-size: 12px;
  font-weight: 750;
  line-height: 1.2;
  overflow-wrap: anywhere;
  padding: 0 10px;
  text-align: center;
  white-space: normal;
}
.diagram-viewport {
  position: absolute;
  inset: 0;
  min-height: 0;
  height: 100%;
  width: 100%;
  overflow: auto;
  background: var(--bg);
  cursor: grab;
  user-select: none;
}
.diagram-viewport.dragging {
  cursor: grabbing;
}
.diagram-viewport.dragging * {
  user-select: none;
}
.diagram-content {
  display: inline-block;
  min-height: 100%;
  min-width: 100%;
  padding: 24px;
}
.diagram-content .mermaid {
  display: inline-block;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: default;
}
.diagram-content svg {
  display: block;
  max-width: none !important;
  max-height: none !important;
  height: auto;
  overflow: visible;
}
  </style>
</head>
<body>
  <main class="diagram-window">
<header class="diagram-toolbar">
  <span id="diagramTitle" class="diagram-title">Mermaid diagram</span>
  <div class="diagram-controls">
    <button id="zoomOut" type="button" title="Zoom out" aria-label="Zoom out">-</button>
    <span id="zoomLevel" class="zoom-level">100%</span>
    <button id="zoomReset" type="button" title="Reset zoom" aria-label="Reset zoom">100%</button>
    <button id="zoomIn" type="button" title="Zoom in" aria-label="Zoom in">+</button>
  </div>
</header>
<section class="diagram-stage">
  <div id="sequenceHeader" class="sequence-header" hidden>
    <div id="sequenceHeaderTrack" class="sequence-header-track"></div>
  </div>
  <div class="diagram-viewport">
    <div id="diagramContent" class="diagram-content">${diagramHtml}</div>
  </div>
</section>
  </main>
  <script>
(() => {
  const minimumZoom = 0.4;
  const maximumZoom = 4;
  const zoomStep = 0.25;
  const wheelZoomFactor = 1.1;
  let zoom = 1;
  let naturalWidth = 0;
  let naturalHeight = 0;
  let baseWidth = 0;
  let baseHeight = 0;
  let panState = null;
  const content = document.getElementById("diagramContent");
  const viewport = document.querySelector(".diagram-viewport");
  const toolbar = document.querySelector(".diagram-toolbar");
  const zoomLevel = document.getElementById("zoomLevel");
  const zoomOut = document.getElementById("zoomOut");
  const zoomReset = document.getElementById("zoomReset");
  const zoomIn = document.getElementById("zoomIn");
  const sequenceHeader = document.getElementById("sequenceHeader");
  const sequenceHeaderTrack = document.getElementById("sequenceHeaderTrack");
  let sequenceHeaderActors = [];

  function contentBox(svg) {
    try {
      const box = svg.getBBox();
      if (
        Number.isFinite(box.x) &&
        Number.isFinite(box.y) &&
        Number.isFinite(box.width) &&
        Number.isFinite(box.height) &&
        box.width > 0 &&
        box.height > 0
      ) {
        return box;
      }
    } catch (error) {
      return null;
    }
    return null;
  }

  function readSvgDimensions(svg) {
    const box = contentBox(svg);
    if (box) {
      svg.setAttribute(
        "viewBox",
        [box.x, box.y, box.width, box.height].join(" "),
      );
      svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
      return { width: box.width, height: box.height };
    }
    const viewBox = (svg.getAttribute("viewBox") || "")
      .trim()
      .split(/\\s+/)
      .map(Number);
    const width = viewBox.length === 4 && Number.isFinite(viewBox[2])
      ? viewBox[2]
      : Number.parseFloat(svg.getAttribute("width")) || svg.clientWidth || 800;
    const height = viewBox.length === 4 && Number.isFinite(viewBox[3])
      ? viewBox[3]
      : Number.parseFloat(svg.getAttribute("height")) || svg.clientHeight || 600;
    return { width, height };
  }

  function sequenceActorLabel(element) {
    const spans = Array.from(element.querySelectorAll("tspan"))
      .map((span) => String(span.textContent || "").trim())
      .filter(Boolean);
    const text = spans.length > 0
      ? spans.join(" ")
      : String(element.textContent || "").trim();
    return text.replace(/\\s+/g, " ");
  }

  function isSequenceDiagram(svg) {
    return Boolean(
      svg &&
      (
        svg.querySelector("text.actor") ||
        svg.querySelector(".actor-line")
      ),
    );
  }

  function sequenceActorCandidates(svg) {
    if (!isSequenceDiagram(svg)) {
      return [];
    }
    return Array.from(svg.querySelectorAll("text.actor, .actor text"))
      .map((element) => {
        const rect = element.getBoundingClientRect();
        const box = Array.from(element.parentElement?.children || [])
          .find((candidate) => candidate.matches?.("rect.actor")) || null;
        return {
          box,
          element,
          fontSize: Number.parseFloat(
            window.getComputedStyle(element).fontSize,
          ) || 16,
          label: sequenceActorLabel(element),
          rect,
        };
      })
      .filter((candidate) => (
        candidate.label &&
        candidate.rect.width > 0 &&
        candidate.rect.height > 0
      ));
  }

  function topSequenceActors(svg) {
    const candidates = sequenceActorCandidates(svg);
    if (candidates.length === 0) {
      return [];
    }
    const top = Math.min(...candidates.map((candidate) => candidate.rect.top));
    const maxHeight = Math.max(
      ...candidates.map((candidate) => candidate.rect.height),
    );
    const topRow = candidates
      .filter((candidate) => candidate.rect.top <= top + maxHeight * 1.6)
      .sort((left, right) => {
        const leftCenter = left.rect.left + left.rect.width / 2;
        const rightCenter = right.rect.left + right.rect.width / 2;
        return leftCenter - rightCenter;
      });
    const seen = new Set();
    return topRow.filter((candidate) => {
      const key = candidate.label.toLowerCase();
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
  }

  function clearSequenceHeader() {
    sequenceHeaderActors = [];
    sequenceHeaderTrack.replaceChildren();
    sequenceHeader.hidden = true;
  }

  function buildSequenceHeader() {
    const svg = content.querySelector("svg");
    const actors = topSequenceActors(svg);
    clearSequenceHeader();
    if (actors.length === 0) {
      return;
    }
    for (const actor of actors) {
      const label = document.createElement("div");
      label.className = "sequence-header-actor";
      label.textContent = actor.label;
      label.title = actor.label;
      sequenceHeaderTrack.append(label);
      sequenceHeaderActors.push({
        sourceBox: actor.box,
        sourceFontSize: actor.fontSize,
        source: actor.element,
        label,
      });
    }
    sequenceHeader.hidden = false;
    syncSequenceHeader();
  }

  function sequenceDiagramScale(svg) {
    const rect = svg?.getBoundingClientRect();
    return rect && rect.width > 0 && naturalWidth > 0
      ? rect.width / naturalWidth
      : zoom;
  }

  function sequenceHeaderMetrics(
    sourceWidth,
    sourceHeight,
    fontSize,
    scale,
  ) {
    const renderedWidth = Math.max(1, sourceWidth);
    const renderedHeight = Math.max(1, sourceHeight);
    return {
      borderRadius: 6 * scale,
      fontSize: Math.max(1, fontSize * scale),
      headerHeight: renderedHeight + 14 * scale,
      height: renderedHeight,
      padding: 10 * scale,
      top: 7 * scale,
      width: renderedWidth,
    };
  }

  function syncSequenceHeader() {
    if (sequenceHeader.hidden || sequenceHeaderActors.length === 0) {
      return;
    }
    const viewportRect = viewport.getBoundingClientRect();
    const svg = content.querySelector("svg");
    const scale = sequenceDiagramScale(svg);
    let headerHeight = 0;
    for (const actor of sequenceHeaderActors) {
      const textRect = actor.source.getBoundingClientRect();
      const boxRect = actor.sourceBox?.getBoundingClientRect();
      const sourceRect = boxRect && boxRect.width > 0 && boxRect.height > 0
        ? boxRect
        : textRect;
      if (sourceRect.width <= 0 || sourceRect.height <= 0) {
        actor.label.hidden = true;
        continue;
      }
      const centerX =
        sourceRect.left - viewportRect.left + sourceRect.width / 2;
      const metrics = sequenceHeaderMetrics(
        sourceRect.width,
        sourceRect.height,
        actor.sourceFontSize,
        scale,
      );
      headerHeight = Math.max(headerHeight, metrics.headerHeight);
      actor.label.hidden = false;
      actor.label.style.left = centerX + "px";
      actor.label.style.top = metrics.top + "px";
      actor.label.style.width = metrics.width + "px";
      actor.label.style.minWidth = metrics.width + "px";
      actor.label.style.maxWidth = metrics.width + "px";
      actor.label.style.height = metrics.height + "px";
      actor.label.style.borderRadius = metrics.borderRadius + "px";
      actor.label.style.fontSize = metrics.fontSize + "px";
      actor.label.style.padding = "0 " + metrics.padding + "px";
      actor.label.style.transform = "translateX(-50%)";
    }
    sequenceHeader.style.height = headerHeight + "px";
  }

  function updateBaseSize() {
    if (!naturalWidth || !naturalHeight) {
      return;
    }
    const viewportRect = viewport.getBoundingClientRect();
    const toolbarRect = toolbar.getBoundingClientRect();
    const viewportWidth = viewportRect.width || window.innerWidth || 980;
    const viewportHeight =
      viewportRect.height ||
      Math.max(220, (window.innerHeight || 720) - toolbarRect.height);
    const availableWidth = Math.max(320, viewportWidth - 48);
    const availableHeight = Math.max(220, viewportHeight - 48);
    const fitScale = Math.min(
      availableWidth / naturalWidth,
      availableHeight / naturalHeight,
    );
    const scale = Math.max(0.1, fitScale);
    baseWidth = naturalWidth * scale;
    baseHeight = naturalHeight * scale;
  }

  function applyZoom() {
    const svg = content.querySelector("svg");
    if (svg) {
      if (!baseWidth || !baseHeight) {
        const dimensions = readSvgDimensions(svg);
        naturalWidth = dimensions.width;
        naturalHeight = dimensions.height;
        updateBaseSize();
      }
      svg.style.width = (baseWidth * zoom) + "px";
      svg.style.height = (baseHeight * zoom) + "px";
    } else {
      content.style.fontSize = (16 * zoom) + "px";
    }
    zoomLevel.textContent = Math.round(zoom * 100) + "%";
    zoomOut.disabled = zoom <= minimumZoom;
    zoomIn.disabled = zoom >= maximumZoom;
    syncSequenceHeader();
  }

  function zoomTo(nextZoom, clientX = null, clientY = null) {
    const clampedZoom = Math.max(
      minimumZoom,
      Math.min(maximumZoom, nextZoom),
    );
    if (clampedZoom === zoom) {
      return;
    }
    let anchor = null;
    if (Number.isFinite(clientX) && Number.isFinite(clientY)) {
      const anchorElement = content.querySelector("svg") || content;
      const rect = anchorElement.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        anchor = {
          element: anchorElement,
          x: clientX,
          y: clientY,
          ratioX: (clientX - rect.left) / rect.width,
          ratioY: (clientY - rect.top) / rect.height,
        };
      }
    }
    zoom = clampedZoom;
    applyZoom();
    if (anchor) {
      const rect = anchor.element.getBoundingClientRect();
      viewport.scrollLeft += rect.left + rect.width * anchor.ratioX - anchor.x;
      viewport.scrollTop += rect.top + rect.height * anchor.ratioY - anchor.y;
    }
    syncSequenceHeader();
  }

  function changeZoom(delta) {
    zoomTo(zoom + delta);
  }

  function handleWheelZoom(event) {
    event.preventDefault();
    if (event.deltaY === 0) {
      return;
    }
    const factor = event.deltaY < 0
      ? wheelZoomFactor
      : 1 / wheelZoomFactor;
    zoomTo(zoom * factor, event.clientX, event.clientY);
  }

  function startPan(event) {
    if (event.button !== 1 || event.target.closest("a")) {
      return;
    }
    event.preventDefault();
    panState = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: viewport.scrollLeft,
      scrollTop: viewport.scrollTop,
    };
    viewport.classList.add("dragging");
    viewport.setPointerCapture(event.pointerId);
  }

  function updatePan(event) {
    if (!panState || event.pointerId !== panState.pointerId) {
      return;
    }
    event.preventDefault();
    viewport.scrollLeft = panState.scrollLeft - (event.clientX - panState.startX);
    viewport.scrollTop = panState.scrollTop - (event.clientY - panState.startY);
    syncSequenceHeader();
  }

  function finishPan(event) {
    if (!panState || event.pointerId !== panState.pointerId) {
      return;
    }
    panState = null;
    viewport.classList.remove("dragging");
    try {
      viewport.releasePointerCapture(event.pointerId);
    } catch (error) {
      return;
    }
  }

  function initializeDiagramPopup(title) {
    const svg = content.querySelector("svg");
    if (svg) {
      const dimensions = readSvgDimensions(svg);
      naturalWidth = dimensions.width;
      naturalHeight = dimensions.height;
      updateBaseSize();
    }
    applyZoom();
    buildSequenceHeader();
  }

  function fitAfterLayout() {
    initializeDiagramPopup("Mermaid diagram");
  }

  zoomOut.addEventListener("click", () => changeZoom(-zoomStep));
  zoomReset.addEventListener("click", () => {
    zoomTo(1);
  });
  zoomIn.addEventListener("click", () => changeZoom(zoomStep));
  viewport.addEventListener("wheel", handleWheelZoom, { passive: false });
  viewport.addEventListener("scroll", syncSequenceHeader);
  viewport.addEventListener("pointerdown", startPan);
  viewport.addEventListener("pointermove", updatePan);
  viewport.addEventListener("pointerup", finishPan);
  viewport.addEventListener("pointercancel", finishPan);
  viewport.addEventListener("auxclick", (event) => {
    if (event.button === 1) {
      event.preventDefault();
    }
  });
  window.addEventListener("resize", () => {
    updateBaseSize();
    applyZoom();
  });
  window.requestAnimationFrame(() => {
    fitAfterLayout();
    window.requestAnimationFrame(fitAfterLayout);
  });
  window.setTimeout(fitAfterLayout, 100);
})();
  <\/script>
</body>
</html>`;
  }

  window.ElectroBoyMermaid = {
    load: loadMermaid,
    open: openMermaidPopup,
    prepare: prepareMermaidPopouts,
    render: renderMermaidBlocks,
  };
})();
