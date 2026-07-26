# Team Workbench Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn yishu-canvas into a company-internal AI design workbench with private-by-default canvases, admin-managed team API, fast local/NAS media display, team sharing, and 115 cold archive.

**Architecture:** Keep the current FastAPI + static HTML/CSS/JS structure. Add a shared workbench shell and storage lifecycle layer without rewriting the canvas engine. Move daily users toward a direct "workbench -> canvas -> generate -> private assets -> publish to team" workflow.

**Tech Stack:** FastAPI (`main.py`, `team_cloud.py`, `team_storage.py`), Supabase Postgres/Auth, Cloudflare Access, Cloudflare Tunnel, Cloudflare R2 optional backup, NAS local storage, static HTML/CSS/JS, lucide icons, Python unittest.

## Global Constraints

- Do not pixel-copy the reference product's logo, exact copy, assets, or protected visual identity; use it only as direction for a dark AI design workbench.
- Ordinary members must not see API settings by default.
- Owner/Admin can configure team API, models, members, and team-level storage.
- API keys must never be returned to frontend, logs, Git, docs, or browser storage.
- Ordinary members can generate with team API but cannot inspect the full key.
- User-created canvases and generated assets are private by default.
- Other members cannot view a user's private canvases or private assets.
- Team visibility requires explicit "publish/share/save to team" action.
- Generated original images should save to NAS/server-local private user storage first, not R2 by default.
- UI must display generated images immediately, then save in background.
- Asset and canvas lists must load thumbnails/previews first; full 4K originals load only on explicit open/download/detail.
- R2 is optional backup/public compatibility, not default display source.
- 115 remote mount is cold archive only, not real-time canvas storage.
- Auto cleanup must never delete referenced, locked, favorited, or team-published originals without archive and recovery metadata.
- Current project root is `K:\claudecode\yishu-canvas`.
- Existing test command is `.venv\Scripts\python.exe -m unittest discover -s tests`.
- Current dirty item `.codex-speedtest-current/` is a local speed-test leftover and is not part of this plan.

---

## Product Rules

### Roles

| Role | Daily Canvas | Team Assets | API Settings | Cleanup / Archive |
| --- | --- | --- | --- | --- |
| Owner | Full access | Full access | Full access | Full access |
| Admin | Full access | Full access | Full access | Full access |
| Member | Own private canvases + shared team canvases | Upload/use team assets, delete only own private assets | Hidden | No system cleanup controls |

### Storage Classes

| Class | Visibility | Default Location | Loaded In UI | Cleanup |
| --- | --- | --- | --- | --- |
| Private original | Owner only | NAS local `storage/users/{user_id}/generated/` | No, only on detail/download | Archive after rule match |
| Private thumbnail | Owner only | NAS local `storage/users/{user_id}/thumbs/` | Yes | Keep while DB record exists |
| Team original | Team members | NAS local `storage/teams/{team_id}/assets/` | No, only on detail/download | Protected by reference check |
| Team thumbnail | Team members | NAS local `storage/teams/{team_id}/thumbs/` | Yes | Keep while DB record exists |
| R2 copy | Optional external backup | Cloudflare R2 | No by default | Not required for first pass |
| 115 archive | Cold archive | Remote mount `115/yishu-canvas-archive/` | No | Restore on demand |

### Sharing Rules

- New canvas: private to creator.
- New generated image: private to creator.
- New uploaded reference: private to creator unless uploaded through team asset panel.
- "Save to team": copy private asset to team asset storage and create team-visible asset record.
- "Publish canvas to team": create or update team-visible canvas record; private draft stays private unless user chooses to replace it.
- Team members cannot open another user's private canvas by guessing URLs.

---

## File Map

### Existing Files To Modify

