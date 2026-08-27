# Smart Image Agent v3 Provider E2E 验收记录

## Task 1：测试服务与模型门禁

- target: PASS — 本地服务配置端点报告 `supabase_ready=true`、`auth_ready=true`，并确认目标为 Supabase 测试项目 `kwxeqhgnimvpspwqkepj`。
- rollout: CLOSED — 服务启动时 `SMART_IMAGE_AGENT_V3_ENABLED_TEAMS` 为空且 `SMART_IMAGE_AGENT_V3_ALLOW_ALL=0`。
- model discovery: PASS — 测试 Provider 的无计费模型发现完成；image model 列表中含项目现有白名单的精确 ID `gpt-image-2`。
- model gate: PASS — 未将 `gpt-image-2-1k`、`gpt-image-2-2k` 或其他变体映射为 `gpt-image-2`。
- credentials: PASS — Provider key 与 Supabase Secret key 仅从用户本地文件输入运行中的本地进程；本记录、仓库和聊天不包含任何密钥或请求认证数据。
- paid images attempted: `0 / 6`。

## Pending tasks

- 保存短期 `custom-api` Provider，单团队开启 v3，并创建测试团队云画布。
- 在明确确认后执行文生图 1 张、参考图编辑 1 张、批量图 4 张。
- 删除 Provider、关闭白名单、验证 HTTP 403，并记录最终结果。

## Task 2：短期 Provider 与云画布

- provider: PASS — 测试团队存在已启用 `custom-api`；公开响应仅显示 `has_api_key=true` 和模型 `gpt-image-2`，未记录或输出密钥。
- rollout: PASS — 本地服务已重启为单团队白名单模式；允许团队为 `436d7f4e-858a-491b-aec6-5568c68c0b4a`，全量开关保持关闭。
- project: PASS — 创建隔离测试项目 `Provider E2E 2026-08-28`，ID 为 `f24e7314-ab1f-4d90-8cd6-22ca6ec3cc30`。
- canvas: PASS — 创建空 Smart Canvas，ID 为 `e9e88682-51b3-4eb0-8479-22c3bce6f702`。
- paid images attempted: `0 / 6`。

## Task 3：真实文生图的安全停止

- request: UNEXPECTED — UI 选择 `gpt-image-2`、数量 `1`，且只确认了一次；团队日志记录一条成功的 `custom-api` / `gpt-image-2` 调用。
- canvas result: UNEXPECTED — 画布返回同一输出节点中的两条不同图片 URL，而不是一条；因此按实际资产保守计为 `2 / 6`。
- root cause: CONFIRMED — `static/js/smart-canvas.js` 对单任务提交的 `n` 为 `1`，但 `main.py` 的无参考图 `gpt-image-2` 分支构造上游请求体时未发送 `n: 1`。该 Provider 默认返回两项，后端的 `extract_images(raw_item)` 与前端结果落图逻辑均按全部结果保留。
- billing: 【无法确认】Provider 的实际计费条目未暴露在本地或团队日志中；为避免低估，验收上限按两张资产处理。
- action: STOP — 未执行编辑或四图批量；在实现并验证“单次请求最多接受期望数量结果”的修复前，不进行任何进一步付费调用。
