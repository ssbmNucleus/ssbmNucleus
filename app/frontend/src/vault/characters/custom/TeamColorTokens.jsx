import { playHoverSound } from '../../../shared/audio/sounds'

const TEAM_TOKENS = [
  { id: 'red', label: 'R', color: '#ff4757' },
  { id: 'blue', label: 'B', color: '#3742fa' },
  { id: 'green', label: 'G', color: '#2ed573' }
]

/**
 * Team color tokens: click a token to arm it, then click a costume card to
 * assign — same interaction as the install page's vanilla character panel.
 * Renders nothing unless the character has a team_colors map and more than one
 * bundled costume to choose between.
 */
export default function TeamColorTokens({ teamColors, costumeCount, selected, onSelect }) {
  if (!teamColors || !(costumeCount > 1)) return null
  return (
    <div className="team-color-tokens">
      {TEAM_TOKENS.map(c => (
        <div
          key={c.id}
          className={`team-color-token ${selected === c.id ? 'selected' : ''}`}
          style={{ '--token-color': c.color }}
          onClick={() => onSelect(c.id)}
          onMouseEnter={playHoverSound}
          title={`${c.id.charAt(0).toUpperCase() + c.id.slice(1)} Team - click to assign`}
        >
          {c.label}
        </div>
      ))}
    </div>
  )
}

/** The little R/B/G corner badges on a costume card. */
export function TeamColorBadges({ teams }) {
  if (teams.length === 0) return null
  return (
    <div className="team-color-badges">
      {teams.map(team => (
        <div
          key={team}
          className={`team-color-badge team-${team}`}
          title={`${team.charAt(0).toUpperCase() + team.slice(1)} Team`}
        >
          {team[0].toUpperCase()}
        </div>
      ))}
    </div>
  )
}
