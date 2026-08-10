(function(){
    const $ = (id) => document.getElementById(id);
    const TOKEN_KEY = "teamCloudAccessToken";
    const SESSION_KEY = "teamAdminPreviewSessionId";

    const state = {
        teamId: "",
        teams: [],
        overview: null,
        users: [],
        selectedUserId: "",
        logs: [],
        feedback: [],
    };

    function iconRefresh(){
        if(window.lucide && typeof window.lucide.createIcons === "function"){
            window.lucide.createIcons();
        }
    }

    function applyTheme(theme){
        const next = theme === "light" ? "light" : "dark";
        const isDark = next === "dark";
        document.documentElement.classList.toggle("theme-dark", isDark);
        document.body?.classList.toggle("theme-dark", isDark);
        document.documentElement.classList.toggle("theme-light", !isDark);
        document.body?.classList.toggle("theme-light", !isDark);
        try {
            localStorage.setItem("studio_theme", next);
            localStorage.setItem("canvas_theme", next);
        } catch(e) {}
    }

    function restoreTheme(){
        try {
            applyTheme(localStorage.getItem("studio_theme") || localStorage.getItem("canvas_theme") || "dark");
        } catch(e) {
            applyTheme("dark");
        }
    }

    function token(){
        try { return localStorage.getItem(TOKEN_KEY) || ""; } catch(e) { return ""; }
    }

    function sessionId(){
        try {
            let id = sessionStorage.getItem(SESSION_KEY);
            if(!id){
                id = `admin_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
                sessionStorage.setItem(SESSION_KEY, id);
            }
            return id;
        } catch(e) {
            return `admin_${Date.now().toString(36)}`;
        }
    }

    async function api(path, options){
        const headers = { "Content-Type": "application/json", ...(options?.headers || {}) };
        const accessToken = token();
        if(accessToken) headers.Authorization = `Bearer ${accessToken}`;
        const res = await fetch(`/api/team-cloud${path}`, {
            ...options,
            credentials: "include",
            headers,
        });
        let data = {};
        try { data = await res.json(); } catch(e) {}
        if(!res.ok){
            const detail = data.detail;
            throw new Error(typeof detail === "string" ? detail : (detail?.message || data.message || "请求失败"));
        }
        return data;
    }

    function showMessage(text){
        const el = $("message");
        el.textContent = text || "";
        el.hidden = !text;
    }

    function fmtNumber(value){
        return new Intl.NumberFormat("zh-CN").format(Number(value || 0));
    }

    function fmtTime(value){
        if(!value) return "-";
        const date = new Date(value);
        if(Number.isNaN(date.getTime())) return "-";
        return date.toLocaleString("zh-CN", { hour12: false });
    }

    function fmtDuration(seconds){
        const total = Math.max(0, Number(seconds || 0));
        const minutes = Math.floor(total / 60);
        if(minutes < 60) return `${minutes} 分钟`;
        return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟`;
    }

    function escapeHtml(value){
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function operationLabel(value){
        return {
            image: "生图",
            video: "视频",
            chat: "聊天",
            upscale: "放大",
            workflow: "工作流",
        }[value] || value || "-";
    }

    function statusLabel(value){
        return {
            succeeded: "成功",
            failed: "失败",
            pending: "进行中",
        }[value] || value || "-";
    }

    function renderTeams(){
        const select = $("teamSelect");
        if(!select) return;
        select.innerHTML = "";
        const adminTeams = state.teams.filter((team) => ["owner", "admin"].includes(team.role));
        if(!adminTeams.length){
            const option = document.createElement("option");
            option.value = "";
            option.textContent = token() ? "暂无可管理团队" : "请先登录后选择团队";
            option.selected = true;
            option.disabled = true;
            select.appendChild(option);
            select.disabled = true;
            return;
        }
        select.disabled = false;
        adminTeams.forEach((team) => {
            const option = document.createElement("option");
            option.value = team.id;
            option.textContent = `${team.name || team.id} · ${team.role}`;
            option.selected = team.id === state.teamId;
            select.appendChild(option);
        });
    }

    function renderMetrics(){
        const today = state.overview?.today || {};
        const month = state.overview?.month || {};
        const items = [
            ["今日调用", today.total],
            ["今日生图", today.image_count],
            ["今日视频", today.video_count],
            ["今日点数", today.points_charged],
            ["在线用户", state.overview?.active_users],
            ["本月调用", month.total],
        ];
        $("metricGrid").innerHTML = items.map(([label, value]) => `
            <div class="metric">
                <span>${escapeHtml(label)}</span>
                <strong>${fmtNumber(value)}</strong>
            </div>
        `).join("");
    }

    function renderUsers(){
        const query = $("userSearch").value.trim().toLowerCase();
        const users = state.users.filter((user) => {
            const haystack = `${user.email || ""} ${user.username || ""} ${user.display_name || ""} ${user.user_id || ""}`.toLowerCase();
            return !query || haystack.includes(query);
        });
        $("userCount").textContent = `${users.length} 人`;
        $("userList").innerHTML = users.length ? users.map((user) => `
            <button class="user-row ${user.user_id === state.selectedUserId ? "active" : ""}" type="button" data-user-id="${escapeHtml(user.user_id)}">
                <span>
                    <span class="name">${escapeHtml(user.display_name || user.email || user.user_id)}</span>
                    <span class="meta">${escapeHtml(user.email || user.user_id)} · ${escapeHtml(user.role || "")}</span>
                </span>
                <span class="badge ${user.online ? "online" : ""}">${user.online ? "在线" : "离线"}</span>
            </button>
        `).join("") : '<div class="empty">暂无用户</div>';
    }

    function renderDetail(detail){
        const user = state.users.find((item) => item.user_id === state.selectedUserId);
        $("pointsBtn").disabled = !state.selectedUserId;
        $("detailTitle").textContent = user?.display_name || user?.email || state.selectedUserId || "用户详情";
        $("detailMeta").textContent = user ? `${user.email || user.user_id} · ${user.online ? "在线" : "离线"}` : "选择用户查看";
        if(!detail){
            $("detailBody").innerHTML = '<div class="empty">选择左侧用户查看详情</div>';
            return;
        }
        const usage = detail.usage || {};
        const points = detail.points || {};
        $("detailBody").innerHTML = `
            <div class="detail-grid">
                <div class="mini"><span>余额</span><strong>${fmtNumber(points.balance)}</strong></div>
                <div class="mini"><span>调用</span><strong>${fmtNumber(usage.total)}</strong></div>
                <div class="mini"><span>生图</span><strong>${fmtNumber(usage.image_count)}</strong></div>
                <div class="mini"><span>在线时长</span><strong>${fmtDuration((user && user.active_seconds) || 0)}</strong></div>
            </div>
            <table>
                <thead><tr><th>日期</th><th>调用</th></tr></thead>
                <tbody>${(detail.daily || []).map((item) => `<tr><td>${escapeHtml(item.date)}</td><td>${fmtNumber(item.count)}</td></tr>`).join("") || '<tr><td colspan="2">暂无趋势</td></tr>'}</tbody>
            </table>
        `;
    }

    function renderLogs(){
        $("logCount").textContent = `${fmtNumber(state.logs.length)} 条`;
        $("logTable").innerHTML = state.logs.length ? state.logs.map((log) => {
            const user = state.users.find((item) => item.user_id === log.user_id);
            return `
                <tr>
                    <td>${fmtTime(log.created_at)}</td>
                    <td>${escapeHtml(user?.display_name || user?.email || log.user_id)}</td>
                    <td>${escapeHtml(operationLabel(log.operation_type))}</td>
                    <td>${escapeHtml(log.provider_id || "-")}</td>
                    <td>${escapeHtml(log.model || "-")}</td>
                    <td>${escapeHtml(statusLabel(log.status))}</td>
                    <td>${fmtNumber(log.points_charged)}</td>
                    <td>${fmtNumber(log.latency_ms)} ms</td>
                </tr>
            `;
        }).join("") : '<tr><td colspan="8">暂无调用日志</td></tr>';
    }

    function feedbackUserLabel(item){
        const user = item?.user || {};
        if(user.display_name) return user.display_name;
        if(user.email) return user.email;
        if(user.username) return user.username;
        if(user.id) return user.id;
        return item?.client_host || "匿名用户";
    }

    function renderFeedback(){
        const list = $("feedbackList");
        if(!list) return;
        $("feedbackCount").textContent = `${fmtNumber(state.feedback.length)} 条`;
        list.innerHTML = state.feedback.length ? state.feedback.map((item) => `
            <article class="feedback-item">
                <header>
                    <strong>${escapeHtml(feedbackUserLabel(item))}</strong>
                    <span>${fmtTime(item.created_at)}</span>
                </header>
                <p>${escapeHtml(item.message || "")}</p>
                <footer>
                    <span>${escapeHtml(item.page || "-")}</span>
                    <span>${escapeHtml(item.id || "")}</span>
                </footer>
            </article>
        `).join("") : '<div class="empty">暂无体验反馈</div>';
    }

    async function loadOverview(){
        const data = await api(`/admin/overview${state.teamId ? `?team_id=${encodeURIComponent(state.teamId)}` : ""}`);
        state.teamId = data.team_id || state.teamId;
        state.teams = data.teams || state.teams;
        state.overview = data.overview;
        renderTeams();
        renderMetrics();
    }

    async function loadUsers(){
        const data = await api(`/admin/users?team_id=${encodeURIComponent(state.teamId)}`);
        state.users = data.users || [];
        if(!state.selectedUserId && state.users[0]) state.selectedUserId = state.users[0].user_id;
        renderUsers();
    }

    async function loadLogs(){
        const params = new URLSearchParams({ team_id: state.teamId, limit: "100" });
        if($("operationFilter").value) params.set("operation_type", $("operationFilter").value);
        if($("statusFilter").value) params.set("status", $("statusFilter").value);
        const data = await api(`/admin/usage/logs?${params.toString()}`);
        state.logs = data.logs || [];
        renderLogs();
    }

    async function loadFeedback(){
        const params = new URLSearchParams({ team_id: state.teamId, limit: "100" });
        const data = await api(`/admin/feedback?${params.toString()}`);
        state.feedback = data.feedback || [];
        renderFeedback();
    }

    async function loadDetail(){
        if(!state.selectedUserId){
            renderDetail(null);
            return;
        }
        const data = await api(`/admin/users/${encodeURIComponent(state.selectedUserId)}?team_id=${encodeURIComponent(state.teamId)}`);
        renderDetail(data.detail);
    }

    async function refresh(){
        showMessage("");
        $("refreshBtn").disabled = true;
        try {
            await loadOverview();
            await Promise.all([loadUsers(), loadLogs(), loadFeedback()]);
            await loadDetail();
            await sendHeartbeat();
        } catch(e) {
            renderTeams();
            showMessage(e.message);
        } finally {
            $("refreshBtn").disabled = false;
            iconRefresh();
        }
    }

    async function sendHeartbeat(){
        try {
            await api("/sessions/heartbeat", {
                method: "POST",
                body: JSON.stringify({ team_id: state.teamId, session_id: sessionId(), page: location.pathname }),
            });
        } catch(e) {}
    }

    async function submitPoints(){
        if(!state.selectedUserId) return;
        $("pointsSubmit").disabled = true;
        try {
            await api(`/admin/users/${encodeURIComponent(state.selectedUserId)}/points`, {
                method: "POST",
                body: JSON.stringify({
                    team_id: state.teamId,
                    mode: $("pointsMode").value,
                    delta: Number($("pointsDelta").value || 0),
                    note: $("pointsNote").value.trim(),
                }),
            });
            $("pointsDialog").close();
            await refresh();
        } catch(e) {
            showMessage(e.message);
        } finally {
            $("pointsSubmit").disabled = false;
        }
    }

    function bind(){
        window.addEventListener("message", (event) => {
            if(event.origin && event.origin !== location.origin) return;
            if(event.data?.type === "studio-theme") applyTheme(event.data.theme);
        });
        $("refreshBtn").addEventListener("click", refresh);
        $("homeBtn")?.addEventListener("click", () => {
            if(window.parent && window.parent !== window){
                window.parent.postMessage({ type: "studio-open-page", page: "workbench" }, window.location.origin);
            } else {
                window.location.href = "/static/workbench.html";
            }
        });
        $("teamSelect")?.addEventListener("change", () => {
            state.teamId = $("teamSelect")?.value || "";
            state.selectedUserId = "";
            refresh();
        });
        $("userSearch").addEventListener("input", renderUsers);
        $("operationFilter").addEventListener("change", loadLogs);
        $("statusFilter").addEventListener("change", loadLogs);
        $("feedbackRefreshBtn")?.addEventListener("click", loadFeedback);
        $("userList").addEventListener("click", async (event) => {
            const row = event.target.closest("[data-user-id]");
            if(!row) return;
            state.selectedUserId = row.dataset.userId;
            renderUsers();
            await loadDetail();
            iconRefresh();
        });
        $("pointsBtn").addEventListener("click", () => $("pointsDialog").showModal());
        $("pointsSubmit").addEventListener("click", submitPoints);
    }

    document.addEventListener("DOMContentLoaded", () => {
        restoreTheme();
        bind();
        renderTeams();
        renderMetrics();
        renderDetail(null);
        renderFeedback();
        refresh();
        window.setInterval(sendHeartbeat, 60000);
        iconRefresh();
    });
})();
