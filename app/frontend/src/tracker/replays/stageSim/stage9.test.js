import test from 'node:test'
import assert from 'node:assert/strict'
import simulate, {awningStep,initialBuilding,buildingStep,ambientStep} from './stage9.js'

test('unloaded awnings stay still; landing causes sag and relaxation returns to rest', () => {
  assert.deepEqual(awningStep({position:0,velocity:0}),{position:0,velocity:0,translation:0})
  let s = awningStep({position:0,velocity:0},1,true)
  assert.ok(s.translation < -2)
  for (let i=0;i<400;i++) s = awningStep(s)
  assert.equal(s.position,0)
  assert.equal(s.velocity,0)
})

test('drugstore thresholds count landings and queue the first damaged state', () => {
  let s = initialBuilding()
  s.hits = 4
  s = buildingStep(s,1)
  assert.equal(s.state,2)
  assert.equal(s.animation,3)
  assert.equal(s.frame,0)
})

test('collapse removes roofs at 20 and 90 and draws recovery only at animation end', () => {
  let s = {...initialBuilding(),state:5,next:5,animation:5}, draws = 0
  const random = () => { draws++; return .5 }
  for (let i=1;i<=177;i++) {
    s = buildingStep(s,0,random)
    if (i===19) assert.deepEqual(s.active,[true,true])
    if (i===20) assert.deepEqual(s.active,[false,true])
    if (i===90) assert.deepEqual(s.active,[false,false])
    if (i===176) assert.equal(draws,0)
  }
  assert.equal(draws,1)
  assert.equal(s.state,6)
  assert.equal(s.timer,400)
  for (let i=0;i<402;i++) s = buildingStep(s,0,random)
  assert.equal(s.state,7)
  assert.deepEqual(s.active,[true,true])
})

test('idle simulator is stable across seeking and gates unknown item contacts', () => {
  const n=250, a = v=>Array(n).fill(v)
  const bundle={meta:{stage:9,start_frame:-123,n},frames:{seed:[a(0)],x:[a(-47.7)],y:[a(15)],state:[a(14)],air:[a(0)],cid:[a(18)],age:[a(0)]},items:[]}
  assert.deepEqual(simulate(bundle,200),simulate(bundle,10))
  const contact = {...bundle,items:[{t:52,f:150,x:[0],y:[63.9]}]}
  assert.ok(simulate(contact,149))
  assert.equal(simulate(contact,150),null)
  assert.equal(simulate({meta:bundle.meta,frames:{}},0),null)
})

test('Onett accepts every vanilla character and applies Nana awning contacts',()=>{
  const n=200,a=v=>Array(n).fill(v),entity={x:a(-47.7),y:a(15),state:a(14),air:a(0),age:a(0),cid:a(10)}
  const make=()=>({meta:{stage:9,start_frame:-123,n},frames:{seed:[a(0)],...Object.fromEntries(Object.entries(entity).map(([k,v])=>[k,[v.slice()]]))}})
  for(let cid=0;cid<27;cid++){const b=make();b.frames.cid=[a(cid)];assert.ok(simulate(b,100),`cid ${cid}`)}
  const b=make();b.frames.fol=[{of:0,...structuredClone(entity),cid:a(11)}]
  assert.ok(simulate(b,100))
  const touching=structuredClone(b)
  touching.frames.fol[0].x[101]=-44.54999923706055
  touching.frames.fol[0].y[101]=72
  touching.frames.fol[0].air[100]=1
  assert.deepEqual(simulate(touching,101),simulate(b,101))
  assert.notDeepEqual(simulate(touching,102),simulate(b,102))
  assert.deepEqual(simulate(touching,102),simulate(structuredClone(touching),102))
  const absent=make();absent.frames.fol=[Object.fromEntries(Object.keys(entity).map(k=>[k,a(null)]))]
  assert.deepEqual(simulate(absent,100),simulate(b,100))
})

test('awning ambient transitions use one draw before building recovery',()=>{
  let draws=0
  const rng={int(n){draws++;assert.equal(n,300);return 7}}
  assert.deepEqual(ambientStep({timer:0,active:false},rng),{timer:-1,active:false})
  const s=ambientStep({timer:-1,active:false},rng)
  assert.deepEqual(s,{timer:307,active:true})
  assert.equal(draws,1)
})

test('Nana roof landings collapse both drugstore floors through the registered simulator',()=>{
  const n=1300,a=v=>Array(n).fill(v),entity={x:a(-47.7),y:a(15),state:a(14),air:a(0),age:a(0),cid:a(10),seed_order:a(1),seed:a(0)}
  const b={meta:{stage:9,start_frame:-123,n,start_seed:0},frames:Object.fromEntries(Object.entries(entity).map(([k,v])=>[k,[v]]))}
  b.frames.fol=[{of:0,...structuredClone(entity),cid:a(11),seed_order:a(2)}]
  const nana=b.frames.fol[0]
  for(const i of [100,250,400,550,700,850,1000]){nana.x[i]=0;nana.y[i]=63.89999771118164;nana.air[i-1]=1}
  assert.ok(simulate(b,1000).lines.some(l=>l[0]===46))
  assert.ok(!simulate(b,1100).lines.some(l=>l[0]===46||l[0]===47))
  assert.deepEqual(simulate(b,1100),simulate(structuredClone(b),1100))
})

test('an ice article landing gives an awning the same single contact impulse as Nana',()=>{
  const n=200,a=v=>Array(n).fill(v),entity={x:a(-47.7),y:a(15),state:a(14),air:a(0),age:a(0),cid:a(10)}
  const b={meta:{stage:9,start_frame:-123,n},frames:{seed:[a(0)],...Object.fromEntries(Object.entries(entity).map(([k,v])=>[k,[v]]))}}
  const ice=structuredClone(b)
  ice.items=[{t:106,f:100,x:[-44.55,-44.55],y:[80,76],s:[1,2]}]
  const nana=structuredClone(b)
  nana.frames.fol=[{of:0,...structuredClone(entity),cid:a(11)}]
  nana.frames.fol[0].x[101]=-44.55;nana.frames.fol[0].y[101]=72;nana.frames.fol[0].air[100]=1
  assert.deepEqual(simulate(ice,102),simulate(nana,102))
  assert.notDeepEqual(simulate(ice,102),simulate(b,102))
})
