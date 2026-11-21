import { registerStageSimData, fighterFrames, supportedFighterHistory } from '../stageData.js'
let data
import { supportedBundle, collisionLines, worldMatrices, transformJoint } from './stage13.js'
import { floorContact } from './stage29.js'
import { copiedPartnerContact } from './stage5.js'
import { frameCursor, setupCursor } from './rng.js'
// grOnett_801E3738 creates awnings (5), building (4), then cars (3).
// The awning ambient timer precedes the building's recovery draw at priority
// 4. GrOt map_ptcl 30000 (negative random) / 30003 (kind&0x100) allocate
// synchronously without drawing; particle emission runs later at priority 15.

export function ambientStep(previous, rng) {
  const s = {...previous}
  if (s.timer-- < 0) {
    const low = data.params[s.active ? 9 : 11], high = data.params[s.active ? 10 : 12]
    s.timer = Math.min(low,high) + rng.int(Math.abs(high-low))
    s.active = !s.active
  }
  return s
}

// gronett.c 801E5214 / 801E54B4. The field called velocity in the decomp is
// the spring position; initial is its velocity. Work in model coordinates.
export function awningStep(previous, contacts = 0, landed = false) {
  const p = data.params, f = Math.fround
  const displacement = contacts ? Math.max(-p[7], f(contacts*p[8])) : 0
  const error = f(displacement-previous.position)
  let force = f((landed ? p[0] : previous.velocity)+p[6])
  const ratio = f(Math.abs(error)/p[7])
  force = error < 0 ? f(-(f(p[5]*ratio)-force)) : f(f(p[5]*ratio)+force)
  force = f(f(force-p[6])*f(1-p[4]))
  force = Math.max(-p[1],Math.min(p[1],force))
  let position, velocity
  if (Math.abs(f(previous.position-displacement)) < p[3] && Math.abs(force) < p[2]) {
    position = displacement; velocity = 0
  } else {
    position = Math.max(-p[7],Math.min(p[7],f(previous.position+force))); velocity = force
  }
  return {position,velocity,translation:f(position+displacement)}
}

export function initialBuilding() {
  return {state:0,next:0,hits:0,frame:0,timer:0,animation:0,active:[true,true]}
}

// The collision callback counts landings, not attacks or frames spent standing
// on a roof. It can queue a state change while the current animation finishes.
export function buildingStep(previous, landings, randomFloat = () => { throw new Error('Missing shared RNG draw') }) {
  const s = {...previous,active:previous.active.slice()}
  for (let i = 0; i < landings; i++) {
    s.hits++
    if (s.state === 0) s.next = s.hits < data.params[13] ? 1 : 2
    else if (s.state === 3) s.next = s.hits < data.params[14] ? 4 : 5
  }
  s.frame++
  const done = s.frame > data.models[4].animations[s.animation].end
  if (s.state === 7) { if (s.timer-- < 0) s.next = 0 }
  else if (s.state === 1 && done) s.next = 0
  else if ((s.state === 2 || s.state === 4) && done) s.next = 3
  else if (s.state === 5) {
    if (s.frame === 20) s.active[0] = false
    if (s.frame === 90) s.active[1] = false
    if (done) {
      const lo = data.params[15], range = Math.fround(data.params[16]-lo)
      s.timer = Math.trunc(Math.fround(Math.fround(range*randomFloat())+lo)); s.next = 6
    }
  } else if (s.state === 6 && s.timer-- < 0) { s.next = 7; s.timer = 60 }
  if (s.state !== s.next) {
    s.state = s.next; s.frame = 0
    if (s.state === 7) { s.animation = 0; s.active = [true,true] }
    else if ([1,2,4,5].includes(s.state)) s.animation = ({1:1,2:3,4:4,5:5})[s.state]
    else if (s.state === 6) s.hits = 0
  }
  return s
}

