import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { gunzipSync } from 'node:zlib'
import { METRICS } from './itemArt.js'

const root = fileURLToPath(new URL('../../../../../', import.meta.url))
register(new URL('../../../../../tools/liteaudit/loader.mjs', import.meta.url))
const { STAGES, STAGE_COVERAGE, collisionGeometry, moverSegments, randallPlatform } = await import('./meleeStages.js')
const { stageGeometryAt } = await import('./liteStageInference.js')
const { paintFrame } = await import('./litePaint.js')
const { simFor, registerStageSim } = await import('./stageSim/index.js')

function bundle(stage, start = 0, n = 1) {
  return { meta: { stage, start_frame: start, n, players: [] }, frames: { x: [], y: [], air: [], state: [] } }
}
function distance(x, y, s) {
  const [a,b,c,d] = s, dx = c-a, dy = d-b
  const t = Math.max(0, Math.min(1, ((x-a)*dx+(y-b)*dy)/(dx*dx+dy*dy || 1)))
  return Math.hypot(x-a-t*dx,y-b-t*dy)
}
function nearest(x,y,segs) { let d=Infinity; for (const s of segs) d=Math.min(d,distance(x,y,s)); return d }
function stats(values) {
  const finite=values.filter(Number.isFinite)
  return { n: values.length, missing: values.length-finite.length,
    within3: values.length ? values.filter(v=>v<=3).length/values.length : null,
    mean: finite.length ? finite.reduce((a,b)=>a+b,0)/finite.length : null,
    max: finite.length ? finite.reduce((a,b)=>Math.max(a,b),0) : null }
}
function context() {
  const strokes=[]; let points=[]
  return { canvas:{width:640,height:480},strokes,
    setTransform(){}, fillRect(){}, beginPath(){points=[]}, moveTo(x,y){points.push([x,y])},
    lineTo(x,y){points.push([x,y])}, closePath(){},fill(){},stroke(){strokes.push(points)},arc(){},
  }
}

test('all vanilla VS stages have coverage metadata; no adventure/mod IDs', () => {
  assert.equal(Object.keys(STAGE_COVERAGE).length,29)
  assert.equal(collisionGeometry(26,100),null)
  assert.equal(collisionGeometry(291,100),null)
  assert.equal(collisionGeometry(10,NaN),null)
})

test('bounded animation never repeats or freezes at a missing frame', () => {
  const c=STAGE_COVERAGE[23]
  for (const frame of [c.range[0]-1,c.range[1]+1,100000]) {
    const g=collisionGeometry(23,frame)
    assert.equal(g.covered,false);assert.equal(g.partial,true);assert.equal(g.lines.length,0)
  }
  assert.ok(collisionGeometry(23,c.range[0]).lines.length>0)
})

test('verified loop and arbitrary seeking are independent of call history', () => {
  const c=STAGE_COVERAGE[30]
  assert.equal(c.loop,499)
  const a=collisionGeometry(30,c.range[0]+100)
  assert.deepEqual(collisionGeometry(30,c.range[0]+100+c.loop*19),a)
  collisionGeometry(30,99999)
  assert.deepEqual(collisionGeometry(30,c.range[0]+100),a)
})

test('main silhouettes close and do not cross; collision floors exclude undersides', () => {
  const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
  for (const [id,st] of Object.entries(STAGES)) {
    if (!st.main.length) continue
    assert.ok(st.main.length>=4,`stage ${id} polygon`)
    assert.deepEqual(st.main[0],st.main.at(-1),`stage ${id} closed`)
    const p=st.main
    for(let i=0;i<p.length-1;i++)for(let j=i+2;j<p.length-1;j++){
      if(i===0&&j===p.length-2)continue
      const a=p[i],b=p[i+1],c=p[j],d=p[j+1]
      assert.ok(!(cross(a,b,c)*cross(a,b,d)<-1e-8&&cross(c,d,a)*cross(c,d,b)<-1e-8),`stage ${id} crossing ${i}/${j}`)
    }
  }
  const fd=collisionGeometry(32,100)
  assert.ok(fd.floors.every(s=>Math.abs(s[1])<.01&&Math.abs(s[3])<.01))
  assert.equal(fd.lines.filter(l=>l[1]&1).length,3)
})

test('simulator removes toggled base lines and suppresses fallback before paint', () => {
  assert.equal(simFor(31),null)
  const b=bundle(31,100),base=stageGeometryAt(b,0),id=base.lines[0][0]
  const remove=registerStageSim(31,()=>({replace:true,lines:[[id,1,1,2,3,2]],complete:true}))
  try {
    const g=stageGeometryAt(b,0)
    assert.deepEqual(g.floors,[[1,2,3,2]]);assert.equal(g.partial,false)
    const c=context();paintFrame(c,b,null,null,0,{S:1,ox:0,oy:0},1)
    assert.deepEqual(c.strokes,[[[1,-2],[3,-2]]])
  } finally {remove()}
  const untoggle=registerStageSim(31,()=>({toggledLines:[[id,false]],complete:true}))
  try {assert.ok(!stageGeometryAt(b,0).lines.some(l=>l[0]===id))} finally {untoggle()}
  assert.equal(simFor(31),null)
})

