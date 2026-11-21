/**
 * BulkStageCaptureModal
 *
 * Pick stage variants from across the whole vault and render their previews in
 * bulk. The backend draws each one OFFLINE with the HSD stage renderer, about a
 * second apiece — no test ISO build and no Dolphin boot, so no vanilla ISO or
 * Slippi path is needed. Flow: select -> rendering (shots appear as they land)
 * -> review (keep/discard each) -> save the kept shots as the variants' previews.
 *
 * Only the six DAS stages have a calibrated camera; every other vault stage
 * reports `canRender: false` and is shown dimmed until one exists.
 *
 * Styling lives in BulkCapture.css (.bulk-capture-*), responsive down to
 * phone-ish widths (full-bleed modal + tighter tiles under 760px).
 */
import { useEffect, useMemo } from 'react'
import { API_URL } from '../../shared/config/config'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { useBulkStageCapture } from '../hooks/useBulkStageCapture'
import '../BulkCapture.css'

const STAGE_ORDER = ['Battlefield', 'Final Destination', 'Dreamland', "Yoshi's Story",
  'Pokemon Stadium', 'Fountain of Dreams']
const imgBase = API_URL.replace('/api/mex', '')

export default function BulkStageCaptureModal({ show, onClose, onSaved }) {
  const bulk = useBulkStageCapture({ onSaved })
  const {
    phase, variants, loading, error, selected, toggle, setMany, clearSelection, keyOf,
    progress, results, keep, toggleKeep, saving, stopping,
    loadVariants, startRender, cancelRender, saveKept, reset,
  } = bulk

  useEffect(() => {
    if (show) { reset(); loadVariants() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show])

  // Group variants by stage for display.
  const grouped = useMemo(() => {
    const g = {}
    for (const v of variants) (g[v.stageName] = g[v.stageName] || []).push(v)
    const names = Object.keys(g).sort(
      (a, b) => (STAGE_ORDER.indexOf(a) + 99) - (STAGE_ORDER.indexOf(b) + 99))
    return names.map((name) => [name, g[name]])
  }, [variants])

  if (!show) return null

  const selectedCount = selected.size
  // Stages without a calibrated camera can't be rendered yet — never selectable.
  const renderable = variants.filter((v) => v.canRender !== false)
  const missing = renderable.filter((v) => !v.hasScreenshot)
  const okResults = results.filter((r) => r.ok)
  const keptCount = okResults.filter((r) => keep.has(keyOf(r))).length
  const failed = results.filter((r) => !r.ok)
  // Closing mid-render stops the batch too, or the next open would meet a
  // "already running" refusal from a render nobody is watching.
  const close = () => {
    playSound('back')
    if (phase === 'rendering') cancelRender()
    reset()
    onClose()
  }

  return (
    <div className="bulk-capture-overlay" onClick={close}>
      <div className="bulk-capture-modal" onClick={(e) => e.stopPropagation()}>

        {/* Header */}
        <div className="bulk-capture-header">
          <h2>
            Bulk Stage Screenshots
            {phase === 'review' && ' — Review'}
          </h2>
          <button className="bulk-capture-close" onClick={close} title="Close">✕</button>
        </div>

        {error && <div className="bulk-capture-error">{error}</div>}

        {/* ---- SELECT ---- */}
        {phase === 'select' && (
          <>
            <div className="bulk-capture-toolbar">
              <button className="mode-btn" onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); setMany(missing, true) }}>
                Select all missing ({missing.length})
              </button>
              <button className="mode-btn" onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); setMany(renderable, true) }}>
                Select all ({renderable.length})
              </button>
              <button className="mode-btn" onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); clearSelection() }}>Clear</button>
              <span className="bulk-capture-count">{selectedCount} selected</span>
            </div>

            <div className="bulk-capture-body">
              {loading ? <p className="bulk-capture-muted">Loading variants…</p>
                : grouped.length === 0 ? <p className="bulk-capture-muted">No stage variants in your vault.</p>
                : grouped.map(([stageName, vs]) => {
                  const stageRenderable = vs.filter((v) => v.canRender !== false)
                  const allOn = stageRenderable.length > 0
                    && stageRenderable.every((v) => selected.has(keyOf(v)))
                  return (
                    <div key={stageName} className="bulk-capture-stage">
                      <div className="bulk-capture-stage-head">
                        <strong>{stageName}</strong>
                        <span className="bulk-capture-muted">({vs.length})</span>
                        {stageRenderable.length > 0 ? (
                          <button className="mode-btn"
                            onClick={() => { playSound('boop'); setMany(stageRenderable, !allOn) }}>
                            {allOn ? 'None' : 'All'}
                          </button>
                        ) : (
                          <span className="bulk-capture-muted">no camera calibrated yet</span>
                        )}
                      </div>
                      <div className="bulk-capture-grid">
                        {vs.map((v) => {
                          const canRender = v.canRender !== false
                          const sel = selected.has(keyOf(v))
                          return (
                            <div key={keyOf(v)}
                              onClick={() => { if (canRender) { playSound('boop'); toggle(v) } }}
                              onMouseEnter={canRender ? playHoverSound : undefined}
                              title={canRender ? undefined : 'The offline renderer has no camera for this stage yet'}
                              className={`bulk-capture-card${sel ? ' selected' : ''}${canRender ? '' : ' failed'}`}>
                              <div className="bulk-capture-thumb">
                                {v.hasScreenshot ? (
                                  <img src={`${imgBase}${v.screenshotUrl}`} alt={v.name} loading="lazy" />
                                ) : (
                                  <span className="noshot">no shot</span>
                                )}
                              </div>
                              <div className="bulk-capture-card-label">
                                <span>{canRender ? (sel ? '☑ ' : '☐ ') : ''}{v.name}</span>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )
                })}
            </div>

            <div className="bulk-capture-footer">
              <button className="mode-btn" onClick={close}>Cancel</button>
              <button className="mode-btn mode-btn-primary" disabled={selectedCount === 0}
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); startRender() }}
                style={{ opacity: selectedCount === 0 ? 0.5 : 1 }}>
                Render {selectedCount || ''} selected
              </button>
            </div>
          </>
        )}

        {/* ---- RENDERING (shots stream in as each stage finishes) ---- */}
        {phase === 'rendering' && (
          <>
            <div className="bulk-capture-progress-wrap bulk-capture-progress-wrap--center">
              <p style={{ marginBottom: '1rem' }}>{progress?.message || 'Rendering…'}</p>
              <div className="bulk-capture-progress-bar">
                <div className="bulk-capture-progress-fill"
                  style={{ width: `${progress ? (progress.done / Math.max(1, progress.total)) * 100 : 0}%` }} />
              </div>
              <p className="bulk-capture-progress-pct">{progress ? `${progress.done} / ${progress.total}` : ''}</p>
            </div>
            {results.length > 0 && (
              <div className="bulk-capture-review-grid">
                {results.map((r) => (
                  <div key={keyOf(r)} className={`bulk-capture-card${r.ok ? '' : ' failed'}`}>
                    <div className="bulk-capture-thumb">
                      {r.ok && r.dataUri
                        ? <img src={r.dataUri} alt={r.name} />
                        : <span className="failreason">{r.error || 'failed'}</span>}
                    </div>
                    <div className="bulk-capture-card-label"><span>{r.name}</span></div>
                  </div>
                ))}
              </div>
            )}
            <div className="bulk-capture-footer">
              <button className="mode-btn" disabled={stopping}
                onClick={() => { playSound('back'); cancelRender() }}>
                {stopping ? 'Stopping…' : 'Stop'}
              </button>
            </div>
          </>
        )}

        {/* ---- REVIEW ---- */}
        {phase === 'review' && (
          <>
            <div className="bulk-capture-review-note">{keptCount} / {okResults.length} kept</div>
            {failed.length > 0 && (
              <div className="bulk-capture-diagnostics">
                <strong>{failed.length} failed</strong>
                <ul>
                  {failed.map((r) => (
                    <li key={keyOf(r)}>
                      <span>{r.name || r.variantId}</span>
                      <em>{r.error || 'render failed'}</em>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="bulk-capture-review-grid">
              {results.map((r) => (
                <div key={keyOf(r)}
                  className={`bulk-capture-card${r.ok && keep.has(keyOf(r)) ? ' selected' : ''}${r.ok ? '' : ' failed'}`}>
                  <div className="bulk-capture-thumb"
                    style={{ cursor: r.ok ? 'pointer' : 'default' }}
                    onClick={() => r.ok && toggleKeep(r)}>
                    {r.ok && r.dataUri
                      ? <img src={r.dataUri} alt={r.name} />
                      : <span className="failreason">{r.error || 'failed'}</span>}
                  </div>
                  <div className="bulk-capture-card-label">
                    {r.ok && (
                      <input type="checkbox" checked={keep.has(keyOf(r))}
                        onChange={() => toggleKeep(r)} />
                    )}
                    <span>{r.name}</span>
                  </div>
                </div>
              ))}
            </div>
            <div className="bulk-capture-footer">
              <button className="mode-btn" onClick={() => { playSound('boop'); reset() }} disabled={saving}>
                Discard all
              </button>
              <button className="mode-btn mode-btn-primary" disabled={saving || keptCount === 0}
                onMouseEnter={playHoverSound}
                onClick={async () => { const n = await saveKept(); if (n) close() }}
                style={{ opacity: saving || keptCount === 0 ? 0.5 : 1 }}>
                {saving ? 'Saving…' : `Save ${keptCount || ''}`}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
