import { COLLISION_TIMING } from './collisionTiming.js'
export const { collisionLag } = COLLISION_TIMING[6]
import { registerStageSimData, fighterDataFor, fighterDataReady, fighterFrames, itemDataReady, supportedFighterHistory } from '../stageData.js'
import { attackSpheres, itemAttackHistory,itemEntryHits, smashChargeHistory, materialDamage, turnipFaceAtSpawn, knownTurnipDamage,nessYoyoHistory,luigiMissileHistory,skullBashHistory,thunderHitHistory,airCatchHistory,chainHistory,missingProjectileBirths,unrecordedJoltHistory,unrecordedNeedleHistory } from './stage16.js'
import { sampleTrack } from './stage13.js'
import { frameCursor, setupCursor } from './rng.js'
let DATA

// grZebes_801D99E0 moves the acid model, its hit test and lighting. It does
// not move a MapJoint or supply a walkable acid surface. The five columns
// (26..30) belong to the destructible connector, not to the acid.
//
// The undamaged connector is a 16-bubble physical system, warmed for 100
// iterations by grZebes_801DC9DC. Only its numeric integration is approximated
// by JS float32 operations; no captured settling trajectory is used. Damage
// callbacks are reconstructed from authored swept hitboxes and replay poses.
// Item/article commands share the swept material collision path.
const cache = new WeakMap()
const F = Math.fround
export { nextSeed as stepSeed } from './rng.js'
// The undamaged collision path has no RNG dependency: random decorative
// bubble animations do not change the physical positions/sizes, and 16 active
// bubbles exceed the <15 replenishment threshold in grZebes_801DC408.

const P = Object.freeze({ radius:F(3.5), near:4, far:6, attract:F(.02),
  force:F(.4), gravity:F(.1), velocity:F(1.2) })
const INITIAL_POINTS = [[7.59,2.5],[24.05,2.2],[8.2,-4.55],[24.1,-4.6]].map(p=>p.map(F))
// GrZe.dat group 6 bone 14 has an authored +0.000002 X translation. The
// callback updates the left bounds AFTER each integration, not during warmup.
const LEFT_TRANSLATION = F(.000002)
const LIVE_POINTS = INITIAL_POINTS.map((p,i)=>[i===0||i===2?F(p[0]+LEFT_TRANSLATION):p[0],p[1]])

export function initialConnector() {
  const [,right,a,b]=INITIAL_POINTS,scales=[1,1.1,1,1.2,1.1,1,1].map(F),bubbles=[]
  const dx=F(b[0]-a[0]),dy=F(b[1]-a[1])
  for(let i=0;i<7;i++)bubbles.push({x:F(F(dx/6)*i+a[0]),y:F(F(dy/6)*i+a[1]),size:scales[i]})
  const xbase=F(a[0]+P.radius),xrange=F(F(right[0]-a[0])-F(2*P.radius)),yrange=F(right[1]-a[1])
  for(const [x,y,size] of [[.5,.5,1],[.2,.8,1.2],[.8,.2,1.1],[.8,.8,1.1],[.5,.2,1.2],[.5,.9,1.3],[.5,.9,1.3],[.6,1,1.1],[.2,1,1]])
    bubbles.push({x:F(x*xrange+xbase),y:F(y*yrange+a[1]),size:F(size)})
  let state={bubbles,live:false}
  for(let i=0;i<100;i++)state=advanceConnector(state,false)
  return state
}

