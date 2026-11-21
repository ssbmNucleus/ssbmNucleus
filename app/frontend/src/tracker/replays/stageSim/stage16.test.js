import test from 'node:test'
import assert from 'node:assert/strict'
import simulate,{initialBlock,blockStep,attackSpheres,sphereSweepHit,stopCeilContact,airCatchHistory} from './stage16.js'
import {fighterDataFor} from '../stageData.js'
import {itemRayContact,unrecordedFireballHistory,unrecordedChefHistory,sleepingFighterHistory,chainHistory,chainRayContact,blockVertices,unrecordedLaserHistory,itemMaterialOccupancy,missingProjectileBirths} from './stage16.js'

test('Shadow Ball catches a lower wall corner and resets its explosion joint',()=>{
  // C32 Kingdom contact: the side point passes below the brick, but the
  // upper diamond edge crosses its corner between these two ticks.
  const track={t:112,x:[-31.246936798095703,-29.618366241455078],y:[25.344951629638672,25.344951629638672],s:[3,3],d:[1,1],vx:[1.6285715103149414,1.6285715103149414],vy:[0,0],shadow:[[0,0],[-1.15,-3.5]]}
  const lines=[[84,8,-29.75,25.5,-29.75,34],[40,2,-21.25,25.5,-29.75,25.5]]
  const hits=itemEntryHits({shadowTerminal:true,track,j:1,mapFrom:[track.x[0],track.y[0]],bundle:{meta:{stage:19}},hits:[]},lines,lines)
  assert.equal(track.s[1],12)
  assert.equal(hits.length,1)
  assert.equal(hits[0].x,track.x[1])
  assert.equal(hits[0].y,track.y[1])
  assert.equal(hits[0].z,0)
})

test('air chain launches from the animation root before fighter movement',()=>{
  const n=25,frames={state:[Array(n).fill(352)],age:[Array.from({length:n},(_,i)=>i)],cid:[Array(n).fill(7)],dir:[Array(n).fill(1)],x:[Array(n).fill(-46)],y:[Array(n).fill(19.64000129699707)],joyx:[Array(n).fill(0)],joyy:[Array(n).fill(0)],hitlag:[Array(n).fill(0)]}
  frames.y[0].splice(22,3,19.520000457763672,19.280000686645508,18.920000076293945)
  const step=chainHistory({meta:{stage:19,n},frames})
  for(let i=0;i<n;i++)step(0,i,[])
  const expected=[-31.01361846923828,28.654869079589844,-1.6644985675811768]
  step.points[0][3].forEach((v,k)=>assert.ok(Math.abs(v-expected[k])<.00001))
})

test('a birth-frame laser is recovered once and recorded births are not duplicated',()=>{
  // C31 full Brinstar: the copied laser hits the support and disappears
  // before its first Item Update. Its held blaster survives in the replay.
  const frames={state:[[427,427]],age:[[4,5]],cid:[[4,4]],dir:[[-1,-1]],x:[[-40,-40]],y:[[10.819998741149902,10.819998741149902]],air:[[1,1]]}
  const b={meta:{stage:6,n:2},frames,items:[]},step=missingProjectileBirths(b)
  assert.deepEqual(step(0,[],[]),[])
  const e=step(1,[],[]).find(e=>e.track.t===136)
  assert.equal(e.hits[0].damage,3)
  assert.ok(e.hits[0].x< -48)
  const recorded={...b,meta:{...b.meta,ports:[0]},items:[{...e.track,port:[0]}]}
  const other=missingProjectileBirths(recorded)
  other(0,[],[])
  assert.deepEqual(other(1,[],[]),[])
})

test('copied Falco consumes the conditional animation nodes and removes a material-hit laser',()=>{
  // C31 full Island, native Item Update at index295. The copy animation
  // contains two absent conditional parts before the posed right hand.
  const frames={state:[[524,524,524]],age:[[7,8,9]],cid:[[4,4,4]],dir:[[1,1,1]],x:[[-41.84754180908203,-41.77236557006836,-41.71718978881836]],y:[[21.999996185302734,21.899995803833008,21.719995498657227]],air:[[1,1,1]]}
  const step=unrecordedLaserHistory({meta:{stage:19,n:3},frames})
  step(0,[],[])
  const e=step(1,[],[]).find(e=>e.track?.t===137)
  assert.ok(Math.abs(e.track.x[0]+28.3077392578125)<.00001)
  assert.ok(Math.abs(e.track.y[0]-27.738037109375)<.00001)
  e.onHit()
  assert.equal(step(2,[],[]).some(e=>e.track?.t===137),false)
})

test('copied Charge Shot release uses its corrected CollData before attack resolution',()=>{
  // C31 full Kingdom index297: the hand is inside a brick. Detachment
  // corrects CollData, then the first flight map destroys the shot.
  const frames={state:[[412,412]],age:[[0,1]],cid:[[4,4]],dir:[[1,1]],x:[[-33.86743927001953,-33.86743927001953]],y:[[25.719995498657227,25.45999526977539]],air:[[1,1]]}
  for(const blocked of [false,true]){
    const step=unrecordedLaserHistory({meta:{stage:19,n:2},frames})
    const lines=blocked?[[41,8,-29.75,25.5,-29.75,34]]:[]
    assert.equal(step(0,lines,lines).some(e=>e.track?.t===151),false)
    const e=step(1,lines,lines).find(e=>e.track?.t===151)
    if(blocked)assert.equal(e,undefined)
    else{
      assert.ok(Math.abs(e.track.x[0]+28.995271682739258)<.00001)
      assert.ok(Math.abs(e.track.y[0]-28.212570190429688)<.00001)
    }
  }
})

