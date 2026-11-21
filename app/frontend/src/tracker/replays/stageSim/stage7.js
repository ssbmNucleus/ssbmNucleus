import { COLLISION_TIMING } from './collisionTiming.js'
export const { collisionLag } = COLLISION_TIMING[7]
import { frameCursor, random, advanceSeed, nextSeed as stepSeed } from './rng.js'
import { registerStageSimData, fighterFrames, supportedFighterHistory } from '../stageData.js'
import { attackSpheres, materialDamage } from './stage16.js'
import { hitCapsule, mayDamageStage } from './stage6.js'
let DATA

// NTSC 1.02 grcorneria.c: priority-4 ship drift starts when READY releases at
// -39. Camera, water, cannon and synchronous spawn work share its cursor
// before the flyby scheduler.
const F = Math.fround
const cache = new WeakMap()
export { stepSeed }
const clamp = (v, limit) => Math.max(-limit, Math.min(limit, v))

export function initialCannon() {
  return { phase:0,wait:0,timer:0,shots:0,kind:0,side:0,damage:0 }
}

// grCorneria_801E1348 / fn_801E12D4. The replay adapter supplies the camera
// prefix and previous fighter Y. Item damage arrives after this proc, and
// becomes pending input to the next ground pass.
// Callbacks consume
// their synchronous draws on the SAME cursor before later flyby decisions.
// Constants are the vanilla GrCn.dat yakumono x18..x38 values.
export function advanceCannon(state, rng, {
  fighterInRange=false,damage=0,effect=()=>{},laser=()=>{},
}={}) {
  const s={...state,damage:F(state.damage+damage)}
  if(damage>0&&s.damage>=200&&s.phase<4)s.phase=4
  switch(s.phase){
  case 0:
    if(s.wait===0){
      if(rng.float()<=F(.5)){s.kind=0;s.shots=1}else{s.kind=1;s.shots=8+rng.int(4)}
      s.timer=160
      effect(0xBC,2,rng);effect(0xBC,3,rng)
      s.phase=1
    }else s.wait--
    break
  case 1:
    if(s.timer===0){s.timer=180;s.phase=2}else s.timer--
    break
  case 2:
    if(fighterInRange)s.timer=0
    if(s.timer===0)s.phase=3;else s.timer--
    break
  case 3:
    if(s.shots!==0){
      if(s.wait===0){
        effect(0xC0,s.side?2:3,rng)
        laser(s.kind,s.side,rng)
        s.side^=1;s.wait=10;s.shots--
      }else s.wait--
    }else{s.wait=1200+rng.int(1200);s.timer=0;s.phase=0}
    break
  case 4:
    effect(0xE3,2,rng);effect(0xE3,3,rng)
    s.phase=5 // disables collision joint 4; never automatically restores
    break
  }
  return s
}

// HSD FOBJ interpolation, including tangent-only packets.
export function sample(keys, frame) {
  let p0=0,p1=0,d0=0,d1=0,t0=0,t1=0,last=0,first=true
  for(const [time,op,value,tan] of keys){
    if(op===5){d0=d1;d1=tan;last=op;continue}
    if(first){p1=value;d1=tan||0;t1=time;last=op;first=false;if(frame<t1)return p1;continue}
    p0=p1;p1=value;t0=t1;t1=time
    if(op===4){d0=d1;d1=tan}else if(op===3||last!==5){d0=d1;d1=0}
    if(frame<t1){
      if(t1===t0)return p1
      const u=(frame-t0)/(t1-t0)
      if(last===1||last===6)return p0
      if(last===2)return p0+(p1-p0)*u
      return (2*u**3-3*u*u+1)*p0+(u**3-2*u*u+u)*(t1-t0)*d0+(-2*u**3+3*u*u)*p1+(u**3-u*u)*(t1-t0)*d1
    }
    last=op
  }
  return p1
}

export function pathPosition(route, frame) {
  const matrices=[]
  for(const node of route.nodes){
    const values={1:node.srt[0],2:node.srt[1],3:node.srt[2],8:node.srt[3],9:node.srt[4],10:node.srt[5],5:node.srt[6],6:node.srt[7],7:node.srt[8]}
    for(const [type,keys] of Object.entries(node.tracks))values[type]=sample(keys,frame)
    const [rx,ry,rz,sx,sy,sz,x,y,z]=[1,2,3,8,9,10,5,6,7].map(k=>values[k])
    const cx=Math.cos(rx),cy=Math.cos(ry),cz=Math.cos(rz),a=Math.sin(rx),b=Math.sin(ry),c=Math.sin(rz)
    let m=[cy*cz*sx,(a*b*cz-cx*c)*sy,(cx*b*cz+a*c)*sz,x,cy*c*sx,(a*b*c+cx*cz)*sy,(cx*b*c-a*cz)*sz,y,-b*sx,a*cy*sy,cx*cy*sz,z]
    if(node.parent>=0){
      const p=matrices[node.parent],out=[]
      for(let r=0;r<3;r++)for(let col=0;col<4;col++)out[r*4+col]=p[r*4]*m[col]+p[r*4+1]*m[4+col]+p[r*4+2]*m[8+col]+(col===3?p[r*4+3]:0)
      m=out
    }
    matrices.push(m)
  }
  const m=matrices.at(-1)
  return [m[3],m[7],m[11]]
}

