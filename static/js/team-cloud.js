(function(){
    const $ = (id) => document.getElementById(id);
    const TEAM_CLOUD_MODE_KEY = "teamCloudMode";
    const TEAM_CLOUD_TEAM_KEY = "teamCloudCurrentTeamId";
    const TEAM_CLOUD_PROJECT_KEY = "teamCloudCurrentProjectId";
    const TEAM_CLOUD_ACCESS_TOKEN_KEY = "teamCloudAccessToken";

    const state = {
        mode: "login",
        user: null,
        teams: [],
        projects: [],
        canvases: [],
        apiProviders: [],
        apiCatalogProviders: [],
        generationLogs: [],
        generationSummary: null,
        selectedTeamId: "",
        selectedProjectId: "",
        selectedCanvasId: "",
        selectedApiProviderId: "",
        canvasVersions: [],
        config: null,
    };

    const TEAM_API_PROVIDER_PRESETS = [
        { provider_id: "modelscope", label: "ModelScope", protocol: "openai", base_url: "https://api-inference.modelscope.cn/v1" },
        { provider_id: "runninghub", label: "RunningHub", protocol: "runninghub", base_url: "https://www.runninghub.cn" },
        { provider_id: "volcengine", label: "火山引擎", protocol: "volcengine", base_url: "https://ark.cn-beijing.volces.com/api/v3" },
        { provider_id: "openai", label: "API", protocol: "openai", base_url: "" },
    ];

    function iconRefresh(){
        if(window.lucide && typeof window.lucide.createIcons === "function"){
            window.lucide.createIcons();
        }
    }

    function applyTheme(theme){
        const dark = theme === "dark";
        document.documentElement.classList.toggle("studio-theme-dark", dark);
        document.documentElement.classList.toggle("theme-dark", dark);
        document.body?.classList.toggle("studio-theme-dark", dark);
        document.body?.classList.toggle("theme-dark", dark);
    }

    function setMessage(el, text, type){
        el.textContent = text || "";
        el.classList.remove("error", "ok");
        if(type) el.classList.add(type);
    }

    function setBusy(button, busy){
        if(!button) return;
        button.disabled = !!busy;
    }

    function storedAccessToken(){
        try {
            return localStorage.getItem(TEAM_CLOUD_ACCESS_TOKEN_KEY) || "";
        } catch(e) {
            return "";
        }
    }

    function storeAccessToken(token){
        try {
            if(token) localStorage.setItem(TEAM_CLOUD_ACCESS_TOKEN_KEY, token);
            else localStorage.removeItem(TEAM_CLOUD_ACCESS_TOKEN_KEY);
        } catch(e) {}
    }

    async function api(path, options){
        const token = storedAccessToken();
        const headers = {
            "Content-Type": "application/json",
            ...(options && options.headers ? options.headers : {}),
        };
        if(token && !headers.Authorization && !headers.authorization){
            headers.Authorization = `Bearer ${token}`;
        }
        const response = await fetch(`/api/team-cloud${path}`, {
            ...options,
            credentials: "include",
            headers,
        });
        let data = null;
        try {
            data = await response.json();
        } catch(e) {
            data = {};
        }
        if(!response.ok){
            throw new Error(apiErrorMessage(data));
        }
        return data;
    }

    function apiErrorMessage(data){
        const detail = data && data.detail;
        if(detail && typeof detail === "object"){
            return detail.message || data.message || "请求失败";
        }
        return detail || (data && data.message) || "请求失败";
    }

    function updateStatus(){
        const el = $("systemStatus");
        const cfg = state.config || {};
        el.classList.remove("ok", "warn");
        if(cfg.dev_bypass){
            el.classList.add("warn");
            el.innerHTML = '<i data-lucide="badge-alert" width="16" height="16"></i><span>本地模式</span>';
        } else if(cfg.supabase_ready && cfg.auth_ready) {
            el.classList.add("ok");
            el.innerHTML = '<i data-lucide="badge-check" width="16" height="16"></i><span>云端已配置</span>';
        } else {
            el.classList.add("warn");
            el.innerHTML = '<i data-lucide="badge-alert" width="16" height="16"></i><span>等待配置</span>';
        }
        iconRefresh();
    }

    function renderAuth(){
        const signedIn = !!state.user;
        $("signedOut").hidden = signedIn;
        $("signedIn").hidden = !signedIn;
        $("logoutBtn").hidden = !signedIn;
        $("teamForm").querySelectorAll("input,button").forEach((item) => item.disabled = !signedIn);
        $("inviteForm").querySelectorAll("input,select,button").forEach((item) => item.disabled = !signedIn || !state.selectedTeamId);
        $("projectForm").querySelectorAll("input,button").forEach((item) => item.disabled = !signedIn || !state.selectedTeamId);
        $("canvasForm").querySelectorAll("input,button").forEach((item) => item.disabled = !signedIn || !state.selectedProjectId);
        $("apiProviderForm").querySelectorAll("input,select,button").forEach((item) => item.disabled = !signedIn || !state.selectedTeamId);
        ["apiProviderAdd", "apiProviderRecommend", "apiProviderDelete", "apiProviderSubmit", "apiProviderClearKey"].forEach((id) => {
            const item = $(id);
            if(item) item.disabled = !signedIn || !state.selectedTeamId;
        });

        if(signedIn){
            $("userLine").textContent = state.user.email || state.user.id;
            $("signedInName").textContent = state.user.email || state.user.id;
            $("signedInProvider").textContent = state.user.provider === "dev-bypass" ? "本地开发用户" : "Supabase 用户";
        } else {
            $("userLine").textContent = "未登录";
        }

        $("loginTab").classList.toggle("active", state.mode === "login");
        $("signupTab").classList.toggle("active", state.mode === "signup");
        $("loginTab").setAttribute("aria-selected", state.mode === "login" ? "true" : "false");
        $("signupTab").setAttribute("aria-selected", state.mode === "signup" ? "true" : "false");
        $("authSubmit").innerHTML = state.mode === "login"
            ? '<i data-lucide="log-in" width="16" height="16"></i><span>登录</span>'
            : '<i data-lucide="user-plus" width="16" height="16"></i><span>注册</span>';
        $("password").autocomplete = state.mode === "login" ? "current-password" : "new-password";
        iconRefresh();
    }

    function renderTeams(){
        const list = $("teamList");
        list.innerHTML = "";
        if(!state.user){
            list.innerHTML = '<div class="empty">登录后显示团队</div>';
            $("memberList").innerHTML = '<div class="empty">选择团队后显示成员</div>';
            return;
        }
        if(!state.teams.length){
            list.innerHTML = '<div class="empty">还没有团队</div>';
            $("memberList").innerHTML = '<div class="empty">创建团队后显示成员</div>';
            return;
        }

        state.teams.forEach((team) => {
            const item = document.createElement("div");
            item.tabIndex = 0;
            item.setAttribute("role", "button");
            item.className = `team-item${team.id === state.selectedTeamId ? " active" : ""}`;
            item.innerHTML = `
                <span>
                    <span class="name">${escapeHtml(team.name)}</span>
                    <span class="meta">${escapeHtml(team.id)}</span>
                </span>
                <span class="item-actions">
                    <span class="badge">${roleLabel(team.role)}</span>
                    <button class="btn ghost danger" type="button" data-team-delete="${escapeHtml(team.id)}" title="删除团队" aria-label="删除团队">
                        <i data-lucide="trash-2" width="16" height="16"></i>
                    </button>
                </span>
            `;
            item.addEventListener("click", (event) => {
                if(event.target.closest("[data-team-delete]")) return;
                selectTeam(team.id);
            });
            item.addEventListener("keydown", (event) => {
                if(event.target.closest("[data-team-delete]")) return;
                if(event.key === "Enter" || event.key === " "){
                    event.preventDefault();
                    selectTeam(team.id);
                }
            });
            list.appendChild(item);
        });
        iconRefresh();
    }

    function renderMembers(members){
        const list = $("memberList");
        list.innerHTML = "";
        if(!state.selectedTeamId){
            list.innerHTML = '<div class="empty">选择团队后显示成员</div>';
            return;
        }
        if(!members || !members.length){
            list.innerHTML = '<div class="empty">暂无成员</div>';
            return;
        }
        members.forEach((member) => {
            const item = document.createElement("div");
            item.className = "member-item";
            item.innerHTML = `
                <span>
                    <span class="name">${escapeHtml(member.email || member.user_id)}</span>
                    <span class="meta">${escapeHtml(member.user_id || "")}</span>
                </span>
                <span class="badge">${roleLabel(member.role)}</span>
            `;
            list.appendChild(item);
        });
    }

    function renderProjects(){
        const list = $("projectList");
        list.innerHTML = "";
        if(!state.selectedTeamId){
            list.innerHTML = '<div class="empty">选择团队后显示项目</div>';
            $("canvasList").innerHTML = '<div class="empty">选择项目后显示画布</div>';
            return;
        }
        if(!state.projects.length){
            list.innerHTML = '<div class="empty">还没有项目</div>';
            $("canvasList").innerHTML = '<div class="empty">创建项目后显示画布</div>';
            return;
        }
        state.projects.forEach((project) => {
            const item = document.createElement("div");
            item.tabIndex = 0;
            item.setAttribute("role", "button");
            item.className = `team-item${project.id === state.selectedProjectId ? " active" : ""}`;
            item.innerHTML = `
                <span>
                    <span class="name">${escapeHtml(project.name)}</span>
                    <span class="meta">${escapeHtml(project.description || project.id)}</span>
                </span>
                <span class="item-actions">
                    <span class="badge">项目</span>
                    <button class="btn ghost danger" type="button" data-project-delete="${escapeHtml(project.id)}" title="删除项目" aria-label="删除项目">
                        <i data-lucide="trash-2" width="16" height="16"></i>
                    </button>
                </span>
            `;
            item.addEventListener("click", (event) => {
                if(event.target.closest("[data-project-delete]")) return;
                selectProject(project.id);
            });
            item.addEventListener("keydown", (event) => {
                if(event.target.closest("[data-project-delete]")) return;
                if(event.key === "Enter" || event.key === " "){
                    event.preventDefault();
                    selectProject(project.id);
                }
            });
            list.appendChild(item);
        });
        iconRefresh();
    }

    function renderCanvases(){
        const list = $("canvasList");
        list.innerHTML = "";
        if(!state.selectedProjectId){
            list.innerHTML = '<div class="empty">Select a project to view canvases</div>';
            renderCanvasVersions();
            return;
        }
        if(!state.canvases.length){
            list.innerHTML = '<div class="empty">No cloud canvases yet</div>';
            renderCanvasVersions();
            return;
        }
        state.canvases.forEach((canvas) => {
            const item = document.createElement("div");
            item.className = "member-item";
            item.innerHTML = `
                <span>
                    <span class="name">${escapeHtml(canvas.title)}</span>
                    <span class="meta">v${escapeHtml(canvas.version)} ? ${escapeHtml(canvas.id)}</span>
                </span>
                <span class="row">
                    <span class="badge">Canvas</span>
                    <button class="btn ghost" type="button" data-canvas-history="${escapeHtml(canvas.id)}" title="History">
                        <i data-lucide="history" width="16" height="16"></i>
                    </button>
                    <button class="btn ghost danger" type="button" data-canvas-delete="${escapeHtml(canvas.id)}" title="删除画布" aria-label="删除画布">
                        <i data-lucide="trash-2" width="16" height="16"></i>
                    </button>
                </span>
            `;
            list.appendChild(item);
        });
        iconRefresh();
    }

    function renderCanvasVersions(){
        const list = $("canvasVersionList");
        if(!list) return;
        list.innerHTML = "";
        if(!state.selectedCanvasId){
            list.innerHTML = '<div class="empty">Pick a canvas to view versions</div>';
            return;
        }
        if(!state.canvasVersions.length){
            list.innerHTML = '<div class="empty">No versions yet</div>';
            return;
        }
        state.canvasVersions.forEach((version) => {
            const item = document.createElement("div");
            item.className = "member-item";
            const selected = state.canvases.find((canvas) => canvas.id === state.selectedCanvasId);
            const isCurrent = selected && Number(selected.version) === Number(version.version);
            item.innerHTML = `
                <span>
                    <span class="name">v${escapeHtml(version.version)}${isCurrent ? " ? current" : ""}</span>
                    <span class="meta">${escapeHtml(formatLogTime(version.created_at))} ? ${Number(version.node_count || 0)} nodes ? ${Number(version.connection_count || 0)} links</span>
                </span>
                <button class="btn ghost" type="button" data-version-restore="${escapeHtml(version.version)}" ${isCurrent ? "disabled" : ""} title="Restore">
                    <i data-lucide="rotate-ccw" width="16" height="16"></i>
                </button>
            `;
            list.appendChild(item);
        });
        iconRefresh();
    }

    function renderApiProviders(){
        const list = $("apiProviderList");
        if(!list) return;
        if(!state.selectedTeamId){
            list.innerHTML = '<div class="empty">选择团队后显示团队 API 配置</div>';
            renderSelectedApiProvider();
            return;
        }
        const providers = teamApiProviderCards();
        if(!state.selectedApiProviderId || !providers.some((item) => item.provider_id === state.selectedApiProviderId)){
            state.selectedApiProviderId = providers[0]?.provider_id || "";
        }
        list.innerHTML = providers.map((provider) => {
            const active = provider.provider_id === state.selectedApiProviderId ? "active" : "";
            const hasKey = provider.has_api_key || provider.has_wallet_api_key;
            const keyText = provider.has_api_key ? `已配置 ${provider.api_key_preview || ""}` : "未配置 Key";
            const protocol = provider.provider_id === "runninghub" ? "RH" : (provider.protocol || "openai");
            return `
                <button class="team-api-provider-card ${active} ${hasKey ? "has-key" : "missing-key"}" type="button" data-api-select="${escapeHtml(provider.provider_id)}">
                    <span class="api-mark"><i data-lucide="${hasKey ? "key-round" : "key"}" width="16" height="16"></i></span>
                    <span>
                        <span class="api-card-name">${escapeHtml(provider.label || provider.provider_id)}</span>
                        <span class="api-card-meta">${escapeHtml(provider.base_url || keyText)}</span>
                    </span>
                    <span class="api-protocol-pill">${escapeHtml(protocol)}</span>
                </button>
            `;
        }).join("");
        renderSelectedApiProvider();
        iconRefresh();
    }

    function teamApiProviderCards(){
        const saved = new Map((state.apiProviders || []).map((item) => [item.provider_id, item]));
        const base = TEAM_API_PROVIDER_PRESETS.map((preset) => ({...preset, ...(saved.get(preset.provider_id) || {})}));
        const presetIds = new Set(TEAM_API_PROVIDER_PRESETS.map((item) => item.provider_id));
        const extras = (state.apiProviders || []).filter((item) => !presetIds.has(item.provider_id));
        return [...base, ...extras].sort((a, b) => {
            const ai = TEAM_API_PROVIDER_PRESETS.findIndex((item) => item.provider_id === a.provider_id);
            const bi = TEAM_API_PROVIDER_PRESETS.findIndex((item) => item.provider_id === b.provider_id);
            if(ai >= 0 || bi >= 0) return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
            return String(a.provider_id).localeCompare(String(b.provider_id));
        });
    }

    function selectedTeamApiProvider(){
        const id = state.selectedApiProviderId || "";
        return teamApiProviderCards().find((item) => item.provider_id === id) || null;
    }

    function renderSelectedApiProvider(){
        const provider = selectedTeamApiProvider();
        const signedIn = !!state.user && !!state.selectedTeamId;
        if($("apiEditorTitle")) $("apiEditorTitle").textContent = provider ? (provider.label || provider.provider_id || "API") : "API";
        if($("apiProviderId")) $("apiProviderId").value = provider?.provider_id || "";
        if($("apiProviderIdPreview")) $("apiProviderIdPreview").textContent = provider?.provider_id || "-";
        if($("apiProviderLabel")) $("apiProviderLabel").value = provider?.label || "";
        if($("apiProviderBaseUrl")) $("apiProviderBaseUrl").value = provider?.base_url || "";
        if($("apiProviderProtocol")) $("apiProviderProtocol").value = provider?.protocol || "openai";
        if($("apiProviderKey")){
            $("apiProviderKey").value = "";
            $("apiProviderKey").placeholder = provider?.has_api_key ? `保留当前 Key ${provider.api_key_preview || ""}` : "输入 API Key";
            $("apiProviderKey").dataset.clearKey = "";
        }
        if($("apiProviderWalletKey")){
            $("apiProviderWalletKey").value = "";
            $("apiProviderWalletKey").placeholder = provider?.has_wallet_api_key ? `保留当前钱包 Key ${provider.wallet_api_key_preview || ""}` : "RunningHub 可选";
        }
        if($("apiProviderKeyHint")) $("apiProviderKeyHint").textContent = provider?.has_api_key ? `已保存 ${provider.api_key_preview || ""}` : "还没有保存 Key。";
        if($("apiProviderWalletHint")) $("apiProviderWalletHint").textContent = provider?.has_wallet_api_key ? `已保存 ${provider.wallet_api_key_preview || ""}` : "可选。";
        if($("apiProviderDelete")) $("apiProviderDelete").disabled = !signedIn || !provider || !state.apiProviders.some((item) => item.provider_id === provider.provider_id);
        renderTeamApiModelLists(provider);
    }

    function renderTeamApiModelLists(provider){
        const catalog = (state.apiCatalogProviders || []).find((item) => item.id === provider?.provider_id) || {};
        renderModelChips("apiImageModelList", catalog.image_models || []);
        renderModelChips("apiChatModelList", catalog.chat_models || []);
        renderModelChips("apiVideoModelList", catalog.video_models || []);
    }

    function renderModelChips(id, models){
        const el = $(id);
        if(!el) return;
        const items = (models || []).map((model) => String(model || "").trim()).filter(Boolean);
        el.innerHTML = items.length
            ? items.slice(0, 30).map((model) => `<span class="model-chip">${escapeHtml(model)}</span>`).join("")
            : '<div class="empty" style="width:100%;padding:14px 12px">暂无模型</div>';
    }

    function selectApiProvider(providerId){
        if(!providerId) return;
        state.selectedApiProviderId = providerId;
        renderApiProviders();
        setMessage($("apiMessage"), "", "");
    }

    function nextCustomApiProviderId(){
        const existing = new Set(teamApiProviderCards().map((item) => item.provider_id));
        let id = "custom-api";
        let index = 2;
        while(existing.has(id)){
            id = `custom-api-${index++}`;
        }
        return id;
    }

    function addApiProvider(){
        const providerId = nextCustomApiProviderId();
        state.apiProviders.push({
            provider_id: providerId,
            label: "API",
            protocol: "openai",
            base_url: "",
            enabled: true,
            has_api_key: false,
            api_key_preview: "",
            temporary: true,
        });
        state.selectedApiProviderId = providerId;
        renderApiProviders();
        setMessage($("apiMessage"), "已新增平台，保存前只在当前页面临时显示。", "ok");
    }

    function applyRecommendedApi(){
        state.selectedApiProviderId = "openai";
        renderApiProviders();
        $("apiProviderLabel").value = "API";
        $("apiProviderProtocol").value = "openai";
        if(!$("apiProviderBaseUrl").value) $("apiProviderBaseUrl").value = "https://api.example.com/v1";
        setMessage($("apiMessage"), "已切换到 OpenAI 兼容配置。把请求地址和 Key 换成你的服务商信息后保存。", "ok");
    }

    function markApiKeyForClear(){
        const input = $("apiProviderKey");
        if(!input) return;
        input.value = "";
        input.dataset.clearKey = "1";
        if($("apiProviderKeyHint")) $("apiProviderKeyHint").textContent = "保存后会清除当前 Key。";
    }

    function renderGenerationLogs(){
        renderGenerationSummary();
        const list = $("generationLogList");
        if(!list) return;
        list.innerHTML = "";
        if(!state.selectedTeamId){
            list.innerHTML = '<div class="empty">Select a team to view generation logs</div>';
            return;
        }
        if(!state.generationLogs.length){
            list.innerHTML = '<div class="empty">No generation logs yet</div>';
            return;
        }
        state.generationLogs.forEach((log) => {
            const item = document.createElement("div");
            item.className = "log-item";
            const status = log.status === "failed" ? "failed" : (log.status === "succeeded" ? "succeeded" : (log.status || "pending"));
            const timeText = formatLogTime(log.created_at);
            const promptLength = log.request_summary && log.request_summary.prompt_length ? ` ? ${log.request_summary.prompt_length} chars` : "";
            const error = log.error ? `<span class="meta">${escapeHtml(log.error)}</span>` : "";
            item.innerHTML = `
                <span>
                    <span class="name">${escapeHtml(log.provider_id || "API")} ? ${escapeHtml(log.model || "default model")}</span>
                    <span class="meta">${escapeHtml(timeText)}${escapeHtml(promptLength)}</span>
                    ${error}
                </span>
                <span class="badge">${escapeHtml(status)}</span>
            `;
            list.appendChild(item);
        });
    }

    function renderGenerationSummary(){
        const list = $("generationLogSummary");
        if(!list) return;
        const summary = state.generationSummary || {};
        if(!state.selectedTeamId){
            list.innerHTML = "";
            return;
        }
        const providers = summary.providers || {};
        const providerText = Object.entries(providers).slice(0, 4).map(([name, count]) => `${name}: ${count}`).join(" · ");
        list.innerHTML = `
            <div class="log-item">
                <span>
                    <span class="name">Usage summary</span>
                    <span class="meta">Total ${Number(summary.total || 0)} · Succeeded ${Number(summary.succeeded || 0)} · Failed ${Number(summary.failed || 0)}${providerText ? ` · ${escapeHtml(providerText)}` : ""}</span>
                </span>
                <span class="badge">latest</span>
            </div>
        `;
    }

    function formatLogTime(value){
        if(!value) return "";
        if(typeof value === "number"){
            return new Date(value).toLocaleString();
        }
        return String(value).replace("T", " ").replace("Z", "");
    }

    function roleLabel(role){
        return {
            owner: "拥有者",
            admin: "管理员",
            member: "成员",
        }[role] || "成员";
    }

    function escapeHtml(value){
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    async function loadMe(showAuthError){
        try {
            const data = await api("/me");
            state.user = data.user;
            state.teams = data.teams || [];
            if(!state.selectedTeamId && state.teams[0]){
                state.selectedTeamId = state.teams[0].id;
            }
            renderAuth();
            renderTeams();
            if(state.selectedTeamId){
                await selectTeam(state.selectedTeamId, true);
            } else {
                renderMembers([]);
                renderProjects();
                renderCanvases();
                renderGenerationLogs();
            }
        } catch(e) {
            state.user = null;
            state.teams = [];
            state.projects = [];
            state.canvases = [];
            state.apiProviders = [];
            state.generationLogs = [];
            state.generationSummary = null;
            state.selectedTeamId = "";
            state.selectedProjectId = "";
            state.selectedCanvasId = "";
            state.selectedApiProviderId = "";
            state.canvasVersions = [];
            renderAuth();
            renderTeams();
            renderMembers([]);
            renderProjects();
            renderCanvases();
            renderApiProviders();
            renderGenerationLogs();
            renderCanvasVersions();
            if(showAuthError) setMessage($("authMessage"), `登录成功，但读取用户状态失败：${e.message}`, "error");
        }
    }

    async function selectTeam(teamId, silent){
        state.selectedTeamId = teamId;
        state.selectedApiProviderId = "";
        try {
            localStorage.setItem(TEAM_CLOUD_MODE_KEY, "1");
            localStorage.setItem(TEAM_CLOUD_TEAM_KEY, teamId);
        } catch(e) {}
        renderTeams();
        try {
            const data = await api(`/teams/${encodeURIComponent(teamId)}/members`);
            renderMembers(data.members || []);
            await loadProjects(teamId);
            await loadApiProviders(teamId);
            await loadGenerationLogs(teamId);
            setMessage($("teamMessage"), silent ? "" : "团队已选择", silent ? "" : "ok");
        } catch(e) {
            renderMembers([]);
            state.projects = [];
            state.canvases = [];
            state.apiProviders = [];
            state.generationLogs = [];
            state.generationSummary = null;
            state.selectedProjectId = "";
            state.selectedApiProviderId = "";
            renderProjects();
            renderCanvases();
            renderApiProviders();
            renderGenerationLogs();
            setMessage($("teamMessage"), e.message, "error");
        }
        renderAuth();
    }

    async function loadApiProviders(teamId){
        const data = await api(`/teams/${encodeURIComponent(teamId)}/api-providers`);
        state.apiProviders = data.providers || [];
        if(state.selectedApiProviderId && !teamApiProviderCards().some((item) => item.provider_id === state.selectedApiProviderId)){
            state.selectedApiProviderId = "";
        }
        renderApiProviders();
    }

    async function loadApiCatalogProviders(){
        try {
            const response = await fetch("/api/config", { credentials: "include" });
            const data = await response.json();
            state.apiCatalogProviders = Array.isArray(data.api_providers) ? data.api_providers : [];
        } catch(e) {
            state.apiCatalogProviders = [];
        }
    }

    async function loadGenerationLogs(teamId){
        const data = await api(`/teams/${encodeURIComponent(teamId)}/generation-logs?limit=100`);
        state.generationLogs = data.logs || [];
        state.generationSummary = data.summary || null;
        renderGenerationLogs();
    }

    async function loadCanvasVersions(canvasId){
        if(!canvasId) return;
        state.selectedCanvasId = canvasId;
        const data = await api(`/canvases/${encodeURIComponent(canvasId)}/versions`);
        state.canvasVersions = data.versions || [];
        renderCanvases();
        renderCanvasVersions();
    }

    async function restoreCanvasVersion(version){
        if(!state.selectedCanvasId || !version) return;
        if(!confirm(`Restore canvas to version ${version}?`)) return;
        try {
            const data = await api(`/canvases/${encodeURIComponent(state.selectedCanvasId)}/versions/${encodeURIComponent(version)}/restore`, {
                method: "POST",
                body: "{}",
            });
            const restored = data.canvas;
            state.canvases = state.canvases.map((canvas) => canvas.id === restored.id ? {...canvas, ...restored} : canvas);
            await loadCanvasVersions(state.selectedCanvasId);
            setMessage($("projectMessage"), `Restored to v${version}; new current version is v${restored.version}`, "ok");
        } catch(e) {
            setMessage($("projectMessage"), e.message, "error");
        }
    }

    async function loadProjects(teamId){
        const data = await api(`/teams/${encodeURIComponent(teamId)}/projects`);
        state.projects = data.projects || [];
        if(!state.projects.some((project) => project.id === state.selectedProjectId)){
            state.selectedProjectId = state.projects[0] ? state.projects[0].id : "";
        }
        renderProjects();
        if(state.selectedProjectId){
            await selectProject(state.selectedProjectId, true);
        } else {
            state.canvases = [];
            state.selectedCanvasId = "";
            state.canvasVersions = [];
            renderCanvases();
        }
    }

    async function selectProject(projectId, silent){
        state.selectedProjectId = projectId;
        state.selectedCanvasId = "";
        state.canvasVersions = [];
        try {
            localStorage.setItem(TEAM_CLOUD_MODE_KEY, "1");
            localStorage.setItem(TEAM_CLOUD_PROJECT_KEY, projectId);
        } catch(e) {}
        renderProjects();
        try {
            const data = await api(`/projects/${encodeURIComponent(projectId)}/canvases`);
            state.canvases = data.canvases || [];
            renderCanvases();
            renderCanvasVersions();
            setMessage($("projectMessage"), silent ? "" : "项目已选择", silent ? "" : "ok");
        } catch(e) {
            state.canvases = [];
            state.selectedCanvasId = "";
            state.canvasVersions = [];
            renderCanvases();
            renderCanvasVersions();
            setMessage($("projectMessage"), e.message, "error");
        }
        renderAuth();
    }

    async function submitAuth(event){
        event.preventDefault();
        const button = $("authSubmit");
        setBusy(button, true);
        setMessage($("authMessage"), "", "");
        try {
            const payload = {
                email: $("email").value.trim(),
                password: $("password").value,
            };
            const path = state.mode === "login" ? "/auth/login" : "/auth/signup";
            const data = await api(path, {
                method: "POST",
                body: JSON.stringify(payload),
            });
            if(data.session_ready){
                storeAccessToken(data.access_token || "");
                setMessage($("authMessage"), state.mode === "login" ? "已登录" : "已注册并登录", "ok");
                await loadMe(true);
            } else {
                storeAccessToken("");
                setMessage($("authMessage"), "注册已提交，请检查邮箱验证", "ok");
            }
        } catch(e) {
            setMessage($("authMessage"), e.message, "error");
        } finally {
            setBusy(button, false);
        }
    }

    async function submitTeam(event){
        event.preventDefault();
        const name = $("teamName").value.trim();
        if(!name) return;
        setMessage($("teamMessage"), "", "");
        try {
            const data = await api("/teams", {
                method: "POST",
                body: JSON.stringify({ name }),
            });
            $("teamName").value = "";
            state.teams.unshift(data.team);
            state.selectedTeamId = data.team.id;
            state.projects = [];
            state.canvases = [];
            state.apiProviders = [];
            state.selectedProjectId = "";
            renderTeams();
            await selectTeam(data.team.id, true);
            setMessage($("teamMessage"), "团队已创建", "ok");
        } catch(e) {
            setMessage($("teamMessage"), e.message, "error");
        }
    }

    async function submitProject(event){
        event.preventDefault();
        if(!state.selectedTeamId) return;
        setMessage($("projectMessage"), "", "");
        try {
            const data = await api(`/teams/${encodeURIComponent(state.selectedTeamId)}/projects`, {
                method: "POST",
                body: JSON.stringify({
                    name: $("projectName").value.trim(),
                    description: $("projectDescription").value.trim(),
                }),
            });
            $("projectName").value = "";
            $("projectDescription").value = "";
            state.projects.unshift(data.project);
            state.selectedProjectId = data.project.id;
            state.canvases = [];
            state.selectedCanvasId = "";
            state.canvasVersions = [];
            renderProjects();
            renderCanvases();
            renderCanvasVersions();
            setMessage($("projectMessage"), "项目已创建", "ok");
            renderAuth();
        } catch(e) {
            setMessage($("projectMessage"), e.message, "error");
        }
    }

    async function submitCanvas(event){
        event.preventDefault();
        if(!state.selectedProjectId) return;
        setMessage($("projectMessage"), "", "");
        try {
            const data = await api(`/projects/${encodeURIComponent(state.selectedProjectId)}/canvases`, {
                method: "POST",
                body: JSON.stringify({
                    title: $("canvasTitle").value.trim(),
                    data: { nodes: [], connections: [], viewport: { x: 0, y: 0, scale: 1 } },
                }),
            });
            $("canvasTitle").value = "";
            state.canvases.unshift(data.canvas);
            state.selectedCanvasId = data.canvas.id;
            state.canvasVersions = [];
            renderCanvases();
            await loadCanvasVersions(data.canvas.id);
            setMessage($("projectMessage"), "云端画布已创建", "ok");
        } catch(e) {
            setMessage($("projectMessage"), e.message, "error");
        }
    }

    async function submitInvite(event){
        event.preventDefault();
        if(!state.selectedTeamId) return;
        setMessage($("teamMessage"), "", "");
        try {
            await api(`/teams/${encodeURIComponent(state.selectedTeamId)}/invitations`, {
                method: "POST",
                body: JSON.stringify({
                    email: $("inviteEmail").value.trim(),
                    role: $("inviteRole").value,
                }),
            });
            $("inviteEmail").value = "";
            setMessage($("teamMessage"), "邀请已创建", "ok");
        } catch(e) {
            setMessage($("teamMessage"), e.message, "error");
        }
    }

    async function submitApiProvider(event){
        event.preventDefault();
        if(!state.selectedTeamId) return;
        const providerId = ($("apiProviderId").value || state.selectedApiProviderId || "").trim();
        if(!providerId){
            setMessage($("apiMessage"), "\u8bf7\u5148\u9009\u62e9\u6216\u65b0\u589e\u4e00\u4e2a\u5e73\u53f0\u3002", "error");
            return;
        }
        const button = $("apiProviderSubmit");
        setBusy(button, true);
        setMessage($("apiMessage"), "", "");
        try {
            const data = await api(`/teams/${encodeURIComponent(state.selectedTeamId)}/api-providers/${encodeURIComponent(providerId)}`, {
                method: "PUT",
                body: JSON.stringify({
                    label: $("apiProviderLabel").value.trim(),
                    base_url: $("apiProviderBaseUrl").value.trim(),
                    protocol: $("apiProviderProtocol").value,
                    enabled: true,
                    api_key: $("apiProviderKey").value,
                    wallet_api_key: $("apiProviderWalletKey").value,
                    clear_api_key: $("apiProviderKey").dataset.clearKey === "1",
                }),
            });
            $("apiProviderKey").value = "";
            $("apiProviderKey").dataset.clearKey = "";
            $("apiProviderWalletKey").value = "";
            const next = state.apiProviders.filter((item) => item.provider_id !== data.provider.provider_id);
            next.push(data.provider);
            state.apiProviders = next.sort((a, b) => String(a.provider_id).localeCompare(String(b.provider_id)));
            state.selectedApiProviderId = data.provider.provider_id;
            renderApiProviders();
            setMessage($("apiMessage"), "\u56e2\u961f API \u5df2\u4fdd\u5b58\uff0c\u6210\u5458\u53ea\u80fd\u770b\u5230\u5bc6\u94a5\u72b6\u6001\u3002", "ok");
        } catch(e) {
            setMessage($("apiMessage"), e.message, "error");
        } finally {
            setBusy(button, false);
        }
    }

    async function deleteApiProvider(providerId){
        if(!state.selectedTeamId || !providerId) return;
        const localProvider = state.apiProviders.find((item) => item.provider_id === providerId);
        if(localProvider?.temporary){
            state.apiProviders = state.apiProviders.filter((item) => item.provider_id !== providerId);
            state.selectedApiProviderId = teamApiProviderCards()[0]?.provider_id || "";
            renderApiProviders();
            setMessage($("apiMessage"), "\u5df2\u79fb\u9664\u672a\u4fdd\u5b58\u7684\u5e73\u53f0\u3002", "ok");
            return;
        }
        if(!confirm("\u786e\u8ba4\u5220\u9664\u8fd9\u4e2a\u56e2\u961f API \u914d\u7f6e\uff1f")) return;
        setMessage($("apiMessage"), "", "");
        try {
            await api(`/teams/${encodeURIComponent(state.selectedTeamId)}/api-providers/${encodeURIComponent(providerId)}`, { method: "DELETE" });
            state.apiProviders = state.apiProviders.filter((item) => item.provider_id !== providerId);
            state.selectedApiProviderId = TEAM_API_PROVIDER_PRESETS.some((item) => item.provider_id === providerId)
                ? providerId
                : (teamApiProviderCards()[0]?.provider_id || "");
            renderApiProviders();
            setMessage($("apiMessage"), "\u56e2\u961f API \u914d\u7f6e\u5df2\u5220\u9664\u3002", "ok");
        } catch(e) {
            setMessage($("apiMessage"), e.message, "error");
        }
    }

    async function deleteTeam(teamId){
        if(!teamId) return;
        const team = state.teams.find((item) => item.id === teamId);
        const name = team ? team.name : teamId;
        if(!confirm(`确认删除团队“${name}”？团队下的项目、画布、素材、API 配置和调用日志都会删除。`)) return;
        setMessage($("teamMessage"), "", "");
        try {
            await api(`/teams/${encodeURIComponent(teamId)}`, { method: "DELETE" });
            if(state.selectedTeamId === teamId){
                state.selectedTeamId = "";
                state.selectedProjectId = "";
                state.selectedCanvasId = "";
                state.projects = [];
                state.canvases = [];
                state.canvasVersions = [];
                state.apiProviders = [];
                state.generationLogs = [];
                state.generationSummary = null;
                state.selectedApiProviderId = "";
                try {
                    localStorage.removeItem(TEAM_CLOUD_TEAM_KEY);
                    localStorage.removeItem(TEAM_CLOUD_PROJECT_KEY);
                } catch(e) {}
            }
            state.teams = state.teams.filter((item) => item.id !== teamId);
            await loadMe();
            setMessage($("teamMessage"), "团队已删除", "ok");
        } catch(e) {
            setMessage($("teamMessage"), e.message, "error");
        }
    }

    async function deleteProject(projectId){
        if(!state.selectedTeamId || !projectId) return;
        const project = state.projects.find((item) => item.id === projectId);
        const name = project ? project.name : projectId;
        if(!confirm(`确认删除项目“${name}”？项目下的云端画布和版本历史都会删除。`)) return;
        setMessage($("projectMessage"), "", "");
        try {
            await api(`/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
            if(state.selectedProjectId === projectId){
                state.selectedProjectId = "";
                state.selectedCanvasId = "";
                state.canvasVersions = [];
                try { localStorage.removeItem(TEAM_CLOUD_PROJECT_KEY); } catch(e) {}
            }
            await loadProjects(state.selectedTeamId);
            setMessage($("projectMessage"), "项目已删除", "ok");
        } catch(e) {
            setMessage($("projectMessage"), e.message, "error");
        }
    }

    async function deleteCanvas(canvasId){
        if(!state.selectedProjectId || !canvasId) return;
        const canvas = state.canvases.find((item) => item.id === canvasId);
        const title = canvas ? canvas.title : canvasId;
        if(!confirm(`确认删除画布“${title}”？该画布的版本历史也会删除。`)) return;
        setMessage($("projectMessage"), "", "");
        try {
            await api(`/canvases/${encodeURIComponent(canvasId)}`, { method: "DELETE" });
            state.canvases = state.canvases.filter((item) => item.id !== canvasId);
            if(state.selectedCanvasId === canvasId){
                state.selectedCanvasId = "";
                state.canvasVersions = [];
            }
            renderCanvases();
            renderCanvasVersions();
            setMessage($("projectMessage"), "画布已删除", "ok");
        } catch(e) {
            setMessage($("projectMessage"), e.message, "error");
        }
    }

    async function logout(){
        try {
            await api("/auth/logout", { method: "POST", body: "{}" });
        } finally {
            state.user = null;
            state.teams = [];
            state.projects = [];
            state.canvases = [];
            state.apiProviders = [];
            state.generationLogs = [];
            state.generationSummary = null;
            state.selectedTeamId = "";
            state.selectedProjectId = "";
            state.selectedCanvasId = "";
            state.selectedApiProviderId = "";
            state.canvasVersions = [];
            try {
                localStorage.removeItem(TEAM_CLOUD_MODE_KEY);
                localStorage.removeItem(TEAM_CLOUD_TEAM_KEY);
                localStorage.removeItem(TEAM_CLOUD_PROJECT_KEY);
            } catch(e) {}
            storeAccessToken("");
            setMessage($("authMessage"), "已退出", "ok");
            renderAuth();
            renderTeams();
            renderMembers([]);
            renderProjects();
            renderCanvases();
            renderApiProviders();
            renderGenerationLogs();
            renderCanvasVersions();
        }
    }

    async function init(){
        $("loginTab").addEventListener("click", () => {
            state.mode = "login";
            renderAuth();
        });
        $("signupTab").addEventListener("click", () => {
            state.mode = "signup";
            renderAuth();
        });
        $("authForm").addEventListener("submit", submitAuth);
        $("teamForm").addEventListener("submit", submitTeam);
        $("inviteForm").addEventListener("submit", submitInvite);
        $("projectForm").addEventListener("submit", submitProject);
        $("canvasForm").addEventListener("submit", submitCanvas);
        $("apiProviderForm").addEventListener("submit", submitApiProvider);
        $("teamList").addEventListener("click", (event) => {
            const del = event.target.closest("[data-team-delete]");
            if(del){
                event.preventDefault();
                event.stopPropagation();
                deleteTeam(del.dataset.teamDelete);
            }
        });
        $("projectList").addEventListener("click", (event) => {
            const del = event.target.closest("[data-project-delete]");
            if(del){
                event.preventDefault();
                event.stopPropagation();
                deleteProject(del.dataset.projectDelete);
            }
        });
        $("apiProviderAdd").addEventListener("click", addApiProvider);
        $("apiProviderRecommend").addEventListener("click", applyRecommendedApi);
        $("apiProviderDelete").addEventListener("click", () => deleteApiProvider(state.selectedApiProviderId));
        $("apiProviderClearKey").addEventListener("click", markApiKeyForClear);
        $("apiProviderList").addEventListener("click", (event) => {
            const selected = event.target.closest("[data-api-select]");
            if(selected) selectApiProvider(selected.dataset.apiSelect);
        });
        $("canvasList").addEventListener("click", (event) => {
            const del = event.target.closest("[data-canvas-delete]");
            if(del){
                event.preventDefault();
                event.stopPropagation();
                deleteCanvas(del.dataset.canvasDelete);
                return;
            }
            const history = event.target.closest("[data-canvas-history]");
            if(history) loadCanvasVersions(history.dataset.canvasHistory);
        });
        $("canvasVersionList").addEventListener("click", (event) => {
            const restore = event.target.closest("[data-version-restore]");
            if(restore) restoreCanvasVersion(restore.dataset.versionRestore);
        });
        $("logoutBtn").addEventListener("click", logout);

        try {
            state.config = await api("/config");
            updateStatus();
        } catch(e) {
            state.config = {};
            $("systemStatus").classList.add("warn");
            $("systemStatus").innerHTML = '<i data-lucide="badge-alert" width="16" height="16"></i><span>连接失败</span>';
            iconRefresh();
        }
        await loadApiCatalogProviders();
        renderAuth();
        renderTeams();
        renderMembers([]);
        renderProjects();
        renderCanvases();
        renderApiProviders();
        renderGenerationLogs();
        await loadMe();
        iconRefresh();
    }

    window.addEventListener("message", (event) => {
        if(event.origin && event.origin !== location.origin) return;
        if(event.data?.type === "studio-theme") applyTheme(event.data.theme || "light");
    });
    window.addEventListener("storage", (event) => {
        if(event.key === "studio_theme" || event.key === "canvas_theme"){
            applyTheme(localStorage.getItem("studio_theme") || localStorage.getItem("canvas_theme") || "light");
        }
    });
    document.addEventListener("DOMContentLoaded", () => {
        applyTheme(localStorage.getItem("studio_theme") || localStorage.getItem("canvas_theme") || "light");
        init();
    });
})();
