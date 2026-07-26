# Team API Model Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add manual model management plus OpenAI-compatible API validation/fetching to team API settings.

**Architecture:** Extend encrypted team API config with model arrays, expose admin-only endpoints for validation and fetching, and update the existing static team-cloud page to edit and display those model arrays. Keep the existing provider storage pattern.

**Tech Stack:** FastAPI, Pydantic, httpx, vanilla JavaScript, unittest.

## Global Constraints

- Do not expose full API keys in responses.
- Owner/admin can manage API configuration; members can only use public metadata.
- Support automatic validation/fetching only for OpenAI-compatible protocol in this pass.
- Existing Supabase/local store behavior must continue passing tests.

---

### Task 1: Backend Config and Model Fetch

**Files:**
- Modify: `team_cloud.py`
- Test: `tests/test_team_cloud.py`

**Interfaces:**
- Produces: `TeamApiProviderModelsRequest`, `parse_model_lines`, `fetch_openai_compatible_models`, `POST /teams/{team_id}/api-providers/{provider_id}/validate`, `POST /teams/{team_id}/api-providers/{provider_id}/models`

- [ ] Write failing tests for model config persistence and `/models` parsing.
- [ ] Run focused unittest and confirm failures.
- [ ] Add model arrays to encrypted config and public config.
- [ ] Add OpenAI-compatible `/models` request helper and admin endpoints.
- [ ] Run focused unittest and confirm pass.

### Task 2: Frontend Controls

**Files:**
- Modify: `static/team-cloud.html`
- Modify: `static/js/team-cloud.js`

**Interfaces:**
- Consumes: backend public provider fields `image_models`, `chat_models`, `video_models`.
- Produces: textareas `apiImageModels`, `apiChatModels`, `apiVideoModels`, buttons `apiProviderValidate`, `apiProviderFetchModels`.

- [ ] Add model textareas and validation button to the existing team API panel.
- [ ] Include model arrays in save payload.
- [ ] Render model chips from saved provider model arrays first, static catalog second.
- [ ] Wire validate and fetch buttons to backend endpoints.
- [ ] Run `node --check static/js/team-cloud.js`.

### Task 3: Verify, Sync, Commit

**Files:**
- Modify: `VERSION`
- Sync changed files to `Z:\yishu-canvas\yishu-canvas-fnos`.

- [ ] Bump version.
- [ ] Run JS check, Python compile, unittest, and diff check.
- [ ] Sync changed files to NAS without touching `.env`.
- [ ] Commit and push to `origin main`.