// grZebes_801DB3CC: spring neighbors update sequentially, pair impulses
// accumulate separately, then bounds and velocity limits are applied.
export function advanceConnector(state, live = true, rng = null) {
  const s=state.bubbles.map(b=>({...b,vx:0,vy:-P.gravity}))
  const points=state.points || (state.live?LIVE_POINTS:INITIAL_POINTS)
  for(let i=1;i<6;i++){
    if(![1,4].includes(s[i].active??1))continue
    const b=s[i];let fx=0,fy=0,neighbors=0
    for(const other of [s[i-1],s[i+1]]){
      if(other.active===0)continue
      neighbors++
      const dx=F(other.x-b.x),dy=F(other.y-b.y),dist=F(Math.sqrt(F(dx*dx+F(dy*dy))))
      if(dist>P.radius){const push=Math.min(P.force,F(dist-P.radius));fx=F(F(dx/dist)*push+fx);fy=F(F(dy/dist)*push+fy)}
    }
    b.x=F(b.x+fx);b.y=F(b.y+fy)
    if((b.active??1)!==4 && neighbors!==2){
      if(!rng)throw new TypeError('Connector collapse needs the ordered frame RNG cursor')
      b.active=3;b.timer=10+rng.int(60)
    }
  }
  for(let i=0;i<s.length-1;i++)for(let j=i+1;j<s.length;j++){
    if(s[i].active===0||s[j].active===0)continue
    const a=s[i],b=s[j];let dx=F(b.x-a.x),dy=F(b.y-a.y),dist=F(Math.sqrt(F(dx*dx+F(dy*dy))))
    const avg=F(a.size+b.size),rad=F(F(P.radius/2)*avg),near=F(P.near/2*avg),far=F(P.far/2*avg)
    if(dist<.001){dy=F(.001);dx=0;dist=F(.001)}
    if(dist<rad){const strength=F(F((F(rad/dist)-1)/2)*.9)
      if(i>=7){a.vx=F(a.vx+F(-dx*strength));a.vy=F(a.vy+Math.max(0,F(-dy*strength)))}
      if(j>=7){b.vx=F(b.vx+F(dx*strength));b.vy=F(b.vy+Math.max(0,F(dy*strength)))}
    }else if(dist>=near&&dist<far){const strength=F(P.attract/dist)
      if(i>=7){a.vx=F(a.vx+F(dx*strength));a.vy=F(a.vy+F(dy*strength))}
      if(j>=7){b.vx=F(b.vx+F(-dx*strength));b.vy=F(b.vy+F(-dy*strength))}
    }
  }
  for(let i=0;i<s.length;i++){
    const b=s[i]
    if(b.active===0)continue
    if(i===0||i===6){[b.x,b.y]=points[i===0?2:3];b.vx=b.vy=0;continue}
    let x=F(b.x+b.vx),y=F(b.y+b.vy)
    if(y<points[0][1]&&x<points[0][0]){if(b.y>=points[0][1])y=points[0][1];else if(b.x>=points[0][0])x=points[0][0]}
    if(y<points[1][1]&&x>points[1][0]){if(b.y>=points[1][1])y=points[1][1];else if(b.x<=points[1][0])x=points[1][0]}
    b.x=x;b.y=y;b.vx=Math.max(-P.velocity,Math.min(P.velocity,b.vx));b.vy=Math.max(-P.velocity,Math.min(P.velocity,b.vy))
  }
  return {...state,bubbles:s,live}
}

// fn_801DAC90 is a late item-damage callback. Removal and nearest-neighbor
// replacement happen at the next priority-4 pass, before bubble integration.
export function popConnectorBubble(state, rng = null, marked = -1) {
  const bubbles=state.bubbles.map(b=>({...b}))
  const target=marked>=0?marked:bubbles.findIndex((b,i)=>i!==0&&i!==6&&(b.active??1)===1)
  if(target<0)return state
  const popped=bubbles[target]
  popped.active=0
  let collapse=false
  if(target<7){
    let closest=-1,distance=64
    for(let i=7;i<bubbles.length;i++){
      const b=bubbles[i]
      if((b.active??1)!==1)continue
      const dx=F(b.x-popped.x),dy=F(b.y-popped.y)
      const squared=F(F(dx*dx)+F(dy*dy))
      if(squared<distance){closest=i;distance=squared}
    }
    if(closest<0){
      if(!rng)return null
      collapse=true
      for(let i=7;i<bubbles.length;i++)if((bubbles[i].active??1)===1){bubbles[i].active=3;bubbles[i].timer=10+rng.int(60)}
    }else{
      popped.active=1;popped.size=bubbles[closest].size;popped.target=bubbles[closest].target??popped.size;popped.decoration=bubbles[closest].decoration
      bubbles[closest].active=0
    }
  }
  return {...state,bubbles,delay:120,collapse:state.collapse||collapse}
}

// grZebes_801D881C projects the tops to six vertices and limits the slope.
export function connectorColumns(state) {
  const points=state.points || (state.live?LIVE_POINTS:INITIAL_POINTS)
  const width=F(F(points[1][0]-points[0][0])/5),xs=Array(6),ys=Array(6).fill(-9999)
  for(const b of state.bubbles){
    if((b.active??1)!==1)continue
    const offset=F(b.x-points[0][0]),top=F(1.8*b.size+b.y)
    for(const v of [F(F(offset-.9)/width),F(F(.9+offset)/width)]){
      const i=Math.max(0,Math.min(5,Math.trunc(.5+v)))
      xs[i]=F(i*width+points[0][0]);ys[i]=Math.max(top,ys[i])
    }
  }
  const shift=state.shifts||[[0,0],[0,0]]
  xs[0]=F(F(F(8.589)+LEFT_TRANSLATION)+shift[0][0]);ys[0]=F(F(1.215)+shift[0][1]);xs[5]=F(F(23.151)+shift[1][0]);ys[5]=F(F(1.207)+shift[1][1])
  for(let i=0;i<5;i++){if(i!==0)ys[i]=Math.max(ys[i],F(ys[i+1]-width));ys[i+1]=Math.max(ys[i+1],F(ys[i]-width))}
  return xs.map((x,i)=>[x,ys[i]])
}

