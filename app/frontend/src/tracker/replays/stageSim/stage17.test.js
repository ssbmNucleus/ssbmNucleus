import test from 'node:test'
import assert from 'node:assert/strict'
import simulate, {INITIAL_HEIGHTS,chooseColumn,fallingStep,blockHistory} from './stage17.js'

test('initial grid weighting excludes an entire side when one column is full', () => {
  assert.equal(chooseColumn(INITIAL_HEIGHTS,{int:()=>30}),4)
  assert.equal(chooseColumn([5,3,2,2,3,4],{int:()=>0}),3)
  assert.equal(chooseColumn([4,3,2,2,3,5],{int:()=>0}),0)
  assert.equal(chooseColumn([5,3,2,2,3,5],{int:()=>{throw Error('must not draw')}}),-1)
})

test('fall acceleration is float32, terminal speed is capped, and settlement is strict', () => {
  const a = fallingStep({y:147.75,speed:0,settled:false},11.25)
  assert.equal(a.y,Math.fround(147.73))
  assert.equal(fallingStep({y:100,speed:5,settled:false},0).speed,5)
  const settled = fallingStep({y:1,speed:1,settled:false},0)
  assert.equal(settled.y,0)
  assert.equal(settled.settled,true)
  assert.deepEqual(fallingStep(settled,0),settled)
})

test('unsupported replay prefixes do not get a fabricated initial grid', () => {
  assert.equal(simulate({meta:{stage:17,start_frame:0,n:1},frames:{seed:[[0]]}},0),null)
  assert.equal(simulate({meta:{stage:17,start_frame:-123,n:1},frames:{}},0),null)
})

test('Green Greens includes follower attacks in its damage guard without rejecting Ice Climbers',()=>{
  const n=200,a=v=>Array(n).fill(v),entity={x:a(0),y:a(15),state:a(14),air:a(0),age:a(0),cid:a(10),seed_order:a(1),seed:a(0)}
  const make=()=>({meta:{stage:17,start_frame:-123,n,start_seed:0},frames:{seed:[a(0)],...Object.fromEntries(Object.entries(entity).map(([k,v])=>[k,[v.slice()]]))}})
  for(let cid=0;cid<27;cid++){const b=make();b.frames.cid=[a(cid)];assert.ok(simulate(b,100),`cid ${cid}`)}
  const b=make();b.frames.fol=[{of:0,...structuredClone(entity),cid:a(11),seed_order:a(2)}]
  assert.ok(simulate(b,100))
  for(const state of [44,187,195,217,256,257,341]){
    const hit=structuredClone(b);hit.frames.fol[0].x[101]=50;hit.frames.fol[0].state[101]=state
    assert.ok(simulate(hit,101));assert.equal(simulate(hit,102),null)
  }
})

function idleBundle(n=600) {
  const a=v=>Array(n).fill(v)
  return {meta:{stage:17,start_frame:-123,n,start_seed:0},frames:{
    x:[a(0)],y:[a(26.25)],state:[a(14)],age:[a(0)],air:[a(0)],cid:[a(18)],dir:[a(1)],seed:[a(0)],seed_order:[a(1)],
  }}
}

test('a witnessed normal block hit removes all four lines on the following ground pass',()=>{
  const b=idleBundle(),before=simulate(b,100)
  b.items=[{t:160,f:100,x:[-48.75],y:[-11.25],s:[0],d:[1]}]
  const same=simulate(structuredClone(b),100),after=simulate(structuredClone(b),101)
  assert.deepEqual(same,before)
  for(const id of [2,49,82,121])assert.equal(after.lines.some(l=>l[0]===id),false)
  assert.equal(before.lines.length-after.lines.length,4)
})

test('normal destruction permits later first-free collision-slot reuse without collapsing settled neighbors',()=>{
  const b=idleBundle()
  b.items=[{t:160,f:100,x:[-48.75],y:[-11.25],s:[0],d:[1]}]
  const c=blockHistory(b)
  assert.ok(!c.rows[101].some(([id])=>id===2))
  assert.ok(c.rows.slice(102).some(row=>row.some(([id])=>id===2)))
  assert.ok(c.rows[101].some(([id,,y])=>id===8&&y===-3.75))
  assert.deepEqual(simulate(b,300),simulate(structuredClone(b),300))
})

test('unrecorded Ice Climbers articles cannot silently bypass the oldest-15 item guard',()=>{
  const b=idleBundle(),n=b.meta.n,a=v=>Array(n).fill(v)
  b.frames.fol=[{of:0,x:a(0),y:a(26.25),state:a(14),age:a(0),air:a(0),cid:a(11),dir:a(1),seed:a(0),seed_order:a(2)}]
  b.frames.fol[0].state[100]=341
  assert.ok(simulate(b,100));assert.equal(simulate(b,101),null)
})

test('a common item pickup proves an omitted article behind the oldest-15 materials',()=>{
  const b=idleBundle()
  b.frames.state[0][100]=94
  assert.ok(simulate(b,100))
  assert.equal(simulate(b,101),null)
})
