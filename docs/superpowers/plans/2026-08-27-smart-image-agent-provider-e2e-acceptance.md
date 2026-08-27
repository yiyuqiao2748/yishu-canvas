# Smart Image Agent v3 Provider E2E Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Supabase 测试项目中以真实、用户本地输入的 Provider key 验收 v3 文生图、参考图编辑和四图批量生成，且真实生成总数不超过 6 张。

**Architecture:** 不修改现有业务代码。先经现有团队 Provider `/models` 端点做一次不计费发现，只在 token 实际可见且项目现有白名单支持的 `gpt-image-2` 出现时，暂时保存 `custom-api` 配置并开启单团队 v3；浏览器从团队云画布执行既有 v3 runner。验收结束后删除 Provider、关闭白名单，并将无密钥的证据写入独立记录。

**Tech Stack:** FastAPI、Supabase 测试数据库、PowerShell、现有 Team Cloud REST API、Smart Canvas 浏览器 UI、OpenAI-compatible Provider API。

## Global Constraints

- 仅使用 Supabase 测试项目 `kwxeqhgnimvpspwqkepj`、本地 `127.0.0.1:3000` 和测试团队 `436d7f4e-858a-491b-aec6-5568c68c0b4a`；不得访问生产环境。
- Provider key 仅在本机交互输入；不得写入仓库、`.env`、终端输出、验收记录或聊天。
- 先请求 `GET /v1/models`；只有其返回的精确 ID 含 `gpt-image-2` 才允许付费调用。`gpt-image-2-1k` 等不同 ID 必须停止，不能映射或替换。
- 真实图片仅用 `gpt-image-2`、`standard`、`1k`；总数上限为 6，任何失败均不自动重试。
- 单张文生图 1 张、单张参考图编辑 1 张、批量文生图一次 4 张；三次操作全部必须由 UI 显式确认后才执行。
- 测试结束必须删除 `custom-api` Provider、关闭 v3 团队白名单并重启本地服务验证 HTTP 403。
- 现有未提交 v3 业务文件均为用户工作区内容，不修改、不暂存、不提交；本计划只可新增验收文档。

---

## File Structure

- Read: `docs/superpowers/specs/2026-08-27-smart-image-agent-provider-e2e-design.md` — 已批准的范围、安全边界与成功标准。
- Read: `team_cloud.py:174-203,1034-1075,4382-4438` — Provider 请求字段、模型发现、保存和删除端点。
- Read: `main.py` 的 v3 白名单及执行端点 — 确认本地服务只对目标团队开放。
- Read: `static/js/smart-canvas.js:1-32,18050-18189` — 团队云画布上下文和 `runImageTask` 对既有 `custom-api` / `gpt-image-2` 的调用方式。
- Create: `docs/superpowers/verification/2026-08-27-smart-image-agent-v3-provider-e2e.md` — 无密钥的执行数量、HTTP 状态、run 状态、日志、画布刷新和清理证据。

### Task 1: 启动封闭的测试服务并发现实际模型

**Files:**
- Read: `team_cloud.py:1034-1075,4382-4438`
- Create: `docs/superpowers/verification/2026-08-27-smart-image-agent-v3-provider-e2e.md`

**Interfaces:**
- Consumes: `POST /api/team-cloud/teams/{team_id}/api-providers/{provider_id}/models` with `TeamApiProviderModelsRequest`.
- Produces: 已过滤的 token 可见模型 ID，以及是否允许付费执行的明确 `gpt-image-2` 判定。

- [ ] **Step 1: 在新的 PowerShell 窗口设置仅本次会话的服务变量**

  不要把 key 写进命令、历史记录或文件。沿用此前测试 Supabase 的 `SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY` 和测试开发用户设置；新增本会话密钥并默认关闭 v3：

  ```powershell
  $env:TEAM_API_SECRET_KEY = ((New-Guid).Guid + (New-Guid).Guid)
  $env:SMART_IMAGE_AGENT_V3_ENABLED_TEAMS = ""
  $env:SMART_IMAGE_AGENT_V3_ALLOW_ALL = "0"
  py main.py
  ```

  Expected: Uvicorn reports `http://0.0.0.0:3000`; v3 is closed.

- [ ] **Step 2: 在第二个 PowerShell 窗口安全读取 Provider key 并仅做模型发现**

  `Read-Host -AsSecureString` 不会回显 key；转换后的 `$providerKey` 仅存活在当前窗口内。Base URL 按 Provider 文档使用 `https://newapi-2.oairegbox.cc/v1`。

  ```powershell
  $secureProviderKey = Read-Host '输入测试 Provider key（不会显示）' -AsSecureString
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureProviderKey)
  try {
      $providerKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
  } finally {
      [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
  }
  $teamId = '436d7f4e-858a-491b-aec6-5568c68c0b4a'
  $discoverBody = @{
      label = 'Provider E2E Test'
      base_url = 'https://newapi-2.oairegbox.cc/v1'
      protocol = 'openai'
      api_key = $providerKey
  } | ConvertTo-Json
  $models = Invoke-RestMethod -Method Post `
      -Uri "http://127.0.0.1:3000/api/team-cloud/teams/$teamId/api-providers/custom-api/models" `
      -ContentType 'application/json' -Body $discoverBody
  $visibleIds = @($models.models.image_models | ForEach-Object { [string]$_ })
  $visibleIds
  ```

  Expected: only model IDs and a successful response are printed; neither the request body nor the key is saved.

