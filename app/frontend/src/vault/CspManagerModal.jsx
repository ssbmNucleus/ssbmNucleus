/**
 * CspManagerModal -- the "Portraits" modal for one costume.
 *
 * One grid: the original portrait, each alternate, and an Add tile. The active
 * card is highlighted; click any other card to make it the one the game uses.
 * Alternates can be removed (hover), the original can be replaced (hover).
 * HD is a small info pill only -- Retake CSP / Bulk Retake write HD themselves.
 *
 * Every action is applied immediately (no Save/Cancel). Grouping of the flat
 * SD/HD alternate list happens in useCspManager.groupPortraits; this file only
 * renders `portraits`.
 */
import { useRef } from 'react'
import { createPortal } from 'react-dom'
import { getAppContentPortalTarget } from '../shared/ui/appContentPortal'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import './CspManagerModal.css'

const X_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <line x1="18" y1="6" x2="6" y2="18"></line>
    <line x1="6" y1="6" x2="18" y2="18"></line>
  </svg>
)

const UPLOAD_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
    <polyline points="17 8 12 3 7 8"></polyline>
    <line x1="12" y1="3" x2="12" y2="15"></line>
  </svg>
)

function PortraitCard({ portrait, lastImageUpdate, busy, onSetActive, onRemove, onReplace }) {
  const p = portrait
  const clickable = !p.isActive && !busy
  return (
    <div
      className={`csp-manager-card${p.isActive ? ' csp-manager-card--active' : ''}${busy ? ' csp-manager-card--busy' : ''}`}
      onClick={() => { if (clickable) { playSound('boop'); onSetActive(p) } }}
      onMouseEnter={clickable ? playHoverSound : undefined}
      title={p.isActive ? 'This portrait is the one the game uses' : 'Click to make this the active portrait'}
    >
      <img src={`${p.url}?t=${lastImageUpdate}`} alt={p.label} className="csp-manager-card-image" />
      <div className="csp-manager-card-badges">
        {p.isActive && <span className="csp-manager-badge csp-manager-badge--active">Active</span>}
        {p.kind === 'original' && !p.isActive && <span className="csp-manager-badge">Original</span>}
        {p.hasHd && <span className="csp-manager-badge csp-manager-badge--hd" title="A 4x copy exists for texture packs">HD</span>}
      </div>
      <div className="csp-manager-card-label">{p.label}</div>
      {!p.isActive && (
        <div className="csp-manager-card-overlay"><span>Set active</span></div>
      )}
      {p.kind === 'alt' && (
        <button
          className="csp-manager-card-action csp-manager-card-action--remove"
          onClick={(e) => { e.stopPropagation(); if (!busy) { playSound('boop'); onRemove(p) } }}
          disabled={busy}
          title="Remove this portrait"
        >
          {X_ICON}
        </button>
      )}
      {p.kind === 'original' && (
        <button
          className="csp-manager-card-action csp-manager-card-action--replace"
          onClick={(e) => { e.stopPropagation(); if (!busy) { playSound('boop'); onReplace() } }}
          disabled={busy}
          title="Replace the original portrait with an image"
        >
          {UPLOAD_ICON}<span>Replace</span>
        </button>
      )}
    </div>
  )
}

export default function CspManagerModal({
  show,
  skin,
  portraits,
  lastImageUpdate,
  busy,
  onClose,
  onSetActive,       // (portrait) => void
  onRemove,          // (portrait) => void        alternates only
  onReplaceOriginal, // ({ file }) => void
  onAddPortrait,     // ({ file }) => void
  onOpenPoseManager  // optional: render alternates from a saved pose instead
}) {
  const replaceInputRef = useRef(null)
  const addInputRef = useRef(null)

  if (!show || !skin) return null

  const pickFile = (e, handler) => {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-picking the same file later
    if (!file) return
    if (!file.type.startsWith('image/')) { alert('Please select an image file'); return }
    handler({ file })
  }
  const close = () => { playSound('back'); onClose() }
  const hasOriginal = portraits.some((p) => p.kind === 'original')

  const modal = (
    <div className="csp-manager-overlay" onClick={close}>
      <div className="csp-manager-modal" onClick={(e) => e.stopPropagation()}>
        <div className="csp-manager-header">
          <h2>Portraits</h2>
          <span className="csp-manager-skin-name">{skin.color || skin.name || skin.id}</span>
          <button className="csp-manager-close" onClick={close} title="Close">{X_ICON}</button>
        </div>

        <p className="csp-manager-hint">
          Click a portrait to make it the one the game uses. Installs use the active portrait.
        </p>

        <div className="csp-manager-grid">
          {!hasOriginal && (
            <button
              className="csp-manager-card csp-manager-card--empty"
              onClick={() => replaceInputRef.current?.click()}
              disabled={busy}
              title="This costume has no portrait yet — upload one"
            >
              {UPLOAD_ICON}
              <span>Upload portrait</span>
            </button>
          )}
          {portraits.map((p) => (
            <PortraitCard
              key={p.key}
              portrait={p}
              lastImageUpdate={lastImageUpdate}
              busy={busy}
              onSetActive={onSetActive}
              onRemove={onRemove}
              onReplace={() => replaceInputRef.current?.click()}
            />
          ))}
          <button
            className="csp-manager-card csp-manager-card--add"
            onClick={() => { playSound('boop'); addInputRef.current?.click() }}
            onMouseEnter={playHoverSound}
            disabled={busy}
            title="Add an alternate portrait from an image"
          >
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            <span>Add portrait</span>
          </button>
        </div>

        <div className="csp-manager-footer">
          {onOpenPoseManager && (
            <button
              className="mode-btn csp-manager-pose-btn"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); onOpenPoseManager() }}
              disabled={busy}
              title="Pose the 3D model and render portraits from it"
            >
              🎭 Render from a pose
            </button>
          )}
          <span className="csp-manager-count">
            {portraits.length} {portraits.length === 1 ? 'portrait' : 'portraits'}
            {busy && ' — working…'}
          </span>
          <span className="csp-manager-note">
            One image is enough: it's scaled for the game and a 4x copy is kept when the image is big enough.
          </span>
        </div>

        <input ref={replaceInputRef} type="file" accept="image/*" style={{ display: 'none' }}
          onChange={(e) => pickFile(e, onReplaceOriginal)} />
        <input ref={addInputRef} type="file" accept="image/*" style={{ display: 'none' }}
          onChange={(e) => pickFile(e, onAddPortrait)} />
      </div>
    </div>
  )

  const portalTarget = getAppContentPortalTarget()
  return portalTarget ? createPortal(modal, portalTarget) : modal
}
