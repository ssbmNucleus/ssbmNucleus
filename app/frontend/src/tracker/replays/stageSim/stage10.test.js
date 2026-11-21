import test from 'node:test'
import assert from 'node:assert/strict'
import simulate, { sampleCollision } from './stage10.js'

const fixture = {
  range: [0, 8], tracks: [[[0, 0, 0], [8, 8, 16]]],
  groups: [{ track: 0, base: [[-2, 1], [2, 1]], lines: [[49, 0, 1]],
    flags: [[0, 1], [3, 0], [5, 257], [7, 2]] }],
}

test('visibility and current kind change on the exact command frame', () => {
  assert.deepEqual(sampleCollision(fixture, 2).lines, [[49, 1, 0, 5, 4, 5]])
  assert.deepEqual(sampleCollision(fixture, 3).lines, [])
  assert.deepEqual(sampleCollision(fixture, 4).lines, [])
  assert.deepEqual(sampleCollision(fixture, 5).lines, [[49, 257, 3, 11, 7, 11]])
  assert.equal(sampleCollision(fixture, 7).lines[0][1], 2)
})

test('affine and deforming tracks retain original endpoint order', () => {
  const data = { range: [0, 2], tracks: [[[0, 0, 1, -1, 0, 10, 20]], [[0, 7, 8, 9, 10]]],
    groups: [
      { track: 0, affine: true, base: [[2, 3], [4, 5]], lines: [[1, 0, 1]], flags: [[0, 8]] },
      { track: 1, lines: [[2, 1, 0]], flags: [[0, 1]] },
    ] }
  assert.deepEqual(sampleCollision(data, 1).lines, [[1, 8, 7, 22, 5, 24], [2, 1, 9, 10, 7, 8]])
})

test('bounded tracks never clamp or loop', () => {
  assert.equal(sampleCollision(fixture, -1), null)
  assert.equal(sampleCollision(fixture, 9), null)
  assert.equal(sampleCollision(fixture, NaN), null)
})

test('a verified loop preserves its startup prefix and wraps only the suffix', () => {
  const data = { ...fixture, loop: 4, loopStart: 4 }
  assert.deepEqual(sampleCollision(data, 2), sampleCollision(fixture, 2))
  assert.deepEqual(sampleCollision(data, 9), sampleCollision(fixture, 5))
  assert.deepEqual(sampleCollision(data, 1001), sampleCollision(fixture, 5))
  assert.equal(sampleCollision(data, -1), null)
})

test('absolute frame sampling is seed independent and seek order independent', () => {
  const a = { meta: { stage: 10, start_frame: 75 } }
  const b = { meta: { stage: 10, start_frame: 74 }, frames: { seed: [[123, 456]] } }
  const first = simulate(a, 0)
  assert.ok(first.complete && first.replace)
  assert.deepEqual(simulate(b, 1), first)
  simulate(a, 1000)
  const raw={...a,meta:{...a.meta,v:5}}
  assert.ok(simulate(raw, 1002).lines.every(line => !(line[1] & 256)))
  assert.deepEqual(simulate(a, 0), first)
  assert.equal(simulate(a, 0), simulate(a, 0))
  assert.ok(simulate(a, 6001)?.lines.length)
  assert.deepEqual(simulate(a, 30000), simulate(a, 30000-6012))
  assert.equal(simulate({ meta: { stage: 24, start_frame: 75 } }, 0), null)
  assert.equal(simulate(a, -1), null)
  assert.equal(simulate(a, 0.5), null)
})