// grZebes_801DA528. Damage is a material callback input, not floor contact.
// Animation completion must refer to this support's requested animation.
// The default adapter supplies replay-reconstructed callbacks below.
export function advanceSupport(state, damage = 0, impactVelocity = null,
  { animationFinished = false, rng = null } = {}) {
  const s = { ...state }
  s.damage = F(s.damage + damage)
  if (impactVelocity != null) s.velocity = F(impactVelocity)
  s.nextPhase ??= s.phase
  if (s.phase !== s.nextPhase) {
    s.phase = s.nextPhase
    if (s.phase === 0) s.timer = s.offset = s.velocity = 0
    else if (s.phase === 2) {
      if (!rng) throw new TypeError('Support restoration needs the ordered frame RNG cursor')
      s.timer = Math.trunc(F(600 * rng.float() + 1200))
    } else if (s.phase === 3) s.damage = 0
  }
  if (s.phase === 1) { if (animationFinished) s.nextPhase = 2; return s }
  if (s.phase === 2) { if (--s.timer < 0) s.nextPhase = 3; return s }
  if (s.phase === 3) { if (animationFinished) s.nextPhase = 0; return s }
  if (s.timer++ > 20) { s.timer = 0; s.damage = Math.max(0, F(s.damage - 1)) }
  if (s.offset > F(.15)) s.velocity = F(s.velocity - F(.1))
  else if (s.offset < -F(.15)) s.velocity = F(s.velocity + F(.1))
  s.velocity = Math.max(-2, Math.min(2, F(s.velocity * F(1 - F(.1)))))
  s.offset = Math.max(-6, Math.min(6, F(s.offset + s.velocity)))
  if (Math.abs(s.offset) < F(.15) && Math.abs(s.velocity) < F(.15)) s.offset = s.velocity = 0
  if (s.damage > 30) s.nextPhase = 1
  return s
}

export function mayDamageStage(action) {
  // Includes attacks, throws and character-specific specials. Conservative
  // invalidation is preferable to silently reconstructing unrecorded hits.
  // DownAttackU/D, CatchAttack, and CliffAttackSlow/Quick
  // are separate common action IDs. In particular, pass6 includes action 187
  // near the connector; omitting getup attacks could accept a damaged history.
  return (action >= 44 && action <= 74) || (action >= 219 && action <= 232) ||
    [187, 195, 217, 256, 257].includes(action) || action >= 341
}

export function connectorCapsule(state){
 const bs=state.bubbles.filter((b,i)=>i!==0&&i!==6&&(b.active??1)===1)
 if(!bs.length)return null
 if(bs.length===1){const b=bs[0];return{a:[b.x,b.y,0],b:[b.x,b.y,0],radius:F(2*b.size)}}
 let a,b,max=-1,largest
 for(let i=0;i<bs.length;i++)for(let j=i+1;j<bs.length;j++){
  const dx=F(bs[i].x-bs[j].x),dy=F(bs[i].y-bs[j].y),d=F(dx*dx+F(dy*dy))
  if(d>max){max=d;a=[bs[i].x,bs[i].y,0];b=[bs[j].x,bs[j].y,0];largest=bs[i].size>bs[j].size?bs[i]:bs[j]}
 }
 if(max<.0001)return{a,b:a.slice(),radius:F(2*largest.size)}
 let dx=F(b[0]-a[0]),dy=F(b[1]-a[1]),width=1,inv=F(1/F(dx*dx+F(dy*dy)))
 for(const v of bs){
  const ex=F(v.x-a[0]),ey=F(v.y-a[1]);let t=F(inv*F(dx*ex+F(dy*ey))),distance
  if(t<0)distance=F(ex*ex+F(ey*ey))
  else if(t>1){const x=F(v.x-b[0]),y=F(v.y-b[1]);distance=F(x*x+F(y*y))}
  else{const x=F(F(dx*t+a[0])-v.x),y=F(F(dy*t+a[1])-v.y);distance=F(x*x+F(y*y))}
  distance=F(Math.sqrt(distance))
  if(F(2*v.size+distance)>width){
   const near=t<.5?a:b,far=t<.5?b:a
   let x=F(v.x-near[0]),y=F(v.y-near[1]);t=F(Math.sqrt(F(F(x*x)+F(y*y))))
   const newWidth=F(.5*(2*v.size+F(t+width)))
   if(t>.001){const ratio=F(F(newWidth-width)/t);near[0]=F(ratio*F(v.x-near[0])+near[0]);near[1]=F(ratio*F(v.y-near[1])+near[1])}
   x=F(near[0]-far[0]);y=F(near[1]-far[1]);t=F(F(newWidth-width)/F(Math.sqrt(F(x*x+F(y*y)))))
   width=newWidth;far[0]=F(x*t+far[0]);far[1]=F(y*t+far[1]);dx=F(b[0]-a[0]);dy=F(b[1]-a[1]);inv=F(1/F(dx*dx+F(dy*dy)))
  }
 }
 return {a,b,radius:width}
}
const dot=(a,b)=>a.reduce((v,x,i)=>v+x*b[i],0),sub=(a,b)=>a.map((x,i)=>x-b[i]),clamp=x=>Math.max(0,Math.min(1,x))
export function hitCapsule(h,prev,c){
 const aa=prev?[prev.x,prev.y,prev.z]:[h.x,h.y,h.z],ab=[h.x,h.y,h.z]
 const d1=sub(ab,aa),d2=sub(c.b,c.a),r=sub(aa,c.a),a=dot(d1,d1),e=dot(d2,d2),f=dot(d2,r)
 let s=0,t=0
 if(a<1e-12&&e<1e-12)return dot(r,r)<=(h.radius+c.radius)**2
 if(a<1e-12)t=clamp(f/e)
 else{const cc=dot(d1,r);if(e<1e-12)s=clamp(-cc/a);else{const bb=dot(d1,d2),den=a*e-bb*bb;s=den?clamp((bb*f-cc*e)/den):0;t=(bb*s+f)/e;if(t<0){t=0;s=clamp(-cc/a)}else if(t>1){t=1;s=clamp((bb-cc)/a)}}}
 const delta=r.map((x,i)=>x+s*d1[i]-t*d2[i]);return dot(delta,delta)<=(h.radius+c.radius)**2
}
const initialSupport = () => ({phase:0,nextPhase:0,timer:0,damage:0,offset:0,velocity:0,animation:1,age:0,platformAnimation:0,platformAge:0})
const track = (group,anim,bone,kind,age,fallback=0) => {
  const keys=DATA.models[group].animations[anim]?.tracks[bone]?.find(t=>t[0]===kind)?.[1]
  return keys?F(sampleTrack(keys,age)):fallback
}
// Requested support/plate animations first evaluate in the NEXT priority-1 pass.
function supportTick(old,rng) {
  let s={...old}
  if(s.request){s.animation=s.request[0];s.age=s.request[1];s.request=null}else s.age++
  if(s.platformRequest){s.platformAnimation=s.platformRequest[0];s.platformAge=s.platformRequest[1];s.platformRequest=null}else s.platformAge++
  const finished=s.age>=DATA.models[6].animations[s.animation].end && !(s.phase!==s.nextPhase && (s.nextPhase===0||s.nextPhase===3))
  const entering=s.phase!==s.nextPhase,next=s.nextPhase
  s=advanceSupport(s,0,null,{animationFinished:finished,rng})
  if(entering){
    if(next===0)s.request=[1,0]
    if(next===1)s.platformRequest=[1,30]
    if(next===3){s.request=[2,0];s.platformRequest=[2,0]}
  }
  if(s.phase===0)s.request=[1,Math.min(30,s.damage)]
  return s
}

