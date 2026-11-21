import test from 'node:test'
import assert from 'node:assert/strict'
import simulate,{plankStep,landingPlank,hazardStep,carrierPoint,copiedPartnerContact} from './stage5.js'
import {fighterFrames} from '../stageData.js'
import {random} from './rng.js'

test('Kongo landing applies an impulse; holding contact is not another landing',()=>{
  const neutral={angle:0,rest:0,speed:0,fixed:false}
  const landed=plankStep([neutral],[1])[0]
  assert.ok(landed.angle>0)
  assert.deepEqual(plankStep([neutral]),[neutral])
  assert.ok(plankStep([landed])[0].speed<landed.speed)
  assert.equal(neutral.angle,0)
})

test('Kongo fixed separator prevents neighbor torque transfer',()=>{
  const a={angle:0,rest:0,speed:0,fixed:false}
  const b={angle:.08,rest:.08,speed:0,fixed:true}
  assert.equal(plankStep([a,b])[0].angle,0)
  assert.ok(plankStep([a,{...b,fixed:false}])[0].angle>0)
  assert.equal(landingPlank(-100,-75,75),0)
  assert.equal(landingPlank(0,-75,75),7)
  assert.equal(landingPlank(100,-75,75),14)
})

test('Kongo requires the complete ordinary-VS replay prefix',()=>{
  assert.equal(simulate({meta:{stage:5}},0),null)
})

test('Kongo hazard draws selection, next timer, log side, then root position',()=>{
  const calls=[],values=[.6,.25,.1,.75],rng={float(){calls.push('float');return values.shift()},int(n){calls.push(n);return Math.floor(values.shift()*n)}}
  const before={timer:1,last:-1},s=hazardStep(before,rng)
  assert.deepEqual(calls,['float','float',2,'float'])
  assert.equal(s.timer,1500)
  assert.deepEqual(s.event,{kind:3,group:2,x:6.75})
  assert.equal(before.timer,1)
  const next=hazardStep(s,{float(){throw Error('no timer expiry')}})
  assert.equal(next.timer,1499);assert.equal(next.event,null)
})

test('Kongo repeat rejection follows the type draw and omits initialization',()=>{
  const calls=[],values=[.6,.25,.1,.9],rng={float(){calls.push('float');return values.shift()},int(n){calls.push(n);return Math.floor(values.shift()*n)}}
  const s=hazardStep({timer:0,last:3},rng)
  assert.equal(s.event,null);assert.deepEqual(calls,['float','float',2,'float'])
  assert.equal(s.timer,1500)
})

test('Kongo carrier placement uses uniform spline parameter, not arc length',()=>{
  const s={n:3,points:[[0,0,0],[0,0,0],[12,0,0],[24,0,0],[36,0,0]]}
  assert.deepEqual(carrierPoint(s,.5),[12,0,0])
  assert.deepEqual(carrierPoint(s,1),[24,0,0])
})

test('Kongo simulation survives reverse seeks and does not expose cached lines',()=>{
  const n=400,zero=()=>Array(n).fill(0),b={meta:{stage:5,start_frame:-123,n,start_seed:1},frames:{x:[zero()],y:[zero()],air:[Array(n).fill(true)],state:[Array(n).fill(14)],age:[zero()],cid:[Array(n).fill(18)],seed:[zero()],frame_seed:[zero()]}},rng=random(1)
  b.frames.seed[0]=Array.from({length:n},()=>{rng.next();return rng.seed})
  const later=simulate(b,399),earlier=simulate(b,100)
  assert.ok(later.lines.length>0)
  later.lines[0][2]=99999
  assert.notEqual(simulate(b,399).lines[0][2],99999)
  assert.deepEqual(earlier,simulate(structuredClone(b),100))
  assert.equal(simulate({...b,frames:{...b.frames,fol:[{}]}},100),null)
})

test('Kongo distinguishes Nana copying Squall Hammer contact from her own landing',()=>{
  const b={frames:{x:[[0]],y:[[0]],cid:[[10]],state:[[344]],fol:[{of:0,x:[0],y:[0],cid:[11],state:[359]}]}}
  assert.equal(copiedPartnerContact(b,fighterFrames(b),0,0),false)
  assert.equal(copiedPartnerContact(b,fighterFrames(b),1,0),true)
  b.frames.fol[0].x[0]=-1.5
  assert.equal(copiedPartnerContact(b,fighterFrames(b),1,0),false)
  b.frames.fol[0].x[0]=0;b.frames.fol[0].state[0]=42
  assert.equal(copiedPartnerContact(b,fighterFrames(b),1,0),false)
})

test('Kongo accepts all vanilla characters and counts an independent follower landing',()=>{
  const n=200,a=v=>Array(n).fill(v)
  const entity={x:a(0),y:a(100),air:a(1),state:a(14),age:a(0),cid:a(10),seed_order:a(1),seed:a(0)}
  const make=()=>({meta:{stage:5,start_frame:-123,n,start_seed:1},frames:{...Object.fromEntries(Object.entries(entity).map(([k,v])=>[k,[v.slice()]])),frame_seed:[a(0)]}})
  for(let cid=0;cid<=26;cid++){const b=make();b.frames.cid=[a(cid)];assert.ok(simulate(b,150),`cid ${cid}`)}
  const neutral=make(),floor=simulate(neutral,149).lines.find(l=>l[0]===54)
  const follower={...structuredClone(entity),of:0,cid:a(11),seed_order:a(2)}
  follower.air[149]=0;follower.x[149]=(floor[2]+floor[4])/2;follower.y[149]=(floor[3]+floor[5])/2
  const b=make();b.frames.fol=[follower]
  const landed=simulate(b,150)
  assert.ok(landed)
  assert.notDeepEqual(landed,simulate(neutral,150))
  assert.deepEqual(landed,simulate(structuredClone(b),150))
  const absent=make();absent.frames.fol=[Object.fromEntries(Object.keys(follower).map(k=>[k,k==='of'?0:a(null)]))]
  assert.deepEqual(simulate(absent,150),simulate(neutral,150))
})