- [ ] **Step 3: Enforce the exact model gate**

  ```powershell
  if ($visibleIds -notcontains 'gpt-image-2') {
      Remove-Variable providerKey -ErrorAction SilentlyContinue
      throw 'STOP: token 未返回项目已支持的精确 gpt-image-2；未保存 Provider，未执行任何付费生成。'
  }
  ```

  Expected: if the command throws, stop this plan after documenting the model mismatch. Do not use `gpt-image-2-1k` or another substituted ID.

- [ ] **Step 4: Create the initial evidence record**

  Record test project ref, team ID, local endpoint, model discovery status and the exact-model result. Do not record base URL with query data, authentication headers, any key, or raw Provider responses.

- [ ] **Step 5: Commit the no-cost gate evidence**

  ```powershell
  git add docs/superpowers/verification/2026-08-27-smart-image-agent-v3-provider-e2e.md
  git commit -m "docs(agent): record provider model gate"
  ```

### Task 2: 保存短期 Provider 配置并建立团队云画布

**Files:**
- Read: `team_cloud.py:174-203,4200-4245,4404-4438`
- Read: `static/js/smart-canvas.js:1-32,6180-6265`
- Modify: `docs/superpowers/verification/2026-08-27-smart-image-agent-v3-provider-e2e.md`

**Interfaces:**
- Consumes: exact `gpt-image-2` from Task 1, `PUT /api/team-cloud/teams/{team_id}/api-providers/custom-api`, Team Cloud project/canvas UI.
- Produces: a `custom-api` configuration scoped to the test team and a cloud canvas URL containing `cloud=1`, `id`, and `project`.

- [ ] **Step 1: Save the Provider to the test team using the in-memory key**

  In the same client PowerShell window from Task 1, do not retype or print `$providerKey`:

  ```powershell
  $saveBody = @{
      label = 'Provider E2E Test'
      base_url = 'https://newapi-2.oairegbox.cc/v1'
      protocol = 'openai'
      enabled = $true
      api_key = $providerKey
      image_models = @('gpt-image-2')
      chat_models = @()
      video_models = @()
  } | ConvertTo-Json
  Invoke-RestMethod -Method Put `
      -Uri "http://127.0.0.1:3000/api/team-cloud/teams/$teamId/api-providers/custom-api" `
      -ContentType 'application/json' -Body $saveBody
  ```

  Expected: response shows `has_api_key: true` or masked key metadata only; it must never show the actual key.

- [ ] **Step 2: Temporarily enable v3 only for the target test team**

  In the service PowerShell window, press physical `Ctrl+C` once to stop Uvicorn, then run:

  ```powershell
  $env:SMART_IMAGE_AGENT_V3_ENABLED_TEAMS = '436d7f4e-858a-491b-aec6-5568c68c0b4a'
  $env:SMART_IMAGE_AGENT_V3_ALLOW_ALL = '0'
  py main.py
  ```

  Expected: local server restarts; `TEAM_API_SECRET_KEY` remains unchanged because this is the same PowerShell window.

- [ ] **Step 3: Create or select a test-team cloud project and canvas through Team Cloud UI**

  Open `http://127.0.0.1:3000/static/team-cloud.html`, select `Smart Image Agent v3 Test`, create a project named `Provider E2E 2026-08-27` and an empty Smart Canvas named `Provider E2E`. Open it from the Team Cloud canvas list, not by manually editing a standalone canvas URL.

  Expected: browser localStorage has the selected team, and the opened URL contains `cloud=1`, `project=<project id>` and `id=<canvas id>`; this is required because `smartImageAgentCanvasContext()` sends the team ID only in cloud mode.

- [ ] **Step 4: Confirm the browser sees the configured model before any generation**

  Open the v3 panel from the cloud canvas. Select `gpt-image-2`, standard quality, `1k`, and inspect the plan before confirmation. The pre-confirmation view must show zero queued runs.

- [ ] **Step 5: Append setup evidence and commit it**

  Record only IDs/statuses: Provider saved, cloud canvas ID, settings selected and pre-confirmation run count `0`.

  ```powershell
  git add docs/superpowers/verification/2026-08-27-smart-image-agent-v3-provider-e2e.md
  git commit -m "docs(agent): record provider e2e setup"
  ```

### Task 3: Execute the three explicitly limited real-generation checks

**Files:**
- Read: `static/js/smart-canvas.js:18050-18189`
- Read: `static/js/smart-image-agent/v3/capability-runner.js`
- Modify: `docs/superpowers/verification/2026-08-27-smart-image-agent-v3-provider-e2e.md`

