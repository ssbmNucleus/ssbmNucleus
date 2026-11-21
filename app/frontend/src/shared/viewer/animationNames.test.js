import test from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import {
  filterAnimations, getAnimCategory, getAnimDisplayName, groupAnimations, specialMove, specialMoveLabel, thrownMove,
} from './animationNames.js'

const sym = (action, prefix = 'PlyPurin5K_Share') => `${prefix}_ACTION_${action}_figatree`

// Every special-move name shape: ground and air, plain and with the suffixes fighters use.
const SLOTS = ['N', 'S', 'Hi', 'Lw']
const SUFFIXES = ['', 'Start', 'Loop', 'End', 'L', 'R', 'StartR', 'EndL', 'Hold', 'Hit', '1', '2']
const SPECIALS = SLOTS.flatMap(slot => SUFFIXES.flatMap(suffix => [
  sym(`Special${slot}${suffix}`), sym(`SpecialAir${slot}${suffix}`),
]))
const UNKNOWN = ['LandingFallSpecial', 'ItemHammerWait', 'CaptureNeck', 'Rebirth', 'Swim'].map(a => sym(a))
const ORDINARY = ['Wait1', 'AttackAirN', 'Attack11', 'FallSpecial', 'ThrowF'].map(a => sym(a))

test("an air special is a Special with a friendly name, not Other (Jigglypuff's air Pound, bug 11-19)", () => {
  assert.equal(getAnimCategory(sym('SpecialAirS')), 'Specials')
  assert.equal(getAnimDisplayName(sym('SpecialAirS')), 'Side B (Air)')
  assert.equal(getAnimDisplayName(sym('SpecialAirN')), 'Neutral B (Air)')
  assert.equal(getAnimDisplayName(sym('SpecialAirHi')), 'Up B (Air)')
  assert.equal(getAnimDisplayName(sym('SpecialAirLw')), 'Down B (Air)')
  assert.equal(getAnimDisplayName(sym('SpecialS')), 'Side B')
})

test('a suffixed special keeps its suffix in the name', () => {
  assert.equal(getAnimDisplayName(sym('SpecialAirNStartR')), 'Neutral B Start R (Air)')
  assert.equal(getAnimDisplayName(sym('SpecialNLoop')), 'Neutral B Loop')
  assert.equal(getAnimDisplayName(sym('SpecialLwEndL')), 'Down B End L')
  assert.equal(getAnimDisplayName(sym('SpecialHiHoldAir', 'PlyFox5K_Share')), 'Up B Hold (Air)')
  assert.equal(specialMoveLabel('SpecialAirS'), 'Side B (Air)')
  assert.deepEqual(specialMove('SpecialAirNStartR'), { slot: 'N', air: true, words: ['Start', 'R'] })
  assert.equal(specialMove('SpecialStart'), null)
  assert.equal(specialMove('FallSpecial'), null)
})

test('every generated special lands exactly once in Specials, unknowns stay in Other, nothing is lost', () => {
  const all = [...ORDINARY, ...SPECIALS, ...UNKNOWN]
  const groups = groupAnimations(all)
  assert.deepEqual([...groups.Specials].sort(), [...SPECIALS].sort())
  assert.equal(new Set(groups.Specials).size, SPECIALS.length)
  assert.deepEqual(groups.Other, UNKNOWN)
  const listed = Object.values(groups).flat()
  assert.equal(listed.length, all.length)
  assert.deepEqual([...listed].sort(), [...all].sort())
  // the special fall is movement, not a special
  assert.equal(getAnimCategory(sym('FallSpecial')), 'Movement')
  // every special has a friendly name, never its raw action name
  for (const symbol of SPECIALS) assert.match(getAnimDisplayName(symbol), /^(Neutral|Side|Up|Down) B\b/, symbol)
})

test('search finds a special by its friendly name or its symbol', () => {
  const list = [sym('SpecialAirS'), sym('SpecialS'), sym('Wait1'), sym('SpecialAirLwR')]
  assert.deepEqual(filterAnimations(list, 'side b'), [sym('SpecialAirS'), sym('SpecialS')])
  assert.deepEqual(filterAnimations(list, '(AIR)'), [sym('SpecialAirS'), sym('SpecialAirLwR')])
  assert.deepEqual(filterAnimations(list, 'SpecialAirLw'), [sym('SpecialAirLwR')])
  assert.deepEqual(filterAnimations(list, ''), list)
})

