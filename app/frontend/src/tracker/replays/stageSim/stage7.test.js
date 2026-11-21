import test from 'node:test'
import assert from 'node:assert/strict'
import simulate, { stepSeed, initialState, advance, drift, driftOnly, shipWitness, cursorOffsets, driftOnlyStep, geometry, sample, pathPosition, nearLand, initialCannon, advanceCannon, initialBackground, advanceBackground, backgroundKind, cameraBackgroundKinds, waterDraws, cannonDamageLimit, cannonContacts, applyCannonContacts, cameraHistory } from './stage7.js'
import {supportedHistory} from './stage29.js'
import stage20 from './stage20.js'

test('cannon waits, proximity trigger, alternating fire and reset preserve callback RNG order', () => {
  const calls=[],rng={float(){calls.push('float');return .75},int(n){calls.push(n);return n===4?2:17}}
  const effect=(id,joint,r)=>{assert.equal(r,rng);calls.push([id,joint])}
  const initial=initialCannon()
  let s=advanceCannon(initial,rng,{effect})
  assert.deepEqual(calls,['float',4,[0xBC,2],[0xBC,3]])
  assert.equal(s.shots,10);assert.equal(initial.phase,0)
  for(let i=0;i<160;i++)s=advanceCannon(s,rng,{effect})
  assert.equal(s.phase,1);assert.equal(s.timer,0)
  s=advanceCannon(s,rng,{effect})
  assert.equal(s.phase,2);assert.equal(s.timer,180)
  s=advanceCannon(s,rng,{fighterInRange:true,effect})
  assert.equal(s.phase,3)
  s=advanceCannon(s,rng,{effect,laser:(kind,side,r)=>{assert.equal(r,rng);calls.push(['laser',kind,side])}})
  assert.deepEqual(calls.slice(-2),[[0xC0,3],['laser',1,0]])
  assert.equal(s.side,1);assert.equal(s.wait,10)
  s=advanceCannon({...s,shots:0},rng)
  assert.equal(s.wait,1217);assert.equal(s.phase,0)
})

test('cannon destruction threshold is inclusive and stays destroyed', () => {
  const noRandom={float(){throw Error('draw')},int(){throw Error('draw')}}
  let s=advanceCannon({...initialCannon(),wait:10},noRandom,{damage:199})
  assert.equal(s.phase,0)
  const effects=[]
  s=advanceCannon(s,noRandom,{damage:1,effect:(id,joint)=>effects.push([id,joint])})
  assert.equal(s.phase,5);assert.deepEqual(effects,[[0xE3,2],[0xE3,3]])
  assert.deepEqual(advanceCannon(s,noRandom),s)
})

test('drift consumes three draws only when the acceleration timer expires', () => {
  const s=initialState(),values=[0,.75,.25];let draws=0
  drift(s,()=>values[draws++])
  assert.equal(draws,3)
  assert.equal(s.remaining,29)
  assert.equal(s.ax,Math.fround(.001))
  assert.equal(s.ay,Math.fround(-.001))
  drift(s,()=>{throw new Error('unexpected draw')})
  assert.equal(s.remaining,28)
})

test('random walk clamps velocity and reverses acceleration at bounds', () => {
  const s={...initialState(),remaining:2,x:20,vx:.1,ax:.002,y:-20,vy:-.1,ay:-.002}
  drift(s,()=>{throw new Error('unexpected draw')})
  assert.equal(s.vx,Math.fround(.1))
  assert.equal(s.ax,Math.fround(-.002))
  assert.equal(s.ay,Math.fround(.002))
})

test('FOBJ constants change at the key boundary; SPL0 clears slope packets', () => {
  assert.equal(sample([[0,1,2,null],[5,1,9,null]],4),2)
  assert.equal(sample([[0,1,2,null],[5,1,9,null]],5),9)
  assert.equal(sample([[0,2,0,null],[10,2,20,null]],3),6)
  const keys=[[0,4,0,0],[10,5,null,2],[10,3,10,null],[20,3,20,null]]
  assert.equal(sample(keys,15),15)
})

