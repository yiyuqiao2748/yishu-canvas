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

  function previewTokenParam(){
    try {
      const token = localStorage.getItem('teamCloudAccessToken') || '';
      return token ? `access_token=${encodeURIComponent(token)}` : '';
    } catch(_err) {
      return '';
    }
  }

  function teamAssetPreviewUrl(proxyUrl, options={}){
    if(!proxyUrl) return '';
    const parts = [];
    if(options.thumbnail) parts.push('thumbnail=1');
    const token = previewTokenParam();
    if(token) parts.push(token);
    return parts.length ? `${proxyUrl}?${parts.join('&')}` : proxyUrl;
  }

  function normalizeTeamAsset(asset){
    const item = asset && typeof asset === 'object' ? asset : {};
    const provider = String(item.storage_provider || '').toLowerCase();
    const id = String(item.id || '');
    const teamId = String(item.team_id || item.teamId || '');
    const proxyUrl = id && teamId ? `/api/team-cloud/teams/${encodeURIComponent(teamId)}/assets/${encodeURIComponent(id)}/content` : '';
    return {
      ...item,
      id,
      name: String(item.name || 'asset'),
      kind: String(item.kind || 'file'),
      mimeType: String(item.mime_type || item.mimeType || ''),
      url: proxyUrl || String(item.public_url || item.url || ''),
      thumbnailUrl: proxyUrl ? `${proxyUrl}?thumbnail=1` : String(item.thumbnail_url || item.thumbnailUrl || ''),
      previewUrl: proxyUrl ? teamAssetPreviewUrl(proxyUrl) : String(item.public_url || item.url || ''),
      thumbnailPreviewUrl: proxyUrl ? teamAssetPreviewUrl(proxyUrl, {thumbnail:true}) : String(item.thumbnail_url || item.thumbnailUrl || ''),
      thumbnailStorageKey: String(item.thumbnail_storage_key || item.thumbnailStorageKey || ''),
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

  const api = {getStoredTeamId, formatTeamAssetSize, normalizeTeamAsset, filterTeamAssets, teamAssetPreviewUrl};
  global.TeamAssets = api;
  if(typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
