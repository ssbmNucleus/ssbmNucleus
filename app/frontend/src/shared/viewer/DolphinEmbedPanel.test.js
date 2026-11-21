import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'esbuild'

const realRequire = createRequire(import.meta.url)
const load = (file, resolve = () => null) => {
  const built = transformSync(readFileSync(new URL(file, import.meta.url), 'utf8'),
    { loader: 'jsx', format: 'cjs', jsx: 'automatic' }).code
  const mod = { exports: {} }
  new Function('require', 'module', 'exports', built)(name => resolve(name) || realRequire(name), mod, mod.exports)
  return mod.exports
}

const crop = load('./captureCrop.js')
const { DolphinCaptureView } = load('./DolphinEmbedPanel.jsx', name =>
  name === '../transport/api' ? { api: {} }
    : name === './screenRect' ? { elementScreenRect: () => ({}) }
      : name === './dolphinPreview' ? { startDolphinPreview: () => ({ stop() {}, popout() {} }) }
        : name === './captureCrop' ? crop : null)

// 640x480 game, 1px side borders, 31px title bar, 1px bottom border.
const client = { x: 1, y: 31, width: 640, height: 480, frameWidth: 642, frameHeight: 512 }
const render = (state, fill = false) => renderToStaticMarkup(React.createElement(DolphinCaptureView,
  { videoRef: { current: null }, state, popout: () => {}, fill }))
const videoStyle = html => /<video[^>]*style="([^"]*)"/.exec(html)[1]

test('live with a measured window: the video is placed so the title bar falls outside the stage', () => {
  const style = videoStyle(render({ status: 'live', message: '', client }))
  assert.match(style, /object-fit:fill/)
  assert.match(style, /top:-6.46%/)        // the 31px title bar sits above the stage
  assert.match(style, /height:106.67%/)
  assert.doesNotMatch(style, /inset/)      // inset:0 would undo the placement
})

test('live but unmeasured: the whole window, contained', () => {
  const style = videoStyle(render({ status: 'live', message: '', client: null }))
  assert.match(style, /object-fit:contain/)
  assert.match(style, /inset:0/)
  assert.match(style, /visibility:visible/)
})

test('before the first frame the video is hidden and the message shows', () => {
  const html = render({ status: 'starting', message: 'Waiting for Dolphin…', client })
  assert.match(videoStyle(html), /visibility:hidden/)
  assert.match(html, /Waiting for Dolphin…/)
})

test('fill mode keeps a 4:3 stage inside a size container, so the crop is not stretched', () => {
  const html = render({ status: 'live', message: '', client }, true)
  assert.match(html, /container-type:size/)
  assert.match(html, /aspect-ratio:4 \/ 3;width:min\(100cqw, calc\(100cqh \* 4 \/ 3\)\)/)
  assert.doesNotMatch(html, /min-height:160px/)   // a floor would break the 4:3 the crop assumes
})
