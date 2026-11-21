import { registerStageSimData, fighterDataFor, fighterDataReady, fighterFrames, itemDataReady, supportedFighterHistory as supportedHistory } from '../stageData.js'
let data
import {collisionLines} from './stage13.js'
import {floorContact} from './stage29.js'
import {attackSpheres,itemAttackHistory,itemEntryHits,itemMaterialOccupancy,sleepingFighterHistory,unrecordedLaserHistory,stopCeilContact,nessYoyoHistory,luigiMissileHistory,skullBashHistory,thunderHitHistory,airCatchHistory,chainHistory} from './stage16.js'
import {frameCursor} from './rng.js'

const f=Math.fround
let p
export function initialPulley(){return {state:0,offset:0,speed:0,fall:0,timer:0}}
// grInishie1_801FC110/664/4A0, model coordinates. Cb1 multiplies landing
// weight by x40 (=8); sustained ground contact contributes ordinary weight.
export function pulleyStep(previous,left,right,bottom=f(data.blastBottom-30)) {
  const s={...previous}
  if(s.state===0) {
    if(left>100000||right>100000)left=right=100000
    left=Math.max(0,f(left-p.x3C));right=Math.max(0,f(right-p.x3C))
    if(!left&&!right){s.offset=Math.sign(s.offset)*Math.max(0,f(Math.abs(s.offset)-p.x38));s.speed=0}
    else {
      s.speed=Math.max(-p.x28,Math.min(p.x28,f(f(f(right-left)*p.x24)+s.speed)))
      if(left&&right&&s.speed)s.speed=f(s.speed*p.x2C)
      else {s.speed=f(s.speed*p.x30);s.speed=Math.sign(s.speed)*Math.max(0,f(Math.abs(s.speed)-p.x34))}
      s.offset=f(s.offset+s.speed)
    }
    if(Math.abs(s.offset)>p.x20){s.offset=Math.sign(s.offset)*p.x20;s.state=1;s.speed=0}
  } else if(s.state===1) {
    s.speed=Math.min(p.x48,f(s.speed+p.x44));s.fall=f(s.fall-s.speed)
    if(f(35+s.fall+Math.abs(s.offset))*data.scale<bottom){s.state=2;s.speed=0;s.timer=Math.trunc(p.x4C)}
  } else if(s.state===2) {
    if(--s.timer===0){s.state=3;s.fall=0}
  } else if(s.state===3) {
    s.offset=Math.sign(s.offset)*Math.max(0,f(Math.abs(s.offset)-p.x50))
    if(s.offset===0){s.state=0;s.speed=0}
  }
  return s
}

// fn_801FBEB8 is a CEILING callback (Cb2), with fabs(delta_y) > .7.
// Attacks call fn_801FBF6C instead. Both hide a block and draw a 400..499
// respawn timer at the collision callback's own scheduler priority.
export function ceilingBreak(deltaY){return Math.abs(deltaY)>.7}
export function brokenBlock(randomInt){return {state:0,timer:data.respawn[0]+randomInt(data.respawn[1]-data.respawn[0]),active:false}}
export function blockRespawnStep(previous,occupied) {
  const s={...previous}
  if(s.state===0) {
    if(s.timer)s.timer--
    else if(!occupied){s.active=true;s.state=1;s.timer=30}
  }else if(s.state===1){if(s.timer>0)s.timer--;else s.state=2}
  return s
}

