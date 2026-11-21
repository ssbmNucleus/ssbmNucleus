import { useEffect, useMemo, useState } from 'react'
import { backendMediaUrl } from '../../shared/config/config'
import { api, ApiError } from '../../shared/transport/api'
import { playSound, playHoverSound } from '../../shared/audio/sounds'

/* Pick two fighters and build them into a single CSS slot ("Any Climbers").

   No project needed: the vault is project-independent, so candidates fall back
   to the bundled vanilla roster and only use the open project's when there is
   one. Fighters are chosen by NAME, not internal id — ids shift as m-ex
   fighters are added, and a stored pair has to survive being installed into a
   project it was never created against.

   Fighters are picked from a grid of their CSS icons rather than a list of
   names: this is a character select, and you recognise Melee's cast by face far
   faster than by reading. The per-side blocked reasons are engine constraints
   (Ice Climbers can't lead, Zelda/Sheik can't follow), so they're shown as a
   dimmed tile with a tooltip rather than silently filtered — a character simply
   being absent is more confusing than one you can see is unavailable. */

function fighterIconUrl(name) {
  return backendMediaUrl('/api/mex/climbers/fighter-icon?name=' + encodeURIComponent(name))
}

function FighterGrid({ label, fighters, side, selected, onSelect }) {
  const canKey = side === 'leader' ? 'canLead' : 'canPartner'
  const reasonKey = side === 'leader' ? 'leaderBlockedReason' : 'partnerBlockedReason'

  return (
    <div className="climbers-column">
      <div className="climbers-column-head">
        <h4 className="climbers-column-title">{label}</h4>
        <span className="climbers-column-pick">{selected || 'none'}</span>
      </div>
      <div className="climbers-grid">
        {fighters.map((f) => {
          const allowed = f[canKey]
          const isSelected = f.name === selected
          return (
            <button
              key={f.name}
              type="button"
              className={`climbers-tile${isSelected ? ' selected' : ''}`}
              disabled={!allowed}
              title={allowed ? `${f.name} — ${f.costumeCount} colours` : f[reasonKey]}
              onMouseEnter={allowed ? playHoverSound : undefined}
              onClick={() => { playSound('boop'); onSelect(f.name) }}
            >
              <img src={fighterIconUrl(f.name)} alt={f.name} draggable={false} />
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default function NewClimbersModal({ onClose, onCreated }) {
  const [fighters, setFighters] = useState([])
  const [loadError, setLoadError] = useState(null)
  const [isLoading, setIsLoading] = useState(true)

  const [leaderName, setLeaderName] = useState(null)
  const [partnerName, setPartnerName] = useState(null)
  const [color, setColor] = useState(0)
  const [name, setName] = useState('')
  const [nameEdited, setNameEdited] = useState(false)

  const [creating, setCreating] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await api.get('/climbers/candidates')
        if (!cancelled) setFighters(data.candidates || [])
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : String(err))
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  const leader = fighters.find((f) => f.name === leaderName) || null
  const partner = fighters.find((f) => f.name === partnerName) || null
  // Same fighter on both sides is allowed -- see the backend note.
  const ready = Boolean(leader && partner)
  // The portrait fills in from the FIRST pick rather than staying blank until
  // both are chosen; `composite` renders a lone fighter on its own.
  const anyPicked = Boolean(leader || partner)

  // One slot per LEADER colour. The engine forces the partner's costume id to
  // equal the slot index and clamps it to 0 past the end of the partner's list,
  // so a shorter partner repeats its default instead of costing the leader
  // colours -- Mr. Game & Watch ships exactly one costume.
  const colorCount = leader ? leader.costumeCount
    : partner ? partner.costumeCount
    : 0
  const partnerRepeats = ready && partner.costumeCount < colorCount

  useEffect(() => {
    if (color >= colorCount) setColor(0)
  }, [colorCount, color])

  const defaultName = !ready ? ''
    : leader.name === partner.name ? `Double ${leader.name}`
    : `${leader.name} & ${partner.name}`
  useEffect(() => {
    if (!nameEdited) setName(defaultName)
  }, [defaultName, nameEdited])

  const previewQuery = (i, kind) =>
    '/api/mex/climbers/preview?color=' + i
    + (leader ? '&leader=' + encodeURIComponent(leader.name) : '')
    + (partner ? '&partner=' + encodeURIComponent(partner.name) : '')
    + (kind ? '&kind=' + kind : '')

  const previewUrl = useMemo(
    () => (anyPicked ? backendMediaUrl(previewQuery(color)) : null),
    [anyPicked, leader, partner, color])

  const stockUrl = (i) => backendMediaUrl(previewQuery(i, 'stock'))

  const handleCreate = async () => {
    if (!ready || creating) return
    setCreating(true)
    setError(null)
    try {
      const data = await api.post('/climbers/create', {
        leader: leader.name,
        partner: partner.name,
        name: name.trim() || defaultName,
      })
      playSound('start')
      onCreated?.(data)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={() => { playSound('back'); onClose() }}>
      <div className="modal-content climbers-modal" onClick={(e) => e.stopPropagation()}>
        <div className="climbers-header">
          <h3>New Climbers</h3>
          <button className="climbers-close" onClick={() => { playSound('back'); onClose() }}>&times;</button>
        </div>

        <p className="climbers-blurb">
          Two fighters on one CSS slot, like the Ice Climbers — you control the
          leader and the partner copies your inputs. Press <strong>down on the
          D-pad</strong> in a match to swap which one you're controlling.
        </p>

        {isLoading ? (
          <p className="climbers-status">Loading fighters…</p>
        ) : loadError ? (
          <p className="climbers-status climbers-error">{loadError}</p>
        ) : (
          <>
            <div className="climbers-picker">
              <FighterGrid
                label="Leader" side="leader" fighters={fighters}
                selected={leaderName} onSelect={setLeaderName}
              />

              <div className="climbers-preview">
                {previewUrl ? (
                  <img src={previewUrl} alt="Pair portrait" className="climbers-preview-img" />
                ) : (
                  <div className="climbers-preview-empty">
                    Pick a leader<br />and a partner
                  </div>
                )}

                {anyPicked && colorCount > 1 && (
                  <div className="climbers-colors">
                    {Array.from({ length: colorCount }).map((_, i) => (
                      <button
                        key={i}
                        type="button"
                        className={`climbers-color${i === color ? ' selected' : ''}`}
                        title={`Colour ${i + 1}`}
                        onMouseEnter={playHoverSound}
                        onClick={() => { playSound('boop'); setColor(i) }}
                      >
                        <img src={stockUrl(i)} alt={`Colour ${i + 1}`} draggable={false} />
                      </button>
                    ))}
                  </div>
                )}

                {anyPicked && (
                  <p className="climbers-colors-note">
                    {colorCount} colour{colorCount !== 1 ? 's' : ''}
                    {ready && (
                      <>
                        {' · '}
                        <span title={`Each slot puts one of ${leader.name}'s colours with the closest colour ${partner.name} has, instead of pairing costume 1 with costume 1`}>
                          matched by colour
                        </span>
                      </>
                    )}
                    {partnerRepeats && (
                      <>
                        {' · '}
                        <span title={`${partner.name} has only ${partner.costumeCount} colour${partner.costumeCount !== 1 ? 's' : ''}, so the rest reuse the default`}>
                          {partner.name} repeats
                        </span>
                      </>
                    )}
                  </p>
                )}
              </div>

              <FighterGrid
                label="Partner" side="partner" fighters={fighters}
                selected={partnerName} onSelect={setPartnerName}
              />
            </div>

            <div className="climbers-footer">
              <div className="climbers-name-row">
                <label htmlFor="climbers-name">Name</label>
                <input
                  id="climbers-name"
                  type="text"
                  value={name}
                  placeholder={defaultName || 'Pick two fighters'}
                  disabled={!ready}
                  onChange={(e) => { setNameEdited(true); setName(e.target.value) }}
                />
              </div>

              <div className="climbers-actions">
                <button
                  className="climbers-btn primary"
                  disabled={!ready || creating}
                  onMouseEnter={ready ? playHoverSound : undefined}
                  onClick={handleCreate}
                >
                  {creating ? 'Building…' : 'Create Pair'}
                </button>
                <button
                  className="climbers-btn"
                  disabled={creating}
                  onClick={() => { playSound('back'); onClose() }}
                >
                  Cancel
                </button>
              </div>
            </div>

            {error && <p className="climbers-status climbers-error">{error}</p>}
          </>
        )}
      </div>
    </div>
  )
}
