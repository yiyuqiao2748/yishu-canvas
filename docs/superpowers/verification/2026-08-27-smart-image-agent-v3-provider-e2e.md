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
