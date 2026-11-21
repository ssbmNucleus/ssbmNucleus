// The renderer's Content-Security-Policy (security review 11-19, H1): what the
// built index.html carries and what it still lets through. Checked in the real
// app on the built files (file://) with zero violations: load and backend calls,
// Socket.IO, Watch Lite with its worker, the HSDRawViewer 3D viewer, fonts.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { RENDERER_CSP, RENDERER_CSP_DIRECTIVES as D, rendererCsp } from '../../rendererCsp.js'

// vite.config.js needs the __dirname Vite gives it, so it is read, not imported.
const VITE_CONFIG = readFileSync(new URL('../../vite.config.js', import.meta.url), 'utf8')

const sources = (name) => D[name].split(/\s+/)

test('only the build gets it, as the first element of <head>', () => {
  const plugin = rendererCsp()
  assert.equal(plugin.apply, 'build')
  assert.deepEqual(plugin.transformIndexHtml('<html></html>'), [{
    tag: 'meta',
    attrs: { 'http-equiv': 'Content-Security-Policy', content: RENDERER_CSP },
    injectTo: 'head-prepend',
  }])
  assert.match(VITE_CONFIG, /import \{ rendererCsp \} from '\.\/rendererCsp\.js'/)
  assert.match(VITE_CONFIG, /plugins: \[[^\]]*rendererCsp\(\)[^\]]*\]/, 'vite.config.js uses the plugin')
})

test('only the bundle runs script', () => {
  assert.deepEqual(sources('script-src'), ["'self'"])
  assert.deepEqual(sources('default-src'), ["'self'"])
  for (const name of ['object-src', 'form-action', 'frame-src']) assert.deepEqual(sources(name), ["'none'"])
  assert.deepEqual(sources('base-uri'), ["'self'"])
  assert.doesNotMatch(RENDERER_CSP, /unsafe-eval|wasm-unsafe-eval|\*;|script-src[^;]*(blob:|data:|https:)/)
})

test('what the app reaches stays open', () => {
  for (const local of ['http://127.0.0.1:*', 'ws://127.0.0.1:*', 'http://localhost:*', 'https:', 'wss:']) {
    assert.ok(sources('connect-src').includes(local), `connect-src ${local}`)
  }
  for (const name of ['img-src', 'media-src']) {
    for (const source of ["'self'", 'data:', 'blob:', 'http://127.0.0.1:*', 'https:']) {
      assert.ok(sources(name).includes(source), `${name} ${source}`)
    }
  }
  assert.deepEqual(sources('worker-src'), ["'self'", 'blob:'])
  assert.ok(sources('style-src').includes('https://fonts.googleapis.com'))
  assert.ok(sources('style-src').includes("'unsafe-inline'"), 'React inline styles')
  assert.ok(sources('font-src').includes('https://fonts.gstatic.com'))
})

test('the policy string is the directives, in order, and holds no stray separators', () => {
  assert.equal(RENDERER_CSP.split('; ').length, Object.keys(D).length)
  assert.ok(RENDERER_CSP.startsWith("default-src 'self'; script-src 'self';"))
  assert.doesNotMatch(RENDERER_CSP, /;;|\s{2}|"/)
})
