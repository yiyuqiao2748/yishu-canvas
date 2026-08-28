# 图片 Agent 助手模型管理员配置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理员选择图片 Agent 的全局聊天 Provider 与模型，不暴露密钥，也不产生付费请求。

**Architecture:** 新增受 `require_user` 和 `resolve_admin_team` 保护的 GET/PUT 管理端点；端点复用既有 Provider 模型列表与 `update_env_values()`。API 设置页仅读取端点返回的脱敏 Provider、聊天模型和当前路由。

**Tech Stack:** FastAPI、Pydantic、Python unittest/TestClient、原生 JavaScript。

## 约束

- 不在页面加载或测试中调用上游 `/v1/models`、聊天或生成接口。
- 新接口不返回 API Key、Key 预览、环境变量名或原始 Provider。
- 本次为应用全局默认路由；不表示按团队隔离。
- 不改现有 Provider 管理、Supabase migration、图片模型选择或 Agnes fallback。

## Task 1：后端安全路由

文件：创建 `tests/test_agent_chat_route_admin.py`；修改 `main.py`。

1. 先写失败测试。模拟一个启用且有 Key 的 `gateway` Provider，聊天模型为 `gemini-3.5-flash-fast`。GET 必须只返回 `id`、`name`、`chat_models`、`has_key`，响应中不能出现 `api_key`。
2. 测试 PUT 保存 `{provider_id: "gateway", model: "gemini-3.5-flash-fast"}` 后只调用 `update_env_values({"AGENT_CHAT_PROVIDER": "gateway", "AGENT_CHAT_MODEL": "gemini-3.5-flash-fast"})`。
3. 覆盖缺失 Provider、禁用 Provider、未导入模型、缺少 Key 均返回 400；`resolve_admin_team` 返回 403 时 GET/PUT 均返回 403。
4. 运行新测试，预期因路由不存在而失败。
5. 新增 `AgentChatRouteUpdate`，字段为 `team_id`、`provider_id`、`model`；新增安全响应投影函数。
6. 新增 `GET/PUT /api/smart-image-agent/v3/admin/chat-route`。两个端点均先调用 `resolve_admin_team(user, team_id)`；PUT 以 `_agent_provider_supports_model` 和 `_agent_provider_has_key` 验证，再写环境值、清空 API cache 并返回安全响应。
7. 扩展 `reload_env_globals()` 重载 `AGENT_CHAT_PROVIDER`、`AGENT_CHAT_MODEL`，使保存无需重启。
8. 运行新测试和 `tests.test_smart_image_agent`，全部通过后提交 `feat(agent): configure admin chat route`。

## Task 2：API 设置页控件

文件：创建 `tests/test_api_settings_agent_chat_route_ui.py`；修改 `static/api-settings.html` 与 `static/js/api-settings.js`。

1. 先写失败源代码契约：HTML 含 `agentChatRouteBlock`；JS 含管理路由、`renderAgentChatRouteModels`；JS 不含 `provider.api_key`。
2. 运行测试，预期失败。
3. 在现有模型列表后增加隐藏管理员区，包含 Provider 下拉、模型下拉、保存按钮与提示；文案提示先使用既有“拉取模型”，勾选 LLM 并保存 Provider。
4. 实现 `loadAgentChatRoute()`、`renderAgentChatRouteModels()` 和 `saveAgentChatRoute()`；所有请求使用 `credentials:'same-origin'` 和 `teamAuthHeaders()`。
5. Provider 变更只能从当前安全响应的 `chat_models` 生成模型选项。GET 403 时隐藏区块，不自动重试；成功加载 Provider 后读取该配置。
6. 运行 UI 契约测试及静态构建；通过后提交 `feat(agent): add admin chat model control`。

## Task 3：审核、发布与线上验收

1. 运行新后端测试、新 UI 测试、Smart Image Agent、v3 UI 和单图输出保护测试；运行静态构建与差异检查。不得发起真实生成。
2. 快进合并本地 `workbench/main`。
3. 发布前核对：生产部署分支、Render 服务对应分支、生产 Supabase 项目及 R2/Supabase 变量、发布前 commit SHA。测试项目 `kwxeqhgnimvpspwqkepj` 不可作为生产目标。
4. 仅在以上目标明确后推送已确认部署分支触发 Render autoDeploy；等待 `/healthz` 200。
5. 线上以管理员验证助手模型读写和权限拒绝，以普通用户验证图片 Agent 不显示管理控件。线上验收不生成图片，除非另行授权付费冒烟。
6. 健康检查失败、管理员配置失败、普通用户访问到管理 API、或生产缺失必需变量时，立即回退部署分支至发布前 SHA 并确认健康检查恢复。
