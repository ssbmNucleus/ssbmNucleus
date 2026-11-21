import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import * as protocol from './paintProtocol.js'

// Exercise the real load effect and message handler. Image decoding is held
// explicitly so navigation and local-edit races are deterministic.
const hookSource = (await readFile(new URL('./useTextureCanvasLoad.js', import.meta.url), 'utf8'))
  .replace("import { useEffect } from 'react'", 'const useEffect = callback => globalThis.__textureLoadEffect(callback)')
  .replace(/import .* from '.\/paintProtocol'/, 'const { textureKey, textureAddress, shouldReloadPaintCanvas } = globalThis.__textureProtocol')
const handlerSource = (await readFile(new URL('./skinCreatorViewerMessages.js', import.meta.url), 'utf8'))
  .replace(/import .* from '..\/..\/shared\/viewer\/viewerStream'/, 'const viewerCapabilityWarning = () => null')
  .replace(/import .* from '..\/..\/shared\/viewer\/viewerMessages'/, 'const handleViewerControlMessage = () => false')
  .replace(/import .* from '.\/datUtils'/, 'const settleExportDat = () => {}')
  .replace(/import .* from '.\/paintProtocol'/, 'const { normalizePaintTextures, isCurrentTextureReply } = globalThis.__textureProtocol')
globalThis.__textureProtocol = protocol
const asModule = source => import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
const { useTextureCanvasLoad } = await asModule(hookSource)
const { createViewerMessageHandler } = await asModule(handlerSource)
const { createTextureFileActions } = await asModule((await readFile(new URL('./textureFileActions.js', import.meta.url), 'utf8'))
  .replace(/import .* from '.\/paintProtocol'/, 'const { isCurrentPaintTarget } = globalThis.__textureProtocol'))
delete globalThis.__textureProtocol

function setup(t, { paired = false, thumbnail = 'small-preview' } = {}) {
  const images = [], sent = [], errors = [], adopts = [], draws = [], timers = new Map()
  let cleanup, timer = 0, request = 0
  const ref = current => ({ current })
  const original = Object.fromEntries(['Image', 'window', 'setTimeout', 'clearTimeout', '__textureLoadEffect'].map(key => [key, globalThis[key]]))
  globalThis.__textureLoadEffect = callback => { cleanup = callback() }
  globalThis.Image = class {
    constructor() { images.push(this); this.naturalWidth = 512; this.naturalHeight = 512 }
    finish() { this.onload?.() }
  }
  globalThis.window = { electron: { viewerSend: command => { sent.push(command); return true } } }
  globalThis.setTimeout = callback => { timers.set(++timer, callback); return timer }
  globalThis.clearTimeout = id => timers.delete(id)
  const tex = { index: 3, width: 512, height: 512, thumbnail, ...(paired ? { memberId: 'nana' } : {}) }
  const key = protocol.textureKey(tex)
  const canvas = { width: 8, height: 8, getContext: () => ({ drawImage: image => draws.push(image.src) }) }
  const o = {
    selectedTextureIndex: 0, modelTextures: [tex], paintCanvasRef: ref(canvas),
    editedTextures: {}, editedTexturesRef: ref({}), canvasWritesRef: ref(new Map()),
    canvasOwnerRef: ref('previous'), viewerGenerationRef: ref(2), setCanvasOwner() {},
    paintPairRef: ref(paired ? [] : null), paintSessionRef: ref('session-2'),
    paintCommand: message => ({ ...message, ...(paired ? { sessionId: 'session-2', requestId: `read-${++request}` } : {}) }),
    fullTextureRequestRef: ref(null), failViewer: error => errors.push(error.message), selectionRef: ref(key),
    layers: { adoptCanvas: (...args) => adopts.push(args) }, updateCanvasScale() {},
    lastMessageTimeRef: ref(0), materialColors: { receive: () => false }, isStage: false,
    isDrawingRef: ref(false), savingRef: ref(false),
  }
  const handler = () => createViewerMessageHandler(o)
  const reply = changes => handler()({ type: 'fullTexture', index: tex.index, data: 'original-full', width: 512, height: 512,
    ...(paired ? { memberId: 'nana', sessionId: 'session-2', requestId: o.fullTextureRequestRef.current?.requestId } : {}), ...changes })
  const load = () => { cleanup?.(); useTextureCanvasLoad(o) }
  t.after(() => { cleanup?.(); for (const [key, value] of Object.entries(original)) {
    if (value === undefined) delete globalThis[key]; else globalThis[key] = value
  } })
  return { o, key, images, sent, errors, adopts, draws, timers, canvas, reply, load, dispose: () => cleanup?.() }
}

test('single textures request original pixels, withholding paint/export ownership until full decode', async t => {
  const h = setup(t)
  h.load(); await Promise.resolve()
  assert.deepEqual(h.sent, [{ type: 'getFullTexture', index: 3 }])
  assert.equal(h.o.canvasOwnerRef.current, null)
  assert.equal(h.images.length, 0, 'never decode or seed the thumbnail')
  h.reply()
  assert.equal(h.o.canvasOwnerRef.current, null)
  h.images[0].finish()
  assert.deepEqual(h.draws, ['data:image/png;base64,original-full'])
  assert.equal(h.o.canvasOwnerRef.current, '3')
  assert.deepEqual([h.canvas.width, h.canvas.height], [512, 512])
  assert.equal(h.timers.size, 0)
  assert.equal(h.adopts[0][2], undefined, 'preserve an existing layer stack on return')
})

