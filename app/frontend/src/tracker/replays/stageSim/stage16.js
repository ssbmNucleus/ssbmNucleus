import { registerStageSimData, stageDataFor, fighterDataFor, fighterDataReady, fighterFrames, itemDataFor, itemDataReady, supportedFighterHistory as supportedHistory } from '../stageData.js'
let data
import { collisionLines } from './stage13.js'
import {frameCursor} from './rng.js'

const f=Math.fround
let p
export function initialBlock() { return {state:0,damage:0,timer:0,start:0,active:true} }

// grYorster_8020266C. The Cb2 input is upward displacement, NOT weight.
// Damage wins when both callbacks arrive before the next ground update.
export function blockStep(previous,{damage=0,bump=0,occupied=false,animationDone=false}={}) {
  const s={...previous,damage:f(previous.damage+damage)}
  if(s.state===0 || s.state===1) {
    const end=Math.min(p.animationStartMax,p.neutralAnimationEnd)
    if(s.damage>=p.damageMin) {
      s.damage=f(s.damage-p.damageMin)
      const left=s.damage>=p.damageMax?0:Math.trunc(f(p.damageMax-s.damage))
      s.start=Math.trunc(f(left*f(end/p.damageMax)))
      s.timer=p.delay;s.state=2
    } else if(bump>=p.bumpMin) {
      const excess=Math.max(p.bumpMin,f(bump-p.bumpMin))
      const left=excess>=p.bumpMax?0:Math.trunc(f(10*f(p.bumpMax-excess)))
      s.start=Math.trunc(f(left*f(end/f(10*p.bumpMax))))
      s.timer=p.delay;s.state=2
    }
  } else if(s.state===2) {
    if(s.timer<=0){s.active=false;s.state=3;s.timer=s.start}
    else s.timer--
  } else if(s.state===3) {
    if(s.timer>=323) {
      if(occupied){s.state=4;s.timer=0}
      else {s.state=1;s.damage=0;s.active=true}
    } else s.timer++
  } else if(s.state===4) {
    if(animationDone || s.timer>=25) {
      s.timer=0
      if(!occupied){s.state=1;s.damage=0;s.active=true}
    } else s.timer++
  }
  return s
}

let centers

// Numeric sphere centers from vanilla fighter DAT + AJ, in unturned model space.
// Unsupported action/character returns null, never an invented attack radius.
export function attackSpheres(cid,state,age,x,y,dir,hitboxes,targetMask=3,runtime=false) {
  const move=hitboxes?.[cid]?.[state] ?? fighterDataFor(cid)?.hitboxes?.[state]
  if(!move || !Number.isFinite(age) || ![1,-1].includes(dir) || !Number.isFinite(x) || !Number.isFinite(y)) return null
  // Empty authored landing/attack animations are safe at fractional ages too.
  if(!Object.keys(move.frames).length)return []
  if(!Number.isInteger(age))return null
  if(move.runtimeBones&&!runtime&&move.frames[age]?.length)return null
  // Chain's four attacks are replaced by it_802BCB88 world-space link
  // positions. The authored hand centers are not their collision pose,
  // including the start tick before the chain's first Item Update.
  if(cid===7&&state>=349&&state<=354&&move.frames[age]?.length&&!runtime)return null
  return (move.frames[age]||[]).flatMap(([id,z,dy,dx,radius,damage,group,angle,growth,setKb,baseKb])=>{
    const flags=move.elements?.[age]?.find(h=>h[0]===id)
    // it_802703E8 excludes Catch/Inert. The bugged victim-only command is
    // skipped by ftAction_8007121C unless the attacker is itself being thrown.
    // "item_hit_interaction" controls knockback, not item hit eligibility.
    if(flags&&(flags[3]||[8,11].includes(flags[1])||!((flags[4]??3)&targetMask)))return []
    // Item_8026A294 has no DmgReceived callback when both damage and
    // knockback are zero (for example Sing's sleep hitboxes).
    if(damage===0&&growth===0&&baseKb===0)return []
    return [{id,x:x+dir*dx,y:y+dy,z:-dir*z,radius,damage,group,angle,growth,setKb,baseKb,element:flags?.[1]??3}]
  })
}

// ftCo_AirCatch -> it_802A4BFC runs in Fighter_procAccessory (priority 8).
// Only the extending tip is an attack. Reaching the last constrained link
// clears both fighter hitboxes; retraction has no material damage. The
// ordinary attachment poses come from the fighter DAT, never RAM watches.
export function airCatchHistory(bundle) {
  const frames=fighterFrames(bundle),ports=[],draws=[]
  const step=(port,i,lines,afterGroundRng=null)=>{
    draws[port]=0
    const cid=frames.cid[port][i],state=frames.state[port][i],age=frames.age[port][i]
    if(!([6,20].includes(cid)&&state===360||cid===13&&state===357)){ports[port]=null;return undefined}
    const move=fighterDataFor(cid)?.hitboxes[state],a=move?.tether,dir=frames.dir[port][i]
    if(!a)return null
    let s=ports[port]
    if(!s||age===0)s=ports[port]={points:[],cleared:false,valid:true}
    if(!Number.isInteger(age))return null
    if(age<a.launch)return []
    const local=a.attach[age]
    if(!local||![1,-1].includes(dir))return null
    const attach=[f(frames.x[port][i]+dir*local[2]),f(frames.y[port][i]+local[1]),f(-dir*local[0])]
    if(age===a.launch){s.points=[attach.slice()];s.vx=f(dir*a.speed+f(frames.x[port][i-1]-frames.x[port][i-2]))}
    if(s.cleared)return []
    if(cid===13&&age>=a.retract)return []
    if(!s.points.length||!s.valid)return null
    if(i&&age===frames.age[port][i-1])return null // frozen accessory3 constraints
    let rng
    if(cid===13){
      // Item physics only installs the callback. Accessory2 consumes these
      // draws before procCollPos flushes queued GFX. A foreign article or
      // an earlier fighter ceiling callback needs its own ordered prefix.
      const bounds=fighterDataFor(cid)?.ecb[state]?.[age],x=frames.x[port][i],y=frames.y[port][i]
      const ceiling=bounds&&lines.some(l=>(l[1]&15)===2&&x>Math.min(l[2],l[4])&&x<Math.max(l[2],l[4])&&Math.abs(y+bounds[3]-l[3])<.01)
      const foreign=(bundle.items||[]).some(t=>![96,160].includes(t.t)&&i>=t.f&&i<t.f+t.x.length)
      rng=frames.x.length===1&&!ceiling&&!foreign?(afterGroundRng??(Number(bundle.meta.stage)===6?null:frameCursor(bundle,i))):null
      if(!rng){s.valid=false;return null}
      s.velY??=[]
    }
    const tip=s.points[0],old=tip.slice();tip[0]=f(tip[0]+s.vx)
    // A map-corrected hook needs the native fixed ECB sweep. Do not emit
    // an unconstrained tip through a wall, floor, or ceiling.
    const radius=a.mapRadius??a.segment
    if([[-radius,0],[radius,0],[0,-radius],[0,radius]].some(([dx,dy])=>itemMapCrossing(old[0]+dx,old[1]+dy,tip[0]+dx,tip[1]+dy,lines))){s.valid=false;return null}
    let ended=true
    for(let n=1;n<a.count;n++){
      const active=!!s.points[n],base=s.points[n-1],pos=s.points[n]||attach.slice()
      if(cid===13&&active){
        let vy=s.velY[n]||0
        if(rng.float()>.9){const amount=rng.float();vy=f(vy-f(vy<0?f(vy-amount):f(vy+amount)))}
        s.velY[n]=vy;pos[1]=f(pos[1]+vy)
      }
      const delta=pos.map((v,k)=>f(v-base[k])),length=Math.hypot(...delta)
      const segment=length>a.segment?a.segment:cid===13&&active&&length<a.minimum?a.minimum:null
      if(segment!=null&&length)s.points[n]=delta.map((v,k)=>f(base[k]+f(v*f(segment/length))))
      else {if(active||cid!==13)s.points[n]=pos;if(!active){ended=false;break}}
    }
    if(rng)draws[port]=rng.used
    if(ended){s.cleared=true;return []}
    const hits=attackSpheres(cid,state,age,frames.x[port][i],frames.y[port][i],dir,undefined,Number(bundle.meta.stage)===6?2:1,true)
    return hits?.map(h=>move.runtimeBones[h.id]===139?{...h,x:tip[0],y:tip[1],z:tip[2]}:h)??null
  }
  step.draws=draws
  return step
}

function chainFobj(events,frame) {
  let p0=0,p1=0,d0=0,d1=0,t0=0,t1=0,last=0,first=true
  for(const [op,time,value,tan] of events){
    if(op===5){d0=d1;d1=tan;last=op;continue}
    if(first){p1=value;d1=tan;t1=time;last=op;first=false;if(frame<t1)return p1;continue}
    p0=p1;p1=value;t0=t1;t1=time
    if(op===4){d0=d1;d1=tan}else if(op===3||last!==5){d0=d1;d1=0}
    if(frame<t1){const u=(frame-t0)/(t1-t0);if([1,6].includes(last))return p0;if(last===2)return p0+(p1-p0)*u
      return (2*u**3-3*u*u+1)*p0+(u**3-2*u*u+u)*(t1-t0)*d0+(-2*u**3+3*u*u)*p1+(u**3-u*u)*(t1-t0)*d1}
    last=op
  }
  return p1
}
function chainQuat(v){
  const [x,y,z]=v.map(a=>a*.5),sx=Math.sin(x),sy=Math.sin(y),sz=Math.sin(z),cx=Math.cos(x),cy=Math.cos(y),cz=Math.cos(z)
  return [sx*cy*cz-cx*sy*sz,cx*sy*cz+sx*cy*sz,cx*cy*sz-sx*sy*cz,cx*cy*cz+sx*sy*sz]
}
function chainHand(table,air,angle,magnitude,bounds=[]){
  const c=table.chain,a=c.aim[air?1:0],values=c.base.map(v=>v.slice()),frame=f(f(.0556*angle)+4)
  for(const [node,key,start,events] of a.tracks)values[node][key]=chainFobj(events,frame-start)
  const matrices=[]
  for(let k=0;k<values.length;k++){
    if(k===1)values[k]=a.rest[k].slice() // TransN.flags_b4 restores the neutral descriptor.
    const rest=a.rest[k],value=values[k],qr=chainQuat(rest.slice(0,3)),qt=chainQuat(value.slice(0,3))
    let dot=qr.reduce((s,v,i)=>s+v*qt[i],0)
    if(dot<0){for(let j=0;j<4;j++)qt[j]=-qt[j];dot=-dot}
    const theta=Math.acos(Math.min(1,dot)),den=Math.sin(theta)
    const q=qr.map((v,j)=>theta<1e-6?v*(1-magnitude)+qt[j]*magnitude:(v*Math.sin((1-magnitude)*theta)+qt[j]*Math.sin(magnitude*theta))/den)
    const [x,y,z,w]=q,sc=rest.slice(3,6).map((v,j)=>v*(1-magnitude)+value[j+3]*magnitude),pos=rest.slice(6).map((v,j)=>v*(1-magnitude)+value[j+6]*magnitude)
    const m=[[(1-2*(y*y+z*z))*sc[0],2*(x*y-z*w)*sc[1],2*(x*z+y*w)*sc[2],pos[0]],
      [2*(x*y+z*w)*sc[0],(1-2*(x*x+z*z))*sc[1],2*(y*z-x*w)*sc[2],pos[1]],
      [2*(x*z-y*w)*sc[0],2*(y*z+x*w)*sc[1],(1-2*(x*x+y*y))*sc[2],pos[2]]]
    const parent=matrices[c.parents[k]]
    matrices.push(!parent?m:parent.map(row=>m[0].map((_,j)=>row[0]*m[0][j]+row[1]*m[1][j]+row[2]*m[2][j]+(j===3?row[3]:0))))
  }
  const ecb=c.ecb.map(k=>matrices[k].map(row=>row[3]*table.modelScale))
  bounds.push(Math.min(...ecb.map(p=>p[2])),Math.max(...ecb.map(p=>p[2])),Math.min(...ecb.map(p=>p[1])),Math.max(...ecb.map(p=>p[1])))
  return matrices[c.hand].map(row=>f((row[3]+row[2]*.1)*table.modelScale))
}

// ftSeakSpecialS + itseakchain: the item owns constrained links and writes
// four fighter capsules. All inputs below are replay controls/poses and DAT
// constants. Native watch_chain is only an independent audit oracle.
export function chainHistory(bundle){
  const frames=fighterFrames(bundle),ports=[],reset=[],points=[],bounds=[],previousLines=[]
  const step=(port,i,lines,allLines=lines)=>{
    reset[port]=false
    const oldLines=previousLines[port]||allLines;previousLines[port]=allLines
    const state=frames.state[port][i],age=frames.age[port][i],table=fighterDataFor(7),c=table?.chain,dir=frames.dir[port][i]
    if(frames.cid[port][i]!==7||state<349||state>354){ports[port]=null;points[port]=null;bounds[port]=null;return undefined}
    if(!c||!Number.isInteger(age))return null
    const start=[349,352].includes(state),loop=[350,353].includes(state),end=[351,354].includes(state),a=c.attrs
    let s=ports[port]
    if(!s||start&&age===0)s=ports[port]={links:Array.from({length:a[0]},()=>({pos:[0,0,0],vel:[0,0,0],coll:[0,0,0],active:false})),phase:0,angle:4,magnitude:0,enabled:false,timer:0,history:Array.from({length:15},()=>[0,0]),current:Array.from({length:4},()=>[0,0,0]),previous:Array.from({length:4},()=>[0,0,0]),stick:[0,0],lastEnv:0}
    const repeated=i&&state===frames.state[port][i-1]&&age===frames.age[port][i-1]
    // procHitLag decrements before accessory physics. The frame whose
    // previous counter was one resumes, even when the start pose has ended.
    const frozen=repeated&&(age<table.hitboxes[state].end||frames.hitlag?.[port]?.[i-1]>1)
    if(frozen)return s.hits||[]
    if(i>1&&frames.hitlag?.[port]?.[i-2]>0)s.grace=2
    const animated=true
    if(!s.hand&&(!start||age>c.fighter[2]))return null
    const stick=[frames.joyx?.[port]?.[i]??0,frames.joyy?.[port]?.[i]??0]
    if(loop&&animated){
      // Fighter animation precedes this frame's input callback; accessory
      // link physics below sees the newly polled controls.
      const aimStick=[frames.joyx?.[port]?.[i-1]??0,frames.joyy?.[port]?.[i-1]??0]
      // lbtrigf.c's atan2f(0,0) is +pi/2 (unlike JavaScript's zero).
      let angle=aimStick[0]===0&&aimStick[1]===0?Math.PI/2:Math.atan2(aimStick[1],aimStick[0]*dir);if(angle<0)angle+=2*Math.PI
      angle=Math.max(0,Math.min(359,angle*180/Math.PI));let delta=f(angle-s.angle)
      if(delta>180)delta-=360;else if(delta< -180)delta+=360
      s.angle=f(s.angle+f(delta*c.smooth));if(s.angle>360)s.angle-=360;else if(s.angle<0)s.angle+=360
      s.magnitude=f(s.magnitude+f(c.smooth*f(Math.min(1,Math.hypot(...aimStick))-s.magnitude)))
    }
    const ecb=[]
    const local=loop&&age>0?chainHand(table,state===353,s.angle,s.magnitude,ecb):table.hitboxes[state]?.chainHand?.[age]
    bounds[port]=ecb.length?ecb:table.ecb[state]?.[age]
    if(!local)return null
    const hand=[f(frames.x[port][i]+dir*local[2]),f(frames.y[port][i]+local[1]),f(-dir*local[0])]
    if(start&&age===c.fighter[2]&&animated){s.enabled=true;s.timer=c.fighter[1]}
    if(loop&&age===0&&animated){s.enabled=true;reset[port]=true}
    else if(animated&&(loop||end&&age>0)){
      const moving=s.current.some((p,j)=>f(f((p[0]-s.previous[j][0])**2)+f((p[1]-s.previous[j][1])**2))>f(a[19]*a[19]))
      s.previous=s.current.map(p=>p.slice())
      if(s.timer>0&&--s.timer===0)s.enabled=false
      if(moving){if(s.timer<=0){s.timer=c.fighter[1];s.enabled=true;reset[port]=true}}
      else if(s.grace>0)s.grace--
      else {s.timer=0;s.enabled=false}
    }
    if(start&&age===c.fighter[2]+2&&animated){const link=s.links.at(-1);link.pos=[f(frames.x[port][i-1]+dir*local[2]),f(frames.y[port][i-1]+local[1]),hand[2]];link.coll=[frames.x[port][i-1],frames.y[port][i-1],0];link.vel=[f(a[20]*dir),0,0];link.active=true;s.phase=1}
    if(end&&age===c.fighter[4])s.phase=4
    if(end&&age>=c.fighter[5]){s.phase=0;s.enabled=false}
    const constrain=(link,target,length=a[1],force=false)=>{
      const delta=link.pos.map((v,k)=>f(v-target[k])),distance=f(Math.sqrt(f(f(delta[0]*delta[0])+f(delta[1]*delta[1])+f(delta[2]*delta[2]))))
      if(distance>length||force){const scale=distance?f(length/distance):0;link.pos=target.map((v,k)=>f(v+f(delta[k]*scale)))}
      return distance
    }
    const move=link=>{link.pos=link.pos.map((v,k)=>f(v+link.vel[k]))}
    const sim=stageDataFor(bundle.meta.stage)?.sim,links=sim?.lineLinks
    if(!links)return null
    // grZebes binds all six collision joints (joint0 also has B10).
    // grYoster/grInishie bind each material/pulley joint, leaving base0
    // static. mpJointUpdate therefore sets B8/B9 even at rest.
    const remaps=id=>Number(bundle.meta.stage)===6||sim.lines[id]?.[0]>=sim.joints[0][1]
    // mpLib_8004ED5C extends each connected edge by one unit for rays.
    const extended=lines.map(([id,flags,ax,ay,bx,by])=>{
      if((flags&15)>=4)return [id,flags,ax,ay,bx,by]
      const edge=links[id],length=Math.hypot(bx-ax,by-ay);if(!edge||length<=.001)return [id,flags,ax,ay,bx,by]
      const dx=(bx-ax)/length,dy=(by-ay)/length
      const neighbor=(primary,fallback,x,y,end)=>{const l=lines.find(l=>l[0]===primary);return l&&Math.hypot(l[end]-x,l[end+1]-y)<2?primary:fallback}
      const prev=neighbor(edge[2],edge[0],ax,ay,4),next=neighbor(edge[3],edge[1],bx,by,2)
      const x=f(ax-(prev>=0?dx:0)),y=f(ay-(prev>=0?dy:0))
      return [id,flags,x,y,f(bx+(next>=0?(bx-x)/length:0)),f(by+(next>=0?(by-y)/length:0))]
    })
    const map=n=>{
      const link=s.links[n],near=s.links[n-1],original=link.pos.slice(),from=(near?.active?near.pos:link.coll).slice()
      const velocity=original.map((v,k)=>f(v-from[k])),distance=Math.max(Math.abs(velocity[0]),Math.abs(velocity[1]))
      const steps=distance>6?Math.trunc(distance/6)+1:1,delta=velocity.map(v=>f(v/steps))
      let env=0;const remap=link.mapFrame!==i;link.mapFrame=i;link.pos=from
      // mpColl_80043754 subdivides the ray into at most six-unit steps.
      // Continue from each corrected position; a contact need not be the
      // final substep, and the accumulated environment survives it.
      for(let tick=0;tick<steps;tick++){
        const previous=link.pos;link.pos=previous.map((v,k)=>f(v+delta[k]))
        const hit=chainRayContact(previous,link.pos,extended,oldLines,remap&&tick===0?remaps:()=>false)
        if(!hit)continue
        let surface=lines.find(l=>l[0]===hit.line),type=surface[1]&15
        if(type<4){
          // The broad ray extends a connected line, then the projection
          // follows same-kind neighbors or rejects beyond its 0.1u endpoint.
          const visited=new Set();let rejected=false
          while(hit.x<Math.min(surface[2],surface[4])||hit.x>Math.max(surface[2],surface[4])){
            if(visited.has(surface[0])){rejected=true;break}visited.add(surface[0])
            const left=hit.x<Math.min(surface[2],surface[4]),prev=left===(surface[2]<surface[4]),edge=links[surface[0]]
            const primary=lines.find(l=>l[0]===edge[prev?2:3]),fallback=lines.find(l=>l[0]===edge[prev?0:1])
            const point=prev?2:4,end=prev?4:2,next=primary&&Math.hypot(primary[end]-surface[point],primary[end+1]-surface[point+1])<2?primary:fallback
            if(next&&(next[1]&15)===type){surface=next;continue}
            const x=left?Math.min(surface[2],surface[4]):Math.max(surface[2],surface[4])
            if(Math.abs(hit.x-x)>.1){rejected=true;break}
            hit.x=x;break
          }
          if(rejected)continue
          hit.y=f(surface[3]+(hit.x-surface[2])*(surface[5]-surface[3])/(surface[4]-surface[2]))
        }
        link.pos=[hit.x,f(hit.y+(type===1?.0001:type===2?-.0001:0)),0];env|=type
      }
      if(env&1)link.pos[0]=original[0]
      else if(env&12&&near?.active&&n<a[0]-1)link.pos[1]=f(link.pos[1]+a[1])
      link.coll=link.pos.slice();return env
    }
    const pull=(first,length)=>{
      constrain(s.links[first],hand,length,true)
      for(let n=first+1;n<a[0];n++){const link=s.links[n];link.vel[1]=f(link.vel[1]-a[6]);move(link);link.coll=link.pos.slice();map(n);constrain(link,s.links[n-1].pos)}
    }
    if(s.phase===1||s.phase===2){
      const tip=s.links.at(-1);if(s.phase===2)tip.vel[1]=f(tip.vel[1]-a[6]);move(tip)
      const env=map(a[0]-1);let all=true,scale=1
      for(let n=a[0]-2;n>=0;n--){const link=s.links[n],next=s.links[n+1]
        if(link.active){if(s.phase===2){link.vel[1]=f(link.vel[1]-f(a[6]*scale));scale=f(scale*a[13]);move(link)}constrain(link,next.pos);link.coll=link.pos.slice()}
        else {link.pos=hand.slice();if(constrain(link,next.pos)>a[1]){link.active=true;link.coll=link.pos.slice()}else {all=false;break}}
      }
      if(all){pull(0,a[1]);s.phase=3;s.enabled=false}
      else if(env>=4){tip.vel[0]=f(-tip.vel[0]*a[22]);s.phase=2;s.enabled=false}
    }else if(s.phase===3){
      const first=s.links.findIndex(l=>l.active)
      // End has no IASA update: the final loop's stick delta persists and
      // continues feeding the chain until retraction starts.
      if(loop)s.delta=stick.map((v,k)=>f((v-(k?frames.joyy:frames.joyx)?.[port]?.[i-1])*(Math.abs(stick[0])<a[18]&&Math.abs(stick[1])<a[18]?.5:1)))
      const delta=s.delta||[0,0]
      const impulse=delta.map((v,k)=>Math.abs(v)>a[18]?f(v*a[k===0?(Math.sign(v)===dir?14:15):(v>0?16:17)]):0)
      s.history=[impulse,...s.history.slice(0,14)];let scale=1,lastEnv=0
      const mode=Math.abs(stick[0])<a[18]&&Math.abs(stick[1])<a[18]?3:stick[1]<-.5?1:2
      for(let n=first;n<a[0];n++){
        const link=s.links[n],counter=n-first,h=s.history[Math.floor(counter*.5)]
        let dx=f(scale*f(h[0]*a[7])),dy=f(scale*f(h[1]*a[8]));if(counter&&s.lastEnv)dx=f(dx*a[12])
        link.vel[0]=f(link.vel[0]+dx);link.vel[1]=f(link.vel[1]+dy)
        const friction=f(a[4]*scale),vx=link.vel[0]
        link.vel[0]=Math.abs(vx)>friction?f(vx-Math.sign(vx)*friction):0
        link.vel[0]=Math.max(-f(a[9]*scale),Math.min(f(a[9]*scale),link.vel[0]))
        const gravity=f(a[6]*scale);if(link.vel[1]>f(gravity-a[10]))link.vel[1]=f(link.vel[1]-gravity);else if(link.vel[1]<f(-gravity-a[10]))link.vel[1]=f(link.vel[1]+gravity)
        link.vel[1]=Math.max(-f(a[11]*scale),Math.min(f(a[11]*scale),link.vel[1]));move(link)
        lastEnv=counter>mode?map(n):0
        if(lastEnv===1){if(Math.abs(link.vel[1])>a[24])link.vel[1]=f(-link.vel[1]*a[23]);else {const vx=link.vel[0];link.vel[0]=Math.abs(vx)>a[5]?f(vx-Math.sign(vx)*a[5]):0;link.vel[1]=0}}
        constrain(link,counter?s.links[n-1].pos:hand);scale=f(scale*a[13])
      }
      s.lastEnv=lastEnv===1?lastEnv:0
    }else if(s.phase===4){
      let first=s.links.findIndex(l=>l.active)
      if(first>=0){let distance=Math.hypot(...s.links[first].pos.map((v,k)=>v-hand[k]))
        while(first<a[0]-1&&a[21]>distance){s.links[first++].active=false;distance=Math.hypot(...s.links[first].pos.map((v,k)=>v-hand[k]))}
        pull(first,Math.min(a[1],distance-a[21]));if(first===a[0]-1)s.phase=0
      }
    }
    if(s.phase){
      const active=s.links.filter(l=>l.active),stride=Math.trunc(a[0]/3)
      for(let n=0;n<active.length;n++){if(n%stride===0)for(let h=2;h>=Math.floor(n/stride);h--)s.current[h]=active[n].pos.slice();if(n===active.length-1)s.current[3]=active[n].pos.slice()}
    }
    s.hand=hand;s.stick=stick;points[port]=s.current.map(p=>p.slice())
    const hits=attackSpheres(7,349,c.fighter[2],frames.x[port][i],frames.y[port][i],dir,undefined,Number(bundle.meta.stage)===6?2:1,true)
    s.hits=!s.enabled?[]:s.phase?hits.map(h=>({...h,x:s.current[h.id][0],y:s.current[h.id][1],z:s.current[h.id][2]})):start?attackSpheres(7,state,age,frames.x[port][i],frames.y[port][i],dir,undefined,Number(bundle.meta.stage)===6?2:1,true):[]
    return s.hits
  }
  step.reset=reset;step.points=points;step.bounds=bounds;return step
}

