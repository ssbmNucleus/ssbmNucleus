/**
 * Animation name data and pure helpers for the Pose Manager.
 */
import { moveLabel, specialMove, thrownMove } from '../../../shared/viewer/animationNames.js'

// Human-readable animation names
export const ANIM_NAMES = {
  // Grounded Attacks
  'Attack11': 'Jab 1', 'Attack12': 'Jab 2', 'Attack13': 'Jab 3',
  'Attack100Start': 'Rapid Jab Start', 'Attack100Loop': 'Rapid Jab Loop', 'Attack100End': 'Rapid Jab End',
  'AttackDash': 'Dash Attack',
  // the angled forward tilts and smashes in the 3D viewer's words (shared/viewer/animationNames.js)
  'AttackS3Hi': 'Forward Tilt (Up)', 'AttackS3HiS': 'Forward Tilt (Up-Middle)', 'AttackS3S': 'Forward Tilt',
  'AttackS3LwS': 'Forward Tilt (Down-Middle)', 'AttackS3Lw': 'Forward Tilt (Down)',
  'AttackHi3': 'Up Tilt', 'AttackLw3': 'Down Tilt',
  'AttackS4Hi': 'Forward Smash (Up)', 'AttackS4HiS': 'Forward Smash (Up-Middle)', 'AttackS4S': 'Forward Smash',
  'AttackS4LwS': 'Forward Smash (Down-Middle)', 'AttackS4Lw': 'Forward Smash (Down)',
  'AttackHi4': 'Up Smash', 'AttackLw4': 'Down Smash',
  // Aerials
  'AttackAirN': 'Neutral Air', 'AttackAirF': 'Forward Air', 'AttackAirB': 'Back Air',
  'AttackAirHi': 'Up Air', 'AttackAirLw': 'Down Air', 'LandingAirN': 'N-Air Landing',
  'LandingAirF': 'F-Air Landing', 'LandingAirB': 'B-Air Landing',
  'LandingAirHi': 'U-Air Landing', 'LandingAirLw': 'D-Air Landing',
  // Specials
  'SpecialN': 'Neutral B', 'SpecialNStart': 'Neutral B Start', 'SpecialNLoop': 'Neutral B Loop',
  'SpecialNEnd': 'Neutral B End', 'SpecialAirN': 'Neutral B (Air)',
  'SpecialS': 'Side B', 'SpecialSStart': 'Side B Start', 'SpecialAirS': 'Side B (Air)',
  'SpecialHi': 'Up B', 'SpecialHiStart': 'Up B Start', 'SpecialAirHi': 'Up B (Air)',
  'SpecialLw': 'Down B', 'SpecialLwStart': 'Down B Start', 'SpecialAirLw': 'Down B (Air)',
  // Grabs & Throws
  'Catch': 'Grab', 'CatchDash': 'Dash Grab', 'CatchWait': 'Grab Hold',
  'CatchAttack': 'Pummel', 'CatchCut': 'Grab Release',
  'ThrowF': 'Forward Throw', 'ThrowB': 'Back Throw', 'ThrowHi': 'Up Throw', 'ThrowLw': 'Down Throw',
  // Movement
  'Wait1': 'Idle 1', 'Wait2': 'Idle 2', 'Wait3': 'Idle 3', 'Wait4': 'Idle 4',
  'Walk': 'Walk', 'WalkSlow': 'Walk (Slow)', 'WalkMiddle': 'Walk (Mid)', 'WalkFast': 'Walk (Fast)',
  'Dash': 'Dash', 'Run': 'Run', 'RunBrake': 'Run Stop',
  'Turn': 'Turn', 'TurnRun': 'Run Turn', 'TurnRunBrake': 'Skid Turn',
  'KneeBend': 'Jumpsquat', 'JumpF': 'Jump (Forward)', 'JumpB': 'Jump (Back)',
  'JumpAerialF': 'Double Jump (F)', 'JumpAerialB': 'Double Jump (B)',
  'Fall': 'Fall', 'FallF': 'Fall (Forward)', 'FallB': 'Fall (Back)',
  'FallAerial': 'Fall (After DJ)', 'FallAerialF': 'Fall (DJ Forward)', 'FallAerialB': 'Fall (DJ Back)',
  'FallSpecial': 'Fall (Special)', 'FallSpecialF': 'Fall (Special Forward)', 'FallSpecialB': 'Fall (Special Back)',
  'Landing': 'Landing', 'LandingFallSpecial': 'Landing (Special)',
  'Squat': 'Crouch', 'SquatWait': 'Crouch Idle', 'SquatRv': 'Stand Up',
  'Pass': 'Platform Drop',
  // Defense
  'Guard': 'Shield', 'GuardOn': 'Shield Start', 'GuardOff': 'Shield Drop',
  'GuardReflect': 'Powershield', 'GuardDamage': 'Shield Stun',
  'EscapeN': 'Spot Dodge', 'EscapeF': 'Roll Forward', 'EscapeB': 'Roll Back',
  'EscapeAir': 'Air Dodge',
  // Damage & KO
  'DamageN1': 'Damage (Weak)', 'DamageN2': 'Damage (Mid)', 'DamageN3': 'Damage (Strong)',
  'DamageHi1': 'Damage High (W)', 'DamageHi2': 'Damage High (M)', 'DamageHi3': 'Damage High (S)',
  'DamageLw1': 'Damage Low (W)', 'DamageLw2': 'Damage Low (M)', 'DamageLw3': 'Damage Low (S)',
  'DamageAir1': 'Damage Air (W)', 'DamageAir2': 'Damage Air (M)', 'DamageAir3': 'Damage Air (S)',
  'DamageFlyN': 'Tumble', 'DamageFlyHi': 'Tumble (High)', 'DamageFlyLw': 'Tumble (Low)',
  'DamageFlyTop': 'Tumble (Top)', 'DamageFlyRoll': 'Tumble Roll',
  'DownBoundU': 'Knockdown (Up)', 'DownBoundD': 'Knockdown (Down)',
  'DownWaitU': 'Grounded (Up)', 'DownWaitD': 'Grounded (Down)',
  'DownStandU': 'Getup (Up)', 'DownStandD': 'Getup (Down)',
  'DownAttackU': 'Getup Attack (Up)', 'DownAttackD': 'Getup Attack (Down)',
  'DownForwardU': 'Getup Roll (Fwd)', 'DownBackU': 'Getup Roll (Back)',
  'DownForwardD': 'Getup Roll (Fwd)', 'DownBackD': 'Getup Roll (Back)',
  // Ledge
  'CliffCatch': 'Ledge Grab', 'CliffWait': 'Ledge Hang',
  'CliffClimbSlow': 'Ledge Climb (Slow)', 'CliffClimbQuick': 'Ledge Climb (Fast)',
  'CliffAttackSlow': 'Ledge Attack (Slow)', 'CliffAttackQuick': 'Ledge Attack (Fast)',
  'CliffEscapeSlow': 'Ledge Roll (Slow)', 'CliffEscapeQuick': 'Ledge Roll (Fast)',
  'CliffJumpSlow1': 'Ledge Jump (Slow)', 'CliffJumpQuick1': 'Ledge Jump (Fast)',
  // Misc
  'Appeal': 'Taunt', 'AppealL': 'Taunt (Left)', 'AppealR': 'Taunt (Right)',
  'Entry': 'Entry', 'EntryStart': 'Entry Start', 'EntryEnd': 'Entry End',
  'Win1': 'Victory 1', 'Win2': 'Victory 2', 'Win3': 'Victory 3',
  'Lose': 'Defeat', 'Dead': 'Star KO', 'DeadUp': 'Up KO', 'DeadLeft': 'Side KO',
  'ReboundStop': 'Clang', 'WallDamage': 'Wall Tech Damage',
  'StopCeil': 'Ceiling Tech', 'StopWall': 'Wall Tech', 'WallJump': 'Wall Jump',
  'Ottotto': 'Teeter', 'OttottoWait': 'Teeter Idle',
  'ItemParasolOpen': 'Parasol Open', 'ItemParasolFall': 'Parasol Fall',
  'LightGet': 'Item Pickup (Light)', 'HeavyGet': 'Item Pickup (Heavy)',
  'LightThrowF': 'Throw Item (F)', 'LightThrowB': 'Throw Item (B)',
  'LightThrowHi': 'Throw Item (Up)', 'LightThrowLw': 'Throw Item (Down)',
  'LightThrowDash': 'Throw Item (Dash)', 'LightThrowDrop': 'Drop Item',
  'LightThrowAirF': 'Air Throw (F)', 'LightThrowAirB': 'Air Throw (B)',
  'LightThrowAirHi': 'Air Throw (Up)', 'LightThrowAirLw': 'Air Throw (Down)',
  'SwordSwing1': 'Bat Swing 1', 'SwordSwing3': 'Bat Swing 2', 'SwordSwing4': 'Bat Swing 3',
  'SwordSwingDash': 'Bat Dash', 'BatSwingDash': 'Bat Dash Attack'
}

