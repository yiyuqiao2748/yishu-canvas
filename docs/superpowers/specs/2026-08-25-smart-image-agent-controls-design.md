# Smart Image Agent Controls Design

## Goal

Make the Smart Canvas image agent behave as one continuous creation surface: users choose a verified image model, enter a request in a bottom-fixed composer, review one execution plan, generate, and continue from the result. Classic Canvas remains unchanged.

## Scope

- Smart Canvas only. Do not change Classic Canvas HTML, scripts, styles, or its legacy Agent.
- Keep the existing `SmartImageAgentBridge`, Nano Banana generation path, session persistence, result placement, and image-only action set.
- Do not add video, audio, 3D, RunningHub, Agnes image fallback, or non-functional controls.

## Model Policy

Every selectable model uses `custom-api` and must be recorded in the plan, task, and result metadata.

| Model | Mode | Points per image | Use |
| --- | --- | ---: | --- |
| `gpt-image-2` | Standard | 6 | Lowest-cost general image generation and editing |
| `nano-banana-2` | Standard | 12 | Default Smart Canvas image generation |
| `nano-banana-pro` | Pro | 18 | Higher-quality Nano Banana generation |
| `gpt-image-2-vip` | VIP | 20 | Higher-cost GPT Image generation and editing |

The model picker must offer only these four entries. It must not expose a model when its configured provider cannot serve image generation. A selected model has one explicit unit price; the plan estimate is `unit_points * count`.

## Right Agent Rail

### Header and history

The header provides New session and History. History lists sessions for the current Smart Canvas only, ordered by activity and showing the session title. Switching a session restores its conversation, plans, runs, and results. Archiving a session removes it from the default history list without deleting data.

### Active creation surface

The scrollable middle region shows only the current state:

- A compact current-context strip for selected images and manual references.
- One waiting execution plan at a time.
- Active task progress with queued, preparing, generating, saving, completed, failed, and cancelled states.
- Result cards with focus, continue editing, variants, expand, save to asset library, and download actions.

There is no generic skill recommendation feed, onboarding essay, level system, or duplicate legacy Agent panel.

### Bottom-fixed composer

The composer is visually and structurally pinned to the bottom of the right rail. Its contents remain available when the activity region scrolls:

- Image upload and asset-library reference entry points.
- Image reference chips with explicit primary, reference, and edit-target roles.
- Text request input and `@` mention search.
- Model menu, ratio, output count, and an action to create one execution plan.

Creating a plan never charges points or starts a generation. The confirmed plan alone starts generation.

## Verified Canvas Controls

Add an unobtrusive bottom canvas control strip only for functions already present in Smart Canvas:

- Selection/pan mode indicator and shortcut help.
- Fit all nodes to the viewport.
- Zoom out, reset to 100%, and zoom in.
- Arrange selected nodes.

The controls call existing Smart Canvas viewport and arrange functions. They do not create a second canvas tool system or duplicate image editor functions.

## Data and API Changes

- Replace the binary plan `quality` field internally with an explicit `model` selection while accepting existing `standard` and `pro` values for stored historical plans.
- Add a server-side model policy map containing provider ID, model name, display label, tier, and unit points.
- Reject unknown models and prohibit a client-provided point value.
- Add the VIP model to the Smart Canvas agent allowlist and keep all generation task calls routed through the existing `custom-api` image endpoint.
- Persist selected model in plan records; old plans infer their existing model from `quality`.

## Error Handling

- If the selected model is missing from the current configured image provider, plan creation returns a clear configuration error and no task is created.
- If an old plan uses a legacy quality value, render it using its resolved Nano Banana model and existing point estimate.
- If session history cannot load, the current session remains usable and the composer stays available.

## Verification

- Unit tests cover all four model policies, estimates, rejection of unknown models, and legacy-plan compatibility.
- Static checks prove Classic Canvas does not reference the new rail controls or model-picker code.
- Browser checks confirm the composer stays fixed while conversation, tasks, and results scroll; each control invokes an existing Smart Canvas action.
- Smart Canvas smoke checks create a plan for each model and verify no generation starts until confirmation.
