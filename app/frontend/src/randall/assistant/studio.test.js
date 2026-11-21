import assert from 'node:assert/strict'
import test from 'node:test'
import {
  costText, freshEyesPictures, gamePictures, importJob, importStatusText, isStudioTool,
  pictureCaption, poseCaption, stageRows, studioChanges, studioContext, studioFighter, studioNotes, studioQuestions, studioStatusText,
  importTimeText, studioSubjectName,
} from './studio.js'
import { elapsedText } from './activity.js'
import { taskProgress } from './taskEnvelope.js'
import { tungChat, tungDone, tungReply, tungRunning } from './__fixtures__/tungImportFixture.js'

// Shapes as a real import chat stores them (r2 Neos on C. Falcon, trimmed).
const ROOT = 'C:\\imports\\neos'
const png = (id, path) => ({ file_id: id, name: path.slice(ROOT.length + 1).replace(/[\\/]+/g, '_'),
  size: 1000, extension: '.png', path })
const tag = (name, id = 'neos') => ({ studio_import: { tool: name, id } })
let n = 0
const call = (name, result, extra = {}) => ({ id: `t${++n}`, name, status: result?.error ? 'error' : 'done',
  arguments: { project: 'neos' }, result: { ...result, ...tag(name) }, ...extra })

const user = { role: 'user', content: 'Import this model onto C. Falcon.',
  context: { files: [{ file_id: 'a'.repeat(32), name: 'elemental-hero-neos.zip', extension: '.zip' }] } }
const clean = call('clean_source', { stage: 2, name: 'clean', status: 'done', next: 'look at the pictures',
  files: [png('c1', `${ROOT}\\02-clean\\pictures\\objects\\parts-rest.png`)], report: { look: { objects: { fighter: null } } } },
{ arguments: { project: 'neos', source: 'a'.repeat(32), fighter: 'C. Falcon' } })
const picked = call('pick_fighter', { stage: 3, name: 'fighter', status: 'done', report: { fighter: 'C. Falcon' },
  files: [png('f1', `${ROOT}\\03-fighter\\pictures\\fit-C. Falcon\\silhouette-rest.png`)] })
const lined = call('line_up', { stage: 4, name: 'line_up', status: 'done',
  report: { look: { overlay: { fighter: 'C. Falcon' } } },
  files: [png('l1', `${ROOT}\\04-line_up\\pictures\\lined-up\\overlay-rest.png`)] },
{ arguments: { project: 'neos', op: 'move_part', arguments: { part: 'r_leg', translation: [0, -0.86, 0] },
  reason: 'Back foot rides above the floor.' } })
const game = call('test_in_game', { stage: 10, name: 'game', status: 'done', next: 'finished',
  report: { identity: { fighter: 'C. Falcon', import: { requested_slot: 6, loaded_slot: 6, slot_matches: true } },
    frames: [{ move: 'idle', frame: 1, status: 'captured', frame_match: true },
      { move: 'run', frame: 9, status: 'captured', frame_match: false }],
    notes: ['import run frame 9: the model touches the frame edge at the fixed camera.'] },
  files: [png('g1', `${ROOT}\\game-runs\\run-01\\pictures\\game-01-idle1-run9.png`),
    png('g2', `${ROOT}\\game-runs\\run-01\\pictures\\game-02-jab3-fair5.png`),
    png('g3', `${ROOT}\\game-runs\\run-01\\pictures\\game-03-upb5-fsmash10.png`)] })
const chat = [user, { role: 'assistant', tools: [clean, picked, lined, game] }]