test('route joint hierarchy composes translation and rotation', () => {
  const route={nodes:[
    {parent:-1,srt:[0,0,Math.PI/2,1,1,1,10,20,0],tracks:{}},
    {parent:0,srt:[0,0,0,1,1,1,2,0,0],tracks:{}},
  ]}
  const p=pathPosition(route,0)
  assert.ok(Math.abs(p[0]-10)<1e-10)
  assert.ok(Math.abs(p[1]-22)<1e-10)
  assert.equal(nearLand(559,0),false)
  assert.equal(nearLand(2738,0),true)
})

test('bank wait expires after decrement; a bank animation starts on the next proc', () => {
  const s={...initialState(),frame:600,remaining:100,type:1,group:1,
    plane:{start:559,route:0,bankState:0,bankWait:1,bankStart:559,bankAnim:-1}}
  const waiting=advance(s,0)
  assert.equal(waiting.plane.bankWait,0)
  assert.equal(waiting.plane.bankState,0)
  const banking=advance(waiting,1)
  assert.equal(banking.plane.bankState,4) // seed 1: draws 41, 51235; scheduler before bank
  assert.equal(banking.plane.bankStart,602)
  assert.equal(s.plane.bankWait,1)
})

test('seeking and zero-valued seeds are supported; missing seeds are not', () => {
  const n=180,arr=v=>[Array(n).fill(v)]
  const b={meta:{stage:7,start_frame:-123,n},frames:{seed:arr(0),x:arr(0),y:arr(300),dir:arr(-1),cid:arr(18),state:arr(14),age:arr(0),air:arr(0)},
    items:[0,1].map(()=>({t:160,o:-1,f:0,x:Array(n).fill(-100),s:Array(n).fill(2),d:Array(n).fill(0)}))}
  const result=simulate(b,160)
  assert.equal(result.complete,true)
  assert.equal(result.lines.length,44)
  assert.deepEqual(simulate(b,100),simulate(structuredClone(b),100))
  result.lines[0][2]=9999
  assert.notEqual(simulate(b,160).lines[0][2],9999)
  assert.equal(simulate({...b,frames:{}},300),null)
  assert.equal(stepSeed(0),2531011)
  assert.equal(simulate({...b,meta:{stage:7,start_frame:0}},0),null)
  const changed=structuredClone(b)
  changed.items.push({t:68,f:100,x:[0]})
  const camera=cameraHistory(changed)
  assert.ok(Number.isFinite(camera[100]))
  assert.equal(camera[101],null)
  // A new camera subject need not reject the whole stage. The source bounds
  // still certify this frame when camera reconstruction becomes unavailable.
  assert.deepEqual(simulate(changed,101),simulate(b,101))
})

test('background latch draws once on strip 4 and resets on strip 9',()=>{
  let draws=0
  const rng={int(n){assert.equal(n,3);draws++;return 1}}
  let s=advanceBackground(initialBackground(),4,rng)
  assert.equal(s.latched,true);assert.equal(s.active,false)
  s=advanceBackground(s,4,rng)
  assert.equal(draws,1)
  s=advanceBackground(s,9,rng)
  s=advanceBackground(s,4,rng)
  assert.equal(draws,2)
  assert.deepEqual([-1000,0,1000].map(x=>backgroundKind(-123,x)),[-1,8,-1])
  assert.equal(backgroundKind(-122,-1000),9)
  assert.equal(backgroundKind(-124+3024,0),8)
})

test('camera strip bounds retain both possible triggers at a crossing',()=>{
  assert.deepEqual(cameraBackgroundKinds(-123),[8])
  const kinds=cameraBackgroundKinds(1200)
  assert.ok(kinds.includes(9)&&kinds.includes(4))
  for(const x of [-200,-100,0,100,200])assert.ok(kinds.includes(backgroundKind(1200,x)))
})