export function initialState() {
  return { frame: -40, x:0,y:0,vx:0,vy:0,ax:0,ay:0,remaining:0,
    wait:600,type:0,group:0,plane:null }
}

// grCorneria_801E1970. Round every stored float, including velocities, so
// long runs and arbitrary seeks do not accumulate double-precision drift.
export function drift(s, randf) {
  if(s.remaining<=0){
    s.remaining=Math.trunc(F(150*randf()+30))
    s.ax=F(F(.002)*F(2*F(randf()-.5)))
    s.ay=F(F(.002)*F(2*F(randf()-.5)))
  }
  s.remaining--
  s.vx=clamp(F(s.vx+s.ax),F(.1));s.vy=clamp(F(s.vy+s.ay),F(.1))
  s.x=F(s.x+s.vx);s.y=F(s.y+s.vy)
  if(s.x>20)s.ax=-F(.002);else if(s.x< -20)s.ax=F(.002)
  if(s.y>20)s.ay=-F(.002);else if(s.y< -20)s.ay=F(.002)
}

// grCorneria_801DD478 recreates map 8 at x=0 before frame -123. The ship's
// priority-4 proc precedes the strips. A newly appended strip DOES run in
// its birth pass (HSD_GObjProc_QueueProc), so a fixed 6048-unit modulo drifts
// by two units per successor. Preserve that object lifecycle and float32.
const stripRows=[],stripObjects=[{kind:8,x:0,spawned:false}]
const stripHalf=kind=>F(F((kind===4?4800:3200)*F(.54))/2)
function stripsAt(frame){
  const idx=Math.max(0,frame+123)
  while(stripRows.length<=idx){
    stripRows.push(stripObjects.map(o=>({...o})))
    for(const o of stripObjects){
      o.x=F(o.x+2)
      const half=stripHalf(o.kind)
      if(!o.spawned){
        if(o.x>=F(half-1400)){
          const kind=o.kind===8?9:o.kind===9?4:8
          stripObjects.push({kind,x:F(o.x-F(half+stripHalf(kind))),spawned:false})
          o.spawned=true
        }
      }else if(o.x>=F(half+1400))o.dead=true
    }
    for(let j=stripObjects.length-1;j>=0;j--)if(stripObjects[j].dead)stripObjects.splice(j,1)
  }
  return stripRows[idx]
}
export function nearLand(frame,shipX){
  return backgroundKind(frame,shipX)===8||backgroundKind(frame,shipX-300)===8
}

export function advance(state, seed, beforeFlyby) {
  const s={...state,frame:state.frame+1,plane:state.plane?{...state.plane}:null}
  const rng=random(seed),randf=()=>rng.float(),rand=n=>rng.int(n)
  drift(s,randf)
  if(beforeFlyby?.(s,rng)===false)return null
  if(!s.plane){
    if(--s.wait<=0){
      let type=s.type
      const count=nearLand(s.frame,s.x)?9:13
      while(type===s.type)type=rand(count)+1
      s.type=type;s.group=s.group===4?1:randf()>F(.15)?1:4
      if(s.group!==4)rand(2) // model's initial laser side
      const route=[-1,0,1,2,3,4,5,6,6,6,7,8,9,10][type]
      s.plane={start:s.frame,route,bankState:0,bankWait:120,bankStart:s.frame,bankAnim:-1}
    }
  }else{
    s.wait=960+rand(840) // re-randomized each active frame, including deletion
    if(s.frame-s.plane.start>=DATA.routes[s.plane.route].end){s.plane=null;return s}
  }
  const p=s.plane
  if(p&&s.type<=9){
    if(p.bankState===0){
      if(p.bankWait<=0){
        p.bankState=rand(5)+1
        p.bankAnim=[[-1,-1],[1,0],[2,2],[4,4],[5,5],[-1,-1]][p.bankState][s.group===4?1:0]
        p.bankStart=s.frame
      }
      p.bankWait--
    }else if(p.bankState<5&&s.frame-p.bankStart>DATA.banks[s.group===4?1:0][p.bankAnim].end){
      p.bankState=0;p.bankWait=120;p.bankAnim=-1
    }
  }
  return s
}

