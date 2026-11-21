import test from 'node:test'
import assert from 'node:assert/strict'
import {
  IDLE_CURRENT,
  MODEL_CURRENT,
  canRestoreCurrent,
  createRequestGate,
  currentFromError,
  currentForSelection,
  currentFromResponse,
  currentImageSize,
  currentKey,
  currentPartCards,
  currentLabel,
  currentNote,
  currentPreviewColors,
  loadingCurrent,
  matchInstalledMod,
  readingStatus,
} from './currentExtraState.js'

const FOX_LASER = currentKey('Fox', 'laser')
const FOX_SHINE = currentKey('Fox', 'shine')
const FALCO_LASER = currentKey('Falco', 'laser')

test('afterimage models show a model, restore, and match only an exact unique model recipe', () => {
  const current = currentFromResponse(currentKey('Falco', 'sideb'), {
    status: 'custom', colors: {}, sidebModel: { version: 1, sha256: 'mesh-a' },
  })
  const model = { id: 'spooky', modifications: { sideb_model: { version: 1, sha256: 'mesh-a' } } }
  const colors = { id: 'blue', modifications: { primary: { color: '0099FFFF' } } }
  assert.equal(currentLabel(current), 'Afterimage model')
  assert.equal(currentNote(current), 'Imported Side-B model')
  assert.equal(currentPreviewColors(current), null)
  assert.equal(canRestoreCurrent(current), true)
  assert.equal(matchInstalledMod(current, [colors, model]), model)
  assert.equal(matchInstalledMod(current, [model, { ...model, id: 'duplicate' }]), null)
  assert.equal(matchInstalledMod(current, [colors]), null)
})

test('keys separate fighter and effect', () => {
  assert.notEqual(FOX_LASER, FOX_SHINE)
  assert.notEqual(FOX_LASER, FALCO_LASER)
  assert.equal(FOX_LASER, currentKey('Fox', 'laser'))
})

test('switching effect drops the previous read, even if it answers last', () => {
  const gate = createRequestGate()
  gate.select(FOX_LASER)
  const laserRead = gate.begin(FOX_LASER)
  gate.select(FOX_SHINE)
  const shineRead = gate.begin(FOX_SHINE)
  // shine answers first, laser answers late: only shine may land
  assert.equal(gate.accepts(shineRead), true)
  assert.equal(gate.accepts(laserRead), false)
})

test('switching fighter drops the previous read', () => {
  const gate = createRequestGate()
  gate.select(FOX_LASER)
  const foxRead = gate.begin(FOX_LASER)
  gate.select(FALCO_LASER)
  assert.equal(gate.accepts(foxRead), false)
})

test('a newer read of the same effect wins over an older one', () => {
  const gate = createRequestGate()
  gate.select(FOX_LASER)
  const first = gate.begin(FOX_LASER)
  const second = gate.begin(FOX_LASER) // e.g. the re-read after an install
  assert.equal(gate.accepts(first), false)
  assert.equal(gate.accepts(second), true)
})

test('a read started from a stale closure is refused up front', () => {
  const gate = createRequestGate()
  gate.select(FOX_LASER)
  gate.select(FOX_SHINE)
  assert.equal(gate.begin(FOX_LASER), null)
  assert.equal(gate.accepts(null), false)
})

test('leaving extras mode invalidates everything', () => {
  const gate = createRequestGate()
  gate.select(FOX_LASER)
  const read = gate.begin(FOX_LASER)
  gate.select(null)
  assert.equal(gate.accepts(read), false)
  assert.equal(gate.begin(null), null)
})

test('select reports whether the selection actually changed', () => {
  const gate = createRequestGate()
  assert.equal(gate.select(FOX_LASER), true)
  assert.equal(gate.select(FOX_LASER), false) // same effect re-selected / refreshed
  assert.equal(gate.select(FOX_SHINE), true)
})

test('re-selecting the same effect still invalidates the older read', () => {
  const gate = createRequestGate()
  gate.select(FOX_LASER)
  const old = gate.begin(FOX_LASER)
  gate.select(FOX_LASER)
  assert.equal(gate.accepts(old), false)
})

