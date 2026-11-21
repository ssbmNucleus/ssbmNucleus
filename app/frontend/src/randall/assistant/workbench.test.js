import test from 'node:test'
import assert from 'node:assert/strict'
import { cameraBack, canLoadInPlace, freshCamera, listedAnimation, opensFor, screenAction, swapPlan, wantedAnimation,
  workbenchState, workbenchTabs } from './workbench.js'
import { tungChat, tungDone } from './__fixtures__/tungImportFixture.js'

const png = (id, name = `${id}.png`) => ({ file_id: id, name, extension: '.png' })
const dat = (id, name = `${id}.dat`) => ({ file_id: id, name, extension: '.dat' })
const turn = (...tools) => ({ role: 'assistant', tools })
let n = 0
const tool = (name, result, extra = {}) => ({ id: `t${++n}`, name, status: 'done', result, ...extra })
const tabIds = state => workbenchTabs(state).map(([id]) => id)

test('a chat with no making work has no workbench', () => {
  const state = workbenchState([turn(tool('search_vault', { items: [] }))])
  assert.equal(state.subject, null)
})

test("an older chat's one-call import shows its costume file in 3D, without its pictures", () => {
  const running = tool('import_model', { progress_label: 'Fitting to Luigi' }, { status: 'running' })
  let state = workbenchState([turn(running)])
  assert.equal(state.subject, null, 'nothing while it runs: the chat card shows the steps')
  const done = tool('import_model', { character: 'Luigi', selected_entry: 'Homer.dae',
    files: [png('review-1'), png('review-2'), dat('costume')] })
  state = workbenchState([turn(done)])
  assert.equal(state.subject.title, 'Homer on Luigi')
  assert.deepEqual(state.model, { fileId: 'costume', character: 'Luigi', revision: 1 })
  assert.equal(state.pictures, null)
  assert.deepEqual(state.gallery, [])
  assert.equal(state.step, null)
  assert.equal(state.focus, '3d')
  assert.deepEqual(tabIds(state), ['3d'])
})

test('follow-up model edits stay on the same model and replace its file', () => {
  const imported = tool('import_model', { character: 'Luigi', selected_entry: 'Homer.dae', files: [dat('v1')] })
  const revised = tool('model_revise', { character: 'Luigi', source_file_id: 'src', candidate_id: 'c2', files: [png('after')] })
  const exported = tool('model_candidate', { character: 'Luigi', source_file_id: 'src', files: [dat('v2')] })
  let state = workbenchState([turn(imported), turn(revised)])
  assert.equal(state.subject.title, 'Homer on Luigi')
  assert.equal(state.model.fileId, 'v1', 'pictures of a revision do not drop the loaded file')
  state = workbenchState([turn(imported), turn(revised, exported)])
  assert.deepEqual(state.model, { fileId: 'v2', character: 'Luigi', revision: 2 })
})

test('a texture session loads its source on open and each checkpoint after', () => {
  const target = { character: 'Fox', costume_code: 'PlFxNr' }
  const opened = tool('skin_lab_open', { session_id: 's1', source_file_id: 'src', skin_target: target })
  const read = tool('skin_lab', { session_id: 's1', files: [png('Skin texture 3')] }, { arguments: { session_id: 's1', action: 'texture' } })
  const edit = tool('skin_lab', { session_id: 's1', checkpoint_file: dat('cp1'), revision: 1, skin_target: target, files: [png('recolor')] })
  let state = workbenchState([turn(opened)])
  assert.equal(state.subject.title, 'Fox costume')
  assert.deepEqual(state.model, { fileId: 'src', character: 'Fox', revision: 1 })
  state = workbenchState([turn(opened, read, edit)])
  assert.equal(state.model.fileId, 'cp1')
  assert.equal(state.pictures.files[0].file_id, 'recolor')
})

test('a stage session follows its checkpoints without a fighter', () => {
  const target = { stage_code: 'GrNBa', name: 'Battlefield' }
  const opened = tool('stage_lab_open', { session_id: 'g1', checkpoint_file: dat('base'), stage_target: target })
  const edit = tool('stage_lab', { session_id: 'g1', checkpoint_file: dat('edited'), stage_target: target, files: [png('Recolored stage')] })
  const state = workbenchState([turn(opened, edit)])
  assert.equal(state.subject.title, 'Battlefield')
  assert.deepEqual(state.model, { fileId: 'edited', stageCode: 'GrNBa', revision: 2 })
})

test('switching to something else clears what the last thing showed', () => {
  const imported = tool('import_model', { character: 'Luigi', files: [dat('costume'), png('review')] })
  const stage = tool('stage_lab_open', { session_id: 'g1', stage_target: { stage_code: 'GrOp', name: 'Dream Land' } })
  const state = workbenchState([turn(imported), turn(stage)])
  assert.equal(state.subject.kind, 'stage')
  assert.equal(state.model, null)
  assert.equal(state.pictures, null)
})

