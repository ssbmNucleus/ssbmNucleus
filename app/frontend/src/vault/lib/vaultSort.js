/**
 * Vault sort definitions + comparators for skins and stage variants.
 *
 * "Custom" is the stored metadata order (drag-reorder) and is the default —
 * every other sort is a DISPLAY-ONLY reordering; the metadata array is never
 * touched, so switching back to Custom always restores the user's own order.
 *
 * Persisted in localStorage under 'vault_sort' as
 * { skins: {key, dir}, stages: {key, dir} }.
 */
import { SLOT_COLORS } from '../../upload/uploadCatalog'

export const VAULT_SORT_KEY = 'vault_sort'

export const DEFAULT_SORT = { key: 'custom', dir: 'asc' }

export const SKIN_SORTS = [
  { value: 'custom', label: 'Custom', defDir: 'asc' },
  { value: 'az', label: 'A–Z', defDir: 'asc' },
  { value: 'date', label: 'Date', defDir: 'desc' },
  { value: 'color', label: 'Color', defDir: 'asc' },
]

export const STAGE_SORTS = [
  { value: 'custom', label: 'Custom', defDir: 'asc' },
  { value: 'az', label: 'A–Z', defDir: 'asc' },
  { value: 'date', label: 'Date', defDir: 'desc' },
]

export const isCustomSort = (sort) => !sort || sort.key === 'custom'

export function loadVaultSort() {
  try {
    const stored = JSON.parse(localStorage.getItem(VAULT_SORT_KEY) || '{}')
    return {
      skins: { ...DEFAULT_SORT, ...(stored.skins || {}) },
      stages: { ...DEFAULT_SORT, ...(stored.stages || {}) },
    }
  } catch {
    return { skins: { ...DEFAULT_SORT }, stages: { ...DEFAULT_SORT } }
  }
}

export function saveVaultSort(vaultSort) {
  localStorage.setItem(VAULT_SORT_KEY, JSON.stringify(vaultSort))
}

// Vanilla costume slot rank, in SLOT_COLORS key order (Neutral first). Items
// with no recognizable costume_code sort after every real slot.
const COLOR_RANK = Object.fromEntries(Object.keys(SLOT_COLORS).map((k, i) => [k, i]))
const NO_COLOR_RANK = Object.keys(SLOT_COLORS).length

const azLabel = (item) => String(item.color || item.name || item.id || '')

const colorRank = (item) => {
  const m = /^pl\w{2}(\w{2})$/i.exec(String(item.costume_code || ''))
  const rank = m ? COLOR_RANK[m[1].toLowerCase()] : undefined
  return rank === undefined ? NO_COLOR_RANK : rank
}

const compareAz = (a, b) =>
  azLabel(a).localeCompare(azLabel(b), undefined, { numeric: true, sensitivity: 'base' })

/**
 * Comparator for skin/variant objects under {key, dir}. 'custom' returns null
 * (callers keep array order).
 */
export function sortComparator(sort) {
  if (isCustomSort(sort)) return null
  const flip = sort.dir === 'desc' ? -1 : 1
  switch (sort.key) {
    case 'az':
      return (a, b) => flip * compareAz(a, b)
    case 'date':
      // ISO 8601 strings compare lexicographically; missing dates sort oldest.
      return (a, b) => {
        const da = a.date_added || ''
        const db = b.date_added || ''
        if (da !== db) return flip * (da < db ? -1 : 1)
        return compareAz(a, b)
      }
    case 'color':
      return (a, b) => {
        const ra = colorRank(a)
        const rb = colorRank(b)
        if (ra !== rb) return flip * (ra - rb)
        return compareAz(a, b)
      }
    default:
      return null
  }
}
