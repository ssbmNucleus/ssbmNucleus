/**
 * AnimeleeDetectModal
 *
 * Scans a character's costumes for the Animelee outline and surfaces the
 * matches, grouped by body geometry so colour variants of the same skin
 * cluster together. Vanilla geometry is excluded server-side. The user picks
 * which models to fold and we move every not-yet-foldered variant into an
 * Animelee folder at once.
 */

import { useState, useEffect, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { getAppContentPortalTarget } from '../../shared/ui/appContentPortal'
import { CloseIcon } from '../../shared/ui/Icons'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { API_URL } from '../../shared/config/config.js'
import { api } from '../../shared/transport/api'

export default function AnimeleeDetectModal({ character, displayName, onClose, onApplied }) {
  const staticBase = API_URL.replace('/api/mex', '')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [data, setData] = useState(null)          // { groups, totalNew, animeFolders }
  const [checked, setChecked] = useState({})        // { geomHash: bool }
  const [applying, setApplying] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError(null)
    api.post('/storage/animelee/detect', { character })
      .then((d) => {
        if (cancelled) return
        setData(d)
        // default-check every group that has at least one not-yet-foldered variant
        const init = {}
        for (const g of d.groups) if (g.unfolderedCount > 0) init[g.geomHash] = true
        setChecked(init)
        setLoading(false)
      })
      .catch((e) => { if (!cancelled) { setError(e.message || 'Detection failed'); setLoading(false) } })
    return () => { cancelled = true }
  }, [character, API_URL])

  const cspUrl = (id) => `${staticBase}/storage/${character}/${id}_csp.png`

  // skin ids we will actually move = not-yet-foldered variants in checked groups
  const selectedSkinIds = useMemo(() => {
    if (!data) return []
    const ids = []
    for (const g of data.groups) {
      if (!checked[g.geomHash]) continue
      for (const s of g.skins) if (!s.alreadyFoldered) ids.push(s.id)
    }
    return ids
  }, [data, checked])

  const newGroups = data ? data.groups.filter((g) => g.unfolderedCount > 0) : []

  const toggleAll = (val) => {
    const next = {}
    for (const g of newGroups) next[g.geomHash] = val
    setChecked(next)
  }

  const apply = async () => {
    if (!selectedSkinIds.length) return
    setApplying(true)
    try {
      const existing = (data.animeFolders && data.animeFolders[0]) || null
      await api.post('/storage/animelee/apply', {
        character,
        skinIds: selectedSkinIds,
        folderId: existing ? existing.id : null,
        folderName: 'Animelee',
      })
      playSound('newSkin')
      if (onApplied) await onApplied()
      onClose()
    } catch (e) {
      setError(e.message || 'Move failed'); setApplying(false)
    }
  }

  const modal = (
    <div className="al-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="al-modal">
        <div className="al-header">
          <div className="al-title">
            <span className="al-title-label">Find Animelee</span>
            <span className="al-title-char">{displayName || character}</span>
          </div>
          <button className="al-close-btn" onMouseEnter={playHoverSound} onClick={() => { playSound('back'); onClose() }}>
            <CloseIcon />
          </button>
        </div>

        <div className="al-body">
          {loading && <div className="al-empty">Scanning for Animelee…</div>}
          {error && <div className="al-empty al-error">{error}</div>}

          {!loading && !error && data && (
            newGroups.length === 0 ? (
              <div className="al-empty">
                No new Animelee skins found.
                {data.groups.length > 0 && ' Everything detected is already in a folder.'}
              </div>
            ) : (
              <>
                <div className="al-hint">
                  <span>
                    Found <b>{data.totalNew}</b> skin{data.totalNew === 1 ? '' : 's'} across{' '}
                    <b>{newGroups.length}</b> model{newGroups.length === 1 ? '' : 's'} not yet in a folder.
                  </span>
                  <span className="al-hint-actions">
                    <button className="al-link-btn" onMouseEnter={playHoverSound} onClick={() => toggleAll(true)}>Select all</button>
                    <button className="al-link-btn" onMouseEnter={playHoverSound} onClick={() => toggleAll(false)}>None</button>
                  </span>
                </div>

                <div className="al-list">
                  {newGroups.map((g) => {
                    const on = !!checked[g.geomHash]
                    return (
                      <label key={g.geomHash} className={`al-group${on ? '' : ' al-group--off'}`}>
                        <input
                          type="checkbox"
                          className="al-check"
                          checked={on}
                          onChange={(e) => setChecked((p) => ({ ...p, [g.geomHash]: e.target.checked }))}
                        />
                        <div className="al-thumbs">
                          {g.skins.slice(0, 8).map((s) => (
                            <img
                              key={s.id}
                              src={cspUrl(s.id)}
                              alt={s.name}
                              title={s.name + (s.alreadyFoldered ? ' (already in a folder)' : '')}
                              className={`al-thumb${s.alreadyFoldered ? ' al-thumb--foldered' : ''}`}
                              onError={(e) => { e.target.style.visibility = 'hidden' }}
                            />
                          ))}
                          {g.skins.length > 8 && <span className="al-more">+{g.skins.length - 8}</span>}
                        </div>
                        <div className="al-group-meta">
                          <span>{g.skins.length} colour{g.skins.length === 1 ? '' : 's'}</span>
                          {g.known && <span className="al-badge">matches your folder</span>}
                        </div>
                      </label>
                    )
                  })}
                </div>
              </>
            )
          )}
        </div>

        <div className="al-footer">
          <button className="al-action-btn" onMouseEnter={playHoverSound} onClick={() => { playSound('back'); onClose() }}>
            Cancel
          </button>
          <button
            className="al-action-btn al-apply-btn"
            disabled={!selectedSkinIds.length || applying}
            onMouseEnter={playHoverSound}
            onClick={apply}
          >
            {applying ? 'Moving…' : `Move ${selectedSkinIds.length} skin${selectedSkinIds.length === 1 ? '' : 's'} to Animelee`}
          </button>
        </div>
      </div>

      <style>{ANIMELEE_STYLES}</style>
    </div>
  )

  const portalTarget = getAppContentPortalTarget()
  return portalTarget ? createPortal(modal, portalTarget) : modal
}

