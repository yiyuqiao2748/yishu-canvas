/* ==========================================
   canvas-agent-panel.js
   Agent 面板 UI — 对话、输入、评分、能力面板
   ========================================== */
(function() {
    'use strict';

    // --- 状态 ---
    var panelOpen = false;
    var messages = [];
    var currentSessionId = null;
    var isThinking = false;

    // --- DOM 引用 ---
    var panel, chatMessages, chatInput, sendBtn, toggleBtn;
    var levelBadge, levelTitle, levelXp, levelBarFill;
    var statsTotalTasks, statsSuccessRate, statsAvgRating;
    var prefEngine, prefModel, prefRatio;
    var successList;
    var ratingRow, ratingStars;

    // --- 初始化 ---
    function init() {
        cacheDom();
        bindEvents();
        loadInitialMemory();
        currentSessionId = 'ag_' + Date.now();

        // 如果有初始消息，显示欢迎
        if (messages.length === 0) {
            addMessage('assistant', '\u{1F44B} 你好！我是智能画布 AI 助手。\n\n我可以帮你：\n\u2022 **生成提示词** — "写一个赛博朋克城市夜景的提示词"\n\u2022 **优化提示词** — "帮我优化选中的提示词"\n\u2022 **推荐参数** — "推荐最适合的引擎和模型"\n\u2022 **批量生成** — "创建一组不同风格的提示词"', false);
        }
    }

    function cacheDom() {
        panel = document.getElementById('agentPanel');
        chatMessages = document.getElementById('agentMessages');
        chatInput = document.getElementById('agentChatInput');
        sendBtn = document.getElementById('agentSendBtn');
        toggleBtn = document.getElementById('agentToggle');
        levelBadge = document.getElementById('agentLevelBadge');
        levelTitle = document.getElementById('agentLevelTitle');
        levelXp = document.getElementById('agentLevelXp');
        levelBarFill = document.getElementById('agentLevelBarFill');
        statsTotalTasks = document.getElementById('agentStatTotalTasks');
        statsSuccessRate = document.getElementById('agentStatSuccessRate');
        statsAvgRating = document.getElementById('agentStatAvgRating');
        prefEngine = document.getElementById('agentPrefEngine');
        prefModel = document.getElementById('agentPrefModel');
        prefRatio = document.getElementById('agentPrefRatio');
        successList = document.getElementById('agentSuccessList');
        ratingRow = document.getElementById('agentRatingRow');
    }

    function escapeAgentHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function teamCloudAuthHeaders() {
        var headers = { 'Content-Type': 'application/json' };
        try {
            var token = localStorage.getItem('teamCloudAccessToken') || '';
            if (token) headers.Authorization = 'Bearer ' + token;
        } catch(_) {}
        return headers;
    }

    function bindEvents() {
        // 切换面板
        if (toggleBtn) {
            toggleBtn.addEventListener('click', function(e) {
                e.preventDefault();
                togglePanel();
            });
        }

        // Ctrl+Space 快捷键（由 smart-canvas.js 转发）

        // 发送按钮
        if (sendBtn) {
            sendBtn.addEventListener('click', function() { sendMessage(); });
        }

        // Enter 发送
        if (chatInput) {
            chatInput.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            });
            // 自动调整高度
            chatInput.addEventListener('input', function() {
                chatInput.style.height = 'auto';
                chatInput.style.height = Math.min(80, chatInput.scrollHeight) + 'px';
            });
        }

        // 快捷操作
        var chips = document.querySelectorAll('.agent-quick-chip');
        chips.forEach(function(chip) {
            chip.addEventListener('click', function() {
                var prompt = this.dataset.prompt;
                if (prompt && chatInput) {
                    chatInput.value = prompt;
                    chatInput.focus();
                    chatInput.dispatchEvent(new Event('input'));
                }
            });
        });

        // 评分星
        document.querySelectorAll('.agent-star').forEach(function(star) {
            star.addEventListener('click', function() {
                var rating = parseInt(this.dataset.rating);
                submitRating(rating);
            });
        });

        // 关闭按钮
        var closeBtn = document.getElementById('agentCloseBtn');
        if (closeBtn) {
            closeBtn.addEventListener('click', function() { hidePanel(); });
        }

        // 清除记忆按钮
        var clearBtn = document.getElementById('agentClearMemoryBtn');
        if (clearBtn) {
            clearBtn.addEventListener('click', function() {
                if (confirm('确定要清除 Agent 的所有记忆吗？这将重置等级和学习数据。')) {
                    if (window.AgentMemory) window.AgentMemory.reset();
                    loadInitialMemory();
                    addMessage('assistant', '\u{1F504} 记忆已重置，让我们重新开始吧！');
                }
            });
        }

        // 调整面板高度
        var resizeHandle = document.getElementById('agentResizeHandle');
        if (resizeHandle) {
            resizeHandle.addEventListener('mousedown', function(e) {
                e.preventDefault();
                var startY = e.clientY;
                var startHeight = panel.offsetHeight;
                function onMove(me) {
                    var newHeight = startHeight - (me.clientY - startY);
                    newHeight = Math.max(200, Math.min(600, newHeight));
                    panel.style.height = newHeight + 'px';
                }
                function onUp() {
                    document.removeEventListener('mousemove', onMove);
                    document.removeEventListener('mouseup', onUp);
                    // 保存高度偏好
                    try { localStorage.setItem('agent_panel_height', panel.style.height); } catch(_) {}
                }
                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onUp);
            });
        }
    }

    function loadInitialMemory() {
        updateSkillsPanel();
        hydrateBackendMemory();
    }

    function hasAgentBackendSession() {
        try {
            return !!localStorage.getItem('teamCloudAccessToken');
        } catch(_) {
            return false;
        }
    }

    async function hydrateBackendMemory() {
        if (!window.AgentMemory || !hasAgentBackendSession()) return;
        try {
            var memoryResponse = await fetch('/api/canvas-agent/memory', {
                method: 'GET',
                credentials: 'same-origin',
                headers: teamCloudAuthHeaders()
            });
            if (memoryResponse.ok) {
                var remoteMemory = await memoryResponse.json();
                mergeRemoteMemory(remoteMemory);
            }
            var levelResponse = await fetch('/api/canvas-agent/level', {
                method: 'GET',
                credentials: 'same-origin',
                headers: teamCloudAuthHeaders()
            });
            if (levelResponse.ok) {
                var levelData = await levelResponse.json();
                mergeRemoteLevel(levelData);
            }
            updateSkillsPanel();
        } catch (e) {
            console.warn('[AgentPanel] backend memory hydration skipped:', e.message);
        }
    }

    function mergeRemoteMemory(remoteMemory) {
        if (!remoteMemory || !window.AgentMemory) return;
        var localMemory = window.AgentMemory.load();
        localMemory.level = Math.max(Number(localMemory.level) || 1, Number(remoteMemory.level) || 1);
        localMemory.experience = Math.max(Number(localMemory.experience) || 0, Number(remoteMemory.experience) || 0);
        localMemory.preferences = Object.assign({}, localMemory.preferences || {}, remoteMemory.preferences || {});
        localMemory.patterns = Object.assign({}, localMemory.patterns || {}, remoteMemory.patterns || {});
        localMemory.skill_values = Object.assign({}, localMemory.skill_values || {}, remoteMemory.skill_values || {});
        window.AgentMemory.save(localMemory);
    }

    function mergeRemoteLevel(levelData) {
        if (!levelData || !window.AgentMemory) return;
        var localMemory = window.AgentMemory.load();
        localMemory.level = Math.max(Number(localMemory.level) || 1, Number(levelData.level) || 1);
        localMemory.experience = Math.max(Number(localMemory.experience) || 0, Number(levelData.experience) || 0);
        if (levelData.preferences) localMemory.preferences = Object.assign({}, localMemory.preferences || {}, levelData.preferences);
        if (levelData.skill_radar) localMemory.skill_values = Object.assign({}, localMemory.skill_values || {}, levelData.skill_radar);
        var stats = levelData.stats || {};
        localMemory.total_tasks = Math.max(Number(localMemory.total_tasks) || 0, Number(stats.total_tasks) || 0);
        localMemory.avg_rating = Math.max(Number(localMemory.avg_rating) || 0, Number(stats.avg_rating) || 0);
        if (Array.isArray(levelData.recent_successes) && levelData.recent_successes.length) {
            var remoteSuccesses = levelData.recent_successes.map(function(item) {
                return {
                    timestamp: item.timestamp || Date.now(),
                    action: item.action || 'remote_feedback',
                    rating: item.rating || 0,
                    accepted: true
                };
            });
            localMemory.feedback_history = (localMemory.feedback_history || []).concat(remoteSuccesses).slice(-50);
        }
        window.AgentMemory.save(localMemory);
    }

    // --- 面板控制 ---
    function togglePanel() {
        if (panelOpen) {
            hidePanel();
        } else {
            showPanel();
        }
    }

    function showPanel() {
        if (!panel) return;
        panel.classList.add('open');
        panel.classList.remove('hidden');
        panelOpen = true;
        if (toggleBtn) toggleBtn.classList.add('active');

        // 恢复保存的高度
        try {
            var savedHeight = localStorage.getItem('agent_panel_height');
            if (savedHeight) panel.style.height = savedHeight;
        } catch(_) {}

        // 聚焦输入框
        setTimeout(function() {
            if (chatInput) chatInput.focus();
        }, 300);

        updateSkillsPanel();
    }

    function hidePanel() {
        if (!panel) return;
        panel.classList.remove('open');
        panelOpen = false;
        if (toggleBtn) toggleBtn.classList.remove('active');
    }

    window.toggleAgentPanel = togglePanel;
    window.showAgentPanel = showPanel;
    window.hideAgentPanel = hidePanel;

    // --- 消息管理 ---
    function addMessage(role, content, showRating) {
        messages.push({ role: role, content: content, timestamp: Date.now() });
        renderMessage(role, content, showRating);
        scrollToBottom();
    }

    function renderMessage(role, content, showRating) {
        if (!chatMessages) return;

        var msgDiv = document.createElement('div');
        msgDiv.className = 'agent-msg ' + role;

        // 头像
        var avatar = document.createElement('div');
        avatar.className = 'agent-msg-avatar';
        if (role === 'assistant') {
            avatar.innerHTML = '\u{1F916}'; // robot
        } else {
            avatar.innerHTML = '\u{1F464}'; // person
        }
        msgDiv.appendChild(avatar);

        // 气泡
        var bubble = document.createElement('div');
        bubble.className = 'agent-msg-bubble';

        // 简单 Markdown 渲染
        var html = escapeAgentHtml(content)
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/`([^`]+)`/g, '<code style="background:var(--agent-chat-bg);padding:1px 4px;border-radius:3px;font-size:11px">$1</code>')
            .replace(/\n/g, '<br>')
            .replace(/• (.*?)(<br>|$)/g, '<span style="display:block;padding-left:8px">\u2022 $1</span>');

        bubble.innerHTML = html;

        // 添加操作标签
        if (role === 'assistant' && content.indexOf('已创建') >= 0) {
            var tag = document.createElement('span');
            tag.className = 'agent-action-tag';
            tag.textContent = '\u2705 已执行';
            bubble.appendChild(document.createElement('br'));
            bubble.appendChild(tag);
        }

        // 评分栏
        if (showRating !== false && role === 'assistant') {
            var ratingDiv = document.createElement('div');
            ratingDiv.className = 'agent-rating-bar';
            ratingDiv.style.cssText = 'margin-top:6px';
            for (var i = 1; i <= 5; i++) {
                (function(starValue) {
                    var star = document.createElement('button');
                    star.className = 'agent-star';
                    star.textContent = '\u2605';
                    star.setAttribute('title', starValue + ' 星');
                    star.addEventListener('click', function() {
                        submitRating(starValue);
                        ratingDiv.querySelectorAll('.agent-star').forEach(function(s, idx) {
                            s.classList.toggle('active', idx < starValue);
                        });
                    });
                    ratingDiv.appendChild(star);
                })(i);
            }
            var label = document.createElement('span');
            label.className = 'agent-rating-label';
            label.textContent = '评分';
            ratingDiv.appendChild(label);

            // 采纳/拒绝按钮
            var fbBtns = document.createElement('div');
            fbBtns.className = 'agent-feedback-btns';
            var acceptBtn = document.createElement('button');
            acceptBtn.className = 'agent-fb-btn';
            acceptBtn.textContent = '\u{1F44D} 采纳';
            acceptBtn.addEventListener('click', function() {
                acceptBtn.classList.add('accepted');
                acceptBtn.disabled = true;
                postAgentFeedback({
                    rating: 5,
                    accepted: true,
                    action_taken: 'create_prompt',
                    session_id: currentSessionId,
                    result: {}
                }).then(function(sync) {
                    acceptBtn.textContent = syncLabel(sync);
                    acceptBtn.title = syncTitle(sync);
                });
                if (window.AgentLearning) {
                    window.AgentLearning.processFeedback({
                        rating: 5,
                        accepted: true,
                        action: 'create_prompt',
                        sessionId: currentSessionId
                    });
                    updateSkillsPanel();
                }
            });
            var rejectBtn = document.createElement('button');
            rejectBtn.className = 'agent-fb-btn';
            rejectBtn.textContent = '\u{1F44E} 拒绝';
            rejectBtn.addEventListener('click', function() {
                rejectBtn.disabled = true;
                postAgentFeedback({
                    rating: 1,
                    accepted: false,
                    action_taken: 'create_prompt',
                    session_id: currentSessionId,
                    result: {}
                }).then(function(sync) {
                    rejectBtn.textContent = syncLabel(sync);
                    rejectBtn.title = syncTitle(sync);
                });
                if (window.AgentLearning) {
                    window.AgentLearning.processFeedback({
                        rating: 1,
                        accepted: false,
                        action: 'create_prompt',
                        sessionId: currentSessionId
                    });
                    updateSkillsPanel();
                }
            });
            fbBtns.appendChild(acceptBtn);
            fbBtns.appendChild(rejectBtn);
            ratingDiv.appendChild(fbBtns);
            bubble.appendChild(ratingDiv);
        }

        msgDiv.appendChild(bubble);
        chatMessages.appendChild(msgDiv);
    }

    function scrollToBottom() {
        if (!chatMessages) return;
        setTimeout(function() {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }, 50);
    }

    function showThinking() {
        if (isThinking) return;
        isThinking = true;
        if (chatMessages) {
            var div = document.createElement('div');
            div.className = 'agent-thinking';
            div.id = 'agentThinkingIndicator';
            div.innerHTML = '思考中 <span class="agent-thinking-dots"><span></span><span></span><span></span></span>';
            chatMessages.appendChild(div);
            scrollToBottom();
        }
    }

    function hideThinking() {
        isThinking = false;
        var indicator = document.getElementById('agentThinkingIndicator');
        if (indicator) indicator.remove();
    }

    // --- 发送消息 ---
    async function sendMessage() {
        if (!chatInput) return;
        var text = chatInput.value.trim();
        if (!text || isThinking) return;

        chatInput.value = '';
        chatInput.style.height = 'auto';
        addMessage('user', text, false);

        showThinking();

        try {
            var plan = await callAgentAPI(text);
            hideThinking();

            if (plan && plan.reply) {
                addMessage('assistant', plan.reply, true);
            } else {
                addMessage('assistant', '\u26A0\uFE0F 未能解析你的意图，请换个方式描述。', true);
                return;
            }

            // 执行计划
            if (plan.action !== 'chat' && window.CanvasAgent) {
                var result = await window.CanvasAgent.executePlan(plan);
                if (result.success) {
                    // 更新学习数据
                    if (window.AgentLearning) {
                        window.AgentLearning.processFeedback({
                            rating: 0, // 等待用户手动评分
                            accepted: true,
                            action: plan.action,
                            sessionId: currentSessionId,
                            paramsChanged: result.paramsChanged || {}
                        });
                        updateSkillsPanel();
                    }
                }
            }
        } catch (e) {
            hideThinking();
            console.error('[AgentPanel] sendMessage failed:', e);
            if (e && e.code === 'AUTH_REQUIRED') {
                addMessage('assistant', '请先在主页顶部登录账户，登录成功后我才能读取团队默认模型并帮你操作画布。', false);
                return;
            }
            // 降级到规则引擎
            try {
                var heuristicPlan = window.CanvasAgent
                    ? window.CanvasAgent.heuristicParse(text)
                    : { action: 'chat', reply: '\u26A0\uFE0F AI 服务暂时不可用。你可以：\n\u2022 手动创建提示词卡片\n\u2022 在 Composer 中直接输入提示词\n\u2022 稍后再试' };
                addMessage('assistant', heuristicPlan.reply, true);
                if (heuristicPlan.action !== 'chat' && window.CanvasAgent) {
                    await window.CanvasAgent.executePlan(heuristicPlan);
                }
            } catch (e2) {
                addMessage('assistant', '\u26A0\uFE0F 服务暂时不可用，请稍后再试。', false);
            }
        } finally {
            currentSessionId = 'ag_' + Date.now();
        }
    }

    /**
     * 调用后端 Agent API
     */
    async function callAgentAPI(message) {
        try {
            // 收集画布上下文
            var context = {};
            if (typeof settings !== 'undefined') {
                context.engine = settings.engine;
                context.model = settings.model;
                context.ratio = settings.ratio;
            }
            if (typeof nodes !== 'undefined') {
                context.nodeCount = nodes.length;
            }
            if (typeof selectedIds !== 'undefined' && selectedIds.length > 0) {
                context.selectedNodeCount = selectedIds.length;
            }
            if (typeof selectedNodeIds === 'function' && typeof nodes !== 'undefined') {
                var selectedNodeList = selectedNodeIds()
                    .map(function(id) {
                        return nodes.find(function(node) { return node.id === id; });
                    })
                    .filter(Boolean)
                    .slice(0, 6)
                    .map(function(node) {
                        return {
                            id: node.id,
                            type: node.type,
                            title: node.title || '',
                            text: node.text || node.prompt || ''
                        };
                    });
                context.selectedNodeCount = selectedNodeList.length;
                context.selectedNodes = selectedNodeList;
            }
            if (typeof teamCloudRequestMeta === 'function') {
                Object.assign(context, teamCloudRequestMeta());
            } else {
                try {
                    context.team_id = localStorage.getItem('teamCloudCurrentTeamId') || '';
                    context.project_id = localStorage.getItem('teamCloudCurrentProjectId') || '';
                } catch(_) {}
            }
            try {
                var urlParams = new URLSearchParams(location.search);
                context.canvas_id = context.canvas_id || urlParams.get('id') || '';
                context.project_id = context.project_id || urlParams.get('project') || '';
            } catch(_) {}

            // 收集用户偏好
            var mem = window.AgentMemory ? window.AgentMemory.load() : {};
            context.agent_preferences = mem.preferences || {};

            var response = await fetch('/api/canvas-agent/suggest', {
                method: 'POST',
                credentials: 'same-origin',
                headers: teamCloudAuthHeaders(),
                body: JSON.stringify({
                    message: message,
                    context: context
                })
            });

            if (!response.ok) {
                var err = new Error('API error: ' + response.status);
                if (response.status === 401 || response.status === 403) err.code = 'AUTH_REQUIRED';
                throw err;
            }

            var data = await response.json();
            if (data.plan) return data.plan;
            return parseAgentResponse(data.text || '', message);
        } catch (e) {
            console.warn('[AgentPanel] API call failed, using heuristic:', e.message);
            throw e;
        }
    }

    /**
     * 构建 System Prompt
     */
    function buildSystemPrompt(memory) {
        var levelInfo = window.AgentMemory
            ? window.AgentMemory.getLevelInfo(memory.level || 1)
            : { title: '学徒' };

        var prompt = '你是智能画布 AI 助手（能力等级：' + levelInfo.title + ' Lv.' + (memory.level || 1) + '）。\n';
        prompt += '你需要理解用户的自然语言，并返回一个 JSON 格式的操作计划。\n\n';
        prompt += '可用操作类型（action）：\n';
        prompt += '- create_prompt: 创建提示词卡片\n';
        prompt += '- optimize_prompt: 优化现有提示词\n';
        prompt += '- suggest_params: 推荐引擎和参数\n';
        prompt += '- create_workflow: 创建多个卡片组成工作流\n';
        prompt += '- chat: 纯对话回答\n\n';

        if (memory.level >= 3) {
            prompt += '你还可以创建循环节点和批量工作流。\n';
        }
        if (memory.level >= 4) {
            prompt += '你可以推荐提示词模板库中的预设。\n';
        }

        // 注入用户偏好
        if (memory.preferences && memory.preferences.preferred_engine) {
            prompt += '\n用户偏好引擎：' + memory.preferences.preferred_engine;
        }
        if (memory.preferences && memory.preferences.preferred_model) {
            prompt += '\n用户偏好模型：' + memory.preferences.preferred_model;
        }

        prompt += '\n\n返回纯 JSON（不要 markdown 代码块）：';
        prompt += '\n{"action":"create_prompt","prompt_text":"生成的提示词","engine_suggestion":"volcengine","model_suggestion":"","params":{"ratio":"16:9"},"cards":[{"type":"prompt","content":"提示词内容","title":"卡片标题"}],"reply":"给用户的友好回复"}';
        prompt += '\n\n引擎可选值：api, volcengine, modelscope, comfy, runninghub';
        prompt += '\n卡片类型可选值：prompt, image, loop';

        return prompt;
    }

    /**
     * 构建用户消息
     */
    function buildUserMessage(message, context, prefs) {
        var msg = '用户输入：' + message + '\n\n';
        msg += '画布状态：节点数=' + (context.nodeCount || 0);
        if (context.engine) msg += '，当前引擎=' + context.engine;
        if (context.model) msg += '，当前模型=' + context.model;
        if (context.selectedNodeCount) msg += '，已选节点数=' + context.selectedNodeCount;
        return msg;
    }

    /**
     * 解析 Agent 响应
     */
    function parseAgentResponse(text, fallbackMessage) {
        try {
            // 尝试提取 JSON
            var jsonStr = text;
            var jsonMatch = text.match(/\{[\s\S]*\}/);
            if (jsonMatch) {
                jsonStr = jsonMatch[0];
            }
            var parsed = JSON.parse(jsonStr);

            // 验证必要字段
            if (!parsed.action) parsed.action = 'chat';
            if (!parsed.reply) parsed.reply = '已处理你的请求。';
            if (!parsed.cards) parsed.cards = [];

            return parsed;
        } catch (e) {
            // JSON 解析失败，尝试启发式
            console.warn('[AgentPanel] JSON parse failed:', e);
            if (window.CanvasAgent) {
                return window.CanvasAgent.heuristicParse(fallbackMessage);
            }
            return {
                action: 'chat',
                reply: text || '已收到你的消息。',
                cards: []
            };
        }
    }

    // --- 评分 ---
    function submitRating(rating) {
        var payload = {
            rating: rating,
            accepted: rating >= 3,
            action_taken: 'manual_rating',
            session_id: currentSessionId,
            result: {}
        };
        if (window.AgentLearning) {
            window.AgentLearning.processFeedback({
                rating: rating,
                accepted: rating >= 3,
                action: 'manual_rating',
                sessionId: currentSessionId
            });
            updateSkillsPanel();
        }
        postAgentFeedback(payload);
        if (typeof toast === 'function') {
            toast('\u2B50 感谢评分！Agent 已记录你的反馈。');
        }
    }

    function postAgentFeedback(payload) {
        return fetch('/api/canvas-agent/feedback', {
            method: 'POST',
            credentials: 'same-origin',
            headers: teamCloudAuthHeaders(),
            body: JSON.stringify(payload || {})
        }).then(function(response) {
            if (response.ok) return { synced: true, status: response.status };
            return { synced: false, authRequired: response.status === 401 || response.status === 403, status: response.status };
        }).catch(function(e) {
            console.warn('[AgentPanel] feedback sync failed:', e.message);
            return { synced: false, error: e.message || 'sync failed' };
        });
    }

    function syncLabel(sync) {
        if (sync && sync.synced) return '已同步';
        if (sync && sync.authRequired) return '需登录';
        return '本地已记';
    }

    function syncTitle(sync) {
        if (sync && sync.synced) return '反馈已同步到账号记忆';
        if (sync && sync.authRequired) return '未登录，反馈只保存在本地记忆';
        return '反馈同步失败，已保存在本地记忆';
    }

    // --- 更新技能面板 ---
    function updateSkillsPanel() {
        if (!window.AgentMemory || !window.AgentLearning) return;

        try {
            var mem = window.AgentMemory.load();
            var stats = window.AgentLearning.getStatsSummary();
            var levelInfo = window.AgentMemory.getLevelInfo(mem.level);
            var progress = window.AgentLearning.getLevelProgress(mem.level, mem.experience);

            // 等级信息
            if (levelBadge) {
                levelBadge.textContent = 'Lv.' + mem.level;
                levelBadge.style.background = 'linear-gradient(135deg, ' + levelInfo.color + ', ' + levelInfo.color + 'dd)';
            }
            if (levelTitle) levelTitle.textContent = levelInfo.title;
            if (levelXp) levelXp.textContent = mem.experience + ' / ' + levelInfo.nextExp + ' XP';
            if (levelBarFill) levelBarFill.style.width = progress + '%';

            // 统计
            if (statsTotalTasks) statsTotalTasks.textContent = stats.totalTasks;
            if (statsSuccessRate) statsSuccessRate.textContent = stats.successRate + '%';
            if (statsAvgRating) statsAvgRating.textContent = (stats.avgRating || 0) + ' / 5';

            // 偏好
            if (prefEngine) prefEngine.textContent = mem.preferences.preferred_engine || '-';
            if (prefModel) prefModel.textContent = mem.preferences.preferred_model || '-';
            if (prefRatio) prefRatio.textContent = mem.preferences.preferred_ratio || '-';

            // 雷达图
            if (window.AgentLearning.renderRadarChart) {
                window.AgentLearning.renderRadarChart('agentRadarSvg', mem.skill_values);
            }

            // 成功案例
            if (successList) {
                var successes = window.AgentLearning.getRecentSuccesses(5);
                if (successes.length > 0) {
                    var html = '';
                    successes.forEach(function(s) {
                        var date = new Date(s.timestamp);
                        var dateStr = date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
                        html += '<div class="agent-success-item">';
                        html += '\u2705 ' + escapeAgentHtml(s.action || '操作') + ' (' + (s.rating || 0) + '星)';
                        html += '<div class="agent-success-date">' + dateStr + '</div>';
                        html += '</div>';
                    });
                    successList.innerHTML = html;
                } else {
                    successList.innerHTML = '<div style="color:var(--muted);font-size:11px;text-align:center;padding:12px">暂无成功案例<br>开始使用 Agent 吧！</div>';
                }
            }

            // 通知标记
            if (toggleBtn && mem.feedback_history && mem.feedback_history.length > 0) {
                toggleBtn.classList.add('has-notification');
            }
        } catch(e) {
            console.warn('[AgentPanel] updateSkillsPanel failed:', e);
        }
    }

    // --- 自动初始化 ---
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // 暴露面板刷新方法
    window.refreshAgentSkillsPanel = updateSkillsPanel;
})();
