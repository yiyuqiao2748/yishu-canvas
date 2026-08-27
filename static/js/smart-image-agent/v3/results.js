function escapeHtml(value){ return String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char])); }
export function renderResults(els, runs, bridge, handlers={}){
    const completed = (runs || []).filter(run => run.status === 'succeeded' && run.result?.url);
    els.results.innerHTML = completed.length ? completed.map(run => `<article class="sia-result"><img src="${escapeHtml(run.result.preview_url || run.result.url)}" alt="生成结果"><div class="sia-result-actions"><button type="button" data-focus="${escapeHtml(run.result.target_node_id || '')}">聚焦画布</button><button type="button" data-result-action="continue-edit" data-run-id="${escapeHtml(run.id)}">继续编辑</button><button type="button" data-result-action="create-variants" data-run-id="${escapeHtml(run.id)}">生成变体</button><button type="button" data-result-action="expand-image" data-run-id="${escapeHtml(run.id)}">扩图</button><button type="button" data-result-action="save-result" data-run-id="${escapeHtml(run.id)}">保存素材</button></div></article>`).join('') : '<div class="sia-empty">结果将在画布中出现</div>';
    els.results.querySelectorAll('[data-focus]').forEach(button => button.addEventListener('click', () => bridge.focusResult(button.dataset.focus)));
    els.results.querySelectorAll('[data-result-action]').forEach(button => button.addEventListener('click', () => {
        const run = completed.find(item => item.id === button.dataset.runId);
        if(run) handlers[button.dataset.resultAction]?.(run);
    }));
}