// Every vanilla fighter's figatree names, read from the AJ archives (0.9.0 hand-check, 11-20): the specials the
// parse above missed. Samus's Super Missile is filed as plain Special / SpecialAir; Kirby's copies carry the
// copied fighter's code; the special fall's forward and back versions had no name.
test("Samus's slotless Special / SpecialAir is her smash side B, under Specials (0.9.0 hand-check)", () => {
  const samus = action => sym(action, 'PlySamus5K_Share')
  assert.equal(getAnimCategory(samus('Special')), 'Specials')
  assert.equal(getAnimCategory(samus('SpecialAir')), 'Specials')
  assert.equal(getAnimDisplayName(samus('SpecialS')), 'Side B')
  assert.equal(getAnimDisplayName(samus('Special')), 'Side B Smash')
  assert.equal(getAnimDisplayName(samus('SpecialAir')), 'Side B Smash (Air)')
  assert.deepEqual(specialMove('SpecialAir'), { slot: 'S', air: true, words: ['Smash'] })
  // only those two exact names: anything else that merely starts with Special stays what it was
  assert.equal(specialMove('SpecialStart'), null)
  assert.equal(specialMove('SpecialAirStart'), null)
})

test("Kirby's copied specials are Specials named for the fighter he copied", () => {
  const kirby = action => sym(action, 'PlyKirby5K_Share')
  const copies = ['MrSpecialN', 'FxSpecialAirNStart', 'PrSpecialNEndL', 'DkSpecialNCansel', 'GwSpecialAirN', 'PeSpecialLwHit']
  for (const action of copies) assert.equal(getAnimCategory(kirby(action)), 'Specials', action)
  assert.equal(getAnimDisplayName(kirby('MrSpecialN')), 'Mario Neutral B')
  assert.equal(getAnimDisplayName(kirby('FxSpecialAirNStart')), 'Fox Neutral B Start (Air)')
  assert.equal(getAnimDisplayName(kirby('PrSpecialNEndL')), 'Jigglypuff Neutral B End L')
  assert.equal(getAnimDisplayName(kirby('DkSpecialNCansel')), 'DK Neutral B Cancel')
  assert.equal(getAnimDisplayName(kirby('GwSpecialAirN')), 'Mr. Game & Watch Neutral B (Air)')
  assert.equal(getAnimDisplayName(kirby('SpecialN')), 'Neutral B', "Kirby's own inhale has no copy name")
  assert.deepEqual(specialMove('FxSpecialAirNStart'), { slot: 'N', air: true, words: ['Start'], copy: 'Fox' })
  // a two-letter code that is not a fighter, and the thrown opponent's motions (T<Fighter>Special...), are not copies
  assert.equal(specialMove('XxSpecialN'), null)
  assert.equal(specialMove('TKoopaSpecialSHit'), null)
})

test('the special fall and its forward and back versions are Movement with names', () => {
  assert.equal(getAnimDisplayName(sym('FallSpecial')), 'Fall (Special)')
  assert.equal(getAnimDisplayName(sym('FallSpecialF')), 'Fall (Special Forward)')
  assert.equal(getAnimDisplayName(sym('FallSpecialB')), 'Fall (Special Back)')
  for (const action of ['FallSpecial', 'FallSpecialF', 'FallSpecialB']) assert.equal(getAnimCategory(sym(action)), 'Movement')
})

// Every vanilla fighter's motion names, from the Tracker's fighter data (one file per internal id): the same names
// the AJ archives' figatree symbols carry.
const FIGHTER_DATA = new URL('../../tracker/replays/data/fighters/', import.meta.url)
const vanillaMotions = () => {
  const motions = new Set()
  for (const file of readdirSync(FIGHTER_DATA).filter(name => name.endsWith('.json'))) {
    const text = readFileSync(new URL(file, FIGHTER_DATA), 'utf8')
    for (const [, motion] of text.matchAll(/"motion":"([A-Za-z0-9]+)"/g)) motions.add(motion)
  }
  return motions
}

// 0.9.0 build 8 testers: the angled tilts and smashes, Kirby's swallow and the T<Fighter> motions showed raw.
test('the angled forward tilts and smashes have names and are grounded attacks', () => {
  const names = {
    AttackS3Hi: 'Forward Tilt (Up)', AttackS3HiS: 'Forward Tilt (Up-Middle)', AttackS3S: 'Forward Tilt',
    AttackS3LwS: 'Forward Tilt (Down-Middle)', AttackS3Lw: 'Forward Tilt (Down)',
    AttackS4Hi: 'Forward Smash (Up)', AttackS4HiS: 'Forward Smash (Up-Middle)', AttackS4S: 'Forward Smash',
    AttackS4LwS: 'Forward Smash (Down-Middle)', AttackS4Lw: 'Forward Smash (Down)',
  }
  for (const [action, name] of Object.entries(names)) {
    assert.equal(getAnimDisplayName(sym(action, 'PlyMars5K_Share')), name)
    assert.equal(getAnimCategory(sym(action, 'PlyMars5K_Share')), 'Grounded Attacks', action)
  }
})

