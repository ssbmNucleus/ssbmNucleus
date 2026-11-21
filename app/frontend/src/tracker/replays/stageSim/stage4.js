import { registerStageSimData, fighterFrames, supportedFighterHistory as supportedHistory } from '../stageData.js'
let data
import {collisionLines} from './stage13.js'
import {floorContact} from './stage29.js'
import {frameCursor} from './rng.js'

const f=Math.fround
let p
export function initialPlatform(){return {state:0,timer:Math.trunc(p.x38),position:p.x18?p.x14:p.x10}}

// Fighter_procMap (priority 6) precedes damage resolution (priority 14).
// A grounded fighter hit into the air still delivered this frame's Cb1.
// Require a fresh damage entry, increased percent, an unchanged grounded
// pre-action and a root still exactly on the floor; ongoing airborne hitlag
// does not keep loading the platform.
export function platformContact(frames,port,idx,line) {
  // mpLib_8004DD90_Floor retains an isolated floor within .1 of its edge;
  // the platform still receives Cb1 before the following teeter clamps X.
  if(line[3]===line[5]){
    line=line.slice()
    if(line[2]<line[4]){line[2]-=.1;line[4]+=.1}
    else {line[2]+=.1;line[4]-=.1}
  }
  if(floorContact(frames,port,idx,line))return true
  if(idx<=0 || !frames.air[port][idx] || frames.air[port][idx-1]
    || frames.state[port][idx]<75 || frames.state[port][idx]>91
    || frames.pre_state?.[port]?.[idx]!==frames.state[port][idx-1]
    || !(frames.pct?.[port]?.[idx]>frames.pct?.[port]?.[idx-1]))return false
  const [,flags,x0,y0,x1,y1]=line,x=frames.x[port][idx],y=frames.y[port][idx]
  return !!(flags&1) && x0!==x1 && x>=Math.min(x0,x1) && x<=Math.max(x0,x1)
    && Math.abs(y-(y0+(y1-y0)*(x-x0)/(x1-x0)))<.002
}

// grCastle_801CDC44: Cb1 sums integer fighter weight, but vanilla x20/x2C
// are zero: any fighter contact selects the same .5 model-unit motion.
export function platformStep(previous,weight=0) {
  const s={...previous}
  switch(s.state) {
    case 0: if(weight>0){if(s.timer++>p.x38)s.state=2}else{s.timer=0;s.state=1}break
    case 1: if(weight>0){s.timer=0;s.state=0}else if(s.timer++>p.x3C)s.state=3;break
    case 2: if(weight>0)s.position=Math.min(p.x10,f(s.position+Math.min(p.x28,f(weight*p.x20+p.x24))))
      else{s.timer=0;s.state=1}break
    case 3: if(weight>0){s.timer=0;s.state=0}
      else s.position=Math.max(p.x14,f(s.position-Math.min(p.x34,f(weight*p.x2C+p.x30))))
  }
  return s
}

// grCastle_801CFBD4: collision enables only at full growth, and disables
// on the FIRST shrink tick. grCastle_801CDF54 supplies the first Bullet Bill's
// root, so a nearby BILL (not a fighter) blocks the beginning of growth.
export function switchBlockStep(previous,grow,near=false) {
  const s={...previous}
  if(grow) {
    if(s.hidden){if(!near){s.hidden=false;s.scale=.0001}return s}
    s.scale=Math.min(1,f(s.scale+p.grow));s.active=s.scale>=1
  } else {
    s.active=false;s.scale=Math.max(.0001,f(s.scale-p.shrink));s.hidden=s.scale<=.0001
  }
  return s
}

const caches=new WeakMap()
export function chooseSwitch(previous,rng) {
  const weights=[100,100,100]
  if(previous>=0)weights[previous]=Math.trunc(weights[previous]/data.switch.repeatDivisor)
  const timer=data.switch.wait[0]+rng.int(data.switch.wait[1]-data.switch.wait[0])
  let value=rng.int(weights.reduce((a,b)=>a+b,0))
  const slot=weights.findIndex(weight=>(value-=weight)<0)
  return {timer,slot:slot<0?0:slot,attachment:rng.int(11)}
}

