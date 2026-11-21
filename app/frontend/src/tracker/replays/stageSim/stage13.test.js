import test from 'node:test'
import assert from 'node:assert/strict'
import simulate, {rngStep,seedWindow,sampleTrack,chooseDirection,dynamicKind,raftStep} from './stage13.js'

test('HSD LCG uses unsigned 32-bit multiplication and exposes zero as a seed', () => {
  assert.equal(rngStep(0),2531011)
  assert.equal(rngStep(1),2745024)
  assert.equal(rngStep(0x12345678),0xb3e97b5b)
})

test('priority-4 cursor uses the current frame even across online reseeds', () => {
  const bundle = {meta:{start_frame:-123,n:2},frames:{seed:[[0,0xffffffff]]}}
  const rng = seedWindow(bundle,-123)
  assert.equal(rng.int(65536),38)
  assert.equal(rng.valid,true)
  rng.float()
  assert.equal(rng.used,2)
  assert.equal(rng.valid,true)
  assert.equal(seedWindow(bundle,-124),null)
  assert.equal(seedWindow(bundle,-122).seed,0xffffffff)
})

test('HSD interpolation handles hold, linear, and tangent-only Hermite packets', () => {
  assert.equal(sampleTrack([[0,1,5,null],[10,1,9,null]],4),5)
  assert.equal(sampleTrack([[0,2,0,null],[10,2,20,null]],3),6)
  assert.equal(sampleTrack([[0,4,0,0],[10,4,10,0]],5),5)
  assert.equal(sampleTrack([[0,3,0,null],[10,5,null,2],[10,3,10,null]],5),2.5)
})

test('turtle direction rejects repetitions and respects the unusual weight order', () => {
  const draws = [3,4,6], rng = {int:()=>draws.shift(),valid:true}
  assert.equal(chooseDirection(rng,0,[4,0,2,1]),3)
  assert.equal(chooseDirection({int:()=>0,valid:true},0,[4,0,2,1]),1)
})

test('dynamic turtle edges change kind at the game thresholds', () => {
  assert.equal(dynamicKind(0,0,1,1),1)
  assert.equal(dynamicKind(0,0,1,2),8)
  assert.equal(dynamicKind(0,0,1,-2),4)
  assert.equal(dynamicKind(1,0,0,0),2)
})

test('missing seeds and a sliced prefix are unavailable', () => {
  assert.equal(simulate({meta:{stage:13,start_frame:-123,n:1},frames:{}},0),null)
  assert.equal(simulate({meta:{stage:13,start_frame:100,n:1},frames:{seed:[[1]]}},0),null)
})

test('raft contact weight tilts and slides away from the load; unloading eases back', () => {
  const empty = {tilt:0,slide:0,down:0}
  assert.deepEqual(raftStep(empty,[]),empty)
  const loaded = raftStep(empty,[{dx:-15,weight:100,landed:false}])
  assert.ok(loaded.tilt > 0 && loaded.slide > 0 && loaded.down < 0)
  const unloaded = raftStep(loaded,[])
  assert.ok(unloaded.tilt < loaded.tilt && unloaded.slide < loaded.slide && unloaded.down > loaded.down)
  const right = raftStep(empty,[{dx:15,weight:100,landed:false}])
  assert.equal(right.tilt,-loaded.tilt)
  assert.equal(right.slide,-loaded.slide)
})

test('default Great Bay adapter applies all fighter weights and follower raft contacts', () => {
  const make=(cid,following=false)=>{
    const n=4,frames={}
    for(const [k,v] of Object.entries({x:-130,y:4.5453596115112305,state:14,air:0,cid,age:0,dir:1,seed:1}))frames[k]=[Array(n).fill(v)]
    if(following){
      const row=Object.fromEntries(Object.entries(frames).map(([k,v])=>[k,[...v[0]]]))
      frames.fol=[{of:0,...row,seed_order:Array(n).fill(2)}]
      frames.seed_order=[Array(n).fill(1)];frames.x[0].fill(300);frames.cid[0].fill(10)
    }
    const items=[{t:221,f:0,x:Array(n).fill(43),y:Array(n).fill(200),s:Array(n).fill(0)}]
    return {meta:{stage:13,start_frame:-123,start_seed:1,n},frames,items}
  }
  for(let cid=0;cid<27;cid++){
    const b=make(cid)
    assert.notDeepEqual(simulate(b,1)?.lines[0],simulate(b,0)?.lines[0],`raft moves for cid ${cid}`)
  }
  assert.deepEqual(simulate(make(11,true),1),simulate(make(11),1))
  assert.notDeepEqual(simulate(make(5),1),simulate(make(15),1))
  const edge=make(15)
  edge.frames.x[0][0]=-137.10499572753906-.05
  assert.notDeepEqual(simulate(edge,1)?.lines[0],simulate(edge,0)?.lines[0],'isolated raft floor retains its endpoint tolerance')
})