**Interfaces:**
- Consumes: team cloud canvas and v3 `custom-api` / `gpt-image-2` plan from Task 2.
- Produces: no more than six successful/failed paid image attempts, canvas output nodes and Team Cloud generation log entries.

- [ ] **Step 1: Run one text-to-image generation**

  In the v3 panel, write a simple prompt, select `gpt-image-2`, `standard`, `1k`, count `1`; generate a plan and verify it shows zero runs. Press the one explicit confirmation control exactly once.

  Expected: exactly one run becomes `queued`, then `running`, then `succeeded`; one result appears as a canvas node. If it fails, record it and stop—do not retry.

- [ ] **Step 2: Run one reference-image edit from the first result**

  Select the image from Step 1 as the only reference. Request a small visible change, keep `gpt-image-2`, `standard`, `1k`, count `1`; generate a plan, verify zero runs, then confirm exactly once.

  Expected: the existing browser bridge sends the reference image through the configured multipart edit request; exactly one new run and one output node result. If the Provider rejects edit input, record the response class and stop—do not change the protocol or retry.

- [ ] **Step 3: Run the four-image batch once**

  Clear references, request four variations with count `4`, keep `gpt-image-2`, `standard`, `1k`; generate one plan, verify zero runs, then confirm exactly once.

  Expected: exactly four runs are created and no fifth batch item appears. Wait for all four terminal statuses without pressing confirmation again.

- [ ] **Step 4: Enforce the hard cap after every confirmation**

  Track only `1 + 1 + 4 = 6`. If the UI presents more than the expected run count or any action may create a seventh image, do not press it; stop and document the discrepancy.

- [ ] **Step 5: Verify persisted results without invoking the Provider again**

  Refresh the cloud canvas once. Confirm result nodes remain visible. In Team Cloud generation logs, record run IDs, terminal statuses, image counts, points fields and error summaries (if any); do not copy result URLs that contain signed query parameters.

- [ ] **Step 6: Append execution evidence and commit it**

  ```powershell
  git add docs/superpowers/verification/2026-08-27-smart-image-agent-v3-provider-e2e.md
  git commit -m "docs(agent): record provider e2e results"
  ```

### Task 4: Remove all temporary authority and prove v3 is closed again

**Files:**
- Read: `team_cloud.py:4432-4438`
- Modify: `docs/superpowers/verification/2026-08-27-smart-image-agent-v3-provider-e2e.md`

**Interfaces:**
- Consumes: `DELETE /api/team-cloud/teams/{team_id}/api-providers/custom-api` and service environment from Tasks 1–3.
- Produces: no stored Provider key, v3 disabled for the target team and a documented HTTP 403 check.

- [ ] **Step 1: Delete the stored test Provider**

  In the client PowerShell, run the delete request. It does not need the Provider key.

  ```powershell
  Invoke-RestMethod -Method Delete `
      -Uri "http://127.0.0.1:3000/api/team-cloud/teams/$teamId/api-providers/custom-api"
  Remove-Variable providerKey, secureProviderKey, saveBody, discoverBody -ErrorAction SilentlyContinue
  ```

  Expected: provider deletion succeeds and the sensitive in-memory variables no longer exist in this PowerShell process.

- [ ] **Step 2: Close the v3 whitelist and restart the local service**

  In the service PowerShell window, press physical `Ctrl+C`, then execute:

  ```powershell
  $env:SMART_IMAGE_AGENT_V3_ENABLED_TEAMS = ''
  $env:SMART_IMAGE_AGENT_V3_ALLOW_ALL = '0'
  py main.py
  ```

  Expected: only local test server starts; v3 is disabled for every team.

- [ ] **Step 3: Verify the target team is denied before any provider call**

  Reload the same cloud canvas and in the v3 panel enter any non-empty prompt, keep count `1`, then press only **生成方案** (do not press the later approval button). Expect the UI request to `POST /api/smart-image-agent/v3/executions` to show `HTTP 403` / `Smart Image Agent v3 is not enabled for this team`. Because the route rejects before it creates an execution, no Provider request or paid image can occur.

- [ ] **Step 4: Record cleanup and run repository checks**

  Document Provider absent, whitelist variables, restart result, 403 result, total paid-image cap and any incomplete check. Then run:

  ```powershell
  py -m unittest tests.test_smart_image_agent
  npm run build:scripts
  git diff --check
  git status --short
  ```

  Expected: tests and build pass; `git diff --check` is clean. Do not stage the pre-existing v3 implementation changes.

- [ ] **Step 5: Commit the final evidence**

  ```powershell
  git add docs/superpowers/verification/2026-08-27-smart-image-agent-v3-provider-e2e.md
  git commit -m "docs(agent): finalize provider e2e acceptance"
  ```

## Exit Conditions

- Pass: exact model is visible; no more than six images are attempted; each planned operation has its expected run count; persisted canvas/log evidence exists; Provider is deleted; v3 returns 403 after shutdown of its whitelist.
- Safe stop: `gpt-image-2` is absent, a paid request fails, the edit endpoint is rejected, or a seventh image could be queued. Record the condition and clean up; do not retry or change Provider semantics.
