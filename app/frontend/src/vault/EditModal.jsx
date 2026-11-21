/**
 * EditModal - the costume / stage-variant edit page.
 *
 * Nothing here is pending: every control writes immediately and refreshes the
 * vault. The item's name IS the title (rename on Enter or blur, Escape reverts).
 * Costume: portrait + stock on the left, grouped actions and the Slippi panel
 * on the right. Stage: preview on the left, actions + safety on the right.
 * Hovering an image shows its buttons: the ones that write to it (replace,
 * retake, generate) along the bottom, Export -- save that one image to a file
 * -- along the top, so a tall row never covers a short one.
 * Footer: Export and Delete only. Close is the X, the overlay or Escape (editModalKeys.js: the name field keeps
 * Escape only to revert an unsaved name). While the vault is not the page on screen (VaultActiveContext) the modal
 * is kept but not shown: it is portaled into .app-content, so it used to stay over the AI page and the other tabs.
 */
import { useContext, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { getAppContentPortalTarget } from '../shared/ui/appContentPortal'
import { InGameTestRunning } from '../shared/viewer/InGameTestPanel'
import HexagonLoader from '../shared/ui/HexagonLoader'
import { playSound } from '../shared/audio/sounds'
import { API_URL, backendMediaUrl } from '../shared/config/config.js'
import { heldPortraitSrc, resolveDisplayCspUrl, toAbsoluteMediaUrl } from './editModalUrls.js'
import { editModalEscape, titleEscapeReverts } from './editModalKeys.js'
import { VaultActiveContext } from './vaultActive.js'
import { downloadImage, imageFilename } from './lib/imageDownload.js'
import PosePicker from './PosePicker'
import { DEFAULT_POSE_LABEL } from './posePickerModel.js'
import '../shared/ui/EditModal.css'
import './EditModal.css'

// Every CSP shares the vanilla texture frame; the hero never adapts to an off-ratio image.
const CSP_ASPECT = 136 / 188

const Icon = {
  close: (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>
    </svg>
  ),
  pencil: (size = 20) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
    </svg>
  ),
  portraits: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
      <circle cx="8.5" cy="8.5" r="1.5"></circle>
      <polyline points="21 15 16 10 5 21"></polyline>
    </svg>
  ),
  retake: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline>
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
    </svg>
  ),
  pose: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="4.5" r="2.5"></circle>
      <path d="M12 7v7M12 14l-4 7M12 14l4 7M5 6l7 4 7-5"></path>
    </svg>
  ),
  // the two stock-icon styles: a palette (recolor the vanilla pixel art) and
  // a head (crop one out of a 3D render)
  palette: (size = 14) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2a10 10 0 0 0 0 20c1.1 0 2-.9 2-2 0-.5-.2-1-.6-1.4-.3-.3-.4-.7-.4-1.1 0-.8.7-1.5 1.5-1.5H16a6 6 0 0 0 6-6c0-4.4-4.5-8-10-8z"></path>
      <circle cx="7.5" cy="11.5" r="1.1" fill="currentColor" stroke="none"></circle>
      <circle cx="11" cy="7.5" r="1.1" fill="currentColor" stroke="none"></circle>
      <circle cx="15.5" cy="8.5" r="1.1" fill="currentColor" stroke="none"></circle>
    </svg>
  ),
  head: (size = 14) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="8" r="5"></circle>
      <path d="M4 22a8 8 0 0 1 16 0"></path>
    </svg>
  ),
  cube: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2L2 7l10 5 10-5-10-5z"></path><path d="M2 17l10 5 10-5"></path><path d="M2 12l10 5 10-5"></path>
    </svg>
  ),
  gamepad: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="2" y="6" width="20" height="12" rx="6"></rect>
      <line x1="6" y1="12" x2="10" y2="12"></line><line x1="8" y1="10" x2="8" y2="14"></line>
      <line x1="15" y1="13" x2="15.01" y2="13"></line><line x1="18" y1="11" x2="18.01" y2="11"></line>
    </svg>
  ),
  camera: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path>
      <circle cx="12" cy="13" r="4"></circle>
    </svg>
  ),
  export: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
      <polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line>
    </svg>
  ),
  // the same tray as `export`, arrow pointing in: save this one image out
  download: (size = 18) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
      <polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="3" x2="12" y2="15"></line>
    </svg>
  ),
  trash: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="3 6 5 6 21 6"></polyline>
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
    </svg>
  ),
  refresh: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
    </svg>
  ),
}

