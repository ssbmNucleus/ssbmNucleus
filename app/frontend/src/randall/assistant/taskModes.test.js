import test from 'node:test'
import assert from 'node:assert/strict'
import { followUpFor, isStartable, launchableTasks, labelFor, mismatchOf, placeholderFor, previousUserText, showStartAnother, startableTasks, taskOf, terminalReceipt } from './taskModes.js'

// What status.tasks serves since 2026-10-03: two starting points, each naming its picker.
const TASKS = [
  { id: 'recolor_part', label: 'Retexture a costume', placeholder: 'Which costume, and what look?', hint: 'Pick a costume.', picker: 'costume' },
  { id: 'model_import', label: 'Import a model', placeholder: 'Attach a model.', hint: 'Turn a 3D model into a costume.', picker: 'fighter' },
]
// Chats stored before then may carry these retired task ids.
const RETIRED = ['find_mod', 'menu_background']
const user = (content, context = {}) => ({ role: 'user', content, context })
// deliver_to_game returns TaskResult.to_dict() as the tool result itself.
const nothing = { prepared: false, exported: false, installed: false, previewed: false }
const delivery = (result, status = 'done') => ({ name: 'deliver_to_game', status, result: { workflow: 'deliver_to_game', contracts_version: 1, ...result } })
const DELIVERED = delivery({ state: 'completed', outcome: 'success', achieved: { prepared: true, exported: true, installed: true, previewed: false } })
// deliver.py `_undecided_envelope`: stopped to ask which copy / about online risk.
const UNDECIDED = delivery({ state: 'waiting_decision', outcome: null, achieved: nothing,
  facts: { what_changed: 'Nothing yet. I stopped to ask.', where: 'Nowhere yet.' },
  next: { kind: 'decision', prompt: 'Which game copy?', allowed_responses: [] } })
const BLOCKED = delivery({ state: 'completed', outcome: 'blocked', achieved: nothing })
const PREPARED_ONLY = delivery({ state: 'completed', outcome: 'success',
  achieved: { prepared: true, exported: false, installed: false, previewed: false }, facts: { requested_outcome: 'prepare' } })
const SAVED = { name: 'save_mod_copy', status: 'done', result: {} }
const reply = (tools = [], extra = {}) => ({ role: 'assistant', content: 'ok', status: 'done', tools, ...extra })

test('launchable tasks come from status and degrade to none', () => {
  assert.deepEqual(launchableTasks(null), [])
  assert.deepEqual(launchableTasks({}), [])
  assert.deepEqual(launchableTasks({ tasks: 'nope' }), [])
  assert.deepEqual(launchableTasks({ tasks: [{ id: 'find_mod' }, null, { label: 'x' }, TASKS[1]] }), [TASKS[1]])
  assert.equal(launchableTasks({ tasks: TASKS }).length, 2)
})

test('a chat task comes from the chat row, then the first user message only', () => {
  assert.equal(taskOf({ task: 'find_mod' }, [user('hi', { task: 'recolor_part' })]), 'find_mod')
  assert.equal(taskOf({ task: null }, [user('hi', { task: 'recolor_part' }), user('again')]), 'recolor_part')
  // As the backend's recipes.chat_task: a later message's task never counts.
  assert.equal(taskOf({ task: null }, [user('hi'), user('again', { task: 'recolor_part' })]), null)
  assert.equal(taskOf({}, [user('hi', { task: '' }), user('again', { task: 'find_mod' })]), null)
  assert.equal(taskOf({}, [reply(), user('hi', { task: 'menu_background' })]), 'menu_background')
  assert.equal(taskOf(null, [user('hi')]), null)
  assert.equal(taskOf(undefined, undefined), null)
})

test('terminal receipts follow the contract table and need a finished tool', () => {
  const saved = { name: 'save_mod_copy', status: 'done', result: {} }
  assert.equal(terminalReceipt('recolor_part', reply([saved])), saved)
  assert.equal(terminalReceipt('recolor_part', reply([{ ...saved, status: 'running' }])), null)
  assert.equal(terminalReceipt('recolor_part', reply([{ ...saved, status: 'error' }])), null)
  // Delivering the recolor (the "Put it in my game" chip) also finishes it.
  assert.equal(terminalReceipt('recolor_part', reply([DELIVERED])), DELIVERED)
  assert.equal(terminalReceipt('recolor_part', reply([{ ...DELIVERED, status: 'running' }])), null)
  // The studio owns the import's completion, so it never offers "Start another".
  assert.equal(terminalReceipt('model_import', reply([{ name: 'save_mod_copy', status: 'done' }])), null)
  assert.equal(terminalReceipt(null, reply([saved])), null)
  assert.equal(terminalReceipt('recolor_part', null), null)
})

