(function(){
    const WORKBENCH_DRAFTS_KEY = 'workbenchCanvasDrafts:v1';
    const WORKBENCH_PENDING_DRAFT_KEY = 'workbenchCanvasDraftPending:v1';
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

    function pageUrl(page, params = null) {
        const fallback = {
            workbench: '/static/workbench.html',
            canvas: '/static/canvas-list.html',
            'team-cloud': '/static/team-cloud.html',
            'asset-manager': '/static/asset-manager.html',
            'gpt-chat': '/static/gpt-chat.html',
        };
        const url = fallback[page] || `/static/${page}.html`;
        if(!params) return url;
        const query = new URLSearchParams(params);
        return `${url}?${query.toString()}`;
    }

    function openPage(page, params = null) {
        if(!PAGE_IDS.has(page)) return;
        if(window.parent && window.parent !== window) {
            window.parent.postMessage({ type: 'studio-open-page', page, params }, window.location.origin);
            return;
        }
        window.location.href = pageUrl(page, params);
    }

    function setStatus(text) {
        const status = document.getElementById('composerStatus');
        if(status) status.textContent = text;
    }

    function selectedValue(id) {
        const el = document.getElementById(id);
        return String(el?.value || '').trim();
    }

    function draftTitleFromPrompt(prompt) {
        const firstLine = String(prompt || '').trim().split(/\r?\n/)[0] || '';
        return (firstLine || '视觉设计').slice(0, 42);
    }

    function loadWorkbenchDrafts() {
        try {
            const data = JSON.parse(localStorage.getItem(WORKBENCH_DRAFTS_KEY) || '{}');
            return data && typeof data === 'object' ? data : {};
        } catch(e) {
            return {};
        }
    }

    function saveWorkbenchDraft(draft) {
        const drafts = loadWorkbenchDrafts();
        drafts[draft.id] = draft;
        localStorage.setItem(WORKBENCH_DRAFTS_KEY, JSON.stringify(drafts));
        localStorage.setItem(WORKBENCH_PENDING_DRAFT_KEY, draft.id);
    }

    function createWorkbenchDraft() {
        const input = document.getElementById('promptInput');
        const prompt = String(input?.value || '').trim();
        if(!prompt) {
            setStatus('请先输入设计需求');
            input?.focus();
            return null;
        }
        return {
            id: `wb_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
            title: draftTitleFromPrompt(prompt),
            prompt: prompt.slice(0, 20000),
            size: selectedValue('sizeSelect'),
            resolution: selectedValue('resolutionSelect'),
            model: selectedValue('modelSelect'),
            createdAt: Date.now()
        };
    }

    function openCanvasDraft(draft) {
        saveWorkbenchDraft(draft);
        if(window.parent && window.parent !== window) {
            openPage('canvas');
            return;
        }
        window.location.href = pageUrl('canvas', { workbenchDraft: draft.id, autoCreate: '1' });
    }

    function startWorkbenchGeneration() {
        const draft = createWorkbenchDraft();
        if(!draft) return;
        setStatus('正在创建画布...');
        openCanvasDraft(draft);
    }

    function init() {
        document.querySelectorAll('[data-open-page]').forEach(button => {
            button.addEventListener('click', () => {
                const params = button.dataset.visibilityTarget
                    ? { cloud: '1', visibility: button.dataset.visibilityTarget }
                    : null;
                openPage(button.dataset.openPage, params);
            });
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

        document.querySelector('[data-workbench-generate]')?.addEventListener('click', startWorkbenchGeneration);

        if(window.lucide) window.lucide.createIcons();
    }

    if(document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
