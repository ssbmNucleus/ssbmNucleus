import test from 'node:test'
import assert from 'node:assert/strict'
import simulate,{initialPulley,pulleyStep,ceilingBreak,brokenBlock,blockRespawnStep,blockHit} from './stage19.js'
import {attackSpheres} from './stage16.js'
import {fighterDataFor} from '../stageData.js'
import {unrecordedLaserHistory,unrecordedFireballHistory,unrecordedChefHistory,shadowOscillator,shadowOscillatorStep} from './stage16.js'

test('Shadow Ball keeps the first offset zero and draws only on its 12-frame period',()=>{
  const a=Array(12).fill(0);a[8]=12
  const rng={used:0,float(){this.used++;return .5},int(){this.used++;return 1}}
  const s=shadowOscillator(a,rng);s.multiplier=1
  assert.equal(rng.used,2)
  shadowOscillatorStep(s,a,rng);assert.deepEqual(s.offset,[0,0]);assert.equal(rng.used,2)
  shadowOscillatorStep(s,a,rng);assert.equal(rng.used,4)
  assert.ok(Math.abs(s.offset[0]+25/12)<.000001)
  for(let i=0;i<11;i++)shadowOscillatorStep(s,a,rng)
  assert.equal(rng.used,4)
  shadowOscillatorStep(s,a,rng);assert.equal(rng.used,6)
})

test('hidden fireballs launch on the authored command and stop after a material hit',()=>{
  for(const [cid,state,kind] of [[0,343,48],[17,341,105],[21,343,49],[4,399,130],[4,512,131]]){
    const spawn=fighterDataFor(cid).hitboxes[state].articleSpawns[0],n=spawn.frame+4
    const frames=Object.fromEntries(Object.entries({x:10,y:40,cid,state,dir:1,air:0}).map(([k,v])=>[k,[Array(n).fill(v)]]))
    frames.age=[Array.from({length:n},(_,i)=>i)]
    const b={meta:{stage:19,n},frames},step=unrecordedFireballHistory(b)
    for(let i=0;i<spawn.frame;i++)assert.deepEqual(step(i,[]),[])
    const born=step(spawn.frame,[])
    assert.equal(born.length,1);assert.equal(born[0].track.t,kind)
    assert.equal(born[0].track.x[0],Math.fround(Math.fround(10+spawn.pos[2])+born[0].track.vx[0]));assert.ok(born[0].hits.length)
    assert.equal(born[0].afterCeilingDraws,1)
    const next=step(spawn.frame+1,[])[0]
    assert.ok(next.track.x[1]>next.track.x[0]);next.onHit()
    assert.deepEqual(step(spawn.frame+2,[]),[])
  }
})

test('Chef consumes the queued particle draw before its trajectory and retains its fade',()=>{
  const cid=24,state=353,n=55,spawn=fighterDataFor(cid).hitboxes[state].articleSpawns[0]
  const frames=Object.fromEntries(Object.entries({x:0,y:60,cid,state,dir:1,air:0}).map(([k,v])=>[k,[Array(n).fill(v)]]))
  frames.age=[Array.from({length:n},(_,i)=>i)]
  const step=unrecordedChefHistory({meta:{stage:19,n},frames}),calls=[]
  const rng={float:()=>{calls.push('particle');return .5},int:n=>{calls.push(n);return n-1}}
  for(let i=0;i<spawn.frame;i++)step(i,[],[],rng)
  const born=step(spawn.frame,[],[],rng)[0]
  assert.deepEqual(calls,['particle',3]);assert.equal(born.track.vx[0],Math.fround(.2))
  assert.ok(born.hits.length);born.onHit()
  const next=step(spawn.frame+1,[],[],rng)[0]
  assert.deepEqual(next.hits,[]);assert.equal(next.track.s[1],1)
  assert.equal(next.track.x[1],next.track.x[0])
})

test('the native item cap cannot silently hide an unsupported article',()=>{
  for(const [cid,state] of [[10,341],[4,539],[18,108]]){
    const b={meta:{stage:19,n:1},frames:{x:[[0]],y:[[0]],cid:[[cid]],state:[[state]],age:[[0]],dir:[[1]],air:[[0]]}}
    assert.ok(unrecordedLaserHistory(b)(0,[],[]).some(e=>e.hits===null),`${cid}:${state}`)
  }
  const b={meta:{stage:19,n:1},frames:{x:[[0]],y:[[0]],cid:[[4]],state:[[475]],age:[[0]],dir:[[1]],air:[[0]]}}
  assert.deepEqual(unrecordedLaserHistory(b)(0,[],[]),[],'copied Puff is a fighter attack')
})