test('a failed step keeps the last good file', () => {
  const imported = tool('import_model', { character: 'Luigi', files: [dat('costume'), png('review')] })
  const failed = tool('model_revise', { error: 'Could not revise' })
  const state = workbenchState([turn(imported, failed)])
  assert.equal(state.model.fileId, 'costume')
  const opened = tool('skin_lab_open', { session_id: 's1', source_file_id: 'src', skin_target: { character: 'Fox' } })
  const edit = tool('skin_lab', { session_id: 's1', checkpoint_file: dat('cp1'), skin_target: { character: 'Fox' },
    files: [png('after')] },
    { arguments: { session_id: 's1' } })
  const broken = tool('skin_lab', { error: 'No such texture' }, { arguments: { session_id: 's1' } })
  const lab = workbenchState([turn(opened, edit, broken)])
  assert.equal(lab.model.fileId, 'cp1')
  assert.equal(lab.pictures.files[0].file_id, 'after')
})

test('a live game test takes the focus', () => {
  const imported = tool('import_model', { character: 'Luigi', files: [dat('costume')] })
  const game = tool('test_in_game', { game_test: { session_id: 'x', label: 'Luigi on Battlefield' } })
  const state = workbenchState([turn(imported, game)], game.id)
  assert.equal(state.game, game.id)
  assert.equal(state.focus, 'game')
  assert.equal(workbenchState([turn(imported)], 'gone').game, null)
})

test('a costume opened from the vault is named and shown by what it is', () => {
  const opened = tool('open_vault_file', { vault_item: { character: 'Fox', name: 'DBZ Pack | Goku Fox' },
    files: [{ file_id: 'zip', extension: '.zip' }, dat('unpacked')] })
  // An older session reply carries no skin_target; the opened file still says what it is.
  const session = tool('skin_lab_open', { session_id: 's1', source_file_id: 'unpacked' }, { arguments: { file_id: 'unpacked' } })
  const state = workbenchState([turn(opened, session)])
  assert.equal(state.subject.title, 'DBZ Pack | Goku Fox')
  assert.deepEqual(state.model, { fileId: 'unpacked', character: 'Fox', revision: 1 })
})

test('an exported model opened in Texture Lab keeps its name', () => {
  const imported = tool('import_model', { character: 'Luigi', selected_entry: 'Homer.dae', files: [dat('costume')] })
  const session = tool('skin_lab_open', { session_id: 's1', source_file_id: 'costume', skin_target: { character: 'Luigi' } },
    { arguments: { file_id: 'costume' } })
  const state = workbenchState([turn(imported, session)])
  assert.equal(state.subject.kind, 'costume')
  assert.equal(state.subject.title, 'Homer on Luigi')
})

test('the gallery keeps every lab picture of the chat, grouped by step, across lab subjects; never an import\'s', () => {
  const fitted = tool('import_model', { character: 'Peach', selected_entry: 'ShyGal.glb', files: [png('fit-1'), png('fit-2'), dat('d1')] })
  const revised = tool('model_revise', { character: 'Peach', source_file_id: 'src', files: [png('rev-1'), png('fit-1')] })
  const skin = tool('skin_lab', { session_id: 's9', skin_target: { character: 'Fox' }, files: [png('fox-1'), png('fox-2')] })
  const stageTarget = { stage_code: 'GrNBa', name: 'Battlefield' }
  const stage = tool('stage_lab', { session_id: 'g1', stage_target: stageTarget, files: [png('bf-1'), png('fox-1')] })
  let state = workbenchState([turn(fitted), turn(revised), turn(skin)])
  assert.deepEqual(state.gallery.map(p => p.key), ['fox-1', 'fox-2'], 'the import\'s pictures stay on its cards')
  state = workbenchState([turn(fitted), turn(revised), turn(skin), turn(stage)])
  assert.deepEqual(state.pictures.files.map(f => f.file_id), ['bf-1', 'fox-1'], 'pictures is still only the newest batch')
  assert.deepEqual(state.gallery.map(p => p.key), ['fox-1', 'fox-2', 'bf-1'], 'oldest first, a repeat shown once')
  assert.deepEqual([...new Set(state.gallery.map(p => p.group.id))], [skin.id, stage.id])
  assert.deepEqual(state.gallery.map(p => p.group.subject), ['Fox costume', 'Fox costume', 'Battlefield'])
  assert.equal(state.gallery[0].file.file_id, 'fox-1', 'a gallery picture carries its file record for attaching')
  assert.deepEqual(workbenchState([turn(tool('search_vault', {}))]).gallery, [])
})

test("an older chat's import drafts are not shown: only a costume file is", () => {
  // The step-by-step importer named drafts the backend built a viewer file of on request; that route is gone.
  const fit = 'a'.repeat(32)
  const imported = tool('import_model', { character: 'Pikachu', candidate_id: fit, selected_entry: 'Togetic.dae', files: [png('fit')] })
  const revised = tool('model_revise', { character: 'Pikachu', candidate_id: 'b'.repeat(32), source_file_id: 'src' })
  const exported = tool('model_candidate', { character: 'Pikachu', source_file_id: 'src', files: [dat('real')] })
  assert.equal(workbenchState([turn(imported), turn(revised)]).subject, null)
  const state = workbenchState([turn(imported), turn(revised, exported)])
  assert.equal(state.subject.title, 'Togetic on Pikachu', 'named by the entry an earlier step picked')
  assert.deepEqual(state.model, { fileId: 'real', character: 'Pikachu', revision: 1 })
})

