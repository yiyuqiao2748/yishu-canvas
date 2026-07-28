(function(){
    const WORKBENCH_DRAFTS_KEY = 'workbenchCanvasDrafts:v1';
    const WORKBENCH_PENDING_DRAFT_KEY = 'workbenchCanvasDraftPending:v1';
    const PROMPT_PLACEHOLDERS = [
        '例如：为城市展厅设计一张建筑概念图，玻璃幕墙、金红色灯带、入口有水景和人流，高级夜景摄影质感。',
        '例如：设计一家现代中餐厅室内效果图，暖金灯光、深色木饰面、开放式吧台、圆桌包间、空间层次丰富。',
        '例如：为商业综合体中庭做节日美陈方案，挑空空间、红金装置、环形动线、品牌橱窗和柔和人群氛围。',
        '例如：设计一家高端咖啡餐厅门头，黑金招牌、落地窗、室外座位、暖色灯光、适合夜间社交打卡。',
    ];
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

    function applyWorkbenchTheme(theme) {
        const isLight = theme === 'light';
        document.documentElement.classList.toggle('theme-light', isLight);
        document.body.classList.toggle('theme-light', isLight);
        document.documentElement.classList.toggle('theme-dark', !isLight);
        document.body.classList.toggle('theme-dark', !isLight);
        try {
            localStorage.setItem('workbench_theme', isLight ? 'light' : 'dark');
        } catch(e) {}
    }

    function toggleStudioTheme() {
        if(window.parent && window.parent !== window) {
            window.parent.postMessage({ type: 'studio-toggle-theme' }, window.location.origin);
            return;
        }
        const current = document.body.classList.contains('theme-light') ? 'light' : 'dark';
        applyWorkbenchTheme(current === 'light' ? 'dark' : 'light');
    }

    function setToolsOpen(open) {
        const rail = document.querySelector('.preview-quick-rail');
        const popover = document.querySelector('.rail-tool-popover');
        const toggle = document.querySelector('[data-tools-toggle]');
        if(!rail || !popover || !toggle) return;
        rail.classList.toggle('is-tools-open', open);
        popover.hidden = !open;
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    function setStatus(text) {
        const status = document.getElementById('composerStatus');
        if(status) status.textContent = text;
    }

    function setFeedbackStatus(text) {
        const status = document.getElementById('feedbackStatus');
        if(status) status.textContent = text;
    }

    async function fetchJson(url, options = {}) {
        const response = await fetch(url, {
            credentials: 'same-origin',
            ...options,
            headers: {
                ...(options.headers || {}),
            },
        });
        if(!response.ok) throw new Error(`request failed: ${response.status}`);
        return await response.json();
    }

    function shortUserName(user) {
        const value = user?.display_name || user?.username || user?.email || '';
        if(!value) return '未登录';
        const text = String(value).trim();
        if(text.includes('@')) return text.split('@')[0] || text;
        return text;
    }

    async function loadCurrentUser() {
        const label = document.getElementById('workbenchUserLabel');
        const points = document.getElementById('workbenchInspirationPoints');
        if(!label) return;
        try {
            const data = await fetchJson('/api/team-cloud/me');
            label.textContent = shortUserName(data.user);
            if(points) points.textContent = (data.user && Array.isArray(data.teams) && data.teams.length) ? '无限制' : '0';
            window.__workbenchCurrentUser = data.user || null;
        } catch(e) {
            label.textContent = '未登录';
            if(points) points.textContent = '0';
            window.__workbenchCurrentUser = null;
        }
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

    function startPromptTyping() {
        const input = document.getElementById('promptInput');
        if(!input || !PROMPT_PLACEHOLDERS.length) return;
        let promptIndex = 0;
        let charIndex = 0;

        function tick() {
            if(input.value) {
                window.setTimeout(tick, 900);
                return;
            }
            const text = PROMPT_PLACEHOLDERS[promptIndex];
            input.placeholder = text.slice(0, charIndex);
            if(charIndex < text.length) {
                charIndex += 1;
                window.setTimeout(tick, 34);
                return;
            }
            window.setTimeout(() => {
                promptIndex = (promptIndex + 1) % PROMPT_PLACEHOLDERS.length;
                charIndex = 0;
                tick();
            }, 1800);
        }

        tick();
    }

    function normalizeImageUrl(url) {
        const text = String(url || '').trim();
        if(!text) return '';
        if(text.startsWith('data:') || text.startsWith('blob:') || /^https?:\/\//i.test(text)) return text;
        if(text.startsWith('/api/team-cloud/')) return text;
        if(text.startsWith('/assets/') || text.startsWith('/output/')) {
            return `/api/media-preview?w=640&url=${encodeURIComponent(text)}`;
        }
        return text.startsWith('/') ? text : '';
    }

    function collectImageUrls(value, out = []) {
        if(!value || out.length >= 8) return out;
        if(typeof value === 'string') {
            const url = normalizeImageUrl(value);
            if(url && /\.(png|jpe?g|webp|gif)(\?|#|$)/i.test(url)) out.push(url);
            if(url && url.startsWith('/api/team-cloud/')) out.push(url);
            return out;
        }
        if(Array.isArray(value)) {
            value.forEach(item => collectImageUrls(item, out));
            return out;
        }
        if(typeof value === 'object') {
            ['thumbnail_url', 'thumbnail', 'preview', 'preview_url', 'image', 'imageUrl', 'url', 'src'].forEach(key => {
                if(value[key]) collectImageUrls(value[key], out);
            });
            if(Array.isArray(value.nodes)) collectImageUrls(value.nodes, out);
            if(Array.isArray(value.items)) collectImageUrls(value.items, out);
            if(Array.isArray(value.categories)) collectImageUrls(value.categories, out);
        }
        return out;
    }

    function applyCardBackground(card, url) {
        if(!card || !url) return false;
        card.style.setProperty('--library-card-bg', `url("${String(url).replace(/"/g, '%22')}")`);
        card.classList.add('has-bg');
        return true;
    }

    async function loadRecentCanvasBackground() {
        const card = document.querySelector('[data-recent-canvas-card]');
        if(!card) return;
        try {
            const data = await fetchJson('/api/canvases');
            const canvases = (data.canvases || [])
                .slice()
                .sort((a, b) => Number(b.updated_at || b.created_at || 0) - Number(a.updated_at || a.created_at || 0))
                .slice(0, 6);
            for(const canvas of canvases) {
                try {
                    const detail = await fetchJson(`/api/canvases/${encodeURIComponent(canvas.id)}`);
                    const urls = collectImageUrls(detail.canvas || detail);
                    if(applyCardBackground(card, urls[0])) return;
                } catch(e) {}
            }
        } catch(e) {}
    }

    function firstAssetImageFromLibrary(library) {
        const urls = collectImageUrls(library);
        return urls[0] || '';
    }

    async function loadAssetBackground() {
        const card = document.querySelector('[data-frequent-assets-card]');
        if(!card) return;
        try {
            const localData = await fetchJson('/api/local-assets');
            const localUrl = firstAssetImageFromLibrary(localData);
            if(applyCardBackground(card, localUrl)) return;
        } catch(e) {}
        try {
            const assetData = await fetchJson('/api/asset-library');
            applyCardBackground(card, firstAssetImageFromLibrary(assetData.library || assetData));
        } catch(e) {}
    }

    function openFeedbackModal() {
        const modal = document.getElementById('feedbackModal');
        const input = document.getElementById('feedbackInput');
        if(!modal) return;
        modal.hidden = false;
        setFeedbackStatus('反馈会保存到后台，后续可做管理页查看。');
        window.setTimeout(() => input?.focus(), 30);
    }

    function closeFeedbackModal() {
        const modal = document.getElementById('feedbackModal');
        if(modal) modal.hidden = true;
    }

    async function submitFeedback() {
        const input = document.getElementById('feedbackInput');
        const message = String(input?.value || '').trim();
        if(!message) {
            setFeedbackStatus('请先写一点反馈内容。');
            input?.focus();
            return;
        }
        setFeedbackStatus('正在发送...');
        try {
            await fetchJson('/api/workbench/feedback', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    message,
                    page: location.href,
                    user: window.__workbenchCurrentUser || null,
                    user_agent: navigator.userAgent,
                    viewport: {
                        width: window.innerWidth,
                        height: window.innerHeight,
                        devicePixelRatio: window.devicePixelRatio || 1,
                    },
                }),
            });
            if(input) input.value = '';
            setFeedbackStatus('已发送，后台可查看。');
            window.setTimeout(closeFeedbackModal, 900);
        } catch(e) {
            setFeedbackStatus('当前环境不能提交；部署到后端后会保存到后台。');
        }
    }

    function init() {
        if(!(window.parent && window.parent !== window)) {
            let savedTheme = 'dark';
            try {
                savedTheme = localStorage.getItem('workbench_theme') === 'light' ? 'light' : 'dark';
            } catch(e) {}
            applyWorkbenchTheme(savedTheme);
        }

        document.querySelectorAll('[data-open-page]').forEach(button => {
            button.addEventListener('click', () => {
                const params = button.dataset.visibilityTarget
                    ? { cloud: '1', visibility: button.dataset.visibilityTarget }
                    : null;
                setToolsOpen(false);
                openPage(button.dataset.openPage, params);
            });
        });

        document.querySelector('[data-tools-toggle]')?.addEventListener('click', event => {
            event.stopPropagation();
            const rail = document.querySelector('.preview-quick-rail');
            setToolsOpen(!rail?.classList.contains('is-tools-open'));
        });

        document.addEventListener('click', event => {
            if(!event.target.closest?.('.preview-quick-rail')) setToolsOpen(false);
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

        document.querySelectorAll('[data-workbench-generate]').forEach(button => {
            button.addEventListener('click', startWorkbenchGeneration);
        });
        document.querySelector('[data-feedback-open]')?.addEventListener('click', openFeedbackModal);
        document.querySelector('[data-theme-toggle]')?.addEventListener('click', toggleStudioTheme);
        document.querySelectorAll('[data-feedback-close]').forEach(button => {
            button.addEventListener('click', closeFeedbackModal);
        });
        document.querySelector('[data-feedback-submit]')?.addEventListener('click', submitFeedback);

        if(window.lucide) window.lucide.createIcons();
        loadCurrentUser();
        startPromptTyping();
        loadRecentCanvasBackground();
        loadAssetBackground();
    }

    if(document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