export function initialSwitchGroup() {return {state:0,timer:0,blocks:[]}}
// 801D0BBC followed by four live flag dynamics (801D0D24). The wind object's
// counter starts at zero and lb_800115F4 increments it before these draws.
export function flagWindDraws(strong,counter,rng) {
  if(counter%30===0)rng.float()
  if(counter%300===0)strong=strong?false:rng.float()>.5
  for(let j=0;j<5;j++)rng.float()
  return strong
}
export function switchGroupStep(previous,near=[]) {
  const s={...previous,blocks:previous.blocks.map(b=>({...b}))}
  if(s.state===1) {
    s.timer=p.duration[0]
    const done=s.blocks.every(b=>!b.hidden&&b.scale===1)
    s.blocks=s.blocks.map((b,j)=>switchBlockStep(b,true,near[j]))
    if(done)s.state=2
  }else if(s.state===2) {
    if(s.timer--<0){s.state=3;s.timer=0}
  }else if(s.state===3) {
    if(s.timer++>p.blink)s.state=4
  }else if(s.state===4) {
    const done=s.blocks.every(b=>b.hidden)
    s.blocks=s.blocks.map(b=>switchBlockStep(b,false))
    if(done)s.state=0
  }
  return s
}

function build(bundle) {
  const frames=fighterFrames(bundle)
  let platforms=[initialPlatform(),initialPlatform()], previous=[]
  let unavailable=Infinity
  let timer=0,slot=-1,attachment=-1,phase=0,blinkIdx=-1,blinkTimer=0,material=null
  let bulletWait=null,bill=null,strongWind=true,recentBills=[]
  let groups=data.switch.groups.map(ids=>({...initialSwitchGroup(),blocks:ids.map(()=>({hidden:true,scale:.0001,active:false}))}))
  const items=bundle.items||[],switches=new Map(items.filter(a=>a.t===160&&a.s?.[0]===1).map(a=>[a.f,a]))
  const bullets=items.filter(a=>a.t===160&&a.s?.[0]===3),bumps=items.filter(a=>a.t===160&&a.s?.[0]===2)
  const blockBumps=new Map()
  const rows=[]
  for(let i=0;i<bundle.meta.n;i++) {
    const rng=frameCursor(bundle,i)
    if(!rng)unavailable=Math.min(unavailable,i)
    // IfAll ready AOBJ ends at 85, with frame zero evaluated at creation.
    // Priority-0 if_802F73C4 invokes 801CD610 at idx 84, before fighter pre.
    if(i===84){
      const ready=frameCursor(bundle,i,{priority:1,extra:0})
      if(!ready)unavailable=Math.min(unavailable,i)
      else {timer=data.switch.wait[0]+ready.int(data.switch.wait[1]-data.switch.wait[0]);bulletWait=data.bullet.initial[0]+ready.int(data.bullet.initial[1])}
    }
    // Main controller precedes all satellite/group controllers at priority 4.
    // Its switch draws precede Bullet Bill selection and decorative flag RNG.
    if(i>=84&&phase===0&&--timer<0){
      if(!rng)unavailable=Math.min(unavailable,i)
      else {
        const next=chooseSwitch(slot,rng);({timer,slot,attachment}=next)
        phase=2;blinkIdx=-1;blinkTimer=0
      }
    }
    if(bulletWait!==null&&!bill&&bulletWait--<0&&rng){
      const options=Array.from({length:9},(_,j)=>j).filter(j=>!recentBills.includes(j)),route=options[rng.int(options.length)]
      recentBills.push(route);if(recentBills.length>3)recentBills.shift()
      const item=bullets.find(a=>a.f===i)
      // 801CE578's end-flag test then old-timer < 0 takes end+62 ticks.
      bill={route,start:i,end:i+data.bullet.animationEnds[route]+data.bullet.endWait+2,item}
      if(!item||item.f+item.x.length!==bill.end&&item.f+item.x.length<bundle.meta.n-1)unavailable=Math.min(unavailable,i)
    }
    if(rng)strongWind=flagWindDraws(strongWind,i+1,rng)
    if(phase===2){
      if(blinkTimer>0)blinkTimer--
      else {
        const delay=data.switch.blink[++blinkIdx]
        if(delay===-1){
          phase=3;material=switches.get(i)
          if(!material)unavailable=Math.min(unavailable,i)
          else {
            const point=data.switch.attachments[attachment]
            if(point.group===3&&Math.hypot(material.x[0]-point.xy[0],material.y[0]-point.xy[1])>.01)unavailable=Math.min(unavailable,i)
          }
        }else blinkTimer=2*delay
      }
    }else if(phase===3&&material&&i===material.f+material.x.length&&i<bundle.meta.n-1){
      // A mode-1 material has no timeout. DmgReceived/touched sets state 4;
      // the next ground callback removes it and starts its OWN linked group.
      // The RNG-selected slot above supplies identity; position is only a check.
      groups[slot].state=1;phase=5
    }else if(phase===5&&groups[slot].state===0)phase=0

    // Both Bill and its explosion are ordinary yaku replay tracks. Only mode 3
    // is a grCastle_801CDF54 growth obstacle. Its priority-1 animated root is
    // unchanged by later item physics. On its removal frame the root is frozen.
    const bullet=bill?.item
    const bt=bullet?Math.min(i-bullet.f,bullet.x.length-1):-1
    groups=groups.map((g,k)=>switchGroupStep(g,data.switch.groups[k].map(j=>bullet&&Math.hypot(data.origins[j][0]-bullet.x[bt],data.origins[j][1]-bullet.y[bt])<40)))
    // Question-block materials are removed immediately by the damage/touch
    // callback. The next ground pass applies [4,6,7,6,4,0] model-unit offsets.
    for(const item of bumps)if(i===item.f+item.x.length+1&&i<bundle.meta.n-1){
      const candidates=Object.keys(data.origins).map(Number).filter(j=>Math.hypot(data.origins[j][0]-item.x[0],data.origins[j][1]-item.y[0])<.05)
      if(candidates.length!==1)unavailable=Math.min(unavailable,i)
      else {
        const group=groups[data.switch.groups.findIndex(ids=>ids.includes(candidates[0]))]
        // State 2's expiration destroys unused materials too. That removal
        // starts blinking, not a touch/damage bump.
        if(!(group.state===3&&group.timer===1))blockBumps.set(candidates[0],0)
      }
    }
    if(bill&&i===bill.end){
      // Bill is created after the three satellite/group pairs. Its reset RNG
      // follows flag wind/dynamics; collision/material item work is later.
      // An item-emitting block bump at this same priority needs its own prefix.
      if([...blockBumps.values()].includes(3))unavailable=Math.min(unavailable,i)
      if(rng)bulletWait=data.bullet.wait[0]+rng.int(data.bullet.wait[1])
      bill=null
    }
    platforms=platforms.map((s,j)=>platformStep(s,i>84 && previous.some(l=>l[0]===14+j && frames.x.some((_,port)=>platformContact(frames,port,i-1,l)))?1:0))
    const vertices=data.initial.map(v=>v.slice())
    for(let j=0;j<2;j++) {
      const [start,n]=data.joints[j+4]
      for(let k=start;k<start+n;k++)vertices[k][1]=f(data.scale*f(platforms[j].position+data.platformLocalY))
    }
    const active=data.joints.map((_,j)=>[3,4,5].includes(j))
    groups.forEach((g,k)=>g.blocks.forEach((b,j)=>{active[data.switch.groups[k][j]]=b.active}))
    for(const [j,age] of blockBumps){
      const [start,n]=data.joints[j],dy=data.scale*data.bump[age]
      for(let k=start;k<start+n;k++)vertices[k][1]=f(vertices[k][1]+dy)
      if(age===data.bump.length-1)blockBumps.delete(j);else blockBumps.set(j,age+1)
    }
    previous=collisionLines(data,vertices,active)
    rows.push(previous)
  }
  return {rows,unavailable}
}
export default function simulate(bundle,idx) {
  if (!data) return null
  if(!supportedHistory(bundle,idx,4))return null
  let c=caches.get(bundle);if(!c){c=build(bundle);caches.set(bundle,c)}
  if(idx>=c.unavailable)return null
  return {lines:c.rows[idx].map(l=>l.slice()),replace:true,complete:true}
}

registerStageSimData(4, value => {
  data = value
  p=data.params
})
