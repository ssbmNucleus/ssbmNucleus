import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { backendMediaUrl } from '../../shared/config/config'
import HexagonLoader from '../../shared/ui/HexagonLoader'

// Costume selection step: pick a vanilla costume as the starting point.
export default function CostumeSelectStep({
  initialCostume,
  onBack,
  vanillaCostumes,
  selectedCharacter,
  loading,
  error,
  reconnecting,
  reconnectAttempts,
  maxReconnectAttempts,
  onSelectCostume
}) {
  return (
    <div className="skin-creator-select">
      {initialCostume ? (
        <>
          <div className="skin-creator-loading-edit">
            <button
              className="back-button"
              onMouseEnter={playHoverSound}
              onClick={onBack}
            >
              &larr; Back
            </button>
            {error && error !== 'closing' ? (
              <div className="skin-creator-error">{error}</div>
            ) : (
              <div className="skin-creator-loading-card">
                <HexagonLoader size={88} label="Loading skin editor" className="skin-creator-loading-hex" />
                <h3>Loading skin editor</h3>
                <p>{selectedCharacter ? `Opening ${selectedCharacter} in the 3D viewer…` : 'Opening the 3D viewer…'}</p>
              </div>
            )}
          </div>
        </>
      ) : (
      <div className="skin-creator-select-scroll">
        {/* Mirror the vault grid pages (CharacterDetailView / ExtrasPageView):
            centered .character-detail shell, a .character-header with Back +
            title, and the standard .skins-grid of .skin-card portraits. */}
        <div className="storage-viewer">
          <div className="character-detail">
            <div className="character-header">
              <button
                className="back-button"
                onMouseEnter={playHoverSound}
                onClick={onBack}
              >
                ← Back
              </button>
              <div className="character-title-area">
                <h2 className="character-name">New Costume</h2>
                <span className="character-skin-count">
                  {selectedCharacter ? `${selectedCharacter} · choose a starting point` : 'Choose a starting point'}
                </span>
              </div>
            </div>

            {loading && (
              <div className="skin-creator-loading">
                <HexagonLoader size={40} decorative />
                <span>Loading costumes…</span>
              </div>
            )}

            {reconnecting && (
              <div className="skin-creator-reconnecting">
                Reconnecting... (attempt {reconnectAttempts}/{maxReconnectAttempts})
              </div>
            )}

            {error && error !== 'closing' && (
              <div className="skin-creator-error">{error}</div>
            )}

            <div className="skins-grid">
              {vanillaCostumes.map(costume => (
                <div
                  key={costume.code}
                  className="skin-card skin-creator-starter-card"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('start'); onSelectCostume(costume); }}
                >
                  <div className="skin-image-container">
                    {costume.hasCsp ? (
                      <img
                        className="skin-csp"
                        src={backendMediaUrl(`/vanilla/${selectedCharacter}/${costume.code}/csp.png`)}
                        alt={costume.colorName}
                      />
                    ) : (
                      <div className="skin-placeholder">
                        <span className="skin-initial">{costume.colorCode}</span>
                      </div>
                    )}
                  </div>
                  <div className="skin-info">
                    <span className="skin-color">{costume.colorName}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      )}
    </div>
  )
}
