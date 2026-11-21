import { COLLISION_TIMING } from './collisionTiming.js'
export const { collisionLag } = COLLISION_TIMING[13]
import { registerStageSimData, fighterDataFor, fighterDataReady, fighterFrames, supportedFighterHistory } from '../stageData.js'
let data
import { frameCursor, setupCursor } from './rng.js'

// NTSC 1.02: grgreatbay.c. Numeric animation keys come from GrGb.dat.
// Turtle RNG is priority 4, before raft 1 and Tingle follower 10 (priority 5).
import { nextSeed as rngStep } from './rng.js'
export { rngStep }

export function supportedBundle(bundle, idx) {
  return !!bundle && Number.isInteger(idx) && idx >= 0 && idx < bundle.meta?.n
    && bundle.meta.start_frame === -123 && bundle.frames?.seed?.length > 0
    && bundle.frames.seed.every(s => s && s.length === bundle.meta.n && Number.isInteger(s[idx]) && s[idx] >= 0 && s[idx] <= 0xffffffff)
    && ['x','y','state','air'].every(k => bundle.frames[k]?.length === bundle.frames.seed.length
      && bundle.frames[k].every(a => a?.length === bundle.meta.n))
}

export function seedWindow(bundle, frame) {
  // Ground callbacks at priority 4, BEFORE fighter physics. The next frame
  // is not a bound (online resets); use this frame's final input hook instead.
  return frameCursor(bundle, frame - bundle.meta.start_frame)
}

// Decoded HSD FObj packets: [frame, opcode, value, tangent]. Opcodes 3/4/5
// use cubic Hermite interpolation; a tangent-only packet does not add a frame.
export function sampleTrack(keys, frame) {
  let p0 = 0, p1 = 0, d0 = 0, d1 = 0, t0 = 0, t1 = 0, last = 0, first = true
  for (const [time, op, value, tan] of keys) {
    if (op === 5) { d0 = d1; d1 = tan; last = op; continue }
    if (first) {
      p1 = value; d1 = tan || 0; t1 = time; last = op; first = false
      if (frame <= time) return p1
      continue
    }
    p0 = p1; p1 = value; t0 = t1; t1 = time
    if (op === 4) { d0 = d1; d1 = tan }
    else if (last !== 5) { d0 = d1; d1 = 0 }
    if (frame <= t1) {
      if (t1 === t0) return p1
      const u = (frame - t0) / (t1 - t0)
      if (last === 1 || last === 6) return p0
      if (last === 2) return p0 + (p1 - p0) * u
      return (2*u**3-3*u*u+1)*p0 + (u**3-2*u*u+u)*(t1-t0)*d0
        + (-2*u**3+3*u*u)*p1 + (u**3-u*u)*(t1-t0)*d1
    }
    last = op
  }
  return p1
}

function multiply(a, b) {
  const c = new Array(12)
  for (let r = 0; r < 3; r++) for (let k = 0; k < 4; k++) {
    c[r*4+k] = a[r*4]*b[k] + a[r*4+1]*b[4+k] + a[r*4+2]*b[8+k] + (k === 3 ? a[r*4+3] : 0)
  }
  return c
}

export function worldMatrices(table, group, anim, frame, { scale = table.scale, x = 0, y = 0, override } = {}) {
  const model = table.models[group], tracks = model.animations[anim]?.tracks || {}
  const matrices = [[scale,0,0,x, 0,scale,0,y, 0,0,scale,0]]
  for (let j = 0; j < model.nodes.length; j++) {
    const n = model.nodes[j], r = n.slice(1,4), s = n.slice(4,7), t = n.slice(7,10)
    for (const [kind, keys] of tracks[j+1] || []) {
      const v = sampleTrack(keys, frame)
      if (kind >= 1 && kind <= 3) r[kind-1] = v
      else if (kind >= 5 && kind <= 7) t[kind-5] = v
      else if (kind >= 8 && kind <= 10) s[kind-8] = v
    }
    override?.(j, r, s, t, n)
    const [cx,sx,cy,sy,cz,sz] = [Math.cos(r[0]),Math.sin(r[0]),Math.cos(r[1]),Math.sin(r[1]),Math.cos(r[2]),Math.sin(r[2])]
    const m = [cz*cy*s[0],(cz*sy*sx-sz*cx)*s[1],(cz*sy*cx+sz*sx)*s[2],t[0],
      sz*cy*s[0],(sz*sy*sx+cz*cx)*s[1],(sz*sy*cx-cz*sx)*s[2],t[1],
      -sy*s[0],cy*sx*s[1],cy*cx*s[2],t[2]]
    matrices.push(multiply(matrices[n[0]], m))
  }
  return matrices
}

