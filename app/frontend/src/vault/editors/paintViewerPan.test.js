import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { bindViewerInput, cameraPanStep } from '../../shared/viewer/viewerInput.js'
import { paintPanStep, readViewerCamera, PAN_STEP, STAGE_PAN_STEP } from './paintViewerPan.js'

const fox = { z: -22.4226398, fovRadians: 1.22173047 }

function target() {
  const listeners = new Map()
  return { listeners,
    addEventListener(type, callback) { listeners.set(type, callback) },
    removeEventListener(type) { listeners.delete(type) },
    emit(type, data = {}) { listeners.get(type)?.({ target: this, preventDefault() {}, ...data }) },
  }
}

test('the Texture Lab pans by the renderer camera, per pixel of the view\'s longer side, as the workbench does', () => {
  const tall = { clientWidth: 300, clientHeight: 400 }, wide = { clientWidth: 800, clientHeight: 400 }
  assert.equal(paintPanStep(fox, tall, false), cameraPanStep(fox, 300, 400))
  assert.equal(paintPanStep(fox, wide, false), cameraPanStep(fox, 800, 400))
  assert.equal(paintPanStep(fox, wide, true), cameraPanStep(fox, 800, 400), 'a stage pans by its camera too')
  // Before the camera is read (or from a renderer that cannot say): the lab's own speeds, both positive.
  assert.equal(paintPanStep(null, tall, false), PAN_STEP)
  assert.equal(paintPanStep(null, tall, true), STAGE_PAN_STEP)
  assert.equal(paintPanStep(fox, null, false), PAN_STEP, 'a view with no size yet')
})

test('a right-drag moves the model with the cursor on both axes, not against it on one', () => {
  const element = target(), cameras = [], captures = new Set()
  element.focus = () => {}
  element.setPointerCapture = id => captures.add(id)
  element.hasPointerCapture = id => captures.has(id)
  element.releasePointerCapture = id => captures.delete(id)
  element.clientWidth = 300
  element.clientHeight = 400
  let camera = null
  const cleanup = bindViewerInput({ element, windowTarget: target(), documentTarget: target(),
    sendCamera: (...args) => cameras.push(args), panStep: () => paintPanStep(camera, element, false) })
  element.emit('pointerdown', { pointerId: 1, button: 2, clientX: 0, clientY: 0 })
  element.emit('pointermove', { pointerId: 1, buttons: 2, clientX: 10, clientY: 20 })
  // The old panScale -0.1 sent [0, 0, 0, -1, 2]: the model ran against the cursor across.
  assert.deepEqual(cameras.at(-1), [0, 0, 0, 10 * PAN_STEP, 20 * PAN_STEP])
  camera = fox
  element.emit('pointermove', { pointerId: 1, buttons: 2, clientX: 20, clientY: 20 })
  assert.deepEqual(cameras.at(-1), [0, 0, 0, 10 * cameraPanStep(fox, 300, 400), 0])
  cleanup()
})

test('the camera is read from the renderer, and a renderer that cannot say gives none', async () => {
  assert.deepEqual(await readViewerCamera({ viewerExportScene: async () => ({ camera: fox }) }), fox)
  assert.equal(await readViewerCamera({ viewerExportScene: async () => { throw new Error('Viewer not running') } }), null)
  assert.equal(await readViewerCamera({ viewerExportScene: async () => ({}) }), null)
  assert.equal(await readViewerCamera({}), null)
  assert.equal(await readViewerCamera(undefined), null)
})

test('the Texture Lab view pans by paintPanStep, not the old one-sign panScale', () => {
  const source = readFileSync(new URL('./SkinCreator.jsx', import.meta.url), 'utf8')
  const input = source.slice(source.indexOf('useViewerInput({'), source.indexOf('useViewerSurface({'))
  assert.match(input, /panStep: \(\) => paintPanStep\(viewerCameraRef\.current, skinCreatorCanvasRef\.current, isStage\)/)
  assert.doesNotMatch(input, /panScale/)
  assert.match(source, /readViewerCamera\(window\.electron\)/)
})