test('only a delivery that put the costume in the game is terminal', () => {
  assert.equal(terminalReceipt('recolor_part', reply([UNDECIDED])), null)
  assert.equal(terminalReceipt('recolor_part', reply([BLOCKED])), null)
  assert.equal(terminalReceipt('recolor_part', reply([PREPARED_ONLY])), null)
  // The model path today: prepare raised "which copy" and the engine stored an error.
  assert.equal(terminalReceipt('recolor_part', reply([delivery({ error: 'Which game copy?' }, 'error')])), null)
  // A plain result with no envelope proves nothing about the game.
  assert.equal(terminalReceipt('recolor_part', reply([{ name: 'deliver_to_game', status: 'done', result: {} }])), null)
  // `play` ends partial (the game is not running yet) but the costume IS installed.
  const played = delivery({ state: 'completed', outcome: 'partial', achieved: { prepared: true, exported: true, installed: true, previewed: false } })
  assert.equal(terminalReceipt('recolor_part', reply([played])), played)
})

test('the LAST terminal step in a reply decides', () => {
  // Saved then delivered: the delivery is the receipt, so no "Put it in my game".
  assert.equal(terminalReceipt('recolor_part', reply([SAVED, DELIVERED])), DELIVERED)
  assert.equal(followUpFor('recolor_part', terminalReceipt('recolor_part', reply([SAVED, DELIVERED]))), null)
  // Saved, then a delivery that stopped to ask: the task waits on that answer.
  assert.equal(terminalReceipt('recolor_part', reply([SAVED, UNDECIDED])), null)
  assert.equal(terminalReceipt('recolor_part', reply([SAVED, BLOCKED])), null)
  // A failed later save does not undo an earlier one that finished.
  assert.equal(terminalReceipt('recolor_part', reply([SAVED, { ...SAVED, status: 'error' }])), SAVED)
  // Under the saving reply alone the chip is offered.
  assert.deepEqual(followUpFor('recolor_part', terminalReceipt('recolor_part', reply([SAVED]))),
    { label: 'Put it in my game', draft: 'Put it in my game' })
})

test('"Start another" waits for a finished last reply with the receipt, and not busy', () => {
  const done = [user('make mario red', { task: 'recolor_part' }), reply([{ name: 'save_mod_copy', status: 'done' }])]
  assert.equal(showStartAnother('recolor_part', done, false), true)
  assert.equal(showStartAnother('recolor_part', done, true), false)
  assert.equal(showStartAnother(null, done, false), false)
  assert.equal(showStartAnother('model_import', done, false), false)
  const running = [done[0], { ...done[1], status: 'running' }]
  assert.equal(showStartAnother('recolor_part', running, false), false)
  // A newer user message means the receipt is no longer the last word.
  assert.equal(showStartAnother('recolor_part', [...done, user('now blue')], false), false)
  // The receipt must be in the LAST reply, not an earlier one.
  assert.equal(showStartAnother('recolor_part', [...done, user('thanks'), reply()], false), false)
  assert.equal(showStartAnother('recolor_part', [], false), false)
  // After "Put it in my game" the delivery reply keeps the row.
  const delivered = [...done, user('Put it in my game'), reply([DELIVERED])]
  assert.equal(showStartAnother('recolor_part', delivered, false), true)
  // ...but not while that delivery is waiting on "which copy?".
  assert.equal(showStartAnother('recolor_part', [...done, user('Put it in my game'), reply([UNDECIDED])], false), false)
})

test('only a saved recolor offers putting the result in the game', () => {
  const chip = { label: 'Put it in my game', draft: 'Put it in my game' }
  assert.deepEqual(followUpFor('recolor_part'), chip)
  assert.deepEqual(followUpFor('recolor_part', { name: 'save_mod_copy', status: 'done' }), chip)
  // Under the delivery itself there is nothing left to put in the game.
  assert.equal(followUpFor('recolor_part', { name: 'deliver_to_game', status: 'done' }), null)
  // An imported model is not delivered from this row.
  assert.equal(followUpFor('model_import'), null)
  assert.equal(followUpFor(null), null)
  assert.equal(followUpFor('deliver_to_game'), null)
})