test("Kirby's swallow: the opponent's motions and his own have readable names", () => {
  const kirby = action => sym(action, 'PlyKirby5K_Share')
  assert.equal(getAnimDisplayName(kirby('TKirbySpecialNDrink')), 'Swallowed by Kirby')
  assert.equal(getAnimDisplayName(kirby('TKirbySpecialNSpit')), 'Spat Out by Kirby')
  assert.equal(getAnimDisplayName(kirby('SpecialNDrink')), 'Neutral B Swallow')
  assert.equal(getAnimDisplayName(kirby('SpecialNSpit')), 'Neutral B Spit')
  assert.equal(getAnimDisplayName(kirby('EatWait')), 'Mouthful Idle')
  assert.equal(getAnimDisplayName(kirby('EatWalkSlow')), 'Mouthful Walk (Slow)')
  assert.equal(getAnimDisplayName(kirby('EatJump2')), 'Mouthful Jump 2')
  assert.equal(getAnimCategory(kirby('TKirbySpecialNDrink')), 'Grabs & Throws')
  assert.equal(getAnimCategory(kirby('SpecialNDrink')), 'Specials')
})

test("a thrown opponent's motion is named for the fighter throwing and filed with the throws", () => {
  const cases = {
    TKirbyThrowF: 'Thrown by Kirby (Forward Throw)', TMarsThrowLw: 'Thrown by Marth (Down Throw)',
    TSeakThrowB: 'Thrown by Sheik (Back Throw)', TPopoThrowHi: 'Thrown by Ice Climbers (Up Throw)',
    TEmblemThrowF: 'Thrown by Roy (Forward Throw)', TClinkThrowB: 'Thrown by Young Link (Back Throw)',
    TKoopaSpecialSHit: 'Thrown by Bowser (Side B Hit)', TKoopaSpecialAirSEndF: 'Thrown by Bowser (Side B End F, Air)',
    TKoopaThrowLwPeach: 'Thrown by Bowser (Down Throw, Peach)', TCaptainSpecialHi: 'Thrown by C. Falcon (Up B)',
    TMewtwoSpecialAirS: 'Thrown by Mewtwo (Side B, Air)', TYoshiSpecialN: 'Thrown by Yoshi (Neutral B)',
    TDonkeyThrowFWait: 'Thrown by DK (Cargo Hold)', TDonkeyThrowFF: 'Thrown by DK (Cargo Forward Throw)',
  }
  for (const [action, name] of Object.entries(cases)) {
    assert.equal(getAnimDisplayName(sym(action)), name, action)
    assert.equal(getAnimCategory(sym(action)), 'Grabs & Throws', action)
  }
  assert.deepEqual(thrownMove('TKoopaSpecialSHit'), { by: 'Bowser', move: 'SpecialSHit' })
  // not thrown motions: the fighter's own throws and turns, an unknown thrower
  for (const action of ['ThrowF', 'Turn', 'TurnRun', 'TXxThrowF', 'TKirby']) assert.equal(thrownMove(action), null, action)
  assert.equal(getAnimDisplayName(sym('ThrowFF', 'PlyDonkey5K_Share')), 'Cargo Forward Throw')
})

test('every vanilla thrown motion and every angled attack has a name, never its raw action', () => {
  const motions = vanillaMotions()
  const thrown = [...motions].filter(motion => /^T[A-Z]/.test(motion))
  assert.ok(thrown.length > 90, `only ${thrown.length} thrown motions read`)
  for (const motion of thrown) {
    assert.ok(thrownMove(motion), motion)
    assert.match(getAnimDisplayName(sym(motion)), /^(Thrown by [^()]+ \([^()]+\)|Swallowed by Kirby|Spat Out by Kirby)$/, motion)
  }
  for (const motion of [...motions].filter(motion => /^(AttackS[34](Hi|Lw)S?|Eat)/.test(motion))) {
    assert.notEqual(getAnimDisplayName(sym(motion)), motion, motion)
  }
})
