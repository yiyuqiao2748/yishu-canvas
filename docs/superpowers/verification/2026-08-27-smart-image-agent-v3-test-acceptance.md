# Smart Image Agent v3 测试环境验收记录

## Task 1

- Python dependencies: PASS — `py -m pip install -r requirements.txt` 完成，补齐 PyJWT、boto3、cryptography 等声明依赖。
- unittest: PASS — `py -m unittest tests.test_smart_image_agent`：56 tests，0 failures。
- static build: PASS — `npm run build:scripts` 成功生成 `smart-image-agent-v3.min.js`。
- diff check: PASS — `git diff --check` 无格式错误。

备注：测试仅输出 FastAPI/Starlette 弃用警告，以及测试环境未配置 planner 外部 API key 时的 fallback 日志；没有测试失败。

## Task 2

- target classification: test — Supabase project ref `kwxeqhgnimvpspwqkepj`（`yishu-canvas-test`）。
- migration: PASS — `migration list` 显示 baseline 与 v3 两条 migration 的 Local/Remote 版本一致。
- tables and RPC: PASS — `db lint --linked --level error` 返回 `No schema errors found`。

说明：初次环境探测没有 Supabase CLI 或 migration 目录；现已通过用户新建的测试项目与版本化 migration 解除该前置条件。本机未安装 Docker，未执行 local container reset；实际 migration 仅应用到用户新建的测试项目，未连接生产项目。

## Task 3

- team allow-list: PASS — 唯一启用团队为 `Smart Image Agent v3 Test`；未列入白名单的测试团队创建 execution 返回 HTTP 403。
- v3 API lifecycle: PASS — 白名单团队的 execution 初始为 `awaiting_confirmation` 且 `runs=[]`；确认后变为 `queued`；确认前取消变为 `cancelled`；反馈 `rated:5` 已持久化。
- SSE and idempotency: PASS — 对同一 `approval_key` 重试确认仍返回同一 run；SSE 返回 5 条不重复、递增 sequence 的事件。
- v2/v3 loader isolation: PASS — 56 项本地契约测试覆盖；本地页面、loader、v2 bundle 与 v3 bundle 均返回 HTTP 200，loader 按 `image_agent=v3` 选择 v3 bundle，默认选择 v2 bundle。
- browser smoke test: PASS — 手动打开 `http://127.0.0.1:3000/static/smart-canvas.html?image_agent=v3`，确认 v3 外壳显示“图片创作导演”“先确认方案，再执行生成”与生成方案入口；v3 静态实现声明四个模型选项。

说明：验收计划中原写的 `/smart-canvas` 在当前应用中为 404；真实页面路径为 `/static/smart-canvas.html`，已据此完成浏览器验证。API 验收只验证队列、事件与幂等，不调用外部图像模型或生成资产。

## Final result

- overall: PASS — 本地/测试环境的 v3 migration、单团队灰度 API、SSE/幂等、loader 隔离与浏览器 smoke 均通过。
- production accessed: no。
- test rollout reset: yes — 清空 `SMART_IMAGE_AGENT_V3_ENABLED_TEAMS` 并保持 `SMART_IMAGE_AGENT_V3_ALLOW_ALL=0` 后，原白名单团队创建 execution 返回 HTTP 403。
- evidence: unittest 56/56、静态构建、`migration list` Local/Remote 一致、`db lint --linked --level error` 无 schema error、API lifecycle/SSE 命令输出、浏览器截图。
