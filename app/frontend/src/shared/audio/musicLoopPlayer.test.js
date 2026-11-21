import test from 'node:test'
import assert from 'node:assert/strict'
import { createMusicLoopPlayer } from './musicLoopPlayer.js'

function setup(t) {
  const nodes = []
  const gain = { gain: { value: 1 }, connect() {}, disconnect() {} }
  const context = {
    currentTime: 0, destination: {}, resume: async () => {},
    createGain: () => gain,
    createBufferSource() {
      const node = { stop() { this.stopped = true }, disconnect() {}, connect(target) { this.target = target },
        start(_when, offset) { this.offset = offset } }
      nodes.push(node)
      return node
    },
  }
  const player = createMusicLoopPlayer(context, { duration: 10 }, { loopStart: 3, volume: 0.3 })
  t.after(() => player.dispose())
  return { player, context, nodes, gain }
}

test('pause/resume preserves position through the intro and multiple repeats', async t => {
  const { player, context, nodes } = setup(t)
  await player.play()
  context.currentTime = 12
  assert.equal(player.position(), 5)
  player.pause()
  context.currentTime = 30
  assert.equal(player.position(), 5)
  assert.equal(player.playing, false)
  await player.play()
  assert.equal(nodes[1].offset, 5)
  context.currentTime = 48
  assert.equal(player.position(), 9)
})

test('seeking changes the listening position without moving the loop point', async t => {
  const { player, nodes } = setup(t)
  await player.seek(8)
  assert.equal(player.playing, false)
  assert.equal(nodes.length, 0)
  await player.play()
  assert.equal(nodes[0].offset, 8)
  assert.equal(nodes[0].loopStart, 3)
  await player.seek(1)
  assert.equal(nodes[0].stopped, true)
  assert.equal(nodes[1].offset, 1)
  assert.equal(nodes[1].loopStart, 3)
})

test('adjusting the loop preserves uninterrupted playback and correct playhead timing', async t => {
  const { player, context, nodes } = setup(t)
  await player.play()
  context.currentTime = 12
  player.setLoopStart(2)
  assert.equal(player.position(), 5)
  assert.equal(nodes.length, 1)
  assert.equal(nodes[0].stopped, undefined)
  assert.equal(nodes[0].loopStart, 2)
  context.currentTime = 18
  assert.equal(player.position(), 3)
})

test('rapid seek updates keep playing and only the newest offset wins', async t => {
  const { player, context, nodes } = setup(t)
  await player.play()
  const resumes = []
  context.resume = () => new Promise(resolve => resumes.push(resolve))
  const first = player.seek(4)
  const last = player.seek(7)
  resumes[0]()
  resumes[1]()
  await Promise.all([first, last])
  assert.equal(nodes.length, 2)
  assert.equal(nodes.at(-1).offset, 7)
  assert.equal(player.playing, true)
})

test('pause and disposal cancel a pending play request', async t => {
  const { player, context, nodes } = setup(t)
  let resume
  context.resume = () => new Promise(resolve => { resume = resolve })
  const first = player.play()
  player.pause()
  resume()
  await first
  assert.equal(nodes.length, 0)
  const second = player.play()
  player.dispose()
  resume()
  await second
  assert.equal(nodes.length, 0)
})

test('volume changes use gain without changing loop or transport', async t => {
  const { player, nodes, gain } = setup(t)
  assert.equal(gain.gain.value, 0.3)
  await player.play()
  player.setVolume(0)
  assert.equal(gain.gain.value, 0)
  assert.equal(nodes[0].target, gain)
  assert.equal(nodes[0].loopStart, 3)
  assert.equal(player.playing, true)
})
