import { COLLISION_TIMING } from './collisionTiming.js'
export const { collisionLag } = COLLISION_TIMING[18]
import { registerStageSimData, fighterFrames, supportedFighterHistory } from '../stageData.js'
let data
import { supportedBundle, seedWindow, worldMatrices, transformJoint, collisionLines } from './stage13.js'
import { setupCursor } from './rng.js'

const f32 = Math.fround
let p
let originalY
const caches = new WeakMap()
const STRIDE = 120

export function initialCrane(wait) {
  return {state:0,timer:wait,side:0,y:originalY,target:originalY,speed:0,accel:0,amplitude:0,phase:0,rate:0,pending:null}
}

// grFourside_UpdateCrane, including the asymmetric upward overshoot and the
// acceleration doubling on each crossing. Animation advances at priority 1,
// before this priority-4 proc, and ReqAnim doesn't immediately apply frame 0.
export function craneStep(previous, randomInt) {
  const s = {...previous}
  if (s.rate) { s.phase = s.pending ?? s.phase+1; s.pending = null }
  switch (s.state) {
    case 0:
      if (s.timer <= 0) { s.pending = s.side ? 400 : 0; s.rate = 1; s.timer = 0; s.state = s.side ? 2 : 1 }
      else s.timer--
      break
    case 1: case 2:
      if (s.timer >= 300) { s.rate = 0; s.side = s.state === 1 ? 1 : 0; s.state = 3 }
      else s.timer++
      break
    case 3: s.timer = p[5]+randomInt(p[6]); s.state = 4; break
    case 4:
      if (s.timer <= 0) {
        if (s.y > originalY) { s.target = f32(originalY-Math.abs(p[9])-randomInt(Math.trunc(Math.abs(p[10]-p[9])))); s.state = 5 }
        else { s.target = f32(originalY+Math.abs(p[7])+randomInt(Math.trunc(Math.abs(p[8]-p[7])))); s.state = 6 }
      } else s.timer--
      break
    case 5: case 6: {
      const down = s.state === 5
      s.y = f32(s.y+(down ? -p[11] : p[11]))
      if (down ? s.y <= s.target : s.y >= s.target) {
        if (down) s.y = s.target
        s.speed = s.amplitude = p[11]; s.accel = p[12]; s.state = 7
      }
      break
    }
    case 7:
      if (Math.abs(s.accel) > s.amplitude) {
        s.y = s.target; s.timer = p[3]+randomInt(p[4]); s.state = 0
      } else {
        s.speed = f32(s.speed+s.accel); s.y = f32(s.y+s.speed)
        if (s.accel < 0 && s.y < s.target) s.accel = f32(s.accel*-2)
        if (s.accel > 0 && s.y > s.target) s.accel = f32(s.accel*-2)
      }
      break
  }
  return s
}

function runCrane(bundle, wait) {
  let state = initialCrane(wait)
  const checkpoints = new Map([[-124,state]])
  const end = bundle.meta.start_frame+bundle.meta.n-1
  for (let frame = -123; frame <= end; frame++) {
    let rng, needed = false
    state = craneStep(state,n => { needed = true; rng ||= seedWindow(bundle,frame); return rng ? rng.int(n) : NaN })
    if (needed && (!rng || !rng.valid)) return null
    if ((frame+124)%STRIDE === 0) checkpoints.set(frame,state)
  }
  return {wait,checkpoints}
}

function craneAt(bundle, candidate, frame) {
  const before = -124+Math.floor((frame+124)/STRIDE)*STRIDE
  let checkpoint = before
  while (!candidate.checkpoints.has(checkpoint) && checkpoint > -124) checkpoint -= STRIDE
  let s = candidate.checkpoints.get(checkpoint)
  for (let f = checkpoint+1; f <= frame; f++) {
    let rng
    s = craneStep(s,n => { rng ||= seedWindow(bundle,f); return rng ? rng.int(n) : NaN })
    if ((rng && !rng.valid) || !Number.isFinite(s.y)) return null
  }
  return s
}

export function touchesCenter(bundle, frame) {
  const frames = fighterFrames(bundle)
  const idx = frame-bundle.meta.start_frame
  if (idx < 0 || idx >= bundle.meta.n) return false
  for (let port = 0; port < frames.x.length; port++) {
    if (frames.air[port][idx]) continue
    const x = frames.x[port][idx], y = frames.y[port][idx]
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue
    for (let id = 0; id <= 5; id++) {
      const [a,b] = data.lines[id], [x0,y0] = data.initial[a], [x1,y1] = data.initial[b]
      if (x >= Math.min(x0,x1) && x <= Math.max(x0,x1) && Math.abs(y-(y0+(y1-y0)*(x-x0)/(x1-x0))) < .1) return true
    }
  }
  return false
}

// grfourside.c:652-762. Helicopter 3 runs after crane 1 and before UFO 5.
// Its camera threshold is a fixed DAT stage bound, not the live camera view.
// The stay is in animation 0 itself; heli_stay_time is unused by this callback.
export function initialHelicopter(wait) {
  return {state:0,timer:wait,seen:false,animation:0,age:0}
}
export function helicopterStep(previous, ufo, rng) {
  const h = {...previous}
  if (h.state) h.age++
  const blocked = ufo.state !== 0 && ufo.building !== 2
  switch (h.state) {
    case 0:
      if (h.timer > 0) h.timer--
      else if (!blocked) { h.state=1; h.seen=false; h.animation=0; h.age=0 }
      break
    case 1:
      if (!h.seen) h.seen = worldMatrices(data,3,0,h.age)[3][7] <= data.cameraTop+50
      if (h.age >= data.models[3].animations[0].end) h.state=2
      break
    case 2:
      if (h.timer > 0) h.timer--
      else if (!blocked) { h.state=3; h.animation=2; h.age=0; h.timer=0 }
      break
    case 3:
      if (h.age >= data.models[3].animations[2].end) {
        h.state=0; h.timer=p[0]+(p[1] ? rng.int(p[1]) : 0)
      }
      h.timer++
      break
  }
  return h
}
export const helicopterBlocksUfo = h => (h.state === 1 && !h.seen) || (h.state === 3 && h.timer <= 700)