test("an older chat's studio stages show nothing until a stage writes the costume file", () => {
  const user = { role: 'user', context: { files: [{ file_id: 'f'.repeat(32), name: 'Neos.zip' }] } }
  const tag = { studio_import: { tool: 'x', id: 'neos' } }
  const clean = tool('clean_source', { ...tag, stage: 2, name: 'clean', status: 'done', files: [png('s2')] },
    { arguments: { project: 'neos', source: 'f'.repeat(32) } })
  const picked = tool('pick_fighter', { ...tag, stage: 3, name: 'fighter', status: 'done', report: { fighter: 'Fox' },
    files: [png('s3')] })
  const running = tool('weight', undefined, { status: 'running' })
  assert.equal(workbenchState([user, turn(clean, picked, running)]).subject, null)
  const exported = tool('export', { ...tag, stage: 9, name: 'export', status: 'done', files: [png('s9'), dat('PlFxNr')] })
  const state = workbenchState([user, turn(clean, picked, exported)])
  assert.equal(state.subject.key, 'studio:neos')
  assert.equal(state.subject.title, 'Neos on Fox')
  assert.deepEqual(state.model, { fileId: 'PlFxNr', character: 'Fox', revision: 1 })
  assert.deepEqual(state.gallery, [])
  assert.equal(state.step, null)
})

test('an import is in the panel once it wrote its costume file: 3D on its fighter, no Pictures', () => {
  const tag = { studio_import: { tool: 'import_model', id: 'wwlink' } }
  const running = tool('import_model', { ...tag, status: 'running', project: 'wwlink', step: 'loading the model',
    progress: ['loading wwlink.zip'] }, { status: 'running' })
  let state = workbenchState([turn(running)])
  assert.equal(state.subject, null, 'while it runs the chat card carries the steps; the panel stays closed')
  // A reply that wrote nothing: tools to download first (no project yet), or the model came without its textures.
  for (const result of [{ studio_import: { tool: 'import_model', id: null }, status: 'needs_tools' },
    { ...tag, status: 'needs_textures', warning: 'its textures did not come with it' },
    { ...tag, status: 'failed', error: 'could not load the model', fighter: 'Young Link' }]) {
    assert.equal(workbenchState([turn(tool('import_model', result))]).subject, null, result.status)
  }
  const done = tool('import_model', { ...tag, status: 'done', fighter: 'Young Link', saved: { name: 'Wind Waker Link' },
    files: [png('finish_csp', 'finish_csp.png'), dat('PlClNr', 'PlClNr.dat')] })
  state = workbenchState([turn(done)])
  assert.equal(state.subject.key, 'studio:wwlink')
  assert.equal(state.subject.title, 'Wind Waker Link on Young Link', 'the costume and its fighter')
  assert.deepEqual(state.model, { fileId: 'PlClNr', character: 'Young Link', revision: 1 })
  assert.equal(state.focus, '3d')
  assert.equal(state.pictures, null, 'its portrait is on its card')
  assert.deepEqual(state.gallery, [])
  assert.equal(state.step, null, 'no step under the title: the card shows them')
  assert.equal(state.arrival, 'studio:wwlink|PlClNr')
  assert.deepEqual(tabIds(state), ['3d'])
  const game = tool('test_in_game', { game_test: { session_id: 'x', label: 'Young Link — Wind Waker Link' } })
  state = workbenchState([turn(done, game)], game.id)
  assert.deepEqual(tabIds(state), ['3d', 'game'], 'tested: 3D and In game')
  assert.equal(state.subject.key, 'studio:wwlink', 'the test is of the import')
  assert.equal(state.focus, 'game')
})

