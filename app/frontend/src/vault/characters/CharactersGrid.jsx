/**
 * CharactersGrid - Character grid display
 *
 * Features:
 * - Grid layout of character cards
 * - CSS icon display with fallback: a character whose icon does not load shows its letter, and is tried again each
 *   time `iconRetryKey` changes (the vault metadata, read again after setup or an import: iconRetry.js)
 * - Skin count display
 * - Skeleton loading state
 * - Click to select character
 */
import { useEffect, useState } from 'react'
import { playSound, playHoverSound } from '../../shared/audio/sounds'
import { BACKEND_URL } from '../../shared/config/config'
import { EMPTY, iconFailed, iconSrc, retryIcons } from './iconRetry'

const SkeletonCard = () => (
  <div className="character-card skeleton-card">
    <div className="character-icon-container">
      <div className="skeleton skeleton-image"></div>
    </div>
    <div className="skeleton skeleton-text" style={{ width: '50%', height: '12px' }}></div>
  </div>
)

export default function CharactersGrid({ characters, allCharacters, isLoading, onSelectCharacter, customCharacterCount = 0, onOpenCustomCharacters, iconRetryKey }) {
  const [icons, setIcons] = useState(EMPTY)
  useEffect(() => { setIcons(retryIcons) }, [iconRetryKey])
  return (
    <div className="grid-wrapper">
      <div className="characters-grid">
        {isLoading ? (
          // Skeleton loading for characters
          Array.from({ length: 12 }).map((_, idx) => (
            <SkeletonCard key={`skeleton-${idx}`} />
          ))
        ) : characters.map((characterName) => {
          const charData = allCharacters[characterName]
          // Only count visible skins (exclude hidden Ice Climbers Nana entries)
          const visibleSkins = charData?.skins?.filter(skin => skin.visible !== false) || []
          const skinCount = visibleSkins.length

          // Use CSS icon which already includes character name
          const cssIconPath = iconSrc(icons, characterName, `${BACKEND_URL}/vanilla/${characterName}/css_icon.png`)

          return (
            <div
              key={characterName}
              className="character-card"
              onMouseEnter={playHoverSound}
              onClick={() => { playSound('boop'); onSelectCharacter(characterName); }}
            >
              <div className="character-icon-container">
                {cssIconPath ? (
                  <img
                    key={cssIconPath}
                    src={cssIconPath}
                    alt={characterName}
                    className="character-css-icon"
                    draggable={false}
                    onError={() => setIcons(state => iconFailed(state, characterName))}
                  />
                ) : (
                  <div className="character-placeholder">
                    <span className="character-initial">{characterName[0]}</span>
                  </div>
                )}
              </div>

              <p className="skin-count"><span>{skinCount}</span> skin{skinCount !== 1 ? 's' : ''}</p>
            </div>
          )
        })}

          {!isLoading && (
          <div
            className="character-card custom-characters-gateway"
            onMouseEnter={playHoverSound}
            onClick={() => { playSound('boop'); onOpenCustomCharacters && onOpenCustomCharacters(); }}
          >
            <div className="character-icon-container">
              <div className="character-placeholder" style={{ display: 'flex', fontSize: '2rem', fontWeight: 700 }}>
                +
              </div>
            </div>
            <p className="skin-count">
              <span>{customCharacterCount}</span> character{customCharacterCount !== 1 ? 's' : ''}
            </p>
          </div>
          )}
      </div>
    </div>
  )
}