test('missing simulator result preserves recorded FoD/Stadium and unknown-stage fallback', () => {
  const b=bundle(2,100)
  b.stage_state={fod:[[0,0,20],[0,1,28]]}
  const remove=registerStageSim(2,()=>null)
  try {
    const g=stageGeometryAt(b,0)
    assert.ok(g.floors.some(s=>s[0]>0&&s[1]===16.125))
    assert.ok(g.floors.some(s=>s[0]<0&&s[1]===22.125))
  } finally {remove()}
  const u=stageGeometryAt(bundle(999),0)
  assert.equal(u.partial,true);assert.equal(u.lines.length,0)
})

test('legacy inferred surfaces disappear when an original-line-ID simulator takes over', () => {
  const b=bundle(2,100),base=collisionGeometry(2,100)
  const remove=registerStageSim(2,()=>({lines:[[0,257,-49,30,-21,30]],complete:true}))
  try {
    const g=stageGeometryAt(b,0)
    assert.equal(g.lines.length,base.lines.length+1)
    assert.ok(g.lines.every(l=>l[0]>=0))
    assert.deepEqual(g.lines.find(l=>l[0]===0),[0,257,-49,30,-21,30])
    assert.equal(g.partial,false)
  } finally {remove()}
})

function inside(polys,x,y){
  let w=0
  for(const p of polys)for(let i=0,j=p.length-1;i<p.length;j=i++){
    const [xi,yi]=p[i],[xj,yj]=p[j]
    if((yi>y)!==(yj>y)&&x<(xj-xi)*(y-yi)/(yj-yi)+xi)w+=yi>yj?1:-1
  }
  return w!==0
}

test('the stage body is traced from collision: under the floor, never under the underside', () => {
  // Battlefield: solid under the main floor; nothing below its underside, which
  // the old flat-underside silhouette filled down to its lowest point.
  const bf=stageGeometryAt(bundle(31,100),0)
  assert.ok(inside(bf.fills,0,-1)&&inside(bf.fills,-60,-1))
  assert.ok(!inside(bf.fills,50,-25)&&!inside(bf.fills,-50,-25))
  // A simulator replacing the lines (FoD, Stadium...) must not lose the fill.
  const base=collisionGeometry(2,100),remove=registerStageSim(2,()=>({lines:base.lines,replace:true,complete:true}))
  try {
    const fod=stageGeometryAt(bundle(2,100),0)
    assert.equal(fod.source,'simulator');assert.ok(inside(fod.fills,0,-1)&&inside(fod.fills,40,-1))
  } finally {remove()}
})

test('a grabbed or thrown fighter marks no floor under it on a partial stage', () => {
  // Unknown stage: partial, so grounded fighters leave the trail mark. Port 0
  // is thrown (241, captured) at y=7 with the thrower's grounded flag; port 1
  // really stands at y=0.
  const b=bundle(999,0,1)
  Object.assign(b.frames,{x:[[0],[30]],y:[[7],[0]],air:[[0],[0]],state:[[241],[14]],cat:[[4],[0]],cid:[[1],[1]],age:[[0],[0]],dir:[[1],[1]]})
  b.meta.players=[{},{}]
  const c=context();paintFrame(c,b,null,null,0,{S:1,ox:0,oy:0},1)
  assert.ok(!c.strokes.some(s=>s.length&&s.every(([,y])=>y===-7)),'no mark at the thrown fighter')
  assert.ok(c.strokes.some(s=>s.length===2&&s.every(([,y])=>y===0)&&s[0][0]===8&&s[1][0]===52),'the standing fighter keeps its mark')
})

test('the reflector is drawn with a corner straight up and is never turned by facing', () => {
  for (const dir of [1, -1]) {
    const b=bundle(999,0,1)
    Object.assign(b.frames,{x:[[100]],y:[[0]],air:[[0]],state:[[361]],cat:[[0]],cid:[[1]],age:[[3]],dir:[[dir]]})
    b.meta.players=[{}]
    const paths=[]; let pts=[]
    const c={canvas:{width:640,height:480},setTransform(){},fillRect(){},beginPath(){pts=[]},moveTo(x,y){pts.push([x,y])},
      lineTo(x,y){pts.push([x,y])},closePath(){},arc(){},ellipse(){},fill(){paths.push(pts)},stroke(){paths.push(pts)}}
    paintFrame(c,b,null,null,0,{S:1,ox:0,oy:0},1)
    // held from before the rows, so its clock is the action frame (3): pulse 1.0199;
    // centre HipN (-1.27, 5.62) model units along facing, x Fox's 0.96
    const R=8.2686*1.0199*0.96, cx=100+dir*-1.27*0.96, cy=-5.62*0.96
    const hex=paths.find(p=>p.length===6&&p.every(([x,y])=>Math.abs(Math.hypot(x-cx,y-cy)-R)<1e-6))
    assert.ok(hex,`outer edge facing ${dir}`)
    const angles=hex.map(([x,y])=>(Math.round(Math.atan2(cy-y,x-cx)*180/Math.PI)+360)%360).sort((p,q)=>p-q)
    assert.deepEqual(angles,[30,90,150,210,270,330])
  }
})

