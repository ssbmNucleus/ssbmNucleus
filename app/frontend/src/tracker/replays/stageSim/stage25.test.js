import test from 'node:test'
import assert from 'node:assert/strict'
import simulate, { nextSeed, initialState, chooseProgram, spacing, stepScroll, sample, triggerContact, geometry } from './stage25.js'

test('LCG wrap and field spacing use game units', () => {
  assert.equal(nextSeed(0),2531011)
  assert.equal(nextSeed(0xffffffff),2316998)
  assert.ok(Math.abs(spacing(1,0)-277)<.0001)
})
test('scroll selection respects cooldown and ramps before holding speed', () => {
  const s=initialState(1,0),rng={int:()=>0}
  chooseProgram(s,rng)
  assert.equal(s.program,0)
  assert.equal(s.scrollCooldown[0],3)
  const before=s.fields[0].y
  stepScroll(s,rng,0)
  assert.ok(s.fields[0].y>before)
  for(let i=0;i<59;i++)stepScroll(s,rng,i+1)
  assert.equal(s.phase,0)
  assert.equal(s.speed,Math.fround(-.15))
  chooseProgram(s,rng)
  assert.equal(s.program,1)
})
test('DAT interpolation is independent of a captured match', () => {
  const keys=[[0,2,-170,null,600],[600,2,-50,null,150],[750,2,-50,null,0]]
  assert.equal(sample(keys,300),-110)
  assert.equal(sample(keys,700),-50)
})
test('contact trigger keeps a platform until frame 265 and restores it at 638', () => {
  const s=initialState(1,0)
  assert.equal(triggerContact(s,37,100),true)
  assert.equal(triggerContact(s,37,101),false)
  const has=idx=>geometry(s,idx).lines.some(l=>l[0]===553)
  assert.equal(has(364),true)
  assert.equal(has(365),false)
  assert.equal(has(738),true)
})
test('simulator refuses unavailable seeds and clipped prefixes', () => {
  assert.equal(simulate({meta:{n:2,start_frame:-123},frames:{}},0),null)
  assert.equal(simulate({meta:{n:2,start_frame:0},frames:{seed:[[1,2]]}},0),null)
})
test('field and animation checkpoints preserve arbitrary seek order', () => {
  const make=()=>({meta:{n:2000,start_frame:-123,start_seed:0},frames:{seed:[Array.from({length:2000},(_,i)=>nextSeed(i))]}})
  const b=make();assert.ok(simulate(b,1900))
  for(const idx of [0,84,1000,480,1600])assert.deepEqual(simulate(b,idx),simulate(make(),idx))
})