test('a mismatch is read from the reply routing only', () => {
  assert.deepEqual(mismatchOf(reply([], { routing: { declared_task: 'recolor_part', task_mismatch: 'model_import' } })), { family: 'model_import' })
  assert.equal(mismatchOf(reply([], { routing: { declared_task: 'recolor_part', task_mismatch: null } })), null)
  assert.equal(mismatchOf(reply()), null)
  assert.equal(mismatchOf({ role: 'user', routing: { task_mismatch: 'find_mod' } }), null)
  assert.equal(mismatchOf(null), null)
})

test('the mismatch draft is the user message before the reply', () => {
  const messages = [user('first'), reply(), user('find me a fox skin'), reply()]
  assert.equal(previousUserText(messages, 3), 'find me a fox skin')
  assert.equal(previousUserText(messages, 1), 'first')
  assert.equal(previousUserText(messages, 0), '')
})

test('labels and placeholders fall back when the build does not offer a task', () => {
  assert.equal(labelFor(TASKS, 'model_import'), 'Import a model')
  assert.equal(labelFor(TASKS, 'deliver_to_game'), null)
  assert.equal(labelFor([], 'recolor_part'), null)
  assert.equal(labelFor(TASKS, null), null)
  assert.equal(placeholderFor(TASKS, 'recolor_part', 'Message Randall...'), 'Which costume, and what look?')
  assert.equal(placeholderFor(TASKS, null, 'Message Randall...'), 'Message Randall...')
  assert.equal(placeholderFor(undefined, 'model_import', 'Message Randall...'), 'Message Randall...')
  assert.equal(placeholderFor([{ id: 'model_import', label: 'Import a model' }], 'model_import', 'Fallback'), 'Fallback')
})

test('a chat stored under a retired task id reads as a plain chat', () => {
  for (const id of RETIRED) {
    // It is still the chat's declared task (the stored row says so)...
    assert.equal(taskOf({ task: id }, [user('find me a fox', { task: id })]), id)
    // ...but this build names no such task: no badge, pill label or placeholder,
    assert.equal(labelFor(TASKS, id), null, id)
    assert.equal(placeholderFor(TASKS, id, 'Message Randall...'), 'Message Randall...', id)
    // and nothing it once finished on offers a follow-up or "Start another".
    const finished = [user('find me a fox', { task: id }),
      reply([{ name: 'download_website_mod', status: 'done' }, { name: 'install_project_mods', status: 'done' }])]
    assert.equal(terminalReceipt(id, finished[1]), null, id)
    assert.equal(showStartAnother(id, finished, false), false, id)
    assert.equal(followUpFor(id), null, id)
  }
})

// Since the five starting points: status.tasks also lists the stage retexture and two
// stubs that are not built yet (`available: false`).
const FOUR = [
  { id: 'recolor_part', label: 'Retexture a costume', picker: 'costume', available: true },
  { id: 'model_import', label: 'Import a character model', picker: 'fighter', available: true },
  { id: 'create_character', label: 'Create a character', placeholder: null, hint: 'Coming later.', picker: null, available: false },
  { id: 'recolor_stage', label: 'Retexture a stage', placeholder: 'Which stage, and what colors?', picker: 'stage', available: true },
  { id: 'stage_import', label: 'Import a stage model', placeholder: null, hint: 'Coming later.', picker: null, available: false },
]

test('the stub is listed for the tiles but is never startable', () => {
  assert.deepEqual(launchableTasks({ tasks: FOUR }).map(task => task.id), FOUR.map(task => task.id))
  assert.deepEqual(startableTasks(FOUR).map(task => task.id), ['recolor_part', 'model_import', 'recolor_stage'])
  // A backend that predates the flag: every row can start a chat.
  assert.deepEqual(startableTasks(TASKS), TASKS)
  assert.equal(isStartable(FOUR[2]), false)
  assert.equal(isStartable(FOUR[4]), false)
  assert.equal(isStartable(null), false)
  assert.deepEqual(startableTasks(undefined), [])
  // A chat that somehow carries the stub's id reads as a plain chat: the panel
  // labels (pill, sidebar badge) from the startable rows, and nothing finishes it.
  const stub = [user('make a stage from this', { task: 'stage_import' }), reply([{ name: 'stage_lab', status: 'done', arguments: { action: 'save' } }])]
  assert.equal(labelFor(startableTasks(FOUR), taskOf({ task: null }, stub)), null)
  assert.equal(showStartAnother('stage_import', stub, false), false)
  assert.equal(followUpFor('stage_import'), null)
  const created = [user('build a fighter', { task: 'create_character' })]
  assert.equal(labelFor(startableTasks(FOUR), taskOf({ task: null }, created)), null)
  assert.equal(followUpFor('create_character'), null)
})