test('Inishie block requires strict ceiling delta and clearance before respawning',()=>{
  assert.equal(ceilingBreak(.7),false)
  assert.equal(ceilingBreak(-.71),true)
  let s=brokenBlock(n=>{assert.equal(n,100);return 99})
  assert.equal(s.timer,499)
  for(let i=0;i<499;i++)s=blockRespawnStep(s,false)
  assert.equal(s.active,false)
  s=blockRespawnStep(s,true)
  assert.equal(s.active,false)
  s=blockRespawnStep(s,false)
  assert.equal(s.active,true)
  assert.equal(s.timer,30)
})

test('Inishie pulley responds to relative weight, then falls and recovers',()=>{
  const neutral=initialPulley()
  assert.equal(pulleyStep(neutral,87,87).offset,0)
  // The source saturates BOTH accumulated loads when either overflows.
  assert.equal(pulleyStep(neutral,100001,0).offset,0)
  assert.ok(pulleyStep(neutral,87,0).offset<0)
  assert.ok(pulleyStep(neutral,0,87).offset>0)
  let s=neutral
  for(let i=0;i<2000&&s.state===0;i++)s=pulleyStep(s,0,696)
  assert.equal(s.state,1)
  assert.equal(s.offset,40)
  for(let i=0;i<2000&&s.state===1;i++)s=pulleyStep(s,0,0,-100)
  assert.equal(s.state,2)
  for(let i=0;i<2000&&s.state!==0;i++)s=pulleyStep(s,0,0,-100)
  assert.equal(s.state,0)
  assert.equal(s.offset,0)
  assert.equal(neutral.offset,0)
  assert.equal(simulate({},0),null)
})

test('Inishie pulley waits below the authored blast bottom and returns after 180 ticks',()=>{
  // GrI1.dat: blast bottom -95.2. Both platforms must be below -125.2;
  // the high platform is 80 model units above the low one at separation 40.
  let s={...initialPulley(),state:1,offset:40,fall:-222,speed:1.98}
  s=pulleyStep(s,0,0)
  assert.equal(s.state,2)
  const stopped=s.fall
  for(let i=0;i<179;i++)s=pulleyStep(s,0,0)
  assert.equal(s.state,2)
  assert.equal(s.fall,stopped)
  s=pulleyStep(s,0,0)
  assert.equal(s.state,3)
  assert.equal(s.fall,0)
  assert.equal(s.offset,40)
  s=pulleyStep(s,0,0)
  assert.ok(s.offset<40)
})

test('Inishie allows a proven attack miss but refuses a hit without its RNG',()=>{
  const bundle=y=>{
    const frames={}
    for(const [key,value] of Object.entries({x:0,y,air:0,state:44,age:4,cid:18,dir:1}))frames[key]=[[value]]
    return {meta:{stage:19,start_frame:-123,n:1},frames}
  }
  assert.ok(simulate(bundle(0),0)?.complete)
  assert.equal(simulate(bundle(20),0),null)
})

function history(n=600) {
  const frames={}
  for(const [key,value] of Object.entries({x:160,y:0,air:0,state:14,age:1,cid:18,dir:1,pre_state:14,seed:1}))frames[key]=[Array(n).fill(value)]
  return {meta:{stage:19,start_frame:-123,n},frames,items:[]}
}
function at(bundle,i,values){for(const [key,value] of Object.entries(values))bundle.frames[key][0][i]=value}

test('Inishie default path reconstructs a head bump before StopCeil changes the root',()=>{
  const b=history()
  at(b,2,{x:-101.78419494628906,y:18.54010009765625,air:1,state:25,age:8,pre_state:25})
  at(b,3,{x:-102.41387176513672,y:18.30419921875,air:1,state:250,age:0,pre_state:25,dir:-1,seed:3903199692})
  // The post-to-post delta is only -.236, below .7. The animated old ECB
  // gives a .973 upward collision displacement, so the brick DOES break.
  assert.ok(simulate(b,3).lines.some(l=>l[0]===13))
  assert.ok(!simulate(b,4).lines.some(l=>l[0]===13))
  assert.ok(!simulate(b,472).lines.some(l=>l[0]===13))
  assert.ok(simulate(b,473).lines.some(l=>l[0]===13))
  const earlier=simulate(b,4);earlier.lines[0][2]=999
  assert.notEqual(simulate(b,4).lines[0][2],999)
  assert.ok(simulate(b,0).lines.some(l=>l[0]===13))
})