export function geometry(s) {
  const lines=[]
  const add=(first,last,scale,x,y)=>{
    for(let id=first;id<=last;id++){
      const [a,b,flag]=DATA.lines[id],p=DATA.vertices[a],q=DATA.vertices[b]
      lines.push([id,flag,F(p[0]*scale+x),F(p[1]*scale+y),F(q[0]*scale+x),F(q[1]*scale+y)])
    }
  }
  // The gun (lines 27-29) goes with collision joint 4 when destroyed. Past the
  // damage witness (drift-only) it is drawn only up to the last frame a fighter
  // stood on it: an uncertain surface is not drawn as if certain.
  const gun=s.cannon?.phase!==5&&(!s.driftOnly||s.gunCertain)
  add(9,gun?29:26,F(.54),s.x,F(250+s.y));add(42,64,F(.54),s.x,F(250+s.y))
  // Past the cannon's damage witness only the hull's drift is known: the
  // Arwings are unknown and left out, and the result is partial.
  if(s.driftOnly)return {lines,replace:true,complete:false}
  const p=s.plane
  if(p&&s.type<=9){
    const t=s.frame-p.start,route=DATA.routes[p.route]
    const [px,py,pz]=pathPosition(route,t)
    const offset=s.type===7?[-40,10,0]:s.type===8?[15,5,0]:s.type===9?[190,-10,0]:[0,0,0]
    const z=F(px*F(.27)+offset[2])
    const bank=p.bankAnim<0?null:DATA.banks[s.group===4?1:0][p.bankAnim]
    const bankFrame=Math.max(0,s.frame-p.bankStart-1)
    let angle=bank?sample(bank.keys,bankFrame):0
    if(s.group===4)angle=0
    while(angle< -Math.PI)angle+=2*Math.PI
    while(angle>Math.PI)angle-=2*Math.PI
    if(Math.abs(z)<10&&Math.abs(angle)<F(Math.PI/3)){
      const x=F(s.x+F(-F(pz*F(.54))+offset[0]))
      const y=F(Math.max(100,F(F(250+s.y)+F(F(py-(t===0?0:349))*F(.54))+offset[1]))+F((bank?sample(bank.y,bankFrame):0)*F(.27)))
      if(s.group===4)add(30,33,F(.27),x,y);else add(0,2,F(.27),x,y)
    }
  }
  return {lines,replace:true,complete:true}
}

export function backgroundKind(frame,x) {
  for(const kind of [8,9,4])for(const o of stripsAt(frame)){
    const half=stripHalf(kind)
    if(o.kind===kind&&x>F(o.x-half)&&x<F(o.x+half))return kind
  }
  return -1
}

// Fallback for unsupported camera subjects/lifecycles. Normal VS uses the
// reconstructed preceding-frame interest below, validated against RAM.
// Camera_8002A768 clamps the standard VS view to the stage bounds and
// 80029AAC interpolates inside them. Drift can overshoot its +/-20 limit by
// at most .1 + .1*49/2 = 2.55; 22.6 rounds outward for float32. Enumerate
// every strip intersecting this interval, then emit only collision consensus.
export function cameraBackgroundKinds(frame){
  const lo=DATA.camera.bounds[0]-22.6,hi=DATA.camera.bounds[1]+22.6
  return [...new Set(stripsAt(frame).filter(o=>o.x+stripHalf(o.kind)>lo&&o.x-stripHalf(o.kind)<hi).map(o=>o.kind))]
}

export function initialBackground(){return {active:false,latched:false,timer:0,speed:0,depth:0}}
export function advanceBackground(previous,kind,rng) {
  const s={...previous}
  if(!s.active){
    if(!s.latched&&kind===4){
      if(rng.int(3)===0){s.active=true;s.timer=0;s.speed=0}
      s.latched=true
    }
    if(kind===9)s.latched=false
  }else {
    const down=s.timer++<900,speed=s.speed,t=F(speed/F(.005))
    const stop=F(F(speed*t)+F(F(-.0025)*F(t*t)))
    const distance=down?F(s.depth-F(F(50*F(.54))-250)):-s.depth
    s.speed=distance>stop?Math.min(3,F(speed+F(.005))):Math.max(F(.005),F(speed-F(.005)))
    s.depth=F(s.depth+(down?-s.speed:s.speed))
    if(down)s.depth=Math.max(F(F(50*F(.54))-250),s.depth)
    else if(s.depth>0){s.depth=0;s.active=false}
  }
  return s
}

// grZakoGenerator_801CA43C: transformed segment/height intersection, then
// one probability draw per intersecting segment, in descriptor order.
// GrCn map_ptcl 30004/30000 both have kind&0x100: synchronous allocation
// consumes no draws. Emission is later, in efLib's priority-15 proc.
export function waterDraws(state,rng) {
  const height=F(F(-35*F(.54))-state.background.depth),y=F(250+state.y)
  for(const [a,b]of [[-58,-73],[-21,-59],[-59,-75]]){
    const y0=F(F(a*F(.54))+y),y1=F(F(b*F(.54))+y)
    if(!((y0>height&&y1>height)||(y0<height&&y1<height)))rng.float()
  }
}

