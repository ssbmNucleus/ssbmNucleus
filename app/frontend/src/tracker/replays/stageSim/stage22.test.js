import test from 'node:test'
import assert from 'node:assert/strict'
import simulate, { initialState, advance, environment, stepSeed, arwingPosition } from './stage22.js'

test('route 2 honors the authored per-channel FObj start offsets', () => {
  // Independent seedB first active pose, after subtracting the roof vertex.
  const [x,y]=arwingPosition(1,0)
  assert.ok(Math.abs(x-242.0986)<.001)
  assert.ok(Math.abs(y-1202.6322)<.001)
})

test('Venom environmental collision windows are distinct from route restrictions', () => {
  assert.deepEqual(environment(3799),{blocked:false,limited:false,collision:false})
  assert.deepEqual(environment(4399),{blocked:true,limited:false,collision:false})
  assert.equal(environment(4400).collision,true)
  assert.equal(environment(6100).collision,false)
  assert.equal(environment(6810).limited,true)
  assert.equal(environment(9200).limited,false)
})

test('environment frame zero is evaluated in setup before the ship animation starts', () => {
  const n=26100,b={meta:{stage:22,start_frame:-123,n},frames:{seed:[Array(n).fill(0)]}}
  const terrain=idx=>simulate(b,idx).lines.some(l=>l[0]===57)
  for(const cycle of [2,0,1]){
    const base=9999*cycle
    assert.equal(terrain(base+4398),false)
    assert.equal(terrain(base+4399),true)
    assert.equal(terrain(base+6098),true)
    assert.equal(terrain(base+6099),false)
    assert.deepEqual(environment(base+6810),environment(6810))
  }
  // Ship AOBJ wraps independently, without resetting wait/type/bank history.
  const ship=idx=>simulate(b,idx).lines.filter(l=>l[0]<=18||l[0]>=41&&l[0]<=56)
  for(const idx of [0,998,4399,9998])assert.deepEqual(ship(idx),ship(idx+9999))
  assert.deepEqual(simulate(b,20150),simulate(structuredClone(b),20150))
})

test('scheduler waits without consuming randomness and starts the selected route', () => {
  const s=initialState(),next=advance(s,0)
  assert.equal(next.wait,599)
  assert.equal(next.plane,null)
  const spawned=advance({...s,wait:1},0)
  assert.equal(spawned.type,1)
  assert.ok(spawned.plane)
  assert.equal(s.wait,600)
  assert.equal(stepSeed(0),2531011)
})

test('an expired spawn timer remains pending through the blocked environment', () => {
  const blocked=advance({...initialState(),frame:4000,wait:0},0)
  assert.equal(blocked.wait,-1)
  assert.equal(blocked.plane,null)
  const resumed=advance({...blocked,frame:6100-123-1},0)
  assert.ok(resumed.plane)
  assert.equal(resumed.type,1)
})

test('bank/route simulation is deterministic under backward seeking', () => {
  const b={meta:{stage:22,start_frame:-123},frames:{seed:[Array.from({length:1400},(_,i)=>stepSeed(i))]}}
  simulate(b,1200)
  assert.deepEqual(simulate(b,300),simulate(structuredClone(b),300))
  assert.equal(simulate(b,300).complete,false)
  assert.equal(simulate({...b,frames:{}},300),null)
  assert.equal(simulate({...b,meta:{stage:22,start_frame:100}},0),null)
})
