# Smart Image Agent Controls Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four verified `custom-api` image models and a fixed composer/history/control layout to the Smart Canvas image Agent without changing Classic Canvas.

**Architecture:** Centralize image model policy in `smart_image_agent.py` so local and Supabase stores calculate the same route and estimate. Rework only the Smart Image Agent rail and expose existing viewport/arrange functions through the established bridge.

**Tech Stack:** FastAPI, Pydantic, native JavaScript, CSS, Lucide, unittest.

## Global Constraints

- Smart Canvas only; do not modify `static/canvas.html`, Classic Canvas scripts, styles, or loader.
- Models: `gpt-image-2` (6), `nano-banana-2` (12), `nano-banana-pro` (18), and `gpt-image-2-vip` (20).
- All models use `custom-api`; do not add video, audio, 3D, RunningHub, or Agnes image fallback.
- Plan creation must not deduct points or create runs.
- Keep `assets/` and `data/` untracked.

---

### Task 1: Centralize four-model policy

**Files:**
- Modify: `smart_image_agent.py:35-80,335-418,660-746`
- Modify: `tests/test_smart_image_agent.py:36-92`

**Interfaces:**
- Produces: `SMART_IMAGE_AGENT_MODELS` and `resolve_smart_image_agent_model(model, quality)`.
- Compatibility: old `quality=standard|pro` plans still resolve to Nano Banana 2/Pro when `model` is absent.

- [ ] **Step 1: Write failing tests**

```python
def test_explicit_model_sets_verified_route_and_points(self):
    expected = {
        "gpt-image-2": 6,
        "nano-banana-2": 12,
        "nano-banana-pro": 18,
        "gpt-image-2-vip": 20,
    }
    for model, points in expected.items():
        with self.subTest(model=model):
            plan = self.create_plan(model=model)
            self.assertEqual(plan["provider_id"], "custom-api")
            self.assertEqual(plan["model"], model)
            self.assertEqual(plan["estimated_points"], points)

def test_unknown_model_is_rejected_without_creating_a_plan(self):
    with self.assertRaises(HTTPException) as error:
        self.create_plan(model="unverified-image-model")
    self.assertEqual(error.exception.status_code, 422)
```

- [ ] **Step 2: Run focused test**

Run: ` .\.venv\Scripts\python.exe -m unittest tests.test_smart_image_agent.SmartImageAgentStoreTests.test_explicit_model_sets_verified_route_and_points -v`

Expected: FAIL because the request model has no explicit `model`.

- [ ] **Step 3: Implement resolver in both stores**

```python
SMART_IMAGE_AGENT_MODELS = {
    "gpt-image-2": {"provider_id": "custom-api", "quality": "standard", "unit_points": 6},
    "nano-banana-2": {"provider_id": "custom-api", "quality": "standard", "unit_points": 12},
    "nano-banana-pro": {"provider_id": "custom-api", "quality": "pro", "unit_points": 18},
    "gpt-image-2-vip": {"provider_id": "custom-api", "quality": "vip", "unit_points": 20},
}

def resolve_smart_image_agent_model(model="", quality="standard"):
    selected = str(model or "").strip()
    if selected:
        policy = SMART_IMAGE_AGENT_MODELS.get(selected)
        if not policy:
            raise HTTPException(status_code=422, detail="Unsupported Smart Image Agent model")
        return {"model": selected, **policy}
    selected = "nano-banana-pro" if quality == "pro" else "nano-banana-2"
    return {"model": selected, **SMART_IMAGE_AGENT_MODELS[selected]}
```

Persist only resolved provider, model, quality, unit points, and total estimate. Use this resolver in local and Supabase create/update methods.

- [ ] **Step 4: Verify**

Run: ` .\.venv\Scripts\python.exe -m unittest tests.test_smart_image_agent.SmartImageAgentStoreTests -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add smart_image_agent.py tests/test_smart_image_agent.py
git commit -m "feat(smart-image-agent): add verified image model policy"
```

### Task 2: Allow only the four policy models on Smart Canvas

**Files:**
- Modify: `static/js/smart-canvas.js:18053-18103`
- Modify: `tests/test_smart_image_agent.py:392-460`

**Interfaces:**
- Consumes: resolved `plan.provider_id`, `plan.model`, and `plan.quality`.
- Produces: `SmartImageAgentBridge.runImageTask` accepts exactly the four policy models.

