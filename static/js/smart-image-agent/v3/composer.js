export function bindComposer(els, onCreate){
    els.create.addEventListener('click', onCreate);
    els.intent.addEventListener('keydown', event => { if((event.metaKey || event.ctrlKey) && event.key === 'Enter') onCreate(); });
}
