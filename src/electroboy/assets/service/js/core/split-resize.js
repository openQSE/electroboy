(function (global) {
  "use strict";

  const DEFAULT_DIVIDER_SIZE = 7;
  const DEFAULT_MIN_SEGMENT_SIZE = 88;
  const MIN_RATIO = 0.12;
  const MAX_RATIO = 0.88;

  function clamp(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, value));
  }

  function splitIsSameDirection(node, direction) {
    return Boolean(node && node.type === "split" && node.direction === direction);
  }

  function pathToNode(node, targetId, path = []) {
    if (!node) {
      return null;
    }
    const nextPath = [...path, node];
    if (node.id === targetId) {
      return nextPath;
    }
    if (node.type !== "split") {
      return null;
    }
    return pathToNode(node.first, targetId, nextPath) ||
      pathToNode(node.second, targetId, nextPath);
  }

  function resizeRoot(layout, targetNode) {
    const path = pathToNode(layout, targetNode.id);
    if (!path) {
      return targetNode;
    }
    let root = targetNode;
    const direction = targetNode.direction;
    for (let index = path.length - 2; index >= 0; index -= 1) {
      const parent = path[index];
      if (!splitIsSameDirection(parent, direction)) {
        break;
      }
      root = parent;
    }
    return root;
  }

  function segmentCount(node, direction) {
    if (splitIsSameDirection(node, direction)) {
      return segmentCount(node.first, direction) +
        segmentCount(node.second, direction);
    }
    return 1;
  }

  function boundaryIndex(node, targetNode, direction, offset = 0) {
    if (!splitIsSameDirection(node, direction)) {
      return null;
    }
    if (node.id === targetNode.id) {
      return offset + segmentCount(node.first, direction);
    }
    const firstBoundary = boundaryIndex(node.first, targetNode, direction, offset);
    if (firstBoundary !== null) {
      return firstBoundary;
    }
    return boundaryIndex(
      node.second,
      targetNode,
      direction,
      offset + segmentCount(node.first, direction),
    );
  }

  function collectSegments(node, direction, outerSize, options, result = []) {
    if (splitIsSameDirection(node, direction)) {
      const available = Math.max(0, outerSize - options.dividerSize);
      const ratio = clamp(Number(node.ratio) || 0.5, MIN_RATIO, MAX_RATIO);
      collectSegments(node.first, direction, available * ratio, options, result);
      collectSegments(
        node.second,
        direction,
        available * (1 - ratio),
        options,
        result,
      );
      return result;
    }
    result.push({ node, size: Math.max(0, outerSize) });
    return result;
  }

  function targetOuterSize(node, direction, targetSizes, options) {
    if (splitIsSameDirection(node, direction)) {
      return targetOuterSize(node.first, direction, targetSizes, options) +
        options.dividerSize +
        targetOuterSize(node.second, direction, targetSizes, options);
    }
    return Number(targetSizes.get(node.id) || 0);
  }

  function applyTargetSizes(node, direction, targetSizes, options) {
    if (!splitIsSameDirection(node, direction)) {
      return;
    }
    const firstSize = targetOuterSize(node.first, direction, targetSizes, options);
    const secondSize = targetOuterSize(node.second, direction, targetSizes, options);
    const total = firstSize + secondSize;
    if (total > 0) {
      node.ratio = clamp(firstSize / total, MIN_RATIO, MAX_RATIO);
    }
    applyTargetSizes(node.first, direction, targetSizes, options);
    applyTargetSizes(node.second, direction, targetSizes, options);
  }

  function applyTemplates(node, direction, options) {
    if (!splitIsSameDirection(node, direction)) {
      return;
    }
    const element = typeof options.elementForNode === "function"
      ? options.elementForNode(node)
      : null;
    if (element && typeof options.applyTemplate === "function") {
      options.applyTemplate(element, node);
    }
    applyTemplates(node.first, direction, options);
    applyTemplates(node.second, direction, options);
  }

  function createResizeController(options = {}) {
    const layout = options.layout;
    const targetNode = options.node;
    if (!layout || !splitIsSameDirection(targetNode, targetNode?.direction)) {
      return null;
    }
    const direction = targetNode.direction;
    const rootNode = resizeRoot(layout, targetNode);
    const rootElement = typeof options.elementForNode === "function"
      ? options.elementForNode(rootNode)
      : null;
    const measuredElement = rootElement || options.splitElement;
    if (!measuredElement || typeof measuredElement.getBoundingClientRect !== "function") {
      return null;
    }
    const rect = measuredElement.getBoundingClientRect();
    const outerSize = direction === "column" ? rect.height : rect.width;
    if (outerSize <= 0) {
      return null;
    }
    const resizeBoundary = boundaryIndex(rootNode, targetNode, direction);
    const config = {
      dividerSize: Number(options.dividerSize || DEFAULT_DIVIDER_SIZE),
      minSegmentSize: Number(options.minSegmentSize || DEFAULT_MIN_SEGMENT_SIZE),
    };
    const segments = collectSegments(rootNode, direction, outerSize, config);
    if (
      resizeBoundary === null ||
      resizeBoundary <= 0 ||
      resizeBoundary >= segments.length
    ) {
      return null;
    }
    const beforeIndex = resizeBoundary - 1;
    const afterIndex = resizeBoundary;
    const startSizes = segments.map((segment) => segment.size);
    const startPointer = direction === "column"
      ? Number(options.startY)
      : Number(options.startX);

    return {
      update(event) {
        const pointer = direction === "column" ? event.clientY : event.clientX;
        const pairTotal = startSizes[beforeIndex] + startSizes[afterIndex];
        if (pairTotal <= 0) {
          return false;
        }
        const minimum = Math.min(config.minSegmentSize, pairTotal / 2);
        const delta = pointer - startPointer;
        const nextBefore = clamp(
          startSizes[beforeIndex] + delta,
          minimum,
          pairTotal - minimum,
        );
        const targetSizes = new Map();
        for (let index = 0; index < segments.length; index += 1) {
          targetSizes.set(segments[index].node.id, startSizes[index]);
        }
        targetSizes.set(segments[beforeIndex].node.id, nextBefore);
        targetSizes.set(segments[afterIndex].node.id, pairTotal - nextBefore);
        applyTargetSizes(rootNode, direction, targetSizes, config);
        applyTemplates(rootNode, direction, options);
        if (typeof options.afterUpdate === "function") {
          options.afterUpdate();
        }
        return true;
      },
    };
  }

  global.ElectroBoySplitResize = { create: createResizeController };
})(window);
