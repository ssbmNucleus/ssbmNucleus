import { COLLISION_TIMING } from './collisionTiming.js'
export const { collisionLag } = COLLISION_TIMING[24]
// Big Blue: road, four car lanes, three small platforms, flyer and route
// platform. The priority-4 pass shares one RNG cursor in source creation order.
// C22 validates full-stage geometry on all four paired captures. Common-item
// pools and uncertified ledge contacts fail closed.

import { nextSeed, setupCursor, frameCursor } from './rng.js'
export { nextSeed, setupCursor, frameCursor }
// grBigBlue_801E59F8 registers every controller at priority 4. OnInit creates
// 31,0,1,2,34(road),33(cars),32,35(platform),36 in that order. Integration must
// pass ONE setupCursor through their initializers and ONE frameCursor through
// their callbacks; advanceStage implements that pipeline below.

function rangedInt(a, b, rng) {
  const lo = Math.min(Math.trunc(a), Math.trunc(b))
  const span = Math.abs(Math.trunc(a) - Math.trunc(b))
  return lo + (span ? rng.int(span) : 0)
}

// grBigBlue_801EC6C0 and its inline spawn, then the timer in 801E6364.
// params are the numeric yakumono x-fields, extracted independently from DAT.
// Caller must provide the seed AT THE START OF INITIALIZATION. It is earlier
// than frames.seed[0][0]; deriveFromSlp v5 preserves it as meta.start_seed.
export function initializeCars(rng, params, stageScale) {
  const f = Math.fround
  const ranks = Array.from({ length: 30 }, () => rng.int(2) ? 0 : 2)
  const count = params.x18 || 1
  const cars = []
  for (let i = 0; i < 4; i++) {
    if (i >= count) { cars.push({ state: 1 }); continue }
    let slot, attempts = 0
    do {
      if (++attempts > 10000) throw new Error('Car slot rejection loop did not terminate')
      slot = rng.int(30)
    } while (cars.some(car => car.slot === slot))
    const width = f(params.x1C * stageScale)
    const x = f(f((i + 1) * f(width / (count + 1))) + f(-width * 0.5))
    const y = f(f(params.x0 * stageScale) + f(params.x2C * stageScale))
    const phase = f(2 * Math.PI * rng.float())
    const threshold = rangedInt(params.x5C, params.x60, rng)
    const sound = rng.int(4) // Sound choice does not move collision, but consumes the shared stream.
    cars.push({ state: 4, slot, joint: slot + 3, direction: 0, x, y, z: 0,
      target: x, delta: 0, gravity: 0, height: 0, velocity: 0, accel: 0,
      phase, amplitude: f(params.x34 * stageScale), angularVelocity: 0,
      threshold, sound, alpha: 1 })
    ranks[slot] = 1
  }
  const spawnTimer = rangedInt(params.x10, params.x14, rng)
  return { ranks, cars, spawnTimer }
}

// 801ECB50's pool balancing, before counting active cars/spawning.
export function balanceCarPool(ranks, rng) {
  const free = ranks.filter(rank => rank === 0).length
  const reserved = ranks.filter(rank => rank === 2).length
  const source = free === 0 ? 2 : reserved === 0 ? 0 : null
  if (source === null) return
  const count = source === 2 ? reserved : free
  let pick = count ? rng.int(count) : 0
  for (let i = 0; i < ranks.length; i++) {
    if (ranks[i] === source && --pick < 0) {
      ranks[i] = source === 2 ? 0 : 2
      break
    }
  }
}

// Pure selection part of 801EB4AC. The geometry integrator must perform the
// current/next promotion and root rebase first, then supply these quantities.
// spY is the promoted jobj's WORLD y before rebasing; roadY is root position.y.
// deltaY entries have already been multiplied by Ground_801C0498().
export function chooseRoad({ current, direction, roadY, spY, restricted = false }, deltaY, params, scale, rng) {
  const f = Math.fround
  const lower = f(params.x4 * scale), upper = f(params.x8 * scale)
  if (direction === 1) {
    if (roadY < f(upper * 0.25)) direction = 0
  } else if (direction === -1) {
    if (roadY > f(-lower * 0.25)) direction = 0
  } else if (roadY < -lower) direction = -1
  else if (roadY > upper) direction = 1
  for (let n = 0; n <= 1000; n++) {
    const lane = rng.int(12)
    if (lane === 11 && roadY < -700) continue
    if (lane === current) continue
    if (restricted) {
      if (lane > 1 && lane !== 4) continue
    } else {
      if (direction === 1 && deltaY[lane] < 0) continue
      if (direction === -1 && deltaY[lane] > 0) continue
      if (f(f(spY + deltaY[current]) + deltaY[lane]) < f(upper + roadY)) continue
    }
    return { lane, direction }
  }
  throw new Error('grBigBlue_801EB4AC exceeded 1001 route candidates')
}

// Route 11's loop changes collision membership as the road rolls over.
export function advanceLoopPhase(phase, rotation) {
  if (phase === 0) return { phase: 1, enabled: [], disabled: [] }
  if (phase === 1) return { phase: 2, enabled: [41, 42, 43], disabled: [44, 45, 46, 47, 48] }
  if (phase === 2 && rotation < Math.fround(-0.5235988)) {
    return { phase: 3, enabled: [44, 45, 46], disabled: [] }
  }
  if (phase === 3 && rotation < Math.fround(-2.7925267)) {
    return { phase: 4, enabled: [47, 48, 49], disabled: [41, 42, 43] }
  }
  return { phase, enabled: [], disabled: [] }
}

