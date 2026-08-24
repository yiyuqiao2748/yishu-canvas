(function(global){
    const STORAGE_PREFIX = 'smartImageAgentV2';
    const state = {
        session:null,
        plans:new Map(),
        currentPlan:null,
        runs:[],
        results:[],
        selectionRefs:[],
        manualRefs:[],
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
        });
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
    function renderReferences(){
        const refs = combinedRefs();
        els.refs.innerHTML = refs.length ? refs.map((item, index) => `
            <div class="sia-ref" data-ref-index="${index}">
                <img src="${escapeHtml(item.preview_url || item.url)}" alt="${escapeHtml(referenceLabel(item, index))}">
                <button type="button" data-remove-ref="${index}" title="移除参考图"><i data-lucide="x"></i></button>
            </div>
        `).join('') : '<div class="sia-empty-ref"><i data-lucide="image-plus"></i><span>选中画布图片或添加参考图</span></div>';
        els.refCount.textContent = `${refs.length}/10`;
        els.refCount.classList.toggle('is-over-limit', refs.length > 10);
        if(refs.length > 10) notify(`已引用 ${refs.length} 张图片，请减少到 10 张后再生成`, 'error');
        els.refs.querySelectorAll('[data-remove-ref]').forEach(button => {
            button.addEventListener('click', () => {
                const target = refs[Number(button.dataset.removeRef)];
                state.manualRefs = state.manualRefs.filter(item => item !== target);
                state.selectionRefs = state.selectionRefs.filter(item => item !== target);
                renderReferences();
            });
        });
        refreshIcons();
    }
    function actionLabel(action){
        return {
            generate_image:'新图生成', edit_image:'选图修改', compose_images:'多图合成',
            create_variants:'创建变体', expand_image:'扩图补景', generate_image_set:'批量套图',
            organize_results:'整理结果'
        }[action] || '图片创作';
    }
    function modelLabel(plan){
        return plan?.model === 'nano-banana-pro' ? 'Nano Banana Pro' : 'Nano Banana 2';
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
            <div class="sia-plan-controls">
                <label><span>比例</span><select data-plan-field="ratio">
                    ${['auto','1:1','4:5','16:9','9:16','4:3','3:4','21:9'].map(value => `<option value="${value}" ${value === plan.ratio ? 'selected' : ''}>${value === 'auto' ? '自动' : value}</option>`).join('')}
                </select></label>
                <label><span>数量</span><input data-plan-field="count" type="number" min="1" max="8" value="${Number(plan.count) || 1}"></label>
                <label><span>质量</span><select data-plan-field="quality">
                    <option value="standard" ${plan.quality !== 'pro' ? 'selected' : ''}>标准</option>
                    <option value="pro" ${plan.quality === 'pro' ? 'selected' : ''}>高质量</option>
                </select></label>
            </div>
            <div class="sia-plan-cost"><span>预计消耗</span><strong>${Number(plan.estimated_points) || 0} 灵感点</strong></div>
            <button class="sia-primary" type="button" data-confirm-plan ${plan.status !== 'awaiting_confirmation' ? 'disabled' : ''}>
                <i data-lucide="sparkles"></i><span>${Number(plan.count) > 1 ? '全部生成' : '生成'}</span>
            </button>`;
        els.plan.querySelectorAll('[data-plan-field]').forEach(control => {
            control.addEventListener('change', () => updatePlan(control.dataset.planField, control.type === 'number' ? Number(control.value) : control.value));
        });
        els.plan.querySelector('[data-confirm-plan]')?.addEventListener('click', confirmCurrentPlan);
        refreshIcons();
    }
    function statusLabel(status){
        return {queued:'排队中', running:'生成中', succeeded:'已完成', failed:'失败', cancelled:'已取消'}[status] || status;
    }
    function renderTasks(){
        const runs = state.runs.slice().sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
        els.taskBadge.textContent = String(runs.filter(run => ['queued','running'].includes(run.status)).length || '');
        els.taskBadge.hidden = !runs.some(run => ['queued','running'].includes(run.status));
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
                <div class="sia-task-state" data-state="${escapeHtml(run.status)}"><span></span>${escapeHtml(statusLabel(run.status))}</div>
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
        els.resultCount.textContent = String(state.results.length);
        els.results.innerHTML = state.results.length ? state.results.map(result => `
            <article class="sia-result" data-result-run="${escapeHtml(result.run_id)}">
                <button class="sia-result-image" type="button" data-focus-node="${escapeHtml(result.target_node_id || '')}">
                    <img src="${escapeHtml(result.preview_url || result.url)}" alt="生成结果">
                </button>
                <div class="sia-result-actions">
                    <button type="button" data-use-result title="继续修改"><i data-lucide="wand-sparkles"></i></button>
                    <button type="button" data-save-result title="保存素材库"><i data-lucide="archive"></i></button>
                    <a href="${escapeHtml(result.url)}" download title="下载"><i data-lucide="download"></i></a>
                </div>
            </article>`).join('') : '<div class="sia-empty"><i data-lucide="images"></i><span>生成结果会保留在这里</span></div>';
        els.results.querySelectorAll('[data-result-run]').forEach(card => {
            const result = state.results.find(item => item.run_id === card.dataset.resultRun);
            card.querySelector('[data-focus-node]')?.addEventListener('click', () => global.SmartImageAgentBridge.focusNode(result.target_node_id));
            card.querySelector('[data-use-result]')?.addEventListener('click', () => {
                state.manualRefs = [{...result, node_id:result.target_node_id, name:'上一轮结果'}];
                switchTab('create');
                renderReferences();
                els.input.focus();
                notify('已引用该结果，可继续描述修改');
            });
            card.querySelector('[data-save-result]')?.addEventListener('click', async () => {
                try {
                    await global.SmartImageAgentBridge.saveToAssetLibrary(result);
                    notify('已保存到素材库', 'success');
                } catch(error) { notify(error.message, 'error'); }
            });
        });
        refreshIcons();
    }
    function switchTab(tab){
        els.root.dataset.tab = tab;
        els.tabs.forEach(button => button.classList.toggle('active', button.dataset.agentTab === tab));
        els.views.forEach(view => view.hidden = view.dataset.agentView !== tab);
        writeSetting('tab', tab);
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
    async function loadSession(){
        const context = global.SmartImageAgentBridge.getCanvasContext();
        const stored = readSetting('session', '');
        if(stored){
            try {
                state.session = await api(`/api/smart-image-agent/sessions/${encodeURIComponent(stored)}`);
            } catch(_error) { writeSetting('session', ''); }
        }
        if(!state.session){
            state.session = await api('/api/smart-image-agent/sessions', {
                method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(context)
            });
            writeSetting('session', state.session.id);
        }
        (state.session.plans || []).forEach(plan => state.plans.set(plan.id, plan));
        const runData = await api(`/api/smart-image-agent/runs?session_id=${encodeURIComponent(state.session.id)}`);
        state.runs = runData.runs || [];
        const resultData = await api(`/api/smart-image-agent/sessions/${encodeURIComponent(state.session.id)}/results`);
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
                    quality:els.quality.value
                })
            });
            state.currentPlan = plan;
            state.plans.set(plan.id, plan);
            renderPlan();
            notify('方案已准备，确认后才会开始生成', 'success');
        } catch(error) { notify(error.message, 'error'); }
        finally { els.create.disabled = false; }
    }
    async function updatePlan(field, value){
        if(!state.currentPlan) return;
        try {
            const updated = await api(`/api/smart-image-agent/plans/${encodeURIComponent(state.currentPlan.id)}`, {
                method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({[field]:value})
            });
            state.currentPlan = updated;
            state.plans.set(updated.id, updated);
            renderPlan();
        } catch(error) { notify(error.message, 'error'); renderPlan(); }
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
            switchTab('tasks');
            processQueue();
        } catch(error) { notify(error.message, 'error'); }
    }
    function runById(id){ return state.runs.find(run => run.id === id); }
    async function processRun(run){
        state.activeRuns += 1;
        try {
            const started = await api(`/api/smart-image-agent/runs/${encodeURIComponent(run.id)}`, {
                method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status:'running'})
            });
            Object.assign(run, started);
            renderTasks();
            const plan = state.plans.get(run.plan_id);
            if(!plan) throw new Error('任务方案已失效，请重新创建');
            const result = await global.SmartImageAgentBridge.runImageTask(run, plan, {
                isCancelled:() => state.cancelled.has(run.id)
            });
            if(state.cancelled.has(run.id) || result?.cancelled) return;
            const completed = await api(`/api/smart-image-agent/runs/${encodeURIComponent(run.id)}`, {
                method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status:'succeeded', result})
            });
            Object.assign(run, completed);
            state.results.unshift({run_id:run.id, plan_id:run.plan_id, session_id:run.session_id, ...result});
            renderResults();
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
                <button class="sia-icon" type="button" data-collapse title="收起图片 Agent"><i data-lucide="chevrons-right"></i></button>
            </header>
            <nav class="sia-tabs">
                <button type="button" data-agent-tab="create" class="active"><i data-lucide="sparkles"></i><span>创作</span></button>
                <button type="button" data-agent-tab="tasks"><i data-lucide="list-checks"></i><span>任务</span><b data-task-badge hidden></b></button>
                <button type="button" data-agent-tab="results"><i data-lucide="images"></i><span>结果</span><b data-result-count>0</b></button>
            </nav>
            <div class="sia-collapsed-entry"><button type="button" data-expand title="展开图片 Agent"><i data-lucide="wand-sparkles"></i><b data-collapsed-count>0</b></button></div>
            <section class="sia-view" data-agent-view="create">
                <div class="sia-ref-head"><span>图片引用</span><b data-ref-count>0/10</b></div>
                <div class="sia-refs" data-refs></div>
                <div class="sia-source-actions">
                    <button type="button" data-upload><i data-lucide="upload"></i><span>上传图片</span></button>
                    <button type="button" data-assets><i data-lucide="library"></i><span>素材库</span></button>
                    <input type="file" accept="image/*" multiple hidden data-file-input>
                </div>
                <div class="sia-quick">
                    <button type="button" data-quick="生成一张高级视觉海报">海报</button>
                    <button type="button" data-quick="基于选中图片创建四个视觉变体">变体</button>
                    <button type="button" data-quick="扩展画面并自然补全背景">扩图</button>
                    <button type="button" data-quick="融合所有参考图，保持主体一致">多图合成</button>
                </div>
                <div class="sia-composer">
                    <textarea data-input rows="4" placeholder="描述要生成或修改的图片，输入 @ 引用画布或素材图片"></textarea>
                    <div class="sia-mentions" data-mentions hidden></div>
                    <div class="sia-settings">
                        <label><span>比例</span><select data-ratio><option value="auto">自动</option><option>1:1</option><option>4:5</option><option>16:9</option><option>9:16</option></select></label>
                        <label><span>数量</span><input data-count type="number" min="1" max="8" value="1"></label>
                        <label><span>质量</span><select data-quality><option value="standard">标准</option><option value="pro">高质量</option></select></label>
                    </div>
                    <button class="sia-primary" type="button" data-create disabled><i data-lucide="arrow-up"></i><span>生成方案</span></button>
                </div>
                <div class="sia-plan" data-plan hidden></div>
            </section>
            <section class="sia-view" data-agent-view="tasks" hidden><div class="sia-list" data-tasks></div></section>
            <section class="sia-view" data-agent-view="results" hidden><div class="sia-results" data-results></div></section>
            <div class="sia-notice" data-notice hidden></div>
            <div class="sia-asset-picker" data-asset-picker hidden>
                <div class="sia-picker-head"><strong>选择图片素材</strong><button type="button" data-close-assets title="关闭"><i data-lucide="x"></i></button></div>
                <input type="search" data-asset-search placeholder="搜索素材">
                <div class="sia-asset-grid" data-asset-grid></div>
            </div>`;
        document.body.appendChild(root);
        els.root = root;
        els.resizer = root.querySelector('.sia-resizer');
        els.collapse = root.querySelector('[data-collapse]');
        els.tabs = [...root.querySelectorAll('[data-agent-tab]')];
        els.views = [...root.querySelectorAll('[data-agent-view]')];
        els.refs = root.querySelector('[data-refs]');
        els.refCount = root.querySelector('[data-ref-count]');
        els.taskBadge = root.querySelector('[data-task-badge]');
        els.resultCount = root.querySelector('[data-result-count]');
        els.collapsedCount = root.querySelector('[data-collapsed-count]');
        els.input = root.querySelector('[data-input]');
        els.mentions = root.querySelector('[data-mentions]');
        els.ratio = root.querySelector('[data-ratio]');
        els.count = root.querySelector('[data-count]');
        els.quality = root.querySelector('[data-quality]');
        els.create = root.querySelector('[data-create]');
        els.plan = root.querySelector('[data-plan]');
        els.tasks = root.querySelector('[data-tasks]');
        els.results = root.querySelector('[data-results]');
        els.notice = root.querySelector('[data-notice]');
        els.fileInput = root.querySelector('[data-file-input]');
        els.assetPicker = root.querySelector('[data-asset-picker]');
        els.assetGrid = root.querySelector('[data-asset-grid]');
        els.assetSearch = root.querySelector('[data-asset-search]');
        els.tabs.forEach(button => button.addEventListener('click', () => switchTab(button.dataset.agentTab)));
        els.collapse.addEventListener('click', () => setCollapsed(!root.classList.contains('is-collapsed')));
        root.querySelector('[data-expand]').addEventListener('click', () => setCollapsed(false));
        root.querySelector('[data-upload]').addEventListener('click', () => els.fileInput.click());
        root.querySelector('[data-assets]').addEventListener('click', openAssetPicker);
        root.querySelector('[data-close-assets]').addEventListener('click', () => { els.assetPicker.hidden = true; });
        els.fileInput.addEventListener('change', () => { uploadFiles(els.fileInput.files); els.fileInput.value = ''; });
        els.create.addEventListener('click', createPlan);
        els.input.addEventListener('input', renderMentionSuggestions);
        els.input.addEventListener('keydown', event => {
            if((event.ctrlKey || event.metaKey) && event.key === 'Enter'){ event.preventDefault(); createPlan(); }
        });
        root.querySelectorAll('[data-quick]').forEach(button => button.addEventListener('click', () => { els.input.value = button.dataset.quick; els.input.focus(); }));
        els.assetSearch.addEventListener('input', () => renderAssetPicker(state.assetCache.filter(item => item.name.toLowerCase().includes(els.assetSearch.value.trim().toLowerCase()))));
        ['dragenter','dragover'].forEach(type => root.querySelector('[data-agent-view="create"]').addEventListener(type, event => { event.preventDefault(); root.classList.add('is-dragging'); }));
        root.querySelector('[data-agent-view="create"]').addEventListener('dragleave', () => root.classList.remove('is-dragging'));
        root.querySelector('[data-agent-view="create"]').addEventListener('drop', event => {
            event.preventDefault(); root.classList.remove('is-dragging'); uploadFiles(event.dataTransfer.files);
        });
        bindResize();
        applyWidth(readSetting('width', '400'));
        setCollapsed(readSetting('collapsed', '0') === '1');
        switchTab(readSetting('tab', 'create'));
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