// Camera callbacks run at priority 18, fighter p_link 8 before camera 18.
// The stage therefore reads the preceding post-physics camera interest.
// Numeric constants are the NTSC camera globals; archive-specific values
// and fighter extents are lazy-loaded with the stage. Camera shake changes
// the CObj translation, not Camera_GetTransformInterest.
const clip=(x,a,b)=>Math.max(a,Math.min(b,x)),rad=F(Math.PI/180),aspect=F(1.2173333)
// lbVector_Rotate uses its authored fifth-order polynomial, not sinf/cosf.
export function cameraSin(a){
 if(a>F(Math.PI))a=F(a-F(2*Math.PI));else if(a< -F(Math.PI))a=F(a+F(2*Math.PI))
 return F(F(F(.9878619909286499)*a)-F(F(F(F(.15527099370956421)*a)*a)*a)+F(F(F(F(F(F(.0056429998949170113)*a)*a)*a)*a)*a))
}
const rot=(v,axis,a)=>{const c=cameraSin(F(a+F(Math.PI/2))),s=cameraSin(a),[x,y,z]=v;return axis===1?[x,F(y*c-F(z*s)),F(y*s+F(z*c))]:[F(x*c+F(z*s)),y,F(z*c-F(x*s))]}
function cameraStep(c,b,i,s){
 const data=DATA.camera,g=data.ground
 const [l,r,bt,tp]=data.bounds
 const f=fighterFrames(b),left=F(s.x+l),right=F(s.x+r),bottom=F(F(250+s.y)+bt),top=F(F(250+s.y)+tp)
 const subjects=[]
 for(let p=0;p<f.x.length;p++){
  if(!Number.isFinite(f.x[p][i])){c.subjects[p]=null;continue}
  const cid=f.cid[p][i],state=f.state[p][i],a=data.fighters[cid]
  if(!a||data.unknown.includes(state)){c.unknown=true;continue}
  const dir=f.dir[p][i],targets=dir===1?[a[2],a[1]*g.fixedZoom]:[-a[1]*g.fixedZoom,-a[2]]
  let old=c.subjects[p]
  if(!old||state===12&&f.state[p][i-1]!==12)old={ext:targets,x:f.x[p][i],y:F(f.y[p][i]+a[0])}
  const hold=data.hold.includes(state)||data.specialHold[cid]?.includes(state)||
    state===221&&cid===4||state===241&&f.cid.some((arr,q)=>arr[i]===4&&f.state[q][i]===221)
  // A held fighter camera keeps its target, but Camera_800293E0 still
  // smooths the extents independently of the fighter's callback.
  const target=hold?(old.target||targets):targets
  const ext=target.map((v,k)=>F(old.ext[k]+clip(v-old.ext[k],-.5,.5)))
  let x=hold?old.x:f.x[p][i],y=hold?old.y:F(f.y[p][i]+a[0])
  if(state>=4&&state<=10){x=F(F(x*F(165.93487548828125))/F(203.19488525390625));y=F(F(250+s.y)+F(203.19488525390625))}
  if(state===12){
   // fn_8016719C + ftCo_800D4FF4: Corneria has one rebirth point and
   // unk8C.b5 keeps its destination fixed at creation. Repeated external
   // placements can move the fighter during Rebirth, not its camera target.
   const dest=old.rebirth||[f.x[p][i],F(F(250+c.previousStage.y)+DATA.camera.rebirth[1])]
   x=dest[0];y=F(dest[1]+a[0]);old.rebirth=dest
  }
  const subject={x,y,ext,target,vertical:[a[3],a[4]],...(state===12?{rebirth:old.rebirth}:{})}
  c.subjects[p]=subject
  if(state!==11)subjects.push(subject)
 }
 const weight=([0,1.5,1.32,1.16,1][subjects.length]??1)*g.track
 let minx=Infinity,maxx=-Infinity,miny=Infinity,maxy=-Infinity
 for(const a of subjects){
  const x=clip(a.x,left,right),y=clip(a.y,bottom,top)
  for(const e of a.ext){const v=clip(F(x+F(weight*e)),left,right);minx=Math.min(minx,v);maxx=Math.max(maxx,v)}
  for(const e of a.vertical){const v=clip(F(y+F(weight*e)),bottom,top);miny=Math.min(miny,v);maxy=Math.max(maxy,v)}
 }
 if(!subjects.length){minx=s.x-40;maxx=s.x+40;miny=250+s.y-40;maxy=250+s.y+40}
 miny=F(miny-F(F(390*clip(F((Math.abs(c.pos[2])-80)/4920),0,1))+10))
 c.fov=F(c.fov+F(F(data.fov-c.fov)*F(.1)))
 const dx=F(maxx-minx),dy=F(maxy-miny),spread=Math.max(dx,dy),bias=F(.0682*clip((spread-60)/60,0,1))
 const base=F(F(F(miny-F(250+s.y))+F(maxy-F(250+s.y)))*F(.5-bias)+F(250+s.y))
 const pitch=F(F(clip(-F(F(base-30)*g.pitch),-7,5)*rad)+F(g.pan*rad)),half=F(F(.5)*F(c.fov*rad)),tu=F(Math.tan(F(half+pitch))),td=F(Math.tan(F(half-pitch)))
 const disty=F(dy/F(tu+td)),yoff=F(disty*F(Math.tan(pitch))),iy=F(yoff+F(maxy-F(disty*tu)))
 const center=F(F(minx+maxx)*F(.5)),yaw=F(clip(-F(F(center-s.x)*g.yaw),-17.5,17.5)*rad),tr=F(aspect*F(Math.tan(F(half-yaw)))),tl=F(aspect*F(Math.tan(F(half+yaw))))
 const distx=F(dx/F(tr+tl)),xoff=F(aspect*F(distx*F(Math.tan(yaw)))),ix=F(F(maxx-F(distx*tr))-xoff)
 const target=[ix,iy,0],pos=[F(ix+xoff),F(iy-yoff),clip(Math.max(distx,disty),g.minDepth,g.maxDepth)]
 const pitch2=Math.atan2(iy-pos[1],pos[2]),yaw2=Math.atan2(pos[0]-ix,pos[2]),h=F(.5*F(data.fov*rad))
 const points=[[1,1],[1,-1],[-1,1],[-1,-1]].map(([a,b])=>{
  let v=rot(rot([0,0,-1],1,h*a),2,h*b);v[0]=F(v[0]*aspect)
  const len=Math.hypot(...v);v=v.map(x=>F(x/len));v=rot(rot(v,1,pitch2),2,yaw2)
  const scale=F(-pos[2]/v[2]);return [F(F(v[0]*scale)+pos[0]),F(F(v[1]*scale)+pos[1])]
 })
 const lo=Math.max(0,left-points[0][0],left-points[2][0]),ro=Math.min(0,right-points[1][0],right-points[3][0]),to=Math.min(0,top-points[0][1],top-points[1][1]),bo=Math.max(0,bottom-points[2][1],bottom-points[3][1])
 const cx=lo&&ro?F(.5*F(lo+ro)):lo||ro,cy=to&&bo?F(.5*F(to+bo)):to||bo
 target[0]=F(target[0]+cx);target[1]=F(target[1]+cy);pos[0]=F(pos[0]+cx);pos[1]=F(pos[1]+cy)
 c.target=target;c.targetPos=pos
 const smooth=F(F((.05+.05*clip((spread-120)/780,0,1))*g.smooth))
 // Retail 80029BAC/80029BB8 use fmadds: round the subtraction, then
 // multiply/add with one final single-precision rounding.
 c.interest=c.interest.map((v,k)=>k===2?0:F(v+F(target[k]-v)*smooth))
 c.pos=c.pos.map((v,k)=>F(v+F(pos[k]-v)*F(.15*g.smooth)))
 return c
}
export function cameraHistory(b,observe){
 if(!DATA?.camera)return null
 const s=initialState(),c={interest:[0,10,0],pos:[0,F(40.241425),F(300.241)],fov:30,subjects:[],previousStage:{x:0,y:0}},result=[]
 // Ordinary VS calls Camera_8002F3AC before the first recorded frame.
 cameraStep(c,b,0,s);c.interest=c.target.slice();c.pos=c.targetPos.slice()
 for(let i=0;i<b.meta.n;i++){
  // Nonstandard camera subjects (items) and item camera modes require
  // their own subject lifecycle; leave their subsequent trigger unknown.
  result[i]=c.unknown?null:c.interest[0]
  if((b.items||[]).some(t=>t.f===i&&(t.t<43||DATA.camera.itemSubjects.includes(t.t))))c.unknown=true
  if(i>=84){const r=frameCursor(b,i);if(!r)break;drift(s,()=>r.float())}
  cameraStep(c,b,i,s)
  observe?.(i,c,s)
  c.previousStage={x:s.x,y:s.y}
 }
 return result
}