test('a new import changes nothing until it writes its own costume; then the panel opens on it', () => {
  const wwTag = { studio_import: { tool: 'import_model', id: 'wwlink' }, project: 'wwlink', fighter: 'Young Link' }
  const neosTag = { studio_import: { tool: 'import_model', id: 'neos' }, project: 'neos', fighter: 'Fox' }
  const done = tool('import_model', { ...wwTag, status: 'done', files: [dat('PlClNr', 'PlClNr.dat')] })
  const running = tool('import_model', { ...neosTag, status: 'running', progress: ['load: neos.zip'] }, { status: 'running' })
  const before = workbenchState([turn(done)])
  let state = workbenchState([turn(done), turn(running)])
  assert.deepEqual(state, before, 'a running import changes nothing, not even a step under the title')
  const failed = tool('import_model', { ...neosTag, status: 'failed', error: 'could not put it on Fox' })
  assert.deepEqual(workbenchState([turn(done), turn(failed)]), before, 'nor one that wrote nothing')
  const written = tool('import_model', { ...neosTag, status: 'done', files: [png('neos-csp', 'finish_csp.png'),
    dat('PlFxNr', 'PlFxNr.dat')] })
  state = workbenchState([turn(done), turn(failed), turn(written)])
  assert.equal(state.subject.key, 'studio:neos')
  assert.deepEqual(state.model, { fileId: 'PlFxNr', character: 'Fox', revision: 1 })
  assert.equal(state.focus, '3d')
  assert.notEqual(state.arrival, before.arrival, 'a new arrival: the panel opens on it')
  // A change to it ("the legs look wrong") writes a second costume of the same import: 3D shows it, no new arrival.
  const changed = tool('import_model', { ...neosTag, status: 'done', changed: 'the legs', files: [dat('PlFxNr2', 'PlFxNr.dat')] },
    { arguments: { project: 'neos', change: 'the legs look wrong' } })
  const after = workbenchState([turn(done), turn(failed), turn(written), turn(changed)])
  assert.deepEqual(after.model, { fileId: 'PlFxNr2', character: 'Fox', revision: 2 })
  assert.equal(after.arrival, state.arrival)
})

test('the panel opens itself only for an import that arrives while its chat is on screen', () => {
  assert.equal(opensFor(null, 'c1', 'studio:a|f1'), false, 'first seen (the app started, the panel mounted)')
  assert.equal(opensFor({ chat: 'c1', arrival: null }, 'c1', 'studio:a|f1'), true, 'it arrived in this chat')
  assert.equal(opensFor({ chat: 'c1', arrival: 'studio:a|f1' }, 'c1', 'studio:a|f1'), false, 'already seen')
  assert.equal(opensFor({ chat: 'c1', arrival: 'studio:a|f1' }, 'c2', 'studio:b|f2'), false, 'another chat opened')
  assert.equal(opensFor({ chat: null, arrival: null }, 'c1', null), false, 'a new chat got its id')
  assert.equal(opensFor({ chat: 'c1', arrival: 'studio:a|f1' }, 'c1', 'studio:b|f2'), true, 'a second import')
})

test('a lab shows its step under the title; a running stage edit does not retitle it', () => {
  const stageTarget = { stage_code: 'GrNBa', name: 'Battlefield' }
  const opened = tool('stage_lab_open', { session_id: 'g1', checkpoint_file: dat('base'), stage_target: stageTarget })
  const running = tool('stage_lab', {}, { status: 'running', arguments: { session_id: 'g1', action: 'recolor' } })
  const state = workbenchState([turn(opened, running)])
  assert.equal(state.subject.title, 'Battlefield')
  assert.equal(state.step.running, true)
  assert.deepEqual(tabIds(state), ['3d', 'pictures'])
  assert.deepEqual(workbenchTabs(workbenchState([turn(opened)])).map(([id, , ready]) => [id, ready]),
    [['3d', true], ['pictures', false]], 'Pictures waits for its first render')
})

test('a lab call that does not name its target (a save) keeps the title', () => {
  // A real Dreamland chat: its last call, stage_lab save, carries no stage_target and the title read "A stage".
  const opened = tool('stage_lab_open', { session_id: 'g2', checkpoint_file: dat('base'),
    stage_target: { stage_code: 'GrOp', name: 'Dreamland' } })
  const saved = tool('stage_lab', { session_id: 'g2', name: 'Dreamland - AI Slop', stageCode: 'GrOp', files: [] },
    { arguments: { session_id: 'g2', action: 'save' } })
  assert.equal(workbenchState([turn(opened, saved)]).subject.title, 'Dreamland')
  const named = tool('stage_lab', { session_id: 'g3' }, { arguments: { session_id: 'g3', action: 'save' } })
  assert.equal(workbenchState([turn(named)]).subject.title, 'A stage', 'a session never named says so')
  const skin = tool('skin_lab_open', { session_id: 's9', source_file_id: 'src', skin_target: { character: 'Fox' } })
  const skinSaved = tool('skin_lab', { session_id: 's9', name: 'Fox - Red' }, { arguments: { session_id: 's9', action: 'save' } })
  assert.equal(workbenchState([turn(skin, skinSaved)]).subject.title, 'Fox costume')
})

test('a game test with nothing else being made has only In game', () => {
  const game = tool('test_in_game', { game_test: { session_id: 'x', label: 'Fox' } })
  const state = workbenchState([turn(game)], game.id)
  assert.equal(state.subject.kind, 'game')
  assert.deepEqual(tabIds(state), ['game'])
})

test('the old play-session test_in_game is not a studio picture step', () => {
  const game = tool('test_in_game', { game_test: { session_id: 'x', label: 'Luigi' }, files: [png('p')] })
  assert.equal(workbenchState([turn(game)]).gallery.length, 0)
})


// ---- the 3D view swaps textures in place when an edit only changed textures ----

const stageTarget = { stage_code: 'GrNBa', name: 'Battlefield' }
const swapOf = (from, ...indices) => ({ from, textures: indices.map(index => ({ index, file_id: `px-${from}-${index}` })) })

