// Keep these tables aligned with tracker/stats/analyzer.py: the labels and
// category boundaries are part of the bundle contract, not renderer guesses.
const range = (lo, hi) => new Set(Array.from({ length: hi - lo }, (_, i) => lo + i))
export const DAMAGE_STATES = range(75, 92)
export const GRABBED = range(223, 233)
export const THROWN = range(239, 244)
export const DOWN_STATES = range(183, 202)
export const TUMBLE = 38
export const GUARD = new Set([178, 179, 180, 182])
export const SHIELDSTUN = 181
export const CHAR_STATE_MIN = 341
export const _CLIFF = range(252, 264) // viz_export._CLIFF

export const CHAR_NAMES = Object.freeze({
  0: 'CF', 1: 'DK', 2: 'Fox', 3: 'G&W', 4: 'Kirby', 5: 'Bowser',
  6: 'Link', 7: 'Luigi', 8: 'Mario', 9: 'Marth', 10: 'Mewtwo',
  11: 'Ness', 12: 'Peach', 13: 'Pikachu', 14: 'ICs', 15: 'Puff',
  16: 'Samus', 17: 'Yoshi', 18: 'Zelda', 19: 'Sheik', 20: 'Falco',
  21: 'YLink', 22: 'Doc', 23: 'Roy', 24: 'Pichu', 25: 'Ganon',
})
export const STAGE_NAMES = Object.freeze({ 2: 'FoD', 3: 'PS', 8: 'YS', 28: 'DL', 31: 'BF', 32: 'FD' })
export const STAGE_EDGE = Object.freeze({ 2: 63.35, 3: 87.75, 8: 56, 28: 77.27, 31: 68.4, 32: 85.57 })
export const ATTACK_NAMES = Object.freeze({
  1: 'misc', 2: 'jab', 3: 'jab2', 4: 'jab3', 5: 'rapid jabs',
  6: 'dash attack', 7: 'ftilt', 8: 'utilt', 9: 'dtilt',
  10: 'fsmash', 11: 'usmash', 12: 'dsmash', 13: 'nair',
  14: 'fair', 15: 'bair', 16: 'uair', 17: 'dair',
  18: 'neutral-B', 19: 'side-B', 20: 'up-B', 21: 'down-B',
  50: 'getup attack', 51: 'getup attack', 52: 'pummel',
  53: 'fthrow', 54: 'bthrow', 55: 'uthrow', 56: 'dthrow',
  61: 'ledge attack', 62: 'ledge attack',
})

// CSS -> in-game ids from viz_export._EXT_TO_INT. Animation packs use the
// latter; an unknown custom character keeps its recorded id.
export const _EXT_TO_INT = Object.freeze({
  0: 2, 1: 3, 2: 1, 3: 24, 4: 4, 5: 5, 6: 6, 7: 17, 8: 0, 9: 18,
  10: 16, 11: 8, 12: 9, 13: 12, 14: 10, 15: 15, 16: 13, 17: 14,
  18: 19, 19: 7, 20: 22, 21: 20, 22: 21, 23: 26, 24: 23, 25: 25,
})
