import test from 'node:test'
import assert from 'node:assert/strict'

test('media URLs authenticate only the local API and preserve existing queries', async () => {
  const previous = globalThis.window
  globalThis.window = { electron: { backendPort: 51234, backendToken: 'test-token' } }
  try {
    const { backendMediaUrl } = await import('./config.js?media-auth-test')
    const local = new URL(backendMediaUrl('/api/mex/preview?mode=door', 17))
    assert.equal(local.origin, 'http://127.0.0.1:51234')
    assert.equal(local.searchParams.get('_nucleus_token'), 'test-token')
    assert.equal(local.searchParams.get('mode'), 'door')
    assert.equal(local.searchParams.get('v'), '17')
    for (const path of ['https://example.com/api/image', 'http://127.0.0.1:9999/api/image', '/storage/image.png', 'blob:http://127.0.0.1:51234/object']) {
      assert.equal(new URL(backendMediaUrl(path)).searchParams.has('_nucleus_token'), false)
    }
  } finally {
    if (previous === undefined) delete globalThis.window
    else globalThis.window = previous
  }
})
