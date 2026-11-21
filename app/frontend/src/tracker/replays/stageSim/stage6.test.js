import test from 'node:test'
import assert from 'node:assert/strict'
import simulate, { advanceSupport, mayDamageStage, stepSeed, initialConnector, advanceConnector, connectorColumns, popConnectorBubble, hitCapsule, simulationHistory } from './stage6.js'
import {fighterDataFor} from '../stageData.js'
import {attackSpheres} from './stage16.js'

function bundle(n=4000) {
  return {meta:{stage:6,start_frame:-123,start_seed:0,n},frames:Object.fromEntries(
    Object.entries({seed:0,state:14,cid:18,age:0,x:0,y:0,air:0,dir:1}).map(([k,v])=>[k,[Array(n).fill(v)]]))}
}
function move(b,at,state,duration,x,y,dir=1) {
  for(let age=1;age<=duration;age++){
    const i=at+age-1
    for(const [k,v] of Object.entries({state,age,x,y,dir}))b.frames[k][0][i]=v
  }
}

test('connector integrates its warmed bubbles instead of freezing the first capture pose', () => {
  const initial=initialConnector(),copy=structuredClone(initial)
  let s=initial
  for(let i=0;i<=199;i++)s=advanceConnector(s)
  // Independent RAM capture at Slippi 76; includes the DAT left-root offset.
  assert.deepEqual(connectorColumns(s),[
    [8.589001655578613,1.215000033378601],
    [10.882001876831055,1.5647673606872559],
    [14.17400074005127,4.856766700744629],
    [17.465999603271484,4.856766700744629],
    [20.757999420166016,1.5647673606872559],
    [23.150999069213867,1.2070000171661377],
  ])
  assert.deepEqual(initial,copy)
  assert.notDeepEqual(connectorColumns(initial),connectorColumns(s))
  assert.equal(s.bubbles.length,16)
})

test('connector seeks use independent checkpoint states across the full history', () => {
  const b=bundle()
  simulate(b,3999)
  for(const idx of [199,0,127,128,3800,300])assert.deepEqual(simulate(b,idx),simulate(structuredClone(b),idx))
})

test('support damage crosses its threshold strictly and damps impact velocity', () => {
  const s={phase:0,timer:0,damage:0,offset:0,velocity:0}
  assert.equal(advanceSupport(s,30).phase,0)
  const hit=advanceSupport(s,31,1)
  assert.equal(hit.phase,0)
  assert.equal(hit.nextPhase,1)
  assert.equal(hit.velocity,Math.fround(.9))
  assert.equal(s.damage,0)
})

test('support break and restoration use deferred phases and one ordered timer draw', () => {
  let s=advanceSupport({phase:0,timer:0,damage:0,offset:0,velocity:0},31)
  s=advanceSupport(s,0,null,{animationFinished:true})
  assert.equal(s.phase,1);assert.equal(s.nextPhase,2)
  assert.throws(()=>advanceSupport(s),/ordered frame RNG/)
  let draws=0
  s=advanceSupport(s,0,null,{rng:{float(){draws++;return .5}}})
  assert.equal(draws,1);assert.equal(s.timer,1499)
  s=advanceSupport({...s,timer:0})
  assert.equal(s.phase,2);assert.equal(s.nextPhase,3)
  s=advanceSupport(s,0,null,{animationFinished:true})
  assert.equal(s.damage,0);assert.equal(s.nextPhase,0)
  s=advanceSupport(s)
  assert.equal(s.phase,0);assert.equal(s.timer,1)
})

test('undamaged support settles and damage decays on the postincrement timer', () => {
  const s={phase:0,timer:21,damage:5,offset:.01,velocity:.01}
  const next=advanceSupport(s)
  assert.equal(next.damage,4)
  assert.equal(next.offset,0)
  assert.equal(next.velocity,0)
})

test('unknown attacks fail closed while harmless attacks keep the default simulator available', () => {
  const b=bundle(300)
  move(b,200,44,20,-120,0)
  assert.ok(simulate(b,280)?.complete)
  assert.equal(stepSeed(0),2531011)
  const unknown=bundle(300)
  unknown.frames.state[0][250]=999
  assert.equal(simulate(unknown,280),null)
  assert.ok(simulate(unknown,200)?.lines.length)
  assert.equal(simulate({...b,frames:{state:b.frames.state}},200),null)
  for(const action of [187,195,217,256,257])assert.equal(mayDamageStage(action),true)
})

test('first connector pop replaces the chain size while retaining its anchor position', () => {
  const state=initialConnector(),copy=structuredClone(state)
  const popped=popConnectorBubble(state)
  assert.equal(popped.bubbles.filter(b=>b.active!==0).length,15)
  assert.equal(popped.bubbles[1].x,state.bubbles[1].x)
  assert.equal(popped.bubbles[1].y,state.bubbles[1].y)
  const freed=popped.bubbles.findIndex(b=>b.active===0)
  assert.ok(freed>=7)
  assert.equal(popped.bubbles[1].size,state.bubbles[freed].size)
  assert.deepEqual(state,copy)
  assert.equal(popConnectorBubble(popped).bubbles.filter(b=>b.active!==0).length,14)
  let settled=popped
  for(let i=0;i<300;i++)settled=advanceConnector(settled)
  assert.ok(connectorColumns(settled).every(p=>p.every(Number.isFinite)))
  assert.notDeepEqual(connectorColumns(settled),connectorColumns(state))
})