export function transformJoint(table, vertices, joint, matrix) {
  const [start, n] = table.joints[joint]
  for (let i = start; i < start + n; i++) {
    const [x,y] = table.local[i]
    vertices[i] = [matrix[0]*x + matrix[1]*y + matrix[3], matrix[4]*x + matrix[5]*y + matrix[7]]
  }
}

export function dynamicKind(x0,y0,x1,y1) {
  const dx = x1-x0, dy = y1-y0
  if (dx > 0) return dy/dx > 1.7320508368950045 ? 8 : dy/dx < -1.7320508368950045 ? 4 : 1
  if (dx < 0) return dy/dx > 0.577350295784245 ? 4 : dy/dx < -0.577350295784245 ? 8 : 2
  return dy > 0 ? 8 : 4
}

export function collisionLines(table, vertices, active, dynamicStart = Infinity) {
  return table.lines.flatMap(([a,b], id) => {
    const j = table.joints.findIndex(([start,n]) => a >= start && a < start+n)
    if (!active[j]) return []
    const coords = [...vertices[a], ...vertices[b]]
    const flags = id >= dynamicStart ? (table.flags[id] & 256) | dynamicKind(...coords) : table.flags[id]
    return [[id,flags,...coords]]
  })
}

export function chooseDirection(rng, current, weights = data.params.directionWeights) {
  const total = weights.reduce((a,b) => a+b, 0)
  for (let i = 0; i <= 1001; i++) {
    let pick = rng.int(total)
    for (const [weight, direction] of [[weights[2],1],[weights[1],2],[weights[0],0],[weights[3],3]]) {
      pick -= weight
      if (pick < 0) { if (direction !== current) return direction; break }
    }
    if (!rng.valid) return null
  }
  return 0
}

// grGreatBay_801F60C4 -> 801F5E28. Kept separate from callback detection: x50
// is the integer common fighter weight. The adapter below reconstructs the
// preceding floor callback; contacts supply dx from the raft joint origin.
export function raftStep(previous, contacts) {
  const p = data.params.raft, f = Math.fround
  let tilt = 0, slide = 0, down = 0
  for (const contact of contacts) {
    const weight = contact.landed ? Math.trunc(f(contact.weight*p[0])) : contact.weight
    const t = Math.min(1,f(Math.abs(contact.dx)/15))
    const angle = f(t*f(.017453292*f(weight*p[1]+p[2])))
    const shift = f(t*f(weight*p[6]+p[7]))
    const sign = contact.dx < 0 ? 1 : -1
    tilt = Math.max(-p[3],Math.min(p[3],f(tilt+sign*angle)))
    slide = Math.max(-p[8],Math.min(p[8],f(slide+sign*shift)))
    down = Math.max(-p[13],f(down-f(weight*p[11]+p[12])))
  }
  const ease = (current,target,outward,inward) => {
    const delta = f(target-current), rate = -current*delta < 0 ? outward : inward
    return f(current+delta*rate)
  }
  return {tilt:ease(previous.tilt,tilt,p[4],p[5]),slide:ease(previous.slide,slide,p[9],p[10]),
    down:f(previous.down+f(down-previous.down)*(down-previous.down < 0 ? p[15] : p[14]))}
}

const caches = new WeakMap()
const range = (rng, bounds) => Math.min(...bounds) + rng.int(Math.abs(bounds[1]-bounds[0]))

