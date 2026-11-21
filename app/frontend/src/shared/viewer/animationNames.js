/**
 * Friendly names and list groups for the 3D model viewer's animations (the viewer
 * pane and Randall's workbench), plus the derived naming the Pose Manager shares
 * (vault/characters/poses/animData.js, through moveLabel): both call a special
 * "Side B", never "Side Special", and a thrown opponent's motion "Thrown by ...".
 *
 * Animations arrive as figatree symbols, e.g. PlyPurin5K_Share_ACTION_SpecialAirS_figatree.
 */

// Animation name mappings (same as ModelViewer.jsx). Specials use the Pose Manager's B wording.
export const ANIM_NAMES = {
  'Attack11': 'Jab 1', 'Attack12': 'Jab 2', 'Attack13': 'Jab 3',
  'AttackHi3': 'Up Tilt', 'AttackLw3': 'Down Tilt', 'AttackS3S': 'Forward Tilt',
  'AttackHi4': 'Up Smash', 'AttackLw4': 'Down Smash', 'AttackS4S': 'Forward Smash',
  // angled forward tilts and smashes: Hi / Lw the angle, a trailing S half-way (the Pose Manager uses the same words)
  'AttackS3Hi': 'Forward Tilt (Up)', 'AttackS3HiS': 'Forward Tilt (Up-Middle)',
  'AttackS3LwS': 'Forward Tilt (Down-Middle)', 'AttackS3Lw': 'Forward Tilt (Down)',
  'AttackS4Hi': 'Forward Smash (Up)', 'AttackS4HiS': 'Forward Smash (Up-Middle)',
  'AttackS4LwS': 'Forward Smash (Down-Middle)', 'AttackS4Lw': 'Forward Smash (Down)',
  'AttackDash': 'Dash Attack',
  'AttackAirN': 'Neutral Air', 'AttackAirHi': 'Up Air', 'AttackAirF': 'Forward Air',
  'AttackAirLw': 'Down Air', 'AttackAirB': 'Back Air',
  'SpecialN': 'Neutral B', 'SpecialHi': 'Up B',
  'SpecialLw': 'Down B', 'SpecialS': 'Side B',
  'Catch': 'Grab', 'ThrowF': 'Forward Throw', 'ThrowB': 'Back Throw',
  'ThrowHi': 'Up Throw', 'ThrowLw': 'Down Throw',
  'Wait1': 'Idle 1', 'Wait2': 'Idle 2', 'Walk': 'Walk', 'Dash': 'Dash',
  'Run': 'Run', 'Jump': 'Jump', 'Fall': 'Fall',
  // the helpless fall after an up special (Movement, as in the Pose Manager)
  'FallSpecial': 'Fall (Special)', 'FallSpecialF': 'Fall (Special Forward)', 'FallSpecialB': 'Fall (Special Back)',
  'Guard': 'Shield', 'EscapeF': 'Roll Forward', 'EscapeB': 'Roll Back',
  'Appeal': 'Taunt', 'Win1': 'Victory Pose 1', 'Win2': 'Victory Pose 2',
}

// Name prefixes per list group. Specials also take every air and suffixed variant (specialMove below).
export const ANIM_CATEGORIES = {
  'Grounded Attacks': ['Attack11', 'Attack12', 'Attack13', 'AttackDash', 'AttackHi3', 'AttackLw3', 'AttackS3', 'AttackHi4', 'AttackLw4', 'AttackS4'],
  'Aerials': ['AttackAirN', 'AttackAirHi', 'AttackAirF', 'AttackAirLw', 'AttackAirB'],
  'Specials': ['SpecialN', 'SpecialHi', 'SpecialLw', 'SpecialS'],
  'Grabs & Throws': ['Catch', 'Throw'],
  'Movement': ['Wait', 'Walk', 'Dash', 'Run', 'Jump', 'Fall'],
  'Defense': ['Guard', 'Escape'],
  'Misc': ['Appeal', 'Win'],
}

export const extractAnimName = (symbol) => {
  const match = symbol.match(/_ACTION_(.+?)_figatree$/)
  if (match) return match[1]
  const match2 = symbol.match(/_ACTION_(.+)$/)
  if (match2) return match2[1]
  return symbol
}

const SPECIAL_SLOTS = { N: 'Neutral', S: 'Side', Hi: 'Up', Lw: 'Down' }

