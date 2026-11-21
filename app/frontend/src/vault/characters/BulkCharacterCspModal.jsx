/**
 * BulkCharacterCspModal
 *
 * Vault-wide bulk portrait retake: pick costumes from across every character,
 * re-render each with its active pose (through the persistent CSP render pool),
 * review the before/after grid, and apply the ones you keep (SD + HD are both
 * saved). The character analog of BulkStageCaptureModal -- opened from the same
 * spot on the characters home grid and grouped by character the way the stage
 * modal groups by stage; reuses the `.bulk-capture-*` styling (BulkCapture.css).
 * Flow: select -> retaking -> review (keep/discard each) -> apply.
 */
import { useEffect, useMemo } from 'react'
import { API_URL } from '../../shared/config/config'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { useBulkCharacterCsp } from '../hooks/useBulkCharacterCsp'
import '../BulkCapture.css'

const imgBase = API_URL.replace('/api/mex', '')

// Current portrait URL for a costume (mirrors SkinCard.getCspUrl): the active
// custom-pose alternate if one is selected, else the default CSP.
function currentCspUrl(character, skin) {
  if (skin.active_csp_id && skin.alternate_csps) {
    const activeAlt = skin.alternate_csps.find((a) => a.id === skin.active_csp_id)
    if (activeAlt) return `${imgBase}/storage/${character}/${activeAlt.filename}`
  }
  return `${imgBase}/storage/${character}/${skin.csp_filename || `${skin.id}_csp.png`}`
}

