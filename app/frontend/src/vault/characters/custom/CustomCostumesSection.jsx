import TeamColorTokens, { TeamColorBadges } from './TeamColorTokens'
import { backendMediaUrl } from '../../../shared/config/config.js'
import { playHoverSound, playSound } from '../../../shared/audio/sounds'
import { getCostumeTeamColors } from '../../lib/customCharacter'

// The character's installed costumes: team colors, rename, edit, reorder, and
// the drop zone that promotes a custom skin to a costume.
export default function CustomCostumesSection({
  costumes, draggingSkinId, costumesDropActive, setCostumesDropActive, handleSkinToCostume,
  detail, selectedTeamColor, handleTeamColorClick, draggingCostume, costumeDragOverId,
  renamingCostume, handleCostumeTeamAssign, setDraggingCostume, setSkinDropActive, setCostumeDragOverId,
  handleCostumeReorder, cspManager, openCostumeEditor, setRenamingCostume, saveCostumeRename,
}) {
  return (
    <div
      className={`custom-char-costumes custom-costume-dropzone${draggingSkinId != null ? ' promote-ready' : ''}${costumesDropActive ? ' promote-active' : ''}`}
      onDragOver={(e) => {
        if (draggingSkinId != null) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy' }
      }}
      onDragEnter={(e) => {
        if (draggingSkinId != null) { e.preventDefault(); setCostumesDropActive(true) }
      }}
      onDragLeave={(e) => {
        if (e.currentTarget.contains(e.relatedTarget)) return
        setCostumesDropActive(false)
      }}
      onDrop={(e) => {
        if (draggingSkinId != null) { e.preventDefault(); handleSkinToCostume(draggingSkinId) }
      }}
    >
      <div className="custom-char-section-header">
        <h3 className="custom-char-section-title">Costumes</h3>
        <TeamColorTokens
          teamColors={detail?.team_colors}
          costumeCount={costumes.length}
          selected={selectedTeamColor}
          onSelect={handleTeamColorClick}
        />
      </div>
      <div className="custom-char-costume-grid">
        {costumes.map((costume) => (
          <div
            key={costume.index}
            className={`custom-char-costume-card${draggingCostume === costume.index ? ' dragging' : ''}${costumeDragOverId === costume.edit_id ? ' drop-before' : ''}${selectedTeamColor ? ' team-assignable' : ''}`}
            draggable={costumes.length > 1 && renamingCostume?.index !== costume.index && !selectedTeamColor}
            onClick={selectedTeamColor ? () => handleCostumeTeamAssign(costume.index) : undefined}
            onDragStart={(e) => {
              e.dataTransfer.effectAllowed = 'move'
              // suppress the global "Drop to import" overlay for this in-app drag
              document.documentElement.dataset.nucInternalDrag = '1'
              setDraggingCostume(costume.index)
            }}
            onDragEnd={() => {
              delete document.documentElement.dataset.nucInternalDrag
              setDraggingCostume(null); setSkinDropActive(false); setCostumeDragOverId(null)
            }}
            onDragOver={(e) => {
              if (draggingCostume != null && draggingCostume !== costume.index) {
                e.preventDefault(); e.dataTransfer.dropEffect = 'move'
                if (costumeDragOverId !== costume.edit_id) setCostumeDragOverId(costume.edit_id)
              }
            }}
            onDrop={(e) => {
              if (draggingCostume != null && draggingCostume !== costume.index) {
                e.preventDefault(); e.stopPropagation()
                handleCostumeReorder(draggingCostume, costume)
              }
            }}
            title={selectedTeamColor
              ? `Set as the ${selectedTeamColor} team costume`
              : costumes.length > 1 ? 'Drag onto another costume to reorder, or down into Custom Skins' : undefined}
          >
            {costume.csp_url ? (
              <img
                src={backendMediaUrl(`${costume.csp_url}?t=${cspManager.lastImageUpdate}`)}
                alt={costume.name}
                draggable={false}
                className="custom-char-csp"
              />
            ) : (
              <div className="custom-char-csp-placeholder">
                {costume.name[0]}
              </div>
            )}
            {costume.edit_id && (
              <button
                className="costume-edit-btn"
                onMouseEnter={playHoverSound}
                onClick={(e) => { e.stopPropagation(); playSound('boop'); openCostumeEditor(costume) }}
                title="Edit costume"
              >
                ✎
              </button>
            )}
            <TeamColorBadges
              teams={costumes.length > 1 ? getCostumeTeamColors(detail?.team_colors, costume.index) : []}
            />
            <div className="custom-char-costume-info">
              {costume.stock_url && (
                <img
                  src={backendMediaUrl(costume.stock_url)}
                  alt="stock"
                  className="custom-char-stock"
                />
              )}
              {renamingCostume?.index === costume.index ? (
                <input
                  className="costume-name-input"
                  value={renamingCostume.value}
                  onChange={(e) => setRenamingCostume({ index: costume.index, value: e.target.value })}
                  onBlur={saveCostumeRename}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') saveCostumeRename()
                    if (e.key === 'Escape') setRenamingCostume(null)
                  }}
                  autoFocus
                  onClick={(e) => e.stopPropagation()}
                />
              ) : (
                <span
                  className="custom-char-costume-name editable"
                  title={`${costume.dat || ''} — click to rename`}
                  onClick={() => {
                    if (selectedTeamColor) return  // card click assigns the team instead
                    playSound('boop'); setRenamingCostume({ index: costume.index, value: costume.name })
                  }}
                >
                  {costume.name}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