test('loading and idle never claim Vanilla and never offer restore', () => {
  for (const state of [IDLE_CURRENT, loadingCurrent(FOX_LASER)]) {
    assert.equal(currentLabel(state), 'Loading...')
    assert.equal(canRestoreCurrent(state), false)
    assert.equal(currentPreviewColors(state), null)
  }
})

test('a failed read is an error, not Vanilla', () => {
  const state = currentFromError(FOX_LASER, new Error('Could not find PlFx.dat in MEX project'))
  assert.equal(state.phase, 'error')
  assert.equal(currentLabel(state), "Couldn't read")
  assert.equal(canRestoreCurrent(state), false)
  assert.equal(currentPreviewColors(state), null)
  assert.match(state.error, /PlFx\.dat/)
  assert.ok(currentFromError(FOX_LASER, undefined).error)
})

test('a vanilla read', () => {
  const state = currentFromResponse(FOX_LASER, { success: true, colors: { core: 'FC00' }, isVanilla: true })
  assert.equal(currentLabel(state), 'Vanilla')
  assert.equal(canRestoreCurrent(state), false)
  assert.deepEqual(currentPreviewColors(state), { core: 'FC00' })
})

test('a custom read offers restore', () => {
  const state = currentFromResponse(FOX_LASER, { success: true, colors: { core: '1234' }, isVanilla: false })
  assert.equal(currentLabel(state), 'Custom')
  assert.equal(canRestoreCurrent(state), true)
})

test('a response without isVanilla is not assumed vanilla', () => {
  const state = currentFromResponse(FOX_LASER, { success: true, colors: {} })
  assert.equal(state.isVanilla, false)
  assert.deepEqual(currentPreviewColors(state), {})
})

test('a reading of another effect or fighter is shown as Loading', () => {
  const laser = currentFromResponse(FOX_LASER, { colors: { core: '1234' }, isVanilla: false })
  assert.equal(currentForSelection(laser, FOX_LASER), laser)
  const shown = currentForSelection(laser, FOX_SHINE)
  assert.equal(shown.phase, 'loading')
  assert.equal(shown.key, FOX_SHINE)
  assert.equal(currentPreviewColors(shown), null)
  assert.equal(currentForSelection(laser, FALCO_LASER).phase, 'loading')
  assert.equal(currentForSelection(laser, null), IDLE_CURRENT)
})

test('an installed image effect is labelled as an image, not as a color recolor', () => {
  const state = currentFromResponse(currentKey('Fox', 'shine'), {
    success: true, colors: {}, isVanilla: false, imageInstalled: true,
    image: { width: 64, height: 64, gxFormat: 14 },
  }, 7)
  assert.equal(currentLabel(state), 'Image effect')
  assert.equal(currentPreviewColors(state), null) // no gradient built from empty colors
  assert.equal(canRestoreCurrent(state), true)
  assert.equal(currentImageSize(state), '64x64')
  assert.equal(state.readId, 7)
})

test('an image without a reported size still reads as an image', () => {
  const state = currentFromResponse(FOX_SHINE, { colors: {}, isVanilla: false, imageInstalled: true })
  assert.equal(currentLabel(state), 'Image effect')
  assert.equal(currentImageSize(state), '')
})

test('unit parts become cards in the unit order, with their own verdicts', () => {
  const state = currentFromResponse(currentKey('Fox', 'upb'), {
    success: true, colors: { tip: 'FC00' }, isVanilla: false,
    parts: {
      charge_flames: { colors: { flame_c1: 'FF0000' }, isVanilla: false, vanilla: {} },
      upb_charge_fire: { colors: { color1: 'FF9400' }, isVanilla: true, vanilla: {} },
    },
  })
  const unitParts = [
    { id: 'upb_charge_fire', name: 'Flight Fire Texture' },
    { id: 'charge_flames', name: 'Charge Flames' },
  ]
  const cards = currentPartCards(state, unitParts)
  assert.deepEqual(cards.map(c => [c.id, c.name, c.label]), [
    ['upb_charge_fire', 'Flight Fire Texture', 'Vanilla'],
    ['charge_flames', 'Charge Flames', 'Custom'],
  ])
  assert.deepEqual(cards[1].colors, { flame_c1: 'FF0000' })
  assert.equal(cards[0].type, unitParts[0])
})

