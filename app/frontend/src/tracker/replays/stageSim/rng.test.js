import test from 'node:test'
import assert from 'node:assert/strict'
import {nextSeed,previousSeed,advanceSeed,random,setupCursor,frameCursor,lastPre,inputTailDraws} from './rng.js'

const make = () => ({meta:{n:2,start_seed:0},frames:{
  seed:[[1,2],[3,4]],seed_order:[[300,600],[200,500]],
  pre_state:[[14,14],[14,14]],state:[[212,14],[14,14]],age:[[0,8],[8,8]],cid:[[18,18],[1,1]],
  frame_seed:[[0,0xffffffff]],scene_frame:[[0,1]],
}})

test('HSD arithmetic, inverse and zero-range draw match the 32-bit stream',()=>{
  assert.equal(nextSeed(0x12345678),0xb3e97b5b)
  for(const s of [0,1,0xffffffff,0x80000000])assert.equal(previousSeed(nextSeed(s)),s)
  const r=random(0)
  assert.equal(r.int(0),0);assert.equal(r.seed,2531011)
  assert.equal(r.float(),(nextSeed(2531011)>>>16)/65536)
  assert.equal(advanceSeed(r.seed,-2),0);assert.equal(r.used,2)
  for(const value of [undefined,null,-1,1.5,0x100000000])assert.equal(random(value),null)
})

test('setup uses GameStart even when online first-pre equals it',()=>{
  const b=make();b.frames.seed[0][0]=0
  assert.equal(setupCursor(b).int(65536),38)
  assert.equal(setupCursor({meta:{}}),null)
})

test('last emitted pre wins over port order, including a later follower',()=>{
  const b=make()
  assert.equal(lastPre(b,0).seed,1)
  b.frames.fol=[{of:1,seed:[0,null],seed_order:[400,null],pre_state:[14,null],state:[14,null],cid:[11,null],age:[2,null]}]
  assert.equal(lastPre(b,0).seed,0);assert.equal(lastPre(b,0).follower,true)
  assert.equal(lastPre(b,1).seed,2)
  assert.equal(frameCursor(b,0).seed,0)
  assert.equal(frameCursor({meta:{n:1},frames:{seed:[[0],[0]]}},0),null)
})

test('input-tail table uses internal character, current pre/post entry and age',()=>{
  const b=make(),table={schema:1,tails:{18:{212:3}}}
  assert.equal(inputTailDraws(b,0,table),3)
  assert.equal(inputTailDraws(b,1,table),0)
  assert.equal(inputTailDraws(b,0,null),0)
  b.frames.age[0][0]=2;assert.equal(inputTailDraws(b,0,table),0)
  b.frames.age[0][0]=0;b.frames.pre_state[0][0]=212
  assert.equal(inputTailDraws(b,0,table),0)
})

test('priority 1/10 require an explicit known prefix; priority 4 never uses next-pre',()=>{
  const b=make();b.frames.state[0][0]=14
  assert.equal(frameCursor(b,0).seed,1)
  assert.equal(frameCursor(b,0,{extra:2}).seed,advanceSeed(1,2))
  assert.equal(frameCursor(b,0,{priority:1}),null)
  assert.equal(frameCursor(b,0,{priority:1,extra:2}).seed,advanceSeed(0,2))
  assert.equal(frameCursor(b,0,{priority:10}),null)
  assert.equal(frameCursor(b,0,{priority:10,extra:5}).seed,advanceSeed(1,5))
  assert.equal(frameCursor(b,0,{priority:2,extra:0}),null)
  assert.equal(frameCursor(b,0,{extra:-1}),null)
  assert.equal(frameCursor(b,2),null)
})