// mpCheck*Remap maps the ray origin from the previous unextended edge
// onto the current extended edge. This matters at stationary brick corners
// too: merely translating the origin does not preserve native contacts.
export function chainRayContact(from,to,lines,oldLines,remaps){
  const kinds=new Map()
  for(const line of lines){
    const [id,flags,ax,ay,bx,by]=line,old=oldLines.find(l=>l[0]===id)
    let px=from[0],py=from[1]
    if(old&&remaps(id)){
      const dx=old[4]-old[2],dy=old[5]-old[3],length=dx*dx+dy*dy
      if(length>.0001){
        const t=Math.max(0,Math.min(1,(dx*f(px-old[2])+dy*f(py-old[3]))/length))
        px=f(px+(1-t)*(ax-old[2])+t*(bx-old[4]));py=f(py+(1-t)*(ay-old[3])+t*(by-old[5]))
      }else {px=f(px+ax-old[2]+bx-old[2]);py=f(py+ay-old[3]+by-old[3])}
    }
    const hit=itemRayContact(px,py,to[0],to[1],[line]);if(!hit)continue
    const dx=f(hit.x-from[0]),dy=f(hit.y-from[1]),distance=f(f(dx*dx)+f(dy*dy))
    const signed=f(f(to[0]-px)*dx+f(to[1]-py)*dy)<0?-distance:distance,kind=flags&15
    if(!kinds.has(kind)||signed<kinds.get(kind).signed)kinds.set(kind,{...hit,distance,signed})
  }
  let hit=null
  for(const kind of [1,2,4,8]){const next=kinds.get(kind);if(next&&(!hit||next.distance<hit.distance))hit=next}
  return hit
}

// Green Missile's Fly state preserves its launch attack. DmgDealt replaces
// the motion after collision, so the first End sample can still carry the
// incoming capsule. Its launch displacement also exposes charge exactly on
// these nontranslating floors (the native speed is affine in integer charge).
export function luigiMissileHistory(bundle) {
  const frames=fighterFrames(bundle),ports=[]
  return (port,i,lines)=>{
    const state=frames.state[port][i],old=frames.state[port][i-1],age=frames.age[port][i]
    if(frames.cid[port][i]!==17||state<343||state>354){ports[port]=null;return undefined}
    const fly=[345,351].includes(state),wasFly=[345,351].includes(old),table=fighterDataFor(17),a=table.missile
    let s=ports[port]
    if([347,348,353,354].includes(state))ports[port]=s={misfire:[348,354].includes(state),damage:null}
    const immediate=state===352&&[347,348,353,354].includes(old)&&frames.age[port][i-1]===3&&age===0
    if(fly&&!wasFly||immediate){
      if(!s)s=ports[port]={misfire:[348,354].includes(old),damage:null}
      const speed=(frames.x[port][i]-frames.x[port][i-1])*frames.dir[port][i],charge=Math.round((speed-a.speed)/a.speedSlope)
      s.damage=s.misfire?25:charge>=0&&charge<=a.max+1&&Math.abs(f(a.speed+f(charge*a.speedSlope))-speed)<.001?f(a.damage+f(charge*a.damageSlope)):null
    }
    const incoming=immediate||state===352&&old===351&&age===0&&frames.age[port][i-1]+1<table.hitboxes[old].end
    if(!fly&&!incoming)return undefined
    if(incoming){
      const ecb=table.ecb[old]?.[frames.age[port][i-1]+1],x=frames.x[port][i],y=frames.y[port][i]
      // A wall-triggered End occurs in map, before item collision.
      if(ecb&&lines.some(([,flags,ax,ay,bx,by])=>[4,8].includes(flags&15)&&y+ecb[3]>=Math.min(ay,by)&&y+Math.max(0,ecb[2])<=Math.max(ay,by)&&Math.min(Math.abs(x+ecb[0]-ax),Math.abs(x+ecb[1]-ax),Math.abs(x-ecb[0]-ax),Math.abs(x-ecb[1]-ax))<.002))return []
    }
    const hits=attackSpheres(17,incoming?351:state,incoming?frames.age[port][i-1]+1:age,frames.x[port][i],frames.y[port][i],frames.dir[port][i],undefined,Number(bundle.meta.stage)===6?2:1)
    const misfire=s?.misfire?attackSpheres(17,348,4,0,0,1)?.[0]:null
    return !hits?.length?hits:s?.damage==null?null:hits.map(h=>({...h,damage:s.damage,...(misfire?{radius:misfire.radius,growth:misfire.growth}:{} )}))
  }
}

export function thunderHitHistory(bundle) {
  const frames=fighterFrames(bundle),cleared=[]
  const step=(port,i)=>{
    step.draws[port]=0
    const cid=frames.cid[port][i],state=frames.state[port][i],age=frames.age[port][i]
    if(![12,23].includes(cid)||![361,365].includes(state)){cleared[port]=false;return undefined}
    const move=fighterDataFor(cid).hitboxes[state],old=frames.state[port][i-1]
    if(![361,365].includes(old))step.draws[port]=move.thunderHit[1]
    // ftPk_SpecialLwLoop1 uses a looping pose with a one-shot command
    // stream. Its clear at command age9 survives every animation wrap
    // and the SkipHit ground/air transition.
    if(age>=move.thunderHit[0]||[361,365].includes(old)&&age<frames.age[port][i-1])cleared[port]=true
    return cleared[port]?[]:attackSpheres(cid,state,age,frames.x[port][i],frames.y[port][i],frames.dir[port][i],undefined,Number(bundle.meta.stage)===6?2:1)
  }
  step.draws=[];return step
}

// Skull Bash preserves its launch capsule in state350; DmgDealt enters351
// after that capsule has already struck. Hold ticks set damage, and the
// first flight displacement independently exposes the affine charge speed.
export function skullBashHistory(bundle) {
  const frames=fighterFrames(bundle),ports=[]
  return (port,i,lines)=>{
    const cid=frames.cid[port][i],state=frames.state[port][i],old=frames.state[port][i-1],age=frames.age[port][i]
    if(![12,23].includes(cid)||state<343||state>352){ports[port]=null;return undefined}
    const table=fighterDataFor(cid),a=table.skullBash
    let s=ports[port]
    if(!s||[343,348].includes(state))ports[port]=s={charge:0}
    if([344,349].includes(old))s.charge++
    const immediate=state===351&&age===0&&[347,352].includes(old)&&frames.age[port][i-1]===3
    const incoming=immediate||state===351&&age===0&&old===350&&frames.age[port][i-1]+1<table.hitboxes[350].end
    if(state===350&&old!==350||immediate){
      const speed=(frames.x[port][i]-frames.x[port][i-1])*frames.dir[port][i],charge=Math.round((speed-a.speed)/a.speedSlope)
      s.charge=charge>=0&&charge<=a.max+1&&Math.abs(f(a.speed+f(charge*a.speedSlope))-speed)<.001?charge:null
    }
    if(![345,347,350,352].includes(state)&&!incoming)return undefined
    if(incoming){
      const ecb=table.ecb[350]?.[frames.age[port][i-1]+1],x=frames.x[port][i],y=frames.y[port][i]
      if(ecb&&lines.some(([,flags,ax,ay,bx,by])=>[4,8].includes(flags&15)&&y+ecb[3]>=Math.min(ay,by)&&y+Math.max(0,ecb[2])<=Math.max(ay,by)&&Math.min(Math.abs(x+ecb[0]-ax),Math.abs(x+ecb[1]-ax),Math.abs(x-ecb[0]-ax),Math.abs(x-ecb[1]-ax))<.002))return []
    }
    const hits=attackSpheres(cid,incoming?350:state,incoming?frames.age[port][i-1]+1:age,frames.x[port][i],frames.y[port][i],frames.dir[port][i],undefined,Number(bundle.meta.stage)===6?2:1)
    return !hits?.length?hits:s.charge==null?null:hits.map(h=>({...h,damage:f(a.damage+f(s.charge*a.damageSlope))}))
  }
}

// Ness overrides hitbox0 in accessory4 with a world point saved in physics,
// before fighter translation/map. Charge holds that point, then release
// interpolates toward joint61 (ftNs_AttackHi4/Lw4Release_Phys).
export function nessYoyoHistory(bundle) {
  const frames=fighterFrames(bundle),ports=[]
  const step=(port,i,lines)=>{
    step.reset[port]=false
    const state=frames.state[port][i],age=frames.age[port][i],cid=frames.cid[port][i]
    if(cid!==8||state<342||state>347){ports[port]=null;return undefined}
    const table=fighterDataFor(8),move=table.hitboxes[state],p=move?.yoyo?.positions[age],dir=frames.dir[port][i]
    const hits=attackSpheres(cid,state,age,frames.x[port][i],frames.y[port][i],dir,undefined,Number(bundle.meta.stage)===6?2:1)
    let s=ports[port]
    if(!s){s=ports[port]={pos:null,charge:0,rehit:0};if([343,344,346,347].includes(state))return hits?.length?null:hits}
    const charging=[343,346].includes(state),release=[344,347].includes(state),same=state===frames.state[port][i-1]
    const advanced=charging||!same||age!==frames.age[port][i-1]
    if(advanced&&s.rehit>0&&(move.yoyo.unrotate==null||age<move.yoyo.unrotate)&&!--s.rehit)step.reset[port]=true
    if(charging){if(same)s.charge++}
    else if(advanced&&p){
      const root=Math.max(0,i-1),x=frames.x[port][root],y=frames.y[port][root]
      let px=dir*p[2],py=p[1]
      if(move.yoyo.unrotate==null||age<move.yoyo.unrotate){
        const floors=lines.filter(([,flags,ax,ay,bx,by])=>(flags&15)===1&&x>=Math.min(ax,bx)-.01&&x<=Math.max(ax,bx)+.01&&Math.abs(y-(ay+(x-ax)*(by-ay)/(bx-ax)))<.03)
        if(floors.length!==1){s.pos=null;return hits?.length?null:hits}
        const [, ,ax,ay,bx,by]=floors[0],angle=Math.atan2(by-ay,bx-ax),c=Math.cos(angle),sin=Math.sin(angle)
        const dx=px-dir*p[5],dy=py-p[4];px=dir*p[5]+c*dx-sin*dy;py=p[4]+sin*dx+c*dy
      }
      let pos=[f(x+px),f(y+py),f(-dir*p[0])]
      if(release){
        if(!s.pos)return hits?.length?null:hits
        const t=Math.min(1,Math.max(0,f((state===344?.1:.2)*(age-13))))
        pos=pos.map((v,k)=>f(f(v*t)+f(s.pos[k]*f(1-t))))
      }else s.charge=0
      s.pos=pos
    }
    if(!hits?.length)return hits
    if(!s.pos)return null
    return hits.map(h=>h.id===0?{...h,x:s.pos[0],y:s.pos[1],z:s.pos[2],damage:release?f(h.damage*f(1+f(f(table.yoyo[1]*.003906-1)*f(s.charge/table.yoyo[0])))):h.damage}:h)
  }
  step.reset=[];step.hit=port=>{if(ports[port])ports[port].rehit=fighterDataFor(8).yoyo[2]}
  return step
}

// ftCo_800DEF38 increments charge time while animation is frozen, before
// input releases it. Only pre-hit repeated ages count (hitlag does not).
export function smashChargeHistory(frames) {
  return frames.state.map((states,port)=>{
    let held=0
    return states.map((state,i)=>{
      const age=frames.age[port][i],cid=frames.cid[port][i]
      if(!i||state!==states[i-1]||cid!==frames.cid[port][i-1]||age<frames.age[port][i-1])held=0
      const move=fighterDataFor(cid)?.hitboxes?.[state]
      if(move?.charge&&i&&age>0&&age===frames.age[port][i-1]&&state===states[i-1]&&age<Math.min(...Object.keys(move.frames).map(Number)))held=Math.min(move.charge[1],held+1)
      return held
    })
  })
}
export function materialDamage(hit,move,held=0) {
  // ftCo_800DEEB8's float expression, then it_802703E8's integer log.
  const charge=move?.charge
  return Math.trunc(charge&&held?f(hit.damage*f(f(f(charge[2]-1)*f(held/charge[1]))+1)):hit.damage)
}

function itemOwnerPort(track,j,bundle) {
  if(Number.isInteger(track.port?.[j]))return track.port[j]>=0?track.port[j]:null
  const owner=track.owner?.[j]??track.o
  if(owner==null||owner<0)return null
  // Older compact metadata retained dense port_index only; it is not the
  // physical port byte in Item Update. A solo fighter is still unambiguous.
  if(bundle.frames.x.length===1)return 0
  const port=bundle.meta.players?.findIndex(p=>p.physical_port===owner)
  return port>=0?port:null
}
function itemThrowMultiplier(track,j,age,bundle) {
  const first=j-age,idx=track.f+first,port=itemOwnerPort(track,first,bundle)
  if(port==null||port<0)return null
  const f=bundle.frames,cid=f.cid?.[port]?.[idx],state=f.state?.[port]?.[idx],at=f.age?.[port]?.[idx]
  const entries=fighterDataFor(cid)?.hitboxes?.[state]?.itemThrowDamage
  if(entries)return entries.filter(([frame])=>frame<=at).at(-1)?.[1]??null
  // Item_8026ABD8's neutral release uses exactly 1. An ordinary drop is
  // observable as held -> dropped without a throw motion.
  return first>0?1:null
}

// ftPe_SpecialLw's accessory callback draws the rare-item roll, then the
// turnip face. The caller supplies the proven scheduler prefix (Brinstar
// has ground RNG before accessory9; Yorster has no ground RNG).
export function turnipFaceAtSpawn(bundle,track,rng) {
  const i=track.f,frames=bundle.frames
  if(track.t!==99||track.s?.[0]!==0||frames.x.length!==1||frames.cid[0][i]!==9||frames.state[0][i]!==352||frames.age[0][i]!==1||!rng)return null
  if((bundle.items||[]).some(t=>![99,160].includes(t.t)&&t.f<=i&&t.f+t.x.length>i))return null
  if(rng.int(fighterDataFor(9).turnipPluck.rareOdds)===0)return null
  const weights=itemDataFor(99).faceWeights
  let roll=rng.int(weights.reduce((a,b)=>a+b,0)),face=0
  while(roll>=weights[face])roll-=weights[face++]
  return face
}

export function knownTurnipDamage(hits,track,j,face) {
  if(face==null||track.t!==99||track.s[j]!==2||!hits)return hits
  const damage=itemDataFor(99).faceDamage[face]
  return hits.map(h=>({...h,damage,damageUnknown:false}))
}

// it_802706D0 uses the same swept hit capsules as fighter/material contact.
// Item state IDs select DOL state-table entries, NOT animation IDs. Inert
// attached props (blasters, bows, G&W meshes) have no item hit commands; their
// fighter's authored attack is already sampled above.
export function itemSpheres(track, j, age, bundle) {
  // Disable's DAT attack has no item target interaction. Its C callbacks
  // only scale that authored attack and manage motion/lifetime.
  if (track.t===160||track.t===110||[68,108,145].includes(track.t)) return []
  if([62,63,96].includes(track.t)) {
    // These items move a fighter-owned attack, not an item attack. Keep
    // unobserved/ground-grab owners gated (Samus has a separate secret
    // grapple attack there); airCatchHistory handles certified births.
    const port=itemOwnerPort(track,j,bundle),cid=bundle.frames.cid?.[port]?.[track.f],state=bundle.frames.state?.[port]?.[track.f]
    return cid===({62:6,63:20,96:13})[track.t]&&state===(cid===13?357:360)?[]:null
  }
  if(track.t===97){
    const port=itemOwnerPort(track,j,bundle),state=bundle.frames.state?.[port]?.[track.f]
    return bundle.frames.cid?.[port]?.[track.f]===7&&[349,352].includes(state)?[]:null
  }
  const table=itemDataFor(track.t),state=track.s?.[j]
  if (!table || state==null) return null
  // An empty DAT script is not proof that an unknown C callback is inert.
  // These props are held models whose attack is owned by the fighter; the
  // remaining authored kinds require either the throw or projectile adapter.
  const heldProp=/(Blaster|Bow|Hammer|Mario_Cape|DrMario_Sheet|Ness_Bat|Ness_Yoyo|Peach_Parasol|Peach_Toad|PeachToad|NeedleHeld|IceClimber_GumStrings|GameWatchChefPan|Yoshi_EggLay|YoshiEggLay)$/.test(table.name)
  // it_2ADA's discarded Kirby copy star only tumbles and expires; its
  // motion0 script is empty and none of its C callbacks creates an attack.
  if(table.family==='authored'&&!table.dropStates&&!heldProp&&![8,9,10,52].includes(track.t)&&
    !/(Mario_?Fire|DrMario_?Vitamin|Luigi_?Fire|Kirby_CBeam|Fox_Illusion|Falco_Phantasm|GameWatch_?Chef|Peach_?ToadSpore|Peach_Explode|Seak_?NeedleThrow)/.test(table.name))return null
  const anim=table.states[state]
  if (anim===-1) return []
  const move=table.animations[anim]
  if (!move) return null
  if(table.family==='joltair'&&track.joltPose?.[j])age=track.joltPose[j].age
  // PK Flash's constructor advances once explicitly; creation during item
  // animation also receives the new object's ordinary priority-1 pass.
  if(['pkexplode','dinexplode'].includes(table.family))age+=2
  // Link bombs enter their explosion in DmgDealt and then freeze in hitlag.
  // UnkMotion5_Anim decrements life only when Item_80269528 advances the
  // script. StateChange already ran that script once (timer 0 -> -1).
  if(table.family==='bomb'&&state===5&&track.lifetime){
    const first=j-age
    age=1+track.lifetime[first]-track.lifetime[j]
  }
  if(track.t===6&&state===11&&track.lifetime){
    const first=j-age
    // Bombhei's explosion commands pause with item hitlag too. Its idle,
    // walking and turning states cannot explode in map/animation;
    // their state11 transition follows this frame's collision pass.
    // A falling unarmed bomb is likewise late; an armed fall is ambiguous.
    if(age===0&&first>0&&([0,2,3].includes(track.s[first-1])||track.s.slice(0,first).every(s=>s===0||s===1)))return []
    age=track.lifetime[first]-track.lifetime[j]
  }
  if (move.truncated && age>move.end) return null
  // Brinstar retains yaku's initial GA_Air. Yorster/Inishie explicitly
  // switch theirs to GA_Ground with grMaterial_801C8E68.
  const targetMask=Number(bundle.meta.stage)===6?2:1
  const hs=(move.frames[Math.min(age+(table.family==='laser'?1:0),move.end)]||[]).filter(h=>h[13]&targetMask)
  if (!hs.length) return []
  const x=track.x[j],y=track.y[j],dir=track.d?.[j],vx=track.vx?.[j],vy=track.vy?.[j]
  if (![x,y,vx,vy].every(Number.isFinite)||![1,-1].includes(dir)) return null
  const family=table.family
  if(family==='jolt'&&state===1)return [] // map transition disables the parent's attack
  if(family==='joltair'&&!track.joltPose?.[j])return null
  if(family==='thunder') {
    let vertical=1,radiusScale=1
    if(state===2){
      const speed=Math.abs(vy),life=track.lifetime?.[j],length=table.special[1]
      if(!(speed>0)||!Number.isFinite(life))return null
      const ticks=Math.round(length/speed-life)
      let left=length
      for(let k=0;k<ticks;k++){
        const next=f(left-speed);if(next<=0)break
        radiusScale=f(radiusScale*f(Math.trunc(f(f(10000*next)/left)+1)/10000))
        vertical=f(Math.trunc(f(f(10000*next)/length)+1)/10000);left=next
      }
    }
    return hs.map(([id,z,dy,dx,radius,damage,group,angle,growth,setKb,baseKb,element])=>({id,x:x+dir*dx,y:y+dy*vertical,z:-dir*z,
      radius:radius*radiusScale,damage,group,angle,growth,setKb,baseKb,element,sourceX:x,vx,kind:track.t,item:true,velocityDirectionThreshold:table.velocityDirectionThreshold}))
  }
  let scale=table.scale,stretch=1,theta=0,damage=null,multiplier=1,damageUnknown=false
  if (family==='laser') {
    // Fighter_procAnim creates the laser before its first item animation pass.
    // The first recorded sample has already grown and moved once.
    const speed=Math.hypot(vx,vy)
    stretch=Math.min(table.special[1],(age+1)*speed/11.25)
    theta=Math.atan2(vy,Math.abs(vx))
    if (j && (track.d[j]!==track.d[j-1] || j>1&&Math.abs(Math.hypot(track.vx[j-1],track.vy[j-1])-speed)>.001)) return null
  } else if (family==='arrow') {
    const first=j-age,speed=Math.hypot(track.vx[first],track.vy[first])
    const a=table.special
    const charge=Math.round(60*(speed-a[1])/(a[2]-a[1]))/60
    if (!Number.isFinite(charge)||charge<-.02||charge>1.02) return null
    damage=age?Math.trunc(f(a[3]+f(Math.max(0,Math.min(1,charge))*f(a[4]-a[3])))):1
    // The arrow's one material hitbox is centered on root zero. Its visual
    // owner-model scale cannot move that center or change collision radius.
    if(hs.some(h=>h[1]||h[2]||h[3]))return null
    theta=Math.max(-a[8],Math.min(a[8],Math.atan2(vy,Math.abs(vx))))
  } else if (family==='charge' && ![94,151].includes(track.t)) {
    return null // Shadow Ball's runtime scaling is not the Samus state adapter.
  } else if(family==='needle') {
    theta=Math.atan2(vy,Math.abs(vx))
  } else if(family==='joltair') {
    theta=-dir*Math.atan2(...track.joltPose[j].normal)
  } else if(family==='pkpillar') {
    if(!Number.isFinite(track.lifetime?.[j]))return null
    scale=f(table.scale*f(table.special[2]+f(Math.min(table.special[0],track.lifetime[j]+1)*f(1-table.special[2]))/table.special[0]))
  } else if(['pkexplode','dinexplode'].includes(family)) {
    if(!Number.isFinite(track.flashCharge))return null
    const a=table.special
    scale=f(f(track.flashCharge*f((a[2]-a[1])/a[0]))+a[1])
    damage=Math.trunc(f(f(track.flashCharge*a[4])+a[3]))
  } else if(family==='shadow') {
    const offset=track.shadow?.[j]
    if(!offset||hs.some(h=>h[1]||h[2]||h[3]||h[12]!==2))return null
    const parent=table.oscillatorParent
    if(!parent)return null
    return hs.map(([id,,, ,radius,damage,group,angle,growth,setKb,baseKb,element])=>({
      // The map transition calls Item_80268E5C, restoring the authored
      // child translations. Explosion physics never runs the oscillator.
      id,x:state>=10?x:x+dir*(offset[0]+parent[2])*scale,y:state>=10?y:y+(offset[1]+parent[1])*scale,z:state>=10?0:-dir*parent[0]*scale,
      radius:radius*scale*(state>=10&&j>0&&track.s[j-1]===state?table.special[9]:1),damage,group,angle,growth,setKb,baseKb,element,
      sourceX:x,vx,kind:track.t,item:true,velocityDirectionThreshold:table.velocityDirectionThreshold,
    }))
  } else if (family==='turnip'&&state===2) {
    // The face is recorded by Slippi. Older compact bundles omitted it;
    // never silently substitute the common 2-damage face for a stitch.
    const face=track.face?.[j]
    if (!Number.isInteger(face)||!Number.isFinite(table.faceDamage?.[face]))damageUnknown=true
    else damage=table.faceDamage[face]
  }
  if(table.dropStates?.includes(state)){
    multiplier=itemThrowMultiplier(track,j,age,bundle)
    if(!Number.isFinite(multiplier)){damageUnknown=true;multiplier=1}
  }
  // Rotating common items with offset/child hitboxes need their own pose
  // adapter. Centered spheres are invariant under the native item spin.
  if(track.t<43&&hs.some(h=>h[1]||h[2]||h[3]||h[12]))return null
  return hs.map(([id,z,dy,dx,radius,baseDamage,group,angle,growth,setKb,baseKb,element,bone])=>{
    const angle2=family==='needle'&&bone!==1?0:theta,c=Math.cos(angle2),s=Math.sin(angle2)
    const px=dir*dx*scale*stretch,py=dy*scale
    // itanimlist's hitbox command divides pill/fireball size by item->scl;
    // itcoll multiplies it back. Model scaling must not enlarge that radius.
    return {id,x:x+c*px-dir*s*py,y:y+dir*s*px+c*py,z:-dir*z*scale,radius:['illusion','chef','pkexplode','dinexplode'].includes(family)||family==='turnip'&&state===2?radius*scale:radius,
      damage:damage??Math.trunc(f(baseDamage*multiplier)),damageUnknown,group,angle,growth,setKb,baseKb,element,
      sourceX:x,vx,kind:track.t,item:true,velocityDirectionThreshold:table.velocityDirectionThreshold}
  })
}