test('shared history helper permits Nana on contact-independent stage 20',()=>{
  const n=150,a=v=>Array(n).fill(v),entity={x:a(0),y:a(15),air:a(0),state:a(14),age:a(0),cid:a(10),seed:a(0),seed_order:a(1)}
  const b={meta:{stage:20,start_frame:-123,n,start_seed:0},frames:Object.fromEntries(Object.entries(entity).map(([k,v])=>[k,[v]]))}
  const follower=structuredClone(b)
  follower.frames.fol=[{of:0,...structuredClone(entity),cid:a(11),seed_order:a(2)}]
  assert.equal(supportedHistory(follower,100,20),true)
  assert.deepEqual(stage20(follower,100),stage20(b,100))
  assert.ok(stage20(follower,100))
  follower.meta.stage=29
  assert.equal(supportedHistory(follower,100,29),false)
})

test('underwater motion uses the old 900-frame timer and segment intersections',()=>{
  const rng={int(){return 0}}
  let s=advanceBackground(initialBackground(),4,rng)
  assert.equal(s.depth,0)
  for(let i=0;i<900;i++)s=advanceBackground(s,4,rng)
  assert.equal(s.timer,900)
  assert.equal(s.depth,-223)
  const up=advanceBackground(s,4,rng)
  assert.ok(up.depth>s.depth)
  let draws=0
  waterDraws({y:-7,background:s},{float(){draws++;return .2}})
  assert.equal(draws,2)
  waterDraws({y:0,background:initialBackground()},{float(){throw Error('dry intersection')}})
})

test('cannon prefix runs after drift and before the flyby scheduler',()=>{
  let called=false
  const result=advance({...initialState(),wait:1},0,(s,rng)=>{
    assert.equal(rng.used,3)
    assert.equal(s.wait,1)
    advanceCannon(initialCannon(),rng)
    assert.ok(rng.used===4||rng.used===5)
    called=true
  })
  assert.equal(called,true)
  assert.ok(result.plane)
})

test('later shots certify earlier damage; unknown later attacks fail closed',()=>{
  const n=30,state=Array(n).fill(14),material=[{t:160,f:0,d:Array.from({length:n},(_,i)=>i<5?0:1)}]
  state[5]=60
  const b={meta:{n},frames:{state:[state]},items:[{t:235,o:-1,f:10,x:Array(20).fill(0)}]}
  assert.equal(cannonDamageLimit(b,material),Infinity)
  state[15]=60
  assert.equal(cannonDamageLimit(b,material),16)
  state[15]=14
  assert.equal(cannonDamageLimit({...b,items:[]},material),6)
  assert.equal(cannonDamageLimit({...b,items:[{...b.items[0],o:0}]},material),11)
  const unhit=[{t:160,f:0,d:Array(n).fill(0)}]
  assert.equal(cannonDamageLimit(b,unhit),Infinity)
})

test('Corneria camera and cannon witnesses include followers and ignore absent samples',()=>{
  const n=180,a=v=>Array(n).fill(v),entity={x:a(0),y:a(300),dir:a(1),cid:a(10),state:a(14),air:a(0),age:a(0),seed:a(0),seed_order:a(1)}
  const make=()=>({meta:{stage:7,start_frame:-123,n},frames:Object.fromEntries(Object.entries(entity).map(([k,v])=>[k,[v.slice()]])),items:[0,1].map(()=>({t:160,f:0,x:a(-100),s:a(2),d:a(0)}))})
  for(let cid=0;cid<27;cid++){const b=make();b.frames.cid=[a(cid)];assert.ok(simulate(b,100),`cid ${cid}`)}
  const b=make();b.frames.fol=[{...structuredClone(entity),of:0,x:a(100),cid:a(11),seed_order:a(2)}]
  assert.ok(simulate(b,160));assert.notDeepEqual(cameraHistory(b),cameraHistory(make()))
  const absent=make();absent.frames.fol=[Object.fromEntries(Object.keys(entity).map(k=>[k,a(null)]))]
  assert.deepEqual(cameraHistory(absent),cameraHistory(make()))
  b.items[0].d[5]=1;b.items.push({t:235,o:-1,f:10,x:a(0)})
  b.frames.fol[0].state[15]=60
  assert.equal(cannonDamageLimit(b,b.items.slice(0,2)),16)
})