// grBigBlue_801EC58C probes floor segments through mpCheckFloor. The latter
// extends linked endpoints (mpLib_8004ED5C) BEFORE intersecting the vertical
// ray. Interpolating the unextended segment misses seam contacts and changes
// the road's fall/recovery branch.
// prev/next are the original MapLine neighbor IDs, with -1 meaning no link.
export function probeRoadSegment(line, prev, next, top, bottom, rayX = 0) {
  const f = Math.fround
  let [, flags, x, y, endX, endY] = line
  if ((flags & 15) !== 1 || top < bottom) return null
  let distance
  const length = () => f(Math.sqrt(f(f(f(x - endX) ** 2) + f(f(y - endY) ** 2))))
  if (prev !== -1) {
    distance = length()
    if (distance > f(.001)) {
      x = f(x + f(f(x - endX) / distance))
      y = f(y + f(f(y - endY) / distance))
    }
  }
  if (next !== -1) {
    distance ??= length()
    if (distance > f(.001)) {
      // The second extension uses the already extended first endpoint and
      // the original length. Replacing this with symmetric padding differs.
      endX = f(endX + f(f(endX - x) / distance))
      endY = f(endY + f(f(endY - y) / distance))
    }
  }
  if (rayX < Math.min(x, endX) || rayX > Math.max(x, endX)) return null
  if (Math.abs(f(y - endY)) <= .0001) {
    if (x >= endX) return null // mpLineIntersectionH rejects downward rays on reversed floors.
    if (f(top - y) < -.0001 || f(bottom - y) > .0001 || Math.abs(f(bottom - top)) < .0001) return null
    return { y, normal: [0, 1] }
  }
  if (top < Math.min(y, endY) || bottom > Math.max(y, endY)) return null
  const height = f(endY - y), width = f(endX - x)
  const d0x = f(rayX-x), d0y = f(top - y), d1x = f(rayX-endX), d1y = f(bottom - endY)
  const side0 = width * d0y - height * d0x, side1 = width * d1y - height * d1x
  if (side0 < -.1 || side1 > .1 || (side0 === 0 && side1 === 0)) return null
  const determinant = d0x * d1y - d0y * d1x
  if ((determinant < side0 && determinant < side1) || (determinant > side0 && determinant > side1)) return null
  // mpLineIntersection rejects a ray whose end remains above this floor.
  if (side1 > 0) return null
  const rayHeight = f(bottom - top), area = -rayHeight * width
  if (Math.abs(area) <= f(.0001)) return null
  const t = -rayHeight * d0x / area
  const hitY = t <= 0 ? y : t >= 1 ? endY : f(height * t + y)
  return { y: hitY, normal: nativeNormal(-height, width) }
}

const f32 = Math.fround
// Gekko frsqrte hardware lookup values, documented by Dolphin FloatUtils.cpp.
// PSVECNormalize performs one single-precision Newton step, not 1 / sqrt(x).
const rsqrtTable = [
  [0x1a7e800,-0x568],[0x17cb800,-0x4f3],[0x1552800,-0x48d],[0x130c000,-0x435],
  [0x10f2000,-0x3e7],[0x0eff000,-0x3a2],[0x0d2e000,-0x365],[0x0b7c000,-0x32e],
  [0x09e5000,-0x2fc],[0x0867000,-0x2d0],[0x06ff000,-0x2a8],[0x05ab800,-0x283],
  [0x046a000,-0x261],[0x0339800,-0x243],[0x0218800,-0x226],[0x0105800,-0x20b],
  [0x3ffa000,-0x7a4],[0x3c29000,-0x700],[0x38aa000,-0x670],[0x3572000,-0x5f2],
  [0x3279000,-0x584],[0x2fb7000,-0x524],[0x2d26000,-0x4cc],[0x2ac0000,-0x47e],
  [0x2881000,-0x43a],[0x2665000,-0x3fa],[0x2468000,-0x3c2],[0x2287000,-0x38e],
  [0x20c1000,-0x35e],[0x1f12000,-0x332],[0x1d79000,-0x30a],[0x1bf4000,-0x2e6],
]
const floatBits = new DataView(new ArrayBuffer(8))
function nativeNormal(x,y) {
  const sum=f32(f32(x*x)+f32(y*y))
  floatBits.setFloat64(0,sum)
  const hi=floatBits.getUint32(0),e=(hi>>>20)&2047,i=((e&1)<<15)|((hi&0xfffff)>>>5)
  const [base,step]=rsqrtTable[i>>>11],mant=base+step*(i&2047),scale=2**(Math.floor(1023-(e-1022)/2)-1023)
  const estimate=scale*(1+mant/67108864),rounded=scale*(1+Math.round(mant/4)*4/67108864)
  const inverse=f32(f32(3-f32(estimate*rounded)*sum)*f32(estimate*.5))
  return [f32(x*inverse),f32(y*inverse)]
}
// MSL/trigf.c and lb/lbtrigf.c. Native float polynomial evaluation matters at
// the road's seam probes: Math.sin/cos/atan2 can pick a different loop normal.
const sincosQuadrants = [0, 1, 1, 0, 0, -1, -1, 0]
const sincosPoly = [0.0000035287617, 0.0000003089747, -0.0003259365,
  -0.00003657235, 0.015854323, 0.0024903931, -0.30842513,
  -0.08074551, 1, 0.7853982].map(f32)
const fourOverPiMinusOne = [0.25, 0.0232393741608, 1.70555722434e-7,
  1.86736494323e-11].map(f32)
const atanTable = [1, -0.3333333134651184, 0.1999988704919815,
  -0.14281649887561798, 0.11041180044412613, -0.08459755778312683,
  0.04714243486523628, 6.828420162200928, 3.239828109741211, 2,
  1.4464620351791382, 1.1715729236602783, 1.039566159248352,
  7.1350000325764995e-6, 8.200000252145401e-7, 0, 6.299999881775875e-7,
  0, 0, 0, 0.3926900029182434, 0.5890486240386963, 0.7853981256484985,
  0.9817469716072083, 1.1780970096588135, 1.3744460344314575, 0,
  9.081698408408556e-6, 2.3000000126671694e-8, 6.30000016599297e-8,
  7.040000014058023e-7, 2.499999993688107e-7, 7.900000014160469e-7,
  2.414212942123413, 1.4966057538986206, 1, 0.6681786179542542,
  0.4142135679721832, 0.1989123672246933, 5.620000251838064e-7, 0, 0, 0, 0, 0, 0]

function reduceAngle(x) {
  const z = f32(f32(2 / f32(Math.PI)) * x)
  const n = Math.trunc(f32(z + (x < 0 || Object.is(x, -0) ? -0.5 : 0.5)))
  let y = f32(x - n * 2)
  for (const c of fourOverPiMinusOne) y = f32(c * x + y)
  return [n & 3, y]
}

function nativeSin(x) {
  const [n, y] = reduceAngle(x)
  if (Math.abs(y) < f32(3.45266983e-4)) {
    return f32(sincosQuadrants[n * 2] + f32(f32(sincosQuadrants[n * 2 + 1] * y) * sincosPoly[9]))
  }
  const yy = f32(y * y)
  let z = sincosPoly[n & 1 ? 0 : 1]
  for (let i = n & 1 ? 2 : 3; i < 10; i += 2) z = f32(z * yy + sincosPoly[i])
  return n & 1 ? f32(z * sincosQuadrants[n * 2]) : f32(f32(z * y) * sincosQuadrants[n * 2 + 1])
}