// it_802C5000 seeds the grandchild oscillator in fighter animation (s_link 1).
// it_802C4D10 advances it in item physics (4), after the final pre record.
// Keep the recorded root position: Slippi does not serialize this child joint.
export function recordedShadowHistory(bundle) {
  const result=new Map(),tracks=(bundle.items||[]).filter(t=>[112,144].includes(t.t))
  if(!tracks.length)return result
  const states=bundle.frames.state?.[0]||[],solo=bundle.frames.x.length===1&&!bundle.frames.fol?.length
  const records=tracks.map(track=>({track,offsets:Array(track.x.length).fill(null),valid:false,tick:0}))
  for(const r of records)result.set(r.track,r.offsets)
  for(let i=0;i<bundle.meta.n;i++) {
    const anim=frameCursor(bundle,i,{priority:1,extra:0}),phys=frameCursor(bundle,i)
    // Foreign articles and damage callbacks can precede these draws. Their
    // source order needs a separate adapter; a matching final seed is no proof.
    const safe=solo&&(states[i]>=14&&states[i]<=350||bundle.frames.cid[0][i]===4&&states[i]>=500&&states[i]<=509)&&!(states[i]>=75&&states[i]<=91)&&
      !(bundle.items||[]).some(t=>t.t!==160&&![112,144].includes(t.t)&&i>=t.f&&i<t.f+t.x.length)
    for(const r of records) {
      const {track}=r,j=i-track.f,a=itemDataFor(track.t)?.special
      if(j<0||j>=track.x.length)continue
      const state=track.s[j]
      if(j===0) {
        r.valid=!!(safe&&anim&&a?.length>=12&&state===0)
        if(r.valid)Object.assign(r,shadowOscillator(a,anim))
      }
      if(!r.valid||!safe||!phys||state===9){r.valid=false;continue}
      if(state===0){r.offsets[j]=[0,0];continue}
      if(j&&track.s[j-1]===0){r.tick=0;r.multiplier=f(.5*f((state-(state>=10?10:1))/7)+.5)}
      if(state<10||j&&track.s[j-1]<10) {
        shadowOscillatorStep(r,a,phys)
      }
      r.offsets[j]=r.offset.slice()
    }
  }
  return result
}
export function shadowOscillator(a,rng) {
  return {angle:f(2*Math.PI*rng.float()),amplitude:f(2.5+f(rng.float()-.5)),period:a[8],offset:[0,0],tick:0,multiplier:0}
}
export function shadowOscillatorStep(r,a,rng) {
  if(r.tick>0) {
    if(++r.period>=a[8]) {r.period=0;r.angle=f(r.angle+f((Math.PI/4)*f(2*f(rng.float()-.5))));r.delta=f(-r.amplitude/f(.5*a[8]));rng.int(3)}
    r.amplitude=f(r.amplitude+r.delta)
    const distance=f(r.amplitude*r.multiplier)
    r.offset=[f(r.offset[0]+f(distance*f(Math.cos(r.angle)))),f(r.offset[1]+f(distance*f(Math.sin(r.angle))))]
  } else r.offset=[0,0]
  r.tick++
}

export function itemAttackHistory(bundle,{allowNeedleOmissions=false}={}) {
  const rows=Array.from({length:bundle.meta.n},()=>[])
  const samusCharges=samusChargeHistory(bundle)
  const itemTracks=(bundle.items||[]).map(track=>{
    const j=track.x.length-1,a=itemDataFor(track.t)
    if(a?.family!=='shadow'||track.s[j]<1||track.s[j]>8||track.f+j+1>=rows.length||!(track.lifetime?.[j]>1))return track
    const t={...track,shadowTerminal:track.x.length}
    for(const key of ['x','y','s','d','vx','vy'])t[key]=track[key].slice()
    const speed=f(a.special[2]+f((track.s[j]-1)*f((a.special[3]-a.special[2])/7))),vx=f(track.d[j]*speed)
    t.x.push(f(track.x[j]+vx));t.y.push(f(track.y[j]+track.vy[j]));t.s.push(track.s[j]);t.d.push(track.d[j]);t.vx.push(vx);t.vy.push(track.vy[j])
    return t
  })
  const shadow=recordedShadowHistory({...bundle,items:itemTracks})
  // The native recorder has 15 slots, including stage materials. Inishie1
  // always fills them and has its explicit hidden-article adapters below.
  // On the other stages, saturation cannot certify that every attack was
  // recorded. Gate that rare history instead of treating missing items as inert.
  const pkOnly=bundle.meta.item_frequency===-1&&bundle.frames.x.length===1&&!bundle.frames.fol?.length&&
    bundle.frames.cid[0].every(cid=>cid===8)&&(bundle.items||[]).every(t=>t.t===160||t.t>=69&&t.t<=73)
  if(Number(bundle.meta.stage)!==19&&!pkOnly){
    const counts=new Int16Array(rows.length+1)
    for(const t of bundle.items||[]){
      const lo=Math.max(0,t.f),hi=Math.min(rows.length,t.f+t.x.length)
      if(lo<hi){counts[lo]++;counts[hi]--}
    }
    for(let i=0,live=0;i<rows.length;i++){
      live+=counts[i]
      // Charging can fill the recorder with held needles while old bounced
      // needles remain alive. With items off and no other article family,
      // those omitted charge models cannot attack. A release or a live
      // projectile still requires a complete record list.
      const rack=live===15&&[6,16].includes(Number(bundle.meta.stage))&&bundle.meta.item_frequency===-1&&
        bundle.frames.x.length===1&&!bundle.frames.fol?.length&&[4,7].includes(bundle.frames.cid[0][i])&&
        [341,342,345,346,467,468,471,472].includes(bundle.frames.state[0][i])&&
        (bundle.items||[]).every(t=>[160,79,80,152,153].includes(t.t))&&
        (bundle.items||[]).filter(t=>i>=t.f&&i<t.f+t.x.length).every(t=>[160,80,153].includes(t.t)||[2,4].includes(t.s[i-t.f]))
      if(live>=15&&!rack&&!allowNeedleOmissions)rows[i].push({id:'item-record-cap',hits:null,previous:[]})
    }
  }
  // Nine Yorster materials + the head + six trails exceed Slippi's cap.
  // it_802AB3F0 samples positions[2*n], which physics saves BEFORE moving
  // the head. The sixth trail can first appear a tick late when the head
  // dies. Fill only holes; recorded trail samples remain authoritative.
  for(const [headId,head] of itemTracks.entries())if(pkOnly&&head.t===69){
    for(let n=0;n<6;n++){
      const kind=[70,70,70,71,72,73][n],birth=head.f+2*n
      const tail=itemTracks.find(t=>t.t===kind&&t.o===head.o&&t.f>=birth&&t.f<=birth+1)
      let previous=[]
      for(let i=birth;i<head.f+head.x.length;i++){
        const age=i-head.f,j=age-2*n-1
        const x=j<0?f(head.x[0]-head.vx[0]):head.x[j],y=j<0?f(head.y[0]-head.vy[0]):head.y[j]
        const track={t:kind,o:head.o,f:i,x:[x],y:[y],s:[0],d:[head.d[0]],vx:[0],vy:[0]}
        const hits=itemSpheres(track,0,0,bundle)
        if(!tail||i<tail.f||i>=tail.f+tail.x.length)rows[i]?.push({id:`pk-tail:${headId}:${n}`,track,j:0,hits,previous,reset:i===birth})
        previous=hits||[]
      }
    }
  }
  for (const [id,recorded] of itemTracks.entries()) {
    let track=recorded
    if(itemDataFor(track.t)?.family==='joltair'){
      const parents=itemTracks.filter(t=>t.t===track.t-1&&t.o===track.o&&t.f<=track.f&&t.f+t.x.length>track.f)
      track={...track,joltPose:[],joltParent:parents.length===1?parents[0]:null}
    }
    if([78,109,146].includes(track.t)) {
      const source=(bundle.items||[]).filter(t=>t.t===({78:68,109:108,146:145})[track.t]&&t.f+t.x.length===track.f&&t.o===track.o&&
        t.s[0]===0&&t.s.at(-1)===1&&Math.hypot(t.x.at(-1)-track.x[0],t.y.at(-1)-track.y[0])<.01)
      if(source.length===1)track={...track,flashCharge:Math.min(itemDataFor(source[0].t).special[1],source[0].s.filter(s=>s===0).length+1)}
    }
    if(shadow.has(recorded))track={...recorded,shadow:shadow.get(recorded)}
    if(Number(bundle.meta.stage)===16&&!track.face){
      const face=turnipFaceAtSpawn(bundle,track,frameCursor(bundle,track.f))
      if(face!=null)track={...track,face:Array(track.x.length).fill(face)}
    }
    if (track.t===160) continue
    let start=0,previous=[]
    for (let j=0;j<track.x.length;j++) {
      // it_802A19E0 uses ITEM_HIT_PRESERVE when state2 enters return.
      // Its script updates damage, but the capsule's preceding center and
      // victim list survive (including a return caused by DmgDealt).
      const keepBoom=j&&itemDataFor(track.t)?.family==='boomerang'&&track.s[j]===3&&track.s[j-1]===2
      const reset=(!j || track.s?.[j]!==track.s?.[j-1])&&!keepBoom,i=track.f+j
      if(j&&track.t===99&&track.s[j-1]===0&&track.s[j]===1){
        const port=itemOwnerPort(track,j,bundle),cid=bundle.frames.cid?.[port]?.[i],state=bundle.frames.state?.[port]?.[i],age=bundle.frames.age?.[port]?.[i]
        const release=fighterDataFor(cid)?.hitboxes?.[state]?.articleSpawns?.find(s=>s.kind==='held'&&s.frame===age)
        if(release){
          // The release and its first hit can occur between two Item Update
          // records, so there is no recorded thrown-state sample at all.
          const impact={...track,s:track.s.slice(),d:track.d.slice(),vx:track.vx.slice(),vy:track.vy.slice()}
          impact.s[j]=2;impact.d[j]=bundle.frames.dir[port][i]
          impact.vx[j]=impact.d[j]*release.velocity[0]*itemDataFor(99).throwSpeed;impact.vy[j]=release.velocity[1]*itemDataFor(99).throwSpeed
          rows[i]?.push({id,track:impact,j,hits:itemSpheres(impact,j,0,bundle),previous:[],reset:true})
        }
      }
      let bombImpact=null
      let boomImpact=null
      if(!j&&itemDataFor(track.t)?.family==='chef'&&track.s[0]===1){
        // Chef is created in accessory4, after the map pass, with no
        // constructor physics. A birth-frame fade preserves the attack's
        // exact root. Every authored trajectory points forward faster than
        // the material direction threshold; the minimum speed is a proven
        // direction bound, not a guessed trajectory selection.
        const port=itemOwnerPort(track,0,bundle),frames=fighterFrames(bundle),state=frames.state[port]?.[i],age=frames.age[port]?.[i],a=itemDataFor(track.t)
        const spawn=fighterDataFor(frames.cid[port]?.[i])?.hitboxes?.[state]?.articleSpawns?.find(s=>s.kind===track.t&&s.phase===9&&s.frame===age)
        if(spawn){
          const dir=frames.dir[port][i],speed=Math.min(...a.trajectories.map(v=>v[0]))
          const rootOnly=Object.values(a.animations[0].frames).flat().every(h=>h[1]===0&&h[2]===0&&h[3]===0)
          const flight={...track,s:[0],d:[dir],vx:[dir*speed],vy:[0]}
          rows[i].push({id,track:flight,j:0,hits:rootOnly&&speed>a.velocityDirectionThreshold?itemSpheres(flight,0,0,bundle):null,previous:[],reset:true})
        }
      }
      if(!j&&itemDataFor(track.t)?.family==='needle'&&track.s[0]===4){
        // Accessory4 creates after the ordinary map pass. A needle already
        // bouncing in its first record therefore had a flight hitbox during
        // this tick's DmgDealt/Clanked pass; no preceding sample exists.
        const port=itemOwnerPort(track,0,bundle),frames=fighterFrames(bundle),state=frames.state[port]?.[i],age=frames.age[port]?.[i]
        if([344,348,470,474].includes(state)&&age>=3&&age<=18&&age%3===0){
          const dir=frames.dir[port][i],air=!!frames.air[port][i],a=itemDataFor(track.t),angle=f(f(dir*(air?f(3*Math.PI/4):f(Math.PI/2)))+f(Math.PI/2))
          const flight={...track,s:[0],d:[dir],vx:[f(-a.special[2]*f(Math.cos(angle)))],vy:[f(a.special[2]*f(Math.sin(angle)))]}
          rows[i].push({id,track:flight,j:0,hits:itemSpheres(flight,0,0,bundle),previous:[],reset:true})
        }
      }
      if(keepBoom&&Math.hypot(track.vx[j],track.vy[j])>itemDataFor(track.t).special[6]+.001&&
        track.vx[j]*track.vx[j-1]+track.vy[j]*track.vy[j-1]>0&&
        Math.abs(f(track.x[j-1]+track.vx[j])-track.x[j])<.0001&&
        Math.abs(f(track.y[j-1]+track.vy[j])-track.y[j])<.0001){
        // No map correction and no physical reversal: DmgDealt made this
        // return after collision, so sample the outgoing damage as well.
        const flight={...track,s:track.s.slice()};flight.s[j]=track.s[j-1]
        boomImpact=itemSpheres(flight,j,j-start,bundle)
      }
      if(j&&itemDataFor(track.t)?.family==='needle'&&track.s[j]!==0&&track.s[j-1]===0){
        const flight={...track,s:track.s.slice(),vx:track.vx.slice(),vy:track.vy.slice()}
        flight.s[j]=0;flight.vx[j]=track.vx[j-1];flight.vy[j]=track.vy[j-1]
        rows[i]?.push({id,track:flight,j,hits:itemSpheres(flight,j,j-start,bundle),previous,reset:false,
          needleImpact:true,mapFrom:[track.x[j-1],track.y[j-1]]})
      }
      if(j&&itemDataFor(track.t)?.family==='chef'&&track.s[j]===1&&track.s[j-1]===0&&
        (track.lifetime?.[j-1]??2)>1){
        const flight={...track,s:track.s.slice(),vx:track.vx.slice(),vy:track.vy.slice()}
        flight.s[j]=0;flight.vx[j]=track.vx[j-1];flight.vy[j]=f(track.vy[j-1]-itemDataFor(track.t).trajectories[0][2])
        rows[i]?.push({id,track:flight,j,hits:itemSpheres(flight,j,j-start,bundle),previous,reset:false,
          chefImpact:true,mapFrom:[track.x[j-1],track.y[j-1]]})
      }
      if(j&&[58,59].includes(track.t)&&track.s[j]===5&&[2,3].includes(track.s[j-1])&&j<=itemDataFor(track.t).special[0]){
        const flight={...track,s:track.s.slice(),d:track.d.slice(),vx:track.vx.slice(),vy:track.vy.slice()}
        flight.s[j]=track.s[j-1];flight.d[j]=track.d[j-1];flight.vx[j]=track.vx[j-1];flight.vy[j]=f(track.vy[j-1]-itemDataFor(track.t).gravity)
        bombImpact={hits:itemSpheres(flight,j,j-start,bundle),previous,from:[track.x[j-1],track.y[j-1]]}
      }
      // DmgDealt runs before Item Update: recover the missile's flight
      // capsule on the frame its recorded state becomes the inert explosion.
      if(j&&(track.t===95&&track.s[j]>=2&&track.s[j-1]<2||track.t===99&&track.s[j]===1&&[2,3].includes(track.s[j-1]))){
        const impact={...track,s:track.s.slice(),d:track.d.slice(),vx:track.vx.slice(),vy:track.vy.slice()}
        impact.s[j]=track.s[j-1];impact.d[j]=track.d[j-1];impact.vx[j]=track.vx[j-1];impact.vy[j]=track.vy[j-1]
        if(i>=0&&i<rows.length)rows[i].push({id,track:impact,j,hits:itemSpheres(impact,j,j-start,bundle),previous,reset:false,mapFrom:[track.x[j-1],track.y[j-1]]})
      }
      if (reset) {start=j;previous=[]}
      // Peach's hurtbox-triggered Bomber is created after item collision.
      // Its first recorded pose cannot damage a material until the next pass.
      const lateBomber=track.t===98&&j===0&&bundle.frames.state?.[itemOwnerPort(track,j,bundle)]?.[i]===359&&bundle.frames.age?.[itemOwnerPort(track,j,bundle)]?.[i]===0
      const hits=lateBomber||track.t===67&&j===0?[]:boomImpact||itemSpheres(track,j,j-start,bundle)
      if (i>=0&&i<rows.length)rows[i].push({id,track,j,hits,previous,reset,bombImpact,
        ...(itemDataFor(track.t)?.family==='joltair'?{joltAir:true,bundle}:{}),
        ...(j===track.shadowTerminal?{shadowTerminal:true,bundle,age:j-start,mapFrom:[track.x[j-1],track.y[j-1]]}:{})})
      previous=hits||[]
    }
    // Charge Shot is deleted by DmgDealt, so that final sample never reaches
    // Slippi. Its constant-velocity physics is source-defined. A map hit
    // suppresses this candidate before any material test.
    const j=track.x.length-1,i=track.f+j+1,table=itemDataFor(track.t)
    if(table?.family==='pkthunder'&&i<rows.length&&track.lifetime?.[j]>1){
      const port=itemOwnerPort(track,j,bundle),frames=bundle.frames
      if(port!=null&&[359,363].includes(frames.state[port][i])){
        const terminal={...track},[vx,vy]=pkThunderVelocity(track.vx[j],track.vy[j],Math.atan2(track.vy[j],track.vx[j]),frames.joyx?.[port]?.[i]??0,frames.joyy?.[port]?.[i]??0,table.special)
        for(const key of ['x','y','s','d','vx','vy'])terminal[key]=track[key].slice()
        terminal.x.push(f(track.x[j]+vx));terminal.y.push(f(track.y[j]+vy));terminal.vx.push(vx);terminal.vy.push(vy);terminal.s.push(0);terminal.d.push(track.d[j])
        rows[i].push({id,track:terminal,j:j+1,hits:itemSpheres(terminal,j+1,0,bundle),previous,reset:false,mapFrom:[track.x[j],track.y[j]]})
      }
    }
    if(table?.family==='joltair'&&i<rows.length){
      for(const key of ['x','y','s','d','vx','vy'])track[key]=track[key].slice()
      for(const key of ['x','y','s','d','vx','vy'])track[key].push(track[key][j])
      rows[i].push({id,track,j:j+1,hits:null,previous:[],reset:false,joltAir:true,joltTerminal:true,bundle})
    }
    const arrow=table?.family==='arrow',charge=[94,151].includes(track.t)
    if(charge&&track.s[j]===0&&i<rows.length){
      // A held shot may be released and destroyed by DmgDealt between
      // Item Updates. The recorded held history still identifies its owner;
      // the fighter callback and charge counter determine the missing shot.
      const port=itemOwnerPort(track,j,bundle),frames=fighterFrames(bundle)
      const cid=frames.cid[port]?.[i],state=frames.state[port]?.[i],age=frames.age[port]?.[i]
      const spawn=fighterDataFor(cid)?.hitboxes?.[state]?.articleSpawns?.find(s=>s.kind===track.t&&s.frame===age)
      const level=samusCharges[port]?.[i]
      if(spawn&&level!=null){
        const dir=frames.dir[port][i],root=Math.max(0,i-1),a=table.special
        const sx=f(frames.x[port][root]+dir*spawn.pos[2]),sy=f(frames.y[port][root]+spawn.pos[1])
        const vx=f(dir*f(a[2]+f(level*f((a[3]-a[2])/fighterDataFor(cid).chargeShot.max))))
        const terminal={t:track.t,o:track.o,f:i,x:[f(sx+vx)],y:[sy],s:[level+1],d:[dir],vx:[vx],vy:[0]}
        rows[i].push({id,track:terminal,j:0,hits:itemSpheres(terminal,0,0,bundle),previous:[],reset:true,
          chargeRelease:{frames,port,root,target:[sx,sy]}})
      }
    }
    if(['needle','pkfire','jolt'].includes(table?.family)&&track.s[j]===0&&i<rows.length&&(track.lifetime?.[j]??table.special[0]-j)>1){
      const terminal={...track}
      for(const key of ['x','y','s','d','vx','vy'])terminal[key]=track[key].slice()
      terminal.x.push(f(track.x[j]+track.vx[j]));terminal.y.push(f(track.y[j]+track.vy[j]))
      for(const key of ['s','d','vx','vy'])terminal[key].push(track[key][j])
      rows[i].push({id,track:terminal,j:j+1,hits:itemSpheres(terminal,j+1,j+1-start,bundle),previous,reset:false,
        needleImpact:table.family==='needle'||table.family==='jolt',pkfireImpact:table.family==='pkfire',mapFrom:[track.x[j],track.y[j]]})
    }
    if(table?.family==='fireball'&&track.s?.[j]===0&&i<rows.length&&
      (track.lifetime?track.lifetime[j]>1:j<([105,132].includes(track.t)?table.special[1]:table.special[2])-1)){
      const terminal={...track}
      for(const key of ['x','y','s','d','vx','vy'])terminal[key]=track[key].slice()
      const vy=Math.max(-table.maxFallSpeed,f(track.vy[j]-table.gravity))
      terminal.x.push(f(track.x[j]+track.vx[j]));terminal.y.push(f(track.y[j]+vy))
      for(const key of ['s','d','vx'])terminal[key].push(track[key][j])
      terminal.vy.push(vy)
      rows[i].push({id,track:terminal,j:j+1,hits:itemSpheres(terminal,j+1,j+1-start,bundle),previous,reset:false,
        fireballTerminal:true,age:j+1-start,bundle,mapFrom:[track.x[j],track.y[j]]})
    }
    if((arrow||charge)&&track.s?.[j]>0&&j-start<(arrow?table.special[0]+table.special[6]:table.special[0])-2&&i<rows.length){
      const terminal={...track}
      for(const key of ['x','y','s','d','vx','vy'])terminal[key]=track[key].slice()
      const vy=arrow?f(track.vy[j]-Math.abs(table.special[7])):track.vy[j]
      terminal.x.push(f(track.x[j]+track.vx[j]));terminal.y.push(f(track.y[j]+vy))
      for(const key of ['s','d','vx'])terminal[key].push(track[key][j])
      terminal.vy.push(vy)
      rows[i].push({id,track:terminal,j:j+1,hits:itemSpheres(terminal,j+1,j+1-start,bundle),previous,reset:false,mapFrom:[track.x[j],track.y[j]],mapRoot:arrow})
    }
  }
  return rows
}

