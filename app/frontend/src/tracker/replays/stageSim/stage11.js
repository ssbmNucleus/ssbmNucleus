import { registerStageSimData, stageDataFor, fighterDataFor, fighterDataReady, fighterFrames, supportedFighterHistory as supportedHistory } from '../stageData.js'
import { sampleCollision } from './stage10.js'
import { worldMatrices, transformJoint, collisionLines, sampleTrack } from './stage13.js'
import { frameCursor } from './rng.js'

let data, p, rv, owners
const f=Math.fround
export function initialDonut(y){return {state:0,timer:0,home:y,y,speed:0,active:true}}
// Cb1 accepts fighters only. Contact must be continuous for the load phase;
// once shaking starts, stepping off no longer prevents the fall.
export function donutStep(previous,contact,bottom,randomInt) {
  const s={...previous}
  if(s.state===0 && contact){s.state=1;s.timer=0}
  switch(s.state) {
    case 1: if(!contact){s.state=0;s.timer=0}else if(s.timer>=p.x20)s.state=2;else s.timer++;break
    case 2:
      if(s.timer%p.x28===0) {
        if(typeof randomInt!=='function')throw new Error('Donut shake requires ordered RNG')
        const range=Math.trunc(f(100*f(p.x30-p.x2C)))
        s.y=f(s.home+f(p.x2C+f((range?randomInt(range):0)/100)))
      }
      if(s.timer>=p.x24){s.speed=0;s.state=3}s.timer++;break
    case 3:
      s.speed=Math.max(-p.x38,f(s.speed-p.x34));s.y=f(s.y+s.speed)
      if(s.y<=bottom){s.speed=0;s.active=false;s.timer=0;s.state=4}break
    case 4:
      if(s.timer>=p.x3C){s.y=s.home;s.active=true;s.timer=0;s.state=5}s.timer++;break
    case 5: if(s.timer>=p.x40){s.timer=0;s.state=0}s.timer++;break
  }
  return s
}

// 80200578 accumulates radial lever arm * min(weight,1000)/1000, ignoring
// distances <=4. Scroll and camera-bound visibility are composed below.
export function teeterLoads(contacts,cx,cy) {
  let left=0,right=0
  for(const {x,y,weight} of contacts){
    const distance=f(Math.hypot(f(cx-x),f(cy-y)))
    if(distance>4){const amount=f(distance*f(Math.min(1000,Math.trunc(weight))/1000));if(x>cx)right=f(right+amount);else left=f(left+amount)}
  }
  return {left,right,count:contacts.length}
}

// 8020071C. Angle/speed are degrees here; the joint write converts to radians.
export function teeterStep(previous,{left=0,right=0,count=0}={}) {
  const s={...previous},wrapped=f(Math.abs(s.angle)-360*Math.trunc(Math.abs(s.angle)/360))
  const returnToLevel=()=>{
    s.direction=s.angle<0?1:-1;s.speed=f(p.x8*s.direction)
    if(wrapped<=.2){s.speed=0;s.state=0}
  }
  if(s.state===0) {
    if(!count)returnToLevel()
    else {s.direction=left>right?1:-1;s.speed=Math.max(-p.x4,Math.min(p.x4,f(p.x0*f(left-right))))}
  }else if(s.state===1) {
    if(!s.timer){if(!count)returnToLevel();else s.state=0}
    else {s.timer--;s.speed=f(s.speed+f(.008*-s.direction));if(Math.abs(s.speed)<=f(.008))s.speed=0}
  }
  s.angle=f(s.angle+s.speed)
  return s
}

