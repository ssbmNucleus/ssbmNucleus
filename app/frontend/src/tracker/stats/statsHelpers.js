import { BACKEND_URL } from '../../shared/config/config'

// API base and number/date formatting shared by the Stats page and its widgets.
export const API = `${BACKEND_URL}/api/nucleome`

export const pct = (v) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)
export const num = (v) => (v == null ? '—' : v.toLocaleString())

export function shortDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function playtimeLabel(seconds) {
  if (!seconds) return '—'
  const h = seconds / 3600
  return h >= 100 ? `${Math.round(h)} h` : `${h.toFixed(1)} h`
}
