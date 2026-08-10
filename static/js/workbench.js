(function(){
    const WORKBENCH_DRAFTS_KEY = 'workbenchCanvasDrafts:v1';
    const WORKBENCH_PENDING_DRAFT_KEY = 'workbenchCanvasDraftPending:v1';
    const WORKBENCH_REFERENCES_KEY = 'workbenchReferences:v1';
    const TEAM_CLOUD_ACCESS_TOKEN_KEY = 'teamCloudAccessToken';
    let currentWorkbenchUser = null;
    let currentWorkbenchTeams = [];
    let authModalMode = 'user';
    let authSignupAwaitingVerification = false;
    let authPendingSignupEmail = '';
    const PROMPT_PLACEHOLDERS = [
        '???????????????????????????????????????????????',
        '???????????????????????????????????????????????',
        '??????????????????????????????????????????????',
        '????????????????????????????????????????????',
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
        'admin-preview',
        'asset-manager',
        'api-settings',
        'comfyui-settings',
    ]);

    function pageUrl(page, params = null) {
        const fallback = {
            workbench: '/static/workbench.html',
            canvas: '/static/canvas-list.html',
            'team-cloud': '/static/team-cloud.html',
            'admin-preview': '/static/admin-preview.html',
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
        document.documentElement.classList.toggle('studio-theme-light', isLight);
        document.body.classList.toggle('studio-theme-light', isLight);
        document.documentElement.classList.toggle('theme-dark', !isLight);
        document.body.classList.toggle('theme-dark', !isLight);
        document.documentElement.classList.toggle('studio-theme-dark', !isLight);
        document.body.classList.toggle('studio-theme-dark', !isLight);
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

    function storedTeamAccessToken() {
        try { return localStorage.getItem(TEAM_CLOUD_ACCESS_TOKEN_KEY) || ''; } catch(e) { return ''; }
    }

    function storeTeamAccessToken(token) {
        try {
            if(token) localStorage.setItem(TEAM_CLOUD_ACCESS_TOKEN_KEY, token);
            else localStorage.removeItem(TEAM_CLOUD_ACCESS_TOKEN_KEY);
        } catch(e) {}
    }

    function teamCloudHeaders(headers = {}) {
        const next = { ...headers };
        const token = storedTeamAccessToken();
        if(token && !next.Authorization && !next.authorization) next.Authorization = `Bearer ${token}`;
        return next;
    }

    function apiErrorMessage(data, fallback = '????') {
        const detail = data && data.detail;
        if(detail && typeof detail === 'object') return detail.message || data.message || fallback;
        return detail || (data && data.message) || fallback;
    }

    async function fetchJson(url, options = {}) {
        const rawHeaders = options.headers || {};
        const headers = String(url || '').startsWith('/api/team-cloud') ? teamCloudHeaders(rawHeaders) : { ...rawHeaders };
        const response = await fetch(url, {
            credentials: 'same-origin',
            ...options,
            headers,
        });
        let data = null;
        try { data = await response.json(); } catch(e) { data = {}; }
        if(!response.ok) throw new Error(apiErrorMessage(data, `request failed: ${response.status}`));
        return data;
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
        setUrlStatus('?????????????');
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
            setUrlStatus('?????????');
            input?.focus();
            return;
        }
        let parsed;
        try {
            parsed = new URL(raw, location.origin);
        } catch(e) {
            setUrlStatus('????????');
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
        setStatus(isLikelyImageUrl(url) ? '?? URL ??????' : '???????');
        closeUrlModal();
    }

    async function uploadReferenceFiles(event) {
        const input = event.currentTarget;
        const files = Array.from(input?.files || []);
        if(!files.length) return;
        const form = new FormData();
        files.forEach(file => form.append('files', file));
        setStatus('???????...');
        try {
            const data = await fetchJson('/api/ai/upload', {
                method: 'POST',
                body: form,
            });
            const uploaded = (data.files || []).filter(item => item?.url);
            if(!uploaded.length) throw new Error('?????????');
            saveReferences([...uploaded.map(item => ({
                url: item.url,
                name: item.name || 'reference',
                kind: item.kind || 'image',
                mime: item.mime || '',
                addedAt: Date.now(),
            })), ...loadReferences()]);
            setStatus(`??? ${uploaded.length} ????`);
        } catch(e) {
            setStatus(e.message || '???????');
        } finally {
            if(input) input.value = '';
        }
    }

    function shortUserName(user) {
        const value = user?.display_name || user?.username || user?.email || '';
        if(!value) return '???';
        const text = String(value).trim();
        if(text.includes('@')) return text.split('@')[0] || text;
        return text;
    }

    async function loadCurrentUser() {
        const label = document.getElementById('workbenchUserLabel');
        const points = document.getElementById('workbenchInspirationPoints');
        if(!label) return null;
        try {
            const data = await fetchJson('/api/team-cloud/me');
            label.textContent = shortUserName(data.user);
            if(points) points.textContent = (data.user && Array.isArray(data.teams) && data.teams.length) ? '???' : '0';
            currentWorkbenchUser = data.user || null;
            currentWorkbenchTeams = Array.isArray(data.teams) ? data.teams : [];
            window.__workbenchCurrentUser = currentWorkbenchUser;
            return data;
        } catch(e) {
            label.textContent = '???';
            if(points) points.textContent = '0';
            currentWorkbenchUser = null;
            currentWorkbenchTeams = [];
            window.__workbenchCurrentUser = null;
            return null;
        }
    }

    async function loadWorkbenchVersion() {
        const label = document.getElementById('workbenchVersionLabel');
        if(!label) return;
        try {
            const data = await fetchJson('/healthz');
            const version = String(data?.version || '').trim();
            label.textContent = version ? `v${version}` : '';
            label.hidden = !version;
        } catch(e) {
            label.hidden = true;
        }
    }

    function hasApiSettingsAccess() {
        return !!currentWorkbenchUser && currentWorkbenchTeams.some(team => ['owner', 'admin'].includes(String(team?.role || '').toLowerCase()));
    }

    function setAuthMessage(text, type = '') {
        const el = document.getElementById('authModalMessage');
        if(!el) return;
        el.textContent = text || '';
        el.classList.remove('error', 'ok');
        if(type) el.classList.add(type);
    }

    function setAuthMode(mode, options = {}) {
        authModalMode = mode === 'admin' ? 'admin' : (mode === 'signup' ? 'signup' : (mode === 'recover' ? 'recover' : 'user'));
        if(authModalMode !== 'signup' || options.resetSignup) {
            authSignupAwaitingVerification = false;
            authPendingSignupEmail = '';
        }
        const isSignup = authModalMode === 'signup';
        const isAdmin = authModalMode === 'admin';
        const isRecover = authModalMode === 'recover';
        const verifyMode = isSignup && authSignupAwaitingVerification;
        document.querySelectorAll('[data-auth-mode]').forEach(button => {
            const active = button.dataset.authMode === authModalMode;
            button.classList.toggle('active', active);
            button.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        const kicker = document.getElementById('authModalKicker');
        const title = document.getElementById('authModalTitle');
        const usernameField = document.getElementById('authUsernameField');
        const usernameInput = document.getElementById('authUsernameInput');
        const identifierLabel = document.getElementById('authIdentifierLabel');
        const identifierInput = document.getElementById('authIdentifierInput');
        const passwordInput = document.getElementById('authPasswordInput');
        const verificationField = document.getElementById('authVerificationField');
        const verificationInput = document.getElementById('authVerificationInput');
        const resendButton = document.querySelector('[data-auth-resend]');
        const recoverButton = document.querySelector('[data-auth-recover]');
        const backLoginButton = document.querySelector('[data-auth-back-login]');
        const submitButton = document.querySelector('[data-auth-submit]');
        if(kicker) kicker.textContent = isAdmin ? '?????' : (isSignup ? '??????' : (isRecover ? '????' : '????'));
        if(title) title.textContent = isAdmin ? '?????' : (isSignup ? '?? AI?????' : (isRecover ? '?? AI?????' : '??? AI???'));
        if(usernameField) usernameField.hidden = !isSignup || verifyMode;
        if(usernameInput) {
            usernameInput.required = isSignup && !verifyMode;
            usernameInput.disabled = verifyMode;
        }
        if(identifierLabel) identifierLabel.textContent = isSignup ? '??' : (isRecover ? '?? / ??' : '?? / ??');
        if(identifierInput) {
            identifierInput.type = isSignup ? 'email' : 'text';
            identifierInput.name = isSignup ? 'email' : 'identifier';
            identifierInput.autocomplete = isSignup ? 'email' : 'username';
            identifierInput.placeholder = isSignup ? '?????????' : (isRecover ? '???????????' : '???????');
            identifierInput.disabled = verifyMode;
        }
        const passwordField = passwordInput?.closest?.('.auth-field');
        if(passwordField) passwordField.hidden = isRecover || verifyMode;
        if(passwordInput) {
            passwordInput.autocomplete = isSignup ? 'new-password' : 'current-password';
            passwordInput.disabled = isRecover || verifyMode;
            passwordInput.required = !isRecover && !verifyMode;
        }
        if(verificationField) verificationField.hidden = !verifyMode;
        if(verificationInput) verificationInput.required = verifyMode;
        if(resendButton) resendButton.hidden = !verifyMode;
        if(recoverButton) recoverButton.hidden = authModalMode !== 'user';
        if(backLoginButton) backLoginButton.hidden = authModalMode !== 'recover';
        if(submitButton) {
            submitButton.textContent = isAdmin ? '?????' : (verifyMode ? '?????' : (isSignup ? '?????' : (isRecover ? '??????' : '??')));
        }
        setAuthMessage(isAdmin
            ? '????????????? API ???'
            : (isSignup ? '????????????????????????' : (isRecover ? '?????????????????????' : '????????????????? API ???')));
    }

    function openAuthModal(mode = 'user') {
        const modal = document.getElementById('authModal');
        const input = document.getElementById('authIdentifierInput');
        if(!modal) return;
        window.__authReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        setAuthMode(mode);
        modal.hidden = false;
        const focusInput = () => input?.focus?.({ preventScroll: true });
        window.requestAnimationFrame(focusInput);
        window.setTimeout(focusInput, 80);
    }

    function closeAuthModal() {
        const modal = document.getElementById('authModal');
        if(modal) modal.hidden = true;
        setAuthMessage('????????????????? API ???');
        window.__authReturnFocus?.focus?.();
        window.__authReturnFocus = null;
    }

    async function submitAuthModal(event) {
        event?.preventDefault?.();
        const identifier = String(document.getElementById('authIdentifierInput')?.value || '').trim();
        const password = String(document.getElementById('authPasswordInput')?.value || '');
        const username = String(document.getElementById('authUsernameInput')?.value || '').trim();
        const verification = String(document.getElementById('authVerificationInput')?.value || '').trim();
        const button = document.querySelector('[data-auth-submit]');
        const isSignup = authModalMode === 'signup';
        const isRecover = authModalMode === 'recover';
        const verifyMode = isSignup && authSignupAwaitingVerification;
        if(!identifier || (!verifyMode && !isRecover && !password) || (isSignup && !verifyMode && !username)) {
            setAuthMessage(isSignup ? '?????????????' : (isRecover ? '?????????' : '?????/??????'), 'error');
            return;
        }
        if(verifyMode && !verification) {
            setAuthMessage('?????????', 'error');
            return;
        }
        if(button) button.disabled = true;
        setAuthMessage(verifyMode ? '??????...' : (isSignup ? '???????...' : (isRecover ? '????????...' : '????...')));
        try {
            let data;
            if(isRecover) {
                await fetchJson('/api/team-cloud/auth/recover', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ identifier }),
                });
                setAuthMessage('??????????????????????', 'ok');
                return;
            }
            if(verifyMode) {
                data = await fetchJson('/api/team-cloud/auth/signup/verify', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ email: authPendingSignupEmail || identifier, token: verification }),
                });
            } else if(isSignup) {
                data = await fetchJson('/api/team-cloud/auth/signup/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username, email: identifier, password }),
                });
                if(data.verification_required) {
                    authSignupAwaitingVerification = true;
                    authPendingSignupEmail = data.email || identifier;
                    setAuthMode('signup');
                    document.getElementById('authVerificationInput').value = '';
                    document.getElementById('authVerificationInput')?.focus?.({ preventScroll: true });
                    setAuthMessage('???????????????????????', 'ok');
                    return;
                }
            } else {
                data = await fetchJson('/api/team-cloud/auth/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ identifier, password }),
                });
            }
            if(!data.session_ready) throw new Error('??????????????');
            storeTeamAccessToken(data.access_token || '');
            authSignupAwaitingVerification = false;
            authPendingSignupEmail = '';
            await loadCurrentUser();
            if(authModalMode === 'admin') {
                if(!hasApiSettingsAccess()) {
                    setAuthMessage('?????????????? API ???', 'error');
                    return;
                }
                closeAuthModal();
                openPage('api-settings');
                return;
            }
            closeAuthModal();
            setStatus(isSignup ? '????' : '????');
        } catch(e) {
            setAuthMessage(e.message || (isSignup ? '??????????????' : '?????????'), 'error');
        } finally {
            if(button) button.disabled = false;
        }
    }

    async function resendAuthVerification() {
        const button = document.querySelector('[data-auth-resend]');
        const email = authPendingSignupEmail || String(document.getElementById('authIdentifierInput')?.value || '').trim();
        if(!email) {
            setAuthMessage('???????', 'error');
            return;
        }
        if(button) button.disabled = true;
        setAuthMessage('???????...');
        try {
            await fetchJson('/api/team-cloud/auth/verification/resend', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ email }),
            });
            setAuthMessage('???????????????', 'ok');
        } catch(e) {
            setAuthMessage(e.message || '????????', 'error');
        } finally {
            if(button) button.disabled = false;
        }
    }

    function openAccountEntry() {
        if(currentWorkbenchUser) {
            openPage('team-cloud');
            return;
        }
        openAuthModal('user');
    }

    async function openApiSettingsEntry() {
        if(!currentWorkbenchUser) await loadCurrentUser();
        if(!currentWorkbenchUser) {
            openAuthModal('admin');
            return;
        }
        if(!hasApiSettingsAccess()) {
            openAuthModal('admin');
            setAuthMessage('??????????? API ???', 'error');
            return;
        }
        openPage('api-settings');
    }
    function selectedValue(id) {
        const el = document.getElementById(id);
        return String(el?.value || '').trim();
    }

    function closeCustomSelects(except = null) {
        document.querySelectorAll('[data-custom-select]').forEach(chip => {
            if(chip === except) return;
            chip.classList.remove('is-open');
            chip.querySelector('[data-select-display]')?.setAttribute('aria-expanded', 'false');
            const menu = chip.querySelector('.select-menu');
            if(menu) menu.hidden = true;
        });
    }

    function setCustomSelectValue(chip, value) {
        const select = chip.querySelector('select');
        const label = chip.querySelector('[data-select-value]');
        if(!select) return;
        select.value = value;
        if(label) label.textContent = select.options[select.selectedIndex]?.text || value;
        chip.querySelectorAll('.select-option').forEach(option => {
            const selected = option.dataset.value === select.value;
            option.classList.toggle('is-selected', selected);
            option.setAttribute('aria-selected', selected ? 'true' : 'false');
        });
        select.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function initCustomSelects() {
        document.querySelectorAll('[data-custom-select]').forEach(chip => {
            const select = chip.querySelector('select');
            const display = chip.querySelector('[data-select-display]');
            const menu = chip.querySelector('.select-menu');
            const label = chip.querySelector('[data-select-value]');
            if(!select || !display || !menu) return;
            select.tabIndex = -1;
            select.setAttribute('aria-hidden', 'true');
            menu.innerHTML = Array.from(select.options).map(option => `
                <button class="select-option" type="button" role="option" data-value="${escapeAttr(option.value)}" aria-selected="false">
                    ${escapeHtml(option.text)}
                </button>
            `).join('');
            if(label) label.textContent = select.options[select.selectedIndex]?.text || select.value;
            chip.querySelectorAll('.select-option').forEach(option => {
                option.addEventListener('click', event => {
                    event.stopPropagation();
                    setCustomSelectValue(chip, option.dataset.value || '');
                    closeCustomSelects();
                });
            });
            setCustomSelectValue(chip, select.value);
            display.addEventListener('click', event => {
                event.stopPropagation();
                const open = !chip.classList.contains('is-open');
                closeCustomSelects(open ? chip : null);
                chip.classList.toggle('is-open', open);
                menu.hidden = !open;
                display.setAttribute('aria-expanded', open ? 'true' : 'false');
            });
        });
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
        if(label) label.textContent = `${count}????`;
    }

    function draftTitleFromPrompt(prompt) {
        const firstLine = String(prompt || '').trim().split(/\r?\n/)[0] || '';
        return (firstLine || '????').slice(0, 42);
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
            setStatus('????????');
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
        return value && !value.includes('??') ? value : '';
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
            <a class="result-card" href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer" aria-label="????? ${index + 1}">
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
        setStatus('????????????...');
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
            if(!response.ok) throw new Error(data.detail || data.message || `?????${response.status}`);
            renderWorkbenchResult(data, draft);
            setStatus('???????????????');
        } catch(e) {
            setStatus(e.message || '???????? API ??');
        }
    }

    function optimizePromptFallback(prompt) {
        const text = String(prompt || '').trim();
        if(!text) return '';
        const suffix = '??????????????????????????????????????????????????????????';
        return text.endsWith('?') || text.endsWith('.') ? `${text}${suffix}` : `${text}${suffix}`;
    }

    async function optimizePromptInPlace() {
        const input = document.getElementById('promptInput');
        const prompt = String(input?.value || '').trim();
        if(!prompt) {
            setStatus('???????????');
            input?.focus();
            return;
        }
        setStatus('???????...');
        try {
            const response = await fetch('/api/canvas-llm', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    provider: 'comfly',
                    model: '',
                    message: `?????????????????????????????????????\n${prompt}`,
                    system_prompt: '?????????????????????????????????????????',
                    messages: [],
                    images: [],
                    videos: [],
                }),
            });
            const data = await response.json().catch(() => ({}));
            if(!response.ok) throw new Error(data.detail || data.message || 'LLM ????');
            const next = String(data.text || '').trim();
            if(!next) throw new Error('LLM ?????');
            input.value = next;
            setStatus('??????');
        } catch(e) {
            const next = optimizePromptFallback(prompt);
            if(next && input) {
                input.value = next;
                setStatus('???????????');
            } else {
                setStatus(e.message || '????');
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
        setFeedbackStatus('???????????????????');
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
            setFeedbackStatus('??????????');
            input?.focus();
            return;
        }
        setFeedbackStatus('????...');
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
            setFeedbackStatus('??????????');
            window.setTimeout(closeFeedbackModal, 900);
        } catch(e) {
            setFeedbackStatus('??????????????????????');
        }
    }

    function init() {
        initCustomSelects();

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
            if(!event.target.closest?.('[data-custom-select]')) closeCustomSelects();
        });

        window.addEventListener('message', event => {
            if(event.origin && event.origin !== location.origin) return;
            if(event.data?.type === 'studio-theme') applyWorkbenchTheme(event.data.theme);
        });

        document.querySelector('[data-clear-prompt]')?.addEventListener('click', () => {
            const input = document.getElementById('promptInput');
            if(input) input.value = '';
            setStatus('????');
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
        document.querySelector('[data-account-entry]')?.addEventListener('click', openAccountEntry);
        document.querySelector('[data-api-settings-entry]')?.addEventListener('click', openApiSettingsEntry);
        document.querySelector('[data-theme-toggle]')?.addEventListener('click', toggleStudioTheme);
        document.querySelectorAll('[data-feedback-close]').forEach(button => {
            button.addEventListener('click', closeFeedbackModal);
        });
        document.querySelector('[data-feedback-submit]')?.addEventListener('click', submitFeedback);
        document.getElementById('authModalForm')?.addEventListener('submit', submitAuthModal);
        document.querySelectorAll('[data-auth-close]').forEach(button => button.addEventListener('click', closeAuthModal));
        document.querySelectorAll('[data-auth-mode]').forEach(button => button.addEventListener('click', () => setAuthMode(button.dataset.authMode, { resetSignup: true })));
        document.querySelector('[data-auth-recover]')?.addEventListener('click', () => setAuthMode('recover'));
        document.querySelector('[data-auth-back-login]')?.addEventListener('click', () => setAuthMode('user'));
        document.querySelector('[data-auth-resend]')?.addEventListener('click', resendAuthVerification);
        document.getElementById('authModal')?.addEventListener('click', event => {
            if(event.target?.id === 'authModal') closeAuthModal();
        });
        document.getElementById('feedbackModal')?.addEventListener('click', event => {
            if(event.target?.id === 'feedbackModal') closeFeedbackModal();
        });
        document.addEventListener('keydown', event => {
            if(event.key === 'Escape' && !document.getElementById('urlModal')?.hidden) {
                closeUrlModal();
                return;
            }
            if(event.key === 'Escape' && document.querySelector('[data-custom-select].is-open')) {
                closeCustomSelects();
                return;
            }
            if(event.key === 'Escape' && !document.getElementById('feedbackModal')?.hidden) {
                closeFeedbackModal();
                return;
            }
            if(event.key === 'Escape' && !document.getElementById('authModal')?.hidden) {
                closeAuthModal();
            }
        });

        if(window.lucide) window.lucide.createIcons();
        loadWorkbenchVersion();
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
