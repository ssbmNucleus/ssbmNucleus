// The empty chat's starting-point chips, the composer's task pill and its menu, and
// "Start another", server-rendered; including chats stored under a task this build
// does not offer. The menu is rendered open by handing TaskPill's `open` state in.
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as taskModes from './taskModes.js'

const realRequire = createRequire(import.meta.url)
let queue = []
const hooked = { ...React, useState: (initial) => (queue.length ? [queue.shift(), () => {}] : React.useState(initial)) }
const code = transformSync(readFileSync(new URL('./TaskPicker.jsx', import.meta.url), 'utf8'), { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
const module = { exports: {} }
new Function('require', 'module', 'exports', code)(name => name === './taskModes' ? taskModes
  : name === 'react' ? hooked : realRequire(name), module, module.exports)
const { TaskPill, StartChips, StartAnother, groupTasks } = module.exports
const noop = () => {}
const html = (component, props, states = []) => {
  queue = [...states]
  try { return renderToStaticMarkup(React.createElement(component, props)) } finally { queue = [] }
}
// Every element in a tree (function components are not expanded).
const elements = node => !node || typeof node !== 'object' ? []
  : Array.isArray(node) ? node.flatMap(elements) : [node, ...elements(node.props?.children)]

// Five starting points in two groups: characters (costume, model import, a stub),
// then stages (stage retexture, a stub). A stub is shown but cannot be started.
const FIVE = [
  { id: 'recolor_part', label: 'Retexture a costume', group: 'Characters', hint: 'Pick a costume.', picker: 'costume', available: true },
  { id: 'model_import', label: 'Import a character model', group: 'Characters', hint: 'Turn a 3D model into a costume.', picker: 'fighter', available: true },
  { id: 'create_character', label: 'Create a character', group: 'Characters', hint: 'Use MCP (Settings > AI): build a whole new fighter, starting from a model.', picker: null, available: false },
  { id: 'recolor_stage', label: 'Retexture a stage', group: 'Stages', hint: 'Pick a stage.', picker: 'stage', available: true },
  { id: 'stage_import', label: 'Import a stage model', group: 'Stages', hint: 'Use MCP (Settings > AI): turn a 3D model into a playable stage.', picker: null, available: false },
]

test('the starting points are chips under Characters and Stages, each with its icon', () => {
  const chips = html(StartChips, { tasks: FIVE, onPick: noop })
  assert.match(chips, /^<div class="randall-start-points">/)
  assert.deepEqual([...chips.matchAll(/class="randall-start-group-label" aria-hidden="true">([^<]*)</g)].map(m => m[1]), ['Characters', 'Stages'])
  assert.equal(chips.match(/role="group" aria-label="Characters"/g).length, 1)
  assert.deepEqual([...chips.matchAll(/<\/svg><span>([^<]*)<\/span>/g)].map(m => m[1]),
    ['Retexture a costume', 'Import a character model', 'Create a character', 'Retexture a stage', 'Import a stage model'])
  assert.equal(chips.match(/class="randall-task-icon"/g).length, 5)
  // The groups hold 3 and 2 chips: Create a character is the last Characters chip.
  const [characters, stages] = chips.split('aria-label="Stages"')
  assert.match(characters, /Create a character/)
  assert.doesNotMatch(characters, /Retexture a stage/)
  assert.match(stages, /Retexture a stage.*Import a stage model/)
  // A brush for the costume, a cube for the model, a drop over a platform for the stage.
  assert.match(chips, /title="Pick a costume\."><svg[^>]*><path d="M18\.4[^"]*"/)
  assert.match(chips, /title="Turn a 3D model into a costume\."><svg[^>]*><path d="m12 2\.8[^"]*"/)
  assert.match(chips, /title="Pick a stage\."><svg[^>]*><path d="M12 2\.8s-3\.6[^"]*"/)
  // No tiles and no headings any more: nothing big.
  assert.doesNotMatch(chips, /randall-task-tile|<h\d|<small>/)
})

test('the stubs are plain "Use MCP" chips: nothing to press or tab to, every word there for a screen reader', () => {
  const chips = html(StartChips, { tasks: FIVE, onPick: noop })
  assert.equal(chips.match(/<button type="button" class="randall-start-point"/g).length, 3)
  const stubs = [...chips.matchAll(/<span class="randall-start-point is-unavailable"[^>]*>.*?Use MCP<\/span><\/span>/g)].map(m => m[0])
  assert.equal(stubs.length, 2)
  for (const stub of stubs) {
    assert.doesNotMatch(stub, /<button|tabindex|aria-hidden="true">Use MCP|onclick/i)
    assert.match(stub, /<span class="randall-task-soon">Use MCP<\/span>/)
  }
  assert.match(stubs[0], /title="Use MCP \(Settings &gt; AI\): build a whole new fighter, starting from a model\.">.*<span>Create a character<\/span>/)
  assert.match(stubs[1], /<span>Import a stage model<\/span>/)
  // Only the three real chips can be picked; the stubs have no handler at all.
  const picked = []
  const all = elements(StartChips({ tasks: FIVE, onPick: id => picked.push(id) })).filter(el => /^randall-start-point( |$)/.test(el.props?.className))
  assert.deepEqual(all.map(el => el.type), ['button', 'button', 'span', 'button', 'span'])
  for (const one of all) one.props.onClick?.()
  assert.deepEqual(picked, ['recolor_part', 'model_import', 'recolor_stage'])
})

test('with a workflow chosen the chips fade out and go inert, still mounted (nothing under the composer reflows)', () => {
  const away = html(StartChips, { tasks: FIVE, onPick: noop, away: true })
  assert.match(away, /^<div class="randall-start-points is-away" inert="">/)
  assert.doesNotMatch(html(StartChips, { tasks: FIVE, onPick: noop }), /inert/)
})

test('tasks without a group are one row with no label (a backend that predates groups)', () => {
  const flat = html(StartChips, { tasks: FIVE.map(({ group, ...task }) => task), onPick: noop })
  assert.doesNotMatch(flat, /randall-start-group-label|role="group"/)
  assert.equal(flat.match(/class="randall-start-row"/g).length, 1)
  assert.equal(flat.match(/class="randall-start-point( is-unavailable)?"/g).length, 5)
  assert.deepEqual(groupTasks(FIVE).map(group => [group.name, group.tasks.length]), [['Characters', 3], ['Stages', 2]])
})

test('the pill names the task with its icon; a chat stored under a retired task or a stub shows no pill', () => {
  for (const retired of ['find_mod', 'menu_background', 'stage_import', 'create_character']) {
    assert.equal(html(TaskPill, { tasks: FIVE, value: retired, locked: true, onChange: noop }), '', retired)
  }
  const locked = html(TaskPill, { tasks: FIVE, value: 'recolor_part', locked: true, onChange: noop })
  assert.match(locked, /aria-label="Chat task: Retexture a costume"/)
  assert.match(locked, /class="randall-task-pill is-task is-locked"/)
  assert.doesNotMatch(locked, /aria-haspopup|randall-task-pill-caret/)
  const open = html(TaskPill, { tasks: FIVE, value: 'recolor_stage', locked: false, onChange: noop })
  assert.match(open, /aria-haspopup="menu" aria-expanded="false"/)
  assert.match(open, /aria-label="Chat task: Retexture a stage\. Change task"/)
  assert.match(open, /<svg[^>]*class="randall-task-icon"><path d="M12 2\.8s-3\.6[^"]*"/)
  assert.match(open, /<span class="randall-task-pill-label">Retexture a stage<\/span>/)
  // A plain chat after its first message: "Ask", locked, no icon.
  assert.match(html(TaskPill, { tasks: FIVE, value: null, locked: true, onChange: noop }), /aria-label="Chat task: Ask"/)
  assert.equal(html(TaskPill, { tasks: [], value: null, locked: false, onChange: noop }), '')
})

test('the open menu: Ask, then each group with its starting points, the stubs disabled and marked "Use MCP"', () => {
  // useState: open.
  const menu = html(TaskPill, { tasks: FIVE, value: 'recolor_part', locked: false, onChange: noop }, [true])
  assert.match(menu, /aria-expanded="true" aria-controls="([^"]+)"[\s\S]*role="menu" aria-label="Chat task"/)
  const options = [...menu.matchAll(/role="menuitemradio"[^>]*>.*?<span class="randall-task-option-label">([^<]*)<\/span>/g)].map(m => m[1])
  assert.deepEqual(options, ['Ask', 'Retexture a costume', 'Import a character model', 'Create a character', 'Retexture a stage', 'Import a stage model'])
  assert.deepEqual([...menu.matchAll(/class="randall-task-menu-group" role="group" aria-label="([^"]*)"/g)].map(m => m[1]), ['Characters', 'Stages'])
  assert.match(menu, /aria-checked="true"[^>]*>.*?Retexture a costume/)
  const stubs = [...menu.matchAll(/<button[^>]*class="randall-task-option is-unavailable"[^>]*>.*?<\/button>/g)].map(m => m[0])
  assert.equal(stubs.length, 2)
  for (const stub of stubs) {
    assert.match(stub, /aria-disabled="true"/)
    assert.match(stub, /<span class="randall-task-soon">Use MCP<\/span>/)
  }
})

test('picking from the menu: Ask clears the task, a starting point sets it, a stub does nothing', () => {
  const React_ = { useState: () => [true, noop], useRef: () => ({ current: null }), useEffect: noop, useId: () => 'menu' }
  const loaded = { exports: {} }
  new Function('require', 'module', 'exports', code)(name => name === './taskModes' ? taskModes
    : name === 'react' ? React_ : realRequire(name), loaded, loaded.exports)
  const chosen = []
  const tree = loaded.exports.TaskPill({ tasks: FIVE, value: 'recolor_part', locked: false, onChange: id => chosen.push(id) })
  const items = elements(tree).filter(el => el.props?.role === 'menuitemradio')
  assert.equal(items.length, 6)
  for (const item of items) item.props.onClick?.()
  assert.deepEqual(chosen, [null, 'recolor_part', 'model_import', 'recolor_stage'])
  assert.deepEqual(items.filter(item => !item.props.onClick).map(item => item.key), ['create_character', 'stage_import'])
})

test('"Start another" offers only what can be started, as small chips', () => {
  const again = html(StartAnother, { tasks: FIVE, onPick: noop })
  assert.doesNotMatch(again, /Import a stage model|Create a character|Use MCP|randall-task-icon|<small>/)
  assert.equal(again.match(/class="randall-task-tile"/g).length, 3)
  assert.match(again, /<div class="randall-task-tiles randall-task-tiles--compact"><button type="button" class="randall-task-tile" title="Pick a costume\."><strong>Retexture a costume<\/strong><\/button>/)
  const picked = []
  for (const tile of elements(StartAnother({ tasks: FIVE, onPick: id => picked.push(id) })).filter(el => el.props?.className === 'randall-task-tile')) tile.props.onClick()
  assert.deepEqual(picked, ['recolor_part', 'model_import', 'recolor_stage'])
})