function nativeCos(x) {
  const [n, y] = reduceAngle(x)
  if (Math.abs(y) < f32(3.45266983e-4)) return f32(sincosQuadrants[n * 2 + 1] - y * sincosQuadrants[n * 2])
  const yy = f32(y * y)
  let z = sincosPoly[n & 1 ? 1 : 0]
  for (let i = n & 1 ? 3 : 2; i < 10; i += 2) z = f32(z * yy + sincosPoly[i])
  return n & 1 ? f32(f32(-z * y) * sincosQuadrants[n * 2]) : f32(z * sincosQuadrants[n * 2 + 1])
}

function nativeAtan(v) {
  const negative = v < 0 || Object.is(v, -0), x = Math.abs(v)
  let i = -1, large = false, r
  if (x >= f32(2.4142136573791504)) { large = true; r = f32(1 / x) }
  else if (x > f32(0.4142135679721832)) {
    if (x < 0.5) i = 0
    else if (x < 1) i = x < f32(0.534511148929596) ? 0 : x < f32(0.8206787705421448) ? 1 : 2
    else if (x < 2) i = x < f32(1.218503475189209) ? 2 : x < f32(1.870868444442749) ? 3 : 4
    else i = 4
    r = f32(1 / f32(atanTable[i + 33] + f32(x + atanTable[i + 39])))
    r = f32(f32(atanTable[i + 33] - r * atanTable[i + 7]) + f32(atanTable[i + 39] - r * atanTable[i + 13]))
  } else r = x
  const rr = f32(r * r)
  let poly = atanTable[6]
  for (let k = 5; k >= 1; k--) poly = f32(rr * poly + atanTable[k])
  r = f32(f32(r * rr) * poly + r)
  r = f32(r + atanTable[i + 27])
  r = f32(r + atanTable[i + 20])
  if (large) { r = f32(r - f32(Math.PI / 2)); return negative ? r : -r }
  return negative ? -r : r
}

function nativeAtan2(y, x) {
  const sx = x < 0 || Object.is(x, -0), sy = y < 0 || Object.is(y, -0)
  if (sx === sy) {
    if (sx) return x === 0 ? -f32(Math.PI / 2) : f32(nativeAtan(f32(y / x)) - f32(Math.PI))
    return x ? nativeAtan(f32(y / x)) : f32(Math.PI / 2)
  }
  if (x < 0) return f32(f32(Math.PI) + nativeAtan(f32(y / x)))
  return x ? nativeAtan(f32(y / x)) : sy ? -f32(Math.PI / 2) : f32(Math.PI / 2)
}

// Road-only state from 801EB004. The caller supplies authored DAT geometry,
// not recorded frames. This is not a complete stage collision result.
export function initializeRoad(data) {
  const center = f32(data.params.x0 * data.scale)
  return { pos: [f32(-1000 * data.scale), f32(10 * data.scale), 0],
    matrix: [0, 0, 0], prev: [0, 0, 0], angle: 0, prevLane: -1,
    current: 4, next: 0, direction: 0,
    children: { 4: [0, center, 0], 0: data.lanes[4].delta.map((v, i) => f32(v + (i === 1 ? center : 0))) },
    fall: false, loop: false, phase: 0, lateral: 0, disabled: new Set() }
}

function roadPoint(state, lane, point) {
  const a = state.children[lane], c = nativeCos(state.angle), n = nativeSin(state.angle)
  // PSMTXConcat then PSMTXMultVec: each paired product/sum rounds separately.
  const x = f32(f32(f32(c * a[0]) - n * a[1]) + state.matrix[0])
  const y = f32(f32(f32(n * a[0]) + c * a[1]) + state.matrix[1])
  return [f32(f32(c * point[0]) + f32(f32(-n * point[1]) + x)),
    f32(f32(n * point[0]) + f32(f32(c * point[1]) + y)),
    f32(a[2] + (point[2] || 0) + state.matrix[2])]
}

export function roadLines(state, data) {
  const result = []
  for (const lane of [state.current, state.next]) {
    for (const [id, joint, flags, x, y, endX, endY] of data.lanes[lane].lines) {
      if (state.disabled.has(joint)) continue
      const a = roadPoint(state, lane, [f32(x * data.scale), f32(y * data.scale)])
      const b = roadPoint(state, lane, [f32(endX * data.scale), f32(endY * data.scale)])
      result.push([id, flags, a[0], a[1], b[0], b[1]])
    }
  }
  return result
}

// 801EBAF8. Mutates only state and the supplied shared RNG cursor. restricted
// is the ready-callback flag, supplied by the host, never a capture timestamp.
export function advanceRoad(state, data, rng, { restricted = false } = {}) {
  const { params: p, scale, lanes, neighbors } = data
  const center = f32(p.x0 * scale), speed = f32(p.x6C * scale)
  const prev = state.pos.slice(), entry = lanes[state.current].delta
  const end = roadPoint(state, state.current, entry), oldLines = roadLines(state, data)
  if (Math.abs(state.angle) < f32(0.17453292) && end[0] < f32(-300 * scale)) {
    const promoted = roadPoint(state, state.next, [0, 0, 0])
    state.prevLane = state.current
    state.current = state.next
    state.pos[0] = promoted[0]
    state.pos[2] = promoted[2]
    state.children[state.current][0] = state.children[state.current][2] = 0
    const choice = chooseRoad({ current: state.current, direction: state.direction,
      roadY: state.pos[1], spY: promoted[1], restricted }, lanes.map(lane => lane.delta[1]), p, scale, rng)
    state.next = choice.lane
    state.direction = choice.direction
    state.children[state.next] = state.children[state.current].map((v, i) => f32(v + lanes[state.current].delta[i]))
    if (state.next === 11) { state.disabled = new Set([44, 45, 46, 47, 48, 49]); state.phase = 0 }
  }
  if (Math.abs(state.angle) < f32(0.17453292)) {
    if (end[0] < 0) state.loop = false
    else if (state.current === 11) state.loop = true
  }
  if (state.current === 11) {
    const change = advanceLoopPhase(state.phase, state.angle)
    state.phase = change.phase
    for (const joint of change.enabled) state.disabled.delete(joint)
    for (const joint of change.disabled) state.disabled.add(joint)
  }
  let target = null, normal = null
  const halfHeight = f32((state.fall ? 120 : 20) * scale)
  const oldById=new Map(oldLines.map(l=>[l[0],l]))
  for (const line of oldLines) {
    const links=state.links?.[line[0]],adjacent=links?links.slice(0,2):neighbors[line[0]]
    if(links)for(let side=0;side<2;side++) {
      const other=oldById.get(links[side+2]);if(!other)continue
      const dx=f32(line[2+side*2]-other[4-side*2]),dy=f32(line[3+side*2]-other[5-side*2])
      if(f32(f32(dx*dx)+f32(dy*dy))<4)adjacent[side]=other[0]
    }
    const hit = probeRoadSegment(line, ...adjacent, f32(center + halfHeight), f32(center - halfHeight))
    if (hit && (target === null || hit.y > target)) { target = hit.y; normal = hit.normal }
  }
  let rotation
  if (target !== null && (!state.fall || target > center)) {
    target = Math.max(-p.x70, Math.min(p.x70, target))
    rotation = state.current === 11 && state.loop ? -nativeAtan2(-normal[0], normal[1]) : -state.angle
    state.fall = false
  } else {
    if (!state.fall) { state.lateral = f32(nativeSin(state.angle) * f32(p.x7C * scale)); state.fall = true }
    state.lateral = f32(state.lateral - f32((target !== null ? 3 : 1) * f32(p.x78 * scale)))
    target = f32(center + state.lateral)
    rotation = -state.angle
  }
  const av = rotation > 0 ? 0 : Math.abs(rotation) > f32(0.0034906585) ? f32(rotation * p.x74) : rotation
  let x = state.pos[0], y = f32(state.pos[1] - target)
  if (av) {
    const c = nativeCos(av), n = nativeSin(av), nextY = f32(x * n + y * c)
    x = f32(x * c - y * n)
    y = nextY
  }
  state.pos = [x, f32(y + center), state.pos[2]]
  const oldRotation = state.angle
  state.angle = f32(state.angle + av)
  if (!state.loop && oldRotation > 0 && state.angle <= 0) state.angle = 0
  if (state.angle > Math.PI) state.angle = f32(state.angle - 2 * Math.PI)
  else if (state.angle < -Math.PI) state.angle = f32(state.angle + 2 * Math.PI)
  state.pos[0] = f32(state.pos[0] - speed)
  const lateral = f32(f32(f32(entry[2] / entry[0]) * speed) * f32(0.6))
  state.pos[2] = f32(state.pos[2] - (end[2] > lateral ? lateral : end[2] < -lateral ? -lateral : end[2]))
  state.matrix = state.pos.slice()
  state.prev = prev
  return state
}

