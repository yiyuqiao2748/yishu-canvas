/* ==========================================
   canvas-agent-memory.js
   localStorage 记忆管理 — 持久化 Agent 状态
   ========================================== */
(function() {
    'use strict';

    const STORAGE_KEY = 'canvas_agent_v2';
    const MAX_HISTORY = 50;

    // 默认记忆结构
    const DEFAULT_MEMORY = {
        level: 1,
        experience: 0,
        total_tasks: 0,
        total_successes: 0,
        total_failures: 0,
        avg_rating: 0,
        rating_count: 0,
        patterns: {},
        preferences: {
            preferred_engine: null,
            preferred_model: null,
            preferred_ratio: null,
            preferred_style: null
        },
        feedback_history: [],
        skill_values: {
            creativity: 25,
            accuracy: 30,
            structure: 20,
            breadth: 25,
            responsiveness: 50
        }
    };

    /**
     * 加载记忆
     */
    function load() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return JSON.parse(JSON.stringify(DEFAULT_MEMORY));
            const data = JSON.parse(raw);
            // 合并默认值（补充缺失字段）
            return deepMerge(JSON.parse(JSON.stringify(DEFAULT_MEMORY)), data);
        } catch (e) {
            console.warn('[AgentMemory] load failed:', e);
            return JSON.parse(JSON.stringify(DEFAULT_MEMORY));
        }
    }

    /**
     * 保存记忆
     */
    function save(memory) {
        try {
            // 限制 feedback_history 长度
            if (memory.feedback_history && memory.feedback_history.length > MAX_HISTORY) {
                memory.feedback_history = memory.feedback_history.slice(-MAX_HISTORY);
            }
            localStorage.setItem(STORAGE_KEY, JSON.stringify(memory));
        } catch (e) {
            console.warn('[AgentMemory] save failed:', e);
            // 如果保存失败（如 quota 超限），清理旧反馈
            if (memory.feedback_history) {
                memory.feedback_history = memory.feedback_history.slice(-20);
                try { localStorage.setItem(STORAGE_KEY, JSON.stringify(memory)); } catch(_) {}
            }
        }
    }

    /**
     * 深度合并对象
     */
    function deepMerge(target, source) {
        for (const key in source) {
            if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
                target[key] = target[key] || {};
                deepMerge(target[key], source[key]);
            } else {
                target[key] = source[key];
            }
        }
        return target;
    }

    /**
     * 添加反馈记录
     */
    function addFeedback(entry) {
        const memory = load();
        memory.feedback_history.push({
            timestamp: Date.now(),
            ...entry
        });
        memory.total_tasks++;
        if (entry.accepted !== false) {
            memory.total_successes++;
        } else {
            memory.total_failures++;
        }
        // 更新平均评分
        if (entry.rating && entry.rating > 0) {
            const totalStars = memory.avg_rating * memory.rating_count + entry.rating;
            memory.rating_count++;
            memory.avg_rating = +(totalStars / memory.rating_count).toFixed(2);
        }
        save(memory);
        return memory;
    }

    /**
     * 添加经验值
     */
    function addExperience(amount) {
        const memory = load();
        memory.experience = Math.max(0, memory.experience + amount);
        // 检查升级
        const newLevel = calculateLevel(memory.experience, memory.total_tasks, memory.avg_rating, memory.total_successes, memory.total_tasks ? memory.total_successes / memory.total_tasks : 0);
        memory.level = newLevel;
        save(memory);
        return memory;
    }

    /**
     * 更新偏好
     */
    function updatePreference(key, value) {
        const memory = load();
        memory.preferences[key] = value;
        save(memory);
        return memory;
    }

    /**
     * 更新技能值
     */
    function updateSkill(skillName, delta) {
        const memory = load();
        if (memory.skill_values[skillName] !== undefined) {
            memory.skill_values[skillName] = Math.min(100, Math.max(0, memory.skill_values[skillName] + delta));
        }
        save(memory);
        return memory;
    }

    /**
     * 添加模式
     */
    function addPattern(keyword, pattern) {
        const memory = load();
        if (!memory.patterns[keyword]) {
            memory.patterns[keyword] = { count: 0, success: 0, lastUsed: 0, template: pattern };
        }
        memory.patterns[keyword].count++;
        memory.patterns[keyword].lastUsed = Date.now();
        save(memory);
        return memory;
    }

    /**
     * 模式成功记录
     */
    function patternSuccess(keyword) {
        const memory = load();
        if (memory.patterns[keyword]) {
            memory.patterns[keyword].success++;
        }
        save(memory);
        return memory;
    }

    /**
     * 计算等级
     */
    function calculateLevel(exp, tasks, avgRating, successes, successRate) {
        if (tasks >= 200 && successRate >= 0.85) return 5;
        if (tasks >= 100 && successRate >= 0.70) return 4;
        if (tasks >= 50 && avgRating >= 3.5) return 3;
        if (tasks >= 20 && avgRating >= 3.0) return 2;
        return 1;
    }

    /**
     * 获取等级信息
     */
    function getLevelInfo(level) {
        const levels = {
            1: { title: '学徒', icon: 'graduation-cap', color: '#94a3b8', nextExp: 200 },
            2: { title: '工匠', icon: 'hammer', color: '#22c55e', nextExp: 500 },
            3: { title: '专家', icon: 'star', color: '#3b82f6', nextExp: 1000 },
            4: { title: '大师', icon: 'award', color: '#8b5cf6', nextExp: 2000 },
            5: { title: '传奇', icon: 'crown', color: '#f59e0b', nextExp: Infinity }
        };
        return levels[level] || levels[1];
    }

    /**
     * 重置记忆
     */
    function reset() {
        localStorage.removeItem(STORAGE_KEY);
        return JSON.parse(JSON.stringify(DEFAULT_MEMORY));
    }

    // 挂载到全局
    window.AgentMemory = {
        load,
        save,
        addFeedback,
        addExperience,
        updatePreference,
        updateSkill,
        addPattern,
        patternSuccess,
        getLevelInfo,
        reset,
        DEFAULT_MEMORY,
        STORAGE_KEY
    };
})();