// One shared current-frame cursor: crane -> helicopter -> UFO. No future
// seed-distance pruning and no guesses about arbitration are necessary.
function ufoEvents(bundle, crane, helicopterWait) {
  let state = 0, timer = p[13], challenge = 0, previous = -1, anim = 0, phase = 0
  const events = [{frame:-124,visible:false,anim:0,phase:0}]
  let helicopter = initialHelicopter(helicopterWait)
  const end = bundle.meta.start_frame+bundle.meta.n-1
  for (let frame = -123; frame <= end; frame++) {
    if (state) phase++
    let rng, needed = false
    const random = n => {
      needed = true
      rng ||= seedWindow(bundle,frame)
      return rng ? rng.int(n) : NaN
    }
    const before = craneAt(bundle,crane,frame-1)
    if (!before) return null
    craneStep(before,random)
    helicopter = helicopterStep(helicopter,{state,building:previous},{int:random})
    if (state === 0) {
      if (timer <= 0) {
        // Fighter map callbacks are priority 6, AFTER this proc; x8 is the
        // preceding frame's contact accumulator (801F30A0 / 801F3894).
        let probability = touchesCenter(bundle,frame-1) ? p[18] : 0
        if (challenge >= p[17]) probability = p[19]
        if (probability && random(probability) === 0) {
          challenge = 0
          let building, draws = 0
          do { building = random(3); draws++ } while (building === previous && draws < 1002)
          const allowed = building === 2 || !helicopterBlocksUfo(helicopter)
          if (allowed) {
            previous = building; anim = building*4; phase = 0; state = 1
            events.push({frame,visible:true,anim,phase:0})
          }
        } else { timer = p[13]; challenge++ }
      } else timer--
    } else if (state === 1) {
      if (phase >= data.models[5].animations[anim].end) {
        timer = p[15]+random(p[16]); anim = previous*4+1; phase = 0; state = 2
        events.push({frame,visible:true,anim,phase:0})
      }
    } else if (state === 2) {
      const endFrame = data.models[5].animations[anim].end
      const looped = phase >= endFrame
      if (looped) phase %= endFrame
      if (timer <= 0) {
        if (looped) { anim = previous*4+2; phase = 0; state = 4; events.push({frame,visible:true,anim,phase:0}) }
      } else timer--
    } else if (state === 4) {
      if (timer >= 60) { state = 0; timer = p[13]; events.push({frame,visible:false,anim,phase:0}) }
      else timer++
    }
    if (needed && !rng) return null
  }
  return {events,arbitration:[]}
}

export function ufoCheckpoints(bundle, crane) {
  const init = setupCursor(bundle)
  if (!init) return []
  if (p[4]) init.int(p[4]) // crane initialization precedes helicopter
  const result = ufoEvents(bundle,crane,p[0]+(p[1] ? init.int(p[1]) : 0))
  return result ? [result] : []
}

function buildCache(bundle) {
  const cranes = []
  // Crane 1 initializes before helicopter 3 and UFO 5 (801F2D10).
  const init = setupCursor(bundle)
  if (init) {
    const wait = p[3] + (p[4] ? init.int(p[4]) : 0)
    const candidate = runCrane(bundle,wait)
    if (candidate) cranes.push(candidate)
  }
  return {cranes,ufos:cranes.length === 1 ? ufoCheckpoints(bundle,cranes[0]) : []}
}

export default function simulate(bundle,idx) {
  if (!data) return null
  if (!supportedBundle(bundle,idx) || !supportedFighterHistory(bundle,idx,18)) return null
  let cache = caches.get(bundle)
  if (!cache) { cache = buildCache(bundle); caches.set(bundle,cache) }
  if (!cache.cranes.length) return null
  const frame = bundle.meta.start_frame+idx
  const cranes = cache.cranes.map(c=>craneAt(bundle,c,frame)), crane = cranes[0]
  if (!crane || cranes.some(c => !c || c.phase !== crane.phase || c.y !== crane.y)) return null
  if (!cache.ufos.length) return null
  const vertices = data.initial.map(v=>v.slice())
  const matrices = worldMatrices(data,1,0,Math.max(0,crane.phase),{
    override(bone,r,s,t) { if (bone === 4) t[1] = crane.y },
  })
  transformJoint(data,vertices,3,matrices[8])
  const states = cache.ufos.map(({events}) => {
    let lo = 0, hi = events.length
    while (lo+1 < hi) { const mid = (lo+hi)>>>1; if (events[mid].frame <= frame) lo = mid; else hi = mid }
    return events[lo]
  })
  const ufo = states[0]
  if (states.some(s => s.visible !== ufo.visible || (s.visible && (s.anim !== ufo.anim || s.frame !== ufo.frame)))) return null
  if (ufo.visible) {
    let phase = frame-ufo.frame
    if (ufo.anim%4 === 1) phase %= data.models[5].animations[ufo.anim].end
    const matrices = worldMatrices(data,5,ufo.anim,phase)
    transformJoint(data,vertices,4,matrices[2])
  }
  return {lines:collisionLines(data,vertices,[true,true,true,true,ufo.visible]),replace:true,complete:true}
}

registerStageSimData(18, value => {
  data = value
  p = data.params
  originalY = f32(data.models[1].nodes[4][8]-10)
})