export function unavailableReason(bundle, idx) {
  if (!DATA) return 'stage data unloaded'
  if (bundle?.meta?.stage!==24||!Number.isInteger(idx)||idx<0||idx>=bundle.meta.n||!Number.isInteger(bundle.meta.n)) return 'invalid stage/index'
  if (bundle.meta.start_frame!==-123) return 'missing match prefix'
  if (!setupCursor(bundle)) return 'missing GameStart seed'
  if (!frameCursor(bundle,idx)) return 'missing recorded pre-frame seed'
  // it_80275E98 assigns character items (48..159) collision class 5, which
  // both Big Blue load callbacks ignore. Common-item pools can synchronously
  // spawn at 801E8A1C, so their RNG/contact history is unsupported here.
  if (bundle.items?.some(item=>!Number.isInteger(item.t)||item.t<48||item.t>159)) return 'unsupported item pool/contact history'
  return null
}

import { registerStageSimData } from '../stageData.js'
let DATA
const caches = new WeakMap(), F = Math.fround, NONE = -3.4028234663852886e38
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x))
const activeCar = c => ![1,7,8].includes(c.state)
const degrees = F(.017453292)

// 801EC58C reads the road collision refreshed earlier in this ground pass.
function surface(lines, x, y, half = 500) {
  let best = { y:NONE, normal:[0,1] }
  const byId=lines.byId??=new Map(lines.map(l=>[l[0],l]))
  // 801EB4AC calls mpLib_80058560 when replacing a road section. Adjacent
  // sections acquire reciprocal secondary links; their transforms remain
  // rigidly attached until the next replacement.
  const linksFor=lines.links
  for (const l of lines) {
    const links=linksFor?.[l[0]]??DATA.links[l[0]],neighbors=links.slice(0,2)
    for(let side=0;side<2;side++) {
      const other=byId.get(links[side+2]);if(!other)continue
      const dx=F(l[2+side*2]-other[4-side*2]),dy=F(l[3+side*2]-other[5-side*2])
      if(F(F(dx*dx)+F(dy*dy))<4)neighbors[side]=other[0]
    }
    const hit = probeRoadSegment(l, ...neighbors, F(y+half), F(y-half), x)
    if (hit && hit.y > best.y) best = hit
  }
  return best
}

export function connectJoints(lines,links) {
  const byId=new Map(lines.map(l=>[l[0],l])),groups=DATA.geometry.map(ls=>ls.map(l=>byId.get(l[0])).filter(Boolean)).filter(ls=>ls.length)
  for(let i=0;i<groups.length-1;i++)for(let j=i+1;j<groups.length;j++) {
    for(const g of [groups[i],groups[j]])for(const l of g)for(let side=2;side<4;side++) {
      const other=links[l[0]][side]
      if(other!==-1&&links[other][5-side]!==-1&&links[other][5-side]!==l[0])links[l[0]][side]=-1
    }
    for(const a of groups[i])for(const b of groups[j])for(let side=0;side<2;side++) {
      const dx=F(a[2+side*2]-b[4-side*2]),dy=F(a[3+side*2]-b[5-side*2])
      if(Math.abs(dx)<2&&Math.abs(dy)<2){links[a[0]][side+2]=b[0];links[b[0]][3-side]=a[0]}
    }
  }
}

function carTransition(s, c, state, rng, roads) {
  const p=DATA.params, scale=DATA.scale
  if (state===1) { s.ranks[c.slot]=c.x>0?0:2; c.state=1; return true }
  if (state===10) c.threshold=20
  if ([2,3,4].includes(state)) c.threshold=rangedInt(p.x5C,p.x60,rng)
  if (state===7||state===8) c.threshold=1000
  if (state===5||state===6) {
    const x=F((state===5?DATA.mapPoints[152][0]:DATA.mapPoints[151][0])+(state===5?1:-1)*F(p.x68*scale))
    const y=surface(roads,x,0,1000).y
    if(y===NONE)return false
    // Both spawn directions count rank ZERO in 801EE398 (not rank two).
    const free=s.ranks.flatMap((rank,i)=>rank===0?[i]:[])
    if(!free.length)return false
    const slot=free[rng.int(free.length)]
    Object.assign(c,{slot,joint:slot+3,x,y:F(F(p.x2C*scale)+y),z:0,target:x,
      delta:0,gravity:0,height:0,velocity:0,accel:0,phase:F(2*Math.PI*rng.float()),
      amplitude:F(p.x34*scale),angularVelocity:0,fall:false,
      threshold:rangedInt(p.x5C,p.x60,rng),alpha:0,sound:rng.int(4)})
    c.angle=s.angles[slot] // reused collision joints retain their last rotation
    s.ranks[slot]=1
  }
  c.state=state
  return true
}

