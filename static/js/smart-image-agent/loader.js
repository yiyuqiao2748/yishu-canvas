(function(){
    const params = new URLSearchParams(location.search);
    const legacy = params.get('image_agent') === 'legacy';
    const source = legacy
        ? '/static/js/canvas-agent-loader.js?v=2026.08.24.3'
        : '/static/dist/js/smart-image-agent.min.js?v=2026.08.24.3';
    const script = document.createElement('script');
    script.src = source;
    script.defer = true;
    script.onload = () => {
        if(!legacy && window.SmartImageAgentApp?.init) window.SmartImageAgentApp.init();
    };
    script.onerror = () => console.error('[smart-image-agent] failed to load', source);
    document.head.appendChild(script);
})();
