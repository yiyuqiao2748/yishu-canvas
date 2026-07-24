# Team Assets Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separate team assets tab to the existing asset manager, backed by `/api/team-cloud/teams/{team_id}/assets`.

**Architecture:** Put pure team-asset helper logic in a small browser/Node-compatible file, then wire the existing asset manager monolith to that helper. Keep team assets display-only except for upload and refresh so the local asset library remains untouched.

**Tech Stack:** Plain browser JavaScript, FastAPI team cloud endpoints, Node built-in test runner, existing `unittest` Python suite.

---

### Task 1: Add Team Asset Helper Tests

**Files:**
- Create: `tests/js/team-assets.test.js`
- Create later: `static/js/team-assets.js`

- [ ] **Step 1: Write the failing test**

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  getStoredTeamId,
  normalizeTeamAsset,
  filterTeamAssets,
} = require('../../static/js/team-assets.js');

test('getStoredTeamId reads the remembered team id', () => {
  const storage = new Map([['teamCloudCurrentTeamId', 'team-123']]);
  assert.equal(getStoredTeamId({getItem: key => storage.get(key) || ''}), 'team-123');
});

test('normalizeTeamAsset maps backend records to display fields', () => {
  const item = normalizeTeamAsset({
    id: 'asset-1',
    name: 'hero.png',
    kind: 'image',
    mime_type: 'image/png',
    byte_size: 2048,
    storage_provider: 'r2',
    public_url: 'https://cdn.example/hero.png',
    created_at: '2026-07-24T00:00:00Z',
  });
  assert.equal(item.id, 'asset-1');
  assert.equal(item.name, 'hero.png');
  assert.equal(item.url, 'https://cdn.example/hero.png');
  assert.equal(item.sizeLabel, '2 KB');
  assert.equal(item.providerLabel, 'R2');
});

test('filterTeamAssets matches name, mime type, and provider', () => {
  const assets = [
    normalizeTeamAsset({id: 'a', name: 'hero.png', mime_type: 'image/png', storage_provider: 'r2'}),
    normalizeTeamAsset({id: 'b', name: 'brief.pdf', mime_type: 'application/pdf', storage_provider: 'local'}),
  ];
  assert.deepEqual(filterTeamAssets(assets, 'pdf').map(item => item.id), ['b']);
  assert.deepEqual(filterTeamAssets(assets, 'r2').map(item => item.id), ['a']);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/js/team-assets.test.js`

Expected: FAIL with module not found for `static/js/team-assets.js`.

### Task 2: Implement Pure Team Asset Helpers

**Files:**
- Create: `static/js/team-assets.js`
- Test: `tests/js/team-assets.test.js`

- [ ] **Step 1: Write minimal implementation**

```javascript
(function(global){
  const TEAM_CLOUD_TEAM_KEY = 'teamCloudCurrentTeamId';

  function getStoredTeamId(storage){
    try {
      return String(storage?.getItem?.(TEAM_CLOUD_TEAM_KEY) || '').trim();
    } catch(_err) {
      return '';
    }
  }

  function formatTeamAssetSize(value){
    const size = Number(value || 0);
    if(!Number.isFinite(size) || size <= 0) return '0 B';
    if(size < 1024) return `${size} B`;
    if(size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
    return `${(size / 1024 / 1024).toFixed(size >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
  }

  function normalizeTeamAsset(asset){
    const item = asset && typeof asset === 'object' ? asset : {};
    const provider = String(item.storage_provider || '').toLowerCase();
    return {
      ...item,
      id: String(item.id || ''),
      name: String(item.name || 'asset'),
      kind: String(item.kind || 'file'),
      mimeType: String(item.mime_type || item.mimeType || ''),
      url: String(item.public_url || item.url || ''),
      byteSize: Number(item.byte_size || item.byteSize || 0),
      sizeLabel: formatTeamAssetSize(item.byte_size || item.byteSize || 0),
      providerLabel: provider === 'r2' ? 'R2' : (provider === 'local' ? 'Local' : (provider || 'unknown')),
      createdAt: item.created_at || item.createdAt || '',
    };
  }

  function filterTeamAssets(assets, query){
    const q = String(query || '').trim().toLowerCase();
    const list = Array.isArray(assets) ? assets : [];
    if(!q) return list;
    return list.filter(item => [
      item.name,
      item.kind,
      item.mimeType,
      item.providerLabel,
      item.url,
    ].some(value => String(value || '').toLowerCase().includes(q)));
  }

  const api = {getStoredTeamId, formatTeamAssetSize, normalizeTeamAsset, filterTeamAssets};
  global.TeamAssets = api;
  if(typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
```

- [ ] **Step 2: Run test to verify it passes**

Run: `node --test tests/js/team-assets.test.js`

Expected: PASS.

### Task 3: Wire The Team Assets Tab

**Files:**
- Modify: `static/asset-manager.html`
- Modify: `static/js/asset-manager.js`

- [ ] **Step 1: Add script and tab markup**

Add `<button type="button" data-tab="team-assets">` next to the existing tabs, using the `cloud` lucide icon and label `团队素材`.

Load `/static/js/team-assets.js` before `/static/js/asset-manager.js`.

- [ ] **Step 2: Add asset manager state and rendering**

In `static/js/asset-manager.js`, add state for `teamAssets`, `teamAssetQuery`, `selectedTeamAssetId`, `teamAssetsLoaded`, and `teamAssetsBusy`.

Add:

```javascript
async function refreshTeamAssets(){ /* calls /api/team-cloud/teams/{teamId}/assets */ }
function renderTeamAssetsManager(){ /* three-panel view matching existing manager */ }
async function uploadTeamAssetFiles(files){ /* one FormData POST per file */ }
```

Route `activeTab === 'team-assets'` to `renderTeamAssetsManager()`.

- [ ] **Step 3: Wire events**

Update the delegated click/change/input handlers so:
- team asset refresh button calls `refreshTeamAssets`
- team asset upload button opens the existing hidden file input
- file input uploads to team assets when `activeTab === 'team-assets'`
- team asset search updates `teamAssetQuery`
- clicking a team asset card selects it
- preview/open button opens `public_url`

### Task 4: Verification

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.gitignore`

- [ ] **Step 1: Add Node helper test and syntax checks to CI**

Add:

```yaml
node --test tests/js/team-assets.test.js
node --check static/js/team-assets.js
node --check static/js/asset-manager.js
```

- [ ] **Step 2: Run local verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
node --test tests\js\team-assets.test.js
node --check static\js\team-assets.js
node --check static\js\asset-manager.js
node --check static\js\canvas-list.js
node --check static\js\canvas.js
node --check static\js\smart-canvas.js
node --check static\js\team-cloud.js
```

Expected: all commands pass.

- [ ] **Step 3: Review git diff**

Run: `git status --short` and `git diff --stat`.

Expected: only the planned files changed.