// Specials whose figatree name drops the slot: Samus's Super Missile (her smash side B, the game's SpecialSSmash
// state) is filed as plain Special / SpecialAir, right after the Homing Missile's SpecialS / SpecialAirS.
const SPECIAL_ALIASES = { Special: 'SpecialSSmash', SpecialAir: 'SpecialAirSSmash' }

// Kirby's copied neutral specials carry the copied fighter's two-letter code: MrSpecialN, FxSpecialAirNStart, ...
// (the clones' copies reuse their originals': Dr. Mario's is Mario's).
const COPY_FIGHTERS = {
  Ca: 'C. Falcon', Dk: 'DK', Fc: 'Falco', Fx: 'Fox', Gn: 'Ganondorf', Gw: 'Mr. Game & Watch', Kp: 'Bowser',
  Lg: 'Luigi', Lk: 'Link', Mr: 'Mario', Ms: 'Marth', Mt: 'Mewtwo', Ns: 'Ness', Pe: 'Peach', Pk: 'Pikachu',
  Pp: 'Ice Climbers', Pr: 'Jigglypuff', Sk: 'Sheik', Ss: 'Samus', Ys: 'Yoshi', Zd: 'Zelda',
}
const SPECIAL_ACTION = new RegExp(`^(${Object.keys(COPY_FIGHTERS).join('|')})?Special(Air)?(Hi|Lw|N|S)([A-Z0-9].*)?$`)
// The game's own words: its spelling in DK's and Sheik's SpecialNCansel, and Kirby's SpecialNDrink, his swallow.
const WORD_FIXES = { Cansel: 'Cancel', Drink: 'Swallow' }

// Plain moves neither name table lists: Kirby holding an inhaled opponent in his mouth (Eat...), and DK's cargo
// carry (his forward throw) with the throws out of it. Bowser's down throw has its own version for Peach.
const MOVE_NAMES = {
  Eat: 'Mouthful', EatWait: 'Mouthful Idle', EatTurn: 'Mouthful Turn', EatLanding: 'Mouthful Landing',
  EatWalkSlow: 'Mouthful Walk (Slow)', EatWalkMiddle: 'Mouthful Walk (Mid)', EatWalkFast: 'Mouthful Walk (Fast)',
  EatJump1: 'Mouthful Jump 1', EatJump2: 'Mouthful Jump 2',
  ThrowFWait: 'Cargo Hold', ThrowFTurn: 'Cargo Turn',
  ThrowFWalkSlow: 'Cargo Walk (Slow)', ThrowFWalkMiddle: 'Cargo Walk (Mid)', ThrowFWalkFast: 'Cargo Walk (Fast)',
  ThrowFF: 'Cargo Forward Throw', ThrowFB: 'Cargo Back Throw', ThrowFHi: 'Cargo Up Throw', ThrowFLw: 'Cargo Down Throw',
  ThrowLwPeach: 'Down Throw (Peach)',
}

// A fighter's archive also holds the motions of the opponent it throws or grabs: T, the thrower in the game's own
// words, then the move. TKirbyThrowF is Kirby's forward throw, TKoopaSpecialSHit Bowser's side B grab; Luigi's
// throws use TMario's and Ganondorf's up B TCaptain's. Every vanilla fighter's, read from the Tracker's fighter data.
const THROWERS = {
  Captain: 'C. Falcon', Clink: 'Young Link', Donkey: 'DK', Drmario: 'Dr. Mario', Emblem: 'Roy', Falco: 'Falco',
  Fox: 'Fox', Gamewatch: 'Mr. Game & Watch', Ganon: 'Ganondorf', Kirby: 'Kirby', Koopa: 'Bowser', Link: 'Link',
  Mario: 'Mario', Mars: 'Marth', Mewtwo: 'Mewtwo', Ness: 'Ness', Peach: 'Peach', Pichu: 'Pichu', Pikachu: 'Pikachu',
  Popo: 'Ice Climbers', Purin: 'Jigglypuff', Samus: 'Samus', Seak: 'Sheik', Yoshi: 'Yoshi', Zelda: 'Zelda',
}
const THROWN_ACTION = new RegExp(`^T(${Object.keys(THROWERS).join('|')})((?:Throw|Special)[A-Z].*)$`)
// Kirby's inhale in its own words: the opponent he swallows, and the star he spits out.
const THROWN_NAMES = { TKirbySpecialNDrink: 'Swallowed by Kirby', TKirbySpecialNSpit: 'Spat Out by Kirby' }

