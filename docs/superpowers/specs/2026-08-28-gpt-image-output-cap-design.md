# GPT Image 2 单任务输出上限设计

## 目标

修复 Smart Canvas 通过 `custom-api` 调用无参考图 `gpt-image-2` 时，数量为 1 但非标准中转站返回并落图多张资产的问题；不得触发任何真实 Provider 请求。

## 已确认事实

- v3 每个逻辑 run 在 `static/js/smart-canvas.js` 向 `/api/canvas-image-tasks` 提交 `n: 1`。
- `main.py` 的无参考图 `gpt-image-2` 分支构造上游 `/images/generations` 请求时遗漏 `n`。
- 测试网关在缺少 `n` 时返回两条不同图片 URL；其他已观察的中转站默认返回一张，因此没有显现问题。
- `build_online_image_result()` 从原始上游响应提取全部图片并保存，故两条资产都进入画布。

## 方案比较

1. 仅在上游请求增加 `n: 1`：改动最小，但若某个网关忽略该参数，画布仍可接收多张结果。
2. 显式 `n: 1`，并在每个单次上游调用后最多保留一项：推荐。请求契约明确，且对不合规上游保留 UI 输出上限。
3. 多图返回时直接报错：可见性最高，但上游可能已经扣费且用户得不到任何结果，不适合作为默认行为。

## 采用设计

- 无参考图、`gpt-image-2` 分支向上游 JSON 请求体显式加入 `n: 1`。
- `build_online_image_result()` 的每次 `generate_one()` 仅处理 `extract_images(raw_item)` 的第一项；当前前端把批量 `count` 拆为多个单任务，因此总输出上限自然等于调用数。
- 不新增自动重试、不修改 Provider 配置、不改变参考图编辑路径或其他模型路径。
- 本次防止画布超量落图；Provider 是否对不合规响应额外计费仍【无法确认】，不能由客户端截断消除。

## 验收

- 单元测试拦截无参考图 `gpt-image-2` 的上游请求，断言 JSON 包含 `n: 1`。
- 单元测试模拟上游返回两张不同图片，断言单个任务结果与本地输出均仅包含第一张。
- 现有 `tests.test_smart_image_agent` 全量通过，静态构建和 `git diff --check` 通过。
- 本轮只做本地模拟验证；不得执行新的 Provider 图片生成。