test('a charged release can damage a support without any flying Item Update',()=>{
  // C31 Brinstar: five charge increments, then release and DmgDealt in
  // one tick. Slippi ends the held state0 track immediately before it.
  const n=102,frames={state:[[...Array(100).fill(408),410,410]],age:[[...Array.from({length:100},(_,i)=>i%10),0,1]]}
  for(const [k,v] of Object.entries({cid:4,x:-40,y:4,dir:1,air:0}))frames[k]=[Array(n).fill(v)]
  const held={t:151,o:0,f:0}
  for(const [k,v] of Object.entries({x:-47,y:6,s:0,d:1,vx:0,vy:0,lifetime:70}))held[k]=Array(n-1).fill(v)
  const b={meta:{stage:6,n,item_frequency:-1},frames,items:[held]},rows=itemAttackHistory(b)
  assert.equal(rows[n-2].find(e=>e.track.t===151).hits.length,0)
  const release=rows[n-1].find(e=>e.track.t===151)
  assert.equal(itemEntryHits(release,[],[])[0].damage,18)
  assert.equal(release.track.s[0],6)
  assert.equal(held.x.length,n-1,'the replay track stays immutable')
})

test('Samus AirCatch uses its source air coefficient and native appended-bone tip',()=>{
  // C32 free pilot, ages5..9. Bone139 is only an offline expected value.
  const frames={cid:[[13,13,13,13,13]],state:[[357,357,357,357,357]],age:[[5,6,7,8,9]],x:[[-55,-55,-55,-55,-55]],y:[[91.93401336669922,92.0420150756836,92.08401489257812,92.06001281738281,92.02281188964844]],dir:[[1,1,1,1,1]],air:[[1,1,1,1,1]],seed:[[2460408579,2460408579,2460408579,4065969668,1634345811]]}
  const step=airCatchHistory({meta:{stage:16,n:5},frames})
  let hits
  for(let i=0;i<5;i++)hits=step(0,i,[])
  const tip=hits.find(h=>fighterDataFor(13).hitboxes[357].runtimeBones[h.id]===139)
  assert.ok(Math.hypot(tip.x+39.17530059814453,tip.y-101.14363861083984,tip.z-2.316633462905884)<.00001)
})

test('a held blaster keeps its spawn ECB through the landing ground pass',()=>{
  const frames={state:[[14,523,524,525,42,42]],age:[[0,1,0,0,0,1]]},n=6
  for(const [k,v] of Object.entries({cid:4,x:-35,y:20,dir:1,air:1}))frames[k]=[Array(n).fill(v)]
  const step=unrecordedLaserHistory({meta:{stage:19,n},frames})
  for(let i=0;i<n;i++){
    const e=step(i,[],[]).find(e=>e.track?.t===139)
    if(i>=1&&i<=4){
      assert.ok(e)
      assert.equal(itemMaterialOccupancy(e.track,-17,29.75,15),true)
      assert.equal(e.track.expiresAt,5)
    }else assert.equal(e,undefined)
  }
})

test('Kirby Chef retains the pan spawn rectangle until the move ends',()=>{
  // C31 Kingdom's block at(-25.5,29.75) is still occupied after Kirby
  // descends below it at1421. The attached pan has no map callback.
  const frames={state:[[25,511,510,14]],age:[[7,1,28,0]],y:[[20.96000099182129,20.880001068115234,0,0]]}
  for(const [k,v] of Object.entries({cid:4,x:-35,dir:1,air:1}))frames[k]=[Array(4).fill(v)]
  const step=unrecordedLaserHistory({meta:{stage:19,n:4},frames})
  step(0,[],[])
  const pan=step(1,[],[]).find(e=>e.track?.t===156)
  assert.ok(pan)
  assert.equal(itemMaterialOccupancy(pan.track,-25.5,29.75,15),true)
  assert.equal(step(2,[],[]).find(e=>e.track?.t===156).track,pan.track)
  assert.equal(pan.track.expiresAt,3)
  assert.equal(step(3,[],[]).some(e=>e.track?.t===156),false)
})

test('item rays keep exact wall endpoints and horizontal intersection coordinates',()=>{
  const wall=[[0,8,93.5,34,93.5,42.5]]
  assert.equal(itemRayContact(92,42.500099,95,42.500099,wall),null)
  assert.equal(itemRayContact(92,42.5,95,42.5,wall)?.line,0)
  const y=-.000006198883056640625
  assert.equal(itemRayContact(-6,1,-5,-4,[[1,1,-8.5,y,0,y]])?.y,y)
})