/** The item's name as the title. Enter / blur commit; Escape reverts an unsaved name, else closes the modal. */
function TitleField({ value, onChange, onCommit, committedName, renaming, disabled }) {
  const [flash, setFlash] = useState(false)
  const inputRef = useRef(null)
  const revertingRef = useRef(false) // Escape: the blur that follows must not commit
  const dirty = value.trim() !== committedName
  const commit = async () => {
    if (revertingRef.current) { revertingRef.current = false; return }
    if (!dirty) { onChange(committedName); return }
    const ok = await onCommit(value)
    if (ok) { setFlash(true); setTimeout(() => setFlash(false), 1600) }
  }
  return (
    <div className={`edit-modal-title${dirty ? ' edit-modal-title--dirty' : ''}`}>
      <input
        ref={inputRef}
        className="edit-modal-title-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); inputRef.current?.blur() }
          if (e.key === 'Escape' && titleEscapeReverts(value, committedName)) {
            e.preventDefault()   // this Escape is the name's: the modal stays open (editModalKeys.js)
            revertingRef.current = true
            onChange(committedName)
            inputRef.current?.blur()
          }
        }}
        placeholder="Name"
        disabled={disabled || renaming}
        spellCheck={false}
        aria-label="Name"
        title="Click to rename. Enter saves, Escape puts the name back."
      />
      <span className="edit-modal-title-status" aria-live="polite">
        {renaming ? 'Renaming…' : flash ? '✓ Renamed' : dirty ? 'Enter to rename' : ''}
      </span>
    </div>
  )
}

function ActionButton({ icon, label, onClick, disabled, title, busy, className = 'edit-modal-tile' }) {
  return (
    <button className={className} onClick={onClick} disabled={disabled} title={title}>
      {busy ? <span className="edit-modal-action-spinner"></span> : icon}
      <span>{label}</span>
    </button>
  )
}