test('the reply tag routes a call to the studio, whatever its name', () => {
  assert.equal(isStudioTool(game), true, 'the studio stage 10 is also called test_in_game')
  assert.equal(isStudioTool({ name: 'test_in_game', status: 'done', result: { game_test: { session_id: 's' } } }, true), false,
    'the play-session tool stays with its own card, even in a chat running an import')
  assert.equal(isStudioTool({ name: 'test_in_game', status: 'done', result: { note: 'No game.' }, arguments: { action: 'start' } }, true), false)
  // Before a reply there is no tag: a studio-only name, the arguments, or the chat decide.
  assert.equal(isStudioTool({ name: 'weight', status: 'running' }), true)
  assert.equal(isStudioTool({ name: 'test_in_game', status: 'running', arguments: { project: 'neos' } }), true)
  assert.equal(isStudioTool({ name: 'test_in_game', status: 'running' }, true), true)
  assert.equal(isStudioTool({ name: 'test_in_game', status: 'running' }, false), false)
  assert.equal(isStudioTool({ name: 'import_model', status: 'done', result: {} }, true), false)
})

test('the chat says which fighter each call was on, and where its pictures are', () => {
  const context = studioContext(chat)
  assert.equal(context.active, true)
  assert.equal(studioFighter(clean, context), 'C. Falcon', 'a card before the pick names the fighter the import went on')
  assert.equal(studioFighter(lined, context), 'C. Falcon')
  assert.equal(studioFighter({ id: 'running', name: 'weight', status: 'running' }, context), 'C. Falcon')
  assert.equal(context.files.get('l1').file_id, 'l1')
  assert.equal(context.files.get(`${ROOT}\\04-line_up\\pictures\\lined-up\\overlay-rest.png`.replace(/\\/g, '/').toLowerCase()).file_id, 'l1')
  assert.equal(studioSubjectName(lined, context), 'elemental-hero-neos', 'named by the file the user attached')
  assert.equal(studioContext([{ role: 'assistant', tools: [{ name: 'import_model', result: {} }] }]).active, false)
})

test('pictures are captioned by what they show, not their chat file names', () => {
  assert.equal(pictureCaption(lined.result.files[0]), 'lined up · overlay rest')
  assert.equal(pictureCaption(picked.result.files[0]), 'fit C. Falcon · silhouette rest')
  assert.equal(pictureCaption(png('s', `${ROOT}\\07-check\\pictures\\spots\\01-off-the-floor.r_leg.j17.png`)),
    'spots · off the floor r leg j17')
  assert.equal(pictureCaption(game.result.files[0]), 'Idle, frame 1 · Run, frame 9')
  assert.equal(pictureCaption({ file_id: 'x', name: '05-parts_pictures_parts_parts-rest.png' }), 'parts parts rest')
  assert.equal(pictureCaption({ file_id: 'x', name: 'looks_1790634177351_shaded-rest-focus-39.png',
    path: `${ROOT}\\looks\\1790634177351\\shaded-rest-focus-39.png` }), 'shaded rest focus 39')
})

test('in-game shots pair the costume with the original when the reply carries both', () => {
  assert.deepEqual(gamePictures(game.result).pairs, [])
  assert.deepEqual(gamePictures(game.result).singles.map(file => file.file_id), ['g1', 'g2', 'g3'])
  const split = { files: [png('i1', `${ROOT}\\game-runs\\run-01\\captures\\import\\0x00-idle-f01.png`),
    png('v1', `${ROOT}\\game-runs\\run-01\\captures\\vanilla\\0x00-idle-f01.png`),
    png('i2', `${ROOT}\\game-runs\\run-01\\captures\\import\\0x00-run-f09.png`)] }
  const { pairs, singles } = gamePictures(split)
  assert.deepEqual(pairs.map(pair => [pair.import.file_id, pair.vanilla.file_id]), [['i1', 'v1']])
  assert.deepEqual(singles.map(file => file.file_id), ['i2'], 'a shot without its original is shown alone')
})

test('fresh_eyes shows the pictures it was given, found by path or file ID', () => {
  const context = studioContext(chat)
  const eyes = { name: 'fresh_eyes', arguments: { question: 'Any gaps?', pictures: [
    `${ROOT}\\04-line_up\\pictures\\lined-up\\overlay-rest.png`, 'c1', `${ROOT}\\gone.png`] } }
  const shown = freshEyesPictures(eyes, context)
  assert.deepEqual(shown.files.map(file => file.file_id), ['l1', 'c1'])
  assert.equal(shown.missing, 1)
})

