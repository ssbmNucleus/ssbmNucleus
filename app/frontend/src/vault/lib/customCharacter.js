// Pure name helpers for custom characters: map a fighter's free-text
// "based on" string onto one of the 26 vanilla character keys.
import { DEFAULT_CHARACTERS } from '../../shared/data/defaultCharacters.js'

export const BASE_CHARACTER_ALIASES = {
  captain: 'C. Falcon',
  captainfalcon: 'C. Falcon',
  falcon: 'C. Falcon',
  clink: 'Young Link',
  donkey: 'DK',
  donkeykong: 'DK',
  dk: 'DK',
  drmario: 'Dr. Mario',
  doc: 'Dr. Mario',
  emblem: 'Roy',
  'game&watch': 'Mr. Game & Watch',
  gamewatch: 'Mr. Game & Watch',
  gameandwatch: 'Mr. Game & Watch',
  'g&w': 'Mr. Game & Watch',
  gw: 'Mr. Game & Watch',
  ganon: 'Ganondorf',
  koopa: 'Bowser',
  mars: 'Marth',
  nana: 'Ice Climbers',
  popo: 'Ice Climbers',
  purin: 'Jigglypuff',
  seak: 'Sheik'
}

export const normalizeCharacterName = (name) => (
  (name || '').toLowerCase().replace(/\band\b/g, '&').replace(/[^a-z0-9&]/g, '')
)

export const resolveBaseCharacter = (name) => {
  const trimmed = (name || '').trim()
  if (!trimmed) return null
  if (DEFAULT_CHARACTERS[trimmed]) return trimmed

  const key = normalizeCharacterName(trimmed)
  if (BASE_CHARACTER_ALIASES[key]) return BASE_CHARACTER_ALIASES[key]

  return Object.keys(DEFAULT_CHARACTERS).find(
    charName => normalizeCharacterName(charName) === key
  ) || null
}

/**
 * Which team tokens ('red' | 'blue' | 'green') are assigned to the bundled
 * costume at `index`, given a character's `team_colors` map.
 */
export const getCostumeTeamColors = (teamColors, index) => {
  if (!teamColors) return []
  return ['red', 'blue', 'green'].filter(team => teamColors[team] === index)
}