- `main.py`: media download/proxy routes, generation response metadata, cleanup/archive commands if global routes live here.
- `team_cloud.py`: team auth, role checks, private/team canvas queries, team API/model config, team asset publish endpoints.
- `team_storage.py`: local NAS storage, thumbnail/original path handling, archive copy/restore helpers.
- `static/index.html`: new workbench home route or redirect to workbench.
- `static/canvas.html`: classic canvas shell layout.
- `static/smart-canvas.html`: smart canvas shell layout.
- `static/asset-manager.html`: asset manager role-aware UI and private/team tabs.
- `static/team-cloud.html`: admin-only team API/settings visibility.
- `static/css/theme.css`: shared color tokens and dark workbench variables.
- `static/css/canvas.css`: classic canvas layout and asset panel.
- `static/css/smart-canvas.css`: smart canvas layout and right panel alignment.
- `static/css/asset-manager.css`: private/team asset display and cleanup indicators.
- `static/js/canvas.js`: asset insertion, drag/drop, thumbnail display, cloud/private mode, background save status.
- `static/js/smart-canvas.js`: same layout/data behavior as classic canvas.
- `static/js/team-cloud.js`: role-aware team API UI and model editor.
- `static/js/team-assets.js`: reusable asset list, thumbnail-first rendering, publish/share actions.

### New Files To Create

- `static/workbench.html`: workbench home page if replacing `index.html` directly is too risky.
- `static/css/workbench.css`: workbench visual shell.
- `static/js/workbench.js`: workbench page state, recent items, direct navigation.
- `static/js/workbench-shell.js`: shared top bar, side rail, role-aware buttons.
- `static/js/media-client.js`: thumbnail/original URL helpers and image insertion behavior.
- `docs/storage-lifecycle.md`: user-facing storage, cleanup, and 115 archive rules.
- `docs/cloudflare-access-team-login.md`: Cloudflare Access auto-login and default team behavior.
- `tests/test_media_storage_lifecycle.py`: local save, thumbnail, archive metadata tests.
- `tests/test_team_privacy.py`: private canvas/asset access tests.
- `tests/test_team_api_roles.py`: API settings permission tests.

---

## Milestones

### Milestone 0: Safety Baseline

**Deliverable:** Current behavior is measured before redesign.

- [ ] Record current Git status and current commit hash.
- [x] Run targeted team-cloud static regression tests for canvas type and asset drag behavior.
- [x] Run syntax checks for `static/js/canvas-list.js`, `static/js/canvas.js`, `static/js/smart-canvas.js`, `static/js/team-cloud.js`.
- [ ] Run `.venv\Scripts\python.exe -m unittest discover -s tests`.
- [ ] Run final syntax checks for all changed JS files before commit.
- [ ] Capture screenshots of current home, classic canvas, smart canvas, asset manager, team page.
- [ ] Remove or ignore `.codex-speedtest-current/` before committing.

**Acceptance:**

- Tests pass or failures are documented before redesign starts.
- Screenshots exist for visual comparison.
- No secrets are printed or committed.

### Milestone 1: Role-Aware Team Entry

**Deliverable:** Users entering through Cloudflare Access can land in the default team without duplicate Supabase registration flow, and role controls are enforced.

**Files:**
- Modify: `team_cloud.py`
- Modify: `static/js/team-cloud.js`
- Modify: `static/team-cloud.html`
- Test: `tests/test_team_api_roles.py`

**Tasks:**

- [ ] Add/verify Cloudflare Access email identity parsing.
- [ ] Map accepted Cloudflare email to a Supabase/team user record.
- [ ] Auto-add first-time accepted users to configured default team as `member`.
- [ ] Hide API settings UI for `member`.
- [ ] Return role metadata in team bootstrap response.
- [ ] Add backend permission checks so hidden UI is not the only protection.
- [ ] Add tests for owner/admin/member API setting access.

**Acceptance:**

- Member sees no API setting entry.
- Admin sees team API setting entry.
- Member API config requests return forbidden.
- Admin API config requests pass.

### Milestone 2: Private-By-Default Data Model

