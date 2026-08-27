const labels = {"context.ready":"理解需求","plan.proposed":"生成方案","plan.updated":"更新方案","approval.requested":"等待确认","approval.decided":"已确认","tool.started":"生成中","tool.progressed":"生成中","tool.completed":"保存结果","tool.failed":"生成失败","tool.cancelled":"已取消","artifact.created":"结果已保存","execution.completed":"已完成"};
export function renderActivity(els, execution, events){
    const latest = events.at(-1)?.type || '';
    els.status.textContent = labels[latest] || (execution ? execution.status : '等待创作目标');
    els.eventDetails.hidden = !events.length;
    els.events.innerHTML = events.map(event => `<li><strong>${labels[event.type] || event.type}</strong><small>${event.occurred_at || ''}</small></li>`).join('');
}