test('a blaster shot is a beam trailing from its head, as long as the game grows it', async () => {
  const { blasterScale } = await import('./litePaint.js')
  // Falco's laser read in RAM (playback Dolphin): speed 5, s = 0.444 a frame up to 3;
  // reflected on the frame before its velocity turns, then it grows again
  const vx=[5,5,5,5,5,5,5,5,5,-5,-5,-5], it={vx,vy:vx.map(()=>0)}
  const s=vx.map((_,k)=>Math.round(blasterScale(it,k)*1000)/1000)
  assert.deepEqual(s,[0.444,0.889,1.333,1.778,2.222,2.667,3,3,0,0.444,0.889,1.333])
  // painted: the white core runs from the head back 11.152 x s along the travel line
  const b=bundle(999,0,1)
  Object.assign(b.frames,{x:[[0]],y:[[0]],air:[[0]],state:[[14]],cat:[[0]],cid:[[1]],age:[[0]],dir:[[1]]})
  b.meta.players=[{}]
  b.items=[{t:54,f:0,x:[50],y:[20],s:[0],d:[1],vx:[7],vy:[0]},{t:54,f:-9,x:[0,0,0,0,0,0,0,0,0,0],y:Array(10).fill(-30),s:Array(10).fill(0),d:Array(10).fill(-1),vx:Array(10).fill(-7),vy:Array(10).fill(0)}]
  const segs=[]; let pts=[]
  const c={canvas:{width:640,height:480},setTransform(){},fillRect(){},beginPath(){pts=[]},moveTo(x,y){pts.push([x,y])},
    lineTo(x,y){pts.push([x,y])},closePath(){},arc(){},ellipse(){},fill(){},stroke(){segs.push({pts,style:c.strokeStyle,w:c.lineWidth})}}
  paintFrame(c,b,null,null,0,{S:1,ox:0,oy:0},1)
  const core=y=>segs.find(g=>g.style==='#ffffff'&&g.pts.length===2&&g.pts[0][1]===-y)
  // just fired at speed 7: s = 7 / 11.25
  const fresh=core(20); assert.ok(fresh,'fresh core')
  assert.ok(Math.abs(fresh.pts[0][0]-50)<1e-9&&Math.abs(fresh.pts[1][0]-(50-11.152*7/11.25))<1e-9)
  // nine frames old, flying left: full length 3, trailing to the right
  const old=core(-30); assert.ok(old,'old core')
  assert.ok(Math.abs(old.pts[0][0])<1e-9&&Math.abs(old.pts[1][0]-11.152*3)<1e-9)
})

test('a floor sunk into the stage body is hidden, as in game (FoD bottom, Randall under the stage)', async () => {
  const { buriedPlatform } = await import('./liteStageInference.js')
  const { drawRandall } = await import('./litePaint.js')
  const { registerStageDataLoader, ensureStageData } = await import('./stageData.js')
  registerStageDataLoader(id => JSON.parse(fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), 'data/stages', `${id}.json`), 'utf8')))
  await ensureStageData(8)
  const body=[[[-60,0],[60,0],[60,-40],[-60,-40]]]
  assert.equal(buriedPlatform(body,-50,-1.3,-20,-1.3),true)    // FoD side platform at the bottom
  assert.equal(buriedPlatform(body,-60,0,60,0),false)          // the top surface: open above
  assert.equal(buriedPlatform(body,20,22,50,22),false)         // a raised platform
  // Randall: drawn beside the stage (our cloud and his platform line), nothing
  // while he passes under it
  const drawn=f=>{const n={line:0,cloud:0};const c={setTransform(){},beginPath(){},moveTo(){},lineTo(){},arc(){},ellipse(){},
    fill(){n.cloud++},stroke(){if(c.strokeStyle==='#d7dcea')n.line++}};drawRandall(c,f,{S:1,ox:0,oy:0},1);return n}
  assert.deepEqual(drawn(601),{line:0,cloud:0})
  let up=null
  for (let f=0;f<4000&&up==null;f++) { const p=randallPlatform(f); if (p&&Math.abs(p.left[0]+p.right[0])/2>62) up=f }
  assert.ok(up!=null&&drawn(up).line===1&&drawn(up).cloud>0,'drawn beside the stage')
})

// no two edges of a polygon cross (adjacent edges share a vertex)
function simple(poly) {
  const n = poly.length, cross = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
  for (let i = 0; i < n; i++) for (let j = i + 2; j < n; j++) {
    if (i === 0 && j === n - 1) continue
    const [a, b, c, d] = [poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n]]
    if (cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0) return false
  }
  return true
}

test('Pokemon Stadium terrain is filled solid down to the base; the neutral side platforms stay lines', async () => {
  const { insideBody, buriedPlatform, interiorLine } = await import('./liteStageInference.js')
  const { registerStageDataLoader, ensureStageData } = await import('./stageData.js')
  registerStageDataLoader(id => JSON.parse(fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), 'data/stages', `${id}.json`), 'utf8')))
  await ensureStageData(3)
  // rock form completed at index 50 (Slippi transformation events: frame, event, form)
  const b=bundle(3,0,400); b.stage_state={stadium:[[10,2,6],[11,3,6],[20,4,6],[30,5,6],[50,6,6],[51,0,6]]}
  Object.assign(b.frames,{x:[[]],y:[[]],air:[[]],state:[[]]})
  const rock=stageGeometryAt(b,300)
  assert.ok(insideBody(rock.fills,-60,40),'under the rock top at y 75')
  assert.ok(insideBody(rock.fills,0,-20),'the base')
  assert.ok(!insideBody(rock.fills,-60,80),'above the rock')
  // its planks stay lines with open space under them: the upper slope over the
  // shelf, the shelf over the ramp; the ramp itself tops solid rock
  assert.ok(!insideBody(rock.fills,10,40),'under the upper slope')
  assert.ok(!insideBody(rock.fills,10,20),'under the shelf')
  assert.ok(insideBody(rock.fills,10,5),'under the ramp')
  assert.ok(!buriedPlatform(rock.fills,-1.2,27.8,22.5,27.8),'the shelf is drawn')
  // the base's inner walls are seams once the terrain stands over them
  assert.ok(interiorLine(rock.fills,-70,0,-70,-5))
  // mid-transformation (old rock sinking, new rock growing) every fill polygon
  // is a simple loop: a self-crossing one cancels itself out of the fill
  for (const i of [35, 60, 100, 160]) for (const poly of stageGeometryAt(b,i).fills) assert.ok(simple(poly),`frame ${i}`)
  // neutral: the side platform at y 25 is a line, nothing under it is solid
  const plain=bundle(3,0,10); plain.stage_state={stadium:[[100,2,6]]}
  Object.assign(plain.frames,{x:[[]],y:[[]],air:[[]],state:[[]]})
  const neutral=stageGeometryAt(plain,5)
  assert.ok(!insideBody(neutral.fills,-40,20)); assert.ok(insideBody(neutral.fills,0,-2))
})