**Deliverable:** Personal canvases and assets are not visible to other members unless explicitly shared.

**Files:**
- Modify: `team_cloud.py`
- Modify: `team_storage.py`
- Test: `tests/test_team_privacy.py`

**Tasks:**

- [ ] Add ownership checks to canvas list/detail endpoints.
- [ ] Add visibility field handling: `private`, `team`.
- [ ] Add publish endpoint for private canvas to team canvas.
- [ ] Add ownership checks to asset list/content endpoints.
- [ ] Add publish endpoint for private asset to team asset.
- [ ] Block guessed private asset/canvas URLs from other members.

**Acceptance:**

- User A cannot list, open, or fetch User B private canvas.
- User A cannot fetch User B private asset content.
- Published team canvas appears to team members.
- Published team asset appears to team members.

### Milestone 3: NAS-Local Media Lifecycle

**Deliverable:** Generated assets save locally on NAS private storage first, with thumbnail-first display and optional team publishing.

**Files:**
- Modify: `team_storage.py`
- Modify: `team_cloud.py`
- Modify: `main.py`
- Create: `tests/test_media_storage_lifecycle.py`
- Create: `docs/storage-lifecycle.md`

**Tasks:**

- [ ] Define private original path format: `storage/users/{user_id}/generated/{asset_id}.{ext}`.
- [ ] Define private thumbnail path format: `storage/users/{user_id}/thumbs/{asset_id}.webp` or `.jpg`.
- [ ] Generate thumbnail after image save.
- [ ] Return `thumbnail_url` for lists and `original_url` only for detail/download.
- [ ] Store media metadata: owner, team, visibility, original path, thumbnail path, size, mime, created time, last accessed time.
- [ ] Add publish-to-team copy path.
- [ ] Update storage lifecycle docs.

**Acceptance:**

- Asset list loads thumbnails only.
- Detail view can open original.
- Publishing copies the asset into team storage and creates team-visible metadata.
- R2 is not required for normal display.

### Milestone 4: Async Save User Experience

**Deliverable:** Generated images appear immediately; saving to NAS happens in the background with visible status.

**Files:**
- Modify: `main.py`
- Modify: `static/js/canvas.js`
- Modify: `static/js/smart-canvas.js`
- Create: `static/js/media-client.js`

**Tasks:**

- [ ] Ensure generation response includes immediate display URL or temporary content URL.
- [ ] Add frontend status states: `保存中`, `已保存`, `保存失败，点击重试`.
- [ ] Add retry save action.
- [ ] Do not block canvas node creation while saving original/thumbnail.
- [ ] Persist final asset metadata after save succeeds.

**Acceptance:**

- Generated result appears before save completes.
- Slow save does not freeze canvas.
- Failed save is visible and retryable.

### Milestone 5: Workbench Home Redesign

**Deliverable:** Main entry becomes a polished AI design workbench in the direction of the reference image.

**Files:**
- Create: `static/workbench.html`
- Create: `static/css/workbench.css`
- Create: `static/js/workbench.js`
- Modify: `static/index.html`
- Modify: `static/css/theme.css`

**Tasks:**

- [ ] Add dark warm workbench visual tokens.
- [ ] Add centered prompt creation area.
- [ ] Add reference image upload and URL controls.
- [ ] Add model, size, and resolution selectors from available API models.
- [ ] Add recent private assets and recent team assets.
- [ ] Add entry buttons for my canvases, team canvases, and history.
- [ ] Ensure reference design influence is not a direct copy.

**Acceptance:**

- `/` or selected entry opens workbench.
- Member can start generating without seeing API settings.
- Admin can navigate to API settings.
- Page works in desktop and reasonable tablet widths.

### Milestone 6: Canvas Shell Redesign

**Deliverable:** Classic canvas and smart canvas share the same stable layout: top pill bar, left tool rail, central grid, right generator/asset panel.

