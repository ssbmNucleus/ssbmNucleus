import test from 'node:test'
import assert from 'node:assert/strict'

test('patch downloads authenticate both requests and surface failures before browser handoff', async () => {
  const previous = { window: globalThis.window, document: globalThis.document, fetch: globalThis.fetch }
  const links = []
  const requests = []
  let status = 200
  globalThis.window = { electron: { backendPort: 51234, backendToken: 'patch-test-token' } }
  globalThis.document = {
    createElement: () => ({ click() { this.clicked = true }, remove() { this.removed = true } }),
    body: { appendChild(link) { links.push(link) } },
  }
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options })
    return new Response(null, { status, headers: { 'content-type': 'application/octet-stream' } })
  }
  try {
    const { downloadPatchFile } = await import('./patchDownload.js')
    // config.js reads the token once, when it is first imported. Under
    // --experimental-test-isolation=none another test file may already have
    // imported it, so check against the token it actually holds.
    const { BACKEND_TOKEN } = await import('../../shared/config/config.js')
    assert.ok(BACKEND_TOKEN, 'a backend token is configured')
    await downloadPatchFile('patch-1')
    assert.equal(requests[0].options.method, 'HEAD')
    assert.equal(requests[0].options.headers.get('X-Nucleus-Token'), BACKEND_TOKEN)
    const downloadUrl = new URL(links[0].href)
    assert.equal(downloadUrl.pathname, '/api/mex/xdelta/download-patch/patch-1')
    assert.equal(downloadUrl.searchParams.get('_nucleus_token'), BACKEND_TOKEN)
    assert.equal(links[0].download, '')
    assert.equal(links[0].clicked, true)
    assert.equal(links[0].removed, true)
    for (status of [401, 404, 500]) {
      await assert.rejects(downloadPatchFile('patch-1'), new RegExp(`HTTP ${status}`))
      assert.equal(links.length, 1)
    }
    status = 200
    await downloadPatchFile('patch-1')
    assert.equal(links.length, 2) // an earlier failure does not trap retries
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[key]
      else globalThis[key] = value
    }
  }
})
