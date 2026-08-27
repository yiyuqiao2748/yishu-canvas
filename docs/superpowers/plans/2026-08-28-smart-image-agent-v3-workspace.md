# Smart Image Agent v3 工作区实施计划

## 目标

将 v3 右侧栏替换为画布优先的底部创作坞站，保持既有图片生成状态机不变。

## 约束

- 不改后端 API、Provider 请求、价格计算、Supabase 迁移或远程环境。
- 不发起真实图片生成或读取用户密钥。
- 不覆盖已有的用户未提交改动。

## Task 1：先锁定工作区契约

文件：`tests/test_smart_image_agent_v3_ui.py`

1. 为底部坞站根类、画布不缩窄规则、紧凑状态区和可读创作控件增加失败测试。
2. 保留既有空输入反馈与标签测试。
3. 运行 `py -m unittest tests.test_smart_image_agent_v3_ui`，确认在实现前失败。

## Task 2：重排 v3 Shell 与样式

文件：

- `static/js/smart-image-agent/v3/shell.js`
- `static/css/smart-image-agent.css`
- `static/js/smart-image-agent/v3/app.js`（仅在需要状态类切换时修改）

1. 将 v3 标记为工作区模式，移除右栏压缩画布的行为。
2. 为现有 `data-*` 节点增加工作区容器和可折叠引用区，但不修改 `app.js` 所依赖的元素引用。
3. 将 composer 重排为底部主入口；为窄屏提供堆叠回退。
4. 方案、活动和结果按状态显示紧凑、可滚动的区域。

## Task 3：构建与回归验证

1. `py -m unittest tests.test_smart_image_agent_v3_ui`
2. `py -m unittest tests.test_smart_image_agent`
3. `py -m unittest tests.test_gpt_image_output_cap`
4. `npm run build:scripts`
5. `git diff --check`

通过后提交仅属于本轮的源文件、测试和 v3 bundle；随后将提交快进合并到本地 `workbench/main`。不推送远程。