**Files:**
- Modify: `static/canvas.html`
- Modify: `static/smart-canvas.html`
- Modify: `static/css/canvas.css`
- Modify: `static/css/smart-canvas.css`
- Create: `static/js/workbench-shell.js`

**Tasks:**

- [ ] Create shared top bar component logic.
- [ ] Align history/workflow/assets/log controls to top-right.
- [x] Move smart canvas history/assets/log controls into a top-right layout override.
- [ ] Create left vertical tool rail for select/text/image/crop/delete where supported.
- [ ] Keep existing canvas engine and node data model.
- [ ] Ensure text does not overflow fixed buttons.
- [x] Ensure light/dark mode toggles affect team canvas pages consistently through shared dark workbench CSS overrides.

**Acceptance:**

- Classic canvas and smart canvas no longer have different panel placement.
- Right sidebar mirrors the ordinary canvas layout.
- Existing node creation and saving still work.

### Milestone 7: Right-Side Generation Panel

**Deliverable:** Canvas pages can generate from a right-side panel using team API and save results into private assets.

**Files:**
- Modify: `static/js/canvas.js`
- Modify: `static/js/smart-canvas.js`
- Modify: `static/js/team-assets.js`
- Modify: `static/css/canvas.css`
- Modify: `static/css/smart-canvas.css`

**Tasks:**

- [ ] Add prompt editor to right sidebar.
- [ ] Add prompt optimizer button as UI placeholder if backend is not ready; disable with clear message if no model is available.
- [ ] Add image/chat/video model selectors based on team API models.
- [ ] Add aspect ratio and resolution selectors.
- [ ] Add reference image upload and URL list.
- [ ] Add generate action.
- [ ] Add generated result list with `加入画布`, `设为参考图`, `保存到团队`, `删除`.

**Acceptance:**

- Member can generate through team API without configuring API.
- Generated result becomes a private asset first.
- User can add result to canvas.
- User can publish result to team assets.

### Milestone 8: Team API Model Manager

**Deliverable:** Team API settings match the richer API settings workflow: add model, delete model, choose default, validate, pull models.

**Files:**
- Modify: `team_cloud.py`
- Modify: `static/team-cloud.html`
- Modify: `static/js/team-cloud.js`
- Modify: `static/css/api-settings.css` if shared styles are reused
- Test: `tests/test_team_api_roles.py`

**Tasks:**

- [ ] Preserve encrypted key storage behavior.
- [ ] Add manual model creation for image/chat/video categories.
- [ ] Add default model selection per category.
- [ ] Add remove model action.
- [ ] Add validate base URL action.
- [ ] Add validate protocol action.
- [ ] Add pull models action when provider supports it.
- [ ] Add member-hidden/admin-visible UI states.

**Acceptance:**

- Admin can add image model manually.
- Admin can add chat model manually.
- Admin can set default model.
- Member cannot open model editor.
- Saved key remains after rebuild when `.env` and database are preserved.

### Milestone 9: 115 Cold Archive And Cleanup

**Deliverable:** Old originals can be safely archived to 115 before NAS cleanup, while thumbnails and restore metadata remain.

**Files:**
- Modify: `team_storage.py`
- Modify: `team_cloud.py`
- Modify: `main.py`
- Create: `docs/storage-lifecycle.md`
- Test: `tests/test_media_storage_lifecycle.py`

**Tasks:**

- [ ] Add archive manifest structure with asset id, owner id, team id, original NAS path, archive path, size, hash, archived time, visibility, reference status.
- [ ] Add dry-run cleanup endpoint for admins.
- [ ] Add manual archive command for files older than 30 days and not locked/favorited/recently used.
- [ ] Copy candidate originals to 115 archive path.
- [ ] Verify copied file by size and hash.
- [ ] Mark asset as archived.
- [ ] Delete only the NAS original after verification.
- [ ] Keep thumbnail and database record.
- [ ] Add restore action that copies archived original back to NAS.

**Acceptance:**

