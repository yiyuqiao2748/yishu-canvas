# Smart Image Agent v3 测试环境验收 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** 在本地或可确认的测试 Supabase 环境完成 Smart Image Agent v3 的自动化、migration 与单团队灰度验收，并保留可复现证据。

**Architecture:** 本计划不改变 v3 的业务实现。先恢复 Python 测试依赖并验证现有 API、持久化和前端隔离测试；随后用名称与连接策略双重确认非生产 Supabase 目标，才执行 additive migration；最后仅对白名单测试团队开启 v3，并验证端到端请求和默认 v2 隔离。

**Tech Stack:** Python 3.14、FastAPI、unittest、Node.js/esbuild、Supabase CLI 或已配置的测试数据库、PowerShell。

## Global Constraints

- 仅使用仓库可确认的本地或测试环境配置；不存在时明确记录为无法确认，不创建或猜测配置。
- 仅安装 \`requirements.txt\` 中已有 Python 依赖；不升级或锁定无关依赖。
- migration 仅执行 \`docs/supabase/smart_image_agent_v3.sql\`，目标必须是本地或测试 Supabase。
- 灰度只允许一个明确的测试团队 ID 写入 \`SMART_IMAGE_AGENT_V3_ENABLED_TEAMS\`；禁止设置 \`SMART_IMAGE_AGENT_V3_ALLOW_ALL=1\`。
- 不提交现有未提交的 v3 实现文件；本规格文档单独提交。
- 任一测试失败、migration 失败或目标无法判定为非生产时，不继续后续有状态步骤。

---

## File Structure

- Read: \`requirements.txt\` — 本地 Python 测试所需依赖的唯一来源。
- Test: \`tests/test_smart_image_agent.py\` — v2/v3 store、API、SSE、前端隔离与 migration 契约测试。
- Read: \`docs/supabase/smart_image_agent_v3.sql\` — additive schema 与原子确认 RPC。
- Read: \`docs/supabase/team-cloud.env.example\` — v3 灰度环境变量命名和默认值。
- Read/Build: \`tools/build-static-scripts.mjs\`、\`static/js/smart-image-agent/v3/\` — v3 bundle 输入。
- Create: \`docs/superpowers/verification/2026-08-27-smart-image-agent-v3-test-acceptance.md\` — 命令、目标判定与验收结果；不记录密钥、token 或完整连接串。

### Task 1: 恢复本地依赖并验证静态与后端契约

**Files:**

- Read: \`requirements.txt\`
- Test: \`tests/test_smart_image_agent.py\`
- Read/Build: \`tools/build-static-scripts.mjs\`
- Modify: \`docs/superpowers/verification/2026-08-27-smart-image-agent-v3-test-acceptance.md\`

**Interfaces:**

- Consumes: \`py -m pip\`、\`py -m unittest tests.test_smart_image_agent\`、\`npm run build:scripts\`。
- Produces: 后端测试、静态构建和 diff 检查的命令结果，供 Task 2 判断是否允许执行 migration。

- [ ] **Step 1: 确认缺失依赖和版本清单**

Run:

\`\`\`powershell
py -m pip show PyJWT
Get-Content -Raw requirements.txt
\`\`\`

Expected: \`PyJWT\` 未安装或显示已安装；依赖来源仅为 \`requirements.txt\`。

- [ ] **Step 2: 安装仓库声明的依赖**

Run:

\`\`\`powershell
py -m pip install -r requirements.txt
\`\`\`

Expected: 成功安装或确认已满足；不执行额外的 upgrade、uninstall 或 lockfile 写入。

- [ ] **Step 3: 运行完整 Python 契约测试**

Run:

\`\`\`powershell
py -m unittest tests.test_smart_image_agent
\`\`\`

Expected: \`OK\`，覆盖 v3 execution、approval、SSE、反馈、migration 契约、静态模块隔离与四模型策略。

- [ ] **Step 4: 重建 v3 bundle 并检查工作区补丁格式**

Run:

\`\`\`powershell
npm run build:scripts
git diff --check
\`\`\`

Expected: build 输出包含 \`smart-image-agent-v3.min.js\`；\`git diff --check\` 无错误。

- [ ] **Step 5: 记录并提交本任务的验收结果**

Create \`docs/superpowers/verification/2026-08-27-smart-image-agent-v3-test-acceptance.md\` with:

\`\`\`markdown
# Smart Image Agent v3 测试环境验收记录

## Task 1

- Python dependencies: PASS | FAIL
- unittest: PASS | FAIL
- static build: PASS | FAIL
- diff check: PASS | FAIL
\`\`\`

Run:

\`\`\`powershell
git add -- docs/superpowers/verification/2026-08-27-smart-image-agent-v3-test-acceptance.md
git commit -m "docs(agent): record v3 local acceptance"
\`\`\`

Expected: 仅提交验收记录；不暂存工作区已有 v3 业务文件。

### Task 2: 发现并验证非生产 Supabase migration 目标

**Files:**

- Read: \`docs/supabase/smart_image_agent_v3.sql\`
- Read: \`docs/supabase/team-cloud.env.example\`
- Modify: \`docs/superpowers/verification/2026-08-27-smart-image-agent-v3-test-acceptance.md\`

**Interfaces:**

- Consumes: Task 1 全部通过的结果，以及 Supabase CLI 或已配置测试数据库连接。
- Produces: 已确认的非生产 migration 目标和 schema/RPC 验证结果，供 Task 3 使用。

- [ ] **Step 1: 无密钥输出地发现候选配置**

Run:

\`\`\`powershell
Get-Command supabase -ErrorAction SilentlyContinue | Select-Object Name,Version
Get-ChildItem -Force -File -Name .env*,supabase* -ErrorAction SilentlyContinue
Get-ChildItem Env: | Where-Object { $_.Name -match 'SUPABASE|TEAM_CLOUD|DATABASE_URL' } | Select-Object -ExpandProperty Name
\`\`\`

Expected: 只显示 CLI、文件名和环境变量名；不得输出 URL、token、service role key 或密码。

- [ ] **Step 2: 明确拒绝任何无法判定的或生产目标**

Decision rule:

\`\`\`text
允许：本地 Supabase CLI 项目，或配置名称/主机名明确标识为 local、test、staging、preview、dev。
拒绝：production、prod、live，或没有可审计非生产标识的目标。
\`\`\`

Expected: 若没有允许目标，在验收记录写入 \`Task 2: 无法确认\`，停止，不执行 SQL。

- [ ] **Step 3: 验证本地 migration runner 是否能执行 v3 SQL**

Run only when \`supabase/config.toml\`、\`supabase/migrations/\` 和 Task 2 Step 2 已确认的 local 项目均存在：

\`\`\`powershell
supabase --version
Get-ChildItem supabase\migrations -File -Name
Get-FileHash docs\supabase\smart_image_agent_v3.sql -Algorithm SHA256
\`\`\`

Expected: 能定位一份版本化 migration，且其内容与 \`docs/supabase/smart_image_agent_v3.sql\` 的 SHA256 一致。若该 migration 不存在，记录 \`无法确认\` 并停止；不得把文档 SQL 临时复制或直接粘贴到数据库。

- [ ] **Step 4: 在已版本化的本地 migration 上执行并验证**

Run only when Step 3 确认有内容一致的 migration：

\`\`\`powershell
supabase db reset --local
supabase db lint --local --level error
\`\`\`

Expected: local reset 与 lint 均成功。migration 文件由 Supabase CLI 按时间顺序执行；不使用未文档化的 \`db query\` 子命令。

- [ ] **Step 5: 在明确测试远程目标推送已版本化 migration**

Run only when Step 2 已确认有受控测试项目、Step 3 已确认存在版本化 migration，并且团队既有测试环境流程已将该测试项目链接：

\`\`\`powershell
supabase db push --dry-run
supabase db push
\`\`\`

Expected: 预览仅包含 v3 additive migration，随后成功应用。若当前仓库没有已版本化 migration 或没有已链接测试项目，记录 \`无法确认\` 并停止；禁止通过 SQL Editor 直接执行文档 SQL。

- [ ] **Step 6: 更新验收记录并提交**

Append:

\`\`\`markdown
## Task 2

- target classification: local | test | rejected | unavailable
- migration: PASS | FAIL | NOT RUN
- tables and RPC: PASS | FAIL | NOT RUN
\`\`\`

Run:

\`\`\`powershell
git add -- docs/superpowers/verification/2026-08-27-smart-image-agent-v3-test-acceptance.md
git commit -m "docs(agent): record v3 migration acceptance"
\`\`\`

Expected: 仅验收记录更新被提交。

### Task 3: 配置单团队灰度并执行端到端验收

**Files:**

- Read: \`docs/supabase/team-cloud.env.example\`
- Read/Test: \`main.py\`
- Read/Test: \`static/js/smart-image-agent/loader.js\`
- Read/Test: \`static/js/smart-image-agent/v3/\`
- Modify: \`docs/superpowers/verification/2026-08-27-smart-image-agent-v3-test-acceptance.md\`

**Interfaces:**

- Consumes: Task 1 通过和 Task 2 的明确 local/test migration 目标。
- Produces: 单一测试团队的 API 与浏览器灰度验收结果；默认 v2 路径保持不变。

- [ ] **Step 1: 获取唯一测试团队 ID 并配置白名单**

Set only in the local/test service environment:

\`\`\`text
SMART_IMAGE_AGENT_V3_ENABLED_TEAMS=<one-confirmed-test-team-uuid>
SMART_IMAGE_AGENT_V3_ALLOW_ALL=0
\`\`\`

Expected: 不修改生产配置；不使用多个团队 ID；不设置 \`ALLOW_ALL=1\`。

- [ ] **Step 2: 验证灰度拒绝与允许行为**

Run against the local/test API with two authenticated test users, one在白名单团队、一个不在白名单团队。调用：

\`\`\`text
POST /api/smart-image-agent/v3/executions
\`\`\`

Expected: 非白名单团队返回 HTTP 403；白名单团队创建 \`awaiting_confirmation\` execution，且 \`runs\` 为空。

- [ ] **Step 3: 验证确认、事件、取消与作用域**

Run against the v3 execution returned in Step 2:

\`\`\`text
POST /api/smart-image-agent/v3/executions/{execution_id}/approve
GET  /api/smart-image-agent/v3/executions/{execution_id}/events?after_sequence=0
POST /api/smart-image-agent/v3/executions/{execution_id}/feedback
\`\`\`

Expected: 相同 \`approval_key\` 重试不重复创建 runs；events sequence 递增；跨用户或跨 canvas 访问被拒绝；取消只允许 confirmation 前执行。

- [ ] **Step 4: 验证浏览器加载隔离**

Open the local/test canvas twice:

\`\`\`text
/smart-canvas
/smart-canvas?image_agent=v3
\`\`\`

Expected: 第一条路径加载默认 v2 bundle；第二条路径加载 \`smart-image-agent-v3.min.js\`，展示四个模型和“先确认方案，再执行生成”，且生成/编辑/变体/扩图等操作仅经已验证 bridge 调用。

- [ ] **Step 5: 更新验收记录并提交**

Append:

\`\`\`markdown
## Task 3

- team allow-list: PASS | FAIL
- v3 API lifecycle: PASS | FAIL
- SSE and idempotency: PASS | FAIL
- v2/v3 loader isolation: PASS | FAIL
- browser smoke test: PASS | FAIL | NOT RUN
\`\`\`

Run:

\`\`\`powershell
git add -- docs/superpowers/verification/2026-08-27-smart-image-agent-v3-test-acceptance.md
git commit -m "docs(agent): record v3 rollout acceptance"
\`\`\`

Expected: 仅验收记录更新被提交。

### Task 4: 汇总结论并恢复安全默认值

**Files:**

- Modify: \`docs/superpowers/verification/2026-08-27-smart-image-agent-v3-test-acceptance.md\`

**Interfaces:**

- Consumes: Tasks 1–3 的命令输出、migration 日志和浏览器验收结果。
- Produces: 最终的通过/失败/无法确认结论，以及测试环境的灰度配置状态。

- [ ] **Step 1: 检查结果是否满足发布前置条件**

Decision rule:

\`\`\`text
可进入测试灰度：Task 1 全通过，Task 2 migration 与 schema/RPC 通过，Task 3 API lifecycle、SSE/idempotency 与 loader isolation 通过。
不可进入：任一项失败或无法确认。
\`\`\`

Expected: 不以静态构建成功替代数据库或端到端验收。

- [ ] **Step 2: 恢复测试环境默认关闭状态（如验收结束）**

Set in the same local/test service environment:

\`\`\`text
SMART_IMAGE_AGENT_V3_ENABLED_TEAMS=
SMART_IMAGE_AGENT_V3_ALLOW_ALL=0
\`\`\`

Expected: 仅在测试环境恢复默认关闭；不接触生产环境。

- [ ] **Step 3: 写入最终结论并提交**

Append:

\`\`\`markdown
## Final result

- overall: PASS | FAIL | UNCONFIRMED
- production accessed: no
- test rollout reset: yes | not applicable
- evidence: command names, exit codes, sanitized target classification
\`\`\`

Run:

\`\`\`powershell
git add -- docs/superpowers/verification/2026-08-27-smart-image-agent-v3-test-acceptance.md
git commit -m "docs(agent): finalize v3 test acceptance"
\`\`\`

Expected: 验收记录完整，且仍不包含任何密钥或生产配置。