// The yaku item copies the attachment's WORLD center and LOCAL scale/rotation.
// The support joint's offset is set at ground priority 4 after animation.
function supportCapsule(s,side,shift=[0,0]) {
  if(s.phase!==0)return null
  const g=side?7:6,root=side?13:28,parent=root+1,bone=root+2
  const nodes=DATA.models[g].nodes,a=s.animation,t=s.age
  const ox=F(nodes[root][7]+(side?0:LEFT_TRANSLATION)+shift[0]),oy=F(nodes[root][8]+shift[1])
  const px=track(g,a,parent,5,t,nodes[parent][7]),py=track(g,a,parent,6,t,nodes[parent][8])
  const angle=track(g,a,parent,3,t),sy=track(g,a,parent,9,t,1),sx=track(g,a,parent,8,t,1)
  const x=F(nodes[bone][7]+s.offset),y=track(g,a,bone,6,t,nodes[bone][8])
  const cx=F(ox+F(nodes[root][4]*F(px+F(Math.cos(angle)*F(x*sx)-Math.sin(angle)*F(y*sy)))))
  const cy=F(oy+F(nodes[root][5]*F(py+F(Math.sin(angle)*F(x*sx)+Math.cos(angle)*F(y*sy)))))
  const half=F((side?5:7)*track(g,a,bone,9,t,1)),radius=side?2:3
  return {a:[cx,F(cy-half),0],b:[cx,F(cy+half),0],radius}
}

