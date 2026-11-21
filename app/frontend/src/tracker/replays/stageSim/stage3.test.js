import test from 'node:test'
import assert from 'node:assert/strict'
import simulate, { chooseForm, initialSchedule, stepSchedule, geometry, dynamicKind, wheelAngle } from './stage3.js'

test('form selection rejects the xE2 history value', () => {
  const draws=[0,0,2]; let used=0
  assert.equal(chooseForm(3,{int:()=>draws[used++]}),6)
  assert.equal(used,3)
})
test('history advances on neutral transitions as well as transformed ones', () => {
  const s=initialSchedule(-1),rng={int:()=>0}
  stepSchedule(s,rng,0)
  assert.deepEqual([s.previous,s.old,s.form],[-1,5,3])
  s.event=0;s.wait=-1;stepSchedule(s,rng,1)
  assert.deepEqual([s.previous,s.old,s.form],[5,3,5])
  s.event=0;s.wait=-1;stepSchedule(s,rng,2)
  assert.deepEqual([s.previous,s.old,s.form],[3,5,3])
})
test('warning, shrink, simultaneous grow, and completion use separate timers', () => {
  const s=initialSchedule(-1),rng={int:()=>0}
  for (let i=0;i<609;i++) stepSchedule(s,rng,i)
  assert.deepEqual(s.events.slice(0,7),[[0,1,3],[1,2,3],[2,3,3],[304,4,3],[485,5,3],[606,6,3],[607,0,3]])
})
test('both old and new MapLines exist throughout grow; neutral side walls toggle', () => {
  const ev=[[0,4,3],[181,5,3],[302,6,3],[303,0,3]]
  const ids = i => new Set(geometry(ev,i).lines.map(l=>l[0]))
  assert.equal(ids(180).has(85),false)
  for (const id of [0,34,85,111]) assert.equal(ids(240).has(id),true)
  assert.equal(ids(302).has(34),false)
  assert.equal(ids(302).has(0),true)
})
test('dynamic wheel classifies directed edges with the game slope thresholds', () => {
  assert.equal(dynamicKind(1,0),1)
  assert.equal(dynamicKind(-1,0),2)
  assert.equal(dynamicKind(0,1),8)
  assert.equal(dynamicKind(0,-1),4)
  assert.equal(dynamicKind(1,2),8)
  assert.equal(dynamicKind(-1,-1),4)
})
test('recorded events win even if seeds are absent or contradictory', () => {
  const b={meta:{n:700,start_frame:-123},frames:{seed:[Array(700).fill(0)]},stage_state:{stadium:[[0,0,3]]}}
  assert.equal(simulate(b,500).lines.some(l=>l[0]===0),true)
  assert.equal(simulate({...b,frames:{}},500).lines.some(l=>l[0]===0),true)
  assert.equal(simulate({meta:b.meta,frames:{}},5),null)
  assert.equal(geometry([[0,0,9]],5,false),null)
})
test('wheel phase preserves float32 accumulation through forward and backward seeks', () => {
  let expected=0
  for (let i=0;i<=1700;i++) expected=Math.fround(expected+Math.fround(-Math.PI/360))
  assert.equal(wheelAngle(1700),expected)
  assert.equal(wheelAngle(0),Math.fround(-Math.PI/360))
  assert.equal(wheelAngle(1700),expected)
})
test('schedule checkpoints preserve transition history through backward seeks', () => {
  const make=()=>({meta:{n:10000,start_frame:-123,start_seed:0},frames:{seed:[Array.from({length:10000},(_,i)=>(Math.imul(i,214013)+2531011)>>>0)]}})
  const b=make();assert.ok(simulate(b,9500))
  for(const idx of [4300,84,7000,0,8500])assert.deepEqual(simulate(b,idx),simulate(make(),idx))
})