// Turtle object 2 initializes before the raft and Tingle, drawing first from
// GameStart (grGreatBay_801F4240 / 801F4694). No event/timer hypothesis fitting.
function turtleCheckpoints(bundle, dive) {
  const end = bundle.meta.start_frame + bundle.meta.n - 1
  const events = [{ frame: -124, mode: 'idle', direction: 0, x: data.params.x + data.params.initialX }]
  let direction = 0, x = data.params.x + data.params.initialX
  for (let cycle = 0; cycle < 10000; cycle++) {
    events.push({frame:dive, mode:'dive', direction, x})
    const hidden = dive + 300
    if (hidden > end) return events
    const r = seedWindow(bundle, hidden)
    if (!r) return null
    const rebirth = range(r, data.params.rebirth)
    if (!r.valid) return null
    events.push({frame:hidden, mode:'hidden', direction, x})
    const rise = hidden + rebirth + 2
    if (rise > end) return events
    const pick = seedWindow(bundle, rise)
    if (!pick) return null
    direction = chooseDirection(pick, direction)
    if (direction === null || direction === 2) return null
    x = data.params.x + range(pick, direction === 0 ? data.params.sideX : data.params.frontX)
    if (!pick.valid) return null
    events.push({frame:rise, mode:'rise', direction, x})
    const idle = rise + 300
    if (idle > end) return events
    const waitRng = seedWindow(bundle, idle)
    if (!waitRng) return null
    const wait = range(waitRng, data.params.wait)
    if (!waitRng.valid) return null
    events.push({frame:idle, mode:'idle', direction, x})
    dive = idle + Math.ceil((wait + 2)/160)*160
  }
  return null
}

function eventAt(events, frame) {
  let lo = 0, hi = events.length
  while (lo + 1 < hi) { const mid = (lo+hi) >>> 1; if (events[mid].frame <= frame) lo = mid; else hi = mid }
  return events[lo]
}

function buildCache(bundle) {
  const candidates = []
  const init = setupCursor(bundle)
  if (init) {
    const wait = range(init, data.params.wait)
    const dive = -124 + Math.ceil((wait + 2) / 160) * 160
    const events = turtleCheckpoints(bundle, dive)
    if (events) candidates.push(events)
  }
  // Item weights are not fighter weights. Uncertified item contacts retain
  // the existing gate; leaders and followers use their own current cid.
  let unsupported = Infinity
  const raft = data.initial.slice(0,8)
  const bounds = [Math.min(...raft.map(p=>p[0]))-8,Math.max(...raft.map(p=>p[0]))+8,
    Math.min(...raft.map(p=>p[1]))-18,Math.max(...raft.map(p=>p[1]))+18]
  const nearRaft = (x,y) => x>bounds[0] && x<bounds[1] && y>bounds[2] && y<bounds[3]
  for (const item of bundle.items || []) if (item.t !== 221) for (let i=0;i<item.x.length;i++) {
    if (nearRaft(item.x[i],item.y[i])) { unsupported = Math.min(unsupported,item.f+i); break }
  }
  const frames=fighterFrames(bundle), raftRows=[]
  const table={...data,models:{raft:data.raftModel}},lastBone=data.raftModel.nodes.length-1
  let state={tilt:0,slide:0,down:0},previous=data.initial.map(v=>v.slice()),pivot=worldMatrices(table,'raft',0,0).at(-1)[3]
  for(let i=0;i<bundle.meta.n;i++){
    const lines=collisionLines(data,previous,[true]),contacts=[]
    for(let port=0;port<frames.x.length;port++){
      const t=i-1,x=frames.x[port]?.[t],y=frames.y[port]?.[t]
      if(t<0||frames.state[port]?.[t]==null||frames.state[port][t]<=10||frames.air[port]?.[t])continue
      // The raft has one isolated floor. mpLib_8004DD90_Floor keeps its
      // callback within .1 beyond an endpoint, using the endpoint's Y.
      if(!lines.some(([,flags,a,b,c,d])=>{
        const lo=Math.min(a,c),hi=Math.max(a,c),edgeX=Math.max(lo,Math.min(hi,x))
        return (flags&1)&&a!==c&&x>=lo-.1&&x<=hi+.1&&Math.abs(y-b-(d-b)*(edgeX-a)/(c-a))<.002
      }))continue
      const weight=fighterDataFor(frames.cid[port][t])?.weight
      if(!Number.isFinite(weight)){unsupported=Math.min(unsupported,i);continue}
      contacts.push({dx:x-pivot,weight:Math.trunc(weight),landed:t>0&&!!frames.air[port][t-1]})
    }
    state=raftStep(state,contacts)
    const matrix=worldMatrices(table,'raft',0,0,{override(j,r,s,t){
      if(j===lastBone){r[2]=state.tilt;t[0]+=state.slide;t[1]+=state.down}
    }}).at(-1)
    previous=data.initial.map(v=>v.slice());transformJoint(data,previous,0,matrix)
    pivot=matrix[3];raftRows.push(previous.slice(0,8))
  }
  return { candidates, unsupported, raftRows, tingle: (bundle.items || []).filter(t => t.t === 221) }
}

