(function(){
    const PAGE_IDS = new Set([
        'workbench',
        'zimage',
        'enhance',
        'klein',
        'angle',
        'online',
        'gpt-chat',
        'canvas',
        'team-cloud',
        'asset-manager',
        'api-settings',
        'comfyui-settings',
    ]);

    function openPage(page) {
        if(!PAGE_IDS.has(page)) return;
        if(window.parent && window.parent !== window) {
            window.parent.postMessage({ type: 'studio-open-page', page }, window.location.origin);
            return;
        }
        const fallback = {
            workbench: '/static/workbench.html',
            canvas: '/static/canvas-list.html',
            'team-cloud': '/static/team-cloud.html',
            'asset-manager': '/static/asset-manager.html',
            'gpt-chat': '/static/gpt-chat.html',
        };
        window.location.href = fallback[page] || `/static/${page}.html`;
    }

    function setStatus(text) {
        const status = document.getElementById('composerStatus');
        if(status) status.textContent = text;
    }

    function init() {
        document.querySelectorAll('[data-open-page]').forEach(button => {
            button.addEventListener('click', () => openPage(button.dataset.openPage));
        });

        document.querySelector('[data-clear-prompt]')?.addEventListener('click', () => {
            const input = document.getElementById('promptInput');
            if(input) input.value = '';
            setStatus('准备就绪');
        });

        document.querySelector('[data-upload-placeholder]')?.addEventListener('click', () => {
            setStatus('参考图请先在素材库上传');
            openPage('asset-manager');
        });

        document.querySelector('[data-url-placeholder]')?.addEventListener('click', () => {
            setStatus('URL 素材请先进入素材库登记');
            openPage('asset-manager');
        });

        if(window.lucide) window.lucide.createIcons();
    }

    if(document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
