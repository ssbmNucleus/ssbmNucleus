/**
 * Drop selected keys that no longer refer to a live item.
 *
 * `keep(key)` returns true for keys that should stay selected. Returns the
 * original Set when nothing was dropped so React state setters can bail out
 * without a re-render.
 */
export function pruneSelection(selected, keep) {
  let changed = false
  const next = new Set()
  for (const key of selected) {
    if (keep(key)) next.add(key)
    else changed = true
  }
  return changed ? next : selected
}
