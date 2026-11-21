import { COLLISION_TIMING } from './collisionTiming.js'
export const { collisionLag } = COLLISION_TIMING[17]
import { registerStageSimData, fighterFrames, fighterDataFor, fighterIdsFor, supportedFighterHistory } from '../stageData.js'
let data
import { supportedBundle, collisionLines } from './stage13.js'
import { setupCursor, frameCursor } from './rng.js'
import { attackSpheres, sphereSweepHit, materialOccupancy } from './stage16.js'

// grgreens.c: 80214B58/80214FA8 fill the grid in row order. MapJoint IDs are
// allocated from the first free slot, NOT row*6+column once a block is spawned.
export const INITIAL_HEIGHTS = [4,3,2,2,3,4]
let cacheByBundle = new WeakMap()
const F = Math.fround
const centers = [-63.75,-56.25,-48.75,48.75,56.25,63.75]

export function chooseColumn(heights, rng) {
  const weights = heights.map(h => [40,20,10,5,1,0][h])
  const leftFull = weights.slice(0,3).includes(0), rightFull = weights.slice(3).includes(0)
  if (leftFull && rightFull) return -1
  const lo = leftFull ? 3 : 0, hi = rightFull ? 3 : 6
  let pick = rng.int(weights.slice(lo,hi).reduce((a,b) => a+b,0))
  for (let c = lo; c < hi; c++) { pick -= weights[c]; if (pick < 0) return c }
  return -1
}

export function fallingStep(block, floor) {
  if (block.settled) return block
  const speed = Math.min(5,Math.fround(block.speed+Math.fround(.02)))
  const y = Math.fround(block.y-speed)
  return y < floor ? {y:floor,speed,settled:true} : {y,speed,settled:false}
}

