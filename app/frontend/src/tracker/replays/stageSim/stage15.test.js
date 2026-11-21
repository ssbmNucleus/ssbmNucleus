import test from 'node:test'
import assert from 'node:assert/strict'
import simulate, { stepSeed, previousSeed, initialState, advance, lineKind } from './stage15.js'

test('HSD global LCG steps, unsigned wrap and inverse', () => {
  assert.equal(stepSeed(0), 2531011)
  for (const seed of [0, 1, 0xffffffff, 0x13572468, 0x9abcdef0]) assert.equal(previousSeed(stepSeed(seed)), seed)
})

test('Kraid hit arms rotation before the duration draw and first movement', () => {
  const s = { ...initialState(0), state: 3, animation: 5, timer: 158, age: 158 }
  const hit = advance(s, 0)
  assert.equal(hit.hit, -1)
  assert.equal(hit.angle, 0)
  const armed = advance(hit, 0)
  assert.equal(armed.duration, 150)
  assert.equal(armed.angle, 0)
  const moving = advance(armed, 0)
  assert.ok(moving.angle < 0)
  assert.equal(moving.duration, 149)
  assert.equal(s.hit, 0)
})

test('deceleration settles without overshooting through zero', () => {
  const s = { ...initialState(0), rotating: true, duration: 0, hit: 1, speed: .001, deceleration: .001, angle: .3, timer: 10 }
  const end = advance(s, 0)
  assert.equal(end.rotating, false)
  assert.equal(end.hit, 0)
  assert.equal(end.angle, .3)
})

test('dynamic collision kinds use Melee asymmetric slope thresholds', () => {
  assert.equal(lineKind(0, 0, 1, 1), 1)
  assert.equal(lineKind(1, 1, 0, 0), 4)
  assert.equal(lineKind(0, 0, 0, 1), 8)
  assert.equal(lineKind(0, 0, 0, -1), 4)
  assert.equal(lineKind(1, 0, 0, 0), 2)
})

test('missing prefix/seed is unavailable; checkpoints support backward seeks', () => {
  assert.equal(simulate({ meta: { stage: 15, start_frame: -123, players: [{char:9}] }, frames: {} }, 0), null)
  const seeds=Array.from({length:1800},(_,i)=>i?stepSeed(i):0)
  const b={meta:{stage:15,start_frame:-123,start_seed:0,n:1800,players:[{char:9}]},frames:{seed:[seeds]}}
  assert.ok(simulate(b,1500))
  assert.deepEqual(simulate(b,400),simulate(structuredClone(b),400))
  assert.equal(simulate({...b,meta:{...b.meta,start_frame:0}},0),null)
  assert.ok(simulate({...b,meta:{...b.meta,players:[{char:2}]}},0))
  assert.equal(simulate({...b,meta:{...b.meta,start_seed:null}},0),null)
})
