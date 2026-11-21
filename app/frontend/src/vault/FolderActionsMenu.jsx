/**
 * FolderActionsMenu - single folder-icon button in the character detail header
 * that opens a dropdown with the folder-related actions (New folder,
 * Detect Animelee).
 *
 * Mirrors the VaultSortControl popover pattern: click-outside and Escape both
 * close the menu, and picking an item closes it before running the action.
 */
import { useEffect, useRef, useState } from 'react'
import { playSound, playHoverSound } from '../shared/audio/sounds'
import { useClickOutside } from '../shared/hooks/useClickOutside'
import './FolderActionsMenu.css'

export default function FolderActionsMenu({ onNewFolder, onDetectAnimelee }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)

  useClickOutside(rootRef, open, () => setOpen(false))

  useEffect(() => {
    if (!open) return undefined
    const esc = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [open])

  const choose = (action) => {
    playSound('boop')
    setOpen(false)
    action()
  }

  return (
    <div className={`folder-menu ${open ? 'is-open' : ''}`} ref={rootRef}>
      <button
        type="button"
        className="character-action-button folder-menu-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Folder actions"
        onMouseEnter={playHoverSound}
        onClick={() => { playSound('boop'); setOpen((o) => !o); }}
        title="Folder actions"
      >
        <span className="folder-menu-icon">📁</span>
        <span className="folder-menu-caret">▾</span>
      </button>
      {open && (
        <div className="folder-menu-popover" role="menu" aria-label="Folder actions">
          <button
            type="button"
            role="menuitem"
            className="folder-menu-option"
            onMouseEnter={playHoverSound}
            onClick={() => choose(onNewFolder)}
            title="Create an empty folder to group this character's costumes"
          >
            New folder <span className="folder-menu-option-icon">📁</span>
          </button>
          <button
            type="button"
            role="menuitem"
            className="folder-menu-option"
            onMouseEnter={playHoverSound}
            onClick={() => choose(onDetectAnimelee)}
            title="Scan this character's costumes for Animelee skins and move them into a folder"
          >
            Detect Animelee <span className="folder-menu-option-icon">📁</span>
          </button>
        </div>
      )}
    </div>
  )
}
