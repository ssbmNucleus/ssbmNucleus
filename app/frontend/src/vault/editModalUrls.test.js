import test from 'node:test'
import assert from 'node:assert/strict'

import { heldPortraitSrc, resolveDisplayCspUrl } from './editModalUrls.js'

const backendBase = 'http://127.0.0.1:5000'

test('keeps an absolute active custom CSP URL unchanged', () => {
  const url = `${backendBase}/storage/Fox/alt_hd.png`
  assert.equal(resolveDisplayCspUrl({
    active_csp_id: 'alt-1',
    alternateCsps: [
      { id: 'alt-1', url: `${backendBase}/storage/Fox/alt.png`, poseName: 'Custom', isHd: false },
      { id: 'alt-hd', url, poseName: 'Custom', isHd: true },
    ],
  }, backendBase), url)
})

test('prefixes root-relative active and main CSP URLs once', () => {
  assert.equal(resolveDisplayCspUrl({
    active_csp_id: 'alt-1',
    alternateCsps: [{ id: 'alt-1', url: '/storage/Fox/alt.png', poseName: null, isHd: false }],
  }, backendBase), `${backendBase}/storage/Fox/alt.png`)

  assert.equal(resolveDisplayCspUrl({
    cspUrl: '/storage/Fox/main_csp.png',
    has_hd_csp: false,
  }, backendBase), `${backendBase}/storage/Fox/main_csp.png`)
})

test('holds a just-saved portrait only while its stamp is the live one', () => {
  const applied = { dataUri: 'data:image/png;base64,AAA', stamp: 42 }
  assert.equal(heldPortraitSrc(applied, 42), applied.dataUri)
  assert.equal(heldPortraitSrc(applied, 43), null)
  assert.equal(heldPortraitSrc(null, 42), null)
})