function carDecision(s,c,rng) {
  const p=DATA.params, cars=s.cars
  if(c.state===1)return 0
  if(c.state===9)return c.alpha===0?1:0
  if(c.state===7)return c.x>F(DATA.mapPoints[152][0]+F(p.x68*DATA.scale))?(c.alpha?9:1):0
  if(c.state===8)return c.x<F(DATA.mapPoints[151][0]-F(p.x68*DATA.scale))?(c.alpha?9:1):0
  let result=0
  if(c.threshold--<0) {
    for(let tries=0;!result&&tries<10000;tries++) {
      if(rng.int(4)!==3){result=4;break}
      let right=0,left=0,rt=0,lt=0
      for(const q of cars)if(q!==c&&activeCar(q)) {
        if(q.x>c.x){if(q.state===10)rt++;else right++}
        else if(q.x<c.x){if(q.state===10)lt++;else left++}
      }
      if(right)result=left?(rt?(lt?0:8):(lt?7:rng.int(2)?7:8)):8
      else if(left)result=7
    }
    if(!result)throw new Error('Big Blue car rejection did not terminate')
  }
  for(const q of cars)if(q!==c) {
    if(q.state===7&&q.x<c.x)result=7
    if(q.state===8&&q.x>c.x)result=8
  }
  return c.y< -2000?1:result
}

// 801ECB50, 801ED694, 801EEF00 and 801EF424, in lane/creation order.
export function advanceCars(s, road, roads, rng) {
  const p=DATA.params, scale=DATA.scale, cars=s.cars
  balanceCarPool(s.ranks,rng)
  if(cars.filter(activeCar).length===1)s.spawnTimer--
  if(!cars.some(c=>c.state===10||activeCar(c)&&Math.abs(c.x)<=60)) {
    const c=cars.filter(activeCar).sort((a,b)=>Math.abs(a.x)-Math.abs(b.x))[0]
    if(c){c.state=10;for(const q of cars)if(q.state===7&&q.x<c.x||q.state===8&&q.x>c.x)q.state=4}
  }
  if(s.spawnTimer--<0) {
    const c=cars.find(c=>c.state===1)
    if(c) {
      const right=cars.some(c=>c.state===7),left=cars.some(c=>c.state===8)
      const direction=!right&&!left?(rng.int(2)?1:-1):right?-1:1
      const eligible=s.ranks.filter(r=>r===(direction===1?0:2)).length
      if(eligible){rng.int(eligible);if(carTransition(s,c,direction===1?5:6,rng,roads))s.spawnTimer=rangedInt(p.x10,p.x14,rng)}
    }
  }
  const accel=F(p.x28*scale),maxSpeed=F(p.x24*scale)
  for(const c of cars) {
    const state=carDecision(s,c,rng)
    if(state)carTransition(s,c,state,rng,roads)
    if(c.state===1)continue
    const norm=F(Math.abs(c.velocity)/accel)
    switch(c.state) {
    case 10:c.accel=c.x>0?(c.threshold>norm?-accel:accel):(c.threshold>norm?accel:-accel);break
    case 2:c.accel=c.threshold>norm&&c.x<DATA.mapPoints[150][0]?accel:-accel;break
    case 3:c.accel=c.threshold>norm&&c.x>DATA.mapPoints[149][0]?-accel:accel;break
    case 4:{
      const predicted=F(F(c.velocity*norm+c.x)-F(norm*F(F(.5*(c.velocity>0?accel:-accel))*norm)))
      c.accel=c.target>c.x?(c.velocity<0||predicted<c.target?accel:-accel):(c.velocity>0||predicted>=c.target?-accel:accel)
      break
    }
    case 5:case 6:c.accel=0;c.alpha=Math.min(1,F(c.alpha+F(1/60)));break
    case 7:c.accel=accel;break
    case 8:c.accel=-accel;break
    case 9:c.alpha=Math.max(0,F(c.alpha-F(1/60)));break
    }
    let target=c.target
    if(c.state!==7&&c.state!==8) {
      const count=cars.filter(activeCar).length,behind=cars.filter(q=>q!==c&&activeCar(q)&&q.x<c.x).length
      target=F(F(.5*-F(p.x1C*scale))+F((behind+1)*F(F(p.x1C*scale)/(count+1))))
    }
    c.target=F(c.target+clamp(F(target-c.target),-.5,.5))
    c.velocity=clamp(F(c.velocity+c.accel),-maxSpeed,maxSpeed)
    c.delta=F(c.delta+c.velocity);c.x=F(c.target+c.delta)
    if(c.fall){c.height=0;c.gravity=0}
    else {c.gravity=F(c.gravity+F(p.x48*scale));c.height=F(c.height+c.gravity);if(c.height>0){c.height=0;c.gravity=0}else c.height=Math.max(-F(p.x4C*scale),c.height)}
    let heading=0
    if(!c.fall) {
      const base=F(p.x34*scale),bound=F((c.velocity>0?p.x38:p.x30)*scale)
      heading=c.velocity?F(base+F(c.velocity*F(F(bound-base)/maxSpeed))):base
    }
    c.amplitude=F(c.amplitude+p.x3C*F(heading-c.amplitude))
    c.phase=F(c.phase+degrees*p.x40);if(c.phase>2*Math.PI)c.phase=F(c.phase-2*Math.PI)
    const osc=F(c.amplitude*nativeSin(c.phase)),level=F(F(F(c.y-F(p.x2C*scale))-c.height)-osc)
    const hit=surface(roads,c.x,c.y,c.fall?500:F(20*scale))
    if(c.fall) {
      if(hit.y!==NONE&&hit.y>level&&c.angularVelocity<0)c.fall=false
      else {c.angularVelocity=F(c.angularVelocity-F((hit.y!==NONE?3:1)*F(p.x80*scale)));c.y=F(c.y+c.angularVelocity);c.y=F(c.y+F(road.pos[1]-road.prev[1]))}
    } else if(hit.y!==NONE)c.y=F(osc+F(c.height+F(F(p.x2C*scale)+hit.y)))
    else {c.fall=true;c.angularVelocity=F(nativeSin(c.angle)*F(p.x84*scale))}
    const angle=hit.y!==NONE&&!c.fall?nativeAtan2(-hit.normal[0],hit.normal[1]):F(degrees*p.x58)
    c.angle=F(c.angle+(hit.y!==NONE&&!c.fall?p.x50:p.x54)*F(angle-c.angle))
    s.angles[c.slot]=c.angle
    // Collision refresh uses these joint writes, BEFORE spacing resolves the
    // internal lane positions for the following frame.
    c.drawX=c.x;c.drawY=c.y
  }
  for(let k=0;k<10;k++) {
    let changed=false
    for(const c of cars)if(c.state!==1)for(const q of cars)if(q!==c&&q.state!==1) {
      let diff=F(c.x-q.x),spacing=F(p.x20*scale)
      if(Math.abs(diff)<spacing){diff=F(F(diff-(diff>0?spacing:-spacing))*.5);c.delta=F(c.delta-diff);c.x=F(c.x-diff);q.delta=F(q.delta+diff);q.x=F(q.x+diff);changed=true}
    }
    if(!changed)break
  }
}