function buildCache(b){
 const f=fighterFrames(b),init=setupCursor(b),grid=Array(30).fill(null),bombs={}
 if(!init)return {rows:[],unknown:0,log:[]}
 for(const k of [18,12,13,6,7,8,0,1,2,23,16,17,9,10,11,3,4,5])bombs[k]=init.int(12)===0
 let next=0
 for(let k=0;k<30;k++)if(k in bombs)grid[k]={id:next++,y:-11.25+7.5*Math.floor(k/6),speed:0,state:3,bomb:bombs[k],hit:false}
 let timer=30+init.int(120)
 const rows=[],prev=f.x.map(()=>[]),log=[],hidden=[]
 const materials=(b.items||[]).filter(t=>t.t===160)
 let unknown=Infinity
 for(let i=0;i<b.meta.n;i++){
  if(i>=84){
   const rng=frameCursor(b,i)
   if(timer--<0){
    if(!rng){unknown=i;break}
    const heights=centers.map((_,c)=>{for(let r=4;r>=0;r--)if(grid[r*6+c])return r+1;return 0}),c=chooseColumn(heights,rng)
    if(c>=0){const taken=grid.filter(Boolean).map(b=>b.id);let id=0;while(taken.includes(id))id++;grid[heights[c]*6+c]={id,y:147.75,speed:0,state:1,bomb:rng.int(12)===0,hit:false}}
    timer=30+rng.int(120)
   }
   for(let k=0;k<30;k++){
    const block=grid[k],r=Math.floor(k/6),c=k%6
    if(!block||block.hit||block.state!==1)continue
    block.speed=Math.min(5,F(block.speed+F(.02)));block.y=F(block.y-block.speed)
    const below=grid[k-6]
    if(r&&below&&[1,2].includes(below.state)&&block.y-below.y<7.5){block.state=2;block.y=F(below.y+7.5)}
    if(block.y< -11.25+7.5*r){
     block.y=-11.25+7.5*r;block.state=3
     for(let j=k+6;j<30&&grid[j]?.state===2;j+=6){grid[j].y=-11.25+7.5*Math.floor(j/6);grid[j].state=3}
    }else for(let j=k+6;j<30&&grid[j]?.state===2;j+=6)grid[j].y=F(grid[j-6].y+7.5)
   }
   for(let k=0;k<30;k++)if(grid[k]?.hit&&!grid[k].bomb){
    log.push([i-123,'remove',grid[k].id]);grid[k]=null
    const c=k%6
    for(let r=1;r<5;r++)if([1,2].includes(grid[r*6+c]?.state)&&!grid[(r-1)*6+c]){
     for(let rr=r;rr<5;rr++)[grid[rr*6+c],grid[(rr-1)*6+c]]=[grid[(rr-1)*6+c],grid[rr*6+c]]
     if(grid[(r-1)*6+c]?.state===2)grid[(r-1)*6+c].state=1
     r=0
    }
    k=-1
   }
  }
  rows.push(grid.flatMap((block,k)=>block?[[block.id,k%6,block.y]]:[]))
  // ityaku records its incoming direction before invoking grGreens' one-hit
  // callback. Unlike HP-based materials, every accepted hit breaks a normal
  // block. An unchanged zero direction certifies no damage in this pass,
  // even when the attacking article fell outside Slippi's 15-item limit.
  const witnessed=grid.map((block,k)=>{
   if(!block)return false
   const match=materials.filter(t=>{
    const j=i-t.f
    return j>=0&&j<t.x.length&&Math.abs(t.x[j]-centers[k%6])<.0001&&Math.abs(t.y[j]-block.y)<.0001
   })
   if(match.length!==1)return false
   const t=match[0],j=i-t.f
   if(![0,1].includes(t.s?.[j])||![-1,0,1].includes(t.d?.[j]))return false
   if(t.d[j]!==0||t.s[j]===1){
    if(block.bomb)unknown=Math.min(unknown,i+1)
    else if(!block.hit){block.hit=true;log.push([i-123,'material-hit',block.id])}
   }
   return true
  })
  for(let port=0;port<f.x.length;port++){
   const state=f.state[port][i],age=f.age[port][i],x=f.x[port][i],y=f.y[port][i],cid=f.cid[port][i]
   if(i&& (state!==f.state[port][i-1]||age<f.age[port][i-1]||cid!==f.cid[port][i-1]))prev[port]=[]
   if(!Number.isFinite(x)||!Number.isFinite(y)){prev[port]=[];continue}
   // fn_80216DE4 sets x1_4 on any map contact. Only falling blocks consume
   // it; their contact-triggered break/explosion needs a separate adapter.
   for(let k=0;k<30;k++)if(grid[k]?.state===1&&materialOccupancy(f,port,i,centers[k%6],grid[k].y+3.75,3.75)!==false)unknown=Math.min(unknown,i+1)
   if(!(state>=44&&state<=69||state>=341||state>=94&&state<=143||[187,195,217,219,220,221,222,256,257].includes(state))){prev[port]=[];continue}
   const hits=attackSpheres(cid,state,age,x,y,f.dir?.[port]?.[i])
   if(!hits){
    if(grid.some((block,k)=>block&&Math.abs(x-centers[k%6])<45&&Math.abs(y-block.y-3.75)<45))unknown=Math.min(unknown,i+1)
    prev[port]=[];continue
   }
   for(let k=0;k<30;k++){
    const block=grid[k];if(!block||block.hit)continue
    if(hits.some(h=>sphereSweepHit(h,prev[port].find(p=>p.id===h.id&&p.group===h.group),centers[k%6],block.y+3.75,block.bomb?6.75:6))){
     block.hit=true;log.push([i-123,'hit',block.id,port,state,age,block.bomb]);if(block.bomb)unknown=Math.min(unknown,i+1)
    }
   }
   prev[port]=hits
  }
  // Stage material items fill Slippi's oldest-15 item limit. A special can
  // create an unrecorded article even when bundle.items contains none. Do
  // not mistake that absence for proof of no projectile damage.
  if(grid.filter(Boolean).length>=15)for(let port=0;port<f.x.length;port++){
   const cid=f.cid[port][i],state=f.state[port][i]
   // Picking up/throwing a common item also proves that a hidden article
   // exists. The oldest material objects can occupy all fifteen recorder
   // slots, so an empty item list does not identify the held kind or its
   // earlier position. Do not emit an undamaged grid through that history.
   if(state>=94&&state<=143){unknown=Math.min(unknown,i+1);continue}
   const article=(cid===10||cid===11)?[341,342,357,358].includes(state):
    !!fighterDataFor(cid)?.hitboxes?.[state]?.articleSpawns?.length||
    (state>=341&&![2,3,15,18,25,26].includes(cid))
   if(!article)continue
   const x=f.x[port][i],y=f.y[port][i],dir=f.dir?.[port]?.[i]
   if(!Number.isFinite(x)||!Number.isFinite(y))continue
   if((cid===10||cid===11)&&[341,342].includes(state)){
    // The unlaunched ice falls from root+18 and is launched horizontally.
    // Below the lowest block (including its hurt radius) it cannot return.
    if(y+18+3.1248>=-11.25+3.75-6.75)unknown=Math.min(unknown,i+1)
   }else if((cid===10||cid===11)&&[357,358].includes(state)){
    // CmdVar0 enables at animation 15; accessory4 first emits on 16 and
    // disables at 60. Considering every eligible age bounds its timer.
    if(f.age[port][i]<=15||f.age[port][i]>60)continue
    const pose=data.climbersArticles?.launches[cid]?.[state]?.[f.age[port][i]]
    // cmd_var3 selects either zero or floor-normal rotation of TopN. Keep
    // both source possibilities; fp.parts[26]'s offset rotates with it.
    const floors=collisionLines(data,data.initial,Array.from({length:31},(_,j)=>j===30)).filter(l=>(l[1]&15)===1&&x>=l[2]-.1&&x<=l[4]+.1&&Math.abs(y-(l[3]+(Math.max(l[2],Math.min(l[4],x))-l[2])*(l[5]-l[3])/(l[4]-l[2])))<.002)
    const onBlock=grid.some((block,k)=>block&&Math.abs(x-centers[k%6])<=3.85&&Math.abs(y-block.y-7.5)<.002)
    if(!pose||![1,-1].includes(dir)||(!f.air[port][i]&&!floors.length&&!onBlock))unknown=Math.min(unknown,i+1)
    else for(const angle of [0,...floors.map(l=>Math.atan2(l[5]-l[3],l[4]-l[2]))]){
     const c=Math.cos(angle),s=Math.sin(angle),dx=dir*pose[0],dy=pose[1]
     hidden.push({i,x:x+c*dx-s*dy,y:y+s*dx+c*dy,dir})
    }
   }else unknown=Math.min(unknown,i+1)
  }
  const a=data.climbersArticles?.blizzard
  if(a)for(let h=hidden.length-1;h>=0;h--){
   const shot=hidden[h],age=i-shot.i
   if(age>a[0]){hidden.splice(h,1);continue}
   // All possible source angles, with one extra physics pass to contain
   // accessory4/item scheduling. Evaluate each age separately so a late
   // high point is not combined with an early horizontal position.
   const speed=a[1],gravity=a[2],lo=a[3]-Math.PI/2,hi=a[4]-Math.PI/2
   for(const n of [age,age+1]){
    const dx0=n*speed*Math.min(Math.cos(lo),Math.cos(hi)),dx1=n*speed
    const x0=shot.x+(shot.dir===1?dx0:-dx1)-.002,x1=shot.x+(shot.dir===1?dx1:-dx0)+.002
    const y0=shot.y+n*speed*Math.sin(lo)+gravity*n*(n+1)/2-.002
    const y1=shot.y+n*speed*Math.sin(hi)+gravity*n*(n+1)/2+.002
    if(grid.some((block,k)=>{
     if(!block||block.hit||witnessed[k])return false
     const dx=Math.max(x0-centers[k%6],0,centers[k%6]-x1),cy=block.y+3.75,dy=Math.max(y0-cy,0,cy-y1)
     return dx*dx+dy*dy<=(4.6872+(block.bomb?6.75:6))**2
    }))unknown=Math.min(unknown,i+1)
   }
  }
  for(const item of b.items||[]){
   const j=i-item.f
   if(item.t===160||j<0||j>=item.x.length)continue
   // Exact vanilla root-centered maximum hit radii: PlPp ice / Blizzard;
   // GrGr apple (including its state-7 explosion). These bounds certify
   // misses only; an intersection still needs item map/damage ordering.
   const radius=({106:3.1248,107:4.6872,225:7.812,226:7.812})[item.t]
   if(radius==null){unknown=Math.min(unknown,i+1);continue}
   const hit={x:item.x[j],y:item.y[j],z:0,radius}
   const previous=j?{x:item.x[j-1],y:item.y[j-1],z:0}:hit
   if(grid.some((block,k)=>block&&!witnessed[k]&&sphereSweepHit(hit,previous,centers[k%6],block.y+3.75,block.bomb?6.75:6)))unknown=Math.min(unknown,i+1)
  }
  if(i>=unknown)break
 }
 return {rows,unknown,log}
}

