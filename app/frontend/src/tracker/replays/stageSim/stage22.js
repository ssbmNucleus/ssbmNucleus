import { COLLISION_TIMING } from './collisionTiming.js'
export const { collisionLag } = COLLISION_TIMING[22]
import { frameCursor } from './rng.js'
import { registerStageSimData } from '../stageData.js'
let DATA
// Both Star Fox stages use the same HSD interpolation and joint evaluation.
import { sample, pathPosition, stepSeed } from './stage7.js'

// NTSC 1.02 grvenom.c: priority 4 scheduler 5 precedes environment 7 and
// spawned Arwings. The 600-frame initial wait is deterministic; later choices
// use the current frame's final input seed. Camera bounds/light updates have
// no RNG; environment 7 has only animation, lighting and fixed sound calls.
// For near routes the model's bank draw follows the scheduler wait draw.
// Far-route laser draws run later in that model callback and cannot precede
// a near-route bank or the scheduler. Re-anchor at each frame, never carry
// those later draws into the next frame's seed.
const F=Math.fround,cache=new WeakMap()
export { stepSeed }
export function initialState(){return {frame:-124,wait:600,type:0,group:0,plane:null}}

export function environment(animationFrame){
  // Both authored AOBJs loop at 9999; HSD_AObjInterpretAnim wraps before
  // evaluating the new pose. Do not restart the independent Arwing scheduler.
  animationFrame %= 9999
  return { blocked:animationFrame>=3800&&animationFrame<6100,
    limited:animationFrame>=6810&&animationFrame<9200,
    collision:animationFrame>=4400&&animationFrame<6100 }
}

export function advance(state,seed){
  const s={...state,frame:state.frame+1,plane:state.plane?{...state.plane}:null}
  const randf=()=>{seed=stepSeed(seed);return(seed>>>16)/65536}
  const rand=n=>Math.floor(n*randf())
  // Gobj 5 (scheduler) precedes gobj 7 (environment) in the proc list.
  const env=environment(s.frame+123)
  if(!s.plane){
    if(--s.wait<=0&&!env.blocked){
      let type=s.type
      while(type===s.type)type=1+rand(env.limited?4:11)
      s.type=type;s.group=s.group===4?1:randf()>F(.15)?1:4
      if(s.group!==4)rand(2)
      s.plane={start:s.frame,route:type-1,bankState:0,bankWait:120,bankStart:s.frame,bankAnim:-1}
    }
  }else{
    s.wait=960+rand(840)
    if(s.frame-s.plane.start>=DATA.routes[s.plane.route].end){s.plane=null;return s}
  }
  const p=s.plane
  if(p&&s.type<=7){
    if(p.bankState===0){
      if(p.bankWait<=0){
        p.bankState=rand(4)+1
        p.bankAnim=[[-1,-1],[1,0],[2,2],[4,4],[5,5]][p.bankState][s.group===4?1:0]
        p.bankStart=s.frame
      }
      p.bankWait--
    }else if(s.frame-p.bankStart>DATA.banks[s.group===4?1:0][p.bankAnim].end){
      p.bankState=0;p.bankWait=120;p.bankAnim=-1
    }
  }
  return s
}

function dynamicKind(a,b){
  const dx=F(b[0]-a[0]),dy=F(b[1]-a[1]),slope=F(dy/dx)
  if(dx>0)return slope>1.7320508368950045?8:slope< -1.7320508368950045?4:1
  if(dx<0)return slope>.577350295784245?4:slope< -.577350295784245?8:2
  return dy>0?8:4
}

// The canonical track times include each signed FObjDesc.startframe. In
// particular route 2's moving node starts ten ticks into its key stream;
// advancing the scheduler or the whole route would shift unrelated tracks.
export function arwingPosition(route, age) {
  return DATA ? pathPosition(DATA.routes[route], age) : null
}

function geometry(s){
  const lines=[],angle=sample(DATA.shipRotation,(s.frame+123)%9999)
  const c=F(Math.cos(angle)*F(.54)),sn=F(Math.sin(angle)*F(.54))
  const ship=DATA.vertices.map(([x,y])=>[F(c*x-sn*y),F(sn*x+c*y)])
  for(let id=0;id<DATA.lines.length;id++){
    if(id>18&&id<41||id>56)continue
    const [a,b,flag]=DATA.lines[id];lines.push([id,flag,...ship[a],...ship[b]])
  }
  // Environment 7 is started with grAnime_801C8138 in OnInit (grvenom.c:478),
  // which immediately evaluates frame 0. The first priority-1 pass evaluates
  // frame 1. Its later priority-4 callback toggles joint 2 at 4400/6100
  // (894-907). Scheduler 5, above, still sees the PREVIOUS environment flags.
  // This is an animation phase difference, not a future-frame seed or lag.
  if(environment(s.frame+124).collision){
    for(let id=57;id<=63;id++){
      const [a,b]=DATA.lines[id],p=DATA.vertices[a],q=DATA.vertices[b]
      lines.push([id,dynamicKind(p,q),...p,...q])
    }
  }
  const p=s.plane
  if(p&&s.type<=7){
    const [rx,ry,rz]=arwingPosition(p.route,s.frame-p.start)
    const bank=p.bankAnim<0?null:DATA.banks[s.group===4?1:0][p.bankAnim]
    const age=Math.max(0,s.frame-p.bankStart-1)
    let angle=bank?sample(bank.keys,age):0
    if(s.group===4)angle=0
    while(angle< -Math.PI)angle+=Math.PI*2
    while(angle>Math.PI)angle-=Math.PI*2
    if(Math.abs(F(rz*F(.27)))<50&&Math.abs(angle)<F(Math.PI/3)){
      const x=F(rx*F(.54)),y=F(F(ry*F(.54))+F((bank?sample(bank.y,age):0)*F(.27)))
      for(let id=s.group===4?19:26;id<=(s.group===4?25:40);id++){
        const [a,b,flag]=DATA.lines[id],p=DATA.vertices[a],q=DATA.vertices[b]
        lines.push([id,flag,F(p[0]*F(.27)+x),F(p[1]*F(.27)+y),F(q[0]*F(.27)+x),F(q[1]*F(.27)+y)])
      }
    }
  }
  // C18 validates active Arwings and more than two environment cycles. Numeric
  // HSD interpolation passes the 0.05u gate but is not bit-exact on all poses.
  return {lines,replace:true,complete:false}
}

export default function simulate(bundle,idx){
  if (!DATA) return null
  const meta=bundle?.meta,seeds=bundle?.frames?.seed?.[0]
  if(meta?.stage!==22||meta.start_frame!==-123||!Number.isInteger(idx)||idx<0||
    !seeds||idx>=seeds.length||seeds[idx]==null)return null
  let entry=cache.get(bundle)
  if(!entry){entry=new Map([[-124,initialState()]]);cache.set(bundle,entry)}
  const frame=idx-123
  let key=-124+Math.floor((frame+124)/128)*128
  while(!entry.has(key))key-=128
  let state=entry.get(key)
  for(let f=key+1;f<=frame;f++){
    const rng=frameCursor(bundle,f+123)
    if(!rng)return null
    state=advance(state,rng.seed)
    if((f+124)%128===0)entry.set(f,state)
  }
  return geometry(state)
}

registerStageSimData(22, value => {
  DATA = value
})