function carHeight(s,left=DATA.mapPoints[149][0],right=DATA.mapPoints[150][0]) {
  let y=NONE
  for(const c of s.cars.cars)if(c.state!==1&&c.x>left&&c.x<right&&c.y>DATA.mapPoints[150][1]&&c.y<DATA.mapPoints[149][1])y=Math.max(y,c.y)
  return y
}
function smallOverlap(s,exclude,pos,secondary,rx,ry) {
  return s.small.some((c,i)=>i!==exclude&&c.state===3&&
    (Math.abs(F(c.x-pos.x))<rx&&Math.abs(F(c.y-pos.y))<ry||secondary&&c.dir===-1))
}
// 801EAB50 actually reads object 32's manager xC4, not object 36. The
// manager word is the cumulative spawn counter; retain that source behavior.
function managerOverlap(s,pos,secondary,rx,ry) {
  return (s.count>>>24)===2&&(Math.abs(pos.x)<rx&&Math.abs(pos.y)<ry||secondary&&((s.count>>>16)&255)===255)
}
function platformAvoid(s,exclude,pos,rx,ry) {
  let inside=3.4028234663852886e38,below=NONE
  const entries=s.small.map((c,i)=>({...c,key:i,half:[56,40,24][i]*DATA.scale,active:c.state===3}))
  entries.push({...s.route,key:3,half:F(68*DATA.scale)/2,active:s.route.state===2})
  const left=F(pos.x-rx),right=F(pos.x+rx),top=F(pos.y+ry),bottom=F(pos.y-ry)
  for(const c of entries)if(c.key!==exclude&&c.active) {
    const l=F(c.x-c.half),r=F(c.x+c.half)
    if(r>left&&r<right||l<right&&l>left) {
      if(c.y>bottom&&c.y<top){if(Math.abs(F(pos.y-c.y))<inside)inside=c.y}
      else if(pos.y>c.y&&c.y>below)below=c.y
    }
  }
  return inside!==3.4028234663852886e38?{kind:1,y:inside}:below!==NONE?{kind:2,y:below}:{kind:0,y:0}
}
function moveHeight(c,target,upDiv,upMax,downDiv,downMax) {
  const diff=F(target-c.y)
  const velocity=Math.abs(diff)<.5?0:diff>0?Math.min(upMax,F(diff/upDiv)):Math.max(-downMax,F(diff/downDiv))
  c.y=F(c.y+velocity)
}
function slopeAngle(roads,c) {const h=surface(roads,c.x,c.y);return nativeAtan2(-h.normal[0],h.normal[1])}
function turn(c,target,rate){c.angle=F(c.angle+F(degrees*F(rate*F(target-c.angle))))}

export function advanceSmall(s,roads,rng) {
  const p=DATA.params,scale=DATA.scale,edge=F(10+DATA.mapPoints[152][0])
  for(let i=0;i<3;i++) {
    const c=s.small[i]
    if(c.state===0){if(s.smallEnabled){c.timer=p.x88+(p.x8C?rng.int(p.x8C):0);c.state=1}continue}
    if(c.state===1&&!s.smallEnabled){c.state=0;continue}
    if(c.state===1||c.state===2) {
      if(c.timer>0) {
        let count=0
        for(const q of s.small)if(q!==c&&(q.state===3&&(q.dir===1&&q.oldX<DATA.mapPoints[150][0]||q.dir===-1&&q.oldX>DATA.mapPoints[149][0])||q.state===1&&q.timer===0))count++
        if(count<=1)c.timer=0;else c.timer--
        continue
      }
      const r=surface(roads,edge,0).y,l=surface(roads,-edge,0).y
      if(r===NONE&&l===NONE)continue
      const span=Math.trunc(Math.abs(F(p.x94-p.x90)))
      c.offset=F(p.x90+(span?rng.int(span):0))
      c.dir=l===NONE?-1:r===NONE?1:Math.abs(F(r-l))<80?(rng.int(2)?1:-1):r<l?-1:1
      c.x=edge;c.y=F(r+c.offset)
      if(s.flyerEnabled){c.dir=1;c.x=-edge}
      else if(c.dir===1){c.x=-edge;c.y=F(l+c.offset)}
      let found=false
      for(let retry=0;retry<3;retry++) {
        found=smallOverlap(s,i,c,false,F(2*F(56*scale)),25)||managerOverlap(s,c,false,F(2*F(56*scale)),25)||c.y<=carHeight(s)
        if(!found)break
        c.y=F(c.y+25)
      }
      if(found||c.y===NONE)c.y=F(10+DATA.mapPoints[149][1])
      Object.assign(c,{state:3,oldX:c.x,targetY:c.y,angle:0,vx:F(p.x98*c.dir),vy:0,sub:0,contacts:0,lastContacts:0,left:0,right:0,loadDirection:0})
      // 801E8A1C only creates from the enabled item pool; callers with an
      // observed item history are rejected by the adapter below.
      if((p.xB8?rng.int(p.xB8):0)===0)c.itemOpportunity=true
      s.count++
      if(!s.routeEnabled&&s.count>=p.x11C&&s.count<=p.x120&&(s.count===p.x120||rng.int(2)))s.routeEnabled=true
      if(!s.flyerEnabled&&s.count>=p.xDC&&c.dir===1&&(s.count>=p.xE0||rng.int(2))){s.smallEnabled=false;s.flyerEnabled=true;s.count=0}
      continue
    }
    if(c.state!==3)continue
    const angle=slopeAngle(roads,c),h=surface(roads,c.x,c.y).y,speed=F([56,40,24][i]*scale)
    const frontY=F(c.y+F(nativeSin(angle)*F(c.dir*speed)))
    if(!c.contacts||c.sub===3) {
      if(!c.lastContacts&&c.contacts){c.home=c.y;c.timer=p.xB0;c.sub=1}
      turn(c,angle,p.x9C)
    } else {
      if(!c.lastContacts){c.home=c.y;c.timer=p.xB0;c.sub=1}
      const direction=c.right<c.left?1:-1
      if(c.loadDirection!==direction){c.timer=p.xB0;c.sub=1}
      c.loadDirection=direction
      if(c.sub===2) {
        c.y=F(c.y+c.vy);turn(c,angle,p.x9C)
        if(c.y>=c.home){c.vy=0;c.loadDirection=0;c.sub=3}
      } else if(c.timer<=0){c.vy=p.xAC;c.timer=p.xB4;c.sub=2}
      else {
        const a=clamp(F(p.xA0*F(c.left-c.right)),-p.xA4,p.xA4)
        c.y=F(c.y+(direction===1?-p.xA8:p.xA8));c.angle=F(c.angle+F(degrees*a))
        const deg=F(F(57.29578)*c.angle)
        if(c.y<F(h+p.x90)){if(deg>30)c.angle=F(.5235988);if(deg< -30)c.angle=F(-.5235988)}
        if(deg>65)c.angle=F(1.1344640);if(deg< -65)c.angle=F(-1.1344640)
        c.timer--
      }
    }
    const bound=carHeight(s,F(c.x-F(20+speed)),F(c.x+F(20+speed))),probe=surface(roads,c.x,c.y).y
    const avoid=platformAvoid(s,i,c,F(10+speed),16.5)
    if(avoid.kind===0||avoid.kind===1&&c.y<avoid.y)c.targetY=bound<=probe?(probe===NONE?frontY:F(probe+c.offset)):F(bound+c.offset)
    else if(avoid.kind===1)c.targetY=F(c.y+F(c.y-avoid.y))
    moveHeight(c,c.targetY??0,p.xBC,p.xC0,p.xC4,p.xC8)
    c.oldX=c.x;c.x=F(c.x+c.vx);c.lastContacts=c.contacts;c.contacts=0;c.left=0;c.right=0
    if(c.vx<0&&c.x< -F(edge-50)||c.vx>0&&c.x>F(edge-50)) {
      c.state=1;c.angle=0;c.sub=0;c.contacts=0;c.vx=0;c.vy=0;c.loadDirection=0
      c.timer=Math.trunc((p.x88+(p.x8C?rng.int(p.x8C):0))/2)
    }
  }
}

