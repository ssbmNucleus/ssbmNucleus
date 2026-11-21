import { playHoverSound, playSound } from '../../../shared/audio/sounds'
import { CharacterFranchiseLine } from './CharacterSeriesSection'
import { backendMediaUrl } from '../../../shared/config/config.js'

// Header of a custom character's page: editable icon, name and franchise,
// and the result-screen banner.
export default function CustomCharacterHeader({
  iconFileRef, iconUrl, character, handleReplaceAsset, editingName,
  nameValue, setNameValue, handleSaveRename, setEditingName, saving,
  detail, BACKEND_BASE, seriesIconBust, showSeriesPicker, setShowSeriesPicker,
  fetchDetail, bigBanner, bannerBigRef, assetBust,
}) {
  return (
    <div className="custom-char-header">
      <div
        className="custom-char-icon-wrap"
        onMouseEnter={playHoverSound}
        onClick={() => { playSound('boop'); iconFileRef.current?.click() }}
        title="Replace CSS icon (64x56)"
      >
        {iconUrl ? (
          <img src={iconUrl} alt={`${character.name} icon`} className="custom-char-icon" />
        ) : (
          <span className="custom-char-icon-placeholder">{(character.name || '?')[0]}</span>
        )}
        <span className="custom-char-icon-edit">✎</span>
      </div>
      <input
        ref={iconFileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        onChange={(e) => handleReplaceAsset('icon', e)}
        style={{ display: 'none' }}
      />

      <div className="custom-char-title">
        {editingName ? (
          <div className="custom-char-name-edit">
            <input
              type="text"
              value={nameValue}
              onChange={(e) => setNameValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSaveRename()
                if (e.key === 'Escape') { setEditingName(false); setNameValue(character.name) }
              }}
              autoFocus
              className="edit-name-input"
              disabled={saving}
            />
            <button className="mode-btn" onClick={handleSaveRename} disabled={saving}>
              {saving ? 'Saving...' : 'Save'}
            </button>
            <button className="mode-btn" onClick={() => { setEditingName(false); setNameValue(character.name) }}>
              Cancel
            </button>
          </div>
        ) : (
          <h2 className="custom-char-name">
            {character.name}
            <button
              className="series-change-btn"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); setEditingName(true) }}
              title="Rename character"
            >
              ✎
            </button>
          </h2>
        )}

        <CharacterFranchiseLine
          slug={character.slug}
          detail={detail}
          backendBase={BACKEND_BASE}
          seriesIconBust={seriesIconBust}
          showPicker={showSeriesPicker}
          onTogglePicker={setShowSeriesPicker}
          onRefresh={fetchDetail}
        />

        {character.has_fsm && (
          <div
            className="custom-char-fsm-badge"
            title="This character ships Frame Speed Modifier data (fsm.txt) — custom move speeds are baked into the game when you build an ISO"
          >
            ⚡ FSM move speeds
          </div>
        )}
      </div>

      {bigBanner && (
        <div
          className="custom-char-banner-wrap"
          onMouseEnter={playHoverSound}
          onClick={() => { playSound('boop'); bannerBigRef.current?.click() }}
          title="Result-screen banner (256x28) — click to replace"
        >
          <img
            src={backendMediaUrl(`${bigBanner.url}${assetBust ? `?v=${assetBust}` : ''}`)}
            alt="result banner"
            className="custom-char-banner-img"
          />
          <span className="custom-char-icon-edit">✎</span>
        </div>
      )}
      <input
        ref={bannerBigRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        onChange={(e) => handleReplaceAsset('big_banner', e)}
        style={{ display: 'none' }}
      />
    </div>
  )
}
