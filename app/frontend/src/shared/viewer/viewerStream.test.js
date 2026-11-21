import test from 'node:test'
import assert from 'node:assert/strict'
import { createViewerFrameDecoder, viewerCapabilityWarning, viewerSupports } from './viewerStream.js'
import { createViewerSurface } from './viewerSurface.js'

const flush = () => new Promise(resolve => setImmediate(resolve))
function setup() {
  const drawn = [], consumed = [], errors = [], decodes = []
  const canvas = { width: 640, height: 480, getContext: () => ({ drawImage: (...args) => drawn.push(args) }) }
  let current = true
  const decoder = createViewerFrameDecoder({ viewerSessionId: 'ours', getCanvas: () => canvas,
    isCurrent: () => current, consume: metadata => consumed.push(metadata.frameId), onError: error => errors.push(error),
    decode: buffer => new Promise((resolve, reject) => decodes.push({ buffer, resolve, reject })) })
  const frame = id => decoder.receive(`jpeg-${id}`, { viewerSessionId: 'ours', frameId: id })
  const bitmap = () => ({ width: 100, height: 100, closed: 0, close() { this.closed++ } })
  return { decoder, frame, bitmap, canvas, drawn, consumed, errors, decodes, supersede: () => { current = false } }
}

test('decodes only owned frames, draws at render size, closes then acknowledges', async () => {
  const s = setup()
  s.decoder.receive('foreign', { viewerSessionId: 'theirs', frameId: 100 })
  s.decoder.receive('untagged')
  assert.equal(s.decodes.length, 0)
  assert.deepEqual(s.consumed, [])
  s.frame(1)
  assert.deepEqual(s.consumed, [])
  const bitmap = s.bitmap()
  s.decodes[0].resolve(bitmap)
  await flush()
  assert.deepEqual(s.drawn, [[bitmap, 0, 0, 640, 480]])
  assert.equal(bitmap.closed, 1)
  assert.deepEqual(s.consumed, [1])
})

test('retains the latest pending frame and fences older decodes and out-of-order frames', async () => {
  const s = setup()
  s.frame(1); s.frame(2); s.frame(3)
  assert.equal(s.decodes.length, 1)
  assert.deepEqual(s.consumed, [2])
  const first = s.bitmap()
  s.decodes[0].resolve(first)
  await flush()
  assert.equal(s.drawn.length, 0)
  assert.equal(first.closed, 1)
  assert.equal(s.decodes[1].buffer, 'jpeg-3')
  const latest = s.bitmap()
  s.decodes[1].resolve(latest)
  await flush()
  s.frame(0)
  assert.equal(s.drawn.length, 1)
  assert.equal(s.drawn[0][0], latest)
  assert.deepEqual(s.consumed, [2, 1, 3, 0])
})

test('cleanup settles both active and pending immediately, late bitmap is closed without a second ack', async () => {
  const s = setup()
  s.frame(1); s.frame(2)
  s.decoder.dispose(); s.decoder.dispose()
  assert.deepEqual(s.consumed, [1, 2])
  const bitmap = s.bitmap()
  s.decodes[0].resolve(bitmap)
  await flush()
  assert.equal(bitmap.closed, 1)
  assert.equal(s.drawn.length, 0)
  assert.equal(s.decodes.length, 1)
  assert.deepEqual(s.consumed, [1, 2])
})

test('decode and drawing failures settle and allow the next frame through', async () => {
  const s = setup()
  s.frame(1)
  s.decodes[0].reject(new Error('invalid JPEG'))
  await flush()
  assert.deepEqual(s.consumed, [1])
  s.canvas.getContext = () => ({ drawImage() { throw new Error('draw failed') } })
  s.frame(2)
  const bitmap = s.bitmap()
  s.decodes[1].resolve(bitmap)
  await flush()
  assert.equal(bitmap.closed, 1)
  assert.deepEqual(s.consumed, [1, 2])
  assert.match(s.errors[0].message, /invalid JPEG/)
  assert.match(s.errors[1].message, /draw failed/)
})

test('a superseded session cannot draw or report a late decode error', async () => {
  const s = setup()
  s.frame(1); s.frame(2)
  s.supersede()
  s.decodes[0].reject(new Error('old decode'))
  await flush()
  assert.equal(s.drawn.length, 0)
  assert.equal(s.errors.length, 0)
  assert.deepEqual(s.consumed, [1, 2])
})

test('resize and hidden/show invalidate an old decode even if dimensions return to the same size', async () => {
  const s = setup()
  let visible = true, width = 640
  const surface = createViewerSurface({ element: { getBoundingClientRect: () => ({ width, height: 480 }) },
    getCanvas: () => s.canvas, streaming: true, getDpr: () => 1, isVisible: () => visible,
    resize() {}, hide() {}, show() {} })
  surface.update()
  s.frame(1)
  width = 320; surface.update(); width = 640; surface.update()
  s.decodes[0].resolve(s.bitmap())
  await flush()
  assert.equal(s.drawn.length, 0)
  s.frame(2)
  visible = false; surface.update(); visible = true; surface.update()
  s.decodes[1].resolve(s.bitmap())
  await flush()
  assert.equal(s.drawn.length, 0)
  assert.deepEqual(s.consumed, [1, 2])
})

test('missing or hidden canvas discards and acknowledges without decoding', async () => {
  const consumed = []
  const decoder = createViewerFrameDecoder({ viewerSessionId: 'ours', getCanvas: () => null,
    consume: metadata => consumed.push(metadata.frameId), decode: () => { throw new Error('must not decode') } })
  decoder.receive('jpeg', { viewerSessionId: 'ours', frameId: 1 })
  await flush()
  assert.deepEqual(consumed, [1])
})

test('capability messages explain unsupported CSP and animation ticks', () => {
  assert.match(viewerCapabilityWarning({ cspMode: false, animationTicks: false }, { cspMode: true }), /CSP camera mode or live animation frame updates/)
  assert.equal(viewerCapabilityWarning({ cspMode: false, animationTicks: true }), '')
})

test('a renderer takes a message only when it announced protocol 2 and lists it', () => {
  const caps = { type: 'capabilities', protocolVersion: 2, messages: ['loadDat', 'setVertexColors'] }
  assert.equal(viewerSupports(caps, 'loadDat'), true)
  assert.equal(viewerSupports(caps, 'setLightColors'), false)
  assert.equal(viewerSupports({ type: 'capabilities', protocolVersion: 1, animationTicks: true }, 'loadDat'), false)
  assert.equal(viewerSupports({ protocolVersion: 1, messages: ['loadDat'] }, 'loadDat'), false)
  assert.equal(viewerSupports(null, 'loadDat'), false)
})