// mpCheckAllRemap tests the moving item's root against all four directed
// collision-line kinds, including soft floors. A laser survives that map
// callback and its damage pass, then expires at the following priority 1.
export function itemMapCrossing(x0,y0,x1,y1,lines,oldLines=lines) {
  return !!itemRayContact(x0,y0,x1,y1,lines,oldLines)
}
export function itemRayContact(x0,y0,x1,y1,lines,oldLines=lines) {
  let contact=null
  for(const [id,flags,ax,ay,bx,by] of lines){
    const old=oldLines.find(l=>l[0]===id)
    // The only moving lines in Inishie1 are translating horizontal pulleys.
    const px=x0+(old?ax-old[2]:0),py=y0+(old?ay-old[3]:0)
    const lx=bx-ax,ly=by-ay,dx=x1-px,dy=y1-py
    let x,y,t
    if(Math.abs(ly)<.0001&&(flags&3)){
      if(Math.max(px,x1)<Math.min(ax,bx)||Math.min(px,x1)>Math.max(ax,bx)||Math.abs(dy)<.0001)continue
      if(ax<bx?(py<y1||py-ay<-.0001||y1-ay>.0001):(py>y1||y1-ay<-.0001||py-ay>.0001))continue
      t=(ay-py)/dy;x=px+t*dx;y=ay
      if(x<Math.min(ax,bx)-.1||x>Math.max(ax,bx)+.1)continue
      x=Math.max(Math.min(ax,bx),Math.min(Math.max(ax,bx),x))
    }else if(Math.abs(lx)<.0001&&(flags&12)){
      if(Math.max(py,y1)<Math.min(ay,by)||Math.min(py,y1)>Math.max(ay,by)||Math.abs(dx)<.0001)continue
      if(ay<by?(px>x1||x1-ax<-.0001||px-ax>.0001):(px<x1||px-ax<-.0001||x1-ax>.0001))continue
      t=(ax-px)/dx;x=ax;y=py+t*dy
      if(y<Math.min(ay,by)-.1||y>Math.max(ay,by)+.1)continue
      y=Math.max(Math.min(ay,by),Math.min(Math.max(ay,by),y))
    }else{
      const before=lx*(py-ay)-ly*(px-ax),after=lx*(y1-ay)-ly*(x1-ax)
      if(before<0||after>0||before===after)continue
      t=before/(before-after);x=px+t*dx;y=py+t*dy
      if(x<Math.min(ax,bx)||x>Math.max(ax,bx)||y<Math.min(ay,by)||y>Math.max(ay,by))continue
    }
    // Native axis intersections first require overlapping ray/line bounds,
    // then clamp an intersection within 0.1u of an endpoint. A ray entirely
    // above a wall remains outside, including a needle at floorY + .0001.
    if(!contact||t<contact.t)contact={x:f(x),y:f(y),normal:[-ly/Math.hypot(lx,ly),lx/Math.hypot(lx,ly)],t,line:id}
  }
  return contact
}

// Item_80267130 and it_80275BC8 sweep a growing fixed ECB from the
// owner's previous ECB center to the attachment, in at-most-6u steps.
function articleSpawnCollision(frames,port,root,kind,dir,target,lines,oldLines) {
  const bounds=fighterDataFor(frames.cid[port][root])?.ecb?.[frames.state[port][root]]?.[frames.age[port][root]]
  if(!bounds)return null
  const from=[frames.x[port][root],f(frames.y[port][root]+f((bounds[3]+(frames.air?.[port]?.[root]?bounds[2]:0))*.5))]
  const distance=Math.max(...target.map((v,k)=>Math.abs(v-from[k]))),steps=distance>6?Math.trunc(distance/6)+1:1
  const velocity=target.map((v,k)=>f((v-from[k])/steps));let point=from
  for(let n=0;n<steps;n++){
    const next=point.map((v,k)=>f(v+velocity[k]))
    const contact=itemMapContact({t:kind,x:[next[0]],y:[next[1]],d:[dir]},0,lines,oldLines,point,n/steps,(n+1)/steps)
    point=contact?[contact.x,contact.y]:next
  }
  return point
}

// Fox/Falco fire in Fighter_procAnim (priority 1); accessory4 is a fallback.
// Their DAT command-flag events and posed muzzle offsets are baked with the
// fighter. This path is necessary when Slippi's 15-item record cap hides
// every projectile behind the stage's older material objects.
// These ft/kinds action-table ranges invoke article callbacks without an
// unrecorded adapter below. Inishie1's record cap cannot prove their absence.
// Keep them explicit: a fighter-only move (including copied Puff) is not a gap.
const hiddenArticleStates={
  5:[[342,342],[345,345]],
  9:[[366,366],[368,368]],10:[[341,342],[357,358]],11:[[341,342],[357,358]],
  14:[[364,365],[367,367]],
  19:[[343,348]],
  4:[[369,370],[380,381],[385,392],
    [444,444],[447,447],[450,450],[452,454],[539,539],[542,542]],
}
export function unrecordedLaserHistory(bundle) {
  const frames=fighterFrames(bundle),live=[],samus=unrecordedSamusHistory(bundle),link=unrecordedLinkHistory(bundle),held=unrecordedHeldHistory(bundle),bomber=unrecordedBomberHistory(bundle)
  const blasters=unrecordedBlasterHistory(bundle)
  const pans=unrecordedChefPanHistory(bundle)
  const fire=unrecordedFireballHistory(bundle)
  const chef=unrecordedChefHistory(bundle)
  const shadow=unrecordedShadowHistory(bundle)
  const needles=unrecordedNeedleHistory(bundle)
  const ness=unrecordedNessHistory(bundle),pkthunder=unrecordedPKThunderHistory(bundle)
  const thunder=unrecordedThunderHistory(bundle)
  const jolt=unrecordedJoltHistory(bundle)
  const ghosts=frames.x.map(()=>[])
  let nextId=0
  return (i,lines,oldLines,afterCeilingRng=null)=>{
    const entries=[]
    for(let port=0;port<frames.x.length;port++){
      const state=frames.state[port][i],cid=frames.cid[port][i]
      if(hiddenArticleStates[cid]?.some(([lo,hi])=>state>=lo&&state<=hi)||
        state>=94&&state<=119&&![6,9,20].includes(cid))
        entries.push({id:`unsupported-article:${port}`,hits:null,previous:[]})
      if((cid===1||cid===22)&&[348,349,351,352].includes(state)){
        const pos=[frames.x[port][Math.max(0,i-1)],frames.y[port][Math.max(0,i-1)]]
        if(!i||![348,349,351,352].includes(frames.state[port][i-1]))ghosts[port]=[pos,pos,pos,pos]
        else ghosts[port]=[pos,...ghosts[port].slice(0,3)]
      }
    }
    for(let k=live.length-1;k>=0;k--){
      const shot=live[k],age=i-shot.track.f,table=itemDataFor(shot.track.t)
      const illusion=table.family==='illusion'
      // Illusion is born in Fighter_procAnim, before the item priority-1
      // pass, so its five-tick lifetime already loses one tick at birth.
      if(shot.dead||age>=table.special[0]-1||illusion&&![347,348,349,350,351,352].includes(frames.state[shot.port][i])){live.splice(k,1);continue}
      const t=shot.track,j=t.x.length,[x,y]=illusion?ghosts[shot.port][1]:[f(t.x[j-1]+shot.vx),f(t.y[j-1]+shot.vy)]
      shot.dead=!illusion&&itemMapCrossing(t.x[j-1],t.y[j-1],x,y,lines,oldLines)
      t.x.push(x);t.y.push(y);t.d.push(shot.dir);t.vx.push(shot.vx);t.vy.push(shot.vy);t.s.push(t.s[0])
      const hits=itemSpheres(t,j,age,bundle)
      entries.unshift({id:shot.id,track:t,j,hits,previous:shot.previous,onHit:()=>{if(!illusion)shot.dead=true}})
      shot.previous=hits||[]
    }
    for(let port=0;port<frames.x.length;port++){
      const state=frames.state[port][i],age=frames.age[port][i],cid=frames.cid[port][i],dir=frames.dir?.[port]?.[i]
      const spawns=fighterDataFor(cid)?.hitboxes?.[state]?.articleSpawns||[]
      const oldState=frames.state[port][i-1]
      const continuing=state===oldState||[348,351].includes(state)&&[348,351].includes(oldState)
      const before=i&&continuing&&age>=frames.age[port][i-1]?frames.age[port][i-1]:-1
      for(const spawn of spawns){
        if(!['laser','illusion'].includes(itemDataFor(spawn.kind)?.family))continue
        if(spawn.frame<=before||spawn.frame>age)continue
        const illusion=itemDataFor(spawn.kind)?.family==='illusion'
        const vx=f(dir*spawn.velocity[0]),vy=dir===1?spawn.velocity[1]:f(Math.sin(Math.fround(Math.PI))*Math.abs(vx))
        const root=Math.max(0,i-1)
        let sx=f(frames.x[port][root]+dir*spawn.pos[2]),sy=f(frames.y[port][root]+spawn.pos[1])
        if(!illusion){
          // Item_80267130 first sweeps the fixed ECB from the owner's ECB
          // center to the muzzle. A gun inside a brick is pushed back to
          // its face before this frame's laser physics and map callback.
          const point=articleSpawnCollision(frames,port,root,spawn.kind,dir,[sx,sy],lines,oldLines)
          if(!point){entries.push({id:'laser-spawn-unknown',hits:null,previous:[]});continue}
          ;[sx,sy]=point
        }
        const [x,y]=illusion?ghosts[port][1]:[f(sx+vx),f(sy+vy)]
        const t={t:spawn.kind,o:port,f:i,s:[illusion?Number(!!frames.air[port][root]):0],x:[x],y:[y],d:[dir],vx:[vx],vy:[vy]}
        const hits=itemSpheres(t,0,0,bundle),shot={id:`article:${nextId++}`,track:t,port,vx,vy,dir,previous:hits||[],dead:!illusion&&itemMapCrossing(sx,sy,x,y,lines,oldLines)}
        // Both laser tables use itFoxLaser_Logic94_Clanked for DmgDealt.
        // Material resolution removes them after all hits in this tick.
        live.push(shot);entries.push({id:shot.id,track:t,j:0,hits,previous:[],onHit:()=>{if(!illusion)shot.dead=true}})
      }
    }
    const shadowEntries=shadow(i,lines,oldLines)
    if(afterCeilingRng)for(const entry of shadowEntries)for(let n=0;n<(entry.beforeCeilingDraws||0);n++)afterCeilingRng.float()
    return [...entries,...blasters(i),...pans(i),...shadowEntries,...samus(i,lines,oldLines),...link(i,lines,oldLines),...held(i,lines,oldLines),...bomber(i),...fire(i,lines,oldLines),...chef(i,lines,oldLines,afterCeilingRng),...needles(i,lines,oldLines,afterCeilingRng),...ness(i,lines,oldLines),...thunder(i,lines,oldLines),...jolt(i,lines,oldLines),...pkthunder(i,lines,oldLines)]
  }
}

// it_802AE8A8 creates the held gun at the pre-physics fighter root with
// initial_collision=false. Its empty map callback never replaces the
// default [-4,4] x [0,8] CollData rectangle (mpColl_SetECBSource_Fixed).
// Item animation removes the gun before Ground when its owner leaves N.
function unrecordedBlasterHistory(bundle) {
  const frames=fighterFrames(bundle),live=[];let serial=0
  const config=(cid,state)=>cid===1||cid===22?[341,cid===1?52:53]:cid===4&&state>=423&&state<=428?[423,138]:cid===4&&state>=520&&state<=525?[520,139]:null
  return i=>{
    for(let k=live.length-1;k>=0;k--)if(i>=live[k].track.expiresAt)live.splice(k,1)
    for(let port=0;port<frames.x.length;port++){
      const cid=frames.cid[port][i],state=frames.state[port][i],c=config(cid,state)
      if(!c||![c[0],c[0]+3].includes(state))continue
      const old=frames.state[port][i-1]
      if(old>=c[0]&&old<c[0]+6&&frames.age[port][i]>=frames.age[port][i-1])continue
      const root=Math.max(0,i-1)
      let end=i+1
      while(end<bundle.meta.n&&frames.cid[port][end]===cid&&frames.state[port][end]>=c[0]&&frames.state[port][end]<c[0]+6)end++
      // Landing clears the gun in Fighter_Map, after this tick's Ground.
      if([42,43].includes(frames.state[port][end]))end++
      const track={t:c[1],o:port,f:i,x:[frames.x[port][root]],y:[frames.y[port][root]],s:[0],fixedEcb:[-4,4,0,8],expiresAt:end}
      live.push({id:`blaster:${serial++}`,track,j:0,hits:[],previous:[]})
    }
    return live.slice()
  }
}

// Kirby's pan attaches its model to LThumbNb, but its inert map callback
// retains the constructor's fixed CollData. Item animation deletes it as
// soon as the owner leaves Chef, before the next Ground restoration check.
function unrecordedChefPanHistory(bundle) {
  const frames=fighterFrames(bundle),live=[];let serial=0
  return i=>{
    for(let k=live.length-1;k>=0;k--)if(i>=live[k].track.expiresAt)live.splice(k,1)
    for(let port=0;port<frames.x.length;port++){
      const state=frames.state[port][i]
      if(frames.cid[port][i]!==4||![510,511].includes(state)||[510,511].includes(frames.state[port][i-1]))continue
      const spawn=fighterDataFor(4)?.hitboxes[state]?.articleSpawns?.find(s=>s.kind===156&&s.frame===frames.age[port][i]),dir=frames.dir[port][i]
      if(!spawn){live.push({id:`pan-unknown:${serial++}`,track:{expiresAt:i+1},hits:null,previous:[]});continue}
      let end=i+1
      while(end<bundle.meta.n&&frames.cid[port][end]===4&&[510,511].includes(frames.state[port][end]))end++
      const track={t:156,o:port,f:i,x:[f(frames.x[port][i]+dir*spawn.pos[2])],y:[f(frames.y[port][i]+spawn.pos[1])],s:[0],fixedEcb:[-4,4,0,8],expiresAt:end}
      live.push({id:`pan:${serial++}`,track,j:0,hits:[],previous:[]})
    }
    return live.slice()
  }
}

// itNesspkthunderball_UnkMotion0_Phys. The stick steers the velocity by at
// most the authored turn radius; trailing spheres use the saved pre-move
// head positions at intervals of two ticks.
export function pkThunderVelocity(vx,vy,angle,stickX,stickY,a) {
  if(Math.abs(stickX)>a[3]||Math.abs(stickY)>a[3]){
    const dot=f(f(vx*stickX)+f(vy*stickY)),length=f(Math.sqrt(f(f(vx*vx)+f(vy*vy)))*Math.sqrt(f(f(stickX*stickX)+f(stickY*stickY))))
    const delta=f(Math.acos(Math.max(-1,Math.min(1,f(dot/length))))),cross=f(f(vx*stickY)-f(vy*stickX))
    const turn=delta>=f(Math.PI/4)?f(a[4]*f(Math.PI/180)):f(delta/f(45/a[4]))
    angle=f(angle+Math.sign(cross)*turn)
    while(angle< -2*Math.PI)angle=f(angle+f(2*Math.PI))
    while(angle>2*Math.PI)angle=f(angle-f(2*Math.PI))
    vx=f(a[1]*f(Math.cos(angle)));vy=f(a[1]*f(Math.sin(angle)))
  }
  return [vx,vy,angle]
}
export function unrecordedPKThunderHistory(bundle) {
  const frames=fighterFrames(bundle),live=[];let serial=0
  return (i,lines,oldLines)=>{
    const entries=[]
    for(let port=0;port<frames.x.length;port++){
      if(frames.cid[port][i]!==8||![359,363].includes(frames.state[port][i])||[359,363].includes(frames.state[port][i-1]))continue
      const spawn=fighterDataFor(8)?.hitboxes[frames.state[port][i]]?.articleSpawns?.find(s=>s.kind===69),a=itemDataFor(69)
      if(!spawn||!a){entries.push({id:`pkthunder-unknown:${port}`,hits:null,previous:[]});continue}
      const dir=frames.dir[port][i],root=Math.max(0,i-1),x=f(frames.x[port][root]+dir*spawn.pos[2]),y=f(frames.y[port][root]+spawn.pos[1]),angle=f(a.special[2]*f(Math.PI/180))
      live.push({id:`pkthunder:${serial++}`,port,dir,x,y,angle,vx:0,vy:a.special[1],born:i,positions:Array.from({length:16},()=>[x,y]),previous:[],trailPrevious:[]})
      entries.push({id:'pkthunder-spawn',hits:[],previous:[],beforeCeilingDraws:a.spawnDraws})
    }
    for(let k=live.length-1;k>=0;k--){
      const s=live[k],a=itemDataFor(69),age=i-s.born
      if(s.dead||![359,363].includes(frames.state[s.port][i])||age>=a.special[0]-1){live.splice(k,1);continue}
      const from=[s.x,s.y]
      ;[s.vx,s.vy,s.angle]=pkThunderVelocity(s.vx,s.vy,s.angle,frames.joyx?.[s.port]?.[i]??0,frames.joyy?.[s.port]?.[i]??0,a.special)
      s.positions=[from,...s.positions.slice(0,15)];s.x=f(s.x+s.vx);s.y=f(s.y+s.vy)
      const track={t:69,o:s.port,f:i,x:[s.x],y:[s.y],d:[s.dir],s:[0],vx:[s.vx],vy:[s.vy]}
      if(itemMapContact(track,0,lines,oldLines,from)){live.splice(k,1);continue}
      const hits=itemSpheres(track,0,0,bundle)
      entries.push({id:s.id,track,j:0,hits,previous:s.previous,onHit:()=>{s.dead=true}});s.previous=hits||[]
      for(let n=0;n<Math.min(6,Math.floor(age/2)+1);n++){
        const [x,y]=s.positions[2*n],t={...track,t:[70,70,70,71,72,73][n],x:[x],y:[y],vx:[0],vy:[0]},hs=itemSpheres(t,0,0,bundle)
        entries.push({id:`${s.id}:trail${n}`,track:t,j:0,hits:hs,previous:s.trailPrevious[n]||[]});s.trailPrevious[n]=hs||[]
      }
    }
    return entries
  }
}

// TJolt's parent follows the preceding child joint6 pose. A ray contact
// anchors a fresh child animation to the surface normal; it is not a
// projectile traveling horizontally along a floor.
function joltSpawnPosition(frames,port,i,spawn,lines,oldLines) {
  const root=Math.max(0,i-1),dir=frames.dir[port][i]
  const x=f(frames.x[port][root]+dir*spawn.pos[2]),y=f(frames.y[port][root]+spawn.pos[1])
  const bounds=fighterDataFor(frames.cid[port][root])?.ecb?.[frames.state[port][root]]?.[frames.age[port][root]]
  if(!bounds)return null
  const from=[frames.x[port][root],f(frames.y[port][root]+f((bounds[3]+(frames.air[port][root]?bounds[2]:0))*.5))]
  // Spawn first corrects the fixed ECB. Its extra ray then resets a shot
  // crossing a surface to the *fighter ECB center*, not the contact point.
  const contact=itemMapContact({t:spawn.kind,x:[x],y:[y],d:[dir]},0,lines,oldLines,from)
  const collision=contact?[contact.x,contact.y]:[x,y]
  return {position:itemRayContact(...from,x,y,lines,oldLines)?from:collision,collision}
}
export function unrecordedJoltHistory(bundle,{missingOnly=false}={}) {
  const frames=fighterFrames(bundle),live=[];let serial=0
  return (i,lines,oldLines=lines)=>{
    const entries=[]
    for(let port=0;port<frames.x.length;port++){
      const cid=frames.cid[port][i],state=frames.state[port][i],age=frames.age[port][i]
      if(![4,12,23].includes(cid))continue
      const old=frames.state[port][i-1],oldAge=frames.age[port][i-1]
      const motions=cid===4?(state>=500?[526,527]:[429,430]):[341,342]
      const before=motions.includes(state)&&motions.includes(old)&&age>=oldAge?oldAge:-1
      // Fighter animation creates the shot before input/map. Landing can
      // replace SpecialAirN with SpecialN later in this same frame.
      const spawnState=motions.includes(frames.pre_state?.[port]?.[i])?frames.pre_state[port][i]:state
      for(const spawn of fighterDataFor(cid).hitboxes[spawnState]?.articleSpawns||[]){
        if(![89,91,147,149].includes(spawn.kind)||spawn.frame<=before||spawn.frame>age)continue
        // A projectile can be created and deal damage before its first raw
        // Item Update. Recorded parents/children stay authoritative elsewhere.
        if(missingOnly&&(bundle.items||[]).some(t=>t.f===i&&[spawn.kind,spawn.kind+1].includes(t.t)&&itemOwnerPort(t,0,bundle)===port))continue
        const a=itemDataFor(spawn.kind),dir=frames.dir[port][i],pos=joltSpawnPosition(frames,port,i,spawn,lines,oldLines)
        if(!pos){entries.push({id:'jolt-spawn-unknown',hits:null,previous:[]});continue}
        const [x,y]=pos.position,points=fixedItemEcbPoints(a,dir)
        const fixed={fixedPosition:pos.collision,fixedEcb:[points[2][0],points[3][0],points[0][1],points[1][1]]}
        const angle=dir===1?a.special[1]:f(Math.PI+Math.abs(a.special[1]))
        live.push({id:`jolt:${serial++}`,port,kind:spawn.kind,table:a,x,y,dir,vx:f(a.special[2]*Math.cos(angle)),vy:f(a.special[2]*Math.sin(angle)),life:a.special[0],born:i,releaseDraws:spawn.releaseDraws,previous:[],fixed,track:{t:spawn.kind,o:port,f:i,x:[],y:[],s:[],d:[],vx:[],vy:[],lifetime:[],...fixed}})
      }
    }
    for(const shot of live){
      if(shot.dead)continue
      if(--shot.life<=0){shot.dead=true;shot.track.expiresAt=i;continue}
      const x0=shot.x,y0=shot.y
      if(shot.child){
        const a=itemDataFor(shot.kind+1),pos=a.animations[0].joint6[shot.age]
        if(!pos||shot.age>=25){shot.dead=true;shot.track.expiresAt=i;continue}
        const angle=Math.atan2(...shot.normal),c=Math.cos(angle),s=Math.sin(angle)
        shot.x=f(shot.anchor[0]+a.scale*(c*shot.childDir*pos[2]+s*pos[1]))
        shot.y=f(shot.anchor[1]+a.scale*(-s*shot.childDir*pos[2]+c*pos[1]));shot.age++
      }else {shot.x=f(shot.x+shot.vx);shot.y=f(shot.y+shot.vy)}
      const contact=itemRayContact(x0,y0,shot.x,shot.y,lines,oldLines)
      let reset=false
      if(contact){
        shot.x=contact.x;shot.y=contact.y;shot.anchor=[shot.x,shot.y];shot.normal=contact.normal;shot.age=1;reset=true
        if(!shot.child){
          let angle=Math.atan2(shot.vy,shot.vx)-Math.atan2(contact.normal[1],contact.normal[0]);angle=(angle%(2*Math.PI)+2*Math.PI)%(2*Math.PI)
          shot.childDir=angle<Math.PI?-1:1;shot.child=true
          shot.track={t:shot.kind+1,o:shot.port,f:i,x:[],y:[],s:[],d:[],vx:[],vy:[],joltPose:[],...shot.fixed}
        }
      }
      const t=shot.track,j=t.x.length
      // Animation deletes an exhausted parent/child before Ground checks
      // restoration. A surface re-anchor restarts the child's 25-tick clock.
      t.expiresAt=Math.min(i+shot.life,shot.child?i+26-shot.age:Infinity)
      t.x.push(shot.child?shot.anchor[0]:shot.x);t.y.push(shot.child?shot.anchor[1]:shot.y);t.s.push(0);t.d.push(shot.child?shot.childDir:shot.dir);t.vx.push(shot.child?0:shot.vx);t.vy.push(shot.child?0:shot.vy)
      if(shot.child)t.joltPose.push({age:shot.age,normal:shot.normal});else t.lifetime.push(shot.life)
      const hits=itemSpheres(t,j,shot.child?shot.age:i-shot.born,bundle)
      entries.push({id:shot.id,track:t,j,hits,previous:reset?[]:shot.previous,reset,afterCeilingDraws:shot.born===i?shot.releaseDraws||0:0,onHit:()=>{shot.dead=true;t.expiresAt=i+1}})
      shot.previous=hits||[]
    }
    return entries
  }
}