test('parts the read did not report are left out, not shown as vanilla', () => {
  const state = currentFromResponse(FOX_LASER, { colors: {}, isVanilla: true, parts: {} })
  assert.deepEqual(currentPartCards(state, [{ id: 'charge_flames', name: 'Charge Flames' }]), [])
})

test('no part cards before a read lands or for non-units', () => {
  const parts = [{ id: 'charge_flames', name: 'Charge Flames' }]
  assert.deepEqual(currentPartCards(loadingCurrent(FOX_LASER), parts), [])
  assert.deepEqual(currentPartCards(currentFromError(FOX_LASER, new Error('x')), parts), [])
  assert.deepEqual(currentPartCards(currentFromResponse(FOX_LASER, { colors: {}, isVanilla: true }), parts), [])
  assert.deepEqual(currentPartCards(currentFromResponse(FOX_LASER, { colors: {}, isVanilla: true, parts: {} }), undefined), [])
})

test('status from the backend wins; older readings fall back to isVanilla', () => {
  assert.equal(readingStatus({ status: 'unknown', isVanilla: false }), 'unknown')
  assert.equal(readingStatus({ status: 'vanilla', isVanilla: true }), 'vanilla')
  assert.equal(readingStatus({ isVanilla: true }), 'vanilla')
  assert.equal(readingStatus({ isVanilla: false }), 'custom')
  assert.equal(readingStatus({ status: 'bogus', isVanilla: true }), 'vanilla')
})

test('an unknown reading says so, draws no guessed preview, and still offers restore', () => {
  const state = currentFromResponse(FOX_LASER, {
    success: true, colors: {}, isVanilla: false, status: 'unknown',
    unknownLayers: ['wide', 'thin'],
  })
  assert.equal(currentLabel(state), 'Unknown')
  assert.equal(currentPreviewColors(state), null)
  assert.equal(canRestoreCurrent(state), true)
  assert.match(currentNote(state), /locate/)
  const detailed = currentFromResponse(FOX_LASER, { status: 'unknown', detail: 'No reference texture' })
  assert.equal(currentNote(detailed), 'No reference texture')
})

test('a custom reading with unreadable layers keeps its preview and notes the gap', () => {
  const state = currentFromResponse(FOX_LASER, {
    colors: { wide: '1234' }, isVanilla: false, status: 'custom', unknownLayers: ['thin'],
  })
  assert.equal(currentLabel(state), 'Custom')
  assert.deepEqual(currentPreviewColors(state), { wide: '1234' })
  assert.equal(currentNote(state), "1 layer couldn't be read")
  assert.equal(currentNote(currentFromResponse(FOX_LASER, {
    status: 'custom', unknownLayers: ['a', 'b'] })), "2 layers couldn't be read")
})

test('notes for plain, image, loading and error readings', () => {
  assert.equal(currentNote(currentFromResponse(FOX_LASER, { status: 'vanilla' })), '')
  assert.equal(currentNote(loadingCurrent(FOX_LASER)), '')
  assert.equal(currentNote(currentFromError(FOX_LASER, new Error('x'))), 'The project file could not be read')
  assert.equal(currentNote(currentFromResponse(FOX_SHINE, {
    imageInstalled: true, image: { width: 64, height: 32 } })), '64x32 image')
})

test('an unknown part card has no preview colors', () => {
  const state = currentFromResponse(currentKey('Fox', 'upb'), {
    status: 'unknown', colors: {}, parts: {
      charge_flames: { status: 'unknown', colors: {}, isVanilla: false },
    },
  })
  const [card] = currentPartCards(state, [{ id: 'charge_flames', name: 'Charge Flames' }])
  assert.equal(card.label, 'Unknown')
  assert.equal(card.colors, null)
})

test('a texture recolor reading is marked approximate', () => {
  const state = currentFromResponse(currentKey('Mario', 'mario_coins'), {
    status: 'custom', colors: { color1: '00FF40' }, isVanilla: false, approximate: true,
  })
  assert.equal(currentLabel(state), 'Custom')
  assert.match(currentNote(state), /Approximate/)
  const vanilla = currentFromResponse(currentKey('Mario', 'mario_coins'), {
    status: 'vanilla', colors: { color1: 'FFD700' }, isVanilla: true, approximate: false,
  })
  assert.equal(currentNote(vanilla), '')
})

