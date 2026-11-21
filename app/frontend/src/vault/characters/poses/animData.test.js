import test from 'node:test'
import assert from 'node:assert/strict'
import {
  ANIM_NAMES, ANIM_CATEGORIES, extractAnimName, getAnimDisplayName, getAnimCategory, getDefaultCostumeCode,
} from './animData.js'
import { DEFAULT_CHARACTERS } from '../../../shared/data/defaultCharacters.js'
import * as viewer from '../../../shared/viewer/animationNames.js'

// AJ animation symbols as the viewer lists them, e.g. PlyFox5K_Share_ACTION_Wait1_figatree
const sym = (action, prefix = 'PlyFox5K_Share') => `${prefix}_ACTION_${action}_figatree`

test('an animation is labelled with its friendly name for any character', () => {
  for (const prefix of ['PlyFox5K_Share', 'PlyMars5K_Share', 'PlyKirby5K_Share']) {
    assert.equal(extractAnimName(sym('Wait1', prefix)), 'Wait1')
    assert.equal(getAnimDisplayName(sym('Wait1', prefix)), ANIM_NAMES.Wait1)
  }
})

test('an uncatalogued animation shows its bare action name, never the raw symbol', () => {
  assert.equal(getAnimDisplayName(sym('ItemHammerWait')), 'ItemHammerWait')
  // anything that is not an ACTION figatree symbol passes through untouched
  assert.equal(getAnimDisplayName('MyCustomAnim'), 'MyCustomAnim')
})

test('the category filter files every catalogued animation under its own category, unknown ones under Other', () => {
  for (const [category, actions] of Object.entries(ANIM_CATEGORIES)) {
    for (const action of actions) {
      assert.equal(getAnimCategory(sym(action)), category, `${action} filed under the wrong category`)
    }
  }
  assert.equal(getAnimCategory(sym('ItemHammerWait')), 'Other')
})

test('every special move is a Special with a name that keeps its air and suffix (bug 11-19)', () => {
  // Jigglypuff's air Pound and Rest, Fox's Firefox charge, and suffixed starts the table does not list
  assert.equal(getAnimCategory(sym('SpecialAirS', 'PlyPurin5K_Share')), 'Specials')
  assert.equal(getAnimDisplayName(sym('SpecialAirS', 'PlyPurin5K_Share')), 'Side B (Air)')
  assert.equal(getAnimDisplayName(sym('SpecialAirLwR', 'PlyPurin5K_Share')), 'Down B R (Air)')
  assert.equal(getAnimDisplayName(sym('SpecialAirNStartL', 'PlyPurin5K_Share')), 'Neutral B Start L (Air)')
  assert.equal(getAnimDisplayName(sym('SpecialHiHold')), 'Up B Hold')
  assert.equal(getAnimDisplayName(sym('SpecialHiHoldAir')), 'Up B Hold (Air)')
  assert.equal(getAnimDisplayName(sym('SpecialLwEnd')), 'Down B End')
  for (const action of ['SpecialHiHold', 'SpecialHiHoldAir', 'SpecialAirNStartL', 'SpecialSEnd', 'SpecialAirLwLoop']) {
    assert.equal(getAnimCategory(sym(action)), 'Specials', action)
  }
  // not specials: the special fall and its landing stay where they were
  assert.equal(getAnimCategory(sym('FallSpecial')), 'Movement')
  assert.equal(getAnimCategory(sym('SpecialStart')), 'Other')
})

