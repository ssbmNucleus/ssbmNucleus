/**
 * SkinCard - Individual costume card component
 *
 * Features:
 * - CSP image display with fallback
 * - Stock icon overlay
 * - Drag and drop support
 * - Context menu (right-click)
 * - Click or keyboard activation opens the editor
 */
import { useMemo, useRef, useEffect } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { API_URL, backendMediaUrl } from '../../shared/config/config.js'
import { createCardActivation } from '../cardActivation'

export default function SkinCard({
  skin,
  focusRequest,
  onFocused,
  selectedCharacter,
  folderId,
  displayIdx,
  arrayIdx,
  isDragging,
  isDropTarget,
  isJustDropped,
  reordering,
  canDrag = true,
  lastImageUpdate,
  onDragStart,
  onDragOver,
  onDragEnter,
  onDragLeave,
  onDrop,
  onDragEnd,
  onContextMenu,
  onEditClick,
  justDraggedRef,
}) {
  const activation = useMemo(() => createCardActivation(justDraggedRef), [justDraggedRef])
  const cardRef = useRef(null)


  // Get the CSP URL - use active alt CSP if one is selected
  const getCspUrl = () => {
    const baseUrl = API_URL.replace('/api/mex', '')
    if (skin.active_csp_id && skin.alternate_csps) {
      const activeAlt = skin.alternate_csps.find(alt => alt.id === skin.active_csp_id)
      if (activeAlt) {
        return `${baseUrl}/storage/${selectedCharacter}/${activeAlt.filename}`
      }
    }
    const cspFilename = skin.csp_filename || `${skin.id}_csp.png`
    return `${baseUrl}/storage/${selectedCharacter}/${cspFilename}`
  }

  const cspUrl = getCspUrl()

  const classNames = [
    'skin-card',
    isDragging && 'dragging',
    isDropTarget && 'drop-target',
    isJustDropped && 'just-dropped',
    folderId && 'in-folder'
  ].filter(Boolean).join(' ')

  const openEditor = () => {
    playSound('boop')
    onEditClick('costume', {
      id: skin.id,
      character: selectedCharacter,
      color: skin.color,
      has_csp: skin.has_csp,
      has_stock: skin.has_stock,
      cspUrl: `${API_URL.replace('/api/mex', '')}/storage/${selectedCharacter}/${skin.csp_filename || `${skin.id}_csp.png`}`,
      hdCspUrl: skin.has_hd_csp
        ? `${API_URL.replace('/api/mex', '')}/storage/${selectedCharacter}/${skin.hd_csp_filename || `${skin.id}_csp_hd.png`}`
        : null,
      stockUrl: skin.has_stock ? `${API_URL.replace('/api/mex', '')}/storage/${selectedCharacter}/${skin.id}_stc.png` : null,
      slippi_safe: skin.slippi_safe,
      slippi_tested: skin.slippi_tested,
      slippi_manual_override: skin.slippi_manual_override,
      has_hd_csp: skin.has_hd_csp,
      hd_csp_resolution: skin.hd_csp_resolution,
      hd_csp_size: skin.hd_csp_size,
      // Active CSP ID (null = original, otherwise points to an alt CSP)
      active_csp_id: skin.active_csp_id || null,
      // Alternate CSPs from batch pose generation (metadata uses snake_case)
      alternateCsps: (skin.alternate_csps || []).map(alt => ({
        id: alt.id,
        url: `${API_URL.replace('/api/mex', '')}/storage/${selectedCharacter}/${alt.filename}`,
        poseName: alt.pose_name,
        isHd: alt.is_hd,
        timestamp: alt.timestamp
      }))
    })
  }

  useEffect(() => {
    if (!focusRequest) return
    const frame = requestAnimationFrame(() => {
      cardRef.current?.scrollIntoView({ block: 'center', behavior: 'instant' })
      cardRef.current?.focus({ preventScroll: true })
      openEditor()
      onFocused?.()
    })
    return () => cancelAnimationFrame(frame)
  }, [focusRequest, onFocused, openEditor])

  const handleCardDragStart = (e) => {
    activation.onDragStart()
    onDragStart(e)
  }

  return (
    <div
      key={skin.id}
      ref={cardRef}
      className={classNames}
      role="button"
      aria-label={`Edit ${selectedCharacter} ${skin.color || skin.name || 'costume'}`}
      tabIndex={0}
      draggable={!reordering && canDrag}
      onMouseEnter={playHoverSound}
      onPointerDown={activation.onPointerDown}
      onPointerMove={activation.onPointerMove}
      onPointerCancel={activation.onPointerCancel}
      onClick={(e) => activation.onClick(e, openEditor)}
      onKeyDown={(e) => activation.onKeyDown(e, openEditor)}
      onDragStart={handleCardDragStart}
      onDragOver={onDragOver}
      onDragEnter={onDragEnter}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
      onContextMenu={onContextMenu ? (e) => onContextMenu(e, skin, arrayIdx) : undefined}
    >
      <div className="skin-image-container">
        {skin.has_csp ? (
          <img
            src={`${cspUrl}?t=${lastImageUpdate}`}
            alt={`${selectedCharacter} - ${skin.color}`}
            className="skin-csp"
            onError={(e) => {
              e.target.style.display = 'none'
              e.target.nextSibling.style.display = 'flex'
            }}
          />
        ) : null}
        <div className="skin-placeholder" style={{ display: skin.has_csp ? 'none' : 'flex' }}>
          <span className="skin-initial">{(skin.color || skin.name || '?')[0]}</span>
        </div>
        {skin.has_stock && (
          <div className="stock-overlay">
            <img
              src={backendMediaUrl(`/storage/${selectedCharacter}/${skin.id}_stc.png?t=${lastImageUpdate}`)}
              alt={`${selectedCharacter} stock`}
              className="stock-overlay-img"
            />
          </div>
        )}
      </div>
    </div>
  )
}
