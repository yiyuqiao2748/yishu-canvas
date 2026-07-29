(function(){
    const WORKBENCH_DRAFTS_KEY = 'workbenchCanvasDrafts:v1';
    const WORKBENCH_PENDING_DRAFT_KEY = 'workbenchCanvasDraftPending:v1';
    const WORKBENCH_REFERENCES_KEY = 'workbenchReferences:v1';
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
            const next = isLight ? 'light' : 'dark';
            localStorage.setItem('studio_theme', next);
            localStorage.setItem('canvas_theme', next);
            localStorage.setItem('workbench_theme', next);
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

    function escapeHtml(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, s => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;',
        }[s]));
    }

    function escapeAttr(value) {
        return escapeHtml(value);
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

    function setUrlStatus(text) {
        const status = document.getElementById('urlStatus');
        if(status) status.textContent = text;
    }

    function openUrlModal() {
        const modal = document.getElementById('urlModal');
        const input = document.getElementById('urlInput');
        if(!modal) return;
        window.__urlReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        modal.hidden = false;
        setUrlStatus('保存后可作为本次创作参考。');
        const focusInput = () => {
            input?.focus?.({ preventScroll: true });
            input?.select?.();
        };
        window.requestAnimationFrame(focusInput);
        window.setTimeout(focusInput, 80);
    }

    function closeUrlModal() {
        const modal = document.getElementById('urlModal');
        if(modal) modal.hidden = true;
        window.__urlReturnFocus?.focus?.();
        window.__urlReturnFocus = null;
    }

    function isLikelyImageUrl(url) {
        return /\.(png|jpe?g|webp|gif)(\?|#|$)/i.test(String(url || ''));
    }

    function saveUrlReference() {
        const input = document.getElementById('urlInput');
        const raw = String(input?.value || '').trim();
        if(!raw) {
            setUrlStatus('请先输入一个链接。');
            input?.focus();
            return;
        }
        let parsed;
        try {
            parsed = new URL(raw, location.origin);
        } catch(e) {
            setUrlStatus('链接格式不正确。');
            input?.focus();
            return;
        }
        const url = parsed.href;
        const refs = loadReferences();
        refs.unshift({
            url,
            original_url: url,
            name: parsed.hostname || 'url-reference',
            kind: isLikelyImageUrl(url) ? 'image' : 'url',
            addedAt: Date.now(),
        });
        saveReferences(refs);
        if(input) input.value = '';
        setStatus(isLikelyImageUrl(url) ? '图片 URL 已加入参考图' : '网页链接已保存');
        closeUrlModal();
    }

    async function uploadReferenceFiles(event) {
        const input = event.currentTarget;
        const files = Array.from(input?.files || []);
        if(!files.length) return;
        const form = new FormData();
        files.forEach(file => form.append('files', file));
        setStatus('正在上传参考图...');
        try {
            const data = await fetchJson('/api/ai/upload', {
                method: 'POST',
                body: form,
            });
            const uploaded = (data.files || []).filter(item => item?.url);
            if(!uploaded.length) throw new Error('没有可用的上传结果');
            saveReferences([...uploaded.map(item => ({
                url: item.url,
                name: item.name || 'reference',
                kind: item.kind || 'image',
                mime: item.mime || '',
                addedAt: Date.now(),
            })), ...loadReferences()]);
            setStatus(`已上传 ${uploaded.length} 张参考图`);
        } catch(e) {
            setStatus(e.message || '参考图上传失败');
        } finally {
            if(input) input.value = '';
        }
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

    function loadReferences() {
        try {
            const data = JSON.parse(localStorage.getItem(WORKBENCH_REFERENCES_KEY) || '[]');
            return Array.isArray(data) ? data.filter(item => item?.url) : [];
        } catch(e) {
            return [];
        }
    }

    function saveReferences(items) {
        const refs = (items || []).filter(item => item?.url).slice(0, 12);
        try { localStorage.setItem(WORKBENCH_REFERENCES_KEY, JSON.stringify(refs)); } catch(e) {}
        updateReferenceCount(refs);
        return refs;
    }

    function updateReferenceCount(items = loadReferences()) {
        const count = items.filter(item => (item.kind || 'image') === 'image').length;
        const label = document.querySelector('[data-reference-count]');
        if(label) label.textContent = `${count}张参考图`;
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
        const params = { workbenchDraft: draft.id, autoCreate: '1' };
        if(window.parent && window.parent !== window) {
            openPage('canvas', params);
            return;
        }
        window.location.href = pageUrl('canvas', params);
    }

    function startWorkbenchGeneration() {
        const draft = createWorkbenchDraft();
        if(!draft) return;
        generateWorkbenchImage(draft);
    }

    function resolutionScale() {
        const value = selectedValue('resolutionSelect').toUpperCase();
        if(value === '4K') return 2048;
        if(value === '1K') return 1024;
        return 1536;
    }

    function requestSizeFromSelections() {
        const base = resolutionScale();
        const ratio = selectedValue('sizeSelect');
        if(ratio === '16:9') return `${base}x${Math.round(base * 9 / 16)}`;
        if(ratio === '9:16') return `${Math.round(base * 9 / 16)}x${base}`;
        return `${base}x${base}`;
    }

    function selectedImageModel() {
        const value = selectedValue('modelSelect');
        return value && !value.includes('默认') ? value : '';
    }

    function imageReferencesForRequest() {
        return loadReferences()
            .filter(item => (item.kind || 'image') === 'image')
            .slice(0, 8)
            .map(item => ({
                url: item.url,
                name: item.name || 'reference',
                kind: 'image',
                original_url: item.original_url || item.url,
            }));
    }

    function renderWorkbenchResult(result, draft) {
        const section = document.getElementById('workbenchResult');
        const grid = document.getElementById('workbenchResultGrid');
        const images = (result?.images || []).filter(Boolean);
        if(!section || !grid || !images.length) return;
        grid.innerHTML = images.map((url, index) => `
            <a class="result-card" href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer" aria-label="查看生成图 ${index + 1}">
                <img src="${escapeAttr(url)}" alt="">
            </a>
        `).join('');
        section.hidden = false;
        window.__lastWorkbenchDraft = {
            ...draft,
            generatedImages: images,
            generatedAt: Date.now(),
        };
        const recentCard = document.querySelector('[data-recent-canvas-card]');
        applyCardBackground(recentCard, images[0]);
    }

    async function generateWorkbenchImage(draft) {
        setStatus('正在调用默认模型生成图片...');
        try {
            const response = await fetch('/api/online-image', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    prompt: draft.prompt,
                    provider_id: 'comfly',
                    model: selectedImageModel(),
                    size: requestSizeFromSelections(),
                    quality: 'auto',
                    n: 1,
                    reference_images: imageReferencesForRequest(),
                }),
            });
            const data = await response.json().catch(() => ({}));
            if(!response.ok) throw new Error(data.detail || data.message || `生成失败：${response.status}`);
            renderWorkbenchResult(data, draft);
            setStatus('已生成图片，可进入画布继续编辑');
        } catch(e) {
            setStatus(e.message || '生成失败，请检查 API 设置');
        }
    }

    function optimizePromptFallback(prompt) {
        const text = String(prompt || '').trim();
        if(!text) return '';
        const suffix = '，高级商业设计质感，空间层次清晰，主体明确，真实材质细节，柔和但有方向的灯光，专业摄影构图，干净背景，适合方案展示。';
        return text.endsWith('。') || text.endsWith('.') ? `${text}${suffix}` : `${text}${suffix}`;
    }

    async function optimizePromptInPlace() {
        const input = document.getElementById('promptInput');
        const prompt = String(input?.value || '').trim();
        if(!prompt) {
            setStatus('请先输入要优化的提示词');
            input?.focus();
            return;
        }
        setStatus('正在优化提示词...');
        try {
            const response = await fetch('/api/canvas-llm', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    provider: 'comfly',
                    model: '',
                    message: `把下面需求改写成适合图像生成的中文提示词。只输出优化后的提示词，不要解释：\n${prompt}`,
                    system_prompt: '你是商业设计和建筑空间图像提示词专家。输出一句完整、具体、可用于生图的中文提示词。',
                    messages: [],
                    images: [],
                    videos: [],
                }),
            });
            const data = await response.json().catch(() => ({}));
            if(!response.ok) throw new Error(data.detail || data.message || 'LLM 优化失败');
            const next = String(data.text || '').trim();
            if(!next) throw new Error('LLM 未返回内容');
            input.value = next;
            setStatus('提示词已优化');
        } catch(e) {
            const next = optimizePromptFallback(prompt);
            if(next && input) {
                input.value = next;
                setStatus('已用本地模板优化提示词');
            } else {
                setStatus(e.message || '优化失败');
            }
        }
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
        window.__feedbackReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        modal.hidden = false;
        setFeedbackStatus('反馈会保存到后台，后续可做管理页查看。');
        window.setTimeout(() => input?.focus(), 30);
    }

    function closeFeedbackModal() {
        const modal = document.getElementById('feedbackModal');
        if(modal) modal.hidden = true;
        window.__feedbackReturnFocus?.focus?.();
        window.__feedbackReturnFocus = null;
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
                const stored = localStorage.getItem('studio_theme')
                    || localStorage.getItem('canvas_theme')
                    || localStorage.getItem('workbench_theme');
                savedTheme = stored === 'light' ? 'light' : 'dark';
            } catch(e) {}
            applyWorkbenchTheme(savedTheme);
        }

        document.querySelectorAll('[data-open-page]').forEach(button => {
            button.addEventListener('click', () => {
                let params = null;
                if(button.dataset.visibilityTarget) params = { cloud: '1', visibility: button.dataset.visibilityTarget };
                if('recentHistoryTarget' in button.dataset) params = { ...(params || {}), recent: '1' };
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
            document.getElementById('referenceFileInput')?.click();
        });

        document.querySelector('[data-url-placeholder]')?.addEventListener('click', () => {
            openUrlModal();
        });

        document.getElementById('referenceFileInput')?.addEventListener('change', uploadReferenceFiles);
        document.querySelector('[data-url-save]')?.addEventListener('click', saveUrlReference);
        document.querySelectorAll('[data-url-close]').forEach(button => button.addEventListener('click', closeUrlModal));
        document.getElementById('urlModal')?.addEventListener('click', event => {
            if(event.target?.id === 'urlModal') closeUrlModal();
        });
        document.querySelector('[data-optimize-prompt]')?.addEventListener('click', optimizePromptInPlace);
        document.querySelector('[data-open-generated-canvas]')?.addEventListener('click', () => {
            const draft = window.__lastWorkbenchDraft || createWorkbenchDraft();
            if(draft) openCanvasDraft(draft);
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
        document.getElementById('feedbackModal')?.addEventListener('click', event => {
            if(event.target?.id === 'feedbackModal') closeFeedbackModal();
        });
        document.addEventListener('keydown', event => {
            if(event.key === 'Escape' && !document.getElementById('urlModal')?.hidden) {
                closeUrlModal();
                return;
            }
            if(event.key === 'Escape' && !document.getElementById('feedbackModal')?.hidden) {
                closeFeedbackModal();
            }
        });

        if(window.lucide) window.lucide.createIcons();
        loadCurrentUser();
        updateReferenceCount();
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