// ftPk_SpecialLw_SpawnEffect / itPikachuthunder. The four segments retain
// their downward velocity when their tail shrinks; only the first maps.
export function unrecordedThunderHistory(bundle) {
  const frames=fighterFrames(bundle),live=[],spawned=[];let serial=0
  return (i,lines,oldLines=lines)=>{
    const entries=[]
    const stop=shot=>{
      if(shot.state===2)return
      shot.state=2;shot.life=Math.abs(shot.table.special[1]/shot.speed)
      if(shot.next)shot.next.stopY=shot.y
    }
    for(const shot of live){
      if(shot.dead)continue
      const t=shot.track,a=shot.table,j=t.x.length
      if(!shot.segment&&shot.state===1&&[361,365].includes(frames.state[shot.port][i])&&
        ![361,365].includes(frames.state[shot.port][i-1]))stop(shot)
      if(shot.state===0){if(shot.delay--<=0){shot.state=1;shot.life=a.special[0]}}
      else if(--shot.life<=0){shot.dead=true;continue}
      const oldY=shot.y
      if(shot.state)shot.y=f(shot.y+shot.speed)
      t.x.push(shot.x);t.y.push(shot.y);t.s.push(shot.state);t.d.push(-1);t.vx.push(0);t.vy.push(shot.state?shot.speed:0);t.lifetime.push(shot.life)
      let draws=0
      if(shot.state===1){
        if(!shot.segment&&itemMapContact(t,j,lines.filter(l=>(l[1]&15)===1),oldLines,[shot.x,oldY])){stop(shot);draws=a.mapDraws||0}
        else if(shot.segment&&shot.stopY!=null&&shot.y<=shot.stopY)stop(shot)
        t.s[j]=shot.state;t.lifetime[j]=shot.life
      }
      const hits=itemSpheres(t,j,j,bundle)
      entries.push({id:shot.id,track:t,j,hits,previous:shot.previous,beforeCeilingDraws:draws});shot.previous=hits||[]
    }
    for(let port=0;port<frames.x.length;port++){
      const cid=frames.cid[port][i],state=frames.state[port][i],age=frames.age[port][i]
      if(![12,23].includes(cid))continue
      if(state<359||state>366){spawned[port]=false;continue}
      if(spawned[port])continue // Loop animation repeats; the retained x0 does not.
      const cfg=fighterDataFor(cid).thunder,move=fighterDataFor(cid).hitboxes[state]
      const before=state===frames.state[port][i-1]?frames.age[port][i-1]:-1
      for(const spawn of move?.articleSpawns||[]){
        if(![81,82].includes(spawn.kind)||spawn.frame<=before||spawn.frame>age)continue
        spawned[port]=true
        let prior=null
        for(let n=0;n<cfg.count;n++){
          const a=itemDataFor(spawn.kind),x=frames.x[port][i],y=f(frames.y[port][i]+spawn.pos[1])
          const t={t:spawn.kind,o:port,f:i,x:[x],y:[y],s:[0],d:[-1],vx:[0],vy:[0],lifetime:[a.special[0]]}
          const shot={id:`thunder:${serial++}`,track:t,table:a,port,segment:n,delay:n*cfg.delay,speed:cfg.speed,x,y,state:0,life:a.special[0],previous:[]}
          if(prior)prior.next=shot;prior=shot;live.push(shot)
          entries.push({id:shot.id,track:t,j:0,hits:[],previous:[],afterCeilingDraws:n?0:a.spawnDraws||0})
        }
      }
    }
    return entries
  }
}

// Ness's PK Flash charges in item animation, then creates its explosion
// there. PK Fire is a late accessory projectile; its pillar starts after
// material resolution and cannot hit another material until the next pass.
export function unrecordedNessHistory(bundle) {
  const frames=fighterFrames(bundle),live=[]
  let serial=0
  const make=(kind,i,port,x,y,dir,vx=0,vy=0)=>({id:`ness:${serial++}`,port,dir,vx,vy,x,y,state:0,charge:0,life:itemDataFor(kind).special[0],previous:[],
    track:{t:kind,o:port,f:i,x:[],y:[],s:[],d:[],vx:[],vy:[],lifetime:[]}})
  return (i,lines,oldLines=lines)=>{
    const entries=[]
    const append=(shot,age,late=false)=>{
      const t=shot.track,j=t.x.length
      t.x.push(shot.x);t.y.push(shot.y);t.s.push(shot.state);t.d.push(shot.dir);t.vx.push(shot.vx);t.vy.push(shot.vy);t.lifetime.push(shot.life)
      const hits=late?[]:itemSpheres(t,j,age,bundle)
      const entry={id:shot.id,track:t,j,hits,previous:shot.previous,onHit:()=>{
        if(t.t!==66||shot.dead)return
        shot.dead=true
        const pillar=make(67,i,shot.port,shot.x,f(shot.y+itemDataFor(66).special[1]),shot.dir)
        live.push(pillar)
        return append(pillar,0,true)
      }}
      shot.previous=hits||[]
      return entry
    }
    for(const shot of live.slice()) {
      const t=shot.track,a=itemDataFor(t.t),age=i-t.f
      if(shot.dead)continue
      const from=[shot.x,shot.y]
      if(a.family==='pkflash') {
        if(shot.state===0) {
          shot.charge=Math.min(a.special[1],shot.charge+1)
          const state=frames.pre_state?.[shot.port]?.[i]??frames.state[shot.port][i-1]
          if(![349,353,436,440].includes(state)||shot.life<=1){shot.state=1;shot.delay=0;shot.life=a.special[10]}
        } else if(shot.state===1&&++shot.delay>=a.special[10]-2) {
          const blast=make(t.t===68?78:146,i,shot.port,shot.x,shot.y,shot.dir)
          blast.track.flashCharge=shot.charge;live.push(blast);shot.dead=true
          entries.push(append(blast,0));continue
        }
        if(--shot.life<=0){shot.dead=true;continue}
        if(shot.state===0) {
          const stick=frames.joyx?.[shot.port]?.[i]??0
          if([349,353,436,440].includes(frames.state[shot.port][i])&&Math.abs(stick)>.2)shot.vx=Math.max(-a.special[8],Math.min(a.special[8],f(shot.vx+f(stick*a.special[6]))))
          shot.vy=Math.max(-a.special[9],f(shot.vy-a.special[7]))
        }else shot.vx=shot.vy=0
      } else if(a.family==='pkexplode') {
        if(age+2>=a.animations[0].end){shot.dead=true;continue}
      } else {
        if(--shot.life<=0){shot.dead=true;continue}
        if(t.t===67)shot.vy=Math.max(-a.maxFallSpeed,f(shot.vy-a.gravity))
      }
      shot.x=f(shot.x+shot.vx);shot.y=f(shot.y+shot.vy)
      const temp={t:t.t,x:[shot.x],y:[shot.y],d:[shot.dir]}
      const contacts=a.family==='pkflash'&&!shot.state?resolveItemMap(temp,0,lines,oldLines,from):[]
      const contact=contacts.at(-1)||(a.family==='pkexplode'||shot.state?null:itemMapContact(temp,0,t.t===66?lines.filter(l=>(l[1]&15)!==2):lines,oldLines,from))
      if(t.t===66&&itemWallCornerCrossing(temp,0,lines,from)){shot.dead=true;continue}
      if(contact) {
        if(t.t===66&&contact.type!==2){shot.dead=true;continue}
        if(a.family==='pkflash'){shot.state=2;shot.life=a.special[10]}
        shot.x=contacts.length?temp.x[0]:contact.x;shot.y=contacts.length?temp.y[0]:contact.y
        if(t.t===67){shot.vy=0;if(contact.type>=4)shot.vx=0}
      }
      entries.push(append(shot,age))
    }
    for(let port=0;port<frames.x.length;port++) {
      const cid=frames.cid[port][i],state=frames.state[port][i],age=frames.age[port][i],old=frames.state[port][i-1]
      const move=fighterDataFor(cid)?.hitboxes?.[state],prior=fighterDataFor(cid)?.hitboxes?.[old]
      const same=move?.motion.replace('Air','')===prior?.motion.replace('Air',''),before=i&&same&&age>=frames.age[port][i-1]?frames.age[port][i-1]:-1
      for(const spawn of move?.articleSpawns||[]) {
        if(![66,68,145].includes(spawn.kind)||spawn.frame<=before||spawn.frame>age)continue
        const a=itemDataFor(spawn.kind),flash=a.family==='pkflash'
        if(flash&&!prior?.motion.includes('Start'))continue
        const dir=frames.dir[port][i],root=spawn.phase===1?Math.max(0,i-1):i
        const shot=make(spawn.kind,i,port,f(frames.x[port][root]+dir*spawn.pos[2]),f(frames.y[port][root]+spawn.pos[1]),dir,
          flash?f(-a.special[5]*f(Math.cos(f(f(f(Math.PI/180)*a.special[4]*dir)+f(Math.PI/2))))):f(dir*spawn.velocity[0]),
          flash?f(a.special[5]*f(Math.sin(f(f(f(Math.PI/180)*a.special[4]*dir)+f(Math.PI/2))))):f(spawn.velocity[1]))
        if(spawn.kind===145&&bundle.meta.stage===19){
          // A copied Flash constructor can call a brick's Cb2 before the
          // replay's input RNG anchor. The close-corner spawn still needs
          // its pre-map JObj/CollData certified; free flight is certified by
          // recorded Item Updates. Bound the whole initial sweep so an
          // unresolved constructor cannot silently leave a brick visible.
          const bounds=fighterDataFor(cid)?.ecb?.[frames.state[port][root]]?.[frames.age[port][root]],points=fixedItemEcbPoints(a,dir)
          const x=frames.x[port][root],y=frames.y[port][root]+(bounds?(bounds[2]+bounds[3])*.5:0)
          const left=Math.min(x,shot.x)+points[2][0],right=Math.max(x,shot.x)+points[3][0]
          const bottom=Math.min(y,shot.y)+points[0][1],top=Math.max(y,shot.y)+points[1][1]
          if(lines.some(l=>(l[1]&15)===2&&Math.max(l[2],l[4])>=left&&Math.min(l[2],l[4])<=right&&Math.max(l[3],l[5])>=bottom&&Math.min(l[3],l[5])<=top))entries.push({id:`pkflash-spawn-map-unknown:${port}`,hits:null,previous:[]})
        }
        if(flash){
          shot.charge=1;shot.life--;const from=[shot.x,shot.y],stick=frames.joyx?.[port]?.[i]??0
          if(Math.abs(stick)>.2)shot.vx=Math.max(-a.special[8],Math.min(a.special[8],f(shot.vx+f(stick*a.special[6]))))
          shot.vy=Math.max(-a.special[9],f(shot.vy-a.special[7]));shot.x=f(shot.x+shot.vx);shot.y=f(shot.y+shot.vy)
          const contact=itemMapContact({t:spawn.kind,x:[shot.x],y:[shot.y],d:[dir]},0,lines,oldLines,from)
          if(contact){shot.x=contact.x;shot.y=contact.y;shot.state=2;shot.life=a.special[10]}
        }else{
          // Item_InitSpawnPositionFromParent sweeps from the fighter's ECB
          // center to the hand. A grounded shot can begin inside a slope;
          // it_80276100 corrects its root before the first Item Update.
          const bounds=fighterDataFor(cid)?.ecb?.[state]?.[age]
          if(bounds){
            const from=[frames.x[port][i],f(frames.y[port][i]+f((bounds[3]+(frames.air[port][i]?bounds[2]:0))*.5))]
            const contact=itemMapContact({t:spawn.kind,x:[shot.x],y:[shot.y],d:[dir]},0,lines,oldLines,from)
            if(contact){shot.x=contact.x;shot.y=contact.y}
          }
        }
        live.push(shot);entries.push(append(shot,0))
      }
    }
    for(let k=live.length-1;k>=0;k--)if(live[k].dead)live.splice(k,1)
    return entries
  }
}

// ftSk_SpecialNEnd_Anim fires at counters 2,5,...17; accessory4 draws
// the vertical jitter. Map chooses stick/bounce before ceiling callbacks.
export function unrecordedNeedleHistory(bundle,{birthsOnly=false,spawnFilter=null,materialOnly=false}={}) {
  const frames=fighterFrames(bundle),counts=frames.x.map(()=>0),counters=frames.x.map(()=>0),live=[]
  let serial=0
  // ABS is a macro in Runtime/platform.h. Its argument contains Randi,
  // and the all-negative velocity table makes it evaluate that argument
  // twice (the test draw, then the selected value).
  const bounceVy=rng=>{rng.int(8);return f(2+rng.int(8)*.1)}
  const bounce=(shot,rng,i,vy)=>{
    const sign=rng.int(2)?-1:1,angle=rng.int(8)
    shot.spin=sign*(Math.PI/6+angle*Math.PI/36)
    const direction=rng.int(2)?-1:1
    shot.vx=f(direction*rng.int(8)*.2);shot.maxFall=f(-2-rng.int(8)*.1)
    shot.gravity=[-.1,-.12,-.14,-.18,-.2,-.22,-.24,-.26][rng.int(8)]
    shot.vy=vy;shot.state=4;shot.fade=i
  }
  return (i,lines,oldLines=lines,afterCeilingRng=null)=>{
    const entries=[],mapRng=materialOnly?afterCeilingRng:frameCursor(bundle,i)
    for(const shot of live) {
      const t=shot.track,a=itemDataFor(t.t),j=t.x.length,age=i-t.f
      if(shot.dead||shot.fade==null&&age>=a.special[0]||shot.state===2&&i-shot.fade>=a.special[1]){shot.dead=true;continue}
      if(shot.state===4)shot.vy=Math.max(shot.maxFall,f(shot.vy+shot.gravity))
      const from=[t.x[j-1],t.y[j-1]]
      t.x.push(f(from[0]+shot.vx));t.y.push(f(from[1]+shot.vy));t.s.push(shot.state);t.d.push(shot.dir);t.vx.push(shot.vx);t.vy.push(shot.vy)
      const contact=[0,4].includes(shot.state)&&itemRayContact(...from,t.x[j],t.y[j],lines,oldLines)
      if(contact) {
        t.x[j]=contact.x;t.y[j]=contact.y
        if(!mapRng){entries.push({id:shot.id,hits:null,previous:[]});continue}
        if(shot.state===0&&mapRng.int(5)>=3){const vy=bounceVy(mapRng);bounce(shot,mapRng,i,vy)}
        else{shot.state=2;shot.vx=shot.vy=0;shot.fade=i}
        t.s[j]=shot.state;t.vx[j]=shot.vx;t.vy[j]=shot.vy
        // Brinstar only consumes attacks, not item restoration ECBs. Both
        // outcomes of the map callback permanently clear needle attacks;
        // consume their ordered RNG, then discard the inert model history.
        if(materialOnly){shot.dead=true;continue}
      }
      const hits=itemSpheres(t,j,age,bundle)
      entries.push({id:shot.id,track:t,j,hits,previous:shot.previous,
        onHit:()=>{shot.hit=true;if(materialOnly)shot.dead=true},onMaterialResolved:rng=>{
          if(!shot.hit)return;shot.hit=false
          if(rng.int(3)===0){const vy=bounceVy(rng);bounce(shot,rng,i,vy)}else shot.dead=true
        }})
      shot.previous=hits||[]
    }
    if(!materialOnly&&mapRng?.used){entries.push({id:'needle-map-rng',hits:[],previous:[],beforeCeilingDraws:mapRng.used});if(afterCeilingRng)for(let n=0;n<mapRng.used;n++)afterCeilingRng.float()}
    for(let port=0;port<frames.x.length;port++) {
      const cid=frames.cid[port][i],cfg=fighterDataFor(cid)?.needles
      if(!cfg)continue
      const base=cid===7?341:467,state=frames.state[port][i]-base,old=frames.state[port][i-1]-base,age=frames.age[port][i]
      if(frames.state[port][i]<11)counts[port]=0
      // Drop selects motion1, whose authored command stream has no attacks.
      // Its random tumble/ECB still matters to restoration on other stages.
      if(frames.state[port][i]>=75&&frames.state[port][i]<=91&&counts[port]){if(!materialOnly)entries.push({id:`needle-drop:${port}`,hits:null,previous:[]});counts[port]=0}
      if([0,4].includes(state)&&![0,4].includes(old)&&!counts[port])counts[port]=1
      if([1,5].includes(old)&&[1,5].includes(state)&&age===0)counts[port]=Math.min(6,counts[port]+1)
      if(![3,7].includes(old))counters[port]=0
      const counter=[3,7].includes(old)?counters[port]++:-1
      if(![3,7].includes(state)){if([3,7].includes(old)&&frames.air[port][i]!==frames.air[port][i-1])counts[port]=0;continue}
      if(![2,5,8,11,14,17].includes(counter)||!counts[port])continue
      const kind=cid===7?79:152
      if(spawnFilter&&!spawnFilter(kind,port,i)){counts[port]--;continue}
      const rng=frames.x.length===1?(afterCeilingRng??frameCursor(bundle,i)):null
      if(!rng){entries.push({id:`needle-rng:${port}`,hits:null,previous:[]});continue}
      // x34_scale is the runtime fighter scale (one in certified vanilla
      // histories), distinct from the authored model's scale of 1.4.
      const a=itemDataFor(kind),air=!!frames.air[port][i],scale=1,dir=frames.dir[port][i]
      const jitter=f(-1+rng.int(9)*.25),angle=f(f(dir*(air?f(3*Math.PI/4):f(Math.PI/2)))+f(Math.PI/2))
      const vx=f(-a.special[2]*f(Math.cos(angle))),vy=f(a.special[2]*f(Math.sin(angle)))
      const t={t:kind,o:port,f:i,x:[f(frames.x[port][i]+f(scale*f(dir*cfg[air?2:0])))],y:[f(frames.y[port][i]+f(scale*f(cfg[air?3:1]+jitter*(air?2:1))))],s:[0],d:[dir],vx:[vx],vy:[vy]}
      const bounds=fighterDataFor(cid)?.ecb?.[frames.state[port][i]]?.[age]
      if(bounds){
        const from=[frames.x[port][i],f(frames.y[port][i]+f((bounds[3]+(air?bounds[2]:0))*.5))]
        const contact=itemMapContact(t,0,lines,oldLines,from)
        if(contact){t.x[0]=contact.x;t.y[0]=contact.y}
      }
      const hits=itemSpheres(t,0,0,bundle),shot={id:`needle:${serial++}`,track:t,port,dir,vx,vy,state:0,previous:hits||[]}
      counts[port]--;if(!birthsOnly)live.push(shot)
      for(let n=0;n<a.spawnDraws;n++)rng.float()
      entries.push({id:shot.id,track:t,j:0,hits,previous:[],afterCeilingDraws:1+a.spawnDraws,
        onHit:()=>{shot.hit=true;if(materialOnly)shot.dead=true},onMaterialResolved:r=>{if(shot.hit){shot.hit=false;if(r.int(3)===0){const v=bounceVy(r);bounce(shot,r,i,v)}else shot.dead=true}}})
    }
    for(let k=live.length-1;k>=0;k--)if(live[k].dead)live.splice(k,1)
    return entries
  }
}

// The hidden Shadow Ball uses the same oscillator as recorded items. Its
// held creation and release run in fighter animation; the released root and
// child then advance in item physics before map and material callbacks.
export function unrecordedShadowHistory(bundle) {
  const frames=fighterFrames(bundle),live=[],held=frames.x.map(()=>null),charge=frames.x.map(()=>0),ticks=frames.x.map(()=>0),lag=frames.x.map(()=>0)
  let serial=0
  return (i,lines,oldLines=lines)=>{
    const entries=[],rng=frameCursor(bundle,i),anim=frameCursor(bundle,i,{priority:1,extra:0})
    const solo=frames.x.length===1
    for(let port=0;port<frames.x.length;port++) {
      const cid=frames.cid[port][i],cfg=fighterDataFor(cid)?.shadowBall
      if(!cfg)continue
      const base=cid===16?341:500,state=frames.state[port][i]-base,old=frames.state[port][i-1]-base,age=frames.age[port][i]
      if(state<0||state>9)held[port]=null
      if(frames.state[port][i]<11&&charge[port]!==cfg.max||frames.state[port][i]>=75&&frames.state[port][i]<=91){charge[port]=ticks[port]=0;held[port]=null}
      if([0,5].includes(state)&&![0,5].includes(old)){ticks[port]=0;lag[port]=charge[port]?0:cfg.lag}
      if([1,6].includes(old)&&--lag[port]<=0&&++ticks[port]>cfg.ticks){ticks[port]=0;charge[port]=Math.min(cfg.max,charge[port]+1)}
      if([2,7].includes(state))charge[port]=cfg.max
      if([3,8].includes(state))held[port]=null
      const move=fighterDataFor(cid).hitboxes[frames.state[port][i]],prior=fighterDataFor(cid).hitboxes[frames.state[port][i-1]]
      const same=move?.motion.replace('Air','')===prior?.motion.replace('Air','')
      const before=i&&same&&age>=frames.age[port][i-1]?frames.age[port][i-1]:-1
      for(const spawn of move?.articleSpawns||[]) {
        const table=itemDataFor(spawn.kind)
        if(table?.family!=='shadow'||spawn.frame<=before||spawn.frame>age)continue
        if(!solo||!anim||!rng){entries.push({id:`shadow-unknown:${port}`,hits:null,previous:[]});continue}
        if(spawn.held) {
          if(!held[port])held[port]={...shadowOscillator(table.special,anim),
            mapFrom:[f(frames.x[port][Math.max(0,i-1)]+frames.dir[port][i]*spawn.pos[2]),f(frames.y[port][Math.max(0,i-1)]+spawn.pos[1])]}
          continue
        }
        const oscillator=held[port]
        if(!oscillator){entries.push({id:`shadow-missing:${port}`,hits:null,previous:[]});continue}
        const dir=frames.dir[port][i],a=table.special,speed=f(a[2]+f(charge[port]*f((a[3]-a[2])/cfg.max)))
        oscillator.multiplier=f(.5*f(charge[port]/cfg.max)+.5)
        // it_8027429C detaches at the shoulder/hand without the +2 local
        // release offset, then remaps CollData from the owner's ECB center.
        // it_802C53F0 restores the visual release position afterwards.
        const root=Math.max(0,i-1),detach=spawn.detachPos
        oscillator.mapFrom=detach?articleSpawnCollision(frames,port,root,spawn.kind,dir,
          [f(frames.x[port][root]+dir*detach[2]),f(frames.y[port][root]+detach[1])],lines,oldLines):null
        if(!oscillator.mapFrom){entries.push({id:`shadow-detach:${port}`,hits:null,previous:[]});held[port]=null;continue}
        live.push({id:`shadow:${serial++}`,port,dir,speed,oscillator,state:charge[port]+1,born:i,previous:[],
          track:{t:spawn.kind,o:port,f:i,x:[],y:[],s:[],d:[],vx:[],vy:[],shadow:[]},
          x:f(frames.x[port][Math.max(0,i-1)]+dir*spawn.pos[2]),y:f(frames.y[port][Math.max(0,i-1)]+spawn.pos[1])})
        held[port]=null;charge[port]=0
      }
    }
    let mapDraws=0
    for(let k=0;k<live.length;k++) {
      const shot=live[k],t=shot.track,a=itemDataFor(t.t),age=i-shot.born,j=t.x.length
      if(shot.dead||age>=a.special[0]-1&&shot.explosion==null||shot.explosion!=null&&i-shot.explosion>=a.special[10])continue
      if(!rng){entries.push({id:shot.id,hits:null,previous:[]});continue}
      let vx=0,vy=0,from=null
      if(shot.explosion==null) {
        vx=f(shot.dir*shot.speed*(shot.oscillator.tick?1:shot.oscillator.multiplier))
        from=shot.oscillator.tick?[shot.x,shot.y]:shot.oscillator.mapFrom
        shot.x=f(shot.x+vx)
        shadowOscillatorStep(shot.oscillator,a.special,rng)
      }
      t.x.push(shot.x);t.y.push(shot.y);t.s.push(shot.state);t.d.push(shot.dir);t.vx.push(vx);t.vy.push(vy);t.shadow.push(shot.oscillator.offset.slice())
      const contact=from?resolveItemMap(t,j,lines,oldLines,from).at(-1):null
      if(contact) {
        shot.x=t.x[j]=contact.x;shot.y=t.y[j]=contact.y;shot.explosion=i;shot.state=t.s[j]=shot.state+9
        mapDraws+=a.mapDraws;shot.previous=[]
      }
      const hits=itemSpheres(t,j,shot.explosion==null?age:i-shot.explosion,bundle)
      entries.push({id:shot.id,track:t,j,hits,previous:shot.previous,onHit:()=>{shot.dead=true}})
      shot.previous=hits||[]
    }
    for(let k=live.length-1;k>=0;k--)if(live[k].dead||i-live[k].born>=itemDataFor(live[k].track.t).special[0]-1&&live[k].explosion==null||live[k].explosion!=null&&i-live[k].explosion>=itemDataFor(live[k].track.t).special[10])live.splice(k,1)
    if(rng?.used||mapDraws)entries.push({id:'shadow-rng',hits:[],previous:[],beforeCeilingDraws:(rng?.used||0)+mapDraws})
    return entries
  }
}

