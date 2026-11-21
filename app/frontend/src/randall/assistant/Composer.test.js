// Randall's message bar in each state of a chat, server-rendered with the real
// ChatInput, task pill, starting-point chips and pick control: the new-chat screen
// (the box in the middle of the page, the chips under it), a workflow chosen (the
// pill and the pick control inside the box, nothing in the page), a sent chat, and
// chats stored under a task this build does not offer.
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as taskModes from './taskModes.js'
import * as startPick from './startPick.js'
import * as pickPopover from './pickPopover.js'
import * as chatList from '../chat/chatList.js'
import * as access from './access.js'
import * as costumePicks from '../../vault/picker/costumePicks.js'
import * as stagePicks from '../../vault/picker/stagePicks.js'

const realRequire = createRequire(import.meta.url)
const noop = () => {}
function load(path, stubs) {
  const code = transformSync(readFileSync(new URL(path, import.meta.url), 'utf8'), { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const module = { exports: {} }
  new Function('require', 'module', 'exports', code)(name => name in stubs ? stubs[name]
    : name.endsWith('.css') ? {} : realRequire(name), module, module.exports)
  return module.exports
}
const sounds = { playSound: noop, playHoverSound: noop }
const config = { backendMediaUrl: path => `http://backend${path}` }
const Sprites = { Randall: ({ size }) => React.createElement('img', { 'data-sprite': 'randall', width: size }) }
const GalleryGrid = load('../../shared/ui/GalleryGrid.jsx', { '../audio/sounds': sounds })
const pickerStubs = { '../../shared/ui/GalleryGrid': GalleryGrid, '../../shared/transport/api': { api: { get: () => new Promise(noop) } },
  '../../shared/config/config': config, '../../shared/audio/sounds': sounds, './costumePicks': costumePicks, './stagePicks': stagePicks }
const Composer = load('./Composer.jsx', {
  '../chat/ChatUI': load('../chat/ChatUI.jsx', { './chatList': chatList, '../assistant/access': access, '../../shared/ui/Sprites': Sprites, '../../shared/audio/sounds': sounds }),
  '../../shared/ui/Sprites': Sprites,
  './TaskPicker': load('./TaskPicker.jsx', { './taskModes': taskModes }),
  './StartPicker': load('./StartPicker.jsx', { '../../vault/picker/CostumePicker': load('../../vault/picker/CostumePicker.jsx', pickerStubs),
    '../../vault/picker/StagePicker': load('../../vault/picker/StagePicker.jsx', pickerStubs), './startPick': startPick, './pickPopover': pickPopover,
    '../../shared/config/config': config }),
}).default

const FIVE = [
  { id: 'recolor_part', label: 'Retexture a costume', group: 'Characters', hint: 'Pick a costume.', picker: 'costume', available: true, placeholder: 'Which costume, and what look?' },
  { id: 'model_import', label: 'Import a character model', group: 'Characters', hint: 'Turn a 3D model into a costume.', picker: 'fighter', available: true },
  { id: 'create_character', label: 'Create a character', group: 'Characters', hint: 'Coming later.', picker: null, available: false },
  { id: 'recolor_stage', label: 'Retexture a stage', group: 'Stages', hint: 'Pick a stage.', picker: 'stage', available: true },
  { id: 'stage_import', label: 'Import a stage model', group: 'Stages', hint: 'Coming later.', picker: null, available: false },
]
const startable = taskModes.startableTasks(FIVE)
// What AssistantPanel hands the bar for a chat in a given state.
const bar = ({ task = null, locked = false, start = !locked, pick = null, tasks = FIVE, ready = true } = {}) => {
  const picker = locked ? null : startPick.pickerFor(startable, task)
  const placeholder = !locked ? startPick.pickPlaceholder(picker, pick) || taskModes.placeholderFor(startable, task, null) : null
  return renderToStaticMarkup(React.createElement(Composer, {
    start, tasks, ready, starters: [['Explain Nucleus features', 'Explain the features available in Nucleus.']],
    task, locked, picker, pick, pickSources: {}, onTask: noop, onPick: noop, onClearPick: noop, onStarter: noop, onSubmit: noop,
    nowrapPlaceholder: Boolean(placeholder),
    attach: React.createElement('button', { type: 'button', className: 'ozone-lead', 'aria-label': 'Attach mod files' }),
    input: { value: '', onChange: noop, onSend: noop, placeholder: placeholder || 'Message Randall...' },
  // React's server render puts a preload hint for a picture before the markup.
  })).replace(/^(<link rel="preload"[^>]*\/>)+/, '')
}
// The parts of the bar: what sits above the box (in its flow), the box, and what follows it.
const parts = html => {
  const form = html.indexOf('<form'), end = html.indexOf('</form>') + '</form>'.length
  return { above: html.slice(0, form), box: html.slice(form, end), below: html.slice(end) }
}
const controlsOf = box => box.slice(box.indexOf('<div class="ozone-composer-controls">'))

test('a new chat with nothing chosen: Randall and one line over the box, the box in the middle, the chips under it', () => {
  const html = bar()
  const { above, box, below } = parts(html)
  assert.match(html, /^<footer class="coach-inputarea is-start">/)
  assert.match(above, /<div class="randall-start-greeting"><span class="randall-start-sprite"><img data-sprite="randall" width="56"\/><\/span><p>What are we making today\?<\/p><\/div>$/)
  // One box: the textarea on top, then the control row inside it, send at its right.
  assert.match(box, /<div class="ozone-composer ozone-composer--stacked"><textarea rows="1" aria-label="Message Randall" placeholder="Message Randall\.\.\."/)
  assert.match(controlsOf(box), /^<div class="ozone-composer-controls"><div class="ozone-composer-tools"><button type="button" class="ozone-lead" aria-label="Attach mod files"><\/button><\/div><button type="submit" class="ozone-send"/)
  // Nothing chosen: no pill, no pick control; the starting points are the chips.
  assert.doesNotMatch(box, /randall-task-pill|randall-pick/)
  assert.match(below, /^<div class="randall-start-points"><div class="randall-start-group" role="group" aria-label="Characters">/)
  assert.equal(below.match(/<button type="button" class="randall-start-point"/g).length, 3)
  assert.equal(below.match(/Use MCP/g).length, 2)
  // No tiles, no boxed picker: nothing big anywhere.
  assert.doesNotMatch(html, /randall-task-tile|costume-picker|role="dialog"|randall-start-picked/)
})

test('a workflow chosen: no panel in the page; the pill and the pick control in the box; nothing above the box moves', () => {
  const before = parts(bar())
  for (const [task, choose, placeholder] of [
    ['recolor_part', 'Choose costume', 'Which costume, and what look?'],
    ['model_import', 'Choose fighter', 'Message Randall...'],
    ['recolor_stage', 'Choose stage', 'Message Randall...'],
  ]) {
    const html = bar({ task })
    const { above, box, below } = parts(html)
    assert.match(html, /^<footer class="coach-inputarea is-start">/, task)
    // The same in-flow rows over the box as with nothing chosen: the box stays where it was.
    assert.equal(above, before.above, task)
    assert.doesNotMatch(html, /costume-picker|role="dialog"|randall-start-picked|randall-task-tile/, task)
    // In the control row, in order: attach, the pill (its task, changeable), the pick control.
    const controls = controlsOf(box)
    const label = taskModes.labelFor(startable, task)
    const at = ['class="ozone-lead"', `aria-label="Chat task: ${label}. Change task"`, `<span>${choose}</span>`, 'class="ozone-send"'].map(piece => controls.indexOf(piece))
    assert.ok(at.every((index, i) => index > 0 && (i === 0 || index > at[i - 1])), `${task}: ${at}`)
    assert.match(controls, /class="randall-task-pill is-task"/)
    assert.match(box, new RegExp(`placeholder="${placeholder.replace(/[.?]/g, '\\$&')}"`))
    // The chips are still there under the box, faded out and inert.
    assert.match(below, /^<div class="randall-start-points is-away" inert="">/, task)
  }
  // A pick named in the box and in the placeholder.
  const picked = parts(bar({ task: 'recolor_part', pick: { kind: 'vault', character: 'Fox', id: 'fox-blue', name: 'Blue Hoodie', image: '/x.png' } }))
  assert.match(picked.box, /placeholder="What look do you want for Fox · Blue Hoodie\?"/)
  assert.match(picked.box, /<span>Fox · Blue Hoodie<\/span><\/button><button type="button" class="randall-pick-clear"/)
  assert.equal(picked.above, before.above)
})

test('after the first message: a normal chat bar at the bottom, the pill locked, no pick, no chips', () => {
  const html = bar({ task: 'recolor_part', locked: true })
  assert.match(html, /^<footer class="coach-inputarea">/)
  assert.doesNotMatch(html, /randall-start-greeting|randall-start-points|randall-pick|aria-haspopup="menu"/)
  assert.match(html, /aria-label="Chat task: Retexture a costume"/)
  assert.match(bar({ locked: true }), /aria-label="Chat task: Ask"/)
})

test('old chats stored under a task this build does not offer read as normal chats', () => {
  for (const old of ['find_mod', 'menu_background', 'stage_import', 'create_character']) {
    const html = bar({ task: old, locked: true })
    assert.match(html, /^<footer class="coach-inputarea">/, old)
    assert.doesNotMatch(html, /randall-task-pill|randall-pick|randall-start|Use MCP/, old)
    assert.match(html, /placeholder="Message Randall\.\.\."/, old)
  }
})

test('until status answers nothing sits under the box; a backend with no tasks offers its starters there', () => {
  assert.doesNotMatch(bar({ ready: false }), /randall-start-points/)
  const old = parts(bar({ tasks: [] }))
  assert.match(old.below, /<button type="button" class="randall-start-point"><span>Explain Nucleus features<\/span><\/button>/)
  assert.doesNotMatch(old.box, /randall-task-pill/)
})

test('AI Choice picked: the control and the placeholder say Randall picks the fighter', () => {
  const html = bar({ task: 'model_import', pick: { kind: 'fighter', auto: true, character: '', image: null } })
  assert.match(html, /<span>AI Choice<\/span>/)
  assert.match(html, /placeholder="Attach a model\. Randall picks the fighter\."/)
})

test('a linked non-member: the locked box offers joining for free and checking again, side by side', () => {
  const ChatUI = load('../chat/ChatUI.jsx', { './chatList': chatList, '../assistant/access': access, '../../shared/ui/Sprites': Sprites, '../../shared/audio/sounds': sounds })
  const lock = access.assistantAccess({ ready: true }, { linked: true, active: false, membership_class: 'none', reason: 'campaign_membership_required' })
  const html = renderToStaticMarkup(React.createElement(ChatUI.ChatInput, {
    value: '', onChange: noop, onSend: noop, disabled: true, sendDisabled: true, placeholder: lock.label,
    lockedAction: React.createElement(ChatUI.JoinFreeUnlock, { onJoin: noop, onCheck: noop }),
  }))
  assert.match(html, /class="chat-unlock-group"/)
  assert.match(html, />Join free on Patreon</)
  assert.match(html, />Check again</)
  assert.match(html, /placeholder="Join sc00p on Patreon for free \(not just Follow\), then press Check again\."/)
  assert.doesNotMatch(html, /ozone-send/, 'no send button while locked')
})