function copy(s){return {...s,background:{...s.background},cannon:{...s.cannon},plane:s.plane?{...s.plane}:null}}

// grMaterial's two Yaku items retain their own position during item hitlag.
// Use those recorded positions, with the authored capsule/Z transforms, for
// it_802703E8's swept test. The original initial states (left 0, right 2)
// identify the cannons even when Slippi's item iteration order is reversed.
// The compact stage table carries certified direct-attack poses; it does not
// depend on unrelated fighter packs having happened to load in the viewer.
export function cannonContacts(b,material){
 const data=DATA.cannonDamage,f=fighterFrames(b),rows=[],active=[],previous=f.x.map(()=>[]),epochs=f.x.map(()=>0),held=f.x.map(()=>0)
 if(!data)return null
 let known=true
 for(let i=0;i<b.meta.n;i++){
  const contacts=[],keys=[]
  for(let p=0;p<f.x.length;p++){
   const state=f.state[p][i],cid=f.cid[p][i],age=f.age[p][i],x=f.x[p][i],y=f.y[p][i]
   const reset=!i||state!==f.state[p][i-1]||age<f.age[p][i-1]||cid!==f.cid[p][i-1]
   if(reset){epochs[p]++;held[p]=0;previous[p]=[]}
   if(state==null||!mayDamageStage(state)){previous[p]=[];continue}
   const move=data.hitboxes[cid]?.[state]
   if(!move){known=false;previous[p]=[];continue}
   if(move.charge&&!reset&&age>0&&age===f.age[p][i-1]&&age<Math.min(...Object.keys(move.frames).map(Number)))held[p]=Math.min(move.charge[1],held[p]+1)
   const hits=attackSpheres(cid,state,age,x,y,f.dir[p][i],data.hitboxes,2)
   if(!hits){known=false;previous[p]=[];continue}
   for(const group of new Set(hits.map(h=>h.group)))for(let c=0;c<2;c++)keys.push(`${p}:${epochs[p]}:${c}:${group}`)
   for(let c=0;c<2;c++){
    const t=material[c],z=data.zByInitialState[t.s[0]]
    if(z==null){known=false;continue}
    if(i>=t.x.length)continue // incomplete final replay row is rejected by its witnesses
    const cap={a:[F(t.x[i]+data.a[0]),F(t.y[i]+data.a[1]),F(z+data.a[2])],b:[F(t.x[i]+data.b[0]),F(t.y[i]+data.b[1]),F(z+data.b[2])],radius:data.radius}
    for(const h of hits){
     if(!hitCapsule(h,previous[p].find(o=>o.id===h.id&&o.group===h.group),cap))continue
     contacts.push({key:`${p}:${epochs[p]}:${c}:${h.group}`,part:c,damage:materialDamage(h,move,held[p]),direction:t.x[i]>x?-1:1})
    }
   }
   previous[p]=hits
  }
  rows.push(contacts);active.push(keys)
 }
 // Stage lasers have NULL owners and cannot damage the NULL-owned material
 // (it_802706D0). Certified direct moves have no reflectors or articles.
 // Any other item/history keeps the previous shot-witness fail-closed path.
 if((b.items||[]).some(t=>t.t!==160&&(![234,235].includes(t.t)||t.o!==-1)))known=false
 return {rows,active,known}
}

