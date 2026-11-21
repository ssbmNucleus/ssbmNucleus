import test from 'node:test'
import assert from 'node:assert/strict'
import { createViewerSurface, viewerRenderSize } from './viewerSurface.js'

test('render dimensions use fractional DPI and never return a zero-sized surface', () => {
  assert.deepEqual(viewerRenderSize({ width: 300.5, height: 200.25 }, 1.5), { width: 451, height: 300 })
  assert.equal(viewerRenderSize({ width: 0, height: 200 }), null)
  assert.equal(viewerRenderSize({ width: NaN, height: 200 }), null)
})

test('render dimensions uniformly cap the longest edge at 2048 for wide and tall high-DPI views', () => {
  assert.deepEqual(viewerRenderSize({ width: 2560, height: 720 }, 2), { width: 2048, height: 576 })
  assert.deepEqual(viewerRenderSize({ width: 720, height: 2560 }, 2), { width: 576, height: 2048 })
  assert.deepEqual(viewerRenderSize({ width: 1920, height: 1080 }, 1.5), { width: 2048, height: 1152 })
  assert.deepEqual(viewerRenderSize({ width: 1024, height: 512 }, 2), { width: 2048, height: 1024 })
})

test('stream canvas and resize command share the same aspect-preserving capped dimensions', () => {
  const sizes = [], canvas = { width: 0, height: 0 }
  const surface = createViewerSurface({ element: {}, getCanvas: () => canvas,
    streaming: true, getDpr: () => 2, isVisible: () => true,
    resize: (...args) => sizes.push(args), show() {}, hide() {} })
  surface.update({ width: 2560, height: 720 })
  assert.deepEqual(sizes, [[0, 0, 2048, 576]])
  assert.deepEqual(canvas, { width: 2048, height: 576 })
})

test('ResizeObserver layout dimensions take precedence over an animated or transformed bounding box', () => {
  const sizes = []
  const surface = createViewerSurface({ element: { getBoundingClientRect() { throw new Error('must use layout dimensions') } },
    getCanvas: () => null, streaming: true, getDpr: () => 1.5, isVisible: () => true,
    resize: (...args) => sizes.push(args), show() {}, hide() {} })
  surface.update({ width: 600.5, height: 400.25 })
  assert.deepEqual(sizes, [[0, 0, 901, 600]])
})

test('stream resize ignores desktop movement, deduplicates size, and pauses/resumes hidden boxes', () => {
  let rect = { x: 20, y: 10, width: 300, height: 200 }, dpr = 2, visible = true
  const commands = [], canvas = { width: 0, height: 0 }
  const surface = createViewerSurface({ element: { getBoundingClientRect: () => rect }, getCanvas: () => canvas,
    streaming: true, screenRect: () => { throw new Error('stream must not read desktop coordinates') },
    getDpr: () => dpr, isVisible: () => visible, resize: (...args) => commands.push(['resize', ...args]),
    show: () => commands.push(['show']), hide: () => commands.push(['hide']) })
  surface.update()
  rect.x = 800; surface.update()
  assert.deepEqual(commands, [['resize', 0, 0, 600, 400], ['show']])
  visible = false; surface.update(); surface.update()
  visible = true; surface.update()
  assert.deepEqual(commands.slice(2), [['hide'], ['show']])
  rect.width = 0; surface.update()
  assert.deepEqual(commands.at(-1), ['hide'])
  assert.equal(canvas.width, 600)
  rect.width = 400; dpr = 1.25; surface.update()
  assert.deepEqual(commands.slice(-2), [['resize', 0, 0, 500, 250], ['show']])
  assert.deepEqual(canvas, { width: 500, height: 250 })
})

test('legacy transport uses desktop rectangle only when visible and never parks hidden surfaces', () => {
  let visible = true
  const commands = []
  const surface = createViewerSurface({ element: { getBoundingClientRect: () => ({ width: 300, height: 200 }) },
    getCanvas: () => null, streaming: false, getDpr: () => 1, isVisible: () => visible,
    screenRect: () => ({ x: -400, y: 100, width: 600, height: 400 }),
    resize: (...args) => commands.push(args), show() {}, hide: () => commands.push('hide') })
  surface.update(); visible = false; surface.update()
  assert.deepEqual(commands, [[-400, 100, 600, 400], 'hide'])
})
