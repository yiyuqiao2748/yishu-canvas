# Team Assets Tab Design

Date: 2026-07-24

## Scope

Add a separate "team assets" tab to the existing asset manager so team members can upload and browse files stored through the team cloud asset API.

This change does not merge team assets into the existing local asset library. Team asset deletion now checks cloud canvas references before removing records; AI-result capture remains separate follow-up work.

## User Experience

- Add a new tab in `static/asset-manager.html` beside the existing asset tabs.
- The tab shows a team asset list, an upload action, status text, and a detail pane for the selected asset.
- If no active team is known, the tab shows an empty/auth state instead of failing silently.
- Uploading files sends them to the current team's `/api/team-cloud/teams/{team_id}/assets` endpoint and refreshes the list.
- Listed assets can be previewed when they expose a `public_url`.

## State And Data Flow

- `static/js/asset-manager.js` owns the new tab state:
  - current team id
  - team asset list
  - selected team asset id
  - team asset query
  - loading/uploading flags
- The page discovers the current team from existing team-cloud client state when available, with a localStorage fallback that matches the existing team cloud pages.
- API calls use the existing `apiJson` helper and include credentials by default through browser cookies.
- The backend response shapes remain unchanged:
  - list: `{ "assets": [...] }`
  - upload: `{ "asset": {...} }`

## Integration Boundaries

- Keep existing local asset library behavior intact.
- Do not reuse local library category, move, batch delete, or classify flows for team assets.
- Convert team asset records into display-only cards with metadata such as name, kind, mime type, size, storage provider, and created date.
- Keep upload behavior simple: file input to `FormData`, one request per file, then refresh.

## Error Handling

- Missing team id shows a clear empty state.
- 401/403/503 responses surface through the existing status area.
- Oversized uploads rely on the backend `413` response.
- Partial multi-file upload failure reports the failed file and keeps already uploaded assets.

## Testing

- Add focused JS tests for pure helper behavior where practical:
  - resolving the active team id from stored team cloud state
  - normalizing team asset records for display
  - filtering assets by query
- Keep CI checks:
  - `python -m unittest discover -s tests`
  - `node --check static/js/canvas-list.js static/js/canvas.js static/js/smart-canvas.js static/js/team-cloud.js`
- Add `node --check static/js/asset-manager.js` to local verification for this change.
