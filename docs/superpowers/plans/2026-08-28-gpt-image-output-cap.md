# GPT Image 2 Output Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure one Smart Canvas `gpt-image-2` task explicitly requests and persists no more than one image.

**Architecture:** Keep existing Provider routing and edit behavior intact. The direct GPT Image 2 generation request receives `n: 1`; the per-call result collector in `build_online_image_result()` retains only the first extracted image, so one frontend task cannot produce a multi-asset canvas node when an upstream ignores `n`.

**Tech Stack:** Python 3, FastAPI, `unittest.IsolatedAsyncioTestCase`, `unittest.mock`.

## Global Constraints

- Do not call any real Provider, use an API key, or access the Supabase test project during this code fix.
- Modify only `main.py` and the new focused test file; do not alter the user-owned uncommitted v3 implementation files.
- Preserve reference-image editing, non-GPT models, Provider configuration, retry semantics and request URLs.
- `gpt-image-2` direct text generation must include JSON `n: 1`.
- A single `generate_one()` call must persist at most its first extracted upstream image; multi-count frontend requests remain multiple one-image tasks.

---

## File Structure

- Modify: `main.py:12058-12063` — add the explicit `n` parameter for direct GPT Image 2 generation.
- Modify: `main.py:14738-14760` — limit the per-call extracted image list before files are saved.
- Create: `tests/test_gpt_image_output_cap.py` — isolated upstream/client mocks covering request body and result persistence.

### Task 1: Capture the regression with local-only tests

**Files:**
- Create: `tests/test_gpt_image_output_cap.py`

**Interfaces:**
- Consumes: `main.generate_ai_image(prompt, size, quality, model, reference_images, provider_id, provider_config=...) -> tuple[dict, dict]`.
- Consumes: `main.build_online_image_result(payload, user=...) -> dict`.
- Produces: regression tests that fail before production changes without making network requests.

- [ ] **Step 1: Write a failing direct-GPT request test**

  Add a fake async HTTP client whose `post()` records `json` and returns this local payload:

  ```python
  {"data": [{"url": "https://example.test/first.png"}]}
  ```

  Patch `main.upstream_async_client` to return the fake client, then assert:

  ```python
  self.assertEqual(fake_client.post_body["n"], 1)
  ```

  Use provider `{ "id": "custom-api", "base_url": "https://example.test/v1", "protocol": "openai", "api_key": "test-key" }`, model `gpt-image-2`, and no reference images.

- [ ] **Step 2: Run the direct-GPT test and verify RED**

  Run:

  ```powershell
  py -m unittest tests.test_gpt_image_output_cap.GptImageOutputCapTests.test_direct_gpt_image_request_explicitly_sets_n_one
  ```

  Expected: FAIL with a missing `n` key; no HTTP request leaves the process because the fake client is installed.

- [ ] **Step 3: Write a failing result-cap test**

  Patch `main.request_api_provider`, `main.generate_ai_image`, `main.save_ai_image_to_output`, `main.save_to_history`, and `main.log_team_generation`. Make `generate_ai_image` return a first image plus this raw payload:

  ```python
  {"data": [
      {"url": "https://example.test/first.png"},
      {"url": "https://example.test/second.png"},
  ]}
  ```

  Call `build_online_image_result(main.OnlineImageRequest(prompt="cat", provider_id="custom-api", model="gpt-image-2", n=1), user=CurrentUser(id="test-user"))` and assert:

  ```python
  self.assertEqual(result["images"], ["/output/first.png"])
  save_image.assert_awaited_once()
  ```

- [ ] **Step 4: Run the result-cap test and verify RED**

  Run:

  ```powershell
  py -m unittest tests.test_gpt_image_output_cap.GptImageOutputCapTests.test_single_generation_persists_only_first_upstream_image
  ```

  Expected: FAIL because current code saves both mock URLs.

### Task 2: Apply the minimal output-cap repair

**Files:**
- Modify: `main.py:12058-12063`
- Modify: `main.py:14748-14755`
- Test: `tests/test_gpt_image_output_cap.py`

**Interfaces:**
- Consumes: tests from Task 1.
- Produces: one explicit upstream requested image and one persisted image for each individual canvas task.

- [ ] **Step 1: Add `n: 1` to the direct GPT Image 2 body**

  Replace the request construction with:

  ```python
  body = {"model": model, "prompt": prompt, "size": size, "n": 1}
  ```

- [ ] **Step 2: Cap extracted results per `generate_one()` call**

  Change the existing extraction block to slice the output before saving files:

  ```python
  try:
      image_items = extract_images(raw_item) if isinstance(raw_item, dict) else [image_data]
  except HTTPException:
      image_items = [image_data]
  image_items = image_items[:1]
  ```

- [ ] **Step 3: Run both focused tests and verify GREEN**

  Run:

  ```powershell
  py -m unittest tests.test_gpt_image_output_cap
  ```

  Expected: two tests pass; neither test has a real Provider dependency.

- [ ] **Step 4: Run regression verification**

  Run:

  ```powershell
  py -m unittest tests.test_smart_image_agent
  py -m unittest tests.test_canvas_log_cleanup
  npm run build:scripts
  git diff --check
  ```

  Expected: all tests and the static build pass; `git diff --check` has no errors.

- [ ] **Step 5: Commit only the repair and its test**

  ```powershell
  git add main.py tests/test_gpt_image_output_cap.py
  git commit -m "fix(canvas): cap gpt image task output"
  ```

### Task 3: Record the safe stop state

**Files:**
- Modify: `docs/superpowers/verification/2026-08-27-smart-image-agent-v3-provider-e2e.md`

**Interfaces:**
- Consumes: focused test and regression outputs from Task 2.
- Produces: a no-secret record of the local repair; it does not authorize more paid tests.

- [ ] **Step 1: Append repair evidence**

  Record that direct GPT Image 2 now sends `n: 1`, simulated two-item upstream responses persist one output, local regression commands pass, and no new Provider call occurred.

- [ ] **Step 2: Commit the verification record**

  ```powershell
  git add docs/superpowers/verification/2026-08-27-smart-image-agent-v3-provider-e2e.md
  git commit -m "docs(agent): record gpt image output cap fix"
  ```

## Exit Conditions

- A one-image GPT Image 2 task sends `n: 1` and persists exactly one result in local tests.
- Existing relevant tests and the static build pass without real Provider access.
- The test Provider remains configured but no new paid image is generated until a separate user decision sets an updated image budget.