function stageLines(connector,supports) {
  const shifts=connectorShifts(connector)
  const lines=DATA.lines.map(l=>{const side=l[0]>=1&&l[0]<=3||l[0]>=14&&l[0]<=17||l[0]>=21&&l[0]<=25?1:0;if(l[0]===4||shifts[side].every(v=>v===0))return l;const r=[...l];if(l[0]!==4){r[2]=F(r[2]+shifts[side][0]);r[3]=F(r[3]+shifts[side][1]);r[4]=F(r[4]+shifts[side][0]);r[5]=F(r[5]+shifts[side][1])}return r})
  for(let side=0;side<2;side++){
    const s=supports[side],g=side?7:6,bone=side?6:21
    const angle=track(g,s.platformAnimation,bone,3,Math.min(s.platformAge,DATA.models[g].animations[s.platformAnimation].end))
    if(angle){
      const node=DATA.models[g].nodes[bone],cx=F(node[7]+(side?0:LEFT_TRANSLATION)+shifts[side][0]),cy=F(node[8]+shifts[side][1]),cos=F(Math.cos(angle)),sin=F(Math.sin(angle))
      for(const id of side?[1,2,3]:[0]){
        const [a,b]=DATA.lineVertices[id],coords=[]
        for(const v of [a,b]){const [x,y]=DATA.local[v];coords.push(F(cos*x+F(-sin*y+cx)),F(sin*x+F(cos*y+cy)))}
        lines[id]=[id,lines[id][1],...coords]
      }
    }
  }
  if(!connector.phase){const vertices=connectorColumns(connector);for(let i=0;i<5;i++)lines.push([26+i,1,...vertices[i],...vertices[i+1]])}
  return lines
}

function replenish(state,rng) {
  const s={...state,bubbles:state.bubbles.map(b=>({...b}))}
  if(s.phase)return s
  if(s.delay){s.delay--;return s}
  if(--s.spawnTimer<0){
    if(s.bubbles.filter(b=>b.active!==0).length<15){
      let at=s.bubbles.findIndex(b=>b.active===0);if(at<0)at=s.bubbles.length
      const p=s.points||LIVE_POINTS,scale=F(.5*rng.float()+1),ry=rng.float(),rx=rng.float()
      s.bubbles[at]={active:1,x:F(F(F(p[1][0]-p[2][0])-7)*rx+F(p[2][0]+P.radius)),y:F(F(p[1][1]-p[2][1])*ry+p[2][1]),size:F(.001),target:scale}
    }
    s.spawnTimer=20+rng.int(30)
  }
  return s
}

// Acid has no walkable MapLine, but its previous-frame height decides how
// generator draws precede subsequent ground objects' random callbacks.
const RIGHT_SPAWNS=[[-11,-25],[1,-17],[-5,-14],[15,4.5]]
const LEFT_SPAWNS=[[-10,-24],[-13,-27],[.5,-10],[4.5,-14.5],[.5,-17.5],[-12,-23],[4,-10.5],[.5,-10], [2,-16],[27.5,17]]
function generatorPrefix(rng,height,shift,pairs) {
  for(let j=0;j<pairs.length;j++){
    const [a,b]=pairs[j].map(y=>F(y+shift))
    if((a>height&&b>height)||(a<height&&b<height))continue
    rng.float() // probability is 1, but the comparison still draws
    if(Math.abs(F(b-a))<=F(.0001))rng.float()
    const effect=j===pairs.length-1?187:186
    for(let n=0;n<DATA.generatorDraws[effect];n++)rng.float()
  }
}
function initialEnvironment(bundle) {
  const rng=setupCursor(bundle)
  if(!rng)return null
  const decoration={timer:3000+rng.int(600),mode:1,age:null}
  const [base,min,max]=DATA.acidLevels[0],timer=base+(max>min?min+rng.int(max-min):max<min?max+rng.int(min-max):max)
  const levels=DATA.acidLevels.filter(e=>e.some(Boolean)),height=F(7*rng.float()+levels.at(-1)[3])
  return {decoration,acid:{phase:0,timer,entry:0,height,target:height,velocity:0,limit:0}}
}
function environmentTail(env,rng,idx) {
  const d=env.decoration,a=env.acid,p=DATA.params
  if(idx===84)a.phase=1
  if(idx>=84){
    if(d.timer>0){
      if(--d.timer===0){d.mode=-d.mode;d.age=0}
    }else if(d.age>=934)d.timer=3000+rng.int(600)
    if(d.age!=null)d.age++
  }
  if(a.phase===1){
    if(--a.timer<0){
      a.target=Math.max(p['90'],Math.min(p['8c'],F(p['94']*rng.float()+DATA.acidLevels[a.entry][3])))
      a.velocity=0;a.phase=2;a.timer=0
      const diff=Math.abs(F(a.target-a.height)),discriminant=F(F(p['98']*p['98'])-F(F(4*diff)/p['9c']))
      a.limit=discriminant<0?999:F(.5*F(p['9c']*F(p['98']-F(Math.sqrt(discriminant)))))
      if(a.limit<0)a.limit=999
    }
  }else if(a.phase===2)a.phase=3
  else if(a.phase===3){
    a.timer++
    const t=F(a.velocity/p['9c']),threshold=F(F(a.velocity*t)-.5*p['9c']*F(t*t)),delta=F(a.target-a.height)
    if(Math.abs(delta)<threshold||Math.abs(delta)<p['9c'])a.phase=4
    else a.velocity=Math.min(a.limit,F(a.velocity+p['9c']))
    a.height=F(a.height+(a.target>a.height?a.velocity:-a.velocity))
  }else if(a.phase===4){
    const delta=F(a.target-a.height);a.velocity=F(a.velocity-p['9c'])
    if(a.velocity<0||Math.abs(delta)<a.velocity){
      a.phase=1;a.velocity=0;a.entry++
      if(a.entry===30||!DATA.acidLevels[a.entry].some(Boolean))a.entry=0
      const [base,min,max]=DATA.acidLevels[a.entry]
      a.timer=base+(max>min?min+rng.int(max-min):max<min?max+rng.int(min-max):max)
    }
    a.height=F(a.height+(a.target>a.height?a.velocity:-a.velocity))
  }
}