test("items and effects at the game's sizes and places: missile, Fire Fox flames", async () => {
  const rec=()=>{const fills=[];let pts=[];const c={...context(),beginPath(){pts=[]},moveTo(x,y){pts.push([x,-y])},lineTo(x,y){pts.push([x,-y])},
    arc(x,y){pts.push([x,-y])},ellipse(x,y){pts.push([x,-y])},rect(){},clip(){},save(){},restore(){},fill(){fills.push([c.fillStyle,pts.slice()])}};return [c,fills]}
  // Samus's missile: nose along its velocity; exploded (state 3) it is hidden in game
  const b=bundle(31,0,1)
  Object.assign(b.frames,{x:[[90]],y:[[0]],air:[[0]],state:[[14]],cat:[[0]],cid:[[13]],age:[[0]],dir:[[1]]}); b.meta.players=[{}]
  b.items=[{t:95,f:0,x:[10],y:[20],s:[1],d:[-1],vx:[-3],vy:[0]},{t:95,f:0,x:[-40],y:[20],s:[3],d:[1],vx:[0],vy:[0]}]
  let [c,fills]=rec(); paintFrame(c,b,null,null,0,{S:1,ox:0,oy:0},1)
  const body=fills.find(f=>f[0]==='#848476')
  assert.ok(body&&Math.min(...body[1].map(p=>p[0]))<10-2.4&&Math.max(...body[1].map(p=>p[0]))<10+2.9,'missile nose to -x')
  assert.ok(!fills.some(f=>f[1].some(p=>Math.abs(p[0]+40)<6&&Math.abs(p[1]-20)<6)),'exploded missile hidden')
  // Fire Fox: charging, the flame stands at the fighter; travelling, the trail points back
  const fx=bundle(31,0,3)
  Object.assign(fx.frames,{x:[[0,3,6]],y:[[10,10,10]],air:[[1,1,1]],state:[[354,356,356]],cat:[[1,1,1]],cid:[[1,1,1]],age:[[5,1,2]],dir:[[1,1,1]]}); fx.meta.players=[{}]
  ;[c,fills]=rec(); paintFrame(c,fx,null,null,0,{S:1,ox:0,oy:0},1)
  const crown=fills.find(f=>f[0]==='#ffcf3a')
  assert.ok(crown&&Math.min(...crown[1].map(p=>p[1]))>=9.9,'charge flame stands on the fighter position')
  ;[c,fills]=rec(); paintFrame(c,fx,null,null,0,{S:1,ox:0,oy:0},1); paintFrame(c,fx,null,null,2,{S:1,ox:0,oy:0},1)
  const trail=fills.filter(f=>f[0]==='#ff7a24').pop()
  // the plume is drawn before its fighter, who stays readable inside it
  const plumeAt=fills.findIndex(f=>f[0]==='#ff7a24'), fighterAt=fills.findIndex(f=>f[1].length===1&&f[1][0][0]===6&&f[1][0][1]===10)
  assert.ok(plumeAt>=0&&fighterAt>plumeAt,`plume ${plumeAt}, fighter ${fighterAt}`)
  assert.ok(trail&&Math.min(...trail[1].map(p=>p[0]))<6-15&&Math.max(...trail[1].map(p=>p[0]))<6+15,'travel plume behind the motion (moving +x)')
  // on the hips (pivot 7.97 above the position, hips 2.98 back down the body), not 5.5 x scale
  const core=fills.filter(f=>f[0]==='#ffd36a').pop(), cy=core[1].map(p=>p[1])
  assert.ok(Math.min(...cy)<14.99&&Math.max(...cy)>14.99,'plume around the hips')
})

test('a held turnip is drawn in front of Peach', () => {
  const b=bundle(31,0,1)
  Object.assign(b.frames,{x:[[0]],y:[[0]],air:[[0]],state:[[14]],cat:[[0]],cid:[[9]],age:[[3]],dir:[[1]]}); b.meta.players=[{}]
  b.items=[{t:99,o:0,f:0,x:[2],y:[8],s:[4],d:[1],vx:[0],vy:[0]}]
  const order=[]; const c={...context(),fill(){order.push(c.fillStyle)}}
  paintFrame(c,b,null,null,0,{S:1,ox:0,oy:0},1)
  const T=METRICS.turnip, dot=order.findIndex(col=>col!=='#20263a'&&col!==T.leaves&&col!==T.bulbColour&&col!=='#2c2c24'), leaves=order.indexOf(T.leaves)
  assert.ok(dot>=0&&leaves>dot,`fighter ${dot}, turnip ${leaves}`)
})