test('a texture-only edit chains onto the file the view shows', () => {
  const opened = tool('stage_lab_open', { session_id: 'g1', checkpoint_file: dat('base'), stage_target: stageTarget })
  const first = tool('stage_lab', { session_id: 'g1', checkpoint_file: dat('e1'), stage_target: stageTarget,
    viewer_update: swapOf('base', 0, 3) })
  const second = tool('stage_lab', { session_id: 'g1', checkpoint_file: dat('e2'), stage_target: stageTarget,
    viewer_update: swapOf('e1', 3, 5) })
  const state = workbenchState([turn(opened, first, second)])
  assert.equal(state.model.fileId, 'e2')
  assert.deepEqual(state.model.swaps.map(swap => swap.from), ['base', 'e1'])
  const live = { connected: true }
  // From the opened file: every texture once, with its newest picture; from e1: only the second edit's.
  assert.deepEqual(swapPlan({ fileId: 'base', stageCode: 'GrNBa' }, state.model, live), { materials: [],
    textures: [{ index: 0, file_id: 'px-base-0' }, { index: 3, file_id: 'px-e1-3' }, { index: 5, file_id: 'px-e1-5' }] })
  assert.deepEqual(swapPlan({ fileId: 'e1', stageCode: 'GrNBa' }, state.model, live).textures.map(t => t.index), [3, 5])
})

test('the view reloads when it cannot swap', () => {
  const opened = tool('stage_lab_open', { session_id: 'g1', checkpoint_file: dat('base'), stage_target: stageTarget })
  const edit = tool('stage_lab', { session_id: 'g1', checkpoint_file: dat('e1'), stage_target: stageTarget,
    viewer_update: swapOf('base', 0) })
  const material = tool('stage_lab', { session_id: 'g1', checkpoint_file: dat('e2'), stage_target: stageTarget })
  const model = workbenchState([turn(opened, edit)]).model
  const shown = { fileId: 'base', stageCode: 'GrNBa' }
  assert.ok(swapPlan(shown, model, { connected: true }))
  assert.equal(swapPlan(shown, model, { connected: false }), null, 'no renderer up')
  assert.equal(swapPlan(shown, model, { connected: true, pair: true }), null, 'the climbers pair loads two files')
  assert.equal(swapPlan({ fileId: 'other', stageCode: 'GrNBa' }, model, { connected: true }), null, 'not in the chain')
  assert.equal(swapPlan({ fileId: 'base', stageCode: 'GrPs' }, model, { connected: true }), null, 'another stage')
  assert.equal(swapPlan({ fileId: 'e1', stageCode: 'GrNBa' }, model, { connected: true }), null, 'already shown')
  // A change the backend could not name (scenery) breaks the chain: a reload, then swaps again from there.
  const broken = workbenchState([turn(opened, edit, material)]).model
  assert.equal(broken.fileId, 'e2')
  assert.equal(broken.swaps, undefined)
  assert.equal(swapPlan(shown, broken, { connected: true }), null)
  // An update that does not apply on top of the shown file never joins the chain.
  const stray = tool('stage_lab', { session_id: 'g1', checkpoint_file: dat('e3'), stage_target: stageTarget,
    viewer_update: swapOf('somewhere-else', 1) })
  assert.equal(workbenchState([turn(opened, stray)]).model.swaps, undefined)
})

test('an export with nothing changed is a swap of no textures', () => {
  const target = { character: 'Fox' }
  const opened = tool('skin_lab_open', { session_id: 's1', source_file_id: 'src', skin_target: target })
  const edit = tool('skin_lab', { session_id: 's1', checkpoint_file: dat('cp1'), skin_target: target,
    viewer_update: swapOf('src', 2) })
  const exported = tool('skin_lab', { session_id: 's1', checkpoint_file: dat('export'), skin_target: target,
    viewer_update: { from: 'cp1', textures: [] } })
  const model = workbenchState([turn(opened, edit, exported)]).model
  assert.equal(model.fileId, 'export')
  assert.deepEqual(swapPlan({ fileId: 'cp1', character: 'Fox' }, model, { connected: true }), { textures: [], materials: [] })
})

test('a generated material on a stage keeps the stage in the workbench', () => {
  const opened = tool('stage_lab_open', { session_id: 'g1', checkpoint_file: dat('base'), stage_target: stageTarget })
  const applied = tool('skin_material', { session_id: 'g1', action: 'apply', checkpoint_file: dat('mat'),
    stage_target: stageTarget, updated_textures: [4], viewer_update: swapOf('base', 4), files: [png('Material edit preview')] })
  const state = workbenchState([turn(opened, applied)])
  assert.equal(state.subject.kind, 'stage')
  assert.equal(state.subject.key, 'stage:g1')
  assert.deepEqual({ fileId: state.model.fileId, stageCode: state.model.stageCode }, { fileId: 'mat', stageCode: 'GrNBa' })
  assert.deepEqual(swapPlan({ fileId: 'base', stageCode: 'GrNBa' }, state.model, { connected: true }).textures,
    [{ index: 4, file_id: 'px-base-4' }])
})

