import { playHoverSound } from '../shared/audio/sounds'
import { COMBO_VIDEO_ENABLED, RANDALL_ENABLED } from '../shared/config/features'

export const NUCLEOME_TABS = [
  ...(RANDALL_ENABLED
    ? [{ id: 'coach', label: 'AI', blurb: 'Your Melee coach, with your real numbers.' }]
    : []),
  { id: 'tournaments', label: 'Tournaments', blurb: 'Your bracket runs, placements, and rivals — from start.gg.' },
  { id: 'stats', label: 'Stats', blurb: 'Matchups, characters, habits — your game in numbers.' },
  { id: 'replays', label: 'Replays', blurb: 'Browse, filter, and watch your Slippi replays.' },
  { id: 'combos', label: 'Combos', blurb: 'Every combo you’ve ever landed — searchable.' },
  ...(COMBO_VIDEO_ENABLED
    ? [{ id: 'combovideo', label: 'Combo Video', blurb: 'Your combos, cut to your music.' }]
    : []),
  { id: 'settings', label: 'Settings', blurb: 'Slippi directory, identity, and analyst settings.' },
]

// badgeTabId is the plain "something is waiting" dot the updater uses.
export function NucleomeTabs({ activeTab, onTabChange, badgeTabId = null }) {
  return (
    <nav className="app-tabs">
      {NUCLEOME_TABS.map((tab) => (
        <button
          key={tab.id}
          className={`tab ${activeTab === tab.id ? 'active' : ''}`}
          onMouseEnter={playHoverSound}
          onClick={() => onTabChange(tab.id)}
        >
          {tab.label}
          {badgeTabId === tab.id && <span className="tab-dot" aria-label="Update available" />}
        </button>
      ))}
    </nav>
  )
}
