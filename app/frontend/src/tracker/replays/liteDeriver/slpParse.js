// Slippi SPEC.md offsets below are relative to the payload (command byte excluded).
// https://github.com/project-slippi/slippi-wiki/blob/master/SPEC.md
// Walk the stream once, retaining offsets rather than allocating event objects or
// decoding float arrays that a later rollback would immediately overwrite.

export class SlpError extends Error {
  constructor(message) {
    super(message)
    this.name = 'SlpError'
  }
}

const HEADER = [123, 85, 3, 114, 97, 119, 91, 36, 85, 35, 108]
const FOOTER = [85, 8, 109, 101, 116, 97, 100, 97, 116, 97, 123]
const RAW = 15
const sjis = new TextDecoder('shift-jis')
const atLeast = (v, major, minor = 0, build = 0) =>
  v[0] > major || (v[0] === major && (v[1] > minor || (v[1] === minor && v[2] >= build)))

function matches(bytes, pos, pattern) {
  for (let i = 0; i < pattern.length; i++) if (bytes[pos + i] !== pattern[i]) return false
  return true
}

function nameAt(bytes, pos, length) {
  let end = pos
  while (end < pos + length && bytes[end]) end++
  // Preserve recorded text, including the fullwidth connect-code #, as peppi
  // does. Display/search normalization belongs to the consumer of the header.
  return sjis.decode(bytes.subarray(pos, end)) || null
}

