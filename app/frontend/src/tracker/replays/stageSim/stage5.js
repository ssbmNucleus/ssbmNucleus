import { registerStageSimData, fighterFrames, supportedFighterHistory } from '../stageData.js'
let data
import {collisionLines,worldMatrices,transformJoint,sampleTrack} from './stage13.js'
import {floorContact} from './stage29.js'
import {cruiseSplinePoint} from './stage11.js'
import {frameCursor} from './rng.js'

const f=Math.fround,rad=d=>f(f(.017453292)*d)
let p
// grKongo_801D6AFC. Landing impulses are fixed angles; fighter weight is NOT
// used. Neighbour coupling reads the whole updated rotation array before any
// correction is applied. Fixed separator planks suppress coupling.
export function plankStep(previous,landings=[]) {
  const planks=previous.map((s,i)=>{
    let speed=f(s.speed+rad(p.xA4)*(landings[i]||0))
    const delta=f(s.angle-s.rest),limit=rad(p.x94)
    speed=f(.99*f(speed+(delta>limit?-limit:delta < -limit?limit:0)))
    speed=Math.max(-rad(p.x98),Math.min(rad(p.x98),speed))
    const angle=Math.max(-rad(p.x90),Math.min(rad(p.x90),f(s.angle+speed)))
    return {...s,angle,speed}
  })
  const correction=planks.map((s,i)=>{
    let sum=0
    if(!s.fixed)for(const n of [planks[i-1],planks[i+1]])if(n && !n.fixed){
      const delta=f(n.angle-s.angle),limit=rad(p.x9C)
      if(delta>limit)sum=f(sum+f(p.xA0*f(delta-limit)))
      else if(delta < -limit)sum=f(sum+f(p.xA0*f(delta+limit)))
    }
    return sum
  })
  return planks.map((s,i)=>({...s,angle:f(s.angle+correction[i])}))
}

// fn_801D7700 selects a plank by x over vertices 29..26, even near an edge.
export function landingPlank(x,left,right) {
  return Math.max(0,Math.min(14,Math.trunc((x-left)/((right-left)/15))))
}

// Main ground 10 precedes barrel 5 in priority-4 creation order. Every hazard
// choice and its synchronous spawn draw share this cursor. Barrel capture,
// rotation and speed draws happen afterwards; the next pass re-anchors at
// the current input hook, which already includes them. They are not a prefix
// to this controller and the barrel has no MapLines.
export function hazardStep(previous,rng,boxes=false) {
  const s={...previous,event:null}
  if(s.timer>0)s.timer--
  if(s.timer!==0)return s
  let roll=f(rng.float()*f(p.x10+f(p.x8+(boxes?p.xC:0))))
  s.timer=Math.trunc(f(f(p.x4-p.x0)*rng.float()+p.x0))
  let kind,group
  roll=f(roll-p.x8)
  if(roll<0)kind=1
  else {
    roll=f(roll-(boxes?p.xC:0))
    if(roll<0)kind=2
    else {
      roll=f(roll-f(p.x10*p.x18))
      if(roll<0){kind=3;group=rng.int(2)?1:2}
      else {roll=f(roll-f(p.x10*f(1-p.x18)));if(roll<0){kind=3;group=7+rng.int(3)}else return s}
    }
  }
  if(s.last===kind&&rng.float()>p.x1C)return s
  s.last=kind
  // The synchronous frame-zero particle is bank30/30003 (kind=0,
  // random=-1): hsd_8039F05C does NOT draw before the root-X randomization.
  if(kind===3)s.event={kind,group,x:f((group===1||group===7?45:group===8?20:9)*rng.float()+(group===1||group===7?-15:group===8?-10:0))}
  else s.event={kind,route:rng.int(3)}
  return s
}

function hazardMatrices(o) {
  const anim=data.models[o.group].animations[o.phase===2?1:0]
  return worldMatrices(data,o.group,o.phase===2?1:0,Math.min(o.age,anim.end),{x:o.x,override:(j,r,s,t)=>{
    const sp=anim.splines[j+1]
    if(sp){const keys=anim.tracks[j+1].find(([k])=>k===4)[1],q=cruiseSplinePoint(sp,sampleTrack(keys,Math.min(o.age,anim.end)))
      for(let k=0;k<3;k++)t[k]=q[k]*sp.scale[k]+sp.translate[k]
    }
  }})
}

// 801D6668 measures its increment using arc-length samples, but 801C4B50
// places the carrier with splGetSplinePoint's uniform parameter.
export function carrierPoint(sp,u) {
  const scaled=f(Math.max(0,Math.min(1,u))*(sp.n-1)),seg=Math.min(sp.n-2,Math.floor(scaled)),a=f(scaled-seg),b=f(1-a)
  const weights=[b*b*b/6,(4+3*a**3-6*a*a)/6,(3*(-(a**3)+a*a+a)+1)/6,a**3/6]
  return [0,1,2].map(k=>f(weights.reduce((v,w,j)=>v+w*sp.points[seg+j][k],0)))
}

