/**
 * L alternates in the CSS layout editor's icon list (docs/dev/L_LOAD.md):
 * tapping L on the select screen scrolls a fighter through its alternates.
 *
 * Each fighter row gets a "+ L" picker on the same row; its alternates show as
 * indented rows underneath (reorder, remove). Every change posts the whole
 * groups array (other groups unchanged) through `onSave`; a group left with
 * no alternates is dropped.
 */

// Group names match case-insensitively, as the backend does
const nameKey = (name) => String(name).trim().toLowerCase()

function groupFor(lload, fighterId) {
  const eligible = lload?.eligible || []
  const fighter = eligible.find(f => f.externalId === fighterId)
  if (!fighter || (lload?.altExternalIds || []).includes(fighterId)) return null
  const groups = lload?.groups || []
  const index = groups.findIndex(g => nameKey(g.base) === nameKey(fighter.name))
  return { fighter, groups, index, alts: index >= 0 ? groups[index].alts : [] }
}

function saveAlts(group, newAlts, onSave) {
  const { groups, index, fighter } = group
  const next = index >= 0
    ? groups.map((g, i) => (i === index ? { ...g, alts: newAlts } : g))
    : [...groups, { base: fighter.name, alts: newAlts }]
  onSave(next.filter(g => g.alts.length > 0))
}

// Keep clicks on the controls from selecting or dragging the row
const stop = (e) => e.stopPropagation()

/** The "+ L" picker at the right end of a fighter's row. */
export function LloadAddPicker({ fighterId, lload, busy, onSave }) {
  const group = groupFor(lload, fighterId)
  if (!group) return null

  // Addable: eligible, not this fighter, and not in any group yet
  const taken = new Set(group.groups.flatMap(g => [g.base, ...g.alts]).map(nameKey))
  taken.add(nameKey(group.fighter.name))
  const choices = []
  ;(lload.eligible || []).forEach(f => {
    if (taken.has(nameKey(f.name))) return
    taken.add(nameKey(f.name))
    choices.push(f.name)
  })
  if (choices.length === 0) return null

  return (
    <select
      className="css-lload-add"
      value=""
      disabled={busy}
      draggable={false}
      title="Add an L alternate: tap L on the select screen to switch to it"
      onClick={stop}
      onMouseDown={stop}
      onChange={(e) => { if (e.target.value) saveAlts(group, [...group.alts, e.target.value], onSave) }}
    >
      <option value="">+ L</option>
      {choices.map(name => <option key={name} value={name}>{name}</option>)}
    </select>
  )
}

/** The alternates under a fighter's row, in the order L scrolls through them. */
export function LloadAltRows({ fighterId, lload, busy, onSave, iconUrlFor }) {
  const group = groupFor(lload, fighterId)
  if (!group || group.alts.length === 0) return null
  const { alts } = group

  const move = (i, dir) => {
    const next = [...alts]
    const [moved] = next.splice(i, 1)
    next.splice(i + dir, 0, moved)
    saveAlts(group, next, onSave)
  }

  return alts.map((name, i) => {
    const url = iconUrlFor ? iconUrlFor(name) : null
    return (
      <div key={name} className="css-lload-alt" onClick={stop} onMouseDown={stop}>
        <span className="css-lload-alt-tag">L{i + 1}</span>
        <span className="sss-icon-thumb css-lload-alt-thumb">
          {url && <img src={url} alt="" draggable={false} onError={(e) => { e.target.style.display = 'none' }} />}
        </span>
        <span className="sss-icon-name">{name}</span>
        <span className="sss-reorder-btns css-lload-alt-btns">
          <button onClick={() => move(i, -1)} disabled={busy || i === 0} title="Earlier in the L order">&#9650;</button>
          <button onClick={() => move(i, 1)} disabled={busy || i === alts.length - 1} title="Later in the L order">&#9660;</button>
          <button onClick={() => saveAlts(group, alts.filter((_, j) => j !== i), onSave)}
            disabled={busy} title="Remove this L alternate">&#215;</button>
        </span>
      </div>
    )
  })
}