test('projectiles as the game shows them: PK Thunder tail, Pikachu bolt, needle, charge shot, revival platform', () => {
  const rec=()=>{const fills=[],strokes=[];let pts=[];const c={...context(),beginPath(){pts=[]},moveTo(x,y){pts.push([x,-y])},lineTo(x,y){pts.push([x,-y])},
    arc(x,y,r){pts.push([x,-y,r])},ellipse(x,y){pts.push([x,-y])},fillRect(x,y,w,h){fills.push([c.fillStyle,[[x,-y],[x+w,-y-h]]])},rect(){},clip(){},save(){},restore(){},
    fill(){fills.push([c.fillStyle,pts.slice()])},stroke(){strokes.push([c.strokeStyle,pts.slice()])}};return [c,fills,strokes]}
  const b=bundle(32,0,4)
  Object.assign(b.frames,{x:[[60,60,60,60]],y:[[0,0,0,0]],air:[[0,0,0,0]],state:[[13,13,13,13]],cat:[[0,0,0,0]],cid:[[5,5,5,5]],age:[[0,1,2,3]],dir:[[1,1,1,1]]}); b.meta.players=[{}]
  b.items=[
    {t:70,o:0,f:0,x:[0,2,4,6],y:[20,20,20,20],s:[0,0,0,0],d:[1,1,1,1],vx:[0,0,0,0],vy:[0,0,0,0]},          // a tail piece, born at 0
    {t:81,o:0,f:0,x:[-20,-20,-20,-20],y:[150,100,40,35],s:[0,1,2,2],d:[1,1,1,1],vx:[0,0,0,0],vy:[0,-5,0,0],lifetime:[0,0,7,1]},
    {t:79,o:0,f:0,x:[30,32,34,36],y:[10,10,10,10],s:[0,0,0,0],d:[1,1,1,1],vx:[2,2,2,2],vy:[0,0,0,0]},
    {t:94,o:0,f:0,x:[-40,-38,-36,-34],y:[10,10,10,10],s:[8,8,8,8],d:[1,1,1,1],vx:[3,3,3,3],vy:[0,0,0,0]}]
  const at=i=>{const [c,fills,strokes]=rec(); paintFrame(c,b,null,null,i,{S:1,ox:0,oy:0},1); return [fills,strokes]}
  // the tail blinks: drawn on its even frames, from its position back to where it was 2 frames ago
  let [fills,strokes]=at(2)
  const tail=strokes.find(s=>s[0]==='#e7e7e7')
  assert.ok(tail&&Math.min(...tail[1].map(p=>p[0]))>=-0.01&&Math.max(...tail[1].map(p=>p[0]))<=4.01,'tail piece at age 2')
  assert.ok(!at(3)[1].some(s=>s[0]==='#e7e7e7'),'hidden on its odd frames')
  // the bolt: nothing at the cloud (state 0), 40 long falling, then 5 x lifetime left
  assert.ok(!at(0)[1].some(s=>s[0]==='#ffffff'&&s[1].some(p=>Math.abs(p[0]+20)<7)),'bolt hidden at the cloud')
  const bolt=at(1)[1].find(s=>s[0]==='#ffffff'&&s[1].some(p=>Math.abs(p[0]+20)<7)), by=bolt[1].map(p=>p[1])
  assert.ok(Math.max(...by)<=100.01&&Math.min(...by)>59&&Math.min(...by)<62,'falling bolt 40 long under its point')
  const short=at(2)[1].find(s=>s[0]==='#ffffff'&&s[1].some(p=>Math.abs(p[0]+20)<7)), sy=short[1].map(p=>p[1])
  assert.ok(Math.max(...sy)-Math.min(...sy)<=35.01,'stopping bolt shrinks to 5 x lifetime')
  // its last frames (5 left): a flat bright flash on the ground, no zigzag and no box
  const [lastFills,lastStrokes]=at(3)
  assert.ok(!lastStrokes.some(s=>s[0]==='#ffffff'&&s[1].some(p=>Math.abs(p[0]+20)<7)),'no squashed zigzag')
  assert.ok(lastFills.some(f=>f[0]==='#ffffff'&&f[1].length===1&&Math.abs(f[1][0][0]+20)<.01&&Math.abs(f[1][0][1]-32.5)<.01),'flash at the bolt foot')
  assert.ok(!lastFills.some(f=>f[0]==='#fff3a0'&&f[1].length===2),'no rectangle')
  // the needle: 2.1 long, centred 1.5 behind the item point
  ;[fills,strokes]=at(0)
  const needle=strokes.find(s=>s[0]==='#d7dcea'), nx=needle[1].map(p=>p[0])
  assert.ok(Math.abs(Math.min(...nx)-27.45)<.01&&Math.abs(Math.max(...nx)-29.55)<.01,'needle behind the item point')
  // a full charge shot (state 8 = level 7): rim 5.04 x 2
  const rim=fills.find(f=>f[0]==='#4f7dff')
  assert.ok(rim&&Math.abs(rim[1][0][2]-10.08)<.01,'charge shot rim')
  // respawning (RebirthWait): the platform under the fighter's feet, about 14 wide
  const deck=fills.find(f=>f[0]==='#1c1c31'), dx=deck[1].map(p=>p[0])
  assert.ok(Math.abs(Math.max(...dx)-Math.min(...dx)-14.26)<.05&&Math.abs((Math.max(...dx)+Math.min(...dx))/2-60)<.01,'revival platform')
})