test('native axis rays clamp corners only after their bounds overlap',()=>{
  const wall=[[50,8,4.25,-8.5,4.25,0]]
  const from=[2.095989465713501,-.032590821385383606,0],to=[7.200174331665039,.17365634441375732,0]
  assert.deepEqual([itemRayContact(...from.slice(0,2),...to.slice(0,2),wall).x,itemRayContact(...from.slice(0,2),...to.slice(0,2),wall).y],[4.25,0])
  const current=[[50,8,4.25,-8.491386413574219,4.25,-.008614063262939453]]
  const old=[[50,8,4.25,-8.465576171875,4.25,-.0344233512878418]]
  // Native chain index821: the returning joint remaps the origin above
  // its wall. Omitting the hidden previous vertices invents a contact.
  assert.equal(chainRayContact(from,to,current,old,()=>true),null)
})

test('returning blocks retain the authored hidden rotation for one ground pass',()=>{
  const blocks=Array.from({length:9},initialBlock)
  blocks[5]={...blocks[5],state:3,timer:323,active:false}
  const vertices=blockVertices(blocks)
  // Native chain index821: before the neutral animation replaces frame323.
  assert.ok(Math.abs(vertices[39][1]-(-.008614063262939453))<.000001)
  assert.ok(Math.abs(vertices[38][1]-(-8.491386413574219))<.000001)
})

test('fireball constructors run physics before the first recorded position',()=>{
  // Native c27 Mario index564: it_802750F8 executes physics/map in accessory4.
  const frames={cid:[[0,0]],state:[[344,344]],age:[[13,14]],dir:[[1,1]],x:[[32.70327377319336,33.151737213134766]],y:[[22.873865127563477,22.92805290222168]]}
  const step=unrecordedFireballHistory({meta:{stage:19,n:2},frames})
  assert.deepEqual(step(0,[]),[])
  const t=step(1,[])[0].track
  assert.ok(Math.abs(t.x[0]-42.618873596191406)<.00002)
  assert.ok(Math.abs(t.y[0]-30.15883445739746)<.00002)
  assert.equal(t.vy[0],-.2964722514152527)
})

test('copied pills rotate their map bounds without scaling their damage radius',()=>{
  // C31 Island's first pill: after 19 flight ticks the rotating diamond
  // reaches a wall/floor corner. A fixed rectangle bounces three ticks early.
  const n=23,frames={state:[Array(n).fill(513)],age:[Array.from({length:n},(_,i)=>13+i)]}
  for(const [k,v] of Object.entries({cid:4,dir:1,x:-41.71718978881836,y:21.719995498657227,air:1}))frames[k]=[Array(n).fill(v)]
  frames.x[0][0]=-41.77236557006836;frames.y[0][0]=21.899995803833008
  const step=unrecordedFireballHistory({meta:{stage:19,n},frames}),lines=simulate(itemBundle(114,0),0).lines
  let entry
  for(let i=0;i<=20;i++)entry=step(i,lines).find(e=>e.track?.t===131)
  assert.ok(Math.abs(entry.track.x[19]+16.241811752319336)<.00003)
  assert.ok(Math.abs(entry.track.y[19]-1.500100016593933)<.00003)
  assert.equal(entry.hits[0].radius,2.3436)
  assert.equal(itemMaterialOccupancy(entry.track,entry.track.x[19],entry.track.y[19],0,19),true)
  entry.onHit()
  assert.equal(entry.track.expiresAt,21)
  assert.deepEqual(step(21,lines),[])
})

test('Chef hand scale and queued particle draw reproduce the native launch',()=>{
  // pass16 Chef index238. Final pre seed is after fighter animation; the
  // queued model3 particle consumes Randf before accessory4 chooses food.
  const frames={cid:[[24,24]],state:[[354,354]],pre_state:[[354,354]],age:[[17,18]],dir:[[1,1]],x:[[-48,-48]],y:[[15.069997787475586,13.36999797821045]],seed:[[1790486070,3057523619]],frame_seed:[[1790486070,1790486070]]}
  const step=unrecordedChefHistory({meta:{stage:19,n:2,start_frame:-123},frames})
  assert.deepEqual(step(0,[]),[])
  const e=step(1,[])[0],t=e.track
  assert.ok(Math.abs(t.x[0]+41.26594543457031)<.00002)
  assert.ok(Math.abs(t.y[0]-24.51266098022461)<.00002)
  assert.equal(t.vx[0],.6000000238418579)
  assert.equal(t.vy[0],1.2000000476837158)
  assert.equal(e.afterCeilingDraws,2)
  e.onHit()
  assert.equal(t.expiresAt,36,'six hitlag frames pause the thirty animation ticks')
})

test('a map-faded copied Chef does not deal a late ceiling hit',()=>{
  // c31 Kirby Chef index313: the recorded root is already .0001 below
  // the native fixed-ECB ceiling correction.
  const b=itemBundle(155,0),t=b.items[0]
  Object.assign(t,{x:[-30.294513702392578,-30.094512939453125],y:[30.308109283447266,30.999906539916992],s:[0,1],d:[1,1],vx:[.20000000298023224,0],vy:[.9600003361701965,0],lifetime:[69,30]})
  const e=itemAttackHistory(b)[6].find(e=>e.chefImpact)
  assert.equal(itemEntryHits(e,[])[0].damage,4)
  assert.deepEqual(itemEntryHits(e,[[0,2,-25.5,34.00000762939453,-34,34.00000762939453]]),[])
})