const rests=[.06981317,0,-.05235988,-.10471976,-.13962634,-.15707964,-.20943952,-.23561944,-.18325958,-.1308997,-.07853982,-.02617994,0,.05235988,.10471976].map(f)
const bones=[8,9,10,23,24,25,26,27,28,29,30,31,32,7,45]
// Nana's joined Squall Hammer Coll copies Popo's position/CollData through
// ft_800849EC; it does not call mpCollEnd. After separation that callback
// offsets her X by at least 1.5u and resumes her own floor tests.
export function copiedPartnerContact(bundle, frames, port, idx) {
 const parent=bundle.frames.fol?.[port-bundle.frames.x.length]?.of
 return parent!=null && frames.cid[port][idx]===11 &&
   [359,360].includes(frames.state[port][idx]) &&
   [344,346].includes(frames.state[parent][idx]) &&
   frames.x[port][idx]===frames.x[parent][idx] && frames.y[port][idx]===frames.y[parent][idx]
}
function buildFloor(b){
 const frames=fighterFrames(b)
 let planks=rests.map(rest=>({rest,angle:rest,speed:0,fixed:false})),previous=[],attached=[{angle:0,speed:0,z:0},{angle:0,speed:0,z:0}],rows=[]
 planks=plankStep(planks)
 const initialHeights=planks.map(s=>f(37.8*f(Math.tan(-s.angle))))
 for(let j=0;j<2;j++){const k=j?12:2;attached[j].z=Math.max(-rad(p.xAC),Math.min(rad(p.xAC),f(Math.PI/4*(.5*f(f(f(initialHeights[k]-initialHeights[k-1])/6)+f(f(initialHeights[k+1]-initialHeights[k])/6))))))}
 for(let i=0;i<b.meta.n;i++){
  const landings=Array(15).fill(0)
  for(let port=0;port<frames.x.length;port++)if(i>84&&frames.air[port][i-2]&&!frames.air[port][i-1]&&!copiedPartnerContact(b,frames,port,i-1)&&previous.some(l=>l[0]>=39&&l[0]<=69&&floorContact(frames,port,i-1,l)))landings[landingPlank(frames.x[port][i-1],data.local[29][0],data.local[26][0])]++
  planks=plankStep(planks,landings)
  const heights=planks.map(s=>f(37.8*f(Math.tan(-s.angle)))),vertices=data.initial.map(v=>v.slice())
  for(let j=0;j<15;j++)for(const id of [40+j*2,...(j===0?[39]:j===14?[69]:[])])for(const v of data.lines[id])vertices[v]=[data.local[v][0],f(data.local[v][1]+heights[j])]
  for(let j=0;j<2;j++){
   const k=j?12:2,a=attached[j],z=Math.max(-rad(p.xAC),Math.min(rad(p.xAC),f(Math.PI/4*(.5*f(f(f(heights[k]-heights[k-1])/6)+f(f(heights[k+1]-heights[k])/6))))))
   if(Math.abs(f(z-a.z))>rad(p.xB0))a.speed=-f(z-a.z)
   a.z=z
   if(a.angle>0)a.speed=f(a.speed-(a.speed>0?rad(p.xB4):f(rad(p.xB4)/2)))
   else if(a.angle<0)a.speed=f(a.speed+(a.speed<0?rad(p.xB4):f(rad(p.xB4)/2)))
   a.angle=f(a.angle+a.speed)
   const limit=rad(f(p.xB8-rad(p.xAC)))
   if(Math.abs(a.angle)>limit){a.angle=Math.sign(a.angle)*limit;a.speed=0}
   else if(Math.abs(a.angle)<rad(p.xB4)&&Math.abs(a.speed)<rad(p.xB4)){a.angle=0;a.speed=0}
  }
  const m=worldMatrices(data,10,0,i%299,{override:(j,r)=>{
   const k=bones.indexOf(j);if(k>=0)r[0]=planks[k].angle
   if(j===11||j===33){const a=j===11?0:1;r[0]=f(planks[a?12:2].angle*f(f(rad(p.xA8)/rad(p.x90))-1));r[2]=attached[a].z}
   if([19,13].includes(j))r[2]=attached[0].angle
   if([43,40].includes(j))r[2]=attached[1].angle
  }})
  for(const j of [2,3,5,6])transformJoint(data,vertices,j,m[data.mapping[j]+1])
  previous=collisionLines(data,vertices,data.joints.map((_,j)=>j>=2)).map(l=>l.map((v,k)=>k>=2?f(v):v));rows.push(previous)
 }
 return rows
}