export default function simulate(bundle, idx) {
  if (!data || !fighterDataReady(bundle)) return null
  if (!supportedBundle(bundle,idx) || !supportedFighterHistory(bundle,idx,13)) return null
  let cache = caches.get(bundle)
  if (!cache) { cache = buildCache(bundle); caches.set(bundle,cache) }
  if (!cache.candidates.length) return null
  const frame = bundle.meta.start_frame + idx
  const states = cache.candidates.map(c => eventAt(c,frame)), event = states[0]
  if (states.some(s => JSON.stringify(s) !== JSON.stringify(event))) return null
  // The raft and Tingle fail closed on their own: an item contact near the
  // raft (unsupported from then on) or a missing/popped Tingle leaves that one
  // piece out (complete:false, so a fighter on it still leaves a ground mark)
  // while the turtle and the island stay exact.
  const raftKnown = idx < cache.unsupported
  const tingle = cache.tingle.find(t => idx >= t.f && idx < t.f+t.x.length)
  const ti = tingle ? idx-tingle.f : -1
  // Only unpopped states have been validated. Do not mistake a balloon burst
  // animation for an active floor while the internal item height is unknown.
  const tingleKnown = !!tingle && tingle.s[ti] <= 2
  const vertices = data.initial.map(p => p.slice())
  if (raftKnown) cache.raftRows[idx].forEach((v,i)=>{vertices[i]=v.slice()})
  const active = [raftKnown, false, false, false, false, tingleKnown, true, true]
  if (event.mode !== 'hidden' && !(event.mode === 'rise' && event.frame === frame)) {
    const anim = event.mode === 'idle' ? 0 : event.mode === 'dive' ? 1 : 2
    const time = event.mode === 'idle' ? (frame-event.frame)%160 : frame-event.frame
    const matrices = worldMatrices(data,1,anim,time,{
      scale:data.scale*data.params.scale, x:event.x,
      override(bone,r,s,t) {
        if (bone === 2) { t[1] *= data.params.verticalScale; if (event.direction === 0) r[1] = 0 }
        if (bone === 3 && event.direction !== 0) r[1] = event.direction === 1 ? Math.PI/2 : -Math.PI/2
      },
    })
    for (const [joint,bone] of [[1,2],[2,3],[3,38],[4,34]]) transformJoint(data,vertices,joint,matrices[bone+1])
    for (const [vertex,bone] of [[32,20],[23,18],[22,15],[29,16],[28,17],[27,19],[39,21]]) vertices[vertex] = [matrices[bone+1][3],matrices[bone+1][7]]
    if (event.direction === 0) active[2] = active[3] = active[4] = true
    else active[1] = true
  }
  // grGreatBay_801F5600 (grgreatbay.c:630-712) reads Tingle AFTER item physics
  // at priority 4, sets its root, and refreshes collision at priority 5. No
  // priority-5 RNG anchor is needed for this observed-item path. it_802EB5C8
  // initializes tincle.x50 once from bone 11 (ittincle.c:106-119); 802ECCA4
  // returns item.pos + that fixed Y offset (829-834). Slippi records items at
  // priority 15, so later item/map/damage state changes are not a priority-5
  // snapshot. The unpopped restriction above must not be dropped on that basis.
  if (tingleKnown) {
    const dx = tingle.x[ti]-43, dy = tingle.y[ti]-200
    for (let i = 50; i < 64; i++) vertices[i] = [data.initial[i][0]+dx,data.initial[i][1]+dy]
  }
  return { lines:collisionLines(data,vertices,active,68), replace:true, complete:raftKnown && tingleKnown }
}

registerStageSimData(13, value => {
  data = value
})
