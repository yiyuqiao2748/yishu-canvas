# Smart Image Agent v3 Usability Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Smart Image Agent v3 desktop side panel legible and unambiguous without changing image-generation behavior.

**Architecture:** Retain the v3 app, execution state machine, and API endpoints. Align `shell.js` markup with targeted CSS in `smart-image-agent.css`; add an empty-input feedback branch in `app.js`. A source-contract unittest verifies the UI without a browser or Provider.

**Tech Stack:** Vanilla JavaScript, CSS, Python `unittest`, esbuild.

## Global Constraints

- Do not change Provider requests, image billing, Supabase migrations, or v3 execution state transitions.
- Do not make a real image-generation request during verification.
- Preserve existing user-owned uncommitted changes outside the listed files.
- Build `static/dist/js/smart-image-agent-v3.min.js` with `npm run build:scripts`.

---

### Task 1: Lock the readable v3 UI contract with tests

**Files:**

- Create: `tests/test_smart_image_agent_v3_ui.py`
- Test: `tests/test_smart_image_agent_v3_ui.py`

**Interfaces:**

- Consumes: the v3 `app.js`, `shell.js`, and `smart-image-agent.css` files as UTF-8 source text.
- Produces: regression coverage for empty-input feedback, labelled controls, and layout selectors.

- [ ] **Step 1: Write the failing test**

```python
class SmartImageAgentV3UiTests(unittest.TestCase):
    def test_empty_intent_notifies_and_focuses_composer(self):
        source = read("static/js/smart-image-agent/v3/app.js")
        self.assertIn("notify('请先输入创作需求', 'error')", source)
        self.assertIn("els.intent.focus()", source)

    def test_shell_labels_current_plan_and_new_requirement(self):
        source = read("static/js/smart-image-agent/v3/shell.js")
        self.assertIn("当前方案", source)
        self.assertIn("新创作需求", source)

    def test_v3_css_prevents_wrapped_control_labels(self):
        source = read("static/css/smart-image-agent.css")
        self.assertIn(".sia-canvas-controls button", source)
        self.assertIn("white-space:nowrap", source)
        self.assertIn(".sia-composer-controls", source)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `py -m unittest tests.test_smart_image_agent_v3_ui`

Expected: FAIL because the current source has no labelled composer or empty-input feedback.

- [ ] **Step 3: Commit the failing test**

```powershell
git add -- tests/test_smart_image_agent_v3_ui.py
git commit -m "test(agent): cover v3 usability contract"
```

### Task 2: Make the v3 panel readable and provide input feedback

**Files:**

- Modify: `static/js/smart-image-agent/v3/app.js:create()`
- Modify: `static/js/smart-image-agent/v3/shell.js:createShell()`
- Modify: `static/css/smart-image-agent.css`
- Test: `tests/test_smart_image_agent_v3_ui.py`

**Interfaces:**

- Consumes: `els.intent`, `els.create`, and `notify(message, kind)` from the v3 app.
- Produces: visible empty-input feedback, readable v3 controls, and explicit current-plan/new-requirement labels.

- [ ] **Step 1: Implement the minimal empty-input branch**

```javascript
const message = els.intent.value.trim();
if(!message){
    notify('请先输入创作需求', 'error');
    els.intent.focus();
    return;
}
```

- [ ] **Step 2: Label the v3 shell without changing data attributes**

```html
<section data-plan hidden aria-label="当前方案"></section>
<label class="sia-composer-label" for="smartImageAgentIntent">新创作需求</label>
<textarea id="smartImageAgentIntent" data-intent ...></textarea>
```

Retain `data-plan` and `data-intent`, because `app.js` queries them through `createShell()`.

- [ ] **Step 3: Add CSS for actual v3 class names**

```css
.sia-canvas-controls button { width:auto; min-width:46px; padding:0 8px; white-space:nowrap; font-size:12px; }
.sia-section-head,.sia-composer-label { display:flex; font-size:13px; font-weight:700; }
.sia-reference-actions,.sia-composer-controls { display:grid; gap:8px; }
.sia-composer-controls { grid-template-columns:minmax(0,1fr) 92px 54px; }
```

Use the existing dark palette. Add matching rules for `sia-plan-head`, plan textarea, `sia-results-section`, and `data-status` so v3 content retains readable spacing and at least 12px text.

- [ ] **Step 4: Run targeted tests**

Run: `py -m unittest tests.test_smart_image_agent_v3_ui`

Expected: PASS.

- [ ] **Step 5: Build the v3 bundle**

Run: `npm run build:scripts`

Expected: exits 0 and writes `static/dist/js/smart-image-agent-v3.min.js`.

- [ ] **Step 6: Commit implementation and generated bundle**

```powershell
git add -- static/js/smart-image-agent/v3/app.js static/js/smart-image-agent/v3/shell.js static/css/smart-image-agent.css static/dist/js/smart-image-agent-v3.min.js tests/test_smart_image_agent_v3_ui.py
git commit -m "fix(agent): make v3 panel usable"
```

### Task 3: Regression verification and final acceptance handoff

**Files:**

- Test: `tests/test_smart_image_agent_v3_ui.py`
- Test: `tests/test_smart_image_agent.py`
- Test: `tests/test_gpt_image_output_cap.py`

**Interfaces:**

- Consumes: completed v3 source and generated bundle.
- Produces: evidence that generation contracts did not change and the panel source contract remains intact.

- [ ] **Step 1: Run automated regressions**

```powershell
py -m unittest tests.test_smart_image_agent_v3_ui
py -m unittest tests.test_smart_image_agent
py -m unittest tests.test_gpt_image_output_cap
npm run build:scripts
git diff --check
```

Expected: every command exits 0; no Provider HTTP request is made.

- [ ] **Step 2: Inspect only intended working-tree paths**

Run: `git status --short -- static/js/smart-image-agent/v3 static/css/smart-image-agent.css static/dist/js/smart-image-agent-v3.min.js tests/test_smart_image_agent_v3_ui.py`

Expected: no uncommitted changes after Task 2 commit.

- [ ] **Step 3: Hand off one final browser check**

Ask the user only to refresh the v3 canvas, verify controls are horizontal/readable, type a new requirement into the labelled bottom field, and confirm an empty field shows the explicit error. Do not ask the user to run diagnostics or make a paid generation.