export default function BulkCharacterCspModal({ show, characters, onApplied, onClose }) {
  const bulk = useBulkCharacterCsp({ onApplied })
  const {
    phase, selected, toggle, setMany, clearSelection, keyOf,
    progress, results, keep, toggleKeep, applying, error,
    startRetake, applyKept, reset,
  } = bulk

  useEffect(() => {
    if (show) reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show])

  // Every real costume in the vault as { character, skinId, skin }, grouped by
  // character in the same alphabetical order as the characters grid; characters
  // with no costumes are skipped.
  const grouped = useMemo(() => {
    const out = []
    for (const name of Object.keys(characters || {}).sort()) {
      const skins = (characters[name]?.skins || [])
        .filter((s) => s.type !== 'folder' && s.visible !== false)
        .map((s) => ({ character: name, skinId: s.id, skin: s }))
      if (skins.length) out.push([name, skins])
    }
    return out
  }, [characters])
  const entries = useMemo(() => grouped.flatMap(([, items]) => items), [grouped])
  const byKey = useMemo(() => {
    const m = {}
    for (const e of entries) m[keyOf(e)] = e
    return m
  }, [entries, keyOf])
  const nameOf = (r) => {
    const s = byKey[keyOf(r)]?.skin
    return s?.name || s?.costume_code || r.skinId
  }

  if (!show) return null

  const selectedCount = selected.size
  const missingCsp = entries.filter((e) => !e.skin.has_csp)
  const missingHd = entries.filter((e) => e.skin.has_csp && !e.skin.has_hd_csp)
  const okResults = results.filter((r) => r.ok)
  const keptCount = okResults.filter((r) => keep.has(keyOf(r))).length
  const failed = results.filter((r) => !r.ok)
  // Review results grouped by character, in the same order as the select view.
  const reviewGroups = grouped
    .map(([name]) => [name, okResults.filter((r) => r.character === name)])
    .filter(([, rs]) => rs.length)
  const close = () => { playSound('back'); reset(); onClose() }

  return (
    <div className="bulk-capture-overlay" onClick={close}>
      <div className="bulk-capture-modal bulk-capture-modal--csp" onClick={(e) => e.stopPropagation()}>

        {/* Header */}
        <div className="bulk-capture-header">
          <h2>Bulk Retake CSPs{phase === 'review' && ' — Review'}</h2>
          <button className="bulk-capture-close" onClick={close} title="Close">✕</button>
        </div>

        {error && <div className="bulk-capture-error">{error}</div>}

        {/* ---- SELECT ---- */}
        {phase === 'select' && (
          <>
            <div className="bulk-capture-toolbar">
              <button className="mode-btn" onMouseEnter={playHoverSound}
                title="Costumes that have no portrait yet"
                onClick={() => { playSound('boop'); setMany(missingCsp, true) }}>
                Select all missing CSP ({missingCsp.length})
              </button>
              <button className="mode-btn" onMouseEnter={playHoverSound}
                title="Costumes with a portrait but no HD (4x) portrait — retaking saves both"
                onClick={() => { playSound('boop'); setMany(missingHd, true) }}>
                Select all missing HD ({missingHd.length})
              </button>
              <button className="mode-btn" onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); setMany(entries, true) }}>
                Select all ({entries.length})
              </button>
              <button className="mode-btn" onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); clearSelection() }}>Clear</button>
              <span className="bulk-capture-count">{selectedCount} selected</span>
            </div>

            <div className="bulk-capture-body">
              {grouped.length === 0
                ? <p className="bulk-capture-muted">No costumes in your vault.</p>
                : grouped.map(([name, items]) => (
                  <div key={name} className="bulk-capture-stage">
                    <div className="bulk-capture-stage-head">
                      <strong>{name}</strong>
                      <span className="bulk-capture-muted">({items.length})</span>
                      <button className="mode-btn"
                        onClick={() => { playSound('boop'); setMany(items, !items.every((e) => selected.has(keyOf(e)))) }}>
                        {items.every((e) => selected.has(keyOf(e))) ? 'None' : 'All'}
                      </button>
                    </div>
                    <div className="bulk-capture-grid">
                      {items.map((e) => {
                        const sel = selected.has(keyOf(e))
                        const s = e.skin
                        return (
                          <div key={keyOf(e)} onClick={() => { playSound('boop'); toggle(e) }}
                            onMouseEnter={playHoverSound}
                            className={`bulk-capture-card${sel ? ' selected' : ''}`}>
                            <div className="bulk-capture-thumb">
                              {s.has_csp
                                ? <img src={currentCspUrl(e.character, s)} alt={s.name} loading="lazy" />
                                : <span className="noshot">no CSP</span>}
                            </div>
                            <div className="bulk-capture-card-label">
                              <span>{sel ? '☑ ' : '☐ '}{s.name}</span>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                ))}
            </div>

            <div className="bulk-capture-footer">
              <button className="mode-btn" onClick={close}>Cancel</button>
              <button className="mode-btn mode-btn-primary" disabled={selectedCount === 0}
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); startRetake(entries.filter((e) => selected.has(keyOf(e)))) }}
                style={{ opacity: selectedCount === 0 ? 0.5 : 1 }}>
                Retake {selectedCount || ''} selected
              </button>
            </div>
          </>
        )}

        {/* ---- RETAKING ---- */}
        {phase === 'retaking' && (
          <div className="bulk-capture-progress-wrap bulk-capture-progress-wrap--center">
            <p style={{ marginBottom: '1rem' }}>{progress?.message || 'Retaking…'}</p>
            <div className="bulk-capture-progress-bar">
              <div className="bulk-capture-progress-fill"
                style={{ width: `${progress ? (progress.done / Math.max(1, progress.total)) * 100 : 0}%` }} />
            </div>
            <p className="bulk-capture-progress-pct">{progress ? `${progress.done} / ${progress.total}` : ''}</p>
          </div>
        )}

        {/* ---- REVIEW (before -> after, grouped by character) ---- */}
        {phase === 'review' && (
          <>
            <div className="bulk-capture-review-note">{keptCount} / {okResults.length} kept</div>
            {failed.length > 0 && (
              <div className="bulk-capture-diagnostics">
                <strong>{failed.length} failed</strong>
                <ul>
                  {failed.map((r) => (
                    <li key={keyOf(r)}>
                      <span>{r.character} · {nameOf(r)}</span>
                      <em>{r.error || 'render failed'}</em>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="bulk-capture-body">
            {reviewGroups.map(([name, rs]) => (
              <div key={name} className="bulk-capture-stage">
                <div className="bulk-capture-stage-head">
                  <strong>{name}</strong>
                  <span className="bulk-capture-muted">({rs.length})</span>
                </div>
                <div className="bulk-capture-review-grid">
                  {rs.map((r) => {
                    const kept = keep.has(keyOf(r))
                    const skin = byKey[keyOf(r)]?.skin
                    return (
                      <div key={keyOf(r)}
                        className={`bulk-capture-card${kept ? ' selected' : ''}`}>
                        <div className="bulk-capture-thumb bulk-capture-beforeafter"
                          style={{ cursor: 'pointer' }}
                          onClick={() => toggleKeep(r)}>
                          {skin && skin.has_csp
                            ? <img src={currentCspUrl(r.character, skin)} alt="before" loading="lazy" />
                            : <span className="noshot">—</span>}
                          <span className="bulk-capture-arrow">→</span>
                          <img src={r.dataUri} alt="after" />
                        </div>
                        <div className="bulk-capture-card-label">
                          <input type="checkbox" checked={kept} onChange={() => toggleKeep(r)} />
                          <span>{nameOf(r)}{r.poseName && r.poseName !== 'Default' ? ` (${r.poseName})` : ''}</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
            </div>
            <div className="bulk-capture-footer">
              <button className="mode-btn" onClick={() => { playSound('boop'); reset() }} disabled={applying}>
                Discard all
              </button>
              <button className="mode-btn mode-btn-primary" disabled={applying || keptCount === 0}
                onMouseEnter={playHoverSound}
                onClick={async () => { try { await applyKept() } finally { close() } }}
                style={{ opacity: applying || keptCount === 0 ? 0.5 : 1 }}>
                {applying ? 'Applying…' : `Apply ${keptCount || ''}`}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
