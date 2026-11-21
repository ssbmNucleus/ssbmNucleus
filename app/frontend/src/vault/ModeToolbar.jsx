/**
 * ModeToolbar - Mode switcher for Characters/Stages/Menus/Patches/Codes
 *
 * Features:
 * - Five mode buttons (Characters, Stages, Menus, Patches, Codes)
 * - Active mode highlighting
 * - Clears selections when switching modes
 */
import { playSound, playHoverSound } from '../shared/audio/sounds'

export default function ModeToolbar({ mode, onModeChange }) {
  const handleModeChange = (newMode) => {
    if (mode !== newMode) {
      playSound('boop')
      onModeChange(newMode)
    }
  }

  return (
    <div className="mode-switcher">
      <button
        className={`mode-btn ${mode === 'characters' ? 'active' : ''}`}
        onMouseEnter={playHoverSound}
        onClick={() => handleModeChange('characters')}
      >
        Characters
      </button>
      <button
        className={`mode-btn ${mode === 'stages' ? 'active' : ''}`}
        onMouseEnter={playHoverSound}
        onClick={() => handleModeChange('stages')}
      >
        Stages
      </button>
      <button
        className={`mode-btn ${mode === 'menus' ? 'active' : ''}`}
        onMouseEnter={playHoverSound}
        onClick={() => handleModeChange('menus')}
      >
        Menus
      </button>
      <button
        className={`mode-btn ${mode === 'patches' ? 'active' : ''}`}
        onMouseEnter={playHoverSound}
        onClick={() => handleModeChange('patches')}
      >
        Patches
      </button>
    </div>
  )
}
