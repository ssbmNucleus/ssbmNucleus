import test from 'node:test'
import assert from 'node:assert/strict'
import simulate,{initialDonut,donutStep,teeterLoads,teeterStep,initialCarpet,carpetStep,cruiseFloorContact,cruiseSplinePoint,scroll} from './stage11.js'

test('Cruise donut cancels short contact, then falls after a committed shake',()=>{
  let s=initialDonut(100)
  for(let i=0;i<30;i++)s=donutStep(s,true,-100)
  assert.equal(s.state,1)
  assert.equal(donutStep(s,false,-100).state,0)
  s=donutStep(s,true,-100)
  assert.equal(s.state,2)
  assert.throws(()=>donutStep(s,false,-100),/ordered RNG/)
  const draws=[]
  while(s.state===2)s=donutStep(s,false,-100,n=>{draws.push(n);return 0})
  assert.equal(draws.length,16)
  assert.ok(draws.every(n=>n===200))
  assert.equal(s.y,99)
  while(s.state===3)s=donutStep(s,false,-100)
  assert.equal(s.active,false)
  while(s.state===4)s=donutStep(s,false,-100)
  assert.equal(s.y,100)
  assert.equal(s.active,true)
})

test('Cruise teeter load uses radial distance, capped integer weight and a dead zone',()=>{
  const load=teeterLoads([{x:4,y:0,weight:1000},{x:3,y:4,weight:2000},{x:-10,y:0,weight:500}],0,0)
  assert.deepEqual(load,{left:5,right:5,count:3})
  const neutral={state:0,angle:0,speed:0,direction:0,timer:0}
  assert.equal(teeterStep(neutral,load).angle,0)
  assert.equal(teeterStep(neutral,{left:100,right:0,count:1}).angle,3)
  assert.equal(teeterStep({...neutral,angle:10}).angle,9.5)
})

test('Cruise carpet freezes on exit, resumes on contact, and resets collision for one tick',()=>{
  let s=carpetStep(initialCarpet(),false)
  s=carpetStep(s,true)
  assert.equal(s.running,true)
  s=carpetStep(s,false)
  assert.equal(s.running,false)
  s=carpetStep(s,true)
  assert.equal(s.state,2)
  s=carpetStep(s,true,true)
  for(let i=0;i<200;i++)s=carpetStep(s,false)
  assert.equal(s.active,true)
  s=carpetStep(s,false)
  assert.equal(s.active,false)
  assert.equal(s.reset,true)
  assert.equal(carpetStep(s,false).active,true)
  assert.equal(simulate({},0),null)
})

test('Cruise floor query clamps a disconnected endpoint but follows its live neighbor',()=>{
  const frame={x:[[10.09]],y:[[0]],state:[[16]],air:[[0]]}
  const left=[0,1,0,0,10,0],right=[1,1,10,0,20,0]
  const neighbors=[[-1,-1,-1,1],[-1,-1,0,-1]]
  assert.equal(cruiseFloorContact(frame,0,0,left,[left],neighbors),true)
  assert.equal(cruiseFloorContact(frame,0,0,left,[left,right],neighbors),false)
  assert.equal(cruiseFloorContact(frame,0,0,right,[left,right],neighbors),true)
  frame.x[0][0]=10.101
  assert.equal(cruiseFloorContact(frame,0,0,left,[left],neighbors),false)
  frame.x[0][0]=10.09;frame.air[0][0]=1
  assert.equal(cruiseFloorContact(frame,0,0,left,[left],neighbors),false)
})

test('Cruise spline uses arc length and the authored scroll reference transform',()=>{
  const straight={type:2,n:2,length:1,points:[[0,0,0],[1,0,0],[2,0,0],[3,0,0]],segments:[0,1],polys:[[0,0,0,0,1]]}
  assert.deepEqual(cruiseSplinePoint(straight,0),[1,0,0])
  assert.deepEqual(cruiseSplinePoint(straight,1),[2,0,0])
  assert.ok(Math.abs(cruiseSplinePoint(straight,.5)[0]-1.5)<.00002)
  const [x,y]=scroll(0)
  assert.ok(Math.abs(x+276.210011)<.0001)
  assert.ok(Math.abs(y-28.830002)<.0001)
})

test('Cruise reverse seeks restore contact state and returned geometry cannot mutate checkpoints',()=>{
  const bundle=()=>({meta:{stage:11,start_frame:-123,n:720},frames:Object.fromEntries(
    Object.entries({x:500,y:500,air:1,state:29,age:0,cid:18,seed:1}).map(([k,v])=>[k,[Array(720).fill(v)]]))})
  const b=bundle(),end=simulate(b,719)
  assert.ok(end?.complete)
  const expected=simulate(bundle(),350)
  assert.deepEqual(simulate(b,350),expected)
  const changed=simulate(b,350);changed.lines[0][2]=1e9
  assert.deepEqual(simulate(b,350),expected)
  assert.deepEqual(simulate(b,719),end)
  assert.equal(simulate({...b,frames:{...b.frames,fol:[{}]}},0),null)
})

test('Cruise does not invent a seed when a loaded donut begins shaking',()=>{
  const n=180,frames=Object.fromEntries(Object.entries({x:500,y:500,air:1,state:14,age:0,cid:18})
    .map(([k,v])=>[k,[Array(n).fill(v)]]))
  const reference={meta:{stage:11,start_frame:-123,n},frames}
  const loaded=structuredClone(reference)
  for(let i=0;i<n;i++){
    const line=simulate(reference,i).lines.find(l=>l[0]===31)
    loaded.frames.x[0][i]=(line[2]+line[4])/2
    loaded.frames.y[0][i]=line[3]+.0001
    loaded.frames.air[0][i]=0
  }
  assert.ok(simulate(loaded,90))
  assert.equal(simulate(loaded,179),null)
  assert.ok(simulate(loaded,90))
})