test('connector replacement uses a strict distance threshold and first equal candidate', () => {
  const state=initialConnector(),anchor=state.bubbles[1]
  for(let i=7;i<state.bubbles.length;i++)Object.assign(state.bubbles[i],{x:anchor.x+100,y:anchor.y})
  Object.assign(anchor,{x:0,y:0})
  Object.assign(state.bubbles[7],{x:8,y:0})
  assert.equal(popConnectorBubble(state),null)
  Object.assign(state.bubbles[7],{x:7,y:0,size:1.25})
  Object.assign(state.bubbles[8],{x:-7,y:0,size:1.5})
  const popped=popConnectorBubble(state)
  assert.equal(popped.bubbles[7].active,0)
  assert.equal(popped.bubbles[8].active,undefined)
  assert.equal(popped.bubbles[1].size,1.25)
})

test('swept attack capsule detects a crossing without expanding the material radius', () => {
  const c={a:[0,-1,0],b:[0,1,0],radius:2}
  assert.equal(hitCapsule({x:10,y:0,z:0,radius:1},{x:-10,y:0,z:0},c),true)
  assert.equal(hitCapsule({x:10,y:5,z:0,radius:1},{x:-10,y:5,z:0},c),false)
})

test('default Brinstar adapter reconstructs smash damage, tilt and restoration on both sides', () => {
  for(const side of [0,1]){
    const b=bundle(3000),id=side?1:0
    for(const at of [200,261,322])move(b,at,60,49,side?40:-40,side?-4.8295:-.0816,side?1:-1)
    const before=simulate(b,199).lines.find(l=>l[0]===id)
    assert.notDeepEqual(simulate(b,400).lines.find(l=>l[0]===id),before)
    assert.deepEqual(simulate(b,2900).lines.find(l=>l[0]===id),before)
    assert.equal(simulate(b,2999).complete,true)
    const history=simulationHistory(b)
    assert.equal(history.events.filter(e=>e.kind==='hit'&&e.part===side).length,3)
    assert.equal(history.events.filter(e=>e.kind==='phase'&&e.side===side&&e.s.nextPhase===3).length,1)
  }
})

test('default connector handles repeated pops, collapse, separated islands, regrowth and replenishment', () => {
  const b=bundle(3000)
  for(let at=200;at<800;at+=30)move(b,at,44,20,4,-6)
  const initial=simulate(b,199).lines,history=simulationHistory(b)
  const collapsed=history.rows.findIndex(row=>row&&!row.some(l=>l[0]===26))
  assert.ok(collapsed>200)
  assert.equal(simulate(b,collapsed).lines.length,26)
  assert.notDeepEqual(simulate(b,collapsed+110).lines.find(l=>l[0]===5),initial.find(l=>l[0]===5))
  assert.equal(simulate(b,2999).lines.length,31)
  assert.deepEqual(simulate(b,2999).lines.find(l=>l[0]===5),initial.find(l=>l[0]===5))
  for(const idx of [2999,collapsed,0,199])assert.deepEqual(simulate(b,idx),simulate(structuredClone(b),idx))
})

test('Popo and Nana can damage one support during the same collision pass', () => {
  const b=bundle(600),n=b.meta.n
  b.frames.cid[0].fill(10);b.frames.x[0].fill(300)
  b.frames.seed_order=[Array(n).fill(1)]
  const follower=Object.fromEntries(Object.entries(b.frames).map(([key,columns])=>[key,[...columns[0]]]))
  follower.cid.fill(11);follower.seed_order.fill(2);follower.of=0
  b.frames.fol=[follower]
  for(const row of [Object.fromEntries(Object.entries(b.frames).filter(([k])=>k!=='fol').map(([k,v])=>[k,v[0]])),follower]){
    const cid=row.cid[0],age=+Object.keys(fighterDataFor(cid).hitboxes[60].frames)[0]
    const h=attackSpheres(cid,60,age,0,0,-1)[0]
    for(const i of [200,260]){
      row.state[i]=60;row.age[i]=age;row.dir[i]=-1
      row.x[i]=-48.0725-h.x;row.y[i]=12.3946-h.y
    }
  }
  assert.ok(simulate(b,599)?.complete)
  const hits=simulationHistory(b).events.filter(e=>e.kind==='hit'&&e.part===0)
  assert.equal(hits.filter(h=>h.i===200).length,2)
  assert.ok(simulationHistory(b).events.some(e=>e.kind==='phase'&&e.side===0&&e.s.nextPhase===1))
})

test('Jigglypuff getup attack can hit one material with two distinct groups',()=>{
  const b=bundle(300)
  b.frames.cid[0].fill(15)
  b.frames.x[0].fill(300)
  for(const [key,value] of Object.entries({x:-52.9,y:5.4,state:195,age:24,dir:1}))b.frames[key][0][200]=value
  assert.ok(simulate(b,299)?.complete)
  const hits=simulationHistory(b).events.filter(e=>e.i===200&&e.kind==='hit'&&e.part===0)
  assert.deepEqual(hits.map(h=>h.damage),[8,6])
})

test('left support restoration uses the first ground draw through different acid phases',()=>{
  // QueueProc preserves parent-before-child GObj order. Right-island splash
  // generators may draw in these histories, but all occur AFTER this timer.
  for(const start of [1450,1900,2350,2800]){
    const b=bundle(5000)
    for(const i of [start,start+61,start+122])move(b,i,60,49,-40,-.0816,-1)
    const phases=simulationHistory(b).events.filter(e=>e.kind==='phase'&&e.side===0)
    const begin=phases.find(e=>e.s.nextPhase===2),end=phases.find(e=>e.s.nextPhase===3)
    assert.ok(begin&&end)
    const seed=b.frames.seed[0][begin.i+1]
    const value=((Math.imul(seed,214013)+2531011)>>>0)>>>16
    const timer=Math.trunc(Math.fround(600*(value/65536)+1200))
    assert.equal(end.i-begin.i-1,timer,`first draw at ${start}`)
  }
})