const caches = new WeakMap()
function buildCache(bundle) {
  const frames = fighterFrames(bundle)
  const bounds = [0,1,3,4].map(joint => {
    const [start,n] = data.joints[joint], v = data.initial.slice(start,start+n)
    return [Math.min(...v.map(p=>p[0]))-6,Math.max(...v.map(p=>p[0]))+6,
      Math.min(...v.map(p=>p[1]))-14,Math.max(...v.map(p=>p[1]))+14]
  })
  const near = (x,y) => bounds.some(([x0,x1,y0,y1]) => x>=x0 && x<=x1 && y>=y0 && y<=y1)
  let unsupported = Infinity
  for (const item of bundle.items || []) if (![106,107,160].includes(item.t)) for (let i=0;i<item.x.length;i++) {
    if (near(item.x[i],item.y[i])) { unsupported = Math.min(unsupported,item.f+i); break }
  }
  const rows=[]
  let awnings=[{position:0,velocity:0},{position:0,velocity:0}],building=initialBuilding()
  const init=setupCursor(bundle)
  let ambient=init?{timer:data.params[9]+init.int(data.params[10]-data.params[9]),active:false}:null
  let previous=collisionLines(data,data.initial,[true,true,true,true,true])
  let animation=0,age=0,pending=null,animated=false
  for(let i=0;i<Math.min(bundle.meta.n,unsupported);i++){
    const contacts=[0,0],landed=[false,false];let roofLandings=0
    if(i>84)for(let port=0;port<frames.x.length;port++){
      if(copiedPartnerContact(bundle,frames,port,i-1))continue
      const line=previous.find(l=>floorContact(frames,port,i-1,l))
      if(!line)continue
      const vertex=data.lines[line[0]][0],joint=data.joints.findIndex(([start,n])=>vertex>=start&&vertex<start+n)
      const landing=!!frames.air[port][i-2]
      if(joint<2){contacts[joint]++;landed[joint]||=landing}
      else if(joint>=3&&landing)roofLandings++
    }
    if(i>84)for(const item of bundle.items||[]){
      if(item.t!==106)continue
      const k=i-1-item.f
      if(k<0||k>=item.x.length)continue
      // PlPp's ice article has a 4-unit bottom ECB. Its air map sets
      // touched_floor; Blizzard's StayAirborne map does not call Cb1.
      const x=item.x[k],y=item.y[k]-4
      const line=previous.find(l=>(l[1]&15)===1&&x>=l[2]&&x<=l[4]&&Math.abs(y-(l[3]+(x-l[2])*(l[5]-l[3])/(l[4]-l[2])))<.002)
      if(!line)continue
      const vertex=data.lines[line[0]][0],joint=data.joints.findIndex(([start,n])=>vertex>=start&&vertex<start+n)
      const landing=[1,3].includes(item.s?.[k-1])
      if(joint<2){contacts[joint]++;landed[joint]||=landing}
      else if(joint>=3&&landing)roofLandings++
    }
    awnings=awnings.map((a,j)=>awningStep(a,contacts[j],landed[j]))
    if(pending!=null){animation=pending;age=0;pending=null;animated=true}
    else if(animated)age=Math.min(age+1,data.models[4].animations[animation].end)
    const oldState=building.state
    let rng=frameCursor(bundle,i)
    if(ambient){
      if(ambient.timer<0&&!rng)ambient=null
      else ambient=ambientStep(ambient,rng)
    }
    building=buildingStep(building,roofLandings,()=>ambient&&rng?rng.float():NaN)
    if(!Number.isFinite(building.timer)){unsupported=i;break}
    if(building.state!==oldState&&[1,2,4,5,7].includes(building.state))pending=building.animation
    const vertices=data.initial.map(v=>v.slice())
    for(let j=0;j<2;j++){
      const [start,n]=data.joints[j]
      for(let k=start;k<start+n;k++)vertices[k][1]=Math.fround(vertices[k][1]+Math.fround(awnings[j].translation*data.scale))
    }
    if(animated){
      const matrices=worldMatrices(data,4,animation,age)
      transformJoint(data,vertices,3,matrices[2]);transformJoint(data,vertices,4,matrices[4])
    }
    previous=collisionLines(data,vertices,[true,true,true,...building.active]).map(l=>l.map((v,k)=>k>=2?Math.fround(v):v))
    rows.push(previous)
  }
  return {unsupported,rows}
}

export default function simulate(bundle,idx) {
  if (!data) return null
  if (!supportedBundle(bundle,idx) || !supportedFighterHistory(bundle,idx,9)) return null
  let cache = caches.get(bundle)
  if (!cache) { cache = buildCache(bundle); caches.set(bundle,cache) }
  if (idx >= cache.unsupported) return null
  return {lines:cache.rows[idx].map(l=>l.slice()),replace:true,complete:true}
}

registerStageSimData(9, value => {
  data = value
})