export function initialCarpet(){return {state:0,timer:0,active:true,running:false,reset:false}}
// 80200460 applies the preceding fighter Cb1, then 80200154 updates it.
// Blinking changes DObj visibility only; collision drops for ONE reset tick.
export function carpetStep(previous,contact,animationDone=false) {
  const s={...previous,reset:false}
  if(contact && [1,3,4].includes(s.state)){s.timer=0;s.state=2;s.running=true}
  switch(s.state) {
    case 0:s.active=true;s.timer=0;s.state=1;break
    case 2:
      if(!contact){s.timer=0;s.running=false;s.state=3}
      else if(animationDone){s.timer=0;s.state=5}
      break
    case 3:if(s.timer>=p.xC){s.timer=0;s.state=4}s.timer++;break
    case 4:
    case 5:
      if(s.timer>=(s.state===4?p.x10:p.x18)) {
        s.active=false;s.running=false;s.reset=true;s.state=0
      }
      s.timer++;break
  }
  return s
}

// HSD splArcLengthGetParameter and cubic spline evaluation.
export function cruiseSplinePoint(s,u){
 u=Math.max(0,Math.min(1,u));let seg=0,result=0
 if(u===1)result=1
 else if(u>0){
  while(s.segments[seg+1]<u)seg++
  if(s.type===0)result=(u-s.segments[seg])/(s.segments[seg+1]-s.segments[seg])
  else{
   let start=0,end=1,left=s.length*(u-s.segments[seg]);const c=s.polys[seg]
   const polynomial=t=>Math.sqrt(Math.max(0,c[0]*t**4+c[1]*t**3+c[2]*t*t+c[3]*t+c[4]))
   while(Math.abs(start-end)>=.00001){
    result=(start+end)/2;const dx=(result-start)/8;let middle=0
    for(let i=2,t=start+dx;i<=8;i++,t+=dx)middle+=(i%2?2:4)*polynomial(t)
    const integral=dx*(middle+polynomial(start)+polynomial(result))/3
    if(left<.00001+integral)end=result;else{start=result;left-=integral}
   }
  }
 }
 if(u===1)seg=s.n-2
 if(s.type===1){const cp=s.points.slice(seg*3,seg*3+4),a=result,b=1-a;return [0,1,2].map(k=>f(cp[0][k]*b**3+3*cp[1][k]*a*b*b+3*cp[2][k]*a*a*b+cp[3][k]*a**3))}
 if(s.type===2){const cp=s.points.slice(seg,seg+4),a=result,b=1-a,weights=[b*b*b/6,(4+3*a**3-6*a*a)/6,(3*(-(a**3)+a*a+a)+1)/6,a**3/6];return [0,1,2].map(k=>f(cp.reduce((v,p,j)=>v+p[k]*weights[j],0)))}
 throw Error('Unsupported spline '+s.type)
}


// grRCruise_801FFADC: animated camera/interest intersection and camera offset.
export function scroll(frame){
 const m=worldMatrices(data,3,0,frame,{override:(j,r,s,t)=>{
  for(const [kind,keys]of data.models['3'].animations[0].tracks[j+1]||[])if(kind===4){const sp=data.scrollSplines[j+1],q=cruiseSplinePoint(sp,sampleTrack(keys,frame));for(let k=0;k<3;k++)t[k]=q[k]*sp.scale[k]+sp.translate[k]}
 }})
 const a=m[3],b=m[4],z=a[11]/(b[11]-a[11]);return [(b[3]-a[3])*z-a[3]+2*data.points[148][0],(b[7]-a[7])*z-a[7]+2*data.points[148][1]-10]
}

export function cruiseFloorContact(frames,p,i,line,lines,neighbors=data.neighbors){
 if(i<0||frames.air[p][i]||frames.state[p][i]<=10||!(line[1]&1))return false
 const [,,a,b,c,d]=line,x=frames.x[p][i],y=frames.y[p][i]
 if(x<a-.002||x>c+.002){
  const side=x<a?0:1,[base,alternate]=[neighbors[line[0]][side],neighbors[line[0]][side+2]]
  const neighbor=lines.find(l=>l[0]===alternate),close=neighbor&&((side?c-neighbor[2]:a-neighbor[4])**2+(side?d-neighbor[3]:b-neighbor[5])**2)<4
  const next=close?neighbor:lines.find(l=>l[0]===base)
  if(next&&(next[1]&1))return false
 }
 // mpLib_8004DD90_Floor allows .1 past a disconnected endpoint and clamps x.
 const edgeX=Math.max(a,Math.min(c,x))
 return x>=a-.1&&x<=c+.1&&a!==c&&Math.abs(y-b-(d-b)*(edgeX-a)/(c-a))<.002
}

