function generateUUID() {
            if (typeof crypto !== 'undefined' && crypto.randomUUID) {
                try { return crypto.randomUUID(); } catch (e) { }
            }
            return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
                var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
        }
        const CID = localStorage.getItem("client_id") || generateUUID();
        localStorage.setItem("client_id", CID);
        const ACTIVE_PAGE_KEY = 'studio_active_page';
        const LOCAL_NAV_COLLAPSED_KEY = 'studio_local_nav_collapsed';
        const SIDEBAR_SETTINGS_COLLAPSED_KEY = 'studio_sidebar_settings_collapsed';
        const SIDEBAR_PINNED_KEY = 'studio_sidebar_pinned';
        const DEFAULT_PAGE_ID = 'workbench';
        const PAGE_IDS = ['workbench','zimage','enhance','klein','angle','online','gpt-chat','canvas','team-cloud','admin-preview','asset-manager','api-settings','comfyui-settings'];
        const LOCAL_PAGE_IDS = ['zimage','enhance','klein','angle'];
        const PROJECT_URL = 'https://github.com/hero8152/Infinite-Canvas';
        let appInfo = { version:'', repo_url:PROJECT_URL, version_url:'https://raw.githubusercontent.com/hero8152/Infinite-Canvas/main/VERSION' };
        let updateConnectivityResult = null;
        let projectUpdateRunning = false;
        let projectUpdateAbort = null;  // 当前更新请求的 AbortController，便于用户中途取消
        let updateSource = localStorage.getItem('studio_update_source') || 'github';
        let projectUpdateNotes = null;

        function setSidebarPinned(pinned, options = {}) {
            const sidebar = document.getElementById('studioSidebar');
            const logo = document.getElementById('sidebarLogoToggle');
            if(!sidebar) return;
            pauseScaleInFrames();
            sidebar.classList.toggle('is-pinned', pinned);
            if(!pinned) {
                sidebar.classList.add('is-collapsing');
                window.setTimeout(() => sidebar.classList.remove('is-collapsing'), 360);
            } else {
                sidebar.classList.remove('is-collapsing');
            }
            if(logo) {
                logo.setAttribute('aria-pressed', pinned ? 'true' : 'false');
                logo.title = pinned ? '收起导航栏' : '固定导航栏';
            }
            if(!options.skipRemember) localStorage.setItem(SIDEBAR_PINNED_KEY, pinned ? '1' : '0');
        }

        function toggleSidebarPinned(event) {
            event?.preventDefault?.();
            event?.stopPropagation?.();
            const sidebar = document.getElementById('studioSidebar');
            setSidebarPinned(!sidebar?.classList.contains('is-pinned'));
        }

        function restoreSidebarPinned() {
            setSidebarPinned(localStorage.getItem(SIDEBAR_PINNED_KEY) === '1', { skipRemember:true });
        }

        function setLocalNavCollapsed(collapsed, options = {}) {
            const group = document.getElementById('local-nav-group');
            const toggle = document.getElementById('local-nav-toggle');
            if(group) group.classList.toggle('is-collapsed', collapsed);
            if(toggle) {
                toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
                toggle.title = collapsed ? '展开本地功能' : '折叠本地功能';
            }
            if(!options.skipRemember) localStorage.setItem(LOCAL_NAV_COLLAPSED_KEY, collapsed ? '1' : '0');
        }

        function toggleLocalNav() {
            const group = document.getElementById('local-nav-group');
            setLocalNavCollapsed(!group?.classList.contains('is-collapsed'));
        }

        function restoreLocalNav(id) {
            const savedCollapsed = localStorage.getItem(LOCAL_NAV_COLLAPSED_KEY) === '1';
            setLocalNavCollapsed(savedCollapsed && !LOCAL_PAGE_IDS.includes(id), { skipRemember:true });
        }

        function setSidebarSettingsCollapsed(collapsed, options = {}) {
            const group = document.getElementById('settings-fold-group');
            const toggle = document.getElementById('settings-fold-toggle');
            if(group) group.classList.toggle('is-collapsed', collapsed);
            if(toggle) {
                toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
                toggle.title = collapsed ? '展开更多设置' : '收起更多设置';
            }
            if(!options.skipRemember) localStorage.setItem(SIDEBAR_SETTINGS_COLLAPSED_KEY, collapsed ? '1' : '0');
        }

        function toggleSidebarSettings() {
            const group = document.getElementById('settings-fold-group');
            setSidebarSettingsCollapsed(!group?.classList.contains('is-collapsed'));
        }

        function restoreSidebarSettings(id) {
            const savedCollapsed = localStorage.getItem(SIDEBAR_SETTINGS_COLLAPSED_KEY) !== '0';
            setSidebarSettingsCollapsed(savedCollapsed && id !== 'comfyui-settings', { skipRemember:true });
        }

        function resetStudioRootScroll() {
            try {
                window.scrollTo(0, 0);
                document.documentElement.scrollTop = 0;
                document.body.scrollTop = 0;
            } catch(e) {}
        }

        const IMMERSIVE_PAGE_IDS = new Set(['workbench', 'canvas', 'team-cloud', 'admin-preview', 'asset-manager', 'api-settings', 'comfyui-settings']);

        function setStudioPageMode(id) {
            document.body.classList.toggle('studio-workbench-mode', id === 'workbench');
            document.body.classList.toggle('studio-immersive-mode', IMMERSIVE_PAGE_IDS.has(id));
        }

        function frameSrcWithParams(frame, params) {
            const base = frame?.dataset?.src || frame?.getAttribute('src') || '';
            if(!base) return '';
            const url = new URL(base, location.origin);
            if(params && typeof params === 'object') {
                Object.entries(params).forEach(([key, value]) => {
                    if(value === undefined || value === null || value === '') return;
                    url.searchParams.set(key, String(value));
                });
            }
            return url.pathname + url.search + url.hash;
        }

        function switchUI(el, id, options = {}) {
            resetStudioRootScroll();
            if(!PAGE_IDS.includes(id)) id = DEFAULT_PAGE_ID;
            setStudioPageMode(id);
            document.querySelectorAll('.nav-item,.side-pill').forEach(n => n.classList.remove('active'));
            if(el) el.classList.add('active');
            document.querySelectorAll('iframe').forEach(f => f.classList.remove('active'));
            const target = document.getElementById('frame-' + id);
            if(!target) return;
            target.classList.add('active');
            const nextSrc = frameSrcWithParams(target, options.params);
            if(options.params || !target.src) target.src = nextSrc;
            if(!options.skipRemember) localStorage.setItem(ACTIVE_PAGE_KEY, id);
            // sync theme to newly activated iframe
            syncThemeToFrame(target);
            syncLanguageToFrame(target);
            syncScaleToFrame(target);
            if(LOCAL_PAGE_IDS.includes(id)) {
                setLocalNavCollapsed(false, { skipRemember:true });
            } else {
                setLocalNavCollapsed(localStorage.getItem(LOCAL_NAV_COLLAPSED_KEY) === '1', { skipRemember:true });
            }
            if(id === 'comfyui-settings') {
                setSidebarSettingsCollapsed(false, { skipRemember:true });
            }
            // 切换到画布时通知刷新工作流列表（防止在 comfyui-settings 修改后画布未及时更新）
            if (id === 'canvas' && target.src) {
                try { target.contentWindow?.postMessage({ type: 'canvas-focus' }, '*'); } catch(e) {}
            }
            resetStudioRootScroll();
        }

        const studioApiForwardSeen = new Map();
        function studioApiEventKey(data) {
            return [data?.type || '', data?.updated_at || '', data?.source || ''].join('|');
        }

        function activeFrame() {
            return document.querySelector('iframe.active');
        }

        function forwardStudioApiChange(data) {
            if(!data || !['providers-changed','workflows-changed','comfy-instances-changed'].includes(data.type)) return;
            const key = studioApiEventKey(data);
            const now = Date.now();
            if(studioApiForwardSeen.get(key) && now - studioApiForwardSeen.get(key) < 1200) return;
            studioApiForwardSeen.set(key, now);
            if(studioApiForwardSeen.size > 40) {
                Array.from(studioApiForwardSeen.entries()).forEach(([eventKey, at]) => {
                    if(now - at > 2500) studioApiForwardSeen.delete(eventKey);
                });
            }
            const iframe = activeFrame();
            try {
                if (iframe && iframe.contentWindow) iframe.contentWindow.postMessage(data, '*');
            } catch(e) {}
        }

        window.addEventListener('message', event => {
            if (event.origin && event.origin !== location.origin) return;
            if(event.data?.type === 'studio-open-page') {
                const id = event.data.page;
                if(PAGE_IDS.includes(id)) {
                    const trigger = document.querySelector(`[onclick*="'${id}'"],[onclick*='"${id}"']`);
                    switchUI(trigger, id, { params: event.data.params || null });
                }
                return;
            }
            if(event.data?.type === 'studio-toggle-theme') {
                toggleTheme();
                return;
            }
            forwardStudioApiChange(event.data);
        });

        try {
            const studioApiChannel = new BroadcastChannel('studio-api');
            studioApiChannel.onmessage = event => forwardStudioApiChange(event.data);
        } catch(e) {}

        function restoreActivePage() {
            restoreSidebarPinned();
            const searchParams = new URLSearchParams(location.search || '');
            const requestedId = searchParams.get('page');
            const savedId = localStorage.getItem(ACTIVE_PAGE_KEY);
            const canRestoreSaved = Boolean(location.search || location.hash);
            const id = PAGE_IDS.includes(requestedId)
                ? requestedId
                : (canRestoreSaved && PAGE_IDS.includes(savedId) ? savedId : DEFAULT_PAGE_ID);
            restoreLocalNav(id);
            restoreSidebarSettings(id);
            const trigger = document.querySelector(`[onclick*="'${id}'"],[onclick*='"${id}"']`);
            switchUI(trigger, id, { skipRemember:true });
            document.documentElement.classList.remove('studio-route-booting');
        }
        document.addEventListener('DOMContentLoaded', restoreActivePage, { once:true });

        async function syncStatus() {
            try {
                const res = await fetch(`/api/queue_status?client_id=${CID}`);
                const data = await res.json();
                const monitor = document.getElementById('nano-monitor');
                const queueVal = document.getElementById('queue-val');
                const logoDot = document.getElementById('logo-dot');
                const total = data.total || 0;
                const pos = data.position || 0;
                if (pos > 0) {
                    monitor?.classList.add('is-busy');
                    if (queueVal) queueVal.innerText = `${pos}/${total}`;
                    if (logoDot) logoDot.style.backgroundColor = '#3b82f6';
                } else {
                    monitor?.classList.remove('is-busy');
                    if (queueVal) queueVal.innerText = total > 0 ? total : '0';
                    if (logoDot) logoDot.style.backgroundColor = 'var(--text)';
                }
            } catch (e) { }
        }

        const host = window.location.host;
        if (host) {
            const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
            const ws = new WebSocket(`${protocol}://${host}/ws/stats?client_id=${CID}`);
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === 'stats') {
                    const ov = document.getElementById('online-val');
                    if (ov) ov.innerText = data.online_count;
                } else if (data.type === 'cloud_status') {
                    const iframe = document.querySelector('iframe.active');
                    if (iframe && iframe.contentWindow) {
                        iframe.contentWindow.postMessage(data, '*');
                    }
                } else if (data.type === 'canvas_updated') {
                    const iframe = document.querySelector('iframe.active');
                    if (iframe && iframe.contentWindow) {
                        iframe.contentWindow.postMessage(data, '*');
                    }
                } else if (data.type === 'asset_library_updated') {
                    document.querySelectorAll('iframe').forEach(iframe => {
                        if (iframe && iframe.contentWindow) iframe.contentWindow.postMessage(data, '*');
                    });
                }
            };
            setInterval(syncStatus, 2000);
        }

        // --- 夜间模式 ---

        function syncThemeToFrame(iframe) {
            const theme = (window.StudioTheme || {get: () => 'light'}).get();
            try {
                if (iframe && iframe.contentWindow) {
                    iframe.contentWindow.postMessage({ type: 'studio-theme', theme }, '*');
                }
            } catch (e) {}
        }

        function syncScaleToFrame(iframe) {
            const mode = (window.StudioScale || {getMode: () => 'auto'}).getMode();
            const cssScale = Number(getComputedStyle(document.documentElement).getPropertyValue('--studio-ui-scale'));
            const scale = Number.isFinite(cssScale) && cssScale > 0 ? cssScale : ((window.StudioScale || {getScale: () => 1}).getScale());
            try {
                if (iframe && iframe.contentWindow) {
                    iframe.contentWindow.postMessage({ type: 'studio-ui-scale', mode, scale }, '*');
                }
            } catch (e) {}
        }

        function pauseScaleInFrame(frame, duration = 650) {
            try {
                frame?.contentWindow?.postMessage({ type:'studio-ui-scale-pause', duration }, '*');
            } catch(e) {}
        }

        function pauseScaleInFrames(duration = 650) {
            pauseScaleInFrame(activeFrame(), duration);
        }

        function broadcastScaleToFrames() {
            document.querySelectorAll('iframe').forEach(frame => syncScaleToFrame(frame));
        }

        function broadcastTheme(theme) {
            if (window.StudioTheme) {
                window.StudioTheme.set(theme);
            }
            document.querySelectorAll('iframe').forEach(f => syncThemeToFrame(f));
            updateThemeIcon(theme);
        }

        function updateThemeIcon(theme) {
            const moon = document.getElementById('icon-moon');
            const sun = document.getElementById('icon-sun');
            const dark = theme === 'dark';
            if (dark) {
                moon.style.display = 'none';
                sun.style.display = 'block';
            } else {
                moon.style.display = 'block';
                sun.style.display = 'none';
            }
            // 标签随当前主题切换：暗色时提示切到白天，亮色时提示切到黑夜
            const label = document.querySelector('#theme-toggle-btn .side-pill-text');
            if (label) {
                const key = dark ? 'common.lightMode' : 'common.darkMode';
                label.dataset.i18n = key;
                if (window.StudioI18n) label.textContent = window.StudioI18n.t(key);
            }
        }

        function toggleTheme() {
            const current = window.StudioTheme ? window.StudioTheme.get() : 'light';
            broadcastTheme(current === 'dark' ? 'light' : 'dark');
        }

        function toggleLanguage() {
            if(!window.StudioI18n) return;
            window.StudioI18n.toggle();
            document.querySelectorAll('iframe').forEach(frame => syncLanguageToFrame(frame));
            updateProjectUpdateTitle();
            refreshUpdateButtonText();
            refreshProjectUpdateModalText();
        }

        function syncLanguageToFrame(frame) {
            if(!window.StudioI18n) return;
            try {
                frame.contentWindow?.postMessage({ type:'studio-lang', lang:window.StudioI18n.lang() }, '*');
            } catch(e) {}
        }

        function broadcastLanguage() {
            document.querySelectorAll('iframe').forEach(frame => {
                try {
                    frame.contentWindow?.postMessage({ type:'studio-lang', lang:window.StudioI18n.lang() }, '*');
                } catch(e) {}
            });
        }

        // listen for theme changes triggered by theme.js
        window.addEventListener('studio-theme-change', (e) => {
            updateThemeIcon(e.detail.theme);
        });

        window.addEventListener('studio-ui-scale-change', () => {
            broadcastScaleToFrames();
        });

        // init icon state on load
        window.addEventListener('DOMContentLoaded', () => {
            const theme = window.StudioTheme ? window.StudioTheme.get() : 'light';
            updateThemeIcon(theme);
            if(window.StudioI18n) window.StudioI18n.apply();
            broadcastLanguage();
            const sidebar = document.getElementById('studioSidebar');
            if(sidebar) {
                sidebar.addEventListener('mouseenter', () => pauseScaleInFrames());
                sidebar.addEventListener('mouseleave', () => pauseScaleInFrames());
            }
            checkForUpdates();
        });

        // sync theme when iframe loads
        document.querySelectorAll('iframe').forEach(f => {
            f.addEventListener('load', () => {
                syncThemeToFrame(f);
                syncLanguageToFrame(f);
                syncScaleToFrame(f);
            });
        });

        function openProjectPage() {
            window.open(appInfo.repo_url || PROJECT_URL, '_blank', 'noopener');
        }

        function versionParts(value) {
            return String(value || '').match(/\d+/g)?.map(Number) || [];
        }

        function compareVersions(a, b) {
            const aa = versionParts(a);
            const bb = versionParts(b);
            const len = Math.max(aa.length, bb.length);
            for(let i = 0; i < len; i++){
                const diff = (aa[i] || 0) - (bb[i] || 0);
                if(diff) return diff;
            }
            return String(a || '').trim() === String(b || '').trim() ? 0 : 1;
        }

        function compactVersion(value) {
            const text = String(value || '').trim();
            const parts = text.match(/\d+/g) || [];
            if(parts.length >= 3) return `${parts[1]}.${parts[2]}`;
            return text.replace(/^v/i, '') || '-';
        }

        function versionLabel(value, mode = 'full') {
            const text = String(value || '').trim();
            if(!text) return 'v-';
            return mode === 'compact' ? `v${compactVersion(text)}` : `v${text.replace(/^v/i, '')}`;
        }

        function setProjectVersionBadge(version) {
            const badge = document.getElementById('project-version-badge');
            if(!badge) return;
            const full = versionLabel(version);
            badge.replaceChildren();
            if(version) {
                const compactSpan = document.createElement('span');
                compactSpan.className = 'project-version-compact';
                compactSpan.textContent = versionLabel(version, 'compact');
                const fullSpan = document.createElement('span');
                fullSpan.className = 'project-version-full';
                fullSpan.textContent = full;
                badge.append(compactSpan, fullSpan);
            } else {
                badge.textContent = 'v-';
            }
            badge.title = window.StudioI18n?.lang?.() === 'en'
                ? `Current version: ${full}`
                : `当前版本：${full}`;
        }

        function refreshUpdateButtonText() {
            const btn = document.getElementById('update-now-btn');
            const text = document.getElementById('update-now-text');
            if(!btn || !text || !btn.classList.contains('show')) return;
            const remoteVersion = document.getElementById('github-entry-btn')?.dataset.remoteVersion || '';
            const isEn = window.StudioI18n?.lang?.() === 'en';
            text.removeAttribute('data-i18n');
            if(remoteVersion) {
                const prefix = isEn ? 'Update to' : '更新到';
                text.replaceChildren();
                const prefixSpan = document.createElement('span');
                prefixSpan.className = 'update-action-prefix';
                prefixSpan.textContent = `${prefix} `;
                const compactSpan = document.createElement('span');
                compactSpan.className = 'update-version-compact';
                compactSpan.textContent = versionLabel(remoteVersion, 'compact');
                const fullSpan = document.createElement('span');
                fullSpan.className = 'update-version-full';
                fullSpan.textContent = versionLabel(remoteVersion);
                text.append(prefixSpan, compactSpan, fullSpan);
                btn.setAttribute('aria-label', `${prefix} ${versionLabel(remoteVersion)}`);
            } else {
                text.textContent = isEn ? 'Update' : '一键更新';
                btn.setAttribute('aria-label', text.textContent);
            }
        }

        function updateProjectUpdateTitle() {
            const gitBtn = document.getElementById('github-entry-btn');
            setProjectVersionBadge(appInfo.version || gitBtn?.dataset.localVersion || '');
            if(!gitBtn?.classList.contains('update-available')) return;
            const remoteVersion = gitBtn.dataset.remoteVersion || '';
            const isEn = window.StudioI18n?.lang?.() === 'en';
            gitBtn.title = isEn
                ? `Current ${versionLabel(gitBtn.dataset.localVersion || appInfo.version)} · latest ${versionLabel(remoteVersion)}`
                : `当前 ${versionLabel(gitBtn.dataset.localVersion || appInfo.version)} · 最新 ${versionLabel(remoteVersion)}`;
            const updateBtn = document.getElementById('update-now-btn');
            if(updateBtn) updateBtn.title = remoteVersion
                ? (isEn ? `Update to ${versionLabel(remoteVersion)}` : `更新到 ${versionLabel(remoteVersion)}`)
                : (isEn ? 'Update main.py and static files from GitHub' : '从 GitHub 更新 main.py 和 static 文件');
            refreshUpdateButtonText();
        }

        function showUpdateNotice(localVersion, remoteVersion) {
            const gitBtn = document.getElementById('github-entry-btn');
            if(!gitBtn) return;
            gitBtn.classList.add('update-available');
            gitBtn.dataset.localVersion = localVersion || '';
            gitBtn.dataset.remoteVersion = remoteVersion || '';
            document.getElementById('update-now-btn')?.classList.add('show');
            updateProjectUpdateTitle();
        }

        function setProjectUpdateNotes(notes) {
            projectUpdateNotes = notes && typeof notes === 'object' ? notes : null;
            renderProjectUpdateNotes();
        }

        function renderProjectUpdateNotes() {
            const box = document.getElementById('project-update-notes');
            if(!box) return;
            const titleEl = document.getElementById('project-update-notes-title');
            const versionEl = document.getElementById('project-update-notes-version');
            const list = document.getElementById('project-update-notes-list');
            const empty = document.getElementById('project-update-notes-empty');
            const isEn = window.StudioI18n?.lang?.() === 'en';
            const notes = projectUpdateNotes || {};
            const items = Array.isArray(notes.items) ? notes.items.filter(Boolean) : [];
            if(titleEl) titleEl.textContent = isEn ? 'What changed' : '本次更新内容';
            if(versionEl) versionEl.textContent = notes.version ? versionLabel(notes.version) : '';
            if(list) {
                list.replaceChildren();
                items.slice(0, 8).forEach(item => {
                    const text = typeof item === 'string' ? item : item.text;
                    if(!text) return;
                    const li = document.createElement('li');
                    li.textContent = String(text);
                    list.append(li);
                });
            }
            const hasItems = !!(list && list.children.length);
            if(empty) {
                empty.hidden = hasItems;
                empty.textContent = isEn ? 'No update notes were found for this version.' : '暂未获取到这个版本的更新说明。';
            }
            box.hidden = !(notes.version || hasItems);
        }

        function describeNetworkError(err, isEn){
            const msg = String(err?.message || err || '');
            const isNetwork = (err instanceof TypeError) || /Failed to fetch|NetworkError|ERR_|timed? ?out|超时|无法连接|GitHub|HTTP 4|HTTP 5/i.test(msg);
            if(isNetwork){
                return isEn
                    ? 'Cannot reach the selected update source. Check your network, proxy, or DNS, then try again.'
                    : '无法连接当前选择的更新源。请检查网络、代理或 DNS 后重试。';
            }
            return msg || (isEn ? 'Update failed' : '更新失败');
        }

        function updateUiText(zh, en) {
            return window.StudioI18n?.lang?.() === 'en' ? en : zh;
        }

        function updateSourceLabel(source = updateSource) {
            return source === 'modelscope' ? 'ModelScope' : 'GitHub';
        }

        function setUpdateSource(source) {
            updateSource = source === 'modelscope' ? 'modelscope' : 'github';
            localStorage.setItem('studio_update_source', updateSource);
            refreshProjectUpdateModalText();
        }

        function sourceConnectivityStats(source, results = []) {
            const sourceItems = (results || []).filter(item => item.source === source);
            const required = sourceItems.filter(item => item.required);
            const okRequired = required.length ? required.every(item => item.ok) : false;
            const okItems = sourceItems.filter(item => item.ok);
            const avg = okItems.length
                ? Math.round(okItems.reduce((sum, item) => sum + Number(item.elapsed_ms || 0), 0) / okItems.length)
                : 999999;
            return {source, ok:okRequired, avg, okItems:okItems.length, total:sourceItems.length};
        }

        function bestUpdateSourceFromConnectivity(data) {
            const results = data?.results || [];
            const github = sourceConnectivityStats('github', results);
            const ms = sourceConnectivityStats('modelscope', results);
            if(github.ok && ms.ok) return ms.avg < github.avg ? 'modelscope' : 'github';
            if(ms.ok) return 'modelscope';
            if(github.ok) return 'github';
            return updateSource;
        }

        function updateTargetLabel(name) {
            const labels = {
                'GitHub 更新列表': ['GitHub 更新列表', 'GitHub update API'],
                'GitHub 版本文件': ['GitHub 版本文件', 'GitHub version file'],
                'GitHub 主页': ['GitHub 主页', 'GitHub home page'],
                'ModelScope 更新列表': ['ModelScope 更新列表', 'ModelScope update list'],
                'ModelScope 版本文件': ['ModelScope 版本文件', 'ModelScope version file'],
                'ModelScope 空间页面': ['ModelScope 空间页面', 'ModelScope space page'],
                'ModelScope 主页': ['ModelScope 主页', 'ModelScope home page'],
                'Google 连通性': ['Google 连通性', 'Google connectivity'],
            };
            const item = labels[name] || [name, name];
            return window.StudioI18n?.lang?.() === 'en' ? item[1] : item[0];
        }

        function updateStatusLabel(item) {
            if(item.pending) return updateUiText('检测中...', 'Testing...');
            if(item.ok) return `${updateUiText('正常', 'OK')} · ${item.elapsed_ms || 0}ms`;
            if(item.timed_out) return updateUiText('失败 · 超时', 'Failed · timeout');
            if(item.status) return `HTTP ${item.status}`;
            return updateUiText('失败', 'Failed');
        }

        function setUpdateSummary(kind, title, text) {
            const box = document.getElementById('project-update-summary');
            const titleEl = document.getElementById('project-update-summary-title');
            const textEl = document.getElementById('project-update-summary-text');
            if(box) {
                box.classList.remove('ok', 'warn', 'fail');
                box.classList.add(kind || 'warn');
            }
            if(titleEl) titleEl.textContent = title;
            if(textEl) textEl.textContent = text;
        }

        function updateConnectivityTargets() {
            const sources = appInfo.sources || {};
            const github = sources.github || {};
            const ms = sources.modelscope || {};
            return [
                { name:'GitHub 更新列表', url:github.tree_url || appInfo.tree_url || 'https://api.github.com/repos/hero8152/Infinite-Canvas/git/trees/main?recursive=1', source:'github', required:true },
                { name:'GitHub 版本文件', url:github.version_url || appInfo.version_url || 'https://raw.githubusercontent.com/hero8152/Infinite-Canvas/main/VERSION', source:'github', required:true },
                { name:'GitHub 主页', url:'https://github.com/', source:'github' },
                { name:'ModelScope 版本文件', url:ms.version_url || 'https://www.modelscope.cn/api/v1/studio/Daniel8152/Infinite-Canvas/repo?Revision=master&FilePath=VERSION', source:'modelscope', required:true },
                { name:'ModelScope 空间页面', url:ms.repo_url || 'https://modelscope.cn/studios/Daniel8152/Infinite-Canvas', source:'modelscope' },
                { name:'ModelScope 主页', url:'https://modelscope.cn/', source:'modelscope' },
                { name:'Google 连通性', url:'https://www.google.com/generate_204', source:'reference' },
            ];
        }

        function renderConnectivityList(results = []) {
            const allItems = results.length ? results : updateConnectivityTargets().map(item => ({...item, pending:false, untouched:true}));
            const renderInto = (list, source) => {
                if(!list) return;
                list.replaceChildren();
                const items = allItems.filter(item => item.source === source || (source === 'github' && item.source === 'reference'));
                items.forEach(item => {
                const row = document.createElement('div');
                row.className = `connectivity-row ${item.pending ? 'pending' : item.untouched ? '' : item.ok ? 'ok' : 'fail'}`;
                const indicator = document.createElement('span');
                indicator.className = 'connectivity-indicator';
                const meta = document.createElement('div');
                const name = document.createElement('div');
                name.className = 'connectivity-name';
                name.textContent = updateTargetLabel(item.name);
                const url = document.createElement('div');
                url.className = 'connectivity-url';
                url.textContent = item.url || '';
                meta.append(name, url);
                const status = document.createElement('div');
                status.className = 'connectivity-status';
                status.textContent = item.untouched ? updateUiText('待测试', 'Not tested') : updateStatusLabel(item);
                row.append(indicator, meta, status);
                if(item.error && !item.timed_out) {
                    const error = document.createElement('div');
                    error.className = 'connectivity-error';
                    error.textContent = String(item.error).slice(0, 220);
                    row.append(error);
                }
                list.append(row);
            });
            };
            renderInto(document.querySelector('[data-connectivity-source="github"]'), 'github');
            renderInto(document.querySelector('[data-connectivity-source="modelscope"]'), 'modelscope');
        }

        function refreshProjectUpdateModalText() {
            const gitBtn = document.getElementById('github-entry-btn');
            const remoteVersion = gitBtn?.dataset.remoteVersion || '';
            const localVersion = gitBtn?.dataset.localVersion || appInfo.version || '';
            const sourceName = updateSourceLabel();
            const title = remoteVersion
                ? updateUiText(`更新到 ${versionLabel(remoteVersion)}`, `Update to ${versionLabel(remoteVersion)}`)
                : updateUiText('一键更新', 'One-click update');
            const titleEl = document.getElementById('project-update-title');
            const copyEl = document.getElementById('project-update-copy');
            const testText = document.getElementById('connectivity-test-text');
            const cancelText = document.getElementById('project-update-cancel-text');
            const confirmText = document.getElementById('project-update-confirm-text');
            const closeBtn = document.querySelector('#project-update-modal .studio-modal-close');
            if(titleEl) titleEl.textContent = title;
            renderProjectUpdateNotes();
            document.querySelectorAll('[data-update-source]').forEach(card => {
                const source = card.dataset.updateSource || 'github';
                const active = source === updateSource;
                card.classList.toggle('active', active);
                card.setAttribute('aria-pressed', active ? 'true' : 'false');
                const badge = card.querySelector('.update-source-badge');
                if(badge) {
                    if(!updateConnectivityResult) {
                        setSourceBadge(badge, '', updateUiText('待测试', 'Not tested'));
                    } else {
                        const stats = sourceConnectivityStats(source, updateConnectivityResult.results || []);
                        setSourceBadge(badge, stats.ok ? 'ok' : 'bad',
                            stats.ok ? updateUiText('可用', 'Available') : updateUiText('不可用', 'Unavailable'));
                    }
                }
            });
            if(copyEl) copyEl.textContent = updateUiText(
                `将从 ${sourceName} 更新 main.py、VERSION 和 static 文件。更新前会自动备份，更新完成后后端会自动重启。当前 ${versionLabel(localVersion)}，最新 ${versionLabel(remoteVersion || localVersion)}。`,
                `This updates main.py, VERSION, and static files from ${sourceName}. A backup is created first, then the backend restarts automatically. Current ${versionLabel(localVersion)}, latest ${versionLabel(remoteVersion || localVersion)}.`
            );
            if(testText) testText.textContent = updateConnectivityResult ? updateUiText('重新测试', 'Retest') : updateUiText('测试连通性', 'Test connectivity');
            if(cancelText) cancelText.textContent = updateUiText('取消', 'Cancel');
            if(confirmText && !projectUpdateRunning) confirmText.textContent = updateUiText('开始更新', 'Start update');
            if(closeBtn) {
                closeBtn.title = updateUiText('关闭', 'Close');
                closeBtn.setAttribute('aria-label', closeBtn.title);
            }
            if(!updateConnectivityResult) {
                setUpdateSummary(
                    'warn',
                    updateUiText('建议先测试连通性', 'Connectivity test recommended'),
                    updateUiText(
                        '测试会同时测速 GitHub 和 ModelScope。你可以根据结果切换下载源。',
                        'The test checks both GitHub and ModelScope. Choose the faster reachable source before updating.'
                    )
                );
            } else if(updateConnectivityResult.backend_missing) {
                setUpdateSummary(
                    'fail',
                    updateUiText('需要重启后端', 'Backend restart required'),
                    updateUiText(
                        '当前页面已经更新，但后端仍是旧版本，所以找不到连通性测试接口。请重启服务后再试。',
                        'The page is updated, but the backend is still the old version and cannot find the connectivity-test API. Restart the service and try again.'
                    )
                );
            } else if((updateConnectivityResult.sources || {})[updateSource]?.ok || (updateSource === 'github' && updateConnectivityResult.ok)) {
                const google = (updateConnectivityResult.results || []).find(item => item.name === 'Google 连通性');
                const sourceResults = (updateConnectivityResult.results || []).filter(item => item.source === updateSource);
                const fastest = sourceResults.filter(item => item.ok).sort((a, b) => (a.elapsed_ms || 999999) - (b.elapsed_ms || 999999))[0];
                setUpdateSummary(
                    google?.ok ? 'ok' : 'warn',
                    updateUiText(`${sourceName} 下载源可用`, `${sourceName} source reachable`),
                    fastest
                        ? updateUiText(`${sourceName} 可访问，最快节点约 ${fastest.elapsed_ms || 0}ms，可以开始更新。`, `${sourceName} is reachable; fastest endpoint is about ${fastest.elapsed_ms || 0}ms.`)
                        : updateUiText(`${sourceName} 更新节点可用，可以开始更新。`, `${sourceName} update endpoints are reachable.`)
                );
            } else {
                setUpdateSummary(
                    'fail',
                    updateUiText(`${sourceName} 下载源不可用`, `${sourceName} source unreachable`),
                    updateUiText(
                        `当前网络无法访问 ${sourceName} 必需节点。请切换下载源，或检查代理、DNS 后重试。`,
                        `This network cannot reach required ${sourceName} endpoints. Switch source, or check proxy/DNS and try again.`
                    )
                );
            }
            renderConnectivityList(updateConnectivityResult?.results || []);
        }

        function openProjectUpdateModal() {
            const modal = document.getElementById('project-update-modal');
            if(!modal) return;
            updateConnectivityResult = null;
            refreshProjectUpdateModalText();
            modal.hidden = false;
            document.getElementById('connectivity-test-btn')?.focus?.();
        }

        function closeProjectUpdateModal() {
            // 更新进行中允许关闭：中止在途请求并恢复 UI，避免「卡在更新中、无法关闭」
            if(projectUpdateRunning) {
                try { projectUpdateAbort?.abort(); } catch(e) {}
            }
            const modal = document.getElementById('project-update-modal');
            if(modal) modal.hidden = true;
        }

        document.getElementById('project-update-modal')?.addEventListener('click', event => {
            if(event.target?.id === 'project-update-modal') closeProjectUpdateModal();
        });

        window.addEventListener('keydown', event => {
            if(event.key === 'Escape') closeProjectUpdateModal();
        });

        async function runProjectUpdate() {
            openProjectUpdateModal();
        }

        function computeConnectivitySources(results) {
            const out = {};
            for(const source of ['github', 'modelscope']) {
                const reqAll = (results || []).filter(it => it.source === source && it.required);
                out[source] = {
                    ok: reqAll.length > 0 && reqAll.every(it => it.ok),
                    required: reqAll.map(it => it.name),
                };
            }
            return out;
        }

        function setSourceBadge(badge, state, text) {
            if(!badge) return;
            badge.classList.remove('ok', 'bad');
            if(state) badge.classList.add(state);
            badge.textContent = text;
        }

        function renderSourceBadgesLive(results) {
            document.querySelectorAll('[data-update-source]').forEach(card => {
                const source = card.dataset.updateSource || 'github';
                const badge = card.querySelector('.update-source-badge');
                if(!badge) return;
                const items = (results || []).filter(it => it.source === source);
                if(!items.length) return;
                const done = items.filter(it => !it.pending && !it.untouched);
                if(done.length < items.length) {
                    setSourceBadge(badge, '', updateUiText(`检测中 ${done.length}/${items.length}`, `${done.length}/${items.length}`));
                    return;
                }
                const stats = sourceConnectivityStats(source, results);
                setSourceBadge(badge, stats.ok ? 'ok' : 'bad',
                    stats.ok ? updateUiText('可用', 'Available') : updateUiText('不可用', 'Unavailable'));
            });
        }

        let connectivityTesting = false;
        async function runUpdateConnectivityTest() {
            if(connectivityTesting) return; // 防止重复点击导致状态错乱
            const isEn = window.StudioI18n?.lang?.() === 'en';
            const btn = document.getElementById('connectivity-test-btn');
            const text = document.getElementById('connectivity-test-text');
            connectivityTesting = true;
            if(btn) btn.disabled = true;
            if(text) text.textContent = isEn ? 'Testing...' : '检测中...';
            updateConnectivityResult = null;

            const targets = updateConnectivityTargets();
            // 实时状态数组：先全部置为「检测中」，每条探测完成立即刷新对应行
            const live = targets.map(item => ({...item, pending:true, untouched:false}));
            let backendMissing = false;
            const applyResult = (name, patch) => {
                const i = live.findIndex(x => x.name === name);
                if(i < 0) return;
                live[i] = {...live[i], pending:false, untouched:false, ...patch};
                renderConnectivityList(live);
                renderSourceBadgesLive(live);
            };

            const probeOne = async (t) => {
                // 客户端兜底超时：5s 探测 + 1s 网络余量，超时即报「超时」，不会永远卡在「检测中」
                const ac = new AbortController();
                const killer = setTimeout(() => ac.abort(), 6000);
                try {
                    const res = await fetch(`/api/update-connectivity/probe?name=${encodeURIComponent(t.name)}`, { cache:'no-store', signal:ac.signal });
                    const data = await res.json().catch(() => ({}));
                    // 旧后端没有单条探测接口 → 404 Not Found，标记后回退到整体接口
                    if(res.status === 404 && (data.detail === 'Not Found' || data.detail === undefined)) {
                        backendMissing = true;
                        return;
                    }
                    if(res.ok) {
                        applyResult(t.name, { ok:!!data.ok, status:data.status || 0, elapsed_ms:data.elapsed_ms || 0, error:data.error || '', timed_out:!!data.timed_out });
                    } else {
                        applyResult(t.name, { ok:false, error:data.detail || (isEn ? 'Failed' : '失败') });
                    }
                } catch(e) {
                    if(e && e.name === 'AbortError') {
                        applyResult(t.name, { ok:false, timed_out:true, error:isEn ? 'Timed out (over 5s)' : '连接超时（超过 5s）' });
                    } else {
                        applyResult(t.name, { ok:false, error:describeNetworkError(e, isEn) });
                    }
                } finally {
                    clearTimeout(killer);
                }
            };

            try {
                setUpdateSummary('warn', isEn ? 'Testing connectivity' : '正在测试连通性', isEn ? 'Probing each endpoint — results stream in live.' : '正在逐条检测各节点，结果实时显示。');
                renderConnectivityList(live);
                renderSourceBadgesLive(live);
                await Promise.all(targets.map(probeOne));

                if(backendMissing) {
                    // 兜底：尝试旧的整体接口
                    try {
                        const res = await fetch('/api/update-connectivity', { cache:'no-store' });
                        const data = await res.json().catch(() => ({}));
                        if(res.ok && Array.isArray(data.results)) {
                            updateConnectivityResult = data;
                            setUpdateSource(bestUpdateSourceFromConnectivity(data));
                            return;
                        }
                    } catch(e) {}
                    const message = isEn
                        ? 'The backend has not loaded the new connectivity-test API yet. Restart the backend service, then test again.'
                        : '后端还没有加载新的连通性测试接口。请重启服务后再测试。';
                    updateConnectivityResult = {
                        ok:false,
                        backend_missing:true,
                        results:targets.map(item => ({...item, ok:false, elapsed_ms:0, error:message })),
                    };
                    return;
                }

                const results = live.map(({pending, untouched, ...rest}) => rest);
                const sources = computeConnectivitySources(results);
                updateConnectivityResult = { results, sources, ok:sources.github.ok };
                setUpdateSource(bestUpdateSourceFromConnectivity(updateConnectivityResult));
            } finally {
                connectivityTesting = false;
                if(btn) btn.disabled = false;
                refreshProjectUpdateModalText();
            }
        }

        async function confirmProjectUpdate() {
            const isEn = window.StudioI18n?.lang?.() === 'en';
            const btn = document.getElementById('update-now-btn');
            const text = document.getElementById('update-now-text');
            const confirmBtn = document.getElementById('project-update-confirm-btn');
            const confirmText = document.getElementById('project-update-confirm-text');
            const testBtn = document.getElementById('connectivity-test-btn');
            const oldText = text?.textContent || '';
            projectUpdateRunning = true;
            if(btn) btn.disabled = true;
            if(confirmBtn) confirmBtn.disabled = true;
            if(testBtn) testBtn.disabled = true;
            if(text) text.textContent = isEn ? 'Updating...' : '更新中...';
            if(confirmText) confirmText.textContent = isEn ? 'Updating...' : '更新中...';
            const sourceName = updateSourceLabel();
            setUpdateSummary('warn', isEn ? 'Updating' : '正在更新', isEn ? `Downloading files from ${sourceName} and creating a local backup.` : `正在从 ${sourceName} 下载文件，并创建本地备份。`);
            // 客户端兜底超时：即使后端异常挂起，UI 也能恢复，不会永远停在「更新中」
            const ac = new AbortController();
            const killer = setTimeout(() => ac.abort(), 300000);
            try {
                const res = await fetch('/api/update-from-github', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({ auto_restart:true, restart_delay:3, source:updateSource, fallback:true }),
                    signal:ac.signal
                });
                const data = await res.json().catch(() => ({}));
                if(!res.ok) throw new Error(data.detail || (isEn ? 'Update failed' : '更新失败'));
                if(data.update_notes) setProjectUpdateNotes(data.update_notes);
                const restarting = data.restart_scheduled;
                const usedLabel = data.source_label || (data.source === 'modelscope' ? 'ModelScope' : 'GitHub');
                const fallbackNote = data.fallback_used
                    ? (isEn
                        ? ` (${sourceName} was unreachable, so it fell back to ${usedLabel})`
                        : `（${sourceName} 不可用，已自动兜底切换到 ${usedLabel}）`)
                    : '';
                setUpdateSummary(
                    'ok',
                    isEn ? 'Update complete' : '更新完成',
                    (restarting
                        ? (isEn
                            ? `Updated ${data.count || 0} files. The backend will restart in about 3 seconds; this page will reload when it returns.`
                            : `已更新 ${data.count || 0} 个文件。后端将在约 3 秒后自动重启，本页面会在恢复后自动刷新。`)
                        : (isEn
                            ? `Updated ${data.count || 0} files. Please restart the backend, then refresh this page.`
                            : `已更新 ${data.count || 0} 个文件。请重启后端，然后刷新页面。`)) + fallbackNote
                );
                document.getElementById('github-entry-btn')?.classList.remove('update-available');
                btn?.classList.remove('show');
                setProjectVersionBadge(data.version || document.getElementById('github-entry-btn')?.dataset.remoteVersion || appInfo.version);
                if(restarting) waitForBackendAndReload();
            } catch(e) {
                const msg = (e && e.name === 'AbortError')
                    ? (isEn ? 'Update timed out. Switch source or check your network, then retry.' : '更新超时。请切换下载源或检查网络后重试。')
                    : describeNetworkError(e, isEn);
                setUpdateSummary('fail', isEn ? 'Update failed' : '更新失败', msg);
            } finally {
                clearTimeout(killer);
                projectUpdateRunning = false;
                if(btn) btn.disabled = false;
                if(confirmBtn) confirmBtn.disabled = false;
                if(testBtn) testBtn.disabled = false;
                if(text) text.textContent = oldText || (isEn ? 'Update' : '一键更新');
                if(confirmText) confirmText.textContent = isEn ? 'Start update' : '开始更新';
                refreshUpdateButtonText();
            }
        }
        async function waitForBackendAndReload() {
            const deadline = Date.now() + 90 * 1000;
            await new Promise(r => setTimeout(r, 4000));
            while(Date.now() < deadline) {
                try {
                    const r = await fetch('/api/app-info', { cache:'no-store' });
                    if(r.ok) { location.reload(); return; }
                } catch {}
                await new Promise(r => setTimeout(r, 1500));
            }
        }
        async function rollbackProjectUpdate() {
            const isEn = window.StudioI18n?.lang?.() === 'en';
            try {
                const list = await fetch('/api/update-backups').then(r => r.json());
                const backups = list.backups || [];
                if(!backups.length){ alert(isEn ? 'No backups available.' : '没有可用的备份'); return; }
                const lines = backups.slice(0, 8).map((b, i) => {
                    const d = new Date((b.created_at || 0) * 1000);
                    const ts = d.toLocaleString();
                    return `${i + 1}. ${b.name}  (${b.file_count} files, ${ts})`;
                });
                const promptMsg = (isEn
                    ? 'Select a backup to restore (enter the number):\n'
                    : '选择要还原的备份（输入序号）：\n') + lines.join('\n');
                const answer = prompt(promptMsg, '1');
                const idx = Number(answer) - 1;
                if(!(idx >= 0 && idx < backups.length)) return;
                const target = backups[idx];
                if(!confirm(isEn ? `Restore "${target.name}"? Backend will restart.` : `要还原 "${target.name}" 吗？后端会自动重启。`)) return;
                const res = await fetch('/api/update-rollback', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({ name:target.name, auto_restart:true, restart_delay:3 })
                });
                const data = await res.json().catch(() => ({}));
                if(!res.ok) throw new Error(data.detail || (isEn ? 'Rollback failed' : '回滚失败'));
                alert(isEn
                    ? `Restored ${data.count || 0} files. Backend is restarting.`
                    : `已还原 ${data.count || 0} 个文件。后端正在重启。`);
                if(data.restart_scheduled) waitForBackendAndReload();
            } catch(e) {
                alert((isEn ? 'Rollback failed: ' : '回滚失败：') + describeNetworkError(e, isEn));
            }
        }
        window.rollbackProjectUpdate = rollbackProjectUpdate;

        async function checkForUpdates(manual = false) {
            const isEn = window.StudioI18n?.lang?.() === 'en';
            const badge = document.getElementById('project-version-badge');
            if(manual && badge) badge.classList.add('checking');
            try {
                const info = await fetch('/api/app-info', { cache:'no-store' }).then(r => r.json()).catch(() => ({}));
                appInfo = {...appInfo, ...info};
                let current = String(appInfo.version || '').trim();
                setProjectVersionBadge(current);
                let best = null;
                let reachable = false;
                let serverChecked = false;
                // 优先走后端检测：服务端用系统代理同时检测 GitHub 和 ModelScope，避免浏览器跨域/被墙
                try {
                    const r = await fetch('/api/check-update', { cache:'no-store' });
                    if(r.ok) {
                        const d = await r.json();
                        serverChecked = true;
                        reachable = !!d.reachable;
                        if(d.current) { current = String(d.current).trim(); setProjectVersionBadge(current); }
                        if(d.latest?.version) best = {source:d.latest.source, version:d.latest.version, update_notes:d.latest.update_notes || d.update_notes || null};
                    }
                } catch(e) {}
                // 兜底：旧后端无 /api/check-update 时，浏览器直接拉取双源 VERSION
                if(!serverChecked) {
                    const sources = appInfo.sources || {};
                    const candidates = [
                        {source:'github', url:sources.github?.version_url || appInfo.version_url || ''},
                        {source:'modelscope', url:sources.modelscope?.version_url || ''},
                    ].filter(item => item.url);
                    for(const item of candidates) {
                        try {
                            const remoteText = await fetch(`${item.url}${item.url.includes('?') ? '&' : '?'}t=${Date.now()}`, { cache:'no-store' }).then(r => r.ok ? r.text() : '');
                            const remote = String(remoteText || '').trim().split(/\r?\n/)[0].trim();
                            if(remote){ reachable = true; if(!best || compareVersions(remote, best.version) > 0) best = {source:item.source, version:remote}; }
                        } catch(e) {}
                    }
                }
                const hasUpdate = !!(current && best?.version && compareVersions(best.version, current) > 0);
                if(hasUpdate) {
                    if(best.source === 'modelscope') setUpdateSource('modelscope');
                    setProjectUpdateNotes(best.update_notes || null);
                    showUpdateNotice(current, best.version);
                }
                if(manual) {
                    if(hasUpdate) {
                        openProjectUpdateModal();
                    } else if(reachable) {
                        alert(isEn ? `You are on the latest version (${versionLabel(current)}).` : `已是最新版本（${versionLabel(current)}）。`);
                    } else {
                        alert(isEn ? 'Could not reach GitHub or ModelScope. Check your network/proxy and try again.' : '无法连接 GitHub 或 ModelScope 更新源，请检查网络或代理后重试。');
                    }
                }
            } catch(e) {
                // 离线包里没有网络时保持安静，不影响本地使用。
                if(manual) alert(isEn ? 'Update check failed.' : '检测更新失败。');
            } finally {
                if(badge) badge.classList.remove('checking');
            }
        }
