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

  function nodeIsVisible(node, options) {
    if (!node || typeof options.nodeVisible !== "function") {
      return true;
    }
    return options.nodeVisible(node) !== false;
  }

  function branchIsVisible(node, options) {
    if (!nodeIsVisible(node, options)) {
      return false;
    }
    if (!node || node.type !== "split") {
      return true;
    }
    return branchIsVisible(node.first, options) ||
      branchIsVisible(node.second, options);
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

  function resizeRoot(layout, targetNode, options) {
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
      if (
        !branchIsVisible(parent.first, options) ||
        !branchIsVisible(parent.second, options)
      ) {
        break;
      }
      root = parent;
    }
    return root;
  }

  function segmentCount(node, direction, options) {
    if (!branchIsVisible(node, options)) {
      return 0;
    }
    if (splitIsSameDirection(node, direction)) {
      return segmentCount(node.first, direction, options) +
        segmentCount(node.second, direction, options);
    }
    return 1;
  }

  function boundaryIndex(node, targetNode, direction, options, offset = 0) {
    if (!splitIsSameDirection(node, direction) || !branchIsVisible(node, options)) {
      return null;
    }
    if (node.id === targetNode.id) {
      return offset + segmentCount(node.first, direction, options);
    }
    const firstBoundary = boundaryIndex(
      node.first,
      targetNode,
      direction,
      options,
      offset,
    );
    if (firstBoundary !== null) {
      return firstBoundary;
    }
    return boundaryIndex(
      node.second,
      targetNode,
      direction,
      options,
      offset + segmentCount(node.first, direction, options),
    );
  }

  function collectSegments(node, direction, outerSize, options, result = []) {
    if (!branchIsVisible(node, options)) {
      return result;
    }
    if (splitIsSameDirection(node, direction)) {
      const firstVisible = branchIsVisible(node.first, options);
      const secondVisible = branchIsVisible(node.second, options);
      if (!firstVisible || !secondVisible) {
        collectSegments(
          firstVisible ? node.first : node.second,
          direction,
          outerSize,
          options,
          result,
        );
        return result;
      }
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
    if (!branchIsVisible(node, options)) {
      return 0;
    }
    if (splitIsSameDirection(node, direction)) {
      const firstVisible = branchIsVisible(node.first, options);
      const secondVisible = branchIsVisible(node.second, options);
      if (!firstVisible || !secondVisible) {
        return targetOuterSize(
          firstVisible ? node.first : node.second,
          direction,
          targetSizes,
          options,
        );
      }
      return targetOuterSize(node.first, direction, targetSizes, options) +
        options.dividerSize +
        targetOuterSize(node.second, direction, targetSizes, options);
    }
    return Number(targetSizes.get(node.id) || 0);
  }

  function applyTargetSizes(node, direction, targetSizes, options) {
    if (!splitIsSameDirection(node, direction) || !branchIsVisible(node, options)) {
      return;
    }
    const firstVisible = branchIsVisible(node.first, options);
    const secondVisible = branchIsVisible(node.second, options);
    if (!firstVisible || !secondVisible) {
      applyTargetSizes(
        firstVisible ? node.first : node.second,
        direction,
        targetSizes,
        options,
      );
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
    if (!splitIsSameDirection(node, direction) || !branchIsVisible(node, options)) {
      return;
    }
    const firstVisible = branchIsVisible(node.first, options);
    const secondVisible = branchIsVisible(node.second, options);
    const element = typeof options.elementForNode === "function"
      ? options.elementForNode(node)
      : null;
    if (
      firstVisible &&
      secondVisible &&
      element &&
      typeof options.applyTemplate === "function"
    ) {
      options.applyTemplate(element, node);
    }
    if (firstVisible) {
      applyTemplates(node.first, direction, options);
    }
    if (secondVisible) {
      applyTemplates(node.second, direction, options);
    }
  }

  function createResizeController(options = {}) {
    const layout = options.layout;
    const targetNode = options.node;
    if (!layout || !splitIsSameDirection(targetNode, targetNode?.direction)) {
      return null;
    }
    const direction = targetNode.direction;
    const rootNode = resizeRoot(layout, targetNode, options);
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
    const config = {
      dividerSize: Number(options.dividerSize || DEFAULT_DIVIDER_SIZE),
      minSegmentSize: Number(options.minSegmentSize || DEFAULT_MIN_SEGMENT_SIZE),
      nodeVisible: options.nodeVisible,
    };
    const resizeBoundary = boundaryIndex(rootNode, targetNode, direction, config);
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
