function escapeHtml(value){ return String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char])); }

export function createContextController(bridge, els, notify){
    let selected = [];
    let refs = [];
    function normalize(items){
        return (Array.isArray(items) ? items : []).filter(item => item?.url || item?.original_url).map(item => ({
            node_id:item.node_id || item.id || '', asset_id:item.asset_id || '', url:item.url || item.original_url || '', preview_url:item.preview_url || item.thumbnail || item.url || '', name:item.name || item.prompt || ''
        }));
    }
    function render(){
        els.refs.innerHTML = refs.length ? refs.map((item, index) => `<div class="sia-ref"><img src="${escapeHtml(item.preview_url || item.url)}" alt="参考图"><span>${escapeHtml(item.name || `参考图 ${index + 1}`)}</span><button type="button" data-remove-ref="${index}">移除</button></div>`).join('') : '<div class="sia-empty-ref">选中画布图片或上传参考图</div>';
        els.refCount.textContent = `${refs.length}/10`;
        els.addSelection.disabled = !selected.length;
        els.refs.querySelectorAll('[data-remove-ref]').forEach(button => button.addEventListener('click', () => { refs.splice(Number(button.dataset.removeRef), 1); render(); }));
    }
    function add(items){
        const unique = [...refs];
        normalize(items).forEach(item => { if(!unique.some(old => `${old.node_id}|${old.asset_id}|${old.url}` === `${item.node_id}|${item.asset_id}|${item.url}`)) unique.push(item); });
        if(unique.length > 10){ notify('单次最多引用 10 张图片', 'error'); return; }
        refs = unique; render();
    }
    els.addSelection.addEventListener('click', () => add(selected));
    els.upload.addEventListener('change', async () => {
        try { add(await bridge.uploadReferences([...els.upload.files].filter(file => file.type.startsWith('image/')))); }
        catch(error) { notify(error.message, 'error'); }
        els.upload.value = '';
    });
    const unsubscribe = bridge.subscribeSelection(items => { selected = normalize(items); render(); });
    selected = normalize(bridge.selection()); render();
    return { add, build(){ return {...bridge.context(), selected_images:refs}; }, dispose:unsubscribe };
}