const colourSwap = (from, id, types = ['setVertexColors'], objects = []) => ({ from, textures: [],
  colours: { id: id.padEnd(32, '0'), types, objects } })
const protocol2 = { connected: true, supports: type => ['setVertexColors', 'setAnimationColors', 'setLightColors',
  'loadDat'].includes(type) }

test('colour edits the lab took in place ride along, in order, on a renderer that takes them', () => {
  const opened = tool('stage_lab_open', { session_id: 'g1', checkpoint_file: dat('base'), stage_target: stageTarget })
  const vertex = tool('stage_lab', { session_id: 'g1', checkpoint_file: dat('e1'), stage_target: stageTarget,
    viewer_update: colourSwap('base', 'a1') })
  const texture = tool('stage_lab', { session_id: 'g1', checkpoint_file: dat('e2'), stage_target: stageTarget,
    viewer_update: swapOf('e1', 2) })
  const lights = tool('stage_lab', { session_id: 'g1', checkpoint_file: dat('e3'), stage_target: stageTarget,
    viewer_update: colourSwap('e2', 'b2', ['setLightColors']) })
  const model = workbenchState([turn(opened, vertex, texture, lights)]).model
  assert.deepEqual(model.swaps.map(swap => swap.from), ['base', 'e1', 'e2'])
  const shown = { fileId: 'base', stageCode: 'GrNBa' }
  assert.deepEqual(swapPlan(shown, model, protocol2), { textures: [{ index: 2, file_id: 'px-e1-2' }], materials: [],
    colours: [{ id: 'a1'.padEnd(32, '0'), types: ['setVertexColors'] },
      { id: 'b2'.padEnd(32, '0'), types: ['setLightColors'] }] })
  // From e2 only the light edit is left.
  assert.deepEqual(swapPlan({ fileId: 'e2', stageCode: 'GrNBa' }, model, protocol2).colours.map(c => c.id),
    ['b2'.padEnd(32, '0')])
  // A renderer that does not announce the messages (an older viewer) reloads instead.
  assert.equal(swapPlan(shown, model, { connected: true }), null)
  assert.equal(swapPlan(shown, model, { connected: true, supports: type => type === 'setVertexColors' }), null)
  // Without colour edits the plan has no `colours` at all.
  assert.deepEqual(Object.keys(swapPlan({ fileId: 'e1', stageCode: 'GrNBa' },
    workbenchState([turn(opened, vertex, texture)]).model, protocol2)).sort(), ['materials', 'textures'])
})

test('a material value older than a colour edit of the same object is dropped', () => {
  const target = { character: 'Fox' }
  const opened = tool('skin_lab_open', { session_id: 's1', source_file_id: 'src', skin_target: target })
  const material = tool('skin_lab', { session_id: 's1', checkpoint_file: dat('cp1'), skin_target: target,
    viewer_update: { from: 'src', textures: [], materials: [{ id: 'Model:3', field: 'diffuse', value: '#ff0000ff' },
      { id: 'Model:3', field: 'alpha', value: 0.5 }, { id: 'Model:4', field: 'diffuse', value: '#00ff00ff' }] } })
  const animated = tool('skin_lab', { session_id: 's1', checkpoint_file: dat('cp2'), skin_target: target,
    viewer_update: colourSwap('cp1', 'c3', ['setAnimationColors'], ['Model:3']) })
  const later = tool('skin_lab', { session_id: 's1', checkpoint_file: dat('cp3'), skin_target: target,
    viewer_update: { from: 'cp2', textures: [], materials: [{ id: 'Model:3', field: 'ambient', value: '#0000ffff' }] } })
  const model = workbenchState([turn(opened, material, animated, later)]).model
  assert.deepEqual(swapPlan({ fileId: 'src', character: 'Fox' }, model, protocol2), {
    textures: [],
    // Model:3's diffuse came from the colour edit (newer); its alpha is no colour; the later ambient stays.
    materials: [{ id: 'Model:3', field: 'alpha', value: 0.5 }, { id: 'Model:4', field: 'diffuse', value: '#00ff00ff' },
      { id: 'Model:3', field: 'ambient', value: '#0000ffff' }],
    colours: [{ id: 'c3'.padEnd(32, '0'), types: ['setAnimationColors'] }] })
})

test('a malformed colour update never joins the chain', () => {
  const opened = tool('stage_lab_open', { session_id: 'g1', checkpoint_file: dat('base'), stage_target: stageTarget })
  for (const colours of [{ id: 'nothex', types: ['setVertexColors'], objects: [] },
    { id: 'a'.repeat(32), types: ['loadDat'], objects: [] }, { id: 'a'.repeat(32), types: [], objects: [] },
    { id: 'a'.repeat(32), types: ['setVertexColors'] }]) {
    const edit = tool('stage_lab', { session_id: 'g1', checkpoint_file: dat('e1'), stage_target: stageTarget,
      viewer_update: { from: 'base', textures: [], colours } })
    assert.equal(workbenchState([turn(opened, edit)]).model.swaps, undefined, JSON.stringify(colours))
  }
})

