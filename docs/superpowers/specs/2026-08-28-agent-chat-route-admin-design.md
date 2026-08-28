# 图片 Agent 助手模型管理员配置设计

## 目标

让管理员在现有 API 设置页为图片 Agent 选择默认聊天 Provider 与聊天模型。模型列表由管理员手动刷新；普通画布用户不能查看、修改或触发模型发现。

## 已确认事实

- API 设置页已有“拉取模型”，它使用服务端 `POST /api/providers/fetch-models` 请求上游 `/v1/models`，将模型暂存到模型选择器，管理员保存 Provider 后写入该 Provider 的 `chat_models`。
- 图片 Agent 的聊天路由独立使用 `AGENT_CHAT_PROVIDER` 和 `AGENT_CHAT_MODEL`；运行时由 `resolve_agent_model_route("chat", ...)` 校验 Provider、模型和 Key，并保留 Agnes fallback。
- `update_env_values()` 可持久化并更新进程环境；`reload_env_globals()` 目前不会重载 Agent 聊天路由变量。
- 现有 Provider 配置为应用全局配置，并非按团队保存。因此本期 Agent 助手路由也是应用全局配置。

## 范围

- 在 API 设置页添加只对管理员可见的“图片 Agent 助手”区。
- 提供读取与保存全局聊天路由的服务端 API。
- 保存前校验启用状态、`chat_models` 归属和服务端 Key；保存后无需重启生效。
- 扩展现有 API 设置前端权限门，所有新 API 在服务端再次校验 owner/admin。

## 不在范围内

- 不自动调用 OAIREGBOX；模型刷新必须由管理员点击既有“拉取模型”。
- 不发起聊天或图片生成，不读取、显示或回传完整 API Key。
- 不在图片 Agent 工作区增加模型选择控件；普通用户继续只选择图片模型。
- 不改 Provider 配置的既有全局权限模型；将 Provider 改为按团队隔离是独立安全重构。

## 方案比较

| 方案 | 优点 | 风险/不足 | 结论 |
| --- | --- | --- | --- |
| 直接编辑 `.env` | 无开发成本 | 易输错、需人工确认、无模型校验 | 不采用 |
| 在图片工作区选择助手模型 | 操作路径短 | 普通用户会看到管理能力，配置容易随任务漂移 | 不采用 |
| API 设置页管理全局路由 | 复用现有 Provider 与模型选择流程，权限边界明确 | 当前配置为全局，多个团队共享该默认值 | 采用 |

## 采用设计

### 1. 管理员 API

新增 `GET /api/smart-image-agent/v3/admin/chat-route` 与 `PUT /api/smart-image-agent/v3/admin/chat-route`。

- 两个接口均以 `user: CurrentUser = Depends(require_user)` 接收登录用户，并调用 `resolve_admin_team(user, team_id)`。请求不带 `team_id` 时仍须拥有至少一个 owner/admin 团队角色。
- GET 返回 `{provider_id, model, fallback_provider_id, fallback_model, providers}`；`providers` 只包含启用且有 Key 的 Provider，并且每项只公开 `id`、`name`、`chat_models`、`has_key`，不公开 Key 或 Key 预览。
- PUT 输入 `team_id`、`provider_id`、`model`。服务端要求目标 Provider 启用、`model` 精确属于 `chat_models`、并且 Provider 有服务端 Key；失败返回 400，不写入任何配置。
- 成功时写入 `AGENT_CHAT_PROVIDER` 与 `AGENT_CHAT_MODEL`，调用扩展后的 `reload_env_globals()` 立即刷新同名全局变量，并清除 API config cache。fallback 保持现有环境配置，不在本期修改。

### 2. API 设置页

在现有“模型列表”下增加全局设置区：

- 文案明确为“图片 Agent 助手（管理员）”，并说明“先选 Provider，必要时点击拉取模型并保存 Provider 后再选择”。
- Provider 下拉仅展示 GET 返回的可用 Provider；模型下拉只展示当前 Provider 的 `chat_models`。
- 首次进入时加载当前路由；保存按钮调用 PUT。没有聊天模型或没有 Key 的 Provider 不可选，并提示先配置 Provider。
- 前端沿用 `ensureApiSettingsAccess()`，但不把前端权限门作为安全控制；服务端 PUT/GET 才是最终授权。

### 3. 运行时与失败处理

- 已有 `resolve_agent_model_route()` 无需改变选择优先级：任务上下文显式指定聊天模型时优先，否则使用新的全局默认值。
- 若 Provider 之后被禁用、模型从其列表移除或 Key 被清空，既有 resolver 继续尝试 Agnes fallback；管理员 GET 返回当前失效状态，但不自动重写默认值。
- 模型发现失败时，由既有 `fetch-models` 呈现上游错误；不会覆盖已保存 Provider 或助手默认值。

## 测试

- 单元测试：读取路由不泄露 Key；非管理员拒绝；缺失 Provider、禁用 Provider、未导入模型和缺失 Key 的保存均拒绝；有效保存更新运行时路由与 `.env` 写入函数调用。
- 前端源代码契约测试：管理员区使用独立 GET/PUT 路由，Provider 变更后只显示该 Provider 的 `chat_models`，不引用 Key 值。
- 回归：现有 Smart Image Agent 路由和 v3 UI 测试继续通过；不调用上游模型列表或生成接口。

## 风险与取舍

- 【已知限制】Provider 与此默认路由是应用全局配置；多团队相互隔离需要后续将 Provider 存储与 Agent 设置改为 team-scoped，不能在本期假装已经隔离。
- 将管理员授权加到新接口不会修复旧 `/api/providers` 全局接口的历史授权边界；本期不扩展为全量权限重构，以避免影响已使用的管理流程。