test('what a call changed reads in one short line', () => {
  assert.deepEqual(studioChanges(lined).map(row => [row.kind, row.op || '', row.text]),
    [['Change', 'move_part', '{part: r_leg, translation: [0, -0.86, 0]}']])
  const weight = { name: 'weight', arguments: { project: 'neos', per_part: { head: 'transfer', torso: 'transfer' }, reason: 'why' } }
  assert.deepEqual(studioChanges(weight).map(row => row.text), ['per_part → {head: transfer, torso: transfer}'])
  assert.deepEqual(studioChanges({ name: 'import_status', arguments: { project: 'neos', undo: { stage: 5, op: 0 } } })
    .map(row => [row.kind, row.text]), [['Undo', 'change 0 of stage 5']])
  assert.deepEqual(studioChanges({ name: 'decide', arguments: { stage: 4, name: 'placement', value: { floor: false } } })
    .map(row => row.text), ['placement → {floor: no}'])
  assert.deepEqual(studioChanges({ name: 'look', arguments: { project: 'neos', focus: 39, views: ['front', 'side'] } })
    .map(row => row.text), ['views [front, side] · focus 39'])
  assert.deepEqual(studioChanges({ name: 'test_in_game', arguments: { project: 'neos', finish_as: 'Neos' } })
    .map(row => [row.kind, row.text]), [['Save as', 'Neos']])
  assert.equal(studioChanges({ name: 'line_up', arguments: { project: 'neos' } }).length, 0, 'a plain run changes nothing')
})

test('warnings are shown, notes are one click away', () => {
  const failed = { stage: 6, name: 'weight', status: 'failed', error: 'joint_band needs 0 < share < 1', fix_at: 6,
    rolled_back: 'Not kept: op joint_band (stage 6 op 0).', input_notes: ['recorded as strategy'],
    questions: [{ id: '2:up_axis', question: 'Which source axis points up?', options: ['y', 'z'], proposal: 'y' }] }
  const { warnings, notes } = studioNotes(failed)
  assert.deepEqual(warnings, ['Not kept: op joint_band (stage 6 op 0).'])
  assert.deepEqual(notes, ['recorded as strategy'])
  assert.deepEqual(studioQuestions(failed), [{ id: '2:up_axis', question: 'Which source axis points up?', proposal: 'y' }])
  const game10 = studioNotes(game.result)
  assert.deepEqual(game10.warnings, ['run frame 9: the costume and the original were not caught on the same frame.'])
  assert.equal(game10.notes.length, 1)
})

test('a card says how the call went in a word', () => {
  assert.equal(studioStatusText(lined), 'Done')
  assert.equal(studioStatusText({ ...lined, status: 'running', result: undefined }), 'Working')
  assert.equal(studioStatusText(call('line_up', { error: 'takes no selection' })), 'Not run')
  assert.equal(studioStatusText(call('weight', { stage: 6, name: 'weight', status: 'failed', error: 'x' })), 'Failed')
  assert.equal(studioStatusText(call('fresh_eyes', { unavailable: 'no key' })), 'Not available')
})

test('import_status reads as one row per stage', () => {
  const rows = stageRows({ stages: [{ stage: 2, name: 'clean', status: 'done', ops: [{ index: 0 }] },
    { stage: 4, name: 'line_up', status: 'failed', failure: 'no legs', ops: [] },
    { stage: 5, name: 'parts', status: 'stale', ops: [], stale: 'code changed' }] })
  assert.deepEqual(rows.map(row => [row.stage, row.title, row.status, row.ops, row.outdated]),
    [[2, 'Clean up', 'done', 1, false], [4, 'Line up', 'failed', 0, false], [5, 'Parts', 'stale', 0, true]])
})


