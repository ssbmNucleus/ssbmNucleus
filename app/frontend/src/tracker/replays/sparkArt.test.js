import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

register(new URL('../../../../../tools/liteaudit/loader.mjs', import.meta.url))
const { drawArt } = await import('./sparkArt.js')
const { RecordingContext } = await import('../../../../../tools/liteaudit/recording_context.mjs')
const FX = (await import('./data/hitEffects.js')).default

const used = kind => new Set(FX.effects[kind].frames.flat().map(p => p[0]))

test('the hit effects draw the game textures, traced; shield hits and techs our own shapes', () => {
  for (const kind of ['normal', 'strong', 'fire', 'electric', 'slash', 'dark', 'ice']) {
    for (const i of used(kind)) assert.ok(FX.textures[i][3]?.length, `${kind}: texture ${FX.textures[i].slice(0, 2)} traced`)
  }
  for (const kind of ['shield', 'tech']) {
    for (const i of used(kind)) {
      const c = new RecordingContext()
      drawArt(c, FX.textures[i], [255, 255, 255], [255, 0, 0], 1, false)
      assert.ok(c.calls.some(x => x.op === 'fill' || x.op === 'stroke'), `${kind}: texture ${FX.textures[i].slice(0, 2)} has our drawing`)
    }
  }
  // the shield hit's textures are never written traced (no game art they do not draw)
  for (const i of used('shield')) assert.equal(FX.textures[i][3], undefined)
})
