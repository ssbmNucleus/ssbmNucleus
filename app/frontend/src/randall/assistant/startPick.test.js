// What a starting-point pick adds to an outgoing message's context, in the exact
// shapes the backend reads: assistant_bp whitelists `selection` and `fighter`;
// workflows.picked_costume opens ONE selected costume ({character, id|skin_id}
// or {character, vanilla: true, color}); studio_import.chosen_fighter reads
// `fighter` back from the chat's user messages.
import assert from 'node:assert/strict'
import test from 'node:test'
import { contextNotes, outgoingContext, pickerFor, pickPlaceholder, pickText, selectionItem } from './startPick.js'

const TASKS = [
  { id: 'recolor_part', label: 'Retexture a costume', picker: 'costume' },
  { id: 'model_import', label: 'Import a model', picker: 'fighter' },
]
const VAULT = { kind: 'vault', character: 'Fox', id: 'fox-blue', name: 'Blue Hoodie', image: '/storage/Fox/fox-blue_csp.png' }
const STOCK = { kind: 'stock', character: 'Fox', code: 'PlFxOr', color: 'Or', name: 'Orange', image: '/vanilla/Fox/PlFxOr/csp.png' }
const FIGHTER = { kind: 'fighter', character: 'Marth', image: '/vanilla/Marth/css_icon.png' }
const APP = { page: 'storage', character: 'Fox', stage: null }

test('the picker comes from the task’s status row', () => {
  assert.equal(pickerFor(TASKS, 'recolor_part'), 'costume')
  assert.equal(pickerFor(TASKS, 'model_import'), 'fighter')
  assert.equal(pickerFor(TASKS, 'find_mod'), null, 'a retired task has no picker')
  assert.equal(pickerFor(TASKS, null), null)
  assert.equal(pickerFor([{ id: 'x', picker: 'something-new' }], 'x'), null)
  assert.equal(pickerFor(undefined, 'recolor_part'), null)
})

test('a vault costume goes as the selected-item shape a Vault selection sends', () => {
  assert.deepEqual(selectionItem(VAULT), { id: 'fox-blue', character: 'Fox', name: 'Blue Hoodie' })
  const sent = outgoingContext({ context: APP, task: 'recolor_part', picker: 'costume', pick: VAULT })
  assert.deepEqual(sent, { ...APP, selection: [{ id: 'fox-blue', character: 'Fox', name: 'Blue Hoodie' }], files: [], task: 'recolor_part' })
  // The exact JSON the panel posts (key order included).
  assert.equal(JSON.stringify(sent),
    '{"page":"storage","character":"Fox","stage":null,"selection":[{"id":"fox-blue","character":"Fox","name":"Blue Hoodie"}],"files":[],"task":"recolor_part"}')
})

test('a stock costume goes as {character, vanilla: true, color}, never with an id', () => {
  const item = selectionItem(STOCK)
  assert.deepEqual(item, { character: 'Fox', vanilla: true, color: 'Or', name: 'Orange (stock)' })
  assert.equal('id' in item || 'skin_id' in item, false)
  assert.deepEqual(outgoingContext({ task: 'recolor_part', picker: 'costume', pick: STOCK }).selection, [item])
})

test('the fighter goes as context.fighter', () => {
  const sent = outgoingContext({ context: APP, task: 'model_import', picker: 'fighter', pick: FIGHTER,
    files: [{ file_id: 'f1', name: 'goku.zip' }] })
  assert.deepEqual(sent, { ...APP, selection: [], files: [{ file_id: 'f1', name: 'goku.zip' }], task: 'model_import', fighter: 'Marth' })
  // A costume pick under the fighter picker (or the reverse) sends nothing.
  assert.equal('fighter' in outgoingContext({ picker: 'fighter', pick: VAULT }), false)
  assert.deepEqual(outgoingContext({ picker: 'costume', pick: FIGHTER }).selection, [])
})

test('the pick goes with the first message only, like the task', () => {
  for (const [picker, pick] of [['costume', VAULT], ['fighter', FIGHTER]]) {
    const later = outgoingContext({ context: APP, task: 'recolor_part', locked: true, picker, pick })
    assert.deepEqual(later, { ...APP, selection: [], files: [] }, picker)
  }
})

test('nothing picked: the context is exactly what the panel sent before pickers', () => {
  const editor = { name: 'Fox', texture: null }
  const selection = [{ id: 'a', character: 'Falco', name: 'A' }]
  assert.deepEqual(outgoingContext({ context: APP, selection, task: 'recolor_part', editor, picker: 'costume', pick: null }),
    { ...APP, selection, files: [], task: 'recolor_part', editor })
  assert.deepEqual(outgoingContext({ context: APP }), { ...APP, selection: [], files: [] })
})

test('a picked costume is THE selection: attached skins are replaced, so the backend opens it directly', () => {
  const chosen = [{ id: 'fox-blue', character: 'Fox', name: 'Blue Hoodie' }]
  assert.deepEqual(outgoingContext({ selection: chosen, picker: 'costume', pick: VAULT }).selection, chosen)
  const other = [{ id: 'x', character: 'Falco', name: 'X' }, { id: 'y', character: 'Fox', name: 'Y' }]
  assert.deepEqual(outgoingContext({ selection: other, picker: 'costume', pick: STOCK }).selection,
    [{ character: 'Fox', vanilla: true, color: 'Or', name: 'Orange (stock)' }])
  assert.equal(outgoingContext({ selection: other, picker: 'costume', pick: VAULT }).selection.length, 1)
  // No pick: attached skins go untouched; later messages never replace them.
  assert.deepEqual(outgoingContext({ selection: other, picker: 'costume', pick: null }).selection, other)
  assert.deepEqual(outgoingContext({ selection: other, picker: 'costume', pick: VAULT, locked: true }).selection, other)
})

