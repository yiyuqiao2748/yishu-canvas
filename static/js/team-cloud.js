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
        generationLogs: [],
        generationSummary: null,
        selectedTeamId: "",
        selectedProjectId: "",
        selectedCanvasId: "",
        canvasVersions: [],
        config: null,
    };

    function iconRefresh(){
        if(window.lucide && typeof window.lucide.createIcons === "function"){
            window.lucide.createIcons();
        }
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
            const item = document.createElement("button");
            item.type = "button";
            item.className = `team-item${team.id === state.selectedTeamId ? " active" : ""}`;
            item.innerHTML = `
                <span>
                    <span class="name">${escapeHtml(team.name)}</span>
                    <span class="meta">${escapeHtml(team.id)}</span>
                </span>
                <span class="badge">${roleLabel(team.role)}</span>
            `;
            item.addEventListener("click", () => selectTeam(team.id));
            list.appendChild(item);
        });
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
            const item = document.createElement("button");
            item.type = "button";
            item.className = `team-item${project.id === state.selectedProjectId ? " active" : ""}`;
            item.innerHTML = `
                <span>
                    <span class="name">${escapeHtml(project.name)}</span>
                    <span class="meta">${escapeHtml(project.description || project.id)}</span>
                </span>
                <span class="badge">项目</span>
            `;
            item.addEventListener("click", () => selectProject(project.id));
            list.appendChild(item);
        });
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
        list.innerHTML = "";
        if(!state.selectedTeamId){
            list.innerHTML = '<div class="empty">选择团队后显示团队 API 配置</div>';
            return;
        }
        if(!state.apiProviders.length){
            list.innerHTML = '<div class="empty">还没有团队 API 配置</div>';
            return;
        }
        state.apiProviders.forEach((provider) => {
            const item = document.createElement("div");
            item.className = "api-item";
            const keyText = provider.has_api_key ? `已保存 ${provider.api_key_preview || ""}` : "未保存 Key";
            item.innerHTML = `
                <span>
                    <span class="name">${escapeHtml(provider.label || provider.provider_id)}</span>
                    <span class="meta">${escapeHtml(provider.provider_id)} · ${escapeHtml(provider.protocol || "openai")} · ${escapeHtml(keyText)}</span>
                </span>
                <span class="row">
                    <span class="badge">${provider.enabled === false ? "停用" : "启用"}</span>
                    <button class="btn ghost" type="button" data-api-edit="${escapeHtml(provider.provider_id)}" title="编辑">
                        <i data-lucide="pencil" width="16" height="16"></i>
                    </button>
                    <button class="btn ghost" type="button" data-api-delete="${escapeHtml(provider.provider_id)}" title="删除">
                        <i data-lucide="trash-2" width="16" height="16"></i>
                    </button>
                </span>
            `;
            list.appendChild(item);
        });
        iconRefresh();
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
        renderApiProviders();
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
        const providerId = $("apiProviderId").value.trim();
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
                }),
            });
            $("apiProviderKey").value = "";
            $("apiProviderWalletKey").value = "";
            const next = state.apiProviders.filter((item) => item.provider_id !== data.provider.provider_id);
            next.push(data.provider);
            state.apiProviders = next.sort((a, b) => String(a.provider_id).localeCompare(String(b.provider_id)));
            renderApiProviders();
            setMessage($("apiMessage"), "团队 API 已保存，成员只能看到密钥状态", "ok");
        } catch(e) {
            setMessage($("apiMessage"), e.message, "error");
        } finally {
            setBusy(button, false);
        }
    }

    async function deleteApiProvider(providerId){
        if(!state.selectedTeamId || !providerId) return;
        if(!confirm("确认删除这个团队 API 配置？")) return;
        setMessage($("apiMessage"), "", "");
        try {
            await api(`/teams/${encodeURIComponent(state.selectedTeamId)}/api-providers/${encodeURIComponent(providerId)}`, { method: "DELETE" });
            state.apiProviders = state.apiProviders.filter((item) => item.provider_id !== providerId);
            renderApiProviders();
            setMessage($("apiMessage"), "团队 API 配置已删除", "ok");
        } catch(e) {
            setMessage($("apiMessage"), e.message, "error");
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
        $("apiProviderId").addEventListener("change", () => {
            const labels = {
                openai: "OpenAI 兼容",
                modelscope: "ModelScope",
                runninghub: "RunningHub",
                volcengine: "火山引擎",
            };
            const protocols = {
                runninghub: "runninghub",
                volcengine: "volcengine",
                modelscope: "openai",
                openai: "openai",
            };
            const id = $("apiProviderId").value;
            $("apiProviderLabel").value = labels[id] || id;
            $("apiProviderProtocol").value = protocols[id] || "openai";
        });
        $("apiProviderList").addEventListener("click", (event) => {
            const edit = event.target.closest("[data-api-edit]");
            if(edit){
                const provider = state.apiProviders.find((item) => item.provider_id === edit.dataset.apiEdit);
                if(provider){
                    $("apiProviderId").value = provider.provider_id;
                    $("apiProviderLabel").value = provider.label || provider.provider_id;
                    $("apiProviderBaseUrl").value = provider.base_url || "";
                    $("apiProviderProtocol").value = provider.protocol || "openai";
                    $("apiProviderKey").value = "";
                    $("apiProviderWalletKey").value = "";
                    setMessage($("apiMessage"), "已载入配置，留空密钥会保持原值", "ok");
                }
                return;
            }
            const del = event.target.closest("[data-api-delete]");
            if(del) deleteApiProvider(del.dataset.apiDelete);
        });
        $("canvasList").addEventListener("click", (event) => {
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

    document.addEventListener("DOMContentLoaded", init);
})();
