import { useState, useEffect, useCallback, useContext } from 'react'
import { createPortal } from 'react-dom'
import HexagonLoader from '../../../shared/ui/HexagonLoader'
import { getAppContentPortalTarget } from '../../../shared/ui/appContentPortal'
import { CloseIcon } from '../../../shared/ui/Icons'
import { playSound } from '../../../shared/audio/sounds'
import { API_URL, backendMediaUrl } from '../../../shared/config/config.js'
import { api } from '../../../shared/transport/api'
import { VaultActiveContext } from '../../vaultActive.js'
import { skinSelectorEscape } from './poseModalKeys.js'
import { skinCspVersion } from './poseSkinCards.js'

/**
 * Pose Skin Selector Modal
 * Opens when clicking a saved pose, allows selecting multiple skins
 * to batch generate CSPs using that pose.
 * Escape closes it (not while rendering: poseModalKeys.js). Portaled into .app-content, so it hides while its page
 * is not on screen (VaultActiveContext). The cards re-read the skins after Generate and carry the shown file's
 * version, so they show the new portraits (poseSkinCards.js).
 */

const CheckIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="20 6 9 17 4 12"/>
  </svg>
)

const GenerateIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
    <circle cx="8.5" cy="8.5" r="1.5"/>
    <polyline points="21 15 16 10 5 21"/>
  </svg>
)

// Skin Card with checkbox
function SkinCheckboxCard({ skin, selected, onToggle }) {
  return (
    <div
      className={`pss-skin-card ${selected ? 'pss-selected' : ''}`}
      onClick={() => onToggle(skin.folder)}
    >
      <div className="pss-checkbox">
        {selected && <CheckIcon />}
      </div>
      <div className="pss-skin-image">
        {skin.cspUrl ? (
          <img
            src={backendMediaUrl(skin.cspUrl, skinCspVersion(skin))}
            alt={skin.name}
            onError={(e) => { e.target.style.display = 'none' }}
          />
        ) : (
          <div className="pss-skin-placeholder">?</div>
        )}
      </div>
      <div className="pss-skin-name">{skin.name?.split(' - ')[1] || skin.costumeCode}</div>
    </div>
  )
}