function header(input) {
  const bytes = input instanceof ArrayBuffer ? new Uint8Array(input) : input
  if (!(bytes instanceof Uint8Array) || bytes.length < RAW + 2 || !matches(bytes, 0, HEADER)) {
    throw new SlpError('not a slp file (bad header)')
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  let rawLength = view.getInt32(11)
  const warnings = []
  if (rawLength < 0) throw new SlpError('negative raw length')
  if (rawLength === 0) {
    // Dolphin backfills this on clean close. Search only the tail, as slp_meta
    // does; a killed recording without a footer is still a usable event prefix.
    let footer = -1
    for (let p = bytes.length - FOOTER.length; p >= Math.max(RAW, bytes.length - 65536); p--) {
      if (matches(bytes, p, FOOTER)) { footer = p; break }
    }
    rawLength = (footer < 0 ? bytes.length : footer) - RAW
    warnings.push(footer < 0 ? 'raw length 0; reading unfinished event prefix' : 'raw length 0; recovered from metadata footer')
  }
  const end = Math.min(RAW + rawLength, bytes.length)
  if (RAW + rawLength > bytes.length) warnings.push('raw block extends past EOF (truncated)')
  const tableLength = bytes[RAW + 1]
  const first = RAW + 1 + tableLength
  if (bytes[RAW] !== 0x35 || tableLength < 1 || (tableLength - 1) % 3 || first > end) {
    throw new SlpError('unusable payload-size table')
  }
  // -1 distinguishes an unknown command from a declared, zero-size event.
  const sizes = new Int32Array(256).fill(-1)
  for (let p = RAW + 2; p < first; p += 3) {
    if (sizes[bytes[p]] !== -1) throw new SlpError('duplicate command in payload-size table')
    sizes[bytes[p]] = view.getUint16(p + 1)
  }
  sizes[0x35] = tableLength
  const size = sizes[0x36]
  // The original GameStart includes the complete Game Info Block and RNG seed.
  if (size < 0x140 || first + 1 + size > end || bytes[first] !== 0x36) {
    throw new SlpError('missing or truncated GameStart')
  }
  const p = first + 1
  const version = [bytes[p], bytes[p + 1], bytes[p + 2]]
  const isTeams = !!bytes[p + 0x0C]
  const players = []
  for (let port = 0; port < 4; port++) {
    const base = p + 0x64 + 0x24 * port
    const type = bytes[base + 1]
    if (type === 3) continue
    const nameOff = 0x1A4 + 0x1F * port, codeOff = 0x220 + 0xA * port
    players.push({ port, extChar: bytes[base], costume: bytes[base + 3],
      team: isTeams ? bytes[base + 9] : null, type,
      code: atLeast(version, 3, 9) && size >= codeOff + 10 ? nameAt(bytes, p + codeOff, 10) : null,
      name: atLeast(version, 3, 9) && size >= nameOff + 31 ? nameAt(bytes, p + nameOff, 31) : null })
  }
  return { bytes, view, sizes, end, offset: p + size, rawLength, version,
    start: { stage: view.getUint16(p + 0x12), isTeams, players,
      itemFrequency: view.getInt8(p + 0x0F),
      seed: atLeast(version, 0, 1) ? view.getUint32(p + 0x13C) : null }, warnings }
}

export function parseHeaderOnly(bytes) {
  const { version, start, rawLength } = header(bytes)
  return { version, start, rawLength }
}

// Pages avoid moving every port's offsets when a rollback introduces an earlier
// first frame. Slots 0..15 are pre/post for four leaders/followers; 16 is the
// item-list head, 17/18 FoD, 19 Stadium, 20 Frame Start. Zero means no event.
const PAGE = 1024, STRIDE = 21
class FrameIndex {
  constructor(rawLength) {
    this.pages = new Map()
    this.first = Infinity
    this.last = -Infinity
    // An int32 corrupted frame id must not allocate gigabytes on a phone.
    // This permits up to 4.85 hours, and generous gaps in a short recording.
    this.maxSpan = Math.min(1 << 20, Math.max(3600, rawLength))
  }
  touch(frame) {
    const first = Math.min(this.first, frame), last = Math.max(this.last, frame)
    if (last - first + 1 > this.maxSpan) return false
    this.first = first; this.last = last
    const key = Math.floor(frame / PAGE)
    this.page = this.pages.get(key)
    if (!this.page) { this.page = new Uint32Array(PAGE * STRIDE); this.pages.set(key, this.page) }
    this.base = (frame - key * PAGE) * STRIDE
    return true
  }
  get(frame, slot) {
    const key = Math.floor(frame / PAGE), page = this.pages.get(key)
    return page ? page[(frame - key * PAGE) * STRIDE + slot] : 0
  }
}

class IntList {
  constructor(Type = Int32Array) { this.data = new Type(1024); this.length = 0 }
  push(value) {
    if (this.length === this.data.length) {
      const next = new this.data.constructor(this.length * 2)
      next.set(this.data); this.data = next
    }
    this.data[this.length++] = value
  }
}

const FRAME_TYPES = {
  present: Uint8Array, state: Uint16Array, cid: Uint8Array,
  x: Float32Array, y: Float32Array, dir: Int8Array, pct: Float32Array,
  shield: Float32Array, stocks: Uint8Array, lastAttack: Uint8Array, age: Float32Array,
  airborne: Uint8Array, lcancel: Uint8Array, joyX: Float32Array, joyY: Float32Array,
  cX: Float32Array, cY: Float32Array, trigger: Float32Array, buttons: Uint16Array,
  // Melee's RNG seed as Slippi recorded it at this player's pre-frame update.
  // HSD_Rand is a plain LCG, so stage hazards that look random (Big Blue's
  // track, Green Greens' blocks, Kraid's spin) are reproducible from it.
  seed: Uint32Array,
  preState: Uint16Array, seedOrder: Uint32Array,
  // the port that last hit this fighter (post-frame 0x20; 6 = none yet)
  hitBy: Uint8Array,
}

function fighter(h, index, slot, n) {
  const a = Object.fromEntries(Object.entries(FRAME_TYPES).map(([key, Type]) => [key, new Type(n)]))
  if (atLeast(h.version, 3, 8) && h.sizes[0x38] >= 76) a.hitlag = new Float32Array(n)
  // Misc action state (post-frame 0x2B): hitstun frames left while hitstunned,
  // 0.4 x the knockback on the frame a hit lands (ftCo_Damage).
  if (atLeast(h.version, 2) && h.sizes[0x38] >= 46) a.hitstun = new Float32Array(n)
  const fields = Object.keys(a).filter(key => !['present', 'seed', 'preState', 'seedOrder'].includes(key))
  const { bytes: b, view: v, sizes, version } = h
  const postSize = sizes[0x38], preSize = sizes[0x37]
  const age = atLeast(version, 0, 2) && postSize >= 37
  const air = atLeast(version, 2) && postSize >= 47
  const lcancel = atLeast(version, 2) && postSize >= 51
  for (let i = 0; i < n; i++) {
    const frame = index.first + i, post = index.get(frame, slot + 1)
    const pre = index.get(frame, slot)
    // Stream offsets preserve actual callback order, including followers and
    // rollbacks. Never carry an RNG anchor over a missing pre record.
    const start = index.get(frame, 20)
    if (pre && pre > start && preSize >= 12 && atLeast(version, 0, 1)) {
      a.seed[i] = v.getUint32(pre + 6)
      a.preState[i] = v.getUint16(pre + 10)
      a.seedOrder[i] = pre
    }
    if (!post) {
      if (i) for (const key of fields) a[key][i] = a[key][i - 1]
      continue
    }
    a.present[i] = 1
    a.cid[i] = b[post + 6]; a.state[i] = v.getUint16(post + 7)
    a.x[i] = v.getFloat32(post + 9); a.y[i] = v.getFloat32(post + 13)
    a.dir[i] = v.getFloat32(post + 17) < 0 ? -1 : 1
    a.pct[i] = v.getFloat32(post + 21); a.shield[i] = v.getFloat32(post + 25)
    a.lastAttack[i] = b[post + 29]; a.hitBy[i] = b[post + 31]; a.stocks[i] = b[post + 32]
    if (a.hitstun) a.hitstun[i] = v.getFloat32(post + 42)
    if (age) a.age[i] = v.getFloat32(post + 33)
    if (air) a.airborne[i] = b[post + 46]
    if (lcancel) a.lcancel[i] = b[post + 50]
    if (a.hitlag) a.hitlag[i] = v.getFloat32(post + 72)
    if (pre) {
      if (preSize >= 28) a.joyX[i] = v.getFloat32(pre + 24)
      if (preSize >= 32) a.joyY[i] = v.getFloat32(pre + 28)
      if (preSize >= 36) a.cX[i] = v.getFloat32(pre + 32)
      if (preSize >= 40) a.cY[i] = v.getFloat32(pre + 36)
      if (preSize >= 44) a.trigger[i] = v.getFloat32(pre + 40)
      if (preSize >= 50) a.buttons[i] = v.getUint16(pre + 48)
    }
  }
  return a
}

function itemTracks(h, index, offsets, next, n) {
  const { bytes: b, view: v, version, sizes } = h
  const hasOwner = atLeast(version, 3, 6) && sizes[0x3B] >= 42
  // Payload offsets (SPEC includes the command byte). Keep optional fields
  // absent on older streams, rather than interpreting a missing byte as zero.
  const extras = [
    ['lifetime', Float32Array, 29, 4, 0],
    ['subtype', Uint8Array, 37, 1, 2], ['face', Uint8Array, 38, 1, 2],
    ['launched', Uint8Array, 39, 1, 2], ['charge', Uint8Array, 40, 1, 2],
    ['owners', Int8Array, 41, 1, 6],
  ].filter(([, , offset, width, minor]) => atLeast(version, 3, minor) && sizes[0x3B] >= offset + width)
  const live = new Map(), tracks = [], perFrame = new Map()
  for (let i = 0; i < n; i++) {
    const frame = index.first + i
    perFrame.clear()
    // Lists are newest-first. Dedupe also handles the no-Frame-Start fallback.
    for (let node = index.get(frame, 16); node; node = next.data[node]) {
      const p = offsets.data[node], spawn = v.getUint32(p + 33)
      if (!perFrame.has(spawn)) perFrame.set(spawn, p)
    }
    for (const [spawn, p] of perFrame) {
      const type = v.getUint16(p + 4)
      let tr = live.get(spawn)
      if (!tr || tr.type !== type || tr.start + tr.offsets.length !== frame) {
        tr = { spawn, type, owner: hasOwner ? v.getInt8(p + 41) : -1, start: frame, offsets: [] }
        tracks.push(tr); live.set(spawn, tr)
      }
      tr.offsets.push(p)
    }
  }
  // Only finalized samples are decoded; speculative lasers never become tracks.
  return tracks.map(tr => {
    const count = tr.offsets.length
    const result = { spawn: tr.spawn, type: tr.type, owner: tr.owner, start: tr.start,
      state: new Uint8Array(count), dir: new Int8Array(count),
      x: new Float32Array(count), y: new Float32Array(count),
      vx: new Float32Array(count), vy: new Float32Array(count) }
    for (const [key, Type] of extras) result[key] = new Type(count)
    for (let i = 0; i < count; i++) {
      const p = tr.offsets[i], d = v.getFloat32(p + 7)
      result.state[i] = b[p + 6]; result.dir[i] = d > 0 ? 1 : d < 0 ? -1 : 0
      result.x[i] = v.getFloat32(p + 19); result.y[i] = v.getFloat32(p + 23)
      result.vx[i] = v.getFloat32(p + 11); result.vy[i] = v.getFloat32(p + 15)
      for (const [key, Type, offset] of extras) {
        result[key][i] = Type === Float32Array ? v.getFloat32(p + offset) :
          Type === Int8Array ? v.getInt8(p + offset) : b[p + offset]
      }
    }
    return result
  })
}

export function parseSlp(bytes) {
  const h = header(bytes)
  const { bytes: b, view: v, sizes, version, start, warnings } = h
  const index = new FrameIndex(h.end - RAW)
  const rows = new IntList(), fallbackRows = new IntList()
  const itemOffsets = new IntList(Uint32Array), itemNext = new IntList(Uint32Array)
  itemOffsets.push(0); itemNext.push(0)
  const followers = new Uint8Array(4), active = new Uint8Array(4)
  for (const player of start.players) {
    active[player.port] = 1
    // Ice Climbers (external/CSS 14) has a follower even in solo-Popo recordings
    // where Nana never emits an event. Keep an all-absent array like peppi.
    if (player.extChar === 14) followers[player.port] = 1
  }
  const firstPort = start.players[0]?.port
  const startsAllowed = atLeast(version, 2, 2), itemsAllowed = atLeast(version, 3)
  const stageAllowed = atLeast(version, 3, 18)
  let hasStarts = false, blockFrame = null, blockHead = 0, gameEnd = null
  let warnedBlock = false
  for (let pos = h.offset; pos < h.end;) {
    const cmd = b[pos], size = sizes[cmd], p = pos + 1
    if (size < 0) { warnings.push(`unknown command 0x${cmd.toString(16)} at byte ${pos}`); break }
    if (p + size > h.end) { warnings.push(`truncated event 0x${cmd.toString(16)} at byte ${pos}`); break }
    const isFighter = cmd === 0x37 || cmd === 0x38
    const isStart = cmd === 0x3A && startsAllowed
    const isItem = cmd === 0x3B && itemsAllowed
    const isBookend = cmd === 0x3C && itemsAllowed
    const isFod = cmd === 0x3F && stageAllowed, isStadium = cmd === 0x41 && stageAllowed
    const minimum = cmd === 0x37 ? 6 : cmd === 0x38 ? 33 : isStart ? 8 :
      isItem ? 37 : isBookend ? 4 : isFod ? 9 : isStadium ? 8 : cmd === 0x39 ? 1 : 0
    if (size < minimum) { warnings.push(`short event 0x${cmd.toString(16)} at byte ${pos}`); break }
    if (isFighter || isStart || isItem || isBookend || isFod || isStadium) {
      // Reject a bad key before it can expand the finalized frame range.
      if (isFighter && (b[p + 4] > 3 || b[p + 5] > 1 || !active[b[p + 4]])) {
        warnings.push(`invalid fighter port/follower at byte ${pos}`); break
      }
      if (isFod && b[p + 4] > 1) { warnings.push(`invalid FoD platform at byte ${pos}`); break }
      const frame = v.getInt32(p)
      if (!index.touch(frame)) { warnings.push(`unreasonable frame span at byte ${pos}`); break }
      const page = index.page, base = index.base
      if (isFighter) {
        const port = b[p + 4], follower = b[p + 5]
        page[base + port * 4 + follower * 2 + (cmd === 0x38 ? 1 : 0)] = p
        if (follower) followers[port] = 1
        if (cmd === 0x38 && !follower && port === firstPort) fallbackRows.push(frame)
      } else if (isStart) {
        page[base + 20] = p
        if (blockFrame !== null && itemsAllowed && !warnedBlock) {
          warnings.push('incomplete item block; keeping last completed block'); warnedBlock = true
        }
        if (!hasStarts) {
          // A declared Frame Start is not evidence that any were actually emitted.
          for (const part of index.pages.values()) for (let k = 16; k < part.length; k += STRIDE) part[k] = 0
        }
        hasStarts = true; rows.push(frame); blockFrame = frame; blockHead = 0
      } else if (isItem) {
        if (!hasStarts || frame === blockFrame) {
          const node = itemOffsets.length
          itemOffsets.push(p); itemNext.push(hasStarts ? blockHead : page[base + 16])
          if (hasStarts) blockHead = node
          else page[base + 16] = node
        } else if (!warnedBlock) {
          warnings.push('item outside its Frame Start/Bookend block'); warnedBlock = true
        }
      } else if (isBookend) {
        if (hasStarts && frame === blockFrame) {
          // Even zero replaces the preceding emission: an empty corrected frame
          // must erase speculative projectiles from the previous simulation.
          page[base + 16] = blockHead; blockFrame = null; blockHead = 0
        } else if (hasStarts && !warnedBlock) {
          warnings.push('Frame Bookend does not match Frame Start'); warnedBlock = true
        }
      } else if (isFod) {
        page[base + 17 + b[p + 4]] = p
      } else if (isStadium) page[base + 19] = p
    } else if (cmd === 0x39) {
      const lras = atLeast(version, 2) && size >= 2 ? v.getInt8(p + 1) : -1
      gameEnd = { method: b[p], lrasInitiator: lras >= 0 && lras <= 3 ? lras : null }
    }
    // Known future commands and message splitter (0x10) are ordinary sized events.
    pos = p + size
  }
  if (blockFrame !== null && itemsAllowed && !warnedBlock) warnings.push('incomplete item block; keeping last completed block')
  const n = index.first === Infinity ? 0 : index.last - index.first + 1
  const ports = start.players.map(({ port }) => ({ port,
    leader: fighter(h, index, port * 4, n),
    follower: followers[port] ? fighter(h, index, port * 4 + 2, n) : null }))
  const stage = { fod: [], stadium: [] }
  const frameSeeds = new Array(n).fill(null), sceneFrames = new Array(n).fill(null)
  for (let i = 0; i < n; i++) {
    const frame = index.first + i
    const start = index.get(frame, 20)
    if (start) {
      frameSeeds[i] = v.getUint32(start + 4)
      if (atLeast(version, 3, 10) && sizes[0x3A] >= 12) sceneFrames[i] = v.getUint32(start + 8)
    }
    for (let platform = 0; platform < 2; platform++) {
      const p = index.get(frame, 17 + platform)
      if (p) stage.fod.push([frame, platform, v.getFloat32(p + 5)])
    }
    const p = index.get(frame, 19)
    if (p) stage.stadium.push([frame, v.getUint16(p + 4), v.getUint16(p + 6)])
  }
  const rowList = hasStarts ? rows : fallbackRows
  return { version, start, firstFrame: n ? index.first : 0, lastFrame: n ? index.last : -1, n,
    rows: rowList.length, rowFids: rowList.data.slice(0, rowList.length), ports, frameSeeds, sceneFrames,
    items: itemTracks(h, index, itemOffsets, itemNext, n), stage, end: gameEnd, warnings }
}
