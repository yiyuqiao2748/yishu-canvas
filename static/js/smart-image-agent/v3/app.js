import { renderActivity } from './activity.js';
import { createBridgeAdapter } from './bridge-adapter.js';
import { executeImageCapability } from './capability-runner.js';
import { bindComposer } from './composer.js';
import { createContextController } from './context.js';
import { renderPlanCard } from './plan-card.js';
import { renderResults } from './results.js';
import { createShell } from './shell.js';

(function(global){
    const state = {session:null, execution:null, events:[], context:null, activeRuns:0, cancelled:new Set()};
    let els;
    let bridge;

    function authHeaders(headers={}){
        const next = {...headers};
        try { const token = localStorage.getItem('teamCloudAccessToken') || ''; if(token) next.Authorization = `Bearer ${token}`; } catch(_error) {}
        return next;
    }
    async function api(path, options={}){
        const response = await fetch(path, {...options, credentials:'include', headers:authHeaders(options.headers || {})});
        if(!response.ok){
            let detail = '';
            try { detail = (await response.clone().json()).detail || ''; } catch(_error) { detail = await response.text().catch(() => ''); }
            throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
        }
        return response.status === 204 ? {} : response.json();
    }
    function notify(message, kind='info'){
        els.notice.textContent = message || '';
        els.notice.dataset.kind = kind;
        els.notice.hidden = !message;
        clearTimeout(notify.timer);
        if(message) notify.timer = setTimeout(() => { els.notice.hidden = true; }, 4200);
    }
    function render(){
        renderPlanCard(els, state.execution, {update:updatePlan, approve:approve, cancel:cancel});
        renderActivity(els, state.execution, state.events);
        renderResults(els, state.execution?.runs || [], bridge, {
            'continue-edit':run => continueFromResult(run, '编辑这张图片'),
            'create-variants':run => continueFromResult(run, '基于这张图片生成多个变体'),
            'expand-image':run => continueFromResult(run, '扩图并补全背景'),
            'save-result':saveResult
        });
    }
    function executionKey(){ return `smartImageAgentV3:${bridge.context().canvas_id || 'local'}:execution`; }
    function sessionKey(){ return `smartImageAgentV3:${bridge.context().canvas_id || 'local'}:session`; }
    async function ensureSession(){
        if(state.session) return state.session;
        const context = bridge.context();
        const saved = localStorage.getItem(sessionKey()) || '';
        if(saved){
            try { state.session = await api(`/api/smart-image-agent/sessions/${encodeURIComponent(saved)}?canvas_id=${encodeURIComponent(context.canvas_id)}`); } catch(_error) { localStorage.removeItem(sessionKey()); }
        }
        if(!state.session){
            state.session = await api('/api/smart-image-agent/sessions', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(context)});
            localStorage.setItem(sessionKey(), state.session.id);
        }
        return state.session;
    }
    async function loadEvents(){
        if(!state.execution) return;
        const response = await fetch(`/api/smart-image-agent/v3/executions/${encodeURIComponent(state.execution.id)}/events`, {credentials:'include', headers:authHeaders()});
        if(!response.ok) return;
        const text = await response.text();
        const received = [...text.matchAll(/^data:\s*(.+)$/gm)].map(match => { try { return JSON.parse(match[1]); } catch(_error) { return null; } }).filter(Boolean);
        state.events = received;
    }
    async function restore(){
        const executionId = localStorage.getItem(executionKey()) || '';
        if(!executionId) return;
        try { state.execution = await api(`/api/smart-image-agent/v3/executions/${encodeURIComponent(executionId)}`); await loadEvents(); render(); }
        catch(_error) { localStorage.removeItem(executionKey()); }
    }
    async function create(){
        const message = els.intent.value.trim();
        if(!message){
            notify('请先输入创作需求', 'error');
            els.intent.focus();
            return;
        }
        if(state.execution?.status === 'awaiting_confirmation'){ notify('请先确认、编辑或放弃当前方案', 'error'); return; }
        try {
            els.create.disabled = true;
            notify('理解需求并生成方案…');
            const session = await ensureSession();
            state.execution = await api('/api/smart-image-agent/v3/executions', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({session_id:session.id, message, context:state.context.build(), ratio:els.ratio.value, model:els.model.value, count:Number(els.count.value) || 1})});
            localStorage.setItem(executionKey(), state.execution.id);
            await loadEvents(); render(); notify('方案已生成，请确认成本后执行');
        } catch(error) { notify(error.message, 'error'); }
        finally { els.create.disabled = false; }
    }
    async function updatePlan(changes){
        if(!state.execution) return;
        try {
            state.execution = await api(`/api/smart-image-agent/v3/executions/${encodeURIComponent(state.execution.id)}/plan`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(changes)});
            recordFeedback({kind:'plan_edited', metadata:{fields:Object.keys(changes)}});
            await loadEvents(); render();
        } catch(error) { notify(error.message, 'error'); }
    }
    async function approve(){
        if(!state.execution) return;
        try {
            state.execution = await api(`/api/smart-image-agent/v3/executions/${encodeURIComponent(state.execution.id)}/approve`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({idempotency_key:state.execution.approval_key})});
            await loadEvents(); render(); notify('已确认，正在生成'); processQueue();
        } catch(error) { notify(error.message, 'error'); }
    }
    async function cancel(){
        if(!state.execution) return;
        try {
            state.execution = await api(`/api/smart-image-agent/v3/executions/${encodeURIComponent(state.execution.id)}/cancel`, {method:'POST'});
            recordFeedback({kind:'cancelled'});
            await loadEvents(); render(); notify('方案已取消');
        } catch(error) { notify(error.message, 'error'); }
    }
    async function processRun(run){
        state.activeRuns += 1;
        try {
            await executeImageCapability({api, bridge, run, plan:state.execution.plan, isCancelled:() => state.cancelled.has(run.id)});
        } catch(error) {
            if(!state.cancelled.has(run.id)) await api(`/api/smart-image-agent/runs/${encodeURIComponent(run.id)}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status:'failed', error:String(error.message || error).slice(0, 1000)})}).catch(() => {});
        } finally {
            state.activeRuns -= 1;
            state.execution = await api(`/api/smart-image-agent/v3/executions/${encodeURIComponent(state.execution.id)}`).catch(() => state.execution);
            await loadEvents(); render(); processQueue();
        }
    }
    function processQueue(){
        while(state.activeRuns < 2){
            const run = state.execution?.runs?.find(item => item.status === 'queued' && !state.cancelled.has(item.id));
            if(!run) break;
            run.status = 'starting'; processRun(run);
        }
    }
    function recordFeedback(payload){
        if(!state.execution) return;
        api(`/api/smart-image-agent/v3/executions/${encodeURIComponent(state.execution.id)}/feedback`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}).catch(() => {});
    }
    function continueFromResult(run, instruction){
        const result = run.result || {};
        state.context.add([{...result, node_id:result.target_node_id || '', role:'edit_target', name:'已生成结果'}]);
        els.intent.value = instruction;
        els.intent.focus();
        recordFeedback({kind:'continued', metadata:{source_run_id:run.id, instruction}});
        notify('已加入引用，请生成下一轮方案');
    }
    async function saveResult(run){
        try {
            await bridge.saveToAssetLibrary({...run.result, name:`agent-result-${run.sequence || 1}.png`});
            recordFeedback({kind:'adopted', metadata:{source_run_id:run.id}});
            notify('已保存到素材库');
        } catch(error) { notify(error.message, 'error'); }
    }
    async function init(){
        if(global.SmartImageAgentV3App?.initialized) return;
        bridge = createBridgeAdapter(global); els = createShell();
        state.context = createContextController(bridge, els, notify);
        Object.entries(bridge.canvasControls).forEach(([name, action]) => els.root.querySelector(`[data-canvas="${name}"]`)?.addEventListener('click', action));
        els.details.addEventListener('click', () => { els.eventDetails.open = !els.eventDetails.open; });
        bindComposer(els, create);
        global.SmartImageAgentV3App.initialized = true;
        try { await ensureSession(); await restore(); } catch(error) { notify(error.message, 'error'); }
    }
    global.SmartImageAgentV3App = {init, initialized:false};
})(window);
