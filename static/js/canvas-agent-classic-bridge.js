/* canvas-agent-classic-bridge.js
   Thin adapter for the classic canvas. It only calls existing canvas actions. */
(function() {
    'use strict';

    function centerPoint(dx, dy) {
        if (typeof window.defaultPoint === 'function') {
            return window.defaultPoint(dx || 0, dy || 0);
        }
        return { x: dx || 0, y: dy || 0 };
    }

    if (typeof window.viewportCenter !== 'function') {
        window.viewportCenter = function() {
            return centerPoint(0, 0);
        };
    }

    if (typeof window.createPromptNode !== 'function') {
        window.createPromptNode = function(x, y, options) {
            if (typeof window.addPromptNode !== 'function') return null;
            var text = options && options.text ? options.text : '';
            return window.addPromptNode({ x: Number(x) || 0, y: Number(y) || 0 }, text);
        };
    }

    if (typeof window.createImageNodeAt !== 'function') {
        window.createImageNodeAt = function(point) {
            if (typeof window.addImageNode !== 'function') return null;
            return window.addImageNode(point || centerPoint(-120, 0));
        };
    }

    if (typeof window.createLoopNode !== 'function') {
        window.createLoopNode = function(x, y) {
            if (typeof window.addLoopNode !== 'function') return null;
            return window.addLoopNode({ x: Number(x) || 0, y: Number(y) || 0 });
        };
    }
})();
