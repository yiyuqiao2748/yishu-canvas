# Task 2 Report: Smart Image Agent Model Guard

## Status

Implemented and verified.

## Scope

- Updated only the Smart Image Agent generation guard in `static/js/smart-canvas.js`.
- Added one focused static regression test in `tests/test_smart_image_agent.py`.
- The guard still requires provider `custom-api`.
- The allowlist is exactly:
  - `gpt-image-2`
  - `nano-banana-2`
  - `nano-banana-pro`
  - `gpt-image-2-vip`
- Legacy plan execution, `plan.quality || 'standard'`, and existing request settings are unchanged.
- No Agnes image fallback was introduced.
- Normal Smart Canvas model controls and Classic Canvas were not changed.

## TDD Evidence

1. Added the focused static test before the production guard change.
2. RED: the test failed because `gpt-image-2` and `gpt-image-2-vip` were absent from the existing two-model guard.
3. GREEN: expanded only the guard allowlist; the focused test passed.

## Verification

- Focused test: passed.
- Full `tests.test_smart_image_agent`: `31` tests passed.
- `git diff --check`: passed.

The test run emitted existing dependency deprecation warnings and planner fallback log messages; no test failed because of them.

## Concerns

No Task 2-specific concerns identified. The guard's existing Chinese error text still mentions only Nano Banana models, but changing user-facing copy was outside this task's requested static allowlist-only scope.
