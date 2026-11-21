import test from 'node:test'
import assert from 'node:assert/strict'
import simulate,{initialPlatform,platformStep,switchBlockStep,platformContact,chooseSwitch,flagWindDraws} from './stage4.js'
import {random} from './rng.js'

test('Castle platform waits for continuous contact and returns after unloading',()=>{
  let s=platformStep(initialPlatform(),0)
  s=platformStep(s,87)
  for(let i=0;i<31;i++)s=platformStep(s,87)
  assert.equal(s.state,0)
  s=platformStep(s,87)
  assert.equal(s.state,2)
  assert.equal(s.position,205)
  assert.deepEqual(platformStep(s,87),platformStep(s,117))
  s=platformStep(s,87)
  assert.equal(s.position,205.5)
  s=platformStep(s,0)
  for(let i=0;i<22;i++)s=platformStep(s,0)
  assert.equal(s.state,3)
  assert.equal(platformStep(s,0).position,205)
})

test('Castle switch growth waits for clearance; collision enables at full size',()=>{
  const initial={hidden:true,active:false,scale:.0001}
  assert.deepEqual(switchBlockStep(initial,true,true),initial)
  let s=switchBlockStep(initial,true,false)
  assert.equal(s.hidden,false)
  for(let i=0;i<9;i++)s=switchBlockStep(s,true)
  assert.equal(s.active,false)
  s=switchBlockStep(s,true)
  assert.equal(s.active,true)
  assert.equal(switchBlockStep(s,false).active,false)
  assert.equal(initial.hidden,true)
})

test('Castle refuses missing history rather than reporting a static complete stage',()=>{
  assert.equal(simulate({meta:{stage:4,start_frame:75,n:1}},0),null)
})

test('Castle retains the floor callback before a grounded fighter takes damage',()=>{
  const line=[14,1,-80,143.6,-63,143.6]
  const frames={x:[[-72,-72,-72]],y:[[143.6001,143.6001,143.6001]],
    air:[[0,1,1]],state:[[14,77,77]],pre_state:[[14,14,77]],pct:[[0,10,10]]}
  assert.equal(platformContact(frames,0,1,line),true)
  assert.equal(platformContact(frames,0,2,line),false)
  assert.equal(platformContact({...frames,pct:[[0,0,0]]},0,1,line),false)
  assert.equal(platformContact({...frames,y:[[143.6001,145,145]]},0,1,line),false)
})

test('Castle keeps grounded edge contact through the native floor tolerance',()=>{
  const line=[15,1,63,106.1,81,106.1]
  const frames={x:[[81.05,81.11]],y:[[106.1001,106.1001]],air:[[0,0]],state:[[17,17]]}
  assert.equal(platformContact(frames,0,0,line),true)
  assert.equal(platformContact(frames,0,1,line),false)
  assert.deepEqual(line,[15,1,63,106.1,81,106.1])
})

test('Castle selects a controller from the ordered wait, color, attachment draws',()=>{
  const rng=random(1106864757)
  assert.deepEqual(chooseSwitch(-1,rng),{timer:597,slot:2,attachment:4})
  assert.equal(rng.used,3)
  const calls=[]
  chooseSwitch(1,{int(n){calls.push(n);return 0}})
  assert.deepEqual(calls,[740,216,11])
})

test('Castle Bullet Bill reset follows conditional wind and all four flag draws',()=>{
  const rng=random(1)
  assert.equal(flagWindDraws(true,1,rng),true)
  assert.equal(rng.used,5)
  assert.equal(flagWindDraws(true,300,rng),false)
  assert.equal(rng.used,11)
  flagWindDraws(false,600,rng)
  assert.equal(rng.used,18)
})

function switchHistory() {
  const n=4050,frames={}
  for(const [key,value] of Object.entries({x:160,y:0,air:0,state:14,age:1,cid:18,dir:1,pre_state:14,seed:1,frame_seed:1}))frames[key]=[Array(n).fill(value)]
  frames.frame_seed[0][84]=3469575313
  frames.seed[0][677]=1106864757
  // Ready wait 593; controller selection idx 677; the authored blink bytes
  // take 129 ticks. The material's end activates that selected Garden group.
  const item={t:160,f:806,x:Array(1913).fill(-15),y:Array(1913).fill(110.8499984741211),s:Array(1913).fill(1)}
  // The first source-selected Bullet Bill is immaterial to this test's
  // geometry, but its independently recorded lifetime must be available.
  const bill={t:160,f:1694,x:Array(650).fill(500),y:Array(650).fill(500),s:Array(650).fill(3)}
  return {meta:{stage:4,start_frame:-123,n},frames,items:[item,bill]}
}

test('Castle default simulator grows the RNG-selected group and supports reverse seeks',()=>{
  const b=switchHistory()
  assert.ok(!simulate(b,2728).lines.some(l=>l[0]===0))
  assert.ok(simulate(b,2729).lines.some(l=>l[0]===0))
  assert.ok(simulate(b,3994).lines.some(l=>l[0]===0))
  assert.ok(!simulate(b,3995).lines.some(l=>l[0]===0))
  const first=simulate(b,2729);first.lines[0][2]=999
  assert.notEqual(simulate(b,2729).lines[0][2],999)
  assert.ok(!simulate(b,0).lines.some(l=>l[0]===0))
  const missing=switchHistory();delete missing.frames.frame_seed
  assert.equal(simulate(missing,2729),null)
})

test('Castle default path bumps a touched question block but not an expired material',()=>{
  const b=switchHistory(),base=simulate(b,2999).lines.find(l=>l[0]===0)[3]
  const material=end=>({t:160,f:2729,x:Array(end-2729).fill(0),y:Array(end-2729).fill(162.5),s:Array(end-2729).fill(2)})
  const hit=switchHistory();hit.items.push(material(3000))
  for(const [i,offset] of [0,2,3,3.5,3,2,0].entries())assert.equal(simulate(hit,3000+i).lines.find(l=>l[0]===0)[3],Math.fround(base+offset))
  const expired=switchHistory();expired.items.push(material(3932))
  assert.equal(simulate(expired,3933).lines.find(l=>l[0]===0)[3],base)
})
