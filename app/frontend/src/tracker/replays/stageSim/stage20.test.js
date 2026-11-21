import test from 'node:test'
import assert from 'node:assert/strict'
import simulate,{birdoLines,initialSchedule,pidgitTurn} from './stage20.js'

test('Inishie II collision follows Birdo, never an egg with the same position',()=>{
  const birdo={t:233,x:[100,110],y:[20,30]}
  const a=birdoLines(birdo,0),b=birdoLines(birdo,1)
  assert.ok(a.length>0)
  for(let i=0;i<a.length;i++)for(let j=2;j<6;j++)assert.ok(Math.abs(b[i][j]-a[i][j]-10)<.00002)
  assert.equal(birdoLines({...birdo,t:236},0),null)
  assert.equal(birdoLines(birdo,-1),null)
  assert.equal(birdoLines(birdo,2),null)
})

test('Inishie II refuses an empty bundle',()=>{
  assert.equal(simulate({},0),null)
})

test('Inishie II initializes the shared setup cursor in controller order',()=>{
  const draws=[]
  assert.deepEqual(initialSchedule({int:n=>{draws.push(n);return 1}}),[51,601,601,601])
  assert.deepEqual(draws,[450,300,600,600])
})

test('Inishie II Pidgit distinguishes entry, mandatory turns, random turns and departure',()=>{
  const s={x:0,y:80,dx:0,dy:-1,anim:0,cycles:0,entering:true,exiting:false,leaving:false,age:100}
  const noDraw=()=>{throw Error('Unexpected RNG')}
  const entered=pidgitTurn(s,noDraw)
  assert.equal(entered.entering,false)
  assert.equal(entered.cycles,0)
  assert.equal(entered.y,79)
  assert.equal(pidgitTurn(entered,noDraw).anim,1)
  assert.equal(pidgitTurn({...entered,cycles:2},n=>{assert.equal(n,8);return 4}).anim,0)
  assert.equal(pidgitTurn({...entered,cycles:2},()=>5).anim,1)
  const departure=pidgitTurn({...entered,x:150,cycles:2},noDraw)
  assert.equal(departure.exiting,true)
  assert.equal(departure.leaving,true)
  assert.equal(departure.anim,0)
})

function bundle(n,items=[]) {
  const frames={}
  for(const [key,value] of Object.entries({x:0,y:0,air:0,state:14,age:0,cid:18,seed:0}))frames[key]=[Array(n).fill(value)]
  return {meta:{stage:20,start_frame:-123,start_seed:0,n},frames,items}
}

test('Inishie II seeking is stable and damaged Birdo fails closed',()=>{
  const b=bundle(2000),first=simulate(b,300)
  assert.ok(simulate(b,1800)?.complete)
  assert.deepEqual(simulate(b,300),first)
  first.lines[0][2]=999
  assert.notEqual(simulate(b,300).lines[0][2],999)
  const damaged=bundle(5,[{t:233,f:2,x:[100,100],y:[30,30],s:[0,8],vy:[0,0]}])
  assert.ok(simulate(damaged,2))
  assert.equal(simulate(damaged,3),null)
  assert.equal(simulate(damaged,4),null)
})

test('Inishie II does not guess the RNG tail after same-frame Birdo creation',()=>{
  // Derive the spawn index from the source setup cursor, not a capture frame.
  const r={seed:0,int(n){this.seed=(Math.imul(this.seed,214013)+2531011)>>>0;return Math.trunc(n*(this.seed>>>16)/65536)}}
  const spawn=initialSchedule(r)[3]+1
  const b=bundle(spawn+2,[{t:233,f:spawn,x:[180,179.6],y:[30,30],s:[0,0],vy:[0,0]}])
  assert.ok(simulate(b,spawn-1))
  assert.equal(simulate(b,spawn),null)
})