test('the Pose Manager and the 3D viewer name and file every special the same way (0.9.0 hand-check)', () => {
  // the hand-check found "Neutral B" here and "Neutral Special" in the viewer, and Samus's slotless Special /
  // SpecialAir, Kirby's copies and the special fall's F/B versions under raw names. Shapes from every vanilla AJ.
  const actions = [
    'SpecialN', 'SpecialAirN', 'SpecialNStart', 'SpecialAirNEndR', 'SpecialHiHoldAir', 'SpecialSAir', 'SpecialLw2',
    'SpecialS1', 'SpecialAirS3Hi', 'SpecialNCansel', 'SpecialAirNCancel', 'Special', 'SpecialAir',
    'MrSpecialN', 'FxSpecialAirNStart', 'PrSpecialNStartR', 'SkSpecialNCancel', 'GwSpecialAirN',
  ]
  for (const action of actions) {
    assert.equal(getAnimCategory(sym(action)), 'Specials', action)
    assert.equal(viewer.getAnimCategory(sym(action)), 'Specials', action)
    assert.equal(getAnimDisplayName(sym(action)), viewer.getAnimDisplayName(sym(action)), action)
    assert.match(getAnimDisplayName(sym(action)), /(Neutral|Side|Up|Down) B\b/, action)
  }
  assert.equal(getAnimDisplayName(sym('Special', 'PlySamus5K_Share')), 'Side B Smash')
  assert.equal(getAnimDisplayName(sym('SpecialAir', 'PlySamus5K_Share')), 'Side B Smash (Air)')
  for (const [action, name] of [['FallSpecialF', 'Fall (Special Forward)'], ['FallSpecialB', 'Fall (Special Back)']]) {
    assert.equal(getAnimDisplayName(sym(action)), name)
    assert.equal(viewer.getAnimDisplayName(sym(action)), name)
    assert.equal(getAnimCategory(sym(action)), 'Movement')
  }
})

test('the Pose Manager names the angled attacks, Kirby\'s swallow and thrown motions as the viewer does (0.9.0 build 8)', () => {
  const kirby = action => sym(action, 'PlyKirby5K_Share')
  const named = {
    AttackS3Hi: 'Forward Tilt (Up)', AttackS3HiS: 'Forward Tilt (Up-Middle)', AttackS3LwS: 'Forward Tilt (Down-Middle)',
    AttackS3Lw: 'Forward Tilt (Down)', AttackS4Hi: 'Forward Smash (Up)', AttackS4HiS: 'Forward Smash (Up-Middle)',
    AttackS4LwS: 'Forward Smash (Down-Middle)', AttackS4Lw: 'Forward Smash (Down)',
    AttackS3S: 'Forward Tilt', AttackS4S: 'Forward Smash',
    TKirbySpecialNDrink: 'Swallowed by Kirby', TKirbySpecialNSpit: 'Spat Out by Kirby', SpecialNDrink: 'Neutral B Swallow',
    EatWalkFast: 'Mouthful Walk (Fast)', TKirbyThrowHi: 'Thrown by Kirby (Up Throw)',
    TKoopaSpecialSHit: 'Thrown by Bowser (Side B Hit)', TGamewatchThrowF: 'Thrown by Mr. Game & Watch (Forward Throw)',
  }
  for (const [action, name] of Object.entries(named)) {
    assert.equal(getAnimDisplayName(kirby(action)), name, action)
    assert.equal(viewer.getAnimDisplayName(kirby(action)), name, action)
  }
  // a thrown opponent's motion is a Grab here (its own button), Grabs & Throws in the viewer
  for (const action of ['TKirbySpecialNDrink', 'TKirbyThrowF', 'TKoopaSpecialAirSHit']) {
    assert.equal(getAnimCategory(kirby(action)), 'Grabs', action)
    assert.equal(viewer.getAnimCategory(kirby(action)), 'Grabs & Throws', action)
  }
})

test('every animation offered in a category has a friendly name', () => {
  const unnamed = Object.values(ANIM_CATEGORIES).flat().filter(action => !(action in ANIM_NAMES))
  assert.deepEqual(unnamed, [])
})

test('vanilla characters open the pose editor on their default costume', () => {
  // DEFAULT_CHARACTERS is the vault's own character list (names as the vault shows them)
  for (const [character, { defaultCostume }] of Object.entries(DEFAULT_CHARACTERS)) {
    assert.equal(getDefaultCostumeCode(character), defaultCostume, character)
  }
})

test('Mr. Game & Watch opens the pose editor on his default costume', () => {
  assert.equal(getDefaultCostumeCode('Mr. Game & Watch'), DEFAULT_CHARACTERS['Mr. Game & Watch'].defaultCostume)
})

test('custom characters have no vanilla default costume to fall back to', () => {
  assert.equal(getDefaultCostumeCode('custom_characters/sonic/skins'), null)
  assert.equal(getDefaultCostumeCode(undefined), null)
})
