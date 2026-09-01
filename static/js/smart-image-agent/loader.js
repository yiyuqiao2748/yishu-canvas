(function(){
    const params = new URLSearchParams(location.search);
    const legacy = params.get('image_agent') === 'legacy';
    const v3 = params.get('image_agent') === 'v3';
    const defaultBundleVersion = '2026.09.01.1';
    const source = legacy
        ? '/static/js/canvas-agent-loader.js?v=2026.08.25.1'
        : v3
            ? '/static/dist/js/smart-image-agent-v3.min.js?v=2026.08.27.1'
            : `/static/dist/js/smart-image-agent.min.js?v=${defaultBundleVersion}`;
    const script = document.createElement('script');
    script.src = source;
    script.defer = true;
    script.onload = () => {
        if(v3 && window.SmartImageAgentV3App?.init) window.SmartImageAgentV3App.init();
        if(!legacy && !v3 && window.SmartImageAgentApp?.init) window.SmartImageAgentApp.init();
    };
    script.onerror = () => console.error('[smart-image-agent] failed to load', source);
    document.head.appendChild(script);
})();