export function applyCannonContacts(previous,contacts,active){
 const s={...previous,hitKeys:(previous.hitKeys||[]).filter(k=>active.includes(k)),directions:[...(previous.directions||[0,0])],pending:0}
 if(s.phase!==0&&s.phase!==3)return s
 for(const h of contacts){
  if(s.hitKeys.includes(h.key))continue
  s.hitKeys.push(h.key);s.pending=F(s.pending+h.damage);s.directions[h.part]=h.direction
 }
 return s
}

// Damage amounts are absent from Slippi's item records. A later Great Fox
// shot nevertheless proves that the irreversible 200-damage transition did
// not occur earlier. After that witness, Wait has no fighter hitboxes. The
// two unreflected stage lasers and the material have NULL owners and default
// friendly-item flags, so it_802706D0 excludes their mutual collisions.
// Require Wait throughout a laser's lifetime to exclude an earlier reflect;
// the bundle's single initial owner field cannot prove that by itself.
export function cannonDamageLimit(b,material) {
  const frames=fighterFrames(b)
  let hit=Infinity
  for(const t of material){const i=t.d.findIndex(d=>d!==0);if(i>=0)hit=Math.min(hit,t.f+i)}
  if(!Number.isFinite(hit))return Infinity
  const items=b.items||[],shots=items.filter(t=>t.t===235)
  const alive=Math.max(hit,...shots.map(t=>t.f))
  const idle=[0]
  for(let i=0;i<b.meta.n;i++)idle.push(idle[i]+Number(!frames.state.every(a=>a[i]==null||a[i]===14)))
  for(let i=alive;i<b.meta.n-1;i++){
    if(idle[i+1]!==idle[i])return i+1
    for(const t of items){
      if(i<t.f||i>=t.f+t.x.length||t.t===160)continue
      if(![234,235].includes(t.t)||t.o!==-1||idle[i+1]!==idle[t.f])return i+1
    }
  }
  return Infinity
}

// Slippi's item record holds this many items per frame; further items exist
// in game but go unrecorded while it is full.
const SLIPPI_ITEM_LIMIT=15

function buildEntry(b){
  const material=(b.items||[]).filter(t=>t.t===160&&t.f===0)
  if(material.length!==2||material.some(t=>!Array.isArray(t.s)||!Array.isArray(t.d)))return null
  const lasers=new Set((b.items||[]).filter(t=>t.t===235).map(t=>t.f))
  // frames whose item record is full (Slippi's 15-item limit)
  const count=new Uint8Array(b.meta.n)
  for(const t of b.items||[])for(let k=0;k<t.x.length&&t.f+k<b.meta.n;k++)count[t.f+k]++
  const full=new Set();count.forEach((n,k)=>{if(n>=SLIPPI_ITEM_LIMIT)full.add(k)})
  // Material facing begins at zero. ityaku's damage callback stores the
  // incoming direction before fn_801E12D4 accumulates damage. Its first
  // nonzero value is an authoritative hit; geometry can change next pass.
  const damaged=cannonDamageLimit(b,material)
  const s={...initialState(),background:initialBackground(),cannon:initialCannon()}
  return {states:[s],next:84,checkpoints:new Map([[84,[copy(s)]]]),result:null,material,lasers,full,damaged,lastOnGun:lastOnGun(b,material),
    camera:cameraHistory(b),contacts:cannonContacts(b,material)}
}