test('a body reached from a wing is filled whole; the wing, a bridge and a deck are not', async () => {
  const { solidFills } = await import('./liteStageInference.js')
  // Collision runs with its solid side on the right: floors left->right.
  const hull=[[1,1,0,0,10,0],[2,4,10,0,10,-10],[3,2,10,-10,0,-10],[4,8,0,-10,0,0]]
  const wing=[[5,1,-20,5,0,0]]                       // ends on the hull's corner
  const fills=solidFills([...wing,...hull])
  assert.equal(fills.length,1)
  assert.ok(inside(fills,5,-5)&&!inside(fills,-10,1))
  // A floor bridging two bodies has nothing under it.
  const right=hull.map(([id,k,a,b,c,d])=>[id+10,k,a+30,b,c+30,d])
  const bridge=solidFills([...hull,...right,[30,1,10,0,30,0]])
  assert.ok(!inside(bridge,20,-1)&&inside(bridge,35,-1))
})

test("floors alone across a closed body's pit are its new top (Stadium mid-transformation)", async () => {
  const { solidFills } = await import('./liteStageInference.js')
  const body=[[1,1,-20,0,-10,0],[2,4,-10,0,-10,-5],[3,1,-10,-5,10,-5],[4,8,10,-5,10,0],[5,1,10,0,20,0],
    [6,4,20,0,20,-20],[7,2,20,-20,-20,-20],[8,8,-20,-20,-20,0]]
  const terrain=[[9,1,-10,0,0,3],[10,1,0,3,10,0]]
  const fills=solidFills([...body,...terrain])
  assert.ok(inside(fills,0,1)&&inside(fills,0,-10)&&!inside(fills,0,4))
})

test('fireballs are drawn at their hitbox size; held props are not drawn', async () => {
  const b=bundle(31,100)
  Object.assign(b.frames,{x:[[60]],y:[[60]],air:[[1]],state:[[29]],cat:[[1]],cid:[[17]],age:[[0]],dir:[[1]]})
  b.meta.players=[{}]
  b.items=[{t:105,o:0,f:0,x:[5],y:[20],d:[1],s:[0],vx:[1],vy:[0]},{t:75,o:0,f:0,x:[-5],y:[20],d:[1],s:[0],vx:[0],vy:[0]}]
  const arcs=[]; let path=[]
  const c={...context(),beginPath(){path=[]},arc(x,y,r){path.push([x,y,r])},fill(){arcs.push(...path.map(p=>[...p,c.fillStyle]))}}
  paintFrame(c,b,null,null,0,{S:1,ox:0,oy:0},1)
  // the core of Luigi's fireball model (-1.04, 2.47) r 1.2, spun -30 degrees on its first frame (vx > 0)
  assert.ok(arcs.some(([x,y,r,col])=>Math.abs(x-5.334)<.01&&Math.abs(y+22.659)<.01&&Math.abs(r-1.5)<.01&&col==='#c6ffb4'),'Luigi fireball (r 1.2, at least 1.5 px)')
  assert.ok(!arcs.some(([x,y])=>x===-5&&y===-20),'Falco blaster is part of the pose')
})

