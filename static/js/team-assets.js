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
