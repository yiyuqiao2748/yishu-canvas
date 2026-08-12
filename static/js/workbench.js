(function(){
    const WORKBENCH_DRAFTS_KEY = 'workbenchCanvasDrafts:v1';
    const WORKBENCH_PENDING_DRAFT_KEY = 'workbenchCanvasDraftPending:v1';
    const WORKBENCH_REFERENCES_KEY = 'workbenchReferences:v1';
    const TEAM_CLOUD_ACCESS_TOKEN_KEY = 'teamCloudAccessToken';
    const TEAM_CLOUD_TEAM_KEY = 'teamCloudCurrentTeamId';
    let currentWorkbenchUser = null;
    let currentWorkbenchTeams = [];
    let authModalMode = 'user';
    let authSignupAwaitingVerification = false;
    let authPendingSignupEmail = '';
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

    function apiErrorMessage(data, fallback = '请求失败') {
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

    function applyWorkbenchAuthState(data) {
        const label = document.getElementById('workbenchUserLabel');
        const points = document.getElementById('workbenchInspirationPoints');
        currentWorkbenchUser = data?.user || null;
        currentWorkbenchTeams = Array.isArray(data?.teams) ? data.teams : [];
        if(label) label.textContent = shortUserName(currentWorkbenchUser);
        if(points && !currentWorkbenchUser) points.textContent = '0';
        try {
            const teamId = data?.selected_team_id || data?.team_id || data?.teams?.[0]?.id || '';
            if(teamId) localStorage.setItem(TEAM_CLOUD_TEAM_KEY, teamId);
        } catch(e) {}
        window.__workbenchCurrentUser = currentWorkbenchUser;
        return data;
    }

    async function loadCurrentUser() {
        const label = document.getElementById('workbenchUserLabel');
        const points = document.getElementById('workbenchInspirationPoints');
        if(!label) return null;
        try {
            // Keep the auth gate independent from optional bootstrap data.
            const auth = applyWorkbenchAuthState(await fetchJson('/api/team-cloud/me'));
            try {
                const data = await fetchJson('/api/team-cloud/bootstrap');
                if(points) points.textContent = auth.user && auth.teams.length
                    ? new Intl.NumberFormat('zh-CN').format(Number(data.points?.balance || 0))
                    : '0';
                return { ...data, user: auth.user, teams: auth.teams };
            } catch(e) {
                if(points) points.textContent = auth.user && auth.teams.length ? points.textContent : '0';
                return auth;
            }
        } catch(e) {
            label.textContent = '未登录';
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
        if(kicker) kicker.textContent = isAdmin ? '管理员入口' : (isSignup ? '邮箱验证注册' : (isRecover ? '找回密码' : '账户登录'));
        if(title) title.textContent = isAdmin ? '管理员登录' : (isSignup ? '注册 AI设计师账号' : (isRecover ? '找回 AI设计师账号' : '登录到 AI设计师'));
        if(usernameField) usernameField.hidden = !isSignup || verifyMode;
        if(usernameInput) {
            usernameInput.required = isSignup && !verifyMode;
            usernameInput.disabled = verifyMode;
        }
        if(identifierLabel) identifierLabel.textContent = isSignup ? '邮箱' : (isRecover ? '邮箱 / 账号' : '邮箱 / 账号');
        if(identifierInput) {
            identifierInput.type = isSignup ? 'email' : 'text';
            identifierInput.name = isSignup ? 'email' : 'identifier';
            identifierInput.autocomplete = isSignup ? 'email' : 'username';
            identifierInput.placeholder = isSignup ? '输入邮箱接收验证码' : (isRecover ? '输入邮箱或账号找回密码' : '输入邮箱或账号');
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
            submitButton.textContent = isAdmin ? '管理员登录' : (verifyMode ? '验证并注册' : (isSignup ? '发送验证码' : (isRecover ? '发送找回邮件' : '登录')));
        }
        setAuthMessage(isAdmin
            ? '管理员登录成功后会直接进入 API 设置。'
            : (isSignup ? '注册需要邮箱验证码，邮箱之后用于找回和修改密码。' : (isRecover ? '输入邮箱或账号后，我们会发送重置密码邮件。' : '登录后可使用团队资源；管理员可进入 API 设置。')));
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
        setAuthMessage('登录后可使用团队资源；管理员可进入 API 设置。');
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
            setAuthMessage(isSignup ? '请输入账号名、邮箱和密码。' : (isRecover ? '请输入邮箱或账号。' : '请输入邮箱/账号和密码。'), 'error');
            return;
        }
        if(verifyMode && !verification) {
            setAuthMessage('请输入邮箱验证码。', 'error');
            return;
        }
        if(button) button.disabled = true;
        setAuthMessage(verifyMode ? '正在验证邮箱...' : (isSignup ? '正在发送验证码...' : (isRecover ? '正在发送找回邮件...' : '正在登录...')));
        try {
            let data;
            if(isRecover) {
                await fetchJson('/api/team-cloud/auth/recover', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ identifier }),
                });
                setAuthMessage('如果账号存在，找回密码邮件会发送到对应邮箱。', 'ok');
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
                    setAuthMessage('验证码已发送，请查看邮箱并输入验证码完成注册。', 'ok');
                    return;
                }
            } else {
                data = await fetchJson('/api/team-cloud/auth/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ identifier, password }),
                });
            }
            if(!data.session_ready) throw new Error('登录未成功，请检查账号状态。');
            storeTeamAccessToken(data.access_token || '');
            authSignupAwaitingVerification = false;
            authPendingSignupEmail = '';
            if(authModalMode === 'admin') {
                await loadCurrentUser();
                if(!hasApiSettingsAccess()) {
                    setAuthMessage('当前账户不是管理员，不能进入 API 设置。', 'error');
                    return;
                }
                closeAuthModal();
                openPage('api-settings');
                return;
            }
            closeAuthModal();
            setStatus(isSignup ? '注册成功' : '登录成功');
            void loadCurrentUser();
        } catch(e) {
            setAuthMessage(e.message || (isSignup ? '注册失败，请检查邮箱验证码。' : '账号或密码不正确。'), 'error');
        } finally {
            if(button) button.disabled = false;
        }
    }

    async function resendAuthVerification() {
        const button = document.querySelector('[data-auth-resend]');
        const email = authPendingSignupEmail || String(document.getElementById('authIdentifierInput')?.value || '').trim();
        if(!email) {
            setAuthMessage('请先填写邮箱。', 'error');
            return;
        }
        if(button) button.disabled = true;
        setAuthMessage('正在重发验证码...');
        try {
            await fetchJson('/api/team-cloud/auth/verification/resend', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ email }),
            });
            setAuthMessage('验证码已重新发送，请查看邮箱。', 'ok');
        } catch(e) {
            setAuthMessage(e.message || '验证码重发失败。', 'error');
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
        await loadCurrentUser();
        if(!currentWorkbenchUser) {
            openAuthModal('admin');
            return;
        }
        if(!hasApiSettingsAccess()) {
            openAuthModal('admin');
            setAuthMessage('需要管理员账户才能进入 API 设置。', 'error');
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
                    team_id: (() => { try { return localStorage.getItem(TEAM_CLOUD_TEAM_KEY) || ''; } catch(e) { return ''; } })(),
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
        const preview = workbenchMediaPreviewUrl(url, 512);
        card.style.setProperty('--library-card-bg', `url("${String(preview).replace(/"/g, '%22')}")`);
        card.classList.add('has-bg');
        return true;
    }

    function workbenchMediaPreviewUrl(url, size = 512) {
        const raw = String(url || '').trim();
        if(!raw || raw.startsWith('data:') || raw.startsWith('blob:') || raw.startsWith('/api/media-preview')) return raw;
        if(!raw.startsWith('/assets/') && !raw.startsWith('/output/') && !raw.startsWith('/api/storage-files/')) return raw;
        if(!/\.(png|jpe?g|webp|gif|bmp|avif|tiff?)(\?|#|$)/i.test(raw)) return raw;
        const width = Math.max(64, Math.min(2048, Math.round(Number(size) || 512)));
        return `/api/media-preview?w=${width}&url=${encodeURIComponent(raw)}`;
    }

    async function loadRecentCanvasBackground() {
        const card = document.querySelector('[data-recent-canvas-card]');
        if(!card) return;
        try {
            const data = await fetchJson('/api/canvases');
            const canvases = (data.canvases || [])
                .slice()
                .sort((a, b) => Number(b.updated_at || b.created_at || 0) - Number(a.updated_at || a.created_at || 0))
                .slice(0, 3);
            const details = await Promise.all(canvases.map(canvas => fetchJson(`/api/canvases/${encodeURIComponent(canvas.id)}`)
                .catch(() => null)));
            for(const detail of details) {
                if(!detail) continue;
                const urls = collectImageUrls(detail.canvas || detail);
                if(applyCardBackground(card, urls[0])) return;
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
        void loadCurrentUser();
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