const cache=new WeakMap()
function buildHazards(b,floors,boxes) {
  const frames=fighterFrames(b)
  const rows=floors.map(lines=>lines.slice()),objects=[]
  let schedule={timer:-1,last:-1}
  for(let i=0;i<rows.length;i++) {
    const rng=frameCursor(b,i)
    if(!rng){rows.length=i;break}
    if(i===84){
      // Ordinary VS READY: priority-0 light/empty scene/zako work has no
      // draws. if_802F73C4 -> fn_8016B7F8 -> fn_801D542C is the first draw.
      const ready=frameCursor(b,i,{priority:1,extra:0})
      if(!ready){rows.length=i;break}
      schedule.timer=Math.trunc(f(f(p.x4-p.x0)*ready.float()+p.x0))
    }
    schedule=hazardStep(schedule,rng,boxes)
    const spawned=(b.items||[]).filter(t=>t.f===i&&(t.t===218||t.t===1))
    if(spawned.length&&(!schedule.event||schedule.event.kind===3||spawned.length!==1||spawned[0].t!==(schedule.event.kind===1?218:1))){rows.length=i;break}
    for(const o of objects)if(o.group){o.age++;o.m=hazardMatrices(o);o.pos=[o.m[3][3],o.m[3][7],o.m[3][11]]}
    if(schedule.event){
      const e=schedule.event
      if(e.kind===3){
        const o={...e,age:0,phase:0,timer:0,contact:0};o.m=hazardMatrices(o);o.pos=[o.m[3][3],o.m[3][7],o.m[3][11]];objects.push(o)
      }else {
        // Crate carrier detachment has additional item callbacks. Preserve
        // the fallback when an item-enabled rule actually creates one.
        if(e.kind===2){rows.length=i;break}
        const item=(b.items||[]).find(t=>t.f===i&&t.t===(e.kind===1?218:1))
        if(!item){rows.length=i;break}
        objects.push({...e,start:i,item,u:0,pos:cruiseSplinePoint(data.itemSplines[e.route],0)})
      }
    }
    for(const o of objects){
      if(o.dead)continue
      if(!o.group){
        if(i>=o.start+o.item.x.length){o.dead=true;continue}
        const sp=data.itemSplines[o.route]
        if(f(o.u+.001)<=1){
          const a=cruiseSplinePoint(sp,o.u),c=cruiseSplinePoint(sp,f(o.u+.001))
          const length=f(Math.hypot(...a.map((v,k)=>f(v-c[k]))))
          if(length>0)o.u=Math.min(1,f(o.u+f(f(.001)*f(p.x14/length))))
        }
        o.pos=carrierPoint(sp,o.u)
      }else if(o.group>=7){if(o.age>=data.models[o.group].animations[0].end)o.dead=true}
      else if(o.phase===0){
        if(o.age>=data.models[o.group].animations[0].end){o.phase=1;o.lines=logLines(o)}
      }else if(o.phase===1){
        const contact=rows[i-1]?.some(l=>o.lines.some(q=>q[0]===l[0])&&frames.x.some((_,port)=>
          i>1&&!frames.air[port][i-2]&&floorContact(frames,port,i-1,l)))
        o.contact=contact?o.contact+1:0;o.timer++
        if(o.contact>p.x88||o.timer>p.x8C||objects.some(other=>other!==o&&!other.dead&&other.pos[2]-o.pos[2]<-100&&other.pos[2]-o.pos[2]>-150&&(other.pos[0]-o.pos[0])**2<6400)){
          o.phase=2;o.age=0;o.m=hazardMatrices(o);o.pos=[o.m[3][3],o.m[3][7],o.m[3][11]]
        }
      }else if(o.age>=data.models[o.group].animations[1].end)o.dead=true
    }
    rows[i].push(...objects.flatMap(o=>!o.dead&&o.phase===1?o.lines:[]))
    for(let j=objects.length-1;j>=0;j--)if(objects[j].dead)objects.splice(j,1)
  }
  return rows
}

function build(b) {
  const floors=buildFloor(b)
  // The bundle does not carry the item switch. Track both source rule states
  // until the recorded Klaptrap/box spawns distinguish them. Emit a frame
  // only when every still-consistent rule state has the same collision.
  const variants=[false,true].map(boxes=>buildHazards(b,floors,boxes))
  return floors.map((_,i)=>{
    const possible=variants.filter(v=>i<v.length).map(v=>v[i])
    if(!possible.length)return null
    const a=possible[0]
    return possible.every(v=>v.length===a.length&&v.every((line,j)=>line.every((x,k)=>x===a[j][k])))?a:null
  })
}

function logLines(o){
  const j=o.group-1,vertices=data.initial.map(v=>v.slice())
  transformJoint(data,vertices,j,o.m[o.group===1?1:3])
  return collisionLines(data,vertices,data.joints.map((_,k)=>k===j)).map(l=>l.map((v,k)=>k>=2?f(v):v))
}

export default function simulate(bundle,idx){
  if(!data||!supportedFighterHistory(bundle,idx,5))return null
  let rows=cache.get(bundle)
  if(!rows){rows=build(bundle);cache.set(bundle,rows)}
  return rows[idx]?{lines:rows[idx].map(l=>l.slice()),replace:true,complete:true}:null
}

registerStageSimData(5, value => {
  data = value
  p=data.params
})
