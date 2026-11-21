import { registerStageSimData, supportedFighterHistory } from '../stageData.js'
let data
import { collisionLines } from './stage13.js'

const f = Math.fround
// These deterministic callbacks do not read HSD_Rand. Guest/background RNG
// in groldyoshi.c is unrelated to the cloud collision.
export function supportedHistory(bundle, idx, stage) {
  // Shared callers such as Inishie2 have no fighter-contact loop. They can
  // use the complete leader/follower history and rng.js's final pre anchor.
  // Keep this stage's own guard unchanged until its cloud contact adapter
  // also includes followers; accepting them while ignoring Nana is unsafe.
  if (stage !== 29) return supportedFighterHistory(bundle, idx, stage)
  const n = bundle?.meta?.n, frames = bundle?.frames
  return Number(bundle?.meta?.stage) === stage && bundle.meta.start_frame === -123
    && Number.isInteger(idx) && idx >= 0 && idx < n && frames?.x?.length > 0
    && !frames.fol?.length && ['x','y','air','state','age','cid'].every(k =>
      frames[k]?.length === frames.x.length && frames[k].every(a => a?.length === n))
}

// mpCollEnd invokes Cb1 for floor AND edge contacts. A grounded post position
// identifies an ordinary floor contact; ledge/corner callbacks need ECB data.
export function floorContact(frames, port, idx, line) {
  if (idx < 0 || frames.air[port][idx] || frames.state[port][idx] <= 10) return false
  const [,flags,x0,y0,x1,y1] = line, x = frames.x[port][idx], y = frames.y[port][idx]
  if (!(flags & 1) || x < Math.min(x0,x1) || x > Math.max(x0,x1) || x0 === x1) return false
  return Math.abs(y-(y0+(y1-y0)*(x-x0)/(x1-x0))) < .002
}

export function initialCloud() { return { state:0, timer:0, sag:0, speed:0, active:true, age:0 } }

// grOldYoshi_8020F31C: brake inside stopping distance, then clamp velocity.
export function cloudVelocity(speed, position, target, p = data.params) {
  const time = f(Math.abs(speed)/p.accel)
  const stopping = f(f(time*f(-p.accel*.5*time))+f(time*Math.abs(speed)))
  if (Math.abs(f(target-position)) < stopping && ((target>position && speed>0) || (target<position && speed<0))) {
    if (speed>0) speed=f(speed-p.accel)
    else if (speed<0) speed=f(speed+p.accel)
  } else if (target>position) speed=f(speed+p.accel)
  else if (target<position) speed=f(speed-p.accel)
  return Math.max(-p.speed,Math.min(p.speed,speed))
}

// grOldYoshi_8020EC10. Contact is the previous priority-6 Cb1 latch. Leaving
// resets the load timer; multiple fighters still contribute just one boolean.
export function cloudStep(previous, contact, p = data.params) {
  const s = {...previous}
  if (s.state===0) {
    s.speed=cloudVelocity(s.speed,s.sag,contact?p.sag:0,p)
    s.sag=contact?Math.min(p.sag,f(s.sag+s.speed)):Math.max(0,f(s.sag+s.speed))
    if (contact) {
      if (s.timer++ > p.loaded) {s.state=1;s.timer=0;s.age=0}
    } else s.timer=0
  } else if (s.state===1) {
    if (s.timer===p.disable) s.active=false
    s.timer=(s.timer+1)&255
    // grAnime_801C7FF8 only requests the animation. HSD_AObjInterpretAnim
    // consumes AOBJ_FIRST_PLAY at frame zero on the next priority-1 pass,
    // so an end frame of 99 needs 100 passes (including frame zero).
    if (s.age++>=p.vanishEnd) {s.state=2;s.timer=0;s.active=false}
  } else if (s.state===2) {
    if (s.timer++>p.wait) {s.state=3;s.timer=0;s.age=0}
  } else if (s.state===3) {
    if (s.timer===p.enable) s.active=true
    s.timer=(s.timer+1)&255
    if (s.age++>=p.returnEnd) {s.state=0;s.timer=0}
  }
  return s
}

const caches=new WeakMap()
function build(bundle) {
  let clouds=Array.from({length:3},initialCloud)
  const rows=[], neutral=collisionLines(data,data.initial,[true,true,true,true])
  let previousLines=neutral
  for(let i=0;i<bundle.meta.n;i++) {
    clouds=clouds.map((c,j)=>cloudStep(c,previousLines.some(l =>
      data.lines[l[0]][0]>=data.joints[j][0] && data.lines[l[0]][0]<data.joints[j][0]+data.joints[j][1]
      && bundle.frames.x.some((_,p)=>floorContact(bundle.frames,p,i-1,l)))))
    const vertices=data.initial.map(v=>v.slice())
    for(let j=0;j<3;j++) {
      const [start,n]=data.joints[j]
      for(let k=start;k<start+n;k++) vertices[k][1]=f(vertices[k][1]-clouds[j].sag)
    }
    previousLines=collisionLines(data,vertices,[...clouds.map(c=>c.active),true])
    rows.push(previousLines)
  }
  return rows
}

export default function simulate(bundle,idx) {
  if (!data) return null
  if(!supportedHistory(bundle,idx,29)) return null
  let rows=caches.get(bundle)
  if(!rows){rows=build(bundle);caches.set(bundle,rows)}
  return {lines:rows[idx].map(l=>l.slice()),replace:true,complete:true}
}

registerStageSimData(29, value => {
  data = value
})
