import { playHoverSound } from '../shared/audio/sounds'

export const PLAY_TABS = [
  { id: 'games', label: 'Games' },
  { id: 'settings', label: 'Settings' },
]

/** Play mode's tabs, in the app header where the other modes keep theirs. */
export function PlayTabs({ activeTab, onTabChange }) {
  return (
    <nav className="app-tabs">
      {PLAY_TABS.map((tab) => (
        <button
          key={tab.id}
          className={`tab ${activeTab === tab.id ? 'active' : ''}`}
          onMouseEnter={playHoverSound}
          onClick={() => onTabChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  )
}

export default PlayTabs