test('a different file of the same kind loads into the running renderer when it takes loadDat', () => {
  const fox = { fileId: 'a', character: 'Fox' }, falco = { fileId: 'b', character: 'Falco' }
  const fd = { fileId: 'c', stageCode: 'GrNLa' }, ps = { fileId: 'd', stageCode: 'GrPs' }
  assert.equal(canLoadInPlace(fox, falco, protocol2), true, 'costume after costume')
  assert.equal(canLoadInPlace(fd, ps, protocol2), true, 'stage after stage')
  assert.equal(canLoadInPlace(fox, { candidateId: 'f'.repeat(32), character: 'Fox' }, protocol2), false,
    'an old import draft has no file to load')
  assert.equal(canLoadInPlace(fox, fd, protocol2), false, 'a stage after a costume relaunches')
  assert.equal(canLoadInPlace(fox, falco, { connected: true }), false, 'an older renderer relaunches')
  assert.equal(canLoadInPlace(fox, falco, { ...protocol2, connected: false }), false, 'no renderer up')
  assert.equal(canLoadInPlace(fox, falco, { ...protocol2, pair: true }), false, 'the climbers pair')
  assert.equal(canLoadInPlace(null, falco, protocol2), false, 'nothing shown yet')
})

test('the animation list shows what the renderer has loaded, or the pose', () => {
  const mario = ['PlyMario5K_Share_ACTION_Attack11_figatree', 'PlyMario5K_Share_ACTION_AttackHi3_figatree']
  const ganon = ['PlyGanon5K_Share_ACTION_Attack11_figatree', 'PlyGanon5K_Share_ACTION_Attack12_figatree']
  assert.equal(listedAnimation(mario, mario[1]), mario[1], 'the one loaded')
  // preview.27: after a Mario chat the Ganondorf chat's list read "Jab 1" (its first entry) with nothing loaded.
  assert.equal(listedAnimation(ganon, mario[1]), '', "another fighter's animation names nothing here")
  assert.equal(listedAnimation(ganon, ''), '', 'nothing loaded')
  assert.equal(listedAnimation([], mario[1]), '', 'no list yet')
})

test('a picked animation plays again only on the subject it was picked on', () => {
  const jab = { symbol: 'PlyMario5K_Share_ACTION_Attack11_figatree', subject: 'studio:tung' }
  assert.equal(wantedAnimation(jab, 'studio:tung'), jab.symbol, 'a reload of the same costume keeps it')
  // 11-20 in the dev app: Jab picked in the tung chat (Mario), then Clank (Pichu), then the Donald Skin Lab chat
  // (Mario) opened playing Jab.
  assert.equal(wantedAnimation(jab, 'skin:donald'), '', "another chat's model starts in its pose")
  assert.equal(wantedAnimation({ symbol: '', subject: 'studio:tung' }, 'studio:tung'), '', 'Pose was picked')
  assert.equal(wantedAnimation({ symbol: jab.symbol, subject: '' }, undefined), jab.symbol, 'no subject known either side')
  assert.equal(wantedAnimation(null, 'studio:tung'), '')
})

test("another chat's costume or another fighter takes a fresh camera; the next file of the same one keeps the view", () => {
  const crash = { subject: 'studio:crash', character: 'Fox' }
  // preview.27: the skeleton's chat opened with its model half off the edge, where Crash's view had been left.
  assert.equal(freshCamera(crash, { subject: 'studio:skeleton', character: 'Fox' }), true)
  assert.equal(freshCamera(crash, { ...crash }), false, 'an edit of the costume on screen')
  assert.equal(freshCamera(crash, { subject: '', character: 'Fox' }), false, 'no subject known: the view stays, as it did')
  assert.equal(freshCamera(null, crash), true, 'nothing of a known subject shown yet')
  // Fox's framing (22 units away, 70 degrees) kept for Bowser (1747 away, 2 degrees) shows his knees.
  assert.equal(freshCamera(crash, { subject: 'studio:crash', character: 'Bowser' }), true, 'the same subject on another fighter')
  assert.equal(freshCamera(crash, { subject: '', character: 'Bowser' }), true, 'another fighter, subject unknown')
  assert.equal(freshCamera({ subject: 'stage:g1', stageCode: 'GrNBa' }, { subject: 'stage:g1', stageCode: 'GrNBa' }), false)
  assert.equal(freshCamera({ subject: 'stage:g1', stageCode: 'GrNBa' }, { subject: 'stage:g1', stageCode: 'GrPs' }), true)
})

test('Pose puts the camera back where the user had it after the renderer resets both', () => {
  const home = { x: 2, y: 10, z: -22, scale: 1, fovRadians: 1.22, rotationXRadians: 0.1, rotationYRadians: 0.08 }
  const turned = { ...home, x: 5, y: 8, scale: 2.5, rotationXRadians: 0.1 + Math.PI / 6, rotationYRadians: 0.08 - Math.PI / 2 }
  const back = cameraBack(turned, home)
  assert.deepEqual(back.map(value => Math.round(value * 1000) / 1000), [30, -90, 1.5, 3, -2],
    'degrees for the turn, a factor for the zoom, units for the pan')
  assert.equal(cameraBack(home, { ...home }), null, 'the user had not moved it')
  assert.equal(cameraBack(null, home), null, 'not read')
  assert.equal(cameraBack({ ...turned, scale: 0 }, home), null)
})

