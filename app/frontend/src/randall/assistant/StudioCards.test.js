import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'

const realRequire = createRequire(import.meta.url)
const loadModule = (file, resolve) => {
  const built = transformSync(readFileSync(new URL(file, import.meta.url), 'utf8'),
    { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const mod = { exports: {} }
  new Function('require', 'module', 'exports', built)(name => resolve(name) || realRequire(name), mod, mod.exports)
  return mod.exports
}
const activity = loadModule('./activity.js', () => null)
const studio = loadModule('./studio.js', name => ['./activity', './activity.js'].includes(name) ? activity : null)
const clock = loadModule('./clock.js', () => null)
// The model import tools' download box: the real view, its data (the shared hook: the api and the job store) faked.
const toolsHelpers = await import('../../settings/modelImportTools.js')
let toolsHook = { tools: null, job: null, busy: false, requestError: null, start() {}, cancel() {} }
const toolsDownload = loadModule('./ImportToolsDownload.jsx', name => {
  if (name === '../../settings/modelImportTools') return toolsHelpers
  if (name === '../../settings/useModelImportTools') return { useModelImportTools: () => toolsHook }
  return null
})
// Developer details: the cards below are drawn with it on (the import's cost shows) unless a test turns it off.
let devDetails = true
const cards = loadModule('./StudioCards.jsx', name => {
  if (name === './ImportToolsDownload') return toolsDownload
  if (name === './devDetails') return { useDevDetails: () => devDetails }
  if (name === './clock') return clock
  if (['./activity', './activity.js'].includes(name)) return activity
  if (['./studio', './studio.js'].includes(name)) return studio
  if (name === '../../shared/config/config') return { backendMediaUrl: value => `http://backend${value}` }
  if (name === './WorkbenchPanel') return { PICTURE_DRAG_TYPE: 'application/x-nucleus-file' }
  if (name.endsWith('.css')) return {}
  return null
})
const StudioToolCard = cards.default

const ROOT = 'C:\\imports\\neos'
const png = (id, path) => ({ file_id: id, name: path.slice(ROOT.length + 1).replace(/[\\/]+/g, '_'),
  size: 1000, extension: '.png', path })
let n = 0
const call = (name, result, extra = {}) => ({ id: `t${++n}`, name, status: result?.error ? 'error' : 'done',
  arguments: { project: 'neos' }, result: { ...result, studio_import: { tool: name, id: 'neos' } }, ...extra })
const render = (tool, messages = [{ role: 'assistant', tools: [tool] }]) =>
  renderToStaticMarkup(React.createElement(StudioToolCard, { tool, context: studio.studioContext(messages) }))
const count = (html, text) => html.split(text).length - 1

const picked = call('pick_fighter', { stage: 3, name: 'fighter', status: 'done', report: { fighter: 'C. Falcon' } })
const lined = call('line_up', { stage: 4, name: 'line_up', status: 'done',
  next: 'look at the pictures; when this stage is right, continue with stage 5 (parts)',
  report: { notes: ['l_leg: the sole sat 0.9% below the floor; the ankle aim moved up.'] },
  files: [png('l1', `${ROOT}\\04-line_up\\pictures\\landmarks\\overlay-rest.png`),
    png('l2', `${ROOT}\\04-line_up\\pictures\\lined-up\\overlay-rest.png`),
    png('l3', `${ROOT}\\04-line_up\\pictures\\silhouette\\silhouette-rest.png`)] },
{ arguments: { project: 'neos', op: 'move_part', arguments: { part: 'r_leg', translation: [0, -0.86, 0] },
  reason: 'Back foot rides 0.86 units above the floor in the dash.' } })

test('a stage card: which stage, how it went, its pictures, what changed and what is next', () => {
  const html = render(lined, [{ role: 'assistant', tools: [picked, lined] }])
  assert.match(html, /Lined up the model on C\. Falcon/)
  assert.match(html, /Stage 4 · Line up/)
  assert.match(html, />Done</)
  assert.equal(count(html, '<img '), 3, 'every picture the stage made is a thumbnail')
  assert.match(html, /src="http:\/\/backend\/api\/assistant\/files\/l2\?preview=1"/)
  assert.match(html, /lined up · overlay rest/)
  assert.match(html, /<code>move_part<\/code>/)
  assert.match(html, /part: r_leg, translation: \[0, -0\.86, 0\]/)
  assert.match(html, /Back foot rides/)
  assert.match(html, /Next<\/span>look at the pictures/)
  assert.match(html, /1 note from this step/)
  assert.doesNotMatch(html, /Finished a step|C:\\\\imports/, 'no fallback label and no local paths on screen')
})

test('a failed stage says what is wrong, where to fix it and what was not kept', () => {
  const failed = call('weight', { stage: 4, name: 'line_up', status: 'failed', fix_at: 4,
    error: "move_part needs one part: No part 'l_wing'; parts: ['head', 'l_arm']",
    rolled_back: 'Not kept: op move_part (stage 4 op 0).', next: 'fix what the error names and call line_up again',
    files: [png('x1', `${ROOT}\\failures\\04-1790634419610\\pictures\\failed\\overlay-rest.png`)] })
  const html = render(failed)
  assert.match(html, /assistant-tool--error/)
  assert.match(html, /Could not line up the model/)
  assert.match(html, /Stage 4 · Line up/)
  assert.match(html, />Failed</)
  assert.match(html, /role="alert"[^>]*><p>move_part needs one part/)
  assert.match(html, /Not kept: op move_part/)
  assert.equal(count(html, '<img '), 1, 'the failure picture is shown')
  const elsewhere = render(call('weight', { stage: 6, name: 'weight', status: 'failed', fix_at: 4, error: 'x' }))
  assert.match(elsewhere, /The fix belongs at Stage 4 · Line up/)
  const refused = render(call('line_up', { error: 'stage 4 op move_part takes no selection' }))
  assert.match(refused, />Not run</)
  assert.doesNotMatch(refused, /assistant-tool--error/, 'a refused call is not a failed stage')
})

test('a running studio call is one working line with its stage', () => {
  const html = render({ id: 'r', name: 'check_moves', status: 'running' }, [{ role: 'assistant', tools: [picked] }])
  assert.match(html, /Checking the model in C\. Falcon&#x27;s moves/)
  assert.match(html, /Stage 7 · Move check/)
  assert.match(html, /assistant-work-pulse/)
})

test('the studio test_in_game shows its in-game pictures three across, not "No game was started"', () => {
  const game = call('test_in_game', { stage: 10, name: 'game', status: 'done',
    next: 'finished: test_in_game with finish_as saves it',
    report: { status: 'captured', identity: { fighter: 'C. Falcon', import: { requested_slot: 6, loaded_slot: 6, slot_matches: true } },
      frames: [1, 2, 3, 4, 5, 6].map(i => ({ move: `m${i}`, frame: i, status: 'captured', frame_match: true, import: {}, vanilla: {} })),
      notes: ['import run frame 9: the model touches the frame edge at the fixed camera.'] },
    files: [png('g1', `${ROOT}\\game-runs\\run-01\\pictures\\game-01-idle1-run9.png`),
      png('g2', `${ROOT}\\game-runs\\run-01\\pictures\\game-02-jab3-fair5.png`),
      png('g3', `${ROOT}\\game-runs\\run-01\\pictures\\game-03-upb5-fsmash10.png`)] })
  const html = render(game)
  assert.match(html, /Tried the costume in the game beside the original C\. Falcon/)
  assert.match(html, /Stage 10 · In game/)
  assert.match(html, /is-triptych/)
  assert.equal(count(html, '<img '), 3)
  assert.match(html, /Idle, frame 1 · Run, frame 9/)
  assert.match(html, /Up-B, frame 5 · Forward smash, frame 10/)
  assert.match(html, /costume slot 6, as asked · 6 of 6 moves caught beside the original/)
  assert.doesNotMatch(html, /No game was started/)
  // Captures carried as separate files are paired with the original.
  const split = call('test_in_game', { stage: 10, name: 'game', status: 'done', files: [
    png('i1', `${ROOT}\\game-runs\\run-01\\captures\\import\\0x00-idle-f01.png`),
    png('v1', `${ROOT}\\game-runs\\run-01\\captures\\vanilla\\0x00-idle-f01.png`)] })
  const paired = render(split)
  assert.match(paired, /assistant-studio-pair/)
  assert.match(paired, /Idle, frame 1 · yours, then the original/)
})

test('finishing saves to the vault, and a refused finish says so', () => {
  const refused = render(call('test_in_game', { error: 'finish_as is not available in this run.' },
    { arguments: { project: 'neos', finish_as: 'Elemental Hero Neos' } }))
  assert.match(refused, /Could not save the costume to your vault/)
  assert.match(refused, /Save as<\/span><span class="assistant-studio-value">Elemental Hero Neos/)
  assert.match(refused, /finish_as is not available/)
  const saved = render(call('test_in_game', { vault: { name: 'Neos', character: 'C. Falcon' }, installable: true,
    notes: ['The stock icon is the vanilla fighter\'s own icon.'] }, { arguments: { project: 'neos', finish_as: 'Neos' } }))
  assert.match(saved, /Saved the costume to your vault/)
  assert.match(saved, /“Neos” · C\. Falcon · in your vault/)
})

test('fresh_eyes shows the pictures it saw and its verdict', () => {
  const eyes = call('fresh_eyes', { answer: 'The wings stick straight out as if T-posing.', cost_usd: 0.001, error: null,
    problems: [{ where: 'Wait-1, front', what: 'Wings stick out sideways' }] },
  { arguments: { question: 'Do the wings look natural?', pictures: [`${ROOT}\\04-line_up\\pictures\\lined-up\\overlay-rest.png`] } })
  const html = render(eyes, [{ role: 'assistant', tools: [lined, eyes] }])
  assert.match(html, /Got a second opinion/)
  assert.match(html, /Asked<\/span><span class="assistant-studio-value">Do the wings look natural\?/)
  assert.match(html, /files\/l2\?preview=1/)
  assert.match(html, /<blockquote[^>]*>The wings stick straight out/)
  assert.match(html, /<strong>Wait-1, front<\/strong>Wings stick out sideways/)
  const failed = render(call('fresh_eyes', { answer: null, problems: [], error: 'deadline passed',
    failed: 'fresh_eyes failed: deadline passed; nothing here is a verdict' }))
  assert.match(failed, /Could not get a second opinion/)
  assert.match(failed, /nothing here is a verdict/)
})

test('look, decide and import_status get their own compact cards', () => {
  const look = render(call('look', { stage: 7, mode: 'parts', by: 'parts', notes: [],
    files: [png('k1', `${ROOT}\\looks\\1790634372443\\parts-Catch-8-focus-23.png`)] },
  { arguments: { project: 'neos', mode: 'parts', poses: ['Catch-8'], focus: 23 } }))
  assert.match(look, /Took a closer look/)
  assert.match(look, /Stage 7 · Move check/)
  assert.match(look, /View<\/span><span class="assistant-studio-value">mode parts · poses \[Catch-8\] · focus 23/)
  assert.equal(count(look, '<img '), 1)
  const decide = render(call('decide', { decided: '4:placement', value: { floor: false }, stale_from: 4,
    next: 'run stage 4 (line_up) to see it: line_up' },
  { arguments: { project: 'neos', stage: 4, name: 'placement', value: { floor: false }, reason: 'keep the soles' } }))
  assert.match(decide, /Recorded a choice for the import/)
  assert.match(decide, /placement → \{floor: no\}/)
  assert.match(decide, /Stage 4 and the stages after it run again with it/)
  const status = render(call('import_status', { stages: [
    { stage: 2, name: 'clean', status: 'done', ops: [] }, { stage: 3, name: 'fighter', status: 'done', ops: [] },
    { stage: 4, name: 'line_up', status: 'failed', failure: 'no legs', ops: [{ index: 0 }] },
    { stage: 5, name: 'parts', status: 'stale', ops: [] }], choices: [{ stage: 3, name: 'fighter' }], questions: [],
  next: 'stage 4 (line_up)' }))
  assert.match(status, /Checked where the import is/)
  assert.equal(count(status, 'assistant-studio-stage-number'), 4)
  assert.match(status, /class="is-failed" title="no legs"/)
  assert.match(status, /Line up<\/span><small>Failed · 1 change/)
  assert.match(status, /1 choice recorded/)
})


// -- import mode: import_model (rigswap) is one card for the whole job

const JOB = 'C:\\imports\\neos-1a2b3c'
const job = (result, extra = {}) => ({ id: `j${++n}`, name: 'import_model', status: 'done',
  arguments: { source: 'a'.repeat(32), fighter: 'C. Falcon' },
  result: { ...result, studio_import: { tool: 'import_model', id: 'neos-1a2b3c' } }, ...extra })
const { tungChat, tungDone, tungRunning } = await import('./__fixtures__/tungImportFixture.js')

test('a rigswap import_model reply: done with its portrait, failed in its own words where it stopped', () => {
  const csp = png('c1', `${JOB}\\finish\\csp.png`)
  const done = render(job({ status: 'done', project: 'neos-1a2b3c', fighter: 'Ganondorf', costume_name: 'Neos',
    seconds: 212.4, cost_usd: 0.0123, fighter_pick: { fighter: 'Ganondorf', why: 'his broad build' },
    pictures: [csp.path], files: [csp], saved: { name: 'Neos', character: 'Ganondorf', installable: true,
      notes: ['The Slippi fix changed the stored copy.'] },
    vault_changed: true, next: 'Reply in one or two short sentences' }, { arguments: { source: 'a'.repeat(32) } }))
  assert.match(done, /Imported your model onto Ganondorf/)
  assert.match(done, />Saved to your vault</)
  assert.match(done, /Ganondorf · 3 min 32 sec · \$0\.01 for the import/)
  assert.match(done, /Saved to your vault as “Neos” · Ganondorf/)
  assert.match(done, /1 note from saving it/)
  assert.match(done, /files\/c1\?preview=1/)
  assert.doesNotMatch(done, /assistant-studio-stage-number|Reply in one/, 'no stages; the reply\'s instructions to Randall are not shown')
  const failed = render(job({ status: 'failed', project: 'neos-1a2b3c', fighter: 'Marth', seconds: 30, cost_usd: 0,
    failed: { stage: 'load', name: 'Load the model', where: 'while loading the model file', kind: 'located',
      cause: 'nothing to open in neos.zip', can_do: ['attach the model again in another format', 'report it'] },
    diagnostic: 'RuntimeError: nothing to open in neos.zip' }))
  assert.match(failed, /Could not import your model/)
  assert.match(failed, />Failed</)
  assert.match(failed, /Stopped while loading the model file: nothing to open in neos\.zip/)
  assert.doesNotMatch(failed, /Stopped at stage|Saved to your vault/)
})

test('import_model: its cost only with developer details on; not saved and stopped say so', () => {
  const done = job({ status: 'done', fighter: 'Fox', seconds: 61, cost_usd: 0.0011, saved: { name: 'Neos', character: 'Fox' } })
  devDetails = false
  try {
    const plain = render(done)
    assert.match(plain, /Fox · 1 min 1 sec<\/p>/)
    assert.doesNotMatch(plain, /\$|for the import/, 'users never see dollars')
  } finally { devDetails = true }
  const unsaved = render(job({ status: 'done', not_saved: 'Saving to the vault is not available in this run.' }))
  assert.match(unsaved, />Done, not saved</)
  assert.match(unsaved, /Not saved: Saving to the vault is not available/)
  const stopped = render(job({ status: 'cancelled', project: 'neos-1a2b3c', fighter: 'Fox', saved: null }))
  assert.match(stopped, /Your model import stopped before it saved/)
  assert.doesNotMatch(stopped, /Saved to your vault|Imported your model/)
})

test('import_model: a model without its textures says which files; the import\'s own check is shown as written', () => {
  // 0.9.0 smoke: a bare Clank.obj came without its Clank.mtl (backend import_job.textures_reply). Build 3: Randall
  // called the .mtl "a texture file"; it is the model's materials file, and the card says "files", not "textures".
  const textures = render(job({ status: 'needs_textures', textures: ['Clank.mtl'], next: 'Nothing was imported yet.',
    warning: 'Clank.obj came without the materials file Clank.mtl. Without it the model would import with no textures (all white).' }))
  assert.match(textures, /Your model came without files it needs/)
  assert.match(textures, />Waiting on its files</)
  assert.match(textures, /assistant-studio-warnings"><li>Clank\.obj came without the materials file Clank\.mtl\./)
  assert.doesNotMatch(textures, /stopped before it saved|Nothing was imported yet|its textures</)
  // 0.9.0 smoke (a bare sack_boy.fbx): its heading showed a ✓ over "Waiting on its textures". Nothing ran: it waits
  // on the user, a warning mark, and no error either.
  assert.match(textures, /<section class="assistant-tool assistant-studio is-waiting assistant-studio-import"/)
  assert.match(textures, /aria-hidden="true">!<\/span><strong>Your model came without files it needs</)
  assert.doesNotMatch(textures, /✓|assistant-tool--error/)
  // Only images missing: those are its textures.
  const images = render(job({ status: 'needs_textures', textures: ['body.png', 'Face.TGA'], next: 'Nothing was imported yet.',
    warning: 'Scorpion.fbx came without the textures body.png, Face.TGA. Without them the model would import with no textures (all white).' }))
  assert.match(images, /aria-hidden="true">!<\/span><strong>Your model came without its textures</)
  assert.match(images, />Waiting on its textures</)
  const warned = render(job({ status: 'done', fighter: 'Fox', saved: { name: 'Clank', character: 'Fox' },
    warning: 'this probably did not work: Small parts float apart from the body during the run' }))
  assert.match(warned, /<li>This probably did not work: Small parts float apart from the body during the run<\/li>/)
  assert.match(warned, /is-done/)
  assert.match(warned, /aria-hidden="true">✓<\/span>/, 'a saved import keeps its ✓')
})

test('import_model: tools still to download say so, with a Download button that follows the download', () => {
  // 0.9.0: Blender and rigswap's Python are an optional download (backend import_job.tools_reply). Nothing ran.
  const reply = job({ status: 'needs_tools', next: 'Nothing ran.', warning: 'model import needs its tools first: '
    + 'Blender and a Python setup, a one-time download of about 791 MB.',
  tools: { state: 'not_installed', download_bytes: 791e6, needed_bytes: 791e6, disk_bytes: 1.62e9 } })
  toolsHook = { ...toolsHook, tools: null, job: null }
  const html = render(reply)
  assert.match(html, /<section class="assistant-tool assistant-studio is-waiting assistant-studio-import"/)
  assert.match(html, /aria-hidden="true">!<\/span><strong>Model import needs its tools</)
  assert.match(html, />Needs its tools</)
  assert.match(html, /assistant-studio-warnings"><li>Model import needs its tools first: Blender and a Python setup/)
  assert.match(html, /<button type="button" class="assistant-studio-tools-button">Download the tools \(about 791 MB\)<\/button>/)
  assert.match(html, /Settings, under AI/)
  assert.doesNotMatch(html, /✓|assistant-tool--error|stopped before it saved|Nothing ran/)
  // The download started (here or in Settings): its progress, and Cancel.
  const tools = { platform: 'win-x64', supported: true, state: 'downloading', download_bytes: 791e6, needed_bytes: 791e6,
    disk_bytes: 1.62e9, disk_estimated: true, pieces: [], path: 'C:\\x', job: null, error: null }
  toolsHook = { ...toolsHook, tools, job: { id: 'd', status: 'running', progress: 0.3, detail: 'Downloading Blender 4.3.2' } }
  const running = render(reply)
  assert.match(running, /role="status">Downloading the tools · 30%</)
  assert.match(running, /class="assistant-studio-tools-fill" style="width:30%"/)
  assert.match(running, />Cancel<\/button>/)
  assert.doesNotMatch(running, /Download the tools \(/)
  // Cancelled part way: paused, with what is in, and the button resumes it (build 3 smoke: it said "Not installed").
  toolsHook = { ...toolsHook, tools: { ...tools, state: 'paused', download_bytes: 779e6, needed_bytes: 611e6,
    downloaded_bytes: 168e6 }, job: null }
  const paused = render(reply)
  assert.match(paused, /role="status">Paused · 168 of 779 MB</)
  assert.match(paused, /<button type="button" class="assistant-studio-tools-button">Resume the download \(about 611 MB\)<\/button>/)
  assert.doesNotMatch(paused, />Cancel<|Download the tools \(/)
  // Done: the import can be asked for again.
  toolsHook = { ...toolsHook, tools: { ...tools, state: 'installed', disk_estimated: false }, job: null }
  const ready = render(reply)
  assert.match(ready, /The tools are installed\. Ask Randall to import it again\./)
  assert.doesNotMatch(ready, /<button/)
  toolsHook = { ...toolsHook, tools: null }
  // Any other import reply has no download box.
  assert.doesNotMatch(render(job({ status: 'done', fighter: 'Fox', saved: { name: 'Neos', character: 'Fox' } })),
    /assistant-studio-tools/)
})

test('import_model running: its plain step (never rigswap\'s raw line) and the status bar\'s clock, live', () => {
  const raw = ['load: neos.zip', "00:03.485 render | Saved: 'E:\\Nucleus Data\\scratch\\front-1.png'"]
  const html = render(job({ status: 'running', fighter: 'Marth', progress: raw, step: 'putting it on the fighter',
    seconds: 40 }, { status: 'running' }))
  assert.match(html, /Importing your model/)
  assert.match(html, />Working</)
  assert.match(html, /role="status">Putting it on the fighter/)
  assert.doesNotMatch(html, /render \||Saved: |Nucleus Data\\\\scratch/, 'no clock, log tag or path')
  // No step yet: nothing, unless developer details are on (then the raw line, for debugging).
  const noStep = job({ status: 'running', fighter: 'Marth', progress: raw, seconds: 40 }, { status: 'running' })
  devDetails = false
  try {
    assert.doesNotMatch(render(noStep), /role="status"/)
    assert.match(render({ ...noStep, result: { ...noStep.result, step: 'loading the model' } }), /role="status">Loading the model/)
  } finally { devDetails = true }
  assert.match(render(noStep), /role="status">00:03\.485 render/)
  assert.match(html, /Marth · 40 sec so far/, 'no start time recorded: the reply\'s own seconds')
  const early = render({ id: 'e', name: 'import_model', status: 'running', arguments: { source: 'a'.repeat(32) } })
  assert.match(early, /Importing your model/, 'a card before the first progress arrives')
  // 175 s into the turn; the last progress event said 150 s, which the card once showed as "2.5 min".
  const { tool, reply } = tungRunning({ now: Date.now() })
  const live = render(tool, tungChat(tool, reply))
  assert.match(live, /Young Link · 2 min 55 sec so far/)
  assert.doesNotMatch(live, /2\.5 min|150 s/)
  const done = tungDone()
  assert.match(render(done, tungChat(done)), /Young Link · 6 min 48 sec/, 'done: the same clock, stopped at the end')
})

test('an older chat\'s v4 import_model reply draws as the plain card: no phases, buttons, stages or sheet', () => {
  // The Tung Tung Tung Sahur import as its chat stored it: its flow, stages, end summary choices and picture sheet.
  const done = tungDone()
  for (const on of [true, false]) {
    devDetails = on
    try {
      const html = render(done, tungChat(done))
      assert.match(html, /Imported your model onto Young Link/)
      assert.match(html, /Saved to your vault as “Tung Tung Tung Sahur” · Young Link/)
      assert.equal(count(html, '<img '), 5, 'every picture it carries, the old sheet among them')
      assert.doesNotMatch(html, /role="tab"|<button[^>]*value=|assistant-studio-stage-number|Picture sheet|questions to GLM/)
    } finally { devDetails = true }
  }
  // One that stopped on a question (it carried on when asked, back then): stopped, nothing to click, no question.
  const asked = render(job({ status: 'needs_user', fighter: 'C. Falcon', seconds: 200, questions_left: 2,
    question: { point: 'D1-pieces', title: 'Pieces to drop', question: 'Which numbered pieces are spare copies?' },
    choices: [{ id: 'D1', what: 'Version', line: 'I used normal Link.', alternative: { ask: 'Use Fierce Deity Link instead' } }],
    flow: { version: 1, status: 'needs_user', phases: [{ key: 'identify', status: 'needs_user', entries: [] }] } }))
  assert.match(asked, /Your model import stopped before it saved/)
  assert.doesNotMatch(asked, /Carry on|Which numbered pieces|Fierce Deity|<button[^>]*value=/)
  // A failed one names its stage by number: the card says where only in rigswap's words.
  const failed = render(job({ status: 'failed', failed: { stage: 6, cause: 'no bone for part 7' } }))
  assert.match(failed, /Stopped: no bone for part 7/)
  assert.doesNotMatch(failed, /stage 6/i)
})