test('model swaps never claim a verdict', () => {
  assert.equal(MODEL_CURRENT.label, "Can't detect")
  assert.doesNotMatch(MODEL_CURRENT.label, /Vanilla|Custom/)
})

test('an undetectable reading (shield without reference) shows the backend detail', () => {
  const state = currentFromResponse(currentKey('Fox', 'common_shield'), {
    status: 'unknown', colors: {}, isVanilla: false,
    detail: 'No vanilla reference to compare the texture with',
  })
  assert.equal(currentLabel(state), 'Unknown')
  assert.equal(currentNote(state), 'No vanilla reference to compare the texture with')
  assert.equal(currentPreviewColors(state), null)
})

const laserMod = (id, wide, thin) => ({
  id, name: id, modifications: { wide: { color: wide }, thin: { color: thin } },
})

test('names the vault mod whose recipe is exactly what is installed', () => {
  const state = currentFromResponse(FOX_LASER, {
    status: 'custom', colors: { wide: 'F800', thin: '07E0' }, isVanilla: false,
  })
  const red = laserMod('red', 'f800', '07e0')
  assert.equal(matchInstalledMod(state, [laserMod('blue', '001F', '07E0'), red]), red)
})

test('no name when nothing or more than one mod matches', () => {
  const state = currentFromResponse(FOX_LASER, {
    status: 'custom', colors: { wide: 'F800', thin: '07E0' },
  })
  assert.equal(matchInstalledMod(state, [laserMod('blue', '001F', '07E0')]), null)
  assert.equal(matchInstalledMod(state, [laserMod('a', 'F800', '07E0'), laserMod('b', 'F800', '07E0')]), null)
  assert.equal(matchInstalledMod(state, []), null)
  assert.equal(matchInstalledMod(state, undefined), null)
})

test('a mod missing one of the read layers does not match', () => {
  const state = currentFromResponse(FOX_LASER, {
    status: 'custom', colors: { wide: 'F800', thin: '07E0', outline: '0000' },
  })
  assert.equal(matchInstalledMod(state, [laserMod('red', 'F800', '07E0')]), null)
})

test('never names a mod for vanilla, unknown, partial, image or approximate readings', () => {
  const mod = laserMod('red', 'F800', '07E0')
  const colors = { wide: 'F800', thin: '07E0' }
  for (const data of [
    { status: 'vanilla', colors },
    { status: 'unknown', colors },
    { status: 'custom', colors, unknownLayers: ['outline'] },
    { status: 'custom', colors, approximate: true },
    { status: 'custom', colors: {}, imageInstalled: true },
  ]) {
    assert.equal(matchInstalledMod(currentFromResponse(FOX_LASER, data), [mod]), null)
  }
  assert.equal(matchInstalledMod(loadingCurrent(FOX_LASER), [mod]), null)
})

test('unit parts must match too', () => {
  const read = parts => currentFromResponse(currentKey('Fox', 'upb'), {
    status: 'custom', colors: { tip: 'F800' }, parts,
  })
  const withFlames = {
    id: 'm', name: 'm', modifications: {
      tip: { color: 'F800' }, parts: { charge_flames: { flame_c1: { color: 'FF0000' } } },
    },
  }
  const flamesCustom = { charge_flames: { status: 'custom', colors: { flame_c1: 'FF0000' } } }
  const flamesOther = { charge_flames: { status: 'custom', colors: { flame_c1: '00FF00' } } }
  const flamesVanilla = { charge_flames: { status: 'vanilla', colors: { flame_c1: 'FFAA00' } } }
  assert.equal(matchInstalledMod(read(flamesCustom), [withFlames]), withFlames)
  assert.equal(matchInstalledMod(read(flamesOther), [withFlames]), null)
  const noParts = { id: 'n', name: 'n', modifications: { tip: { color: 'F800' } } }
  assert.equal(matchInstalledMod(read(flamesVanilla), [noParts]), noParts)
  assert.equal(matchInstalledMod(read(flamesCustom), [noParts]), null)
  const flamesUnknown = { charge_flames: { status: 'unknown', colors: {} } }
  assert.equal(matchInstalledMod(read(flamesUnknown), [withFlames]), null)
})