test('VS camera initializes to its target at the stage FOV before replay frame zero',()=>{
  const n=4,a=v=>[Array(n).fill(v)]
  const b={meta:{n},frames:{x:a(51.30000305175781),y:a(327.3748779296875),cid:a(18),state:a(322),dir:a(-1)}}
  const trace=[],history=cameraHistory(b,(i,c)=>trace[i]=structuredClone(c))
  assert.ok(Math.abs(history[0]-39.58574676513672)<.00002)
  assert.equal(trace[0].fov,30)
  assert.ok(Math.abs(trace[2].interest[1]-334.56292724609375)<.00004)
  assert.equal(history[1],trace[0].interest[0]) // stage reads the previous camera pass
})

test('camera bounds use lbVector polynomial rotations and rebirth keeps its original destination',()=>{
  const n=5,a=v=>[Array(n).fill(v)]
  const b={meta:{n},frames:{x:a(-220),y:a(250),cid:a(18),state:a(14),dir:a(1)}}
  const trace=[];cameraHistory(b,(i,c)=>trace[i]=structuredClone(c))
  // Using ordinary trigonometry in lbVector_Rotate changes a clamped view.
  assert.ok(trace[0].target[0]<-177)
  b.frames.state[0]=[14,12,12,12,13]
  b.frames.x[0]=[-220,-24.30000114440918,-116,-100,-24.30000114440918]
  b.frames.y[0]=[250,414.31488037109375,242,240,318.73486328125]
  const changed=[];cameraHistory(structuredClone(b),(i,c)=>changed[i]=structuredClone(c.subjects[0]))
  assert.deepEqual(changed[2].rebirth,changed[1].rebirth)
  assert.deepEqual(changed[3].rebirth,changed[1].rebirth)
  assert.equal(changed[2].x,b.frames.x[0][1])
  assert.ok(Math.abs(changed[2].y-330.73487854003906)<.00004)
})

test('cannon damage accepts one hit per attack group and material only during vulnerability',()=>{
  const contacts=[{key:'0:1:0:0',part:0,damage:13,direction:-1},{key:'0:1:0:0',part:0,damage:10,direction:-1},{key:'0:1:1:0',part:1,damage:13,direction:-1}]
  const active=contacts.map(h=>h.key)
  for(const phase of [1,2,4,5])assert.equal(applyCannonContacts({...initialCannon(),phase},contacts,active).pending,0)
  const first=applyCannonContacts({...initialCannon(),phase:3,damage:180},contacts,active)
  assert.equal(first.pending,26)
  assert.equal(first.damage,180) // damage callback is later than the ground pass
  assert.equal(applyCannonContacts(first,contacts,active).pending,0)
  const expired=applyCannonContacts(first,[],[])
  assert.equal(applyCannonContacts(expired,contacts,active).pending,26)
  const noRandom={float(){throw Error('draw')},int(){throw Error('draw')}}
  const destroyed=advanceCannon(first,noRandom,{damage:first.pending})
  assert.equal(destroyed.phase,5);assert.equal(destroyed.damage,206)
  assert.equal(applyCannonContacts(destroyed,contacts,active).pending,0)
})

test('cannon contacts use stage-owned poses and distinguish initial material states',()=>{
  const n=3,a=v=>[Array(n).fill(v)]
  const b={meta:{n},frames:{x:a(-116),y:a(224.4),cid:a(18),state:a(66),dir:a(1),age:[[4,5,6]]},items:[]}
  const material=[2,0].map(s=>({x:Array(n).fill(-105),y:Array(n).fill(227.6),s:Array(n).fill(s)}))
  const plan=cannonContacts(b,material)
  assert.equal(plan.known,true)
  assert.equal(new Set(plan.rows[2].map(h=>h.part)).size,2)
  assert.ok(plan.rows[2].every(h=>[9,10,13].includes(h.damage)))
  b.frames.cid[0].fill(1)
  assert.equal(cannonContacts(b,material).known,false)
})