test('a stage recolor finishes when the Stage Lab saves a new variant, and only then', () => {
  const lab = (action, status = 'done', result = {}) => ({ name: 'stage_lab', status, arguments: { session_id: 's', action }, result })
  const save = lab('save', 'done', { success: true, variantId: 'night-sky-1a2b', vault_changed: true })
  assert.equal(terminalReceipt('recolor_stage', reply([lab('recolor'), save])), save)
  // Closing the session after the save is a step, not the end.
  assert.equal(terminalReceipt('recolor_stage', reply([save, lab('close')])), save)
  // Looking, editing or exporting finishes nothing; a save that failed neither.
  assert.equal(terminalReceipt('recolor_stage', reply([lab('frame'), lab('recolor'), lab('export')])), null)
  assert.equal(terminalReceipt('recolor_stage', reply([lab('save', 'error', { error: 'Enter a stage name' })])), null)
  assert.equal(terminalReceipt('recolor_stage', reply([{ name: 'stage_lab_open', status: 'done', result: {} }])), null)
  // A costume save is not a stage save.
  assert.equal(terminalReceipt('recolor_stage', reply([SAVED])), null)
  const chat = [user('make battlefield purple', { task: 'recolor_stage' }), reply([save])]
  assert.equal(showStartAnother('recolor_stage', chat, false), true)
  // No same-chat follow-up: a stage cannot be delivered into the game.
  assert.equal(followUpFor('recolor_stage', save), null)
  assert.equal(placeholderFor(FOUR, 'recolor_stage', 'x'), 'Which stage, and what colors?')
  assert.equal(placeholderFor(FOUR, 'stage_import', 'Message Randall...'), 'Message Randall...')
})

test('a retexture saved by code when its turn ended finishes the task like an asked-for save', () => {
  // backend randall/recolor/autosave.py: the edits, then the auto-save receipt at the end of the reply.
  const apply = { name: 'skin_lab', status: 'done', arguments: { session_id: 's', action: 'apply' }, result: {} }
  const saved = { name: 'save_mod_copy', status: 'done', arguments: { file_id: 'f', name: 'Fox - Lava' },
    auto_save: { session_id: 's', kind: 'costume', mode: 'saved' },
    result: { autosave: 'saved', vault_changed: true, items: [{ id: 'fox-lava', character: 'Fox' }] } }
  const updated = { ...saved, auto_save: { ...saved.auto_save, mode: 'updated' }, result: { ...saved.result, autosave: 'updated' } }
  const chip = { label: 'Put it in my game', draft: 'Put it in my game' }
  for (const receipt of [saved, updated]) {
    assert.equal(terminalReceipt('recolor_part', reply([apply, receipt])), receipt)
    assert.deepEqual(followUpFor('recolor_part', receipt), chip)
    assert.equal(showStartAnother('recolor_part', [user('make fox lava', { task: 'recolor_part' }), reply([apply, receipt])], false), true)
  }
  // Still saving (its progress line), or not saved: nothing is finished and no chip is offered.
  assert.equal(terminalReceipt('recolor_part', reply([apply, { ...saved, status: 'running', result: { progress_label: 'Saving the costume to your vault' } }])), null)
  const failed = { ...saved, status: 'error', result: { error: 'Not saved to your vault: the vault could not be written. Your edits are kept, and the next message tries again.', refusal: 'not_saved' } }
  assert.equal(terminalReceipt('recolor_part', reply([apply, failed])), null)
  // The stage's auto-save is the Stage Lab's save receipt.
  const stage = { name: 'stage_lab', status: 'done', arguments: { session_id: 's', action: 'save', name: 'Dreamland - Candy' },
    auto_save: { session_id: 's', kind: 'stage', mode: 'updated' },
    result: { autosave: 'updated', variantId: 'dreamland-candy-1a2b', vault_changed: true } }
  const edit = { name: 'stage_lab', status: 'done', arguments: { session_id: 's', action: 'apply' }, result: {} }
  assert.equal(terminalReceipt('recolor_stage', reply([edit, stage])), stage)
  assert.equal(followUpFor('recolor_stage', stage), null)
})