test('sleeping transformation partners preserve their last clearance rectangle',()=>{
  const frames={cid:[[7,19,7]],state:[[361,14,14]],age:[[36,0,0]],dir:[[1,1,1]],x:[[0,100,0]],y:[[34.000099182128906,0,34.000099182128906]]}
  const occupied=sleepingFighterHistory(frames)
  assert.deepEqual(occupied(0,0,38,1),[])
  assert.deepEqual(occupied(1,0,38,1),[true])
  assert.deepEqual(occupied(2,0,38,1),[false])
})

test('chain launch replaces authored attacks with the four constrained link positions',()=>{
  const frames={age:[[22,23,24]],state:[[349,349,349]]}
  for(const [k,v] of Object.entries({cid:7,x:-29.75,y:.00009999999747378752,dir:1,joyx:0,joyy:0,hitlag:0}))frames[k]=[Array(3).fill(v)]
  const step=chainHistory({meta:{stage:16,n:3},frames})
  step(0,0,[]);step(0,1,[])
  const hits=step(0,2,[])
  for(const h of hits){
    assert.ok(Math.abs(h.x-(h.id===3?-15.1722412109375:-16.6722412109375))<.00003)
    assert.ok(Math.abs(h.y-9.682997703552246)<.00003)
    assert.ok(Math.abs(h.z+.953269898891449)<.00003)
  }
  assert.equal(hits.length,4)
})

test('AirCatch reconstructs appended tip139 and clears Young Link at full extension',()=>{
  // Independent pass16 native JObj matrices; no watch data enters a bundle.
  for(const [cid,x,ys,tip] of [
    [6,-45.07700729370117,[19.692106246948242,19.872106552124023,19.942106246948242,19.9021053314209,19.840105056762695,19.756105422973633,19.650104522705078,19.522104263305664,19.37210464477539,19.200103759765625],[-26.61349105834961,30.401941299438477,-.026448003947734833]],
    [20,-45,[19.86509895324707,19.825098037719727,19.763097763061523,19.67909812927246,19.573097229003906,19.445096969604492,19.29509735107422,19.123096466064453,18.929096221923828,18.713096618652344],[-28.773723602294922,27.65450668334961,.1367608606815338]],
  ]) {
    const n=ys.length,frames={y:[ys],age:[Array.from({length:n},(_,i)=>i+8)]}
    for(const [key,value] of Object.entries({cid,x,state:360,dir:1}))frames[key]=[Array(n).fill(value)]
    const b={meta:{stage:16,n},frames},step=airCatchHistory(b)
    assert.deepEqual(step(0,0,[]),[]);assert.deepEqual(step(0,1,[]),[])
    for(let i=2;i<n;i++) {
      const hs=step(0,i,[])
      if(cid===20&&i>=8){assert.deepEqual(hs,[]);continue}
      const h=hs.find(h=>h.id===1)
      assert.ok(Math.hypot(h.x-(tip[0]+(i-2)*4.050000190734863),h.y-tip[1],h.z-tip[2])<.0003)
    }
    assert.equal(attackSpheres(cid,360,10,x,ys[2],1),null)
    const obstructed=airCatchHistory(b)
    obstructed(0,0,[]);obstructed(0,1,[])
    assert.equal(obstructed(0,2,[[0,8,tip[0]-2,tip[1]-10,tip[0]-2,tip[1]+10]]),null)
  }
})

test('StopCeil inversion certifies a unique ceiling despite the earlier jump blend',()=>{
  // Independent native sample, stage16 Falco frame4502. The static JumpF4
  // pose projects34.082; the native second-map push identifies ceiling34.
  const frames={cid:[[22,22]],x:[[-41.53970718383789,-41.53970718383789]],y:[[20.79480743408203,14.009000778198242]]}
  const blocks=[{active:true}],locations=[[-38.25,38.25]]
  const result=stopCeilContact(frames,0,1,blocks,locations)
  assert.equal(result.block,0);assert.ok(result.correction>0)
  assert.equal(stopCeilContact(frames,0,1,[...blocks,...blocks],[...locations,...locations]),null)
  assert.equal(stopCeilContact(frames,0,1,blocks,locations,[[0,2,-45,34,-35,34]]),null)
})

test('Yorster damage delays collision removal and returns after its damage-dependent animation',()=>{
  let s=blockStep(initialBlock(),{damage:4})
  assert.equal(s.start,9)
  for(let i=0;i<3;i++)s=blockStep(s)
  assert.equal(s.active,true)
  s=blockStep(s)
  assert.equal(s.active,false)
  for(let i=0;i<314;i++)s=blockStep(s)
  assert.equal(s.active,false)
  s=blockStep(s)
  assert.equal(s.active,true)
})

test('Cape hand scale hits the center block without reaching its left neighbor',()=>{
  // Native c27-fireball index4786: Mario faces left at this exact root.
  // RHaveN's inverse model scale prevents a shallow false hit on block3.
  const hits=attackSpheres(0,345,12,13.485342979431152,.00009999999747378752,-1)
  assert.ok(hits.some(h=>sphereSweepHit(h,null,0,-4.25)))
  assert.ok(hits.every(h=>!sphereSweepHit(h,null,-8.5,-4.25)))
})

