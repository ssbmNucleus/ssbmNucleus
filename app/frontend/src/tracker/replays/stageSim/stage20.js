import { registerStageSimData } from '../stageData.js'
let data
import {collisionLines,worldMatrices,transformJoint,sampleTrack} from './stage13.js'
import {setupCursor,frameCursor} from './rng.js'
import {supportedHistory} from './stage29.js'

// grInishie2_801FD654 reads the Birdo ITEM position at priority 4, before
// item physics. Kind 233 is Birdo; eggs (236) do not attach MapJoint 14.
export function birdoLines(item,sample) {
  if(item?.t!==233 || !Number.isInteger(sample) || sample<0 || sample>=item.x.length)return null
  const vertices=data.initial.map(v=>v.slice()),[start,n]=data.joints[14]
  for(let k=start;k<start+n;k++)vertices[k]=[
    Math.fround(data.initial[k][0]+item.x[sample]),
    Math.fround(data.initial[k][1]+item.y[sample]+data.params.x2C)]
  return collisionLines(data,vertices,data.joints.map((_,j)=>j===14))
}

const f=Math.fround
let timers
let bounds

// grInishie2_801FCE04 calls FD018, FD368, FD744 in that order before
// fighters exist: left carpet, right carpet, Birdo, then Pidgit setup draws.
export function initialSchedule(rng) {
  return [0,2,4,6].map(k=>timers[k]+rng.int(timers[k+1]))
}

// FD9EC keeps the last NON-terminal child translation when restarting a
// clip. Its first two in-view cycles turn unconditionally; later ones either
// depart or draw from the authored [continue, turn] weights.
export function pidgitTurn(previous,randomInt) {
  const s={...previous}
  const side=s.x+s.dx>bounds.right?2:s.x+s.dx<bounds.left?1:0
  if(s.entering){if(side===0)s.entering=false}
  else {
    if(!s.exiting) {
      if(s.cycles<2)s.anim^=1
      else if(side){s.exiting=true;s.anim=side&1;s.leaving=true}
      else if(randomInt(data.directionWeights[0]+data.directionWeights[1])>=data.directionWeights[0])s.anim^=1
    }
    s.cycles++
  }
  s.x=f(s.x+s.dx);s.y=f(s.y+s.dy);s.age=0
  return s
}

const caches=new WeakMap()
function build(bundle) {
  const init=setupCursor(bundle)
  if(!init)return []
  const waits=initialSchedule(init),carpets=[null,null],rows=[]
  const birdos=(bundle.items||[]).filter(item=>item.t===233)
  let pidgit=null
  for(let i=0;i<bundle.meta.n;i++) {
    const rng=frameCursor(bundle,i)
    if(!rng)break
    const active=data.joints.map((_,j)=>j===1),vertices=data.initial.map(v=>v.slice())
    let birdoCreated=false,unknownPrefix=false
    const draw=n=>{
      // Birdo's direction draw is followed by synchronous item creation.
      // Until that transitive prefix is certified, fail closed if another
      // stage object needs RNG later in the SAME priority-4 pass.
      if(birdoCreated){unknownPrefix=true;return 0}
      return rng.int(n)
    }
    for(const carpet of carpets)if(carpet)carpet.age++
    if(pidgit)pidgit.age++
    // Controller FD0B4 runs before FD3CC/FD7A8 and all spawned objects.
    for(let j=0;j<2;j++)if(!carpets[j]&&waits[j]--<0) {
      carpets[j]={age:0,delay:timers[8+j],order:i}
    }
    // Birdo is a recorded item, as on Great Bay's Tingle path. Its respawn
    // timer runs in the item-destruction callback, not this ground RNG phase.
    // No timer or direction is inferred by searching a future seed.
    const birdo=birdos.find(item=>i>=item.f&&i<item.f+item.x.length)
    if(birdo) {
      const sample=i-birdo.f
      // Damaged/dead Birdo can disable joint 14 after the ground pass. That
      // callback path needs its own chronology; it is not ordinary movement.
      if(!Array.isArray(birdo.s)||birdo.s[sample]>=8||birdo.s[0]!==0
        ||!Number.isFinite(birdo.y[sample])||birdo.vy?.[sample]!==0)break
      birdoCreated=sample===0
    }
    if(!pidgit&&waits[3]--<0) {
      const side=draw(2)
      pidgit={age:0,anim:side===0?1:0,
        x:side===0?f(bounds.blastRight+data.params.x30):f(bounds.blastLeft+data.params.x3C),
        y:side===0?data.params.x34:data.params.x40,entering:true,exiting:false,
        leaving:false,cycles:0,dx:0,dy:0,order:i}
    }
    // Same-priority GObjs run in creation order, which can change each cycle.
    const objects=[...carpets.flatMap((c,j)=>c?[{c,j,order:c.order}]:[]),
      ...(pidgit?[{c:pidgit,j:3,order:pidgit.order}]:[])]
      .sort((a,b)=>a.order-b.order||a.j-b.j)
    for(const {c,j} of objects) {
      if(j<2) {
        if(c.delay--<0)active[12+j]=true
        transformJoint(data,vertices,12+j,worldMatrices(data,j+3,0,c.age)[2])
        if(c.age>=data.models[j+3].animations[0].end) {
          active[12+j]=false;carpets[j]=null
          waits[j]=timers[j*2]+draw(timers[j*2+1])
        }
      } else {
        active[0]=true
        const matrix=worldMatrices(data,1,c.anim,c.age,{x:c.x*data.scale,y:c.y*data.scale})[2]
        transformJoint(data,vertices,0,matrix)
        if(c.age>=data.models[1].animations[c.anim].end) {
          Object.assign(c,pidgitTurn(c,draw))
        } else {
          const tracks=data.models[1].animations[c.anim].tracks[2]
          c.dx=f(sampleTrack(tracks.find(([k])=>k===5)[1],c.age))
          c.dy=f(sampleTrack(tracks.find(([k])=>k===6)[1],c.age))
        }
        // FD9EC compares local translation to camera limits; FDED8 checks
        // the world-space root against blast limits AFTER restarting a clip.
        if(c.leaving&&(c.x*data.scale>bounds.blastRight||c.x*data.scale<bounds.blastLeft)) {
          pidgit=null;active[0]=false;waits[3]=timers[6]+draw(timers[7])
        }
      }
    }
    if(unknownPrefix)break
    let lines=collisionLines(data,vertices,active).map(l=>l.map((v,k)=>k>=2?f(v):v))
    if(birdo) {
      const sample=i-birdo.f
      if(sample>0)lines.push(...birdoLines(birdo,sample-1))
      else {
        // FD4F0's authored spawn X precedes the first item physics update;
        // initialization already corrects Y to the flat ground. Entry has
        // zero vertical velocity, so its recorded Y is the same position.
        const x=birdo.x[0]>0?f(bounds.blastRight+data.params.x14):f(bounds.blastLeft+data.params.x20)
        lines.push(...birdoLines({t:233,x:[x],y:[birdo.y[0]]},0))
      }
    }
    rows.push(lines)
  }
  return rows
}

export default function simulate(bundle,idx) {
  if (!data) return null
  if(!supportedHistory(bundle,idx,20))return null
  let rows=caches.get(bundle)
  if(!rows){rows=build(bundle);caches.set(bundle,rows)}
  return rows[idx]?{lines:rows[idx].map(l=>l.slice()),replace:true,complete:true}:null
}

registerStageSimData(20, value => {
  data = value
  timers=data.timers
  bounds=Object.fromEntries(Object.entries(data.bounds).map(([k,v])=>[k,f(v)]))
})
