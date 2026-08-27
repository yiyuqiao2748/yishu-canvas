export function createShell(){
    document.getElementById('agentPanel')?.remove();
    document.getElementById('smartImageAgent')?.remove();
    document.body.classList.remove?.('smart-image-agent-v2-open', 'smart-image-agent-v2-collapsed');
    document.body.classList.add('smart-image-agent-v3-workspace');
    const root = document.createElement('aside');
    root.id = 'smartImageAgent';
    root.className = 'smart-image-agent smart-image-agent-workspace';
    root.innerHTML = `
        <header class="sia-workspace-header"><div class="sia-brand"><div><strong>图片 Agent</strong><span>先确认方案，再执行生成</span></div></div><div class="sia-workspace-actions"><button type="button" data-toggle-references aria-expanded="false">引用 <span data-ref-count>0/10</span></button><div class="sia-canvas-controls" aria-label="画布视图"><button type="button" data-canvas="fitAll" title="适应画布">适应</button><button type="button" data-canvas="zoomIn" title="放大画布">放大</button><button type="button" data-canvas="zoomOut" title="缩小画布">缩小</button><button type="button" data-canvas="resetZoom" title="重置视图">重置</button><button type="button" data-canvas="arrangeSelection" title="整理选中内容">整理</button></div></div></header>
        <main class="sia-workspace-stage" data-workspace-stage>
            <section class="sia-reference-section" data-reference-panel hidden><div class="sia-section-head"><strong>创作引用</strong></div><div class="sia-refs" data-refs></div><div class="sia-reference-actions"><button type="button" data-add-selection>添加选中图片</button><label class="sia-secondary">上传引用<input data-upload type="file" accept="image/*" multiple hidden></label></div></section>
            <section data-plan hidden aria-label="当前方案"></section>
            <section class="sia-activity-section"><div class="sia-section-head"><strong>创作状态</strong><button type="button" data-details>执行详情</button></div><div data-status class="sia-empty">等待创作目标</div><details data-event-details hidden><summary>事件流</summary><ol data-events></ol></details></section>
            <section class="sia-results-section"><div class="sia-section-head"><strong>结果</strong></div><div class="sia-results" data-results><div class="sia-empty">结果将在画布中出现</div></div></section>
        </main>
        <footer class="sia-composer sia-workspace-composer"><label class="sia-composer-label" for="smartImageAgentIntent">新创作需求</label><textarea id="smartImageAgentIntent" data-intent rows="3" placeholder="描述你想完成的画面；可选中或上传参考图"></textarea><div class="sia-composer-controls"><select data-ratio aria-label="画面比例"><option value="auto">自动比例</option><option value="1:1">1:1</option><option value="4:5">4:5</option><option value="16:9">16:9</option><option value="9:16">9:16</option></select><select data-model aria-label="图片模型"><option value="gpt-image-2">GPT Image 2 · 6 点</option><option value="nano-banana-2" selected>Nano Banana 2 · 12 点</option><option value="nano-banana-pro">Nano Banana Pro · 18 点</option><option value="gpt-image-2-vip">GPT Image 2 VIP · 20 点</option></select><input data-count type="number" min="1" max="8" value="1" aria-label="生成数量"></div><button class="sia-primary" type="button" data-create>生成方案</button><p data-notice hidden></p></footer>`;
    document.body.appendChild(root);
    return {
        root,
        refs:root.querySelector('[data-refs]'), refCount:root.querySelector('[data-ref-count]'),
        toggleReferences:root.querySelector('[data-toggle-references]'), referencePanel:root.querySelector('[data-reference-panel]'), workspaceStage:root.querySelector('[data-workspace-stage]'), addSelection:root.querySelector('[data-add-selection]'), upload:root.querySelector('[data-upload]'),
        plan:root.querySelector('[data-plan]'), status:root.querySelector('[data-status]'), details:root.querySelector('[data-details]'), eventDetails:root.querySelector('[data-event-details]'), events:root.querySelector('[data-events]'), results:root.querySelector('[data-results]'),
        intent:root.querySelector('[data-intent]'), ratio:root.querySelector('[data-ratio]'), model:root.querySelector('[data-model]'), count:root.querySelector('[data-count]'), create:root.querySelector('[data-create]'), notice:root.querySelector('[data-notice]')
    };
}