// grrcruise.c: visibility entries, donut callback order, and carpet roots.
const appear=[[6,4],[8,5],[16,10],[11,6],[12,7],[13,8],[14,9],[15,8]]
const bones=[32,41,42,43,44,45,46,47,48,33,34,35,36,37,38,39,40]
const owned=new Set([4,5,6,7,8,9,10,24,25,26,...Array.from({length:17},(_,i)=>27+i)])
const caches=new WeakMap()
function initialState(){
 return {next:0,previous:[],donuts:bones.map(j=>initialDonut(data.models['1'].nodes[j][8])),
  carpets:[0,1,2].map(()=>({...initialCarpet(),age:0,first:true})),
  teeter:{state:0,angle:0,speed:0,direction:0,timer:0},
  visibility:appear.map(()=>({state:0,age:0})),pivot:[0,0],unavailable:false}
}
function copyState(s){
 return {...s,donuts:s.donuts.map(x=>({...x})),carpets:s.carpets.map(x=>({...x})),
  visibility:s.visibility.map(x=>({...x})),teeter:{...s.teeter},pivot:s.pivot.slice()}
}

// Ground priority 4 consumes the preceding priority-6 fighter Cb1 latches.
// Donuts consume this frame's final input-tail cursor, in the array order
// above. 80201110's wind RNG runs AFTER the donut pass, never before it.
// Ready is source-derived: IfAll's ready animation ends at 85, with frame
// zero evaluated during creation; its priority-0 callback runs at index 84.
// Carpets install their Cb1 immediately and animate at priority 1, including
// FIRST_PLAY while the animation rate is zero. Their reset is one tick.
function advance(b,s,track){
 const i=s.next,frames=fighterFrames(b)
 if(s.unavailable){s.next++;return null}
 let {previous,donuts,carpets,teeter,visibility,pivot}=s
  const baked=sampleCollision(track,i-123);if(!baked){s.next++;s.previous=null;return null}
  const anchor=baked.lines.find(l=>l[0]===1),bakedShift=[anchor[2]-rv[0][0],anchor[3]-rv[0][1]],shift=scroll((i+1)%7200)
  const contact=j=>previous.some(l=>owners[l[0]]===j&&frames.x.some((_,p)=>cruiseFloorContact(frames,p,i-1,l,previous)))
  const rng=frameCursor(b,i)
  if(i>=data.readyEnd-1){
   donuts=donuts.map((donut,k)=>donutStep(donut,contact(bones[k]-5),data.points[150][1],n=>{if(!rng){s.unavailable=true;return 0}return rng.int(n)}))
   const loads=[]
   for(let p=0;p<frames.x.length;p++)if(previous.some(l=>owners[l[0]]===5&&cruiseFloorContact(frames,p,i-1,l,previous))){
    const weight=fighterDataFor(frames.cid[p][i-1])?.weight
    if(!Number.isFinite(weight))s.unavailable=true
    else loads.push({x:frames.x[p][i-1],y:frames.y[p][i-1],weight})
   }
   teeter=teeterStep(teeter,teeterLoads(loads,...pivot))
  }
  for(let k=0;k<3;k++){
   let s=carpets[k],c=contact(24+k)
   if(c&&[1,3,4].includes(s.state))s={...s,running:true}
   if(s.first)s.first=false;else if(s.running)s.age++
   s=carpetStep(s,c,s.age>=data.models['4'].animations[1].end)
   if(s.reset){s.age=0;s.first=true}
   carpets[k]=s
  }
  const vertices=data.initial.map(v=>v.slice()),clock=(i+1)%7200
  const m=worldMatrices(data,1,0,clock,{override:(j,r,s,t)=>{
   if(j===0){t[0]=shift[0]/data.scale;t[1]=shift[1]/data.scale}
   if(j===8)r[2]=f(.017453292*teeter.angle)
   const k=bones.indexOf(j);if(k>=0)t[1]=donuts[k].y
  }})
  pivot=[m[9][3],m[9][7]]
  const active=data.joints.map(()=>false)
  for(let k=0;k<appear.length;k++){
   const [bone,j]=appear[k],s=visibility[k],pos=m[bone+1],inside=pos[3]>=data.points[149][0]+20&&pos[3]<=data.points[150][0]-20&&pos[7]>=data.points[150][1]+20&&pos[7]<=data.points[149][1]-20
   if(i>=data.readyEnd-1){if(s.state===0&&inside){s.state=1;s.age=0}else if(s.state===1&&s.age++>=data.appearanceEnd)s.state=2;else if(s.state===2&&!inside){s.state=3;s.age=0}else if(s.state===3&&s.age++>=data.appearanceEnd)s.state=0}
   if(s.state)active[j]=true
  }
  for(let k=0;k<bones.length;k++)active[bones[k]-5]=donuts[k].active
  for(const j of owned)if(j<24||j>26)transformJoint(data,vertices,j,m[data.mapping[j][1]+1])
  for(let k=0;k<3;k++){
   const bone=[1,26,51][k]
   const m4=worldMatrices(data,4,0,(i+1)%60,{override:(j,r,s,t)=>{
    if(j===0){t[0]=shift[0]/data.scale;t[1]=shift[1]/data.scale}
    if(j===bone)for(const [kind,keys]of data.models['4'].animations[1].tracks[j+1]||[])if(kind===4){const sp=data.splines[j+1],q=cruiseSplinePoint(sp,sampleTrack(keys,carpets[k].age));for(let a=0;a<3;a++)t[a]=q[a]*sp.scale[a]+sp.translate[a]}
   }})
   transformJoint(data,vertices,24+k,m4[bone+1]);active[24+k]=carpets[k].active
  }
  const contactLines=collisionLines(data,vertices,active,118).filter(l=>l[0]<118||(l[1]&15)===1).map(l=>l[0]<118?l:[l[0],257,...l.slice(2)])
  previous=[...baked.lines.map(l=>[l[0],l[1]&15,...l.slice(2).map((v,k)=>v+shift[k%2]-bakedShift[k%2])]),...contactLines].sort((a,b)=>a[0]-b[0])
 Object.assign(s,{next:i+1,previous,donuts,carpets,teeter,visibility,pivot})
 return s.unavailable?null:{lines:previous,replace:true,complete:true}
}