test('Inishie sword hit consumes the slash spark draw before its respawn draw',()=>{
  const b=history()
  at(b,2,{x:7.266547679901123,y:34.000099182128906,state:44,age:3,pre_state:44,dir:-1})
  at(b,3,{x:7.266547679901123,y:34.000099182128906,state:44,age:4,pre_state:44,dir:-1,seed:1472542251})
  assert.ok(simulate(b,3).lines.some(l=>l[0]===21))
  assert.ok(!simulate(b,4).lines.some(l=>l[0]===21))
  assert.ok(!simulate(b,405).lines.some(l=>l[0]===21))
  assert.ok(simulate(b,406).lines.some(l=>l[0]===21))
})

test('Inishie capsule test rejects the enclosing sphere corner and sweeps moving attacks',()=>{
  assert.equal(blockHit({x:7,y:0,z:0,radius:.1},null,0,0),false)
  assert.equal(blockHit({x:10,y:0,z:0,radius:1},{x:-10,y:0,z:0},0,0),true)
  assert.equal(blockHit({x:0,y:8,z:0,radius:1},null,0,0),true)
  assert.equal(blockHit({x:0,y:8.01,z:0,radius:1},null,0,0),false)
})

test('Bowser aerial ceiling correction precedes the other two material callbacks',()=>{
  const b=history()
  b.frames.cid[0].fill(5)
  at(b,2,{x:-89.07304382324219,y:15.655118942260742,air:1,state:68,age:21,pre_state:68,dir:-1})
  at(b,3,{x:-89.07304382324219,y:12.314802169799805,air:1,state:68,age:22,pre_state:68,dir:-1,seed:798387652})
  // Captured Cb2 keeps AttackAirHi, so a StopCeil-only adapter misorders
  // these respawns. Ceiling first, two sparks, then two damage callbacks.
  for(const [id,restored] of [[11,472],[12,468],[13,482]]){
    assert.ok(!simulate(b,4).lines.some(l=>l[0]===id))
    assert.ok(!simulate(b,restored-1).lines.some(l=>l[0]===id))
    assert.ok(simulate(b,restored).lines.some(l=>l[0]===id))
  }
})

test('Bowser jab uses the new pose at an exact constant-key endpoint',()=>{
  const b=history()
  b.frames.cid[0].fill(5)
  at(b,2,{x:12.780001640319824,y:34.000099182128906,state:44,age:7,pre_state:44,dir:-1})
  at(b,3,{x:12.780001640319824,y:34.000099182128906,state:44,age:8,pre_state:44,dir:-1})
  assert.ok(simulate(b,3).lines.some(l=>l[0]===22))
  assert.ok(!simulate(b,4).lines.some(l=>l[0]===22))
  const second=history()
  second.frames.cid[0].fill(5)
  at(second,3,{x:12.780001640319824,y:34.000099182128906,state:45,age:8,pre_state:45,dir:-1})
  assert.equal(simulate(second,4).lines.length,simulate(second,0).lines.length,'jab 2 must miss the block overhead')
})

test('default pulley applies each current fighter weight and includes Nana independently',()=>{
  const loaded=(cid,follower=false)=>{
    const b=history(10)
    const line=simulate(history(10),0).lines.find(l=>l[0]===26)
    const values={x:(line[2]+line[4])/2,y:line[3],cid}
    if(follower){
      const row=Object.fromEntries(Object.entries(b.frames).map(([k,v])=>[k,[...v[0]]]))
      for(const [key,value] of Object.entries(values))row[key].fill(value)
      b.frames.fol=[{of:0,...row}]
      b.frames.cid[0].fill(10)
    }else for(const [key,value] of Object.entries(values))b.frames[key][0].fill(value)
    return simulate(b,9)
  }
  assert.deepEqual(loaded(11,true),loaded(11),'Nana alone carries her own weight')
  assert.notDeepEqual(loaded(5),loaded(15),'Bowser and Jigglypuff produce different pulley displacement')
  for(let cid=0;cid<27;cid++)assert.ok(loaded(cid)?.complete,`weight ${cid}`)
})