export default function PoseSkinSelectorModal({
  show,
  character,
  poseName,
  // Display name when poseName is a sentinel (e.g. the built-in default pose)
  poseLabel,
  poseThumbnail,
  onClose,
  onRefresh,
  onCostumesUpdated,
}) {
  const [skins, setSkins] = useState([])
  const [selectedSkins, setSelectedSkins] = useState(new Set())
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [progress, setProgress] = useState({ current: 0, total: 0 })
  const [results, setResults] = useState(null)

  // Fetch skins for this character. Custom characters share poses between
  // their bundled costumes and added skins, so offer both lists. `quiet` keeps
  // the grid up (the re-read after Generate).
  const fetchSkins = useCallback(async (quiet = false) => {
    if (!character) return
    if (!quiet) setLoading(true)
    try {
      const keys = character.startsWith('custom_characters/')
        ? [character.replace(/\/(skins|costumes)$/, '/costumes'),
           character.replace(/\/(skins|costumes)$/, '/skins')]
        : [character]
      const all = []
      for (const key of keys) {
        try {
          const data = await api.get('/storage/costumes', { query: { character: key } })
          all.push(...data.costumes.filter(c => c.character === key))
        } catch {
          // a container that doesn't exist just contributes no skins
        }
      }
      setSkins(all)
    } catch (err) {
      console.error('[PoseSkinSelector] Fetch skins error:', err)
    } finally {
      setLoading(false)
    }
  }, [character, API_URL])

  useEffect(() => {
    if (show) {
      fetchSkins()
      setSelectedSkins(new Set())
      setResults(null)
    }
  }, [show, fetchSkins])

  const hidden = !useContext(VaultActiveContext)   // another page is on screen: kept, not shown, deaf to Escape
  useEffect(() => {
    if (!show) return undefined
    const onKey = (e) => {
      if (skinSelectorEscape({ key: e.key, defaultPrevented: e.defaultPrevented, hidden, generating }) !== 'close') return
      e.preventDefault()   // this Escape is the dialog's: the Pose Manager underneath stays open
      playSound('back')
      onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [show, hidden, generating, onClose])

  if (!show) return null

  const toggleSkin = (skinId) => {
    setSelectedSkins(prev => {
      const next = new Set(prev)
      if (next.has(skinId)) {
        next.delete(skinId)
      } else {
        next.add(skinId)
      }
      return next
    })
  }

  const selectAll = () => {
    setSelectedSkins(new Set(skins.map(s => s.folder)))
  }

  const deselectAll = () => {
    setSelectedSkins(new Set())
  }

  // Generate one skin per request so we can show real per-skin progress
  // (each render takes seconds; one big batch request gave no feedback)
  const handleGenerate = async () => {
    if (selectedSkins.size === 0) return

    const skinList = Array.from(selectedSkins)
    setGenerating(true)
    setResults(null)
    setProgress({ current: 0, total: skinList.length })

    let generated = 0
    let failed = 0
    const details = []

    for (let i = 0; i < skinList.length; i++) {
      setProgress({ current: i + 1, total: skinList.length })
      try {
        // Custom characters mix two skin containers (bundled costumes +
        // added skins) — address each skin under its own character key.
        const skinChar = skins.find(s => s.folder === skinList[i])?.character || character
        const data = await api.post('/storage/poses/batch-generate-csp', {
          character: skinChar,
          poseName,
          skinIds: [skinList[i]],
          hdResolution: '4x'
        })

        generated += data.generated || 0
        failed += data.failed || 0
        if (Array.isArray(data.results)) details.push(...data.results)
      } catch (err) {
        console.error('[PoseSkinSelector] Generate error:', err)
        failed += 1
      }
    }

    playSound(generated > 0 ? 'camera' : 'error')
    setResults({ generated, failed, details })

    if (generated > 0) {
      if (onCostumesUpdated) {
        await onCostumesUpdated({ character, skinIds: skinList })
      } else if (onRefresh) {
        await onRefresh()
      }
      // the cards were read when the dialog opened: re-read them so they show the new portraits
      await fetchSkins(true)
    }

    setGenerating(false)
  }

  const handleClose = () => {
    playSound('back')
    onClose()
  }

  const modal = (
    <div className="pss-overlay" onClick={(e) => e.target === e.currentTarget && !generating && handleClose()}
      style={hidden ? { display: 'none' } : undefined}>
      <div className="pss-modal">
        {/* Header */}
        <div className="pss-header">
          <div className="pss-title">
            <span className="pss-title-label">Generate CSPs</span>
            <span className="pss-title-pose">"{poseLabel || poseName}"</span>
          </div>
          <button className="pss-close-btn" onClick={handleClose} disabled={generating}>
            <CloseIcon />
          </button>
        </div>

        {/* Pose Preview */}
        {poseThumbnail && (
          <div className="pss-pose-preview">
            <img src={poseThumbnail} alt={poseLabel || poseName} />
            <span>Using this pose for all selected skins</span>
          </div>
        )}

        {/* Controls */}
        <div className="pss-controls">
          <div className="pss-select-btns">
            <button onClick={selectAll} disabled={generating}>Select All</button>
            <button onClick={deselectAll} disabled={generating}>Deselect All</button>
          </div>
          <div className="pss-resolution-note">Generates standard + 4x HD portraits</div>
        </div>

        {/* Skins Grid */}
        <div className="pss-skins-grid">
          {loading ? (
            <div className="pss-loading-shell">
              <HexagonLoader size={96} label="Loading skins" />
              <div className="pss-loading">Loading skins...</div>
            </div>
          ) : skins.length === 0 ? (
            <div className="pss-empty">No skins found for {character}</div>
          ) : (
            skins.map(skin => (
              <SkinCheckboxCard
                key={skin.folder}
                skin={skin}
                selected={selectedSkins.has(skin.folder)}
                onToggle={toggleSkin}
              />
            ))
          )}
        </div>

        {/* Generate Button / Progress */}
        <div className="pss-footer">
          {generating ? (
            <div className="pss-progress">
              <HexagonLoader
                size={92}
                label="Generating CSPs"
                progress={progress.total ? ((progress.current - 1) / progress.total) * 100 : null}
                centerLabel={progress.total ? `${progress.current}/${progress.total}` : null}
                minimumVisibleProgress={4}
              />
              <span>Generating {progress.current} / {progress.total}…</span>
            </div>
          ) : results ? (
            <div className={`pss-results ${results.error ? 'pss-error' : 'pss-success'}`}>
              {results.error ? (
                <span>Error: {results.error}</span>
              ) : (
                <span>{results.generated} skin{results.generated !== 1 ? 's' : ''} now show{results.generated === 1 ? 's' : ''} this pose{results.failed > 0 ? `, ${results.failed} failed` : ''}</span>
              )}
              <button onClick={handleClose}>Done</button>
            </div>
          ) : (
            <button
              className="pss-generate-btn"
              onClick={handleGenerate}
              disabled={selectedSkins.size === 0}
            >
              <GenerateIcon />
              <span>Generate {selectedSkins.size} CSP{selectedSkins.size !== 1 ? 's' : ''}</span>
            </button>
          )}
        </div>
      </div>

      <style>{`
        .pss-overlay {
          position: absolute;
          inset: 0;
          background: rgba(6, 12, 20, 0.92);
          backdrop-filter: blur(12px);
          -webkit-backdrop-filter: blur(12px);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: calc(var(--z-modal) + 50);
          padding: var(--page-block-padding) var(--modal-inline-padding);
          overflow: auto;
          overscroll-behavior: contain;
        }

        .pss-modal {
          background: linear-gradient(
            165deg,
            var(--color-bg-elevated) 0%,
            var(--color-bg-base) 40%,
            var(--color-bg-deep) 100%
          );
          border: 1px solid var(--color-cyan);
          border-radius: var(--radius-2xl);
          width: min(100%, 60rem);
          max-height: min(100%, var(--modal-max-height));
          display: flex;
          flex-direction: column;
          overflow: hidden;
          box-shadow:
            var(--shadow-xl),
            0 0 80px rgba(0, 0, 0, 0.5),
            0 0 24px rgba(125, 211, 232, 0.12);
          margin: auto;
        }

        .pss-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: var(--space-3) var(--space-6);
          background: rgba(0, 0, 0, 0.15);
          border-bottom: 1px solid var(--color-border-subtle);
        }

        .pss-title {
          display: flex;
          align-items: center;
          gap: var(--space-3);
          min-width: 0;
        }

        .pss-title-label {
          font-family: var(--font-display);
          font-size: var(--text-lg);
          font-weight: var(--font-bold);
          letter-spacing: var(--tracking-tight);
          background: var(--gradient-cyan);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
        }

        .pss-title-pose {
          font-size: var(--text-sm);
          color: var(--color-cyan);
          padding: 2px 10px;
          background: var(--color-cyan-muted, rgba(125, 211, 232, 0.12));
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-md);
        }

        .pss-close-btn {
          width: 32px;
          height: 32px;
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-full);
          background: var(--color-bg-surface);
          color: var(--color-text-tertiary);
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all var(--transition-fast);
          flex-shrink: 0;
        }

        .pss-close-btn:hover:not(:disabled) {
          background: var(--color-danger-muted);
          color: var(--color-danger);
          border-color: var(--color-danger);
          transform: rotate(90deg);
        }

        .pss-close-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .pss-pose-preview {
          display: flex;
          align-items: center;
          gap: var(--space-4);
          padding: var(--space-3) var(--space-6);
          border-bottom: 1px solid var(--color-border-subtle);
        }

        .pss-pose-preview img {
          width: 60px;
          height: 80px;
          object-fit: contain;
          border-radius: var(--radius-md);
          background: var(--color-bg-deep);
          border: 1px solid var(--color-border-subtle);
        }

        .pss-pose-preview span {
          color: var(--color-text-secondary);
          font-size: var(--text-sm);
        }

        .pss-controls {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: var(--space-3);
          padding: var(--space-3) var(--space-6);
          border-bottom: 1px solid var(--color-border-subtle);
        }

        .pss-select-btns {
          display: flex;
          gap: var(--space-2);
        }

        .pss-select-btns button {
          padding: var(--space-1) var(--space-3);
          background: var(--color-bg-elevated);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-lg);
          color: var(--color-text-secondary);
          cursor: pointer;
          font-family: var(--font-display);
          font-size: var(--text-xs);
          font-weight: var(--font-semibold);
          transition: all var(--transition-fast);
        }

        .pss-select-btns button:hover:not(:disabled) {
          background: var(--color-cyan);
          border-color: var(--color-cyan);
          color: var(--color-bg-deep);
        }

        .pss-select-btns button:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .pss-resolution-note {
          color: var(--color-text-muted);
          font-size: var(--text-xs);
        }

        .pss-skins-grid {
          flex: 1;
          overflow-y: auto;
          padding: var(--space-4) var(--space-6);
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
          gap: var(--space-3);
          align-content: start;
        }

        .pss-loading-shell,
        .pss-loading,
        .pss-empty {
          grid-column: 1 / -1;
          text-align: center;
          color: var(--color-text-muted);
          padding: var(--space-8);
        }

        .pss-loading-shell {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: var(--space-4);
        }

        .pss-skin-card {
          position: relative;
          background: var(--color-bg-deep);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-lg);
          padding: var(--space-2);
          cursor: pointer;
          transition: all var(--transition-fast);
        }

        .pss-skin-card:hover {
          border-color: var(--color-cyan);
          transform: translateY(-2px);
          box-shadow: var(--glow-cyan-sm);
        }

        .pss-skin-card.pss-selected {
          border-color: var(--color-cyan);
          background: var(--color-cyan-muted, rgba(125, 211, 232, 0.1));
        }

        .pss-checkbox {
          position: absolute;
          top: 6px;
          left: 6px;
          width: 20px;
          height: 20px;
          background: var(--color-bg-deep);
          border: 2px solid var(--color-border);
          border-radius: var(--radius-sm);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1;
        }

        .pss-selected .pss-checkbox {
          background: var(--color-cyan);
          border-color: var(--color-cyan);
        }

        .pss-checkbox svg {
          color: var(--color-bg-deep);
        }

        .pss-skin-image {
          width: 100%;
          aspect-ratio: 3/4;
          display: flex;
          align-items: center;
          justify-content: center;
          background: var(--color-bg-base);
          border-radius: var(--radius-md);
          overflow: hidden;
        }

        .pss-skin-image img {
          max-width: 100%;
          max-height: 100%;
          object-fit: contain;
        }

        .pss-skin-placeholder {
          color: var(--color-text-tertiary);
          font-size: var(--text-xl);
          font-family: var(--font-display);
          font-weight: var(--font-bold);
        }

        .pss-skin-name {
          text-align: center;
          font-family: var(--font-display);
          font-size: var(--text-xs);
          color: var(--color-text-secondary);
          margin-top: var(--space-1);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .pss-footer {
          padding: var(--space-3) var(--space-6);
          background: rgba(0, 0, 0, 0.15);
          border-top: 1px solid var(--color-border-subtle);
        }

        .pss-generate-btn {
          width: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: var(--space-2);
          padding: var(--space-3);
          background: var(--gradient-cyan, var(--color-cyan));
          border: none;
          border-radius: var(--radius-lg);
          color: var(--color-bg-deep);
          font-family: var(--font-display);
          font-size: var(--text-sm);
          font-weight: var(--font-semibold);
          cursor: pointer;
          transition: all var(--transition-fast);
        }

        .pss-generate-btn:hover:not(:disabled) {
          box-shadow: var(--glow-cyan-sm);
          transform: translateY(-1px);
        }

        .pss-generate-btn:disabled {
          background: var(--color-bg-elevated);
          color: var(--color-text-muted);
          cursor: not-allowed;
        }

        .pss-progress {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: var(--space-3);
        }

        .pss-progress span {
          text-align: center;
          color: var(--color-text-secondary);
          font-size: var(--text-sm);
        }

        .pss-results {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: var(--space-3);
        }

        .pss-results span {
          font-size: var(--text-sm);
        }

        .pss-results.pss-success span {
          color: var(--color-success, #51cf66);
        }

        .pss-results.pss-error span {
          color: var(--color-danger, #ff6b6b);
        }

        .pss-results button {
          padding: var(--space-2) var(--space-4);
          background: var(--color-bg-elevated);
          border: 1px solid var(--color-border-subtle);
          border-radius: var(--radius-lg);
          color: var(--color-text-secondary);
          font-family: var(--font-display);
          font-size: var(--text-sm);
          font-weight: var(--font-semibold);
          cursor: pointer;
          transition: all var(--transition-fast);
        }

        .pss-results button:hover {
          background: var(--color-cyan);
          border-color: var(--color-cyan);
          color: var(--color-bg-deep);
        }

        @media (max-width: 960px) {
          .pss-modal {
            width: 100%;
          }

          .pss-controls {
            flex-wrap: wrap;
          }
        }
      `}</style>
    </div>
  )

  const portalTarget = getAppContentPortalTarget()
  return portalTarget ? createPortal(modal, portalTarget) : modal
}