// Animation categories
export const ANIM_CATEGORIES = {
  'Grounded': [
    'Attack11', 'Attack12', 'Attack13', 'Attack100Start', 'Attack100Loop', 'Attack100End',
    'AttackDash', 'AttackS3Hi', 'AttackS3HiS', 'AttackS3S', 'AttackS3LwS', 'AttackS3Lw',
    'AttackHi3', 'AttackLw3', 'AttackS4Hi', 'AttackS4HiS', 'AttackS4S', 'AttackS4LwS', 'AttackS4Lw',
    'AttackHi4', 'AttackLw4'
  ],
  'Aerials': [
    'AttackAirN', 'AttackAirF', 'AttackAirB', 'AttackAirHi', 'AttackAirLw',
    'LandingAirN', 'LandingAirF', 'LandingAirB', 'LandingAirHi', 'LandingAirLw'
  ],
  'Specials': [
    'SpecialN', 'SpecialNStart', 'SpecialNLoop', 'SpecialNEnd', 'SpecialAirN',
    'SpecialS', 'SpecialSStart', 'SpecialAirS',
    'SpecialHi', 'SpecialHiStart', 'SpecialAirHi',
    'SpecialLw', 'SpecialLwStart', 'SpecialAirLw'
  ],
  'Grabs': [
    'Catch', 'CatchDash', 'CatchWait', 'CatchAttack', 'CatchCut',
    'ThrowF', 'ThrowB', 'ThrowHi', 'ThrowLw'
  ],
  'Movement': [
    'Wait1', 'Wait2', 'Wait3', 'Wait4', 'Walk', 'WalkSlow', 'WalkMiddle', 'WalkFast',
    'Dash', 'Run', 'RunBrake', 'Turn', 'TurnRun', 'TurnRunBrake',
    'KneeBend', 'JumpF', 'JumpB', 'JumpAerialF', 'JumpAerialB',
    'Fall', 'FallF', 'FallB', 'FallAerial', 'FallAerialF', 'FallAerialB',
    'FallSpecial', 'FallSpecialF', 'FallSpecialB', 'Landing', 'LandingFallSpecial', 'Squat', 'SquatWait', 'SquatRv', 'Pass'
  ],
  'Defense': [
    'Guard', 'GuardOn', 'GuardOff', 'GuardReflect', 'GuardDamage',
    'EscapeN', 'EscapeF', 'EscapeB', 'EscapeAir'
  ],
  'Damage': [
    'DamageN1', 'DamageN2', 'DamageN3', 'DamageHi1', 'DamageHi2', 'DamageHi3',
    'DamageLw1', 'DamageLw2', 'DamageLw3', 'DamageAir1', 'DamageAir2', 'DamageAir3',
    'DamageFlyN', 'DamageFlyHi', 'DamageFlyLw', 'DamageFlyTop', 'DamageFlyRoll',
    'DownBoundU', 'DownBoundD', 'DownWaitU', 'DownWaitD', 'DownStandU', 'DownStandD',
    'DownAttackU', 'DownAttackD', 'DownForwardU', 'DownBackU', 'DownForwardD', 'DownBackD'
  ],
  'Ledge': [
    'CliffCatch', 'CliffWait', 'CliffClimbSlow', 'CliffClimbQuick',
    'CliffAttackSlow', 'CliffAttackQuick', 'CliffEscapeSlow', 'CliffEscapeQuick',
    'CliffJumpSlow1', 'CliffJumpQuick1'
  ],
  'Misc': [
    'Appeal', 'AppealL', 'AppealR', 'Entry', 'EntryStart', 'EntryEnd',
    'Win1', 'Win2', 'Win3', 'Lose', 'Dead', 'DeadUp', 'DeadLeft',
    'ReboundStop', 'WallDamage', 'StopCeil', 'StopWall', 'WallJump',
    'Ottotto', 'OttottoWait', 'ItemParasolOpen', 'ItemParasolFall',
    'LightGet', 'HeavyGet', 'LightThrowF', 'LightThrowB', 'LightThrowHi', 'LightThrowLw',
    'LightThrowDash', 'LightThrowDrop', 'LightThrowAirF', 'LightThrowAirB',
    'LightThrowAirHi', 'LightThrowAirLw', 'SwordSwing1', 'SwordSwing3', 'SwordSwing4',
    'SwordSwingDash', 'BatSwingDash'
  ]
}