function unrecordedBomberHistory(bundle) {
  const frames=fighterFrames(bundle),live=[],smash=frames.x.map(()=>false)
  let serial=0
  return i=>{
    const entries=[]
    for(let k=live.length-1;k>=0;k--){
      const shot=live[k],age=i-shot.track.f
      if(age>=itemDataFor(98).animations[shot.state].end){live.splice(k,1);continue}
      const hits=itemSpheres(shot.track,0,age,bundle)
      entries.push({id:shot.id,track:shot.track,j:0,hits,previous:[]})
    }
    for(let port=0;port<frames.x.length;port++){
      if(frames.cid[port][i]!==9)continue
      const state=frames.state[port][i],old=frames.state[port][i-1],fighter=fighterDataFor(9)
      if([354,357].includes(state)&&![354,357].includes(old)){
        let held=0
        for(let n=i;n>=0&&Math.abs(frames.joyx?.[port]?.[n]??0)>=.3;n--)held++
        smash[port]=held<fighter.bomberSmashFrames
      }
      // Hurtbox detection resolves after item collision. Its new explosion
      // first participates in collision on the following frame.
      if(state!==359||old===359||frames.age[port][i]!==0)continue
      const pos=fighter.hitboxes[state].bomberPosition,dir=frames.dir[port][i],s=Number(smash[port])
      const track={t:98,o:port,f:i,x:[f(frames.x[port][i]+dir*pos[2])],y:[f(frames.y[port][i]+pos[1])],s:[s],d:[dir],vx:[0],vy:[0]}
      live.push({id:`bomber:${serial++}`,track,state:s})
    }
    return entries
  }
}

// Fixed item ECB points, from ItemAttr.x40 and mpColl_SetECBSource_Fixed.
// A map hit precedes material damage and removes charge/missile attacks.
function fixedItemEcbPoints(table,dir,angle=0) {
  const ecb=table.ecb
  let [top,bottom,right,left]=ecb.map((v,k)=>v*table.scale*(k===1||k===3?-1:1))
  if(dir!==1)[right,left]=[-left,-right]
  if(angle){
    // mpColl_800428F8 rotates the fixed source, then takes its axis bounds.
    if(angle>2*Math.PI)angle=f(angle-f(2*Math.PI));else if(angle< -2*Math.PI)angle=f(angle+f(2*Math.PI))
    const c=f(Math.cos(angle)),s=f(Math.sin(angle)),mid=f((right+left)*.5)
    const xs=[0,f(-top*s),f(-bottom*s),f(f(right*c)-f(mid*s)),f(f(left*c)-f(mid*s))]
    const ys=[0,f(top*c),f(bottom*c),f(f(right*s)+f(mid*c)),f(f(left*s)+f(mid*c))]
    left=Math.min(...xs);right=Math.max(...xs);bottom=Math.min(...ys);top=Math.max(...ys)
  }
  // mpColl_800428F8 clamps fixed ECB dimensions to three world units.
  if(top-bottom<3){top=1.5;bottom=-1.5}
  if(right-left<3){right=1.5;left=-1.5}
  const side=(top+bottom)/2
  return [[0,bottom,1],[0,top,2],[left,side,4],[right,side,8]]
}
export function itemMapContact(track,j,lines,oldLines=lines,from=null,previousScale=1,currentScale=1) {
  const table=itemDataFor(track.t),dir=track.d[j]
  if(!table?.ecb)return null
  const x0=from?.[0]??track.x[j-1],y0=from?.[1]??track.y[j-1],x1=track.x[j],y1=track.y[j]
  if(![x0,y0,x1,y1].every(Number.isFinite))return null
  const points=fixedItemEcbPoints(table,dir,track.mapAngle?.[j]),prior=fixedItemEcbPoints(table,dir,track.mapAngle?.[j-1])
  let contact=null
  for(const [k,[ox,oy,type]] of points.entries())for(const line of lines||[]){
    if((line[1]&15)!==type)continue
    const [id,,ax,ay,bx,by]=line,old=oldLines?.find(l=>l[0]===id)
    const px=x0+prior[k][0]*previousScale+(old?ax-old[2]:0),py=y0+prior[k][1]*previousScale+(old?ay-old[3]:0)
    const lx=bx-ax,ly=by-ay,dx=x1+ox*currentScale-px,dy=y1+oy*currentScale-py
    const before=lx*(py-ay)-ly*(px-ax),after=lx*(y1+oy*currentScale-ay)-ly*(x1+ox*currentScale-ax)
    if(before<0||after>0||before===after)continue
    const t=before/(before-after),x=px+t*dx,y=py+t*dy
    if(x<Math.min(ax,bx)-.0001||x>Math.max(ax,bx)+.0001||y<Math.min(ay,by)-.0001||y>Math.max(ay,by)+.0001)continue
    // Map correction preserves the tangent component of the final position.
    // Moving floors translate with their joint before this projection.
    const cx=type<4?x1:ax+(ly?(y1+oy*currentScale-ay)*lx/ly:0)-ox*currentScale
    const cy=type<4?ay+(lx?(x1+ox*currentScale-ax)*ly/lx:0)-oy*currentScale+(type===1?.0001:-.0001):y1
    if(!contact||t<contact.t)contact={t,x:f(cx),y:f(cy),type,line:id,normal:[-ly/Math.hypot(lx,ly),lx/Math.hypot(lx,ly)],shift:old?[ax-old[2],ay-old[3]]:[0,0]}
  }
  return contact
}

// mpColl_80046904 resolves walls before ceiling/floor. A fixed diamond
// can meet a corner along its current edges without a side-point crossing.
function resolveItemMap(track,j,lines,oldLines,from) {
  const contacts=[],points=fixedItemEcbPoints(itemDataFor(track.t),track.d[j],track.mapAngle?.[j])
  for(const type of [8,4,2,1]){
    const subset=lines.filter(l=>(l[1]&15)===type)
    let contact=itemMapContact(track,j,subset,oldLines,from)
    if(!contact&&type>=4){
      const side=points[type===8?3:2]
      for(const tip of points.slice(0,2)){
        const ray=itemRayContact(track.x[j]+tip[0],track.y[j]+tip[1],track.x[j]+side[0],track.y[j]+side[1],subset,subset)
        if(ray){
          let dx=side[0]
          const wall=subset.find(l=>l[0]===ray.line)
          if(Math.abs(wall[2]-wall[4])<.0001){
            // The wall can end inside a diamond edge. Native wall-air
            // correction projects that endpoint onto the sloping edge.
            const y=Math.max(Math.min(wall[3],wall[5]),Math.min(Math.max(wall[3],wall[5]),track.y[j]+side[1]))-track.y[j]
            dx=y>=side[1]?side[0]*(points[1][1]-y)/(points[1][1]-side[1]):side[0]*(y-points[0][1])/(side[1]-points[0][1])
          }
          contact={...ray,type,x:f(ray.x-dx),y:track.y[j],shift:[0,0]};break
        }
      }
      // A fast side point can pass the endpoint entirely between ticks;
      // the native wall pass sweeps both diamond edges as well.
      contact??=itemWallCornerCrossing(track,j,subset,from)
    }
    if(!contact&&type===2){
      for(const hit of contacts.filter(c=>c.type>=4)){
        const wall=lines.find(l=>l[0]===hit.line),cy=Math.min(wall[3],wall[5])
        const ceiling=subset.find(l=>[2,4].some(k=>Math.abs(l[k]-wall[2])<.0001&&Math.abs(l[k+1]-cy)<.0001))
        if(ceiling&&cy>=track.y[j]+points[0][1]&&track.y[j]+points[1][1]>cy){contact={line:ceiling[0],type:2,x:track.x[j],y:f(cy-points[1][1]),normal:[0,-1],shift:[0,0]};break}
      }
    }
    if(contact){contacts.push(contact);track.x[j]=contact.x;track.y[j]=contact.y}
  }
  return contacts
}

// mpColl's wall pass also sweeps the two diamond edges against each wall
// endpoint. A tiny article can strike the lower wall corner even though its
// side point is below the wall and its top point crosses no ceiling segment.
function itemWallCornerCrossing(track,j,lines,from) {
  const a=itemDataFor(track.t),e=a.ecb.map(v=>v*a.scale)
  let top=e[0],bottom=-e[1],right=e[2],left=-e[3]
  if(top-bottom<3){top=1.5;bottom=-1.5}
  if(right-left<3){right=1.5;left=-1.5}
  const side=(top+bottom)/2,dx=track.x[j]-from[0],dy=track.y[j]-from[1]
  const diamond=[[0,top],[left,side],[0,bottom],[right,side]]
  for(const [line,flags,ax,ay,bx,by] of lines){
    const kind=flags&15
    if(kind!==8&&kind!==4||kind===8&&dx<=0||kind===4&&dx>=0)continue
    for(const [x,y] of [[ax,ay],[bx,by]]){
      let enter=0,leave=1,outside=false
      for(let k=0;k<4;k++){
        const [ux,uy]=diamond[k],[vx,vy]=diamond[(k+1)%4],ex=vx-ux,ey=vy-uy
        const before=ex*(y-from[1]-uy)-ey*(x-from[0]-ux),delta=-ex*dy+ey*dx
        if(before<0)outside=true
        if(!delta){if(before<0){leave=-1;break}}else if(delta>0)enter=Math.max(enter,-before/delta);else leave=Math.min(leave,-before/delta)
      }
      if(outside&&enter<=leave&&enter>=0&&enter<=1){
        const offset=y-track.y[j],width=kind===8?right:left
        const edge=offset>=side?width*(top-offset)/(top-side):width*(offset-bottom)/(side-bottom)
        return {line,type:kind,x:f(x-edge),y:track.y[j],normal:[kind===8?-1:1,0],shift:[0,0]}
      }
    }
  }
  return false
}
export function itemEntryHits(entry,lines,oldLines) {
  if(entry.chargeRelease){
    const {frames,port,root,target}=entry.chargeRelease,t=entry.track
    const from=articleSpawnCollision(frames,port,root,t.t,t.d[0],target,lines,oldLines)
    return !from?null:itemMapContact(t,0,lines,oldLines,from)?[]:entry.hits
  }
  if(entry.joltAir){
    const {track:t,j,bundle}=entry,p=t.joltParent,pi=t.f+j-(p?.f||0)
    let pose=t.joltPose[j-1]
    const reset=!j||t.x[j]!==t.x[j-1]||t.y[j]!==t.y[j-1]
    if(reset){
      if(!p||pi<0)return null
      let from=pi?[p.x[pi-1],p.y[pi-1]]:null
      if(!from){
        const frames=fighterFrames(bundle),i=p.f,port=itemOwnerPort(p,0,bundle),state=frames.state[port]?.[i]
        const spawn=fighterDataFor(frames.cid[port]?.[i])?.hitboxes?.[state]?.articleSpawns?.find(s=>s.kind===p.t&&s.frame===frames.age[port][i])
        if(spawn)from=joltSpawnPosition(frames,port,i,spawn,lines,oldLines)?.position
      }
      if(!from)return null
      const [x,y]=from,dx=t.x[j]-x,dy=t.y[j]-y,len=Math.hypot(dx,dy)
      if(!len)return null
      const contact=itemRayContact(x,y,t.x[j]+dx*.002/len,t.y[j]+dy*.002/len,lines,oldLines)
      if(!contact)return null
      pose={age:1,normal:contact.normal}
    }else if(pose)pose={...pose,age:pose.age+1}
    if(!pose)return null
    t.joltPose[j]=pose
    if(pose.age>25||entry.joltTerminal&&p?.lifetime?.[Math.min(pi-1,p.x.length-1)]<=1)return []
    const hits=itemSpheres(t,j,pose.age,bundle)
    entry.reset=reset;entry.previous=reset?[]:t.joltHits||[];t.joltHits=hits||[]
    return hits
  }
  if(entry.pkfireImpact)return itemMapContact(entry.track,entry.j,lines.filter(l=>(l[1]&15)!==2),oldLines,entry.mapFrom)||itemWallCornerCrossing(entry.track,entry.j,lines,entry.mapFrom)?[]:entry.hits
  if(entry.needleImpact)return itemMapCrossing(...entry.mapFrom,entry.track.x[entry.j],entry.track.y[entry.j],lines,oldLines)?[]:entry.hits
  if(entry.shadowTerminal){
    const {track:t,j}=entry,contact=resolveItemMap(t,j,lines,oldLines,entry.mapFrom).at(-1)
    if(contact){t.x[j]=contact.x;t.y[j]=contact.y;t.s[j]=t.s[j-1]+9;return itemSpheres(t,j,0,entry.bundle)}
    return entry.hits
  }
  if(entry.chefImpact){
    // A recorded map fade already contains the epsilon-corrected root,
    // just outside the ceiling/floor. Test the pre-map physics endpoint,
    // otherwise that correction can be mistaken for a DmgDealt fade.
    const {track:t,j,mapFrom:from}=entry,flight={...t,x:t.x.slice(),y:t.y.slice()}
    flight.x[j]=f(from[0]+t.vx[j]);flight.y[j]=f(from[1]+t.vy[j])
    const contact=itemMapContact(flight,j,lines,oldLines,from)
    return contact&&contact.type<4?[]:entry.hits
  }
  if(entry.fireballTerminal){
    const {track:t,j,bundle,age}=entry,a=itemDataFor(t.t),contact=itemMapContact(t,j,lines,oldLines,entry.mapFrom)
    if(contact){
      const [nx,ny]=contact.normal,dot=f(f(t.vx[j]*nx)+f(t.vy[j]*ny))
      const vx=f(f(t.vx[j]-f(2*dot*nx))*a.bounce),vy=f(f(t.vy[j]-f(2*dot*ny))*a.bounce)
      if(dot<0&&Math.hypot(vx,vy)<([105,132].includes(t.t)?a.special[3]:a.special[4]))return []
      t.x[j]=contact.x;t.y[j]=contact.y;t.vx[j]=vx;t.vy[j]=vy
      return itemSpheres(t,j,age,bundle)
    }
    return entry.hits
  }
  // Link bomb DmgDealt changes its recorded state after collision. A map
  // explosion happens before collision and can use the new blast immediately.
  if(entry.bombImpact&&!itemMapContact(entry.track,entry.j,lines,oldLines,entry.bombImpact.from)){
    entry.previous=entry.bombImpact.previous;entry.reset=false
    return entry.bombImpact.hits
  }
  if(!entry.mapFrom)return entry.hits
  const {track:t,j,mapFrom:from}=entry
  const contact=entry.mapRoot?itemMapCrossing(...from,t.x[j],t.y[j],lines,oldLines):itemMapContact(t,j,lines,oldLines,from)
  return contact?[]:entry.hits
}

// itMario/DrMario/Luigi fireball: accessory spawn, falling physics, fixed
// ECB map correction, velocity reflection and ItemAttr.x58 restitution.
// The muzzle and deferred bounce generators execute at priority 9, after
// fighter ceiling callbacks and before priority-13 material hit effects.
export function unrecordedFireballHistory(bundle,{birthsOnly=false,spawnFilter=null}={}) {
  const frames=fighterFrames(bundle),live=[]
  let serial=0
  return (i,lines,oldLines=lines)=>{
    const entries=[]
    const physics=(shot,j,from)=>{
      const t=shot.track,a=itemDataFor(t.t),luigi=[105,132].includes(t.t)
      // it_80272860 tests the previous speed; it permits one gravity step
      // past the limit and retains that overshoot on subsequent ticks.
      if(shot.vy> -a.maxFallSpeed)shot.vy=f(shot.vy-a.gravity)
      if(a.mapSpin){
        let spin=f(f(.01*a.mapSpin[0])*f(f(Math.PI/180)*a.mapSpin[1]))
        if(Math.sign(shot.vx||1)!==shot.dir)spin=-spin
        if(!a.mapSpin[2])spin=f(spin*-shot.dir)
        shot.angle=f((shot.angle||0)+spin);t.mapAngle??=[];t.mapAngle[j]=shot.angle
      }
      t.x[j]=f(f(from[0]+shot.vx)+shot.shift[0]);t.y[j]=f(f(from[1]+shot.vy)+shot.shift[1])
      shot.shift=[0,0] // it_8027346C clears x64 after the position update.
      const contacts=resolveItemMap(t,j,lines,oldLines,from)
      let draws=0
      const reflections=contacts.filter(c=>f(f(shot.vx*c.normal[0])+f(shot.vy*c.normal[1]))<0)
      if(reflections.length){
        let rx=0,ry=0
        shot.shift=[0,0]
        for(const contact of reflections){
          const [nx,ny]=contact.normal,dot=f(f(shot.vx*nx)+f(shot.vy*ny))
          rx=f(rx+f(shot.vx-f(2*dot*nx)));ry=f(ry+f(shot.vy-f(2*dot*ny)))
          // mpGetSpeed remaps the final item root along the old line.
          // Item_Phys applies x64_vec_unk2 on the next tick, then clears it.
          const line=lines.find(l=>l[0]===contact.line),old=oldLines.find(l=>l[0]===contact.line)
          if(old){
            const dx=f(old[4]-old[2]),dy=f(old[5]-old[3]),length=dx*dx+dy*dy
            const u=length>.0001?Math.max(0,Math.min(1,(dx*f(t.x[j]-old[2])+dy*f(t.y[j]-old[3]))/length)):0
            for(let k=0;k<2;k++)shot.shift[k]=f(shot.shift[k]+f(f(t[k?'y':'x'][j]+(1-u)*f(line[2+k]-old[2+k])+u*f(line[4+k]-old[4+k]))-t[k?'y':'x'][j]))
          }
        }
        if(Math.hypot(rx,ry)<.01){rx=shot.vx;ry=-shot.vy}
        const speed=f(f(Math.sqrt(f(f(shot.vx*shot.vx)+f(shot.vy*shot.vy))))*a.bounce),length=f(Math.sqrt(f(f(rx*rx)+f(ry*ry))))
        shot.vx=f(f(rx/length)*speed);shot.vy=f(f(ry/length)*speed)
        if(Math.hypot(shot.vx,shot.vy)<(luigi?a.special[3]:a.special[4]))return null
        draws=a.bounceDraws
      }
      t.vx[j]=shot.vx;t.vy[j]=shot.vy
      return draws
    }
    for(let k=live.length-1;k>=0;k--){
      const shot=live[k],t=shot.track,a=itemDataFor(t.t),luigi=[105,132].includes(t.t),age=i-t.f
      if(shot.dead||age>=(luigi?a.special[1]:a.special[2])){t.expiresAt=Math.min(t.expiresAt??Infinity,i);live.splice(k,1);continue}
      const j=t.x.length,from=[t.x[j-1],t.y[j-1]]
      t.s.push(0);t.d.push(shot.dir);t.vx.push(shot.vx);t.vy.push(shot.vy)
      const draws=physics(shot,j,from)
      if(draws===null){t.expiresAt=i;live.splice(k,1);continue}
      const hits=itemSpheres(t,j,age,bundle)
      entries.unshift({id:shot.id,track:t,j,hits,previous:shot.previous,afterCeilingDraws:draws,onHit:()=>{shot.dead=true;t.expiresAt=i+1}})
      shot.previous=hits||[]
    }
    for(let port=0;port<frames.x.length;port++){
      const cid=frames.cid[port][i],state=frames.state[port][i],age=frames.age[port][i],dir=frames.dir[port][i]
      const move=fighterDataFor(cid)?.hitboxes?.[state],old=frames.state[port][i-1]
      const continuation=state===old||move?.motion.replace('Air','')===fighterDataFor(cid)?.hitboxes?.[old]?.motion.replace('Air','')
      const before=i&&continuation&&age>=frames.age[port][i-1]?frames.age[port][i-1]:-1
      for(const spawn of move?.articleSpawns||[]){
        const a=itemDataFor(spawn.kind)
        if(a?.family!=='fireball'||spawn.frame<=before||spawn.frame>age||spawnFilter&&!spawnFilter(spawn.kind,port,i))continue
        const luigi=[105,132].includes(spawn.kind),vx=f(dir*f(a.special[0]*Math.cos(luigi?0:a.special[1]))),vy=f(a.special[0]*Math.sin(luigi?0:a.special[1]))
        const t={t:spawn.kind,o:port,f:i,x:[f(frames.x[port][i]+dir*spawn.pos[2])],y:[f(frames.y[port][i]+spawn.pos[1])],s:[0],d:[dir],vx:[vx],vy:[vy]}
        const origin=articleSpawnCollision(frames,port,i,spawn.kind,dir,[t.x[0],t.y[0]],lines,oldLines)
        if(!origin){entries.push({id:`fireball-unknown:${port}`,hits:null,previous:[]});continue}
        ;[t.x[0],t.y[0]]=origin
        const shot={id:`fireball:${serial++}`,track:t,dir,vx,vy,shift:[0,0]}
        // All three constructors call it_802750F8: physics and map run
        // immediately, even though accessory4 is after their normal passes.
        const draws=physics(shot,0,[t.x[0],t.y[0]])
        if(draws===null)continue
        const hits=itemSpheres(t,0,0,bundle);shot.previous=hits||[]
        if(!birthsOnly)live.push(shot)
        entries.push({id:shot.id,track:t,j:0,hits,previous:[],afterCeilingDraws:a.spawnDraws+draws,onHit:()=>{shot.dead=true}})
      }
    }
    return entries
  }
}

// DmgDealt can delete a laser/fireball before its first Item Update. Recover
// just that birth when no recorded projectile supplies it; all later flight
// samples remain owned by the ordinary recorded-item history.
export function missingProjectileBirths(bundle,{includeNeedles=true}={}){
  const frames=fighterFrames(bundle),births=new Set((bundle.items||[]).map(t=>`${t.t}:${t.f}:${itemOwnerPort(t,0,bundle)}`))
  const missing=(kind,port,i)=>!births.has(`${kind}:${i}:${port}`)&&!births.has(`${kind}:${i}:null`)
  const fire=unrecordedFireballHistory(bundle,{birthsOnly:true,spawnFilter:missing})
  const needles=unrecordedNeedleHistory(bundle,{birthsOnly:true,spawnFilter:missing})
  return (i,lines,oldLines=lines,afterGroundRng=null)=>{
    const entries=[...fire(i,lines,oldLines),...(includeNeedles?needles(i,lines,oldLines,afterGroundRng):[])]
    for(let port=0;port<frames.x.length;port++){
      const cid=frames.cid[port][i],state=frames.state[port][i],age=frames.age[port][i],dir=frames.dir[port][i]
      const before=i&&state===frames.state[port][i-1]&&age>=frames.age[port][i-1]?frames.age[port][i-1]:-1
      for(const spawn of fighterDataFor(cid)?.hitboxes?.[state]?.articleSpawns||[]){
        if(itemDataFor(spawn.kind)?.family!=='laser'||spawn.frame<=before||spawn.frame>age||!missing(spawn.kind,port,i))continue
        const root=Math.max(0,i-1),sx=f(frames.x[port][root]+dir*spawn.pos[2]),sy=f(frames.y[port][root]+spawn.pos[1])
        const from=articleSpawnCollision(frames,port,root,spawn.kind,dir,[sx,sy],lines,oldLines)
        if(!from){entries.push({id:`missing-laser:${port}:${i}`,hits:null,previous:[]});continue}
        const vx=f(dir*spawn.velocity[0]),vy=dir===1?spawn.velocity[1]:f(Math.sin(Math.fround(Math.PI))*Math.abs(vx))
        const x=f(from[0]+vx),y=f(from[1]+vy)
        if(itemMapCrossing(...from,x,y,lines,oldLines))continue
        const track={t:spawn.kind,o:port,f:i,s:[0],x:[x],y:[y],d:[dir],vx:[vx],vy:[vy]}
        entries.push({id:`missing-laser:${port}:${i}`,track,j:0,hits:itemSpheres(track,0,0,bundle),previous:[],reset:true})
      }
    }
    return entries
  }
}

