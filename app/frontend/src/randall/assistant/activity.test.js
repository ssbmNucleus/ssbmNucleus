import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { ACTIVITY, INTERMEDIATE_TOOLS, STUDIO_ACTIVITY, STUDIO_ONLY_TOOLS, STUDIO_STAGES, STUDIO_STAGE_TOOLS,
  activityLabel, elapsedText, onlyTexturesMissing, phraseForTool, isStudioResult, settledLines, studioActivity,
  studioActivityLabel } from './activity.js'

// The schema list lives in Python, so the source of truth is read from it
// rather than snapshotted: a snapshot would go stale the moment a tool lands,
// which is exactly when a missing label reaches a user as `deliver_to_game`.
const TOOLS_PY = new URL('../../../../backend/randall/assistant/tools.py', import.meta.url)
const toolNames = () => [...new Set([...readFileSync(TOOLS_PY, 'utf8')
  .matchAll(/_schema\(\s*'([a-z_]+)'/g)].map(match => match[1]))]

test('every tool in tools.py has a plain-language phrase', () => {
  const names = toolNames()
  assert.ok(names.length > 30, `only found ${names.length} tools — has the schema syntax changed?`)
  const missing = names.filter(name => !ACTIVITY[name])
  assert.deepEqual(missing, [], `these tools have no user-facing phrase in activity.js: ${missing.join(', ')}. `
    + 'Add one line each — the chat surface must never show a tool name.')
})

test('no phrase leaks an internal word', () => {
  for (const [name, phrase] of Object.entries(ACTIVITY)) {
    for (const text of [phrase.working, phrase.done]) {
      assert.ok(text && text[0] === text[0].toUpperCase(), `${name}: ${text}`)
      assert.doesNotMatch(text, /_|mesh|binding|alignment|candidate|DAT|hsdraw|CSP|silhouette|index/i, `${name}: ${text}`)
    }
  }
})

test('an unknown tool still never shows its own name', () => {
  assert.equal(activityLabel({ name: 'brand_new_tool', status: 'running' }), 'Working on your request')
  assert.equal(activityLabel({ name: 'brand_new_tool', status: 'done' }), 'Finished a step')
})

test('a material put on a stage is named for the stage, not the skin', () => {
  const stage = { name: 'skin_material', status: 'done', result: { action: 'apply', stage_target: { stage_code: 'GrOp' } } }
  assert.equal(activityLabel(stage), 'Material on the stage')
  assert.equal(phraseForTool(stage).done, 'Material on the stage')
  assert.equal(activityLabel({ name: 'skin_material', status: 'done', result: { action: 'apply' } }), 'Material on the skin')
  assert.doesNotMatch(activityLabel({ name: 'skin_material', status: 'running' }), /skin|stage/)
})

test('intermediate steps are working material, never the result the user judges', () => {
  for (const name of ['model_fit', 'model_candidate', 'model_revise', 'model_review', 'test_in_game',
    'deliver_to_game', 'download_website_mod']) {
    assert.equal(INTERMEDIATE_TOOLS.has(name), false, `${name} must stay visible`)
  }
  for (const name of ['model_mesh', 'model_probe', 'hsdraw']) assert.ok(INTERMEDIATE_TOOLS.has(name))
})

test('every ended-without-doing-it state gets the honest sentence, what was kept, and one alternative', () => {
  for (const status of ['error', 'denied', 'expired', 'cancelled', 'interrupted']) {
    const lines = settledLines({ name: 'download_website_mod', status })
    assert.ok(lines.sentence && lines.preserved && lines.alternative, status)
    assert.doesNotMatch(lines.sentence, /^Done|^Success/, status)
    assert.doesNotMatch(`${lines.sentence} ${lines.preserved} ${lines.alternative}`, /download_website_mod/)
  }
  // A denial changed nothing, and that is what it says.
  assert.match(settledLines({ name: 'install_project_mods', status: 'denied' }).preserved, /Nothing was changed/)
  // The backend's own error sentence is the honest sentence when there is one.
  assert.equal(settledLines({ name: 'model_fit', status: 'error', result: { error: 'The file has no bones.' } }).sentence,
    'The file has no bones.')
  assert.equal(settledLines({ name: 'model_fit', status: 'done' }), null)
})

test('a refusal the backend explained already says what to do next, so no "try again" is added', () => {
  const error = 'This request already generated its three images; ask again in a new message to make more.'
  const lines = settledLines({ name: 'generate_material', status: 'error', result: { error, refusal: 'image_allowance' } })
  assert.equal(lines.sentence, error)
  assert.equal(lines.alternative, '')
  assert.match(lines.preserved, /Everything finished before this is kept/)
  // An unexplained failure keeps its usual next step.
  assert.match(settledLines({ name: 'generate_material', status: 'error', result: { error: 'Boom.' } }).alternative,
    /Tell Randall what to try instead/)
})

// The v2 studio's tools are gone from the backend; older chats still hold their calls, routed by these names.
test('no app tool takes a name only the old studio used', () => {
  const shared = toolNames().filter(name => STUDIO_ONLY_TOOLS.has(name))
  assert.deepEqual(shared, [], 'a studio-only name is routed to the import cards before any reply arrives')
  assert.equal(STUDIO_ONLY_TOOLS.has('test_in_game'), false, 'the shared name is routed by the reply tag')
  for (const name of STUDIO_ONLY_TOOLS) assert.ok(STUDIO_STAGE_TOOLS[name] || STUDIO_ACTIVITY[name], name)
})

test('no studio phrase leaks an internal word', () => {
  const lines = []
  for (const stage of Object.values(STUDIO_STAGES)) {
    for (const fighter of ['Fox', null]) lines.push(stage.working(fighter), stage.done(fighter), stage.failed(fighter))
    lines.push(stage.title)
  }
  for (const phrase of Object.values(STUDIO_ACTIVITY)) lines.push(phrase.working, phrase.done, phrase.failed)
  for (const text of lines) {
    assert.ok(text && text[0] === text[0].toUpperCase(), text)
    assert.doesNotMatch(text, /_|mesh|binding|alignment|candidate|DAT|hsdraw|CSP|silhouette|index|null|undefined/i, text)
  }
})

const studio = (name, result, extra = {}) => ({ id: name, name, status: result?.error ? 'error' : 'done',
  result: { studio_import: { tool: name, id: 'neos' }, ...result }, ...extra })

test('a studio stage is named by what it did, on which fighter, at which stage', () => {
  const lined = studio('line_up', { stage: 4, name: 'line_up', status: 'done', next: 'continue with stage 5 (parts)' })
  assert.equal(studioActivityLabel(lined, 'Fox'), 'Lined up the model on Fox (stage 4)')
  assert.equal(activityLabel(lined, { fighter: 'Fox' }), 'Lined up the model on Fox (stage 4)')
  assert.equal(activityLabel(lined), 'Lined up the model on the fighter (stage 4)', 'never a tool name, never "Finished a step"')
  const running = { id: 'r', name: 'check_moves', status: 'running' }
  assert.equal(activityLabel(running, { fighter: 'C. Falcon' }), "Checking the model in C. Falcon's moves (stage 7)")
  // A weight call reruns a stale line-up first; the reply is about the stage that failed.
  const stale = studio('weight', { stage: 4, name: 'line_up', status: 'failed', error: 'No part l_wing', fix_at: 4 })
  assert.deepEqual(studioActivity(stale, 'Fox'), { phrase: 'Could not line up the model on Fox', stage: 4,
    title: 'Line up', outcome: 'failed' })
  // Turned down before any stage ran.
  const refused = studio('line_up', { error: 'stage 4 op move_part takes no selection' })
  assert.equal(studioActivity(refused, 'Fox').outcome, 'refused')
  assert.equal(studioActivity(studio('test_in_game', { stage: 10, name: 'game', status: 'done' }), 'C. Falcon').phrase,
    'Tried the costume in the game beside the original C. Falcon')
  assert.equal(studioActivityLabel(studio('test_in_game', { error: 'finish_as is not available' },
    { arguments: { finish_as: 'Neos', project: 'neos' } })), 'Could not save the costume to your vault')
  assert.equal(studioActivityLabel(studio('look', { stage: 7, mode: 'parts' })), 'Took a closer look (stage 7)')
  assert.equal(studioActivityLabel(studio('decide', { decided: '6:strategy', stale_from: 6 })),
    'Recorded a choice for the import (stage 6)')
  assert.equal(studioActivityLabel(studio('import_status', { stage: 5, name: 'parts', status: 'done' },
    { arguments: { project: 'neos', undo: { stage: 5, op: 0 } } })), 'Took back a change (stage 5)')
  assert.equal(studioActivityLabel(studio('fresh_eyes', { answer: null, error: 'timeout', failed: 'fresh_eyes failed' })),
    'Could not get a second opinion')
})

test('import_model is named by how the import ended', () => {
  const job = (result, extra = {}) => studio('import_model', result, { arguments: { source: 'a'.repeat(32) }, ...extra })
  assert.equal(studioActivity(job({ status: 'done' }), 'Fox').phrase, 'Imported your model onto Fox')
  assert.equal(studioActivity(job({ status: 'done' })).phrase, 'Imported your model')
  assert.equal(studioActivity(job({ status: 'failed', failed: { stage: 'load', cause: 'x' } }), 'Fox').outcome, 'failed')
  assert.equal(studioActivity(job({ status: 'failed', failed: { stage: 'load', cause: 'x' } }), 'Fox').phrase,
    'Could not import your model')
  assert.equal(studioActivity({ name: 'import_model', status: 'running' }).phrase, 'Importing your model')
  // A change to a finished import (what the user said looks wrong) is named as one.
  const change = (result, status = 'done') => studio('import_model', result, { status,
    arguments: { project: 'neos-1a2b3c', change: 'the legs look wrong' } })
  assert.equal(studioActivity(change({}, 'running'), 'Fox').phrase, 'Changing your import')
  assert.equal(studioActivity(change({ status: 'done' }), 'Fox').phrase, 'Changed your import')
  assert.equal(studioActivity(change({ status: 'failed', failed: { stage: 'fix', cause: 'x' } }), 'Fox').phrase,
    'Could not change your import')
  // A model without the texture files it names: nothing ran, the user is asked for them. Waiting on them, never done
  // (0.9.0 smoke: the card's heading showed a ✓ over "Waiting on its textures").
  // Build 3 smoke: a missing Clank.mtl is the model's materials file, not a texture, so the heading says "files".
  assert.deepEqual(studioActivity(job({ status: 'needs_textures', textures: ['Clank.mtl'] }), 'Fox'),
    { phrase: 'Your model came without files it needs', stage: null, title: null, outcome: 'waiting' })
  assert.deepEqual(studioActivity(job({ status: 'needs_textures', textures: ['body.png', 'eyes.tga'] }), 'Fox'),
    { phrase: 'Your model came without its textures', stage: null, title: null, outcome: 'waiting' })
  assert.equal(studioActivity(job({ status: 'needs_textures', textures: ['scene.bin', 'tex.png'] }), 'Fox').phrase,
    'Your model came without files it needs')
  assert.equal(onlyTexturesMissing({ textures: ['a.PNG', 'b.jpg'] }), true)
  assert.equal(onlyTexturesMissing({ textures: ['a.png', ' Clank.MTL '] }), false)
  assert.equal(onlyTexturesMissing({}), true)
  // The tools it runs on are still to download (0.9.0: an optional download): nothing ran, it waits on the user.
  assert.deepEqual(studioActivity(job({ status: 'needs_tools', tools: { state: 'not_installed' } }), 'Fox'),
    { phrase: 'Model import needs its tools', stage: null, title: null, outcome: 'waiting' })
  // An older chat's v4 import that stopped on a question: neither done nor failed, so stopped before it saved.
  assert.deepEqual(studioActivity(job({ status: 'needs_user' }), 'Fox'), { phrase: 'Your model import stopped before it saved',
    stage: null, title: null, outcome: 'done' })
})

test('the old play-session test_in_game keeps its own label', () => {
  assert.equal(activityLabel({ name: 'test_in_game', status: 'done', result: { game_test: { session_id: 's' } } }),
    'Checked it in the game')
  assert.equal(isStudioResult({ game_test: {} }), false)
  assert.equal(isStudioResult({ studio_import: { tool: 'test_in_game', id: 'x' } }), true)
})

test('elapsed time reads as time', () => {
  assert.equal(elapsedText(9), '9 sec')
  assert.equal(elapsedText(60), '1 min')
  assert.equal(elapsedText(95), '1 min 35 sec')
})


test('a cancelled model import is stopped even when its tool envelope is done', () => {
  const tool = studio('import_model', { status: 'cancelled' })
  assert.deepEqual(studioActivity(tool, 'Fox'), {
    phrase: STUDIO_ACTIVITY.stopped.done, stage: null, title: null, outcome: 'done',
  })
  assert.doesNotMatch(studioActivityLabel(tool, 'Fox'), /Imported your model/)
})