- Dry run lists files and estimated reclaimed space without deleting.
- Archive copies and verifies before deleting NAS original.
- Archived asset still appears in UI with thumbnail.
- Opening original prompts restore when original is archived.
- Restore brings original back.

### Milestone 10: Deployment And Verification

**Deliverable:** Changes are tested locally, pushed to GitHub, deployed to NAS, and verified through public URL.

**Files:**
- Modify docs as needed.
- No new business files unless defects require fixes.

**Tasks:**

- [ ] Run `.venv\Scripts\python.exe -m unittest discover -s tests`.
- [ ] Run JS syntax checks for changed JS files.
- [ ] Run local app and capture screenshots for workbench, classic canvas, smart canvas, team API, asset manager.
- [ ] Verify member account cannot see API settings.
- [ ] Verify admin account can see API settings.
- [ ] Verify private canvas isolation with two users.
- [ ] Verify generated 4K image uses thumbnail in asset list.
- [ ] Verify original opens only on detail/download.
- [ ] Verify public URL no longer loads 20MB originals in list view.
- [ ] Push to GitHub.
- [ ] Sync NAS deployment while preserving `.env`.
- [ ] Rebuild/restart Docker compose.
- [ ] Verify `https://canvas.yiyuqiaoai.uk/`.

**Acceptance:**

- Tests pass.
- No secret appears in Git diff.
- Public page works through Cloudflare Access.
- Member workflow is: enter site -> workbench -> create private canvas -> generate -> see thumbnail -> publish to team if needed.

---

## Progress Tracker

| Milestone | Status | Notes |
| --- | --- | --- |
| 0 Safety Baseline | In progress | Targeted tests and JS syntax checks completed; full test run pending |
| 1 Role-Aware Team Entry | Not started | Needed before hiding API for members |
| 2 Private-By-Default Data Model | Not started | Blocks privacy requirements |
| 3 NAS-Local Media Lifecycle | Not started | Blocks fast media display |
| 4 Async Save UX | Not started | Prevents NAS save latency from blocking canvas |
| 5 Workbench Home Redesign | In progress | Project list and main sidebar now use AI designer workbench direction |
| 6 Canvas Shell Redesign | In progress | Classic and smart canvas have matching dark shell and right-panel overrides |
| 7 Right-Side Generation Panel | Not started | Main generation workflow |
| 8 Team API Model Manager | Not started | Admin-only API management |
| 9 115 Cold Archive And Cleanup | Not started | Storage protection |
| 10 Deployment And Verification | In progress | GitHub/NAS handoff planned for this pass |

---

## Open Decisions

These are intentionally fixed for the first implementation pass to keep scope controlled:

- Default storage is NAS local private storage, not user's computer and not R2.
- R2 remains optional backup/compatibility storage.
- 115 is cold archive only and starts with manual admin action, not automatic scheduled deletion.
- Real-time多人协作 is not included in this pass; privacy and private/team sharing come first.
- Team asset deletion remains protected by reference checks.
- Ordinary members can upload team assets, but deleting team assets should be admin-only in the first pass.

---

## Recommended Execution Order

1. Milestone 0
2. Milestone 1
3. Milestone 2
4. Milestone 3
5. Milestone 4
6. Milestone 6
7. Milestone 7
8. Milestone 5
9. Milestone 8
10. Milestone 9
11. Milestone 10

This order prioritizes permission correctness and storage speed before the visual redesign. The UI will look better only after the data rules are safe.

---

## Self-Review

- Spec coverage: Covered member/admin API visibility, private canvases, private assets, NAS-local originals, thumbnail-first display, async save, team publish, 115 archive, cleanup protection, and reference-inspired UI redesign.
- Placeholder scan: No TBD/TODO placeholders are present.
- Type consistency: Data names are consistent at the planning level: `private`, `team`, `thumbnail_url`, `original_url`, `archived`.
- Scope check: This is a large product redesign split into milestones. Each milestone is independently testable and can be reviewed before continuing.