// Chef excludes the last two trajectory indices, seeded 1/3 on fighter
// initialization. Selection consumes exactly one Randi in accessory4.
export function unrecordedChefHistory(bundle) {
  const frames=fighterFrames(bundle),live=[],recent=frames.x.map(()=>[1,3]),counts=frames.x.map(()=>0)
  let serial=0
  return (i,lines,oldLines=lines,afterCeilingRng=null)=>{
    const entries=[]
    for(let k=live.length-1;k>=0;k--){
      const shot=live[k],t=shot.track,a=itemDataFor(t.t),j=t.x.length,age=i-t.f
      if(shot.fade==null&&age>=a.special[1]){shot.fade=i;t.expiresAt=i+a.special[2]}
      if(shot.fade!=null){
        if(i-shot.fade>=a.special[2]){live.splice(k,1);continue}
        for(const key of ['x','y','d'])t[key].push(t[key][j-1])
        t.s.push(1);t.vx.push(0);t.vy.push(0)
        entries.unshift({id:shot.id,track:t,j,hits:[],previous:[]});continue
      }
      shot.vy=Math.max(-a.trajectories[shot.type][3],f(shot.vy-a.trajectories[shot.type][2]))
      const from=[t.x[j-1],t.y[j-1]]
      t.x.push(f(from[0]+shot.vx));t.y.push(f(from[1]+shot.vy));t.d.push(shot.dir);t.s.push(0);t.vx.push(shot.vx);t.vy.push(shot.vy)
      const contact=itemMapContact(t,j,lines,oldLines,from)
      if(contact){
        t.x[j]=contact.x;t.y[j]=contact.y
        if(contact.type<4){
          shot.fade=i;t.expiresAt=i+a.special[2];t.s[j]=1;t.vx[j]=t.vy[j]=0
          entries.unshift({id:shot.id,track:t,j,hits:[],previous:[]});continue
        }
        shot.vx=f(-shot.vx*a.special[0]);t.vx[j]=shot.vx
      }
      const hits=itemSpheres(t,j,age,bundle)
      entries.unshift({id:shot.id,track:t,j,hits,previous:shot.previous,onHit:()=>{shot.fade=i+Math.max(0,Math.trunc(f(4*a.hitlag[0]+a.hitlag[1]))-1);t.expiresAt=shot.fade+a.special[2]}})
      shot.previous=hits||[]
    }
    for(let port=0;port<frames.x.length;port++){
      const cid=frames.cid[port][i],state=frames.state[port][i],age=frames.age[port][i],old=frames.state[port][i-1]
      if(state<11){recent[port]=[1,3];counts[port]=0}
      const move=fighterDataFor(cid)?.hitboxes?.[state],previous=fighterDataFor(cid)?.hitboxes?.[old]
      const continuation=move?.motion.replace('Air','')===previous?.motion.replace('Air','')
      if(!continuation)counts[port]=0
      const before=i&&continuation&&age>=frames.age[port][i-1]?frames.age[port][i-1]:-1
      for(const spawn of move?.articleSpawns||[]){
        const a=itemDataFor(spawn.kind)
        if(a?.family!=='chef'||spawn.frame<=before||spawn.frame>age||counts[port]>=fighterDataFor(cid).chefMax)continue
        // Other fighters can create effects between the last pre and this
        // accessory callback. Until that prefix is accounted, fail closed.
        const rng=frames.x.length===1?(afterCeilingRng??frameCursor(bundle,i)):null
        if(!rng){entries.push({id:`chef:${serial++}`,hits:null,previous:[]});continue}
        // procCollPos flushes GFX1021 before accessory4. efAsync model3
        // immediately animates channel40, creating generators8/266; the
        // latter consumes Randf before the trajectory Randi.
        for(let n=0;n<(spawn.beforeDraws||0);n++)rng.float()
        const choices=[0,1,2,3,4].filter(n=>!recent[port].includes(n)),type=choices[rng.int(choices.length)]
        recent[port]=[type,recent[port][0]];counts[port]++
        const dir=frames.dir[port][i],vx=f(dir*a.trajectories[type][0]),vy=a.trajectories[type][1]
        const t={t:spawn.kind,o:port,f:i,x:[f(frames.x[port][i]+dir*spawn.pos[2])],y:[f(frames.y[port][i]+spawn.pos[1])],s:[0],d:[dir],vx:[vx],vy:[vy]}
        const hits=itemSpheres(t,0,0,bundle),shot={id:`chef:${serial++}`,track:t,dir,type,vx,vy,previous:hits||[]}
        live.push(shot);entries.push({id:shot.id,track:t,j:0,hits,previous:[],afterCeilingDraws:1+(spawn.beforeDraws||0),onHit:()=>{shot.fade=i+Math.max(0,Math.trunc(f(4*a.hitlag[0]+a.hitlag[1]))-1);t.expiresAt=shot.fade+a.special[2]}})
      }
    }
    return entries
  }
}

// Samus launch callbacks, charge counter, and the native missile/bomb timers.
// Ordinary recorded items use itemAttackHistory; this only supplies articles
// omitted by Inishie1's permanently full Slippi item list.
function samusChargeHistory(bundle) {
  const frames=fighterFrames(bundle),levels=frames.x.map(()=>[])
  for(let port=0;port<frames.x.length;port++){
    let charge=0,ticks=0
    for(let i=0;i<bundle.meta.n;i++){
      const cid=frames.cid[port][i],a=fighterDataFor(cid)?.chargeShot
      if(![4,13].includes(cid)||!a)continue
      const state=frames.state[port][i],old=frames.state[port][i-1],age=frames.age[port][i],hold=cid===4?408:344
      if(state<11){charge=0;ticks=0}
      if(old===hold){if(++ticks>a.ticks){ticks=0;charge=Math.min(a.max,charge+1)}}else if(state===hold)ticks=0
      const before=i&&old===state&&age>=frames.age[port][i-1]?frames.age[port][i-1]:-1
      if(fighterDataFor(cid)?.hitboxes[state]?.articleSpawns?.some(s=>[94,151].includes(s.kind)&&s.frame>before&&s.frame<=age)){
        levels[port][i]=charge;charge=0
      }
    }
  }
  return levels
}

function unrecordedSamusHistory(bundle) {
  const frames=fighterFrames(bundle),live=[],charges=samusChargeHistory(bundle),missiles=frames.x.map(()=>0)
  let serial=0
  return (i,lines,oldLines)=>{
    const entries=[]
    const append=(shot,x,y,state,age,from)=>{
      const t=shot.track,j=t.x.length
      const wasFloor=shot.floor
      t.x.push(x);t.y.push(y);t.s.push(state);t.d.push(shot.dir);t.vx.push(shot.vx);t.vy.push(shot.vy)
      const table=itemDataFor(t.t),contact=from?itemMapContact(t,j,lines,oldLines,from):null
      if(contact&&t.t!==93){shot.dead=true;return}
      if(contact&&t.t===93){
        if(contact.type!==1){entries.push({id:shot.id,track:t,j,hits:null,previous:[]});shot.dead=true;return}
        t.x[j]=contact.x;t.y[j]=contact.y;t.s[j]=0;shot.vx=shot.vy=0;shot.floor=contact.line
      }
      const hits=itemSpheres(t,j,age,bundle)
      entries.push({id:shot.id,track:t,j,hits,previous:shot.previous,reset:state!==shot.lastState,
        groundLoad:shot.floor!=null?{line:shot.floor,weight:table.weight,landing:wasFloor==null}:null,
        onHit:()=>{if([94,95,151].includes(t.t))shot.dead=true;else if(t.t===93&&state!==3)shot.explode=true}})
      shot.previous=hits||[];shot.lastState=state
    }
    for(let k=live.length-1;k>=0;k--){
      const shot=live[k],t=shot.track,a=itemDataFor(t.t).special,age=i-t.f,j=t.x.length-1
      if(shot.dead){live.splice(k,1);continue}
      let state=t.s[j],animAge=age
      if([94,151].includes(t.t)){if(age>=a[0]-1){live.splice(k,1);continue}}
      else if(t.t===95){
        if(age>(state?a[9]:a[1])||missiles[shot.port]-shot.number>=2){live.splice(k,1);continue}
        if(state===1){if(age>a[10])shot.vx=shot.dir*Math.min(a[13],f(Math.abs(shot.vx)+a[12]))}
        else if(age>a[2]&&Math.hypot(shot.vx,shot.vy)>a[5]){shot.vx=f(shot.vx*a[4]);shot.vy=f(shot.vy*a[4])}
        else if(frames.x.length>1){entries.push({id:shot.id,track:t,j,hits:null,previous:[]});shot.dead=true;continue}
      }else{
        if((age>a[0]||shot.explode)&&state!==3){state=3;shot.explosion=i;shot.vx=shot.vy=0;shot.previous=[];shot.floor=null}
        if(state===3){animAge=i-shot.explosion;if(animAge>itemDataFor(93).animations[1].end){live.splice(k,1);continue}}
        else if(shot.floor!=null&&!lines.some(l=>l[0]===shot.floor)){shot.floor=null;state=1}
        if(state===1)shot.vy=Math.max(-itemDataFor(93).maxFallSpeed,f(shot.vy-itemDataFor(93).gravity))
      }
      const floor=shot.floor==null?null:lines.find(l=>l[0]===shot.floor),oldFloor=floor?oldLines.find(l=>l[0]===shot.floor):null
      const x=f(t.x[j]+shot.vx+(floor&&oldFloor?floor[2]-oldFloor[2]:0)),y=f(t.y[j]+shot.vy+(floor&&oldFloor?floor[3]-oldFloor[3]:0))
      append(shot,x,y,state,animAge,state===3||floor?null:[t.x[j],t.y[j]])
    }
    for(let port=0;port<frames.x.length;port++){
      const cid=frames.cid[port][i]
      if(![4,13].includes(cid))continue
      const state=frames.state[port][i],age=frames.age[port][i],dir=frames.dir[port][i]
      const old=frames.state[port][i-1],before=i&&(old===state||[355,356].includes(old)&&[355,356].includes(state))&&age>=frames.age[port][i-1]?frames.age[port][i-1]:-1
      for(const spawn of fighterDataFor(cid).hitboxes[state]?.articleSpawns||[]){
        if(![93,94,95,151].includes(spawn.kind))continue
        if(spawn.frame<=before||spawn.frame>age)continue
        const table=itemDataFor(spawn.kind),a=table.special,root=spawn.phase===1?Math.max(0,i-1):i
        const sx=f(frames.x[port][root]+dir*spawn.pos[2]),sy=f(frames.y[port][root]+spawn.pos[1])
        let itemState=spawn.state,vx=0,vy=0
        if([94,151].includes(spawn.kind)){const charge=charges[port][i];itemState=charge+1;vx=f(dir*f(a[2]+f(charge*f((a[3]-a[2])/fighterDataFor(cid).chargeShot.max))))}
        if(spawn.kind===95)vx=f(dir*(itemState?a[11]:a[3]))
        if(spawn.kind===93)vy=table.spawnVy
        const shot={id:`samus:${serial++}`,track:{t:spawn.kind,o:port,f:i,x:[],y:[],s:[],d:[],vx:[],vy:[]},dir,vx,vy,port,previous:[]}
        if(spawn.kind===95)shot.number=++missiles[port]
        live.push(shot)
        // Releasing a held Charge Shot remaps CollData from the owner's
        // ECB center, then it_802B56E4 restores the uncorrected hand root.
        // The first physics sweep starts at that corrected CollData point.
        let from=spawn.phase===1?[sx,sy]:null
        if([94,151].includes(spawn.kind)){
          from=articleSpawnCollision(frames,port,root,spawn.kind,dir,[sx,sy],lines,oldLines)
          if(!from){entries.push({id:shot.id,hits:null,previous:[]});shot.dead=true;continue}
        }
        append(shot,spawn.phase===1?f(sx+vx):sx,spawn.phase===1?f(sy+vy):sy,itemState,0,from)
      }
    }
    return entries
  }
}

function unrecordedLinkHistory(bundle) {
  const frames=fighterFrames(bundle),live=[],charges=frames.x.map(()=>0),smash=frames.x.map(()=>false)
  const config=(cid,state)=>{
    const table=fighterDataFor(cid)
    return cid===4?table?.copyArrows?.[state>=514&&state<=519?'Cl':'Lk']:table?.linkArticles
  }
  const normalized=(cid,state)=>cid!==4?state:state>=514&&state<=519?state-170:state>=401&&state<=406?state-57:state
  let serial=0
  const wrap=a=>a>Math.PI?a-2*Math.PI:a< -Math.PI?a+2*Math.PI:a
  return (i,lines,oldLines)=>{
    const entries=[]
    for(let port=0;port<frames.x.length;port++){
      const cid=frames.cid[port][i],state=normalized(cid,frames.state[port][i]),old=normalized(cid,frames.state[port][i-1]),age=frames.age[port][i],a=config(cid,frames.state[port][i])
      if(!a)continue
      if([344,347].includes(state)){
        if(![344,347].includes(old))charges[port]=0
        if(age>=a.chargeStart)charges[port]=Math.min(a.chargeMax,charges[port]+1)
      }else if([345,348].includes(state))charges[port]=a.chargeMax
      else if([346,349].includes(state)&&![346,349].includes(old))charges[port]=Math.min(a.chargeMax,charges[port]+1)
      if([350,353].includes(state)&&![350,353].includes(old)){
        let held=0
        for(let n=i;n>=0&&Math.abs(frames.joyx?.[port]?.[n]??0)>=a.smashThreshold;n--)held++
        smash[port]=held<a.smashFrames
      }
    }
    const push=(shot,x,y,state,age,from)=>{
      const t=shot.track,j=t.x.length
      t.x.push(x);t.y.push(y);t.s.push(state);t.d.push(shot.dir);t.vx.push(shot.vx);t.vy.push(shot.vy)
      if(from&&t.t>=64&&itemMapCrossing(...from,x,y,lines,oldLines)){shot.dead=true;return}
      if(from&&t.t<64){
        const contact=itemMapContact(t,j,lines,oldLines,from)
        if(contact){
          // The ordinary head-on wall branch reverses into its return state.
          // Glancing reflections require the native wall normal adapter.
          const line=lines.find(l=>l[0]===contact.line),dx=line[4]-line[2],dy=line[5]-line[3],len=Math.hypot(dx,dy)
          const dot=(shot.vx*(-dy/len)+shot.vy*(dx/len))/Math.hypot(shot.vx,shot.vy)
          if(dot<0&&dot> -Math.sin(shot.table.special[7]*Math.PI/180)){entries.push({id:shot.id,track:t,j,hits:null,previous:[]});shot.dead=true;return}
          t.x[j]=contact.x;t.y[j]=contact.y;shot.angle=wrap(shot.angle+Math.PI);shot.returned=i;shot.turn=shot.table.special[8]*Math.PI/180;state=t.s[j]=3;age=0
        }
      }
      const hits=itemSpheres(t,j,age,bundle)
      entries.push({id:shot.id,track:t,j,hits,previous:shot.previous,reset:state!==shot.lastState,
        onHit:()=>{if(t.t>=64)shot.dead=true;else if(state!==3){shot.angle=wrap(shot.angle+Math.PI);shot.returned=i+1;shot.turn=shot.table.special[9]*Math.PI/180}}})
      shot.previous=hits||[];shot.lastState=state
    }
    for(let k=live.length-1;k>=0;k--){
      const shot=live[k],t=shot.track,age=i-t.f,a=shot.table.special,j=t.x.length-1
      if(shot.dead||age>shot.life||frames.state[shot.port][i]<11){live.splice(k,1);continue}
      let state=1,animAge=age
      if(t.t>=64)shot.vy=f(shot.vy-Math.abs(a[7]))
      else{
        state=age>=3?2:1
        let speed=Math.hypot(shot.vx,shot.vy)
        if(shot.returned==null){speed=f(speed-a[3]);if(speed<a[6]){speed=a[6];shot.angle=wrap(shot.angle+Math.PI);shot.returned=i;shot.turn=a[8]*Math.PI/180}}
        else speed=Math.min(a[5],f(speed+a[3]))
        shot.vx=f(speed*Math.cos(shot.angle));shot.vy=f(speed*Math.sin(shot.angle))
        if(shot.returned!=null){
          state=3;animAge=i-shot.returned
          const dx=frames.x[shot.port][i]-t.x[j],dy=frames.y[shot.port][i]+fighterDataFor(frames.cid[shot.port][i]).linkArticles.boomerang[5]-t.y[j]
          if(Math.hypot(dx,dy)<a[11]){shot.dead=true;continue}
          if(animAge<a[10])shot.angle=wrap(shot.angle+Math.max(-shot.turn,Math.min(shot.turn,wrap(Math.atan2(dy,dx)-shot.angle))))
        }else if(state===2)animAge=age-3
      }
      push(shot,f(t.x[j]+shot.vx),f(t.y[j]+shot.vy),state,animAge,[t.x[j],t.y[j]])
    }
    for(let port=0;port<frames.x.length;port++){
      const cid=frames.cid[port][i],state=frames.state[port][i],age=frames.age[port][i],dir=frames.dir[port][i],cfg=config(cid,state)
      if(!cfg)continue
      const old=frames.state[port][i-1],same=state===old||[346,349].includes(state)&&[346,349].includes(old)||[350,353].includes(state)&&[350,353].includes(old)
      const before=i&&same&&age>=frames.age[port][i-1]?frames.age[port][i-1]:-1
      for(const spawn of fighterDataFor(cid).hitboxes[state]?.articleSpawns||[]){
        if(![60,61,64,65,140,141].includes(spawn.kind)||spawn.frame<=before||spawn.frame>age)continue
        const table=itemDataFor(spawn.kind),a=table.special,arrow=spawn.kind>=64
        if(!arrow&&live.some(s=>!s.dead&&s.port===port&&s.track.t<64))continue
        let angle,speed,life
        if(arrow){angle=Math.PI/36;speed=f(a[1]+f(charges[port]*f((a[2]-a[1])/cfg.chargeMax)));life=a[0]+a[6]}
        else{
          const y=frames.joyy?.[port]?.[i]??0,x=Math.abs(frames.joyx?.[port]?.[i]??0),v=cfg.boomerang
          angle=Math.abs(y)>v[0]?Math.max(-v[1]*v[2],Math.min(v[1]*v[2],Math.atan2(y,x))):0
          speed=v[smash[port]?3:4]*table.throwSpeed;life=a[smash[port]?1:0]
        }
        const vx=f(dir*speed*Math.cos(angle)),vy=f((arrow?1:dir)*speed*Math.sin(angle))
        const shot={id:`link:${serial++}`,track:{t:spawn.kind,o:port,f:i,x:[],y:[],s:[],d:[],vx:[],vy:[]},table,port,dir,vx,vy,life,angle:dir===1?angle:Math.PI-angle,previous:[]}
        live.push(shot)
        push(shot,f(frames.x[port][i]+dir*spawn.pos[2]),f(frames.y[port][i]+spawn.pos[1]),1,0,null)
      }
    }
    return entries
  }
}

// Items held by Link/Peach are absent from Inishie1's full item record list.
// Release is Fighter_Accessory4 (9), after item physics/map; fuse expiration
// is Item_Anim (1), before the held joint is updated for the current pose.
function unrecordedHeldHistory(bundle) {
  const frames=fighterFrames(bundle),live=[],held=frames.x.map(()=>null)
  let serial=0
  const position=(port,i)=>{
    const move=fighterDataFor(frames.cid[port][i])?.hitboxes?.[frames.state[port][i]],age=frames.age[port][i]
    const pos=Number.isInteger(age)?move?.heldItemPos?.[Math.min(age,move.heldItemPos.length-1)]:null
    return pos?[f(frames.x[port][i]+frames.dir[port][i]*pos[2]),f(frames.y[port][i]+pos[1])]:null
  }
  return (i,lines,oldLines)=>{
    const entries=[]
    const append=(shot,x,y,state,age,from)=>{
      const t=shot.track,j=t.x.length,table=shot.table
      const wasFloor=shot.floor
      t.x.push(x);t.y.push(y);t.s.push(state);t.d.push(shot.dir);t.vx.push(shot.vx);t.vy.push(shot.vy);t.face.push(shot.face)
      const contact=from?itemMapContact(t,j,lines,oldLines,from):null
      if(contact){
        t.x[j]=contact.x;t.y[j]=contact.y
        if(t.t===99){shot.dead=true;return}
        if(Math.abs(shot.vx)>table.special[9]||Math.abs(shot.vy)>table.special[10]){state=t.s[j]=5;shot.explosion=i;age=0;shot.vx=shot.vy=0}
        else if(contact.type===1){state=t.s[j]=4;shot.floor=contact.line;shot.vx=shot.vy=0}
        else {entries.push({id:shot.id,track:t,j,hits:null,previous:[]});shot.dead=true;return}
      }
      const hits=itemSpheres(t,j,age,bundle)
      entries.push({id:shot.id,track:t,j,hits,previous:shot.previous,reset:state!==shot.lastState,
        groundLoad:shot.floor!=null&&state===4?{line:shot.floor,weight:table.weight,landing:wasFloor==null}:null,
        onHit:()=>{if(t.t===99)shot.dead=true;else if(state!==5)shot.explode=true}})
      shot.previous=hits||[];shot.lastState=state
    }
    for(let k=live.length-1;k>=0;k--){
      const shot=live[k],t=shot.track,j=t.x.length-1,table=shot.table
      if(shot.dead){live.splice(k,1);continue}
      let state=t.s[j],age=i-shot.changed,x=t.x[j],y=t.y[j]
      if(t.t!==99&&(i-t.f>table.special[0]||shot.explode)&&state!==5){
        if(shot.unknownPosition){entries.push({id:shot.id,track:t,j,hits:null,previous:[]});shot.dead=true;held[shot.port]=null;continue}
        state=5;shot.explosion=i;shot.changed=i;age=0;shot.vx=shot.vy=0
        if(held[shot.port]===shot)held[shot.port]=null
      }
      if(state===5){if(i-shot.explosion>=table.animations[2].end){shot.dead=true;continue}}
      else if(held[shot.port]===shot){
        const pos=position(shot.port,i)
        if(frames.state[shot.port][i]<11){if(t.t!==99)entries.push({id:shot.id,track:t,j,hits:null,previous:[]});shot.dead=true;held[shot.port]=null;continue}
        const move=fighterDataFor(frames.cid[shot.port][i]).hitboxes[frames.state[shot.port][i]]
        const old=frames.state[shot.port][i-1],before=old===frames.state[shot.port][i]?frames.age[shot.port][i-1]:-1
        const release=move?.articleSpawns?.find(s=>s.kind==='held'&&s.frame>before&&s.frame<=frames.age[shot.port][i])
        if(release){
          held[shot.port]=null;state=2;shot.changed=i;age=0;shot.dir=frames.dir[shot.port][i]
          shot.unknownPosition=false
          shot.vx=f(shot.dir*f(release.velocity[0]*table.throwSpeed));shot.vy=f(release.velocity[1]*table.throwSpeed)
          x=f(frames.x[shot.port][i]+shot.dir*release.pos[2]);y=f(frames.y[shot.port][i]+release.pos[1])
        }else {shot.unknownPosition=!pos;if(pos)[x,y]=pos}
      }else if(shot.floor!=null){
        const line=lines.find(l=>l[0]===shot.floor),old=oldLines.find(l=>l[0]===shot.floor)
        if(line&&old){x=f(x+line[2]-old[2]);y=f(y+line[3]-old[3])}
        else {shot.floor=null;state=1}
      }else {
        if(t.t===99&&++shot.airtime>=table.special[0]){shot.dead=true;continue}
        shot.vy=Math.max(-table.maxFallSpeed,f(shot.vy-table.gravity));x=f(x+shot.vx);y=f(y+shot.vy)
      }
      append(shot,x,y,state,age,state===5||held[shot.port]===shot||shot.changed===i?null:[t.x[j],t.y[j]])
    }
    for(let port=0;port<frames.x.length;port++){
      const cid=frames.cid[port][i],state=frames.state[port][i],age=frames.age[port][i],move=fighterDataFor(cid)?.hitboxes?.[state]
      if(![6,9,20].includes(cid)||held[port])continue
      const old=frames.state[port][i-1],before=old===state?frames.age[port][i-1]:-1
      for(const spawn of move?.articleSpawns||[]){
        if(!spawn.held||spawn.frame<=before||spawn.frame>age)continue
        const table=itemDataFor(spawn.kind),pos=position(port,i)
        let face=null
        if(spawn.kind===99){
          // Grounded solo plucks have no fighter map RNG prefix. Rare item
          // substitutions have different callbacks and remain explicit gaps.
          const rng=frames.x.length===1&&!frames.air[port][i]?frameCursor(bundle,i):null
          if(!rng||rng.int(fighterDataFor(cid).turnipPluck.rareOdds)===0){entries.push({id:`held:${serial++}`,hits:null,previous:[]});continue}
          let roll=rng.int(table.faceWeights.reduce((a,b)=>a+b,0));face=0
          while(roll>=table.faceWeights[face])roll-=table.faceWeights[face++]
        }
        if(!pos){entries.push({id:`held:${serial++}`,hits:null,previous:[]});continue}
        const shot={id:`held:${serial++}`,track:{t:spawn.kind,o:port,f:i,x:[],y:[],s:[],d:[],vx:[],vy:[],face:[]},table,port,dir:frames.dir[port][i],vx:0,vy:0,changed:i,airtime:0,face,previous:[]}
        held[port]=shot;live.push(shot);append(shot,...pos,0,0,null)
      }
    }
    return entries
  }
}