// Destruction leaves no item trace, but it is irreversible, so a fighter
// standing on the gun proves it was there until then. The last frame a
// grounded fighter stands on lines 27-29, placed by the gun item's witness of
// the ship (shipWitness), bounds how long drift-only frames may draw the gun.
export function lastOnGun(b,material){
  const f=fighterFrames(b),gun=[27,28,29].map(id=>{const [a,c]=DATA.lines[id];return [DATA.vertices[a],DATA.vertices[c]]})
  let last=-1
  for(let i=0;i<b.meta.n;i++){
    const w=shipWitness(material,i)
    if(!w)continue
    for(let p=0;p<f.x.length;p++){
      const x=f.x[p][i],y=f.y[p][i]
      if(f.air[p][i]||!(f.state[p][i]>=14)||!Number.isFinite(x))continue
      for(const [a,c] of gun){
        const x0=a[0]*.54+w.x,x1=c[0]*.54+w.x,y0=a[1]*.54+250+w.y,y1=c[1]*.54+250+w.y
        if(x<Math.min(x0,x1)||x>Math.max(x0,x1))continue
        if(Math.abs(y0+(y1-y0)*(x-x0)/(x1-x0)-y)<.05){last=i;break}
      }
    }
  }
  return last
}

// The ship's drift is the first draw on the frame's cursor (advance), so it
// stays known from the recorded seed when the draws after it do not.
export function driftOnly(previous,seed){
  const s={...previous,frame:previous.frame+1,plane:null,driftOnly:true}
  const rng=random(seed)
  drift(s,()=>rng.float())
  return s
}

// Every candidate drift, each at every cursor offset that lands on the gun
// item's witness (none is dropped before a witness rules it out).
export function driftOnlyStep(states,seed,w,gunCertain){
  const out=[]
  for(const prev of distinctDrift(states))for(const k of cursorOffsets(prev,seed,w)){
    const s=driftOnly(prev,advanceSeed(seed,k))
    s.gunCertain=gunCertain
    if(onShip(s,w))out.push(s)
  }
  return distinctDrift(out)
}

// One candidate per distinct drift state: what drift-only frames carry on.
const DRIFT=['x','y','vx','vy','ax','ay','remaining']
function distinctDrift(states){
  const out=new Map()
  for(const s of states)out.set(JSON.stringify(DRIFT.map(k=>s[k])),s)
  return [...out.values()]
}

// The left gun's yaku item (material[0]) rides ship joint 2, so the replay
// records where the ship really is on every frame: its position is the
// ship's drift plus (-108.378, 250-9.828). Measured on every in-sync frame of
// the owner's 43 Corneria games. While the item is in hitlag its position
// freezes (it_2E6A skips its physics); a frozen row is no witness.
const GUN_X=-108.37808,GUN_Y=F(F(-18.200002670288086)*F(.54))
export function shipWitness(material,i){
  const t=material?.[0],x=t?.x?.[i],y=t?.y?.[i]
  if(!Number.isFinite(x)||!Number.isFinite(y))return null
  if(i>0&&t.x[i-1]===x&&t.y[i-1]===y)return null
  return {x:x-GUN_X,y:y-GUN_Y-250}
}
const onShip=(s,w)=>!w||(Math.abs(s.x-w.x)<2e-4&&Math.abs(s.y-w.y)<2e-4)

// Random cursor offsets to try for a candidate this frame. The cursor is the
// last recorded pre-frame seed plus the known input-tail draws (rng.js);
// something it does not model can still draw before the stage (Samus's
// neutral-B entry with a stored charge drew 6 in Game_20251003T223026). The
// drift is the first draw on the cursor, so on a frame where the ship picks a
// new acceleration and the model's cursor misses the recorded ship, the
// offsets whose drift lands on it are the cursors the game can have used.
// Later frames' witnesses keep only the right one.
export function cursorOffsets(previous,seed,w){
  if(!w||previous.remaining>0)return [0]
  const lands=k=>{
    const s={...previous},rng=random(advanceSeed(seed,k))
    drift(s,()=>rng.float())
    return onShip(s,w)
  }
  if(lands(0))return [0]
  const out=[]
  for(let k=1;k<=30;k++){if(lands(k))out.push(k);if(k<=6&&lands(-k))out.push(-k)}
  return out
}