function advanceFlyer(s,roads) {
  const c=s.flyer,p=DATA.params,scale=DATA.scale,angle=slopeAngle(roads,c)
  const frontY=F(c.y+F(50*nativeSin(angle)))
  if(c.state===0) {
    if(s.flyerEnabled&&s.small.filter(q=>q.state!==0).length<=1) {
      const x=F(DATA.mapPoints[151][0]-50),h=surface(roads,x,0).y
      if(h!==NONE) {
        c.x=x;c.y=F(h+p.xCC)
        if(smallOverlap(s,-1,c,true,F(2*F(60*scale)),F(140*scale))||managerOverlap(s,c,true,F(2*F(60*scale)),25)||c.y<=carHeight(s))c.y=F(30+DATA.mapPoints[149][1])
        c.vx=p.xD0;c.state=1
      }
    }
    return
  }
  if(c.state===1) {
    if(c.x>0){c.vx=0;c.timer=Math.trunc(p.xD8);c.state=2}
    else c.vx=smallOverlap(s,-1,c,true,F(F(60*scale)+30),F(140*scale))||managerOverlap(s,c,true,F(F(60*scale)+30),F(140*scale))?0:p.xD0
  } else if(c.state===2) {
    if(c.timer<=0){c.vx=p.xD0;c.state=3;const q=s.small.find(q=>q.state===0);if(q){q.state=2;q.timer=0}}
    else c.timer--
  } else if(c.state===3&&c.x>F(50+DATA.mapPoints[152][0])) {
    c.state=0;c.vx=0;c.angle=0;s.flyerEnabled=false;s.smallEnabled=true
  }
  turn(c,angle,p.xD4)
  const bound=carHeight(s),h=surface(roads,c.x,c.y).y,target=bound<=h?(h===NONE?frontY:F(h+p.xCC)):F(bound+p.xCC)
  moveHeight(c,target,p.xE4,p.xE8,p.xEC,p.xF0);c.x=F(c.x+c.vx)
}

export function advanceRoute(s,roads,rng) {
  const c=s.route,p=DATA.params,scale=DATA.scale,edge=DATA.mapPoints[152][0],angle=slopeAngle(roads,c)
  if(c.state===0){if(s.routeEnabled){c.timer=0;c.tx=0;c.ty=0;c.state=1}return}
  if(c.state===1) {
    if(c.timer>0){c.timer--;return}
    const r=surface(roads,edge,0).y,l=surface(roads,-edge,0).y,range=Math.trunc(Math.abs(F(p.xF8-p.xF4)))
    c.offset=F(p.xF4+(range?rng.int(range):0))
    if(r===NONE&&l===NONE)return
    c.dir=l===NONE?-1:r===NONE?1:Math.abs(F(r-l))<80?(rng.int(2)?1:-1):r<l?-1:1
    c.x=c.dir===1?-edge:edge;c.y=F((c.dir===1?l:r)+c.offset)
    if(!smallOverlap(s,-1,c,false,F(2*F(68*scale)),F(52*scale))&&c.y>carHeight(s)){c.state=2;c.targetY=c.y;c.vx=0;c.vy=0}
    return
  }
  const half=F(F(68*scale)/2),bound=carHeight(s,F(c.x-F(half+20)),F(c.x+F(half+20))),h=surface(roads,c.x,c.y).y
  const avoid=platformAvoid(s,3,c,F(half+10),F(F(F(52*scale)/2)+4))
  if(avoid.kind===0||avoid.kind===1&&c.y<avoid.y)c.targetY=bound<=h?(h===NONE?F(c.y+F(half*nativeSin(angle))):F(h+c.offset)):F(bound+c.offset)
  else if(avoid.kind===1)c.targetY=F(c.y+F(c.y-avoid.y))
  moveHeight(c,c.targetY??0,p.x124,p.x128,p.x12C,p.x130)
  if(c.tx<=0){c.tx=p.x10C+rng.int(Math.abs(p.x110-p.x10C));let v=F(F(.1)*rng.int(Math.trunc(F(F(p.x100-p.xFC)/F(.1)))));if(!v)v=p.xFC;c.vx=F(v*c.dir)}else c.tx--
  if(c.ty<=0){c.ty=p.x10C+rng.int(Math.abs(p.x110-p.x10C));let v=F(F(.1)*rng.int(Math.trunc(F(F(p.x108-p.x104)/F(.1)))));if(!v)v=p.x104;if(rng.int(2))v=-v;c.vy=v}else c.ty--
  c.x=F(c.x+c.vx);c.y=F(c.y+c.vy)
  if(c.dir===-1&&c.x< -F(edge-50)||c.dir===1&&c.x>F(edge-50)){c.state=0;c.vx=0;c.vy=0;s.routeEnabled=false}
}