- [ ] **Step 1: Write failing static test**

```python
def test_smart_canvas_agent_allows_only_verified_four_image_models(self):
    bridge = (self.root / "static/js/smart-canvas.js").read_text(encoding="utf-8")
    for model in ("gpt-image-2", "nano-banana-2", "nano-banana-pro", "gpt-image-2-vip"):
        self.assertIn(model, bridge)
    self.assertIn("plan?.provider_id !== 'custom-api'", bridge)
    self.assertNotIn("agnes-image-", bridge)
```

- [ ] **Step 2: Run focused test**

Run: ` .\.venv\Scripts\python.exe -m unittest tests.test_smart_image_agent.SmartImageAgentStaticIsolationTests.test_smart_canvas_agent_allows_only_verified_four_image_models -v`

Expected: FAIL because the current guard allows only Nano Banana models.

- [ ] **Step 3: Replace the generation guard**

```javascript
const SMART_IMAGE_AGENT_MODELS = new Set([
  'gpt-image-2', 'nano-banana-2', 'nano-banana-pro', 'gpt-image-2-vip'
]);
if(plan?.provider_id !== 'custom-api' || !SMART_IMAGE_AGENT_MODELS.has(plan?.model)){
  throw new Error('图片 Agent 仅允许使用已配置的四个图片模型');
}
```

- [ ] **Step 4: Verify and commit**

Run: ` .\.venv\Scripts\python.exe -m unittest tests.test_smart_image_agent.SmartImageAgentStaticIsolationTests.test_smart_canvas_agent_allows_only_verified_four_image_models -v`

```powershell
git add static/js/smart-canvas.js tests/test_smart_image_agent.py
git commit -m "feat(smart-canvas): allow four agent image models"
```

### Task 3: Implement model picker and fixed bottom composer

**Files:**
- Modify: `static/js/smart-image-agent/app.js:147-186,402-449,651-770`
- Modify: `static/css/smart-image-agent.css:39-240`
- Modify: `tests/test_smart_image_agent.py:392-475`

**Interfaces:**
- Produces: `data-model`, `data-session-history`, `data-new-session`, and `data-create` controls in the Smart Canvas-only Agent rail.
- Compatibility: API continues accepting `quality` for old stored plans; new UI sends explicit `model`.

- [ ] **Step 1: Write failing UI test**

```python
def test_smart_image_agent_has_fixed_composer_and_four_model_picker(self):
    app = (self.root / "static/js/smart-image-agent/app.js").read_text(encoding="utf-8")
    styles = (self.root / "static/css/smart-image-agent.css").read_text(encoding="utf-8")
    for model in ("gpt-image-2", "nano-banana-2", "nano-banana-pro", "gpt-image-2-vip"):
        self.assertIn(model, app)
    self.assertIn("data-model", app)
    self.assertIn("sia-composer-fixed", app)
    self.assertIn("position:sticky", styles)
```

- [ ] **Step 2: Run focused test**

Run: ` .\.venv\Scripts\python.exe -m unittest tests.test_smart_image_agent.SmartImageAgentStaticIsolationTests.test_smart_image_agent_has_fixed_composer_and_four_model_picker -v`

Expected: FAIL because the current UI has a two-value quality selector and scrolls its composer.

- [ ] **Step 3: Rebuild Smart Image Agent rail only**

```javascript
const MODEL_OPTIONS = [
  {id:'gpt-image-2', label:'GPT Image 2', points:6, detail:'快速通用'},
  {id:'nano-banana-2', label:'Nano Banana 2', points:12, detail:'默认创作'},
  {id:'nano-banana-pro', label:'Nano Banana Pro', points:18, detail:'高质量'},
  {id:'gpt-image-2-vip', label:'GPT Image 2 VIP', points:20, detail:'高质量 GPT'},
];
```

Use this exact list for composer and plan-card model selects. The header holds New session and History. The scrollable activity section holds current context, one plan, tasks, and results. The fixed composer retains upload, asset picker, role-labelled references, mentions, ratio, count, and create plan. Send `model: els.model.value` when creating and patching plans.

- [ ] **Step 4: Add layout styles**

```css
.smart-image-agent { display:grid; grid-template-rows:auto minmax(0,1fr) auto; }
.sia-activity { min-height:0; overflow:auto; }
.sia-composer-fixed { position:sticky; bottom:0; z-index:4; padding:10px; background:#111318; border-top:1px solid #2b3038; }
```

