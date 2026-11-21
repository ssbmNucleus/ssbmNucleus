import test from 'node:test'
import assert from 'node:assert/strict'
import simulate, { nextSeed, previousSeed, random, initialPlatform, stepPlatform } from './stage2.js'

test('HSD LCG uses all 32 bits and inverse preserves zero', () => {
  assert.equal(nextSeed(0), 2531011)
  assert.equal(nextSeed(1), 2745024)
  for (const s of [0, 1, 0x13572468, 0x9abcdef0, 0xffffffff]) assert.equal(previousSeed(nextSeed(s)), s)
  assert.equal(random(1).int(6), 0)
})
test('dwell uses signed post-decrement, then moves on the next proc', () => {
  const p = initialPlatform(20, 0)
  const rng = { float: () => 0, int: () => 0 }
  stepPlatform(p, rng)
  assert.equal(p.state, 1)
  stepPlatform(p, rng)
  assert.equal(p.target, -1)
  assert.equal(p.height, 20)
  stepPlatform(p, rng)
  assert.equal(p.height, Math.fround(19.9))
})
test('submerged collision differs from recorded -1 fountain height', () => {
  const b = { meta: { n: 7, start_frame: -123 }, frames: {}, stage_state: {
    fod: [[1, 1, -1], [4, 1, -1], [5, 1, -.85]] } }
  const y = i => simulate(b,i).lines.find(l=>l[0]===0)[3]
  assert.equal(y(1), .375)
  assert.equal(y(2), -1.3125)
  assert.equal(y(4), .375)
  assert.ok(y(5) > y(4))
})
test('events are authoritative without seeds, and incomplete clipped events defer', () => {
  const b = { meta: { n: 5, start_frame: 100 }, frames: {}, stage_state: { fod: [[0,0,28],[0,1,20]] } }
  assert.equal(simulate(b,4).lines[0][3], 16.125)
  assert.equal(simulate({ ...b,stage_state:{fod:[[0,0,28]]}},0),null)
  assert.equal(simulate({ ...b,stage_state:{fod:[[0,0,28],[0,1,-1]]}},0),null)
  assert.equal(simulate({meta:{n:5,start_frame:-123},frames:{}},0),null)
})
test('checkpoint seeks agree with fresh replay from the full prefix', () => {
  const make = () => ({ meta:{n:2000,start_frame:-123,start_seed:0}, frames:{seed:[Array.from({length:2000},(_,i)=>nextSeed(i))]} })
  const b=make()
  assert.ok(simulate(b,1700))
  for (const i of [0,1001,239,480,1900,760]) assert.deepEqual(simulate(b,i),simulate(make(),i))
})