test('Yorster bump threshold and occupied restoration use separate branches',()=>{
  assert.equal(blockStep(initialBlock(),{bump:.79}).state,0)
  assert.equal(blockStep(initialBlock(),{bump:.81}).state,2)
  const hidden={...initialBlock(),active:false,state:3,timer:323}
  const waiting=blockStep(hidden,{occupied:true})
  assert.equal(waiting.state,4)
  assert.equal(waiting.active,false)
  assert.equal(blockStep({...waiting,timer:25},{occupied:false}).active,true)
  assert.equal(blockStep(initialBlock(),{damage:4,bump:3}).start,9)
})

test('Vanilla Marth hit spheres respect active frames, facing, and swept collision',()=>{
  assert.deepEqual(attackSpheres(18,65,5,0,0,1),[])
  const right=attackSpheres(18,65,6,0,0,1),left=attackSpheres(18,65,6,0,0,-1)
  assert.equal(right.length,4)
  assert.equal(right[0].damage,4)
  assert.equal(right[0].x,-left[0].x)
  assert.equal(right[0].y,left[0].y)
  assert.ok(attackSpheres(1,65,6,0,0,1).length>0)
  assert.equal(attackSpheres(99,65,6,0,0,1),null)
  assert.equal(attackSpheres(18,65,6.5,0,0,1),null)
  const hit={x:20,y:0,z:0,radius:1}
  assert.equal(sphereSweepHit(hit,null,0,0),false)
  assert.equal(sphereSweepHit(hit,{...hit,x:-20},0,0),true)
  assert.equal(sphereSweepHit({...hit,z:10},{...hit,x:-20,z:10},0,0),false)
  assert.equal(simulate({},0),null)
})

test('Yorster history refuses an occupied restore before re-enabling collision',()=>{
  const n=430,frames={}
  for(const [key,value] of Object.entries({x:100,y:0,air:1,state:29,age:0,cid:18,dir:-1}))frames[key]=[Array(n).fill(value)]
  frames.x[0][100]=34;frames.y[0][100]=20;frames.state[0][100]=65;frames.age[0][100]=6
  for(let i=419;i<n;i++){frames.x[0][i]=29.75;frames.y[0][i]=42.5;frames.state[0][i]=14;frames.air[0][i]=0}
  const b={meta:{stage:16,start_frame:-123,n},frames}
  assert.ok(simulate(b,418)?.complete)
  assert.equal(simulate(b,420),null)
})

test('all vanilla jabs feed the default block adapter, including Nana as a follower',()=>{
  const n=25,make=(cid,following=false)=>{
    const row={}
    for(const [key,value] of Object.entries({x:400,y:0,air:1,state:29,age:0,cid,dir:1}))row[key]=Array(n).fill(value)
    const age=+Object.keys(fighterDataFor(cid).hitboxes[44].frames)[0]
    const sphere=attackSpheres(cid,44,age,0,0,1)[0]
    assert.ok(sphere,`jab ${cid}`)
    Object.assign(row.x,{5:29.75-sphere.x});Object.assign(row.y,{5:38.25-sphere.y})
    row.state[5]=44;row.age[5]=age
    const frames=Object.fromEntries(Object.entries(row).map(([k,v])=>[k,[v]]))
    if(following){
      const leader=structuredClone(row);leader.x.fill(400);leader.state.fill(29);leader.cid.fill(10)
      for(const key of Object.keys(row))frames[key]=[leader[key]]
      frames.fol=[{of:0,...row}]
    }
    return {meta:{stage:16,n,start_frame:-123},frames}
  }
  for(let cid=0;cid<27;cid++){
    const b=make(cid),before=simulate(b,4),after=simulate(b,15)
    assert.ok(after?.complete,`available ${cid}`)
    assert.ok(after.lines.length<before.lines.length,`jab breaks a block ${cid}`)
  }
  const follower=make(11,true)
  assert.deepEqual(simulate(follower,15),simulate(make(11),15))
})

test('a proven single Ice Climber ceiling callback uses the preceding displacement',()=>{
  const n=400,frames={}
  for(const [key,value] of Object.entries({x:400,y:0,air:1,state:29,age:0,cid:10,dir:1}))frames[key]=[Array(n).fill(value)]
  for(const [i,values] of [[1,{x:16.259994506835938,y:23.1001033782959,state:25,age:10}],
    [2,{x:16.259994506835938,y:24.6001033782959,state:25,age:11}],
    [3,{x:16.259994506835938,y:22.66565704345703,state:250,age:0}]]){
    for(const [key,value] of Object.entries(values))frames[key][0][i]=value
  }
  const b={meta:{stage:16,n,start_frame:-123},frames},count=simulate(b,0).lines.length
  assert.equal(simulate(b,7).lines.length,count)
  assert.equal(simulate(b,8).lines.length,count-4)
  assert.equal(simulate(b,324).lines.length,count-4)
  assert.equal(simulate(b,325).lines.length,count)
})

test('Fox two-pass ceiling bump counts both callbacks through disappearance and return',()=>{
  const n=400,frames={}
  for(const [key,value] of Object.entries({x:400,y:0,air:1,state:29,age:0,cid:1,dir:1}))frames[key]=[Array(n).fill(value)]
  for(const [i,values] of [[1,{x:24.77013397216797,y:20.930099487304688,state:25,age:6}],
    [2,{x:25.801054000854492,y:23.000099182128906,state:25,age:7}],
    [3,{x:28.97382354736328,y:15.572733879089355,state:250,age:0}]])
    for(const [key,value] of Object.entries(values))frames[key][0][i]=value
  const b={meta:{stage:16,n,start_frame:-123},frames},count=simulate(b,0).lines.length
  assert.equal(simulate(b,7).lines.length,count)
  assert.equal(simulate(b,8).lines.length,count-4)
  assert.equal(simulate(b,331).lines.length,count-4)
  assert.equal(simulate(b,332).lines.length,count)
})

