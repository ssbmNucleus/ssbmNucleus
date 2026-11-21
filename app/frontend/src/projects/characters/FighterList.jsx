/**
 * FighterList - left panel of CharacterMode: mode toggle buttons,
 * playable fighter list, and the Add Character button.
 */
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { backendMediaUrl } from '../../shared/config/config'
import { MusicIcon } from '../../shared/ui/Icons'

export default function FighterList({
  mode,
  onModeChange,
  playableFighters,
  selectedFighter,
  onSelectFighter,
  getCostumesForFighter,
  onRemoveFighter,
  onAddCharacter,
  onOpenMenuMusic
}) {
  return (
    <div className="fighters-list">
      <div className="fighters-header">
        <div className="mode-toggle">
          <button
            className={`mode-toggle-btn ${mode === 'characters' ? 'active' : ''}`}
            onMouseEnter={playHoverSound}
            onClick={() => { if (mode !== 'characters') { playSound('boop'); onModeChange('characters'); } }}
          >
            Fighters
          </button>
          <button
            className={`mode-toggle-btn ${mode === 'stages' ? 'active' : ''}`}
            onMouseEnter={playHoverSound}
            onClick={() => { if (mode !== 'stages') { playSound('boop'); onModeChange('stages'); } }}
          >
            Stages
          </button>
          <button
            className={`mode-toggle-btn ${mode === 'menus' ? 'active' : ''}`}
            onMouseEnter={playHoverSound}
            onClick={() => { if (mode !== 'menus') { playSound('boop'); onModeChange('menus'); } }}
          >
            Menus
          </button>
          <button
            className="mode-music-btn"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); onOpenMenuMusic(); }}
            title="Edit menu music"
            aria-label="Edit menu music"
          >
            <MusicIcon size={14} />
          </button>
        </div>
        <span className="fighters-count">
          {playableFighters.length - (playableFighters.some(f => f.name === 'Sheik') ? 1 : 0)}
        </span>
      </div>
      <div className="fighter-items">
        {(() => {
          // Zelda and Sheik share one in-game slot pairing (and one combined
          // costumes panel), so the list shows them as a SINGLE entry with a
          // split stock icon. Sheik's own row is dropped; the Zelda row becomes
          // "Zelda / Sheik" and carries both fighters' counts.
          const sheikFighter = playableFighters.find(f => f.name === 'Sheik')
          const displayFighters = sheikFighter
            ? playableFighters.filter(f => f.name !== 'Sheik')
            : playableFighters
          return displayFighters.map(fighter => {
            const isZeldaCombo = !!sheikFighter && fighter.name === 'Zelda'
            const availableCostumes = isZeldaCombo
              ? [...getCostumesForFighter('Zelda'), ...getCostumesForFighter('Sheik')]
              : getCostumesForFighter(fighter.name)
            const isSelected = selectedFighter?.internalId === fighter.internalId ||
              (isZeldaCombo && selectedFighter?.internalId === sheikFighter.internalId)
            return (
              <div
                key={fighter.internalId}
                className={`fighter-item ${isSelected ? 'selected' : ''}`}
                onMouseEnter={playHoverSound}
                onClick={() => { playSound('boop'); onSelectFighter(fighter); }}
              >
                {isZeldaCombo && fighter.defaultStockUrl && sheikFighter.defaultStockUrl ? (
                  <div className="fighter-stock-icon zs-combo-stock">
                    <img
                      src={backendMediaUrl(fighter.defaultStockUrl)}
                      alt=""
                      className="zs-stock-zelda"
                      onError={(e) => e.target.style.display = 'none'}
                    />
                    <img
                      src={backendMediaUrl(sheikFighter.defaultStockUrl)}
                      alt=""
                      className="zs-stock-sheik"
                      onError={(e) => e.target.style.display = 'none'}
                    />
                  </div>
                ) : fighter.defaultStockUrl && (
                  <img
                    src={backendMediaUrl(fighter.defaultStockUrl)}
                    alt=""
                    className="fighter-stock-icon"
                    onError={(e) => e.target.style.display = 'none'}
                  />
                )}
                <div className="fighter-content">
                  <div className="fighter-name">{isZeldaCombo ? 'Zelda / Sheik' : fighter.name}</div>
                  <div className="fighter-info">
                    <span className="costume-count">
                      {isZeldaCombo
                        ? `${fighter.costumeCount}+${sheikFighter.costumeCount} in MEX`
                        : `${fighter.costumeCount} in MEX`}
                    </span>
                    {isZeldaCombo && fighter.costumeCount !== sheikFighter.costumeCount && (
                      <span
                        className="zs-mismatch zs-mismatch-mini"
                        title="Zelda and Sheik have different costume counts — unpaired slots transform to the default costume (safe, no crash)."
                      >
                        ⚠
                      </span>
                    )}
                    {availableCostumes.length > 0 && (
                      <span className="available-count">{availableCostumes.length} available</span>
                    )}
                  </div>
                </div>
                {fighter.isMexFighter && (
                  <button
                    className="fighter-remove-btn"
                    title={`Remove ${fighter.name}`}
                    onClick={(e) => { e.stopPropagation(); onRemoveFighter(fighter.name); }}
                  >
                    ×
                  </button>
                )}
              </div>
            )
          })
        })()}
        <button
          className="add-character-btn"
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('boop'); onAddCharacter(); }}
        >
          + Add Character
        </button>
      </div>
    </div>
  )
}