export function connectorShifts(s) {
  if(!s.animation)return [[0,0],[0,0]]
  return [6,7].map((g,side)=>[5,6].map(kind=>track(g,s.animation,side?1:14,kind,Math.min(s.animationAge,DATA.models[g].animations[s.animation].end))))
}
function connectorAnimation(previous) {
  const s={...previous,bubbles:previous.bubbles.map(b=>({...b}))}
  if(s.animationRequest){s.animation=s.animationRequest;s.animationAge=0;s.animationRequest=null}
  else if(s.animation)s.animationAge++
  return s
}
// grZebes_801D881C: destruction, 600-tick hold, 15-tick symmetric
// regrowth, then the authored return animation re-enables the connector.
export function connectorPhase(previous,rng) {
  const s={...previous,bubbles:previous.bubbles.map(b=>({...b}))}
  const done=s.animation && s.animationAge>=DATA.models[6].animations[s.animation].end
  if(!s.phase && s.collapse){s.phase=1;s.animationRequest=3;s.collapse=false}
  else if(s.phase===1 && done){s.phase=2;s.timer=Math.trunc(F((DATA.params['4']-DATA.params['0'])*rng.float()+DATA.params['0']))}
  else if(s.phase===2 && --s.timer<0){s.phase=3;s.animationRequest=4;s.growth=0;s.delay=0}
  else if(s.phase===3){
    s.growth++
    if(s.growth%DATA.params['10']===0){
      const at=s.growth/DATA.params['10'],mirror=6-at
      const spawn=(i,neighbor)=>{
        const scale=F(.5*rng.float()+1),b=s.bubbles[i]
        if(b?.active!==0)return
        const p=s.bubbles[neighbor]
        s.bubbles[i]={active:4,x:p.x,y:p.y,size:scale,target:scale}
      }
      if(at<mirror)spawn(at,at-1)
      if(at<=mirror)spawn(mirror,mirror+1)
    }
    if(done){s.phase=0;for(const b of s.bubbles)if(b.active===4)b.active=1}
  }
  return s
}