import {itemSpheres,itemAttackHistory,itemEntryHits,materialDamage,smashChargeHistory,unrecordedNessHistory,unrecordedNeedleHistory,luigiMissileHistory,thunderHitHistory} from './stage16.js'
const itemBundle=(kind,state,x=29.75,y=38.25)=>{
  const n=400,frames={}
  for(const [key,value] of Object.entries({x:400,y:0,air:1,state:29,age:0,cid:13,dir:1}))frames[key]=[Array(n).fill(value)]
  return {meta:{stage:16,n,start_frame:-123},frames,items:[{t:kind,o:0,f:5,x:[x],y:[y],d:[1],vx:[1.5],vy:[0],s:[state]}]}
}
test('birth-frame Chef fade and needle bounce retain their preceding material attack',()=>{
  for(const [kind,state,action,age,damage] of [[155,1,510,18,4],[152,4,470,3,3]]){
    const b=itemBundle(kind,state),t=b.items[0],i=t.f
    b.meta.stage=6;b.frames.cid[0].fill(4);b.frames.state[0][i]=action;b.frames.age[0][i]=age;b.frames.air[0][i]=0
    const entries=itemAttackHistory(b)[i]
    assert.equal(entries.filter(e=>e.hits?.length).length,1)
    assert.equal(entries.find(e=>e.hits?.length).hits[0].damage,damage)
    assert.equal(t.s[0],state,'the recorded post-collision state is preserved')
  }
})
test('recorded charge-shot states damage the default block simulation',()=>{
  const weak=itemBundle(94,1),full=itemBundle(94,8),before=simulate(weak,4).lines.length
  assert.ok(simulate(weak,12).lines.length<before)
  assert.ok(simulate(full,12).lines.length<before)
  assert.equal(itemSpheres(full.items[0],0,0,full)[0].damage,25)
  assert.equal(itemSpheres(weak.items[0],0,0,weak)[0].damage,3)
  assert.ok(simulate(weak,325).lines.length>simulate(full,325).lines.length)
})

test('needle target flags distinguish ground materials from Brinstar supports',()=>{
  const b=itemBundle(79,0)
  assert.deepEqual(itemSpheres(b.items[0],0,0,b).map(h=>h.id),[0])
  b.meta.stage=6
  assert.deepEqual(itemSpheres(b.items[0],0,0,b).map(h=>h.id),[1,2,3])
})

test('Bob-omb chain reactions begin after collision and pause their commands in hitlag',()=>{
  const b=itemBundle(6,1),t=b.items[0]
  for(const key of ['x','y','d','vx','vy'])t[key]=Array(6).fill(t[key][0])
  t.s=[1,11,11,11,11,11];t.lifetime=[1390,80,80,80,79,77]
  assert.deepEqual(itemSpheres(t,1,0,b),[])
  assert.equal(itemSpheres(t,3,2,b)[0].damage,25)
  assert.deepEqual(itemSpheres(t,5,4,b),[])
})
test('terminal missile impact is retained and map collision wins',()=>{
  const b=itemBundle(95,0,0,0),t=b.items[0]
  Object.assign(t,{x:[0,2],y:[0,0],d:[1,1],vx:[1.3,0],vy:[0,0],s:[0,2]})
  const entry=itemAttackHistory(b)[6].find(e=>e.mapFrom)
  assert.ok(entry.hits.length)
  assert.deepEqual(itemEntryHits(entry,[[1,8,3,-10,3,10]]),[])
  assert.equal(itemEntryHits(entry,[]),entry.hits)
})

test('Link bomb damage uses the flight capsule before its DmgDealt explosion',()=>{
  const b=itemBundle(58,2,21.885923385620117,28.17536735534668),t=b.items[0]
  Object.assign(t,{x:[t.x[0],t.x[0]],y:[t.y[0],30.288166046142578],d:[1,1],vx:[0,0],vy:[2.1608,0],s:[2,5]})
  b.frames.cid[0].fill(6);b.frames.state[0][5]=110;b.frames.age[0][5]=12
  const entry=itemAttackHistory(b)[6][0]
  assert.equal(entry.hits[0].damage,4)
  assert.equal(itemEntryHits(entry,[])[0].damage,1)
  // A ceiling map impact happens earlier in the scheduler and instead uses
  // the explosion capsule on the transition frame.
  const mapped=itemAttackHistory(b)[6][0]
  assert.equal(itemEntryHits(mapped,[[1,2,40,31,0,31]])[0].damage,4)
})

test('boomerang release includes its item attachment offset',()=>{
  // Independent raw Item Update samples, Link standing on flat Yorster.
  const spawn=fighterDataFor(6).hitboxes[350].articleSpawns[0]
  assert.ok(Math.abs(spawn.pos[2]-16.628910064697266)<.0001)
  assert.ok(Math.abs(spawn.pos[1]-9.823956625368737)<.0001)
})

