/* ==========================================
   canvas-agent-executor.js
   Agent 操作执行器 — 调用 smart-canvas.js 函数
   ========================================== */
(function() {
    'use strict';

    /**
     * 执行 LLM 返回的计划
     * @param {Object} plan - LLM 响应解析结果
     * @returns {Object} 执行结果
     */
    async function executePlan(plan) {
        if (!plan || !plan.action) {
            return { success: false, error: '无效的计划' };
        }

        const result = {
            success: false,
            action: plan.action,
            nodesCreated: [],
            paramsChanged: {}
        };

        try {
            // 操作前存档（用于撤销）
            if (typeof pushUndo === 'function') {
                pushUndo();
            }

            // 获取视口中心位置（新节点的默认位置）
            const vpCenter = typeof viewportCenter === 'function'
                ? viewportCenter()
                : { x: 0, y: 0 };

            switch (plan.action) {
                case 'create_prompt':
                    result.nodesCreated = createPromptCards(plan, vpCenter);
                    break;

                case 'optimize_prompt':
                    result.nodesCreated = optimizeExistingPrompt(plan);
                    break;

                case 'suggest_params':
                    result.paramsChanged = applySuggestParams(plan);
                    break;

                case 'create_workflow':
                    result.nodesCreated = createWorkflowCards(plan, vpCenter);
                    break;

                case 'chat':
                    // 纯对话，不需要操作画布
                    break;

                default:
                    console.warn('[AgentExecutor] unknown action:', plan.action);
            }

            // 渲染更新
            if (typeof render === 'function') render();
            if (typeof scheduleSave === 'function') scheduleSave();

            result.success = true;
        } catch (e) {
            console.error('[AgentExecutor] executePlan failed:', e);
            result.success = false;
            result.error = e.message || '执行失败';
        }

        return result;
    }

    /**
     * 创建提示词卡片
     */
    function createPromptCards(plan, center) {
        const created = [];
        const cards = plan.cards || [];
        const promptText = plan.prompt_text || '';

        if (cards.length === 0 && promptText) {
            // 没有明确卡片，创建一个默认 prompt 节点
            const node = createSinglePromptNode(center.x - 158, center.y - 80, promptText, plan.label || 'AI 提示词');
            if (node) created.push(node);
        } else {
            // 按卡片列表创建
            cards.forEach(function(card, index) {
                const x = center.x - 158 + (index % 3) * 340;
                const y = center.y - 80 + Math.floor(index / 3) * 220;
                const cardType = card.type || '';
                if (cardType === 'prompt' || cardType === 'smart-prompt') {
                    const node = createSinglePromptNode(x, y, card.text || card.content || promptText, card.label || card.title || 'AI 卡片');
                    if (node) created.push(node);
                } else if ((cardType === 'image' || cardType === 'smart-image') && typeof createImageNodeAt === 'function') {
                    createImageNodeAt({ x: x + 160, y: y + 40 });
                    created.push({ type: 'smart-image', position: { x, y } });
                } else if ((cardType === 'loop' || cardType === 'smart-loop') && typeof createLoopNode === 'function') {
                    const node = createLoopNode(x, y);
                    if (node) created.push(node);
                }
            });
        }

        return created;
    }

    /**
     * 创建单个提示词节点
     */
    function createSinglePromptNode(x, y, text, label) {
        if (typeof createPromptNode !== 'function') {
            console.warn('[AgentExecutor] createPromptNode not found');
            return null;
        }
        // 在附近偏移避免重叠
        const offsetX = (Math.random() - 0.5) * 40;
        const offsetY = (Math.random() - 0.5) * 40;
        const node = createPromptNode(x + offsetX, y + offsetY, { label: label || 'AI 提示词', text: text || '' });
        if (node && node.id && text) {
            // 尝试设置提示词文本
            setNodePromptText(node.id, text);
            if (label && typeof updateNodeLabel === 'function') {
                updateNodeLabel(node.id, label);
            }
        }
        return node;
    }

    /**
     * 设置节点提示词文本
     */
    function setNodePromptText(nodeId, text) {
        if (!nodeId || !text) return;
        try {
            if (typeof nodes !== 'undefined') {
                const node = nodes.find(function(n) { return n.id === nodeId; });
                if (node) {
                    node.text = text;
                    // 兼容早期 Agent 原型写入过的结构，但渲染与保存以 node.text 为准。
                    node.text_items = [{ id: 'ai_' + Date.now(), text: text, role: 'user' }];
                }
            }
        } catch (e) {
            console.warn('[AgentExecutor] setNodePromptText failed:', e);
        }
    }

    /**
     * 优化已选节点提示词
     */
    function optimizeExistingPrompt(plan) {
        const created = [];
        try {
            if (typeof selectedIds === 'undefined' || typeof nodes === 'undefined') return created;

            const targetIds = (selectedIds && selectedIds.length) ? selectedIds.slice() : (typeof selectedId !== 'undefined' && selectedId ? [selectedId] : []);
            if (targetIds.length === 0) {
                // 没有选中节点，创建一个新的优化提示词节点
                const center = typeof viewportCenter === 'function' ? viewportCenter() : { x: 0, y: 0 };
                const node = createSinglePromptNode(center.x - 158, center.y - 80, plan.prompt_text || '', '优化提示词');
                if (node) created.push(node);
                return created;
            }

            targetIds.forEach(function(id) {
                const node = nodes.find(function(n) { return n.id === id; });
                if (node && node.type === 'smart-prompt') {
                    // 替换提示词文本
                    if (plan.prompt_text) {
                        setNodePromptText(node.id, plan.prompt_text);
                    }
                    created.push(node);
                }
            });
        } catch (e) {
            console.warn('[AgentExecutor] optimizeExistingPrompt failed:', e);
        }
        return created;
    }

    /**
     * 应用建议参数
     */
    function applySuggestParams(plan) {
        const changed = {};
        try {
            if (typeof settings === 'undefined') return changed;

            if (plan.engine_suggestion && ['api', 'volcengine', 'modelscope', 'comfy', 'runninghub'].includes(plan.engine_suggestion)) {
                settings.engine = plan.engine_suggestion;
                changed.engine = plan.engine_suggestion;
                // 同步 UI
                const engineSelect = document.getElementById('engineSelect');
                if (engineSelect) engineSelect.value = plan.engine_suggestion;
            }
            if (plan.model_suggestion) {
                const providerId = resolveProviderForModel(plan.model_suggestion);
                if (providerId) {
                    settings.provider_id = providerId;
                    changed.provider_id = providerId;
                    settings.model = plan.model_suggestion;
                    changed.model = plan.model_suggestion;
                } else if (settings.provider_id) {
                    settings.model = plan.model_suggestion;
                    changed.model = plan.model_suggestion;
                }
            }
            if (plan.params) {
                if (plan.params.ratio) { settings.ratio = plan.params.ratio; changed.ratio = plan.params.ratio; }
                if (plan.params.resolution) { settings.resolution = plan.params.resolution; changed.resolution = plan.params.resolution; }
            }

            // 更新 UI
            if (typeof applyRecentSmartSettingsForCurrentMode === 'function') {
                applyRecentSmartSettingsForCurrentMode();
            }
            if (typeof renderDynamicParams === 'function') {
                renderDynamicParams();
            }
            if (typeof persistActiveSmartSettings === 'function') {
                persistActiveSmartSettings();
            }
            if (changed.model && settings.model !== changed.model) {
                delete changed.model;
            }
        } catch (e) {
            console.warn('[AgentExecutor] applySuggestParams failed:', e);
        }
        return changed;
    }

    function resolveProviderForModel(model) {
        if (!model) return '';
        try {
            if (typeof apiProviders !== 'undefined' && Array.isArray(apiProviders)) {
                const provider = apiProviders.find(function(item) {
                    const imageModels = Array.isArray(item && item.image_models) ? item.image_models : [];
                    return item && item.enabled !== false && imageModels.includes(model);
                });
                if (provider && provider.id) return provider.id;
            }
        } catch (e) {
            console.warn('[AgentExecutor] resolveProviderForModel failed:', e);
        }
        return '';
    }

    /**
     * 创建工作流卡片
     */
    function createWorkflowCards(plan, center) {
        const created = [];
        try {
            const cards = plan.cards || [];
            cards.forEach(function(card, index) {
                const x = center.x - 200 + index * 360;
                const y = center.y - 60;
                const cardType = card.type || '';
                if (cardType === 'prompt' || cardType === 'smart-prompt') {
                    const node = createSinglePromptNode(x, y, card.text || card.content || '', card.label || card.title || '步骤 ' + (index + 1));
                    if (node) created.push(node);
                } else if ((cardType === 'loop' || cardType === 'smart-loop') && typeof createLoopNode === 'function') {
                    const node = createLoopNode(x, y);
                    if (node) created.push(node);
                }
            });
        } catch (e) {
            console.warn('[AgentExecutor] createWorkflowCards failed:', e);
        }
        return created;
    }

    /**
     * 规则引擎：LLM 不可用时的关键词匹配
     */
    function heuristicParse(message) {
        const msg = (message || '').toLowerCase();
        const plan = { action: 'chat', reply: '', cards: [] };
        const now = Date.now();

        // 关键词检测
        const hasGenerate = /生成|创建|做[一一个张幅]/g.test(msg);
        const hasOptimize = /优化|改进|改善|修改提示/g.test(msg);
        const hasBatch = /批量|多个|一系列|几[张个]/g.test(msg);
        const hasLoop = /循环|重复|迭代/g.test(msg);

        // 引擎检测
        if (/火山|volcengine/.test(msg)) plan.engine_suggestion = 'volcengine';
        else if (/modelscope|ms生成/.test(msg)) plan.engine_suggestion = 'modelscope';
        else if (/comfyui|comfy/.test(msg)) plan.engine_suggestion = 'comfy';
        else if (/runninghub/.test(msg)) plan.engine_suggestion = 'runninghub';
        else if (/api生成|api/.test(msg)) plan.engine_suggestion = 'api';

        // 操作决定
        if (hasBatch || hasLoop) {
            plan.action = 'create_workflow';
            plan.cards = [
                { type: 'smart-prompt', text: extractPromptText(msg), label: '批量提示词' },
                { type: 'smart-loop', label: '循环控制' }
            ];
            plan.reply = '已创建批量生成工作流，包含提示词卡片和循环控制节点。';
        } else if (hasOptimize) {
            plan.action = 'optimize_prompt';
            plan.reply = '请选中要优化的提示词节点，我将为你优化内容。';
        } else if (hasGenerate) {
            plan.action = 'create_prompt';
            plan.cards = [{ type: 'smart-prompt', text: extractPromptText(msg), label: '提示词卡片' }];
            plan.reply = '已创建提示词卡片。';
        } else {
            plan.action = 'chat';
            plan.reply = '你好！我可以帮你：\n• 生成提示词 — "写一个赛博朋克提示词"\n• 优化提示词 — "优化选中的提示词"\n• 推荐参数 — "推荐最佳引擎"\n• 批量生成 — "创建批量工作流"';
        }

        return plan;
    }

    /**
     * 从消息中提取主题关键词作为提示词
     */
    function extractPromptText(msg) {
        // 简单的启发式提取
        const clean = msg
            .replace(/帮我|请|生成|创建|写[一一个]/g, '')
            .replace(/提示词|用[火山上山]|使用|引擎/g, '')
            .trim();
        if (!clean) return '请在此输入提示词内容...';
        return clean;
    }

    // 挂载到全局
    window.CanvasAgent = {
        executePlan: executePlan,
        heuristicParse: heuristicParse,
        createPromptCards: createPromptCards,
        createSinglePromptNode: createSinglePromptNode,
        setNodePromptText: setNodePromptText,
        optimizeExistingPrompt: optimizeExistingPrompt,
        applySuggestParams: applySuggestParams,
        createWorkflowCards: createWorkflowCards
    };
})();