test('normal multiplayer material hits and Nana attacks do not take a solo-character gate',()=>{
  for(const follower of [false,true]){
    const b=history(25),n=b.meta.n,row={}
    b.frames.pct=[Array(n).fill(0)];b.frames.seed_order=[Array(n).fill(1)]
    for(const [key,value] of Object.entries({x:300,y:0,air:1,state:29,age:0,cid:follower?11:1,dir:1,seed:1,pre_state:29,seed_order:2,pct:0}))row[key]=Array(n).fill(value)
    const cid=row.cid[0],age=+Object.keys(fighterDataFor(cid).hitboxes[44].frames)[0]
    const h=attackSpheres(cid,44,age,0,0,1)[0]
    row.x[5]=0-h.x;row.y[5]=29.75-h.y;row.state[5]=44;row.pre_state[5]=44;row.age[5]=age
    if(follower){delete row.pct;b.frames.fol=[{of:0,...row}];b.frames.cid[0].fill(10)}
    else for(const [key,values] of Object.entries(row))b.frames[key].push(values)
    assert.ok(simulate(b,24)?.complete)
    assert.ok(simulate(b,7).lines.length<simulate(b,4).lines.length)
  }
})

test('pulley floor callback keeps its load within the native endpoint tolerance',()=>{
  const baseline=simulate(history(2),0).lines.find(l=>l[0]===26)
  const loaded=outside=>{
    const b=history(2)
    at(b,0,{x:Math.min(baseline[2],baseline[4])+outside,y:baseline[3],cid:15,state:17,age:.5})
    return simulate(b,1)
  }
  assert.deepEqual(loaded(-.05),loaded(.05),'grounded endpoint tolerance retains Jigglypuff weight')
  assert.notDeepEqual(loaded(-.11),loaded(.05),'a point outside the native tolerance is not a floor contact')
})

test('Nana second StopCeil map breaks a brick that the first map does not',()=>{
  const b=history(),n=b.meta.n,row={of:0}
  b.frames.cid[0].fill(10);b.frames.pct=[Array(n).fill(0)];b.frames.seed_order=[Array(n).fill(1)]
  for(const [key,value] of Object.entries({x:300,y:0,air:1,state:29,age:0,cid:11,dir:1,seed:1,pre_state:29,seed_order:2}))row[key]=Array(n).fill(value)
  for(const [i,values] of [[2,{x:-24.046951293945312,y:50.90010452270508,state:28,age:7,pre_state:28}],[3,{x:-23.33403778076172,y:48.12616729736328,state:250,age:0,pre_state:28,seed:285975648}]])
    for(const [key,value] of Object.entries(values))row[key][i]=value
  b.frames.fol=[row]
  assert.ok(!simulate(b,4).lines.some(l=>l[0]===18))
  assert.ok(!simulate(b,484).lines.some(l=>l[0]===18))
  assert.ok(simulate(b,485).lines.some(l=>l[0]===18))
})

test('two StopCeil callbacks consume two timers and uncertain clearance can recover',()=>{
  const b=history()
  b.frames.cid[0].fill(10)
  at(b,2,{x:6.9234771728515625,y:16.100101470947266,air:1,state:25,age:6,pre_state:25})
  at(b,3,{x:7.3649702072143555,y:14.141890525817871,air:1,state:250,age:0,pre_state:25,seed:1349971170})
  // Both Cb2 displacements exceed .7: the second RNG draw selects 463.
  assert.ok(!simulate(b,466).lines.some(l=>l[0]===23))
  assert.ok(simulate(b,467).lines.some(l=>l[0]===23))
  const uncertain=structuredClone(b)
  at(uncertain,466,{x:8.5,y:4,air:1,state:29,age:2,pre_state:29})
  assert.equal(simulate(uncertain,467),null)
  assert.ok(simulate(uncertain,468).lines.some(l=>l[0]===23),'resume after all possible blended poses clear')
})

test('birth-frame Thunder Jolt hit includes its deferred hand-effect RNG',()=>{
  // Native c30-pikachu 5218..5219: AirN creates the shot before landing
  // changes the recorded state to N. Both native blocks return at5633.
  const b=history();b.frames.cid[0].fill(12)
  at(b,2,{x:0,y:34.16999816894531,air:1,state:342,age:17,pre_state:342,dir:-1})
  at(b,3,{x:0,y:34.000099182128906,air:0,state:341,age:18,pre_state:342,dir:-1,seed:1024643812})
  for(const id of [21,22]){
    assert.ok(!simulate(b,416).lines.some(l=>l[0]===id))
    assert.ok(simulate(b,417).lines.some(l=>l[0]===id))
  }
})