test('an idle 3D view stays up off screen and is reused on the way back, not reloaded', () => {
  const idle = { session: true, shown: true, connected: true, streaming: true, busy: false }
  // The user clicks off the AI tab (or onto Pictures) with the stage on screen, then back.
  assert.equal(screenAction({ ...idle, active: false, wasActive: true }), 'keep')
  assert.equal(screenAction({ ...idle, active: true, wasActive: false }), 'resume')
  // Randall edits the stage while the user is away: still kept, and shown on the way back (resume, then show).
  assert.equal(screenAction({ ...idle, active: false, wasActive: false }), 'keep')
  // Randall edits it again with the view on screen: a real update.
  assert.equal(screenAction({ ...idle, active: true, wasActive: true }), 'show')
})

test('a 3D view that is not up and idle stops off screen and launches when shown', () => {
  const idle = { session: true, shown: true, connected: true, streaming: true, busy: false }
  assert.equal(screenAction({ ...idle, active: false, busy: true }), 'stop', 'mid swap or load')
  assert.equal(screenAction({ ...idle, active: false, shown: false }), 'stop', 'still starting')
  assert.equal(screenAction({ ...idle, active: false, connected: false }), 'stop', 'its renderer went away')
  assert.equal(screenAction({ ...idle, active: false, streaming: false }), 'stop', 'the native overlay window')
  assert.equal(screenAction({ active: false }), 'stop', 'nothing running')
  // Back on screen with nothing kept: the view follows its model (a launch).
  assert.equal(screenAction({ active: true, wasActive: false }), 'show')
  assert.equal(screenAction({ active: true }), 'show', 'first shown')
})

test('material values ride along: each field once, with its newest value', () => {
  const target = { character: 'Fox' }
  const opened = tool('skin_lab_open', { session_id: 's1', source_file_id: 'src', skin_target: target })
  const recolor = tool('skin_lab', { session_id: 's1', checkpoint_file: dat('cp1'), skin_target: target,
    viewer_update: { ...swapOf('src', 1), materials: [{ id: 'Group 0:1', field: 'diffuse', value: '#ff0000ff' },
      { id: 'Group 0:2', field: 'diffuse', value: '#00ff00ff' }] } })
  const material = tool('skin_lab', { session_id: 's1', checkpoint_file: dat('cp2'), skin_target: target,
    viewer_update: { from: 'cp1', textures: [], materials: [{ id: 'Group 0:1', field: 'diffuse', value: '#0000ffff' },
      { id: 'Group 0:1', field: 'alpha', value: 0.5 }] } })
  const model = workbenchState([turn(opened, recolor, material)]).model
  assert.deepEqual(swapPlan({ fileId: 'src', character: 'Fox' }, model, { connected: true }), {
    textures: [{ index: 1, file_id: 'px-src-1' }],
    materials: [{ id: 'Group 0:2', field: 'diffuse', value: '#00ff00ff' },
      { id: 'Group 0:1', field: 'diffuse', value: '#0000ffff' }, { id: 'Group 0:1', field: 'alpha', value: 0.5 }] })
  // A malformed update never joins the chain.
  const bad = tool('skin_lab', { session_id: 's1', checkpoint_file: dat('cp3'), skin_target: target,
    viewer_update: { from: 'cp2', textures: [], materials: [{ id: 'Group 0:1', field: 'diffuse' }] } })
  assert.equal(workbenchState([turn(opened, recolor, material, bad)]).model.swaps, undefined)
})

// The Tung Tung Tung Sahur import (the launch-video run, an older chat's v4 reply): the user attached
// tung_tung_sahur.glb, Randall saved it as "Tung Tung Tung Sahur".
test('an import is titled by the file the user attached until it saves, then by the costume\'s name in the vault', () => {
  const unsaved = tungDone()
  unsaved.result.saved = null
  let state = workbenchState(tungChat(unsaved))
  assert.equal(state.subject.title, 'tung_tung_sahur on Young Link', 'the panel reads it as "Tung Tung Sahur on Young Link"')
  state = workbenchState(tungChat(tungDone()))
  assert.equal(state.subject.key, 'studio:tung-tung-sahur-471b6f')
  assert.equal(state.subject.title, 'Tung Tung Tung Sahur on Young Link', 'one name: the one in the vault')
  assert.equal(state.model.character, 'Young Link')
  // v4's reply carried a sheet of pictures; they are on its card, not in the panel.
  assert.ok(tungDone().result.files.filter(file => file.extension === '.png').length > 4)
  assert.deepEqual(state.gallery, [])
  assert.deepEqual(tabIds(state), ['3d'])
})
