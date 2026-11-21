import { useState, useEffect, useRef } from 'react'
import { playSound, playHoverSound } from '../../../shared/audio/sounds'
import { API_URL, backendMediaUrl } from '../../../shared/config/config.js'
import { api } from '../../../shared/transport/api'
import { useClickOutside } from '../../../shared/hooks/useClickOutside'

/**
 * The vault skins of the vanilla character this custom fighter is based on.
 * Reloads (and closes the popover) whenever the base character changes.
 */
function useBaseSkinPool(baseCharacter) {
  const [baseSkinPool, setBaseSkinPool] = useState([])
  const [baseSkinLoading, setBaseSkinLoading] = useState(false)
  const [showBaseSkinMenu, setShowBaseSkinMenu] = useState(false)

  useEffect(() => {
    let cancelled = false

    setBaseSkinPool([])
    setShowBaseSkinMenu(false)
    if (!baseCharacter) {
      setBaseSkinLoading(false)
      return () => { cancelled = true }
    }

    setBaseSkinLoading(true)
    api.get(`/storage/costumes?character=${encodeURIComponent(baseCharacter)}`)
      .then(data => {
        if (cancelled) return
        const pool = (data.costumes || [])
          .filter(skin => !skin.isNana)
        setBaseSkinPool(pool)
      })
      .catch(err => {
        if (!cancelled) {
          console.error('Failed to fetch base character skins:', err)
          setBaseSkinPool([])
        }
      })
      .finally(() => {
        if (!cancelled) setBaseSkinLoading(false)
      })

    return () => { cancelled = true }
  }, [API_URL, baseCharacter])

  return { baseSkinPool, baseSkinLoading, showBaseSkinMenu, setShowBaseSkinMenu }
}

/**
 * "Add <Base> Skin" button + popover: copies a skin out of the base vanilla
 * character's vault into this custom character's Custom Skins.
 * Renders nothing when the character isn't based on a vanilla fighter.
 */
export default function BaseSkinPicker({ slug, baseCharacter, backendBase, onRefresh, flashMessage }) {
  const { baseSkinPool, baseSkinLoading, showBaseSkinMenu, setShowBaseSkinMenu } = useBaseSkinPool(baseCharacter)
  const [copyingBaseSkin, setCopyingBaseSkin] = useState(false)
  const baseSkinMenuRef = useRef(null)

  useClickOutside(baseSkinMenuRef, showBaseSkinMenu, () => setShowBaseSkinMenu(false))

  const handleCopyBaseSkin = async (skinId) => {
    if (!baseCharacter || !skinId || copyingBaseSkin) return
    const selected = baseSkinPool.find(skin => skin.folder === skinId)
    setCopyingBaseSkin(true)
    try {
      const data = await api.post(`/custom-characters/${slug}/skins/add`, { character: baseCharacter, skinId })
      playSound('newSkin')
      setShowBaseSkinMenu(false)
      flashMessage(`Copied ${selected?.name || data.skin?.name || 'skin'} from ${baseCharacter}`)
      await onRefresh()
    } catch (err) {
      flashMessage(`Copy failed: ${err.message}`)
    } finally {
      setCopyingBaseSkin(false)
    }
  }

  const baseSkinLabel = (skin) => {
    const name = skin.name || skin.costumeCode || skin.folder || 'Skin'
    const prefix = `${baseCharacter} - `
    return name.startsWith(prefix) ? name.slice(prefix.length) : name
  }

  if (!baseCharacter) return null

  return (
    <div className="base-skin-copy-controls" ref={baseSkinMenuRef}>
      <button
        type="button"
        className={`base-skin-menu-btn ${showBaseSkinMenu ? 'active' : ''}`}
        onMouseEnter={playHoverSound}
        onClick={() => { playSound('boop'); setShowBaseSkinMenu(open => !open) }}
        disabled={copyingBaseSkin}
        title={`Open ${baseCharacter} vault skins to copy into this custom character`}
      >
        {copyingBaseSkin ? 'Adding...' : `Add ${baseCharacter} Skin`}
      </button>
      {showBaseSkinMenu && (
        <div className="base-skin-popover" role="menu" aria-label={`${baseCharacter} skins`}>
          <div className="base-skin-popover-title">{baseCharacter} Skins</div>
          {baseSkinLoading ? (
            <div className="base-skin-popover-state">Loading...</div>
          ) : baseSkinPool.length === 0 ? (
            <div className="base-skin-popover-state">No skins in vault</div>
          ) : (
            <div className="base-skin-grid">
              {baseSkinPool.map(skin => (
                <button
                  key={skin.folder}
                  type="button"
                  className="base-skin-card"
                  onMouseEnter={playHoverSound}
                  onClick={() => { playSound('boop'); handleCopyBaseSkin(skin.folder) }}
                  disabled={copyingBaseSkin}
                  title={`Copy ${baseSkinLabel(skin)} from ${baseCharacter}`}
                >
                  <div className="base-skin-card-image">
                    {skin.cspUrl ? (
                      <img
                        src={backendMediaUrl(skin.cspUrl)}
                        alt={baseSkinLabel(skin)}
                        draggable={false}
                      />
                    ) : (
                      <span>{baseSkinLabel(skin)[0] || '?'}</span>
                    )}
                  </div>
                  <div className="base-skin-card-info">
                    {skin.stockUrl && (
                      <img
                        src={backendMediaUrl(skin.stockUrl)}
                        alt=""
                        className="base-skin-stock"
                        draggable={false}
                      />
                    )}
                    <span>{baseSkinLabel(skin)}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
