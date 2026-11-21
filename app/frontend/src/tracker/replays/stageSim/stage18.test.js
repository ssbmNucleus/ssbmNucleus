import test from 'node:test'
import assert from 'node:assert/strict'
import simulate, {initialCrane,craneStep,ufoCheckpoints,initialHelicopter,helicopterStep,helicopterBlocksUfo,touchesCenter} from './stage18.js'
import {rngStep} from './stage13.js'

test('crane wait and animation request preserve the current pose until the next tick', () => {
  let s = initialCrane(0)
  const noRandom = () => { throw Error('not a random transition') }
  s = craneStep(s,noRandom)
  assert.equal(s.state,1)
  assert.equal(s.phase,0)
  s = craneStep(s,noRandom)
  assert.equal(s.phase,0)
  for (let i=0;i<300;i++) s = craneStep(s,noRandom)
  assert.equal(s.state,3)
  assert.equal(s.phase,300)
  let draws=0
  s = craneStep(s,n=>{draws++;assert.equal(n,300);return 7})
  assert.equal(draws,1)
  assert.equal(s.timer,607)
})

test('return travel keeps frame 300 on the request tick, then applies frame 400', () => {
  let s = {...initialCrane(0),side:1,phase:300}
  s = craneStep(s,()=>0)
  assert.equal(s.phase,300)
  s = craneStep(s,()=>0)
  assert.equal(s.phase,400)
})

test('crane bounce doubles acceleration on target crossings and settles exactly', () => {
  let s = {...initialCrane(0),state:7,y:0,target:0,speed:.2,amplitude:.2,accel:-.08}
  for (let i=0;i<100 && s.state===7;i++) s = craneStep(s,()=>0)
  assert.equal(s.state,0)
  assert.equal(s.y,0)
  assert.equal(s.timer,900)
})

test('Fourside refuses missing seeds instead of making an independent RNG stream', () => {
  assert.equal(simulate({meta:{stage:18,start_frame:-123,n:1},frames:{}},0),null)
})

test('UFO history requires the helicopter GameStart anchor, never a future seed fit', () => {
  const n = 2700, start = -123, after = rngStep(rngStep(0))
  const seeds = Array.from({length:n},(_,i)=>i+start>=1382 ? after : 0)
  const bundle = {meta:{n,start_frame:start},frames:{seed:[seeds],x:[Array(n).fill(-95)],y:[Array(n).fill(0)],air:[Array(n).fill(0)]}}
  const crane = {checkpoints:new Map([[-124,initialCrane(100000)]])}
  const histories = ufoCheckpoints(bundle,crane)
  assert.deepEqual(histories,[])
  bundle.meta.start_seed=0
  assert.equal(ufoCheckpoints(bundle,crane).length,1)
})

test('helicopter and UFO arbitration follows source state and the inclusive departure timer', () => {
  const rng={int(){throw Error('no RNG before helicopter completes departure')}}
  const idle=initialHelicopter(0)
  assert.equal(helicopterStep(idle,{state:1,building:0},rng).state,0)
  const landing=helicopterStep(idle,{state:1,building:2},rng)
  assert.equal(landing.state,1)
  assert.equal(helicopterBlocksUfo(landing),true)
  assert.equal(helicopterBlocksUfo({...landing,seen:true}),false)
  assert.equal(helicopterBlocksUfo({...landing,state:3,timer:700}),true)
  assert.equal(helicopterBlocksUfo({...landing,state:3,timer:701}),false)
  let draws=0
  const departed=helicopterStep({...landing,state:3,age:1999,timer:1999},{state:0,building:0},{int(n){draws++;assert.equal(n,900);return 17}})
  assert.equal(departed.state,0)
  assert.equal(departed.timer,618) // reset to 600+17, then unconditional timer++
  assert.equal(draws,1)
})

test('Fourside accepts all vanilla fighters and Nana can trigger the center roof',()=>{
  const n=150,a=v=>Array(n).fill(v),entity={x:a(-95),y:a(0),air:a(0),state:a(14),age:a(0),cid:a(10),seed_order:a(1),seed:a(0)}
  const make=()=>({meta:{stage:18,start_frame:-123,n,start_seed:0},frames:Object.fromEntries(Object.entries(entity).map(([k,v])=>[k,[v.slice()]]))})
  for(let cid=0;cid<27;cid++){const b=make();b.frames.cid=[a(cid)];assert.ok(simulate(b,100),`cid ${cid}`)}
  const b=make();b.frames.fol=[{of:0,...structuredClone(entity),cid:a(11),seed_order:a(2)}]
  b.frames.fol[0].x[100]=0;b.frames.fol[0].y[100]=30
  assert.equal(touchesCenter(b,-23),true)
  assert.equal(touchesCenter(b,-24),false)
  const absent=make();absent.frames.fol=[Object.fromEntries(Object.keys(entity).map(k=>[k,a(null)]))]
  assert.equal(touchesCenter(absent,-23),false)
  assert.ok(simulate(absent,100))
})
