import BaseSkinPicker from './BaseSkinPicker'
import { backendMediaUrl } from '../../../shared/config/config.js'
import { playHoverSound, playSound } from '../../../shared/audio/sounds'

// The character's custom skins: the drop zone for costumes, import, base-skin
// picker, and the skin cards.
export default function CustomSkinsSection({
  draggingCostume, skinDropActive, setSkinDropActive, handleCostumeToSkin, character,
  baseCharacter, BACKEND_BASE, fetchDetail, flashSkinMessage, addedSkins,
  draggingSkinId, skinDragOverId, setDraggingSkinId, setSkinDragOverId, handleSkinReorder,
  cspManager, openSkinEditor, importingSkin, skinFileRef, handleImportSkin,
  skinMessage,
}) {
  return (
    <div
      className={`custom-char-costumes custom-skin-dropzone${draggingCostume != null ? ' drop-ready' : ''}${skinDropActive ? ' drop-active' : ''}`}
      onDragOver={(e) => {
        if (draggingCostume != null) { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }
      }}
      onDragEnter={(e) => {
        if (draggingCostume != null) { e.preventDefault(); setSkinDropActive(true) }
      }}
      onDragLeave={(e) => {
        if (e.currentTarget.contains(e.relatedTarget)) return
        setSkinDropActive(false)
      }}
      onDrop={(e) => { e.preventDefault(); handleCostumeToSkin(draggingCostume) }}
    >
      <div className="custom-char-section-header custom-skin-section-header">
        <h3 className="custom-char-section-title">Custom Skins</h3>
        <BaseSkinPicker
          slug={character.slug}
          baseCharacter={baseCharacter}
          backendBase={BACKEND_BASE}
          onRefresh={fetchDetail}
          flashMessage={flashSkinMessage}
        />
      </div>
      {addedSkins.length === 0 && (
        <p className="custom-char-section-hint">
          Add extra skins for this character — import a costume zip/dat, drag a
          costume from above down here to make it removable, or drag a skin from
          a vanilla character&apos;s page onto this character.
        </p>
      )}
      <div className="custom-char-costume-grid">
        {addedSkins.map((skin) => (
          <div
            key={skin.id}
            className={`custom-char-costume-card${draggingSkinId === skin.id ? ' dragging' : ''}${skinDragOverId === skin.id ? ' drop-before' : ''}`}
            draggable={addedSkins.length > 1}
            onDragStart={(e) => {
              e.dataTransfer.effectAllowed = 'move'
              document.documentElement.dataset.nucInternalDrag = '1'
              setDraggingSkinId(skin.id)
            }}
            onDragEnd={() => {
              delete document.documentElement.dataset.nucInternalDrag
              setDraggingSkinId(null); setSkinDragOverId(null)
            }}
            onDragOver={(e) => {
              if (draggingSkinId && draggingSkinId !== skin.id) {
                e.preventDefault(); e.dataTransfer.dropEffect = 'move'
                if (skinDragOverId !== skin.id) setSkinDragOverId(skin.id)
              }
            }}
            onDrop={(e) => {
              if (draggingSkinId && draggingSkinId !== skin.id) {
                e.preventDefault(); e.stopPropagation()
                handleSkinReorder(draggingSkinId, skin.id)
              }
            }}
          >
            {skin.csp_url ? (
              <img
                src={backendMediaUrl(`${skin.csp_url}?t=${cspManager.lastImageUpdate}`)}
                alt={skin.name}
                draggable={false}
                className="custom-char-csp"
              />
            ) : (
              <div className="custom-char-csp-placeholder">
                {(skin.name || '?')[0]}
              </div>
            )}
            <button
              className="costume-edit-btn"
              onMouseEnter={playHoverSound}
              onClick={(e) => { e.stopPropagation(); playSound('boop'); openSkinEditor(skin) }}
              title="Edit skin"
            >
              ✎
            </button>
            <div className="custom-char-costume-info">
              {skin.stock_url && (
                <img
                  src={backendMediaUrl(skin.stock_url)}
                  alt="stock"
                  className="custom-char-stock"
                />
              )}
              <span className="custom-char-costume-name" title={skin.name}>{skin.name}</span>
            </div>
          </div>
        ))}
        <div
          className="custom-char-costume-card custom-skin-add-card"
          onMouseEnter={playHoverSound}
          onClick={() => { if (!importingSkin) { playSound('boop'); skinFileRef.current?.click() } }}
          title="Import a costume .zip or .dat as a custom skin"
        >
          <div className="custom-char-csp-placeholder">+</div>
          <div className="custom-char-costume-info">
            <span className="custom-char-costume-name">
              {importingSkin ? 'Importing...' : 'Add Skin'}
            </span>
          </div>
        </div>
      </div>
      <input
        ref={skinFileRef}
        type="file"
        accept=".zip,.dat,.usd"
        onChange={handleImportSkin}
        style={{ display: 'none' }}
      />
      {skinMessage && (
        <div className={`import-message ${skinMessage.includes('failed') || skinMessage.includes('error') ? 'error' : 'success'}`}>
          {skinMessage}
        </div>
      )}
    </div>
  )
}