// Extract base animation name from symbol (e.g., "PlFx_Share_ACTION_Wait1_figatree" -> "Wait1")
export const extractAnimName = (symbol) => {
  const match = symbol.match(/ACTION_(\w+)_figatree/)
  return match ? match[1] : symbol
}

// Get human-readable display name for animation. Moves the table does not list (SpecialAirNStartR,
// Samus's Special, Kirby's FxSpecialN and his mouthful, a thrown opponent's TKirbyThrowF, ...) get the
// viewer's derived name (shared/viewer/animationNames.js), so the two always agree.
export const getAnimDisplayName = (symbol) => {
  const baseName = extractAnimName(symbol)
  return ANIM_NAMES[baseName] || moveLabel(baseName) || baseName
}

// Get category for an animation. Every special move, air and suffixed versions too, is a Special; a thrown or
// grabbed opponent's motion (TKirbyThrowF, TKoopaSpecialSHit, ...) is a Grab.
export const getAnimCategory = (symbol) => {
  const baseName = extractAnimName(symbol)
  for (const [category, anims] of Object.entries(ANIM_CATEGORIES)) {
    if (anims.includes(baseName)) return category
  }
  if (specialMove(baseName)) return 'Specials'
  if (thrownMove(baseName)) return 'Grabs'
  return 'Other'
}

// Character to costume code prefix mapping
export const CHAR_PREFIXES = {
  "C. Falcon": "PlCa", "Falco": "PlFc", "Fox": "PlFx",
  "Marth": "PlMs", "Roy": "PlFe", "Bowser": "PlKp",
  "DK": "PlDk", "Ganondorf": "PlGn", "Jigglypuff": "PlPr",
  "Kirby": "PlKb", "Link": "PlLk", "Luigi": "PlLg",
  "Mario": "PlMr", "Mewtwo": "PlMt", "Ness": "PlNs",
  "Peach": "PlPe", "Pichu": "PlPc", "Pikachu": "PlPk",
  "Ice Climbers": "PlPp", "Samus": "PlSs", "Sheik": "PlSk",
  "Yoshi": "PlYs", "Young Link": "PlCl", "Zelda": "PlZd",
  "Dr. Mario": "PlDr", "Mr. Game & Watch": "PlGw"
}

// Get default costume code for a character (e.g., "PlFxNr" for Fox)
export const getDefaultCostumeCode = (character) => {
  const prefix = CHAR_PREFIXES[character]
  return prefix ? `${prefix}Nr` : null
}