// Checkpoints bound reverse-seek work without keeping every frame's geometry.
// The shared fighter cache supplies every vanilla weight, including Nana.
export default function simulate(bundle,idx){
 if(!data||!stageDataFor(11)?.collision||!supportedHistory(bundle,idx,11)||!fighterDataReady(bundle))return null
 let c=caches.get(bundle)
 if(!c){const s=initialState();c={state:s,checkpoints:new Map([[0,copyState(s)]]),result:null};caches.set(bundle,c)}
 if(idx<c.state.next-1){
  let key=Math.floor(idx/300)*300
  while(!c.checkpoints.has(key))key-=300
  c.state=copyState(c.checkpoints.get(key))
 }
 const track={...data.scrollBake,...stageDataFor(11).collision}
 while(c.state.next<=idx){
  c.result=advance(bundle,c.state,track)
  if(c.state.next%300===0)c.checkpoints.set(c.state.next,copyState(c.state))
 }
 return c.result?{...c.result,lines:c.result.lines.map(l=>l.slice())}:null
}

registerStageSimData(11,value=>{
 data=value;p=data.params
 const rest=worldMatrices(data,1,0,0)
 rv=data.initial.map(x=>x.slice());transformJoint(data,rv,0,rest[2])
 owners=data.lines.map(([v])=>data.joints.findIndex(([start,n])=>v>=start&&v<start+n))
})