function transformed(j,x,y,angle,scale) {
  const cos=F(nativeCos(angle)*scale),sin=F(nativeSin(angle)*scale)
  return DATA.geometry[j].map(([id,flags,ax,ay,bx,by])=>{
    const coords=[F(F(cos*ax)+F(x-sin*ay)),F(F(sin*ax)+F(y+cos*ay)),F(F(cos*bx)+F(x-sin*by)),F(F(sin*bx)+F(y+cos*by))]
    if(id>=DATA.dynamicStart) {
      const dx=F(coords[2]-coords[0]),dy=F(coords[3]-coords[1]),slope=F(dy/dx)
      const kind=dx>0?(slope>1.7320508368950045?8:slope< -1.7320508368950045?4:1):dx<0?(slope>.577350295784245?4:slope< -.577350295784245?8:2):dy>0?8:4
      flags=(flags&256)|kind
    }
    return [id,flags,...coords]
  })
}

export function initialStage(bundle) {
  const rng=setupCursor(bundle);if(!DATA||!rng)return null
  const cars=initializeCars(rng,DATA.params,DATA.scale);cars.angles=Array(30).fill(0)
  for(const c of cars.cars)Object.assign(c,{angle:0,fall:false,drawX:c.x,drawY:c.y})
  return {idx:-1,links:DATA.links.map(l=>l.slice()),road:initializeRoad(DATA),cars,small:DATA.smallInitial.map(([x,y])=>({state:0,x,y,angle:0})),
    flyer:{state:2,x:0,y:DATA.params.xCC,angle:0,vx:0,timer:Math.trunc(DATA.params.xD8)},
    route:{state:0,x:0,y:0,angle:0},smallEnabled:false,flyerEnabled:true,routeEnabled:false,count:0}
}

function geometry(s,roads=roadLines(s.road,DATA)) {
  const lines=[...roads]
  for(const c of s.cars.cars)if(c.state!==1)lines.push(...transformed(c.joint,c.drawX,c.drawY,c.angle,F(DATA.scale*DATA.params.xC)))
  for(let i=0;i<3;i++){const c=s.small[i];if(c.state===3)lines.push(...transformed(i,c.x,c.y,c.angle,DATA.scale))}
  if(s.flyer.state)lines.push(...transformed(34,s.flyer.x,s.flyer.y,s.flyer.angle,DATA.scale))
  if(s.route.state===2)lines.push(...transformed(66,s.route.x,s.route.y,0,DATA.scale))
  return {lines,replace:true,complete:true}
}

// Late fighter Cb1 writes are latched for the NEXT priority-4 stage pass.
export function contacts(s,bundle,idx,lines) {
  const frames=bundle.frames
  const fighters=Array.from({length:frames.x?.length||0},(_,port)=>Object.fromEntries(
    ['x','y','air','cid','state','seed_order'].map(k=>[k,frames[k]?.[port]]))).concat(frames.fol||[])
  fighters.sort((a,b)=>(a.seed_order?.[idx]??0)-(b.seed_order?.[idx]??0))
  for(const fighter of fighters) {
    // mpLib_8005811C also invokes Cb1 for ledges. The bundle lacks the ledge
    // line/ECB attachment, so do not invent a small-platform lever arm.
    if(fighter.state?.[idx]>=252&&fighter.state[idx]<=263&&s.small.some(c=>c.state===3)){s.unsupported=true;return}
    if(fighter.air?.[idx]!==0)continue
    const x=fighter.x[idx],y=fighter.y[idx]
    let best=null,error=.05
    for(const l of lines)if((l[1]&15)===1&&x>=Math.min(l[2],l[4])-.1&&x<=Math.max(l[2],l[4])+.1) {
      const cx=clamp(x,Math.min(l[2],l[4]),Math.max(l[2],l[4])),height=l[3]+(l[5]-l[3])*(cx-l[2])/(l[4]-l[2]),e=Math.abs(y-height)
      if(e<error){best=l;error=e}
    }
    if(!best)continue
    const j=DATA.geometry.findIndex(ls=>ls.some(l=>l[0]===best[0]))
    if(j>=3&&j<=32||j<=2&&j>=0) {
      // ft_80081B38 sets CollData.x50 from the common DAT weight attribute.
      const weight=DATA.weights[fighter.cid?.[idx]]
      if(!Number.isFinite(weight)){s.unsupported=true;return}
      // mpColl_80043268 emits kind 1 for an airborne landing, kind 2 for
      // continuing grounded contact. Car suspension accepts only kind 1.
      if(j>=3){if(fighter.air[idx-1]===1)for(const c of s.cars.cars)if(c.joint===j)c.gravity=F(-weight*DATA.params.x44)}
      else {
        const c=s.small[j],dx=F(c.x-x),dy=F(c.y-y),dist=F(Math.sqrt(F(dy*dy+F(dx*dx))))
        if(dist>2){const amount=F(dist*F(weight/1000));if(x>c.x)c.right=F(c.right+amount);else c.left=F(c.left+amount);c.contacts++}
      }
    }
  }
}

export function advanceStage(s,bundle,idx) {
  const rng=frameCursor(bundle,idx);if(!rng)return null
  const previous=s.road.current,oldGeometry=geometry(s).lines
  s.road.links=s.links
  advanceRoad(s.road,DATA,rng,{restricted:idx<84})
  if(previous!==s.road.current)connectJoints(oldGeometry,s.links)
  const roads=roadLines(s.road,DATA)
  roads.links=s.links
  advanceCars(s.cars,s.road,roads,rng)
  advanceSmall(s,roads,rng);advanceFlyer(s,roads);advanceRoute(s,roads,rng)
  s.idx=idx
  contacts(s,bundle,idx,geometry(s,roads).lines)
  return s
}

export default function simulate(bundle,idx) {
  if(unavailableReason(bundle,idx))return null
  let cache=caches.get(bundle)
  if(!cache){const s=initialStage(bundle);if(!s)return null;cache=new Map([[-1,s]]);caches.set(bundle,cache)}
  let key=Math.floor((idx+1)/128)*128-1;while(!cache.has(key))key-=128
  if(cache.last&&cache.last.idx<=idx&&cache.last.idx>key)key=cache.last.idx
  let s=structuredClone(cache.last?.idx===key?cache.last:cache.get(key))
  for(let i=key+1;i<=idx;i++) {
    if(!advanceStage(s,bundle,i))return null
    if((i+1)%128===0)cache.set(i,structuredClone(s))
  }
  cache.last=s
  return s.unsupported?null:geometry(s)
}

export function receiveStageData(value) { DATA=value }
registerStageSimData(24,receiveStageData)
