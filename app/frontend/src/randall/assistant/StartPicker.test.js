// The starting pick in the composer's control row (StartPickControl): "Choose costume"
// (fighter, stage), the pick's chip with ×, and the picker in a popover anchored to
// the composer. Server-rendered for the markup (the popover rendered open by handing
// the control its `open` state); the handlers are called on the element tree with a
// stand-in React (no DOM here), for the keys, the pick, clearing and closing.
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'
import * as costumePicks from '../../vault/picker/costumePicks.js'
import * as stagePicks from '../../vault/picker/stagePicks.js'
import * as startPick from './startPick.js'
import * as pickPopover from './pickPopover.js'

const realRequire = createRequire(import.meta.url)
const SKIP = Symbol('skip')
let queue = []
const hooked = { ...React, useState: (initial) => {
  if (queue.length) { const next = queue.shift(); if (next !== SKIP) return [next, () => {}] }
  return React.useState(initial)
} }
const noop = () => {}
const compiled = new Map()
function load(url, stubs, react = hooked) {
  const key = url.href
  if (!compiled.has(key)) compiled.set(key, transformSync(readFileSync(url, 'utf8'), { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code)
  const module = { exports: {} }
  new Function('require', 'module', 'exports', compiled.get(key))(name => {
    if (name === 'react') return react
    if (name in stubs) return stubs[name]
    if (name.endsWith('.css')) return {}
    return realRequire(name)
  }, module, module.exports)
  return module.exports
}
const sounds = { playSound: noop, playHoverSound: noop }
const config = { backendMediaUrl: path => `http://backend${path}` }
const pending = { api: { get: () => new Promise(noop) } }
const GalleryGrid = load(new URL('../../shared/ui/GalleryGrid.jsx', import.meta.url), { '../audio/sounds': sounds })
const pickerStubs = { '../../shared/ui/GalleryGrid': GalleryGrid, '../../shared/transport/api': pending,
  '../../shared/config/config': config, '../../shared/audio/sounds': sounds, './costumePicks': costumePicks, './stagePicks': stagePicks }
const CostumePicker = load(new URL('../../vault/picker/CostumePicker.jsx', import.meta.url), pickerStubs)
const StagePicker = load(new URL('../../vault/picker/StagePicker.jsx', import.meta.url), pickerStubs)
const controlStubs = { '../../vault/picker/CostumePicker': CostumePicker, '../../vault/picker/StagePicker': StagePicker,
  './startPick': startPick, './pickPopover': pickPopover, '../../shared/config/config': config }
const { StartPickControl } = load(new URL('./StartPicker.jsx', import.meta.url), controlStubs)

const VAULT = { kind: 'vault', character: 'Fox', id: 'fox-blue', name: 'Blue Hoodie', image: '/storage/Fox/fox-blue_csp.png' }
const FIGHTER = { kind: 'fighter', character: 'Marth', image: '/vanilla/Marth/css_icon.png' }
const NIGHT = { kind: 'stage', stage: 'GrNBa', stageName: 'Battlefield', id: 'night-sky-1a2b', name: 'Night Sky',
  image: '/storage/das/battlefield/night-sky-1a2b_screenshot.png' }
const STAGES = [{ code: 'GrNBa', name: 'Battlefield', folder: 'battlefield', legal: true, art: '/vanilla/stages/battlefield.png' }]
const APP = { page: 'storage', character: 'Fox', stage: null }
const render = (props, states = []) => {
  queue = [...states]
  try { return renderToStaticMarkup(React.createElement(StartPickControl, { onPick: noop, onClear: noop, ...props })) }
  finally { queue = [] }
}

test('no picker (a task without one, a plain chat, a sent chat): nothing', () => {
  assert.equal(render({ picker: null }), '')
})

test('nothing picked: a "Choose costume" button that opens a dialog; no popover until it is pressed', () => {
  const html = render({ picker: 'costume' })
  assert.match(html, /^<div class="randall-pick"><div class="randall-pick-chip"><button type="button" class="randall-pick-open" aria-haspopup="dialog" aria-expanded="false" title="Pick the costume to start from \(optional\)">/)
  assert.match(html, /<span>Choose costume<\/span><\/button><\/div><\/div>$/)
  assert.doesNotMatch(html, /role="dialog"|costume-picker|randall-pick-clear/)
  assert.match(render({ picker: 'fighter' }), /<span>Choose fighter<\/span>/)
  assert.match(render({ picker: 'stage' }), /<span>Choose stage<\/span>/)
})

test('a pick: its thumbnail and name, a button to change it and × to clear it', () => {
  const html = render({ picker: 'costume', pick: VAULT })
  assert.match(html, /class="randall-pick-chip is-picked"/)
  assert.match(html, /aria-label="Costume: Fox · Blue Hoodie\. Change" title="Change the costume">/)
  assert.match(html, /<img src="http:\/\/backend\/storage\/Fox\/fox-blue_csp\.png" alt="" class="randall-pick-thumb randall-pick-thumb--vault"\/><span>Fox · Blue Hoodie<\/span>/)
  assert.match(html, /<button type="button" class="randall-pick-clear" aria-label="Clear the costume" title="Clear the costume">/)
  assert.match(render({ picker: 'fighter', pick: FIGHTER }), /aria-label="Fighter: Marth\. Change"[^>]*><img [^>]*randall-pick-thumb--fighter"\/><span>Marth<\/span>/)
  assert.match(render({ picker: 'stage', pick: NIGHT }), /aria-label="Stage: Battlefield · Night Sky\. Change"[^>]*><img [^>]*randall-pick-thumb--stage"\/><span>Battlefield · Night Sky<\/span>/)
})

test('open: the picker in a dialog anchored to the composer, its search first, the grid a listbox', () => {
  // useState: open, place.
  const html = render({ picker: 'costume', metadata: { characters: {} } }, [true, { up: false, maxHeight: 312 }])
  const [, controls] = html.match(/aria-expanded="true" aria-controls="([^"]+)"/)
  assert.match(html, new RegExp(`<div id="${controls}" role="dialog" aria-label="Choose a costume" class="randall-pick-popover is-down" style="max-height:312px">`))
  assert.match(html, /role="dialog"[^>]*><div class="costume-picker costume-picker--fighters"><div class="costume-picker-head"><strong>Pick a fighter<\/strong><\/div><input type="search" class="gallery-search" aria-label="Search fighters"/)
  assert.match(html, /role="listbox" aria-label="Fighters"/)
  assert.equal(html.match(/class="gallery-cell[^"]*"/g).length, 26)
  // No boxed panel in the page: the dialog is the control's own popover.
  assert.doesNotMatch(html, /randall-start-picked|randall-start-change/)
  const up = render({ picker: 'stage', stages: STAGES }, [true, { up: true, maxHeight: 400 }])
  assert.match(up, /role="dialog" aria-label="Choose a stage" class="randall-pick-popover is-up" style="max-height:400px"><div class="costume-picker costume-picker--stages">/)
  assert.match(render({ picker: 'fighter', fighters: ['Fox', 'Marth'] }, [true, SKIP]), /class="randall-pick-popover is-up"><div class="costume-picker costume-picker--fighters"><div class="costume-picker-head"><strong>Which fighter does it go on\?<\/strong>/)
})

// The control called directly, with a stand-in React that hands out its state and
// refs and records what it sets. Refs, in order: the wrapper, the button, the dialog.
const source = transformSync(readFileSync(new URL('./StartPicker.jsx', import.meta.url), 'utf8'), { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
const spy = () => { const fn = (...args) => { fn.calls.push(args) }; fn.calls = []; return fn }
function control(props, { open = false, inside: more = [] } = {}) {
  const sets = []
  const inside = new Set(['search', 'cell', ...more])
  const button = { focus: spy() }, firstCell = { click: spy() }
  const refs = [
    { current: { contains: node => node === 'button' || inside.has(node) } },
    { current: button },
    { current: { contains: node => inside.has(node), querySelector: selector => (selector === '.gallery-cell' ? firstCell : null) } },
  ]
  const stand = { useState: initial => { const calls = []; sets.push(calls); return [sets.length === 1 ? open : initial, value => calls.push(value)] },
    useRef: () => refs.shift(), useEffect: noop, useLayoutEffect: noop, useId: () => 'pick-dialog' }
  const module = { exports: {} }
  new Function('require', 'module', 'exports', source)(name => name === 'react' ? stand : name in controlStubs ? controlStubs[name] : realRequire(name), module, module.exports)
  const tree = module.exports.StartPickControl({ onPick: noop, onClear: noop, ...props })
  return { tree, opened: sets[0], button, firstCell }
}
const elements = node => !node || typeof node !== 'object' ? []
  : Array.isArray(node) ? node.flatMap(elements) : [node, ...elements(node.props?.children)]
const find = (tree, test) => elements(tree).find(test)
const key = (key, target, extra = {}) => ({ key, target, preventDefault: spy(), stopPropagation: spy(), ...extra })
// The picker's search box, as the wrapper sees the event target.
const searchBox = value => ({ value, matches: selector => selector === 'input.gallery-search' })

test('keyboard: arrows or Enter open it; Escape closes it and puts focus back on the control', () => {
  const closed = control({ picker: 'costume' })
  const down = key('ArrowDown', 'button')
  closed.tree.props.onKeyDown(down)
  assert.deepEqual(closed.opened, [true])
  assert.equal(down.preventDefault.calls.length, 1)
  // Enter and Space are the button's own click, which toggles.
  find(closed.tree, el => el.props?.className === 'randall-pick-open').props.onClick()
  assert.equal(closed.opened[1](false), true)
  const open = control({ picker: 'costume' }, { open: true })
  const escape = key('Escape', 'button')
  open.tree.props.onKeyDown(escape)
  assert.deepEqual(open.opened, [false])
  assert.equal(open.button.focus.calls.length, 1)
  assert.equal(escape.stopPropagation.calls.length, 1, 'Escape stops here: it does not also close the history sidebar')
  // Escape that the picker left alone (nothing to step back from) closes it too.
  const inDialog = control({ picker: 'costume' }, { open: true })
  inDialog.tree.props.onKeyDown(key('Escape', 'cell'))
  assert.deepEqual(inDialog.opened, [false])
  assert.equal(inDialog.button.focus.calls.length, 1)
})

test('Enter in the popover’s search picks the first match, and an empty search never submits the message', () => {
  const box = searchBox('fox')
  const typed = control({ picker: 'costume' }, { open: true, inside: [box] })
  const enter = key('Enter', box)
  typed.tree.props.onKeyDown(enter)
  assert.equal(typed.firstCell.click.calls.length, 1)
  assert.equal(enter.preventDefault.calls.length, 1)
  // An empty search: Enter does nothing at all, and above all does not send the
  // message (the popover sits inside the message form).
  const empty = searchBox('  ')
  const blank = control({ picker: 'costume' }, { open: true, inside: [empty] })
  const hold = key('Enter', empty)
  blank.tree.props.onKeyDown(hold)
  assert.equal(hold.preventDefault.calls.length, 1)
  assert.equal(blank.firstCell.click.calls.length, 0)
  assert.deepEqual(blank.opened, [])
  // Enter on a cell is the cell's own click: the wrapper leaves it alone.
  const onCell = key('Enter', 'cell')
  blank.tree.props.onKeyDown(onCell)
  assert.equal(onCell.preventDefault.calls.length, 0)
  // The same search box outside an open dialog is not the popover's: no pick.
  const elsewhere = control({ picker: 'costume' }, { open: true })
  elsewhere.tree.props.onKeyDown(key('Enter', searchBox('fox')))
  assert.equal(elsewhere.firstCell.click.calls.length, 0)
})

test('picking in the popover closes it and hands the pick over; the outgoing context is exactly what a pick sent before', () => {
  for (const [picker, picked, Picker, expected] of [
    ['costume', VAULT, CostumePicker.default,
      '{"page":"storage","character":"Fox","stage":null,"selection":[{"id":"fox-blue","character":"Fox","name":"Blue Hoodie"}],"files":[],"task":"recolor_part"}'],
    ['stage', NIGHT, StagePicker.default,
      '{"page":"storage","character":"Fox","stage":null,"selection":[{"kind":"stage","stage":"GrNBa","id":"night-sky-1a2b","name":"Battlefield · Night Sky"}],"files":[],"task":"recolor_stage"}'],
    ['fighter', FIGHTER, CostumePicker.default,
      '{"page":"storage","character":"Fox","stage":null,"selection":[],"files":[],"task":"model_import","fighter":"Marth"}'],
  ]) {
    const handed = []
    const { tree, opened } = control({ picker, onPick: pick => handed.push(pick) }, { open: true })
    const inner = find(tree, el => el.type === Picker)
    assert.ok(inner, picker)
    if (picker === 'fighter') assert.equal(inner.props.mode, 'fighter')
    assert.equal(inner.props.autoFocus, true, 'the picker focuses its search when it opens')
    inner.props.onChange(picked)
    assert.deepEqual(opened, [false])
    assert.deepEqual(handed, [picked])
    // The panel keeps the pick as it came (choosePick) and sends it through startPick.outgoingContext.
    const task = { costume: 'recolor_part', stage: 'recolor_stage', fighter: 'model_import' }[picker]
    const attached = [{ id: 'x', character: 'Falco', name: 'X' }]
    const sent = startPick.outgoingContext({ context: APP, selection: picker === 'fighter' ? [] : attached, task, picker, pick: handed[0] })
    assert.equal(JSON.stringify(sent), expected, picker)
    // And the control now shows it.
    assert.match(render({ picker, pick: handed[0] }), new RegExp(`<span>${startPick.pickText(picked)}</span>`))
  }
})

test('clearing the pick, or cancelling the picker, puts focus back on the control', () => {
  const cleared = []
  const picked = control({ picker: 'costume', pick: VAULT, onClear: () => cleared.push(true) }, { open: true })
  find(picked.tree, el => el.props?.className === 'randall-pick-clear').props.onClick()
  assert.deepEqual(cleared, [true])
  assert.deepEqual(picked.opened, [false])
  assert.equal(picked.button.focus.calls.length, 1)
  const cancelled = control({ picker: 'stage', stages: STAGES }, { open: true })
  find(cancelled.tree, el => el.type === StagePicker.default).props.onCancel()
  assert.deepEqual(cancelled.opened, [false])
  assert.equal(cancelled.button.focus.calls.length, 1)
})

test('focus moving out closes it; a picker step swapping its cells (no new target) does not', () => {
  const { tree, opened } = control({ picker: 'costume' }, { open: true })
  tree.props.onBlur({ relatedTarget: null })
  tree.props.onBlur({ relatedTarget: 'search' })
  assert.deepEqual(opened, [])
  tree.props.onBlur({ relatedTarget: 'the message box' })
  assert.deepEqual(opened, [false])
})

test('AI Choice: the control shows the "?" tile and "AI Choice", × clears back to "Choose fighter"', () => {
  const ai = { kind: 'fighter', auto: true, character: '', image: null }
  const html = render({ picker: 'fighter', pick: ai })
  assert.match(html, /aria-label="Fighter: AI Choice\. Change"[^>]*><span class="randall-pick-thumb randall-pick-thumb--fighter randall-pick-thumb--glyph" aria-hidden="true">\?<\/span><span>AI Choice<\/span>/)
  assert.match(html, /randall-pick-clear" aria-label="Clear the fighter"/)
  assert.match(render({ picker: 'fighter', pick: null }), /<span>Choose fighter<\/span>/)
})