test("stage objects: the game's invisible hit volumes are not drawn, the rest take their ECB box", async () => {
  const { itemLook, HIDDEN, STAGE_ITEMS } = await import('./itemLooks.js')
  // every (stage, kind) the owner's replays carry is identified: a look, or hidden
  for (const [stage, kinds] of Object.entries(STAGE_ITEMS))
    for (const kind of Object.keys(kinds)) {
      const look = itemLook(+kind)
      assert.ok(look === HIDDEN || Array.isArray(look) || [234, 235].includes(+kind), `${stage}:${kind}`)
    }
  const b=bundle(8,100)
  Object.assign(b.frames,{x:[[60]],y:[[60]],air:[[1]],state:[[29]],cat:[[1]],cid:[[17]],age:[[0]],dir:[[1]]})
  b.meta.players=[{}]
  // a Shy Guy (GrSt.dat ECB 6/6/8/8 x scale .85) and a yaku volume (kind 160)
  b.items=[{t:210,o:-1,f:0,x:[10],y:[30],d:[1],s:[1]},{t:160,o:-1,f:0,x:[-10],y:[5],d:[1],s:[0]}]
  const shapes=[]; let path=[]
  const c={...context(),beginPath(){path=[]},arc(x,y,r){path.push(['arc',x,y,r])},ellipse(x,y,rx,ry){path.push(['ellipse',x,y,rx,ry])},
    moveTo(x,y){path.push(['pt',x,y])},lineTo(x,y){path.push(['pt',x,y])},fill(){shapes.push(...path.map(p=>[...p,c.fillStyle]))}}
  paintFrame(c,b,null,null,0,{S:1,ox:0,oy:0},1)
  // the Shy Guy is our own drawing in the game sprite's box (GrSt.dat, 11 x 9.6):
  // a red robe around the item point with the white mask forward, at its height
  const body=shapes.filter(p=>p[0]==='pt'&&p[3]==='#c4100c'), mask=shapes.filter(p=>p[0]==='pt'&&p[3]==='#ece8ec')
  const [bx0,bx1,by0,by1]=METRICS.shyGuy.box, mean=a=>a.reduce((s,v)=>s+v,0)/a.length
  assert.ok(body.length>10&&Math.min(...body.map(p=>p[1]))>10-3&&Math.max(...body.map(p=>p[1]))<10+6,'Shy Guy body')
  const shy=new Set(['#838b29','#5a5f1c','#0829a4','#c4100c','#ece8ec','#000000'])
  assert.ok(shapes.filter(p=>p[0]==='pt'&&shy.has(p[3])).every(p=>p[1]>=10+bx0-.01&&p[1]<=10+bx1+.01&&-p[2]>=30+by0-.01&&-p[2]<=30+by1+.01),'inside its box')
  assert.ok(mask.length&&mean(mask.map(p=>p[1]))>mean(body.map(p=>p[1]))+1&&Math.abs(mean(mask.map(p=>-p[2]))-29.4)<0.5,'Shy Guy mask in front')
  assert.ok(!shapes.some(p=>p[1]===-10&&p[2]===-5),'kind 160 has no model: nothing drawn')
  assert.ok(!shapes.some(p=>p[0]==='arc'&&p[3]===2),'no generic dot')
  // Onett: the same kind carries a car (GrOt.dat map_head group 3): our own car at
  // its size and colour, wheels on the road, while it drives; a parked one
  // (lane B state 0, not moving) is not drawn
  const onett=bundle(9,100)
  Object.assign(onett.frames,b.frames); onett.meta.players=[{}]
  onett.items=[{t:160,o:-1,f:0,x:[30],y:[0],d:[1],s:[2]},{t:160,o:-1,f:0,x:[-30],y:[0],d:[1],s:[0]}]
  const fills=[]; let pts=[]
  const oc={...context(),beginPath(){pts=[]},moveTo(x,y){pts.push([x,y])},lineTo(x,y){pts.push([x,y])},arc(){},ellipse(){},fill(){fills.push([oc.fillStyle,pts.slice()])}}
  paintFrame(oc,onett,null,null,0,{S:1,ox:0,oy:0},1)
  const taxi=fills.filter(f=>f[0]==='#cec14d').flatMap(f=>f[1]), wheels=fills.filter(f=>f[0]==='#1e1e1e').flatMap(f=>f[1])
  assert.ok(taxi.length,'the taxi (state 2) drawn in its body colour')
  const xs=taxi.map(p=>p[0]), ys=wheels.map(p=>-p[1])
  assert.ok(Math.abs(Math.min(...ys))<0.01&&Math.max(...xs)-Math.min(...xs)>20&&Math.max(...xs)-Math.min(...xs)<23,`taxi ${Math.min(...ys)} ${Math.max(...xs)-Math.min(...xs)}`)
  assert.ok(!fills.some(f=>['#0293c2','#bb5e9d','#232323'].includes(f[0])),'parked car (lane B, not moving) not drawn')
})

test('stage fills: bounded work on any collision set, traced once per distinct set', async () => {
  const { solidFills, cachedFills } = await import('./liteStageInference.js')
  const chain = (n, closed) => {
    const pts = Array.from({ length: n + 1 }, (_, i) => [i, Math.sin(i / 7) * 3])
    const lines = pts.slice(0, -1).map((p, i) => [i, 1, ...p, ...pts[i + 1]])
    if (closed) lines.push([n, 2, n, pts[n][1], n, -50], [n + 1, 2, n, -50, 0, -50], [n + 2, 2, 0, -50, 0, pts[0][1]])
    return lines
  }
  // 8,000 segments: no stack overflow, no quadratic retrace (was 94 ms at 1,000)
  for (const closed of [false, true]) {
    const lines = chain(8000, closed), t0 = performance.now()
    assert.equal(solidFills(lines).length, 1)
    assert.ok(performance.now() - t0 < 1000, 'bounded')
  }
  // past the step budget the stage fails closed to its outline (no fill)
  const loop = chain(50, true)
  assert.equal(solidFills(loop).length, 1)
  assert.deepEqual(solidFills(loop, { loopSteps: 10 }), [])
  // the same lines are traced once
  const lines = chain(200, true), first = cachedFills(lines)
  assert.equal(cachedFills(lines.map(l => [...l])), first)
  assert.notEqual(cachedFills(lines.map((l, i) => i ? [...l] : [l[0], l[1], l[2], l[3] + 0.001, l[4], l[5]])), first)
})

test('the camera contains the fighters and the platforms above them at every host shape', async () => {
  const { stepCamera, viewFromCam } = await import('./litePaint.js')
  // Dream Land neutral: both fighters on the floor; top platform at 51.4.
  const f={x:[[-20],[25]],y:[[0],[0]],state:[[14],[14]],cat:[[0],[0]]}
  for(const [w,h] of [[720,405],[615,250],[844,220],[390,338],[168,95],[1280,620]]){
    const cam={};stepCamera(cam,f,0,true);const v=viewFromCam(cam,w,h)
    const left=-v.ox/v.S,right=(w-v.ox)/v.S,top=v.oy/v.S,bottom=(v.oy-h)/v.S
    assert.ok(left<=-20-25&&right>=25+25,`${w}x${h} fighters in width`)
    assert.ok(top>=51.4+1&&bottom<=-10,`${w}x${h} top platform and floor in height`)
  }
})

