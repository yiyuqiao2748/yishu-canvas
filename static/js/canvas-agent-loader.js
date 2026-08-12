(function() {
    'use strict';

    var loadPromise = null;
    var moduleUrls = [
        '/static/js/canvas-agent-classic-bridge.js',
        '/static/js/canvas-agent-memory.js',
        '/static/js/canvas-agent-executor.js',
        '/static/js/canvas-agent-learning.js',
        '/static/js/canvas-agent-panel.js'
    ];

    function loadScript(url) {
        return new Promise(function(resolve, reject) {
            var script = document.createElement('script');
            script.src = url;
            script.async = false;
            script.onload = resolve;
            script.onerror = function() { reject(new Error('Failed to load ' + url)); };
            document.head.appendChild(script);
        });
    }

    function loadAgentModules() {
        if (!loadPromise) {
            loadPromise = moduleUrls.reduce(function(promise, url) {
                return promise.then(function() { return loadScript(url); });
            }, Promise.resolve()).catch(function(error) {
                loadPromise = null;
                throw error;
            });
        }
        return loadPromise;
    }

    function openAgent(event) {
        if (event) event.preventDefault();
        var toggle = document.getElementById('agentToggle');
        if (toggle) toggle.disabled = true;
        loadAgentModules().then(function() {
            if (toggle) toggle.disabled = false;
            toggle?.click();
        }).catch(function(error) {
            if (toggle) toggle.disabled = false;
            console.error('[AgentLoader]', error);
        });
    }

    document.getElementById('agentToggle')?.addEventListener('click', function onFirstClick(event) {
        if (window.refreshAgentSkillsPanel) return;
        event.stopImmediatePropagation();
        openAgent(event);
    }, true);

    window.toggleAgentPanel = function() {
        if (window.refreshAgentSkillsPanel) {
            document.getElementById('agentToggle')?.click();
            return;
        }
        openAgent();
    };
    window.loadAgentModules = loadAgentModules;
})();
