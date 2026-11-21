import test from 'node:test'
import assert from 'node:assert/strict'
import simulate, { nextSeed, ANIMATIONS, nextVariation, initialState, stepState } from './stage27.js'

test('LCG retains unsigned wraparound', () => {
  assert.equal(nextSeed(1),2745024)
  assert.equal(nextSeed(0xffffffff),2316998)
})
test('layout rejects invalid and repeated variants without modulo remapping', () => {
  const draws=[3,0,1];let used=0
  assert.equal(nextVariation(0,1,{int:()=>draws[used++]}),2)
  assert.equal(used,3)
  assert.deepEqual(ANIMATIONS[4],[18,-1,-1,-1,-1])
})
test('tool event switches to a whole layout and lasts exactly 1200 procs', () => {
  const s=initialState(1,999),rng={int:n=>n===8?7:0}
  stepState(s,rng)
  assert.equal(s.animation,21)
  assert.equal(s.variation,0)
  assert.equal(s.tools,1199)
  for(let i=0;i<1199;i++)stepState(s,rng)
  assert.equal(s.tools,0)
  assert.equal(s.running,true)
})
test('random seeking does not depend on the previous paint call', () => {
  const make=()=>({meta:{n:1600,start_frame:-123,start_seed:0},frames:{seed:[Array.from({length:1600},(_,i)=>nextSeed(i))]}})
  const b=make();assert.ok(simulate(b,1500))
  for(const idx of [83,84,1000,0,500]) assert.deepEqual(simulate(b,idx),simulate(make(),idx))
  assert.equal(simulate({meta:b.meta,frames:{}},4),null)
  assert.equal(simulate({...make(),meta:{n:1600,start_frame:0}},4),null)
})
