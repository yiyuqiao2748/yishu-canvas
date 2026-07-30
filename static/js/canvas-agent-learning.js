/* ==========================================
   canvas-agent-learning.js
   学习系统 — 等级计算、反馈处理、雷达图渲染
   ========================================== */
(function() {
    'use strict';

    /**
     * 处理反馈并更新学习状态
     * @param {Object} feedback - { rating, accepted, action, sessionId }
     * @returns {Object} 更新后的记忆
     */
    function processFeedback(feedback) {
        if (!window.AgentMemory) return null;
        const mem = window.AgentMemory.addFeedback(feedback);
        if (!mem) return null;

        // 计算经验值变化
        let expDelta = 10; // 完成任务基础经验
        if (feedback.accepted !== false) expDelta += 20;
        if (feedback.rating >= 4) expDelta += 5;
        if (feedback.rating >= 5) expDelta += 10;
        if (feedback.accepted === false || feedback.rating <= 2) expDelta = -5;

        window.AgentMemory.addExperience(expDelta);

        // 更新技能值
        if (feedback.rating >= 4) {
            window.AgentMemory.updateSkill('accuracy', 2);
            window.AgentMemory.updateSkill('responsiveness', 1);
        }
        if (feedback.action === 'create_workflow') {
            window.AgentMemory.updateSkill('structure', 3);
        }
        if (feedback.action === 'create_prompt') {
            window.AgentMemory.updateSkill('creativity', 2);
        }
        if (feedback.action === 'suggest_params') {
            window.AgentMemory.updateSkill('breadth', 2);
        }
        if (feedback.rating >= 3) {
            window.AgentMemory.updateSkill('responsiveness', 1);
        }

        // 更新偏好
        if (feedback.paramsChanged) {
            if (feedback.paramsChanged.engine) {
                window.AgentMemory.updatePreference('preferred_engine', feedback.paramsChanged.engine);
            }
            if (feedback.paramsChanged.model) {
                window.AgentMemory.updatePreference('preferred_model', feedback.paramsChanged.model);
            }
        }

        return window.AgentMemory.load();
    }

    /**
     * 渲染雷达图
     * @param {string} svgId - SVG 元素 ID
     * @param {Object} skillValues - 技能值对象
     */
    function renderRadarChart(svgId, skillValues) {
        const svg = document.getElementById(svgId);
        if (!svg) return;

        const skills = [
            { key: 'creativity', label: '创造力' },
            { key: 'accuracy', label: '准确度' },
            { key: 'structure', label: '结构化' },
            { key: 'breadth', label: '知识广度' },
            { key: 'responsiveness', label: '响应速度' }
        ];

        const cx = 120, cy = 75, radius = 50;
        const angleStep = (2 * Math.PI) / skills.length;
        const levels = 5;

        let html = '';

        // 网格圈
        for (let l = 1; l <= levels; l++) {
            const r = (radius / levels) * l;
            let points = '';
            for (let i = 0; i < skills.length; i++) {
                const angle = -Math.PI / 2 + i * angleStep;
                const px = cx + r * Math.cos(angle);
                const py = cy + r * Math.sin(angle);
                points += px + ',' + py + ' ';
            }
            html += '<polygon points="' + points.trim() + '" fill="none" stroke="var(--agent-border, rgba(148,163,184,.12))" stroke-width="0.5"/>';
        }

        // 轴线
        for (let i = 0; i < skills.length; i++) {
            const angle = -Math.PI / 2 + i * angleStep;
            const ex = cx + radius * Math.cos(angle);
            const ey = cy + radius * Math.sin(angle);
            html += '<line x1="' + cx + '" y1="' + cy + '" x2="' + ex + '" y2="' + ey + '" stroke="var(--agent-border, rgba(148,163,184,.12))" stroke-width="0.5"/>';
        }

        // 数据多边形
        let dataPoints = '';
        const fillPoints = [];
        for (let i = 0; i < skills.length; i++) {
            const skill = skills[i];
            const value = (skillValues && skillValues[skill.key]) || 0;
            const r = (value / 100) * radius;
            const angle = -Math.PI / 2 + i * angleStep;
            const px = cx + r * Math.cos(angle);
            const py = cy + r * Math.sin(angle);
            dataPoints += px + ',' + py + ' ';
            fillPoints.push({ x: px, y: py });
        }
        html += '<polygon points="' + dataPoints.trim() + '" fill="rgba(139,92,246,0.15)" stroke="#8b5cf6" stroke-width="1.5" stroke-linejoin="round"/>';

        // 数据点
        fillPoints.forEach(function(p) {
            html += '<circle cx="' + p.x + '" cy="' + p.y + '" r="3" fill="#8b5cf6"/>';
        });

        // 标签
        for (let i = 0; i < skills.length; i++) {
            const skill = skills[i];
            const value = (skillValues && skillValues[skill.key]) || 0;
            const angle = -Math.PI / 2 + i * angleStep;
            const labelR = radius + 18;
            const lx = cx + labelR * Math.cos(angle);
            const ly = cy + labelR * Math.sin(angle);
            const textAnchor = Math.abs(Math.cos(angle)) < 0.1 ? 'middle' : (Math.cos(angle) > 0 ? 'start' : 'end');
            html += '<text x="' + lx + '" y="' + ly + '" text-anchor="' + textAnchor + '" dominant-baseline="middle" fill="var(--muted, #8f9aab)" font-size="9">' + skill.label + ' ' + value + '</text>';
        }

        svg.innerHTML = html;
    }

    /**
     * 获取等级进度百分比
     * @param {number} level - 当前等级
     * @param {number} experience - 经验值
     * @returns {number} 0-100
     */
    function getLevelProgress(level, experience) {
        if (!window.AgentMemory) return 0;
        const info = window.AgentMemory.getLevelInfo(level);
        const thresholds = { 1: 0, 2: 200, 3: 500, 4: 1000, 5: 2000 };
        const currentThreshold = thresholds[level] || 0;
        const nextThreshold = thresholds[level + 1] || 3000;
        const range = nextThreshold - currentThreshold;
        if (range <= 0) return 100;
        const progress = ((experience - currentThreshold) / range) * 100;
        return Math.min(100, Math.max(0, Math.round(progress)));
    }

    /**
     * 获取最近成功案例
     */
    function getRecentSuccesses(limit) {
        if (!window.AgentMemory) return [];
        const mem = window.AgentMemory.load();
        limit = limit || 5;
        return (mem.feedback_history || [])
            .filter(function(f) { return f.accepted !== false && f.rating >= 3; })
            .slice(-limit)
            .reverse();
    }

    /**
     * 获取统计摘要
     */
    function getStatsSummary() {
        if (!window.AgentMemory) return {};
        const mem = window.AgentMemory.load();
        const successRate = mem.total_tasks > 0
            ? Math.round((mem.total_successes / mem.total_tasks) * 100)
            : 0;
        return {
            totalTasks: mem.total_tasks,
            successRate: successRate,
            avgRating: mem.avg_rating || 0,
            level: mem.level,
            experience: mem.experience,
            preferences: mem.preferences || {},
            skillValues: mem.skill_values || {}
        };
    }

    // 挂载到全局
    window.AgentLearning = {
        processFeedback: processFeedback,
        renderRadarChart: renderRadarChart,
        getLevelProgress: getLevelProgress,
        getRecentSuccesses: getRecentSuccesses,
        getStatsSummary: getStatsSummary
    };
})();
