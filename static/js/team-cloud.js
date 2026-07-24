(function(){
    const $ = (id) => document.getElementById(id);

    const state = {
        mode: "login",
        user: null,
        teams: [],
        selectedTeamId: "",
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

    async function api(path, options){
        const response = await fetch(`/api/team-cloud${path}`, {
            credentials: "include",
            headers: {
                "Content-Type": "application/json",
                ...(options && options.headers ? options.headers : {}),
            },
            ...options,
        });
        let data = null;
        try {
            data = await response.json();
        } catch(e) {
            data = {};
        }
        if(!response.ok){
            throw new Error(data.detail || data.message || "请求失败");
        }
        return data;
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
        $("authSubmit").querySelector("span").textContent = state.mode === "login" ? "登录" : "注册";
        $("authSubmit").querySelector("i").setAttribute("data-lucide", state.mode === "login" ? "log-in" : "user-plus");
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

    async function loadMe(){
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
            }
        } catch(e) {
            state.user = null;
            state.teams = [];
            state.selectedTeamId = "";
            renderAuth();
            renderTeams();
            renderMembers([]);
        }
    }

    async function selectTeam(teamId, silent){
        state.selectedTeamId = teamId;
        renderTeams();
        try {
            const data = await api(`/teams/${encodeURIComponent(teamId)}/members`);
            renderMembers(data.members || []);
            setMessage($("teamMessage"), silent ? "" : "团队已选择", silent ? "" : "ok");
        } catch(e) {
            renderMembers([]);
            setMessage($("teamMessage"), e.message, "error");
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
                setMessage($("authMessage"), state.mode === "login" ? "已登录" : "已注册并登录", "ok");
                await loadMe();
            } else {
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
            renderTeams();
            await selectTeam(data.team.id, true);
            setMessage($("teamMessage"), "团队已创建", "ok");
        } catch(e) {
            setMessage($("teamMessage"), e.message, "error");
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

    async function logout(){
        try {
            await api("/auth/logout", { method: "POST", body: "{}" });
        } finally {
            state.user = null;
            state.teams = [];
            state.selectedTeamId = "";
            setMessage($("authMessage"), "已退出", "ok");
            renderAuth();
            renderTeams();
            renderMembers([]);
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
        await loadMe();
        iconRefresh();
    }

    document.addEventListener("DOMContentLoaded", init);
})();