test('past the cannon witness the hull keeps drifting exactly as the full step does', () => {
  // drift is the first draw on the frame's cursor, so the hull's motion does
  // not depend on the cannon or flyby draws that follow it
  let full={...initialState(),wait:100000,frame:0}, hull={...full}
  for(let i=0;i<400;i++){
    const seed=(i*2654435761+12345)>>>0
    full=advance(full,seed)
    hull=driftOnly(hull,seed)
    for(const k of ['x','y','vx','vy','ax','ay','remaining'])assert.equal(hull[k],full[k],`${k} at ${i}`)
  }
  assert.equal(hull.driftOnly,true);assert.equal(hull.plane,null)
})

test('the recorded gun item is the ship: it re-syncs a cursor something unmodelled moved', async () => {
  const { random, advanceSeed } = await import('./rng.js')
  const F = Math.fround
  // a frame where the ship picks a new acceleration, and 6 draws the model
  // does not know about happened first (Samus's neutral-B entry, stored charge)
  const previous = { ...initialState(), x: 3.5, y: -7.25, vx: .05, vy: -.02, remaining: 0 }
  const seed = 0x12345678, truth = { ...previous }, r = random(advanceSeed(seed, 6))
  drift(truth, () => r.float())
  const gun = { x: [F(truth.x - 108.37808), F(truth.x - 108.37808)], y: [F(250 + truth.y - 9.828), F(250 + truth.y - 9.828)] }
  // a frozen row (item hitlag) is no witness; a moving one is the ship
  assert.equal(shipWitness([gun], 1), null)
  gun.x[0] -= 1
  const w = shipWitness([gun], 1)
  assert.ok(Math.abs(w.x - truth.x) < 1e-4 && Math.abs(w.y - truth.y) < 1e-4)
  const offsets = cursorOffsets(previous, seed, w)
  assert.ok(offsets.includes(6) && !offsets.includes(0), JSON.stringify(offsets))
  // with no draw due this frame, or no witness, the model's cursor stands
  assert.deepEqual(cursorOffsets({ ...previous, remaining: 5 }, seed, w), [0])
  assert.deepEqual(cursorOffsets(previous, seed, null), [0])
})

test('drift-only: every candidate drift survives until the gun witness rules it out', () => {
  const a = { ...initialState(), x: 1, y: 2, vx: .01, vy: 0, remaining: 40, cannon: initialCannon() }
  const b = { ...a, x: 1.004 }   // e.g. two cursor offsets that both fit one witness
  // no witness this frame (item hitlag): both carry on
  const both = driftOnlyStep([a, b], 0x2468ace0, null, true)
  assert.equal(both.length, 2)
  // next frame the witness is b's drift: b alone is kept
  const truth = driftOnly(both[1], 0x13579bdf)
  const kept = driftOnlyStep(both, 0x13579bdf, { x: truth.x, y: truth.y }, true)
  assert.equal(kept.length, 1)
  assert.equal(kept[0].x, truth.x)
})

test("drift-only: the gun is drawn only while a fighter's footing certifies it", () => {
  const s = { ...initialState(), cannon: initialCannon(), driftOnly: true }
  const ids = g => new Set(g.lines.map(l => l[0]))
  assert.ok(ids(geometry({ ...s, gunCertain: true })).has(28))
  assert.ok(!ids(geometry({ ...s, gunCertain: false })).has(28))
  assert.ok(ids(geometry({ ...s, driftOnly: false })).has(28))
  assert.ok(!ids(geometry({ ...s, driftOnly: false, cannon: { ...initialCannon(), phase: 5 } })).has(28))
})