const audit=process.env.STAGE_BAKE_AUDIT
test('every dumped frame: JS reconstruction, visibility, floor projection and real replay fit', {skip:!audit}, async () => {
  const report=JSON.parse(fs.readFileSync(path.join(audit,'report.json')))
  const baselinePath=path.join(audit,'baseline-stages.json')
  const baseline=fs.existsSync(baselinePath)?JSON.parse(fs.readFileSync(baselinePath)):null
  const output=[];const previews={}
  for(const row of report){
    if(row.error)continue
    const truth=JSON.parse(gunzipSync(fs.readFileSync(path.join(audit,`truth-${row.stage}.json.gz`))))
    const known=new Set(truth.known),neutral=new Set(truth.neutral),errors=[],floors=[],baselineDistances=[]
    const b=bundle(row.stage,truth.frames[0],truth.frames.length),shots=[]
    const snapshots=new Set(Array.from({length:6},(_,i)=>Math.floor(i*(truth.frames.length-1)/5)))
    let checked=0
    for(let i=0;i<truth.frames.length;i++){
      const frame=truth.frames[i],g=collisionGeometry(row.stage,frame),actual=new Map(g.lines.map(l=>[l[0],l]))
      const expected=new Map(truth.rows[i].map(l=>[l[0],l]))
      for(const id of known){
        const a=actual.get(id),e=expected.get(id)
        assert.equal(!!a,!!e,`stage ${row.stage} frame ${frame} line ${id} visibility`)
        if(!e)continue
        assert.equal(a[1],e[1],`stage ${row.stage} frame ${frame} line ${id} flags`)
        for(const k of [2,4]){
          const err=Math.hypot(a[k]-e[k],a[k+1]-e[k+1]);errors.push(err)
          assert.ok(err<=.021,`stage ${row.stage} frame ${frame} line ${id}: ${err}`)
        }
        checked++
      }
      for(const id of actual.keys())assert.ok(known.has(id)||neutral.has(id))
      // Use actual sampled frame IDs even when the source had duplicate rows.
      b.meta.start_frame=frame-i
      const drawing=stageGeometryAt(b,i)
      const old=baseline?.[row.stage],oldFloors=[]
      if(old){
        for(let k=0;k<old.main.length;k++){
          const a=old.main[k],c=old.main[(k+1)%old.main.length],dx=c[0]-a[0]
          if(dx>0&&Math.abs((c[1]-a[1])/dx)<=1.5)oldFloors.push([...a,...c])
        }
        for(const pf of old.platforms)oldFloors.push([...pf[0],...pf[1]])
      }
      for(const l of truth.rows[i])if(l[1]&1){
        for(const t of [0,.5,1]){
          const x=l[2]+t*(l[4]-l[2]),y=l[3]+t*(l[5]-l[3])
          floors.push(nearest(x,y,drawing.floors))
          if(old)baselineDistances.push(nearest(x,y,oldFloors))
        }
      }
      if(snapshots.has(i))shots.push({frame,main:drawing.main,lines:drawing.lines,truth:truth.rows[i],source:drawing.source})
      if(row.stage===8){
        const r=randallPlatform(frame),e=expected.get(0)
        assert.ok(nearest(r.left[0],r.left[1],[e.slice(2)])<.01)
      }
    }
    previews[row.stage]=shots
    const drawn=stats(floors),old=stats(baselineDistances)
    if(old.n)assert.ok(drawn.within3+1e-6>=old.within3,`stage ${row.stage}: grounded-surface coverage regressed`)
    output.push({stage:row.stage,checked_line_frames:checked,exact:stats(errors),drawn_floor:drawn,old_floor:old})
  }
  fs.writeFileSync(path.join(audit,'runtime-validation.json'),JSON.stringify(output,null,2))
  fs.writeFileSync(path.join(audit,'runtime-preview.json'),JSON.stringify(previews))
  const {deriveFromSlp}=await import('./liteDeriver/index.js')
  const corpus=JSON.parse(fs.readFileSync(path.join(root,'app/scratch/liteaudit/harness/corpus.json')))
  const games=corpus.games.filter(g=>g.eligible&&g.stage<33&&![2,3,8,28,31,32].includes(g.stage)),results=[]
  for(const game of games){
    try {
      const b=deriveFromSlp(fs.readFileSync(game.path)),f=b.frames,all=[],filtered=[],covered=[]
      for(let i=0;i<b.meta.n;i++){
        const g=stageGeometryAt(b,i)
        for(let p=0;p<f.x.length;p++){
          if(f.air[p][i])continue
          const d=nearest(f.x[p][i],f.y[p][i],g.floors);all.push(d)
          if(f.state[p][i]<14||f.cat?.[p][i]===4)continue
          filtered.push(d);if(g.covered)covered.push(d)
        }
      }
      results.push({id:game.id,stage:game.stage,path:game.path,all_grounded:stats(all),filtered:stats(filtered),covered:stats(covered)})
    } catch(error){results.push({id:game.id,stage:game.stage,error:String(error)})}
  }
  fs.writeFileSync(path.join(audit,'replays.json'),JSON.stringify(results,null,2))
  console.log('Dump evaluator:',output.length,'stages; real replay results:',JSON.stringify(results))
})
