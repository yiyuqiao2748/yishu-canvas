(function(global){
    const STORAGE_PREFIX = 'smartImageAgentV2';
    const IMAGE_MODELS = [
        {id:'gpt-image-2', label:'GPT Image 2', cost:6, quality:'standard'},
        {id:'nano-banana-2', label:'Nano Banana 2', cost:12, quality:'standard'},
        {id:'nano-banana-pro', label:'Nano Banana Pro', cost:18, quality:'pro'},
        {id:'gpt-image-2-vip', label:'GPT Image 2 VIP', cost:20, quality:'vip'}
    ];
    const state = {
        session:null,
        plans:new Map(),
        currentPlan:null,
        runs:[],
        results:[],
        sessions:[],
        selectionRefs:[],
        manualRefs:[],
        referenceRoles:new Map(),
        selectedResultGroup:[],
        pendingAction:'',
        assetCache:[],
        activeRuns:0,
        cancelled:new Set(),
        initialized:false,
        unsubscribe:null,
        sessionPromise:null
    };

    const els = {};

    function canvasKey(name){
        const context = global.SmartImageAgentBridge?.getCanvasContext?.() || {};
        return `${STORAGE_PREFIX}:${context.canvas_id || 'local'}:${name}`;
    }
    function readSetting(name, fallback){
        try { return localStorage.getItem(canvasKey(name)) ?? fallback; } catch(_error) { return fallback; }
    }
    function writeSetting(name, value){
        try { localStorage.setItem(canvasKey(name), String(value)); } catch(_error) {}
    }
    function authHeaders(headers={}){
        const next = {...headers};
        try {
            const token = localStorage.getItem('teamCloudAccessToken') || '';
            if(token) next.Authorization = `Bearer ${token}`;
        } catch(_error) {}
        return next;
    }
    async function api(path, options={}){
        const response = await fetch(path, {
            ...options,
            credentials:'include',
            headers:authHeaders(options.headers || {})
        });
        if(!response.ok){
            let detail = '';
            try {
                const body = await response.clone().json();
                detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || body);
            } catch(_error) {
                detail = await response.text().catch(() => '');
            }
            throw new Error(detail || `请求失败 (${response.status})`);
        }
        return response.status === 204 ? {} : response.json();
    }
    function escapeHtml(value){
        return String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
    }
    function refreshIcons(){
        try { global.lucide?.createIcons?.({nodes:[els.root]}); } catch(_error) { try { global.lucide?.createIcons?.(); } catch(_ignored) {} }
    }
    function notify(message, kind='info'){
        els.notice.textContent = String(message || '');
        els.notice.dataset.kind = kind;
        els.notice.hidden = !message;
        clearTimeout(notify.timer);
        if(message) notify.timer = setTimeout(() => { els.notice.hidden = true; }, 4200);
    }
    function combinedRefs(){
        const seen = new Set();
        return [...state.selectionRefs, ...state.manualRefs].filter(item => {
            const key = `${item.node_id || ''}|${item.asset_id || ''}|${item.url || ''}`;
            if(!item.url || seen.has(key)) return false;
            seen.add(key);
            return true;
        }).map(item => ({...item, role:state.referenceRoles.get(referenceKey(item)) || item.role || ''}));
    }
    function referenceKey(item){
        return `${item?.node_id || ''}|${item?.asset_id || ''}|${item?.url || ''}`;
    }
    function addManualReferences(items){
        const additions = (Array.isArray(items) ? items : [items]).filter(item => item?.url);
        if(!additions.length) return false;
        const previous = state.manualRefs;
        state.manualRefs = [...previous, ...additions];
        const total = combinedRefs().length;
        if(total > 10){
            state.manualRefs = previous;
            notify(`单次最多引用 10 张图片，当前添加后会有 ${total} 张`, 'error');
            return false;
        }
        renderReferences();
        return true;
    }
    function referenceLabel(item, index){
        return item.name || item.prompt || `参考图 ${index + 1}`;
    }
    function referenceRoleLabel(role){
        return {primary:'主图', reference:'参考', edit_target:'待修改'}[role] || '自动';
    }
    function renderReferences(){
        const refs = combinedRefs();
        els.refs.innerHTML = refs.length ? refs.map((item, index) => `
            <div class="sia-ref" data-ref-index="${index}">
                <img src="${escapeHtml(item.preview_url || item.url)}" alt="${escapeHtml(referenceLabel(item, index))}">
                <select data-reference-role="${index}" title="图片用途">
                    <option value="" ${!item.role ? 'selected' : ''}>自动</option>
                    <option value="primary" ${item.role === 'primary' ? 'selected' : ''}>主图</option>
                    <option value="reference" ${item.role === 'reference' ? 'selected' : ''}>参考</option>
                    <option value="edit_target" ${item.role === 'edit_target' ? 'selected' : ''}>修改</option>
                </select>
                <button type="button" data-remove-ref="${index}" title="移除参考图"><i data-lucide="x"></i></button>
            </div>
        `).join('') : '<div class="sia-empty-ref"><i data-lucide="image-plus"></i><span>选中画布图片或添加参考图</span></div>';
        els.refCount.textContent = `${refs.length}/10`;
        els.refCount.classList.toggle('is-over-limit', refs.length > 10);
        if(refs.length > 10) notify(`已引用 ${refs.length} 张图片，请减少到 10 张后再生成`, 'error');
        els.refs.querySelectorAll('[data-remove-ref]').forEach(button => {
            button.addEventListener('click', () => {
                const target = refs[Number(button.dataset.removeRef)];
                state.referenceRoles.delete(referenceKey(target));
                state.manualRefs = state.manualRefs.filter(item => referenceKey(item) !== referenceKey(target));
                state.selectionRefs = state.selectionRefs.filter(item => referenceKey(item) !== referenceKey(target));
                renderReferences();
            });
        });
        els.refs.querySelectorAll('[data-reference-role]').forEach(select => select.addEventListener('change', () => {
            const item = refs[Number(select.dataset.referenceRole)];
            if(!item) return;
            state.referenceRoles.set(referenceKey(item), select.value);
            notify(`${referenceLabel(item, Number(select.dataset.referenceRole))} 将作为${referenceRoleLabel(select.value)}`);
        }));
        refreshIcons();
    }
    function actionLabel(action){
        return {
            generate_image:'新图生成', edit_image:'选图修改', compose_images:'多图合成',
            create_variants:'创建变体', expand_image:'扩图补景', generate_image_set:'批量套图',
            organize_results:'整理结果'
        }[action] || '图片创作';
    }
    function modelPolicy(model){
        return IMAGE_MODELS.find(item => item.id === model) || IMAGE_MODELS[1];
    }
    function modelOptions(selected){
        return IMAGE_MODELS.map(item => `<option value="${item.id}" ${item.id === selected ? 'selected' : ''}>${item.label} · ${item.cost} 灵感点</option>`).join('');
    }
    function modelLabel(plan){
        return modelPolicy(plan?.model).label;
    }
    function renderPlan(){
        const plan = state.currentPlan;
        if(!plan){
            els.plan.hidden = true;
            return;
        }
        els.plan.hidden = false;
        els.plan.innerHTML = `
            <div class="sia-plan-head">
                <span>${escapeHtml(actionLabel(plan.action))}</span>
                <strong>${escapeHtml(modelLabel(plan))}</strong>
            </div>
            <p>${escapeHtml(plan.prompt || plan.message)}</p>
            <div class="sia-plan-references">${(plan.references || []).map((item, index) => `
                <span title="${escapeHtml(referenceLabel(item, index))}">${escapeHtml(referenceRoleLabel(item.role))}</span>
            `).join('') || '<span>纯文字创作</span>'}</div>
            <div class="sia-plan-controls">
                <label class="sia-model-control"><span>模型</span><select data-plan-field="model">${modelOptions(plan.model)}</select></label>
                <label><span>比例</span><select data-plan-field="ratio">
                    ${['auto','1:1','4:5','16:9','9:16','4:3','3:4','21:9'].map(value => `<option value="${value}" ${value === plan.ratio ? 'selected' : ''}>${value === 'auto' ? '自动' : value}</option>`).join('')}
                </select></label>
                <label><span>数量</span><input data-plan-field="count" type="number" min="1" max="8" value="${Number(plan.count) || 1}"></label>
            </div>
            <div class="sia-plan-cost"><span>预计消耗</span><strong>${Number(plan.estimated_points) || 0} 灵感点</strong></div>
            <button class="sia-primary" type="button" data-confirm-plan ${plan.status !== 'awaiting_confirmation' ? 'disabled' : ''}>
                <i data-lucide="sparkles"></i><span>${Number(plan.count) > 1 ? '全部生成' : '生成'}</span>
            </button>
            ${plan.status === 'awaiting_confirmation' ? '<button class="sia-secondary" type="button" data-dismiss-plan>放弃此方案</button>' : ''}`;
        els.plan.querySelectorAll('[data-plan-field]').forEach(control => {
            control.addEventListener('change', () => updatePlan(control.dataset.planField, control.type === 'number' ? Number(control.value) : control.value));
        });
        els.plan.querySelector('[data-confirm-plan]')?.addEventListener('click', confirmCurrentPlan);
        els.plan.querySelector('[data-dismiss-plan]')?.addEventListener('click', dismissCurrentPlan);
        refreshIcons();
    }
    function statusLabel(status, stage=''){
        if(stage) return {queued:'排队等待', preparing:'准备图片', generating:'生成中', saving:'保存结果', completed:'已完成', failed:'失败', cancelled:'已取消'}[stage] || stage;
        return {queued:'排队中', running:'生成中', succeeded:'已完成', failed:'失败', cancelled:'已取消'}[status] || status;
    }
    function renderTasks(){
        const runs = state.runs.slice().sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
        const activeCount = runs.filter(run => ['queued','running','starting'].includes(run.status)).length;
        if(els.collapsedCount){
            els.collapsedCount.textContent = String(activeCount);
            els.collapsedCount.hidden = !activeCount;
        }
        els.tasks.innerHTML = runs.length ? runs.map(run => {
            const plan = state.plans.get(run.plan_id) || {};
            const canCancel = ['queued','running'].includes(run.status);
            const canRetry = ['failed','cancelled'].includes(run.status);
            return `<article class="sia-task" data-run-id="${escapeHtml(run.id)}">
                <div class="sia-task-state" data-state="${escapeHtml(run.status)}"><span></span>${escapeHtml(statusLabel(run.status, run.progress_stage))}</div>
                <strong>${escapeHtml(actionLabel(plan.action))} · ${Number(run.sequence) || 1}</strong>
                <small>${escapeHtml(modelLabel(plan))}${run.attempt > 1 ? ` · 第 ${run.attempt} 次` : ''}</small>
                ${run.error ? `<p>${escapeHtml(run.error)}</p>` : ''}
                <div class="sia-task-actions">
                    ${canCancel ? '<button type="button" data-cancel-run><i data-lucide="square"></i><span>取消</span></button>' : ''}
                    ${canRetry ? '<button type="button" data-retry-run><i data-lucide="rotate-cw"></i><span>重试</span></button>' : ''}
                </div>
            </article>`;
        }).join('') : '<div class="sia-empty"><i data-lucide="list-checks"></i><span>暂无生成任务</span></div>';
        els.tasks.querySelectorAll('[data-run-id]').forEach(row => {
            const id = row.dataset.runId;
            row.querySelector('[data-cancel-run]')?.addEventListener('click', () => cancelRun(id));
            row.querySelector('[data-retry-run]')?.addEventListener('click', () => retryRun(id));
        });
        refreshIcons();
    }
    function renderResults(){
        els.results.innerHTML = state.results.length ? state.results.map(result => `
            <article class="sia-result" data-result-run="${escapeHtml(result.run_id)}">
                <button class="sia-result-image" type="button" data-focus-node="${escapeHtml(result.target_node_id || '')}">
                    <img src="${escapeHtml(result.preview_url || result.url)}" alt="生成结果">
                </button>
                <div class="sia-result-actions">
                    <button type="button" data-use-result title="继续修改"><i data-lucide="wand-sparkles"></i></button>
                    <button type="button" data-variant-result title="生成变体"><i data-lucide="copy-plus"></i></button>
                    <button type="button" data-expand-result title="扩图补景"><i data-lucide="maximize"></i></button>
                    <button type="button" data-save-result title="保存素材库"><i data-lucide="archive"></i></button>
                    <a href="${escapeHtml(result.url)}" download title="下载"><i data-lucide="download"></i></a>
                </div>
            </article>`).join('') : '<div class="sia-empty"><i data-lucide="images"></i><span>生成结果会保留在这里</span></div>';
        els.results.querySelectorAll('[data-result-run]').forEach(card => {
            const result = state.results.find(item => item.run_id === card.dataset.resultRun);
            card.querySelector('[data-focus-node]')?.addEventListener('click', () => global.SmartImageAgentBridge.focusNode(result.target_node_id));
            card.querySelector('[data-use-result]')?.addEventListener('click', () => {
                continueFromResult(result, '继续修改这张图片：');
            });
            card.querySelector('[data-variant-result]')?.addEventListener('click', () => continueFromResult(result, '基于这张图片生成四个视觉变体：', 'create_variants', 4));
            card.querySelector('[data-expand-result]')?.addEventListener('click', () => continueFromResult(result, '扩展画面并自然补全背景：', 'expand_image'));
            card.querySelector('[data-save-result]')?.addEventListener('click', async () => {
                try {
                    await global.SmartImageAgentBridge.saveToAssetLibrary(result);
                    notify('已保存到素材库', 'success');
                } catch(error) { notify(error.message, 'error'); }
            });
        });
        refreshIcons();
    }
    function continueFromResult(result, prefix, action='', count=1){
        state.selectedResultGroup = state.results.filter(item => item.plan_id === result.plan_id)
            .sort((left, right) => Number(left.sequence || 0) - Number(right.sequence || 0));
        state.manualRefs = [{...result, node_id:result.target_node_id, name:'上一轮结果', role:'edit_target'}];
        state.referenceRoles.set(referenceKey(state.manualRefs[0]), 'edit_target');
        state.pendingAction = action;
        els.count.value = String(count);
        els.input.value = prefix;
        els.activity.scrollTo({top:0, behavior:'smooth'});
        renderReferences();
        els.input.focus();
        notify('已引用结果，可直接继续创作');
    }
    function setCollapsed(collapsed){
        els.root.classList.toggle('is-collapsed', collapsed);
        document.body.classList.toggle('smart-image-agent-v2-collapsed', collapsed);
        writeSetting('collapsed', collapsed ? '1' : '0');
        els.collapse.innerHTML = `<i data-lucide="${collapsed ? 'chevrons-left' : 'chevrons-right'}"></i>`;
        els.collapse.title = collapsed ? '展开图片 Agent' : '收起图片 Agent';
        refreshIcons();
        setTimeout(() => global.dispatchEvent(new Event('resize')), 180);
    }
    function applyWidth(width){
        const value = Math.max(320, Math.min(560, Number(width) || 400));
        document.documentElement.style.setProperty('--smart-image-agent-width', `${value}px`);
        writeSetting('width', value);
    }
    function bindResize(){
        els.resizer.addEventListener('pointerdown', event => {
            if(els.root.classList.contains('is-collapsed')) return;
            event.preventDefault();
            const startX = event.clientX;
            const startWidth = els.root.getBoundingClientRect().width;
            const move = next => applyWidth(startWidth + startX - next.clientX);
            const end = () => {
                document.removeEventListener('pointermove', move);
                document.removeEventListener('pointerup', end);
                global.dispatchEvent(new Event('resize'));
            };
            document.addEventListener('pointermove', move);
            document.addEventListener('pointerup', end, {once:true});
        });
    }
    async function refreshSessions(){
        const context = global.SmartImageAgentBridge.getCanvasContext();
        if(!context.canvas_id) return [];
        const data = await api(`/api/smart-image-agent/sessions?canvas_id=${encodeURIComponent(context.canvas_id)}`);
        state.sessions = data.sessions || [];
        renderSessionHistory();
        return state.sessions;
    }
    function renderSessionHistory(){
        if(!els.sessionHistory) return;
        els.sessionHistory.innerHTML = state.sessions.length ? state.sessions.map(session => `
            <div class="sia-session-item" data-session-id="${escapeHtml(session.id)}">
                <button type="button" data-open-session title="${escapeHtml(session.title || '未命名创作')}">${escapeHtml(session.title || '未命名创作')}</button>
                <button type="button" data-archive-session title="归档"><i data-lucide="archive"></i></button>
            </div>
        `).join('') : '<div class="sia-empty">暂无历史创作</div>';
        els.sessionHistory.querySelectorAll('[data-session-id]').forEach(row => {
            row.querySelector('[data-open-session]')?.addEventListener('click', () => switchSession(row.dataset.sessionId));
            row.querySelector('[data-archive-session]')?.addEventListener('click', () => archiveSession(row.dataset.sessionId));
        });
        refreshIcons();
    }
    function resetSessionTransientState(){
        state.manualRefs = [];
        state.referenceRoles.clear();
        state.selectedResultGroup = [];
        state.pendingAction = '';
    }
    async function switchSession(sessionId){
        if(!sessionId || sessionId === state.session?.id) return;
        resetSessionTransientState();
        renderReferences();
        state.session = null;
        writeSetting('session', sessionId);
        await loadSession(sessionId);
        els.sessionHistory.hidden = true;
        notify('已恢复该创作会话', 'success');
    }
    async function createNewSession(){
        resetSessionTransientState();
        state.session = null;
        state.plans.clear();
        state.currentPlan = null;
        state.runs = [];
        state.results = [];
        writeSetting('session', '');
        await loadSession();
        renderReferences(); renderPlan(); renderTasks(); renderResults();
        els.input.value = '';
        els.input.focus();
        notify('已新建创作会话');
    }
    async function archiveSession(sessionId){
        try {
            const context = global.SmartImageAgentBridge.getCanvasContext();
            await api(`/api/smart-image-agent/sessions/${encodeURIComponent(sessionId)}?canvas_id=${encodeURIComponent(context.canvas_id)}`, {
                method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({archived:true}),
            });
            if(sessionId === state.session?.id) await createNewSession();
            await refreshSessions();
        } catch(error) { notify(error.message, 'error'); }
    }
    async function loadSession(requestedId=''){
        const context = global.SmartImageAgentBridge.getCanvasContext();
        const stored = requestedId || readSetting('session', '');
        if(stored){
            try {
                state.session = await api(`/api/smart-image-agent/sessions/${encodeURIComponent(stored)}?canvas_id=${encodeURIComponent(context.canvas_id)}`);
            } catch(_error) { writeSetting('session', ''); }
        }
        if(!state.session){
            state.session = await api('/api/smart-image-agent/sessions', {
                method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(context)
            });
            writeSetting('session', state.session.id);
        }
        state.plans.clear();
        (state.session.plans || []).forEach(plan => state.plans.set(plan.id, plan));
        state.currentPlan = [...state.plans.values()].reverse().find(plan => plan.status === 'awaiting_confirmation') || null;
        const runData = await api(`/api/smart-image-agent/runs?session_id=${encodeURIComponent(state.session.id)}&canvas_id=${encodeURIComponent(context.canvas_id)}`);
        state.runs = runData.runs || [];
        const resultData = await api(`/api/smart-image-agent/sessions/${encodeURIComponent(state.session.id)}/results?canvas_id=${encodeURIComponent(context.canvas_id)}`);
        state.results = resultData.results || [];
        for(const run of state.runs.filter(item => item.status === 'running')){
            try {
                const failed = await api(`/api/smart-image-agent/runs/${encodeURIComponent(run.id)}`, {
                    method:'PATCH', headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({status:'failed', error:'页面刷新后任务执行已中断，请重试'})
                });
                Object.assign(run, failed);
            } catch(_error) {}
        }
        renderTasks();
        renderResults();
        renderPlan();
        refreshSessions().catch(() => {});
        processQueue();
        return state.session;
    }
    async function ensureSession(){
        if(state.session) return state.session;
        if(!state.sessionPromise) state.sessionPromise = loadSession();
        try { return await state.sessionPromise; }
        finally { state.sessionPromise = null; }
    }
    async function createPlan(){
        const message = els.input.value.trim();
        if(!message) return;
        if(state.currentPlan?.status === 'awaiting_confirmation'){
            notify('请先确认、编辑或放弃当前方案', 'error');
            return;
        }
        const resultMatch = message.match(/第\s*(\d+)\s*张/);
        if(resultMatch && state.selectedResultGroup.length){
            const selected = state.selectedResultGroup[Number(resultMatch[1]) - 1];
            if(selected){
                state.manualRefs = [{...selected, node_id:selected.target_node_id, name:`第 ${resultMatch[1]} 张结果`, role:'edit_target'}];
                state.referenceRoles.set(referenceKey(state.manualRefs[0]), 'edit_target');
                renderReferences();
            }
        }
        const references = combinedRefs();
        if(references.length > 10){ notify('单次最多引用 10 张图片', 'error'); return; }
        const context = {...global.SmartImageAgentBridge.getCanvasContext(), selected_images:references};
        els.create.disabled = true;
        notify('正在整理图片方案...');
        try {
            if(!state.session) await ensureSession();
            await api(`/api/smart-image-agent/sessions/${encodeURIComponent(state.session.id)}/messages`, {
                method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({content:message, context})
            });
            const plan = await api('/api/smart-image-agent/plans', {
                method:'POST', headers:{'Content-Type':'application/json'},
                body:JSON.stringify({
                    session_id:state.session.id,
                    message,
                    context,
                    ratio:els.ratio.value,
                    count:Number(els.count.value) || 1,
                    model:els.model.value,
                    quality:modelPolicy(els.model.value).quality,
                    action:state.pendingAction
                })
            });
            state.currentPlan = plan;
            state.plans.set(plan.id, plan);
            state.pendingAction = '';
            renderPlan();
            refreshSessions().catch(() => {});
            notify('方案已准备，确认后才会开始生成', 'success');
        } catch(error) { notify(error.message, 'error'); }
        finally { els.create.disabled = false; }
    }
    async function updatePlan(field, value){
        if(!state.currentPlan) return;
        try {
            const updated = await api(`/api/smart-image-agent/plans/${encodeURIComponent(state.currentPlan.id)}`, {
                method:'PATCH', headers:{'Content-Type':'application/json'},
                body:JSON.stringify({[field]:value, model:field === 'model' ? value : state.currentPlan.model, quality:modelPolicy(field === 'model' ? value : state.currentPlan.model).quality})
            });
            state.currentPlan = updated;
            state.plans.set(updated.id, updated);
            renderPlan();
        } catch(error) { notify(error.message, 'error'); renderPlan(); }
    }
    async function dismissCurrentPlan(){
        const plan = state.currentPlan;
        if(!plan || plan.status !== 'awaiting_confirmation') return;
        try {
            const dismissed = await api(`/api/smart-image-agent/plans/${encodeURIComponent(plan.id)}`, {
                method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status:'cancelled', model:plan.model, quality:modelPolicy(plan.model).quality})
            });
            state.plans.set(dismissed.id, dismissed);
            state.currentPlan = null;
            renderPlan();
            notify('已放弃该方案');
        } catch(error) { notify(error.message, 'error'); }
    }
    async function confirmCurrentPlan(){
        const plan = state.currentPlan;
        if(!plan || plan.status !== 'awaiting_confirmation') return;
        try {
            const confirmed = await api(`/api/smart-image-agent/plans/${encodeURIComponent(plan.id)}/confirm`, {method:'POST'});
            state.currentPlan = confirmed.plan;
            state.plans.set(confirmed.plan.id, confirmed.plan);
            confirmed.runs.forEach(run => {
                const index = state.runs.findIndex(item => item.id === run.id);
                if(index >= 0) state.runs[index] = run;
                else state.runs.push(run);
            });
            renderPlan();
            renderTasks();
            els.tasks.closest('.sia-activity-section')?.scrollIntoView({block:'start', behavior:'smooth'});
            processQueue();
        } catch(error) { notify(error.message, 'error'); }
    }
    function runById(id){ return state.runs.find(run => run.id === id); }
    async function processRun(run){
        const sessionId = run.session_id || state.session?.id;
        state.activeRuns += 1;
        try {
            const started = await api(`/api/smart-image-agent/runs/${encodeURIComponent(run.id)}`, {
                method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status:'running', progress_stage:'preparing'})
            });
            Object.assign(run, started);
            renderTasks();
            const plan = state.plans.get(run.plan_id);
            if(!plan) throw new Error('任务方案已失效，请重新创建');
            const generating = await api(`/api/smart-image-agent/runs/${encodeURIComponent(run.id)}`, {
                method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status:'running', progress_stage:'generating'})
            });
            Object.assign(run, generating);
            renderTasks();
            const result = await global.SmartImageAgentBridge.runImageTask(run, plan, {
                isCancelled:() => state.cancelled.has(run.id)
            });
            if(state.cancelled.has(run.id) || result?.cancelled) return;
            const saving = await api(`/api/smart-image-agent/runs/${encodeURIComponent(run.id)}`, {
                method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status:'running', progress_stage:'saving'})
            });
            Object.assign(run, saving);
            renderTasks();
            const completed = await api(`/api/smart-image-agent/runs/${encodeURIComponent(run.id)}`, {
                method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status:'succeeded', progress_stage:'completed', result})
            });
            Object.assign(run, completed);
            if(state.session?.id === sessionId){
                state.results.unshift({run_id:run.id, plan_id:run.plan_id, session_id:run.session_id, ...result});
                renderResults();
            }
            await global.SmartImageAgentBridge.saveCanvas();
        } catch(error) {
            if(!state.cancelled.has(run.id)){
                try {
                    const failed = await api(`/api/smart-image-agent/runs/${encodeURIComponent(run.id)}`, {
                        method:'PATCH', headers:{'Content-Type':'application/json'},
                        body:JSON.stringify({status:'failed', error:String(error.message || error).slice(0, 1000)})
                    });
                    Object.assign(run, failed);
                } catch(_ignored) { run.status = 'failed'; run.error = error.message || String(error); }
            }
        } finally {
            state.activeRuns -= 1;
            renderTasks();
            processQueue();
        }
    }
    function processQueue(){
        while(state.activeRuns < 2){
            const next = state.runs.find(run => run.status === 'queued' && !state.cancelled.has(run.id));
            if(!next) break;
            next.status = 'starting';
            processRun(next);
        }
    }
    async function cancelRun(id){
        const run = runById(id);
        if(!run || !['queued','running','starting'].includes(run.status)) return;
        state.cancelled.add(id);
        try {
            const cancelled = await api(`/api/smart-image-agent/runs/${encodeURIComponent(id)}/cancel`, {method:'POST'});
            Object.assign(run, cancelled);
        } catch(error) { notify(error.message, 'error'); }
        renderTasks();
    }
    async function retryRun(id){
        const run = runById(id);
        if(!run) return;
        try {
            state.cancelled.delete(id);
            const retried = await api(`/api/smart-image-agent/runs/${encodeURIComponent(id)}/retry`, {method:'POST'});
            Object.assign(run, retried);
            renderTasks();
            processQueue();
        } catch(error) { notify(error.message, 'error'); }
    }
    async function uploadFiles(files){
        try {
            const images = [...files].filter(file => String(file?.type || '').startsWith('image/'));
            if(combinedRefs().length + images.length > 10){
                notify('单次最多引用 10 张图片，请减少后再上传', 'error');
                return;
            }
            const uploaded = await global.SmartImageAgentBridge.uploadReferences(images);
            addManualReferences(uploaded);
        } catch(error) { notify(error.message, 'error'); }
    }
    async function loadAssets(){
        const context = global.SmartImageAgentBridge.getCanvasContext();
        const items = [];
        try {
            const local = await api('/api/local-assets');
            (local.items || []).forEach(item => items.push({
                asset_id:item.id || item.file || '', url:item.url || item.path || '',
                preview_url:item.preview_url || item.thumbnail_url || item.url || '', name:item.name || item.file || '素材'
            }));
        } catch(_error) {}
        if(context.team_id){
            try {
                const team = await api(`/api/team-cloud/teams/${encodeURIComponent(context.team_id)}/assets`);
                (team.assets || []).forEach(item => {
                    const normalized = global.TeamAssets?.normalizeTeamAsset?.(item) || item;
                    items.push({asset_id:normalized.id || '', url:normalized.previewUrl || normalized.url || '', preview_url:normalized.thumbnailPreviewUrl || normalized.thumbnailUrl || normalized.url || '', name:normalized.name || '团队素材'});
                });
            } catch(_error) {}
        }
        state.assetCache = items.filter(item => item.url);
        return state.assetCache;
    }
    async function openAssetPicker(){
        els.assetPicker.hidden = false;
        els.assetGrid.innerHTML = '<div class="sia-empty">正在加载素材...</div>';
        const assets = state.assetCache.length ? state.assetCache : await loadAssets();
        renderAssetPicker(assets);
    }
    function renderAssetPicker(items){
        els.assetGrid.innerHTML = items.length ? items.slice(0, 100).map((item, index) => `
            <button type="button" data-asset-index="${index}" title="${escapeHtml(item.name)}"><img src="${escapeHtml(item.preview_url || item.url)}" alt="${escapeHtml(item.name)}"><span>${escapeHtml(item.name)}</span></button>
        `).join('') : '<div class="sia-empty">暂无可用图片素材</div>';
        els.assetGrid.querySelectorAll('[data-asset-index]').forEach(button => button.addEventListener('click', () => {
            const item = items[Number(button.dataset.assetIndex)];
            if(addManualReferences(item)) els.assetPicker.hidden = true;
        }));
    }
    function renderMentionSuggestions(){
        const match = els.input.value.slice(0, els.input.selectionStart).match(/@([^\s@]*)$/);
        if(!match){ els.mentions.hidden = true; return; }
        const query = match[1];
        const canvasItems = global.SmartImageAgentBridge.searchCanvasImages(query);
        const assets = state.assetCache.filter(item => !query || item.name.toLowerCase().includes(query.toLowerCase()));
        const items = [...canvasItems, ...assets].slice(0, 8);
        els.mentions.hidden = false;
        els.mentions.innerHTML = items.length ? items.map((item, index) => `<button type="button" data-mention-index="${index}"><img src="${escapeHtml(item.preview_url || item.url)}" alt=""><span>${escapeHtml(item.name || item.prompt || '画布图片')}</span></button>`).join('') : '<span>没有匹配图片</span>';
        els.mentions.querySelectorAll('[data-mention-index]').forEach(button => button.addEventListener('click', () => {
            const item = items[Number(button.dataset.mentionIndex)];
            if(!addManualReferences(item)) return;
            const start = els.input.selectionStart - match[0].length;
            els.input.value = els.input.value.slice(0, start) + els.input.value.slice(els.input.selectionStart);
            els.mentions.hidden = true;
            els.input.focus();
        }));
    }
    function selectSkill(skill){
        const presets = {
            poster:{message:'生成一张高级视觉海报：', action:'generate_image', count:1, ratio:'4:5'},
            product:{message:'为产品制作电商商品主图：', action:'generate_image', count:1, ratio:'1:1'},
            social:{message:'生成四张统一视觉方向的社媒套图：', action:'generate_image_set', count:4, ratio:'4:5'},
            variants:{message:'基于引用图片生成四个视觉变体：', action:'create_variants', count:4, ratio:'auto'},
            expand:{message:'扩展画面并自然补全背景：', action:'expand_image', count:1, ratio:'auto'},
            compose:{message:'融合引用图片并保持主体一致：', action:'compose_images', count:1, ratio:'auto'}
        };
        const preset = presets[skill];
        if(!preset) return;
        state.pendingAction = preset.action;
        els.input.value = preset.message;
        els.count.value = String(preset.count);
        els.ratio.value = preset.ratio;
        els.input.focus();
    }
    function runCanvasControl(control){
        const canvasControls = global.SmartImageAgentBridge?.canvasControls;
        if(!canvasControls) return;
        const actions = {
            fitAll:() => canvasControls.fitAll(),
            zoomIn:() => canvasControls.zoomIn(),
            zoomOut:() => canvasControls.zoomOut(),
            resetZoom:() => canvasControls.resetZoom(),
            arrangeSelection:() => canvasControls.arrangeSelection()
        };
        actions[control]?.();
    }
    function buildUi(){
        const oldPanel = document.getElementById('agentPanel');
        if(oldPanel) oldPanel.remove();
        document.body.classList.add('smart-image-agent-v2-open');
        const root = document.createElement('aside');
        root.id = 'smartImageAgent';
        root.className = 'smart-image-agent';
        root.innerHTML = `
            <div class="sia-resizer" aria-hidden="true"></div>
            <header class="sia-header">
                <div class="sia-brand"><i data-lucide="wand-sparkles"></i><div><strong>图片 Agent</strong><span>智能画布协作</span></div></div>
                <div class="sia-header-actions">
                    <button class="sia-icon" type="button" data-new-session title="新建创作"><i data-lucide="plus"></i></button>
                    <button class="sia-icon" type="button" data-session-history title="创作历史"><i data-lucide="history"></i></button>
                    <button class="sia-icon" type="button" data-collapse title="收起图片 Agent"><i data-lucide="chevrons-right"></i></button>
                </div>
            </header>
            <div class="sia-canvas-controls" aria-label="画布控制">
                <button type="button" data-canvas-control="fitAll" title="适应全部节点"><i data-lucide="scan"></i></button>
                <button type="button" data-canvas-control="zoomIn" title="放大"><i data-lucide="zoom-in"></i></button>
                <button type="button" data-canvas-control="zoomOut" title="缩小"><i data-lucide="zoom-out"></i></button>
                <button type="button" data-canvas-control="resetZoom" title="重置缩放"><i data-lucide="rotate-ccw"></i></button>
                <button type="button" data-canvas-control="arrangeSelection" title="整理选中节点"><i data-lucide="layout-grid"></i></button>
            </div>
            <div class="sia-collapsed-entry"><button type="button" data-expand title="展开图片 Agent"><i data-lucide="wand-sparkles"></i><b data-collapsed-count>0</b></button></div>
            <main class="sia-activity" data-activity>
            <section class="sia-context">
                <div class="sia-ref-head"><span>图片引用</span><b data-ref-count>0/10</b></div>
                <div class="sia-refs" data-refs></div>
                <div class="sia-source-actions">
                    <button type="button" data-upload><i data-lucide="upload"></i><span>上传图片</span></button>
                    <button type="button" data-assets><i data-lucide="library"></i><span>素材库</span></button>
                    <input type="file" accept="image/*" multiple hidden data-file-input>
                </div>
                <div class="sia-quick">
                    <button type="button" data-skill="poster">海报</button>
                    <button type="button" data-skill="product">商品主图</button>
                    <button type="button" data-skill="social">社媒套图</button>
                    <button type="button" data-skill="variants">风格变体</button>
                    <button type="button" data-skill="expand">扩图补景</button>
                    <button type="button" data-skill="compose">多图合成</button>
                </div>
            </section>
            <section class="sia-activity-section"><div class="sia-plan" data-plan hidden></div></section>
            <section class="sia-activity-section"><div class="sia-section-title"><span>任务</span></div><div class="sia-list" data-tasks></div></section>
            <section class="sia-activity-section"><div class="sia-section-title"><span>结果</span></div><div class="sia-results" data-results></div></section>
            </main>
            <div class="sia-composer">
                <textarea data-input rows="4" placeholder="描述要生成或修改的图片，输入 @ 引用画布或素材图片"></textarea>
                <div class="sia-mentions" data-mentions hidden></div>
                <div class="sia-settings">
                    <label class="sia-model-control"><span>模型</span><select data-model>${modelOptions('nano-banana-2')}</select></label>
                    <label><span>比例</span><select data-ratio><option value="auto">自动</option><option>1:1</option><option>4:5</option><option>16:9</option><option>9:16</option></select></label>
                    <label><span>数量</span><input data-count type="number" min="1" max="8" value="1"></label>
                </div>
                <button class="sia-primary" type="button" data-create disabled><i data-lucide="arrow-up"></i><span>生成方案</span></button>
                <div class="sia-notice" data-notice hidden></div>
            </div>
            <div class="sia-asset-picker" data-asset-picker hidden>
                <div class="sia-picker-head"><strong>选择图片素材</strong><button type="button" data-close-assets title="关闭"><i data-lucide="x"></i></button></div>
                <input type="search" data-asset-search placeholder="搜索素材">
                <div class="sia-asset-grid" data-asset-grid></div>
            </div>
            <div class="sia-session-history" data-session-history-panel hidden></div>`;
        document.body.appendChild(root);
        els.root = root;
        els.resizer = root.querySelector('.sia-resizer');
        els.collapse = root.querySelector('[data-collapse]');
        els.activity = root.querySelector('[data-activity]');
        els.refs = root.querySelector('[data-refs]');
        els.refCount = root.querySelector('[data-ref-count]');
        els.collapsedCount = root.querySelector('[data-collapsed-count]');
        els.input = root.querySelector('[data-input]');
        els.mentions = root.querySelector('[data-mentions]');
        els.ratio = root.querySelector('[data-ratio]');
        els.count = root.querySelector('[data-count]');
        els.model = root.querySelector('[data-model]');
        els.create = root.querySelector('[data-create]');
        els.plan = root.querySelector('[data-plan]');
        els.tasks = root.querySelector('[data-tasks]');
        els.results = root.querySelector('[data-results]');
        els.notice = root.querySelector('[data-notice]');
        els.fileInput = root.querySelector('[data-file-input]');
        els.assetPicker = root.querySelector('[data-asset-picker]');
        els.assetGrid = root.querySelector('[data-asset-grid]');
        els.assetSearch = root.querySelector('[data-asset-search]');
        els.sessionHistory = root.querySelector('[data-session-history-panel]');
        els.collapse.addEventListener('click', () => setCollapsed(!root.classList.contains('is-collapsed')));
        root.querySelector('[data-expand]').addEventListener('click', () => setCollapsed(false));
        root.querySelector('[data-upload]').addEventListener('click', () => els.fileInput.click());
        root.querySelector('[data-assets]').addEventListener('click', openAssetPicker);
        root.querySelector('[data-close-assets]').addEventListener('click', () => { els.assetPicker.hidden = true; });
        root.querySelector('[data-new-session]').addEventListener('click', createNewSession);
        root.querySelector('[data-session-history]').addEventListener('click', () => {
            els.sessionHistory.hidden = !els.sessionHistory.hidden;
            if(!els.sessionHistory.hidden) refreshSessions().catch(error => notify(error.message, 'error'));
        });
        root.querySelectorAll('[data-canvas-control]').forEach(button => button.addEventListener('click', () => runCanvasControl(button.dataset.canvasControl)));
        els.fileInput.addEventListener('change', () => { uploadFiles(els.fileInput.files); els.fileInput.value = ''; });
        els.create.addEventListener('click', createPlan);
        els.input.addEventListener('input', renderMentionSuggestions);
        els.input.addEventListener('keydown', event => {
            if((event.ctrlKey || event.metaKey) && event.key === 'Enter'){ event.preventDefault(); createPlan(); }
        });
        root.querySelectorAll('[data-skill]').forEach(button => button.addEventListener('click', () => selectSkill(button.dataset.skill)));
        els.assetSearch.addEventListener('input', () => renderAssetPicker(state.assetCache.filter(item => item.name.toLowerCase().includes(els.assetSearch.value.trim().toLowerCase()))));
        ['dragenter','dragover'].forEach(type => root.querySelector('.sia-context').addEventListener(type, event => { event.preventDefault(); root.classList.add('is-dragging'); }));
        root.querySelector('.sia-context').addEventListener('dragleave', () => root.classList.remove('is-dragging'));
        root.querySelector('.sia-context').addEventListener('drop', event => {
            event.preventDefault(); root.classList.remove('is-dragging'); uploadFiles(event.dataTransfer.files);
        });
        bindResize();
        applyWidth(readSetting('width', '400'));
        setCollapsed(readSetting('collapsed', '0') === '1');
        renderReferences(); renderTasks(); renderResults();
        refreshIcons();
        const toolbarToggle = document.getElementById('agentToggle');
        toolbarToggle?.addEventListener('click', () => setCollapsed(!root.classList.contains('is-collapsed')));
        global.toggleAgentPanel = () => setCollapsed(!root.classList.contains('is-collapsed'));
    }
    async function init(){
        if(state.initialized) return;
        if(!global.SmartImageAgentBridge){ console.error('[smart-image-agent] bridge unavailable'); return; }
        state.initialized = true;
        buildUi();
        state.unsubscribe = global.SmartImageAgentBridge.subscribeSelection(selection => {
            state.selectionRefs = Array.isArray(selection) ? selection : [];
            renderReferences();
        });
        loadAssets();
        try { await ensureSession(); }
        catch(error) { notify(error.message || '图片 Agent 初始化失败', 'error'); }
        finally { els.create.disabled = false; }
    }

    global.SmartImageAgentApp = {init};
})(window);
