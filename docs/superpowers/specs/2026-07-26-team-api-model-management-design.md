# Team API Model Management Design

## Goal

团队 API 页面需要让管理员手动维护模型列表，并能验证 OpenAI 兼容接口地址与 Key 是否可用。

## Scope

- 团队 API 配置保存 `image_models`、`chat_models`、`video_models` 三组模型。
- 页面提供一行一个模型名的手动输入。
- `拉取模型` 对 OpenAI 兼容协议调用后端接口，后端使用保存或本次输入的 Base URL / Key 请求 `/models`。
- `验证地址` 使用同一条后端能力，只验证 `/models` 可访问，不保存 Key。
- RunningHub、火山、Gemini、APIMart 暂不自动拉取模型，仍允许手动维护模型。

## Security

- API Key 只在后端解密或从本次请求临时读取。
- 后端响应不返回完整 API Key。
- 普通成员只能读取公开配置并使用团队 API；只有 owner/admin 可以保存、验证和拉取。

## Error Handling

- Base URL 为空时报中文错误。
- Key 为空时报中文错误。
- 第三方返回非 2xx 时，返回状态码和有限长度错误文本。
- 模型拉取只取 `data[].id`，无法识别分类的模型默认进入聊天模型。

## Verification

- 后端单元测试覆盖模型字段保存、OpenAI `/models` 解析、缺少 Key 错误。
- 前端 JS 语法检查通过。
- Python 编译检查通过。
- 全量 unittest 通过。