const caches=new WeakMap()
let centers
function pulleyContact(frames,port,i,line) {
  // mpLib_8004DD90_Floor accepts a grounded bottom up to .1 beyond an
  // isolated floor endpoint. mpCollEnd still calls Cb1 on that frame.
  // Both pulleys are horizontal; extending their endpoints preserves Y.
  const extended=line.slice()
  if(extended[2]<extended[4]){extended[2]-=.1;extended[4]+=.1}
  else {extended[2]+=.1;extended[4]-=.1}
  if(floorContact(frames,port,i,extended))return true
  // ftSs_SpecialLwBomb_Coll uses a fixed Morph Ball ECB while cmd_var0
  // is set. Its positive bottom places the grounded root below the floor;
  // the landing pass can still have the ordinary bottom before the swap.
  if(i<0||frames.air[port][i]||frames.cid[port][i]!==13||frames.state[port][i]!==355||frames.age[port][i]<10||frames.age[port][i]>=43)return false
  const x=frames.x[port][i],bottom=fighterDataFor(13)?.morphBallEcb?.[1]
  return Number.isFinite(bottom)&&x>=Math.min(extended[2],extended[4])&&x<=Math.max(extended[2],extended[4])&&Math.abs(frames.y[port][i]+bottom-extended[3])<.002
}
// Distance between the swept hit center and the material's vertical capsule.
// lbColl_80006E58; grMaterial_801C8DE0 endpoints (0,-1,0)/(0,1,0), radius 6.
export function blockHit(hit,previous,cx,cy) {
  const a=previous||hit,dx=hit.x-a.x,dy=hit.y-a.y,dz=hit.z-a.z
  const cuts=[0,1]
  if(dy)for(const y of [cy-1,cy+1]){const t=(y-a.y)/dy;if(t>0&&t<1)cuts.push(t)}
  cuts.sort((a,b)=>a-b)
  for(let i=1;i<cuts.length;i++){
    const lo=cuts[i-1],hi=cuts[i],mid=a.y+dy*(lo+hi)/2
    const by=mid<cy-1?cy-1:mid>cy+1?cy+1:null
    const v=dx*dx+dz*dz+(by===null?0:dy*dy)
    const t=Math.max(lo,Math.min(hi,v?-((a.x-cx)*dx+a.z*dz+(by===null?0:(a.y-by)*dy))/v:lo))
    const y=a.y+dy*t,ey=y-Math.max(cy-1,Math.min(cy+1,y))
    if((a.x+dx*t-cx)**2+(a.z+dz*t)**2+ey*ey<=(hit.radius+6)**2)return true
  }
  return false
}

function headBump(frames,port,i,blocks) {
  const state=frames.state[port][i],age=frames.age[port][i]
  if(state==null)return -1
  const stopped=state===250
  if(stopped&&age!==0)return -1
  if(!stopped&&!frames.air[port][i])return -1
  if(i===0)return stopped?null:-1
  if(stopped&&frames.state[port][i-1]===250)return -1
  const fighter=fighterDataFor(frames.cid[port][i])
  const top=stopped?fighter?.ecb?.[frames.state[port][i-1]]?.[frames.age[port][i-1]+1]?.[3]:fighter?.ecb?.[state]?.[age]?.[3]
  if(top==null)return stopped?null:-1
  // StopCeil replaces the pose AFTER mpCollEnd: post Y is ceiling Y plus
  // the new TransN translation, not CollData.cur_pos at Cb2.
  // AttackAir's map callback keeps its motion after a ceiling correction;
  // its authored ECB instead identifies the corrected contact directly.
  const ceiling=stopped?frames.y[port][i]-fighter.stopCeilTranslationY:frames.y[port][i]+top,x=frames.x[port][i]
  // 80082D40 -> 80048768 loads a compressed ECB (flags 0x12). Its
  // model root is still at the first corrected position while cur_pos
  // already includes TransN. Hence the second top is mid + 1 - top -
  // TransN; if it crosses the ceiling, 8004E090 pushes it down by .0001.
  // Preserve the original Marth projection, whose stored pose retains TransN.
  const stop=fighter.ecb?.[250]?.[0]
  const correction=stopped&&frames.cid[port][i]!==18&&stop?Math.max(0,(stop[2]+stop[3])/2+1-top):0
  const hits=centers.flatMap(([cx,cy],j)=>blocks[j].active&&
    Math.abs(ceiling+correction+(correction ? .0001 : 0)-(cy-4.25))<.002&&x>cx-4.25&&x<cx+4.25?[j]:[])
  const inferred=stopped&&hits.length!==1?stopCeilContact(frames,port,i,blocks,centers,collisionLines(data,data.initial,[true])):null
  if(hits.length!==1&&!inferred)return stopped?null:-1
  const block=inferred?.block??hits[0],firstTop=inferred?.top??top
  const delta=centers[block][1]-4.25-firstTop-frames.y[port][i-1]
  const second=correction||inferred?frames.y[port][i]-(centers[block][1]-4.25-firstTop):0
  if(Math.abs(Math.abs(delta)-.7)<.02||Math.abs(Math.abs(second)-.7)<.02)return null
  const count=Number(ceilingBreak(delta))+Number(ceilingBreak(second))
  return count?{block,count}:-1
}