test('placeholders and the sent message’s notes name the pick', () => {
  assert.equal(pickPlaceholder('costume', VAULT), 'What look do you want for Fox · Blue Hoodie?')
  assert.equal(pickPlaceholder('costume', STOCK), 'What look do you want for Fox · Orange (stock)?')
  assert.equal(pickPlaceholder('fighter', FIGHTER), 'Attach the model for Marth and send it.')
  assert.equal(pickPlaceholder('costume', null), null)
  assert.deepEqual(contextNotes({ selection: [selectionItem(VAULT)] }), ['Fox · Blue Hoodie'])
  assert.deepEqual(contextNotes({ selection: [selectionItem(STOCK)], fighter: 'Marth' }), ['Fox · Orange (stock)', 'For Marth'])
  assert.deepEqual(contextNotes({ selection: [{ id: 'a' }, { id: 'b' }] }), ['2 attached skins'])
  assert.deepEqual(contextNotes({ selection: [{ id: 'a' }] }), ['1 attached skin'])
  assert.deepEqual(contextNotes({}), [])
  assert.deepEqual(contextNotes(undefined), [])
})

// "Retexture a stage": the pick is ONE selection entry of kind 'stage', in the shape
// assistant_bp._stage_item checks and stage_start.picked_stage opens.
const NIGHT = { kind: 'stage', stage: 'GrNBa', stageName: 'Battlefield', id: 'night-sky-1a2b', name: 'Night Sky',
  image: '/storage/das/battlefield/night-sky-1a2b_screenshot.png' }
const STOCK_FD = { kind: 'stage', stage: 'GrNLa', stageName: 'Final Destination', vanilla: true, name: 'Final Destination',
  image: '/vanilla/stages/final destination.png' }

test('the stage picker comes from the task’s status row', () => {
  assert.equal(pickerFor([...TASKS, { id: 'recolor_stage', label: 'Retexture a stage', picker: 'stage' }], 'recolor_stage'), 'stage')
  assert.equal(pickerFor([{ id: 'stage_import', label: 'Import a stage model', picker: null, available: false }], 'stage_import'), null)
})

test('a picked stage goes as the single selection entry, in the exact shape the backend reads', () => {
  assert.deepEqual(selectionItem(NIGHT), { kind: 'stage', stage: 'GrNBa', id: 'night-sky-1a2b', name: 'Battlefield · Night Sky' })
  assert.deepEqual(selectionItem(STOCK_FD), { kind: 'stage', stage: 'GrNLa', vanilla: true, name: 'Final Destination (stock)' })
  assert.equal('id' in selectionItem(STOCK_FD), false)
  const attached = [{ id: 'x', character: 'Falco', name: 'X' }]
  const sent = outgoingContext({ context: APP, selection: attached, task: 'recolor_stage', picker: 'stage', pick: NIGHT })
  // The exact JSON the panel posts (key order included): the pick replaces attached skins.
  assert.equal(JSON.stringify(sent),
    '{"page":"storage","character":"Fox","stage":null,"selection":[{"kind":"stage","stage":"GrNBa","id":"night-sky-1a2b","name":"Battlefield · Night Sky"}],"files":[],"task":"recolor_stage"}')
  assert.deepEqual(outgoingContext({ task: 'recolor_stage', picker: 'stage', pick: STOCK_FD }).selection,
    [{ kind: 'stage', stage: 'GrNLa', vanilla: true, name: 'Final Destination (stock)' }])
  // First message only; and a pick of the other kind is never sent under a picker.
  assert.deepEqual(outgoingContext({ context: APP, task: 'recolor_stage', locked: true, picker: 'stage', pick: NIGHT }),
    { ...APP, selection: [], files: [] })
  assert.deepEqual(outgoingContext({ picker: 'stage', pick: VAULT }).selection, [])
  assert.deepEqual(outgoingContext({ picker: 'costume', pick: NIGHT }).selection, [])
  assert.deepEqual(outgoingContext({ picker: 'stage', pick: null, selection: attached }).selection, attached)
})

test('the stage pick names itself in the placeholder, the chip and the sent note', () => {
  assert.equal(pickPlaceholder('stage', NIGHT), 'What colors do you want for Battlefield · Night Sky?')
  assert.equal(pickPlaceholder('stage', STOCK_FD), 'What colors do you want for Final Destination (stock)?')
  assert.equal(pickPlaceholder('stage', VAULT), null)
  assert.equal(pickText(NIGHT), 'Battlefield · Night Sky')
  assert.equal(pickText(VAULT), 'Fox · Blue Hoodie')
  assert.equal(pickText(FIGHTER), 'Marth')
  assert.deepEqual(contextNotes({ selection: [selectionItem(NIGHT)] }), ['Battlefield · Night Sky'])
  assert.deepEqual(contextNotes({ selection: [selectionItem(STOCK_FD)] }), ['Final Destination (stock)'])
})

test('AI Choice: no fighter in the context, byte-identical to no pick; the control text and placeholder name it', () => {
  const ai = { kind: 'fighter', auto: true, character: '', image: null }
  const args = { context: APP, task: 'model_import', picker: 'fighter', files: [{ file_id: 'f1', name: 'goku.zip' }] }
  const sent = outgoingContext({ ...args, pick: ai })
  assert.equal('fighter' in sent, false)
  assert.equal(JSON.stringify(sent), JSON.stringify(outgoingContext({ ...args, pick: null })))
  assert.equal(pickText(ai), 'AI Choice')
  assert.equal(pickPlaceholder('fighter', ai), 'Attach a model. Randall picks the fighter.')
  assert.deepEqual(contextNotes(sent), [])
})