test('Young Link explosion advances with native lifetime across hitlag',()=>{
  // c27-younglink: explosion at 2482, first animation tick at 2487.
  const b=itemBundle(59,5,38.350337982177734,30.80878448486328),t=b.items[0]
  for(const key of ['x','y','d','vx','vy','s'])t[key]=Array(7).fill(t[key][0])
  t.lifetime=[80,80,80,80,80,79,78]
  assert.deepEqual(Array.from({length:7},(_,j)=>itemSpheres(t,j,j,b).length),[0,0,0,0,0,1,0])
})

test('boomerang DmgDealt retains the outgoing sweep on its return transition',()=>{
  // c27-younglink: the material hit precedes the recorded state3 switch.
  const b=itemBundle(61,2,-39.04829406738281,46.5611457824707),t=b.items[0]
  Object.assign(t,{x:[t.x[0],-36.571292877197266],y:[t.y[0],t.y[0]],s:[2,3],d:[1,1],vx:[2.524000644683838,2.4770007133483887],vy:[0,0]})
  const entry=itemAttackHistory(b)[6][0],hits=itemEntryHits(entry,[])
  assert.equal(hits[0].damage,7)
  assert.equal(entry.previous[0].x,t.x[0])
  assert.equal(entry.reset,false)
})

test('held item release includes the native grip overlay and inverse hand scale',()=>{
  // Independent native Item Update positions minus the fighter root, before
  // item physics. Standing, airborne and upward throws exercise RHaveN.
  for(const [cid,state,frame,x,y] of [
    [6,108,7,15.149219512939453,12.625547215342522],
    [6,114,6,-1.7124252319335938,25.556583404541016],
    [6,110,10,-.0016021728515625,23.805667877197266],
    [9,108,10,13.10427474975586,5.8063118904829025],
    [9,110,11,-.8739051818847656,23.15935230255127],
    [9,114,11,-.6751785278320312,17.63103485107422],
    [9,100,10,10.715131521224976,6.524929046630859],
  ]){
    const spawn=fighterDataFor(cid).hitboxes[state].articleSpawns.find(s=>s.kind==='held'&&s.frame===frame)
    assert.ok(spawn,`${cid}:${state}:${frame}`)
    assert.ok(Math.abs(spawn.pos[2]-x)<.0001,`release x ${cid}:${state}`)
    assert.ok(Math.abs(spawn.pos[1]-y)<.0001,`release y ${cid}:${state}`)
  }
})
test('unknown turnip faces gate actual material hits; attached G&W props stay inert',()=>{
  assert.ok(simulate(itemBundle(99,2,200,200),399)?.complete)
  assert.equal(simulate(itemBundle(99,2),20),null)
  for(const kind of [114,115,116,117,118,119,120,121,124]){
    const b=itemBundle(kind,0)
    assert.deepEqual(itemSpheres(b.items[0],0,0,b),[],`article ${kind}`)
    assert.ok(simulate(b,100)?.complete)
  }
  const tether=itemBundle(62,0)
  assert.equal(itemSpheres(tether.items[0],0,0,tether),null,'a runtime tether is not certified inert by its empty script')
})

test('a saturated native item record list cannot certify absent projectiles',()=>{
  const b=itemBundle(114,0)
  b.items=Array.from({length:15},()=>structuredClone(b.items[0]))
  assert.equal(simulate(b,10),null)
  const below=structuredClone(b);below.items.pop()
  assert.ok(simulate(below,10)?.complete)
})
test('copied Puff/Mewtwo motions and smash charge have numeric tables',()=>{
  for(const motion of ['PrSpecialN','MtSpecialNLoop','MtSpecialAirNLoop'])assert.ok(Object.values(fighterDataFor(4).hitboxes).some(m=>m.motion===motion),motion)
  const move=fighterDataFor(18).hitboxes[60],age=+Object.keys(move.frames)[0],h=attackSpheres(18,60,age,0,0,1)[0]
  assert.equal(materialDamage(h,move,0),h.damage)
  assert.ok(materialDamage(h,move,move.charge[1])>h.damage)
  const f={state:[[60,60,60,60]],cid:[[18,18,18,18]],age:[[move.charge[0],move.charge[0],move.charge[0],age]]}
  assert.deepEqual(smashChargeHistory(f),[[0,1,2,2]])
})

test('PK Fire spawn sweeps from the fighter ECB center across a slope',()=>{
  // Native c30-ness, index222. The uncorrected hand is below the slope.
  const frames={}
  for(const [k,v] of Object.entries({cid:8,state:356,x:-29.75,y:.00009999999747378752,air:0,dir:-1}))frames[k]=[[v,v]]
  frames.age=[[19,20]]
  const b={meta:{stage:16,n:2,start_frame:-123},frames}
  const lines=simulate(itemBundle(114,0),0).lines,step=unrecordedNessHistory(b)
  const shot=step(1,lines)[0].track
  assert.ok(Math.abs(shot.x[0]+41.77137756347656)<.00002)
  assert.ok(Math.abs(shot.y[0]-7.146477699279785)<.00002)
})

test('PK Fire pillar expands on age8 after its immediate command tick',()=>{
  // Native Inishie1: PK Fire hits at6162; the expanded pillar reaches the
  // third block at6170 and its collision disappears at6171.
  const b=itemBundle(67,0),t=b.items[0];t.lifetime=[93]
  assert.equal(itemSpheres(t,0,7,b).length,1)
  assert.equal(itemSpheres(t,0,8,b).length,2)
})

