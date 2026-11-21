/**
 * Pure portrait grouping for the Portraits ("Manage CSPs") modal.
 *
 * The vault stores a costume's alternates as a FLAT list mixing SD and HD
 * entries paired by `pose_name` (backend: vault/routes/storage_costumes/csp.py manage_csp,
 * poses.py batch-generate, generate-csp apply). This folds skin + that list
 * into one card per portrait so the modal only renders.
 *
 * `active_csp_id` null/undefined means the original is active; otherwise it
 * names the SD (or, legacy, the HD) member of the active alternate group.
 *
 * Card shape: { key, kind: 'original'|'alt', label, url, hasHd, isActive, sdId, hdId }
 * Alt entries in: { id, url, poseName, isHd }
 */
export function groupPortraits(skin, alts) {
  if (!skin) return []
  const activeId = skin.active_csp_id || null
  const out = []
  if (skin.has_csp) {
    out.push({
      key: 'original', kind: 'original',
      label: skin.csp_pose_name || 'Original',
      url: skin.cspUrl, hasHd: !!skin.has_hd_csp,
      isActive: !activeId, sdId: null, hdId: null,
    })
  }
  const list = alts || []
  const seen = new Set()
  for (const alt of list) {
    // Pose-less uploads only group with themselves (null must not cross-match).
    const groupKey = alt.poseName || alt.id
    if (seen.has(groupKey)) continue
    seen.add(groupKey)
    const sd = alt.poseName
      ? list.find((a) => a.poseName === alt.poseName && !a.isHd)
      : (alt.isHd ? null : alt)
    const hd = alt.poseName
      ? list.find((a) => a.poseName === alt.poseName && a.isHd)
      : (alt.isHd ? alt : null)
    const shown = sd || hd
    if (!shown) continue
    out.push({
      key: `alt:${groupKey}`, kind: 'alt',
      label: alt.poseName || 'Custom',
      url: shown.url, hasHd: !!hd,
      isActive: !!activeId && (activeId === sd?.id || activeId === hd?.id),
      sdId: sd?.id || null, hdId: hd?.id || null,
    })
  }
  return out
}