const ANIMELEE_STYLES = `
        .al-overlay {
          position: absolute;
          inset: 0;
          background: rgba(6, 12, 20, 0.92);
          backdrop-filter: blur(12px);
          -webkit-backdrop-filter: blur(12px);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: calc(var(--z-modal) + 35);
          padding: var(--page-block-padding) var(--modal-inline-padding);
          overflow: auto;
          overscroll-behavior: contain;
        }

        .al-modal {
          width: min(100%, 600px);
          max-height: min(100%, var(--modal-max-height));
          background: linear-gradient(
            165deg,
            var(--color-bg-elevated) 0%,
            var(--color-bg-base) 40%,
            var(--color-bg-deep) 100%
          );
          border: 1px solid var(--color-cyan);
          border-radius: var(--radius-2xl);
          box-shadow:
            var(--shadow-xl),
            0 0 80px rgba(0, 0, 0, 0.5),
            0 0 24px rgba(125, 211, 232, 0.12);
          display: flex;
          flex-direction: column;
          overflow: hidden;
          margin: auto;
        }

        .al-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: var(--space-3) var(--space-6);
          background: rgba(0, 0, 0, 0.15);
          border-bottom: 1px solid var(--color-border-subtle);
          flex-shrink: 0;
        }

        .al-title {
          display: flex;
          align-items: baseline;
          gap: var(--space-3);
          min-width: 0;
        }

        .al-title-label {
          font-size: var(--text-lg);
          font-weight: 700;
          color: var(--color-text-primary);
        }

        .al-title-char {
          color: var(--color-cyan);
          font-weight: 600;
        }

        .al-close-btn {
          background: transparent;
          border: none;
          color: var(--color-text-secondary);
          cursor: pointer;
          display: flex;
          padding: var(--space-1);
        }

        .al-close-btn:hover {
          color: var(--color-text-primary);
        }

        .al-body {
          display: flex;
          flex-direction: column;
          min-height: 140px;
          overflow: hidden;
        }

        .al-hint {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: var(--space-3);
          padding: var(--space-3) var(--space-6);
          color: var(--color-text-tertiary);
          font-size: var(--text-sm);
          border-bottom: 1px solid var(--color-border-subtle);
          flex-shrink: 0;
        }

        .al-hint-actions {
          display: flex;
          flex-shrink: 0;
        }

        .al-link-btn {
          background: none;
          border: none;
          color: var(--color-cyan);
          cursor: pointer;
          margin-left: var(--space-3);
          font-size: var(--text-sm);
        }

        .al-link-btn:hover {
          text-decoration: underline;
        }

        .al-empty {
          padding: var(--space-8);
          text-align: center;
          color: var(--color-text-muted);
        }

        .al-error {
          color: var(--color-danger);
        }

        .al-list {
          overflow-y: auto;
          padding: var(--space-3) var(--space-4);
          display: flex;
          flex-direction: column;
          gap: var(--space-2);
        }

        .al-group {
          display: flex;
          align-items: center;
          gap: var(--space-3);
          padding: var(--space-2) var(--space-3);
          border-radius: var(--radius-md);
          border: 1px solid var(--color-border-subtle);
          background: var(--color-bg-surface);
          cursor: pointer;
        }

        .al-group:hover {
          border-color: var(--color-cyan);
        }

        .al-group--off {
          opacity: 0.5;
        }

        .al-check {
          flex-shrink: 0;
          accent-color: var(--color-cyan);
          width: 16px;
          height: 16px;
          cursor: pointer;
        }

        .al-thumbs {
          display: flex;
          gap: var(--space-1);
          flex-wrap: wrap;
          flex: 1;
          align-items: center;
          min-width: 0;
        }

        .al-thumb {
          width: 42px;
          height: 56px;
          object-fit: cover;
          border-radius: var(--radius-sm);
          background: var(--color-bg-deep);
          border: 1px solid var(--color-border-subtle);
        }

        .al-thumb--foldered {
          border-color: var(--color-cyan);
        }

        .al-more {
          font-size: var(--text-sm);
          color: var(--color-text-tertiary);
        }

        .al-group-meta {
          display: flex;
          flex-direction: column;
          align-items: flex-end;
          gap: var(--space-1);
          flex-shrink: 0;
          min-width: 76px;
        }

        .al-group-meta > span:first-child {
          color: var(--color-text-tertiary);
          font-size: var(--text-sm);
        }

        .al-badge {
          font-size: var(--text-xs);
          color: var(--color-cyan);
          border: 1px solid var(--color-cyan);
          border-radius: var(--radius-pill, 999px);
          padding: 1px 8px;
          white-space: nowrap;
        }

        .al-footer {
          display: flex;
          justify-content: flex-end;
          gap: var(--space-2);
          padding: var(--space-3) var(--space-4);
          border-top: 1px solid var(--color-border-subtle);
          flex-shrink: 0;
        }

        .al-action-btn {
          background: transparent;
          border: 1px solid var(--color-border);
          color: var(--color-text-secondary);
          border-radius: var(--radius-md);
          padding: var(--space-2) var(--space-4);
          cursor: pointer;
          font-size: var(--text-sm);
        }

        .al-action-btn:hover:not(:disabled) {
          border-color: var(--color-cyan);
          color: var(--color-cyan);
        }

        .al-action-btn:disabled {
          opacity: 0.5;
          cursor: default;
        }

        .al-apply-btn {
          border-color: var(--color-cyan);
          color: var(--color-cyan);
          font-weight: 600;
        }

        .al-apply-btn:hover:not(:disabled) {
          background: var(--color-cyan-muted);
        }
`