export default function EditModal({
  show,
  editingItem,
  lastImageUpdate,
  covered = false,   // a dialog or viewer is open over the modal: Escape is its

  // Name (title field)
  editName,
  onNameChange,
  onRename,          // (name) => Promise<boolean>
  renaming,

  // Write-in-flight flags
  busy,
  deleting,
  exporting,

  // Handlers
  onClose,
  onDelete,
  onExport,
  onReplaceStock,          // (file) => void          costume
  onGenerateStock,
  onConfirmGeneratedStock,
  onDiscardGeneratedStock,
  pendingGeneratedStock,
  generatingStock,
  onRetakeCsp,
  onNewPose,               // (costume) => void: open the pose maker on this costume's model
  onConfirmGeneratedCsp,
  onDiscardGeneratedCsp,
  pendingGeneratedCsp,
  appliedCsp,
  generatingCsp,
  onReplaceScreenshot,     // (file) => void          stage
  onSetStageSafety,        // (true|false|null) => void  stage
  onSlippiRetest,          // costume
  onSlippiOverride,        // (slippiSafe) => void   costume
  safetyBusy,
  onOpenCspManager,
  onStartSkinCreator,
  onView3D,

  // In-game test
  onTestInGame,
  onCaptureScreenshot,
  onReplaceWithCapture,
  testingInGame,
  testStatus,
  testResult,
  testError,
  testMode,
  stoppingTest,
  stopError,
  onStopTest,
  onResetTest,

}) {
  // Aspect ratio of the loaded hero image, so the grid panel hugs it
  const [panelAspect, setPanelAspect] = useState(null)
  const [safetyOpen, setSafetyOpen] = useState(false)   // Slippi dropdown (costume)
  const [posesOpen, setPosesOpen] = useState(false)     // pose list over the portrait (costume)
  const stockInputRef = useRef(null)
  const screenshotInputRef = useRef(null)

  useEffect(() => {
    setPanelAspect(null)
    setSafetyOpen(false)
    setPosesOpen(false)
  }, [editingItem?.type, editingItem?.data?.id])

  const open = Boolean(show && editingItem)
  const hidden = !useContext(VaultActiveContext)   // another page is on screen: kept, not shown, deaf to Escape
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      const action = editModalEscape({ key: e.key, defaultPrevented: e.defaultPrevented, covered, hidden, posesOpen, safetyOpen })
      if (action === 'poses') setPosesOpen(false)
      else if (action === 'safety') setSafetyOpen(false)
      else if (action === 'close') { playSound('back'); onClose() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, covered, hidden, posesOpen, safetyOpen, onClose])

  if (!open) return null

  const isCostume = editingItem.type === 'costume'
  const d = editingItem.data
  const committedName = (isCostume ? d.color : d.name) || ''
  const locked = deleting || exporting
  const anyBusy = locked || busy || testingInGame

  const handleHeroImageLoad = (e) => {
    const { naturalWidth, naturalHeight } = e.target
    if (naturalWidth && naturalHeight) setPanelAspect(naturalWidth / naturalHeight)
  }

  // Root-relative URLs (/storage/..., /api/mex/...) resolve via the vite proxy in
  // dev, but in the packaged app the page origin is file:// so they fail to load
  // (blank stage preview / stock icon). Prefix the backend origin for any
  // leading-'/' URL; data URIs and already-absolute URLs pass through unchanged.
  const backendBase = API_URL.replace('/api/mex', '')
  const toAbsUrl = (u) => toAbsoluteMediaUrl(u, backendBase)
  const displayCspUrl = isCostume ? resolveDisplayCspUrl(d, backendBase) : null
  // A portrait the user just retook and kept stays on screen from memory --
  // instant, and exactly what they approved, where displayCspUrl still points
  // at whichever file this snapshot knew about before the retake.
  const heldCspSrc = isCostume ? heldPortraitSrc(appliedCsp, lastImageUpdate) : null

  const pickFile = (e, handler) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (file) handler(file)
  }

  // Save one image out to a file. These buttons sit at the TOP of each image so
  // they never crowd the import / render buttons that live along the bottom.
  const exportImage = async (src, parts) => {
    playSound('boop')
    try {
      await downloadImage(src, imageFilename(parts, src))
    } catch (err) {
      playSound('error')
      alert(`Export error: ${err.message}`)
    }
  }
  const cspSrc = heldCspSrc || (displayCspUrl ? `${displayCspUrl}?t=${lastImageUpdate}` : null)

  const handleClose = () => { playSound('back'); onClose() }

  const modal = (
    <div className="edit-modal-fullscreen-overlay" onClick={handleClose} style={hidden ? { display: 'none' } : undefined}>
      {/* --costume sizes the modal around a tall portrait; a stage variant's
          preview is wide, so it keeps the roomier --item width. */}
      <div className={`edit-modal-fullscreen edit-modal-fullscreen--item${isCostume ? ' edit-modal-fullscreen--costume' : ''}`} onClick={(e) => e.stopPropagation()}>
        <button className="edit-modal-close" onClick={handleClose} title="Close">{Icon.close}</button>

        {/* Header: the name IS the title */}
        <div className="edit-modal-header edit-modal-header--title">
          <TitleField
            value={editName}
            onChange={onNameChange}
            onCommit={onRename}
            committedName={committedName}
            renaming={renaming}
            disabled={locked}
          />
          {!isCostume && d.transformationSkins === 4 && (
            <div className="edit-modal-subtitle">
              <span className="edit-modal-forms-badge" title="This skin has its own textures for fire, grass, water and rock">4 FORMS</span>
            </div>
          )}
        </div>

        {/* Body */}
        <div className="edit-modal-body">
          {isCostume ? (
            <>
              {/* LEFT: portrait, always in the CSP's own 136:188 frame; anything
                  off-ratio is crop-filled, never stretched or letterboxed */}
              <div className="edit-modal-csp-section">
                <div className="edit-modal-media">
                <div className="edit-modal-csp-stage">
                <div className="edit-modal-csp-container" style={{ '--panel-aspect': CSP_ASPECT }}>
                  {pendingGeneratedCsp ? (
                    /* Fresh render wipes in over the current portrait (key
                       restarts the sweep for each new retake) */
                    <div className="edit-modal-reveal" key={pendingGeneratedCsp.dataUri}>
                      {(heldCspSrc || d.has_csp || d.active_csp_id) && (
                        <img src={heldCspSrc || `${displayCspUrl}?t=${lastImageUpdate}`} alt="Current portrait"
                          className="edit-modal-csp-image edit-modal-csp-image--cover edit-modal-reveal-old"
                          onError={(e) => e.target.style.display = 'none'} />
                      )}
                      <img src={pendingGeneratedCsp.dataUri} alt="Retaken portrait preview"
                        className="edit-modal-csp-image edit-modal-csp-image--cover edit-modal-reveal-new" />
                      <div className="edit-modal-reveal-edge" aria-hidden="true"></div>
                    </div>
                  ) : (heldCspSrc || d.has_csp || d.active_csp_id) ? (
                    <img src={heldCspSrc || `${displayCspUrl}?t=${lastImageUpdate}`} alt="CSP"
                      className="edit-modal-csp-image edit-modal-csp-image--cover"
                      onError={(e) => e.target.style.display = 'none'} />
                  ) : (
                    <div className="edit-modal-csp-placeholder"><span>{(d.color || '?')[0]}</span></div>
                  )}
                  {/* Retaken portrait: confirm ON the hero so nothing reflows */}
                  {pendingGeneratedCsp && !generatingCsp && (
                    <div className="edit-modal-csp-confirm-overlay">
                      {'pose' in pendingGeneratedCsp && (
                        <span className="edit-modal-csp-confirm-pose">
                          {pendingGeneratedCsp.pose || DEFAULT_POSE_LABEL}
                        </span>
                      )}
                      <div className="edit-modal-stock-confirm-actions">
                        <button className="edit-modal-stock-confirm-btn edit-modal-stock-confirm-btn--yes"
                          onClick={onConfirmGeneratedCsp}
                          title="Replace the portrait with this fresh render">✓ Use it</button>
                        <button className="edit-modal-stock-confirm-btn"
                          onClick={onDiscardGeneratedCsp}
                          title="Keep the current portrait">✗ Discard</button>
                      </div>
                    </div>
                  )}
                  {!pendingGeneratedCsp && !generatingCsp && (heldCspSrc || d.has_csp || d.active_csp_id) && (
                    <div className="edit-modal-hover-actions edit-modal-hover-actions--top">
                      <button className="edit-modal-image-edit-btn"
                        onClick={() => exportImage(cspSrc, [d.character, d.color, 'csp'])}
                        title="Save this portrait out as an image file">
                        {Icon.download(18)}<span>Export CSP</span>
                      </button>
                    </div>
                  )}
                  {!pendingGeneratedCsp && !generatingCsp && !posesOpen && (
                    <div className="edit-modal-hover-actions">
                      {onOpenCspManager && (
                        <button className="edit-modal-image-edit-btn" onClick={() => onOpenCspManager(d)} disabled={locked}
                          title="Pick the active portrait, add or remove alternates, replace the original">
                          {Icon.portraits}<span>Portraits</span>
                        </button>
                      )}
                      {onRetakeCsp && (
                        <button className="edit-modal-image-edit-btn" onClick={() => { playSound('boop'); setPosesOpen(true) }} disabled={anyBusy}
                          title="Take the portrait with another pose (you confirm before it replaces anything)">
                          {Icon.pose}<span>Pose</span>
                        </button>
                      )}
                      {onRetakeCsp && (
                        <button className="edit-modal-image-edit-btn" onClick={() => onRetakeCsp()} disabled={anyBusy}
                          title="Re-render the portrait from this costume with its active pose (you confirm before it replaces anything)">
                          {Icon.retake}<span>Retake CSP</span>
                        </button>
                      )}
                    </div>
                  )}
                  {/* Pose list, in the buttons' place: a pick renders the preview above */}
                  {posesOpen && !pendingGeneratedCsp && !generatingCsp && onRetakeCsp && (
                    <PosePicker character={d.character} costume={d}
                      onPick={(pose) => { setPosesOpen(false); onRetakeCsp(pose) }}
                      onNew={onNewPose ? () => { setPosesOpen(false); onNewPose(d) } : null}
                      onClose={() => setPosesOpen(false)} />
                  )}
                  {generatingCsp && (
                    <div className="edit-modal-csp-rendering-overlay">
                      <HexagonLoader size={72} label="Rendering" />
                      <span>Rendering portrait…</span>
                    </div>
                  )}
                </div>
                </div>
                {/* Stock icon beside the portrait: hover for replace / generate */}
                <div className="edit-modal-stock-side">
                  {pendingGeneratedStock ? (
                    /* generated icon: current -> new, confirm in place */
                    <div className="edit-modal-stock-compare">
                      <div className="edit-modal-stock-thumb" title="Current stock icon">
                        {d.has_stock
                          ? <img src={`${toAbsUrl(d.stockUrl)}?t=${lastImageUpdate}`} alt="Current stock" />
                          : <span>—</span>}
                      </div>
                      <span className="edit-modal-stock-arrow">↓</span>
                      <div className="edit-modal-stock-thumb edit-modal-stock-thumb--new" title="Generated stock icon">
                        <img src={pendingGeneratedStock.dataUri} alt="Generated stock" />
                      </div>
                      <div className="edit-modal-stock-compare-actions">
                        <button className="edit-modal-stock-confirm-btn edit-modal-stock-confirm-btn--yes"
                          onClick={onConfirmGeneratedStock} disabled={generatingStock}
                          title="Replace the stock icon with the generated one">✓ Use it</button>
                        <button className="edit-modal-stock-confirm-btn"
                          onClick={onDiscardGeneratedStock} disabled={generatingStock}
                          title="Keep the current stock icon">✗ Discard</button>
                      </div>
                    </div>
                  ) : (
                  <div className="edit-modal-stock-hero" title="Stock icon">
                    {d.has_stock ? (
                      <img src={`${toAbsUrl(d.stockUrl)}?t=${lastImageUpdate}`} alt="Stock"
                        onError={(e) => e.target.style.display = 'none'} />
                    ) : (
                      <span>{(d.color || '?')[0]}</span>
                    )}
                    <input ref={stockInputRef} type="file" accept="image/*" style={{ display: 'none' }}
                      onChange={(e) => pickFile(e, onReplaceStock)} />
                    {d.has_stock && (
                      <div className="edit-modal-hover-actions edit-modal-hover-actions--stock edit-modal-hover-actions--top">
                        <button className="edit-modal-icon-btn"
                          onClick={() => exportImage(toAbsUrl(d.stockUrl), [d.character, d.color, 'stock'])}
                          title="Save this stock icon out as an image file">
                          {Icon.download(14)}
                        </button>
                      </div>
                    )}
                    <div className="edit-modal-hover-actions edit-modal-hover-actions--stock">
                      <button className="edit-modal-icon-btn"
                        onClick={() => stockInputRef.current?.click()} disabled={anyBusy || generatingStock}
                        title="Replace the stock icon with an image (applies immediately)">
                        {Icon.pencil(14)}
                      </button>
                      {onGenerateStock && (
                        /* The two icon styles are a CHOICE, not a fallback
                           chain: the backend used to pick one and there was
                           no way to overrule it. */
                        <>
                          <button className="edit-modal-icon-btn"
                            onClick={() => onGenerateStock('recolor')} disabled={generatingStock || anyBusy}
                            title="Generate a stock icon by recoloring the vanilla pixel icon">
                            {generatingStock === 'recolor' ? '⟳' : Icon.palette(14)}
                          </button>
                          <button className="edit-modal-icon-btn"
                            onClick={() => onGenerateStock('render')} disabled={generatingStock || anyBusy}
                            title="Generate a stock icon by rendering this model's head in 3D">
                            {generatingStock === 'render' ? '⟳' : Icon.head(14)}
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                  )}
                </div>
                </div>

                {/* model actions under the portrait */}
                <div className="edit-modal-stock-strip">
                  <div className="edit-modal-stock-row">
                    <ActionButton icon={Icon.cube} label="View 3D Model" onClick={onView3D} disabled={locked} />
                    {onStartSkinCreator && (
                      <ActionButton icon={Icon.pencil(20)} label="Edit Textures" className="edit-modal-tile edit-modal-tile--accent"
                        onClick={() => onStartSkinCreator(d)} disabled={locked} />
                    )}
                    {onTestInGame && (
                      <ActionButton icon={Icon.gamepad} label="Test in Game"
                        onClick={onTestInGame} disabled={anyBusy}
                        title="Build a one-costume test ISO and play a short match to verify it loads" />
                    )}
                  </div>
                </div>
              </div>

            </>
          ) : (
            <>
              {/* stage preview, hover to replace */}
              <div className="edit-modal-csp-section">
                <div className="edit-modal-media">
                <div className="edit-modal-csp-stage">
                <div className="edit-modal-csp-container" style={{ '--panel-aspect': panelAspect || (4 / 3) }}>
                  {d.hasScreenshot ? (
                    <img src={`${toAbsUrl(d.screenshotUrl)}?t=${lastImageUpdate}`} alt="Preview"
                      className="edit-modal-csp-image" onLoad={handleHeroImageLoad}
                      onError={(e) => e.target.style.display = 'none'} />
                  ) : (
                    <div className="edit-modal-csp-placeholder"><span>{(d.name || '?')[0]}</span></div>
                  )}
                  <input ref={screenshotInputRef} type="file" accept="image/*" style={{ display: 'none' }}
                    onChange={(e) => pickFile(e, onReplaceScreenshot)} />
                  {d.hasScreenshot && (
                    <div className="edit-modal-hover-actions edit-modal-hover-actions--top">
                      <button className="edit-modal-image-edit-btn"
                        onClick={() => exportImage(toAbsUrl(d.screenshotUrl), [d.stageName, d.name])}
                        title="Save this screenshot out as an image file">
                        {Icon.download(20)}<span>Export Screenshot</span>
                      </button>
                    </div>
                  )}
                  <div className="edit-modal-hover-actions">
                    <button className="edit-modal-image-edit-btn" onClick={() => screenshotInputRef.current?.click()}
                      disabled={anyBusy} title="Replace the preview with an image (applies immediately)">
                      {Icon.pencil(20)}<span>Replace Screenshot</span>
                    </button>
                  </div>
                </div>
                </div>
                </div>

                {/* stage actions under the preview */}
                <div className="edit-modal-stock-strip">
                  <div className="edit-modal-stock-row">
                    {onStartSkinCreator && (
                      <ActionButton icon={Icon.pencil(20)} label="Edit Textures" className="edit-modal-tile edit-modal-tile--accent"
                        onClick={() => onStartSkinCreator(d)} disabled={anyBusy} />
                    )}
                    {onTestInGame && (
                      <ActionButton icon={Icon.gamepad} label="Test in Game" onClick={onTestInGame} disabled={anyBusy}
                        title="Build a one-skin test ISO and play a short match (holds the DAS button) to verify it loads" />
                    )}
                    {onCaptureScreenshot && (
                      <ActionButton icon={Icon.camera} label="Capture Screenshot" onClick={onCaptureScreenshot} disabled={anyBusy}
                        title="Boot the stage alone in a throwaway Dolphin and grab a clean whole-stage screenshot to use as the preview" />
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer: only the two non-form actions */}
        <div className="edit-modal-actions edit-modal-actions--end">
          {isCostume && (
            /* Slippi verdict: click to expand Retest + override to the right */
                  <div className={`edit-modal-slippi-badge edit-modal-slippi-card ${d.slippi_safe ? 'edit-modal-slippi-badge--safe' : 'edit-modal-slippi-badge--unsafe'}${safetyOpen ? ' is-open' : ''}`}>
                    <button
                      type="button"
                      className="edit-modal-slippi-toggle-btn"
                      onClick={() => { playSound('boop'); setSafetyOpen((o) => !o) }}
                      aria-expanded={safetyOpen}
                      title={safetyOpen ? 'Hide safety options' : 'Retest or override the verdict'}
                    >
                      <div className="edit-modal-slippi-indicator"></div>
                      <span>{d.slippi_safe ? 'Slippi Safe' : 'Not Slippi Safe'}</span>
                      {d.slippi_manual_override && <span className="edit-modal-slippi-override">(Override)</span>}
                      <span className="edit-modal-slippi-chevron" aria-hidden="true">▾</span>
                    </button>
                  {safetyOpen && (
                  <div className="edit-modal-slippi-row">
                    {onSlippiRetest && (
                      <button className="edit-modal-slippi-retest-btn" onClick={() => onSlippiRetest(false)}
                        disabled={locked || safetyBusy} title="Run the netplay-safety check again">
                        {Icon.refresh} Retest
                      </button>
                    )}
                    {onSlippiOverride && (
                      <button className="edit-modal-slippi-retest-btn" onClick={() => onSlippiOverride(!d.slippi_safe)}
                        disabled={locked || safetyBusy}
                        title="Force the verdict by hand (marked as an override)">
                        {d.slippi_safe ? 'Mark as Not Safe' : 'Mark as Safe'}
                      </button>
                    )}
                  </div>
                  )}
                  </div>
          )}
          {!isCostume && (
            <div className={`edit-modal-slippi-badge edit-modal-slippi-card ${d.slippi_safe === true ? 'edit-modal-slippi-badge--safe' : d.slippi_safe === false ? 'edit-modal-slippi-badge--unsafe' : 'edit-modal-slippi-badge--unknown'}${safetyOpen ? ' is-open' : ''}`}>
              <button
                type="button"
                className="edit-modal-slippi-toggle-btn"
                onClick={() => { playSound('boop'); setSafetyOpen((o) => !o) }}
                aria-expanded={safetyOpen}
                title="Set the netplay-safety status by hand"
              >
                <div className="edit-modal-slippi-indicator"></div>
                <span>{d.slippi_safe === true ? 'Slippi Safe' : d.slippi_safe === false ? 'Not Slippi Safe' : 'Safety Unknown'}</span>
                <span className="edit-modal-slippi-chevron" aria-hidden="true">▾</span>
              </button>
              {safetyOpen && (
                <div className="edit-modal-slippi-row">
                  <div className="edit-modal-segmented" role="radiogroup" aria-label="Slippi safety">
                    {[[null, 'Unknown'], [true, 'Safe'], [false, 'Not Safe']].map(([value, label]) => (
                      <button key={label} type="button" role="radio"
                        aria-checked={d.slippi_safe === value}
                        className={`edit-modal-segmented-btn${d.slippi_safe === value ? ' edit-modal-segmented-btn--on' : ''}${value === true ? ' is-safe' : value === false ? ' is-unsafe' : ''}`}
                        onClick={() => onSetStageSafety?.(value)}
                        disabled={anyBusy}>
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          <button className="edit-modal-action-btn edit-modal-action-btn--export" onClick={onExport} disabled={locked || renaming}>
            {exporting ? <><span className="edit-modal-action-spinner"></span>Exporting...</> : <>{Icon.export}Export</>}
          </button>
          <button className="edit-modal-action-btn edit-modal-action-btn--delete" onClick={onDelete} disabled={locked || renaming}>
            {deleting ? <><span className="edit-modal-action-spinner"></span>Deleting...</> : <>{Icon.trash}Delete</>}
          </button>
        </div>

        {/* In-game test overlay (progress / result / error) */}
        {(testingInGame || testResult || testError) && (
          <div className="edit-modal-test-overlay">
            {/* The captured Dolphin video clips with this panel. Keep controls
                reachable in short windows; the preview uses remaining space. */}
            <div className={testingInGame ? 'edit-modal-test-panel edit-modal-test-panel--running' : 'edit-modal-test-panel'}>
              {testingInGame ? (
                <InGameTestRunning fill test={{ testStatus, testMode, testError,
                  stoppingTest, stopError, stopTest: onStopTest }} />
              ) : testError ? (
                <>
                  <p className="edit-modal-test-text" style={{ color: 'var(--color-error, #e74c3c)' }}>{testError}</p>
                  <button className="edit-modal-action-btn edit-modal-action-btn--cancel" onClick={onResetTest}>Close</button>
                </>
              ) : testResult ? (
                <>
                  <div className={`edit-modal-test-verdict ${testResult.success ? 'is-pass' : 'is-fail'}`}>
                    {testResult.captured ? '✓ CAPTURED' : testResult.interactive ? (testResult.success ? 'Session ended' : 'Session failed') : testResult.success ? '✓ PASS' : `✕ ${String(testResult.verdict || '').toUpperCase()}`}
                  </div>
                  <p className="edit-modal-test-text">{testResult.reason}</p>
                  {testResult.screenshot && (
                    <img src={backendMediaUrl(testResult.screenshot)} alt="In-game screenshot" className="edit-modal-test-shot" />
                  )}
                  <div className="edit-modal-test-actions">
                    {testResult.captured ? (
                      <>
                        <button className="edit-modal-action-btn edit-modal-action-btn--export"
                          onClick={() => onReplaceWithCapture && onReplaceWithCapture(testResult.screenshot)}>
                          Replace Current Screenshot
                        </button>
                        <button className="edit-modal-action-btn edit-modal-action-btn--cancel" onClick={onCaptureScreenshot}>Retake</button>
                        <button className="edit-modal-action-btn edit-modal-action-btn--cancel" onClick={onResetTest}>Discard</button>
                      </>
                    ) : (
                      <>
                        <button className="edit-modal-action-btn edit-modal-action-btn--export" onClick={onTestInGame}>Test again</button>
                        <button className="edit-modal-action-btn edit-modal-action-btn--cancel" onClick={onResetTest}>Close</button>
                      </>
                    )}
                  </div>
                </>
              ) : null}
            </div>
          </div>
        )}
      </div>
    </div>
  )

  const portalTarget = getAppContentPortalTarget()
  return portalTarget ? createPortal(modal, portalTarget) : modal
}
