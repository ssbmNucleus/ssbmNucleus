// Old overlapping imports can leave multiple metadata rows for one ZIP.
// React keys must still be unique or reorder/delete can leave ghost cards.
// Keep the original arrayIndex: drag/reorder addresses the raw metadata list.
export function uniqueCostumeDisplayItems(items) {
  const seen = new Set()
  return items.filter(item => {
    const id = item.type === 'folder' ? item.folder.id : item.skin.id
    if (seen.has(id)) return false
    seen.add(id)
    return true
  })
}