/**
 * A special move's action name taken apart: SpecialAirNStartR -> {slot: 'N', air: true, words: ['Start', 'R']}.
 * Covers the air versions (SpecialAir<slot>..., or a trailing Air as in Fox's SpecialHiHoldAir), any
 * suffix (Start, Loop, End, L, R, Hold, ...), Samus's slotless Special / SpecialAir (SPECIAL_ALIASES) and
 * Kirby's copied specials (`copy`: the copied fighter, FxSpecialN -> copy 'Fox'). null when the name is
 * not a special move.
 */
export const specialMove = (action) => {
  const name = String(action || '')
  const match = (SPECIAL_ALIASES[name] || name).match(SPECIAL_ACTION)
  if (!match) return null
  const words = ((match[4] || '').match(/[A-Z][a-z]*|[0-9]+|[a-z]+/g) || []).map(word => WORD_FIXES[word] || word)
  let air = Boolean(match[2])
  if (words.length && words[words.length - 1] === 'Air') {
    words.pop()
    air = true
  }
  const move = { slot: match[3], air, words }
  if (match[1]) move.copy = COPY_FIGHTERS[match[1]]
  return move
}

/**
 * The friendly name of a special move, or null: "Side B Start (Air)", Samus's "Side B Smash (Air)",
 * Kirby's copy "Fox Neutral B Start (Air)". The viewer and the Pose Manager both use it.
 */
export const specialMoveLabel = (action) => {
  const move = specialMove(action)
  if (!move) return null
  const name = [...(move.copy ? [move.copy] : []), `${SPECIAL_SLOTS[move.slot]} B`, ...move.words].join(' ')
  return move.air ? `${name} (Air)` : name
}

/**
 * The opponent's motion in one of this fighter's throws or grabs, taken apart: TKoopaSpecialSHit ->
 * {by: 'Bowser', move: 'SpecialSHit'}. null for anything else.
 */
export const thrownMove = (action) => {
  const match = String(action || '').match(THROWN_ACTION)
  return match ? { by: THROWERS[match[1]], move: match[2] } : null
}

/**
 * The friendly name of a thrown or grabbed opponent's motion, or null: "Thrown by Kirby (Forward Throw)",
 * "Thrown by Bowser (Side B Hit, Air)", "Swallowed by Kirby".
 */
export const thrownMoveLabel = (action) => {
  const thrown = thrownMove(action)
  if (!thrown) return null
  if (THROWN_NAMES[action]) return THROWN_NAMES[action]
  const move = ANIM_NAMES[thrown.move] || moveLabel(thrown.move) || thrown.move
  return `Thrown by ${thrown.by} (${move.replace(/ \((.+)\)$/, ', $1')})`
}

/**
 * The friendly name of a move the name tables leave out, or null: a special move (specialMoveLabel), Kirby's
 * mouthful, DK's cargo throws, a thrown opponent's motion (thrownMoveLabel). The viewer and the Pose Manager both
 * fall back to it, so the two always agree.
 */
export const moveLabel = (action) => specialMoveLabel(action) || MOVE_NAMES[action] || thrownMoveLabel(action)

export const getAnimDisplayName = (symbol) => {
  const coreName = extractAnimName(symbol)
  return ANIM_NAMES[coreName] || moveLabel(coreName) || coreName
}

export const getAnimCategory = (symbol) => {
  const coreName = extractAnimName(symbol)
  if (specialMove(coreName)) return 'Specials'
  if (thrownMove(coreName)) return 'Grabs & Throws'
  for (const [category, prefixes] of Object.entries(ANIM_CATEGORIES)) {
    if (prefixes.some(prefix => coreName.startsWith(prefix))) {
      return category
    }
  }
  return 'Other'
}

export const groupAnimations = (animList) => {
  const grouped = {}
  for (const symbol of animList) {
    const category = getAnimCategory(symbol)
    if (!grouped[category]) grouped[category] = []
    grouped[category].push(symbol)
  }
  const categoryOrder = Object.keys(ANIM_CATEGORIES).concat(['Other'])
  const sorted = {}
  for (const cat of categoryOrder) {
    if (grouped[cat]?.length > 0) sorted[cat] = grouped[cat]
  }
  return sorted
}

/** The animations whose friendly name or symbol contains `query` (case-insensitive). */
export const filterAnimations = (animList, query) => {
  const q = String(query || '').toLowerCase()
  return animList.filter(a => getAnimDisplayName(a).toLowerCase().includes(q) || a.toLowerCase().includes(q))
}