function returnOccupied(frames,port,i,cx,cy) {
  if(i<0)return false
  if(frames.state[port][i]==null)return false
  const x=frames.x[port][i],y=frames.y[port][i]
  // All ordinary fighter ECB bottoms are clamped at zero. A point below
  // root-15 is outside even when the bottom remains locked after a jump.
  if(cy<y-15.02)return false
  const cid=frames.cid[port][i],fighter=fighterDataFor(cid),state=frames.state[port][i]
  if(cid===18&&(Math.abs(x-cx)>60||Math.abs(y-cy)>80))return false
  // A rotation preserves length; the extracted sum-of-bone-lengths bound
  // includes Hermite control extrema, scale and SRT blending. It can prove
  // clearance without guessing a fractional or runtime-blended pose.
  const radius=fighter?.ecbRadius
  if(Number.isFinite(radius)&&(Math.abs(x-cx)>radius+15.02||Math.abs(y-cy)>radius+15.02))return false
  if(cid!==18&&state>=29&&state<=34)return null // Fall_Anim blends with drift.
  const copiedPose=cid===4&&/^(Mr|Dr|Lg|Pk|Pc|Sk|Mt|Gw|Fx|Fc|Ss|Lk|Cl|Ns)Special/.test(fighter?.hitboxes?.[state]?.motion||'')
  if(state>=341&&!(cid===7&&state>=341&&state<=348||cid===8&&state>=358&&state<=366||cid===24&&[353,354].includes(state)||copiedPose))return null // Other specials can replace the authored ECB.
  const bounds=fighter?.ecb?.[state]?.[frames.age[port][i]]
  if(!bounds)return null
  const dir=frames.dir?.[port]?.[i]
  if(dir!==1&&dir!==-1)return null
  const left=Math.min(-2,dir===1?bounds[0]:-bounds[1]),right=Math.max(2,dir===1?bounds[1]:-bounds[0])
  const distances=[cx-(x+left-15),x+right+15-cx,cy-(y-15),y+bounds[3]+15-cy]
  if(distances.some(d=>d<-.02))return false
  if(distances.some(d=>d<.02))return null
  return true
}

