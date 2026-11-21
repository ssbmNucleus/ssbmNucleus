export const SCAN_CATEGORIES = [
  { key: 'skins', targetKey: 'skins', label: 'Character skins' },
  { key: 'das', targetKey: 'dasVariants', label: 'Stage variants' },
  { key: 'characters', targetKey: 'customCharacters', label: 'Custom characters' },
  { key: 'stages', targetKey: 'customStages', label: 'Custom stages' },
]

export function describeScanResults({ characters = {}, customSummary, scanSkins, importResult, extractionFailures = [], scanError, stats }) {
  const skinCount = Object.values(characters).reduce((count, skins) => count + skins.length, 0)
  const categories = SCAN_CATEGORIES.map(category => {
    const summary = customSummary?.[category.key]
    const isSkins = category.key === 'skins'
    return { ...category,
      scanned: isSkins ? scanSkins : !!summary,
      added: isSkins ? (importResult?.imported || 0) : (summary?.imported.length || 0),
      ready: isSkins && !importResult ? skinCount : 0,
      issues: isSkins ? (importResult?.errors?.length || 0) + (scanError ? 1 : 0)
        + (stats?.preview_failed || 0) : (summary?.errors.length || 0),
    }
  })
  const added = categories.reduce((n, c) => n + c.added, 0)
  const ready = categories[0].ready
  const issues = categories.reduce((n, c) => n + c.issues, 0) + extractionFailures.length
  const initialCategory = (importResult ? 'skins' : null) || categories.find(c => c.ready)?.key
    || categories.find(c => c.added)?.key
    || categories.find(c => c.issues)?.key
    || categories.find(c => c.scanned)?.key || 'skins'
  const title = ready ? `${ready} character skin${ready === 1 ? '' : 's'} ready to import`
    : added ? `${added} item${added === 1 ? '' : 's'} added to your vault`
      : issues ? 'Scan needs attention' : 'No new content found'
  return { categories, added, ready, issues, title, initialCategory }
}

export const scanItemName = item => typeof item === 'string' ? item : (item?.name || item?.id || 'Unnamed item')
export const scanFileName = path => String(path || '').split(/[\\/]/).pop()