function build(bundle) {
  const frames=fighterFrames(bundle),n=bundle.meta.n??frames.seed[0].length,rows=[],events=[]
  let connector={...initialConnector(),phase:0,delay:0,spawnTimer:0,decorationTimer:0},supports=[initialSupport(),initialSupport()]
  const last=[],previous=[],charged=smashChargeHistory(frames),hits=frames.state.map(()=>new Set())
  // With items off, one needle user and no foreign article family, every
  // attack can be reconstructed even when inert/held needles fill Slippi's
  // cap. Inert needles have no support/connector or restoration callback.
  const needleOnly=bundle.meta.item_frequency===-1&&frames.x.length===1&&frames.cid[0].every(cid=>[4,7].includes(cid))&&
    frames.state[0].every((state,i)=>state<341||(frames.cid[0][i]===7?state>=341&&state<=348:state>=467&&state<=474))&&
    // Kind52 is the discarded copy star (it_2ADA): no attack commands.
    (bundle.items||[]).every(t=>[160,52,79,80,152,153].includes(t.t))&&
    frames.state[0].every((state,i)=>(fighterDataFor(frames.cid[0][i])?.hitboxes?.[state]?.articleSpawns||[]).every(s=>[79,80,152,153].includes(s.kind)))
  const itemRows=itemAttackHistory(bundle,{allowNeedleOmissions:needleOnly}),itemHits=new Map(),turnipFaces=new Map(),missingBirths=missingProjectileBirths(bundle,{includeNeedles:!needleOnly})
  const needleStep=needleOnly?unrecordedNeedleHistory(bundle,{materialOnly:true}):null
  const missingJolts=unrecordedJoltHistory(bundle,{missingOnly:true})
  const yoyo=nessYoyoHistory(bundle),luigi=luigiMissileHistory(bundle),skull=skullBashHistory(bundle),thunder=thunderHitHistory(bundle),tether=airCatchHistory(bundle),chain=chainHistory(bundle)
  const environment=initialEnvironment(bundle)
  let unavailable=environment?Infinity:0
  for(let i=0;i<n&&i<unavailable;i++){
    connector=connectorAnimation(connector)
    const shifts=connectorShifts(connector)
    const rng=frameCursor(bundle,i)
    if(!rng){unavailable=i;break}
    // QueueProc orders equal-priority callbacks by GObj creation order,
    // even when the child registers its proc before the parent's initializer
    // returns. Group 6 (left) therefore precedes its nested group 7 (right).
    supports[0]=supportTick(supports[0],rng)
    for(const b of connector.bubbles)if(b.decoration!=null)b.decoration--
    if(connector.decorationTimer--<0){
      const eligible=connector.bubbles.flatMap((b,j)=>j!==0&&j!==6&&(b.active??1)===1&&b.decoration==null?[j]:[])
      if(eligible.length)connector.bubbles[eligible[rng.int(eligible.length)]].decoration=DATA.bubbleAnimationEnd
      connector.decorationTimer=Math.trunc(F(100*rng.float()+200))
    }
    for(let at=0;at<connector.bubbles.length;at++){
      const b=connector.bubbles[at]
      if(b.active===0)continue
      if(b.target!=null)b.size=F(b.size+Math.max(-F(.05),Math.min(F(.05),F(b.target-b.size))))
      if(b.decoration<=0)b.decoration=null
      if(b.active===3 && b.timer--<0){b.active=0;b.decoration=null}
      else if(b.active===2){
        connector=popConnectorBubble(connector,rng,at)
        events.push({i,kind:'pop',count:connector.bubbles.filter(b=>b.active!==0).length})
      }
    }
    // Both bounds are from the preceding ground pass. Group 6 writes its
    // left bounds after integration; group 7 writes the right bounds later.
    const points=(connector.points||INITIAL_POINTS).map(p=>[...p])
    connector=advanceConnector({...connector,points},true,rng)
    const caps=[supportCapsule(supports[0],0,shifts[0]),null,connectorCapsule(connector)]
    connector=replenish(connector,rng)
    connector=connectorPhase(connector,rng)
    const current=connectorShifts(connector)
    connector.shifts=current
    connector.points=[...connector.points]
    for(const j of [0,2])connector.points[j]=LIVE_POINTS[j].map((v,k)=>F(v+current[0][k]))
    generatorPrefix(rng,F(environment.acid.height-55),current[0][1],LEFT_SPAWNS)
    supports[1]=supportTick(supports[1],rng)
    caps[1]=supportCapsule(supports[1],1,shifts[1])
    for(const j of [1,3])connector.points[j]=INITIAL_POINTS[j].map((v,k)=>F(v+shifts[1][k]))
    generatorPrefix(rng,F(environment.acid.height-55),shifts[1][1],RIGHT_SPAWNS)
    environmentTail(environment,rng,i)
    for(const entry of itemRows[i])if(entry.j===0&&entry.track.t===99){
      const face=turnipFaceAtSpawn(bundle,entry.track,rng)
      if(face!=null)turnipFaces.set(entry.id,face)
    }
    rows.push(stageLines(connector,supports))
    const materialHits=new Map()
    for(let port=0;port<frames.state.length;port++){
      const state=frames.state[port][i],age=frames.age?.[port]?.[i],x=frames.x?.[port]?.[i],y=frames.y?.[port]?.[i],cid=frames.cid?.[port]?.[i],dir=frames.dir?.[port]?.[i]
      const yoyoHits=yoyo(port,i,rows[i]),luigiHits=luigi(port,i,rows[i]),skullHits=skull(port,i,rows[i]),thunderHits=thunder(port,i),tetherHits=tether(port,i,rows[i],rng),chainHits=chain(port,i,rows[i])
      if(state==null){last[port]=null;previous[port]=[];continue}
      const move=fighterDataFor(cid)?.hitboxes?.[state]
      if(state!==last[port]||(i&&(age<frames.age?.[port]?.[i-1]||cid!==frames.cid?.[port]?.[i-1]))){hits[port].clear();previous[port]=[]}
      last[port]=state
      if(yoyo.reset[port]||chain.reset[port])hits[port].clear()
      if(chain.reset[port])previous[port]=[]
      if(!mayDamageStage(state)){previous[port]=[];continue}
      const spheres=chainHits!==undefined?chainHits:tetherHits!==undefined?tetherHits:thunderHits!==undefined?thunderHits:skullHits!==undefined?skullHits:luigiHits!==undefined?luigiHits:yoyoHits!==undefined?yoyoHits:attackSpheres(cid,state,age,x,y,dir,undefined,2)
      if(!spheres){unavailable=i;break}
      if(!Number.isFinite(x)||!Number.isFinite(y)){unavailable=i;break}
      const groups=new Set(spheres.map(h=>h.group))
      for(const key of hits[port])if(!groups.has(Number(key.split(':')[1])))hits[port].delete(key)
      for(let part=0;part<3;part++){
        if(!caps[part])continue
        for(const hit of spheres){
          if(hits[port].has(`${part}:${hit.group}`)||!hitCapsule(hit,previous[port]?.find(p=>p.id===hit.id&&p.group===hit.group),caps[part]))continue
          hits[port].add(`${part}:${hit.group}`);yoyo.hit(port)
          events.push({i,kind:'hit',part,port,cid,follower:port>=bundle.frames.x.length,state,age,damage:hit.damage})
          if(part===2){
            // One material DmgReceived callback, even when Popo and Nana both
            // hit it during the same item collision pass.
            if(!materialHits.has(part)){
              const at=connector.bubbles.findIndex((b,j)=>j!==0&&j!==6&&(b.active??1)===1)
              if(at>=0){connector.bubbles[at].active=2;connector.bubbles[at].target=F(.001);connector.delay=120}
              materialHits.set(part,{})
            }
          }
          else{
            const s=supports[part],knockback=F(F(F(.01)*hit.growth)*DATA.knockback.base+hit.baseKb)
            const angle=hit.angle===361?DATA.knockback.airAngle:F(F(.017453292)*hit.angle)
            s.damage=F(s.damage+materialDamage(hit,move,charged[port][i]))
            // it_80270E30 sums damage, then selects the largest knockback; ties
            // keep the first collision entry. The callback sets velocity once.
            if(!materialHits.has(part)||knockback>materialHits.get(part).knockback){
              s.velocity=F(F(knockback*DATA.knockback.speed)*F(Math.cos(angle)))*(caps[part].a[0]>x?1:-1)
              materialHits.set(part,{knockback})
            }
          }
        }
      }
      previous[port]=spheres
    }
    const needleEntries=needleStep?.(i,rows[i],rows[Math.max(0,i-1)],rng)||[]
    for(const entry of [...itemRows[i].filter(e=>!needleOnly||![79,152].includes(e.track?.t)),...needleEntries,...missingBirths(i,rows[i],rows[Math.max(0,i-1)],rng),...missingJolts(i,rows[i],rows[Math.max(0,i-1)])]) {
      const hitSpheres=itemEntryHits(entry,rows[i],rows[Math.max(0,i-1)])
      const {id,track,j,previous:old}=entry
      const spheres=knownTurnipDamage(hitSpheres,track,j,turnipFaces.get(id))
      if(!spheres){unavailable=Math.min(unavailable,i);continue}
      if(!itemHits.has(id))itemHits.set(id,new Set())
      const seen=itemHits.get(id),groups=new Set(spheres.map(h=>h.group))
      if(entry.reset)seen.clear()
      for(const key of seen)if(!groups.has(Number(key.split(':')[1])))seen.delete(key)
      for(let part=0;part<3;part++){
        if(!caps[part])continue
        for(const hit of spheres){
          const key=`${part}:${hit.group}`
          if(seen.has(key)||!hitCapsule(hit,old.find(h=>h.id===hit.id&&h.group===hit.group),caps[part]))continue
          if(hit.damageUnknown&&part!==2){unavailable=Math.min(unavailable,i);continue}
          seen.add(key)
          entry.onHit?.()
          events.push({i,kind:'hit',part,item:track.t,state:track.s[j],damage:hit.damage})
          if(part===2){
            if(!materialHits.has(part)){
              const at=connector.bubbles.findIndex((b,k)=>k!==0&&k!==6&&(b.active??1)===1)
              if(at>=0){connector.bubbles[at].active=2;connector.bubbles[at].target=F(.001);connector.delay=120}
              materialHits.set(part,{})
            }
          }else{
            const support=supports[part],knockback=F(F(F(.01)*hit.growth)*DATA.knockback.base+hit.baseKb)
            const angle=hit.angle===361?DATA.knockback.airAngle:F(F(.017453292)*hit.angle)
            support.damage=F(support.damage+Math.trunc(hit.damage))
            if(!materialHits.has(part)||knockback>materialHits.get(part).knockback){
              const dir=Math.abs(hit.vx)<hit.velocityDirectionThreshold?(caps[part].a[0]>hit.sourceX?1:-1):Math.sign(hit.vx)
              support.velocity=F(F(knockback*DATA.knockback.speed)*F(Math.cos(angle)))*dir
              materialHits.set(part,{knockback})
            }
          }
        }
      }
    }
    for(let side=0;side<2;side++)if(supports[side].phase!==supports[side].nextPhase)events.push({i,kind:'phase',side,s:{...supports[side]}})
  }
  return {rows,unavailable,events}
}

export function simulationHistory(bundle) {
  let entry=cache.get(bundle)
  if(!entry){entry=build(bundle);cache.set(bundle,entry)}
  return entry
}
export default function simulate(bundle,idx) {
  const n=bundle?.meta?.n
  if(!DATA||!Number.isInteger(n)||!supportedFighterHistory(bundle,idx,6)||bundle.frames?.seed?.[0]?.[idx]==null||!fighterDataReady(bundle)||!itemDataReady(bundle))return null
  const c=simulationHistory(bundle)
  return idx>=c.unavailable?null:{lines:c.rows[idx],replace:true,complete:true}
}
registerStageSimData(6,value=>{DATA=value})