function build(bundle) {
  const frames=fighterFrames(bundle),rows=[],events=[]
  const lastSpheres=[],lastActions=[]
  const itemRows=itemAttackHistory(bundle)
  const laserStep=unrecordedLaserHistory(bundle)
  const yoyo=nessYoyoHistory(bundle),luigi=luigiMissileHistory(bundle),skull=skullBashHistory(bundle),thunder=thunderHitHistory(bundle),tether=airCatchHistory(bundle),chain=chainHistory(bundle)
  const sleeping=sleepingFighterHistory(frames)
  let priorItems=[]
  let blocks=centers.map(()=>({state:2,timer:0,active:true}))
  let s=initialPulley(),last=collisionLines(data,data.initial,data.joints.map(()=>true)),unavailable=Infinity
  for(let i=0;i<bundle.meta.n;i++){
    const loads=[0,0]
    blocks=blocks.map((block,j)=>{
      if(block.state===2)return block
      const [cx,cy]=centers[j]
      const occupants=block.state===0&&!block.timer?[...frames.x.map((_,port)=>returnOccupied(frames,port,i-1,cx,cy)),...sleeping(i-1,cx,cy,15)]:[]
      // Held/inert articles can retain an older CollData position. Until
      // their ECB update is certified, preserve the existing recoverable
      // clearance gate over the whole possible birth-to-current rectangle.
      if(block.state===0&&!block.timer)for(const entry of priorItems){
        const t=entry.track,j=entry.j
        // Item animation deletes expired articles before ground callbacks.
        if(!t||t.expiresAt!=null&&i>=t.expiresAt)continue
        if(t.fixedEcb||cx>=Math.min(t.x[0],t.x[j])-20&&cx<=Math.max(t.x[0],t.x[j])+20&&cy>=Math.min(t.y[0],t.y[j])-20&&cy<=Math.max(t.y[0],t.y[j])+20)occupants.push(itemMaterialOccupancy(t,cx,cy,15,j,bundle))
      }
      const occupied=occupants.some(v=>v===true),unknown=occupants.includes(null)
      const uncertain=block.returnUncertain||unknown&&!occupied
      const next=blockRespawnStep(block,occupied||unknown)
      // Returning has no RNG draw. While clearance is ambiguous, withhold
      // just those rows; once every possible pose clears, the block is
      // certainly visible again. A possible intervening attack gates history.
      next.returnUncertain=uncertain&&(occupied||unknown)
      return next
    })
    const rowUncertain=blocks.some(b=>b.returnUncertain)
    for(const entry of priorItems){const load=entry.groundLoad;if(load&&[26,27].includes(load.line))loads[load.line-26]+=load.weight*(load.landing?p.x40:1)}
    const visible=blocks.map(b=>b.active)
    const breaks=[]
    for(let port=0;port<frames.x.length;port++) {
      for(let j=0;j<2;j++)if(last.some(l=>l[0]===26+j&&pulleyContact(frames,port,i-1,l))){
        const weight=fighterDataFor(frames.cid[port][i-1])?.weight
        if(!Number.isFinite(weight)){unavailable=Math.min(unavailable,i);continue}
        // Mario/Dr. Mario enter the air Tornado motion while their GA flag
        // can remain grounded. Its ft_800824A0 pass still reports a landing
        // (ground_kind=1) when it changes to the ground motion.
        const tornadoLanding=i>1&&[0,21].includes(frames.cid[port][i-1])&&frames.state[port][i-2]===350&&frames.state[port][i-1]===349
        loads[j]+=weight*(i>1&&(frames.air[port][i-2]||tornadoLanding)?p.x40:1)
      }
      const x=frames.x[port][i],y=frames.y[port][i],state=frames.state[port][i],age=frames.age[port][i]
      const yoyoHits=yoyo(port,i,last),luigiHits=luigi(port,i,last),skullHits=skull(port,i,last),thunderHits=thunder(port,i),tetherHits=tether(port,i,last),chainHits=chain(port,i,last)
      if(state==null){lastActions[port]=null;lastSpheres[port]=[];continue}
      if(state!==lastActions[port] || i && (age<frames.age[port][i-1] || frames.cid[port][i]!==frames.cid[port][i-1]))lastSpheres[port]=[]
      lastActions[port]=state
      if(chain.reset[port])lastSpheres[port]=[]
      const near=centers.some(([cx,cy])=>Math.abs(x-cx)<45&&Math.abs(y-cy)<45)
      const head=headBump(frames,port,i,blocks)
      if(head===null)unavailable=Math.min(unavailable,i)
      else if(head!==-1)for(let n=0;n<head.count;n++)breaks.push({block:head.block,kind:'ceiling',port})
      if(near && (state>=44&&state<=69 || state>=341 || state>=94&&state<=143
        || [187,195,217,219,220,221,222,256,257].includes(state))) {
        const spheres=chainHits!==undefined?chainHits:tetherHits!==undefined?tetherHits:thunderHits!==undefined?thunderHits:skullHits!==undefined?skullHits:luigiHits!==undefined?luigiHits:yoyoHits===undefined?attackSpheres(frames.cid[port][i],state,age,x,y,frames.dir?.[port]?.[i],undefined,1):yoyoHits
        if(!spheres)unavailable=Math.min(unavailable,i)
        else centers.forEach(([cx,cy],j)=>{
          if(!blocks[j].active&&!blocks[j].returnUncertain)return
          const hits=spheres.filter(h=>blockHit(h,lastSpheres[port]?.find(a=>a.id===h.id&&a.group===h.group),cx,cy))
          if(blocks[j].returnUncertain){if(hits.length)unavailable=Math.min(unavailable,i);return}
          const groups=new Set()
          for(const hit of hits)if(!groups.has(hit.group)){
            groups.add(hit.group);breaks.push({block:j,kind:'attack',port,element:hit.element})
          }
        })
        lastSpheres[port]=spheres||[]
      }else lastSpheres[port]=[]
    }
    const nextPulley=pulleyStep(s,...loads)
    const vertices=data.initial.map(v=>v.slice())
    for(let j=0;j<2;j++){
      const [start,n]=data.joints[20+j]
      for(let k=start;k<start+n;k++)vertices[k][1]=f(data.scale*f(35+nextPulley.fall+(j?-nextPulley.offset:nextPulley.offset)))
    }
    const currentLines=collisionLines(data,vertices,[true,...visible,true,true])
    const articleRng=frameCursor(bundle,i)
    if(articleRng)for(const hit of breaks)if(hit.kind==='ceiling')for(let n=0;n<1+data.breakEffectDraws;n++)articleRng.float()
    if(articleRng)for(const draws of tether.draws)for(let n=0;n<(draws||0);n++)articleRng.float()
    const currentItems=[...itemRows[i],...laserStep(i,currentLines,last,articleRng)]
    for(const entry of currentItems){
      const hits=itemEntryHits(entry,currentLines,last)
      const {id,previous}=entry
      if(!hits){unavailable=Math.min(unavailable,i);continue}
      centers.forEach(([cx,cy],block)=>{
        if(!blocks[block].active&&!blocks[block].returnUncertain)return
        const groups=new Set()
        for(const hit of hits){
          if(groups.has(hit.group)||!blockHit(hit,previous.find(h=>h.id===hit.id&&h.group===hit.group),cx,cy))continue
          if(blocks[block].returnUncertain){unavailable=Math.min(unavailable,i);continue}
          groups.add(hit.group);breaks.push({block,kind:'attack',item:id,element:hit.element})
          const born=entry.onHit?.();if(born)currentItems.push(born)
        }
      })
    }
    if(breaks.length){
      events.push({i,breaks})
      const rng=frameCursor(bundle,i)
      // Fighter-vs-fighter resolution can add effects before item callbacks.
      // Missing percent history in a multiplayer replay cannot prove that
      // prefix. Ordinary material-only hits include leaders and Nana alike.
      const combat=frames.x.length>1&&frames.x.some((_,port)=>{
        if(frames.state[port][i]==null)return false
        const now=frames.pct?.[port]?.[i],before=frames.pct?.[port]?.[i-1]
        const state=frames.state[port][i],age=frames.age[port][i]
        // Lite followers have no percent channel. Nana's damage/guard/rebound
        // states still disclose the uncertain resolution; do not reject her
        // ordinary attacks merely because that optional channel is absent.
        return port<bundle.frames.x.length&&!Number.isFinite(now)||i&&before!=null&&now>before||
          [181,237,238].includes(state)||(state>=75&&state<=91&&(age<=1||state!==frames.pre_state?.[port]?.[i]))
      })
      if(!rng||combat)unavailable=Math.min(unavailable,i)
      else {
        // Cb2 precedes attack resolution. 801FAD84 creates materials in the
        // grI1_803E49B8 order (joint IDs, not ascending collision joint order).
        // All Item_80269C5C sparks run at priority 13; DmgReceived is priority
        // 14 (Item_8026A294). Never interleave a spark with its respawn draw.
        const order=[13,14,15,16,17,18,19,11,12,1,2,3,4,5,6,7,8,9,10]
        const ceiling=breaks.filter(h=>h.kind==='ceiling')
        const attacks=breaks.filter(h=>h.kind==='attack'&&!ceiling.some(c=>c.block===h.block))
        const unique=[...new Map(attacks.map(hit=>[hit.block,hit])).values()]
          .sort((a,b)=>order.indexOf(a.block+1)-order.indexOf(b.block+1))
        const destroy=hit=>{
          blocks[hit.block]=brokenBlock(n=>rng.int(n))
          for(let n=0;n<data.breakEffectDraws;n++)rng.float()
        }
        for(const entry of currentItems)for(let n=0;n<(entry.beforeCeilingDraws||0);n++)rng.float()
        for(const hit of ceiling)destroy(hit)
        for(const draws of tether.draws)for(let n=0;n<(draws||0);n++)rng.float()
        for(const draws of thunder.draws)for(let n=0;n<(draws||0);n++)rng.float()
        for(const entry of currentItems)for(let n=0;n<(entry.afterCeilingDraws||0);n++)rng.float()
        for(const hit of attacks){
          const draws=data.hitEffectDraws?.[hit.element]
          if(!Number.isInteger(draws)){unavailable=Math.min(unavailable,i);continue}
          for(let n=0;n<draws;n++)rng.float()
        }
        for(const hit of unique)destroy(hit)
        for(const entry of currentItems)entry.onMaterialResolved?.(rng)
      }
    }
    s=nextPulley
    priorItems=currentItems
    last=currentLines;rows.push(rowUncertain?null:last)
  }
  return {rows,unavailable,events}
}
export function simulationHistory(bundle) {
  let c=caches.get(bundle);if(!c){c=build(bundle);caches.set(bundle,c)}
  return c
}
export default function simulate(bundle,idx) {
  if (!data || !fighterDataReady(bundle) || !itemDataReady(bundle)) return null
  if(!supportedHistory(bundle,idx,19))return null
  const c=simulationHistory(bundle)
  if(idx>=c.unavailable||!c.rows[idx])return null
  return {lines:c.rows[idx].map(l=>l.slice()),replace:true,complete:true}
}

registerStageSimData(19, value => {
  data = value
  p=data.params
  centers=data.joints.slice(1,20).map(([start,n])=>{
    const vertices=data.initial.slice(start,start+n)
    return [vertices.reduce((sum,v)=>sum+v[0],0)/n,vertices.reduce((sum,v)=>sum+v[1],0)/n]
  })
})
