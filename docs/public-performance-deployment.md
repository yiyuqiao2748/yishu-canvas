# Public performance deployment

## Static build

Run the existing Node toolchain before deploying source:

```powershell
npm ci
npm run build:static
```

Generated production assets are stored in `static/dist/`. Source files remain in
`static/js/` so tests and future edits keep using readable code.

## Origin cache boundaries

- `/` and `/static/*.html`: browser revalidation, Cloudflare edge TTL 5 minutes.
- `/static/dist/*`: browser TTL 1 year, Cloudflare edge TTL 30 days, immutable.
- `/api/*`: no shared cache unless an endpoint explicitly opts in.
- `/api/workbench/summary`: private, no-store.
- `/api/media-preview`: immutable generated previews only.

## Cloudflare cache rules

Create the following Cache Rules for `canvas.yiyuqiaoai.uk`, in this order:

1. Bypass cache when the path starts with `/api/`, `/assets/`, or `/output/`.
2. Cache eligible requests when the path is `/` or ends with `.html`; use the
   origin cache-control header, with a 5-minute edge TTL fallback.
3. Cache eligible requests when the path starts with `/static/dist/`; use a
   30-day edge TTL and honor query strings.

Do not enable a whole-site "Cache Everything" rule. Private API and asset
responses must not enter Cloudflare shared cache.

After deployment, purge only changed HTML and `/static/dist/*` URLs. The current
NAS environment does not contain a Cloudflare Zone API token, so purge remains a
dashboard/API deployment step rather than being embedded in source sync.

## Safe NAS rollout

```powershell
powershell -ExecutionPolicy Bypass -File deploy/sync-nas-source.ps1 `
  -TargetRoot Z:\yishu-canvas\yishu-canvas-fnos
```

The sync helper excludes `.env`, `api-env`, `data`, `assets`, `output`,
`team-assets`, `.venv`, `node_modules`, and local performance reports.

After the container is healthy, prewarm public assets:

```powershell
.\.venv\Scripts\python.exe tools\prewarm_deployment.py `
  --base-url https://canvas.yiyuqiaoai.uk
```

Run the performance report twice and require `CF-Cache-Status: HIT` for the
second eligible HTML/static request before marking production acceptance done.
