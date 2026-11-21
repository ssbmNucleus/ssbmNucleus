import test from 'node:test'
import assert from 'node:assert/strict'
import { loadModule, hookHarness, deferred, flush } from '../../../../../tests/frontend/hookHarness.mjs'
import { isProjectChanged } from '../../shared/transport/projectGeneration.js'
import { selectionAfterMove } from './installedCostumeSelection.js'

function fixture() {
  const h = hookHarness(), timers = [], requests = [], alerts = [], refreshes = [], listeners = new Set()
  let generation = 3, costumes = ['a', 'b', 'c'], selection = new Set()
  const saves = loadModule(new URL('./orderSaves.js', import.meta.url), {})
  const { useCostumeReorder } = loadModule(new URL('./useCostumeReorder.js', import.meta.url), {
    react: h.react, '../../shared/audio/sounds': { playSound() {} },
    '../../shared/transport/api': { api: { post: (path, body, options) => {
      const reply = deferred()
      requests.push({ path, body, project: options?.headers?.['X-Nucleus-Project'] ?? String(generation), ...reply })
      return reply.promise
    } } },
    '../../shared/transport/projectGeneration': { isProjectChanged, getProjectGeneration: () => generation },
    '../../shared/ui/appDialogs': { appAlert: message => { alerts.push(message); return Promise.resolve() } },
    './installedCostumeSelection': { selectionAfterMove }, './orderSaves': saves,
  }, {
    document: { documentElement: { dataset: {} } },
    window: { addEventListener: (_name, fn) => listeners.add(fn), removeEventListener: (_name, fn) => listeners.delete(fn) },
    setTimeout: fn => { timers.push(fn); return timers.length },
    console: { error() {} },
  })
  const props = { selectedFighter: { name: 'Fox' },
    setMexCostumes: update => { costumes = update(costumes) },
    setSelectedInstalledCostumes: update => { selection = typeof update === 'function' ? update(selection) : update },
    setPairCostumes() {}, refreshMexCostumes: async fighter => refreshes.push(fighter), isVisibleFighter: () => true }
  const render = () => h.render(() => useCostumeReorder(props))
  const event = { preventDefault() {}, dataTransfer: {} }
  const drag = (from, to) => { render().handleDragStart(event, from); render().handleDrop(event, to); render() }
  return { render, drag, saves, requests, timers, alerts, refreshes, listeners, h, switchProject: () => { generation++ } }
}

test('one save slot covers a burst and every move queued while the first batch is saving', async () => {
  const f = fixture(); f.drag(0, 2); f.drag(1, 0)
  assert.equal(f.saves.orderSavesPending(), true); assert.equal(f.timers.length, 1)
  let settled = false
  const wait = f.saves.waitForOrderSaves().then(() => { settled = true })
  f.timers[0](); assert.equal(f.requests[0].body.moves.length, 2)
  f.drag(2, 0); f.timers[1]() // the single-flight guard leaves this move queued
  f.requests[0].resolve({}); await flush()
  assert.equal(f.requests.length, 2); assert.equal(settled, false)
  assert.equal(f.requests[1].body.moves.length, 1)
  f.requests[1].resolve({}); await flush(); await wait
  assert.equal(f.saves.orderSavesPending(), false)
  assert.equal(f.render().syncingOrder, false); assert.equal(f.render().pendingOrderMoves, 0)
  f.h.unmount(); assert.equal(f.listeners.size, 0)
})

test('project_changed drops unsent moves, alerts once, and releases Switch/Close waiters', async () => {
  const f = fixture(); f.drag(0, 2); f.timers[0](); f.drag(1, 0)
  const waiting = f.saves.waitForOrderSaves()
  f.requests[0].reject({ status: 409, data: { code: 'project_changed' } }); await flush(); await waiting
  f.timers[1](); await flush()
  assert.equal(f.requests.length, 1); assert.equal(f.alerts.length, 1)
  assert.match(f.alerts[0], /not saved.*another project/)
  assert.equal(f.saves.orderSavesPending(), false); assert.deepEqual(f.refreshes, [])
  f.h.unmount()
})

test('an ordinary save failure reconciles the visible fighter and still releases pending saves', async () => {
  const f = fixture(); f.drag(0, 1); f.timers[0]()
  f.requests[0].reject(new Error('save failed')); await flush()
  assert.deepEqual(f.refreshes, ['Fox']); assert.equal(f.saves.orderSavesPending(), false)
  assert.deepEqual(f.alerts, []); f.h.unmount()
})

test('a queued costume move keeps the project it was dragged in even if the panel unmounts before dispatch', async () => {
  const f = fixture(); f.drag(0, 2)
  f.h.unmount(); f.switchProject(); f.timers[0]()
  // api.js otherwise adds the now-current generation, allowing A's moves into B.
  const project = f.requests[0].project
  f.requests[0].resolve({}); await flush()
  assert.equal(project, '3')
  assert.equal(f.saves.orderSavesPending(), false)
})