test('import_model: the job reply read for its card; a running job is the studio\'s', () => {
  const csp = png('c1', `${ROOT}\\finish\\csp.png`)
  const reply = { status: 'done', fighter: 'C. Falcon', seconds: 61, cost_usd: 0.00042, files: [csp],
    saved: { name: 'Neos', character: 'C. Falcon' }, ...tag('import_model') }
  const read = importJob(reply)
  assert.deepEqual(read.pictures.map(file => file.file_id), ['c1'])
  assert.equal(read.cost, '$0.00042')
  assert.equal(read.saved.name, 'Neos')
  assert.equal(costText(0.0123), '$0.01')
  const tool = { id: 'j', name: 'import_model', status: 'done', arguments: { source: 'a'.repeat(32) }, result: reply }
  assert.equal(importStatusText(tool), 'Saved to your vault')
  assert.equal(importStatusText({ ...tool, result: { ...reply, saved: null } }), 'Done, not saved')
  assert.equal(importStatusText({ ...tool, result: { status: 'failed', failed: { stage: 'load' } } }), 'Failed')
  assert.equal(importStatusText({ ...tool, result: { status: 'cancelled', saved: null } }), 'Stopped',
    'the user stopped it: the call finished, the import did not')
  const textures = { status: 'needs_textures', textures: ['Clank.mtl'], warning: ' Clank.obj came without... ' }
  // Build 3 smoke: Clank.mtl is the model's materials file, not a texture.
  assert.equal(importStatusText({ ...tool, result: textures }), 'Waiting on its files')
  assert.equal(importStatusText({ ...tool, result: { ...textures, textures: ['body.png'] } }), 'Waiting on its textures')
  assert.deepEqual([importJob(textures).warning, importJob(textures).textures], ['Clank.obj came without...', ['Clank.mtl']])
  assert.equal(importJob(reply).warning, null)
  // 0.9.0: the tools it runs on are a download; a reply that needs them says so and carries their size.
  const tools = { status: 'needs_tools', warning: 'Model import needs its tools.',
    tools: { state: 'not_installed', download_bytes: 750e6, needed_bytes: 750e6, disk_bytes: 1.6e9 } }
  assert.equal(importStatusText({ ...tool, result: tools }), 'Needs its tools')
  assert.deepEqual([importJob(tools).warning, importJob(tools).tools.needed_bytes], ['Model import needs its tools.', 750e6])
  assert.equal(importJob(reply).tools, null)
  assert.equal(importJob({ ...reply, tools: { state: 'x' } }).tools, null, 'only a needs_tools reply carries them')
  assert.equal(isStudioTool(tool), true)
  assert.equal(isStudioTool({ name: 'import_model', status: 'running' }), true, 'before its first progress')
  assert.equal(studioFighter(tool, null), 'C. Falcon')
  const context = studioContext([user, { role: 'assistant', tools: [{ ...tool, result: { ...reply, ...tag('import_model', 'neos-9') } }] }])
  assert.equal(context.active, true)
  assert.equal(context.sources.get('neos-9'), 'elemental-hero-neos.zip', 'named by the file the user attached')
  // An older chat's v4 reply: what only v4 sent is not read.
  const old = importJob({ status: 'needs_user', stages: [{ stage: 2, name: 'clean', status: 'done' }],
    decisions: ['Facing: view A'], choices: [{ id: 'D1', line: 'x' }], sheet: { pictures: [] }, ...tag('import_model') })
  assert.deepEqual(Object.keys(old).filter(key => ['stages', 'decisions', 'choices', 'sheet', 'stopped'].includes(key)), [])
})

// -- the Tung Tung Tung Sahur import (the launch-video run): the costume file's pictures, its time, its name

