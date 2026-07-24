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
