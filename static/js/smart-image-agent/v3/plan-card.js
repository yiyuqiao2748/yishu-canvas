function escapeHtml(value){ return String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char])); }
const models = [['gpt-image-2','GPT Image 2'],['nano-banana-2','Nano Banana 2'],['nano-banana-pro','Nano Banana Pro'],['gpt-image-2-vip','GPT Image 2 VIP']];
export function renderPlanCard(els, execution, handlers){
    const plan = execution?.plan;
    if(!plan){ els.plan.hidden = true; return; }
    const editable = execution.status === 'awaiting_confirmation';
    els.plan.hidden = false;
    els.plan.innerHTML = `<div class="sia-plan-section-title">当前方案</div><div class="sia-plan-head"><span>${escapeHtml(plan.action)}</span><strong>${escapeHtml(plan.model)}</strong></div><textarea data-prompt ${editable ? '' : 'disabled'}>${escapeHtml(plan.prompt || '')}</textarea><div class="sia-plan-controls"><label>模型<select data-field="model" ${editable ? '' : 'disabled'}>${models.map(([id,label]) => `<option value="${id}" ${id === plan.model ? 'selected' : ''}>${label}</option>`).join('')}</select></label><label>比例<select data-field="ratio" ${editable ? '' : 'disabled'}>${['auto','1:1','4:5','16:9','9:16'].map(value => `<option value="${value}" ${value === plan.ratio ? 'selected' : ''}>${value}</option>`).join('')}</select></label><label>数量<input data-field="count" type="number" min="1" max="8" value="${Number(plan.count) || 1}" ${editable ? '' : 'disabled'}></label></div><div class="sia-plan-cost">预计消耗 <strong>${Number(plan.estimated_points) || 0} 灵感点</strong></div>${editable ? '<button class="sia-primary" type="button" data-approve>确认并生成</button><button class="sia-secondary" type="button" data-cancel>放弃方案</button>' : ''}`;
    els.plan.querySelector('[data-prompt]')?.addEventListener('change', event => handlers.update({prompt:event.target.value}));
    els.plan.querySelectorAll('[data-field]').forEach(control => control.addEventListener('change', () => handlers.update({[control.dataset.field]:control.type === 'number' ? Number(control.value) : control.value})));
    els.plan.querySelector('[data-approve]')?.addEventListener('click', handlers.approve);
    els.plan.querySelector('[data-cancel]')?.addEventListener('click', handlers.cancel);
}