// Rebuild after a lazy fighter table arrives; a cached unavailable prefix
// must not permanently mask newly available Nana/transform animations.
export function blockHistory(bundle) {
 const tables=fighterIdsFor(bundle).map(fighterDataFor)
 let cache=cacheByBundle.get(bundle)
 if(!cache||cache.tables.some((t,i)=>t!==tables[i])||cache.tables.length!==tables.length){
  cache={...buildCache(bundle),tables};cacheByBundle.set(bundle,cache)
 }
 return cache
}

export default function simulate(bundle,idx) {
 if(!data||!supportedBundle(bundle,idx)||!supportedFighterHistory(bundle,idx,17))return null
 const cache=blockHistory(bundle)
 if(idx>=cache.unknown||!cache.rows[idx])return null
 const vertices=data.initial.map(p=>p.slice()),active=Array(31).fill(false);active[30]=true
 for(const [id,column,y]of cache.rows[idx]){
  active[id]=true
  for(let j=id*4;j<id*4+4;j++)vertices[j]=[centers[column]+data.local[j][0]*data.scale,y+data.local[j][1]*data.scale]
 }
 return {lines:collisionLines(data,vertices,active),replace:true,complete:true}
}

registerStageSimData(17, value => {
  data = value
  cacheByBundle = new WeakMap()
})