Keep existing dark colors and 8px-or-less corners. On mobile the composer remains the bottom drawer section.

- [ ] **Step 5: Verify and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_smart_image_agent -v
node --check static/js/smart-image-agent/app.js
node --check static/js/smart-canvas.js
```

```powershell
git add static/js/smart-image-agent/app.js static/css/smart-image-agent.css tests/test_smart_image_agent.py
git commit -m "feat(smart-image-agent): add fixed composer and model picker"
```

### Task 4: Add only verified canvas controls

**Files:**
- Modify: `static/js/smart-canvas.js:18131-18155`
- Modify: `static/js/smart-image-agent/app.js:651-770`
- Modify: `static/css/smart-image-agent.css:1-240`
- Modify: `tests/test_smart_image_agent.py:376-390`
- Modify: `T0D0.md`
- Modify: `docs/团队画布项目规划.md`

**Interfaces:**
- Produces: `SmartImageAgentBridge.canvasControls = { fitAll, zoomIn, zoomOut, resetZoom, arrangeSelection }`.
- Consumes: existing `fitAllNodesViewport`, `applyViewport`, `arrangeSelectedSmartNodes`, `render`, and `scheduleSave`.

- [ ] **Step 1: Write failing bridge test**

```python
def test_smart_bridge_exposes_only_verified_canvas_controls(self):
    smart = (self.root / "static/js/smart-canvas.js").read_text(encoding="utf-8")
    app = (self.root / "static/js/smart-image-agent/app.js").read_text(encoding="utf-8")
    for method in ("fitAll", "zoomIn", "zoomOut", "resetZoom", "arrangeSelection"):
        self.assertIn(f"{method}:", smart)
        self.assertIn(f"canvasControls.{method}", app)
    classic = (self.root / "static/canvas.html").read_text(encoding="utf-8")
    self.assertNotIn("canvasControls", classic)
```

- [ ] **Step 2: Run focused test**

Run: ` .\.venv\Scripts\python.exe -m unittest tests.test_smart_image_agent.SmartImageAgentStaticIsolationTests.test_smart_bridge_exposes_only_verified_canvas_controls -v`

Expected: FAIL because the bridge does not have `canvasControls`.

- [ ] **Step 3: Add bridge wrappers and control strip**

```javascript
canvasControls: Object.freeze({
  fitAll: () => fitAllNodesViewport(),
  zoomIn: () => { viewport.scale = Math.min(3, viewport.scale * 1.15); applyViewport(); scheduleSave(); },
  zoomOut: () => { viewport.scale = Math.max(0.1, viewport.scale / 1.15); applyViewport(); scheduleSave(); },
  resetZoom: () => { viewport.scale = 1; applyViewport(); scheduleSave(); },
  arrangeSelection: () => arrangeSelectedSmartNodes(),
}),
```

Render the five controls from the Smart Image Agent module with tooltips and Lucide icons. Do not create drawing or image-edit controls.

- [ ] **Step 4: Update progress documents**

Record local implementation completion in `T0D0.md` and `docs/团队画布项目规划.md`. Keep public-account browser acceptance pending until observed.

- [ ] **Step 5: Run full verification**

```powershell
npm run build:scripts
node --check static/js/smart-image-agent/app.js
node --check static/js/smart-canvas.js
.\.venv\Scripts\python.exe -m py_compile smart_image_agent.py main.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
```

Expected: all tests pass, syntax checks pass, and there are no whitespace errors.

- [ ] **Step 6: Commit**

```powershell
git add static/js/smart-canvas.js static/js/smart-image-agent/app.js static/css/smart-image-agent.css tests/test_smart_image_agent.py T0D0.md docs/团队画布项目规划.md
git commit -m "feat(smart-image-agent): add verified canvas controls"
```

## Final Acceptance

1. The Smart Canvas composer remains visible while history, plan, task, and result content scrolls.
2. Each of the four models makes one unconfirmed plan with estimates 6, 12, 18, and 20; no run exists before confirmation.
3. A confirmed task records the selected model.
4. Fit all, zoom out, reset 100%, zoom in, and arrange selected invoke working Smart Canvas behavior.
5. Classic Canvas receives no model picker, composer, or controls.
