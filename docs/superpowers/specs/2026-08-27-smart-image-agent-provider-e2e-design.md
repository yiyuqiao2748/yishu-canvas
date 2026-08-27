# Smart Image Agent v3 测试 Provider 端到端验收设计

## 目标

在现有 Supabase 测试项目和唯一测试团队中，使用一个用户本地输入的测试 Provider key，验证 v3 的真实图片生成链路；总生成量最多 6 张，禁止访问生产环境。

## 范围与安全边界

- 仅使用测试团队 `Smart Image Agent v3 Test`、本地服务与 Supabase 测试项目。
- Provider key 仅由用户在本地 Provider 设置中输入；不得写入仓库、`.env`、终端输出、验收记录或聊天。
- 先调用无计费的 `GET /v1/models`，再决定是否进行任何图片生成。
- 只接受当前项目已支持的 `gpt-image-2`；若 token 只返回 `gpt-image-2-1k` 等不同 ID，停止并另行设计兼容改造，不把 ID 擅自映射为 `gpt-image-2`。
- 真实生成只使用 `gpt-image-2`、标准质量、最低可用分辨率；最多 6 张。超过上限立即停止。
- 验收结束时删除测试团队 Provider 配置，并关闭 v3 白名单；不保留可用 key。

## 已确认的 Provider 契约

文档声明该网关提供 OpenAI 兼容的 `GET /v1/models` 与 `POST /v1/images/generations`；编辑走 `POST /v1/images/edits` 的 multipart 请求。模型可见性和实际价格由 token 与控制台决定，不在代码中推断。

## 流程

1. 启动只连接测试 Supabase 的本地服务，保持 v3 默认关闭。
2. 在测试团队保存一个 `custom-api` Provider：OpenAI 协议、用户提供的 Base URL、仅本地输入的 key；先验证模型列表。
3. 若模型列表包含 `gpt-image-2`，将 v3 仅对白名单测试团队短暂开启，并依次执行：
   - 文生图 1 张；
   - 使用第一张结果作为参考的编辑 1 张；
   - 四张批量生成 1 次（`count=4`）。
4. 每步记录状态、run 数、积分/日志、结果 URL 可读性、画布节点落图和刷新后的恢复情况；失败后不自动重试付费请求。
5. 删除该 Provider、关闭 v3 白名单、重启本地服务并验证原团队再次返回 HTTP 403。

## 成功标准

- 模型发现只使用 token 实际返回的模型 ID。
- 所有真实生成合计不超过 6 张；没有外部自动重试或生产请求。
- 每次确认前 run 数为 0；确认后 run 数与请求数量一致。
- 文生、编辑与四张批量均有结果、团队日志和可恢复的画布节点。
- 清理后 Provider 不存在，v3 返回 HTTP 403。

## 风险与取舍

- 测试 Provider 仍会产生费用；“6 张”是硬上限，不以灵感点估算替代 Provider 实际账单。
- 参考图编辑需符合 Provider 的 multipart、尺寸和总大小限制；不支持时记录失败，不换协议绕过。
- 当前项目模型白名单与 Provider 返回的模型 ID 可能不同；此设计选择停止而非静默适配，避免错误计费或调用未知模型。
