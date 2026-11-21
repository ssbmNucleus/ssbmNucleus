// Older receipts only enumerate costumes. Fill the remaining successful count
// from its own website post, never from another post or a failed batch item.
export function downloadReceiptItems(result) {
  const refreshed = new Map((result.imported_items || []).map(item => [`${item.character}:${item.id}`, item]))
  const sources = result.downloads ? result.downloads.map(row => row.result).filter(Boolean) : [result]
  return sources.flatMap(source => {
    if (!(source.imported_count > 0)) return []
    const mod = source.website_mods?.[0] || {}
    const costumes = (source.imported_items || []).map(item => ({
      ...item, ...refreshed.get(`${item.character}:${item.id}`), kind: 'costume', fallback_image: mod.image,
    }))
    const stages = (source.imported_stages || []).map(item => ({ ...item, kind: 'stage' }))
    const remaining = source.imported_count - costumes.length - stages.length
    const other = remaining > 0 ? [{
      id: `post-${mod.post_id || 'download'}`, kind: 'mod', name: mod.title || 'Downloaded mod',
      image: mod.image, count: remaining,
      label: mod.tags?.find(tag => ['Stage Skin', 'Custom Stage', 'Effects', 'Assets/Other', 'Patch', 'Gameplay Mod'].includes(tag)) || 'Mod',
    }] : []
    return [...costumes, ...stages, ...other]
  })
}