function stepCandidates(b,entry,i){
  const rng=frameCursor(b,i)
  if(!rng)return []
  const w=shipWitness(entry.material,i)
  if(entry.states[0]?.driftOnly||!entry.contacts?.known&&i>=entry.damaged){
    // Slippi records no damage amounts, so from here the cannon may have
    // taken its 200 damage: its draws, and the flyby decisions that follow
    // them on the same cursor, are unknown. The hull is not: keep drifting it,
    // every candidate drift until the gun item's witness tells them apart
    // (once only the drift is known, it stays the only thing known).
    return driftOnlyStep(entry.states,rng.seed,w,i<=entry.lastOnGun)
  }
  const unique=new Map()
  const x=entry.camera[i]
  const kinds=x==null?cameraBackgroundKinds(i-123):[backgroundKind(i-123,x)]
  for(const previous of entry.states)for(const k of cursorOffsets(previous,rng.seed,w))for(const kind of kinds){
    const state=advance(previous,advanceSeed(rng.seed,k),(s,r)=>{
      s.background=advanceBackground(previous.background,kind,r)
      waterDraws(s,r)
      let shot=false
      const cannonY=F(F(250+s.y)+F(F(-18.200002670288086)*F(.54)))
      s.cannon=advanceCannon(previous.cannon,r,{
        damage:previous.cannon.pending||0,
        fighterInRange:fighterFrames(b).y.some(a=>Number.isFinite(a[i-1])&&Math.abs(cannonY-a[i-1])<=10),
        laser(){shot=true},
      })
      // Source-proven zero-draw calls here: grLib_801C9808 BC/C0/E3
      // (EfCoData kind&0x100), Yaku 0/2 scripts, and GreatFox laser creation.
      const state=s.cannon.phase===1?2:0
      // Slippi records at most 15 items a frame. While the record is full a
      // new laser goes unrecorded until a slot frees, and then first appears
      // late (Game_20250923T220430: born 7449, recorded from 7452). So a shot
      // with no record, or a record with no shot, only disproves a candidate
      // when the record had room.
      const recorded=entry.lasers.has(i)
      if(shot&&!recorded&&!entry.full.has(i))return false
      if(!shot&&recorded&&!entry.full.has(i-1))return false
      if(!entry.material.every(t=>t.s[i]===state))return false
      if(entry.contacts?.known){
        s.cannon=applyCannonContacts(s.cannon,entry.contacts.rows[i],entry.contacts.active[i])
        // Incoming directions independently validate accepted hit identity;
        // they never supply a damage amount or a destruction frame.
        if(!entry.material.every((t,c)=>t.d[i]===s.cannon.directions[c]))return false
      }
      return true
    })
    if(state&&onShip(state,w)){
      const key=JSON.stringify([state.background,state.cannon,state.wait,state.type,state.group,state.plane,
        state.x,state.y,state.vx,state.vy,state.ax,state.ay,state.remaining])
      unique.set(key,state)
    }
  }
  // No candidate explaining a frame means the model has lost the game's
  // state, its random cursor included: nothing, not even the drift, is known.
  return [...unique.values()]
}

function consensus(states){
  if(!states.length)return null
  let result=null,key,common=null,split=false
  const seen=new Set()
  for(const s of states){
    // everything geometry() reads: candidates can differ in drift too
    const signature=JSON.stringify([s.type,s.group,s.plane,s.cannon.phase===5,s.x,s.y,s.driftOnly,s.gunCertain])
    if(seen.has(signature))continue
    seen.add(signature)
    const g=geometry(s),k=JSON.stringify(g.lines)
    if(!common){result=g;key=k;common=g.lines}
    else if(k!==key){
      // The candidates disagree (an Arwing's route, the gun): keep the lines
      // they all place, the hull among them, as a partial result. Drifts the
      // witness cannot yet tell apart differ by thousandths of a unit: the
      // same line within .05 units counts as agreement.
      const kept=common.filter(l=>g.lines.some(m=>m[0]===l[0]&&m[1]===l[1]&&[2,3,4,5].every(c=>Math.abs(m[c]-l[c])<.05)))
      if(kept.length!==common.length||g.lines.length!==common.length)split=true
      common=kept
    }
  }
  if(!split)return result
  return common.length?{lines:common,replace:true,complete:false}:null
}

export default function simulate(bundle,idx) {
  if(!DATA)return null
  const m=bundle?.meta,f=bundle?.frames
  if(!supportedFighterHistory(bundle,idx,7)||!f?.seed?.length||
     fighterFrames(bundle).dir?.length!==fighterFrames(bundle).x.length||
     !fighterFrames(bundle).dir.every(a=>a?.length===m.n))return null
  if(idx<84)return geometry(initialState())
  let e=cache.get(bundle)
  if(!e){e=buildEntry(bundle);if(!e)return null;cache.set(bundle,e)}
  if(idx<e.next-1){
    let key=84+Math.floor((idx-84)/512)*512
    while(!e.checkpoints.has(key))key-=512
    e.states=e.checkpoints.get(key).map(copy);e.next=key
  }
  while(e.next<=idx){
    e.states=stepCandidates(bundle,e,e.next)
    e.result=consensus(e.states)
    if((++e.next-84)%512===0)e.checkpoints.set(e.next,e.states.map(copy))
  }
  return e.result?{...e.result,lines:e.result.lines.map(l=>l.slice())}:null
}

registerStageSimData(7, value => {
  DATA = value
})
