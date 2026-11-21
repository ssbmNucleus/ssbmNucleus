import test from 'node:test'
import assert from 'node:assert/strict'
import { bindViewerInput, cameraPanStep } from './viewerInput.js'

function target() {
  const listeners = new Map()
  return { listeners,
    addEventListener(type, callback, options) { listeners.set(type, { callback, options }) },
    removeEventListener(type) { listeners.delete(type) },
    emit(type, data = {}) {
      const event = { target: this, prevented: false, preventDefault() { this.prevented = true }, ...data }
      listeners.get(type)?.callback(event)
      return event
    }
  }
}

test('captures pointer, focuses without scrolling, ends drags on blur and cancels wheel scrolling', () => {
  const element = target(), windowTarget = target(), documentTarget = target(), cameras = [], focus = [], captures = new Set()
  element.focus = options => focus.push(options)
  element.setPointerCapture = id => captures.add(id)
  element.hasPointerCapture = id => captures.has(id)
  element.releasePointerCapture = id => captures.delete(id)
  const cleanup = bindViewerInput({ element, windowTarget, documentTarget, sendCamera: (...args) => cameras.push(args) })
  element.emit('pointerdown', { pointerId: 1, button: 0, clientX: 10, clientY: 20 })
  assert.deepEqual(focus, [{ preventScroll: true }])
  assert.equal(captures.has(1), true)
  element.emit('pointermove', { pointerId: 2, buttons: 1, clientX: 90, clientY: 90 })
  element.emit('pointermove', { pointerId: 1, buttons: 1, clientX: 20, clientY: 40 })
  assert.deepEqual(cameras, [[10, 5, 0, 0, 0]])
  windowTarget.emit('blur')
  element.emit('pointermove', { pointerId: 1, buttons: 1, clientX: 30, clientY: 60 })
  assert.equal(cameras.length, 1)
  assert.equal(captures.size, 0)
  assert.equal(element.listeners.get('wheel').options.passive, false)
  assert.equal(element.emit('wheel', { deltaY: 12 }).prevented, true)
  assert.deepEqual(cameras.at(-1), [0, 0, -0.05, 0, 0])
  element.emit('pointerdown', { pointerId: 3, button: 2, clientX: 0, clientY: 0 })
  element.emit('pointermove', { pointerId: 3, buttons: 2, clientX: 10, clientY: 10 })
  assert.deepEqual(cameras.at(-1), [0, 0, 0, 0.1, -0.1])
  documentTarget.emit('visibilitychange')
  assert.equal(captures.size, 0)
  cleanup()
  assert.equal(element.listeners.size, 0)
  assert.equal(windowTarget.listeners.size, 0)
  assert.equal(documentTarget.listeners.size, 0)
})

test('buttons inside the viewport keep their focus and pointer actions', () => {
  const element = target()
  const cleanup = bindViewerInput({ element, windowTarget: target(), documentTarget: target(),
    sendCamera() { assert.fail('button must not move camera') } })
  const button = { closest: () => true }
  assert.equal(element.emit('pointerdown', { target: button, button: 0 }).prevented, false)
  assert.equal(element.emit('wheel', { target: button, deltaY: 1 }).prevented, false)
  cleanup()
})

test('a pan with panStep keeps the model under the cursor on both axes', () => {
  const element = target(), cameras = [], captures = new Set()
  element.focus = () => {}
  element.setPointerCapture = id => captures.add(id)
  element.hasPointerCapture = id => captures.has(id)
  element.releasePointerCapture = id => captures.delete(id)
  let step = 0.05
  const cleanup = bindViewerInput({ element, windowTarget: target(), documentTarget: target(),
    sendCamera: (...args) => cameras.push(args), panScale: -0.1, panStep: () => step })
  element.emit('pointerdown', { pointerId: 1, button: 2, clientX: 0, clientY: 0 })
  // The renderer adds deltaX as it is and draws Y downwards: right and down move the model right and down.
  element.emit('pointermove', { pointerId: 1, buttons: 2, clientX: 10, clientY: 20 })
  assert.deepEqual(cameras.at(-1), [0, 0, 0, 0.5, 1])
  element.emit('pointermove', { pointerId: 1, buttons: 2, clientX: 0, clientY: 0 })
  assert.deepEqual(cameras.at(-1), [0, 0, 0, -0.5, -1])
  // Read at each move: a camera read meanwhile changes the next step.
  step = 0.1
  element.emit('pointermove', { pointerId: 1, buttons: 2, clientX: 10, clientY: 0 })
  assert.deepEqual(cameras.at(-1), [0, 0, 0, 1, 0])
  const sent = cameras.length
  step = null
  element.emit('pointermove', { pointerId: 1, buttons: 2, clientX: 20, clientY: 0 })
  assert.equal(cameras.length, sent, 'no step known: no move')
  cleanup()
})

test('the pan step is the span the camera sees at the model, per pixel of the longer side', () => {
  // Fox's CSP scene: 22.42 units away at a 70 degree field of view, in a 300 x 400 px view.
  const fox = cameraPanStep({ z: -22.4226398, fovRadians: 1.22173047 }, 300, 400)
  assert.ok(Math.abs(fox - 2 * 22.4226398 * Math.tan(1.22173047 / 2) / 400) < 1e-12)
  assert.ok(fox > 0.07 && fox < 0.08)
  // Bowser's: 1747 away at 2 degrees, so about twice as much per pixel.
  const bowser = cameraPanStep({ z: -1746.71631, fovRadians: 0.0349065848 }, 300, 400)
  assert.ok(bowser > 0.15 && bowser < 0.16)
  // Wider than tall, the field of view is the width's (the renderer narrows the vertical one by the aspect).
  assert.equal(cameraPanStep({ z: -22.4226398, fovRadians: 1.22173047 }, 800, 400), fox / 2)
  assert.equal(cameraPanStep({ z: -22.4226398, fovRadians: 1.22173047 }, undefined, 400), fox, 'width not known')
  assert.equal(cameraPanStep(null, 300, 400), null)
  assert.equal(cameraPanStep({ z: -20, fovRadians: 1 }, 0, 0), null, 'a view with no size yet')
  assert.equal(cameraPanStep({ z: 0, fovRadians: 1 }, 300, 400), null)
  assert.equal(cameraPanStep({ z: -20, fovRadians: 4 }, 300, 400), null)
})