test('the costume file\'s pictures are captioned by the pose they show, as people say it', () => {
  const files = tungDone().result.files.filter(file => /dat-/.test(file.name))
  assert.deepEqual(files.map(pictureCaption), ['Idle, frame 1', 'Run, frame 9', 'Neutral air, frame 5', 'Blink'])
  assert.deepEqual(files.map(({ path, ...file }) => pictureCaption(file)),
    ['Idle, frame 1', 'Run, frame 9', 'Neutral air, frame 5', 'Blink'], 'by the chat file name when there is no path')
  // Melee's animation names, in words.
  assert.deepEqual(['AttackAirF-3', 'AttackAirB-2', 'AttackAirHi-4', 'AttackAirLw-6', 'Attack11-2', 'AttackS3S-5',
    'AttackHi3-1', 'AttackLw4-7', 'AttackS4S-9', 'AttackDash-4', 'Catch-2', 'EscapeN-3'].map(poseCaption),
  ['Forward air, frame 3', 'Back air, frame 2', 'Up air, frame 4', 'Down air, frame 6', 'Jab, frame 2',
    'Forward tilt, frame 5', 'Up tilt, frame 1', 'Down smash, frame 7', 'Forward smash, frame 9',
    'Dash attack, frame 4', 'Grab, frame 2', 'Spot dodge, frame 3'])
  assert.equal(poseCaption('Squat-5'), 'Squat, frame 5')
  assert.equal(poseCaption('SomethingNew-2'), 'SomethingNew, frame 2', 'a name not known stays as it is')
  assert.equal(poseCaption('rest pose'), 'rest pose')
  // The other pictures keep their captions.
  assert.equal(pictureCaption({ file_id: 'x', path: 'C:\\imports\\t\\02-clean\\pictures\\textured\\shaded-rest.png' }),
    'textured · shaded rest')
  assert.equal(pictureCaption({ file_id: 'x', path: 'C:\\imports\\t\\09-export\\pictures\\eyes\\dat-blink.png' }),
    'eyes · dat blink', 'only the costume file\'s own folder is read as poses')
  assert.equal(pictureCaption({ file_id: 'x', name: '09-export_pictures_dat_Wait-1.png' }), 'dat Wait 1')
})

test('the import\'s time is the status bar\'s clock and words: live while it runs, stopped when it ends', () => {
  const now = Date.UTC(2026, 9, 6, 12)
  const { tool, reply, turnStart } = tungRunning({ now })
  assert.equal(tool.result.seconds, 150, 'the last progress event said 2.5 min')
  const card = importTimeText(tool, { startedAt: turnStart, now })
  assert.equal(card, '2 min 55 sec')
  const bar = elapsedText(taskProgress({ ...reply, tools: [tool] }, now).elapsedSeconds)
  assert.equal(card, bar, 'the card and the status bar read the same')
  assert.equal(importTimeText(tool, { startedAt: turnStart, now: now + 1000 }), '2 min 56 sec', 'a second later')
  assert.equal(importTimeText(tool, { now }), '2 min 52 sec', 'without the turn: from the call\'s own start')
  assert.equal(importTimeText({ ...tool, started_at: undefined }, { now }), '2 min 30 sec',
    'no start at all: the reply\'s own seconds')
  // Done: the same clock, stopped when the call finished (the turn started 2.9 s before it).
  const done = tungDone()
  assert.equal(importTimeText(done, { startedAt: tungReply().started_at }), '6 min 48 sec')
  assert.equal(importTimeText(done), '6 min 45 sec', 'the call\'s own start and end')
  assert.equal(importTimeText({ ...done, started_at: null, completed_at: null }), '6 min 38 sec', 'an older reply')
  assert.equal(importTimeText({ name: 'import_model', status: 'done', result: {} }), null)
})

test('the chat knows when each call\'s turn started; an import is named by its saved costume once it has one', () => {
  const done = tungDone()
  const context = studioContext(tungChat(done))
  assert.equal(context.turnStart.get(done.id), tungReply().started_at)
  assert.equal(studioSubjectName(done, context), 'Tung Tung Tung Sahur', 'the name in the vault, from the user\'s message')
  const { tool } = tungRunning()
  assert.equal(studioSubjectName(tool, studioContext(tungChat(tool))), 'tung_tung_sahur',
    'before it saves: the file the user attached')
})