// lbColl_80006E58 sweeps an active hitbox from its preceding center. A newly
// enabled hitbox starts at its current center, not the preceding animation pose.
export function sphereSweepHit(hit,previous,cx,cy,radius=5) {
  const a=previous||hit,dx=hit.x-a.x,dy=hit.y-a.y,dz=hit.z-a.z
  const length=dx*dx+dy*dy+dz*dz
  const t=length?Math.max(0,Math.min(1,((cx-a.x)*dx+(cy-a.y)*dy-a.z*dz)/length)):0
  return (a.x+t*dx-cx)**2+(a.y+t*dy-cy)**2+(a.z+t*dz)**2 <= (hit.radius+radius)**2
}

// StopCeil can call Cb2 twice. Its second map uses the new compressed ECB
// against a model root still at the first corrected position (80082D40).
export function stopCeilContact(frames,port,i,blocks,locations,otherLines=[]) {
  const fighter=fighterDataFor(frames.cid[port][i]),stop=fighter?.ecb?.[250]?.[0]
  if(!stop||i<1||frames.cid[port][i]===18)return null
  const x=frames.x[port][i],x0=frames.x[port][i-1],y=frames.y[port][i]
  // A blended jump ECB need not equal its authored pose. Invert the second
  // map using the unblended StopCeil pose instead. 80048768 loads flags0x12;
  // top>=0 bounds its correction by the new midpoint+1. A unique ceiling
  // in that interval certifies both the first ceiling and the second push.
  const mid=(stop[2]+stop[3])/2+1,base=y-fighter.stopCeilTranslationY
  if(Math.abs(x-x0)>=6)return null
  if(otherLines.some(([,flags,ax,ay,bx,by])=>(flags&15)===2&&
    Math.max(ax,bx)>=Math.min(x,x0)&&Math.min(ax,bx)<=Math.max(x,x0)&&
    Math.max(ay,by)>base&&Math.min(ay,by)<base+mid))return null
  const candidates=locations.flatMap(([cx,cy],j)=>{
    const correction=cy-4.25-base-.0001
    const old=fighter.ecb?.[frames.state?.[port]?.[i-1]]?.[frames.age?.[port]?.[i-1]+1]
    const inside=Math.min(x,x0)>cx-4.25+.002&&Math.max(x,x0)<cx+4.25-.002
    // The compressed second ECB can push the root sideways past a corner.
    // Its inverted top must then agree with the authored first-map pose,
    // and the corrected root must identify the receiving ceiling. The
    // preceding root can be over its neighbor before horizontal physics.
    const corner=old&&x>cx-4.25+.002&&x<cx+4.25-.002&&Math.abs(mid-correction-old[3])<.002&&
      x0+Math.max(2,-old[0],old[1])>cx-4.25&&x0-Math.max(2,-old[0],old[1])<cx+4.25
    return blocks[j].active&&(inside||corner)&&
      correction>.002&&correction<mid-.002?[{block:j,correction,top:mid-correction}]:[]
  })
  return candidates.length===1?candidates[0]:null
}
function ceilingBump(frames,port,i,blocks) {
  if(frames.state[port][i]!==250){
    if(i<2||!frames.air[port][i]||frames.state[port][i]===frames.state[port][i-1]&&frames.age[port][i]===frames.age[port][i-1])return false
    const top=fighterDataFor(frames.cid[port][i])?.ecb?.[frames.state[port][i]]?.[frames.age[port][i]]?.[3]
    if(!Number.isFinite(top))return false
    const x=frames.x[port][i],ceiling=frames.y[port][i]+top
    const hits=centers.flatMap(([cx,cy],j)=>blocks[j].active&&Math.abs(ceiling-(cy-4.25))<.002&&x>cx-4.25&&x<cx+4.25?[j]:[])
    return hits.length===1?{block:hits[0],bump:f(frames.y[port][i-1]-frames.y[port][i-2])}:hits.length?null:false
  }
  if(frames.state[port][i]!==250||frames.age[port][i]!==0||frames.state[port]?.[i-1]===250)return false
  if(i<2)return null
  const fighter=fighterDataFor(frames.cid[port][i]),x=frames.x[port][i],y=frames.y[port][i],dir=frames.dir?.[port]?.[i]
  const old=fighter?.ecb?.[frames.state[port][i-1]]?.[frames.age[port][i-1]+1],next=fighter?.ecb?.[250]?.[0]
  if(!old||!next||![1,-1].includes(dir))return null
  const x0=frames.x[port][i-1],moving=Math.abs(x-x0)>.002
  const correction=frames.cid[port][i]===18?0:Math.max(0,(next[2]+next[3])/2+1-old[3])
  const ceiling=y-fighter.stopCeilTranslationY+correction+(correction ? .0001 : 0)
  if(frames.cid[port][i]===18&&(moving||y+next[3]+2>=ceiling-.002))return null
  const left=Math.min(-2,dir===1?old[0]:-old[1]),right=Math.max(2,dir===1?old[1]:-old[0])
  const candidates=centers.flatMap(([cx,cy],j)=>blocks[j].active&&Math.abs(ceiling-(cy-4.25))<.002&&
    (moving||correction ? Math.abs(x-x0)<6&&Math.min(x,x0)>cx-4.25+.002&&Math.max(x,x0)<cx+4.25-.002 : x+right>cx-4.25&&x+left<cx+4.25)?[j]:[])
  const inferred=candidates.length!==1?stopCeilContact(frames,port,i,blocks,centers,collisionLines(data,data.initial,[true])):null
  if(candidates.length!==1&&!inferred)return null
  // Fighter_procAnim saves the preceding post-to-post displacement before
  // physics. grYorster_802024F0 reads it through ftLib_GetPosDelta.
  const bump=f(frames.y[port][i-1]-frames.y[port][i-2])
  return {block:inferred?.block??candidates[0],bump:correction||inferred?f(bump+bump):bump}
}

const caches=new WeakMap()
// grLib_801C9EE8 expands the current ECB rectangle, rather than testing a
// fixed distance from the fighter root. Ground updates precede fighter map,
// so the preceding finalized pose supplies this rectangle.
export function materialOccupancy(frames,port,i,cx,cy,padding,allowSpecial=true,boundsOverride=null) {
  if(i<0||frames.state[port][i]==null)return false
  const x=frames.x[port][i],y=frames.y[port][i],cid=frames.cid[port][i],state=frames.state[port][i]
  const table=fighterDataFor(cid),dir=frames.dir?.[port]?.[i]
  if(cy<y-15-padding-.02)return false
  if(Number.isFinite(table?.ecbRadius)&&(Math.abs(x-cx)>table.ecbRadius+padding+.02||Math.abs(y-cy)>table.ecbRadius+padding+.02))return false
  // Keep the pinned Marth projection, as in stage19.returnOccupied. Other
  // fighters' Fall_Anim drift blends require a runtime pose reconstruction.
  if(cid!==18&&state>=29&&state<=34)return null
  // Ness's PK Thunder hold/end uses the authored pose; its remote item
  // never drives fighter bones. Other special ECB overrides remain gated.
  const copiedPose=cid===4&&/^(Mr|Dr|Lg|Pk|Pc|Sk|Mt|Gw|Fx|Fc|Ss|Lk|Cl|Ns)Special/.test(table?.hitboxes?.[state]?.motion||'')
  if(state>=341&&!allowSpecial&&!boundsOverride&&!(cid===8&&state>=358&&state<=366||cid===7&&state>=341&&state<=348||cid===24&&[353,354].includes(state)||copiedPose))return null
  const bounds=boundsOverride||table?.ecb?.[state]?.[frames.age[port][i]]
  if(!bounds||![1,-1].includes(dir))return null
  const left=Math.min(-2,dir===1?bounds[0]:-bounds[1]),right=Math.max(2,dir===1?bounds[1]:-bounds[0])
  // ECB bottoms can remain locked during an aerial transition. The lower
  // bound certifies misses; ambiguous overlap remains unknown.
  const distances=[cx-x-left+padding,x+right+padding-cx,cy-y+padding,y+bounds[3]+padding-cy]
  if(distances.some(d=>d<-.02))return false
  if(distances.some(d=>d<.02))return null
  return true
}
// grLib_801C9EE8 visits every Fighter GObj, including the sleeping member
// of a Zelda/Sheik pair. Transformation preserves that member's last ECB
// until it becomes active again; the active replay row alone is insufficient.
export function sleepingFighterHistory(frames) {
  const asleep=frames.x.map(()=>new Map());let last=-1
  return (i,cx,cy,padding)=>{
    for(let k=last+1;k<=i;k++)for(let port=0;port<frames.x.length;port++){
      const cid=frames.cid[port][k],old=frames.cid[port][k-1]
      if(k&&cid!==old&&[7,19].includes(cid)&&[7,19].includes(old)){
        asleep[port].set(old,k-1);asleep[port].delete(cid)
      }
    }
    last=Math.max(last,i)
    return asleep.flatMap((actors,port)=>[...actors].map(([cid,at])=>{
      const x=frames.x[port][at],y=frames.y[port][at],fighter=fighterDataFor(cid)
      if(Math.abs(x-cx)>fighter.ecbRadius+padding||Math.abs(y-cy)>fighter.ecbRadius+padding)return false
      const bounds=fighter.ecb?.[frames.state[port][at]]?.[frames.age[port][at]],dir=frames.dir[port][at]
      if(!bounds||![1,-1].includes(dir))return null
      const left=Math.min(-2,dir===1?bounds[0]:-bounds[1]),right=Math.max(2,dir===1?bounds[1]:-bounds[0])
      return cx>=x+left-padding&&cx<=x+right+padding&&cy>=y-padding&&cy<=y+bounds[3]+padding
    }))
  }
}

export function itemMaterialOccupancy(track,cx,cy,padding,at=track.x.length-1,bundle=null){
  // Needle map uses mpCheckAllRemap directly. Its separate CollData stays
  // at the corrected spawn point (it_80275E98); animation never replaces
  // the fixed ECB. Chain link CollData is outside the item GObj list.
  if(track.fixedEcb){
    const [left,right,bottom,top]=track.fixedEcb,[x,y]=track.fixedPosition||[track.x[0],track.y[0]]
    return cx>=x+left-padding&&cx<=x+right+padding&&cy>=y+bottom-padding&&cy<=y+top+padding
  }
  const table=itemDataFor(track.t)
  if(track.t===156){
    const port=itemOwnerPort(track,0,bundle),i=track.f,frames=bundle?.frames
    if(!frames||port==null||frames.cid[port][i]!==4||![510,511].includes(frames.state[port][i])||frames.age[port][i]>1)return null
    const spawn=fighterDataFor(4)?.hitboxes[frames.state[port][i]]?.articleSpawns?.find(s=>s.kind===156&&s.frame===frames.age[port][i])
    if(!spawn)return null
    const x=f(frames.x[port][i]+frames.dir[port][i]*spawn.pos[2]),y=f(frames.y[port][i]+spawn.pos[1])
    return cx>=x-4-padding&&cx<=x+4+padding&&cy>=y-padding&&cy<=y+8+padding
  }
  if([52,53,138,139].includes(track.t)){
    const port=itemOwnerPort(track,0,bundle),i=track.f,frames=bundle?.frames
    if(!frames||port==null||i<1||![341,344,423,426,520,523].includes(frames.state[port][i])||frames.age[port][i]>1)return null
    const x=frames.x[port][i-1],y=frames.y[port][i-1]
    return cx>=x-4-padding&&cx<=x+4+padding&&cy>=y-padding&&cy<=y+8+padding
  }
  if(['jolt','joltair'].includes(table?.family)){
    // it_8026E9A4 maps the projectile's separate Vec3, never CollData.
    // The child copies its parent's unchanged CollData in it_802B3F88.
    // Recover that fixed spawn only when a recorded flight sample and the
    // authored fighter spawn agree; a first-tick map correction stays gated.
    const parents=table.family==='jolt'?[track]:(bundle?.items||[]).filter(t=>t.t===track.t-1&&t.o===track.o&&t.f<=track.f&&t.f+t.x.length>track.f)
    if(parents.length!==1||!bundle)return null
    const parent=parents[0],port=itemOwnerPort(parent,0,bundle),i=parent.f,frames=bundle.frames
    if(parent.s[0]!==0||port==null||i<1)return null
    const cid=frames.cid[port][i],state=frames.pre_state?.[port]?.[i]??frames.state[port][i],age=frames.age[port][i]
    const spawn=fighterDataFor(cid)?.hitboxes[state]?.articleSpawns?.find(s=>s.kind===parent.t&&s.frame===age)
    if(!spawn)return null
    const x=f(frames.x[port][i-1]+frames.dir[port][i]*spawn.pos[2]),y=f(frames.y[port][i-1]+spawn.pos[1])
    if(Math.abs(f(parent.x[0]-parent.vx[0])-x)>.002||Math.abs(f(parent.y[0]-parent.vy[0])-y)>.002)return null
    const a=itemDataFor(parent.t),[top,bottom,right,left]=a.ecb.map(v=>v*a.scale)
    return cx>=x-left-padding&&cx<=x+right+padding&&cy>=y-bottom-padding&&cy<=y+top+padding
  }
  if(table?.family==='chef'){
    const j=at,[top,bottom,right,left]=table.ecb.map(v=>v*table.scale),x=track.x[j],y=track.y[j]
    return cx>=x-left-padding&&cx<=x+right+padding&&cy>=y-bottom-padding&&cy<=y+top+padding
  }
  if(table?.family==='fireball'){
    // These map callbacks update the fixed CollData every tick. A pill's
    // rotation is available on reconstructed tracks; a truncated recorded
    // track cannot establish its initial angle and remains conservative.
    if(table.mapSpin&&!Number.isFinite(track.mapAngle?.[at]))return null
    const points=fixedItemEcbPoints(table,track.d?.[at]||1,track.mapAngle?.[at]),x=track.x[at],y=track.y[at]
    return cx>=x+points[2][0]-padding&&cx<=x+points[3][0]+padding&&cy>=y+points[0][1]-padding&&cy<=y+points[1][1]+padding
  }
  if(![79,152,97].includes(track.t))return null
  const bounds=itemDataFor(track.t)?.ecb
  if(!bounds)return null
  const [top,bottom,right,left]=bounds,x=track.x[0],y=track.y[0]
  return cx>=x-left-padding&&cx<=x+right+padding&&cy>=y+bottom-padding&&cy<=y+top+padding
}
// The ground callback changes animation requests after this pass's pose.
// Hidden joints still animate; their previous vertices remap chain rays when
// mpJointListAdd restores collision. Only DAT rotations are sampled here.
export function blockVertices(blocks){
  const vertices=data.initial.map(v=>v.slice())
  for(let j=0;j<blocks.length;j++){
    const b=blocks[j],angles=data.blockAngles
    if(!angles||b.state!==3&&b.state!==4)continue
    const angle=angles[b.state===3?0:b.state===4?2:1][b.state===3||b.state===4?b.timer:0]??angles[1][0]
    const scale=f(f(Math.cos(angle))*data.scale),[at,n]=data.joints[j+1],cy=centers[j][1]
    for(let k=at;k<at+n;k++)vertices[k][1]=f(cy+f((data.initial[k][1]<cy?-5:5)*scale))
  }
  return vertices
}

function build(bundle) {
  let blocks=Array.from({length:9},initialBlock), pending=blocks.map(()=>({}))
  const uncertain=new Set()
  const frames=fighterFrames(bundle)
  const rows=[], hitSets=frames.x.map(()=>new Set()), lastActions=[],lastSpheres=[]
  const charged=smashChargeHistory(frames)
  const yoyo=nessYoyoHistory(bundle),luigi=luigiMissileHistory(bundle),skull=skullBashHistory(bundle),thunder=thunderHitHistory(bundle),tether=airCatchHistory(bundle),chain=chainHistory(bundle)
  const itemRows=itemAttackHistory(bundle),itemHits=new Map(),missingBirths=missingProjectileBirths(bundle)
  const missingJolts=unrecordedJoltHistory(bundle,{missingOnly:true}),sleeping=sleepingFighterHistory(frames)
  let unavailable=Infinity
  for(let i=0;i<bundle.meta.n;i++) {
    // Native state 3 and state 4 use different expanded ECB rectangles.
    for(let j=0;j<9;j++) if(blocks[j].state===3 && blocks[j].timer>=323 || blocks[j].state===4) {
      const padding=blocks[j].state===3?f(f(10*data.scale)-2):f(f(10*data.scale)/2)
      const occupants=[...frames.x.map((_,port)=>materialOccupancy(frames,port,i-1,...centers[j],padding,false,chain.bounds[port])),...sleeping(i-1,...centers[j],padding)]
      // Item ECB animation is not implied by its hitbox. Distant items are
      // harmless to clearance; nearby ones require an item ECB adapter.
      for(const track of bundle.items||[]){const at=i-1-track.f;if(track.t!==160&&at>=0&&at<track.x.length&&(['jolt','joltair'].includes(itemDataFor(track.t)?.family)||Math.abs(track.x[at]-centers[j][0])<20&&Math.abs(track.y[at]-centers[j][1])<30)){
        // Chain's Item CollData remains a zero-sized rectangle at spawn;
        // its links have separate CollData outside the item GObj list.
        occupants.push(itemMaterialOccupancy(track,...centers[j],padding,at,bundle))
      }}
      if(occupants.includes(true))pending[j].occupied=true
      else if(occupants.includes(null)){pending[j].occupied=true;uncertain.add(j)}
    }
    const before=blocks,vertices=blockVertices(before)
    blocks=blocks.map((b,j)=>blockStep(b,pending[j]));pending=blocks.map(()=>({}))
    // Simulate the latest possible restoration while clearance is unknown.
    // Once that branch restores, every earlier possible return is visible
    // too. A possible intervening attack below still gates the whole history.
    for(const j of uncertain)if(blocks[j].state===1)uncertain.delete(j)
    const currentLines=collisionLines(data,vertices,[true,...blocks.map(b=>b.active)])
    const allLines=collisionLines(data,vertices,Array(10).fill(true))
    // Unknown ECB clearance can delay our state4 return beyond the native
    // return. Its first visible pose is ambiguous; the next pass is rest.
    rows.push(uncertain.size||blocks.some((b,j)=>before[j].state===4&&b.state===1)?null:{
      active:blocks.map(b=>b.active),
      // Keep only rare visible animated poses; ordinary rows retain the
      // compact visibility mask instead of duplicating every terrain line.
      vertices:blocks.some((b,j)=>b.active&&[3,4].includes(before[j].state))?vertices:null,
    })
    for(let port=0;port<frames.x.length;port++) {
      const x=frames.x[port][i],y=frames.y[port][i],state=frames.state[port][i],age=frames.age[port][i]
      const yoyoHits=yoyo(port,i,currentLines),luigiHits=luigi(port,i,currentLines),skullHits=skull(port,i,currentLines),thunderHits=thunder(port,i),tetherHits=tether(port,i,currentLines),chainHits=chain(port,i,currentLines,allLines)
      if(state==null){lastActions[port]=null;lastSpheres[port]=[];continue}
      if(state!==lastActions[port] || (i && (age<frames.age[port][i-1] || frames.cid[port][i]!==frames.cid[port][i-1]))) {hitSets[port].clear();lastSpheres[port]=[]}
      const move=fighterDataFor(frames.cid[port][i])?.hitboxes?.[state]
      lastActions[port]=state
      if(yoyo.reset[port]||chain.reset[port])hitSets[port].clear()
      if(chain.reset[port])lastSpheres[port]=[]
      const near=centers.some(([cx,cy])=>Math.abs(cx-x)<45 && Math.abs(cy-y)<45)
      if(!near){lastSpheres[port]=[];continue}
      if(state>=44 && state<=69 || state>=341 || state>=94 && state<=143
        || [187,195,217,219,220,221,222,256,257].includes(state)) {
        const spheres=chainHits!==undefined?chainHits:tetherHits!==undefined?tetherHits:thunderHits!==undefined?thunderHits:skullHits!==undefined?skullHits:luigiHits!==undefined?luigiHits:yoyoHits===undefined?attackSpheres(frames.cid[port][i],state,age,x,y,frames.dir?.[port]?.[i],undefined,1):yoyoHits
        if(!spheres){unavailable=Math.min(unavailable,i);continue}
        const groups=new Set(spheres.map(h=>h.group))
        for(const key of hitSets[port])if(!groups.has(Number(key.split(':')[1])))hitSets[port].delete(key)
        for(let j=0;j<9;j++) {
          if(blocks[j].state>1&&!uncertain.has(j))continue
          const [cx,cy]=centers[j]
          for(const hit of spheres){
            const key=`${j}:${hit.group}`
            if(hitSets[port].has(key)||!sphereSweepHit(hit,lastSpheres[port]?.find(a=>a.id===hit.id&&a.group===hit.group),cx,cy))continue
            if(uncertain.has(j)){unavailable=Math.min(unavailable,i);continue}
            pending[j].damage=f((pending[j].damage||0)+materialDamage(hit,move,charged[port][i]));hitSets[port].add(key);yoyo.hit(port)
          }
        }
        lastSpheres[port]=spheres
      } else {
        lastSpheres[port]=[]
      }
      const bump=ceilingBump(frames,port,i,blocks.map((b,j)=>uncertain.has(j)?{...b,active:true}:b))
      if(bump===null)unavailable=Math.min(unavailable,i)
      else if(bump&&uncertain.has(bump.block))unavailable=Math.min(unavailable,i)
      else if(bump)pending[bump.block].bump=f((pending[bump.block].bump||0)+bump.bump)
    }
    const itemLines=currentLines
    for(const entry of [...itemRows[i],...missingJolts(i,itemLines),...missingBirths(i,currentLines)]) {
      const hits=itemEntryHits(entry,currentLines)
      const {id,track,j,previous}=entry
      if(!hits){unavailable=Math.min(unavailable,i);continue}
      if(!itemHits.has(id))itemHits.set(id,new Set())
      const seen=itemHits.get(id),groups=new Set(hits.map(h=>h.group))
      if(entry.reset)seen.clear()
      for(const key of seen)if(!groups.has(Number(key.split(':')[1])))seen.delete(key)
      for(let part=0;part<9;part++) {
        if(blocks[part].state>1&&!uncertain.has(part))continue
        for(const hit of hits) {
          const key=`${part}:${hit.group}`
          if(seen.has(key)||!sphereSweepHit(hit,previous.find(h=>h.id===hit.id&&h.group===hit.group),...centers[part]))continue
          if(uncertain.has(part)){unavailable=Math.min(unavailable,i);continue}
          if(hit.damageUnknown){unavailable=Math.min(unavailable,i);continue}
          pending[part].damage=f((pending[part].damage||0)+Math.trunc(hit.damage));seen.add(key);entry.onHit?.()
        }
      }
    }
  }
  return {rows,unavailable}
}

export default function simulate(bundle,idx) {
  if (!data || !fighterDataReady(bundle) || !itemDataReady(bundle)) return null
  if(!supportedHistory(bundle,idx,16)) return null
  let c=caches.get(bundle)
  if(!c){c=build(bundle);caches.set(bundle,c)}
  if(idx>=c.unavailable||!c.rows[idx])return null
  return {lines:collisionLines(data,c.rows[idx].vertices||data.initial,[true,...c.rows[idx].active]),replace:true,complete:true}
}

registerStageSimData(16, value => {
  data = value
  p=data.params
  centers=data.joints.slice(1).map(([start,n])=>{
    const v=data.initial.slice(start,start+n)
    return [v.reduce((s,p)=>s+p[0],0)/n,v.reduce((s,p)=>s+p[1],0)/n]
  })
})
