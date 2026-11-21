import test from 'node:test'
import assert from 'node:assert/strict'
import simulate,{initialCloud,cloudStep,floorContact} from './stage29.js'

test('Old Yoshi continuous load threshold resets when the fighter leaves',()=>{
  let s=initialCloud()
  for(let i=0;i<121;i++)s=cloudStep(s,true)
  assert.equal(s.state,0)
  assert.equal(s.sag,6)
  assert.equal(cloudStep(s,false).timer,0)
  s=cloudStep(s,true)
  assert.equal(s.state,1)
  for(let i=0;i<30;i++)s=cloudStep(s,false)
  assert.equal(s.active,true)
  s=cloudStep(s,false)
  assert.equal(s.active,false)
  while(s.state===1)s=cloudStep(s,false)
  for(let i=0;i<181;i++)s=cloudStep(s,false)
  assert.equal(s.state,2)
  s=cloudStep(s,false)
  assert.equal(s.state,3)
  for(let i=0;i<30;i++)s=cloudStep(s,false)
  assert.equal(s.active,false)
  assert.equal(cloudStep(s,false).active,true)
})

test('Old Yoshi uses floor contact, not nearby airborne position or fighter weight',()=>{
  const frames={x:[[115]],y:[[54]],state:[[14]],air:[[0]]},line=[1,1,92,54,138,54]
  assert.equal(floorContact(frames,0,0,line),true)
  assert.equal(floorContact({...frames,air:[[1]]},0,0,line),false)
  assert.equal(floorContact({...frames,y:[[55]]},0,0,line),false)
  assert.equal(floorContact(frames,0,-1,line),false)
})

test('Old Yoshi request-only animations evaluate frame zero before advancing',()=>{
  let s={...initialCloud(),state:1,sag:6}
  // The authored vanish clip ends at 99, after samples 0 through 99.
  for(let i=0;i<99;i++)s=cloudStep(s,false)
  assert.equal(s.state,1)
  s=cloudStep(s,false)
  assert.equal(s.state,2)
  for(let i=0;i<182;i++)s=cloudStep(s,false)
  assert.equal(s.state,3)
  for(let i=0;i<100;i++)s=cloudStep(s,false)
  assert.equal(s.state,3)
  assert.equal(s.sag,6)
  s=cloudStep(s,false)
  assert.equal(s.state,0)
  assert.equal(s.sag,6)
  assert.ok(cloudStep(s,false).sag<6)
})

test('Old Yoshi seeking is deterministic and returned line edits cannot poison the cache',()=>{
  const n=10,frames={}
  for(const [key,value] of Object.entries({x:0,y:-13,air:0,state:14,age:0,cid:18}))frames[key]=[Array(n).fill(value)]
  const b={meta:{stage:29,start_frame:-123,n},frames}
  const start=simulate(b,0)
  simulate(b,9)
  assert.deepEqual(simulate(b,0),start)
  start.lines[0][2]=999
  assert.notEqual(simulate(b,0).lines[0][2],999)
  assert.equal(simulate({...b,meta:{...b.meta,start_frame:0}},0),null)
  assert.equal(simulate(b,.5),null)
  assert.equal(simulate(b,n),null)
})
