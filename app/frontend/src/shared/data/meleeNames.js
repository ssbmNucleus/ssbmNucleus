// External character IDs (as used in .slp GameStart) and stage IDs -> names.

export const CHARACTERS = {
  0: 'Captain Falcon',
  1: 'Donkey Kong',
  2: 'Fox',
  3: 'Mr. Game & Watch',
  4: 'Kirby',
  5: 'Bowser',
  6: 'Link',
  7: 'Luigi',
  8: 'Mario',
  9: 'Marth',
  10: 'Mewtwo',
  11: 'Ness',
  12: 'Peach',
  13: 'Pikachu',
  14: 'Ice Climbers',
  15: 'Jigglypuff',
  16: 'Samus',
  17: 'Yoshi',
  18: 'Zelda',
  19: 'Sheik',
  20: 'Falco',
  21: 'Young Link',
  22: 'Dr. Mario',
  23: 'Roy',
  24: 'Pichu',
  25: 'Ganondorf',
}

export const STAGES = {
  2: 'Fountain of Dreams',
  3: 'Pokémon Stadium',
  4: "Peach's Castle",
  5: 'Kongo Jungle',
  6: 'Brinstar',
  7: 'Corneria',
  8: "Yoshi's Story",
  9: 'Onett',
  10: 'Mute City',
  11: 'Rainbow Cruise',
  12: 'Jungle Japes',
  13: 'Great Bay',
  14: 'Hyrule Temple',
  15: 'Brinstar Depths',
  16: "Yoshi's Island",
  17: 'Green Greens',
  18: 'Fourside',
  19: 'Mushroom Kingdom I',
  20: 'Mushroom Kingdom II',
  22: 'Venom',
  23: 'Poké Floats',
  24: 'Big Blue',
  25: 'Icicle Mountain',
  27: 'Flat Zone',
  28: 'Dream Land N64',
  29: "Yoshi's Island N64",
  30: 'Kongo Jungle N64',
  31: 'Battlefield',
  32: 'Final Destination',
}

// Slippi "last attack landed" move ids (slippi-js melee/moves.ts)
export const MOVES = {
  1: 'Misc',
  2: 'Jab 1',
  3: 'Jab 2',
  4: 'Jab 3',
  5: 'Rapid Jabs',
  6: 'Dash Attack',
  7: 'F-Tilt',
  8: 'U-Tilt',
  9: 'D-Tilt',
  10: 'F-Smash',
  11: 'U-Smash',
  12: 'D-Smash',
  13: 'Nair',
  14: 'Fair',
  15: 'Bair',
  16: 'Uair',
  17: 'Dair',
  18: 'Neutral B',
  19: 'Side B',
  20: 'Up B',
  21: 'Down B',
  50: 'Getup Attack',
  51: 'Getup Attack (Slow)',
  52: 'Pummel',
  53: 'F-Throw',
  54: 'B-Throw',
  55: 'U-Throw',
  56: 'D-Throw',
  61: 'Edge Attack (Slow)',
  62: 'Edge Attack',
}

export const charName = (id) => CHARACTERS[id] ?? `Char ${id}`
export const stageName = (id) => STAGES[id] ?? `Stage ${id}`
export const moveName = (id) => MOVES[id] ?? `Move ${id}`

export function formatDuration(seconds) {
  if (seconds == null) return '—'
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

export function formatDate(iso) {
  if (!iso) return 'Unknown date'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit',
  })
}

// slippi.gg profile URL for a connect code ("ABCD#123" -> ".../user/ABCD-123").
// Null for players with no code (CPUs, guests, pre-rollback replays).
export function slippiProfileUrl(code) {
  if (!code) return null
  const slug = code.trim().toUpperCase().replace('#', '-')
  if (!/^[A-Z0-9]+-\d+$/.test(slug)) return null
  return `https://slippi.gg/user/${slug}`
}

// Open a player's slippi.gg profile in the system browser (Electron), falling
// back to a new tab in the dev/browser build.
export function openSlippiProfile(code) {
  const url = slippiProfileUrl(code)
  if (!url) return
  if (window.electron?.openExternal) window.electron.openExternal(url)
  else window.open(url, '_blank', 'noopener,noreferrer')
}
