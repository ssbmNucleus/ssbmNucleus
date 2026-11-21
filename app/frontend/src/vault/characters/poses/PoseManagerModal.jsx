import { useContext, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { VaultActiveContext } from '../../vaultActive.js'
import { isTextEntry, poseManagerEscape } from './poseModalKeys.js'
import EmbeddedModelViewer from '../../../shared/viewer/EmbeddedModelViewer'
import PoseSkinSelectorModal from './PoseSkinSelectorModal'
import { getAppContentPortalTarget } from '../../../shared/ui/appContentPortal'
import { CloseIcon } from '../../../shared/ui/Icons'
import { getDefaultCostumeCode } from './animData'
import useViewerAnimations from './useViewerAnimations'
import usePoseLibrary from './usePoseLibrary'
import CategoryBar from './CategoryBar'
import AnimationListPanel from './AnimationListPanel'
import PoseCard from './PoseCard'
import BasePoseCard, { DEFAULT_POSE_NAME, DEFAULT_POSE_LABEL } from './BasePoseCard'
import SavePoseControls from './SavePoseControls'
import { POSE_MANAGER_STYLES } from './poseManagerStyles'
import { playSound } from '../../../shared/audio/sounds'
import { API_URL } from '../../../shared/config/config.js'
import { api } from '../../../shared/transport/api'

/**
 * Pose Manager Modal - two views:
 *
 * Library (default): grid of saved poses. Click one to batch-render portraits
 * with it (PoseSkinSelectorModal), or hit "Create New Pose". Lightweight - the
 * native 3D viewer is NOT loaded here.
 *
 * Create: embedded 3D viewer + animation browser + save controls. The viewer
 * only mounts in this view; saving a pose returns to the library.
 *
 * Escape closes the innermost layer: Generate CSPs, the model menu, Create back
 * to the library, then the modal (poseModalKeys.js). Both modals are portaled
 * into .app-content, so they hide while their page is not on screen
 * (VaultActiveContext: the Vault, or the Install tab for apply-to-all) and are
 * still open on return.
 */
export default function PoseManagerModal({
  show,
  character,
  // Custom characters: `character` is a pseudo key
  // ('custom_characters/<slug>/costumes'); pass their display name and the
  // base costume id so the create-view viewer can load the model from the
  // vault instead of a vanilla costume code.
  displayName,
  baseSkinId,
  // Optional list of models to choose from in the create view:
  // [{ value, label, skinId? , costumeCode? }]. Falls back to baseSkinId /
  // the default costume code when omitted.
  models,
  // A model's `value` to open straight into the create view on (the costume
  // menu's "New pose with this model"); null opens on the library as usual.
  createWith = null,
  onClose,
  onRefresh,
  onCostumesUpdated,
  // When set, clicking a library pose calls this instead of opening the
  // batch skin selector (used by the install page's apply-to-all flow)
  onSelectPose,
  defaultPoseName = '',
  onSetDefaultPose,
  settingDefaultPose = false
}) {
  const viewerRef = useRef(null)
  const modelMenuRef = useRef(null)
  const [mode, setMode] = useState('library') // 'library' | 'create'
  // Which model the create-view viewer loads (#2). null => default/baseSkinId.
  const [selectedModelValue, setSelectedModelValue] = useState(null)
  const [showModelMenu, setShowModelMenu] = useState(false)
  // "Start from existing pose" (#3): {sceneFile, animSymbol, frame, poseName}.
  const [startFrom, setStartFrom] = useState(null)

  const modelList = Array.isArray(models) ? models : []
  const selectedModel =
    modelList.find(m => m.value === selectedModelValue) ||
    modelList.find(m => m.skinId && m.skinId === baseSkinId) ||
    modelList[0] || null
  const BACKEND_BASE = API_URL.replace('/api/mex', '')
  const modelAssetUrl = (url) => {
    if (!url) return null
    return /^https?:\/\//.test(url) ? url : `${BACKEND_BASE}${url}`
  }
  const handleSelectModel = (value) => {
    playSound('boop')
    setSelectedModelValue(value)
    setShowModelMenu(false)
  }

  // Fetch a saved pose's viewer scene file + animation, then open the create
  // view starting from it.
  const startFromPose = async (pose) => {
    try {
      const data = await api.get(
        `/storage/poses/scene-file/${encodeURIComponent(character)}/${encodeURIComponent(pose.name)}`)
      setStartFrom({ sceneFile: data.sceneFile, animSymbol: data.animSymbol,
                     frame: data.frame, poseName: pose.name })
      playSound('start')
      setMode('create')
    } catch (err) {
      console.error('[PoseManager] start-from-pose error:', err)
    }
  }

  // Viewer coordination: animation list polling + load-animation calls
  // (only active while the create view has the viewer mounted)
  const animations = useViewerAnimations({ show: show && mode === 'create', viewerRef })

  // Pose list management + save/delete API calls
  const poseLibrary = usePoseLibrary({ show, character, viewerRef })

  const {
    poses,
    loadingPoses,
    selectedPose,
    setSelectedPose,
    handleDeletePose,
    saveSuccess
  } = poseLibrary

  // Open on the library view, or on the create view with the model asked for
  useEffect(() => {
    if (show) { setMode(createWith ? 'create' : 'library'); setStartFrom(null); setSelectedModelValue(createWith || null) }
  }, [show, createWith])

  useEffect(() => {
    if (!showModelMenu) return
    const handlePointerDown = (event) => {
      if (modelMenuRef.current?.contains(event.target)) return
      setShowModelMenu(false)
    }
    document.addEventListener('pointerdown', handlePointerDown)
    return () => document.removeEventListener('pointerdown', handlePointerDown)
  }, [showModelMenu])

  useEffect(() => {
    if (!show || mode !== 'create') setShowModelMenu(false)
  }, [show, mode])

  // A successful save returns to the library, where the new pose now shows
  useEffect(() => {
    if (saveSuccess) { setMode('library'); setStartFrom(null) }
  }, [saveSuccess])

  const hidden = !useContext(VaultActiveContext)   // another page is on screen: kept, not shown, deaf to Escape
  const skinSelectorOpen = selectedPose !== null   // Generate CSPs answers Escape itself
  useEffect(() => {
    if (!show) return undefined
    const onKey = (e) => {
      const action = poseManagerEscape({ key: e.key, defaultPrevented: e.defaultPrevented, hidden, skinSelectorOpen,
        modelMenuOpen: showModelMenu, creating: mode === 'create', typing: isTextEntry(e.target) })
      if (!action) return
      e.preventDefault()   // a modal underneath (the vault's edit modal) must not also close
      if (action === 'menu') { setShowModelMenu(false); return }
      playSound('back')
      if (action === 'library') setMode('library')
      else onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [show, hidden, skinSelectorOpen, showModelMenu, mode, onClose])

  if (!show) return null

  const isCreating = mode === 'create'
  const canEditDefaultPose = typeof onSetDefaultPose === 'function'

  // The built-in pose is shown as a regular card using the base costume's
  // portrait: the shipped vanilla CSP, or a custom character's base costume.
  const defaultCostumeCode = getDefaultCostumeCode(character)
  const baseModel =
    modelList.find(m => m.skinId && m.skinId === baseSkinId && (m.cspUrl || m.csp_url)) ||
    modelList.find(m => m.cspUrl || m.csp_url)
  const basePoseThumbnail = defaultCostumeCode
    ? `${BACKEND_BASE}/vanilla/${encodeURIComponent(character)}/${defaultCostumeCode}/csp.png`
    : modelAssetUrl(baseModel?.cspUrl || baseModel?.csp_url)
  const handleBasePoseClick = () => {
    playSound('boop')
    if (onSelectPose) { onSelectPose({ name: '__original__', isOriginal: true }); return }
    setSelectedPose({ name: DEFAULT_POSE_NAME, label: DEFAULT_POSE_LABEL, previewUrl: basePoseThumbnail })
  }

  const handleSetDefaultPose = async (pose) => {
    if (!canEditDefaultPose || settingDefaultPose || !pose?.name || pose.name === defaultPoseName) return
    try {
      await onSetDefaultPose(pose.name)
    } catch (err) {
      console.error('[PoseManager] set-default-pose error:', err)
    }
  }

  const modal = (
    <div className="pm-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}
      style={hidden ? { display: 'none' } : undefined}>
      <div className={`pm-modal ${isCreating ? 'pm-modal--create' : 'pm-modal--library'}`}>
        {/* Header */}
        <div className="pm-header">
          <div className="pm-title">
            {isCreating && (
              <button
                className="pm-back-btn"
                onClick={() => { playSound('back'); setMode('library'); }}
              >
                ← Poses
              </button>
            )}
            <span className="pm-title-label">{isCreating ? 'Create Pose' : 'Poses'}</span>
            <span className="pm-title-char">{displayName || character}</span>
          </div>
          <button className="pm-close-btn" onClick={onClose}>
            <CloseIcon />
          </button>
        </div>

        {isCreating ? (
          <>
            {/* Create view: viewer + animation browser */}
            <div className="pm-body">
              <div className="pm-left-section">
                {/* Model picker sits in a LEFT column because the native HSD
                    render window is an OS-topmost overlay over the viewport. */}
                <div className="pm-create-row">
                  {modelList.length > 1 && (
                    <div className="pm-model-select" ref={modelMenuRef}>
                      <label>Model</label>
                      <button
                        type="button"
                        className={`pm-model-menu-btn${showModelMenu ? ' active' : ''}`}
                        onClick={() => { playSound('boop'); setShowModelMenu(open => !open) }}
                        aria-haspopup="menu"
                        aria-expanded={showModelMenu}
                        title="Choose the model to pose"
                      >
                        {selectedModel?.label || 'Model'}
                      </button>
                      {showModelMenu && (
                        <div className="pm-model-popover" role="menu" aria-label="Model">
                          <div className="pm-model-grid">
                            {modelList.map(model => {
                              const cspUrl = modelAssetUrl(model.cspUrl || model.csp_url)
                              const stockUrl = modelAssetUrl(model.stockUrl || model.stock_url)
                              return (
                                <button
                                  key={model.value}
                                  type="button"
                                  className={`pm-model-card${model.value === selectedModel?.value ? ' active' : ''}`}
                                  onClick={() => handleSelectModel(model.value)}
                                  role="menuitem"
                                  title={model.label}
                                >
                                  <div className="pm-model-card-image">
                                    {cspUrl ? (
                                      <img src={cspUrl} alt={model.label} draggable={false} />
                                    ) : (
                                      <span>{(model.label || 'M').charAt(0).toUpperCase()}</span>
                                    )}
                                  </div>
                                  <div className="pm-model-card-info">
                                    {stockUrl && (
                                      <img
                                        src={stockUrl}
                                        alt=""
                                        className="pm-model-stock"
                                        draggable={false}
                                      />
                                    )}
                                    <span>{model.label}</span>
                                  </div>
                                </button>
                              )
                            })}
                          </div>
                        </div>
                      )}
                      {startFrom && (
                        <span className="pm-startfrom-tag">from “{startFrom.poseName}”</span>
                      )}
                    </div>
                  )}
                  <div className="pm-viewer-section">
                    <EmbeddedModelViewer
                      key={`${selectedModel?.value || baseSkinId || 'default'}|${startFrom?.poseName || 'new'}`}
                      ref={viewerRef}
                      character={character}
                      skinId={selectedModel ? (selectedModel.skinId || undefined) : (baseSkinId || undefined)}
                      costumeCode={selectedModel
                        ? (selectedModel.skinId ? undefined : selectedModel.costumeCode)
                        : (baseSkinId ? undefined : getDefaultCostumeCode(character))}
                      overrideSceneFile={startFrom?.sceneFile || null}
                      startAnimSymbol={startFrom?.animSymbol || null}
                      startFrame={startFrom?.frame || 0}
                      onClose={onClose}
                      inline={true}
                      cspMode={true}
                      showGrid={false}
                      showBackground={false}
                    />
                  </div>
                </div>

                {/* Category buttons below viewer */}
                <CategoryBar animations={animations} />
              </div>

              {animations.animList.length > 0 && (
                <AnimationListPanel animations={animations} />
              )}
            </div>

            {/* Save controls + status messages */}
            <SavePoseControls poseLibrary={poseLibrary} />
          </>
        ) : (
          /* Library view: saved poses grid + create card */
          <div className="pm-library">
            <div className="pm-library-hint">
              {onSelectPose
                ? 'Click a pose to apply it to all installed costumes, or create a new one.'
                : 'Click a pose to render portraits from it, or create a new one.'}
            </div>
            {saveSuccess && (
              <div className="pm-message pm-success">Pose saved!</div>
            )}
            <div className="pm-library-grid">
              <BasePoseCard
                thumbnailUrl={basePoseThumbnail}
                label={onSelectPose ? 'Original Portraits' : DEFAULT_POSE_LABEL}
                isDefault={canEditDefaultPose && !defaultPoseName}
                title={onSelectPose
                  ? "Put every installed costume's portrait back to its original CSP"
                  : 'Render portraits from the built-in game pose'}
                onClick={handleBasePoseClick}
              />
              {loadingPoses ? (
                <div className="pm-library-empty">Loading poses…</div>
              ) : (
                poses.map(pose => (
                  <PoseCard
                    key={pose.name}
                    pose={pose}
                    character={character}
                    onDelete={handleDeletePose}
                    onClick={() => {
                      if (onSelectPose) { onSelectPose(pose); return }
                      playSound('boop'); setSelectedPose(pose)
                    }}
                    onStartFrom={startFromPose}
                    defaultPoseName={defaultPoseName}
                    onSetDefaultPose={canEditDefaultPose ? handleSetDefaultPose : null}
                    settingDefaultPose={settingDefaultPose}
                  />
                ))
              )}
              {/* The next empty slot is where a new pose goes */}
              <div
                className="pm-pose-card pm-create-card"
                onClick={() => { playSound('start'); setStartFrom(null); setMode('create'); }}
              >
                <div className="pm-pose-image pm-create-image">
                  <span className="pm-create-icon">+</span>
                </div>
                <div className="pm-pose-name">Create New Pose</div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Skin Selector Modal for batch CSP generation (opens from the library) */}
      <PoseSkinSelectorModal
        show={selectedPose !== null}
        character={character}
        poseName={selectedPose?.name}
        poseLabel={selectedPose?.label}
        poseThumbnail={selectedPose?.previewUrl
          || (selectedPose?.hasThumbnail ? `${API_URL.replace('/api/mex', '')}${selectedPose.thumbnailUrl}` : null)}
        onClose={() => setSelectedPose(null)}
        onRefresh={onRefresh}
        onCostumesUpdated={onCostumesUpdated}
      />

      <style>{POSE_MANAGER_STYLES}</style>
    </div>
  )

  const portalTarget = getAppContentPortalTarget()
  return portalTarget ? createPortal(modal, portalTarget) : modal
}