test('copied PK Flash fades at its native wall and ceiling corner',()=>{
  // C31 Island indices300..328: the first flight is bit-exact through
  // its compound map contact at308 and cannot become an explosion later.
  const n=29,frames={state:[[439,...Array(n-1).fill(440)]],age:[[15,...Array.from({length:n-1},(_,i)=>i)]]}
  for(const [k,v] of Object.entries({cid:4,x:-41.666839599609375,y:16.60300064086914,dir:1,air:1}))frames[k]=[Array(n).fill(v)]
  frames.x[0][0]=-41.68201446533203;frames.y[0][0]=16.704999923706055
  frames.pre_state=[frames.state[0].slice()]
  const step=unrecordedNessHistory({meta:{stage:16,n},frames}),lines=simulate(itemBundle(114,0),0).lines
  let shot
  for(let i=0;i<n;i++){
    const entries=step(i,lines)
    assert.equal(entries.some(e=>e.track?.t===146),false)
    shot??=entries.find(e=>e.track?.t===145)?.track
  }
  assert.equal(shot.x[7],-42.98782730102539)
  assert.equal(shot.y[7],32.50000762939453)
  assert.equal(shot.s[7],2)
  assert.equal(shot.x.length,27)
})

test('Dins Fire inherits the recorded charge and advances the explosion constructor',()=>{
  const b=itemBundle(108,0),parent=b.items[0],n=8
  for(const key of ['x','y','d','vx','vy'])parent[key]=Array(n).fill(parent[key][0])
  parent.s=[0,0,0,0,0,1,1,1]
  const explosion={...parent,t:109,f:parent.f+n}
  for(const key of ['x','y','d','vx','vy','s'])explosion[key]=[parent[key].at(-1)]
  explosion.s=[0];b.items.push(explosion)
  const hits=itemAttackHistory(b)[explosion.f].find(e=>e.track.t===109).hits
  assert.equal(hits[0].damage,4)
  assert.ok(Math.abs(hits[0].radius-3.093552)<.000001)
  assert.deepEqual(itemSpheres(parent,0,0,b),[])
  assert.equal(itemSpheres(explosion,0,0,b),null,'a truncated parent cannot establish charge')
})

test('needle spawn correction and macro RNG reproduce the native slope bounce',()=>{
  // Native c30-sheik indices2278..2280. ABS(Randi) consumes its argument
  // twice, followed by the six SetupBounce draws.
  const n=8,frames={}
  for(const [k,v] of Object.entries({cid:7,x:57.60440444946289,y:.00009999999747378752,air:0,dir:1,seed:0}))frames[k]=[Array(n).fill(v)]
  frames.state=[[341,342,344,344,344,344,344,344]]
  frames.pre_state=[frames.state[0].slice()];frames.age=[[0,0,0,1,2,3,4,5]]
  frames.seed[0][5]=4039999728;frames.seed[0][6]=4237689038
  const b={meta:{stage:16,n,start_frame:-123},frames},step=unrecordedNeedleHistory(b)
  const lines=simulate(itemBundle(114,0),0).lines,rows=[]
  for(let i=0;i<n;i++)rows.push(step(i,lines))
  const t=rows[5].find(e=>e.track).track
  assert.ok(Math.abs(t.y[0]-8.412605285644531)<.00002)
  assert.equal(rows[6].find(e=>e.beforeCeilingDraws).beforeCeilingDraws,9)
  assert.ok(Math.abs(t.x[2]-66.11359405517578)<.00002)
  assert.ok(Math.abs(t.y[2]-10.192605018615723)<.00002)
})

test('Green Missile launch can hit and enter End in the same recorded frame',()=>{
  // Native Inishie1 indices2782..2783: no recorded Fly frame intervenes.
  const frames={cid:[[17,17]],state:[[353,352]],age:[[3,0]],dir:[[1,1]],air:[[1,1]],x:[[0,2.0333333015441895]],y:[[33.54299545288086,34.10188293457031]]}
  const step=luigiMissileHistory({meta:{n:2},frames})
  step(0,0,[])
  const hits=step(0,1,[])
  assert.ok(hits.length>0)
  assert.ok(Math.abs(hits[0].damage-13.866666793823242)<.00001)
})

test('Thunder keeps its hitbox cleared across pose loops and air transitions',()=>{
  // Native Inishie1 c30-pikachu: command age9 clears the capsule; the
  // subsequent animation wrap at6119 does not create another attack.
  const ages=[0,1,8,9,0,1],states=[361,365,365,365,365,365],n=ages.length,frames={age:[ages],state:[states]}
  for(const [k,v] of Object.entries({cid:12,x:0,y:34,dir:1}))frames[k]=[Array(n).fill(v)]
  const step=thunderHitHistory({meta:{stage:19,n},frames})
  assert.ok(step(0,0).length)
  assert.equal(step.draws[0],fighterDataFor(12).hitboxes[361].thunderHit[1])
  assert.ok(step(0,1).length)
  assert.equal(step.draws[0],0)
  assert.ok(step(0,2).length)
  for(let i=3;i<n;i++)assert.deepEqual(step(0,i),[])
})