test('textures without a preview still load full resolution', async t => {
  const h = setup(t, { thumbnail: null }); h.load(); await Promise.resolve()
  assert.equal(h.sent.length, 1); h.reply(); h.images[0].finish()
  assert.equal(h.o.canvasOwnerRef.current, h.key)
})

test('PNG export and import stay gated while the full-resolution canvas is loading', t => {
  const h = setup(t); h.load()
  const actions = createTextureFileActions({ ...h.o, selectedTextureId: h.key })
  // The DOM/file reader are deliberately absent: neither action may reach them
  // or consume the previous selection's canvas while ownership is pending.
  assert.doesNotThrow(() => actions.exportTexture())
  assert.doesNotThrow(() => actions.importTexture({ target: { files: [{}] } }))
  assert.deepEqual(h.draws, [])
})

test('paired reads retain member addressing and reject other owner/session/request replies', async t => {
  const h = setup(t, { paired: true }); h.load(); await Promise.resolve()
  assert.deepEqual(h.sent, [{ type: 'getFullTexture', index: 3, memberId: 'nana', sessionId: 'session-2', requestId: 'read-1' }])
  for (const wrong of [{ memberId: 'popo' }, { sessionId: 'old' }, { requestId: 'old' }, { index: 4 }]) h.reply(wrong)
  assert.equal(h.images.length, 0); assert.equal(h.o.canvasOwnerRef.current, null)
  h.reply(); h.images[0].finish(); assert.equal(h.o.canvasOwnerRef.current, 'nana:3')
})

test('switching away and back invalidates old PNG decode and timeout', t => {
  const h = setup(t); h.load(); h.reply()
  const oldImage = h.images[0], oldTimeout = [...h.timers.values()][0]
  h.o.selectionRef.current = '4'; h.o.modelTextures = [{ index: 4, width: 512, height: 512 }]; h.load()
  h.o.selectionRef.current = '3'; h.o.modelTextures = [{ index: 3, width: 512, height: 512 }]; h.load()
  oldImage.finish(); oldTimeout()
  assert.deepEqual(h.draws, []); assert.deepEqual(h.errors, [])
  h.reply(); h.images[1].finish(); assert.equal(h.draws.length, 1)
})

test('closed or reconnected viewers cannot finish old reads', t => {
  const h = setup(t); h.load(); h.reply(); h.o.viewerGenerationRef.current++
  h.images[0].finish(); h.reply()
  assert.deepEqual(h.draws, []); assert.equal(h.images.length, 1)
  h.dispose(); assert.equal(h.o.fullTextureRequestRef.current, null); assert.equal(h.timers.size, 0)
})

test('closing before dispatch does not send an old read to a replacement viewer', async t => {
  const h = setup(t); h.load(); h.dispose(); await Promise.resolve()
  assert.deepEqual(h.sent, [])
})

test('local edits and active painting/saving prevent asynchronous overwrites', t => {
  const h = setup(t)
  for (const guard of ['edit', 'draw', 'save']) {
    h.load(); h.reply(); const image = h.images.at(-1)
    if (guard === 'edit') h.o.editedTexturesRef.current['3'] = 'local'
    if (guard === 'draw') h.o.isDrawingRef.current = true
    if (guard === 'save') h.o.savingRef.current = true
    image.finish()
    h.o.editedTexturesRef.current = {}; h.o.isDrawingRef.current = false; h.o.savingRef.current = false
  }
  assert.deepEqual(h.draws, [])
})

test('own stroke echoes keep ownership; external edits rebuild only their flattened base', t => {
  const h = setup(t)
  h.o.editedTextures = { '3': 'own-stroke' }; h.o.canvasWritesRef.current.set('3', 'own-stroke'); h.o.canvasOwnerRef.current = '3'
  h.load(); assert.equal(h.images.length, 0); assert.equal(h.o.canvasOwnerRef.current, '3')
  h.o.editedTextures = { '3': 'palette-recolor' }; h.load(); h.images[0].finish()
  assert.deepEqual(h.draws, ['palette-recolor']); assert.deepEqual(h.adopts[0][2], { reset: true })
  assert.equal(h.sent.length, 0)
})

test('missing data, native failure and bad dimensions surface errors without editable preview pixels', t => {
  const h = setup(t)
  for (const invalid of [{ data: '' }, { error: 'native read failed' }, { success: false }]) {
    h.load(); h.reply(invalid); assert.equal(h.o.canvasOwnerRef.current, null)
  }
  h.load(); h.reply({ width: 128 }); h.images[0].finish()
  h.load(); h.reply(); h.images[1].naturalWidth = 128; h.images[1].finish()
  assert.equal(h.errors.length, 5); assert.deepEqual(h.draws, []); assert.equal(h.timers.size, 0)
})

test('decode failure, timeout and disconnected sends leave no usable thumbnail', async t => {
  const h = setup(t); h.load(); h.reply(); h.images[0].onerror()
  h.load(); [...h.timers.values()][0]()
  window.electron.viewerSend = () => false; h.load()
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
  assert.equal(h.errors.length, 3); assert.deepEqual(h.draws, []); assert.equal(h.o.canvasOwnerRef.current, null)
})

test('duplicate full-texture replies cannot reset a layer stack twice', t => {
  const h = setup(t); h.load(); h.reply(); h.reply(); assert.equal(h.images.length, 1)
  h.images[0].finish(); h.reply(); assert.equal(h.images.length, 1); assert.equal(h.adopts.length, 1)
})
