import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

register(new URL('../../../../../tools/liteaudit/loader.mjs', import.meta.url))
const { bodyFlash, flashFill, flashAnim } = await import('./hitFlash.js')
const FLASH = (await import('./data/hitFlash.js')).default
await import('./meleeStages.js')   // hydrates the hit tables hitEvents needs

// Falco (port 0, cid 22) shines Fox (port 1, cid 1) on frame 10: an electric hit
// (Falco's SpecialLwStart hitbox, element 2), hitstun `stun`. Fox's state
// changes on `turns`.
function bundle({ stun = 14, turns = [] } = {}) {
  const n = 80, row = v => Array.from({ length: n }, () => v)
  const pct = Array.from({ length: n }, (_, i) => (i >= 10 ? 8 : 0))
  const lag = Array.from({ length: n }, (_, i) => (i >= 10 && i < 14 ? 4 : 0))
  const foxState = Array.from({ length: n }, (_, i) => (i < 10 ? 14 : 76 + turns.filter(t => i >= t).length))
  const falcoState = Array.from({ length: n }, (_, i) => (i >= 9 && i < 20 ? 360 : 14))
  const falcoAge = Array.from({ length: n }, (_, i) => (i >= 9 && i < 20 ? i - 9 : 0))
  return {
    meta: { n, stage: 32, start_frame: 0, players: [{}, {}] },
    frames: {
      cid: [row(22), row(1)], x: [row(0), row(6)], y: [row(0), row(0)], dir: [row(1), row(-1)],
      state: [falcoState, foxState], age: [falcoAge, row(1)], pct: [row(0), pct],
      hitlag: [row(0), lag], hitstun: [row(0), row(stun)], hitby: [row(-1), row(0)],
    },
    items: [],
  }
}
const hex = c => c && c.map(v => v.toString(16).padStart(2, '0')).join('')

test('the colour animation by element and knockback class', () => {
  assert.equal(flashAnim(0, 80, 88), 4, 'normal: one animation for every class')
  assert.equal(flashAnim(1, 5, 88), 11)
  assert.equal(flashAnim(2, 14, 76), 16, 'electric, hitstun 10-21: class 1')
  assert.equal(flashAnim(2, 39, 90), 18, 'hitstun 32 and up: class 3')
  assert.equal(flashAnim(13, 0, 88), 35)
  assert.equal(flashAnim(1, 0, 185), 14, 'a hit while lying down: class 3')
  assert.deepEqual(FLASH.classes, [10, 21, 32])
})

test('an electric hit flashes blue and white on alternate frames, as RAM showed', () => {
  // playback Dolphin, Fighter +0x408 on Falco's electric hit (hitstun 14,
  // animation 16): 0000945a on the hit frame, then ffffff46, alternating
  const b = bundle()
  assert.equal(bodyFlash(b, 1, 9), null)
  assert.equal(hex(bodyFlash(b, 1, 10)), '0000945a')
  assert.equal(hex(bodyFlash(b, 1, 11)), 'ffffff46')
  assert.equal(hex(bodyFlash(b, 1, 12)), '0000945a')
  assert.equal(bodyFlash(b, 0, 12), null, 'the attacker does not flash')
  // 32 steps in all (16 loops of 2)
  assert.equal(FLASH.anims[16].length, 32)
  assert.ok(bodyFlash(b, 1, 10 + 31))
  assert.equal(bodyFlash(b, 1, 10 + 32), null)
})

test('a change of state steps the animation once more', () => {
  // RAM: the frame Falco left hitstun (76 -> 42) repeated the white of the frame before
  const b = bundle({ turns: [14] })
  assert.equal(hex(bodyFlash(b, 1, 13)), 'ffffff46')
  assert.equal(hex(bodyFlash(b, 1, 14)), 'ffffff46')
  assert.equal(hex(bodyFlash(b, 1, 15)), '0000945a')
  assert.ok(bodyFlash(b, 1, 10 + 30))
  assert.equal(bodyFlash(b, 1, 10 + 31), null, 'and ends a frame sooner')
})

test('the fill is blended to the flash by its alpha', () => {
  const b = bundle()
  // 0x5a = 90: #ff7a66 x (1 - 90/255) + #000094 x 90/255
  assert.equal(flashFill(b, 1, 10, '#ff7a66'), '#a54f76')
  assert.equal(flashFill(b, 1, 9, '#ff7a66'), '#ff7a66')
  assert.equal(flashFill(b, 1, 10, 'red'), 'red', 'a colour it cannot read stays as it is')
})

test("a throw's release flashes white, a step ahead of a hit", () => {
  // Fox thrown (ThrownF 239) until 30, released into DamageFlyN at 30 with 7%
  const b = bundle()
  const st = b.frames.state[1], pct = b.frames.pct[1]
  for (let i = 20; i < 80; i++) { st[i] = i < 30 ? 239 : 88; pct[i] = i < 30 ? 8 : 15 }
  // RAM (a throw on Pokemon Stadium): white at alpha 170 on the release frame already
  assert.equal(hex(bodyFlash(b, 1, 30)), 'ffffffaa')
  assert.equal(hex(bodyFlash(b, 1, 36)), 'ffffff14')
  assert.equal(bodyFlash(b, 1, 37), null)
})

test('a darkness hit dims the body while its light is on, and tints it', () => {
  // Ganondorf (cid 25) up-tilts Fox at frame 10: AttackHi3 (58) action frame
  // 20, a darkness hitbox (element 13) at (3, 12) r 3.5; hitstun 86: class 3
  const b = bundle({ stun: 86 })
  b.frames.cid[0] = b.frames.cid[0].map(() => 25)
  b.frames.state[0] = b.frames.state[0].map((_, i) => (i >= 9 && i < 20 ? 58 : 14))
  b.frames.age[0] = b.frames.age[0].map((_, i) => (i >= 9 && i < 20 ? i + 10 : 0))
  b.frames.x[1] = b.frames.x[1].map(() => 3)
  assert.equal(hex(bodyFlash(b, 1, 10)), '5000b478', 'animation 38, step 1 (RAM: Ganondorf on Falco)')
  assert.deepEqual(Object.keys(FLASH.lights).sort(), ['35', '36', '37', '38'])
  // #5aa0ff dimmed to half, then 120/255 of the way to #5000b4
  const half = [0x5a, 0xa0, 0xff].map(v => v * 0.5), a = 0x78 / 255
  const want = '#' + half.map((v, j) => Math.round(v * (1 - a) + [0x50, 0x00, 0xb4][j] * a).toString(16).padStart(2, '0')).join('')
  assert.equal(flashFill(b, 1, 10, '#5aa0ff'), want)
  // an electric hit has no light: the colour alone
  assert.equal(flashFill(bundle(), 1, 10, '#ff7a66'), '#a54f76')
})
